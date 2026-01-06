"""Block mosaic visualization for X feed."""

import asyncio
import sys
import termios
import time
import tty
import webbrowser
from datetime import datetime
from threading import Thread
from queue import Queue, Empty

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.align import Align
from rich import box

from xfeed.models import FilteredTweet, TopicVibe, MyEngagementStats, Notification, NotificationType, ThreadContext, Tweet


class KeyboardListener:
    """Non-blocking keyboard listener for terminal using select()."""

    def __init__(self):
        self.queue: Queue[str] = Queue()
        self._running = False
        self._thread: Thread | None = None
        self._old_settings = None

    def start(self):
        """Start listening for keypresses."""
        if self._running:
            return  # Already running

        # Wait for old thread to finish if it exists
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=0.5)

        # Clear any stale keys from queue
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Empty:
                break

        self._running = True
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except Exception:
            pass  # Terminal might already be in right state

        self._thread = Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening and restore terminal."""
        self._running = False
        if self._old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass  # Terminal might be in weird state
            self._old_settings = None

    def _listen(self):
        """Background thread that reads keypresses using select for non-blocking."""
        import select
        while self._running:
            try:
                # Use select with timeout so we can check _running periodically
                readable, _, _ = select.select([sys.stdin], [], [], 0.05)
                if readable and self._running:
                    ch = sys.stdin.read(1)
                    if ch:
                        self.queue.put(ch)
            except Exception:
                if not self._running:
                    break  # Expected during shutdown

    def get_key(self) -> str | None:
        """Get a keypress if available, non-blocking."""
        try:
            return self.queue.get_nowait()
        except Empty:
            return None

    def drain_keys(self) -> list[str]:
        """Get all queued keypresses, non-blocking."""
        keys = []
        while True:
            try:
                keys.append(self.queue.get_nowait())
            except Empty:
                break
        return keys


def normalize_emoji(emoji: str) -> tuple[str, int]:
    """
    Normalize emoji for consistent terminal display width.

    Returns (normalized_emoji, display_width).

    Handles:
    - Variation selectors (U+FE0E text, U+FE0F emoji style)
    - Most emojis render as 2 cells in terminals
    - ZWJ sequences (👨‍👩‍👧) are kept intact but counted as 2 cells
    """
    # Strip variation selectors - they cause width miscalculation
    normalized = emoji.replace("\ufe0e", "").replace("\ufe0f", "")

    # Most emojis render as 2 cells in modern terminals
    # This is a safe assumption for display purposes
    return normalized, 2


def get_block_style(score: int) -> tuple[str, str, str]:
    """Get block character, fg color, bg color based on score."""
    if score >= 9:
        return "█", "bright_white", "red"
    elif score >= 7:
        return "▓", "bright_yellow", "yellow"
    elif score >= 5:
        return "▒", "bright_blue", "blue"
    else:
        return "░", "bright_black", "black"


def get_tile_height(score: int) -> int:
    """Get tile height based on relevance score."""
    if score >= 9:
        return 5
    elif score >= 7:
        return 3
    elif score >= 5:
        return 2
    else:
        return 1


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def split_into_pages(text: str, line_width: int, lines_per_page: int) -> list[list[str]]:
    """Split text into pages of wrapped lines."""
    text = text.replace("\n", " ").strip()
    words = text.split()

    all_lines = []
    current_line = ""

    for word in words:
        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= line_width:
            current_line += " " + word
        else:
            all_lines.append(current_line)
            current_line = word

    if current_line:
        all_lines.append(current_line)

    if not all_lines:
        return [[]]

    pages = []
    for i in range(0, len(all_lines), lines_per_page):
        pages.append(all_lines[i:i + lines_per_page])

    return pages if pages else [[]]


class MosaicTile:
    """A single tile in the mosaic representing a tweet."""

    PAGE_DURATION = 3.0

    def __init__(self, tweet: FilteredTweet, width: int, tile_id: int = 0, shortcut_num: int | None = None):
        self.tweet = tweet
        self.width = width
        self.score = tweet.relevance_score
        self.is_superdunk = tweet.is_superdunk
        self.height = get_tile_height(self.score)
        self.tile_id = tile_id
        self.shortcut_num = shortcut_num  # 1-9 for keyboard shortcut, None if no shortcut

        # Reputation badges (parsed from reason string)
        self.is_trusted = "[rep+" in tweet.reason
        self.is_rising = tweet.reason.startswith("[RISING]")

        content_width = self.width - 6
        content_lines = max(1, self.height - 2)

        if self.is_superdunk and tweet.tweet.quoted_tweet:
            quoted = tweet.tweet.quoted_tweet
            quoted_prefix = f"💬 {quoted.author_handle}: {quoted.content}"
            self.quoted_pages = split_into_pages(quoted_prefix, content_width, content_lines)
            dunk_prefix = f"🎯 {tweet.tweet.content}"
            self.dunk_pages = split_into_pages(dunk_prefix, content_width, content_lines)
            self.pages = self.quoted_pages + self.dunk_pages
        else:
            self.pages = split_into_pages(tweet.tweet.content, content_width, content_lines)

        self.total_pages = len(self.pages)

    def get_current_page(self, time_now: float) -> int:
        if self.total_pages <= 1:
            return 0
        offset_time = time_now + (self.tile_id * 0.5)
        cycle_position = (offset_time / self.PAGE_DURATION) % self.total_pages
        return int(cycle_position)

    def render(self, time_now: float = 0) -> Panel:
        t = self.tweet.tweet
        block, fg, bg = get_block_style(self.score)

        if self.is_superdunk:
            border_style = "bold bright_green"
            box_type = box.DOUBLE
        elif self.score >= 9:
            border_style = "bold red"
            box_type = box.DOUBLE
        elif self.score >= 7:
            border_style = "yellow"
            box_type = box.ROUNDED
        elif self.score >= 5:
            border_style = "blue"
            box_type = box.SQUARE
        else:
            border_style = "dim"
            box_type = box.MINIMAL

        current_page = self.get_current_page(time_now)
        page_lines = self.pages[current_page] if current_page < len(self.pages) else []

        page_indicator = ""
        if self.total_pages > 1:
            page_indicator = f" [{current_page + 1}/{self.total_pages}]"

        content_width = self.width - 4

        if self.height >= 5:
            available_content = max(1, self.height - 2)
            lines = []
            header = Text()
            if self.shortcut_num:
                header.append(f"⌘{self.shortcut_num} ", style="bold black on bright_yellow")
            if self.is_superdunk:
                header.append("🎯 ", style="bold")
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 18), style="bold cyan")
            # Reputation badges
            if self.is_trusted:
                header.append(" ★", style="bold gold1")
            elif self.is_rising:
                header.append(" ↑", style="bold bright_green")
            # Engagement badges
            if t.is_by_me:
                header.append(" 👤", style="bold bright_green")
            if t.is_liked_by_me:
                header.append(" ♥", style="bold red")
            if t.is_retweeted_by_me:
                header.append(" ↻", style="bold green")
            header.append(f" · {t.formatted_time}", style="dim")
            if page_indicator:
                header.append(page_indicator, style="dim magenta")
            lines.append(header)

            for line in page_lines[:available_content]:
                lines.append(Text(line, style="white"))

            while len(lines) < available_content + 1:
                lines.append(Text(""))

            eng = Text()
            if t.likes:
                eng.append(f"♥ {t.likes} ", style="red")
            if t.retweets:
                eng.append(f"↻ {t.retweets}", style="green")
            lines.append(eng)

            body = Text("\n").join(lines)

        elif self.height >= 3:
            available_content = max(1, self.height - 1)
            lines = []
            header = Text()
            if self.shortcut_num:
                header.append(f"⌘{self.shortcut_num} ", style="bold black on bright_yellow")
            if self.is_superdunk:
                header.append("🎯 ", style="bold")
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 12), style="cyan")
            # Reputation badges
            if self.is_trusted:
                header.append(" ★", style="bold gold1")
            elif self.is_rising:
                header.append(" ↑", style="bold bright_green")
            # Engagement badges
            if t.is_by_me:
                header.append(" 👤", style="bold bright_green")
            if t.is_liked_by_me:
                header.append(" ♥", style="bold red")
            if t.is_retweeted_by_me:
                header.append(" ↻", style="bold green")
            if page_indicator:
                header.append(page_indicator, style="dim magenta")
            lines.append(header)

            for line in page_lines[:available_content]:
                lines.append(Text(line, style="white"))

            while len(lines) < self.height:
                lines.append(Text(""))

            body = Text("\n").join(lines)

        elif self.height >= 2:
            available_content = max(1, self.height - 1)
            header = Text()
            if self.shortcut_num:
                header.append(f"⌘{self.shortcut_num} ", style="bold black on bright_yellow")
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 10), style="cyan")
            # Reputation badges (compact)
            if self.is_trusted:
                header.append(" ★", style="gold1")
            elif self.is_rising:
                header.append(" ↑", style="bright_green")
            # Engagement badges (compact)
            if t.is_by_me:
                header.append(" 👤", style="bright_green")
            if t.is_liked_by_me:
                header.append(" ♥", style="red")
            if t.is_retweeted_by_me:
                header.append(" ↻", style="green")
            if page_indicator:
                header.append(page_indicator, style="dim magenta")

            lines = [header]
            for line in page_lines[:available_content]:
                lines.append(Text(line, style="dim"))

            body = Text("\n").join(lines)

        else:
            body = Text()
            if self.shortcut_num:
                body.append(f"⌘{self.shortcut_num} ", style="bold black on bright_yellow")
            body.append(f"[{self.score}] ", style=f"{fg}")
            body.append(truncate(t.author_handle, content_width - 12), style="dim cyan")
            # Reputation badges (minimal)
            if self.is_trusted:
                body.append(" ★", style="gold1")
            elif self.is_rising:
                body.append(" ↑", style="bright_green")
            # Engagement badges (minimal)
            if t.is_by_me:
                body.append(" 👤", style="bright_green")
            if t.is_liked_by_me:
                body.append(" ♥", style="red")
            if t.is_retweeted_by_me:
                body.append(" ↻", style="green")

        return Panel(
            body,
            box=box_type,
            border_style=border_style,
            width=self.width,
            height=self.height + 2,
            padding=(0, 1),
        )


class VibeCard:
    """A card displaying a topic vibe."""

    def __init__(self, vibe: TopicVibe, width: int = 40):
        self.vibe = vibe
        self.width = width

    def render(self) -> Panel:
        v = self.vibe
        lines = []

        # Content width = panel width - 2 (borders) - 2 (padding)
        content_width = self.width - 4

        # Vibe line - build complete line then truncate
        count_suffix = f" ({v.tweet_count})"
        vibe_line = Text()
        vibe_line.append(v.vibe, style="italic cyan")
        vibe_line.append(count_suffix, style="dim")
        vibe_line.truncate(content_width, overflow="ellipsis")
        lines.append(vibe_line)

        # Description with cell-aware truncation
        desc_text = Text(v.description, style="white")
        desc_text.truncate(content_width, overflow="ellipsis")
        lines.append(desc_text)

        body = Text("\n").join(lines)

        # Build title with normalized emoji for consistent width
        emoji, emoji_width = normalize_emoji(v.emoji)
        # Account for border chars: "╭─ " (3) + " ─╮" (3) = 6
        # Plus emoji (2 cells) + space (1) = 3 more
        title_max = self.width - 6 - emoji_width - 1  # -1 for space after emoji
        topic_text = Text(v.topic)
        topic_text.truncate(title_max, overflow="ellipsis")
        title_text = Text(f"{emoji} ")
        title_text.append(topic_text)

        return Panel(
            body,
            title=title_text,
            title_align="left",
            box=box.ROUNDED,
            border_style="bright_magenta",
            width=self.width,
            height=4,  # 2 borders + 2 content lines
            padding=(0, 1),
        )


class EngagementCard:
    """A card displaying user's engagement stats with notifications."""

    PAGE_DURATION = 5.0  # Seconds per page of notifications
    NOTIFICATIONS_PER_PAGE = 4

    def __init__(self, stats: MyEngagementStats, width: int = 60):
        self.stats = stats
        self.width = width
        # Calculate total pages
        total_notifs = len(stats.recent_notifications) if stats.recent_notifications else 0
        self.total_pages = max(1, (total_notifs + self.NOTIFICATIONS_PER_PAGE - 1) // self.NOTIFICATIONS_PER_PAGE)

    def get_current_page(self, time_now: float) -> int:
        """Get the current page index based on time."""
        if self.total_pages <= 1:
            return 0
        cycle_position = (time_now / self.PAGE_DURATION) % self.total_pages
        return int(cycle_position)

    def _format_notification(self, n: Notification) -> Text:
        """Format a single notification for display (single line, no wrap)."""
        line = Text()

        # Icon based on type (all 2 chars wide for alignment)
        icons = {
            NotificationType.LIKE: ("♥ ", "red"),
            NotificationType.RETWEET: ("↻ ", "green"),
            NotificationType.REPLY: ("💬", "blue"),
            NotificationType.FOLLOW: ("+ ", "cyan"),
            NotificationType.QUOTE: ("❝ ", "yellow"),
            NotificationType.MENTION: ("@ ", "magenta"),
            NotificationType.UNKNOWN: ("? ", "dim"),
        }
        icon, color = icons.get(n.type, ("? ", "dim"))
        prefix = f"  {icon} "
        line.append(prefix, style=color)

        # Actor
        line.append(n.actor_handle, style="cyan")
        if n.additional_count > 0:
            line.append(f" +{n.additional_count}", style="dim")

        # Calculate used width so far (for reply content truncation)
        # prefix (5) + actor handle + optional count
        used_width = len(prefix) + len(n.actor_handle)
        if n.additional_count > 0:
            used_width += len(f" +{n.additional_count}")

        # For replies: show tone and content
        if n.type == NotificationType.REPLY:
            if n.reply_tone:
                # Color tone based on sentiment
                tone_color = "dim"
                tone_lower = n.reply_tone.lower()
                if any(w in tone_lower for w in ["hostile", "rude", "angry", "snarky", "dismissive", "condescending", "aggressive"]):
                    tone_color = "red"
                elif any(w in tone_lower for w in ["curious", "question", "confused", "wondering"]):
                    tone_color = "yellow"
                elif any(w in tone_lower for w in ["support", "grateful", "excited", "encouraging", "friendly", "helpful", "positive"]):
                    tone_color = "green"
                tone_text = f" [{n.reply_tone}]"
                line.append(tone_text, style=tone_color)
                used_width += len(tone_text)

            if n.reply_content:
                # Calculate remaining width for content (account for quotes and ellipsis)
                content_width = self.width - 4  # Panel content width
                remaining = content_width - used_width - 4  # 4 for ' "..."'
                remaining = max(10, remaining)  # Minimum 10 chars

                # Clean up content (remove newlines) and truncate
                content = n.reply_content.replace("\n", " ").strip()
                if len(content) > remaining:
                    content = content[:remaining - 1] + "…"
                line.append(f" \"{content}\"", style="dim italic")
        else:
            # Time for non-reply notifications
            line.append(f" ({n.formatted_time})", style="dim")

        return line

    def render(self, time_now: float = 0) -> Panel:
        s = self.stats
        content_width = self.width - 4

        lines = []

        # 24h Stats Row (if we have notification data)
        if s.likes_last_24h or s.retweets_last_24h or s.new_followers_last_24h:
            stats_24h = Text()
            stats_24h.append("Last 24h: ", style="dim")
            stats_24h.append(f"+{s.likes_last_24h} ♥ ", style="red")
            stats_24h.append(f"  +{s.retweets_last_24h} ↻ ", style="green")
            stats_24h.append(f"  +{s.replies_last_24h} 💬", style="blue")
            if s.new_followers_last_24h:
                stats_24h.append(f"  +{s.new_followers_last_24h} followers", style="cyan")
            lines.append(stats_24h)

        # Top engagers (if available)
        if s.top_likers:
            likers = Text()
            likers.append("Top likers: ", style="dim")
            handles = [h for h, _ in s.top_likers[:3]]
            likers.append(", ".join(handles), style="cyan")
            lines.append(likers)

        # Recent notifications (paged)
        if s.recent_notifications:
            current_page = self.get_current_page(time_now)
            start_idx = current_page * self.NOTIFICATIONS_PER_PAGE
            end_idx = start_idx + self.NOTIFICATIONS_PER_PAGE
            page_notifications = s.recent_notifications[start_idx:end_idx]

            lines.append(Text(""))
            # Show page indicator if multiple pages
            header = Text()
            header.append("Recent:", style="dim")
            if self.total_pages > 1:
                header.append(f" [{current_page + 1}/{self.total_pages}]", style="dim magenta")
            lines.append(header)

            for n in page_notifications:
                lines.append(self._format_notification(n))

        # Fallback to old display if no notification data
        if not lines:
            # My tweets stats
            if s.my_tweets_count > 0:
                my_line = Text()
                my_line.append(f"Your tweets: {s.my_tweets_count}", style="bright_green")
                my_line.append("  │  ", style="dim")
                my_line.append(f"+{s.total_likes_received} ♥ ", style="red")
                my_line.append(f"  +{s.total_retweets_received} ↻ ", style="green")
                lines.append(my_line)
            else:
                lines.append(Text("No engagement data yet", style="dim"))

        body = Text("\n").join(lines)

        # Build title
        title = Text()
        title.append("YOUR ENGAGEMENT", style="bold bright_cyan")
        if s.my_handle and s.my_handle != "unknown":
            title.append(f" ({s.my_handle})", style="dim")

        # Dynamic height based on content
        height = min(len(lines) + 2, 10)

        return Panel(
            body,
            title=title,
            title_align="left",
            box=box.ROUNDED,
            border_style="bright_cyan",
            width=self.width,
            height=height,
            padding=(0, 1),
        )


def compute_engagement_stats(
    tweets: list[FilteredTweet],
    my_handle: str | None,
    notifications: list[Notification] | None = None,
    profile_tweets: list | None = None,  # list[Tweet]
    analyze_tones: bool = True,
) -> MyEngagementStats:
    """Compute engagement statistics from tweets and notifications."""
    from collections import Counter
    from datetime import timedelta

    stats = MyEngagementStats(my_handle=my_handle or "unknown")

    # Process home feed tweets
    for ft in tweets:
        t = ft.tweet
        if t.is_by_me:
            stats.my_tweets_count += 1
            stats.total_likes_received += t.likes
            stats.total_retweets_received += t.retweets
            stats.total_replies_received += t.replies
        if t.is_liked_by_me:
            stats.tweets_i_liked_count += 1
        if t.is_retweeted_by_me:
            stats.tweets_i_retweeted_count += 1

    # Process profile tweets
    if profile_tweets:
        stats.profile_tweets = profile_tweets

    # Process notifications
    if notifications:
        # Analyze reply tones
        if analyze_tones:
            from xfeed.tone import analyze_reply_tones
            notifications = analyze_reply_tones(notifications)

        stats.recent_notifications = notifications[:20]  # Keep top 20 for paging

        cutoff = datetime.now() - timedelta(hours=24)
        liker_counts: Counter = Counter()
        retweeter_counts: Counter = Counter()

        for n in notifications:
            # Count engagement in last 24h
            if n.timestamp > cutoff:
                if n.type == NotificationType.LIKE:
                    stats.likes_last_24h += n.total_actors
                    liker_counts[n.actor_handle] += 1
                elif n.type == NotificationType.RETWEET:
                    stats.retweets_last_24h += n.total_actors
                    retweeter_counts[n.actor_handle] += 1
                elif n.type == NotificationType.REPLY:
                    stats.replies_last_24h += n.total_actors
                elif n.type == NotificationType.FOLLOW:
                    stats.new_followers_last_24h += n.total_actors

        # Top engagers
        stats.top_likers = liker_counts.most_common(5)
        stats.top_retweeters = retweeter_counts.most_common(5)

    return stats


class ThreadOverlay:
    """Overlay panel showing thread context for a selected tweet."""

    def __init__(self, context: ThreadContext, width: int, height: int):
        self.context = context
        self.width = width
        self.height = height
        self.scroll_offset = 0

    def _render_thread_tweet(self, tweet: Tweet, highlight: bool = False) -> Text:
        """Render a single tweet in thread format."""
        line = Text()

        if highlight:
            line.append(">>> ", style="bold bright_yellow")
        else:
            line.append("    ", style="dim")

        line.append(f"{tweet.author_handle}", style="cyan")
        line.append(f" ({tweet.formatted_time})", style="dim")
        line.append("\n")

        # Indent content
        prefix = "    " if not highlight else "    "
        content = tweet.content.replace("\n", " ")
        if len(content) > 300:
            content = content[:297] + "..."

        # Wrap content to fit width
        content_width = self.width - 10
        words = content.split()
        current_line = prefix
        for word in words:
            if len(current_line) + len(word) + 1 > content_width:
                line.append(current_line + "\n", style="white" if highlight else "dim")
                current_line = prefix + word + " "
            else:
                current_line += word + " "
        if current_line.strip():
            line.append(current_line.rstrip(), style="white" if highlight else "dim")

        return line

    def render(self) -> Panel:
        """Render the thread overlay as a panel."""
        lines: list[Text] = []

        # Header
        header = Text()
        header.append("THREAD CONTEXT", style="bold bright_cyan")
        header.append(f"  ({self.context.total_count} tweets)", style="dim")
        lines.append(header)
        lines.append(Text())

        # Parent tweets (context above)
        if self.context.parent_tweets:
            for tweet in self.context.parent_tweets:
                lines.append(self._render_thread_tweet(tweet, highlight=False))
                lines.append(Text())

            # Separator
            sep = Text("─" * (self.width - 8), style="dim cyan")
            lines.append(sep)
            lines.append(Text())

        # Main tweet (highlighted)
        lines.append(self._render_thread_tweet(self.context.original_tweet, highlight=True))
        lines.append(Text())

        # Replies below
        if self.context.reply_tweets:
            # Separator
            sep = Text("─" * (self.width - 8), style="dim cyan")
            lines.append(sep)
            lines.append(Text())

            for tweet in self.context.reply_tweets:
                lines.append(self._render_thread_tweet(tweet, highlight=False))
                lines.append(Text())

        body = Text("\n").join(lines)

        return Panel(
            body,
            title="[bold cyan]Thread View[/bold cyan]",
            subtitle="[dim][Esc] close[/dim]",
            box=box.DOUBLE,
            border_style="bright_cyan",
            width=self.width,
            padding=(1, 2),
        )


class MosaicDisplay:
    """Live mosaic display of filtered tweets."""

    def __init__(
        self,
        tweets: list[FilteredTweet] | None = None,
        vibes: list[TopicVibe] | None = None,
        engagement_stats: MyEngagementStats | None = None,
        refresh_callback=None,
        refresh_interval: int = 300,
        threshold: int = 5,
        count: int = 20,
    ):
        # Store all tweets for re-filtering when threshold changes
        tweets = tweets or []
        self._all_tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.tweets = self._all_tweets  # Currently displayed tweets
        self.vibes = vibes or []
        self.engagement_stats = engagement_stats
        self.console = Console()
        self.refresh_callback = refresh_callback
        self.refresh_interval = refresh_interval
        self.last_refresh = time.time()
        self.url_shortcuts: dict[int, str] = {}  # Maps 1-9 to tweet URLs

        # Mutable criteria state
        self.threshold = threshold
        self.count = count
        self.count_options = [10, 20, 50, 100]

        # Refresh state (updated by run_mosaic)
        self.is_refreshing = False
        self.refresh_elapsed = 0
        self.refresh_phase = ""

        # Initial loading state
        self.is_initial_load = len(tweets) == 0
        self.load_phase = "Connecting to X..."
        self.load_start_time = time.time()

        # Thread overlay state
        self.thread_overlay_visible: bool = False
        self.thread_context: ThreadContext | None = None
        self.thread_loading: bool = False
        self.selected_tweet_num: int | None = None

    def create_tiles(self) -> list[MosaicTile]:
        """Create tiles for tweets with shortcut numbers."""
        tiles = []
        width = self.console.width
        self.url_shortcuts = {}

        # Assign shortcuts in display order: large, medium, small
        large = [t for t in self.tweets if t.relevance_score >= 9][:3]
        medium = [t for t in self.tweets if 7 <= t.relevance_score < 9][:6]
        small = [t for t in self.tweets if t.relevance_score < 7][:9]

        # Combine in display order, limit to 9 total
        ordered_tweets = (large + medium + small)[:9]

        # Create mapping of tweet to shortcut number
        shortcut_map = {id(t): i + 1 for i, t in enumerate(ordered_tweets)}

        # Store URLs for shortcuts
        for i, tweet in enumerate(ordered_tweets):
            self.url_shortcuts[i + 1] = tweet.tweet.url

        for i, tweet in enumerate(self.tweets):
            if tweet.relevance_score >= 9:
                tile_width = min(width - 4, 80)
            elif tweet.relevance_score >= 7:
                tile_width = min(width - 4, 60)
            elif tweet.relevance_score >= 5:
                tile_width = min(width - 4, 50)
            else:
                tile_width = min(width - 4, 40)

            shortcut = shortcut_map.get(id(tweet))
            tiles.append(MosaicTile(tweet, tile_width, tile_id=i, shortcut_num=shortcut))

        return tiles

    def get_url_for_shortcut(self, num: int) -> str | None:
        """Get the URL for a shortcut number (1-9)."""
        return self.url_shortcuts.get(num)

    def refilter_tweets(self):
        """Re-filter current tweets with updated threshold."""
        self.tweets = [t for t in self._all_tweets if t.relevance_score >= self.threshold]

    def cycle_count(self):
        """Cycle through count options: 10 → 20 → 50 → 100 → 10."""
        if self.count in self.count_options:
            idx = self.count_options.index(self.count)
            self.count = self.count_options[(idx + 1) % len(self.count_options)]
        else:
            self.count = self.count_options[0]

    def render_vibe_section(self) -> RenderableType | None:
        """Render the vibe of the day section."""
        if not self.vibes:
            return None

        num_vibes = min(3, len(self.vibes))
        width = self.console.width

        # Calculate card width to fill available space
        card_width = max(30, (width - 10) // num_vibes)

        table = Table.grid(padding=1)
        for _ in range(num_vibes):
            table.add_column()

        cards = [VibeCard(v, width=card_width).render() for v in self.vibes[:num_vibes]]
        table.add_row(*cards)

        return Align.center(table)

    def render_engagement_section(self, time_now: float) -> RenderableType | None:
        """Render the my engagement section (full width)."""
        if not self.engagement_stats:
            return None

        # Always show if we have a valid handle
        if not self.engagement_stats.my_handle or self.engagement_stats.my_handle == "unknown":
            return None

        # Use full terminal width
        width = self.console.width - 2
        card = EngagementCard(self.engagement_stats, width=width)
        return card.render(time_now)

    def render_header(self) -> Text:
        """Render the header bar."""
        now = datetime.now().strftime("%H:%M:%S")
        next_refresh = max(0, self.refresh_interval - (time.time() - self.last_refresh))

        # Count displayed tweets
        large = len([t for t in self.tweets if t.relevance_score >= 9][:3])
        medium = len([t for t in self.tweets if 7 <= t.relevance_score < 9][:6])
        small = len([t for t in self.tweets if t.relevance_score < 7][:9])
        displayed = large + medium + small

        header = Text()
        header.append("━━━ ", style="bold red")
        header.append("XFEED", style="bold bright_white")
        header.append(" ", style="")
        header.append("MOSAIC", style="bold bright_red")
        header.append(" ━━━", style="bold red")
        header.append(f"  {now}", style="dim")
        header.append(f"  │  threshold: {self.threshold}+", style="cyan")
        header.append(f"  │  count: {self.count}", style="cyan")
        if self.is_refreshing:
            phase_text = self.refresh_phase if self.refresh_phase else "refreshing"
            header.append(f"  │  ⟳ {phase_text} ({self.refresh_elapsed}s)", style="bold yellow")
        else:
            header.append(f"  │  refresh in {int(next_refresh)}s", style="dim")
        header.append(f"  │  {displayed} showing", style="dim")

        return header

    def render_legend(self) -> Text:
        """Render a legend."""
        legend = Text()
        legend.append("█ 9-10 ", style="red")
        legend.append("▓ 7-8 ", style="yellow")
        legend.append("▒ 5-6 ", style="blue")
        legend.append("░ <5 ", style="dim")
        legend.append("│ ", style="dim")
        legend.append("★ trusted ", style="gold1")
        legend.append("↑ rising ", style="bright_green")
        legend.append("│ ", style="dim")
        legend.append("🎯 superdunk", style="bright_green")
        return legend

    def render_thread_overlay(self) -> Group:
        """Render the thread overlay on top of a dimmed mosaic."""
        elements: list[RenderableType] = [
            Align.center(self.render_header()),
            Text(),
        ]

        if self.thread_context:
            overlay_width = min(100, int(self.console.width * 0.85))
            overlay = ThreadOverlay(
                self.thread_context,
                width=overlay_width,
                height=30,
            )
            elements.append(Text())
            elements.append(Align.center(overlay.render()))

        return Group(*elements)

    def render_thread_loading(self) -> Group:
        """Render loading indicator while fetching thread."""
        elements: list[RenderableType] = [
            Align.center(self.render_header()),
            Text(),
            Text(),
            Text(),
        ]

        loading = Text()
        loading.append("⟳ ", style="bold bright_cyan")
        loading.append(f"Loading thread for tweet #{self.selected_tweet_num}...", style="cyan")
        elements.append(Align.center(loading))
        elements.append(Text())
        elements.append(Align.center(Text("[Esc] cancel", style="dim")))

        return Group(*elements)

    def render_loading(self) -> Group:
        """Render the loading screen with animated spinner."""
        now = time.time()
        elapsed = now - self.load_start_time

        elements: list[RenderableType] = [
            Align.center(self.render_header()),
            Text(),
            Text(),
        ]

        # Animated spinner frames
        spinner_frames = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        frame_idx = int(elapsed * 10) % len(spinner_frames)
        spinner = spinner_frames[frame_idx]

        # Progress bar animation
        bar_width = 40
        progress_pos = int((elapsed * 2) % bar_width)
        bar = Text()
        for i in range(bar_width):
            dist = abs(i - progress_pos)
            if dist == 0:
                bar.append("█", style="bold red")
            elif dist == 1:
                bar.append("▓", style="red")
            elif dist == 2:
                bar.append("▒", style="yellow")
            elif dist == 3:
                bar.append("░", style="blue")
            else:
                bar.append("░", style="dim")

        # Build loading display
        loading_text = Text()
        loading_text.append(f"\n\n{spinner} ", style="bold bright_red")
        loading_text.append(self.load_phase, style="bold white")
        loading_text.append(f" ({int(elapsed)}s)", style="dim")

        elements.append(Align.center(loading_text))
        elements.append(Text())
        elements.append(Align.center(bar))
        elements.append(Text())

        # Anticipation messages based on elapsed time and phase
        tip = Text()
        phase = self.load_phase.lower()

        if "fetching" in phase and "scoring" in phase:
            # Combined fetch + score phase
            if elapsed < 5:
                tip.append("Opening browser session...", style="dim italic")
            elif elapsed < 15:
                tip.append("Scrolling your timeline...", style="dim italic")
            elif elapsed < 25:
                tip.append("Scoring with Claude Haiku...", style="dim italic")
            elif elapsed < 35:
                tip.append("Analyzing relevance...", style="dim italic")
            else:
                tip.append("Still working, hang tight...", style="dim italic")
        elif "vibe" in phase:
            tip.append("Identifying topics and themes...", style="dim italic")
        elif "building" in phase:
            tip.append("Arranging tiles...", style="dim italic")
        else:
            tip.append("Preparing your feed...", style="dim italic")

        elements.append(Align.center(tip))

        # Add some visual flair
        elements.append(Text())
        elements.append(Text())

        flair = Text()
        flair.append("█ ", style="red")
        flair.append("▓ ", style="yellow")
        flair.append("▒ ", style="blue")
        flair.append("░", style="dim")
        elements.append(Align.center(flair))

        elements.append(Text())
        elements.append(Align.center(Text("[q]uit", style="dim")))

        return Group(*elements)

    def render(self) -> Group:
        """Render the full mosaic display."""
        # Show loading screen during initial load
        if self.is_initial_load:
            return self.render_loading()

        # Show thread overlay if visible
        if self.thread_overlay_visible and self.thread_context:
            return self.render_thread_overlay()

        # Show thread loading indicator
        if self.thread_loading:
            return self.render_thread_loading()

        now = time.time()
        tiles = self.create_tiles()

        elements: list[RenderableType] = [
            Align.center(self.render_header()),
            Text(),
        ]

        # Add vibe section at the top
        vibe_section = self.render_vibe_section()
        if vibe_section:
            elements.append(vibe_section)
            elements.append(Text())

        if not tiles:
            elements.append(Align.center(Text("No tweets to display...", style="dim italic")))
        else:
            large_tiles = [t for t in tiles if t.score >= 9][:3]
            medium_tiles = [t for t in tiles if 7 <= t.score < 9][:6]
            small_tiles = [t for t in tiles if t.score < 7][:9]

            # Large tiles
            for tile in large_tiles:
                elements.append(Align.center(tile.render(now)))

            # Medium tiles (2 per row)
            if medium_tiles:
                table = Table.grid(padding=1)
                table.add_column()
                table.add_column()

                for i in range(0, len(medium_tiles), 2):
                    row = [medium_tiles[i].render(now)]
                    if i + 1 < len(medium_tiles):
                        row.append(medium_tiles[i + 1].render(now))
                    table.add_row(*row)

                elements.append(Align.center(table))

            # Small tiles (3 per row)
            if small_tiles:
                small_table = Table.grid(padding=0)
                for _ in range(3):
                    small_table.add_column()

                for i in range(0, len(small_tiles), 3):
                    row = [small_tiles[i].render(now)]
                    for j in range(1, 3):
                        if i + j < len(small_tiles):
                            row.append(small_tiles[i + j].render(now))
                    small_table.add_row(*row)

                elements.append(Align.center(small_table))

        # Add engagement section at bottom, above commands
        engagement_section = self.render_engagement_section(now)
        if engagement_section:
            elements.append(Text())
            elements.append(engagement_section)

        elements.append(Text())
        elements.append(Align.center(self.render_legend()))
        elements.append(Align.center(Text("[1-9] open  [t] thread  [+/-] threshold  [c]ount  [o]bjectives  [r]efresh  [q]uit", style="dim")))

        return Group(*elements)

    def update_tweets(
        self,
        tweets: list[FilteredTweet],
        vibes: list[TopicVibe] | None = None,
        engagement_stats: MyEngagementStats | None = None,
    ):
        """Update with new tweets, vibes, and engagement stats."""
        # Store all tweets for re-filtering, then filter by current threshold
        self._all_tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.refilter_tweets()
        if vibes is not None:
            self.vibes = vibes
        if engagement_stats is not None:
            self.engagement_stats = engagement_stats
        self.last_refresh = time.time()


def set_terminal_title(status: str = "") -> None:
    """Set the terminal window title."""
    if status:
        title = f"XFEED Mosaic - {status}"
    else:
        title = "XFEED Mosaic"
    sys.stdout.write(f"\033]0;{title}\007")
    sys.stdout.flush()


def open_objectives_in_editor(keyboard: KeyboardListener, live) -> None:
    """Open objectives.md in user's editor."""
    import os
    import subprocess
    from xfeed.config import get_objectives_path

    editor = os.environ.get("EDITOR", "nano")
    objectives_path = get_objectives_path()

    # Temporarily stop keyboard listener and live display for editor
    keyboard.stop()
    live.stop()

    try:
        subprocess.run([editor, str(objectives_path)])
    finally:
        # Restart keyboard listener and live display
        keyboard.start()
        live.start()


def get_insight(vibes: list[TopicVibe], tweets: list[FilteredTweet]) -> str:
    """Get a short insight for the title bar."""
    if vibes:
        # Use top vibe's topic + emoji
        v = vibes[0]
        return f"{v.emoji} {v.topic}"
    elif tweets:
        # Use top tweet's author
        return f"@{tweets[0].tweet.author_handle}"
    return "No tweets"


def parse_fetch_result(result, default_handle=None):
    """Parse fetch result which can be 2-tuple or 4-tuple."""
    if not isinstance(result, tuple):
        return result, default_handle, [], []
    if len(result) == 2:
        return result[0], result[1], [], []
    if len(result) == 4:
        return result
    return result[0], default_handle, [], []


async def run_mosaic(
    fetch_func,
    vibe_func=None,
    refresh_minutes: int = 5,
    count: int = 20,
    threshold: int = 5,
):
    """Run the mosaic display with periodic refresh."""
    console = Console()

    # Create mosaic immediately with empty state (shows loading screen)
    mosaic = MosaicDisplay(
        tweets=None,  # Empty - triggers loading state
        vibes=None,
        engagement_stats=None,
        refresh_callback=fetch_func,
        refresh_interval=refresh_minutes * 60,
        threshold=threshold,
        count=count,
    )

    set_terminal_title("Loading...")

    last_refresh = time.time()
    keyboard = KeyboardListener()
    keyboard.start()

    # Background refresh state
    refresh_task: asyncio.Task | None = None
    refresh_started: float = 0
    my_handle = None
    vibe_task = None
    vibe_task_data = None

    # Thread fetch state
    thread_task: asyncio.Task | None = None

    async def do_refresh(cnt: int, thresh: int):
        """Perform refresh in background."""
        return await fetch_func(cnt, thresh)

    async def do_initial_load():
        """Perform initial load with phase updates."""
        nonlocal my_handle
        loop = asyncio.get_event_loop()

        # Phase 1: Fetch from X and score with Claude Haiku
        mosaic.load_phase = "Fetching & scoring tweets..."
        mosaic.load_start_time = time.time()  # Reset timer for this phase
        result = await fetch_func(count, threshold)
        tweets, my_handle, profile_tweets, notifications = parse_fetch_result(result)

        # Phase 2: Extract vibes/topics (run in executor to not block UI)
        vibes = []
        if tweets and vibe_func:
            mosaic.load_phase = "Extracting vibes..."
            mosaic.load_start_time = time.time()  # Reset timer for this phase
            vibes = await loop.run_in_executor(None, vibe_func, tweets)

        # Phase 3: Build display (fast)
        mosaic.load_phase = "Building mosaic..."

        # Compute engagement stats
        engagement_stats = compute_engagement_stats(
            tweets, my_handle, notifications, profile_tweets
        ) if tweets else None

        return tweets, vibes, engagement_stats, my_handle

    # Start initial load immediately
    initial_load_task = asyncio.create_task(do_initial_load())

    try:
        with Live(mosaic.render(), console=console, refresh_per_second=10, screen=True) as live:
            try:
                while True:
                    now = time.time()

                    # Check if initial load completed
                    if initial_load_task is not None and initial_load_task.done():
                        try:
                            tweets, vibes, engagement_stats, my_handle = initial_load_task.result()
                            if tweets:
                                mosaic.update_tweets(tweets, vibes, engagement_stats)
                                set_terminal_title(get_insight(vibes, tweets))
                            mosaic.is_initial_load = False
                            last_refresh = now
                        except Exception as e:
                            set_terminal_title(f"Error: {e}")
                            mosaic.is_initial_load = False
                        initial_load_task = None

                    # Check if background refresh completed (but vibe extraction still pending)
                    if refresh_task is not None and refresh_task.done() and vibe_task is None:
                        try:
                            result = refresh_task.result()
                            new_tweets, new_handle, new_profile, new_notifs = parse_fetch_result(result, my_handle)

                            # Start vibe extraction in background
                            if vibe_func and new_tweets:
                                mosaic.refresh_phase = "extracting vibes"
                                loop = asyncio.get_event_loop()
                                vibe_task = loop.run_in_executor(None, vibe_func, new_tweets)
                                vibe_task_data = (new_tweets, new_handle, new_profile, new_notifs)
                            else:
                                # No vibes needed, finish refresh now
                                # Always compute engagement stats (even without tweets, we have notifications)
                                new_stats = compute_engagement_stats(
                                    new_tweets, new_handle, new_notifs, new_profile
                                )
                                mosaic.update_tweets(new_tweets, [], new_stats)
                                if new_tweets:
                                    set_terminal_title(get_insight([], new_tweets))
                                last_refresh = now
                                refresh_task = None
                                mosaic.is_refreshing = False
                                mosaic.refresh_phase = ""
                        except Exception as e:
                            set_terminal_title(f"Error: {e}")
                            refresh_task = None
                            mosaic.is_refreshing = False
                            mosaic.refresh_phase = ""

                    # Check if vibe extraction completed
                    if vibe_task is not None and vibe_task.done():
                        try:
                            new_vibes = vibe_task.result()
                            new_tweets, new_handle, new_profile, new_notifs = vibe_task_data

                            # Always compute engagement stats (notifications provide engagement data)
                            new_stats = compute_engagement_stats(
                                new_tweets, new_handle, new_notifs, new_profile
                            )
                            mosaic.update_tweets(new_tweets, new_vibes, new_stats)
                            if new_tweets:
                                set_terminal_title(get_insight(new_vibes, new_tweets))
                            last_refresh = now
                        except Exception as e:
                            set_terminal_title(f"Error: {e}")
                        vibe_task = None
                        vibe_task_data = None
                        refresh_task = None
                        mosaic.is_refreshing = False
                        mosaic.refresh_phase = ""

                    # Check if thread fetch completed
                    if thread_task is not None and thread_task.done():
                        try:
                            thread_context = thread_task.result()
                            if thread_context:
                                mosaic.thread_context = thread_context
                                mosaic.thread_overlay_visible = True
                        except Exception:
                            pass  # Thread fetch failed silently
                        thread_task = None
                        mosaic.thread_loading = False

                    # Handle keyboard input - process all queued keys
                    keys = keyboard.drain_keys()
                    should_quit = False
                    should_refresh = False

                    for key in keys:
                        # Handle overlay mode differently
                        if mosaic.thread_overlay_visible:
                            if key == '\x1b' or key == 'q':  # Escape or q closes overlay
                                mosaic.thread_overlay_visible = False
                                mosaic.thread_context = None
                            continue  # Don't process other keys when overlay visible

                        # Handle thread loading cancellation
                        if mosaic.thread_loading:
                            if key == '\x1b' or key == 'q':  # Cancel loading
                                if thread_task and not thread_task.done():
                                    thread_task.cancel()
                                mosaic.thread_loading = False
                                thread_task = None
                            continue

                        # Normal mode
                        if key == 'q':
                            should_quit = True
                            break
                        elif key == 'r':
                            should_refresh = True
                        elif key and key.isdigit() and key != '0':
                            num = int(key)
                            mosaic.selected_tweet_num = num  # Track selection
                            url = mosaic.get_url_for_shortcut(num)
                            if url:
                                webbrowser.open(url)
                        elif key == 't':
                            # Load thread for selected tweet
                            if mosaic.selected_tweet_num and thread_task is None:
                                url = mosaic.get_url_for_shortcut(mosaic.selected_tweet_num)
                                if url:
                                    from xfeed.fetcher import fetch_thread
                                    mosaic.thread_loading = True
                                    thread_task = asyncio.create_task(fetch_thread(url))
                        elif key == '+' or key == '=':
                            if mosaic.threshold < 10:
                                mosaic.threshold += 1
                                mosaic.refilter_tweets()
                        elif key == '-':
                            if mosaic.threshold > 0:
                                mosaic.threshold -= 1
                                mosaic.refilter_tweets()
                        elif key == 'c':
                            mosaic.cycle_count()
                        elif key == 'o':
                            open_objectives_in_editor(keyboard, live)

                    if should_quit:
                        break

                    # Start background refresh if needed (manual or auto)
                    need_auto_refresh = now - last_refresh >= refresh_minutes * 60
                    if (should_refresh or need_auto_refresh) and refresh_task is None:
                        set_terminal_title("Refreshing...")
                        refresh_started = now
                        mosaic.is_refreshing = True
                        mosaic.refresh_elapsed = 0
                        mosaic.refresh_phase = "fetching & scoring"
                        refresh_task = asyncio.create_task(
                            do_refresh(mosaic.count, mosaic.threshold)
                        )

                    # Update refresh progress if refreshing
                    if refresh_task is not None:
                        elapsed = int(now - refresh_started)
                        mosaic.refresh_elapsed = elapsed
                        set_terminal_title(f"Refreshing... ({elapsed}s)")

                    live.update(mosaic.render())
                    await asyncio.sleep(0.1)  # Fast loop for responsive keyboard

            except KeyboardInterrupt:
                pass
    finally:
        # Cancel any pending tasks
        if initial_load_task is not None and not initial_load_task.done():
            initial_load_task.cancel()
            try:
                await initial_load_task
            except asyncio.CancelledError:
                pass
        if refresh_task is not None and not refresh_task.done():
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        if vibe_task is not None:
            try:
                vibe_task.cancel()
            except Exception:
                pass
        if thread_task is not None and not thread_task.done():
            thread_task.cancel()
            try:
                await thread_task
            except asyncio.CancelledError:
                pass
        keyboard.stop()
        # Restore default terminal title
        sys.stdout.write("\033]0;\007")
        sys.stdout.flush()

    console.print("\n[dim]Mosaic stopped.[/dim]")
