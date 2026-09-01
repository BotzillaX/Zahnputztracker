"""Notifications (spec 12.5).

One function for the whole application. Where a notification ends up is
decided by the channels registered here, so a second channel can be added
later without touching a single caller. Today there are two: the event
stream, which the user interface reads, and a short queue the host
process asks for, which turns a message into a system notification.

The queue exists because the host is a separate process that only speaks
HTTP. It keeps the last few messages with a running number, so the host
can ask for everything after the number it saw last and miss nothing.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Deque, Dict, List

from ..api.events import bus
from ..storage import config as config_store

UNKNOWN_STATE = "unbekannter_zustand"
BLOCKED = "blockade"
RUNTIME = "laufzeit"
AUTH = "anmeldung"
CODE = "code"
APPROVAL = "freigabe"
NEW_ITEM = "neuer_eintrag"

TITLES = {
    UNKNOWN_STATE: "Unbekannter Zustand",
    BLOCKED: "Vorgang blockiert",
    RUNTIME: "Auffällige Laufzeit",
    AUTH: "Anmeldeproblem",
    CODE: "Code wird gebraucht",
    APPROVAL: "Freigabe wartet",
    NEW_ITEM: "Neuer Eintrag",
}

_channels: List[Callable[[Dict[str, Any]], None]] = []

# How many messages the host may fall behind before the oldest is lost.
# It asks every couple of seconds, so this is generous.
MAX_QUEUE = 50

_queue: Deque[Dict[str, Any]] = deque(maxlen=MAX_QUEUE)
_number = 0


def pending(after: int = 0) -> Dict[str, Any]:
    """Everything the host has not seen yet, oldest first."""
    return {
        "number": _number,
        "messages": [item for item in _queue if int(item.get("number") or 0) > after],
    }


def add_channel(channel: Callable[[Dict[str, Any]], None]) -> None:
    if channel not in _channels:
        _channels.append(channel)


def remove_channel(channel: Callable[[Dict[str, Any]], None]) -> None:
    if channel in _channels:
        _channels.remove(channel)


def notify(kind: str, text: str = "", **details: Any) -> Dict[str, Any]:
    """Announce something the user should look at."""
    global _number
    settings = config_store.load()
    _number += 1
    # Deliberately "topic" and not "kind": the bus already carries the
    # event kind, and a second key of that name would collide with it.
    message: Dict[str, Any] = {
        "number": _number,
        "topic": kind,
        "title": TITLES.get(kind, kind),
        "text": text,
        "sound": bool(settings.get("sound_on_new")) and kind == NEW_ITEM,
        "wanted": bool(settings.get("notify")),
        **details,
    }
    # The event always goes out, even with notifications switched off:
    # the user interface shows it either way. Only the system message is
    # governed by the setting, and that decision belongs to the host.
    bus.publish("notification", **message)
    _queue.append(message)
    for channel in list(_channels):
        try:
            channel(message)
        except Exception:  # noqa: BLE001 - a channel never breaks the caller
            pass
    return message
