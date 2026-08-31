"""The selection mode as seen from the service.

The overlay lives in the page (overlay/overlay.js). This module turns it
on and off, receives what the user picked and keeps it until the user
has assigned it to a role in the application window.

The assignment panel is part of the application, not of the page: the
less the overlay does inside the page, the smaller the risk that it ends
up in a screenshot or a snapshot.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from ..api.events import bus

OVERLAY_FILE = Path(__file__).with_name("overlay") / "overlay.js"
OVERLAY_SOURCE = OVERLAY_FILE.read_text(encoding="utf-8")

# The name the overlay calls to report back. Bound per browser context.
BINDING = "__ztAssist"


class Picker:
    """State of the selection mode, one per application run."""

    def __init__(self) -> None:
        self.scope: str = ""
        self.active: bool = False
        self.pick: Optional[Dict[str, Any]] = None
        # Counts up with every selection. The user interface needs a
        # stable mark to tell a new selection from the same selection
        # polled again: the answer object itself is rebuilt every time.
        self.serial: int = 0

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
            self.serial += 1
            self.pick = {
                "scope": scope,
                "serial": self.serial,
                "element": element,
                "url": payload.get("url", ""),
            }
            self.active = False
            bus.publish(
                "pick",
                scope=scope,
                tag=element.get("tag", ""),
                candidates=len(element.get("candidates") or []),
            )

    # ------------------------------------------------------ towards the page

    async def start(self, page: Any, scope: str) -> Dict[str, Any]:
        self.scope = scope
        self.pick = None
        await page.evaluate("() => window.__ztOverlay.start()")
        self.active = True
        return self.state()

    async def stop(self, page: Any) -> Dict[str, Any]:
        await page.evaluate("() => window.__ztOverlay.stop()")
        self.active = False
        return self.state()

    def clear(self) -> Dict[str, Any]:
        self.pick = None
        return self.state()

    def state(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "scope": self.scope,
            "serial": self.serial,
            "pick": self.pick,
        }


picker = Picker()
