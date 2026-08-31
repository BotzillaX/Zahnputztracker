"""Watching what is still running (spec 6.6).

Looking at finished operations only ever finds what came to an end. The
case that matters is the one that never ends, so a small loop checks the
open operations against their two thresholds several times a minute.

Soft threshold: the state is captured while the operation still hangs,
and the cycle is marked for keeping. The run carries on. This capture is
the more useful one, because by the hard limit the page has often
replaced the cause with its own error message.

Hard threshold: a second capture into the same incident folder, the
image sequence and the recordings beside it, a notification, and the
recovery.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..registry import store as registry_store
from ..storage import config as config_store
from . import incidents, notify, recovery, spans, stats

INTERVAL_S = 1.0
_task: Optional[asyncio.Task] = None
_working: set = set()


def running() -> bool:
    return _task is not None and not _task.done()


def start() -> None:
    global _task
    if not running():
        _task = asyncio.create_task(_loop())
        bus.publish("watchdog_started")


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
            await asyncio.sleep(INTERVAL_S)
            await inspect()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - the watchdog outlives its own faults
            bus.publish("watchdog_note", reason=f"{type(error).__name__}: {error}")


async def inspect(settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """One pass over the open operations. Returns what it acted on."""
    data = settings or config_store.load()
    acted: List[Dict[str, Any]] = []
    for item in spans.open_spans():
        if item.id in _working or item.instance is None:
            continue
        elapsed = item.elapsed_ms
        limit_ms = spans.hard_limit(item.name, data) * 1000.0
        soft_ms = stats.soft_threshold(item.name, item.scope)

        if not item.hard_hit and elapsed >= limit_ms:
            _working.add(item.id)
            asyncio.create_task(_hard(item, data, elapsed, limit_ms))
            acted.append({"span": item.id, "name": item.name, "stage": "hart"})
        elif not item.soft_hit and soft_ms > 0 and elapsed >= soft_ms:
            _working.add(item.id)
            asyncio.create_task(_soft(item, elapsed, soft_ms))
            acted.append({"span": item.id, "name": item.name, "stage": "weich"})
    return acted


def _context(item: Any, elapsed: float, **more: Any) -> Dict[str, Any]:
    base = stats.reference(item.name, item.scope)
    return {
        "span": item.name,
        "span_id": item.id,
        "elapsed_ms": round(elapsed, 1),
        "median_ms": base["median_ms"],
        "n": base["n"],
        **more,
    }


async def _soft(item: Any, elapsed: float, threshold: float) -> None:
    """Hold the state while the operation is still hanging (6.4)."""
    try:
        document = registry_store.load(item.scope)
        incident = await incidents.capture(
            item.instance,
            document,
            f"{item.name.replace('.', '_')}_langsam",
            f"Über der weichen Schwelle: {round(elapsed / 1000, 1)} s",
            key=str(item.attrs.get("key", "")),
            stage=incidents.SOFT,
            context=_context(item, elapsed, threshold_ms=round(threshold, 1)),
        )
        spans.note_slow(item, threshold, incident)
    except Exception as error:  # noqa: BLE001
        bus.publish("watchdog_note", reason=f"weiche Schwelle: {error}")
    finally:
        _working.discard(item.id)


async def _hard(item: Any, settings: Dict[str, Any], elapsed: float, limit_ms: float) -> None:
    """Blocked: full incident, notification, recovery (6.6 and 6.7)."""
    try:
        document = registry_store.load(item.scope)
        history = int(settings.get("trace_history") or 20)
        context = _context(item, elapsed, limit_s=round(limit_ms / 1000, 1))
        incident = item.incident
        if incident:
            await incidents.add_stage(
                incident, item.instance, document, incidents.HARD,
                reason=f"Hartes Zeitlimit überschritten: {round(elapsed / 1000, 1)} s",
                context=context,
            )
        else:
            incident = await incidents.capture(
                item.instance,
                document,
                f"{item.name.replace('.', '_')}_blockiert",
                f"Hartes Zeitlimit überschritten: {round(elapsed / 1000, 1)} s",
                key=str(item.attrs.get("key", "")),
                stage=incidents.HARD,
                context=context,
            )
        spans.note_blocked(item, incident)
        if incident:
            incidents.attach_material(incident, item.scope, span_name=item.name, history=history)
        notify.notify(
            notify.BLOCKED,
            f"{item.name} läuft seit {round(elapsed / 1000, 1)} s und ist über dem Zeitlimit.",
            scope=item.scope,
            span=item.name,
            incident=incident,
        )
        await recovery.recover(
            item.instance,
            f"{item.name} blockiert",
            key=str(item.attrs.get("key", "")),
        )
    except Exception as error:  # noqa: BLE001
        bus.publish("watchdog_note", reason=f"harte Schwelle: {error}")
    finally:
        _working.discard(item.id)
