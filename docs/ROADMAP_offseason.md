# NBAgent — Roadmap - Off Season / Deferred

---

## Open Items

### Frontend

#### Per-player streak pills on pick cards
**Deferred from 2026-03-25** (removed system-wide streak pill as incorrect stopgap)

Compute each player's individual hit streak at their specific pick tier from `picks.json` history at site build time. Display a streak pill on the pick card only when ≥3 consecutive hits at that player's exact `pick_value`. This is distinct from the system-wide prop-type streak counter that was removed — it would reflect the individual player's recent performance at that specific line, which is meaningful context.

Implementation sketch: `build_site.py` reads `picks.json`, groups by `(player_name, prop_type, pick_value)`, walks backward from most recent graded pick counting consecutive HITs; if streak ≥ 3, attach `player_streak` count to the pick object and render pill in `buildMicroStats()`.

---

### Matchup Signals Queue

Design philosophy: the Analyst already has a solid quantitative matchup foundation (positional DvP, vs_soft/vs_tough splits, game pace, spread context). The following proposals address gaps where rolling averages give a misleading picture because something material has changed that the numbers alone cannot capture.

#### M1 — Situational Player Profiles (DEFERRED TO OFFSEASON)
**Priority: OFFSEASON — multi-season data required; not tractable within a single season**
**Replaces the original narrow H2H splits design; scope significantly expanded after March 2026 discussion**

**What this is really about:** The original M1 framing — compute per-player tier hit rate against today's specific opponent over a single season — is too narrow and too sample-limited to be honest. NBA teams play each opponent only 2–4 times per season. By the time you have 5+ matchups (the original minimum), the season is nearly over, and there's no subsequent game to act on. The regular season ends April 12, 2026 — the mid-April backtest timing in the original design was almost exactly end-of-season, making it operationally useless for in-season picks.

**The broader hypothesis worth investigating:** There is a real class of player-level situational performance patterns that are statistically grounded but currently invisible to the system. Examples that motivated this:
- Players who consistently over- or under-perform against specific opponents (scheme familiarity, matchup history, rivalry dynamics)
- Players who elevate in big-market road arenas (MSG, Crypto.com, TD Garden) — the "big stage" effect
- Players who perform differently in nationally televised games vs. local broadcasts
- Players with historically strong/weak records against specific defensive archetypes (switching teams, zone-heavy teams, physical bigs) across multiple seasons
- Career rivalries between individual players (Ant vs. Luka, etc.) that show up in stat lines, not just narrative

**Why not now:** All of these require multi-season data with consistent role context to be meaningful. A single-season sample has too few instances per condition, and roster/role changes between seasons require careful controls. The investigation belongs in the offseason when there's time to assemble clean multi-season datasets and run honest backtests.

**Relationship to Stay Away flag:** This offseason investigation is the right long-term feeder for the "Stay Away?" UI caution flag (see Frontend open items). The pattern isn't "the system should hard-skip this pick" — it's "here is a real tension between the statistical case and a situational risk factor the numbers don't fully capture." Small-sample situational splits are well-suited to informing a human hold decision, not to encoding as directive system rules.

**Offseason research agenda (when ready):**
- Assemble 2–3 seasons of `player_game_log.csv` data with consistent player-team mapping
- Define and test: opponent-specific hit rate splits; home arena performance profiles; national TV game splits; opponent defensive archetype splits (requires team-level scheme tagging)
- Validate each against a null hypothesis of no effect — most narrative-driven splits will not survive honest testing, and that's the finding worth knowing
- For signals that survive: design annotation-only injection into player profiles or Stay Away flag triggers; do NOT encode as directive rules without further validation
- Consider: which signals are stable enough across seasons to be useful in-season, and which require annual recalibration?

**Where:** Offseason project. No current-season code changes.

---
## Research

#### **RAG with a purpose-built NBA knowledge base**

This is the option I'd actually push you toward first, because it solves 80% of the staleness problem without fine-tuning complexity. You build a structured, queryable database of NBA facts — rosters, role changes, coach schemes, recent performance narratives — and your agents retrieve only what's relevant before each reasoning call.

**The key difference from what you have now:** instead of a static nba_season_context.md that gets injected whole, you have a database where the agent asks "what do I need to know about Darius Garland today?" and gets back a focused, current, authoritative answer. The retrieval is dynamic; the database is continuously updated.

**Cost:** Mostly your time. Vector databases (Pinecone, Weaviate, or even a simple local setup) have free tiers. The embedding API calls are pennies. The real investment is building the ingestion pipeline that keeps the database current.

**Technical barrier:** Medium. This is closer to what you've already built — it's Python scripting and API calls, not ML training. With Claude as a coding partner it's achievable.

---

#### **Fine-tuning an existing model**

Fine-tuning means taking a pre-trained model and continuing to train it on your specific domain data — not from scratch, just adjusting the weights to reinforce NBA-specific knowledge. Anthropic doesn't currently offer fine-tuning on Claude, but OpenAI does on GPT-4o, and open-source models (Llama 3, Mistral) can be fine-tuned on your own hardware or cloud.

**What this would actually buy you:** a model that has corrected factual priors on rosters, trades, and current-season context. It would still use the same underlying reasoning architecture — it just wouldn't "think" Luka is a Maverick at a weights level.

**Cost reality:** Fine-tuning GPT-4o through OpenAI's API costs roughly $25 per million training tokens. A comprehensive NBA dataset — play-by-play logs, box scores, roster moves, news archives for 2023-2026 — might run 50-200 million tokens depending on how thorough you are. So $1,250–$5,000 for the training run, plus ongoing re-training as the season progresses (you'd want to re-fine-tune monthly to stay current). The data preparation is the harder part — getting all that into clean training format is weeks of work, or a developer you'd need to hire.

**Technical barrier for you personally:** High. Fine-tuning requires understanding training data formatting (JSONL with prompt/completion pairs), running training jobs via API or cloud GPU, and evaluating whether the fine-tuned model actually improved. This is doable but would need either a technical collaborator or significant learning investment.