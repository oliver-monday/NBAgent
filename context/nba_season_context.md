<!--
  context/nba_season_context.md
  Injected into the Analyst prompt daily between ## CURRENT INJURY REPORT and ## PLAYER RECENT PERFORMANCE.

  MAINTENANCE RULES:
  - Add facts only when they are stable for the rest of the season (trade settled, player confirmed OFS, role locked in).
  - Remove or correct facts immediately when they change (player returns, trade reversal, role shifts).
  - Never let stale facts accumulate — a wrong fact is worse than no fact.
  - Only include players and teams present in playerprops/player_whitelist.csv (active=1).
  - Keep total file under 700 tokens (~500 words of content, excluding this header).
  - Every sentence must answer: "does this change how I should predict today's stat line?"
  - No hedging language. No standings or win-loss records. No week-to-week information.

  Last updated: 2026-03-06
-->

## SEASON FACTS

#PERMANENT 

ABSENCES (OFS ALL SEASON): Players marked OFS all season are permanent absences. Their teammates' current roles are baselines, not elevations. No agent should cite these absences as a causal factor in any pick reasoning or audit analysis. Do not attribute teammate performance increases to these players being out — the elevated role is the new normal and has been priced into all statistical baselines from the start of the season.

Tyrese Haliburton (IND): OFS all season (Achilles). Andrew Nembhard role reflects this as baseline.
Kyrie Irving (DAL): OFS all season (Knee). Anthony Davis traded away from DAL. Cooper Flagg usage reflects these as baseline.
Fred VanVleet (HOU): OFS all season (ACL). Kevin Durant usage reflects this as baseline.

TRADES
James Harden: traded LAC → CLE (Feb 2026). Pre-trade log rows are LAC.
Payton Pritchard (BOS): Sixth Man role established Feb 2026, but Tatum's return tonight introduces rotation uncertainty.
Jalen Johnson (ATL): permanent primary offensive hub as of Jan 2026. Usage increase is baseline, not situational.
Tyrese Maxey (PHI): permanent first-option status as of Nov 2025 with Embiid and George missing significant time. High volume is baseline.

# STABLE / SEMI-STABLE

ACTIVE RETURNS (recently returned from OFS): Jayson Tatum (BOS): returning tonight 2026-03-06 from Achilles OFS — first game back this season. Role is starter but minutes will be managed (expect 20-28 min initially). Brown/White/Pritchard usage will compress from current baselines. Do not assume any BOS player's role is stable tonight — treat all BOS picks with elevated uncertainty until new baselines establish over 5+ games.