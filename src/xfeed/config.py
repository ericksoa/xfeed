"""Configuration management for XFeed."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
import yaml

# Load .env from project directory
_project_root = Path(__file__).parent.parent.parent
load_dotenv(_project_root / ".env")


CONFIG_DIR = Path.home() / ".xfeed"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
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
    """Save Anthropic API key to config."""
    config = load_config()
    config["anthropic_api_key"] = api_key
    save_config(config)


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
