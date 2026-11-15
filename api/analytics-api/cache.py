"""SQLite-backed TTL cache for the Gemini advisory, so repeat projections don't re-call the API.

The analytics-api also stores this in `NASLOP_SQLITE_PATH` (mounted to a Docker volume), so cached
advisory responses survive container restarts.
"""

import json
import sqlite3
import time
from pathlib import Path

from projection_api.config import SQLITE_PATH

ADVISORY_TTL = 7 * 24 * 3600  # 7 days


def _db():
    path = Path(SQLITE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS gemini_cache "
        "(key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)"
    )
    conn.execute("DELETE FROM gemini_cache WHERE expires < ?", (time.time(),))
    conn.commit()
    return conn


def cache_get(key: str):
    try:
        conn = _db()
        row = conn.execute("SELECT expires, value FROM gemini_cache WHERE key = ?", (key,)).fetchone()
        conn.close()
        if row and row[0] > time.time():
            return json.loads(row[1])
    except Exception:  # noqa: BLE001 — a broken cache must never break a request
        pass
    return None


def cache_set(key: str, value, ttl: int = ADVISORY_TTL):
    try:
        conn = _db()
        conn.execute(
            "INSERT OR REPLACE INTO gemini_cache (key, expires, value) VALUES (?, ?, ?)",
            (key, time.time() + ttl, json.dumps(value)),
        )
        conn.commit()
        conn.close()
    except Exception:  # noqa: BLE001
        pass
