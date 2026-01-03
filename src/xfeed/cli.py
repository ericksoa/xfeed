"""CLI interface for XFeed."""

import asyncio
import json
import os
import subprocess
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from xfeed.config import (
    get_api_key,
    set_api_key,
    load_config,
    save_config,
    get_objectives_path,
    load_objectives,
    CONFIG_DIR,
)
from xfeed.filter import filter_tweets
from xfeed.models import FilteredTweet
from xfeed.scraper import scrape_timeline


console = Console()


def print_tweet(filtered_tweet: FilteredTweet) -> None:
    """Print a filtered tweet to the console."""
    tweet = filtered_tweet.tweet
    score = filtered_tweet.relevance_score
    reason = filtered_tweet.reason

    # Color based on score
    if score >= 9:
        score_color = "green"
    elif score >= 7:
        score_color = "yellow"
    else:
        score_color = "white"

    header = f"[bold]{tweet.author}[/bold] [dim]{tweet.author_handle}[/dim] · {tweet.formatted_time}"
    score_badge = f"[{score_color}][{score}/10][/{score_color}]"

    content = tweet.content
    if len(content) > 280:
        content = content[:277] + "..."

    footer_parts = []
    if tweet.likes:
        footer_parts.append(f"[red]♥[/red] {tweet.likes}")
    if tweet.retweets:
        footer_parts.append(f"↻ {tweet.retweets}")
    if tweet.replies:
        footer_parts.append(f"💬 {tweet.replies}")
    if tweet.has_media:
        footer_parts.append("📷")

    footer = "  ".join(footer_parts) if footer_parts else ""

    panel_content = f"{content}\n\n[dim]{footer}[/dim]\n[italic cyan]Why: {reason}[/italic cyan]"

    console.print(Panel(
        panel_content,
        title=f"{header}  {score_badge}",
        title_align="left",
        border_style="dim",
    ))
    console.print()


@click.group()
@click.version_option()
def main():
    """XFeed - Filter your X timeline based on your interests."""
    pass


@main.command()
@click.option("--count", "-n", default=50, help="Number of tweets to fetch")
@click.option("--threshold", "-t", type=int, help="Minimum relevance score (0-10)")
@click.option("--raw", is_flag=True, help="Show all tweets without filtering")
@click.option("--json-output", "--json", "json_output", is_flag=True, help="Output as JSON")
def fetch(count: int, threshold: int | None, raw: bool, json_output: bool):
    """Fetch and filter your X timeline."""
    # Check for API key if not in raw mode
    if not raw and not get_api_key():
        console.print(
            "[red]Error:[/red] Anthropic API key not configured.\n"
            "Add ANTHROPIC_API_KEY to .env file in the project directory."
        )
        sys.exit(1)

    # Fetch tweets
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching tweets from X...", total=None)

        try:
            tweets = asyncio.run(scrape_timeline(
                count=count,
                headless=True,
                on_progress=lambda current, total: progress.update(
                    task, description=f"Fetched {current}/{total} tweets..."
                ),
            ))
        except RuntimeError as e:
            progress.stop()
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

        progress.update(task, description=f"Fetched {len(tweets)} tweets")

    if not tweets:
        console.print("[yellow]No tweets found.[/yellow]")
        return

    # Filter tweets (unless raw mode)
    if raw:
        # In raw mode, wrap tweets in FilteredTweet with score 0
        filtered = [FilteredTweet(tweet=t, relevance_score=0, reason="Unfiltered") for t in tweets]
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Filtering with Claude Haiku...", total=None)

            filtered = filter_tweets(
                tweets,
                threshold=threshold,
                on_progress=lambda current, total: progress.update(
                    task, description=f"Analyzed {current}/{total} tweets..."
                ),
            )

            progress.update(task, description=f"Found {len(filtered)} relevant tweets")

    if not filtered:
        console.print("[yellow]No tweets matched your interests.[/yellow]")
        return

    # Output
    if json_output:
        output = []
        for ft in filtered:
            output.append({
                "id": ft.tweet.id,
                "author": ft.tweet.author,
                "author_handle": ft.tweet.author_handle,
                "content": ft.tweet.content,
                "timestamp": ft.tweet.timestamp.isoformat(),
                "url": ft.tweet.url,
                "relevance_score": ft.relevance_score,
                "relevance_reason": ft.reason,
            })
        click.echo(json.dumps(output, indent=2))
    else:
        console.print(f"\n[bold]Found {len(filtered)} relevant tweets:[/bold]\n")
        for ft in filtered:
            print_tweet(ft)


@main.command()
@click.option("--api-key", help="Set Anthropic API key")
@click.option("--threshold", type=int, help="Set default relevance threshold (0-10)")
@click.option("--show", is_flag=True, help="Show current configuration")
def config(api_key: str | None, threshold: int | None, show: bool):
    """Configure XFeed settings."""
    if show:
        cfg = load_config()
        table = Table(title="XFeed Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value")

        # Check for API key in environment (from .env)
        env_key = get_api_key()
        if env_key:
            api_val = env_key[:12] + "..." + env_key[-4:]
        else:
            api_val = "[red]Not set[/red]"

        table.add_row("Anthropic API Key", api_val)
        table.add_row("Relevance Threshold", str(cfg.get("relevance_threshold", 7)))
        table.add_row("Default Tweet Count", str(cfg.get("default_tweet_count", 50)))
        table.add_row("Batch Size", str(cfg.get("batch_size", 15)))
        table.add_row("Config Directory", str(CONFIG_DIR))

        console.print(table)
        return

    if api_key:
        set_api_key(api_key)
        console.print("[green]✓ API key saved[/green]")

    if threshold is not None:
        if not 0 <= threshold <= 10:
            console.print("[red]Error:[/red] Threshold must be between 0 and 10")
            sys.exit(1)
        cfg = load_config()
        cfg["relevance_threshold"] = threshold
        save_config(cfg)
        console.print(f"[green]✓ Threshold set to {threshold}[/green]")

    if not api_key and threshold is None and not show:
        # No options provided, show help
        ctx = click.get_current_context()
        click.echo(ctx.get_help())


@main.command()
@click.option("--edit", "-e", is_flag=True, help="Open objectives file in editor")
@click.option("--show", "-s", is_flag=True, help="Show current objectives")
def objectives(edit: bool, show: bool):
    """View or edit your objectives file."""
    objectives_path = get_objectives_path()

    if show or (not edit):
        content = load_objectives()
        console.print(Panel(content, title="Your Objectives", border_style="cyan"))
        console.print(f"\n[dim]File: {objectives_path}[/dim]")
        return

    if edit:
        editor = os.environ.get("EDITOR", "nano")
        try:
            subprocess.run([editor, str(objectives_path)])
            console.print(f"[green]✓ Objectives saved to {objectives_path}[/green]")
        except FileNotFoundError:
            console.print(f"[red]Error:[/red] Editor '{editor}' not found.")
            console.print(f"Edit manually: {objectives_path}")
            sys.exit(1)


if __name__ == "__main__":
    main()
