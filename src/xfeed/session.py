"""Session state tracking with SQLite storage."""

import json
import pickle
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from xfeed.config import CONFIG_DIR, ensure_config_dir

DB_FILE = CONFIG_DIR / "authors.db"
CACHE_FILE = CONFIG_DIR / "tweet_cache.pkl"


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


# Tweet cache for faster startup during development
def save_tweet_cache(
    tweets: list,
    vibes: list | None = None,
    engagement_stats: Any | None = None,
    my_handle: str | None = None,
) -> None:
    """
    Save tweets and related data to cache for quick reload.

    Args:
        tweets: List of FilteredTweet objects
        vibes: List of TopicVibe objects (optional)
        engagement_stats: MyEngagementStats object (optional)
        my_handle: User's Twitter handle (optional)
    """
    ensure_config_dir()
    cache_data = {
        "tweets": tweets,
        "vibes": vibes,
        "engagement_stats": engagement_stats,
        "my_handle": my_handle,
        "cached_at": datetime.now().isoformat(),
    }
    try:
        with open(CACHE_FILE, "wb") as f:
            pickle.dump(cache_data, f)
    except Exception:
        pass  # Silently fail - cache is optional


def load_tweet_cache() -> dict | None:
    """
    Load tweets from cache if available.

    Returns:
        Dict with keys: tweets, vibes, engagement_stats, my_handle, cached_at
        Or None if cache doesn't exist or is invalid
    """
    if not CACHE_FILE.exists():
        return None

    try:
        with open(CACHE_FILE, "rb") as f:
            cache_data = pickle.load(f)

        # Validate cache has required data
        if not cache_data.get("tweets"):
            return None

        return cache_data
    except Exception:
        return None


def get_cache_age_minutes() -> float | None:
    """Get age of cache in minutes, or None if no cache."""
    cache = load_tweet_cache()
    if not cache:
        return None

    try:
        cached_at = datetime.fromisoformat(cache["cached_at"])
        age = datetime.now() - cached_at
        return age.total_seconds() / 60
    except Exception:
        return None


def clear_tweet_cache() -> None:
    """Delete the tweet cache file."""
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
    except Exception:
        pass
