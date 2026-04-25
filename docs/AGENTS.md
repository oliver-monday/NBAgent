# NBAgent — Agents Reference

---

## Agent Execution Order (daily)

```
ingest.yml (8 AM ET)
  └─ espn_daily_ingest.py    → nba_master.csv, standings_today.json
  └─ espn_player_ingest.py   → player_game_log.csv, player_dim.csv, team_game_log.csv
  └─ quant.py                → player_stats.json, team_defense_narratives.json

auditor.yml (chains off ingest)
  └─ auditor.py              → audit_log.json, updates picks.json + parlays.json

analyst.yml (chains off auditor)
  └─ rotowire_injuries_only.py → injuries_today.json + lineups_today.json (fresh refresh before picks)
  └─ quant.py                (re-run to ensure freshness)
  └─ playoff_matchup.py      → playoff_matchup.json (no-op if playoff_bracket.json absent)
  └─ odds_today.py --prefetch → odds_available.json (FanDuel market availability gate)
  └─ pre_game_reporter.py    → pre_game_news.json, context/context_flags.md
  └─ analyst.py              → picks.json (today's picks appended; OUT/DOUBTFUL pre-filtered)
  └─ odds_today.py           → picks.json (odds annotation + calibrated edge), odds_today.json
  └─ parlay.py               → parlays.json (today's parlays appended; OUT/DOUBTFUL excluded)
  └─ build_site.py           → site/index.html (deployed to GitHub Pages)

odds_pretip.yml (independent, every 30 min 3–7:30 PM PT)
  └─ odds_today.py --pretip  → picks.json (pre-tip odds update + CLV baseline), odds_pretip.json

injuries.yml (hourly, independent)
  └─ rotowire_injuries_only.py → injuries_today.json + lineups_today.json
  └─ lineup_watch.py           → picks.json (voided/lineup_risk updated in-place)
  └─ lineup_update.py          → picks.json (lineup_update sub-object on affected picks, conditional LLM call)
  └─ build_site.py             → site/index.html (redeployed with fresh injuries + amendments)
```

---

## quant.py — Deterministic Stats Engine

**Purpose:** Pre-computes all quantitative analytics from raw game logs so the Analyst and Parlay agents receive structured numbers rather than raw CSV rows. Pure Python — no LLM call.

**Key config constants:**
```python
PLAYER_WINDOW      = 20   # games for tier hit rates + trend base (raised from 10; backtest showed REB T8 +9.6pp, AST T6 +12pp, PTS T25 crosses floor)
TREND_SHORT_WINDOW = 5    # games for "recent" trend comparison
TREND_THRESHOLD    = 0.10 # >10% delta = up/down
MIN_GAMES          = 5    # skip players with fewer games
OPP_WINDOW         = 15   # games for opponent defensive context
CONFIDENCE_FLOOR   = 0.70 # minimum hit rate for a "best tier" pick
CORR_MIN_GAMES     = 8    # minimum shared games for teammate correlation
PACE_WINDOW        = 10   # games for game pace context
MIN_MATCHUP_GAMES  = 3    # minimum games per opp-rating bucket for matchup splits
H2H_MIN_GAMES      = 2    # minimum H2H games vs today's opponent to emit h2h_splits (else null)
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
- `tier_hit_rates` — hit rate at each tier across last 20 games, per stat
- `matchup_tier_hit_rates` — hit rate at each tier split by opponent defensive rating (soft/mid/tough) across full season history; only buckets with ≥3 games included
- `h2h_splits` — per-opponent tier hit rates from the full season game log specifically against today's opponent; `{opponent, games, PTS:{tier_str:{hits,n,rate}}, REB, AST, 3PM}` or `null` when `< H2H_MIN_GAMES` (2). DNP filter applied once to the whole H2H subset — `games` count is shared across all tiers and all stats (sample invariant). Annotation-only — surfaced by analyst `build_quant_context()` as a `H2H vs {OPP} ({N}g): ...` line after player stat lines, showing the highest qualifying tier (≥70% rate) per stat. No directive rules attached.
- `spread_split_hit_rates` — hit rate at each tier split by game competitiveness (competitive = spread_abs ≤ 6.5 vs blowout = spread_abs > 6.5); only buckets with ≥5 games included; limited by spread data coverage
- `best_tiers` — highest tier with ≥70% hit rate, per stat (null if none qualify)
- `trend` — up / stable / down (last 5 vs last 20 avg), per stat
- `home_away_splits` — best qualifying tier split by H/A
- `minutes_trend` — increasing / stable / decreasing
- `avg_minutes_last5` — float; average minutes over last 5 non-DNP games
- `minutes_floor` — `{floor_minutes, avg_minutes, n}`; computed floor based on recent minutes distribution; null if insufficient data
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
- `raw_avgs` — season averages per stat (PTS/REB/AST/3PM)
- `volatility` — per-stat volatility classification
- `positional_dvp` — positional defense vs. position rating per stat
- `ft_safety_margin` — `{label, margin, breakeven_fg_pct, season_fg_pct, n}`; H11 feature; FT contribution safety buffer for PTS props; null if insufficient FT data
- `shooting_regression` — `{fg_hot, fg_cold, fg_pct_l5, fg_pct_l20, n_l5, n_l20}`; P3 feature; recent FG% vs season baseline for regression context
- `playoff_profile` — `{playoff_games, seasons_with_data, deltas:{pts,reb,ast,tpm,fg_pct}, playoff_avgs, regular_avgs}` or `null`. Career playoff vs regular-season deltas from `data/playoff_career_log.csv` (2021–2025). Regular-season comparison restricted to the same seasons where the player also has playoff data (same-season apples-to-apples). FG% computed from aggregate FGM/FGA totals, not per-game mean. `null` when player has fewer than `PLAYOFF_MIN_GAMES` (5) career playoff games, player absent from backfill, or CSV missing. Surfaced by analyst `build_quant_context()` as a `PLAYOFF PROFILE` annotation line gated behind `PLAYOFFS_R1_DATE` (2026-04-18, inclusive). Annotation-only — no directive rules.
- `bounce_back` — per stat: `{post_miss_hit_rate, lift, iron_floor, n_misses, near_miss_rate, blowup_rate, typical_miss}`; Miss Anatomy fields (`near_miss_rate`, `blowup_rate`, `typical_miss`) are null if fewer than 5 misses; `near_miss_rate + blowup_rate == 1.0` when both non-null (they partition all misses)
- `profile_narrative` — string or null; live statistical portrait rendered for players with ≥10 non-DNP games and a qualifying PTS best tier; computed fresh daily by `build_player_profiles()`; injected into analyst prompt as `## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS`
- `key_teammate_absent` — per-stat absence baseline for the top-PPG whitelisted teammate; computed by `compute_teammate_absence_splits()` (added 2026-03-20); schema: `{teammate_name, n_games, raw_avgs, best_tier_hit_rate, tier}`; null when fewer than 3 historical without-teammate games; surfaced as `Without [X]` line in `build_quant_context()`; Pick stage uses as primary evaluation signal when that teammate is OUT/DOUBTFUL

**Additional quant output — `team_defense_narratives.json`:**
- Written by `build_team_defense_narratives()`, called as part of the daily quant run
- One auto-generated narrative line per team, computed from `team_game_log.csv` last 15 games
- Replaces the static `## TEAM DEFENSIVE PROFILES` section from `nba_season_context.md` in the analyst prompt; static section is no longer injected
- Format: `{ABBR} (last 15g): Allows {ppg:.1f} PPG (rank: Nth). [perimeter clause if data available]. [pace clause if noteworthy].`
- See DATA.md for full schema

**Correlation tags used:**
`feeder_target`, `volume_game`, `pace_beneficiary`, `positively_correlated`, `independent`, `insufficient_data`, `board_rivals`, `scoring_rivals`, `negatively_correlated`

**Whitelist filtering:** Quant filters to `(player_name.lower(), team_abbrev.upper())` tuples — this prevents traded players from appearing under their old team.

---

## espn_daily_ingest.py — Game + Standings Ingest

Fetches today's game slate (`nba_master.csv`) and, via `fetch_standings()`, live NBA standings. Standings are written to `data/standings_today.json` with per-team bucket assignments (`safe / contending / playin / bubble / eliminated`). Teams are sorted by win percentage descending (with total wins tiebreaker) before rank assignment — ESPN API returns entries in division-grouped order, not by record. See DATA.md for full schema.

---

## pre_game_reporter.py — Context Freshness Monitor

**Purpose:** Detects stale or conflicting information in `context/nba_season_context.md` before the analyst runs. Writes flags to `context/context_flags.md` and `pre_game_news.json`. Analyst picks up flags via the existing `⚠ CONTEXT FLAG` injection mechanism — no analyst.py changes required.

**Two-pass design:**

**Pass 1 — Deterministic staleness detection (Python only, no LLM):**
Runs first. Parses explicit dates from the `## SEASON FACTS` section of `nba_season_context.md` and applies three staleness rules:
- Return/injury notes older than 7 days → `⚠ CONTEXT FLAG: [player] — Return/injury note is N days old. Verify current status before picking this player.`
- Specific ISO-dated facts older than 5 days → `⚠ CONTEXT FLAG: [player] — Dated fact is N days old (from DATE). Verify still accurate.`
- Trade/role notes older than 60 days → `⚠ CONTEXT FLAG: [player] — Trade/role note is N days old. Game log now has sufficient data; note may be redundant.`

Deduplicates: if the same player token already appears in a Pass 2 flag, no staleness flag is emitted for that player. Uses stdlib `re` + `datetime` only — no third-party date libraries.

**Pass 2 — ESPN news cross-reference (Claude call):**
Existing behavior unchanged. Fetches ESPN headlines and cross-references against the full context file. Writes conflict flags for direct contradictions detected in recent news.

**Output written to:**
- `context/context_flags.md` — Pass 1 flags appended after Pass 2 flags; existing flags preserved
- `pre_game_news.json` — `"staleness_flags": [...]` key added (empty list `[]` if none)

**Does not modify:** `context/nba_season_context.md` — read only.

---

## analyst.py — Pick Generator (Three-Stage Scout → Pick → Review Pipeline)

**Architecture:** Three-stage LLM pipeline with single-call fallback. Scout (context-heavy, no rules) produces a 20–25 player shortlist. Pick (rules-heavy, filtered context) generates picks from the shortlist. Review (adversarial stress-test) flags structural vulnerabilities in each pick. Falls back to original single-call path if Scout fails or <5 shortlisted players match quant stats. Review failure is non-fatal — picks are already saved before Review runs.

**Scout model:** `claude-sonnet-4-6` (`claude-opus-4-6` when >30 active players post injury pre-filter)
**Pick model:** `claude-sonnet-4-6` (always Sonnet — shortlist ~20 players, never triggers Opus threshold)
**Review model:** `claude-sonnet-4-6` (always Sonnet)
**SCOUT_MAX_TOKENS:** `4096` (compact JSON shortlist output)
**MAX_TOKENS:** `32000` (Pick call — rules + filtered quant context)
**Review max_tokens:** `4096` (verdict JSON array)
**RECENT_GAME_WINDOW:** `10` games per player
**AUDIT_CONTEXT_ENTRIES:** `5` most recent entries

**Inputs consumed:**
- `nba_master.csv` — today's game slate
- `player_game_log.csv` — raw recent box scores (last 10 per player, filtered to today's whitelisted players)
- `player_stats.json` — quant output; provides pre-computed best tiers and matchup-specific hit rates injected as a structured prompt section
- `injuries_today.json` — filtered to today's teams only
- `audit_log.json` — last 5 entries (reinforcements, lessons, recommendations)
- `context/nba_season_context.md` — SEASON FACTS section only; static `## TEAM DEFENSIVE PROFILES` section no longer injected; handles missing file gracefully
- `context/context_flags.md` — staleness and conflict flags from pre_game_reporter; injected as `⚠ CONTEXT FLAG` prefixed lines
- `data/standings_today.json` — live standings snapshot; formatted by `format_playoff_picture()` and injected as `## PLAYOFF PICTURE` section
- `data/team_defense_narratives.json` — auto-generated team defense profiles; formatted by `format_team_defense_section()` and injected as `## TEAM DEFENSIVE PROFILES` section
- `data/lineups_today.json` — projected starting lineups from rotowire_injuries_only.py; formatted by `format_lineups_section()` and injected as `## PROJECTED LINEUPS` section; staleness-checked against today's date
- `data/odds_available.json` — pre-fetched FanDuel market availability; consumed via `load_available_markets()` + `format_available_markets()`; unconditional market gate: no FanDuel market → no pick (`no_market` skip); gate disabled when file missing/stale
- `playerprops/player_whitelist.csv` — (name, team) tuple filter

**Scout prompt sections (Stage 1 — `build_scout_prompt()`):**
1. Task framing + knowledge staleness awareness block
2. `## TODAY'S GAMES`
3. `## CURRENT INJURY REPORT`
4. `## PROJECTED LINEUPS`
5. `## PRE-GAME NEWS` (conditional)
6. `## SEASON CONTEXT`
7. `## PLAYOFF PICTURE`
8. `## WHITELISTED PLAYER RANKINGS`
9. `## TEAM DEFENSIVE PROFILES`
10. `## PLAYER PROFILES`
11. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS` (data only, no rules)
12. `## FANDUEL MARKET AVAILABILITY` (conditional — from `odds_available.json`; omitted when gate disabled)
13. `## OUTPUT FORMAT` — `{"slate_read": str, "shortlist": [...], "omitted": [...]}`

**Pick prompt sections (Stage 2 — `build_pick_prompt()`):**
1. Task framing + tier system intro
2. Hit definition + tier ceiling rules
3. `## SCOUT SHORTLIST` (from Scout output)
4. `## TODAY'S GAMES`
5. `## CURRENT INJURY REPORT`
6. All KEY RULES blocks (KEY FRAMEWORK, MATCHUP QUALITY, DvP, SELECTION, REST & FATIGUE, SEQUENTIAL GAME CONTEXT, SPREAD/BLOWOUT, VOLATILITY, HIGH CONFIDENCE GATE, INJURY EXCLUSION, TEAMMATE ABSENCE USAGE ABSORPTION)
7. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS` (filtered to shortlisted players only)
8. `## FANDUEL MARKET AVAILABILITY` (conditional — from `odds_available.json`; omitted when gate disabled)
9. `## AUDITOR FEEDBACK FROM PREVIOUS DAYS`
10. `## ROLLING PERFORMANCE SUMMARY`
11. `## ANALYSIS APPROACH` (modified to reference Scout shortlist)
12. `## OUTPUT FORMAT`

**Review prompt sections (Stage 3 — `build_review_prompt()`):**
1. Role framing — adversarial stress-tester
2. Structural vulnerability taxonomy (volatility, B2B suppression, blowout game script, minutes fragility, dense schedule fatigue, REB slump persistence, FT-dependent PTS)
3. Calibration guidance — expected 2–4 flags per typical 12-pick slate; over-flagging and under-flagging failure modes
4. Scope boundaries — what Review is NOT (no re-litigating tier selection, no training priors, no flagging already-priced risks)
5. `## HISTORICAL MISS PATTERNS` — extracted from `audit_summary` (miss classifications + recent lessons)
6. `## TODAY'S PICKS — VULNERABILITY CARDS` — per-pick cards from `build_review_context()` (schedule, volatility, opp_defense, spread, minutes floor, B2B hit rates, bounce_back, FT safety margin, abbreviated tier_walk)
7. `## OUTPUT FORMAT` — JSON array of `{player_name, team, prop_type, pick_value, verdict, vulnerability, confidence_in_flag}`

**Review inputs:** Pick output (list of picks), `player_stats.json` (filtered to shortlisted players), `audit_summary.json`
**Review output:** `data/picks_review_YYYY-MM-DD.json` in existing picks_review schema with `source: "auto"` field
**Review failure behavior:** Non-fatal — `call_review()` returns `None` on any failure; picks are already saved; day runs normally without a picks_review file
**Manual review priority:** `apply_review_flags()` skips writing if `picks_review_YYYY-MM-DD.json` already exists

**Fallback prompt sections (single-call — `build_prompt()`, unchanged):**
1. Task framing + knowledge staleness awareness block + tier system intro
2. Hit definition
3. Tier ceiling rules with backtest evidence
4. `## TODAY'S GAMES`
5. `## CURRENT INJURY REPORT`
5a. `## PROJECTED LINEUPS` (from `lineups_today.json`; fallback line if unavailable)
6. `## PRE-GAME NEWS` (conditional)
7. `## SEASON CONTEXT` — SEASON FACTS only (from `nba_season_context.md`)
8. `## PLAYOFF PICTURE` — auto-generated from `standings_today.json`
8b. `## PLAYOFF CONTEXT — POSTSEASON MODE` (conditional — on/after 2026-04-14; annotation-only behavioral framing)
8c. `## WHITELISTED PLAYER RANKINGS — SEASON vs L20` — top 15 per stat, season avg + L20 avg with ↑/↓/→ arrows; built from already-loaded game log; anchors elite scorer recognition
9. `## TEAM DEFENSIVE PROFILES` — auto-generated from `team_defense_narratives.json` (last 15g, updates daily)
9a. `## SERIES CONTEXT — PLAYOFFS` (conditional — from `playoff_matchup.json`; per-series performance + season H2H)
10. `## PLAYER RECENT GAME LOGS`
11. `## QUANT STATS — PRE-COMPUTED TIER ANALYSIS` — includes: KEY FRAMEWORK (5-level rule conflict priority order, PENALTY STACK LIMIT, TIER_WALK FORMAT, SANITY CHECK, CONFIDENCE THRESHOLD IS A FLOOR), KEY RULES — MATCHUP QUALITY, OPPONENT DEFENSE — POSITIONAL DvP, SELECTION RULES, KEY RULES — REST & FATIGUE (including RETURN FROM INJURY — SHORT SAMPLE INSTABILITY for `[SHORT_SAMPLE:Ng]` players), KEY RULES — SEQUENTIAL GAME CONTEXT, KEY RULES — SPREAD / BLOWOUT RISK, KEY RULES — VOLATILITY, KEY RULES — HIGH CONFIDENCE GATE, INJURY EXCLUSION
12. `## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS`
13. `## AUDITOR FEEDBACK FROM PREVIOUS DAYS`
14. `## ROLLING PERFORMANCE SUMMARY`
15. `## ANALYSIS APPROACH`
16. `## OUTPUT FORMAT`

**Prompt design principles:**
- Tier system explicitly taught: walk down from ceiling until ≥70% hit rate found
- Example reasoning pattern included in prompt
- Audit feedback framed as "use this to refine your selections"
- Output schema enforced strictly: `pick_value` must be a valid tier value
- Player profiles are live statistical portraits (evidence), not hardcoded flags or verdicts — analyst reasons from them
- Standings snapshot and team defense narratives are situational awareness only — no hard rules attached
- **Any rulebook change must be applied to BOTH `build_prompt()` (fallback) AND `build_pick_prompt()` (Pick stage) identically** — they contain mirror copies of the full rulebook

**Notable rule fixes (2026-03-20):**
- BLOWOUT_RISK Secondary Scorer Skip: direction was inverted in prompt text (said "underdog" but BLOWOUT_RISK=True means favored side). Corrected + `CRITICAL DIRECTION CHECK` paragraph added to both functions.
- 3PM extreme blowout hard skip (spread_abs ≥ 19): BLOWOUT_RISK=True AND spread_abs ≥ 19 → skip ALL 3PM regardless of trend direction; additive to existing trend=down rule; reuses `3pm_blowout_trend_down` skip_reason.

**Output schema (appended to `picks.json`):**
```json
{
  "date": "YYYY-MM-DD",
  "player_name": "string",
  "team": "abbrev",
  "opponent": "abbrev",
  "home_away": "H|A",
  "prop_type": "PTS|REB|AST|3PM",
  "pick_value": number,          // must be a valid tier value; must equal walked_tier
  "walked_tier": number,         // MANDATORY — final integer tier after all step-downs; verified by reconcile_pick_values()
  "direction": "OVER",
  "confidence_pct": 70–99,
  "hit_rate_display": "8/10",    // fraction at this tier from last 20 games
  "trend": "up|stable|down",
  "opp_defense_rating": "soft|mid|tough|unknown",
  "reasoning": "string",         // max 15 words, no restating hit rate
  "result": null,                // filled by auditor
  "actual_value": null           // filled by auditor
}
```

---

## parlay.py — Parlay Builder (Combinatorial Menu)

**Model:** — (pure Python, no LLM call, zero API cost)
**MAX_TOKENS:** —

**Architecture (rewritten 2026-04-22):** Replaced prior LLM-based selection (59.8% hit rate) with a deterministic combinatorial enumerator. Generates 5–10 ranked cards across three odds buckets. The system's `confidence_pct` product is used only for ranking within a bucket; `market_implied_prob` (FanDuel) determines the odds bucket placement and the card's advertised payout. This two-signal separation is intentional — the market prices the payout, and the system ranks which card in that bucket is most likely to hit.

**Odds buckets:**

| Bucket   | American Odds | Implied Prob   | Target Cards |
|----------|---------------|----------------|--------------|
| Value    | +100 to +200  | 33.3% – 50.0%  | 4            |
| Standard | +200 to +350  | 22.2% – 33.3%  | 3            |
| Reach    | +350 to +600  | 14.3% – 22.2%  | 2            |

Total: **5-10 cards** per day depending on leg pool size.

**Config constants:**
```python
ODDS_BUCKETS     = [("Value", 100, 200, 4), ("Standard", 200, 350, 3), ("Reach", 350, 600, 2)]
MAX_LEGS         = 8
MAX_COMBO_POOL   = 25   # cap legs before combo generation (performance)
MIN_LEGS         = 2
MIN_CONFIDENCE   = 70   # individual leg confidence floor
MAX_CANDIDATES   = 50   # early-termination per bucket
MAX_PLAYER_CARDS = 2    # max cards any one player appears in
```

**Logic flow:**
1. `load_todays_picks()` — filter picks to `date == TODAY_STR`, `confidence_pct ≥ 70`, `result is None`, `voided != True`, not OUT/DOUBTFUL in `injuries_today.json`, not `manual_skip` in `picks_review_YYYY-MM-DD.json`, **and `market_implied_prob is not None`** (no market odds → can't price the parlay). Carry `_human_verdict` on each pick.
2. Cap the pool at `MAX_COMBO_POOL` (25) by `confidence_pct` descending for performance.
3. Sort the pool by `market_implied_prob` descending (safest legs first) for the min-legs computation.
4. **Per bucket:** compute `max_prob` (upper probability bound from the bucket's lower American odds) and `min_prob` (lower bound from upper odds). Call `find_min_legs_for_bucket(sorted_pool, max_prob)` — walks the highest-probability legs multiplying cumulatively until combined prob drops below `max_prob`; this is the optimistic fewest-legs answer. Skip the bucket if it cannot be reached within `MAX_LEGS`.
5. Enumerate `combinations(pool, n)` from `max(min_legs, MIN_LEGS)` to `min(min_legs + 4, MAX_LEGS + 1)`. For each combo:
    - Skip duplicate player names (hard constraint).
    - Compute `combined_market_prob = ∏(market_implied_prob/100)`; skip if out of bucket range.
    - Confirm American odds fall within the bucket (`american_odds()` converts prob → odds).
    - Compute `combined_confidence = ∏(confidence_pct/100)` (ranking signal).
    - Compute `n_games` (distinct `_game_key(leg)` count) and `iron_floor_count`.
    - Tag `correlation`: `independent` if n_games == n_legs, `positive` if n_games == 1, `mixed` otherwise.
    - Compute `rank_score` (see formula below) and push to candidates.
    - **Early-terminate at `MAX_CANDIDATES` (50) per bucket.**
6. Sort candidates by `rank_score` descending, take top N for the bucket, label as `"{bucket} #{rank}"`.
7. `enforce_player_cap(cards, max_appearances=MAX_PLAYER_CARDS)` — across the full menu in rank order, drop any card that would push any player over 2 appearances. Prevents menu concentration on a small subset of players.
8. Re-label within bucket after the cap (so labels remain sequential 1..N), reassemble in bucket order (Value → Standard → Reach), and write via `save_parlays()`.

**Ranking formula:**
```python
rank_score = (
    combined_confidence * 1000  # primary: system confidence product
  + n_games            * 5      # bonus: game independence (less correlated failure)
  + iron_floor_count   * 3      # bonus: structural certainty
  - n_legs             * 1      # slight preference for fewer legs at same odds
)
```

**Odds math:**
```python
combined_market_prob = ∏(leg.market_implied_prob / 100)       # FanDuel odds product
combined_confidence  = ∏(leg.confidence_pct / 100)            # system confidence product
american_odds        = round(((1 / combined_market_prob) - 1) * 100)   # for prob < 0.5
```

**Exclusions / no-LLM design:**
- No `load_parlay_audit_feedback()` or `parlay_lessons` injection — no LLM to consume them. Auditor's own parlay analysis (in `build_audit_prompt()` PARLAY ANALYSIS TASK) still runs and still writes `parlay_lessons` for audit-trail purposes, but those lessons no longer flow back into pick selection.
- No `build_cannibalization_context()` / H33 scoring — cannibalization was an LLM reasoning prompt input. Game-independence (via `n_games` in rank_score) is the new structural guard; lowly-ranked same-game stacks lose to higher-ranked multi-game cards without needing the H33 dictionary.
- No `CORR_BONUS` / Pearson correlation scoring — was an LLM input, not used here. `correlation` field preserved on the output card purely for the frontend badge.
- No `edge_tier` preference rule — FADE legs are not pre-filtered. The market-priced bucket construction inherently favors legs FanDuel has priced near the ceiling; if a FADE leg happens to fit a bucket it competes on rank_score like any other.

**Output schema (appended as bundle to `parlays.json`):**
```json
// parlays.json structure: list of daily bundles (preserved byte-compatible)
[{
  "date": "YYYY-MM-DD",
  "parlays": [{
    "id": "parlay_YYYY-MM-DD_01",
    "label": "Value #1",                    // {bucket} #{rank} — auto-generated
    "bucket": "Value",                       // new: which odds tier
    "legs": [{
      "player_name":         "De'Aaron Fox",
      "prop_type":           "PTS",
      "pick_value":          10,
      "direction":           "OVER",
      "confidence_pct":      74,
      "market_implied_prob": 91.67,
      "iron_floor":          false
    }],
    "n_legs":               4,
    "combined_market_prob": 0.4512,          // ∏(market_implied_prob/100) — drives odds
    "combined_confidence":  0.2894,          // ∏(confidence_pct/100) — drives ranking
    "implied_odds":         "+145",
    "implied_odds_int":     145,
    "n_games":              3,               // distinct games represented
    "iron_floor_count":     2,
    "rank_score":           294.5,           // composite ranking score
    "correlation":          "independent",   // independent | mixed | positive (frontend badge)
    "result":               null,            // HIT|MISS|PARTIAL|NO_DATA|null — filled by auditor
    "legs_hit":             null,
    "legs_total":           4,
    "leg_results":          []               // filled by auditor
  }]
}]
```

Fields `date`, `id`, `result`, `legs_hit`, `legs_total` are added by `save_parlays()` at write time. **Parlay grading was removed on 2026-04-24** — the auditor no longer reads or grades `parlays.json`. New parlays write `result: null` and per-leg outcome fields stay null with no consumer. Historical entries with `result` set retain their values as dead-data.

---

## auditor.py — Results Grader + Feedback Writer

**Model:** `claude-sonnet-4-6`
**MAX_TOKENS:** `2048`
**Runs for:** yesterday's date

**Inputs consumed (in addition to picks.json):**
- `data/standings_today.json` — auditor receives the same playoff picture snapshot as the analyst, since it grades picks made with that information available
- `data/picks_review_YYYY-MM-DD.json` — optional human-produced daily review file; read by `load_picks_review()` to tag `human_verdict` + `trim_reasons` on graded picks; graceful no-op when absent

**Grading logic:**
- Matches picks to `player_game_log.csv` by `(player_name.lower(), team_abbrev)` for yesterday's date
- Pick result: `HIT` if actual > pick_value, `MISS` if actual ≤ pick_value, `NO_DATA` if player not found
- Skips run if zero gradeable picks (box scores not yet ingested)
- **Parlay grading removed 2026-04-24** — the parlay agent shifted to a deterministic combinatorial menu builder, so per-card grading is a category error. `data/parlays.json` is no longer read; new parlays carry `result: null` indefinitely.

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
    "root_cause": "string",
    "miss_classification": "selection_error|model_gap_signal|model_gap_rule|variance|injury_event|workflow_gap"
  }]
}
```

Note: pre-2026-04-24 audit entries also include a `parlay_results` block (`{total, hits, misses, partial, parlay_lessons, parlay_reinforcements}`) — left as dead-data per spec; new entries omit the key entirely. `audit_summary.json` similarly drops its `parlay_summary` aggregator on regeneration.

Also updates `picks.json` in-place with graded results. Calls `load_picks_review(YESTERDAY_STR)` + `apply_human_verdicts()` to tag `human_verdict` ("keep"/"trim"/"manual_skip"/null) and `trim_reasons` (list/[]) on each graded pick from the daily review file (no-op when file absent). `save_audit_summary()` produces a `human_flag_precision` block in `audit_summary.json` — reads all picks from `picks.json`, groups by `human_verdict`, computes `{hits, misses, total, hit_rate_pct}` per verdict type over full season history.

**injury_event auto-void (added 2026-04-22):** Between `call_auditor()` and `save_audit()`, `promote_injury_event_voids(graded_picks, audit_entry)` scans `audit_entry["miss_details"]` for `miss_classification == "injury_event"` entries and promotes the matching graded picks to `voided=True, result=null, void_reason="injury_exit_mid_game"`. This catches mid-game injury exits where `actual_value > 0` (so the existing late-DNP void at line ~554 doesn't fire). After promotion, the daily audit entry is recomputed: `total_picks`, `voided_picks`, `hits`, `misses`, `hit_rate_pct`, `prop_type_breakdown`, and `confidence_calibration` band totals are all updated so the saved entry is internally consistent with the voided picks. The miss still appears in `miss_details` for audit-trail purposes — the LLM's classification is preserved. Frontend `build_site.py` filters on `result in ("HIT","MISS")`, so voided picks are automatically excluded from Overall, Yesterday, and Playoffs stat cards. A companion one-time `_retroactive_injury_void_patch()` runs at the start of `main()` to idempotently patch the two Wemby 2026-04-21 picks (concussion exit) to voided status, recomputing audit_log[2026-04-21] accordingly.

---

## season_context_updater.py — Playoff Series Diary Automation

**Model:** `claude-sonnet-4-6`
**MAX_TOKENS:** `4096`
**Runs:** in `auditor.yml` directly after `auditor.py`, before the commit step

**Purpose:** Automates daily playoff-diary updates to `context/nba_season_context.md` during R1 and beyond. The season context document is read by both the Analyst and Auditor on every run — its series diary entries, injury bullets, and suppressor notes drive contextual reasoning. This agent closes the last-mile automation gap: all the required data (scores, stat lines, post-game narratives, current injuries) already flows through the pipeline by the time auditor.py completes; this agent assembles them into new diary entries via a single Claude call.

**Date gate:** No-op before `PLAYOFFS_R1_DATE = "2026-04-18"`. Safe to leave in the workflow year-round — exits cleanly with a log message during regular season and off-season.

**Inputs consumed:**
- `data/nba_master.csv` — yesterday's completed games (postseason only, `season_type == 3`); key fields: `home_team_abbrev`, `away_team_abbrev`, `home_score`, `away_score`, `home_spread`, `game_date`, `season_type`
- `data/player_game_log.csv` — per-player box scores; filters to whitelisted players + any non-whitelisted 25+ pt performer on either team
- `data/post_game_news.json` — narratives written by `post_game_reporter.py` earlier in the same workflow run
- `data/injuries_today.json` — current injury statuses, keyed by team abbrev
- `context/nba_season_context.md` — read as ground-truth context AND patched in place

**Output written to:** `context/nba_season_context.md` (in-place patch)

**Processing flow:**
1. Date-gate check (`YESTERDAY_STR >= PLAYOFFS_R1_DATE`)
2. Read season context; early-exit if missing or empty
3. `load_yesterday_playoff_games()` — completed postseason games only
4. `find_series_sections()` — regex over `##### (N) TEAM vs (N) TEAM` headers; returns per-section dicts with `header_start`, `section_end`, `last_game_entry_end` (= insertion point right after the last existing `**Game N**` paragraph), and `game_count`
5. `match_game_to_series()` — symmetric team-pair match; sets `game_number = existing_count + 1`
6. `load_player_stat_lines()` — per-game stats sorted by pts desc
7. Build prompt with the FULL season context inside `<season_context>` tags (authoritative, combats stale training priors), game blocks, post-game narratives for mapped players, and injury bullets for teams that played yesterday
8. Single Claude call; response parsed with four fallback strategies (raw JSON → markdown-fence strip → `json_repair` → brace extraction)
9. `apply_diary_entries()` — inserts each new entry at its section's `last_game_entry_end`; applies bottom-up to preserve character offsets
10. `apply_injury_updates()` — for each update, finds the existing bullet by substring match on `search_line`, replaces the entire bullet with `full_replacement`; graceful skip + warning if not found
11. `update_timestamp()` — replaces `*Last updated: YYYY-MM-DD.*` with today's date
12. Safety net: refuses to write if updated content is shorter than the original

**Output schema (strict JSON from Claude):**
```json
{
  "diary_entries": [
    {
      "team1": "ATL",
      "team2": "NYK",
      "game_number": 2,
      "entry_text": "**Game 2 (Apr 20) — ATL 107, NYK 106 | Series tied 1-1**\n..."
    }
  ],
  "injury_updates": [
    {
      "search_line": "**Anthony Edwards (MIN)** — Right knee",
      "full_replacement": "- **Anthony Edwards (MIN)** — Right knee..."
    }
  ]
}
```

**Failure modes:**
- No playoff games yesterday → graceful exit with log message
- No series sections found in document → graceful exit (handles pre-playoff state or empty doc)
- LLM response JSON unparseable → error log, does NOT write the file
- Injury `search_line` not found → warning, skip that update, continue
- Updated content shorter than original → error log, does NOT write the file

---

## lineup_update.py — Afternoon Lineup Amendment Agent

**Model:** `claude-sonnet-4-6`
**MAX_TOKENS:** `2048`
**Runs:** hourly after `lineup_watch.py` in `injuries.yml`

**Purpose:** Diffs current lineup/injury state against the morning snapshot written by `analyst.py`
at pick time. When meaningful changes are detected (a morning starter is now OUT/DOUBTFUL, or has
been silently dropped from projected starters), calls Claude to assess the downstream impact on
today's open picks. Writes a `lineup_update` sub-object to affected picks — leaving all original
pick fields intact.

**No-op conditions (skips LLM call):**
- `lineups_today.json` missing or has no `snapshot_at_analyst_run` key
- No starter-level changes detected vs. morning snapshot
- All affected picks are past the tip-off cutoff (CUTOFF_MINUTES = 20)
- No open, non-voided today picks match the changed teams

**Amendment gates (deterministic, in `apply_amendments()`):**
- **Gate 1 — Sub-70% auto-void:** `direction=="down"` + `revised_confidence_pct < 70` → pick immediately voided; `lineup_update` sub-object preserved for audit trail
- **Gate 2 — B2B <5g upside block:** `direction=="up"` + `player_stats[player].b2b_hit_rates[prop]` is null + `on_back_to_back` → override to `direction="unchanged"`, original confidence preserved

**Change types detected:**
- `new_absence` — player was in morning starters, now OUT/DOUBTFUL in injury report
- `starter_replaced` — player was in morning starters, no longer listed, not injured (quiet scratch)

**Affected pick scope:** a pick is affected when its `team` OR `opponent` appears in the change list —
covering both usage-boost picks (teammate is out → more usage) and matchup picks (key defender is out).

**`lineup_update` sub-object written to each amended pick:**
```json
{
  "triggered_by":          ["string, detail of each relevant change"],
  "updated_at":            "ISO timestamp",
  "direction":             "up" | "down" | "unchanged",
  "revised_confidence_pct": number,
  "revised_reasoning":     "string, max 20 words"
}
```

Sub-object is **overwritten** on each hourly run — latest Claude assessment always wins.
`direction=unchanged` is still written (audit evidence that the change was evaluated).
Original `confidence_pct`, `reasoning`, `pick_value`, `tier_walk` fields are **never modified**.

**Frontend display:** pick cards show `↑ Updated HH:MM` (green) or `↓ Updated HH:MM` (amber)
badge beneath reasoning. Clicking expands a detail panel showing triggered_by, revised reasoning
(with revised confidence %), and the original morning reasoning.

**Opportunity suggestion schema (written/appended to `data/opportunity_flags.json`):**
```json
{
  "date":              "YYYY-MM-DD",
  "generated_at":      "ISO timestamp",
  "triggered_by":      "Absent Player Name",
  "triggered_by_team": "abbrev",
  "side":              "teammate|opponent",
  "player_name":       "string",
  "team":              "abbrev",
  "card_type":         "new_pick|upgrade|mixed",
  "qualifying_tiers":  {
    "PTS": {"tier": 20, "hit_rate_pct": 78, "trend": "up", "volatility": "consistent",
            "without_player_hit_rate_pct": 82, "without_player_n": 6}
  },
  "upgrade_tiers": {
    "AST": {"tier": 8, "hit_rate_pct": 75, "trend": "stable", "volatility": "moderate",
            "morning_tier": 6, "morning_confidence_pct": 78}
  },
  "spread_delta":    "string|null",
  "morning_context": "string|null",
  "reasoning":       "string"
}
```

One card per player per triggering absence (deduped by `(date, player_name_lower, triggered_by_lower)`). `qualifying_tiers`: props ≥70% hit rate where player has no morning pick. `upgrade_tiers`: props where quant best tier > morning pick tier. Both dicts optional; player skipped when both empty. `without_player_*` fields optional (teammate side only, requires ≥3 historical without-player games).

---

## injury_profiles.py — Injury & Availability Profiles

**Purpose:** Quantitative data provider for per-player availability and injury metrics. Pure Python — no LLM call, no automated risk classification.

**Runs:** Daily in `analyst.yml` after `playoff_matchup.py`, before odds prefetch.

**Inputs:** `player_game_log.csv`, `nba_master.csv`, `player_whitelist.csv`, `injuries_today.json`

**Output:** `data/injury_profiles.json` — one entry per active whitelisted player with:
- `current_status`: OUT / DOUBTFUL / QUESTIONABLE / ACTIVE (from injury report overlay)
- `availability`: games_played, team_games, pct, total_absences, dnp_count
- `absence_profile`: longest_streak, streak_count, absences_last_14d/30d, days_since_last_game
- `minutes_profile`: season_avg, l5_avg, l20_avg, trend (stable/declining/increasing)
- `b2b_profile`: b2b_total, b2b_played, b2b_sat, sit_rate_pct
- `current_injury`: status + details from injuries_today.json (null if not listed)

**Design:** No automated risk classification — the curated `### PLAYOFF INJURY LANDSCAPE` section in `context/nba_season_context.md` provides the qualitative intelligence layer. This agent provides the quantitative data foundation only.

**Downstream consumer:** The PLAYOFF INJURY LANDSCAPE section in season context (manually curated by Oliver) references this data.

---

## build_site.py — Frontend Generator

Pure Python, no JS dependencies in output. Reads all data files, writes `site/index.html`.

**Five tabs:**
1. **Today's Picks** — injury report dropdown, pick cards grouped by game (collapsible), sorted by prop type then confidence. Each card: player, micro-stat pills (trend + opp defense), reasoning, hit rate bar, confidence. Voided picks show VOIDED badge. DOUBTFUL/QUESTIONABLE picks show risk pills. Lineup Update shows ↑/↓ badge with expandable amendment detail. Review badges: ⚠ Caution (amber) for `trim` verdict, ⚠ Flagged (red) for `manual_skip` verdict — shown below status badge when picks_review file present; includes inline trim_reasons. **Best Bets section** below Top Picks: shows POSITIVE and STRONG edge picks ranked by calibrated edge descending; teal border (POSITIVE) or green border (STRONG); includes Odds + Sizing drawer; hidden when no qualifying picks.
2. **Parlays** — historical stats banner (hidden until data exists), parlay cards with leg rows showing player/team, stat value + colored prop badge, confidence, result icon post-grading. Correlation badge + rationale on each card. H33 cannibalization badges (⊖/⊕) inline between consecutive same-team same-stat legs. Custom Parlay Builder below system parlays: click-to-add picks, live odds/payout/edge, H33+correlation warnings, copy to clipboard. Opportunity flags shown as per-player cards with `qualifying_tiers` (amber "OPPORTUNITY" rows) and `upgrade_tiers` (blue "UPGRADE" rows showing T{morning}→T{new}); `card_type` label ("OPPORTUNITY"/"UPGRADE"/"MIXED"); opponent-side cards show "(opp)" suffix.
3. **Results** — overall hit rate banner, named stat cards (Overall/Yesterday/Props/Top Picks/Daily Hit Rate), 30-day hit rate trend chart (vanilla canvas), collapsible full pick history drawer.
4. **Audit Log** — latest auditor entry: hit rate stats, what worked, what to avoid, analyst instructions. Skip validation table.
5. **Research** — player game log explorer; filter by player, stat, home/away, rest days, spread bucket, game result, opponent; renders tier hit rate table with bar charts, distribution stats, and full game log. Static — no LLM calls, fully client-side.

**Triggered by:** end of `analyst.yml` AND end of each `injuries.yml` run (so injury data stays fresh on the live site without needing a full analyst run).
