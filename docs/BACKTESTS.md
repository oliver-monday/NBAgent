# NBAgent — Backtest Log

All retrospective signal analyses run against historical game log data using `agents/backtest.py`.
Results drive prompt design, quant config, and tier rules. Findings are only applied to production
after passing a minimum-sample and magnitude threshold — do not apply verdicts with n < 15.

> **Grading correction (2026-03-05):** All backtest JSON files and numbers in this document were
> regenerated with corrected `>=` grading (exact threshold = HIT). Prior to this correction, the
> backtest and all production code used strict `>` (exact match = MISS). Numbers changed materially
> in several places — see highlighted cells below. The 3PM opp_defense "inverted signal" finding
> from the original run was an artifact of incorrect grading and has been reversed to NOISE.

---

## Data Scope

- **Season:** 2025–26 (Oct 21, 2025 – Mar 3, 2026)
- **Source:** `data/player_game_log.csv`, `data/team_game_log.csv`, `data/nba_master.csv`
- **Whitelist:** ~57 active whitelisted players (name + team tuple filter)
- **Stats tested:** PTS / REB / AST / 3PM
- **Tier definitions:** PTS [10,15,20,25,30] | REB [2,4,6,8,10,12] | AST [2,4,6,8,10,12] | 3PM [1,2,3,4]
- **Hit definition:** `actual >= tier` (exact threshold = HIT, consistent with all production code)

---

## Backtest 1 — Signal Analysis (w10 baseline)

**Mode:** default (`python agents/backtest.py`)
**Output:** `data/backtest_results.json`
**Instances:** 6,437 (player × stat × game date where tier was selected)
**Window:** 10 games rolling

### Signal Verdicts

| Signal | PTS | REB | AST | 3PM | Notes |
|--------|-----|-----|-----|-----|-------|
| trend (L5 vs L10) | noise | noise | **weak** | noise | AST "up" trend 80.4% (lift=1.070, n=439) — marginal |
| opp_defense | noise | noise | **weak** | noise | AST: soft 78.3% vs tough 71.6%; 3PM opp_defense now NOISE (corrected) |
| home_away | noise | noise | noise | noise | Lift variance ≤0.05 across all stats |
| on_b2b | noise | noise | noise | noise | Directionally negative but lift variance ≤0.08 |
| pace_tag | **weak** | noise | noise | **predictive** | PTS mid-pace 66.1%; 3PM: high 72.5% vs mid 61.2% (lift=0.853, n=85 mid) |
| spread_risk | noise | **weak** | **weak** | **weak** | Directionally consistent; REB/AST high-spread 77.6%/79.3% |

**3PM opp_defense corrected:** Under corrected `>=` grading, 3PM opp_defense is NOISE (soft 69.7%, mid 72.3%, tough 73.5%; lift variance 0.053 ≤ 0.08). The prior "tough defense = positive for 3PM" inverted instruction was based on incorrectly-graded data. The prompt instruction inverting this signal should be removed — it is not supported by correctly-graded data.

**Note on AST signals:** AST trend (up, lift=1.070) and AST opp_defense (soft vs tough, 7pp spread) both registered WEAK. Below the 0.15 PREDICTIVE threshold; informational only — not applied as directive rules.

### Tier Calibration (w10 window, full dataset)

| Tier | n | Hit Rate | Flag |
|------|---|----------|------|
| PTS T10 | 315 | 81.6% | — |
| PTS T15 | 614 | 74.6% | — |
| PTS T20 | 414 | **69.6%** | ⚠ threshold_concern (was 71.5% under `>` grading) |
| PTS T25 | 253 | 66.8% | ⚠ threshold_concern |
| PTS T30 | 81 | 56.8% | ⚠ threshold_concern |
| REB T2 | 351 | 91.2% | — |
| REB T4 | 687 | 76.9% | — |
| REB T6 | 466 | 68.9% | ⚠ threshold_concern |
| REB T8 | 247 | 63.2% | ⚠ threshold_concern |
| REB T10 | 67 | 44.8% | ⚠ threshold_concern |
| REB T12 | 30 | 63.3% | ⚠ threshold_concern |
| AST T2 | 637 | 83.2% | — |
| AST T4 | 615 | 74.3% | — |
| AST T6 | 255 | 65.1% | ⚠ threshold_concern |
| AST T8 | 91 | 63.7% | ⚠ threshold_concern |
| AST T10 | 25 | 36.0% | ⚠ threshold_concern |
| 3PM T1 | 649 | **77.5%** | — (was 71.4%) |
| 3PM T2 | 441 | **71.4%** | — (was 58.0% — now ABOVE threshold; was never miscalibrated) |
| 3PM T3 | 157 | 58.6% | ⚠ threshold_concern |
| 3PM T4 | 42 | 35.7% | ⚠ threshold_concern |

### Implementation Applied

1. **Tier ceiling rules** added to analyst.py SELECTION RULES — REB T8+, AST T6+, PTS T25+ require exceptional justification. *(3PM T2 ceiling rule is now unsupported — 3PM T2 clears 70% at 71.4%.)*
2. **3PM opp_defense instruction:** The inverted instruction ("tough defense = mild positive for 3PM") was based on incorrect grading. Under corrected data, 3PM opp_defense is NOISE. This prompt instruction should be removed or neutralized.
3. **Trend and home/away removed as directive signals** — confirmed noise across all 4 stats; data retained in output but prompt no longer weights them.

---

## Backtest 2 — Rolling Window Calibration (w10 vs w20)

**Mode:** `--calibration-only --window 20`
**Output:** `data/backtest_results_w20.json`
**Instances:** 4,900 (w20 window; fewer because w20 requires 20 prior games vs 10)
**Window:** 20 games rolling

### Tier Calibration (w20 window)

| Tier | n (w20) | Hit Rate (w20) | Hit Rate (w10) | Delta |
|------|---------|---------------|----------------|-------|
| PTS T25 | 173 | 67.0% | 66.8% | +0.2pp |
| PTS T30 | 39 | 51.3% | 56.8% | −5.5pp (worse; eliminate this pick) |
| REB T6 | 335 | 69.8% | 68.9% | +0.9pp (marginal improvement) |
| REB T8 | 200 | **71.0%** | 63.2% | **+7.8pp** (crosses threshold at w20) |
| REB T10 | 29 | 51.7% | 44.8% | +6.9pp (still below threshold) |
| AST T6 | 149 | 68.5% | 65.1% | +3.4pp (still below threshold) |
| AST T8 | 72 | 68.1% | 63.7% | +4.4pp (still below threshold) |
| 3PM T2 | 322 | **77.3%** | 71.4% | +5.9pp (well above threshold) |
| 3PM T3 | 94 | 60.6% | 58.6% | +2.0pp (still below threshold) |

**Key finding:** w20 window substantially improves REB T8 (+7.8pp to 71.0% — crosses the 70% threshold). 3PM T2 further improves to 77.3%. PTS T30 worsens at w20 and should be treated as an invalid pick. AST T6 and T8 remain below threshold even at w20. The tradeoff is ~24% fewer total selections (4,900 vs 6,437 instances), estimated ≥8 picks/day on typical slates.

### Implementation Applied

`PLAYER_WINDOW` raised from 10 → 20 in `quant.py`. All tier hit rates, best_tiers, and matchup splits use a 20-game rolling window.

---

## Backtest 3 — Bounce-Back Analysis

**Mode:** `--mode bounce-back`
**Output:** `data/backtest_bounce_back.json`
**Instances:** 5,231 consecutive game pairs (Nov 12, 2025 – Mar 4, 2026)
**Window:** 10 games rolling; best qualifying tier must have ≥70% hit rate

### Analysis 1 — Simple Bounce-Back (post-miss vs post-hit next game)

| Stat | Baseline | Post-Hit | Post-Miss | BB Lift | Verdict |
|------|----------|----------|-----------|---------|---------|
| PTS | 72.0% | 73.1% | 67.7% | 0.94 | independent |
| REB | 75.0% | 78.2% | **62.0%** | **0.83** | **slump-persistent** |
| AST | 75.8% | 77.6% | 68.5% | 0.90 | independent |
| 3PM | 73.0% | 74.8% | 66.2% | 0.91 | independent |
| All | 74.0% | 76.1% | 66.0% | 0.89 | slump-persistent |

**Key finding:** No meaningful league-wide bounce-back signal. After a miss, players hit at 0.89× their baseline rate, not above. REB is the exception — strongly slump-persistent (post-miss 62.0% vs baseline 75.0%, lift=0.83, n=300). This is a meaningful signal: a REB miss predicts continued underperformance the next game. Applying −5% confidence or one-tier-down for post-miss REB is justified by this data.

### Analysis 2 — Miss Severity

| Stat | Near-Miss | Moderate | Bad | Verdict |
|------|-----------|----------|-----|---------|
| PTS | 65.8%(n=79) | 75.0%(n=104) | 61.9%(n=105) | flat |
| REB | 63.6%(n=206) | 57.3%(n=75) | 63.2%(n=19) | insufficient-sample |
| AST | 69.6%(n=214) | 63.6%(n=55) | 75.0%(n=4) | insufficient-sample |
| 3PM | 66.5%(n=215) | 50.0%(n=4) | 0.0%(n=0) | insufficient-sample |

No "worse miss → stronger reversion" gradient confirmed. Miss severity is not actionable.

### Analysis 3 — Consecutive Miss Streak

| Stat | 0 misses | 1 miss | 2 misses | 3+ misses | Verdict |
|------|----------|--------|----------|-----------|---------|
| PTS | 73.1%(n=1050) | 67.1%(n=228) | 68.5%(n=54) | 83.3%(n=6)* | insufficient-sample |
| REB | 78.2%(n=1185) | 62.7%(n=228) | 54.0%(n=50) | 72.7%(n=22) | **reversion strengthens** |
| AST | 77.6%(n=1107) | 70.5%(n=217) | 60.5%(n=43) | 61.5%(n=13)* | insufficient-sample |
| 3PM | 74.8%(n=809) | 65.5%(n=165) | 72.1%(n=43) | 54.5%(n=11)* | insufficient-sample |

*n < 15 — insufficient. REB shows deepening slump with streak length (2-miss: 54.0%), then partial recovery at 3+ (72.7%, n=22). Directionally persistent, not mean-reverting.

### Implementation Applied

None for league-wide signal. REB slump-persistent finding (lift=0.83, n=300) is notable but existing bounce-back profile integration (player-level) captures the player-specific version. A blanket "post-miss REB one-tier-down" rule remains a candidate enhancement based on this data.

---

## Supplementary — Player-Level Bounce-Back Analysis

**Mode:** `--mode player-bounce-back`
**Output:** `data/bounce_back_players.json`
**Scope:** All whitelisted players, full season history, per-player per-stat at best qualifying tier

This analysis identified that while the league-wide signal is null (or mildly slump-persistent), specific players are individually exceptional at recovering from misses.

### Iron Floor Players (never missed their best tier twice in a row, ≥2 total misses)

16 player-stat combinations qualified as iron floor. Highlights:

| Player | Stat | Tier | Games | Misses | Overall HR |
|--------|------|------|-------|--------|------------|
| Luka Doncic | 3PM | T3 | 49 | 12 | 75.5% |
| Jaylen Brown | PTS | T20 | 60 | 10 | 83.3% |
| LaMelo Ball | 3PM | T2 | 53 | 9 | 83.0% |
| Kawhi Leonard | REB | T4 | 47 | 8 | 83.0% |
| Devin Booker | AST | T4 | 45 | 8 | 82.2% |
| Donovan Mitchell | AST | T4 | 56 | 8 | 85.7% |
| Shai Gilgeous-Alexander | PTS | T25 | 52 | 7 | 86.5% |
| Brandon Miller | AST | T2 | 46 | 7 | 84.8% |
| Derrick White | REB | T2 | 61 | 6 | 90.2% |
| Jamal Murray | REB | T2 | 59 | 6 | 89.8% |
| Donovan Mitchell | 3PM | T2 | 56 | 6 | 89.3% |
| Payton Pritchard | 3PM | T1 | 61 | 6 | 90.2% |
| Cooper Flagg | AST | T2 | 48 | 5 | 89.6% |
| Cooper Flagg | REB | T4 | 48 | 5 | 89.6% |
| Desmond Bane | AST | T2 | 60 | 5 | 91.7% |
| Chet Holmgren | PTS | T10 | 57 | 5 | 91.2% |

### Implementation Applied

- `build_bounce_back_profiles()` added to `quant.py` — computes per-player bounce-back metrics using full season history. Requires ≥5 post-miss observations; outputs `post_miss_hit_rate`, `lift`, `consecutive_miss_rate`, `max_consecutive_misses`, `iron_floor`, `n_misses` per stat, or null if insufficient data.
- `bounce_back` key added to each player's entry in `player_stats.json`.
- `build_quant_context()` in `analyst.py` annotates each stat line with `bb_lift=X.XX(Nmiss)` when lift > 1.0, or `[iron_floor]` when iron_floor is true.
- SELECTION RULES updated: "Where bb_lift > 1.15, treat post-miss as neutral-to-positive. Where [iron_floor], a single prior miss carries no negative weight."

---

## Backtest 4 — Mean Reversion (Cold Streaks)

**Mode:** `--mode mean-reversion`
**Output:** `data/backtest_mean_reversion.json`
**Instances:** 4,900 (Nov 30, 2025 – Mar 4, 2026; requires 20 prior games)
**Definition:** Cold streak = L5 raw avg drop ≥5% OR L5 tier hit rate drop ≥10 pp vs L20 baseline

### Analysis 1 — Next-Game Hit Rate by Cold Streak Severity

| Stat | Baseline | Mild (lift) | Moderate (lift) | Severe (lift) | Verdict |
|------|----------|-------------|-----------------|---------------|---------|
| PTS | 73.3%(n=712) | 74.3%(1.01) | 73.3%(1.00) | 69.6%(0.95) | independent |
| REB | 77.8%(n=758) | 74.8%(0.96) | 76.7%(0.99) | 66.7%(0.86) | independent |
| AST | 77.4%(n=686) | 77.4%(1.00) | 80.3%(1.04) | 74.7%(0.96) | independent |
| 3PM | 78.2%(n=501) | 77.5%(0.99) | 73.9%(0.94) | **68.3%(0.87)** | **decline** |

**Key finding — 3PM cold streak decline:** Severe 3PM cold streak (L5 hit rate ≥10pp below L20) predicts continued underperformance next game at 68.3% (lift=0.87, n=161). This is below the 70% threshold. Unlike other stats, 3PM cold streaks do not self-correct at N+1. This is the first directional, production-actionable finding from mean reversion analysis.

**All other stats:** Independent verdict — cold streak state does not predict next-game tier performance for PTS, REB, or AST.

### Analysis 2 — Reversion Curve (N+1, N+2, N+3)

| Stat | Cold Type | N+1 | N+2 | N+3 | Baseline |
|------|-----------|-----|-----|-----|----------|
| PTS | moderate | 73.3%(n=266) | 69.9% | 73.6% | 73.3% |
| PTS | severe | 69.6%(n=46) | 69.8% | 76.2% | 73.3% |
| REB | moderate | 76.7%(n=262) | 76.3% | 73.9% | 77.8% |
| REB | severe | 66.7%(n=111) | 70.6% | 76.6% | 77.8% |
| AST | moderate | 80.3%(n=249) | 78.3% | 79.7% | 77.4% |
| AST | severe | 74.7%(n=79) | 77.9% | 83.3% | 77.4% |
| 3PM | moderate | 73.9%(n=184) | 76.8% | 72.2% | 78.2% |
| 3PM | severe | 68.3%(n=161) | 64.1% | 70.6% | 78.2% |

3PM severe cold does not self-correct at N+2 (64.1%) — the slump deepens before recovering at N+3 (70.6%). This supports treating 3PM cold streaks as persistent, not mean-reverting.

### Analysis 3 — Matchup Interaction

| Condition | Soft Opp | Tough Opp | Verdict |
|-----------|----------|-----------|---------|
| REB moderate cold | 69.7%(n=99) | 81.6%(n=76) | **matchup accelerates reversion** |
| REB severe cold | 63.6%(n=33) | 61.4%(n=44) | no interaction |
| AST moderate cold | 78.0%(n=91) | 79.2%(n=72) | no interaction |
| AST severe cold | 83.9%(n=31) | 64.0%(n=25) | **matchup accelerates reversion** |
| 3PM moderate cold | 66.1%(n=56) | 69.2%(n=52) | no interaction |
| 3PM severe cold | 71.1%(n=45) | 79.1%(n=67) | no interaction |

Two matchup interactions: REB moderate cold vs tough opponent improves 12pp vs vs soft opponent; AST severe cold vs soft opponent improves 20pp vs tough opponent. Small n, but directionally notable.

### Implementation Applied

None yet. The 3PM cold streak decline signal (severe cold, lift=0.87, n=161) is the first mean reversion finding with production implications — down-tiering severe-cold 3PM players is a candidate prompt rule.

---

## Backtest 5 — Recency Weight Correction

**Mode:** `--mode recency-weight`
**Output:** `data/backtest_recency_weight.json`
**Train period:** Oct 21, 2025 – Jan 31, 2026 (context only, not evaluated)
**Test period:** Feb 1 – Mar 3, 2026 (held-out evaluation)
**Combos tested:** Window × Decay = [10, 20] × [1.00, 0.95, 0.90, 0.85]

### Overall Calibration on Test Period

| Combo | Window | Decay | Picks | Sel% | Cal% | vs Baseline |
|-------|--------|-------|-------|------|------|-------------|
| w10_d1.00 | 10 | 1.00 | 1,613 | 81.5% | 72.8% | −2.0pp |
| w10_d0.95 | 10 | 0.95 | 1,544 | 78.0% | 76.5% | +1.7pp |
| w10_d0.90 | 10 | 0.90 | 1,547 | 78.1% | 76.6% | +1.8pp |
| w10_d0.85 | 10 | 0.85 | 1,530 | 77.3% | 77.0% | +2.2pp |
| **w20_d1.00** | 20 | 1.00 | 1,649 | 83.3% | **74.8%** | (baseline) |
| w20_d0.95 | 20 | 0.95 | 1,603 | 81.0% | **76.9%** | **+2.1pp** |
| w20_d0.90 | 20 | 0.90 | 1,567 | 79.1% | 76.7% | +1.9pp |
| w20_d0.85 | 20 | 0.85 | 1,546 | 78.1% | 76.6% | +1.8pp |

### Problem Tier Results on Test Period

| Tier | w10_d1.00 | w20_d1.00 | Best w20 combo | Notes |
|------|-----------|-----------|----------------|-------|
| REB T8 | 65.5%(n=55) | 72.5%(n=69) | 75.0% at d=0.95(n=56) | w20 resolves this tier |
| AST T8 | 53.3%(n=30) | 66.7%(n=36) | 61.9% at d=0.90 | Remains below threshold |
| 3PM T2 | 76.2%(n=105) | 79.6%(n=108) | — | Well above threshold; no longer a problem tier |
| 3PM T3 | 58.8%(n=34) | 77.8%(n=18) | — | Resolved by w20; very small n |

**Key finding:** With corrected `>=` grading, 3PM T2 (76.2–79.6%) and 3PM T3 (77.8% at w20, n=18) are no longer problem tiers. The "problem tier" framing from the original `>` grading was an artifact. Remaining issues: AST T8 (66.7% at w20, still borderline); REB T8 improves to 72.5% at w20 (above threshold). No recency decay factor offered a sufficiently large, robust improvement to justify a production change — w20_d0.95 is only +2.1pp over a 31-day test window.

### Implementation Applied

None. The problems were `>` grading artifacts largely resolved by the w20 deployment. The minor improvement from recency decay is within noise given the test period length.

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

**Priority:** Medium — testable with no new data collection.

---

### H7 — Opponent Schedule Fatigue
**Question:** Do player prop hit rates increase when the opposing team is on a B2B or coming off a dense schedule (4+ games in 5 days)?

**Mechanism:** Opponent fatigue → softer defense → higher prop production. Mirror of the own-team fatigue signal already tracked in quant.py.

**Test design:**
- For each player-game instance, compute the opponent's rest context using `compute_rest_context()` logic from quant.py
- Classify opponent: rested (≥2 days rest, no dense) / moderate (1 day rest) / fatigued (B2B) / dense (4+ in 5)
- Measure tier hit rate per opponent fatigue category, by stat
- Compare to own-team rest signal for relative effect size

**Data availability:** All fields in `nba_master.csv`. Logic mirrors existing `build_b2b_game_ids()` in quant.py — apply to the opposing team at test time.

**Priority:** Medium — natural complement to existing own-team fatigue signals.

---

## Key Signals Summary

| Signal | Verdict | Effect Size | Applied? |
|--------|---------|-------------|---------|
| Rolling window (w10 vs w20) | w20 better | REB T8 +7.8pp to 71.0%, 3PM T2 +5.9pp to 77.3% at w20 | ✅ PLAYER_WINDOW=20 |
| Tier calibration | Several tiers below 70% threshold | REB T8 63.2%(w10)→71.0%(w20); AST T6 65.1%; PTS T20 69.6% | ✅ Ceiling rules in prompt (3PM T2 ceiling removed — now 71.4%) |
| 3PM opp_defense | **NOISE** (corrected from predictive) | soft 69.7%, mid 72.3%, tough 73.5%; lift variance 0.053 | ⚠️ Prior inverted prompt instruction needs removal |
| Trend (L5 vs L10) | Noise (all stats) | Lift variance < 0.05 | ✅ Removed as directive signal |
| Home/away | Noise | Lift variance < 0.03 | ✅ Removed as directive signal |
| AST trend | Weak | AST "up" 80.4% (lift=1.070, n=439) | ❌ Below predictive threshold; not applied |
| AST opp_defense | Weak | Soft 78.3% vs tough 71.6% (7pp) | ❌ Below predictive threshold; not applied |
| 3PM pace_tag | Predictive | High 72.5% vs mid 61.2% (lift=0.853, n=85 mid) | ✅ Data surfaced; pace tag in context |
| B2B (own team) | Noise (aggregate) / quantified per player | Directionally −3% but below threshold | ✅ B2B rates surfaced; one-tier-down fallback when n<5 |
| Spread / blowout risk | Weak | High-spread: REB 77.6%, AST 79.3% high-spread; blowout flag | ✅ Blowout flag + spread rules in prompt |
| Bounce-back (league-wide) | Slump-persistent | Overall lift=0.89; REB lift=0.83 (n=300) — slump persists | ❌ No blanket rule; player-level integrated |
| Bounce-back (player-level) | Strong for specific players | 16 iron floor combos; post-miss profiles in quant output | ✅ bb_lift / iron_floor in quant + prompt |
| Cold streak → mean reversion | **3PM: decline; others: null** | 3PM severe cold 68.3%(lift=0.87, n=161); PTS/REB/AST independent | ⚠️ 3PM finding actionable — prompt rule candidate |
| Recency decay weighting | Marginal | w20_d0.95 +2.1pp over 31 test days | ❌ Within noise; no change |
| Post-Blowout Bounce-Back | Not tested | — | H6 queued |
| Opponent Schedule Fatigue | Not tested | — | H7 queued |
