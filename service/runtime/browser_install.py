"""Downloading and locating the browser binary.

The binary is not shipped with the application (spec section 4). It is
fetched on first use into %LOCALAPPDATA%\\Zahnputztracker\\browser.

The upstream package installs into its own cache directory. We redirect
that to our own folder by rebinding the module level paths. If the
upstream layout ever changes, `_redirect` fails loudly instead of
silently writing somewhere else.
"""

from __future__ import annotations

import contextlib
import io
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..storage import paths

ProgressCallback = Callable[[str, int, int], None]

_lock = threading.Lock()
_redirected: Optional[Path] = None

# Module attributes that must exist before we rebind them.
_PKGMAN_PATHS = ("INSTALL_DIR",)
_VERSION_PATHS = ("INSTALL_DIR", "BROWSERS_DIR", "CONFIG_FILE", "REPO_CACHE_FILE", "COMPAT_FLAG")


class InstallError(RuntimeError):
    """Raised when the browser binary cannot be provided."""


def root_dir() -> Path:
    return paths.local_dir() / "browser"


def _redirect() -> Path:
    """Point the upstream package at our own install directory."""
    global _redirected
    if _redirected is not None:
        return _redirected

    root = root_dir()
    root.mkdir(parents=True, exist_ok=True)

    from camoufox import multiversion, pkgman

    for name in _PKGMAN_PATHS:
        if not hasattr(pkgman, name):
            raise InstallError(f"Unerwarteter Aufbau des Browser-Pakets ({name} fehlt)")
    for name in _VERSION_PATHS:
        if not hasattr(multiversion, name):
            raise InstallError(f"Unerwarteter Aufbau des Browser-Pakets ({name} fehlt)")

    pkgman.INSTALL_DIR = root
    multiversion.INSTALL_DIR = root
    multiversion.BROWSERS_DIR = root / "browsers"
    multiversion.CONFIG_FILE = root / "config.json"
    multiversion.REPO_CACHE_FILE = root / "repo_cache.json"
    multiversion.COMPAT_FLAG = root / ".0.5_FLAG"

    for candidate in (multiversion.BROWSERS_DIR, multiversion.CONFIG_FILE):
        if root not in candidate.parents:
            raise InstallError("Umleitung des Browser-Verzeichnisses fehlgeschlagen")

    _redirected = root
    return root


def executable() -> Optional[Path]:
    """Path of the installed binary, or None if nothing is installed."""
    _redirect()
    from camoufox import multiversion, pkgman

    active = multiversion.get_active_path()
    if active is None or not active.exists():
        return None
    try:
        return Path(pkgman.launch_path(active))
    except Exception:
        return None


def state() -> Dict[str, Any]:
    """What the user interface needs to decide whether to offer a download."""
    binary = executable()
    version = ""
    if binary is not None:
        from camoufox import pkgman

        with contextlib.suppress(Exception):
            version = pkgman.installed_verstr()
    return {
        "installed": binary is not None,
        "path": str(binary) if binary else "",
        "version": version,
        "directory": str(root_dir()),
    }


def install(on_progress: Optional[ProgressCallback] = None, replace: bool = False) -> Dict[str, Any]:
    """Download and unpack the binary. Blocking; call from a worker thread.

    `on_progress` is called as (phase, done, total). Phases are
    "suche", "laden" and "entpacken". Total is 0 when unknown.
    """
    if not _lock.acquire(blocking=False):
        raise InstallError("Es läuft bereits ein Download")
    try:
        _redirect()
        from camoufox import pkgman

        def report(phase: str, done: int, total: int) -> None:
            if on_progress is not None:
                on_progress(phase, done, total)

        report("suche", 0, 0)

        class _Fetcher(pkgman.CamoufoxFetcher):
            # The upstream fetcher draws a terminal progress bar. Standard
            # output is our handshake channel, so we take the callback
            # instead and keep the console quiet.
            def download_file(self, file, url):  # type: ignore[override]
                return pkgman.webdl(
                    url,
                    buffer=file,
                    bar=False,
                    progress_callback=lambda done, total: report("laden", done, total),
                )

        quiet = io.StringIO()
        try:
            with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
                fetcher = _Fetcher()
                fetcher.install(replace=replace)
        except Exception as error:  # noqa: BLE001 - reported to the user as text
            raise InstallError(str(error) or error.__class__.__name__) from error

        report("entpacken", 1, 1)
        result = state()
        if not result["installed"]:
            raise InstallError("Nach dem Download war kein Programm auffindbar")
        return result
    finally:
        _lock.release()


def busy() -> bool:
    return _lock.locked()
