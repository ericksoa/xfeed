# XFEED Implementation Plan

## Feed Quality Improvements (Jan 2026)

### Features Added

#### 1. Serendipity / Exploration Mode
- Injects high-quality tweets from unknown/new authors at configurable rate
- Bounded by: minimum quality threshold, author cooldown, diversity sampling
- Exploration candidates are sampled AFTER base exclusion filtering
- Maximum N exploration posts per refresh (default: 10% of feed)
- Authors marked `[EXPLORE]` in reason string for transparency

#### 2. Reasoning Quality Scoring
- LLM prompt now includes factor-based scoring instructions
- Boost factors: `mechanism`, `tradeoffs`, `evidence`, `uncertainty`, `assumptions`
- Penalty factors: `vague`, `unsourced`, `rhetorical`, `overconfident`
- Each tweet's reason includes factor breakdown: `"Great insight [+mechanism, +evidence]"`

#### 3. Contrarian-but-Serious Allowance
- New factor `dissent_rigorous` flags contrarian content with strong reasoning
- Dissent bonus only applied when rigor score meets threshold
- Bonus capped to prevent over-rewarding contrarian views
- Low-rigor dissent treated normally (no boost, may be penalized)

### Files Touched

| File | Changes |
|------|---------|
| `src/xfeed/filter.py` | New SYSTEM_PROMPT with factor scoring, exploration sampling logic, dissent bonus calculation, `_build_explanation()` helper |
| `src/xfeed/config.py` | Added config knobs: `exploration_rate`, `exploration_min_quality`, `exploration_cooldown_hours`, `dissent_min_rigor`, `dissent_bonus_cap`, `reasoning_boost_max`, `reasoning_penalty_max` |
| `~/.xfeed/objectives.md` | Added sections: Serendipity, Reasoning Quality Scoring, Contrarian-but-Serious, Interpretation Rules |
| `objectives.md` (repo) | Mirror of user objectives for reference |
| `ROADMAP.md` | Added "In Progress" section documenting these features |
| `tests/test_filter.py` | Unit tests for new scoring logic |

### Config Knobs Added

```yaml
# Exploration / Serendipity
exploration_rate: 0.1          # % of feed for exploration candidates
exploration_min_quality: 7     # Min score for unknown authors
exploration_cooldown_hours: 24 # Hours before repeating new author

# Reasoning quality
reasoning_boost_max: 2         # Max boost for quality factors
reasoning_penalty_max: 2       # Max penalty for quality factors

# Contrarian handling
dissent_min_rigor: 6           # Min rigor for dissent bonus
dissent_bonus_cap: 2           # Max boost for contrarian content
```

### TODOs / Future Work

- [ ] Persist exploration author cache across sessions (currently in-memory)
- [ ] Add CLI command to view/clear exploration cache
- [ ] Track author reputation over time (requires SQLite)
- [ ] Add `--no-exploration` flag to disable exploration mode
- [ ] Expose factor breakdown in mosaic UI (currently only in reason string)
- [ ] Add metrics: % of feed that is exploration, avg rigor score, etc.

### Test Plan

Run tests with:
```bash
source .venv/bin/activate
pytest tests/ -v
```

#### Test Cases

1. **Exclusion rules still apply in exploration**
   - Rage bait from unknown author → excluded (score 0-1)
   - Engagement farming from unknown author → excluded

2. **Contrarian without rigor NOT boosted**
   - Contrarian take with no evidence → no dissent bonus
   - Contrarian take with `vague` factor → may be penalized

3. **Mechanism/evidence posts are boosted**
   - Post with `mechanism` factor → explanation shows `[+mechanism]`
   - Post with `evidence` factor → explanation shows `[+evidence]`

4. **Explanation strings include factors**
   - All scored posts have reason with factor breakdown
   - Format: `"Base reason [+factor1, -factor2]"`

5. **Exploration sampling is deterministic**
   - Same seed → same exploration candidates selected
   - Candidates interspersed at regular intervals

6. **Author cooldown works**
   - Author shown as exploration → marked in cache
   - Same author within cooldown → not shown again as exploration

### Architecture Notes

- Scoring is still done by Claude Haiku (no local ML)
- Factor extraction is LLM-based, not heuristic
- Exploration sampling uses seeded RNG for reproducibility
- Author cache is in-memory (resets on process restart)
- O(n) complexity over candidates maintained
