"""Data models for XFeed."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class QuotedTweet:
    """Represents a quoted tweet embedded in another tweet."""

    author: str
    author_handle: str
    content: str


@dataclass
class Tweet:
    """Represents a tweet from the X timeline."""

    id: str
    author: str
    author_handle: str
    content: str
    timestamp: datetime
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    has_media: bool = False
    url: str = ""
    quoted_tweet: QuotedTweet | None = None  # For quote tweets

    @property
    def formatted_time(self) -> str:
        """Return human-readable time difference."""
        now = datetime.now()
        diff = now - self.timestamp

        if diff.days > 0:
            return f"{diff.days}d ago"
        elif diff.seconds >= 3600:
            return f"{diff.seconds // 3600}h ago"
        elif diff.seconds >= 60:
            return f"{diff.seconds // 60}m ago"
        else:
            return "just now"


@dataclass
class FilteredTweet:
    """A tweet with relevance scoring from the LLM filter."""

    tweet: Tweet
    relevance_score: int  # 0-10
    reason: str  # Why it's relevant
    is_superdunk: bool = False  # Quote tweet with educational correction/insight


@dataclass
class TopicVibe:
    """Represents a topic theme extracted from tweets."""

    topic: str  # e.g., "AI Safety Developments"
    vibe: str  # e.g., "Cautiously optimistic"
    emoji: str  # e.g., "🔥"
    description: str  # 1-sentence summary
    tweet_count: int  # How many tweets relate to this
