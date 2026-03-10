# NBAgent — Roadmap & Issue Log

---

## Open Items

### Operational
- **Whitelist maintenance** — review and update `active` flags as the season evolves, especially post-trade-deadline role changes
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **`context/nba_season_context.md` — manual restructure pending** — restructure SEASON FACTS into three decay tiers (PERMANENT / SEMI-STABLE / VOLATILE) as designed in Season Context Improvement 3. Improvements 0–2 are live as of March 8, 2026. This is a manual file edit only — no code required.

### Untested Hypotheses (backtest designs documented in `docs/BACKTESTS.md`)
- **H8 — Positional DvP Validity** — Does the positional defense rating predict PTS/AST hit rates more accurately than the team-level opp_defense rating? Requires ~30 days of live positional DvP data accumulating in `player_stats.json`. Run approximately early April 2026. If positional DvP shows no meaningful lift over team-level, consider reverting to team-level to simplify the prompt. Design documented in `docs/BACKTESTS.md`.
- **H9 — Player × Opponent H2H Splits** — Does a player's historical hit rate against today's specific opponent predict next-game performance better than the population-level opp_defense rating? Requires near-complete season sample (~mid-April 2026). See Active Queue entry M1 for implementation design.

### Closed Hypotheses
- **H6 — Post-Blowout Bounce-Back** ❌ NOISE — post-blowout lift 0.955–0.988 across all stats; lift variance ≤ 0.08. Closed March 7, 2026. Full results in `docs/BACKTESTS.md`.
- **H7 — Opponent Schedule Fatigue** ❌ NOISE — opponent B2B lift 0.977–1.025; dense bucket had 0 instances in full season. Closed March 7, 2026. Full results in `docs/BACKTESTS.md`.
- **H11 — FG% Safety Margin** ✅ IMPLEMENTED — structural explainability feature shipped without backtest. `ft_safety_margin` live in `quant.py` + `analyst.py`. Validates naturally via audit log accumulation.
- **H13 — Shot Volume** ❌ NOISE / CONFOUNDED — median FGA sanity check failed; results not interpretable. Closed March 2026. Full results in `docs/BACKTESTS.md`.

### Technical Debt
- **Prompt caching** — system prompt and player context in `analyst.py` are strong candidates for Anthropic's prompt caching feature. Will meaningfully reduce cost once daily volume grows.
- **`quant.py` runs twice** — once in `ingest.yml` and once in `analyst.yml`. This is intentional (ensures freshness) but adds ~10s to runtime. Low priority.
- **`data/audit_summary.json` not yet seeded** — `save_audit_summary()` only runs going forward. Historical `audit_log.json` entries will be aggregated incrementally — the summary will be meaningfully populated after 3+ audit runs. `load_audit_summary()` returns empty string until then. No manual action needed.
- **`prop_type_breakdown` / `confidence_calibration` absent from pre-March audit entries** — older entries in `audit_log.json` won't have these fields; `save_audit_summary()` handles missing fields with `.get()` defaults. Per-prop and calibration totals in `audit_summary.json` will undercount until all historical entries are replaced by new runs. Acceptable accumulation behavior.

### Frontend
- **Parlays tab historical stats banner** — hidden until graded parlay history exists. Once data accumulates (1–2 weeks), evaluate whether to add a rolling chart similar to the picks trend chart.
- **Mobile layout** — current pick cards are readable but not optimized for small screens. Low priority until real users request it.

---

## Active Queue — In Priority Order

### Season Context Improvement 3 — Restructure SEASON FACTS into Decay Tiers
**Status: MANUAL — no Code prompt needed**
**Priority: LOW — do after Improvements 0–2 land**

**What:** Edit `context/nba_season_context.md` manually to add three explicit decay tiers to the SEASON FACTS section header: PERMANENT, SEMI-STABLE, VOLATILE. VOLATILE entries are explicitly dated and get the most scrutiny from the staleness detection added in Improvement 2. When a volatile fact stabilizes (e.g., Tatum's minutes settle after 10+ games), promote to SEMI-STABLE or remove entirely.

---

### P5 — Afternoon Lineup Update Agent (`agents/lineup_update.py`)
**Status: ✅ IMPLEMENTED (March 10, 2026)**

Implemented as snapshot-based diff: `analyst.py` writes `snapshot_at_analyst_run` into
`lineups_today.json` at pick time. `lineup_update.py` runs hourly, diffs current
lineup/injury state against that snapshot, and calls Claude only when changes are detected.

**Output schema (actual implementation):**
```json
{
  "lineup_update": {
    "triggered_by": ["string"],
    "updated_at": "ISO timestamp",
    "direction": "up | down | unchanged",
    "revised_confidence_pct": number,
    "revised_reasoning": "string, max 20 words"
  }
}
```

Morning pick fields (`confidence_pct`, `reasoning`, `pick_value`) are **never modified**.
Sub-object overwritten on each hourly run — latest assessment wins. `direction=unchanged`
still written as audit evidence.

**Audit integration:** NOT yet implemented. Picks amended by lineup_update are graded identically
to morning picks — no distinction in the audit log. Revisit after ~20 days of amendment data.
The key evaluation question: do re-reasoned-DOWN picks miss more than un-amended picks at the
same tier? If yes, keep the feature. If no improvement, simplify to log-only.

**Frontend:** `↑ Updated HH:MM` (green) / `↓ Updated HH:MM` (amber) badge on pick cards and
Top Picks cards. Click expands: triggered_by, revised conf+reasoning, original morning reasoning.

**Files:** `agents/lineup_update.py` (new), `analyst.py` (write_analyst_snapshot),
`ingest/rotowire_injuries_only.py` (lineups_today.json), `injuries.yml`, `build_site.py`, `AGENTS.md`.

---

### Matchup Signals Queue

Design philosophy: the Analyst already has a solid quantitative matchup foundation (positional DvP, vs_soft/vs_tough splits, game pace, spread context). The following proposals address gaps where rolling averages give a misleading picture because something material has changed that the numbers alone cannot capture.

#### M1 — Player × Opponent H2H Splits
**Priority: MEDIUM — backtest-ready mid-April 2026**
**Prerequisite: sufficient per-player-opponent sample sizes (~8+ games)**

**What:** For each player today, compute their hit rate at their best tier specifically against today's opponent (full season history). Surface as `h2h_hit_rate` and `h2h_n` alongside the existing `vs_soft`/`vs_tough` population-level rates.

**Why:** The system knows "Brunson hits PTS T25 80% of the time vs soft defenses." It does not know "Brunson hits PTS T25 in 7 of his last 8 games specifically against BOS." Those are different signals — a player may systematically over- or under-perform against a specific defensive scheme that the population-level soft/mid/tough rating smooths over.

**Design:**
- `quant.py` — `compute_h2h_splits(player_log, stat)`: per player × opponent, compute tier hit rate at best qualifying tier. Minimum n=5 to surface; null otherwise. New `h2h_splits` key in `player_stats.json`.
- `analyst.py` — `h2h=XX%(Ng)` appended to stat line when n≥5 and today's opponent matches. Prompt rule: weight h2h rate over vs_soft/vs_tough when n≥8; supporting context only when n=5–7.

**Validation gate:** After 30+ days of flagged h2h picks, run backtest H9. **Where:** `agents/quant.py`, `agents/analyst.py` only.

---

#### M2 — Defensive Recency Split
**Priority: LOW-MEDIUM — cheap quant addition, no backtest required to ship**

**What:** A recency flag on opponent defense: compare opponent's allowed average over last 5 games vs. last 15 games (the existing `opp_defense` window). Flag when L5 diverges materially from L15 — indicating the defense has changed recently (injury to key defender, scheme change, fatigue stretch).

**Design:**
- `quant.py` — extend `build_opp_defense()` or add `compute_opp_defense_recency()`. Flag `def_trending_soft` when L5 allowed avg ≥8% above L15; `def_trending_tough` when ≥8% below. Minimum 3 games in L5 window. New `def_recency` field per player in `player_stats.json`.
- `analyst.py` — `DEF↑` (trending soft) or `DEF↓` (trending tough) per-player header annotation. Prompt rule: mild modifier, same weight as pace_tag — not tier-changing until backtested.

**Validation gate:** After 30+ flagged instances, evaluate whether `def_trending_soft` picks outperform baseline. **Where:** `agents/quant.py`, `agents/analyst.py` only.

---

### Watch-and-Accumulate Items (March 9, 2026)

Items with directional signal but insufficient sample to act. Revisit after 2–3 more weeks of audit data.

#### W1 — 76-80% Confidence Band Underconfidence
**Status: WATCH — do not act until ~30 more picks in band**

5-day calibration shows 76-80% band at 89.1% actual vs 78.0% expected (+11.1 pts, 55 picks). This is the largest sustained delta across all bands and is no longer noise. Hypothesis: VOLATILE (-5%) and BLOWOUT_RISK (-5%) penalties are stacking and pushing picks that would otherwise state ~82% down into the 76-80% range, where they then dramatically outperform. Action if confirmed: audit whether these penalties are additive caps or independent adjustments, and tighten stacking behavior. **Do not change penalty mechanics until calibration band has 80+ picks.**

#### W2 — REB Opponent-Adjusted Floor
**Status: WATCH — needs 3–4 more model_gap REB misses to justify quant work**

REB has the worst miss profile of any prop type: 4 model_gaps out of 10 total misses, all sharing the same root cause — raw historical L10 floor overstates expected output when the opponent's defensive scheme specifically suppresses rebounding (MIA zone, HOU switching). The existing REB DvP exclusion from positional DvP was correct (rebounding is less positional), but the absence of any opponent-adjusted floor gate is showing up consistently. Conceptual fix: a modifier in the analyst prompt that discounts the qualifying L10 floor when opp_defense is tough for REB — not a hard block, but a downward adjustment to the clearance threshold. **Do not write quant or prompt code until pattern holds another week.**

#### W3 — CLE Switching Scheme / DvP Aggregate Mismatch
**Status: WATCH — single-team signal, needs more instances before generalizing**

Derrick White's two model_gap misses (PTS + 3PM, March 8) expose a gap: CLE's aggregate 3PM DvP rates as "soft" in the team-level data, but their switching scheme neutralizes off-ball guard perimeter looks in a way the aggregate number cannot capture. The fix is architectural (team-level DvP cannot distinguish switching vs. drop coverage) and cannot be resolved with current data. Near-term action: add a CLE scheme note to `context/nba_season_context.md` (or its renamed successor) flagging this mismatch so the analyst has scheme context that the DvP rating doesn't convey. **Generalize to a broader "switching-scheme DvP discount" rule only if similar misses appear for other known switching teams (MIN, BOS, MIL).**

---

### Pending Backtests

| ID | Name | Status | Mode | ETA |
|----|------|--------|------|-----|
| H8 | Positional DvP Validity | Queued — data accumulating | `--mode positional-dvp` | ~early April 2026 |
| H9 | Player × Opponent H2H | Queued — data accumulating | `--mode h2h-splits` | ~mid-April 2026 |
| Miss Anatomy | Near-miss vs. blowup next-game | Queued — quant fields live | `--mode miss-anatomy` | ~late March 2026 |

**Miss Anatomy — analyst wiring deferred:** `near_miss_rate` and `blowup_rate` fields are live in `player_stats.json` and feeding Player Profiles. The directive prompt rule (confidence modifier or tier-drop on high `blowup_rate`) is explicitly NOT shipped until the backtest validates the signal. See `miss_anatomy_quant_only.md`.

---

## Implementation Notes

- **Season Context Improvements 0–2** — ✅ All implemented March 8, 2026. Standings snapshot, auto-generated team defense narratives, and staleness detection are live in production. Improvement 3 (manual SEASON FACTS restructure) is the only remaining item.
- **Miss Anatomy** — quant fields live and feeding Player Profiles conditional rendering. Analyst wiring deferred until backtest (~late March). See `miss_anatomy_quant_only.md` for deferred scope rationale.
- **Minutes Floor** — structural feature, ships without backtest. Validates naturally via audit log accumulation within 2–3 weeks.
- **P4 (Tier-Walk)** — ✅ IMPLEMENTED (March 6, 2026). `tier_walk_flag` in `miss_details` accumulates going forward — expect meaningful patterns after 20+ audit days.
- **P3 (Shooting Regression)** — ✅ FULLY IMPLEMENTED (March 8, 2026). Signal threshold (±8%) is an untested prior — validate via audit accumulation after 30+ days of flagged picks. HOT misses should cluster in `model_gap` to confirm mechanism; if they cluster in `variance`, the penalty is overcorrecting.
- **P5 (Afternoon Lineup Update)** — ✅ IMPLEMENTED (March 10, 2026). Snapshot-based diff (not prior-cycle diff). `analyst.py` writes `snapshot_at_analyst_run` into `lineups_today.json`; `lineup_update.py` diffs hourly. Audit integration NOT yet done — picks amended by lineup_update are graded identically to morning picks. Evaluate after ~20 days of amendment data: do revised-DOWN picks miss more? If no lift, simplify to log-only.
- **#1 (Teammate Absence Delta)** — highest long-run alpha; revisit at season start when full-year DNP data exists.
- **Confidence calibration tracking** — `audit_summary.json` accumulates per-band hit rates (70–75 / 76–80 / 81–85 / 86+). After 20+ audit days, compare actual hit rates to stated confidence bands. If a band systematically underperforms, tighten prompt guidance for that band directly.
- **Positional DvP backtest (H8)** — data accumulating in `player_stats.json` since March 2026. Run early April. If not meaningfully stronger than team-level, consider reverting to simplify the prompt.
- **Rotowire projected_minutes/onoff_usage (March 10, 2026)** — scraper wired; `lineups_today.json` carries the data; analyst wiring live (`proj_min`, `[USG_SPIKE]`, `⚠ OPP` annotations). No directive prompt rules yet — treat as contextual signals until audit data accumulates. No backtest required for the annotation layer; validate via analyst pick quality over time.
- **Knowledge staleness awareness (March 10, 2026)** — epistemic calibration block inserted in `build_prompt()`. No code-level validation possible — validate indirectly by watching for fewer "stale training knowledge" root causes in audit miss classifications over time.
- **Analyst — full-coverage prop enumeration + Opus hybrid (March 10, 2026)** — `## ANALYSIS APPROACH` block rewritten to require explicit evaluation of all four prop types per player before moving on. `LARGE_SLATE_THRESHOLD = 30` constant added; `call_analyst()` accepts `model` param; `main()` conditionally upgrades to `claude-opus-4-6` when active player count (post injury pre-filter) exceeds threshold. Addresses coverage collapse observed on 48-player slate where Analyst silently skipped prop types.
- **`lineup_update.py` — direction guide expansion + Rotowire context injection (March 10, 2026)** — `build_rotowire_context(lineups, changed_teams)` helper added; reads `projected_minutes` and `onoff_usage` from `lineups_today.json` for changed teams and formats a plain-text block for Claude. `call_lineup_update()` signature updated to accept optional `rotowire_context` param; system prompt replaced with prop-type-aware direction guide covering PTS/REB/AST/3PM each with separate up/down/unchanged logic; calibration instruction added for Rotowire usage magnitude → confidence adjustment. `rotowire_section` injected into Claude user message when context non-empty (graceful no-op on unauthenticated runs). `main()` computes `changed_teams` set and passes Rotowire context to `call_lineup_update()`.
- **Analyst — blowout spread cap refinements (March 10, 2026)** — Two bullets added to KEY RULES — SPREAD / BLOWOUT RISK in `build_prompt()`. (1) BLOWOUT-RESILIENT OFFSET CAP: `[iron_floor]` or "blowout-resilient" signals do not zero out the BLOWOUT_RISK -10% PTS penalty — they offset it by 5pp (net -5%), not eliminate it entirely. (2) LARGE SPREAD PTS CAP: when BLOWOUT_RISK=True AND spread_abs ≥ 12, PTS confidence capped at 74% regardless of hit rate, iron_floor, or resilience signals. Motivated by March 9 audit over-confidence on large-spread favored-team PTS picks.
- **Analyst — INJURY STATUS ON SHOOTING PROPS rule (March 10, 2026)** — New KEY RULES — INJURY STATUS ON SHOOTING PROPS block added to `build_prompt()`. When a player carries QUESTIONABLE status involving a soft-tissue joint concern (ankle, foot, knee, hip, groin), apply -5% confidence to all shooting-dependent props (3PM and PTS). Rationale: compromised lower-body movement shifts attempts away from the perimeter, reducing 3PM floors directly and PTS floors via shooting efficiency. Does not apply to PROBABLE/unlisted (OUT/DOUBTFUL already pre-filtered). Non-contact injury types (illness, rest) exempt.
- **Analyst — 3PM hard skip: trend=down AND tough DvP (March 10, 2026)** — Second 3PM hard skip rule added to KEY RULES — SEQUENTIAL GAME CONTEXT in `build_prompt()`. If 3PM trend is "down" AND opponent DvP 3PM rating is "tough", skip all 3PM picks including T1 — do not apply step-down rule. Rationale: after a trend=down step-down lands at T1, there is no margin left; a single cold night produces zero. Tough perimeter DvP compounds the floor compression. Both March 9 audit 3PM misses (Mitchell T1 8/10, Murray T1 9/10) met this exact profile. Note: 3PM DvP is otherwise noise — this is the sole exception, requiring BOTH conditions simultaneously.
- **Auditor — amendment context injection + model_gap sub-classification (March 10, 2026)** — STEP 6 added to PICK ANALYSIS TASK: Auditor reads `lineup_update` sub-object on pick objects and notes amendment direction vs. outcome in `root_cause` (direction=down + miss → "Amendment correctly flagged…"; direction=up + miss → "Amendment flagged upside but pick missed"; etc.). Does not change `miss_classification` — amendment notes are contextual feature-validation evidence only. `model_gap` split into `model_gap_signal` (system lacks the signal entirely — no quant field or rule exists) and `model_gap_rule` (signal existed in quant data/context but analyst rule didn't handle the combination). `save_audit_summary()` valid set updated to include both new sub-classifications; legacy `model_gap` removed. Two prose references to `model_gap` in NO_DATA block and STEP 2 inspection-order text also updated.

---

## Improvement Proposals

### Completed

**#2 — Opponent-Specific Tier Hit Rates ✅ IMPLEMENTED**
- `quant.py` — `compute_matchup_tier_hit_rates()`. Full season history split by opponent defensive rating (soft/mid/tough). Stored as `matchup_tier_hit_rates` in `player_stats.json`.
- `analyst.py` — `build_quant_context()` injects per-player `vs_soft`/`vs_tough` rates into prompt.

**P2 — Rolling Volatility Score ✅ IMPLEMENTED**
- `quant.py` — `compute_volatility()`. 20-game window; σ < 0.3 = consistent, 0.3–0.4 = moderate, > 0.4 = volatile. `"volatility"` key in `player_stats.json`.
- `analyst.py` — `[VOLATILE]` / `[consistent]` tags on stat lines; KEY RULES — VOLATILITY block.

**P1 — Positional DvP ✅ IMPLEMENTED**
- `player_whitelist.csv` — `position` column added for all active players.
- `quant.py` — `load_whitelist_positions()` + `compute_positional_dvp()`. `"positional_dvp"` key in `player_stats.json`.
- `analyst.py` — `DvP [POS]` line per player; positional prompt instructions with REB/3PM exclusions.

**P3 — Shooting Efficiency Regression ✅ IMPLEMENTED (March 7–8, 2026)**
- `espn_player_ingest.py` — `fgm/fga/fg3m/fg3a` collected on all new daily rows. `player_game_log.csv` backfilled to 7,584 rows (22 columns).
- `quant.py` — `compute_shooting_regression()`. L5 vs L20 FG%/3P% delta; ±8% threshold; `hot/cold/neutral` flag. `"shooting_regression"` key in `player_stats.json`.
- `analyst.py` — `[FG_HOT:+X%]` / `[FG_COLD:−X%]` on PTS stat lines; KEY RULES — SHOOTING EFFICIENCY REGRESSION block.
- **First live run (March 8, 2026):** HOT flags: Ausar Thompson (+26%), Paolo Banchero (+14%), Isaiah Hartenstein (+11%), Kawhi Leonard (+8%). COLD flags: Tyrese Maxey (−13%), Giannis (−12%), Julius Randle (−12%), Jalen Johnson (−10%), Desmond Bane (−9%).

**P4 — Tier-Walk Audit Trail ✅ IMPLEMENTED (March 6, 2026)**
- `analyst.py` — `tier_walk` field in output schema; walk-down discipline in SELECTION RULES.
- `auditor.py` — STEP 5 (INSPECT TIER WALK); `tier_walk_flag` in `miss_details`.
- `build_site.py` — tier-walk displayed on pick cards and Top Picks cards.

**H11 — FG% Safety Margin ✅ IMPLEMENTED (shipped without backtest — structural feature)**
- `quant.py` — `ft_safety_margin` computed and added to `player_stats.json`.
- `analyst.py` — annotated in `build_quant_context()`.

**Miss Anatomy (quant fields) ✅ IMPLEMENTED**
- `quant.py` — `build_bounce_back_profiles()` extended with `near_miss_rate`, `blowup_rate`, `typical_miss` per stat × best tier. Fields null when fewer than 5 misses.
- `analyst.py` — **DO NOT TOUCH** pending backtest validation. Fields feed Player Profiles conditional rendering only.

**Minutes Floor ✅ IMPLEMENTED (shipped without backtest — structural feature)**
- `quant.py` — `minutes_floor` computed and added to `player_stats.json`: `{floor_minutes, avg_minutes, n}`.
- `analyst.py` — annotation in `build_quant_context()`; conditional line in Player Profiles portrait.

**Player Profiles ✅ IMPLEMENTED**
- `quant.py` — `build_player_profiles()` computes fresh daily PTS-only statistical portraits. `profile_narrative` key in `player_stats.json`.
- `analyst.py` — `## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS` injected between QUANT STATS and AUDITOR FEEDBACK.
- Eligibility: ≥10 non-DNP games + qualifying PTS best tier. Portrait includes hit sequence, scoring channels, B2B sensitivity, blowout context, and conditional miss anatomy and minutes floor lines.
- **Guiding principle:** Profiles are live statistical portraits, not hardcoded flags or static labels. Analyst reads evidence, not verdicts.

### Deferred

**#1 — Usage-Share Delta When Teammates Are Out**
**Status: DEFERRED** — insufficient DNP sample data mid-season. Key star pairings have 0 absence games; most whitelisted player pairs have <3 shared absence games. Highest-alpha proposal — revisit at start of next season with a full year of data.
- `quant.py` — `build_teammate_absence_deltas()`. Joins `player_game_log.csv` DNP rows to compute per-player stat delta when each teammate is absent vs. present.
- `analyst.py` — instruction to factor absence delta ≥+2 pts or ≥+1 reb/ast into tier selection.

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
| **Improvement Proposal #2 — Opponent-Specific Tier Hit Rates** | Implemented in `quant.py` (`compute_matchup_tier_hit_rates()`, `MIN_MATCHUP_GAMES=3`) and `analyst.py` (`load_player_stats()`, `build_quant_context()`, new QUANT STATS prompt section). `player_stats.json` now includes `matchup_tier_hit_rates` field. |
| **P1 — Game Script Filter (Spread-Adjusted Blowout Risk)** | Implemented across `espn_daily_ingest.py`, `quant.py`, `analyst.py`. Spread + blowout_risk flag + spread_split_hit_rates in player output; prompt rules for BLOWOUT_RISK and spread_abs > 13. |
| **P1 (formerly) — B2B Quantified Tier Adjustment + P3 (formerly) — Days of Rest / Schedule Density** | `build_b2b_game_ids()`, `compute_b2b_hit_rates()`, `compute_rest_context()` in `quant.py`. `b2b_hit_rates`, `rest_days`, `games_last_7`, `dense_schedule` in `player_stats.json`. KEY RULES — REST & FATIGUE block in analyst prompt. |
| **Backtest-driven prompt + quant calibration (March 2026)** | `agents/backtest.py` added. Findings: tier ceiling rules, 3PM opp_defense inversion, trend/home-away removed as directive signals, `PLAYER_WINDOW` raised 10→20. |
| **Bounce-back analysis + player-level integration (March 2026)** | `build_bounce_back_profiles()` in `quant.py`; `bounce_back` key in `player_stats.json`; `bb_lift` / `[iron_floor]` annotations in analyst; SELECTION RULES updated. |
| **Grading correction + full backtest re-run (March 2026)** | All code corrected from `>` to `>=` grading. All 5 backtests re-run. 3PM T2 now above threshold; 3PM opp_defense changed to NOISE; `BACKTESTS.md` rewritten. |
| **Prompt calibration from corrected backtests (March 2026)** | 3PM opp_defense inversion removed; 3PM cold-streak decline rule added; PTS T25 requires ≥80% individual hit rate. |
| **REB opp_defense decoupled (March 2026)** | Stat-specific OPPONENT DEFENSE block in analyst prompt; REB explicitly excluded; REB T8 ceiling rule updated. |
| **Offensive-first player REB floor rule (March 2026)** | Added to analyst SELECTION RULES: players with PTS avg > 20 or AST avg > 6 targeted at or below 25th-percentile recent REB output. |
| **Auditor root cause discipline (March 2026)** | ROOT CAUSE DISCIPLINE block added to `auditor.py`: three pre-flight checks before any miss root cause assignment. |
| **Lineup watch script (March 2026)** | `agents/lineup_watch.py` added. OUT → `voided=True`; DOUBTFUL → `lineup_risk="high"`; QUESTIONABLE → `lineup_risk="moderate"`. `injuries.yml` updated; `build_site.py` updated with voided/risk display. |
| **Auditor season context injection (March 2026)** | `load_season_context()` in `auditor.py`; OFS framing injected into audit prompt. PERMANENT ABSENCES rule block added to `nba_season_context.md`. |
| **Auditor pre-computed statistics (March 2026)** | `prop_type_breakdown` and `confidence_calibration` pre-computed in Python before Claude call. `## PRE-COMPUTED STATISTICS` section added to audit prompt. Both fields added to `audit_log.json`. |
| **Auditor 4-step miss analysis + miss_classification (March 2026)** | PICK ANALYSIS TASK replaced with 4-step protocol. `miss_classification` field added to `miss_details` schema. |
| **Auditor player stats context injection (March 2026)** | `load_player_stats_for_audit()` added. `## PLAYER STATS CONTEXT` injected into audit prompt. *(Superseded March 8, 2026 — function removed; auditor now reads quant context from pick object fields to avoid date-gate bug.)* |
| **Parlay agent reads audit feedback (March 2026)** | `load_parlay_audit_feedback()` added to `parlay.py`. `## PARLAY AUDIT FEEDBACK FROM PREVIOUS DAYS` injected into parlay prompt. |
| **Longitudinal audit summary (March 2026)** | `save_audit_summary()` in `auditor.py` writes `data/audit_summary.json`. `load_audit_summary()` in `analyst.py` injects `## ROLLING PERFORMANCE SUMMARY`. |
| **Injury report display overhaul (March 2026)** | `build_site.py` `load_injuries_display()` rewritten. Game grouping from `nba_master.csv`; whitelist filtering by `(canonical_team, last_name)` tuple; abbrev normalization via `_ABBR_NORM`. |
| **PWA start_url fix (March 2026)** | `site/manifest.json`: `"start_url": "."` and `"scope": "."`. Fixes GitHub Pages subpath resolution for PWA launcher. |
| **Site accent color → orange (March 2026)** | All purple accent instances replaced with `#E8703A` in `build_site.py`. |
| **ML win probability odds on game headers (March 2026)** | `load_game_ml_odds()` added to `build_site.py`. `DAL (24%) @ ORL (80%)` inline in game group headers. |
| **Team abbrev normalization — systematic fix (March 2026)** | `_ABBR_NORM` dict in `build_site.py`; `normAbbr()` JS helper; both Python and JS lookups handle legacy 2-char forms (`GS`, `SA`, `NO`, `UTAH`, `WSH`). |
| **Top Picks section (March 2026)** | `get_top_picks()` in `build_site.py`. `⚡ TOP PICKS TODAY` header above game groups; conf ≥ 85%, ranked by iron_floor + confidence + hit rate + stat priority; min 3 to display. |
| **Picks tab cosmetic refinements (March 2026)** | Streak pills threshold raised to ≥5 consecutive; moved inline. Results tab "OVER " prefix removed from Pick column. |
| **P2 — Rolling Volatility Score (March 2026)** | `compute_volatility()` in `quant.py`. `[VOLATILE]` / `[consistent]` in analyst. KEY RULES — VOLATILITY block. |
| **P1 — Positional DvP (March 2026)** | `position` column in whitelist. `compute_positional_dvp()` in `quant.py`. `DvP [POS]` line per player in analyst prompt. |
| **Auditor crash bug fixes — three sequential bugs in `save_audit_summary()` (March 6, 2026)** | Bug 1: `.items()` on list — added `isinstance` guard. Bug 2: `conf_schema` built as list — rebuilt as dict. Bug 3: `TODAY_STR` NameError — replaced with `TODAY.strftime(...)`. |
| **Lineup Watch — injury snapshot fields on all picks (March 6, 2026)** | `lineup_watch.py` writes `injury_status_at_check` and `injury_check_time` to ALL of today's picks on every run. |
| **Auditor — expanded miss classifications + injury lesson exclusion (March 6, 2026)** | Two new classifications: `injury_event` and `workflow_gap`. Injury/workflow misses excluded from lesson generation. `miss_classification` updated to 5 valid values. |
| **Post-Game Reporter — new agent + auditor wiring (March 6, 2026)** | `agents/post_game_reporter.py` added. Fetches ESPN news for flagged players (DNP, <15 min, zero stats). Classifies as `injury_exit` / `dnp` / `minutes_restriction` / `no_data`. Writes `data/post_game_news.json`. `auditor.py` and `auditor.yml` wired. |
| **Frontend enhancements — Results tab + timezone labels (March 6, 2026)** | ET → PT labels; pick history date format M/D/YY; parlay history key added; Top Picks stats banner on Results tab; collapsible drawers (Top Picks / Pick History / Parlay History). |
| **Pre-Game Reporter — new agent + analyst wiring (March 6, 2026)** | `agents/pre_game_reporter.py` added. Fetches ESPN player + league news; filters to prop-relevant items; single Claude call to summarize. `## PRE-GAME NEWS` injected into analyst prompt. `analyst.yml` wired. |
| **P4 — Tier-Walk Audit Trail (March 6, 2026)** | `tier_walk` field in analyst output. STEP 5 in auditor grading. `tier_walk_flag` in `miss_details`. Tier-walk displayed on pick cards. |
| **JSON-first analyst output enforcement (March 7, 2026)** | `## OUTPUT FORMAT — EMIT THIS FIRST` header in analyst prompt. `bracket_idx` fallback extraction in `call_analyst()`. |
| **Post-Game Reporter — broadened injury detection (March 7, 2026)** | `INJURY_SCAN_TERMS` constant; universal fetch for all missed picks; `injury_language_detected` field in `post_game_news.json`. |
| **Auditor — absence context block + ⚠ injury news flag (March 7, 2026)** | `build_absence_context()` added. `## YESTERDAY'S NOTABLE ABSENCES` injected before pick analysis. `⚠ INJURY LANGUAGE IN NEWS` flag on relevant entries. |
| **Auditor — injury_event hit rate exclusion from audit_summary (March 7, 2026)** | `injury_event` misses excluded from per-prop and overall hit rate denominators in `audit_summary.json`. `injury_exclusions` key added. |
| **Auditor — parlay summary field + PARLAY ANALYSIS TASK rewrite (March 7, 2026)** | PARLAY ANALYSIS TASK rewritten with items 4–8. `parlay_summary` field added to `parlay_results` schema. Markdown audit report extended. |
| **Parlay audit feedback card on frontend (March 7, 2026)** | Parlay card added to `renderAudit()` in `build_site.py`. `parlay_reinforcements` / `parlay_lessons` displayed. Parlay history filter includes `PARTIAL`. |
| **3PM trend=down mandatory step-down rule (March 7, 2026)** | New bullet in KEY RULES — SEQUENTIAL GAME CONTEXT: 3PM trend=down → step down one full tier before finalizing. Scoped to 3PM only. |
| **Parlay concentration cap (March 7, 2026)** | `parlay.py`: no single player-prop combination in more than 2 of today's parlays. |
| **iron_floor field propagated to picks.json (March 7, 2026)** | `"iron_floor"` added to analyst OUTPUT FORMAT schema. `save_picks()` extended with defensive default. |
| **P3 — Shooting Efficiency Regression (March 7–8, 2026)** | `espn_player_ingest.py` collects FG/3P shooting stats. `compute_shooting_regression()` in `quant.py`. `[FG_HOT]`/`[FG_COLD]` annotations in analyst. KEY RULES — SHOOTING EFFICIENCY REGRESSION block. |
| **H11 — FG% Safety Margin (March 2026)** | `ft_safety_margin` in `quant.py` and `analyst.py`. Structural feature, no backtest. |
| **Miss Anatomy quant fields (March 2026)** | `near_miss_rate`, `blowup_rate`, `typical_miss` added to `build_bounce_back_profiles()` in `quant.py`. Analyst wiring deferred pending backtest. |
| **Minutes Floor (March 2026)** | `minutes_floor` in `quant.py` and `analyst.py`. Structural feature, no backtest. |
| **Player Profiles (March 2026)** | `build_player_profiles()` in `quant.py`. `## PLAYER PROFILES` injected into analyst prompt. Live statistical portraits computed fresh daily. |
| **Season Context Improvement 0 — Standings Snapshot (March 8, 2026)** | `fetch_standings()` in `espn_daily_ingest.py` writes `data/standings_today.json`. `render_playoff_picture()` formatter in `analyst.py` and `auditor.py`. Bucketed `## PLAYOFF PICTURE` injected into both prompts. |
| **Season Context Improvement 1 — Auto-Generated Team Defense Narratives (March 8, 2026)** | `build_team_defense_narratives()` in `quant.py` writes `data/team_defense_narratives.json` (last 15g PPG + rank per team). `format_team_defense_section()` in `analyst.py` replaces static `## TEAM DEFENSIVE PROFILES` section; validates `as_of == TODAY` and returns fallback if stale. |
| **Season Context Improvement 2 — Staleness Detection (March 8, 2026)** | `detect_staleness_flags()` (Pass 1 — Python only, no LLM) added to `pre_game_reporter.py`. Parses SEASON FACTS dates and flags stale facts (7d/5d/60d rules). Flags appended to `data/context_flags.md` and `staleness_flags` key in `pre_game_news.json`. `analyst.py` picks up via existing `⚠ CONTEXT FLAG` mechanism. |
| **Auditor — NO_DATA handling + player stats date gate (March 8, 2026)** | Removed `load_player_stats_for_audit()` and `PLAYER_STATS_JSON` entirely — eliminates today's-data-for-yesterday's-audit confabulation bug. HIT/MISS picks now go to `## FULL GRADED PICKS` for standard miss analysis; NO_DATA picks split into separate `## NO_DATA PICKS` block with dedicated `## NO_DATA ANALYSIS TASK`. Auditor directed to read quant context from pick object fields (`reasoning`, `hit_rate_display`, `tier_walk`, `opponent`). `no_data_details` array added to `audit_log.json` output schema. |
| **Post-Game Reporter — QUESTIONABLE pre-game status + NO_DATA promotion (March 8, 2026)** | `load_yesterdays_picks_with_status()` added — reads `injury_status_at_check` from `picks.json`, returns highest-severity status per player. `classify_from_news()` now accepts `injury_status` param; pre-game status inference block fires when status ∈ {QUESTIONABLE, DOUBTFUL, OUT} and minutes are 0/low — returns `dnp` or `minutes_restriction` without needing ESPN confirmation. Separate promotion block upgrades `no_data` → `dnp`/`injury_exit` when injury language detected. `injury_status_at_check` added to `post_game_news.json` output. |
| **Analyst — AST T4+ hard gate + 3PM hard skip (March 8, 2026)** | Two unconditional gates added to `build_prompt()`. (1) AST T4+ hard gate: PF/C or raw_avgs AST < 4.0 → opponent AST DvP must be "soft"; mid/tough = skip, no override. (2) 3PM hard skip: trend=down AND avg_minutes_last5 ≤ 30 → skip all 3PM picks including T1 (step-down rule does not apply). Both gates are additive; existing rules unchanged. |
| **Lineup Watch — wiring fix (March 9, 2026)** | `lineup_watch.py` was not in the `injuries.yml` chain — injuries refreshed hourly but `picks.json` `voided` flags never updated. Fixed: `lineup_watch.py` added between `rotowire_injuries_only.py` and `build_site.py` in `injuries.yml`. Name matching hardened to last-name + team-abbrev key (handles Rotowire abbreviated format). Stale flag clearing added: status improvements between hourly runs now remove prior `voided`/`lineup_risk` flags. `AGENTS.md` workflow diagram updated. |
| **Analyst — min_floor confidence cap + BLOWOUT_RISK secondary scorer skip + parlay player-level concentration cap (March 9, 2026)** | Three hard gates added. (1) min_floor cap: PTS pick with `floor_minutes < 24` → confidence capped at 84% regardless of streak/iron_floor tag. (2) BLOWOUT_RISK secondary scorer skip: spread ≥ +8 underdog AND non-primary scorer → PTS pick skipped entirely (not just -5% deduction). (3) Parlay concentration cap widened from player-prop level to player level: no single `player_name` in more than 2 of today's parlays regardless of prop type. Post-selection validation added to `parlay.py` as reliable enforcement point. |
| **Analyst — OUT/DOUBTFUL hard pre-filter (March 9, 2026)** | Root cause: `analyst.py` relied on LLM self-exclusion of OUT players — no Python filter existed. Two-layer fix: (1) `rotowire_injuries_only.py` added as first step of `analyst.yml` so injuries are always fresh before picks run. (2) `load_out_players()` added to `analyst.py` — reads `injuries_today.json`, builds `(last_name, team_abbrev)` exclusion set, strips OUT/DOUBTFUL players from `player_stats` dict before any prompt-building call. Claude never receives stats for excluded players. INJURY EXCLUSION hard rule added to KEY RULES as backstop. `parlay.py` candidate pool filters excluded players as defense-in-depth. Exclusions logged to stdout. `AGENTS.md` updated. |
| **Projected Lineup Scraping + Analyst Context Injection (March 9–10, 2026)** | `rotowire_injuries_only.py` extended with `parse_rotowire_lineups()` and `write_lineups_json()` → writes `data/lineups_today.json`. Guard condition prevents 0-team parse from overwriting good existing data. `analyst.py` adds `format_lineups_section()` (reads + staleness-checks `lineups_today.json`), `write_analyst_snapshot()` (writes `snapshot_at_analyst_run` into `lineups_today.json` at pick time), LINEUP CONTEXT key rule in SELECTION RULES. `## PROJECTED LINEUPS` injected between injury report and pre-game news. `AGENTS.md` updated. |
| **P5 — Afternoon Lineup Update Agent (March 10, 2026)** | New `agents/lineup_update.py`: snapshot-based diff against `snapshot_at_analyst_run`; detects `new_absence` and `starter_replaced` change types; calls Claude (single prompt) for affected picks (team or opponent changed, tip-off > 20 min); writes `lineup_update` sub-object `{triggered_by, updated_at, direction, revised_confidence_pct, revised_reasoning}` in-place; fully idempotent — overwrites on each hourly run; `direction=unchanged` still written as audit evidence. `injuries.yml` wired (`anthropic` dep + run step + commit step). `build_site.py` badge: `↑/↓ Updated HH:MM` with expandable detail panel on pick cards and Top Picks. `AGENTS.md` updated. |
| **Rotowire session login + projected_minutes/onoff_usage scraping (March 10, 2026)** | `login_rotowire(session)`, `parse_projected_minutes(soup)`, `parse_onoff_usage(soup)` added to `rotowire_injuries_only.py`. `fetch_rotowire_html()` refactored to accept optional session (backward-compatible). `write_lineups_json()` extended with optional `projected_minutes`/`onoff_usage` params. `main()` creates `requests.Session()`, authenticates, and conditionally calls new parsers only when authenticated. `lineups_today.json` now optionally carries per-team projected minutes and on/off usage data. `ROTOWIRE_EMAIL`/`ROTOWIRE_PASSWORD` env vars injected into both `injuries.yml` and `analyst.yml`. All new parsing is graceful-degradation — returns `{}` on any exception, never crashes. |
| **Analyst lineup context wiring (March 10, 2026)** | `load_lineup_context()` added to `analyst.py` — reads `lineups_today.json`, staleness-checks `asof_date`, builds per-team normalized lookup dict. `build_quant_context()` signature updated to accept optional `lineup_context` param. Three new per-player annotations injected when Rotowire creds present: (1) `proj_min=N` in header (Rotowire projected minutes), (2) `[USG_SPIKE:+N.Npp vs X.Name]` in header when usage_change ≥ 5.0 AND minutes_sample ≥ 100, (3) `⚠ OPP: Name OUT (proj=0min)` after DvP line for opponent key absences (capped at 3). `main()` wired to call `load_lineup_context()` and pass result to `build_quant_context()`. |
| **Knowledge staleness awareness block in analyst build_prompt() (March 10, 2026)** | `## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE` block inserted in `build_prompt()` between `Today is {TODAY_STR}.` and `## YOUR TASK`. Distinguishes perishable knowledge (player roles and usage, rosters and depth charts, team systems and pace, H2H matchup history, season narratives — do NOT rely on training data for any of these) from durable knowledge (general basketball principles, tier logic and statistical reasoning, role archetype reasoning — apply freely). Instructs Claude: if a fact is specific to a named player or team, trust the injected data; if it is a general basketball principle, apply it freely. |
