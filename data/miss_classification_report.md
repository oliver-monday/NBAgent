# Miss Classification Population Analysis

_Read-only descriptive analysis over `data/audit_log.json`. Decision input for the next major workstream choice. No rules ship from this report._

_v3 enrichment: extends v2 (confidence-band analysis, per-prop/per-player miss rates from picks.json volume baseline, tightened keyword detection) with two new keyword patterns (`expected_variance_lang`, `reasoning_was_sound`) calibrated against actual auditor variance-class language. Variance-class keyword coverage expanded from ~10% (v2 top pattern) to substantially higher. v1 and v2 sections retain their structure._

---

## 1. Overview

Population characterization of graded miss data. This is descriptive analysis only — no rules ship from this report. Output informs the offseason workstream-choice conversation.

- Date range: **2026-03-05 → 2026-04-30**
- Audit entries (unique slate dates): **47**
- Total miss rows analyzed: **172**
- Null/ungraded `miss_classification` rows excluded: **7**
- Total graded picks in baseline (denominator for miss rates): **1215**
- Audit miss rows successfully joined to picks.json: **172 of 172 (100.0%)**
- Keyword detection: **v3** with negation guards (30-char lookback), causal-phrase tightening, and variance-class coverage expansion (16 pattern groups, +2 over v2)
- `model_gap` (legacy alias) and `model_gap_signal` are bucketed identically as `catchable_with_new_data` but reported separately so audit-time taxonomy drift remains visible.


---

## 2. Taxonomy Breakdown (7 classes)

Counts and percentages by raw `miss_classification` value. `model_gap` is the legacy alias for `model_gap_signal`.

|classification|count|% of total|
|---|---|---|
|variance|68|39.5%|
|model_gap_rule|59|34.3%|
|model_gap_signal|12|7.0%|
|model_gap|12|7.0%|
|injury_event|10|5.8%|
|workflow_gap|6|3.5%|
|selection_error|5|2.9%|
|**TOTAL**|**172**|**100.0%**|

---

## 3. Four-Bucket Roll-up (Roadmap View)

Roll-up of the 7-class taxonomy into the four buckets named in `docs/ROADMAP_active.md`. Sums must equal the 7-class total.

|roadmap bucket|underlying classes|count|% of total|
|---|---|---|---|
|catchable_with_current_signals|selection_error|5|2.9%|
|deterministic_rule_catchable|model_gap_rule, workflow_gap|65|37.8%|
|catchable_with_new_data|model_gap_signal, model_gap|24|14.0%|
|inherent_variance|variance, injury_event|78|45.3%|
|**TOTAL**|—|**172**|**100.0%**|

---

## 4. Keyword Pattern Frequency Within Each Classification

For each classification with `n >= 5`, the top-5 keyword patterns. v2 detection: causal-phrase matching with negation guards (a phrase match is suppressed if a negation marker — `no`, `not`, `without`, `never`, `absent`, `isn't`, `wasn't`, `didn't` — appears within 30 characters before the match position). A single miss can match multiple patterns; counts are independent. This is the core analytical output — pattern dominance within a class points to the highest-leverage workstream for that class.

### variance (n=68)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|reasoning_was_sound|56|82.4%|
|expected_variance_lang|48|70.6%|
|near_miss_variance|14|20.6%|
|blowout|6|8.8%|
|fg_cold|5|7.4%|

### model_gap_rule (n=59)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|reasoning_was_sound|34|57.6%|
|blowout|11|18.6%|
|fg_margin_thin|10|16.9%|
|near_miss_variance|10|16.9%|
|minutes_compression|5|8.5%|

### model_gap_signal (n=12)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|reasoning_was_sound|5|41.7%|
|blowout|3|25.0%|
|minutes_compression|3|25.0%|
|rebounding_competition|1|8.3%|
|suppressor_cross_prop|1|8.3%|

### model_gap (n=12)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|blowout|3|25.0%|
|reasoning_was_sound|3|25.0%|
|minutes_compression|2|16.7%|
|expected_variance_lang|1|8.3%|
|near_miss_variance|1|8.3%|

### injury_event (n=10)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|injury_exit|6|60.0%|
|reasoning_was_sound|3|30.0%|
|fg_margin_thin|1|10.0%|
|tier_walk_market|1|10.0%|
|volatile_tag|1|10.0%|

### workflow_gap (n=6)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|reasoning_was_sound|1|16.7%|

### selection_error (n=5)

|pattern_key|matches|% of misses in this class|
|---|---|---|
|reasoning_was_sound|2|40.0%|
|near_miss_variance|1|20.0%|
|volatile_tag|1|20.0%|

---

## 5. Prop-Type Concentration

Miss distribution across the 4 prop types, with v2 miss-rate column. Miss rate denominator is graded picks only (HIT or MISS, not voided) from picks.json. The top-3 classification column is the per-prop view (denominator = misses in that prop), not the global view.

|prop_type|miss count|% of total misses|total picks (graded)|miss rate %|top-3 classifications|
|---|---|---|---|---|---|
|PTS|58|33.7%|475|12.2%|model_gap_rule 46.6%, variance 32.8%, injury_event 8.6%|
|REB|24|14.0%|193|12.4%|variance 41.7%, model_gap 16.7%, model_gap_rule 16.7%|
|AST|59|34.3%|357|16.5%|variance 40.7%, model_gap_rule 30.5%, model_gap_signal 11.9%|
|3PM|31|18.0%|190|16.3%|variance 48.4%, model_gap_rule 32.3%, model_gap 9.7%|
|**TOTAL**|**172**|**100.0%**|**1215**|—|—|

---

## 5a. Confidence Band Analysis (v2)

Cross-tab of pick volume and miss patterns against the system's stated `confidence_pct`. Bands defined as `70_74` / `75_79` / `80_84` / `85_89` / `90_plus`. Expected hit rate uses the band midpoint (95.0 for the open-ended top band). Overshoot = actual − expected; positive means the system is over-performing the band's confidence label, indicating a calibration gap. **All denominators in this section come from picks.json graded baseline (HIT or MISS, not voided), not audit_log.json.**

### 5a.1 — Pick volume by confidence band

|confidence_band|total picks (graded)|hits|misses|hit rate %|expected hit rate %|overshoot pp|
|---|---|---|---|---|---|---|
|70_74|512|440|72|85.9|72.5|+13.4|
|75_79|296|250|46|84.5|77.5|+7.0|
|80_84|359|314|45|87.5|82.5|+5.0|
|85_89|29|27|2|93.1|87.5|+5.6|
|90_plus|16|16|0|100.0|95.0|+5.0|
|<70 (unbanded)|3|3|0|100.0|—|—|
|**TOTAL**|**1215**|**1050**|**165**|—|—|—|

### 5a.2 — Miss classification breakdown within each band

Of misses within each confidence band, what fraction falls into each classification? Rows with `n_misses < 5` show insufficient-sample placeholder rather than degenerate percentages.

|confidence_band|n misses|variance %|model_gap_rule %|model_gap_signal %|model_gap %|injury_event %|workflow_gap %|selection_error %|
|---|---|---|---|---|---|---|---|---|
|70_74|78|35.9%|44.9%|3.8%|1.3%|9.0%|2.6%|2.6%|
|75_79|45|40.0%|26.7%|8.9%|13.3%|2.2%|2.2%|6.7%|
|80_84|47|44.7%|25.5%|8.5%|10.6%|4.3%|6.4%|0.0%|
|85_89|_(insufficient sample, n=2)_|—|—|—|—|—|—|—|
|90_plus|_(insufficient sample, n=0)_|—|—|—|—|—|—|—|

### 5a.3 — Razor-margin variance concentration by band

Of misses with `miss_classification == "variance"` AND `miss_margin <= 1` (razor), how do they distribute by band? This directly diagnoses whether band overshoot is concentrated in close-call variance — the central calibration recalibration question. If the lowest-confidence band's overshoot is large AND its razor-variance share is dominant, the band is over-predicting hits on near-miss cases (calibration target). Razor share denominator is all misses in the band, including injury_event rows where margin is null (those rows are excluded from the razor count by construction).
|confidence_band|razor variance misses|total band misses|razor share of band misses|
|---|---|---|---|
|70_74|9|78|11.5%|
|75_79|14|45|31.1%|
|80_84|15|47|31.9%|
|85_89|0|2|0.0%|
|90_plus|0|0|—|

---

## 6. Player Concentration

Top-10 players by total miss count, with v2 miss-rate column. Total picks denominator comes from picks.json graded baseline. Dossier-review flag requires BOTH `total_misses >= 5` AND `miss_rate_pct >= 15%` — this surfaces players whose miss rate is structurally elevated, not high-volume players with average rates.

|player_name|total_misses|total_picks|miss rate %|% of all misses|classification breakdown|dossier candidate|
|---|---|---|---|---|---|---|
|Donovan Mitchell|10|31|32.3%|5.8%|model_gap_rule=5, variance=3, model_gap=1, model_gap_signal=1|⚠|
|Derrick White|9|21|42.9%|5.2%|workflow_gap=4, model_gap=2, variance=2, model_gap_rule=1|⚠|
|Brandon Ingram|8|21|38.1%|4.7%|variance=4, model_gap_rule=2, model_gap_signal=1, injury_event=1|⚠|
|Alperen Sengun|6|26|23.1%|3.5%|variance=2, workflow_gap=2, model_gap=1, model_gap_rule=1|⚠|
|Jalen Johnson|6|32|18.8%|3.5%|variance=4, model_gap_rule=2|⚠|
|Nikola Jokic|6|33|18.2%|3.5%|model_gap_rule=5, variance=1|⚠|
|Jamal Murray|6|29|20.7%|3.5%|variance=5, model_gap_rule=1|⚠|
|Julius Randle|5|44|11.4%|2.9%|variance=3, model_gap_rule=2||
|Cade Cunningham|5|18|27.8%|2.9%|model_gap_rule=3, injury_event=2|⚠|
|Ausar Thompson|5|7|71.4%|2.9%|model_gap=2, variance=2, model_gap_rule=1|⚠|

Players flagged as dossier-review candidates (both `total_misses >= 5` AND `miss_rate_pct >= 15%`):

- **Donovan Mitchell** (10 misses on 31 picks = 32.3% miss rate, 5.8% of all misses) — candidate for player-specific dossier review.
- **Derrick White** (9 misses on 21 picks = 42.9% miss rate, 5.2% of all misses) — candidate for player-specific dossier review.
- **Brandon Ingram** (8 misses on 21 picks = 38.1% miss rate, 4.7% of all misses) — candidate for player-specific dossier review.
- **Alperen Sengun** (6 misses on 26 picks = 23.1% miss rate, 3.5% of all misses) — candidate for player-specific dossier review.
- **Jalen Johnson** (6 misses on 32 picks = 18.8% miss rate, 3.5% of all misses) — candidate for player-specific dossier review.
- **Nikola Jokic** (6 misses on 33 picks = 18.2% miss rate, 3.5% of all misses) — candidate for player-specific dossier review.
- **Jamal Murray** (6 misses on 29 picks = 20.7% miss rate, 3.5% of all misses) — candidate for player-specific dossier review.
- **Cade Cunningham** (5 misses on 18 picks = 27.8% miss rate, 2.9% of all misses) — candidate for player-specific dossier review.
- **Ausar Thompson** (5 misses on 7 picks = 71.4% miss rate, 2.9% of all misses) — candidate for player-specific dossier review.

---

## 7. Miss Margin Distribution

For each classification, the distribution of `miss_margin = pick_value - actual_value`. Rows where `actual_value` is `None` (typical of `injury_event`) are excluded from this section. This is critical for distinguishing 'near-miss variance' (razor/small margins, system was nearly right) from 'structural ceiling miss' (medium/large margins, system was wrong about the player's range).

|classification|n|mean|median|p25|p75|max|razor (≤1)|small (2–3)|medium (4–6)|large (7+)|
|---|---|---|---|---|---|---|---|---|---|---|
|variance|68|2.04|1.00|1.00|2.00|10.00|38|20|7|3|
|model_gap_rule|59|2.54|2.00|1.00|3.00|9.00|27|19|10|3|
|model_gap_signal|12|3.00|1.50|1.00|2.25|12.00|6|4|0|2|
|model_gap|12|2.50|2.00|1.75|4.00|4.00|3|5|4|0|
|injury_event|8|4.75|2.50|1.00|6.75|15.00|3|2|1|2|
|workflow_gap|6|5.33|4.00|2.50|8.50|10.00|0|2|2|2|
|selection_error|5|2.40|2.00|2.00|2.00|4.00|0|4|1|0|

---

## 8. Regular-Season vs. Playoff Split

Regular-season slates: 118 miss rows. Playoff slates (date ≥ 2026-04-18): 54 miss rows. Playoff sample is small as of session date; classifications with >5pp divergence are flagged but should be investigated rather than treated as structural changes.

|classification|reg-season n|% of reg|playoff n|% of playoff|delta (pp)|divergent (>5pp)|
|---|---|---|---|---|---|---|
|variance|49|41.5%|19|35.2%|-6.3pp|⚠|
|model_gap_rule|36|30.5%|23|42.6%|+12.1pp|⚠|
|model_gap_signal|6|5.1%|6|11.1%|+6.0pp|⚠|
|model_gap|12|10.2%|0|0.0%|-10.2pp|⚠|
|injury_event|4|3.4%|6|11.1%|+7.7pp|⚠|
|workflow_gap|6|5.1%|0|0.0%|-5.1pp|⚠|
|selection_error|5|4.2%|0|0.0%|-4.2pp||
|**TOTAL**|**118**|**100.0%**|**54**|**100.0%**|—|—|

Classifications with >5pp playoff-vs-regular divergence:

- **variance**: regular 41.5% → playoff 35.2% (-6.3pp) — investigate.
- **model_gap_rule**: regular 30.5% → playoff 42.6% (+12.1pp) — investigate.
- **model_gap_signal**: regular 5.1% → playoff 11.1% (+6.0pp) — investigate.
- **model_gap**: regular 10.2% → playoff 0.0% (-10.2pp) — investigate.
- **injury_event**: regular 3.4% → playoff 11.1% (+7.7pp) — investigate.
- **workflow_gap**: regular 5.1% → playoff 0.0% (-5.1pp) — investigate.

---

## 9. Findings & Workstream Recommendation

This section surfaces population patterns to inform the next major workstream choice. **It does not prescribe rule changes.** Any rule candidate named below requires its own backtest before shipping, per project discipline.

### What dominates the catchable population?

Excluding `inherent_variance` (78 rows, 45.3% of all misses), the catchable population is 94 rows. Bucket shares within the catchable population:


|bucket|count|% of catchable population|
|---|---|---|
|catchable_with_current_signals|5|5.3% of catchable population|
|deterministic_rule_catchable|65|69.1% of catchable population|
|catchable_with_new_data|24|25.5% of catchable population|


**Largest catchable bucket:** `deterministic_rule_catchable` — points toward this as the highest-leverage workstream class. Per-pattern analysis below names the candidate areas for that bucket.


### Within `deterministic_rule_catchable` (model_gap_rule + workflow_gap):

Top-3 keyword patterns — candidates for new prompt rules. Each requires its own backtest.


|pattern_key|matches|
|---|---|
|reasoning_was_sound|35|
|blowout|11|
|fg_margin_thin|10|

### Within `catchable_with_new_data` (model_gap_signal + model_gap):

Top-3 keyword patterns — candidates for new data fields in `agents/quant.py` or new ingest pipelines.


|pattern_key|matches|
|---|---|
|reasoning_was_sound|8|
|blowout|6|
|minutes_compression|5|

### Notable single-pick concentration

- **Donovan Mitchell** (10 misses, 5.8% of total) — dossier-review candidate.
- **Derrick White** (9 misses, 5.2% of total) — dossier-review candidate.

### Calibration check

- `variance` accounts for 45.3% of total misses and 85.3% of variance misses are razor/small (margin ≤ 3 units).
- This pattern suggests **calibration** is the dominant issue, not new signals. Consider per-band confidence floor recalibration or per-player calibration extension as the next workstream rather than new rules.

### Confidence band overshoot diagnostic (v2)

- `70_74`: actual hit rate 85.9% vs expected 72.5% → overshoot +13.4pp on 512 graded picks. Razor-variance share of band misses: 9/78 = 11.5%.
- `75_79`: actual hit rate 84.5% vs expected 77.5% → overshoot +7.0pp on 296 graded picks. Razor-variance share of band misses: 14/45 = 31.1%.
- `80_84`: actual hit rate 87.5% vs expected 82.5% → overshoot +5.0pp on 359 graded picks. Razor-variance share of band misses: 15/47 = 31.9%.
- `85_89`: actual hit rate 93.1% vs expected 87.5% → overshoot +5.6pp on 29 graded picks. Razor-variance share of band misses: 0/2 = 0.0%.
- `90_plus`: actual hit rate 100.0% vs expected 95.0% → overshoot +5.0pp on 16 graded picks. Razor-variance share of band misses: 0/0 = 0.0%.

The `70_74` band has overshoot (+13.4pp) but the variance is not concentrated in razor margins (11.5% razor share). The diagnosis is more nuanced — recalibration alone may not capture the full structure of band misses.

### Per-prop miss rate diagnostic (v2)

|prop_type|misses|picks|miss rate %|ratio vs min|flagged (>1.5×)|
|---|---|---|---|---|---|
|PTS|58|475|12.2%|1.00x||
|REB|24|193|12.4%|1.02x||
|AST|59|357|16.5%|1.35x||
|3PM|31|190|16.3%|1.34x||

No prop is more than 1.5× the lowest-rate prop. Per-prop miss rates are roughly proportional.

### Open question for human review

Given that `deterministic_rule_catchable` is the largest catchable bucket and `reasoning_was_sound` is its top pattern: is the next workstream a `reasoning_was_sound`-rule expansion (with backtest), or do we accept that variance level and prioritize the next-largest bucket instead?
