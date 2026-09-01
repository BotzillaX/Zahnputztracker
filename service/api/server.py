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
from contextlib import asynccontextmanager
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
from .. import text as composer
from ..engine import approval as engine_approval
from ..engine import runner as engine_runner
from ..engine import templates as engine_templates
from ..picker import picker
from ..picker import session as picker_session
from ..picker import snapshot as snapshot_view
from ..registry import model as registry_model
from ..registry import resolve as registry_resolve
from ..flow import contact as contact_flow
from ..flow import contract as flow_contract
from ..flow import login as login_flow
from ..flow import manager as flow_manager
from ..flow import search as search_flow
from ..registry import store as registry_store
from ..telemetry import (
    frames,
    housekeeping,
    incidents,
    journal,
    notify,
    report as diagnosis_report,
    spans,
    stats,
    tracing,
    watchdog,
)
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


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Start and stop the background watchers of the service."""
    journal.attach()
    journal.write("service_started", version=__version__, build=build_stamp())
    housekeeping.sweep()
    watchdog.start()
    housekeeping.start()
    try:
        yield
    finally:
        journal.write("service_stopped")
        await watchdog.stop()
        await housekeeping.stop()
        await frames.detach_all()
        stats.flush(force=True)


def create_app(token: str) -> FastAPI:
    app = FastAPI(title="local service", version=__version__, docs_url=None,
                  redoc_url=None, lifespan=_lifespan)

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
                "decisions": [
                    {"value": "kontaktiert", "label": "Als erledigt vermerken"},
                    {"value": "erneut", "label": "Erneut bearbeiten"},
                ],
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

    @app.get("/registry/{scope}/plan", dependencies=guard)
    async def registry_plan(scope: str) -> dict:
        """What this browser is used for, in the order it happens."""
        scope = registry_scope(scope)
        document = registry_answer(lambda: registry_store.load(scope))
        answer = flow_contract.plan(scope, document)
        answer["label"] = registry_model.SCOPE_LABELS[scope]
        answer["version"] = document["version"]
        return answer

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

    @app.post("/picker/picks", dependencies=guard)
    async def picker_add(body: Dict[str, Any] = Body(...)) -> dict:
        """An entry added by hand, from wherever it was copied.

        It joins the same numbered list as a selection made in the
        browser, marked as pasted so the two are never confused.
        """
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="Es wurde nichts eingefuegt")
        scope = str(body.get("scope") or "")
        picker.add(
            registry_scope(scope) if scope else "",
            raw=text,
            note=str(body.get("note") or ""),
            url=str(body.get("url") or ""),
            source=picker_session.BY_HAND,
        )
        return picker.state()

    @app.delete("/picker/picks/{serial}", dependencies=guard)
    async def picker_forget(serial: int) -> dict:
        return picker.forget(int(serial))

    @app.delete("/picker/picks", dependencies=guard)
    async def picker_forget_all() -> dict:
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

    # ------------------------------------------------------------------ states

    @app.get("/states/{scope}", dependencies=guard)
    async def states_read(scope: str) -> dict:
        """Everything the state editor needs, in one answer."""
        scope = registry_scope(scope)
        document = registry_answer(lambda: registry_store.load(scope))
        settings = config_store.load()
        return {
            "scope": scope,
            "label": registry_model.SCOPE_LABELS[scope],
            "version": document["version"],
            "states": document["states"],
            "roles": [
                {"id": role["id"], "label": role["label"], "menge": role["menge"],
                 "taught": bool(role["candidates"]), "options": role["options"]}
                for role in document["roles"]
            ],
            "actions": registry_model.ACTIONS,
            "modes": registry_model.MODE_LABELS,
            "conditions": registry_model.CONDITION_LABELS,
            "sources": registry_model.SOURCE_LABELS,
            "config_names": sorted(engine_runner.BUILT_IN_CONFIG)
            + [str(entry.get("label", "")) for entry in settings.get("profile_values") or []],
            "answer_names": [str(entry.get("label", "")) for entry in settings.get("answers") or []],
            "secret_names": [
                {"name": entry["name"], "label": entry["label"], "present": entry["present"]}
                for entry in secrets.status()
            ],
            "variables": engine_runner.variables(),
        }

    @app.put("/states/{scope}/{state_id}", dependencies=guard)
    async def states_put(scope: str, state_id: str, body: Dict[str, Any] = Body(...)) -> dict:
        scope = registry_scope(scope)
        candidate = {**body, "id": state_id}
        stored = registry_answer(lambda: registry_store.put_state(scope, candidate))
        bus.publish("state_saved", scope=scope, state=state_id, version=stored["version"])
        return stored

    @app.delete("/states/{scope}/{state_id}", dependencies=guard)
    async def states_drop(scope: str, state_id: str) -> dict:
        scope = registry_scope(scope)
        stored = registry_answer(lambda: registry_store.drop_state(scope, state_id))
        bus.publish("state_dropped", scope=scope, state=state_id, version=stored["version"])
        return stored

    @app.get("/states/{scope}/new-id", dependencies=guard)
    async def states_new_id(scope: str, wanted: str = Query(default="zustand")) -> dict:
        scope = registry_scope(scope)
        return {"id": registry_store.free_state_id(scope, wanted)}

    @app.post("/states/{scope}/detect", dependencies=guard)
    async def states_detect(scope: str) -> dict:
        """Which states hold on the page that is open right now."""
        scope = registry_scope(scope)
        instance = live_page(scope)
        try:
            return await engine_runner.state_report(instance, scope)
        except registry_model.RegistryError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001 - reported as text
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/states/{scope}/run", dependencies=guard)
    async def states_run(scope: str, body: Dict[str, Any] = Body(default={})) -> dict:
        """Detect the state and work through its chain (spec 2.6 to 2.8)."""
        scope = registry_scope(scope)
        instance = live_page(scope)
        rounds = int(body.get("rounds") or engine_runner.MAX_ROUNDS)
        try:
            return await engine_runner.run_once(instance, scope, rounds)
        except registry_model.RegistryError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001 - reported as text
            raise HTTPException(status_code=502, detail=str(error)) from error

    # -------------------------------------------------------------- approval

    @app.get("/approval", dependencies=guard)
    async def approval_state() -> dict:
        return engine_approval.gate.state()

    @app.post("/approval/answer", dependencies=guard)
    async def approval_answer(body: Dict[str, Any] = Body(...)) -> dict:
        try:
            return engine_approval.gate.answer(
                int(body.get("id") or 0),
                str(body.get("decision") or ""),
                str(body.get("value") or ""),
            )
        except KeyError as error:
            raise HTTPException(status_code=409, detail=str(error.args[0])) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    # ------------------------------------------------------------- variables

    @app.get("/variables", dependencies=guard)
    async def variables_read() -> dict:
        return engine_runner.variables()

    @app.post("/variables/open", dependencies=guard)
    async def variables_open(body: Dict[str, Any] = Body(default={})) -> dict:
        return engine_runner.open_run(str(body.get("key") or ""))

    # ------------------------------------------------------------- templates

    def template_answer(call):
        try:
            return call()
        except engine_templates.TemplateError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except registry_model.RegistryError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/templates", dependencies=guard)
    async def templates_read(scope: Optional[str] = Query(default=None)) -> dict:
        document = template_answer(engine_templates.load)
        if scope:
            wanted = registry_scope(scope)
            document["templates"] = [
                entry for entry in document["templates"] if entry.get("scope") == wanted
            ]
        return document

    @app.post("/templates/switch", dependencies=guard)
    async def templates_switch(body: Dict[str, Any] = Body(...)) -> dict:
        return template_answer(lambda: engine_templates.set_enabled(bool(body.get("enabled"))))

    @app.post("/templates/reset", dependencies=guard)
    async def templates_reset() -> dict:
        return template_answer(engine_templates.reset)

    @app.delete("/templates/{template_id}", dependencies=guard)
    async def templates_drop(template_id: str) -> dict:
        return template_answer(lambda: engine_templates.drop(template_id))

    @app.post("/templates/{template_id}/apply/{scope}", dependencies=guard)
    async def templates_apply(template_id: str, scope: str) -> dict:
        scope = registry_scope(scope)
        stored = template_answer(lambda: engine_templates.apply(scope, template_id))
        bus.publish("template_applied", scope=scope, template=template_id,
                    version=stored["version"])
        return stored

    @app.get("/approval/screenshot", dependencies=guard)
    async def approval_screenshot():
        """The picture that belongs to the open request, if there is one."""
        target = contact_flow.screenshot_file()
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Kein Bild vorhanden")
        return FileResponse(target)

    # -------------------------------------------------------------- one entry

    @app.get("/flow", dependencies=guard)
    async def flow_state() -> dict:
        """What is running, and whether the taught roles are enough."""
        document = registry_answer(lambda: registry_store.load(registry_model.SESSION))
        answer = flow_manager.manager.state()
        answer["readiness"] = flow_contract.readiness(document)
        answer["review_mode"] = bool(config_store.load().get("review_mode", True))
        answer["search_readiness"] = search_flow.readiness(
            registry_answer(lambda: registry_store.load(registry_model.SEARCH))
        )
        return answer

    @app.get("/flow/search", dependencies=guard)
    async def flow_search_state() -> dict:
        """The search cycle: what it did, and what it still needs."""
        return {
            "state": search_flow.loop.state(),
            "readiness": search_flow.readiness(
                registry_answer(lambda: registry_store.load(registry_model.SEARCH))
            ),
        }

    @app.post("/flow/search", dependencies=guard)
    async def flow_search_start() -> dict:
        """Start the cycle. Both browsers have to be up for it."""
        search_instance = live_page(registry_model.SEARCH)
        session_instance = live_page(registry_model.SESSION)
        try:
            return flow_manager.manager.start_search(search_instance, session_instance)
        except search_flow.SearchError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/flow/sign-in", dependencies=guard)
    async def flow_sign_in_state() -> dict:
        instance = live_page(registry_model.SESSION)
        try:
            return await login_flow.state(instance)
        except Exception as error:  # noqa: BLE001 - reported as text
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post("/flow/sign-in", dependencies=guard)
    async def flow_sign_in() -> dict:
        instance = live_page(registry_model.SESSION)
        try:
            return flow_manager.manager.start_login(instance)
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/flow/contact", dependencies=guard)
    async def flow_contact(body: Dict[str, Any] = Body(...)) -> dict:
        """Work through one entry whose address was handed over by hand."""
        url = str(body.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise HTTPException(status_code=422, detail="Das ist keine gültige Adresse")
        # Without a key from a result list the address is the key. It is
        # what makes the entry unique, and it keeps the protection
        # against sending twice working for a run started by hand.
        key = str(body.get("key") or "").strip() or url
        instance = live_page(registry_model.SESSION)
        try:
            return flow_manager.manager.start_contact(
                instance, key, url, str(body.get("title") or "")
            )
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/flow/stop", dependencies=guard)
    async def flow_stop() -> dict:
        return flow_manager.manager.stop()

    @app.get("/text/help", dependencies=guard)
    async def text_help() -> dict:
        return {
            "placeholders": [
                {"name": name, "meaning": meaning}
                for name, meaning in composer.PLACEHOLDER_HELP
            ],
            "providers": composer.providers(),
        }

    @app.post("/items/decision", dependencies=guard)
    async def item_decide(body: Dict[str, Any] = Body(...)) -> dict:
        """Decide an entry whose send was never confirmed (8.4).

        The key travels in the body: it may be an address, and an address
        does not belong in a path.
        """
        key = str(body.get("key") or "").strip()
        if not key:
            raise HTTPException(status_code=422, detail="Es fehlt die Kennung")
        try:
            return flow_manager.decide(key, str(body.get("decision") or ""))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    # ------------------------------------------------------------- incidents

    @app.get("/incidents", dependencies=guard)
    async def incident_list(limit: int = Query(default=100, ge=1, le=500)) -> dict:
        return {"incidents": incidents.listing(limit)}

    @app.get("/incidents/{incident}", dependencies=guard)
    async def incident_read(incident: str) -> dict:
        try:
            return incidents.read(incident)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/incidents/{incident}/file/{name:path}", dependencies=guard)
    async def incident_file(incident: str, name: str):
        try:
            return FileResponse(incidents.file_of(incident, name))
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/incidents/{incident}/picker", dependencies=guard)
    async def incident_picker(incident: str, body: Dict[str, Any] = Body(default={})) -> dict:
        """Open the page copy of an incident, ready to be corrected.

        The way from a bad situation to its repair without reproducing
        it (spec 12.4). The name of the file is checked against the
        incident's own folder, so nothing else can be opened this way.
        """
        scope = registry_scope(str(body.get("scope") or "search"))
        name = str(body.get("name") or "seite.html")
        instance = live_page(scope)
        try:
            file = incidents.file_of(incident, name)
            opened = await snapshot_view.open_on(instance.page, file)
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(error)) from error
        bus.publish("snapshot_opened", scope=scope, incident=incident, file=name)
        return {**opened, "incident": incident, "scope": scope, "name": name}

    @app.delete("/incidents/{incident}", dependencies=guard)
    async def incident_forget(incident: str) -> dict:
        try:
            incidents.forget(incident)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"removed": incident}

    # ------------------------------------------------------------- diagnosis

    def _degradations(days: int = 1) -> list:
        """How often a role had to fall back to a weaker candidate."""
        counted: Dict[str, Dict[str, Any]] = {}
        for record in journal.entries(days):
            if record.get("ev") != "degraded":
                continue
            role = str(record.get("role", ""))
            entry = counted.setdefault(
                role,
                {"role": role, "label": record.get("label", role), "count": 0,
                 "kind_label": record.get("kind_label", ""), "step": record.get("step", 0),
                 "last": record.get("ts", "")},
            )
            entry["count"] += 1
            entry["last"] = record.get("ts", entry["last"])
            entry["kind_label"] = record.get("kind_label", entry["kind_label"])
            entry["step"] = record.get("step", entry["step"])
        return sorted(counted.values(), key=lambda item: -item["count"])

    @app.get("/diagnose", dependencies=guard)
    async def diagnosis() -> dict:
        return {
            "status": spans.level(),
            "open": [item.report() for item in spans.open_spans()],
            "recent": spans.recent(50),
            "degraded": _degradations(),
            "watchdog": watchdog.running(),
            "frames": frames.state(),
            "tracing": tracing.state(),
            "storage": housekeeping.usage(),
            "paused": spans.paused(),
        }

    @app.get("/diagnose/stats", dependencies=guard)
    async def diagnosis_stats() -> dict:
        settings = config_store.load()
        return {
            "names": list(spans.NAMES),
            "limits": settings.get("limits", {}),
            "stats": stats.summary(),
            "min_samples": stats.MIN_SAMPLES,
            "levels": stats.LEVEL_LABELS,
        }

    @app.get("/diagnose/log", dependencies=guard)
    async def diagnosis_log(count: int = Query(default=200, ge=1, le=2000)) -> dict:
        return {"days": journal.days(), "records": journal.tail(count)}

    @app.get("/diagnose/storage", dependencies=guard)
    async def diagnosis_storage() -> dict:
        return housekeeping.usage()

    @app.post("/diagnose/cleanup", dependencies=guard)
    async def diagnosis_cleanup() -> dict:
        return housekeeping.sweep()

    @app.get("/diagnose/reports", dependencies=guard)
    async def diagnosis_reports() -> dict:
        return {"reports": diagnosis_report.listing(), "days": journal.days()}

    @app.post("/diagnose/report", dependencies=guard)
    async def diagnosis_write_report(body: Dict[str, Any] = Body(default={})) -> dict:
        target = diagnosis_report.write(str(body.get("day", "") or ""))
        return {"name": target.name, "path": str(target)}

    @app.get("/diagnose/report/{name}", dependencies=guard)
    async def diagnosis_read_report(name: str):
        try:
            return FileResponse(diagnosis_report.file_of(name), media_type="text/markdown")
        except (FileNotFoundError, ValueError) as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/diagnose/probe", dependencies=guard)
    async def diagnosis_probe(body: Dict[str, Any] = Body(...)) -> dict:
        """Hold one operation open on purpose (acceptance 7 and 8).

        This is the only way to see the two thresholds without waiting
        for the target page to have a bad day.
        """
        name = str(body.get("name") or "state.detect")
        if name not in spans.NAMES:
            raise HTTPException(status_code=422, detail="unbekannter Vorgang")
        try:
            seconds = float(body.get("seconds", 10))
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Sekunden sind keine Zahl") from None
        if not 1 <= seconds <= 900:
            raise HTTPException(status_code=422, detail="Sekunden müssen zwischen 1 und 900 liegen")
        scope = str(body.get("scope") or runtime.SESSION)
        if scope not in runtime.ROLES:
            raise HTTPException(status_code=422, detail="unbekannter Browser")
        instance = runtime.fleet.instance(scope)
        if instance.page is None:
            raise HTTPException(status_code=409, detail="Dieser Browser läuft nicht")

        async def hold() -> None:
            async with spans.span(name, instance=instance, probe=True):
                await asyncio.sleep(seconds)

        asyncio.create_task(hold())
        return {"name": name, "scope": scope, "seconds": seconds,
                "limit_s": spans.hard_limit(name),
                "soft_ms": stats.soft_threshold(name, scope)}

    # --------------------------------------------------------- notifications

    @app.get("/notifications", dependencies=guard)
    async def notification_queue(after: int = Query(default=0, ge=0)) -> dict:
        """What the host process has not turned into a system message yet."""
        return notify.pending(after)

    # ----------------------------------------------------------- page catalogue

    @app.get("/atlas", dependencies=guard)
    async def atlas_views(scope: Optional[str] = Query(default=None)) -> dict:
        if scope:
            scope = registry_scope(scope)
        return {"views": atlas.views(scope)}

    @app.get("/atlas/map", dependencies=guard)
    async def atlas_map(scope: Optional[str] = Query(default=None)) -> dict:
        """Views and the steps between them, for the map."""
        if scope:
            scope = registry_scope(scope)
        return atlas.graph(scope)

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
