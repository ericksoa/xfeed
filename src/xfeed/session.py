"""Session state tracking with SQLite storage."""

import sqlite3
from datetime import datetime
from pathlib import Path

from xfeed.config import CONFIG_DIR, ensure_config_dir

DB_FILE = CONFIG_DIR / "authors.db"


class SessionDB:
    """SQLite storage for session state (uses existing authors.db)."""

    def __init__(self, db_path: Path | None = None):
        ensure_config_dir()
        self.db_path = db_path or DB_FILE
        self._init_db()

    def _init_db(self) -> None:
        """Initialize session_state table if needed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_last_seen(self) -> datetime | None:
        """Get timestamp of last digest view."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value FROM session_state WHERE key = 'last_seen_at'"
            ).fetchone()
            if row and row[0]:
                return datetime.fromisoformat(row[0])
            return None

    def set_last_seen(self, timestamp: datetime | None = None) -> None:
        """Set last seen timestamp (defaults to now)."""
        if timestamp is None:
            timestamp = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO session_state (key, value, updated_at)
                VALUES ('last_seen_at', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (timestamp.isoformat(),),
            )
            conn.commit()

    def get_last_seen_hours_ago(self) -> float | None:
        """Get hours since last digest view, or None if never viewed."""
        last_seen = self.get_last_seen()
        if last_seen is None:
            return None
        diff = datetime.now() - last_seen
        return diff.total_seconds() / 3600


# Module-level singleton
_session_db: SessionDB | None = None


def get_session_db() -> SessionDB:
    """Get the singleton SessionDB instance."""
    global _session_db
    if _session_db is None:
        _session_db = SessionDB()
    return _session_db
