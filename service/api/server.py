"""HTTP and WebSocket surface of the local service.

Bound to 127.0.0.1 only. Every request must carry the one-time token
that the host process handed over on startup.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import time
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

from .. import __version__
from .. import runtime
from ..runtime import browser_install
from ..storage import config as config_store
from ..storage import database, secrets
from .events import bus

HEARTBEAT_SECONDS = 15.0
_started_at = time.monotonic()


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
