"""SQLite database: the leading record of processed items.

Two tables carry the safety rules of the specification:

* ``items`` holds one row per known key with its status. A key only
  counts as done once its status says so; ``pending_review`` explicitly
  does not count as known, so such an item is offered again.
* ``dispatch`` implements the protection against sending twice. A marker
  is written immediately before a send and confirmed afterwards. A marker
  without confirmation (crash, power loss) turns into an entry the user
  has to decide on. Nothing is ever re-sent automatically.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import paths

SCHEMA_VERSION = 1

# Status values, kept in one place so the user interface and the flow
# logic cannot drift apart.
STATUS_CONTACTED = "kontaktiert"
STATUS_UNCLEAR = "unklar"
STATUS_SKIPPED = "uebersprungen"
STATUS_ALREADY = "bereits_angefragt"
STATUS_FAILED = "fehlgeschlagen"
STATUS_PENDING_REVIEW = "wartet_auf_freigabe"
# Internal: the key has been seen but not processed yet. Never settled,
# so such an item is always picked up again.
STATUS_OPEN = "offen"

ALL_STATUS = (
    STATUS_OPEN,
    STATUS_CONTACTED,
    STATUS_UNCLEAR,
    STATUS_SKIPPED,
    STATUS_ALREADY,
    STATUS_FAILED,
    STATUS_PENDING_REVIEW,
)

# A key with one of these statuses is treated as already handled and is
# skipped on the next pass. Everything else is offered again.
SETTLED_STATUS = (STATUS_CONTACTED, STATUS_SKIPPED, STATUS_ALREADY, STATUS_UNCLEAR)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    key        TEXT PRIMARY KEY,
    url        TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    status     TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    message    TEXT NOT NULL DEFAULT '',
    incident   TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS items_status ON items (status);
CREATE INDEX IF NOT EXISTS items_updated ON items (updated_at);

CREATE TABLE IF NOT EXISTS dispatch (
    key          TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    confirmed_at TEXT,
    evidence     TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (key) REFERENCES items (key) ON DELETE CASCADE
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def database_path() -> Path:
    return paths.roaming_dir() / "data.sqlite"


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open the database and make sure the schema is present."""
    target = path or database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(_SCHEMA)
    connection.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    return connection


def see(connection: sqlite3.Connection, key: str, url: str = "", title: str = "") -> None:
    """Record that a key exists, without changing an established status."""
    stamp = now()
    connection.execute(
        "INSERT INTO items (key, url, title, status, first_seen, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET "
        "  url = CASE WHEN excluded.url <> '' THEN excluded.url ELSE items.url END, "
        "  title = CASE WHEN excluded.title <> '' THEN excluded.title ELSE items.title END",
        (key, url, title, STATUS_OPEN, stamp, stamp),
    )


def set_status(
    connection: sqlite3.Connection,
    key: str,
    status: str,
    *,
    reason: str = "",
    message: str = "",
    incident: str = "",
    url: str = "",
    title: str = "",
) -> None:
    if status not in ALL_STATUS:
        raise ValueError(f"unbekannter Status: {status}")
    see(connection, key, url=url, title=title)
    connection.execute(
        "UPDATE items SET status = ?, reason = ?, message = ?, incident = ?, updated_at = ? "
        "WHERE key = ?",
        (status, reason, message, incident, now(), key),
    )


def unknown_keys(connection: sqlite3.Connection, keys: Iterable[str]) -> List[str]:
    """Filter a list of keys down to those still needing work.

    Order is preserved. A key that is absent, or present but not settled,
    counts as needing work.
    """
    keys = list(keys)
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"SELECT key FROM items WHERE key IN ({placeholders}) "
        f"AND status IN ({','.join('?' for _ in SETTLED_STATUS)})",
        (*keys, *SETTLED_STATUS),
    ).fetchall()
    settled = {row["key"] for row in rows}
    return [key for key in keys if key not in settled]


def items(
    connection: sqlite3.Connection,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    if status:
        rows = connection.execute(
            "SELECT * FROM items WHERE status = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT * FROM items ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [dict(row) for row in rows]


def counts(connection: sqlite3.Connection) -> Dict[str, int]:
    rows = connection.execute("SELECT status, COUNT(*) AS n FROM items GROUP BY status").fetchall()
    result = {status: 0 for status in ALL_STATUS}
    for row in rows:
        result[row["status"]] = row["n"]
    return result


def mark_dispatch_started(connection: sqlite3.Connection, key: str, evidence: str = "") -> None:
    """Write the marker that a send is about to happen."""
    connection.execute(
        "INSERT INTO dispatch (key, started_at, confirmed_at, evidence) VALUES (?, ?, NULL, ?) "
        "ON CONFLICT (key) DO UPDATE SET started_at = excluded.started_at, "
        "confirmed_at = NULL, evidence = excluded.evidence",
        (key, now(), evidence),
    )


def mark_dispatch_confirmed(connection: sqlite3.Connection, key: str) -> None:
    connection.execute("UPDATE dispatch SET confirmed_at = ? WHERE key = ?", (now(), key))


def clear_dispatch(connection: sqlite3.Connection, key: str) -> None:
    """Drop a marker without claiming the send happened.

    Used when the user decides that an unconfirmed send is to be tried
    again: the entry goes back into the queue and must not carry a
    confirmation it never got.
    """
    connection.execute("DELETE FROM dispatch WHERE key = ?", (key,))


def open_dispatches(connection: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Sends that were started but never confirmed."""
    rows = connection.execute(
        "SELECT d.key, d.started_at, d.evidence, i.url, i.title, i.status "
        "FROM dispatch d LEFT JOIN items i ON i.key = d.key "
        "WHERE d.confirmed_at IS NULL ORDER BY d.started_at DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_open_dispatches(connection: sqlite3.Connection) -> List[str]:
    """Move unconfirmed sends into the 'unclear' list. Never re-sends."""
    keys = [row["key"] for row in open_dispatches(connection)]
    for key in keys:
        set_status(connection, key, STATUS_UNCLEAR, reason="Versand ohne Bestätigung")
    return keys
