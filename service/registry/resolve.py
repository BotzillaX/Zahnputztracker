"""Finding an element again from its stored candidates (spec 2.4).

The candidates of a role are tried in their stored order. The first one
that matches wins. Having to fall back to a weaker candidate is a
degradation: it is recorded and shown, but it does not stop anything.

Two situations are not decided here, because deciding them would be
guessing (2.8):
  * no candidate matches            -> the role is not present
  * a candidate matches several
    visible elements                -> unknown state
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..api.events import bus
from . import model

HIT = "data-zt-hit"


class UnknownState(RuntimeError):
    """Raised when the page cannot be read without guessing."""


class Resolution:
    """What the search for one role produced."""

    def __init__(self, role: Dict[str, Any]) -> None:
        self.role_id: str = role["id"]
        self.label: str = role["label"]
        self.quantity: str = role.get("menge", model.SINGLE)
        self.found = False
        self.count = 0
        self.step = -1  # position of the candidate that matched
        self.kind = ""
        self.degraded = False
        self.multiple_hidden = False
        self.reason = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role_id,
            "label": self.label,
            "found": self.found,
            "count": self.count,
            "step": self.step,
            "kind": self.kind,
            "kind_label": model.KIND_LABELS.get(self.kind, self.kind),
            "degraded": self.degraded,
            "multiple_hidden": self.multiple_hidden,
            "reason": self.reason,
        }


async def _try(page: Any, candidate: Dict[str, Any], want_all: bool) -> Dict[str, Any]:
    return await page.evaluate(
        "([candidate, wantAll]) => window.__ztOverlay.find(candidate, wantAll)",
        [candidate, want_all],
    )


async def clear(page: Any) -> None:
    await page.evaluate("() => window.__ztOverlay.clearHit()")


async def locate(page: Any, role: Dict[str, Any], announce: bool = True) -> Resolution:
    """Mark the element (or elements) of a role in the page.

    On success the matched elements carry the marker attribute, so the
    caller can act on them with a normal locator.
    """
    result = Resolution(role)
    candidates: List[Dict[str, Any]] = role.get("candidates") or []
    if not candidates:
        result.reason = "Für diese Rolle ist noch nichts angelernt"
        return result

    want_all = result.quantity == model.MANY
    for step, candidate in enumerate(candidates):
        hit = await _try(page, candidate, want_all)
        total = int(hit.get("total") or 0)
        visible = int(hit.get("visible") or 0)
        if total == 0:
            continue
        if visible == 0:
            # Present but hidden. That is not a match, and it is not a
            # reason to take a hidden element either.
            result.multiple_hidden = True
            continue
        if not want_all and visible > 1:
            await clear(page)
            message = (
                f"{result.label}: {visible} sichtbare Treffer über "
                f"{model.KIND_LABELS.get(candidate['kind'], candidate['kind'])}"
            )
            bus.publish(
                "ambiguous",
                role=result.role_id,
                visible=visible,
                candidate=candidate["kind"],
            )
            raise UnknownState(message)

        result.found = True
        result.count = int(hit.get("marked") or 0)
        result.step = step
        result.kind = candidate["kind"]
        result.degraded = step > 0
        if total > visible:
            # The page holds the same thing several times and only shows
            # one of them. Fixed resolution rule, worth recording.
            bus.publish(
                "duplicate_resolved",
                role=result.role_id,
                total=total,
                visible=visible,
                candidate=candidate["kind"],
            )
        if result.degraded and announce:
            bus.publish(
                "degraded",
                role=result.role_id,
                label=result.label,
                step=step,
                candidate=candidate["kind"],
                kind_label=model.KIND_LABELS.get(candidate["kind"], candidate["kind"]),
                first_kind=candidates[0]["kind"],
            )
        return result

    await clear(page)
    result.reason = "Kein Merkmal hat gegriffen"
    return result


def locator(page: Any, resolution: Resolution) -> Any:
    """A Playwright locator for what `locate` marked."""
    if not resolution.found:
        raise UnknownState(f"{resolution.label}: nichts gefunden")
    return page.locator(f"[{HIT}]")


async def present(page: Any, role: Dict[str, Any]) -> bool:
    """Is the role visible on the page right now (basis of 2.6)."""
    resolution = await locate(page, role, announce=False)
    await clear(page)
    return resolution.found


async def check(page: Any, role: Dict[str, Any]) -> Dict[str, Any]:
    """Report for the user interface, without acting on the page."""
    try:
        resolution = await locate(page, role, announce=False)
    except UnknownState as error:
        await clear(page)
        return {
            "role": role["id"],
            "label": role["label"],
            "found": False,
            "ambiguous": True,
            "reason": str(error),
        }
    await clear(page)
    report = resolution.as_dict()
    report["ambiguous"] = False
    return report


async def check_all(page: Any, roles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [await check(page, role) for role in roles]


def find_role(roles: List[Dict[str, Any]], role_id: str) -> Optional[Dict[str, Any]]:
    for role in roles:
        if role["id"] == role_id:
            return role
    return None
