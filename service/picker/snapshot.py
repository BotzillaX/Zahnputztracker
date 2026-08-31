"""Picking on a saved copy of a page (spec 2.9, decision 12).

A correction must be possible without reproducing the situation live.
The saved copy is opened locally, with two guarantees:

  * no script of the copied page runs (scripts are removed beforehand)
  * nothing is loaded from the network (every request is refused)

The copy therefore looks unstyled. That is intended: what matters here
is the structure, not the appearance.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from ..storage import paths

_SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_BARE_SCRIPT = re.compile(r"<script\b[^>]*/?>", re.IGNORECASE)
_HANDLER = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE)
_JS_HREF = re.compile(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", re.IGNORECASE)


def defuse(html: str) -> str:
    """Remove everything in the copy that could execute."""
    html = _SCRIPT.sub("", html)
    html = _BARE_SCRIPT.sub("", html)
    html = _HANDLER.sub("", html)
    html = _JS_HREF.sub(r'\1="#"', html)
    return html


def staging_file() -> Path:
    return paths.local_dir() / "traces" / "snapshot-view.html"


def prepare(source: Path) -> Path:
    """Write the defused copy next to the temporary files."""
    html = Path(source).read_text(encoding="utf-8", errors="replace")
    target = staging_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(defuse(html), encoding="utf-8")
    return target


async def open_on(page: Any, source: Path, timeout_s: float = 30.0) -> Dict[str, Any]:
    """Show the saved copy in a browser instance, cut off from the network."""
    target = prepare(source)
    url = target.as_uri()

    async def refuse(route: Any) -> None:
        if route.request.url == url:
            await route.continue_()
        else:
            await route.abort()

    await page.unroute("**/*")
    await page.route("**/*", refuse)
    await page.goto(url, timeout=timeout_s * 1000, wait_until="domcontentloaded")
    return {"url": url, "file": str(target)}


async def release(page: Any) -> None:
    """Let the instance reach the network again."""
    await page.unroute("**/*")
