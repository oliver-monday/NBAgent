# Season Context Updater — Forward-Venue Hallucination Investigation
Generated: 2026-04-25 (UTC; investigator-local clock)
Investigator: Claude Code

This report follows up on `data/home_away_root_cause_investigation.md`
(2026-04-25) by looking upstream at `agents/season_context_updater.py`
— the auto-generative agent that runs in `auditor.yml` after
`auditor.py` and produces playoff diary entries appended into
`context/nba_season_context.md`. The motivating question: was the
DEN-MIN G3 paragraph (the one with two factually wrong forward-venue
claims) auto-generated, and if so does the auto-updater systematically
invite forward-venue hallucinations? All findings are read-only quotes
from production source files and committed git history; no code or
context was modified.

---

## 1. Auto-update commit attribution

`git log --since="2026-04-18" --pretty=format:"%h | %ai | %an | %s" -- context/nba_season_context.md`:

```
89cf4d8 | 2026-04-25 11:10:54 -0700 | oliver-monday          | Season Context: Fix
c711fbf | 2026-04-25 07:04:05 -0700 | github-actions[bot]    | Auditor results 2026-04-25 [skip ci]
d58707f | 2026-04-24 20:30:27 -0700 | oliver-monday          | Strip Parlay Grading from Auditor + Frontend
aaf809f | 2026-04-24 07:34:08 -0700 | github-actions[bot]    | Auditor results 2026-04-24 [skip ci]
cb540ef | 2026-04-23 12:35:35 -0700 | oliver-monday          | Parlay agent rebuild debug
febe859 | 2026-04-23 08:12:42 -0700 | github-actions[bot]    | Auditor results 2026-04-23 [skip ci]
7dc6e2b | 2026-04-22 07:46:38 -0700 | github-actions[bot]    | Auditor results 2026-04-22 [skip ci]
b1695c1 | 2026-04-21 11:08:51 -0700 | oliver-monday          | season context update
5fd7b4a | 2026-04-20 15:59:13 -0700 | oliver-monday          | nba_season_context Update
9efa02e | 2026-04-19 14:09:19 -0700 | oliver-monday          | nba season context update
```

Per-bot-commit content map (from `git show --stat <hash>`):

| Commit | Date | Author | Series modified | Auto-update or manual? |
|---|---|---|---|---|
| 9efa02e | 2026-04-19 | oliver-monday | n/a — pre-G1 manual setup | manual |
| 5fd7b4a | 2026-04-20 | oliver-monday | n/a — manual | manual |
| b1695c1 | 2026-04-21 | oliver-monday | n/a — manual | manual |
| **7dc6e2b** | **2026-04-22** | **github-actions[bot]** | BOS-PHI G2, LAL-HOU G2, SAS-POR G2 | **AUTO** (commit message ends `[skip ci]`, author is bot) |
| **febe859** | **2026-04-23** | **github-actions[bot]** | DET-ORL G2, OKC-PHX G2 | **AUTO** |
| cb540ef | 2026-04-23 | oliver-monday | other (parlay rebuild) | manual |
| **aaf809f** | **2026-04-24** | **github-actions[bot]** | NYK-ATL G3, CLE-TOR G3, DEN-MIN G3 | **AUTO** ⚠ (DEN-MIN smoking gun) |
| d58707f | 2026-04-24 | oliver-monday | other | manual |
| **c711fbf** | **2026-04-25** | **github-actions[bot]** | BOS-PHI G3, LAL-HOU G3, SAS-POR G3 | **AUTO** |
| 89cf4d8 | 2026-04-25 | oliver-monday | DEN-MIN G3 prose correction | manual (Fix #1) |

Four bot commits since `PLAYOFFS_R1_DATE = 2026-04-18`. Each adds
diary entries for the one-game-prior playoff date. Total auto-generated
diary entries: **11** (3 + 2 + 3 + 3). The smoking gun DEN-MIN G3
paragraph is in commit `aaf809f` (2026-04-24 bot run, processing the
2026-04-23 game).

---

## 2. Diary entries written by the auto-updater

Per-commit, per-series, per-game with first 80 chars + char length:

| Run date | Series | Game # | First 80 chars | Char length |
|---|---|---|---|---|
| 2026-04-22 | BOS-PHI | G2 | `**Game 2 (Apr 21) — PHI 111, BOS 97 \| Series tied 1-1 — PHI STEALS ONE AT TD GA` | 1131 |
| 2026-04-22 | LAL-HOU | G2 | `**Game 2 (Apr 21) — LAL 101, HOU 94 \| LAL leads 2-0**` | 1078 |
| 2026-04-22 | SAS-POR | G2 | `**Game 2 (Apr 21) — POR 106, SAS 103 \| Series tied 1-1 — MAJOR UPSET (home spr` | 1144 |
| 2026-04-23 | DET-ORL | G2 | `**Game 2 (Apr 22) — DET 98, ORL 83 \| Series tied 1-1 — DET RECLAIMS HOME COURT` | 1252 |
| 2026-04-23 | OKC-PHX | G2 | `**Game 2 (Apr 22) — OKC 120, PHX 107 \| OKC leads 2-0 — JALEN WILLIAMS INJURY C` | 1448 |
| 2026-04-24 | NYK-ATL | G3 | `**Game 3 (Apr 23) — ATL 109, NYK 108 \| ATL leads 2-1 — ANOTHER ONE-POINT ATL W` | 1483 |
| 2026-04-24 | CLE-TOR | G3 | `**Game 3 (Apr 23) — TOR 126, CLE 104 \| CLE leads 2-1 — TOR RESPONDS AT HOME (m` | 1372 |
| **2026-04-24** | **DEN-MIN** | **G3** | `**Game 3 (Apr 23) — MIN 113, DEN 96 \| MIN leads 2-1 — MIN TAKES SERIES LEAD AT` | **1591** |
| 2026-04-25 | BOS-PHI | G3 | `**Game 3 (Apr 24) — BOS 108, PHI 100 \| BOS leads 2-1 — BOS WINS IN PHILLY**` | 1471 |
| 2026-04-25 | LAL-HOU | G3 | `**Game 3 (Apr 24) — LAL 112, HOU 108 \| LAL leads 3-0 — OT (Durant DNP)**` | 1411 |
| 2026-04-25 | SAS-POR | G3 | `**Game 3 (Apr 24) — SAS 120, POR 108 \| SAS leads 2-1 — SAS RECLAIMS SERIES LEA` | 1471 |

11 entries total. Average length ~1350 chars (3–5 substantial lines as
the DIARY ENTRY GUIDELINES specify). Consistent with auto-generation —
all hit the same length envelope.

The full text of each entry is too long to paste in the report; it
lives in `context/nba_season_context.md` (lines 121–509). For analysis
purposes, the relevant portion is each entry's "G(N+1) key:" closing
sentence — examined in Section 3.

---

## 3. Forward-venue claim sweep

For each diary entry, scanned for phrases asserting where an upcoming
(or just-completed) game was/will be played. Truth derived from
2-2-1-1-1 format: G1+G2+G5+G7 at higher seed (lower bracket number),
G3+G4+G6 at lower seed.

Bracket seedings from headings: (1) DET vs (8) ORL, (2) BOS vs (7) PHI,
(2) SAS vs (7) POR, (3) NYK vs (6) ATL, (3) DEN vs (6) MIN, (4) CLE vs
(5) TOR, (4) LAL vs (5) HOU, (1) OKC vs (8) PHX. Higher seed = first
listed in each.

| Run | Series | G# | Phrase | Refers to | Truth | Verdict |
|---|---|---|---|---|---|---|
| 4/22 | BOS-PHI | G2 | "Series now shifts to Philadelphia for G3-G4 where PHI owns home court" | G3, G4 | G3+G4 at lower seed PHI | **CORRECT** |
| 4/22 | BOS-PHI | G2 | "G3 key: ... allowing a close game in Philly" | G3 | G3 at PHI | **CORRECT** |
| 4/22 | LAL-HOU | G2 | "Series shifts to Houston where HOU's home crowd" | G3 | G3 at lower seed HOU | **CORRECT** |
| 4/22 | SAS-POR | G2 | (none — entry's G3 key is purely status-driven, no venue reference) | — | — | — |
| 4/23 | DET-ORL | G2 | "G3 key: Series shifts to Orlando where ORL's home crowd and G1 momentum could re-energize" | G3 | G3 at lower seed ORL | **CORRECT** |
| 4/23 | OKC-PHX | G2 | "PHX must convert their improved offensive output (107 pts) into defensive stops and exploit any OKC adjustment period without Williams **in San Antonio**" | G3 | G3 at lower seed PHX (Phoenix) | **WRONG** ⚠ |
| 4/24 | NYK-ATL | G3 | "G4 key: NYK is now in a must-win situation **at home in Atlanta**" | G4 | G4 at lower seed ATL (NYK is the road team) | **AMBIGUOUS** ⚠ |
| 4/24 | NYK-ATL | G3 | "ATL's crunch-time execution gives them a structural edge **heading back to MSG**" | G5 | G5 at higher seed NYK (MSG) | **CORRECT** |
| 4/24 | CLE-TOR | G3 | "G4 key: TOR must win G4 **at home** to tie the series" | G4 | G4 at lower seed TOR | **CORRECT** |
| **4/24** | **DEN-MIN** | **G3** | "if Finch increases his minutes in a **must-win road game**" (re MIN G4) | G4 | G4 at lower seed MIN (MIN is HOME, not road) | **WRONG** ⚠ |
| **4/24** | **DEN-MIN** | **G3** | "or MIN will close out the series **at home in G5**" | G5 | G5 at higher seed DEN (DEN home, not MIN home) | **WRONG** ⚠ |
| 4/25 | BOS-PHI | G3 | "G4 key: PHI must steal G4 **at home** to avoid a 3-1 deficit" | G4 | G4 at lower seed PHI | **CORRECT** |
| 4/25 | LAL-HOU | G3 | "LAL faces a sweep opportunity **in Houston**" | G4 | G4 at lower seed HOU | **CORRECT** |
| 4/25 | SAS-POR | G3 | (no forward-venue claim; G4 key is purely "Wembanyama protocol clearance") | — | — | — |

Per-row context for the WRONG and AMBIGUOUS rows (the surrounding
sentences):

> **OKC-PHX 4/23 G3 key (full sentence):**
> "PHX must convert their improved offensive output (107 pts) into
> defensive stops and exploit any OKC adjustment period without
> Williams **in San Antonio** — though the series structure strongly
> favors OKC regardless."
>
> Diagnosis: "in San Antonio" is a hard hallucination. OKC plays in
> Oklahoma City, PHX plays in Phoenix; San Antonio is irrelevant to
> the OKC-PHX series at any game number. Almost certainly a confusion
> between the bracket "(1) OKC vs (8) PHX" and "(2) SAS vs (7) POR"
> — both are West, both have lower seed in the 7/8 slot, and SAS = San
> Antonio. The LLM seems to have cross-contaminated the two series.

> **NYK-ATL 4/24 G3 key (full sentence):**
> "G4 key: NYK is now in a must-win situation **at home in Atlanta** to
> avoid falling into a 1-3 hole; Bridges' diminished role is the
> critical variable — if coach Brown cannot find a productive
> deployment for him, NYK's perimeter depth is compromised, and ATL's
> crunch-time execution gives them a structural edge heading back to
> MSG."
>
> Diagnosis: the phrase "at home in Atlanta" is contradictory — "at
> home" naturally binds to NYK (the subject), but "in Atlanta" anchors
> the game to ATL. The LLM probably meant "in a must-win game at home
> [for ATL] in Atlanta" but the syntax leaves it ambiguous. The
> immediate next clause about MSG for G5 is correct (G5 returns to
> higher seed NYK). AMBIGUOUS rather than WRONG, but readable as wrong
> by an inattentive analyst LLM downstream.

> **DEN-MIN 4/24 G3 key (full sentence):**
> "G4 key: Edwards' 24-minute load management is the defining variable
> — if Finch increases his minutes in a **must-win road game**, MIN's
> offensive ceiling rises sharply; DEN needs Murray to find his
> 3-point shot and Jokic to generate assists in a competitive game
> script rather than an isolation-heavy blowout role, **or MIN will
> close out the series at home in G5**."
>
> Diagnosis: two factually wrong forward-venue claims in one sentence.
> The phrasing is internally consistent — both treat MIN as if it were
> the higher seed. The LLM appears to have inverted the bracket.

Tally:

- Total diary entries: **11**
- Entries with at least one forward-venue claim: **9** (only SAS-POR
  G2 4/22 and SAS-POR G3 4/25 produced no forward-venue claim)
- Entries with at least one WRONG or AMBIGUOUS claim: **3** of 11
  (27%) — OKC-PHX 4/23, NYK-ATL 4/24, DEN-MIN 4/24
- Total individual claims: **13** (CORRECT 9 + AMBIGUOUS 1 + WRONG 3)
- Wrong-claim rate among claims emitted: 3 of 13 = **23%**
- Per-series breakdown of wrong/ambiguous claims:
  - OKC-PHX: 1 wrong ("in San Antonio") — out of 1 forward claim
  - NYK-ATL: 1 ambiguous ("at home in Atlanta") — out of 2 forward claims
  - DEN-MIN: 2 wrong (must-win road game; at home in G5) — out of 2 forward claims (100%)

Note an additional related-class error not classified as forward-venue
(it's backward-looking) but worth flagging:

> **SAS-POR 4/25 G3 entry, near end:** "Castle/Harper's output falls
> back toward mean, making **the 12-point road loss margin in G3** the
> series turning point."
>
> G3 was SAS 120, POR 108 at lower seed POR. From SAS's perspective it
> was a 12-point road WIN (SAS won on the road); from POR's perspective
> a 12-point HOME loss. "Road loss" doesn't fit either party. This is
> a wrong attribution of a completed game's home/away, structurally
> similar to the forward-venue hallucinations.

---

## 4. Prompt structure audit

`build_llm_prompt()` opens with this paragraph (lines 491–500, verbatim):

```
You are updating the NBAgent season context document for yesterday's playoff results.

The document in <season_context> tags is GROUND TRUTH — it is current as of today
and supersedes any stale training-data priors about NBA rosters, coaching, or team
identities. Use its existing series diary entries as format templates; match their
tone, depth, and structure.

Your task: produce JSON with (a) new diary entries to append to the appropriate
series sections, and (b) optional injury bullet updates where yesterday's game
performance meaningfully changes a player's injury status.
```

DIARY ENTRY GUIDELINES (lines 551–564, verbatim):

```
## DIARY ENTRY GUIDELINES

- Start with a bold result line:
  **Game N ({ylabel}) — WINNER SCORE, LOSER SCORE | Series status**
  - Series status examples: "CLE leads 2-0", "Series tied 1-1", "NYK leads 2-1"
  - Add context tag when notable: "— UPSET", "— BLOWOUT (margin NN)", "— OT"
- Include top stat lines for key players (pts/reb/ast format, add FG splits when notable)
- Reference prior game entries in the same series for pattern observations
  (e.g., "Johnson AST suppressed for second straight game — 3 AST in both G1 and G2")
- Note tactical / scheme observations relevant to future prop picks
- End with "GN key:" observation for the next game
- Keep entries to 3-5 substantial lines
- Match the tone and depth of existing diary entries
```

INJURY UPDATE GUIDELINES (lines 566–574, verbatim):

```
## INJURY UPDATE GUIDELINES

- Only update bullets where yesterday's game performance meaningfully changes the
  status (confirmed healthy, new limitation, confirmed still OUT, etc.)
- `search_line` should contain enough of the existing bullet's opening text to
  uniquely identify it (bold player name + first few words are ideal).
- Preserve the "- **Player Name (TEAM)** — ..." format.
- Include game performance data that confirms or contradicts the concern.
- If no injury updates are warranted, return `"injury_updates": []`.
```

IMPORTANT (lines 576–582, verbatim):

```
## IMPORTANT

- The document inside <season_context> is AUTHORITATIVE. Your training data may
  be stale — do NOT correct rosters, coaches, or team facts against your priors.
- Do not invent stats. Only use stat lines provided in the game data above.
- Return ONLY valid JSON. No markdown fencing, no explanation, no preamble.
```

### Per-guideline forward-venue invitation analysis

| # | Guideline | Quote | Invites forward-venue claim? |
|---|---|---|---|
| 1 | Bold result line | "Start with a bold result line: **Game N ({ylabel}) — WINNER SCORE..." | No — historical only |
| 2 | Stat lines | "Include top stat lines for key players" | No — historical only |
| 3 | Prior-game references | "Reference prior game entries... for pattern observations" | No — historical/pattern only |
| 4 | Tactical observations | "Note tactical / scheme observations relevant to future prop picks" | **YES — implicitly invites forward inference** ("relevant to future prop picks" frames the LLM toward forward-looking claims) |
| 5 | **GN key forward observation** | **"End with 'GN key:' observation for the next game"** | **YES — direct invitation to make a forward-looking claim** |
| 6 | Length cap | "Keep entries to 3-5 substantial lines" | No |
| 7 | Tone match | "Match the tone and depth of existing diary entries" | **YES — indirect invitation** (existing diary entries contain forward-venue claims; "match the tone" reads as license to imitate) |

### Constraints DISCOURAGING forward-venue claims

Searched DIARY ENTRY GUIDELINES, INJURY UPDATE GUIDELINES, IMPORTANT
section, and the opening paragraph. Found **zero** constraints that:

- Forbid forward-venue claims
- Require forward claims to be sourced from supplied data
- Tell the LLM not to invent venue facts
- Reference 2-2-1-1-1 format or bracket seeding rules
- Restrict "GN key:" content to non-venue topics

The IMPORTANT section's "Do not invent stats" line is the closest
analogue — it forbids fabricating stat numbers — but says nothing
about venue facts. The "training data may be stale" caveat addresses
roster/coach drift but not forward-venue inference.

---

## 5. Source data audit

Loader functions in `agents/season_context_updater.py`:

| Loader | Line | Provides | Does NOT provide |
|---|---|---|---|
| `load_yesterday_playoff_games()` | 116 | Yesterday's completed playoff games: home_team, away_team, home_score, away_score, home_spread, season_type filter | **Today's games. Tomorrow's games. Series format. Bracket seeding. Future-game venues.** |
| `load_player_stat_lines(games)` | 181 | Per-game stat dict list (pts/reb/ast/3pm/fgm/fga/min) for whitelisted players + 25+ pt non-whitelisted, sorted desc | Forward-game venue, future minutes projections, future game date |
| `load_post_game_news()` | 252 | `players` dict from `post_game_news.json` — narratives keyed by player_name | Forward-game venue or any future-game data |
| `load_injuries()` | 262 | Raw `injuries_today.json` dict (per-team injury bullets, plus metadata keys) | Forward-game venue. Player projected availability for upcoming game (only current status) |

> **None of the four loaders supplies forward-venue source data.**
> Specifically absent from the LLM's prompt context:
> - The next game's date
> - The next game's host
> - The series format (2-2-1-1-1)
> - The bracket seeding (which team is the higher seed)

The constant `BRACKET = DATA / "playoff_bracket.json"` IS defined in
the file:

```bash
$ grep -c "playoff_bracket\|BRACKET" agents/season_context_updater.py
1

$ grep -n "playoff_bracket\|BRACKET" agents/season_context_updater.py
45:BRACKET     = DATA / "playoff_bracket.json"
```

The file path constant exists at line 45 — alongside `MASTER_CSV`,
`GAME_LOG`, `POST_NEWS`, `INJURIES`, etc. — but is **never referenced**
again anywhere in the file. No loader reads it, no helper consumes it,
no caller imports it. This is the canonical "shaped but unused"
dead-end pattern: the data file exists in `data/` (per
`data/playoff_matchup.json` and `agents/playoff_matchup.py` which DO
read it), but the season-context updater's prompt construction never
reaches it.

`data/nba_master.csv` does carry tomorrow's games (the `2026-04-25`
rows during the `2026-04-24` auto-run), but `load_yesterday_playoff_games()`
specifically filters to `YESTERDAY_STR` rows. Today/tomorrow rows are
in the file but unread.

The LLM's only references for forward-venue facts are therefore:

1. Its training data — known stale per the spec's own warning ("Your
   training data may be stale")
2. The embedded `<season_context>` document — itself partly constructed
   from prior auto-runs that may contain wrong forward-venue claims,
   creating a feedback loop where one wrong claim contaminates the
   next day's grounding

---

## 6. Comparison: auto-generated vs hand-authored prose

Hand-authored content in `context/nba_season_context.md` includes:

- Pre-Series Intel blocks (one per series) — written before R1 G1
- The opening italic line per series header (e.g.,
  `*(Game 1: Apr 18, 3:30 PM ET at Denver. DEN won season series 3-1.
  Third playoff meeting in 4 years.)*`)
- Top-level sections (PLAYOFF INJURY LANDSCAPE, OPPONENT SCHEME NOTES,
  PLAYER NOTES, PLAYOFF DOSSIER UPDATES) — Oliver-maintained

| Feature | Hand-authored | Auto-generated |
|---|---|---|
| Sentence structure | Predominantly **bullet lists** with terse declaratives. Pre-Series Intel uses `- Subject: data point. Implication or watch item.` form | Predominantly **dense paragraphs** of multi-clause sentences joined by em-dashes; no bullets within diary entries |
| Hedging language | "All signs are…", "expect…", "monitor as a…wildcard" — calibrated forecasts | "the most significant development", "the defining variable", "validates", "asserting itself emphatically" — high-confidence assertions |
| Forward predictions | Specific named variables to watch (e.g., "Tim Hardaway Jr. venue factor: Had two explosive 3rd-quarter performances in Minneapolis") | Broad "G(N+1) key:" sentences with venue inferences ("must-win road game", "at home in Atlanta") |
| Average sentence length | ~15–25 words; many short data-citation sentences | ~30–50 words; long compound sentences with multiple subordinate clauses |
| Source citations | Frequent ("(NBA.com, ESPN, SI)", "(SI)", "(The Athletic, Krawczynski)") | None — auto-entries quote no sources |
| Specific factual hooks | "170 Murray assists to Jokic (most in NBA), 894 Jokic ball-screens for Murray (most to any single teammate)" | "the 8-seed that nearly won in Denver twice has now seized control" — narrativized, not numerically grounded |
| Tense and forward-claim style | Hedged conditionals ("could", "should", "if") tied to specific named conditions | Confident future indicatives ("will close out", "is the defining variable") often unconditional |

Prose features cluster cleanly. The DEN-MIN G3 paragraph's voice
("the defining variable", "isolation-heavy blowout role", "or MIN will
close out the series at home in G5") matches the auto-generated voice
across the other 10 diary entries — multi-clause, em-dash-heavy,
high-confidence narrative. It does **not** match Oliver's terse
bullet-and-hedge Pre-Series Intel style.

This is consistent with Section 1's commit attribution: the DEN-MIN
G3 paragraph appears in commit `aaf809f` (2026-04-24, github-actions
bot), not in any of Oliver's manual commits.

---

## 7. Hypothesis evaluation

### H1. The DEN-MIN G3 paragraph was auto-generated

**SUPPORTED.** Section 1 shows commit `aaf809f` (2026-04-24,
`github-actions[bot]`, message "Auditor results 2026-04-24 [skip ci]")
added three G3 diary entries including DEN-MIN G3. Section 6 confirms
the prose voice matches the other 10 auto-generated entries and not
Oliver's hand-authored Pre-Series Intel style.

### H2. Forward-venue claims appear in most auto-generated G3 paragraphs

**SUPPORTED.** Section 3 shows 9 of 11 diary entries (82%) contain at
least one forward-venue claim. Of the 6 G3 paragraphs specifically
(NYK-ATL, CLE-TOR, DEN-MIN on 4/24; BOS-PHI, LAL-HOU, SAS-POR on 4/25),
**5 of 6** contain a forward-venue claim — only SAS-POR G3 (4/25) does
not, and that exception is conditioned on the unusual Wembanyama
concussion-protocol scenario where the LLM appropriately defaulted to
a status question instead of a venue assertion.

### H3. The wrong-claim rate is meaningful (not just DEN-MIN as a one-off)

**SUPPORTED.** Section 3 finds:
- **2 wrong claims** classified WRONG (DEN-MIN "must-win road game";
  DEN-MIN "at home in G5")
- **1 wrong claim** also classified WRONG (OKC-PHX "in San Antonio")
- **1 ambiguous claim** classified AMBIGUOUS (NYK-ATL "at home in
  Atlanta")

Plus an additional **backward-venue error** outside the spec's strict
definition (SAS-POR G3 "12-point road loss margin in G3" describes a
home loss / road win as a "road loss"). That is a closely-related
hallucination class — same agent, same prompt, same data envelope —
suggesting the LLM is generally weak on home/away attribution, not
just on forward inference.

3 entries with WRONG/AMBIGUOUS claims out of 11 total = 27% entry-rate.
3 wrong + 1 ambiguous out of 13 forward-venue claim instances = 23%
claim-rate. Both well above what would be acceptable for a content
input that downstream agents may read as authoritative.

### H4. The prompt has zero constraints against forward-venue claims

**SUPPORTED.** Section 4's per-guideline analysis finds **zero**
constraints in any of the prompt's structured sections (DIARY ENTRY
GUIDELINES, INJURY UPDATE GUIDELINES, IMPORTANT, opening paragraph)
that forbid forward-venue claims, require sourcing, or instruct the
LLM not to invent venue facts. The single closest analogue ("Do not
invent stats") forbids fabricating stat numbers but explicitly does
not extend to venue.

### H5. The prompt invites forward-venue claims structurally

**SUPPORTED.** Section 4 identifies three structural invitations:

1. **Direct (Guideline 5):** `End with "GN key:" observation for the
   next game` — explicitly directs the LLM to produce a forward-looking
   sentence. The LLM has no authoritative source for forward facts but
   is told to produce one anyway.
2. **Indirect (Guideline 7):** `Match the tone and depth of existing
   diary entries` — the existing entries inside `<season_context>` DO
   contain forward-venue claims (some correct, some wrong from prior
   bot runs), and the "match the tone" instruction reads as license
   to imitate.
3. **Soft (Guideline 4):** `Note tactical / scheme observations
   relevant to future prop picks` — frames the LLM toward
   forward-looking claims more broadly.

### H6. The prompt supplies no forward-venue source data

**SUPPORTED.** Section 5 confirms none of the four loaders
(`load_yesterday_playoff_games`, `load_player_stat_lines`,
`load_post_game_news`, `load_injuries`) supply forward-venue data.
`BRACKET = DATA / "playoff_bracket.json"` is defined at line 45 but
unreferenced anywhere else in the file (`grep -c` returns 1; that 1
is the definition itself).

### H7. The auto-updater is the SOLE writer of post-2026-04-18 diary entries

**SUPPORTED.** Section 1's commit attribution shows every `**Game N**`
paragraph added after `PLAYOFFS_R1_DATE = 2026-04-18` came from a bot
commit (`7dc6e2b`, `febe859`, `aaf809f`, `c711fbf`). The two human
commits in this period that touched `nba_season_context.md`
(`d58707f`, `cb540ef`, `89cf4d8`) added or modified other content:
parlay-related changes (`d58707f`), the Fix #1 prose correction
(`89cf4d8`), and a parlay rebuild debug (`cb540ef`). None of them
authored a diary `**Game N**` paragraph. The fix scope therefore
correctly targets the auto-updater alone — Oliver is not contributing
diary content directly.

> **Consolidated finding:** The auto-updater generates forward-venue
> claims at a meaningful rate (9 of 11 entries, 82%), with 3 of those
> 11 entries (27%) containing a wrong or ambiguous claim — a 23%
> wrong-claim rate among the 13 forward-venue claim instances emitted.
> The prompt structure invites these claims through three independent
> mechanisms (the GN-key guideline, the tone-matching instruction, and
> the broader "future prop picks" framing) and supplies zero
> forward-venue source data — the BRACKET path constant is defined but
> never plumbed into the prompt. The single highest-leverage fix is to
> add an explicit constraint to DIARY ENTRY GUIDELINES forbidding
> forward-venue claims unless sourced from supplied data, paired with
> a corresponding instruction to focus "GN key:" sentences on
> variables, players, or tactical questions rather than venue facts.

---

## 8. Recommended next steps

Three candidate prompt-level fixes for `agents/season_context_updater.py`,
ordered most-to-least conservative.

### Candidate A — Forbid forward-venue claims (small)

**File:** `agents/season_context_updater.py` `build_llm_prompt()` —
modify DIARY ENTRY GUIDELINES (lines 551–564) and/or IMPORTANT
section (lines 576–582). Single-paragraph addition, no new data
plumbing.

**Mechanism:** Add an explicit constraint such as:

> "GN key:" observations must focus on VARIABLES (player health,
> minutes, role), TACTICAL keys, or PATTERN observations relevant
> to future prop picks. They must NOT make claims about WHERE the
> next game will be played — no "at home", "on the road", "at
> <city>", "<team> hosts", "shifts to <venue>", or future-game venue
> assumptions ("at home in G5", "back to MSG"). Venue is determined
> deterministically by the bracket seeding and 2-2-1-1-1 format and
> is supplied to downstream agents from authoritative sources; do
> not infer or invent it here.

Plus a paired note that prior diary entries inside `<season_context>`
may contain venue claims meant for human review — that is not a
license to imitate.

**Trade-off:** Some loss of expressive texture. "Series shifts to
Minnesota" is a legitimate observation when correct; this rule bans
it preemptively. The trade is expressiveness for safety.

**Addresses:** All wrong-claim cases. No data plumbing. Easiest to
implement and to verify (the constraint either fires in next bot run
or it doesn't).

**Complexity:** Small — one paragraph addition to one prompt string.

**Manifestation coverage:** Both the DEN-MIN G3 wrong claims (Fix #1
already corrected manually) and the OKC-PHX "in San Antonio"
hallucination would be prevented by Candidate A's constraint, since
both are forward-venue claims.

### Candidate B — Supply forward-venue source data (medium)

**File:** `agents/season_context_updater.py` — new loader + new
prompt section.

**Mechanism:** Three changes:

1. **New loader `load_upcoming_game_venues()`** that reads the
   already-defined-but-unused `BRACKET` constant
   (`data/playoff_bracket.json`) plus 2-2-1-1-1 format logic plus
   completed-game counts to produce a structured "Next game:" line
   per active series:

   ```
   - DEN vs MIN: Game 4 (next, 2026-04-25) at MIN. DEN on the road.
     If series continues: G5 (if needed) at DEN, G6 at MIN, G7 at DEN.
   ```

2. **New prompt section** between YESTERDAY'S GAMES and OUTPUT FORMAT:

   ```
   ## UPCOMING GAME VENUES (authoritative — derived from bracket
   seeding + 2-2-1-1-1 format)
   <upcoming_venues_block>

   When making "GN key:" observations that mention venue, refer ONLY
   to this data. Do not infer venue from training data.
   ```

3. **DIARY ENTRY GUIDELINES** gains a sentence pointing the LLM at
   the new section.

**Trade-off:** Plumbing — one new loader, one new prompt section,
one helper that derives venue from bracket. Risk that the LLM
still confabulates when the structured data is misread (but
significantly lower risk than no data at all).

**Addresses:** Same as Candidate A but preserves the
"shifts to <city>" / "must-win road game" expressiveness when
correctly grounded.

**Complexity:** Medium — ~50 lines of new code (loader +
formatter), ~10 lines of prompt insertion. The bracket-format
derivation is small (8 series × 2 G(N+1) lookups per run).

### Candidate C — Both (medium)

Combine Candidate A's guardrail (no venue claims unless sourced)
with Candidate B's data plumbing (structured next-game venue block).
The LLM is allowed to mention venue but ONLY by quoting the
structured block. This is the most defensive design and is what
production prompt engineering typically converges on for
auto-generative agents.

**Trade-off:** Carries both costs — Candidate B's plumbing complexity
plus Candidate A's expressiveness limit, with the LLM operating
inside both constraints simultaneously.

**Addresses:** Same. Strongest defense.

**Complexity:** Medium — sum of A and B.

### Recommended ordering

Ship **Candidate A first** as the cheapest fix that removes the risk
source. The constraint can land in a single Edit call modifying one
prompt string, no data plumbing, no test infrastructure changes.
Verification: read the next bot commit's diary entries (one or two
days later) and grep for the banned phrases (`at home`, `on the
road`, `at <city>` etc.) — should return zero.

If texture loss is felt after a week or two of bot runs, layer
Candidate B on top to re-enable venue mentions when sourced. This
two-stage rollout matches the surgical-then-structural pattern used
elsewhere in the repo (e.g., the home/away inversion fix series:
manual context correction first, then structural defenses).

Candidate C is the right end state but doesn't need to land all at
once — it falls out naturally if both A and B ship in sequence.

### Beyond prompt-level fixes — structural concerns surfaced

1. **Daily auto-update commit gate.** Consider adding a
   deterministic post-write check that scans new diary entries for
   any `at <city>` / `at home` / `road game` claim, and if Candidate
   A's constraint is in place, aborts the commit when a banned
   phrase appears. Belt-and-suspenders against future LLM
   regressions. Implementation would live in
   `season_context_updater.py` `apply_diary_entries()` or in the
   workflow's commit step.

2. **Backward-venue claims are also a class problem.** The SAS-POR
   G3 "12-point road loss margin in G3" misattributes a completed
   game's home/away. Out of strict scope for forward-venue
   guardrails, but a Candidate A extension could include both
   forward and backward venue claims under a single
   "no venue claims unless sourced" rule, with the source for
   completed games being `nba_master.csv` rows already loaded by
   `load_yesterday_playoff_games()` (which carries home/away).

3. **Historical wrong claims in committed diary entries.** Should
   the auto-updater patch wrong claims in prior diary entries it
   did not write? Almost certainly **no** — those are graded games
   and the wrong claim is now context for tomorrow's analyst run,
   which the structural fixes shipped 2026-04-25 already insulate
   (Fix #1 for DEN-MIN G3, plus Fix #2/#3/#4 for the analyst
   pipeline). Corrections to historical diary entries are a
   per-incident manual decision, not auto-update scope.

4. **Dependency on `<season_context>` as ground truth.** The prompt
   says "The document inside <season_context> is AUTHORITATIVE." If
   the document contains a wrong forward-venue claim from a prior
   bot run, that claim is now treated as authoritative by the LLM
   on the next run. Candidate A's constraint partly mitigates this
   (the LLM is forbidden from emitting venue claims) but the next
   run still SEES the wrong claim in the embedded document — it
   just isn't allowed to imitate it. A heavier fix would carve a
   "diary entries from prior bot runs are not authoritative for
   forward-venue facts" exception into the IMPORTANT section, but
   this is out of scope for a Candidate A starter.

---

End of report.
