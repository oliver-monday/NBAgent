---
name: nbagent-code-prompts
description: Writing implementation prompts for Claude Code in the NBAgent project. Use this skill whenever the session involves designing or writing a prompt to send to Claude Code — including new quant features, analyst prompt changes, ingest additions, backtest modes, or any multi-file implementation task. This skill captures the exact structure, tone, and discipline conventions that have produced clean, zero-regression Code implementations across this project.
---

# NBAgent — Writing Prompts for Claude Code

This skill governs how to write implementation prompts intended for Claude Code in the NBAgent
project. These prompts are handed off at session end (or mid-session) and executed autonomously
by Code with no human in the loop. The standard here is high: a well-written prompt produces a
clean implementation on the first pass. A poorly-written one creates silent bugs, scope creep, or
regressions in unrelated files.

---

## The Mental Model

Code is a capable but literal executor. It will do exactly what the prompt says — including
things the prompt implies but didn't intend. Your job when writing a Code prompt is to:

1. **Eliminate ambiguity** about what to change and where
2. **Pre-empt scope creep** by explicitly naming files that must NOT be touched
3. **Anchor Code in existing patterns** so it writes consistent code, not idiomatic rewrites
4. **Give Code enough context to reason** about why, not just what — this prevents well-meaning
   "improvements" that break downstream consumers

Think of it as writing a contract, not a wish list.

---

## Prompt Anatomy

Every Code prompt for NBAgent should have these sections, in this order:

### 1. Title + One-Paragraph Context

```markdown
# [Feature Category]: [Feature Name]

You are working in the NBAgent repo. This task [does X] in [file(s)].

[1–3 sentences: why this feature exists, what problem it solves, what it connects to.]
```

**Rules:**
- Start with "You are working in the NBAgent repo." — grounds Code in project context
- State the motivation, not just the mechanic. Code that understands *why* makes better
  micro-decisions when the prompt is ambiguous on a detail
- If the feature has downstream consumers already waiting for it, name them explicitly here.
  This prevents Code from "helpfully" stubbing them out incorrectly.

**Example (from miss_anatomy_quant_only.md):**
```
You are working in the NBAgent repo. This task extends the existing `bounce_back` profiles in
`quant.py` to classify the severity of each player's historical misses...

These fields are needed by two downstream consumers:
1. Player Profiles (`build_player_profiles()`) — already implemented and waiting for these fields.
2. Future backtest — a `--mode miss-anatomy` backtest will validate the signal separately.

**Scope: `agents/quant.py` only.** Do NOT touch `agents/analyst.py` in this task.
```

Note: scope declaration belongs in the opening paragraph, not buried later.

---

### 2. Context Block (when modifying existing code)

Before any implementation instructions, tell Code what already exists:

```markdown
## Context

`build_bounce_back_profiles()` in `quant.py` already computes: `post_miss_hit_rate`, `lift`,
`iron_floor`, `n_misses`. These live in `player_stats.json` under `bounce_back["PTS"]`.

The three new fields slot into the same per-stat dict — no schema restructuring needed.
```

**Rules:**
- List the exact existing field names, function names, and dict keys
- State the insertion pattern ("slot into same dict", "add after existing line X", etc.)
- If the existing function has non-obvious behavior (sort order, DNP handling, window size),
  call it out explicitly — Code will not re-read the whole function unless told to

---

### 3. Implementation Parts (one section per file, one sub-section per edit)

Structure each file as `## Part N: \`path/to/file.py\` — what you're doing`.

Within each part, be surgical:

```markdown
## Part 1: `agents/quant.py` — extend `build_bounce_back_profiles()`

Read the existing function carefully before editing. Make only the additions described below.

### After the existing line:
\```python
hits = (values >= best_t).astype(int).tolist()
\```

Add:
\```python
shortfalls = [max(0.0, float(best_t) - float(v)) for v in values]
\```
```

**Rules for implementation sections:**

- **Quote the exact existing line(s) to anchor the insertion point.** Never say "near line 432"
  alone — line numbers drift. Always pair with a code snippet. Use both: "around line 432" +
  the exact code. Code will find the snippet even if the line number is off.

- **Show the complete new code block, not a description of it.** If Code has to infer the
  implementation from your description, it will — and it might infer wrong.

- **State the sort order of DataFrames explicitly.** In NBAgent, `grp` is always sorted
  newest→oldest. This is non-obvious and silently corrupts results if Code assumes ascending.
  Whenever you're passing a DataFrame to a new function, state the sort direction.

- **DNP handling: always explicit.** The pattern `df[df["dnp"] != "1"]` is easy to forget.
  Any new function that touches `player_game_log` data must be told explicitly to exclude DNPs
  and how (string comparison `"1"`, not int).

- **For dict additions, show the surrounding context:**
  ```python
  "avg_minutes_last5": avg_minutes_last5,
  "minutes_floor":     minutes_floor,      # ← ADD THIS LINE
  "raw_avgs":          raw_avgs,
  ```
  This prevents Code from appending to the wrong dict or inserting at the wrong position.

- **For prompt text additions** (in `build_prompt()`), provide the exact block verbatim in a
  code fence. Do not paraphrase what the rule should say — write the rule itself. The Analyst
  reads this text and reasons from it; imprecise language produces imprecise reasoning.

- **For `build_quant_context()` annotation additions**, show the before/after of the annotation
  string construction and an example of what the output line should look like:
  ```
  Jalen Brunson (vs BOS | spread_abs=5.5 rest=1d L7:4g min_floor=29.4(avg=34.1)):
  ```

---

### 4. What NOT To Do

This section is not optional. It is the most important defensive layer in the prompt.

```markdown
## What NOT to do

- Do NOT touch `agents/analyst.py` — no annotations, no prompt rules in this task
- Do NOT touch `agents/auditor.py`, `agents/parlay.py`, `agents/backtest.py`
- Do NOT modify any `.yml` workflow files
- Do NOT rename or remove the existing `n_misses` field — Player Profiles reads it
```

**Rules:**
- List every file that is in-scope but should only be touched as specified
- List every file that is out-of-scope entirely
- Explicitly call out field names or function signatures that must not be changed,
  especially when they have downstream consumers (auditor, parlay, site builder)
- Always include: **Do NOT modify any `.yml` workflow files** — Code sometimes "helpfully"
  updates workflows when it sees a new data file being written

**Common NBAgent-specific NOT-TO-DO items:**
- `.yml` files: never touch unless the prompt is specifically about workflow changes
- `build_site.py`: never touch unless the prompt is about frontend
- `auditor.py`: never touch unless the prompt is about audit logic
- `backtest.py`: never touch unless the prompt is about adding a backtest mode
- Existing field names in `player_stats.json` that feed downstream consumers
- `load_player_log()` in quant — the schema is settled; don't modify unless ingest changed

---

### 5. Verification

Tell Code how to confirm the implementation is correct. This serves two purposes: it gives
Code a self-check before calling the task done, and it gives you a checklist when reviewing.

```markdown
## Verification

After Code runs, trigger a manual quant run. In `data/player_stats.json`, find a player
with ≥5 misses at their best PTS tier and confirm:

1. `bounce_back["PTS"]` contains `near_miss_rate`, `blowup_rate`, `typical_miss`
2. `near_miss_rate + blowup_rate == 1.0` exactly (they partition all misses)
3. `typical_miss` is a positive float, typical range 1.0–6.0
4. Players with < 5 misses show `null` for all three fields (graceful)
```

**Rules:**
- Include at least one mathematical/logical invariant that Code can check deterministically
  (e.g., "near_miss_rate + blowup_rate must == 1.0", "floor_minutes must be ≤ avg_minutes")
- Include expected value ranges for new numeric fields — this catches off-by-one errors
  in window computations or unit mismatches
- If the feature has a "graceful null" pattern (returns None when sample is too small),
  verify it explicitly
- If the feature produces output visible in the analyst prompt, include an example of
  what the formatted output line should look like

---

### 6. Docs Update

Every prompt must include a final step instructing Code to update relevant `/docs` files
to reflect what was just implemented. This is the last step after all verification checks
pass — not optional.

```markdown
## Docs Update

After verification passes, update the following docs to reflect this implementation:

- `docs/ROADMAP_active.md` — if the item was in the active queue, move it to Resolved by
  adding a pointer entry ("see ROADMAP_resolved.md") and removing the full entry. If it's
  a new open item, add it here.
- `docs/ROADMAP_resolved.md` — add a new Resolved entry with implementation date and a
  one-line summary of what was done.
- `docs/SESSION_CONTEXT.md` — update any affected schema descriptions, function
  signatures, or "what's live vs. pending" state. If a new field was added to
  `player_stats.json` or `picks.json`, update the schema tables.
- `docs/AGENTS.md` — if agent logic, config, or output schemas changed, update the
  relevant section.
- `docs/DATA.md` — if any CSV or JSON schema changed (new fields, new files), update
  the schema documentation.
- `CLAUDE.md` — only if the repo structure, workflow chain, or agent config table
  changed materially (new file, new agent, new workflow).
- `README.md` — only if user-facing setup or usage instructions changed.
```

**Rules:**
- Always update `ROADMAP_active.md` / `ROADMAP_resolved.md` and `SESSION_CONTEXT.md` — these are the two most
  critical for future session continuity.
- Only update `AGENTS.md`, `DATA.md`, `CLAUDE.md`, `README.md` when those docs are
  actually affected. Do not make cosmetic edits.
- Docs updates are part of the implementation, not a post-implementation courtesy.
  A prompt that ships code without updating docs is incomplete.

---

### 7. File Summary Table

End every prompt with a clean table:

```markdown
## File summary

| File | Action |
|------|--------|
| `agents/quant.py` | Add `compute_minutes_floor()`, wire into `build_player_stats()` |
| `agents/analyst.py` | Add `min_floor_str` to player header, add prompt rule in KEY RULES |
| `agents/analyst.py` | **DO NOT TOUCH** |
```

Note: listing "DO NOT TOUCH" explicitly in the table is intentional — it's a final reminder
at the point where Code is about to start editing.

---

## Scope Discipline

The biggest source of implementation problems in NBAgent is scope creep — Code making
"sensible" changes to files that weren't part of the task. The fix is explicit scope
declaration at three levels:

### At the top of the prompt (most important):
```
**Scope: `agents/quant.py` only.**
```
or
```
This task touches `agents/quant.py` and `agents/analyst.py` only.
```

### In the What NOT To Do section:
List every out-of-scope file explicitly, even obvious ones.

### In the File Summary table:
Make DO NOT TOUCH entries visible at the end.

**The canonical NBAgent out-of-scope files** (include whenever relevant):
- `agents/auditor.py` — unless task is about audit logic
- `agents/parlay.py` — unless task is about parlay logic
- `agents/backtest.py` — unless task is adding a backtest mode
- `agents/build_site.py` — unless task is about frontend
- `agents/lineup_watch.py` — unless task is about injury processing
- `ingest/espn_daily_ingest.py` — unless task is about game-level data ingest
- `ingest/espn_player_ingest.py` — unless task is about player box score ingest
- `ingest/rotowire_injuries_only.py` — unless task is about injury scraping
- `.github/workflows/*.yml` — **never touch** without explicit prompt instruction
- `context/nba_season_context.md` — human-maintained; Code should not edit

---

## NBAgent-Specific Patterns to Always Include

These are gotchas that have bitten the project before. Include them in any prompt that
touches the relevant code:

### DNP Exclusion
Any function that reads `player_game_log.csv` data must exclude DNP rows.
Always specify: `df[df["dnp"] != "1"]` (string, not int).

### DataFrame Sort Direction
`grp` in `build_player_stats()` is sorted **newest→oldest** (`ascending=False`).
If a new function uses `.head(N)` to get recent games, it's getting the N most recent.
If a new function uses `.tail(N)`, it's getting the oldest. State this explicitly.

### Graceful Null Pattern
All new computed fields should return `None` when sample size is below minimum,
matching the existing pattern. Never return `0` or `{}` when data is insufficient —
downstream consumers check `if field is not None` to gate rendering.

### player_stats.json Field Ordering
New fields should be added in a logical position relative to related fields.
Include the surrounding dict keys in the prompt to anchor the insertion point.
The auditor's `load_player_stats_for_audit()` slims entries to 9 fields — if you're
adding a field that the auditor needs, say so explicitly.

### Prompt Rule Placement
`build_prompt()` has a fixed section order documented in `SESSION_CONTEXT.md`.
Always specify which named block (e.g., `KEY RULES — REST & FATIGUE`) the new
sub-rule belongs to, and whether it goes at the start or end of that block.

### Analyst Annotation String Construction
In `build_quant_context()`, annotation strings are built by concatenating field strings
(`bb_field`, `vol_tag`, `trend_field`, etc.) into a stat line. New annotations must:
- Use a leading space if appending to an existing string
- Be `""` (empty string, not None) when the condition doesn't apply
- Follow the existing `if X is not None: ... else: ""` guard pattern

---

## Deciding What to Write vs. What to Leave to Code

**Write the full implementation code when:**
- The logic is non-trivial (median computation, percentile, conditional branching)
- The insertion point is inside a complex existing loop
- The output format must exactly match an existing pattern (annotation strings, JSON keys)
- Getting it wrong would silently corrupt existing data (hit rate computations, DNP handling)

**Write pseudocode or a description when:**
- The logic is a simple dict extension or string append
- Code has clear analogous patterns to follow (e.g., "same pattern as `compute_rest_context()`")
- You've already shown the exact insertion point with surrounding code

**Never:**
- Say "implement as you see fit" for anything touching `player_stats.json` schema or
  `build_prompt()` content — these have exact downstream expectations

---

## Multi-Part Prompts

When a feature spans multiple files with sequential dependencies, structure the prompt
so Code implements in dependency order:

1. Data computation (quant.py compute function)
2. Data wiring (quant.py `build_player_stats()` dict entry)
3. Context rendering (analyst.py `build_quant_context()` annotation)
4. Prompt rule (analyst.py `build_prompt()` KEY RULES block)

Never skip steps or combine non-adjacent layers — Code can lose track of the full chain.

If a task is large (4+ files, 100+ lines of new code), consider splitting into two prompts
with a clear handoff note: "Part 2 depends on Part 1 landing first."

---

## Deferred Scope Pattern

When a feature has components that require validation before shipping (e.g., a directive
prompt rule that should be backtested first), split the prompt explicitly:

**Prompt A — Data only:**
```
Scope: `agents/quant.py` only. Do NOT touch `agents/analyst.py`.
The fields write to `player_stats.json` silently. Analyst-facing changes are a
separate future prompt pending backtest validation.
```

**Prompt B — Analyst wiring (written later):**
```
Prerequisite: Miss Anatomy quant fields are live in `player_stats.json`.
This prompt adds the annotation and prompt rule to `agents/analyst.py`.
```

This prevents Code from anticipating the "obvious next step" and wiring the analyst
changes before the signal has been validated.

---

## Output Format

Every Code prompt must be saved and delivered as a `.md` file (e.g., `rotowire_projected_minutes.md`). Do not paste prompts inline into the chat as the sole deliverable. Writing to a file ensures the prompt is downloadable for local archiving, referenceable by name in future sessions, and cleanly separated from session discussion.

---

## Quality Checklist Before Sending

Before handing a prompt to Code, verify:

- [ ] Opening paragraph states the repo, the files in scope, and the motivation
- [ ] Downstream consumers of any new fields are named
- [ ] Every insertion point is anchored by exact existing code, not line number alone
- [ ] DNP handling is specified for any new function reading game log data
- [ ] DataFrame sort direction is stated for any new function using `.head()` / `.tail()`
- [ ] Graceful null pattern is specified for any new computed field
- [ ] Prompt rule text (if any) is written verbatim, not described
- [ ] Example output is shown for any new annotation string
- [ ] "What NOT to do" section covers all out-of-scope files
- [ ] `.yml` files are explicitly excluded
- [ ] Verification section has at least one mathematical invariant
- [ ] File summary table is present and accurate
- [ ] If directive signal: backtest-first decision is documented
- [ ] Docs Update section is present with ROADMAP_active.md / ROADMAP_resolved.md and SESSION_CONTEXT.md as mandatory targets

---

## Reference Examples

The following prompts in the project files are canonical examples of this standard:

| Prompt | Why it's a good reference |
|--------|--------------------------|
| `minutes_floor_prompt.md` | Clean 4-part structure, exact insertion anchors, graceful null, verification with invariant |
| `miss_anatomy_quant_only.md` | Deferred scope pattern, downstream consumer declaration, explicit DO NOT TOUCH |
| `h11_production_wiring.md` | Multi-file prompt with correct dependency order (quant → analyst annotation → prompt rule) |
