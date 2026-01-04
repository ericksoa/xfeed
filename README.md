# XFEED

A CLI tool that filters your X (Twitter) timeline using Claude AI, surfacing content that matches your interests while filtering out noise.

## Quick Start

```bash
# Install with pipx (recommended)
pipx install git+https://github.com/ericksoa/xfeed.git

# Or with pip
pip install git+https://github.com/ericksoa/xfeed.git

# Run it
xfeed mosaic
```

On first run, xfeed will:
1. Prompt for your [Anthropic API key](https://console.anthropic.com/)
2. Auto-install the browser component
3. Create a default objectives file at `~/.xfeed/objectives.md`

**Prerequisite**: You must be logged into X (twitter.com) in Chrome.

## Features

- **AI-Powered Filtering**: Claude Haiku scores tweets 0-10 based on your interests
- **Rich Mosaic Display**: Visual heatmap sized by relevance
- **Reasoning Quality**: Boosts evidence-based posts, penalizes rage bait
- **Interactive Controls**: Adjust filters on-the-fly
- **Engagement Tracking**: See your notifications at a glance

## Usage

### Mosaic View (Recommended)

```bash
xfeed mosaic
```

**Keyboard shortcuts:**
| Key | Action |
|-----|--------|
| `1-9` | Open tweet in browser |
| `+` / `-` | Adjust relevance threshold |
| `c` | Cycle tweet count |
| `o` | Edit objectives |
| `r` | Refresh |
| `q` | Quit |

### Other Commands

```bash
xfeed fetch              # List view of filtered tweets
xfeed watch              # Periodic updates (ambient mode)
xfeed ticker             # CNN-style rotating display
xfeed objectives --edit  # Edit your interests
xfeed config --show      # Show configuration
```

## Customizing Your Feed

Edit `~/.xfeed/objectives.md` to define what you care about:

```markdown
# Things I Care About

## Topics
- AI/ML research
- Developer tools
- Open source

## People
- @karpathy
- @simonw

## Exclude
- Crypto promotions
- Rage bait
- Drama
```

## Configuration

Set via environment variable or xfeed will prompt on first run:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

All config is stored in `~/.xfeed/`:
- `.env` - API key (chmod 600)
- `config.yaml` - Settings
- `objectives.md` - Your interests

## License

MIT
