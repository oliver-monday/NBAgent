# NBAgent — Roadmap - Active

Updated: 2026-04-22
Swept against ROADMAP_resolved.md — all items shipped through 2026-04-22 verified.

---

## Open Items

### Operational
- **Whitelist maintenance** — non-playoff teams deactivated (4/12–13). Reactivate if play-in surprises alter bracket after Apr 17 finals.
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **DST reversal (November 2026)** — all UTC offsets in `injuries.yml` and `odds_pretip.yml` must be incremented by 1 when clocks fall back (PDT → PST, UTC-7 → UTC-8). Add to October re-enable checklist.
- ✅ **Node.js 20→24 migration (4/12):** `checkout@v4→@v6`, `setup-python@v5→@v6` across all 8 workflows.

### Odds Integration
**Multi-phase implementation. All phases through Layer 3 complete. Phase 2 offseason.**

**Current architecture (as of 2026-04-16):**
- `analyst.yml` runs: `--prefetch` (before analyst) writes `odds_available.json`, `main()` (after analyst) matches picks to FanDuel odds and writes `market_implied_prob`, `edge_pct`, `bet_recommendation` to `picks.json`. Per-player calibration from H29 data wired into `_get_calibrated_prob()` (4/12).
- `odds_pretip.yml` runs: hourly from noon–7 PM PT. Closing-line re-fetch architecture (4/11) re-fetches games when closer to tip by ≥30min. Tip-off guard (4/11) prevents post-tip odds from contaminating CLV.
- `odds.yml`: manual-trigger only, for ad-hoc re-fetches
- `auditor.py`: computes per-pick CLV, aggregates `clv_summary`. Playoff calibration early warning (4/12) fires when ≥15 graded playoff picks exist and any confidence band diverges ≥10pp from regular-season baseline.
- Paid tier ($30/month, 20k credits) active — no credit budget constraints

**Completed phases:** Phase 1 (3/31), Phase 1.5 prefetch + market gate (4/7), Phase 1.75 calibration-corrected edge (4/7), Phase 1.8 parlay edge awareness (4/7), Phase 1.9 frontend odds display (4/7), alt-tier edge display (4/9), pre-tip sweep Layer 1 (4/9), CLV tracking Layer 2 (4/9), ✅ Layer 3 line movement indicators (4/11), ✅ P1.1 per-player calibration wiring H29→odds (4/12), ✅ P1.5 playoff calibration early warning (4/12), ✅ pretip closing-line re-fetch + tip-off guard (4/11).

**Phase 2 — Decision support UI (offseason):** "Market disagrees" flag, Kelly sizing display, edge tracking dashboard, value-first picking. Extends Phase 1.9 display with contextual warnings.

**Platform note:** Primary execution on Kalshi (CA-legal prediction market). Odds ingest pulls from OddsAPI (FanDuel as bookmaker); execution remains manual.

### Technical Debt
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. Intentional (ensures freshness) but adds ~10s to runtime. Low priority.

### Frontend
- ✅ **Layer 3 — Line movement indicators** (shipped 2026-04-11).
- ✅ **Frontend HTML-escape fix** (shipped 2026-04-15) — `escapeHtml()` helper wraps all analyst free-text injection sites.
- **Parlays tab historical stats banner** — hidden until graded parlay history exists. Evaluate whether to add a rolling chart once data accumulates.
- **Mobile layout** — current pick cards are readable but not optimized for small screens. Low priority.
- **"Stay Away?" UI caution flag** — informational badge when 2+ risk signals co-occur. Deferred to offseason.

---

## Active Queue — In Priority Order

### P1 — Playoffs Transition
**Status: ✅ ALL P1 ITEMS SHIPPED.** Play-in complete (Apr 14–15). R1 starts Apr 18. System is playoff-ready.

**Completed playoff prep (4/7–4/16):**
- ✅ Playoff context block — date-gated `## PLAYOFF CONTEXT` (4/9)
- ✅ Playoff Matchup Agent (`playoff_matchup.py`) — live, game-in-series tracking (4/7, enriched 4/12)
- ✅ Whitelist expanded to ~67 active players (4/7), non-playoff teams deactivated (4/12)
- ✅ Pre-tip odds sweep Layer 1 + CLV tracking Layer 2 (4/9)
- ✅ Standings rank bug fixed (4/7)
- ✅ H2H splits — annotation-only, closes H9 (4/9)
- ✅ ESPN Playoff Career Backfill — 20,139 rows for 65 players (4/9)
- ✅ Player name normalization fix — KAT/SGA/Fox/NAW/Jabari (4/9)
- ✅ Playoff career splits quant integration — `compute_playoff_splits()` (4/9)
- ✅ Daily ingest `season_type` + playoff dual-write (4/10)
- ✅ Frontend Playoff Career Profiles + Playoff Game Explorer (4/10)
- ✅ Scout token budget 4096→12288 + undersize fallback (4/10)
- ✅ Playoff Player Adjustments block — H27-H32 synthesis, date-gated R1 (4/11)
- ✅ Skip Re-evaluation on Star Absence — H26 Part 2, downstream loop closed (4/11)
- ✅ Analyst Star-Absence Uplift Annotation — H26 Part 1 (4/11)
- ✅ Skip Rule Refinements — 4 prompt edits: elite T25 exemption, co-primary gate, 3PM T1 iron_floor, monolithic alignment (4/11)
- ✅ Parlay Track 1: Variety + Bold Card (4/12)
- ✅ Parlay Builder UI + Spec 3 Cannib Badges (4/12)
- ✅ P1.1 Per-player calibration wiring H29→odds (4/12)
- ✅ P1.2 Playoff blowout rule relaxation — thresholds +3, penalty -10%→-5% (4/12)
- ✅ P1.4 Game-in-series confidence modifier — H31 activation at G5+ (4/12)
- ✅ P1.5 Playoff calibration early warning — fires at 15+ graded playoff picks (4/12)
- ✅ P2.3 Same-game parlay variance penalty (4/12)
- ✅ Injury Profiles agent — simplified data provider (4/13)
- ✅ Playoff injury landscape + player adjustments refinement (4/13)
- ✅ Pre-series intel for 4 locked R1 matchups (4/13)
- ✅ Playoff Rule Modifications — 3 directive overrides: min_floor suspension, VOLATILE -5%→-3%, momentum informational only (4/15). Override 1 extended to also suspend mandatory step-down (4/16).
- ✅ Rotowire projected minutes auth fix — `email` field, full team coverage (4/15)
- ✅ AST iron-floor role-purity gatecheck — soft_floor for non-playmakers (4/16)
- ✅ Standings injection paused during playoffs (4/16)
- ✅ ESPN athlete news removal from both reporters — endpoint 100% failing (4/16)
- ✅ Play-in results + R1 matchups updated in `nba_season_context.md` (4/16)
- ✅ Remaining gap items (4/12–13) all completed: playoff_bracket.json, season context updates, whitelist maintenance, verification runs

**Monitor during R1:**
- Update PLAYOFF INJURY LANDSCAPE in `nba_season_context.md` as injury statuses change
- Review analyst reasoning quality after first playoff week — are H27-H32 adjustments improving picks?
- W13 skip rule refinements — monitor FSR over next 20–30 picks (review ~4/21)
- Season context update — Apr 21 G2 results (BOS-PHI, OKC-PHX, DET-ORL, SAS-POR, LAL-HOU) needed after games complete
- Season context auto-updater — monitor diary entry quality through R1. If entries are consistently thin or miss pattern observations, consider switching to Opus or adding a review step.
- Monitor injury_event auto-void — confirm next in-game injury exit is correctly voided in picks.json + frontend (auditor.py promote_injury_event_voids).
- Skip recalibration monitoring — track false skip rate through R1 G3-G4. Target: FSR below 60% (down from 91.7%). If FSR remains above 70%, consider further floor reductions. If actual hit rate on newly-admitted picks drops below 80%, revert.
- **Parlay menu builder monitoring (shipped 2026-04-22)** — monitor hit rates per bucket (Value / Standard / Reach) through R1. Compare to pre-rewrite LLM-era 59.8% baseline. Targets: Value bucket >65%, Standard >45%, Reach >25%. A randomly-constructed 2-leg parlay from the pick pool hits ~73%, so Value should converge upward as the combinatorial builder has no narrative bias. If any bucket underperforms its target after 15+ graded cards, investigate whether game-independence ranking bonus is weighted correctly or if the combined_market_prob range for that bucket needs adjustment.
- **DET secondary creator AST caution (WATCH, shipped 2026-04-23)** — monitor Thompson AST T2 through G3-G4. If misses again (3rd consecutive), upgrade to practical confirmed rule. If clears, demote annotation. Scope: DET non-primary playmakers only (raw_avgs AST < 4.0) — Cunningham unaffected.
- **Parlay tier calibration dashboard (Audit Log tab, followup)** — surface per-tier (Safe / Reach / Degen) hit rate vs market-implied probability range to validate the menu agent's calibration per bucket. Wait until ≥10 graded cards per tier before rendering. Replaces the legacy aggregate parlay hit-rate banner removed 2026-04-23.
- **Cannibalization/synergy scoring in auto parlay agent (followup)** — H33 pair signals are currently surfaced only as UI badges between consecutive same-team same-stat legs in the rendered cards; they are NOT used in `parlay.py` `rank_score()`. Research indicates they should apply as a mild rank_score bonus (synergy) / penalty (cannibalization). Revisit after ≥15 graded cards across buckets to quantify impact.

**Known playoff transfer risks:**
- H15 suppressors (HOU, PHI, LAL): measured against full-season schedule. Fixed matchups in playoffs may concentrate or invert signal.
- Pace/blowout profiles: playoff games are lower-scoring; blowout frequency drops. System's blowout rules were calibrated on regular season rates.
- B2B context: irrelevant in playoffs (2–4 days between games). Treat as noise.
- Rotation tightening: 8-man playoff rotations — whitelist players with lineup-dependent roles are higher risk.

---

### Matchup Signals Queue

Design philosophy: the Analyst already has a solid quantitative matchup foundation (positional DvP, vs_soft/vs_tough splits, game pace, spread context). The following proposals address gaps where rolling averages give a misleading picture because something material has changed.

### F1 — Personal Foul Tracking + Foul-Prone Player Profiles
**Status: FUTURE — data pipeline expansion required**
**Priority: LOW — offseason**

Track personal fouls (PF) per game in `player_game_log.csv` and surface foul-prone patterns in Player Profiles. Requires schema expansion in `espn_player_ingest.py`, backfill, and new quant function. The min_floor guardrail already partially mitigates the downstream effect.

---

### Watch-and-Accumulate Items

#### W1 — Confidence Band Calibration
**Status: WATCH — offseason analysis target**

Season data shows all bands outperforming stated confidence (70–75% → 84.9%, 76–80% → 87.5%). The 76–80% band carries ~43% of all picks and has a +9.5pp gap. Per-player calibration (H29) now wired into the odds layer (P1.1, 4/12). Offseason: evaluate whether stacking penalties should be capped.

#### W2 — REB Opponent-Adjusted Floor
**Status: WATCH — needs more model_gap REB misses to justify quant work**

REB has the worst miss profile of any prop type. Do not act until pattern holds through playoffs.

#### W3 — CLE Switching Scheme / DvP Aggregate Mismatch
**Status: WATCH — single-team signal**

CLE scheme note in `nba_season_context.md`. Generalize only if similar misses appear for other switching teams. CLE plays TOR in R1.

#### W4 — FG_COLD Tier-Step Revisit
**Status: CLOSED (2026-04-11) — insufficient evidence through full regular season.**

#### W5 — Skip Validation
**Status: WATCH — 75% season-wide FSR. Offseason overhaul priority #1.**

Skip rules collectively produce a 75% false skip rate. Four refinements shipped 4/11 (see W13). Full skip rule redesign remains top offseason priority.

#### W6 — 3PM VOLATILE × iron_floor
**Status: CLOSED (4/9) — trim picks hit at 92.9% vs 89.0% for keep. Anti-predictive signal.**

#### W8 — 76–80% Confidence Fragility Band
**Status: OPEN — monitor through playoffs**

If this band underperforms during playoffs, it would be the first sign of calibration drift. Track per-round.

#### W9 — Post-Game Reporter False Positives
**Status: CLOSED (2026-04-12) — zero false positives since 4/8 LLM redesign.**

#### W10 — ESPN Athlete News API
**Status: CLOSED (2026-04-16) — endpoint removed from both reporters. `common/v3/athletes/{id}/news` had 100% failure rate. Code fully stripped from `post_game_reporter.py` and `pre_game_reporter.py`. League-wide news (`site/v2`) retained in pre-game reporter. Re-enable if ESPN restores the endpoint.**

#### W13 — Skip Rule Refinements
**Status: OPEN — monitor in production (opened 2026-04-11)**

Four prompt refinements shipped 4/11: blowout_t25 elite exemption, secondary scorer T10 + co-primary gate, 3PM T1 iron_floor exception, monolithic 3PM blowout alignment. Monitor FSR — review ~2026-04-21.

#### W12 — DET Defensive Scheme Impact on AST/PTS Props
**Status: OPEN — R1 context updated (4/16)**

DET is the #1 seed East, plays winner of ORL vs CHA (determined Apr 17). DET×AST at 50.0% (n=8) — below formal gate but extreme magnitude. Monitor through R1. Cross-reference H15 suppressors against actual matchups.

---

### Completed Backtests (summary — full findings in `docs/BACKTESTS.md`)

#### H9 — Player × Opponent H2H Splits
**Status: CLOSED (4/9) — deployed as annotation-only `h2h_splits` in quant + analyst. No directive rules.**

#### H15 — Opponent Team Pick Suppression / Lift
**Status: FOURTH RUN COMPLETE (4/12, 815 picks) — stable. CLOSED for regular season.**
Suppressors: HOU (65.2%), PHI (65.0%), LAL (76.5%). PHX dropped (82.3%, regressed). Amplifier: IND (100%, n=38). MIN×AST confirmed (75.0%, n=16). DET×AST watch (50.0%, n=8). Notes in `nba_season_context.md`.

#### H16 — 3PA Volume Gate
**Status: CLOSED (4/12, NOISE) — insufficient low-volume data. System already self-selects high-volume shooters.**

#### H24 — Market Disagreement Gate
**Status: INSUFFICIENT DATA (4/12) — rerun post-playoffs at 200+ odds-enriched picks.**
Zero picks in `market_much_lower` bucket. System's under-confidence means market almost always agrees MORE.

#### H25 — Trim Escalation Signal
**Status: CLOSED (4/12, PARADOX CONFIRMED) — trim picks hit at 92.4% vs keep 88.5%. Anti-predictive.**

#### H26 — Star Absence Teammate Impact
**Status: CONFIRMED SIGNAL + FULLY INTEGRATED (4/10–4/11)**
PTS T15-T25 +11–13pp weighted lift, AST T4 +10pp. Deployed: `star_absence_lift` in quant (Part 1), skip re-evaluation in lineup_update (Part 2), H33 cannibalization mechanism (Spec 1). Per-player direction varies — PERSONAL_DRAG_WARNING guard prevents Jalen Green class of misses. Multi-season verification deferred to offseason.

#### H27 — Primary Scorer Blowout PTS Performance
**Status: MIXED verdict, action deferred (4/11)**
Primary scorers at spread_abs ≥ 15 hit T25 at 58.8% (MARGINAL, above 50.6% baseline). GAME_SCRIPT_DEPENDENT: actual blowouts 45.7% vs competitive 73.7% (+28pp delta). Jokic hypothesis not confirmed (n=1). Offseason: consider replacing hard skip with -5pp cap.

#### H28 — Playoff Career Tier Performance
**Status: COMPLETE + INTEGRATED into `build_playoff_adjustments()` (4/11)**
58 players qualified. Per-player ELEVATOR/STABLE/SUPPRESSOR flags. Population deltas small — signal is entirely per-player. Synthesized with H29-H32 into per-player playoff guidance, date-gated to R1. Full data in `data/backtest_playoff_career.json`.

#### H29 — Player-Level Confidence Calibration
**Status: COMPLETE + INTEGRATED into odds layer (P1.1, 4/12)**
31 qualified players. 2 OVER_CONFIDENT (Ingram, Mitchell), 18 UNDER_CONFIDENT, 11 WELL_CALIBRATED. Per-player actual hit rates now feed `_get_calibrated_prob()` in `odds_today.py` — directly improves Kelly sizing. Deferred: analyst-prompt confidence floors/caps per player.

#### H30 — Minutes Elasticity
**Status: COMPLETE + INTEGRATED into `build_playoff_adjustments()` (4/11)**
Population elasticity massive: PTS T20 +26pp, T25 +29pp at 38+ min. 23 MINUTES_SCALERS identified. 2 MINUTES_INVERTERS (Mitchell, LeBron — small samples). Deferred: per-player playoff confidence bumps from `extended_key_rates`.

#### H31 — Playoff Series Progression
**Status: COMPLETE + INTEGRATED via `build_series_progression_rules()` (P1.4, 4/12)**
11 LATE_RISER, 18 STABLE, 11 LATE_FADER. Top fader: Harden −33pp. Game-in-series modifier activates at G5+ (PTS only, -5% FADER / +3% RISER). Deferred: three-layer composition with H28+H30 for a full playoff confidence model.

#### H32 — Player Consistency Index
**Status: COMPLETE + INTEGRATED into `build_playoff_adjustments()` (4/11)**
Zero ALL_WEATHER players. REST is dominant vulnerability dimension (59%). Worst vulnerabilities inform per-player playoff context. Deferred: per-player slate-position-aware confidence adjustment from `worst_vulnerability`.

#### H33 — Teammate Scoring Cannibalization
**Status: COMPLETE + INTEGRATED into parlay agent + auditor + quant + lineup_update (4/11)**
68 PTS pairs, 58 AST pairs across 14 teams. STRONG pairs blocked in parlay candidates, MODERATE penalized, SYNERGY boosted. Cannibalization badges on frontend. Skip reconsideration Path C (−15pp threshold). Note: SAS/NYK/GSW missing from backtest due to `backtest.py` whitelist loader not emitting `team_abbr_alt` tuples — separate fix needed.

---

## Untested Hypotheses
(none active — all closed or integrated)

---

## Improvement Proposals

### Current
(none active — all current work is playoff operations)

### Completed
see `docs/ROADMAP_resolved.md`

### Deferred
see `docs/ROADMAP_Offseason.md`

## Implementation Notes
see `docs/ROADMAP_resolved.md`

## Resolved Issues
see `docs/ROADMAP_resolved.md`
