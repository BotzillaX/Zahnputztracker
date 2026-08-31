"""In-process event bus.

Every subscriber gets its own bounded queue. A slow or dead subscriber
drops its oldest events instead of blocking the producer: the service
must never stall because the user interface is gone.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Iterator, List

MAX_QUEUE = 500
MAX_REPLAY = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class EventBus:
    def __init__(self) -> None:
        self._subscribers: List[asyncio.Queue] = []
        self._replay: Deque[Dict[str, Any]] = deque(maxlen=MAX_REPLAY)
        self._seq = 0
        self._loop: Any = None

    def publish(self, kind: str, **payload: Any) -> Dict[str, Any]:
        self._seq += 1
        event: Dict[str, Any] = {"seq": self._seq, "ts": _now(), "kind": kind, **payload}
        self._replay.append(event)

        # Some work runs in a worker thread (the download, for example).
        # Queues of the event loop must not be touched from there, so
        # the delivery is handed back to the loop.
        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False
        if in_loop or self._loop is None:
            self._deliver(event)
        else:
            self._loop.call_soon_threadsafe(self._deliver, event)
        return event

    def _deliver(self, event: Dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:  # pragma: no cover - race only
                    pass
            queue.put_nowait(event)

    def replay(self, after_seq: int = 0) -> Iterator[Dict[str, Any]]:
        for event in list(self._replay):
            if event["seq"] > after_seq:
                yield event

    def subscribe(self) -> asyncio.Queue:
        # Called from the event loop, which is the loop every later
        # delivery has to run on.
        self._loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


bus = EventBus()
