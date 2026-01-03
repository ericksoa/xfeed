"""LLM-based tweet filtering using Claude."""

import json
import re

import anthropic

from xfeed.config import get_api_key, load_config, load_objectives
from xfeed.models import Tweet, FilteredTweet


SYSTEM_PROMPT = """You are a tweet relevance filter. Your job is to score tweets based on how relevant they are to the user's interests and objectives.

Here are the user's interests and objectives:

{objectives}

For each tweet, you will:
1. Score its relevance from 0-10 (10 = highly relevant, 0 = completely irrelevant)
2. Provide a brief reason (1 sentence) explaining the score
3. Identify "superdunks" - quote tweets where someone provides an educational correction, insightful counter-argument, or exposes flawed reasoning in the quoted content

Be strict in your scoring:
- 8-10: Directly matches stated interests, high-value content
- 5-7: Tangentially related, might be interesting
- 2-4: Weakly related, mostly noise
- 0-1: Completely irrelevant or matches exclusion criteria

SUPERDUNK DETECTION:
A "superdunk" is when someone quote-tweets a bad take and provides:
- A factual correction with evidence or expertise
- An insightful reframe that exposes flawed logic
- Educational context that the original poster missed
- A genuinely clever observation that teaches something

NOT a superdunk: simple mockery, "ratio" attempts, pile-ons, hot takes responding to hot takes.
The VALUE is in the reply/quote being genuinely educational, not just "winning."

If a tweet matches any "Exclude" criteria, score it 0-1 regardless of other content.

Respond with a JSON array in this exact format:
[
  {{"id": "tweet_id", "score": 8, "reason": "Brief explanation", "superdunk": false}},
  {{"id": "tweet_id", "score": 9, "reason": "Excellent correction of a common misconception", "superdunk": true}},
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


def filter_tweets(
    tweets: list[Tweet],
    threshold: int | None = None,
    on_progress: callable = None,
) -> list[FilteredTweet]:
    """
    Filter tweets using Claude Haiku to score relevance.

    Args:
        tweets: List of tweets to filter
        threshold: Minimum relevance score (0-10). Uses config default if None.
        on_progress: Callback function for progress updates

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

    client = anthropic.Anthropic(api_key=api_key)

    # Create lookup dict for tweets
    tweet_lookup = {t.id: t for t in tweets}

    filtered_tweets: list[FilteredTweet] = []
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
                score = score_data.get("score", 0)
                reason = score_data.get("reason", "")
                is_superdunk = score_data.get("superdunk", False)

                if tweet_id in tweet_lookup and score >= threshold:
                    filtered_tweets.append(FilteredTweet(
                        tweet=tweet_lookup[tweet_id],
                        relevance_score=score,
                        reason=reason,
                        is_superdunk=is_superdunk,
                    ))

        except Exception as e:
            # Log error but continue with other batches
            print(f"API error processing batch: {e}")

        processed += len(batch)
        if on_progress:
            on_progress(processed, len(tweets))

    # Sort by relevance score (highest first)
    filtered_tweets.sort(key=lambda x: x.relevance_score, reverse=True)

    return filtered_tweets
