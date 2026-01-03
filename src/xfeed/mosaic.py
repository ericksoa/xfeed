"""Block mosaic visualization for X feed."""

import asyncio
import random
import time
from datetime import datetime

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.text import Text
from rich.table import Table
from rich.align import Align
from rich import box

from xfeed.models import FilteredTweet


# Block characters for visual density
BLOCKS = {
    "solid": "█",
    "dark": "▓",
    "medium": "▒",
    "light": "░",
    "empty": " ",
}

# Color palette based on relevance (heat map style)
COLORS = {
    10: ("bright_white", "on red"),
    9: ("bright_white", "on bright_red"),
    8: ("black", "on yellow"),
    7: ("black", "on bright_yellow"),
    6: ("white", "on blue"),
    5: ("white", "on bright_blue"),
    4: ("white", "on cyan"),
    3: ("white", "on bright_cyan"),
    2: ("white", "on bright_black"),
    1: ("bright_black", ""),
}


def get_block_style(score: int) -> tuple[str, str, str]:
    """Get block character, fg color, bg color based on score."""
    if score >= 9:
        return BLOCKS["solid"], "bright_white", "red"
    elif score >= 7:
        return BLOCKS["dark"], "bright_yellow", "yellow"
    elif score >= 5:
        return BLOCKS["medium"], "bright_blue", "blue"
    else:
        return BLOCKS["light"], "bright_black", "black"


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


class MosaicTile:
    """A single tile in the mosaic representing a tweet."""

    def __init__(self, tweet: FilteredTweet, width: int):
        self.tweet = tweet
        self.width = width
        self.score = tweet.relevance_score
        self.height = get_tile_height(self.score)
        self.age = 0  # For animation effects
        self.pulse = 0.0  # For pulse animation

    def render(self, animate_phase: float = 0) -> Panel:
        """Render this tile as a Rich Panel."""
        t = self.tweet.tweet
        block, fg, bg = get_block_style(self.score)

        # Determine border style based on score
        if self.score >= 9:
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

        # Build content based on tile size
        content_width = self.width - 4  # Account for borders

        if self.height >= 5:
            # Large tile: full content
            lines = []
            # Header
            header = Text()
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 20), style="bold cyan")
            header.append(f" · {t.formatted_time}", style="dim")
            lines.append(header)

            # Content (multiple lines)
            content = t.content.replace("\n", " ")
            remaining = content
            for _ in range(2):
                if remaining:
                    line_text = truncate(remaining, content_width)
                    lines.append(Text(line_text))
                    remaining = remaining[len(line_text):].strip()

            # Engagement
            eng = Text()
            if t.likes:
                eng.append(f"♥ {t.likes} ", style="red")
            if t.retweets:
                eng.append(f"↻ {t.retweets}", style="green")
            lines.append(eng)

            body = Text("\n").join(lines)

        elif self.height >= 3:
            # Medium tile: author + truncated content
            lines = []
            header = Text()
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 15), style="cyan")
            lines.append(header)

            content = truncate(t.content.replace("\n", " "), content_width)
            lines.append(Text(content, style="white"))

            body = Text("\n").join(lines)

        elif self.height >= 2:
            # Small tile: compact single line + author
            header = Text()
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 12), style="cyan")
            content = Text(truncate(t.content.replace("\n", " "), content_width - 5), style="dim")
            body = Text("\n").join([header, content])

        else:
            # Tiny tile: just score and handle
            body = Text()
            body.append(f"[{self.score}] ", style=f"{fg}")
            body.append(truncate(t.author_handle, content_width - 5), style="dim cyan")

        return Panel(
            body,
            box=box_type,
            border_style=border_style,
            width=self.width,
            height=self.height + 2,  # Account for top/bottom border
            padding=(0, 1),
        )


class MosaicDisplay:
    """Live mosaic display of filtered tweets."""

    def __init__(
        self,
        tweets: list[FilteredTweet],
        refresh_callback=None,
        refresh_interval: int = 300,
    ):
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.console = Console()
        self.refresh_callback = refresh_callback
        self.refresh_interval = refresh_interval
        self.last_refresh = time.time()
        self.animation_phase = 0.0
        self.width = self.console.width
        self.height = self.console.height

    def create_tiles(self) -> list[MosaicTile]:
        """Create tiles for all tweets."""
        tiles = []
        for tweet in self.tweets:
            # Width varies by score too
            if tweet.relevance_score >= 9:
                width = min(self.width - 2, 80)
            elif tweet.relevance_score >= 7:
                width = min(self.width - 2, 60)
            elif tweet.relevance_score >= 5:
                width = min(self.width - 2, 50)
            else:
                width = min(self.width - 2, 40)

            tiles.append(MosaicTile(tweet, width))
        return tiles

    def render_header(self) -> Text:
        """Render the header bar."""
        now = datetime.now().strftime("%H:%M:%S")
        next_refresh = max(0, self.refresh_interval - (time.time() - self.last_refresh))

        header = Text()
        header.append("▄" * 20, style="bright_red")
        header.append(" XFEED MOSAIC ", style="bold white on red")
        header.append("▄" * 20, style="bright_red")
        header.append(f"  {now}", style="dim")
        header.append(f"  │  refresh in {int(next_refresh)}s", style="dim")
        header.append(f"  │  {len(self.tweets)} tweets", style="dim")

        return header

    def render_legend(self) -> Text:
        """Render a legend showing score-to-size mapping."""
        legend = Text()
        legend.append("█ 9-10 ", style="red")
        legend.append("▓ 7-8 ", style="yellow")
        legend.append("▒ 5-6 ", style="blue")
        legend.append("░ <5", style="dim")
        return legend

    def render(self) -> Group:
        """Render the full mosaic display."""
        tiles = self.create_tiles()

        elements: list[RenderableType] = [
            Align.center(self.render_header()),
            Text(),
        ]

        if not tiles:
            elements.append(
                Align.center(Text("No tweets to display...", style="dim italic"))
            )
        else:
            # Arrange tiles - larger ones centered, smaller ones grouped
            large_tiles = [t for t in tiles if t.score >= 9]
            medium_tiles = [t for t in tiles if 7 <= t.score < 9]
            small_tiles = [t for t in tiles if t.score < 7]

            # Render large tiles (centered, full width)
            for tile in large_tiles[:3]:  # Max 3 large tiles
                elements.append(Align.center(tile.render(self.animation_phase)))

            # Render medium tiles in a row
            if medium_tiles:
                # Create a table for side-by-side layout
                table = Table.grid(padding=1)
                table.add_column()
                table.add_column()

                for i in range(0, len(medium_tiles[:6]), 2):
                    row = [medium_tiles[i].render(self.animation_phase)]
                    if i + 1 < len(medium_tiles[:6]):
                        row.append(medium_tiles[i + 1].render(self.animation_phase))
                    table.add_row(*row)

                elements.append(Align.center(table))

            # Render small tiles compactly
            if small_tiles:
                small_table = Table.grid(padding=0)
                for _ in range(3):
                    small_table.add_column()

                for i in range(0, len(small_tiles[:9]), 3):
                    row = [small_tiles[i].render(self.animation_phase)]
                    for j in range(1, 3):
                        if i + j < len(small_tiles[:9]):
                            row.append(small_tiles[i + j].render(self.animation_phase))
                    small_table.add_row(*row)

                elements.append(Align.center(small_table))

        # Footer with legend
        elements.append(Text())
        elements.append(Align.center(self.render_legend()))
        elements.append(Align.center(Text("Press Ctrl+C to exit", style="dim")))

        return Group(*elements)

    def update_tweets(self, tweets: list[FilteredTweet]):
        """Update with new tweets."""
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.last_refresh = time.time()


async def run_mosaic(
    fetch_func,
    refresh_minutes: int = 5,
    count: int = 20,
    threshold: int = 5,
):
    """
    Run the mosaic display with periodic refresh.

    Args:
        fetch_func: Async function that returns list[FilteredTweet]
        refresh_minutes: Minutes between feed refresh
        count: Number of tweets to fetch
        threshold: Relevance threshold
    """
    console = Console()

    # Initial fetch
    console.print("[dim]Fetching tweets for mosaic...[/dim]")
    tweets = await fetch_func(count, threshold)

    if not tweets:
        console.print("[yellow]No tweets found. Will retry on refresh.[/yellow]")

    mosaic = MosaicDisplay(
        tweets,
        refresh_callback=fetch_func,
        refresh_interval=refresh_minutes * 60,
    )

    last_refresh = time.time()

    with Live(mosaic.render(), console=console, refresh_per_second=2, screen=True) as live:
        try:
            while True:
                now = time.time()

                # Check for refresh
                if now - last_refresh >= refresh_minutes * 60:
                    new_tweets = await fetch_func(count, threshold)
                    if new_tweets:
                        mosaic.update_tweets(new_tweets)
                    last_refresh = now

                # Update animation phase
                mosaic.animation_phase = (now % 2) / 2  # 0-1 cycle every 2 seconds

                # Update display
                live.update(mosaic.render())

                await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            pass

    console.print("\n[dim]Mosaic stopped.[/dim]")
