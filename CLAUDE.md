# NBAgent — CLAUDE.md

You are the technical co-builder for **NBAgent**, an autonomous NBA player props prediction system. Read this file first on every session, then load the `@docs/` files relevant to the task at hand.

---

## What NBAgent Does

A self-improving multi-agent system that runs entirely via GitHub Actions. Every day it:

1. Ingests fresh ESPN box scores and game data (`espn_daily_ingest.py`, `espn_player_ingest.py`)
2. Scrapes Rotowire for injury updates hourly (`rotowire_injuries_only.py`)
3. **Auditor** grades yesterday's picks + parlays, writes structured feedback to `audit_log.json` + rolls up `audit_summary.json`
4. **Quant** computes deterministic per-player stats cards from raw game logs — tier hit rates, best qualifying tier per stat, trend (L5 vs L20), home/away splits, B2B flag and quantified B2B hit rates, opponent defense rating, spread context, matchup-specific tier hit rates, teammate correlations (Pearson r + correlation tags), game pace context, bounce-back profiles, volatility scores, positional DvP, FG% safety margin, shooting regression flags, player profile narratives, team momentum, and defensive recency splits
5. **Pre-Game Reporter** summarises today's ESPN player news + detects staleness in `nba_season_context.md` → `pre_game_news.json`
6. **Analyst** reads today's slate + Quant output + Auditor feedback + Rolling summary → calls Claude API → generates prop picks; skips are recorded to `skipped_picks.json`
7. **Lineup Watch** post-processes picks after each injury refresh — voids OUT picks, flags DOUBTFUL/QUESTIONABLE picks with risk levels
8. **Lineup Update** diffs afternoon lineup changes against morning snapshot → calls Claude → amends affected picks
9. **Post-Game Reporter** fetches ESPN exit news + Brave Search web narratives for missed-pick players → `post_game_news.json`
10. **Parlay** reads today's picks → builds scored combinations → calls Claude API → generates 3–5 curated parlays
11. Builds and deploys a static frontend to GitHub Pages

Picks: **PTS / REB / AST / 3PM** — OVER only, ≥70% confidence.
API cost: ~$0.60/day (analyst + parlay + auditor combined at current slate sizes).

---

## Repo Structure

```
NBAgent/
├── agents/
│   ├── quant.py              # Deterministic stats cards — tier hit rates, best tier, trend, B2B, opp defense, matchup splits, spread context, teammate correlations, game pace, bounce-back profiles, volatility, positional DvP, FG% safety margin, shooting regression, player profiles, team momentum, defensive recency
│   ├── analyst.py            # Analyst agent — calls Claude, generates picks; injects season context + rolling audit summary; writes skipped_picks.json
│   ├── parlay.py             # Parlay agent — calls Claude, generates parlays; reads parlay audit feedback
│   ├── auditor.py            # Auditor agent — grades picks + parlays + skips, writes audit_log.json + audit_summary.json; injects season context
│   ├── pre_game_reporter.py  # Summarises ESPN player news; detects nba_season_context.md staleness → pre_game_news.json
│   ├── post_game_reporter.py # Fetches ESPN exit news + Brave Search web narratives for missed-pick players → post_game_news.json
│   ├── lineup_watch.py       # Deterministic post-process — voids OUT picks, flags DOUBTFUL/QUESTIONABLE; runs after each injury refresh
│   ├── lineup_update.py      # Afternoon amendment agent — diffs morning lineup snapshot vs current, calls Claude, writes lineup_update sub-objects to picks
│   ├── backtest.py           # Standalone retrospective signal analysis — multiple modes (see docs/BACKTESTS.md)
│   ├── playoff_matchup.py    # Pure Python — reads playoff_bracket.json + game logs, writes playoff_matchup.json; no-op if bracket absent
│   └── build_site.py         # Static site generator (5-tab dark theme SPA); renders voided/risk/update/review badges
├── ingest/
│   ├── espn_daily_ingest.py        # Game slate + spreads + standings from ESPN API → nba_master.csv, standings_today.json
│   ├── espn_player_ingest.py       # Player box scores → player_game_log.csv, team_game_log.csv, player_dim.csv
│   └── rotowire_injuries_only.py   # Injury + lineup scrape → injuries_today.json, lineups_today.json; optional projected_minutes + onoff_usage when Rotowire creds present
├── context/
│   └── nba_season_context.md   # Manually maintained NBA context — injected into Analyst AND Auditor prompts
├── data/
│   ├── nba_master.csv                  # Season game data (game slate, scores, spreads, moneylines); includes season_type (2=regular, 3=postseason) from ESPN scoreboard
│   ├── player_game_log.csv             # Player box scores — one row per player per game; season_type joined from nba_master.csv via game_id
│   ├── playoff_career_log.csv          # Career playoff + regular season box scores (2021–2025 backfill + daily playoff dual-write from espn_player_ingest.py)
│   ├── player_dim.csv                  # ESPN athlete_id → player name map
│   ├── team_game_log.csv               # Team-level aggregated box scores — used by Quant for opp defense + pace
│   ├── player_stats.json               # Quant output — consumed by Analyst, Parlay, and Auditor
│   ├── injuries_today.json             # Hourly updated by injuries workflow
│   ├── lineups_today.json              # Projected starters + snapshot_at_analyst_run; written by rotowire_injuries_only.py
│   ├── standings_today.json            # Current NBA standings — written by espn_daily_ingest.py; feeds PLAYOFF PICTURE block
│   ├── team_defense_narratives.json    # Auto-generated per-team defensive narrative — written by quant.py
│   ├── pre_game_news.json              # Today's player news summaries + staleness flags — written by pre_game_reporter.py
│   ├── post_game_news.json             # Yesterday's exit news + web narratives for missed players — written by post_game_reporter.py
│   ├── picks.json                      # All picks with results; mutated in-place by analyst (append), lineup_watch (void/flag), lineup_update (lineup_update sub-object), auditor (grade)
│   ├── skipped_picks.json              # Today's rule-forced skips (null grading fields); graded each morning by auditor; overwritten daily
│   ├── parlays.json                    # All parlays with results
│   ├── audit_log.json                  # Daily auditor entries — full graded pick details
│   ├── audit_summary.json              # Rolled-up season stats — consumed by Analyst as Rolling Performance Summary; includes skip_validation + human_flag_precision blocks
│   ├── picks_review_YYYY-MM-DD.json    # Human-produced daily review file — verdicts: keep/trim/manual_skip; committed before auditor.yml runs; NOT written by any agent
│   ├── odds_available.json             # Pre-fetched FanDuel alternate market lines — written by odds_today.py --prefetch; consumed by analyst.py as market availability gate
│   ├── odds_today.json                 # Diagnostic odds cache — written by odds_today.py after picks; enriches picks.json with market_line/edge_pct
│   ├── odds_pretip.json                # Morning baseline + pre-tip odds snapshots — written by odds_today.py main() and --pretip; consumed for CLV tracking
│   ├── playoff_matchup.json            # Per-series playoff context — written by playoff_matchup.py; consumed by analyst.py; absent during regular season
│   └── context_flags.md                # Staleness flags written by pre_game_reporter.py; picked up by analyst via ⚠ CONTEXT FLAG mechanism
├── playerprops/
│   └── player_whitelist.csv    # Active player tracking list — (player_name, team_abbr) tuple filter; includes position column for DvP
├── site/
│   └── index.html              # Auto-generated, deployed to GitHub Pages
├── docs/
│   ├── SESSION_CONTEXT.md      # Session handoff — current schema, function signatures, design decisions, known gotchas
│   ├── AGENTS.md               # Agent logic, config, schemas
│   ├── DATA.md                 # All CSV/JSON schemas, player whitelist with current roster, team abbreviation notes
│   ├── ROADMAP_active.md       # Open items, active queue, watch items, pending backtests
│   ├── ROADMAP_resolved.md     # Historical log — resolved issues, completed improvements
│   ├── ROADMAP_Offseason.md    # Deferred improvements, off-season plan
│   └── BACKTESTS.md            # Completed backtest log — findings, verdicts, and implementation status
├── .github/workflows/
│   ├── ingest.yml              # ~7 AM PT daily — ingests ESPN data, runs quant
│   ├── injuries.yml            # Every :15 and :45, 11:45 AM–8:45 PM PT — scrapes Rotowire, runs lineup_watch + lineup_update, rebuilds site
│   ├── auditor.yml             # Chains off ingest — grades yesterday's picks + skips, writes audit_log + audit_summary
│   ├── analyst.yml             # Chains off auditor — runs rotowire → quant → odds_prefetch → pre_game_reporter → analyst → odds_enrich → parlay → deploy
│   ├── odds.yml               # Manual-only — standalone odds fetch for mid-day re-runs
│   └── odds_pretip.yml        # Every 30 min 3–7:30 PM PT — pre-tip odds sweep, updates picks.json + odds_pretip.json
└── CLAUDE.md                   # This file
```

---

## Workflow Chain

```
ingest.yml → auditor.yml → analyst.yml (rotowire refresh → quant → playoff_matchup → odds_prefetch → pre_game_reporter → analyst → odds_enrich → parlay → deploy)
injuries.yml runs independently on :15/:45 schedule (rotowire → lineup_watch → lineup_update → site rebuild)
odds_pretip.yml runs independently every 30 min 3–7:30 PM PT (pre-tip odds sweep → picks.json update → CLV baseline)
post_game_reporter.py runs as first step of auditor.yml (fetches ESPN recaps + Rotowire news for yesterday's missed picks)
```

- All workflows: `TZ: America/Los_Angeles`
- Commits: `github-actions[bot]` with `[skip ci]` to prevent loops
- **Required secrets:** `ANTHROPIC_API_KEY`, `BRAVE_API_KEY`, `ODDS_API_KEY`, `ROTOWIRE_EMAIL`, `ROTOWIRE_PASSWORD`
- **Model used by all LLM agents:** `claude-sonnet-4-6` (analyst upgrades to `claude-opus-4-6` on slates >30 active players)

---

## Agent Config (quick reference)

| Agent | Model | MAX_TOKENS | Key inputs | Key output |
|-------|-------|-----------|------------|------------|
| quant.py | — (pure Python) | — | player_game_log, team_game_log, nba_master, player_whitelist | player_stats.json, team_defense_narratives.json |
| pre_game_reporter.py | claude-sonnet-4-6 | 2048 | ESPN player news, nba_season_context.md | pre_game_news.json, context_flags.md |
| analyst.py (Scout) | claude-sonnet-4-6 / opus-4-6 | 4096 | player_stats.json, injuries, lineups, game logs, nba_season_context, standings, team_defense_narratives, pre_game_news, player_profiles, leaderboard, odds_available.json | Scout shortlist (20–25 players) |
| analyst.py (Pick) | claude-sonnet-4-6 | 32000 | Scout shortlist, filtered player_stats.json, injuries, audit_log (last 5), audit_summary, odds_available.json | picks.json (append), skipped_picks.json |
| parlay.py | claude-sonnet-4-6 | 4096 | picks.json, player_stats.json, audit_log (last 3 parlay feedback) | parlays.json (append) |
| post_game_reporter.py | claude-sonnet-4-6 | 2048 | picks.json (yesterday), ESPN athlete news, Brave Search | post_game_news.json |
| auditor.py | claude-sonnet-4-6 | 2048 | picks.json, parlays.json, skipped_picks.json, player_game_log, post_game_news.json, nba_season_context, standings, picks_review_YYYY-MM-DD.json (optional) | audit_log.json, audit_summary.json, updates picks + parlays in-place, grades skipped_picks.json |
| playoff_matchup.py | — (pure Python) | — | playoff_bracket.json, nba_master.csv, player_game_log.csv, player_whitelist.csv | playoff_matchup.json (no-op if bracket absent) |
| lineup_watch.py | — (pure Python) | — | injuries_today.json, picks.json | picks.json (in-place mutations: voided, lineup_risk) |
| lineup_update.py | claude-sonnet-4-6 | 2048 | lineups_today.json (snapshot), injuries_today.json, picks.json, nba_master.csv | picks.json (lineup_update sub-object on affected picks) |

Full agent details → **@docs/AGENTS.md**

---

## Key Data Flows (non-obvious)

- **`audit_summary.json`** is generated fresh after every auditor run by `save_audit_summary()`. The Analyst reads it as `## ROLLING PERFORMANCE SUMMARY` — provides season hit rates, per-prop rates, miss classification totals, and `skip_validation` per-rule false skip rates. Returns empty string if fewer than 3 audit entries exist (graceful cold-start).
- **`player_stats.json`** is consumed by three agents: Analyst (pick generation), Parlay (correlation tags, spread context), and Auditor (audit context injection for root-cause grading). Do not change its schema without checking all three consumers.
- **`picks.json`** is mutated in-place by four separate processes in sequence: Analyst appends new picks, lineup_watch.py mutates voided/risk fields, lineup_update.py writes `lineup_update` sub-objects (hourly, conditional on changes), Auditor grades results and tags `human_verdict`/`trim_reasons` from `picks_review_YYYY-MM-DD.json`. Always read the full file before writing — never overwrite with a subset.
- **`skipped_picks.json`** is written fresh each morning by analyst (null grading fields), then graded by auditor the next morning. Committed by both `analyst.yml` and `auditor.yml`. Accumulates only today's skips — not a historical archive.
- **`context/nba_season_context.md`** is injected into BOTH `analyst.py` and `auditor.py` prompts. Updates to this file affect both agents.
- **`pre_game_news.json`** staleness flags are picked up by `analyst.py` via the `⚠ CONTEXT FLAG` mechanism — Python-detected stale facts in `nba_season_context.md` are surfaced to the analyst as warnings without modifying the context file automatically.
- **`post_game_news.json`** includes `web_narrative` fields (Brave Search summaries) for missed-pick players. Auditor renders these as `📰 WEB RECAP:` in the audit prompt — addresses ejections, foul trouble, and blowout context that ESPN athlete news misses.
- **Parlay audit feedback loop** — `parlay.py` reads the last 3 `audit_log.json` entries for `parlay_reinforcements` and `parlay_lessons` and injects them into the Claude prompt.
- **`odds_available.json`** is written by `ingest/odds_today.py --prefetch` early in `analyst.yml` (before the analyst runs). Consumed by `analyst.py` via `load_available_markets()` + `format_available_markets()` as an unconditional market availability gate: if no FanDuel alternate market exists for a player+prop+tier, the pick is forbidden (`no_market` skip). Gate disabled when file is missing or stale (graceful degradation — all picks proceed normally). `odds_today.json` is written later by `ingest/odds_today.py` (no flag) to enrich picks with market lines post-generation.
- **Cross-workflow file persistence** — each GitHub Actions workflow does a fresh checkout. Files written but not committed by an upstream workflow are absent downstream. `lineups_today.json` and `skipped_picks.json` are both committed by `analyst.yml` so downstream hourly runs can read them. `playoff_career_log.csv` is committed by `ingest.yml` so that any playoff rows dual-written by `espn_player_ingest.py`'s `append_playoff_rows()` persist for consumption by `compute_playoff_splits()` in `quant.py` on the next run (inert during regular season — file will be clean in `git status` until postseason games flow through). When adding any cross-workflow feature, explicitly verify: (1) what files the feature writes, (2) which downstream workflow reads them, (3) whether they are committed before that workflow runs.

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
| `bounce_back` | Per-stat: post_miss_hit_rate, lift, iron_floor, n_misses, near_miss_rate, blowup_rate, typical_miss |
| `volatility` | Per-stat: sigma + label (volatile/consistent/moderate) at best qualifying tier |
| `opp_defense` | Opponent's allowed avg + rank + rating (soft/mid/tough), last 15 games, per stat |
| `def_recency` | Opponent's L5 vs L15 allowed PTS trend: flag (soft/tough/null), l5_avg, l15_avg, delta_pct |
| `game_pace` | Combined scoring avg for today's matchup + pace_tag (high/mid/low) |
| `teammate_correlations` | Pearson r + correlation tag per stat pair with each whitelisted teammate |
| `today_spread` / `spread_abs` / `blowout_risk` | Spread context for today's game |
| `rest_days` / `games_last_7` / `dense_schedule` | Schedule fatigue context |
| `on_back_to_back` | Bool — true if today is second night of B2B |
| `raw_avgs` / `avg_minutes_last5` / `minutes_trend` | Volume context |
| `minutes_floor` | floor_minutes + avg_minutes over L10; null if <5 games |
| `positional_dvp` | Position-specific opponent defense ratings (pts/reb/ast/tpm); falls back to team-level when <10 positional games |
| `ft_safety_margin` | FG% safety margin (H11): label, margin, breakeven_fg_pct, season_fg_pct |
| `shooting_regression` | fg_flag (hot/cold/null), fg_delta_pct — L5 vs L20 FG% divergence |
| `playoff_profile` | Career playoff vs regular season deltas (PTS/REB/AST/3PM/FG%) from `data/playoff_career_log.csv` (2021–2025); null if <5 career playoff games. Annotation-only, gated to `PLAYOFFS_R1_DATE = 2026-04-18` in analyst output |
| `team_momentum` | L10 W-L record + avg point margin + tag (hot/cold/neutral) for player's team and opponent |
| `profile_narrative` | Live scoring portrait text block (Players Profiles); null if <10 games or no qualifying PTS tier |
| `whitelisted_teammates` | Sorted list of other active whitelisted players on same team playing today; `[]` when none; used to ground Analyst teammate references and prevent stale training knowledge hallucinations |

Full schema → **@docs/DATA.md** and **@docs/SESSION_CONTEXT.md**

---

## picks.json — Fields Added Since Launch

The base schema is in `@docs/DATA.md`. These fields were added post-launch:

| Field | Set by | Notes |
|-------|--------|-------|
| `game_time` | Analyst | Formatted game time string, e.g. `"7:30 PM PT"` |
| `voided` | lineup_watch.py | `true` when player is listed OUT; pick treated as inactive. **Grading contract:** `voided=True` picks always have `result=null, actual_value=null` — auditor skips grading them entirely |
| `void_reason` | lineup_watch.py | e.g. `"OUT: Knee (Rotowire)"`. Also set post-hoc by auditor for late DNPs detected at grading time (auditor promotes to `voided=True` when `void_reason` non-empty + `actual=0.0`) |
| `lineup_risk` | lineup_watch.py | `"high"` (DOUBTFUL) or `"moderate"` (QUESTIONABLE); not set for OUT |
| `injury_status_at_check` | lineup_watch.py | `OUT / DOUBTFUL / QUESTIONABLE / NOT_LISTED` — written to ALL today's picks on every run |
| `injury_check_time` | lineup_watch.py | ISO timestamp of last lineup_watch run |
| `tier_walk` | Analyst | Tier walk-down reasoning string; shown on pick cards as expandable |
| `walked_tier` | Analyst | Integer — final tier after all step-downs; set by analyst, verified by `reconcile_pick_values()`. Must equal `pick_value` |
| `iron_floor` | Analyst | `true` when quant stat line showed `[iron_floor]`; Claude copies directly from context |
| `top_pick` | Analyst | `true` for 2–4 analyst-declared best picks of the day; `false` for all others; used by `build_site.py` `get_top_picks()` as primary selection signal |
| `lineup_update` | lineup_update.py | Sub-object: `{triggered_by, updated_at, direction, revised_confidence_pct, revised_reasoning}`; written hourly when starter changes detected; overwritten on each run |
| `human_verdict` | auditor.py | `"keep"/"trim"/"manual_skip"/null` — tagged from daily `picks_review_YYYY-MM-DD.json`; null when pick not reviewed |
| `trim_reasons` | auditor.py | List of strings from review file; `[]` when not reviewed or verdict is `"keep"` |
| `morning_implied_prob` | odds_today.py (pretip) | FanDuel morning implied prob; set once by `pretip_sweep()` before overwriting with pre-tip odds; used for CLV; null when no pretip sweep ran |
| `clv_pp` | auditor.py | Closing Line Value in pp (`pretip_implied − morning_implied`); positive = beat the close; null when no morning+pretip data |

---

## Whitelist Notes

**File:** `playerprops/player_whitelist.csv`
**Columns:** `team_abbr, team_abbr_alt, player_name, active, position`
**Filter logic:** `(player_name.lower(), team_abbr.upper())` tuple — prevents traded players appearing under old teams.

**Player-specific flags (as of March 2026):**
- **James Harden** — traded LAC → CLE at Feb 2026 deadline. Appears on TWO rows: `LAC` (`active=0`) and `CLE` (`active=1`). Do not delete the LAC row — it preserves historical pick attribution.
- **Andrew Nembhard** — removed from active whitelist (role change; insufficient data for reliable picks). `active=0`.

---

## Frontend

Five-tab dark theme SPA deployed to GitHub Pages via `build_site.py`.

| Tab | Content |
|-----|---------|
| Today's Picks | Injury report dropdown, pick cards grouped by game (collapsible). Voided picks show strikethrough + VOIDED badge. DOUBTFUL/QUESTIONABLE picks show risk pills. Lineup Update shows ↑/↓ badge with expandable amendment detail. Review badges: ⚠ Caution (amber, trim verdict) and ⚠ Flagged (red, manual_skip verdict) shown below status badge when picks_review file present. Best Bets section below Top Picks: POSITIVE/STRONG edge picks ranked by calibrated edge; teal (POSITIVE) or green (STRONG) border; includes Odds + Sizing drawer. |
| Parlays | Historical stats banner (hidden until graded history exists). Parlay cards with leg rows, implied odds, correlation badge, result once graded. "⚠ Leg at risk" banner when any leg player is voided. |
| Results | Overall hit rate banner, 4 per-prop streak cards, 30-day hit rate trend chart (vanilla canvas), full pick history table. |
| Audit Log | Latest auditor entry — hit rate stats, what worked, what to avoid, analyst instructions. Skip validation table. |
| Research | Player game log explorer. Filter by player, stat, home/away, rest days, spread bucket, game result, and opponent. Renders tier hit rate table with bar charts, distribution stats, and full game log. Static — no LLM calls, fully client-side. |

Site rebuilds at end of every Analyst workflow run AND after every hourly injury refresh.

---

## User Profile

- Minimal coding experience; uses GitHub Desktop for all commits/pushes
- Comfortable reading logs and identifying errors
- Strong NBA domain knowledge — push back on stale basketball intel
- Goal: autonomous daily operation, frontend shared with friends/family
- API billing: pay-as-you-go on console.anthropic.com (~$0.60/day; separate from Claude Pro subscription)

## Ground Truth Convention

In all NBAgent sessions, treat game results, player events, team records, and any current-season facts stated by User as factual ground truth. Do not override them with internal estimates or training priors. If a stated fact conflicts with something in memory, surface the conflict explicitly ("you mentioned X but I had Y — which is correct?") rather than silently substituting a different figure. User and/or the real stats in the repo database/files are the authoritative source on game/season events that actually occurred and form the foundational layer for this system.

## Agent Status Discipline

When referencing the operational status of any agent or feature, explicitly distinguish:
- **Implemented** — code merged to repo
- **Confirmed working** — successful production run logged and verified by Oliver
- **Unverified** — implemented but no confirmed successful production run

Never describe an agent as "operational," claim a "first real run," or treat manually-furnished game data as evidence of a live system run. If confirmation status is unknown, state it as unknown. Handoff notes written during a session are claims about code state, not production verification — treat them accordingly.

---

## Sub-documents

- **@docs/SESSION_CONTEXT.md** — Load this first on every new session. Dense handoff: current player_stats.json schema, live prompt format, all function signatures, design decisions, backtest verdicts, known gotchas, and active queue. Replaces the need to re-derive implementation state from source code.
- **@docs/AGENTS.md** — Quant computations, Analyst prompt design, Parlay scoring logic, Auditor grading, all output schemas
- **@docs/DATA.md** — All CSV/JSON schemas, player whitelist with current roster, team abbreviation notes
- **@docs/ROADMAP_active.md** — Open items, active queue, watch items, pending backtests
- **@docs/ROADMAP_resolved.md** — Historical log of resolved issues and completed improvements
- **@docs/ROADMAP_Offseason.md** — Deferred improvements and off-season plan
- **@docs/BACKTESTS.md** — Completed backtest log — findings, verdicts, and implementation status for all hypotheses tested
