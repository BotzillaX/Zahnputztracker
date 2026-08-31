"""Runtime reference values per operation (spec 6.5).

Median and median absolute deviation over a sliding window, because a
single outlier must not poison the reference for hours. Kept apart per
browser instance and per hour of the day, with the overall value of the
instance as the fallback while an hour has too few measurements
(decision 14).

The first measurement of an operation is dropped: the first run of
anything includes a cold start and is not representative.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..storage import paths

MAX_SAMPLES = 200
MIN_SAMPLES = 8
# Robust distance from the median, measured in scaled deviations.
ELEVATED_AT = 3.5
CRITICAL_AT = 6.0
# A short operation deviates in percent very easily. Below this margin a
# deviation is not worth a word.
MIN_MARGIN_MS = 250.0
FLUSH_AFTER_S = 10.0

NORMAL = "normal"
ELEVATED = "erhoeht"
CRITICAL = "kritisch"
UNKNOWN = "sammelt"
LEVEL_LABELS = {
    NORMAL: "normal",
    ELEVATED: "erhöht",
    CRITICAL: "kritisch",
    UNKNOWN: "noch keine Referenz",
}

_state: Optional[Dict[str, Any]] = None
_dirty = False
_last_write = 0.0


def file() -> Path:
    return paths.roaming_dir() / "stats" / "laufzeiten.json"


def _empty() -> Dict[str, Any]:
    return {"version": 1, "buckets": {}, "seen": []}


def _load() -> Dict[str, Any]:
    global _state
    if _state is not None:
        return _state
    target = file()
    data = _empty()
    if target.is_file():
        try:
            stored = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(stored, dict) and isinstance(stored.get("buckets"), dict):
                data = {
                    "version": 1,
                    "buckets": {
                        str(key): [float(x) for x in value][-MAX_SAMPLES:]
                        for key, value in stored["buckets"].items()
                        if isinstance(value, list)
                    },
                    "seen": [str(x) for x in stored.get("seen") or []],
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            data = _empty()
    _state = data
    return _state


def flush(force: bool = False) -> None:
    """Write the reference values so a restart keeps them (6.5)."""
    global _dirty, _last_write
    if _state is None or (not _dirty and not force):
        return
    if not force and time.monotonic() - _last_write < FLUSH_AFTER_S:
        return
    target = file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(_state, stream, ensure_ascii=False)
        os.replace(temporary, target)
        _dirty = False
        _last_write = time.monotonic()
    except OSError:
        # Losing reference values costs accuracy, never the run.
        pass


def _hour(at: Optional[datetime] = None) -> int:
    return (at or datetime.now()).hour


def _keys(name: str, scope: str, at: Optional[datetime] = None) -> Tuple[str, str]:
    scope = scope or "-"
    return f"{name}|{scope}|{_hour(at):02d}", f"{name}|{scope}|*"


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _spread(values: List[float], median: float) -> float:
    """Scaled median absolute deviation, with a floor.

    Without the floor a perfectly steady operation would call every
    millisecond of variation critical.
    """
    mad = _median([abs(value - median) for value in values])
    return max(1.4826 * mad, median * 0.15, MIN_MARGIN_MS / 2)


def reference(name: str, scope: str, at: Optional[datetime] = None) -> Dict[str, Any]:
    """The reference of this operation, hour first, instance as fallback."""
    data = _load()
    hourly, overall = _keys(name, scope, at)
    for key, basis in ((hourly, "stunde"), (overall, "gesamt")):
        values = data["buckets"].get(key) or []
        if len(values) >= MIN_SAMPLES:
            median = _median(values)
            spread = _spread(values, median)
            return {
                "known": True,
                "basis": basis,
                "n": len(values),
                "median_ms": round(median, 1),
                "spread_ms": round(spread, 1),
                "elevated_ms": round(median + ELEVATED_AT * spread + MIN_MARGIN_MS, 1),
                "critical_ms": round(median + CRITICAL_AT * spread + MIN_MARGIN_MS, 1),
            }
    values = data["buckets"].get(overall) or []
    return {
        "known": False,
        "basis": "gesamt",
        "n": len(values),
        "median_ms": 0.0,
        "spread_ms": 0.0,
        "elevated_ms": 0.0,
        "critical_ms": 0.0,
    }


def rate(name: str, scope: str, ms: float, at: Optional[datetime] = None) -> Dict[str, Any]:
    """Judge a runtime without recording it."""
    base = reference(name, scope, at)
    if not base["known"]:
        return {**base, "level": UNKNOWN, "dur_ms": round(ms, 1)}
    level = NORMAL
    if ms >= base["critical_ms"]:
        level = CRITICAL
    elif ms >= base["elevated_ms"]:
        level = ELEVATED
    return {**base, "level": level, "dur_ms": round(ms, 1)}


def soft_threshold(name: str, scope: str, at: Optional[datetime] = None) -> float:
    """Milliseconds after which a running operation counts as noticeable."""
    base = reference(name, scope, at)
    return float(base["elevated_ms"]) if base["known"] else 0.0


def record(name: str, scope: str, ms: float, at: Optional[datetime] = None) -> Dict[str, Any]:
    """Judge a runtime against the current reference, then add it.

    Noticeable values are added as well (6.5): the reference has to
    follow conditions that stay changed, otherwise the day after a
    slower release of the page would be one long alarm.
    """
    global _dirty
    verdict = rate(name, scope, ms, at)
    data = _load()
    marker = f"{name}|{scope or '-'}"
    if marker not in data["seen"]:
        # Cold start: remembered, not counted.
        data["seen"].append(marker)
        _dirty = True
        flush()
        return {**verdict, "recorded": False, "cold": True}
    hourly, overall = _keys(name, scope, at)
    for key in (hourly, overall):
        values = data["buckets"].setdefault(key, [])
        values.append(round(float(ms), 1))
        del values[:-MAX_SAMPLES]
    _dirty = True
    flush()
    return {**verdict, "recorded": True, "cold": False}


def summary() -> List[Dict[str, Any]]:
    """One line per operation and instance, for the diagnosis view."""
    data = _load()
    out: List[Dict[str, Any]] = []
    for key, values in sorted(data["buckets"].items()):
        name, _, rest = key.partition("|")
        scope, _, hour = rest.partition("|")
        if hour != "*" or not values:
            continue
        median = _median(values)
        spread = _spread(values, median)
        out.append(
            {
                "name": name,
                "scope": scope,
                "n": len(values),
                "median_ms": round(median, 1),
                "spread_ms": round(spread, 1),
                "elevated_ms": round(median + ELEVATED_AT * spread + MIN_MARGIN_MS, 1),
                "critical_ms": round(median + CRITICAL_AT * spread + MIN_MARGIN_MS, 1),
                "ready": len(values) >= MIN_SAMPLES,
            }
        )
    return out


def size_bytes() -> int:
    target = file()
    return target.stat().st_size if target.is_file() else 0


def reset() -> None:
    global _state, _dirty
    _state = _empty()
    _dirty = True
    flush(force=True)
