"""A small SQLite cache so repeated runs don't re-scrape Steam and HLTB."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .session import CACHE_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    scope   TEXT NOT NULL,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    fetched INTEGER NOT NULL,
    PRIMARY KEY (scope, key)
);
"""


class Cache:
    def __init__(self, path: Path | None = None):
        self.path = path or (CACHE_DIR / "metadata.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.execute(SCHEMA)
        self._db.commit()

    def get(self, scope: str, key: Any, max_age: float | None = None) -> Any:
        row = self._db.execute(
            "SELECT value, fetched FROM entries WHERE scope = ? AND key = ?",
            (scope, str(key)),
        ).fetchone()
        if row is None:
            return None
        if max_age is not None and time.time() - row[1] > max_age:
            return None
        return json.loads(row[0])

    def set(self, scope: str, key: Any, value: Any) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO entries (scope, key, value, fetched) VALUES (?, ?, ?, ?)",
            (scope, str(key), json.dumps(value), int(time.time())),
        )
        self._db.commit()

    def clear(self, scope: str | None = None) -> int:
        cur = (
            self._db.execute("DELETE FROM entries WHERE scope = ?", (scope,))
            if scope
            else self._db.execute("DELETE FROM entries")
        )
        self._db.commit()
        return cur.rowcount

    def stats(self) -> list[tuple[str, int]]:
        return list(
            self._db.execute(
                "SELECT scope, COUNT(*) FROM entries GROUP BY scope ORDER BY scope"
            )
        )

    def close(self) -> None:
        self._db.close()
