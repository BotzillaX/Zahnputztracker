"""Signing in (spec 7).

The steps are in the code, what they touch on the page comes from the
roles the user taught. A code request is not worked around: the
application stops, asks for the code in its own window, types it in and
confirms. If that does not lead anywhere, it stops for good and says so
(7.2).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from ..api.events import bus
from ..engine.approval import ALLOWED, gate
from ..engine.runner import EngineStop, element, role_visible, wait_for_role
from ..registry import store as registry_store
from ..storage import config as config_store
from ..storage import secrets
from ..telemetry import incidents
from . import contract

# How often the whole procedure is tried before it stops (7.1.5).
MAX_ATTEMPTS = 3
STEP_S = 1.0


class SignInError(RuntimeError):
    """The sign in did not work. The reason is in the message."""


async def state(instance: Any) -> Dict[str, Any]:
    """Is the session signed in right now (7.3)."""
    document = registry_store.load(instance.role)
    known = contract.roles_of(document)
    marker = known.get(contract.SIGNED_IN)
    if not contract.taught(marker):
        return {"known": False, "signed_in": False,
                "reason": f"Die Rolle '{contract.LABELS[contract.SIGNED_IN]}' ist nicht angelernt"}
    try:
        visible = await role_visible(instance.page, document, contract.SIGNED_IN)
    except EngineStop as error:
        return {"known": False, "signed_in": False, "reason": str(error)}
    return {"known": True, "signed_in": visible, "reason": ""}


async def _ask_for_code(instance: Any) -> str:
    bus.publish("code_wanted", scope=instance.role)
    answer = await gate.ask(
        {
            "mode": "code",
            "scope": instance.role,
            "state": "",
            "state_label": "Anmeldung",
            "action": "code",
            "wants_text": True,
            "description": "Der Zugang verlangt einen Code. Bitte hier eintragen.",
        }
    )
    if answer["decision"] != ALLOWED:
        raise SignInError("Die Eingabe des Codes wurde abgebrochen")
    return answer["value"]


async def _attempt(instance: Any, document: Dict[str, Any], limit: float) -> bool:
    page = instance.page
    known = contract.roles_of(document)

    # The way in is optional: on many pages the form is already there.
    if contract.taught(known.get(contract.SIGN_IN_ENTRY)):
        if await role_visible(page, document, contract.SIGN_IN_ENTRY):
            await (await element(page, document, contract.SIGN_IN_ENTRY)).click()
            await wait_for_role(page, document, contract.IDENTITY_FIELD, limit, True)

    settings = config_store.load()
    identity = str(settings.get("account", {}).get("email") or "").strip()
    if not identity:
        raise SignInError("In den Einstellungen steht keine Kennung")
    password = secrets.get(secrets.ACCOUNT_PASSWORD)
    if not password:
        raise SignInError("Im Anmeldeinformationsspeicher liegt kein Passwort")

    await (await element(page, document, contract.IDENTITY_FIELD)).fill(identity)
    await (await element(page, document, contract.SECRET_FIELD)).fill(password)
    await (await element(page, document, contract.SIGN_IN_SUBMIT)).click()
    bus.publish("sign_in_submitted", scope=instance.role)

    deadline = asyncio.get_running_loop().time() + limit
    asked_for_code = False
    while asyncio.get_running_loop().time() < deadline:
        if await role_visible(page, document, contract.SIGNED_IN):
            return True
        if not asked_for_code and contract.taught(known.get(contract.SECOND_FACTOR_MARKER)):
            if await role_visible(page, document, contract.SECOND_FACTOR_MARKER):
                if not contract.taught(known.get(contract.SECOND_FACTOR_FIELD)):
                    raise SignInError(
                        "Es wird ein Code verlangt, aber "
                        f"'{contract.LABELS[contract.SECOND_FACTOR_FIELD]}' ist nicht angelernt"
                    )
                code = await _ask_for_code(instance)
                await (await element(page, document, contract.SECOND_FACTOR_FIELD)).fill(code)
                await (await element(page, document, contract.SIGN_IN_SUBMIT)).click()
                asked_for_code = True
                bus.publish("code_entered", scope=instance.role)
        await asyncio.sleep(STEP_S)
    return False


async def sign_in(instance: Any) -> Dict[str, Any]:
    """Run the taught sign in procedure. Raises SignInError on failure."""
    document = registry_store.load(instance.role)
    missing = contract.missing(document, contract.REQUIRED_SIGN_IN)
    if missing:
        names = ", ".join(contract.LABELS.get(name, name) for name in missing)
        raise SignInError(f"Für die Anmeldung fehlt noch: {names}")

    if await role_visible(instance.page, document, contract.SIGNED_IN):
        return {"signed_in": True, "attempts": 0, "already": True}

    limit = float(config_store.load()["limits"].get("auth.login", 120))
    for attempt in range(1, MAX_ATTEMPTS + 1):
        bus.publish("sign_in_started", scope=instance.role, attempt=attempt)
        try:
            if await _attempt(instance, document, limit):
                bus.publish("sign_in_done", scope=instance.role, attempt=attempt)
                return {"signed_in": True, "attempts": attempt, "already": False}
            reason = "Nach der Anmeldung ist das Merkmal nicht erschienen"
        except EngineStop as error:
            reason = str(error)
        except SignInError:
            raise
        incident = await incidents.capture(
            instance, document, "anmeldung", reason, notes=f"Versuch {attempt}"
        )
        bus.publish("sign_in_failed", scope=instance.role, attempt=attempt,
                    reason=reason, incident=incident)

    raise SignInError(
        f"Die Anmeldung ist {MAX_ATTEMPTS} mal nicht gelungen. Die Anwendung hält an."
    )


async def ensure(instance: Any) -> Dict[str, Any]:
    """Check before every run, sign in if necessary (7.3)."""
    current = await state(instance)
    if current["signed_in"]:
        return {"signed_in": True, "attempts": 0, "already": True}
    if not current["known"]:
        raise SignInError(current["reason"])
    return await sign_in(instance)
