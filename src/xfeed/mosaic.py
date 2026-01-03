"""Block mosaic visualization for X feed using Textual."""

import asyncio
import time
import webbrowser
from datetime import datetime

from rich.console import RenderableType
from rich.panel import Panel
from rich.text import Text
from rich import box

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Header, Footer
from textual.reactive import reactive
from textual.binding import Binding

from xfeed.models import FilteredTweet, TopicVibe


# Color palette based on relevance (heat map style)
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
        return 7
    elif score >= 7:
        return 5
    elif score >= 5:
        return 4
    else:
        return 3


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis."""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def wrap_text(text: str, width: int, max_lines: int) -> list[str]:
    """Wrap text to fit width, limited to max_lines."""
    text = text.replace("\n", " ").strip()
    words = text.split()

    lines = []
    current_line = ""

    for word in words:
        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= width:
            current_line += " " + word
        else:
            lines.append(current_line)
            if len(lines) >= max_lines:
                # Add ellipsis to last line if truncated
                if lines[-1] and len(lines[-1]) < width - 1:
                    lines[-1] += "…"
                return lines
            current_line = word

    if current_line and len(lines) < max_lines:
        lines.append(current_line)

    return lines


class TweetTile(Static):
    """A clickable tweet tile widget."""

    def __init__(
        self,
        tweet: FilteredTweet,
        tile_width: int = 60,
        tile_height: int = 5,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.tweet = tweet
        self.tile_width = tile_width
        self.tile_height = tile_height
        self.score = tweet.relevance_score
        self.is_superdunk = tweet.is_superdunk

    def on_click(self) -> None:
        """Open the tweet in browser when clicked."""
        url = self.tweet.tweet.url
        if url:
            webbrowser.open(url)
            self.notify(f"Opening tweet by {self.tweet.tweet.author_handle}...")

    def render(self) -> RenderableType:
        """Render this tile as a Rich Panel."""
        t = self.tweet.tweet
        block, fg, bg = get_block_style(self.score)

        # Determine border style based on score and superdunk status
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

        # Build content based on tile size
        content_width = self.tile_width - 6
        content_lines = max(1, self.tile_height - 2)

        lines = []

        # Header
        header = Text()
        if self.is_superdunk:
            header.append("🎯 ", style="bold")
        header.append(f"[{self.score}] ", style=f"bold {fg}")
        header.append(truncate(t.author_handle, 20), style="bold cyan")
        header.append(f" · {t.formatted_time}", style="dim")
        header.append(" 🔗", style="dim blue")  # Click hint
        lines.append(header)

        # Content
        if self.is_superdunk and t.quoted_tweet:
            # Show quoted tweet first
            quoted_text = f"💬 {t.quoted_tweet.author_handle}: {t.quoted_tweet.content}"
            content_text = f"🎯 {t.content}"
            full_text = quoted_text + " → " + content_text
        else:
            full_text = t.content

        wrapped = wrap_text(full_text, content_width, content_lines - 1)
        for line in wrapped:
            lines.append(Text(line, style="white"))

        # Pad if needed
        while len(lines) < content_lines:
            lines.append(Text(""))

        # Engagement (for larger tiles)
        if self.tile_height >= 5:
            eng = Text()
            if t.likes:
                eng.append(f"♥ {t.likes} ", style="red")
            if t.retweets:
                eng.append(f"↻ {t.retweets}", style="green")
            lines.append(eng)

        body = Text("\n").join(lines)

        return Panel(
            body,
            box=box_type,
            border_style=border_style,
            width=self.tile_width,
            height=self.tile_height + 2,
            padding=(0, 1),
        )


class VibeCard(Static):
    """A card displaying a topic vibe."""

    def __init__(self, vibe: TopicVibe, width: int = 35, **kwargs):
        super().__init__(**kwargs)
        self.vibe = vibe
        self.card_width = width

    def render(self) -> RenderableType:
        """Render this vibe card."""
        v = self.vibe
        lines = []

        # Topic header with emoji
        header = Text()
        header.append(f"{v.emoji} ", style="bold")
        header.append(truncate(v.topic, self.card_width - 8), style="bold bright_magenta")
        lines.append(header)

        # Vibe sentiment
        vibe_line = Text()
        vibe_line.append(v.vibe, style="italic cyan")
        vibe_line.append(f" ({v.tweet_count})", style="dim")
        lines.append(vibe_line)

        # Description (wrapped)
        desc_lines = wrap_text(v.description, self.card_width - 4, 2)
        for line in desc_lines:
            lines.append(Text(line, style="white"))

        body = Text("\n").join(lines)

        return Panel(
            body,
            box=box.ROUNDED,
            border_style="bright_magenta",
            width=self.card_width,
            height=6,
            padding=(0, 1),
        )


class MosaicApp(App):
    """Textual app for mosaic tweet display."""

    CSS = """
    Screen {
        background: $surface;
    }

    #header-bar {
        dock: top;
        height: 3;
        background: $error;
        color: $text;
        text-align: center;
        padding: 1;
    }

    #legend {
        dock: bottom;
        height: 3;
        background: $surface-darken-1;
        color: $text-muted;
        text-align: center;
        padding: 1;
    }

    #vibe-section {
        height: auto;
        align: center middle;
        margin: 1 0;
    }

    #vibe-header {
        text-align: center;
        margin-bottom: 1;
    }

    .vibe-row {
        align: center middle;
        height: auto;
    }

    VibeCard {
        margin: 0 1;
    }

    #main-container {
        align: center middle;
    }

    .tile-row {
        align: center middle;
        height: auto;
        margin-bottom: 1;
    }

    TweetTile {
        margin: 0 1;
    }

    TweetTile:hover {
        background: $primary-background;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(
        self,
        tweets: list[FilteredTweet],
        vibes: list[TopicVibe] | None = None,
        fetch_func=None,
        vibe_func=None,
        refresh_minutes: int = 5,
        count: int = 20,
        threshold: int = 5,
    ):
        super().__init__()
        self.tweets = sorted(tweets, key=lambda x: x.relevance_score, reverse=True)
        self.vibes = vibes or []
        self.fetch_func = fetch_func
        self.vibe_func = vibe_func
        self.refresh_minutes = refresh_minutes
        self.count = count
        self.threshold = threshold
        self.last_refresh = time.time()

    def compose(self) -> ComposeResult:
        """Compose the app layout."""
        yield Static(self._render_header(), id="header-bar")

        with ScrollableContainer(id="main-container"):
            # Vibe section at the top
            if self.vibes:
                yield from self._compose_vibe_section()

            # Tweet tiles
            yield from self._compose_tiles()

        yield Static(self._render_legend(), id="legend")

    def _compose_vibe_section(self) -> ComposeResult:
        """Compose the vibe of the day section."""
        # Header
        vibe_header = Text()
        vibe_header.append("💭 ", style="bold")
        vibe_header.append("VIBE OF THE DAY", style="bold bright_magenta")
        yield Static(vibe_header, id="vibe-header")

        # Vibe cards in a row
        with Horizontal(classes="vibe-row"):
            for vibe in self.vibes[:3]:
                yield VibeCard(vibe, width=38)

    def _render_header(self) -> Text:
        """Render the header bar."""
        now = datetime.now().strftime("%H:%M:%S")
        header = Text()
        header.append("▄" * 15, style="bright_red")
        header.append(" XFEED MOSAIC ", style="bold white")
        header.append("▄" * 15, style="bright_red")
        header.append(f"  {now}", style="dim")
        header.append(f"  │  {len(self.tweets)} tweets", style="dim")
        header.append("  │  Click tile to open", style="dim cyan")
        return header

    def _render_legend(self) -> Text:
        """Render the legend."""
        legend = Text()
        legend.append("█ 9-10 ", style="red")
        legend.append("▓ 7-8 ", style="yellow")
        legend.append("▒ 5-6 ", style="blue")
        legend.append("░ <5 ", style="dim")
        legend.append("│ ", style="dim")
        legend.append("🎯 superdunk ", style="bright_green")
        legend.append("│ ", style="dim")
        legend.append("[q]uit  [r]efresh", style="dim cyan")
        return legend

    def _compose_tiles(self) -> ComposeResult:
        """Compose tweet tiles."""
        if not self.tweets:
            yield Static("No tweets to display...", classes="tile-row")
            return

        # Categorize tweets
        large_tweets = [t for t in self.tweets if t.relevance_score >= 9][:3]
        medium_tweets = [t for t in self.tweets if 7 <= t.relevance_score < 9][:6]
        small_tweets = [t for t in self.tweets if t.relevance_score < 7][:9]

        # Large tiles (full width, one per row)
        for tweet in large_tweets:
            with Horizontal(classes="tile-row"):
                yield TweetTile(
                    tweet,
                    tile_width=80,
                    tile_height=get_tile_height(tweet.relevance_score),
                )

        # Medium tiles (2 per row)
        for i in range(0, len(medium_tweets), 2):
            with Horizontal(classes="tile-row"):
                yield TweetTile(
                    medium_tweets[i],
                    tile_width=55,
                    tile_height=get_tile_height(medium_tweets[i].relevance_score),
                )
                if i + 1 < len(medium_tweets):
                    yield TweetTile(
                        medium_tweets[i + 1],
                        tile_width=55,
                        tile_height=get_tile_height(medium_tweets[i + 1].relevance_score),
                    )

        # Small tiles (3 per row)
        for i in range(0, len(small_tweets), 3):
            with Horizontal(classes="tile-row"):
                for j in range(3):
                    if i + j < len(small_tweets):
                        yield TweetTile(
                            small_tweets[i + j],
                            tile_width=40,
                            tile_height=get_tile_height(small_tweets[i + j].relevance_score),
                        )

    async def action_refresh(self) -> None:
        """Refresh tweets from the feed."""
        if self.fetch_func:
            self.notify("Refreshing feed...")
            try:
                new_tweets = await self.fetch_func(self.count, self.threshold)
                if new_tweets:
                    self.tweets = sorted(new_tweets, key=lambda x: x.relevance_score, reverse=True)
                    # Also refresh vibes if function provided
                    if self.vibe_func:
                        self.vibes = self.vibe_func(self.tweets)
                    self.last_refresh = time.time()
                    # Rebuild the UI
                    await self._rebuild_tiles()
                    self.notify(f"Loaded {len(new_tweets)} tweets")
                else:
                    self.notify("No new tweets found", severity="warning")
            except Exception as e:
                self.notify(f"Refresh failed: {e}", severity="error")

    async def _rebuild_tiles(self) -> None:
        """Rebuild the tile display."""
        container = self.query_one("#main-container")
        await container.remove_children()

        # Rebuild vibe section if we have vibes
        if self.vibes:
            for widget in self._compose_vibe_section():
                await container.mount(widget)

        # Rebuild tweet tiles
        for widget in self._compose_tiles():
            await container.mount(widget)

        # Update header
        header = self.query_one("#header-bar", Static)
        header.update(self._render_header())


async def run_mosaic(
    fetch_func,
    vibe_func=None,
    refresh_minutes: int = 5,
    count: int = 20,
    threshold: int = 5,
):
    """
    Run the mosaic display.

    Args:
        fetch_func: Async function that returns list[FilteredTweet]
        vibe_func: Function that takes tweets and returns list[TopicVibe]
        refresh_minutes: Minutes between feed refresh
        count: Number of tweets to fetch
        threshold: Relevance threshold
    """
    from rich.console import Console
    console = Console()

    # Initial fetch
    console.print("[dim]Fetching tweets for mosaic...[/dim]")
    tweets = await fetch_func(count, threshold)

    if not tweets:
        console.print("[yellow]No tweets found.[/yellow]")
        tweets = []

    # Extract vibes from tweets
    vibes = []
    if tweets and vibe_func:
        console.print("[dim]Analyzing vibe of the day...[/dim]")
        vibes = vibe_func(tweets)

    app = MosaicApp(
        tweets,
        vibes=vibes,
        fetch_func=fetch_func,
        vibe_func=vibe_func,
        refresh_minutes=refresh_minutes,
        count=count,
        threshold=threshold,
    )

    await app.run_async()
