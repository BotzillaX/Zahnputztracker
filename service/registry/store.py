"""Storing the registry (spec 2.10).

One document per browser instance, in %APPDATA%, never next to the
program and never in the repository. Every save keeps the previous
version, so a mistake made while teaching costs one click, not a day.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage import paths
from . import model
from .model import RegistryError

MAX_HISTORY = 50


def root() -> Path:
    return paths.roaming_dir() / "registry"


def document_file(scope: str) -> Path:
    return root() / f"{model.check_scope(scope)}.json"


def history_dir(scope: str) -> Path:
    return root() / "history" / model.check_scope(scope)


def export_dir() -> Path:
    return root() / "export"


def _write(target: Path, data: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load(scope: str) -> Dict[str, Any]:
    """The current registry of one instance. Missing means empty (2.2)."""
    target = document_file(scope)
    if not target.exists():
        return model.empty_document(scope)
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A damaged file is a case for the user, not a reason to guess.
        raise RegistryError(
            "Die gespeicherte Registrierung ist unlesbar. "
            f"Datei: {target}"
        ) from None
    document = model.clean_document(stored, scope)
    document["updated"] = str(stored.get("updated") or model.now())
    return document


def save(scope: str, candidate: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    """Validate, archive the previous version, write the new one."""
    document = model.clean_document(candidate, scope)
    current = document_file(scope)

    previous_version = 0
    if current.exists():
        try:
            previous = json.loads(current.read_text(encoding="utf-8"))
            previous_version = int(previous.get("version") or 0)
            _archive(scope, previous)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            # An unreadable predecessor must not block the correction.
            previous_version = 0

    document["version"] = previous_version + 1
    document["updated"] = model.now()
    document["note"] = str(note or "")
    _write(current, document)
    _trim_history(scope)
    return document


def _archive(scope: str, document: Dict[str, Any]) -> None:
    version = int(document.get("version") or 0)
    stamp = re.sub(r"[^0-9A-Za-z]", "", str(document.get("updated") or model.now()))
    target = history_dir(scope) / f"{version:04d}-{stamp}.json"
    _write(target, document)


def _trim_history(scope: str) -> None:
    files = sorted(history_dir(scope).glob("*.json"))
    for stale in files[:-MAX_HISTORY]:
        try:
            stale.unlink()
        except OSError:
            pass


def history(scope: str) -> List[Dict[str, Any]]:
    """Older versions, newest first, with what they contained."""
    entries: List[Dict[str, Any]] = []
    for file in sorted(history_dir(scope).glob("*.json"), reverse=True):
        try:
            stored = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "version": int(stored.get("version") or 0),
                "updated": str(stored.get("updated") or ""),
                "note": str(stored.get("note") or ""),
                "roles": len(stored.get("roles") or []),
                "file": file.name,
            }
        )
    return entries


def restore(scope: str, version: int) -> Dict[str, Any]:
    """Bring an older version back as a new version.

    Going back never destroys anything: the state before the rollback is
    archived like any other change.
    """
    for file in history_dir(scope).glob("*.json"):
        try:
            stored = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if int(stored.get("version") or 0) == int(version):
            return save(scope, stored, note=f"Rücksetzen auf Fassung {version}")
    raise RegistryError(f"Fassung {version} ist nicht mehr vorhanden")


def export(scope: str) -> Dict[str, Any]:
    """Write a copy the user can keep or move to another machine."""
    document = load(scope)
    stamp = re.sub(r"[^0-9]", "", model.now())
    target = export_dir() / f"{scope}-{stamp}.json"
    _write(target, document)
    return {"path": str(target), "roles": len(document["roles"])}


def import_document(scope: str, payload: Any) -> Dict[str, Any]:
    """Take a document from a file, check it, store it as a new version."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise RegistryError(f"Die Datei ist kein gültiges JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RegistryError("Die Datei enthält keine Registrierung")
    written = str(payload.get("scope") or scope)
    if written != scope:
        raise RegistryError(
            f"Die Datei gehört zu {model.SCOPE_LABELS.get(written, written)}, "
            f"nicht zu {model.SCOPE_LABELS[scope]}"
        )
    return save(scope, payload, note="Import")


def import_file(scope: str, file_path: str) -> Dict[str, Any]:
    source = Path(file_path)
    if not source.is_file():
        raise RegistryError(f"Datei nicht gefunden: {file_path}")
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise RegistryError(f"Datei nicht lesbar: {error}") from error
    return import_document(scope, text)


# ------------------------------------------------------------- single roles


def role(scope: str, role_id: str) -> Optional[Dict[str, Any]]:
    for entry in load(scope)["roles"]:
        if entry["id"] == role_id:
            return entry
    return None


def put_role(scope: str, candidate: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    """Add or replace one role, keeping the order of the others."""
    document = load(scope)
    cleaned = model.clean_role(candidate, scope)
    cleaned["updated"] = model.now()
    roles = document["roles"]
    for index, entry in enumerate(roles):
        if entry["id"] == cleaned["id"]:
            roles[index] = cleaned
            break
    else:
        roles.append(cleaned)
    return save(scope, document, note=note or f"Rolle {cleaned['id']} gespeichert")


def drop_role(scope: str, role_id: str) -> Dict[str, Any]:
    document = load(scope)
    remaining = [entry for entry in document["roles"] if entry["id"] != role_id]
    if len(remaining) == len(document["roles"]):
        raise RegistryError(f"Rolle '{role_id}' ist nicht vorhanden")
    document["roles"] = remaining
    return save(scope, document, note=f"Rolle {role_id} gelöscht")


def add_catalogue(scope: str) -> Dict[str, Any]:
    """Add the empty base catalogue without touching taught roles."""
    document = load(scope)
    known = {entry["id"] for entry in document["roles"]}
    added = [entry for entry in model.catalogue(scope) if entry["id"] not in known]
    document["roles"] = document["roles"] + added
    return save(scope, document, note=f"Grundkatalog ergänzt ({len(added)} Rollen)")


def free_id(scope: str, wanted: str = "rolle") -> str:
    """A free, neutral identifier for a newly created role."""
    known = {entry["id"] for entry in load(scope)["roles"]}
    base = re.sub(r"[^a-z0-9_]", "_", wanted.lower()) or "rolle"
    if not model.ID_PATTERN.match(base):
        base = "rolle"
    if base not in known:
        return base
    index = 2
    while f"{base}_{index}" in known:
        index += 1
    return f"{base}_{index}"
