# NBAgent — Roadmap - Off Season / Deferred

---

## Open Items

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