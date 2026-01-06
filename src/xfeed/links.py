"""Link expansion - fetch and summarize linked articles."""

import asyncio
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from xfeed.config import CONFIG_DIR, ensure_config_dir, get_api_key

# Cache settings
CACHE_DB = CONFIG_DIR / "links.db"
CACHE_EXPIRY_DAYS = 7

# URL patterns to skip (images, videos, twitter links, etc.)
SKIP_DOMAINS = {
    "twitter.com", "x.com", "t.co",  # Twitter itself
    "youtube.com", "youtu.be",  # Video
    "imgur.com", "giphy.com",  # Images
    "instagram.com", "tiktok.com",  # Social media
}

SKIP_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".mp4", ".webp", ".svg"}

# URL regex pattern
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)


class LinkCache:
    """SQLite cache for link summaries."""

    def __init__(self, db_path: Path | None = None):
        ensure_config_dir()
        self.db_path = db_path or CACHE_DB
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the cache table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS link_summaries (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    summary TEXT,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get(self, url: str) -> dict | None:
        """Get cached summary for URL, or None if not cached/expired."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT title, summary, fetched_at FROM link_summaries WHERE url = ?",
                (url,)
            ).fetchone()

            if not row:
                return None

            # Check expiry
            fetched_at = datetime.fromisoformat(row[2])
            if datetime.now() - fetched_at > timedelta(days=CACHE_EXPIRY_DAYS):
                return None

            return {"title": row[0], "summary": row[1]}

    def set(self, url: str, title: str, summary: str) -> None:
        """Cache a link summary."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO link_summaries (url, title, summary, fetched_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary,
                    fetched_at = CURRENT_TIMESTAMP
                """,
                (url, title, summary),
            )
            conn.commit()


# Module-level cache singleton
_link_cache: LinkCache | None = None


def get_link_cache() -> LinkCache:
    """Get the singleton LinkCache instance."""
    global _link_cache
    if _link_cache is None:
        _link_cache = LinkCache()
    return _link_cache


def extract_urls(text: str) -> list[str]:
    """Extract URLs from text, filtering out skippable ones."""
    urls = URL_PATTERN.findall(text)
    result = []

    for url in urls:
        # Clean trailing punctuation
        url = url.rstrip(".,;:!?)")

        # Parse and check domain
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()

            # Remove www. prefix for comparison
            if domain.startswith("www."):
                domain = domain[4:]

            # Skip certain domains
            if domain in SKIP_DOMAINS:
                continue

            # Skip image/video extensions
            path_lower = parsed.path.lower()
            if any(path_lower.endswith(ext) for ext in SKIP_EXTENSIONS):
                continue

            result.append(url)
        except Exception:
            continue

    return result


async def fetch_page_content(url: str, timeout: float = 10.0) -> tuple[str, str] | None:
    """
    Fetch page and extract title + main text content.

    Returns (title, text_content) or None on failure.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            # Only process HTML
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return None

            html = response.text
            soup = BeautifulSoup(html, "html.parser")

            # Extract title
            title = ""
            if soup.title:
                title = soup.title.string or ""
            title = title.strip()[:200]  # Limit title length

            # Remove script, style, nav elements
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            # Try to find main content
            main_content = None
            for selector in ["article", "main", '[role="main"]', ".post-content", ".article-body"]:
                main_content = soup.select_one(selector)
                if main_content:
                    break

            if main_content:
                text = main_content.get_text(separator=" ", strip=True)
            else:
                # Fallback to body
                body = soup.find("body")
                text = body.get_text(separator=" ", strip=True) if body else ""

            # Clean up whitespace and limit length
            text = " ".join(text.split())
            text = text[:5000]  # Limit to ~5000 chars for Claude

            return title, text

    except Exception:
        return None


def summarize_with_claude(title: str, content: str) -> str | None:
    """Use Claude Haiku to generate a 2-sentence summary."""
    api_key = get_api_key()
    if not api_key:
        return None

    if not content or len(content) < 50:
        return None

    import anthropic

    try:
        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""Summarize this article in exactly 2 sentences. Be informative and specific about what the article says. Don't use phrases like "This article discusses..." - just state the key points directly.

Title: {title}

Content:
{content[:3000]}"""

        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )

        summary = response.content[0].text.strip()
        return summary

    except Exception:
        return None


async def expand_link(url: str) -> dict | None:
    """
    Expand a single link: fetch, summarize, cache.

    Returns {"title": str, "summary": str} or None on failure.
    """
    cache = get_link_cache()

    # Check cache first
    cached = cache.get(url)
    if cached:
        return cached

    # Fetch page content
    result = await fetch_page_content(url)
    if not result:
        return None

    title, content = result

    # Summarize with Claude (run in executor since it's sync)
    loop = asyncio.get_event_loop()
    summary = await loop.run_in_executor(None, summarize_with_claude, title, content)

    if not summary:
        return None

    # Cache the result
    cache.set(url, title, summary)

    return {"title": title, "summary": summary}


async def expand_links_batch(urls: list[str], max_concurrent: int = 5) -> dict[str, dict]:
    """
    Expand multiple links concurrently.

    Args:
        urls: List of URLs to expand
        max_concurrent: Max concurrent requests

    Returns:
        Dict mapping URL -> {"title": str, "summary": str}
    """
    if not urls:
        return {}

    # Deduplicate
    unique_urls = list(set(urls))

    # Use semaphore to limit concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def expand_with_limit(url: str) -> tuple[str, dict | None]:
        async with semaphore:
            result = await expand_link(url)
            return url, result

    # Run all expansions concurrently
    tasks = [expand_with_limit(url) for url in unique_urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build result dict
    expanded = {}
    for item in results:
        if isinstance(item, tuple) and item[1] is not None:
            url, data = item
            expanded[url] = data

    return expanded


def get_tweet_urls(tweet_content: str) -> list[str]:
    """Extract expandable URLs from a tweet."""
    return extract_urls(tweet_content)
