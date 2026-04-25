# Parlay Research Hypothesis Analysis

*Generated: 2026-04-24 22:43*

- Source: `data/parlay_card_universe.jsonl`
- Total cards processed: 1,055,719
- Min reportable subgroup size: n ≥ 100

## Caveat

**Caveat: small base-pick pool.** This analysis enumerates combinations of 348 graded picks across 21 dates. Findings reflect the structural patterns in *this season's pick distribution*, not universal parlay truths. Patterns identified should be re-validated as the picks dataset grows. Subgroups with n<100 are excluded from interpretation.

## 1. Universe-Level Summary

| bucket | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| Stable | 408,209 | 55.0% | 73.1% | 27.2% | -18.2pp | +27.8pp |
| Safe | 548,170 | 33.3% | 57.0% | 25.0% | -23.6pp | +8.3pp |
| Reach | 96,881 | 14.3% | 40.1% | 22.8% | -25.7pp | -8.5pp |
| Degen | 2,459 | 5.5% | 28.1% | 20.7% | -22.6pp | -15.2pp |
| **ALL** | **1,055,719** | **39.9%** | **61.6%** | **25.7%** | **-21.7pp** | **+14.2pp** |

## 2. Bucket × Leg Count

| leg_count | Stable n | Stable hit_rate | Stable delta_vs_market | Safe n | Safe hit_rate | Safe delta_vs_market | Reach n | Reach hit_rate | Reach delta_vs_market | Degen n | Degen hit_rate | Degen delta_vs_market |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L=2 | 1,816 | 65.7% | -12.3pp | 224 | 54.9% | -5.5pp | 1 | 100.0% | +58.8pp | 0 | — | — |
| L=3 | 17,082 | 61.2% | -14.7pp | 5,688 | 38.3% | -21.0pp | 149 | 30.2% | -11.8pp | 0 | — | — |
| L=4 | 88,710 | 57.7% | -16.5pp | 67,868 | 34.2% | -23.8pp | 5,808 | 19.9% | -21.2pp | 27 | 18.5% | -10.5pp |
| L=5 | 300,601 | 53.8% | -18.9pp | 474,390 | 33.1% | -23.7pp | 90,923 | 13.9% | -26.1pp | 2,432 | 5.3% | -22.8pp |

## 3. Stable Bucket Investigation

### 3a. Stable by Leg Count

| leg_count | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| L=2 | 1,816 | 65.7% | 77.9% | 56.9% | -12.2pp | +8.8pp |
| L=3 | 17,082 | 61.2% | 76.0% | 43.1% | -14.7pp | +18.2pp |
| L=4 | 88,710 | 57.7% | 74.2% | 32.5% | -16.5pp | +25.1pp |
| L=5 | 300,601 | 53.8% | 72.6% | 24.6% | -18.9pp | +29.2pp |

### 3b. Stable by combined_market_prob bin (0.01-wide)

| bin | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| 0.66_0.67 | 33,932 | 46.9% | 66.5% | 26.1% | -19.6pp | +20.8pp |
| 0.67_0.68 | 34,134 | 49.1% | 67.5% | 26.2% | -18.4pp | +23.0pp |
| 0.68_0.69 | 32,718 | 51.1% | 68.5% | 26.3% | -17.4pp | +24.8pp |
| 0.69_0.70 | 31,961 | 52.2% | 69.5% | 26.5% | -17.2pp | +25.8pp |
| 0.70_0.71 | 30,303 | 54.4% | 70.5% | 26.6% | -16.1pp | +27.8pp |
| 0.71_0.72 | 28,520 | 53.3% | 71.5% | 26.9% | -18.2pp | +26.4pp |
| 0.72_0.73 | 27,799 | 53.7% | 72.5% | 27.0% | -18.8pp | +26.7pp |
| 0.73_0.74 | 26,859 | 56.3% | 73.5% | 26.9% | -17.2pp | +29.4pp |
| 0.74_0.75 | 24,966 | 56.8% | 74.5% | 27.2% | -17.6pp | +29.7pp |
| 0.75_0.76 | 22,728 | 58.2% | 75.5% | 27.5% | -17.3pp | +30.7pp |
| 0.76_0.77 | 19,828 | 60.6% | 76.5% | 27.8% | -15.9pp | +32.8pp |
| 0.77_0.78 | 17,922 | 59.7% | 77.5% | 28.2% | -17.8pp | +31.5pp |
| 0.78_0.79 | 16,054 | 57.6% | 78.5% | 28.3% | -20.8pp | +29.3pp |
| 0.79_0.80 | 14,339 | 58.0% | 79.5% | 28.4% | -21.5pp | +29.5pp |
| 0.80_0.81 | 12,769 | 60.0% | 80.5% | 28.9% | -20.5pp | +31.1pp |
| 0.81_0.82 | 10,945 | 60.9% | 81.5% | 29.2% | -20.6pp | +31.7pp |
| 0.82_0.83 | 9,231 | 64.8% | 82.5% | 29.6% | -17.7pp | +35.2pp |
| 0.83_0.84 | 7,367 | 66.4% | 83.5% | 30.2% | -17.0pp | +36.3pp |
| 0.84_0.85 | 5,834 | 63.3% | 84.5% | 31.1% | -21.2pp | +32.2pp |

### 3c. Stable — Top 5 Single-Hypothesis Subgroups (by delta_vs_market)

| hypothesis | subgroup | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| H2 | max_per_game_3plus | 43,679 | 57.2% | 72.4% | -15.2pp | +31.2pp |
| H5 | one_team_3plus_legs | 43,679 | 57.2% | 72.4% | -15.2pp | +31.2pp |
| H4 | dispersion_10_20 | 158,960 | 57.9% | 73.4% | -15.5pp | +31.6pp |
| H3 | zero_iron_floor | 264,031 | 57.4% | 73.4% | -16.0pp | +30.4pp |
| H1 | PTS | 209,547 | 57.5% | 73.9% | -16.4pp | +31.3pp |

### 3d. Stable — Bottom 5 Single-Hypothesis Subgroups (by delta_vs_market)

| hypothesis | subgroup | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| H3 | all_iron_floor | 252 | 28.2% | 77.3% | -49.1pp | -12.0pp |
| H1 | 3PM | 5,114 | 39.3% | 71.3% | -32.0pp | +8.0pp |
| H3 | two_plus_iron_floor_not_all | 51,506 | 47.3% | 72.7% | -25.4pp | +19.6pp |
| H1 | all_AST | 1,448 | 48.5% | 73.1% | -24.5pp | +9.2pp |
| H4 | dispersion_lt_05 | 77,161 | 50.2% | 73.2% | -22.9pp | +22.3pp |

## 4. Reach Bucket Investigation

### 4a. Reach by Leg Count

| leg_count | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| L=2 | 1 | — | — | — | — | — *insufficient_sample* |
| L=3 | 149 | 30.2% | 42.0% | 39.2% | -11.8pp | -9.0pp |
| L=4 | 5,808 | 19.9% | 41.1% | 29.6% | -21.2pp | -9.7pp |
| L=5 | 90,923 | 13.9% | 40.0% | 22.3% | -26.1pp | -8.4pp |

### 4b. Reach by combined_market_prob bin (0.01-wide)

| bin | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| 0.30_0.31 | 1,255 | 6.2% | 30.5% | 21.2% | -24.3pp | -15.0pp |
| 0.31_0.32 | 1,686 | 6.7% | 31.5% | 21.3% | -24.8pp | -14.6pp |
| 0.32_0.33 | 2,170 | 8.1% | 32.5% | 21.5% | -24.5pp | -13.4pp |
| 0.33_0.34 | 2,805 | 8.1% | 33.5% | 21.7% | -25.5pp | -13.7pp |
| 0.34_0.35 | 3,330 | 9.5% | 34.5% | 21.8% | -25.0pp | -12.3pp |
| 0.35_0.36 | 4,150 | 10.1% | 35.5% | 21.9% | -25.4pp | -11.9pp |
| 0.36_0.37 | 4,980 | 10.9% | 36.5% | 22.2% | -25.6pp | -11.3pp |
| 0.37_0.38 | 6,022 | 12.8% | 37.5% | 22.4% | -24.7pp | -9.6pp |
| 0.38_0.39 | 6,806 | 13.1% | 38.5% | 22.6% | -25.4pp | -9.5pp |
| 0.39_0.40 | 7,878 | 15.7% | 39.5% | 22.8% | -23.8pp | -7.1pp |
| 0.40_0.41 | 8,933 | 15.3% | 40.5% | 22.9% | -25.2pp | -7.6pp |
| 0.41_0.42 | 9,995 | 15.7% | 41.5% | 23.1% | -25.8pp | -7.4pp |
| 0.42_0.43 | 11,290 | 16.0% | 42.5% | 23.2% | -26.5pp | -7.2pp |
| 0.43_0.44 | 12,405 | 17.7% | 43.5% | 23.4% | -25.8pp | -5.6pp |
| 0.44_0.45 | 13,176 | 16.5% | 44.5% | 23.5% | -28.0pp | -7.0pp |

### 4c. Reach — Top 5 Single-Hypothesis Subgroups (by delta_vs_market)

| hypothesis | subgroup | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| H7 | one_player_3plus_legs | 640 | 40.5% | 38.7% | +1.7pp | +17.5pp |
| H3 | two_plus_iron_floor_not_all | 3,573 | 28.1% | 41.3% | -13.3pp | +2.4pp |
| H1 | REB | 3,413 | 24.5% | 41.3% | -16.8pp | +0.9pp |
| H1 | all_PTS | 472 | 19.7% | 39.7% | -20.0pp | -4.2pp |
| H4 | dispersion_lt_05 | 24,986 | 19.1% | 39.5% | -20.4pp | -3.1pp |

### 4d. Reach — Bottom 5 Single-Hypothesis Subgroups (by delta_vs_market)

| hypothesis | subgroup | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| H4 | dispersion_10_20 | 32,433 | 5.6% | 40.2% | -34.6pp | -17.4pp |
| H1 | all_AST | 411 | 9.0% | 41.4% | -32.4pp | -13.9pp |
| H1 | AST | 26,833 | 8.9% | 40.1% | -31.1pp | -13.5pp |
| H2 | all_cross_game | 10,854 | 11.6% | 40.8% | -29.2pp | -11.4pp |
| H5 | all_different_teams | 10,854 | 11.6% | 40.8% | -29.2pp | -11.4pp |

## 5. Per-Hypothesis Tables

Each row sorted by `delta_vs_market` descending within bucket. Rows with n<100 retain their position by label and are flagged *insufficient_sample*; they are excluded from the top/bottom rankings in section 7 but remain present here for reference.

### H1: Prop mix

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| PTS | 209,547 | 57.5% | 73.9% | 26.2% | -16.4pp | +31.3pp |
| REB | 15,783 | 54.4% | 72.7% | 29.9% | -18.2pp | +24.6pp |
| mixed | 106,145 | 53.9% | 72.6% | 27.8% | -18.7pp | +26.1pp |
| all_PTS | 8,993 | 57.1% | 76.0% | 28.1% | -18.9pp | +28.9pp |
| AST | 71,620 | 50.3% | 71.8% | 28.4% | -21.5pp | +21.9pp |
| all_AST | 1,448 | 48.5% | 73.1% | 39.4% | -24.5pp | +9.2pp |
| 3PM | 5,114 | 39.3% | 71.3% | 31.2% | -32.0pp | +8.0pp |
| all_3PM | 58 | — | — | — | — | — *insufficient_sample* |
| all_REB | 83 | — | — | — | — | — *insufficient_sample* |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| REB | 27,890 | 41.1% | 56.5% | 25.9% | -15.3pp | +15.3pp |
| mixed | 164,294 | 34.0% | 56.9% | 25.0% | -22.8pp | +9.0pp |
| AST | 160,199 | 33.3% | 56.6% | 25.0% | -23.4pp | +8.2pp |
| PTS | 178,376 | 33.0% | 57.6% | 24.8% | -24.5pp | +8.3pp |
| all_AST | 3,227 | 28.8% | 56.1% | 28.2% | -27.3pp | +0.6pp |
| all_PTS | 2,945 | 21.5% | 58.7% | 26.1% | -37.2pp | -4.6pp |
| 3PM | 17,411 | 17.8% | 55.8% | 27.3% | -38.0pp | -9.5pp |
| all_3PM | 39 | — | — | — | — | — *insufficient_sample* |
| all_REB | 41 | — | — | — | — | — *insufficient_sample* |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| REB | 3,413 | 24.5% | 41.3% | 23.7% | -16.8pp | +0.9pp |
| all_PTS | 472 | 19.7% | 39.7% | 23.9% | -20.0pp | -4.2pp |
| PTS | 32,332 | 18.0% | 39.8% | 22.8% | -21.8pp | -4.7pp |
| mixed | 30,580 | 14.2% | 40.1% | 22.8% | -25.9pp | -8.6pp |
| 3PM | 3,723 | 12.5% | 40.8% | 25.2% | -28.2pp | -12.6pp |
| AST | 26,833 | 8.9% | 40.1% | 22.4% | -31.1pp | -13.5pp |
| all_AST | 411 | 9.0% | 41.4% | 22.9% | -32.4pp | -13.9pp |
| all_3PM | 8 | — | — | — | — | — *insufficient_sample* |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| mixed | 805 | 8.8% | 28.0% | 21.0% | -19.2pp | -12.2pp |
| AST | 786 | 5.6% | 28.0% | 20.3% | -22.4pp | -14.7pp |
| PTS | 817 | 1.4% | 28.3% | 20.7% | -27.0pp | -19.3pp |
| 3PM | 38 | — | — | — | — | — *insufficient_sample* |
| REB | 13 | — | — | — | — | — *insufficient_sample* |
| all_AST | 4 | — | — | — | — | — *insufficient_sample* |

### H2: Cross-game vs same-game

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| max_per_game_3plus | 43,679 | 57.2% | 72.4% | 25.9% | -15.2pp | +31.2pp |
| has_same_game | 301,822 | 55.5% | 73.0% | 26.5% | -17.4pp | +29.0pp |
| max_per_game_2 | 258,143 | 55.3% | 73.0% | 26.6% | -17.8pp | +28.7pp |
| all_cross_game | 106,387 | 53.3% | 73.7% | 29.3% | -20.3pp | +24.1pp |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| all_cross_game | 105,216 | 35.5% | 57.6% | 26.1% | -22.1pp | +9.4pp |
| max_per_game_2 | 368,236 | 33.0% | 56.8% | 24.8% | -23.8pp | +8.2pp |
| has_same_game | 442,954 | 32.8% | 56.8% | 24.8% | -24.0pp | +8.0pp |
| max_per_game_3plus | 74,718 | 32.0% | 56.9% | 24.6% | -24.9pp | +7.3pp |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| max_per_game_3plus | 17,849 | 15.3% | 39.5% | 22.9% | -24.2pp | -7.6pp |
| has_same_game | 86,027 | 14.7% | 40.0% | 22.8% | -25.3pp | -8.1pp |
| max_per_game_2 | 68,178 | 14.5% | 40.1% | 22.8% | -25.6pp | -8.2pp |
| all_cross_game | 10,854 | 11.6% | 40.8% | 23.0% | -29.2pp | -11.4pp |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| max_per_game_2 | 1,510 | 6.7% | 28.2% | 20.6% | -21.5pp | -13.9pp |
| has_same_game | 2,374 | 5.6% | 28.1% | 20.7% | -22.5pp | -15.1pp |
| max_per_game_3plus | 864 | 3.8% | 28.0% | 21.0% | -24.2pp | -17.2pp |
| all_cross_game | 85 | — | — | — | — | — *insufficient_sample* |

### H3: Iron_floor concentration

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| zero_iron_floor | 264,031 | 57.4% | 73.4% | 27.0% | -16.0pp | +30.4pp |
| one_iron_floor | 92,420 | 52.3% | 72.7% | 27.7% | -20.4pp | +24.7pp |
| two_plus_iron_floor_not_all | 51,506 | 47.3% | 72.7% | 27.7% | -25.4pp | +19.6pp |
| all_iron_floor | 252 | 28.2% | 77.3% | 40.1% | -49.1pp | -12.0pp |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| zero_iron_floor | 346,535 | 33.3% | 56.8% | 24.7% | -23.6pp | +8.5pp |
| one_iron_floor | 150,851 | 33.1% | 56.8% | 25.5% | -23.7pp | +7.6pp |
| two_plus_iron_floor_not_all | 50,725 | 34.5% | 58.5% | 26.0% | -23.9pp | +8.6pp |
| all_iron_floor | 59 | — | — | — | — | — *insufficient_sample* |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| two_plus_iron_floor_not_all | 3,573 | 28.1% | 41.3% | 25.8% | -13.3pp | +2.4pp |
| one_iron_floor | 21,956 | 19.4% | 40.7% | 23.7% | -21.3pp | -4.3pp |
| zero_iron_floor | 71,345 | 12.1% | 39.8% | 22.4% | -27.8pp | -10.3pp |
| all_iron_floor | 7 | — | — | — | — | — *insufficient_sample* |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_iron_floor | 226 | 22.6% | 28.5% | 22.4% | -5.9pp | +0.1pp |
| zero_iron_floor | 2,220 | 3.5% | 28.1% | 20.5% | -24.6pp | -17.0pp |
| two_plus_iron_floor_not_all | 13 | — | — | — | — | — *insufficient_sample* |

### H4: Confidence dispersion

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| dispersion_10_20 | 158,960 | 57.9% | 73.4% | 26.3% | -15.5pp | +31.6pp |
| dispersion_05_10 | 172,033 | 54.4% | 72.9% | 27.7% | -18.5pp | +26.7pp |
| dispersion_lt_05 | 77,161 | 50.2% | 73.2% | 28.0% | -22.9pp | +22.3pp |
| dispersion_gte_20 | 55 | — | — | — | — | — *insufficient_sample* |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| dispersion_05_10 | 244,806 | 35.6% | 57.1% | 25.2% | -21.5pp | +10.4pp |
| dispersion_10_20 | 197,094 | 32.1% | 57.0% | 24.9% | -24.9pp | +7.2pp |
| dispersion_lt_05 | 106,258 | 30.4% | 56.7% | 25.0% | -26.2pp | +5.5pp |
| dispersion_gte_20 | 12 | — | — | — | — | — *insufficient_sample* |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| dispersion_lt_05 | 24,986 | 19.1% | 39.5% | 22.2% | -20.4pp | -3.1pp |
| dispersion_05_10 | 39,462 | 18.5% | 40.4% | 23.0% | -21.9pp | -4.5pp |
| dispersion_10_20 | 32,433 | 5.6% | 40.2% | 23.0% | -34.6pp | -17.4pp |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| dispersion_lt_05 | 1,047 | 9.7% | 28.0% | 20.2% | -18.2pp | -10.4pp |
| dispersion_05_10 | 676 | 4.9% | 28.3% | 20.6% | -23.5pp | -15.7pp |
| dispersion_10_20 | 736 | 0.0% | 28.2% | 21.6% | -28.2pp | -21.6pp |

### H5: Same-team concentration

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_team_3plus_legs | 43,679 | 57.2% | 72.4% | 25.9% | -15.2pp | +31.2pp |
| one_team_2_legs | 258,143 | 55.3% | 73.0% | 26.6% | -17.8pp | +28.7pp |
| all_different_teams | 106,387 | 53.3% | 73.7% | 29.3% | -20.3pp | +24.1pp |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| all_different_teams | 105,216 | 35.5% | 57.6% | 26.1% | -22.1pp | +9.4pp |
| one_team_2_legs | 368,236 | 33.0% | 56.8% | 24.8% | -23.8pp | +8.2pp |
| one_team_3plus_legs | 74,718 | 32.0% | 56.9% | 24.6% | -24.9pp | +7.3pp |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_team_3plus_legs | 17,849 | 15.3% | 39.5% | 22.9% | -24.2pp | -7.6pp |
| one_team_2_legs | 68,178 | 14.5% | 40.1% | 22.8% | -25.6pp | -8.2pp |
| all_different_teams | 10,854 | 11.6% | 40.8% | 23.0% | -29.2pp | -11.4pp |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_team_2_legs | 1,510 | 6.7% | 28.2% | 20.6% | -21.5pp | -13.9pp |
| one_team_3plus_legs | 864 | 3.8% | 28.0% | 21.0% | -24.2pp | -17.2pp |
| all_different_teams | 85 | — | — | — | — | — *insufficient_sample* |

### H6: Confidence vs market delta

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| system_pessimistic | 408,208 | 55.0% | 73.1% | 27.2% | -18.2pp | +27.8pp |
| edge_small | 1 | — | — | — | — | — *insufficient_sample* |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| system_pessimistic | 548,126 | 33.3% | 57.0% | 25.0% | -23.6pp | +8.3pp |
| edge_medium | 7 | — | — | — | — | — *insufficient_sample* |
| edge_small | 37 | — | — | — | — | — *insufficient_sample* |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| system_pessimistic | 96,831 | 14.3% | 40.1% | 22.8% | -25.8pp | -8.5pp |
| edge_large | 1 | — | — | — | — | — *insufficient_sample* |
| edge_medium | 9 | — | — | — | — | — *insufficient_sample* |
| edge_small | 40 | — | — | — | — | — *insufficient_sample* |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| system_pessimistic | 2,448 | 5.3% | 28.1% | 20.7% | -22.8pp | -15.4pp |
| edge_small | 11 | — | — | — | — | — *insufficient_sample* |

### H7: Per-player concentration

**Stable bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_player_2_legs | 125,692 | 55.2% | 72.9% | 26.3% | -17.7pp | +28.9pp |
| all_different_players | 279,772 | 54.9% | 73.2% | 27.7% | -18.3pp | +27.3pp |
| one_player_3plus_legs | 2,745 | 49.6% | 72.1% | 26.2% | -22.4pp | +23.4pp |

**Safe bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_player_2_legs | 170,050 | 35.0% | 57.1% | 24.8% | -22.1pp | +10.2pp |
| all_different_players | 374,210 | 32.7% | 56.9% | 25.2% | -24.2pp | +7.6pp |
| one_player_3plus_legs | 3,910 | 19.5% | 58.3% | 24.9% | -38.9pp | -5.5pp |

**Reach bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_player_3plus_legs | 640 | 40.5% | 38.7% | 22.9% | +1.7pp | +17.5pp |
| one_player_2_legs | 31,410 | 18.5% | 39.9% | 22.7% | -21.4pp | -4.2pp |
| all_different_players | 64,831 | 12.0% | 40.2% | 22.9% | -28.1pp | -10.8pp |

**Degen bucket**

| subgroup | n | actual_hit_rate | expected_market | expected_system | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| one_player_2_legs | 881 | 7.3% | 28.2% | 20.8% | -20.9pp | -13.5pp |
| all_different_players | 1,555 | 4.5% | 28.1% | 20.7% | -23.6pp | -16.2pp |
| one_player_3plus_legs | 23 | — | — | — | — | — *insufficient_sample* |

## 6. Compound Archetypes

Pre-defined parlay-construction strategies. One table per bucket. Rows sorted by `delta_vs_market` descending.

### Stable bucket — compound archetypes

| archetype | description | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | all cross-game, 2 legs | 1,494 | 65.6% | 78.0% | -12.4pp | +8.8pp |
| A10 | tight uniform conf (dispersion <5pp), 2 legs | 1,204 | 65.5% | 77.9% | -12.4pp | +8.7pp |
| A3 | all cross-game, REB-dominant | 4,841 | 58.7% | 73.5% | -14.8pp | +26.7pp |
| A2 | all cross-game, 3 legs | 10,273 | 60.7% | 76.0% | -15.4pp | +17.7pp |
| A7 | all unique games, PTS or REB dominant | 57,858 | 54.5% | 74.3% | -19.8pp | +26.4pp |
| A8 | min leg conf ≥ 80%, 2 legs | 124 | 58.1% | 78.9% | -20.8pp | -6.3pp |
| A9 | min leg conf ≥ 80%, 3 legs | 332 | 54.5% | 75.5% | -21.0pp | +2.7pp |
| A5 | ≥2 iron_floor legs, ≤4 legs | 11,309 | 51.4% | 74.8% | -23.4pp | +16.2pp |
| A4 | all iron_floor, ≤3 legs | 110 | 40.0% | 79.7% | -39.7pp | -10.0pp |
| A6 | all cross-game, all REB | 83 | — | — | — | — *insufficient_sample* |

### Safe bucket — compound archetypes

| archetype | description | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | all cross-game, 2 legs | 182 | 55.5% | 60.7% | -5.2pp | +0.6pp |
| A10 | tight uniform conf (dispersion <5pp), 2 legs | 143 | 53.1% | 59.9% | -6.8pp | -1.1pp |
| A3 | all cross-game, REB-dominant | 6,018 | 45.7% | 57.4% | -11.7pp | +18.6pp |
| A5 | ≥2 iron_floor legs, ≤4 legs | 4,124 | 39.8% | 59.1% | -19.3pp | +5.9pp |
| A7 | all unique games, PTS or REB dominant | 39,113 | 35.7% | 58.1% | -22.4pp | +9.8pp |
| A2 | all cross-game, 3 legs | 3,256 | 36.8% | 59.5% | -22.7pp | -4.5pp |
| A4 | all iron_floor, ≤3 legs | 23 | — | — | — | — *insufficient_sample* |
| A6 | all cross-game, all REB | 41 | — | — | — | — *insufficient_sample* |
| A9 | min leg conf ≥ 80%, 3 legs | 21 | — | — | — | — *insufficient_sample* |

### Reach bucket — compound archetypes

| archetype | description | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| A3 | all cross-game, REB-dominant | 323 | 30.6% | 42.3% | -11.6pp | +6.4pp |
| A5 | ≥2 iron_floor legs, ≤4 legs | 169 | 30.8% | 42.7% | -11.9pp | -3.2pp |
| A7 | all unique games, PTS or REB dominant | 4,117 | 16.1% | 40.6% | -24.5pp | -7.1pp |
| A1 | all cross-game, 2 legs | 1 | — | — | — | — *insufficient_sample* |
| A10 | tight uniform conf (dispersion <5pp), 2 legs | 1 | — | — | — | — *insufficient_sample* |
| A2 | all cross-game, 3 legs | 62 | — | — | — | — *insufficient_sample* |

### Degen bucket — compound archetypes

| archetype | description | n | actual_hit_rate | expected_market | delta_vs_market | delta_vs_system |
| --- | --- | --- | --- | --- | --- | --- |
| A7 | all unique games, PTS or REB dominant | 36 | — | — | — | — *insufficient_sample* |

## 7. Top 10 / Bottom 10 Archetypes (Universe)

Pool: all single-hypothesis subgroups + compound archetypes with n ≥ 100.

### 7a. Top 10 by delta_vs_market (descending)

| rank | hypothesis | bucket | subgroup | n | actual_hit_rate | delta_vs_market |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | H7 | Reach | one_player_3plus_legs | 640 | 40.5% | +1.7pp |
| 2 | ARCH | Safe | A1 | 182 | 55.5% | -5.2pp |
| 3 | H3 | Degen | one_iron_floor | 226 | 22.6% | -5.9pp |
| 4 | ARCH | Safe | A10 | 143 | 53.1% | -6.8pp |
| 5 | ARCH | Reach | A3 | 323 | 30.6% | -11.6pp |
| 6 | ARCH | Safe | A3 | 6,018 | 45.7% | -11.7pp |
| 7 | ARCH | Reach | A5 | 169 | 30.8% | -11.9pp |
| 8 | ARCH | Stable | A1 | 1,494 | 65.6% | -12.4pp |
| 9 | ARCH | Stable | A10 | 1,204 | 65.5% | -12.4pp |
| 10 | H3 | Reach | two_plus_iron_floor_not_all | 3,573 | 28.1% | -13.3pp |

### 7b. Bottom 10 by delta_vs_market (ascending)

| rank | hypothesis | bucket | subgroup | n | actual_hit_rate | delta_vs_market |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | H3 | Stable | all_iron_floor | 252 | 28.2% | -49.1pp |
| 2 | ARCH | Stable | A4 | 110 | 40.0% | -39.7pp |
| 3 | H7 | Safe | one_player_3plus_legs | 3,910 | 19.5% | -38.9pp |
| 4 | H1 | Safe | 3PM | 17,411 | 17.8% | -38.0pp |
| 5 | H1 | Safe | all_PTS | 2,945 | 21.5% | -37.2pp |
| 6 | H4 | Reach | dispersion_10_20 | 32,433 | 5.6% | -34.6pp |
| 7 | H1 | Reach | all_AST | 411 | 9.0% | -32.4pp |
| 8 | H1 | Stable | 3PM | 5,114 | 39.3% | -32.0pp |
| 9 | H1 | Reach | AST | 26,833 | 8.9% | -31.1pp |
| 10 | H2 | Reach | all_cross_game | 10,854 | 11.6% | -29.2pp |
