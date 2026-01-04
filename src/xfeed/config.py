"""Configuration management for XFeed."""

import json
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
import yaml

# Load .env from multiple locations
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")  # Project directory
load_dotenv(Path.home() / ".xfeed" / ".env")  # Config directory


CONFIG_DIR = Path.home() / ".xfeed"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"
COOKIES_FILE = CONFIG_DIR / "cookies.json"
OBJECTIVES_FILE = CONFIG_DIR / "objectives.md"

DEFAULT_OBJECTIVES = """# Things I Care About

## Technology
- AI/ML research and breakthroughs
- Developer tools and productivity
- Open source projects

## Topics
- [Add your specific interests here]

## People
- [Specific accounts to always include]

## Exclude
- Crypto/NFT promotions
- Engagement bait / rage bait
- Drama and controversy
- Ads and sponsored content
"""

DEFAULT_CONFIG = {
    "openai_api_key": "",
    "relevance_threshold": 7,
    "default_tweet_count": 50,
    "batch_size": 15,
    # Exploration / Serendipity settings
    "exploration_rate": 0.1,  # % of feed slots for exploration candidates
    "exploration_min_quality": 7,  # Minimum score for unknown authors
    "exploration_diversity_window": 50,  # Posts to consider for diversity
    "exploration_cooldown_hours": 24,  # Hours before showing same new author again
    # Reasoning quality settings
    "reasoning_boost_max": 2,  # Max boost for high-quality reasoning
    "reasoning_penalty_max": 2,  # Max penalty for low-quality reasoning
    # Contrarian settings
    "dissent_min_rigor": 6,  # Minimum rigor score for dissent bonus
    "dissent_bonus_cap": 2,  # Max boost for contrarian content
}


def ensure_config_dir() -> None:
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load configuration from file."""
    ensure_config_dir()

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f) or {}

    # Merge with defaults for any missing keys
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value

    return config


def save_config(config: dict) -> None:
    """Save configuration to file."""
    ensure_config_dir()

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_api_key() -> str | None:
    """Get Anthropic API key from .env or environment."""
    # Environment variable (loaded from .env or system)
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key

    config = load_config()
    return config.get("anthropic_api_key") or None


def set_api_key(api_key: str) -> None:
    """Save Anthropic API key to .env file."""
    ensure_config_dir()

    # Write to .env file with restricted permissions
    ENV_FILE.write_text(f"ANTHROPIC_API_KEY={api_key}\n")
    ENV_FILE.chmod(0o600)  # Owner read/write only

    # Also set in environment for current session
    os.environ["ANTHROPIC_API_KEY"] = api_key


def load_cookies() -> dict | None:
    """Load saved X session cookies."""
    if not COOKIES_FILE.exists():
        return None

    with open(COOKIES_FILE) as f:
        return json.load(f)


def save_cookies(cookies: list[dict]) -> None:
    """Save X session cookies."""
    ensure_config_dir()

    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f)


def load_objectives() -> str:
    """Load objectives from file."""
    ensure_config_dir()

    if not OBJECTIVES_FILE.exists():
        save_objectives(DEFAULT_OBJECTIVES)
        return DEFAULT_OBJECTIVES

    return OBJECTIVES_FILE.read_text()


def save_objectives(content: str) -> None:
    """Save objectives to file."""
    ensure_config_dir()
    OBJECTIVES_FILE.write_text(content)


def get_objectives_path() -> Path:
    """Get path to objectives file."""
    ensure_config_dir()

    if not OBJECTIVES_FILE.exists():
        save_objectives(DEFAULT_OBJECTIVES)

    return OBJECTIVES_FILE


def ensure_playwright_browser() -> bool:
    """Check if Playwright chromium is installed, install if needed. Returns True if ready."""
    try:
        # Check if chromium is already installed
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
        )
        # If dry-run shows nothing to install, we're good
        if "chromium" not in result.stdout.lower() or "already installed" in result.stdout.lower():
            return True
    except Exception:
        pass

    # Need to install
    print("Installing Playwright browser (one-time setup)...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("Browser installed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to install browser: {e}")
        print("Try running: playwright install chromium")
        return False


def prompt_for_api_key() -> str | None:
    """Prompt user for API key if not set. Returns the key or None."""
    print("\n" + "=" * 60)
    print("XFEED SETUP")
    print("=" * 60)
    print("\nTo filter your timeline, xfeed needs an Anthropic API key.")
    print("Get one at: https://console.anthropic.com/")
    print("\nThe key will be saved to ~/.xfeed/.env (permissions: 600)")
    print("You can also set ANTHROPIC_API_KEY environment variable.\n")

    try:
        api_key = input("Enter your Anthropic API key (or press Enter to skip): ").strip()
        if api_key:
            if api_key.startswith("sk-ant-"):
                set_api_key(api_key)
                print("\nAPI key saved!")
                return api_key
            else:
                print("\nWarning: Key doesn't look like an Anthropic key (should start with sk-ant-)")
                confirm = input("Save anyway? [y/N]: ").strip().lower()
                if confirm == "y":
                    set_api_key(api_key)
                    print("\nAPI key saved!")
                    return api_key
        return None
    except (KeyboardInterrupt, EOFError):
        print("\nSkipped.")
        return None


def ensure_setup() -> bool:
    """Run first-time setup if needed. Returns True if ready to run."""
    # Check API key
    if not get_api_key():
        key = prompt_for_api_key()
        if not key:
            print("\nNo API key configured. Set ANTHROPIC_API_KEY or run: xfeed config --api-key YOUR_KEY")
            return False

    # Check Playwright browser
    if not ensure_playwright_browser():
        return False

    return True
