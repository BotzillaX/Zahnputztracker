"""Filesystem locations used by the service.

Nothing is ever written next to the executable (spec section 4):
roaming data lives in %APPDATA%, bulky local data in %LOCALAPPDATA%.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "Zahnputztracker"


def _base(env_var: str, fallback: str) -> Path:
    root = os.environ.get(env_var)
    if not root:
        root = str(Path.home() / fallback)
    return Path(root) / APP_DIR_NAME


def roaming_dir() -> Path:
    """Configuration, registry, database, logs, incidents."""
    return _base("APPDATA", "AppData/Roaming")


def local_dir() -> Path:
    """Browser binary, profiles, temporary traces."""
    return _base("LOCALAPPDATA", "AppData/Local")


def ensure_layout() -> None:
    """Create every directory the application expects to exist."""
    for path in (
        roaming_dir(),
        roaming_dir() / "registry",
        roaming_dir() / "logs",
        roaming_dir() / "stats",
        roaming_dir() / "atlas",
        roaming_dir() / "incidents",
        local_dir(),
        local_dir() / "browser",
        local_dir() / "profiles",
        local_dir() / "traces",
    ):
        path.mkdir(parents=True, exist_ok=True)


def runtime_file() -> Path:
    """Where the running service publishes its port and process id.

    The authentication token is deliberately NOT part of this file
    (spec section 4: the token is never stored in a file).
    """
    return roaming_dir() / "runtime.json"
