"""HTTP and WebSocket surface of the local service.

Bound to 127.0.0.1 only. Every request must carry the one-time token
that the host process handed over on startup.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import (
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .. import __version__
from .. import atlas, runtime
from ..picker import picker
from ..picker import snapshot as snapshot_view
from ..registry import model as registry_model
from ..registry import resolve as registry_resolve
from ..registry import store as registry_store
from ..runtime import browser_install
from ..storage import config as config_store
from ..storage import database, secrets
from .events import bus

HEARTBEAT_SECONDS = 15.0
_started_at = time.monotonic()


_build: str = ""


def build_stamp() -> str:
    """Which state of the code this service is running.

    The host process compares this with what it expects and refuses to
    adopt a service that still runs older code. Running from source that
    is the newest change time below the package; as a packaged program
    the sources cannot change, so the version is enough.
    """
    global _build
    if _build:
        return _build
    if getattr(sys, "frozen", False):
        _build = __version__
        return _build
    root = Path(__file__).resolve().parent.parent
    newest = 0
    for entry in root.rglob("*"):
        if "__pycache__" in entry.parts or not entry.is_file():
            continue
        try:
            newest = max(newest, int(entry.stat().st_mtime))
        except OSError:
            continue
    _build = str(newest)
    return _build


def create_app(token: str) -> FastAPI:
    app = FastAPI(title="local service", version=__version__, docs_url=None, redoc_url=None)

    # The user interface runs from a different origin during development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:1420", "http://127.0.0.1:1420", "tauri://localhost"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def authorised(x_auth_token: Optional[str] = Header(default=None)) -> None:
        if not x_auth_token or not hmac.compare_digest(x_auth_token, token):
            raise HTTPException(status_code=401, detail="unauthorized")

    guard = [Depends(authorised)]

    # ------------------------------------------------------------------ state

    @app.get("/health", dependencies=guard)
    async def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "build": build_stamp(),
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - _started_at, 1),
            "listeners": bus.subscriber_count,
        }

    @app.post("/ping", dependencies=guard)
    async def ping() -> dict:
        """Emit a test event. Used to verify the live stream end to end."""
        return {"published": bus.publish("ping", message="Testereignis")}

    # ---------------------------------------------------------------- settings

    @app.get("/config", dependencies=guard)
    async def read_config() -> dict:
        return config_store.load()

    @app.get("/config/defaults", dependencies=guard)
    async def read_defaults() -> dict:
        return config_store.DEFAULTS

    @app.put("/config", dependencies=guard)
    async def write_config(candidate: Dict[str, Any] = Body(...)) -> dict:
        try:
            stored = config_store.save(candidate)
        except config_store.ConfigError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        bus.publish("config_saved")
        return stored

    # ----------------------------------------------------------------- secrets

    @app.get("/secrets", dependencies=guard)
    async def read_secrets() -> list:
        return secrets.status()

    @app.put("/secrets/{name}", dependencies=guard)
    async def write_secret(name: str, body: Dict[str, str] = Body(...)) -> dict:
        try:
            secrets.set_value(name, body.get("value", ""))
        except secrets.UnknownSecret:
            raise HTTPException(status_code=404, detail="unbekanntes Geheimnis") from None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        bus.publish("secret_changed", name=name, present=True)
        return {"name": name, "present": True}

    @app.delete("/secrets/{name}", dependencies=guard)
    async def drop_secret(name: str) -> dict:
        try:
            secrets.delete(name)
        except secrets.UnknownSecret:
            raise HTTPException(status_code=404, detail="unbekanntes Geheimnis") from None
        bus.publish("secret_changed", name=name, present=False)
        return {"name": name, "present": False}

    # ------------------------------------------------------------------- items

    @app.get("/items", dependencies=guard)
    async def read_items(
        status: Optional[str] = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        if status and status not in database.ALL_STATUS:
            raise HTTPException(status_code=422, detail="unbekannter Status")
        connection = database.connect()
        try:
            return {
                "items": database.items(connection, status=status, limit=limit, offset=offset),
                "counts": database.counts(connection),
            }
        finally:
            connection.close()

    @app.get("/items/unclear", dependencies=guard)
    async def read_unclear() -> dict:
        connection = database.connect()
        try:
            return {
                "items": database.items(connection, status=database.STATUS_UNCLEAR),
                "open_dispatches": database.open_dispatches(connection),
            }
        finally:
            connection.close()

    # ----------------------------------------------------------------- browser

    @app.get("/browser", dependencies=guard)
    async def browser_state() -> dict:
        return runtime.fleet.snapshot()

    @app.get("/browser/windows", dependencies=guard)
    async def browser_windows() -> dict:
        """What the host process enforces: process id and wanted visibility."""
        return {"windows": runtime.fleet.wanted_windows()}

    @app.post("/browser/install", dependencies=guard)
    async def browser_install_start(body: Dict[str, Any] = Body(default={})) -> dict:
        if browser_install.busy():
            raise HTTPException(status_code=409, detail="Es laeuft bereits ein Download")
        replace = bool(body.get("replace", False))

        def progress(phase: str, done: int, total: int) -> None:
            bus.publish("browser_download", phase=phase, done=done, total=total)

        async def worker() -> None:
            try:
                result = await asyncio.to_thread(browser_install.install, progress, replace)
            except Exception as error:  # noqa: BLE001 - reported to the user
                bus.publish("browser_download", phase="fehler", message=str(error))
                return
            bus.publish("browser_download", phase="fertig", **result)

        asyncio.create_task(worker())
        return {"started": True}

    @app.post("/browser/start", dependencies=guard)
    async def browser_start() -> dict:
        settings = config_store.load()
        try:
            return await runtime.fleet.start(settings.get("browsers", {}))
        except runtime.BrowserError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/browser/stop", dependencies=guard)
    async def browser_stop() -> dict:
        return await runtime.fleet.stop()

    @app.post("/browser/pause", dependencies=guard)
    async def browser_pause(body: Dict[str, Any] = Body(default={})) -> dict:
        return runtime.fleet.set_paused(bool(body.get("paused", True)))

    @app.post("/browser/{role}/visibility", dependencies=guard)
    async def browser_visibility(role: str, body: Dict[str, Any] = Body(...)) -> dict:
        try:
            return runtime.fleet.set_visible(role, bool(body.get("visible", False)))
        except runtime.BrowserError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/browser/{role}/navigate", dependencies=guard)
    async def browser_navigate(role: str, body: Dict[str, Any] = Body(default={})) -> dict:
        settings = config_store.load()
        url = str(body.get("url") or settings.get("source", {}).get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="Keine Adresse hinterlegt")
        try:
            instance = runtime.fleet.instance(role)
            reached = await instance.navigate(url, float(settings["limits"]["search.reload"]))
        except runtime.BrowserError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001 - navigation failures are expected
            bus.publish("browser_failed", role=role, message=str(error))
            raise HTTPException(status_code=502, detail=str(error)) from error
        bus.publish("browser_navigated", role=role, url=reached)
        return runtime.fleet.snapshot()

    # ---------------------------------------------------------------- registry

    def registry_scope(scope: str) -> str:
        try:
            return registry_model.check_scope(scope)
        except registry_model.RegistryError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    def registry_answer(call):
        """Run a registry operation and turn a refusal into a message."""
        try:
            return call()
        except registry_model.RegistryError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def live_page(scope: str):
        """The page of an instance, or a clear reason why there is none."""
        try:
            instance = runtime.fleet.instance(scope)
        except runtime.BrowserError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if instance.page is None:
            raise HTTPException(
                status_code=409,
                detail=f"{registry_model.SCOPE_LABELS[scope]} laeuft nicht",
            )
        return instance

    @app.get("/registry/{scope}", dependencies=guard)
    async def registry_read(scope: str) -> dict:
        scope = registry_scope(scope)
        document = registry_answer(lambda: registry_store.load(scope))
        document["label"] = registry_model.SCOPE_LABELS[scope]
        document["kinds"] = registry_model.KIND_LABELS
        return document

    @app.put("/registry/{scope}", dependencies=guard)
    async def registry_write(scope: str, body: Dict[str, Any] = Body(...)) -> dict:
        scope = registry_scope(scope)
        stored = registry_answer(lambda: registry_store.save(scope, body, note="Bearbeitet"))
        bus.publish("registry_saved", scope=scope, version=stored["version"])
        return stored

    @app.get("/registry/{scope}/catalogue", dependencies=guard)
    async def registry_catalogue(scope: str) -> dict:
        scope = registry_scope(scope)
        return {"roles": registry_model.catalogue(scope)}

    @app.post("/registry/{scope}/catalogue", dependencies=guard)
    async def registry_catalogue_add(scope: str) -> dict:
        scope = registry_scope(scope)
        stored = registry_answer(lambda: registry_store.add_catalogue(scope))
        bus.publish("registry_saved", scope=scope, version=stored["version"])
        return stored

    @app.put("/registry/{scope}/roles/{role_id}", dependencies=guard)
    async def registry_put_role(
        scope: str, role_id: str, body: Dict[str, Any] = Body(...)
    ) -> dict:
        scope = registry_scope(scope)
        candidate = {**body, "id": role_id}
        stored = registry_answer(lambda: registry_store.put_role(scope, candidate))
        bus.publish("registry_saved", scope=scope, version=stored["version"], role=role_id)
        return stored

    @app.delete("/registry/{scope}/roles/{role_id}", dependencies=guard)
    async def registry_drop_role(scope: str, role_id: str) -> dict:
        scope = registry_scope(scope)
        stored = registry_answer(lambda: registry_store.drop_role(scope, role_id))
        bus.publish("registry_saved", scope=scope, version=stored["version"], role=role_id)
        return stored

    @app.get("/registry/{scope}/history", dependencies=guard)
    async def registry_history(scope: str) -> dict:
        scope = registry_scope(scope)
        return {"versions": registry_store.history(scope)}

    @app.post("/registry/{scope}/restore", dependencies=guard)
    async def registry_restore(scope: str, body: Dict[str, Any] = Body(...)) -> dict:
        scope = registry_scope(scope)
        version = int(body.get("version") or 0)
        stored = registry_answer(lambda: registry_store.restore(scope, version))
        bus.publish("registry_restored", scope=scope, version=stored["version"], back_to=version)
        return stored

    @app.post("/registry/{scope}/export", dependencies=guard)
    async def registry_export(scope: str) -> dict:
        scope = registry_scope(scope)
        return registry_answer(lambda: registry_store.export(scope))

    @app.post("/registry/{scope}/import", dependencies=guard)
    async def registry_import(scope: str, body: Dict[str, Any] = Body(...)) -> dict:
        scope = registry_scope(scope)
        if body.get("path"):
            stored = registry_answer(
                lambda: registry_store.import_file(scope, str(body["path"]))
            )
        else:
            stored = registry_answer(
                lambda: registry_store.import_document(scope, body.get("document"))
            )
        bus.publish("registry_saved", scope=scope, version=stored["version"])
        return stored

    @app.get("/registry/{scope}/new-id", dependencies=guard)
    async def registry_new_id(scope: str, wanted: str = Query(default="rolle")) -> dict:
        scope = registry_scope(scope)
        return {"id": registry_store.free_id(scope, wanted)}

    @app.post("/registry/{scope}/check", dependencies=guard)
    async def registry_check(scope: str, body: Dict[str, Any] = Body(default={})) -> dict:
        """Try the stored candidates against the page that is open now."""
        scope = registry_scope(scope)
        instance = live_page(scope)
        roles = registry_answer(lambda: registry_store.load(scope))["roles"]
        wanted = str(body.get("role") or "")
        if wanted:
            roles = [role for role in roles if role["id"] == wanted]
            if not roles:
                raise HTTPException(status_code=404, detail="unbekannte Rolle")
        try:
            reports = await registry_resolve.check_all(instance.page, roles)
        except Exception as error:  # noqa: BLE001 - reported as text
            raise HTTPException(status_code=502, detail=str(error)) from error
        return {"url": instance.page.url, "results": reports}

    # ------------------------------------------------------------------ picker

    @app.get("/picker", dependencies=guard)
    async def picker_state() -> dict:
        return picker.state()

    @app.post("/picker/{scope}/start", dependencies=guard)
    async def picker_start(scope: str) -> dict:
        scope = registry_scope(scope)
        instance = live_page(scope)
        try:
            return await picker.start(instance.page, scope)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/picker/{scope}/stop", dependencies=guard)
    async def picker_stop(scope: str) -> dict:
        scope = registry_scope(scope)
        instance = live_page(scope)
        try:
            return await picker.stop(instance.page)
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/picker/clear", dependencies=guard)
    async def picker_clear() -> dict:
        return picker.clear()

    @app.post("/picker/{scope}/snapshot", dependencies=guard)
    async def picker_snapshot(scope: str, body: Dict[str, Any] = Body(...)) -> dict:
        """Open a saved copy of a view, without script and without network."""
        scope = registry_scope(scope)
        instance = live_page(scope)
        view = str(body.get("view") or "")
        source = str(body.get("path") or "")
        try:
            if source:
                file = Path(source)
            else:
                file = atlas.catalog.snapshot_file(str(body.get("from") or scope), view)
            opened = await snapshot_view.open_on(instance.page, file)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(error)) from error
        bus.publish("snapshot_opened", scope=scope, view=view)
        return opened

    @app.post("/picker/{scope}/release", dependencies=guard)
    async def picker_release(scope: str) -> dict:
        scope = registry_scope(scope)
        instance = live_page(scope)
        await snapshot_view.release(instance.page)
        return {"released": True}

    # ----------------------------------------------------------- page catalogue

    @app.get("/atlas", dependencies=guard)
    async def atlas_views(scope: Optional[str] = Query(default=None)) -> dict:
        if scope:
            scope = registry_scope(scope)
        return {"views": atlas.views(scope)}

    @app.post("/atlas/{scope}/capture", dependencies=guard)
    async def atlas_capture(scope: str) -> dict:
        scope = registry_scope(scope)
        instance = live_page(scope)
        record = await atlas.capture(instance.page, scope, trigger="Von Hand")
        if record is None:
            raise HTTPException(status_code=502, detail="Die Ansicht war nicht lesbar")
        return record

    @app.get("/atlas/{scope}/{view}/screenshot", dependencies=guard)
    async def atlas_screenshot(scope: str, view: str):
        scope = registry_scope(scope)
        try:
            return FileResponse(atlas.catalog.screenshot_file(scope, view))
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.delete("/atlas/{scope}/{view}", dependencies=guard)
    async def atlas_forget(scope: str, view: str) -> dict:
        scope = registry_scope(scope)
        try:
            atlas.forget(scope, view)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"removed": view}

    # ------------------------------------------------------------------ stream

    @app.websocket("/events")
    async def events(
        websocket: WebSocket,
        token_param: str = Query(alias="token"),
        after: int = Query(default=0),
    ) -> None:
        if not hmac.compare_digest(token_param, token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        queue = bus.subscribe()
        try:
            for missed in bus.replay(after_seq=after):
                await websocket.send_json(missed)
            bus.publish("client_attached", listeners=bus.subscriber_count)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    await websocket.send_json({"kind": "heartbeat"})
                    continue
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            bus.unsubscribe(queue)

    return app
