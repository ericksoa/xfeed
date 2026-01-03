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


def get_base_tile_height(score: int) -> int:
    """Get minimum tile height based on relevance score."""
    if score >= 9:
        return 5
    elif score >= 7:
        return 3
    elif score >= 5:
        return 2
    else:
        return 1


def get_tile_height(score: int, bonus: int = 0) -> int:
    """Get tile height with optional bonus for extra space."""
    return get_base_tile_height(score) + bonus


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

    # Split lines into pages
    pages = []
    for i in range(0, len(all_lines), lines_per_page):
        pages.append(all_lines[i:i + lines_per_page])

    return pages if pages else [[]]


class MosaicTile:
    """A single tile in the mosaic representing a tweet."""

    PAGE_DURATION = 3.0  # seconds per page

    def __init__(self, tweet: FilteredTweet, width: int, tile_id: int = 0, height_bonus: int = 0):
        self.tweet = tweet
        self.width = width
        self.score = tweet.relevance_score
        self.is_superdunk = tweet.is_superdunk
        self.base_height = get_base_tile_height(self.score)
        self.height = self.base_height + height_bonus
        self.tile_id = tile_id  # Used to stagger page timing

        # Pre-compute pages based on tile size (use actual height for content capacity)
        content_width = self.width - 6  # Account for borders and padding
        content_lines = max(1, self.height - 2)  # Lines available for content (minus header/footer)

        # For superdunks, include the quoted content as context
        if self.is_superdunk and tweet.tweet.quoted_tweet:
            # First page(s): the quoted tweet (the bad take)
            quoted = tweet.tweet.quoted_tweet
            quoted_prefix = f"💬 {quoted.author_handle}: {quoted.content}"
            self.quoted_pages = split_into_pages(quoted_prefix, content_width, content_lines)

            # Following page(s): the dunk (the reply)
            dunk_prefix = f"🎯 {tweet.tweet.content}"
            self.dunk_pages = split_into_pages(dunk_prefix, content_width, content_lines)

            # Combine: show quoted first, then dunk
            self.pages = self.quoted_pages + self.dunk_pages
        else:
            self.pages = split_into_pages(
                tweet.tweet.content,
                content_width,
                content_lines
            )
            self.quoted_pages = []
            self.dunk_pages = []

        self.total_pages = len(self.pages)

    def get_current_page(self, time_now: float) -> int:
        """Get current page index based on time, staggered by tile_id."""
        if self.total_pages <= 1:
            return 0
        # Stagger each tile by 0.5 seconds based on tile_id
        offset_time = time_now + (self.tile_id * 0.5)
        cycle_position = (offset_time / self.PAGE_DURATION) % self.total_pages
        return int(cycle_position)

    def render(self, time_now: float = 0) -> Panel:
        """Render this tile as a Rich Panel."""
        t = self.tweet.tweet
        block, fg, bg = get_block_style(self.score)

        # Determine border style based on score and superdunk status
        if self.is_superdunk:
            # Special treatment for superdunks - green/teal with double border
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

        # Get current page
        current_page = self.get_current_page(time_now)
        page_lines = self.pages[current_page] if current_page < len(self.pages) else []

        # Page indicator (only show if multiple pages)
        page_indicator = ""
        if self.total_pages > 1:
            page_indicator = f" [{current_page + 1}/{self.total_pages}]"

        # Build content based on tile size (use base_height for style, height for capacity)
        content_width = self.width - 4  # Account for borders

        if self.base_height >= 5:
            # Large tile: header + paged content + engagement
            # Available content lines = height - 2 (header + engagement)
            available_content = max(1, self.height - 2)
            lines = []

            # Header with page indicator
            header = Text()
            if self.is_superdunk:
                header.append("🎯 ", style="bold")
            header.append(f"[{self.score}] ", style=f"bold {fg}")
            header.append(truncate(t.author_handle, 20), style="bold cyan")
            header.append(f" · {t.formatted_time}", style="dim")
            if page_indicator:
                header.append(page_indicator, style="dim magenta")
            lines.append(header)

            # Content from current page
            for line in page_lines[:available_content]:
                lines.append(Text(line, style="white"))

            # Pad with empty lines if needed (total = 1 header + available_content + 1 engagement)
            while len(lines) < available_content + 1:
                lines.append(Text(""))

            # Engagement
            eng = Text()
            if t.likes:
                eng.append(f"♥ {t.likes} ", style="red")
            if t.retweets:
                eng.append(f"↻ {t.retweets}", style="green")
            lines.append(eng)

            body = Text("\n").join(lines)

        elif self.base_height >= 3:
            # Medium tile: header + paged content (no engagement line)
            # Available content lines = height - 1 (just header)
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

            # Content from current page
            for line in page_lines[:available_content]:
                lines.append(Text(line, style="white"))

            # Pad if needed
            while len(lines) < self.height:
                lines.append(Text(""))

            body = Text("\n").join(lines)

        elif self.base_height >= 2:
            # Small tile: header + content lines
            # Available content lines = height - 1 (just header)
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
            # Tiny tile: just score and handle (no paging)
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

    def create_tiles(self, available_height: int = 100) -> list[MosaicTile]:
        """Create tiles for all tweets, expanding if extra space available."""
        if not self.tweets:
            return []

        # First pass: calculate minimum heights and categorize
        large_tweets = [t for t in self.tweets if t.relevance_score >= 9][:3]
        medium_tweets = [t for t in self.tweets if 7 <= t.relevance_score < 9][:6]
        small_tweets = [t for t in self.tweets if t.relevance_score < 7][:9]

        all_visible = large_tweets + medium_tweets + small_tweets

        # Calculate minimum height needed
        min_height = 0
        for tweet in large_tweets:
            min_height += get_base_tile_height(tweet.relevance_score) + 3  # +2 border +1 spacing
        # Medium tiles in rows of 2
        medium_rows = (len(medium_tweets) + 1) // 2
        min_height += medium_rows * 6
        # Small tiles in rows of 3
        small_rows = (len(small_tweets) + 2) // 3
        min_height += small_rows * 5

        # Calculate extra height to distribute
        extra_height = max(0, available_height - min_height)

        # Distribute extra height to tiles (prioritize by score)
        # Give bonus lines to tiles that would benefit most
        height_bonuses = {}
        if extra_height > 0 and all_visible:
            # Give more bonus to higher-scored tweets
            remaining = extra_height
            for tweet in sorted(all_visible, key=lambda t: t.relevance_score, reverse=True):
                if remaining <= 0:
                    break
                # Give up to 3 bonus lines per tile
                bonus = min(3, remaining)
                height_bonuses[tweet.tweet.id] = bonus
                remaining -= bonus

        # Second pass: create tiles with bonuses
        tiles = []
        for i, tweet in enumerate(self.tweets):
            # Width varies by score
            if tweet.relevance_score >= 9:
                width = min(self.width - 2, 80)
            elif tweet.relevance_score >= 7:
                width = min(self.width - 2, 60)
            elif tweet.relevance_score >= 5:
                width = min(self.width - 2, 50)
            else:
                width = min(self.width - 2, 40)

            bonus = height_bonuses.get(tweet.tweet.id, 0)
            tiles.append(MosaicTile(tweet, width, tile_id=i, height_bonus=bonus))

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
        legend.append("░ <5 ", style="dim")
        legend.append("│ ", style="dim")
        legend.append("🎯 superdunk", style="bright_green")
        return legend

    def render(self) -> Group:
        """Render the full mosaic display, respecting terminal bounds."""
        now = time.time()

        # Get current terminal dimensions
        term_height = self.console.height
        term_width = self.console.width

        # Reserve space for header (2 lines), footer (3 lines), and some padding
        HEADER_LINES = 2
        FOOTER_LINES = 3
        PADDING = 2
        available_height = term_height - HEADER_LINES - FOOTER_LINES - PADDING

        # Create tiles with height expansion based on available space
        tiles = self.create_tiles(available_height)

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

            used_height = 0
            shown_count = 0
            total_count = len(tiles)

            # Render large tiles (centered, full width)
            for tile in large_tiles[:3]:  # Max 3 large tiles
                tile_height = tile.height + 2  # Panel adds 2 for borders
                if used_height + tile_height <= available_height:
                    elements.append(Align.center(tile.render(now)))
                    used_height += tile_height + 1  # +1 for spacing
                    shown_count += 1

            # Render medium tiles in rows (use actual tile heights)
            if medium_tiles:
                table = Table.grid(padding=1)
                table.add_column()
                table.add_column()

                added_medium = 0
                for i in range(0, len(medium_tiles), 2):
                    # Get actual height of tallest tile in this row
                    row_height = medium_tiles[i].height + 3  # +2 border +1 padding
                    if i + 1 < len(medium_tiles):
                        row_height = max(row_height, medium_tiles[i + 1].height + 3)

                    if used_height + row_height > available_height:
                        break

                    row = [medium_tiles[i].render(now)]
                    shown_count += 1
                    added_medium += 1
                    if i + 1 < len(medium_tiles):
                        row.append(medium_tiles[i + 1].render(now))
                        shown_count += 1
                        added_medium += 1
                    table.add_row(*row)
                    used_height += row_height

                if added_medium > 0:
                    elements.append(Align.center(table))

            # Render small tiles compactly (use actual tile heights)
            if small_tiles:
                small_table = Table.grid(padding=0)
                for _ in range(3):
                    small_table.add_column()

                added_small = 0
                for i in range(0, len(small_tiles), 3):
                    # Get actual height of tallest tile in this row
                    row_height = small_tiles[i].height + 3
                    for j in range(1, 3):
                        if i + j < len(small_tiles):
                            row_height = max(row_height, small_tiles[i + j].height + 3)

                    if used_height + row_height > available_height:
                        break

                    row = [small_tiles[i].render(now)]
                    shown_count += 1
                    added_small += 1
                    for j in range(1, 3):
                        if i + j < len(small_tiles):
                            row.append(small_tiles[i + j].render(now))
                            shown_count += 1
                            added_small += 1
                    small_table.add_row(*row)
                    used_height += row_height

                if added_small > 0:
                    elements.append(Align.center(small_table))

            # Show indicator if some tweets are hidden
            hidden_count = total_count - shown_count
            if hidden_count > 0:
                elements.append(
                    Align.center(Text(f"  +{hidden_count} more tweets (resize terminal to see)", style="dim italic"))
                )

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

                # Update display
                live.update(mosaic.render())

                await asyncio.sleep(0.5)

        except KeyboardInterrupt:
            pass

    console.print("\n[dim]Mosaic stopped.[/dim]")
