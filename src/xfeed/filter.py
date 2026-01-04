"""LLM-based tweet filtering using Claude."""

import json
import random
import re
from datetime import datetime, timedelta

import anthropic

from xfeed.config import get_api_key, load_config, load_objectives
from xfeed.models import Tweet, FilteredTweet


# Track recently seen exploration authors to avoid repetition
_exploration_author_cache: dict[str, datetime] = {}


SYSTEM_PROMPT = """You are a tweet relevance filter. Your job is to score tweets based on how relevant they are to the user's interests and objectives.

Here are the user's interests and objectives:

{objectives}

For each tweet, you will:
1. Score its relevance from 0-10 (10 = highly relevant, 0 = completely irrelevant)
2. Provide a brief reason (1 sentence) explaining the score
3. Identify "superdunks" - quote tweets where someone provides an educational correction, insightful counter-argument, or exposes flawed reasoning in the quoted content
4. Assess reasoning quality and provide factor breakdown
5. Flag if the author appears to be unknown/new (not a well-known figure)

SCORING GUIDE:
- 8-10: Directly matches stated interests, high-value content, strong reasoning
- 5-7: Tangentially related, might be interesting
- 2-4: Weakly related, mostly noise
- 0-1: Completely irrelevant or matches exclusion criteria

REASONING QUALITY FACTORS (include in "factors" field):
Apply these as adjustments to the base topic relevance score:

BOOSTS (+1 to +2):
- "mechanism": Explains WHY/HOW something works, causal reasoning
- "tradeoffs": Analyzes pros/cons, acknowledges complexity
- "evidence": Links to papers, data, primary sources
- "uncertainty": Explicit hedging ("I think", "possibly", "early data")
- "assumptions": States what they're taking for granted

PENALTIES (-1 to -2):
- "vague": Claims without mechanism ("X will change everything")
- "unsourced": "Breaking" or factual claims without attribution
- "rhetorical": Excessive emotional framing designed to provoke
- "overconfident": Certain claims about uncertain topics

CONTRARIAN HANDLING:
- If a tweet presents a dissenting/contrarian view:
  - Check if it has strong reasoning (mechanism, evidence, hedging)
  - If rigor is high: include "dissent_rigorous" in factors (allows bonus)
  - If rigor is low: do NOT boost, treat as normal or penalize

SUPERDUNK DETECTION:
A "superdunk" is when someone quote-tweets a bad take and provides:
- A factual correction with evidence or expertise
- An insightful reframe that exposes flawed logic
- Educational context that the original poster missed
NOT a superdunk: simple mockery, "ratio" attempts, pile-ons.

EXCLUSION RULES:
If a tweet matches any "Exclude" criteria, score it 0-1 regardless of other content.
Exclusions apply even to unknown/new accounts - exploration is not a bypass for quality.

Respond with a JSON array in this exact format:
[
  {{"id": "tweet_id", "score": 8, "reason": "Brief explanation", "superdunk": false, "factors": ["mechanism", "evidence"], "is_unknown_author": false}},
  {{"id": "tweet_id", "score": 7, "reason": "Interesting contrarian take with citations", "superdunk": false, "factors": ["dissent_rigorous", "evidence", "uncertainty"], "is_unknown_author": true}},
  {{"id": "tweet_id", "score": 3, "reason": "Vague claim, no mechanism", "superdunk": false, "factors": ["vague", "overconfident"], "is_unknown_author": false}},
  ...
]"""


USER_PROMPT = """Score the relevance of these tweets:

{tweets_json}

Respond with only the JSON array, no other text."""


def format_tweets_for_prompt(tweets: list[Tweet]) -> str:
    """Format tweets as JSON for the prompt."""
    tweet_data = []
    for tweet in tweets:
        data = {
            "id": tweet.id,
            "author": f"{tweet.author} ({tweet.author_handle})",
            "content": tweet.content[:500],  # Truncate very long tweets
            "engagement": f"{tweet.likes} likes, {tweet.retweets} RTs",
        }

        # Include quoted tweet if present (for superdunk detection)
        if tweet.quoted_tweet:
            data["quoted_tweet"] = {
                "author": f"{tweet.quoted_tweet.author} ({tweet.quoted_tweet.author_handle})",
                "content": tweet.quoted_tweet.content[:400],
            }

        tweet_data.append(data)
    return json.dumps(tweet_data, indent=2)


def parse_filter_response(response_text: str) -> list[dict]:
    """Parse the JSON response from the model."""
    # Try to extract JSON from the response
    json_match = re.search(r'\[[\s\S]*\]', response_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: try parsing the whole response
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return []


def _is_author_in_cooldown(author_handle: str, cooldown_hours: int) -> bool:
    """Check if an exploration author is still in cooldown period."""
    global _exploration_author_cache
    if author_handle not in _exploration_author_cache:
        return False
    last_seen = _exploration_author_cache[author_handle]
    return datetime.now() - last_seen < timedelta(hours=cooldown_hours)


def _mark_author_seen(author_handle: str) -> None:
    """Mark an exploration author as recently seen."""
    global _exploration_author_cache
    _exploration_author_cache[author_handle] = datetime.now()
    # Clean up old entries
    cutoff = datetime.now() - timedelta(hours=48)
    _exploration_author_cache = {
        k: v for k, v in _exploration_author_cache.items() if v > cutoff
    }


def _build_explanation(factors: list[str], base_reason: str) -> str:
    """Build explanation string from factors and base reason."""
    if not factors:
        return base_reason

    boost_factors = []
    penalty_factors = []

    boost_names = {"mechanism", "tradeoffs", "evidence", "uncertainty", "assumptions", "dissent_rigorous"}
    penalty_names = {"vague", "unsourced", "rhetorical", "overconfident"}

    for f in factors:
        if f in boost_names:
            boost_factors.append(f"+{f}")
        elif f in penalty_names:
            penalty_factors.append(f"-{f}")

    factor_str = ", ".join(boost_factors + penalty_factors)
    if factor_str:
        return f"{base_reason} [{factor_str}]"
    return base_reason


def filter_tweets(
    tweets: list[Tweet],
    threshold: int | None = None,
    on_progress: callable = None,
    seed: int | None = None,
) -> list[FilteredTweet]:
    """
    Filter tweets using Claude Haiku to score relevance.

    Args:
        tweets: List of tweets to filter
        threshold: Minimum relevance score (0-10). Uses config default if None.
        on_progress: Callback function for progress updates
        seed: Random seed for deterministic exploration sampling

    Returns:
        List of FilteredTweet objects that meet the threshold
    """
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not configured. "
            "Add ANTHROPIC_API_KEY to .env file in the project directory."
        )

    config = load_config()
    if threshold is None:
        threshold = config.get("relevance_threshold", 7)

    batch_size = config.get("batch_size", 15)
    objectives = load_objectives()

    # Exploration settings
    exploration_rate = config.get("exploration_rate", 0.1)
    exploration_min_quality = config.get("exploration_min_quality", 7)
    exploration_cooldown = config.get("exploration_cooldown_hours", 24)

    # Contrarian settings
    dissent_min_rigor = config.get("dissent_min_rigor", 6)
    dissent_bonus_cap = config.get("dissent_bonus_cap", 2)

    client = anthropic.Anthropic(api_key=api_key)

    # Create lookup dict for tweets
    tweet_lookup = {t.id: t for t in tweets}

    # Collect all scored tweets (before threshold filtering)
    all_scored: list[dict] = []
    processed = 0

    # Process in batches
    for i in range(0, len(tweets), batch_size):
        batch = tweets[i:i + batch_size]

        tweets_json = format_tweets_for_prompt(batch)

        try:
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=2000,
                system=SYSTEM_PROMPT.format(objectives=objectives),
                messages=[
                    {"role": "user", "content": USER_PROMPT.format(tweets_json=tweets_json)}
                ]
            )

            response_text = response.content[0].text
            scores = parse_filter_response(response_text)

            for score_data in scores:
                tweet_id = score_data.get("id")
                if tweet_id in tweet_lookup:
                    all_scored.append({
                        "tweet": tweet_lookup[tweet_id],
                        "score": score_data.get("score", 0),
                        "reason": score_data.get("reason", ""),
                        "superdunk": score_data.get("superdunk", False),
                        "factors": score_data.get("factors", []),
                        "is_unknown_author": score_data.get("is_unknown_author", False),
                    })

        except Exception as e:
            # Log error but continue with other batches
            print(f"API error processing batch: {e}")

        processed += len(batch)
        if on_progress:
            on_progress(processed, len(tweets))

    # Process all scored tweets with enhanced scoring
    filtered_tweets: list[FilteredTweet] = []

    for scored in all_scored:
        factors = scored["factors"]
        score = scored["score"]

        # Build explanation with factors
        explanation = _build_explanation(factors, scored["reason"])

        # Check for rigorous dissent bonus
        has_dissent = "dissent_rigorous" in factors
        rigor_factors = {"mechanism", "evidence", "tradeoffs", "uncertainty", "assumptions"}
        rigor_count = len([f for f in factors if f in rigor_factors])

        # Apply dissent bonus if rigorous enough
        if has_dissent and rigor_count >= (dissent_min_rigor // 2):
            bonus = min(dissent_bonus_cap, rigor_count)
            score = min(10, score + bonus)
            explanation += f" [dissent+{bonus}]"

        # Mark exploration candidates (for visibility, not filtering)
        if scored["is_unknown_author"] and score >= exploration_min_quality:
            explanation = f"[NEW] {explanation}"

        # Apply threshold filter (same as before)
        if score >= threshold:
            filtered_tweets.append(FilteredTweet(
                tweet=scored["tweet"],
                relevance_score=score,
                reason=explanation,
                is_superdunk=scored["superdunk"],
            ))

    # Sort by relevance score (highest first)
    filtered_tweets.sort(key=lambda x: x.relevance_score, reverse=True)

    return filtered_tweets
