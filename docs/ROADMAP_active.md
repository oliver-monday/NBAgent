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

#### W5 — Skip Validation Monitoring
**Status: WATCH — ongoing**

`ast_hard_gate` Jokic false skip addressed — elite playmaker exemption (≥8.0 APG) added to prompt 2026-03-15; monitoring continues for non-elite-playmaker frontcourt cases. `reb_floor_skip` T4 false skip cluster (100% false skip rate at T4) addressed — T4 exemption added to prompt 2026-03-15; monitoring continues for pick_value ≥ 6 cases. `workflow_gap` miss class addressed — `filter_self_skip_picks()` Python gate added 2026-03-15. **Floor gate enforcement gap closed 2026-03-16** — 4 floor gate failure patterns added to `filter_self_skip_picks()` SKIP_CONCLUSIONS; prototype: Thompson REB T4 floor gate SKIP filed at 78% after lineup amendment override. Accumulate skip validation data; revisit remaining rules at ≥200 total graded skips.

**Post-Game Reporter injury exit detection: fixed 2026-03-18.** Monitor next 2–3 low-minutes events to confirm `injury_exit` classification fires correctly for both the `_INJURY_EXIT_TERMS` direct path and the `minutes_restriction` → `injury_exit` promotion path. Close this watch item once two confirmed in-game exits are correctly classified in production.


### Pending Backtests

### H15 — Opponent Team Pick Suppression / Lift
**Status: SECOND RUN COMPLETE (Mar 22, 538 picks) — HOU confirmed suppressor; nba_season_context.md updated**
**Mode: `--mode opp-team-hit-rate`**

Second run (Mar 22, 538 picks): **HOU confirmed system-wide suppressor** — 61.9% (n=21, −23.4pp). HOU PTS 63.6% (n=11), HOU AST 62.5% (n=8). MIN×AST deepened to 55.6% (n=9, −29.5pp) — below formal threshold but upgraded to active scrutiny. SAS floor compression strengthened (n=6, mean −5.0). All three notes updated in `nba_season_context.md`. Full results in `docs/BACKTESTS.md`. Re-run at end of season (≥600 picks) to check if any additional teams clear the suppressor gate.

---

### H14 — Elite Opposing Rebounder REB Suppression
**Status: COMPLETE — NO_SIGNAL verdict (Mar 22, 2026)**
**Mode: `--mode elite-opp-rebounder`** | Full results in `docs/BACKTESTS.md`.

NO_SIGNAL at all three thresholds (8/10/12 REB/g). thresh=10.0: elite_present 70.3% vs no_elite 69.8% (delta=−0.5pp). H14b team REB flat. No rule change. Sengun vs. Jokic (Mar 11) was variance.

---

### H16 — 3PA Volume Gate
**Status: IMPLEMENTED — verdict pending. Re-run at ~150+ 3PM picks.**
**Mode: `--mode 3pa-volume-gate`** | Full results in `docs/BACKTESTS.md`.

---

### H18 — Wembanyama Rim Deterrent Effect
**Status: DESIGNED — research phase first, backtest pending data dependency check**
**ETA: late March / early April 2026**

Hypothesis: Wemby suppresses inside-the-arc scorers specifically (drive/mid-range-heavy), not perimeter-first players — making the existing SAS watch item too broad. Motivated by Miller 2-14 FG vs SAS (March 14) while Ball/Knueppel/Bridges were unaffected. Research phase: manually check current SAS miss set for 2PA vs 3PA clustering before writing backtest code. Data dependency: confirm `tpa` and `fga` columns exist in `player_game_log.csv`; schema expansion required if absent. Full design in `docs/h18_wemby_rim_deterrent.md`.

---

### H19 — In-Game Blowout Regime
**Status: COMPLETE — MIXED verdict (Mar 22, 2026)**
**Mode: `--mode blowout-regime`** | Full results in `docs/BACKTESTS.md`.

Tests tier hit rates for primary vs. secondary scorers in actual blowout games (final margin ≥ 15) on both the winning (favored) and losing (underdog) sides. Minutes gate ≥ 24 min excludes garbage-time. Key finding: favored-side secondary scorers NOT suppressed (PTS lift=1.083); underdog-side AST secondary COLLAPSE (lift=0.713, n=59). Existing BLOWOUT_RISK rule unchanged. Underdog AST collapse flagged for future annotation-only rule.

---

### H20 — Losing-Side Blowout AST Suppression
**Status: COMPLETE — NO_SIGNAL verdict (Mar 22, 2026)**
**Mode: `--mode losing-side-ast`** | Full results in `docs/BACKTESTS.md`.

Tests whether pre-game underdog spread_abs ≥ 10 suppresses AST tier hit rate. Result: underdog_10plus hit rate 75.9% vs baseline 74.1% (lift=1.024, n=54) — directionally opposite to suppression hypothesis. Rule NOT shipped. Motivated by Jalen Johnson AST miss (2026-03-21) in LAL blowout win. Full design and results in `docs/BACKTESTS.md`.

---

### H21 — Miss Anatomy: Near-Miss vs. Blowup Next-Game Prediction
**Status: COMPLETE — NOISE verdict (Mar 22, 2026)**
**Mode: `--mode miss-anatomy`** | Full results in `docs/BACKTESTS.md`.

PTS delta 0.6pp, REB delta 2.0pp, AST delta 0.8pp — all below the 4pp noise threshold. Rule NOT shipped. `near_miss_rate`/`blowup_rate` fields remain in `player_stats.json` for Player Profiles only.

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
