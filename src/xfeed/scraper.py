"""X timeline scraper using Playwright."""

import asyncio
import random
import re
from datetime import datetime, timedelta

import browser_cookie3
from playwright.async_api import async_playwright, Page

from xfeed.models import Tweet, QuotedTweet, Notification, NotificationType


# =============================================================================
# Timing and pacing settings
# =============================================================================
# Variable delays for natural pacing during scraping.
# All times are in milliseconds unless noted.

# Scroll delays: variable intervals between scrolls
SCROLL_DELAY_MIN = 1200  # Minimum ms between scrolls
SCROLL_DELAY_MAX = 3500  # Maximum ms between scrolls
SCROLL_DELAY_READ = 800  # Extra delay when "reading" (random chance)

# Page load: wait for content to settle after load
PAGE_LOAD_MIN = 2500
PAGE_LOAD_MAX = 4500

# Navigation: pause between switching pages
NAV_PAUSE_MIN = 1500
NAV_PAUSE_MAX = 3000

# Reading simulation: occasionally pause longer for content loading
READ_PAUSE_CHANCE = 0.15  # 15% chance to pause and "read"
READ_PAUSE_MIN = 2000
READ_PAUSE_MAX = 5000

# Rate limiting: minimum time between full scrape sessions (seconds)
MIN_SCRAPE_INTERVAL = 120  # 2 minutes minimum between full refreshes

# Track last scrape time for rate limiting
_last_scrape_time: datetime | None = None


def _scroll_delay() -> int:
    """Get a variable delay for scrolling (ms)."""
    base = random.randint(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX)
    # Occasionally add extra "reading" time
    if random.random() < READ_PAUSE_CHANCE:
        base += random.randint(READ_PAUSE_MIN, READ_PAUSE_MAX)
    return base


def _page_load_delay() -> int:
    """Get a variable delay after page load (ms)."""
    return random.randint(PAGE_LOAD_MIN, PAGE_LOAD_MAX)


def _nav_delay() -> int:
    """Get a variable delay between page navigations (ms)."""
    return random.randint(NAV_PAUSE_MIN, NAV_PAUSE_MAX)


def _jitter(base_seconds: int, jitter_pct: float = 0.2) -> int:
    """Add random jitter to a time value. Returns seconds."""
    jitter_range = int(base_seconds * jitter_pct)
    return base_seconds + random.randint(-jitter_range, jitter_range)


def _check_rate_limit() -> bool:
    """Check if we should rate limit. Returns True if OK to proceed."""
    global _last_scrape_time
    if _last_scrape_time is None:
        return True
    elapsed = (datetime.now() - _last_scrape_time).total_seconds()
    return elapsed >= MIN_SCRAPE_INTERVAL


def _update_scrape_time():
    """Update the last scrape timestamp."""
    global _last_scrape_time
    _last_scrape_time = datetime.now()


# =============================================================================
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
            f"Could not access Chrome session: {e}\n"
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
            "Not logged into X. Please log in to x.com in Chrome first."
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
        await page.wait_for_timeout(_page_load_delay())

        # Check if we're logged in
        if "/login" in page.url or "x.com/i/flow/login" in page.url:
            await browser.close()
            raise RuntimeError(
                "Not logged in to X. Please log in to x.com in Chrome first, "
                "then try again."
            )

        # Get the logged-in user's handle
        my_handle = await get_logged_in_user(page)

        # Scroll and collect tweets with variable timing
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
            await page.wait_for_timeout(_scroll_delay())
            scroll_count += 1

        await browser.close()

    _update_scrape_time()
    return list(tweets.values())[:count], my_handle


def parse_notification_text(text: str) -> tuple[NotificationType, list[str], int]:
    """
    Parse notification text to extract type and actors.

    Returns:
        (notification_type, actor_names, additional_count)
    """
    text_lower = text.lower()

    # Determine notification type
    if "liked your" in text_lower:
        notif_type = NotificationType.LIKE
    elif "retweeted your" in text_lower or "reposted your" in text_lower:
        notif_type = NotificationType.RETWEET
    elif "replied to" in text_lower:
        notif_type = NotificationType.REPLY
    elif "quoted your" in text_lower:
        notif_type = NotificationType.QUOTE
    elif "followed you" in text_lower:
        notif_type = NotificationType.FOLLOW
    elif "mentioned you" in text_lower:
        notif_type = NotificationType.MENTION
    else:
        notif_type = NotificationType.UNKNOWN

    # Parse "and N others" pattern
    additional_count = 0
    others_match = re.search(r"and (\d+) others?", text_lower)
    if others_match:
        additional_count = int(others_match.group(1))

    return notif_type, [], additional_count


async def extract_notification_data(article, page: Page) -> Notification | None:
    """Extract notification data from an article element."""
    try:
        # Get the full text
        text = await article.inner_text()
        if not text:
            return None

        # Parse notification type and additional count
        notif_type, _, additional_count = parse_notification_text(text)
        if notif_type == NotificationType.UNKNOWN:
            return None

        # Get user links (actors who performed the action)
        links = await article.query_selector_all('a[role="link"]')
        actor_handle = "@unknown"
        actor_name = "Unknown"
        additional_actors = []

        for link in links:
            href = await link.get_attribute("href") or ""
            # Skip non-user links (like status links)
            if href.startswith("/") and "/status/" not in href and len(href) > 1:
                link_text = await link.inner_text()
                handle = f"@{href.strip('/')}"

                if actor_handle == "@unknown":
                    actor_handle = handle
                    actor_name = link_text.strip()
                else:
                    additional_actors.append(handle)

        # Get timestamp
        time_elem = await article.query_selector("time")
        if time_elem:
            time_str = await time_elem.get_attribute("datetime")
            if time_str:
                timestamp = datetime.fromisoformat(time_str.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                time_text = await time_elem.inner_text()
                timestamp = parse_relative_time(time_text)
        else:
            timestamp = datetime.now()

        # Get tweet preview if available (truncated content)
        tweet_preview = None
        # The notification text often contains the tweet content after the action description
        lines = text.split("\n")
        for line in lines[1:]:  # Skip first line which is the notification
            line = line.strip()
            if len(line) > 20 and not line.endswith("..."):
                tweet_preview = line[:100]
                break

        return Notification(
            type=notif_type,
            actor_handle=actor_handle,
            actor_name=actor_name,
            timestamp=timestamp,
            additional_actors=additional_actors[:5],  # Limit to 5
            additional_count=additional_count,
            target_tweet_preview=tweet_preview,
        )
    except Exception:
        return None


async def scrape_notifications(
    count: int = 50,
    headless: bool = True,
    on_progress: callable = None,
) -> list[Notification]:
    """
    Scrape notifications from the X notifications page.

    Args:
        count: Number of notifications to fetch
        headless: Run browser in headless mode
        on_progress: Callback function for progress updates

    Returns:
        List of Notification objects
    """
    notifications: list[Notification] = []

    cookies = get_x_cookies_from_chrome()
    if not cookies:
        raise RuntimeError("Not logged into X. Please log in to x.com in Chrome first.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        await page.goto("https://x.com/notifications")
        await page.wait_for_timeout(_page_load_delay())

        # Check if logged in
        if "/login" in page.url:
            await browser.close()
            raise RuntimeError("Not logged in to X.")

        # Scroll and collect notifications with variable timing
        scroll_count = 0
        max_scrolls = count // 5 + 5
        seen_ids = set()

        while len(notifications) < count and scroll_count < max_scrolls:
            articles = await page.query_selector_all("article")

            for article in articles:
                if len(notifications) >= count:
                    break

                # Use inner text as a simple dedup key
                text = await article.inner_text()
                text_key = text[:100] if text else ""
                if text_key in seen_ids:
                    continue
                seen_ids.add(text_key)

                notif = await extract_notification_data(article, page)
                if notif:
                    notifications.append(notif)
                    if on_progress:
                        on_progress(len(notifications), count)

            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(_scroll_delay())
            scroll_count += 1

        await browser.close()

    _update_scrape_time()
    return notifications[:count]


async def scrape_profile_timeline(
    username: str,
    count: int = 20,
    headless: bool = True,
    on_progress: callable = None,
) -> list[Tweet]:
    """
    Scrape tweets from a user's profile timeline.

    Args:
        username: The username to scrape (without @)
        count: Number of tweets to fetch
        headless: Run browser in headless mode
        on_progress: Callback function for progress updates

    Returns:
        List of Tweet objects from the user's profile
    """
    tweets: dict[str, Tweet] = {}
    username = username.lstrip("@")

    cookies = get_x_cookies_from_chrome()
    if not cookies:
        raise RuntimeError("Not logged into X. Please log in to x.com in Chrome first.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        await page.goto(f"https://x.com/{username}")
        await page.wait_for_timeout(_page_load_delay())

        # Check if logged in
        if "/login" in page.url:
            await browser.close()
            raise RuntimeError("Not logged in to X.")

        my_handle = f"@{username}"

        # Scroll and collect tweets with variable timing
        scroll_count = 0
        max_scrolls = count // 5 + 5

        while len(tweets) < count and scroll_count < max_scrolls:
            articles = await page.query_selector_all(TWEET_SELECTOR)

            for article in articles:
                if len(tweets) >= count:
                    break

                tweet = await extract_tweet_data(article, page, my_handle)
                # Only include tweets by this user (not retweets or replies shown on profile)
                if tweet and tweet.id not in tweets and tweet.author_handle.lower() == my_handle.lower():
                    tweets[tweet.id] = tweet

                    if on_progress:
                        on_progress(len(tweets), count)

            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(_scroll_delay())
            scroll_count += 1

        await browser.close()

    _update_scrape_time()
    return list(tweets.values())[:count]


async def scrape_all_engagement(
    home_count: int = 20,
    profile_count: int = 10,
    notifications_count: int = 30,
    headless: bool = True,
    on_progress: callable = None,
) -> tuple[list[Tweet], list[Tweet], list[Notification], str | None]:
    """
    Scrape home timeline, profile timeline, and notifications in a single session.
    Uses variable delays between actions for reliability.

    Returns:
        (home_tweets, profile_tweets, notifications, my_handle)
    """
    home_tweets: dict[str, Tweet] = {}
    profile_tweets: dict[str, Tweet] = {}
    notifications: list[Notification] = []
    my_handle: str | None = None

    cookies = get_x_cookies_from_chrome()
    if not cookies:
        raise RuntimeError("Not logged into X. Please log in to x.com in Chrome first.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        # 1. Scrape home timeline
        if on_progress:
            on_progress("home", 0, home_count)

        await page.goto("https://x.com/home")
        await page.wait_for_timeout(_page_load_delay())

        if "/login" in page.url:
            await browser.close()
            raise RuntimeError("Not logged in to X.")

        my_handle = await get_logged_in_user(page)

        scroll_count = 0
        while len(home_tweets) < home_count and scroll_count < home_count // 5 + 5:
            articles = await page.query_selector_all(TWEET_SELECTOR)
            for article in articles:
                if len(home_tweets) >= home_count:
                    break
                tweet = await extract_tweet_data(article, page, my_handle)
                if tweet and tweet.id not in home_tweets:
                    home_tweets[tweet.id] = tweet
                    if on_progress:
                        on_progress("home", len(home_tweets), home_count)

            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(_scroll_delay())
            scroll_count += 1

        # 2. Scrape profile timeline (with navigation pause)
        if my_handle and profile_count > 0:
            # Pause before navigating like a human would
            await page.wait_for_timeout(_nav_delay())

            if on_progress:
                on_progress("profile", 0, profile_count)

            username = my_handle.lstrip("@")
            await page.goto(f"https://x.com/{username}")
            await page.wait_for_timeout(_page_load_delay())

            scroll_count = 0
            while len(profile_tweets) < profile_count and scroll_count < profile_count // 5 + 5:
                articles = await page.query_selector_all(TWEET_SELECTOR)
                for article in articles:
                    if len(profile_tweets) >= profile_count:
                        break
                    tweet = await extract_tweet_data(article, page, my_handle)
                    if tweet and tweet.id not in profile_tweets:
                        if tweet.author_handle.lower() == my_handle.lower():
                            profile_tweets[tweet.id] = tweet
                            if on_progress:
                                on_progress("profile", len(profile_tweets), profile_count)

                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(_scroll_delay())
                scroll_count += 1

        # 3. Scrape notifications (with navigation pause)
        if notifications_count > 0:
            # Pause before navigating like a human would
            await page.wait_for_timeout(_nav_delay())

            if on_progress:
                on_progress("notifications", 0, notifications_count)

            await page.goto("https://x.com/notifications")
            await page.wait_for_timeout(_page_load_delay())

            scroll_count = 0
            seen_ids = set()
            while len(notifications) < notifications_count and scroll_count < notifications_count // 5 + 5:
                articles = await page.query_selector_all("article")
                for article in articles:
                    if len(notifications) >= notifications_count:
                        break

                    text = await article.inner_text()
                    text_key = text[:100] if text else ""
                    if text_key in seen_ids:
                        continue
                    seen_ids.add(text_key)

                    notif = await extract_notification_data(article, page)
                    if notif:
                        notifications.append(notif)
                        if on_progress:
                            on_progress("notifications", len(notifications), notifications_count)

                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(_scroll_delay())
                scroll_count += 1

        await browser.close()

    _update_scrape_time()
    return (
        list(home_tweets.values())[:home_count],
        list(profile_tweets.values())[:profile_count],
        notifications[:notifications_count],
        my_handle,
    )
