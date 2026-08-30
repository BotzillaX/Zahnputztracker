"""HTTP and WebSocket surface of the local service.

Bound to 127.0.0.1 only. Every request must carry the one-time token
that the host process handed over on startup.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import time
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .. import __version__
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

    def check(candidate: Optional[str]) -> None:
        if not candidate or not hmac.compare_digest(candidate, token):
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health(x_auth_token: Optional[str] = Header(default=None)) -> dict:
        check(x_auth_token)
        return {
            "status": "ok",
            "version": __version__,
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - _started_at, 1),
            "listeners": bus.subscriber_count,
        }

    @app.post("/ping")
    async def ping(x_auth_token: Optional[str] = Header(default=None)) -> dict:
        """Emit a test event. Used to verify the live stream end to end."""
        check(x_auth_token)
        event = bus.publish("ping", message="Testereignis")
        return {"published": event}

    @app.websocket("/events")
    async def events(websocket: WebSocket, token_param: str = Query(alias="token"),
                     after: int = Query(default=0)) -> None:
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
