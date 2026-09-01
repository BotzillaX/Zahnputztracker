"""Check the repository against the local word list (decision 22).

    .venv\\Scripts\\python.exe scripts\\tarnung.py            alles
    .venv\\Scripts\\python.exe scripts\\tarnung.py --staged   nur Vorgemerktes
    .venv\\Scripts\\python.exe scripts\\tarnung.py --nachricht <datei>

Acceptance criterion 12 asks that a full text search over the repository
finds nothing about the subject the program is used for. This check is
what makes that a fact instead of a hope, and it runs before a commit.

The words themselves are not in this file and never will be. They live
in privat\\wortliste.txt, which is not part of the repository. Without
that list nothing is checked, and the check says so and fails: a check
that quietly passes is worse than no check at all.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# A line that starts with this is a regular expression instead of a
# plain piece of text. Needed where a harmless technical word contains
# a suspicious one (\bwort\b then only matches the word itself).
PATTERN = "re:"

ROOT = Path(__file__).resolve().parent.parent
LIST = ROOT / "privat" / "wortliste.txt"

# Not looked at: what is not part of the repository anyway, and what is
# generated rather than written.
SKIP_PARTS = {
    ".git",
    "privat",
    "node_modules",
    "dist",
    "target",
    "build",
    "service_dist",
    "__pycache__",
    ".venv",
    "gen",
}
SKIP_SUFFIX = {
    ".png", ".jpg", ".jpeg", ".ico", ".gif", ".webp", ".wav", ".mp3",
    ".zip", ".exe", ".dll", ".pyd", ".pdb", ".lock",
}
MAX_BYTES = 2_000_000


def words() -> list[str]:
    if not LIST.is_file():
        return []
    found = []
    for line in LIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            found.append(line)
    return found


def skipped(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return True
    if path.suffix.lower() in SKIP_SUFFIX:
        return True
    return False


def tracked() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def staged() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def look(text: str, terms: list[str]) -> list[tuple[int, str, str]]:
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        for term in terms:
            if term.startswith(PATTERN):
                if not re.search(term[len(PATTERN):], low):
                    continue
            elif term not in low:
                continue
            hits.append((number, term, line.strip()[:120]))
    return hits


def check(paths: list[Path], terms: list[str]) -> int:
    found = 0
    for path in paths:
        if skipped(path.relative_to(ROOT) if path.is_absolute() else path):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, term, line in look(text, terms):
            found += 1
            name = path.relative_to(ROOT)
            print(f"{name}:{number}: '{term}' in: {line}")
    return found


def main(argv: list[str]) -> int:
    terms = words()
    if not terms:
        print(f"Die Wortliste fehlt oder ist leer: {LIST}")
        print("Ohne sie wird nichts geprueft. Bitte anlegen, ein Wort je Zeile.")
        return 1

    if "--nachricht" in argv:
        datei = Path(argv[argv.index("--nachricht") + 1])
        hits = look(datei.read_text(encoding="utf-8"), terms)
        for number, term, line in hits:
            print(f"Commit-Nachricht, Zeile {number}: '{term}' in: {line}")
        if hits:
            print(f"{len(hits)} Treffer in der Nachricht. Nichts wurde uebernommen.")
            return 1
        return 0

    paths = staged() if "--staged" in argv else tracked()
    found = check(paths, terms)
    if found:
        print(f"\n{found} Treffer in {len(paths)} geprueften Dateien. Nichts wurde uebernommen.")
        return 1
    print(f"Sauber: {len(paths)} Dateien gegen {len(terms)} Woerter geprueft.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
