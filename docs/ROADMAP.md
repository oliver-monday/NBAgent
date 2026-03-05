# NBAgent — Roadmap & Issue Log

---

## Resolved Issues

| Issue | Fix Applied |
|-------|-------------|
| API key "balance too low" error | Create new API key after adding credits — old key had sync issue |
| JSON truncation on large slates | analyst.py MAX_TOKENS increased 4096 → 8192 → 16384 |
| All 30 teams' injuries sent to prompt | `load_injuries()` filters to today's teams only |
| All whitelisted players sent regardless of who's playing | `build_player_context()` + Quant filter to whitelisted players on today's teams |
| Traded players appearing under old team | Whitelist filter changed from name-only to `(name, team)` tuple in both `analyst.py` and `quant.py` |
| Audit context too large | Reduced from 20 → 5 most recent entries |
| `Brandon MIller` typo in whitelist | Fixed to `Brandon Miller` — capital I caused name match failure |
| `injuries_today.json` empty on first run | Expected — hourly injuries workflow populates it; all agents handle empty gracefully |
| Parlays tab missing from live site | `build_site.py` merged with full Parlays tab (session March 5, 2026) |
| `SyntaxWarning: invalid escape sequence '\d'` in build_site.py | Pre-existing cosmetic warning in JS canvas regex block — does not affect runtime |
| **Improvement Proposal #2 — Opponent-Specific Tier Hit Rates** | Implemented in `quant.py` (`compute_matchup_tier_hit_rates()`, `MIN_MATCHUP_GAMES=3`) and `analyst.py` (`load_player_stats()`, `build_quant_context()`, new QUANT STATS prompt section). `player_stats.json` now includes `matchup_tier_hit_rates` field; analyst prompt instructs Claude to down/upgrade tiers based on vs_soft/vs_tough deltas. |
| **P1 — Game Script Filter (Spread-Adjusted Blowout Risk)** | Implemented across `espn_daily_ingest.py` (spreads collected from ESPN Core odds API via `fetch_moneylines_for_game()`), `quant.py` (`build_game_spreads()`, `compute_spread_split_hit_rates()`, `today_spread`/`spread_abs`/`blowout_risk`/`spread_split_hit_rates` in player output), `analyst.py` (`build_quant_context()` shows spread + blowout flag per player, prompt rules: down one tier when BLOWOUT_RISK=True, cap confidence at 80% when spread_abs > 13). Historical coverage limited to Oct 21–Nov 13, 2025; accumulates from March 2026 forward. |

---

## Open Items

### Operational
- **Whitelist maintenance** — review and update `active` flags as the season evolves, especially post-trade-deadline role changes
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **Team abbreviation audit** — verify NYK/NY, GSW/GS, UTA/UTAH, NOP/NO, SAS/SA consistency across all ingest sources and whitelist `team_abbr_alt` column

### Technical Debt
- **`context/nba_season_context.md`** — manually maintained; needs periodic updates as roster/role changes accumulate. Consider adding a maintenance reminder to the repo README.
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. This is intentional (ensures freshness) but adds ~10s to runtime. Low priority.

### Frontend
- **Parlays tab historical stats banner** — hidden until graded parlay history exists. Once data accumulates (1–2 weeks), evaluate whether to add a rolling chart similar to the picks trend chart.
- **Mobile layout** — current pick cards are readable but not optimized for small screens. Low priority until real users request it.

---

## Improvement Proposals

### Completed / Deferred

**#1 — Usage-Share Delta When Teammates Are Out**
**Status: DEFERRED** — insufficient DNP sample data mid-season. Key star pairings (Brunson/KAT, LeBron/Luka, etc.) have 0 absence games; most whitelisted player pairs have <3 shared absence games. Highest-alpha proposal — revisit at start of next season with a full year of data.
- `quant.py` — `build_teammate_absence_deltas()`. Joins `player_game_log.csv` DNP rows to compute per-player stat delta when each teammate is absent vs. present. Stores as `teammate_absence_delta` in `player_stats.json`.
- `analyst.py` — instruction: "If a key teammate is listed as OUT today and their absence delta is ≥+2 pts or ≥+1 reb/ast, factor this into tier selection."

**#2 — Opponent-Specific Tier Hit Rates ✅ IMPLEMENTED**
- `quant.py` — `compute_matchup_tier_hit_rates()`. Full season history split by opponent defensive rating (soft/mid/tough). Stored as `matchup_tier_hit_rates` in `player_stats.json`.
- `analyst.py` — `build_quant_context()` injects per-player `vs_soft`/`vs_tough` rates into prompt. Prompt instructs Claude to weight matchup-specific rate over overall when opp is rated soft or tough.

---

### Active Queue — In Priority Order

---

#### P1 — Back-to-Back Quantified Tier Adjustment
**Priority: MEDIUM — known hole, currently handled qualitatively only**

**What:** Compute each player's tier hit rate specifically on B2B second nights vs. normal rest. Store as `b2b_hit_rates` alongside normal `tier_hit_rates` in `player_stats.json`.

**Why:** B2B fatigue is a real effect but currently a soft warning in the prompt. If a player's PTS tier 20 drops from 78% normally to 45% on B2Bs, the correct pick is tier 15 — this correction only happens if Claude reasons about it unprompted, which is inconsistent.

**Where:** `quant.py` — filter historical games where the player's team played the night before (reuses `build_b2b_teams()` logic applied retroactively using `nba_master.csv` date pairs). Analyst prompt: "When `on_back_to_back = true`, use `b2b_hit_rates` instead of `tier_hit_rates`. If B2B sample <5 games, apply a conservative one-tier-down adjustment."

**Note:** Implement together with P2 (Days of Rest) — both use `nba_master.csv` date logic and extend the same player_stats.json rest/fatigue context block.

---

#### P2 — Positional DvP (Defense vs. Position)
**Priority: MEDIUM — upgrades opp_defense from team-level to position-aware**

**What:** Split opponent's allowed stats by the position of the player who scored/rebounded/assisted. Add a `position` column (PG/SG/SF/PF/C) to `player_whitelist.csv`. Compute allowed PTS/REB/AST per position group per opposing team. Replaces or supplements the current team-level `opp_defense_rating`.

**Why:** Team-level allowed averages miss positional targeting. The Thunder may allow 110 pts/game overall but suppress guards completely while being soft on centers — the current rating would show "mid" for both. A position-aware rating directly improves the opp_defense signal for every pick.

**Where:** `player_whitelist.csv` — add `position` column (manual, ~5 minutes). `quant.py` — extend `build_opp_defense()` to join on position. `player_stats.json` — `opp_defense` gains `position_rating` field. `analyst.py` — prompt uses position-specific rating when available.

**Data dependency:** Requires manual `position` column addition to whitelist before implementation.

---

#### P3 — Days of Rest / Schedule Density
**Priority: MEDIUM — light lift, more precise than binary B2B flag**

**What:** Per player: `days_since_last_game`, `games_last_7_days`, `dense_schedule` bool (4+ games in 5 nights). All derived from `nba_master.csv` game dates — no new data sources.

**Why:** The current `on_back_to_back` flag is binary and misses softer fatigue signals. A player on 1 day rest after 3 games in 4 nights is meaningfully different from a player on 3 days rest, even if neither is a true B2B. Schedule density captures cumulative fatigue that the binary flag cannot.

**Where:** `quant.py` — ~20 lines of date arithmetic on `nba_master.csv`. Adds `rest_days`, `games_last_7`, `dense_schedule` to `player_stats.json`. `analyst.py` — brief prompt instruction for rest context alongside existing B2B flag.

**Note:** Implement together with P1 (B2B Quantified) as a combined rest/fatigue block.

---

#### P4 — Rolling Volatility Score Per Player Per Stat
**Priority: MEDIUM — prevents overconfidence in streaky players**

**What:** Standard deviation of binary hit outcomes over the last 20 games at the best tier for each stat. Express as `"consistent"` (σ < 0.3), `"moderate"` (0.3–0.4), or `"volatile"` (σ > 0.4).

**Why:** Hit rate is an average — it hides whether a player is a reliable 80% hitter or a streaky player who goes 10/10 then 2/10. A volatile player at 75% is a worse prop bet than a consistent player at 72%.

**Where:** `quant.py` — `compute_volatility()` alongside `compute_tier_hit_rates()`. 20-game window for stability. `analyst.py` — instruction: "Prefer consistent or moderate volatility players when confidence is otherwise similar. Flag volatile players in reasoning."

---

#### P5 — Shooting Efficiency Regression Flag
**Priority: LOWER — high signal for PTS props, requires ingest schema change**

**What:** L5 vs. L20 shooting % delta per player. Flag players shooting materially above/below season FG% over the last 5 games as regression candidates. Applied specifically as a PTS confidence modifier, not universal.

**Why:** A player hitting 8% above their season FG% over 5 games has a more fragile counting stat floor than their hit rate suggests — mean reversion is real and predictable from shooting data. Currently invisible to the system.

**Where:** `espn_player_ingest.py` — add `fga`, `fgm`, `fg3a`, `fg3m` columns (ESPN provides these). `player_game_log.csv` schema change. `quant.py` — `compute_shooting_regression()`. `analyst.py` — regression flag in quant context block.

**Data dependency:** Requires ingest schema change — coordinate as a standalone session. Do not mix with other quant.py changes until ingest is updated.

---

#### P6 — Tier-Walk Audit Trail in Pick Output
**Priority: LOWER — improves feedback loop, compounds over time**

**What:** Add a `tier_walk` field to the Analyst output schema documenting Claude's walk-down reasoning, e.g. `"30:3/10 25:5/10 20:8/10→pick"`.

**Why:** The current `reasoning` field hides tier selection logic. Impossible to audit whether Claude skipped a better tier or made a sound walk-down. Enables Auditor to flag systematic tier-selection errors over time.

**Where:** `analyst.py` prompt — add `tier_walk` to output schema. Instruction: "Always show your walk-down. Never pick a tier if the tier above it also qualifies." `auditor.py` — future enhancement: flag picks where chosen tier's hit rate is lower than the tier above it.

---

## Implementation Notes

- **P1 (B2B + Days of Rest)** — implement together in one session; both use `nba_master.csv` date logic and populate the same rest/fatigue context block in `player_stats.json`.
- **P2 (Positional DvP)** — requires adding `position` column to `player_whitelist.csv` before coding begins. Manual step, ~5 minutes.
- **P4 (Volatility) and P6 (Tier-Walk)** — fully independent of each other and all other proposals. Can be implemented in any order.
- **P5 (Shooting Regression)** — requires `espn_player_ingest.py` schema change. Plan as a standalone session; do not bundle with quant-only changes.
- **#1 (Teammate Absence Delta)** — highest long-run alpha; revisit at season start when full-year DNP data exists.
