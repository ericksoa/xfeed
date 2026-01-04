# Things I Care About

## AI Research & Industry
- New papers, especially on LLMs, reasoning, agents, and alignment
- Model releases and benchmarks (GPT, Claude, Gemini, Llama, open-source)
- Research from Anthropic, OpenAI, DeepMind, Meta AI, academic labs
- AI safety and alignment work
- Novel architectures, training techniques, scaling insights
- AI tooling, infrastructure, and developer experience
- Thoughtful AI commentary from researchers (not hype)

## Technical Content
- Systems programming, Rust, Python
- Developer tools and productivity
- Open source projects worth knowing about
- Interesting engineering problems and solutions

## Major News (Real Events Only)
- Significant world events (natural disasters, elections, major policy)
- Tech industry news with actual substance
- Scientific breakthroughs beyond AI
- Must be from credible sources or firsthand accounts

## People to Prioritize
- Known AI researchers and lab employees
- Technical founders sharing insights
- Academics with domain expertise

## EXCLUDE (Score 0-2)
- Rage bait, outrage farming, "you won't believe..."
- Hot takes designed to provoke, not inform
- Crypto/NFT/Web3 promotion
- Engagement farming ("RT if you agree", ratio attempts)
- Vague motivational content
- AI doomer hysteria without substance
- AI hype without technical grounding
- Celebrity gossip, sports, entertainment news
- Political tribalism and culture war content
- Ads, sponsored content, affiliate marketing
- Threads that are mostly self-promotion

## Filtering Guidelines
- Prefer signal over noise
- A tweet from a credible source > viral tweet from unknown
- Original insights > reactions to others' takes
- Be skeptical of "breaking news" without sources
- Technical depth is a plus
- If it feels like it's trying to make me angry, it's probably not worth showing

---

## Serendipity / Exploration

Allow discovery of valuable new voices without letting in noise:

- Unknown accounts CAN score well IF they demonstrate:
  - Technical depth with specific details
  - Clear reasoning with mechanisms explained
  - Evidence, citations, or links to primary sources
- Unknown accounts that score well should be flagged as "exploration" candidates
- Still apply all exclusion rules - exploration does not override quality filters

**Anti-gaming:**
- No engagement farming patterns even from new accounts
- No "hot take" style even if technically adjacent
- Prefer accounts with real profile info over anon/meme accounts

---

## Reasoning Quality Scoring

Evaluate argument quality as a scoring component (not just topic match):

**BOOST (+1 to +2 points) for:**
- Causal reasoning: "X happens because Y mechanism"
- Tradeoff analysis: "This is good for A but bad for B"
- Evidence: links to papers, data, primary sources
- Explicit uncertainty: "I think", "evidence suggests", "unclear but"
- Stated assumptions: acknowledges what they're taking for granted

**PENALIZE (-1 to -2 points) for:**
- Vague claims: "AI will change everything" with no mechanism
- Unattributed "breaking" news without sources
- Excessive rhetorical framing designed to provoke
- Confident claims about uncertain topics without hedging
- Pure prediction with no reasoning chain

**Explanation requirement:**
Each score should note which reasoning factors contributed (e.g., "mechanism +1, no source -1").

---

## Contrarian-but-Serious Allowance

Valuable dissent should not be filtered out:

- Dissenting/contrarian takes are ALLOWED if they include:
  - Evidence or citations supporting the contrarian view
  - Mechanism explaining why the consensus might be wrong
  - Careful argumentation acknowledging the opposing view

- Dissent WITHOUT rigor is still excluded:
  - "Everyone is wrong and here's my hot take" = excluded
  - "The data actually shows X, contrary to popular belief" = included

**Rubric:**
- Calculate `rigor_score` based on reasoning quality factors above
- Only apply `dissent_bonus` if `rigor_score >= 6`
- Cap dissent bonus at +2 (don't over-reward contrarians)

---

## Interpretation Rules

**Unknown accounts:**
- Treat with higher scrutiny but not automatic exclusion
- Quality signals matter more: depth, evidence, hedging
- Check for engagement farming patterns regardless of follower count

**Sources and citations:**
- Links to arxiv, papers, official docs = strong positive signal
- Links to other tweets/threads = neutral (depends on context)
- No links for factual claims = negative signal
- "Trust me" or "sources say" without specifics = strong negative

**Uncertainty handling:**
- Explicit uncertainty is GOOD ("I think", "possibly", "early data suggests")
- False confidence is BAD ("This will definitely", "Everyone knows")
- Distinguish epistemic humility from wishy-washy non-statements
