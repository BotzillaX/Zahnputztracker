"""Every operation is a span (spec 6.2).

Start, end, status, context, and the operation it belongs to. The names
are a fixed list and are never assembled at runtime, so a statistic per
name stays comparable over months.

A span does two things beyond writing a line: it lets the watchdog see
that something is still running (6.6), and it hands its runtime to the
statistics, which decide whether that runtime was ordinary (6.5).
"""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from ..api.events import bus
from ..storage import config as config_store
from . import journal, notify, stats, tracing

# The fixed catalogue. The absolute limits per name live in the
# configuration, which is where the user can change them.
NAMES = (
    "search.reload",
    "search.parse_results",
    "search.new_item_found",
    "search.idle_behavior",
    "item.open",
    "auth.check",
    "auth.login",
    "form.open",
    "form.fill",
    "compose.generate",
    "submit.send",
    "submit.confirm",
    "state.detect",
)

OK = "ok"
ERROR = "fehler"
BLOCKED = "blockiert"

MAX_RECENT = 200
# How many of the last operations are looked at for the three-step
# status display (12.2).
WINDOW = 20
CROWDED = 3

_open: Dict[str, "Span"] = {}
_recent: Deque[Dict[str, Any]] = deque(maxlen=MAX_RECENT)
_parent: contextvars.ContextVar[str] = contextvars.ContextVar("zt_span_parent", default="")
_blocked_at: float = 0.0
_paused_at: float = 0.0


def paused() -> bool:
    return _paused_at > 0.0


def pause() -> None:
    """Stop the clock of every running operation.

    Everything waits while an approval is open (decision 9). Counting
    that wait against a time limit would mean the watchdog declares a
    run blocked because the user was making tea.
    """
    global _paused_at
    if _paused_at == 0.0:
        _paused_at = time.monotonic()


def resume() -> None:
    """Hand back the waited time to the operations that were running."""
    global _paused_at
    if _paused_at == 0.0:
        return
    now = time.monotonic()
    for item in _open.values():
        item.started += now - max(item.started, _paused_at)
    _paused_at = 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hard_limit(name: str, settings: Optional[Dict[str, Any]] = None) -> float:
    """The absolute limit of this operation, in seconds."""
    data = settings or config_store.load()
    limits = data.get("limits") or {}
    try:
        return float(limits.get(name, config_store.DEFAULT_LIMITS.get(name, 60)))
    except (TypeError, ValueError):
        return 60.0


class Span:
    def __init__(self, name: str, scope: str, parent: str, instance: Any,
                 attrs: Dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.name = name
        self.scope = scope
        self.parent = parent
        self.instance = instance
        self.attrs = attrs
        self.started_at = _now()
        self.started = time.monotonic()
        self.soft_hit = False
        self.hard_hit = False
        self.incident = ""
        self.status = ""

    @property
    def elapsed_ms(self) -> float:
        now = time.monotonic()
        # A pause that is still going on is subtracted right away, not
        # only when it ends: the watchdog looks at this value every
        # second and must not see a waiting user as a blockade.
        waiting = (now - max(self.started, _paused_at)) if _paused_at else 0.0
        return (now - self.started - waiting) * 1000.0

    def report(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "scope": self.scope,
            "parent": self.parent,
            "started_at": self.started_at,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "limit_s": hard_limit(self.name),
            "soft": self.soft_hit,
            "hard": self.hard_hit,
            "incident": self.incident,
            "attrs": self.attrs,
        }


def open_spans() -> List[Span]:
    return list(_open.values())


def find(span_id: str) -> Optional[Span]:
    return _open.get(span_id)


def busy(scope: str) -> bool:
    """Is an operation working on this browser right now?"""
    return any(item.scope == scope for item in _open.values())


def recent(limit: int = 50) -> List[Dict[str, Any]]:
    """Finished operations, newest first (the live timeline of 12.2)."""
    return list(_recent)[-limit:][::-1]


def note_blocked(span: Span, incident: str = "") -> None:
    """Called by the watchdog when an operation passed its hard limit."""
    global _blocked_at
    span.hard_hit = True
    span.incident = incident or span.incident
    _blocked_at = time.monotonic()
    journal.write("span_blocked", id=span.id, name=span.name, scope=span.scope,
                  elapsed_ms=round(span.elapsed_ms, 1), limit_s=hard_limit(span.name),
                  incident=span.incident)
    bus.publish("span_blocked", span=span.id, name=span.name, scope=span.scope,
                elapsed_ms=round(span.elapsed_ms, 1), incident=span.incident)


def note_slow(span: Span, threshold_ms: float, incident: str = "") -> None:
    """Called by the watchdog at the soft threshold."""
    span.soft_hit = True
    span.incident = incident or span.incident
    tracing.mark(span.scope, f"{span.name} über der weichen Schwelle")
    journal.write("span_slow", id=span.id, name=span.name, scope=span.scope,
                  elapsed_ms=round(span.elapsed_ms, 1), threshold_ms=round(threshold_ms, 1),
                  incident=span.incident)
    bus.publish("span_slow", span=span.id, name=span.name, scope=span.scope,
                elapsed_ms=round(span.elapsed_ms, 1), incident=span.incident)


def level() -> Dict[str, Any]:
    """The three steps of the status display (12.2)."""
    now = time.monotonic()
    blocked = any(item.hard_hit for item in _open.values()) or (
        _blocked_at > 0 and now - _blocked_at < 600
    )
    window = list(_recent)[-WINDOW:]
    noticeable = [item for item in window if item.get("level") in (stats.ELEVATED, stats.CRITICAL)]
    if blocked:
        step, label = "blockiert", "blockiert"
    elif len(noticeable) >= CROWDED:
        step, label = "auffaellig", "gehäufte Auffälligkeiten"
    else:
        step, label = "normal", "normal"
    return {
        "level": step,
        "label": label,
        "noticeable": len(noticeable),
        "window": len(window),
        "open": len(_open),
    }


@asynccontextmanager
async def span(name: str, scope: str = "", instance: Any = None, **attrs: Any):
    """Measure one operation.

    ``instance`` is what the watchdog needs to photograph the browser at
    the moment an operation hangs, instead of afterwards.
    """
    if instance is not None and not scope:
        scope = getattr(instance, "role", "")
    parent = _parent.get()
    item = Span(name, scope, parent, instance, dict(attrs))
    _open[item.id] = item
    token = _parent.set(item.id)
    journal.write("span_start", id=item.id, parent=parent, name=name,
                  attrs={"scope": scope, **attrs})
    bus.publish("span_start", span=item.id, name=name, scope=scope, parent=parent)
    status = OK
    error_text = ""
    try:
        yield item
    except BaseException as error:
        status = ERROR
        error_text = f"{type(error).__name__}: {error}"
        raise
    finally:
        _parent.reset(token)
        _open.pop(item.id, None)
        _finish(item, status, error_text)


def _finish(item: Span, status: str, error_text: str) -> None:
    duration = item.elapsed_ms
    if item.hard_hit:
        status = BLOCKED if status != ERROR else status
    verdict = stats.record(item.name, item.scope, duration)
    anomaly = None if verdict["level"] in (stats.NORMAL, stats.UNKNOWN) else verdict["level"]
    record = {
        "id": item.id,
        "name": item.name,
        "scope": item.scope,
        "parent": item.parent,
        "at": item.started_at,
        "dur_ms": round(duration, 1),
        "status": status,
        "level": verdict["level"],
        "median_ms": verdict["median_ms"],
        "n": verdict["n"],
        "soft": item.soft_hit,
        "hard": item.hard_hit,
        "incident": item.incident,
        "reason": error_text,
    }
    _recent.append(record)
    journal.write(
        "span_end",
        id=item.id,
        name=item.name,
        scope=item.scope,
        dur_ms=round(duration, 1),
        status=status,
        baseline={"p50": verdict["median_ms"], "n": verdict["n"], "basis": verdict["basis"]},
        anomaly=anomaly,
        incident=item.incident,
        reason=error_text,
    )
    bus.publish("span_end", span=item.id, name=item.name, scope=item.scope,
                dur_ms=round(duration, 1), status=status, level=verdict["level"],
                median_ms=verdict["median_ms"], incident=item.incident)

    if status == OK and verdict["level"] in (stats.NORMAL, stats.UNKNOWN):
        # A clean run is what a later comparison is measured against.
        tracing.note_success(item.scope, item.name)
    if verdict["level"] == stats.CRITICAL:
        tracing.mark(item.scope, f"{item.name} kritisch langsam")
        notify.notify(
            notify.RUNTIME,
            f"{item.name} brauchte {round(duration / 1000, 1)} s "
            f"(üblich {round(verdict['median_ms'] / 1000, 1)} s).",
            name=item.name,
            scope=item.scope,
        )
    elif verdict["level"] == stats.ELEVATED:
        tracing.mark(item.scope, f"{item.name} auffällig langsam")
    if status == ERROR:
        tracing.mark(item.scope, f"{item.name} endete mit einem Fehler")


def forget() -> None:
    """Only used by the tests."""
    _open.clear()
    _recent.clear()
