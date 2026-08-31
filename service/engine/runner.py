"""Carrying out an action chain (spec 2.7).

Every action is described before it runs, and the description is what the
user sees when an action is set to ``freigabe`` or ``manuell``. Anything
that cannot be carried out exactly as defined ends the chain with a
defined stop: there is no fallback that tries something similar (2.8).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from ..api.events import bus
from ..registry import model
from ..registry import resolve as registry_resolve
from ..registry import store as registry_store
from ..registry.resolve import UnknownState
from ..storage import config as config_store
from ..storage import database, secrets
from . import states as state_detection
from .approval import ALLOWED, CANCELLED, DONE, gate
from .variables import space

# How long a single interaction with an element may take. The real time
# limits per operation come with the observability stage; this is only
# the guard that keeps one action from hanging forever.
ACTION_TIMEOUT_S = 20.0
POLL_S = 0.4

# Two settings are named values in their own right, so a state can use
# them without the user having to repeat them in the list of personal
# values.
BUILT_IN_CONFIG = {
    "Zugangskennung": ("account", "email"),
    "Startadresse": ("source", "url"),
}

# How often a chain may ask for a new state check before we call it a
# loop. Without this an "erneut_pruefen" in a state that keeps matching
# would run forever.
MAX_ROUNDS = 20


class EngineStop(RuntimeError):
    """A defined stop: the run ends, the user is told why."""

    def __init__(self, message: str, kind: str = "stop") -> None:
        super().__init__(message)
        self.kind = kind


class Recheck(Exception):
    """Internal: the chain asks for the state to be looked at again."""


def _role(document: Dict[str, Any], role_id: str) -> Dict[str, Any]:
    for role in document["roles"]:
        if role["id"] == role_id:
            return role
    raise EngineStop(f"Die Rolle '{role_id}' ist nicht angelegt")


def source_value(source: Dict[str, str], for_display: bool = True) -> str:
    """The text behind a source (spec 2.7, decisions 7 and 8).

    A secret is fetched here and handed straight to the page. It is never
    put into an event, a description or a log line.
    """
    kind = source["art"]
    name = source["name"]
    if kind == model.SOURCE_VARIABLE:
        try:
            return space.get(name)
        except KeyError as error:
            raise EngineStop(str(error)) from error

    if kind == model.SOURCE_SECRET:
        try:
            value = secrets.get(name)
        except secrets.UnknownSecret as error:
            raise EngineStop(f"Das Geheimnis '{name}' gibt es nicht") from error
        if not value:
            raise EngineStop(f"Für '{name}' ist im Anmeldeinformationsspeicher nichts hinterlegt")
        return value

    settings = config_store.load()
    if kind == model.SOURCE_CONFIG:
        built_in = BUILT_IN_CONFIG.get(name)
        if built_in:
            value = str(settings.get(built_in[0], {}).get(built_in[1], "") or "")
            if not value:
                raise EngineStop(f"In den Einstellungen ist '{name}' leer")
            return value
        for entry in settings.get("profile_values") or []:
            if entry.get("label") == name:
                return str(entry.get("value", ""))
        raise EngineStop(f"Der Konfigurationswert '{name}' ist nicht gesetzt")

    # An answer pair carries both an internal value and a display text.
    # A text field gets what a person would type, a stored value is used
    # when there is no display text.
    for entry in settings.get("answers") or []:
        if entry.get("label") == name:
            display = str(entry.get("display", ""))
            value = str(entry.get("value", ""))
            return (display or value) if for_display else (value or display)
    raise EngineStop(f"Das Antwort-Paar '{name}' ist nicht hinterlegt")


async def element(page: Any, document: Dict[str, Any], role_id: str) -> Any:
    """Mark the element of a role and return a locator for it.

    Public because the flows of the next stage act on the same roles and
    must fail in exactly the same way as an action does.
    """
    role = _role(document, role_id)
    try:
        resolution = await registry_resolve.locate(page, role)
    except UnknownState as error:
        raise EngineStop(str(error), kind="unknown_state") from error
    if not resolution.found:
        raise EngineStop(f"{role['label']}: {resolution.reason or 'nicht gefunden'}")
    if resolution.count > 1:
        raise EngineStop(f"{role['label']}: mehrere Treffer, kein eindeutiges Element")
    return registry_resolve.locator(page, resolution)


async def role_visible(page: Any, document: Dict[str, Any], role_id: str) -> bool:
    try:
        return await registry_resolve.present(page, _role(document, role_id))
    except UnknownState as error:
        raise EngineStop(str(error), kind="unknown_state") from error


async def wait_for_role(page: Any, document: Dict[str, Any], role_id: str, seconds: float, wanted: bool) -> None:
    deadline = time.monotonic() + seconds
    while True:
        if await role_visible(page, document, role_id) == wanted:
            return
        if time.monotonic() >= deadline:
            label = _role(document, role_id)["label"]
            word = "erschienen" if wanted else "verschwunden"
            raise EngineStop(f"{label} ist innerhalb von {seconds} s nicht {word}")
        await asyncio.sleep(POLL_S)


async def set_choice(page: Any, locator: Any, value: str, label: str) -> str:
    """Set a dropdown, a checkbox or a radio button.

    Which of the three it is comes from the element itself. Anything else
    is not silently clicked: it stops.
    """
    shape = await locator.evaluate(
        "(node) => ({ tag: node.tagName.toLowerCase(), type: (node.type || '').toLowerCase() })"
    )
    tag = shape.get("tag")
    kind = shape.get("type")
    if tag == "select":
        await locator.select_option(value, timeout=ACTION_TIMEOUT_S * 1000)
        return "Auswahlfeld gesetzt"
    if tag == "input" and kind == "checkbox":
        wanted = value.strip().lower() in ("1", "true", "ja", "an", "aktiv")
        await locator.set_checked(wanted, timeout=ACTION_TIMEOUT_S * 1000)
        return "Haken gesetzt" if wanted else "Haken entfernt"
    if tag == "input" and kind == "radio":
        await locator.check(timeout=ACTION_TIMEOUT_S * 1000)
        return "Auswahl angeklickt"
    raise EngineStop(f"{label}: das Element ist kein Auswahlfeld, kein Haken und kein Radiofeld")


def _settle(status: str, reason: str) -> str:
    """Write the outcome of an item run into the database."""
    key = space.run
    if not key:
        raise EngineStop("Es läuft kein Vorgang, es gibt nichts zu dokumentieren")
    connection = database.connect()
    try:
        database.set_status(connection, key, status, reason=reason)
    finally:
        connection.close()
    return key


async def perform(instance: Any, document: Dict[str, Any], action: Dict[str, Any]) -> str:
    """Carry out one action. Returns a short line about what happened."""
    page = instance.page
    kind = action["type"]

    if kind == "klicken":
        locator = await element(page, document, action["role"])
        await locator.click(timeout=ACTION_TIMEOUT_S * 1000)
        await registry_resolve.clear(page)
        return "geklickt"

    if kind == "text_eintragen":
        text = source_value(action["source"])
        locator = await element(page, document, action["role"])
        await locator.fill(text, timeout=ACTION_TIMEOUT_S * 1000)
        await registry_resolve.clear(page)
        secret = action["source"]["art"] == model.SOURCE_SECRET
        return "Geheimnis eingetragen" if secret else f"{len(text)} Zeichen eingetragen"

    if kind == "auswahl_setzen":
        label = _role(document, action["role"])["label"]
        locator = await element(page, document, action["role"])
        result = await set_choice(page, locator, action["value"], label)
        await registry_resolve.clear(page)
        return result

    if kind == "adresse_oeffnen":
        url = source_value(action["source"], for_display=False).strip()
        if not url.lower().startswith(("http://", "https://")):
            raise EngineStop("Die Quelle enthält keine gültige Adresse")
        limit = float(config_store.load()["limits"].get("item.open", 60))
        reached = await instance.navigate(url, limit)
        return f"geöffnet: {reached}"

    if kind == "scrollen_zu":
        locator = await element(page, document, action["role"])
        await locator.scroll_into_view_if_needed(timeout=ACTION_TIMEOUT_S * 1000)
        await registry_resolve.clear(page)
        return "in den sichtbaren Bereich geholt"

    if kind == "warten_sichtbar":
        await wait_for_role(page, document, action["role"], action["seconds"], True)
        return "ist sichtbar"

    if kind == "warten_verschwunden":
        await wait_for_role(page, document, action["role"], action["seconds"], False)
        return "ist verschwunden"

    if kind == "warten":
        await asyncio.sleep(action["seconds"])
        return f"{action['seconds']} s gewartet"

    if kind == "neu_laden":
        instance.next_trigger = "Neu laden"
        await page.reload(timeout=ACTION_TIMEOUT_S * 1000, wait_until="domcontentloaded")
        return "neu geladen"

    if kind == "text_auslesen":
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        stored = space.set(action["target"], text)
        return f"{len(stored)} Zeichen nach '{action['target']}' gelegt"

    if kind == "anschreiben_erzeugen":
        # The text generation belongs to the next stage. Until it is
        # there this action stops instead of writing something made up.
        raise EngineStop("Die Textgenerierung ist in dieser Ausbaustufe noch nicht angebunden")

    if kind == "dokumentieren":
        key = _settle(database.STATUS_CONTACTED, "Aktionskette abgeschlossen")
        return f"als kontaktiert vermerkt: {key}"

    if kind == "ueberspringen":
        key = _settle(database.STATUS_SKIPPED, action["reason"])
        return f"übersprungen: {key}"

    if kind == "anhalten":
        raise EngineStop(action["message"], kind="halt")

    if kind == "erneut_pruefen":
        raise Recheck()

    raise EngineStop(f"Unbekannte Aktion: {kind}")


async def _permission(action: Dict[str, Any], description: str, state: Dict[str, Any], scope: str) -> bool:
    """Ask the user, if this action asks to be asked. True = carry it out."""
    mode = action["mode"]
    if mode == model.MODE_AUTOMATIC:
        return True
    answer = await gate.ask(
        {
            "mode": mode,
            "scope": scope,
            "state": state["id"],
            "state_label": state["label"],
            "action": action["type"],
            "description": description,
        }
    )
    decision = answer["decision"]
    if mode == model.MODE_APPROVAL:
        if decision == ALLOWED:
            return True
        raise EngineStop(
            "Die Freigabe wurde abgelehnt"
            if decision != CANCELLED
            else "Die Freigabe wurde abgebrochen"
        )
    # manuell: the user did it himself, nothing is carried out here.
    if decision == DONE:
        return False
    raise EngineStop(
        "Der Schritt von Hand wurde abgebrochen"
        if decision == CANCELLED
        else "Der Schritt von Hand wurde nicht bestätigt"
    )


async def run_chain(instance: Any, document: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    """Work through the actions of one state."""
    scope = document["scope"]
    steps: List[Dict[str, Any]] = []
    bus.publish("chain_started", scope=scope, state=state["id"], label=state["label"],
                actions=len(state["actions"]))
    for position, action in enumerate(state["actions"], start=1):
        description = model.describe_action(action, document["roles"])
        bus.publish("action_started", scope=scope, state=state["id"], step=position,
                    action=action["type"], mode=action["mode"], description=description)
        try:
            run_it = await _permission(action, description, state, scope)
            outcome = await perform(instance, document, action) if run_it else "von Hand erledigt"
        except Recheck:
            steps.append({"step": position, "description": description, "outcome": "Zustandsprüfung"})
            bus.publish("action_done", scope=scope, state=state["id"], step=position,
                        description=description, outcome="Zustandsprüfung")
            return {"state": state["id"], "steps": steps, "recheck": True}
        except EngineStop:
            raise
        except Exception as error:  # noqa: BLE001 - reported as a defined stop
            raise EngineStop(f"{description}: {error}") from error
        steps.append({"step": position, "description": description, "outcome": outcome})
        bus.publish("action_done", scope=scope, state=state["id"], step=position,
                    description=description, outcome=outcome)
    bus.publish("chain_done", scope=scope, state=state["id"], label=state["label"])
    return {"state": state["id"], "steps": steps, "recheck": False}


async def run_once(instance: Any, scope: str, rounds: int = MAX_ROUNDS) -> Dict[str, Any]:
    """Look at the page and work through what the state says, once.

    A chain that ends with "check again" starts another round. Every
    other outcome ends here, successfully or with a defined stop.
    """
    report: Dict[str, Any] = {"scope": scope, "rounds": [], "stopped": "", "kind": ""}
    for _ in range(max(1, rounds)):
        document = registry_store.load(scope)
        try:
            detection = await state_detection.detect(instance.page, document)
        except UnknownState as error:
            return _stopped(report, str(error), "unknown_state", scope)
        if detection.chosen is None:
            return _stopped(report, detection.reason, "unknown_state", scope)
        try:
            outcome = await run_chain(instance, document, detection.chosen)
        except EngineStop as error:
            report["rounds"].append({"state": detection.chosen["id"], "steps": []})
            return _stopped(report, str(error), error.kind, scope)
        report["rounds"].append(outcome)
        if not outcome["recheck"]:
            return report
    return _stopped(report, f"Nach {rounds} Durchgängen ist kein Ende erreicht", "loop", scope)


def _stopped(report: Dict[str, Any], reason: str, kind: str, scope: str) -> Dict[str, Any]:
    report["stopped"] = reason
    report["kind"] = kind
    bus.publish("engine_stopped", scope=scope, reason=reason, stop=kind)
    return report


async def state_report(instance: Any, scope: str) -> Dict[str, Any]:
    """What the user interface shows: which states hold right now."""
    document = registry_store.load(scope)
    try:
        detection = await state_detection.detect(instance.page, document, announce=False)
    except UnknownState as error:
        return {"scope": scope, "url": instance.page.url, "error": str(error),
                "matches": [], "chosen": "", "visible": {}}
    answer = detection.as_dict()
    answer["scope"] = scope
    answer["url"] = instance.page.url
    answer["error"] = ""
    return answer


def variables() -> Dict[str, Any]:
    return space.report()


def open_run(key: str = "") -> Dict[str, Any]:
    space.open(key)
    bus.publish("run_opened", key=key)
    return space.report()


__all__ = [
    "EngineStop",
    "MAX_ROUNDS",
    "element",
    "open_run",
    "perform",
    "role_visible",
    "set_choice",
    "wait_for_role",
    "run_chain",
    "run_once",
    "source_value",
    "state_report",
    "variables",
]
