"""CNN-style rotating ticker display for X feed."""

import asyncio
import time
from datetime import datetime

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, BarColumn, TextColumn
from rich.style import Style
from rich.text import Text
from rich.align import Align

from xfeed.models import FilteredTweet


# Progress bar characters
FILLED = "▰"
EMPTY = "▱"


def format_engagement(likes: int, retweets: int) -> str:
    """Format engagement numbers compactly."""
    def fmt(n: int) -> str:
        if n >= 1000000:
            return f"{n/1000000:.1f}M"
        elif n >= 1000:
            return f"{n/1000:.1f}K"
        return str(n)

    parts = []
    if likes:
        parts.append(f"♥ {fmt(likes)}")
    if retweets:
        parts.append(f"↻ {fmt(retweets)}")
    return "  ".join(parts) if parts else ""


def create_progress_bar(elapsed: float, total: float, width: int = 12) -> str:
    """Create a visual progress bar."""
    progress = min(elapsed / total, 1.0)
    filled = int(progress * width)
    return FILLED * filled + EMPTY * (width - filled)


class TickerDisplay:
    """CNN-style rotating ticker for filtered tweets."""

    def __init__(
        self,
        tweets: list[FilteredTweet],
        rotate_seconds: int = 5,
        refresh_minutes: int = 5,
    ):
        self.tweets = tweets
        self.current_index = 0
        self.rotate_seconds = rotate_seconds
        self.refresh_minutes = refresh_minutes
        self.last_refresh = datetime.now()
        self.console = Console()
        self.transition_phase = 0  # 0 = normal, 1-3 = transitioning

    def get_score_style(self, score: int) -> Style:
        """Get color style based on relevance score."""
        if score >= 9:
            return Style(color="green", bold=True)
        elif score >= 7:
            return Style(color="yellow", bold=True)
        else:
            return Style(color="white")

    def render_tweet(self, ft: FilteredTweet, opacity: float = 1.0) -> Panel:
        """Render a single tweet as a panel."""
        tweet = ft.tweet
        score = ft.relevance_score

        # Adjust style based on opacity (for transitions)
        if opacity < 0.5:
            text_style = Style(dim=True)
            score_style = Style(dim=True)
        elif opacity < 1.0:
            text_style = Style()
            score_style = self.get_score_style(score)
        else:
            text_style = Style()
            score_style = self.get_score_style(score)

        # Header with author and score
        header = Text()
        header.append(f"{tweet.author_handle}", style="bold cyan" if opacity >= 0.5 else "dim")
        header.append(f" · {tweet.formatted_time}", style="dim")
        header.append("  ")
        header.append(f"[{score}/10]", style=score_style)

        # Tweet content (truncate to ~140 chars for compact display)
        content = tweet.content
        if len(content) > 140:
            content = content[:137] + "..."

        content_text = Text(content, style=text_style)

        # Combine header and content
        body = Text()
        body.append_text(header)
        body.append("\n")
        body.append_text(content_text)

        return Panel(
            body,
            border_style="dim" if opacity < 1.0 else "blue",
            padding=(0, 1),
        )

    def render_status_bar(self, elapsed: float) -> Text:
        """Render the bottom status bar."""
        remaining = max(0, self.rotate_seconds - elapsed)
        progress = create_progress_bar(elapsed, self.rotate_seconds)

        # Position indicator
        pos = f"[{self.current_index + 1}/{len(self.tweets)}]"

        # Engagement for current tweet
        if self.tweets:
            ft = self.tweets[self.current_index]
            engagement = format_engagement(ft.tweet.likes, ft.tweet.retweets)
        else:
            engagement = ""

        # Time until next refresh
        mins_since_refresh = (datetime.now() - self.last_refresh).seconds // 60
        mins_until_refresh = max(0, self.refresh_minutes - mins_since_refresh)

        status = Text()
        status.append(progress, style="cyan")
        status.append(f"  Next: {remaining:.0f}s", style="dim")
        status.append(f"  │  Refresh: {mins_until_refresh}min", style="dim")
        if engagement:
            status.append(f"  │  {engagement}", style="dim")
        status.append(f"  {pos}", style="bold")

        return status

    def render_header(self) -> Text:
        """Render the top header bar."""
        header = Text()
        header.append("═" * 20, style="blue")
        header.append(" X FEED ", style="bold white on blue")
        header.append("═" * 20, style="blue")
        return header

    def render(self, elapsed: float) -> Group:
        """Render the complete ticker display."""
        if not self.tweets:
            return Group(
                self.render_header(),
                Text("\nNo relevant tweets found.\n", style="dim italic"),
                Text("Waiting for refresh...", style="dim"),
            )

        # Calculate opacity for transition effect
        if elapsed > self.rotate_seconds - 0.3:
            # Fade out
            opacity = max(0.3, (self.rotate_seconds - elapsed) / 0.3)
        elif elapsed < 0.3:
            # Fade in
            opacity = min(1.0, 0.3 + elapsed / 0.3 * 0.7)
        else:
            opacity = 1.0

        current_tweet = self.tweets[self.current_index]

        return Group(
            Align.center(self.render_header()),
            self.render_tweet(current_tweet, opacity),
            self.render_status_bar(elapsed),
        )

    def advance(self):
        """Move to the next tweet."""
        if self.tweets:
            self.current_index = (self.current_index + 1) % len(self.tweets)

    def update_tweets(self, tweets: list[FilteredTweet]):
        """Update the tweet list (called on refresh)."""
        self.tweets = tweets
        self.current_index = 0
        self.last_refresh = datetime.now()


async def run_ticker(
    fetch_func,
    rotate_seconds: int = 5,
    refresh_minutes: int = 5,
    count: int = 20,
    threshold: int = 7,
):
    """
    Run the ticker display with periodic refresh.

    Args:
        fetch_func: Async function that returns list[FilteredTweet]
        rotate_seconds: Seconds between tweet rotation
        refresh_minutes: Minutes between feed refresh
        count: Number of tweets to fetch
        threshold: Relevance threshold
    """
    console = Console()

    # Initial fetch
    console.print("[dim]Fetching initial tweets...[/dim]")
    tweets = await fetch_func(count, threshold)

    if not tweets:
        console.print("[yellow]No relevant tweets found. Will retry on refresh.[/yellow]")

    ticker = TickerDisplay(tweets, rotate_seconds, refresh_minutes)

    last_rotate = time.time()
    last_refresh = time.time()

    with Live(ticker.render(0), console=console, refresh_per_second=10, screen=True) as live:
        try:
            while True:
                now = time.time()
                elapsed_rotate = now - last_rotate
                elapsed_refresh = now - last_refresh

                # Check if we need to rotate
                if elapsed_rotate >= rotate_seconds:
                    ticker.advance()
                    last_rotate = now
                    elapsed_rotate = 0

                # Check if we need to refresh
                if elapsed_refresh >= refresh_minutes * 60:
                    # Fetch new tweets in background
                    new_tweets = await fetch_func(count, threshold)
                    if new_tweets:
                        ticker.update_tweets(new_tweets)
                    last_refresh = now

                # Update display
                live.update(ticker.render(elapsed_rotate))

                await asyncio.sleep(0.1)

        except KeyboardInterrupt:
            pass

    console.print("\n[dim]Ticker stopped.[/dim]")
