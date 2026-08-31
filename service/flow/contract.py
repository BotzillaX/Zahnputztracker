"""The dividing line between code and page knowledge (decision 4).

The flows below know a fixed set of role names. What is behind each name
is decided by the user alone, through the picker. This file is the
complete list of what the code expects: nothing else is ever looked for,
and a missing role is reported by name instead of being worked around.

Moving the line later means changing this file and the flow that uses it,
not rebuilding the application.
"""

from __future__ import annotations

from typing import Any, Dict, List

# --------------------------------------------------------------- sign in
SIGNED_IN = "signed_in_marker"
SIGN_IN_ENTRY = "sign_in_entry"
IDENTITY_FIELD = "identity_field"
SECRET_FIELD = "secret_field"
SIGN_IN_SUBMIT = "primary_action_a"
SECOND_FACTOR_MARKER = "second_factor_marker"
SECOND_FACTOR_FIELD = "second_factor_field"

# --------------------------------------------------------------- one item
READY_MARKER = "ready_marker"
ALREADY_MARKER = "already_marker"
OPEN_FORM = "primary_action_b"
MESSAGE_FIELD = "message_field"
SUBMIT_ACTION = "submit_action"
CONFIRMATION_MARKER = "confirmation_marker"

# Every role whose name starts like this is treated as a reason to leave
# an item alone (spec 8.2 asks for several of them).
EXCLUSION_PREFIX = "exclusion_marker"

# Every role whose name starts like this is a form field that is filled
# from the answer pair stored on the role (spec 8.3).
FORM_FIELD_PREFIX = "form_field"

# What each flow cannot do without. Everything else is optional: an
# absent optional role simply means that step does not apply.
REQUIRED_SIGN_IN = (SIGNED_IN, IDENTITY_FIELD, SECRET_FIELD, SIGN_IN_SUBMIT)
REQUIRED_CONTACT = (READY_MARKER, MESSAGE_FIELD, SUBMIT_ACTION)

LABELS = {
    SIGNED_IN: "Merkmal für den angemeldeten Zustand",
    SIGN_IN_ENTRY: "Einstieg in die Anmeldung",
    IDENTITY_FIELD: "Feld für die Kennung",
    SECRET_FIELD: "Feld für das Geheimnis",
    SIGN_IN_SUBMIT: "Knopf, der die Anmeldung abschickt",
    SECOND_FACTOR_MARKER: "Merkmal für die Code-Abfrage",
    SECOND_FACTOR_FIELD: "Feld für den Code",
    READY_MARKER: "Merkmal für die fertig geladene Seite",
    ALREADY_MARKER: "Merkmal für einen bereits erledigten Eintrag",
    OPEN_FORM: "Knopf, der das Formular öffnet",
    MESSAGE_FIELD: "Textfeld der Nachricht",
    SUBMIT_ACTION: "Absende-Element",
    CONFIRMATION_MARKER: "Merkmal für die Bestätigung",
}


def roles_of(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {role["id"]: role for role in document["roles"]}


def taught(role: Dict[str, Any] | None) -> bool:
    return bool(role and role.get("candidates"))


def by_prefix(document: Dict[str, Any], prefix: str) -> List[Dict[str, Any]]:
    """All taught roles of one family, in the order they are stored."""
    return [
        role
        for role in document["roles"]
        if role["id"].startswith(prefix) and role.get("candidates")
    ]


def missing(document: Dict[str, Any], required) -> List[str]:
    """Which required roles are absent or not taught yet."""
    known = roles_of(document)
    return [name for name in required if not taught(known.get(name))]


def readiness(document: Dict[str, Any]) -> Dict[str, Any]:
    """What the user interface shows before a run is started."""
    known = roles_of(document)
    entries = []
    for name, label in LABELS.items():
        role = known.get(name)
        entries.append(
            {
                "role": name,
                "meaning": label,
                "label": role["label"] if role else "",
                "present": role is not None,
                "taught": taught(role),
                "required": name in REQUIRED_SIGN_IN or name in REQUIRED_CONTACT,
            }
        )
    fields = [
        {"role": role["id"], "label": role["label"], "answer": role.get("answer", "")}
        for role in by_prefix(document, FORM_FIELD_PREFIX)
    ]
    return {
        "roles": entries,
        "exclusions": [
            {"role": role["id"], "label": role["label"]}
            for role in by_prefix(document, EXCLUSION_PREFIX)
        ],
        "fields": fields,
        "missing_sign_in": missing(document, REQUIRED_SIGN_IN),
        "missing_contact": missing(document, REQUIRED_CONTACT),
    }
