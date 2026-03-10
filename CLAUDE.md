# NBAgent — CLAUDE.md

You are the technical co-builder for **NBAgent**, an autonomous NBA player props prediction system. Read this file first on every session, then load the `@docs/` files relevant to the task at hand.

---

## What NBAgent Does

A self-improving multi-agent system that runs entirely via GitHub Actions. Every day it:

1. Ingests fresh ESPN box scores and game data (`espn_daily_ingest.py`, `espn_player_ingest.py`)
2. Scrapes Rotowire for injury updates hourly (`rotowire_injuries_only.py`)
3. **Auditor** grades yesterday's picks + parlays, writes structured feedback to `audit_log.json` + rolls up `audit_summary.json`
4. **Quant** computes deterministic per-player stats cards from raw game logs — tier hit rates, best qualifying tier per stat, trend (L5 vs L20), home/away splits, B2B flag and quantified B2B hit rates, opponent defense rating, spread context, matchup-specific tier hit rates, teammate correlations (Pearson r + correlation tags), game pace context, and bounce-back profiles per player per stat
5. **Analyst** reads today's slate + Quant output + Auditor feedback + Rolling summary → calls Claude API → generates prop picks
6. **Lineup Watch** post-processes picks after each injury refresh — voids OUT picks, flags DOUBTFUL/QUESTIONABLE picks with risk levels
7. **Parlay** reads today's picks → builds scored combinations → calls Claude API → generates 3–5 curated parlays
8. Builds and deploys a static frontend to GitHub Pages

Picks: **PTS / REB / AST / 3PM** — OVER only, ≥70% confidence.
API cost: ~$0.36/day (analyst + parlay + auditor combined at current slate sizes).

---

## Repo Structure

```
NBAgent/
├── agents/
│   ├── quant.py            # Deterministic stats cards — tier hit rates, best tier, trend, B2B, opp defense, matchup splits, spread context, teammate correlations, game pace, bounce-back profiles
│   ├── analyst.py          # Analyst agent — calls Claude, generates picks; injects season context + rolling audit summary
│   ├── parlay.py           # Parlay agent — calls Claude, generates parlays; reads parlay audit feedback
│   ├── auditor.py          # Auditor agent — grades picks + parlays, writes audit_log.json + audit_summary.json; injects season context
│   ├── lineup_watch.py     # Deterministic post-process — voids OUT picks, flags DOUBTFUL/QUESTIONABLE; runs after each injury refresh
│   ├── lineup_update.py    # Afternoon amendment agent — diffs morning lineup snapshot vs current, calls Claude, writes lineup_update sub-objects to picks
│   ├── backtest.py         # Standalone retrospective signal analysis — 5 modes (see docs/BACKTESTS.md)
│   └── build_site.py       # Static site generator (v3 — 4-tab); renders voided/risk badges
├── ingest/
│   ├── espn_daily_ingest.py        # Game slate + spreads from ESPN Core odds API
│   ├── espn_player_ingest.py       # Player box scores → player_game_log.csv, team_game_log.csv, player_dim.csv
│   └── rotowire_injuries_only.py   # Injury + lineup scrape → injuries_today.json, lineups_today.json
├── context/
│   └── nba_season_context.md   # Manually maintained NBA context — injected into Analyst AND Auditor prompts
├── data/
│   ├── nba_master.csv          # Season game data (game slate, scores, spreads, moneylines)
│   ├── player_game_log.csv     # Player box scores — one row per player per game
│   ├── player_dim.csv          # ESPN athlete_id → player name map
│   ├── team_game_log.csv       # Team-level aggregated box scores — used by Quant for opp defense + pace
│   ├── player_stats.json       # Quant output — consumed by Analyst, Parlay, and Auditor
│   ├── injuries_today.json     # Hourly updated by injuries workflow
│   ├── picks.json              # All picks with results; mutated in-place by analyst (append), lineup_watch (void/flag), lineup_update (lineup_update sub-object), auditor (grade)
│   ├── lineups_today.json      # Projected starters — written by rotowire_injuries_only.py; snapshot_at_analyst_run key added by analyst.py at pick time
│   ├── parlays.json            # All parlays with results
│   ├── audit_log.json          # Daily auditor entries — full graded pick details
│   └── audit_summary.json      # Rolled-up season stats — consumed by Analyst as Rolling Performance Summary
├── playerprops/
│   └── player_whitelist.csv    # Active player tracking list — (player_name, team_abbr) tuple filter; includes position column for DvP
├── site/
│   └── index.html              # Auto-generated, deployed to GitHub Pages
├── docs/
│   ├── SESSION_CONTEXT.md      # Session handoff — current schema, function signatures, design decisions, known gotchas
│   ├── AGENTS.md               # Agent logic, config, schemas
│   ├── DATA.md                 # All CSV/JSON schemas, player whitelist with current roster, team abbreviation notes
│   ├── ROADMAP.md              # Resolved bugs, open items, improvement proposals
│   └── BACKTESTS.md            # Completed backtest log — findings, verdicts, and implementation status
├── .github/workflows/
│   ├── ingest.yml              # 8 AM ET daily — ingests ESPN data, runs quant
│   ├── injuries.yml            # Hourly 9 AM–6 PM ET — scrapes Rotowire, runs lineup_watch, rebuilds site
│   ├── auditor.yml             # Chains off ingest — grades yesterday's picks, writes audit_log + audit_summary
│   └── analyst.yml             # Chains off auditor — runs quant→analyst→parlay, deploys site
└── CLAUDE.md                   # This file
```

---

## Workflow Chain

```
ingest.yml → auditor.yml → analyst.yml (rotowire refresh → quant → analyst → parlay → deploy)
injuries.yml runs independently on hourly schedule (rotowire → lineup_watch → lineup_update → site rebuild)
```

- All workflows: `TZ: America/Los_Angeles`
- Commits: `github-actions[bot]` with `[skip ci]` to prevent loops
- **Required secret:** `ANTHROPIC_API_KEY`
- **Model used by all LLM agents:** `claude-sonnet-4-6`

---

## Agent Config (quick reference)

| Agent | Model | MAX_TOKENS | Key inputs | Key output |
|-------|-------|-----------|------------|------------|
| quant.py | — (pure Python) | — | player_game_log, team_game_log, nba_master, player_whitelist | player_stats.json |
| analyst.py | claude-sonnet-4-6 | 16384 | player_stats.json, injuries, audit_log (last 5), audit_summary, nba_season_context | picks.json (append) |
| parlay.py | claude-sonnet-4-6 | 4096 | picks.json, player_stats.json, audit_log (last 3 parlay feedback) | parlays.json (append) |
| auditor.py | claude-sonnet-4-6 | 2048 | picks.json, parlays.json, player_game_log, player_stats.json, nba_season_context | audit_log.json, audit_summary.json, updates picks + parlays in-place |
| lineup_watch.py | — (pure Python) | — | injuries_today.json, picks.json | picks.json (in-place mutations: voided, lineup_risk) |
| lineup_update.py | claude-sonnet-4-6 | 2048 | lineups_today.json (snapshot), injuries_today.json, picks.json, nba_master.csv | picks.json (lineup_update sub-object on affected picks) |

Full agent details → **@docs/AGENTS.md**

---

## Key Data Flows (non-obvious)

- **`audit_summary.json`** is generated fresh after every auditor run by `save_audit_summary()`. The Analyst reads it as `## ROLLING PERFORMANCE SUMMARY` — provides season hit rates, per-prop rates, and miss classification totals. Returns empty string if fewer than 3 audit entries exist (graceful cold-start).
- **`player_stats.json`** is consumed by three agents: Analyst (pick generation), Parlay (correlation tags, spread context), and Auditor (audit context injection for root-cause grading). Do not change its schema without checking all three consumers.
- **`picks.json`** is mutated in-place by four separate processes in sequence: Analyst appends new picks, lineup_watch.py mutates voided/risk fields, lineup_update.py writes `lineup_update` sub-objects (hourly, conditional on changes), Auditor grades results. Always read the full file before writing — never overwrite with a subset.
- **`context/nba_season_context.md`** is injected into BOTH `analyst.py` and `auditor.py` prompts. Updates to this file affect both agents. The file includes a PERMANENT ABSENCES block at the top instructing both agents to treat listed players as if they never existed this season.
- **Parlay audit feedback loop** — `parlay.py` reads the last 3 `audit_log.json` entries for `parlay_reinforcements` and `parlay_lessons` and injects them into the Claude prompt. The parlay agent now sees what correlation types and leg structures have historically succeeded or failed.

---

## player_stats.json — Key Fields

Quant output. One entry per whitelisted player playing today. Key fields:

| Field | Description |
|-------|-------------|
| `tier_hit_rates` | Hit rate at each tier, last 20 games (PLAYER_WINDOW=20), per stat |
| `matchup_tier_hit_rates` | Hit rate at each tier split by opp defense rating (soft/mid/tough), full season |
| `spread_split_hit_rates` | Hit rate split by competitive vs blowout game context |
| `best_tiers` | Highest tier with ≥70% hit rate per stat (null if none qualify) |
| `trend` | up/stable/down — L5 vs L20 avg, per stat |
| `home_away_splits` | Best qualifying tier split by H/A |
| `b2b_hit_rates` | Tier hit rates on historical B2B second-night games; null when <5 B2B games |
| `bounce_back` | Per-stat: post_miss_hit_rate, lift, iron_floor (bool), n_misses — full season history |
| `opp_defense` | Opponent's allowed avg + rank + rating (soft/mid/tough), last 15 games, per stat |
| `game_pace` | Combined scoring avg for today's matchup + pace_tag (high/mid/low) |
| `teammate_correlations` | Pearson r + correlation tag per stat pair with each whitelisted teammate |
| `today_spread` / `spread_abs` / `blowout_risk` | Spread context for today's game |
| `rest_days` / `games_last_7` / `dense_schedule` | Schedule fatigue context |
| `on_back_to_back` | Bool — true if today is second night of B2B |
| `raw_avgs` / `avg_minutes_last5` / `minutes_trend` | Volume context |

Full schema → **@docs/DATA.md**

---

## picks.json — Fields Added Since Launch

The base schema is in `@docs/DATA.md`. These fields were added post-launch:

| Field | Set by | Notes |
|-------|--------|-------|
| `game_time` | Analyst | Formatted game time string, e.g. `"7:30 PM PT"` |
| `voided` | lineup_watch.py | `true` when player is listed OUT; pick treated as inactive |
| `void_reason` | lineup_watch.py | e.g. `"OUT: Knee (Rotowire)"` |
| `lineup_risk` | lineup_watch.py | `"high"` (DOUBTFUL) or `"moderate"` (QUESTIONABLE); not set for OUT |
| `injury_status_at_check` | lineup_watch.py | `OUT / DOUBTFUL / QUESTIONABLE / NOT_LISTED` — written to ALL today's picks on every run |
| `injury_check_time` | lineup_watch.py | ISO timestamp of last lineup_watch run |
| `tier_walk` | Analyst | Tier walk-down reasoning string; shown on pick cards as expandable |
| `iron_floor` | Analyst | `true` when quant stat line showed `[iron_floor]`; Claude copies directly from context |
| `lineup_update` | lineup_update.py | Sub-object: `{triggered_by, updated_at, direction, revised_confidence_pct, revised_reasoning}`; written hourly when starter changes detected; overwritten on each run |

---

## Whitelist Notes

**File:** `playerprops/player_whitelist.csv`
**Columns:** `team_abbr, team_abbr_alt, player_name, active, position`
**Filter logic:** `(player_name.lower(), team_abbr.upper())` tuple — prevents traded players appearing under old teams.

**Player-specific flags (as of March 2026):**
- **James Harden** — appears on TWO rows: one for `CLE` (old team, `active=0`) and one for `LAC` (`active=1`). The tuple filter ensures only the LAC row is active. Do not delete the CLE row — it preserves historical pick attribution.
- **Andrew Nembhard** — removed from active whitelist (role change; insufficient data for reliable picks). Toggle `active=0` if not already done.
- **Kon Knueppel (CHA)** — newer addition; monitor game log volume before relying on his stats.
- **Ace Bailey (UTA)** — newer addition; same caveat as Knueppel.

---

## Frontend

Four-tab dark theme SPA deployed to GitHub Pages via `build_site.py`.

| Tab | Content |
|-----|---------|
| Today's Picks | Injury report dropdown, pick cards grouped by game (collapsible). Voided picks show strikethrough + VOIDED badge. DOUBTFUL/QUESTIONABLE picks show risk pills. |
| Parlays | Historical stats banner (hidden until graded history exists). Parlay cards with leg rows, implied odds, correlation badge, result once graded. "⚠ Leg at risk" banner when any leg player is voided. |
| Results | Overall hit rate banner, 4 per-prop streak cards, 30-day hit rate trend chart (vanilla canvas), full pick history table. |
| Audit Log | Latest auditor entry — hit rate stats, what worked, what to avoid, analyst instructions. |

Site rebuilds at end of every Analyst workflow run AND after every hourly injury refresh.

---

## User Profile

- Minimal coding experience; uses GitHub Desktop for all commits/pushes
- Comfortable reading logs and identifying errors
- Strong NBA domain knowledge — push back on stale basketball intel
- Goal: autonomous daily operation, frontend shared with friends/family
- API billing: pay-as-you-go on console.anthropic.com (~$0.36/day; separate from Claude Pro subscription)

---

## Sub-documents

- **@docs/SESSION_CONTEXT.md** — Load this first on every new session. Dense handoff: current player_stats.json schema, live prompt format, all function signatures, design decisions, backtest verdicts, known gotchas, and active queue. Replaces the need to re-derive implementation state from source code.
- **@docs/AGENTS.md** — Quant computations, Analyst prompt design, Parlay scoring logic, Auditor grading, all output schemas
- **@docs/DATA.md** — All CSV/JSON schemas, player whitelist with current roster, team abbreviation notes
- **@docs/ROADMAP.md** — Resolved bugs, open items, improvement proposals with implementation priority
- **@docs/BACKTESTS.md** — Completed backtest log — findings, verdicts, and implementation status for all hypotheses tested
