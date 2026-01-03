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

from xfeed.models import FilteredTweet, TopicVibe, MyEngagementStats, Notification, NotificationType


class KeyboardListener:
    """Non-blocking keyboard listener for terminal."""

    def __init__(self):
        self.queue: Queue[str] = Queue()
        self._running = False
        self._thread: Thread | None = None
        self._old_settings = None

    def start(self):
        """Start listening for keypresses."""
        self._running = True
        self._old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        self._thread = Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening and restore terminal."""
        self._running = False
        if self._old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)

    def _listen(self):
        """Background thread that reads keypresses."""
        while self._running:
            try:
                ch = sys.stdin.read(1)
                if ch:
                    self.queue.put(ch)
            except Exception:
                break

    def get_key(self) -> str | None:
        """Get a keypress if available, non-blocking."""
        try:
            return self.queue.get_nowait()
        except Empty:
            return None


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

    def __init__(self, stats: MyEngagementStats, width: int = 60):
        self.stats = stats
        self.width = width

    def _format_notification(self, n: Notification) -> Text:
        """Format a single notification for display."""
        line = Text()

        # Icon based on type
        icons = {
            NotificationType.LIKE: ("♥", "red"),
            NotificationType.RETWEET: ("↻", "green"),
            NotificationType.REPLY: ("💬", "blue"),
            NotificationType.FOLLOW: ("+", "cyan"),
            NotificationType.QUOTE: ("❝", "yellow"),
            NotificationType.MENTION: ("@", "magenta"),
        }
        icon, color = icons.get(n.type, ("•", "dim"))
        line.append(f"  {icon} ", style=color)

        # Actor
        line.append(n.actor_handle, style="cyan")
        if n.additional_count > 0:
            line.append(f" +{n.additional_count}", style="dim")

        # Time
        line.append(f" ({n.formatted_time})", style="dim")

        return line

    def render(self) -> Panel:
        s = self.stats
        content_width = self.width - 4

        lines = []

        # 24h Stats Row (if we have notification data)
        if s.likes_last_24h or s.retweets_last_24h or s.new_followers_last_24h:
            stats_24h = Text()
            stats_24h.append("Last 24h: ", style="dim")
            stats_24h.append(f"+{s.likes_last_24h} ♥", style="red")
            stats_24h.append(f"  +{s.retweets_last_24h} ↻", style="green")
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

        # Recent notifications
        if s.recent_notifications:
            lines.append(Text(""))
            lines.append(Text("Recent:", style="dim"))
            for n in s.recent_notifications[:4]:
                lines.append(self._format_notification(n))

        # Fallback to old display if no notification data
        if not lines:
            # My tweets stats
            if s.my_tweets_count > 0:
                my_line = Text()
                my_line.append(f"Your tweets: {s.my_tweets_count}", style="bright_green")
                my_line.append("  │  ", style="dim")
                my_line.append(f"+{s.total_likes_received} ♥", style="red")
                my_line.append(f"  +{s.total_retweets_received} ↻", style="green")
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
        stats.recent_notifications = notifications[:10]  # Keep top 10

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


class MosaicDisplay:
    """Live mosaic display of filtered tweets."""

    def __init__(
        self,
        tweets: list[FilteredTweet],
        vibes: list[TopicVibe] | None = None,
        engagement_stats: MyEngagementStats | None = None,
        refresh_callback=None,
        refresh_interval: int = 300,
    ):
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.vibes = vibes or []
        self.engagement_stats = engagement_stats
        self.console = Console()
        self.refresh_callback = refresh_callback
        self.refresh_interval = refresh_interval
        self.last_refresh = time.time()
        self.url_shortcuts: dict[int, str] = {}  # Maps 1-9 to tweet URLs

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

    def render_engagement_section(self) -> RenderableType | None:
        """Render the my engagement section."""
        if not self.engagement_stats:
            return None

        # Always show if we have a valid handle
        if not self.engagement_stats.my_handle or self.engagement_stats.my_handle == "unknown":
            return None

        width = min(self.console.width - 4, 60)
        card = EngagementCard(self.engagement_stats, width=width)
        return Align.center(card.render())

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
        header.append("▄" * 20, style="bright_red")
        header.append(" XFEED MOSAIC ", style="bold white on red")
        header.append("▄" * 20, style="bright_red")
        header.append(f"  {now}", style="dim")
        header.append(f"  │  refresh in {int(next_refresh)}s", style="dim")
        header.append(f"  │  {displayed} tweets", style="dim")

        return header

    def render_legend(self) -> Text:
        """Render a legend."""
        legend = Text()
        legend.append("█ 9-10 ", style="red")
        legend.append("▓ 7-8 ", style="yellow")
        legend.append("▒ 5-6 ", style="blue")
        legend.append("░ <5 ", style="dim")
        legend.append("│ ", style="dim")
        legend.append("🎯 superdunk", style="bright_green")
        return legend

    def render(self) -> Group:
        """Render the full mosaic display."""
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

        # Add engagement section
        engagement_section = self.render_engagement_section()
        if engagement_section:
            elements.append(engagement_section)
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

        elements.append(Text())
        elements.append(Align.center(self.render_legend()))
        elements.append(Align.center(Text("[1-9] open  [r]efresh  [q]uit", style="dim")))

        return Group(*elements)

    def update_tweets(
        self,
        tweets: list[FilteredTweet],
        vibes: list[TopicVibe] | None = None,
        engagement_stats: MyEngagementStats | None = None,
    ):
        """Update with new tweets, vibes, and engagement stats."""
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
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

    set_terminal_title("Loading...")
    console.print("[dim]Fetching tweets for mosaic...[/dim]")
    result = await fetch_func(count, threshold)
    tweets, my_handle, profile_tweets, notifications = parse_fetch_result(result)

    vibes = []
    if tweets and vibe_func:
        set_terminal_title("Analyzing...")
        console.print("[dim]Analyzing vibe of the day...[/dim]")
        vibes = vibe_func(tweets)

    # Compute engagement stats with notifications
    engagement_stats = compute_engagement_stats(
        tweets, my_handle, notifications, profile_tweets
    ) if tweets else None

    if not tweets:
        console.print("[yellow]No tweets found. Will retry on refresh.[/yellow]")

    # Set title to top insight
    set_terminal_title(get_insight(vibes, tweets))

    mosaic = MosaicDisplay(
        tweets,
        vibes=vibes,
        engagement_stats=engagement_stats,
        refresh_callback=fetch_func,
        refresh_interval=refresh_minutes * 60,
    )

    last_refresh = time.time()
    keyboard = KeyboardListener()
    keyboard.start()

    try:
        with Live(mosaic.render(), console=console, refresh_per_second=2, screen=True) as live:
            try:
                while True:
                    now = time.time()

                    # Handle keyboard input
                    key = keyboard.get_key()
                    if key == 'q':
                        break
                    elif key == 'r':
                        # Manual refresh
                        set_terminal_title("Refreshing...")
                        result = await fetch_func(count, threshold)
                        new_tweets, new_handle, new_profile, new_notifs = parse_fetch_result(result, my_handle)
                        new_vibes = vibe_func(new_tweets) if vibe_func and new_tweets else []
                        new_stats = compute_engagement_stats(
                            new_tweets, new_handle, new_notifs, new_profile
                        ) if new_tweets else None
                        if new_tweets:
                            mosaic.update_tweets(new_tweets, new_vibes, new_stats)
                            set_terminal_title(get_insight(new_vibes, new_tweets))
                        last_refresh = now
                    elif key and key.isdigit() and key != '0':
                        # Open tweet by number
                        num = int(key)
                        url = mosaic.get_url_for_shortcut(num)
                        if url:
                            webbrowser.open(url)

                    # Auto refresh
                    if now - last_refresh >= refresh_minutes * 60:
                        set_terminal_title("Refreshing...")
                        result = await fetch_func(count, threshold)
                        new_tweets, new_handle, new_profile, new_notifs = parse_fetch_result(result, my_handle)
                        new_vibes = vibe_func(new_tweets) if vibe_func and new_tweets else []
                        new_stats = compute_engagement_stats(
                            new_tweets, new_handle, new_notifs, new_profile
                        ) if new_tweets else None
                        if new_tweets:
                            mosaic.update_tweets(new_tweets, new_vibes, new_stats)
                            set_terminal_title(get_insight(new_vibes, new_tweets))
                        last_refresh = now

                    live.update(mosaic.render())
                    await asyncio.sleep(0.5)

            except KeyboardInterrupt:
                pass
    finally:
        keyboard.stop()
        # Restore default terminal title
        sys.stdout.write("\033]0;\007")
        sys.stdout.flush()

    console.print("\n[dim]Mosaic stopped.[/dim]")
