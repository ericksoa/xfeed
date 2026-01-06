"""Tests for the author reputation tracking module."""

import pytest
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from xfeed.reputation import AuthorDB, AuthorStats


class TestAuthorDB:
    """Tests for AuthorDB database operations."""

    def setup_method(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_authors.db"
        self.db = AuthorDB(db_path=self.db_path)

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_db_initialization(self):
        """Database should be created with correct schema."""
        assert self.db_path.exists()
        # Should be able to record a score without error
        self.db.record_tweet_score("@test", "Test User", 8, "tweet123")

    def test_record_tweet_score(self):
        """Recording a score should create author and score entries."""
        self.db.record_tweet_score("@testuser", "Test User", 8, "tweet1")

        stats = self.db.get_author_stats("@testuser")
        assert stats is not None
        assert stats.handle == "@testuser"
        assert stats.display_name == "Test User"
        assert stats.total_tweets_seen == 1
        assert stats.avg_score == 8.0

    def test_handle_normalization(self):
        """Handles should be normalized to lowercase."""
        self.db.record_tweet_score("@TestUser", "Test User", 8, "tweet1")
        self.db.record_tweet_score("@TESTUSER", "Test User", 8, "tweet2")

        stats = self.db.get_author_stats("@testuser")
        assert stats is not None
        assert stats.total_tweets_seen == 2
        assert stats.avg_score == 8.0

    def test_multiple_scores_forgiving_average(self):
        """Forgiving average ignores worst 20% of scores."""
        # 5 scores: top 80% = 4 scores kept
        self.db.record_tweet_score("@user", "User", 9, "t1")
        self.db.record_tweet_score("@user", "User", 9, "t2")
        self.db.record_tweet_score("@user", "User", 8, "t3")
        self.db.record_tweet_score("@user", "User", 8, "t4")
        self.db.record_tweet_score("@user", "User", 2, "t5")  # Bad take - should be forgiven

        stats = self.db.get_author_stats("@user")
        assert stats.total_tweets_seen == 5
        # Forgiving avg: (9+9+8+8)/4 = 8.5, ignores the 2
        assert stats.avg_score == 8.5

    def test_nonexistent_author_returns_none(self):
        """Looking up unknown author should return None."""
        stats = self.db.get_author_stats("@nobody")
        assert stats is None

    def test_clear_all(self):
        """clear_all should remove all data."""
        self.db.record_tweet_score("@user1", "User 1", 8, "t1")
        self.db.record_tweet_score("@user2", "User 2", 7, "t2")

        count = self.db.clear_all()
        assert count == 2

        assert self.db.get_author_stats("@user1") is None
        assert self.db.get_author_stats("@user2") is None

    def test_stats_summary(self):
        """get_stats_summary should return correct counts."""
        self.db.record_tweet_score("@user1", "User 1", 8, "t1")
        self.db.record_tweet_score("@user1", "User 1", 9, "t2")
        self.db.record_tweet_score("@user2", "User 2", 5, "t3")

        summary = self.db.get_stats_summary()
        assert summary["total_authors"] == 2
        assert summary["total_scores"] == 3


class TestAuthorTrust:
    """Tests for trust status calculation."""

    def setup_method(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_authors.db"
        self.db = AuthorDB(db_path=self.db_path)
        self.config = {
            "reputation_minimum_samples": 5,
            "reputation_trusted_threshold": 7.5,
            "reputation_boost_max": 1.5,
        }

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_not_trusted_below_minimum_samples(self):
        """Author with fewer than minimum samples should not be trusted."""
        for i in range(4):  # Only 4 samples
            self.db.record_tweet_score("@user", "User", 9, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        assert stats.avg_score == 9.0
        assert not stats.is_trusted

    def test_trusted_with_enough_samples_and_high_score(self):
        """Author with enough samples and high avg should be trusted."""
        for i in range(5):
            self.db.record_tweet_score("@user", "User", 8, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        assert stats.is_trusted

    def test_not_trusted_with_low_average(self):
        """Author with enough samples but low avg should not be trusted."""
        for i in range(5):
            self.db.record_tweet_score("@user", "User", 5, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        assert not stats.is_trusted

    def test_get_trusted_authors(self):
        """get_trusted_authors should return only trusted authors."""
        # Trusted author
        for i in range(6):
            self.db.record_tweet_score("@trusted", "Trusted", 9, f"t{i}")

        # Not trusted (low score)
        for i in range(6):
            self.db.record_tweet_score("@lowscore", "Low", 5, f"l{i}")

        # Not trusted (few samples)
        for i in range(2):
            self.db.record_tweet_score("@fewsamples", "Few", 9, f"f{i}")

        trusted = self.db.get_trusted_authors(config=self.config)
        handles = [a.handle for a in trusted]
        assert "@trusted" in handles
        assert "@lowscore" not in handles
        assert "@fewsamples" not in handles


class TestReputationBoost:
    """Tests for reputation boost calculation."""

    def setup_method(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_authors.db"
        self.db = AuthorDB(db_path=self.db_path)
        self.config = {
            "reputation_minimum_samples": 5,
            "reputation_trusted_threshold": 7.5,
            "reputation_boost_max": 1.5,
        }

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_no_boost_below_minimum_samples(self):
        """No boost should be given before minimum samples."""
        for i in range(3):
            self.db.record_tweet_score("@user", "User", 10, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        assert stats.reputation_boost(self.config) == 0.0

    def test_no_boost_for_untrusted(self):
        """No boost for authors below trust threshold."""
        for i in range(5):
            self.db.record_tweet_score("@user", "User", 6, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        assert stats.reputation_boost(self.config) == 0.0

    def test_boost_scales_with_score(self):
        """Boost should scale based on score above threshold."""
        # 8.0 avg = 0.5 above threshold * 0.5 = 0.25 boost
        for i in range(5):
            self.db.record_tweet_score("@user", "User", 8, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        boost = stats.reputation_boost(self.config)
        assert boost == pytest.approx(0.25)

    def test_boost_capped_at_max(self):
        """Boost should not exceed configured maximum."""
        for i in range(5):
            self.db.record_tweet_score("@user", "User", 10, f"t{i}")

        stats = self.db.get_author_stats("@user", self.config)
        boost = stats.reputation_boost(self.config)
        assert boost <= 1.5


class TestTrendDetection:
    """Tests for author trend detection."""

    def setup_method(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_authors.db"
        self.db = AuthorDB(db_path=self.db_path)

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stable_trend_with_no_history(self):
        """New author should have stable trend."""
        self.db.record_tweet_score("@user", "User", 8, "t1")

        stats = self.db.get_author_stats("@user")
        assert stats.trend == "stable"

    def test_stable_trend_with_consistent_scores(self):
        """Consistent scores should result in stable trend."""
        for i in range(5):
            self.db.record_tweet_score("@user", "User", 8, f"t{i}")

        stats = self.db.get_author_stats("@user")
        assert stats.trend == "stable"


class TestGetAllAuthors:
    """Tests for get_all_authors method."""

    def setup_method(self):
        """Create a temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_authors.db"
        self.db = AuthorDB(db_path=self.db_path)

    def teardown_method(self):
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_all_authors_empty(self):
        """Empty database should return empty list."""
        authors = self.db.get_all_authors()
        assert authors == []

    def test_get_all_authors_sorted_by_tweet_count(self):
        """Authors should be sorted by tweet count descending."""
        self.db.record_tweet_score("@user1", "User 1", 8, "t1")
        for i in range(5):
            self.db.record_tweet_score("@user2", "User 2", 7, f"t2_{i}")
        for i in range(3):
            self.db.record_tweet_score("@user3", "User 3", 9, f"t3_{i}")

        authors = self.db.get_all_authors()
        assert len(authors) == 3
        assert authors[0].handle == "@user2"  # 5 tweets
        assert authors[1].handle == "@user3"  # 3 tweets
        assert authors[2].handle == "@user1"  # 1 tweet

    def test_get_all_authors_respects_limit(self):
        """Should respect limit parameter."""
        for i in range(10):
            self.db.record_tweet_score(f"@user{i}", f"User {i}", 8, f"t{i}")

        authors = self.db.get_all_authors(limit=5)
        assert len(authors) == 5
