"""X timeline fetcher using Playwright."""

import asyncio
import random
import re
from datetime import datetime, timedelta

import browser_cookie3
from playwright.async_api import async_playwright, Page

from xfeed.models import Tweet, QuotedTweet, Notification, NotificationType, ThreadContext


# =============================================================================
# Timing and pacing settings
# =============================================================================
# Variable delays for natural pacing during fetching.
# All times are in milliseconds unless noted.

# Scroll delays: variable intervals between scrolls
SCROLL_DELAY_MIN = 400   # Minimum ms between scrolls
SCROLL_DELAY_MAX = 800   # Maximum ms between scrolls

# Page load: wait for content to settle after load
PAGE_LOAD_MIN = 800
PAGE_LOAD_MAX = 1500

# Navigation: pause between switching pages
NAV_PAUSE_MIN = 500
NAV_PAUSE_MAX = 1000

# Reading simulation: occasionally pause longer for content loading
READ_PAUSE_CHANCE = 0.05  # 5% chance to pause and "read"
READ_PAUSE_MIN = 500
READ_PAUSE_MAX = 1000

# =============================================================================
# Resource blocking - skip loading things we don't need
# =============================================================================
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}  # Don't block stylesheet - needed for page load
BLOCKED_URL_PATTERNS = [
    "analytics",
    "tracking",
    "ads.",
    "doubleclick",
    "googlesyndication",
    "facebook.com",
    "twimg.com/emoji",  # Emoji images
    "twimg.com/profile_images",  # Profile pics (we just need text)
    "video.twimg.com",
    "pbs.twimg.com",  # Media images
    "ton.twitter.com",  # Analytics
]

# Rate limiting: minimum time between full fetch sessions (seconds)
MIN_FETCH_INTERVAL = 120  # 2 minutes minimum between full refreshes

# Track last fetch time for rate limiting
_last_fetch_time: datetime | None = None


async def _block_unnecessary_resources(route):
    """Block images, media, fonts, and tracking to speed up page loads."""
    request = route.request

    # Block by resource type
    if request.resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return

    # Block by URL pattern
    url = request.url.lower()
    for pattern in BLOCKED_URL_PATTERNS:
        if pattern in url:
            await route.abort()
            return

    # Allow everything else
    await route.continue_()


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
    global _last_fetch_time
    if _last_fetch_time is None:
        return True
    elapsed = (datetime.now() - _last_fetch_time).total_seconds()
    return elapsed >= MIN_FETCH_INTERVAL


def _update_fetch_time():
    """Update the last fetch timestamp."""
    global _last_fetch_time
    _last_fetch_time = datetime.now()


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


def get_x_session_from_chrome() -> list[dict]:
    """Get X/Twitter session from Chrome browser."""
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

        # Check if this tweet is a reply
        # X shows "Replying to @handle" above reply tweets
        is_reply = False
        try:
            # Look for "Replying to" text in the tweet article
            full_text = await article.inner_text()
            is_reply = "replying to" in full_text.lower()
        except Exception:
            pass

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
            is_reply=is_reply,
        )
    except Exception:
        return None


async def fetch_timeline(
    count: int = 50,
    headless: bool = True,
    on_progress: callable = None,
) -> tuple[list[Tweet], str | None]:
    """
    Fetch tweets from the X home timeline using Chrome session.

    Args:
        count: Number of tweets to fetch
        headless: Run browser in headless mode
        on_progress: Callback function for progress updates

    Returns:
        Tuple of (List of Tweet objects, logged-in user handle or None)
    """
    tweets: dict[str, Tweet] = {}
    my_handle: str | None = None

    # Get session from Chrome
    cookies = get_x_session_from_chrome()
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

        # Block unnecessary resources for faster loading
        # Resource blocking disabled - was causing blank pages on X
        # await page.route("**/*", _block_unnecessary_resources)

        # Navigate to home timeline (don't wait for all resources)
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
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

    _update_fetch_time()
    return list(tweets.values())[:count], my_handle


def parse_notification_text(text: str) -> tuple[NotificationType, list[str], int]:
    """
    Parse notification text to extract type and actors.

    Returns:
        (notification_type, actor_names, additional_count)
    """
    text_lower = text.lower()

    # Determine notification type - check multiple patterns for each type
    if any(p in text_lower for p in ["liked your", "likes your"]):
        notif_type = NotificationType.LIKE
    elif any(p in text_lower for p in ["retweeted your", "reposted your", "retweets your", "reposts your"]):
        notif_type = NotificationType.RETWEET
    elif any(p in text_lower for p in ["replied", "reply", "commented", "responding to"]):
        notif_type = NotificationType.REPLY
    elif any(p in text_lower for p in ["quoted your", "quotes your", "quote tweeted"]):
        notif_type = NotificationType.QUOTE
    elif any(p in text_lower for p in ["followed you", "follows you", "started following"]):
        notif_type = NotificationType.FOLLOW
    elif any(p in text_lower for p in ["mentioned you", "mentions you", "tagged you"]):
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
        # Still capture UNKNOWN notifications so user can see what we're missing
        # They just won't count toward engagement stats

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

        # Get timestamp - convert to local time for consistent comparison
        time_elem = await article.query_selector("time")
        if time_elem:
            time_str = await time_elem.get_attribute("datetime")
            if time_str:
                # Parse ISO timestamp (usually UTC) and convert to local naive datetime
                from datetime import timezone
                utc_dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                # Convert to local time, then make naive for comparison with datetime.now()
                local_dt = utc_dt.astimezone().replace(tzinfo=None)
                timestamp = local_dt
            else:
                time_text = await time_elem.inner_text()
                timestamp = parse_relative_time(time_text)
        else:
            timestamp = datetime.now()

        # Get tweet content using proper DOM selectors
        tweet_preview = None
        reply_content = None
        reply_to_content = None

        # X uses [data-testid="tweetText"] for tweet content
        tweet_text_elements = await article.query_selector_all('[data-testid="tweetText"]')

        if notif_type == NotificationType.REPLY:
            # For replies: first tweetText is original, second is the reply
            if len(tweet_text_elements) >= 2:
                reply_to_content = (await tweet_text_elements[0].inner_text())[:200]
                reply_content = (await tweet_text_elements[1].inner_text())[:200]
            elif len(tweet_text_elements) == 1:
                # Only one text element - could be either, assume it's the reply
                reply_content = (await tweet_text_elements[0].inner_text())[:200]
            else:
                # Fallback to text parsing if no tweetText elements found
                lines = text.split("\n")
                content_lines = [line.strip() for line in lines[1:] if line.strip() and len(line.strip()) > 10]
                if len(content_lines) >= 2:
                    reply_to_content = content_lines[0][:200]
                    reply_content = content_lines[1][:200]
                elif len(content_lines) == 1:
                    reply_content = content_lines[0][:200]
        else:
            # For other notification types, get any tweet preview
            if tweet_text_elements:
                tweet_preview = (await tweet_text_elements[0].inner_text())[:100]
            else:
                # Fallback to text parsing
                lines = text.split("\n")
                content_lines = [line.strip() for line in lines[1:] if line.strip() and len(line.strip()) > 10]
                if content_lines:
                    tweet_preview = content_lines[0][:100]

        return Notification(
            type=notif_type,
            actor_handle=actor_handle,
            actor_name=actor_name,
            timestamp=timestamp,
            additional_actors=additional_actors[:5],  # Limit to 5
            additional_count=additional_count,
            target_tweet_preview=tweet_preview,
            reply_content=reply_content,
            reply_to_content=reply_to_content,
        )
    except Exception:
        return None


async def fetch_notifications(
    count: int = 50,
    headless: bool = True,
    on_progress: callable = None,
) -> list[Notification]:
    """
    Fetch notifications from the X notifications page.

    Args:
        count: Number of notifications to fetch
        headless: Run browser in headless mode
        on_progress: Callback function for progress updates

    Returns:
        List of Notification objects
    """
    notifications: list[Notification] = []

    cookies = get_x_session_from_chrome()
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

        # Block unnecessary resources for faster loading
        # Resource blocking disabled - was causing blank pages on X
        # await page.route("**/*", _block_unnecessary_resources)

        await page.goto("https://x.com/notifications", wait_until="domcontentloaded", timeout=60000)
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

    _update_fetch_time()
    return notifications[:count]


async def fetch_profile_timeline(
    username: str,
    count: int = 20,
    headless: bool = True,
    on_progress: callable = None,
) -> list[Tweet]:
    """
    Fetch tweets from a user's profile timeline.

    Args:
        username: The username to fetch (without @)
        count: Number of tweets to fetch
        headless: Run browser in headless mode
        on_progress: Callback function for progress updates

    Returns:
        List of Tweet objects from the user's profile
    """
    tweets: dict[str, Tweet] = {}
    username = username.lstrip("@")

    cookies = get_x_session_from_chrome()
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

        # Block unnecessary resources for faster loading
        # Resource blocking disabled - was causing blank pages on X
        # await page.route("**/*", _block_unnecessary_resources)

        await page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=60000)
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

    _update_fetch_time()
    return list(tweets.values())[:count]


async def fetch_all_engagement(
    home_count: int = 20,
    profile_count: int = 10,
    notifications_count: int = 30,
    headless: bool = True,
    on_progress: callable = None,
) -> tuple[list[Tweet], list[Tweet], list[Notification], str | None]:
    """
    Fetch home timeline, profile timeline, and notifications in a single session.
    Uses variable delays between actions for reliability.

    Returns:
        (home_tweets, profile_tweets, notifications, my_handle)
    """
    home_tweets: dict[str, Tweet] = {}
    profile_tweets: dict[str, Tweet] = {}
    notifications: list[Notification] = []
    my_handle: str | None = None

    cookies = get_x_session_from_chrome()
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

        # NOTE: Resource blocking disabled - was causing blank pages
        # await page.route("**/*", _block_unnecessary_resources)

        # 1. Fetch home timeline
        if on_progress:
            on_progress("home", 0, home_count)

        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(_page_load_delay())

        # Wait for tweets to load (they load dynamically)
        try:
            await page.wait_for_selector(TWEET_SELECTOR, timeout=15000)
        except Exception:
            # Tweets didn't load in time - continue anyway and try scrolling
            pass

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

        # 2. Fetch profile timeline (with navigation pause)
        if my_handle and profile_count > 0:
            # Pause before navigating like a human would
            await page.wait_for_timeout(_nav_delay())

            if on_progress:
                on_progress("profile", 0, profile_count)

            username = my_handle.lstrip("@")
            await page.goto(f"https://x.com/{username}", wait_until="domcontentloaded", timeout=60000)
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

        # 3. Fetch notifications (with navigation pause)
        if notifications_count > 0:
            # Pause before navigating like a human would
            await page.wait_for_timeout(_nav_delay())

            if on_progress:
                on_progress("notifications", 0, notifications_count)

            await page.goto("https://x.com/notifications", wait_until="domcontentloaded", timeout=60000)
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

    _update_fetch_time()
    return (
        list(home_tweets.values())[:home_count],
        list(profile_tweets.values())[:profile_count],
        notifications[:notifications_count],
        my_handle,
    )


async def fetch_thread(
    tweet_url: str,
    max_parents: int = 5,
    max_replies: int = 10,
    headless: bool = True,
) -> ThreadContext | None:
    """
    Fetch thread context for a tweet by navigating to its detail page.

    On X, the tweet detail page shows:
    - Parent tweets above (conversation context)
    - The main tweet
    - Replies below

    Args:
        tweet_url: Full URL to the tweet (e.g., https://x.com/user/status/123)
        max_parents: Maximum parent tweets to fetch (context above)
        max_replies: Maximum replies to fetch
        headless: Run browser in headless mode

    Returns:
        ThreadContext with parent and reply tweets, or None on failure
    """
    # Extract tweet ID from URL for matching
    if "/status/" not in tweet_url:
        return None

    target_tweet_id = tweet_url.split("/status/")[-1].split("?")[0].split("/")[0]
    if not target_tweet_id:
        return None

    cookies = get_x_session_from_chrome()
    if not cookies:
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        try:
            # Navigate to tweet detail page
            await page.goto(tweet_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(_page_load_delay())

            # Wait for tweets to load
            try:
                await page.wait_for_selector(TWEET_SELECTOR, timeout=10000)
            except Exception:
                await browser.close()
                return None

            # Get logged-in user for engagement detection
            my_handle = await get_logged_in_user(page)

            # Collect all tweets on the page
            parent_tweets: list[Tweet] = []
            reply_tweets: list[Tweet] = []
            original_tweet: Tweet | None = None

            # First pass: collect all visible tweets
            articles = await page.query_selector_all(TWEET_SELECTOR)

            found_original = False
            for article in articles:
                tweet = await extract_tweet_data(article, page, my_handle)
                if not tweet:
                    continue

                # Check if this is the target tweet
                if tweet.id == target_tweet_id:
                    original_tweet = tweet
                    found_original = True
                elif not found_original:
                    # Before target = parent/context
                    if len(parent_tweets) < max_parents:
                        parent_tweets.append(tweet)
                else:
                    # After target = replies
                    if len(reply_tweets) < max_replies:
                        reply_tweets.append(tweet)

            # If we didn't find the original tweet, something went wrong
            if not original_tweet:
                await browser.close()
                return None

            # Scroll down to get more replies if needed
            scroll_count = 0
            max_scrolls = 3
            while len(reply_tweets) < max_replies and scroll_count < max_scrolls:
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(_scroll_delay())
                scroll_count += 1

                articles = await page.query_selector_all(TWEET_SELECTOR)
                for article in articles:
                    tweet = await extract_tweet_data(article, page, my_handle)
                    if not tweet or tweet.id == target_tweet_id:
                        continue

                    # Check if we already have this tweet
                    existing_ids = {t.id for t in reply_tweets}
                    if tweet.id not in existing_ids and len(reply_tweets) < max_replies:
                        # Only add tweets that appear after our target (replies)
                        reply_tweets.append(tweet)

            await browser.close()

            return ThreadContext(
                original_tweet=original_tweet,
                parent_tweets=parent_tweets,
                reply_tweets=reply_tweets,
            )

        except Exception:
            await browser.close()
            return None
