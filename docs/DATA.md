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

### player_game_log.csv (18 columns)
```
season_end_year, game_id, game_date, team_abbrev, opp_abbrev,
home_away, player_id, player_name, started, minutes, minutes_raw,
pts, reb, ast, tpm, dnp, team_hint_ok, ingested_at
```
Source: `espn_player_ingest.py`. One row per player per game.  
`dnp = "1"` rows are kept but excluded from analytics.  
`home_away`: `"H"` or `"A"`.

### team_game_log.csv
```
game_id, game_date, team_abbrev, opp_abbrev, home_away,
team_pts, team_reb, team_ast, team_tpm
```
Source: `espn_player_ingest.py`. Aggregated from player rows. Used by Quant for opponent defense and game pace.

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
    "opponent": "abbrev",
    "games_available": 10,
    "last_updated": "YYYY-MM-DD",
    "on_back_to_back": false,
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
    "raw_avgs": {"PTS": 22.1, "REB": 5.4, "AST": 6.1, "3PM": 1.8},
    "opp_defense": {
      "PTS": {"allowed_pg": 112.4, "rank": 28, "n_teams": 30, "rating": "soft"},
      "REB": {...}, "AST": {...}, "3PM": {...}
    },
    "game_pace": {"combined_pts_avg": 224.1, "pace_tag": "high", "source": "h2h"},
    "teammate_correlations": {
      "Teammate Name": {
        "shared_games": 18,
        "correlations": {
          "AST_PTS": {"r": 0.71, "tag": "feeder_target"},
          "PTS_PTS": {"r": -0.08, "tag": "independent"}
        }
      }
    }
  }
}
```

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
  "result": "HIT|MISS|NO_DATA|null",
  "actual_value": number|null,
  "game_time": "7:30 PM PT"
}]
```

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
List of daily audit entries. See `@docs/AGENTS.md` for full schema.

---

## Player Whitelist

**File:** `playerprops/player_whitelist.csv`  
**Columns:** `team_abbr, team_abbr_alt, player_name, active`  
**Filter logic:** `(player_name.lower(), team_abbr.upper())` tuple — filters on both name AND current team to prevent traded players appearing under old teams.  
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
