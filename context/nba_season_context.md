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

  Last updated: 2026-03-04
-->

## SEASON FACTS

Jayson Tatum (BOS): OFS all season (Achilles). Jaylen Brown/Derrick White usage reflects this as baseline, not elevated.
Tyrese Haliburton (IND): OFS all season (Achilles). Andrew Nembhard role reflects this as baseline.
Kyrie Irving (DAL): OFS all season (Knee). Cooper Flagg usage reflects this as baseline.
Fred VanVleet (HOU): OFS all season (ACL). Kevin Durant/Alperen Sengun usage reflects this as baseline.

James Harden: traded LAC → CLE (Feb 2026). Pre-trade log rows are LAC system; discount for current CLE role projection.
Kevin Durant: traded PHX → HOU (Jan 2026). Pre-trade log rows are PHX system; discount for current HOU role projection.
Brandon Ingram: traded NOP → TOR (Jan 2026). Pre-trade log rows are NOP system; discount for current TOR role projection.
Jalen Green: traded HOU → PHX (Jan 2026). Pre-trade log rows are HOU system; discount for current PHX role projection.

Payton Pritchard (BOS): permanent Sixth Man role as of Feb 2026 following backcourt trades. Weight recent 10 games heavily.
Jalen Johnson (ATL): permanent primary offensive hub as of Jan 2026. Usage increase is baseline, not situational. Weight recent 10 games heavily.
Tyrese Maxey (PHI): permanent first-option status as of Nov 2025 with Embiid and George missing significant time. High volume is baseline.
Matas Buzelis (CHI): expanded starter role permanent for rest of season following mid-season trades. Weight recent 10 games heavily.

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
