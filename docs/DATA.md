# NBAgent — Data Reference

---

## CSV Schemas

### nba_master.csv (17 columns)
```
game_id, game_date, game_time_utc,
home_team_name, home_team_abbrev, home_score, home_ml, home_spread,
away_team_name, away_team_abbrev, away_score, away_ml, away_spread,
venue_city, venue_state, home_injuries, away_injuries
```
Source: `espn_daily_ingest.py`. One row per game. `game_time_utc` is ISO format.

**Spread convention:** `home_spread` is signed from the home team's perspective. Negative = home team is favored (e.g., `-6.5` means home gives 6.5 points). `away_spread` is the mirror.

**Spread coverage:** 829/935 rows have spreads (88.7%). Sources:
- ESPN Core odds API — collects spreads for today's pre-game rows going forward (March 2026+)
- Pinnacle closing lines backfill (`ingest/backfill_spreads.py`) — filled historical rows from Oct 21 2025 through early March 2026

Remaining 106 null rows: ~4 All-Star game entries, ~20 games with no Pinnacle coverage, and ~82 games from mid-Jan through Feb where the Pinnacle scraper stopped collecting before game day and the gap exceeded the 3-day tolerance. Coverage accumulates going forward via ESPN.

### player_game_log.csv (24 columns)
```
season_end_year, game_id, game_date, team_abbrev, opp_abbrev,
home_away, player_id, player_name, started, minutes, minutes_raw,
pts, reb, ast, tpm, fgm, fga, fg3m, fg3a, ftm, fta, dnp, team_hint_ok, ingested_at
```
Source: `espn_player_ingest.py`. One row per player per game.  
`dnp = "1"` rows are kept but excluded from analytics.  
`home_away`: `"H"` or `"A"`.

### team_game_log.csv
```
game_id, game_date, team_abbrev, opp_abbrev, home_away,
team_pts, team_reb, team_ast, team_tpm
```
Source: `espn_player_ingest.py`. Aggregated from player rows. Used by Quant for opponent defense, game pace, and team defense narratives.

### player_dim.csv
```
player_id, player_name, team_abbrev
```
ESPN athlete_id → name mapping. Used during ingest for name normalization.

---

## JSON Schemas

### injuries_today.json
```json
{
  "fetched_at": "ISO timestamp",
  "TEAM_ABBREV": [
    {
      "player_name": "string",
      "status": "OUT|DOUBTFUL|QUESTIONABLE|PROBABLE",
      "reason": "string"
    }
  ]
}
```
Non-list keys are metadata. List keys are team rosters. Updated hourly by `rotowire_injuries_only.py`.

### player_stats.json
Quant output. One entry per whitelisted player playing today.
```json
{
  "Player Name": {
    "team": "abbrev",
    "whitelisted_teammates": ["Name1", "Name2"],  // sorted list of other active whitelisted players on same team playing today; [] when none
    "opponent": "abbrev",
    "games_available": 20,
    "last_updated": "YYYY-MM-DD",
    "on_back_to_back": false,
    "rest_days": 2,               // days since team's last game (0=B2B, 1=1 day rest, etc.); null if no history
    "games_last_7": 4,            // games played in the 7 days before today
    "dense_schedule": false,      // true when 4+ games played in the last 5 days
    "b2b_hit_rates": {
      "PTS": {"hit_rates": {"10": 1.0, "15": 0.9, "20": 0.7, "25": 0.5, "30": 0.2}, "n": 8},
      "REB": null,                // null = fewer than 5 B2B games (Analyst applies one-tier-down)
      "AST": {"hit_rates": {...}, "n": 6},
      "3PM": null
    },
    "today_spread": -6.5,         // signed for this team (neg = favored); null if unavailable
    "spread_abs": 6.5,            // absolute value; null if unavailable
    "blowout_risk": false,        // true when is_favorite AND spread_abs > 8.0
    "tier_hit_rates": {
      "PTS": {"10": 1.0, "15": 0.9, "20": 0.7, "25": 0.3, "30": 0.1},
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "matchup_tier_hit_rates": {
      "PTS": {
        "20": {"soft": {"hit_rate": 0.91, "n": 11}, "mid": {"hit_rate": 0.72, "n": 18}, "tough": {"hit_rate": 0.58, "n": 12}},
        "25": {"soft": {"hit_rate": 0.64, "n": 11}}
      },
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "spread_split_hit_rates": {
      "PTS": {
        "competitive": {"hit_rates": {"10": 1.0, "15": 0.85, "20": 0.71, "25": 0.43, "30": 0.14}, "n": 14},
        "blowout":     {"hit_rates": {"10": 1.0, "15": 0.78, "20": 0.56, "25": 0.22, "30": 0.0},  "n": 9}
      },
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "best_tiers": {
      "PTS": {"tier": 20, "hit_rate": 0.7},
      "REB": null, "AST": null, "3PM": null
    },
    "trend": {"PTS": "up", "REB": "stable", "AST": "down", "3PM": "stable"},
    "home_away_splits": {
      "PTS": {"H": {"tier": 25, "hit_rate": 0.83}, "A": {"tier": 20, "hit_rate": 0.71}}
    },
    "minutes_trend": "stable",
    "avg_minutes_last5": 34.2,
    "minutes_floor": {            // null if insufficient data
      "floor_minutes": 29.4,      // lower bound below which player is unlikely to play
      "avg_minutes": 34.1,        // season avg minutes (non-DNP games)
      "n": 18                     // games used in computation
    },
    "raw_avgs": {"PTS": 22.1, "REB": 5.4, "AST": 6.1, "3PM": 1.8},
    "opp_defense": {
      "PTS": {"allowed_pg": 112.4, "rank": 28, "n_teams": 30, "rating": "soft"},
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "game_pace": {"combined_pts_avg": 224.1, "pace_tag": "high", "source": "h2h"},
    "team_momentum": {                        // null if no completed games data
      "team":     {"l10_wins": 7, "l10_losses": 3, "l10_pct": 0.70, "l10_margin": 5.2, "tag": "hot"},
      "opponent": {"l10_wins": 4, "l10_losses": 6, "l10_pct": 0.40, "l10_margin": -1.8, "tag": "neutral"}
    },
    "def_recency": "soft|tough|null",         // opponent L5 vs L15 PTS-allowed divergence ≥8%; null when neutral or insufficient data
    "teammate_correlations": {
      "Teammate Name": {
        "shared_games": 18,
        "correlations": {
          "AST_PTS": {"r": 0.71, "tag": "feeder_target"},
          "PTS_PTS": {"r": -0.08, "tag": "independent"}
        }
      }
    },
    "bounce_back": {
      "PTS": {
        "post_miss_hit_rate": 0.71,   // hit rate in game immediately following a miss
        "lift": 0.12,                 // pp delta vs baseline hit rate
        "iron_floor": false,          // true if hit rate never drops below floor after a miss
        "n_misses": 7,                // total misses at best tier in window
        "near_miss_rate": 0.43,       // fraction of misses within 2 units of tier; null if n_misses < 5
        "blowup_rate": 0.57,          // fraction of misses 3+ units below tier; null if n_misses < 5
        "typical_miss": 3.0           // median shortfall on miss games (units); null if n_misses < 5
      },
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "volatility": {
      "PTS": "consistent|moderate|volatile",   // per stat classification
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "positional_dvp": {
      "PTS": {"allowed_pg": 24.1, "rank": 22, "rating": "soft"},
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "ft_safety_margin": {         // null if insufficient FT data (H11)
      "label": "FT-dependent",    // FT-dependent | FT-contributor | FG-dependent | balanced
      "margin": 3.2,              // pp headroom before FT contribution fails to cover FG drop
      "breakeven_fg_pct": 0.41,   // FG% at which FT contribution exactly compensates
      "season_fg_pct": 0.47,      // season baseline FG% for reference
      "n": 22                     // games used
    },
    "shooting_regression": {      // null if insufficient data (P3)
      "fg_hot": 0.54,             // FG% in top-tercile scoring games (last 20)
      "fg_cold": 0.38,            // FG% in bottom-tercile scoring games (last 20)
      "fg_pct_l5": 0.51,          // FG% over last 5 games
      "fg_pct_l20": 0.46,         // FG% over last 20 games
      "n_l5": 5,
      "n_l20": 20
    },
    "profile_narrative": "string | null"  // null if player doesn't meet eligibility threshold
                                          // (≥10 non-DNP games + qualifying PTS best tier)
  }
}
```

### standings_today.json
Written daily by `espn_daily_ingest.py`. Source: ESPN standings endpoint.
```json
{
  "as_of": "YYYY-MM-DD",
  "east": [
    {
      "seed": 1,
      "abbr": "CLE",
      "wins": 49,
      "losses": 14,
      "gb_from_8th": -35.0,       // negative = ahead of 8th seed; positive = behind
      "gb_from_playin": -37.0,    // negative = ahead of 10th seed
      "bucket": "safe"            // safe | contending | playin | bubble | eliminated
    }
  ],
  "west": [...]
}
```

**Bucket definitions:**
- `safe` — seed 1–8, 5+ game cushion on 9th seed
- `contending` — seed 1–8, within 3 games of losing playoff spot
- `playin` — seed 9–10
- `bubble` — seed 11–12, within 3 games of play-in cutoff
- `eliminated` — 15+ games back of play-in

Teams outside all buckets (between bubble and eliminated) are stored in the JSON but omitted from the analyst prompt snapshot — clutter without narrative value.

Consumed by: `analyst.py` and `auditor.py` (injected as `## PLAYOFF PICTURE` block).

### team_defense_narratives.json
Written daily by `build_team_defense_narratives()` in `quant.py`. Computed from `team_game_log.csv` last 15 games.
```json
{
  "as_of": "YYYY-MM-DD",
  "narratives": {
    "UTA": "UTA (last 15g): Allows 118.4 PPG (rank: 29th). Weak perimeter defense — opponents shooting 42.1% from 3 (rank: 28th). High pace (103.2 poss/g). Inflates all counting stats.",
    "CLE": "CLE (last 15g): Allows 106.2 PPG (rank: 3rd). Strong perimeter defense — opponents shooting 33.1% from 3 (rank: 2nd).",
    "...": "..."
  }
}
```

All 30 teams present. Narrative components: PPG allowed + league rank (always); 3P% allowed + rank (if column available in `team_game_log.csv`); pace classification (if column available and noteworthy — only high/low pace included, average omitted).

Replaces the static `## TEAM DEFENSIVE PROFILES` section in `nba_season_context.md` for analyst prompt injection. The static section remains in the file as a reference but is not read by any agent.

Consumed by: `analyst.py` only (injected as `## TEAM DEFENSIVE PROFILES` block).

### pre_game_news.json
Written by `pre_game_reporter.py`. Contains ESPN news headlines cross-referenced against season context, plus deterministic staleness flags.
```json
{
  "fetched_at": "ISO timestamp",
  "headlines": [...],
  "context_conflicts": ["string"],   // from Claude news cross-reference pass
  "staleness_flags": [               // from deterministic date-parsing pass
    "⚠ CONTEXT FLAG: Jayson Tatum — Return/injury note is 8 days old. Verify current status before picking this player.",
    "..."
  ]
}
```

All flags (both passes) also written to `context/context_flags.md` as `⚠ CONTEXT FLAG: ...` lines. Picked up by `analyst.py` via existing context flag mechanism.

### picks.json
Flat list of all picks, all dates. `result` and `actual_value` are null until Auditor runs.
```json
[{
  "date": "YYYY-MM-DD",
  "player_name": "string",
  "team": "abbrev",
  "opponent": "abbrev",
  "home_away": "H|A",
  "prop_type": "PTS|REB|AST|3PM",
  "pick_value": number,
  "direction": "OVER",
  "confidence_pct": 70-99,
  "hit_rate_display": "8/10",
  "trend": "up|stable|down",
  "opp_defense_rating": "soft|mid|tough|unknown",
  "reasoning": "string",
  "result": "HIT|MISS|NO_DATA|null",  // null until auditor runs; voided=True picks always have result=null
  "actual_value": number|null,          // null until auditor runs; voided=True picks always have actual_value=null
  "game_time": "7:30 PM PT",
  "human_verdict": "keep|trim|manual_skip|null",  // tagged by auditor from picks_review file; null when not reviewed
  "trim_reasons":  ["string"] | [],               // reasons from review file; [] when not reviewed
  "is_skip": false                                 // true when Analyst concluded skip; filtered by filter_self_skip_picks() before publication; defaults to false in save_picks() when field absent
}]
```

### picks_review_YYYY-MM-DD.json
Daily review file. Written by the Review agent (`analyst.py` Stage 3) or manually in Claude chat sessions; committed before `auditor.yml` runs. Manual files take priority — Review skips writing if the file already exists.
```json
// Filename: data/picks_review_YYYY-MM-DD.json (yesterday's date when auditor runs)
[{
  "date":         "YYYY-MM-DD",
  "player_name":  "string",
  "team":         "abbrev",
  "prop_type":    "PTS|REB|AST|3PM",
  "pick_value":   number,
  "verdict":      "keep|trim|manual_skip",
  "trim_reasons": ["string"],  // required when verdict=="trim"; [] otherwise
  "source":       "auto"       // "auto" for Review-generated; absent on manual files
}]
```

Join key (used by auditor): `(player_name.strip().lower(), prop_type, pick_value)`.
Verdicts: `"keep"` (clean pick) | `"trim"` (marginally weak; excluded from parlay core) | `"manual_skip"` (should not have been filed).
`source` field: `"auto"` when written by the Review agent; absent on manually-produced files. Auditor ignores `source` — it joins on name/prop/value only. `build_site.py` reads `source` to distinguish auto-review badges (`🤖 Auto-Review` / `🤖 Stay Away`) from manual badges (`⚠ Caution` / `⚠ Flagged`).
Consumers: `auditor.py` (tags picks), `parlay.py` (excludes manual_skip; limits trim legs), `build_site.py` (renders review badges).

### opportunity_flags.json
Written/appended by `lineup_update.py` hourly when qualifying player absences are detected. Cumulative — not overwritten daily. Deduped by `(date, player_name_lower, triggered_by_lower)` — one card per player per triggering absence.
```json
[{
  "date":              "YYYY-MM-DD",
  "generated_at":      "ISO timestamp",
  "triggered_by":      "Absent Player Name",
  "triggered_by_team": "abbrev",
  "side":              "teammate|opponent",
  "player_name":       "string",
  "team":              "abbrev",
  "card_type":         "new_pick|upgrade|mixed",
  "qualifying_tiers":  {
    "PTS": {
      "tier": 20, "hit_rate_pct": 78, "trend": "up", "volatility": "consistent",
      "without_player_hit_rate_pct": 82, "without_player_n": 6  // optional
    }
  },
  "upgrade_tiers": {
    "AST": {
      "tier": 8, "hit_rate_pct": 75, "trend": "stable", "volatility": "moderate",
      "morning_tier": 6, "morning_confidence_pct": 78
    }
  },
  "spread_delta":    "string|null",
  "morning_context": "string|null",
  "reasoning":       "string"
}]
```

`qualifying_tiers`: props ≥70% hit rate where player has no morning pick. `upgrade_tiers`: props where quant best tier > morning pick tier. Both optional; player card not emitted when both empty. `without_player_*` fields optional (teammate side only, ≥3 historical without-player games required). Has no grading integration — opportunity card accuracy not tracked by auditor.

### parlays.json
List of daily bundles. Each bundle contains the day's parlays.
```json
[{
  "date": "YYYY-MM-DD",
  "parlays": [{
    "id": "parlay_YYYY-MM-DD_01",
    "label": "short evocative name",
    "type": "same_game_stack|multi_game|mixed",
    "legs": [{
      "player_name": "string",
      "team": "abbrev",
      "opponent": "abbrev",
      "prop_type": "PTS|REB|AST|3PM",
      "pick_value": number,
      "direction": "OVER",
      "confidence_pct": number,
      "correlation_role": "feeder|target|scorer|rebounder|independent|pace_play"
    }],
    "implied_odds": "+NNN",
    "confidence_product": number,
    "correlation": "positive|independent|mixed",
    "rationale": "string",
    "result": "HIT|MISS|PARTIAL|NO_DATA|null",
    "legs_hit": number|null,
    "legs_total": number,
    "leg_results": [{
      "player_name": "string",
      "prop_type": "string",
      "pick_value": number,
      "result": "HIT|MISS|NO_DATA",
      "actual_value": number|null
    }]
  }]
}]
```

### audit_log.json
List of daily audit entries. See `AGENTS.md` for full schema.

### skipped_picks_archive.json
Persistent append-log of all graded skip records accumulated across the season. Written by `save_skip_archive()` in `auditor.py` after each auditor run. Never overwritten — entries are deduplicated by date on re-run (same pattern as `audit_log.json`). Committed by `auditor.yml` alongside `audit_log.json`. Schema is identical to `skipped_picks.json` fields, accumulated across all dates:
```
date, player_name, team, opponent, prop_type, tier_considered, direction,
skip_reason, rule_context,
actual_value, would_have_hit, skip_verdict, skip_verdict_notes
```
`skip_verdict` values: `correct_skip` / `false_skip` / `no_data`. Enables longitudinal false-skip-rate analysis and retrospective skip-rule debugging across the full season (previously impossible because `skipped_picks.json` is overwritten each morning by the analyst).

### audit_summary.json
Rolled-up season stats written fresh after every auditor run by `save_audit_summary()`. Consumed by `analyst.py` as `## ROLLING PERFORMANCE SUMMARY`. Key blocks: `overall` (season hit rates, injury_exclusions, voided count), `prop_type_breakdown` (per-stat rates), `confidence_calibration` (per-band actual vs stated), `skip_validation` (per-rule false skip rates), `human_flag_precision` (season hit/miss rates grouped by `human_verdict` — "keep"/"trim"/"manual_skip" — computed from `picks.json` directly; accumulates automatically without explicit audit_log entries).

---

## Player Whitelist

**File:** `playerprops/player_whitelist.csv`
**Columns:** `team_abbr, team_abbr_alt, player_name, active, position`
**Filter logic:** `(player_name.lower(), team_abbr.upper())` tuple — filters on both name AND current team to prevent traded players appearing under old teams. `position` column used by Quant for positional DvP computation.
**`team_abbr_alt`** — ESPN abbreviation when it differs from the standard NBA `team_abbr`. Read by `load_whitelist()` in both `quant.py` and `analyst.py` to generate alt tuples alongside the primary tuples. Empty string for most teams. Non-empty for: SAS→SA, NYK→NY, GSW→GS, UTA→UTAH. Without this, player_game_log.csv rows (which use ESPN abbrevs) would never match the whitelist, making those players invisible to quant and analyst.
**Maintenance:** Toggle `active=0/1` rather than deleting rows — keeps historical picks attributable.

**Philosophy:** Established starters and consistent high-minute players only. Exclude: volatile bench players, injury-prone players on extended absences, players mid-role-change with insufficient data.

### Current Roster (~60 rows, ~57 active as of March 2026)

```
DET: Cade Cunningham, Jalen Duren, Ausar Thompson
NYK: Jalen Brunson, Karl-Anthony Towns, OG Anunoby, Mikal Bridges
TOR: Brandon Ingram, Scottie Barnes, RJ Barrett
BOS: Jaylen Brown, Derrick White, Payton Pritchard
PHI: Tyrese Maxey, Joel Embiid
ORL: Paolo Banchero, Desmond Bane
MIA: Tyler Herro, Bam Adebayo
CLE: Donovan Mitchell, Evan Mobley, Jarrett Allen, James Harden
ATL: Jalen Johnson
CHI: Josh Giddey, Matas Buzelis
MIL: Giannis Antetokounmpo
CHA: LaMelo Ball, Miles Bridges, Brandon Miller, Kon Knueppel
IND: Pascal Siakam, Andrew Nembhard
OKC: Shai Gilgeous-Alexander, Chet Holmgren, Jalen Williams, Isaiah Hartenstein
DEN: Nikola Jokic, Jamal Murray
LAL: Luka Doncic, LeBron James, Austin Reaves
SAS: Victor Wembanyama, Stephon Castle
HOU: Alperen Sengun, Kevin Durant, Amen Thompson
MIN: Anthony Edwards, Julius Randle, Rudy Gobert
PHX: Devin Booker, Jalen Green
GSW: Stephen Curry
DAL: Cooper Flagg
UTA: Lauri Markkanen, Ace Bailey
LAC: James Harden, Kawhi Leonard
```

---

## Team Abbreviation Notes

`nba_master.csv` and ingest sources occasionally use alternate abbreviations. The whitelist `team_abbr_alt` column handles known variants. Known edge cases:

| Canonical | Alt seen | Notes |
|-----------|----------|-------|
| NYK | NY | ESPN sometimes uses NY |
| GSW | GS | ESPN sometimes uses GS |
| UTA | UTAH | Verify in ingest output |
| NOP | NO | Verify in ingest output |
| SAS | SA | Verify in ingest output |

When a name-match fails suspiciously, check whether the team abbreviation variant is the cause before debugging the whitelist.
