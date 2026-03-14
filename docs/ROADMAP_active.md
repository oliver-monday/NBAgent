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
**Status: FIRST RUN COMPLETE — rerun triggered at ≥400 graded picks (~Mar 20–25)**
**Mode: `--mode opp-team-hit-rate`**

First run (Mar 12, 279 picks): No suppressors cleared ±10pp/≥15 picks threshold. MIN×AST notable at −26.4pp (n=7). SAS floor compression (mean miss margin −6.0, n=3). Watch items added to `nba_season_context.md`. Full design in `docs/BACKTESTS.md`.

---

### H14 — Elite Opposing Rebounder REB Suppression
**Status: QUEUED — no new data required**
**Mode: `--mode elite-opp-rebounder` | ETA: ~late March / early April 2026**

Tests whether REB tier hit rate drops when opponent has elite individual rebounder (top-N season REB avg) or elite team OREB rate. Motivated by Sengun REB miss vs Jokic (Mar 11). Full design in `docs/BACKTESTS.md`.

---

### H16 — 3PA Volume Gate
**Status: IMPLEMENTED — verdict pending. Re-run at ~150+ 3PM picks.**
**Mode: `--mode 3pa-volume-gate`** | Full results in `docs/BACKTESTS.md`.

### H17 — Spread Context vs. Tier Hit Rate
**Status: FIRST RUN COMPLETE — NOISE verdict (Mar 13, 327 picks). Re-run at ≥500 picks.**
**Mode: `--mode spread-context`** | Full results in `docs/BACKTESTS.md`.

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
