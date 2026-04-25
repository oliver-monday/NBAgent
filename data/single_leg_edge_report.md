# Single-Leg Edge Analysis: Conf-vs-Market Delta vs Actual Hit Rate

## Section 1: Header & metadata

| field | value |
| --- | --- |
| date_generated | 2026-04-25 00:01:19 |
| source_file | data/picks.json |
| total_picks_loaded | 1138 |
| picks_passing_filter | 348 |
| date_range_min | 2026-03-31 |
| date_range_max | 2026-04-23 |
| overall_hit_rate | 85.6% |

## Section 2: Caveats

**Truncated distribution.** This analysis covers only picks the analyst emitted, typically those with `confidence_pct ≥ 70`. Findings describe the relationship between delta and hit rate within the emitted subset. They do NOT predict what would happen if the filter were tightened to high-delta picks only.

**Partial odds coverage.** market_implied_prob is missing for earlier-season picks (before OddsAPI infrastructure shipped). Filtering for picks with the field reduces the dataset substantially. Findings represent the period since odds coverage began.

## Section 3: Distribution of delta values

### 3a — Quantile summary

| statistic | delta |
| --- | --- |
| min | -0.2859 |
| p05 | -0.2524 |
| p10 | -0.2383 |
| p25 | -0.2012 |
| p50 | -0.1477 |
| p75 | -0.1013 |
| p90 | -0.0561 |
| p95 | -0.0219 |
| max | +0.1567 |

### 3b — Histogram (bin width = 0.01, half-open [lo, hi))

| bin | n |
| --- | --- |
| [-0.29, -0.28) | 7 |
| [-0.28, -0.27) | 8 |
| [-0.26, -0.25) | 7 |
| [-0.25, -0.24) | 9 |
| [-0.24, -0.23) | 22 |
| [-0.23, -0.22) | 15 |
| [-0.22, -0.21) | 10 |
| [-0.21, -0.20) | 11 |
| [-0.20, -0.19) | 15 |
| [-0.19, -0.18) | 11 |
| [-0.18, -0.17) | 23 |
| [-0.17, -0.16) | 23 |
| [-0.16, -0.15) | 11 |
| [-0.15, -0.14) | 20 |
| [-0.14, -0.13) | 20 |
| [-0.13, -0.12) | 19 |
| [-0.12, -0.11) | 16 |
| [-0.11, -0.10) | 15 |
| [-0.10, -0.09) | 15 |
| [-0.09, -0.08) | 13 |
| [-0.08, -0.07) | 9 |
| [-0.07, -0.06) | 12 |
| [-0.06, -0.05) | 4 |
| [-0.05, -0.04) | 7 |
| [-0.04, -0.03) | 4 |
| [-0.03, -0.02) | 5 |
| [-0.01, +0.00) | 1 |
| [+0.00, +0.01) | 7 |
| [+0.01, +0.02) | 1 |
| [+0.03, +0.04) | 1 |
| [+0.04, +0.05) | 2 |
| [+0.06, +0.07) | 1 |
| [+0.09, +0.10) | 2 |
| [+0.11, +0.12) | 1 |
| [+0.15, +0.16) | 1 |

## Section 4: Banding A — Deciles (data-led)

| decile | delta_min | delta_max | mean_delta | n | hits | hit_rate | mean_conf | mean_market |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | -0.2859 | -0.2383 | -0.2596 | 35 | 32 | 91.4% | +0.7109 | +0.9704 |
| 1 | -0.2383 | -0.2177 | -0.2298 | 35 | 33 | 94.3% | +0.7337 | +0.9635 |
| 2 | -0.2167 | -0.1877 | -0.2027 | 35 | 32 | 91.4% | +0.7426 | +0.9453 |
| 3 | -0.1859 | -0.1691 | -0.1768 | 35 | 32 | 91.4% | +0.7594 | +0.9362 |
| 4 | -0.1691 | -0.1477 | -0.1598 | 34 | 31 | 91.2% | +0.7650 | +0.9248 |
| 5 | -0.1477 | -0.1333 | -0.1398 | 35 | 28 | 80.0% | +0.7700 | +0.9098 |
| 6 | -0.1333 | -0.1147 | -0.1225 | 35 | 32 | 91.4% | +0.7729 | +0.8953 |
| 7 | -0.1133 | -0.0889 | -0.1017 | 35 | 28 | 80.0% | +0.7680 | +0.8697 |
| 8 | -0.0867 | -0.0551 | -0.0715 | 35 | 26 | 74.3% | +0.7709 | +0.8424 |
| 9 | -0.0533 | +0.1567 | +0.0015 | 34 | 24 | 70.6% | +0.7697 | +0.7682 |

## Section 5: Banding B — Semantic tags (overall, all props)

### 5a — All props

| band | delta_range | n | hits | hit_rate | mean_delta | mean_conf | mean_market | flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deep_fade | delta < -0.10 | 262 | 234 | 89.3% | -0.1792 | +0.7513 | +0.9305 |  |
| fade | -0.10 ≤ delta < -0.05 | 53 | 41 | 77.4% | -0.0789 | +0.7745 | +0.8534 |  |
| mild_fade | -0.05 ≤ delta < +0.00 | 17 | 11 | 64.7% | -0.0347 | +0.7647 | +0.7994 |  |
| mild_edge | +0.00 ≤ delta < +0.05 | 11 | 7 | 63.6% | +0.0149 | +0.7745 | +0.7596 |  |
| medium_edge | +0.05 ≤ delta < +0.10 | 3 | 3 | 100.0% | +0.0851 | +0.7433 | +0.6583 |  |
| strong_edge | delta ≥ +0.10 | 2 | 2 | 100.0% | +0.1371 | +0.7700 | +0.6329 |  |

## Section 6: Banding B — Per-prop breakdown

### 6.1 — PTS

| band | delta_range | n | hits | hit_rate | mean_delta | mean_conf | mean_market | flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deep_fade | delta < -0.10 | 133 | 122 | 91.7% | -0.1984 | +0.7409 | +0.9394 |  |
| fade | -0.10 ≤ delta < -0.05 | 17 | 13 | 76.5% | -0.0765 | +0.7659 | +0.8423 |  |
| mild_fade | -0.05 ≤ delta < +0.00 | 2 | 1 | 50.0% | -0.0299 | +0.7400 | +0.7699 | insufficient_sample |
| mild_edge | +0.00 ≤ delta < +0.05 | 3 | 2 | 66.7% | +0.0173 | +0.7733 | +0.7560 | insufficient_sample |
| medium_edge | +0.05 ≤ delta < +0.10 | 1 | 1 | 100.0% | +0.0676 | +0.7000 | +0.6324 | insufficient_sample |
| strong_edge | delta ≥ +0.10 | 0 | 0 | — | — | — | — | no_data |

### 6.2 — REB

| band | delta_range | n | hits | hit_rate | mean_delta | mean_conf | mean_market | flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deep_fade | delta < -0.10 | 31 | 30 | 96.8% | -0.1582 | +0.7745 | +0.9327 |  |
| fade | -0.10 ≤ delta < -0.05 | 2 | 2 | 100.0% | -0.0639 | +0.8100 | +0.8739 | insufficient_sample |
| mild_fade | -0.05 ≤ delta < +0.00 | 1 | 1 | 100.0% | -0.0414 | +0.7800 | +0.8214 | insufficient_sample |
| mild_edge | +0.00 ≤ delta < +0.05 | 2 | 1 | 50.0% | +0.0271 | +0.7600 | +0.7329 | insufficient_sample |
| medium_edge | +0.05 ≤ delta < +0.10 | 1 | 1 | 100.0% | +0.0975 | +0.7800 | +0.6825 | insufficient_sample |
| strong_edge | delta ≥ +0.10 | 1 | 1 | 100.0% | +0.1175 | +0.8000 | +0.6825 | insufficient_sample |

### 6.3 — AST

| band | delta_range | n | hits | hit_rate | mean_delta | mean_conf | mean_market | flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deep_fade | delta < -0.10 | 74 | 63 | 85.1% | -0.1616 | +0.7538 | +0.9154 |  |
| fade | -0.10 ≤ delta < -0.05 | 24 | 19 | 79.2% | -0.0835 | +0.7750 | +0.8585 |  |
| mild_fade | -0.05 ≤ delta < +0.00 | 8 | 4 | 50.0% | -0.0307 | +0.7550 | +0.7856 | insufficient_sample |
| mild_edge | +0.00 ≤ delta < +0.05 | 2 | 1 | 50.0% | +0.0027 | +0.7650 | +0.7623 | insufficient_sample |
| medium_edge | +0.05 ≤ delta < +0.10 | 0 | 0 | — | — | — | — | no_data |
| strong_edge | delta ≥ +0.10 | 1 | 1 | 100.0% | +0.1567 | +0.7400 | +0.5833 | insufficient_sample |

### 6.4 — 3PM

| band | delta_range | n | hits | hit_rate | mean_delta | mean_conf | mean_market | flag |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deep_fade | delta < -0.10 | 24 | 19 | 79.2% | -0.1540 | +0.7708 | +0.9249 |  |
| fade | -0.10 ≤ delta < -0.05 | 10 | 7 | 70.0% | -0.0749 | +0.7810 | +0.8559 | insufficient_sample |
| mild_fade | -0.05 ≤ delta < +0.00 | 6 | 5 | 83.3% | -0.0405 | +0.7833 | +0.8238 | insufficient_sample |
| mild_edge | +0.00 ≤ delta < +0.05 | 4 | 3 | 75.0% | +0.0131 | +0.7875 | +0.7744 | insufficient_sample |
| medium_edge | +0.05 ≤ delta < +0.10 | 1 | 1 | 100.0% | +0.0901 | +0.7500 | +0.6599 | insufficient_sample |
| strong_edge | delta ≥ +0.10 | 0 | 0 | — | — | — | — | no_data |

## Section 7: No interpretive commentary

This report is data only. Interpretation of whether deciles trend up, whether semantic tags map to anything meaningful, or what the action implication is — lives in chat, not in this file.
