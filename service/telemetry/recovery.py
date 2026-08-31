"""Getting a stuck browser going again (spec 6.7).

Four stages, in order, each one more invasive than the last, and a fifth
that is no longer a stage: stop and say so. Between the stages the state
detection decides whether it worked, because that is the only judgement
the application is allowed to make on its own.

The one action that is never repeated automatically is sending a contact
form. If a send was already under way when the recovery started, the
entry goes onto the "unclear" list (8.4) and stays there until a person
decides.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from ..api.events import bus
from ..registry import store as registry_store
from ..storage import config as config_store
from ..storage import database
from . import notify

STATE = "zustand"
RELOAD = "neu_laden"
START = "startadresse"
SIGN_IN = "anmeldung"
HALT = "anhalten"

STAGE_LABELS = {
    STATE: "Zustandsprüfung wiederholt",
    RELOAD: "Seite neu geladen",
    START: "Zur Startadresse zurückgekehrt",
    SIGN_IN: "Anmeldung geprüft",
    HALT: "Angehalten und benachrichtigt",
}

STEP_TIMEOUT_S = 60.0


async def _known_state(instance: Any) -> Dict[str, Any]:
    """Does the application recognise where it is?"""
    from ..engine import states as engine_states

    document = registry_store.load(instance.role)
    if not document.get("states"):
        # Nothing has been taught yet. Then a page that answers at all is
        # the most that may honestly be claimed.
        try:
            await instance.page.evaluate("() => document.readyState")
            return {"ok": True, "label": "Seite antwortet", "state": ""}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "label": str(error), "state": ""}
    try:
        detection = await engine_states.detect(instance.page, document, announce=False)
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "label": str(error), "state": ""}
    chosen = getattr(detection, "chosen", None)
    if chosen:
        return {"ok": True, "label": chosen.get("label", ""), "state": chosen.get("id", "")}
    return {"ok": False, "label": getattr(detection, "reason", "unbekannter Zustand"), "state": ""}


async def _reload(instance: Any) -> None:
    await instance.page.reload(wait_until="domcontentloaded")


async def _start_page(instance: Any) -> None:
    settings = config_store.load()
    address = str(settings["source"].get("url") or "").strip()
    if not address:
        raise RuntimeError("Es ist keine Startadresse eingetragen")
    await instance.navigate(address, STEP_TIMEOUT_S)


async def _sign_in(instance: Any) -> None:
    from ..flow import login as login_flow

    await login_flow.ensure(instance)


def _park_open_send(key: str) -> bool:
    """An unconfirmed send is never repeated, it is handed over (8.4)."""
    if not key:
        return False
    connection = database.connect()
    try:
        open_ones = {entry.get("key") for entry in database.open_dispatches(connection)}
        if key not in open_ones:
            return False
        database.set_status(
            connection,
            key,
            database.STATUS_UNCLEAR,
            reason="Wiederherstellung nach dem Absenden, Ergebnis unbekannt",
        )
    finally:
        connection.close()
    bus.publish("dispatch_unclear", keys=[key])
    return True


async def recover(instance: Any, reason: str, key: str = "") -> Dict[str, Any]:
    """Work through the stages until one of them holds."""
    scope = getattr(instance, "role", "")
    parked = _park_open_send(key)
    tried: List[Dict[str, Any]] = []
    bus.publish("recovery_started", scope=scope, reason=reason, parked=parked)

    stages = (
        (STATE, None),
        (RELOAD, _reload),
        (START, _start_page),
        (SIGN_IN, _sign_in),
    )
    for name, action in stages:
        note = ""
        if action is not None:
            try:
                await asyncio.wait_for(action(instance), timeout=STEP_TIMEOUT_S)
            except Exception as error:  # noqa: BLE001 - the next stage is the answer
                note = f"{type(error).__name__}: {error}"
        verdict = await _known_state(instance)
        tried.append({"stage": name, "label": STAGE_LABELS[name], "note": note,
                      "ok": verdict["ok"], "state": verdict.get("label", "")})
        bus.publish("recovery_stage", scope=scope, stage=name, ok=verdict["ok"],
                    note=note, state=verdict.get("label", ""))
        if verdict["ok"]:
            bus.publish("recovery_done", scope=scope, stage=name, parked=parked)
            return {"ok": True, "stage": name, "stages": tried, "parked": parked}

    # Nothing held. Stop and say so, which is always better than a guess.
    from ..flow import manager as flow_manager

    try:
        if flow_manager.manager.busy:
            flow_manager.manager.stop()
    except Exception:  # noqa: BLE001
        pass
    tried.append({"stage": HALT, "label": STAGE_LABELS[HALT], "note": "", "ok": False, "state": ""})
    bus.publish("recovery_failed", scope=scope, reason=reason, parked=parked)
    notify.notify(
        notify.BLOCKED,
        f"Der {scope}-Browser ließ sich nicht wiederherstellen ({reason}). Der Ablauf steht.",
        scope=scope,
    )
    return {"ok": False, "stage": HALT, "stages": tried, "parked": parked}
