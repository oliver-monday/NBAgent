# Parlay Research Drilldown — H7 Same-Player Concentration in Reach

*Generated: 2026-04-24 21:49*

- Source: `data/parlay_card_universe.jsonl`
- Total cards streamed: 647,510
- Target subset size (Reach + max_legs_per_player≥3): 640
- Min reportable n per row: 20

## 1. Overall Subset Stats

| subset | n | hits | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| Reach + max_legs_per_player≥3 | 640 | 259 | 40.5% | 38.7% | +1.7pp | +17.5pp |

## 2. Player Breakdown

Cards in the subset grouped by the player contributing 3+ legs. Sorted by `hit_rate` descending; rows with n<20 are flagged *insufficient_sample* and pushed to the bottom.

| player | n_cards | hits | hit_rate | expected_market | delta_vs_market | delta_vs_system | flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| De'Aaron Fox | 25 | 21 | 84.0% | 38.5% | +45.5pp | +59.7pp |  |
| Evan Mobley | 431 | 220 | 51.0% | 37.7% | +13.3pp | +28.3pp |  |
| James Harden | 20 | 0 | 0.0% | 36.9% | -36.9pp | -25.0pp |  |
| Jalen Johnson | 29 | 0 | 0.0% | 42.0% | -42.0pp | -23.1pp |  |
| Nikola Jokic | 82 | 0 | 0.0% | 41.1% | -41.1pp | -22.0pp |  |
| Amen Thompson | 17 | 14 | — | — | — | — | *insufficient_sample* |
| Desmond Bane | 3 | 2 | — | — | — | — | *insufficient_sample* |
| Scottie Barnes | 9 | 2 | — | — | — | — | *insufficient_sample* |
| Nickeil Alexander-Walker | 6 | 0 | — | — | — | — | *insufficient_sample* |
| Jamal Murray | 6 | 0 | — | — | — | — | *insufficient_sample* |
| Julius Randle | 5 | 0 | — | — | — | — | *insufficient_sample* |
| Anthony Edwards | 7 | 0 | — | — | — | — | *insufficient_sample* |

## 3. Date Breakdown

Cards in the subset grouped by date (sorted chronologically).

| date | n_cards | hits | hit_rate | expected_market | delta_vs_market | delta_vs_system | flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-03-31 | 20 | 0 | 0.0% | 36.9% | -36.9pp | -25.0pp |  |
| 2026-04-01 | 6 | 0 | — | — | — | — | *insufficient_sample* |
| 2026-04-09 | 2 | 0 | — | — | — | — | *insufficient_sample* |
| 2026-04-18 | 11 | 0 | — | — | — | — | *insufficient_sample* |
| 2026-04-20 | 38 | 1 | 2.6% | 42.1% | -39.5pp | -20.9pp |  |
| 2026-04-21 | 42 | 35 | 83.3% | 39.5% | +43.9pp | +59.0pp |  |
| 2026-04-22 | 3 | 2 | — | — | — | — | *insufficient_sample* |
| 2026-04-23 | 518 | 221 | 42.7% | 38.3% | +4.3pp | +20.1pp |  |

## 4. Player × Date Concentration (Top 10 by n_cards)

Top 10 (player, date) pairs by card count. A single (player, date) with >20 cards represents a heavy concentration of the subset on one slate.

| rank | player | date | n_cards | hits | hit_rate |
| --- | --- | --- | --- | --- | --- |
| 1 | Evan Mobley | 2026-04-23 | 431 | 220 | 51.0% |
| 2 | Nikola Jokic | 2026-04-23 | 82 | 0 | 0.0% |
| 3 | Jalen Johnson | 2026-04-20 | 29 | 0 | 0.0% |
| 4 | De'Aaron Fox | 2026-04-21 | 25 | 21 | 84.0% |
| 5 | James Harden | 2026-03-31 | 20 | 0 | 0.0% |
| 6 | Amen Thompson | 2026-04-21 | 17 | 14 | 82.4% |
| 7 | Anthony Edwards | 2026-04-20 | 7 | 0 | 0.0% |
| 8 | Nickeil Alexander-Walker | 2026-04-01 | 6 | 0 | 0.0% |
| 9 | Jamal Murray | 2026-04-18 | 6 | 0 | 0.0% |
| 10 | Julius Randle | 2026-04-18 | 5 | 0 | 0.0% |

## 5. Stat Trio Breakdown

For 3-leg concentration the trio is one of C(4,3)=4 (PTS|REB|AST, PTS|REB|3PM, PTS|AST|3PM, REB|AST|3PM); for 4-leg concentration the trio is the unique PTS|REB|AST|3PM. Sorted by `hit_rate` descending.

| stat_trio | n_cards | hits | hit_rate | expected_market | delta_vs_market | delta_vs_system | flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AST|PTS|REB | 567 | 236 | 41.6% | 38.4% | +3.2pp | +18.9pp |  |
| 3PM|AST|PTS | 59 | 23 | 39.0% | 40.7% | -1.7pp | +14.9pp |  |
| 3PM|PTS|REB | 11 | 0 | — | — | — | — | *insufficient_sample* |
| 3PM|AST|REB | 3 | 0 | — | — | — | — | *insufficient_sample* |

## 6. Concentration Legs (3 vs 4 same-player legs)

Does 3-leg same-player concentration perform differently from 4-leg same-player concentration?

| concentration_legs | n_cards | hits | hit_rate | expected_market | delta_vs_market | delta_vs_system | flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 3-leg | 640 | 259 | 40.5% | 38.7% | +1.7pp | +17.5pp |  |

## 7. Total Card Legs Distribution

Distribution of the subset by the card's TOTAL leg count (vs the player-concentrated count above). A 3-leg card with all 3 legs same player is fundamentally different from a 5-leg card with 3 legs same player + 2 other-player legs.

| total_n_legs | n_cards | hits | hit_rate | expected_market | delta_vs_market | delta_vs_system | flag |
| --- | --- | --- | --- | --- | --- | --- | --- |
| L=4 | 27 | 14 | 51.8% | 40.9% | +11.0pp | +22.2pp |  |
| L=5 | 613 | 245 | 40.0% | 38.6% | +1.3pp | +17.3pp |  |

## 8. Interpretation Notes

> This drilldown is data only. Interpretation lives in chat after review. Key questions:
> 1. Is the +1.7pp signal broad-based across players or concentrated in 1-2 stars?
> 2. Are the cards date-clustered (suggesting hot streaks rather than structural pattern)?
> 3. Does any specific stat trio outperform others significantly?
> 4. Does 3-leg concentration differ meaningfully from 4-leg concentration?
