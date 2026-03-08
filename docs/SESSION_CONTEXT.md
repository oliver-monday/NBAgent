# NBAgent — Session Context & Handoff Reference

**Purpose:** Dense technical handoff for new Claude sessions. Load this alongside `CLAUDE.md`
and `@docs/AGENTS.md` at session start. Covers current implementation state, design decisions,
non-obvious gotchas, and live prompt format — things that take time to re-derive from source.

**Last updated:** March 8, 2026 (Season Context Improvements 0, 1, 2 complete — standings
snapshot, auto-generated team defense narratives, staleness detection in pre_game_reporter)

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
minutes_trend, avg_minutes_last5, minutes_floor,   ← {floor_minutes, avg_minutes, n}; null if <5 games
raw_avgs,
opp_defense,          ← team-level, kept for auditor context injection
game_pace, teammate_correlations,
bounce_back,          ← player-level post-miss profiles + iron_floor + miss anatomy fields
volatility,           ← {PTS/REB/AST/3PM: {label, sigma, n}}
positional_dvp,       ← {position, pts_rating, reb_rating, ast_rating, tpm_rating, n, source}
ft_safety_margin,     ← {label, margin, breakeven_fg_pct, season_fg_pct, n}; null if insufficient FT data
shooting_regression,  ← {fg_hot, fg_cold, fg_pct_l5, fg_pct_l20, n_l5, n_l20}; null if insufficient data
profile_narrative     ← string or null; live portrait for ≥10 non-DNP games + qualifying PTS best tier
```

`opp_defense` is still written to `player_stats.json` even though the analyst no longer reads
`opp_today=` from the quant context block — the auditor's `load_player_stats_for_audit()` slims
entries to 9 fields including `opp_defense`, so it must stay.

`bounce_back` per-stat fields: `{post_miss_hit_rate, lift, iron_floor, n_misses,
near_miss_rate, blowup_rate, typical_miss}`. The Miss Anatomy fields (`near_miss_rate`,
`blowup_rate`, `typical_miss`) are null when fewer than 5 misses — they feed Player Profiles
conditional rendering. Analyst wiring for directive rules is **deferred** pending backtest.

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
**PTS stat line may also show:** `[FG_HOT:+X%]` or `[FG_COLD:−X%]` (shooting regression flag)

---

## Current `build_prompt()` Section Order

1. Task framing + tier system intro
2. Hit definition (`>=`, exact match = HIT)
3. Tier ceiling rules with backtest evidence (REB T8+, AST T6+, PTS T25+, PTS T30 invalid)
4. `## TODAY'S GAMES` (JSON array)
5. `## CURRENT INJURY REPORT` (filtered to today's teams only)
6. `## PRE-GAME NEWS` (conditional — only injected when `pre_game_news.json` has content; critical context flags prepended with ⚠ warning)
7. `## SEASON CONTEXT` (SEASON FACTS only — `## TEAM DEFENSIVE PROFILES` section is stripped from the file at load time; manually maintained)
8. `## PLAYOFF PICTURE` — auto-generated from `data/standings_today.json` (bucketed: safe / contending / playin / bubble / eliminated)
9. `## TEAM DEFENSIVE PROFILES` — auto-generated from `data/team_defense_narratives.json` (last 15g PPG allowed + rank, updates daily via quant.py)
10. `## PLAYER RECENT GAME LOGS` (last 10 games per whitelisted player)
11. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS`
    - KEY RULES — MATCHUP QUALITY (DvP + vs_soft/vs_tough interaction)
    - OPPONENT DEFENSE — POSITIONAL DvP (stat-specific rules, REB/3PM exclusions)
    - SELECTION RULES (offensive-first REB floor rule, tier ceiling conditions, tier walk-down discipline)
    - KEY RULES — REST & FATIGUE (B2B, DENSE, rest_days)
    - KEY RULES — SEQUENTIAL GAME CONTEXT (REB slump-persistent, 3PM cold streak, **3PM trend=down mandatory step-down**)
    - KEY RULES — SPREAD / BLOWOUT RISK (BLOWOUT_RISK flag, spread_abs > 13 cap)
    - KEY RULES — VOLATILITY (−5% for VOLATILE, Top Pick gate, iron_floor override)
    - KEY RULES — HIGH CONFIDENCE GATE 81%+ (Conditions A/B/C)
    - `{quant_context}` — the per-player blocks
12. `## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS` (from `profile_narrative` fields in `player_stats.json`)
13. `## AUDITOR FEEDBACK FROM PREVIOUS DAYS` (last 5 entries)
14. `## ROLLING PERFORMANCE SUMMARY` (from `audit_summary.json`, blank < 3 days)
15. `## ANALYSIS APPROACH` (3-line per-player reasoning format)
16. `## OUTPUT FORMAT` (strict JSON schema — includes `tier_walk` and `iron_floor` fields)

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

---

## Live Agent Function Inventory (non-obvious additions only)

### `quant.py`
- `load_whitelist()` → `set` of `(name_lower, team_upper)` — unchanged, used for mask filtering
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
- `build_player_stats(player_log, b2b_teams, opp_defense, game_pace, todays_games, teammate_correlations, whitelist, game_spreads=None, master_df=None, b2b_game_ids=None, positional_dvp_data=None, position_map=None)` → full `player_stats.json` dict

### `analyst.py`
- `load_player_stats()` → reads `player_stats.json`, returns dict
- `build_quant_context(player_stats)` → formatted string; DvP line per player + stat lines with vol_tag + FG_HOT/FG_COLD annotation on PTS lines
- `load_audit_summary()` → reads `audit_summary.json`, returns "" if < 3 entries
- `load_season_context()` → reads `context/nba_season_context.md`; strips HTML comment header; **strips `## TEAM DEFENSIVE PROFILES` section** (truncates at that heading — file unchanged, only in-memory text is modified); returns "" if missing
- `load_pre_game_news()` → reads `pre_game_news.json`; formats critical flags + player_notes + game_notes + monitor flags; returns "" if no notable items
- `render_playoff_picture(standings_path=STANDINGS_JSON)` → reads `data/standings_today.json`; formats bucketed `## PLAYOFF PICTURE` string; returns fallback string if file missing/stale
- `format_team_defense_section(narratives_path=TEAM_DEFENSE_NARRATIVES_JSON)` → reads `data/team_defense_narratives.json`; validates `as_of == TODAY_STR`; returns `## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated DATE)` block sorted alphabetically; always returns non-empty string (fallback warning if file missing/stale)
- `build_prompt(games, player_context, injuries, audit_context, season_context, quant_context="", audit_summary="", pre_game_news="", player_profiles="", playoff_picture="", team_defense="")` → full system prompt string
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
| BLOWOUT_RISK | Header flag | Confirmed directionally; −1 tier rule |
| spread_abs > 13 | Header flag | Cap at 80% confidence |
| DENSE schedule | Header flag | −5–10% confidence |
| REB opp defense | DvP line REB field | Excluded — not a valid signal |
| 3PM opp defense | DvP line 3PM field | Excluded — noise (lift variance 0.053) |
| 3PM cold streak | Inferred from trend + recent logs | Decline signal (lift=0.87, n=161) |
| 3PM trend=down | Stat line `trend=down` | **Mandatory step-down rule** — pick one tier lower; skip if below T1 |
| PLAYOFF PICTURE | ## PLAYOFF PICTURE section | Situational awareness only — no hard rules |
| TEAM DEFENSIVE PROFILES | ## TEAM DEFENSIVE PROFILES section | Rolling 15g — replaces static file section |

---

## Active Improvement Queue (as of March 8, 2026)

| ID | Name | Status | Files |
|----|------|--------|-------|
| Season Context 0 | Standings Snapshot | ✅ DONE (March 2026) | `espn_daily_ingest.py`, `analyst.py`, `auditor.py` |
| Season Context 1 | Auto-Generated Team Defense Narratives | ✅ DONE (March 2026) | `quant.py`, `analyst.py` |
| Season Context 2 | Staleness Detection in pre_game_reporter | ✅ DONE (March 8, 2026) | `pre_game_reporter.py` |
| Season Context 3 | Restructure SEASON FACTS into decay tiers | Manual edit — no code needed | `context/nba_season_context.md` |
| P3 | Shooting Efficiency Regression | ✅ DONE (March 7–8, 2026) | `espn_player_ingest.py`, `quant.py`, `analyst.py` |
| P5 | Afternoon Lineup Re-Reasoning | Waiting for 7+ days voiding data | `lineup_update.py` (new), `injuries.yml`, `auditor.py`, `build_site.py` |
| P4 | Tier-Walk Audit Trail | ✅ DONE (March 6, 2026) | — |
| #1 | Teammate Absence Delta | Deferred to next season (insufficient DNP sample) | `quant.py`, `analyst.py` |

**Next backtests to run:**
- **H8 — Positional DvP Validity:** Does positional DvP outpredict team-level DvP for PTS/AST? Requires ~30 days of live positional DvP data. Run ~early April 2026.
- **H9 — Player × Opponent H2H Splits:** Does player-vs-specific-opponent hit rate outpredict population opp_defense? Requires near-complete season sample. Run ~mid-April 2026.
- **Miss Anatomy:** Validate `near_miss_rate` / `blowup_rate` next-game prediction. Fields live in `player_stats.json`, analyst wiring deferred until backtest (~late March 2026).

**H6 (post-blowout bounce-back)** and **H7 (opponent schedule fatigue)** are both CLOSED as NOISE (March 7, 2026). Full results in `docs/BACKTESTS.md`.

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
| Team defense narratives | `quant.py` `build_team_defense_narratives()` only |
| Backtest | `agents/backtest.py` — standalone, reads CSVs, writes JSON, no production impact |
| Frontend change | `build_site.py` only — triggers on next injury refresh or analyst run |

---

## What Has NOT Been Done (common assumption errors)

- **Positional DvP has not been backtested** — the rating is structurally sound but unvalidated.
  Weight it appropriately until H8 runs (target: early April 2026 with 30+ days of data).
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
- **Season Context Improvement 3 (SEASON FACTS decay tier restructure) is NOT done** — this is
  a manual edit to `context/nba_season_context.md`. No code required. Do after verifying that
  Improvements 0–2 are running cleanly in production.
- **`team_defense_narratives.json` perimeter and pace clauses are NOT active** — the current
  `team_game_log.csv` schema lacks `fg3_pct_allowed` and `possessions` columns, so only the
  PPG rank line is generated. Perimeter/pace clauses will auto-activate when schema expands.
- **Staleness flags do NOT auto-update `context/nba_season_context.md`** — `detect_staleness_flags()`
  is read-only. Flags are surfaced for human action only — the analyst sees them as ⚠ warnings
  in `pre_game_news.json`, but no agent modifies the context file automatically.
