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
| **P1 (formerly) — B2B Quantified Tier Adjustment + P3 (formerly) — Days of Rest / Schedule Density** | Implemented together in `quant.py`: `build_b2b_game_ids()` builds historical B2B game ID set per team; `compute_b2b_hit_rates()` computes tier hit rates on B2B second-night games per player (null when <5 games); `compute_rest_context()` computes `rest_days`, `games_last_7`, `dense_schedule` from nba_master dates. `build_player_stats()` extended with `b2b_hit_rates`, `rest_days`, `games_last_7`, `dense_schedule` in output. `analyst.py`: `build_quant_context()` shows `B2B`, `rest=Xd`, `DENSE`, `L7:Xg` flags per player header and `b2b=` rate per stat line when on B2B. Prompt adds KEY RULES — REST & FATIGUE block: use b2b= rates when B2B, one-tier-down fallback when <5g, 5-10% confidence reduction for DENSE. |
| **Backtest-driven prompt + quant calibration (March 2026)** | `agents/backtest.py` added (5,368 instances, Oct 21–Mar 3). Findings applied: (1) Tier ceiling rules added to analyst.py prompt with full-season evidence bars — REB T8+, AST T6+, 3PM T2+, PTS T25+ flagged as requiring exceptional justification. (2) 3PM opp_defense instruction inverted — tough PTS defense is a mild positive signal for 3PM (72.1% vs 60.9% hit rate); mechanism documented in prompt. (3) Trend and home/away removed as directive signals — confirmed noise across all 4 stats (5,368 instances); data retained, instruction weight removed. (4) `PLAYER_WINDOW` raised 10→20 in `quant.py` — backtest calibration showed REB T6 63%→72%, AST T6 63%→75%, PTS T25 65.7%→70.2% at window=20; REB T8 improved 9.6pp to 66.3% (above ≥65% deploy threshold); pick volume −25% but estimated ≥8 picks/day, above parlay minimum. |
| **Bounce-back analysis + player-level integration (March 2026)** | League-wide bounce-back backtest (Backtest 3, 3,559 consecutive pairs) confirmed null signal — all stats independent (lift 0.90–0.93), no next-game mean reversion from cold streaks (Backtest 4). Player-level analysis (`--mode player-bounce-back`) identified 19 iron-floor player-stat combinations and strong individual bounce-back profiles (e.g., Luka Doncic 3PM T2 100% post-miss n=12, Jaylen Brown PTS T20 100% n=11). Integrated into production pipeline: `build_bounce_back_profiles()` added to `quant.py` (full-season computation per player × stat × best tier; `post_miss_hit_rate`, `lift`, `iron_floor`, `n_misses`); `bounce_back` key added to `player_stats.json`; `build_quant_context()` in `analyst.py` annotates stat lines with `bb_lift=X.XX` or `[iron_floor]`; SELECTION RULES updated to treat post-miss picks neutrally when bb_lift > 1.15 and with no negative weight when iron_floor. |
| **Grading correction + full backtest re-run (March 2026)** | All production code and backtests corrected from strict `>` to `>=` grading (exact threshold = HIT). Changes applied across `auditor.py` (grade_picks), `quant.py` (all 4 hit rate functions + bounce-back profiles), `analyst.py` (prompt language), and `backtest.py` (9 locations). All 5 backtests re-run; JSON outputs regenerated. Key findings: 3PM T2 now 71.4% (above threshold — never miscalibrated, only misgraded); 3PM opp_defense verdict changed from PREDICTIVE → NOISE (inverted prompt instruction removed); PTS T20 now 69.6% (new borderline concern); total instances increased 5,368 → 6,437. `docs/BACKTESTS.md` rewritten with corrected numbers and correction note. |
| **Prompt calibration from corrected backtests (March 2026)** | Three analyst.py prompt changes from corrected findings: (1) 3PM opp_defense inversion removed — signal is NOISE under correct grading; replaced with neutral language applying opp_defense conventionally for all stats. (2) 3PM cold-streak decline rule added to KEY RULES — SEQUENTIAL GAME CONTEXT (lift=0.87, n=161; severe cold streak → −5% confidence or skip). (3) PTS T25 now requires ≥80% individual hit rate (8+/10) before selection. Tier ceiling instance counts and hit rates updated to corrected values throughout. |
| **REB opp_defense decoupled (March 2026)** | Auditor confirmed that opp_defense_rating is not a valid signal for REB props (Giannis, Jalen Johnson, Hartenstein all missed T8/T6 REB on soft-defense logic, 2026-03-04). `analyst.py` prompt updated: stat-specific OPPONENT DEFENSE block added; REB explicitly excluded with mechanism explanation (points-allowed doesn't capture pace, opponent FG%, or frontcourt competition). REB T8 ceiling rule updated to remove opp_defense as a qualifying condition. |
| **Offensive-first player REB floor rule (March 2026)** | Added to analyst.py SELECTION RULES: players with PTS avg > 20 or AST avg > 6 should be targeted at or below their 25th-percentile recent REB output; if the player's REB floor (lowest L10 value) is within 2 of the intended pick value, skip the REB prop and pick scoring/assists instead. |
| **Auditor root cause discipline (March 2026)** | Added ROOT CAUSE DISCIPLINE block to `auditor.py` `build_audit_prompt()`: three pre-flight checks required before assigning any miss root cause — (a) DNP check via non-zero stats, (b) variance check for near-misses within 1–2 units, (c) game-level cause check for same-game prop-type clusters. Prevents false "lineup failure" attribution when box score shows the player was active. |
| **Lineup watch script (March 2026)** | `agents/lineup_watch.py` added — deterministic post-processing pass that runs after each Rotowire injury refresh. Reads today's open picks and mutates them in-place: OUT → `voided=True` + `void_reason`; DOUBTFUL → `lineup_risk="high"`; QUESTIONABLE → `lineup_risk="moderate"`. Team abbrev mismatches (NYK/NY, GS/GSW, etc.) avoided by flattening injury lookup to `player_name.lower()` across all teams. Severity sticky upward — picks are never downgraded. `injuries.yml` updated with two new steps (run lineup_watch, commit picks.json). `build_site.py` updated: voided picks display with strikethrough + VOIDED badge; DOUBTFUL/QUESTIONABLE picks show risk pills; parlay cards show "⚠ Leg at risk" banner when any leg player is voided. |
| **Auditor season context injection (March 2026)** | `auditor.py`: Added `load_season_context()` (identical logic to `analyst.py`); season context injected into `build_audit_prompt()` with explicit OFS framing — the auditor is instructed not to cite permanent-absence players as causal factors in miss root causes. `context/nba_season_context.md`: Added PERMANENT ABSENCES rule block at top of SEASON FACTS section; strengthened Tatum line to "treat as if Tatum never existed this season." |
| **Auditor pre-computed statistics (March 2026)** | `auditor.py` `build_audit_prompt()`: Added Python pre-computation of `prop_type_breakdown` (picks + hits per prop type) and `confidence_calibration` (picks + hits per confidence band: 70–75 / 76–80 / 81–85 / 86+) before f-string injection — Claude copies values, does no arithmetic. Both fields added to `audit_log.json` OUTPUT FORMAT schema. `## PRE-COMPUTED STATISTICS` prompt section added so Claude has full numeric context before analysis. |
| **Auditor 4-step miss analysis + miss_classification (March 2026)** | `auditor.py` PICK ANALYSIS TASK block replaced with structured 4-step protocol: STEP 1 (CHECK ACTIVITY — DNP guard), STEP 2 (CLASSIFY THE MISS as exactly one of `selection_error` / `model_gap` / `variance`), STEP 3 (CRITIQUE THE ORIGINAL REASONING field), STEP 4 (REFERENCE HIT RATE DATA — must cite `hit_rate_display` and `trend` from the pick). `miss_classification` field added to `miss_details` schema in `audit_log.json`. Enables downstream aggregation of error taxonomy. |
| **Auditor player stats context injection (March 2026)** | `auditor.py`: `load_player_stats_for_audit(graded_picks)` added — filters `player_stats.json` to only picked players, slims each entry to 9 fields (`team`, `opponent`, `on_back_to_back`, `best_tiers`, `tier_hit_rates`, `trend`, `opp_defense`, `game_pace`, `teammate_correlations`). `## PLAYER STATS CONTEXT` section injected into `build_audit_prompt()` after FULL GRADED PICKS — gives auditor the quant baseline at pick time so root cause analysis can reference what the data actually showed. |
| **Parlay agent reads audit feedback (March 2026)** | `parlay.py`: `load_parlay_audit_feedback()` added — reads last 3 `audit_log.json` entries, formats each as one block with parlay hit/miss summary line plus bullet-point `parlay_reinforcements` (✓) and `parlay_lessons` (✗). `build_parlay_prompt()` updated to accept and inject `## PARLAY AUDIT FEEDBACK FROM PREVIOUS DAYS` section before PRE-SCORED CANDIDATES. `main()` wired up. Closes the parlay feedback loop — agent now sees what correlation types and leg structures have historically succeeded or failed. |
| **Longitudinal audit summary (March 2026)** | `auditor.py`: `save_audit_summary(audit_log)` added — after every audit run, rolls up entire `audit_log.json` history into `data/audit_summary.json` containing: overall season hit rate, per-prop hit rates (aggregated from `prop_type_breakdown`), miss classification totals (`selection_error`/`model_gap`/`variance` counts), confidence calibration totals (aggregated from `confidence_calibration`), parlay season totals, and last 5 days of lessons/reinforcements/recommendations. Called from `save_audit()` after log write. `auditor.yml` commit loop extended to include `data/audit_summary.json`. `analyst.py`: `load_audit_summary()` added — reads summary, returns `""` if file missing or fewer than 3 entries, otherwise formats a readable multi-line text block. `build_prompt()` signature updated; `## ROLLING PERFORMANCE SUMMARY` section injected between AUDITOR FEEDBACK and OUTPUT FORMAT. `main()` wired up. |

---

## Open Items

### Operational
- **Whitelist maintenance** — review and update `active` flags as the season evolves, especially post-trade-deadline role changes
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **Team abbreviation audit** — verify NYK/NY, GSW/GS, UTA/UTAH, NOP/NO, SAS/SA consistency across all ingest sources and whitelist `team_abbr_alt` column

### Untested Hypotheses (backtest designs documented in docs/BACKTESTS.md)
- **Post-Blowout Bounce-Back** — Do players on teams that suffered a blowout loss (opponent margin ≥15 pts) show elevated prop hit rates in their next game as a corrective response? Testable with `nba_master.csv` score differentials + next-game player performance. Expected signal: players facing a humiliating loss may have higher usage and motivation next game; or the effect is noise (same as league-wide bounce-back). Low data cost — all fields already available.
- **Opponent Schedule Fatigue** — Do player prop hit rates increase when the opposing team is playing their second game in two nights or coming off a dense 4-in-5 schedule? Testable with opponent B2B flags and schedule density computed from `nba_master.csv`. Extends the existing rest-context logic from self (own fatigue) to opponent (opponent fatigue = potential edge). Rest data already computed in `quant.py`'s `compute_rest_context()` — needs to be applied to the opposing team at backtest time.

### Technical Debt
- **`context/nba_season_context.md`** — manually maintained; needs periodic updates as roster/role changes accumulate. Consider adding a maintenance reminder to the repo README.
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. This is intentional (ensures freshness) but adds ~10s to runtime. Low priority.
- **`data/audit_summary.json` not yet seeded** — `save_audit_summary()` only runs going forward. Historical `audit_log.json` entries will be aggregated incrementally — the summary will be meaningfully populated after 3+ audit runs. `load_audit_summary()` returns empty string until then and the analyst prompt shows the placeholder message. No manual action needed.
- **`prop_type_breakdown` / `confidence_calibration` absent from pre-March audit entries** — older entries in `audit_log.json` won't have these fields; `save_audit_summary()` handles missing fields with `.get()` defaults. Per-prop and calibration totals in `audit_summary.json` will undercount until all historical entries are replaced by new runs. Acceptable accumulation behavior.

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

#### P1 — Positional DvP (Defense vs. Position)
**Priority: MEDIUM — upgrades opp_defense from team-level to position-aware**

**What:** Split opponent's allowed stats by the position of the player who scored/rebounded/assisted. Add a `position` column (PG/SG/SF/PF/C) to `player_whitelist.csv`. Compute allowed PTS/REB/AST per position group per opposing team. Replaces or supplements the current team-level `opp_defense_rating`.

**Why:** Team-level allowed averages miss positional targeting. The Thunder may allow 110 pts/game overall but suppress guards completely while being soft on centers — the current rating would show "mid" for both. A position-aware rating directly improves the opp_defense signal for every pick.

**Where:** `player_whitelist.csv` — add `position` column (manual, ~5 minutes). `quant.py` — extend `build_opp_defense()` to join on position. `player_stats.json` — `opp_defense` gains `position_rating` field. `analyst.py` — prompt uses position-specific rating when available.

**Data dependency:** Requires manual `position` column addition to whitelist before implementation.

---

#### P2 — Rolling Volatility Score Per Player Per Stat
**Priority: MEDIUM — prevents overconfidence in streaky players**

**What:** Standard deviation of binary hit outcomes over the last 20 games at the best tier for each stat. Express as `"consistent"` (σ < 0.3), `"moderate"` (0.3–0.4), or `"volatile"` (σ > 0.4).

**Why:** Hit rate is an average — it hides whether a player is a reliable 80% hitter or a streaky player who goes 10/10 then 2/10. A volatile player at 75% is a worse prop bet than a consistent player at 72%.

**Where:** `quant.py` — `compute_volatility()` alongside `compute_tier_hit_rates()`. 20-game window for stability. `analyst.py` — instruction: "Prefer consistent or moderate volatility players when confidence is otherwise similar. Flag volatile players in reasoning."

---

#### P3 — Shooting Efficiency Regression Flag
**Priority: LOWER — high signal for PTS props, requires ingest schema change**

**What:** L5 vs. L20 shooting % delta per player. Flag players shooting materially above/below season FG% over the last 5 games as regression candidates. Applied specifically as a PTS confidence modifier, not universal.

**Why:** A player hitting 8% above their season FG% over 5 games has a more fragile counting stat floor than their hit rate suggests — mean reversion is real and predictable from shooting data. Currently invisible to the system.

**Where:** `espn_player_ingest.py` — add `fga`, `fgm`, `fg3a`, `fg3m` columns (ESPN provides these). `player_game_log.csv` schema change. `quant.py` — `compute_shooting_regression()`. `analyst.py` — regression flag in quant context block.

**Data dependency:** Requires ingest schema change — coordinate as a standalone session. Do not mix with other quant.py changes until ingest is updated.

---

#### P5 — Afternoon Lineup Re-Reasoning Pass (`agents/lineup_update.py`)
**Priority: MEDIUM — targeted Claude call when a key player goes OUT after morning picks are set**
**Prerequisite: `lineup_watch.py` must be live first (✅ done as of March 2026)**
**Revisit: once 7+ days of amendment data accumulated in audit_log.json**

**What:** A focused LLM re-evaluation pass that triggers only when something meaningful has changed. Not a full analyst re-run — a minimal prompt scoped to the picks that are genuinely affected by a new absence.

**Trigger conditions (both must be true):**
- At least one player crossed to OUT or DOUBTFUL since the previous injury refresh (detected by comparing current `injuries_today.json` to a cached snapshot from the prior run, or by checking for new `voided=True` picks added by `lineup_watch.py`)
- Current time is before 5 PM ET (post-tip-off amendments are not actionable)

**Scope:** Does not re-pick from scratch. Identifies today's open picks (`result == null`, not voided) where the picked player is a teammate or opponent of a player who just went OUT/DOUBTFUL. Builds a minimal context block from `player_stats.json` for the newly-absent player: team, role descriptor, `avg_minutes_last5`, primary stat averages.

**Claude call:** Single focused prompt:
> "Given that [Player] is now OUT, does this meaningfully change the confidence or reasoning on any of these picks? Return only picks where your assessment changes, with revised `confidence_pct` and a one-sentence `updated_reasoning`. If no picks are materially affected, return an empty array []."

**Output schema additions to each amended pick in `picks.json`:**
```json
{
  "lineup_updated": true,
  "updated_at": "ISO timestamp",
  "morning_pick": {
    "confidence_pct": <original>,
    "reasoning": "<original reasoning>"
  },
  "confidence_pct": <revised>,
  "reasoning": "<revised reasoning>"
}
```
Original morning values are preserved in `morning_pick` — never overwritten.

**Audit integration:** `auditor.py` should detect `lineup_updated: true` picks and compare morning vs. afternoon confidence against actual outcomes. After ~20 audit entries with amendments, evaluate whether re-reasoned picks outperform their morning originals. Track as a separate signal in `audit_log.json`. If no improvement after 20 samples, cut the feature.

**Frontend:** Amended pick cards display a small `↻ Updated [time]` badge. Clicking/hovering the badge expands a comparison showing morning reasoning vs. revised reasoning side-by-side.

**Where:**
- `agents/lineup_update.py` — new script (~150 lines)
- `injuries.yml` — add step after `lineup_watch`, conditioned on time check and new-absence detection
- `auditor.py` — add `lineup_updated` pick tracking to grading and audit output
- `build_site.py` — `↻ Updated` badge and expandable reasoning comparison on pick cards

---

#### P4 — Tier-Walk Audit Trail in Pick Output
**Priority: LOWER — improves feedback loop, compounds over time**

**What:** Add a `tier_walk` field to the Analyst output schema documenting Claude's walk-down reasoning, e.g. `"30:3/10 25:5/10 20:8/10→pick"`.

**Why:** The current `reasoning` field hides tier selection logic. Impossible to audit whether Claude skipped a better tier or made a sound walk-down. Enables Auditor to flag systematic tier-selection errors over time.

**Where:** `analyst.py` prompt — add `tier_walk` to output schema. Instruction: "Always show your walk-down. Never pick a tier if the tier above it also qualifies." `auditor.py` — future enhancement: flag picks where chosen tier's hit rate is lower than the tier above it.

---

## Implementation Notes

- **P1 (Positional DvP)** — requires adding `position` column to `player_whitelist.csv` before coding begins. Manual step, ~5 minutes.
- **P2 (Volatility) and P4 (Tier-Walk)** — fully independent of each other and all other proposals. Can be implemented in any order. P4 (Tier-Walk) now has better downstream utility: `miss_classification` data accumulating in `audit_log.json` means the Auditor can eventually cross-reference tier-walk decisions against `selection_error` classifications.
- **P3 (Shooting Regression)** — requires `espn_player_ingest.py` schema change. Plan as a standalone session; do not bundle with quant-only changes.
- **P5 (Afternoon Re-Reasoning)** — requires `lineup_watch.py` already live (✅). Key open design question: change-detection mechanism for "new absence since last run" — simplest approach is comparing the current `injuries_today.json` against a prior-run snapshot cached to `data/injuries_prev.json` by `lineup_watch.py`. Revisit after 7 days of lineup_watch data to confirm voiding frequency and feasibility. Do not build until audit data confirms lineup_watch is functioning correctly.
- **#1 (Teammate Absence Delta)** — highest long-run alpha; revisit at season start when full-year DNP data exists.
- **Confidence calibration tracking (new, no proposal needed)** — `audit_summary.json` now accumulates per-band hit rates (70–75 / 76–80 / 81–85 / 86+). After 20+ audit days, compare actual hit rates to stated confidence bands. If a band systematically underperforms (e.g., 86%+ picks hit at 70%), tighten prompt confidence guidance for that band directly. This is a maintenance task, not a new feature — revisit when the season has 3+ weeks of post-March audit data.
