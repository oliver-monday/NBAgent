# NBAgent — Roadmap - Off Season / Deferred

---

## Open Items

### Frontend

#### Per-player streak pills on pick cards
**Deferred from 2026-03-25** (removed system-wide streak pill as incorrect stopgap)

Compute each player's individual hit streak at their specific pick tier from `picks.json` history at site build time. Display a streak pill on the pick card only when ≥3 consecutive hits at that player's exact `pick_value`. This is distinct from the system-wide prop-type streak counter that was removed — it would reflect the individual player's recent performance at that specific line, which is meaningful context.

Implementation sketch: `build_site.py` reads `picks.json`, groups by `(player_name, prop_type, pick_value)`, walks backward from most recent graded pick counting consecutive HITs; if streak ≥ 3, attach `player_streak` count to the pick object and render pill in `buildMicroStats()`.

#### On/Off Court Usage Parsing (Headless Browser)
**Deferred from 2026-03-25** (parse_onoff_usage rewritten as graceful skip)

The On/Off Court Stats panel on Rotowire's `nba-lineups.php` is loaded via JavaScript after a button click — the content is not present in the server-rendered HTML that `requests.get()` fetches. `parse_onoff_usage()` currently returns `{}` cleanly with a diagnostic log line.

A future implementation using a headless browser (e.g. Playwright) could click the On/Off button, wait for the AJAX panel to render, then parse the usage data. This would restore the `[USG_SPIKE]` annotations in the analyst's quant context block and the `onoff_usage` data in `lineups_today.json`.

Implementation sketch: Replace `fetch_rotowire_html()` with a Playwright-based fetch for the lineups page only; click each team's On/Off button sequentially; capture the rendered panel HTML; parse with the original `parse_onoff_usage` logic (preserved in git history). Playwright adds a ~500ms overhead per team (15 teams × 0.5s = ~8s total). Evaluate whether the `[USG_SPIKE]` signal justifies the added complexity and CI dependency.

**Where:** `ingest/rotowire_injuries_only.py` only. No agent changes needed — `load_lineup_context()` in `analyst.py` already handles `onoff_usage: {}` gracefully.

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

### Pending Backtests (Offseason)

#### H22 — Within-Window Sequential Slope
**Status: DEFERRED TO OFFSEASON — motivated by Randle 2026-03-25**
**Mode: `--mode sequential-slope` (not yet implemented)**

**Motivation:** The current trend signal (`compute_trend()`) computes a binary label by comparing the L5 average to the L20 average. This misses within-window momentum: a player whose last 5 games show a monotone decline (32→32→21→19→9) would register `trend=up` if their L5 average still exceeds a depressed L20 baseline. The Randle case on 2026-03-25 was the prototype — absence-aware trend correctly overrode to `stable` in that instance, but the underlying L5-vs-L20 mechanism remains susceptible to sequences with this shape.

**Hypothesis:** OLS slope computed across the L20 window (or within the absence window) is a better predictor of next-game tier hit rate than the current binary L5-vs-L20 delta comparison.

**Test design:**
- For each player-game in the log, fit an OLS slope through the last 20 values of each stat (excluding DNPs)
- Classify: `slope_up` (positive, above noise threshold), `slope_flat`, `slope_down` (negative, above noise threshold); threshold TBD (candidate: ≥0.15 units/game)
- Compare next-game tier hit rate for slope_up / slope_flat / slope_down vs. current up/stable/down labels
- Gate: ≥15 instances per bucket, ≥10pp separation to replace current signal

**Sample constraint:** OLS slope requires stable role context across the full L20 window. Split the analysis by (a) all whitelisted players and (b) players with stable minute allocations (avg_minutes variance ≤ 20% across window). Category (b) is the more honest test — high-variance minutes players add structural noise the slope cannot distinguish from performance trend. Expected qualifying instances ~200+ at full-season volume.

**Why not now:** Season ends April 12, 2026. Implementing a new quant signal in the final 3 weeks introduces timing risk with no opportunity to validate in production before the year ends. Evaluate as a replacement for `compute_trend()` next season if the backtest clears the threshold.

**Where:** `agents/backtest.py` (new mode), then `agents/quant.py` if verdict is KEEP.

---

#### H23 — Regime-Adjusted Without-Star Trend Predictive Validity
**Status: DEFERRED TO OFFSEASON — prerequisite: absence-aware trend live in production**
**Mode: `--mode absence-trend-validity` (not yet implemented)**

**Motivation:** The absence-aware trend fix (2026-03-25) overrides standard L5-vs-L20 trend labels with within-absence-window trend when `key_teammate_absent.n_games >= 5`. The fix is theoretically sound (eliminates regime-crossing artifacts) but has not been validated against actual pick outcomes. Before promoting absence_trend to a directive prompt rule (e.g., `trend=down` in absence window → mandatory tier step-down), the signal needs a proper backtest.

**Hypothesis:** Within-absence-window trend (`absence_trend`) is a more reliable predictor of next-game tier hit rate than standard trend for players whose star teammate was absent during the window.

**Test design:**
- Filter to games where `key_teammate_absent` is active (player's top-PPG whitelisted teammate was absent)
- For each qualifying player-game, compute `absence_trend` as of that game date
- Compare next-game tier hit rate for `absence_trend=up / stable / down` vs. standard `trend=up / stable / down` at the same pick tiers
- Measure whether absence_trend provides lift above standard trend as a predictor
- Gate: ≥15 instances per bucket; lift > 5pp to warrant directive rule; annotation-only if lift 2–5pp

**Sample constraint:** In-season 2025-26 data is insufficient — the `key_teammate_absent` population is small (requires ≥5 games without the star; most stars miss fewer than that in a single season). Full validation requires 2+ seasons of data. Do not run this backtest until the 2026-27 season has at least 60 days of data.

**Prerequisite:** `absence_trend` field must be live in production (implemented 2026-03-25) and accumulating in `player_stats.json` for the full 2026-27 season before analysis is tractable.

**Why not now:** Single-season sample is too thin for the target population. The absence-aware trend override is shipped as a correctness fix (eliminating a known artifact), not as a validated directive signal. The backtest determines whether it also has predictive validity beyond artifact elimination.

**Where:** `agents/backtest.py` (new mode). If KEEP verdict, wire into `build_pick_prompt()` as a note alongside the existing `Without [X]` directive rule.

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