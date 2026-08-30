"""Secrets in the Windows credential store.

Nothing here is ever written to a file, logged, or returned to the user
interface. The interface may set a value, delete it, and ask whether one
is present; it can never read one back.
"""

from __future__ import annotations

from typing import Dict, List

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "Zahnputztracker"

# Only these names may be stored. An open key space would let a mistake
# in the interface scatter arbitrary data through the credential store.
ACCOUNT_PASSWORD = "account-password"
COMPOSER_API_KEY = "composer-api-key"

KNOWN: Dict[str, str] = {
    ACCOUNT_PASSWORD: "Passwort des Zugangs",
    COMPOSER_API_KEY: "API-Schlüssel für die Textgenerierung",
}


class UnknownSecret(KeyError):
    pass


def _check(name: str) -> str:
    if name not in KNOWN:
        raise UnknownSecret(name)
    return name


def get(name: str) -> str | None:
    return keyring.get_password(SERVICE, _check(name))


def set_value(name: str, value: str) -> None:
    if not value:
        raise ValueError("leerer Wert")
    keyring.set_password(SERVICE, _check(name), value)


def delete(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, _check(name))
    except PasswordDeleteError:
        pass


def status() -> List[Dict[str, object]]:
    """Which secrets exist, without revealing any value."""
    result: List[Dict[str, object]] = []
    for name, label in KNOWN.items():
        value = keyring.get_password(SERVICE, name)
        result.append({"name": name, "label": label, "present": bool(value)})
    return result
