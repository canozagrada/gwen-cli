"""Every change `gwen watch` sees, kept in a local SQLite file.

The history is what makes priority 3 useful -- those changes are never sent,
but they are here when you need to look back -- and it doubles as the queue
for priority-2 changes held outside work hours.

Each row records how the change was routed:

- `notify`: sent when it happened (or would have been, in a dry run)
- `hold`: waiting for work hours; `released_at` is set once it has been sent
- `log`: recorded only
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

NOTIFY, HOLD, LOG = "notify", "hold", "log"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    provider    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    priority    INTEGER NOT NULL,
    route       TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    level       TEXT NOT NULL DEFAULT '',
    previous    TEXT NOT NULL DEFAULT '',
    targets     TEXT NOT NULL DEFAULT '[]',
    regions     TEXT NOT NULL DEFAULT '[]',
    text        TEXT NOT NULL DEFAULT '',
    released_at TEXT
);
CREATE INDEX IF NOT EXISTS events_at ON events (at);
CREATE INDEX IF NOT EXISTS events_held ON events (route, released_at);
"""



def _connect(path: pathlib.Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    return connection


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def record(
    path: pathlib.Path,
    routed: list[tuple[object, str]],
    at: datetime,
    release: list[int] = (),
) -> None:
    """Store each `(event, route)` and mark held rows *release* as sent, atomically."""
    with closing(_connect(path)) as connection, connection:
        connection.executemany(
            "INSERT INTO events (at, provider_key, provider, kind, priority, route, title,"
            " summary, url, level, previous, targets, regions, text)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    _iso(at),
                    event.key,
                    event.provider,
                    event.kind,
                    event.priority,
                    route,
                    event.title,
                    event.summary,
                    event.url,
                    event.level,
                    event.previous,
                    json.dumps(event.targets),
                    json.dumps(event.regions),
                    event.text,
                )
                for event, route in routed
            ],
        )
        if release:
            connection.executemany(
                "UPDATE events SET released_at = ? WHERE id = ?",
                [(_iso(at), row_id) for row_id in release],
            )


def held(path: pathlib.Path) -> list[tuple[int, dict]]:
    """Held changes not yet sent, oldest first, as `(row id, event fields)`."""
    if not path.exists():
        return []
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            "SELECT * FROM events WHERE route = ? AND released_at IS NULL ORDER BY id",
            (HOLD,),
        ).fetchall()
    return [(row["id"], _fields(row)) for row in rows]


def between(path: pathlib.Path, start: datetime, end: datetime) -> list[dict]:
    """Every recorded change from *start* to *end*, oldest first."""
    if not path.exists():
        return []
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            "SELECT * FROM events WHERE at >= ? AND at <= ? ORDER BY at, id",
            (_iso(start), _iso(end)),
        ).fetchall()
    return [_fields(row) for row in rows]


def latest(path: pathlib.Path, provider_key: str, kinds: tuple[str, ...]) -> list[dict]:
    """A provider's recorded changes of the given *kinds*, newest first."""
    if not path.exists():
        return []
    marks = ",".join("?" * len(kinds))
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            f"SELECT * FROM events WHERE provider_key = ? AND kind IN ({marks})"
            " ORDER BY at DESC, id DESC",
            (provider_key, *kinds),
        ).fetchall()
    return [_fields(row) for row in rows]


def _fields(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["key"] = data.pop("provider_key")
    data["targets"] = json.loads(data["targets"])
    data["regions"] = json.loads(data["regions"])
    data["at"] = datetime.fromisoformat(data["at"])
    return data
