"""Notifications (spec 12.5).

One function for the whole application. Where a notification ends up is
decided by the channels registered here, so a second channel can be added
later without touching a single caller. Today there is exactly one: the
event stream, which the host process turns into a tray message.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

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


def add_channel(channel: Callable[[Dict[str, Any]], None]) -> None:
    if channel not in _channels:
        _channels.append(channel)


def remove_channel(channel: Callable[[Dict[str, Any]], None]) -> None:
    if channel in _channels:
        _channels.remove(channel)


def notify(kind: str, text: str = "", **details: Any) -> Dict[str, Any]:
    """Announce something the user should look at."""
    settings = config_store.load()
    # Deliberately "topic" and not "kind": the bus already carries the
    # event kind, and a second key of that name would collide with it.
    message: Dict[str, Any] = {
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
    for channel in list(_channels):
        try:
            channel(message)
        except Exception:  # noqa: BLE001 - a channel never breaks the caller
            pass
    return message
