# XFEED

A CLI tool that filters your X (Twitter) timeline using Claude AI, surfacing content that matches your interests while filtering out noise, rage bait, and irrelevant posts.

## Features

- **AI-Powered Filtering**: Uses Claude Haiku to score tweets (0-10) based on your personal objectives
- **Rich Mosaic Display**: Visual heatmap where tweet tiles are sized and colored by relevance
- **Reasoning Quality Scoring**: Boosts posts with evidence, mechanisms, and careful argumentation; penalizes vague claims and rage bait
- **Engagement Tracking**: See your notifications, likes, and retweets at a glance
- **Interactive Controls**: Adjust threshold and count on-the-fly without restarting
- **Background Refresh**: UI stays responsive during scraping operations
- **Human-like Throttling**: Randomized delays to avoid bot detection

## Getting Started

### Prerequisites

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/)
- A logged-in X session in your default browser (Chrome, Firefox, or Safari)

### Installation

```bash
# Clone the repository
git clone https://github.com/ericksoa/xfeed.git
cd xfeed

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium
```

### Configuration

1. **Set your Anthropic API key**:

   Create a `.env` file in the project root:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

2. **Customize your objectives**:

   Edit `~/.xfeed/objectives.md` to define what you care about:
   ```markdown
   # Things I Care About

   ## Technology
   - AI/ML research and breakthroughs
   - Developer tools and productivity
   - Open source projects

   ## Topics
   - Distributed systems
   - Programming languages

   ## People
   - @karpathy - Always include
   - @simonw - Always include

   ## Exclude
   - Crypto/NFT promotions
   - Engagement bait / rage bait
   - Drama and controversy
   ```

### Usage

#### Mosaic View (Recommended)

The mosaic shows a visual heatmap of your filtered feed:

```bash
xfeed mosaic
```

**Keyboard shortcuts:**
| Key | Action |
|-----|--------|
| `1-9` | Open tweet in browser |
| `+` / `-` | Adjust relevance threshold |
| `c` | Cycle tweet count (10/20/50/100) |
| `o` | Open objectives in $EDITOR |
| `r` | Manual refresh |
| `q` | Quit |

Options:
```bash
xfeed mosaic --refresh 10      # Refresh every 10 minutes
xfeed mosaic --threshold 8     # Only show score 8+ tweets
xfeed mosaic --count 50        # Fetch 50 tweets per refresh
xfeed mosaic --no-engagement   # Skip notifications scraping
```

#### Simple Fetch

Fetch and display filtered tweets in a list format:

```bash
xfeed fetch                    # Default: 50 tweets, threshold 7
xfeed fetch -n 100             # Fetch 100 tweets
xfeed fetch -t 9               # Only high-relevance tweets
xfeed fetch --raw              # Show all tweets unfiltered
xfeed fetch --json             # Output as JSON
```

#### Watch Mode

Background watcher that prints updates periodically (great for ambient awareness):

```bash
xfeed watch                    # Print top 3 tweets every 5 minutes
xfeed watch -i 10 -t 9         # Every 10 min, only 9+ scores
```

#### Ticker Mode

CNN-style rotating display:

```bash
xfeed ticker                   # Rotate tweets every 5 seconds
xfeed ticker --compact         # 2-line tmux-friendly display
```

### Commands Reference

| Command | Description |
|---------|-------------|
| `xfeed fetch` | Fetch and filter timeline |
| `xfeed mosaic` | Visual heatmap display |
| `xfeed watch` | Background periodic updates |
| `xfeed ticker` | Rotating ticker display |
| `xfeed config --show` | Show current configuration |
| `xfeed objectives --edit` | Edit objectives file |

## How It Works

1. **Scraping**: Uses Playwright to scrape your X home timeline using cookies from your logged-in browser session
2. **Filtering**: Sends tweets to Claude Haiku in batches with your objectives
3. **Scoring**: Claude scores each tweet 0-10 and provides a reason
4. **Display**: High-scoring tweets are shown in a rich terminal UI

### Scoring Factors

The AI considers these factors when scoring:

**Boosts (+1 to +2):**
- `mechanism` - Explains WHY/HOW something works
- `tradeoffs` - Analyzes pros/cons
- `evidence` - Links to papers, data, sources
- `uncertainty` - Explicit hedging
- `dissent_rigorous` - Contrarian view with strong reasoning

**Penalties (-1 to -2):**
- `vague` - Claims without mechanism
- `unsourced` - Breaking claims without attribution
- `rhetorical` - Emotional manipulation
- `overconfident` - Certain claims about uncertain topics

## Configuration

Configuration is stored in `~/.xfeed/`:

| File | Purpose |
|------|---------|
| `config.yaml` | Settings (threshold, batch size, etc.) |
| `objectives.md` | Your interests and exclusions |
| `cookies.json` | Cached X session cookies |

### Config Options

```yaml
# ~/.xfeed/config.yaml
relevance_threshold: 7         # Default minimum score
default_tweet_count: 50        # Default tweets to fetch
batch_size: 15                 # Tweets per API call

# Exploration / Serendipity
exploration_rate: 0.1          # % of feed for new authors
exploration_min_quality: 7     # Min score for unknown authors
exploration_cooldown_hours: 24 # Cooldown before repeating author

# Reasoning quality
reasoning_boost_max: 2         # Max boost for quality factors
reasoning_penalty_max: 2       # Max penalty for low quality

# Contrarian handling
dissent_min_rigor: 6           # Min rigor for dissent bonus
dissent_bonus_cap: 2           # Max boost for contrarian content
```

## Development

```bash
# Run tests
pytest tests/ -v

# Type checking
mypy src/xfeed

# Format code
black src/xfeed tests
```

## License

MIT

## Acknowledgments

- Built with [Claude](https://claude.ai) by Anthropic
- Terminal UI powered by [Rich](https://github.com/Textualize/rich)
- Browser automation via [Playwright](https://playwright.dev)
