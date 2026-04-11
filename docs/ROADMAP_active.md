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
- `odds_pretip.yml` runs: hourly from noon–7 PM PT (8 entries) — widened from the original every-30-min 3–7:30 PM schedule so GitHub Actions cron delays (typically 1–6h) don't push every run past tip-off. `pretip_sweep()` window default is now 360 min (6h) with a 30-min post-tip grace period; deduplication on event_id keeps credit cost unchanged (4 per newly-captured game, 0 on re-fires)
- `odds.yml`: manual-trigger only, for ad-hoc re-fetches
- `auditor.py`: computes per-pick CLV (`clv_pp`) from `morning_implied_prob` vs `market_implied_prob`, aggregates `clv_summary` in `audit_summary.json`. **`morning_implied_prob` is now written by `odds_today.py main()` at morning odds annotation time (fix 4/10)** — CLV no longer depends on `pretip_sweep()` actually executing before tip. Verify on the next game day that `morning_implied_prob` populates on every matched pick after the morning `analyst.yml` run.
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
- ✅ H2H splits (`h2h_splits`) — per-opponent tier hit rates annotation in quant + analyst. Annotation-only, no directive rules. Closes H9. (4/9)
- ✅ ESPN Playoff Career Backfill (`ingest/espn_playoff_backfill.py`) — standalone local-run script, probe-first format discovery, upsert idempotency. Full 2021–2025 backfill run: **20,139 rows (18,256 regular / 1,883 playoff) for 65 players** written to `data/playoff_career_log.csv`. Remaining 3 whitelisted players with no rows are 2025-draft rookies with no pre-2026 NBA history (Dylan Harper, Kon Knueppel, VJ Edgecombe) — expected, not a gap. Quant integration (`compute_playoff_splits()`) + daily ingest wiring are separate follow-up prompts. (4/9)
- ✅ Fixed player name normalization mismatch in athlete ID lookups affecting KAT, SGA, De'Aaron Fox, Nickeil Alexander-Walker, Jabari Smith Jr. across `ingest/espn_playoff_backfill.py`, `agents/pre_game_reporter.py`, `agents/post_game_reporter.py`. Added `_norm_name()` helper (hyphens → space, apostrophes/periods stripped) that mirrors `player_dim.csv`'s `player_name_norm` convention. All 68 active whitelisted players now resolve correctly. Backfill row delta: +1,617 rows across the 5 players. (4/9)
- ✅ Playoff career splits quant integration — `compute_playoff_splits()` in `quant.py` reads `playoff_career_log.csv`, computes career playoff vs regular-season deltas (PTS/REB/AST/3PM/FG%) using same-season comparison. Writes `playoff_profile` to `player_stats.json`. Annotation in `build_quant_context()` gated behind `PLAYOFFS_R1_DATE = "2026-04-18"` (inclusive). Annotation-only — no directive rules. 58/65 players eligible (≥5 career playoff games); 11 flagged as small-sample (5–9 games). Zero invariant violations on offline test against the 20,137-row CSV. (4/9)
- ✅ Daily ingest `season_type` integration + playoff dual-write — added `season_type` column to `nba_master.csv` (from ESPN scoreboard `season.type`) and `player_game_log.csv` (joined via `game_id`). Postseason rows (type=3) automatically dual-written to `data/playoff_career_log.csv` by `append_playoff_rows()` in `espn_player_ingest.py` — upsert idempotent on `(player_id, game_id)`. Inert during regular season (returns immediately when no playoff rows present). `ingest.yml` commits `playoff_career_log.csv` alongside other ingest outputs. Keeps the file fresh for `compute_playoff_splits()` without manual backfill re-runs once playoffs start. (4/10)
- ✅ Frontend — Playoff Career Profiles panel + Playoff Game Explorer added to Research tab in `build_site.py`. New `build_playoff_data()` reads `playoff_career_log.csv` at build time and produces `{profiles: [...], games: {...}}`. Research tab now stacks three collapsible sections: (1) **Playoff Career Profiles** — 58 sortable cards (sort by Games / PTS Δ / REB Δ / AST Δ / 3PM Δ / FG% Δ / A–Z) with colour-coded deltas, season chips, and expandable per-season breakdown; (2) **Playoff Game Explorer** — player/stat/season/round/opponent/H-A filters → tier hit rate table with bar charts + grouped-by-series game log with inferred round labels (R1/R2/CF/Finals); (3) **Player Explorer** — existing current-season explorer, wrapped in `renderCurrentSeasonExplorer()` and preserved byte-for-byte. Pure static data, no LLM calls, no runtime dependencies beyond pandas. Site size 1.14 MB → 1.53 MB (+391 KB, mostly the per-game playoff dataset). Verified in browser: 58 profiles render, Tatum 76g / Brown 74g / White 73g descending sort, Banchero +4.3 PTS Δ leads PTS sort, Tatum × 2023-24 × R1 filter shows 5 games vs MIA with small-sample badge, current-season explorer unchanged. (4/10)
- ✅ Scout token budget fixed 4/10 — `SCOUT_MAX_TOKENS` 4096→12288, undersize fallback at <12 shortlisted on 40+ slates, prompt inclusion language strengthened. Root cause: 4096 output tokens physically limited Scout to ~8-9 structured entries, causing it to pre-filter aggressively and drop strong candidates (KAT 85% PTS, Brunson 75% PTS, OG Anunoby 90% PTS on 4/10). Now the Scout has ~3× the output headroom; if the model still under-delivers on a large slate, the undersize check falls back to single-call mode automatically. (4/10)
- ✅ **Playoff Player Adjustments block** — `build_playoff_adjustments()` live in `agents/analyst.py`, date-gated to PLAYOFFS_R1_DATE (≥ 2026-04-18). Annotation-only per-player directional guidance for 20 players synthesized from H27–H32 backtests (career playoff data, minutes elasticity, confidence calibration, consistency index, series progression, blowout resilience). Wired into all 3 prompt builders: `build_prompt()` (v1 fallback), `build_scout_prompt()` (v2 scout), `build_pick_prompt()` (v2 pick — inline next to existing `build_playoff_context()` call). Review after first playoff week for analyst reasoning quality. (4/11)

**Remaining gap items (April 12–13):**
- Create `data/playoff_bracket.json` — populate once seeds are final after 4/11 games
- Update `context/nba_season_context.md` — add PLAYOFFS section with bracket, revisit H15 suppressor notes for actual matchups
- Deactivate non-playoff teams on whitelist
- Verify 4/10 run: walked_tier emission, market gate, pre-game reporter fixes, pretip sweep, CLV computation
- Layer 3 frontend implementation (if Layers 1+2 verified clean)
- ✅ **Skip Re-evaluation on Star Absence** shipped 2026-04-11 (Part 2 of 2, H26 downstream loop closed). `build_skip_reconsiderations()` in `agents/lineup_update.py` re-evaluates morning `merit_below_floor` PTS/AST skips when a team's leading scorer is confirmed OUT. Reads `star_absence_lift` from `player_stats.json` (Part 1), uses `compute_without_player_rates()` for per-player gate, emits `card_type="skip_reconsideration"` cards to `opportunity_flags.json` via existing `save_opportunity_flags()` pipeline. PERSONAL_DRAG_WARNING guard fires before any reconsider logic (Jalen Green / Booker case). Runtime-tested with synthetic fixture reproducing the Tatum/Brown motivating case — PTS T20 reconsidered with `+27.3pp` player-specific delta; REB/volatile_weak_combo/wrong-date/DRAG skips all correctly filtered out.
- ✅ **Analyst Star-Absence Uplift Annotation** shipped 2026-04-11 (Part 1 of 2). `compute_star_absence_deltas()` in `quant.py`, `star_absence_lift` field in `player_stats.json`, STAR_ABSENT_LIFT annotation in `build_quant_context()` gated on star being in today's OUT set, per-qualifier guidance added to WITHOUT-STAR BASELINE rule (build_prompt) and TEAMMATE ABSENCE USAGE ABSORPTION rule (build_pick_prompt). Annotation-only — no directive rules. Validated end-to-end with Tatum/Brown case (+27.3pp PTS T20 STRONG_PERSONAL_SIGNAL). Part 2 above (Skip Re-evaluation in lineup_update.py) shipped same day — H26 downstream loop now fully closed.

---

#### Skip Re-evaluation on Star Absence
**Status: ✅ SHIPPED 2026-04-11 (Part 2 of 2)** — `build_skip_reconsiderations()` in `agents/lineup_update.py` re-evaluates `merit_below_floor` PTS/AST skips on star absence; reads `star_absence_lift` from Part 1's quant output; PERSONAL_DRAG_WARNING guard prevents the Jalen Green / Booker class of misses; outputs `skip_reconsideration` cards to `opportunity_flags.json`. Runtime-tested with synthetic Tatum/Brown fixture (+27.3pp PTS T20 reconsidered). H26 downstream loop now fully closed.
**Depends on:** H26 (CONFIRMED SIGNAL, 4/10)
**Scope:** `agents/lineup_update.py`, `data/opportunity_flags.json`, reads `data/skipped_picks.json` + `data/player_stats.json`

**Design:** When `lineup_update.py` detects a confirmed-OUT player who is the team's leading scorer (per quant data), scan `skipped_picks.json` for teammates whose `skip_reason` is `merit_below_floor`. Re-estimate confidence by softening penalties invalidated by the absence:
- FG% safety margin (H11): recomputed without the star's shot-diet competition → threshold shifts downward, fewer "fg_margin_thin" triggers
- SHORT_SAMPLE flag: if the player's low `games_available` is caused by the star's own absence pattern (both missed the same stretches), the flag is spurious in the current state and can be relaxed
- vs_tough rate: supplemented by without-star hit rate where available (per-teammate from H26 data)

If the re-estimated confidence crosses 70%, write a `skip_reconsideration` entry to `opportunity_flags.json` with `{triggered_by_star, original_skip_reason, softened_penalties, revised_confidence, tier, stat}`. The frontend already renders `opportunity_flags.json` cards — no new UI work required.

**Gates:**
- PTS and AST props only (REB and 3PM showed no H26 signal)
- Confirmed-OUT star only (no QUESTIONABLE / DOUBTFUL / GTD — matches the Without-Star Baseline rule's gate philosophy)
- Leading scorer identification uses the same logic as the H26 backtest (highest PTS avg, ≥20 games)
- Per-teammate without-star check: if the player has ≥3 prior without-star games in `player_stats.json["key_teammate_absent"]` AND the per-player direction is *negative* (e.g. Jalen Green without Booker), skip the reconsideration for that teammate — the population lift must not override per-player evidence

**Motivation:** Direct fix for the 4/9 Tatum scenario that motivated H26 — if the Review agent had escalated Tatum's pick to `manual_skip` but Brown was OUT, this feature would have caught the reconsideration window and surfaced Tatum as a recoverable opportunity.

---

#### Analyst Star-Absence Uplift Annotation
**Status: ✅ SHIPPED 2026-04-11 (Part 1 of 2)** — `compute_star_absence_deltas()` in `quant.py` produces `star_absence_lift` field in `player_stats.json`; `build_quant_context()` renders `STAR_ABSENT_LIFT` two-line annotation gated on star being in today's OUT set; per-qualifier guidance added to `WITHOUT-STAR BASELINE` rule in `build_prompt()` and to `TEAMMATE ABSENCE USAGE ABSORPTION` rule in `build_pick_prompt()`. Runtime invariant verified (49/49 players pass `n_with + n_without == total` check). Motivating Tatum/Brown case reproduces exactly (PTS T25 +57.6pp, PTS T20 +27.3pp, STRONG_PERSONAL_SIGNAL). Annotation-only — no directive rules. Part 2 (Skip Re-evaluation) still pending.
**Depends on:** H26 (CONFIRMED SIGNAL, 4/10)
**Scope:** `agents/quant.py` (compute population + per-player deltas at context-build time), `agents/analyst.py` (annotation injection + prompt rule)

**Design:** When the team's leading scorer is confirmed OUT for today's game, inject a `STAR_ABSENT_LIFT` annotation into quant context for each teammate on that team:

```
  STAR_ABSENT: [Jaylen Brown OUT] population PTS T15-T25 +11 to +13pp, AST T4 +10pp
  Player-specific (6g): PTS T20 without Brown = 100%, delta +71pp  [STRONG_PERSONAL_SIGNAL]
```

**Interaction with existing rules:**
- The annotation is **informational only** — no directive rule, no mechanical confidence override. The analyst sees the line and factors it into reasoning alongside the existing Without-Star Baseline two-gate check (added 2026-03-22).
- Per-player without-star data in `key_teammate_absent` **always takes precedence** over the population average. If the player has ≥3 prior without-star games, the annotation leads with the player-specific number; population lift is shown as supplementary context.
- The existing Without-Star Baseline rule (confirmed-OUT gate + n ≥ 10 sample gate for primary qualifier) is unchanged. This annotation is additive, not a replacement.

**Directional qualifier from H26 per-teammate data:**
- `[STRONG_PERSONAL_SIGNAL]` — player has ≥3 without-star games AND per-player delta is positive AND aligned with population direction
- `[NEUTRAL_PERSONAL_DATA]` — player has ≥3 without-star games but delta is within ±3pp of zero
- `[PERSONAL_DRAG_WARNING]` — player has ≥3 without-star games AND per-player delta is negative (e.g. Jalen Green without Booker); in this case the annotation SUPPRESSES the population lift entirely and prints only the drag warning
- `[POPULATION_ONLY]` — fewer than 3 without-star games; population average is shown but labeled as low-confidence

**Caveat:** If per-player data shows a drag, the population lift must NOT fire. The annotation logic is: per-player data wins whenever it exists at ≥3 games; population data is only shown standalone when no per-player history is available. This prevents the Jalen Green–type miss where the population signal would have misled the analyst.

**Gates:** PTS T15/T20/T25 and AST T4/T6 only — the five tiers where H26 crossed the +3pp SIGNAL threshold. Do not annotate REB (weak signal) or 3PM (noise).

---

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
**Status: SYSTEMIC — monitor whether endpoint recovers (4/10)**

All per-athlete ESPN fetches failing across every player with a valid athlete_id — this is not a missing-ID problem, it's the ESPN public athlete news endpoint itself (monitor for recovery upstream). Pre-game news still arrives via the league-wide feed (`fetch_league_news`), which is unaffected. Error diagnostics are now fully split in `pre_game_news.json`: `no_id_errors` (athlete_id missing from `player_dim.csv`), `espn_errors` (HTTP/network failure on the athlete endpoint), `no_news_players` (fetch succeeded but returned zero items). Combined `fetch_errors` retained for backward compatibility. Shipped 4/10 alongside the `team_abbr_alt` match fix in `load_target_players()` which recovered 10 NYK/SAS/GSW players who had been silently dropped because the whitelist uses Rotowire abbrevs and `nba_master.csv` uses ESPN short codes.

#### W13 — Skip Rule Refinements: T10 floor exception + co-primary gate + elite exemption + 3PM T1 iron_floor
**Status: OPEN — monitor in production (opened 2026-04-11)**

Four prompt refinements shipped 2026-04-11 addressing high-false-skip-rate rules: (1) `blowout_t25_skip` now exempts elite scorers (raw_avgs PTS >= 27.0) — they proceed through normal T25 eval at the 74% cap instead of hard-skipping; (2) `blowout_secondary_scorer` threshold lowered from >= 15 → >= 13.5, with a new `T10 FLOOR EXCEPTION` (T10 PTS picks are never hard-skipped by this rule) and a `CO-PRIMARY SCORER GATE` (any player with raw_avgs PTS >= 22.0 is always PRIMARY, preventing the rule from firing against one of two co-primaries on the same team); (3) 3PM trend=down T1 step-down now has an `iron_floor OR 9+/10` exception — instead of skipping outright, hold at T1 with a -5% confidence penalty; (4) monolithic `build_prompt()` 3PM blowout rule aligned with the H19-relaxed version in `build_pick_prompt()` (step-down at spread_abs 8–18 instead of hard-skip, with the spread_abs >= 19 unconditional hard-skip unchanged). **What to watch:** skip validation table in `audit_summary.json` — these four rules should show reduced false skip rates over the next ~10 days of audited picks. Specifically: `blowout_t25_skip` FSR should drop as elite scorers with 8+/10 hit rates no longer get blocked; `blowout_secondary_scorer` FSR should drop as T10 picks and co-primaries no longer trigger it; and 3PM picks for players with iron_floor at T1 should no longer appear in the skip archive when trend turns down. Any regression (hits at reduced confidence that should have been skipped) should surface within 20–30 picks if the relaxation was too aggressive. Review around 2026-04-21.

---

### Pending Backtests

### H9 — Player × Opponent H2H Splits
**Status: CLOSED — deployed as annotation-only quant feature (`h2h_splits`) on 2026-04-09.**
**Mode: `--mode h2h-splits` (not implemented — formal backtest bypassed)**

Deployed as annotation-only feature in `agents/quant.py` (`compute_h2h_splits()`) and `agents/analyst.py` (`build_quant_context()`) — see ROADMAP_resolved.md. Formal backtest bypassed: annotation-only deployment at small samples (n=2–4) does not warrant backtest-first validation. A divisional opponent played 2–4× per season in the regular season reflects deliberate defensive attention, not noise — qualitatively different from signals that need gating. In a 7-game series, H2H is the most playoff-relevant signal the system can surface. The analyst receives it as context and applies its own judgment; no directive rules attached. Signal will accumulate through playoffs.

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

### H24 — Market Disagreement Gate
**Status: DESIGNED — queued for backtest when ~50+ odds-enriched picks are graded**
**Mode: `--mode market-disagreement` (not yet implemented)**

**Question:** Do picks where FanDuel implied probability exceeds system confidence by ≥15pp (`edge_pct ≤ -15`) hit at a meaningfully lower rate than other picks?

**Proposed rule:** When `market_implied_prob − confidence_pct ≥ 15` AND the pick does not carry `iron_floor`, exclude with `skip_reason = market_disagreement`. Lives in the analyst prompt as a KEY RULE using the prefetched odds data from `odds_available.json` (already loaded by the market availability gate).

**Trigger:** Auditor Rec #1 from the 4/9 audit — Barnes AST T4 at 74% confidence vs 91.67% market-implied probability, missed badly. The thesis is that when the market prices a leg 15+ percentage points tighter than the system, the market has information (rotation, load, matchup) the system lacks.

**Activation gate:** ≥50 graded picks with `bet_recommendation` data in `picks.json`. Currently accumulating since the 4/7 odds integration shipped. Re-check count weekly — when it crosses 50, implement the mode and run the backtest before shipping the prompt rule.

---

### H25 — Trim Escalation Signal
**Status: DESIGNED — queued for backtest when ~30+ trim-verdict picks have outcomes**
**Mode: `--mode trim-escalation` (not yet implemented)**

**Question:** Do picks with `verdict: "trim"` AND `confidence_pct ≤ 75` AND at least one structural weakness flag (VOLATILE tag, vs_tough < 60%, road underdog) hit at a meaningfully lower rate than other trimmed picks?

**Proposed rule:** Review agent escalates `trim` → `manual_skip` when all three conditions are met simultaneously. Lives in the Review agent prompt as a stay-away gate. Does not touch the Pick stage — the escalation happens downstream in Stage 3.

**Trigger:** Auditor Rec #4 from the 4/9 audit — both session misses that day had trim recommendations AND ≤75% confidence AND a structural weakness flag. Thesis: trim-verdict picks as a class hit at 92.9% season-to-date (very safe), but the sub-population that combines all three weakness signals may be where the trim verdict is under-calling the risk.

**Activation gate:** ≥30 `trim`-verdict picks with graded HIT/MISS outcomes across historical `picks_review_*.json` files. Currently 116 trim picks season-to-date (per `human_flag_precision` block), but the sub-population of `trim + ≤75% + weakness flag` is much smaller — need to measure it first before running the backtest.

---

### H26 — Star Absence Teammate Impact
**Status: CONFIRMED SIGNAL — results reviewed 4/10**
**Mode: `--mode star-absence`**

Measures teammate tier hit rate deltas (with vs without the team's leading scorer) across the 2026 season. Leading scorer = highest PTS avg with ≥20 non-DNP games; star-absent games = dates the team played but the star did not. Per-teammate hit rates computed at every PTS/REB/AST/3PM tier with min 3 games per condition.

**Confirmed signal on 2026-season data** (14 teams qualified, 31 teammate observations):
- **PTS_T15**: +11.3pp weighted avg lift (77% positive)
- **PTS_T20**: +12.7pp weighted avg lift (71% positive)
- **PTS_T25**: +10.5pp weighted avg lift (71% positive)
- **AST_T4**: +9.6pp weighted avg lift (71% positive)
- **AST_T6**: +6.7pp weighted avg lift (55% positive)

All five key tiers cross the +3pp SIGNAL threshold with ≥10 observations. The motivating 4/9 scenario (Tatum +27.3pp PTS T20 when Brown OUT, Pritchard +71.2pp PTS T20) is present in the BOS-specific section.

**Important caveat:** per-player direction varies. Population lift is strong but individual teammates can show drags (e.g. Jalen Green PTS cratered without Booker). Any production rule MUST check per-player without-star history before applying the population average — the two downstream items below both respect this.

**Downstream consumers:** two items added to the April 12–13 gap queue (see below) — skip re-evaluation in `lineup_update.py` and analyst star-absence uplift annotation in `quant.py` + `analyst.py`. Both are designed to respect per-player history when available and fall back to population data only when per-player samples are thin.

---

### H27 — Primary Scorer Blowout PTS Performance
**Status: FIRST RUN COMPLETE — MIXED verdict, action deferred (4/11)**
**Mode: `--mode primary-blowout`**

Tests whether `blowout_t25_skip` (hard-skip of primary scorer PTS T25/T30 at spread_abs ≥ 15) is correctly suppressing a structural risk, or whether the rule is over-penalizing a population that still hits T25 above baseline. Motivated by 100% false skip rate on graded data (Maxey 32, Wembanyama 40).

**Headline findings:**
- Primary scorers at spread_abs ≥ 15 hit PTS T25 at **58.8% (n=68)** — ABOVE the 50.6% full-dataset baseline. Verdict: MARGINAL.
- **GAME_SCRIPT_DEPENDENT** signal is the most important result. When the spread said blowout AND the game actually materialized as one (final margin ≥ 15), primary T25 dropped to 45.7% (n=35). When the spread said blowout BUT the game stayed competitive, primary T25 elevated to 73.7% (n=19). **Delta: +28.0pp.** The rule is firing on a population that's roughly half pure-signal (real blowouts) and half false-positive (spreads that don't materialize).
- Jokic hypothesis NOT confirmed — only 1 qualifying Jokic game in the sample (n_with=68 vs n_ex=67, delta=+0.9pp).
- Per-player breakdown identifies 3 PLAYER_SUPPRESSED (Durant HOU, Cunningham DET, Luka LAL minutes-compressed) and 3 PLAYER_RESILIENT (Mitchell +17.2pp, Ball, Murray +51.6pp). Suppression concentrated in HOU/DET roster contexts, not uniform.

**Action deferred for in-season:** single-season sample for actionable change. The GAME_SCRIPT_DEPENDENT finding is compelling but operationalizing it requires knowing whether the game will actually be a blowout at pick time, which we don't. Revisit after playoffs + multi-season sample. For now, per-player flags inform offseason discussion of player-specific rules.

**Candidate rule changes (offseason):**
1. Replace `blowout_t25_skip` hard skip with a -5pp confidence cap for primary scorers at spread_abs ≥ 15 — matches MARGINAL verdict
2. Keep hard skip only for players with repeated PLAYER_SUPPRESSED flags across multiple seasons (player-specific)
3. Consider retiring the rule entirely; the false skip rate (2/2) aligns with population T25 58.8% vs 50.6% baseline.

---

### H28 — Playoff Career Tier Performance
**Status: FINDINGS INJECTED INTO ANALYST PROMPT (4/11) — H27/H28/H29/H30/H31/H32 synthesized into `build_playoff_adjustments()`, date-gated to PLAYOFFS_R1_DATE (4/18). Review analyst reasoning quality after first playoff week.**
**Mode: `--mode playoff-career`**

Compares per-player regular vs playoff career tier hit rates across PTS/REB/AST/3PM using `data/playoff_career_log.csv` (2021–2025, 18,168 regular + 1,883 playoff games). 58 players qualified (47 reliable with ≥10 playoff games, 11 limited-sample with 5–9). Per-player flags: ELEVATOR / STABLE / SUPPRESSOR per stat at key tier (PTS T20, REB T6, AST T4, 3PM T2); cross-stat overall flag: STRONG_ELEVATOR / ELEVATOR / MIXED / STABLE / SUPPRESSOR / STRONG_SUPPRESSOR.

**Headline findings:**
- Population deltas are small (PTS +0.7pp, REB +4.9pp, AST −4.9pp, 3PM −1.6pp at key tiers). The signal is entirely per-player.
- **6 STRONG_ELEVATOR** players: Banchero, Paul George, Jalen Williams, CJ McCollum, Anthony Edwards, Austin Reaves — all lift across 3+ stats.
- **15 STRONG_SUPPRESSOR** players including Tyler Herro (−37pp PTS T20), Julius Randle (−30pp REB), KAT (−36pp AST T4), Mikal Bridges, Payton Pritchard (uniformly crushed across all stats).
- **Jokic** is ELEVATOR overall and gets *more* lethal in playoffs at PTS (+12.6pp at T30) — opposite of the H27-motivating anecdote. He compresses AST at higher tiers (T6 −12.2pp, T8 −13.7pp) but stays STABLE at T4. A rule reading the `tiers` sub-dict (not just the key-tier flag) gets the nuance for free.
- **Tatum** is MIXED: PTS T20 −6.5pp suppression is absorbed by a +16.6pp AST T4 lift — usage profile shifts toward playmaking in playoffs.

**Downstream consumers (deferred to separate task):** Playoff context block injection into analyst prompt. The JSON output (`data/backtest_playoff_career.json`) contains per-player `stats[stat].flag`, `key_tier_delta_pp`, full `tiers` sub-dict, and `playoff_game_log` for evidence review. Top-level `summary` dict maps `player_name → overall_flag` for quick lookup. No production rule changes shipped in this backtest.

**Caveat:** Single-playoff-sample risk — Herro's 29-game sample is dominated by a specific tough matchup series; Randle's 30-game sample reflects the pre-MIN-trade Knicks context. Before using flags as directive signals, multi-season cross-validation is wise for any player with fewer than ~20 playoff games.

---

### H29 — Player-Level Confidence Calibration
**Status: FIRST RUN COMPLETE — actionable signal confirmed (4/11)**
**Mode: `--mode confidence-calibration`**

Audits per-player calibration using 815 graded picks from `picks.json`. For each player with ≥10 picks, compares mean assigned confidence to actual hit rate. Flags OVER_CONFIDENT (delta ≤ −8pp), UNDER_CONFIDENT (delta ≥ +8pp), WELL_CALIBRATED.

**Headline findings:**
- **Overall hit rate 87.1%** (815 picks) vs **avg assigned confidence 77.1%** — a 10pp population under-confidence gap. Consistent with existing `audit_summary.json` `confidence_calibration_totals` and validates the pick mechanism.
- **31 players qualified** (≥10 picks): 2 OVER_CONFIDENT, 18 UNDER_CONFIDENT, 11 WELL_CALIBRATED.
- **OVER_CONFIDENT: Brandon Ingram (−15.2pp)** — PTS 40% (n=5) and AST 66.7% (n=6) both flagged prop-specific. **Donovan Mitchell (−10.4pp)** — PTS 60% (n=5) and 3PM 42.9% (n=7) are the culprits; his AST picks are fine. These are the only two players over-rated at threshold.
- **UNDER_CONFIDENT clusters**: Paolo Banchero (+19.5pp, 95.7% actual), Cade Cunningham (+18.6pp), Jaylen Brown (+18.3pp), Wembanyama (+17.5pp), LeBron (+17.3pp), Luka (+15.7pp), Kon Knueppel (+14.6pp), SGA (+13.5pp), LaMelo Ball (+13.6pp), Austin Reaves (+13.5pp), Giannis (+12.3pp), Sengun (+12.2pp), Desmond Bane (+11.5pp), Kawhi Leonard (+11.2pp), Jokic (+10.6pp), James Harden (+10.2pp), Scottie Barnes (+9.8pp), Julius Randle (+8.5pp). Many of these players hit at 90–100% while being rated at 75–79% — systematic conservative floor.

**Downstream consumer (deferred to separate task):** Per-player calibration lifts/caps could be injected into the analyst prompt as confidence adjustments or into the `bet_recommendation.calibrated_prob` computation as per-player overrides. Care needed to avoid double-counting with the existing band-based calibration already feeding the odds layer.

**Caveat:** Small-sample risk for players with 10–15 picks (Wemby, Cunningham, Giannis, Duren, Flagg). The big-sample OVER_CONFIDENT cases (Mitchell 23, Ingram 13) are more trustworthy than their raw delta magnitude suggests — Mitchell's 3PM weakness is specifically coherent with his perimeter-heavy role on CLE.

---

### H30 — Minutes Elasticity
**Status: FIRST RUN COMPLETE — strong population signal, per-player ranking ready (4/11)**
**Mode: `--mode minutes-elasticity`**

Quantifies per-player production-vs-minutes curves across 4 absolute minutes buckets: low (<30), normal (30–34), high (34–38), extended (38+). Elasticity = (extended − normal) hit rate delta at key tier (PTS T20, REB T6, AST T4, 3PM T2). Flags: SCALES (delta ≥ +10pp), PLATEAUS (−10 to +10pp), INVERTS (delta ≤ −10pp). Overall player flag driven by PTS flag with SELECTIVE_SCALER for PTS-plateau + other-stat-scales combinations.

**Headline findings (3,533 non-DNP player-games, 58 unique players, 56 qualified at ≥20 games):**
- **Population elasticity is massive**: PTS T20 +26.0pp, PTS T25 +28.9pp, REB T6 +17.0pp, AST T4 +21.1pp, AST T6 +26.7pp. Every bucket is monotonically higher than the previous one at every tested PTS/REB/AST tier. 3PM is weakest (+9.6pp at T2) — 3PM is more shot-allocation-bound than minutes-bound.
- **23 MINUTES_SCALERS**: biggest deltas are Alperen Sengun (+54.7pp), Miles Bridges (+54.2pp), Jalen Johnson (+50.6pp), Paolo Banchero (+48.3pp), Bam Adebayo (+40.9pp), Scottie Barnes (+40.4pp), Brandon Ingram (+38.9pp), **Anthony Edwards (+37.5pp)**, **Jokic (+33.3pp)**, VJ Edgecombe, Austin Reaves, Derrick White, Desmond Bane, Joel Embiid, Devin Booker, Luka (+12.5pp, 57→88→100→100%), Jamal Murray, Tyrese Maxey, Julius Randle, Jabari Smith Jr., NAW, Kon Knueppel, Jaden McDaniels.
- **6 SELECTIVE_SCALERS**: Rudy Gobert (REB scales, PTS plateaus), Kawhi Leonard (already near ceiling at 89→96→100→100% PTS), Payton Pritchard, Cameron Johnson, Amen Thompson, Kevin Durant.
- **3 MIXED**: SGA (100%→100%→100%→100% PTS T20 — pure ceiling), Jaylen Brown, Cade Cunningham.
- **2 MINUTES_INVERTERS**: Donovan Mitchell (−19.1pp, n_ext=7), LeBron James (−28.0pp, n_ext=5). Both small samples, both directionally consistent with age/efficiency-compression narratives but treat as suggestive, not definitive.
- **22 INSUFFICIENT_DATA**: players whose avg minutes sits below ~32 so they don't have ≥5 games in the extended bucket (LaMelo, Jalen Green, Hartenstein, CJ McCollum, RJ Barrett, Holmgren, Mobley, many others). Not a bug — real information about regular-season minute allocation.

**Ant Edwards T25 progression (the canonical extreme case):** 25% low → 50% normal → 69.6% high → **86.4% extended** = +61.4pp span. Aggregate T25 rate of 52% massively understates his playoff T25 capability.

**Downstream consumer (deferred to separate task):** A future playoff confidence adjustment layer could directly use each scaler's `extended_key_rates` or `playoff_projection.vs_overall_delta` as per-player playoff bumps. Prime candidates for +5 to +10pp playoff confidence bumps: Banchero, Ant Edwards, Jalen Johnson, Sengun, Bam Adebayo, Jokic, Scottie Barnes, Luka, Jamal Murray, Maxey. No bump for MIXED/INSUFFICIENT players. Possible slight tax for Mitchell/LeBron — but given the small extended samples, prudent to wait for more data before penalizing them.

**Caveat:** Many scaler deltas come from thin extended-bucket samples (5–12 games). The population-level signal is real at n=3,533 player-games, but individual per-player deltas carry sample noise. Any per-player rule should gate on n_extended ≥ 10 to be directive, and use the flag as directional guidance below that threshold.

---

### H32 — Player Consistency Index
**Status: FIRST RUN COMPLETE — per-player vulnerability ranking ready (4/11)**
**Mode: `--mode consistency-index`**

Measures per-player tier hit rate stability across 3 context dimensions (Home/Away, Rest: B2B/Normal/Extended, Spread: Competitive/Blowout-risk). Formalizes the iron_floor intuition across multiple dimensions. Flags ALL_WEATHER (<10pp range), MODERATE (10–20pp), CONTEXT_SENSITIVE (≥20pp).

**Headline finding: context-invariance is the exception.** Zero ALL_WEATHER players in the 56-player qualified pool. Only 4 MODERATE (Randle, Jamal Murray, Jaylen Brown, Norman Powell). All other 52 qualified players have at least one stat with ≥20pp range across contexts. The tight thresholds combined with slice-level sample noise make the flag taxonomy itself less useful than the *worst_vulnerability* ranking.

**Dominant vulnerability dimension: REST** (33 of 56 players). Spread was worst for 13 players, Home/Away for 7. Rest-sensitivity is distributed so broadly that per-player quant-level gating is likely more impactful than any blanket rule.

**Top 5 worst vulnerabilities (all at key tier, modal best_tier):**
- Jalen Williams 3PM(T1) spread 64.3pp (comp:0% blow:64%)
- Coby White PTS(T10) H/A 50.0pp (H:100% A:50%)
- Joel Embiid PTS(T25) spread 48.3pp (comp:52% blow:100%) — **opposite of blowout_t25_skip assumption**
- Paul George 3PM(T2) spread 46.4pp (comp:54% blow:100%)
- Bennedict Mathurin PTS(T15) rest 43.3pp (B2B:83% normal:69% extended:40%)

**Notable narrative patterns:**
- **Jokic AST T8** compresses on B2B (57% B2B → 97% normal → 76% extended) — matches the existing one-tier step-down rule for AST on B2B nights.
- **Joel Embiid PTS T25** flips the blowout_t25_skip intuition: his T25 hit rate is *higher* in blowout games (100%) than competitive ones (52%), not lower. Another data point against the aggressive hard-skip.
- **Kevin Durant** plays dramatically better on the road (PTS T20 H:70% A:95%, 25pp range) — opposite of the usual home-court narrative.
- **Kawhi Leonard** shows the mirror image (3PM T2 H:82% A:58%, 24pp range).

**Downstream consumer (deferred to separate task):** A future playoff confidence-adjustment layer could read each player's `worst_vulnerability` + slice detail to flag the specific context in which that player is reliable or unreliable. Today's slate position (home/away + rest + spread_abs) would determine whether the vulnerability fires. Care needed to avoid over-correcting on small-sample slice noise: any per-player rule should gate on slice n ≥ 10 and dim_range ≥ 25pp to be directive.

**Caveat:** Many worst-vulnerability samples come from thin slice populations (5–10 games). Slices with n<5 are already excluded, but the 5-game floor is still noisy. Population signal is clear at the dimension level (rest dominates vulnerability), but individual per-player dim_ranges carry sample noise for slices near the floor.

---

### H31 — Playoff Series Progression
**Status: FIRST RUN COMPLETE — per-player within-series temporal signal validated (4/11)**
**Mode: `--mode series-progression`**

Tests whether tier hit rates shift across phases of a 7-game playoff series: early (G1–2), mid (G3–4), late (G5–7). Complements H28 (overall playoff delta) with a within-series temporal dimension. Data: `playoff_career_log.csv` (2021–2025, 1,883 playoff player-games, 73 series, 44 qualified players at ≥15 playoff games). Series inferred from (season, sorted team pair) with per-player `cumcount` for game-in-series numbering.

**Headline findings:**
- **Population deltas are small:** PTS +1.3pp (flat), REB +4.4pp (slight late lift), AST +3.7pp (slight late lift), 3PM −1.9pp (slight late decline). Only 3PM shows directional compression at the population level — defenses prioritize closing out on shooters as series narrow.
- **Per-player distribution (44 qualified):** 11 LATE_RISER, 18 STABLE, 11 LATE_FADER, 4 INSUFFICIENT_DATA. A clean 25% rise / 41% stable / 25% fade / 9% insufficient split.
- **Top LATE_FADER: James Harden (−33.1pp)** — quantifies his famous playoff collapses. From 56% PTS T20 in games 1–2 to 23% in games 5–7 across 45 playoff games in 8 series. Largest fade in the dataset.
- **Surprising LATE_FADERS: Curry (−15.3pp)** and **Ant Edwards (−15.0pp)** — both fade in late games despite Curry's playoff-closer reputation and Edwards's MINUTES_SCALER flag from H30. Defensive adjustments catch up in games 5–7.
- **Top LATE_RISER: Desmond Bane (+61.4pp)** — biggest rise but thin sample. More robust risers: Julius Randle (+25pp), Kawhi Leonard (+20pp, already near ceiling at 80→100→100%), KAT (+17.7pp), Andrew Wiggins (+13pp), SGA (+8.3pp).
- **STABLE cluster includes: Jokic (+1.8pp)**, **Tatum (+7.1pp, just under threshold)**, Luka, LeBron, Embiid, Brunson, Jaylen Brown, Bam — the elite playoff performers cluster here.

**Notable cross-backtest composition:**
- **H28 + H30 + H31 together produce a 3-layer playoff confidence model.** H28: overall regular→playoff delta per player. H30: minutes-scaler bump for players who benefit from 38+ min. H31: within-series temporal adjustment based on game-in-series at pick time. A fully-wired playoff confidence layer would compose all three: start with regular-season confidence, apply H28 delta, apply H30 minutes bump if applicable, apply H31 phase adjustment based on today's position in the active series.
- **Curry/Edwards/Booker all MINUTES_SCALERS (H30) + LATE_FADERS (H31):** they benefit from the aggregate playoff minutes bump but lose it back in games 5–7. Net effect likely neutral for early-round picks, negative for conference-finals picks.

**Downstream consumer (deferred to separate task):** Future playoff confidence-adjustment layer could read `progression_delta_pp` + current game-in-series to apply phase-weighted confidence adjustments. Three-layer composition with H28 and H30 produces the most nuanced playoff model the backtest suite has generated.

**Caveat:** Per-player late-phase data is inherently thin — requires multiple 5+ game series. Top LATE_FADERS (Harden n=45, Booker n=47, Curry n=43) have richer samples and should be trusted. Top LATE_RISERS like Bane, Norman Powell, Mathurin have n_late ~5–7 and should be treated as directional only. The population signal is noise-free but the per-player sample floor of 5 games is barely enough.

---

## Untested Hypotheses
(none active — H9 closed 2026-04-09 as annotation-only deployment)

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
