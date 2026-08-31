"""Cycle recordings (spec 6.3).

Not a continuous video: that is bound to the lifetime of a browser
context which is never closed, cannot be rotated, and costs gigabytes a
day for nothing. Instead every cycle is recorded on its own and thrown
away again unless it turned out to be worth keeping.

Two reasons make a recording stay:

* the cycle was noticeable or blocked, and then the twenty cycles before
  it are still on disk as well (the cause is rarely in the cycle that
  broke),
* or the cycle holds a successful run of an operation whose reference
  recording has grown old. That is what makes a comparison possible
  while a fault has been going on for hours.

Everything here degrades quietly. A browser that cannot record is worse
to diagnose, but it still works.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..api.events import bus
from ..storage import paths

# A reference older than this is renewed at the next opportunity.
REFERENCE_MAX_AGE_H = 12
DEFAULT_HISTORY = 20

_started: Set[int] = set()
_cycles: Dict[str, "Cycle"] = {}
_counter = 0


def root() -> Path:
    return paths.local_dir() / "traces"


def cycle_dir(scope: str) -> Path:
    return root() / "zyklen" / (scope or "-")


def reference_dir() -> Path:
    return root() / "referenz"


def _index_file() -> Path:
    return reference_dir() / "index.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _now().strftime("%Y%m%dT%H%M%S")


def _read_index() -> Dict[str, Any]:
    target = _index_file()
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_index(data: Dict[str, Any]) -> None:
    try:
        reference_dir().mkdir(parents=True, exist_ok=True)
        _index_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class Cycle:
    """One recorded stretch of work in one browser."""

    def __init__(self, scope: str, label: str) -> None:
        global _counter
        _counter += 1
        self.scope = scope
        self.label = label
        self.number = _counter
        self.started = _now()
        self.keep = False
        self.reason = ""
        self.successful: List[str] = []
        self.recording = False

    def mark(self, reason: str) -> None:
        """Remember this cycle for the disk."""
        if not self.keep:
            self.keep = True
            self.reason = reason


def current(scope: str) -> Optional[Cycle]:
    return _cycles.get(scope)


def mark(scope: str, reason: str) -> None:
    cycle = _cycles.get(scope)
    if cycle is not None:
        cycle.mark(reason)


def note_success(scope: str, name: str) -> None:
    cycle = _cycles.get(scope)
    if cycle is not None and name not in cycle.successful:
        cycle.successful.append(name)


async def begin(instance: Any, label: str) -> Optional[Cycle]:
    """Start recording a cycle in this browser."""
    scope = getattr(instance, "role", "")
    if scope in _cycles:
        await end(instance)
    cycle = Cycle(scope, label)
    _cycles[scope] = cycle
    context = getattr(instance, "context", None)
    if context is None:
        return cycle
    try:
        if id(context) not in _started:
            await context.tracing.start(screenshots=True, snapshots=True, sources=False)
            _started.add(id(context))
        await context.tracing.start_chunk(title=label)
        cycle.recording = True
    except Exception as error:  # noqa: BLE001 - recording is not the job
        bus.publish("trace_unavailable", scope=scope, reason=str(error))
    return cycle


async def end(instance: Any, history: int = DEFAULT_HISTORY) -> Optional[Path]:
    """Close the cycle. Writes it only if there is a reason to."""
    scope = getattr(instance, "role", "")
    cycle = _cycles.pop(scope, None)
    if cycle is None:
        return None
    stale = [name for name in cycle.successful if _needs_reference(name, scope)]
    context = getattr(instance, "context", None)
    if context is None or not cycle.recording:
        return None
    if not cycle.keep and not stale:
        try:
            await context.tracing.stop_chunk()
        except Exception:  # noqa: BLE001
            pass
        return None

    folder = cycle_dir(scope)
    target = folder / f"{cycle.number:06d}-{_stamp()}.zip"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        await context.tracing.stop_chunk(path=str(target))
    except Exception as error:  # noqa: BLE001
        bus.publish("trace_failed", scope=scope, reason=str(error))
        return None

    prune(scope, history)
    for name in stale:
        _store_reference(name, scope, target, cycle)
    if cycle.keep:
        bus.publish("trace_kept", scope=scope, reason=cycle.reason, file=target.name)
    return target


async def abandon(instance: Any) -> None:
    """Drop the open cycle without writing anything."""
    scope = getattr(instance, "role", "")
    cycle = _cycles.pop(scope, None)
    context = getattr(instance, "context", None)
    if cycle is None or context is None or not cycle.recording:
        return
    try:
        await context.tracing.stop_chunk()
    except Exception:  # noqa: BLE001
        pass


def forget_context(context: Any) -> None:
    """A closed browser starts over with tracing next time."""
    _started.discard(id(context))


def _needs_reference(name: str, scope: str) -> bool:
    entry = _read_index().get(f"{name}|{scope}")
    if not entry:
        return True
    target = reference_dir() / str(entry.get("file", ""))
    if not target.is_file():
        return True
    try:
        at = datetime.fromisoformat(str(entry.get("at", "")).replace("Z", "+00:00"))
    except ValueError:
        return True
    return _now() - at > timedelta(hours=REFERENCE_MAX_AGE_H)


def _store_reference(name: str, scope: str, source: Path, cycle: Cycle) -> None:
    """Keep one successful run of this operation for comparison."""
    safe = name.replace(".", "_")
    destination = reference_dir() / f"{safe}-{scope or 'x'}.zip"
    try:
        reference_dir().mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    except OSError:
        return
    index = _read_index()
    index[f"{name}|{scope}"] = {
        "name": name,
        "scope": scope,
        "at": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "file": destination.name,
        "cycle": cycle.label,
    }
    _write_index(index)


def reference_for(name: str, scope: str) -> Optional[Dict[str, Any]]:
    entry = _read_index().get(f"{name}|{scope}")
    if not entry:
        return None
    target = reference_dir() / str(entry.get("file", ""))
    if not target.is_file():
        return None
    return {**entry, "path": str(target)}


def recent(scope: str, count: int) -> List[Path]:
    """The newest recordings of this browser, newest first."""
    folder = cycle_dir(scope)
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.zip"), reverse=True)[:max(0, count)]


def prune(scope: str, history: int) -> List[Path]:
    """Keep only the configured number of cycles."""
    keep = max(0, int(history)) + 1
    files = sorted(cycle_dir(scope).glob("*.zip"), reverse=True) if cycle_dir(scope).is_dir() else []
    removed: List[Path] = []
    for item in files[keep:]:
        try:
            item.unlink()
            removed.append(item)
        except OSError:
            pass
    return removed


def size_bytes() -> int:
    folder = root()
    if not folder.is_dir():
        return 0
    total = 0
    for item in folder.rglob("*.zip"):
        try:
            total += item.stat().st_size
        except OSError:
            pass
    return total


def state() -> Dict[str, Any]:
    return {
        "open": [
            {"scope": scope, "label": cycle.label, "keep": cycle.keep,
             "reason": cycle.reason, "recording": cycle.recording}
            for scope, cycle in sorted(_cycles.items())
        ],
        "references": list(_read_index().values()),
        "size_bytes": size_bytes(),
    }
