# NBAgent — Backtest Log

All retrospective signal analyses run against historical game log data using `agents/backtest.py`.
Results drive prompt design, quant config, and tier rules. Findings are only applied to production
after passing a minimum-sample and magnitude threshold — do not apply verdicts with n < 15.

## Data Scope

- **Season:** 2025–26 (Oct 21, 2025 – Mar 3, 2026)
- **Source:** `data/player_game_log.csv`, `data/team_game_log.csv`, `data/nba_master.csv`
- **Whitelist:** ~57 active whitelisted players (name + team tuple filter)
- **Stats tested:** PTS / REB / AST / 3PM
- **Tier definitions:** PTS [10,15,20,25,30] | REB [2,4,6,8,10,12] | AST [2,4,6,8,10,12] | 3PM [1,2,3,4]
- **Hit definition:** `actual >= tier` (exact threshold = HIT, consistent with all production code)

---

## Completed Backtests — Summary

All findings applied. Full methodology preserved in git history. Key results:


| Backtest                       | Window/n    | Key Finding                                                                                            | Applied?                                 |
| ------------------------------ | ----------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------- |
| H1 — Signal Analysis           | w10, 6,437  | Tier ceilings: REB T8 63.2%, AST T6 65.1%, PTS T20 69.6%. 3PM opp defense = NOISE. Trend/H/A = noise.  | ✅ Ceiling rules in prompt                |
| H2 — Window Calibration        | w20, 4,900  | w20 raises REB T8 to 71.0% (+7.8pp). 3PM T2 to 77.3%. PTS T30 worsens (51.3%) — invalid pick.          | ✅ PLAYER_WINDOW=20                       |
| H3 — Bounce-Back               | 5,231 pairs | League-wide = slump-persistent (lift 0.89). REB worst (lift 0.83, n=300). 16 iron-floor player combos. | ✅ bb_lift / iron_floor in quant + prompt |
| H4 — Mean Reversion            | w20, 4,900  | 3PM severe cold streak = decline (lift 0.87, n=161). PTS/REB/AST = null.                               | ✅ 3PM step-down rule                     |
| H5 — Recency Weight            | test period | w20_d0.95 +2.1pp over 31 days — within noise.                                                          | ❌ Not applied                            |
| H6 — Post-Blowout Bounce-Back  | 4,446       | NOISE — lift 0.955–0.988, variance ≤ 0.08.                                                             | ❌ Closed                                 |
| H7 — Opponent Schedule Fatigue | 4,610       | NOISE — opp B2B lift 0.977–1.025; dense bucket = 0 instances.                                          | ❌ Closed                                 |
| H11 — FG% Safety Margin        | structural  | Shipped without backtest. Validates via audit log.                                                     | ✅ ft_safety_margin in quant + analyst    |
| H13 — Shot Volume              | confounded  | Median FGA sanity check failed; results uninterpretable.                                               | ❌ Closed                                 |
| H8 — Positional DvP            | 6,137       | REVERT PTS/REB/AST (lift adv −0.051 to −0.060). KEEP 3PM (+0.106). Prompt cleanup done (W6, Mar 13).   | ✅ DvP line removed; opp_today= restored  |


---

## Open Hypotheses (Pending Backtest)

### H8 — Positional DvP vs. Team-Level DvP Predictive Validity

**Status: COMPLETE — March 12, 2026**
**Mode:** `--mode positional-dvp`
**Output:** `data/backtest_positional_dvp.json`
**Sample:** 6,137 instances, full 2025-26 season through March 11

**Question:** Is positional defense rating (DvP) a stronger predictor of PTS/AST/REB/3PM tier hit rates than the existing team-level opponent defense rating?

**Verdict by stat:**


| Stat | Team-Level Lift | Positional Lift | Lift Advantage | Verdict    |
| ---- | --------------- | --------------- | -------------- | ---------- |
| PTS  | 1.020           | 0.969           | −0.051         | **REVERT** |
| REB  | 1.041           | 0.989           | −0.052         | **REVERT** |
| AST  | 1.067           | 1.007           | −0.060         | **REVERT** |
| 3PM  | 0.938           | 1.044           | +0.106         | **KEEP**   |


**Overall verdict: REVERT for PTS/REB/AST. KEEP for 3PM.**

**Key findings:**

1. **PTS/REB/AST — positional DvP adds noise, not signal.** Team-level lift is consistently higher across all three. Positional buckets are roughly half the size (~300 instances vs. ~500), making percentile thresholds noisier. The positional ratings for PTS and REB show mild inversion — "tough" cells outperforming "soft" — which is the signal going backwards. The frontcourt REB breakdown is the most telling: team-level lift = 1.077 vs. positional lift = 0.980 (−0.097 swing) for the matchup where positional DvP should theoretically matter most. Team-level is capturing something real that position-splitting is diluting.
2. **Why positional DvP inverts for PTS/REB:** The whitelist skews heavily toward star players. Star players at a given position disproportionately face the opponent's best defensive assignment — meaning "tough" positional cells include games where elite offensive players still hit their tier despite tough defense, creating upward bias in the tough bucket and compressing lift.
3. **3PM exception is real and mechanically sound.** Perimeter three-point defense is genuinely position-specific in a way PTS/REB/AST aren't. Team-level 3PM DvP runs *backwards* (tough 79.6% beats soft 74.6%) because it mixes in frontcourt-defender games where 3PM is nearly irrelevant. Positional DvP filters those out and finds the true signal: +0.106 lift advantage, above the KEEP threshold.
4. **Current production state:** `DvP [POS]` line in analyst prompt is annotation-only with no directive rules — no picks at risk from this finding. However, the inverted signal for PTS/REB/AST means the annotation may be actively misleading the analyst.

**Implementation (backtest.py approach):**

- Reconstructs positional allowed-avg retroactively from `player_game_log.csv` grouped by `(opp_abbrev, position)`. Uses `shift(1).rolling(PDV_WINDOW=15, min_periods=10).mean()` — no lookahead.
- Per-`(stat, position)` percentile classification: ≥67th pctile allowed avg = "soft", ≤33rd = "tough". Direction: high allowed avg → soft defense.
- Team-level baseline computed via existing `build_opp_defense_lookup()` + `add_opp_defense_signal()` functions.

**Required production changes (next session):**

1. Remove `DvP [POS]` annotation from analyst prompt for PTS, REB, AST — revert to team-level `opp_today=` format for those three stats
2. For 3PM: positional DvP is valid — evaluate whether to activate it in prompt (currently excluded as noise per prior decision). The backtest verdict says it works; activation is a separate prompt-design decision
3. Simplify `build_quant_context()` in `analyst.py` accordingly — ~2 lines removed per player for PTS/REB/AST

**Do not revert `compute_positional_dvp()` in `quant.py`** — keep the field in `player_stats.json`. The 3PM signal is valid, and the field may be useful for future analyses (H15b cross-validation, offseason M1). Only the analyst *prompt injection* needs to change for PTS/REB/AST.

---

### H9 — Player × Opponent H2H Splits

**Status: QUEUED — data accumulating, run ~mid-April 2026**
**Mode:** `--mode h2h-splits`
**Output:** `data/backtest_h2h_splits.json` (not yet run)

**Question:** Does a player's historical performance specifically against today's opponent predict hit rates better than their overall tier hit rate?

**Mechanism:** Some players consistently over- or under-perform against specific teams regardless of defensive rating bucket. A player who has faced a particular opponent 4+ times in the season may have a reliable H2H pattern worth surfacing.

**Test design:**

- For each player-game instance, compare hit rate at best tier when player has ≥4 prior games vs this specific opponent vs overall season hit rate
- Measure lift variance between H2H-adjusted and non-adjusted predictions
- Requires full-season sample to have sufficient H2H instances (most opponents appear 2–4× per season)

**Data dependency:** Requires near-complete season sample (~mid-April 2026).

**Priority:** Medium-low. H2H samples are small by design (NBA schedule) — expect high variance, may close as NOISE.

---

### H15 — Opponent Team Pick Suppression / Lift

**Status: IMPLEMENTED in backtest.py — ready to run ~late March 2026**
**Mode:** `--mode opp-team-hit-rate`
**Output:** `data/backtest_opp_team_hit_rate.json` (not yet run)

**Question:** Do certain opponent teams systematically suppress or amplify the system's pick hit rate beyond what the `opp_defense` soft/mid/tough rating captures?

**Three sub-hypotheses:**

- **H15a — Overall hit rate by opponent:** Gate ≥15 picks. Suppressor: ≥10pp below baseline. Amplifier: ≥10pp above. Output: ranked list of all 30 opponents by system-wide hit rate.
- **H15b — By prop type:** Gate ≥5 picks per (opponent, prop_type). Same ±10pp threshold. Surfaces prop-specific suppression (e.g., team neutralizing AST without affecting PTS).
- **H15c — Miss margin floor compression:** Gate ≥3 misses per opponent. Mean miss margin = `actual_value − pick_value` (negative = missed below). Floor compression: mean ≤ −5.0. Near-miss pattern: mean > −3.0. Detects tier overshoot vs. variance.

**Implementation (backtest.py):**

- Reads `data/picks.json` directly (graded picks only: `result in HIT/MISS`, `voided != True`). Does NOT require `player_game_log.csv` — all data already in picks.json.
- Normalizes `opponent` field via `_ABBR_NORM_BT` dict (GS→GSW, NY→NYK, SA→SAS, NO→NOP, UTAH→UTA, WSH→WAS).
- Overall baseline = all graded picks hit rate (equivalent to `audit_summary.json` overall rate).
- H15a/H15b suppressor/amplifier verdict applied at ≥15 / ≥5 pick thresholds respectively. Opponents below threshold tagged `insufficient_sample`.
- H15c includes overall miss margin distribution (mean, median, p25, p75) as baseline reference.

**Run timing:** ~late March 2026 — no new data collection required; all inputs already in `picks.json`. Run alongside H8.

**If signal confirmed (H15a/b):** Implementation path is annotation-only first — `opp_team_suppressor` bool flag per prop type in `player_stats.json`; single annotation line in `build_quant_context()`. No tier-step or confidence rules without cross-season validation.

**If signal confirmed (H15c):** Floor compression evidence warrants note in `nba_season_context.md` or player profile conditional rendering for affected opponent matchups.

---

### Miss Anatomy — Near-Miss vs. Blowup Next-Game Prediction

**Status: QUEUED — data accumulating, run ~late March 2026**
**Mode:** `--mode miss-anatomy`
**Output:** `data/backtest_miss_anatomy.json` (not yet run)

**Question:** Does the severity of a miss (near-miss within 2 units vs. blowup 3+ units below tier) predict next-game hit rate differently?

**Mechanism:** If a player narrowly missed a tier (near-miss), the underlying performance level is close to the threshold and a hit the next game is plausible. If a player was blown out (3+ units below tier), the miss may reflect a structural bad game rather than variance, and the next-game outlook may be worse.

**Relationship to Backtest 3 (Miss Severity):** Backtest 3 tested miss severity as a league-wide signal and found it flat or insufficiently sampled. Miss Anatomy tests the same hypothesis at the player level, using the `near_miss_rate` and `blowup_rate` fields now computed in `quant.py` (`build_bounce_back_profiles()`). The quant fields are live and feeding Player Profiles; the directive prompt rule (confidence modifier or tier-drop on high `blowup_rate`) is deferred until this backtest validates the signal.

**Data dependency:** `near_miss_rate` and `blowup_rate` fields are live in `player_stats.json` as of March 2026. Requires ~~2 weeks of accumulation for meaningful per-player samples (~~late March 2026).

**Priority:** High — quant fields already live. If signal validates, analyst wiring (annotation + prompt rule) ships immediately after.

**Deferred scope:** `analyst.py` annotation and directive confidence rule are explicitly NOT shipped until this backtest completes. See `miss_anatomy_quant_only.md` for rationale.

---

### H19 — In-Game Blowout Regime: Favored vs. Underdog Secondary Scorers

**Status: COMPLETE — MIXED verdict, rule conflicts identified**
**Mode:** `--mode blowout-regime`
**Output:** `data/backtest_blowout_regime.json`
**Sample:** 1,874 PTS instances (after ≥24 min gate), full 2025-26 season through March 21

**Question:** Do secondary scorers on heavily-favored winning teams show tier hit rate suppression in actual blowout games (final margin ≥ 15)? And do secondary scorers on the losing side show desperation-mode lift or a similar collapse?

**Two regimes under test:**
- **Favored side (blowout_win):** Primary vs. secondary scorer hit rates on teams that won by ≥ 15. Hypothesis: secondary scorers are benched in Q4 garbage time → suppression.
- **Underdog side (blowout_loss):** Primary vs. secondary scorer hit rates on teams that lost by ≥ 15. Hypothesis: two competing regimes — desperation mode (lift) if game was competitive until late, collapse mode (suppression) if deficit was insurmountable early.

**Key design decisions:**
- Uses actual final score margin, not pre-game spread, to classify blowouts
- Minutes gate: player must have played ≥ 24 minutes (excludes true garbage-time appearances on both sides)
- Primary scorer = highest rolling-window PPG whitelisted player on the team that game
- Reuses `build_game_result_lookup()` from H6 for consistency

**Full results table (2025-10-21 – 2026-03-21):**

| Cell | PTS lift (n) | REB lift (n) | AST lift (n) | 3PM lift (n) |
|------|-------------|-------------|-------------|-------------|
| blowout_win_primary | 0.944 (145) | 0.919 (109) | 1.057 (137) | 1.097 (137) |
| blowout_win_secondary | **1.083 (140)** | 0.989 (128) | 1.049 (128) | **1.103 (96)** |
| blowout_loss_primary | 0.867 (99) | 0.873 (78) | 0.942 (95) | 0.907 (86) |
| blowout_loss_secondary | 0.895 (66) | 0.858 (60) | **0.713 (59)** | 0.990 (38) |
| competitive_primary | 1.034 (486) | 1.050 (400) | 1.049 (467) | 1.024 (426) |
| competitive_secondary | 1.034 (431) | 1.031 (401) | 1.001 (397) | 0.983 (272) |

Baseline (all instances, ≥24 min): PTS 74.5% | REB 71.9% | AST 76.0% | 3PM 71.8%

**Key findings:**

**Finding 1: The secondary scorer skip rule is misfiring.**
The current `BLOWOUT_RISK SECONDARY SCORER SKIP` blocks PTS picks for secondary scorers on the favored side. But `blowout_win_secondary` PTS hits at **80.7% (lift=1.083, n=140)** — meaningfully above baseline. 3PM is the same: 79.2% (lift=1.103, n=96). The rule is suppressing picks that hit at above-baseline rates.

The mechanism is clear from `avg_minutes`: `blowout_win_secondary` averages 30.1 min — down from 34.0 in competitive games, but still well above the 24-minute gate. These are rotation players logging real minutes in Q1–Q3 before rest decisions. The true garbage-time benchings — the population the rule intuitively targets — are already below the minutes floor and excluded. The rule fires at pick time based on pre-game spread, but the players it blocks are posting above-baseline production.

**Finding 2: Losing-side secondary AST is the real suppression signal.**
`blowout_loss_secondary` AST: **54.2% (lift=0.713, n=59)** — a 21.8pp drop below baseline, and below the system's 70% pick floor. This is the single largest effect in the entire dataset. Losing teams in blowouts force all creation through their primary ball-handler in desperation mode; secondary assist sequences are eliminated. `blowout_loss_primary` AST is only mildly suppressed (71.6%, lift=0.942) — the primary playmaker absorbs volume but keeps hitting.

Cross-referencing with H20: H20 found no AST suppression using pre-game spread as the predictor. H19 finds massive suppression at actual final margin. These are not contradictory — the signal is **game-script realization**, not pre-game expectation. The Johnson case (ATL lost by 22) makes complete sense: ATL wasn't projected to lose by that margin; they just did.

REB also shows losing-side collapse: `blowout_loss_secondary` REB 61.7% (lift=0.858, n=60). Fewer defensive rebound opportunities when the opponent scores efficiently.

**Finding 3: Losing-side primary PTS is suppressed but hard to operationalize.**
`blowout_loss_primary` PTS: **64.6% (lift=0.867, n=99)** — 10pp below baseline, and below the 70% floor. The current system's blowout penalty applies only to the winning side (via BLOWOUT_RISK); losing-side primary scorer suppression is currently unaddressed. However, operationalizing this requires knowing the final margin at pick time — which we don't have. Flag for offseason when live-score feeds might be available.

**Finding 4: 3PM in blowout wins is elevated, not suppressed.**
Both `blowout_win_primary` (78.8%) and `blowout_win_secondary` (79.2%) for 3PM are well above baseline. The current `3pm_blowout_trend_down` hard skip fires when `trend=down AND BLOWOUT_RISK=True` — it is blocking picks in exactly the environment where 3PM hits at high rates. This directly conflicts with the skip data (100% false skip rate observed in Mar 20 validation). The mechanism: winning-team players logging ≥24 min in blowouts are getting catch-and-shoot opportunities in a relaxed offensive environment.

**Actionable recommendations:**

| Priority | Cell | Finding | Recommended action |
|----------|------|---------|-------------------|
| 🔴 High | blowout_win_secondary PTS | 80.7% vs. current hard skip | Narrow secondary scorer skip: raise threshold to spread_abs ≥ 15, or convert to −10pp penalty instead of hard skip |
| 🔴 High | blowout_win secondary 3PM | 79.2% vs. current hard skip | Retire `trend=down AND blowout_risk` 3PM gate for spread_abs 8–18; keep only spread_abs ≥ 19 unconditional skip |
| 🟡 Medium | blowout_loss_secondary AST | 54.2%, n=59 | Soft −5pp penalty for secondary passers on large underdogs (spread_abs ≥ 15 as proxy); hard skip not warranted given H20 no-signal at pre-game level; offseason for full rule using live-score data |
| ⚪ Low | blowout_loss_primary PTS | 64.6%, n=99 | Flag for offseason — requires live game-script data to operationalize pre-tip |

**On the secondary scorer skip rule specifically:** Two options for the remaining 3 weeks of season:
- **Option A (surgical):** Raise the spread threshold from `spread_abs > 8` to `spread_abs ≥ 15` for the secondary scorer PTS skip. At ≥15 the blowout is near-certain and minutes compression risk is real; at 8–14 it is speculative and the data shows the population still hits at 80%+.
- **Option B (convert to penalty):** Replace the hard skip with a −10pp confidence penalty. Preserves directional signal without blocking an 80.7% population.

Option A is the lower-risk, prompt-only change for in-season. Both options are backed by this data.

**✅ Finding 1 applied (2026-03-22):** Option A implemented — secondary scorer skip threshold raised to `spread_abs ≥ 15` in `build_pick_prompt()`. `build_prompt()` (fallback path) left unchanged per convention.

**On the 3PM blowout gate:** The `spread_abs ≥ 19` unconditional hard skip (added 2026-03-20) is correctly scoped. The broader `trend=down AND BLOWOUT_RISK=True` gate (spread_abs 8–18 range) is the misfiring rule — retiring it entirely is supported by this data and the skip validation false-skip rate.

**✅ Finding 2 applied (2026-03-22):** 3PM blowout trend-down hard skip (spread_abs 8–18) retired in `build_pick_prompt()`. Replaced with a note deferring to the existing trend=down step-down rule only. The `spread_abs ≥ 19` unconditional hard skip is unchanged. `agents/analyst.py` only — `build_prompt()` (fallback path) left unchanged per convention.

---

### H20 — Losing-Side Blowout AST Suppression

**Status: COMPLETE — NO_SIGNAL (2026-03-22)**
**Mode:** `--mode losing-side-ast`
**Output:** `data/backtest_losing_side_ast.json`

**Question:** Does pre-game underdog status (spread_abs ≥ 10) suppress AST tier hit rate for players on the projected-losing team?

**Proposed rule (pending validation):** −10pp AST confidence penalty when the player's team is the underdog by spread_abs ≥ 10. Mirror of the existing winning-side blowout PTS penalty.

**Key design decisions:**
- Uses pre-game spread (not actual final margin) — matches how rules fire at pick time
- Spread buckets: fav_or_even | underdog_6_9 | underdog_10_14 | underdog_15plus | underdog_10plus (combined)
- Tier breakdown within underdog_10plus: T2 / T4 / T6 / T8+ — tests whether effect is
  concentrated at higher tiers where blowout possession compression most likely causes a miss
- Role breakdown: primary ball-handler (rolling AST avg ≥ 6.0) vs. secondary

**Evidence motivating this backtest:** Jalen Johnson AST OVER 6 miss 2026-03-20 (model_gap_rule, actual 3, ATL lost by 22). Third confirmed miss of this archetype in lessons history per audit_summary.json.

**Results (2025-10-21 – 2026-03-21, 1,866 qualified AST instances):**

| Bucket | n | Hit Rate | Lift |
|--------|---|----------|------|
| fav_or_even (baseline) | 1,454 | 74.1% | — |
| underdog_6_9 | 147 | 75.5% | 1.018 |
| underdog_10_14 | 43 | 76.7% | 1.035 |
| underdog_15plus | 11 | 72.7% | 0.981 |
| **underdog_10plus (key)** | **54** | **75.9%** | **1.024** |

Tier breakdown (underdog_10plus): T2 75.8% (n=33), T4 73.3% (n=15), T6 80.0% (n=5), T8+ 100.0% (n=1)
Role breakdown (underdog_10plus): primary ball-handler 80.0% (n=10), secondary 75.0% (n=44)

**Verdict: NO_SIGNAL** — underdog_10plus hit rate 75.9% is *above* baseline 74.1%. Hypothesis not confirmed. The Jalen Johnson miss appears to be a variance event, not a structural suppression pattern. Game-script AST compression on the losing side is not detectable in this season's data at spread_abs ≥ 10.

**Rule recommendation:** No action. Do not add the proposed −10pp AST penalty. Consider rerunning with multi-season data if the archetype continues to show in audit lessons — single-season sample for the ≥10 bucket is only n=54.

---

## Key Signals Summary


| Signal                         | Verdict                                   | Effect Size                                                                                                                            | Applied?                                                                                     |
| ------------------------------ | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Rolling window (w10 vs w20)    | w20 better                                | REB T8 +7.8pp to 71.0%, 3PM T2 +5.9pp to 77.3% at w20                                                                                  | ✅ PLAYER_WINDOW=20                                                                           |
| Tier calibration               | Several tiers below 70% threshold         | REB T8 63.2%(w10)→71.0%(w20); AST T6 65.1%; PTS T20 69.6%                                                                              | ✅ Ceiling rules in prompt (3PM T2 ceiling removed — now 71.4%)                               |
| 3PM opp_defense                | **NOISE** (corrected from predictive)     | soft 69.7%, mid 72.3%, tough 73.5%; lift variance 0.053                                                                                | ⚠️ Prior inverted prompt instruction needs removal                                           |
| Trend (L5 vs L10)              | Noise (all stats)                         | Lift variance < 0.05                                                                                                                   | ✅ Removed as directive signal                                                                |
| Home/away                      | Noise                                     | Lift variance < 0.03                                                                                                                   | ✅ Removed as directive signal                                                                |
| AST trend                      | Weak                                      | AST "up" 80.4% (lift=1.070, n=439)                                                                                                     | ❌ Below predictive threshold; not applied                                                    |
| AST opp_defense                | Weak                                      | Soft 78.3% vs tough 71.6% (7pp)                                                                                                        | ❌ Below predictive threshold; not applied                                                    |
| 3PM pace_tag                   | Predictive                                | High 72.5% vs mid 61.2% (lift=0.853, n=85 mid)                                                                                         | ✅ Data surfaced; pace tag in context                                                         |
| B2B (own team)                 | Noise (aggregate) / quantified per player | Directionally −3% but below threshold                                                                                                  | ✅ B2B rates surfaced; one-tier-down fallback when n<5                                        |
| Spread / blowout risk          | Weak                                      | High-spread: REB 77.6%, AST 79.3% high-spread; blowout flag                                                                            | ✅ Blowout flag + spread rules in prompt                                                      |
| Bounce-back (league-wide)      | Slump-persistent                          | Overall lift=0.89; REB lift=0.83 (n=300) — slump persists                                                                              | ❌ No blanket rule; player-level integrated                                                   |
| Bounce-back (player-level)     | Strong for specific players               | 16 iron floor combos; post-miss profiles in quant output                                                                               | ✅ bb_lift / iron_floor in quant + prompt                                                     |
| Cold streak → mean reversion   | **3PM: decline; others: null**            | 3PM severe cold 68.3%(lift=0.87, n=161); PTS/REB/AST independent                                                                       | ⚠️ 3PM finding actionable — prompt rule candidate                                            |
| Recency decay weighting        | Marginal                                  | w20_d0.95 +2.1pp over 31 test days                                                                                                     | ❌ Within noise; no change                                                                    |
| Post-Blowout Bounce-Back (H6)  | NOISE                                     | Post-blowout lift 0.955–0.988; lift variance ≤ 0.08                                                                                    | ❌ Closed                                                                                     |
| Opponent Schedule Fatigue (H7) | NOISE                                     | Opp B2B lift 0.977–1.025; dense bucket = 0 instances                                                                                   | ❌ Closed                                                                                     |
| FG% Safety Margin (H11)        | Structural — shipped without backtest     | Explainability feature; validates via audit log                                                                                        | ✅ ft_safety_margin in quant + analyst                                                        |
| Shot Volume / H13              | NOISE / CONFOUNDED                        | Median FGA sanity check failed                                                                                                         | ❌ Closed                                                                                     |
| Positional DvP (H8)            | **REVERT (PTS/REB/AST) / KEEP (3PM)**     | Team-level beats positional on PTS/REB/AST (lift adv −0.05 to −0.06); 3PM positional lift adv +0.106. Inversion on PTS/REB frontcourt. | ⚠️ Remove `DvP [POS]` from prompt for PTS/REB/AST; retain field in quant; 3PM activation TBD |
| Player × Opponent H2H (H9)     | QUEUED                                    | —                                                                                                                                      | ⏳ ~mid-April 2026                                                                            |
| Miss Anatomy (player-level)    | QUEUED — quant fields live                | near_miss_rate / blowup_rate in player_stats.json                                                                                      | ⏳ ~late March 2026; analyst wiring deferred                                                  |
| In-game blowout regime (H19)       | **MIXED** (2026-03-22)                 | Favored secondary: ELEVATED not suppressed (PTS lift=1.083, 3PM lift=1.103). Underdog secondary AST: COLLAPSE (lift=0.713, n=59). Underdog REB secondary: COLLAPSE (lift=0.858, n=60). | ✅ Finding 1 applied (2026-03-22): secondary scorer skip narrowed to spread_abs ≥ 15 in `build_pick_prompt()`. ✅ Finding 2 applied (2026-03-22): 3PM blowout trend-down hard skip (spread_abs 8–18) retired; trend=down step-down applies instead. spread_abs ≥ 19 unconditional skip unchanged. Underdog AST collapse flagged for annotation-only rule. |
| Losing-side AST suppression (H20) | **NO_SIGNAL** (2026-03-22)             | underdog_10plus 75.9% vs baseline 74.1% (lift=1.024, n=54); no suppression detected                                                   | ❌ Closed — no rule change; rerun with multi-season data if archetype persists in audit |


