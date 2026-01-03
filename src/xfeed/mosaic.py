"""Block mosaic visualization for X feed."""

import asyncio
import sys
import termios
import time
import tty
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

from xfeed.models import FilteredTweet, TopicVibe


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

    def __init__(self, tweet: FilteredTweet, width: int, tile_id: int = 0):
        self.tweet = tweet
        self.width = width
        self.score = tweet.relevance_score
        self.is_superdunk = tweet.is_superdunk
        self.height = get_tile_height(self.score)
        self.tile_id = tile_id

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
            if self.is_superdunk:
                header.append("🎯 ", style="bold")
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 20), style="bold cyan")
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
            if self.is_superdunk:
                header.append("🎯 ", style="bold")
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 15), style="cyan")
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
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 12), style="cyan")
            if page_indicator:
                header.append(page_indicator, style="dim magenta")

            lines = [header]
            for line in page_lines[:available_content]:
                lines.append(Text(line, style="dim"))

            body = Text("\n").join(lines)

        else:
            body = Text()
            body.append(f"[{self.score}] ", style=f"{fg}")
            body.append(truncate(t.author_handle, content_width - 5), style="dim cyan")

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

        # Build header with proper cell-width truncation
        # Emoji (2 cells) + space (1 cell) = 3 cells prefix
        header = Text()
        header.append(f"{v.emoji} ", style="bold")
        topic_text = Text(v.topic, style="bold bright_magenta")
        topic_text.truncate(content_width - 3, overflow="ellipsis")
        header.append(topic_text)
        lines.append(header)

        # Vibe line with cell-aware truncation
        vibe_line = Text()
        vibe_text = Text(v.vibe, style="italic cyan")
        vibe_text.truncate(content_width - 6, overflow="ellipsis")  # Leave room for " (XX)"
        vibe_line.append(vibe_text)
        vibe_line.append(f" ({v.tweet_count})", style="dim")
        lines.append(vibe_line)

        # Description with cell-aware truncation
        desc_text = Text(v.description, style="white")
        desc_text.truncate(content_width * 2, overflow="ellipsis")  # Allow 2 lines worth
        lines.append(desc_text)

        body = Text("\n").join(lines)

        return Panel(
            body,
            box=box.ROUNDED,
            border_style="bright_magenta",
            width=self.width,
            height=6,
            padding=(0, 1),
        )


class MosaicDisplay:
    """Live mosaic display of filtered tweets."""

    def __init__(
        self,
        tweets: list[FilteredTweet],
        vibes: list[TopicVibe] | None = None,
        refresh_callback=None,
        refresh_interval: int = 300,
    ):
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.vibes = vibes or []
        self.console = Console()
        self.refresh_callback = refresh_callback
        self.refresh_interval = refresh_interval
        self.last_refresh = time.time()

    def create_tiles(self) -> list[MosaicTile]:
        """Create tiles for tweets."""
        tiles = []
        width = self.console.width

        for i, tweet in enumerate(self.tweets):
            if tweet.relevance_score >= 9:
                tile_width = min(width - 4, 80)
            elif tweet.relevance_score >= 7:
                tile_width = min(width - 4, 60)
            elif tweet.relevance_score >= 5:
                tile_width = min(width - 4, 50)
            else:
                tile_width = min(width - 4, 40)

            tiles.append(MosaicTile(tweet, tile_width, tile_id=i))

        return tiles

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
        elements.append(Align.center(Text("[q]uit  [r]efresh", style="dim")))

        return Group(*elements)

    def update_tweets(self, tweets: list[FilteredTweet], vibes: list[TopicVibe] | None = None):
        """Update with new tweets and vibes."""
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        if vibes is not None:
            self.vibes = vibes
        self.last_refresh = time.time()


async def run_mosaic(
    fetch_func,
    vibe_func=None,
    refresh_minutes: int = 5,
    count: int = 20,
    threshold: int = 5,
):
    """Run the mosaic display with periodic refresh."""
    console = Console()

    console.print("[dim]Fetching tweets for mosaic...[/dim]")
    tweets = await fetch_func(count, threshold)

    vibes = []
    if tweets and vibe_func:
        console.print("[dim]Analyzing vibe of the day...[/dim]")
        vibes = vibe_func(tweets)

    if not tweets:
        console.print("[yellow]No tweets found. Will retry on refresh.[/yellow]")

    mosaic = MosaicDisplay(
        tweets,
        vibes=vibes,
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
                        new_tweets = await fetch_func(count, threshold)
                        new_vibes = vibe_func(new_tweets) if vibe_func and new_tweets else []
                        if new_tweets:
                            mosaic.update_tweets(new_tweets, new_vibes)
                        last_refresh = now

                    # Auto refresh
                    if now - last_refresh >= refresh_minutes * 60:
                        new_tweets = await fetch_func(count, threshold)
                        new_vibes = vibe_func(new_tweets) if vibe_func and new_tweets else []
                        if new_tweets:
                            mosaic.update_tweets(new_tweets, new_vibes)
                        last_refresh = now

                    live.update(mosaic.render())
                    await asyncio.sleep(0.5)

            except KeyboardInterrupt:
                pass
    finally:
        keyboard.stop()

    console.print("\n[dim]Mosaic stopped.[/dim]")
