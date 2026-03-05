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

## Improvement Proposals (Queued)

These were designed together and are ready for implementation. Listed in recommended execution order.

---

### #1 — Usage-Share Delta When Teammates Are Out
**Priority: HIGH — biggest alpha, most underpriced edge**
**Status: DEFERRED — insufficient DNP sample data mid-season.** Key star pairings (Brunson/KAT, LeBron/Luka, etc.) have 0 absence games; most whitelisted player pairs have <3 shared absence games. Revisit at start of next season with a full year of data.

**What:** For each whitelisted player, compute their average minutes, shot attempts, usage rate, and stat output in games where a given teammate DNP'd vs. games that teammate played. Store as `teammate_absence_delta` in `player_stats.json`.

**Why:** The biggest NBA props edge is role expansion when a key teammate is out. The Analyst currently infers this qualitatively from injury context, which is inconsistent. Concrete numbers like "when Brunson DNPs, Towns averages +4.2 shots and +3.1 pts" turn a subjective judgment into a quantified edge.

**Where:** `quant.py` — new `build_teammate_absence_deltas()` function. Uses `player_game_log.csv` with `dnp` column to identify absence games.

**Prompt change:** Add `teammate_absence_delta` field to the per-player context block in `analyst.py`. Instruction: "If a key teammate is listed as OUT today and their absence delta is ≥+2 pts or ≥+1 reb/ast for this player, factor this into tier selection."

---

### #2 — Opponent-Specific Tier Hit Rates ✅ IMPLEMENTED
**Priority: HIGH — fixes biggest data conflation in current prompt**

**What:** Split each player's tier hit rates by opponent defensive rating. Output: `{"soft": {"hit_rate": 0.91, "n": 11}, "tough": {"hit_rate": 0.58, "n": 12}}` per tier per stat alongside the existing overall rate.

**Why:** The current "8/10 L10" conflates easy and hard matchups. A player hitting 80% overall but only 55% against tough defenses is a fundamentally different pick when today's matchup is tough.

**Where:** `quant.py` — extend `compute_tier_hit_rates()` to accept an optional `opp_rating_filter`. Requires joining `player_game_log` with `opp_defense` context retroactively.

**Prompt change:** Analyst receives `hit_rate_vs_soft` and `hit_rate_vs_tough` alongside the existing `hit_rate_display`. Instruction: "When opp_defense_rating is soft or tough, weight the matchup-specific hit rate more than the overall rate."

---

### #3 — Back-to-Back Quantified Tier Adjustment
**Priority: MEDIUM — known hole, currently handled qualitatively only**

**What:** Compute each player's tier hit rate specifically on B2B second nights vs. normal rest. Store as `b2b_hit_rates` alongside normal `tier_hit_rates` in `player_stats.json`.

**Why:** B2B fatigue is a real effect but currently a soft warning in the prompt ("factor in back-to-back fatigue"). If a player's PTS tier 20 drops from 78% normally to 45% on B2Bs, the correct pick is tier 15 — this correction only happens if Claude reasons about it unprompted, which is inconsistent.

**Where:** `quant.py` — filter games where the player's team played the night before (using `nba_master.csv` date logic, same as `build_b2b_teams()`).

**Prompt change:** When `on_back_to_back = true`, Analyst prompt instructs: "Use `b2b_hit_rates` instead of `tier_hit_rates` for tier selection. If sample is <5 games, apply a conservative one-tier-down adjustment."

---

### #4 — Rolling Volatility Score Per Player Per Stat
**Priority: MEDIUM — improves pick quality, prevents overconfidence in streaky players**

**What:** Add a `volatility` metric: standard deviation of binary hit outcomes over the last 20 games at the best tier for each stat. Express as `"consistent"` (σ < 0.3), `"moderate"` (0.3–0.4), or `"volatile"` (σ > 0.4).

**Why:** Hit rate is an average — it hides whether a player is a reliable 80% hitter or a streaky player who goes 10/10 then 2/10. A volatile player at 75% is a worse prop bet than a consistent player at 72%.

**Where:** `quant.py` — add `compute_volatility()` alongside existing `compute_tier_hit_rates()`. 20-game window preferred over 10 for stability.

**Prompt change:** Add `volatility` tag to per-player output. Instruction: "Prefer consistent or moderate volatility players when confidence is otherwise similar. Flag volatile players in reasoning."

---

### #5 — Tier-Walk Audit Trail in Pick Output
**Priority: LOWER — improves feedback loop, compounds over time**

**What:** Add a `tier_walk` field to the Analyst output schema: a compact string documenting Claude's walk-down reasoning, e.g. `"30:3/10 25:5/10 20:8/10→pick"`.

**Why:** The current single `reasoning` sentence hides the tier selection logic. This makes it impossible to audit whether Claude skipped a better tier, picked a tier with lower hit rate than the one above it, or made a sound walk-down. The Auditor can then flag systematic tier-selection errors.

**Where:** `analyst.py` prompt — add `tier_walk` field to output schema. `auditor.py` — add tier-walk validation: flag any pick where the chosen tier's hit rate is lower than the tier above it.

**Prompt change:** Add to output schema: `"tier_walk": "string — compact walk-down, e.g. '30:3/10 25:5/10 20:8/10→pick'"`. Analyst instructions: "Always show your walk-down. Never pick a tier if the tier above it also qualifies."

---

## Implementation Notes

- Proposals #1 and #2 both extend `quant.py` — implement together in one session to avoid two separate `player_stats.json` schema changes.
- Proposal #3 reuses `build_b2b_teams()` logic already in `quant.py` — relatively quick addition.
- Proposals #4 and #5 are independent of each other and of #1–#3.
- All proposals require corresponding prompt updates in `analyst.py` — plan the schema additions and prompt changes together.
- None of these require changes to `auditor.py` or `parlay.py` for the initial implementation (though #5 enables future Auditor enhancements).
