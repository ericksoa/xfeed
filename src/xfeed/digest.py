"""Tweet clustering and digest display for 'While You Were Away' feature."""

import json
import re
from datetime import datetime

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from xfeed.config import get_api_key, load_objectives
from xfeed.models import FilteredTweet, Digest, DigestTopic


CLUSTER_SYSTEM_PROMPT = """You are a tweet analyst. Your job is to cluster tweets into 3-5 meaningful topics that help someone catch up on what they missed.

The user cares about these topics:
{objectives}

For the given tweets, identify 3-5 distinct topics/themes and cluster the tweets accordingly.

GUIDELINES:
- Combine very small clusters (1-2 tweets) into a broader "Misc" or related topic
- Topic names should be specific and descriptive (e.g., "Claude 3.5 Release Discussion" not just "AI")
- Pick an emoji that captures the vibe of each topic
- Write a 1-sentence summary that tells someone what happened
- Order topics by importance/relevance to user's interests

Respond with JSON in this exact format:
{{
  "topics": [
    {{
      "name": "Topic Name Here",
      "emoji": "🤖",
      "summary": "One sentence describing what happened in this topic.",
      "tweet_ids": ["id1", "id2", "id3"]
    }}
  ]
}}"""


CLUSTER_USER_PROMPT = """Cluster these {count} tweets into 3-5 topics:

{tweets_json}

Respond with only JSON, no other text."""


def format_tweets_for_clustering(tweets: list[FilteredTweet]) -> str:
    """Format tweets as JSON for clustering prompt."""
    tweet_data = []
    for ft in tweets:
        tweet = ft.tweet
        data = {
            "id": tweet.id,
            "author": tweet.author_handle,
            "content": tweet.content[:400],
            "score": ft.relevance_score,
        }
        tweet_data.append(data)
    return json.dumps(tweet_data, indent=2)


def parse_cluster_response(response_text: str) -> dict:
    """Parse the JSON response from clustering."""
    # Try to extract JSON object from response
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: try parsing whole response
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"topics": []}


def cluster_tweets(
    tweets: list[FilteredTweet],
    time_window_hours: float,
) -> Digest:
    """
    Use Claude to cluster tweets into 3-5 topics.

    Args:
        tweets: List of filtered tweets to cluster
        time_window_hours: How many hours this digest covers

    Returns:
        Digest object with clustered topics
    """
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("Anthropic API key not configured.")

    # For very few tweets, skip clustering
    if len(tweets) < 5:
        # Create a single "Recent Activity" topic
        return Digest(
            topics=[
                DigestTopic(
                    name="Recent Activity",
                    emoji="📝",
                    summary=f"Just {len(tweets)} tweet(s) since you were away.",
                    tweet_ids=[ft.tweet.id for ft in tweets],
                )
            ],
            total_tweets=len(tweets),
            time_window_hours=time_window_hours,
        )

    objectives = load_objectives()
    tweets_json = format_tweets_for_clustering(tweets)

    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1500,
            system=CLUSTER_SYSTEM_PROMPT.format(objectives=objectives),
            messages=[
                {
                    "role": "user",
                    "content": CLUSTER_USER_PROMPT.format(
                        count=len(tweets),
                        tweets_json=tweets_json,
                    ),
                }
            ],
        )

        response_text = response.content[0].text
        result = parse_cluster_response(response_text)

        topics = []
        for topic_data in result.get("topics", []):
            topics.append(
                DigestTopic(
                    name=topic_data.get("name", "Unknown Topic"),
                    emoji=topic_data.get("emoji", "📌"),
                    summary=topic_data.get("summary", ""),
                    tweet_ids=topic_data.get("tweet_ids", []),
                )
            )

        if not topics:
            # Fallback if clustering failed
            topics = [
                DigestTopic(
                    name="Your Feed",
                    emoji="📰",
                    summary=f"{len(tweets)} tweets while you were away.",
                    tweet_ids=[ft.tweet.id for ft in tweets[:10]],
                )
            ]

        return Digest(
            topics=topics,
            total_tweets=len(tweets),
            time_window_hours=time_window_hours,
        )

    except Exception as e:
        # Return a simple fallback digest on error
        return Digest(
            topics=[
                DigestTopic(
                    name="Your Feed",
                    emoji="📰",
                    summary=f"Clustering failed: {e}",
                    tweet_ids=[ft.tweet.id for ft in tweets[:10]],
                )
            ],
            total_tweets=len(tweets),
            time_window_hours=time_window_hours,
        )


def render_digest(
    digest: Digest,
    tweets: list[FilteredTweet],
    console: Console,
    max_tweets_per_topic: int = 3,
) -> None:
    """
    Render digest to terminal using Rich panels.

    Args:
        digest: The clustered digest to render
        tweets: Original filtered tweets (for looking up content)
        console: Rich console for output
        max_tweets_per_topic: Max tweets to show per topic
    """
    # Create tweet lookup by ID
    tweet_lookup = {ft.tweet.id: ft for ft in tweets}

    # Header
    header = Text()
    header.append("━" * 55 + "\n", style="cyan dim")
    header.append("  WHILE YOU WERE AWAY ", style="bold cyan")
    header.append(f"(last {digest.time_window_str})\n", style="cyan dim")
    header.append(
        f"  {digest.total_tweets} relevant tweets in {len(digest.topics)} topics\n",
        style="dim",
    )
    header.append("━" * 55, style="cyan dim")
    console.print(header)
    console.print()

    # Render each topic
    for topic in digest.topics:
        # Get tweets for this topic
        topic_tweets = []
        for tweet_id in topic.tweet_ids:
            if tweet_id in tweet_lookup:
                topic_tweets.append(tweet_lookup[tweet_id])

        # Sort by score descending
        topic_tweets.sort(key=lambda x: x.relevance_score, reverse=True)

        # Build panel content
        content_lines = []

        # Summary line
        content_lines.append(f"[italic]{topic.summary}[/italic]")
        content_lines.append("")

        # Top tweets
        for ft in topic_tweets[:max_tweets_per_topic]:
            tweet = ft.tweet
            score = round(ft.relevance_score)

            # Score color
            if score >= 9:
                score_style = "green bold"
            elif score >= 7:
                score_style = "yellow"
            else:
                score_style = "white dim"

            # Truncate content
            content = tweet.content.replace("\n", " ")
            if len(content) > 70:
                content = content[:67] + "..."

            content_lines.append(
                f"[{score_style}][{score}][/{score_style}] "
                f"[cyan]{tweet.author_handle}[/cyan]: {content}"
            )

        # Show how many more if there are more
        remaining = len(topic_tweets) - max_tweets_per_topic
        if remaining > 0:
            content_lines.append(f"[dim]  +{remaining} more tweets[/dim]")

        panel_content = "\n".join(content_lines)

        # Topic title with emoji
        title = f"{topic.emoji} {topic.name}"

        console.print(
            Panel(
                panel_content,
                title=title,
                title_align="left",
                border_style="blue",
                padding=(0, 1),
            )
        )
        console.print()

    # Footer
    footer = Text()
    footer.append("━" * 55, style="cyan dim")
    console.print(footer)
