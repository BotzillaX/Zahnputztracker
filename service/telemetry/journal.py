"""Append-only event log (spec 6.2).

One line of JSON per record, one file per day. Every line stands on its
own, so a crash in the middle of a write costs at most that one line and
never the file. Writing never raises: a log that cannot be written must
not stop the run it is describing.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ..api.events import bus
from ..storage import paths

DAY = "%Y-%m-%d"
_DAY_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# What may be mirrored from the event bus into the log. Everything else
# is live information for the user interface and not worth a file.
MIRRORED = (
    "degraded",
    "ambiguous",
    "duplicate_resolved",
    "unknown_state",
    "engine_stopped",
    "incident_stored",
    "notification",
    "dispatch_started",
    "item_finished",
    "flow_failed",
    "recovery_stage",
    "recovery_failed",
)

_failed_once = False


def directory() -> Path:
    return paths.roaming_dir() / "logs"


def today() -> str:
    return datetime.now(timezone.utc).strftime(DAY)


def file_for(day: str = "") -> Path:
    return directory() / f"{day or today()}.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write(event: str, **fields: Any) -> Dict[str, Any]:
    """Append one record. Returns it, whether or not the file took it."""
    global _failed_once
    record: Dict[str, Any] = {"ts": _now(), "ev": event, **fields}
    try:
        target = file_for()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        _failed_once = False
    except (OSError, TypeError, ValueError) as error:
        if not _failed_once:
            # Reported once, not on every line: a full disk would
            # otherwise drown the event stream in its own complaint.
            _failed_once = True
            bus.publish("journal_failed", reason=str(error))
    return record


def _mirror(event: Dict[str, Any]) -> None:
    if event.get("kind") in MIRRORED:
        payload = {key: value for key, value in event.items() if key not in ("kind", "ts", "seq")}
        write(str(event["kind"]), **payload)


def attach() -> None:
    """Mirror the interesting bus events into the log."""
    bus.add_sink(_mirror)


def days() -> List[str]:
    """Known log days, newest first."""
    folder = directory()
    if not folder.is_dir():
        return []
    names = [item.stem for item in folder.glob("*.jsonl") if _DAY_NAME.match(item.stem)]
    return sorted(names, reverse=True)


def read(day: str = "", events: Optional[tuple] = None, limit: int = 5000) -> List[Dict[str, Any]]:
    """Records of one day, oldest first. Broken lines are skipped."""
    target = file_for(day)
    if not target.is_file():
        return []
    out: List[Dict[str, Any]] = []
    try:
        with target.open("r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if events and record.get("ev") not in events:
                    continue
                out.append(record)
    except OSError:
        return out
    return out[-limit:]


def tail(count: int = 100, events: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """The most recent records across the last two days, newest first."""
    collected: List[Dict[str, Any]] = []
    for day in days()[:2]:
        collected = read(day, events=events) + collected
        if len(collected) >= count:
            break
    return list(reversed(collected))[:count]


def prune(keep_days: int) -> List[str]:
    """Delete logs older than the retention (spec 6.10)."""
    if keep_days <= 0:
        return []
    edge = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime(DAY)
    removed: List[str] = []
    for day in days():
        if day >= edge:
            continue
        try:
            file_for(day).unlink()
            removed.append(day)
        except OSError:
            pass
    return removed


def size_bytes() -> int:
    folder = directory()
    if not folder.is_dir():
        return 0
    return sum(item.stat().st_size for item in folder.glob("*.jsonl") if item.is_file())


def entries(days_back: int = 1) -> Iterator[Dict[str, Any]]:
    for day in days()[:max(1, days_back)]:
        yield from read(day)
