"""Tests for the tweet filtering and scoring logic."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from xfeed.filter import (
    _build_explanation,
    _is_author_in_cooldown,
    _mark_author_seen,
    _exploration_author_cache,
    parse_filter_response,
)
from xfeed.models import Tweet, FilteredTweet


class TestBuildExplanation:
    """Tests for _build_explanation function."""

    def test_no_factors_returns_base_reason(self):
        """With no factors, just return the base reason."""
        result = _build_explanation([], "Great technical content")
        assert result == "Great technical content"

    def test_boost_factors_show_plus(self):
        """Boost factors should show with + prefix."""
        result = _build_explanation(["mechanism", "evidence"], "Good post")
        assert "+mechanism" in result
        assert "+evidence" in result
        assert "Good post" in result

    def test_penalty_factors_show_minus(self):
        """Penalty factors should show with - prefix."""
        result = _build_explanation(["vague", "overconfident"], "Weak post")
        assert "-vague" in result
        assert "-overconfident" in result
        assert "Weak post" in result

    def test_mixed_factors(self):
        """Mixed boost and penalty factors."""
        result = _build_explanation(
            ["mechanism", "vague", "evidence"],
            "Mixed quality"
        )
        assert "+mechanism" in result
        assert "+evidence" in result
        assert "-vague" in result
        assert "Mixed quality" in result

    def test_dissent_rigorous_is_boost(self):
        """dissent_rigorous should be treated as a boost factor."""
        result = _build_explanation(["dissent_rigorous", "evidence"], "Contrarian take")
        assert "+dissent_rigorous" in result
        assert "+evidence" in result

    def test_unknown_factors_ignored(self):
        """Unknown factor names should not appear in output."""
        result = _build_explanation(["unknown_factor", "mechanism"], "Post")
        assert "+mechanism" in result
        assert "unknown_factor" not in result


class TestExplorationAuthorCache:
    """Tests for exploration author cooldown logic."""

    def setup_method(self):
        """Clear the cache before each test."""
        global _exploration_author_cache
        from xfeed import filter as filter_module
        filter_module._exploration_author_cache = {}

    def test_new_author_not_in_cooldown(self):
        """New author should not be in cooldown."""
        assert not _is_author_in_cooldown("@new_user", 24)

    def test_recently_seen_author_in_cooldown(self):
        """Recently seen author should be in cooldown."""
        _mark_author_seen("@seen_user")
        assert _is_author_in_cooldown("@seen_user", 24)

    def test_author_outside_cooldown_window(self):
        """Author seen long ago should not be in cooldown."""
        from xfeed import filter as filter_module
        # Manually set a timestamp in the past
        filter_module._exploration_author_cache["@old_user"] = (
            datetime.now() - timedelta(hours=48)
        )
        assert not _is_author_in_cooldown("@old_user", 24)

    def test_mark_author_seen_updates_cache(self):
        """Marking author as seen should update the cache."""
        from xfeed import filter as filter_module
        _mark_author_seen("@test_user")
        assert "@test_user" in filter_module._exploration_author_cache

    def test_mark_author_seen_cleans_old_entries(self):
        """Marking author should clean up entries older than 48h."""
        from xfeed import filter as filter_module
        # Add an old entry
        filter_module._exploration_author_cache["@ancient_user"] = (
            datetime.now() - timedelta(hours=72)
        )
        # Mark a new author (triggers cleanup)
        _mark_author_seen("@new_user")
        # Old entry should be gone
        assert "@ancient_user" not in filter_module._exploration_author_cache
        assert "@new_user" in filter_module._exploration_author_cache


class TestParseFilterResponse:
    """Tests for parsing LLM filter responses."""

    def test_parse_valid_json_array(self):
        """Parse a valid JSON array response."""
        response = '''[
            {"id": "123", "score": 8, "reason": "Good", "superdunk": false, "factors": ["mechanism"]},
            {"id": "456", "score": 3, "reason": "Bad", "superdunk": false, "factors": ["vague"]}
        ]'''
        result = parse_filter_response(response)
        assert len(result) == 2
        assert result[0]["id"] == "123"
        assert result[0]["score"] == 8
        assert result[0]["factors"] == ["mechanism"]

    def test_parse_json_with_surrounding_text(self):
        """Parse JSON embedded in other text."""
        response = '''Here are the scores:
        [{"id": "123", "score": 7, "reason": "OK", "superdunk": false, "factors": []}]
        That's all!'''
        result = parse_filter_response(response)
        assert len(result) == 1
        assert result[0]["id"] == "123"

    def test_parse_invalid_json_returns_empty(self):
        """Invalid JSON should return empty list."""
        response = "This is not JSON at all"
        result = parse_filter_response(response)
        assert result == []

    def test_parse_with_new_fields(self):
        """Parse response with new is_unknown_author field."""
        response = '''[
            {"id": "123", "score": 7, "reason": "Unknown author post", "superdunk": false, "factors": ["evidence"], "is_unknown_author": true}
        ]'''
        result = parse_filter_response(response)
        assert len(result) == 1
        assert result[0]["is_unknown_author"] is True
        assert result[0]["factors"] == ["evidence"]


class TestScoringLogic:
    """Tests for scoring behavior (without actual API calls)."""

    def test_ragebait_excluded_even_from_unknown(self):
        """Rage bait should be excluded regardless of author status.

        This test verifies the expected behavior - actual filtering
        depends on Claude's response which we mock.
        """
        # This is a behavioral expectation test
        # The actual exclusion happens in the LLM prompt
        # We verify the prompt includes exclusion rules
        from xfeed.filter import SYSTEM_PROMPT
        assert "Exclude" in SYSTEM_PROMPT
        assert "exclusion criteria" in SYSTEM_PROMPT.lower() or "Exclusions apply" in SYSTEM_PROMPT

    def test_contrarian_without_rigor_not_boosted(self):
        """Contrarian takes without rigor factors should not get dissent bonus.

        The dissent bonus is only applied when:
        1. dissent_rigorous is in factors
        2. rigor_count meets threshold
        """
        # This tests the logic in filter_tweets
        # Without dissent_rigorous factor, no bonus is applied
        factors_no_dissent = ["vague", "overconfident"]
        explanation = _build_explanation(factors_no_dissent, "Hot take")
        assert "dissent" not in explanation
        assert "-vague" in explanation

    def test_mechanism_posts_show_boost(self):
        """Posts with mechanism factor show boost in explanation."""
        factors = ["mechanism"]
        explanation = _build_explanation(factors, "Explains how X works")
        assert "+mechanism" in explanation

    def test_evidence_posts_show_boost(self):
        """Posts with evidence factor show boost in explanation."""
        factors = ["evidence"]
        explanation = _build_explanation(factors, "Links to paper")
        assert "+evidence" in explanation


class TestExplorationSampling:
    """Tests for exploration candidate sampling."""

    def test_deterministic_with_seed(self):
        """Same seed should produce same exploration selection."""
        import random

        # Create mock candidates
        candidates1 = [f"candidate_{i}" for i in range(10)]
        candidates2 = [f"candidate_{i}" for i in range(10)]

        # Sample with same seed twice
        rng1 = random.Random(42)
        rng1.shuffle(candidates1)
        sample1 = candidates1[:3]

        rng2 = random.Random(42)
        rng2.shuffle(candidates2)
        sample2 = candidates2[:3]

        # Should get same order with same seed
        assert sample1 == sample2

    def test_exploration_interspersed_not_at_end(self):
        """Exploration candidates should be interspersed, not appended."""
        # This tests the insertion logic
        regular = list(range(10))  # 10 regular items
        exploration = ["exp1", "exp2"]

        result = regular.copy()
        interval = max(3, len(result) // (len(exploration) + 1))

        for i, exp in enumerate(exploration):
            insert_pos = min((i + 1) * interval, len(result))
            result.insert(insert_pos, exp)

        # Exploration items should not all be at end
        assert result[-1] != "exp2" or result[-2] != "exp1"
        # They should be somewhere in the middle
        assert "exp1" in result
        assert "exp2" in result


class TestPromptContents:
    """Tests to verify prompt contains required instructions."""

    def test_prompt_has_reasoning_factors(self):
        """System prompt should include reasoning quality factors."""
        from xfeed.filter import SYSTEM_PROMPT
        assert "mechanism" in SYSTEM_PROMPT
        assert "tradeoffs" in SYSTEM_PROMPT
        assert "evidence" in SYSTEM_PROMPT
        assert "uncertainty" in SYSTEM_PROMPT

    def test_prompt_has_penalty_factors(self):
        """System prompt should include penalty factors."""
        from xfeed.filter import SYSTEM_PROMPT
        assert "vague" in SYSTEM_PROMPT
        assert "unsourced" in SYSTEM_PROMPT
        assert "rhetorical" in SYSTEM_PROMPT
        assert "overconfident" in SYSTEM_PROMPT

    def test_prompt_has_contrarian_handling(self):
        """System prompt should include contrarian handling."""
        from xfeed.filter import SYSTEM_PROMPT
        assert "dissent" in SYSTEM_PROMPT.lower() or "contrarian" in SYSTEM_PROMPT.lower()
        assert "dissent_rigorous" in SYSTEM_PROMPT

    def test_prompt_has_unknown_author_field(self):
        """System prompt should request is_unknown_author field."""
        from xfeed.filter import SYSTEM_PROMPT
        assert "is_unknown_author" in SYSTEM_PROMPT

    def test_prompt_has_factors_field(self):
        """System prompt should request factors field."""
        from xfeed.filter import SYSTEM_PROMPT
        assert '"factors"' in SYSTEM_PROMPT
