"""The report (spec 6.9).

Markdown is an output format here, never a storage format. Everything in
it is read back out of the event log, so a report can be produced again
at any time for any day that is still kept.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from ..registry import model as registry_model
from ..storage import paths
from . import journal, stats


def directory() -> Path:
    return paths.roaming_dir() / "reports"


def _seconds(ms: Any) -> str:
    try:
        return f"{round(float(ms) / 1000, 1)} s"
    except (TypeError, ValueError):
        return "?"


def _collect(day: str) -> Dict[str, Any]:
    records = journal.read(day)
    ends = [item for item in records if item.get("ev") == "span_end"]
    slow = [item for item in records if item.get("ev") == "span_slow"]
    blocked = [item for item in records if item.get("ev") == "span_blocked"]
    degraded = [item for item in records if item.get("ev") == "degraded"]
    stored = [item for item in records if item.get("ev") == "incident_stored"]
    finished = [item for item in records if item.get("ev") == "item_finished"]
    return {
        "records": records,
        "ends": ends,
        "slow": slow,
        "blocked": blocked,
        "degraded": degraded,
        "incidents": stored,
        "items": finished,
    }


def _by_name(ends: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in ends:
        key = f"{item.get('name', '')}|{item.get('scope', '')}"
        entry = grouped.setdefault(
            key,
            {"name": item.get("name", ""), "scope": item.get("scope", ""), "n": 0,
             "slow": 0, "critical": 0, "errors": 0, "total_ms": 0.0, "max_ms": 0.0,
             "median_ms": 0.0},
        )
        entry["n"] += 1
        duration = float(item.get("dur_ms") or 0)
        entry["total_ms"] += duration
        entry["max_ms"] = max(entry["max_ms"], duration)
        if item.get("anomaly") == stats.ELEVATED:
            entry["slow"] += 1
        elif item.get("anomaly") == stats.CRITICAL:
            entry["critical"] += 1
        if item.get("status") not in ("ok", None):
            entry["errors"] += 1
        baseline = item.get("baseline") or {}
        entry["median_ms"] = baseline.get("p50", entry["median_ms"])
    return sorted(grouped.values(), key=lambda entry: entry["name"])


def build(day: str = "") -> str:
    """The report of one day as Markdown."""
    day = day or journal.today()
    data = _collect(day)
    made = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    lines = [
        f"# Bericht {day}",
        "",
        f"Erzeugt am {made}.",
        "",
        "## Überblick",
        "",
        f"- Vorgänge gemessen: {len(data['ends'])}",
        f"- Über der weichen Schwelle: {len(data['slow'])}",
        f"- Blockiert: {len(data['blocked'])}",
        f"- Vorfälle festgehalten: {len(data['incidents'])}",
        f"- Abgestufte Erkennungen: {len(data['degraded'])}",
        "",
        "## Laufzeiten je Vorgang",
        "",
        "| Vorgang | Browser | Anzahl | Mittel | Längster | Referenz | erhöht | kritisch | Fehler |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for entry in _by_name(data["ends"]):
        mean = entry["total_ms"] / entry["n"] if entry["n"] else 0
        lines.append(
            f"| {entry['name']} "
            f"| {registry_model.SCOPE_LABELS.get(entry['scope'], entry['scope'] or '-')} "
            f"| {entry['n']} | {_seconds(mean)} | {_seconds(entry['max_ms'])} "
            f"| {_seconds(entry['median_ms'])} | {entry['slow']} | {entry['critical']} "
            f"| {entry['errors']} |"
        )
    if not data["ends"]:
        lines.append("| (nichts gemessen) | | | | | | | | |")

    lines += ["", "## Auffällige Vorgänge", ""]
    noticeable = [item for item in data["ends"] if item.get("anomaly")]
    if not noticeable:
        lines.append("Keiner.")
    for item in noticeable[-50:]:
        baseline = item.get("baseline") or {}
        lines.append(
            f"- {str(item.get('ts', ''))[11:19]} {item.get('name')} "
            f"({stats.LEVEL_LABELS.get(item.get('anomaly'), item.get('anomaly'))}): "
            f"{_seconds(item.get('dur_ms'))} statt {_seconds(baseline.get('p50'))}"
            + (f", Vorfall {item['incident']}" if item.get("incident") else "")
        )

    lines += ["", "## Blockaden", ""]
    if not data["blocked"]:
        lines.append("Keine.")
    for item in data["blocked"]:
        lines.append(
            f"- {str(item.get('ts', ''))[11:19]} {item.get('name')}: "
            f"{_seconds(item.get('elapsed_ms'))} über dem Limit von {item.get('limit_s')} s"
            + (f", Vorfall {item['incident']}" if item.get("incident") else "")
        )

    lines += ["", "## Abgestufte Erkennungsmerkmale", ""]
    if not data["degraded"]:
        lines.append("Keine.")
    else:
        counted: Dict[str, int] = {}
        for item in data["degraded"]:
            label = f"{item.get('label') or item.get('role')} ({item.get('kind_label', '')})"
            counted[label] = counted.get(label, 0) + 1
        for label, count in sorted(counted.items(), key=lambda pair: -pair[1]):
            lines.append(f"- {label}: {count} mal")

    lines += ["", "## Einträge", ""]
    if not data["items"]:
        lines.append("Keiner abgeschlossen.")
    for item in data["items"][-50:]:
        lines.append(
            f"- {str(item.get('ts', ''))[11:19]} {item.get('key', '')}: "
            f"{item.get('status', '')} ({item.get('reason', '')})"
        )

    lines += ["", "## Aufzeichnungen", ""]
    if not data["incidents"]:
        lines.append("Keine.")
    for item in data["incidents"]:
        lines.append(
            f"- {item.get('incident', '')}: {item.get('operation', '')}, "
            f"{item.get('reason', '')} ({item.get('missing', 0)} Rollen nicht gefunden)"
        )
    lines.append("")
    return "\n".join(lines)


def write(day: str = "") -> Path:
    """Store the report beside the logs and return its path."""
    day = day or journal.today()
    folder = directory()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"bericht-{day}.md"
    target.write_text(build(day), encoding="utf-8")
    return target


def listing() -> List[Dict[str, Any]]:
    folder = directory()
    if not folder.is_dir():
        return []
    out = []
    for item in sorted(folder.glob("bericht-*.md"), reverse=True):
        try:
            out.append({"name": item.name, "day": item.stem[8:], "bytes": item.stat().st_size})
        except OSError:
            continue
    return out


def file_of(name: str) -> Path:
    folder = directory().resolve()
    candidate = (folder / name).resolve()
    if candidate.parent != folder or not candidate.is_file():
        raise FileNotFoundError("Diesen Bericht gibt es nicht")
    return candidate
