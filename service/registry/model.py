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

    # States belong to the next stage. The field exists from the start so
    # a document written today stays readable then.
    states = raw.get("states") or []
    if not isinstance(states, list):
        raise RegistryError("Zustände müssen eine Liste sein")

    return {"scope": scope, "version": int(raw.get("version") or 0), "roles": roles, "states": states}


def empty_document(scope: str) -> Dict[str, Any]:
    check_scope(scope)
    return {"scope": scope, "version": 0, "updated": now(), "roles": [], "states": []}
