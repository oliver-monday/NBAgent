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

**W8 — Kalshi P1 first production run** — Verify `ingest/kalshi_today.py` writes the new `kalshi_*` fields correctly on the first slate where `analyst.yml` actually fires after P1 landed (2026-05-01). Confirm: all four series fetched (KXNBAPTS/REB/AST/3PT), player-name normalization works on first slate (Karl-Anthony Towns / De'Aaron Fox / Shai Gilgeous-Alexander all match), no schema drift (each pickable today's pick has `kalshi_market_listed` set; matched picks have full nine-field set; unmatched picks have only `kalshi_market_listed: false` with no leakage of other `kalshi_*` fields). Spot-check a few `kalshi_market_implied_prob` values against fresh Kalshi UI to confirm the convention conversion (`yes_bid_dollars * 100` → percent) is correct.

**W9 — Kalshi coverage rate** — Track % of today's pickable picks with `kalshi_market_listed: true` over the first 5 slates after P1. Below 50% on any slate triggers data-problem investigation (likely candidates: ticker-encoding drift, slate-date format change, player-name normalization edge case). Over 80% is healthy and supports queuing P2/P3. Compare per-slate to the v2 reprobe's 100% floor-tier coverage on the May 1 slate (which used hardcoded matchup tickers; W9 now uses team/opponent pairs from picks).

**P2 (Kalshi frontend display)** — Deferred. Side-by-side Kalshi vs FanDuel implied probability line on pick cards in `agents/build_site.py`. Renders only when `kalshi_market_listed: true`; shows nothing otherwise. Will need a small visual treatment (green when Kalshi agrees with FanDuel within 2pp, amber when they disagree by ≥5pp, etc. — to be designed in P2 prompt). Settlement-rule footnote: Kalshi `last_fair_price` vs FanDuel void on DNP-active scratches.

**P3 (Kalshi disagreement backtest)** — Deferred until 5+ slates of Kalshi data have accumulated (target ≥2026-05-06). New `--mode kalshi-disagreement` in `agents/backtest.py`. Hypothesis: when Kalshi and FanDuel disagree on implied prob by ≥5pp going into tip, the side with higher implied prob is more accurate (i.e., the disagreement is signal, not noise). Filter to `clv_pp` field present + `kalshi_morning_implied_prob` present + `kalshi_market_listed: true`. Compute hit-rate split: agreement vs Kalshi-higher vs FanDuel-higher. Output `data/backtest_kalshi_disagreement.json` + console table. Descriptive only — rule design is a separate downstream prompt.

**H34 Prompt C — CLV warning activation** — Wait until at least **2026-05-07** (7+ pretip cycles' worth of warned picks accumulated) before deciding. Decision criteria: count warned AST picks (those with `clv_warning` set at any point that day per audit_log) and their actual hit rate. If the warned-pick hit rate confirms <70% on n≥15 warned picks, ship the activation prompt: flip `applied: true` in the warning sub-object, apply the proposed -5pp penalty to `confidence_pct` at warning-fire time. If hit rate is ≥75% or sample is too small, hold and re-evaluate at n≥30. **Activation must be implemented at `lineup_update.py` time, NOT `analyst.py`** (analyst runs before pretip data exists). H34 Prompt A (observability detection) shipped 2026-04-30 — every pretip cycle now scans today's AST picks for `live_clv_pp < -0.5` and writes `clv_warning` sub-objects with `applied: false`. Sister Prompt B (frontend badge) is a separate session.

**H34 rule design — AST × lost_close → confidence penalty** — Backtest landed 2026-04-30 (`--mode clv-ast-disagree` in `agents/backtest.py`, output `data/backtest_clv_ast_disagree.json`). Verdict MEANINGFUL_DEGRADATION: AST × lost_close 62.5% on n=32 vs AST baseline 77.0% on n=113 (-14.5pp delta). Stable across date halves (62.5% / 62.5%) and recent 14d (60.7%, n=28). Pattern holds at T2 and T4 with similar magnitude. Cross-prop reference confirms AST-specific signal (PTS/REB/3PM × lost_close show no comparable degradation). Borderline sample size n=32. Decide whether to (a) ship a soft rule now (e.g. -7% confidence on AST × lost_close, likely pushes 70-72% picks below skip floor); (b) wait for n=60+ confirmation; (c) implement at `lineup_update.py` time as a pre-tip caution layer rather than at analyst time. **Architectural constraint:** CLV signal requires pretip data, so rule must fire AFTER `odds_pretip.yml` runs — not at morning analyst time. Temporal placement (analyst-stage vs lineup_update-stage) is the dominant decision before rule text design.

**CLV deep analysis review** — `tools/clv_analysis.py` ran 2026-04-30, report at `data/clv_analysis_2026-04-30.md` (407 CLV-qualified picks across prop type / confidence band / magnitude / miss classification / per-player). Decide based on the breakdowns whether to (a) build an Audit Log CLV panel surfacing the headline + magnitude split for daily situational awareness; (b) add a pre-tip caution layer when `market_implied_prob` drops materially vs `morning_implied_prob` (note: the `medium_lost` 92.0% hit rate at clv ∈ [-5.0, -2.0] suggests modest adverse movement is noise, while `large_lost` <-5.0pp drops to 71.4% — magnitude threshold matters); (c) feed CLV-conditional hit rates into the analyst rolling performance summary; or (d) close as "system tracks market consensus, no actionable edge" given avg_clv ~0. Companion follow-up: backfill `miss_classification` onto graded picks (or have auditor mirror the field onto pick records at grading time) so Breakdown 4 surfaces real classifications instead of only "unclassified".

**Platform note:** Primary execution on Kalshi (CA-legal prediction market). Odds ingest pulls from OddsAPI (FanDuel as bookmaker); execution remains manual.

### Technical Debt
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. Intentional (ensures freshness) but adds ~10s to runtime. Low priority.
- **Gate 1 auto-skip architectural refactor** — `lineup_update.py` line ~1601 currently uses `voided=True` for confidence-based skips, colliding with injury-void semantics (see 2026-04-23 Jokic incident in `ROADMAP_resolved.md`). The retroactive un-void patch + injury_void whitelist are bandaids. Needs a new field (`amendment_skip=True`) with independent frontend treatment ("AMENDMENT SKIP" badge, strikethrough or distinct color, clearly separated from "VOIDED — Player OUT"). `build_site.py` would need to render both states distinctly; `auditor.py` would need to handle `amendment_skip` picks (grade normally against actual outcome; don't count as void). Offseason scope.
- **Rotowire ingest data bleed** — on 2026-04-23, `injuries_today.json` showed J. Clark and T. Shannon listed under BOTH DEN and MIN rosters (both are MIN-only players). Low operational impact since neither is a pick target, but suggests a name-matching bug in `rotowire_injuries_only.py` (possibly the Rotowire HTML rendering duplicates cross-team names on matchup pages, or the parser walks too far from the team-logo anchor). Offseason investigation.

### Frontend
- ✅ **Layer 3 — Line movement indicators** (shipped 2026-04-11).
- ✅ **Frontend HTML-escape fix** (shipped 2026-04-15) — `escapeHtml()` helper wraps all analyst free-text injection sites.
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
- **DET secondary creator AST caution (WATCH, shipped 2026-04-23)** — monitor Thompson AST T2 through G3-G4. If misses again (3rd consecutive), upgrade to practical confirmed rule. If clears, demote annotation. Scope: DET non-primary playmakers only (raw_avgs AST < 4.0) — Cunningham unaffected.
- **Promote playoff trajectory to a permanent dossier dimension** (followup to 2026-04-24 sweep utility) — currently surfaced only via `tools/playoff_trajectory_sweep.py` and the 2026-04-24 batched annotations in `nba_season_context.md`. Long-term: add cross-season trajectory metric to H28 backtest output schema directly (per-player `trajectory_class` field per stat), have `playoff_player_dossier.md` regeneration consume it, retire the standalone sweep utility once integrated.
- **Home/away inversion bug — full fix sequence shipped (2026-04-25):** Fix 1 (manual season-context correction in DEN-MIN G3 paragraph), Fix 2 (`agents/playoff_matchup.py` TONIGHT line + `load_today_host()` helper + `today_host` series field), Fix 3 (per-player `today_is_home` field in `quant.py` + ` [H]`/` [A]` tag in `build_quant_context()` player headers + explanation paragraph in both `build_prompt()` and `build_pick_prompt()` QUANT STATS sections), Fix 4 (`reconcile_game_attribution()` post-processor in `save_picks()` chain), and Fix 5 (`agents/season_context_updater.py:build_llm_prompt()` Candidate A venue-claim guardrails — DIARY ENTRY GUIDELINES + IMPORTANT prompt-text constraints) all landed. Five independent layers now catch the home/away inversion class of error at every stage of the pipeline. Full diagnosis: `data/home_away_root_cause_investigation.md`. Season context updater investigation: `data/season_context_updater_investigation.md`. Functional verification of Candidate A occurs on the morning of 2026-04-26 (next bot commit producing G4 diary entries for tonight's DET-ORL/NYK-ATL/DEN-MIN slate at lower-seed homes); diary entry text should grep clean for the 11 banned phrases enumerated in the VENUE CLAIMS rule. Candidates B (`playoff_bracket.json` plumbing) and C (A+B combined) deferred to offseason.
- **Penalty cap rule shipped (2026-04-28):** MAGNITUDE CAP at -20pp added to `agents/analyst.py:build_prompt()` + `build_pick_prompt()` PENALTY STACK LIMIT section as a parallel constraint to the existing COUNT rule. Caps aggregate penalty magnitude at -20pp regardless of penalty count. Canonical case: 2026-04-27 Jokic AST T8 (90% base − 25pp uncapped → 65% → silently skipped; actual 16-AST triple-double). With cap: 90% base − 20pp → 70% (above 68% AST floor) → pick ships. Structurally verified at landing; awaiting natural production trigger conditions for empirical confirmation. **Observability shipped 2026-04-30** — every analyst run now produces `obs_penalty` telemetry on every pick with penalties (raw aggregate distribution + cap fire rate), regardless of whether the cap fires. The new `[PENALTY_RAW: <value>pp]` LLM annotation captures the pre-cap aggregate sum on every pick; `compute_observability()` parses it into `picks.json.obs_penalty.{raw_pp, cap_applied, savings_pp}` and emits `[analyst] OBS PENALTY:` console log lines. Re-evaluate after 5–10 days of accumulation. Individual-penalty recalibration and cap-value sensitivity test remain offseason work. Companion prompt for AST playoff floor bump (+5pp confidence floor for AST picks in playoff close games against tough defense) held for separate session due to context budget.
- **Tier walk market-awareness shipped (2026-04-26):** Two-layer fix landed in `agents/analyst.py` — Layer A LLM prompt rule (TIER_WALK MARKET-AWARENESS bullet in SELECTION RULES of both `build_prompt()` and `build_pick_prompt()`) + Layer B Python post-processor `revert_no_market_walk(picks, player_stats)` slotted between `reconcile_pick_values()` and `reconcile_game_attribution()` in `save_picks()` chain. Structurally verified at landing; awaiting natural production trigger conditions for empirical confirmation. **Observability shipped 2026-04-30** — every analyst run now produces `obs_walk` telemetry whenever Layer A declines a walk for market reasons or Layer B reverts one. New `[WALK_DECLINED: T<from>→T<to>, no market]` LLM annotation is the LLM-side counterpart to Layer B's existing `[WALK_REVERTED:` Python annotation; together they cover both Layer A (LLM-prevented) and Layer B (Python-rescued) cases. `compute_observability()` parses both into `picks.json.obs_walk.{outcome, from_tier, to_tier}` and emits `[analyst] OBS WALK_DECLINED:` / `[analyst] OBS WALK_REVERTED:` console log lines. Re-evaluate after 5–10 days. **Companion prompt** for `skipped_picks.json` logging of `MARKET_GATE_REJECT` events (observability for cases this fix doesn't catch — e.g., when the LLM emits a player not in FanDuel data at all) remains pending as Prompt 2 from the 2026-04-26 dispatch sequence.
- **Decide Review (auto-trim) fate for regular season** — Stage-3 Review API call gated off in playoffs on 2026-04-30 after observing ~95% false-positive rate on `concern`/`stay_away` flags across multiple slates (4/28: 8 of 9 false; 4/30: 13 of 13 false on a 33-pick slate; 39% flag rate vs documented 17–33% target). Root cause: regular-season-derived signals (FG_COLD, FG_MARGIN_NEG, raw_avg, post-miss bounce-back, volatile tag) dominate Review's bear-case construction while playoff series tier hit rates empirically dominate those signals. Gate is currently `is_playoff_mode()` in `agents/analyst.py`; reversal is a 3-line deletion. **Offseason action items:** (1) pull `human_flag_precision` from `audit_summary.json` for the full 2025-26 season, including the H25 backtest (2026-04-12) finding that trim picks hit at 92.4% vs keep at 88.5% (ANTI-PREDICTIVE — trim signal identifies the system's safest picks); (2) evaluate whether Review's `concern` and `stay_away` verdicts have meaningful predictive value at any threshold; (3) decide keep / refine / deprecate before regular season opens. If keep, recalibrate prompt to weight playoff series tier hit rates over regular-season-derived signals; if refine, tighten verdict thresholds; if deprecate, remove `call_review()` / `build_review_prompt()` / `apply_review_flags()` and the Stage-3 block entirely.
- **Auditor guard compliance** — strengthened recommendation contamination guards landed 2026-04-30 in response to the 2026-04-29 audit which produced 5 recommendations with 3 contaminated (rec #3 from a `variance` miss, rec #4 from picks that HIT, rec #5 from an `injury_event` miss bypassing the existing injury guardrail by reframing around the post-injury risk profile). New block in `agents/auditor.py` adds GUARD 1 (injury/workflow with explicit anti-bypass clause), GUARD 2 (variance — lessons OK, recommendations forbidden), GUARD 3 (hits — recommendations exist for misses only), plus an informational note defaulting miss-by-1 outcomes to variance absent a specific mechanism. Verify next 3–5 audit reports contain no recommendations derived from injury_event misses, workflow_gap misses, variance-classified misses, or hits. If contamination persists despite verbatim guardrail text across multiple runs, escalate to Python-side filter at `recent_recommendations` roll-up (line ~1411 in auditor.py) — that requires structured tagging on each recommendation by miss source, a larger change deferred unless behavioral instruction proves unreliable.
- **Run miss classification analysis (`tools/miss_classification.py`) to determine what fraction of misses are catchable-with-current-signals vs catchable-with-new-data vs deterministic-rule-catchable vs inherent variance.** Output: `data/miss_classification_report.md`. Decision input for whether multi-agent expert architecture or new data pipelines should be the next major workstream. Companion to the 2026-04-25 high-conviction filter + tag rename — the high-conviction subset already isolates the safest band; this followup investigates what's left in the miss population to surface where additional accuracy gains are still available.
- **Author static parlay guidance content for the Parlays tab** (followup to 2026-04-24 deprecation of auto-generated parlay agent) — populate `data/parlay_builder_guidance.md` with manually-authored Builder-usage guidance. The guidance loader (`load_parlay_guidance_html()` in `agents/build_site.py`) supports inline markdown: `# H1`, `## H2`, `### H3`, `**bold**`, `- ` bullets, paragraphs. File is read at every site build; graceful no-op when missing. Suggested content (informed by the 2026-04-24 parlay research conclusion that no auto-generated archetype beats market): leverage the empirical findings — Stable bucket (0.66–0.85 combined market prob) had the smallest market underperformance (-18.2pp) and the largest system-vs-actual gap (+27.8pp), so highlight that high-floor anchor-leg construction is the strongest available parlay regime; warn that same-player concentration (3+ legs from one player, even when calibrated_prob looks attractive) does NOT diversify miss correlation and the +1.7pp H7 Reach signal was a small-sample artifact from a single player×date; recommend mixing 2–3 STRONG/POSITIVE-edge legs from different games rather than chasing combined odds.

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
