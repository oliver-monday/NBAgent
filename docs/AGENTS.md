# NBAgent — Agents Reference

---

## Agent Execution Order (daily)

```
ingest.yml (8 AM ET)
  └─ espn_daily_ingest.py    → nba_master.csv
  └─ espn_player_ingest.py   → player_game_log.csv, player_dim.csv, team_game_log.csv
  └─ quant.py                → player_stats.json

auditor.yml (chains off ingest)
  └─ auditor.py              → audit_log.json, updates picks.json + parlays.json

analyst.yml (chains off auditor)
  └─ quant.py                (re-run to ensure freshness)
  └─ analyst.py              → picks.json (today's picks appended)
  └─ parlay.py               → parlays.json (today's parlays appended)
  └─ build_site.py           → site/index.html (deployed to GitHub Pages)

injuries.yml (hourly, independent)
  └─ rotowire_injuries_only.py → injuries_today.json
  └─ build_site.py             → site/index.html (redeployed with fresh injuries)
```

---

## quant.py — Deterministic Stats Engine

**Purpose:** Pre-computes all quantitative analytics from raw game logs so the Analyst and Parlay agents receive structured numbers rather than raw CSV rows. Pure Python — no LLM call.

**Key config constants:**
```python
PLAYER_WINDOW      = 10   # games for tier hit rates + trend base
TREND_SHORT_WINDOW = 5    # games for "recent" trend comparison
TREND_THRESHOLD    = 0.10 # >10% delta = up/down
MIN_GAMES          = 5    # skip players with fewer games
OPP_WINDOW         = 15   # games for opponent defensive context
CONFIDENCE_FLOOR   = 0.70 # minimum hit rate for a "best tier" pick
CORR_MIN_GAMES     = 8    # minimum shared games for teammate correlation
PACE_WINDOW        = 10   # games for game pace context
MIN_MATCHUP_GAMES  = 3    # minimum games per opp-rating bucket for matchup splits
SPREAD_COMPETITIVE = 6.5  # spread_abs ≤ this = competitive game
SPREAD_BLOWOUT_RISK = 8.0 # spread_abs > this for favored team → blowout risk flag
SPREAD_BIG_FAVORITE = 13.0 # spread_abs > this → cap analyst confidence at 80%
MIN_SPREAD_GAMES   = 5    # min games per spread bucket for historical split
B2B_MIN_GAMES      = 5    # min B2B games to produce b2b_hit_rates (else → one-tier-down flag)
REST_DENSE_DAYS    = 5    # look-back window (days) for dense schedule detection
REST_DENSE_THRESHOLD = 4  # games in REST_DENSE_DAYS window = dense_schedule=True
```

**Tier definitions:**
```python
PTS_TIERS = [10, 15, 20, 25, 30]
REB_TIERS = [2, 4, 6, 8, 10, 12]
AST_TIERS = [2, 4, 6, 8, 10, 12]
TPM_TIERS = [1, 2, 3, 4]
```

**Per-player outputs in `player_stats.json`:**
- `tier_hit_rates` — hit rate at each tier across last 10 games, per stat
- `matchup_tier_hit_rates` — hit rate at each tier split by opponent defensive rating (soft/mid/tough) across full season history; only buckets with ≥3 games included
- `spread_split_hit_rates` — hit rate at each tier split by game competitiveness (competitive = spread_abs ≤ 6.5 vs blowout = spread_abs > 6.5); only buckets with ≥5 games included; limited by spread data coverage
- `best_tiers` — highest tier with ≥70% hit rate, per stat (null if none qualify)
- `trend` — up / stable / down (last 5 vs last 10 avg), per stat
- `home_away_splits` — best qualifying tier split by H/A
- `minutes_trend` — increasing / stable / decreasing
- `on_back_to_back` — bool
- `rest_days` — int; days since team's last game (0 = B2B, 1 = 1 day rest, etc.); null if no history
- `games_last_7` — int; games played in the 7 days before today
- `dense_schedule` — bool; True when team played 4+ games in the last 5 days
- `b2b_hit_rates` — per stat: `{"hit_rates": {tier: float}, "n": int}` computed from historical B2B second-night games; null per stat when fewer than 5 B2B games exist (Analyst falls back to one-tier-down)
- `today_spread` — this team's signed spread for today's game (negative = favored); null if unavailable
- `spread_abs` — absolute value of today's spread; null if unavailable
- `blowout_risk` — bool; True when team is favored AND spread_abs > 8.0
- `opp_defense` — opponent's allowed avg + rank + rating (soft/mid/tough) per stat, based on last 15 games
- `game_pace` — combined scoring avg for today's matchup + pace_tag (high/mid/low)
- `teammate_correlations` — Pearson r + correlation tag for each stat pair with each whitelisted teammate

**Correlation tags used:**
`feeder_target`, `volume_game`, `pace_beneficiary`, `positively_correlated`, `independent`, `insufficient_data`, `board_rivals`, `scoring_rivals`, `negatively_correlated`

**Whitelist filtering:** Quant filters to `(player_name.lower(), team_abbrev.upper())` tuples — this prevents traded players from appearing under their old team.

---

## analyst.py — Pick Generator

**Model:** `claude-sonnet-4-6`  
**MAX_TOKENS:** `16384` (large slates can produce 30+ picks)  
**RECENT_GAME_WINDOW:** `10` games per player  
**AUDIT_CONTEXT_ENTRIES:** `5` most recent entries

**Inputs consumed:**
- `nba_master.csv` — today's game slate
- `player_game_log.csv` — raw recent box scores (last 10 per player, filtered to today's whitelisted players)
- `player_stats.json` — quant output; provides pre-computed best tiers and matchup-specific hit rates injected as a structured prompt section
- `injuries_today.json` — filtered to today's teams only
- `audit_log.json` — last 5 entries (reinforcements, lessons, recommendations)
- `context/nba_season_context.md` — manually maintained NBA context injected into prompt; handles missing file gracefully
- `playerprops/player_whitelist.csv` — (name, team) tuple filter

**Prompt design principles:**
- Tier system explicitly taught: walk down from ceiling until ≥70% hit rate found
- Example reasoning pattern included in prompt
- Season context injected between injury report and player logs sections
- Audit feedback framed as "use this to refine your selections"
- Output schema enforced strictly: `pick_value` must be a valid tier value

**Output schema (appended to `picks.json`):**
```json
{
  "date": "YYYY-MM-DD",
  "player_name": "string",
  "team": "abbrev",
  "opponent": "abbrev",
  "home_away": "H|A",
  "prop_type": "PTS|REB|AST|3PM",
  "pick_value": number,          // must be a valid tier value
  "direction": "OVER",
  "confidence_pct": 70–99,
  "hit_rate_display": "8/10",    // fraction at this tier from last 10 games
  "trend": "up|stable|down",
  "opp_defense_rating": "soft|mid|tough|unknown",
  "reasoning": "string",         // max 15 words, no restating hit rate
  "result": null,                // filled by auditor
  "actual_value": null           // filled by auditor
}
```

---

## parlay.py — Parlay Builder

**Model:** `claude-sonnet-4-6`  
**MAX_TOKENS:** `4096`

**Logic flow:**
1. Load today's picks with `confidence_pct ≥ 70` and `result == null`
2. Build all 2–6 leg combinations (no duplicate players)
3. Filter: implied odds must be +100 to +600 American
4. Filter: skip combos with `scoring_rivals` or `board_rivals` between same-team players
5. Score each combo on: confidence product, floor confidence, correlation quality, game spread
6. Send top 15 scored combos to Claude → returns 3–5 curated parlays

**Implied odds formula:**
```
combined_prob = product of (confidence_pct / 100)
american_odds = ((1 / combined_prob) - 1) * 100   # if prob < 0.5
```

**Correlation scoring weights:**
```python
CORR_BONUS = {
    "feeder_target":          +0.10,
    "volume_game":            +0.05,
    "pace_beneficiary":       +0.05,
    "positively_correlated":  +0.05,
    "independent":             0.00,
    "insufficient_data":       0.00,
    "board_rivals":           -0.05,
    "scoring_rivals":         -0.10,
    "negatively_correlated":  -0.08,
}
```

**Claude selection criteria (in priority order):**
1. Implied odds +100 to +300 preferred; +300–600 OK if all legs strong
2. Floor confidence — weakest leg matters most, prefer ≥75%
3. Positive correlation tags
4. Game spread — multi-game more robust than same-game stacks
5. Variety across 3–5 selections (mix of leg counts)

**Output schema (appended as bundle to `parlays.json`):**
```json
// parlays.json structure: list of daily bundles
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
    "rationale": "string (max 20 words)",
    "result": "HIT|MISS|PARTIAL|NO_DATA|null",
    "legs_hit": number|null,
    "legs_total": number,
    "leg_results": [...]   // filled by auditor
  }]
}]
```

---

## auditor.py — Results Grader + Feedback Writer

**Model:** `claude-sonnet-4-6`  
**MAX_TOKENS:** `2048`  
**Runs for:** yesterday's date

**Grading logic:**
- Matches picks to `player_game_log.csv` by `(player_name.lower(), team_abbrev)` for yesterday's date
- Pick result: `HIT` if actual > pick_value, `MISS` if actual ≤ pick_value, `NO_DATA` if player not found
- Parlay result: `HIT` (all legs hit), `MISS` (any leg missed), `PARTIAL` (no miss but some NO_DATA), `NO_DATA` (all legs NO_DATA)
- Skips run if zero gradeable picks (box scores not yet ingested)

**Output written to `audit_log.json`:**
```json
{
  "date": "YYYY-MM-DD",
  "total_picks": number,
  "hits": number,
  "misses": number,
  "no_data": number,
  "hit_rate_pct": number,
  "reinforcements": ["string"],
  "lessons": ["string"],
  "recommendations": ["string"],
  "miss_details": [{
    "player_name": "string",
    "prop_type": "string",
    "pick_value": number,
    "actual_value": number,
    "root_cause": "string"
  }],
  "parlay_results": {
    "total": number,
    "hits": number,
    "misses": number,
    "partial": number,
    "parlay_lessons": ["string"],
    "parlay_reinforcements": ["string"]
  }
}
```

Also updates `picks.json` and `parlays.json` in-place with graded results.

---

## build_site.py — Frontend Generator

Pure Python, no JS dependencies in output. Reads all data files, writes `site/index.html`.

**Four tabs:**
1. **Today's Picks** — injury report dropdown, pick cards grouped by game (collapsible), sorted by prop type then confidence. Each card: player, micro-stat pills (trend + opp defense), reasoning, hit rate bar, confidence.
2. **Parlays** — historical stats banner (hidden until data exists), parlay cards with leg rows showing player/team, stat value + colored prop badge, confidence, result icon post-grading. Correlation badge + rationale on each card.
3. **Results** — overall hit rate banner, 4 per-prop streak cards, 30-day hit rate trend chart (vanilla canvas), full pick history table.
4. **Audit Log** — latest auditor entry: hit rate stats, what worked, what to avoid, analyst instructions.

**Triggered by:** end of `analyst.yml` AND end of each `injuries.yml` run (so injury data stays fresh on the live site without needing a full analyst run).
