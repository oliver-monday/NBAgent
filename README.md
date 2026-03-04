# NBAgent

A self-improving multi-agent system that generates daily high-confidence NBA player prop picks.

## How It Works

Two AI agents run on a daily schedule via GitHub Actions:

**Analyst** — Selects high-confidence prop picks (Points, Rebounds, Assists, 3PM) for players in today's games. Weighs recent form over season averages, accounts for matchup context, injuries, and reads feedback from the Auditor before each run.

**Auditor** — Cross-references the prior day's picks against real box scores. Grades each pick as HIT or MISS, performs root cause analysis on misses, and writes structured feedback that the Analyst reads the next day. This feedback loop drives continuous improvement.

## Daily Schedule (ET)

| Time | Action |
|------|--------|
| 8:00 AM | Ingest: ESPN box scores + player game logs |
| 9:00 AM | Auditor: grade yesterday's picks, write feedback |
| ~9:30 AM | Analyst: read feedback, generate today's picks, deploy site |
| 9AM–6PM | Injuries: refresh hourly from Rotowire |

## Repo Structure

```
NBAgent/
├── agents/
│   ├── analyst.py           # Analyst agent
│   ├── auditor.py           # Auditor agent
│   └── build_site.py        # Static site generator
├── ingest/
│   ├── espn_daily_ingest.py     # Game scores + odds
│   ├── espn_player_ingest.py    # Player box scores
│   └── rotowire_injuries_only.py # Injury status
├── data/
│   ├── nba_master.csv       # Game-level data (scores, matchups)
│   ├── player_game_log.csv  # Player box scores (season)
│   ├── player_dim.csv       # Player ID map
│   ├── team_game_log.csv    # Team totals
│   ├── injuries_today.json  # Current injury status
│   ├── picks.json           # All picks (today + historical with results)
│   └── audit_log.json       # Auditor feedback history
├── playerprops/
│   └── player_whitelist.csv # Players tracked for props
├── site/
│   └── index.html           # Auto-generated frontend
└── .github/workflows/
    ├── ingest.yml           # Daily data ingest
    ├── injuries.yml         # Hourly injury refresh
    ├── auditor.yml          # Auditor agent (chains off ingest)
    └── analyst.yml          # Analyst agent (chains off auditor)
```

## Setup

### 1. Add your Anthropic API key
In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `ANTHROPIC_API_KEY`
- Value: your key from console.anthropic.com

### 2. Enable GitHub Pages
**Settings → Pages → Source: GitHub Actions**

### 3. Enable GitHub Actions
**Actions tab → Enable workflows**

### 4. Run manually to test
Go to **Actions → Daily Ingest → Run workflow** to trigger the full chain.

## Data Sources

- **ESPN API** — Game scores, schedules, player box scores (free, no key required)
- **Rotowire** — Injury and lineup status (scraped)
- **Anthropic Claude** — AI analysis (requires API key)
