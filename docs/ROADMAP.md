# NBAgent — Roadmap & Issue Log

---

## Open Items

### Operational
- **Whitelist maintenance** — review and update `active` flags as the season evolves, especially post-trade-deadline role changes
- **Season end handling** — workflows need to be paused/disabled in the off-season (roughly late June). Simplest approach: disable the cron schedules in each `.yml`, re-enable in October.
- **DST → PST cron shift (early November)** — GitHub Actions cron runs in UTC. During PDT (mid-March → early November) PT = UTC-7; during PST (early November → mid-March) PT = UTC-8. All cron entries in `injuries.yml` (and any other workflow with PT-labeled schedules) need their UTC hour values incremented by 1 when clocks fall back in November, and decremented by 1 when clocks spring forward in March. Failure to update will cause the schedule to run one hour later than intended all winter. Add this to the October re-enable checklist.

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
- **"Stay Away?" UI caution flag** — A `⚠ Stay Away?` badge on pick cards that meet the system's statistical criteria but carry compounding contextual risk signals. Does NOT suppress the pick — purely informational for manual betting decision. Badge triggers when 2+ risk signals co-occur on the same pick. Candidate signals: team momentum `[cold]` tag, opponent `[hot]` tag, `DENSE` schedule, `B2B`, `blowout_risk`, player on `[cold]` matchup DvP split, `VOLATILE` + weak trend. Badge expands a drawer (same UX pattern as "show reasoning") listing whichever signals fired and a brief plain-English summary. Implementation: small new field on pick output (`stay_away_signals: []`) written by analyst if signals fire; `build_site.py` renders badge + drawer. No new LLM calls, no new quant logic. Prerequisite: team momentum indicator live in production so `[hot]`/`[cold]` tags are available. Evaluate trigger threshold after momentum data accumulates (~2 weeks).

---

## Active Queue — In Priority Order

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

#### M1 — Situational Player Profiles (DEFERRED TO OFFSEASON)
**Priority: OFFSEASON — multi-season data required; not tractable within a single season**
**Replaces the original narrow H2H splits design; scope significantly expanded after March 2026 discussion**

**What this is really about:** The original M1 framing — compute per-player tier hit rate against today's specific opponent over a single season — is too narrow and too sample-limited to be honest. NBA teams play each opponent only 2–4 times per season. By the time you have 5+ matchups (the original minimum), the season is nearly over, and there's no subsequent game to act on. The regular season ends April 12, 2026 — the mid-April backtest timing in the original design was almost exactly end-of-season, making it operationally useless for in-season picks.

**The broader hypothesis worth investigating:** There is a real class of player-level situational performance patterns that are statistically grounded but currently invisible to the system. Examples that motivated this:
- Players who consistently over- or under-perform against specific opponents (scheme familiarity, matchup history, rivalry dynamics)
- Players who elevate in big-market road arenas (MSG, Crypto.com, TD Garden) — the "big stage" effect
- Players who perform differently in nationally televised games vs. local broadcasts
- Players with historically strong/weak records against specific defensive archetypes (switching teams, zone-heavy teams, physical bigs) across multiple seasons
- Career rivalries between individual players (Ant vs. Luka, etc.) that show up in stat lines, not just narrative

**Why not now:** All of these require multi-season data with consistent role context to be meaningful. A single-season sample has too few instances per condition, and roster/role changes between seasons require careful controls. The investigation belongs in the offseason when there's time to assemble clean multi-season datasets and run honest backtests.

**Relationship to Stay Away flag:** This offseason investigation is the right long-term feeder for the "Stay Away?" UI caution flag (see Frontend open items). The pattern isn't "the system should hard-skip this pick" — it's "here is a real tension between the statistical case and a situational risk factor the numbers don't fully capture." Small-sample situational splits are well-suited to informing a human hold decision, not to encoding as directive system rules.

**Offseason research agenda (when ready):**
- Assemble 2–3 seasons of `player_game_log.csv` data with consistent player-team mapping
- Define and test: opponent-specific hit rate splits; home arena performance profiles; national TV game splits; opponent defensive archetype splits (requires team-level scheme tagging)
- Validate each against a null hypothesis of no effect — most narrative-driven splits will not survive honest testing, and that's the finding worth knowing
- For signals that survive: design annotation-only injection into player profiles or Stay Away flag triggers; do NOT encode as directive rules without further validation
- Consider: which signals are stable enough across seasons to be useful in-season, and which require annual recalibration?

**Where:** Offseason project. No current-season code changes.

---

#### M2 — Defensive Recency Split
**Status: ✅ IMPLEMENTED (March 12, 2026)**

`compute_opp_defense_recency()` added to `quant.py` (constants: `DEF_RECENCY_SHORT=5`, `DEF_RECENCY_THRESH=0.08`, `DEF_RECENCY_MIN_L5=3`). Compares opponent's L5 vs L15 PTS-allowed avg; flags `"soft"` (L5 ≥8% above L15) or `"tough"` (L5 ≥8% below L15); `def_recency` field in `player_stats.json`. `DEF↑`/`DEF↓` inline header annotation in `build_quant_context()`. Annotation only — no directive rules. Validation gate: after 30+ flagged instances, evaluate whether `DEF↑` picks outperform baseline vs. neutral/`DEF↓` picks.

**What:** A recency flag on opponent defense: compare opponent's allowed average over last 5 games vs. last 15 games (the existing `opp_defense` window). Flag when L5 diverges materially from L15 — indicating the defense has changed recently (injury to key defender, scheme change, fatigue stretch).

**Validation gate:** After 30+ flagged instances, evaluate whether `def_trending_soft` picks outperform baseline. **Where:** `agents/quant.py`, `agents/analyst.py` only.

---

### F1 — Personal Foul Tracking + Foul-Prone Player Profiles
**Status: FUTURE — data pipeline expansion required**
**Priority: LOW — queue for offseason or early next season**

**What:** Track personal fouls (PF) per game in `player_game_log.csv` and surface foul-prone patterns in Player Profiles for players where foul trouble is a recurring performance driver. LaMelo Ball (March 10) is the prototype case: his 22-minute game was driven by early foul trouble in Q1, not load management or a coaching decision. This behavioral pattern — not minutes fragility per se — is a recurring known risk for specific players.

**Why not now:** Requires schema expansion in `espn_player_ingest.py` to collect PF from box scores, a backfill pass on `player_game_log.csv` for historical data, and a new quant function to identify foul-prone players (e.g., games with PF ≥ 4 in the L20 window). The min_floor guardrail already partially mitigates the downstream effect (foul trouble shows up as a low-minutes game). The marginal lift from identifying the cause vs. the effect is real but not urgent given current system coverage.

**Design (when ready):**
- `espn_player_ingest.py` — add `personal_fouls` column to `player_game_log.csv`
- `quant.py` — `compute_foul_trouble_profile()`: flag players with ≥3 games of PF ≥ 4 in L20; surface as `foul_prone` bool + `foul_trouble_rate` (% of L20 games with PF ≥ 4) in `player_stats.json`
- Player Profiles — add conditional rendering: "Foul-prone: X% of recent games with 4+ PF — minutes exposure at risk in tight or physical matchups"
- No directive prompt rules until signal is backtested against actual minutes/performance outcomes

**Where:** `ingest/espn_player_ingest.py`, `agents/quant.py`, `agents/analyst.py` (Player Profiles block only)

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

#### W4 — H10 FG_COLD Tier-Step Revisit
**Status: WATCH — one instance, do not act until more FG_COLD misses accumulate**

Cooper Flagg's March 10 miss (14 actual vs 15 pick, FG_COLD:-18%, missed by 1) raised the question of whether FG_COLD ≥ -15% should trigger a hard tier step-down on PTS picks rather than remaining annotation-only. H10 backtest verdict (521 instances) found FG_COLD lift=1.128 (counterintuitively positive) — confidence penalties were removed on that basis. However, the H10 backtest evaluated confidence adjustments, not tier step-downs; these are distinct mechanisms. A tier step-down at high FG_COLD values is an open question the backtest did not directly address. **Do not act until 3–5 additional FG_COLD ≥ -15% PTS misses accumulate in the audit log. If a pattern emerges, revisit whether a tier-step rule is warranted at high thresholds (≥ -15% or ≥ -18%) without conflicting with the H10 annotation-only verdict on confidence.**

---

### Pending Backtests

| ID | Name | Status | Mode | ETA |
|----|------|--------|------|-----|
| H8 | Positional DvP Validity | Queued — data accumulating | `--mode positional-dvp` | ~early April 2026 (run before Apr 12) |
| H9 | Situational Player Profiles | DEFERRED TO OFFSEASON — see M1 entry | — | Oct 2026+ |
| Miss Anatomy | Near-miss vs. blowup next-game | Queued — quant fields live | `--mode miss-anatomy` | ~late March 2026 |
| H14 | Elite Opposing Rebounder REB Suppression | Queued — no new data required | `--mode elite-opp-rebounder` | ~late March / early April 2026 |

**Miss Anatomy — analyst wiring deferred:** `near_miss_rate` and `blowup_rate` fields are live in `player_stats.json` and feeding Player Profiles. The directive prompt rule (confidence modifier or tier-drop on high `blowup_rate`) is explicitly NOT shipped until the backtest validates the signal. See `miss_anatomy_quant_only.md`.

---

### H14 — Elite Opposing Rebounder REB Suppression
**Status: QUEUED — no new data collection required; all inputs in existing CSVs**
**ETA: ~late March / early April 2026**
**Mode: `--mode elite-opp-rebounder`**

**Hypothesis:** A player's REB tier hit rate is meaningfully suppressed when the opponent features (a) an elite individual rebounder at center — specifically a top-N season REB average — and/or (b) an elite team offensive rebounding unit, because the opposing center is implicitly tasked with boxing-out or otherwise contesting the elite rebounder, compressing their own counting stats.

**Motivating observation (March 11, 2026):** Alperen Sengun (9.0 avg REB, #11 league-wide) missed REB O6 with only 2 actual against Jokic and DEN despite a 10/10 recent hit rate, 80% confidence, and tough DvP. Post-game context: DEN won 129–93, HOU team REB distribution was spread across guards/wings (Tari Eason notable first-half boards), suggesting Sengun was occupied boxing out Jokic rather than collecting boards. Classified as `variance` by auditor, but domain reasoning suggests a structural mechanism worth testing.

**Two separable sub-hypotheses:**

1. **H14a — Individual Opposing Center Quality:** Does REB tier hit rate for a center/PF drop when the opposing center ranks in the top N by season REB average? Test at top-5, top-10, top-15 cutoffs. Primary position filter: apply only to C and PF (the positional boxing-out effect is direct; wings are less affected).

2. **H14b — Team Offensive Rebounding Rate:** Does REB tier hit rate drop when playing against a top-N offensive rebounding team? An elite OREB team generates more contested second-chance situations that change the rebounding geometry for the opposing big. This is independent of individual matchup — a team that crashes hard (OKC, IND, DEN historically) compresses opposing center REB totals even without one dominant individual rebounder. Test at top-5, top-10, top-15 cutoffs by team OREB rate.

**Why these are distinct:** H14a is about a single elite opponent rebounder demanding defensive attention. H14b is about the volume of offensive rebounding attempts requiring response. A team can have a high OREB rate without a single dominant rebounder (and vice versa). Both mechanisms could independently suppress opposing center REB totals; both should be tested separately.

**Data requirements:** All inputs already in existing CSVs.
- `player_game_log.csv` — per-game REB totals, player position, opponent
- `nba_master.csv` — game-level opponent pairing, season context
- `player_whitelist.csv` — position column for filtering to C/PF
- For H14b: team OREB data derivable from `team_game_log.csv` (offensive rebounds column, if present) or from per-player REB aggregation

**Key design decisions:**

- **Position filter:** Apply primarily to C and PF. Wing scorers (SG/SF) are not the primary boxing-out assignment and the mechanism is weaker for them. Run wing cut separately to confirm the effect is position-specific.
- **Opponent center identification:** Rank by season REB average among centers (use `player_whitelist.csv` positions + `player_game_log.csv` aggregates). For games where the opposing center is in the top-N, flag the game.
- **Tier hit rate metric:** Same methodology as existing backtests — compute tier hit rate for the target REB tier (best qualifying tier from `tier_hit_rates`) split by elite-opponent-present vs. not-present. Primary stat: lift = hit_rate_elite_opp / hit_rate_baseline.
- **Minimum sample gate:** Require ≥15 game observations per split before reporting a lift figure. Small-N splits are discarded.
- **DNP exclusion:** Standard — exclude `dnp == "1"` rows before any computation.

**Thresholds to test:**
- Individual opposing center: top-5, top-10, top-15 by season REB avg
- Team OREB: top-5, top-10, top-15 teams by season OREB rate
- Report lift at each threshold; look for consistent directional signal before setting a production cutoff

**Verdict criteria:**
- **Actionable signal:** Lift ≤ 0.85 (≥15% suppression) at top-10 individual or top-10 team OREB cutoff with ≥15 game sample → warrants an annotation in analyst context and possible tier-step rule
- **Weak signal:** Lift 0.86–0.94 → annotation only, no directive rule, monitor further
- **Noise:** Lift > 0.95 or inconsistent across cutoffs → close hypothesis, no action

**If signal confirmed:** Implementation path is quant-first / analyst-annotation-only (consistent with annotation vs. directive discipline). New `opp_rebounder_risk` field in `player_stats.json` (bool + label); annotation injected into per-player REB stat line similar to `[FG_COLD]`. Directive tier-step rule requires further validation before shipping. REB DvP exclusion already established — this signal is complementary, not redundant (it measures opposing rebounder quality, not team defensive rebounding tendency).

**Scope:** `agents/backtest.py` only — add `--mode elite-opp-rebounder` mode. No production files touched until verdict is confirmed.

---

## Implementation Notes

- **Season Context Improvements 0–2** — ✅ All implemented March 8, 2026. Standings snapshot, auto-generated team defense narratives, and staleness detection are live in production. 
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
- **Analyst — three prompt rule hardenings (March 11, 2026):** Three rules tightened following March 10 audit review. (1) **Minutes Floor mandatory tier step-down:** `min_floor < 24 AND tier ≥ T15 → mandatory step to T10` (was: confidence cap only). Exception: `avg_minutes > 36`. Validated by Ball (foul trouble) and Flagg (FG_COLD) misses. (2) **Iron-floor scope clarification:** `[iron_floor]` protects TIER only, not confidence level. VOLATILE -5% still applies even when iron_floor is present. Iron_floor does not suppress AST VOLATILE deduction for wing scorers (SG/SF) with down trend — motivated by Barrett AST miss and Barrett/Ingram scoring load shift. (3) **VOLATILE PTS skip rule:** VOLATILE + 7/10 hit rate + T15+ PTS → skip entirely. Exception: iron_floor AND trend=up. Motivated by Ingram PTS miss pattern.
- **Post-Game Reporter — Brave Search web narrative layer (March 11, 2026):** Root cause addressed: Post-Game Reporter was ESPN athlete news API only. Ejections (Brown), in-game foul trouble (Ball), and blowout-driven early-game context were invisible to the reporter and therefore to the Auditor. Fix: `fetch_web_narratives()` added — queries Brave Search API (3 results per missed-pick player, `"{name} {team} NBA recap {date}"` format). `call_claude_summarise_narratives()` makes a single batch Claude call (sonnet-4-6, 2048 tokens) for all missed players, returns `{player_name_lower: narrative_string}`. `web_narrative` field added to `players_out` entries in `post_game_news.json` (default null). Auditor `build_audit_prompt()` appends `📰 WEB RECAP: {narrative}` as indented second line in POST-GAME NEWS CONTEXT block. `auditor.yml` wired with `BRAVE_API_KEY` secret. ESPN flow fully preserved; web layer is additive and gracefully degrades at every failure point. `BRAVE_API_KEY` added to GitHub repo secrets.
- **Skip Validation — analyst skip records + auditor grading (March 11, 2026):** Closed-loop validation system for rule-forced skips. Analyst now emits `{"picks": [...], "skips": [...]}` JSON object (was flat array). Skip records written to `data/skipped_picks.json` (overwrite daily) for any hard-rule-forced skip where the blocked tier had ≥70% hit rate. Eight `skip_reason` values tracked: `min_floor_tier_step`, `volatile_weak_combo`, `blowout_secondary_scorer`, `3pm_trend_down_tough_dvp`, `3pm_trend_down_low_minutes`, `ast_hard_gate`, `fg_margin_thin_no_valid_tier`, `reb_floor_skip`. `call_analyst()` returns `(picks, skips)` tuple; backward-compatible flat-array fallback retained. `save_skips()` writes null-initialized grading fields. Auditor grades skips each morning via pure-Python `grade_skips()` (no Claude call) — fills `actual_value`, `would_have_hit`, `skip_verdict`, `skip_verdict_notes`. Results roll up into `audit_summary.json` under `skip_validation` key (per-rule `false_skip_rate`). Daily audit report includes `## Skip Validation` table. Graded `skipped_picks.json` committed in both `analyst.yml` and `auditor.yml`. `false_skip_rate > ~30%` for a rule type = signal that rule may be overcorrecting.
- **Injuries workflow — extended evening cron schedule (March 11, 2026):** Hourly injury refresh runs extended from 6 PM PT cutoff to 10 PM PT, covering all NBA tipoff windows (5 PM, 7 PM, 8 PM, 8:30 PM PT). Seven new cron entries added (4 PM–10 PM PT). Root cause: late scratches (e.g., LeBron) were announced after the last scheduled refresh, leaving picks un-voided through tip-off. All comments corrected from ET to PT. `workflow_dispatch` retained for manual triggers.
- **`lineup_update.py` — direction guide expansion + Rotowire context injection (March 10, 2026)** — `build_rotowire_context(lineups, changed_teams)` helper added; reads `projected_minutes` and `onoff_usage` from `lineups_today.json` for changed teams and formats a plain-text block for Claude. `call_lineup_update()` signature updated to accept optional `rotowire_context` param; system prompt replaced with prop-type-aware direction guide covering PTS/REB/AST/3PM each with separate up/down/unchanged logic; calibration instruction added for Rotowire usage magnitude → confidence adjustment. `rotowire_section` injected into Claude user message when context non-empty (graceful no-op on unauthenticated runs). `main()` computes `changed_teams` set and passes Rotowire context to `call_lineup_update()`.
- **Analyst — blowout spread cap refinements (March 10, 2026)** — Two bullets added to KEY RULES — SPREAD / BLOWOUT RISK in `build_prompt()`. (1) BLOWOUT-RESILIENT OFFSET CAP: `[iron_floor]` or "blowout-resilient" signals do not zero out the BLOWOUT_RISK -10% PTS penalty — they offset it by 5pp (net -5%), not eliminate it entirely. (2) LARGE SPREAD PTS CAP: when BLOWOUT_RISK=True AND spread_abs ≥ 12, PTS confidence capped at 74% regardless of hit rate, iron_floor, or resilience signals. Motivated by March 9 audit over-confidence on large-spread favored-team PTS picks.
- **Analyst — INJURY STATUS ON SHOOTING PROPS rule (March 10, 2026)** — New KEY RULES — INJURY STATUS ON SHOOTING PROPS block added to `build_prompt()`. When a player carries QUESTIONABLE status involving a soft-tissue joint concern (ankle, foot, knee, hip, groin), apply -5% confidence to all shooting-dependent props (3PM and PTS). Rationale: compromised lower-body movement shifts attempts away from the perimeter, reducing 3PM floors directly and PTS floors via shooting efficiency. Does not apply to PROBABLE/unlisted (OUT/DOUBTFUL already pre-filtered). Non-contact injury types (illness, rest) exempt.
- **Analyst — 3PM hard skip: trend=down AND tough DvP (March 10, 2026)** — Second 3PM hard skip rule added to KEY RULES — SEQUENTIAL GAME CONTEXT in `build_prompt()`. If 3PM trend is "down" AND opponent DvP 3PM rating is "tough", skip all 3PM picks including T1 — do not apply step-down rule. Rationale: after a trend=down step-down lands at T1, there is no margin left; a single cold night produces zero. Tough perimeter DvP compounds the floor compression. Both March 9 audit 3PM misses (Mitchell T1 8/10, Murray T1 9/10) met this exact profile. Note: 3PM DvP is otherwise noise — this is the sole exception, requiring BOTH conditions simultaneously.
- **Auditor — amendment context injection + model_gap sub-classification (March 10, 2026)** — STEP 6 added to PICK ANALYSIS TASK: Auditor reads `lineup_update` sub-object on pick objects and notes amendment direction vs. outcome in `root_cause` (direction=down + miss → "Amendment correctly flagged…"; direction=up + miss → "Amendment flagged upside but pick missed"; etc.). Does not change `miss_classification` — amendment notes are contextual feature-validation evidence only. `model_gap` split into `model_gap_signal` (system lacks the signal entirely — no quant field or rule exists) and `model_gap_rule` (signal existed in quant data/context but analyst rule didn't handle the combination). `save_audit_summary()` valid set updated to include both new sub-classifications; legacy `model_gap` removed. Two prose references to `model_gap` in NO_DATA block and STEP 2 inspection-order text also updated.
- **Team Momentum Indicator (March 11, 2026)** — `build_team_momentum()` in `quant.py`. L10 record + avg point margin for player's team and opponent. `team_momentum` field in `player_stats.json`. `Momentum —` annotation line in `build_quant_context()` between DvP and stat lines. Annotation only — no directive rules. No new ingest required: fully derived from existing `nba_master.csv` completed game data. Tag logic: ≥7 wins = "hot", ≤3 wins = "cold", otherwise "neutral" (not shown in annotation). Computed for all teams playing today via `build_team_momentum(master_df, teams_today)` in `main()`; passed to `build_player_stats()` as `team_momentum=team_momentum`.
- **M2 — Defensive Recency Split (March 12, 2026)** — `compute_opp_defense_recency()` added to `quant.py`; compares opponent's L5 vs L15 PTS-allowed avg; `DEF_RECENCY_SHORT=5`, `DEF_RECENCY_THRESH=0.08`, `DEF_RECENCY_MIN_L5=3`; flags `"soft"` (L5 ≥8% above L15 = defense trending easier) or `"tough"` (L5 ≥8% below L15 = defense tightening), `None` otherwise; `def_recency` field in `player_stats.json`; `DEF↑`/`DEF↓` inline header annotation in `build_quant_context()` after `{usg_spike_str}`; annotation only — no directive rules. Validation gate: after 30+ flagged instances, evaluate whether `DEF↑` picks outperform baseline.
- **Analyst — three prompt rule tightenings (March 12, 2026)** — Three targeted audit-hardening changes to `build_prompt()` based on 8 days / 45 misses of evidence. (1) **REB gate strict greater-than:** pick tier must be strictly less than 3rd-lowest L10 REB value; "at or below" language removed — exact match forces step-down; motivated by Sengun REB miss (3rd-lowest=6, pick=6, actual=2, 10/10 streak broken). (2) **VOLATILE PTS skip extended to 8/10:** skip condition broadened from "exactly 7/10" to "7/10 OR 8/10" at T15+; motivated by Ingram PTS O15 miss ×3 in 8 days — twice at 8/10 bypassed the existing rule; exception clause updated to reference "8/10 baseline." (3) **FG_COLD ≥15% tier step-down:** added EXCEPTION clause to SHOOTING EFFICIENCY REGRESSION block; FG_COLD ≤ -15% on T15+ PTS now requires mandatory one-tier step-down before finalizing; `fg_cold_tier_step` skip_reason added (fires when step-down finds no qualifying tier); FG_HOT handling and confidence-adjustment removal unchanged; motivated by Flagg PTS O15 miss with FG_COLD:-18% treated as informational. All prompt-only — no quant, schema, or workflow changes.
- **Auditor — Game Results Context Injection (March 12, 2026)** — Root cause: auditor had no direct access to final game scores; had to infer blowout/close-game context from ESPN athlete news and Brave Search hits — both fragile and delayed. Motivating failure: Kevin Durant (HOU) and Nikola Jokic (DEN) both missed in the same 36-pt HOU/DEN blowout (March 11). Without knowing the game result, the auditor classified one as `variance` and the other as `selection_error` — inconsistent, because both were driven by the same blowout game script. Fix: `MASTER_CSV = DATA / "nba_master.csv"` path constant added to `auditor.py`; `load_game_results()` reads yesterday's rows from master CSV, keys result dict by BOTH home and away team abbrev (O(1) lookup from either direction), skips rows with unparseable scores, returns `{}` on any file error; `build_game_results_block()` deduplicates via `seen` set on `{home}_{away}` key, labels each game BLOWOUT (margin ≥ 20), COMPETITIVE (10–19), or CLOSE (<10), sorts alphabetically, returns `## GAME RESULTS — YESTERDAY` header block; `build_audit_prompt()` signature extended with `game_results_block: str = ""`; block injected between season context and playoff picture sections; STEP 0 — ESTABLISH GAME CONTEXT added as first step of PICK ANALYSIS TASK — directs auditor to look up each player's team in the game results section and identify the final score, margin, and game_script label before analyzing any individual miss, ensuring shared game-context evidence is applied consistently across all players from the same game; existing STEP 1–6 numbering unchanged; `main()` wired with both new function calls and kwarg pass to `build_audit_prompt()`. `agents/auditor.py` only — no quant, analyst, or workflow changes.
- **Fix: `analyst.yml` — commit `lineups_today.json` (March 10, 2026)** — `data/lineups_today.json` added as fourth entry in the analyst.yml commit loop (alongside `picks.json`, `parlays.json`, `player_stats.json`). Root cause: P5 implemented `write_analyst_snapshot()` in `analyst.py` and `lineup_update.py` correctly, but `analyst.yml` never committed the file. Every hourly `injuries.yml` run checked out a clean repo with no `lineups_today.json`, causing `lineup_update.py` to exit with "no snapshot found — skipping" and produce zero output. **Implementation lesson:** when a feature spans multiple workflows, explicitly audit every file the feature reads at runtime and verify it will be present in each workflow's checkout. Specifically: if workflow A writes a file and workflow B reads it in a later job, the file must be committed by A's commit step or B will always see a missing file. The "no file found" skip log is ambiguous — it can mean expected no-op *or* silent failure from a missing commit. Verify which before shipping cross-workflow features.

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
| **Analyst — three prompt rule hardenings (March 11, 2026)** | (1) **min_floor mandatory tier step-down:** `min_floor < 24 AND tier ≥ T15 → mandatory step to T10` (was: confidence cap only). Exception: `avg_minutes > 36`. (2) **Iron-floor scope clarification:** `[iron_floor]` protects tier only, not confidence. VOLATILE -5% still applies even with iron_floor. AST iron_floor does not suppress VOLATILE deduction for wing scorers (SG/SF) with down trend. (3) **VOLATILE PTS skip:** VOLATILE + 7/10 + T15+ PTS → skip. Exception: iron_floor AND trend=up. All three rules are prompt-only — no code changes. |
| **Post-Game Reporter — Brave Search web narrative layer (March 11, 2026)** | `fetch_web_narratives()` added to `post_game_reporter.py` — queries Brave Search API for each missed-pick player (`"{name} {team} NBA recap {date}"`, 3 results). `call_claude_summarise_narratives()` makes a single batch Claude call (2048 tokens) and returns `{player_name_lower: narrative_string}`. `web_narrative` field added to `players_out` entries in `post_game_news.json` (default null). Auditor `build_audit_prompt()` appends `📰 WEB RECAP: {narrative}` to POST-GAME NEWS CONTEXT per missed player. `auditor.yml` wired with `BRAVE_API_KEY`. ESPN flow unchanged; web layer is additive and fully gracefully-degrading. Root cause addressed: ejections and foul-trouble narratives were invisible to reporter and auditor. |
| **Skip Validation — analyst skip records + auditor grading (March 11, 2026)** | Analyst now emits `{"picks": [...], "skips": [...]}` JSON object (was flat array). Backward-compatible flat-array fallback retained. Skip records written to `data/skipped_picks.json` (overwrite daily) for hard-rule-forced skips where blocked tier had ≥70% hit rate. Eight `skip_reason` values: `min_floor_tier_step`, `volatile_weak_combo`, `blowout_secondary_scorer`, `3pm_trend_down_tough_dvp`, `3pm_trend_down_low_minutes`, `ast_hard_gate`, `fg_margin_thin_no_valid_tier`, `reb_floor_skip`. `call_analyst()` returns `(picks, skips)` tuple. `save_skips()` writes null grading fields. Auditor grades via pure-Python `grade_skips()` (no Claude call) — fills `actual_value`, `would_have_hit`, `skip_verdict`, `skip_verdict_notes`. `save_audit_summary()` rolls up `skip_validation` block (per-rule `false_skip_rate`). Daily audit report includes `## Skip Validation` table. `skipped_picks.json` committed in both `analyst.yml` and `auditor.yml`. |
| **Injuries workflow — extended evening cron schedule (March 11, 2026)** | Hourly injury refresh runs extended from 6 PM PT cutoff to 10 PM PT. Seven new cron entries added (4 PM–10 PM PT). Covers all NBA tipoff windows (5 PM, 7 PM, 8 PM, 8:30 PM PT) and late-scratch window (~90 min post-tip). All schedule comments corrected from ET to PT. Root cause: late scratches announced after last scheduled refresh were leaving picks un-voided through tip-off. |
| **Team Momentum Indicator (March 11, 2026)** | `build_team_momentum()` in `quant.py` computes L10 W-L record, avg point margin, and hot/cold/neutral tag for all teams playing today from `nba_master.csv`; `team_momentum` field in `player_stats.json` with `{team: {...}, opponent: {...}}` structure; `Momentum —` annotation line in `build_quant_context()` between DvP line and stat lines; annotation only — no directive rules. |
| **M2 — Defensive Recency Split (March 12, 2026)** | `compute_opp_defense_recency()` added to `quant.py`; `def_recency` field in `player_stats.json`; `DEF↑`/`DEF↓` inline header annotation in analyst `build_quant_context()`; annotation only — no directive rules; validation gate at 30+ flagged instances. |
| **Analyst — three prompt rule tightenings (March 12, 2026)** | (1) REB pick value gate: "at or below" → "strictly less than" 3rd-lowest L10 value; exact match now forces step-down (motivated by Sengun REB miss: 3rd-lowest=6, pick=6, actual=2). (2) VOLATILE PTS skip extended to 8/10: condition now fires on 7/10 OR 8/10 at T15+; exception clause updated to "8/10 baseline" (motivated by Ingram PTS O15 ×3 in 8 days, twice at 8/10). (3) FG_COLD ≥15% mandatory tier step-down on T15+ PTS: severe FG_COLD no longer informational-only at high tiers; step to lower tier and re-qualify; `fg_cold_tier_step` skip_reason added for cases where step-down finds no qualifying tier (motivated by Flagg PTS O15 miss with FG_COLD:-18%). All prompt-only — no quant or schema changes. |
| **Auditor — Game Results Context Injection (March 12, 2026)** | Root cause addressed: auditor had no direct access to final game scores, forcing it to infer blowout context from ESPN news and Brave Search hits — both unreliable (Durant vs. Jokic HOU/DEN same-game miss asymmetry, March 11, 2026). Fix: `MASTER_CSV = DATA / "nba_master.csv"` path constant added; `load_game_results()` reads yesterday's completed rows, keys result dict by BOTH home and away team abbrev (O(1) lookup from either side), skips unparseable score rows, returns `{}` on any error; `build_game_results_block()` deduplicates via `seen` set, labels each game BLOWOUT (≥20 margin) / COMPETITIVE (10–19) / CLOSE (<10), sorts alphabetically, returns formatted block; `build_audit_prompt()` signature extended with `game_results_block: str = ""`; block injected between season context and playoff picture; STEP 0 — ESTABLISH GAME CONTEXT added as first step of PICK ANALYSIS TASK — auditor looks up each player's team in the game results block before analyzing any miss, ensuring shared game-script evidence is applied consistently across all players from the same game; existing STEP 1–6 numbering unchanged; `main()` wired with `game_results = load_game_results()` + `build_game_results_block(game_results)` + kwarg pass. `agents/auditor.py` only — no other files changed. |
