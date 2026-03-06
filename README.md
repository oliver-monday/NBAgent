# NBAgent

A self-improving multi-agent system that generates daily high-confidence NBA player prop picks and deploys them to a live site.

## How It Works

Six agents run automatically via GitHub Actions every day.

**Quant** — Deterministic stats engine. Pre-computes tier hit rates, trend, home/away splits, opponent positional defense (DvP), B2B rates, schedule density, spread context, bounce-back profiles, volatility scores, teammate correlations, and game pace for every tracked player. No LLM call.

**Pre-Game Reporter** — Fetches ESPN news for today's tracked players. Filters to prop-relevant items (availability, minutes, role changes). Calls Claude once to distill into concise player and game notes for the Analyst.

**Analyst** — Reads today's slate, quant stats, injury report, pre-game news, season context, and rolling audit feedback. Calls Claude to select OVER picks (PTS / REB / AST / 3PM) at fixed tier thresholds with ≥70% confidence.

**Parlay** — Reads today's picks. Scores all 2–6 leg combinations on confidence, correlation, and spread context. Calls Claude to curate 3–5 parlays.

**Lineup Watch** — Deterministic post-processor. Runs after each hourly injury refresh. Voids picks for OUT players; flags DOUBTFUL/QUESTIONABLE picks with risk levels. No LLM call.

**Post-Game Reporter** — Runs before the Auditor. Fetches ESPN news for yesterday's low-minutes or DNP players. Classifies events (injury exit, DNP, minutes restriction) for auditor context.

**Auditor** — Cross-references yesterday's picks and parlays against real box scores. Grades HIT/MISS/NO_DATA, classifies each miss (selection_error / model_gap / variance / injury_event / workflow_gap), and writes structured feedback the Analyst reads the next day. Maintains a rolling season summary.

**Build Site** — Pure Python. Generates a 4-tab dark theme SPA (Today's Picks, Parlays, Results, Audit Log) deployed to GitHub Pages after every analyst run and every hourly injury refresh.

## Daily Chain

```
8:00 AM  Daily Ingest   → ESPN box scores, player logs, spreads → Quant
          ↓ chains
         Auditor        → Post-Game Reporter → grade picks → write feedback + summary
          ↓ chains
         Analyst        → Quant (re-run) → Pre-Game Reporter → Analyst → Parlay → deploy site

9AM–6PM  Injuries (hourly) → Rotowire scrape → Lineup Watch → rebuild + deploy site
```

All times PT (America/Los_Angeles). Workflows chain via `workflow_run` — manual trigger available on each.

## Repo Structure

```
NBAgent/
├── agents/
│   ├── quant.py                 # Deterministic stats engine — player_stats.json
│   ├── pre_game_reporter.py     # ESPN pre-game news → pre_game_news.json
│   ├── analyst.py               # Pick generator (Claude)
│   ├── parlay.py                # Parlay builder (Claude)
│   ├── lineup_watch.py          # Injury post-processor — voids/flags picks
│   ├── post_game_reporter.py    # ESPN post-game news for auditor context
│   ├── auditor.py               # Results grader + feedback writer (Claude)
│   ├── build_site.py            # Static site generator
│   └── backtest.py              # Standalone signal analysis (5 modes)
├── ingest/
│   ├── espn_daily_ingest.py         # Game slate + spreads
│   ├── espn_player_ingest.py        # Player box scores
│   └── rotowire_injuries_only.py    # Hourly injury status
├── context/
│   └── nba_season_context.md        # Manually maintained — injected into Analyst + Auditor
├── data/
│   ├── nba_master.csv           # Game-level data (scores, spreads, matchups)
│   ├── player_game_log.csv      # Player box scores (full season)
│   ├── team_game_log.csv        # Team totals (used by Quant)
│   ├── player_dim.csv           # ESPN athlete_id → player name map
│   ├── player_stats.json        # Quant output — consumed by Analyst, Parlay, Auditor
│   ├── injuries_today.json      # Current injury status (refreshed hourly)
│   ├── pre_game_news.json       # Pre-game ESPN news (consumed by Analyst)
│   ├── post_game_news.json      # Post-game ESPN news (consumed by Auditor)
│   ├── picks.json               # All picks with results (appended daily)
│   ├── parlays.json             # All parlays with results
│   ├── audit_log.json           # Auditor feedback history
│   └── audit_summary.json       # Rolling season stats (consumed by Analyst)
├── playerprops/
│   └── player_whitelist.csv     # ~57 active tracked players (name, team, position)
├── site/
│   └── index.html               # Auto-generated — deployed to GitHub Pages
├── docs/
│   ├── AGENTS.md                # Agent logic, schemas, quant config
│   ├── DATA.md                  # All CSV/JSON schemas
│   ├── SESSION_CONTEXT.md       # Dense technical handoff for AI sessions
│   ├── ROADMAP.md               # Issue log, improvement proposals, active queue
│   └── BACKTESTS.md             # Signal analysis log — findings and verdicts
└── .github/workflows/
    ├── ingest.yml               # 8 AM PT — ingest + quant
    ├── auditor.yml              # Chains off ingest — post-game reporter + auditor
    ├── analyst.yml              # Chains off auditor — quant + pre-game + analyst + parlay + deploy
    └── injuries.yml             # Hourly 9 AM–6 PM PT — injuries + lineup watch + deploy
```

## Setup

### 1. Add your Anthropic API key
**Settings → Secrets and variables → Actions → New repository secret**
- Name: `ANTHROPIC_API_KEY`
- Value: your key from console.anthropic.com

### 2. Enable GitHub Pages
**Settings → Pages → Source: GitHub Actions**

### 3. Enable GitHub Actions
**Actions tab → Enable workflows**

### 4. Trigger the first run
**Actions → Daily Ingest → Run workflow** — this kicks off the full chain automatically.

## Data Sources

- **ESPN API** — Game schedules, scores, spreads, player box scores, player news (free, no key)
- **Rotowire** — Injury and lineup status (scraped hourly)
- **Anthropic Claude** — Analyst, Parlay, Auditor, Pre-Game Reporter (`claude-sonnet-4-6`)

**API cost:** ~$0.36/day (analyst + parlay + auditor + pre-game reporter combined).
