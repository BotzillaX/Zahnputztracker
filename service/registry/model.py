"""Roles, recognition candidates and the base catalogue.

A role is an abstract name for something on the page (spec 2.3). The
program only ever refers to roles; which element is behind a role is
decided by the user alone. Nothing in this file describes a concrete
page.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

SEARCH = "search"
SESSION = "session"
SCOPES = (SEARCH, SESSION)

SCOPE_LABELS = {SEARCH: "Such-Browser", SESSION: "Sitzungs-Browser"}

# How many elements a role stands for (decision 6).
SINGLE = "einzel"
MANY = "liste"
QUANTITIES = (SINGLE, MANY)

# Candidate kinds in the priority order of spec 2.4. The order of this
# tuple is the order in which they are tried at run time.
KINDS = ("attr", "aria", "text", "id", "path")

KIND_LABELS = {
    "attr": "Datenattribut",
    "aria": "Rolle und Name",
    "text": "Sichtbarer Text",
    "id": "Kennung",
    "path": "Strukturpfad",
}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class RegistryError(ValueError):
    """Raised when something cannot be stored as written."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# The catalogue is a set of empty, neutrally named slots. It contains no
# recognition candidate whatsoever: after loading it the application
# still cannot do anything until the user has taught it (spec 2.2). The
# user may add, rename and delete roles freely.
BASE_CATALOGUE: Dict[str, List[Tuple[str, str, str]]] = {
    SEARCH: [
        ("consent_accept", "Zustimmung bestätigen", SINGLE),
        ("list_container", "Ergebnisliste", SINGLE),
        ("list_item", "Listeneintrag", MANY),
        ("item_key", "Kennungsträger", SINGLE),
        ("item_title", "Eintragstitel", SINGLE),
        ("item_detail", "Eintragsdetail", SINGLE),
        ("item_link", "Eintragsverweis", SINGLE),
        ("empty_marker", "Leer-Hinweis", SINGLE),
    ],
    SESSION: [
        ("signed_in_marker", "Angemeldet-Merkmal", SINGLE),
        ("sign_in_entry", "Anmelde-Einstieg", SINGLE),
        ("identity_field", "Kennungsfeld", SINGLE),
        ("secret_field", "Geheimnisfeld", SINGLE),
        ("second_factor_marker", "Zweitfaktor-Merkmal", SINGLE),
        ("second_factor_field", "Zweitfaktor-Feld", SINGLE),
        ("primary_action_a", "Hauptaktion A", SINGLE),
        ("primary_action_b", "Hauptaktion B", SINGLE),
        ("message_field", "Textfeld", SINGLE),
        ("submit_action", "Absende-Element", SINGLE),
        ("confirmation_marker", "Bestätigungs-Merkmal", SINGLE),
        ("exclusion_marker_a", "Ausschluss-Merkmal A", SINGLE),
        ("exclusion_marker_b", "Ausschluss-Merkmal B", SINGLE),
        ("form_field_a", "Formularfeld A", SINGLE),
        ("form_field_b", "Formularfeld B", SINGLE),
        ("form_field_c", "Formularfeld C", SINGLE),
        ("form_field_d", "Formularfeld D", SINGLE),
        ("ready_marker", "Seite-fertig-Merkmal", SINGLE),
        ("already_marker", "Bereits-erledigt-Merkmal", SINGLE),
    ],
}


def catalogue(scope: str) -> List[Dict[str, Any]]:
    """Empty role slots to start from. Values are added by the user."""
    check_scope(scope)
    return [
        blank_role(role_id, label, scope, quantity)
        for role_id, label, quantity in BASE_CATALOGUE[scope]
    ]


def blank_role(role_id: str, label: str, scope: str, quantity: str = SINGLE) -> Dict[str, Any]:
    return {
        "id": role_id,
        "label": label,
        "scope": scope,
        "menge": quantity,
        "notes": "",
        "key_attribute": "",
        "answer": "",
        "options": [],
        "candidates": [],
        "updated": now(),
    }


def check_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise RegistryError("unbekannte Browser-Instanz")
    return scope


def clean_candidate(raw: Any, position: int) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise RegistryError(f"Merkmal {position} ist kein Objekt")
    kind = str(raw.get("kind") or "")
    if kind not in KINDS:
        raise RegistryError(f"Merkmal {position} hat eine unbekannte Art")
    value = str(raw.get("value") or "").strip()
    if not value:
        raise RegistryError(f"Merkmal {position} hat keinen Wert")
    candidate = {"kind": kind, "value": value}
    if kind == "attr":
        attribute = str(raw.get("attr") or "").strip()
        if not attribute:
            raise RegistryError(f"Merkmal {position} nennt kein Attribut")
        candidate["attr"] = attribute
    if kind == "aria":
        aria = str(raw.get("role") or "").strip()
        if not aria:
            raise RegistryError(f"Merkmal {position} nennt keine Rolle")
        candidate["role"] = aria
    return candidate


def clean_role(raw: Any, scope: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RegistryError("Rolle ist kein Objekt")
    role_id = str(raw.get("id") or "").strip()
    if not ID_PATTERN.match(role_id):
        raise RegistryError(
            f"Die Kennung '{role_id}' ist nicht zulässig "
            "(Kleinbuchstaben, Ziffern und Unterstrich, mindestens zwei Zeichen)"
        )
    label = str(raw.get("label") or "").strip()
    if not label:
        raise RegistryError(f"Rolle '{role_id}' hat keinen Anzeigenamen")
    quantity = str(raw.get("menge") or SINGLE)
    if quantity not in QUANTITIES:
        raise RegistryError(f"Rolle '{role_id}' hat eine unbekannte Menge")

    candidates = raw.get("candidates") or []
    if not isinstance(candidates, list):
        raise RegistryError(f"Rolle '{role_id}': Merkmale müssen eine Liste sein")

    options = []
    for entry in raw.get("options") or []:
        if not isinstance(entry, dict):
            raise RegistryError(f"Rolle '{role_id}': Auswahlwert ist kein Objekt")
        options.append(
            {
                "value": str(entry.get("value", "")),
                "display": str(entry.get("display", "")),
            }
        )

    return {
        "id": role_id,
        "label": label,
        "scope": scope,
        "menge": quantity,
        "notes": str(raw.get("notes") or ""),
        "key_attribute": str(raw.get("key_attribute") or "").strip(),
        # Which answer pair fills this field (spec 8.3). Empty means the
        # field is left alone.
        "answer": str(raw.get("answer") or "").strip(),
        "options": options,
        "candidates": [
            clean_candidate(candidate, index)
            for index, candidate in enumerate(candidates, start=1)
        ],
        "updated": str(raw.get("updated") or now()),
    }


def clean_document(raw: Any, scope: str) -> Dict[str, Any]:
    """Normalise a whole registry document, or refuse it with a reason."""
    check_scope(scope)
    if not isinstance(raw, dict):
        raise RegistryError("Die Registrierung ist kein Objekt")
    roles_raw = raw.get("roles")
    if roles_raw is None:
        roles_raw = []
    if not isinstance(roles_raw, list):
        raise RegistryError("Rollen müssen eine Liste sein")

    roles = [clean_role(entry, scope) for entry in roles_raw]
    seen = set()
    for role in roles:
        if role["id"] in seen:
            raise RegistryError(f"Die Kennung '{role['id']}' kommt doppelt vor")
        seen.add(role["id"])

    states_raw = raw.get("states") or []
    if not isinstance(states_raw, list):
        raise RegistryError("Zustände müssen eine Liste sein")
    states = [clean_state(entry, index) for index, entry in enumerate(states_raw, start=1)]
    seen_states = set()
    for state in states:
        if state["id"] in seen_states:
            raise RegistryError(f"Die Kennung '{state['id']}' kommt doppelt vor")
        seen_states.add(state["id"])

    # A condition or an action may only refer to a role that exists. A
    # dangling reference would turn into a guess at run time.
    for state in states:
        for condition in state["all"] + state["any"]:
            if condition["role"] not in seen:
                raise RegistryError(
                    f"Zustand '{state['id']}' verweist auf die unbekannte Rolle "
                    f"'{condition['role']}'"
                )
        for action in state["actions"]:
            if "role" in action and action["role"] not in seen:
                raise RegistryError(
                    f"Zustand '{state['id']}' verweist auf die unbekannte Rolle "
                    f"'{action['role']}'"
                )

    return {"scope": scope, "version": int(raw.get("version") or 0), "roles": roles, "states": states}


def empty_document(scope: str) -> Dict[str, Any]:
    check_scope(scope)
    return {"scope": scope, "version": 0, "updated": now(), "roles": [], "states": []}


# ---------------------------------------------------------------- states
# A state is a combination of visible and invisible roles (spec 2.6). The
# condition model is deliberately flat: a list of conditions that all have
# to hold, plus one optional group of which at least one has to hold.
# Nesting, brackets and comparisons are not part of this version; every
# condition carries its own kind so a further kind can be added later
# without touching what is stored today.

VISIBLE = "sichtbar"
INVISIBLE = "unsichtbar"
CONDITION_KINDS = (VISIBLE, INVISIBLE)

CONDITION_LABELS = {
    VISIBLE: "ist sichtbar",
    INVISIBLE: "ist nicht sichtbar",
}

# Where the text of an action comes from. A value is never written into a
# state: it is fetched at run time from the configuration, from the answer
# pairs, from the credential store or from the variable space.
SOURCE_CONFIG = "konfiguration"
SOURCE_ANSWER = "antwort"
SOURCE_SECRET = "geheimnis"
SOURCE_VARIABLE = "variable"
SOURCE_KINDS = (SOURCE_CONFIG, SOURCE_ANSWER, SOURCE_SECRET, SOURCE_VARIABLE)

SOURCE_LABELS = {
    SOURCE_CONFIG: "Konfigurationswert",
    SOURCE_ANSWER: "Antwort-Paar",
    SOURCE_SECRET: "Geheimnis",
    SOURCE_VARIABLE: "Variable",
}

# How a single action is carried out (spec 2.7).
MODE_AUTOMATIC = "automatisch"
MODE_APPROVAL = "freigabe"
MODE_MANUAL = "manuell"
MODES = (MODE_AUTOMATIC, MODE_APPROVAL, MODE_MANUAL)

MODE_LABELS = {
    MODE_AUTOMATIC: "automatisch",
    MODE_APPROVAL: "mit Freigabe",
    MODE_MANUAL: "von Hand",
}

# The action catalogue of spec 2.7. Each entry names the fields it needs;
# everything else is refused when a chain is saved, so a half filled
# action can never reach the run time.
ACTIONS: Dict[str, Dict[str, Any]] = {
    "klicken": {"label": "Klicken", "fields": ("role",)},
    "text_eintragen": {"label": "Text eintragen", "fields": ("role", "source")},
    "auswahl_setzen": {"label": "Auswahl setzen", "fields": ("role", "value")},
    "adresse_oeffnen": {"label": "Adresse öffnen", "fields": ("source",)},
    "scrollen_zu": {"label": "Scrollen bis sichtbar", "fields": ("role",)},
    "warten_sichtbar": {"label": "Warten bis sichtbar", "fields": ("role", "seconds")},
    "warten_verschwunden": {
        "label": "Warten bis verschwunden",
        "fields": ("role", "seconds"),
    },
    "warten": {"label": "Feste Wartezeit", "fields": ("seconds",)},
    "neu_laden": {"label": "Seite neu laden", "fields": ()},
    "text_auslesen": {"label": "Seitentext auslesen", "fields": ("target",)},
    "anschreiben_erzeugen": {
        "label": "Anschreiben generieren",
        "fields": ("prompt", "source"),
    },
    "dokumentieren": {"label": "Als kontaktiert dokumentieren", "fields": ()},
    "ueberspringen": {"label": "Überspringen und dokumentieren", "fields": ("reason",)},
    "anhalten": {"label": "Anhalten und benachrichtigen", "fields": ("message",)},
    "erneut_pruefen": {"label": "Zustandsprüfung wiederholen", "fields": ()},
}

MAX_WAIT_SECONDS = 600
MAX_PRIORITY = 999


def clean_condition(raw: Any, position: int) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise RegistryError(f"Bedingung {position} ist kein Objekt")
    kind = str(raw.get("kind") or "")
    if kind not in CONDITION_KINDS:
        raise RegistryError(f"Bedingung {position} hat eine unbekannte Art")
    role_id = str(raw.get("role") or "").strip()
    if not ID_PATTERN.match(role_id):
        raise RegistryError(f"Bedingung {position} nennt keine gültige Rolle")
    return {"kind": kind, "role": role_id}


def clean_source(raw: Any, where: str) -> Dict[str, str]:
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: Quelle ist kein Objekt")
    kind = str(raw.get("art") or "")
    if kind not in SOURCE_KINDS:
        raise RegistryError(f"{where}: unbekannte Quelle")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise RegistryError(f"{where}: die Quelle nennt keinen Namen")
    return {"art": kind, "name": name}


def clean_action(raw: Any, position: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RegistryError(f"Aktion {position} ist kein Objekt")
    kind = str(raw.get("type") or "")
    if kind not in ACTIONS:
        raise RegistryError(f"Aktion {position} hat eine unbekannte Art")
    mode = str(raw.get("mode") or MODE_AUTOMATIC)
    if mode not in MODES:
        raise RegistryError(f"Aktion {position} hat einen unbekannten Ausführungsmodus")

    where = f"Aktion {position} ({ACTIONS[kind]['label']})"
    action: Dict[str, Any] = {"type": kind, "mode": mode, "notes": str(raw.get("notes") or "")}
    fields = ACTIONS[kind]["fields"]

    if "role" in fields:
        role_id = str(raw.get("role") or "").strip()
        if not ID_PATTERN.match(role_id):
            raise RegistryError(f"{where}: es ist keine gültige Rolle angegeben")
        action["role"] = role_id
    if "source" in fields:
        action["source"] = clean_source(raw.get("source"), where)
    if "value" in fields:
        value = str(raw.get("value", ""))
        if not value:
            raise RegistryError(f"{where}: es ist kein Wert angegeben")
        action["value"] = value
    if "seconds" in fields:
        try:
            seconds = float(raw.get("seconds"))
        except (TypeError, ValueError):
            raise RegistryError(f"{where}: die Zeitangabe ist keine Zahl") from None
        if not 0 < seconds <= MAX_WAIT_SECONDS:
            raise RegistryError(
                f"{where}: die Zeitangabe muss zwischen 0 und {MAX_WAIT_SECONDS} Sekunden liegen"
            )
        action["seconds"] = round(seconds, 3)
    if "target" in fields:
        target = str(raw.get("target") or "").strip()
        if not ID_PATTERN.match(target):
            raise RegistryError(
                f"{where}: der Variablenname ist nicht zulässig "
                "(Kleinbuchstaben, Ziffern und Unterstrich, mindestens zwei Zeichen)"
            )
        action["target"] = target
    if "prompt" in fields:
        action["prompt"] = str(raw.get("prompt") or "")
    if "message" in fields:
        message = str(raw.get("message") or "").strip()
        if not message:
            raise RegistryError(f"{where}: es ist kein Meldungstext angegeben")
        action["message"] = message
    if "reason" in fields:
        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise RegistryError(f"{where}: es ist kein Grund angegeben")
        action["reason"] = reason
    return action


def clean_state(raw: Any, position: int = 0) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise RegistryError(f"Zustand {position} ist kein Objekt")
    state_id = str(raw.get("id") or "").strip()
    if not ID_PATTERN.match(state_id):
        raise RegistryError(
            f"Die Kennung '{state_id}' ist nicht zulässig "
            "(Kleinbuchstaben, Ziffern und Unterstrich, mindestens zwei Zeichen)"
        )
    label = str(raw.get("label") or "").strip()
    if not label:
        raise RegistryError(f"Zustand '{state_id}' hat keinen Anzeigenamen")
    try:
        priority = int(raw.get("priority", 100))
    except (TypeError, ValueError):
        raise RegistryError(f"Zustand '{state_id}': die Priorität ist keine Zahl") from None
    if not 1 <= priority <= MAX_PRIORITY:
        raise RegistryError(
            f"Zustand '{state_id}': die Priorität muss zwischen 1 und {MAX_PRIORITY} liegen"
        )

    for key in ("all", "any"):
        if raw.get(key) is not None and not isinstance(raw.get(key), list):
            raise RegistryError(f"Zustand '{state_id}': Bedingungen müssen eine Liste sein")
    if not isinstance(raw.get("actions") or [], list):
        raise RegistryError(f"Zustand '{state_id}': Aktionen müssen eine Liste sein")

    conditions_all = [
        clean_condition(entry, index)
        for index, entry in enumerate(raw.get("all") or [], start=1)
    ]
    conditions_any = [
        clean_condition(entry, index)
        for index, entry in enumerate(raw.get("any") or [], start=1)
    ]
    if not conditions_all and not conditions_any:
        # A state without a condition would match everything. That is the
        # opposite of what 2.8 asks for.
        raise RegistryError(f"Zustand '{state_id}' hat keine einzige Bedingung")

    actions = [
        clean_action(entry, index)
        for index, entry in enumerate(raw.get("actions") or [], start=1)
    ]

    return {
        "id": state_id,
        "label": label,
        "priority": priority,
        "enabled": bool(raw.get("enabled", True)),
        "notes": str(raw.get("notes") or ""),
        "all": conditions_all,
        "any": conditions_any,
        "actions": actions,
        "origin": str(raw.get("origin") or ""),
        "updated": str(raw.get("updated") or now()),
    }


def blank_state(state_id: str, label: str) -> Dict[str, Any]:
    return {
        "id": state_id,
        "label": label,
        "priority": 100,
        "enabled": True,
        "notes": "",
        "all": [],
        "any": [],
        "actions": [],
        "origin": "",
        "updated": now(),
    }


def describe_action(action: Dict[str, Any], roles: List[Dict[str, Any]]) -> str:
    """One readable line, for the approval dialogue and the log.

    A secret is named, never shown.
    """
    def role_label(role_id: str) -> str:
        for entry in roles:
            if entry["id"] == role_id:
                return entry["label"]
        return role_id

    def source_label(source: Dict[str, str]) -> str:
        return f"{SOURCE_LABELS.get(source['art'], source['art'])} '{source['name']}'"

    kind = action["type"]
    name = ACTIONS[kind]["label"]
    if kind in ("klicken", "scrollen_zu"):
        return f"{name}: {role_label(action['role'])}"
    if kind == "text_eintragen":
        return f"{name} in {role_label(action['role'])} aus {source_label(action['source'])}"
    if kind == "auswahl_setzen":
        return f"{name} in {role_label(action['role'])} auf '{action['value']}'"
    if kind == "adresse_oeffnen":
        return f"{name} aus {source_label(action['source'])}"
    if kind in ("warten_sichtbar", "warten_verschwunden"):
        return f"{name}: {role_label(action['role'])} (höchstens {action['seconds']} s)"
    if kind == "warten":
        return f"{name}: {action['seconds']} s"
    if kind == "text_auslesen":
        return f"{name} nach '{action['target']}'"
    if kind == "anschreiben_erzeugen":
        return f"{name} mit Kontext aus {source_label(action['source'])}"
    if kind == "ueberspringen":
        return f"{name}: {action['reason']}"
    if kind == "anhalten":
        return f"{name}: {action['message']}"
    return name
