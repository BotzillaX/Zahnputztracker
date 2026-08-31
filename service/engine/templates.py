"""State templates (decision 5).

Templates are a convenience, never a source of truth. They live in their
own file next to the registry, they can be deleted one by one, and one
switch turns the whole idea off. Nothing here ever runs on its own: a
template only becomes a state when the user loads it, and from then on it
is an ordinary state he can change or delete.

A template refers to the neutral role slots of the base catalogue and
contains no recognition candidate. Loading one therefore cannot make the
application find anything by itself.
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..registry import model
from ..registry import store as registry_store
from ..storage import paths

VERSION = 1


class TemplateError(ValueError):
    """Raised when a template cannot be used as asked."""


def _state(
    state_id: str,
    label: str,
    priority: int,
    all_of: List[Dict[str, str]],
    actions: List[Dict[str, Any]],
    any_of: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    body = model.blank_state(state_id, label)
    body["priority"] = priority
    body["all"] = all_of
    body["any"] = any_of or []
    body["actions"] = actions
    return body


def _visible(role: str) -> Dict[str, str]:
    return {"kind": model.VISIBLE, "role": role}


def _hidden(role: str) -> Dict[str, str]:
    return {"kind": model.INVISIBLE, "role": role}


def _act(kind: str, **fields: Any) -> Dict[str, Any]:
    return {"type": kind, "mode": fields.pop("mode", model.MODE_AUTOMATIC), **fields}


# The shipped set. Deliberately small: these are the situations that occur
# on almost any page, written against the neutral catalogue.
DEFAULTS: List[Dict[str, Any]] = [
    {
        "id": "vorlage_zustimmung",
        "label": "Zustimmung steht im Weg",
        "scope": model.SEARCH,
        "description": "Solange die Zustimmung sichtbar ist, wird sie bestätigt.",
        "state": _state(
            "zustimmung_offen",
            "Zustimmung offen",
            10,
            [_visible("consent_accept")],
            [
                _act("klicken", role="consent_accept"),
                _act("warten_verschwunden", role="consent_accept", seconds=10),
                _act("erneut_pruefen"),
            ],
        ),
    },
    {
        "id": "vorlage_liste_leer",
        "label": "Liste ist leer",
        "scope": model.SEARCH,
        "description": "Der Leer-Hinweis steht da: kurz warten und neu laden.",
        "state": _state(
            "liste_leer",
            "Liste leer",
            20,
            [_visible("empty_marker")],
            [_act("warten", seconds=10), _act("neu_laden")],
        ),
    },
    {
        "id": "vorlage_liste_steht",
        "label": "Liste steht bereit",
        "scope": model.SEARCH,
        "description": "Ergebnisliste sichtbar, nichts steht im Weg. Keine Aktion.",
        "state": _state(
            "liste_steht",
            "Liste steht",
            30,
            [_visible("list_container"), _hidden("consent_accept")],
            [],
        ),
    },
    {
        "id": "vorlage_nicht_angemeldet",
        "label": "Nicht angemeldet",
        "scope": model.SESSION,
        "description": "Der Einstieg zur Anmeldung ist sichtbar, das Merkmal fehlt.",
        "state": _state(
            "nicht_angemeldet",
            "Nicht angemeldet",
            10,
            [_hidden("signed_in_marker"), _visible("sign_in_entry")],
            [
                _act("klicken", role="sign_in_entry"),
                _act("warten_sichtbar", role="identity_field", seconds=20),
                _act("erneut_pruefen"),
            ],
        ),
    },
    {
        "id": "vorlage_anmeldemaske",
        "label": "Anmeldemaske offen",
        "scope": model.SESSION,
        "description": "Kennung und Geheimnis eintragen, danach die Hauptaktion.",
        "state": _state(
            "anmeldemaske",
            "Anmeldemaske",
            20,
            [_visible("identity_field"), _visible("secret_field")],
            [
                _act(
                    "text_eintragen",
                    role="identity_field",
                    source={"art": model.SOURCE_CONFIG, "name": "Zugangskennung"},
                ),
                _act(
                    "text_eintragen",
                    role="secret_field",
                    source={"art": model.SOURCE_SECRET, "name": "account-password"},
                ),
                _act("klicken", role="primary_action_a", mode=model.MODE_APPROVAL),
                _act("erneut_pruefen"),
            ],
        ),
    },
    {
        "id": "vorlage_zweitfaktor",
        "label": "Zweitfaktor verlangt",
        "scope": model.SESSION,
        "description": "Anhalten und melden, statt irgendetwas zu versuchen.",
        "state": _state(
            "zweitfaktor",
            "Zweitfaktor verlangt",
            5,
            [_visible("second_factor_marker")],
            [_act("anhalten", message="Der Zugang verlangt einen Code")],
        ),
    },
]


def file_path() -> Path:
    return paths.roaming_dir() / "vorlagen.json"


def _defaults_document() -> Dict[str, Any]:
    return {"version": VERSION, "enabled": True, "templates": deepcopy(DEFAULTS)}


def _write(document: Dict[str, Any]) -> None:
    target = file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load() -> Dict[str, Any]:
    """The template file, created from the shipped set when missing."""
    target = file_path()
    if not target.exists():
        document = _defaults_document()
        _write(document)
        return document
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TemplateError(f"Die Vorlagendatei ist unlesbar. Datei: {target}") from error
    templates = stored.get("templates")
    if not isinstance(templates, list):
        raise TemplateError("Die Vorlagendatei enthält keine Liste von Vorlagen")
    return {
        "version": int(stored.get("version") or VERSION),
        "enabled": bool(stored.get("enabled", True)),
        "templates": templates,
        "file": str(target),
    }


def set_enabled(enabled: bool) -> Dict[str, Any]:
    """The switch of decision 5: off means the templates are ignored."""
    document = load()
    document["enabled"] = bool(enabled)
    _write({k: document[k] for k in ("version", "enabled", "templates")})
    return load()


def drop(template_id: str) -> Dict[str, Any]:
    document = load()
    remaining = [entry for entry in document["templates"] if entry.get("id") != template_id]
    if len(remaining) == len(document["templates"]):
        raise TemplateError(f"Die Vorlage '{template_id}' gibt es nicht")
    _write({"version": document["version"], "enabled": document["enabled"], "templates": remaining})
    return load()


def reset() -> Dict[str, Any]:
    """Put the shipped set back, for example after deleting too much."""
    document = _defaults_document()
    document["enabled"] = load()["enabled"]
    _write(document)
    return load()


def offered(scope: str) -> List[Dict[str, Any]]:
    """Templates for one instance, empty when the switch is off."""
    document = load()
    if not document["enabled"]:
        return []
    return [entry for entry in document["templates"] if entry.get("scope") == scope]


def apply(scope: str, template_id: str) -> Dict[str, Any]:
    """Turn a template into a real state of that instance."""
    model.check_scope(scope)
    document = load()
    if not document["enabled"]:
        raise TemplateError("Die Vorlagen sind abgeschaltet")
    for entry in document["templates"]:
        if entry.get("id") == template_id and entry.get("scope") == scope:
            template = entry
            break
    else:
        raise TemplateError(f"Die Vorlage '{template_id}' gibt es für diese Instanz nicht")

    registry = registry_store.load(scope)
    known = {role["id"] for role in registry["roles"]}
    body = deepcopy(template["state"])
    wanted = {condition["role"] for condition in body["all"] + body["any"]}
    wanted |= {action["role"] for action in body["actions"] if "role" in action}
    missing = sorted(wanted - known)
    if missing:
        raise TemplateError(
            "Diese Vorlage braucht Rollen, die es hier nicht gibt: "
            + ", ".join(missing)
            + ". Grundkatalog ergänzen oder die Vorlage nach dem Laden anpassen."
        )

    body["id"] = registry_store.free_state_id(scope, body["id"])
    body["origin"] = template_id
    return registry_store.put_state(scope, body, note=f"Vorlage {template_id} geladen")
