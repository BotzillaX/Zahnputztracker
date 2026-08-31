"""Screenshot ring buffer (spec 6.3).

One picture every two seconds, the last sixty kept in memory. That is
the two minutes before an event, which is the stretch that usually
explains it. Nothing of this touches the disk until a threshold is
crossed; then the sequence is written into the incident folder.

The buffer is an observer, and it stays out of the way: while an
operation is working on the page, no picture is taken. A screenshot in
this browser holds the page for a moment, and a click that runs into
that moment waits for it. Measuring runtimes with a stopwatch that
occasionally trips the runner would be worse than a gap in the pictures.

What is lost by that is small: the pictures cover the run-up to an
operation, and the moment of the operation itself is held by the state
captures at the two thresholds, which take their own picture.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from collections import deque

from ..api.events import bus
from ..storage import config as config_store
from . import spans

INTERVAL_S = 2.0
MAX_FRAMES = 60
SHOT_TIMEOUT_S = 2.0
# After this many pictures in a row that did not work, the buffer slows
# down. A browser that cannot be photographed right now is left alone
# instead of being asked every two seconds.
BACKOFF_AFTER = 5
BACKOFF_S = 15.0

_recorders: Dict[str, "Recorder"] = {}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%H%M%S")


class Recorder:
    """Keeps the recent look of one browser in memory."""

    def __init__(self, instance: Any) -> None:
        self.instance = instance
        self.scope = getattr(instance, "role", "")
        self.frames: Deque[Tuple[str, bytes]] = deque(maxlen=MAX_FRAMES)
        self._task: Optional[asyncio.Task] = None
        self.failures = 0
        self.skipped = 0

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.frames.clear()

    async def _loop(self) -> None:
        misses = 0
        while True:
            await asyncio.sleep(BACKOFF_S if misses >= BACKOFF_AFTER else INTERVAL_S)
            page = getattr(self.instance, "page", None)
            if page is None:
                continue
            if spans.busy(self.scope):
                # An operation is on the page. It goes first.
                self.skipped += 1
                continue
            try:
                data = await asyncio.wait_for(self._shot(page), timeout=SHOT_TIMEOUT_S * 2)
            except Exception:  # noqa: BLE001 - a lost frame is only a lost frame
                self.failures += 1
                misses += 1
                continue
            misses = 0
            if data:
                self.frames.append((_stamp(), data))

    @staticmethod
    async def _shot(page: Any) -> bytes:
        # The overlay is never part of saved material (spec 2.5).
        try:
            await page.evaluate("() => window.__ztOverlay.hide()")
        except Exception:  # noqa: BLE001
            pass
        try:
            # The limit is handed to the browser itself, not only to the
            # waiting here: a picture that is merely abandoned would keep
            # the page busy and the next click would wait for it.
            return await page.screenshot(
                type="jpeg", quality=45, timeout=SHOT_TIMEOUT_S * 1000
            )
        finally:
            try:
                await page.evaluate("() => window.__ztOverlay.show()")
            except Exception:  # noqa: BLE001
                pass

    def dump(self, folder: Path) -> int:
        """Write the sequence, oldest first. Returns the number of files."""
        pictures = list(self.frames)
        if not pictures:
            return 0
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return 0
        written = 0
        for index, (stamp, data) in enumerate(pictures, start=1):
            try:
                (folder / f"{index:02d}-{stamp}.jpg").write_bytes(data)
                written += 1
            except OSError:
                break
        return written


def attach(instance: Any) -> Optional[Recorder]:
    if not config_store.load().get("record_frames", True):
        return None
    scope = getattr(instance, "role", "")
    recorder = _recorders.get(scope)
    if recorder is None or recorder.instance is not instance:
        recorder = Recorder(instance)
        _recorders[scope] = recorder
    recorder.start()
    bus.publish("frames_started", scope=scope)
    return recorder


async def detach(scope: str) -> None:
    recorder = _recorders.pop(scope, None)
    if recorder is not None:
        await recorder.stop()


async def detach_all() -> None:
    for scope in list(_recorders):
        await detach(scope)


def recorder(scope: str) -> Optional[Recorder]:
    return _recorders.get(scope)


def dump(scope: str, folder: Path) -> int:
    found = _recorders.get(scope)
    return found.dump(folder) if found else 0


def state() -> List[Dict[str, Any]]:
    return [
        {"scope": scope, "frames": len(item.frames), "failures": item.failures,
         "skipped": item.skipped}
        for scope, item in sorted(_recorders.items())
    ]
