"""One run at a time (spec 12.2).

A run waits for approvals, and an approval can take minutes. So a run is
a background task: the request that starts it returns at once, and the
user interface follows along through the event stream. Only one run
exists at a time, which is also what decision 9 asks for.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..api.events import bus
from ..engine.approval import gate
from ..engine.runner import open_run
from ..storage import config as config_store
from ..storage import database
from ..telemetry import tracing
from . import contact as contact_flow
from . import login as login_flow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Manager:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self.job: Optional[Dict[str, Any]] = None
        self.last: Optional[Dict[str, Any]] = None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def state(self) -> Dict[str, Any]:
        return {"busy": self.busy, "job": self.job, "last": self.last}

    def _guard(self) -> None:
        if self.busy:
            raise RuntimeError("Es läuft bereits ein Vorgang")

    async def _wrap(self, kind: str, work, instance: Any = None) -> None:
        # One job is one recorded cycle. It is thrown away again unless
        # something in it was worth keeping (6.3).
        if instance is not None:
            await tracing.begin(instance, kind)
        try:
            outcome = await work()
            self.last = {"kind": kind, "at": _now(), "ok": True, "result": outcome}
        except asyncio.CancelledError:
            if instance is not None:
                tracing.mark(instance.role, "Vorgang abgebrochen")
            raise
        except Exception as error:  # noqa: BLE001 - reported, never lost
            self.last = {"kind": kind, "at": _now(), "ok": False,
                         "reason": f"{type(error).__name__}: {error}"}
            if instance is not None:
                tracing.mark(instance.role, f"{kind} endete mit einem Fehler")
            bus.publish("flow_failed", kind=kind, reason=str(error))
        finally:
            self.job = None
            if instance is not None:
                history = int(config_store.load().get("trace_history") or 20)
                try:
                    await tracing.end(instance, history)
                except Exception:  # noqa: BLE001 - a recording is never the job
                    pass
            bus.publish("flow_finished", kind=kind)

    def start_login(self, instance: Any) -> Dict[str, Any]:
        self._guard()
        self.job = {"kind": "anmeldung", "scope": instance.role, "started": _now()}
        bus.publish("flow_started", kind="anmeldung", scope=instance.role)
        self._task = asyncio.create_task(
            self._wrap("anmeldung", lambda: login_flow.sign_in(instance), instance)
        )
        return self.state()

    def start_contact(self, instance: Any, key: str, url: str, title: str = "") -> Dict[str, Any]:
        self._guard()
        self.job = {"kind": "vorgang", "scope": instance.role, "key": key, "url": url,
                    "title": title, "started": _now()}
        bus.publish("flow_started", kind="vorgang", scope=instance.role, key=key, url=url)
        # A new run starts with an empty variable space (decision 8).
        open_run(key)

        async def work() -> Dict[str, Any]:
            # Signed in before every run (7.3).
            await login_flow.ensure(instance)
            return await contact_flow.contact(instance, key, url, title)

        self._task = asyncio.create_task(self._wrap("vorgang", work, instance))
        return self.state()

    def stop(self) -> Dict[str, Any]:
        """End the running job. An open approval is dropped with it."""
        if self._task is not None and not self._task.done():
            gate.cancel("Vorgang abgebrochen")
            self._task.cancel()
        self.job = None
        bus.publish("flow_cancelled")
        return self.state()


manager = Manager()


def open_dispatches() -> Dict[str, Any]:
    """Sends that were started and never confirmed (8.4).

    They are only listed, never repeated: a person decides.
    """
    connection = database.connect()
    try:
        return {
            "open": database.open_dispatches(connection),
            "unclear": database.items(connection, status=database.STATUS_UNCLEAR),
        }
    finally:
        connection.close()


def decide(key: str, decision: str) -> Dict[str, Any]:
    """What happens to an entry whose send was never confirmed."""
    connection = database.connect()
    try:
        if decision == "kontaktiert":
            database.mark_dispatch_confirmed(connection, key)
            database.set_status(connection, key, database.STATUS_CONTACTED,
                                reason="Von Hand als erledigt bestätigt")
        elif decision == "erneut":
            database.clear_dispatch(connection, key)
            database.set_status(connection, key, database.STATUS_OPEN,
                                reason="Zur erneuten Bearbeitung freigegeben")
        else:
            raise ValueError("unbekannte Entscheidung")
        bus.publish("item_decided", key=key, decision=decision)
        return {"key": key, "decision": decision}
    finally:
        connection.close()
