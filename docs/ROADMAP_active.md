# NBAgent — Roadmap - Active

---

## Open Items

### Operational
- **Whitelist maintenance** — review and update `active` flags as the season evolves, especially post-trade-deadline role changes
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **DST → PDT cron shift** — ✅ Fixed March 12, 2026 — all UTC offsets in `injuries.yml` decremented by 1 for PDT (UTC-7). Coverage 10:45 AM – 8:45 PM PT on :15/:45 cadence (21 entries; added 10:45 AM entry, retained all prior slots). Reverse action required November 2026 when clocks fall back — add to October re-enable checklist.

### Untested Hypotheses (backtest designs documented in `docs/BACKTESTS.md`)
- **H9 — Player × Opponent H2H Splits** — Does a player's historical hit rate against today's specific opponent predict next-game performance better than the population-level opp_defense rating? Requires near-complete season sample (~mid-April 2026). See Active Queue entry M1 for implementation design.

### Odds Integration
**Two-phase implementation. Phase 1 is an April target; Phase 2 is offseason.**

**Phase 1 — Data collection (April 2026):** Wire a player prop odds aggregator API (OddsAPI recommended starting point — free tier available) into a new daily ingest step. Fetch prop lines for whitelisted players, write to `data/odds_today.json`, append `market_implied_prob` and `edge_pct` to each pick in `picks.json` at analyst write time. No UI changes, no betting behavior changes. Goal: accumulate odds-tagged pick history through the playoffs so offseason analysis can answer "were our highest-edge picks actually our best picks?" Four weeks of tagged data by season end is the minimum useful sample.

**Phase 2 — Decision support UI (offseason / next season):** Kelly sizing display on pick cards (bet X% of bankroll), edge highlighting (system confidence vs. market implied), "market disagrees" flag when market implied prob is >10pp above system confidence. The three numbers surfaced per pick: market implied probability (prop line → percentage), edge (system confidence − implied), Kelly fraction (edge / odds → recommended bet size as % of bankroll). Output is a single actionable number per pick — no statistics background required to use it.

**Platform note:** Primary execution on Kalshi (CA-legal prediction market, mirrors major books). Kalshi has no official API and displays round payout estimates rather than precise vig-adjusted lines. Odds ingest pulls from aggregator (not Kalshi directly) for analytical precision; execution remains manual. Kelly sizing math is still valid even if Kalshi rounds the displayed payout — size the bet correctly, execute at the closest available line.

**Prerequisite for Phase 1:** Confirm OddsAPI covers NBA player props at sufficient coverage for whitelisted players before committing to it. Check free tier rate limits against daily ingest timing.

**Relationship to existing features:** "Stay Away?" badge (frontend roadmap) is the near-term version of the same risk-surface instinct and should be built first — it uses existing quant fields with no odds dependency. Odds data enhances the badge later (market disagreement becomes one additional signal).

### Technical Debt
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. This is intentional (ensures freshness) but adds ~10s to runtime. Low priority.


### Frontend
- **Parlays tab historical stats banner** — hidden until graded parlay history exists. Once data accumulates (1–2 weeks), evaluate whether to add a rolling chart similar to the picks trend chart.
- **Mobile layout** — current pick cards are readable but not optimized for small screens. Low priority until real users request it.
- **"Stay Away?" UI caution flag** — A `⚠ Stay Away?` badge on pick cards that meet the system's statistical criteria but carry compounding contextual risk signals. Does NOT suppress the pick — purely informational for manual betting decision. Badge triggers when 2+ risk signals co-occur on the same pick. Candidate signals: team momentum `[cold]` tag, opponent `[hot]` tag, `DENSE` schedule, `B2B`, `blowout_risk`, player on `[cold]` matchup DvP split, `VOLATILE` + weak trend. Badge expands a drawer (same UX pattern as "show reasoning") listing whichever signals fired and a brief plain-English summary. Implementation: small new field on pick output (`stay_away_signals: []`) written by analyst if signals fire; `build_site.py` renders badge + drawer. No new LLM calls, no new quant logic. Prerequisite: team momentum indicator live in production so `[hot]`/`[cold]` tags are available. Evaluate trigger threshold after momentum data accumulates (~2 weeks).

---

## Active Queue — In Priority Order


### Matchup Signals Queue

Design philosophy: the Analyst already has a solid quantitative matchup foundation (positional DvP, vs_soft/vs_tough splits, game pace, spread context). The following proposals address gaps where rolling averages give a misleading picture because something material has changed that the numbers alone cannot capture.

---

### F1 — Personal Foul Tracking + Foul-Prone Player Profiles
**Status: FUTURE — data pipeline expansion required**
**Priority: LOW — queue for offseason or early next season**

**What:** Track personal fouls (PF) per game in `player_game_log.csv` and surface foul-prone patterns in Player Profiles for players where foul trouble is a recurring performance driver. LaMelo Ball (March 10) is the prototype case: his 22-minute game was driven by early foul trouble in Q1, not load management or a coaching decision. This behavioral pattern — not minutes fragility per se — is a recurring known risk for specific players.

**Why not now:** Requires schema expansion in `espn_player_ingest.py` to collect PF from box scores, a backfill pass on `player_game_log.csv` for historical data, and a new quant function to identify foul-prone players (e.g., games with PF ≥ 4 in the L20 window). The min_floor guardrail already partially mitigates the downstream effect (foul trouble shows up as a low-minutes game). The marginal lift from identifying the cause vs. the effect is real but not urgent given current system coverage.

**Design (when ready):**
- `espn_player_ingest.py` — add `personal_fouls` column to `player_game_log.csv`
- `quant.py` — `compute_foul_trouble_profile()`: flag players with ≥3 games of PF ≥ 4 in L20; surface as `foul_prone` bool + `foul_trouble_rate` (% of L20 games with PF ≥ 4) in `player_stats.json`
- Player Profiles — add conditional rendering: "Foul-prone: X% of recent games with 4+ PF — minutes exposure at risk in tight or physical matchups"
- No directive prompt rules until signal is backtested against actual minutes/performance outcomes

**Where:** `ingest/espn_player_ingest.py`, `agents/quant.py`, `agents/analyst.py` (Player Profiles block only)

---

### Watch-and-Accumulate Items (March 9, 2026)

Items with directional signal but insufficient sample to act. Revisit after 2–3 more weeks of audit data.

#### W1 — 76-80% Confidence Band Underconfidence
**Status: WATCH — do not act until end of season**

8-day calibration (247 graded picks) shows 76-80% band at 88.1% actual vs ~78% expected (+10pp gap, 126 picks = 43% of all picks). This is the largest sustained delta across all bands — well beyond noise. Hypothesis: VOLATILE (-5%) and BLOWOUT_RISK (-5%) penalties are stacking and pushing picks that would otherwise state ~82% down into the 76-80% range, where they dramatically outperform. 81-85% band (33 picks, 84.8%) and 86%+ band (12 picks, 91.7%) are well calibrated. Do not adjust penalty mechanics in-season. Revisit in offseason with full-season sample — if pattern holds, the stacking behavior of VOLATILE + BLOWOUT_RISK is the most likely lever.

#### W2 — REB Opponent-Adjusted Floor
**Status: WATCH — needs 3–4 more model_gap REB misses to justify quant work**

REB has the worst miss profile of any prop type: 4 model_gaps out of 10 total misses, all sharing the same root cause — raw historical L10 floor overstates expected output when the opponent's defensive scheme specifically suppresses rebounding (MIA zone, HOU switching). The existing REB DvP exclusion from positional DvP was correct (rebounding is less positional), but the absence of any opponent-adjusted floor gate is showing up consistently. Conceptual fix: a modifier in the analyst prompt that discounts the qualifying L10 floor when opp_defense is tough for REB — not a hard block, but a downward adjustment to the clearance threshold. **Do not write quant or prompt code until pattern holds another week.**

#### W3 — CLE Switching Scheme / DvP Aggregate Mismatch
**Status: WATCH — single-team signal, needs more instances before generalizing**

Derrick White's two model_gap misses (PTS + 3PM, March 8) expose a gap: CLE's aggregate 3PM DvP rates as "soft" in the team-level data, but their switching scheme neutralizes off-ball guard perimeter looks in a way the aggregate number cannot capture. The fix is architectural (team-level DvP cannot distinguish switching vs. drop coverage) and cannot be resolved with current data. Near-term action: add a CLE scheme note to `context/nba_season_context.md` (or its renamed successor) flagging this mismatch so the analyst has scheme context that the DvP rating doesn't convey. **Generalize to a broader "switching-scheme DvP discount" rule only if similar misses appear for other known switching teams (MIN, BOS, MIL).**

#### W4 — H10 FG_COLD Tier-Step Revisit
**Status: WATCH — one instance, do not act until more FG_COLD misses accumulate**

Cooper Flagg's March 10 miss (14 actual vs 15 pick, FG_COLD:-18%, missed by 1) raised the question of whether FG_COLD ≥ -15% should trigger a hard tier step-down on PTS picks rather than remaining annotation-only. H10 backtest verdict (521 instances) found FG_COLD lift=1.128 (counterintuitively positive) — confidence penalties were removed on that basis. However, the H10 backtest evaluated confidence adjustments, not tier step-downs; these are distinct mechanisms. A tier step-down at high FG_COLD values is an open question the backtest did not directly address. **Do not act until 3–5 additional FG_COLD ≥ -15% PTS misses accumulate in the audit log. If a pattern emerges, revisit whether a tier-step rule is warranted at high thresholds (≥ -15% or ≥ -18%) without conflicting with the H10 annotation-only verdict on confidence.**

#### W5 — Skip Validation: First Data (March 12, 2026)
**Status: WATCH — first graded data arrives tomorrow morning**

March 12 produced 18 skips across 10 players / 6 rules. Two confirmed false skips visible before grading: (1) **Derrick White AST T4** — `ast_hard_gate` should not fire for SG with AST avg >4.0; model reasoned correctly in `rule_context` ("gate technically does NOT fire") then skipped anyway — prompt discipline failure. (2) **Derrick White 3PM T2** — labeled `3pm_trend_down_tough_dvp` but `rule_context` notes DvP is soft, not tough — rule should not have fired; correct action was step-down to T1, not hard skip.

Root cause of both: model evaluates gate condition correctly mid-analysis but does not honor that reasoning in the final skip decision. Pending prompt fix: add output discipline instruction — if model determines a gate condition does NOT fire, it must proceed to confidence calculation, not record a skip. Also: `skip_reason` must reflect the rule that actually triggered, not one evaluated and rejected. **Do not ship fix until tomorrow's graded data confirms false skip rate for `ast_hard_gate`.**

Watch list for graded data: `ast_hard_gate` false-skip rate (White confirmed = 1/3 minimum); `reb_floor_skip` entries (all 5 look clean — strict greater-than rule firing correctly); `volatile_weak_combo` calibration (Doncic 60%, Green 61% reasoning well-supported).


### Pending Backtests

### H15 — Opponent Team Pick Suppression / Lift
**Status: FIRST RUN COMPLETE — rerun triggered at ≥400 graded picks**
**First run:** March 12, 2026 — 279 graded picks
**Rerun ETA:** ~March 20-25 (pick-count dependent, not date-dependent — large slate days like Mar 12 ~52 picks/day accelerate timeline significantly)
**Mode: `--mode opp-team-hit-rate`**

**First run findings (279 picks, Mar 12):**
- H15a (overall by opponent): No suppressors or amplifiers cleared the ±10pp / ≥15 picks threshold. Only 5 opponents had ≥15 picks (MIN, SAS, NYK, DEN, ORL) — all rated neutral. MIN closest at −6.6pp but below actionable threshold.
- H15b (by prop type): **MIN × AST at 57.1% hit rate (n=7), −26.4pp below AST baseline.** Plausible mechanism: Minnesota switching scheme compresses ball-handler assist opportunities. Watch item added to `nba_season_context.md`.
- H15c (miss margin): **SAS floor compression — mean miss margin −6.0 (n=3 misses).** Players missing well below tier threshold vs. SAS, not near-miss variance. Sample too small to act on. CHA at −5.0 (n=3) also flagged. MIN is near-miss pattern (−1.8 avg) — borderline, not structural.
- `nba_season_context.md` updated with MIN AST and SAS floor compression watch items.

**Hypothesis:** Certain opponent teams systematically suppress or amplify the system's tier pick hit rate beyond what the current `opp_defense` soft/mid/tough rating captures. The existing defensive rating measures *allowed averages* — it does not directly measure whether the system's tier picks actually hit or miss against that opponent. A team might rate "soft" on PTS-allowed but the system keeps missing against them due to scheme, pace, or matchup geometry not captured by the average. Conversely, a team rated "tough" might yield high hit rates because their defensive identity concentrates on stopping things (e.g., three-point defense) that are orthogonal to the props we pick.

**Motivating framing:** Individual player hit rates vs. a specific opponent have inadequate sample (2–4 games/season per matchup). Aggregating *all whitelisted player picks vs. Team X* across the full season gives a workable N while measuring the same structural opponent effect.

**Three separable sub-hypotheses:**

1. **H15a — Team-level suppression/lift (overall):** Does facing Opponent X predict system hit rate above or below baseline? Rank all 30 opponents by system-wide hit rate against them. Flag teams where actual hit rate diverges ≥10pp from baseline with ≥15 pick observations.

2. **H15b — Prop-specific suppression:** Does Opponent X suppress REB picks specifically even if their PTS-allowed rating is unremarkable? Compute hit rate by opponent × prop type (PTS / REB / AST / 3PM). A switching scheme may compress AST without affecting PTS; a physical frontcourt may suppress REB without affecting perimeter props. This gives a more actionable signal than the overall rate.

3. **H15c — Tier threshold misalignment:** Does the system's tier selection systematically overshoot against certain opponents? Measure not just hit/miss but *miss margin* — how far below the pick threshold did the player finish on misses against Team X? A consistent miss-by-many pattern (e.g., picking T15 PTS but player averages 10 actual against this opponent) signals the tier ceiling is wrong, not variance. Compare miss margin distribution against Team X vs. all-opponent baseline.

**Relationship to existing hypotheses:**
- **H8 (Positional DvP):** If positional DvP is working, opponents with tough positional ratings should correlate with the team-level suppressors found in H15a/b. If they don't correlate, that's direct evidence DvP rating isn't translating to pick outcomes — the most important validation H8 needs.
- **H14 (Elite Opposing Rebounder):** H15b's REB-by-opponent slice should surface the same teams (DEN, MIL) that H14 targets via the individual-rebounder mechanism. Convergent findings across H14 and H15b strengthen the case for a REB opp annotation.
- **M1 (Situational Profiles, offseason):** H15 is the population-level version of the same investigation, tractable mid-season where M1 is not.

**Data requirements:** All inputs already in existing CSVs.
- `data/picks.json` — all graded picks with `result` (HIT/MISS), `prop_type`, `opponent`, `pick_value`, `actual_value`, `confidence_pct`
- `player_game_log.csv` — for miss margin computation (actual stat value per game)
- `player_whitelist.csv` — position column for prop-specific position filtering if needed

**Key design decisions:**
- **Population:** All graded picks in `picks.json` with `result` in `("HIT", "MISS")` and `voided != True`. Do not filter to whitelist — the pick record is already whitelist-filtered by construction.
- **Opponent key:** Use `opponent` field from picks.json (team abbrev). Normalize via `_ABBR_NORM` dict.
- **Minimum sample gate:** ≥15 picks against an opponent before reporting a hit rate figure. Opponents below threshold reported as "insufficient sample" — do not discard, flag separately.
- **Baseline:** Overall system hit rate across all graded picks (the `overall_hit_rate` figure from `audit_summary.json`).
- **Miss margin (H15c):** For each MISS pick, compute `actual_value - pick_value` (negative = missed below threshold). Report mean miss margin per opponent. A mean miss margin of −5 or worse against a specific team is structurally different from −1 (near-miss variance vs. systematic floor compression).
- **DNP/injury exclusion:** `voided == True` picks already excluded. `injury_event` classified misses should also be excluded from the opponent suppression analysis — they are not evidence of opponent-driven suppression.

**Output structure:**
```
H15a — Overall hit rate by opponent (ranked):
  OKC: 12/18 picks (66.7%) vs baseline 83.9% → −17.2pp [SUPPRESSOR]
  MIA: 8/10 picks (80.0%) vs baseline 83.9% → −3.9pp
  GSW: 9/9 picks (100.0%) vs baseline 83.9% → +16.1pp [AMPLIFIER]
  ...

H15b — Hit rate by opponent × prop type (≥5 picks):
  OKC × AST: 2/6 (33.3%) → −50.6pp [SUPPRESSOR]
  OKC × PTS: 7/9 (77.8%) → −6.1pp
  MIA × REB: 3/5 (60.0%) → −23.9pp [SUPPRESSOR]
  ...

H15c — Mean miss margin by opponent (misses only):
  OKC: mean miss margin −6.2 pts (n=6 misses) [FLOOR COMPRESSION]
  MIA: mean miss margin −3.1 pts (n=2 misses)
  ...
```

**Verdict criteria:**
- **Actionable signal (H15a/b):** ≥15 picks against opponent, hit rate ≥10pp below baseline → warrants `opp_team_flag` annotation in analyst context (not a hard rule — annotation only until mechanism is understood)
- **Actionable signal (H15c):** Mean miss margin ≤ −5 with ≥5 misses → tier overshoot signal; warrants a note in `nba_season_context.md` or player profile conditional rendering
- **Weak signal:** 5–9pp below baseline or mean miss margin −3 to −4 → note in `nba_season_context.md` only; no quant changes
- **Noise:** <5pp divergence or insufficient sample → close sub-hypothesis with no action

**If signal confirmed:** Implementation is annotation-only first. New `opp_team_suppressor` flag in `player_stats.json` (bool per prop type); injected as a single annotation line in `build_quant_context()` when today's opponent is a confirmed system suppressor at that prop type. No tier-step or confidence rules until the signal is validated across two seasons.

**Scope:** `agents/backtest.py` only — add `--mode opp-team-hit-rate` mode. No production files touched until verdict confirmed. Run alongside H8 in late March — the two are complementary (H8 tests whether our defensive *input signal* is well-calibrated; H15 tests whether our defensive signal translates to actual *pick outcome* differences).

---

### H14 — Elite Opposing Rebounder REB Suppression
**Status: QUEUED — no new data collection required; all inputs in existing CSVs**
**ETA: ~late March / early April 2026**
**Mode: `--mode elite-opp-rebounder`**

**Hypothesis:** A player's REB tier hit rate is meaningfully suppressed when the opponent features (a) an elite individual rebounder at center — specifically a top-N season REB average — and/or (b) an elite team offensive rebounding unit, because the opposing center is implicitly tasked with boxing-out or otherwise contesting the elite rebounder, compressing their own counting stats.

**Motivating observation (March 11, 2026):** Alperen Sengun (9.0 avg REB, #11 league-wide) missed REB O6 with only 2 actual against Jokic and DEN despite a 10/10 recent hit rate, 80% confidence, and tough DvP. Post-game context: DEN won 129–93, HOU team REB distribution was spread across guards/wings (Tari Eason notable first-half boards), suggesting Sengun was occupied boxing out Jokic rather than collecting boards. Classified as `variance` by auditor, but domain reasoning suggests a structural mechanism worth testing.

**Two separable sub-hypotheses:**

1. **H14a — Individual Opposing Center Quality:** Does REB tier hit rate for a center/PF drop when the opposing center ranks in the top N by season REB average? Test at top-5, top-10, top-15 cutoffs. Primary position filter: apply only to C and PF (the positional boxing-out effect is direct; wings are less affected).

2. **H14b — Team Offensive Rebounding Rate:** Does REB tier hit rate drop when playing against a top-N offensive rebounding team? An elite OREB team generates more contested second-chance situations that change the rebounding geometry for the opposing big. This is independent of individual matchup — a team that crashes hard (OKC, IND, DEN historically) compresses opposing center REB totals even without one dominant individual rebounder. Test at top-5, top-10, top-15 cutoffs by team OREB rate.

**Why these are distinct:** H14a is about a single elite opponent rebounder demanding defensive attention. H14b is about the volume of offensive rebounding attempts requiring response. A team can have a high OREB rate without a single dominant rebounder (and vice versa). Both mechanisms could independently suppress opposing center REB totals; both should be tested separately.

**Data requirements:** All inputs already in existing CSVs.
- `player_game_log.csv` — per-game REB totals, player position, opponent
- `nba_master.csv` — game-level opponent pairing, season context
- `player_whitelist.csv` — position column for filtering to C/PF
- For H14b: team OREB data derivable from `team_game_log.csv` (offensive rebounds column, if present) or from per-player REB aggregation

**Key design decisions:**

- **Position filter:** Apply primarily to C and PF. Wing scorers (SG/SF) are not the primary boxing-out assignment and the mechanism is weaker for them. Run wing cut separately to confirm the effect is position-specific.
- **Opponent center identification:** Rank by season REB average among centers (use `player_whitelist.csv` positions + `player_game_log.csv` aggregates). For games where the opposing center is in the top-N, flag the game.
- **Tier hit rate metric:** Same methodology as existing backtests — compute tier hit rate for the target REB tier (best qualifying tier from `tier_hit_rates`) split by elite-opponent-present vs. not-present. Primary stat: lift = hit_rate_elite_opp / hit_rate_baseline.
- **Minimum sample gate:** Require ≥15 game observations per split before reporting a lift figure. Small-N splits are discarded.
- **DNP exclusion:** Standard — exclude `dnp == "1"` rows before any computation.

**Thresholds to test:**
- Individual opposing center: top-5, top-10, top-15 by season REB avg
- Team OREB: top-5, top-10, top-15 teams by season OREB rate
- Report lift at each threshold; look for consistent directional signal before setting a production cutoff

**Verdict criteria:**
- **Actionable signal:** Lift ≤ 0.85 (≥15% suppression) at top-10 individual or top-10 team OREB cutoff with ≥15 game sample → warrants an annotation in analyst context and possible tier-step rule
- **Weak signal:** Lift 0.86–0.94 → annotation only, no directive rule, monitor further
- **Noise:** Lift > 0.95 or inconsistent across cutoffs → close hypothesis, no action

**If signal confirmed:** Implementation path is quant-first / analyst-annotation-only (consistent with annotation vs. directive discipline). New `opp_rebounder_risk` field in `player_stats.json` (bool + label); annotation injected into per-player REB stat line similar to `[FG_COLD]`. Directive tier-step rule requires further validation before shipping. REB DvP exclusion already established — this signal is complementary, not redundant (it measures opposing rebounder quality, not team defensive rebounding tendency).

**Scope:** `agents/backtest.py` only — add `--mode elite-opp-rebounder` mode. No production files touched until verdict is confirmed.

---

**H16 — 3PA Volume Gate:** backtest implemented, pending first run. See ROADMAP_resolved.md.

**H17 — Spread Context vs. Tier Hit Rate:** FIRST RUN COMPLETE — March 13, 2026 (327 picks). Current binary split (≤6 vs >6) is NOISE — 1.2pp gap. No spread threshold produces a meaningful hit rate gap; best single threshold (10.5) yields only 4.8pp gap. Gradient sparse due to NBA half-point spread clustering. Verdict: insufficient signal — spread magnitude does not predict tier hit rate at current sample. Re-run at full-season completion to confirm noise verdict before closing. See ROADMAP_resolved.md.

---

## Improvement Proposals

### Current

---

### Completed

see 'docs/ROADMAP_resolved.md'

### Deferred

see 'docs/ROADMAP_Offseason.md'

## Implementation Notes

see 'docs/ROADMAP_resolved.md'

## Resolved Issues

see 'docs/ROADMAP_resolved.md'
