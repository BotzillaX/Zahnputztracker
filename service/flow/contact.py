"""Contacting one entry (spec 8).

The fourteen steps of 8.1 are in this file, in that order. What each step
touches on the page comes from the roles the user taught (see
contract.py). Two rules run through everything:

* An entry counts as done only after a confirmed send (8.4). The marker
  in the database is written before the send and confirmed after it, so a
  crash in between leaves a trace that is decided by a person, never
  automatically repeated.
* Nothing is guessed. A missing role, a form that does not appear, a
  confirmation that stays away: each of those ends the run with a named
  outcome and, where it helps, a recorded incident.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..engine.approval import ALLOWED, gate
from ..engine.runner import (
    EngineStop,
    element,
    role_visible,
    set_choice,
    wait_for_role,
)
from ..registry import store as registry_store
from ..storage import config as config_store
from ..storage import database, paths
from ..telemetry import incidents, spans
from ..text import ComposerError, build, generate
from ..text.prompt import PromptError
from . import contract

MAX_TEXT = 200_000


class ContactError(RuntimeError):
    """The run ended early. The outcome says how."""


def screenshot_file() -> Path:
    """One file, overwritten per request: it is only shown while asking."""
    return paths.local_dir() / "traces" / "freigabe.png"


def _answer_pair(settings: Dict[str, Any], label: str) -> Optional[Dict[str, str]]:
    for entry in settings.get("answers") or []:
        if str(entry.get("label", "")) == label:
            return {
                "label": label,
                "value": str(entry.get("value", "")),
                "display": str(entry.get("display", "")),
            }
    return None


async def _shoot(page: Any) -> bool:
    target = screenshot_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        # The overlay is never part of saved material (spec 2.5).
        await page.evaluate("() => window.__ztOverlay.hide()")
        try:
            await page.screenshot(path=str(target))
        finally:
            await page.evaluate("() => window.__ztOverlay.show()")
        return True
    except Exception:  # noqa: BLE001 - a missing picture must not stop the run
        return False


async def _planned_fields(
    page: Any, document: Dict[str, Any], settings: Dict[str, Any], on_page: bool = True
) -> List[Dict[str, str]]:
    """The form fields and what would go into them.

    With ``on_page`` only the fields that are actually visible right now
    are listed. Before the form is opened there are none, so the first
    approval of the test mode asks for the whole list instead: it is
    meant to show what the run would fill in, not what happens to be on
    screen at that second.
    """
    planned: List[Dict[str, str]] = []
    for role in contract.by_prefix(document, contract.FORM_FIELD_PREFIX):
        try:
            if on_page and not await role_visible(page, document, role["id"]):
                continue
        except EngineStop:
            continue
        name = role.get("answer", "")
        pair = _answer_pair(settings, name) if name else None
        planned.append(
            {
                "role": role["id"],
                "label": role["label"],
                "answer": name,
                "value": pair["display"] or pair["value"] if pair else "",
                "known": bool(pair),
            }
        )
    return planned


async def _fill_fields(
    page: Any, document: Dict[str, Any], planned: List[Dict[str, str]], settings: Dict[str, Any]
) -> List[Dict[str, str]]:
    """Fill what has an answer, leave the rest alone (8.3)."""
    done: List[Dict[str, str]] = []
    for entry in planned:
        if not entry["known"]:
            # An unassigned field stays empty and the send is tried
            # anyway. If the confirmation then stays away, the incident
            # shows which field it was.
            bus.publish("field_unassigned", role=entry["role"], label=entry["label"])
            continue
        pair = _answer_pair(settings, entry["answer"]) or {"value": "", "display": ""}
        locator = await element(page, document, entry["role"])
        shape = await locator.evaluate("(node) => node.tagName.toLowerCase()")
        if shape in ("select", "input"):
            kind = await locator.evaluate("(node) => (node.type || '').toLowerCase()")
        else:
            kind = ""
        if shape == "select" or kind in ("checkbox", "radio"):
            # A choice needs the internal value the page uses.
            await set_choice(page, locator, pair["value"] or pair["display"], entry["label"])
        else:
            await locator.fill(pair["display"] or pair["value"])
        done.append(entry)
    return done


async def _confirmed(instance: Any, document: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """Was the send confirmed (8.4). Returns how, or an empty string."""
    page = instance.page
    known = contract.roles_of(document)
    limit = float(settings["limits"].get("submit.confirm", 45))
    quiet = float(settings.get("confirm_wait_s") or 3.0)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + limit
    gone_since = None

    while loop.time() < deadline:
        if contract.taught(known.get(contract.CONFIRMATION_MARKER)):
            try:
                if await role_visible(page, document, contract.CONFIRMATION_MARKER):
                    return "Bestätigung erschienen"
            except EngineStop:
                pass
        try:
            still_there = await role_visible(page, document, contract.SUBMIT_ACTION)
        except EngineStop:
            still_there = True
        if still_there:
            gone_since = None
        else:
            if gone_since is None:
                gone_since = loop.time()
            elif loop.time() - gone_since >= quiet:
                return f"Absende-Element seit {quiet} s verschwunden"
        await asyncio.sleep(0.5)
    return ""


def _settle(key: str, status: str, **fields: Any) -> None:
    connection = database.connect()
    try:
        database.set_status(connection, key, status, **fields)
    finally:
        connection.close()


async def _ask(request: Dict[str, Any]) -> bool:
    answer = await gate.ask(request)
    return answer["decision"] == ALLOWED


async def contact(instance: Any, key: str, url: str, title: str = "") -> Dict[str, Any]:
    """Work through spec 8.1 for one entry."""
    document = registry_store.load(instance.role)
    missing = contract.missing(document, contract.REQUIRED_CONTACT)
    if missing:
        names = ", ".join(contract.LABELS.get(name, name) for name in missing)
        raise ContactError(f"Für den Vorgang fehlt noch: {names}")

    settings = config_store.load()
    known = contract.roles_of(document)
    page = instance.page
    review = bool(settings.get("review_mode", True))
    result: Dict[str, Any] = {"key": key, "url": url, "title": title, "status": "", "reason": "",
                              "incident": "", "text": "", "fields": []}
    bus.publish("item_started", key=key, url=url, review=review)

    connection = database.connect()
    try:
        database.see(connection, key, url=url, title=title)
    finally:
        connection.close()

    async def stop(status: str, reason: str, incident: str = "") -> Dict[str, Any]:
        _settle(key, status, reason=reason, incident=incident, url=url, title=title,
                message=result.get("text", ""))
        result["status"] = status
        result["reason"] = reason
        result["incident"] = incident
        bus.publish("item_finished", key=key, status=status, reason=reason, incident=incident)
        return result

    async def failed(operation: str, reason: str, status: str) -> Dict[str, Any]:
        incident = await incidents.capture(instance, document, operation, reason, key=key)
        return await stop(status, reason, incident)

    try:
        # 1 and 2: the address is opened, never a link that is clicked.
        limit = float(settings["limits"].get("item.open", 60))
        try:
            async with spans.span("item.open", instance=instance, key=key):
                await instance.navigate(url, limit)
                # 3: wait for the page to be ready.
                await wait_for_role(page, document, contract.READY_MARKER, limit, True)
        except EngineStop as error:
            return await failed("eintrag_oeffnen", str(error), database.STATUS_FAILED)

        # 4: a reason to leave this one alone.
        for role in contract.by_prefix(document, contract.EXCLUSION_PREFIX):
            if await role_visible(page, document, role["id"]):
                return await stop(database.STATUS_SKIPPED, f"Ausschluss: {role['label']}")

        # 5: the page says it has been done already.
        if contract.taught(known.get(contract.ALREADY_MARKER)):
            if await role_visible(page, document, contract.ALREADY_MARKER):
                return await stop(database.STATUS_ALREADY, "Von der Seite als erledigt gemeldet")

        # 6: the visible text, read from the page itself.
        page_text = str(await page.evaluate(
            "() => document.body ? document.body.innerText : ''"
        ))[:MAX_TEXT]
        if not page_text.strip():
            return await failed("text_lesen", "Die Seite hat keinen sichtbaren Text",
                                database.STATUS_FAILED)

        planned = await _planned_fields(page, document, settings, on_page=False)
        result["fields"] = planned

        # First approval of the test mode (decision 10): what was found,
        # before anything is generated.
        if review:
            _settle(key, database.STATUS_PENDING_REVIEW, url=url, title=title)
            picture = await _shoot(page)
            allowed = await _ask({
                "mode": "vorschau", "scope": instance.role, "state": "", "state_label": "Vorgang",
                "action": "vorschau", "key": key, "url": url, "title": title,
                "screenshot": picture, "fields": planned,
                "description": "Für diesen Eintrag ein Anschreiben erzeugen?",
            })
            if not allowed:
                return await stop(database.STATUS_OPEN, "Vorschau abgelehnt")

        # 7: the message text.
        try:
            prompt, _ = build(settings["composer"].get("prompt", ""), settings,
                              page_text, url=url, title=title)
            async with spans.span("compose.generate", instance=instance, key=key):
                text = await generate(prompt, settings["composer"])
        except (ComposerError, PromptError) as error:
            return await failed("anschreiben", str(error), database.STATUS_FAILED)
        result["text"] = text
        bus.publish("text_generated", key=key, characters=len(text))

        # 8 and 9: open the form. No message field means the entry is
        # gone. Not a failure, and explicitly not "contacted".
        form_limit = float(settings["limits"].get("form.open", 45))
        try:
            async with spans.span("form.open", instance=instance, key=key):
                if contract.taught(known.get(contract.OPEN_FORM)):
                    await (await element(page, document, contract.OPEN_FORM)).click()
                await wait_for_role(page, document, contract.MESSAGE_FIELD, form_limit, True)
        except EngineStop:
            return await stop(database.STATUS_SKIPPED, "Nicht mehr verfügbar")

        # 10 and 11: fill in, and scrolling is not optional (8.3).
        async with spans.span("form.fill", instance=instance, key=key):
            await (await element(page, document, contract.MESSAGE_FIELD)).fill(text)
            planned = await _planned_fields(page, document, settings)
            result["fields"] = planned
            await _fill_fields(page, document, planned, settings)
            await (await element(page, document,
                                contract.SUBMIT_ACTION)).scroll_into_view_if_needed()

        # Second approval of the test mode: the finished text, before it
        # goes anywhere.
        if review:
            picture = await _shoot(page)
            allowed = await _ask({
                "mode": "versand", "scope": instance.role, "state": "", "state_label": "Vorgang",
                "action": "versand", "key": key, "url": url, "title": title,
                "screenshot": picture, "fields": planned, "text": text,
                "description": "Diesen Text jetzt absenden?",
            })
            if not allowed:
                return await stop(database.STATUS_OPEN, "Versand abgelehnt")

        # 12: the marker goes in before the send, not after it.
        connection = database.connect()
        try:
            database.mark_dispatch_started(connection, key, evidence=url)
        finally:
            connection.close()
        bus.publish("dispatch_started", key=key)
        async with spans.span("submit.send", instance=instance, key=key):
            await (await element(page, document, contract.SUBMIT_ACTION)).click()

        # 13: confirmation.
        async with spans.span("submit.confirm", instance=instance, key=key):
            how = await _confirmed(instance, document, settings)
        if not how:
            # The click happened. Whether it arrived is unknown, so this
            # is not a failure that may be repeated on its own (8.4).
            incident = await incidents.capture(
                instance, document, "versand", "Keine Bestätigung nach dem Absenden", key=key
            )
            return await stop(database.STATUS_UNCLEAR, "Keine Bestätigung", incident)

        connection = database.connect()
        try:
            database.mark_dispatch_confirmed(connection, key)
        finally:
            connection.close()

        # 14: only now.
        _settle(key, database.STATUS_CONTACTED, reason=how, message=text, url=url, title=title)
        result["status"] = database.STATUS_CONTACTED
        result["reason"] = how
        bus.publish("item_finished", key=key, status=database.STATUS_CONTACTED, reason=how)
        return result

    except EngineStop as error:
        return await failed("vorgang", str(error), database.STATUS_FAILED)
    except ContactError:
        raise
    except Exception as error:  # noqa: BLE001 - recorded, never swallowed
        return await failed("vorgang", f"{type(error).__name__}: {error}", database.STATUS_FAILED)
