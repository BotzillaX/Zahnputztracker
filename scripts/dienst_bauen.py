"""Package the background service into one folder (phase 9).

    .venv\\Scripts\\python.exe scripts\\dienst_bauen.py

The result is service_dist\\service\\service.exe with everything beside
it. The core expects exactly that path and puts the whole folder into
the installer as an accompanying resource.

Two things that are easy to get wrong and expensive to notice late:

* The program must keep a console channel. The core hands the token over
  standard input and reads the answer from standard output. A windowed
  build has neither, and the handshake would fail with no message at all.
* The overlay is a text file next to its module, not code. It has to be
  carried along explicitly, or the selection mode is missing in the
  packaged program while everything else looks fine.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "service_dist"
KEEP = OUT / "service" / "LIESMICH.txt"

# Files that belong to a module but are not code. Source, then the
# folder inside the package.
DATA = [
    ("service/picker/overlay/overlay.js", "service/picker/overlay"),
]

# Packages whose parts are found at runtime rather than by import, so
# the analysis cannot see them.
COLLECT = ["camoufox", "playwright", "keyring", "uvicorn"]

HIDDEN = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "keyring.backends.Windows",
]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller fehlt. Zuerst: .venv\\Scripts\\pip.exe install pyinstaller")
        return 1

    keep = KEEP.read_text(encoding="utf-8") if KEEP.is_file() else ""
    target = OUT / "service"
    if target.exists():
        shutil.rmtree(target)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "service",
        # One folder, and a console channel: see the note above.
        "--onedir",
        "--console",
        "--distpath",
        str(OUT),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
        "--paths",
        str(ROOT),
    ]
    for source, inside in DATA:
        command += ["--add-data", f"{ROOT / source}{';' if sys.platform == 'win32' else ':'}{inside}"]
    for package in COLLECT:
        command += ["--collect-all", package]
    for module in HIDDEN:
        command += ["--hidden-import", module]
    command.append(str(ROOT / "scripts" / "dienst_start.py"))

    print(" ".join(command))
    result = subprocess.run(command, cwd=str(ROOT))
    if result.returncode != 0:
        return result.returncode

    program = target / "service.exe"
    if not program.is_file():
        print(f"Erwartet wurde {program}, gebaut wurde das nicht.")
        return 1
    if keep:
        KEEP.write_text(keep, encoding="utf-8")

    # Prove that the overlay really travelled along. Without it the
    # packaged program starts and the selection mode is simply gone.
    overlay = list(target.rglob("overlay.js"))
    if not overlay:
        print("Das Overlay fehlt im Ergebnis.")
        return 1

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"Fertig: {program} ({round(size / 1048576)} MB im Ordner)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
