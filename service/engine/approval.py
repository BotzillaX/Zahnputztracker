"""Waiting for a decision of the user (spec 2.7, decision 9).

Two execution modes need the user: ``freigabe`` asks whether an action
may be carried out, ``manuell`` asks the user to do it himself and to
confirm afterwards. Both use the same gate.

Only one request can be open at a time. While it is open everything else
waits, which is exactly what decision 9 asks for: an open approval pauses
the run rather than letting a second thing slip past it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from ..api.events import bus

ALLOWED = "erlaubt"
REFUSED = "abgelehnt"
DONE = "erledigt"
CANCELLED = "abgebrochen"
DECISIONS = (ALLOWED, REFUSED, DONE)


class Gate:
    def __init__(self) -> None:
        self._pending: Optional[Dict[str, Any]] = None
        self._answer: Optional[asyncio.Future] = None
        self._serial = 0

    @property
    def open(self) -> bool:
        return self._pending is not None

    def state(self) -> Dict[str, Any]:
        return {"open": self.open, "request": self._pending}

    async def ask(self, request: Dict[str, Any]) -> str:
        """Show a request and wait for the answer. Returns the decision."""
        if self._pending is not None:
            raise RuntimeError("Es wartet bereits eine Freigabe")
        self._serial += 1
        loop = asyncio.get_running_loop()
        self._answer = loop.create_future()
        self._pending = {"id": self._serial, **request}
        bus.publish("approval_open", **self._pending)
        try:
            decision = await self._answer
        finally:
            self._pending = None
            self._answer = None
        bus.publish("approval_closed", id=self._serial, decision=decision)
        return decision

    def answer(self, request_id: int, decision: str) -> Dict[str, Any]:
        if self._pending is None or self._answer is None:
            raise KeyError("Es wartet keine Freigabe")
        if int(request_id) != int(self._pending["id"]):
            raise KeyError("Diese Freigabe ist nicht mehr offen")
        if decision not in DECISIONS:
            raise ValueError("unbekannte Entscheidung")
        if not self._answer.done():
            self._answer.set_result(decision)
        return {"id": request_id, "decision": decision}

    def cancel(self, reason: str = "") -> None:
        """Drop an open request, for example when the run is stopped."""
        if self._answer is not None and not self._answer.done():
            self._answer.set_result(CANCELLED)
        bus.publish("approval_cancelled", reason=reason)


gate = Gate()
