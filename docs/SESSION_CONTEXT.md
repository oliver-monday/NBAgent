# NBAgent — Session Context & Handoff Reference

**Purpose:** Dense technical handoff for new Claude sessions. Load this alongside `CLAUDE.md`
and `@docs/AGENTS.md` at session start. Covers current implementation state, design decisions,
non-obvious gotchas, and live prompt format — things that take time to re-derive from source.

**Last updated:** March 7, 2026 (post-game reporter broadening, auditor absence context, iron_floor propagation, 3PM step-down rule, parlay concentration cap)

---

## Mental Model: Data Flow

```
player_game_log.csv + team_game_log.csv + nba_master.csv
    ↓ quant.py
player_stats.json  (one entry per whitelisted player playing today)
    ↓ pre_game_reporter.py     → pre_game_news.json (ESPN athlete news, prop-filtered, Claude-summarised)
    ↓ analyst.py               → picks.json (appended, result=null until auditor runs)
    ↓ parlay.py                → parlays.json (appended)
    ↓ lineup_watch.py          → picks.json (injury_status_at_check + voided/risk fields, hourly)

    ↓ post_game_reporter.py    → post_game_news.json (ESPN exit/DNP news for yesterday's picks)
    ↓ auditor.py (next morning)
picks.json + parlays.json  (result fields filled)
audit_log.json + audit_summary.json  (written, injury_exclusions in denominator)
    ↓ build_site.py
site/index.html  (deployed to GitHub Pages)
```

Quant runs twice per day: once in `ingest.yml` (for freshness after box scores land), once at
the start of `analyst.yml` (to ensure the analyst sees today's correct data). This is intentional.

---

## Current `player_stats.json` Schema (all keys, in order)

```
team, opponent, games_available, last_updated,
on_back_to_back, rest_days, games_last_7, dense_schedule,
b2b_hit_rates, today_spread, spread_abs, blowout_risk,
tier_hit_rates, matchup_tier_hit_rates, spread_split_hit_rates,
best_tiers, trend, home_away_splits,
minutes_trend, avg_minutes_last5, raw_avgs,
opp_defense,          ← team-level, kept for auditor context injection
game_pace, teammate_correlations,
bounce_back,          ← player-level post-miss profiles + iron_floor flag
volatility,           ← NEW (P2): {PTS/REB/AST/3PM: {label, sigma, n}}
positional_dvp        ← NEW (P1): {position, pts_rating, reb_rating, ast_rating, tpm_rating, n, source}
```

`opp_defense` is still written to `player_stats.json` even though the analyst no longer reads
`opp_today=` from the quant context block — the auditor's `load_player_stats_for_audit()` slims
entries to 9 fields including `opp_defense`, so it must stay.

---

## Current Quant Context Block Format (what the Analyst actually sees per player)

```
Jalen Brunson (vs BOS | spread_abs=5.5 rest=1d L7:4g):
  DvP [PG]: PTS=soft REB=mid AST=tough 3PM=soft (n=52)
  PTS: tier=25 overall=80% vs_soft=85%(14g) vs_tough=62%(11g) competitive=79%(18g) blowout_games=71%(7g) trend=up bb_lift=1.18(6miss) [consistent]
  AST: tier=6 overall=72% vs_soft=n/a vs_tough=68%(11g) competitive=74%(18g) blowout_games=n/a trend=stable [VOLATILE]
```

**Header flags:** `B2B`, `rest=Xd`, `DENSE`, `L7:Xg`, `BLOWOUT_RISK=True`, `spread_abs=X.X`
**DvP line:** one per player (not per stat), covers all 4 stats, shows `(team-lvl)` tag when
the positional sample had < 10 games. `n=` is the number of player-game observations.
**Stat line fields (in order):** `tier` · `overall` · `vs_soft` · `vs_tough` · `competitive` ·
`blowout_games` · `trend` · `b2b=` (only when B2B) · `bb_lift=` or `[iron_floor]` · `[VOLATILE]` or `[consistent]`

---

## Current `build_prompt()` Section Order

1. Task framing + tier system intro
2. Hit definition (`>=`, exact match = HIT)
3. Tier ceiling rules with backtest evidence (REB T8+, AST T6+, PTS T25+, PTS T30 invalid)
4. `## TODAY'S GAMES` (JSON array)
5. `## CURRENT INJURY REPORT` (filtered to today's teams only)
6. `## PRE-GAME NEWS` (conditional — only injected when `pre_game_news.json` has content; critical context flags prepended with ⚠ warning)
7. `## SEASON CONTEXT` (from `context/nba_season_context.md` — manually maintained)
8. `## PLAYER RECENT GAME LOGS` (last 10 games per whitelisted player)
9. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS`
   - KEY RULES — MATCHUP QUALITY (DvP + vs_soft/vs_tough interaction)
   - OPPONENT DEFENSE — POSITIONAL DvP (stat-specific rules, REB/3PM exclusions)
   - SELECTION RULES (offensive-first REB floor rule, tier ceiling conditions, tier walk-down discipline)
   - KEY RULES — REST & FATIGUE (B2B, DENSE, rest_days)
   - KEY RULES — SEQUENTIAL GAME CONTEXT (REB slump-persistent, 3PM cold streak, **3PM trend=down mandatory step-down**)
   - KEY RULES — SPREAD / BLOWOUT RISK (BLOWOUT_RISK flag, spread_abs > 13 cap)
   - KEY RULES — VOLATILITY (−5% for VOLATILE, Top Pick gate, iron_floor override)
   - KEY RULES — HIGH CONFIDENCE GATE 81%+ (Conditions A/B/C)
   - `{quant_context}` — the per-player blocks
10. `## AUDITOR FEEDBACK FROM PREVIOUS DAYS` (last 5 entries)
11. `## ROLLING PERFORMANCE SUMMARY` (from `audit_summary.json`, blank < 3 days)
12. `## ANALYSIS APPROACH` (3-line per-player reasoning format)
13. `## OUTPUT FORMAT` (strict JSON schema — includes `tier_walk` and `iron_floor` fields)

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
runs in analyst, parlay, and auditor.

**Why does positional DvP rank *within position groups* rather than globally?**
A PG averaging 18 pts/game against a team is not directly comparable to a C averaging 18 pts.
Ranking teams separately within each position group (all PG allowed averages ranked against each
other across 30 teams) gives a meaningful "soft/mid/tough for PGs" label. Global ranking would
mix apples and oranges.

**Why is there a 10-game minimum for positional DvP cells?**
With only ~12 whitelisted players per position across 30 teams, some cells will have very few
observations early in a season. Below 10, the variance is too high to trust the rating — the
system falls back to team-level gracefully and marks `source: "team_fallback"`.

**Why does the auditor get `player_stats.json` context?**
The auditor originally had only the pick and the graded box score. Without the quant baseline,
it couldn't distinguish "the data showed 80% and this was a model_gap miss" from "the data
showed 60% and this was a selection_error." Now it can write precise, trackable root causes.

**Why was `PLAYER_WINDOW` raised from 10 to 20?**
Backtest 2 showed w20 improved REB T8 by +7.8pp (to 71.0%), crossing the 70% threshold that
makes it a valid pick. The tradeoff was ~25% fewer total selections — estimated ≥8 picks/day on
typical slates, above the parlay minimum.

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

---

## Live Agent Function Inventory (non-obvious additions only)

### `quant.py`
- `load_whitelist()` → `set` of `(name_lower, team_upper)` — unchanged, used for mask filtering
- `load_whitelist_positions()` → `{name_lower: position}` — new, used only by positional DvP
- `compute_tier_hit_rates(games_df, stat)` → `{str(tier): float}` — uses `>=` grading
- `compute_volatility(game_log_list, stat, tier, window=20)` → `{label, sigma, n}` — takes records NOT DataFrame; must be sorted oldest→newest at call site
- `compute_matchup_tier_hit_rates(all_games_df, opp_defense_dict, stat)` → matchup splits
- `compute_spread_split_hit_rates(player_log_df, game_spreads_dict, stat)` → competitive/blowout splits
- `compute_b2b_hit_rates(player_log_df, b2b_game_ids_dict, stat)` → B2B tier hit rates
- `compute_positional_dvp(player_log_df, position_map_dict)` → `{team: {position: {avgs + ratings}}}`
- `build_bounce_back_profiles(player_log_df, whitelist_set)` → `{player: {stat: {post_miss_hit_rate, lift, iron_floor, n_misses}}}`
- `build_player_stats(player_log, b2b_teams, opp_defense, game_pace, todays_games, teammate_correlations, whitelist, game_spreads=None, master_df=None, b2b_game_ids=None, positional_dvp_data=None, position_map=None)` → full `player_stats.json` dict

### `analyst.py`
- `load_player_stats()` → reads `player_stats.json`, returns dict
- `build_quant_context(player_stats)` → formatted string; DvP line per player + stat lines with vol_tag
- `load_audit_summary()` → reads `audit_summary.json`, returns "" if < 3 entries
- `load_season_context()` → reads `context/nba_season_context.md`, returns "" if missing
- `load_pre_game_news()` → reads `pre_game_news.json`; formats critical flags + player_notes + game_notes + monitor flags; returns "" if no notable items
- `build_prompt(games, player_context, injuries, audit_context, season_context, quant_context="", audit_summary="", pre_game_news="")` → full system prompt string
- Output schema fields: `date, player_name, team, opponent, home_away, prop_type, pick_value, direction, confidence_pct, hit_rate_display, trend, opp_defense_rating, tier_walk, iron_floor, reasoning`

### `auditor.py`
- `load_player_stats_for_audit(graded_picks)` → slimmed player_stats for just picked players (9 fields)
- `build_absence_context(graded_picks)` → returns `## YESTERDAY'S NOTABLE ABSENCES` block (players voided or OUT at check time) or ""
- `save_audit_summary(audit_log)` → writes `data/audit_summary.json`; per-prop and overall denominators exclude `injury_event` picks; `injury_exclusions` key in both per-prop and overall dicts
- Miss classification taxonomy (5 types): `selection_error` / `model_gap` / `variance` / `injury_event` / `workflow_gap` — written to `miss_classification` in `miss_details`
- `build_audit_prompt()` injects: `{absence_block}` before `{news_block}`, ⚠ INJURY LANGUAGE IN NEWS flag on news_lines entries where detected

### `post_game_reporter.py` (runs before auditor each morning)
- `load_yesterdays_player_names()` → set of lowercase names from yesterday's picks
- `load_yesterdays_missed_pick_names()` → subset where `result == "MISS"` or `None`
- `load_athlete_id_map()` → `{player_name_norm: player_id}` from `player_dim.csv`
- `load_yesterday_game_rows(player_names)` → `{name: row_dict}` from `player_game_log.csv`
- `should_fetch(game_row, is_missed_pick=False)` → `(bool, reason)` — reason is one of `missed_pick / dnp_flag / zero_minutes / low_minutes_X / zero_STAT_at_Xmin / normal`
- `news_contains_injury_language(news_items)` → `(bool, matched_term)` — scans `INJURY_SCAN_TERMS` (26 terms) across headline + description
- `fetch_espn_news(athlete_id)` → `(news_items, fetch_ok)`
- `classify_from_news(news_items, minutes, game_row)` → `(event_type, detail, source_url, from_news)` — event_type is `injury_exit / dnp / minutes_restriction / no_data`
- Writes `data/post_game_news.json`: `{date, generated_at, players: {name: {event_type, detail, minutes_played, source_url, confidence, injury_language_detected, injury_scan_term}}, fetch_errors}`
- **Universal fetch:** ALL yesterday's pick players are fetched regardless of box score criteria; `should_fetch()` output used only for logging labels

### `pre_game_reporter.py` (runs between quant and analyst)
- Loads today's team abbrevs from `nba_master.csv`; loads active whitelist players on today's teams
- Fetches ESPN athlete news per player + league-wide news (48h window)
- Filters to prop-relevant items; discards noise keywords (contract/fine/trade rumor)
- ONE Claude call (`claude-sonnet-4-6`, 2048 tokens) if filtered items exist → `player_notes` + `game_notes` dicts + `suggested_context_updates` (urgency: critical/monitor)
- Writes `data/pre_game_news.json`; always writes (empty) even with no news

### `lineup_watch.py` (standalone, runs after each injury refresh)
- Reads `picks.json` + `injuries_today.json`
- Writes `injury_status_at_check` (OUT / DOUBTFUL / QUESTIONABLE / NOT_LISTED) + `injury_check_time` (ISO PT) to **ALL** of today's picks on every run
- OUT → `voided=True` + `void_reason`; DOUBTFUL → `lineup_risk="high"`; QUESTIONABLE → `lineup_risk="moderate"`
- Severity is sticky upward — picks never downgraded
- Name matching is `player_name.lower()` across all teams (avoids abbrev mismatch)

---

## Known Edge Cases and Gotchas

**Team abbreviation variants:** `nba_master.csv` uses legacy 2-char forms (`GS`, `SA`, `NO`,
`UTAH`, `WSH`). `build_site.py` handles this with `_ABBR_NORM` dict and `normAbbr()` JS helper.
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
not a historical archive. The auditor's `load_player_stats_for_audit()` is called at the start
of each audit run before the new quant run overwrites the file. If the auditor runs after quant,
yesterday's positional DvP data may be gone. (Current workflow: ingest → auditor → quant → analyst.
The quant in ingest.yml precedes the auditor, so the auditor sees yesterday's data. Low risk.)

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

**`injury_status_at_check` field in `picks.json`** — written by `lineup_watch.py` on every hourly run to ALL of today's picks (not just open ones). Values: `OUT / DOUBTFUL / QUESTIONABLE / NOT_LISTED`. Used by the auditor's STEP 2 to distinguish `injury_event` (player was NOT_LISTED/QUESTIONABLE at pick time, exited mid-game) from `workflow_gap` (player was OUT/DOUBTFUL pre-game but wasn't voided). If `lineup_watch.py` hasn't run yet when the auditor grades, the field will be absent — auditor handles gracefully.

**`post_game_news.json` fetch errors** — `fetch_errors` list in the output names players whose ESPN API call failed. The auditor receives this in `## POST-GAME NEWS CONTEXT` and should note the gap, not infer absence from missing data. Players without `athlete_id` in `player_dim.csv` are also silently skipped for news fetch (box score inference used instead).

**`iron_floor` field in `picks.json`** — as of March 7, 2026, `iron_floor` is written to all new picks. Pre-March picks don't have the field; `build_site.py` badge logic handles `undefined` gracefully. The field is `true` only when the quant stat line showed `[iron_floor]` — Claude is instructed to copy it directly from the context, not derive it.

**Whitelist filter is a `(name, team)` tuple set**, not name-only. This prevents traded players
from appearing under their old team. If a player is traded mid-season, update `team_abbr` in
`player_whitelist.csv` and set the old entry `active=0`. Do not delete old rows.

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
| trend (up/stable/down) | Stat line | Noise — data shown, no directive weight |
| BLOWOUT_RISK | Header flag | Confirmed directionally; −1 tier rule |
| spread_abs > 13 | Header flag | Cap at 80% confidence |
| DENSE schedule | Header flag | −5–10% confidence |
| REB opp defense | DvP line REB field | Excluded — not a valid signal |
| 3PM opp defense | DvP line 3PM field | Excluded — noise (lift variance 0.053) |
| 3PM cold streak | Inferred from trend + recent logs | Decline signal (lift=0.87, n=161) |
| 3PM trend=down | Stat line `trend=down` | **Mandatory step-down rule** — pick one tier lower; skip if below T1 |

---

## Active Improvement Queue (as of March 7, 2026)

| ID | Name | Blocker | Files |
|----|------|---------|-------|
| P3 | Shooting Efficiency Regression | Requires ingest schema change (`fga/fgm/fg3a/fg3m`) — plan as standalone session | `espn_player_ingest.py`, `quant.py`, `analyst.py` |
| P5 | Afternoon Lineup Re-Reasoning | `lineup_watch.py` live ✅. Wait for 7+ days voiding data | `lineup_update.py` (new), `injuries.yml`, `auditor.py`, `build_site.py` |
| P4 | Tier-Walk Audit Trail | ✅ DONE (March 6, 2026) | — |
| #1 | Teammate Absence Delta | Deferred to next season (insufficient DNP sample) | `quant.py`, `analyst.py` |

**Next backtest to run (H6/H7):** Post-blowout bounce-back and opponent schedule fatigue.
Both testable with existing data — no new ingest needed. Design documented in `docs/BACKTESTS.md`.

**H8 (new):** Validate positional DvP vs. team-level DvP for PTS/AST hit rate prediction.
Run after 30+ days of positional data accumulates (approximately early April 2026).

**Confidence calibration check:** After 20+ audit days (~late March), compare per-band actual
hit rates in `audit_summary.json` against stated confidence bands (70–75 / 76–80 / 81–85 / 86+).
Tighten prompt ceiling if any band systematically underperforms.

---

## Files To Touch Most Often (by task type)

| Task | Files |
|------|-------|
| New quant signal | `quant.py` only (add function + wire in `build_player_stats()` + `main()`) |
| New prompt rule | `analyst.py` `build_prompt()` only |
| New context shown to analyst | `quant.py` `build_player_stats()` + `analyst.py` `build_quant_context()` |
| New pick output field | `analyst.py` OUTPUT FORMAT schema + `build_site.py` pick card renderer |
| Whitelist change | `playerprops/player_whitelist.csv` only (toggle `active` flag) |
| Season context update | `context/nba_season_context.md` only |
| Backtest | `agents/backtest.py` — standalone, reads CSVs, writes JSON, no production impact |
| Frontend change | `build_site.py` only — triggers on next injury refresh or analyst run |

---

## What Has NOT Been Done (common assumption errors)

- **Positional DvP has not been backtested** — the rating is structurally sound but unvalidated.
  Weight it appropriately until H8 runs (target: early April 2026 with 30+ days of data).
- **Volatility scores have not been backtested** — σ thresholds (0.3/0.4) are reasonable priors
  but not empirically validated against this dataset. The auditor will accumulate evidence over
  time via the `reasoning` field (volatility flag instruction).
- **P5 (lineup re-reasoning) is NOT live** — `lineup_watch.py` voids/flags picks and writes
  `injury_status_at_check` per run, but does NOT call Claude to re-evaluate confidence. Only
  deterministic status updates happen hourly.
- **`auditor.py` does NOT currently detect lineup_updated picks** — the P5 audit integration
  is described in ROADMAP but not implemented.
- **`injury_status_at_check` depends on `lineup_watch.py` having run before tip-off** — if
  the workflow fails or runs after a game starts, the field may be absent or stale. The auditor
  uses `.get("injury_status_at_check", "unknown")` and handles missing gracefully.
- **Parlay concentration cap is enforced by Claude prompt, not deterministically** — the
  `## AVOID` rule in `parlay.py` instructs Claude not to use the same leg in 3+ parlays, but
  there is no Python-level filter enforcing this. Verify in the output if the rule seems ignored.
