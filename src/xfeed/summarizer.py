"""LLM-based topic extraction and vibe analysis."""

import json
import re

import anthropic

from xfeed.config import get_api_key, load_objectives
from xfeed.models import FilteredTweet, TopicVibe


SYSTEM_PROMPT = """You are an expert at analyzing social media discussions to identify key themes and their overall sentiment.

Given a collection of tweets that have been filtered for relevance to a user's interests, identify the 2-3 main topics being discussed.

For each topic, provide:
1. **topic**: A short, descriptive name (3-5 words max)
2. **vibe**: The overall sentiment/tone in 1-2 words (e.g., "Excited", "Skeptical", "Cautiously optimistic", "Heated debate")
3. **emoji**: A single emoji that captures the vibe
4. **description**: A one-sentence summary of what's being discussed
5. **tweet_count**: How many of the provided tweets relate to this topic

The user's interests are:
{objectives}

Focus on topics that are genuinely distinct from each other. Don't create overlapping topics.

Respond with ONLY a JSON array in this exact format:
[
  {{"topic": "Topic Name", "vibe": "Sentiment", "emoji": "🔥", "description": "Brief description", "tweet_count": 5}},
  {{"topic": "Another Topic", "vibe": "Mood", "emoji": "🤔", "description": "Brief description", "tweet_count": 3}}
]"""


USER_PROMPT = """Analyze these {count} tweets and identify 2-3 main topics with their vibes:

{tweets_text}

Respond with only the JSON array, no other text."""


def format_tweets_for_vibe(tweets: list[FilteredTweet]) -> str:
    """Format filtered tweets for vibe analysis."""
    lines = []
    for i, ft in enumerate(tweets, 1):
        t = ft.tweet
        # Include the filter's reason as context
        lines.append(f"{i}. [{ft.relevance_score}/10] {t.author_handle}: {t.content[:300]}")
        lines.append(f"   Relevance: {ft.reason}")
        lines.append("")
    return "\n".join(lines)


def parse_vibe_response(response_text: str) -> list[dict]:
    """Parse the JSON response from the model."""
    # Try to extract JSON array from the response
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


def extract_vibe(tweets: list[FilteredTweet]) -> list[TopicVibe]:
    """
    Extract topic vibes from filtered tweets using Claude.

    Args:
        tweets: List of filtered tweets to analyze

    Returns:
        List of TopicVibe objects (2-3 topics)
    """
    if not tweets:
        return []

    api_key = get_api_key()
    if not api_key:
        return []

    objectives = load_objectives()
    client = anthropic.Anthropic(api_key=api_key)

    tweets_text = format_tweets_for_vibe(tweets)

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1000,
            system=SYSTEM_PROMPT.format(objectives=objectives),
            messages=[
                {"role": "user", "content": USER_PROMPT.format(
                    count=len(tweets),
                    tweets_text=tweets_text
                )}
            ]
        )

        response_text = response.content[0].text
        vibe_data = parse_vibe_response(response_text)

        vibes = []
        for item in vibe_data[:3]:  # Max 3 topics
            vibes.append(TopicVibe(
                topic=item.get("topic", "Unknown"),
                vibe=item.get("vibe", "Neutral"),
                emoji=item.get("emoji", "💭"),
                description=item.get("description", ""),
                tweet_count=item.get("tweet_count", 0),
            ))

        return vibes

    except Exception as e:
        # Silently fail - vibe is optional enhancement
        print(f"Vibe extraction error: {e}")
        return []
