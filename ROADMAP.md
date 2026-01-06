# XFEED Roadmap

A curated list of improvements to make xfeed the best X client for cutting through noise and surfacing signal.

---

## High Impact

### 1. Thread Awareness
Detect when a high-score tweet is part of a thread. Offer to load full context with `[t]hread` key. Many valuable insights are buried in threads, not standalone tweets.

### 2. "While You Were Away" Digest
Summarize what happened since last check. Cluster by topic, show top 3 tweets per topic. Perfect for catching up after being offline.

### 3. Link Expansion
Fetch and summarize linked articles inline using Claude. "This tweet links to: [2-sentence summary]". No more clicking through to understand context.

### 4. Deduplication
Collapse duplicate content: same link shared by multiple people, quote tweets of the same original, rephrased versions of the same news. Show "5 people shared this" instead of 5 tiles.

## Medium Impact

### 5. Bookmarks / Save
Press `[s]` to save tweet to local SQLite database. `xfeed saved` command to review later. Export to markdown for sharing or archival.

### 6. Quick Actions
`[l]ike`, `[R]etweet` directly from mosaic. Requires write access via browser session. Powerful for engagement workflow.

### 7. Multiple Objective Profiles
`xfeed mosaic --profile work` vs `--profile learning`. Different objectives files for different contexts. Switch profiles with `[p]` key while running.

### 8. Conversation Loader
Press `[T]` to load replies and conversation for a selected tweet. See the discussion without leaving the terminal.

### 9. Desktop Notifications
Optional system notifications when exceptionally high-relevance content appears (score 9+). Ambient awareness without constant watching.

## Nice to Have

### 10. Source Diversity Indicator
Warn if >50% of displayed feed comes from the same 3 accounts. Encourage diverse information diet.

### 11. Sentiment Overlay
Color-code tiles by sentiment in addition to relevance. Distinguish excited/optimistic (green) from skeptical/critical (orange) from heated/angry (red).

### 12. Time-Series View
`xfeed trends` showing topic volume over past week. What's heating up? What's cooling down? Requires historical data collection.

### 13. Export Digest
`xfeed digest --since yesterday --format markdown` for sharing curated content. Email digest, blog post draft, or team Slack update.

### 14. Search Within Results
`/search` command to filter currently displayed tweets by keyword. Find that tweet you saw earlier without re-fetching.

---

## Completed Features

- [x] Home timeline fetching with Playwright
- [x] Claude Haiku relevance filtering with custom objectives
- [x] Rich terminal mosaic visualization
- [x] Engagement tracking (notifications, profile tweets)
- [x] Interactive controls (+/- threshold, count cycling, objectives editing)
- [x] Smart rate limiting with variable delays
- [x] Keyboard shortcuts for opening tweets in browser
- [x] Vibe/topic extraction and display
- [x] Serendipity/Exploration mode (discover new authors)
- [x] Reasoning quality scoring (mechanism, evidence, tradeoffs)
- [x] Contrarian-but-serious allowance (rigorous dissent)
- [x] Author reputation tracking with SQLite persistence
- [x] Trusted/rising author badges in mosaic
