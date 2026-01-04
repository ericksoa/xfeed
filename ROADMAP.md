# XFEED Roadmap

A curated list of improvements to make xfeed the best X client for cutting through noise and surfacing signal.

---

## In Progress: Feed Quality Improvements (Jan 2026)

### Serendipity / Exploration Mode
Prevent the feed from becoming an echo chamber of the same 20 accounts.

- Inject a small percentage of candidates from unknown/new accounts
- Only when the post demonstrates technical depth or strong reasoning
- Bounded by: low frequency, diversity-aware, strict anti-manipulation filters
- **Config knobs**:
  - `exploration_rate` (default: 0.1) - % of feed slots for exploration
  - `exploration_min_quality` (default: 7) - minimum score for unknown authors
  - `exploration_diversity_window` (default: 50) - posts to consider for diversity
  - `exploration_cooldown_per_author` (default: 24h) - avoid repeating new authors

### Reasoning Quality Scoring
Score tweets on argument quality, not just topic match.

**Boosts for:**
- Causal reasoning / mechanism explanations
- Tradeoff analysis ("X is good for Y but bad for Z")
- Evidence / citations / links to primary sources
- Explicit uncertainty or stated assumptions

**Penalties for:**
- Vague claims with no mechanism ("AI will change everything")
- "Breaking" claims without sources
- Excessive rhetorical framing / emotional manipulation

Each scored post includes an explanation string listing top contributing factors.

### Contrarian-but-Serious Allowance
Allow valuable dissent without letting in outrage bait.

- Dissenting/contrarian takes allowed IF they include evidence, mechanisms, or careful argumentation
- Still exclude tribalism and rage bait
- **Rubric**: `dissent_score` positive only when `rigor_score` above threshold
- **Config knobs**:
  - `dissent_min_rigor` (default: 6) - minimum rigor for dissent bonus
  - `dissent_bonus_cap` (default: 2) - max boost for contrarian content

---

## High Impact

### 1. Thread Awareness
Detect when a high-score tweet is part of a thread. Offer to load full context with `[t]hread` key. Many valuable insights are buried in threads, not standalone tweets.

### 2. Author Reputation Tracking
Build a local SQLite database of authors. Track which ones consistently score high over time. Auto-boost trusted voices, surface new voices that are trending upward.

### 3. "While You Were Away" Digest
Summarize what happened since last check. Cluster by topic, show top 3 tweets per topic. Perfect for catching up after being offline.

### 4. Link Expansion
Fetch and summarize linked articles inline using Claude. "This tweet links to: [2-sentence summary]". No more clicking through to understand context.

### 5. Deduplication
Collapse duplicate content: same link shared by multiple people, quote tweets of the same original, rephrased versions of the same news. Show "5 people shared this" instead of 5 tiles.

## Medium Impact

### 6. Bookmarks / Save
Press `[s]` to save tweet to local SQLite database. `xfeed saved` command to review later. Export to markdown for sharing or archival.

### 7. Quick Actions
`[l]ike`, `[R]etweet` directly from mosaic. Requires extending cookie auth for write access. Risky but powerful for engagement workflow.

### 8. Multiple Objective Profiles
`xfeed mosaic --profile work` vs `--profile learning`. Different objectives files for different contexts. Switch profiles with `[p]` key while running.

### 9. Conversation Loader
Press `[T]` to load replies and conversation for a selected tweet. See the discussion without leaving the terminal.

### 10. Desktop Notifications
Optional system notifications when exceptionally high-relevance content appears (score 9+). Ambient awareness without constant watching.

## Nice to Have

### 11. Source Diversity Indicator
Warn if >50% of displayed feed comes from the same 3 accounts. Encourage diverse information diet.

### 12. Sentiment Overlay
Color-code tiles by sentiment in addition to relevance. Distinguish excited/optimistic (green) from skeptical/critical (orange) from heated/angry (red).

### 13. Time-Series View
`xfeed trends` showing topic volume over past week. What's heating up? What's cooling down? Requires historical data collection.

### 14. Export Digest
`xfeed digest --since yesterday --format markdown` for sharing curated content. Email digest, blog post draft, or team Slack update.

### 15. Search Within Results
`/search` command to filter currently displayed tweets by keyword. Find that tweet you saw earlier without re-fetching.

---

## Completed Features

- [x] Home timeline scraping with Playwright
- [x] Claude Haiku relevance filtering with custom objectives
- [x] Rich terminal mosaic visualization
- [x] Engagement tracking (notifications, profile tweets)
- [x] Interactive controls (+/- threshold, count cycling, objectives editing)
- [x] Smart rate limiting with variable delays
- [x] Keyboard shortcuts for opening tweets in browser
- [x] Vibe/topic extraction and display
