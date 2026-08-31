"""Page catalogue, first stage (plan, decision 13).

Every time a view is shown, its structural signature is computed. A
signature that has never been seen is kept with a copy of the page, a
screenshot, the address, the time and the action that led there. A known
signature only raises a counter.

The point is to know offline which views exist at all, when a new one
appeared and how it was reached. The map view over this material comes
later; the material has to be collected from the first day.

Everything lives in %APPDATA%, never in the repository.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..api.events import bus
from ..storage import paths

# How many different arrivals are remembered per view. Enough to see the
# ways in, small enough to stay readable.
MAX_ARRIVALS = 20


def root() -> Path:
    return paths.roaming_dir() / "atlas"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(signature: str) -> str:
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def _view_dir(scope: str, digest: str) -> Path:
    return root() / scope / digest


def _write_json(target: Path, data: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
    os.replace(temporary, target)


async def capture(page: Any, scope: str, trigger: str = "Navigation") -> Optional[Dict[str, Any]]:
    """Record the view currently shown. Returns its record, or None.

    Never raises: the catalogue is an observer, and an observer that can
    stop the run is worse than no observer.
    """
    try:
        signature = await page.evaluate("() => window.__ztOverlay.signature()")
    except Exception:  # noqa: BLE001 - the page may be navigating right now
        return None
    if not signature:
        return None

    digest = _digest(signature)
    folder = _view_dir(scope, digest)
    meta_file = folder / "meta.json"
    url = ""
    try:
        url = page.url
    except Exception:  # noqa: BLE001
        pass

    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        meta["count"] = int(meta.get("count") or 0) + 1
        meta["last_seen"] = _now()
        arrivals = meta.get("arrivals") or []
        if trigger not in arrivals:
            arrivals.append(trigger)
        meta["arrivals"] = arrivals[-MAX_ARRIVALS:]
        _write_json(meta_file, meta)
        bus.publish("view_seen", scope=scope, view=digest, count=meta["count"])
        return meta

    folder.mkdir(parents=True, exist_ok=True)
    try:
        (folder / "signature.txt").write_text(signature, encoding="utf-8")
        html = await page.evaluate("() => window.__ztOverlay.snapshot()")
        (folder / "snapshot.html").write_text(html, encoding="utf-8")
        # The overlay is never part of saved material (spec 2.5).
        await page.evaluate("() => window.__ztOverlay.hide()")
        try:
            await page.screenshot(path=str(folder / "screenshot.png"))
        finally:
            await page.evaluate("() => window.__ztOverlay.show()")
    except Exception as error:  # noqa: BLE001 - a partial record is still useful
        bus.publish("view_note", scope=scope, view=digest, message=str(error))

    meta = {
        "view": digest,
        "scope": scope,
        "url": url,
        "first_seen": _now(),
        "last_seen": _now(),
        "count": 1,
        "arrivals": [trigger],
        "elements": len(signature.splitlines()),
    }
    _write_json(meta_file, meta)
    bus.publish("view_new", scope=scope, view=digest, url=url, trigger=trigger)
    return meta


def views(scope: Optional[str] = None) -> List[Dict[str, Any]]:
    """All known views, newest first."""
    found: List[Dict[str, Any]] = []
    scopes = [scope] if scope else [entry.name for entry in root().glob("*") if entry.is_dir()]
    for name in scopes:
        folder = root() / name
        if not folder.is_dir():
            continue
        for view in folder.iterdir():
            meta_file = view / "meta.json"
            if not meta_file.is_file():
                continue
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            meta["has_snapshot"] = (view / "snapshot.html").is_file()
            meta["has_screenshot"] = (view / "screenshot.png").is_file()
            meta["path"] = str(view)
            found.append(meta)
    found.sort(key=lambda entry: str(entry.get("first_seen") or ""), reverse=True)
    return found


def snapshot_file(scope: str, digest: str) -> Path:
    target = _view_dir(scope, digest) / "snapshot.html"
    if not target.is_file():
        raise FileNotFoundError("Zu dieser Ansicht ist keine Kopie gespeichert")
    return target


def screenshot_file(scope: str, digest: str) -> Path:
    target = _view_dir(scope, digest) / "screenshot.png"
    if not target.is_file():
        raise FileNotFoundError("Zu dieser Ansicht ist kein Bild gespeichert")
    return target


def forget(scope: str, digest: str) -> None:
    """Remove one view from the catalogue."""
    folder = _view_dir(scope, digest)
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        try:
            entry.unlink()
        except OSError:
            pass
    try:
        folder.rmdir()
    except OSError:
        pass
