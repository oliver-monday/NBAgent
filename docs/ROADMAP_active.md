# NBAgent — Roadmap - Active

Updated: 2026-04-09

---

## Open Items

### Operational
- **Whitelist maintenance** — deactivate non-playoff teams once seeds are set (April 12–13). East: MIL, CHI, BKN, IND, WAS. West: NOP, MEM, DAL, SAC, UTA. Reactivate if play-in surprises occur.
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **DST reversal (November 2026)** — all UTC offsets in `injuries.yml` and `odds_pretip.yml` must be incremented by 1 when clocks fall back (PDT → PST, UTC-7 → UTC-8). Add to October re-enable checklist.

### Odds Integration
**Multi-phase implementation. Phases 1–1.9 complete. Pre-tip sweep + CLV live. Phase 2 offseason.**

**Current architecture (as of 2026-04-09):**
- `analyst.yml` runs: `--prefetch` (before analyst) writes `odds_available.json`, `main()` (after analyst) matches picks to FanDuel odds and writes `market_implied_prob`, `edge_pct`, `bet_recommendation` to `picks.json`
- `odds_pretip.yml` runs: every 30 min 3–7:30 PM PT, game-time-aware sweep fetches odds ~60 min before tip, overwrites picks with latest prices, saves morning baseline to `odds_pretip.json`, logs line movement
- `odds.yml`: manual-trigger only, for ad-hoc re-fetches
- `auditor.py`: computes per-pick CLV (`clv_pp`) from `morning_implied_prob` vs `market_implied_prob`, aggregates `clv_summary` in `audit_summary.json`
- Paid tier ($30/month, 20k credits) planned for playoffs — eliminates credit budget constraints

**Completed phases:** Phase 1 data collection (3/31), Phase 1.5 prefetch + market gate (4/7), Phase 1.75 calibration-corrected edge (4/7), Phase 1.8 parlay edge awareness (4/7), Phase 1.9 frontend odds display (4/7), alt-tier edge display (4/9), pre-tip odds sweep Layer 1 (4/9), CLV tracking Layer 2 (4/9).

**Layer 3 — Frontend line movement indicators: SPECCED, not yet implemented.** Spec saved locally (`layer3_movement_indicators_spec.md`). Shows ↑/↓/→ arrows on pick cards based on morning-to-pretip line movement. Implement after confirming Layers 1+2 on 4/10 run. `build_site.py` only.

**Phase 2 — Decision support UI (offseason):** "Market disagrees" flag, Kelly sizing display, edge tracking dashboard, value-first picking. Extends Phase 1.9 display with contextual warnings.

**Platform note:** Primary execution on Kalshi (CA-legal prediction market). Kalshi has no official API and rounds payout displays. Odds ingest pulls from OddsAPI (FanDuel as bookmaker); execution remains manual.

### Technical Debt
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. Intentional (ensures freshness) but adds ~10s to runtime. Low priority.

### Frontend
- **Layer 3 — Line movement indicators** — specced (see Odds Integration above). Shows morning→pretip movement on pick cards. Implement after 4/10 verification of Layers 1+2.
- **Parlays tab historical stats banner** — hidden until graded parlay history exists. Evaluate whether to add a rolling chart once data accumulates.
- **Mobile layout** — current pick cards are readable but not optimized for small screens. Low priority.
- **"Stay Away?" UI caution flag** — informational badge when 2+ risk signals co-occur. Deferred to offseason — requires team momentum accumulation and signal threshold calibration.

---

## Active Queue — In Priority Order

### P1 — Playoffs Transition
Status: ACTIVE — 2 regular season game days remain (4/10, 4/11). Play-in: April 14–17. Playoffs R1: April 18.

**Completed playoff prep:**
- ✅ Playoff context block — date-gated `## PLAYOFF CONTEXT` section fires on/after 4/14. Annotation-only behavioral framing (tighter rotations, pace compression, series dynamics). Dispatched 4/9.
- ✅ Playoff Matchup Agent (`playoff_matchup.py`) — live, writes series-specific context from `playoff_bracket.json`. Inert until bracket populated.
- ✅ Whitelist expanded to ~67 active players for playoffs (4/7).
- ✅ Pre-tip odds sweep (Layer 1) — game-time-aware odds fetching live (4/9).
- ✅ CLV tracking (Layer 2) — per-pick CLV + season summary in audit (4/9).
- ✅ Standings rank bug in `espn_daily_ingest.py` fixed (4/7).

**Remaining gap items (April 12–13):**
- Create `data/playoff_bracket.json` — populate once seeds are final after 4/11 games
- Update `context/nba_season_context.md` — add PLAYOFFS section with bracket, revisit H15 suppressor notes for actual matchups
- Deactivate non-playoff teams on whitelist
- Verify 4/10 run: walked_tier emission, market gate, pre-game reporter fixes, pretip sweep, CLV computation
- Layer 3 frontend implementation (if Layers 1+2 verified clean)

**What NOT to change pre-emptively:** Do not modify quant computations, confidence rules, or skip thresholds before seeing playoff data. Observe first, adjust second.

**Known playoff transfer risks:**
- H15 suppressors (HOU, PHX, PHI): measured against full-season schedule. Fixed matchups in playoffs may concentrate or invert signal.
- Pace/blowout profiles: playoff games are lower-scoring; blowout frequency drops. System's blowout rules were calibrated on regular season rates.
- B2B context: irrelevant in playoffs (2–4 days between games). Treat as noise.
- Rotation tightening: 8-man playoff rotations — whitelist players with lineup-dependent roles are higher risk.

---

### Matchup Signals Queue

Design philosophy: the Analyst already has a solid quantitative matchup foundation (positional DvP, vs_soft/vs_tough splits, game pace, spread context). The following proposals address gaps where rolling averages give a misleading picture because something material has changed.

---

### F1 — Personal Foul Tracking + Foul-Prone Player Profiles
**Status: FUTURE — data pipeline expansion required**
**Priority: LOW — offseason**

Track personal fouls (PF) per game in `player_game_log.csv` and surface foul-prone patterns in Player Profiles. Requires schema expansion in `espn_player_ingest.py`, backfill, and new quant function. The min_floor guardrail already partially mitigates the downstream effect. Design documented in prior roadmap versions.

---

### Watch-and-Accumulate Items

#### W1 — Confidence Band Calibration
**Status: WATCH — offseason analysis target**

Season data (778 graded picks) shows all bands outperforming stated confidence: 70–75% → 84.9% actual, 76–80% → 87.5%, 81–85% → 88.3%, 86+ → 94.1%. The 76–80% band carries ~43% of all picks and has a +9.5pp gap — the largest sustained delta. Hypothesis: VOLATILE (-5%) and BLOWOUT_RISK (-5%) penalties stack and push picks into this band where they dramatically outperform. Do not adjust penalty mechanics in-season. Offseason priority: evaluate whether stacking penalties should be capped.

#### W2 — REB Opponent-Adjusted Floor
**Status: WATCH — needs more model_gap REB misses to justify quant work**

REB has the worst miss profile of any prop type. Root cause: raw L10 floor overstates expected output when opponent's defensive scheme suppresses rebounding. Conceptual fix: opponent-adjusted floor gate. Do not act until pattern holds through playoffs.

#### W3 — CLE Switching Scheme / DvP Aggregate Mismatch
**Status: WATCH — single-team signal**

CLE's aggregate 3PM DvP rates as "soft" but their switching scheme neutralizes perimeter looks. Architectural limitation of team-level DvP. CLE scheme note added to `nba_season_context.md`. Generalize only if similar misses appear for other switching teams.

#### W4 — FG_COLD Tier-Step Revisit
**Status: WATCH — insufficient instances**

Question: should FG_COLD ≥ -15% trigger a hard tier step-down on PTS picks? H10 evaluated confidence adjustments (verdict: noise), not tier step-downs — distinct mechanisms. Do not act until 3–5 additional FG_COLD ≥ -15% PTS misses accumulate.

#### W5 — Skip Validation
**Status: WATCH — 75% season-wide FSR. Offseason overhaul priority #1.**

Skip rules collectively produce a 75% false skip rate. `ast_hard_gate` and `reb_floor_skip` have been partially addressed with exemptions. Full skip rule redesign is the top offseason priority.

#### W6 — 3PM VOLATILE × iron_floor
**Status: CLOSED — addressed by trim badge removal context (4/9)**

Trim picks (including VOLATILE 3PM with iron_floor) hit at 92.9% vs 89.0% for keep picks. The ⚠ Caution badge was removed as it was flagging the system's safest picks. Review agent still runs for offline analysis.

#### W8 — 76–80% Confidence Fragility Band
**Status: OPEN — monitor through playoffs**

The 76–80% band carries the most picks and has the highest overperformance gap. If this band starts underperforming during playoffs (different game dynamics), it would be the first sign of calibration drift. Track per-round.

#### W9 — Post-Game Reporter False Positives
**Status: OPEN — monitor with LLM classification (redesigned 4/8)**

Post-game reporter was redesigned from deterministic phrase-matching to Claude LLM classification on 4/8. Monitor for false positive injury exit classifications.

#### W10 — ESPN Athlete News API
**Status: OPEN — monitor with split logging (4/9)**

Pre-game reporter showed 24/24 ESPN fetch errors on 4/9. Error logging split into `no_id_count` vs `http_fail_count` (dispatched 4/9) to diagnose whether this is missing athlete IDs or ESPN API failures.

---

### Pending Backtests

### H9 — Player × Opponent H2H Splits
**Status: QUEUED — run during R1 playoffs (mid-April)**
**Mode: `--mode h2h-splits`**

Does a player's historical hit rate against today's specific opponent predict next-game performance better than population-level opp_defense? Most opponents appear 2–4× per season. Full season sample available after 4/11. In a 7-game series, H2H signal is the most playoff-relevant signal the system can generate. Priority for R1.

---

### H15 — Opponent Team Pick Suppression / Lift
**Status: THIRD RUN COMPLETE (Mar 31, ≥600 picks) — stable**
**Mode: `--mode opp-team-hit-rate`**

Three suppressors: HOU (65.2%, n=23), PHX (75.0%, n=24), PHI (64.7%, n=17). One amplifier: IND (100.0%, n=23). MIN×AST at 63.6% (n=11) — needs ≥15 for formal gate, unlikely to reach before season end. All notes in `nba_season_context.md`. Fourth run optional — sample has grown to 778+ picks but suppressor team samples are unlikely to have grown proportionally. Revisit post-R1 if suppressors appear in playoff matchups.

---

### H16 — 3PA Volume Gate
**Status: IMPLEMENTED — verdict pending**
**Mode: `--mode 3pa-volume-gate`**

Was 99/150 graded 3PM picks as of Mar 22. Check current count — may have reached threshold for rerun. If not, defer to offseason.

---

## Untested Hypotheses
- **H9 — Player × Opponent H2H Splits** — see Pending Backtests above.

---

## Improvement Proposals

### Current
(none active — all current work is playoff prep or odds integration)

### Completed
see `docs/ROADMAP_resolved.md`

### Deferred
see `docs/ROADMAP_Offseason.md`

## Implementation Notes
see `docs/ROADMAP_resolved.md`

## Resolved Issues
see `docs/ROADMAP_resolved.md`
