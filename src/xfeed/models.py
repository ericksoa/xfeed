"""Data models for XFeed."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class NotificationType(Enum):
    """Types of notifications from X."""
    LIKE = "like"
    RETWEET = "retweet"
    REPLY = "reply"
    QUOTE = "quote"
    FOLLOW = "follow"
    MENTION = "mention"
    UNKNOWN = "unknown"


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
    # Engagement tracking
    is_by_me: bool = False  # True if I authored this tweet
    is_liked_by_me: bool = False  # True if I liked this tweet
    is_retweeted_by_me: bool = False  # True if I retweeted this tweet
    # Thread context
    is_reply: bool = False  # True if this tweet is a reply to another

    @property
    def has_thread_context(self) -> bool:
        """True if pressing [t] would show useful thread context."""
        return self.is_reply or self.replies > 0

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
class LinkSummary:
    """Summary of a linked article."""

    url: str
    title: str
    summary: str  # 2-sentence summary


@dataclass
class FilteredTweet:
    """A tweet with relevance scoring from the LLM filter."""

    tweet: Tweet
    relevance_score: int  # 0-10
    reason: str  # Why it's relevant
    is_superdunk: bool = False  # Quote tweet with educational correction/insight
    link_summaries: list[LinkSummary] = field(default_factory=list)  # Expanded links


@dataclass
class ThreadContext:
    """Thread context for a selected tweet."""

    original_tweet: Tweet  # The tweet the user selected
    parent_tweets: list[Tweet] = field(default_factory=list)  # Context above (oldest first)
    reply_tweets: list[Tweet] = field(default_factory=list)  # Replies below (oldest first)

    @property
    def total_count(self) -> int:
        """Total tweets in thread."""
        return len(self.parent_tweets) + 1 + len(self.reply_tweets)

    @property
    def all_tweets(self) -> list[Tweet]:
        """All tweets in chronological order."""
        return self.parent_tweets + [self.original_tweet] + self.reply_tweets


@dataclass
class TopicVibe:
    """Represents a topic theme extracted from tweets."""

    topic: str  # e.g., "AI Safety Developments"
    vibe: str  # e.g., "Cautiously optimistic"
    emoji: str  # e.g., "🔥"
    description: str  # 1-sentence summary
    tweet_count: int  # How many tweets relate to this


@dataclass
class Notification:
    """Represents a notification from the notifications page."""

    type: NotificationType
    actor_handle: str  # @user who performed the action
    actor_name: str  # Display name
    timestamp: datetime
    additional_actors: list[str] = field(default_factory=list)  # Other actors in grouped notifs
    additional_count: int = 0  # "and N others"
    target_tweet_preview: str | None = None  # Preview of the tweet that was engaged with
    reply_content: str | None = None  # For replies: the actual reply text
    reply_to_content: str | None = None  # For replies: the original tweet they're replying to
    reply_tone: str | None = None  # For replies: tone classification (e.g., "curious", "supportive", "hostile")

    @property
    def total_actors(self) -> int:
        """Total number of actors including additional ones."""
        return 1 + len(self.additional_actors) + self.additional_count

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
class MyEngagementStats:
    """Statistics about the user's engagement in the current feed."""

    my_handle: str
    my_tweets_count: int = 0
    total_likes_received: int = 0
    total_retweets_received: int = 0
    total_replies_received: int = 0
    tweets_i_liked_count: int = 0
    tweets_i_retweeted_count: int = 0

    # From profile timeline
    profile_tweets: list = field(default_factory=list)  # list[Tweet]

    # From notifications
    recent_notifications: list = field(default_factory=list)  # list[Notification]
    likes_last_24h: int = 0
    retweets_last_24h: int = 0
    replies_last_24h: int = 0
    new_followers_last_24h: int = 0

    # Top engagers
    top_likers: list = field(default_factory=list)  # list[tuple[str, int]]
    top_retweeters: list = field(default_factory=list)  # list[tuple[str, int]]


@dataclass
class DigestTopic:
    """A topic cluster in the digest."""

    name: str  # e.g., "AI Safety Developments"
    emoji: str  # e.g., "🤖"
    summary: str  # 1-sentence summary
    tweet_ids: list[str] = field(default_factory=list)  # IDs of tweets in this topic


@dataclass
class Digest:
    """A clustered summary of tweets since last session."""

    topics: list[DigestTopic]
    total_tweets: int
    time_window_hours: float
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def time_window_str(self) -> str:
        """Human-readable time window."""
        hours = self.time_window_hours
        if hours < 1:
            return f"{int(hours * 60)} minutes"
        elif hours < 24:
            return f"{hours:.0f} hours"
        else:
            days = hours / 24
            return f"{days:.1f} days"
