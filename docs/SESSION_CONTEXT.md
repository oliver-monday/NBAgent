# NBAgent — Session Context & Handoff Reference

**Purpose:** Dense technical handoff for new Claude sessions. Load this alongside `CLAUDE.md`
and `@docs/AGENTS.md` at session start. Covers current implementation state, design decisions,
non-obvious gotchas, and live prompt format — things that take time to re-derive from source.

**Last updated:** March 10, 2026 (P5 Afternoon Lineup Update Agent complete; March 9 additions
documented: OUT/DOUBTFUL hard pre-filter, projected lineup scraping + analyst injection, lineup
watch wiring fix, min_floor cap, BLOWOUT_RISK secondary scorer skip, parlay player-level cap.
Session 2: Rotowire session login + projected_minutes/onoff_usage scraping; analyst lineup
context wiring (proj_min/USG_SPIKE/OPP annotations); knowledge staleness awareness block
in build_prompt())

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
    ↓ analyst.py
         reads lineups_today.json (written by rotowire_injuries_only.py, refreshed at analyst start)
         lineups_today.json optionally contains projected_minutes + onoff_usage per team (when Rotowire creds present)
         load_lineup_context() builds per-team lookup → proj_min/USG_SPIKE/OPP annotations in quant context blocks
         calls write_analyst_snapshot() → stores snapshot_at_analyst_run in lineups_today.json
         OUT/DOUBTFUL pre-filter applied to player_stats before prompt building
         → picks.json (appended, result=null until auditor runs)
    ↓ parlay.py                → parlays.json (appended; OUT/DOUBTFUL excluded)
    ↓ lineup_watch.py          → picks.json (injury_status_at_check + voided/risk fields, hourly)
    ↓ lineup_update.py         → picks.json (lineup_update sub-object on affected picks, hourly)

    ↓ post_game_reporter.py    → post_game_news.json (ESPN exit/DNP news for yesterday's picks)
    ↓ auditor.py (next morning)
picks.json + parlays.json  (result fields filled)
audit_log.json + audit_summary.json  (written, injury_exclusions in denominator)
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
`opp_today=` from the quant context block — the auditor reads quant context from pick object
fields directly (not from `player_stats.json`), but `opp_defense` remains for other consumers.

`bounce_back` per-stat fields: `{post_miss_hit_rate, lift, iron_floor, n_misses,
near_miss_rate, blowup_rate, typical_miss}`. The Miss Anatomy fields (`near_miss_rate`,
`blowup_rate`, `typical_miss`) are null when fewer than 5 misses — they feed Player Profiles
conditional rendering. Analyst wiring for directive rules is **deferred** pending backtest.

---

## Current Quant Context Block Format (what the Analyst actually sees per player)

```
Jalen Brunson (vs BOS | spread_abs=5.5 rest=1d L7:4g proj_min=34 [USG_SPIKE:+7.2pp vs J.Holiday]):
  ⚠ OPP: Jayson Tatum OUT (proj=0min)
  DvP [PG]: PTS=soft REB=mid AST=tough 3PM=soft (n=52)
  PTS: tier=25 overall=80% vs_soft=85%(14g) vs_tough=62%(11g) competitive=79%(18g) blowout_games=71%(7g) trend=up bb_lift=1.18(6miss) [consistent]
  AST: tier=6 overall=72% vs_soft=n/a vs_tough=68%(11g) competitive=74%(18g) blowout_games=n/a trend=stable [VOLATILE]
```

**Header flags:** `B2B`, `rest=Xd`, `DENSE`, `L7:Xg`, `BLOWOUT_RISK=True`, `spread_abs=X.X`, `proj_min=N` (Rotowire projected minutes, when creds present), `[USG_SPIKE:+N.Npp vs X.Name]` (usage spike ≥5pp + ≥100 min sample, when creds present)
**After DvP line (optional):** `⚠ OPP: Name OUT (proj=0min)` — opponent player with 0 projected minutes per Rotowire; capped at 3 entries; only emitted when Rotowire creds present
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
9. `## TEAM DEFENSIVE PROFILES` — auto-generated from `data/team_defense_narratives.json` (last 15g PPG allowed + rank, updates daily via quant.py)
10. `## PLAYER RECENT GAME LOGS` (last 10 games per whitelisted player)
11. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS`
    - KEY RULES — MATCHUP QUALITY (DvP + vs_soft/vs_tough interaction)
    - OPPONENT DEFENSE — POSITIONAL DvP (stat-specific rules, REB/3PM exclusions)
    - SELECTION RULES (offensive-first REB floor rule, tier ceiling conditions, tier walk-down discipline; **LINEUP CONTEXT** rule — use ## PROJECTED LINEUPS as ground truth for who is playing)
    - KEY RULES — REST & FATIGUE (B2B, DENSE, rest_days)
    - KEY RULES — SEQUENTIAL GAME CONTEXT (REB slump-persistent, 3PM cold streak, **3PM trend=down mandatory step-down**)
    - KEY RULES — SPREAD / BLOWOUT RISK (BLOWOUT_RISK flag, spread_abs > 13 cap; BLOWOUT_RISK secondary scorer skip for underdog non-primary scorers)
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
- `BLOWOUT_RISK secondary scorer skip` — spread ≥ +8 underdog AND non-primary scorer → PTS pick skipped
- `AST T4+ hard gate` — PF/C or raw_avgs AST < 4.0 → opponent AST DvP must be "soft"; skip on mid/tough
- `3PM hard skip` — trend=down AND avg_minutes_last5 ≤ 30 → skip all 3PM picks including T1

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

### `ingest/rotowire_injuries_only.py`
- `ROTOWIRE_LOGIN_URL` — constant for Rotowire login endpoint
- `login_rotowire(session: requests.Session) → bool` — reads `ROTOWIRE_EMAIL`/`ROTOWIRE_PASSWORD` env vars; POSTs to login URL; returns `False` (not crash) if creds missing or HTTP != 200; returns `True` when session is authenticated
- `fetch_rotowire_html(session: requests.Session | None = None) → str | None` — refactored to accept optional session; `requester = session if session is not None else requests`; backward-compatible for callers without session
- `parse_rotowire_lineups(html) → dict` — BeautifulSoup parse of Rotowire projected starters; returns `{team_abbr: {"starters": [{name, position}], "confirmed": bool}}`; walks `<li>` elements with PG/SG/SF/PF/C position labels + player `<a>` links
- `parse_projected_minutes(soup: BeautifulSoup) → dict[str, list[dict]]` — parses subscription-gated Projected Minutes panel; finds `.lineups-viz` containers; identifies team via `find_previous_siblings()` walk on `data-team` attribute (with nested button fallback); extracts `{name, minutes, section, injury_status}` per player; returns `{}` on any exception (graceful degradation)
- `parse_onoff_usage(soup: BeautifulSoup) → dict[str, list[dict]]` — parses subscription-gated On/Off Court Stats panel; finds `.lineups-viz__off-usage-screen`; resolves absent player names via `data-out` ID → `data-athlete-id` map built from `<a data-athlete-id>` tags in the viz container; extracts `{name, usage_pct, usage_change, minutes_sample, absent_players}`; returns `{}` on any exception
- `write_lineups_json(lineups, asof_date, built_at_utc, projected_minutes: dict | None = None, onoff_usage: dict | None = None)` — extended signature; merges `projected_minutes` and `onoff_usage` dicts into per-team payload before atomic write to `data/lineups_today.json`
- Guard condition in `main()`: if parsed 0 teams but existing file has teams for today, keeps existing (protects against partial scrape overwriting good data)
- Session flow in `main()`: creates `requests.Session()`; calls `login_rotowire(session)`; passes session to `fetch_rotowire_html(session)`; calls `parse_projected_minutes()`/`parse_onoff_usage()` only when `authenticated=True`
- Output: `data/lineups_today.json` keys: `asof_date`, `built_at_utc`, `source`, per-team dicts with `starters` + `confirmed`; optional `projected_minutes` + `onoff_usage` per team when Rotowire creds present and scrape succeeds; `snapshot_at_analyst_run` key added later by analyst.py

### `analyst.py`
- `_ABBR_NORM` dict + `_norm_team(abbr)` + `_extract_last(raw_name)` — normalization helpers (mirrors `lineup_watch.py` and `build_site.py`); `_extract_last` handles "J. Brunson" style Rotowire names
- `load_out_players() → set[tuple[str, str]]` — reads `injuries_today.json`; returns `{(last_name_lower, norm_team_upper)}` for all OUT/DOUBTFUL players; used in `main()` to pre-filter `player_stats` before any prompt building; Claude never receives stats for excluded players
- `format_lineups_section(lineups_path=LINEUPS_JSON, today_teams=None) → str` — reads `lineups_today.json`; staleness-checks `asof_date == TODAY_STR`; loads game pairings from MASTER_CSV; loads injuries for key absences; returns formatted `## PROJECTED LINEUPS` block (starters + key absences per game pair); falls back to `"[Lineup data unavailable — injury report only]"` if file missing/stale
- `write_analyst_snapshot(lineups_path, picks_run_at_iso) → None` — writes `snapshot_at_analyst_run` key into `lineups_today.json` capturing starters + confirmed flag per team at pick time; guards against double-snapshot (returns immediately if key already exists); atomic write via `.tmp` rename; called in `main()` after `format_lineups_section()`, before `build_prompt()`
- `load_player_stats()` → reads `player_stats.json`, returns dict
- `load_lineup_context() → dict[str, dict]` — reads `lineups_today.json`; staleness-checks `asof_date == TODAY_STR`; skips metadata keys (`asof_date`, `built_at_utc`, `source`, `snapshot_at_analyst_run`); builds `{norm_team: {"projected_minutes": {name_lower: {minutes, section}}, "onoff_usage": {name_lower: {usage_pct, usage_change, minutes_sample, absent_players}}}}`; returns `{}` silently if missing/stale; logs team count on success
- `build_quant_context(player_stats: dict, lineup_context: dict | None = None) → str` — updated signature; DvP line per player + stat lines with vol_tag + FG_HOT/FG_COLD; new per-player annotations: `proj_min=N` appended to header when projected minutes present; `[USG_SPIKE:+N.Npp vs X.Name]` appended to header when `usage_change ≥ 5.0` AND `minutes_sample ≥ 100` (absent player abbreviated as `F.Lastname`); `⚠ OPP: Name OUT (proj=0min)` lines after DvP (only `section=="OUT"` or `minutes==0` from opponent team, capped at 3)
- `load_audit_summary()` → reads `audit_summary.json`, returns "" if < 3 entries
- `load_season_context()` → reads `context/nba_season_context.md`; strips HTML comment header; **strips `## TEAM DEFENSIVE PROFILES` section** (truncates at that heading — file unchanged, only in-memory text is modified); returns "" if missing
- `load_pre_game_news()` → reads `pre_game_news.json`; formats critical flags + player_notes + game_notes + monitor flags; returns "" if no notable items
- `render_playoff_picture(standings_path=STANDINGS_JSON)` → reads `data/standings_today.json`; formats bucketed `## PLAYOFF PICTURE` string; returns fallback string if file missing/stale
- `format_team_defense_section(narratives_path=TEAM_DEFENSE_NARRATIVES_JSON)` → reads `data/team_defense_narratives.json`; validates `as_of == TODAY_STR`; returns `## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated DATE)` block sorted alphabetically; always returns non-empty string (fallback warning if file missing/stale)
- `build_prompt(games, player_context, injuries, audit_context, season_context, quant_context="", audit_summary="", pre_game_news="", player_profiles="", playoff_picture="", team_defense="", lineups_section="")` → full system prompt string
- Output schema fields: `date, player_name, team, opponent, home_away, prop_type, pick_value, direction, confidence_pct, hit_rate_display, trend, opp_defense_rating, tier_walk, iron_floor, reasoning`

### `agents/lineup_update.py` (new — March 10, 2026)
- Constants: `MODEL = "claude-sonnet-4-6"`, `MAX_TOKENS = 2048`, `CUTOFF_MINUTES = 20`
- `_ABBR_NORM` dict + `_norm(abbr)` — same normalization pattern as rest of codebase
- `load_game_map() → dict[str, str]` — `{norm_team_abbr: game_time_utc}` from `nba_master.csv`; used to check tip-off cutoff per pick
- `game_is_actionable(game_time_utc, now_et) → bool` — True if tip-off > CUTOFF_MINUTES away; True on parse failure (safe default — don't skip on bad data)
- `compute_lineup_diff(lineups, injuries) → list[dict]` — diffs `snapshot_at_analyst_run` vs current lineups + injuries; returns change events `{team, player_name, change_type, status, detail}`; change_type is `"new_absence"` (was starter, now OUT/DOUBTFUL) or `"starter_replaced"` (was starter, no longer listed, not injured)
- `get_affected_picks(today_picks, changes, game_map, now_et) → list[dict]` — returns open today picks (result=None, not voided) where `team` OR `opponent` in changed teams AND game still actionable
- `build_rotowire_context(lineups, changed_teams) → str` — reads `projected_minutes` and `onoff_usage` from `lineups_today.json` for each team in `changed_teams`; formats starters/bench/out projected minutes and on/off usage deltas as a plain-text block; returns `""` when no Rotowire data present (graceful no-op on unauthenticated runs)
- `call_lineup_update(affected_picks, changes, rotowire_context="") → list[dict]` — single Claude call; system prompt uses prop-type-aware direction guide (PTS/REB/AST/3PM each with separate up/down/unchanged logic + magnitude calibration from Rotowire usage); `rotowire_context` injected as `## ROTOWIRE PROJECTIONS FOR CHANGED TEAMS` in user message when non-empty; returns `[{player_name, prop_type, direction, revised_confidence_pct, revised_reasoning}]`; extracts JSON array via `raw.find("[") … raw.rfind("]")`
- `apply_amendments(all_picks, amendments, affected_picks, changes, now_iso) → tuple[int,int,int]` — writes `lineup_update` sub-objects in-place to `all_picks`; returns `(n_amended, n_up, n_down)`; keyed by `(player_name_lower, prop_type)`
- `main()` — full no-op logic with 5 guard conditions; computes `changed_teams` set, calls `build_rotowire_context()`, passes result to `call_lineup_update()`; atomic write via `.tmp` rename; logs `changes=N affected_picks=M amended=K (X up, Y down, Z unchanged)`

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
- `build_absence_context(graded_picks)` → returns `## YESTERDAY'S NOTABLE ABSENCES` block (players voided or OUT at check time) or ""
- `save_audit_summary(audit_log)` → writes `data/audit_summary.json`; per-prop and overall denominators exclude `injury_event` picks; `injury_exclusions` key in both per-prop and overall dicts
- Miss classification taxonomy (6 types): `selection_error` / `model_gap_signal` / `model_gap_rule` / `variance` / `injury_event` / `workflow_gap` — written to `miss_classification` in `miss_details`. `model_gap_signal` = system lacks the signal entirely (no quant field or rule exists that could have caught this); `model_gap_rule` = signal existed in quant data/context at pick time but the analyst rule didn't correctly handle the combination. The legacy `model_gap` value is no longer valid.
- `build_audit_prompt()` injects: `{absence_block}` before `{news_block}`, ⚠ INJURY LANGUAGE IN NEWS flag on news_lines entries where detected. STEP 6 of PICK ANALYSIS TASK reads `lineup_update` sub-objects on pick objects and annotates amendment direction vs. outcome in `root_cause` (direction=down + miss → "Amendment correctly flagged…"; direction=up + miss → "Amendment flagged upside but pick missed"; direction=down + hit → "Amendment flagged downside but pick hit"; direction=unchanged or absent → no comment). Does not change `miss_classification` — amendment notes are contextual only.
- **`load_player_stats_for_audit()` was REMOVED (March 8, 2026)** — eliminates yesterday's-data-for-today's-audit confabulation bug. Auditor now reads quant context from pick object fields (`reasoning`, `hit_rate_display`, `tier_walk`, `opponent`) written at pick time.

### `post_game_reporter.py` (runs before auditor each morning)
- `load_yesterdays_player_names()` → set of lowercase names from yesterday's picks
- `load_yesterdays_missed_pick_names()` → subset where `result == "MISS"` or `None`
- `load_athlete_id_map()` → `{player_name_norm: player_id}` from `player_dim.csv`
- `load_yesterday_game_rows(player_names)` → `{name: row_dict}` from `player_game_log.csv`
- `should_fetch(game_row, is_missed_pick=False)` → `(bool, reason)` — reason is one of `missed_pick / dnp_flag / zero_minutes / low_minutes_X / zero_STAT_at_Xmin / normal`
- `news_contains_injury_language(news_items)` → `(bool, matched_term)` — scans `INJURY_SCAN_TERMS` (26 terms) across headline + description
- `fetch_espn_news(athlete_id)` → `(news_items, fetch_ok)`
- `classify_from_news(news_items, minutes, game_row)` → `(event_type, detail, source_url, from_news)` — event_type is `injury_exit / dnp / minutes_restriction / no_data`
- `_get_miss_pick_meta(player_name_lower)` → `{prop_type, pick_value, actual_value, team}` — reads first MISS/ungraded pick for the player on YESTERDAY_STR from `picks.json`; returns `{}` if not found
- `fetch_web_narratives(missed_players)` → `{name_lower: raw_snippet_text}` — Brave Search API; one query per missed-pick player (`"{name} {team} NBA recap {date}"`); `count=3` results; returns `{}` if `BRAVE_API_KEY` not set or all searches fail; graceful per-player error handling
- `call_claude_summarise_narratives(missed_players, raw_snippets)` → `{name_lower: narrative_str}` — single batch Claude call (`claude-sonnet-4-6`, max_tokens=2048); extracts factual one-to-two sentence miss explanation per player from snippets; returns `{}` if `ANTHROPIC_API_KEY` not set or API fails; only called when at least one snippet exists
- Writes `data/post_game_news.json`: `{date, generated_at, players: {name: {event_type, detail, minutes_played, source_url, confidence, injury_language_detected, injury_scan_term, web_narrative}}, fetch_errors}` — `web_narrative` is a string for missed players with Brave snippets, `null` otherwise; present on all entries
- **Universal fetch:** ALL yesterday's pick players are fetched regardless of box score criteria; `should_fetch()` output used only for logging labels
- **Web narrative layer (March 11, 2026):** runs AFTER the ESPN loop, scoped to missed-pick players only; `BRAVE_API_KEY` secret injected in `auditor.yml`; Auditor `build_audit_prompt()` renders `web_narrative` as `📰 WEB RECAP:` line in `## POST-GAME NEWS CONTEXT` block

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

---

## Known Edge Cases and Gotchas

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

**`lineups_today.json` guard condition** — `rotowire_injuries_only.py` will NOT overwrite a
good existing file with 0 teams parsed. If a scrape returns 0 starters (e.g., Rotowire is slow
pre-noon), the existing file for today's date is preserved. Only non-zero parses overwrite.

**`snapshot_at_analyst_run` in `lineups_today.json`** — written ONCE by `write_analyst_snapshot()`
in `analyst.py` at pick time. Idempotent: if the key already exists, the function returns
immediately without overwriting. This ensures the morning baseline is frozen even if the analyst
workflow runs again. `lineup_update.py` treats absence of this key as a skip condition.

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
| BLOWOUT_RISK | Header flag | Confirmed directionally; −1 tier rule + secondary scorer skip |
| spread_abs > 13 | Header flag | Cap at 80% confidence |
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
| ⚠ OPP: Name OUT (proj=0min) | After DvP line | Opponent key player with 0 projected minutes per Rotowire; supports matchup assessment; absent when creds not present |

---

## Active Improvement Queue (as of March 10, 2026)

| ID | Name | Status | Files |
|----|------|--------|-------|
| Season Context 0 | Standings Snapshot | ✅ DONE (March 2026) | `espn_daily_ingest.py`, `analyst.py`, `auditor.py` |
| Season Context 1 | Auto-Generated Team Defense Narratives | ✅ DONE (March 2026) | `quant.py`, `analyst.py` |
| Season Context 2 | Staleness Detection in pre_game_reporter | ✅ DONE (March 8, 2026) | `pre_game_reporter.py` |
| Season Context 3 | Restructure SEASON FACTS into decay tiers | Manual edit — no code needed | `context/nba_season_context.md` |
| P3 | Shooting Efficiency Regression | ✅ DONE (March 7–8, 2026) | `espn_player_ingest.py`, `quant.py`, `analyst.py` |
| P4 | Tier-Walk Audit Trail | ✅ DONE (March 6, 2026) | — |
| P5 | Afternoon Lineup Update Agent | ✅ DONE (March 10, 2026) | `analyst.py`, `agents/lineup_update.py` (new), `injuries.yml`, `build_site.py`, `AGENTS.md` |
| #1 | Teammate Absence Delta | Deferred to next season (insufficient DNP sample) | `quant.py`, `analyst.py` |

**Also completed March 9 (not in prior queue but shipped):**
- Lineup Watch wiring fix — `lineup_watch.py` now actually in `injuries.yml` chain; name matching hardened; stale flag clearing added
- Analyst OUT/DOUBTFUL hard pre-filter — `load_out_players()` + Python-level filter before prompt building; `parlay.py` also filters
- Projected Lineup Scraping + Analyst Injection — `rotowire_injuries_only.py` parses starters → `lineups_today.json`; `## PROJECTED LINEUPS` in analyst prompt
- Hard analyst gates — min_floor confidence cap (floor_minutes < 24 → max 84%), BLOWOUT_RISK secondary scorer PTS skip, AST T4+ hard gate for PF/C, 3PM hard skip for trend=down + low minutes
- Parlay player-level concentration cap — Python enforcement in `parlay.py` (no single player_name in 3+ parlays regardless of prop type)

**Also completed March 10, Session 2:**
- Rotowire session login + projected_minutes/onoff_usage scraping — `login_rotowire()`, `parse_projected_minutes()`, `parse_onoff_usage()` added to `rotowire_injuries_only.py`; `write_lineups_json()` extended with optional params; `lineups_today.json` optionally carries per-team projected minutes + on/off usage when Rotowire creds present; `ROTOWIRE_EMAIL`/`ROTOWIRE_PASSWORD` env vars injected into both `injuries.yml` and `analyst.yml`
- Analyst lineup context wiring — `load_lineup_context()` in `analyst.py`; `proj_min=N`, `[USG_SPIKE:+N.Npp vs Name]`, and `⚠ OPP: Name OUT` annotations in `build_quant_context()`; `main()` wired to load and pass lineup context
- Knowledge staleness awareness block — `## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE` inserted in `build_prompt()` between date line and `## YOUR TASK`; perishable vs. durable knowledge distinction; instructs Claude to trust injected data over training priors on named-player/team facts
- Analyst coverage + Opus hybrid — `LARGE_SLATE_THRESHOLD=30`; `MODEL_LARGE=claude-opus-4-6`; `call_analyst(model=)` param; `main()` conditionally upgrades to Opus when active player count (post injury pre-filter) > 30; `## ANALYSIS APPROACH` block enforces all-four-prop enumeration per player in fixed order (PTS→REB→AST→3PM); skip records excluded from JSON output

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
| Lineup update rules | `agents/lineup_update.py` `call_lineup_update()` system/user prompt only |

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
