# NBAgent — Playoff Readiness Roadmap

**Created:** 2026-04-12
**Status:** Canonical reference — synthesized and aligned from two independent analysis passes (Claude Code session + Claude Chat session) against the full system state after the 4/11-4/12 development sprint. Both analyses converged on the same core thesis with complementary implementation ideas. This document merges all items from both, organized for efficient stepwise execution.

**Window:** April 13–17 (gap + Play-In) → April 18 (R1 Game 1)

---

## Core Thesis

**Playoffs are a repeated game, not a random draw. The system is optimized for the latter.**

The entire quant pipeline — L20 windows, team defense ratings averaged over 15 games, trend computed against a diverse opponent schedule — works brilliantly for 82 games against 29 opponents. In a 7-game series against one opponent with continuous film study, three things change:

1. **Defensive adaptation compounds game-over-game.** Game 1 base scheme → Game 4 face-guarding. Regular-season H2H splits (2-4 meetings months apart) capture none of this.
2. **Minutes variance collapses.** Star players go from 32-36 min (with rest/blowout noise) to 38-42 min with near-zero variance. The system's conservative confidence estimates bake in minutes uncertainty that no longer exists.
3. **The opponent distribution narrows from 29 to 1.** Tier hit rates computed against a mixed schedule overstate reliability against a single elite defense that has days to prepare.

**Expected impact:** Hit rate drops 5-8pp in the first playoff week. This is structural, not a system failure. The goal is to recognize it, adapt quickly, and avoid compounding the miss by over-trusting regular-season calibration.

---

## Priority 1 — Ship Before R1 Tips (April 13–17)

### P1.1: Per-Player Calibration Wiring (H29 → Odds Layer)
**Impact: Highest dollar-value improvement available. Data ready.**
**Scope:** `ingest/odds_today.py` only
**Depends on:** `data/backtest_confidence_calibration.json` (exists)

The system is ~10pp under-confident at the population level, but the distribution is wildly uneven: Banchero is 19.5pp under-confident (95.7% actual vs 76.2% stated), Mitchell is 10.4pp over-confident (65.2% actual vs 75.6% stated). The odds layer currently uses population-level calibration bands (`70-75: 0.851`, etc.). Feeding per-player H29 data into `_get_calibrated_prob()` would:
- Increase Kelly sizing on systematically under-rated players (larger bets where edge is real)
- Decrease sizing on over-rated players (smaller bets where edge is illusory)
- Directly improve ROI without changing a single pick

Implementation: `_get_calibrated_prob()` gains a player-name parameter, reads per-player actual rates from the H29 JSON, falls back to population band when player has <10 graded picks. Low risk — falls back cleanly to existing behavior for unknown players. Reversible by removing the override.

---

### P1.2: Playoff Blowout Rule Relaxation
**Impact: Prevents systematic under-confidence on playoff stars.**
**Scope:** `agents/analyst.py` only (prompt text, date-gated)

Regular-season blowout rules were calibrated against tanking teams and load management. On 4/12 (final regular season day), 21 of 35 picks hit the 74% blowout cap. In playoffs, a -7 favorite plays starters 42 minutes — the blowout scenario that motivates the cap (starters benched Q4) almost never materializes. Playoff spreads cluster 3-7 points where blowout risk is structurally lower.

Implementation: date-gated `## PLAYOFF BLOWOUT ADJUSTMENT` block in both analyst prompts, gated on `>= PLAYOFFS_R1_DATE`. Raises blowout `spread_abs` thresholds by +3 points (secondary scorer skip fires at ≥16.5 instead of ≥13.5; 74% cap fires at ≥18 instead of ≥15). Reduces penalty magnitude from -10% to -5%. No backtest needed — the rationale is structural. Reversible after R1 if results don't support it.

---

### P1.3: Series Diary in Season Context (Zero Engineering)
**Impact: Highest-value qualitative upgrade. Zero code changes.**
**Scope:** Manual edits to `context/nba_season_context.md`

After each playoff game, Oliver adds 3-4 lines under a per-series header:

```markdown
### PLAYOFF SERIES DIARIES — R1

#### DEN vs MIN
G1 (Apr 18): Jokic 31/14/9, dominated interior. MIN doubled from weak side — Murray 14 pts.
  Ant held to 18 on 6/19 — DEN switching scheme neutralized drives.
  → G2 expect: continued Murray usage if MIN keeps doubling Jokic.

G2 (Apr 20): ...
```

The analyst reads `nba_season_context.md` every morning. This is the qualitative layer that captures within-series defensive adaptation — coaching adjustments, scheme evolution, face-guarding patterns — that no quant pipeline can model. Oliver's NBA domain knowledge is the system's most underutilized input; the context file is the delivery mechanism. The key insight: within-series defensive adaptation is the biggest unmodeled signal, and the human expert is the only sensor for it.

---

### P1.4: Game-in-Series Confidence Modifier (H31 Activation)
**Impact: Most playoff-specific signal available. Data ready, sitting unused.**
**Scope:** `agents/playoff_matchup.py` + `agents/analyst.py` (prompt rule, date-gated)
**Depends on:** Oliver populating `data/playoff_bracket.json` with series results after each game

H31 gives per-player series progression deltas — Harden fades -33pp in Games 5-7, SGA rises +8pp, Kawhi rises +20pp. The Playoff Matchup Agent already computes series state. Wire them together:

- Enrich `playoff_matchup.py` output with `game_in_series` per matchup
- Add prompt rules in both analyst prompts:
  - LATE_FADER players in Games 5-7: apply -5% confidence penalty
  - LATE_RISER players in Games 5-7: apply +3% confidence bonus
  - STABLE players: no adjustment

Small, testable, reversible. Only fires in Games 5+ so it doesn't affect R1 Games 1-4 — gives time to validate before it matters.

---

### P1.5: Playoff Calibration Early Warning System
**Impact: Safety net for regime change. Prevents flying blind.**
**Scope:** `agents/auditor.py` — addition to `save_audit_summary()`

The system has never run during actual playoffs. Add a lightweight check: after the first 3 days of playoff picks are graded, compute playoff-specific hit rate by confidence band. If playoff picks in the 76-80% band are hitting at <75% instead of 88%, that's a regime change that demands attention.

Implementation: `playoff_calibration_check()` in `auditor.py`, date-gated to `>= PLAYOFFS_R1_DATE`. Computes playoff-only calibration when `season_type == 3` picks exist. Prints `[PLAYOFF CALIBRATION WARNING]` to stdout and surfaces as a `recommendations` entry in `audit_log.json` when divergence exceeds 10pp from stated band. Purely diagnostic — no automatic rule changes. The audit loop is designed for exactly this; give it the right question to answer.

---

## Priority 2 — Ship During R1 (April 18–25)

### P2.1: Star Minutes Certainty Boost
**Impact: Corrects systematic under-confidence on star playoff props.**
**Scope:** `agents/analyst.py` prompt rule, date-gated

The regular-season confidence model bakes in minutes variance (rest games, blowouts, load management). In playoffs, that variance disappears for starters. H30 quantifies the magnitude: PTS T20 is +26pp from normal (30-34 min) to extended (38+). Playoff stars live in the extended bucket permanently.

Implementation: prompt rule in analyst: "In playoff games, star players (raw_avgs PTS ≥ 22) have near-guaranteed 38+ minutes. If the primary source of uncertainty in your tier_walk is minutes/role, increase confidence by 3-5%." Annotation-only initially; can become mechanical after R1 validation.

---

### P2.2: CLV Retrospective — "What Did the Market Know?"
**Impact: Identifies blind spots in the system's information diet.**
**Scope:** Manual analysis first, then `agents/auditor.py` if pattern emerges

CLV data is accumulating on every pick. The most valuable use isn't aggregate beat-close rates — it's identifying which specific picks had the market moving hardest against them, and correlating with outcomes. A pick where `morning_implied_prob` was 82% and pretip dropped to 72% that then MISSED — what information channel was the market pricing?

First pass is manual: after 2-3 playoff days, Oliver reviews CLV outliers (biggest negative moves) against miss outcomes. If a pattern emerges (e.g., market consistently knew about minutes restrictions before the system), build a systematic filter. Could evolve into automated `market_disagreement_miss` tagging in the auditor.

---

### P2.3: Same-Game Parlay Variance Penalty
**Impact: Protects against correlated parlay collapse in playoff context.**
**Scope:** `agents/parlay.py` — `score_combination()` only

Game-script correlation is unmodeled. A 4-leg parlay with 3 legs from the same game has massive correlated downside — if that game becomes a blowout, 3 of 4 legs fail simultaneously regardless of individual pick quality. H33 captures teammate stat correlation but not the correlated downside of game-script concentration.

Implementation: add `-0.05` per leg beyond 2 from the same game in `score_combination()`. A 4-leg parlay with 3 same-game legs gets -0.05 penalty; with 4 same-game legs gets -0.10. Pushes toward multi-game diversification without blocking same-game stacks. The `n_games` field and game-spread bonus already exist in scoring; this extends the principle.

---

## Priority 3 — Evaluate After First Playoff Week (April 25+)

### P3.1: Tier Walk Reasoning Quality Audit
**Impact: Identifies systematic LLM reasoning errors invisible to backtests.**

800+ tier_walks with graded outcomes exist. The backtest suite tests quant signal quality, but nobody has tested analyst reasoning quality. Questions: Does the analyst correctly apply penalty stacks when 3+ co-occur? When it cites iron_floor, do those picks actually hit more often? When the tier_walk mentions "bounce-back" as positive evidence, is it applying that correctly given H21's slump-persistent verdict?

Mining tier_walk text against outcomes identifies the gap between "correct quant signal" and "correct LLM application of that signal." Could be a new backtest mode or standalone script.

---

### P3.2: Per-Player Playoff Recalibration
**Impact: Refines P1.1 calibration for playoff regime.**

After 20+ playoff picks per player accumulate, compute playoff-specific calibration deltas. Some players' regular-season calibration will transfer cleanly (STABLE players per H28/H31), others won't. A player who was 19.5pp under-confident in the regular season might be perfectly calibrated in playoffs where their "true" rate is lower due to tougher competition.

Extension of H29 backtest mode for playoff-only data. Realistically available after the conference semifinals (late May).

---

### P3.3: Frontend — Real-Time Feel
**Impact: Makes the site feel alive for the friends-and-family audience.**

Add a "games in progress" indicator to the Picks tab header, updated each site rebuild (every 30 min via injuries.yml). Show how many of today's games have started vs finished, and aggregate pick status (X of Y legs resolved). Biggest UX gap between NBAgent and commercial apps — picks sit with `result=null` all day until the next morning's auditor.

Scope: `agents/build_site.py` only. Reads game times from `nba_master.csv` and current time.

---

### P3.4: Friends-and-Family Hero Card
**Impact: Makes the site immediately useful to casual visitors.**

A single prominent card at the very top of the Picks tab: "Today's Best: [Player] [Prop] [Tier] — [one-sentence why]" with a confidence ring and American odds. Targets the friend who opens the URL and needs one answer in 5 seconds. The Top Picks + Bold Card + Best Bets sections serve informed users; the hero card serves everyone else.

Scope: `agents/build_site.py` — reads existing `top_pick=True` + `edge_tier=STRONG` data. Pure frontend.

---

### P3.5: System Streak Persistence Signal
**Impact: Unknown until measured — could improve parlay bold card sizing.**

If NBAgent has hit 14 of its last 15 picks, is that persistence-positive (continue aggressive) or mean-reverting (pull back)? Audit data can answer this. If hot streaks are persistence-positive, the parlay engine could size the bold card more aggressively. If mean-reverting, the reverse. Needs analysis first, then implementation.

---

## Execution Plan — April 13–17

| Day | Item | Engineering | Notes |
|-----|------|-------------|-------|
| Apr 13 | P1.1 (H29 calibration wiring) | Code prompt → `odds_today.py` | Highest ROI item. Data ready. |
| Apr 13 | P1.3 (Series diary template) | Manual | Add empty template to `nba_season_context.md` |
| Apr 13 | Playoff bracket + context overhaul | Manual | `playoff_bracket.json`, whitelist, season context |
| Apr 13 | H15/H16/H24/H25 backtests | Code prompts | Run against full regular-season dataset |
| Apr 14 | P1.2 (Blowout relaxation) | Code prompt → `analyst.py` | Date-gated, prompt-only |
| Apr 14 | P1.5 (Calibration early warning) | Code prompt → `auditor.py` | Diagnostic only |
| Apr 15-17 | P1.4 (Game-in-series modifier) | Code prompt → `playoff_matchup.py` + `analyst.py` | Depends on bracket being populated |
| Apr 15-17 | P2.3 (SGP variance penalty) | Code prompt → `parlay.py` | Can ship early if time permits |

---

## The Overarching Principle

The system's quantitative backbone (87% hit rate, H33 cannibalization, odds integration, playoff career splits) is a genuine competitive advantage. The playoff gap is **contextual intelligence about the specific series being played** — and that's where the human-in-the-loop adds the most value.

The series diary (P1.3) is arguably the single most important item on this list despite requiring zero engineering. Everything else is systematic refinement of known signals. The diary is new information that no quant pipeline can produce. Oliver's NBA domain knowledge, applied daily through the season context file, is the highest-leverage playoff input the system has access to.

**Trust the audit loop.** The first 10-15 playoff picks are the recalibration dataset. Make picks normally, grade them, read the miss patterns, adjust. The system is built for exactly this feedback cycle.

**Success metric for R1:** If the system maintains ≥80% hit rate through the first round (vs 87% regular season), the calibration held well enough. If it drops below 75%, the P1.5 early warning should fire and P2 adjustments should be accelerated. Track per-series, not aggregate — a 60% rate against one elite defense and 90% against another is more informative than a blended 75%.
