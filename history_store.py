"""SQLite search history. The JSON file is read once, then left alone."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from logutil import log_event

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock TEXT NOT NULL,
    searched_at TEXT NOT NULL,
    count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS summary_cache (
    url TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    sentiment TEXT NOT NULL
);
"""


class HistoryStore:
    def __init__(self, db_path, json_path=None):
        self.db_path = str(db_path)
        self.json_path = str(json_path) if json_path else None
        self._lock = threading.Lock()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
        self._migrate_json_once()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def load(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT stock, searched_at, count FROM search_history ORDER BY id ASC"
            ).fetchall()
        return [
            {"stock": row["stock"], "timestamp": row["searched_at"], "count": row["count"]}
            for row in rows
        ]

    def append(self, stock, count):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO search_history (stock, searched_at, count) VALUES (?, ?, ?)",
                (stock, datetime.now().isoformat(), int(count)),
            )
            conn.execute(
                """
                DELETE FROM search_history
                WHERE id NOT IN (
                    SELECT id FROM search_history ORDER BY id DESC LIMIT 50
                )
                """
            )

    def clear(self):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM search_history")

    def get_summary(self, url):
        if not url:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT summary, sentiment FROM summary_cache WHERE url = ?",
                (url,),
            ).fetchone()
        if row is None:
            return None
        return {"summary": row["summary"], "sentiment": row["sentiment"]}

    def put_summary(self, url, summary, sentiment):
        if not url or not summary or not sentiment:
            return
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO summary_cache (url, summary, sentiment)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    summary = excluded.summary,
                    sentiment = excluded.sentiment
                """,
                (url, summary, sentiment),
            )

    def delete_stock(self, stock):
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM search_history WHERE UPPER(stock) = UPPER(?)",
                (stock,),
            )

    def _migrate_json_once(self):
        """Import search_history.json a single time. Later edits to the file are ignored."""
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT value FROM app_meta WHERE key = ?",
                ("migrated_search_history_json",),
            ).fetchone()
            if existing:
                return
            path = Path(self.json_path) if self.json_path else None
            if path is None or not path.is_file():
                return
            rows = []
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    rows = [
                        row for row in loaded
                        if isinstance(row, dict) and str(row.get("stock", "")).strip()
                    ]
            except (OSError, json.JSONDecodeError) as exc:
                log_event(
                    logging.WARNING,
                    "history_migrate",
                    outcome="skip",
                    error=exc.__class__.__name__,
                )
                conn.execute(
                    "INSERT INTO app_meta (key, value) VALUES (?, ?)",
                    ("migrated_search_history_json", "1"),
                )
                return
            already = conn.execute("SELECT COUNT(*) AS n FROM search_history").fetchone()["n"]
            if rows and already == 0:
                for row in rows[-50:]:
                    conn.execute(
                        "INSERT INTO search_history (stock, searched_at, count) VALUES (?, ?, ?)",
                        (
                            str(row.get("stock")),
                            str(row.get("timestamp") or datetime.now().isoformat()),
                            int(row.get("count") or 0),
                        ),
                    )
            conn.execute(
                "INSERT INTO app_meta (key, value) VALUES (?, ?)",
                ("migrated_search_history_json", "1"),
            )
            log_event(
                logging.INFO,
                "history_migrate",
                outcome="ok",
                count=len(rows) if already == 0 else 0,
            )
