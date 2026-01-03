"""X timeline scraper using Playwright."""

import asyncio
import re
from datetime import datetime, timedelta

import browser_cookie3
from playwright.async_api import async_playwright, Page

from xfeed.models import Tweet, QuotedTweet


# Selectors for X's DOM - these may need updating if X changes their structure
TWEET_SELECTOR = 'article[data-testid="tweet"]'
TWEET_TEXT_SELECTOR = '[data-testid="tweetText"]'
USER_NAME_SELECTOR = '[data-testid="User-Name"]'
LIKE_COUNT_SELECTOR = '[data-testid="like"] span'
RETWEET_COUNT_SELECTOR = '[data-testid="retweet"] span'
REPLY_COUNT_SELECTOR = '[data-testid="reply"] span'
LIKE_BUTTON_SELECTOR = '[data-testid="like"]'
RETWEET_BUTTON_SELECTOR = '[data-testid="retweet"]'
TIME_SELECTOR = "time"
# Quote tweet is embedded in a card/container - try multiple selectors
QUOTE_TWEET_SELECTOR = '[data-testid="quoteTweet"]'
QUOTE_TWEET_ALT_SELECTOR = 'div[role="link"][tabindex="0"]'  # Fallback
# Profile link for detecting logged-in user
PROFILE_LINK_SELECTOR = 'a[data-testid="AppTabBar_Profile_Link"]'


def get_x_cookies_from_chrome() -> list[dict]:
    """Extract X/Twitter cookies from Chrome browser."""
    try:
        cj = browser_cookie3.chrome(domain_name=".x.com")
        cookies = []
        for cookie in cj:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": bool(cookie.secure),
                "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
            })

        # Also get twitter.com cookies (X uses both domains)
        cj_twitter = browser_cookie3.chrome(domain_name=".twitter.com")
        for cookie in cj_twitter:
            cookies.append({
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": bool(cookie.secure),
                "httpOnly": bool(cookie.has_nonstandard_attr("HttpOnly")),
            })

        return cookies
    except Exception as e:
        raise RuntimeError(
            f"Could not extract cookies from Chrome: {e}\n"
            "Make sure you are logged into x.com in Chrome."
        )


def parse_count(text: str | None) -> int:
    """Parse engagement count strings like '1.2K' or '500'."""
    if not text:
        return 0

    text = text.strip().upper()
    if not text:
        return 0

    try:
        if "K" in text:
            return int(float(text.replace("K", "")) * 1000)
        elif "M" in text:
            return int(float(text.replace("M", "")) * 1000000)
        else:
            return int(text)
    except ValueError:
        return 0


def parse_relative_time(time_str: str) -> datetime:
    """Parse relative time strings like '2h', '3m', '1d' to datetime."""
    now = datetime.now()

    match = re.match(r"(\d+)([smhd])", time_str.lower())
    if match:
        value = int(match.group(1))
        unit = match.group(2)

        if unit == "s":
            return now - timedelta(seconds=value)
        elif unit == "m":
            return now - timedelta(minutes=value)
        elif unit == "h":
            return now - timedelta(hours=value)
        elif unit == "d":
            return now - timedelta(days=value)

    return now


async def get_logged_in_user(page: Page) -> str | None:
    """Extract the logged-in user's handle from the page."""
    try:
        profile_link = await page.query_selector(PROFILE_LINK_SELECTOR)
        if profile_link:
            href = await profile_link.get_attribute("href")
            # href is like "/username" -> extract "username"
            if href:
                handle = href.strip("/")
                return f"@{handle}" if not handle.startswith("@") else handle
        return None
    except Exception:
        return None


async def extract_quoted_tweet(article) -> QuotedTweet | None:
    """Extract quoted tweet data if present."""
    try:
        # Try primary selector first
        quote_elem = await article.query_selector(QUOTE_TWEET_SELECTOR)

        if not quote_elem:
            # Try looking for a nested tweet-like structure
            # Quote tweets often have their own tweetText and User-Name inside a card
            inner_cards = await article.query_selector_all('div[data-testid="card.wrapper"]')
            for card in inner_cards:
                text_elem = await card.query_selector(TWEET_TEXT_SELECTOR)
                if text_elem:
                    quote_elem = card
                    break

        if not quote_elem:
            return None

        # Get quoted author
        user_elem = await quote_elem.query_selector(USER_NAME_SELECTOR)
        if user_elem:
            user_text = await user_elem.inner_text()
            lines = user_text.strip().split("\n")
            author = lines[0] if lines else "Unknown"
            author_handle = lines[1] if len(lines) > 1 else "@unknown"
        else:
            # Try to find any user reference in the quote
            author = "Unknown"
            author_handle = "@unknown"

        # Get quoted content
        text_elem = await quote_elem.query_selector(TWEET_TEXT_SELECTOR)
        content = await text_elem.inner_text() if text_elem else ""

        if not content:
            return None

        return QuotedTweet(
            author=author,
            author_handle=author_handle,
            content=content[:500],  # Truncate long quotes
        )
    except Exception:
        return None


async def extract_tweet_data(article, page: Page, my_handle: str | None = None) -> Tweet | None:
    """Extract tweet data from an article element."""
    try:
        # Get tweet ID from the link
        tweet_link = await article.query_selector('a[href*="/status/"]')
        tweet_url = await tweet_link.get_attribute("href") if tweet_link else ""
        tweet_id = tweet_url.split("/status/")[-1].split("?")[0] if "/status/" in tweet_url else ""

        if not tweet_id:
            return None

        # Get author info
        user_name_elem = await article.query_selector(USER_NAME_SELECTOR)
        if not user_name_elem:
            return None

        user_text = await user_name_elem.inner_text()
        lines = user_text.strip().split("\n")
        author = lines[0] if lines else "Unknown"
        author_handle = lines[1] if len(lines) > 1 else "@unknown"

        # Get tweet content
        tweet_text_elem = await article.query_selector(TWEET_TEXT_SELECTOR)
        content = await tweet_text_elem.inner_text() if tweet_text_elem else ""

        # Get timestamp
        time_elem = await article.query_selector(TIME_SELECTOR)
        time_str = await time_elem.get_attribute("datetime") if time_elem else None

        if time_str:
            timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            time_text = await time_elem.inner_text() if time_elem else ""
            timestamp = parse_relative_time(time_text)

        # Get engagement counts
        like_elem = await article.query_selector(LIKE_COUNT_SELECTOR)
        like_text = await like_elem.inner_text() if like_elem else "0"

        retweet_elem = await article.query_selector(RETWEET_COUNT_SELECTOR)
        retweet_text = await retweet_elem.inner_text() if retweet_elem else "0"

        reply_elem = await article.query_selector(REPLY_COUNT_SELECTOR)
        reply_text = await reply_elem.inner_text() if reply_elem else "0"

        # Check for media
        has_media = bool(await article.query_selector('[data-testid="tweetPhoto"]')) or \
                    bool(await article.query_selector('[data-testid="videoPlayer"]'))

        # Check for quoted tweet
        quoted_tweet = await extract_quoted_tweet(article)

        # Check if this is my tweet
        is_by_me = False
        if my_handle:
            # Normalize handles for comparison (both should have @)
            my_handle_norm = my_handle.lower()
            author_handle_norm = author_handle.lower()
            is_by_me = my_handle_norm == author_handle_norm

        # Check if I liked this tweet
        # When not liked: "9 Likes. Like" - ends with "Like"
        # When liked: "9 Likes. Unlike" - contains "Unlike"
        is_liked_by_me = False
        like_button = await article.query_selector(LIKE_BUTTON_SELECTOR)
        if like_button:
            aria_label = await like_button.get_attribute("aria-label") or ""
            is_liked_by_me = "unlike" in aria_label.lower()

        # Check if I retweeted this tweet
        # When not retweeted: "0 reposts. Repost" - ends with "Repost"
        # When retweeted: "0 reposts. Undo repost" - contains "Undo"
        is_retweeted_by_me = False
        retweet_button = await article.query_selector(RETWEET_BUTTON_SELECTOR)
        if retweet_button:
            aria_label = await retweet_button.get_attribute("aria-label") or ""
            is_retweeted_by_me = "undo" in aria_label.lower()

        return Tweet(
            id=tweet_id,
            author=author,
            author_handle=author_handle,
            content=content,
            timestamp=timestamp,
            likes=parse_count(like_text),
            retweets=parse_count(retweet_text),
            replies=parse_count(reply_text),
            has_media=has_media,
            url=f"https://x.com{tweet_url}" if tweet_url.startswith("/") else tweet_url,
            quoted_tweet=quoted_tweet,
            is_by_me=is_by_me,
            is_liked_by_me=is_liked_by_me,
            is_retweeted_by_me=is_retweeted_by_me,
        )
    except Exception:
        return None


async def scrape_timeline(
    count: int = 50,
    headless: bool = True,
    on_progress: callable = None,
) -> tuple[list[Tweet], str | None]:
    """
    Scrape tweets from the X home timeline using Chrome cookies.

    Args:
        count: Number of tweets to fetch
        headless: Run browser in headless mode
        on_progress: Callback function for progress updates

    Returns:
        Tuple of (List of Tweet objects, logged-in user handle or None)
    """
    tweets: dict[str, Tweet] = {}
    my_handle: str | None = None

    # Extract cookies from Chrome
    cookies = get_x_cookies_from_chrome()
    if not cookies:
        raise RuntimeError(
            "No X cookies found in Chrome. Please log in to x.com in Chrome first."
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Add cookies to the context
        await context.add_cookies(cookies)

        page = await context.new_page()

        # Navigate to home timeline
        await page.goto("https://x.com/home")
        await page.wait_for_timeout(3000)

        # Check if we're logged in
        if "/login" in page.url or "x.com/i/flow/login" in page.url:
            await browser.close()
            raise RuntimeError(
                "Not logged in to X. Please log in to x.com in Chrome first, "
                "then try again."
            )

        # Get the logged-in user's handle
        my_handle = await get_logged_in_user(page)

        # Scroll and collect tweets
        scroll_count = 0
        max_scrolls = count // 5 + 10

        while len(tweets) < count and scroll_count < max_scrolls:
            articles = await page.query_selector_all(TWEET_SELECTOR)

            for article in articles:
                if len(tweets) >= count:
                    break

                tweet = await extract_tweet_data(article, page, my_handle)
                if tweet and tweet.id not in tweets:
                    tweets[tweet.id] = tweet

                    if on_progress:
                        on_progress(len(tweets), count)

            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(1500)
            scroll_count += 1

        await browser.close()

    return list(tweets.values())[:count], my_handle
