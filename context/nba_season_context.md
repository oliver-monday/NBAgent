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

## TEAM DEFENSIVE PROFILES

ATL: High pace. Inflates opponent guard assists and perimeter scoring. Weak rebounding unit; inflates opponent frontcourt boards.
BOS: League-lowest pace. Suppresses all opponent counting stats via low possession volume. Elite wing suppression.
CHA: High pace. Allows high 3PA volume; inflates scoring for high-usage wings. Weak interior defense.
CHI: High pace. Inflates opponent PPG and FG%. Weak rim protection inflates opponent paint points.
CLE: Low pace. Elite suppression of big-man scoring and rebounding. Switches heavy, neutralizing post-up volume.
DAL: Mid pace. Suppresses opponent 3PM and 3P%. Vulnerable frontcourt inflates opponent rebounding stats.
DEN: Mid pace. Elite defensive rebounding; suppresses opponent second-chance points and big-man boards.
DET: Mid pace. Elite rim protection suppresses opponent FG% in the paint and big-man scoring/rebounding.
GSW: High pace. Inflates opponent 3PA and guard scoring. Heavy help-side scheme allows high assist rates to opposing wings.
HOU: Low pace. Suppresses all counting stats. Switching-heavy defense neutralizes traditional big-man usage.
IND: Maximum pace. League-high inflation of all opponent counting stats across all positions.
LAC: Mid pace. Suppresses wing scoring and 3PM. Strong perimeter unit reduces opponent assist rates.
LAL: Mid pace. Suppresses opponent rebounds. Allows high opponent FG% but restricts transition opportunities.
MIA: Low pace. Elite rebounding suppression. Zone scheme forces high 3PA while neutralizing opponent interior points.
MIL: Mid pace. Inflates opponent 3PM and wing scoring. Weak rebounding unit allows high volume to opposing forwards.
MIN: Low pace. Elite rim protection (Gobert); suppresses opponent FG% and big-man points specifically.
NYK: Low pace. Suppresses opponent rebounds and PPG via slow possession length. Heavy focus on defensive glass.
OKC: Mid pace. Forces maximum turnovers; inflates opponent TO rate. Suppresses opponent guard FG%.
ORL: Low pace. Suppresses opponent assists and big-man scoring. Elite positional size neutralizes small-guard volume.
PHI: Mid pace. Inflates opponent turnovers/steals. Allows high rebounding volume to opposing bigs.
PHX: Mid pace. Suppresses opponent SF points and 3P%. Strong interior rebounding suppresses opposing big-man boards.
SAC: Mid pace. Allows high opponent FG% from mid-range and wing areas. Weak perimeter closeouts inflate 3PA volume.
SAS: Mid pace. Elite rim protection (Wembanyama); suppresses opponent paint points. Weak rebounding unit outside of Wembanyama.
TOR: Mid pace. Suppresses opponent SF scoring. Switching scheme reduces big-man post-up efficiency and usage.
UTA: High pace. League-worst overall defense. Inflates all opponent stats across all categories and positions.
