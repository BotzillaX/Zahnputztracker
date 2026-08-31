"""Which state the page is in (spec 2.6).

A state holds when every condition of its ``all`` list holds and, if it
has an ``any`` group, at least one condition of that group holds. There
is no other logic: no brackets, no comparisons, no similarity. Each
condition carries its kind, so a further kind can be added later without
changing what is stored today.

Three outcomes are possible and all three are named:

* exactly one state holds            -> that one is used
* several hold                       -> the smallest priority number wins;
                                        an equal number is not decided here
* none holds, or a role is ambiguous -> unknown state (2.8), stop
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..registry import model
from ..registry import resolve as registry_resolve
from ..registry.resolve import UnknownState


class Detection:
    """The result of one look at the page."""

    def __init__(self) -> None:
        self.matches: List[Dict[str, Any]] = []
        self.chosen: Optional[Dict[str, Any]] = None
        self.visible: Dict[str, bool] = {}
        self.reason = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "matches": [
                {"id": state["id"], "label": state["label"], "priority": state["priority"]}
                for state in self.matches
            ],
            "chosen": self.chosen["id"] if self.chosen else "",
            "chosen_label": self.chosen["label"] if self.chosen else "",
            "visible": self.visible,
            "reason": self.reason,
        }


def referenced_roles(states: List[Dict[str, Any]]) -> List[str]:
    """Every role a condition asks about, each one only once."""
    wanted: List[str] = []
    for state in states:
        for condition in state["all"] + state["any"]:
            if condition["role"] not in wanted:
                wanted.append(condition["role"])
    return wanted


async def visibility(page: Any, document: Dict[str, Any], wanted: List[str]) -> Dict[str, bool]:
    """Ask the page once per role. Ambiguity ends the look immediately."""
    roles = {role["id"]: role for role in document["roles"]}
    seen: Dict[str, bool] = {}
    for role_id in wanted:
        role = roles.get(role_id)
        if role is None:
            # clean_document rejects this, so it can only happen with a
            # document that was written past the validation.
            raise UnknownState(f"Die Rolle '{role_id}' ist nicht angelegt")
        seen[role_id] = await registry_resolve.present(page, role)
    return seen


def holds(state: Dict[str, Any], seen: Dict[str, bool]) -> bool:
    for condition in state["all"]:
        if seen.get(condition["role"], False) != (condition["kind"] == model.VISIBLE):
            return False
    if state["any"]:
        for condition in state["any"]:
            if seen.get(condition["role"], False) == (condition["kind"] == model.VISIBLE):
                break
        else:
            return False
    return True


async def detect(page: Any, document: Dict[str, Any], announce: bool = True) -> Detection:
    """Look at the page and decide which state it is in."""
    result = Detection()
    states = [state for state in document["states"] if state["enabled"]]
    if not states:
        result.reason = "Es ist kein Zustand definiert"
        return result

    result.visible = await visibility(page, document, referenced_roles(states))
    result.matches = sorted(
        [state for state in states if holds(state, result.visible)],
        key=lambda state: (state["priority"], state["id"]),
    )

    if not result.matches:
        result.reason = "Kein definierter Zustand trifft zu"
    elif len(result.matches) > 1 and result.matches[0]["priority"] == result.matches[1]["priority"]:
        # Two states of equal rank. Picking one of them would be a guess.
        result.reason = (
            f"Mehrere Zustände treffen zu und haben dieselbe Priorität: "
            f"{result.matches[0]['label']}, {result.matches[1]['label']}"
        )
    else:
        result.chosen = result.matches[0]
        if len(result.matches) > 1:
            result.reason = (
                f"{len(result.matches)} Zustände treffen zu, "
                f"die Priorität entscheidet für {result.chosen['label']}"
            )

    if announce:
        bus.publish(
            "state_detected",
            scope=document["scope"],
            chosen=result.chosen["id"] if result.chosen else "",
            label=result.chosen["label"] if result.chosen else "",
            matches=len(result.matches),
            reason=result.reason,
        )
    return result
