"""Recording a failed or noticeable operation (spec 6.8).

A saved incident has to be readable without knowing any tool. One folder
holds everything about one situation:

* the state at the soft threshold and, if it came to that, at the hard
  one (picture, copy of the page, visible text, address, window and
  viewport size, zoom, sign-in status)
* the image sequence from the ring buffer, the two minutes before
* the recording of this cycle and of the cycles before it
* the last successful reference run of the same operation
* a short report in plain German, whose centre is which roles were found
  and which were expected and missing

Recording never raises. A failure that also broke the recording would
leave nothing behind at all.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..registry import model as registry_model
from ..registry import resolve as registry_resolve
from ..storage import paths
from . import frames, tracing

# Upper bound on what one incident may hold of the page text.
MAX_TEXT = 200_000
_NAME = re.compile(r"^[0-9]{8}T[0-9]{6}-[a-z0-9_]{1,40}$")
_STAGE = re.compile(r"^[a-z0-9_]{1,20}$")

SOFT = "weich"
HARD = "hart"
STAGE_LABELS = {SOFT: "weiche Schwelle", HARD: "harte Schwelle", "": "Erfassung"}


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
        json.dump(data, stream, ensure_ascii=False, indent=2, default=str)
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


_MEASURE = """() => ({
  url: location.href,
  title: document.title || '',
  viewport: {width: window.innerWidth, height: window.innerHeight},
  window: {width: window.outerWidth, height: window.outerHeight},
  zoom: window.devicePixelRatio,
  visual: window.visualViewport ? window.visualViewport.scale : 1,
  scroll: {x: window.scrollX, y: window.scrollY}
})"""


async def _signed_in(page: Any, document: Dict[str, Any]) -> Optional[bool]:
    """The sign-in status, if the user taught what it looks like."""
    # Local import: the flow knows the telemetry, not the other way round.
    from ..flow import contract

    role = contract.roles_of(document).get(contract.SIGNED_IN)
    if not contract.taught(role):
        return None
    try:
        report = await registry_resolve.check(page, role)
    except Exception:  # noqa: BLE001
        return None
    return bool(report.get("found"))


async def _state(page: Any, document: Dict[str, Any], folder: Path) -> Dict[str, Any]:
    """One complete state capture into ``folder`` (6.4)."""
    data: Dict[str, Any] = {"url": "", "roles": {"found": [], "missing": []}}
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return data
    try:
        data["url"] = page.url
    except Exception:  # noqa: BLE001
        pass
    try:
        measured = await page.evaluate(_MEASURE)
        if isinstance(measured, dict):
            data.update(measured)
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
        data["roles"] = await _roles(page, document)
    except Exception:  # noqa: BLE001
        pass
    try:
        signed = await _signed_in(page, document)
        if signed is not None:
            data["signed_in"] = signed
    except Exception:  # noqa: BLE001
        pass
    return data


def _stage_folder(folder: Path, index: int, stage: str) -> Path:
    """The first capture lies in the folder itself, later ones beside it."""
    if index == 0:
        return folder
    safe = stage if _STAGE.match(stage or "") else "weitere"
    return folder / f"stufe{index + 1}-{safe}"


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

    context = data.get("context") or {}
    if context:
        lines += ["", "## Laufzeit", ""]
        if context.get("span"):
            lines.append(f"- Gemessener Vorgang: {context['span']}")
        if context.get("elapsed_ms"):
            lines.append(f"- Gelaufen: {round(float(context['elapsed_ms']) / 1000, 1)} s")
        if context.get("median_ms"):
            lines.append(
                f"- Üblich: {round(float(context['median_ms']) / 1000, 1)} s "
                f"(aus {context.get('n', 0)} Messungen)"
            )
        if context.get("threshold_ms"):
            lines.append(
                f"- Weiche Schwelle: {round(float(context['threshold_ms']) / 1000, 1)} s"
            )
        if context.get("limit_s"):
            lines.append(f"- Hartes Zeitlimit: {context['limit_s']} s")

    for index, stage in enumerate(data.get("stages") or []):
        title = STAGE_LABELS.get(stage.get("stage", ""), stage.get("stage", ""))
        where = stage.get("folder") or "(Hauptordner)"
        lines += ["", f"## Zustand bei der {title}", "",
                  f"- Zeitpunkt: {stage.get('at', '')}",
                  f"- Adresse: {stage.get('url') or '(keine)'}",
                  f"- Dateien in: {where}"]
        viewport = stage.get("viewport") or {}
        window = stage.get("window") or {}
        if viewport:
            lines.append(
                f"- Sichtbarer Bereich: {viewport.get('width')} x {viewport.get('height')}"
            )
        if window:
            lines.append(f"- Fenster: {window.get('width')} x {window.get('height')}")
        if stage.get("zoom"):
            lines.append(f"- Zoomstufe: {stage['zoom']}")
        if stage.get("signed_in") is not None:
            lines.append(f"- Angemeldet: {'ja' if stage['signed_in'] else 'nein'}")
        roles = stage.get("roles") or {"found": [], "missing": []}
        lines += ["", "### Gefundene Rollen", ""]
        lines += [
            f"- {entry['label']} ({entry['role']}) über {entry['kind_label'] or entry['kind']}"
            + (" (abgestuft)" if entry.get("degraded") else "")
            for entry in roles.get("found") or []
        ] or ["- keine"]
        lines += ["", "### Erwartet, aber nicht gefunden", ""]
        lines += [
            f"- {entry['label']} ({entry['role']}): {entry.get('reason') or 'nicht gefunden'}"
            for entry in roles.get("missing") or []
        ] or ["- keine"]

    material = data.get("material") or {}
    lines += ["", "## Mitgeschriebenes Material", ""]
    lines.append(f"- Bildfolge: {material.get('frames', 0)} Bilder in bilder/")
    lines.append(f"- Aufzeichnungen: {material.get('traces', 0)} Zyklen in aufzeichnung/")
    reference = material.get("reference")
    if reference:
        lines.append(
            f"- Letzter erfolgreicher Referenzdurchlauf von {reference.get('name')} "
            f"vom {reference.get('at')}: referenz/{reference.get('file')}"
        )
    else:
        lines.append("- Referenzdurchlauf: keiner vorhanden")

    lines += ["", "## Dateien", "",
              "- seite.html (Kopie der Seite)", "- bild.png (Bildschirmfoto)",
              "- text.txt (sichtbarer Text)", "- daten.json (alles Obige als Daten)", ""]
    return "\n".join(lines)


def _save(folder: Path, data: Dict[str, Any]) -> None:
    _write_json(folder / "daten.json", data)
    (folder / "bericht.md").write_text(_summary(data), encoding="utf-8")


async def capture(
    instance: Any,
    document: Dict[str, Any],
    operation: str,
    reason: str,
    key: str = "",
    notes: str = "",
    stage: str = "",
    context: Optional[Dict[str, Any]] = None,
    material: bool = False,
    span_name: str = "",
    history: int = tracing.DEFAULT_HISTORY,
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

    captured: Dict[str, Any] = {"url": "", "roles": {"found": [], "missing": []}}
    if page is not None:
        captured = await _state(page, document, folder)

    data: Dict[str, Any] = {
        "incident": incident,
        "at": _now(),
        "scope": scope,
        "operation": operation,
        "reason": reason,
        "key": key,
        "notes": notes,
        "url": captured.get("url", ""),
        "context": dict(context or {}),
        "roles": captured.get("roles", {"found": [], "missing": []}),
        "stages": [{"stage": stage, "at": _now(), "folder": "", **captured}],
        "material": {"frames": 0, "traces": 0, "reference": None},
    }
    if material:
        data["material"] = collect(incident, scope, span_name=span_name, history=history)
    try:
        _save(folder, data)
    except OSError as error:
        bus.publish("incident_failed", reason=str(error))
        return incident

    bus.publish(
        "incident_stored",
        incident=incident,
        scope=scope,
        operation=operation,
        reason=reason,
        missing=len((data["roles"] or {}).get("missing") or []),
    )
    return incident


async def add_stage(
    incident: str,
    instance: Any,
    document: Dict[str, Any],
    stage: str,
    reason: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """Add a further state capture to an incident already open (6.4).

    Comparing the two captures is what shows whether the page changed
    while it hung or simply stood still.
    """
    try:
        folder = _folder(incident)
    except ValueError:
        return False
    data_file = folder / "daten.json"
    if not data_file.is_file():
        return False
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    page = getattr(instance, "page", None)
    if page is None:
        return False
    index = len(data.get("stages") or [])
    stage_dir = _stage_folder(folder, index, stage)
    captured = await _state(page, document, stage_dir)
    data.setdefault("stages", []).append(
        {
            "stage": stage,
            "at": _now(),
            "folder": "" if stage_dir == folder else stage_dir.name,
            **captured,
        }
    )
    if reason:
        data["reason"] = reason
    if context:
        data["context"] = {**(data.get("context") or {}), **context}
    try:
        _save(folder, data)
    except OSError:
        return False
    bus.publish("incident_extended", incident=incident, stage=stage)
    return True


def collect(
    incident: str,
    scope: str,
    span_name: str = "",
    history: int = tracing.DEFAULT_HISTORY,
) -> Dict[str, Any]:
    """Put the image sequence, the recordings and the reference beside it."""
    try:
        folder = _folder(incident)
    except ValueError:
        return {"frames": 0, "traces": 0, "reference": None}
    material: Dict[str, Any] = {"frames": 0, "traces": 0, "reference": None}
    try:
        material["frames"] = frames.dump(scope, folder / "bilder")
    except Exception:  # noqa: BLE001
        pass
    try:
        target = folder / "aufzeichnung"
        copied = 0
        for source in tracing.recent(scope, max(1, history + 1)):
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target / source.name)
            copied += 1
        material["traces"] = copied
    except Exception:  # noqa: BLE001
        pass
    if span_name:
        try:
            reference = tracing.reference_for(span_name, scope)
            if reference:
                destination = folder / "referenz"
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(reference["path"], destination / reference["file"])
                material["reference"] = {
                    key: reference[key] for key in ("name", "scope", "at", "file")
                }
        except Exception:  # noqa: BLE001
            pass
    return material


def attach_material(
    incident: str, scope: str, span_name: str = "", history: int = tracing.DEFAULT_HISTORY
) -> Dict[str, Any]:
    """Collect the material and write it into the stored incident."""
    material = collect(incident, scope, span_name=span_name, history=history)
    try:
        folder = _folder(incident)
        data = json.loads((folder / "daten.json").read_text(encoding="utf-8"))
        data["material"] = material
        _save(folder, data)
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    return material


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
        context = data.get("context") or {}
        material = data.get("material") or {}
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
                "stages": len(data.get("stages") or []),
                "span": context.get("span", ""),
                "elapsed_ms": context.get("elapsed_ms", 0),
                "median_ms": context.get("median_ms", 0),
                "frames": material.get("frames", 0),
                "traces": material.get("traces", 0),
                "reference": bool(material.get("reference")),
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
    data["files"] = files_of(incident)
    return data


def files_of(incident: str) -> List[Dict[str, Any]]:
    """Everything the incident holds, as names that may be requested."""
    folder = _folder(incident)
    out: List[Dict[str, Any]] = []
    if not folder.is_dir():
        return out
    for item in sorted(folder.rglob("*")):
        if not item.is_file():
            continue
        try:
            name = item.relative_to(folder).as_posix()
        except ValueError:
            continue
        out.append({"name": name, "bytes": item.stat().st_size})
    return out


def file_of(incident: str, name: str) -> Path:
    """One file of an incident, and never one above its folder."""
    folder = _folder(incident).resolve()
    candidate = (folder / name).resolve()
    if folder not in candidate.parents:
        raise ValueError("unbekannte Datei")
    if not candidate.is_file():
        raise FileNotFoundError(f"'{name}' ist zu diesem Vorfall nicht gespeichert")
    return candidate


def size_bytes() -> int:
    folder = root()
    if not folder.is_dir():
        return 0
    total = 0
    for item in folder.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def names(oldest_first: bool = True) -> List[str]:
    folder = root()
    if not folder.is_dir():
        return []
    found = [item.name for item in folder.iterdir() if item.is_dir() and _NAME.match(item.name)]
    return sorted(found, reverse=not oldest_first)


def older_than(days: int) -> List[str]:
    """Incidents past the retention, oldest first."""
    if days <= 0:
        return []
    edge = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y%m%dT%H%M%S")
    return [name for name in names() if name[:15] < edge]


def forget(incident: str) -> None:
    folder = _folder(incident)
    if folder.parent != root() or not folder.is_dir():
        return
    shutil.rmtree(folder, ignore_errors=True)
