"""Author reputation tracking with SQLite storage."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from xfeed.config import CONFIG_DIR, ensure_config_dir, load_config

DB_FILE = CONFIG_DIR / "authors.db"


@dataclass
class AuthorStats:
    """Statistics for a tracked author."""

    handle: str
    display_name: str
    total_tweets_seen: int
    avg_score: float
    recent_avg_score: float  # Last 30 days
    last_seen: datetime
    first_seen: datetime
    trend: str  # "rising", "stable", "declining"
    is_trusted: bool

    def reputation_boost(self, config: dict | None = None) -> float:
        """Calculate reputation boost (0 to max configured boost)."""
        if config is None:
            config = load_config()

        min_samples = config.get("reputation_minimum_samples", 5)
        trusted_threshold = config.get("reputation_trusted_threshold", 7.5)
        boost_max = config.get("reputation_boost_max", 1.5)

        if self.total_tweets_seen < min_samples:
            return 0.0
        if not self.is_trusted:
            return 0.0

        # Scale boost based on how far above trusted threshold
        excess = self.avg_score - trusted_threshold
        return min(boost_max, max(0, excess * 0.5))


class AuthorDB:
    """SQLite database for author reputation tracking."""

    def __init__(self, db_path: Path | None = None):
        ensure_config_dir()
        self.db_path = db_path or DB_FILE
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS authors (
                    handle TEXT PRIMARY KEY,
                    display_name TEXT,
                    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tweet_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    author_handle TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    tweet_id TEXT,
                    FOREIGN KEY (author_handle) REFERENCES authors(handle)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_scores_author
                ON tweet_scores(author_handle)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_scores_date
                ON tweet_scores(scored_at)
            """)
            conn.commit()

    def record_tweet_score(
        self,
        author_handle: str,
        display_name: str,
        score: int,
        tweet_id: str | None = None,
    ) -> None:
        """Record a scored tweet for an author."""
        handle = author_handle.lower()
        with sqlite3.connect(self.db_path) as conn:
            # Upsert author
            conn.execute(
                """
                INSERT INTO authors (handle, display_name, last_seen)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(handle) DO UPDATE SET
                    display_name = excluded.display_name,
                    last_seen = CURRENT_TIMESTAMP
            """,
                (handle, display_name),
            )

            # Record score
            conn.execute(
                """
                INSERT INTO tweet_scores (author_handle, score, tweet_id)
                VALUES (?, ?, ?)
            """,
                (handle, score, tweet_id),
            )
            conn.commit()

    def get_author_stats(
        self, author_handle: str, config: dict | None = None
    ) -> Optional[AuthorStats]:
        """Get reputation statistics for an author.

        Uses "forgiving average" - ignores worst 20% of scores.
        Philosophy: "Up like a rock, down like a feather"
        - Good takes boost reputation quickly
        - Occasional bad takes don't tank trusted authors
        """
        if config is None:
            config = load_config()

        min_samples = config.get("reputation_minimum_samples", 5)
        trusted_threshold = config.get("reputation_trusted_threshold", 7.5)
        decay_days = 30

        handle = author_handle.lower()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get author info
            author = conn.execute(
                "SELECT * FROM authors WHERE handle = ?", (handle,)
            ).fetchone()
            if not author:
                return None

            # Get all scores for forgiving average calculation
            all_scores = conn.execute(
                """
                SELECT score FROM tweet_scores
                WHERE author_handle = ?
                ORDER BY score DESC
            """,
                (handle,),
            ).fetchall()

            total_count = len(all_scores)
            if total_count == 0:
                return None

            # Forgiving average: use top 80% of scores (ignore worst 20%)
            # This means 1 bad take out of 5 is forgiven, 2 out of 10, etc.
            keep_count = max(1, int(total_count * 0.8))
            top_scores = [row["score"] for row in all_scores[:keep_count]]
            avg_score = sum(top_scores) / len(top_scores)

            # Get recent stats (last 30 days) - also forgiving
            cutoff = (datetime.now() - timedelta(days=decay_days)).isoformat()
            recent_scores = conn.execute(
                """
                SELECT score FROM tweet_scores
                WHERE author_handle = ? AND scored_at > ?
                ORDER BY score DESC
            """,
                (handle, cutoff),
            ).fetchall()

            if recent_scores:
                recent_keep = max(1, int(len(recent_scores) * 0.8))
                recent_top = [row["score"] for row in recent_scores[:recent_keep]]
                recent_avg = sum(recent_top) / len(recent_top)
            else:
                recent_avg = avg_score

            # Calculate trend
            trend = self._calculate_trend(conn, handle)

            is_trusted = (
                total_count >= min_samples and avg_score >= trusted_threshold
            )

            return AuthorStats(
                handle=handle,
                display_name=author["display_name"],
                total_tweets_seen=total_count,
                avg_score=avg_score,
                recent_avg_score=recent_avg,
                last_seen=datetime.fromisoformat(author["last_seen"]),
                first_seen=datetime.fromisoformat(author["first_seen"]),
                trend=trend,
                is_trusted=is_trusted,
            )

    def _calculate_trend(self, conn: sqlite3.Connection, handle: str) -> str:
        """Calculate author's trend direction."""
        # Compare last 7 days to previous 7-14 days
        now = datetime.now()
        week_ago = (now - timedelta(days=7)).isoformat()
        two_weeks_ago = (now - timedelta(days=14)).isoformat()

        recent = conn.execute(
            """
            SELECT AVG(score) FROM tweet_scores
            WHERE author_handle = ? AND scored_at > ?
        """,
            (handle, week_ago),
        ).fetchone()[0]

        previous = conn.execute(
            """
            SELECT AVG(score) FROM tweet_scores
            WHERE author_handle = ? AND scored_at > ? AND scored_at <= ?
        """,
            (handle, two_weeks_ago, week_ago),
        ).fetchone()[0]

        if recent is None or previous is None:
            return "stable"

        diff = recent - previous
        if diff > 0.5:
            return "rising"
        elif diff < -0.5:
            return "declining"
        return "stable"

    def get_trusted_authors(
        self, limit: int = 50, config: dict | None = None
    ) -> list[AuthorStats]:
        """Get list of trusted authors sorted by reputation."""
        if config is None:
            config = load_config()

        min_samples = config.get("reputation_minimum_samples", 5)
        trusted_threshold = config.get("reputation_trusted_threshold", 7.5)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT a.handle
                FROM authors a
                JOIN tweet_scores s ON a.handle = s.author_handle
                GROUP BY a.handle
                HAVING COUNT(s.id) >= ? AND AVG(s.score) >= ?
                ORDER BY AVG(s.score) DESC
                LIMIT ?
            """,
                (min_samples, trusted_threshold, limit),
            ).fetchall()

            return [
                stats
                for row in rows
                if (stats := self.get_author_stats(row["handle"], config)) is not None
            ]

    def get_rising_authors(
        self, limit: int = 20, config: dict | None = None
    ) -> list[AuthorStats]:
        """Get authors with rising reputation scores."""
        if config is None:
            config = load_config()

        # Get all authors with at least 3 samples, then filter by trend
        with sqlite3.connect(self.db_path) as conn:
            handles = conn.execute(
                """
                SELECT DISTINCT author_handle FROM tweet_scores
                GROUP BY author_handle
                HAVING COUNT(*) >= 3
            """
            ).fetchall()

        all_stats = []
        for (handle,) in handles:
            stats = self.get_author_stats(handle, config)
            if stats and stats.trend == "rising":
                all_stats.append(stats)

        all_stats.sort(key=lambda x: x.recent_avg_score, reverse=True)
        return all_stats[:limit]

    def get_all_authors(
        self, limit: int = 100, config: dict | None = None
    ) -> list[AuthorStats]:
        """Get all tracked authors sorted by tweet count."""
        if config is None:
            config = load_config()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT a.handle
                FROM authors a
                JOIN tweet_scores s ON a.handle = s.author_handle
                GROUP BY a.handle
                ORDER BY COUNT(s.id) DESC
                LIMIT ?
            """,
                (limit,),
            ).fetchall()

            return [
                stats
                for row in rows
                if (stats := self.get_author_stats(row["handle"], config)) is not None
            ]

    def clear_all(self) -> int:
        """Clear all author data. Returns count of authors deleted."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
            conn.execute("DELETE FROM tweet_scores")
            conn.execute("DELETE FROM authors")
            conn.commit()
            return count

    def get_stats_summary(self, config: dict | None = None) -> dict:
        """Get summary statistics for the database."""
        if config is None:
            config = load_config()

        min_samples = config.get("reputation_minimum_samples", 5)
        trusted_threshold = config.get("reputation_trusted_threshold", 7.5)

        with sqlite3.connect(self.db_path) as conn:
            authors_count = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
            scores_count = conn.execute("SELECT COUNT(*) FROM tweet_scores").fetchone()[
                0
            ]

            # Count trusted authors
            trusted_result = conn.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT author_handle
                    FROM tweet_scores
                    GROUP BY author_handle
                    HAVING COUNT(*) >= ? AND AVG(score) >= ?
                )
            """,
                (min_samples, trusted_threshold),
            ).fetchone()

            return {
                "total_authors": authors_count,
                "total_scores": scores_count,
                "trusted_authors": trusted_result[0] if trusted_result else 0,
            }


# Module-level singleton for convenience
_db: AuthorDB | None = None


def get_author_db() -> AuthorDB:
    """Get the singleton AuthorDB instance."""
    global _db
    if _db is None:
        _db = AuthorDB()
    return _db
