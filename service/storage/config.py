"""User configuration.

One JSON document in %APPDATA%. Written atomically, validated on read,
and never holding a secret: passwords and keys live in the Windows
credential store (see secrets.py).

Every knob the user interface offers is declared here with its default.
Unknown keys coming from an older or newer file are kept untouched so a
downgrade does not silently discard settings.
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from typing import Any, Dict, List, Tuple

from . import paths

CONFIG_VERSION = 1

# Time limits are kept per operation name, not globally: normal runtimes
# differ by more than an order of magnitude.
DEFAULT_LIMITS: Dict[str, int] = {
    "search.reload": 60,
    "search.parse_results": 30,
    "search.new_item_found": 30,
    "search.idle_behavior": 60,
    "item.open": 60,
    "auth.check": 30,
    "auth.login": 120,
    "form.open": 45,
    "form.fill": 60,
    "compose.generate": 120,
    "submit.send": 60,
    "submit.confirm": 45,
    "state.detect": 30,
}

DEFAULTS: Dict[str, Any] = {
    "version": CONFIG_VERSION,
    "account": {
        "email": "",
    },
    "source": {
        "url": "",
        "item_url_template": "",
        "reload_min_s": 10,
        "reload_max_s": 15,
        "idle_behavior": False,
    },
    "browsers": {
        "search": {"width": 1280, "height": 720},
        "session": {"width": 1280, "height": 720},
    },
    "composer": {
        "provider": "anthropic",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "model": "claude-sonnet-4-5",
        "prompt": "",
        "timeout_s": 120,
    },
    # Free list of label/value pairs the user maintains, used in the prompt
    # and in form fields.
    "profile_values": [],
    # Answer pairs for form fields: the target page uses an internal value
    # and a display text in parallel, so both are stored.
    "answers": [],
    "review_mode": True,
    "limits": deepcopy(DEFAULT_LIMITS),
    "confirm_wait_s": 3.0,
    "storage_cap_mb": 500,
    "trace_history": 20,
    "record_frames": True,
    "retention_days_log": 30,
    "retention_days_incident": 7,
    "sound_on_new": True,
    "notify": True,
}

# (path, kind, minimum, maximum)
_NUMERIC_RULES: List[Tuple[Tuple[str, ...], type, float, float]] = [
    (("source", "reload_min_s"), int, 1, 3600),
    (("source", "reload_max_s"), int, 1, 3600),
    (("browsers", "search", "width"), int, 480, 3840),
    (("browsers", "search", "height"), int, 360, 2160),
    (("browsers", "session", "width"), int, 480, 3840),
    (("browsers", "session", "height"), int, 360, 2160),
    (("composer", "timeout_s"), int, 5, 600),
    (("confirm_wait_s",), float, 0.5, 60),
    (("storage_cap_mb",), int, 50, 100_000),
    (("trace_history",), int, 0, 200),
    (("retention_days_log",), int, 1, 365),
    (("retention_days_incident",), int, 1, 365),
]


class ConfigError(ValueError):
    """Raised when a submitted configuration cannot be accepted."""


def _merge(base: Any, incoming: Any) -> Any:
    """Deep merge, with incoming values winning over defaults."""
    if isinstance(base, dict) and isinstance(incoming, dict):
        merged = dict(base)
        for key, value in incoming.items():
            merged[key] = _merge(base.get(key), value) if key in base else value
        return merged
    return incoming if incoming is not None else base


def _dig(data: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    node: Any = data
    for step in path:
        if not isinstance(node, dict) or step not in node:
            return None
        node = node[step]
    return node


def _put(data: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    node = data
    for step in path[:-1]:
        node = node.setdefault(step, {})
    node[path[-1]] = value


def _pairs(raw: Any, fields: Tuple[str, ...], label: str) -> List[Dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConfigError(f"{label} muss eine Liste sein")
    cleaned: List[Dict[str, str]] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{label}: Eintrag {index} ist kein Objekt")
        item = {field: str(entry.get(field, "") or "") for field in fields}
        if not item[fields[0]].strip():
            raise ConfigError(f"{label}: Eintrag {index} hat keine Bezeichnung")
        cleaned.append(item)
    return cleaned


def validate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalised copy or raise ConfigError."""
    data = _merge(deepcopy(DEFAULTS), candidate)
    data["version"] = CONFIG_VERSION

    for path, kind, low, high in _NUMERIC_RULES:
        path = path if isinstance(path, tuple) else (path,)
        value = _dig(data, path)
        try:
            value = kind(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{'.'.join(path)} ist keine Zahl") from None
        if not low <= value <= high:
            raise ConfigError(f"{'.'.join(path)} muss zwischen {low} und {high} liegen")
        _put(data, path, value)

    if data["source"]["reload_min_s"] > data["source"]["reload_max_s"]:
        raise ConfigError("Das Minimum der Wartezeit darf nicht über dem Maximum liegen")

    limits: Dict[str, int] = {}
    for name, value in (data.get("limits") or {}).items():
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"Zeitlimit für {name} ist keine Zahl") from None
        if not 5 <= seconds <= 1800:
            raise ConfigError(f"Zeitlimit für {name} muss zwischen 5 und 1800 Sekunden liegen")
        limits[str(name)] = seconds
    data["limits"] = {**DEFAULT_LIMITS, **limits}

    data["profile_values"] = _pairs(data.get("profile_values"), ("label", "value"), "Persönliche Werte")
    data["answers"] = _pairs(data.get("answers"), ("label", "value", "display"), "Antwort-Paare")

    for flag in ("review_mode", "sound_on_new", "notify", "record_frames"):
        data[flag] = bool(data.get(flag))
    data["source"]["idle_behavior"] = bool(data["source"].get("idle_behavior"))

    for key in ("url", "item_url_template"):
        data["source"][key] = str(data["source"].get(key) or "").strip()
    data["account"]["email"] = str(data["account"].get("email") or "").strip()
    for key in ("provider", "endpoint", "model", "prompt"):
        data["composer"][key] = str(data["composer"].get(key) or "")

    return data


def path() -> "paths.Path":
    return paths.roaming_dir() / "config.json"


def load() -> Dict[str, Any]:
    """Read the stored configuration, falling back to defaults."""
    target = path()
    if not target.exists():
        return deepcopy(DEFAULTS)
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A damaged file must not stop the application from starting.
        return deepcopy(DEFAULTS)
    if not isinstance(stored, dict):
        return deepcopy(DEFAULTS)
    try:
        return validate(stored)
    except ConfigError:
        return _merge(deepcopy(DEFAULTS), stored)


def save(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and write atomically. Returns the stored document."""
    data = validate(candidate)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return data
