---
name: xfeed
description: Fetch and display filtered X (Twitter) timeline based on your interests. Shows AI/ML research, developer tools, and technical content while filtering out noise, rage bait, and irrelevant posts. Uses Claude Haiku to score relevance against your objectives.
---

# XFeed - Filtered X Timeline

Fetch your X timeline and filter it based on your interests defined in ~/.xfeed/objectives.md.

## When to Use This Skill

Use this skill when users want to:
- Check their X/Twitter timeline
- See filtered, relevant tweets
- Catch up on AI/ML news and research
- See what's happening in tech without the noise

**Trigger keywords:** twitter, x feed, timeline, tweets, what's happening, tech news, AI news

## Requirements

The xfeed CLI must be installed and configured:
- Python virtual environment in the project directory
- Chrome browser logged into X (for cookie extraction)
- Anthropic API key in `.env`

## Commands

### Fetch Filtered Timeline
```bash
xfeed fetch --count 30
```

### Fetch More Tweets
```bash
xfeed fetch --count 50
```

### Fetch with Lower Threshold (More Results)
```bash
xfeed fetch --count 30 --threshold 5
```

### View Raw Unfiltered Feed
```bash
xfeed fetch --count 20 --raw
```

### View Current Objectives
```bash
xfeed objectives
```

### Check Configuration
```bash
xfeed config --show
```

## How It Works

1. Extracts X session cookies from Chrome browser
2. Uses Playwright to fetch your home timeline
3. Sends tweets in batches to Claude Haiku for relevance scoring
4. Displays tweets scoring above threshold (default: 7/10)
5. Shows relevance reason for each tweet

## Objectives

Your interests are defined in `~/.xfeed/objectives.md`. Current focus:
- AI/ML research and breakthroughs
- Model releases and benchmarks
- AI safety and alignment
- Developer tools and productivity
- Major news (real events only)

Exclusions: rage bait, crypto promotion, engagement farming, political tribalism

## Output Format

Each tweet shows:
- Author and handle
- Time ago
- Relevance score [X/10]
- Tweet content
- Engagement metrics
- Why it's relevant

## Troubleshooting

**"No cookies found"**: Log into x.com in Chrome first
**"Not logged in"**: Your X session expired, log in again in Chrome
**API errors**: Check Anthropic API key in `.env`
