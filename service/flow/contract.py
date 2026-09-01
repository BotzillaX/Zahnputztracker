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

# ------------------------------------------------------- the result list
# One role, taught with quantity "liste": it marks every entry of the
# visible result list at once. The address behind an entry becomes its
# identifier through the template in the settings (see keys.py).
ITEM_LINK = "item_link"

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
REQUIRED_SEARCH = (ITEM_LINK,)

LABELS = {
    ITEM_LINK: "Verweis eines Eintrags der Trefferliste",
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


def search_readiness(document: Dict[str, Any]) -> Dict[str, Any]:
    """What the search cycle needs, read from the search browser.

    Its one role lives in the other registry, so it is asked for
    separately instead of being mixed into the report above.
    """
    role = roles_of(document).get(ITEM_LINK)
    return {
        "role": ITEM_LINK,
        "meaning": LABELS[ITEM_LINK],
        "label": role["label"] if role else "",
        "present": role is not None,
        "taught": taught(role),
        "many": bool(role and role.get("menge") == "liste"),
        "missing_search": missing(document, REQUIRED_SEARCH),
    }


# --------------------------------------------------------------- the plan
#
# The same names as above, but ordered along the runs that use them and
# with a sentence each. This is what the application shows instead of a
# flat list: which role belongs to which run, in which order it is used,
# and what happens when it is missing.

SEARCH_GROUP = "Suchlauf"
SIGN_IN_GROUP = "Anmeldung"
ITEM_GROUP = "Ein Eintrag"

GROUP_ORDER = {SEARCH_GROUP: 1, SIGN_IN_GROUP: 2, ITEM_GROUP: 3}

STEPS: List[Dict[str, Any]] = [
    {
        "role": ITEM_LINK, "scope": "search", "group": SEARCH_GROUP,
        "quantity": "liste", "required": True, "family": False,
        "description": "Der Verweis einer Zeile der Trefferliste. Mit der Menge "
                       "'liste' werden alle Zeilen auf einmal gelesen. Ohne diese "
                       "Rolle startet der Suchlauf nicht.",
    },
    {
        "role": SIGN_IN_ENTRY, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": False, "family": False,
        "description": "Öffnet die Anmeldemaske, falls sie erst aufgeklappt werden "
                       "muss. Fehlt sie, wird angenommen, dass die Felder schon da sind.",
    },
    {
        "role": IDENTITY_FIELD, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Hier kommt die E-Mail aus den Einstellungen hinein.",
    },
    {
        "role": SECRET_FIELD, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Hier kommt das Passwort aus dem Windows-Anmeldeinformations"
                       "speicher hinein. Es steht in keiner Datei und in keinem Protokoll.",
    },
    {
        "role": SIGN_IN_SUBMIT, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Der Knopf, der die Anmeldung abschickt.",
    },
    {
        "role": SECOND_FACTOR_MARKER, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": False, "family": False,
        "description": "Woran zu erkennen ist, dass ein Code verlangt wird. Ist sie "
                       "sichtbar, hält die Anwendung an und fragt dich nach dem Code.",
    },
    {
        "role": SECOND_FACTOR_FIELD, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": False, "family": False,
        "description": "Das Feld, in das der Code eingetragen wird.",
    },
    {
        "role": SIGNED_IN, "scope": "session", "group": SIGN_IN_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Etwas, das es nur im angemeldeten Zustand gibt (Profilbild, "
                       "dein Name). Daran wird vor jedem Vorgang geprüft, ob die "
                       "Anmeldung noch steht. Die wichtigste Rolle der Anmeldung.",
    },
    {
        "role": READY_MARKER, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Woran zu erkennen ist, dass die Seite eines Eintrags fertig "
                       "geladen ist. Bis dahin wird gewartet, nicht geklickt.",
    },
    {
        "role": EXCLUSION_PREFIX, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": False, "family": True,
        "description": "Ein Grund, diesen Eintrag zu überspringen (zum Beispiel ein "
                       "Hinweis auf einen fehlenden kostenpflichtigen Zugang). Es darf "
                       "mehrere geben, jede bekommt einen eigenen Namen mit diesem Anfang.",
    },
    {
        "role": ALREADY_MARKER, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": False, "family": False,
        "description": "Die Seite meldet selbst, dass hier schon angefragt wurde. "
                       "Dann wird nichts gesendet und der Eintrag gilt als erledigt.",
    },
    {
        "role": OPEN_FORM, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": False, "family": False,
        "description": "Der Knopf, der das Kontaktformular öffnet. Fehlt er, wird "
                       "angenommen, dass das Formular schon offen ist.",
    },
    {
        "role": MESSAGE_FIELD, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Das große Textfeld der Nachricht. Erscheint es nach dem "
                       "Öffnen nicht, gilt der Eintrag als nicht mehr verfügbar und "
                       "ausdrücklich nicht als kontaktiert.",
    },
    {
        "role": FORM_FIELD_PREFIX, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": False, "family": True,
        "description": "Ein weiteres Feld des Formulars (Haustiere, Einzugstermin, "
                       "Personen). Jedem wird ein Antwort-Paar aus den Einstellungen "
                       "zugeordnet. Ohne Zuordnung bleibt das Feld leer.",
    },
    {
        "role": SUBMIT_ACTION, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": True, "family": False,
        "description": "Das Absende-Element. Davor wird immer bis dorthin gescrollt.",
    },
    {
        "role": CONFIRMATION_MARKER, "scope": "session", "group": ITEM_GROUP,
        "quantity": "einzel", "required": False, "family": False,
        "description": "Die Bestätigung nach dem Senden. Fehlt sie, wird ersatzweise "
                       "geprüft, ob das Absende-Element verschwunden bleibt.",
    },
]


def _state_of(document: Dict[str, Any], step: Dict[str, Any]) -> Dict[str, Any]:
    """Live state of one step against the stored registry."""
    entry = dict(step)
    entry["meaning"] = LABELS.get(step["role"], step["role"])
    if step["family"]:
        members = by_prefix(document, step["role"])
        entry["members"] = [
            {"role": role["id"], "label": role["label"],
             "candidates": len(role.get("candidates") or []),
             "answer": role.get("answer", "")}
            for role in members
        ]
        entry["present"] = bool(members)
        entry["taught"] = bool(members)
        entry["label"] = ""
        entry["candidates"] = sum(len(role.get("candidates") or []) for role in members)
        entry["quantity_is"] = ""
        entry["quantity_ok"] = True
        return entry
    role = roles_of(document).get(step["role"])
    entry["members"] = []
    entry["present"] = role is not None
    entry["taught"] = taught(role)
    entry["label"] = role["label"] if role else ""
    entry["candidates"] = len(role.get("candidates") or []) if role else 0
    entry["quantity_is"] = role.get("menge", "") if role else ""
    entry["quantity_ok"] = (role is None) or role.get("menge") == step["quantity"]
    return entry


def plan(scope: str, document: Dict[str, Any]) -> Dict[str, Any]:
    """What this browser is used for, in the order it happens."""
    groups: Dict[str, Dict[str, Any]] = {}
    for step in STEPS:
        if step["scope"] != scope:
            continue
        group = groups.setdefault(
            step["group"],
            {"group": step["group"], "order": GROUP_ORDER.get(step["group"], 99),
             "steps": []},
        )
        found = _state_of(document, step)
        found["position"] = len(group["steps"]) + 1
        group["steps"].append(found)
    ordered = sorted(groups.values(), key=lambda item: item["order"])
    open_required = [
        step["meaning"]
        for group in ordered for step in group["steps"]
        if step["required"] and (not step["taught"] or not step["quantity_ok"])
    ]
    known = {step["role"] for step in STEPS if step["scope"] == scope}
    families = tuple(
        step["role"] for step in STEPS if step["scope"] == scope and step["family"]
    )
    extra = [
        {"role": role["id"], "label": role["label"],
         "candidates": len(role.get("candidates") or [])}
        for role in document["roles"]
        if role["id"] not in known and not role["id"].startswith(families)
    ]
    return {"scope": scope, "groups": ordered, "open": open_required, "extra": extra}
