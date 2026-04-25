# Playoff Trajectory Sweep — Candidate Annotations
*Generated: 2026-04-24*

This file is the OUTPUT of `tools/playoff_trajectory_sweep.py`. 
It is overwritten on each run. Review each candidate, approve/reject, 
then batch-ship approved annotations to `context/nba_season_context.md` 
via the followup prompt.

## Summary
- Active playoff teams: 16
- Active whitelisted players analyzed: 55
- Per-stat verdict counts (across all evaluated players):
  - `ship_strong_caution`: 2
  - `ship_strong_boost`: 2
  - `ship_caution`: 17
  - `ship_boost`: 18
  - `demote_to_watch`: 16
  - `ship_trajectory_only`: 11
  - `suppress_eroding_boost`: 2
  - `suppress_candidate`: 6
  - `no_signal`: 50
- Players with no H28 entry: 6
- Players with insufficient playoff seasons (<3): 18
- Players evaluated but no actionable signal: 1

---

## Candidates to Ship

### Kevin Durant (HOU, SF) — ship_strong_caution
*Already in dossier: no | n_playoff_games: 31 | n_seasons: 4*

**PTS** — `no_signal`
- Career RS baseline: 27.80 | Career PO avg: 30.40 | Static delta: +2.60
- H28 flag: ELEVATOR (key_tier T20, delta_pp +5.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 34.25 | +6.45 |
  | 2022 | 4 | 26.25 | -1.55 |
  | 2023 | 11 | 29.00 | +1.20 |
  | 2024 | 4 | 26.75 | -1.05 |
- Trajectory: **net_down** (+6.45 → -1.05)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Kevin Durant PTS no actionable signal: career playoff avg 30.4 vs RS career 27.8 (+2.6 across 31 games / 4 playoff seasons). Trajectory: net_down, dominant direction: mixed.

**REB** — `ship_boost`
- Career RS baseline: 6.70 | Career PO avg: 8.30 | Static delta: +1.60
- H28 flag: ELEVATOR (key_tier T6, delta_pp +16.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 9.25 | +2.55 |
  | 2022 | 4 | 5.75 | -0.95 |
  | 2023 | 11 | 8.73 | +2.03 |
  | 2024 | 4 | 6.50 | -0.20 |
- Trajectory: **net_down** (+2.55 → -0.20)
- Directional consistency: 1/4 below RS, 2/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Kevin Durant REB playoff boost: career playoff avg 8.3 vs RS career 6.7 (+1.6 across 31 games / 4 playoff seasons). 2 of 4 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**AST** — `no_signal`
- Career RS baseline: 5.20 | Career PO avg: 4.90 | Static delta: -0.30
- H28 flag: STABLE (key_tier T4, delta_pp -3.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 4.42 | -0.78 |
  | 2022 | 4 | 6.25 | +1.05 |
  | 2023 | 11 | 5.55 | +0.35 |
  | 2024 | 4 | 3.25 | -1.95 |
- Trajectory: **net_down** (-0.78 → -1.95)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Kevin Durant AST no actionable signal: career playoff avg 4.9 vs RS career 5.2 (-0.3 across 31 games / 4 playoff seasons). Trajectory: net_down, dominant direction: mixed.

**3PM** — `ship_strong_caution`
- Career RS baseline: 2.30 | Career PO avg: 2.00 | Static delta: -0.30
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -10.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 2.75 | +0.45 |
  | 2022 | 4 | 1.75 | -0.55 |
  | 2023 | 11 | 1.55 | -0.75 |
  | 2024 | 4 | 1.25 | -1.05 |
- Trajectory: **monotonic_down** (+0.45 → -1.05)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression worsening over time — strong CAUTION

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Kevin Durant 3PM playoff suppression: career playoff avg 2.0 vs RS career 2.3 (-0.3 across 31 games / 4 playoff seasons). 3 of 4 prior playoffs below RS. Trajectory: monotonic_down — pattern is worsening over time, strengthened CAUTION. Apply strong caution to 3PM T2+ in playoffs.

---

### Julius Randle (MIN, PF) — ship_strong_caution
*Already in dossier: no | n_playoff_games: 30 | n_seasons: 3*

**PTS** — `demote_to_watch`
- Career RS baseline: 22.30 | Career PO avg: 19.40 | Static delta: -2.90
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -7.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 18.00 | -4.30 |
  | 2023 | 10 | 16.60 | -5.70 |
  | 2025 | 15 | 21.73 | -0.57 |
- Trajectory: **net_up** (-4.30 → -0.57)
- Directional consistency: 3/3 below RS, 0/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Julius Randle PTS playoff WATCH: historical suppression (career playoff avg 19.4 vs RS career 22.3 (-2.9 across 30 games / 3 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**REB** — `ship_strong_caution`
- Career RS baseline: 9.30 | Career PO avg: 7.60 | Static delta: -1.70
- H28 flag: SUPPRESSOR (key_tier T6, delta_pp -30.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 11.60 | +2.30 |
  | 2023 | 10 | 8.30 | -1.00 |
  | 2025 | 15 | 5.87 | -3.43 |
- Trajectory: **monotonic_down** (+2.30 → -3.43)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression worsening over time — strong CAUTION

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Julius Randle REB playoff suppression: career playoff avg 7.6 vs RS career 9.3 (-1.7 across 30 games / 3 playoff seasons). 2 of 3 prior playoffs below RS. Trajectory: monotonic_down — pattern is worsening over time, strengthened CAUTION. Apply strong caution to REB T6+ in playoffs.

**AST** — `demote_to_watch`
- Career RS baseline: 5.00 | Career PO avg: 4.30 | Static delta: -0.70
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -17.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 4.00 | -1.00 |
  | 2023 | 10 | 3.60 | -1.40 |
  | 2025 | 15 | 4.93 | -0.07 |
- Trajectory: **net_up** (-1.00 → -0.07)
- Directional consistency: 2/3 below RS, 0/3 above RS, 1/3 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Julius Randle AST playoff WATCH: historical suppression (career playoff avg 4.3 vs RS career 5.0 (-0.7 across 30 games / 3 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `no_signal`
- Career RS baseline: 2.00 | Career PO avg: 1.90 | Static delta: -0.10
- H28 flag: ELEVATOR (key_tier T2, delta_pp +5.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 2.20 | +0.20 |
  | 2023 | 10 | 1.70 | -0.30 |
  | 2025 | 15 | 2.00 | +0.00 |
- Trajectory: **flat** (+0.20 → +0.00)
- Directional consistency: 1/3 below RS, 0/3 above RS, 2/3 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Julius Randle 3PM no actionable signal: career playoff avg 1.9 vs RS career 2.0 (-0.1 across 30 games / 3 playoff seasons). Trajectory: flat, dominant direction: mixed.

---

### Tyrese Maxey (PHI, PG) — ship_strong_boost
*Already in dossier: yes | n_playoff_games: 41 | n_seasons: 4*

**PTS** — `no_signal`
- Career RS baseline: 19.60 | Career PO avg: 17.80 | Static delta: -1.80
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -10.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 6.33 | -13.27 |
  | 2022 | 12 | 20.75 | +1.15 |
  | 2023 | 11 | 20.55 | +0.95 |
  | 2024 | 6 | 29.83 | +10.23 |
- Trajectory: **net_up** (-13.27 → +10.23)
- Directional consistency: 1/4 below RS, 3/4 above RS, 0/4 neutral (dominant: positive)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Tyrese Maxey PTS no actionable signal: career playoff avg 17.8 vs RS career 19.6 (-1.8 across 41 games / 4 playoff seasons). Trajectory: net_up, dominant direction: positive.

**REB** — `ship_strong_boost`
- Career RS baseline: 3.00 | Career PO avg: 3.60 | Static delta: +0.60
- H28 flag: ELEVATOR (key_tier T6, delta_pp +14.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 1.83 | -1.17 |
  | 2022 | 12 | 3.50 | +0.50 |
  | 2023 | 11 | 4.82 | +1.82 |
  | 2024 | 6 | 5.17 | +2.17 |
- Trajectory: **monotonic_up** (-1.17 → +2.17)
- Directional consistency: 1/4 below RS, 3/4 above RS, 0/4 neutral (dominant: positive)
- Rationale: Static boost reinforced by monotonic improvement

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Tyrese Maxey REB playoff boost: career playoff avg 3.6 vs RS career 3.0 (+0.6 across 41 games / 4 playoff seasons). 3 of 4 prior playoffs above RS. Trajectory: monotonic_up — monotonically improving, strengthened BOOST. System under-rates this prop in playoffs.

**AST** — `demote_to_watch`
- Career RS baseline: 4.40 | Career PO avg: 3.10 | Static delta: -1.30
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -24.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 1.33 | -3.07 |
  | 2022 | 12 | 3.92 | -0.48 |
  | 2023 | 11 | 2.27 | -2.13 |
  | 2024 | 6 | 6.83 | +2.43 |
- Trajectory: **net_up** (-3.07 → +2.43)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Tyrese Maxey AST playoff WATCH: historical suppression (career playoff avg 3.1 vs RS career 4.4 (-1.3 across 41 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `ship_trajectory_only`
- Career RS baseline: 2.20 | Career PO avg: 2.10 | Static delta: -0.10
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -10.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 12 | 0.33 | -1.87 |
  | 2022 | 12 | 2.17 | -0.03 |
  | 2023 | 11 | 3.09 | +0.89 |
  | 2024 | 6 | 3.67 | +1.47 |
- Trajectory: **monotonic_up** (-1.87 → +1.47)
- Directional consistency: 1/4 below RS, 2/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Tyrese Maxey 3PM emerging playoff trend: no career-aggregate signal (-0.1 across 41 games / 4 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

---

### Jaden McDaniels (MIN, SF) — ship_strong_boost
*Already in dossier: no | n_playoff_games: 37 | n_seasons: 3*

**PTS** — `ship_strong_boost`
- Career RS baseline: 10.30 | Career PO avg: 12.70 | Static delta: +2.40
- H28 flag: ELEVATOR (key_tier T20, delta_pp +16.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 9.33 | -0.97 |
  | 2024 | 16 | 12.19 | +1.89 |
  | 2025 | 15 | 14.67 | +4.37 |
- Trajectory: **monotonic_up** (-0.97 → +4.37)
- Directional consistency: 1/3 below RS, 2/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: Static boost reinforced by monotonic improvement

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaden McDaniels PTS playoff boost: career playoff avg 12.7 vs RS career 10.3 (+2.4 across 37 games / 3 playoff seasons). 2 of 3 prior playoffs above RS. Trajectory: monotonic_up — monotonically improving, strengthened BOOST. System under-rates this prop in playoffs.

**REB** — `ship_trajectory_only`
- Career RS baseline: 4.20 | Career PO avg: 4.40 | Static delta: +0.20
- H28 flag: STABLE (key_tier T6, delta_pp +2.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 2.83 | -1.37 |
  | 2024 | 16 | 3.81 | -0.39 |
  | 2025 | 15 | 5.60 | +1.40 |
- Trajectory: **monotonic_up** (-1.37 → +1.40)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaden McDaniels REB emerging playoff trend: no career-aggregate signal (+0.2 across 37 games / 3 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

**AST** — `ship_trajectory_only`
- Career RS baseline: 1.50 | Career PO avg: 1.20 | Static delta: -0.30
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -7.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 0.67 | -0.83 |
  | 2024 | 16 | 1.12 | -0.38 |
  | 2025 | 15 | 1.53 | +0.03 |
- Trajectory: **monotonic_up** (-0.83 → +0.03)
- Directional consistency: 2/3 below RS, 0/3 above RS, 1/3 neutral (dominant: negative)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaden McDaniels AST emerging playoff trend: no career-aggregate signal (-0.3 across 37 games / 3 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

**3PM** — `suppress_eroding_boost`
- Career RS baseline: 1.20 | Career PO avg: 1.50 | Static delta: +0.30
- H28 flag: ELEVATOR (key_tier T2, delta_pp +8.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 1.67 | +0.47 |
  | 2024 | 16 | 1.50 | +0.30 |
  | 2025 | 15 | 1.40 | +0.20 |
- Trajectory: **monotonic_down** (+0.47 → +0.20)
- Directional consistency: 0/3 below RS, 2/3 above RS, 1/3 neutral (dominant: positive)
- Rationale: Static boost but eroding — do not ship a positive annotation; flag for watch

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaden McDaniels 3PM playoff WATCH: historically a boost (career playoff avg 1.5 vs RS career 1.2 (+0.3 across 37 games / 3 playoff seasons)) but trajectory is monotonically declining. Do not assume past playoff lift continues; annotation only.

---

### Karl-Anthony Towns (NYK, C) — ship_caution
*Already in dossier: yes | n_playoff_games: 45 | n_seasons: 4*

**PTS** — `ship_caution`
- Career RS baseline: 23.60 | Career PO avg: 20.30 | Static delta: -3.30
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -16.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 21.83 | -1.77 |
  | 2023 | 5 | 18.20 | -5.40 |
  | 2024 | 16 | 19.06 | -4.54 |
  | 2025 | 18 | 21.44 | -2.16 |
- Trajectory: **flat** (-1.77 → -2.16)
- Directional consistency: 4/4 below RS, 0/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Karl-Anthony Towns PTS playoff suppression: career playoff avg 20.3 vs RS career 23.6 (-3.3 across 45 games / 4 playoff seasons). 4 of 4 prior playoffs below RS. Trajectory: flat. Apply caution to PTS T20+ in playoffs.

**REB** — `no_signal`
- Career RS baseline: 10.20 | Career PO avg: 10.40 | Static delta: +0.20
- H28 flag: STABLE (key_tier T6, delta_pp +1.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 10.83 | +0.63 |
  | 2023 | 5 | 10.20 | +0.00 |
  | 2024 | 16 | 9.00 | -1.20 |
  | 2025 | 18 | 11.61 | +1.41 |
- Trajectory: **net_up** (+0.63 → +1.41)
- Directional consistency: 1/4 below RS, 2/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Karl-Anthony Towns REB no actionable signal: career playoff avg 10.4 vs RS career 10.2 (+0.2 across 45 games / 4 playoff seasons). Trajectory: net_up, dominant direction: positive.

**AST** — `ship_caution`
- Career RS baseline: 3.60 | Career PO avg: 2.00 | Static delta: -1.60
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -36.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 2.17 | -1.43 |
  | 2023 | 5 | 2.00 | -1.60 |
  | 2024 | 16 | 2.62 | -0.98 |
  | 2025 | 18 | 1.33 | -2.27 |
- Trajectory: **net_down** (-1.43 → -2.27)
- Directional consistency: 4/4 below RS, 0/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Karl-Anthony Towns AST playoff suppression: career playoff avg 2.0 vs RS career 3.6 (-1.6 across 45 games / 4 playoff seasons). 4 of 4 prior playoffs below RS. Trajectory: net_down. Apply caution to AST T4+ in playoffs.

**3PM** — `ship_caution`
- Career RS baseline: 2.10 | Career PO avg: 1.60 | Static delta: -0.50
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -19.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 1.67 | -0.43 |
  | 2023 | 5 | 1.20 | -0.90 |
  | 2024 | 16 | 1.88 | -0.22 |
  | 2025 | 18 | 1.44 | -0.66 |
- Trajectory: **flat** (-0.43 → -0.66)
- Directional consistency: 3/4 below RS, 0/4 above RS, 1/4 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Karl-Anthony Towns 3PM playoff suppression: career playoff avg 1.6 vs RS career 2.1 (-0.5 across 45 games / 4 playoff seasons). 3 of 4 prior playoffs below RS. Trajectory: flat. Apply caution to 3PM T2+ in playoffs.

---

### OG Anunoby (NYK, SF) — ship_caution
*Already in dossier: no | n_playoff_games: 33 | n_seasons: 3*

**PTS** — `no_signal`
- Career RS baseline: 16.60 | Career PO avg: 16.20 | Static delta: -0.40
- H28 flag: STABLE (key_tier T20, delta_pp +2.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 17.33 | +0.73 |
  | 2024 | 9 | 15.11 | -1.49 |
  | 2025 | 18 | 16.33 | -0.27 |
- Trajectory: **net_down** (+0.73 → -0.27)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> OG Anunoby PTS no actionable signal: career playoff avg 16.2 vs RS career 16.6 (-0.4 across 33 games / 3 playoff seasons). Trajectory: net_down, dominant direction: negative.

**REB** — `no_signal`
- Career RS baseline: 5.00 | Career PO avg: 4.90 | Static delta: -0.10
- H28 flag: SUPPRESSOR (key_tier T6, delta_pp -10.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 4.00 | -1.00 |
  | 2024 | 9 | 6.00 | +1.00 |
  | 2025 | 18 | 4.61 | -0.39 |
- Trajectory: **net_up** (-1.00 → -0.39)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> OG Anunoby REB no actionable signal: career playoff avg 4.9 vs RS career 5.0 (-0.1 across 33 games / 3 playoff seasons). Trajectory: net_up, dominant direction: negative.

**AST** — `ship_caution`
- Career RS baseline: 2.20 | Career PO avg: 1.50 | Static delta: -0.70
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -7.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 2.50 | +0.30 |
  | 2024 | 9 | 1.11 | -1.09 |
  | 2025 | 18 | 1.33 | -0.87 |
- Trajectory: **net_down** (+0.30 → -0.87)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> OG Anunoby AST playoff suppression: career playoff avg 1.5 vs RS career 2.2 (-0.7 across 33 games / 3 playoff seasons). 2 of 3 prior playoffs below RS. Trajectory: net_down. Apply caution to AST T4+ in playoffs.

**3PM** — `no_signal`
- Career RS baseline: 2.20 | Career PO avg: 2.20 | Static delta: +0.00
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -6.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 2.33 | +0.13 |
  | 2024 | 9 | 1.78 | -0.42 |
  | 2025 | 18 | 2.28 | +0.08 |
- Trajectory: **flat** (+0.13 → +0.08)
- Directional consistency: 1/3 below RS, 0/3 above RS, 2/3 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> OG Anunoby 3PM no actionable signal: career playoff avg 2.2 vs RS career 2.2 (+0.0 across 33 games / 3 playoff seasons). Trajectory: flat, dominant direction: mixed.

---

### Mikal Bridges (NYK, SF) — ship_caution
*Already in dossier: no | n_playoff_games: 57 | n_seasons: 4*

**PTS** — `demote_to_watch`
- Career RS baseline: 17.20 | Career PO avg: 13.90 | Static delta: -3.30
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -16.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 11.09 | -6.11 |
  | 2022 | 13 | 13.31 | -3.89 |
  | 2023 | 4 | 23.50 | +6.30 |
  | 2025 | 18 | 15.56 | -1.64 |
- Trajectory: **net_up** (-6.11 → -1.64)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Mikal Bridges PTS playoff WATCH: historical suppression (career playoff avg 13.9 vs RS career 17.2 (-3.3 across 57 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**REB** — `no_signal`
- Career RS baseline: 4.10 | Career PO avg: 4.50 | Static delta: +0.40
- H28 flag: ELEVATOR (key_tier T6, delta_pp +10.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 4.27 | +0.17 |
  | 2022 | 13 | 4.69 | +0.59 |
  | 2023 | 4 | 5.25 | +1.15 |
  | 2025 | 18 | 4.50 | +0.40 |
- Trajectory: **flat** (+0.17 → +0.40)
- Directional consistency: 0/4 below RS, 3/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Mikal Bridges REB no actionable signal: career playoff avg 4.5 vs RS career 4.1 (+0.4 across 57 games / 4 playoff seasons). Trajectory: flat, dominant direction: positive.

**AST** — `no_signal`
- Career RS baseline: 3.00 | Career PO avg: 2.50 | Static delta: -0.50
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -14.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 1.64 | -1.36 |
  | 2022 | 13 | 2.85 | -0.15 |
  | 2023 | 4 | 4.00 | +1.00 |
  | 2025 | 18 | 2.94 | -0.06 |
- Trajectory: **net_up** (-1.36 → -0.06)
- Directional consistency: 1/4 below RS, 1/4 above RS, 2/4 neutral (dominant: mixed)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Mikal Bridges AST no actionable signal: career playoff avg 2.5 vs RS career 3.0 (-0.5 across 57 games / 4 playoff seasons). Trajectory: net_up, dominant direction: mixed.

**3PM** — `ship_caution`
- Career RS baseline: 2.00 | Career PO avg: 1.50 | Static delta: -0.50
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -9.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 1.59 | -0.41 |
  | 2022 | 13 | 1.00 | -1.00 |
  | 2023 | 4 | 2.50 | +0.50 |
  | 2025 | 18 | 1.56 | -0.44 |
- Trajectory: **flat** (-0.41 → -0.44)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Mikal Bridges 3PM playoff suppression: career playoff avg 1.5 vs RS career 2.0 (-0.5 across 57 games / 4 playoff seasons). 3 of 4 prior playoffs below RS. Trajectory: flat. Apply caution to 3PM T2+ in playoffs.

---

### Jaylen Brown (BOS, SG) — ship_caution
*Already in dossier: yes | n_playoff_games: 74 | n_seasons: 4*

**PTS** — `ship_caution`
- Career RS baseline: 24.00 | Career PO avg: 23.00 | Static delta: -1.00
- H28 flag: STABLE (key_tier T20, delta_pp +0.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 24 | 23.08 | -0.92 |
  | 2023 | 20 | 22.65 | -1.35 |
  | 2024 | 19 | 23.89 | -0.11 |
  | 2025 | 11 | 22.09 | -1.91 |
- Trajectory: **net_down** (-0.92 → -1.91)
- Directional consistency: 3/4 below RS, 0/4 above RS, 1/4 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaylen Brown PTS playoff suppression: career playoff avg 23.0 vs RS career 24.0 (-1.0 across 74 games / 4 playoff seasons). 3 of 4 prior playoffs below RS. Trajectory: net_down. Apply caution to PTS T20+ in playoffs.

**REB** — `no_signal`
- Career RS baseline: 6.10 | Career PO avg: 6.30 | Static delta: +0.20
- H28 flag: ELEVATOR (key_tier T6, delta_pp +17.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 24 | 6.92 | +0.82 |
  | 2023 | 20 | 5.60 | -0.50 |
  | 2024 | 19 | 5.95 | -0.15 |
  | 2025 | 11 | 7.09 | +0.99 |
- Trajectory: **flat** (+0.82 → +0.99)
- Directional consistency: 1/4 below RS, 2/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaylen Brown REB no actionable signal: career playoff avg 6.3 vs RS career 6.1 (+0.2 across 74 games / 4 playoff seasons). Trajectory: flat, dominant direction: positive.

**AST** — `no_signal`
- Career RS baseline: 3.70 | Career PO avg: 3.50 | Static delta: -0.20
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -6.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 24 | 3.54 | -0.16 |
  | 2023 | 20 | 3.40 | -0.30 |
  | 2024 | 19 | 3.26 | -0.44 |
  | 2025 | 11 | 3.91 | +0.21 |
- Trajectory: **flat** (-0.16 → +0.21)
- Directional consistency: 2/4 below RS, 0/4 above RS, 2/4 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaylen Brown AST no actionable signal: career playoff avg 3.5 vs RS career 3.7 (-0.2 across 74 games / 4 playoff seasons). Trajectory: flat, dominant direction: negative.

**3PM** — `no_signal`
- Career RS baseline: 2.30 | Career PO avg: 2.10 | Static delta: -0.20
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -7.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 24 | 2.50 | +0.20 |
  | 2023 | 20 | 2.00 | -0.30 |
  | 2024 | 19 | 1.89 | -0.41 |
  | 2025 | 11 | 1.91 | -0.39 |
- Trajectory: **net_down** (+0.20 → -0.39)
- Directional consistency: 3/4 below RS, 0/4 above RS, 1/4 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jaylen Brown 3PM no actionable signal: career playoff avg 2.1 vs RS career 2.3 (-0.2 across 74 games / 4 playoff seasons). Trajectory: net_down, dominant direction: negative.

---

### Payton Pritchard (BOS, PG) — ship_caution
*Already in dossier: no | n_playoff_games: 67 | n_seasons: 5*

**PTS** — `demote_to_watch`
- Career RS baseline: 9.10 | Career PO avg: 6.20 | Static delta: -2.90
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -10.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 3.40 | -5.70 |
  | 2022 | 24 | 4.75 | -4.35 |
  | 2023 | 8 | 4.00 | -5.10 |
  | 2024 | 19 | 6.42 | -2.68 |
  | 2025 | 11 | 11.91 | +2.81 |
- Trajectory: **net_up** (-5.70 → +2.81)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Payton Pritchard PTS playoff WATCH: historical suppression (career playoff avg 6.2 vs RS career 9.1 (-2.9 across 67 games / 5 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**REB** — `ship_caution`
- Career RS baseline: 2.70 | Career PO avg: 1.80 | Static delta: -0.90
- H28 flag: SUPPRESSOR (key_tier T6, delta_pp -11.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 1.80 | -0.90 |
  | 2022 | 24 | 1.92 | -0.78 |
  | 2023 | 8 | 0.75 | -1.95 |
  | 2024 | 19 | 1.95 | -0.75 |
  | 2025 | 11 | 2.27 | -0.43 |
- Trajectory: **flat** (-0.90 → -0.43)
- Directional consistency: 5/5 below RS, 0/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Payton Pritchard REB playoff suppression: career playoff avg 1.8 vs RS career 2.7 (-0.9 across 67 games / 5 playoff seasons). 5 of 5 prior playoffs below RS. Trajectory: flat. Apply caution to REB T6+ in playoffs.

**AST** — `ship_caution`
- Career RS baseline: 2.50 | Career PO avg: 1.80 | Static delta: -0.70
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -11.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 2.40 | -0.10 |
  | 2022 | 24 | 1.58 | -0.92 |
  | 2023 | 8 | 1.38 | -1.12 |
  | 2024 | 19 | 2.11 | -0.39 |
  | 2025 | 11 | 1.55 | -0.95 |
- Trajectory: **net_down** (-0.10 → -0.95)
- Directional consistency: 4/5 below RS, 0/5 above RS, 1/5 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Payton Pritchard AST playoff suppression: career playoff avg 1.8 vs RS career 2.5 (-0.7 across 67 games / 5 playoff seasons). 4 of 5 prior playoffs below RS. Trajectory: net_down. Apply caution to AST T4+ in playoffs.

**3PM** — `demote_to_watch`
- Career RS baseline: 1.90 | Career PO avg: 1.20 | Static delta: -0.70
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -11.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 0.60 | -1.30 |
  | 2022 | 24 | 1.00 | -0.90 |
  | 2023 | 8 | 0.50 | -1.40 |
  | 2024 | 19 | 1.21 | -0.69 |
  | 2025 | 11 | 2.45 | +0.55 |
- Trajectory: **net_up** (-1.30 → +0.55)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Payton Pritchard 3PM playoff WATCH: historical suppression (career playoff avg 1.2 vs RS career 1.9 (-0.7 across 67 games / 5 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

---

### Evan Mobley (CLE, PF) — ship_caution
*Already in dossier: no | n_playoff_games: 25 | n_seasons: 3*

**PTS** — `suppress_candidate`
- Career RS baseline: 16.40 | Career PO avg: 15.10 | Static delta: -1.30
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -8.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 9.80 | -6.60 |
  | 2024 | 12 | 16.00 | -0.40 |
  | 2025 | 8 | 17.12 | +0.72 |
- Trajectory: **monotonic_up** (-6.60 → +0.72)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression but monotonic improvement — player fixing it

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Evan Mobley PTS suppress_candidate (do NOT ship): static suppression (-1.3) but monotonic improvement across seasons — player is fixing it; do not annotate as caution.

**REB** — `ship_trajectory_only`
- Career RS baseline: 8.90 | Career PO avg: 9.00 | Static delta: +0.10
- H28 flag: ELEVATOR (key_tier T6, delta_pp +7.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 10.00 | +1.10 |
  | 2024 | 12 | 9.25 | +0.35 |
  | 2025 | 8 | 8.12 | -0.78 |
- Trajectory: **monotonic_down** (+1.10 → -0.78)
- Directional consistency: 1/3 below RS, 2/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: No static signal, but monotonic_down trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Evan Mobley REB emerging playoff trend: no career-aggregate signal (+0.1 across 25 games / 3 seasons) but trajectory is monotonic_down. Each playoff is worse than the last — emerging CAUTION candidate; annotation only.

**AST** — `ship_caution`
- Career RS baseline: 2.90 | Career PO avg: 2.00 | Static delta: -0.90
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -13.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 2.00 | -0.90 |
  | 2024 | 12 | 2.33 | -0.57 |
  | 2025 | 8 | 1.62 | -1.28 |
- Trajectory: **flat** (-0.90 → -1.28)
- Directional consistency: 3/3 below RS, 0/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Evan Mobley AST playoff suppression: career playoff avg 2.0 vs RS career 2.9 (-0.9 across 25 games / 3 playoff seasons). 3 of 3 prior playoffs below RS. Trajectory: flat. Apply caution to AST T4+ in playoffs.

**3PM** — `ship_trajectory_only`
- Career RS baseline: 0.60 | Career PO avg: 0.80 | Static delta: +0.20
- H28 flag: ELEVATOR (key_tier T2, delta_pp +10.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 0.00 | -0.60 |
  | 2024 | 12 | 0.42 | -0.18 |
  | 2025 | 8 | 1.75 | +1.15 |
- Trajectory: **monotonic_up** (-0.60 → +1.15)
- Directional consistency: 1/3 below RS, 1/3 above RS, 1/3 neutral (dominant: mixed)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Evan Mobley 3PM emerging playoff trend: no career-aggregate signal (+0.2 across 25 games / 3 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

---

### James Harden (CLE, PG) — ship_caution
*Already in dossier: yes | n_playoff_games: 45 | n_seasons: 5*

**PTS** — `ship_caution`
- Career RS baseline: 21.10 | Career PO avg: 19.70 | Static delta: -1.40
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -8.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 9 | 20.22 | -0.88 |
  | 2022 | 12 | 18.58 | -2.52 |
  | 2023 | 11 | 20.27 | -0.83 |
  | 2024 | 6 | 21.17 | +0.07 |
  | 2025 | 7 | 18.71 | -2.39 |
- Trajectory: **net_down** (-0.88 → -2.39)
- Directional consistency: 4/5 below RS, 0/5 above RS, 1/5 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> James Harden PTS playoff suppression: career playoff avg 19.7 vs RS career 21.1 (-1.4 across 45 games / 5 playoff seasons). 4 of 5 prior playoffs below RS. Trajectory: net_down. Apply caution to PTS T20+ in playoffs.

**REB** — `ship_caution`
- Career RS baseline: 6.40 | Career PO avg: 5.70 | Static delta: -0.70
- H28 flag: STABLE (key_tier T6, delta_pp -0.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 9 | 6.33 | -0.07 |
  | 2022 | 12 | 5.67 | -0.73 |
  | 2023 | 11 | 6.18 | -0.22 |
  | 2024 | 6 | 4.50 | -1.90 |
  | 2025 | 7 | 5.43 | -0.97 |
- Trajectory: **net_down** (-0.07 → -0.97)
- Directional consistency: 3/5 below RS, 0/5 above RS, 2/5 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> James Harden REB playoff suppression: career playoff avg 5.7 vs RS career 6.4 (-0.7 across 45 games / 5 playoff seasons). 3 of 5 prior playoffs below RS. Trajectory: net_down. Apply caution to REB T6+ in playoffs.

**AST** — `demote_to_watch`
- Career RS baseline: 9.60 | Career PO avg: 8.50 | Static delta: -1.10
- H28 flag: STABLE (key_tier T4, delta_pp +0.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 9 | 8.56 | -1.04 |
  | 2022 | 12 | 8.58 | -1.02 |
  | 2023 | 11 | 8.27 | -1.33 |
  | 2024 | 6 | 8.00 | -1.60 |
  | 2025 | 7 | 9.14 | -0.46 |
- Trajectory: **net_up** (-1.04 → -0.46)
- Directional consistency: 5/5 below RS, 0/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> James Harden AST playoff WATCH: historical suppression (career playoff avg 8.5 vs RS career 9.6 (-1.1 across 45 games / 5 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `no_signal`
- Career RS baseline: 2.70 | Career PO avg: 2.60 | Static delta: -0.10
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -7.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 9 | 2.67 | -0.03 |
  | 2022 | 12 | 2.33 | -0.37 |
  | 2023 | 11 | 2.82 | +0.12 |
  | 2024 | 6 | 3.00 | +0.30 |
  | 2025 | 7 | 2.29 | -0.41 |
- Trajectory: **flat** (-0.03 → -0.41)
- Directional consistency: 2/5 below RS, 1/5 above RS, 2/5 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> James Harden 3PM no actionable signal: career playoff avg 2.6 vs RS career 2.7 (-0.1 across 45 games / 5 playoff seasons). Trajectory: flat, dominant direction: negative.

---

### Nickeil Alexander-Walker (ATL, SG) — ship_caution
*Already in dossier: no | n_playoff_games: 37 | n_seasons: 4*

**PTS** — `ship_caution`
- Career RS baseline: 9.00 | Career PO avg: 7.80 | Static delta: -1.20
- H28 flag: STABLE (key_tier T20, delta_pp -0.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 8.40 | -0.60 |
  | 2024 | 16 | 7.25 | -1.75 |
  | 2025 | 15 | 8.33 | -0.67 |
- Trajectory: **flat** (-0.60 → -0.67)
- Directional consistency: 3/3 below RS, 0/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nickeil Alexander-Walker PTS playoff suppression: career playoff avg 7.8 vs RS career 9.0 (-1.2 across 36 games / 3 playoff seasons). 3 of 3 prior playoffs below RS. Trajectory: flat. Apply caution to PTS T20+ in playoffs.

**REB** — `ship_caution`
- Career RS baseline: 2.60 | Career PO avg: 1.80 | Static delta: -0.80
- H28 flag: STABLE (key_tier T6, delta_pp -4.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 2.00 | -0.60 |
  | 2024 | 16 | 1.75 | -0.85 |
  | 2025 | 15 | 1.80 | -0.80 |
- Trajectory: **flat** (-0.60 → -0.80)
- Directional consistency: 3/3 below RS, 0/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nickeil Alexander-Walker REB playoff suppression: career playoff avg 1.8 vs RS career 2.6 (-0.8 across 36 games / 3 playoff seasons). 3 of 3 prior playoffs below RS. Trajectory: flat. Apply caution to REB T6+ in playoffs.

**AST** — `ship_trajectory_only`
- Career RS baseline: 2.40 | Career PO avg: 2.20 | Static delta: -0.20
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -8.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 1.40 | -1.00 |
  | 2024 | 16 | 2.31 | -0.09 |
  | 2025 | 15 | 2.33 | -0.07 |
- Trajectory: **monotonic_up** (-1.00 → -0.07)
- Directional consistency: 1/3 below RS, 0/3 above RS, 2/3 neutral (dominant: mixed)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nickeil Alexander-Walker AST emerging playoff trend: no career-aggregate signal (-0.2 across 36 games / 3 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

**3PM** — `ship_trajectory_only`
- Career RS baseline: 1.50 | Career PO avg: 1.50 | Static delta: +0.00
- H28 flag: STABLE (key_tier T2, delta_pp -1.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 2.00 | +0.50 |
  | 2024 | 16 | 1.50 | +0.00 |
  | 2025 | 15 | 1.47 | -0.03 |
- Trajectory: **monotonic_down** (+0.50 → -0.03)
- Directional consistency: 0/3 below RS, 1/3 above RS, 2/3 neutral (dominant: mixed)
- Rationale: No static signal, but monotonic_down trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nickeil Alexander-Walker 3PM emerging playoff trend: no career-aggregate signal (+0.0 across 36 games / 3 seasons) but trajectory is monotonic_down. Each playoff is worse than the last — emerging CAUTION candidate; annotation only.

---

### CJ McCollum (ATL, PG) — ship_caution
*Already in dossier: no | n_playoff_games: 16 | n_seasons: 3*

**PTS** — `no_signal`
- Career RS baseline: 21.30 | Career PO avg: 20.50 | Static delta: -0.80
- H28 flag: ELEVATOR (key_tier T20, delta_pp +10.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 20.67 | -0.63 |
  | 2022 | 6 | 22.17 | +0.87 |
  | 2024 | 4 | 17.75 | -3.55 |
- Trajectory: **net_down** (-0.63 → -3.55)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> CJ McCollum PTS no actionable signal: career playoff avg 20.5 vs RS career 21.3 (-0.8 across 16 games / 3 playoff seasons). Trajectory: net_down, dominant direction: negative.

**REB** — `ship_boost`
- Career RS baseline: 4.20 | Career PO avg: 5.90 | Static delta: +1.70
- H28 flag: ELEVATOR (key_tier T6, delta_pp +31.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 6.00 | +1.80 |
  | 2022 | 6 | 6.67 | +2.47 |
  | 2024 | 4 | 4.75 | +0.55 |
- Trajectory: **net_down** (+1.80 → +0.55)
- Directional consistency: 0/3 below RS, 3/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> CJ McCollum REB playoff boost: career playoff avg 5.9 vs RS career 4.2 (+1.7 across 16 games / 3 playoff seasons). 3 of 3 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**AST** — `no_signal`
- Career RS baseline: 4.90 | Career PO avg: 4.60 | Static delta: -0.30
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -15.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 4.33 | -0.57 |
  | 2022 | 6 | 4.83 | -0.07 |
  | 2024 | 4 | 4.75 | -0.15 |
- Trajectory: **flat** (-0.57 → -0.15)
- Directional consistency: 1/3 below RS, 0/3 above RS, 2/3 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> CJ McCollum AST no actionable signal: career playoff avg 4.6 vs RS career 4.9 (-0.3 across 16 games / 3 playoff seasons). Trajectory: flat, dominant direction: mixed.

**3PM** — `ship_caution`
- Career RS baseline: 3.10 | Career PO avg: 2.40 | Static delta: -0.70
- H28 flag: ELEVATOR (key_tier T2, delta_pp +5.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 2.33 | -0.77 |
  | 2022 | 6 | 2.83 | -0.27 |
  | 2024 | 4 | 1.75 | -1.35 |
- Trajectory: **net_down** (-0.77 → -1.35)
- Directional consistency: 3/3 below RS, 0/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> CJ McCollum 3PM playoff suppression: career playoff avg 2.4 vs RS career 3.1 (-0.7 across 16 games / 3 playoff seasons). 3 of 3 prior playoffs below RS. Trajectory: net_down. Apply caution to 3PM T2+ in playoffs.

---

### Luka Doncic (LAL, PG) — ship_caution
*Already in dossier: yes | n_playoff_games: 49 | n_seasons: 4*

**PTS** — `no_signal`
- Career RS baseline: 30.30 | Career PO avg: 30.80 | Static delta: +0.50
- H28 flag: STABLE (key_tier T20, delta_pp +2.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 35.71 | +5.41 |
  | 2022 | 15 | 31.67 | +1.37 |
  | 2024 | 22 | 28.86 | -1.44 |
  | 2025 | 5 | 30.20 | -0.10 |
- Trajectory: **net_down** (+5.41 → -0.10)
- Directional consistency: 1/4 below RS, 2/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Luka Doncic PTS no actionable signal: career playoff avg 30.8 vs RS career 30.3 (+0.5 across 49 games / 4 playoff seasons). Trajectory: net_down, dominant direction: positive.

**REB** — `no_signal`
- Career RS baseline: 8.70 | Career PO avg: 9.10 | Static delta: +0.40
- H28 flag: ELEVATOR (key_tier T6, delta_pp +5.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 7.86 | -0.84 |
  | 2022 | 15 | 9.80 | +1.10 |
  | 2024 | 22 | 9.45 | +0.75 |
  | 2025 | 5 | 7.00 | -1.70 |
- Trajectory: **net_down** (-0.84 → -1.70)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Luka Doncic REB no actionable signal: career playoff avg 9.1 vs RS career 8.7 (+0.4 across 49 games / 4 playoff seasons). Trajectory: net_down, dominant direction: mixed.

**AST** — `ship_caution`
- Career RS baseline: 8.60 | Career PO avg: 7.70 | Static delta: -0.90
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -5.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 10.29 | +1.69 |
  | 2022 | 15 | 6.40 | -2.20 |
  | 2024 | 22 | 8.09 | -0.51 |
  | 2025 | 5 | 5.80 | -2.80 |
- Trajectory: **net_down** (+1.69 → -2.80)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Luka Doncic AST playoff suppression: career playoff avg 7.7 vs RS career 8.6 (-0.9 across 49 games / 4 playoff seasons). 3 of 4 prior playoffs below RS. Trajectory: net_down. Apply caution to AST T4+ in playoffs.

**3PM** — `no_signal`
- Career RS baseline: 3.30 | Career PO avg: 3.40 | Static delta: +0.10
- H28 flag: STABLE (key_tier T2, delta_pp +2.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 4.43 | +1.13 |
  | 2022 | 15 | 3.40 | +0.10 |
  | 2024 | 22 | 3.09 | -0.21 |
  | 2025 | 5 | 3.20 | -0.10 |
- Trajectory: **net_down** (+1.13 → -0.10)
- Directional consistency: 0/4 below RS, 1/4 above RS, 3/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Luka Doncic 3PM no actionable signal: career playoff avg 3.4 vs RS career 3.3 (+0.1 across 49 games / 4 playoff seasons). Trajectory: net_down, dominant direction: mixed.

---

### Rudy Gobert (MIN, C) — ship_caution
*Already in dossier: no | n_playoff_games: 52 | n_seasons: 5*

**PTS** — `ship_caution`
- Career RS baseline: 13.80 | Career PO avg: 11.70 | Static delta: -2.10
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -9.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 14.73 | +0.93 |
  | 2022 | 6 | 12.00 | -1.80 |
  | 2023 | 5 | 15.00 | +1.20 |
  | 2024 | 15 | 12.07 | -1.73 |
  | 2025 | 15 | 7.87 | -5.93 |
- Trajectory: **net_down** (+0.93 → -5.93)
- Directional consistency: 3/5 below RS, 2/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Rudy Gobert PTS playoff suppression: career playoff avg 11.7 vs RS career 13.8 (-2.1 across 52 games / 5 playoff seasons). 3 of 5 prior playoffs below RS. Trajectory: net_down. Apply caution to PTS T20+ in playoffs.

**REB** — `ship_caution`
- Career RS baseline: 12.70 | Career PO avg: 10.60 | Static delta: -2.10
- H28 flag: SUPPRESSOR (key_tier T6, delta_pp -6.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 12.27 | -0.43 |
  | 2022 | 6 | 13.17 | +0.47 |
  | 2023 | 5 | 12.20 | -0.50 |
  | 2024 | 15 | 9.80 | -2.90 |
  | 2025 | 15 | 8.60 | -4.10 |
- Trajectory: **net_down** (-0.43 → -4.10)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, stable or worsening trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Rudy Gobert REB playoff suppression: career playoff avg 10.6 vs RS career 12.7 (-2.1 across 52 games / 5 playoff seasons). 4 of 5 prior playoffs below RS. Trajectory: net_down. Apply caution to REB T6+ in playoffs.

**AST** — `no_signal`
- Career RS baseline: 1.30 | Career PO avg: 1.10 | Static delta: -0.20
- H28 flag: STABLE (key_tier T4, delta_pp -4.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 0.82 | -0.48 |
  | 2022 | 6 | 0.50 | -0.80 |
  | 2023 | 5 | 2.00 | +0.70 |
  | 2024 | 15 | 1.60 | +0.30 |
  | 2025 | 15 | 0.73 | -0.57 |
- Trajectory: **flat** (-0.48 → -0.57)
- Directional consistency: 3/5 below RS, 2/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Rudy Gobert AST no actionable signal: career playoff avg 1.1 vs RS career 1.3 (-0.2 across 52 games / 5 playoff seasons). Trajectory: flat, dominant direction: negative.

**3PM** — `no_signal`
- Career RS baseline: 0.00 | Career PO avg: 0.00 | Static delta: +0.00
- H28 flag: STABLE (key_tier T2, delta_pp +0.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 0.00 | +0.00 |
  | 2022 | 6 | 0.00 | +0.00 |
  | 2023 | 5 | 0.00 | +0.00 |
  | 2024 | 15 | 0.00 | +0.00 |
  | 2025 | 15 | 0.00 | +0.00 |
- Trajectory: **flat** (+0.00 → +0.00)
- Directional consistency: 0/5 below RS, 0/5 above RS, 5/5 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Rudy Gobert 3PM no actionable signal: career playoff avg 0.0 vs RS career 0.0 (+0.0 across 52 games / 5 playoff seasons). Trajectory: flat, dominant direction: mixed.

---

### Jalen Brunson (NYK, PG) — ship_boost
*Already in dossier: yes | n_playoff_games: 67 | n_seasons: 5*

**PTS** — `ship_boost`
- Career RS baseline: 21.50 | Career PO avg: 25.40 | Static delta: +3.90
- H28 flag: ELEVATOR (key_tier T20, delta_pp +17.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 8.00 | -13.50 |
  | 2022 | 18 | 21.56 | +0.06 |
  | 2023 | 11 | 27.82 | +6.32 |
  | 2024 | 13 | 32.38 | +10.88 |
  | 2025 | 18 | 29.44 | +7.94 |
- Trajectory: **net_up** (-13.50 → +7.94)
- Directional consistency: 1/5 below RS, 3/5 above RS, 1/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jalen Brunson PTS playoff boost: career playoff avg 25.4 vs RS career 21.5 (+3.9 across 67 games / 5 playoff seasons). 3 of 5 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**REB** — `no_signal`
- Career RS baseline: 3.50 | Career PO avg: 3.90 | Static delta: +0.40
- H28 flag: STABLE (key_tier T6, delta_pp +4.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 2.57 | -0.93 |
  | 2022 | 18 | 4.61 | +1.11 |
  | 2023 | 11 | 4.91 | +1.41 |
  | 2024 | 13 | 3.31 | -0.19 |
  | 2025 | 18 | 3.44 | -0.06 |
- Trajectory: **net_up** (-0.93 → -0.06)
- Directional consistency: 1/5 below RS, 2/5 above RS, 2/5 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jalen Brunson REB no actionable signal: career playoff avg 3.9 vs RS career 3.5 (+0.4 across 67 games / 5 playoff seasons). Trajectory: net_up, dominant direction: positive.

**AST** — `no_signal`
- Career RS baseline: 5.70 | Career PO avg: 5.40 | Static delta: -0.30
- H28 flag: STABLE (key_tier T4, delta_pp -2.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 1.43 | -4.27 |
  | 2022 | 18 | 3.67 | -2.03 |
  | 2023 | 11 | 5.64 | -0.06 |
  | 2024 | 13 | 7.46 | +1.76 |
  | 2025 | 18 | 7.00 | +1.30 |
- Trajectory: **net_up** (-4.27 → +1.30)
- Directional consistency: 2/5 below RS, 2/5 above RS, 1/5 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jalen Brunson AST no actionable signal: career playoff avg 5.4 vs RS career 5.7 (-0.3 across 67 games / 5 playoff seasons). Trajectory: net_up, dominant direction: mixed.

**3PM** — `no_signal`
- Career RS baseline: 1.90 | Career PO avg: 2.00 | Static delta: +0.10
- H28 flag: STABLE (key_tier T2, delta_pp -1.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 7 | 0.86 | -1.04 |
  | 2022 | 18 | 1.44 | -0.46 |
  | 2023 | 11 | 2.36 | +0.46 |
  | 2024 | 13 | 2.00 | +0.10 |
  | 2025 | 18 | 2.67 | +0.77 |
- Trajectory: **net_up** (-1.04 → +0.77)
- Directional consistency: 2/5 below RS, 2/5 above RS, 1/5 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jalen Brunson 3PM no actionable signal: career playoff avg 2.0 vs RS career 1.9 (+0.1 across 67 games / 5 playoff seasons). Trajectory: net_up, dominant direction: mixed.

---

### Jayson Tatum (BOS, PF) — ship_boost
*Already in dossier: yes | n_playoff_games: 76 | n_seasons: 5*

**PTS** — `no_signal`
- Career RS baseline: 27.40 | Career PO avg: 26.50 | Static delta: -0.90
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -6.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 30.60 | +3.20 |
  | 2022 | 24 | 25.62 | -1.78 |
  | 2023 | 20 | 27.15 | -0.25 |
  | 2024 | 19 | 25.00 | -2.40 |
  | 2025 | 8 | 28.12 | +0.72 |
- Trajectory: **net_down** (+3.20 → +0.72)
- Directional consistency: 2/5 below RS, 2/5 above RS, 1/5 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jayson Tatum PTS no actionable signal: career playoff avg 26.5 vs RS career 27.4 (-0.9 across 76 games / 5 playoff seasons). Trajectory: net_down, dominant direction: mixed.

**REB** — `ship_boost`
- Career RS baseline: 8.20 | Career PO avg: 8.90 | Static delta: +0.70
- H28 flag: STABLE (key_tier T6, delta_pp +3.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 5.80 | -2.40 |
  | 2022 | 24 | 6.71 | -1.49 |
  | 2023 | 20 | 10.50 | +2.30 |
  | 2024 | 19 | 9.68 | +1.48 |
  | 2025 | 8 | 11.50 | +3.30 |
- Trajectory: **net_up** (-2.40 → +3.30)
- Directional consistency: 2/5 below RS, 3/5 above RS, 0/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jayson Tatum REB playoff boost: career playoff avg 8.9 vs RS career 8.2 (+0.7 across 76 games / 5 playoff seasons). 3 of 5 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**AST** — `ship_boost`
- Career RS baseline: 4.90 | Career PO avg: 5.80 | Static delta: +0.90
- H28 flag: ELEVATOR (key_tier T4, delta_pp +16.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 4.60 | -0.30 |
  | 2022 | 24 | 6.17 | +1.27 |
  | 2023 | 20 | 5.25 | +0.35 |
  | 2024 | 19 | 6.26 | +1.36 |
  | 2025 | 8 | 5.38 | +0.48 |
- Trajectory: **net_up** (-0.30 → +0.48)
- Directional consistency: 1/5 below RS, 4/5 above RS, 0/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jayson Tatum AST playoff boost: career playoff avg 5.8 vs RS career 4.9 (+0.9 across 76 games / 5 playoff seasons). 4 of 5 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**3PM** — `demote_to_watch`
- Career RS baseline: 3.20 | Career PO avg: 2.80 | Static delta: -0.40
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -11.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 2.80 | -0.40 |
  | 2022 | 24 | 3.21 | +0.01 |
  | 2023 | 20 | 2.65 | -0.55 |
  | 2024 | 19 | 2.05 | -1.15 |
  | 2025 | 8 | 3.62 | +0.42 |
- Trajectory: **net_up** (-0.40 → +0.42)
- Directional consistency: 3/5 below RS, 1/5 above RS, 1/5 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jayson Tatum 3PM playoff WATCH: historical suppression (career playoff avg 2.8 vs RS career 3.2 (-0.4 across 76 games / 5 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

---

### Donovan Mitchell (CLE, SG) — ship_boost
*Already in dossier: yes | n_playoff_games: 40 | n_seasons: 5*

**PTS** — `ship_boost`
- Career RS baseline: 26.20 | Career PO avg: 28.90 | Static delta: +2.70
- H28 flag: ELEVATOR (key_tier T20, delta_pp +5.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 32.30 | +6.10 |
  | 2022 | 6 | 25.50 | -0.70 |
  | 2023 | 5 | 23.20 | -3.00 |
  | 2024 | 10 | 29.60 | +3.40 |
  | 2025 | 9 | 29.56 | +3.36 |
- Trajectory: **net_down** (+6.10 → +3.36)
- Directional consistency: 2/5 below RS, 3/5 above RS, 0/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Donovan Mitchell PTS playoff boost: career playoff avg 28.9 vs RS career 26.2 (+2.7 across 40 games / 5 playoff seasons). 3 of 5 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**REB** — `no_signal`
- Career RS baseline: 4.50 | Career PO avg: 4.70 | Static delta: +0.20
- H28 flag: ELEVATOR (key_tier T6, delta_pp +10.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 4.20 | -0.30 |
  | 2022 | 6 | 4.33 | -0.17 |
  | 2023 | 5 | 5.00 | +0.50 |
  | 2024 | 10 | 5.40 | +0.90 |
  | 2025 | 9 | 4.67 | +0.17 |
- Trajectory: **flat** (-0.30 → +0.17)
- Directional consistency: 1/5 below RS, 2/5 above RS, 2/5 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Donovan Mitchell REB no actionable signal: career playoff avg 4.7 vs RS career 4.5 (+0.2 across 40 games / 5 playoff seasons). Trajectory: flat, dominant direction: positive.

**AST** — `no_signal`
- Career RS baseline: 5.20 | Career PO avg: 5.20 | Static delta: +0.00
- H28 flag: STABLE (key_tier T4, delta_pp +2.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 5.50 | +0.30 |
  | 2022 | 6 | 5.67 | +0.47 |
  | 2023 | 5 | 7.20 | +2.00 |
  | 2024 | 10 | 4.70 | -0.50 |
  | 2025 | 9 | 3.89 | -1.31 |
- Trajectory: **net_down** (+0.30 → -1.31)
- Directional consistency: 2/5 below RS, 3/5 above RS, 0/5 neutral (dominant: positive)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Donovan Mitchell AST no actionable signal: career playoff avg 5.2 vs RS career 5.2 (+0.0 across 40 games / 5 playoff seasons). Trajectory: net_down, dominant direction: positive.

**3PM** — `no_signal`
- Career RS baseline: 3.40 | Career PO avg: 3.20 | Static delta: -0.20
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -7.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 5.00 | +1.60 |
  | 2022 | 6 | 1.67 | -1.73 |
  | 2023 | 5 | 2.60 | -0.80 |
  | 2024 | 10 | 2.90 | -0.50 |
  | 2025 | 9 | 3.11 | -0.29 |
- Trajectory: **net_down** (+1.60 → -0.29)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Donovan Mitchell 3PM no actionable signal: career playoff avg 3.2 vs RS career 3.4 (-0.2 across 40 games / 5 playoff seasons). Trajectory: net_down, dominant direction: negative.

---

### Nikola Jokic (DEN, C) — ship_boost
*Already in dossier: yes | n_playoff_games: 61 | n_seasons: 5*

**PTS** — `ship_boost`
- Career RS baseline: 26.80 | Career PO avg: 28.90 | Static delta: +2.10
- H28 flag: ELEVATOR (key_tier T20, delta_pp +9.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 29.80 | +3.00 |
  | 2022 | 5 | 31.00 | +4.20 |
  | 2023 | 20 | 30.00 | +3.20 |
  | 2024 | 12 | 28.67 | +1.87 |
  | 2025 | 14 | 26.21 | -0.59 |
- Trajectory: **net_down** (+3.00 → -0.59)
- Directional consistency: 1/5 below RS, 4/5 above RS, 0/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nikola Jokic PTS playoff boost: career playoff avg 28.9 vs RS career 26.8 (+2.1 across 61 games / 5 playoff seasons). 4 of 5 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**REB** — `ship_boost`
- Career RS baseline: 12.30 | Career PO avg: 13.00 | Static delta: +0.70
- H28 flag: STABLE (key_tier T6, delta_pp +1.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 11.60 | -0.70 |
  | 2022 | 5 | 13.20 | +0.90 |
  | 2023 | 20 | 13.45 | +1.15 |
  | 2024 | 12 | 13.42 | +1.12 |
  | 2025 | 14 | 12.71 | +0.41 |
- Trajectory: **net_up** (-0.70 → +0.41)
- Directional consistency: 1/5 below RS, 4/5 above RS, 0/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nikola Jokic REB playoff boost: career playoff avg 13.0 vs RS career 12.3 (+0.7 across 61 games / 5 playoff seasons). 4 of 5 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**AST** — `demote_to_watch`
- Career RS baseline: 9.00 | Career PO avg: 8.00 | Static delta: -1.00
- H28 flag: STABLE (key_tier T4, delta_pp -3.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 5.00 | -4.00 |
  | 2022 | 5 | 5.80 | -3.20 |
  | 2023 | 20 | 9.50 | +0.50 |
  | 2024 | 12 | 8.67 | -0.33 |
  | 2025 | 14 | 8.00 | -1.00 |
- Trajectory: **net_up** (-4.00 → -1.00)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nikola Jokic AST playoff WATCH: historical suppression (career playoff avg 8.0 vs RS career 9.0 (-1.0 across 61 games / 5 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `ship_boost`
- Career RS baseline: 1.30 | Career PO avg: 1.70 | Static delta: +0.40
- H28 flag: ELEVATOR (key_tier T2, delta_pp +16.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 2.00 | +0.70 |
  | 2022 | 5 | 1.00 | -0.30 |
  | 2023 | 20 | 1.75 | +0.45 |
  | 2024 | 12 | 1.17 | -0.13 |
  | 2025 | 14 | 1.93 | +0.63 |
- Trajectory: **flat** (+0.70 → +0.63)
- Directional consistency: 1/5 below RS, 3/5 above RS, 1/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Nikola Jokic 3PM playoff boost: career playoff avg 1.7 vs RS career 1.3 (+0.4 across 61 games / 5 playoff seasons). 3 of 5 prior playoffs above RS. Trajectory: flat. System under-rates this prop in playoffs — consider BOOST.

---

### Jamal Murray (DEN, PG) — ship_boost
*Already in dossier: yes | n_playoff_games: 46 | n_seasons: 3*

**PTS** — `ship_boost`
- Career RS baseline: 20.90 | Career PO avg: 23.30 | Static delta: +2.40
- H28 flag: ELEVATOR (key_tier T20, delta_pp +6.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 20 | 26.10 | +5.20 |
  | 2024 | 12 | 20.58 | -0.32 |
  | 2025 | 14 | 21.79 | +0.89 |
- Trajectory: **net_down** (+5.20 → +0.89)
- Directional consistency: 1/3 below RS, 2/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jamal Murray PTS playoff boost: career playoff avg 23.3 vs RS career 20.9 (+2.4 across 46 games / 3 playoff seasons). 2 of 3 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**REB** — `ship_boost`
- Career RS baseline: 4.00 | Career PO avg: 5.10 | Static delta: +1.10
- H28 flag: ELEVATOR (key_tier T6, delta_pp +14.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 20 | 5.65 | +1.65 |
  | 2024 | 12 | 4.33 | +0.33 |
  | 2025 | 14 | 4.86 | +0.86 |
- Trajectory: **net_down** (+1.65 → +0.86)
- Directional consistency: 0/3 below RS, 3/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jamal Murray REB playoff boost: career playoff avg 5.1 vs RS career 4.0 (+1.1 across 46 games / 3 playoff seasons). 3 of 3 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**AST** — `ship_trajectory_only`
- Career RS baseline: 5.90 | Career PO avg: 6.10 | Static delta: +0.20
- H28 flag: STABLE (key_tier T4, delta_pp +1.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 20 | 7.10 | +1.20 |
  | 2024 | 12 | 5.58 | -0.32 |
  | 2025 | 14 | 5.21 | -0.69 |
- Trajectory: **monotonic_down** (+1.20 → -0.69)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: No static signal, but monotonic_down trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jamal Murray AST emerging playoff trend: no career-aggregate signal (+0.2 across 46 games / 3 seasons) but trajectory is monotonic_down. Each playoff is worse than the last — emerging CAUTION candidate; annotation only.

**3PM** — `no_signal`
- Career RS baseline: 2.50 | Career PO avg: 2.50 | Static delta: +0.00
- H28 flag: STABLE (key_tier T2, delta_pp +2.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 20 | 2.95 | +0.45 |
  | 2024 | 12 | 1.92 | -0.58 |
  | 2025 | 14 | 2.43 | -0.07 |
- Trajectory: **net_down** (+0.45 → -0.07)
- Directional consistency: 1/3 below RS, 1/3 above RS, 1/3 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jamal Murray 3PM no actionable signal: career playoff avg 2.5 vs RS career 2.5 (+0.0 across 46 games / 3 playoff seasons). Trajectory: net_down, dominant direction: mixed.

---

### Aaron Gordon (DEN, PF) — ship_boost
*Already in dossier: no | n_playoff_games: 61 | n_seasons: 5*

**PTS** — `no_signal`
- Career RS baseline: 14.60 | Career PO avg: 13.80 | Static delta: -0.80
- H28 flag: STABLE (key_tier T20, delta_pp +0.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 11.10 | -3.50 |
  | 2022 | 5 | 13.80 | -0.80 |
  | 2023 | 20 | 13.25 | -1.35 |
  | 2024 | 12 | 14.33 | -0.27 |
  | 2025 | 14 | 16.21 | +1.61 |
- Trajectory: **net_up** (-3.50 → +1.61)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Aaron Gordon PTS no actionable signal: career playoff avg 13.8 vs RS career 14.6 (-0.8 across 61 games / 5 playoff seasons). Trajectory: net_up, dominant direction: negative.

**REB** — `ship_boost`
- Career RS baseline: 6.00 | Career PO avg: 6.60 | Static delta: +0.60
- H28 flag: ELEVATOR (key_tier T6, delta_pp +9.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 5.40 | -0.60 |
  | 2022 | 5 | 7.20 | +1.20 |
  | 2023 | 20 | 6.00 | +0.00 |
  | 2024 | 12 | 7.25 | +1.25 |
  | 2025 | 14 | 7.57 | +1.57 |
- Trajectory: **net_up** (-0.60 → +1.57)
- Directional consistency: 1/5 below RS, 3/5 above RS, 1/5 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Aaron Gordon REB playoff boost: career playoff avg 6.6 vs RS career 6.0 (+0.6 across 61 games / 5 playoff seasons). 3 of 5 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**AST** — `no_signal`
- Career RS baseline: 3.10 | Career PO avg: 2.90 | Static delta: -0.20
- H28 flag: STABLE (key_tier T4, delta_pp +3.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 2.00 | -1.10 |
  | 2022 | 5 | 2.60 | -0.50 |
  | 2023 | 20 | 2.60 | -0.50 |
  | 2024 | 12 | 4.42 | +1.32 |
  | 2025 | 14 | 2.71 | -0.39 |
- Trajectory: **net_up** (-1.10 → -0.39)
- Directional consistency: 4/5 below RS, 1/5 above RS, 0/5 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Aaron Gordon AST no actionable signal: career playoff avg 2.9 vs RS career 3.1 (-0.2 across 61 games / 5 playoff seasons). Trajectory: net_up, dominant direction: negative.

**3PM** — `no_signal`
- Career RS baseline: 1.00 | Career PO avg: 1.00 | Static delta: +0.00
- H28 flag: ELEVATOR (key_tier T2, delta_pp +5.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 10 | 0.90 | -0.10 |
  | 2022 | 5 | 0.60 | -0.40 |
  | 2023 | 20 | 0.90 | -0.10 |
  | 2024 | 12 | 0.92 | -0.08 |
  | 2025 | 14 | 1.57 | +0.57 |
- Trajectory: **net_up** (-0.10 → +0.57)
- Directional consistency: 1/5 below RS, 1/5 above RS, 3/5 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Aaron Gordon 3PM no actionable signal: career playoff avg 1.0 vs RS career 1.0 (+0.0 across 61 games / 5 playoff seasons). Trajectory: net_up, dominant direction: mixed.

---

### Austin Reaves (LAL, SG) — ship_boost
*Already in dossier: yes | n_playoff_games: 26 | n_seasons: 3*

**PTS** — `suppress_eroding_boost`
- Career RS baseline: 14.50 | Career PO avg: 16.70 | Static delta: +2.20
- H28 flag: ELEVATOR (key_tier T20, delta_pp +14.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 16 | 16.88 | +2.38 |
  | 2024 | 5 | 16.80 | +2.30 |
  | 2025 | 5 | 16.20 | +1.70 |
- Trajectory: **monotonic_down** (+2.38 → +1.70)
- Directional consistency: 0/3 below RS, 3/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: Static boost but eroding — do not ship a positive annotation; flag for watch

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Austin Reaves PTS playoff WATCH: historically a boost (career playoff avg 16.7 vs RS career 14.5 (+2.2 across 26 games / 3 playoff seasons)) but trajectory is monotonically declining. Do not assume past playoff lift continues; annotation only.

**REB** — `ship_boost`
- Career RS baseline: 3.80 | Career PO avg: 4.50 | Static delta: +0.70
- H28 flag: ELEVATOR (key_tier T6, delta_pp +6.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 16 | 4.44 | +0.64 |
  | 2024 | 5 | 3.80 | +0.00 |
  | 2025 | 5 | 5.40 | +1.60 |
- Trajectory: **net_up** (+0.64 → +1.60)
- Directional consistency: 0/3 below RS, 2/3 above RS, 1/3 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Austin Reaves REB playoff boost: career playoff avg 4.5 vs RS career 3.8 (+0.7 across 26 games / 3 playoff seasons). 2 of 3 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**AST** — `no_signal`
- Career RS baseline: 4.30 | Career PO avg: 4.20 | Static delta: -0.10
- H28 flag: ELEVATOR (key_tier T4, delta_pp +8.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 16 | 4.56 | +0.26 |
  | 2024 | 5 | 3.60 | -0.70 |
  | 2025 | 5 | 3.60 | -0.70 |
- Trajectory: **net_down** (+0.26 → -0.70)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Austin Reaves AST no actionable signal: career playoff avg 4.2 vs RS career 4.3 (-0.1 across 26 games / 3 playoff seasons). Trajectory: net_down, dominant direction: negative.

**3PM** — `ship_boost`
- Career RS baseline: 1.80 | Career PO avg: 2.30 | Static delta: +0.50
- H28 flag: ELEVATOR (key_tier T2, delta_pp +11.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 16 | 2.44 | +0.64 |
  | 2024 | 5 | 1.40 | -0.40 |
  | 2025 | 5 | 3.00 | +1.20 |
- Trajectory: **net_up** (+0.64 → +1.20)
- Directional consistency: 1/3 below RS, 2/3 above RS, 0/3 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Austin Reaves 3PM playoff boost: career playoff avg 2.3 vs RS career 1.8 (+0.5 across 26 games / 3 playoff seasons). 2 of 3 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

---

### Anthony Edwards (MIN, SG) — ship_boost
*Already in dossier: yes | n_playoff_games: 42 | n_seasons: 4*

**PTS** — `ship_boost`
- Career RS baseline: 23.80 | Career PO avg: 26.90 | Static delta: +3.10
- H28 flag: ELEVATOR (key_tier T20, delta_pp +7.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 25.17 | +1.37 |
  | 2023 | 5 | 31.60 | +7.80 |
  | 2024 | 16 | 27.56 | +3.76 |
  | 2025 | 15 | 25.33 | +1.53 |
- Trajectory: **flat** (+1.37 → +1.53)
- Directional consistency: 0/4 below RS, 4/4 above RS, 0/4 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Anthony Edwards PTS playoff boost: career playoff avg 26.9 vs RS career 23.8 (+3.1 across 42 games / 4 playoff seasons). 4 of 4 prior playoffs above RS. Trajectory: flat. System under-rates this prop in playoffs — consider BOOST.

**REB** — `no_signal`
- Career RS baseline: 5.30 | Career PO avg: 6.60 | Static delta: +1.30
- H28 flag: ELEVATOR (key_tier T6, delta_pp +20.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 4.17 | -1.13 |
  | 2023 | 5 | 5.00 | -0.30 |
  | 2024 | 16 | 7.00 | +1.70 |
  | 2025 | 15 | 7.80 | +2.50 |
- Trajectory: **monotonic_up** (-1.13 → +2.50)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Anthony Edwards REB no actionable signal: career playoff avg 6.6 vs RS career 5.3 (+1.3 across 42 games / 4 playoff seasons). Trajectory: monotonic_up, dominant direction: mixed.

**AST** — `ship_boost`
- Career RS baseline: 4.20 | Career PO avg: 5.50 | Static delta: +1.30
- H28 flag: ELEVATOR (key_tier T4, delta_pp +22.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 3.00 | -1.20 |
  | 2023 | 5 | 5.20 | +1.00 |
  | 2024 | 16 | 6.50 | +2.30 |
  | 2025 | 15 | 5.47 | +1.27 |
- Trajectory: **net_up** (-1.20 → +1.27)
- Directional consistency: 1/4 below RS, 3/4 above RS, 0/4 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Anthony Edwards AST playoff boost: career playoff avg 5.5 vs RS career 4.2 (+1.3 across 42 games / 4 playoff seasons). 3 of 4 prior playoffs above RS. Trajectory: net_up. System under-rates this prop in playoffs — consider BOOST.

**3PM** — `no_signal`
- Career RS baseline: 2.90 | Career PO avg: 3.10 | Static delta: +0.20
- H28 flag: STABLE (key_tier T2, delta_pp -2.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 6 | 3.83 | +0.93 |
  | 2023 | 5 | 3.00 | +0.10 |
  | 2024 | 16 | 2.88 | -0.02 |
  | 2025 | 15 | 3.07 | +0.17 |
- Trajectory: **net_down** (+0.93 → +0.17)
- Directional consistency: 0/4 below RS, 1/4 above RS, 3/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Anthony Edwards 3PM no actionable signal: career playoff avg 3.1 vs RS career 2.9 (+0.2 across 42 games / 4 playoff seasons). Trajectory: net_down, dominant direction: mixed.

---

### Devin Booker (PHX, SG) — ship_boost
*Already in dossier: yes | n_playoff_games: 47 | n_seasons: 4*

**PTS** — `ship_boost`
- Career RS baseline: 26.50 | Career PO avg: 28.00 | Static delta: +1.50
- H28 flag: STABLE (key_tier T20, delta_pp -2.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 27.32 | +0.82 |
  | 2022 | 10 | 23.30 | -3.20 |
  | 2023 | 11 | 33.73 | +7.23 |
  | 2024 | 4 | 27.50 | +1.00 |
- Trajectory: **flat** (+0.82 → +1.00)
- Directional consistency: 1/4 below RS, 3/4 above RS, 0/4 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Devin Booker PTS playoff boost: career playoff avg 28.0 vs RS career 26.5 (+1.5 across 47 games / 4 playoff seasons). 3 of 4 prior playoffs above RS. Trajectory: flat. System under-rates this prop in playoffs — consider BOOST.

**REB** — `ship_boost`
- Career RS baseline: 4.50 | Career PO avg: 5.10 | Static delta: +0.60
- H28 flag: ELEVATOR (key_tier T6, delta_pp +12.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 5.64 | +1.14 |
  | 2022 | 10 | 4.80 | +0.30 |
  | 2023 | 11 | 4.82 | +0.32 |
  | 2024 | 4 | 3.25 | -1.25 |
- Trajectory: **net_down** (+1.14 → -1.25)
- Directional consistency: 1/4 below RS, 3/4 above RS, 0/4 neutral (dominant: positive)
- Rationale: Static boost, stable or net-up trajectory

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Devin Booker REB playoff boost: career playoff avg 5.1 vs RS career 4.5 (+0.6 across 47 games / 4 playoff seasons). 3 of 4 prior playoffs above RS. Trajectory: net_down. System under-rates this prop in playoffs — consider BOOST.

**AST** — `demote_to_watch`
- Career RS baseline: 5.80 | Career PO avg: 5.30 | Static delta: -0.50
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -9.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 4.55 | -1.25 |
  | 2022 | 10 | 4.40 | -1.40 |
  | 2023 | 11 | 7.18 | +1.38 |
  | 2024 | 4 | 6.00 | +0.20 |
- Trajectory: **net_up** (-1.25 → +0.20)
- Directional consistency: 2/4 below RS, 1/4 above RS, 1/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Devin Booker AST playoff WATCH: historical suppression (career playoff avg 5.3 vs RS career 5.8 (-0.5 across 47 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `no_signal`
- Career RS baseline: 2.30 | Career PO avg: 2.30 | Static delta: +0.00
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -6.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 22 | 2.00 | -0.30 |
  | 2022 | 10 | 2.80 | +0.50 |
  | 2023 | 11 | 2.82 | +0.52 |
  | 2024 | 4 | 1.75 | -0.55 |
- Trajectory: **flat** (-0.30 → -0.55)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Devin Booker 3PM no actionable signal: career playoff avg 2.3 vs RS career 2.3 (+0.0 across 47 games / 4 playoff seasons). Trajectory: flat, dominant direction: mixed.

---

### Derrick White (BOS, SG) — demote_to_watch
*Already in dossier: no | n_playoff_games: 73 | n_seasons: 4*

**PTS** — `ship_trajectory_only`
- Career RS baseline: 14.40 | Career PO avg: 13.50 | Static delta: -0.90
- H28 flag: STABLE (key_tier T20, delta_pp +0.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 23 | 8.52 | -5.88 |
  | 2023 | 20 | 13.35 | -1.05 |
  | 2024 | 19 | 16.74 | +2.34 |
  | 2025 | 11 | 18.82 | +4.42 |
- Trajectory: **monotonic_up** (-5.88 → +4.42)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Derrick White PTS emerging playoff trend: no career-aggregate signal (-0.9 across 73 games / 4 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

**REB** — `no_signal`
- Career RS baseline: 3.80 | Career PO avg: 3.60 | Static delta: -0.20
- H28 flag: STABLE (key_tier T6, delta_pp -4.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 23 | 3.04 | -0.76 |
  | 2023 | 20 | 2.95 | -0.85 |
  | 2024 | 19 | 4.26 | +0.46 |
  | 2025 | 11 | 5.09 | +1.29 |
- Trajectory: **net_up** (-0.76 → +1.29)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Derrick White REB no actionable signal: career playoff avg 3.6 vs RS career 3.8 (-0.2 across 73 games / 4 playoff seasons). Trajectory: net_up, dominant direction: mixed.

**AST** — `demote_to_watch`
- Career RS baseline: 4.50 | Career PO avg: 3.00 | Static delta: -1.50
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -24.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 23 | 2.65 | -1.85 |
  | 2023 | 20 | 2.10 | -2.40 |
  | 2024 | 19 | 4.05 | -0.45 |
  | 2025 | 11 | 3.55 | -0.95 |
- Trajectory: **net_up** (-1.85 → -0.95)
- Directional consistency: 4/4 below RS, 0/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Derrick White AST playoff WATCH: historical suppression (career playoff avg 3.0 vs RS career 4.5 (-1.5 across 73 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `ship_trajectory_only`
- Career RS baseline: 2.40 | Career PO avg: 2.50 | Static delta: +0.10
- H28 flag: STABLE (key_tier T2, delta_pp +3.9pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2022 | 23 | 1.13 | -1.27 |
  | 2023 | 20 | 2.50 | +0.10 |
  | 2024 | 19 | 3.42 | +1.02 |
  | 2025 | 11 | 3.64 | +1.24 |
- Trajectory: **monotonic_up** (-1.27 → +1.24)
- Directional consistency: 1/4 below RS, 2/4 above RS, 1/4 neutral (dominant: positive)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Derrick White 3PM emerging playoff trend: no career-aggregate signal (+0.1 across 73 games / 4 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

---

### Joel Embiid (PHI, C) — demote_to_watch
*Already in dossier: yes | n_playoff_games: 36 | n_seasons: 4*

**PTS** — `demote_to_watch`
- Career RS baseline: 30.90 | Career PO avg: 26.60 | Static delta: -4.30
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -12.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 28.09 | -2.81 |
  | 2022 | 10 | 23.60 | -7.30 |
  | 2023 | 9 | 23.67 | -7.23 |
  | 2024 | 6 | 33.00 | +2.10 |
- Trajectory: **net_up** (-2.81 → +2.10)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Joel Embiid PTS playoff WATCH: historical suppression (career playoff avg 26.6 vs RS career 30.9 (-4.3 across 36 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**REB** — `no_signal`
- Career RS baseline: 10.70 | Career PO avg: 10.40 | Static delta: -0.30
- H28 flag: STABLE (key_tier T6, delta_pp -1.3pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 10.55 | -0.15 |
  | 2022 | 10 | 10.70 | +0.00 |
  | 2023 | 9 | 9.78 | -0.92 |
  | 2024 | 6 | 10.83 | +0.13 |
- Trajectory: **flat** (-0.15 → +0.13)
- Directional consistency: 1/4 below RS, 0/4 above RS, 3/4 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Joel Embiid REB no actionable signal: career playoff avg 10.4 vs RS career 10.7 (-0.3 across 36 games / 4 playoff seasons). Trajectory: flat, dominant direction: mixed.

**AST** — `demote_to_watch`
- Career RS baseline: 4.10 | Career PO avg: 3.20 | Static delta: -0.90
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -17.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 3.36 | -0.74 |
  | 2022 | 10 | 2.10 | -2.00 |
  | 2023 | 9 | 2.67 | -1.43 |
  | 2024 | 6 | 5.67 | +1.57 |
- Trajectory: **net_up** (-0.74 → +1.57)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Joel Embiid AST playoff WATCH: historical suppression (career playoff avg 3.2 vs RS career 4.1 (-0.9 across 36 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**3PM** — `no_signal`
- Career RS baseline: 1.20 | Career PO avg: 1.10 | Static delta: -0.10
- H28 flag: STABLE (key_tier T2, delta_pp +0.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 11 | 1.45 | +0.25 |
  | 2022 | 10 | 0.70 | -0.50 |
  | 2023 | 9 | 0.56 | -0.64 |
  | 2024 | 6 | 2.17 | +0.97 |
- Trajectory: **net_up** (+0.25 → +0.97)
- Directional consistency: 2/4 below RS, 1/4 above RS, 1/4 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Joel Embiid 3PM no actionable signal: career playoff avg 1.1 vs RS career 1.2 (-0.1 across 36 games / 4 playoff seasons). Trajectory: net_up, dominant direction: negative.

---

### Jarrett Allen (CLE, C) — demote_to_watch
*Already in dossier: no | n_playoff_games: 18 | n_seasons: 3*

**PTS** — `demote_to_watch`
- Career RS baseline: 14.60 | Career PO avg: 13.10 | Static delta: -1.50
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -5.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 9.40 | -5.20 |
  | 2024 | 4 | 17.00 | +2.40 |
  | 2025 | 9 | 13.44 | -1.16 |
- Trajectory: **net_up** (-5.20 → -1.16)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jarrett Allen PTS playoff WATCH: historical suppression (career playoff avg 13.1 vs RS career 14.6 (-1.5 across 18 games / 3 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**REB** — `demote_to_watch`
- Career RS baseline: 10.10 | Career PO avg: 9.30 | Static delta: -0.80
- H28 flag: SUPPRESSOR (key_tier T6, delta_pp -21.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 7.40 | -2.70 |
  | 2024 | 4 | 13.75 | +3.65 |
  | 2025 | 9 | 8.44 | -1.66 |
- Trajectory: **net_up** (-2.70 → -1.66)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jarrett Allen REB playoff WATCH: historical suppression (career playoff avg 9.3 vs RS career 10.1 (-0.8 across 18 games / 3 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**AST** — `no_signal`
- Career RS baseline: 2.00 | Career PO avg: 1.60 | Static delta: -0.40
- H28 flag: STABLE (key_tier T4, delta_pp -3.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 2.40 | +0.40 |
  | 2024 | 4 | 1.25 | -0.75 |
  | 2025 | 9 | 1.33 | -0.67 |
- Trajectory: **net_down** (+0.40 → -0.67)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jarrett Allen AST no actionable signal: career playoff avg 1.6 vs RS career 2.0 (-0.4 across 18 games / 3 playoff seasons). Trajectory: net_down, dominant direction: negative.

**3PM** — `no_signal`
- Career RS baseline: 0.00 | Career PO avg: 0.00 | Static delta: +0.00
- H28 flag: STABLE (key_tier T2, delta_pp +0.0pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2023 | 5 | 0.00 | +0.00 |
  | 2024 | 4 | 0.00 | +0.00 |
  | 2025 | 9 | 0.00 | +0.00 |
- Trajectory: **flat** (+0.00 → +0.00)
- Directional consistency: 0/3 below RS, 0/3 above RS, 3/3 neutral (dominant: mixed)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Jarrett Allen 3PM no actionable signal: career playoff avg 0.0 vs RS career 0.0 (+0.0 across 18 games / 3 playoff seasons). Trajectory: flat, dominant direction: mixed.

---

### LeBron James (LAL, SF) — demote_to_watch
*Already in dossier: no | n_playoff_games: 32 | n_seasons: 4*

**PTS** — `demote_to_watch`
- Career RS baseline: 26.70 | Career PO avg: 24.90 | Static delta: -1.80
- H28 flag: ELEVATOR (key_tier T20, delta_pp +9.6pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 23.33 | -3.37 |
  | 2023 | 16 | 24.50 | -2.20 |
  | 2024 | 5 | 27.80 | +1.10 |
  | 2025 | 5 | 25.40 | -1.30 |
- Trajectory: **net_up** (-3.37 → -1.30)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression, improving but not strictly monotonic — WATCH

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> LeBron James PTS playoff WATCH: historical suppression (career playoff avg 24.9 vs RS career 26.7 (-1.8 across 32 games / 4 playoff seasons)) but trajectory is improving (net_up). Annotation only — analyst weighs alongside other context.

**REB** — `no_signal`
- Career RS baseline: 7.90 | Career PO avg: 8.80 | Static delta: +0.90
- H28 flag: ELEVATOR (key_tier T6, delta_pp +7.7pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 7.17 | -0.73 |
  | 2023 | 16 | 9.88 | +1.98 |
  | 2024 | 5 | 6.80 | -1.10 |
  | 2025 | 5 | 9.00 | +1.10 |
- Trajectory: **net_up** (-0.73 → +1.10)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> LeBron James REB no actionable signal: career playoff avg 8.8 vs RS career 7.9 (+0.9 across 32 games / 4 playoff seasons). Trajectory: net_up, dominant direction: mixed.

**AST** — `no_signal`
- Career RS baseline: 7.50 | Career PO avg: 7.00 | Static delta: -0.50
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -5.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 8.00 | +0.50 |
  | 2023 | 16 | 6.50 | -1.00 |
  | 2024 | 5 | 8.80 | +1.30 |
  | 2025 | 5 | 5.60 | -1.90 |
- Trajectory: **net_down** (+0.50 → -1.90)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> LeBron James AST no actionable signal: career playoff avg 7.0 vs RS career 7.5 (-0.5 across 32 games / 4 playoff seasons). Trajectory: net_down, dominant direction: mixed.

**3PM** — `no_signal`
- Career RS baseline: 2.30 | Career PO avg: 2.10 | Static delta: -0.20
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -7.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 6 | 3.00 | +0.70 |
  | 2023 | 16 | 1.75 | -0.55 |
  | 2024 | 5 | 2.00 | -0.30 |
  | 2025 | 5 | 2.00 | -0.30 |
- Trajectory: **net_down** (+0.70 → -0.30)
- Directional consistency: 3/4 below RS, 1/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> LeBron James 3PM no actionable signal: career playoff avg 2.1 vs RS career 2.3 (-0.2 across 32 games / 4 playoff seasons). Trajectory: net_down, dominant direction: negative.

---

### Desmond Bane (ORL, SG) — ship_trajectory_only
*Already in dossier: no | n_playoff_games: 27 | n_seasons: 4*

**PTS** — `no_signal`
- Career RS baseline: 17.90 | Career PO avg: 16.90 | Static delta: -1.00
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -7.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 5.60 | -12.30 |
  | 2022 | 12 | 18.75 | +0.85 |
  | 2023 | 6 | 23.50 | +5.60 |
  | 2025 | 4 | 15.25 | -2.65 |
- Trajectory: **net_up** (-12.30 → -2.65)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: Static delta passes magnitude but per-season directions are mixed

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Desmond Bane PTS no actionable signal: career playoff avg 16.9 vs RS career 17.9 (-1.0 across 27 games / 4 playoff seasons). Trajectory: net_up, dominant direction: mixed.

**REB** — `ship_trajectory_only`
- Career RS baseline: 4.60 | Career PO avg: 4.60 | Static delta: +0.00
- H28 flag: STABLE (key_tier T6, delta_pp -4.1pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 3.40 | -1.20 |
  | 2022 | 12 | 3.75 | -0.85 |
  | 2023 | 6 | 6.00 | +1.40 |
  | 2025 | 4 | 6.75 | +2.15 |
- Trajectory: **monotonic_up** (-1.20 → +2.15)
- Directional consistency: 2/4 below RS, 2/4 above RS, 0/4 neutral (dominant: mixed)
- Rationale: No static signal, but monotonic_up trajectory across seasons

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Desmond Bane REB emerging playoff trend: no career-aggregate signal (+0.0 across 27 games / 4 seasons) but trajectory is monotonic_up. Each playoff is better than the last — emerging BOOST candidate; annotation only.

**AST** — `suppress_candidate`
- Career RS baseline: 3.80 | Career PO avg: 2.50 | Static delta: -1.30
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -16.5pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 2.00 | -1.80 |
  | 2022 | 12 | 2.17 | -1.63 |
  | 2023 | 6 | 3.17 | -0.63 |
  | 2025 | 4 | 3.25 | -0.55 |
- Trajectory: **monotonic_up** (-1.80 → -0.55)
- Directional consistency: 4/4 below RS, 0/4 above RS, 0/4 neutral (dominant: negative)
- Rationale: Static suppression but monotonic improvement — player fixing it

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Desmond Bane AST suppress_candidate (do NOT ship): static suppression (-1.3) but monotonic improvement across seasons — player is fixing it; do not annotate as caution.

**3PM** — `no_signal`
- Career RS baseline: 2.60 | Career PO avg: 2.70 | Static delta: +0.10
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -8.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 5 | 1.20 | -1.40 |
  | 2022 | 12 | 3.58 | +0.98 |
  | 2023 | 6 | 2.67 | +0.07 |
  | 2025 | 4 | 1.75 | -0.85 |
- Trajectory: **net_up** (-1.40 → -0.85)
- Directional consistency: 2/4 below RS, 1/4 above RS, 1/4 neutral (dominant: negative)
- Rationale: Neither static nor trajectory signal

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Desmond Bane 3PM no actionable signal: career playoff avg 2.7 vs RS career 2.6 (+0.1 across 27 games / 4 playoff seasons). Trajectory: net_up, dominant direction: negative.

---

## Candidates Suppressed by Trajectory

### Cameron Johnson (DEN, SF) — suppress_candidate
*Already in dossier: no | n_playoff_games: 38 | n_seasons: 3*

**PTS** — `suppress_candidate`
- Career RS baseline: 13.70 | Career PO avg: 10.20 | Static delta: -3.50
- H28 flag: SUPPRESSOR (key_tier T20, delta_pp -14.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 21 | 8.19 | -5.51 |
  | 2022 | 13 | 10.77 | -2.93 |
  | 2023 | 4 | 18.50 | +4.80 |
- Trajectory: **monotonic_up** (-5.51 → +4.80)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression but monotonic improvement — player fixing it

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Cameron Johnson PTS suppress_candidate (do NOT ship): static suppression (-3.5) but monotonic improvement across seasons — player is fixing it; do not annotate as caution.

**REB** — `suppress_candidate`
- Career RS baseline: 4.10 | Career PO avg: 3.60 | Static delta: -0.50
- H28 flag: SUPPRESSOR (key_tier T6, delta_pp -17.2pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 21 | 3.14 | -0.96 |
  | 2022 | 13 | 3.54 | -0.56 |
  | 2023 | 4 | 5.75 | +1.65 |
- Trajectory: **monotonic_up** (-0.96 → +1.65)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression but monotonic improvement — player fixing it

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Cameron Johnson REB suppress_candidate (do NOT ship): static suppression (-0.5) but monotonic improvement across seasons — player is fixing it; do not annotate as caution.

**AST** — `suppress_candidate`
- Career RS baseline: 2.10 | Career PO avg: 1.20 | Static delta: -0.90
- H28 flag: SUPPRESSOR (key_tier T4, delta_pp -9.8pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 21 | 0.76 | -1.34 |
  | 2022 | 13 | 1.54 | -0.56 |
  | 2023 | 4 | 2.75 | +0.65 |
- Trajectory: **monotonic_up** (-1.34 → +0.65)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression but monotonic improvement — player fixing it

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Cameron Johnson AST suppress_candidate (do NOT ship): static suppression (-0.9) but monotonic improvement across seasons — player is fixing it; do not annotate as caution.

**3PM** — `suppress_candidate`
- Career RS baseline: 2.40 | Career PO avg: 1.80 | Static delta: -0.60
- H28 flag: SUPPRESSOR (key_tier T2, delta_pp -16.4pp)
- Per-season:
  | Season | n_games | PO avg | Δ vs RS |
  |--------|---------|--------|---------|
  | 2021 | 21 | 1.57 | -0.83 |
  | 2022 | 13 | 1.69 | -0.71 |
  | 2023 | 4 | 3.00 | +0.60 |
- Trajectory: **monotonic_up** (-0.83 → +0.60)
- Directional consistency: 2/3 below RS, 1/3 above RS, 0/3 neutral (dominant: negative)
- Rationale: Static suppression but monotonic improvement — player fixing it

**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):
> Cameron Johnson 3PM suppress_candidate (do NOT ship): static suppression (-0.6) but monotonic improvement across seasons — player is fixing it; do not annotate as caution.

---

## Insufficient Sample / No H28 Coverage

### Players with <3 playoff seasons
- **Alperen Sengun** (HOU) — 1 prior playoff season(s), 7 game(s)
- **Amen Thompson** (HOU) — 1 prior playoff season(s), 7 game(s)
- **Ausar Thompson** (DET) — 1 prior playoff season(s), 6 game(s)
- **Brandon Ingram** (TOR) — 2 prior playoff season(s), 10 game(s)
- **Cade Cunningham** (DET) — 1 prior playoff season(s), 6 game(s)
- **Chet Holmgren** (OKC) — 2 prior playoff season(s), 33 game(s)
- **De'Aaron Fox** (SAS) — 1 prior playoff season(s), 7 game(s)
- **Immanuel Quickley** (TOR) — 2 prior playoff season(s), 13 game(s)
- **Jabari Smith Jr.** (HOU) — 1 prior playoff season(s), 7 game(s)
- **Jalen Duren** (DET) — 1 prior playoff season(s), 6 game(s)
- **Jalen Green** (PHX) — 1 prior playoff season(s), 7 game(s)
- **Jalen Johnson** (ATL) — 2 prior playoff season(s), 8 game(s)
- **Jalen Williams** (OKC) — 2 prior playoff season(s), 33 game(s)
- **Neemias Queta** (BOS) — 2 prior playoff season(s), 7 game(s)
- **Paolo Banchero** (ORL) — 2 prior playoff season(s), 12 game(s)
- **Paul George** (PHI) — 2 prior playoff season(s), 25 game(s)
- **RJ Barrett** (TOR) — 2 prior playoff season(s), 16 game(s)
- **Shai Gilgeous-Alexander** (OKC) — 2 prior playoff season(s), 33 game(s)

### Players with no H28 entry
- **Devin Vassell** (SAS)
- **Dylan Harper** (SAS)
- **Scottie Barnes** (TOR)
- **Stephon Castle** (SAS)
- **VJ Edgecombe** (PHI)
- **Victor Wembanyama** (SAS)

## Evaluated but No Actionable Signal

*These players have ≥3 playoff seasons in H28 but produced no ship-worthy verdict on any stat. Listed for completeness — no action.*

- **Isaiah Hartenstein** (OKC) — 3 seasons, in dossier: no
