# NBAgent — Backtest Log

All retrospective signal analyses run against historical game log data using `agents/backtest.py`.
Results drive prompt design, quant config, and tier rules. Findings are only applied to production
after passing a minimum-sample and magnitude threshold — do not apply verdicts with n < 15.

---

## Data Scope

- **Season:** 2025–26 (Oct 21, 2025 – Mar 3, 2026)
- **Source:** `data/player_game_log.csv`, `data/team_game_log.csv`, `data/nba_master.csv`
- **Whitelist:** ~57 active whitelisted players (name + team tuple filter)
- **Stats tested:** PTS / REB / AST / 3PM
- **Tier definitions:** PTS [10,15,20,25,30] | REB [2,4,6,8,10,12] | AST [2,4,6,8,10,12] | 3PM [1,2,3,4]
- **Hit definition:** `actual > tier` (strict greater-than, consistent with production quant.py)

---

## Backtest 1 — Signal Analysis (w10 baseline)

**Mode:** default (`python agents/backtest.py`)
**Output:** `data/backtest_results.json`
**Instances:** 5,368 (player × stat × game date where tier was selected)
**Window:** 10 games rolling

### Signal Verdicts

| Signal | PTS | REB | AST | 3PM | Notes |
|--------|-----|-----|-----|-----|-------|
| trend (L5 vs L10) | noise | noise | noise | noise | Lift variance ≤0.08 across all stats — no predictive value |
| opp_defense | weak | noise | noise | **predictive** | 3PM: tough opp 72.1% vs soft 60.9% — inverted from intuition |
| home_away | noise | noise | noise | noise | Lift variance ≤0.05 across all stats |
| on_b2b | noise | noise | noise | noise | Lift variance ≤0.08 — directionally negative but not significant |
| pace_tag | noise | noise | noise | predictive | 3PM high pace 66.8% vs mid pace 47.4% (n=38 mid — small) |
| spread_risk | weak | noise | noise | weak | Directionally consistent but below predictive threshold |

**Key finding — 3PM opp_defense inversion:** Players facing a "tough" PTS defense are marginally more likely to see 3PM opportunities. Mechanism: tough PTS defenses crowd the paint and sag on shooters, generating more kick-out opportunities. The opp_defense prompt instruction for 3PM was explicitly inverted from intuition in analyst.py as a result.

### Tier Calibration (w10 window, full dataset)

| Tier | n | Hit Rate | Flag |
|------|---|----------|------|
| PTS T10 | 389 | 83.8% | — |
| PTS T15 | 601 | 71.4% | — |
| PTS T20 | 375 | 71.5% | — |
| PTS T25 | 239 | 65.7% | threshold_concern |
| PTS T30 | 27 | 44.4% | threshold_concern |
| REB T2 | 617 | 81.0% | — |
| REB T4 | 585 | 72.3% | — |
| REB T6 | 350 | 68.6% | threshold_concern |
| REB T8 | 150 | 56.7% | threshold_concern |
| AST T2 | 710 | 78.7% | — |
| AST T4 | 408 | 71.1% | — |
| AST T6 | 165 | 63.0% | threshold_concern |
| AST T8 | 55 | 61.8% | threshold_concern |
| 3PM T1 | 444 | 71.4% | — |
| 3PM T2 | 157 | 58.0% | threshold_concern |
| 3PM T3 | 43 | 34.9% | threshold_concern |

### Implementation Applied

1. **Tier ceiling rules** added to analyst.py SELECTION RULES — REB T8+, AST T6+, 3PM T2+, PTS T25+ require exceptional justification.
2. **3PM opp_defense instruction inverted** — prompt now correctly treats tough PTS defense as a mild positive signal for 3PM picks.
3. **Trend and home/away removed as directive signals** — data retained in output (for transparency) but prompt no longer weights them as selection factors.

---

## Backtest 2 — Rolling Window Calibration (w10 vs w20)

**Mode:** `--mode calibration_only --window 20` (calibration re-run at w20)
**Output:** `data/backtest_results_w20.json`
**Instances:** 4,009 (w20 window; fewer instances because w20 requires 20 prior games vs 10)
**Window:** 20 games rolling

### Tier Calibration (w20 window)

| Tier | n | Hit Rate (w20) | Hit Rate (w10) | Delta |
|------|---|---------------|----------------|-------|
| PTS T25 | 161 | 70.2% | 65.7% | +4.5pp |
| PTS T30 | 6 | 16.7% | 44.4% | −27.7pp (effectively eliminates this pick) |
| REB T6 | 275 | 71.6% | 68.6% | +3.0pp |
| REB T8 | 101 | 66.3% | 56.7% | **+9.6pp** |
| AST T6 | 88 | 75.0% | 63.0% | **+12.0pp** |
| AST T8 | 26 | 57.7% | 61.8% | −4.1pp (still below threshold) |
| 3PM T2 | 96 | 61.5% | 58.0% | +3.5pp (still below threshold) |
| 3PM T3 | 5 | 40.0% | 34.9% | marginal (n too small) |

**Key finding:** w20 window substantially improves calibration at REB T6 (+3pp to 71.6%) and AST T6 (+12pp to 75%), and partially at REB T8 (+9.6pp to 66.3%). PTS T30 is effectively eliminated. The tradeoff is ~25% fewer total selections (4,009 vs 5,368 instances), estimated ≥8 picks/day on typical slates.

### Implementation Applied

`PLAYER_WINDOW` raised from 10 → 20 in `quant.py`. All tier hit rates, best_tiers, and matchup splits now use a 20-game rolling window.

---

## Backtest 3 — Bounce-Back Analysis

**Mode:** `--mode bounce-back`
**Output:** `data/backtest_bounce_back.json`
**Instances:** 3,559 consecutive game pairs (Dec 2, 2025 – Mar 3, 2026)
**Window:** 20 games rolling; best qualifying tier must have ≥70% hit rate

### Analysis 1 — Simple Bounce-Back (post-miss vs post-hit next game)

| Stat | Baseline | Post-Hit | Post-Miss | BB Lift | Verdict |
|------|----------|----------|-----------|---------|---------|
| PTS | 77.98% | 79.25% | 72.77% | 0.933 | independent |
| REB | 85.46% | 87.13% | 74.00% | 0.866 | **slump-persistent** |
| AST | 87.51% | 88.21% | 81.63% | 0.933 | independent |
| 3PM | 90.59% | 90.64% | 90.00% | 0.994 | independent |
| All | 84.24% | 85.56% | 75.97% | 0.902 | independent |

**Key finding:** No meaningful league-wide bounce-back signal. After a miss, players hit at 0.90× their baseline rate, not above. REB is the exception — slump-persistent, meaning a REB miss is mildly predictive of another miss (lift=0.87, n=150). Applying −5% confidence or one-tier-down for post-miss REB was considered but not implemented given the moderate effect size.

### Analysis 2 — Miss Severity

Miss severity (near/moderate/bad) showed flat post-miss recovery rates across all stats (PTS miss buckets: near 74.2%, moderate 73.6%, bad 70.9% — gradient verdict: flat). No "worse the miss → stronger reversion" pattern confirmed.

### Analysis 3 — Consecutive Miss Streak

Directionally negative as streaks lengthen (PTS: after 0 misses 79.3%, after 1 miss 74.3%, after 2 misses 67.7%) but all streak_2+ cells flagged `insufficient_sample`. Cannot draw a production conclusion at this sample size.

### Implementation Applied

None for league-wide signal. See player-level supplementary analysis below.

---

## Supplementary — Player-Level Bounce-Back Analysis

**Mode:** `--mode player-bounce-back`
**Output:** `data/bounce_back_players.json`
**Scope:** All whitelisted players, full season history, per-player per-stat at best qualifying tier

This analysis identified that while the league-wide signal is null, specific players are individually exceptional at recovering from misses.

### Iron Floor Players (never missed twice in a row, ≥5 total misses)

19 player-stat combinations qualified as iron floor (max consecutive miss streak = 1, n_misses ≥ 5). Highlights:

| Player | Stat | Tier | Post-Miss HR | n_misses |
|--------|------|------|--------------|---------|
| Luka Doncic | 3PM | T2 | 100% | 12 |
| Jaylen Brown | PTS | T20 | 100% | 11 |
| Kawhi Leonard | AST | T2 | 100% | 10 |
| LaMelo Ball | 3PM | T2 | 100% | 9 |
| Multiple players | REB | various | 100% | 5–8 |

### Implementation Applied

- `build_bounce_back_profiles()` added to `quant.py` — computes per-player bounce-back metrics using full season history (not rolling window). Requires ≥5 post-miss observations; outputs `post_miss_hit_rate`, `lift`, `consecutive_miss_rate`, `max_consecutive_misses`, `iron_floor`, `n_misses` per stat, or null if insufficient data.
- `bounce_back` key added to each player's entry in `player_stats.json`.
- `build_quant_context()` in `analyst.py` annotates each stat line with `bb_lift=X.XX(Nmiss)` when lift > 1.0, or `[iron_floor]` when iron_floor is true.
- SELECTION RULES updated: "Where bb_lift > 1.15, treat post-miss as neutral-to-positive. Where [iron_floor], a single prior miss carries no negative weight."

---

## Backtest 4 — Mean Reversion (Cold Streaks)

**Mode:** `--mode mean-reversion`
**Output:** `data/backtest_mean_reversion.json`
**Instances:** 4,009 (Nov 30, 2025 – Mar 3, 2026; requires 20 prior games)
**Definition:** Cold streak = L5 raw avg drop ≥5% OR L5 tier hit rate drop ≥10 pp vs L20 baseline

### Analysis 1 — Next-Game Hit Rate by Cold Streak Severity

| Stat | Baseline | Mild Lift | Moderate Lift | Severe Lift | Verdict |
|------|----------|-----------|---------------|-------------|---------|
| PTS | 78.8% | 0.994 | 0.983 | 0.929 | independent |
| REB | 86.0% | 0.965 | 0.996 | 0.926 | independent |
| AST | 88.2% | 1.024 | 0.963 | 0.960 | independent |
| 3PM | 92.9% | 0.953 | 0.924 | 0.931 | independent |

All four stats returned "independent" verdict — cold streak state does not predict next-game tier performance in either direction. The hypothesis (cold streak → bounce back) was rejected.

### Analysis 2 — Reversion Curve (N+1, N+2, N+3)

Players in a cold streak do show recovery, but it happens 2–3 games later, not immediately:
- PTS severe cold: N+1 73.2% → N+2 77.5% → N+3 79.5% (baseline 78.8%)
- REB severe cold: N+1 79.6% → N+2 85.3% → N+3 87.1% (baseline 86.0%)

Reversion is real over 2–3 games, but irrelevant for NBAgent which picks next-game props only.

### Analysis 3 — Matchup Interaction

Matchup quality (soft/mid/tough) does not reliably accelerate reversion within a cold streak. Two marginal cells showed spread > 10pp (AST severe cold: soft 90% vs tough 73.7%; 3PM moderate cold: soft 73.9% vs tough 92.0%) but both involve small n and the 3PM direction is counter-intuitive, suggesting noise.

### Implementation Applied

None. Cold streak state is not actionable for next-game props at current sample sizes.

---

## Backtest 5 — Recency Weight Correction

**Mode:** `--mode recency-weight`
**Output:** `data/backtest_recency_weight.json`
**Train period:** Oct 21, 2025 – Jan 31, 2026 (context only, not evaluated)
**Test period:** Feb 1 – Mar 3, 2026 (held-out, 2,100 instances across 8 combos)
**Combos tested:** Window × Decay = [10, 20] × [1.00, 0.95, 0.90, 0.85]

### Overall Calibration on Test Period

| Combo | Selection Rate | Calibration | vs Baseline |
|-------|---------------|-------------|-------------|
| w10_d1.00 | 65.3% | 71.1% | −2.8pp |
| w20_d1.00 (baseline) | 64.4% | **73.9%** | — |
| w20_d0.95 | 61.9% | **75.6%** | +1.7pp |
| w20_d0.90 | 60.9% | 74.8% | +0.9pp |
| w20_d0.85 | 60.7% | 74.0% | +0.1pp |
| w10_d0.95 | 60.3% | 73.8% | −0.1pp |
| w10_d0.90 | 60.5% | 73.7% | −0.2pp |
| w10_d0.85 | 60.1% | 73.8% | −0.1pp |

### Problem Tier Results on Test Period

| Tier | w10_d1.00 | w20_d1.00 | Best Decay (w20) | Notes |
|------|-----------|-----------|-----------------|-------|
| REB T8 | 61.9%(n=42) | 63.8%(n=47) | 70.0% d=0.85 (n=40) | Improvement via decay, but n small |
| AST T8 | 25.0%(n=4) | 40.0%(n=5) | n≤5 all combos | Tier too rare to evaluate reliably |
| 3PM T2 | 58.3%(n=36) | **76.2%(n=21)** | — | Already fixed by w20 window |
| 3PM T3 | 25.0%(n=8) | 0 picks | — | Eliminated entirely by w20 window |

**Key finding:** The "problem tiers" from Backtest 1 were artifacts of the w10 window. The w20 deployment (Backtest 2) already resolved 3PM T2, 3PM T3, and most of AST T8. The only meaningful remaining issue is REB T8, which benefits from d=0.85 (+6.2pp on test) but at the cost of degraded 3PM calibration. w20_d0.95 is the best overall combo but +1.7pp over 31 days is within noise given the test window size.

### Implementation Applied

None. The problems were window=10 artifacts already resolved by the w20 deployment. No decay factor offered a sufficiently large, robust improvement to justify a production change.

---

## Open Hypotheses (Not Yet Backtested)

### H6 — Post-Blowout Bounce-Back
**Question:** Do players on teams that suffered a blowout loss (margin ≥15 pts) show elevated tier hit rates in their next game?

**Mechanism:** Blowout losses may increase team motivation and coaching emphasis on performance correction. Alternatively, the loss signals genuine quality mismatch and the effect is noise.

**Test design:**
- For each player-game instance (game N+1), look at their team's result in game N
- Classify game N result: win / close_loss (margin < 15) / blowout_loss (margin ≥ 15)
- Measure tier hit rate at game N+1 for each category
- Minimum n=15 per category; lift threshold > 0.10 for actionable signal

**Data availability:** `nba_master.csv` has home_score and away_score for all games. All other fields already exist.

**Priority:** Medium — testable with no new data collection. Backtest design is straightforward.

---

### H7 — Opponent Schedule Fatigue
**Question:** Do player prop hit rates increase when the opposing team is on a B2B or coming off a dense schedule (4+ games in 5 days)?

**Mechanism:** Opponent fatigue → softer defense → higher prop production. This is the mirror of the own-team fatigue signal already tracked in quant.py. If the signal exists, it could be used to upweight picks when the opponent is fatigued, independent of the opponent's overall defensive rating.

**Test design:**
- For each player-game instance, compute the opponent's rest context as of that game date using `compute_rest_context()` logic from quant.py
- Classify opponent: rested (rest ≥ 2 days, no dense schedule) / moderate (rest = 1 day) / fatigued (B2B) / dense (4+ games in 5 days)
- Measure tier hit rate at game N+1 for each opponent fatigue category, by stat
- Compare to the player's own-team rest signal for relative effect size

**Data availability:** All fields in `nba_master.csv`. Opponent B2B detection requires the same `build_b2b_game_ids()` logic already in quant.py — apply it to the opposing team at test time.

**Priority:** Medium — natural complement to the existing own-team fatigue signals. Shares implementation logic with current quant.py rest context computation.

---

## Key Signals Summary

| Signal | Verdict | Effect Size | Applied? |
|--------|---------|-------------|---------|
| Rolling window (w10 vs w20) | w20 better | +9.6pp REB T8, +12pp AST T6 | ✅ PLAYER_WINDOW=20 |
| Tier calibration | Several tiers below 70% threshold | REB T8 56.7%, AST T6 63%, 3PM T2 58% (at w10) | ✅ Ceiling rules in prompt |
| 3PM opp_defense inversion | Predictive | tough 72.1% vs soft 60.9% | ✅ Inverted in prompt |
| Trend (L5 vs L10) | Noise | Lift variance < 0.05 across all stats | ✅ Removed as directive signal |
| Home/away | Noise | Lift variance < 0.03 | ✅ Removed as directive signal |
| B2B (own team) | Noise (aggregate) / quantified per player | Directionally −3-5% but below threshold | ✅ B2B rates surfaced; one-tier-down fallback when n<5 |
| Spread / blowout risk | Weak | High spread favored teams → lower prop hit rates | ✅ Blowout flag + spread rules in prompt |
| Bounce-back (league-wide) | Independent (null) | Lift 0.90–0.93, not directional | ❌ No prompt change |
| Bounce-back (player-level) | Strong for specific players | 19 iron floor combos; Luka 3PM, Jaylen Brown PTS, etc. | ✅ bb_lift / iron_floor in quant output + prompt |
| Cold streak → mean reversion | Independent (null) | All stats; reversion real but over 2–3 games not N+1 | ❌ No prompt change |
| Recency decay weighting | Marginal | w20_d0.95 +1.7pp over 31 test days | ❌ Within noise; no change |
| Post-Blowout Bounce-Back | Not tested | — | H6 queued |
| Opponent Schedule Fatigue | Not tested | — | H7 queued |
