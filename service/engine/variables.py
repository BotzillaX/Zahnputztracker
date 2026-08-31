"""The variable space of one item run (decision 8).

Values read from a page during a run land here: the page text of a
detail view, a link that was read out, whatever an action stored. Both
browser instances read from the same space, because a value found in the
search instance is regularly needed in the session instance.

The space is deliberately not persistent. It is emptied when a new run
starts, so a value from a previous item can never leak into the next one.
"""

from __future__ import annotations

from typing import Any, Dict, List

MAX_VALUE_LENGTH = 20000
MAX_ENTRIES = 200
PREVIEW_LENGTH = 120


class Space:
    def __init__(self) -> None:
        self._values: Dict[str, str] = {}
        self.run: str = ""

    def open(self, run: str = "") -> None:
        """Begin a new run. Everything from the previous one is dropped."""
        self._values = {}
        self.run = run

    def set(self, name: str, value: Any) -> str:
        text = "" if value is None else str(value)
        if len(text) > MAX_VALUE_LENGTH:
            text = text[:MAX_VALUE_LENGTH]
        if name not in self._values and len(self._values) >= MAX_ENTRIES:
            raise KeyError(f"Der Variablenraum ist voll ({MAX_ENTRIES} Einträge)")
        self._values[name] = text
        return text

    def get(self, name: str) -> str:
        if name not in self._values:
            raise KeyError(f"Die Variable '{name}' ist nicht gesetzt")
        return self._values[name]

    def has(self, name: str) -> bool:
        return name in self._values

    def names(self) -> List[str]:
        return sorted(self._values)

    def report(self) -> Dict[str, Any]:
        """What the user interface may show: names and a short preview."""
        return {
            "run": self.run,
            "entries": [
                {
                    "name": name,
                    "length": len(value),
                    "preview": value[:PREVIEW_LENGTH],
                    "truncated": len(value) > PREVIEW_LENGTH,
                }
                for name, value in sorted(self._values.items())
            ],
        }


space = Space()
