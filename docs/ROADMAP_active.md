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
**Two-phase implementation. Phase 1 IMPLEMENTED (2026-03-31); Phase 2 is offseason.**

**Phase 1 — Data collection: ✅ IMPLEMENTED (2026-03-31).** `ingest/odds_today.py` + `.github/workflows/odds.yml`. Fetches FanDuel NBA player prop lines from The Odds API after each analyst run (chains off `Analyst Agent` workflow; also manually triggerable). Annotates today's picks in `picks.json` with `market_line`, `market_implied_prob`, `market_book`, `edge_pct`, `odds_fetched_at`. Writes diagnostic cache to `data/odds_today.json` (overwritten each run). FanDuel only, exact line matching (`pick_value − 0.5`), ~4 credits/game/day. Required secret: `ODDS_API_KEY`. Goal: accumulate odds-tagged pick history through the playoffs so offseason analysis can answer "were our highest-edge picks actually our best picks?" Four weeks of tagged data by season end is the minimum useful sample. **Future enhancement:** chain off `injuries.yml` for intraday refresh when significant lineup changes detected (not yet implemented — standalone workflow confirmed working first).

**Phase 2 — Decision support UI (offseason / next season):** Kelly sizing display on pick cards (bet X% of bankroll), edge highlighting (system confidence vs. market implied), "market disagrees" flag when market implied prob is >10pp above system confidence. The three numbers surfaced per pick: market implied probability (prop line → percentage), edge (system confidence − implied), Kelly fraction (edge / odds → recommended bet size as % of bankroll). Output is a single actionable number per pick — no statistics background required to use it.

**Platform note:** Primary execution on Kalshi (CA-legal prediction market, mirrors major books). Kalshi has no official API and displays round payout estimates rather than precise vig-adjusted lines. Odds ingest pulls from aggregator (not Kalshi directly) for analytical precision; execution remains manual. Kelly sizing math is still valid even if Kalshi rounds the displayed payout — size the bet correctly, execute at the closest available line.

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

### P1 — Playoffs Mode-Shift Preparation
Status: ACTIVE — regular season ends April 12, playoffs begin ~April 19
Priority: HIGH — time-sensitive, ~12 days of regular season remaining
Playoff basketball has structurally different properties than the regular season sample the system was built and tuned on. The established rules will transfer; the calibrated signal strengths may not. Preparation before the first-round tip-off reduces the risk of a rough opening week.
Known transfer risks:

H15 suppressors (HOU, PHX, PHI): These were measured against the full-season schedule. In playoffs, matchups are fixed for up to 7 games. If HOU or PHX are eliminated in R1, the suppressor notes are moot; if they advance, the signal may concentrate or invert based on the specific pairing. Revisit suppressor/amplifier notes in nba_season_context.md after R1 matchups are set.
Pace and blowout profiles: Playoff games are lower-scoring and more physical on average. Pace tags were calibrated on regular season team pace; playoff pace compresses. Blowout frequency drops sharply — the system's blowout rules were calibrated on a regular season blowout rate that won't hold in May.
Teammate correlations and role stability: Coaches make aggressive lineup adjustments between playoff games and series. Rotation players can disappear entirely (8-man playoff rotations). Whitelist players whose role depends on a specific lineup construction are higher risk.
Rest and schedule context: Regular season B2B rates are irrelevant in playoffs (2–4 days between games). The B2B penalty and hit rate data are inapplicable — treat B2B context as noise.

Preparation actions (before first-round tip-off):

Update nba_season_context.md once R1 matchups are confirmed (~April 13–15): add a PLAYOFFS section with the bracket, note which H15 suppressors/amplifiers remain relevant based on who survived, and flag any team facing a first-time opponent this season (H2H samples will be thin).
Audit whitelist for eliminated teams — players on lottery teams (NOP, UTA, CHA, SAS, etc.) won't be in the bracket; set active=0 before the first playoff analyst run to prevent stale quant data polluting context.
Watch the first week of R1 closely — treat it as a calibration check. If miss rate spikes vs. regular season baseline, the likely culprits are pace compression (PTS over-projecting), scheme adjustments (AST disrupted), and rotation instability (minutes floors unreliable). Tag these misses distinctly for post-R1 analysis.
Prioritize H9 (H2H splits) — in a 7-game series, a player's historical performance against that specific opponent is the most playoff-relevant signal the system can generate. Run H9 during R1 while R2 matchups are still being set.

What NOT to change pre-emptively: Do not modify quant computations, confidence rules, or skip thresholds before seeing playoff data. The system's rule set is well-calibrated; the risk is signal drift, not structural failure. Observe first, adjust second.

---

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


#### W6 — 3PM VOLATILE × iron_floor merit_below_floor false skip rate
**Status: WATCH — accumulate merit_below_floor skip data through end of season + playoffs**

The 75% 3PM confidence floor combined with VOLATILE -5% penalty routinely pushes VOLATILE-tagged 3PM picks with iron_floor below the selection threshold. Prior to the merit_below_floor rename (2026-03-25), these were mislabeled as 3pm_blowout_trend_down. Hypothesis: iron_floor protection on VOLATILE 3PM picks makes the -5% penalty overly conservative — the floor itself prevents catastrophic misses, so the confidence discount may be double-counting the risk. Population is thin in-season (~10–15 picks expected by season end); full analysis deferred to offseason pending Odds API integration (T1 3PM R/R at market odds is the key missing input before any floor adjustment is warranted). Do not act until offseason. Accumulate correctly-labeled skip records through playoffs.

### Pending Backtests

### H9 — Player × Opponent H2H Splits
**Status: QUEUED — data accumulating**
**Mode: `--mode h2h-splits`** | ETA: mid-April 2026 (near-complete season sample required)

Does a player's historical hit rate against today's specific opponent predict next-game performance better than the population-level opp_defense rating? Most opponents appear 2–4× per season — sample too thin until late April. Design in `docs/BACKTESTS.md`.

---

### H15 — Opponent Team Pick Suppression / Lift
**Status: THIRD RUN COMPLETE (Mar 31, ≥600 picks) — monitor MIN×AST through playoffs (n=11, need ≥15)**
**Mode: `--mode opp-team-hit-rate`**

Three suppressors confirmed: **HOU** (65.2%, n=23, −20.1pp), **PHX** (75.0%, n=24, −10.3pp), **PHI** (64.7%, n=17, −20.6pp; game-script/tanking caveat — see BACKTESTS.md). One amplifier confirmed: **IND** (100.0%, n=23, +14.7pp). MIN×AST at 63.6% (n=11) — active scrutiny, 4 more picks needed to clear ≥15 formal gate; season ends April 12. All notes updated in `nba_season_context.md`. Full results in `docs/BACKTESTS.md`.

---

### H16 — 3PA Volume Gate
**Status: IMPLEMENTED — verdict pending. Re-run at ~150+ 3PM picks (~April 1–3).**
**Mode: `--mode 3pa-volume-gate`** | Currently 99/150 graded 3PM picks (as of Mar 22). Full results in `docs/BACKTESTS.md`.

---

### Completed This Session (Mar 22, 2026)

All completed backtests logged in `docs/ROADMAP_resolved.md` and `docs/BACKTESTS.md`.

| Backtest | Verdict | Rule shipped? |
|----------|---------|--------------|
| H14 — Elite Opposing Rebounder | NO_SIGNAL (n=1,709, delta=−0.5pp at thresh=10) | No |
| H17 — Spread Context | NOISE (n=538, best threshold gap 3.6pp) | No — CLOSED |
| H18 — Wembanyama Rim Deterrent | NO_PATTERN (research phase — Miller classifies as perimeter, Q3 runs opposite direction) | No — CLOSED |
| H19 — In-Game Blowout Regime | MIXED — secondary scorer skip narrowed to spread_abs ≥ 15; 3PM blowout skip retired for spread_abs 8–18 | ✅ Two rules updated |
| H20 — Losing-Side Blowout AST | NO_SIGNAL (n=54, lift=1.024) | No |
| H21 — Miss Anatomy | NOISE (max delta 2.0pp, all below 4pp threshold) | No |

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
