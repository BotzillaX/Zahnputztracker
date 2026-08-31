"""The provider interface and the first provider (spec 9.1).

A provider is one function: it takes the finished prompt and returns the
text, or it raises. Adding a second provider means adding one function
and one line in PROVIDERS.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List

from ..storage import secrets

# Upper bound for the answer. A message that runs past this is not a
# message any more, it is a runaway.
MAX_TOKENS = 2000
API_VERSION = "2023-06-01"


class ComposerError(RuntimeError):
    """Raised when no usable text came back."""


def _post(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001 - the status alone still helps
            pass
        raise ComposerError(f"Der Anbieter antwortet mit {error.code}. {detail}") from error
    except urllib.error.URLError as error:
        raise ComposerError(f"Der Anbieter ist nicht erreichbar: {error.reason}") from error
    except TimeoutError as error:
        raise ComposerError("Der Anbieter hat sein Zeitlimit überschritten") from error
    except json.JSONDecodeError as error:
        raise ComposerError("Die Antwort des Anbieters ist unlesbar") from error


def _anthropic(prompt: str, settings: Dict[str, Any], timeout: float) -> str:
    key = secrets.get(secrets.COMPOSER_API_KEY)
    if not key:
        raise ComposerError("Im Anmeldeinformationsspeicher liegt kein API-Schlüssel")
    endpoint = str(settings.get("endpoint") or "").strip()
    model = str(settings.get("model") or "").strip()
    if not endpoint or not model:
        raise ComposerError("Endpunkt oder Modell fehlt in den Einstellungen")

    answer = _post(
        endpoint,
        {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        },
        {"x-api-key": key, "anthropic-version": API_VERSION},
        timeout,
    )
    parts: List[str] = [
        str(block.get("text", ""))
        for block in answer.get("content") or []
        if block.get("type") == "text"
    ]
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        raise ComposerError("Der Anbieter hat keinen Text geliefert")
    return text


PROVIDERS: Dict[str, Callable[[str, Dict[str, Any], float], str]] = {
    "anthropic": _anthropic,
}


def providers() -> List[str]:
    return sorted(PROVIDERS)


async def generate(prompt: str, settings: Dict[str, Any]) -> str:
    """Ask the configured provider. Blocking work runs off the loop."""
    name = str(settings.get("provider") or "").strip()
    provider = PROVIDERS.get(name)
    if provider is None:
        raise ComposerError(f"Der Anbieter '{name}' ist nicht angebunden")
    timeout = float(settings.get("timeout_s") or 120)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(provider, prompt, settings, timeout), timeout + 5
        )
    except asyncio.TimeoutError as error:
        raise ComposerError("Der Anbieter hat sein Zeitlimit überschritten") from error
