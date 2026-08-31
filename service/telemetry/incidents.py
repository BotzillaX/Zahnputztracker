"""Recording a failed operation (spec 6.8, basic set).

The full version with image sequence, trace archive and reference run
comes with the observability stage. What is here already is the part that
decides whether a failure can be understood afterwards at all: the
address, the visible text, a copy of the page, a picture, and above all
which roles were found and which were expected but missing.

Recording never raises. A failure that also breaks the recording would
leave nothing behind at all.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..registry import model as registry_model
from ..registry import resolve as registry_resolve
from ..storage import paths

# Upper bound on what one incident may hold of the page text.
MAX_TEXT = 200_000
_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}-[a-z0-9_]{1,40}$")


def root() -> Path:
    return paths.roaming_dir() / "incidents"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _folder(incident: str) -> Path:
    if not _NAME.match(incident or ""):
        raise ValueError("unbekannter Vorfall")
    return root() / incident


def _write_json(target: Path, data: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, target)


async def _roles(page: Any, document: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Which roles are on the page right now and which are not.

    This is the heart of the later evaluation: it usually shows without
    opening anything else whether the layout changed, something came in
    between, or the page did not load at all.
    """
    found: List[Dict[str, Any]] = []
    absent: List[Dict[str, Any]] = []
    for role in document["roles"]:
        if not role.get("candidates"):
            continue
        try:
            report = await registry_resolve.check(page, role)
        except Exception as error:  # noqa: BLE001 - one role must not stop the record
            absent.append({"role": role["id"], "label": role["label"], "reason": str(error)})
            continue
        entry = {
            "role": role["id"],
            "label": role["label"],
            "kind": report.get("kind", ""),
            "kind_label": report.get("kind_label", ""),
            "degraded": bool(report.get("degraded")),
            "reason": report.get("reason", ""),
        }
        (found if report.get("found") else absent).append(entry)
    return {"found": found, "missing": absent}


def _summary(data: Dict[str, Any]) -> str:
    lines = [
        f"# Vorfall {data['incident']}",
        "",
        f"- Zeitpunkt: {data['at']}",
        f"- Vorgang: {data['operation']}",
        f"- Grund: {data['reason']}",
        f"- Browser: {registry_model.SCOPE_LABELS.get(data['scope'], data['scope'])}",
        f"- Adresse: {data['url'] or '(keine)'}",
    ]
    if data.get("key"):
        lines.append(f"- Kennung: {data['key']}")
    if data.get("notes"):
        lines.append(f"- Anmerkung: {data['notes']}")
    lines += ["", "## Gefundene Rollen", ""]
    lines += [
        f"- {entry['label']} ({entry['role']}) über {entry['kind_label'] or entry['kind']}"
        + (" — abgestuft" if entry["degraded"] else "")
        for entry in data["roles"]["found"]
    ] or ["- keine"]
    lines += ["", "## Erwartet, aber nicht gefunden", ""]
    lines += [
        f"- {entry['label']} ({entry['role']}): {entry.get('reason') or 'nicht gefunden'}"
        for entry in data["roles"]["missing"]
    ] or ["- keine"]
    lines += ["", "## Dateien", "", "- seite.html (Kopie der Seite)",
              "- bild.png (Bildschirmfoto)", "- text.txt (sichtbarer Text)",
              "- daten.json (alles Obige als Daten)", ""]
    return "\n".join(lines)


async def capture(
    instance: Any,
    document: Dict[str, Any],
    operation: str,
    reason: str,
    key: str = "",
    notes: str = "",
) -> str:
    """Record the situation. Returns the name of the incident, or ''."""
    scope = getattr(instance, "role", "")
    page = getattr(instance, "page", None)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = re.sub(r"[^a-z0-9_]", "_", operation.lower())[:40] or "vorgang"
    incident = f"{stamp}-{slug}"
    folder = root() / incident
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        bus.publish("incident_failed", reason=str(error))
        return ""

    url = ""
    roles: Dict[str, List[Dict[str, Any]]] = {"found": [], "missing": []}
    if page is not None:
        try:
            url = page.url
        except Exception:  # noqa: BLE001
            pass
        try:
            text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            (folder / "text.txt").write_text(str(text)[:MAX_TEXT], encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            html = await page.evaluate("() => window.__ztOverlay.snapshot()")
            (folder / "seite.html").write_text(html, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            # The overlay is never part of saved material (spec 2.5).
            await page.evaluate("() => window.__ztOverlay.hide()")
            try:
                await page.screenshot(path=str(folder / "bild.png"))
            finally:
                await page.evaluate("() => window.__ztOverlay.show()")
        except Exception:  # noqa: BLE001
            pass
        try:
            roles = await _roles(page, document)
        except Exception:  # noqa: BLE001
            pass

    data = {
        "incident": incident,
        "at": _now(),
        "scope": scope,
        "operation": operation,
        "reason": reason,
        "key": key,
        "notes": notes,
        "url": url,
        "roles": roles,
    }
    try:
        _write_json(folder / "daten.json", data)
        (folder / "bericht.md").write_text(_summary(data), encoding="utf-8")
    except OSError as error:
        bus.publish("incident_failed", reason=str(error))
        return incident

    bus.publish(
        "incident_stored",
        incident=incident,
        scope=scope,
        operation=operation,
        reason=reason,
        missing=len(roles["missing"]),
    )
    return incident


def listing(limit: int = 100) -> List[Dict[str, Any]]:
    """Known incidents, newest first."""
    folder = root()
    if not folder.is_dir():
        return []
    entries: List[Dict[str, Any]] = []
    for item in sorted(folder.iterdir(), reverse=True):
        data_file = item / "daten.json"
        if not data_file.is_file():
            continue
        try:
            data = json.loads(data_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append(
            {
                "incident": data.get("incident", item.name),
                "at": data.get("at", ""),
                "scope": data.get("scope", ""),
                "operation": data.get("operation", ""),
                "reason": data.get("reason", ""),
                "key": data.get("key", ""),
                "url": data.get("url", ""),
                "missing": len((data.get("roles") or {}).get("missing") or []),
                "has_screenshot": (item / "bild.png").is_file(),
                "has_snapshot": (item / "seite.html").is_file(),
            }
        )
        if len(entries) >= limit:
            break
    return entries


def read(incident: str) -> Dict[str, Any]:
    data_file = _folder(incident) / "daten.json"
    if not data_file.is_file():
        raise FileNotFoundError("Diesen Vorfall gibt es nicht")
    data = json.loads(data_file.read_text(encoding="utf-8"))
    data["path"] = str(_folder(incident))
    return data


def file_of(incident: str, name: str) -> Path:
    if name not in ("bild.png", "seite.html", "text.txt", "bericht.md", "daten.json"):
        raise ValueError("unbekannte Datei")
    target = _folder(incident) / name
    if not target.is_file():
        raise FileNotFoundError(f"'{name}' ist zu diesem Vorfall nicht gespeichert")
    return target


def forget(incident: str) -> None:
    folder = _folder(incident)
    if folder.parent != root() or not folder.is_dir():
        return
    for entry in folder.iterdir():
        try:
            entry.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
