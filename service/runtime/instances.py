"""The two permanent browser instances.

Spec section 5.1: one instance searches (not signed in, fresh fingerprint
per application start), one instance works signed in on a persistent
profile. Both are opened once and stay open. Both run in exactly one tab.

This module owns the browser objects and the desired visibility of their
windows. It does not touch windows itself: the host process enforces the
desired state (see windows.rs), the service only reports process ids.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from ..api.events import bus
from ..storage import paths
from . import browser_install

SEARCH = "search"
SESSION = "session"
ROLES = (SEARCH, SESSION)

# German labels for the user interface, kept next to the roles so the
# frontend does not invent its own wording.
ROLE_LABELS = {SEARCH: "Such-Browser", SESSION: "Sitzungs-Browser"}

# Firefox is told to keep everything in the current tab. The one tab rule
# is still enforced below, this only removes the most common cause.
USER_PREFS: Dict[str, Any] = {
    "browser.link.open_newwindow": 1,
    "browser.link.open_newwindow.restriction": 0,
    "browser.tabs.loadDivertedInBackground": True,
    "browser.startup.homepage": "about:blank",
    "browser.aboutwelcome.enabled": False,
    "browser.sessionstore.resume_from_crash": False,
}


class BrowserError(RuntimeError):
    """Raised when an instance cannot do what was asked of it."""


def _profile_dir(role: str) -> Path:
    return paths.local_dir() / "profiles" / role


def _options_file(role: str) -> Path:
    return _profile_dir(role) / "launch-options.json"


def _browser_processes(executable: Path) -> Dict[int, int]:
    """Browser processes below our own process, as pid to parent pid.

    Matching happens on the program name and on descent from this
    process, not on the full path: the path a process reports can differ
    from the path we launched (redirection, links, packaged hosts).
    """
    name = executable.name.lower()
    found: Dict[int, int] = {}
    try:
        me = psutil.Process()
    except psutil.Error:
        return found
    for process in me.children(recursive=True):
        try:
            if process.name().lower() == name:
                found[process.pid] = process.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _new_processes(executable: Path, before: set) -> List[int]:
    """Every browser process that appeared since the snapshot.

    A browser run consists of several processes: a starter, the process
    that owns the window and one process per page. Which of them carries
    the window is not fixed, so all of them are reported and the host
    process decides per window.
    """
    fresh = {
        pid: parent for pid, parent in _browser_processes(executable).items() if pid not in before
    }
    roots = [pid for pid, parent in fresh.items() if parent not in fresh]
    rest = [pid for pid in fresh if pid not in roots]
    return roots + rest


def _running_pids(executable: Path) -> set:
    return set(_browser_processes(executable))


class Instance:
    """One browser window with exactly one tab."""

    def __init__(self, role: str) -> None:
        self.role = role
        self.context: Any = None
        self.page: Any = None
        self.pid: Optional[int] = None
        self.pids: List[int] = []
        self.visible = False
        self.extra_pages_closed = 0
        self.last_error = ""

    # ------------------------------------------------------------- lifecycle

    async def start(
        self,
        playwright: Any,
        executable: Path,
        width: int,
        height: int,
        before: set,
    ) -> None:
        from camoufox.async_api import AsyncNewBrowser

        profile = _profile_dir(self.role)
        if self.role == SEARCH:
            # A fresh fingerprint on every application start means a fresh
            # profile: nothing of the previous run may survive.
            shutil.rmtree(profile, ignore_errors=True)
        profile.mkdir(parents=True, exist_ok=True)

        options = self._stored_options()
        reused = options is not None
        if options is None:
            options = await asyncio.to_thread(
                self._build_options, executable, profile, width, height
            )
        else:
            # Paths may have moved between runs, the fingerprint may not.
            options["executable_path"] = str(executable)
            options["user_data_dir"] = str(profile)
            options["headless"] = False

        context = await AsyncNewBrowser(
            playwright, from_options=options, persistent_context=True
        )

        self.context = context
        self.page = context.pages[0] if context.pages else await context.new_page()
        context.on("page", self._reject_extra_page)
        context.on("close", self._forget)
        self.pids = _new_processes(executable, before)
        self.pid = self.pids[0] if self.pids else None
        self.visible = False
        self.last_error = ""

        if self.role == SESSION and not reused:
            self._remember_options(options)

        bus.publish("browser_started", role=self.role, pid=self.pid)

    @staticmethod
    def _build_options(
        executable: Path, profile: Path, width: int, height: int
    ) -> Dict[str, Any]:
        from camoufox.utils import launch_options

        return launch_options(
            headless=False,
            executable_path=str(executable),
            user_data_dir=str(profile),
            window=(width, height),
            firefox_user_prefs=dict(USER_PREFS),
            # Proxy support is not part of this version. The shape stays so a
            # per instance proxy can be added later without restructuring
            # (spec 5.1).
            proxy=None,
        )

    def _stored_options(self) -> Optional[Dict[str, Any]]:
        """Launch options of a previous run, for a stable fingerprint."""
        if self.role != SESSION:
            return None
        target = _options_file(self.role)
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _remember_options(self, options: Dict[str, Any]) -> None:
        """Freeze the fingerprint that was actually used, bound to the profile."""
        try:
            _options_file(self.role).write_text(
                json.dumps(options, indent=2, default=str), encoding="utf-8"
            )
        except (OSError, TypeError, ValueError) as error:
            bus.publish("browser_note", role=self.role, message=f"Merken misslang: {error}")

    async def close(self) -> None:
        context, self.context, self.page = self.context, None, None
        self.pid = None
        self.pids = []
        if context is not None:
            try:
                await context.close()
            except Exception:  # noqa: BLE001 - a dead browser is closed enough
                pass

    def _forget(self, *_: Any) -> None:
        self.context = None
        self.page = None
        self.pid = None
        self.pids = []
        bus.publish("browser_gone", role=self.role)

    # ------------------------------------------------------------ one tab rule

    def _reject_extra_page(self, page: Any) -> None:
        """Spec 5.2: a second page must not exist. Close it and record it."""
        if page is self.page:
            return
        self.extra_pages_closed += 1
        bus.publish("extra_page_closed", role=self.role, url=page.url or "")
        asyncio.ensure_future(self._close_page(page))

    @staticmethod
    async def _close_page(page: Any) -> None:
        try:
            await page.close()
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------------------- behaviour

    async def navigate(self, url: str, timeout_s: float) -> str:
        """Go to an address. Links are never clicked (spec 5.2)."""
        if self.page is None:
            raise BrowserError(f"{ROLE_LABELS[self.role]} läuft nicht")
        await self.page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
        return self.page.url

    def snapshot(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "label": ROLE_LABELS[self.role],
            "running": self.context is not None,
            "pid": self.pid,
            "pids": list(self.pids),
            "visible": self.visible,
            "url": (self.page.url if self.page is not None else ""),
            "tabs": len(self.context.pages) if self.context is not None else 0,
            "extra_pages_closed": self.extra_pages_closed,
            "last_error": self.last_error,
        }


class Fleet:
    """Both instances, started and stopped together."""

    def __init__(self) -> None:
        self.instances: Dict[str, Instance] = {role: Instance(role) for role in ROLES}
        self.paused = False
        self._playwright: Any = None
        self._lock = asyncio.Lock()
        self._starting = False

    @property
    def running(self) -> bool:
        return any(instance.context is not None for instance in self.instances.values())

    def instance(self, role: str) -> Instance:
        if role not in self.instances:
            raise BrowserError("unbekannte Instanz")
        return self.instances[role]

    async def start(self, browsers_config: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            if self.running:
                return self.snapshot()
            executable = browser_install.executable()
            if executable is None:
                raise BrowserError("Der Browser ist noch nicht geladen")

            from playwright.async_api import async_playwright

            self._starting = True
            try:
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                for role in ROLES:
                    size = browsers_config.get(role, {})
                    before = _running_pids(executable)
                    instance = self.instances[role]
                    try:
                        await instance.start(
                            self._playwright,
                            executable,
                            int(size.get("width", 1280)),
                            int(size.get("height", 720)),
                            before,
                        )
                    except Exception as error:  # noqa: BLE001 - surfaced to the user
                        instance.last_error = str(error)
                        bus.publish("browser_failed", role=role, message=str(error))
                        raise BrowserError(
                            f"{ROLE_LABELS[role]} konnte nicht starten: {error}"
                        ) from error
            finally:
                self._starting = False
            self.paused = False
            bus.publish("browser_fleet", running=True)
            return self.snapshot()

    async def stop(self) -> Dict[str, Any]:
        async with self._lock:
            for instance in self.instances.values():
                await instance.close()
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._playwright = None
            bus.publish("browser_fleet", running=False)
            return self.snapshot()

    def set_paused(self, paused: bool) -> Dict[str, Any]:
        """Spec 5.4: both browsers stay open and keep their state."""
        self.paused = bool(paused)
        bus.publish("paused" if self.paused else "resumed")
        return self.snapshot()

    def set_visible(self, role: str, visible: bool) -> Dict[str, Any]:
        instance = self.instance(role)
        instance.visible = bool(visible)
        bus.publish("browser_visibility", role=role, visible=instance.visible)
        return self.snapshot()

    def wanted_windows(self) -> List[Dict[str, Any]]:
        """What the host process has to enforce: process id and visibility."""
        return [
            {"role": instance.role, "pids": list(instance.pids), "visible": instance.visible}
            for instance in self.instances.values()
            if instance.pids
        ]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "starting": self._starting,
            "paused": self.paused,
            "binary": browser_install.state(),
            "downloading": browser_install.busy(),
            "instances": [instance.snapshot() for instance in self.instances.values()],
        }


fleet = Fleet()
