# NBAgent — Session Context & Handoff Reference

**Purpose:** Dense technical handoff for new Claude sessions. Load this alongside `CLAUDE.md`
and `@docs/AGENTS.md` at session start. Covers current implementation state, design decisions,
non-obvious gotchas, and live prompt format — things that take time to re-derive from source.

**Last updated:** March 5, 2026 (post P2 Volatility + P1 Positional DvP implementation)

---

## Mental Model: Data Flow

```
player_game_log.csv + team_game_log.csv + nba_master.csv
    ↓ quant.py
player_stats.json  (one entry per whitelisted player playing today)
    ↓ analyst.py
picks.json  (appended, result=null until auditor runs)
    ↓ parlay.py
parlays.json  (appended)
    ↓ auditor.py (next morning)
picks.json + parlays.json  (result fields filled)
audit_log.json + audit_summary.json  (written)
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
5. `## INJURY REPORT` (filtered to today's teams only)
6. `## NBA SEASON CONTEXT` (from `context/nba_season_context.md` — manually maintained)
7. `## PLAYER RECENT GAME LOGS` (last 10 games per whitelisted player)
8. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS`
   - KEY RULES — MATCHUP QUALITY (DvP + vs_soft/vs_tough interaction)
   - OPPONENT DEFENSE — POSITIONAL DvP (stat-specific rules, REB/3PM exclusions)
   - SELECTION RULES (offensive-first REB floor rule, tier ceiling conditions)
   - KEY RULES — REST & FATIGUE (B2B, DENSE, rest_days)
   - KEY RULES — SEQUENTIAL GAME CONTEXT (REB slump-persistent, 3PM cold streak)
   - KEY RULES — SPREAD / BLOWOUT RISK (BLOWOUT_RISK flag, spread_abs > 13 cap)
   - KEY RULES — VOLATILITY (−5% for VOLATILE, Top Pick gate, iron_floor override)
   - `{quant_context}` — the per-player blocks
9. `## AUDITOR FEEDBACK FROM PREVIOUS DAYS` (last 5 entries)
10. `## ROLLING PERFORMANCE SUMMARY` (from `audit_summary.json`, blank < 3 days)
11. `## OUTPUT FORMAT` (strict JSON schema)

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
- `build_prompt(games, player_context, injuries, audit_context, season_context, quant_context="", audit_summary="")` → full system prompt string
- `load_season_context()` → reads `context/nba_season_context.md`, returns "" if missing

### `auditor.py`
- `load_player_stats_for_audit(graded_picks)` → slimmed player_stats for just picked players (9 fields)
- `save_audit_summary(audit_log)` → writes `data/audit_summary.json` rolling up entire history
- Miss classification taxonomy: `selection_error` / `model_gap` / `variance` — written to `miss_classification` field in `miss_details`

### `lineup_watch.py` (standalone, runs after each injury refresh)
- Reads `picks.json` + `injuries_today.json`
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

---

## Active Improvement Queue (as of March 5, 2026)

| ID | Name | Blocker | Files |
|----|------|---------|-------|
| P3 | Shooting Efficiency Regression | Requires ingest schema change (`fga/fgm/fg3a/fg3m`) — plan as standalone session | `espn_player_ingest.py`, `quant.py`, `analyst.py` |
| P5 | Afternoon Lineup Re-Reasoning | `lineup_watch.py` live ✅. Wait for 7+ days voiding data | `lineup_update.py` (new), `injuries.yml`, `auditor.py`, `build_site.py` |
| P4 | Tier-Walk Audit Trail | No blocker — fully independent | `analyst.py` (output schema), `auditor.py` |
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

- **`iron_floor` is NOT in `picks.json`** — it exists in `player_stats.json` under `bounce_back`
  and is surfaced in the quant context, but the analyst does not write it to the pick output.
  The `🔒 Iron Floor` badge in Top Picks cards therefore never fires. Future: add `iron_floor`
  as an analyst output field.
- **Positional DvP has not been backtested** — the rating is structurally sound but unvalidated.
  Weight it appropriately until H8 runs.
- **Volatility scores have not been backtested** — σ thresholds (0.3/0.4) are reasonable priors
  but not empirically validated against this dataset. The auditor will accumulate evidence over
  time via the `reasoning` field (volatility flag instruction).
- **P5 (lineup re-reasoning) is NOT live** — `lineup_watch.py` voids/flags picks but does NOT
  call Claude to re-evaluate confidence. Only deterministic status updates happen hourly.
- **`auditor.py` does NOT currently detect lineup_updated picks** — the P5 audit integration
  is described in ROADMAP but not implemented.
