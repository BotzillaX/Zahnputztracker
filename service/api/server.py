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
