"""The selection mode as seen from the service.

The overlay lives in the page (overlay/overlay.js). This module turns it
on and off and collects what the user picked.

A selection is not assigned to a role here. The user points at elements,
several in a row, and the list of what was pointed at is what leaves this
module: it is read out of the application window or out of the file it is
written to. Naming the roles and choosing their recognition features
happens outside, by someone who can weigh both.

The list therefore has to survive a restart of the service, and adding to
it must never fail loudly: a lost write is annoying, a crash while the
user is pointing at things is worse.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..storage import paths

OVERLAY_FILE = Path(__file__).with_name("overlay") / "overlay.js"
OVERLAY_SOURCE = OVERLAY_FILE.read_text(encoding="utf-8")

# The name the overlay calls to report back. Bound per browser context.
BINDING = "__ztAssist"

# How many selections are kept. Enough for a long session of teaching,
# small enough that the file stays readable.
MAX_PICKS = 50
# Pasted material is kept as it came, but not without a limit.
MAX_RAW = 20_000

FROM_PAGE = "auswahl"
BY_HAND = "eingefuegt"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def store_file() -> Path:
    return paths.roaming_dir() / "auswahl.json"


class Picker:
    """State of the selection mode, one per application run."""

    def __init__(self) -> None:
        self.scope: str = ""
        self.active: bool = False
        # Oldest first: the order is what the user refers to ("the first
        # one is the sign in button").
        self.picks: List[Dict[str, Any]] = []
        # Counts up with every selection and is never reused, so one
        # entry can be removed by name.
        self.serial: int = 0
        self._complained = False
        self._read()

    # ----------------------------------------------------------- the file

    def _read(self) -> None:
        target = store_file()
        try:
            if not target.is_file():
                return
            stored = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # An unreadable file is not worth stopping for. It is
            # replaced by the next selection.
            return
        if not isinstance(stored, dict):
            return
        picks = stored.get("picks")
        if isinstance(picks, list):
            self.picks = [item for item in picks if isinstance(item, dict)][-MAX_PICKS:]
        self.serial = max(
            [int(stored.get("serial") or 0)]
            + [int(item.get("serial") or 0) for item in self.picks]
        )

    def _write(self) -> None:
        target = store_file()
        payload = {"serial": self.serial, "picks": self.picks}
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=1)
            os.replace(temporary, target)
        except OSError as error:  # noqa: BLE001 - reported once, never raised
            if not self._complained:
                self._complained = True
                bus.publish("picks_unsaved", reason=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------ the list

    def add(
        self,
        scope: str,
        element: Optional[Dict[str, Any]] = None,
        url: str = "",
        note: str = "",
        raw: str = "",
        source: str = FROM_PAGE,
    ) -> Dict[str, Any]:
        """One entry, from the page or pasted by hand."""
        self.serial += 1
        entry = {
            "serial": self.serial,
            "at": _now(),
            "scope": scope,
            "source": source,
            "url": url,
            "note": note[:500],
            "element": element,
            "raw": raw[:MAX_RAW],
        }
        self.picks.append(entry)
        del self.picks[:-MAX_PICKS]
        self._write()
        return entry

    def forget(self, serial: int) -> Dict[str, Any]:
        self.picks = [item for item in self.picks if int(item.get("serial") or 0) != serial]
        self._write()
        return self.state()

    def clear(self) -> Dict[str, Any]:
        self.picks = []
        self._write()
        return self.state()

    # ---------------------------------------------------------- from the page

    def report(self, scope: str, payload: Dict[str, Any]) -> None:
        """Called by the overlay through the exposed binding."""
        kind = str(payload.get("type") or "")
        if kind == "picker_state":
            self.active = bool(payload.get("active"))
            self.scope = scope if self.active else ""
            bus.publish("picker_state", scope=scope, active=self.active)
            return
        if kind == "pick_cancelled":
            self.active = False
            bus.publish("pick_cancelled", scope=scope)
            return
        if kind == "pick":
            element = payload.get("element") or {}
            entry = self.add(scope, element=element, url=str(payload.get("url") or ""))
            # The mode stays on: the user usually points at several
            # elements in a row.
            bus.publish(
                "pick",
                scope=scope,
                serial=entry["serial"],
                position=len(self.picks),
                tag=element.get("tag", ""),
                candidates=len(element.get("candidates") or []),
            )

    # ------------------------------------------------------ towards the page

    async def start(self, page: Any, scope: str) -> Dict[str, Any]:
        self.scope = scope
        await page.evaluate("() => window.__ztOverlay.start()")
        self.active = True
        return self.state()

    async def stop(self, page: Any) -> Dict[str, Any]:
        await page.evaluate("() => window.__ztOverlay.stop()")
        self.active = False
        return self.state()

    def state(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "scope": self.scope,
            "serial": self.serial,
            "file": str(store_file()),
            "picks": list(self.picks),
        }


picker = Picker()
