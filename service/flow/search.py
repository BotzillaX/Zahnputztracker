"""The search cycle (spec 5.5).

The seven steps of 5.5 are in this file, in that order: reload, wait a
random time, read the whole visible result list, compare the identifiers
against the database, and work through every entry that is new before the
next cycle begins.

Three rules decide the shape of it:

* The **whole** visible list is read, never a fixed number of top rows.
  Several entries are regularly published at the same moment, and a
  cycle that only ever looked at the first row would lose all but one.
* New entries are worked through in reverse list order. The list is
  newest first, so the reverse is oldest first, and the oldest new entry
  is the one with the least time left.
* Nothing here decides anything about content. An entry is new or it is
  not, and that is decided by its identifier alone.

The loop stops rather than improvising. Without an address, without a
usable template and without the taught role of the result list it does
not start at all, and after a small number of failed cycles in a row it
stops and says so.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..engine.approval import gate
from ..engine.runner import open_run
from ..registry import resolve as registry_resolve
from ..registry import store as registry_store
from ..runtime.instances import fleet
from ..storage import config as config_store
from ..storage import database
from ..telemetry import notify, spans, tracing
from . import contact as contact_flow
from . import contract, keys
from . import login as login_flow

# How many cycles may fail in a row before the loop stops. A single
# failed cycle is usually the network; three in a row is a situation a
# person has to look at.
MAX_FAILED_CYCLES = 3
# Steps of the waiting time, small enough that a stop is felt at once.
TICK_S = 0.25
MAX_TITLE = 200

# What the browser is asked for each marked entry of the list. The role
# may be taught on the link itself or on the row that contains it; both
# are answered without guessing, and a row holding several links is
# reported instead of one of them being picked.
_READ = """
nodes => nodes.map(node => {
  const inner = node.querySelectorAll('a[href]');
  let target = node.closest('a[href]');
  if (!target && inner.length === 1) target = inner[0];
  return {
    href: target ? (target.getAttribute('href') || '') : '',
    links: target ? 1 : inner.length,
    text: (node.innerText || '').trim().slice(0, 200)
  };
})
"""


def _list_role(document: Dict[str, Any]) -> Dict[str, Any]:
    for item in document["roles"]:
        if item["id"] == contract.ITEM_LINK:
            return item
    raise SearchError(
        f"Im Such-Browser fehlt die Rolle '{contract.LABELS[contract.ITEM_LINK]}'"
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SearchError(RuntimeError):
    """The cycle cannot start or cannot go on. The text says why."""


class Loop:
    """One search cycle after the other, until it is stopped."""

    def __init__(self) -> None:
        self.running = False
        self.started = ""
        self.cycles = 0
        self.last_at = ""
        self.last_seen = 0
        self.last_new = 0
        self.found_total = 0
        self.contacted = 0
        self.unreadable = 0
        self.current = ""
        self.waiting_s = 0.0
        self.failures = 0
        self.stopped = ""
        self.queue: List[Dict[str, str]] = []
        # Entries that ended this run without a settled status. They are
        # not offered again in this run, so one entry that keeps failing
        # cannot occupy every following cycle. A new start tries again.
        self.deferred: Dict[str, str] = {}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "started": self.started,
            "cycles": self.cycles,
            "last_at": self.last_at,
            "last_seen": self.last_seen,
            "last_new": self.last_new,
            "found_total": self.found_total,
            "contacted": self.contacted,
            "unreadable": self.unreadable,
            "current": self.current,
            "waiting_s": round(self.waiting_s, 1),
            "failures": self.failures,
            "stopped": self.stopped,
            "queue": list(self.queue),
            "deferred": [{"key": key, "reason": reason}
                         for key, reason in self.deferred.items()],
        }

    # ------------------------------------------------------------- checks

    @staticmethod
    def _prepare(search: Any) -> Dict[str, Any]:
        """Everything the loop needs, or a clear reason why it cannot run."""
        settings = config_store.load()
        address = str(settings["source"].get("url") or "").strip()
        template = str(settings["source"].get("item_url_template") or "").strip()
        if not address:
            raise SearchError("Es ist keine Adresse der Ergebnisseite hinterlegt")
        if not keys.usable(template):
            raise SearchError(
                "Die Adressvorlage für Einzelseiten braucht genau einen Platzhalter "
                f"{keys.PLACEHOLDER}. Ohne ihn lässt sich keine Kennung ermitteln."
            )
        document = registry_store.load(search.role)
        if contract.missing(document, contract.REQUIRED_SEARCH):
            raise SearchError(
                f"Im Such-Browser fehlt die Rolle '{contract.LABELS[contract.ITEM_LINK]}'"
            )
        if _list_role(document).get("menge") != "liste":
            # With quantity "einzel" only one element is marked, so a
            # list of ten new entries would look like one. That is a
            # setting the user has to correct, not something to work
            # around here.
            raise SearchError(
                f"Die Rolle '{contract.LABELS[contract.ITEM_LINK]}' muss die Menge "
                "'liste' haben, sonst wird nur ein Eintrag gelesen"
            )
        return {"address": address, "template": template}

    def check(self, search: Any) -> Dict[str, Any]:
        """Raise SearchError unless the cycle could start right now.

        Called before the loop becomes a background task, so a missing
        setting is answered to the caller instead of appearing as a
        failure in the event stream a second later.
        """
        return self._prepare(search)

    # ------------------------------------------------------------ waiting

    async def _hold(self) -> None:
        """Wait while something else has the floor.

        An open approval stops everything (decision 9), and so does the
        pause switch. Neither is an error, so neither is counted.
        """
        while gate.state()["request"] is not None or fleet.paused:
            await asyncio.sleep(TICK_S)

    async def _sleep(self, seconds: float) -> None:
        self.waiting_s = seconds
        while self.waiting_s > 0:
            await asyncio.sleep(TICK_S)
            self.waiting_s = max(0.0, self.waiting_s - TICK_S)
            await self._hold()
        self.waiting_s = 0.0

    async def _idle(self, page: Any, seconds: float) -> None:
        """Small movements in the search browser (12.1, off by default).

        Only scrolling, never a click: a click could open something, and
        this browser is meant to read a list and nothing else.
        """
        self.waiting_s = seconds
        while self.waiting_s > 0:
            step = min(self.waiting_s, random.uniform(1.5, 4.0))
            await asyncio.sleep(step)
            self.waiting_s = max(0.0, self.waiting_s - step)
            try:
                await page.mouse.wheel(0, random.randint(-240, 420))
            except Exception:  # noqa: BLE001 - a lost movement is nothing
                pass
            await self._hold()
        self.waiting_s = 0.0

    async def _wait(self, search: Any, settings: Dict[str, Any]) -> None:
        low = float(settings["source"].get("reload_min_s") or 10)
        high = float(settings["source"].get("reload_max_s") or 15)
        seconds = random.uniform(low, max(low, high))
        bus.publish("search_waiting", seconds=round(seconds, 1))
        if settings["source"].get("idle_behavior"):
            async with spans.span("search.idle_behavior", instance=search):
                await self._idle(search.page, seconds)
        else:
            await self._sleep(seconds)

    # ------------------------------------------------------------ reading

    async def _read(self, search: Any, document: Dict[str, Any],
                    template: str) -> List[Dict[str, str]]:
        """The whole visible result list as identifier and address."""
        role = _list_role(document)
        resolution = await registry_resolve.locate(search.page, role)
        if not resolution.found:
            await registry_resolve.clear(search.page)
            raise SearchError(
                f"{role['label']}: {resolution.reason or 'nichts gefunden'}"
            )
        try:
            raw = await registry_resolve.locator(search.page, resolution).evaluate_all(_READ)
        finally:
            await registry_resolve.clear(search.page)

        base = search.page.url
        entries: List[Dict[str, str]] = []
        unreadable = 0
        seen = set()
        for item in raw:
            key = keys.key_of(str(item.get("href") or ""), template, base)
            if not key:
                unreadable += 1
                continue
            if key in seen:
                # The same entry twice in one list is one entry.
                continue
            seen.add(key)
            entries.append({
                "key": key,
                "url": keys.address_of(key, template),
                "title": str(item.get("text") or "")[:MAX_TITLE],
            })
        self.unreadable = unreadable
        if unreadable:
            # Not an error of the run, but something the user has to see:
            # it usually means the template no longer fits the addresses.
            bus.publish("search_unreadable", count=unreadable, seen=len(raw))
        return entries

    @staticmethod
    def _new_ones(entries: List[Dict[str, str]]) -> List[str]:
        connection = database.connect()
        try:
            return database.unknown_keys(connection, [item["key"] for item in entries])
        finally:
            connection.close()

    # ------------------------------------------------------------- one go

    async def _handle(self, search: Any, session: Any, entry: Dict[str, str],
                      history: int) -> None:
        """One new entry, from the find to the documented outcome.

        The find belongs to the search browser, the run that follows to
        the session browser. Both are measured where they happen, so the
        statistics per browser stay meaningful.
        """
        async with spans.span("search.new_item_found", instance=search, key=entry["key"]):
            bus.publish("item_found", key=entry["key"], url=entry["url"],
                        title=entry["title"])
            notify.notify(notify.NEW_ITEM, entry["title"] or entry["key"],
                          key=entry["key"])

        self.current = entry["key"]
        self.found_total += 1
        await tracing.begin(session, "vorgang")
        try:
            open_run(entry["key"])
            await login_flow.ensure(session)
            result = await contact_flow.contact(
                session, entry["key"], entry["url"], entry["title"]
            )
            status = str(result.get("status") or "")
            if status == database.STATUS_CONTACTED:
                self.contacted += 1
            if status not in database.SETTLED_STATUS:
                self.deferred[entry["key"]] = str(result.get("reason") or status)
        except asyncio.CancelledError:
            tracing.mark(session.role, "Vorgang abgebrochen")
            raise
        except Exception as error:  # noqa: BLE001 - one entry, not the loop
            self.deferred[entry["key"]] = f"{type(error).__name__}: {error}"
            tracing.mark(session.role, "Vorgang endete mit einem Fehler")
            bus.publish("item_failed", key=entry["key"], reason=str(error))
        finally:
            self.current = ""
            try:
                await tracing.end(session, history)
            except Exception:  # noqa: BLE001 - a recording is never the job
                pass

    async def _cycle(self, search: Any, session: Any, ready: Dict[str, Any],
                     settings: Dict[str, Any]) -> None:
        self.cycles += 1
        history = int(settings.get("trace_history") or 20)
        document = registry_store.load(search.role)
        bus.publish("search_cycle", number=self.cycles)
        await tracing.begin(search, "suchlauf")
        try:
            # 1: load the result page again.
            limit = float(settings["limits"].get("search.reload", 60))
            async with spans.span("search.reload", instance=search):
                await search.navigate(ready["address"], limit)

            # 2: the random wait of 5.5, between loading and reading.
            await self._wait(search, settings)

            # 3: the whole visible list.
            async with spans.span("search.parse_results", instance=search):
                entries = await self._read(search, document, ready["template"])
            self.last_seen = len(entries)

            # 4: which of them still need work.
            unknown = set(self._new_ones(entries))
            fresh = [item for item in entries
                     if item["key"] in unknown and item["key"] not in self.deferred]
            self.last_new = len(fresh)
            self.last_at = _now()
        finally:
            try:
                await tracing.end(search, history)
            except Exception:  # noqa: BLE001
                pass

        if not fresh:
            return
        # 6: oldest new entry first, and all of them before the next cycle.
        self.queue = [item["key"] for item in reversed(fresh)]
        for entry in reversed(fresh):
            await self._hold()
            await self._handle(search, session, entry, history)
            self.queue = [key for key in self.queue if key != entry["key"]]
        self.queue = []

    # ---------------------------------------------------------------- run

    async def run(self, search: Any, session: Any) -> Dict[str, Any]:
        ready = self._prepare(search)
        self.running = True
        self.started = _now()
        self.stopped = ""
        self.failures = 0
        self.deferred = {}
        bus.publish("search_started")
        try:
            while True:
                await self._hold()
                settings = config_store.load()
                try:
                    await self._cycle(search, session, ready, settings)
                    self.failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 - counted, not lost
                    self.failures += 1
                    reason = f"{type(error).__name__}: {error}"
                    bus.publish("search_cycle_failed", reason=reason,
                                failures=self.failures)
                    if self.failures >= MAX_FAILED_CYCLES:
                        self.stopped = (
                            f"{self.failures} Zyklen in Folge fehlgeschlagen: {error}"
                        )
                        notify.notify(notify.BLOCKED, self.stopped)
                        break
                    await self._sleep(min(30.0, 5.0 * self.failures))
        finally:
            self.running = False
            self.current = ""
            self.waiting_s = 0.0
            self.queue = []
            bus.publish("search_stopped", reason=self.stopped)
        return self.state()


loop = Loop()


def readiness(search_document: Dict[str, Any]) -> Dict[str, Any]:
    """What the user interface shows before the cycle is started."""
    settings = config_store.load()
    template = str(settings["source"].get("item_url_template") or "").strip()
    report = contract.search_readiness(search_document)
    report["address"] = bool(str(settings["source"].get("url") or "").strip())
    report["template"] = keys.usable(template)
    report["placeholder"] = keys.PLACEHOLDER
    report["idle_behavior"] = bool(settings["source"].get("idle_behavior"))
    report["wait"] = [settings["source"].get("reload_min_s"),
                      settings["source"].get("reload_max_s")]
    return report
