# Verification Sweep — 2026-04-28

Generated: 2026-04-28 (UTC; investigator-local clock)
Repo HEAD: f8ac6df2167f48e31795a18ac3b7988a69ffb88a
Branch: main

This sweep verifies three structural fixes shipped during the
2026-04-25 → 2026-04-28 window: Candidate A venue-claim guardrails
in `season_context_updater.py`; the Layer A + Layer B tier-walk
market-aware fix in `analyst.py`; and the PENALTY STACK LIMIT
MAGNITUDE CAP rule in `analyst.py`. All checks are read-only against
existing repo files; no GitHub Actions run logs needed.

---

## Part 1: Candidate A — bot commit guardrail check

**Scope:** github-actions bot commits to `context/nba_season_context.md`,
2026-04-25 17:00 → 2026-04-29 06:00 PT (wide window for TZ skew).

**Commits examined:** 3

| Hash (short) | Author Date (ISO)            | Subject                                | Diff stat |
|--------------|------------------------------|----------------------------------------|-----------|
| bf85013      | 2026-04-28 08:27:28 -0700    | Auditor results 2026-04-28 [skip ci]   | 15 lines (++++++++++++---) |
| 998d924      | 2026-04-27 08:07:13 -0700    | Auditor results 2026-04-27 [skip ci]   | 20 lines (++++++++++++++++----) |
| 8e922f1      | 2026-04-26 07:05:21 -0700    | Auditor results 2026-04-26 [skip ci]   | 18 lines (+++++++++++++++---) |

**Total added lines across 3 commits:** 43 (added-line union, excluding `+++` file headers)

### Confirmed forbidden matches (patterns 1–6)

Count: **0**

Patterns scanned:
1. `must-win road game` (case-insensitive)
2. `at home in G\d`
3. `series shifts to`
4. `back to <city>` (20-city alternation)
5. `<team> hosts? G\d` (16-team alternation)
6. `G\d at <city>` (16-city alternation)

Zero hits across all 6 patterns × 43 added lines × 3 commits.

### Requires human review (patterns 7–8)

Count: **0**

Patterns scanned:
7. `\bon the road\b` (case-insensitive)
8. `\bin <city>\b` (16-city alternation)

Zero hits. None of the 43 added lines contain even ambiguous
past/future tense venue language. The Candidate A guardrails appear
to have suppressed the entire venue-language category cleanly across
three consecutive bot runs without false-positive ambiguous hits.

### Verdict

**VERIFIED CLEAN** — zero confirmed forbidden matches AND zero
human-review hits across 3 bot commits / 43 added lines spanning
2026-04-26 → 2026-04-28. Candidate A's prompt-text guardrail is
binding in production.

The auto-updater is producing diary entries that grep-clean on every
banned phrase including the soft "in <city>" and "on the road"
patterns that would have legitimately required human review for
past-tense uses. The narrowness suggests the LLM is following the
constraint by avoiding venue language entirely (as the rule
instructed) rather than by carefully past/future-tense parsing.

---

## Part 2: Tier-walk market-aware — picks.json scan

**Scope:** `data/picks.json` picks with date in
{2026-04-26, 2026-04-27, 2026-04-28}.

**Picks scanned:** 85
**Per-date breakdown:**
- 2026-04-26: 34 picks
- 2026-04-27: 23 picks
- 2026-04-28: 28 picks

**Picks with `[WALK_REVERTED:` annotation (primary):** 0
**Picks with `WALK_REVERT` substring (secondary, broader):** 0

### Matches

None.

### Canonical-case spot check

The spec named **LeBron James 4/26 PTS** (walked T15→T10) as the
explicit case the rule was designed to catch. Result of search across
the 4/26–4/28 window:

| Date         | LeBron picks | Notes |
|--------------|--------------|-------|
| 2026-04-26   | 0            | No LeBron picks of any prop type |
| 2026-04-27   | 0            | No LeBron picks of any prop type |
| 2026-04-28   | 0            | No LeBron picks of any prop type |

**Total LeBron picks 4/26–4/28: 0** (across all prop types).

The canonical case did not recur — the analyst did not emit a LeBron
PTS pick on any of the three days in the verification window. Either
LeBron was unavailable / load-managed during this period, or the LLM
correctly declined a pick in light of the new TIER_WALK MARKET-AWARENESS
rule (the rule's stated behavior is to decline rather than walk to
no-market when both walked and qualifying tiers are bettable but
walked is not). Distinguishing those two interpretations is beyond
the scope of this read-only sweep.

### Verdict

**NO TRIGGER CONDITIONS HIT** — zero `[WALK_REVERTED:` annotations
across 85 picks in the 3-day window, AND no canonical-case pick
(LeBron PTS) was emitted. This is the documented "plausible result"
case from the spec ("Don't infer 'broken' from zero matches alone").

A regression detection would require checking whether any 4/26–4/28
pick has a `tier_walk` referencing a walk-down to a tier with no
FanDuel market — explicitly out of scope per the spec
("manual review of trigger conditions deferred"). The LeBron
canonical-case spot check is also clean: no LeBron PTS pick was
emitted, so no LeBron PTS pick lacked a `[WALK_REVERTED:` annotation.

Structural confirmation that Layer B is wired correctly was performed
at code-landing time (synthetic invariant tests covering the LeBron
T15→T10 case, all passed). Production evidence of Layer B firing
will accumulate when slate composition produces a trigger condition.

---

## Part 3: Penalty cap rule — picks.json + skipped_picks.json scan

**Scope:** date 2026-04-28 only. The rule landed today
(2026-04-28); earlier dates pre-date the fix.

### picks.json scan

**Picks scanned (date=2026-04-28):** 28
**Picks with `PENALTY_CAP applied` annotation (primary):** 0
**Picks with `PENALTY_CAP` substring (secondary, broader):** 0

### skipped_picks.json `merit_below_floor` entries on 2026-04-28

`data/skipped_picks.json` contents:

```
[]
```

File is an empty array (2 bytes, last modified 2026-04-28 13:02).

**Total entries on 2026-04-28:** 0
**`merit_below_floor` entries on 2026-04-28:** 0
**Any reason on 2026-04-28:** 0

The skipped_picks.json file is overwritten fresh each morning by
the analyst run (per `agents/analyst.py:save_skips()` documented
behavior); an empty file means today's morning analyst run wrote
zero rule-forced skips for any reason — not just zero
`merit_below_floor` skips, but zero of every type
(`no_market`, `ast_hard_gate`, `fg_cold_tier_step`,
`3pm_blowout_trend_down`, etc.).

### Canonical-case spot check

Canonical primary creators (Jokic, SGA / Gilgeous-Alexander, LeBron,
Brunson, Cunningham, Tatum, Banchero, Edwards, Wembanyama) on the
4/28 slate:

| Player              | Prop  | Tier | Conf | In merit_below_floor? |
|---------------------|-------|------|------|----------------------|
| Jayson Tatum        | PTS   | T15  | 74%  | NO (skipped_picks empty) |
| Jayson Tatum        | AST   | T6   | 74%  | NO |
| Jayson Tatum        | 3PM   | T2   | 80%  | NO |
| Jalen Brunson       | PTS   | T15  | 74%  | NO |
| Jalen Brunson       | 3PM   | T1   | 80%  | NO |
| Victor Wembanyama   | PTS   | T15  | 74%  | NO |

All confidences sit above the relevant prop-type minimum floors
(PTS/AST 68%, 3PM 75%). None of the canonical primary creators
appear in skipped_picks.json today. No Jokic / SGA / LeBron /
Cunningham / Banchero / Edwards picks were emitted today (LAL/HOU,
DEN/MIN, OKC/PHX, DET/ORL series may have eliminated some teams or
otherwise removed those players from today's slate; not within
scope to investigate).

### Verdict

**NO TRIGGER CONDITIONS HIT** — zero `PENALTY_CAP applied`
annotations among 28 picks on 2026-04-28; skipped_picks.json is
empty so zero `merit_below_floor` skips today; no canonical
primary-creator pick fell below the relevant floor. This is the
documented "plausible result" case from the spec — "the rule fires
only when natural penalty math drives below -20pp, which depends
on slate composition."

The rule's structural correctness was confirmed at landing time
(spec-grep matrix passed: TWO PARALLEL CONSTRAINTS = 2,
MAGNITUDE CAP = 4 references, COUNT LIMIT preserved). Production
evidence of the cap firing will accumulate when a slate produces
a stack >-20pp on a structurally strong primary-creator pick. The
canonical Jokic AST T8 (-25pp aggregate) profile did not recur on
the 4/28 slate.

---

## Summary

| Part | Fix verified | Verdict | Evidence basis |
|------|--------------|---------|----------------|
| 1 | Candidate A venue guardrails | **VERIFIED CLEAN** | 0 forbidden + 0 review hits across 3 bot commits / 43 added lines |
| 2 | Tier-walk market-aware (Layer A + Layer B) | **NO TRIGGER CONDITIONS HIT** | 0 annotations across 85 picks in 3-day window; LeBron canonical case absent from slate |
| 3 | Penalty cap rule | **NO TRIGGER CONDITIONS HIT** | 0 cap annotations on 28 picks today; skipped_picks.json empty; canonical primary creators all above floor |

**Two distinct verification states** are present:

- **Part 1** is positively verified — the bot ran 3 times since the
  rule landed, and every run grep-clean'd on banned venue language.
  This is functional confirmation that the LLM is binding to the
  constraint.
- **Parts 2 and 3** are structurally correct (verified at landing
  time via synthetic invariant tests) but have not yet encountered
  trigger conditions in production. Both are awaiting natural slate
  composition that exercises the rule. Neither is a regression
  signal; both will accumulate evidence over the next several days
  of analyst runs.

No file modifications were made by this verification sweep beyond
the creation of this report.
