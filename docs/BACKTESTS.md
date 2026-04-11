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

### H31 — Playoff Series Progression

**Status: FIRST RUN COMPLETE — April 11, 2026**
**Mode:** `--mode series-progression`
**Output:** `data/backtest_series_progression.json`
**Data:** `data/playoff_career_log.csv` (2021–2025, 1,883 playoff player-games, 73 series, 59 unique players, 44 qualified at ≥15 playoff games)

**Question:** Do tier hit rates shift as a playoff series progresses from games 1–2 (early) to games 3–4 (mid) to games 5–7 (late)? Do defensive adjustments accumulate in measurable ways?

**Motivation:** Defensive scheming intensifies as a series progresses — primary scorers get more aggressive attention, bench rotations tighten, elimination pressure mounts. Some players rise to elimination games; others fade under scrutiny. Population preview shows subtle effects; per-player analysis may reveal stronger individual patterns. Complements H28 (overall playoff adjustment) by adding a within-series temporal dimension.

**Method:** Infer series from (season, sorted team abbreviation pair). Sort by `(season, matchup, player_name, game_date)` and use `cumcount() + 1` per group to assign game-in-series number. Phase assignment: early (G1–2), mid (G3–4), late (G5–7). Phase distribution in the dataset: 699 / 675 / 509 player-games respectively (late is naturally lower because not all series go 6+ games). Per-player progression delta = (late hit rate − early hit rate) × 100 at the key tier (PTS T20, REB T6, AST T4, 3PM T2). Flags: LATE_RISER (delta ≥ +8pp), LATE_FADER (delta ≤ −8pp), STABLE. Per-series game logs preserved in JSON for evidence review.

**Population findings (pooled across all players):**

| Stat | Tier | early | mid   | late  | delta(e→l)  |
|------|------|-------|-------|-------|-------------|
| PTS  | T15  | 64.2% | 63.9% | 64.8% | +0.6pp      |
| PTS  | T20  | 46.8% | 47.4% | 48.1% | **+1.3pp**  |
| PTS  | T25  | 28.0% | 29.3% | 28.9% | +0.9pp      |
| PTS  | T30  | 16.5% | 19.3% | 16.3% | −0.2pp      |
| REB  | T4   | 72.4% | 73.6% | 75.8% | +3.4pp      |
| REB  | T6   | 50.4% | 52.4% | 54.8% | **+4.4pp**  |
| REB  | T8   | 32.0% | 32.7% | 36.0% | +4.0pp      |
| REB  | T10  | 19.2% | 19.7% | 19.8% | +0.6pp      |
| AST  | T2   | 75.3% | 75.3% | 75.0% | −0.3pp      |
| AST  | T4   | 46.8% | 46.4% | 50.5% | **+3.7pp**  |
| AST  | T6   | 24.3% | 24.3% | 27.5% | +3.2pp      |
| AST  | T8   | 12.7% | 12.9% | 14.7% | +2.0pp      |
| 3PM  | T1   | 73.1% | 72.9% | 71.3% | −1.8pp      |
| 3PM  | T2   | 50.2% | 49.9% | 48.3% | **−1.9pp**  |
| 3PM  | T3   | 30.3% | 29.0% | 28.1% | −2.2pp      |

**Interpretation:**
- **PTS: flat** (+0.6 to +1.3pp across tiers). The narrative that defenses clamp down on scorers as series progress is NOT supported at the population level — aggregate scoring production is remarkably stable across phases. Defensive adjustments likely net out across the population because some players are targeted while others get easier looks.
- **REB: slight late-series lift** (+3.4 to +4.4pp at mid tiers). Tighter rotations mean starters log more minutes and can collect more boards; late-series possession battles often produce more missed shots. Statistically meaningful (n ≈ 500–700 per phase) but well below the 8pp per-player progression threshold.
- **AST: slight late-series lift at the mid tiers** (T4 +3.7pp, T6 +3.2pp) but flat at T2 and T8. Primary creators may be forced to make more reads as defenses trap scorers, redistributing looks.
- **3PM: slight late-series decline** (−1.8 to −2.2pp across tiers). This is the only stat that shows directional compression in playoffs. Plausible mechanisms: defenses prioritize closing out on shooters as the series narrows, less open-look variance, tighter defensive rotations.

**Per-player flag distribution (44 qualified players):**

| Flag              | n  | Notes |
|-------------------|----|-------|
| LATE_RISER        | 11 | PTS T20 delta ≥ +8pp early→late |
| STABLE            | 18 | PTS T20 delta within ±8pp |
| LATE_FADER        | 11 | PTS T20 delta ≤ −8pp early→late |
| INSUFFICIENT_DATA | 4  | <5 games in early or late phase |

**LATE_RISERS (11):**

| Player                 | po_n | series | PTS(T20) e→m→l      | delta   |
|------------------------|------|--------|---------------------|---------|
| Desmond Bane           | 27   | 5      | 10%→40%→71%         | +61.4pp |
| Norman Powell          | 24   | 4      | 0%→62%→38%          | +37.5pp |
| Bennedict Mathurin     | 22   | 4      | 0%→38%→33%          | +33.3pp |
| Julius Randle          | 30   | 6      | 42%→67%→67%         | +25.0pp |
| Darius Garland         | 22   | 5      | 40%→29%→60%         | +20.0pp |
| Kawhi Leonard          | 22   | 5      | 80%→100%→100%       | +20.0pp |
| Karl-Anthony Towns     | 45   | 8      | 44%→62%→62%         | +17.7pp |
| Andrew Wiggins         | 39   | 7      | 14%→21%→27%         | +13.0pp |
| Rudy Gobert            | 52   | 10     | 5%→0%→17%           | +11.7pp |
| Kevin Durant           | 31   | 6      | 92%→92%→100%        | +8.3pp  |
| Shai Gilgeous-Alex.    | 33   | 6      | 92%→83%→100%        | +8.3pp  |

**LATE_FADERS (11):**

| Player              | po_n | series | PTS(T20) e→m→l     | delta    |
|---------------------|------|--------|--------------------|----------|
| James Harden        | 45   | 8      | 56%→62%→23%        | −33.1pp  |
| Devin Booker        | 47   | 9      | 89%→65%→67%        | −22.2pp  |
| Paul George         | 25   | 4      | 100%→88%→78%       | −22.2pp  |
| Stephen Curry       | 43   | 8      | 87%→93%→71%        | −15.3pp  |
| Anthony Edwards     | 42   | 8      | 75%→81%→60%        | −15.0pp  |
| Austin Reaves       | 26   | 5      | 30%→60%→17%        | −13.3pp  |
| Derrick White       | 73   | 13     | 31%→8%→19%         | −11.8pp  |
| Jamal Murray        | 46   | 8      | 69%→62%→57%        | −11.7pp  |
| OG Anunoby          | 33   | 6      | 42%→36%→30%        | −11.7pp  |
| Tyrese Maxey        | 41   | 7      | 50%→29%→38%        | −11.5pp  |
| Evan Mobley         | 25   | 5      | 30%→10%→20%        | −10.0pp  |

**Standout narrative observations:**
- **James Harden's −33.1pp is the largest fade in the dataset** — quantifies his well-known playoff collapses. From 56% PTS T20 in early games to 23% in late games across 45 playoff games in 8 series. This is one of the cleanest "famous pattern confirmed by data" results in the NBAgent backtest suite.
- **Curry's −15.3pp fade** is surprising given his reputation as a playoff closer. The 87→93→71% pattern suggests he peaks in games 3–4 and cools in games 5–7. May be driven by defensive scheming becoming more aggressive as the matchup is understood, or by Curry's tendency to run out of gas on high-usage possessions.
- **Anthony Edwards (−15.0pp)** and **Booker (−22.2pp)** both fade, despite both being flagged as MINUTES_SCALERS in H30 — the playoff minutes bump helps them in aggregate (H30) but the within-series defensive adjustment catches up (H31). Combined reading: these players do well in early-round light matchups but run into trouble in conference finals / NBA Finals.
- **Desmond Bane's +61.4pp** is the biggest late-riser but comes from a thin early-game sample (n=10 early, 10% hit rate → n=5+ late, 71%). Treat as directional, not definitive.
- **Jokic STABLE** — no pattern in either direction, which is consistent with his reputation as a metronomic playoff performer. His REB and AST show matching stability (not shown in PTS table).
- **Jayson Tatum STABLE** at +7.1pp — just under the LATE_RISER threshold. Tatum shows a mid-series spike (+18pp at mid vs early) that settles back in late games.

**Sample size caveat:** Per-player late-phase data is inherently thin. The 5-game minimum per phase allows players who played 5+ late-series games to qualify, but a 5-game sample is still noisy. Flags with `n_late < 10` should be treated as directional, not definitive. Bane (n_late≈5-7), Norman Powell (similar), Mathurin (similar) all sit in this zone. The top LATE_FADERS (Harden n=45, Booker n=47, Curry n=43) have richer samples and should be trusted more.

**Downstream consumer (deferred to separate task):** A future playoff confidence-adjustment layer could read each player's `progression_delta_pp` and current series phase (inferred from game-in-series on the day of the pick) to apply a phase-weighted confidence bump or fade. This is the most nuanced playoff adjustment the backtest suite has produced — it composes with H28 (overall playoff delta) and H30 (minutes elasticity) to produce a three-layer playoff confidence model.

---

### H32 — Player Consistency Index

**Status: FIRST RUN COMPLETE — April 11, 2026**
**Mode:** `--mode consistency-index`
**Output:** `data/backtest_consistency_index.json`
**Data:** `data/player_game_log.csv` + `data/nba_master.csv` (3,645 non-DNP player-games, 58 unique players, 56 qualified at ≥20 games)

**Question:** How stable is each player's tier hit rate across contextual dimensions (Home/Away, Rest, Spread)? Which players are "all-weather" picks and which are highly context-sensitive?

**Motivation:** Aggregate tier hit rates mask context variance. A player with 80% overall but 25pp range across home/away is fundamentally different from one with 80% and 5pp range. For playoffs, this matters more: games skew road-heavy (2-2-1-1-1 format), no B2Bs but dense every-other-day scheduling, and higher-leverage spread contexts. All-weather players deserve stable confidence; context-sensitive players need context-weighted adjustments based on today's slate position.

**Method:** For each player with ≥20 games, compute the modal best_tier per stat (via `add_best_tiers`) and measure hit rate across 7 possible context slices: home, away, rest_B2B, rest_normal, rest_extended, spread_competitive (spread_abs ≤ 6.5), spread_blowout_risk (> 6.5). Slices with <5 games excluded. Stats with <3 valid slices skipped. Range = max slice rate − min slice rate (in pp). Per-dimension range computed for each of {home_away, rest, spread}. Stat flag: ALL_WEATHER (range <10pp), MODERATE (10–20pp), CONTEXT_SENSITIVE (≥20pp). Overall player flag: ALL_WEATHER (all stats all-weather), HAS_VULNERABILITY (any stat context-sensitive), MODERATE (middle). Worst vulnerability = (stat, dimension, range_pp) triple with highest dim_range.

**Headline population finding — context-invariance is the exception, not the rule:**

| Flag              | n  | Notes |
|-------------------|----|-------|
| ALL_WEATHER       | 0  | No player has <10pp range in all 4 stat categories |
| MODERATE          | 4  | Julius Randle, Jamal Murray, Jaylen Brown, Norman Powell |
| HAS_VULNERABILITY | 52 | At least one stat with ≥20pp range across contexts |

**Dominant vulnerability pattern: the REST dimension.** Rest was the worst dimension for 33 of 56 players (59%), spread was worst for 13 (23%), home/away was worst for 7 (12%). This suggests the system's current implicit treatment of rest (via `b2b_hit_rates` in quant output) captures a large fraction of context-driven variance, but the rest-sensitivity is distributed so broadly that quant-level per-player gating is likely more impactful than any population rule.

**Top 10 worst vulnerabilities (all at key tier by modal best_tier):**

| Player               | n  | Stat(tier)     | Dimension  | range  | Slice detail                          |
|----------------------|----|----------------|------------|--------|---------------------------------------|
| Jalen Williams       | 33 | 3PM(T1)        | spread     | 64.3pp | comp:0% blow:64%                       |
| Coby White           | 22 | PTS(T10)       | home_away  | 50.0pp | H:100% A:50%                           |
| Joel Embiid          | 39 | PTS(T25)       | spread     | 48.3pp | comp:52% blow:100%                     |
| Paul George          | 43 | 3PM(T2)        | spread     | 46.4pp | comp:54% blow:100%                     |
| Bennedict Mathurin   | 25 | PTS(T15)       | rest       | 43.3pp | B2B:83% normal:69% extended:40%        |
| Tyler Herro          | 51 | PTS(T15)       | rest       | 40.4pp | B2B:30% normal:69% extended:29%        |
| Derrick White        | 79 | 3PM(T2)        | rest       | 39.7pp | B2B:100% normal:60% extended:78%       |
| Nikola Jokic         | 64 | AST(T8)        | rest       | 39.9pp | B2B:57% normal:97% extended:76%        |
| Cameron Johnson      | 55 | PTS(T10)       | rest       | 39.1pp | B2B:64% normal:48% extended:88%        |
| Austin Reaves        | 52 | 3PM(T2)        | rest       | 37.5pp | B2B:88% normal:74% extended:50%        |

**Notable narrative patterns from the top 52 vulnerabilities:**
- **Nikola Jokic AST T8 rest compression** (B2B 57% → normal 97% → extended 76%): the elite-creation outlier is badly impacted on B2B nights. This matches the existing analyst rule that applies a one-tier step-down for AST on B2B nights.
- **Joel Embiid PTS T25 spread**: 52% competitive → 100% in blowout games. When PHI is favored, Embiid is automatic; when it's a coin flip, he's a coin flip too. This is the opposite of the blowout_t25_skip rule intuition — Embiid's T25 hit rate is dramatically *higher* in blowout-risk games, not lower.
- **Derrick White 3PM T2 rest**: 100% on B2B → 60% on normal rest → 78% on extended. Counterintuitive: best when rested least. This is likely driven by small sample in the B2B bucket (5-10 games) and reflects noise more than signal.
- **Kevin Durant PTS T20 home_away** (H:70% A:95%, 25pp range): the opposite of the usual home-court narrative. KD plays dramatically better on the road this season.
- **Kawhi Leonard 3PM T2 home_away** (H:82% A:58%, 24pp range): a mirror-image of KD — dramatic home preference.

**MODERATE players (4 — all under 20pp range but none under 10pp in every stat):**
- **Julius Randle** (79g): PTS T15 80% rng=18pp, REB T6 67% rng=17pp, AST T4 73% rng=10pp, 3PM T1 76% rng=9pp — the closest to all-weather in the dataset, and the only player where every stat lands in the 9–18pp band.
- **Jamal Murray** (77g): PTS T20 75% rng=19pp, REB T4 60% rng=16pp, AST T6 65% rng=14pp, 3PM T1 91% rng=17pp
- **Jaylen Brown** (76g): PTS T25 68% rng=11pp, REB T6 67% rng=18pp, AST T4 70% rng=18pp, 3PM T1 84% rng=17pp
- **Norman Powell** (76g): PTS T20 50% rng=14pp, AST T2 57% rng=19pp, 3PM T1 68% rng=13pp

**Important caveat:** The tight 10pp ALL_WEATHER threshold combined with slice-level sample noise (n=5–10 per slice is common) produces a population where ALL_WEATHER is effectively empty. The signal is in the *worst_vulnerability* ranking (who compresses most, on which dimension), not in the flag taxonomy itself. A relaxed threshold (e.g. <15pp = ALL_WEATHER) would produce a handful of qualifying players but the real information is per-player dim_ranges and vulnerability detail.

**Downstream consumer (deferred to separate task):** A future playoff confidence-adjustment layer could read each player's `worst_vulnerability` and slice detail to flag the specific context (rest, home/away, spread) in which that player is reliable or unreliable. Today's slate position would then determine whether the vulnerability fires. Care needed to avoid over-correcting on small-sample slice noise: any per-player rule should gate on slice n ≥ 10 and absolute dim_range ≥ 25pp to be directive.

---

### H30 — Minutes Elasticity

**Status: FIRST RUN COMPLETE — April 11, 2026**
**Mode:** `--mode minutes-elasticity`
**Output:** `data/backtest_minutes_elasticity.json`
**Data:** `data/player_game_log.csv` (3,533 non-DNP player-games, 58 unique players, 56 qualified at ≥20 games)

**Question:** For each player, does their tier hit rate scale with minutes played? When a player gets 38+ minutes (playoff-level load), does their production increase, plateau, or invert?

**Motivation:** Playoff starters play 36–42 min vs 32–36 regular season. A player's aggregate tier rate is diluted by low-minute games (blowouts, foul trouble, managed rest) that won't recur in playoffs. If their 38+ min rate is 90% but aggregate is 50%, the aggregate massively understates their playoff capability — and the 38+ rate is the directly applicable number. Conversely, players who plateau or invert don't benefit from the minutes increase and don't warrant a playoff confidence bump.

**Method:** Bucket each game by actual minutes played using absolute boundaries with `right=False`: **low** [0,30), **normal** [30,34), **high** [34,38), **extended** [38,60). Per-player, per-stat, per-tier hit rates computed per bucket with ≥5 games required. Elasticity = (extended - normal) hit rate at the key tier (PTS T20, REB T6, AST T4, 3PM T2). Monotonicity check verifies whether rates increase consistently across available buckets. Per-stat flags: SCALES (delta ≥ +10pp), PLATEAUS (−10 to +10pp), INVERTS (delta ≤ −10pp). Overall player flag driven by PTS flag with SELECTIVE_SCALER when PTS plateaus but another stat scales.

**Population (pooled across 49 starters with avg min ≥ 28):**

| Stat | Key Tier | low    | normal | high   | extended | elasticity  |
|------|----------|--------|--------|--------|----------|-------------|
| PTS  | T15      | 56.0%  | 72.8%  | 85.9%  | 88.9%    | +16.1pp     |
| PTS  | T20      | 32.5%  | 48.0%  | 62.5%  | 74.0%    | **+26.0pp** |
| PTS  | T25      | 14.5%  | 26.0%  | 36.7%  | 54.9%    | **+28.9pp** |
| PTS  | T30      | 6.0%   | 10.3%  | 20.1%  | 36.9%    | +26.6pp     |
| REB  | T4       | 64.3%  | 73.1%  | 82.2%  | 86.8%    | +13.7pp     |
| REB  | T6       | 37.7%  | 47.8%  | 56.9%  | 64.8%    | **+17.0pp** |
| REB  | T8       | 19.0%  | 27.2%  | 34.0%  | 43.2%    | +16.0pp     |
| REB  | T10      | 9.5%   | 14.3%  | 18.2%  | 26.0%    | +11.7pp     |
| AST  | T2       | 77.8%  | 88.2%  | 91.8%  | 94.6%    | +6.4pp      |
| AST  | T4       | 44.0%  | 54.8%  | 68.4%  | 75.9%    | **+21.1pp** |
| AST  | T6       | 20.4%  | 26.9%  | 39.1%  | 53.6%    | +26.7pp     |
| AST  | T8       | 8.5%   | 10.8%  | 21.0%  | 31.8%    | +21.0pp     |
| 3PM  | T1       | 68.5%  | 78.5%  | 81.1%  | 82.1%    | +3.6pp      |
| 3PM  | T2       | 42.4%  | 54.7%  | 57.6%  | 64.3%    | **+9.6pp**  |
| 3PM  | T3       | 22.2%  | 32.9%  | 37.4%  | 42.4%    | +9.5pp      |

**Population elasticity is massive and monotone at every tier.** Every bucket is higher than the previous one across PTS/REB/AST at every tested tier. 3PM shows the weakest elasticity (3PM T1 only +3.6pp) which makes sense: a shooter in foul trouble still hits 1 three, and a shooter in extended minutes can't take more than his shot allocation allows. PTS T25 shows the largest elasticity (+28.9pp), consistent with the story that high-tier scoring is strongly minutes-dependent.

**Per-player distribution (56 qualified players):**

| Flag                 | n  | Notes |
|----------------------|----|-------|
| MINUTES_SCALER       | 23 | PTS flag = SCALES (delta ≥ +10pp at T20) |
| SELECTIVE_SCALER     | 6  | PTS plateaus but REB/AST/3PM scales |
| MIXED                | 3  | PTS plateaus with 1+ inverting stats |
| MINUTES_INDEPENDENT  | 0  | All stats plateau |
| MINUTES_INVERTER     | 2  | PTS flag = INVERTS (delta ≤ −10pp) |
| INSUFFICIENT_DATA    | 22 | < 5 games in normal or extended bucket |

**Top MINUTES_SCALERS (PTS T20 progression low→norm→high→ext):**

| Player             | avg_min | n_ext | PTS(T20)              | elasticity | monotonic |
|--------------------|---------|-------|-----------------------|------------|-----------|
| Alperen Sengun     | 33.3    | 12    | 29→29→56→83%          | +54.7pp    | ↑         |
| Miles Bridges      | 31.1    | 7     | 14→17→63→71%          | +54.2pp    | ↑         |
| Jalen Johnson      | 35.2    | 26    | 33→42→54→92%          | +50.6pp    | ↑         |
| Paolo Banchero     | 34.7    | 20    | 40→42→59→90%          | +48.3pp    | ↑         |
| Bam Adebayo        | 32.5    | 11    | 32→50→57→91%          | +40.9pp    | ↑         |
| Scottie Barnes     | 33.5    | 10    | 27→30→32→70%          | +40.4pp    | ↑         |
| Brandon Ingram     | 33.8    | 9     | 11→50→65→89%          | +38.9pp    | ↑         |
| Anthony Edwards    | 35.0    | 22    | 38→62→87→100%         | +37.5pp    | ↑         |
| Nikola Jokic       | 35.1    | 18    | 70→67→96→100%         | +33.3pp    | ·         |
| Luka Doncic        | 35.8    | 34    | 57→88→100→100%        | +12.5pp    | ↑         |
| Jamal Murray       | 35.4    | 26    | 22→80→80→92%          | +12.3pp    | ↑         |
| Tyrese Maxey       | 38.2    | 42    | —→83→82→95%           | +11.9pp    | ·         |

**Ant Edwards T25 rates (the canonical extreme case):** 25% low → 50% normal → 69.6% high → **86.4% extended** — a +61.4pp span. Aggregate T25 rate would grossly understate his playoff T25 capability.

**MINUTES_INVERTERS (2 players):**
- **Donovan Mitchell** (33.4 avg min): 67→76→88→57% at PTS T20, −19.1pp elasticity. Note: only 7 extended-bucket games — sample-limited but directionally suggestive of diminishing returns at high minutes.
- **LeBron James** (33.4 avg min): 67→68→52→40% at PTS T20, −28.0pp. Monotonically DECLINING through the buckets, only 5 extended-bucket games. Consistent with the "LeBron at age 41" story: efficiency drops when minutes stretch.

Both inverters have small extended-bucket samples (n=5, 7) so treat the signal as directional, not definitive.

**MIXED (3 players):**
- **SGA** — PTS T20 at 100% in every bucket (absolute floor). PLATEAUS flag for PTS with MIXED overall due to REB/AST/3PM secondary flags. SGA gets no PTS bump from increased minutes because there's no headroom above 100%.
- **Jaylen Brown** — 60→93→97→94% at PTS T20, plateaus at high minutes.
- **Cade Cunningham** — 17→75→91→75% at PTS T20, inverts slightly at extended.

**INSUFFICIENT_DATA (22 players):** Most of these are players whose average minutes sits below 32, so they don't have ≥5 games in the extended (38+) bucket. Examples: LaMelo Ball, Jalen Green, Jarrett Allen, CJ McCollum, Hartenstein, Norman Powell, RJ Barrett, Chet Holmgren, Evan Mobley. This is not a bug — it's real information that these players don't typically log 38+ min in the regular season. Their playoff rates at 38+ min will be genuinely extrapolatory.

**Downstream consumer (deferred to separate task):** A future playoff confidence adjustment layer could use this data by reading each scaler's `extended_key_rates` or `playoff_projection.vs_overall_delta` as a direct confidence bump for playoff picks. Candidates for the strongest +5 to +10pp playoff bumps: Banchero, Ant Edwards, Jalen Johnson, Sengun, Bam Adebayo, Jokic, Scottie Barnes, Paolo Banchero. Candidates for NO bump or a slight tax: LeBron, Mitchell (with caveat about small sample).

**Important caveat:** Sample sizes in the extended bucket are thin for many otherwise-qualified players (5–10 games). The elasticity number is real at the population level (+26pp PTS T20 is not noise) but individual player deltas carry sample noise. Any per-player production rule should require n_extended ≥ 10 or treat the flag as directional only.

---

### H29 — Player-Level Confidence Calibration

**Status: FIRST RUN COMPLETE — April 11, 2026**
**Mode:** `--mode confidence-calibration`
**Output:** `data/backtest_confidence_calibration.json`
**Data:** `data/picks.json` (815 graded picks, 87.1% overall hit rate, avg assigned confidence 77.1%)

**Question:** For each player with sufficient pick history, does the analyst's assigned confidence match their actual hit rate? Which players are systematically over-confident (assigned > actual) or under-confident (assigned < actual)?

**Motivation:** Population calibration shows the analyst is under-confident at every band: 70–75% band hits at 85.5% (+12.5pp), 76–80% at 88.3% (+9.2pp). But population averages mask per-player variation — some players are rated too conservatively (under-confident) while others are over-rated despite weaker actual results. With playoffs narrowing the pick pool to ~20 players over repeated series games, per-player calibration deltas are directly actionable: they tell the system how to adjust confidence for each player without adding any new signal.

**Method:** Group graded picks (`result in HIT/MISS`, not voided) by player. Compute mean `confidence_pct` vs actual hit rate for each player with `n_picks >= 10`. Per-prop and per-band sub-breakdowns (`n >= 5` per prop, `n >= 3` per band). Miss severity: mean `pick_value - actual_value` across misses (positive = below threshold, lower = near-miss, higher = structural failure). Flags: **OVER_CONFIDENT** (calibration_delta ≤ −8pp), **UNDER_CONFIDENT** (calibration_delta ≥ +8pp), **WELL_CALIBRATED** (otherwise). Population confidence band recomputation cross-validates against `audit_summary.json`.

**Population confidence bands (815 picks):**

| Band    | n   | avg_conf | actual | delta    | flag            |
|---------|-----|----------|--------|----------|-----------------|
| 70–75   | 352 | 73.0%    | 85.5%  | +12.5pp  | UNDER_CONFIDENT |
| 76–80   | 368 | 79.1%    | 88.3%  | +9.2pp   | UNDER_CONFIDENT |
| 81–85   | 70  | 82.9%    | 85.7%  | +2.8pp   | (within window) |
| 86+     | 25  | 89.4%    | 96.0%  | +6.6pp   | (within window) |

The 70–75 and 76–80 bands carry 88% of all picks (720 of 815) and both sit well into UNDER_CONFIDENT territory. The tighter 81–85 and 86+ bands are closer to calibrated but still slightly under. This is consistent with the existing `confidence_calibration_totals` block in `audit_summary.json` and validates the pick mechanism.

**OVER_CONFIDENT players (2 of 31 qualified):**

| Player            | n  | actual | avg_conf | delta    | Notable |
|-------------------|----|--------|----------|----------|---------|
| Brandon Ingram    | 13 | 61.5%  | 76.7%    | −15.2pp  | PTS 40% (n=5), AST 66.7% (n=6) — both prop-specific over-confidence |
| Donovan Mitchell  | 23 | 65.2%  | 75.6%    | −10.4pp  | PTS 60% (n=5), 3PM 42.9% (n=7) — 3PM particularly poor |

Ingram's over-confidence is structural — small sample but consistent across props. Mitchell's AST picks (77.8%, n=9) are fine; the problem is concentrated in his PTS and 3PM picks, which is actionable (analyst can apply the calibration only to those two props).

**UNDER_CONFIDENT players (18 of 31 qualified, top 8 by magnitude):**

| Player               | n  | actual | avg_conf | delta    | Notable |
|----------------------|----|--------|----------|----------|---------|
| Paolo Banchero       | 23 | 95.7%  | 76.2%    | +19.5pp  | PTS 100% (n=14), AST 83.3% (n=6) — both consistent under-rating |
| Cade Cunningham      | 12 | 91.7%  | 73.1%    | +18.6pp  | AST 100% (n=6) — consistent under-rating |
| Jaylen Brown         | 23 | 95.7%  | 77.4%    | +18.3pp  | PTS 91.7% (n=12), AST 100% (n=8) — both consistent |
| Victor Wembanyama    | 12 | 91.7%  | 74.2%    | +17.5pp  | PTS 100% (n=5), AST 83.3% (n=6) — limited sample but clear |
| LeBron James         | 20 | 95.0%  | 77.7%    | +17.3pp  | AST 100% (n=10) — consistent under-rating |
| Luka Doncic          | 30 | 93.3%  | 77.6%    | +15.7pp  | PTS 100% (n=12), 3PM 100% (n=8) — both consistent |
| Kon Knueppel         | 27 | 92.6%  | 78.0%    | +14.6pp  | PTS 100% (n=9), AST 91.7% (n=12) — both consistent |
| Shai Gilgeous-Alex.  | 33 | 90.9%  | 77.4%    | +13.5pp  | PTS/AST/3PM all tagged consistent under-rating |

Also in the UNDER_CONFIDENT cluster: LaMelo Ball, Austin Reaves, Giannis, Sengun, Desmond Bane, Kawhi Leonard, Jokic, James Harden, Scottie Barnes, Julius Randle (all +8 to +14pp). This is a LOT of the core pick pool — the mechanism is systematic prompt caution on elite scorers with strong quant signals.

**Downstream implication (deferred to separate task):** A future analyst prompt enhancement could inject per-player calibration floors into the pick rules. The data supports:
1. Floor lifts for UNDER_CONFIDENT players (e.g. +5pp minimum confidence bump for Banchero/Cunningham/Brown/Wemby/LeBron/Luka/Knueppel)
2. Caution notes for OVER_CONFIDENT players (−5pp minimum cap for Ingram/Mitchell, prop-scoped where possible)
3. Do NOT modify well-calibrated players (11 of 31 — the current mechanism is correct for them)

**Caveat:** Most UNDER_CONFIDENT results cluster at 80-95% actual vs 77% assigned — this is partly a reflection of the system's conservative confidence floor (70% minimum). A rule that lifts confidence by +10pp for these players would push many into the 86+% band, which itself calibrates at 96% — so the lift is justified by the data. But be careful not to double-count: the existing `confidence_calibration` block in `audit_summary.json` already informs the `bet_recommendation` calibrated_prob used by the odds integration layer. Per-player calibration should slot in AS OR BEFORE that band lookup, not in addition to it.

---

### H28 — Playoff Career Tier Performance

**Status: FIRST RUN COMPLETE — April 11, 2026**
**Mode:** `--mode playoff-career`
**Output:** `data/backtest_playoff_career.json`
**Data:** `data/playoff_career_log.csv` (2021–2025, 18,168 regular + 1,883 playoff games, 58 players qualified after ≥5 playoff-game filter; 47 reliable / 11 limited-sample)

**Question:** For each playoff-bound player, do their playoff career tier hit rates differ meaningfully from their regular season rates? Which players reliably elevate in playoffs and which compress?

**Motivation:** Playoff basketball is structurally different: tighter rotations (+3–5 min/game for starters), increased usage concentration, defensive scheming against primary options, elimination pressure. Some players historically thrive (Edwards +22.7pp AST T4, Mitchell +10.7pp REB T6, Jokic +16.0pp 3PM T2) while others compress (Embiid −12.3pp PTS T20, KAT −16.1pp PTS T20, Tyler Herro −37.0pp PTS T20). These per-player adjustments are the single most valuable playoff calibration signal because the pick pool narrows to ~20 players who each appear in 4–16 picks per series — population averages obscure player-specific tendencies entirely.

**Method:** Compare same-player regular season vs playoff tier hit rates using career data from `playoff_career_log.csv` (apples-to-apples, same multi-year window). Per-player, per-stat flags: ELEVATOR (delta ≥ +5pp at key tier), STABLE, SUPPRESSOR (delta ≤ −5pp). Key tiers: PTS T20, REB T6, AST T4, 3PM T2. Overall flag based on cross-stat pattern: STRONG_ELEVATOR (3+ ELEVATOR stats) / ELEVATOR (2 ELEVATOR, no SUPPRESSOR) / MIXED / STABLE / SUPPRESSOR / STRONG_SUPPRESSOR. Population pooled rates as baseline. Per-player playoff game logs preserved in JSON for evidence review.

**Population (pooled across 58 qualifying players):**

| Stat | Key Tier | reg_rate | po_rate | delta   |
|------|----------|----------|---------|---------|
| PTS  | T20      | 46.8%    | 47.5%   | +0.7pp  |
| REB  | T6       | 47.3%    | 52.2%   | +4.9pp  |
| AST  | T4       | 52.5%    | 47.6%   | −4.9pp  |
| 3PM  | T2       | 51.3%    | 49.7%   | −1.6pp  |

Population deltas are small — the signal is entirely per-player. REB rates lift slightly (fewer fast-break possessions → more half-court rebounds), AST rates drop modestly (tighter rotations concentrate creation in fewer hands), PTS and 3PM are near flat at the population level. The interesting information lives in the per-player table.

**STRONG_ELEVATOR players (6 of 47 reliable sample):**

| Player             | po_n | min_d | PTS(T20)     | REB(T6)      | AST(T4)       | 3PM(T2)       |
|--------------------|------|-------|--------------|--------------|---------------|---------------|
| Paolo Banchero     | 12   | +3.8  | 65→83 +18.5  | 70→83 +13.5  | 69→67 −2.1    | 42→83 +41.6   |
| Paul George        | 25   | +6.1  | 61→88 +27.3  | 56→84 +28.4  | 67→84 +17.1   | 80→80 −0.5    |
| Jalen Williams     | 33   | +4.1  | 43→52 +8.4   | 33→55 +21.9  | 56→85 +28.4   | 38→52 +13.0   |
| CJ McCollum        | 16   | +4.7  | 58→69 +10.3  | 25→56 +31.1  | 72→56 −15.8   | 76→81 +5.0    |
| Anthony Edwards    | 42   | +4.6  | 67→74 +7.1   | 44→64 +20.5  | 58→81 +22.7   | 76→74 −2.0    |
| Austin Reaves      | 26   | +6.5  | 24→38 +14.1  | 24→31 +6.8   | 53→62 +8.8    | 50→62 +11.7   |

**STRONG_SUPPRESSOR players (15 of 47 reliable sample)** — highlights include Tyler Herro (−37.0pp PTS T20, −29.9pp 3PM T2), Julius Randle (−30.1pp REB T6, −17.1pp AST T4), KAT (−16.1pp PTS T20, −36.1pp AST T4), Maxey (−24.1pp AST T4), Mikal Bridges (−16.0pp PTS T20, −14.0pp AST T4), Payton Pritchard (−10.6pp PTS T20, −11.5pp REB T6, −11.4pp AST T4, −11.8pp 3PM T2 — uniformly suppressed).

**Notable per-stat findings from the detail tier breakdowns:**
- **Jokic PTS** is ELEVATOR at every tier (T15 +5.8pp, T20 +9.4pp, T25 +11.1pp, T30 +12.6pp) — the playoff version of Jokic is *more* lethal, not less, when defenses collapse on him.
- **Jokic AST** is STABLE at T4 (−3.5pp) but SUPPRESSOR at T6 (−12.2pp) and T8 (−13.7pp) — Jokic distributes less in playoffs at the higher assist tiers but still hits low-volume creation targets. The key-tier flag is T4 so overall AST reads STABLE, but any rule reading `tiers` directly will see the T6/T8 suppression.
- **Tatum** is MIXED with PTS T20 −6.5pp (SUPPRESSOR at key tier), but AST T4 +16.6pp (ELEVATOR) — he absorbs more creation load in playoffs, which pulls from his scoring.
- **Jaylen Brown** is MIXED: PTS T20 +0.3pp (STABLE), but REB T6 +17.4pp (ELEVATOR) and 3PM T2 −7.5pp (SUPPRESSOR) — rebounds go up, threes go down.
- **Brunson** shows a strong PTS T20 lift (+17.0pp) but is MIXED overall because the other stats are STABLE — a pure scoring elevator, not a usage profile shift.

**Limited-sample standouts (5–9 playoff games, treat as annotation only):**
- ⚠ **Alperen Sengun** (7g, +8.2 min): PTS T20 +26.7pp, REB T6 +24.1pp, AST T4 +30.1pp → STRONG_ELEVATOR. Matches his profile as a center whose usage spikes when given more minutes.
- ⚠ **Cade Cunningham** (6g, +7.3 min): PTS T20 +37.0pp, REB T6 +51.9pp, AST T4 −6.6pp, 3PM T2 −39.1pp → MIXED. Massive PTS/REB elevation with 3PM collapse — old Detroit playoff sample, shooter-dependent context.
- ⚠ **Jalen Johnson** (8g, −15.6 min): STRONG_SUPPRESSOR across all four stats — minutes crushed in playoff role, small sample.

**Downstream consumer:** Future playoff context block injection into analyst prompt (separate task). Output schema includes per-player `stats[stat].flag`, `key_tier_delta_pp`, full `tiers` sub-dict, and `playoff_game_log` for evidence review. The `summary` top-level dict maps `player_name → overall_flag` for quick lookup.

**Action:** NOT YET SHIPPED to production. Wiring into analyst prompt is explicitly out of scope for this backtest task — output is ready for consumption when the playoff context prompt lands.

---

### H27 — Primary Scorer Blowout PTS Performance

**Status: FIRST RUN COMPLETE — April 11, 2026 — VERDICT MIXED, ACTION DEFERRED**
**Mode:** `--mode primary-blowout`
**Output:** `data/backtest_primary_blowout.json`
**Sample:** 228/154/68 primary-scorer instances at spread_abs ≥ 10/12/15 (full 2025-26 season through 4/10)

**Question:** Do primary scorers on the favored side reliably hit PTS T25 in high-spread games (spread_abs ≥ 15), or is the `blowout_t25_skip` rule correctly suppressing a structural risk? Is the documented suppression Jokic-specific rather than a general primary-scorer pattern?

**Motivation:** `blowout_t25_skip` has 100% false skip rate on graded skips (2/2 — Maxey actual 32, Wembanyama actual 40). The rule was motivated by Jokic (8 PTS at spread_abs=15.5) and SGA (20 PTS at spread_abs=19.5, which actually hit T20). Jokic's unique play style (triple-double center who distributes more in comfortable leads) may not generalize to other primary scorers.

**Method:** Pre-game spread classification (not final margin). Three thresholds: spread_abs ≥ 10/12/15. Primary vs secondary via `classify_player_role()`. Actual-outcome overlay: tracks whether anticipated blowout materialized (final margin ≥ 15) as secondary analysis — reveals whether suppression is game-script dependent or baked into spread. Per-player breakdown at ≥ 15 with individual game logs isolates player-specific tendencies. Jokic-specific removal test at spread_abs ≥ 15.

**Population results (PTS T25 hit rate, primary scorers, favored side):**

| Threshold | n   | T25 rate | vs baseline (50.6%) | Verdict    |
|-----------|-----|----------|---------------------|------------|
| ≥ 10      | 228 | 57.5%    | +6.9pp              | MARGINAL   |
| ≥ 12      | 154 | 54.5%    | +3.9pp              | SUPPRESSED |
| ≥ 15      | 68  | 58.8%    | +8.2pp              | MARGINAL   |

Non-monotone: the suppression at ≥12 does not intensify at ≥15. Primary scorers at ALL three thresholds hit T25 at or above their full-dataset baseline, which is the opposite of what `blowout_t25_skip` assumes.

**Actual-outcome overlay at spread_abs ≥ 15 — the most important finding:**

| Bucket              | n  | T25 rate |
|---------------------|----|----------|
| actual_blowout=True | 35 | 45.7%    |
| actual_blowout=False (stayed competitive) | 19 | 73.7%    |

**Delta = +28.0pp** — when the spread said blowout and the game actually materialized as one, primary scorers were suppressed (45.7%, below baseline). When the spread said blowout but the game stayed competitive, primary scorers ELEVATED to 73.7% (well above baseline). Flagged as `GAME_SCRIPT_DEPENDENT` — suppression is real but only when the blowout actually happens, suggesting spread alone is not the right trigger. This means the analyst rule is firing on games that, roughly half the time, will stay competitive and deliver above-baseline T25 hits.

**Jokic isolation at spread_abs ≥ 15:** `JOKIC_OUTLIER_NOT_CONFIRMED` (T25 ex-Jokic 59.7% vs with-Jokic 58.8%, delta=+0.9pp, n_with=68, n_ex=67). Jokic had 1 qualifying game in the sample (not enough to skew the population). The Jokic-specific hypothesis is not supported at the population level by this dataset — there aren't enough Jokic blowouts to test it cleanly. Conclusion: don't make a player-specific exemption for Jokic based on this run.

**Per-player primary scorer breakdown at spread_abs ≥ 15 (n ≥ 3):**

| Player              | Team | n  | blow/comp | avg_min | min_d | avg_pts | T25    | base_T25 | delta   | flags                                |
|---------------------|------|----|-----------|---------|-------|---------|--------|----------|---------|--------------------------------------|
| Kevin Durant        | HOU  | 4  | 1/1       | 33.0    | -3.3  | 22.8    | 1/4    | 56.1%    | -31.1pp | PLAYER_SUPPRESSED                    |
| Cade Cunningham     | DET  | 4  | 2/2       | 23.0    | -10.4 | 15.0    | 1/4    | 54.7%    | -29.7pp | PLAYER_SUPPRESSED, MINUTES_COMPRESSED |
| Luka Doncic         | LAL  | 3  | 2/1       | 24.7    | -10.3 | 25.0    | 2/3    | 81.5%    | -14.8pp | MINUTES_COMPRESSED                   |
| Shai Gilgeous-Alex. | OKC  | 21 | 7/5       | 30.6    | -2.2  | 29.8    | 16/21  | 82.8%    | -6.6pp  |                                      |
| Jaylen Brown        | BOS  | 6  | 3/2       | 31.7    | -0.5  | 24.8    | 4/6    | 70.3%    | -3.6pp  |                                      |
| Tyrese Maxey        | PHI  | 3  | 2/1       | 36.0    | -1.9  | 26.0    | 2/3    | 68.4%    | -1.7pp  |                                      |
| LaMelo Ball         | CHA  | 4  | 4/0       | 27.5    |  +0.0 | 20.2    | 1/4    | 23.2%    | +1.8pp  | PLAYER_RESILIENT                     |
| Donovan Mitchell    | CLE  | 6  | 2/3       | 32.0    | -0.9  | 32.2    | 5/6    | 66.1%    | +17.2pp | PLAYER_RESILIENT                     |
| Jamal Murray        | DEN  | 3  | 1/2       | 37.0    |  +1.9 | 31.3    | 3/3    | 48.4%    | +51.6pp | PLAYER_RESILIENT                     |

**Per-player interpretation:**
- **Durant (HOU)** is the most suppressed elite scorer in the sample — dropped 31.1pp in T25 rate. Mechanism appears to be the Houston roster context (multiple scoring options, Sengun/Amen absorbing usage). 9 total HOU primary-scorer games at ≥15 is tiny, but the signal is directionally alarming.
- **Cunningham (DET)** is doubly flagged — suppressed AND minutes-compressed (-10.4 min). DET is rebuilding and loses blowouts badly; this is a losing-side effect, not a favored-side one.
- **Luka** minutes-compressed but not severely suppressed — the 81.5% baseline cushion absorbs the drop. Most suppressed cases are minutes-driven.
- **SGA** is the only player with a meaningful sample (n=21) and sits at -6.6pp — below his baseline but still producing 16/21 (76.2%) T25 hits. This is what a healthy primary scorer in blowouts looks like.
- **Mitchell and Murray** are PLAYER_RESILIENT in blowouts — they maintain or improve, consistent with the spec's "most primary scorers still hit T25 reliably" hypothesis.
- **Five players show mild suppression (-17 to -2pp), three show resilience.** Suppression is real but concentrated in specific situations (HOU roster, DET collapses, minutes compression) rather than uniform.

**Rule implication (NOT YET SHIPPED):** The current `blowout_t25_skip` hard-skip of ALL primary scorer PTS T25/T30 at spread_abs ≥ 15 is **over-penalizing**. A better rule would be:
1. Replace hard skip with a confidence cap (e.g., -5pp) at spread_abs ≥ 15 for primary scorers — matches the MARGINAL verdict
2. Keep hard skip only for players with repeated PLAYER_SUPPRESSED flags across multiple seasons (player-specific, not structural)
3. Consider no rule at all — the 68-game primary population hits T25 at 58.8%, above baseline 50.6%. The false skip rate on graded data (Maxey, Wembanyama) aligns with this population signal.

**Action:** DEFERRED. Do not modify `analyst.py` in-season based on a single-season sample. The GAME_SCRIPT_DEPENDENT finding is compelling but operationalizing it requires knowing whether the game will actually be a blowout at pick time, which we don't. Revisit after playoffs when the sample includes more high-spread series games. For now, the per-player flags inform offseason discussion of player-specific rules.

### H26 — Star Absence Teammate Impact

**Status: CONFIRMED SIGNAL — April 10, 2026**
**Mode:** `--mode star-absence`
**Output:** `data/backtest_star_absence.json`
**Sample:** 14 teams, 31 teammate observations, 2025-10-21 → 2026-04-09 (full season through 4/9)

**Verdict:** SIGNAL at PTS T15–T25 (+11–13pp weighted delta, 71–77% directionally positive, n=31) and AST T4 (+9.6pp, 71% positive). REB and 3PM are noise. Per-player direction varies — population lift is strong but individual teammates can show drags (e.g. Jalen Green PTS cratered without Booker). Any production rule must check per-player history, not just population average.

**Question:** When a team's leading scorer is absent, do teammate tier hit rates lift in measurable amounts — specifically at the tiers where NBAgent picks (PTS T15/T20/T25, AST T4/T6)?

**Motivation:** On 2026-04-09, Jayson Tatum's PTS pick was penalty-skipped by the analyst but he scored 24 (clearing T20) when Jaylen Brown was confirmed OUT. The system currently has no way to quantify the expected teammate lift on a star absence, which directly affects two downstream features: (1) re-evaluation of skipped picks in `lineup_update.py` when a star teammate flips to confirmed OUT post-morning, (2) a potential absence-driven confidence adjustment rule in the analyst prompt.

**Method:**
- **Star identification:** Per team, highest PTS avg with ≥`SA_MIN_STAR_GAMES` (20) non-DNP games in the window. Sort by PTS avg descending, `drop_duplicates(subset=team, keep=first)`.
- **Absence detection:** Reads the *raw* `player_game_log.csv` (not the DNP-filtered `player_log` used by other backtest modes) so DNP rows are available. A team date is "star-absent" when the team played (any row for that team/date exists in the full log) but the star has no non-DNP row for that date — covers both DNP flags and entirely missing rows.
- **Per-teammate tier hit rates:** For each whitelisted teammate on a qualifying team, split their non-DNP games by the `_star_absent` flag. Compute hit rates at every tier (PTS 10/15/20/25/30, REB 4/6/8/10/12, AST 2/4/6/8/10/12, 3PM 1/2/3/4) with minimum `SA_MIN_CONDITION_N` (3) games per condition. Delta = hit_rate_without − hit_rate_with.
- **Population aggregation:** Weighted average delta across all (team × teammate × tier) observations, weight = `min(n_with, n_without)`. Also: unweighted mean, observation count, and percentage of positive-delta observations.
- **Verdict thresholds:** SIGNAL at |delta| ≥ +3pp with n_obs ≥ 10, NOISE otherwise, negative (star presence helps) if delta ≤ −3pp.

**Constants:** `SA_MIN_STAR_GAMES=20` | `SA_MIN_ABSENT_GAMES=5` | `SA_MIN_CONDITION_N=3`

**Population summary (weighted avg delta across all teams):**

| Tier | Weighted Δ | Unweighted Δ | n_obs | % positive |
|---|---|---|---|---|
| PTS_T15 | **+11.3pp** | +12.9pp | 31 | 77% |
| PTS_T20 | **+12.7pp** | +15.9pp | 31 | 71% |
| PTS_T25 | **+10.5pp** | +14.4pp | 31 | 71% |
| PTS_T30 | +7.1pp | +9.3pp | 31 | 64% |
| REB_T6 | +5.2pp | +5.5pp | 31 | 55% |
| REB_T12 | +3.7pp | +3.6pp | 31 | 36% |
| AST_T4 | **+9.6pp** | +10.0pp | 31 | 71% |
| AST_T6 | **+6.7pp** | +8.0pp | 31 | 55% |
| AST_T8 | +6.6pp | +9.3pp | 31 | 42% |
| 3PM_T2 | +2.6pp | +4.3pp | 31 | 48% |

**Verdict: SIGNAL at PTS_T15/T20/T25 and AST_T4/T6.** All five key tiers cross the +3pp SIGNAL threshold with ≥10 observations. PTS_T20 is the strongest at +12.7pp (71% positive). REB shows directional lift but weaker (+1.6 to +5.2pp) — likely because the absent star is usually a wing/guard scorer, not a rebound competitor. 3PM is essentially noise across all tiers (+0.4 to +2.6pp).

**Motivating BOS case validated in data:** The backtest identifies Jaylen Brown (26.9 PPG, 75g) as BOS's leading scorer because Tatum had only 15 qualifying non-DNP games in the window (missed the gate). In Brown's 5 absent games:
- **Jayson Tatum PTS T20**: with Brown = 72.7%, without Brown = **100% (4/4)**, Δ = **+27.3pp**
- **Jayson Tatum PTS T25**: with Brown = 9.1%, without Brown = **50% (2/4)**, Δ = **+40.9pp**
- **Payton Pritchard PTS T20**: with Brown = 28.8%, without Brown = **100% (6/6)**, Δ = **+71.2pp**
- **Payton Pritchard PTS T15**: with Brown = 57.5%, without Brown = **100%**, Δ = **+42.5pp**

Small per-teammate samples (4–6 absent games), but direction is strong and consistent. The population-level aggregation across all 14 teams × 31 teammates smooths out individual small-sample noise.

**Caveats before shipping as a production rule:**
1. **Small per-team samples** — only 5 teams have ≥15 star-absent games (MIN 20, DET 18, CHA 17, DEN 16, PHX 16). The other 9 qualifying teams are in the 5–12 range. The signal holds up because the population weights by observation count, but individual team estimates shouldn't be trusted.
2. **Confirmed-OUT vs QUES/GTD distinction not applied** — backtest counts any non-playing date as "absent" regardless of pre-game injury designation. The existing Without-Star Baseline rule in `build_pick_prompt()` gates on confirmed OUT only; any derived rule from H26 should match that gate.
3. **Single-season data** — the 2021–2025 playoff career log doesn't have DNP rows and covers a different set of players (no reliable star-identification across years without carefully handling roster/role changes). Multi-season verification would require reconstructing DNPs from schedule gaps.
4. **Not all "leading scorers" are the system's primary target** — for BOS, Brown is identified (more games played than Tatum this season), but the user's mental model usually has Tatum as the #1. Any derived rule needs to handle "second-highest scorer" lifts or use a different criterion (career PPG, contract value, etc.) depending on use case.

**Downstream consumers (queued for April 12–13 gap — see `docs/ROADMAP_active.md`):**
1. **Skip re-evaluation in `lineup_update.py`** — when a star teammate flips from AVAILABLE to confirmed OUT post-morning, scan `skipped_picks.json` for teammates whose skip reason was `merit_below_floor`, re-estimate confidence with penalties softened by the absence, and emit a `skip_reconsideration` entry to `opportunity_flags.json` if the revised confidence crosses 70%. PTS/AST props only, confirmed-OUT only.
2. **Analyst star-absence uplift annotation** — injected into quant context as an informational `STAR_ABSENT_LIFT` line when the team's leading scorer is confirmed OUT. Supplements (not replaces) the existing two-gate Without-Star Baseline rule. Per-player without-star history takes precedence over the population average whenever available — Jalen Green without Booker (negative per-player drag) must NOT receive the population uplift.

**Multi-season verification (deferred to offseason):** DNP reconstruction from schedule gaps in the 2021–2025 playoff_career_log data would roughly triple the sample size and enable a confirmed-OUT vs QUES/GTD breakdown. Not a blocker for shipping the two annotation-only downstream items above — both respect per-player history and fall back cleanly when data is thin.

---

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

**Status: THIRD RUN COMPLETE — PHX + PHI confirmed suppressors; IND amplifier (Mar 31, 2026)**
**Mode:** `--mode opp-team-hit-rate`
**Output:** `data/backtest_opp_team_hit_rate.json`

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

**Run 1 — March 12, 2026 (279 picks, baseline 85.3%):** No suppressors cleared ±10pp/≥15 picks threshold. MIN×AST notable at −26.4pp (n=7). SAS floor compression (mean −6.0, n=3). Watch items added to `nba_season_context.md`.

**Run 2 — March 22, 2026 (538 picks, baseline 85.3%):**

H15a results (≥15 picks):

| Opponent | n | Hit Rate | vs Baseline | Verdict |
|----------|---|----------|-------------|---------|
| HOU | 21 | 61.9% | −23.4pp | **SUPPRESSOR** |
| MIN | 31 | 77.4% | −7.9pp | Neutral (watch) |
| PHX | 18 | 77.8% | −7.5pp | Neutral |
| SAS | 35 | 82.9% | −2.5pp | Neutral |
| BOS | 21 | 95.2% | +9.9pp | Neutral (borderline amplifier) |
| CHI | 22 | 95.5% | +10.1pp | Amplifier (small-sample artifact) |

Notable H15b prop-specific signals (≥5 picks):

| Matchup | n | Hit Rate | vs Prop Baseline | Verdict |
|---------|---|----------|------------------|---------|
| MIN × AST | 9 | 55.6% | −29.5pp vs 85.1% AST | Below threshold — active scrutiny |
| HOU × PTS | 11 | 63.6% | −22.6pp vs 86.2% PTS | SUPPRESSOR |
| HOU × AST | 8 | 62.5% | −22.6pp vs 85.1% AST | SUPPRESSOR |
| CHA × AST | 6 | 66.7% | −18.4pp vs 85.1% AST | Below threshold |
| GSW × AST | 7 | 71.4% | −13.6pp vs 85.1% AST | Below threshold |
| DAL × 3PM | 7 | 71.4% | −12.4pp vs 83.8% 3PM | Below threshold |

H15c miss margin (≥3 misses):

| Opponent | Misses | Mean margin | Pattern |
|----------|--------|-------------|---------|
| SAS | 6 | −5.0 | Floor compression |
| CHA | 3 | −5.0 | Floor compression (borderline n) |
| HOU | 8 | −2.4 | Near-miss (tier overshoot) |
| MIN | 7 | −1.6 | Near-miss (squeeze, not blow-out) |

Overall miss margin baseline (n=79): mean=−2.7 | median=−2.0 | p25=−3.5 | p75=−1.0

**Key findings:**

1. **HOU is the project's first confirmed system-wide opponent suppressor.** 61.9% hit rate at n=21 clears both the ≥15 pick gate and ≥10pp suppressor threshold by a wide margin. PTS and AST both suppressed. Mechanism: Durant rim deterrence + Udoka switching scheme compress scoring and creation. HOU's H15c near-miss pattern (mean −2.4) suggests tier overshoot — the system is one tier too aggressive vs. Houston. `nba_season_context.md` updated with conservative tier guidance.

2. **MIN × AST is the most alarming prop-specific signal in the dataset (55.6%, n=9, −29.5pp) but has not cleared the formal ≥15 pick gate.** Upgraded from watch to active scrutiny in `nba_season_context.md`. If signal holds to n=15+ by season end, a directive AST rule is warranted next season.

3. **SAS floor compression is holding** (n=6, mean −5.0). Players missing vs. SAS are underperforming their historical floors by 5 units on average — structural suppression. `nba_season_context.md` note updated.

4. **Amplifiers are small-sample noise.** CHI, BOS, MIA, MEM 100% cells range from n=5–11. Do not add positive confidence rules based on these.

**Next run:** End of season (≥600 picks) — check whether additional teams cross the suppressor gate, and whether MIN × AST clears ≥15 picks for formal confirmation.

---

**Run 3 — March 31, 2026 (≥600 picks, baseline 85.3%):**

H15a results — confirmed suppressors and amplifiers (≥15 picks):

| Opponent | n | Hit Rate | vs Baseline | Verdict |
|----------|---|----------|-------------|---------|
| PHI | 17 | 64.7% | −20.6pp | **SUPPRESSOR** (new) |
| HOU | 23 | 65.2% | −20.1pp | **SUPPRESSOR** (confirmed, updated from 61.9%/n=21) |
| PHX | 24 | 75.0% | −10.3pp | **SUPPRESSOR** (new) |
| MIN | 35+ | ~77% | ~−8pp | Neutral (watch) |
| IND | 23 | 100.0% | +14.7pp | **AMPLIFIER** (new) |

Notable H15b prop-specific updates (≥5 picks):

| Matchup | n | Hit Rate | vs Prop Baseline | Verdict |
|---------|---|----------|------------------|---------|
| MIN × AST | 11 | 63.6% | ~−21pp vs AST baseline | Below ≥15 gate — active scrutiny (4 more needed) |
| MIN × 3PM | 8 | 100.0% | +16pp vs 3PM baseline | Small-sample noise |
| PHI × PTS | ~5 | ~40% | extreme suppression | Game-script caveat (see below) |

**Key findings:**

1. **PHX confirmed as second system-wide suppressor (75.0%, n=24, −10.3pp).** Clears both the ≥15 pick gate and the ≥10pp threshold. Mechanism: Barkley/Booker offensive-first roster means opponents are playing catch-up, but PHX's transition defense and length suppresses scoring opportunity counts. `nba_season_context.md` updated with PHX suppressor note.

2. **PHI confirmed as suppressor (64.7%, n=17, −20.6pp) — game-script/tanking caveat.** Numbers clear all thresholds, but PHI is a tanking team in 2025-26 — defensive intensity is low, but blowout game-script compression (PHI losing badly, reduced opponent possessions in Q4 garbage time) may be the driving mechanism rather than defensive scheme. Conservative guidance: apply one-tier step-down vs. PHI for PTS props, especially on favored-side opponents. PTS suppression is particularly extreme (~40% hit rate at n≈5). `nba_season_context.md` updated with PHI suppressor note and game-script caveat.

3. **IND confirmed as system's first amplifier (100.0%, n=23, +14.7pp).** Clears the ≥15 pick gate by wide margin. All prop types running at 100%. Mechanism: Indiana's transition pace and relatively weak interior defense creates scoring and creation opportunities across all stat categories. Flag for positive awareness — not a reason to add confidence rules (100% rates are likely due to small-sample clustering), but IND opponents are historically not a reason to step down. `nba_season_context.md` updated.

4. **MIN × AST at n=11 (63.6%, −21pp) — 4 more picks needed to clear formal gate.** Season ends April 12, 2026. If 4 more MIN AST picks are generated, this will clear the gate and warrant a directive rule in the offseason. Monitor closely through playoffs.

5. **HOU suppressor holding and strengthening** (updated 65.2%/n=23 from 61.9%/n=21). Signal stable across the larger sample. HOU season context note remains in place.

**Next run:** End of season / playoffs — close tracking of MIN×AST for ≥15 pick gate clearance. No further structural re-runs planned.

---

### H14 — Elite Opposing Rebounder REB Suppression

**Status: COMPLETE — NO_SIGNAL verdict (2026-03-22)**
**Mode:** `--mode elite-opp-rebounder`
**Output:** `data/backtest_elite_opp_rebounder.json`
**Sample:** 1,709 qualified REB instances, 2025-10-21 – 2026-03-21

**Question:** Does the presence of an elite opposing rebounder (rolling REB avg ≥ 8/10/12) or high opponent team REB total suppress whitelisted players' REB tier hit rates?

**Two sub-hypotheses:**
- **H14a:** Individual: opponent's best rebounder rolling avg ≥ threshold → REB suppression
- **H14b:** Team: opponent team total REB rate above median → REB suppression

**Key design decisions:**
- Rolling avg for opponent players uses all players in log (not just whitelisted) — opponent roster requires the full player population
- shift(1).rolling() on all opponent player averages — no lookahead
- Three thresholds tested: 8.0, 10.0, 12.0 REB/g rolling avg
- Verdict anchored to threshold=10.0 as the primary decision threshold

**H14a results:**

| Threshold | elite_present n | elite hit rate | no_elite n | no_elite hit rate | lift |
|-----------|-----------------|---------------|------------|-------------------|------|
| ≥ 8.0 REB | 499 | 69.7% | 527 | 70.0% | 0.992 |
| ≥ 10.0 REB | 202 | 70.3% | 824 | 69.8% | 1.000 |
| ≥ 12.0 REB | 40 | 67.5% | 986 | 70.0% | 0.960 |

Baseline REB hit rate: **70.3%** (n=1,709)

**H14b results (team REB median split):**

| Bucket | n | Hit Rate | Lift |
|--------|---|----------|------|
| high_opp_reb | 857 | 70.5% | 1.003 |
| low_opp_reb | 852 | 70.1% | 0.997 |

**Verdict: NO_SIGNAL**

Delta at thresh=10.0: **−0.5pp** (no_elite 69.8% vs elite_present 70.3%) — directionally opposite to suppression hypothesis and well below the 4pp noise threshold. H14b team-level median split is essentially flat (70.5% vs 70.1%, lift difference 0.006). The hypothesis is not confirmed at any threshold.

**Why:** Elite rebounders do not appear to claim a disproportionate share of available rebounds in a way that suppresses opposing whitelisted players' REB output at the tier-hit-rate level. The Sengun vs. Jokic motivating case may be a single-game variance event rather than a structural pattern.

**Rule recommendation:** No action. Do not add any REB suppression rule based on opposing elite rebounder presence.

---

### H21 — Miss Anatomy: Near-Miss vs. Blowup Next-Game Prediction

**Status: COMPLETE — NOISE verdict (2026-03-22)**
**Mode:** `--mode miss-anatomy`
**Output:** `data/backtest_miss_anatomy.json`
**Sample:** 2,669 player-game rows, 48 players, 2025-10-21 – 2026-03-21

**Question:** Does the severity of a miss (near-miss within 2 units vs. blowup 3+ units below tier) predict next-game hit rate differently?

**Results:**

| Stat | post_near_miss | post_blowup | Delta | Verdict |
|------|---------------|------------|-------|---------|
| PTS | 66.2% (n=142) | 65.6% (n=363) | +0.6pp | NOISE |
| REB | 60.0% (n=285) | 58.0% (n=193) | +2.0pp | NOISE |
| AST | 64.9% (n=348) | 64.1% (n=106) | +0.8pp | NOISE |
| 3PM | 63.9% (n=393) | 54.5% (n=11) | — | INSUFFICIENT_SAMPLE |

**Verdict: NOISE across all stats.** The null hypothesis holds — whether a previous miss was close (within 2 units) or bad (3+ units below tier) does not predict whether the player hits the same tier next game. Maximum delta is 2.0pp (REB), well below the 4pp threshold.

**Player-level notable separations** (≥15pp delta, min 3 games per bucket) are present but samples are too small (n=4–11) to be actionable — the deltas are variance at these sizes.

**Rule recommendation:** Do NOT ship any directive rule based on `near_miss_rate` or `blowup_rate`. The quant fields remain in `player_stats.json` for Player Profiles conditional rendering (existing use unchanged). No analyst prompt changes required.

---

### H17 — Spread Context vs. Tier Hit Rate

**Status: SECOND RUN COMPLETE — NOISE verdict confirmed (Mar 22, 2026)**
**Mode:** `--mode spread-context`
**Output:** `data/backtest_spread_context.json`
**Sample:** 538 graded picks (PTS: 189, REB: 96, AST: 154, 3PM: 99), full 2025-26 season through March 21. Excluded (no spread match): 0. Baseline: 85.3%.

**Question:** Does pregame spread magnitude predict tier pick hit rate? Does the relationship differ meaningfully across prop types? Is the existing binary competitive/blowout split at spread_abs=6 the right threshold?

**Layer 1 — Overall hit rate by spread bucket:**

| Bucket | Hit Rate | n | vs. Baseline |
|--------|----------|---|--------------|
| 0-3    | 85.2%    | 108 | −0.1pp |
| 4-6    | 85.2%    | 155 | −0.2pp |
| 7-9    | 87.2%    | 125 | +1.9pp |
| 10-13  | 82.4%    | 74  | −2.9pp |
| 14+    | 85.5%    | 76  | +0.2pp |

**Layer 2 — Hit rate by prop type × spread bucket:**

|     | 0-3       | 4-6       | 7-9       | 10-13     | 14+       |
|-----|-----------|-----------|-----------|-----------|-----------|
| PTS | 86.0%(43) | 83.6%(55) | 88.1%(42) | 92.3%(26) | 82.6%(23) |
| REB | 80.0%(15) | 84.6%(26) | 88.5%(26) | 78.6%(14) | 93.3%(15) |
| AST | 87.1%(31) | 82.0%(50) | 83.9%(31) | 80.0%(20) | 95.5%(22) |
| 3PM | 84.2%(19) | 95.8%(24) | 88.5%(26) | 71.4%(14) | 68.8%(16) |

**Layer 3 — Threshold validation:**

Current binary split (≤6 vs >6): 85.2% (n=263) vs. 85.5% (n=275) — gap: **−0.3pp** (essentially zero). The existing threshold has no predictive power at all.

Best single threshold search (4.0–12.0, step 0.5):
- Rank 1: split at 9.5 → gap 3.6pp (≤9.5: 86.1% n=418 | >9.5: 82.5% n=120)
- Rank 2: split at 10.0 → gap 3.5pp
- Rank 3: split at 9.0 → gap 3.1pp

Even the best threshold produces only 3.6pp gap — well below the ±10pp signal threshold applied to other backtest verdicts.

**Continuous gradient:** Nearly empty — spread values cluster around half-points that span integer buckets (structural data artifact). Only spread_abs=1 (66.7%, n=6) and spread_abs=4 (80.0%, n=5) had ≥5 picks. No continuous trend visible.

**Verdict: NOISE — confirmed at second run (n=538, +211 from first run of 327).**

The overall spread-to-hit-rate relationship is flat. The current binary split at spread_abs=6 has essentially zero predictive value (−0.3pp gap). The most interesting cell-level signal is 3PM at 10-13 (71.4%, n=14) and 14+ (68.8%, n=16) — both below the 70% floor — but the blowout rules already implemented at spread_abs ≥ 8–15 address this population directly. No new spread-based rules warranted. The existing tier ceiling rules, blowout confidence caps, and BLOWOUT_RISK flag cover the cases where spread context provides genuine signal.

**Rule recommendation:** No action. Existing rules already capture the meaningful spread-context effects. Do not add a spread bucket modifier or change the binary split threshold.

**CLOSED.** NOISE confirmed at 538 picks (rerun Mar 22). Maximum bucket gap 2.9pp. Best threshold search finds 3.6pp at spread_abs ≥ 9.5 — insufficient for a rule. The spread_abs value at pick time has no meaningful predictive relationship with whether picks hit across the full population. Blowout rules in the system (BLOWOUT_RISK penalty, tier caps, skip rules) are justified by specific audited miss archetypes — not by this population-level signal, which is flat.

**3PM × large spread footnote:** 3PM at spread_abs ≥ 10 ran 69–71% across both the 10-13 and 14+ buckets (combined n≈30). Below the 70% floor, but the sample is too small and the finding is contradicted by H19's blowout_win result (3PM hits at 79.2% for favored-side players with ≥24 min in actual blowouts). The population below 70% is likely the players already excluded by existing rules (trend=down, spread_abs ≥ 19 skip, etc.). Watch item at best — not actionable on its own.

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
| Opponent team hit rate (H15)   | **HOU CONFIRMED SUPPRESSOR** (2026-03-22, n=538) | HOU 61.9% (n=21, −23.4pp). MIN×AST 55.6% (n=9, −29.5pp) — active scrutiny, below formal gate. SAS floor compression (n=6, −5.0). | ✅ `nba_season_context.md` updated: HOU suppressor note added, MIN×AST upgraded, SAS note updated. Re-run at ≥600 picks. |
| Spread context (H17)           | **NOISE — CLOSED** (2026-03-22, n=538) | Overall spread-to-hit-rate flat; current ≤6 vs >6 split gap = −0.3pp (zero). Best threshold 9.5 → 3.6pp gap — not actionable. 3PM ≥10 (n≈30, 69–71%) below floor but contradicted by H19 blowout_win finding. | ❌ CLOSED — no rules warranted. Blowout rules justified by specific miss archetypes, not this signal. |
| Miss Anatomy / H21 (player-level) | **NOISE — CLOSED** (2026-03-22, n=1,482) | PTS delta 0.6pp, REB delta 2.0pp, AST delta 0.8pp — all below 4pp threshold. 3PM blowup n=11 (insufficient). No player-level signal at actionable sample sizes. | ❌ CLOSED — no directive rule shipped. `near_miss_rate`/`blowup_rate` remain in quant for Player Profiles only. |
| In-game blowout regime (H19)       | **MIXED** (2026-03-22)                 | Favored secondary: ELEVATED not suppressed (PTS lift=1.083, 3PM lift=1.103). Underdog secondary AST: COLLAPSE (lift=0.713, n=59). Underdog REB secondary: COLLAPSE (lift=0.858, n=60). | ✅ Finding 1 applied (2026-03-22): secondary scorer skip narrowed to spread_abs ≥ 15 in `build_pick_prompt()`. ✅ Finding 2 applied (2026-03-22): 3PM blowout trend-down hard skip (spread_abs 8–18) retired; trend=down step-down applies instead. spread_abs ≥ 19 unconditional skip unchanged. Underdog AST collapse flagged for annotation-only rule. |
| Losing-side AST suppression (H20) | **NO_SIGNAL** (2026-03-22)             | underdog_10plus 75.9% vs baseline 74.1% (lift=1.024, n=54); no suppression detected                                                   | ❌ Closed — no rule change; rerun with multi-season data if archetype persists in audit |
| Elite opposing rebounder (H14)    | **NO_SIGNAL** (2026-03-22, n=1,709)   | thresh=10.0: elite_present 70.3% vs no_elite 69.8% (delta=−0.5pp). H14b team REB flat (70.5% vs 70.1%). No suppression at any threshold (8/10/12). | ❌ CLOSED — no rule change. Sengun vs. Jokic was variance. |


