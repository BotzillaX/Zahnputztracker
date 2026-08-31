"""Keeping the disk usage bounded (spec 6.10).

The rule that outranks every other one here: the application must never
stop because a disk is full. So this module deletes rather than
complains, oldest first, and it never lets a failure of its own reach
the caller.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..storage import config as config_store
from ..storage import paths
from . import incidents, journal, stats, tracing

INTERVAL_S = 1800.0
MB = 1024 * 1024

_task: Optional[asyncio.Task] = None


def running() -> bool:
    return _task is not None and not _task.done()


def start() -> None:
    global _task
    if not running():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


async def _loop() -> None:
    while True:
        try:
            sweep()
            await asyncio.sleep(INTERVAL_S)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            bus.publish("storage_note", reason=f"{type(error).__name__}: {error}")
            await asyncio.sleep(INTERVAL_S)


def _database_bytes() -> int:
    target = paths.roaming_dir() / "data.sqlite"
    try:
        return target.stat().st_size if target.is_file() else 0
    except OSError:
        return 0


def _atlas_bytes() -> int:
    folder = paths.roaming_dir() / "atlas"
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


def usage() -> Dict[str, Any]:
    """What lies where, in bytes, plus the cap it is measured against."""
    settings = config_store.load()
    cap = int(settings.get("storage_cap_mb") or 500) * MB
    recordings = incidents.size_bytes() + tracing.size_bytes()
    return {
        "cap_bytes": cap,
        "cap_mb": int(settings.get("storage_cap_mb") or 500),
        "recordings_bytes": recordings,
        "incidents_bytes": incidents.size_bytes(),
        "traces_bytes": tracing.size_bytes(),
        "log_bytes": journal.size_bytes(),
        "stats_bytes": stats.size_bytes(),
        "database_bytes": _database_bytes(),
        "views_bytes": _atlas_bytes(),
        "over_cap": recordings > cap,
        "share": round(recordings / cap, 3) if cap else 0.0,
    }


def _cycle_files() -> List[Path]:
    folder = tracing.root() / "zyklen"
    if not folder.is_dir():
        return []
    return sorted(folder.rglob("*.zip"))


def sweep(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Retention first, then the hard cap. Returns what was removed."""
    data = settings or config_store.load()
    removed_logs: List[str] = []
    removed_incidents: List[str] = []
    removed_traces: List[str] = []

    try:
        removed_logs = journal.prune(int(data.get("retention_days_log") or 30))
    except Exception:  # noqa: BLE001
        pass
    try:
        for name in incidents.older_than(int(data.get("retention_days_incident") or 7)):
            incidents.forget(name)
            removed_incidents.append(name)
    except Exception:  # noqa: BLE001
        pass

    cap = int(data.get("storage_cap_mb") or 500) * MB
    try:
        # Oldest recordings go first, and the incidents before the plain
        # cycle recordings: a saved incident is worth more than a cycle
        # nobody asked about.
        remaining = incidents.names(oldest_first=True)
        while incidents.size_bytes() + tracing.size_bytes() > cap and remaining:
            name = remaining.pop(0)
            incidents.forget(name)
            removed_incidents.append(name)
        files = _cycle_files()
        while incidents.size_bytes() + tracing.size_bytes() > cap and files:
            item = files.pop(0)
            try:
                item.unlink()
                removed_traces.append(item.name)
            except OSError:
                break
    except Exception:  # noqa: BLE001
        pass

    report = {
        "logs": removed_logs,
        "incidents": removed_incidents,
        "traces": removed_traces,
        "usage": usage(),
    }
    if removed_logs or removed_incidents or removed_traces:
        bus.publish(
            "storage_swept",
            logs=len(removed_logs),
            incidents=len(removed_incidents),
            traces=len(removed_traces),
        )
    return report
