"""Putting the prompt together (spec 9.2).

The prompt itself is written by the user in the settings. This file only
fills the placeholders. A placeholder that nobody can fill is an error
with a list of the names that do exist: a prompt that silently keeps the
braces would end up in a message someone reads.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

PATTERN = re.compile(r"\{\{([^{}]+)\}\}")

PLACEHOLDER_HELP = [
    ("{{seitentext}}", "Der sichtbare Text der geöffneten Seite"),
    ("{{adresse}}", "Die Adresse der geöffneten Seite"),
    ("{{titel}}", "Der Titel des Eintrags, soweit bekannt"),
    ("{{wert:Bezeichnung}}", "Ein persönlicher Wert aus den Einstellungen"),
]


class PromptError(ValueError):
    """Raised when the prompt cannot be filled as written."""


def _values(settings: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(entry.get("label", "")).strip(): str(entry.get("value", ""))
        for entry in settings.get("profile_values") or []
        if str(entry.get("label", "")).strip()
    }


def build(
    template: str,
    settings: Dict[str, Any],
    page_text: str,
    url: str = "",
    title: str = "",
) -> Tuple[str, List[str]]:
    """Fill the prompt. Returns the text and which names were used."""
    if not template.strip():
        raise PromptError("In den Einstellungen steht kein Prompt")

    personal = _values(settings)
    direct = {"seitentext": page_text, "adresse": url, "titel": title}
    used: List[str] = []

    def replace(match: "re.Match[str]") -> str:
        name = match.group(1).strip()
        if name in direct:
            used.append(name)
            return direct[name]
        if name.lower().startswith("wert:"):
            wanted = name.split(":", 1)[1].strip()
            if wanted not in personal:
                raise PromptError(
                    f"Der persönliche Wert '{wanted}' ist nicht hinterlegt. "
                    "Vorhanden: " + (", ".join(sorted(personal)) or "keiner")
                )
            used.append(name)
            return personal[wanted]
        raise PromptError(
            f"Der Platzhalter '{{{{{name}}}}}' ist unbekannt. "
            "Möglich sind: " + ", ".join(entry[0] for entry in PLACEHOLDER_HELP)
        )

    filled = PATTERN.sub(replace, template)
    if not filled.strip():
        raise PromptError("Der Prompt ist nach dem Einsetzen leer")
    return filled, used
