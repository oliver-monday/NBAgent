# NBAgent — CLAUDE.md

You are the technical co-builder for **NBAgent**, an autonomous NBA player props prediction system. Read this file first on every session, then load the `@docs/` files relevant to the task at hand.

---

## What NBAgent Does

A self-improving multi-agent system that runs entirely via GitHub Actions. Every day it:

1. Ingests fresh ESPN box scores and game data
2. Scrapes Rotowire for injury updates (hourly)
3. **Auditor** grades yesterday's picks + parlays, writes structured feedback
4. **Quant** computes deterministic per-player stats cards from raw game logs
5. **Analyst** reads today's slate + Quant output + Auditor feedback → calls Claude API → generates prop picks
6. **Parlay** reads today's picks → builds scored combinations → calls Claude API → generates 3–5 curated parlays
7. Builds and deploys a static frontend to GitHub Pages

Picks: **PTS / REB / AST / 3PM** — OVER only, ≥70% confidence.

---

## Repo Structure

```
NBAgent/
├── agents/
│   ├── quant.py            # Deterministic stats cards — runs before analyst
│   ├── analyst.py          # Analyst agent — calls Claude, generates picks
│   ├── parlay.py           # Parlay agent — calls Claude, generates parlays
│   ├── auditor.py          # Auditor agent — grades picks + parlays, writes feedback
│   └── build_site.py       # Static site generator (v3 — 4-tab)
├── ingest/
│   ├── espn_daily_ingest.py
│   ├── espn_player_ingest.py
│   └── rotowire_injuries_only.py
├── context/
│   └── nba_season_context.md   # Manually maintained NBA context — injected into Analyst prompt
├── data/
│   ├── nba_master.csv          # Season game data
│   ├── player_game_log.csv     # Player box scores
│   ├── player_dim.csv          # ESPN athlete_id → player name map
│   ├── team_game_log.csv       # Team-level box scores
│   ├── player_stats.json       # Quant output — consumed by Analyst + Parlay
│   ├── injuries_today.json     # Hourly updated by injuries workflow
│   ├── picks.json              # All picks with results
│   ├── parlays.json            # All parlays with results
│   └── audit_log.json          # Auditor feedback history
├── playerprops/
│   └── player_whitelist.csv    # Active player tracking list (name + team tuple)
├── site/
│   └── index.html              # Auto-generated, deployed to GitHub Pages
├── docs/
│   ├── AGENTS.md               # Agent logic, config, schemas
│   ├── DATA.md                 # All data schemas + whitelist
│   └── ROADMAP.md              # Resolved issues, open items, improvement proposals
├── .github/workflows/
│   ├── ingest.yml              # 8 AM ET daily
│   ├── injuries.yml            # Hourly 9 AM–6 PM ET
│   ├── auditor.yml             # Chains off ingest
│   └── analyst.yml             # Chains off auditor — runs quant→analyst→parlay, deploys site
└── CLAUDE.md                   # This file
```

---

## Workflow Chain

```
ingest.yml → auditor.yml → analyst.yml (quant → analyst → parlay → deploy)
injuries.yml runs independently on hourly schedule
```

- All workflows: `TZ: America/Los_Angeles`
- Commits: `github-actions[bot]` with `[skip ci]` to prevent loops
- **Required secret:** `ANTHROPIC_API_KEY`
- **Model used by all LLM agents:** `claude-sonnet-4-6`

---

## Agent Config (quick reference)

| Agent | Model | MAX_TOKENS | Key inputs | Key output |
|-------|-------|-----------|------------|------------|
| quant.py | — (pure Python) | — | player_game_log, team_game_log, nba_master | player_stats.json |
| analyst.py | claude-sonnet-4-6 | 16384 | player_stats.json, injuries, audit_log | picks.json |
| parlay.py | claude-sonnet-4-6 | 4096 | picks.json, player_stats.json | parlays.json |
| auditor.py | claude-sonnet-4-6 | 2048 | picks.json, parlays.json, player_game_log | audit_log.json, updates picks + parlays |

Full agent details → **@docs/AGENTS.md**

---

## Frontend

Four-tab dark theme SPA deployed to GitHub Pages via `build_site.py`.

| Tab | Content |
|-----|---------|
| Today's Picks | Pick cards grouped by game, with hit rate bar, trend pill, reasoning |
| Parlays | Parlay cards with leg rows, implied odds, correlation badge, result once graded |
| Results | Hit rate banner, per-prop streak cards, 30-day trend chart, pick history table |
| Audit Log | Latest auditor entry — what worked, what to avoid, analyst instructions |

Site rebuilds automatically at end of every Analyst workflow run, and after every hourly injury refresh.

---

## User Profile

- Minimal coding experience; uses GitHub Desktop for all commits/pushes
- Comfortable reading logs and identifying errors
- Strong NBA domain knowledge — push back on stale basketball intel
- Goal: autonomous daily operation, frontend shared with friends/family
- API billing: pay-as-you-go on console.anthropic.com (separate from Claude Pro subscription)

---

## Sub-documents

- **@docs/AGENTS.md** — Quant computations, Analyst prompt design, Parlay scoring logic, Auditor grading, all output schemas
- **@docs/DATA.md** — All CSV/JSON schemas, player whitelist with current roster, team abbreviation notes
- **@docs/ROADMAP.md** — Resolved bugs, open items, 5 queued improvement proposals with implementation priority
