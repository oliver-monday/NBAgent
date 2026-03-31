# NBAgent — Session Context & Handoff Reference

**Purpose:** Dense technical handoff for new Claude sessions. Load this alongside `CLAUDE.md`
and `@docs/AGENTS.md` at session start. Covers current implementation state, design decisions,
non-obvious gotchas, and live prompt format — things that take time to re-derive from source.

**Last updated:** March 31, 2026 ((20) **Wembanyama `volatile_weak_combo` PTS exemption** — exception (c) added to `volatile_weak_combo` exceptions in both `build_prompt()` and `build_pick_prompt()`. Wembanyama PTS props receive standard VOLATILE treatment (-5%) rather than hard skip at 7/10 + T20+. Consistent with existing blowout exemption philosophy. Fixes 2026-03-30 PTS T20 skip (actual 41). `agents/analyst.py` only.)
**Last updated (prior):** March 31, 2026 ((19) **BLOWOUT_SECONDARY_SCORER PPG-tier tiebreaker** — both `build_prompt()` and `build_pick_prompt()` now contain a "PRIMARY vs. SECONDARY SCORER TIEBREAKER" paragraph in their BLOWOUT_SECONDARY_SCORER blocks. Tiebreaker: if a whitelisted teammate has a higher best qualifying PTS tier, that teammate is primary and this player is secondary — regardless of ball-handler role. Falls back to season PPG. Fixes 2026-03-30 Harden PTS T15 miss (ball-handler rationalization bypassed skip at spread=17.5). `agents/analyst.py` only.)
**Last updated (prior):** March 31, 2026 ((18) **Amendment sub-70% auto-skip** — `apply_amendments()` in `lineup_update.py` now voids picks when `direction="down"` and `revised_confidence_pct < 70`. The `lineup_update` sub-object remains on the voided pick for audit visibility. Fixes 2026-03-30 SGA AST T4 miss (amended to 68%, ran anyway). `agents/lineup_update.py` only.)
**Last updated (prior):** March 31, 2026 ((17) **Overload retry logic** — `_call_with_overload_retry()` helper added; `call_scout()` and `call_analyst()` now retry up to 4 times on `overloaded_error` with exponential backoff (10s/20s/40s/80s). Scout retries before falling back to single-call mode; analyst retries before raising. Fixes 2026-03-31 complete run failure due to unhandled `overloaded_error`. `agents/analyst.py` only.)
**Last updated (prior):** March 31, 2026 ((16) **H15 Run 3 complete** — ≥600 picks threshold crossed. Three suppressors confirmed: HOU (65.2%, n=23), PHX (75.0%, n=24, NEW), PHI (64.7%, n=17, NEW — game-script/tanking caveat). IND confirmed amplifier (100.0%, n=23, NEW). MIN×AST at 63.6% n=11 — 4 more picks needed for ≥15 formal gate. All updated in `nba_season_context.md` and `docs/BACKTESTS.md`. No prompt rule changes — context-file guidance only.)
**Last updated (prior):** March 26, 2026 ((15) **Eight workflow + prompt fixes**: (a) `lineups_today.json` added to `injuries.yml` commit loop — lineup data now persists across hourly runs; (b) `projected_minutes` integer extraction fix — `el.find_parent("li")` replaces `el.parent` so minutes integer is captured from full list item not just name wrapper; (c) `road_underdog_near_threshold` PTS penalty added to both `build_prompt()` and `build_pick_prompt()` — away team + spread_abs 4–7 (underdog) + raw_avgs PTS − pick_value ≤ 5 → -5% confidence; iron_floor exempt; (d) `volatile_weak_combo` narrowed — trigger changed from `(7/10 OR 8/10) + T15+` to `(7/10 only) + T20+`; 8/10 removed as false-skip driver (KD T20, Sengun T15 confirmed false skips); (e) `parlays.json` added to `auditor.yml` commit loop — parlay grading results were silently discarded since launch; (f) `standings_today.json` added to `ingest.yml` commit loop — auditor was reading stale/missing standings; (g) `Without [X]` context line gated on teammate OUT status — `build_quant_context()` only renders the line when `teammate_name in _out_set`; (h) diagnostic files `pre_game_news.json`, `team_defense_narratives.json` (analyst.yml), `post_game_news.json` (auditor.yml) added to commit loops for retroactive debugging. `agents/analyst.py`, `agents/build_site.py`, `.github/workflows/analyst.yml`, `.github/workflows/auditor.yml`, `.github/workflows/injuries.yml`, `.github/workflows/ingest.yml`, `ingest/rotowire_injuries_only.py`.)
**Last updated (prior):** March 25, 2026 ((14) **Scout omitted block removed** — prompt OMITTED BLOCK section, `call_scout()` omitted extraction + sentinel, `save_scout_omitted()`, `SCOUT_OMITTED_JSON`, `analyst.yml` commit glob all removed. Never populated correctly in 6 days. `call_scout()` return type simplified to `list[dict] | None`. `agents/analyst.py`, `.github/workflows/analyst.yml`.)
**Last updated (prior):** March 25, 2026 ((13) **Absence-aware trend activation guard** — trend override now requires key teammate confirmed OUT/OFS in `injuries_today.json` via `load_players_out_today()` + `players_out_today` param on `build_player_stats()`. Previously fired for any player with ≥5 historical absence games even when teammate was healthy. Gate: `_teammate_name in _out_set`. Safe fallback: empty set means override never fires. Full `key_teammate_absent` dict still written to `player_stats.json` regardless. `agents/quant.py` only.)
**Last updated (prior):** March 25, 2026 (Rotowire parser rewrite: (10) **parse_rotowire_lineups** rewritten — anchors on `data-team` in On/Off Court Stats button (same as working `parse_rotowire_injuries`); reads player names from `<a title="">` attribute; was returning 0 teams since launch due to stale DOM-walking selectors. (11) **parse_projected_minutes** rewritten — anchors on team logo `<img src="/100{ABBREV}.png">`; old parser searched for `div.lineups-viz` class which doesn't exist on `projected-minutes.php`. (12) **parse_onoff_usage** rewritten as graceful `return {}` — On/Off Court Stats data is JS-loaded, not in server-rendered HTML; deferred to offseason (Playwright). `ingest/rotowire_injuries_only.py` only — no agent files touched.)
**Last updated (prior):** March 25, 2026 (Nine fixes applied: (1) **Absence-aware trend** — `compute_teammate_absence_splits()` now returns `absence_trend` per-stat dict (L5 vs full absence-window mean, TREND_THRESHOLD=0.10, only when n≥5); `build_player_stats()` overrides top-level `trend` dict with `absence_trend` values when key teammate is absent and `absence_trend` non-empty — eliminates regime-crossing artifact. Confirmed: Randle trend=up→stable. (2) **Team abbreviation mismatch fix** — `load_whitelist()` in both `quant.py` and `analyst.py` now emits tuples for both `team_abbr` AND `team_abbr_alt`; `load_injuries()` in `analyst.py` normalises `teams_today` via `_ABBR_NORM`. Fixes 10 invisible players (SAS/SA, NYK/NY, GSW/GS, UTA/UTAH). (3) **Scout omitted mandatory accounting** — `build_scout_prompt()` OMITTED BLOCK requires one entry per non-shortlisted player; `call_scout()` injects sentinel on empty return. (4) **is_skip boolean field** — `is_skip: true/false` in pick JSON schema; `filter_self_skip_picks()` checks it as primary gate; `save_picks()` defaults to false. (5) **Streak pill removed** — system-wide streak pills on pick cards were misleading; removed from `buildMicroStats()` in `build_site.py`. (6) **merit_below_floor skip_reason** — added to enum in both prompt functions and `SKIP_CONCLUSIONS`; distinguishes confidence-floor failures from `3pm_blowout_trend_down`. (7) **filter_self_skip_picks merit-floor regex** — two patterns added to catch 75%/78% floor failures in tier_walk; fixed LaMelo/Miller 3PM leaks. (8) **Self-skip picks leaking into picks_review** — `save_picks()` now returns the filtered list; all three call sites in `main()` capture return value. (9) **Signed spread in quant context header** — player header now shows `spread=-10.5(abs=10.5)` rather than bare `spread_abs=X.X`; also: lineup snapshot staleness guard fixed in `write_analyst_snapshot()`.)
**Last updated (prior):** March 22, 2026 (H19 Finding 2 applied: `3PM blowout trend-down hard skip` (spread_abs 8–18) retired in `build_pick_prompt()`. trend=down AND BLOWOUT_RISK=True at spread_abs 8–18 now defers to the existing trend=down step-down rule only — no hard skip. The spread_abs ≥ 19 unconditional hard skip is unchanged. `build_prompt()` (fallback) is NOT updated. Backtest evidence: H19 n=96–137, lift=1.097–1.103 — blowout_win 3PM hits at 78.8–79.2%, above 71.8% baseline. `agents/analyst.py` only.)
**Last updated (prior):** March 22, 2026 (H19 Finding 1 applied: `BLOWOUT_RISK SECONDARY SCORER SKIP` threshold raised from `spread_abs > 8` to `spread_abs ≥ 15` in `build_pick_prompt()` only. At spread_abs 8–14, secondary scorers now receive the standard BLOWOUT_RISK confidence penalty only — no hard skip. `build_prompt()` (fallback) is NOT updated. Backtest evidence: H19 n=140, lift=1.083 — secondary scorers at spread_abs 8–14 hit PTS props at 80.7%, above baseline. `agents/analyst.py` only.)
**Last updated (prior):** March 22, 2026 (H20 backtest `--mode losing-side-ast` added to `agents/backtest.py`; tests underdog spread_abs ≥ 10 AST suppression; NO_SIGNAL verdict — underdog_10plus 75.9% vs 74.1% baseline, lift=1.024; rule NOT shipped. `WITHOUT-STAR BASELINE — TWO REQUIRED GATES` block added to `build_pick_prompt()` in `analyst.py` between RETURN FROM INJURY and MINUTES FLOOR sections. Gate 1 (Confirmed-OUT): Without-Star baseline may only be the primary tier qualifier when the star is confirmed OUT in today's injury report — QUES/GTD/PROBABLE triggers fallback to standard shared-lineup baseline, skip if no standard tier qualifies. Gate 2 (Minimum Sample): n < 10 games → Without-Star data is supplementary only, cannot be sole qualifying path. Both gates must pass independently. `build_prompt()` (fallback) is NOT updated. Motivated by LeBron PTS T15 miss on 2026-03-21: Luka listed QUES, Without-Luka n=6 used as primary qualifier, auditor classified model_gap_rule.)
**Last updated (prior):** March 22, 2026 (`build_pick_prompt()` in `analyst.py` now contains a `WITHOUT-STAR BASELINE — TWO REQUIRED GATES` block inserted between RETURN FROM INJURY and MINUTES FLOOR sections. Gate 1 (Confirmed-OUT): Without-Star baseline may only be the primary tier qualifier when the star is confirmed OUT in today's injury report — QUES/GTD/PROBABLE triggers fallback to standard shared-lineup baseline, skip if no standard tier qualifies. Gate 2 (Minimum Sample): n < 10 games → Without-Star data is supplementary only, cannot be sole qualifying path. Both gates must pass independently. `build_prompt()` (fallback) is NOT updated. Motivated by LeBron PTS T15 miss on 2026-03-21: Luka listed QUES, Without-Luka n=6 used as primary qualifier, auditor classified model_gap_rule.)
**Last updated (prior):** March 21, 2026 (Three `analyst.py` runtime bugs fixed: (1) `SCOUT_OMITTED_JSON` module-level constant referenced `TODAY_STR` before it was defined — NameError on import; moved below `TODAY_STR` block. (2) `build_review_context()` line 3217: `(s.get("bounce_back") or {}).get(prop, {})` returns `None` when the key exists but its value is `None` — `.get(prop, default)` only fires when key is absent; fixed with `or {}` after `.get(prop)`. (3) `build_review_context()` line 3205: `volatility[prop]` is a dict `{label, sigma, n}` not a string — was doing `.get(prop, "unknown")` and embedding the raw dict in the review card; fixed with `((s.get("volatility") or {}).get(prop) or {}).get("label", "unknown")`. `call_scout()` return type annotation corrected to `tuple[list[dict] | None, list[dict]]`.)
Session 7 continued: Two analyst prompt bug fixes applied to both `build_prompt()` and `build_pick_prompt()`: (1) BLOWOUT_RISK secondary scorer skip direction corrected — rule body said "large underdog (spread of +8 or worse)" which was inverted; fixed to BLOWOUT_RISK=True (favored side only) with explicit CRITICAL DIRECTION CHECK; (2) New 3PM extreme blowout hard skip — BLOWOUT_RISK=True AND spread_abs ≥ 19 → skip all 3PM regardless of trend direction (including trend=up); additive to existing trend=down rule; reuses `3pm_blowout_trend_down` skip_reason. Auto-review badge rendering bug fixed — `build_site.py` replaced `auto_review_keys` set with `review_lookup` dict; game-time annotation loop now attaches `human_verdict`, `trim_reasons`, `auto_reviewed` directly to pick objects so JS badge logic has the fields it needs. Scout omitted block persisted to `data/scout_omitted_YYYY-MM-DD.json` via `save_scout_omitted()`. Teammate absence splits: `compute_teammate_absence_splits()` in `quant.py`, `Without [X]` line in `build_quant_context()`, `KEY RULES — TEAMMATE ABSENCE USAGE ABSORPTION` in `build_pick_prompt()` only. Session 7: Review Agent — adversarial pick stress-test as Stage 3 of analyst pipeline. Four new functions: `build_review_context()`, `build_review_prompt()`, `call_review()`, `apply_review_flags()`. Writes `data/picks_review_YYYY-MM-DD.json` in existing schema. Manual review files take priority. Non-fatal failure. `build_site.py` auto-review badges (`🤖 Auto-Review` / `🤖 Stay Away`). `analyst.yml` commits picks_review files. Session 6: Scout → Pick two-stage analyst pipeline. Replaced single-call analyst with two-stage LLM pipeline: Scout (context-heavy, no rules, shortlist 20–25 players) → Pick (rules-heavy, filtered quant context, shortlisted players only). `SCOUT_MAX_TOKENS = 4096`, `build_scout_prompt()`, `call_scout()`, `build_pick_prompt()` added; `main()` refactored with fallback to original single-call path if Scout fails or <5 players match. Scout uses Opus on large slates, Sonnet otherwise; Pick always Sonnet. All legacy functions preserved byte-for-byte. Output schemas unchanged. Session 5: Six targeted analyst.py prompt fixes — all prompt-only, no quant/schema/workflow changes. (1) JSON repair layer in `call_analyst()` — `_repair_json()` two-step fallback (json_repair lib + char sanitization) before sys.exit(1); `json-repair` added to analyst.yml pip install. (2) Three prompt rules (2026-03-17): `volatile_ast_t6` hard skip in VOLATILITY block, 3PM confidence ceiling at 80% at end of SEQUENTIAL GAME CONTEXT block, VOLATILE neutralizes absence-driven upside in VOLATILITY block. (3) Four prompt rules (2026-03-18): elite scorer blowout exemption capped at spread_abs < 15, VOLATILE + AST >= T6 hard SKIP in AST rules block, iron_floor B2B road gate for non-primary BHs (AST < 6.0), 3PM top_pick requires iron_floor + 80% cap. (4) fg_margin_thin redesign: full step-down cascade T20→T15→T10 before skipping; `fg_margin_thin_no_valid_tier` retired → `fg_margin_thin_tier_step`. (5) T25 blowout hard skip + 3PM 75% floor: `PTS T25 BLOWOUT HARD SKIP` in TIER CEILING RULES (spread_abs >= 15, favored side = hard skip T25/T30, `blowout_t25_skip`); `3PM CONFIDENCE FLOOR` in SELECTION RULES (75% minimum for 3PM, no skip record needed). (6) filter_self_skip_picks: 7 named hard-gate patterns added to SKIP_CONCLUSIONS (16 total) — `HARD GATE FIRES`, `BLOWOUT_SECONDARY_SCORER SKIP fires`, named rule skip phrases, `mandatory skip`, `Record as skip`. Session 4: Session 3: Opportunity Flags overhaul — per-player card collapse, `qualifying_tiers`/`upgrade_tiers` schema, upgrade card design, absent player self-exclusion guard, dedup by `name_lower` only, `card_type` ("new_pick"/"upgrade"/"mixed"). Picks Review integration — `human_verdict`/`trim_reasons` tagging in `auditor.py` via `load_picks_review()`+`apply_human_verdicts()`, `human_flag_precision` block in `audit_summary.json`, parlay `trim`/`manual_skip` guard in `parlay.py`, `⚠ Caution`/`⚠ Flagged` frontend review badges in `build_site.py`. Also: analyst meta-framework for rule conflicts, leaderboard injection, `reconcile_pick_values` hardening + elite scorer blowout exemption, floor gate skip enforcement, return-from-injury SHORT_SAMPLE rule, voided pick grading fix, whitelisted teammates grounding, `lineup_update.py` comprehensive overhaul, 3PM blowout hard skip, parlay one-player-per-card cap, T2 REB deprecation.
Session 2: Analyst-driven Top Picks — `top_pick` field in picks schema, `## TOP PICKS` prompt section, `get_top_picks()` flag-first with 85%+ fallback; Results tab redesigned to 3 stat cards + Props card + chart + drawers; `load_yesterday_summary()` + `AUDIT_SUMMARY_JSON`; post_game_reporter.py Bug Fixes — `result=="MISS"` filter fix, `espn_fetch_ok` scoping fix. Session 1: M2 Defensive Recency Split complete — `compute_opp_defense_recency()`,
`def_recency` field in player_stats.json, `DEF↑`/`DEF↓` header annotation, annotation-only.
March 11 additions: P6 Skip Validation System, P7 Team Momentum Indicator, three analyst prompt
rule hardenings, Post-Game Reporter Brave Search web narrative layer. March 10: P5 Lineup Update
Agent complete, Rotowire session login + proj_min/USG_SPIKE/OPP annotations, knowledge staleness
awareness block, analyst Opus hybrid.)

---

## Mental Model: Data Flow

```
player_game_log.csv + team_game_log.csv + nba_master.csv
    ↓ quant.py
player_stats.json          (one entry per whitelisted player playing today)
team_defense_narratives.json  (per-team last-15g PPG allowed + rank, auto-generated daily)
    ↓ pre_game_reporter.py → pre_game_news.json
         player_notes, game_notes (Claude-summarised ESPN news)
         suggested_context_updates (Claude conflict flags)
         staleness_flags (deterministic date-based stale fact flags — Pass 1, no LLM)
    ↓ analyst.py (two-stage Scout → Pick pipeline, with single-call fallback)
         reads lineups_today.json (written by rotowire_injuries_only.py, refreshed at analyst start)
         lineups_today.json optionally contains projected_minutes + onoff_usage per team (when Rotowire creds present)
         load_lineup_context() builds per-team lookup → proj_min/USG_SPIKE/OPP annotations in quant context blocks
         calls write_analyst_snapshot() → stores snapshot_at_analyst_run in lineups_today.json
         OUT/DOUBTFUL pre-filter applied to player_stats before prompt building
         Stage 1 — Scout: all context (quant, logs, news, lineups, profiles, leaderboard), no rules → shortlist 20–25 players
         Stage 2 — Pick: shortlisted quant context + full rulebook + audit feedback → picks + skips
         Fallback: if Scout fails or <5 shortlisted players match quant stats → original single-call build_prompt() path
         → picks.json (appended, result=null until auditor runs)
    ↓ parlay.py                → parlays.json (appended; OUT/DOUBTFUL excluded)
    ↓ lineup_watch.py          → picks.json (injury_status_at_check + voided/risk fields, hourly)
    ↓ lineup_update.py         → picks.json (lineup_update sub-object on affected picks, hourly)
                               → opportunity_flags.json (teammate suggestions when qualifying absence detected, hourly)

    ↓ post_game_reporter.py    → post_game_news.json (ESPN exit/DNP news for yesterday's picks)
    ↓ picks_review_YYYY-MM-DD.json (human-produced, committed before auditor.yml runs — see below)
    ↓ auditor.py (next morning)
picks.json + parlays.json  (result fields filled; human_verdict + trim_reasons tagged from review file)
audit_log.json + audit_summary.json  (written; human_flag_precision block in audit_summary)
    ↓ build_site.py
site/index.html  (deployed to GitHub Pages)
```

Quant runs twice per day: once in `ingest.yml` (for freshness after box scores land), once at
the start of `analyst.yml` (to ensure the analyst sees today's correct data). This is intentional.

`rotowire_injuries_only.py` runs at the START of `analyst.yml` (before quant re-run) to ensure
injuries and lineups are fresh before picks are generated.

---

## Current `player_stats.json` Schema (all keys, in order)

```
team, whitelisted_teammates,  ← sorted list of other active whitelisted players on same team playing today; [] when none
opponent, games_available, last_updated,
on_back_to_back,   ← player-level (2026-03-15): True only if team in b2b_teams AND player's most recent game_date == yesterday; rested players (OUT/load mgmt yesterday) get False even if team played
rest_days, games_last_7, dense_schedule,
b2b_hit_rates, today_spread, spread_abs, blowout_risk,
tier_hit_rates, matchup_tier_hit_rates, spread_split_hit_rates,
best_tiers, trend, home_away_splits,
minutes_trend, avg_minutes_last5, minutes_floor,   ← {floor_minutes, avg_minutes, n}; null if <5 games
raw_avgs,
opp_defense,          ← team-level, kept for auditor context injection
game_pace, teammate_correlations,
bounce_back,          ← player-level post-miss profiles + iron_floor + miss anatomy fields
volatility,           ← {PTS/REB/AST/3PM: {label, sigma, n}}
positional_dvp,       ← {position, pts_rating, reb_rating, ast_rating, tpm_rating, n, source}
ft_safety_margin,     ← {label, margin, breakeven_fg_pct, season_fg_pct, n}; null if insufficient FT data
team_momentum,        ← {team: {l10_wins, l10_losses, l10_pct, l10_margin, tag}, opponent: {...}}; null if no data
def_recency,          ← "soft" | "tough" | null — opponent's L5 vs L15 PTS allowed divergence; null when <3 L5 games or within threshold
shooting_regression,  ← {fg_hot, fg_cold, fg_pct_l5, fg_pct_l20, n_l5, n_l20}; null if insufficient data
profile_narrative,    ← string or null; live portrait for ≥10 non-DNP games + qualifying PTS best tier
key_teammate_absent   ← {teammate_name, teammate_avg_pts, n_games, raw_avgs, tier_hit_rates, absence_trend} or null (added 2026-03-20/25); absence_trend is per-stat {PTS/REB/AST/3PM: "up"|"stable"|"down"} dict computed as L5 vs full absence-window mean; empty {} when n_games < TREND_SHORT_WINDOW (5); top-level trend dict is overridden with these values in build_player_stats() when key teammate is absent and absence_trend non-empty — prevents regime-crossing artifact; null when <3 without-teammate games
```

`opp_defense` is still written to `player_stats.json` even though the analyst no longer reads
`opp_today=` from the quant context block — the auditor reads quant context from pick object
fields directly (not from `player_stats.json`), but `opp_defense` remains for other consumers.

`bounce_back` per-stat fields: `{post_miss_hit_rate, lift, iron_floor, n_misses,
near_miss_rate, blowup_rate, typical_miss}`. The Miss Anatomy fields (`near_miss_rate`,
`blowup_rate`, `typical_miss`) are null when fewer than 5 misses — they feed Player Profiles
conditional rendering. Analyst wiring for directive rules is **deferred** pending backtest.

---

## Current Quant Context Block Format (what the Analyst actually sees per player)

```
Jalen Brunson (vs BOS | spread_abs=5.5 rest=1d L7:4g proj_min=34 [USG_SPIKE:+7.2pp vs J.Holiday] DEF↑):
  ⚠ OPP: Jayson Tatum OUT (proj=0min)
  DvP [PG]: PTS=soft REB=mid AST=tough 3PM=soft (n=52)
  Momentum — NYK: 7-3 L10 avg_margin=+5.2 [hot] | BOS: 4-6 L10 avg_margin=-1.8
  PTS: tier=25 overall=80% vs_soft=85%(14g) vs_tough=62%(11g) competitive=79%(18g) blowout_games=71%(7g) trend=up bb_lift=1.18(6miss) [consistent]
  AST: tier=6 overall=72% vs_soft=n/a vs_tough=68%(11g) competitive=74%(18g) blowout_games=n/a trend=stable [VOLATILE]
```

**Header flags:** `B2B`, `rest=Xd`, `DENSE`, `L7:Xg`, `BLOWOUT_RISK=True`, `spread={signed:+.1f}(abs={abs:.1f})` — negative = this team favored, positive = underdog (2026-03-25: replaces bare `spread_abs=X.X`; falls back to `spread_abs=X.X` when signed value unavailable), `proj_min=N` (Rotowire projected minutes, when creds present), `[USG_SPIKE:+N.Npp vs X.Name]` (usage spike ≥5pp + ≥100 min sample, when creds present), `DEF↑` (opponent defense trending soft — L5 ≥8% above L15 PTS allowed), `DEF↓` (opponent defense trending tough — L5 ≥8% below L15 PTS allowed); omitted when neutral or insufficient data
**After DvP line (optional):** `Momentum —` line showing L10 W-L record, avg point margin, and hot/cold tag for the player's team and opponent; omitted when neither team's momentum can be computed; "neutral" tag teams show no tag (only [hot] and [cold] labelled)
**After Momentum line (optional):** `Teammates (active/whitelisted): Name1, Name2` — other active whitelisted players on the same team playing today; omitted when none; used to ground Analyst teammate references and prevent stale training knowledge hallucinations
**After Teammates line (optional):** `⚠ OPP: Name OUT (proj=0min)` — opponent player with 0 projected minutes per Rotowire; capped at 3 entries; only emitted when Rotowire creds present
**DvP line:** one per player (not per stat), covers all 4 stats, shows `(team-lvl)` tag when
the positional sample had < 10 games. `n=` is the number of player-game observations.
**Stat line fields (in order):** `tier` · `overall` · `vs_soft` · `vs_tough` · `competitive` ·
`blowout_games` · `trend` · `b2b=` (only when B2B) · `bb_lift=` or `[iron_floor]` · `[VOLATILE]` or `[consistent]`
**PTS stat line may also show:** `[FG_HOT:+X%]` or `[FG_COLD:−X%]` (shooting regression flag)

---

## Current `build_prompt()` Section Order

1. Task framing:
   - `Today is {TODAY_STR}.`
   - `## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE` — epistemic calibration block; distinguishes perishable knowledge (player roles, rosters, team systems, H2H history, season narratives — do NOT rely on training data) from durable knowledge (basketball principles, tier logic, role archetype reasoning — apply freely); instructs Claude to trust injected data over training priors on any named-player or named-team fact
   - `## YOUR TASK` + tier system intro
2. Hit definition (`>=`, exact match = HIT)
3. Tier ceiling rules with backtest evidence (REB T8+, AST T6+, PTS T25+, PTS T30 invalid)
4. `## TODAY'S GAMES` (JSON array)
5. `## CURRENT INJURY REPORT` (filtered to today's teams only)
5a. `## PROJECTED LINEUPS` (from `lineups_today.json`; freshness-checked vs TODAY_STR; fallback "unavailable" line if missing or stale)
6. `## PRE-GAME NEWS` (conditional — only injected when `pre_game_news.json` has content; critical context flags prepended with ⚠ warning)
7. `## SEASON CONTEXT` (SEASON FACTS only — `## TEAM DEFENSIVE PROFILES` section is stripped from the file at load time; manually maintained)
8. `## PLAYOFF PICTURE` — auto-generated from `data/standings_today.json` (bucketed: safe / contending / playin / bubble / eliminated)
8a. `## WHITELISTED PLAYER RANKINGS — SEASON vs L20` — built by `build_player_leaderboard()` from already-loaded `game_log`; top 15 per stat (PTS/REB/AST/3PM), season avg + L20 avg with ↑/↓/→ arrow (±3 rank threshold); injected between PLAYOFF PICTURE and TEAM DEFENSIVE PROFILES; "" on any exception
9. `## TEAM DEFENSIVE PROFILES` — auto-generated from `data/team_defense_narratives.json` (last 15g PPG allowed + rank, updates daily via quant.py)
10. `## PLAYER RECENT GAME LOGS` (last 10 games per whitelisted player)
11. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS`
    - **KEY FRAMEWORK — HOW TO REASON WHEN RULES CONFLICT** (inserted before all KEY RULES blocks): 5-level priority order (hard skips → mandatory tier steps → confidence penalties → caps → positive signals); PENALTY STACK LIMIT (>3 independent penalties → re-examine or skip; B2B + DENSE double-counting example); TIER_WALK FORMAT standard (✓ marks, step notation, clean confidence chain, no skip conclusions in emitted picks); SANITY CHECK 4-point gate (tier vs. actual floor, honest confidence, self-skip consistency, smell test); ON COMPLEX SLATES (evaluate independently, quality over volume); PLAYER TIER CONTEXT (leaderboard as ground truth for elite status, anchors 27.0 PPG exemption); CONFIDENCE THRESHOLD IS A FLOOR, NOT A TARGET (no rounding up from sub-70% assessment)
    - KEY RULES — MATCHUP QUALITY (DvP + vs_soft/vs_tough interaction)
    - OPPONENT DEFENSE — POSITIONAL DvP (stat-specific rules, REB/3PM exclusions)
    - SELECTION RULES (offensive-first REB floor rule, tier ceiling conditions, tier walk-down discipline; **LINEUP CONTEXT** rule — use ## PROJECTED LINEUPS as ground truth for who is playing)
    - KEY RULES — REST & FATIGUE (B2B, DENSE, rest_days; **RETURN FROM INJURY — SHORT SAMPLE INSTABILITY** for `[SHORT_SAMPLE:Ng]` players: mandatory REB/AST one-tier step-down, PTS -5% + no T20+ unless ≥7 games)
    - KEY RULES — SEQUENTIAL GAME CONTEXT (REB slump-persistent, 3PM cold streak, **3PM trend=down mandatory step-down**; **3PM blowout hard skip** — trend=down AND BLOWOUT_RISK=True → skip all 3PM; **3PM extreme blowout hard skip** — BLOWOUT_RISK=True AND spread_abs ≥ 19 → skip all 3PM regardless of trend direction)
    - KEY RULES — SPREAD / BLOWOUT RISK (BLOWOUT_RISK flag, spread_abs > 13 cap; **BLOWOUT_RISK secondary scorer skip for FAVORED players** — BLOWOUT_RISK=True on the player's own team → skip non-primary scorer PTS; CRITICAL DIRECTION CHECK: does NOT apply to underdog players; ELITE SCORER BLOWOUT EXEMPTION for raw_avgs PTS ≥ 27.0; **ROAD UNDERDOG NEAR-THRESHOLD PTS PENALTY** — away team + spread_abs 4–7 (underdog) + raw_avgs PTS − pick_value ≤ 5 → -5% confidence; iron_floor exempt; added 2026-03-26)
    - KEY RULES — VOLATILITY (−5% for VOLATILE, Top Pick gate, iron_floor override)
    - KEY RULES — HIGH CONFIDENCE GATE 81%+ (Conditions A/B/C)
    - INJURY EXCLUSION (HARD RULE) — players removed from quant context by Python pre-filter; do not pick any player absent from ## QUANT STATS
    - `{quant_context}` — the per-player blocks
12. `## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS` (from `profile_narrative` fields in `player_stats.json`)
13. `## AUDITOR FEEDBACK FROM PREVIOUS DAYS` (last 5 entries)
14. `## ROLLING PERFORMANCE SUMMARY` (from `audit_summary.json`, blank < 3 days)
15. `## ANALYSIS APPROACH` (3-line per-player reasoning format)
16. `## OUTPUT FORMAT` (strict JSON schema — includes `tier_walk` and `iron_floor` fields)

**Hard gates enforced in Python before prompt building (not just in prompt rules):**
- OUT/DOUBTFUL players removed from `player_stats` dict via `load_out_players()` — Claude never sees their stats
- Same filter applied in `parlay.py` `load_todays_picks()` — cannot appear in parlay legs
- `min_floor confidence cap` — PTS pick with `floor_minutes < 24` → confidence capped at 84%
- `BLOWOUT_RISK secondary scorer skip` — BLOWOUT_RISK=True (player's team is the heavily FAVORED side) AND spread_abs ≥ 15 AND non-primary scorer → PTS pick skipped (`blowout_secondary_scorer`). **Direction corrected 2026-03-20.** **Threshold raised 2026-03-22:** narrowed from spread_abs > 8 to spread_abs ≥ 15 in `build_pick_prompt()` only (`build_prompt()` fallback unchanged). At spread_abs 8–14, standard BLOWOUT_RISK confidence penalty applies instead of a hard skip — H19 backtest (n=140, lift=1.083) showed secondary scorers hit at 80.7% in that range. Prompt-only — no Python change.
- `AST T4+ hard gate` — PF/C or raw_avgs AST < 4.0 → opponent AST DvP must be "soft"; skip on mid/tough. **Exception (2026-03-15):** players with raw_avgs AST ≥ 8.0 APG are exempt — elite playmaker profile, gate not designed for this case (e.g. Jokic). Prompt-only — no Python change.
- `reb_floor_skip` — pick_value must be strictly below 3rd-lowest L10 REB value; exact match = skip. **Exception (2026-03-15):** T4 (minimum valid tier) is exempt from the exact-match gate — no lower tier to step to; validate on hit rate merit alone. Gate fires normally for pick_value ≥ 6. Prompt-only — no Python change.
- `3PM hard skip` — trend=down AND avg_minutes_last5 ≤ 30 → skip all 3PM picks including T1
- `3PM blowout hard skip` (March 14, 2026) — trend=down AND BLOWOUT_RISK=True → skip all 3PM including T1; overrides [iron_floor] (prompt rule only; no Python pre-filter). **RETIRED for spread_abs 8–18 (2026-03-22, H19 Finding 2)** — in `build_pick_prompt()` only, this hard skip is replaced with a note deferring to the trend=down step-down rule. `build_prompt()` fallback retains original behavior unchanged.
- `3PM extreme blowout hard skip` (March 20, 2026) — BLOWOUT_RISK=True AND spread_abs ≥ 19 → skip all 3PM for ALL players on favored team regardless of trend direction; reuses `3pm_blowout_trend_down` skip_reason (prompt rule only; no Python pre-filter). **Unchanged — still active.**

**Parlay concentration cap:** max 1 parlay per player per day (March 14, 2026 — tightened from 2). Enforced in `enforce_concentration_cap()` (`> 1` threshold) and `build_parlay_prompt()` AVOID section.

---

## Key Design Decisions (and why)

**Why two whitelist load functions?**
`load_whitelist()` returns a `set` of `(name_lower, team_upper)` tuples — used in three places
for DataFrame mask filtering. Changing the return type would break all three callers. Instead,
`load_whitelist_positions()` returns a separate `{name_lower: position}` dict used only by the
new positional DvP code. Zero risk to existing filtering logic.

**Why is `player_games` sorted ascending before passing to `compute_volatility()`?**
`grp` in `build_player_stats()` is always sorted newest→oldest (the `grp.sort_values("game_date",
ascending=False)` at line ~967). If you called `.to_dict("records")` directly, `played[-window:]`
would return the *oldest* 20 games. The ascending sort at the call site ensures `[-window:]`
correctly yields the most recent games.

**Why does `opp_defense_rating` still appear in `picks.json` output schema?**
The analyst prompt's OUTPUT FORMAT section still asks for `"opp_defense_rating"` in each pick.
The Analyst derives this from the DvP line's PTS rating (since the prompt removed `opp_today=`
from stat lines, the DvP PTS rating is the closest proxy). This field is used by `build_site.py`
for defense pills on pick cards. A future cleanup could rename it to `dvp_pts_rating`.

**Why is the tier walk-down taught by example in the prompt instead of rules?**
Backtesting showed the system was picking based on raw averages rather than tier hit rates.
An explicit worked example (PTS: check ≥20 → 40% → skip; check ≥15 → 80% → pick) was more
effective than abstract rules at anchoring Claude to the right selection logic.

**Why does Quant NOT run LLM calls?**
All signal is pre-computed deterministically. This keeps cost at zero for the heaviest compute
step, makes debugging trivial (inspect the JSON), and separates concerns cleanly. The LLM only
runs in analyst, parlay, auditor, and lineup_update.

**Why does positional DvP rank *within position groups* rather than globally?**
A PG averaging 18 pts/game against a team is not directly comparable to a C averaging 18 pts.
Ranking teams separately within each position group (all PG allowed averages ranked against each
other across 30 teams) gives a meaningful "soft/mid/tough for PGs" label. Global ranking would
mix apples and oranges.

**Why is there a 10-game minimum for positional DvP cells?**
With only ~12 whitelisted players per position across 30 teams, some cells will have very few
observations early in a season. Below 10, the variance is too high to trust the rating — the
system falls back to team-level gracefully and marks `source: "team_fallback"`.

**Why does the auditor read quant context from pick object fields rather than player_stats.json?**
The auditor runs the morning after picks are made. `player_stats.json` is overwritten by quant
each day — if the auditor read it, it would see today's (not yesterday's) quant context, which
is wrong. `load_player_stats_for_audit()` was removed (March 8) to eliminate this confabulation
bug. The auditor now reads `reasoning`, `hit_rate_display`, `tier_walk`, `opponent` directly
from each pick object — fields that were written at pick time.

**Why was `PLAYER_WINDOW` raised from 10 to 20?**
Backtest 2 showed w20 improved REB T8 by +7.8pp (to 71.0%), crossing the 70% threshold that
makes it a valid pick. The tradeoff was ~25% fewer total selections — estimated ≥8 picks/day on
typical slates, above the parlay minimum.

**Why does `build_team_defense_narratives()` omit perimeter and pace clauses?**
The current `team_game_log.csv` schema lacks `fg3_pct_allowed` and `possessions` columns.
`build_team_defense_narratives()` checks `has_3p` and `has_pace` boolean flags at runtime and
omits those clauses when the columns are absent. All 30 teams still get the PPG rank line. The
function is structured to add these clauses automatically if/when the schema expands.

**Why do staleness flags go into both `data/context_flags.md` AND `pre_game_news.json`?**
`context_flags.md` is a human-readable daily report for manual review. `pre_game_news.json`
carries the same flags structured as a list under `"staleness_flags"` for programmatic access
if needed. The analyst reads `pre_game_news.json` (via `load_pre_game_news()`) — not the .md
file directly — so both formats serve different consumers.

**Why is `data/context_flags.md` NOT in `context/context_flags.md`?**
The `CONTEXT_FLAGS_MD = DATA / "context_flags.md"` constant was established when the file was
first created. The flags file lives in `data/`, not `context/`. `analyst.py` reads flags via
`load_pre_game_news()` which reads `pre_game_news.json` — the `.md` file is human-readable only.

**Why does `lineup_update.py` use `snapshot_at_analyst_run` rather than the previous hourly cycle?**
The comparison baseline must be "what was true when picks were made," not "what was true an hour
ago." If the previous cycle is used, a change that happened before the first hourly run would
never appear as a change. Using the morning snapshot means every hourly run independently compares
against the same ground truth — and `direction=unchanged` is still written as audit evidence.

**Why does `lineup_update.py` overwrite the `lineup_update` sub-object each run?**
The latest Claude assessment is always the most current. Writing idempotently means the frontend
always shows the most recent reasoning without needing to track "has this been processed" state.
Original morning fields (`confidence_pct`, `reasoning`, `pick_value`, `tier_walk`) are never
touched — the sub-object is additive, not destructive.

---

## Key Backtest Verdicts (applied to production)

| Signal | Verdict | Applied |
|--------|---------|---------|
| Trend (L5 vs L20) | Noise for PTS/REB/3PM; weak for AST | Data shown, not directive |
| Home/away | Noise | Data shown, not directive |
| Opp defense (team-level) | Noise for REB, noise for 3PM, weak for PTS/AST | REB/3PM excluded in prompt |
| B2B (aggregate) | Noise (directionally −3%) | Quantified per-player instead |
| Bounce-back (league-wide) | Slump-persistent (lift=0.89); REB worst (lift=0.83) | Player-level profiles instead |
| Player-level bounce-back | Strong for specific combos (16 iron-floor) | bb_lift + iron_floor in context |
| 3PM cold streak (severe) | Decline: 68.3% next game (lift=0.87, n=161) | −5% confidence or skip rule |
| Mean reversion (cold streaks) | Null for PTS/REB/AST; decline for 3PM | 3PM rule only |
| Recency decay weighting | Marginal (+2.1pp over 31 days) | Not applied |
| PTS T20 | 69.6% at w20 (borderline concern) | Ceiling rule in prompt |
| REB T8 | 63.2%(w10) → 71.0%(w20) | Requires w20 to be valid |
| AST T6 | 65.1% — below threshold | Ceiling rule in prompt |
| 3PM T2 | 71.4%(w10) → 77.3%(w20) | Valid pick tier |
| Post-blowout bounce-back (H6) | NOISE — lift 0.955–0.988 across all stats | Closed March 7, 2026 |
| Opponent schedule fatigue (H7) | NOISE — opp B2B lift 0.977–1.025; dense=0 instances | Closed March 7, 2026 |
| Positional DvP (H8) | REVERT — lift_advantage negative for PTS/REB/AST (−0.051/−0.052/−0.060); 3PM KEEP (+0.106) but 3PM DvP already excluded from prompt. Team-level opp defense outperforms positional splits — position-splitting dilutes cell sizes and flattens signal. | Prompt cleanup pending; `DvP [POS]` annotation line to be removed; implementation is currently annotation-only so no picks at risk |
| Opponent team hit rate (H15) | **Second run complete (March 22, n=538):** HOU confirmed system-wide suppressor (61.9%, n=21, −23.4pp). MIN×AST at 55.6% (n=9, −29.5pp) — active scrutiny, below formal ≥15 gate. SAS floor compression (n=6, mean −5.0). CHI/BOS amplifiers (95%+) are small-sample noise (n=5–11). `nba_season_context.md` updated: HOU suppressor note added, MIN×AST upgraded to active scrutiny, SAS note updated. Re-run at ≥600 picks (end of season). | HOU note in season context; watch MIN×AST for ≥15 picks |

---

## Live Agent Function Inventory (non-obvious additions only)

### `quant.py`
- `load_whitelist()` → `set` of `(name_lower, team_upper)` tuples — **updated 2026-03-25**: uses iterrows loop emitting tuples for BOTH `team_abbr` (standard NBA) AND `team_abbr_alt` (ESPN short abbrev) when alt is non-empty; fixes 10 players invisible since launch (SAS/SA, NYK/NY, GSW/GS, UTA/UTAH); DO NOT revert to set-comprehension pattern (would break alt-abbrev matching again)
- `load_whitelist_positions()` → `{name_lower: position}` — new, used only by positional DvP
- `_ordinal(n)` → `str` — converts int to ordinal string (`1→"1st"`, `11→"11th"`, `21→"21st"`); handles 11th/12th/13th exception
- `compute_tier_hit_rates(games_df, stat)` → `{str(tier): float}` — uses `>=` grading
- `compute_volatility(game_log_list, stat, tier, window=20)` → `{label, sigma, n}` — takes records NOT DataFrame; must be sorted oldest→newest at call site
- `compute_matchup_tier_hit_rates(all_games_df, opp_defense_dict, stat)` → matchup splits
- `compute_spread_split_hit_rates(player_log_df, game_spreads_dict, stat)` → competitive/blowout splits
- `compute_b2b_hit_rates(player_log_df, b2b_game_ids_dict, stat)` → B2B tier hit rates
- `compute_positional_dvp(player_log_df, position_map_dict)` → `{team: {position: {avgs + ratings}}}`
- `compute_shooting_regression(grp)` → `{fg_hot, fg_cold, fg_pct_l5, fg_pct_l20, n_l5, n_l20}` — P3 feature; ±8% threshold for HOT/COLD flag
- `compute_ft_safety_margin(grp)` → `{label, margin, breakeven_fg_pct, season_fg_pct, n}` — H11 feature; null if insufficient FT data
- `compute_minutes_floor(grp, window=10)` → `{floor_minutes, avg_minutes, n}` or `None` — lower bound on expected minutes
- `build_bounce_back_profiles(player_log_df, whitelist_set)` → `{player: {stat: {post_miss_hit_rate, lift, iron_floor, n_misses, near_miss_rate, blowup_rate, typical_miss}}}`
- `build_team_defense_narratives(team_log)` → `dict[str, str]`; writes `data/team_defense_narratives.json`; one auto-generated narrative per team (PPG allowed + rank + perimeter/pace clauses when columns available)
- `build_player_profiles(player_stats_dict)` → mutates `profile_narrative` key in-place for each player meeting eligibility; called at end of `main()` after `build_player_stats()` writes the JSON
- `build_team_momentum(master_df, teams_today) → dict[str, dict]` — computes L10 W-L record, avg point margin, and hot (≥7W) / cold (≤3W) / neutral tag for each team in `teams_today`; uses completed games only (both scores present, date < TODAY_STR); returns `{}` if master_df is None/empty; tag is always one of "hot"/"cold"/"neutral"
- `compute_opp_defense_recency(team_log) → dict[str, str | None]` — one entry per team appearing as opponent today; value is `"soft"` (L5 PTS-allowed ≥8% above L15), `"tough"` (L5 ≥8% below L15), or `None` (neutral / insufficient data); requires `n_l15 ≥ 3` and `n_l5 ≥ DEF_RECENCY_MIN_L5 (3)` to compute; mirrors `build_opp_defense()` self-join pattern
- `compute_teammate_absence_splits(player_log, player_name, team, whitelist)` → `{teammate_name, teammate_avg_pts, n_games, raw_avgs, tier_hit_rates, absence_trend}` or `None` — computes player's raw avgs and tier hit rates in games where their top-PPG whitelisted teammate was absent (min 3 qualifying games); stored as `key_teammate_absent` field in `player_stats.json`; used by `build_quant_context()` to emit `Without [X]` line; added 2026-03-20. **`absence_trend` field (added 2026-03-25):** per-stat `up/stable/down` dict computed as L5 vs full absence-window mean (same logic as `compute_trend()` but scoped to absence regime only); only populated when `n_games >= TREND_SHORT_WINDOW` (5); empty dict `{}` otherwise. `build_player_stats()` overrides the top-level `trend` dict with `absence_trend` values **only when the key teammate is confirmed OUT or OFS in `injuries_today.json`** (activation guard added 2026-03-25). If the teammate is healthy/playing, the absence data is still written to `player_stats.json` as historical context but the trend label is not overridden. Gate condition: `_teammate_name in players_out_today`. Safe fallback: empty `players_out_today` (file missing) means override never fires.
- `load_players_out_today() → set[str]` — reads `injuries_today.json`, returns set of player names with status OUT or OFS; QUES/DOUBT/PROB/GTD excluded (those players may still play); returns empty set if file missing; added 2026-03-25
- `build_player_stats(player_log, b2b_teams, opp_defense, game_pace, todays_games, teammate_correlations, whitelist, game_spreads=None, master_df=None, b2b_game_ids=None, positional_dvp_data=None, position_map=None, team_momentum=None, opp_defense_recency=None, players_out_today=None)` → full `player_stats.json` dict

### `ingest/rotowire_injuries_only.py`
- `ROTOWIRE_LOGIN_URL` — constant for Rotowire login endpoint
- `login_rotowire(session: requests.Session) → bool` — reads `ROTOWIRE_EMAIL`/`ROTOWIRE_PASSWORD` env vars; POSTs to login URL; returns `False` (not crash) if creds missing or HTTP != 200; returns `True` when session is authenticated
- `fetch_rotowire_html(session: requests.Session | None = None) → str | None` — refactored to accept optional session; `requester = session if session is not None else requests`; backward-compatible for callers without session
- `fetch_rotowire_minutes_html(session: requests.Session) → str | None` — fetches `ROTOWIRE_MINUTES_URL` (`/basketball/projected-minutes.php`); returns raw HTML or None on error/non-200; used by `main()` to feed premium parsers from the correct page (the lineups page does not server-render those panels)
- `ROTOWIRE_MINUTES_URL = "https://www.rotowire.com/basketball/projected-minutes.php"` — constant added after `ROTOWIRE_LOGIN_URL`; this page is a separate URL from the lineups page, with different HTML structure
- `parse_rotowire_lineups(html) → dict` — **(rewritten 2026-03-25)** anchors on `data-team` attribute in On/Off Court Stats `<button>` elements (same anchor used by `parse_rotowire_injuries`); slices raw HTML between consecutive button matches to isolate each team's Expected Lineup section; walks `<li>` elements within the section looking for position labels (PG/SG/SF/PF/C) as first word; reads player names from `a_tag.get("title")` (full name, reliable) NOT from link text (may be abbreviated, e.g. "R. Hachimura"); detects inline injury status keywords (Ques/Doubt/Out/Prob/GTD etc.) from `<li>` text; deduplicates by position; returns `{team_abbr: {"starters": [{name, position, injury_status}], "confirmed": bool}}`
- `parse_projected_minutes(soup: BeautifulSoup) → dict[str, list[dict]]` — **(rewritten 2026-03-25)** parses `projected-minutes.php` (NOT the lineups page); anchors on team logo `<img>` tags with `src` matching `/100{ABBREV}.png` pattern; walks up ancestors to find containers with ≥2 player links; handles "Subscriber Exclusive" gating with `break` (skip team); tracks STARTERS/BENCH/MAY NOT PLAY/OUT section headers from NavigableString text nodes; extracts `{name, minutes, section, injury_status}` per player; deduplicates by name; returns `{}` on any exception (graceful degradation); includes health-check log: `parsed N teams, M players with minutes > 0`
- `parse_onoff_usage(soup: BeautifulSoup) → dict[str, list[dict]]` — **(rewritten 2026-03-25)** intentionally returns `{}` with diagnostic log. On/Off Court Stats data is loaded via JavaScript after a button click — not present in the server-rendered HTML fetched by `requests.get()`. A future Playwright-based implementation could populate this; see `docs/ROADMAP_offseason.md`. Function signature preserved so callers in `main()` require no changes
- `write_lineups_json(lineups, asof_date, built_at_utc, projected_minutes: dict | None = None, onoff_usage: dict | None = None)` — extended signature; merges `projected_minutes` and `onoff_usage` dicts into per-team payload before atomic write to `data/lineups_today.json`
- Guard condition in `main()`: if parsed 0 teams but existing file has teams for today, keeps existing (protects against partial scrape overwriting good data)
- Session flow in `main()`: creates `requests.Session()`; calls `login_rotowire(session)`; passes session to `fetch_rotowire_html(session)` (lineups page); when authenticated, makes a second fetch via `fetch_rotowire_minutes_html(session)` (minutes page) → builds separate `soup_minutes` for `parse_projected_minutes()` and `parse_onoff_usage()`
- Output: `data/lineups_today.json` keys: `asof_date`, `built_at_utc`, `source`, per-team dicts with `starters` + `confirmed`; optional `projected_minutes` + `onoff_usage` per team when Rotowire creds present and scrape succeeds; `snapshot_at_analyst_run` key added later by analyst.py

### `analyst.py`
- `_call_with_overload_retry(fn, max_retries=4, base_delay=10)` — retries `fn()` on `anthropic.APIStatusError` containing `overloaded_error`; exponential backoff (10s/20s/40s/80s); raises last exception if all retries exhausted; non-overload exceptions raise immediately with no retry; added 2026-03-31
- `_ABBR_NORM` dict + `_norm_team(abbr)` + `_extract_last(raw_name)` — normalization helpers (mirrors `lineup_watch.py` and `build_site.py`); `_extract_last` handles "J. Brunson" style Rotowire names
- `load_out_players() → set[tuple[str, str]]` — reads `injuries_today.json`; returns `{(last_name_lower, norm_team_upper)}` for all OUT/DOUBTFUL players; used in `main()` to pre-filter `player_stats` before any prompt building; Claude never receives stats for excluded players
- `format_lineups_section(lineups_path=LINEUPS_JSON, today_teams=None) → str` — reads `lineups_today.json`; staleness-checks `asof_date == TODAY_STR`; loads game pairings from MASTER_CSV; loads injuries for key absences; returns formatted `## PROJECTED LINEUPS` block (starters + key absences per game pair); falls back to `"[Lineup data unavailable — injury report only]"` if file missing/stale
- `write_analyst_snapshot(lineups_path, picks_run_at_iso) → None` — writes `snapshot_at_analyst_run` key into `lineups_today.json` capturing starters + confirmed flag per team at pick time; guard logic (2026-03-25 fix): refreshes if today's date differs from existing snapshot OR if existing `teams` is empty — safe to re-run within the same day, will not overwrite a valid same-day snapshot; atomic write via `.tmp` rename; called in `main()` after `format_lineups_section()`, before `build_prompt()`
- `load_player_stats()` → reads `player_stats.json`, returns dict
- `load_lineup_context() → dict[str, dict]` — reads `lineups_today.json`; staleness-checks `asof_date == TODAY_STR`; skips metadata keys (`asof_date`, `built_at_utc`, `source`, `snapshot_at_analyst_run`); builds `{norm_team: {"projected_minutes": {name_lower: {minutes, section}}, "onoff_usage": {name_lower: {usage_pct, usage_change, minutes_sample, absent_players}}}}`; returns `{}` silently if missing/stale; logs team count on success
- `build_player_leaderboard(game_log: pd.DataFrame, whitelist: set) → str` — computes season avg and L20 avg per-stat rankings for all whitelisted players (top 15 per stat, PTS/REB/AST/3PM); L20 rank shown with ↑/↓/→ arrow (±3 spot threshold); returns `## WHITELISTED PLAYER RANKINGS — SEASON vs L20` block; fully graceful — returns `""` on any exception; placed immediately before `build_quant_context()` in source; wired in `main()` as `leaderboard = build_player_leaderboard(game_log, whitelist)`; injected between PLAYOFF PICTURE and TEAM DEFENSIVE PROFILES via `leaderboard_section` variable in `build_prompt()`; added 2026-03-16
- `load_players_out_today() → set[str]` — reads `injuries_today.json`, returns full player names with OUT/OFS status; QUES/DOUBTFUL excluded; used to gate `Without [X]` context line in `build_quant_context()`; added 2026-03-26
- `build_quant_context(player_stats: dict, lineup_context: dict | None = None, players_out_today: set[str] | None = None) → str` — updated signature (2026-03-26: added `players_out_today` param); DvP line per player + stat lines with vol_tag + FG_HOT/FG_COLD; per-player annotations: `proj_min=N`, `[USG_SPIKE:+N.Npp vs X.Name]`, `⚠ OPP: Name OUT (proj=0min)` lines; `Without [X] (their avg=Ypts, n=Ng): ...` line after teammates line — **now only rendered when `teammate_name` is confirmed OUT/OFS in `players_out_today`** (gated 2026-03-26; was unconditional on `n_games ≥ 3` before)
- `load_audit_summary()` → reads `audit_summary.json`, returns "" if < 3 entries
- `load_season_context()` → reads `context/nba_season_context.md`; strips HTML comment header; **strips `## TEAM DEFENSIVE PROFILES` section** (truncates at that heading — file unchanged, only in-memory text is modified); returns "" if missing
- `load_pre_game_news()` → reads `pre_game_news.json`; formats critical flags + player_notes + game_notes + monitor flags; returns "" if no notable items
- `render_playoff_picture(standings_path=STANDINGS_JSON)` → reads `data/standings_today.json`; formats bucketed `## PLAYOFF PICTURE` string; returns fallback string if file missing/stale
- `format_team_defense_section(narratives_path=TEAM_DEFENSE_NARRATIVES_JSON)` → reads `data/team_defense_narratives.json`; validates `as_of == TODAY_STR`; returns `## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated DATE)` block sorted alphabetically; always returns non-empty string (fallback warning if file missing/stale)
- `build_prompt(games, player_context, injuries, audit_context, season_context, quant_context="", audit_summary="", pre_game_news="", player_profiles="", playoff_picture="", team_defense="", lineups_section="")` → full system prompt string; preserved as fallback path for Scout failure
- `build_scout_prompt(games, player_context, injuries, season_context, quant_context, pre_game_news, player_profiles, playoff_picture, team_defense, leaderboard, lineups_section)` → Scout stage prompt; all contextual data, NO rules; output schema: `{"slate_read": str, "shortlist": [...]}`; targets 20–25 players; added 2026-03-20. **Omitted block removed 2026-03-25** — never populated correctly (6 days of empty `[]` or sentinel); Review agent handles coverage concerns.
- `call_scout(prompt, model=MODEL) → list[dict] | None` — calls Claude for Scout shortlist; returns shortlist on success, `None` on any failure (triggers fallback); never calls `sys.exit()`; uses `SCOUT_MAX_TOKENS = 4096`; streaming API; same JSON repair pattern as `call_analyst()`; added 2026-03-20. **(Simplified 2026-03-25):** return type changed from `tuple[list[dict] | None, list[dict]]` to `list[dict] | None`; omitted extraction removed; `save_scout_omitted()` removed. **(Overload retry 2026-03-31):** streaming call wrapped with `_call_with_overload_retry()` — retries up to 4 times on `overloaded_error` (10s/20s/40s/80s exponential backoff) before falling back to single-call mode.
- `build_pick_prompt(scout_shortlist, games, injuries, quant_context, audit_context, audit_summary)` → Pick stage prompt; contains full rulebook (all KEY RULES, TIER CEILING RULES, KEY FRAMEWORK, SELECTION RULES, etc.) copied verbatim from `build_prompt()`; receives Scout shortlist as `## SCOUT SHORTLIST` section + filtered quant context (shortlisted players only); no redundant context blocks (no game logs, season context, profiles, leaderboard, lineup section); added 2026-03-20
- `build_review_context(picks, player_stats)` → compact per-pick vulnerability card string; extracts risk-relevant quant fields (volatility, B2B hit rates, blowout risk, minutes floor, bounce_back, FT safety margin, def_recency, team_momentum); one card per pick; added 2026-03-20
- `build_review_prompt(picks, review_context, audit_summary)` → Review stage prompt; adversarial stress-test framing; miss pattern extraction from audit_summary; calibration guidance (2–4 flags per typical slate); output schema: `[{player_name, team, prop_type, pick_value, verdict, vulnerability, confidence_in_flag}]`; added 2026-03-20
- `call_review(prompt, model=MODEL) → list[dict] | None` — calls Claude for Review verdicts; returns parsed list on success, `None` on any failure (non-fatal — picks already saved); never calls `sys.exit()`; max_tokens=4096; streaming API; same JSON repair pattern as `call_analyst()`; added 2026-03-20
- `apply_review_flags(verdicts, picks, review_path)` → converts Review verdicts to `picks_review_YYYY-MM-DD.json`; verdict mapping: clean→keep, concern→trim, stay_away→manual_skip; writes `source: "auto"` on every entry; skips write if file already exists (manual review priority); added 2026-03-20
- Output schema: Claude emits `{"picks": [...], "skips": [...]}` JSON object. `call_analyst()` returns `tuple[list[dict], list[dict]]` — picks and skips. Falls back to flat-array parse for robustness. **(Overload retry 2026-03-31):** streaming call wrapped with inline retry loop — retries up to 4 times on `overloaded_error` (10s/20s/40s/80s exponential backoff) before raising; `raw_chunks` reset on each retry attempt.
- Pick output fields: `date, player_name, team, opponent, home_away, prop_type, pick_value, direction, confidence_pct, hit_rate_display, trend, opp_defense_rating, tier_walk, iron_floor, top_pick, is_skip, reasoning`
- `is_skip` field: `true` when Analyst concluded skip for any reason; `false` for all genuine picks. Primary gate in `filter_self_skip_picks()` — checked before regex fallback. `save_picks()` defaults to `false` when field absent. Added 2026-03-25 to eliminate regex whack-a-mole for skip detection.
- Skip output fields: `date, player_name, team, opponent, prop_type, tier_considered, direction, skip_reason, rule_context` (rule-specific dict)
- Skip reasons: `min_floor_tier_step`, `volatile_weak_combo`, `blowout_secondary_scorer`, `3pm_trend_down_tough_dvp`, `3pm_trend_down_low_minutes`, `3pm_blowout_trend_down` (scoped exclusively to spread_abs ≥ 19 unconditional 3PM hard skip — 2026-03-25; do NOT use for penalty-driven confidence floor failures), `ast_hard_gate`, `fg_margin_thin_tier_step`, `reb_floor_skip`, `merit_below_floor` (confidence after all penalties falls below prop-type floor: 75% 3PM, 78% REB, 70% general — added 2026-03-25 to fix skip_validation table pollution), `fg_cold_tier_step`, `volatile_ast_t6`, `blowout_t25_skip`
- `volatile_weak_combo` (2026-03-26 update): **PTS props only**, triggers on VOLATILE + exactly 7/10 (70%) hit rate + T20 or higher. **(Narrowed 2026-03-26):** previously fired on `(7/10 OR 8/10) + T15+`; 8/10 removed from trigger (80% - 5% = 75%, a legitimate pick; KD T20 actual 30 and Sengun T15 actual 30 were false skips); tier threshold raised from T15 to T20 (T15–T19 VOLATILE picks with 8/10 proceed under standard -5% treatment). Do NOT apply to AST picks below T6 (governed by the VOLATILE AST skip rule). Two exceptions: **(a)** player has [iron_floor] on this stat AND trend=up; **(b)** stat is AST AND raw_avgs AST ≥ 6.0 AND [iron_floor] is true on AST — elite passers with confirmed structural floor are not weak-combo candidates. Both `build_prompt()` and `build_pick_prompt()` updated identically.
- `fg_margin_thin_no_valid_tier` RETIRED (2026-03-19) — renamed `fg_margin_thin_tier_step`; rule now applies full cascade (T20→T15→T10) before skipping. Only skips PTS when T10 also fails. 100% false skip rate on graded instances motivated the fix.
- `blowout_t25_skip` (2026-03-19): spread_abs >= 15 AND favored side → hard skip PTS T25 and T30 for ALL players (including elite scorers). No cap — pick does not emit. T20 and below still subject to existing 74% cap rule.
- **Analyst prompt rules updated 2026-03-20:** Two blowout rule fixes applied to BOTH `build_prompt()` AND `build_pick_prompt()` (any rulebook change must update both identically): (1) **BLOWOUT_RISK Secondary Scorer Skip — direction correction:** Rule body was inverted — it said "player's team is the large underdog" but BLOWOUT_RISK=True means the player's team IS the favored side. Rewritten to correctly reference BLOWOUT_RISK=True (favored side); `CRITICAL DIRECTION CHECK` paragraph added prohibiting application to underdog players. Motivated by Jalen Green PTS skip on 2026-03-19 (PHX +9.5 underdog — rule misfired on wrong team). `BLOWOUT_SECONDARY_SCORER SKIP fires` pattern in `filter_self_skip_picks()` now correctly targets favored-side scenarios. (2) **3PM extreme blowout hard skip (spread_abs ≥ 19):** BLOWOUT_RISK=True AND spread_abs ≥ 19 → skip ALL 3PM picks regardless of trend direction (even trend=up). Additive to existing trend=down rule (fires at spread_abs ≥ 8). Reuses `3pm_blowout_trend_down` skip_reason. Motivated by SGA 0-for-3 in 29-point OKC blowout win on 2026-03-18 despite trend=up. Applied to `agents/analyst.py` only.
- **Analyst prompt rules updated 2026-03-19:** Two additional rules in `build_prompt()`: (1) `PTS T25 BLOWOUT HARD SKIP` in TIER CEILING RULES — spread_abs >= 15 + favored side = hard skip T25/T30, skip_reason=blowout_t25_skip. Cross-reference note added to ELITE SCORER BLOWOUT EXEMPTION exception clause. (2) `3PM CONFIDENCE FLOOR` in SELECTION RULES — 3PM minimum confidence is 75% (not system-wide 70%); picks landing 71–74% after all adjustments do not emit (no skip record needed). `agents/analyst.py` only.
- `3pm_blowout_trend_down` (March 14, 2026): trend=down AND BLOWOUT_RISK=True → hard skip all 3PM including T1; overrides [iron_floor]; winning-side players only. **RETIRED for spread_abs 8–18 in `build_pick_prompt()` (2026-03-22, H19 Finding 2)** — skip_reason enum retained for the ≥19 unconditional case. `build_prompt()` fallback still emits this skip at all spread levels (unchanged).
- **Analyst prompt rules updated 2026-03-18:** Four new rules added to `build_prompt()`: (1) elite scorer blowout exemption capped at spread_abs < 15 — at spread_abs >= 15, full 74% blowout cap applies to ALL players regardless of raw_avgs PTS; exemption unchanged for spreads 8–14. (2) VOLATILE + AST >= T6 = hard SKIP — added to AST rules block after the ast_hard_gate section; separate from and in addition to the VOLATILITY block volatile_ast_t6 rule. (3) iron_floor does NOT waive B2B road gate for non-primary BHs (raw_avgs AST < 6.0) — IRON-FLOOR B2B ROAD GATE added to REST & FATIGUE block; all four conditions required: on_back_to_back=True, home_away="A", opp_defense=tough, raw_avgs AST < 6.0. (4) 3PM top_pick requires iron_floor — 3PM TOP-PICK RESTRICTION added to TOP PICKS block; without iron_floor, 3PM capped at 80% and excluded from top_pick regardless of hit rate.
- **Three new prompt rules added 2026-03-17** (KEY RULES — VOLATILITY and KEY RULES — SEQUENTIAL GAME CONTEXT blocks):
  - **`volatile_ast_t6`** (HARD SKIP): [VOLATILE] + AST tier >= T6 → skip AST pick entirely, no lower-tier fallback. Elite playmaker exemption (>=8.0 APG) does NOT override — that exemption covers the low-volume position gate only, not floor instability. Exception: iron_floor AND trend=up at exactly T6 is exempt; T8+ skips regardless of iron_floor. Added to HARD SKIPS named skip list in priority framework. Audit evidence: Luka Doncic AST T6, actual 4 (exact floor value). Location: VOLATILITY block, after VOLATILE PTS skip exception paragraph.
  - **3PM confidence ceiling at 80%**: confidence_pct capped at 80 for all 3PM picks where iron_floor=false. Applied after all other penalties and caps. top_pick=true ineligible on non-iron-floor 3PM. Audit evidence: Austin Reaves 3PM T1 at 84%, actual 0. Location: end of SEQUENTIAL GAME CONTEXT block, before INJURY STATUS ON SHOOTING PROPS.
  - **VOLATILE neutralizes absence-driven upside**: [VOLATILE] on a stat → do not raise confidence citing teammate/opponent OUT. Treat as direction unchanged. Genuine role-change reassignments (primary ball-handler absent → VOLATILE player takes all creation duties) evaluated separately with explicit floor-change reasoning; iron_floor overrides. Audit evidence: Kevin Durant PTS (VOLATILE) 74%→79% via Sengun OUT amendment — scored 18 on T20. Location: VOLATILITY block, after volatile_ast_t6.
- `save_picks(picks: list[dict]) → list[dict]` — runs `filter_self_skip_picks()` then `reconcile_pick_values()` on the input list, appends survivors to `picks.json`, logs each saved pick, and **returns the filtered list** (fixed 2026-03-25). All three call sites in `main()` capture the return value: `picks = save_picks(picks)` — ensures the Review stage (Stage 3) only receives picks that survived the filter; previously the unfiltered list was passed to Review, causing ghost picks to appear in `picks_review_YYYY-MM-DD.json` with Auto-Review badges despite having no entry in `picks.json`.
- `save_skips(skips: list[dict]) → None` — writes `data/skipped_picks.json`; initialises null grading fields (`actual_value`, `would_have_hit`, `skip_verdict`, `skip_verdict_notes`); logs each skip reason to stdout
- `main()` now unpacks `picks, skips = call_analyst(...)` and calls both `picks = save_picks(picks)` and `save_skips(skips)`
- `VALID_TIERS` constant — `{"PTS": [10,15,20,25,30], "REB": [4,6,8,10,12], "AST": [2,4,6,8,10,12], "3PM": [1,2,3,4]}` — defined after `LARGE_SLATE_THRESHOLD`; used by `reconcile_pick_values()`; T2 REB removed 2026-03-14 (no betting market at mainstream books)
- `filter_self_skip_picks(picks: list[dict]) → list[dict]` — **first step of `save_picks()`** (runs before `reconcile_pick_values()`); scans each pick's `tier_walk` for unambiguous skip-conclusion language; **SKIP_CONCLUSIONS now has 16 patterns**: 5 confidence-threshold patterns ("below 70% skip", "→ 65% skip", "confidence = N% skip", etc.) + 4 floor gate failure patterns (`floor gate fails`, `no variance buffer + floor gate/skip`, `3rd-lowest equals pick value + skip`, `SKIP: 3rd-lowest`) + 7 named hard-gate patterns (2026-03-19): `HARD GATE FIRES`, `BLOWOUT_SECONDARY_SCORER SKIP fires`, `hard gate fires` (case-insensitive), named rule skip phrases (volatile_weak_combo, ast_hard_gate, blowout_secondary_scorer, 3pm_blowout_trend_down, reb_floor_skip, blowout_t25_skip, fg_margin_thin_tier_step + fires/skip), `SKIP T{N} AST/PTS/REB/3PM` + hard gate/mandatory skip/no valid tier, `mandatory skip`, `Record as skip`; hard-gate patterns cover rules that fire unconditionally before confidence arithmetic; removes picks whose own reasoning concludes skip but were emitted anyway; conservative — override signals ("proceed", "exception applies", "iron_floor overrides", etc.) appearing AFTER the skip language leave the pick intact; filtered picks logged to stdout as `[analyst] SELF_SKIP_FILTERED:` (not written to `skipped_picks.json`); added 2026-03-15; floor gate patterns added 2026-03-16; hard-gate patterns added 2026-03-19. Prototype failures: Pritchard PTS T10 (confidence threshold), Thompson REB T4 (floor gate), Banchero AST (HARD GATE FIRES / ast_hard_gate), Jalen Green PTS (BLOWOUT_SECONDARY_SCORER SKIP fires).
- `reconcile_pick_values(picks: list[dict]) → list[dict]` — **second step of `save_picks()`** (runs after `filter_self_skip_picks()`); detects mandatory tier step-downs documented in `tier_walk` but not reflected in `pick_value` (root cause: Claude reasons correctly about step-downs but Python never verified the two fields agreed); two-strategy parser: (1) rightmost valid tier after a step/→/apply/drop keyword that is lower than current `pick_value`; (2) fallback: rightmost `→T{N}` arrow pattern (gated on `check_hits` being non-empty — Strategy 2 only fires when Strategy 1 found ≥1 ✓-qualified tier, preventing false positives from unrelated tier mentions in text without ✓ marks); never raises `pick_value`; **one-tier-step guard** — after "never raise" check, computes `next_lower_tier = valid[current_idx - 1]` and RECONCILE_SKIPs when `final_tier != next_lower_tier` (prevents multi-tier cascades from ambiguous text matching two tier mentions); on correction: updates `pick_value`, appends `[reconciled: pick_value corrected {old}→{new} by Python post-processor]` to `tier_walk`, prints `[analyst] RECONCILED:` warning; on ambiguous parse: prints `[analyst] RECONCILE_SKIP:` and leaves pick untouched. Motivating failure: Jalen Duren PTS T15 March 12 — `tier_walk` documented "Apply step to T10" but `pick_value=15` was published; Duren scored 14 (HIT at T10, graded MISS at T15). One-tier-step + check_hits gate added 2026-03-16.

### `agents/lineup_update.py` (new — March 10, 2026; overhauled March 12, 2026; fixes applied March 14, 2026)
- Constants: `MODEL = "claude-sonnet-4-6"`, `MAX_TOKENS = 2048`, `CUTOFF_MINUTES = 20`
- `_ABBR_NORM` dict + `_norm(abbr)` — same normalization pattern as rest of codebase
- `OPPORTUNITY_FLAGS_JSON = DATA / "opportunity_flags.json"` — cumulative suggestion file
- `SKIPPED_PICKS_JSON = DATA / "skipped_picks.json"` — read by `load_morning_skips()` for annotation
- `ESPN_SCOREBOARD_URL` — ESPN scoreboard API used by `fetch_live_spreads()`
- `_OPPORTUNITY_TRIGGER_TAGS = {"defensive_anchor", "rim_anchor", "high_usage"}` — role tags; **used only by `classify_absent_player()` / amendment path now**; opportunity surfacing no longer uses tag gating (redesign 2026-03-15)
- `load_game_map() → dict[str, str]` — `{norm_team_abbr: game_time_utc}` from `nba_master.csv`; used to check tip-off cutoff per pick
- `game_is_actionable(game_time_utc, now_et) → bool` — True if tip-off > CUTOFF_MINUTES away; True on parse failure (safe default — don't skip on bad data)
- `compute_lineup_diff(lineups, injuries, today_picks=None) → list[dict]` — **TWO-SOURCE detection (March 14, 2026):** Source 1 (snapshot starters): players in `snapshot_at_analyst_run` now OUT/DOUBTFUL in injury report or silently dropped from starters. Source 2 (picks-based): players with open (ungraded) picks today who appear OUT/DOUBTFUL in injuries OR have `voided=True` in picks (lineup_watch already confirmed OUT). Both sources run; results merged and deduplicated via `(player_name_lower, norm_team)` 2-tuple. Each change dict carries a `"source": "snapshot" | "picks"` field. Root cause fixed: stars who aren't in Rotowire projected starters (load management, post-snapshot status shifts, bench players) were completely invisible to the original snapshot-only diff.
- `get_affected_picks(today_picks, changes, game_map, now_et) → list[dict]` — returns open today picks (result=None, not voided) where `team` OR `opponent` in changed teams AND game still actionable
- `build_rotowire_context(lineups, changed_teams) → str` — reads `projected_minutes` and `onoff_usage` from `lineups_today.json` for each team in `changed_teams`; formats starters/bench/out projected minutes and on/off usage deltas as a plain-text block; returns `""` when no Rotowire data present (graceful no-op on unauthenticated runs)
- `load_player_stats() → dict` — reads `data/player_stats.json`; returns `{}` gracefully if missing
- `build_pick_quant_summary(player_name, prop_type, player_stats) → str` — builds a one-line quant summary for a specific pick (tier hit rate, vs_soft/vs_tough, trend, volatility tag); injected as context beneath each pick in the Claude prompt
- `classify_absent_player(player_name, team, player_stats, today_picks=None) → dict` — derives role tags `{role_tags, avg_pts, avg_reb, avg_ast, avg_min}` from `player_stats.json`; tag logic: high_usage (avg_pts ≥ 20 or raw_avgs usage proxy), rim_anchor (avg_reb ≥ 7 and C/PF or raw_reb ≥ 9), defensive_anchor (avg_reb ≥ 6 and avg_pts < 15 proxy), perimeter_threat (avg_tpm ≥ 1.5), otherwise role_player. **Picks-based fallback (March 14, 2026):** if `player_stats` lookup finds nothing AND `today_picks` provided, infers tags from pick values — PTS pick → `high_usage`, REB pick ≥ 6 → `rim_anchor + defensive_anchor`, AST pick ≥ 4 → `primary_creator`, 3+ picks → `high_usage`; logs `[lineup_update] classify: {name} not in player_stats — inferred from picks: {tags}`. Prevents opportunity scan from silently failing when absent player was pre-filtered from player_stats at analyst run time.
- `build_absent_player_profiles(changes, player_stats) → str` — builds a `## ABSENT PLAYER PROFILES` block for the Claude prompt listing each absent player with role tags and key stats
- `call_lineup_update(affected_picks, changes, rotowire_context="", player_stats=None) → list[dict]` — single Claude call with 4-step reasoning framework (identify role, determine direction, calibrate magnitude using quant, apply default rule); system prompt now uses absent player profiles and per-pick quant context; `rotowire_context` injected when non-empty; returns `[{player_name, prop_type, direction, revised_confidence_pct, revised_reasoning}]`
- `apply_amendments(all_picks, amendments, affected_picks, changes, now_iso) → tuple[int,int,int]` — writes `lineup_update` sub-objects in-place to `all_picks`; returns `(n_amended, n_up, n_down)`; keyed by `(player_name_lower, prop_type)`. **Amendment sub-70% auto-skip (2026-03-31):** after writing the `lineup_update` sub-object, if `direction=="down"` and `revised_confidence_pct < 70`, the pick is immediately voided (`voided=True`, `void_reason` references revised confidence). The sub-object remains visible on the voided pick for audit trail. Fixes SGA AST T4 miss 2026-03-30 (amended to 68%, ran anyway).
- `load_game_log() → pd.DataFrame | None` — reads `data/player_game_log.csv`; returns None gracefully on missing/error
- `fetch_live_spreads() → dict[str, float | None]` — fetches current spreads from ESPN scoreboard API; returns `{norm_team: signed_spread}`; negative = favored; returns `{}` on any error (graceful degradation — spread delta omitted from cards without blocking run)
- `load_morning_skips() → dict[str, list[str]]` — reads `data/skipped_picks.json`; filters to TODAY_STR; returns `{player_name_lower: [skip_reason, ...]}` for opportunity card annotation
- `compute_without_player_rates(teammate_name, absent_player_name, game_log) → dict` — looks up historical games where absent player had dnp=="1" or minutes in ("","0"); computes hit rates at each tier for the teammate in those games; returns `{stat: {tier, hit_rate, n}}` for qualifying tiers (≥0.70 and n≥3); returns `{}` when insufficient history
- `build_opportunity_suggestions(changes, today_picks, player_stats, game_log, now_iso) → list[dict]` — **(overhauled 2026-03-16)** for each confirmed absence (new_absence), scans ALL whitelisted teammates AND opponents; **skips absent player from their own scan** (self-exclusion guard); collapses all qualifying props into one card per player (was one card per player×prop); builds `qualifying_tiers` dict (props ≥70% where player has no morning pick) and `upgrade_tiers` dict (props where quant best tier > morning pick tier, carries `morning_tier`/`morning_confidence_pct` sub-fields); determines `card_type` ("new_pick"/"upgrade"/"mixed"); skips player if both dicts empty; deduplicates by `name_lower` only; uses `triggered_by` (string, not `triggered_by_player`). Suggestion schema: `{date, generated_at, triggered_by (str), triggered_by_team, side ("teammate"|"opponent"), player_name, team, card_type, qualifying_tiers {stat: {tier, hit_rate_pct, trend, volatility, [without_player_hit_rate_pct, without_player_n]}}, upgrade_tiers {stat: {tier, hit_rate_pct, trend, volatility, morning_tier, morning_confidence_pct, [without_player_hit_rate_pct, without_player_n]}}, spread_delta, morning_context, reasoning}`.
- `save_opportunity_flags(suggestions) → None` — appends to `data/opportunity_flags.json`; deduplicates by `(date, player_name_lower, triggered_by_lower)` — one card per player per triggering absence; atomic write via `.tmp` rename
- `main()` — accepts `--debug` flag (argparse). Debug mode: prints full diagnostic (snapshot teams found, changes detected with source labels, affected picks count, opportunity suggestions formatted as `[card_type] new=STAT Ttier hit% upgrade=STAT T{old}→T{new} ← absent_player (side)`) without making LLM call or writing any files. Picks are loaded BEFORE `compute_lineup_diff()` call so `today_picks` can be passed as second detection source. Run with: `python agents/lineup_update.py --debug`

**`lineup_update` sub-object schema (written to affected picks):**
```json
{
  "triggered_by":           ["string — detail of each relevant change"],
  "updated_at":             "ISO timestamp",
  "direction":              "up" | "down" | "unchanged",
  "revised_confidence_pct": number,
  "revised_reasoning":      "string, max 20 words"
}
```
Sub-object is overwritten on each hourly run. `direction=unchanged` is still written (audit evidence).
Original `confidence_pct`, `reasoning`, `pick_value`, `tier_walk` fields are NEVER modified.

### `auditor.py`
- **Path constants:** `MASTER_CSV = DATA / "nba_master.csv"` added; `SKIP_ARCHIVE_JSON = DATA / "skipped_picks_archive.json"` added (2026-03-23) — persistent append-log for graded skips, never overwritten.
- `save_skip_archive(graded_skips: list[dict]) -> None` — appends fully graded skip records to `data/skipped_picks_archive.json` after each auditor run; de-duplicates on re-run by date (same pattern as `audit_log.json`); called inside the `if skips:` block in `save_audit()` after the `SKIPPED_PICKS_JSON` write; no-op when `graded_skips` is empty; added 2026-03-23.
- `build_absence_context(graded_picks)` → returns `## YESTERDAY'S NOTABLE ABSENCES` block (players voided or OUT at check time) or ""
- `load_game_results() → dict[str, dict]` — reads `nba_master.csv` for YESTERDAY_STR; returns `{team_abbrev: {home, away, home_score, away_score, margin, winner}}` keyed by BOTH home and away team abbrev (O(1) lookup from either side); skips rows where scores can't be cast to int; returns `{}` on any exception; logs game count. Motivating failure: Durant and Jokic played in the same game (HOU/DEN 36-pt blowout, March 11) — auditor couldn't identify the game context without a Brave Search hit, causing asymmetric miss classification.
- `build_game_results_block(game_results: dict) → str` — deduplicates via `seen` set on `{home}_{away}` key; labels each game `BLOWOUT` (margin ≥ 20), `COMPETITIVE` (10–19), or `CLOSE` (<10); sorts lines alphabetically; returns `## GAME RESULTS — YESTERDAY\n...` block; returns `""` if no games
- `save_audit_summary(audit_log, all_skips=None)` → writes `data/audit_summary.json`; per-prop and overall denominators exclude `injury_event` picks; `injury_exclusions` key in both per-prop and overall dicts; when `all_skips` provided, rolls up per-rule false skip rates into `"skip_validation"` key in the summary; `overall.voided` accumulates `voided_picks` across all audit entries (older entries without the field return 0 via `.get()`); `"human_flag_precision"` block (added 2026-03-16) reads `picks.json` directly, groups all graded picks by `human_verdict`, computes `{hits, misses, total, hit_rate_pct}` per verdict type across full season — accumulates automatically without explicit audit_log entries
- `load_picks_review(date_str: str) → dict[tuple, dict]` — reads `data/picks_review_{date_str}.json`; returns `{(player_name_lower, prop_type, pick_value): entry_dict}`; returns `{}` gracefully when file absent (prints no-op log); called in `main()` with `YESTERDAY_STR` after `grade_picks()`
- `apply_human_verdicts(graded_picks, review) → list[dict]` — tags each pick in-place with `human_verdict` ("keep"/"trim"/"manual_skip"/None) and `trim_reasons` (list/[]); returns same list; no-op (returns unchanged) when `review` is empty; called in `main()` after `load_picks_review()`
- `build_audit_prompt()` — splits `graded_picks` into `voided_picks` (player confirmed OUT, `voided=True`) and `active_picks` at the top of the function before any counting; all hit/miss/no_data counts, prop_breakdown, conf_breakdown, and `hits_and_misses` use `active_picks` only; `build_absence_context()` still receives full `graded_picks` (voided players ARE the absences it surfaces); OUTPUT FORMAT schema now emits both `"total_picks"` (active only) and `"voided_picks"`; summary line shows `active | voided | hits | misses` separately. Motivating fix: voided picks were inflating total_picks and appearing as NO_DATA, docking the system's hit rate for picks correctly voided before tip-off.
- `load_skipped_picks() → list[dict]` — reads `data/skipped_picks.json`; returns `[]` gracefully if missing
- `build_game_log_rows_for_yesterday() → dict[str, dict]` — reads `player_game_log.csv` for YESTERDAY_STR; returns `{player_name_lower: row_dict}` for non-DNP rows; used by `grade_skips()`
- `grade_skips(skips, game_log_rows) → list[dict]` — pure Python; fills `actual_value`, `would_have_hit`, `skip_verdict` (`false_skip` / `correct_skip` / `no_data`), `skip_verdict_notes` on each skip record in-place; returns same list
- `save_audit_report(audit_entry, graded_picks, graded_parlays, skips=None)` → extended signature; when `skips` provided, appends `## Skip Validation` table to the daily markdown report in `data/audit_reports/`; `save_audit()` callsite passes graded skips
- Miss classification taxonomy (6 types): `selection_error` / `model_gap_signal` / `model_gap_rule` / `variance` / `injury_event` / `workflow_gap` — written to `miss_classification` in `miss_details`. `model_gap_signal` = system lacks the signal entirely (no quant field or rule exists that could have caught this); `model_gap_rule` = signal existed in quant data/context at pick time but the analyst rule didn't correctly handle the combination. The legacy `model_gap` value is no longer valid.
- `build_audit_prompt(..., game_results_block: str = "")` — extended signature; `{game_results_block}` injected into prompt between season context and playoff_picture_section. Injects `{absence_block}` before `{news_block}`, ⚠ INJURY LANGUAGE IN NEWS flag on news_lines entries where detected. STEP 0 — ESTABLISH GAME CONTEXT inserted as first step of PICK ANALYSIS TASK: auditor looks up each player's team in `## GAME RESULTS — YESTERDAY` to identify final score, margin, and game_script label (BLOWOUT/COMPETITIVE/CLOSE) before analyzing any individual miss; provides shared game-context evidence across all players from the same game without requiring Brave Search hits. STEP 6 reads `lineup_update` sub-objects and annotates amendment direction vs. outcome in `root_cause`. Does not change `miss_classification` — amendment and game context notes are contextual only. Existing STEP 1–6 numbering unchanged.
- **`load_player_stats_for_audit()` was REMOVED (March 8, 2026)** — eliminates yesterday's-data-for-today's-audit confabulation bug. Auditor now reads quant context from pick object fields (`reasoning`, `hit_rate_display`, `tier_walk`, `opponent`) written at pick time.

### `post_game_reporter.py` (runs before auditor each morning)
- `load_yesterdays_player_names()` → set of lowercase names from yesterday's picks
- `load_yesterdays_missed_pick_names()` → subset where `result == "MISS"` **only** — `None` (ungraded) excluded. The reporter runs as the FIRST step of auditor.yml, before picks are graded. Including `None` caused all ungraded picks to be treated as missed picks, triggering Brave/ESPN fetches for every player even on a 92% hit-rate day. Fix: `result == "MISS"` only (March 12, 2026).
- `load_athlete_id_map()` → `{player_name_norm: player_id}` from `player_dim.csv`
- `load_yesterday_game_rows(player_names)` → `{name: row_dict}` from `player_game_log.csv`
- `should_fetch(game_row, is_missed_pick=False)` → `(bool, reason)` — reason is one of `missed_pick / dnp_flag / zero_minutes / low_minutes_X / zero_STAT_at_Xmin / normal`
- `news_contains_injury_language(news_items)` → `(bool, matched_term)` — scans `INJURY_SCAN_TERMS` (26 terms) across headline + description
- `fetch_espn_news(athlete_id)` → `(news_items, fetch_ok)`
- `classify_from_news(news_items, minutes, game_row)` → `(event_type, detail, source_url, from_news)` — event_type is `injury_exit / dnp / minutes_restriction / no_data`
- `_get_miss_pick_meta(player_name_lower)` → `{prop_type, pick_value, actual_value, team}` — reads first MISS pick for the player on YESTERDAY_STR from `picks.json`; returns `{}` if not found
- `fetch_web_narratives(missed_players)` → `{name_lower: raw_snippet_text}` — Brave Search API; **two queries per missed-pick player** (2026-03-15): (1) `"{name} {team} NBA recap {date}"` (recap), (2) `"{name} injury"` (injury-specific, catches mid-game exits not in recap results); `count=3` per query; snippets combined and deduplicated by title prefix (~40 chars); `_brave_query()` inner helper handles each query; returns `{}` if `BRAVE_API_KEY` not set or all searches fail; graceful per-player error handling; log line reports `N recap + M injury snippets, K unique`
- `call_claude_summarise_narratives(missed_players, raw_snippets)` → `{name_lower: narrative_str}` — single batch Claude call (`claude-sonnet-4-6`, max_tokens=2048); extracts factual one-to-two sentence miss explanation per player from snippets; returns `{}` if `ANTHROPIC_API_KEY` not set or API fails; only called when at least one snippet exists
- Writes `data/post_game_news.json`: `{date, generated_at, players: {name: {event_type, detail, minutes_played, source_url, confidence, injury_language_detected, injury_scan_term, espn_fetch_ok, web_narrative}}, fetch_errors}` — `espn_fetch_ok` is `true/false` when ESPN was attempted, `null` when no athlete ID; `web_narrative` is a string for missed players with Brave snippets, `null` otherwise; both present on all entries
- **Universal fetch:** ALL yesterday's pick players are fetched regardless of box score criteria; `should_fetch()` output used only for logging labels
- **Web narrative layer (March 11, 2026):** runs AFTER the ESPN loop, scoped to missed-pick players only; `BRAVE_API_KEY` secret injected in `auditor.yml`; Auditor `build_audit_prompt()` renders `web_narrative` as `📰 WEB RECAP:` line in `## POST-GAME NEWS CONTEXT` block
- **`espn_fetch_ok` field (March 12, 2026):** `fetch_ok = None` initialized before `if aid:` block so it is always defined; added to all `players_out` entries as `fetch_ok if aid else None` — `null` for no athlete ID, `true`/`false` for ESPN attempt outcome. Informational only — does not change classification logic.
- **web_narrative merge order (March 12, 2026 — verified correct):** merge loop (`for name, narrative in web_narratives.items()`) runs at lines 724–740, before `json.dump` at line 750. Narratives are always written into `players_out` before the file is saved. No code change required — order was already correct.

### `pre_game_reporter.py` (runs between quant and analyst)
- Loads today's team abbrevs from `nba_master.csv`; loads active whitelist players on today's teams
- Fetches ESPN athlete news per player + league-wide news (48h window)
- Filters to prop-relevant items; discards noise keywords (contract/fine/trade rumor)
- **`detect_staleness_flags(context_path, today)` → `list[str]`** — deterministic Pass 1; parses `## SEASON FACTS` section of `nba_season_context.md` for ISO dates (`YYYY-MM-DD`) and month-year dates (`Feb 2026`); applies three rules per line: (1) return/injury keyword + age >7d, (2) ISO date + no return keyword + age >5d, (3) trade/role keyword + age >60d; returns list of `⚠ CONTEXT FLAG: ...` strings; uses `re` + `datetime` only — no LLM
- **`_append_staleness_flags_to_md(staleness_flags)`** — appends a `## 🕐 DATE-BASED STALENESS FLAGS (auto-detected)` block to `data/context_flags.md` after the Claude report section
- **`call_claude_staleness_check(context_text, news_items)`** → `list[dict]` — Pass 2; single Claude call cross-referencing season context against today's news; returns list of `{player_or_team, current_context_fact, conflict, urgency, suggested_action}` flag dicts
- **`write_context_flags_md(flags)`** — writes full structured markdown report to `data/context_flags.md` (OVERWRITES — critical/monitor urgency tiers with `##` headers); `_append_staleness_flags_to_md()` is called AFTER this to append Pass 1 flags
- **`run_context_staleness_check(filtered_items, all_raw_items)`** → `tuple[list[dict], list[str]]` — orchestrates both passes; Pass 1 always runs first; Pass 2 (Claude) fires when `filtered_items > 0` OR context file date is stale; deduplicates Pass 1 flags against Pass 2 `player_or_team` tokens; returns `(claude_flags, staleness_flags)`
- **`write_output(..., context_flags=None, staleness_flags=None)`** — writes `data/pre_game_news.json`; keys: `suggested_context_updates` (Claude flags), **`staleness_flags`** (Pass 1 flags — always present, `[]` when none)
- Writes `data/pre_game_news.json`; always writes (empty) even with no news

### `lineup_watch.py` (standalone, runs after each injury refresh)
- Reads `picks.json` + `injuries_today.json`
- Writes `injury_status_at_check` (OUT / DOUBTFUL / QUESTIONABLE / NOT_LISTED) + `injury_check_time` (ISO PT) to **ALL** of today's picks on every run
- OUT → `voided=True` + `void_reason`; DOUBTFUL → `lineup_risk="high"`; QUESTIONABLE → `lineup_risk="moderate"`
- Severity is sticky upward — picks never downgraded
- Name matching uses last-name + team-abbrev key to handle Rotowire abbreviated player name format
- Stale flag clearing: status improvements between hourly runs (e.g., DOUBTFUL → NOT_LISTED) now remove prior `voided`/`lineup_risk` flags
- **Sticky void guard (March 14, 2026):** CLEAR block guards against clearing confirmed voids. If `voided=True` AND `void_reason` is set, the pick is never un-voided — Rotowire post-game roster resets (which move all players back to PROB/unlisted) cannot undo a confirmed OUT. Speculative `lineup_risk` flags (DOUBTFUL/QUESTIONABLE) still clear normally when status improves.

---

## Known Edge Cases and Gotchas

**`player_stats.json` nullable per-stat fields — `.get(prop, default)` does NOT protect against explicit None (2026-03-21):** Several quant fields store per-stat sub-dicts but write explicit `None` when data is insufficient (e.g. `bounce_back["REB"] = None`, `b2b_hit_rates["3PM"] = None`). The pattern `(s.get("field") or {}).get(prop, {})` is NOT safe for this case — `.get(prop, default)` only fires when the key is absent; when the key exists with a `None` value the default is bypassed and `None` is returned. The correct pattern is `(s.get("field") or {}).get(prop) or {}`. This bit `build_review_context()` on `bounce_back` (line 3217). Apply the `or {}` form any time a per-stat quant field can be explicitly `None`.

**`build_review_context()` volatility field shape (2026-03-21):** `player_stats.json["volatility"][prop]` is a dict `{label, sigma, n}`, not a string. Any code reading this field must do `.get(prop) or {}` then `.get("label")` to extract the label string. The pattern `.get(prop, "unknown")` embeds the raw dict representation into output instead of the label. Fixed at line 3205.

**Date-stamped module constants must follow `TODAY_STR` definition (2026-03-21):** Module-level path constants that embed `TODAY_STR` must be defined AFTER the `TODAY` / `TODAY_STR` block (lines ~46–47). Placing them above causes a `NameError` on import. All date-stamped paths in the file are in functions or after the date block — keep this invariant. (`SCOUT_OMITTED_JSON` was the original example; removed 2026-03-25 when the omitted block was dropped.)

**`call_analyst()` JSON repair fallback (added 2026-03-17):** `parse_claude_response()` (implemented inside `call_analyst()`) now has a two-step repair fallback that fires when `json.loads(raw)` raises an exception — triggered by a 2026-03-17 run failure where Claude produced structurally valid JSON with a bad character inside a `tier_walk` string field. Step 1: `json_repair` library (`from json_repair import repair_json`). Step 2: character sanitization — char-by-char scan that replaces literal `\n`/`\r`/`\t` inside JSON string values with their escaped forms. Both `except` blocks (object-format path and flat-array fallback path) call `_repair_json(raw)` before `sys.exit(1)`. The happy path (valid JSON) is completely unchanged. Repair logs `[analyst] WARNING: JSON repair via ... succeeded` so the pick run continues with visible evidence in the Actions log. `json-repair` is installed in `analyst.yml` pip install step.

**Team abbreviation variants:** `nba_master.csv` uses legacy 2-char forms (`GS`, `SA`, `NO`,
`UTAH`, `WSH`). `_ABBR_NORM` dict + normalization helpers exist in THREE places: `analyst.py`
(`_norm_team()`), `parlay.py` (`_norm_team()`), and `build_site.py` (`normAbbr()` JS). Also in
`lineup_update.py` (`_norm()`). Keep all in sync if abbreviations need updating.
`analyst.py` copies raw abbrevs from `nba_master.csv` into `picks.json` — this is the root
cause of historical game grouping issues (all now resolved in `build_site.py`).

**Player name case:** Whitelist CSV uses title case ("Cade Cunningham"). All filtering uses
`.strip().lower()` before set membership checks. The `position_map` dict is also keyed by
lowercase. The `player_name` variable in the `build_player_stats()` loop comes from
`log.groupby("player_name")` — raw case from game log CSV (also title case).

**DNP rows:** `player_game_log.csv` keeps DNP rows with `dnp="1"`. All hit rate computations
and volatility exclude them via `df[df["dnp"] != "1"]` or equivalent. Missing this filter
anywhere would silently corrupt hit rates (0 pts on a DNP would count as a miss at every tier).

**`player_stats.json` is overwritten daily** — it only contains players playing TODAY. It is
not a historical archive. The auditor no longer reads `player_stats.json` at all (the function
was removed March 8 to fix the date-gate bug). The auditor reads quant context from pick fields.

**`compute_positional_dvp` uses full season history,** not just the last 15 games (unlike
`build_opp_defense()` which uses `OPP_WINDOW=15`). This is intentional — position-specific
cells need larger samples to clear the 10-game minimum reliably.

**`spread_split_hit_rates` coverage is limited** — only 829/935 rows in nba_master.csv have
spread data. Cells with < 5 games show `n/a` in the quant context. Accumulates going forward.

**The `opp_defense_rating` field in `picks.json` output** — the analyst's prompt no longer
shows `opp_today=` per stat line (replaced by the DvP line), but the OUTPUT FORMAT schema
still requests `opp_defense_rating`. Claude derives this from the DvP PTS rating. It's read
by `build_site.py` for defense pills. Functionally fine; cosmetically inconsistent naming.

**`audit_summary.json` starts empty** — `save_audit_summary()` only accumulates going forward.
The analyst prompt shows "Insufficient audit history yet (need 3+ days)" until 3+ days exist.
The `prop_type_breakdown` and `confidence_calibration` fields are absent from pre-March audit
entries; `save_audit_summary()` handles missing fields with `.get()` defaults.

**`injury_status_at_check` field in `picks.json`** — written by `lineup_watch.py` on every
hourly run to ALL of today's picks (not just open ones). Values: `OUT / DOUBTFUL / QUESTIONABLE /
NOT_LISTED`. Used by the auditor's STEP 2 to distinguish `injury_event` (player was
NOT_LISTED/QUESTIONABLE at pick time, exited mid-game) from `workflow_gap` (player was
OUT/DOUBTFUL pre-game but wasn't voided). If `lineup_watch.py` hasn't run yet when the auditor
grades, the field will be absent — auditor handles gracefully.

**`post_game_news.json` fetch errors** — `fetch_errors` list in the output names players whose
ESPN API call failed. The auditor receives this in `## POST-GAME NEWS CONTEXT` and should note
the gap, not infer absence from missing data. Players without `athlete_id` in `player_dim.csv`
are also silently skipped for news fetch (box score inference used instead).

**`iron_floor` field in `picks.json`** — as of March 7, 2026, `iron_floor` is written to all
new picks. Pre-March picks don't have the field; `build_site.py` badge logic handles `undefined`
gracefully. The field is `true` only when the quant stat line showed `[iron_floor]` — Claude is
instructed to copy it directly from the context, not derive it.

**Voided pick grading contract (fixed March 14, 2026)** — `grade_picks()` in `auditor.py` now guards against grading voided picks. Two rules: (1) Fix 1A — `voided=True` picks are passed through with `result=None, actual_value=None` (no box score lookup). (2) Fix 1B — a second pass after the main loop promotes any pick with `result=="MISS" AND actual_value==0.0 AND void_reason set AND not voided` to `voided=True, result=None` (post-hoc late-DNP detection). `build_audit_prompt()` already filters `voided/active` correctly; `save_audit_summary()` denominator already excludes voided picks. The repair script `scripts/repair_void_grading.py` patched historical data for 2026-03-12 and 2026-03-13.

**`top_pick` field in `picks.json`** — as of March 12, 2026 (Session 2), `top_pick` is emitted by the analyst for 2–4 picks per day. Older picks without the field are treated as `false` by JS. `get_top_picks()` in `build_site.py` uses `top_pick=True` as primary gate; falls back to `confidence_pct >= 85` for backwards-compatibility. The `past_top_picks` history filter is `p.get("top_pick") is True OR p.get("confidence_pct", 0) >= 85` so historical picks still populate the Top Picks History drawer. Criteria live in the `## TOP PICKS — FINAL SELECTION STEP` section of `build_prompt()`.

**Whitelist filter is a `(name, team)` tuple set**, not name-only. This prevents traded players
from appearing under their old team. If a player is traded mid-season, update `team_abbr` in
`player_whitelist.csv` and set the old entry `active=0`. Do not delete old rows.

**`load_whitelist()` emits alt-abbrev tuples (2026-03-25):** Both `quant.py` and `analyst.py`
`load_whitelist()` now emit tuples for BOTH `team_abbr` (standard NBA) AND `team_abbr_alt` (ESPN
short) when alt is non-empty. Required because `player_game_log.csv` uses ESPN abbrevs (SA, GS,
NY, UTAH) while the whitelist uses standard NBA abbrevs (SAS, GSW, NYK, UTA). Without this, 10
players were invisible to quant and analyst since launch. Affected teams: SAS/SA, NYK/NY,
GSW/GS, UTA/UTAH. `load_injuries()` in `analyst.py` also normalizes `teams_today` through
`_ABBR_NORM` for the same reason (injury data for all four teams was silently dropped).

**`data/context_flags.md` write order** — `write_context_flags_md(claude_flags)` OVERWRITES the
file each run with the Claude-format structured report. `_append_staleness_flags_to_md()` is
called AFTER to append Pass 1 deterministic flags as a plain `## 🕐 DATE-BASED STALENESS FLAGS`
block. If there are no Claude flags, `write_context_flags_md([])` writes a "no conflicts" stub,
then staleness flags are still appended if any exist.

**`detect_staleness_flags()` section boundary** — the function stops at BOTH
`## TEAM DEFENSIVE PROFILES` AND `## PERMANENT ABSENCES` (whichever comes first). This prevents
the static TEAM DEFENSIVE PROFILES content (still in the file as a reference — not injected by
agents) from generating false staleness flags for old team defense notes.

**`format_team_defense_section()` always non-empty contract** — returns the fallback warning
string (including `##` header) on missing file, stale file (`as_of != TODAY_STR`), or empty
narratives. The analyst always sees a `## TEAM DEFENSIVE PROFILES` section even if it's just
the warning line. This means `team_defense_section` is never injected as a bare empty string.

**`load_season_context()` TEAM DEFENSIVE PROFILES stripping** — the static `## TEAM DEFENSIVE
PROFILES` section remains in `context/nba_season_context.md` as a human reference but is
stripped in-memory before injection. The file itself is never modified by any agent.

**`lineups_today.json` guard condition** — `rotowire_injuries_only.py` will NOT overwrite a
good existing file with 0 teams parsed. If a scrape returns 0 starters (e.g., Rotowire is slow
pre-noon), the existing file for today's date is preserved. Only non-zero parses overwrite.

**`snapshot_at_analyst_run` in `lineups_today.json`** — written by `write_analyst_snapshot()`
in `analyst.py` at pick time. Guard logic (2026-03-25): skips write only when `written_at` date
matches today AND `teams` is non-empty — prevents redundant overwrites within the same day while
allowing a refresh when a prior run left `teams: {}` (stale empty snapshot bug). Prior guard was
`if raw.get("snapshot_at_analyst_run"): return` which blocked all refreshes once any snapshot
existed, causing `lineup_update.py` to skip for 13 days. `lineup_update.py` treats absence of
this key (or empty `teams`) as a skip condition.

**`lineup_update.py` no-op conditions** — five conditions will silently skip the LLM call:
(1) `lineups_today.json` missing; (2) `snapshot_at_analyst_run` key absent; (3) no starter
changes detected (most common daily case); (4) no open non-voided picks for changed teams;
(5) all affected picks past tip-off cutoff. The agent logs the reason and exits cleanly.

**`_extract_last()` in `analyst.py`** — handles Rotowire-abbreviated name format "J. Brunson"
by detecting a pattern of `[char]. [rest]` and taking everything after the `. `. For normal
names (e.g., "Jalen Brunson"), takes the last space-separated token. Both normalize to lowercase.

---

## Prompt Signals and Their Reliability Status

| Signal shown to Analyst | Where in context | Reliability |
|--------------------------|-----------------|-------------|
| Tier hit rates (last 20g) | Stat line `overall=` | Primary — use as floor |
| vs_soft / vs_tough (full season) | Stat line | Secondary — confirm DvP direction |
| competitive / blowout_games splits | Stat line | Confirm spread risk |
| DvP [POS] rating | DvP line per player | Primary defense signal for PTS/AST |
| B2B rate at tier | Stat line `b2b=` | Primary on B2B nights |
| bb_lift / iron_floor | Stat line | Trust iron_floor; treat bb_lift as mild |
| [VOLATILE] / [consistent] | Stat line suffix | Directional (no confirmed backtest yet) |
| [FG_HOT] / [FG_COLD] | PTS stat line suffix | Shooting regression — ±8% threshold; unvalidated |
| trend (up/stable/down) | Stat line | Noise — data shown, no directive weight |
| BLOWOUT_RISK | Header flag | Confirmed directionally; −1 tier rule + secondary scorer skip at spread_abs ≥ 15 (favored team only — BLOWOUT_RISK=True means player's team is the heavily favored side). At spread_abs 8–14: confidence penalty only, no hard skip. H19 backtest applied 2026-03-22. |
| Without [X] (key_teammate_absent) | After Teammates line | Player's raw avgs + tier hit rates in games where top-PPG whitelisted teammate was absent (n≥3); directive — Pick stage uses absence baseline as primary evaluation when teammate is OUT/DOUBTFUL; added 2026-03-20. **Two-gate eligibility rule in `build_pick_prompt()` (added 2026-03-22):** Gate 1 — star must be confirmed OUT (not QUES/GTD) to use as primary qualifier; Gate 2 — n ≥ 10 games required to use as primary qualifier. Both gates must pass. n < 10 or QUES status → supplementary context only, fall back to standard baseline. **`absence_trend` override (added 2026-03-25):** When key teammate is absent and n_games ≥ 5, the top-level `trend=` value shown in the stat line is overridden with within-absence-window trend (L5 vs full absence-window mean). This means the `trend` label in the stat line reflects the player's trajectory WITHIN the without-star regime, not against an L20 baseline that includes higher-usage shared-lineup games — prevents false `trend=up` on a player declining within the absence window. |
| spread_abs > 13 | Header flag | Cap at 80% confidence (elite scorer exempt if raw_avgs PTS ≥ 27.0) |
| DENSE schedule | Header flag | −5–10% confidence |
| REB opp defense | DvP line REB field | Excluded — not a valid signal |
| 3PM opp defense | DvP line 3PM field | Excluded — noise (lift variance 0.053) |
| 3PM cold streak | Inferred from trend + recent logs | Decline signal (lift=0.87, n=161) |
| 3PM trend=down | Stat line `trend=down` | **Mandatory step-down rule** — pick one tier lower; skip if below T1 |
| PROJECTED LINEUPS | ## PROJECTED LINEUPS section | Ground truth for starter availability — treat as LINEUP CONTEXT backstop |
| PLAYOFF PICTURE | ## PLAYOFF PICTURE section | Situational awareness only — no hard rules |
| TEAM DEFENSIVE PROFILES | ## TEAM DEFENSIVE PROFILES section | Rolling 15g — replaces static file section |
| proj_min=N (player header) | Quant context block header | Rotowire projected minutes; contextual only — no directive rules; absent when Rotowire creds not present |
| [USG_SPIKE:+Npp vs X.Name] (player header) | Quant context block header | Usage boost ≥5pp with ≥100 min sample when named player absent; treat as contextual positive signal |
| ⚠ OPP: Name OUT (proj=0min) | After Momentum line | Opponent key player with 0 projected minutes per Rotowire; supports matchup assessment; absent when creds not present |
| Momentum — line | After DvP line | L10 W-L record + avg margin + hot/cold tag; annotation only — no directive rules; unbacktested; treat as situational awareness |
| DEF↑ / DEF↓ (player header) | Quant context block header | Opponent's L5 vs L15 PTS-allowed divergence ≥8%; annotation only — no directive rules; absent when neutral or <3 L5 games |
| [SHORT_SAMPLE:Ng] (player header) | Quant context block header | `games_available < 8` — player recently returned from injury or missed extended stretch; L10 floor unreliable; triggers RETURN FROM INJURY rule: mandatory REB/AST one-tier step-down, PTS -5% + no T20+ unless ≥7 games; absent when games_available ≥ 8; added 2026-03-16 |

---

## Active Improvement Queue (as of March 25, 2026)

| ID | Name | Status | Files |
|----|------|--------|-------|
| Season Context 0 | Standings Snapshot | ✅ DONE (March 2026) | `espn_daily_ingest.py`, `analyst.py`, `auditor.py` |
| Season Context 1 | Auto-Generated Team Defense Narratives | ✅ DONE (March 2026) | `quant.py`, `analyst.py` |
| Season Context 2 | Staleness Detection in pre_game_reporter | ✅ DONE (March 8, 2026) | `pre_game_reporter.py` |
| Season Context 3 | Restructure SEASON FACTS into decay tiers | Manual edit — no code needed | `context/nba_season_context.md` |
| P3 | Shooting Efficiency Regression | ✅ DONE (March 7–8, 2026) | `espn_player_ingest.py`, `quant.py`, `analyst.py` |
| P4 | Tier-Walk Audit Trail | ✅ DONE (March 6, 2026) | — |
| P5 | Afternoon Lineup Update Agent | ✅ DONE (March 10, 2026) | `analyst.py`, `agents/lineup_update.py` (new), `injuries.yml`, `build_site.py`, `AGENTS.md` |
| P6 | Skip Validation System | ✅ DONE (March 11, 2026) | `analyst.py`, `auditor.py`, `analyst.yml`, `auditor.yml` |
| P7 | Team Momentum Indicator | ✅ DONE (March 11, 2026) | `quant.py`, `analyst.py` |
| #1 | Teammate Absence Delta | Deferred to next season (insufficient DNP sample) | `quant.py`, `analyst.py` |

**Next backtests to run:**
- **H9 — H2H Splits:** Run ~mid-April 2026
- **H14 — Elite Opposing Rebounder:** COMPLETE — NO_SIGNAL (Mar 22, 2026, n=1,709). thresh=10.0 delta=−0.5pp; H14b team REB flat. No rule change. CLOSED.
- **H15 — Opp Team Hit Rate:** COMPLETE third run (Mar 31, ≥600 picks). Suppressors confirmed: HOU (65.2%, n=23), PHX (75.0%, n=24), PHI (64.7%, n=17; game-script caveat). Amplifier confirmed: IND (100.0%, n=23). MIN×AST 63.6% n=11 — below ≥15 gate, monitor through playoffs. `nba_season_context.md` updated. No new prompt rules — context guidance only. CLOSED unless MIN×AST clears ≥15 picks.
- **H16 — 3PA Volume Gate:** Re-run at ~150+ 3PM picks (`--mode 3pa-volume-gate`). Currently 99/150 graded 3PM picks as of Mar 22 — ETA ~April 1–3.
- **H18 — Wembanyama Rim Deterrent:** CLOSED after research phase (Mar 22, 2026). Q2: miss players split 4 interior/balanced vs 2 perimeter; Miller (motivating case) classifies as PERIMETER (49.77% 3PA rate). Q3: opponents take +0.52 more 2PA vs SA (opposite of hypothesis). Pattern does not hold. No backtest warranted.
- **H17 — Spread Context:** COMPLETE second run (Mar 22, n=538) — NOISE confirmed. CLOSED. `--mode spread-context`. No rules warranted.
- **H20 — Losing-Side AST:** COMPLETE — NO_SIGNAL (Mar 22, 2026, n=54). `--mode losing-side-ast` implemented in `backtest.py`. Rule not shipped.
- **H21 — Miss Anatomy:** COMPLETE — NOISE (Mar 22, 2026). PTS delta 0.6pp, REB delta 2.0pp, AST delta 0.8pp — all below 4pp threshold. Rule NOT shipped. `near_miss_rate`/`blowup_rate` remain in quant for Player Profiles only.

**Confidence calibration check:** After 20+ audit days (~late March), compare per-band actual hit rates in `audit_summary.json` against stated confidence bands (70–75 / 76–80 / 81–85 / 86+).

---

## Files To Touch Most Often (by task type)

| Task | Files |
|------|-------|
| New quant signal | `quant.py` only (add function + wire in `build_player_stats()` + `main()`) |
| New prompt rule | `analyst.py` `build_prompt()` AND `build_pick_prompt()` — both functions contain the full rulebook and must be updated identically for any rule change |
| New context shown to analyst | `quant.py` `build_player_stats()` + `analyst.py` `build_quant_context()` |
| New pick output field | `analyst.py` OUTPUT FORMAT schema + `build_site.py` pick card renderer |
| Whitelist change | `playerprops/player_whitelist.csv` only (toggle `active` flag) |
| Season context update | `context/nba_season_context.md` only |
| Team defense narratives | `quant.py` `build_team_defense_narratives()` only |
| Backtest | `agents/backtest.py` — standalone, reads CSVs, writes JSON, no production impact |
| Frontend change | `build_site.py` only — triggers on next injury refresh or analyst run |
| Lineup update rules | `agents/lineup_update.py` `call_lineup_update()` system/user prompt; also `classify_absent_player()` role_tag thresholds for absence impact tuning |
| Daily picks review | `data/picks_review_YYYY-MM-DD.json` only — human-produced in Claude chat session, committed before auditor.yml runs |

---

## data/picks_review_YYYY-MM-DD.json

Human-produced daily picks review file. Written in Claude chat sessions each morning after reviewing the day's picks. Committed to the repo **before `auditor.yml` runs** so the auditor can join against it.

**Schema:** `[{date, player_name, team, prop_type, pick_value, verdict, trim_reasons}]`

**Verdicts:** `"keep"` (clean pick) | `"trim"` (marginally weak; exclude from parlay core) | `"manual_skip"` (should not have been filed; workflow/analyst error)

**Join key:** `(player_name.strip().lower(), prop_type, pick_value)` — date is for reference only (all entries should match yesterday's date when the auditor reads the file)

**Consumers:**
- `auditor.py` — `load_picks_review(YESTERDAY_STR)` + `apply_human_verdicts()` → writes `human_verdict` and `trim_reasons` fields to `picks.json`; `save_audit_summary()` rolls up `human_flag_precision` block tracking season hit/miss rates by verdict type
- `parlay.py` — `load_todays_picks_review()` (TODAY_STR) → excludes `manual_skip` picks from candidate pool; allows max 1 `trim` pick per card only with ≥2 clean anchors
- `build_site.py` — renders amber `⚠ Caution` badge on `trim` picks, red `⚠ Flagged` badge on `manual_skip` picks, with inline `trim_reasons`

**Graceful degradation:** All three consumers return no-op (empty/unchanged) when the file is absent for the date — no crash, no silent error.

**NOT automated** — `data/picks_review_YYYY-MM-DD.json` is never written by any agent. `analyst.py`, `quant.py`, `lineup_update.py`, `lineup_watch.py` do not read or write this file.

---

## What Has NOT Been Done (common assumption errors)

- **Cunningham/Ball misclassification fix is implemented but unverified in production** — injury_exit promotion in `post_game_reporter.py` and auditor STEP 2 fast path added 2026-03-18. Two paths: (1) `_INJURY_EXIT_TERMS` extended to catch "spasms", "ruled out for the remainder", "hard fall" etc. directly in `classify_from_news()`; (2) new promotion block: `event_type=="minutes_restriction"` AND `from_news=False` AND `inj_detected=True` AND `minutes < MINUTES_LOW_THRESHOLD` → promoted to `injury_exit`. Auditor: STEP 2 opens with FAST PATH — if `injury_exit` in POST-GAME NEWS CONTEXT, classify immediately as `injury_event` without game-script reasoning; `post_game_event="injury_exit"` annotation stamped on pick dicts in `build_audit_prompt()`. Confirm working after next low-minutes in-game injury exit is processed by the pipeline.
- **Positional DvP — H8 verdict: REVERT (March 12, 2026)** — backtest ran against full season game logs. Positional lift_advantage was negative for PTS (−0.051), REB (−0.052), and AST (−0.060). Team-level opp defense outperforms positional splits — position-splitting dilutes cell sizes and flattens signal, particularly for frontcourt REB (team-level lift 1.077 vs positional 0.980). 3PM was KEEP (+0.106) but 3PM DvP is already excluded from prompt rules. **Prompt cleanup is PENDING** — `DvP [POS]` line in `build_quant_context()` to be removed; implementation is annotation-only so no picks are at risk in the interim. Do not treat positional DvP as a validated signal.
- **Volatility scores have not been backtested** — σ thresholds (0.3/0.4) are reasonable priors
  but not empirically validated against this dataset. The auditor will accumulate evidence over
  time via the `reasoning` field (volatility flag instruction).
- **Shooting regression signal has not been backtested** — ±8% threshold is an untested prior;
  validate via audit accumulation after 30+ days of flagged picks. HOT misses clustering in
  `model_gap` confirms mechanism; `variance` clustering suggests penalty is overcorrecting.
- **Miss Anatomy analyst wiring is NOT done** — `near_miss_rate` and `blowup_rate` fields are
  live in `player_stats.json` and feeding Player Profiles conditional rendering. The directive
  prompt rule (confidence modifier or tier-drop on high `blowup_rate`) is explicitly NOT shipped
  until the backtest validates the signal.
- **`auditor.py` does NOT detect `lineup_update` picks** — picks that were re-reasoned by
  `lineup_update.py` are graded identically to morning picks. The audit log does not distinguish
  "revised up/down" from "original." A future P5 audit integration would tag these and evaluate
  whether re-reasoned picks outperform their morning originals. Revisit after ~20 days of
  amendment data accumulates.
- **`lineup_update.py` LLM cost** — each hourly run that detects changes will call Claude (one
  call, up to 2048 tokens). On a typical day with one morning absence detected, this adds ~$0.01.
  On a busy injury day with 3+ changes, cost is still negligible. Monitor if cost becomes visible.
- **`lineup_update.py` has no audit integration** — `lineup_update` sub-objects are written
  but the auditor's STEP 2 and miss classification do not yet check for them. A pick that was
  revised DOWN and then missed would still be classified via the normal root-cause logic without
  noting the amendment context. Acceptable for now.
- **`opportunity_flags.json` has no grading integration** — the auditor does NOT read `opportunity_flags.json`
  and does NOT compare suggestion tiers against actual game results. Implement after ~2 weeks of suggestion
  data accumulates to verify the surfacing mechanism is working before adding grading infrastructure.
  The follow-on design (Option 2 from spec) would log `opportunity_miss` events to `audit_log.json` when
  a surfaced suggestion would have hit at the suggested tier.
- **Skip Validation has no analyst prompt feedback loop yet** — `audit_summary.json["skip_validation"]`
  accumulates per-rule false skip rates, but the analyst prompt does NOT yet read or act on this
  data. A future enhancement would inject high-false-skip-rate rules into the analyst prompt
  (e.g., "skip rule X has 35% false skip rate — consider loosening"). Evaluate after ~20 days of
  skip data accumulates.
- **Season Context Improvement 3 (SEASON FACTS decay tier restructure) is NOT done** — this is
  a manual edit to `context/nba_season_context.md`. No code required. Do after verifying that
  Improvements 0–2 are running cleanly in production.
- **`team_defense_narratives.json` perimeter and pace clauses are NOT active** — the current
  `team_game_log.csv` schema lacks `fg3_pct_allowed` and `possessions` columns, so only the
  PPG rank line is generated. Perimeter/pace clauses will auto-activate when schema expands.
- **Staleness flags do NOT auto-update `context/nba_season_context.md`** — `detect_staleness_flags()`
  is read-only. Flags are surfaced for human action only — the analyst sees them as ⚠ warnings
  in `pre_game_news.json`, but no agent modifies the context file automatically.
- **`lineups_today.json` IS committed by `analyst.yml`** — added to the commit loop (alongside
  `picks.json`, `parlays.json`, `player_stats.json`) so that the `snapshot_at_analyst_run` key
  written by `write_analyst_snapshot()` persists into the hourly `injuries.yml` runs. Without
  this, `lineup_update.py` would always exit with "no snapshot found — skipping" because each
  hourly checkout started from a clean repo with no `lineups_today.json`. `injuries.yml` does
  NOT commit the file — it only reads and updates it in-place. The file is overwritten fresh
  each morning by the next day's analyst run, so it does not accumulate across days.
  Note: `injuries_today.json` remains uncommitted (refreshed every hourly run, no snapshot
  dependency) — the analogy to `lineups_today.json` is imperfect.
  Note: `write_lineups_json()` in `rotowire_injuries_only.py` now preserves `snapshot_at_analyst_run` across hourly rewrites — fixed March 12, 2026. Prior to this fix, every successful Rotowire parse overwrote the file without the snapshot key, causing `lineup_update.py` to always skip despite the key being committed.
- **`skipped_picks.json` is committed by BOTH `analyst.yml` AND `auditor.yml`** — `analyst.py`
  writes it fresh each morning (null grading fields). `auditor.py` reads it, calls `grade_skips()`
  to fill `would_have_hit` / `skip_verdict` / `skip_verdict_notes` / `actual_value`, then writes
  it back. Both commit steps include it. The auditor's graded version is what `save_audit_summary()`
  rolls up into `audit_summary.json` under `"skip_validation"`. `save_audit_report()` renders the
  per-day skip table in the markdown archive report. This file accumulates only the current day's
  skips (overwritten each morning) — it is not a historical archive.

---

## Workflow Implementation Lesson (from P5 post-mortem, March 2026)

**When implementing a feature that spans multiple workflows, explicitly audit every file the
feature reads at runtime and verify it will be present in each workflow's checkout.**

The P5 Lineup Update Agent (lineup_update.py) was implemented correctly in isolation — the
Python logic, snapshot writing, and diff computation all worked as designed. The blindspot was
`lineups_today.json`: analyst.py wrote it, lineup_update.py read it, but analyst.yml never
committed it. Every hourly injuries.yml run checked out a clean repo, found no
`lineups_today.json`, and silently skipped with "no snapshot found." The feature ran for
multiple days producing zero output with no visible error.

**Checklist for any future cross-workflow feature:**
1. List every file the new agent reads (not just writes).
2. For each file: which workflow writes it? which workflow reads it? are they the same job, or different jobs running at different times?
3. If different jobs: is the file committed between them? If not, the reader will always see a missing or stale file.
4. Check that all commit steps (`git add` loops) in relevant `.yml` files include the new file.
5. Verify the "no file found" graceful-skip log line is actually the expected no-op, not a silent failure masking a missing commit step.
