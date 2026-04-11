#!/usr/bin/env python3
"""
NBAgent — Backtest

Retrospective analysis of which Quant signals are actually predictive of
player prop tier hits. Runs standalone against historical game log data.

Usage:
    python agents/backtest.py                        # all available data
    python agents/backtest.py --season 2026          # filter by season_end_year
    python agents/backtest.py --start 2025-10-21 --end 2026-03-01

Writes: data/backtest_results.json
Prints: formatted signal quality report to stdout
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GAME_LOG_CSV   = DATA / "player_game_log.csv"
TEAM_LOG_CSV   = DATA / "team_game_log.csv"
MASTER_CSV     = DATA / "nba_master.csv"
WHITELIST_CSV  = ROOT / "playerprops" / "player_whitelist.csv"
RESULTS_JSON          = DATA / "backtest_results.json"
BOUNCE_BACK_JSON      = DATA / "backtest_bounce_back.json"
MEAN_REVERSION_JSON   = DATA / "backtest_mean_reversion.json"
RECENCY_WEIGHT_JSON        = DATA / "backtest_recency_weight.json"
PLAYER_BOUNCE_BACK_JSON    = DATA / "bounce_back_players.json"
POST_BLOWOUT_JSON          = DATA / "backtest_post_blowout.json"
OPP_FATIGUE_JSON           = DATA / "backtest_opp_fatigue.json"
SHOOTING_REGRESSION_JSON   = DATA / "backtest_shooting_regression.json"
STAR_ABSENCE_JSON          = DATA / "backtest_star_absence.json"

# ── Tier definitions (mirrors quant.py) ───────────────────────────────
PTS_TIERS = [10, 15, 20, 25, 30]
REB_TIERS = [4, 6, 8, 10, 12]
AST_TIERS = [2, 4, 6, 8, 10, 12]
TPM_TIERS = [1, 2, 3, 4]

TIERS    = {"PTS": PTS_TIERS, "REB": REB_TIERS, "AST": AST_TIERS, "3PM": TPM_TIERS}
STAT_COL = {"PTS": "pts",     "REB": "reb",     "AST": "ast",     "3PM": "tpm"}

# ── Analysis config ───────────────────────────────────────────────────
ROLLING_WINDOW      = 10    # games for tier hit rate + trend base
TREND_SHORT_WINDOW  = 5     # games for "recent" comparison
TREND_THRESHOLD     = 0.10  # >10% delta = up/down
OPP_WINDOW          = 15    # games for opponent defensive rolling avg
OPP_MIN_GAMES       = 5     # min opp games required for rating (not null)
CONFIDENCE_FLOOR    = 0.70  # min historical hit rate to qualify as "best tier"
MIN_SIGNAL_N        = 15    # min instances per signal value for lift (else insufficient_sample)
LIFT_PREDICTIVE     = 0.15  # max_lift - min_lift > this → predictive
LIFT_WEAK           = 0.08  # > this → weak
CALIBRATION_CONCERN = 0.68  # actual hit rate below this → threshold_concern
SPREAD_HIGH         = 10.0  # abs(spread) > this → "high" risk
SPREAD_MODERATE     = 6.5   # abs(spread) > this → "moderate" risk

POST_BLOWOUT_THRESHOLD = 15   # points margin to classify as blowout
OPP_DENSE_THRESHOLD    = 4    # games in OPP_DENSE_WINDOW days = dense
OPP_DENSE_WINDOW       = 5    # days window for dense schedule check (mirrors quant.py)

# Shooting regression mode constants (mirrors quant.py compute_shooting_regression)
SR_L5_WINDOW   = 5     # games for "recent" FG%
SR_L20_WINDOW  = 20    # games for "baseline" FG%
SR_MIN_GAMES   = 10    # min valid shooting games to qualify (mirrors quant.py)
SR_HOT_THRESH  = 0.08  # relative delta >= +8% → FG_HOT
SR_COLD_THRESH = 0.08  # relative delta <= -8% → FG_COLD
SR_MIN_N       = 20    # min instances per flag bucket for a verdict

# Shot volume mode constants
SV_JSON        = DATA / "backtest_shot_volume.json"
SV_L5_WINDOW   = 5     # recent FGA window
SV_L20_WINDOW  = 20    # baseline FGA window
SV_MIN_GAMES   = 10    # min valid FGA games in L20 window to qualify
SV_LOW_THRESH  = 0.10  # delta <= -10% → volume_low
SV_HIGH_THRESH = 0.10  # delta >= +10% → volume_high
SV_MIN_N       = 20    # min instances per bucket for a verdict

# Star absence mode constants (H26)
SA_MIN_STAR_GAMES    = 20   # min non-DNP games to qualify as team's "leading scorer"
SA_MIN_ABSENT_GAMES  = 5    # min star-absent games per team for analysis
SA_MIN_CONDITION_N   = 3    # min games per condition (with/without star) per teammate per tier

# FG% safety margin mode constants
FSM_JSON        = DATA / "backtest_ft_safety_margin.json"
FSM_L20_WINDOW  = 20    # games used to compute season averages
FSM_MIN_GAMES   = 10    # min valid (non-DNP, fga>0) games in L20 to qualify
FSM_SAFE_THRESH = 0.05  # margin >= this → safe
FSM_FRAG_THRESH = 0.00  # margin <  this → fragile (else borderline)
FSM_MIN_N       = 20    # min instances per fragility bucket for a verdict

# Positional DvP mode constants (H8)
PDV_WINDOW        = 15    # games for rolling positional allowed avg (mirrors quant.py OPP_WINDOW)
PDV_MIN_GAMES     = 10    # min positional games to qualify (mirrors quant.py)
PDV_MIN_N         = 20    # min instances per rating bucket for a verdict
PDV_SOFT_PCTILE   = 33    # ≤ this percentile of allowed avg → "tough" defense
PDV_TOUGH_PCTILE  = 67    # ≥ this percentile of allowed avg → "soft" defense
POSITIONAL_DVP_JSON = DATA / "backtest_positional_dvp.json"

# Opponent team hit rate mode constants (H15)
OTH_MIN_PICKS        = 15    # min picks against an opponent for a hit rate figure
OTH_MIN_PROP_PICKS   = 5     # min picks for a prop-specific split
OTH_MIN_MISSES       = 3     # min misses for a miss-margin figure
OTH_SUPPRESSOR_DELTA = 0.10  # hit rate ≥10pp below baseline → suppressor
OTH_AMPLIFIER_DELTA  = 0.10  # hit rate ≥10pp above baseline → amplifier
OTH_MARGIN_FLOOR_CMP = -5.0  # mean miss margin ≤ this → floor compression signal
OPP_TEAM_HIT_RATE_JSON = DATA / "backtest_opp_team_hit_rate.json"

# 3PA Volume Gate mode constants (H16)
H16_L10_WINDOW        = 10     # L10 window for avg_3pa computation (mirrors PLAYER_WINDOW)
H16_MIN_GAMES         = 5      # min non-DNP games prior to pick date to qualify
H16_MIN_N             = 15     # min picks per bucket/profile for a reportable hit rate
H16_MIN_N_H16C        = 10     # min picks per 3PA floor threshold for H16c
H16_VOL_LOW_MAX       = 3.0    # avg_3pa_l10 < this → low-vol bucket
H16_VOL_HIGH_MIN      = 5.0    # avg_3pa_l10 ≥ this → high-vol bucket
H16_PCT_HIGH_MIN      = 0.37   # avg_3pct_l10 ≥ this → high-pct profile
H16_ACTIONABLE_DELTA  = 0.15   # ≥15pp gap low vs high → actionable signal
H16_WEAK_DELTA        = 0.08   # 8–14pp gap → weak signal / annotation only
THREE_PA_VOLUME_JSON  = DATA / "backtest_3pa_volume_gate.json"

# H19 — In-game blowout regime
H19_JSON               = DATA / "backtest_blowout_regime.json"
H19_BLOWOUT_MARGIN     = 15    # final score margin ≥ this → blowout game
H19_MIN_MINUTES_GATE   = 24    # minimum minutes played to include in analysis
H19_MIN_N              = 15    # minimum instances for a verdict

# H20 — Losing-side blowout AST suppression
H20_JSON                = DATA / "backtest_losing_side_ast.json"
H20_UNDERDOG_THRESHOLDS = [6.5, 10.0, 15.0]  # spread_abs breakpoints
H20_PRIMARY_AST_AVG     = 6.0                 # rolling avg threshold for primary ball-handler
H20_MIN_N               = 20                  # min instances per bucket for a verdict

# H14 — Elite opposing rebounder REB suppression
H14_JSON                  = DATA / "backtest_elite_opp_rebounder.json"
H14_ELITE_REB_THRESHOLDS  = [8.0, 10.0, 12.0]  # rolling avg REB thresholds to test
H14_OPP_REB_WINDOW        = 15   # games for opponent player rolling avg (mirrors OPP_WINDOW)
H14_OPP_MIN_GAMES         = 5    # min games for opponent player avg to qualify
H14_MIN_N                 = 20   # min instances per bucket for a verdict
H14_OREB_WINDOW           = 15   # games for team OREB rate rolling avg

# H21 — Miss Anatomy: near-miss vs. blowup next-game prediction
H21_JSON             = DATA / "backtest_miss_anatomy.json"
H21_NEAR_MISS_THRESH = 2      # actual >= tier - this → near-miss
H21_BLOWUP_THRESH    = 3      # actual < tier - this → blowup
H21_MIN_MISSES       = 3      # min misses per player-stat combo for player-level analysis
H21_MIN_N            = 15     # min next-game instances per bucket for a verdict

# H27 — Primary Scorer Blowout PTS Performance
H27_SPREAD_THRESHOLDS     = [10, 12, 15]  # maps to blowout_risk(8+), cap-74(12+), hard-skip(15+)
H27_PTS_TIERS             = [15, 20, 25, 30]  # PTS tiers to test (the actionable ones)
H27_MIN_N                 = 10   # min instances per cell for a population verdict
H27_MIN_PLAYER_N          = 3    # min high-spread games per player for per-player table
H27_ACTUAL_BLOWOUT_MARGIN = 15   # final margin threshold to classify "actual blowout"
PRIMARY_BLOWOUT_JSON      = DATA / "backtest_primary_blowout.json"

# H31 — Playoff Series Progression
H31_STATS = ["PTS", "REB", "AST", "3PM"]
H31_STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
H31_TIERS = {
    "PTS": [15, 20, 25, 30],
    "REB": [4, 6, 8, 10],
    "AST": [2, 4, 6, 8],
    "3PM": [1, 2, 3],
}
H31_KEY_TIER = {"PTS": 20, "REB": 6, "AST": 4, "3PM": 2}
H31_PHASES = ["early", "mid", "late"]
H31_MIN_PHASE_N           = 5    # min games in a phase for per-player rate
H31_MIN_TOTAL_PLAYOFF     = 15   # min total playoff games for per-player table
H31_PROGRESSION_THRESHOLD = 8.0  # |late - early| >= 8pp at key tier → meaningful progression
SERIES_PROGRESSION_JSON = DATA / "backtest_series_progression.json"

# H32 — Player Consistency Index
H32_STATS = ["PTS", "REB", "AST", "3PM"]
H32_STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
H32_MIN_SLICE_N        = 5     # min games in a context slice to include in stability calc
H32_MIN_TOTAL_GAMES    = 20    # min total games for a player to qualify
H32_ALLWEATHER_RANGE   = 10.0  # max_rate - min_rate < 10pp → ALL_WEATHER
H32_SENSITIVE_RANGE    = 20.0  # range >= 20pp → CONTEXT_SENSITIVE
H32_SPREAD_THRESHOLD   = 6.5   # split competitive vs blowout-risk (mirrors quant.py)
CONSISTENCY_INDEX_JSON = DATA / "backtest_consistency_index.json"

# H30 — Minutes Elasticity
H30_STATS = ["PTS", "REB", "AST", "3PM"]
H30_STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
H30_TIERS = {
    "PTS": [15, 20, 25, 30],
    "REB": [4, 6, 8, 10],
    "AST": [2, 4, 6, 8],
    "3PM": [1, 2, 3],
}
H30_KEY_TIER = {"PTS": 20, "REB": 6, "AST": 4, "3PM": 2}
H30_MIN_BUCKET_N     = 5         # min games in a bucket to include
H30_MIN_TOTAL_GAMES  = 20        # min total games for a player to qualify
H30_MINUTES_BINS     = [0, 30, 34, 38, 60]
H30_MINUTES_LABELS   = ["low", "normal", "high", "extended"]
# Elasticity flags — based on delta between "extended" (38+) and "normal" (30-34) at key tier
H30_SCALES_THRESHOLD  = 10.0     # extended - normal >= +10pp → SCALES
H30_INVERTS_THRESHOLD = -10.0    # extended - normal <= -10pp → INVERTS
H30_POPULATION_MIN_MIN = 28      # pooled population filters to starter-level averages only
MINUTES_ELASTICITY_JSON = DATA / "backtest_minutes_elasticity.json"

# H29 — Player-Level Confidence Calibration
H29_MIN_PICKS            = 10    # min graded picks for a per-player verdict
H29_MIN_PROP_PICKS       = 5     # min picks per prop_type for per-prop breakdown
H29_MIN_BAND_PICKS       = 3     # min picks per band for per-player band breakdown
H29_OVER_CONF_THRESHOLD  = 8.0   # assigned - actual >= 8pp → OVER_CONFIDENT
H29_UNDER_CONF_THRESHOLD = 8.0   # actual - assigned >= 8pp → UNDER_CONFIDENT
H29_CONF_BANDS = [
    (70, 75, "70-75"),
    (76, 80, "76-80"),
    (81, 85, "81-85"),
    (86, 99, "86+"),
]
CONFIDENCE_CAL_JSON = DATA / "backtest_confidence_calibration.json"

# H28 — Playoff Career Tier Performance
H28_STATS = ["PTS", "REB", "AST", "3PM"]
H28_STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
H28_TIERS = {
    "PTS": [15, 20, 25, 30],
    "REB": [4, 6, 8, 10],
    "AST": [2, 4, 6, 8],
    "3PM": [1, 2, 3],
}
# "Key tier" per stat — used for the summary flag (ELEVATOR/STABLE/SUPPRESSOR)
H28_KEY_TIER = {"PTS": 20, "REB": 6, "AST": 4, "3PM": 2}
H28_MIN_PLAYOFF_GAMES    = 10        # min playoff games for a reliable per-player verdict
H28_LIMITED_SAMPLE_MIN   = 5         # 5-9 playoff games: report but flag as limited_sample
H28_ELEVATOR_THRESHOLD   = 5.0       # delta >= +5pp at key tier = ELEVATOR
H28_SUPPRESSOR_THRESHOLD = -5.0      # delta <= -5pp at key tier = SUPPRESSOR
H28_ALLSTAR_TEAMS = {"CAN", "CHK", "DUR", "EAST", "GIA", "KEN", "LEB", "SHQ", "WEST"}
PLAYOFF_CAREER_CSV  = DATA / "playoff_career_log.csv"
PLAYOFF_CAREER_JSON = DATA / "backtest_playoff_career.json"

_ABBR_NORM_BT = {
    "GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP",
    "UTAH": "UTA", "WSH": "WAS", "UTH": "UTA",
}


# ── Loaders ───────────────────────────────────────────────────────────

def load_whitelist() -> set:
    if not WHITELIST_CSV.exists():
        print("[backtest] WARNING: whitelist not found — no player filtering.")
        return set()
    df = pd.read_csv(WHITELIST_CSV, dtype=str)
    active = df[df["active"].astype(str).str.strip() == "1"]
    return set(zip(
        active["player_name"].str.strip().str.lower(),
        active["team_abbr"].str.strip().str.upper(),
    ))


def load_player_log(whitelist: set, args) -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        print("[backtest] ERROR: player_game_log.csv not found.")
        sys.exit(1)
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df = df[df["dnp"].astype(str).str.strip() != "1"].copy()
    for col in ["pts", "reb", "ast", "tpm", "minutes_raw"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    # Shooting columns: keep NaN where data is absent — do NOT fill with 0
    for col in ["fgm", "fga", "fg3m", "fg3a"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan

    # Optional date / season filters
    if getattr(args, "season", None):
        df = df[df["season_end_year"].astype(str) == str(args.season)]
    if getattr(args, "start", None):
        df = df[df["game_date"] >= pd.Timestamp(args.start)]
    if getattr(args, "end", None):
        df = df[df["game_date"] <= pd.Timestamp(args.end)]

    # Whitelist filter: (lowercase name, uppercase team)
    if whitelist:
        mask = df.apply(
            lambda r: (
                str(r["player_name"]).strip().lower(),
                str(r["team_abbrev"]).strip().upper(),
            ) in whitelist,
            axis=1,
        )
        df = df[mask].copy()

    df = df.sort_values(["player_name", "game_date"]).reset_index(drop=True)
    print(f"[backtest] Player log: {len(df):,} rows  |  "
          f"{df['player_name'].nunique()} players  |  "
          f"{df['game_date'].min().date()} – {df['game_date'].max().date()}")
    return df


def load_team_log(args) -> pd.DataFrame:
    if not TEAM_LOG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(TEAM_LOG_CSV, dtype={"game_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    for col in ["team_pts", "team_reb", "team_ast", "team_tpm"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    if getattr(args, "start", None):
        df = df[df["game_date"] >= pd.Timestamp(args.start)]
    if getattr(args, "end", None):
        df = df[df["game_date"] <= pd.Timestamp(args.end)]
    return df.sort_values("game_date").reset_index(drop=True)


def load_master(args) -> pd.DataFrame:
    if not MASTER_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(MASTER_CSV, dtype=str)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
    df["game_id"] = df["game_id"].astype(str).str.split(".").str[0].str.strip()
    for col in ["home_spread", "away_spread"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if getattr(args, "start", None):
        df = df[df["game_date"] >= pd.Timestamp(args.start)]
    if getattr(args, "end", None):
        df = df[df["game_date"] <= pd.Timestamp(args.end)]
    return df


def load_picks_json() -> list:
    """Load all graded picks from data/picks.json. Used by H15."""
    picks_path = DATA / "picks.json"
    if not picks_path.exists():
        print("[backtest] WARNING: picks.json not found — H15 requires graded picks")
        return []
    with open(picks_path) as f:
        raw = json.load(f)
    picks = raw if isinstance(raw, list) else []
    graded = [
        p for p in picks
        if p.get("result") in ("HIT", "MISS")
        and not p.get("voided", False)
    ]
    print(f"[backtest] picks.json: {len(graded)} graded picks "
          f"({sum(1 for p in graded if p['result'] == 'HIT')} HIT, "
          f"{sum(1 for p in graded if p['result'] == 'MISS')} MISS)")
    return graded


# ── Signal 1: Trend ───────────────────────────────────────────────────

def add_trend_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add trend_{stat} columns (up/stable/down/null) for each stat.
    Computed per player using only prior games (shift before rolling).
    Requires ≥ 10 prior games; null otherwise.
    """
    df = df.copy()
    for stat, col in STAT_COL.items():
        grp = df.groupby("player_name")[col]
        avg10 = grp.transform(
            lambda x: x.shift(1).rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).mean()
        )
        avg5 = grp.transform(
            lambda x: x.shift(1).rolling(TREND_SHORT_WINDOW, min_periods=TREND_SHORT_WINDOW).mean()
        )
        # Compute trend direction
        ratio = (avg5 - avg10) / avg10.replace(0, np.nan)
        trend = pd.Series("null", index=df.index)
        trend = trend.where(avg10.isna() | avg5.isna(), other="stable")  # set stable as default
        trend[ratio > TREND_THRESHOLD]  = "up"
        trend[ratio < -TREND_THRESHOLD] = "down"
        # Re-apply null where data insufficient
        null_mask = avg10.isna() | avg5.isna()
        trend[null_mask] = "null"
        df[f"trend_{stat}"] = trend

    return df


# ── Signal 2: Opponent Defense ────────────────────────────────────────

def build_opp_defense_lookup(team_log: pd.DataFrame) -> dict:
    """
    Build a lookup: {(defending_team_upper, game_date): {stat: rating}}

    For each date in team_log, compute the defending team's 15-game rolling
    allowed average (using only games strictly before that date).
    Then rank all teams at that date and assign soft/mid/tough.

    Returns a dict keyed by (team_abbrev, date_string) for fast merge.
    The lookup is computed using a wide pivot + ffill approach (vectorized).
    """
    if team_log.empty:
        return {}

    # "allowed" by team X = rows where opp_abbrev == X (the scoring team's pts is what X allowed)
    allowed = team_log.rename(columns={
        "opp_abbrev":  "defending_team",
        "team_pts":    "allowed_pts",
        "team_reb":    "allowed_reb",
        "team_ast":    "allowed_ast",
        "team_tpm":    "allowed_tpm",
    })[["game_date", "defending_team", "allowed_pts", "allowed_reb", "allowed_ast", "allowed_tpm"]].copy()

    allowed["defending_team"] = allowed["defending_team"].str.upper().str.strip()
    allowed = allowed.sort_values(["defending_team", "game_date"]).reset_index(drop=True)

    stat_map = {"PTS": "allowed_pts", "REB": "allowed_reb", "AST": "allowed_ast", "3PM": "allowed_tpm"}

    # Compute 15-game rolling avg per team (shift=1 to exclude the current game)
    for col in stat_map.values():
        allowed[f"roll_{col}"] = allowed.groupby("defending_team")[col].transform(
            lambda x: x.shift(1).rolling(OPP_WINDOW, min_periods=OPP_MIN_GAMES).mean()
        )
        allowed[f"n_{col}"] = allowed.groupby("defending_team")[col].transform(
            lambda x: x.shift(1).rolling(OPP_WINDOW, min_periods=1).count()
        )

    # Pivot to wide format: index=game_date, columns=defending_team, values=roll_*
    result: dict = {}

    for stat, raw_col in stat_map.items():
        roll_col = f"roll_{raw_col}"
        n_col    = f"n_{raw_col}"

        pivot = allowed.pivot_table(
            index="game_date", columns="defending_team",
            values=roll_col, aggfunc="last"
        ).sort_index().ffill()

        pivot_n = allowed.pivot_table(
            index="game_date", columns="defending_team",
            values=n_col, aggfunc="last"
        ).sort_index().ffill()

        # Store as dict for merge_asof usage: {team: [(date, avg, n), ...]}
        for team in pivot.columns:
            for date, avg in pivot[team].dropna().items():
                n_games = pivot_n[team].get(date, 0)
                key = (team.upper(), stat)
                if key not in result:
                    result[key] = []
                result[key].append((date, float(avg), int(n_games) if not pd.isna(n_games) else 0))

    # Now build ranking snapshots per stat per date
    # For each date in the wide pivot, rank all teams
    ranking_lookup: dict = {}  # {(team_upper, date_str, stat): rating}

    for stat, raw_col in stat_map.items():
        roll_col = f"roll_{raw_col}"
        pivot = allowed.pivot_table(
            index="game_date", columns="defending_team",
            values=roll_col, aggfunc="last"
        ).sort_index().ffill()

        pivot_n = allowed.pivot_table(
            index="game_date", columns="defending_team",
            values=f"n_{raw_col}", aggfunc="last"
        ).sort_index().ffill()

        for date, row in pivot.iterrows():
            valid = row.dropna()
            n_valid = pivot_n.loc[date].reindex(valid.index).fillna(0)
            # Only include teams with sufficient data
            valid = valid[n_valid >= OPP_MIN_GAMES]
            if len(valid) < 3:
                continue
            n = len(valid)
            third = max(1, round(n / 3))
            sorted_teams = valid.sort_values().index.tolist()
            for rank, team in enumerate(sorted_teams, 1):
                if rank <= third:
                    rating = "tough"
                elif rank <= 2 * third:
                    rating = "mid"
                else:
                    rating = "soft"
                ranking_lookup[(team.upper(), str(date.date()), stat)] = rating

    print(f"[backtest] Opp defense lookup: {len(ranking_lookup):,} entries")
    return ranking_lookup


def add_opp_defense_signal(df: pd.DataFrame, opp_lookup: dict) -> pd.DataFrame:
    """Add opp_defense_{stat} columns (soft/mid/tough/null)."""
    df = df.copy()
    df["_date_str"] = df["game_date"].dt.strftime("%Y-%m-%d")
    df["_opp_upper"] = df["opp_abbrev"].str.upper().str.strip()

    for stat in STAT_COL:
        df[f"opp_def_{stat}"] = df.apply(
            lambda r: opp_lookup.get(
                (r["_opp_upper"], r["_date_str"], stat), "null"
            ),
            axis=1,
        )

    df = df.drop(columns=["_date_str", "_opp_upper"])
    return df


# ── Signal 3: Pace ────────────────────────────────────────────────────

def build_pace_lookup(team_log: pd.DataFrame, player_log: pd.DataFrame) -> pd.Series:
    """
    For each player-game, compute pace tag using only prior data.
    H2H preferred (if ≥3 prior meetings); falls back to team offensive avgs.
    Returns a Series indexed like player_log with values: high/mid/low.
    """
    if team_log.empty:
        return pd.Series("null", index=player_log.index)

    tl = team_log[["game_date", "game_id", "team_abbrev", "opp_abbrev", "team_pts"]].copy()
    tl["team_abbrev"] = tl["team_abbrev"].str.upper().str.strip()
    tl["opp_abbrev"]  = tl["opp_abbrev"].str.upper().str.strip()

    def pace_tag(avg: float) -> str:
        if avg > 220:
            return "high"
        if avg < 200:
            return "low"
        return "mid"

    def get_pace(team: str, opp: str, date: pd.Timestamp) -> str:
        prior = tl[tl["game_date"] < date]
        # H2H games (both directions, deduplicated by game_id)
        h2h = prior[
            ((prior["team_abbrev"] == team) & (prior["opp_abbrev"] == opp)) |
            ((prior["team_abbrev"] == opp)  & (prior["opp_abbrev"] == team))
        ]
        game_totals = (
            h2h.groupby("game_id")["team_pts"].sum()
            .sort_index(ascending=False)
            .head(10)
        )
        if len(game_totals) >= 3:
            return pace_tag(game_totals.mean())
        # Fallback: each team's offensive avg last 10 games
        home_avg = prior[prior["team_abbrev"] == team]["team_pts"].tail(10)
        away_avg = prior[prior["team_abbrev"] == opp]["team_pts"].tail(10)
        if len(home_avg) >= 3 and len(away_avg) >= 3:
            return pace_tag(home_avg.mean() + away_avg.mean())
        return "null"

    # Precompute unique (team, opp, date) combos to avoid recomputation
    combos = player_log[["team_abbrev", "opp_abbrev", "game_date"]].copy()
    combos["team_abbrev"] = combos["team_abbrev"].str.upper().str.strip()
    combos["opp_abbrev"]  = combos["opp_abbrev"].str.upper().str.strip()

    unique_combos = combos.drop_duplicates(subset=["team_abbrev", "opp_abbrev", "game_date"])
    print(f"[backtest] Computing pace for {len(unique_combos):,} unique matchup-dates...")
    pace_cache = {}
    for _, row in unique_combos.iterrows():
        key = (row["team_abbrev"], row["opp_abbrev"], row["game_date"])
        pace_cache[key] = get_pace(row["team_abbrev"], row["opp_abbrev"], row["game_date"])

    result = combos.apply(
        lambda r: pace_cache.get(
            (r["team_abbrev"], r["opp_abbrev"], r["game_date"]), "null"
        ),
        axis=1,
    )
    result.index = player_log.index
    return result


# ── Signal 4: Back-to-Back ────────────────────────────────────────────

def add_b2b_signal(df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """Add on_b2b column (True/False)."""
    df = df.copy()
    if master_df.empty:
        df["on_b2b"] = False
        return df

    # Build set of (team_upper, date) for all game dates
    home_games = master_df[["game_date", "home_team_abbrev"]].rename(
        columns={"home_team_abbrev": "team"}
    )
    away_games = master_df[["game_date", "away_team_abbrev"]].rename(
        columns={"away_team_abbrev": "team"}
    )
    all_games = pd.concat([home_games, away_games]).dropna()
    all_games["team"] = all_games["team"].str.upper().str.strip()
    all_games = all_games.drop_duplicates()

    # For each (team, date), check if (team, date - 1 day) exists
    game_set = set(
        zip(all_games["team"], all_games["game_date"].dt.date)
    )

    def is_b2b(team: str, date: pd.Timestamp) -> bool:
        prev = (date - pd.Timedelta(days=1)).date()
        return (team.upper().strip(), prev) in game_set

    df["on_b2b"] = df.apply(
        lambda r: is_b2b(str(r["team_abbrev"]), r["game_date"]),
        axis=1,
    )
    return df


# ── Signal 6: Spread Risk ─────────────────────────────────────────────

def add_spread_signal(df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """Add spread_risk column (high/moderate/none/null)."""
    df = df.copy()
    if master_df.empty:
        df["spread_risk"] = "null"
        return df

    # Normalize game_id in player log
    df["_gid"] = df["game_id"].astype(str).str.split(".").str[0].str.strip()

    # Build spread lookup: {game_id: {team_upper: abs_spread}}
    spread_map = {}
    for _, row in master_df.iterrows():
        gid  = str(row.get("game_id", "")).strip()
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        hs   = row.get("home_spread")
        as_  = row.get("away_spread")
        for team, spread in [(home, hs), (away, as_)]:
            if team and not pd.isna(spread):
                spread_map[(gid, team)] = abs(float(spread))

    def risk(row) -> str:
        abs_sp = spread_map.get((row["_gid"], str(row["team_abbrev"]).upper().strip()))
        if abs_sp is None:
            return "null"
        if abs_sp > SPREAD_HIGH:
            return "high"
        if abs_sp > SPREAD_MODERATE:
            return "moderate"
        return "none"

    df["spread_risk"] = df.apply(risk, axis=1)
    df = df.drop(columns=["_gid"])
    return df


# ── Best Tier Selection ───────────────────────────────────────────────

def add_best_tiers(df: pd.DataFrame, window: int = ROLLING_WINDOW) -> pd.DataFrame:
    """
    For each player-game-stat, compute the best tier: highest tier where the
    prior {window}-game hit rate ≥ CONFIDENCE_FLOOR. Stored as best_tier_{stat}.

    Also adds hit_actual_{stat}: whether the actual stat exceeded best tier.
    Uses only prior games (shift=1 before rolling).
    """
    df = df.copy()

    for stat, col in STAT_COL.items():
        tiers = sorted(TIERS[stat], reverse=True)  # highest first

        # Compute rolling hit rates for each tier (vectorized, shift to exclude current game)
        hr_cols = {}
        for tier in tiers:
            hit_col = f"_hit_{stat}_{tier}"
            df[hit_col] = (df[col] >= tier).astype(float)
            hr_col = f"_hr_{stat}_{tier}"
            df[hr_col] = df.groupby("player_name")[hit_col].transform(
                lambda x: x.shift(1).rolling(window, min_periods=window).mean()
            )
            hr_cols[tier] = hr_col

        # Find best tier: highest tier where hr >= CONFIDENCE_FLOOR
        best = pd.Series(np.nan, index=df.index, dtype="float64")
        for tier in tiers:
            qualifies = df[hr_cols[tier]] >= CONFIDENCE_FLOOR
            no_pick_yet = best.isna()
            best = best.where(~(qualifies & no_pick_yet), other=float(tier))

        df[f"best_tier_{stat}"] = best

        # Actual hit: actual stat >= best_tier_value
        actual_hit = pd.Series(np.nan, index=df.index, dtype="float64")
        has_tier = best.notna()
        if has_tier.any():
            actual_hit[has_tier] = (
                df.loc[has_tier, col] >= df.loc[has_tier, f"best_tier_{stat}"]
            ).astype(float)
        df[f"hit_actual_{stat}"] = actual_hit

        # Cleanup temp columns
        df = df.drop(columns=[f"_hit_{stat}_{t}" for t in tiers] +
                              [f"_hr_{stat}_{t}" for t in tiers])

    return df


# ── Signal Analysis ───────────────────────────────────────────────────

SIGNALS = {
    "trend":       {s: f"trend_{s}" for s in STAT_COL},
    "opp_defense": {s: f"opp_def_{s}" for s in STAT_COL},
    "pace_tag":    {s: "pace_tag" for s in STAT_COL},  # same col for all stats
    "on_b2b":      {s: "on_b2b" for s in STAT_COL},
    "home_away":   {s: "home_away" for s in STAT_COL},
    "spread_risk": {s: "spread_risk" for s in STAT_COL},
}


def analyze_signal(
    df: pd.DataFrame,
    stat: str,
    signal_col: str,
    signal_name: str,
) -> dict:
    """
    Compute hit rate by signal value for one stat × signal combination.
    Returns dict with baseline, by_value, verdict.
    """
    best_col = f"best_tier_{stat}"
    hit_col  = f"hit_actual_{stat}"

    # Filter to qualified instances: has a best tier and signal is not null
    qualified = df[
        df[best_col].notna() &
        df[hit_col].notna() &
        df[signal_col].astype(str).ne("null") &
        df[signal_col].notna()
    ].copy()

    if qualified.empty:
        return {"baseline_hit_rate": None, "by_value": {}, "verdict": "insufficient_data", "verdict_reason": "no qualified instances"}

    baseline_n    = len(qualified)
    baseline_hits = int(qualified[hit_col].sum())
    baseline_rate = round(baseline_hits / baseline_n, 4) if baseline_n > 0 else None

    by_value = {}
    for val, grp in qualified.groupby(signal_col):
        n    = len(grp)
        hits = int(grp[hit_col].sum())
        if n < MIN_SIGNAL_N:
            by_value[str(val)] = {"n": n, "hits": hits, "hit_rate": None, "lift": None, "note": "insufficient_sample"}
        else:
            hr   = round(hits / n, 4)
            lift = round(hr / baseline_rate, 4) if baseline_rate else None
            by_value[str(val)] = {"n": n, "hits": hits, "hit_rate": hr, "lift": lift}

    # Compute verdict based on lift variance across values with sufficient data
    valid_lifts = [v["lift"] for v in by_value.values() if v.get("lift") is not None]
    if len(valid_lifts) < 2:
        verdict = "insufficient_data"
        reason  = "fewer than 2 signal values with sufficient sample"
    else:
        lift_variance = round(max(valid_lifts) - min(valid_lifts), 4)
        if lift_variance > LIFT_PREDICTIVE:
            verdict = "predictive"
            reason  = f"lift variance {lift_variance:.3f} > {LIFT_PREDICTIVE}"
        elif lift_variance > LIFT_WEAK:
            verdict = "weak"
            reason  = f"lift variance {lift_variance:.3f} between {LIFT_WEAK} and {LIFT_PREDICTIVE}"
        else:
            verdict = "noise"
            reason  = f"lift variance {lift_variance:.3f} ≤ {LIFT_WEAK}"

    return {
        "baseline_hit_rate": baseline_rate,
        "baseline_n": baseline_n,
        "by_value": by_value,
        "verdict": verdict,
        "verdict_reason": reason,
    }


def tier_calibration(df: pd.DataFrame) -> dict:
    """
    For each stat × tier, compute actual hit rate across all instances
    where that tier was selected as the best tier.
    """
    result = {}
    for stat, col in STAT_COL.items():
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"
        stat_result = {}
        for tier in sorted(TIERS[stat]):
            subset = df[(df[best_col] == float(tier)) & df[hit_col].notna()]
            n = len(subset)
            if n < 5:
                continue
            hit_rate = round(float(subset[hit_col].sum()) / n, 4)
            entry = {"n": n, "hit_rate": hit_rate}
            if hit_rate < CALIBRATION_CONCERN:
                entry["flag"] = "threshold_concern"
            stat_result[str(tier)] = entry
        result[stat] = stat_result
    return result


def top_signal_combinations(
    df: pd.DataFrame,
    signal_results: dict,
) -> dict:
    """
    For the top 2 most predictive signals per stat (by lift variance),
    compute cross-tabulation hit rates.
    """
    result = {}

    for stat in STAT_COL:
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"

        # Find top 2 signals by lift variance
        stat_signals = signal_results.get(stat, {})
        lift_variances = {}
        for sig_name, sig_data in stat_signals.items():
            lifts = [v.get("lift") for v in sig_data.get("by_value", {}).values()
                     if v.get("lift") is not None]
            if len(lifts) >= 2:
                lift_variances[sig_name] = max(lifts) - min(lifts)

        if len(lift_variances) < 2:
            result[stat] = {}
            continue

        top2 = sorted(lift_variances, key=lift_variances.get, reverse=True)[:2]
        sig1_name, sig2_name = top2
        sig1_col = SIGNALS[sig1_name][stat]
        sig2_col = SIGNALS[sig2_name][stat]

        qualified = df[
            df[best_col].notna() &
            df[hit_col].notna() &
            df[sig1_col].astype(str).ne("null") & df[sig1_col].notna() &
            df[sig2_col].astype(str).ne("null") & df[sig2_col].notna()
        ].copy()

        combo_result = {}
        if not qualified.empty:
            grp = qualified.groupby([sig1_col, sig2_col])
            for (v1, v2), sub in grp:
                n    = len(sub)
                hits = int(sub[hit_col].sum())
                if n >= MIN_SIGNAL_N:
                    combo_result[f"{sig1_name}={v1} & {sig2_name}={v2}"] = {
                        "n": n, "hits": hits, "hit_rate": round(hits / n, 4)
                    }

        result[stat] = {
            "signal_1": sig1_name,
            "signal_2": sig2_name,
            "combinations": combo_result,
        }

    return result


def build_recommendations(
    signal_results: dict,
    calibration: dict,
) -> list[str]:
    recs = []

    for stat in STAT_COL:
        for sig_name, sig_data in signal_results.get(stat, {}).items():
            verdict = sig_data.get("verdict")
            reason  = sig_data.get("verdict_reason", "")
            if verdict == "predictive":
                recs.append(
                    f"{stat} {sig_name}: PREDICTIVE ({reason}) — weight heavily in prompt"
                )
            elif verdict == "noise":
                recs.append(
                    f"{stat} {sig_name}: NOISE ({reason}) — consider removing or de-emphasizing"
                )

    for stat, tiers in calibration.items():
        for tier_str, entry in tiers.items():
            if entry.get("flag") == "threshold_concern":
                recs.append(
                    f"{stat} Tier {tier_str}: calibration hit rate {entry['hit_rate']*100:.1f}% "
                    f"(n={entry['n']}) is below the {CONFIDENCE_FLOOR*100:.0f}% floor — "
                    f"consider raising threshold or reviewing tier selection logic"
                )

    # Selection bias note
    recs.append(
        "NOTE: Selection bias — instances are filtered to players with ≥70% hit rate in prior "
        "10 games. This over-selects recent hot streaks; forward-looking calibration rates will "
        "naturally be lower than the 70% selection threshold (regression to the mean)."
    )

    return recs


# ── Bounce-Back Analysis ──────────────────────────────────────────────

BOUNCE_BACK_MIN_PAIRS   = 15   # min n for streak / severity cells
BOUNCE_BACK_MIN_VERDICT = 30   # min n_post_hit and n_post_miss for A1 verdict


def build_bounce_back_pairs(player_log: pd.DataFrame, stat: str, window: int) -> pd.DataFrame:
    """
    Build consecutive-game pairs for a single stat.

    For each player, sort non-DNP games chronologically and pair each
    game N with game N+1. Only retain pairs where:
      - Both games have an established tier (rolling HR ≥ 0.70 over prior `window` games)
      - The established tier is the same in both games (tier stability)

    Returns one row per valid pair with hit/miss labels, miss_gap, hit_margin,
    and streak state (streak_0 through streak_3plus) for game N+1.
    """
    col   = STAT_COL[stat]
    tiers = sorted(TIERS[stat], reverse=True)   # highest first

    df = player_log[["player_name", "game_date", col]].copy()
    df = df.sort_values(["player_name", "game_date"]).reset_index(drop=True)

    # Skip players with < 15 total games in the log
    game_counts = df.groupby("player_name")[col].transform("count")
    df = df[game_counts >= 15].copy()
    if df.empty:
        return pd.DataFrame()

    # Rolling hit rates per tier (shift=1 to exclude current game — no lookahead)
    for tier in tiers:
        df[f"_hit_{tier}"] = (df[col] >= tier).astype(float)
        df[f"_hr_{tier}"]  = df.groupby("player_name")[f"_hit_{tier}"].transform(
            lambda x: x.shift(1).rolling(window, min_periods=window).mean()
        )

    # Established tier: highest tier with rolling HR ≥ CONFIDENCE_FLOOR
    df["established_tier"] = np.nan
    for tier in tiers:
        qualifies   = df[f"_hr_{tier}"] >= CONFIDENCE_FLOOR
        no_tier_yet = df["established_tier"].isna()
        df.loc[qualifies & no_tier_yet, "established_tier"] = float(tier)

    # Is-hit indicator at the established tier
    df["is_hit"] = np.nan
    has_tier = df["established_tier"].notna()
    df.loc[has_tier, "is_hit"] = (
        df.loc[has_tier, col] >= df.loc[has_tier, "established_tier"]
    ).astype(float)

    # Shift within each player's sequence to build "prior game" columns
    grp = df.groupby("player_name")
    df["prior_tier"]     = grp["established_tier"].shift(1)
    df["prior_is_hit"]   = grp["is_hit"].shift(1)
    df["prior_actual"]   = grp[col].shift(1)
    df["prior_is_hit_2"] = grp["is_hit"].shift(2)   # N-1 (for streak)
    df["prior_is_hit_3"] = grp["is_hit"].shift(3)   # N-2 (for streak)

    # Valid pairs: both games have established tier AND same tier
    valid = df[
        df["established_tier"].notna() &
        df["prior_tier"].notna() &
        df["is_hit"].notna() &
        df["prior_is_hit"].notna() &
        (df["established_tier"] == df["prior_tier"])
    ].copy()

    if valid.empty:
        return pd.DataFrame()

    # miss_gap = tier - prior_actual  (when prior was a MISS; miss_gap=0 → near-miss bucket)
    valid["miss_gap"] = np.where(
        valid["prior_is_hit"] == 0.0,
        valid["prior_tier"] - valid["prior_actual"],
        np.nan,
    )
    # hit_margin = prior_actual - tier  (when prior was a HIT)
    valid["hit_margin"] = np.where(
        valid["prior_is_hit"] == 1.0,
        valid["prior_actual"] - valid["prior_tier"],
        np.nan,
    )

    # Streak state at game N+1, based on outcomes of games N, N-1, N-2
    cond_s0   = (valid["prior_is_hit"] == 1.0)
    cond_s1   = (valid["prior_is_hit"] == 0.0) & (
                    (valid["prior_is_hit_2"] != 0.0) | valid["prior_is_hit_2"].isna()
                )
    cond_s2   = (valid["prior_is_hit"] == 0.0) & (valid["prior_is_hit_2"] == 0.0) & (
                    (valid["prior_is_hit_3"] != 0.0) | valid["prior_is_hit_3"].isna()
                )
    cond_s3p  = (valid["prior_is_hit"] == 0.0) & (valid["prior_is_hit_2"] == 0.0) & (
                    valid["prior_is_hit_3"] == 0.0
                )
    valid["streak_state"] = np.select(
        [cond_s0, cond_s1, cond_s2, cond_s3p],
        ["streak_0", "streak_1", "streak_2", "streak_3plus"],
        default="unknown",
    )

    valid["stat"]        = stat
    valid["next_actual"] = valid[col]

    keep = [
        "player_name", "stat", "game_date", "established_tier",
        "next_actual", "is_hit",
        "prior_actual", "prior_is_hit", "miss_gap", "hit_margin",
        "streak_state",
    ]
    # Cleanup temp columns
    drop = [c for c in valid.columns if c.startswith("_")]
    valid = valid.drop(columns=drop)
    return valid[[c for c in keep if c in valid.columns]].copy()


# ── Analysis 1 — Simple Bounce-Back ──────────────────────────────────

def _verdict_a1(bb_lift: float, hh_lift: float, n_miss: int, n_hit: int) -> str:
    if n_miss < BOUNCE_BACK_MIN_VERDICT or n_hit < BOUNCE_BACK_MIN_VERDICT:
        return "insufficient-sample"
    if bb_lift > 1.10 and hh_lift > 1.10:
        return "both"
    if bb_lift > 1.10:
        return "bounce-back"
    if hh_lift > 1.10 and bb_lift < 1.05:
        return "hot-hand"
    if bb_lift < 0.90:
        return "slump-persistent"
    return "independent"


def _stat_a1(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    baseline = round(float(df["is_hit"].mean()), 4)
    ph_df    = df[df["prior_is_hit"] == 1.0]
    pm_df    = df[df["prior_is_hit"] == 0.0]
    n_hit    = len(ph_df)
    n_miss   = len(pm_df)
    ph_rate  = round(float(ph_df["is_hit"].mean()), 4) if n_hit  > 0 else None
    pm_rate  = round(float(pm_df["is_hit"].mean()), 4) if n_miss > 0 else None
    bb_lift  = round(pm_rate / baseline, 4) if (pm_rate is not None and baseline > 0) else None
    hh_lift  = round(ph_rate / baseline, 4) if (ph_rate is not None and baseline > 0) else None
    return {
        "baseline_hit_rate":  baseline,
        "post_hit_hit_rate":  ph_rate,
        "post_miss_hit_rate": pm_rate,
        "bounce_back_lift":   bb_lift,
        "hot_hand_lift":      hh_lift,
        "n_post_hit":         n_hit,
        "n_post_miss":        n_miss,
        "verdict":            _verdict_a1(bb_lift or 0, hh_lift or 0, n_miss, n_hit),
    }


def bounce_back_analysis_1(pairs: pd.DataFrame) -> dict:
    by_stat = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        sub = pairs[pairs["stat"] == stat]
        if not sub.empty:
            by_stat[stat] = _stat_a1(sub)
    return {
        "all_stats": _stat_a1(pairs),
        "by_stat":   by_stat,
    }


# ── Analysis 2 — Miss Severity ────────────────────────────────────────

def _miss_bucket(gap: float) -> str:
    # miss_gap > 0 always (hit = actual >= tier, so misses are strictly below tier)
    if gap <= 2.0:
        return "near_miss"
    if gap <= 5.0:
        return "moderate_miss"
    return "bad_miss"


def _hit_bucket(margin: float) -> str:
    if margin <= 2.0:
        return "narrow_hit"
    if margin <= 5.0:
        return "moderate_hit"
    return "strong_hit"


def _severity_verdict(rates: dict, ns: dict) -> str:
    near = rates.get("near_miss", 0)
    mod  = rates.get("moderate_miss", 0)
    bad  = rates.get("bad_miss", 0)
    if any(ns.get(k, 0) < 20 for k in ("near_miss", "moderate_miss", "bad_miss")):
        return "insufficient-sample"
    if bad > mod > near and bad - near > 0.08:
        return "stronger reversion with larger miss"
    if near > bad and near - bad > 0.08:
        return "inverted"
    if abs(bad - near) <= 0.05:
        return "flat"
    return "flat"


def bounce_back_analysis_2(pairs: pd.DataFrame) -> dict:
    by_stat = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        sub = pairs[pairs["stat"] == stat]
        if sub.empty:
            continue

        # Miss severity buckets
        miss_df = sub[sub["prior_is_hit"] == 0.0].copy()
        miss_df["bucket"] = miss_df["miss_gap"].apply(
            lambda g: _miss_bucket(g) if pd.notna(g) else None
        )
        miss_buckets, miss_rates, miss_ns = {}, {}, {}
        for bn in ("near_miss", "moderate_miss", "bad_miss"):
            bdf = miss_df[miss_df["bucket"] == bn]
            n   = len(bdf)
            hr  = round(float(bdf["is_hit"].mean()), 4) if n > 0 else None
            miss_buckets[bn] = {
                "n": n,
                "post_miss_hit_rate": hr,
                "avg_gap": round(float(bdf["miss_gap"].mean()), 2) if n > 0 else None,
                "flag": "insufficient_sample" if n < 20 else None,
            }
            miss_rates[bn] = hr or 0
            miss_ns[bn]    = n

        # Hit margin buckets
        hit_df = sub[sub["prior_is_hit"] == 1.0].copy()
        hit_df["bucket"] = hit_df["hit_margin"].apply(
            lambda m: _hit_bucket(m) if pd.notna(m) else None
        )
        hit_buckets = {}
        for bn in ("narrow_hit", "moderate_hit", "strong_hit"):
            bdf = hit_df[hit_df["bucket"] == bn]
            n   = len(bdf)
            hit_buckets[bn] = {
                "n": n,
                "next_hit_rate": round(float(bdf["is_hit"].mean()), 4) if n > 0 else None,
                "avg_margin":    round(float(bdf["hit_margin"].mean()), 2) if n > 0 else None,
                "flag": "insufficient_sample" if n < 20 else None,
            }

        by_stat[stat] = {
            "miss_buckets":             miss_buckets,
            "hit_buckets":              hit_buckets,
            "severity_gradient_verdict": _severity_verdict(miss_rates, miss_ns),
        }
    return {"by_stat": by_stat}


# ── Analysis 3 — Streak Analysis ─────────────────────────────────────

def _streak_verdict(s1: float, s2: float, s3p: float, n_s2: int, n_s3p: int) -> str:
    if n_s2 < 15 or n_s3p < 15:
        return "insufficient-sample"
    max_streak = max(s2, s3p)
    min_streak = min(s2, s3p)
    if max_streak > s1 + 0.08:
        return "reversion strengthens"
    if min_streak < s1 - 0.08:
        return "slump persists"
    return "independent"


def bounce_back_analysis_3(pairs: pd.DataFrame) -> dict:
    by_stat = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        sub = pairs[pairs["stat"] == stat]
        if sub.empty:
            continue

        stat_result = {}
        s1_rate = s2_rate = s3p_rate = 0.0
        n_s2 = n_s3p = 0

        for state in ("streak_0", "streak_1", "streak_2", "streak_3plus"):
            sdf = sub[sub["streak_state"] == state]
            n   = len(sdf)
            hr  = round(float(sdf["is_hit"].mean()), 4) if n > 0 else None
            entry: dict = {"n": n, "next_hit_rate": hr}

            if state in ("streak_1", "streak_2", "streak_3plus") and n > 0:
                avg_gap = round(float(sdf["miss_gap"].mean()), 2) if sdf["miss_gap"].notna().any() else None
                entry["avg_miss_gap"] = avg_gap

            if state in ("streak_2", "streak_3plus"):
                entry["flag"] = "insufficient_sample" if n < 15 else None

            if state == "streak_1":
                s1_rate = hr or 0.0
            elif state == "streak_2":
                s2_rate = hr or 0.0
                n_s2    = n
            elif state == "streak_3plus":
                s3p_rate = hr or 0.0
                n_s3p    = n

            stat_result[state] = entry

        stat_result["streak_verdict"] = _streak_verdict(s1_rate, s2_rate, s3p_rate, n_s2, n_s3p)
        by_stat[stat] = stat_result

    return {"by_stat": by_stat}


# ── Bounce-Back Recommendations ───────────────────────────────────────

def bounce_back_recommendations(a1: dict, a2: dict, a3: dict) -> tuple:
    recs    = []
    implies = []

    # Analysis 1 — per stat
    for stat, d in a1.get("by_stat", {}).items():
        verdict  = d.get("verdict", "")
        bb_lift  = d.get("bounce_back_lift") or 0
        hh_lift  = d.get("hot_hand_lift") or 0
        baseline = d.get("baseline_hit_rate") or 0
        pm_rate  = d.get("post_miss_hit_rate") or 0
        ph_rate  = d.get("post_hit_hit_rate") or 0
        n_miss   = d.get("n_post_miss", 0)
        n_hit    = d.get("n_post_hit", 0)

        if verdict == "bounce-back":
            recs.append(
                f"{stat}: Post-miss hit rate {pm_rate*100:.1f}% vs baseline {baseline*100:.1f}% "
                f"(lift={bb_lift:.3f}, n={n_miss}) — bounce-back signal confirmed"
            )
            implies.append(
                f"{stat}: Add prompt instruction — 'If player missed their established "
                f"{stat} tier last game, apply +3–5% confidence boost (bounce-back lift="
                f"{bb_lift:.2f} confirmed over {n_miss} instances)'"
            )
        elif verdict == "hot-hand":
            recs.append(
                f"{stat}: Hot-hand effect confirmed — post-hit rate {ph_rate*100:.1f}% "
                f"vs baseline {baseline*100:.1f}% (lift={hh_lift:.3f}, n={n_hit})"
            )
            implies.append(
                f"{stat}: Post-hit momentum — player who hit {stat} tier last game has "
                f"elevated hit rate next game (lift={hh_lift:.2f}); factor into confidence"
            )
        elif verdict == "slump-persistent":
            recs.append(
                f"{stat}: Slumps are persistent — post-miss hit rate {pm_rate*100:.1f}% "
                f"BELOW baseline {baseline*100:.1f}% (lift={bb_lift:.3f}, n={n_miss}). "
                f"Avoid post-miss {stat} picks."
            )
            implies.append(
                f"{stat}: Add prompt instruction — 'If player missed {stat} last game, "
                f"apply -5% confidence or prefer a lower tier (slump-persistent, lift="
                f"{bb_lift:.2f} over {n_miss} instances)'"
            )
        elif verdict == "both":
            recs.append(
                f"{stat}: Sequential dependency in both directions — post-hit lift={hh_lift:.3f} "
                f"(n={n_hit}), post-miss lift={bb_lift:.3f} (n={n_miss})"
            )

    # Analysis 1 — all-stats combined
    all_d = a1.get("all_stats", {})
    av    = all_d.get("verdict", "")
    if av not in ("insufficient-sample", "independent", ""):
        recs.append(
            f"Overall ({av}): post-miss lift={all_d.get('bounce_back_lift',0):.3f} "
            f"(n={all_d.get('n_post_miss',0)}), "
            f"post-hit lift={all_d.get('hot_hand_lift',0):.3f} "
            f"(n={all_d.get('n_post_hit',0)})"
        )

    # Analysis 2 — severity gradient
    for stat, d in a2.get("by_stat", {}).items():
        sv = d.get("severity_gradient_verdict", "")
        if sv == "stronger reversion with larger miss":
            bad  = d.get("miss_buckets", {}).get("bad_miss", {})
            near = d.get("miss_buckets", {}).get("near_miss", {})
            recs.append(
                f"{stat} severity: bad misses (gap>5) show stronger bounce-back — "
                f"bad {(bad.get('post_miss_hit_rate') or 0)*100:.1f}% (n={bad.get('n',0)}) "
                f"vs near-miss {(near.get('post_miss_hit_rate') or 0)*100:.1f}% (n={near.get('n',0)})"
            )
            implies.append(
                f"{stat}: Use miss severity in reasoning — a player who badly missed "
                f"(>5 units below tier) deserves higher bounce-back confidence than a near-miss"
            )

    # Analysis 3 — streak verdicts
    for stat, d in a3.get("by_stat", {}).items():
        sv = d.get("streak_verdict", "")
        if sv == "reversion strengthens":
            s2 = d.get("streak_2", {})
            recs.append(
                f"{stat} streak: 2-game miss streak shows STRONGER reversion — "
                f"hit rate {(s2.get('next_hit_rate') or 0)*100:.1f}% (n={s2.get('n',0)}) "
                f"after 2 consecutive misses"
            )
            implies.append(
                f"{stat}: '2-game miss streak → extra bounce-back confidence' — add to prompt"
            )
        elif sv == "slump persists":
            recs.append(
                f"{stat} streak: multi-game miss streaks are PERSISTENT — "
                f"avoid players on 2+ consecutive {stat} misses"
            )

    if not recs:
        recs.append(
            "All signals are independent — prior game outcome does not predict next game "
            "at currently measurable confidence levels across any stat."
        )
    if not implies:
        implies.append(
            "No prompt changes warranted — no confirmed sequential dependencies detected."
        )

    return recs, implies


# ── Bounce-Back Stdout Report ─────────────────────────────────────────

def print_bounce_back_report(a1: dict, a2: dict, a3: dict, meta: dict, recs: list, implies: list):
    sep = "─" * 54
    d   = meta["date_range"]
    print(f"\n{'═'*54}")
    print(f"BOUNCE-BACK BACKTEST — {d['start']} to {d['end']}")
    print(f"Rolling window: {meta['rolling_window']} games | "
          f"Total pairs: {meta['total_consecutive_pairs']:,}")
    print(f"{'═'*54}")

    # Analysis 1
    all_d    = a1.get("all_stats", {})
    baseline = all_d.get("baseline_hit_rate") or 0
    ph_rate  = all_d.get("post_hit_hit_rate") or 0
    pm_rate  = all_d.get("post_miss_hit_rate") or 0
    hh_lift  = all_d.get("hot_hand_lift") or 0
    bb_lift  = all_d.get("bounce_back_lift") or 0
    n_hit    = all_d.get("n_post_hit", 0)
    n_miss   = all_d.get("n_post_miss", 0)
    verdict  = all_d.get("verdict", "?")

    print(f"\nANALYSIS 1 — Simple Bounce-Back (all stats combined)")
    print(f"  Baseline hit rate:    {baseline*100:.1f}%  (n={n_hit+n_miss:,})")
    print(f"  Post-HIT hit rate:    {ph_rate*100:.1f}%  (n={n_hit:,})  "
          f"lift: {hh_lift:.3f}  [{verdict}]")
    print(f"  Post-MISS hit rate:   {pm_rate*100:.1f}%  (n={n_miss:,})  "
          f"lift: {bb_lift:.3f}  [{verdict}]")
    print(f"\n  By stat:")
    hdr = f"  {'Stat':<5} {'Baseline':>9} {'Post-HIT':>9} {'Lift':>6} {'Post-MISS':>10} {'Lift':>6}  Verdict"
    print(hdr)
    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = a1.get("by_stat", {}).get(stat)
        if not sd:
            continue
        b  = sd.get("baseline_hit_rate") or 0
        ph = sd.get("post_hit_hit_rate") or 0
        pm = sd.get("post_miss_hit_rate") or 0
        hl = sd.get("hot_hand_lift") or 0
        bl = sd.get("bounce_back_lift") or 0
        v  = sd.get("verdict", "?")
        print(f"  {stat:<5} {b*100:>8.1f}%  {ph*100:>8.1f}%  {hl:>5.2f}"
              f"  {pm*100:>9.1f}%  {bl:>5.2f}  [{v}]")

    # Analysis 2
    print(f"\n{sep}")
    print("ANALYSIS 2 — Miss Severity (post-miss next-game hit rate)")
    print()
    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = a2.get("by_stat", {}).get(stat)
        if not sd:
            continue
        mb  = sd.get("miss_buckets", {})
        nm  = mb.get("near_miss", {})
        mo  = mb.get("moderate_miss", {})
        bd  = mb.get("bad_miss", {})
        nmr = (nm.get("post_miss_hit_rate") or 0) * 100
        mor = (mo.get("post_miss_hit_rate") or 0) * 100
        bdr = (bd.get("post_miss_hit_rate") or 0) * 100
        v   = sd.get("severity_gradient_verdict", "?")
        print(f"  {stat}:  near-miss {nmr:.1f}% (n={nm.get('n',0)}) | "
              f"moderate {mor:.1f}% (n={mo.get('n',0)}) | "
              f"bad {bdr:.1f}% (n={bd.get('n',0)}) → [{v}]")

    # Analysis 3
    print(f"\n{sep}")
    print("ANALYSIS 3 — Streak Analysis (next-game hit rate by streak state)")
    print()
    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = a3.get("by_stat", {}).get(stat)
        if not sd:
            continue
        s0  = sd.get("streak_0",    {})
        s1  = sd.get("streak_1",    {})
        s2  = sd.get("streak_2",    {})
        s3p = sd.get("streak_3plus",{})
        r0  = (s0.get("next_hit_rate")  or 0) * 100
        r1  = (s1.get("next_hit_rate")  or 0) * 100
        r2  = (s2.get("next_hit_rate")  or 0) * 100
        r3p = (s3p.get("next_hit_rate") or 0) * 100
        f2  = "* " if (s2.get("n",  0) < 15) else ""
        f3  = "* " if (s3p.get("n", 0) < 15) else ""
        v   = sd.get("streak_verdict", "?")
        print(f"  {stat}:  0-miss {r0:.1f}%(n={s0.get('n',0)}) | "
              f"1-miss {r1:.1f}%(n={s1.get('n',0)}) | "
              f"2-miss {f2}{r2:.1f}%(n={s2.get('n',0)}) | "
              f"3+ {f3}{r3p:.1f}%(n={s3p.get('n',0)}) → [{v}]")
    print("  (* = n < 15, insufficient sample)")

    print(f"\n{sep}")
    print("RECOMMENDATIONS")
    for r in recs:
        print(f"  → {r}")
    print(f"\nPROMPT IMPLICATIONS (if signals confirmed)")
    for i in implies:
        print(f"  → {i}")
    print(f"{'═'*54}\n")


# ── Bounce-Back Entry Point ───────────────────────────────────────────

def run_bounce_back_analysis(player_log: pd.DataFrame, args) -> None:
    window      = args.window if args.window else ROLLING_WINDOW
    stat_filter = getattr(args, "stat", None)
    stats_to_run = [stat_filter] if stat_filter else list(STAT_COL.keys())

    print(f"[backtest] Bounce-back mode | window={window} | stats={stats_to_run}")

    all_pairs = []
    for stat in stats_to_run:
        stat_pairs = build_bounce_back_pairs(player_log, stat, window)
        if not stat_pairs.empty:
            all_pairs.append(stat_pairs)
            print(f"[backtest] {stat}: {len(stat_pairs):,} valid consecutive pairs")
        else:
            print(f"[backtest] {stat}: no valid pairs")

    if not all_pairs:
        print("[backtest] No valid pairs built — cannot run bounce-back analysis.")
        sys.exit(0)

    pairs = pd.concat(all_pairs, ignore_index=True)
    print(f"[backtest] Total pairs: {len(pairs):,}")

    print("[backtest] Running Analysis 1 (simple bounce-back)...")
    a1 = bounce_back_analysis_1(pairs)

    print("[backtest] Running Analysis 2 (miss severity)...")
    a2 = bounce_back_analysis_2(pairs)

    print("[backtest] Running Analysis 3 (streak analysis)...")
    a3 = bounce_back_analysis_3(pairs)

    recs, implies = bounce_back_recommendations(a1, a2, a3)

    date_min = pairs["game_date"].min()
    date_max = pairs["game_date"].max()
    date_min = date_min.strftime("%Y-%m-%d") if hasattr(date_min, "strftime") else str(date_min)
    date_max = date_max.strftime("%Y-%m-%d") if hasattr(date_max, "strftime") else str(date_max)

    meta = {
        "generated_at":            dt.date.today().isoformat(),
        "mode":                    "bounce-back",
        "rolling_window":          window,
        "date_range":              {"start": date_min, "end": date_max},
        "total_consecutive_pairs": int(len(pairs)),
        "pairs_by_stat":           {s: int((pairs["stat"] == s).sum()) for s in STAT_COL},
    }

    output = {
        **meta,
        "analysis_1_simple_bounce_back": a1,
        "analysis_2_miss_severity":      a2,
        "analysis_3_streak":             a3,
        "recommendations":               recs,
        "prompt_implications":           implies,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else BOUNCE_BACK_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] Results written → {out_path}")

    print_bounce_back_report(a1, a2, a3, meta, recs, implies)


# ── Mean Reversion Analysis ───────────────────────────────────────────

# Config (mirrors spec)
MR_BASELINE_WINDOW  = 20   # L20 window for established tier and raw avg baseline
MR_SHORT_WINDOW     = 5    # L5 window for "current form" assessment
MR_MIN_PRIOR_GAMES  = 20   # minimum games before a player enters analysis
MR_MIN_SAMPLE       = 15   # minimum n for Analysis 2/3 cells to report (else flag)
MR_A1_MIN_VERDICT   = 15   # minimum n per cold streak category for A1 verdict


def _cold_streak_category(raw_drop: pd.Series, tier_drop: pd.Series) -> pd.Series:
    """
    Vectorized cold streak classification. Inputs are pandas Series.

    raw_drop   = (L20_raw_avg - L5_raw_avg) / L20_raw_avg  (NaN-safe, filled to 0 before call)
    tier_drop  = L20_tier_hit_rate - L5_tier_hit_rate       (NaN-safe, filled to 0 before call)

    Classification uses the MORE SEVERE of the two dimensions (OR logic), with severity
    checked in descending order so each row falls into exactly one bucket.
    Hot-streak rows (both drops < 0) naturally fall into "baseline".
    """
    severe   = (raw_drop > 0.30) | (tier_drop > 0.40)
    moderate = (
        ((raw_drop >= 0.15) & (raw_drop <= 0.30)) |
        ((tier_drop >= 0.20) & (tier_drop <= 0.40))
    ) & ~severe
    mild = (
        ((raw_drop >= 0.05) & (raw_drop <= 0.15)) |
        ((tier_drop >= 0.10) & (tier_drop <= 0.20))
    ) & ~severe & ~moderate
    baseline = (raw_drop < 0.05) & (tier_drop < 0.10)

    return pd.Series(
        np.select(
            [severe, moderate, mild, baseline],
            ["severe_cold", "moderate_cold", "mild_cold", "baseline"],
            default="baseline",   # hot streaks (negative drops) → baseline
        ),
        index=raw_drop.index,
    )


def build_mean_reversion_instances(
    player_log: pd.DataFrame,
    stat: str,
    baseline_window: int = MR_BASELINE_WINDOW,
    short_window: int = MR_SHORT_WINDOW,
) -> pd.DataFrame:
    """
    Build one row per qualified target game (game N+1) for a single stat.

    Columns produced:
      player_name, game_date, stat, team_abbrev, opp_abbrev,
      established_tier, l20_raw_avg, l5_raw_avg, l20_hr, l5_hr,
      raw_avg_drop, tier_rate_drop, cold_streak_cat,
      is_hit,               # actual >= established_tier at target game
      future_actual_1,      # stat value 1 game after target (N+2 measurement)
      future_actual_2       # stat value 2 games after target (N+3 measurement)
    """
    col   = STAT_COL[stat]
    tiers = sorted(TIERS[stat], reverse=True)   # highest first

    df = player_log[
        ["player_name", "game_date", "team_abbrev", "opp_abbrev", col]
    ].copy()
    df = df.sort_values(["player_name", "game_date"]).reset_index(drop=True)

    # Quick pre-filter: skip players with fewer than baseline_window + 1 total games
    game_counts = df.groupby("player_name")[col].transform("count")
    df = df[game_counts >= baseline_window + 1].copy()
    if df.empty:
        return pd.DataFrame()

    # ── L20 and L5 raw averages (shift=1: no lookahead) ───────────────
    df["l20_raw_avg"] = df.groupby("player_name")[col].transform(
        lambda x: x.shift(1).rolling(baseline_window, min_periods=baseline_window).mean()
    )
    df["l5_raw_avg"] = df.groupby("player_name")[col].transform(
        lambda x: x.shift(1).rolling(short_window, min_periods=short_window).mean()
    )

    # ── Per-tier rolling hit rates (L20 and L5, shift=1) ─────────────
    for tier in tiers:
        hit_col = f"_hit_{tier}"
        df[hit_col] = (df[col] >= tier).astype(float)
        df[f"_l20_hr_{tier}"] = df.groupby("player_name")[hit_col].transform(
            lambda x: x.shift(1).rolling(baseline_window, min_periods=baseline_window).mean()
        )
        df[f"_l5_hr_{tier}"] = df.groupby("player_name")[hit_col].transform(
            lambda x: x.shift(1).rolling(short_window, min_periods=short_window).mean()
        )

    # ── Established tier: highest tier with L20 HR >= CONFIDENCE_FLOOR ─
    df["established_tier"] = np.nan
    for tier in tiers:
        qualifies   = df[f"_l20_hr_{tier}"] >= CONFIDENCE_FLOOR
        no_tier_yet = df["established_tier"].isna()
        df.loc[qualifies & no_tier_yet, "established_tier"] = float(tier)

    # ── L20 and L5 HR at the established tier (per-row lookup) ────────
    df["l20_hr"] = np.nan
    df["l5_hr"]  = np.nan
    for tier in tiers:
        mask = df["established_tier"] == float(tier)
        df.loc[mask, "l20_hr"] = df.loc[mask, f"_l20_hr_{tier}"]
        df.loc[mask, "l5_hr"]  = df.loc[mask, f"_l5_hr_{tier}"]

    # ── Cold streak metrics ────────────────────────────────────────────
    # raw_avg_drop: protect against division by zero when L20 avg = 0
    df["raw_avg_drop"]  = (df["l20_raw_avg"] - df["l5_raw_avg"]) / \
                           df["l20_raw_avg"].replace(0, np.nan)
    df["tier_rate_drop"] = df["l20_hr"] - df["l5_hr"]

    # Classify (fillna(0) so NaN drops → baseline, not an error)
    df["cold_streak_cat"] = _cold_streak_category(
        df["raw_avg_drop"].fillna(0),
        df["tier_rate_drop"].fillna(0),
    )

    # ── Is-hit at target game: actual >= established_tier ─────────────
    df["is_hit"] = np.nan
    has_tier = df["established_tier"].notna()
    df.loc[has_tier, "is_hit"] = (
        df.loc[has_tier, col] >= df.loc[has_tier, "established_tier"]
    ).astype(float)

    # ── Forward shifts for Analysis 2 (N+2 and N+3) ──────────────────
    # shift(-1) = 1 game after target (N+2), shift(-2) = 2 games after (N+3)
    # DNPs are already excluded from player_log, so shifts skip them correctly.
    df["future_actual_1"] = df.groupby("player_name")[col].shift(-1)
    df["future_actual_2"] = df.groupby("player_name")[col].shift(-2)

    # ── Filter to qualified instances ─────────────────────────────────
    qualified = df[
        df["established_tier"].notna() &
        df["l20_raw_avg"].notna() &
        df["l5_raw_avg"].notna() &
        df["is_hit"].notna()
    ].copy()

    # Drop temp columns
    drop_cols = [c for c in qualified.columns if c.startswith("_")]
    qualified = qualified.drop(columns=drop_cols)
    qualified["stat"] = stat

    keep = [
        "player_name", "stat", "game_date", "team_abbrev", "opp_abbrev",
        "established_tier", "l20_raw_avg", "l5_raw_avg", "l20_hr", "l5_hr",
        "raw_avg_drop", "tier_rate_drop", "cold_streak_cat",
        "is_hit", "future_actual_1", "future_actual_2",
    ]
    return qualified[[c for c in keep if c in qualified.columns]].copy()


# ── Mean Reversion — Analysis 1 ───────────────────────────────────────

def _mr_verdict_a1(cats: dict) -> str:
    """
    Derive verdict from per-category hit rates and lifts.

    cats keys: "baseline", "mild_cold", "moderate_cold", "severe_cold"
    Each value: {"n": int, "hit_rate": float|None, "lift": float|None}

    Verdict rules (in priority order):
      insufficient-sample  → any category with n < MR_A1_MIN_VERDICT
      reversion            → lift increases monotonically mild→mod→severe AND severe lift > 1.10
      decline              → hit rate decreases monotonically AND severe lift < 0.90
      mixed-threshold      → moderate shows reversion (lift > 1.0) but severe shows decline (lift < 0.90)
      independent          → all cold-streak lifts between 0.95 and 1.10
    """
    cold_cats = ["mild_cold", "moderate_cold", "severe_cold"]
    ns    = [cats.get(c, {}).get("n", 0)        for c in cold_cats]
    lifts = [cats.get(c, {}).get("lift")         for c in cold_cats]
    hrs   = [cats.get(c, {}).get("hit_rate")     for c in cold_cats]

    baseline_n = cats.get("baseline", {}).get("n", 0)
    if baseline_n < MR_A1_MIN_VERDICT:
        return "insufficient-sample"

    # Any cold-streak category with 0 instances → insufficient to judge
    if any(n == 0 for n in ns):
        return "insufficient-sample"

    # Work only with categories that have sufficient sample
    valid = [(l, h, n) for l, h, n in zip(lifts, hrs, ns)
             if l is not None and h is not None and n >= MR_A1_MIN_VERDICT]
    if len(valid) < 2:
        return "insufficient-sample"

    valid_lifts = [v[0] for v in valid]
    valid_hrs   = [v[1] for v in valid]

    sev_lift = cats.get("severe_cold", {}).get("lift")
    sev_n    = cats.get("severe_cold", {}).get("n", 0)
    mod_lift = cats.get("moderate_cold", {}).get("lift") or 0

    is_monotonic_up   = all(valid_lifts[i] <= valid_lifts[i+1]
                             for i in range(len(valid_lifts)-1))
    is_monotonic_down = all(valid_hrs[i]   >= valid_hrs[i+1]
                             for i in range(len(valid_hrs)-1))

    if sev_lift is not None and sev_n >= MR_A1_MIN_VERDICT:
        if is_monotonic_up and sev_lift > 1.10:
            return "reversion"
        if is_monotonic_down and sev_lift < 0.90:
            return "decline"
        if mod_lift > 1.0 and sev_lift < 0.90:
            return "mixed-threshold"

    if all(0.95 <= l <= 1.10 for l in valid_lifts):
        return "independent"

    return "independent"


def mean_reversion_analysis_1(instances: pd.DataFrame) -> dict:
    """
    Per stat: next-game hit rate by cold streak severity category.
    Returns per-stat dicts with n, hit_rate, lift (vs baseline), verdict.
    """
    by_stat = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        sub = instances[instances["stat"] == stat]
        if sub.empty:
            continue

        cat_order = ["baseline", "mild_cold", "moderate_cold", "severe_cold"]
        cats = {}

        # Baseline hit rate first (needed to compute lifts)
        baseline_df = sub[sub["cold_streak_cat"] == "baseline"]
        baseline_n  = len(baseline_df)
        baseline_hr = round(float(baseline_df["is_hit"].mean()), 4) if baseline_n > 0 else None
        cats["baseline"] = {"n": baseline_n, "hit_rate": baseline_hr}

        for cat in ("mild_cold", "moderate_cold", "severe_cold"):
            cat_df = sub[sub["cold_streak_cat"] == cat]
            n  = len(cat_df)
            hr = round(float(cat_df["is_hit"].mean()), 4) if n > 0 else None
            entry: dict = {"n": n, "hit_rate": hr}
            if hr is not None and baseline_hr and baseline_hr > 0:
                entry["lift"] = round(hr / baseline_hr, 4)
            else:
                entry["lift"] = None
            cats[cat] = entry

        verdict = _mr_verdict_a1(cats)
        cats["verdict"] = verdict

        # mixed_threshold: find first cold category with lift < 0.90
        mixed_threshold = None
        if verdict == "mixed-threshold":
            for cat in ("mild_cold", "moderate_cold", "severe_cold"):
                lift = cats.get(cat, {}).get("lift")
                if lift is not None and lift < 0.90:
                    mixed_threshold = cat
                    break
        cats["mixed_threshold"] = mixed_threshold

        by_stat[stat] = cats

    return by_stat


# ── Mean Reversion — Analysis 2 ───────────────────────────────────────

def mean_reversion_analysis_2(instances: pd.DataFrame) -> dict:
    """
    Reversion curve: for players classified in moderate/severe cold, measure
    hit rate at N+1 (already the target game), N+2, and N+3.

    Uses the established tier from the entry point throughout (no re-classification).
    N+2 and N+3 are computed from pre-built forward-shift columns future_actual_1/2.
    """
    by_stat = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        sub = instances[instances["stat"] == stat].copy()
        if sub.empty:
            continue

        # Forward-game hits at N+2 and N+3 using entry-point established tier
        sub["is_hit_n2"] = np.where(
            sub["future_actual_1"].notna(),
            (sub["future_actual_1"] >= sub["established_tier"]).astype(float),
            np.nan,
        )
        sub["is_hit_n3"] = np.where(
            sub["future_actual_2"].notna(),
            (sub["future_actual_2"] >= sub["established_tier"]).astype(float),
            np.nan,
        )

        baseline_df = sub[sub["cold_streak_cat"] == "baseline"]
        baseline_hr = float(baseline_df["is_hit"].mean()) if len(baseline_df) > 0 else None

        stat_result = {}
        for cold_cat in ("moderate_cold", "severe_cold"):
            cat_df = sub[sub["cold_streak_cat"] == cold_cat]
            n_n1   = int(cat_df["is_hit"].notna().sum())
            n_n2   = int(cat_df["is_hit_n2"].notna().sum())
            n_n3   = int(cat_df["is_hit_n3"].notna().sum())

            hr_n1 = round(float(cat_df["is_hit"].mean()), 4) if n_n1 > 0 else None
            hr_n2 = round(float(cat_df["is_hit_n2"].dropna().mean()), 4) if n_n2 >= MR_MIN_SAMPLE else None
            hr_n3 = round(float(cat_df["is_hit_n3"].dropna().mean()), 4) if n_n3 >= MR_MIN_SAMPLE else None

            stat_result[cold_cat] = {
                "baseline":  {"hit_rate": round(baseline_hr, 4) if baseline_hr is not None else None},
                "n_plus_1":  {"n": n_n1, "hit_rate": hr_n1},
                "n_plus_2":  {"n": n_n2, "hit_rate": hr_n2,
                               "flag": "insufficient_sample" if n_n2 < MR_MIN_SAMPLE else None},
                "n_plus_3":  {"n": n_n3, "hit_rate": hr_n3,
                               "flag": "insufficient_sample" if n_n3 < MR_MIN_SAMPLE else None},
            }

        by_stat[stat] = stat_result

    return by_stat


# ── Mean Reversion — Analysis 3 ───────────────────────────────────────

def mean_reversion_analysis_3(instances: pd.DataFrame, opp_lookup: dict) -> dict:
    """
    Cold streak × opponent defense interaction.
    Tests whether a favorable matchup accelerates reversion for cold-streak players.

    Requires opp_lookup from build_opp_defense_lookup(). Returns {} if lookup is empty.
    """
    if not opp_lookup:
        return {}

    df = instances.copy()
    df["_date_str"] = df["game_date"].dt.strftime("%Y-%m-%d")
    df["_opp_upper"] = df["opp_abbrev"].str.upper().str.strip()

    by_stat = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        sub = df[df["stat"] == stat].copy()
        if sub.empty:
            continue

        # Attach opp defense rating for each target game
        sub["opp_def"] = sub.apply(
            lambda r: opp_lookup.get((r["_opp_upper"], r["_date_str"], stat), "null"),
            axis=1,
        )

        stat_result = {}
        for cold_cat in ("moderate_cold", "severe_cold"):
            cat_df = sub[sub["cold_streak_cat"] == cold_cat]
            cat_result: dict = {}
            soft_hr = tough_hr = None

            for rating in ("soft", "mid", "tough"):
                rating_df = cat_df[cat_df["opp_def"] == rating]
                n  = int(len(rating_df))
                hr = round(float(rating_df["is_hit"].mean()), 4) if n >= MR_MIN_SAMPLE else None
                cat_result[rating] = {
                    "n": n,
                    "hit_rate": hr,
                    "flag": "insufficient_sample" if n < MR_MIN_SAMPLE else None,
                }
                if rating == "soft":
                    soft_hr = hr
                elif rating == "tough":
                    tough_hr = hr

            # matchup_matters: soft vs tough spread > 10pp, both cells sufficient
            if soft_hr is not None and tough_hr is not None:
                cat_result["matchup_matters"] = abs(soft_hr - tough_hr) > 0.10
            else:
                cat_result["matchup_matters"] = None   # insufficient data both sides

            stat_result[cold_cat] = cat_result

        by_stat[stat] = stat_result

    return by_stat


# ── Mean Reversion — Recommendations ──────────────────────────────────

def mean_reversion_recommendations(a1: dict, a2: dict, a3: dict) -> tuple:
    recs    = []
    implies = []

    for stat in ("PTS", "REB", "AST", "3PM"):
        sd      = a1.get(stat, {})
        verdict = sd.get("verdict", "")
        base_hr = sd.get("baseline", {}).get("hit_rate", 0) or 0
        sev     = sd.get("severe_cold", {})
        sev_hr  = sev.get("hit_rate", 0) or 0
        sev_n   = sev.get("n", 0)
        sev_l   = sev.get("lift", 0) or 0
        mod     = sd.get("moderate_cold", {})
        mod_hr  = mod.get("hit_rate", 0) or 0
        mod_n   = mod.get("n", 0)
        mod_l   = mod.get("lift", 0) or 0

        if verdict == "reversion":
            recs.append(
                f"{stat}: Mean reversion CONFIRMED — severe cold hit rate {sev_hr*100:.1f}% "
                f"vs baseline {base_hr*100:.1f}% (lift={sev_l:.3f}, n={sev_n})"
            )
            implies.append(
                f"{stat}: When L5 is materially below L20 (severe cold streak), apply +3–5% "
                f"confidence — mean reversion is predictive (lift={sev_l:.2f}, n={sev_n})"
            )
        elif verdict == "decline":
            recs.append(
                f"{stat}: Genuine decline signal — severe cold hit rate {sev_hr*100:.1f}% "
                f"BELOW baseline {base_hr*100:.1f}% (lift={sev_l:.3f}, n={sev_n}). "
                f"L5 underperformance persists."
            )
            implies.append(
                f"{stat}: Cold-streak players continue to underperform next game. "
                f"Avoid or down-tier players with severe cold streak (lift={sev_l:.2f})."
            )
        elif verdict == "mixed-threshold":
            threshold = sd.get("mixed_threshold", "severe")
            recs.append(
                f"{stat}: Mixed — moderate cold shows partial reversion "
                f"({mod_hr*100:.1f}%, lift={mod_l:.3f}, n={mod_n}) but "
                f"severe cold shows decline ({sev_hr*100:.1f}%, lift={sev_l:.3f}, n={sev_n}). "
                f"Decline threshold at: {threshold}"
            )
            implies.append(
                f"{stat}: Flag severe cold streak — reversion holds for moderate underperformance "
                f"only; severe cold indicates genuine decline. Avoid severe cold streak picks."
            )
        elif verdict == "insufficient-sample":
            recs.append(
                f"{stat}: Insufficient sample — mean reversion verdict inconclusive "
                f"(baseline n={sd.get('baseline', {}).get('n', 0)}, "
                f"severe n={sev_n})"
            )
        else:  # independent
            recs.append(
                f"{stat}: Cold streak state → independent. No hit-rate adjustment warranted "
                f"(baseline {base_hr*100:.1f}%, severe {sev_hr*100:.1f}%, "
                f"lift={sev_l:.3f}, n={sev_n})"
            )

    # Analysis 3 — matchup interaction
    matchup_signals = []
    for stat in ("PTS", "REB", "AST", "3PM"):
        for cold_cat in ("moderate_cold", "severe_cold"):
            cell = a3.get(stat, {}).get(cold_cat, {})
            if cell.get("matchup_matters") is True:
                soft_hr  = (cell.get("soft", {}).get("hit_rate") or 0) * 100
                tough_hr = (cell.get("tough", {}).get("hit_rate") or 0) * 100
                soft_n   = cell.get("soft", {}).get("n", 0)
                tough_n  = cell.get("tough", {}).get("n", 0)
                label    = "moderate" if cold_cat == "moderate_cold" else "severe"
                matchup_signals.append(
                    f"{stat} {label} cold: soft opp {soft_hr:.1f}%(n={soft_n}) "
                    f"vs tough opp {tough_hr:.1f}%(n={tough_n}) — "
                    f"matchup accelerates reversion (spread > 10pp)"
                )

    if matchup_signals:
        recs.extend(matchup_signals)
        implies.append(
            "For cold-streak players, prioritize soft matchups — matchup interaction "
            "confirmed for: " + "; ".join(matchup_signals[:2])
        )
    elif a3:  # a3 was built but no signals found
        recs.append(
            "Matchup interaction: soft/tough opponent does not reliably accelerate "
            "cold-streak reversion across any stat (spread ≤ 10pp in all cells)"
        )
    else:
        recs.append("Analysis 3 skipped — no team log available for opp defense lookup")

    if not implies:
        implies.append(
            "No prompt changes warranted from mean reversion analysis — "
            "cold streak state is not consistently predictive"
        )

    return recs, implies


# ── Mean Reversion — Stdout Report ────────────────────────────────────

def print_mean_reversion_report(
    a1: dict, a2: dict, a3: dict, meta: dict, recs: list, implies: list
):
    sep = "─" * 54
    d   = meta["date_range"]
    print(f"\n{'═'*54}")
    print(f"MEAN REVERSION BACKTEST — {d['start']} to {d['end']}")
    print(f"Rolling window: {meta['rolling_window']} games | "
          f"Short window: {meta['short_window']} games")
    print(f"Total instances: {meta['total_instances']:,}")
    print(f"{'═'*54}")

    # Analysis 1
    print(f"\nANALYSIS 1 — Next-Game Hit Rate by Cold Streak Severity\n")
    print(f"  {'Stat':<5} {'Baseline':>10}  {'Mild':>9}  {'Lift':>5}  "
          f"{'Moderate':>9}  {'Lift':>5}  {'Severe':>9}  {'Lift':>5}  Verdict")
    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = a1.get(stat, {})
        if not sd:
            continue
        b   = sd.get("baseline",      {})
        mil = sd.get("mild_cold",     {})
        mod = sd.get("moderate_cold", {})
        sev = sd.get("severe_cold",   {})
        def _hr(d):  return f"{(d.get('hit_rate') or 0)*100:.1f}%(n={d.get('n',0)})"
        def _l(d):   return f"{d.get('lift') or 0:.2f}" if d.get("lift") is not None else "----"
        v = sd.get("verdict", "?")
        print(f"  {stat:<5} {_hr(b):>12}  {_hr(mil):>12}  {_l(mil):>5}  "
              f"{_hr(mod):>12}  {_l(mod):>5}  {_hr(sev):>12}  {_l(sev):>5}  [{v}]")

    # Analysis 2
    print(f"\n{sep}")
    print("ANALYSIS 2 — Reversion Curve (moderate + severe cold only)\n")
    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = a2.get(stat, {})
        if not sd:
            continue
        for cold_cat in ("moderate_cold", "severe_cold"):
            cat_d = sd.get(cold_cat, {})
            if not cat_d:
                continue
            bl = cat_d.get("baseline", {}).get("hit_rate", 0) or 0
            n1 = cat_d.get("n_plus_1", {})
            n2 = cat_d.get("n_plus_2", {})
            n3 = cat_d.get("n_plus_3", {})
            def _cell(d):
                if d.get("flag"):
                    return f"insuff(n={d.get('n',0)})"
                hr = d.get("hit_rate")
                return f"{hr*100:.1f}%(n={d.get('n',0)})" if hr is not None else f"---(n={d.get('n',0)})"
            label = "mod" if cold_cat == "moderate_cold" else "sev"
            print(f"  {stat} {label} cold: baseline {bl*100:.1f}% | "
                  f"N+1 {_cell(n1)} | N+2 {_cell(n2)} | N+3 {_cell(n3)}")

    # Analysis 3
    print(f"\n{sep}")
    if not a3:
        print("ANALYSIS 3 — Matchup Interaction: SKIPPED (no team log)\n")
    else:
        print("ANALYSIS 3 — Matchup Interaction (cold streak × opponent defense)\n")
        print(f"  {'':14} {'Soft opp':>14} {'Mid opp':>12} {'Tough opp':>12}  Matchup?")
        for stat in ("PTS", "REB", "AST", "3PM"):
            sd = a3.get(stat, {})
            if not sd:
                continue
            for cold_cat in ("moderate_cold", "severe_cold"):
                cat_d = sd.get(cold_cat, {})
                if not cat_d:
                    continue
                def _m(d):
                    if d.get("flag"):
                        return f"---(n={d.get('n',0)})"
                    hr = d.get("hit_rate")
                    return f"{hr*100:.1f}%(n={d.get('n',0)})" if hr is not None else f"---(n={d.get('n',0)})"
                mm     = cat_d.get("matchup_matters")
                mm_str = "Yes" if mm is True else ("No" if mm is False else "?-insuff")
                label  = "mod" if cold_cat == "moderate_cold" else "sev"
                print(f"  {stat} {label:<10} {_m(cat_d.get('soft',{})):>14} "
                      f"{_m(cat_d.get('mid',{})):>12} {_m(cat_d.get('tough',{})):>12}  {mm_str}")

    print(f"\n{sep}")
    print("RECOMMENDATIONS")
    for r in recs:
        print(f"  → {r}")
    print(f"\nPROMPT IMPLICATIONS")
    for i in implies:
        print(f"  → {i}")
    print(f"{'═'*54}\n")


# ── Mean Reversion — Entry Point ──────────────────────────────────────

def run_mean_reversion_analysis(
    player_log: pd.DataFrame, team_log: pd.DataFrame, args
) -> None:
    window      = args.window if args.window else MR_BASELINE_WINDOW
    stat_filter = getattr(args, "stat", None)
    stats_to_run = [stat_filter] if stat_filter else list(STAT_COL.keys())

    print(f"[backtest] Mean-reversion mode | window={window} | "
          f"short_window={MR_SHORT_WINDOW} | stats={stats_to_run}")

    all_instances = []
    for stat in stats_to_run:
        inst = build_mean_reversion_instances(player_log, stat, window, MR_SHORT_WINDOW)
        if not inst.empty:
            n_cold     = int((inst["cold_streak_cat"] != "baseline").sum())
            n_baseline = int((inst["cold_streak_cat"] == "baseline").sum())
            print(f"[backtest] {stat}: {len(inst):,} instances | "
                  f"baseline={n_baseline:,} | cold={n_cold:,} "
                  f"(mild={int((inst['cold_streak_cat']=='mild_cold').sum())} "
                  f"mod={int((inst['cold_streak_cat']=='moderate_cold').sum())} "
                  f"sev={int((inst['cold_streak_cat']=='severe_cold').sum())})")
            all_instances.append(inst)
        else:
            print(f"[backtest] {stat}: no instances")

    if not all_instances:
        print("[backtest] No instances built — cannot run mean reversion analysis.")
        sys.exit(0)

    instances = pd.concat(all_instances, ignore_index=True)
    total_instances = int(len(instances))
    print(f"[backtest] Total instances: {total_instances:,}")

    # Analysis 1 and 2 — fast (vectorized)
    print("[backtest] Running Analysis 1 (next-game hit rate by cold streak severity)...")
    a1 = mean_reversion_analysis_1(instances)

    print("[backtest] Running Analysis 2 (reversion curve N+1, N+2, N+3)...")
    a2 = mean_reversion_analysis_2(instances)

    # Analysis 3 — requires opp defense lookup (slow ~2 min if team_log is large)
    opp_lookup = {}
    if not team_log.empty:
        print("[backtest] Building opp defense lookup for Analysis 3 (this may take ~2 min)...")
        opp_lookup = build_opp_defense_lookup(team_log)
    else:
        print("[backtest] No team log available — skipping Analysis 3 matchup interaction")

    print("[backtest] Running Analysis 3 (cold streak × matchup interaction)...")
    a3 = mean_reversion_analysis_3(instances, opp_lookup)

    recs, implies = mean_reversion_recommendations(a1, a2, a3)

    date_min = instances["game_date"].min()
    date_max = instances["game_date"].max()
    date_min = date_min.strftime("%Y-%m-%d") if hasattr(date_min, "strftime") else str(date_min)
    date_max = date_max.strftime("%Y-%m-%d") if hasattr(date_max, "strftime") else str(date_max)

    meta = {
        "generated_at":   dt.date.today().isoformat(),
        "mode":           "mean-reversion",
        "rolling_window": window,
        "short_window":   MR_SHORT_WINDOW,
        "date_range":     {"start": date_min, "end": date_max},
        "total_instances": total_instances,
    }

    output = {
        **meta,
        "analysis_1_next_game_by_severity": a1,
        "analysis_2_reversion_curve":       a2,
        "analysis_3_matchup_interaction":   a3,
        "recommendations":                  recs,
        "prompt_implications":              implies,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else MEAN_REVERSION_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] Results written → {out_path}")

    print_mean_reversion_report(a1, a2, a3, meta, recs, implies)


# ── Player-Level Bounce-Back Analysis ────────────────────────────────

PBB_MIN_POST_MISS   = 5     # min post-miss observations to include player in rankings
PBB_MIN_GAMES       = 10    # min total games for a player to be analyzed
PBB_COMP_WEIGHTS    = (0.50, 0.30, 0.20)   # (post_miss_hr, 1-consecutive_miss_rate, bb_lift)
PBB_TOP_N           = 10    # players to rank per stat


def _pbb_best_tier(values: np.ndarray, tiers: list) -> tuple:
    """
    Find highest tier where full-season overall hit rate >= 70%.
    values: stat values for all non-DNP games, any order.
    Returns (best_tier, overall_hit_rate) or (None, None) if none qualify.
    Uses >= (exact threshold = HIT, consistent with production quant.py).
    """
    for tier in sorted(tiers, reverse=True):
        hr = float((values >= tier).mean())
        if hr >= CONFIDENCE_FLOOR:
            return tier, hr
    return None, None


def _pbb_metrics(hits: list) -> dict | None:
    """
    Compute all bounce-back metrics for a player's hit sequence at their best tier.
    hits: list of booleans (True = hit, False = miss), chronological order.
    Returns None if fewer than PBB_MIN_POST_MISS post-miss observations.
    """
    n = len(hits)

    # ── Post-miss observations ─────────────────────────────────────────
    post_miss_hits = []     # outcome (True/False) on game N+1 given miss on game N
    for i in range(n - 1):
        if not hits[i]:     # game N is a miss and game N+1 exists
            post_miss_hits.append(hits[i + 1])

    n_post_miss = len(post_miss_hits)
    if n_post_miss < PBB_MIN_POST_MISS:
        return None

    post_miss_hr       = float(np.mean(post_miss_hits))
    consecutive_miss_r = 1.0 - post_miss_hr   # % of misses followed by another miss

    # ── Max consecutive miss streak ────────────────────────────────────
    max_streak = cur = 0
    for h in hits:
        if not h:
            cur += 1
            max_streak = max(max_streak, cur)
        else:
            cur = 0

    # ── Post-miss recovery streak: consecutive hits following each miss ─
    # For each miss at position i (i < n-1), count consecutive hits at i+1, i+2, ...
    recovery_streaks = []
    for i in range(n - 1):
        if not hits[i]:
            streak = 0
            j = i + 1
            while j < n and hits[j]:
                streak += 1
                j += 1
            recovery_streaks.append(streak)
    avg_recovery = float(np.mean(recovery_streaks)) if recovery_streaks else None

    return {
        "n_post_miss_obs":         n_post_miss,
        "post_miss_hit_rate":      round(post_miss_hr, 4),
        "consecutive_miss_rate":   round(consecutive_miss_r, 4),
        "max_consecutive_miss":    max_streak,
        "never_missed_twice":      max_streak <= 1,
        "avg_post_miss_recovery":  round(avg_recovery, 2) if avg_recovery is not None else None,
    }


def run_player_bounce_back(player_log: pd.DataFrame, args) -> None:
    """
    Player-level bounce-back analysis.
    For each whitelisted player × stat, finds best qualifying tier (overall season
    hit rate >= 70%), then computes post-miss hit rate and related metrics.
    Rankings are sorted by composite score; iron floor players flagged separately.
    """
    out_path = Path(args.output) if getattr(args, "output", None) else PLAYER_BOUNCE_BACK_JSON
    print(f"[backtest] Player bounce-back mode | min_post_miss_obs={PBB_MIN_POST_MISS}")

    by_stat: dict = {stat: [] for stat in STAT_COL}
    iron_floor: list = []
    total_analyzed = 0

    for player, pdf in player_log.groupby("player_name"):
        pdf = pdf.sort_values("game_date").reset_index(drop=True)
        if len(pdf) < PBB_MIN_GAMES:
            continue

        for stat, col in STAT_COL.items():
            values = pdf[col].values.astype(float)
            n_games = len(values)
            if n_games < PBB_MIN_GAMES:
                continue

            best_tier, overall_hr = _pbb_best_tier(values, TIERS[stat])
            if best_tier is None:
                continue

            hits = list(values >= best_tier)
            n_misses = hits.count(False)

            m = _pbb_metrics(hits)
            if m is None:
                continue   # < PBB_MIN_POST_MISS post-miss obs

            total_analyzed += 1

            # Bounce-back lift vs overall hit rate
            bb_lift = round(m["post_miss_hit_rate"] / overall_hr, 4) if overall_hr > 0 else 0.0

            # Composite: 50% post_miss_hr, 30% (1-consecutive_miss_rate), 20% bb_lift
            composite = round(
                PBB_COMP_WEIGHTS[0] * m["post_miss_hit_rate"] +
                PBB_COMP_WEIGHTS[1] * (1.0 - m["consecutive_miss_rate"]) +
                PBB_COMP_WEIGHTS[2] * bb_lift,
                4,
            )

            record = {
                "player_name":            player,
                "best_tier":              int(best_tier),
                "n_games":                n_games,
                "n_misses":               n_misses,
                "overall_hit_rate":       round(overall_hr, 4),
                "n_post_miss_obs":        m["n_post_miss_obs"],
                "post_miss_hit_rate":     m["post_miss_hit_rate"],
                "bounce_back_lift":       bb_lift,
                "consecutive_miss_rate":  m["consecutive_miss_rate"],
                "max_consecutive_miss":   m["max_consecutive_miss"],
                "never_missed_twice":     m["never_missed_twice"],
                "avg_post_miss_recovery": m["avg_post_miss_recovery"],
                "composite_score":        composite,
            }
            by_stat[stat].append(record)

            # Iron floor: never missed twice consecutively (with meaningful miss count)
            if m["never_missed_twice"] and n_misses >= 2:
                iron_floor.append({
                    "player_name": player,
                    "stat":        stat,
                    "best_tier":   int(best_tier),
                    "n_games":     n_games,
                    "n_misses":    n_misses,
                    "overall_hit_rate": round(overall_hr, 4),
                })

    print(f"[backtest] Analyzed {total_analyzed} player-stat combinations")

    # ── Sort by composite score descending, keep top PBB_TOP_N ──────────
    for stat in STAT_COL:
        by_stat[stat].sort(key=lambda r: r["composite_score"], reverse=True)
        by_stat[stat] = [
            {**r, "rank": i + 1}
            for i, r in enumerate(by_stat[stat][:PBB_TOP_N])
        ]

    # Deduplicate iron floor (a player could appear for multiple stats)
    iron_floor.sort(key=lambda r: (r["player_name"], r["stat"]))

    # ── Write JSON ────────────────────────────────────────────────────
    output = {
        "generated_at":       dt.date.today().isoformat(),
        "mode":               "player-bounce-back",
        "min_post_miss_obs":  PBB_MIN_POST_MISS,
        "composite_weights":  {
            "post_miss_hit_rate":       PBB_COMP_WEIGHTS[0],
            "1_minus_consec_miss_rate": PBB_COMP_WEIGHTS[1],
            "bounce_back_lift":         PBB_COMP_WEIGHTS[2],
        },
        "by_stat":            by_stat,
        "iron_floor_players": iron_floor,
    }
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] Results written → {out_path}")

    _print_player_bounce_back_report(by_stat, iron_floor)


def _print_player_bounce_back_report(by_stat: dict, iron_floor: list) -> None:
    W   = 82
    sep = "─" * W

    print(f"\n{'═'*W}")
    print("PLAYER BOUNCE-BACK ANALYSIS — Top 5 per stat")
    print("Composite = 50% post-miss HR + 30% (1−consec-miss rate) + 20% BB lift")
    print(f"{'═'*W}")

    stat_labels = {"PTS": "POINTS", "REB": "REBOUNDS", "AST": "ASSISTS", "3PM": "3-POINTERS"}

    for stat in ("PTS", "REB", "AST", "3PM"):
        ranked = by_stat.get(stat, [])
        print(f"\n  {stat_labels[stat]} (T = best tier, n = post-miss obs)")
        if not ranked:
            print("  (no players with ≥5 post-miss observations at a qualifying tier)")
            continue

        hdr = (f"  {'#':<3} {'Player':<26} {'T':>3}  {'Overall':>7}  "
               f"{'PostMiss':>8}  {'BBLift':>6}  {'MaxStr':>6}  {'Comp':>5}")
        print(hdr)
        print(f"  {sep[:78]}")

        for r in ranked[:5]:
            iron = " ★" if r["never_missed_twice"] else "  "
            nm_str = f"n={r['n_post_miss_obs']}"
            print(
                f"  {r['rank']:<3} {r['player_name']:<26} {r['best_tier']:>3}  "
                f"{r['overall_hit_rate']*100:>6.1f}%  "
                f"{r['post_miss_hit_rate']*100:>7.1f}%({nm_str:>5})  "
                f"{r['bounce_back_lift']:>6.3f}  "
                f"{r['max_consecutive_miss']:>6}  "
                f"{r['composite_score']:>5.3f}{iron}"
            )

    # ── Iron floor players ─────────────────────────────────────────────
    print(f"\n{'═'*W}")
    print("IRON FLOOR PLAYERS — Never missed their best tier twice in a row (★)")
    print("(Shown only when player had ≥2 total misses, so pattern is non-trivial)\n")

    if not iron_floor:
        print("  None found with ≥2 misses this season.")
    else:
        print(f"  {'Player':<26} {'Stat':<5} {'Tier':>4}  {'Games':>5}  "
              f"{'Misses':>6}  {'Overall':>7}")
        print(f"  {sep[:72]}")
        for r in iron_floor:
            print(
                f"  {r['player_name']:<26} {r['stat']:<5} {r['best_tier']:>4}  "
                f"{r['n_games']:>5}  {r['n_misses']:>6}  "
                f"{r['overall_hit_rate']*100:>6.1f}%"
            )

    print(f"\n{'═'*W}\n")


# ── Recency Weight Analysis ───────────────────────────────────────────

# Fixed train/test split — do not change without re-running
RW_TRAIN_START   = "2025-10-21"
RW_TRAIN_END     = "2026-01-31"
RW_TEST_START    = "2026-02-01"
RW_TEST_END      = "2026-03-03"
RW_WINDOWS       = [10, 20]
RW_DECAYS        = [1.0, 0.95, 0.90, 0.85]
RW_THRESHOLD     = 0.70
# Previously flagged miscalibrated tiers (from backtest_results.json)
RW_PROBLEM_TIERS = [("REB", 8), ("AST", 8), ("3PM", 2), ("3PM", 3)]
# Primary baseline: deployed production config
RW_BASELINE_KEY  = "w20_d1.00"


def _rw_key(window: int, decay: float) -> str:
    return f"w{window:02d}_d{decay:.2f}"


def _weighted_hit_rate(actuals: np.ndarray, tier: float, decay: float) -> float:
    """
    Weighted hit rate at a tier. actuals ordered oldest → most recent.
    Most recent game (index n-1) gets weight decay^0 = 1.0.
    Each prior game decays geometrically: oldest (index 0) = decay^(n-1).
    hit_i = 1 if actual >= tier (exact threshold = HIT, consistent with production quant.py).
    Returns NaN if actuals is empty.
    """
    n = len(actuals)
    if n == 0:
        return np.nan
    exponents = np.arange(n - 1, -1, -1, dtype=float)   # [n-1, n-2, ..., 1, 0]
    weights   = decay ** exponents
    hits      = (actuals >= tier).astype(float)
    return float(np.dot(weights, hits) / weights.sum())


def run_recency_weight_analysis(player_log: pd.DataFrame, args) -> None:
    test_start = pd.Timestamp(RW_TEST_START)
    test_end   = pd.Timestamp(RW_TEST_END)
    combos     = [(w, d) for w in RW_WINDOWS for d in RW_DECAYS]
    keys       = [_rw_key(w, d) for w, d in combos]

    print(f"[backtest] Recency-weight mode")
    print(f"[backtest] Train: {RW_TRAIN_START} → {RW_TRAIN_END} (lookback only)")
    print(f"[backtest] Test:  {RW_TEST_START} → {RW_TEST_END}  (evaluation)")
    print(f"[backtest] Combos ({len(combos)}): {keys}")

    # Per (combo, stat): list of {"tier": int, "hit": bool}
    pick_records: dict = {k: {s: [] for s in STAT_COL} for k in keys}
    # Per (combo, stat): count of test instances with no pick (insufficient lookback OR no qualifying tier)
    no_pick_count: dict = {k: {s: 0 for s in STAT_COL} for k in keys}
    # Per stat: total test instances (same for all combos — denominator for selection rate)
    total_test:  dict = {s: 0 for s in STAT_COL}

    for player, pdf in player_log.groupby("player_name"):
        pdf = pdf.sort_values("game_date").reset_index(drop=True)

        test_rows = pdf[
            (pdf["game_date"] >= test_start) & (pdf["game_date"] <= test_end)
        ]
        if test_rows.empty:
            continue

        for _, row in test_rows.iterrows():
            test_date = row["game_date"]
            lookback  = pdf[pdf["game_date"] < test_date]
            lb_len    = len(lookback)

            for stat, col in STAT_COL.items():
                actual      = float(row[col])
                tiers_desc  = sorted(TIERS[stat], reverse=True)   # highest first
                lb_vals     = lookback[col].values                  # oldest → most recent

                total_test[stat] += 1

                for (window, decay), ck in zip(combos, keys):
                    if lb_len < window:
                        # Insufficient lookback — no pick
                        no_pick_count[ck][stat] += 1
                        continue

                    recent = lb_vals[-window:]   # last `window` games, oldest→most recent

                    # Walk tiers highest→lowest; pick first that meets threshold
                    selected = None
                    for tier in tiers_desc:
                        if _weighted_hit_rate(recent, float(tier), decay) >= RW_THRESHOLD:
                            selected = tier
                            break

                    if selected is None:
                        no_pick_count[ck][stat] += 1
                    else:
                        pick_records[ck][stat].append({
                            "tier": selected,
                            "hit":  actual >= float(selected),   # >= consistent with production
                        })

    # ── Aggregate results ─────────────────────────────────────────────
    def _calibration(records: list) -> tuple:
        """Returns (hit_rate, n_picks)."""
        n = len(records)
        if n == 0:
            return None, 0
        return round(sum(r["hit"] for r in records) / n, 4), n

    summary: dict = {}
    for (window, decay), ck in zip(combos, keys):
        all_records = [r for s in STAT_COL for r in pick_records[ck][s]]
        cal, n_picks = _calibration(all_records)
        n_total = sum(total_test[s] for s in STAT_COL)

        by_stat: dict = {}
        for stat, col in STAT_COL.items():
            s_records = pick_records[ck][stat]
            s_cal, s_n = _calibration(s_records)
            s_total    = total_test[stat]

            # Per-tier breakdown
            tier_bucket: dict = {}
            for r in s_records:
                tk = str(r["tier"])
                if tk not in tier_bucket:
                    tier_bucket[tk] = {"picks": 0, "hits": 0}
                tier_bucket[tk]["picks"] += 1
                if r["hit"]:
                    tier_bucket[tk]["hits"] += 1

            by_tier = {
                tk: {
                    "n":           v["picks"],
                    "calibration": round(v["hits"] / v["picks"], 4) if v["picks"] > 0 else None,
                }
                for tk, v in sorted(tier_bucket.items(), key=lambda x: int(x[0]))
            }

            by_stat[stat] = {
                "total_instances": s_total,
                "picks_made":      s_n,
                "no_pick":         no_pick_count[ck][stat],
                "selection_rate":  round(s_n / s_total, 4) if s_total > 0 else None,
                "calibration":     s_cal,
                "by_tier":         by_tier,
            }

        summary[ck] = {
            "window":          window,
            "decay":           decay,
            "total_instances": n_total,
            "picks_made":      n_picks,
            "selection_rate":  round(n_picks / n_total, 4) if n_total > 0 else None,
            "calibration":     cal,
            "by_stat":         by_stat,
        }

    # ── Problem tiers ─────────────────────────────────────────────────
    problem_tier_results: dict = {}
    for (stat, tier) in RW_PROBLEM_TIERS:
        pt_key = f"{stat}_{tier}"
        problem_tier_results[pt_key] = {}
        for ck in keys:
            tier_records = [r for r in pick_records[ck][stat] if r["tier"] == tier]
            n    = len(tier_records)
            hits = sum(1 for r in tier_records if r["hit"])
            problem_tier_results[pt_key][ck] = {
                "n":           n,
                "calibration": round(hits / n, 4) if n > 0 else None,
            }

    # ── Write JSON ────────────────────────────────────────────────────
    output = {
        "generated_at":  dt.date.today().isoformat(),
        "mode":          "recency-weight",
        "train_period":  {"start": RW_TRAIN_START, "end": RW_TRAIN_END},
        "test_period":   {"start": RW_TEST_START,  "end": RW_TEST_END},
        "baseline_combo": RW_BASELINE_KEY,
        "combos":        summary,
        "problem_tiers": problem_tier_results,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else RECENCY_WEIGHT_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] Results written → {out_path}")

    _print_recency_weight_report(summary, problem_tier_results, output)


def _print_recency_weight_report(summary: dict, problem_tiers: dict, output: dict) -> None:
    W   = 80
    sep = "─" * W
    tp  = output["test_period"]
    bl  = output["baseline_combo"]
    baseline_cal = (summary.get(bl, {}).get("calibration") or 0)

    print(f"\n{'═'*W}")
    print(f"RECENCY WEIGHT BACKTEST — Test period: {tp['start']} to {tp['end']}")
    print(f"Baseline: {bl} (deployed production config)")
    print(f"Metric: calibration = actual hit rate on test-period picks")
    print(f"{'═'*W}")

    # ── Overall calibration table ──────────────────────────────────────
    print(f"\nOVERALL CALIBRATION (all stats combined)\n")
    hdr = f"  {'Combo':<14} {'Win':>4} {'Decay':>5}  {'Picks':>6}  {'Sel%':>5}  {'Cal%':>6}  vs baseline"
    print(hdr)
    print(f"  {sep[:72]}")
    for ck, d in summary.items():
        w     = d["window"]
        dec   = d["decay"]
        picks = d["picks_made"]
        sel   = (d["selection_rate"] or 0) * 100
        cal   = (d["calibration"] or 0)
        delta = (cal - baseline_cal) * 100
        tag   = f"{delta:+.1f}pp" if ck != bl else "(baseline)"
        print(f"  {ck:<14} {w:>4} {dec:>5.2f}  {picks:>6,}  {sel:>5.1f}%  {cal*100:>5.1f}%  {tag}")

    # ── Per-stat calibration ───────────────────────────────────────────
    print(f"\n{sep}")
    print("PER-STAT CALIBRATION\n")
    stat_hdr = f"  {'Combo':<14} {'Picks':>6}  {'Sel%':>5}  {'Cal%':>6}  vs baseline"
    for stat in ("PTS", "REB", "AST", "3PM"):
        print(f"  {stat}:")
        print(f"  {stat_hdr}")
        bl_stat_cal = (summary.get(bl, {}).get("by_stat", {}).get(stat, {}).get("calibration") or 0)
        for ck, d in summary.items():
            sd  = d["by_stat"].get(stat, {})
            n   = sd.get("picks_made", 0)
            sel = (sd.get("selection_rate") or 0) * 100
            cal = (sd.get("calibration") or 0)
            delta = (cal - bl_stat_cal) * 100
            tag = f"{delta:+.1f}pp" if ck != bl else "(baseline)"
            print(f"  {ck:<14} {n:>6,}  {sel:>5.1f}%  {cal*100:>5.1f}%  {tag}")
        print()

    # ── Problem tiers table ────────────────────────────────────────────
    print(f"{sep}")
    print("PROBLEM TIERS — Calibration by combo")
    print("(previously flagged: REB T8≈66%, AST T8≈58%, 3PM T2≈61%, 3PM T3≈40%)\n")
    pt_hdr = f"  {'Combo':<14} {'n':>5}  {'Cal%':>6}  vs baseline"
    for pt_key, combo_data in problem_tiers.items():
        print(f"  {pt_key}:")
        print(f"  {pt_hdr}")
        bl_pt_cal = (combo_data.get(bl, {}).get("calibration") or 0)
        for ck, d in combo_data.items():
            n   = d.get("n", 0)
            cal = d.get("calibration") or 0
            if n == 0:
                print(f"  {ck:<14} {'---':>5}  {'  ---':>6}  (no picks at this tier)")
            else:
                delta = (cal - bl_pt_cal) * 100
                tag   = f"{delta:+.1f}pp" if ck != bl else "(baseline)"
                print(f"  {ck:<14} {n:>5,}  {cal*100:>5.1f}%  {tag}")
        print()

    print(f"{'═'*W}\n")


# ── H6: Post-Blowout Bounce-Back ─────────────────────────────────────

def build_game_result_lookup(master_df: pd.DataFrame) -> dict:
    """
    Build lookup: {(team_upper, game_date_str): result_type}
    result_type: "blowout_loss" / "close_loss" / "win" / "neutral"

    blowout_loss: team lost by >= POST_BLOWOUT_THRESHOLD points
    close_loss:   team lost by <  POST_BLOWOUT_THRESHOLD points
    win:          team won
    neutral:      missing scores — cannot determine
    """
    lookup: dict = {}
    for _, row in master_df.iterrows():
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        game_date = row.get("game_date")
        if pd.isna(game_date):
            continue
        date_str = pd.Timestamp(game_date).strftime("%Y-%m-%d")

        home_score = pd.to_numeric(row.get("home_score"), errors="coerce")
        away_score = pd.to_numeric(row.get("away_score"), errors="coerce")

        if pd.isna(home_score) or pd.isna(away_score):
            if home:
                lookup[(home, date_str)] = "neutral"
            if away:
                lookup[(away, date_str)] = "neutral"
            continue

        home_margin = float(home_score) - float(away_score)

        # Home team result
        if home_margin > 0:
            home_result = "win"
        elif home_margin > -POST_BLOWOUT_THRESHOLD:
            home_result = "close_loss"
        else:
            home_result = "blowout_loss"

        # Away team result (mirror)
        if home_margin < 0:
            away_result = "win"
        elif home_margin < POST_BLOWOUT_THRESHOLD:
            away_result = "close_loss"
        else:
            away_result = "blowout_loss"

        if home:
            lookup[(home, date_str)] = home_result
        if away:
            lookup[(away, date_str)] = away_result

    print(f"[backtest] Game result lookup: {len(lookup):,} entries")
    return lookup


def add_prior_game_result(player_log: pd.DataFrame, result_lookup: dict) -> pd.DataFrame:
    """
    Add prior_game_result column (blowout_loss / close_loss / win / neutral / null).

    For each player-game row, looks up the team's result in their immediately
    preceding game (shift(1) within each player's chronological game history).
    "null" = no prior game (first game in log).
    """
    df = player_log.copy()
    df = df.sort_values(["player_name", "game_date"]).reset_index(drop=True)

    df["_prior_date"] = df.groupby("player_name")["game_date"].shift(1)
    df["_team_upper"] = df["team_abbrev"].str.upper().str.strip()

    def _get_result(row) -> str:
        prior = row["_prior_date"]
        if pd.isna(prior):
            return "null"
        prior_str = pd.Timestamp(prior).strftime("%Y-%m-%d")
        return result_lookup.get((row["_team_upper"], prior_str), "null")

    df["prior_game_result"] = df.apply(_get_result, axis=1)
    df = df.drop(columns=["_prior_date", "_team_upper"])
    return df


def _post_blowout_compute(qualified_df: pd.DataFrame, hit_col: str = "is_hit") -> dict:
    """
    Core computation: hit rates by prior_game_result.
    qualified_df must already be filtered to valid instances
    (prior_game_result not in null/neutral, best tier not null).
    Returns dict with baseline, per-category rates, and verdict.
    """
    if qualified_df.empty:
        return {
            "baseline_hit_rate": None, "baseline_n": 0,
            "blowout_loss": {"n": 0, "hit_rate": None, "lift": None},
            "close_loss":   {"n": 0, "hit_rate": None, "lift": None},
            "win":          {"n": 0, "hit_rate": None, "lift": None},
            "verdict": "insufficient_data",
        }

    baseline_n  = len(qualified_df)
    baseline_hr = round(float(qualified_df[hit_col].mean()), 4)
    result: dict = {"baseline_hit_rate": baseline_hr, "baseline_n": baseline_n}

    valid_lifts: list = []
    for cat in ("blowout_loss", "close_loss", "win"):
        sub  = qualified_df[qualified_df["prior_game_result"] == cat]
        n    = len(sub)
        hr   = round(float(sub[hit_col].mean()), 4) if n > 0 else None
        lift = round(hr / baseline_hr, 4) if (hr is not None and baseline_hr > 0) else None
        entry: dict = {"n": n, "hit_rate": hr, "lift": lift}
        if 0 < n < MIN_SIGNAL_N:
            entry["flag"] = "insufficient_sample"
        result[cat] = entry
        if lift is not None and n >= MIN_SIGNAL_N:
            valid_lifts.append(lift)

    if len(valid_lifts) < 2:
        verdict = "insufficient_data"
    else:
        lift_var = max(valid_lifts) - min(valid_lifts)
        if lift_var > LIFT_PREDICTIVE:
            verdict = "predictive"
        elif lift_var > LIFT_WEAK:
            verdict = "weak"
        else:
            verdict = "noise"

    result["verdict"] = verdict
    return result


def _post_blowout_recommendations(by_stat: dict) -> tuple:
    recs: list    = []
    implies: list = []

    for stat, d in by_stat.items():
        verdict  = d.get("verdict", "")
        baseline = d.get("baseline_hit_rate") or 0
        bl       = d.get("blowout_loss", {})
        bl_hr    = bl.get("hit_rate") or 0
        bl_lift  = bl.get("lift")
        bl_n     = bl.get("n", 0)

        if verdict == "predictive" and bl_lift is not None:
            recs.append(
                f"{stat}: Post-blowout signal PREDICTIVE — "
                f"blowout_loss hit rate {bl_hr*100:.1f}% vs baseline {baseline*100:.1f}% "
                f"(lift={bl_lift:.3f}, n={bl_n})"
            )
            if bl_lift > 1.08:
                implies.append(
                    f"{stat}: Post-blowout bounce-back confirmed (lift={bl_lift:.2f}, n={bl_n}) — "
                    f"add prompt signal: team coming off blowout loss → mild confidence boost"
                )
            elif bl_lift < 0.92:
                implies.append(
                    f"{stat}: Post-blowout suppression confirmed (lift={bl_lift:.2f}, n={bl_n}) — "
                    f"consider reducing confidence when team lost by ≥{POST_BLOWOUT_THRESHOLD}pts last game"
                )
        elif verdict == "weak" and bl_lift is not None:
            recs.append(
                f"{stat}: Post-blowout signal WEAK — blowout_loss hit rate {bl_hr*100:.1f}% "
                f"(lift={bl_lift:.3f}, n={bl_n}) — directional but not conclusive"
            )
        elif verdict == "noise":
            recs.append(
                f"{stat}: Post-blowout signal NOISE — team's prior game result "
                f"does not predict next-game {stat} tier hit rate"
            )
        elif verdict == "insufficient_data":
            recs.append(
                f"{stat}: Insufficient data for post-blowout verdict "
                f"(blowout_loss n={bl_n}, need ≥{MIN_SIGNAL_N})"
            )

    if not recs:
        recs.append(
            "No post-blowout signal detected across any stat — "
            "team's prior game result does not predict individual prop hit rates."
        )
    if not implies:
        implies.append(
            "No prompt changes warranted — post-blowout bounce-back is not confirmed."
        )

    return recs, implies


def _print_post_blowout_report(
    by_stat: dict, all_stats: dict, meta: dict, recs: list, implies: list
) -> None:
    W   = 70
    sep = "─" * W
    d   = meta["date_range"]

    print(f"\n{'═'*W}")
    print(f"POST-BLOWOUT BOUNCE-BACK BACKTEST — {d['start']} to {d['end']}")
    print(f"Rolling window: {meta['rolling_window']} games | "
          f"Blowout threshold: ≥{meta['blowout_threshold_pts']} pts margin")
    print(f"Total instances: {meta['total_instances']:,}")
    print(f"{'═'*W}")

    def _cell(entry: dict) -> str:
        hr = entry.get("hit_rate")
        n  = entry.get("n", 0)
        if hr is None:
            return f"---(n={n})"
        flag = "*" if entry.get("flag") else ""
        return f"{hr*100:.1f}%{flag}(n={n})"

    def _lift(entry: dict) -> str:
        l = entry.get("lift")
        return f"{l:.3f}" if l is not None else "----"

    print(f"\n  {'Stat':<5} {'Baseline':>14}  {'blowout_loss':>14}  {'Lift':>5}  "
          f"{'close_loss':>14}  {'Lift':>5}  {'win':>12}  {'Lift':>5}  Verdict")
    print(f"  {sep}")

    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = by_stat.get(stat, {})
        if not sd:
            continue
        base = f"{(sd.get('baseline_hit_rate') or 0)*100:.1f}%(n={sd.get('baseline_n', 0)})"
        bl   = sd.get("blowout_loss", {})
        cl   = sd.get("close_loss",   {})
        wn   = sd.get("win",          {})
        v    = sd.get("verdict", "?")
        print(f"  {stat:<5} {base:>14}  {_cell(bl):>14}  {_lift(bl):>5}  "
              f"{_cell(cl):>14}  {_lift(cl):>5}  {_cell(wn):>12}  {_lift(wn):>5}  [{v}]")

    if all_stats:
        base = f"{(all_stats.get('baseline_hit_rate') or 0)*100:.1f}%(n={all_stats.get('baseline_n', 0)})"
        bl   = all_stats.get("blowout_loss", {})
        cl   = all_stats.get("close_loss",   {})
        wn   = all_stats.get("win",          {})
        v    = all_stats.get("verdict", "?")
        print(f"  {'ALL':<5} {base:>14}  {_cell(bl):>14}  {_lift(bl):>5}  "
              f"{_cell(cl):>14}  {_lift(cl):>5}  {_cell(wn):>12}  {_lift(wn):>5}  [{v}]")

    print(f"\n  (* = n < {MIN_SIGNAL_N}, insufficient sample)")
    print(f"\n{sep}")
    print("RECOMMENDATIONS")
    for r in recs:
        print(f"  → {r}")
    print(f"\nPROMPT IMPLICATIONS")
    for i in implies:
        print(f"  → {i}")
    print(f"{'═'*W}\n")


def classify_player_role(
    player_log: pd.DataFrame,
    window: int = 20,
) -> pd.DataFrame:
    """
    For each player-game row, classify the player as 'primary' or 'secondary' scorer
    on their team for that game, based on their rolling PPG average vs. whitelisted
    teammates on the same team.

    Primary = player has the highest rolling avg PTS among all whitelisted players
    on their team in that game's rolling window.
    Secondary = any other whitelisted player on the same team.

    Returns player_log with a new 'scorer_role' column: 'primary' or 'secondary'.
    Uses shift(1).rolling(window) to avoid lookahead on the rolling average.
    player_log must be sorted by player_name, game_date ascending (load_player_log
    already does this).
    """
    df = player_log.copy()

    # Compute rolling avg PTS per player (no lookahead)
    df["_rolling_pts"] = (
        df.groupby("player_name")["pts"]
        .transform(lambda s: s.shift(1).rolling(window, min_periods=5).mean())
    )

    # For each (team_abbrev, game_date), find the player with highest rolling avg PTS
    team_date_max = (
        df.groupby(["team_abbrev", "game_date"])["_rolling_pts"]
        .transform("max")
    )

    df["scorer_role"] = np.where(
        df["_rolling_pts"] == team_date_max,
        "primary",
        "secondary",
    )

    # Fallback: if rolling avg is NaN (< min_periods), mark as unknown and exclude later
    df.loc[df["_rolling_pts"].isna(), "scorer_role"] = "unknown"
    df = df.drop(columns=["_rolling_pts"])
    return df


def run_post_blowout_analysis(
    player_log: pd.DataFrame, master_df: pd.DataFrame, args
) -> None:
    if master_df.empty:
        print("[backtest] WARNING: master_df is empty — cannot run post-blowout analysis.")
        sys.exit(0)

    window       = args.window if args.window else ROLLING_WINDOW
    stat_filter  = getattr(args, "stat", None)
    stats_to_run = [stat_filter] if stat_filter else list(STAT_COL.keys())

    print(f"[backtest] Post-blowout mode | window={window} | stats={stats_to_run} | "
          f"blowout_threshold={POST_BLOWOUT_THRESHOLD}pts")

    print("[backtest] Building game result lookup...")
    result_lookup = build_game_result_lookup(master_df)

    print("[backtest] Adding best tiers...")
    df = add_best_tiers(player_log, window=window)

    print("[backtest] Adding prior game result signal...")
    df = add_prior_game_result(df, result_lookup)

    for cat in ("blowout_loss", "close_loss", "win", "neutral", "null"):
        n = int((df["prior_game_result"] == cat).sum())
        print(f"[backtest] Prior game result — {cat}: {n:,} player-games")

    by_stat:       dict = {}
    all_qualified: list = []

    for stat in stats_to_run:
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"
        q = df[
            df[best_col].notna() &
            df[hit_col].notna() &
            ~df["prior_game_result"].isin(["null", "neutral"])
        ].copy()
        q["is_hit"] = q[hit_col]
        by_stat[stat] = _post_blowout_compute(q)
        print(f"[backtest] {stat}: {len(q):,} qualified instances "
              f"(baseline_hr={by_stat[stat].get('baseline_hit_rate') or 0:.3f} "
              f"verdict={by_stat[stat].get('verdict')})")
        all_qualified.append(q[["prior_game_result", "is_hit"]])

    if all_qualified:
        combined  = pd.concat(all_qualified, ignore_index=True)
        all_stats = _post_blowout_compute(combined)
    else:
        all_stats = {}

    recs, implies = _post_blowout_recommendations(by_stat)

    date_min = player_log["game_date"].min()
    date_max = player_log["game_date"].max()
    date_min = date_min.strftime("%Y-%m-%d") if hasattr(date_min, "strftime") else str(date_min)
    date_max = date_max.strftime("%Y-%m-%d") if hasattr(date_max, "strftime") else str(date_max)
    total_instances = int(sum(r.get("baseline_n", 0) for r in by_stat.values()))

    meta = {
        "generated_at":          dt.date.today().isoformat(),
        "mode":                  "post-blowout",
        "rolling_window":        window,
        "blowout_threshold_pts": POST_BLOWOUT_THRESHOLD,
        "date_range":            {"start": date_min, "end": date_max},
        "total_instances":       total_instances,
    }
    output = {
        **meta,
        "by_stat":             by_stat,
        "all_stats":           all_stats,
        "recommendations":     recs,
        "prompt_implications": implies,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else POST_BLOWOUT_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] Results written → {out_path}")

    _print_post_blowout_report(by_stat, all_stats, meta, recs, implies)


# ── H7: Opponent Schedule Fatigue ─────────────────────────────────────

def build_opp_fatigue_lookup(master_df: pd.DataFrame) -> dict:
    """
    Build lookup: {(team_upper, game_date_str): fatigue_tag}

    fatigue_tag: "b2b" / "dense" / "rested" / "moderate" / "null"

    b2b:      team played yesterday
    dense:    team played >= OPP_DENSE_THRESHOLD games in the OPP_DENSE_WINDOW
              calendar days immediately before this game
    moderate: exactly 1 day rest (played 2 days ago) — not b2b, not dense
    rested:   2+ days rest — not b2b, not dense
    null:     no prior games found (first game in log)

    b2b takes priority over dense — if both are true, tag as b2b.
    """
    if master_df.empty:
        return {}

    home_df = master_df[["game_date", "home_team_abbrev"]].rename(
        columns={"home_team_abbrev": "team"}
    )
    away_df = master_df[["game_date", "away_team_abbrev"]].rename(
        columns={"away_team_abbrev": "team"}
    )
    all_games = pd.concat([home_df, away_df]).dropna()
    all_games["team"]      = all_games["team"].str.upper().str.strip()
    all_games["game_date"] = pd.to_datetime(all_games["game_date"], errors="coerce")
    all_games = all_games.dropna(subset=["game_date"]).drop_duplicates()

    # Per-team set of game date objects (for O(1) lookup)
    team_date_sets: dict = {}
    for _, row in all_games.iterrows():
        team = row["team"]
        d    = row["game_date"].date()
        if team not in team_date_sets:
            team_date_sets[team] = set()
        team_date_sets[team].add(d)

    lookup: dict = {}
    for team, date_set in team_date_sets.items():
        for game_date in sorted(date_set):
            date_str = game_date.strftime("%Y-%m-%d")

            # B2B: played yesterday
            yesterday = game_date - dt.timedelta(days=1)
            if yesterday in date_set:
                lookup[(team, date_str)] = "b2b"
                continue

            # Dense: >= OPP_DENSE_THRESHOLD games in the OPP_DENSE_WINDOW days before
            games_in_window = sum(
                1 for i in range(1, OPP_DENSE_WINDOW + 1)
                if (game_date - dt.timedelta(days=i)) in date_set
            )
            if games_in_window >= OPP_DENSE_THRESHOLD:
                lookup[(team, date_str)] = "dense"
                continue

            # Days since last game
            prior_dates = [d for d in date_set if d < game_date]
            if not prior_dates:
                lookup[(team, date_str)] = "null"
                continue
            last_game = max(prior_dates)
            days_rest = (game_date - last_game).days - 1  # 0 = B2B, 1 = 1-day rest

            if days_rest == 0:
                lookup[(team, date_str)] = "b2b"   # guard — already caught above
            elif days_rest == 1:
                lookup[(team, date_str)] = "moderate"
            else:
                lookup[(team, date_str)] = "rested"

    print(f"[backtest] Opp fatigue lookup: {len(lookup):,} entries")
    return lookup


def add_opp_fatigue_signal(player_log: pd.DataFrame, fatigue_lookup: dict) -> pd.DataFrame:
    """Add opp_fatigue column (b2b / dense / rested / moderate / null)."""
    df = player_log.copy()
    df["_date_str"]  = df["game_date"].dt.strftime("%Y-%m-%d")
    df["_opp_upper"] = df["opp_abbrev"].str.upper().str.strip()

    df["opp_fatigue"] = df.apply(
        lambda r: fatigue_lookup.get((r["_opp_upper"], r["_date_str"]), "null"),
        axis=1,
    )
    df = df.drop(columns=["_date_str", "_opp_upper"])
    return df


def _opp_fatigue_compute(qualified_df: pd.DataFrame, hit_col: str = "is_hit") -> dict:
    """
    Core computation: hit rates by opp_fatigue.
    qualified_df must already be filtered to valid instances
    (opp_fatigue != null, best tier not null).
    """
    if qualified_df.empty:
        return {
            "baseline_hit_rate": None, "baseline_n": 0,
            "b2b":      {"n": 0, "hit_rate": None, "lift": None},
            "dense":    {"n": 0, "hit_rate": None, "lift": None},
            "moderate": {"n": 0, "hit_rate": None, "lift": None},
            "rested":   {"n": 0, "hit_rate": None, "lift": None},
            "verdict": "insufficient_data",
        }

    baseline_n  = len(qualified_df)
    baseline_hr = round(float(qualified_df[hit_col].mean()), 4)
    result: dict = {"baseline_hit_rate": baseline_hr, "baseline_n": baseline_n}

    valid_lifts: list = []
    for cat in ("b2b", "dense", "moderate", "rested"):
        sub  = qualified_df[qualified_df["opp_fatigue"] == cat]
        n    = len(sub)
        hr   = round(float(sub[hit_col].mean()), 4) if n > 0 else None
        lift = round(hr / baseline_hr, 4) if (hr is not None and baseline_hr > 0) else None
        entry: dict = {"n": n, "hit_rate": hr, "lift": lift}
        if 0 < n < MIN_SIGNAL_N:
            entry["flag"] = "insufficient_sample"
        result[cat] = entry
        if lift is not None and n >= MIN_SIGNAL_N:
            valid_lifts.append(lift)

    if len(valid_lifts) < 2:
        verdict = "insufficient_data"
    else:
        lift_var = max(valid_lifts) - min(valid_lifts)
        if lift_var > LIFT_PREDICTIVE:
            verdict = "predictive"
        elif lift_var > LIFT_WEAK:
            verdict = "weak"
        else:
            verdict = "noise"

    result["verdict"] = verdict
    return result


def _opp_fatigue_recommendations(by_stat: dict) -> tuple:
    recs: list    = []
    implies: list = []

    for stat, d in by_stat.items():
        verdict  = d.get("verdict", "")
        baseline = d.get("baseline_hit_rate") or 0
        b2b_d    = d.get("b2b", {})
        b2b_hr   = b2b_d.get("hit_rate") or 0
        b2b_lift = b2b_d.get("lift")
        b2b_n    = b2b_d.get("n", 0)

        if verdict == "predictive" and b2b_lift is not None:
            recs.append(
                f"{stat}: Opp-fatigue signal PREDICTIVE — "
                f"opp B2B hit rate {b2b_hr*100:.1f}% vs baseline {baseline*100:.1f}% "
                f"(lift={b2b_lift:.3f}, n={b2b_n}) — lift variance confirms spread"
            )
            if b2b_lift > 1.08:
                implies.append(
                    f"{stat}: Opponent B2B confirmed as prop boost (lift={b2b_lift:.2f}, n={b2b_n}) — "
                    f"when opp is on B2B, treat as mild positive signal for {stat}"
                )
            elif b2b_lift < 0.92:
                implies.append(
                    f"{stat}: Opponent B2B suppresses prop (lift={b2b_lift:.2f}, n={b2b_n}) — "
                    f"unexpected; review methodology before applying to prompt"
                )
        elif verdict == "weak":
            recs.append(
                f"{stat}: Opp-fatigue signal WEAK — directional but below predictive threshold"
            )
        elif verdict == "noise":
            recs.append(
                f"{stat}: Opp-fatigue signal NOISE — opponent rest state does not predict {stat} hit rate"
            )
        elif verdict == "insufficient_data":
            recs.append(
                f"{stat}: Insufficient data for opp-fatigue verdict "
                f"(opp B2B n={b2b_n}, need ≥{MIN_SIGNAL_N})"
            )

    if not recs:
        recs.append(
            "No opponent fatigue signal detected across any stat — "
            "opponent rest context does not predict individual prop hit rates."
        )
    if not implies:
        implies.append(
            "No prompt changes warranted — opponent fatigue is not confirmed as a "
            "prop predictor at current sample sizes."
        )

    return recs, implies


def _print_opp_fatigue_report(
    by_stat: dict,
    all_stats: dict,
    meta: dict,
    recs: list,
    implies: list,
    own_b2b_data: dict,
) -> None:
    W   = 72
    sep = "─" * W
    d   = meta["date_range"]

    print(f"\n{'═'*W}")
    print(f"OPPONENT FATIGUE BACKTEST — {d['start']} to {d['end']}")
    print(f"Rolling window: {meta['rolling_window']} games | "
          f"Dense threshold: ≥{meta['dense_schedule_threshold']} games / "
          f"{meta['dense_schedule_window_days']} days")
    print(f"Total instances: {meta['total_instances']:,}")
    print(f"{'═'*W}")

    def _cell(entry: dict) -> str:
        hr = entry.get("hit_rate")
        n  = entry.get("n", 0)
        if hr is None:
            return f"---(n={n})"
        flag = "*" if entry.get("flag") else ""
        return f"{hr*100:.1f}%{flag}(n={n})"

    def _lift(entry: dict) -> str:
        l = entry.get("lift")
        return f"{l:.3f}" if l is not None else "----"

    print(f"\n  {'Stat':<5} {'Baseline':>14}  {'b2b':>12}  {'Lift':>5}  "
          f"{'dense':>12}  {'Lift':>5}  {'moderate':>14}  {'Lift':>5}  "
          f"{'rested':>12}  {'Lift':>5}  Verdict")
    print(f"  {sep}")

    for stat in ("PTS", "REB", "AST", "3PM"):
        sd = by_stat.get(stat, {})
        if not sd:
            continue
        base = f"{(sd.get('baseline_hit_rate') or 0)*100:.1f}%(n={sd.get('baseline_n', 0)})"
        b2   = sd.get("b2b",      {})
        dn   = sd.get("dense",    {})
        mo   = sd.get("moderate", {})
        rs   = sd.get("rested",   {})
        v    = sd.get("verdict", "?")
        print(f"  {stat:<5} {base:>14}  {_cell(b2):>12}  {_lift(b2):>5}  "
              f"{_cell(dn):>12}  {_lift(dn):>5}  {_cell(mo):>14}  {_lift(mo):>5}  "
              f"{_cell(rs):>12}  {_lift(rs):>5}  [{v}]")

    if all_stats:
        base = f"{(all_stats.get('baseline_hit_rate') or 0)*100:.1f}%(n={all_stats.get('baseline_n', 0)})"
        b2   = all_stats.get("b2b",      {})
        dn   = all_stats.get("dense",    {})
        mo   = all_stats.get("moderate", {})
        rs   = all_stats.get("rested",   {})
        v    = all_stats.get("verdict", "?")
        print(f"  {'ALL':<5} {base:>14}  {_cell(b2):>12}  {_lift(b2):>5}  "
              f"{_cell(dn):>12}  {_lift(dn):>5}  {_cell(mo):>14}  {_lift(mo):>5}  "
              f"{_cell(rs):>12}  {_lift(rs):>5}  [{v}]")

    print(f"\n  (* = n < {MIN_SIGNAL_N}, insufficient sample)")

    # Own-team B2B comparison for context
    if own_b2b_data:
        print(f"\n{sep}")
        print("OWN-TEAM B2B COMPARISON (for context)")
        print(f"  {'Stat':<5} {'Baseline':>14}  {'Own B2B':>12}  {'Lift':>5}  "
              f"{'Non-B2B':>12}  {'Lift':>5}")
        print(f"  {sep[:62]}")
        for stat in ("PTS", "REB", "AST", "3PM"):
            ob = own_b2b_data.get(stat, {})
            if not ob:
                continue
            base_hr = ob.get("baseline_hr") or 0
            b2b_hr  = ob.get("b2b_hr")  or 0
            nb_hr   = ob.get("non_b2b_hr") or 0
            b2b_n   = ob.get("b2b_n", 0)
            nb_n    = ob.get("non_b2b_n", 0)
            bn      = ob.get("baseline_n", 0)
            b2b_lift = round(b2b_hr / base_hr, 3) if base_hr > 0 and b2b_hr > 0 else None
            nb_lift  = round(nb_hr  / base_hr, 3) if base_hr > 0 and nb_hr  > 0 else None
            base_str  = f"{base_hr*100:.1f}%(n={bn})"
            b2b_str   = f"{b2b_hr*100:.1f}%(n={b2b_n})"
            nb_str    = f"{nb_hr*100:.1f}%(n={nb_n})"
            b2b_l_str = f"{b2b_lift:.3f}" if b2b_lift is not None else "----"
            nb_l_str  = f"{nb_lift:.3f}"  if nb_lift  is not None else "----"
            print(f"  {stat:<5} {base_str:>14}  {b2b_str:>12}  {b2b_l_str:>5}  "
                  f"{nb_str:>12}  {nb_l_str:>5}")

    print(f"\n{sep}")
    print("RECOMMENDATIONS")
    for r in recs:
        print(f"  → {r}")
    print(f"\nPROMPT IMPLICATIONS")
    for i in implies:
        print(f"  → {i}")
    print(f"{'═'*W}\n")


def run_opp_fatigue_analysis(
    player_log: pd.DataFrame, master_df: pd.DataFrame, args
) -> None:
    if master_df.empty:
        print("[backtest] WARNING: master_df is empty — cannot run opp-fatigue analysis.")
        sys.exit(0)

    window       = args.window if args.window else ROLLING_WINDOW
    stat_filter  = getattr(args, "stat", None)
    stats_to_run = [stat_filter] if stat_filter else list(STAT_COL.keys())

    print(f"[backtest] Opp-fatigue mode | window={window} | stats={stats_to_run} | "
          f"dense_threshold={OPP_DENSE_THRESHOLD}/{OPP_DENSE_WINDOW}d")

    print("[backtest] Building opponent fatigue lookup...")
    fatigue_lookup = build_opp_fatigue_lookup(master_df)

    print("[backtest] Adding best tiers...")
    df = add_best_tiers(player_log, window=window)

    print("[backtest] Adding opponent fatigue signal...")
    df = add_opp_fatigue_signal(df, fatigue_lookup)

    for cat in ("b2b", "dense", "moderate", "rested", "null"):
        n = int((df["opp_fatigue"] == cat).sum())
        print(f"[backtest] Opp fatigue — {cat}: {n:,} player-games")

    # Own-team B2B comparison (add signal on a copy; does not affect df)
    df_b2b = add_b2b_signal(df.copy(), master_df)
    own_b2b_data: dict = {}
    for stat in stats_to_run:
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"
        q_b2b = df_b2b[df_b2b[best_col].notna() & df_b2b[hit_col].notna()].copy()
        if q_b2b.empty:
            continue
        base_hr = float(q_b2b[hit_col].mean())
        b2b_sub = q_b2b[q_b2b["on_b2b"] == True]   # noqa: E712
        nb_sub  = q_b2b[q_b2b["on_b2b"] == False]   # noqa: E712
        own_b2b_data[stat] = {
            "baseline_hr":  round(base_hr, 4),
            "baseline_n":   len(q_b2b),
            "b2b_hr":       round(float(b2b_sub[hit_col].mean()), 4) if len(b2b_sub) > 0 else None,
            "b2b_n":        len(b2b_sub),
            "non_b2b_hr":   round(float(nb_sub[hit_col].mean()),  4) if len(nb_sub)  > 0 else None,
            "non_b2b_n":    len(nb_sub),
        }

    by_stat:       dict = {}
    all_qualified: list = []

    for stat in stats_to_run:
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"
        q = df[
            df[best_col].notna() &
            df[hit_col].notna() &
            (df["opp_fatigue"] != "null")
        ].copy()
        q["is_hit"] = q[hit_col]
        by_stat[stat] = _opp_fatigue_compute(q)
        print(f"[backtest] {stat}: {len(q):,} qualified instances "
              f"(baseline_hr={by_stat[stat].get('baseline_hit_rate') or 0:.3f} "
              f"verdict={by_stat[stat].get('verdict')})")
        all_qualified.append(q[["opp_fatigue", "is_hit"]])

    if all_qualified:
        combined  = pd.concat(all_qualified, ignore_index=True)
        all_stats = _opp_fatigue_compute(combined)
    else:
        all_stats = {}

    recs, implies = _opp_fatigue_recommendations(by_stat)

    date_min = player_log["game_date"].min()
    date_max = player_log["game_date"].max()
    date_min = date_min.strftime("%Y-%m-%d") if hasattr(date_min, "strftime") else str(date_min)
    date_max = date_max.strftime("%Y-%m-%d") if hasattr(date_max, "strftime") else str(date_max)
    total_instances = int(sum(r.get("baseline_n", 0) for r in by_stat.values()))

    meta = {
        "generated_at":              dt.date.today().isoformat(),
        "mode":                      "opp-fatigue",
        "rolling_window":            window,
        "dense_schedule_threshold":  OPP_DENSE_THRESHOLD,
        "dense_schedule_window_days": OPP_DENSE_WINDOW,
        "date_range":                {"start": date_min, "end": date_max},
        "total_instances":           total_instances,
    }
    output = {
        **meta,
        "by_stat":             by_stat,
        "all_stats":           all_stats,
        "recommendations":     recs,
        "prompt_implications": implies,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else OPP_FATIGUE_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] Results written → {out_path}")

    _print_opp_fatigue_report(by_stat, all_stats, meta, recs, implies, own_b2b_data)


# ── Stdout formatting ─────────────────────────────────────────────────

def print_report(signal_results: dict, calibration: dict, meta: dict):
    sep = "─" * 72

    print(f"\n{'═'*72}")
    print(f"  NBAgent Backtest Report — {meta['generated_at']}")
    print(f"  Date range: {meta['date_range']['start']} → {meta['date_range']['end']}")
    print(f"  Total instances (player-game-stat): {meta['total_instances']:,}")
    print(f"{'═'*72}\n")

    for stat in ("PTS", "REB", "AST", "3PM"):
        print(f"\n{'='*72}")
        print(f"  STAT: {stat}")
        print(f"{'='*72}")

        stat_signals = signal_results.get(stat, {})
        for sig_name, sig_data in stat_signals.items():
            verdict = sig_data.get("verdict", "?")
            verdict_str = f"[{verdict.upper()}]"
            baseline = sig_data.get("baseline_hit_rate")
            baseline_n = sig_data.get("baseline_n", 0)
            baseline_str = f"{baseline*100:.1f}%" if baseline else "n/a"
            print(f"\n  {sig_name:<18} {verdict_str:<18}  baseline={baseline_str} (n={baseline_n:,})")
            print(f"  {sep}")

            by_value = sig_data.get("by_value", {})
            for val, entry in sorted(by_value.items()):
                n     = entry.get("n", 0)
                hits  = entry.get("hits", 0)
                hr    = entry.get("hit_rate")
                lift  = entry.get("lift")
                note  = entry.get("note", "")
                if note:
                    print(f"    {val:<12} n={n:<6}  {note}")
                else:
                    hr_str   = f"{hr*100:.1f}%"   if hr   is not None else "n/a"
                    lift_str = f"lift={lift:.3f}"  if lift is not None else ""
                    bar = ""
                    if lift is not None:
                        if lift > 1.10:
                            bar = " ▲▲"
                        elif lift > 1.05:
                            bar = " ▲"
                        elif lift < 0.90:
                            bar = " ▼▼"
                        elif lift < 0.95:
                            bar = " ▼"
                    print(f"    {str(val):<12} n={n:<6} hits={hits:<6} hr={hr_str:<8} {lift_str}{bar}")

        # Tier calibration for this stat
        print(f"\n  Tier Calibration:")
        print(f"  {sep}")
        for tier_str, entry in sorted(calibration.get(stat, {}).items(), key=lambda x: int(x[0])):
            n       = entry["n"]
            hr      = entry["hit_rate"]
            flag    = "  ⚠ THRESHOLD CONCERN" if entry.get("flag") == "threshold_concern" else ""
            print(f"    Tier {tier_str:<6} n={n:<6} hit_rate={hr*100:.1f}%{flag}")

    print(f"\n{'='*72}")
    print("  RECOMMENDATIONS")
    print(f"{'='*72}")


# ── Shooting Regression Mode ──────────────────────────────────────────

def compute_fg_pct_flag(player_log: pd.DataFrame) -> pd.DataFrame:
    """
    Add fg_flag, fg3_flag, and _fg_delta_pct columns to player_log.

    Computed per-player using only prior games (shift=1 before rolling)
    so the flag reflects what the system would have seen on game morning.
    player_log must be sorted oldest→newest per player (load_player_log default).

    fga == 0 → treated as missing data (NaN), not 0% shooting.
    Requires SR_MIN_GAMES non-NaN fg_pct values in the L20 window to assign a flag.
    """
    df = player_log.copy()

    # Per-row FG% and 3P% — NaN when no shot attempts
    df["_fg_pct"]  = df["fgm"] / df["fga"].replace(0, np.nan)
    df["_fg3_pct"] = df["fg3m"] / df["fg3a"].replace(0, np.nan)

    # Per-player rolling L20 and L5, shifted so current game is excluded
    grp_fg  = df.groupby("player_name")["_fg_pct"]
    grp_fg3 = df.groupby("player_name")["_fg3_pct"]

    l20_fg  = grp_fg.transform(
        lambda x: x.shift(1).rolling(SR_L20_WINDOW, min_periods=SR_MIN_GAMES).mean()
    )
    l5_fg   = grp_fg.transform(
        lambda x: x.shift(1).rolling(SR_L5_WINDOW, min_periods=3).mean()
    )
    l20_fg3 = grp_fg3.transform(
        lambda x: x.shift(1).rolling(SR_L20_WINDOW, min_periods=SR_MIN_GAMES).mean()
    )
    l5_fg3  = grp_fg3.transform(
        lambda x: x.shift(1).rolling(SR_L5_WINDOW, min_periods=3).mean()
    )

    # Relative deltas
    fg_delta  = (l5_fg  - l20_fg)  / l20_fg.replace(0, np.nan)
    fg3_delta = (l5_fg3 - l20_fg3) / l20_fg3.replace(0, np.nan)

    def _flag_series(delta: pd.Series, l20: pd.Series, hot_thresh: float, cold_thresh: float) -> pd.Series:
        flags = pd.Series("insufficient", index=delta.index, dtype=str)
        valid = l20.notna() & delta.notna()
        flags[valid] = "neutral"
        flags[valid & (delta >= hot_thresh)]   = "hot"
        flags[valid & (delta <= -cold_thresh)] = "cold"
        return flags

    df["fg_flag"]       = _flag_series(fg_delta,  l20_fg,  SR_HOT_THRESH, SR_COLD_THRESH)
    df["fg3_flag"]      = _flag_series(fg3_delta, l20_fg3, SR_HOT_THRESH, SR_COLD_THRESH)
    df["_fg_delta_pct"] = fg_delta   # raw delta preserved for threshold sweep

    df = df.drop(columns=["_fg_pct", "_fg3_pct"])
    return df


def build_shooting_regression_instances(player_log: pd.DataFrame) -> pd.DataFrame:
    """
    Build the evaluation instance DataFrame for the shooting regression backtest.

    Each row represents a game where:
    - The player had a qualifying PTS tier (≥ T20) based on prior 20 games
    - FG% data existed pre-game (fg_flag != 'insufficient')
    - FG attempts data was present (fga not NaN)

    Returns DataFrame with columns:
      player_name, game_date, fg_flag, fg3_flag, pts, best_tier_pts,
      pts_tier_hit (bool), fgm, fga, fg3m, fg3a, _fg_delta_pct
    """
    print("[sr-backtest] Computing FG% flags per player...")
    df = compute_fg_pct_flag(player_log)

    print("[sr-backtest] Computing best PTS tiers (window=20)...")
    df = add_best_tiers(df, window=20)

    qualified = df[
        (df["fg_flag"] != "insufficient") &
        (df["best_tier_PTS"].notna()) &
        (df["best_tier_PTS"] >= 20) &
        (df["fga"].notna())
    ].copy()

    qualified["pts_tier_hit"] = (qualified["hit_actual_PTS"] == 1.0)

    return qualified[[
        "player_name", "game_date", "fg_flag", "fg3_flag",
        "pts", "best_tier_PTS", "pts_tier_hit",
        "fgm", "fga", "fg3m", "fg3a", "_fg_delta_pct",
    ]].rename(columns={"best_tier_PTS": "best_tier_pts"})


def run_shooting_regression_analysis(player_log: pd.DataFrame, args) -> None:
    """H10 — Shooting Efficiency Regression backtest."""
    sep = "─" * 60

    print(f"\n{'='*72}")
    print("  BACKTEST H10: SHOOTING EFFICIENCY REGRESSION")
    print(f"  Date range: {player_log['game_date'].min().date()} → {player_log['game_date'].max().date()}")
    print(f"{'='*72}\n")

    # ── Step 1: Build instances ────────────────────────────────────────
    instances = build_shooting_regression_instances(player_log)
    total = len(instances)
    counts = instances["fg_flag"].value_counts().to_dict()

    print(f"  Instance counts by FG flag (qualifying rows: best_tier_pts ≥ T20, fg data present):")
    for flag in ["hot", "cold", "neutral", "insufficient"]:
        n = counts.get(flag, 0)
        pct = f"  ({n/total*100:.1f}%)" if total > 0 else ""
        print(f"    {flag:<14} n={n:,}{pct}")
    print(f"    {'TOTAL':<14} n={total:,}\n")

    if total == 0:
        print("[sr-backtest] No qualified instances — check that fgm/fga columns exist in player_game_log.csv.")
        return

    # ── Step 2: Core analysis ──────────────────────────────────────────
    print(f"  FG FLAG → PTS TIER HIT RATE")
    print(f"  {sep}")

    neutral_bucket = instances[instances["fg_flag"] == "neutral"]
    neutral_n    = len(neutral_bucket)
    neutral_hits = int(neutral_bucket["pts_tier_hit"].sum())
    neutral_hr   = neutral_hits / neutral_n if neutral_n > 0 else None

    core_analysis: dict = {}
    for flag in ["neutral", "cold", "hot"]:
        bucket = instances[instances["fg_flag"] == flag]
        n    = len(bucket)
        hits = int(bucket["pts_tier_hit"].sum())
        hr   = round(hits / n, 4) if n > 0 else None
        lift = round(hr / neutral_hr, 3) if (hr is not None and neutral_hr) else None

        if flag == "neutral":
            lift_str = "lift=1.000 (baseline)"
        else:
            lift_str = f"lift={lift:.3f}" if lift is not None else "n/a"
        hr_str = f"{hr*100:.1f}%" if hr is not None else "n/a"

        bar = ""
        if lift is not None and flag != "neutral":
            if lift > 1.10:   bar = "  ▲▲"
            elif lift > 1.05: bar = "  ▲"
            elif lift < 0.90: bar = "  ▼▼"
            elif lift < 0.95: bar = "  ▼"

        note = ""
        if n < SR_MIN_N:
            note = f"  ⚠ n < {SR_MIN_N} (insufficient for verdict)"

        print(f"  {flag:<10} n={n:<6} hits={hits:<6} hr={hr_str:<8} {lift_str}{bar}{note}")
        core_analysis[flag] = {"n": n, "hits": hits, "hit_rate": hr, "lift": lift if flag != "neutral" else 1.0}

    # ── Step 3: Threshold sensitivity sweep ───────────────────────────
    print(f"\n  THRESHOLD SENSITIVITY — delta required to flag HOT or COLD")
    print(f"  {sep}")
    header = f"  {'thresh':<8} {'hot_n':<8} {'hot_hr':<10} {'hot_lift':<12} {'cold_n':<8} {'cold_hr':<10} {'cold_lift'}"
    print(header)

    sweep_results: list = []
    for thresh_pct in range(5, 21):
        t = thresh_pct / 100.0
        hot_mask  = instances["_fg_delta_pct"] >= t
        cold_mask = instances["_fg_delta_pct"] <= -t
        # neutral: everything in-between (among rows with non-null delta)
        neutral_mask = (
            instances["_fg_delta_pct"].notna() &
            ~hot_mask & ~cold_mask
        )

        hot_bucket  = instances[hot_mask]
        cold_bucket = instances[cold_mask]
        neut_bucket = instances[neutral_mask]

        neut_n = len(neut_bucket)
        neut_hr = neut_bucket["pts_tier_hit"].sum() / neut_n if neut_n > 0 else None

        def _bucket_stats(b):
            bn = len(b)
            bh = int(b["pts_tier_hit"].sum())
            bhr = round(bh / bn, 4) if bn > 0 else None
            blift = round(bhr / neut_hr, 3) if (bhr is not None and neut_hr) else None
            return bn, bh, bhr, blift

        hot_n, hot_hits, hot_hr, hot_lift   = _bucket_stats(hot_bucket)
        cold_n, cold_hits, cold_hr, cold_lift = _bucket_stats(cold_bucket)

        marker = "  ← current" if thresh_pct == int(SR_HOT_THRESH * 100) else ""
        hot_hr_str  = f"{hot_hr*100:.1f}%"  if hot_hr  is not None else "n/a"
        cold_hr_str = f"{cold_hr*100:.1f}%" if cold_hr is not None else "n/a"
        hot_lift_str  = f"{hot_lift:.3f}"  if hot_lift  is not None else "n/a"
        cold_lift_str = f"{cold_lift:.3f}" if cold_lift is not None else "n/a"

        print(f"  {str(thresh_pct)+'%':<8} {hot_n:<8} {hot_hr_str:<10} {hot_lift_str:<12} {cold_n:<8} {cold_hr_str:<10} {cold_lift_str}{marker}")

        sweep_results.append({
            "threshold_pct": thresh_pct,
            "hot_n":  hot_n,  "hot_hr":  hot_hr,  "hot_lift":  hot_lift,
            "cold_n": cold_n, "cold_hr": cold_hr, "cold_lift": cold_lift,
        })

    # ── Step 4: Tier split ─────────────────────────────────────────────
    print(f"\n  PER-TIER SPLIT (best_tier_pts × fg_flag)")
    print(f"  {sep}")
    tier_split: dict = {}
    for tier_val in [20, 25, 30]:
        tier_key = f"T{tier_val}"
        tier_bucket = instances[instances["best_tier_pts"] == float(tier_val)]
        tier_split[tier_key] = {}
        parts = []
        for flag in ["hot", "neutral", "cold"]:
            fb = tier_bucket[tier_bucket["fg_flag"] == flag]
            n  = len(fb)
            if n < 10:
                parts.append(f"{flag}=n<10")
                tier_split[tier_key][flag] = {"n": n, "note": "n<10"}
            else:
                hr = round(fb["pts_tier_hit"].sum() / n, 4)
                parts.append(f"{flag}={hr*100:.1f}%(n={n})")
                tier_split[tier_key][flag] = {"n": n, "hit_rate": hr}
        print(f"  {tier_key}: {' | '.join(parts)}")

    # ── Step 5: Verdict ────────────────────────────────────────────────
    print(f"\n  VERDICT")
    print(f"  {sep}")

    hot_lift_base  = core_analysis["hot"]["lift"]
    cold_lift_base = core_analysis["cold"]["lift"]
    hot_n_base     = core_analysis["hot"]["n"]
    cold_n_base    = core_analysis["cold"]["n"]

    def _signal_verdict(lift, n) -> str:
        if n < SR_MIN_N or lift is None:
            return "insufficient_data"
        if lift > 1 + LIFT_PREDICTIVE or lift < 1 - LIFT_PREDICTIVE:
            return "predictive"
        if lift > 1 + LIFT_WEAK or lift < 1 - LIFT_WEAK:
            return "weak"
        return "noise"

    signal_verdict      = _signal_verdict(hot_lift_base,  hot_n_base)
    cold_signal_verdict = _signal_verdict(cold_lift_base, cold_n_base)

    # Best threshold for HOT: maximize hot_lift while hot_n >= SR_MIN_N
    best_thresh_entry = max(
        (r for r in sweep_results if r["hot_n"] >= SR_MIN_N and r["hot_lift"] is not None),
        key=lambda r: r["hot_lift"],
        default=None,
    )
    if best_thresh_entry:
        threshold_verdict = (
            f"{best_thresh_entry['threshold_pct']}% maximizes hot_lift "
            f"({best_thresh_entry['hot_lift']:.3f}) with n={best_thresh_entry['hot_n']}"
        )
    else:
        threshold_verdict = f"No threshold with hot_n >= {SR_MIN_N} found"

    # Recommendations
    recommendations: list[str] = []
    if signal_verdict == "predictive" and hot_lift_base is not None and hot_lift_base < 1.0:
        recommendations.append(
            f"FG_HOT reduces PTS hit rate (lift={hot_lift_base:.3f}). "
            "Confirm -3% confidence penalty in analyst.py is calibrated correctly."
        )
    elif signal_verdict == "noise" or signal_verdict == "insufficient_data":
        recommendations.append(
            "FG_HOT signal is not predictive at the population level. "
            "Consider relaxing the -3% penalty or raising the threshold before removing."
        )
    else:
        recommendations.append(
            f"FG_HOT signal shows {signal_verdict} lift={hot_lift_base:.3f}. "
            "Current -3% penalty directionally supported; monitor accumulation."
        )

    if cold_signal_verdict == "predictive":
        recommendations.append(
            f"FG_COLD is predictive (lift={cold_lift_base:.3f}). "
            "Consider adding a confidence adjustment for cold-shooting players."
        )
    else:
        recommendations.append(
            f"FG_COLD is {cold_signal_verdict} (lift={cold_lift_base:.3f}). "
            "No change recommended — maintain 'mild caution' framing in prompt."
        )

    print(f"  signal_verdict (HOT):  {signal_verdict}")
    print(f"  signal_verdict (COLD): {cold_signal_verdict}")
    print(f"  threshold_verdict:     {threshold_verdict}")
    for rec in recommendations:
        print(f"  → {rec}")

    # ── Step 6: Write JSON ─────────────────────────────────────────────
    date_min = player_log["game_date"].min().strftime("%Y-%m-%d")
    date_max = player_log["game_date"].max().strftime("%Y-%m-%d")

    output = {
        "generated_at":       dt.datetime.now().isoformat(timespec="seconds"),
        "mode":               "shooting-regression",
        "date_range":         {"start": date_min, "end": date_max},
        "total_instances":    total,
        "instances_by_flag":  {
            "hot":         counts.get("hot", 0),
            "cold":        counts.get("cold", 0),
            "neutral":     counts.get("neutral", 0),
            "insufficient": counts.get("insufficient", 0),
        },
        "core_analysis":      core_analysis,
        "threshold_sweep":    sweep_results,
        "tier_split":         tier_split,
        "verdict": {
            "signal_verdict":      signal_verdict,
            "cold_signal_verdict": cold_signal_verdict,
            "threshold_verdict":   threshold_verdict,
            "recommendations":     recommendations,
        },
    }

    out_path = Path(args.output) if getattr(args, "output", None) else SHOOTING_REGRESSION_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[sr-backtest] Results written → {out_path}")
    print(f"\n{'='*72}\n")


# ── Shot Volume Mode ──────────────────────────────────────────────────

def compute_fga_volume_flag(player_log: pd.DataFrame) -> pd.DataFrame:
    """
    Add fga_volume_flag and _fga_delta_pct columns to player_log.

    Operates on raw FGA counts (not FG%). fga=NaN means missing data;
    fga=0 is a real zero (rare non-DNP game with no attempts).
    player_log must be sorted oldest→newest per player.
    """
    df = player_log.copy()

    grp_fga = df.groupby("player_name")["fga"]

    l20_fga = grp_fga.transform(
        lambda x: x.shift(1).rolling(SV_L20_WINDOW, min_periods=SV_MIN_GAMES).mean()
    )
    l5_fga = grp_fga.transform(
        lambda x: x.shift(1).rolling(SV_L5_WINDOW, min_periods=3).mean()
    )

    fga_delta = (l5_fga - l20_fga) / l20_fga.replace(0, np.nan)

    flags = pd.Series("insufficient", index=df.index, dtype=str)
    valid = l20_fga.notna() & fga_delta.notna()
    flags[valid] = "volume_neutral"
    flags[valid & (fga_delta >= SV_HIGH_THRESH)]  = "volume_high"
    flags[valid & (fga_delta <= -SV_LOW_THRESH)]  = "volume_low"

    df["fga_volume_flag"] = flags
    df["_fga_delta_pct"]  = fga_delta
    return df


def build_shot_volume_instances(player_log: pd.DataFrame) -> pd.DataFrame:
    """
    Build evaluation instances for the shot volume backtest.

    Rows qualify when: fga_volume_flag != 'insufficient',
    best_tier_PTS >= 20, and fga is not NaN.
    """
    print("[sv-backtest] Computing FGA volume flags per player...")
    df = compute_fga_volume_flag(player_log)

    print("[sv-backtest] Computing best PTS tiers (window=20)...")
    df = add_best_tiers(df, window=20)

    qualified = df[
        (df["fga_volume_flag"] != "insufficient") &
        (df["best_tier_PTS"].notna()) &
        (df["best_tier_PTS"] >= 20) &
        (df["fga"].notna())
    ].copy()

    qualified["pts_tier_hit"] = (qualified["hit_actual_PTS"] == 1.0)

    return qualified[[
        "player_name", "game_date", "fga_volume_flag",
        "pts", "best_tier_PTS", "pts_tier_hit",
        "fga", "_fga_delta_pct",
    ]].rename(columns={"best_tier_PTS": "best_tier_pts"})


def run_shot_volume_analysis(player_log: pd.DataFrame, args) -> None:
    """H13 — Shot Volume Delta backtest."""
    sep = "─" * 60

    print(f"\n{'='*72}")
    print("  BACKTEST H13: SHOT VOLUME DELTA (L5 FGA vs L20 FGA)")
    print(f"  Date range: {player_log['game_date'].min().date()} → {player_log['game_date'].max().date()}")
    print(f"{'='*72}\n")

    # ── Step 1: Build instances ────────────────────────────────────────
    instances = build_shot_volume_instances(player_log)
    total = len(instances)
    counts = instances["fga_volume_flag"].value_counts().to_dict()

    print("  Instance counts by FGA volume flag (qualifying rows: best_tier_pts ≥ T20, fga present):")
    for flag in ["volume_high", "volume_low", "volume_neutral", "insufficient"]:
        n = counts.get(flag, 0)
        pct = f"  ({n/total*100:.1f}%)" if total > 0 and flag != "insufficient" else ""
        print(f"    {flag:<18} n={n:,}{pct}")
    print(f"    {'TOTAL':<18} n={total:,}\n")

    if total == 0:
        print("[sv-backtest] No qualified instances — check fga column in player_game_log.csv.")
        return

    # Median FGA sanity check
    median_fga: dict = {}
    for flag in ["volume_high", "volume_neutral", "volume_low"]:
        bucket = instances[instances["fga_volume_flag"] == flag]
        median_fga[flag] = round(float(bucket["fga"].median()), 1) if len(bucket) > 0 else None

    print(f"  Median FGA — volume_high: {median_fga.get('volume_high')} | "
          f"volume_neutral: {median_fga.get('volume_neutral')} | "
          f"volume_low: {median_fga.get('volume_low')}")
    print()

    # ── Step 2: Core analysis ──────────────────────────────────────────
    print(f"  FGA VOLUME FLAG → PTS TIER HIT RATE")
    print(f"  {sep}")

    neutral_bucket = instances[instances["fga_volume_flag"] == "volume_neutral"]
    neutral_n    = len(neutral_bucket)
    neutral_hits = int(neutral_bucket["pts_tier_hit"].sum())
    neutral_hr   = neutral_hits / neutral_n if neutral_n > 0 else None

    core_analysis: dict = {}
    for flag in ["volume_neutral", "volume_low", "volume_high"]:
        bucket = instances[instances["fga_volume_flag"] == flag]
        n    = len(bucket)
        hits = int(bucket["pts_tier_hit"].sum())
        hr   = round(hits / n, 4) if n > 0 else None
        lift = round(hr / neutral_hr, 3) if (hr is not None and neutral_hr) else None

        if flag == "volume_neutral":
            lift_str = "lift=1.000 (baseline)"
        else:
            lift_str = f"lift={lift:.3f}" if lift is not None else "n/a"
        hr_str = f"{hr*100:.1f}%" if hr is not None else "n/a"

        bar = ""
        if lift is not None and flag != "volume_neutral":
            if lift > 1.10:   bar = "  ▲▲"
            elif lift > 1.05: bar = "  ▲"
            elif lift < 0.90: bar = "  ▼▼"
            elif lift < 0.95: bar = "  ▼"

        note = f"  ⚠ n < {SV_MIN_N}" if n < SV_MIN_N else ""
        print(f"  {flag:<16} n={n:<6} hits={hits:<6} hr={hr_str:<8} {lift_str}{bar}{note}")
        core_analysis[flag] = {
            "n": n, "hits": hits, "hit_rate": hr,
            "lift": lift if flag != "volume_neutral" else 1.0,
        }

    # ── Step 3: Threshold sensitivity sweep ───────────────────────────
    print(f"\n  THRESHOLD SENSITIVITY — delta required to flag VOLUME_HIGH or VOLUME_LOW")
    print(f"  {sep}")
    print(f"  {'thresh':<8} {'high_n':<8} {'high_hr':<10} {'high_lift':<12} {'low_n':<8} {'low_hr':<10} {'low_lift'}")

    sweep_results: list = []
    for thresh_pct in range(5, 26):
        t = thresh_pct / 100.0
        high_mask    = instances["_fga_delta_pct"] >= t
        low_mask     = instances["_fga_delta_pct"] <= -t
        neutral_mask = instances["_fga_delta_pct"].notna() & ~high_mask & ~low_mask

        neut_bucket = instances[neutral_mask]
        neut_n  = len(neut_bucket)
        neut_hr = neut_bucket["pts_tier_hit"].sum() / neut_n if neut_n > 0 else None

        def _stats(b):
            bn   = len(b)
            bh   = int(b["pts_tier_hit"].sum())
            bhr  = round(bh / bn, 4) if bn > 0 else None
            blift = round(bhr / neut_hr, 3) if (bhr is not None and neut_hr) else None
            return bn, bh, bhr, blift

        high_n, _, high_hr, high_lift = _stats(instances[high_mask])
        low_n,  _, low_hr,  low_lift  = _stats(instances[low_mask])

        marker = "  ← current" if thresh_pct == int(SV_HIGH_THRESH * 100) else ""
        print(
            f"  {str(thresh_pct)+'%':<8} {high_n:<8} "
            f"{(str(round(high_hr*100,1))+'%') if high_hr else 'n/a':<10} "
            f"{str(high_lift) if high_lift else 'n/a':<12} "
            f"{low_n:<8} "
            f"{(str(round(low_hr*100,1))+'%') if low_hr else 'n/a':<10} "
            f"{str(low_lift) if low_lift else 'n/a'}{marker}"
        )
        sweep_results.append({
            "threshold_pct": thresh_pct,
            "high_n": high_n, "high_hr": high_hr, "high_lift": high_lift,
            "low_n":  low_n,  "low_hr":  low_hr,  "low_lift":  low_lift,
        })

    # ── Step 4: Tier split ─────────────────────────────────────────────
    print(f"\n  PER-TIER SPLIT (best_tier_pts × fga_volume_flag)")
    print(f"  {sep}")
    tier_split: dict = {}
    for tier_val in [20, 25, 30]:
        tier_key = f"T{tier_val}"
        tier_bucket = instances[instances["best_tier_pts"] == float(tier_val)]
        tier_split[tier_key] = {}
        parts = []
        for flag in ["volume_high", "volume_neutral", "volume_low"]:
            fb = tier_bucket[tier_bucket["fga_volume_flag"] == flag]
            n  = len(fb)
            if n < 10:
                parts.append(f"{flag}=n<10")
                tier_split[tier_key][flag] = {"n": n, "note": "n<10"}
            else:
                hr = round(fb["pts_tier_hit"].sum() / n, 4)
                parts.append(f"{flag}={hr*100:.1f}%(n={n})")
                tier_split[tier_key][flag] = {"n": n, "hit_rate": hr}
        print(f"  {tier_key}: {' | '.join(parts)}")

    # ── Step 5: Verdict ────────────────────────────────────────────────
    print(f"\n  VERDICT")
    print(f"  {sep}")

    def _signal_verdict(lift, n) -> str:
        if n < SV_MIN_N or lift is None:
            return "insufficient_data"
        if lift > 1 + LIFT_PREDICTIVE or lift < 1 - LIFT_PREDICTIVE:
            return "predictive"
        if lift > 1 + LIFT_WEAK or lift < 1 - LIFT_WEAK:
            return "weak"
        return "noise"

    high_lift_base = core_analysis["volume_high"]["lift"]
    low_lift_base  = core_analysis["volume_low"]["lift"]
    high_verdict   = _signal_verdict(high_lift_base, core_analysis["volume_high"]["n"])
    low_verdict    = _signal_verdict(low_lift_base,  core_analysis["volume_low"]["n"])

    best_low_entry = max(
        (r for r in sweep_results if r["low_n"] >= SV_MIN_N and r["low_lift"] is not None),
        key=lambda r: abs(r["low_lift"] - 1.0),
        default=None,
    )
    if best_low_entry:
        threshold_verdict = (
            f"{best_low_entry['threshold_pct']}% maximizes low_lift divergence "
            f"({best_low_entry['low_lift']:.3f}) with n={best_low_entry['low_n']}"
        )
    else:
        threshold_verdict = f"No threshold with low_n >= {SV_MIN_N} found"

    recommendations: list[str] = []
    if low_verdict == "predictive" and low_lift_base is not None and low_lift_base < 0.85:
        recommendations.append(
            f"volume_low is predictive (lift={low_lift_base:.3f}). "
            "Add [VOL_LOW] flag to quant.py PTS stat lines with a confidence reduction."
        )
    elif low_verdict in ("weak", "predictive"):
        recommendations.append(
            f"volume_low shows {low_verdict} signal (lift={low_lift_base:.3f}). "
            "Consider surfacing as informational context on PTS stat lines in quant.py."
        )
    else:
        recommendations.append(
            f"volume_low is {low_verdict} (lift={low_lift_base:.3f}). "
            "Shot volume delta does not predict PTS tier outcomes — hypothesis closed."
        )

    if high_verdict == "predictive" and high_lift_base is not None and high_lift_base > 1.15:
        recommendations.append(
            f"volume_high is predictive (lift={high_lift_base:.3f}). "
            "Surface as mild positive context on PTS stat lines."
        )
    else:
        recommendations.append(
            f"volume_high is {high_verdict} (lift={high_lift_base:.3f}). No change recommended."
        )

    print(f"  high_volume_verdict: {high_verdict}")
    print(f"  low_volume_verdict:  {low_verdict}")
    print(f"  threshold_verdict:   {threshold_verdict}")
    for rec in recommendations:
        print(f"  → {rec}")

    # ── Step 6: Write JSON ─────────────────────────────────────────────
    date_min = player_log["game_date"].min().strftime("%Y-%m-%d")
    date_max = player_log["game_date"].max().strftime("%Y-%m-%d")

    output = {
        "generated_at":        dt.datetime.now().isoformat(timespec="seconds"),
        "mode":                "shot-volume",
        "date_range":          {"start": date_min, "end": date_max},
        "total_instances":     total,
        "instances_by_flag":   {
            "volume_high":    counts.get("volume_high", 0),
            "volume_low":     counts.get("volume_low", 0),
            "volume_neutral":  counts.get("volume_neutral", 0),
            "insufficient":   counts.get("insufficient", 0),
        },
        "median_fga_by_flag":  median_fga,
        "core_analysis":       core_analysis,
        "threshold_sweep":     sweep_results,
        "tier_split":          tier_split,
        "verdict": {
            "high_volume_verdict": high_verdict,
            "low_volume_verdict":  low_verdict,
            "threshold_verdict":   threshold_verdict,
            "recommendations":     recommendations,
        },
    }

    out_path = Path(args.output) if getattr(args, "output", None) else SV_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[sv-backtest] Results written → {out_path}")
    print(f"\n{'='*72}\n")


def run_ft_safety_margin_backtest(player_log: pd.DataFrame, args) -> None:
    """
    H11 — FG% Safety Margin Backtest.

    For each player-game instance where a qualifying PTS tier (T20/T25/T30)
    exists and sufficient prior FG + FT data is available, computes the FG%
    safety margin from the prior L20 games (strict temporal holdout):

      breakeven_fg_pct = (tier - season_ftm_avg - season_3pm_avg) / (season_fga_avg * 2)
      margin           = season_fg_pct - breakeven_fg_pct

    Classifies each instance as safe / borderline / fragile and measures PTS
    tier hit rates within each bucket. ft_dominant instances (where FTs + 3s
    alone could reach the tier) are excluded.

    Requires player_game_log.csv to have ftm/fta columns (run
    ingest/backfill_ft_stats.py + ingest/merge_ft_stats.py first).
    """
    print(f"\n{'='*72}")
    print(f"  H11 — FG% Safety Margin Backtest")
    print(f"{'='*72}")

    # Verify required columns exist
    for col in ["ftm", "fta", "fgm", "fga", "tpm"]:
        if col not in player_log.columns:
            print(f"\n[H11] ERROR: column '{col}' not found in player_game_log.csv.")
            print(f"       Run ingest/backfill_ft_stats.py + ingest/merge_ft_stats.py first.")
            sys.exit(1)

    # Coerce shooting / FT columns to numeric (empty strings → NaN)
    for col in ["ftm", "fta", "fgm", "fga", "tpm"]:
        player_log[col] = pd.to_numeric(player_log[col], errors="coerce")

    # Add best tiers so we know which PTS tier to evaluate per row
    log = add_best_tiers(player_log.copy(), window=FSM_L20_WINDOW)

    instances = []

    for player_name, grp in log.groupby("player_name"):
        # Sort ascending for temporal rolling
        grp_asc = grp.sort_values("game_date").reset_index(drop=True)
        n_rows = len(grp_asc)

        for idx in range(n_rows):
            row = grp_asc.iloc[idx]

            # Only evaluate rows with a qualifying PTS tier at T20 / T25 / T30
            tier_val = row.get("best_tier_PTS")
            if pd.isna(tier_val):
                continue
            tier = int(float(tier_val))
            if tier not in (20, 25, 30):
                continue

            # Prior games only (strict temporal holdout)
            prior = grp_asc.iloc[:idx]
            if len(prior) == 0:
                continue

            # DNP mask for prior games
            dnp_prior = pd.to_numeric(prior["dnp"], errors="coerce").fillna(0) == 1

            # Valid shooting games: non-DNP AND fga > 0
            prior_shots = prior[~dnp_prior & (prior["fga"].fillna(0) > 0)]
            prior_shots_20 = prior_shots.tail(FSM_L20_WINDOW)
            if len(prior_shots_20) < FSM_MIN_GAMES:
                continue

            # Active games (non-DNP) for FT/3PM averages — same L20 window
            prior_active = prior[~dnp_prior].tail(FSM_L20_WINDOW)
            if len(prior_active) < FSM_MIN_GAMES:
                continue

            # Season averages (aggregated totals, not mean of per-game rates)
            total_fgm = float(prior_shots_20["fgm"].fillna(0).sum())
            total_fga = float(prior_shots_20["fga"].fillna(0).sum())
            if total_fga == 0:
                continue
            season_fg_pct  = total_fgm / total_fga
            season_fga_avg = total_fga / len(prior_shots_20)

            season_ftm_avg = float(prior_active["ftm"].fillna(0).mean())
            season_3pm_avg = float(prior_active["tpm"].fillna(0).mean())

            pts_from_ft_and_3s = season_ftm_avg + season_3pm_avg

            # ft_dominant: player can reach tier from FTs + 3s alone
            if pts_from_ft_and_3s >= tier:
                continue

            if season_fga_avg == 0:
                continue

            pts_needed_from_fg = tier - pts_from_ft_and_3s
            breakeven_fg_pct   = pts_needed_from_fg / (season_fga_avg * 2)

            # Impossible tier (requires FG% > 100%)
            if breakeven_fg_pct > 1.0:
                continue

            margin = season_fg_pct - breakeven_fg_pct

            if margin >= FSM_SAFE_THRESH:
                fragility = "safe"
            elif margin >= FSM_FRAG_THRESH:
                fragility = "borderline"
            else:
                fragility = "fragile"

            # Did the player hit the tier?
            actual_pts = row.get("pts")
            if pd.isna(actual_pts):
                continue
            hit = 1 if float(actual_pts) >= tier else 0

            instances.append({
                "player":            player_name,
                "game_date":         str(row["game_date"])[:10],
                "tier":              tier,
                "fragility":         fragility,
                "margin":            round(margin, 3),
                "breakeven_fg_pct":  round(breakeven_fg_pct, 3),
                "season_fg_pct":     round(season_fg_pct, 3),
                "season_ftm_avg":    round(season_ftm_avg, 2),
                "season_3pm_avg":    round(season_3pm_avg, 2),
                "season_fga_avg":    round(season_fga_avg, 2),
                "hit":               hit,
            })

    print(f"\n[H11] Total qualifying instances: {len(instances)}")
    if len(instances) < 30:
        print(f"[H11] WARNING: fewer than 30 instances — results are not reliable.")
        print(f"       Ensure player_game_log.csv has ftm/fta columns from the backfill.")
        return

    df = pd.DataFrame(instances)
    baseline_hr = float(df["hit"].mean())
    date_range = f"{df['game_date'].min()} → {df['game_date'].max()}"

    # ── Core hit rates by fragility ───────────────────────────────────────
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  Core Hit Rates by Fragility Bucket")
    print(f"{sep}")
    print(f"  Baseline (all): n={len(df)}, hr={baseline_hr:.1%}")

    results_by_fragility: dict = {}
    for label in ["safe", "borderline", "fragile"]:
        sub = df[df["fragility"] == label]
        if len(sub) == 0:
            print(f"  {label:12s}: n=0 — no instances")
            results_by_fragility[label] = {"n": 0, "hit_rate": None, "lift": None, "verdict": "no_data"}
            continue
        hr   = float(sub["hit"].mean())
        lift = hr / baseline_hr if baseline_hr > 0 else None
        abs_lift = abs(lift - 1.0) if lift else 0
        if abs_lift >= LIFT_PREDICTIVE:
            verdict = "PREDICTIVE"
        elif abs_lift >= LIFT_WEAK:
            verdict = "weak"
        else:
            verdict = "noise"
        print(f"  {label:12s}: n={len(sub):3d}, hr={hr:.1%}, lift={lift:.3f}  {verdict}")
        results_by_fragility[label] = {
            "n": len(sub), "hit_rate": round(hr, 3),
            "lift": round(lift, 3) if lift is not None else None, "verdict": verdict,
        }

    # ── Tier split: T20 vs T25 vs T30 ────────────────────────────────────
    print(f"\n{sep}")
    print(f"  Tier Split: T20 vs T25 vs T30")
    print(f"{sep}")
    tier_results: dict = {}
    for tier_val in [20, 25, 30]:
        sub = df[df["tier"] == tier_val]
        if len(sub) == 0:
            print(f"  T{tier_val}: n=0")
            tier_results[str(tier_val)] = {}
            continue
        t_baseline = float(sub["hit"].mean())
        print(f"  T{tier_val} (n={len(sub)}, baseline={t_baseline:.1%}):")
        tfrag: dict = {}
        for label in ["safe", "borderline", "fragile"]:
            fsub = sub[sub["fragility"] == label]
            if len(fsub) < 5:
                print(f"    {label:12s}: n={len(fsub)} (insufficient)")
                tfrag[label] = {"n": len(fsub), "hit_rate": None}
                continue
            hr   = float(fsub["hit"].mean())
            lift = hr / t_baseline if t_baseline > 0 else None
            print(f"    {label:12s}: n={len(fsub):3d}, hr={hr:.1%}, lift={lift:.3f}")
            tfrag[label] = {"n": len(fsub), "hit_rate": round(hr, 3), "lift": round(lift, 3) if lift else None}
        tier_results[str(tier_val)] = tfrag

    # ── Threshold sweep: fragile threshold 0.00 → 0.10 in 0.01 steps ────
    print(f"\n{sep}")
    print(f"  Threshold Sweep (fragile = margin < X)")
    print(f"{sep}")
    sweep_results: dict = {}
    for thresh_int in range(0, 11):
        thresh = thresh_int / 100.0
        fragile_mask = df["margin"] < thresh
        safe_mask    = df["margin"] >= thresh
        n_frag = int(fragile_mask.sum())
        n_safe = int(safe_mask.sum())
        if n_frag < FSM_MIN_N or n_safe < FSM_MIN_N:
            continue
        hr_frag = float(df.loc[fragile_mask, "hit"].mean())
        hr_safe = float(df.loc[safe_mask,    "hit"].mean())
        delta   = hr_safe - hr_frag
        print(f"  thresh={thresh:.2f}: fragile n={n_frag:3d} hr={hr_frag:.1%} | "
              f"safe n={n_safe:3d} hr={hr_safe:.1%} | delta={delta:+.1%}")
        sweep_results[f"{thresh:.2f}"] = {
            "fragile": {"n": n_frag, "hit_rate": round(hr_frag, 3)},
            "safe":    {"n": n_safe, "hit_rate": round(hr_safe, 3)},
            "delta":   round(delta, 3),
        }

    # ── Overall verdict ───────────────────────────────────────────────────
    safe_hr    = results_by_fragility.get("safe",    {}).get("hit_rate")
    fragile_hr = results_by_fragility.get("fragile", {}).get("hit_rate")
    if safe_hr is not None and fragile_hr is not None:
        delta = safe_hr - fragile_hr
        if delta >= LIFT_PREDICTIVE:
            verdict = "PREDICTIVE — fragile picks underperform safe picks meaningfully"
        elif delta >= LIFT_WEAK:
            verdict = "weak — directional but below predictive threshold"
        else:
            verdict = "noise — fragility not predictive"
    else:
        verdict = "insufficient data for verdict"

    print(f"\n  Verdict: {verdict}")

    # ── Write JSON ────────────────────────────────────────────────────────
    output = {
        "mode":             "ft-safety-margin",
        "date_range":       date_range,
        "total_instances":  len(df),
        "ft_dominant_excluded": True,
        "baseline_hit_rate": round(baseline_hr, 3),
        "results_by_fragility": results_by_fragility,
        "tier_split":       tier_results,
        "threshold_sweep":  sweep_results,
        "verdict":          verdict,
        "constants": {
            "FSM_L20_WINDOW":  FSM_L20_WINDOW,
            "FSM_MIN_GAMES":   FSM_MIN_GAMES,
            "FSM_SAFE_THRESH": FSM_SAFE_THRESH,
            "FSM_FRAG_THRESH": FSM_FRAG_THRESH,
        },
    }
    FSM_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(FSM_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[H11] Results written → {FSM_JSON}")
    print(f"\n{'='*72}\n")


# ── Positional DvP Backtest (H8) ──────────────────────────────────────

def run_positional_dvp_analysis(
    player_log: pd.DataFrame,
    team_log: pd.DataFrame,
    whitelist_df: pd.DataFrame,
    args,
) -> None:
    """H8 — Positional DvP Validity Backtest.

    Retroactively computes position-specific opponent defense ratings from raw
    game log data and compares their predictive lift against team-level ratings.
    """
    sep = "─" * 60
    VALID_POSITIONS = {"PG", "SG", "SF", "PF", "C"}
    PERIMETER   = {"PG", "SG"}
    FRONTCOURT  = {"PF", "C"}

    print(f"\n{'='*60}")
    print(f"  H8 — Positional DvP Validity Backtest")
    print(f"  Date range: {player_log['game_date'].min().date()} → {player_log['game_date'].max().date()}")
    print(f"{'='*60}\n")

    # ── Step 1: Add position column from whitelist ─────────────────────
    if whitelist_df.empty or "position" not in whitelist_df.columns:
        print("[H8] ERROR: whitelist_df missing or has no 'position' column.")
        return
    wl_active = whitelist_df[whitelist_df["active"].astype(str).str.strip() == "1"].copy()
    pos_map = dict(zip(
        wl_active["player_name"].str.strip().str.lower(),
        wl_active["position"].str.strip().str.upper(),
    ))
    df = player_log.copy()
    df["position"] = df["player_name"].str.strip().str.lower().map(pos_map)
    df = df[df["position"].notna() & df["position"].isin(VALID_POSITIONS)].copy()
    n_after = len(df)
    print(f"  Player log after position filter: {n_after:,} rows "
          f"({df['player_name'].nunique()} players)")
    pos_counts = df["position"].value_counts().to_dict()
    for pos in ["PG", "SG", "SF", "PF", "C"]:
        print(f"    {pos}: {pos_counts.get(pos, 0):,} rows")
    print()
    if n_after < 100:
        print("[H8] ERROR: fewer than 100 rows after position filter — insufficient data.")
        return

    # ── Step 2: Build positional DvP rolling averages ─────────────────
    # For each player-game: rolling mean of stat for players of this position
    # who played against the same opponent in the prior PDV_WINDOW games.
    # Achieved by grouping by (opp_abbrev, position) and computing a
    # shift(1) rolling mean — no lookahead.
    print(f"  [H8] Computing positional DvP rolling averages "
          f"(window={PDV_WINDOW}, min={PDV_MIN_GAMES})...")
    df["_opp_upper"] = df["opp_abbrev"].str.upper().str.strip()
    df_sorted = df.sort_values(["_opp_upper", "position", "game_date"]).copy()

    for stat, col in STAT_COL.items():
        df_sorted[f"pos_dvp_{stat}"] = df_sorted.groupby(
            ["_opp_upper", "position"]
        )[col].transform(
            lambda x: x.shift(1).rolling(PDV_WINDOW, min_periods=PDV_MIN_GAMES).mean()
        )

    # Index-aligned merge back to original order
    for stat in STAT_COL:
        df[f"pos_dvp_{stat}"] = df_sorted[f"pos_dvp_{stat}"]
    df = df.drop(columns=["_opp_upper"])

    for stat in STAT_COL:
        n_nn = int(df[f"pos_dvp_{stat}"].notna().sum())
        print(f"    pos_dvp_{stat}: {n_nn:,} non-null ({n_nn / len(df) * 100:.1f}%)")
    print()

    # ── Step 3: Classify positional DvP into soft/mid/tough ───────────
    # Percentiles computed per (stat, position) so PG PTS is ranked vs other
    # PG PTS values — not mixed with C PTS values.
    # High allowed avg = soft defense (favorable for offense).
    print(f"  [H8] Classifying positional DvP per stat × position "
          f"(soft={PDV_TOUGH_PCTILE}th pctile, tough={PDV_SOFT_PCTILE}th pctile)...")
    for stat in STAT_COL:
        dvp_col    = f"pos_dvp_{stat}"
        rating_col = f"pos_dvp_rating_{stat}"
        df[rating_col] = "null"
        for pos in VALID_POSITIONS:
            pos_mask = df["position"] == pos
            vals = df.loc[pos_mask, dvp_col].dropna()
            if len(vals) < PDV_MIN_N:
                continue
            p_low  = float(np.percentile(vals, PDV_SOFT_PCTILE))   # ≤33rd → tough
            p_high = float(np.percentile(vals, PDV_TOUGH_PCTILE))  # ≥67th → soft

            def _classify(v, pl=p_low, ph=p_high):
                if pd.isna(v):
                    return "null"
                if v >= ph:
                    return "soft"
                if v <= pl:
                    return "tough"
                return "mid"

            df.loc[pos_mask, rating_col] = df.loc[pos_mask, dvp_col].apply(_classify)

    # ── Step 4: Build team-level opp defense ratings ───────────────────
    print(f"  [H8] Building team-level opp defense ratings...")
    if not team_log.empty:
        opp_lookup = build_opp_defense_lookup(team_log)
        df = add_opp_defense_signal(df, opp_lookup)
    else:
        print("  [H8] WARNING: team_log empty — team-level comparison unavailable.")
        for stat in STAT_COL:
            df[f"opp_def_{stat}"] = "null"

    # ── Step 5: Compute best tiers ─────────────────────────────────────
    print(f"  [H8] Computing best tiers (window={PDV_WINDOW})...")
    df = add_best_tiers(df, window=PDV_WINDOW)
    total_instances = int(sum(df[f"best_tier_{s}"].notna().sum() for s in STAT_COL))
    print(f"  [H8] Qualified instances by stat:")
    for stat in STAT_COL:
        print(f"    {stat}: {int(df[f'best_tier_{stat}'].notna().sum()):,}")
    print(f"    Total: {total_instances:,}\n")

    if total_instances < PDV_MIN_N:
        print("[H8] ERROR: insufficient qualified instances for analysis.")
        return

    # ── Step 6: Core hit rate analysis ────────────────────────────────
    date_min = df["game_date"].min().strftime("%Y-%m-%d")
    date_max = df["game_date"].max().strftime("%Y-%m-%d")

    def _fl(v):
        """Format a float as 3dp, or 'n/a'."""
        return f"{v:.3f}" if v is not None else "n/a"

    def _hr_str(n, hr):
        flag = " ⚠" if n < PDV_MIN_N else ""
        return f"n={n} hr={hr * 100:.1f}%{flag}" if hr is not None else f"n={n} hr=n/a{flag}"

    def bucket_hit_rates(data: pd.DataFrame, stat: str, rating_col: str) -> dict:
        """Compute hit rates for soft/mid/tough buckets."""
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"
        qual = data[data[best_col].notna() & data[hit_col].notna()].copy()
        results: dict = {}
        for rating in ("soft", "mid", "tough"):
            bucket = qual[qual[rating_col] == rating]
            n  = len(bucket)
            hr = round(float(bucket[hit_col].mean()), 4) if n > 0 else None
            results[rating] = {"n": n, "hit_rate": hr}
        soft_hr  = results["soft"]["hit_rate"]
        tough_hr = results["tough"]["hit_rate"]
        lift = round(soft_hr / tough_hr, 3) if (soft_hr is not None and tough_hr and tough_hr > 0) else None
        results["lift"] = lift
        return results

    print(f"\n{'='*60}")
    print(f"  H8 — Positional DvP Validity Backtest")
    print(f"  Date range: {date_min} → {date_max}")
    print(f"  Qualified instances: {total_instances:,}")
    print(f"{'='*60}")

    results_by_stat: dict  = {}
    position_breakdown: dict = {}

    for stat in STAT_COL:
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"
        n_total  = int(df[df[best_col].notna() & df[hit_col].notna()].__len__())

        print(f"\n  {stat} ({n_total:,} instances)")
        print(f"  {sep}")

        tl_rates  = bucket_hit_rates(df, stat, f"opp_def_{stat}")
        pos_rates = bucket_hit_rates(df, stat, f"pos_dvp_rating_{stat}")

        tl_lift  = tl_rates["lift"]
        pos_lift = pos_rates["lift"]

        print(f"  Team-level DvP:")
        print(f"    soft {_hr_str(tl_rates['soft']['n'], tl_rates['soft']['hit_rate'])} | "
              f"mid {_hr_str(tl_rates['mid']['n'], tl_rates['mid']['hit_rate'])} | "
              f"tough {_hr_str(tl_rates['tough']['n'], tl_rates['tough']['hit_rate'])}")
        print(f"    lift (soft/tough) = {_fl(tl_lift)}")

        print(f"  Positional DvP:")
        print(f"    soft {_hr_str(pos_rates['soft']['n'], pos_rates['soft']['hit_rate'])} | "
              f"mid {_hr_str(pos_rates['mid']['n'], pos_rates['mid']['hit_rate'])} | "
              f"tough {_hr_str(pos_rates['tough']['n'], pos_rates['tough']['hit_rate'])}")
        print(f"    lift (soft/tough) = {_fl(pos_lift)}")

        lift_adv = round(pos_lift - tl_lift, 3) if (pos_lift is not None and tl_lift is not None) else None
        if lift_adv is None:
            verdict = "INSUFFICIENT_DATA"
        elif lift_adv > 0.08:
            verdict = "KEEP"
        elif lift_adv > 0.03:
            verdict = "MONITOR"
        else:
            verdict = "REVERT"

        adv_str = f"{lift_adv:+.3f}" if lift_adv is not None else "n/a"
        print(f"  Lift advantage (positional over team): {adv_str} → {verdict}")

        results_by_stat[stat] = {
            "team_level":     tl_rates,
            "positional":     pos_rates,
            "lift_advantage": lift_adv,
            "verdict":        verdict,
        }

        # ── Position breakdown for PTS and REB ────────────────────────
        if stat in ("PTS", "REB"):
            print(f"\n  {stat} — Position group breakdown:")
            pos_bd: dict = {}
            for group_name, group_positions in [
                ("perimeter",  PERIMETER),
                ("frontcourt", FRONTCOURT),
            ]:
                sub = df[df["position"].isin(group_positions)]
                n_sub = int(sub[sub[f"best_tier_{stat}"].notna()].__len__())
                if n_sub < PDV_MIN_N:
                    print(f"    {group_name:10s}: n={n_sub} qualified — skipped (< {PDV_MIN_N})")
                    pos_bd[group_name] = {"n_qualified": n_sub, "note": "insufficient"}
                    continue
                pos_sub   = bucket_hit_rates(sub, stat, f"pos_dvp_rating_{stat}")
                team_sub  = bucket_hit_rates(sub, stat, f"opp_def_{stat}")
                ps_lift   = pos_sub.get("lift")
                tl_sub_l  = team_sub.get("lift")
                la_sub    = round(ps_lift - tl_sub_l, 3) if (ps_lift is not None and tl_sub_l is not None) else None
                la_str    = f"{la_sub:+.3f}" if la_sub is not None else "n/a"
                print(f"    {group_name:10s}: positional lift={_fl(ps_lift)} | "
                      f"team lift={_fl(tl_sub_l)} | advantage={la_str}")
                pos_bd[group_name] = {
                    "n_qualified": n_sub,
                    "positional":  pos_sub,
                    "team_level":  team_sub,
                    "lift_advantage": la_sub,
                }
            position_breakdown[stat] = pos_bd

    # ── Overall verdict ────────────────────────────────────────────────
    verdicts = [results_by_stat[s]["verdict"] for s in STAT_COL]
    keep_n    = verdicts.count("KEEP")
    monitor_n = verdicts.count("MONITOR")
    revert_n  = verdicts.count("REVERT")
    if keep_n >= 2:
        overall = "KEEP — positional DvP meaningfully outpredicts team-level for ≥2 stats"
    elif keep_n + monitor_n >= 3:
        overall = "MONITOR — weak advantage; accumulate more data before deciding"
    elif revert_n >= 3:
        overall = "REVERT — positional DvP not improving over team-level; consider simplifying prompt"
    else:
        overall = "MIXED — review per-stat verdicts individually"

    print(f"\n  Overall verdict: {overall}")
    print(f"{'='*60}\n")

    # ── Write JSON ─────────────────────────────────────────────────────
    output = {
        "mode":              "positional-dvp",
        "generated_at":      dt.datetime.now().isoformat(timespec="seconds"),
        "date_range":        {"start": date_min, "end": date_max},
        "total_instances":   total_instances,
        "constants": {
            "PDV_WINDOW":       PDV_WINDOW,
            "PDV_MIN_GAMES":    PDV_MIN_GAMES,
            "PDV_MIN_N":        PDV_MIN_N,
            "PDV_SOFT_PCTILE":  PDV_SOFT_PCTILE,
            "PDV_TOUGH_PCTILE": PDV_TOUGH_PCTILE,
        },
        "results":            results_by_stat,
        "position_breakdown": position_breakdown,
        "overall_verdict":    overall,
    }
    POSITIONAL_DVP_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(POSITIONAL_DVP_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[H8] Results written → {POSITIONAL_DVP_JSON}")
    print(f"\n{'='*60}\n")


# ── Opponent Team Hit Rate Backtest (H15) ─────────────────────────────

def run_opp_team_hit_rate_analysis(picks: list, args) -> None:
    """H15 — Opponent Team Pick Suppression / Lift Backtest.

    Reads picks.json directly. Measures whether certain opponents systematically
    suppress or amplify the system's pick hit rate beyond what opp_defense captures.
    """
    from collections import defaultdict
    sep = "─" * 60

    # Optional date filter
    if getattr(args, "start", None):
        picks = [p for p in picks if p.get("date", "") >= args.start]
    if getattr(args, "end", None):
        picks = [p for p in picks if p.get("date", "") <= args.end]
    if not picks:
        print("[H15] No graded picks after date filter.")
        return

    # ── Step 1: Normalize and enrich pick records ──────────────────────
    enriched = []
    for p in picks:
        opp_raw = str(p.get("opponent", "")).strip().upper()
        opp = _ABBR_NORM_BT.get(opp_raw, opp_raw)
        hit = (p["result"] == "HIT")
        actual   = p.get("actual_value")
        pick_val = p.get("pick_value")
        if actual is not None and pick_val is not None:
            try:
                miss_margin = float(actual) - float(pick_val)
            except (TypeError, ValueError):
                miss_margin = None
        else:
            miss_margin = None
        # injury_event exclusion: field absent in picks.json schema → include all (conservative)
        if p.get("miss_classification") == "injury_event":
            continue
        enriched.append({
            "date":        p.get("date", ""),
            "player":      p.get("player_name", ""),
            "opponent":    opp,
            "prop_type":   p.get("prop_type", ""),
            "pick_value":  pick_val,
            "actual":      actual,
            "hit":         hit,
            "miss_margin": miss_margin if not hit else None,
        })

    if not enriched:
        print("[H15] No picks remain after enrichment.")
        return

    dates    = sorted(set(p["date"] for p in enriched))
    date_min = dates[0]
    date_max = dates[-1]
    total    = len(enriched)
    n_hits   = sum(1 for p in enriched if p["hit"])
    baseline_hr = n_hits / total

    # Per-prop baseline
    prop_baseline: dict = {}
    for prop in ("PTS", "REB", "AST", "3PM"):
        sub = [p for p in enriched if p["prop_type"] == prop]
        prop_baseline[prop] = sum(1 for p in sub if p["hit"]) / len(sub) if sub else None

    print(f"\n{'='*60}")
    print(f"  H15 — Opponent Team Pick Suppression / Lift")
    print(f"  Date range: {date_min} → {date_max}")
    print(f"  Total graded picks: {total}  |  Baseline hit rate: {baseline_hr * 100:.1f}%")
    print(f"{'='*60}")

    # ── Step 2: H15a — Overall hit rate by opponent ────────────────────
    by_opp: dict = defaultdict(list)
    for p in enriched:
        by_opp[p["opponent"]].append(p)

    suppressors: list = []
    amplifiers:  list = []
    neutral:     list = []
    insufficient: list = []

    for opp in sorted(by_opp.keys()):
        opp_picks = by_opp[opp]
        n = len(opp_picks)
        if n < OTH_MIN_PICKS:
            insufficient.append(opp)
            continue
        hits  = sum(1 for p in opp_picks if p["hit"])
        hr    = hits / n
        delta = hr - baseline_hr
        entry = {
            "opponent": opp, "picks": n, "hits": hits,
            "hit_rate": round(hr, 4), "delta": round(delta, 4),
        }
        if delta <= -OTH_SUPPRESSOR_DELTA:
            suppressors.append(entry)
        elif delta >= OTH_AMPLIFIER_DELTA:
            amplifiers.append(entry)
        else:
            neutral.append(entry)

    suppressors.sort(key=lambda x: x["delta"])
    amplifiers.sort(key=lambda x: x["delta"], reverse=True)
    neutral.sort(key=lambda x: x["delta"])

    print(f"\n  H15a — Overall hit rate by opponent (≥{OTH_MIN_PICKS} picks)")
    print(f"  {sep}")
    if suppressors:
        print(f"  SUPPRESSORS (hit rate ≥{OTH_SUPPRESSOR_DELTA * 100:.0f}pp below baseline):")
        for e in suppressors:
            print(f"    {e['opponent']:5s}: {e['hits']}/{e['picks']} picks  "
                  f"{e['hit_rate'] * 100:.1f}%  ({e['delta'] * 100:+.1f}pp)  ← SUPPRESSOR")
    else:
        print(f"  SUPPRESSORS: none (with ≥{OTH_MIN_PICKS} picks)")
    if amplifiers:
        print(f"  AMPLIFIERS (hit rate ≥{OTH_AMPLIFIER_DELTA * 100:.0f}pp above baseline):")
        for e in amplifiers:
            print(f"    {e['opponent']:5s}: {e['hits']}/{e['picks']} picks  "
                  f"{e['hit_rate'] * 100:.1f}%  ({e['delta'] * 100:+.1f}pp)  ← AMPLIFIER")
    else:
        print(f"  AMPLIFIERS: none")
    if neutral:
        print(f"  NEUTRAL (< {OTH_SUPPRESSOR_DELTA * 100:.0f}pp delta, ≥{OTH_MIN_PICKS} picks):")
        for e in neutral:
            print(f"    {e['opponent']:5s}: {e['hits']}/{e['picks']} picks  "
                  f"{e['hit_rate'] * 100:.1f}%  ({e['delta'] * 100:+.1f}pp)")
    if insufficient:
        print(f"  Insufficient sample (<{OTH_MIN_PICKS} picks): {', '.join(sorted(insufficient))}")

    # ── Step 3: H15b — Hit rate by opponent × prop type ───────────────
    print(f"\n  H15b — Hit rate by opponent × prop type (≥{OTH_MIN_PROP_PICKS} picks)")
    print(f"  {sep}")

    h15b_results: dict = {}
    notable_suppressors_b: list = []
    notable_amplifiers_b:  list = []

    for prop in ("PTS", "REB", "AST", "3PM"):
        prop_picks_all = [p for p in enriched if p["prop_type"] == prop]
        pb = prop_baseline.get(prop)
        if pb is None:
            continue
        by_opp_prop: dict = defaultdict(list)
        for p in prop_picks_all:
            by_opp_prop[p["opponent"]].append(p)

        prop_supp: list = []
        prop_ampl: list = []
        for opp in sorted(by_opp_prop.keys()):
            opp_prop_picks = by_opp_prop[opp]
            n = len(opp_prop_picks)
            if n < OTH_MIN_PROP_PICKS:
                continue
            hits  = sum(1 for p in opp_prop_picks if p["hit"])
            hr    = hits / n
            delta = hr - pb
            entry = {
                "opponent": opp, "picks": n, "hits": hits,
                "hit_rate": round(hr, 4), "delta": round(delta, 4),
            }
            if delta <= -OTH_SUPPRESSOR_DELTA:
                prop_supp.append(entry)
                notable_suppressors_b.append({**entry, "prop": prop, "prop_baseline": round(pb, 4)})
            elif delta >= OTH_AMPLIFIER_DELTA:
                prop_ampl.append(entry)
                notable_amplifiers_b.append({**entry, "prop": prop, "prop_baseline": round(pb, 4)})

        prop_supp.sort(key=lambda x: x["delta"])
        prop_ampl.sort(key=lambda x: x["delta"], reverse=True)
        h15b_results[prop] = {
            "baseline":    round(pb, 4),
            "suppressors": prop_supp,
            "amplifiers":  prop_ampl,
        }

    if notable_suppressors_b:
        print(f"  Notable suppressors:")
        for e in sorted(notable_suppressors_b, key=lambda x: x["delta"]):
            print(f"    {e['opponent']:5s} × {e['prop']:3s}: "
                  f"{e['hits']}/{e['picks']}  {e['hit_rate'] * 100:.1f}%  "
                  f"({e['delta'] * 100:+.1f}pp vs {e['prop']} baseline "
                  f"{e['prop_baseline'] * 100:.1f}%)  ← SUPPRESSOR")
    else:
        print(f"  No notable suppressors "
              f"(≥{OTH_SUPPRESSOR_DELTA * 100:.0f}pp below prop baseline, "
              f"≥{OTH_MIN_PROP_PICKS} picks)")
    if notable_amplifiers_b:
        print(f"  Notable amplifiers:")
        for e in sorted(notable_amplifiers_b, key=lambda x: x["delta"], reverse=True):
            print(f"    {e['opponent']:5s} × {e['prop']:3s}: "
                  f"{e['hits']}/{e['picks']}  {e['hit_rate'] * 100:.1f}%  "
                  f"({e['delta'] * 100:+.1f}pp vs {e['prop']} baseline "
                  f"{e['prop_baseline'] * 100:.1f}%)  ← AMPLIFIER")
    else:
        print(f"  No notable amplifiers")

    # ── Step 4: H15c — Miss margin by opponent ─────────────────────────
    print(f"\n  H15c — Miss margin by opponent (misses only, ≥{OTH_MIN_MISSES} misses)")
    print(f"  {sep}")

    miss_picks = [p for p in enriched if not p["hit"] and p["miss_margin"] is not None]
    by_opp_miss: dict = defaultdict(list)
    for p in miss_picks:
        by_opp_miss[p["opponent"]].append(p["miss_margin"])

    floor_compression: list = []
    near_miss_list:    list = []
    all_opp_margins:   list = []

    for opp in sorted(by_opp_miss.keys()):
        margins = by_opp_miss[opp]
        if len(margins) < OTH_MIN_MISSES:
            continue
        mean_m = round(float(np.mean(margins)), 2)
        if mean_m <= OTH_MARGIN_FLOOR_CMP:
            cls = "floor_compression"
            floor_compression.append({"opponent": opp, "n_misses": len(margins), "mean_margin": mean_m})
        elif mean_m > -3.0:
            cls = "near_miss"
            near_miss_list.append({"opponent": opp, "n_misses": len(margins), "mean_margin": mean_m})
        else:
            cls = "other"
        all_opp_margins.append({
            "opponent": opp, "n_misses": len(margins),
            "mean_margin": mean_m, "classification": cls,
        })

    floor_compression.sort(key=lambda x: x["mean_margin"])
    near_miss_list.sort(key=lambda x: x["mean_margin"])

    if floor_compression:
        print(f"  FLOOR COMPRESSION (mean miss margin ≤ {OTH_MARGIN_FLOOR_CMP:.0f}):")
        for e in floor_compression:
            print(f"    {e['opponent']:5s}: mean miss margin {e['mean_margin']:.1f} "
                  f"(n={e['n_misses']} misses)  ← FLOOR COMPRESSION")
    else:
        print(f"  FLOOR COMPRESSION: none (with ≥{OTH_MIN_MISSES} misses)")
    if near_miss_list:
        print(f"  NEAR-MISS VARIANCE (mean miss margin > −3):")
        for e in near_miss_list:
            print(f"    {e['opponent']:5s}: mean miss margin {e['mean_margin']:.1f} "
                  f"(n={e['n_misses']} misses)")

    all_margins = [p["miss_margin"] for p in miss_picks if p["miss_margin"] is not None]
    if all_margins:
        mm_arr = np.array(all_margins)
        dist = {
            "mean":   round(float(np.mean(mm_arr)),            2),
            "median": round(float(np.median(mm_arr)),          2),
            "p25":    round(float(np.percentile(mm_arr, 25)),  2),
            "p75":    round(float(np.percentile(mm_arr, 75)),  2),
        }
        print(f"\n  Overall miss margin distribution (n={len(all_margins)} misses):")
        print(f"    mean={dist['mean']:.1f} | median={dist['median']:.1f} | "
              f"p25={dist['p25']:.1f} | p75={dist['p75']:.1f}")
    else:
        dist = {}

    # ── Verdict ────────────────────────────────────────────────────────
    n_suppressors = len(suppressors)
    n_floor       = len(floor_compression)
    vparts: list  = []
    if n_suppressors > 0:
        vparts.append(
            f"{n_suppressors} opponent(s) qualify as system-wide suppressors "
            f"with ≥{OTH_MIN_PICKS} picks."
        )
    else:
        vparts.append("No system-wide suppressors with sufficient sample.")
    if n_floor > 0:
        vparts.append(
            f"{n_floor} opponent(s) show floor compression "
            f"(mean margin ≤ {OTH_MARGIN_FLOOR_CMP:.0f})."
        )
    if n_suppressors > 0 or n_floor > 0:
        vparts.append("Recommend annotation in nba_season_context.md for confirmed suppressors.")
    else:
        vparts.append("No action required at current sample size.")
    verdict = " ".join(vparts)
    print(f"\n  Verdict: {verdict}")
    print(f"{'='*60}\n")

    # ── Write JSON ─────────────────────────────────────────────────────
    output = {
        "mode":             "opp-team-hit-rate",
        "generated_at":     dt.datetime.now().isoformat(timespec="seconds"),
        "date_range":       {"start": date_min, "end": date_max},
        "total_picks":      total,
        "baseline_hit_rate": round(baseline_hr, 4),
        "baseline_by_prop": {k: round(v, 4) if v is not None else None for k, v in prop_baseline.items()},
        "constants": {
            "OTH_MIN_PICKS":        OTH_MIN_PICKS,
            "OTH_MIN_PROP_PICKS":   OTH_MIN_PROP_PICKS,
            "OTH_MIN_MISSES":       OTH_MIN_MISSES,
            "OTH_SUPPRESSOR_DELTA": OTH_SUPPRESSOR_DELTA,
            "OTH_AMPLIFIER_DELTA":  OTH_AMPLIFIER_DELTA,
            "OTH_MARGIN_FLOOR_CMP": OTH_MARGIN_FLOOR_CMP,
        },
        "h15a_overall": {
            "suppressors":       suppressors,
            "amplifiers":        amplifiers,
            "neutral":           neutral,
            "insufficient_sample": sorted(insufficient),
        },
        "h15b_by_prop":   h15b_results,
        "h15c_miss_margin": {
            "floor_compression":   floor_compression,
            "near_miss":           near_miss_list,
            "all_opponents":       all_opp_margins,
            "overall_distribution": dist,
        },
        "verdict": verdict,
    }
    OPP_TEAM_HIT_RATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OPP_TEAM_HIT_RATE_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[H15] Results written → {OPP_TEAM_HIT_RATE_JSON}")
    print(f"\n{'='*60}\n")


# ── 3PA Volume Gate Backtest (H16) ────────────────────────────────────

def run_3pa_volume_gate_analysis(picks: list, player_log_raw: pd.DataFrame, args) -> None:
    """H16 — 3PA Volume Gate for 3PM Tier Picks.

    Tests whether 3PM tier hit rates are meaningfully higher for players above
    a 3PA-per-game threshold. Uses graded picks from picks.json + L10 avg 3PA
    computed from player_game_log.csv at pick time (no lookahead).
    """
    from collections import defaultdict
    sep = "─" * 60

    today_str = dt.datetime.now().strftime("%Y-%m-%d")

    # ── Filter to 3PM HIT/MISS non-voided picks ───────────────────────
    tpm_picks = [
        p for p in picks
        if p.get("prop_type") == "3PM"
        and p.get("result") in ("HIT", "MISS")
        and not p.get("voided", False)
    ]
    if not tpm_picks:
        print("[H16] No graded 3PM picks found.")
        return

    # ── Build player log lookup: player → sorted list of (date, fg3a, fg3m, dnp) ─
    # player_log_raw already has dnp rows excluded by load_player_log;
    # we need ALL rows (incl. dnp) to correctly exclude them per the spec.
    # Re-read the CSV directly so we have dnp rows too.
    raw_csv_path = DATA / "player_game_log.csv"
    if not raw_csv_path.exists():
        print("[H16] player_game_log.csv not found.")
        return
    full_log = pd.read_csv(raw_csv_path, dtype=str)
    full_log["game_date"] = pd.to_datetime(full_log["game_date"], errors="coerce")
    full_log["fg3a"] = pd.to_numeric(full_log["fg3a"], errors="coerce")
    full_log["fg3m"] = pd.to_numeric(full_log["fg3m"], errors="coerce")
    # Normalise player name
    full_log["player_name_lower"] = full_log["player_name"].str.strip().str.lower()

    # Index: player_name_lower → DataFrame sorted by game_date ascending
    player_log_idx: dict = {}
    for pname, grp in full_log.groupby("player_name_lower"):
        player_log_idx[pname] = grp.sort_values("game_date").reset_index(drop=True)

    # ── Compute avg_3pa_l10 and avg_3pm_l10 per pick at pick time ──────
    enriched = []
    n_excluded_games = 0

    for p in tpm_picks:
        pname_lower = str(p.get("player_name", "")).strip().lower()
        pick_date_str = str(p.get("date", ""))
        try:
            pick_date = pd.Timestamp(pick_date_str)
        except Exception:
            continue

        plog = player_log_idx.get(pname_lower)
        if plog is None:
            n_excluded_games += 1
            continue

        # Games strictly before pick date, non-DNP only
        prior = plog[
            (plog["game_date"] < pick_date) &
            (plog["dnp"].astype(str).str.strip() != "1")
        ]
        if len(prior) < H16_MIN_GAMES:
            n_excluded_games += 1
            continue

        # Take 10 most recent (grp is ascending; tail gives most recent)
        recent = prior.tail(H16_L10_WINDOW)
        avg_3pa = float(recent["fg3a"].mean()) if recent["fg3a"].notna().any() else None
        avg_3pm = float(recent["fg3m"].mean()) if recent["fg3m"].notna().any() else None

        if avg_3pa is None:
            n_excluded_games += 1
            continue

        avg_3pct = (avg_3pm / avg_3pa) if (avg_3pm is not None and avg_3pa > 0) else None

        # Actual fg3a for this specific game (H16c)
        game_rows = plog[plog["game_date"] == pick_date]
        actual_fg3a = None
        if not game_rows.empty:
            val = game_rows.iloc[0]["fg3a"]
            if pd.notna(val):
                actual_fg3a = int(val)

        enriched.append({
            "player":      p.get("player_name", ""),
            "date":        pick_date_str,
            "pick_value":  p.get("pick_value"),
            "result":      p.get("result"),
            "hit":         p.get("result") == "HIT",
            "avg_3pa":     round(avg_3pa, 2),
            "avg_3pm":     round(avg_3pm, 2) if avg_3pm is not None else None,
            "avg_3pct":    round(avg_3pct, 4) if avg_3pct is not None else None,
            "actual_fg3a": actual_fg3a,
        })

    n_total    = len(enriched)
    n_hits     = sum(1 for e in enriched if e["hit"])
    n_misses   = n_total - n_hits

    print(f"\n{'='*70}")
    print(f"  H16 — 3PA Volume Gate Backtest")
    print(f"  Population: {n_total} total 3PM picks  "
          f"({n_hits} HIT, {n_misses} MISS, {n_excluded_games} excluded <{H16_MIN_GAMES} games)")
    print(f"  Analysis date: {today_str}")
    print(f"{'='*70}")

    if n_total == 0:
        print("[H16] No picks survived after L10 computation.")
        return

    # ── H16a: Tier hit rate by avg L10 3PA bucket ─────────────────────
    print(f"\n  --- H16a: Tier Hit Rate by avg L10 3PA Bucket ---\n")

    # Baseline across all qualified picks by tier
    def _tier_hr(subset: list, tier: int) -> tuple:
        """Returns (hit_rate, n) for picks at given pick_value tier."""
        at_tier = [e for e in subset if e.get("pick_value") == tier]
        n = len(at_tier)
        if n == 0:
            return (None, 0)
        hits = sum(1 for e in at_tier if e["hit"])
        return (hits / n, n)

    def _print_tier_row(label: str, subset: list, tier: int, indent: str = "  ") -> dict:
        hr, n = _tier_hr(subset, tier)
        if n == 0:
            print(f"{indent}T{tier}: n=0")
            return {"tier": tier, "hit_rate": None, "n": 0}
        pct_str = f"{hr*100:.1f}%"
        flag = "  [BELOW MIN — n<15]" if n < H16_MIN_N else ""
        print(f"{indent}T{tier}: {pct_str} (n={n}){flag}")
        return {"tier": tier, "hit_rate": round(hr, 4) if hr is not None else None, "n": n}

    print(f"  Baseline (all qualified 3PM picks):")
    baseline_results = {}
    for t in (1, 2, 3):
        baseline_results[t] = _print_tier_row("", enriched, t)

    buckets = {
        "low":  [e for e in enriched if e["avg_3pa"] < H16_VOL_LOW_MAX],
        "mid":  [e for e in enriched if H16_VOL_LOW_MAX <= e["avg_3pa"] < H16_VOL_HIGH_MIN],
        "high": [e for e in enriched if e["avg_3pa"] >= H16_VOL_HIGH_MIN],
    }
    bucket_labels = {
        "low":  f"Low volume (avg 3PA < {H16_VOL_LOW_MAX:.0f}):",
        "mid":  f"Mid volume ({H16_VOL_LOW_MAX:.0f} ≤ avg 3PA < {H16_VOL_HIGH_MIN:.0f}):",
        "high": f"High volume (avg 3PA ≥ {H16_VOL_HIGH_MIN:.0f}):",
    }
    bucket_results: dict = {}
    for bkey in ("low", "mid", "high"):
        sub = buckets[bkey]
        print(f"\n  {bucket_labels[bkey]}")
        bucket_results[bkey] = {}
        for t in (1, 2, 3):
            bucket_results[bkey][t] = _print_tier_row("", sub, t)

    # Key gap: low vs high at T2
    low_t2  = bucket_results["low"][2]
    high_t2 = bucket_results["high"][2]
    print(f"\n  Key gaps (low vs high bucket, T2):")
    if low_t2["hit_rate"] is not None and high_t2["hit_rate"] is not None:
        delta_pp = (high_t2["hit_rate"] - low_t2["hit_rate"]) * 100
        flag = "  ← ACTIONABLE SIGNAL" if abs(delta_pp) >= H16_ACTIONABLE_DELTA * 100 else (
               "  ← WEAK SIGNAL"       if abs(delta_pp) >= H16_WEAK_DELTA * 100      else
               "  ← NOISE")
        print(f"    High − Low delta: {delta_pp:+.1f}pp{flag}")
    else:
        print(f"    Insufficient data in one or both buckets for T2 comparison.")

    # ── H16b: Tier hit rate by 3PA × 3P% profile ──────────────────────
    print(f"\n  --- H16b: Tier Hit Rate by 3PA × 3P% Profile ---\n")

    h16b_picks = [e for e in enriched if e["avg_3pct"] is not None]
    h16b_excluded = n_total - len(h16b_picks)

    if h16b_picks:
        arr_3pa  = np.array([e["avg_3pa"]  for e in h16b_picks])
        arr_3pct = np.array([e["avg_3pct"] for e in h16b_picks])
        print(f"  3PA distribution (n={len(arr_3pa)}): "
              f"median={np.median(arr_3pa):.1f}, "
              f"p25={np.percentile(arr_3pa, 25):.1f}, "
              f"p75={np.percentile(arr_3pa, 75):.1f}")
        print(f"  3P% distribution (n={len(arr_3pct)}): "
              f"median={np.median(arr_3pct)*100:.1f}%, "
              f"p25={np.percentile(arr_3pct, 25)*100:.1f}%, "
              f"p75={np.percentile(arr_3pct, 75)*100:.1f}%")
        print(f"  Volume threshold used: {H16_VOL_HIGH_MIN:.1f}  |  "
              f"Efficiency threshold used: {H16_PCT_HIGH_MIN*100:.1f}%")
        if h16b_excluded > 0:
            print(f"  ({h16b_excluded} picks excluded from H16b: avg_3pa = 0)")

        profiles = {
            "high-vol/high-%": [e for e in h16b_picks
                                 if e["avg_3pa"] >= H16_VOL_HIGH_MIN and e["avg_3pct"] >= H16_PCT_HIGH_MIN],
            "high-vol/low-%":  [e for e in h16b_picks
                                 if e["avg_3pa"] >= H16_VOL_HIGH_MIN and e["avg_3pct"] < H16_PCT_HIGH_MIN],
            "low-vol/high-%":  [e for e in h16b_picks
                                 if e["avg_3pa"] < H16_VOL_HIGH_MIN  and e["avg_3pct"] >= H16_PCT_HIGH_MIN],
            "low-vol/low-%":   [e for e in h16b_picks
                                 if e["avg_3pa"] < H16_VOL_HIGH_MIN  and e["avg_3pct"] < H16_PCT_HIGH_MIN],
        }
        print()
        profile_results: dict = {}
        for pkey, psub in profiles.items():
            n = len(psub)
            if n == 0:
                print(f"  {pkey:<22}: n=0")
                profile_results[pkey] = {"n": 0}
                continue
            hits  = sum(1 for e in psub if e["hit"])
            hr    = hits / n
            hr_t1, n_t1 = _tier_hr(psub, 1)
            hr_t2, n_t2 = _tier_hr(psub, 2)
            flag = "  [BELOW MIN — n<15]" if n < H16_MIN_N else ""
            t1_str = f"T1: {hr_t1*100:.1f}%" if hr_t1 is not None else "T1: n/a"
            t2_str = f"T2: {hr_t2*100:.1f}%" if hr_t2 is not None else "T2: n/a"
            print(f"  {pkey:<22}: {hr*100:.1f}% (n={n})  [{t1_str}, {t2_str}]{flag}")
            profile_results[pkey] = {
                "n": n, "hit_rate": round(hr, 4),
                "t1": {"hit_rate": round(hr_t1, 4) if hr_t1 is not None else None, "n": n_t1},
                "t2": {"hit_rate": round(hr_t2, 4) if hr_t2 is not None else None, "n": n_t2},
            }
    else:
        print("  No picks with valid avg_3pct — fg3a may be zero for all picks.")
        profile_results = {}

    # ── H16c: Game-level 3PA floor (post-hoc) ──────────────────────────
    print(f"\n  --- H16c: Game-Level 3PA Floor (post-hoc mechanism check) ---\n")

    h16c_picks = [e for e in enriched if e["actual_fg3a"] is not None]
    if h16c_picks:
        floor_results: dict = {}
        for floor in (1, 2, 3, 4, 5):
            at_or_above = [e for e in h16c_picks if e["actual_fg3a"] >= floor]
            n = len(at_or_above)
            if n < H16_MIN_N_H16C:
                flag = f"  (n={n}, below {H16_MIN_N_H16C}-pick minimum)"
                print(f"  3PA ≥ {floor}: —{flag}")
                floor_results[floor] = {"hit_rate": None, "n": n}
            else:
                hits = sum(1 for e in at_or_above if e["hit"])
                hr   = hits / n
                print(f"  3PA ≥ {floor}: {hr*100:.1f}% hit rate (n={n})")
                floor_results[floor] = {"hit_rate": round(hr, 4), "n": n}

        # Contrast case: 3PA = 0
        zero_pa = [e for e in h16c_picks if e["actual_fg3a"] == 0]
        n_zero = len(zero_pa)
        if n_zero >= H16_MIN_N_H16C:
            hits_zero = sum(1 for e in zero_pa if e["hit"])
            hr_zero = hits_zero / n_zero
            print(f"  3PA = 0: {hr_zero*100:.1f}% hit rate (n={n_zero})  [contrast case]")
            floor_results[0] = {"hit_rate": round(hr_zero, 4), "n": n_zero}
        else:
            print(f"  3PA = 0: n={n_zero} (below {H16_MIN_N_H16C}-pick minimum)  [contrast case]")
            floor_results[0] = {"hit_rate": None, "n": n_zero}

        print(f"\n  NOTE: H16c is post-hoc (actual 3PA unknown pre-game). Validates mechanism only.")
    else:
        print("  No game-level fg3a data found — H16c skipped.")
        floor_results = {}

    # ── Verdict guidance ───────────────────────────────────────────────
    print(f"\n  --- Verdict Guidance ---\n")
    print(f"  H16a actionable signal: low-bucket T2 hit rate ≥{H16_ACTIONABLE_DELTA*100:.0f}pp below high-bucket "
          f"with ≥{H16_MIN_N} picks each")
    print(f"  H16a weak signal: {H16_WEAK_DELTA*100:.0f}–{H16_ACTIONABLE_DELTA*100-1:.0f}pp gap → annotation only "
          f"(avg_3pa_l10 as context, no gate)")
    print(f"  H16a noise: <{H16_WEAK_DELTA*100:.0f}pp gap or insufficient sample → close")
    print(f"  H16b actionable: low-vol underperforms high-vol by ≥{H16_ACTIONABLE_DELTA*100:.0f}pp "
          f"regardless of 3P% → volume is dominant gate")
    print(f"  H16c actionable: hit rate rises ≥20pp above a specific 3PA floor → validates mechanism")
    print(f"\n{'='*70}\n")

    # ── Write JSON ─────────────────────────────────────────────────────
    output = {
        "mode":           "3pa-volume-gate",
        "generated_at":   dt.datetime.now().isoformat(timespec="seconds"),
        "population": {
            "total_3pm_picks": n_total,
            "hits":            n_hits,
            "misses":          n_misses,
            "excluded_lt5_games": n_excluded_games,
        },
        "constants": {
            "H16_L10_WINDOW":       H16_L10_WINDOW,
            "H16_MIN_GAMES":        H16_MIN_GAMES,
            "H16_MIN_N":            H16_MIN_N,
            "H16_VOL_LOW_MAX":      H16_VOL_LOW_MAX,
            "H16_VOL_HIGH_MIN":     H16_VOL_HIGH_MIN,
            "H16_PCT_HIGH_MIN":     H16_PCT_HIGH_MIN,
            "H16_ACTIONABLE_DELTA": H16_ACTIONABLE_DELTA,
            "H16_WEAK_DELTA":       H16_WEAK_DELTA,
        },
        "h16a_baseline": {t: baseline_results[t] for t in (1, 2, 3)},
        "h16a_buckets":  bucket_results,
        "h16b_profiles": profile_results,
        "h16c_floors":   floor_results,
    }
    THREE_PA_VOLUME_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(THREE_PA_VOLUME_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[H16] Results written → {THREE_PA_VOLUME_JSON}")
    print(f"\n{'='*70}\n")


# ── Spread Context mode constants (H17) ──────────────────────────────
H17_MIN_N          = 10    # min picks per cell for a reportable hit rate (Layer 2)
H17_MIN_N_OVERALL  = 5     # min picks per bucket for Layer 1 / gradient
H17_THRESH_MIN     = 4.0   # start of threshold search range
H17_THRESH_MAX     = 12.0  # end of threshold search range
H17_THRESH_STEP    = 0.5   # step size for threshold search
SPREAD_CONTEXT_JSON = DATA / "backtest_spread_context.json"

# Bucket definitions: (label, lo_inclusive, hi_exclusive)
_H17_BUCKETS = [
    ("0-3",   0.0,  3.5),
    ("4-6",   3.5,  6.5),
    ("7-9",   6.5,  9.5),
    ("10-13", 9.5, 13.5),
    ("14+",  13.5, float("inf")),
]


def _h17_bucket(spread_abs: float) -> str | None:
    """Return bucket label for a given spread_abs value, or None if negative."""
    if spread_abs < 0:
        return None
    for label, lo, hi in _H17_BUCKETS:
        if lo <= spread_abs < hi:
            return label
    return "14+"


def run_spread_context_analysis(picks: list, master: pd.DataFrame, args) -> None:
    """H17 — Spread Context vs. Tier Hit Rate Backtest.

    Tests whether pregame spread magnitude predicts tier pick hit rate, and
    whether the relationship differs meaningfully across prop types.
    """
    today_str = dt.date.today().isoformat()
    sep = "─" * 70

    # Optional date filter
    if getattr(args, "start", None):
        picks = [p for p in picks if p.get("date", "") >= args.start]
    if getattr(args, "end", None):
        picks = [p for p in picks if p.get("date", "") <= args.end]
    if not picks:
        print("[H17] No graded picks after date filter.")
        return

    # ── Build spread lookup from nba_master.csv ────────────────────────
    # Key: (game_date_str, norm_team) → spread_abs
    spread_lookup: dict[tuple[str, str], float] = {}
    if master is not None and not master.empty:
        for _, row in master.iterrows():
            gd = str(row["game_date"])[:10]  # YYYY-MM-DD
            home = _ABBR_NORM_BT.get(str(row.get("home_team_abbrev", "")).strip().upper(),
                                      str(row.get("home_team_abbrev", "")).strip().upper())
            away = _ABBR_NORM_BT.get(str(row.get("away_team_abbrev", "")).strip().upper(),
                                      str(row.get("away_team_abbrev", "")).strip().upper())
            try:
                spread_abs = abs(float(row["home_spread"]))
            except (TypeError, ValueError):
                continue
            if spread_abs != spread_abs:  # NaN check
                continue
            spread_lookup[(gd, home)] = spread_abs
            spread_lookup[(gd, away)] = spread_abs

    # ── Enrich picks with spread_abs ──────────────────────────────────
    enriched = []
    n_excluded = 0
    for p in picks:
        date_str = str(p.get("date", ""))[:10]
        opp_raw  = str(p.get("opponent", "")).strip().upper()
        team_raw = str(p.get("team", "")).strip().upper()
        opp      = _ABBR_NORM_BT.get(opp_raw,  opp_raw)
        team     = _ABBR_NORM_BT.get(team_raw, team_raw)

        # Try matching by team first, then opponent
        spread_abs = spread_lookup.get((date_str, team))
        if spread_abs is None:
            spread_abs = spread_lookup.get((date_str, opp))

        if spread_abs is None:
            n_excluded += 1
            continue

        bucket = _h17_bucket(spread_abs)
        hit    = (p["result"] == "HIT")
        enriched.append({
            "date":       date_str,
            "player":     p.get("player_name", ""),
            "prop_type":  p.get("prop_type", ""),
            "pick_value": p.get("pick_value"),
            "actual":     p.get("actual_value"),
            "hit":        hit,
            "spread_abs": spread_abs,
            "bucket":     bucket,
        })

    if not enriched:
        print("[H17] No picks could be matched to spread data.")
        return

    total    = len(enriched)
    n_hits   = sum(1 for p in enriched if p["hit"])
    baseline = n_hits / total

    prop_counts = {pt: sum(1 for p in enriched if p["prop_type"] == pt)
                   for pt in ("PTS", "REB", "AST", "3PM")}

    # ── Print header ───────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  H17 — Spread Context Backtest")
    print(f"{'='*70}")
    print(f"  Population: {total} total picks  "
          f"(PTS: {prop_counts['PTS']}, REB: {prop_counts['REB']}, "
          f"AST: {prop_counts['AST']}, 3PM: {prop_counts['3PM']})")
    print(f"  Excluded (no spread match): {n_excluded}")
    print(f"  Analysis date: {today_str}")

    # ── Layer 1: Overall hit rate by spread bucket ─────────────────────
    print(f"\n{sep}")
    print(f"  Layer 1: Overall Hit Rate by Spread Bucket")
    print(f"{sep}")
    print(f"  {'Bucket':<10} | {'Hit Rate':>8} | {'n':>6} | {'vs. Baseline':>12}")
    print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*6}-+-{'-'*12}")

    bucket_results: dict[str, dict] = {}
    for label, _, _ in _H17_BUCKETS:
        sub  = [p for p in enriched if p["bucket"] == label]
        n    = len(sub)
        if n >= H17_MIN_N_OVERALL:
            hr   = sum(1 for p in sub if p["hit"]) / n
            delta = hr - baseline
            sign  = "+" if delta >= 0 else ""
            hr_str    = f"{hr*100:.1f}%"
            delta_str = f"{sign}{delta*100:.1f}pp"
        else:
            hr   = None
            delta = None
            hr_str    = f"n={n} (below min)"
            delta_str = "—"
        print(f"  {label:<10} | {hr_str:>8} | {n:>6} | {delta_str:>12}")
        bucket_results[label] = {"hit_rate": hr, "n": n, "vs_baseline": delta}

    print(f"  {'Baseline':<10} | {baseline*100:>7.1f}% | {total:>6} |")

    # ── Layer 2: Hit rate by prop type × spread bucket ─────────────────
    print(f"\n{sep}")
    print(f"  Layer 2: Hit Rate by Prop Type × Spread Bucket")
    print(f"{sep}")
    bucket_labels = [b[0] for b in _H17_BUCKETS]
    col_w = 11
    header = f"  {'':8} | " + " | ".join(f"{b:>{col_w}}" for b in bucket_labels)
    print(header)
    print(f"  {'-'*8}-+-" + "-+-".join("-" * col_w for _ in bucket_labels))

    prop_bucket_results: dict[str, dict[str, dict]] = {}
    for prop in ("PTS", "REB", "AST", "3PM"):
        cells = []
        prop_bucket_results[prop] = {}
        for label, _, _ in _H17_BUCKETS:
            sub = [p for p in enriched if p["prop_type"] == prop and p["bucket"] == label]
            n   = len(sub)
            if n >= H17_MIN_N:
                hr  = sum(1 for p in sub if p["hit"]) / n
                cell_str = f"{hr*100:.1f}%({n})"
                hr_val = hr
            else:
                cell_str = f"n={n}(<min)"
                hr_val = None
            cells.append(f"{cell_str:>{col_w}}")
            prop_bucket_results[prop][label] = {"hit_rate": hr_val, "n": n}
        print(f"  {prop:<8} | " + " | ".join(cells))

    print(f"\n  [Cells below {H17_MIN_N}-pick minimum shown as n=N(<min)]")

    # ── Layer 3: Threshold validation ─────────────────────────────────
    print(f"\n{sep}")
    print(f"  Layer 3: Threshold Validation")
    print(f"{sep}")

    # Reproduce current binary split at 6.0 (competitive ≤6 vs blowout >6)
    comp   = [p for p in enriched if p["spread_abs"] <= 6.0]
    blow   = [p for p in enriched if p["spread_abs"] >  6.0]
    comp_hr = sum(1 for p in comp if p["hit"]) / len(comp) if comp else None
    blow_hr = sum(1 for p in blow if p["hit"]) / len(blow) if blow else None
    gap_cur = (comp_hr - blow_hr) if (comp_hr is not None and blow_hr is not None) else None

    print(f"\n  Current binary split (≤6 vs >6):")
    if comp_hr is not None:
        print(f"    Competitive (≤6): {comp_hr*100:.1f}% (n={len(comp)})")
    if blow_hr is not None:
        print(f"    Blowout     (>6): {blow_hr*100:.1f}% (n={len(blow)})")
    if gap_cur is not None:
        print(f"    Gap: {gap_cur*100:.1f}pp")

    # Best single threshold search
    threshold_results = []
    thresh = H17_THRESH_MIN
    while thresh <= H17_THRESH_MAX + 1e-9:
        below = [p for p in enriched if p["spread_abs"] <= thresh]
        above = [p for p in enriched if p["spread_abs"] >  thresh]
        if len(below) >= H17_MIN_N_OVERALL and len(above) >= H17_MIN_N_OVERALL:
            hr_below = sum(1 for p in below if p["hit"]) / len(below)
            hr_above = sum(1 for p in above if p["hit"]) / len(above)
            gap      = abs(hr_below - hr_above)
            threshold_results.append({
                "threshold": round(thresh, 1),
                "hr_below": hr_below,
                "n_below":  len(below),
                "hr_above": hr_above,
                "n_above":  len(above),
                "gap":      gap,
            })
        thresh += H17_THRESH_STEP

    threshold_results.sort(key=lambda x: x["gap"], reverse=True)

    print(f"\n  Best single threshold search ({H17_THRESH_MIN}–{H17_THRESH_MAX}, step {H17_THRESH_STEP}):")
    print(f"  ({len(threshold_results)} thresholds tested)")
    for rank, r in enumerate(threshold_results[:3], 1):
        sign = "+" if r["hr_below"] >= r["hr_above"] else ""
        print(f"    Rank {rank}: split at {r['threshold']:.1f} → gap {r['gap']*100:.1f}pp  "
              f"(≤{r['threshold']:.1f}: {r['hr_below']*100:.1f}% n={r['n_below']} | "
              f">{r['threshold']:.1f}: {r['hr_above']*100:.1f}% n={r['n_above']})")

    # ── Continuous gradient ────────────────────────────────────────────
    print(f"\n{sep}")
    print(f"  Continuous Gradient (all props, ±0.5 around each integer)")
    print(f"{sep}")
    print(f"  {'spread_abs':>10} | {'hit_rate':>8} | {'n':>5}")
    print(f"  {'-'*10}-+-{'-'*8}-+-{'-'*5}")

    gradient_rows = []
    for sa in range(0, 21):
        sub = [p for p in enriched if abs(p["spread_abs"] - sa) < 0.5]
        n   = len(sub)
        if n >= H17_MIN_N_OVERALL:
            hr  = sum(1 for p in sub if p["hit"]) / n
            print(f"  {sa:>10} | {hr*100:>7.1f}% | {n:>5}")
            gradient_rows.append({"spread_abs": sa, "hit_rate": hr, "n": n})
        else:
            print(f"  {sa:>10} | {'—':>8} | {n:>5}  (below min)")
            gradient_rows.append({"spread_abs": sa, "hit_rate": None, "n": n})

    print(f"\n{'='*70}\n")

    # ── Write JSON output ──────────────────────────────────────────────
    output = {
        "analysis_date":    today_str,
        "total_picks":      total,
        "n_excluded":       n_excluded,
        "baseline_hit_rate": baseline,
        "prop_counts":      prop_counts,
        "layer1_overall":   bucket_results,
        "layer2_by_prop":   prop_bucket_results,
        "layer3_threshold": {
            "current_split": {
                "threshold":   6.0,
                "hr_competitive": comp_hr,
                "n_competitive":  len(comp),
                "hr_blowout":     blow_hr,
                "n_blowout":      len(blow),
                "gap":            gap_cur,
            },
            "best_thresholds": threshold_results[:3],
            "all_thresholds":  threshold_results,
        },
        "gradient": gradient_rows,
    }
    SPREAD_CONTEXT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(SPREAD_CONTEXT_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[H17] Results written → {SPREAD_CONTEXT_JSON}")
    print(f"\n{'='*70}\n")


# ── Elite Opposing Rebounder REB Suppression (H14) ────────────────────

def build_opp_rebounder_lookup(
    player_log: pd.DataFrame,
    team_log: pd.DataFrame,
) -> dict:
    """
    H14 — Build two lookups for opposing rebounder context.
    Returns a dict with two keys:
      "elite_rebounder": {(game_id_str, team_upper): max_opp_reb_avg}
          For each game x team, the maximum rolling REB avg among any opposing player
          in that game (using only prior games for the rolling avg — no lookahead).
          "team" here is the PLAYER's team — we look up the OPPONENT's top rebounder.
      "opp_team_reb": {(game_id_str, team_upper): opp_team_reb_avg}
          For each game x team, the opponent's rolling total REB (or OREB when available).
          Uses team_game_log for team totals.
    player_log is sorted ascending by (player_name, game_date) — use this for rolling avgs.
    team_log is sorted ascending by game_date.
    """
    # ── Part A: Elite individual rebounder lookup ─────────────────────────
    # For each player-game in the full (non-whitelisted) player_log,
    # compute their rolling REB avg using only prior games.
    # Then for each (game_id, opposing_team), find the max rolling avg.
    # Use all players in log (not just whitelist) — we need opponent players too
    all_log = player_log.copy()
    all_log["game_id_str"] = (
        all_log["game_id"].astype(str).str.split(".").str[0].str.strip()
    )
    all_log["team_upper"] = all_log["team_abbrev"].str.upper().str.strip()
    all_log["opp_upper"]  = all_log["opp_abbrev"].str.upper().str.strip()

    # Rolling REB avg per player (shift=1, no lookahead), min H14_OPP_MIN_GAMES games
    all_log["rolling_reb_avg"] = (
        all_log.groupby("player_name")["reb"]
        .transform(
            lambda s: s.shift(1).rolling(H14_OPP_REB_WINDOW, min_periods=H14_OPP_MIN_GAMES).mean()
        )
    )

    # For each (game_id, team_that_is_facing_this_player), find max rolling_reb_avg
    # i.e., for game G, player P on team T: opp_team = T → look at all players on opp_team
    # group by (game_id_str, opp_upper) to get max rebounder on the opposing side
    elite_lookup: dict = {}
    for (gid, opp), grp in all_log.groupby(["game_id_str", "opp_upper"]):
        max_avg = grp["rolling_reb_avg"].max()
        if pd.notna(max_avg):
            # Key: (game_id, player's team) — player's team is the opp_upper here
            # because we want "the best rebounder facing player on team X in game G"
            elite_lookup[(gid, str(opp).upper())] = float(max_avg)

    # ── Part B: Team OREB rate lookup ─────────────────────────────────────
    # team_game_log has team_reb (total team rebounds) per team per game.
    # Proxy for OREB rate: we don't have separate OREB/DREB columns in team_game_log.
    # Use total team rebounds as a proxy signal instead — higher total REB = more dominant.
    # If team_log has oreb or dreb columns use them; otherwise skip this signal.
    oreb_lookup: dict = {}
    if not team_log.empty:
        tl = team_log.copy()
        tl["game_id_str"] = (
            tl["game_id"].astype(str).str.split(".").str[0].str.strip()
        )
        tl["team_upper"] = tl["team_abbrev"].str.upper().str.strip()
        tl["opp_upper"]  = tl["opp_abbrev"].str.upper().str.strip()

        # Check if oreb column exists
        if "team_oreb" in tl.columns:
            tl["team_oreb"] = pd.to_numeric(tl["team_oreb"], errors="coerce").fillna(0)
            tl["team_dreb"] = pd.to_numeric(tl.get("team_dreb", 0), errors="coerce").fillna(0)
            # Rolling OREB avg per team (shift=1)
            tl["rolling_oreb"] = (
                tl.groupby("team_upper")["team_oreb"]
                .transform(
                    lambda s: s.shift(1).rolling(H14_OREB_WINDOW, min_periods=5).mean()
                )
            )
            for (gid, team), grp in tl.groupby(["game_id_str", "team_upper"]):
                oreb_val = grp["rolling_oreb"].iloc[0] if len(grp) > 0 else None
                if pd.notna(oreb_val):
                    # Key: player is on the OPPONENT of this team
                    opp = grp["opp_upper"].iloc[0] if len(grp) > 0 else None
                    if opp:
                        oreb_lookup[(gid, str(opp).upper())] = float(oreb_val)
        else:
            # Fall back to total team_reb as proxy
            tl["team_reb"] = pd.to_numeric(tl["team_reb"], errors="coerce").fillna(0)
            tl["rolling_reb"] = (
                tl.groupby("team_upper")["team_reb"]
                .transform(
                    lambda s: s.shift(1).rolling(H14_OREB_WINDOW, min_periods=5).mean()
                )
            )
            for (gid, team), grp in tl.groupby(["game_id_str", "team_upper"]):
                reb_val = grp["rolling_reb"].iloc[0] if len(grp) > 0 else None
                if pd.notna(reb_val):
                    opp = grp["opp_upper"].iloc[0] if len(grp) > 0 else None
                    if opp:
                        oreb_lookup[(gid, str(opp).upper())] = float(reb_val)

    print(f"[backtest] H14 lookups: elite_rebounder={len(elite_lookup):,} | "
          f"oreb={len(oreb_lookup):,}")
    return {"elite_rebounder": elite_lookup, "opp_team_reb": oreb_lookup}


def run_elite_opp_rebounder_analysis(
    player_log: pd.DataFrame,
    team_log: pd.DataFrame,
    args,
) -> None:
    """
    H14 — Elite opposing rebounder REB suppression.
    Tests whether the presence of an elite opposing rebounder (rolling REB avg >= threshold)
    or high opponent team REB total suppresses whitelisted players' REB tier hit rates.
    """
    window = getattr(args, "window", None) or ROLLING_WINDOW
    print(f"[backtest] H14 elite-opp-rebounder | window={window} | "
          f"thresholds={H14_ELITE_REB_THRESHOLDS}")

    # ── Step 1: Build opponent rebounder lookups ──────────────────────────
    lookups = build_opp_rebounder_lookup(player_log, team_log)
    elite_lookup = lookups["elite_rebounder"]
    oreb_lookup  = lookups["opp_team_reb"]

    # ── Step 2: Compute REB best tier for whitelisted players ─────────────
    df = add_best_tiers(player_log, window=window)
    df["game_id_str"] = df["game_id"].astype(str).str.split(".").str[0].str.strip()
    df["team_upper"]  = df["team_abbrev"].str.upper().str.strip()

    # Join elite rebounder value for this player's game
    df["opp_max_reb_avg"] = df.apply(
        lambda r: elite_lookup.get((r["game_id_str"], r["team_upper"])),
        axis=1,
    )
    df["opp_team_reb_avg"] = df.apply(
        lambda r: oreb_lookup.get((r["game_id_str"], r["team_upper"])),
        axis=1,
    )

    # Qualified REB instances only
    qualified = df[
        df["best_tier_REB"].notna() &
        df["hit_actual_REB"].notna()
    ].copy()
    total_n = len(qualified)
    baseline_hits = int(qualified["hit_actual_REB"].sum())
    baseline_rate = round(baseline_hits / total_n, 4) if total_n > 0 else None
    print(f"[backtest] H14 qualified REB instances: {total_n:,} | baseline: {baseline_rate}")

    # ── Step 3: H14a — Elite individual rebounder analysis ───────────────
    H14a_results: dict = {}
    for thresh in H14_ELITE_REB_THRESHOLDS:
        has_data   = qualified["opp_max_reb_avg"].notna()
        elite_mask = has_data & (qualified["opp_max_reb_avg"] >= thresh)
        other_mask = has_data & (qualified["opp_max_reb_avg"] <  thresh)
        for label, mask in [("elite_present", elite_mask), ("no_elite", other_mask)]:
            sub  = qualified[mask]
            n    = len(sub)
            h    = int(sub["hit_actual_REB"].sum()) if n > 0 else 0
            hr   = round(h / n, 4) if n > 0 else None
            lift = round(hr / baseline_rate, 4) if (hr is not None and baseline_rate) else None
            H14a_results[f"thresh_{int(thresh)}_{label}"] = {
                "threshold": thresh, "label": label,
                "n": n, "hits": h, "hit_rate": hr, "lift": lift,
            }

    # ── Step 4: H14b — Team OREB rate analysis ────────────────────────────
    H14b_results: dict = {}
    if qualified["opp_team_reb_avg"].notna().sum() >= H14_MIN_N:
        median_oreb = qualified["opp_team_reb_avg"].median()
        high_mask   = qualified["opp_team_reb_avg"] >= median_oreb
        low_mask    = qualified["opp_team_reb_avg"] <  median_oreb
        for label, mask in [("high_opp_reb", high_mask), ("low_opp_reb", low_mask)]:
            sub  = qualified[mask & qualified["opp_team_reb_avg"].notna()]
            n    = len(sub)
            h    = int(sub["hit_actual_REB"].sum()) if n > 0 else 0
            hr   = round(h / n, 4) if n > 0 else None
            lift = round(hr / baseline_rate, 4) if (hr is not None and baseline_rate) else None
            H14b_results[label] = {
                "n": n, "hits": h, "hit_rate": hr, "lift": lift,
                "median_split": float(median_oreb) if pd.notna(median_oreb) else None,
            }

    # ── Step 5: Verdict ───────────────────────────────────────────────────
    # Use T10.0 threshold (middle) as primary verdict threshold
    elite_key   = "thresh_10_elite_present"
    noelite_key = "thresh_10_no_elite"
    ep = H14a_results.get(elite_key, {})
    ne = H14a_results.get(noelite_key, {})
    ep_hr = ep.get("hit_rate")
    ne_hr = ne.get("hit_rate")
    ep_n  = ep.get("n", 0)
    if ep_n < H14_MIN_N or ep_hr is None or ne_hr is None:
        verdict  = "insufficient_sample"
        reason   = f"elite_present (thresh=10) n={ep_n} < {H14_MIN_N}"
        rule_rec = "Insufficient sample. Rerun at end of season or next season."
    else:
        delta = round(ne_hr - ep_hr, 4)
        if delta >= 0.08:
            verdict  = "confirmed_suppression"
            reason   = f"no_elite {ne_hr*100:.1f}% vs elite_present {ep_hr*100:.1f}% (delta={delta*100:.1f}pp >= 8pp)"
            rule_rec = "Consider REB tier step-down or confidence penalty when opp has player with rolling REB avg >= 10.0."
        elif delta >= 0.04:
            verdict  = "weak_signal"
            reason   = f"delta={delta*100:.1f}pp (4-8pp range)"
            rule_rec = "Weak signal. Monitor; do not add directive rule yet."
        else:
            verdict  = "no_signal"
            reason   = f"delta={delta*100:.1f}pp < 4pp"
            rule_rec = "Hypothesis not confirmed. No rule change."

    # ── Step 6: Print report ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  H14 — ELITE OPPOSING REBOUNDER REB SUPPRESSION")
    print(f"  Baseline REB hit rate: {(baseline_rate or 0)*100:.1f}% (n={total_n:,})")
    print(f"  Date range: {player_log['game_date'].min().date()} "
          f"→ {player_log['game_date'].max().date()}")
    print(f"{'='*65}")
    print(f"\n  H14a — Elite individual rebounder (rolling avg >= threshold):")
    for thresh in H14_ELITE_REB_THRESHOLDS:
        ep_res = H14a_results.get(f"thresh_{int(thresh)}_elite_present", {})
        ne_res = H14a_results.get(f"thresh_{int(thresh)}_no_elite", {})
        ep_hr_s = f"{(ep_res.get('hit_rate') or 0)*100:.1f}%" if ep_res.get("hit_rate") else "n/a"
        ne_hr_s = f"{(ne_res.get('hit_rate') or 0)*100:.1f}%" if ne_res.get("hit_rate") else "n/a"
        lift_s  = f"lift={ep_res.get('lift'):.3f}" if ep_res.get("lift") else "lift=n/a"
        print(f"    thresh >= {thresh}: elite n={ep_res.get('n',0):<4} hr={ep_hr_s}  "
              f"no_elite n={ne_res.get('n',0):<4} hr={ne_hr_s}  {lift_s}")
    if H14b_results:
        print(f"\n  H14b — Team OREB/REB rate (median split):")
        for label, res in H14b_results.items():
            hr_s   = f"{(res.get('hit_rate') or 0)*100:.1f}%" if res.get("hit_rate") else "n/a"
            lift_s = f"lift={res.get('lift'):.3f}" if res.get("lift") else "lift=n/a"
            print(f"    {label:<18} n={res.get('n',0):<4} hr={hr_s}  {lift_s}")
    print(f"\n  Verdict: {verdict.upper()}")
    print(f"  Reason:  {reason}")
    print(f"  Rule recommendation: {rule_rec}")
    print(f"\n{'='*65}\n")

    # ── Step 7: Write JSON ────────────────────────────────────────────────
    out = {
        "generated_at":        dt.date.today().isoformat(),
        "mode":                "elite-opp-rebounder",
        "hypothesis":          "Elite opposing rebounder (rolling REB avg >= threshold) suppresses REB tier hit rate",
        "rolling_window":      window,
        "date_range": {
            "start": str(player_log["game_date"].min().date()),
            "end":   str(player_log["game_date"].max().date()),
        },
        "total_reb_instances": total_n,
        "baseline_hit_rate":   baseline_rate,
        "H14a_individual":     H14a_results,
        "H14b_team_reb":       H14b_results,
        "verdict":             verdict,
        "verdict_reason":      reason,
        "rule_recommendation": rule_rec,
    }
    out_path = Path(args.output) if getattr(args, "output", None) else H14_JSON
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[backtest] H14 results → {out_path}")


# ── Losing-Side AST Suppression Backtest (H20) ────────────────────────

def run_losing_side_ast_analysis(
    player_log: pd.DataFrame,
    master_df: pd.DataFrame,
    args,
) -> None:
    """
    H20 — Losing-side blowout AST suppression.

    Tests whether pre-game underdog spread_abs >= 10 suppresses AST tier hit rate.
    Segments by spread magnitude, AST tier, and player role (primary/secondary ball-handler).
    Uses signed pre-game spread (positive = underdog) from nba_master.csv.
    """
    if master_df.empty:
        print("[backtest] WARNING: master_df is empty — cannot run H20.")
        return

    window = getattr(args, "window", None) or ROLLING_WINDOW
    print(f"[backtest] H20 losing-side-ast | window={window} | "
          f"underdog thresholds={H20_UNDERDOG_THRESHOLDS}")

    # ── Step 1: Build signed spread lookup ───────────────────────────────
    # Same inline pattern as H19 — {(gid, team_upper): signed_spread}
    spread_map: dict = {}
    for _, row in master_df.iterrows():
        gid  = str(row.get("game_id", "")).strip()
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        hs   = row.get("home_spread")
        as_  = row.get("away_spread")
        for team, spread in [(home, hs), (away, as_)]:
            if team and not pd.isna(spread):
                spread_map[(gid, team)] = float(spread)

    df = player_log.copy()
    df["_gid"]        = df["game_id"].astype(str).str.split(".").str[0].str.strip()
    df["_team_upper"] = df["team_abbrev"].str.upper().str.strip()

    df["signed_spread"] = df.apply(
        lambda r: spread_map.get((r["_gid"], r["_team_upper"])),
        axis=1,
    )
    df["is_underdog"] = df["signed_spread"].apply(
        lambda s: bool(s > 0) if (s is not None and not pd.isna(s)) else None
    )
    df["spread_abs_h20"] = df["signed_spread"].apply(
        lambda s: abs(s) if (s is not None and not pd.isna(s)) else None
    )

    # ── Step 2: Rolling AST avg for role classification ──────────────────
    # No-lookahead: shift(1) before rolling
    df["rolling_ast_avg"] = (
        df.groupby("player_name")["ast"]
        .transform(lambda s: s.shift(1).rolling(window, min_periods=5).mean())
    )

    # ── Step 3: Compute AST best tier + hit ──────────────────────────────
    df = add_best_tiers(df, window=window)
    qualified = df[df["best_tier_AST"].notna() & df["hit_actual_AST"].notna()].copy()

    print(f"[backtest] H20 qualified AST instances: {len(qualified):,}")

    # ── Step 4: Classify spread bucket ───────────────────────────────────
    def classify_bucket(row) -> str:
        s = row["signed_spread"]
        a = row["spread_abs_h20"]
        if s is None or pd.isna(s) or a is None or pd.isna(a):
            return "no_spread_data"
        if not row["is_underdog"]:
            return "fav_or_even"
        if a < H20_UNDERDOG_THRESHOLDS[0]:   # < 6.5
            return "fav_or_even"
        if a < H20_UNDERDOG_THRESHOLDS[1]:   # 6.5–9.9
            return "underdog_6_9"
        if a < H20_UNDERDOG_THRESHOLDS[2]:   # 10.0–14.9
            return "underdog_10_14"
        return "underdog_15plus"             # >= 15.0

    qualified["spread_bucket"] = qualified.apply(classify_bucket, axis=1)
    qualified["underdog_10plus"] = qualified["spread_bucket"].isin(
        ["underdog_10_14", "underdog_15plus"]
    )

    # ── Step 5: Primary results — hit rate by spread bucket ──────────────
    baseline_mask = qualified["spread_bucket"] == "fav_or_even"
    baseline_n    = int(baseline_mask.sum())
    baseline_hits = int(qualified.loc[baseline_mask, "hit_actual_AST"].sum())
    baseline_rate = round(baseline_hits / baseline_n, 4) if baseline_n > 0 else None

    bucket_results: dict = {
        "fav_or_even": {
            "n": baseline_n, "hits": baseline_hits, "hit_rate": baseline_rate
        }
    }
    for bucket in ("underdog_6_9", "underdog_10_14", "underdog_15plus"):
        sub = qualified[qualified["spread_bucket"] == bucket]
        n   = len(sub)
        h   = int(sub["hit_actual_AST"].sum()) if n > 0 else 0
        hr  = round(h / n, 4) if n > 0 else None
        lift = round(hr / baseline_rate, 4) if (hr is not None and baseline_rate) else None
        bucket_results[bucket] = {"n": n, "hits": h, "hit_rate": hr, "lift": lift}

    sub10 = qualified[qualified["underdog_10plus"]]
    n10   = len(sub10)
    h10   = int(sub10["hit_actual_AST"].sum()) if n10 > 0 else 0
    hr10  = round(h10 / n10, 4) if n10 > 0 else None
    lift10 = round(hr10 / baseline_rate, 4) if (hr10 is not None and baseline_rate) else None
    bucket_results["underdog_10plus"] = {"n": n10, "hits": h10, "hit_rate": hr10, "lift": lift10}

    # ── Step 6: Tier breakdown within underdog_10plus ────────────────────
    tier_breakdown: dict = {}
    for tier_label, tier_vals in [
        ("T2",      [2.0]),
        ("T4",      [4.0]),
        ("T6",      [6.0]),
        ("T8plus",  [8.0, 10.0, 12.0]),
    ]:
        sub = sub10[sub10["best_tier_AST"].isin(tier_vals)]
        n   = len(sub)
        h   = int(sub["hit_actual_AST"].sum()) if n > 0 else 0
        hr  = round(h / n, 4) if n > 0 else None
        tier_breakdown[tier_label] = {"n": n, "hits": h, "hit_rate": hr}

    # ── Step 7: Role breakdown within underdog_10plus ────────────────────
    role_breakdown: dict = {}
    for role_label, mask in [
        ("primary_ball_handler", sub10["rolling_ast_avg"] >= H20_PRIMARY_AST_AVG),
        ("secondary",            sub10["rolling_ast_avg"] <  H20_PRIMARY_AST_AVG),
    ]:
        sub  = sub10[mask]
        n    = len(sub)
        h    = int(sub["hit_actual_AST"].sum()) if n > 0 else 0
        hr   = round(h / n, 4) if n > 0 else None
        role_breakdown[role_label] = {"n": n, "hits": h, "hit_rate": hr}

    # ── Step 8: Verdict ───────────────────────────────────────────────────
    if n10 < H20_MIN_N:
        verdict = "insufficient_sample"
        reason  = f"underdog_10plus n={n10} < H20_MIN_N={H20_MIN_N}"
        rule_rec = "Defer — insufficient season sample. Rerun at season end or with multi-season data."
    elif hr10 is None or baseline_rate is None:
        verdict = "insufficient_sample"
        reason  = "baseline or key bucket hit rate is None"
        rule_rec = "Cannot evaluate — data issue."
    else:
        delta = round(baseline_rate - hr10, 4)
        if delta >= 0.08:
            verdict  = "confirmed_penalty"
            reason   = f"underdog_10plus hit rate {hr10*100:.1f}% vs baseline {baseline_rate*100:.1f}% (delta={delta*100:.1f}pp >= 8pp)"
            rule_rec = f"Ship -10pp AST confidence penalty when team is underdog by spread_abs >= 10."
        elif delta >= 0.04:
            verdict  = "weak_signal"
            reason   = f"underdog_10plus hit rate {hr10*100:.1f}% vs baseline {baseline_rate*100:.1f}% (delta={delta*100:.1f}pp, 4-8pp range)"
            rule_rec = "Consider -5pp penalty or raise threshold to spread_abs >= 12. Check tier breakdown."
        elif delta > 0:
            verdict  = "directional_only"
            reason   = f"underdog_10plus hit rate {hr10*100:.1f}% vs baseline {baseline_rate*100:.1f}% (delta={delta*100:.1f}pp < 4pp)"
            rule_rec = "Signal too weak to justify a penalty rule. No action."
        else:
            verdict  = "no_signal"
            reason   = f"underdog_10plus hit rate {hr10*100:.1f}% at or above baseline {baseline_rate*100:.1f}%"
            rule_rec = "Hypothesis not confirmed. No rule change."

    # ── Step 9: Print report ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  H20 — LOSING-SIDE BLOWOUT AST SUPPRESSION")
    print(f"  Proposed rule: -10pp AST confidence when underdog spread_abs >= 10")
    print(f"  Date range: {player_log['game_date'].min().date()} → {player_log['game_date'].max().date()}")
    print(f"{'='*65}")
    print(f"\n  AST hit rate by spread bucket (baseline = fav_or_even):")
    for bkt, res in bucket_results.items():
        lift_str = f"  lift={res['lift']:.3f}" if res.get("lift") is not None else ""
        marker   = "  ← KEY BUCKET" if bkt == "underdog_10plus" else ""
        print(f"  {bkt:<22} n={res['n']:<5} hit_rate={((res['hit_rate'] or 0)*100):.1f}%{lift_str}{marker}")

    print(f"\n  Tier breakdown (underdog_10plus only):")
    for tier_label, res in tier_breakdown.items():
        hr_str = f"{(res['hit_rate'] or 0)*100:.1f}%" if res["hit_rate"] is not None else "n/a"
        print(f"    {tier_label:<8} n={res['n']:<4} hit_rate={hr_str}")

    print(f"\n  Role breakdown (underdog_10plus only):")
    for role_label, res in role_breakdown.items():
        hr_str = f"{(res['hit_rate'] or 0)*100:.1f}%" if res["hit_rate"] is not None else "n/a"
        print(f"    {role_label:<25} n={res['n']:<4} hit_rate={hr_str}")

    print(f"\n  Verdict: {verdict.upper()}")
    print(f"  Reason:  {reason}")
    print(f"  Rule recommendation: {rule_rec}")
    print(f"\n{'='*65}\n")

    # ── Step 10: Write JSON ───────────────────────────────────────────────
    out = {
        "generated_at":          dt.date.today().isoformat(),
        "mode":                  "losing-side-ast",
        "hypothesis":            "Underdog spread_abs >= 10 suppresses AST tier hit rate",
        "proposed_rule":         "-10pp AST confidence when team is underdog by spread_abs >= 10",
        "rolling_window":        window,
        "date_range": {
            "start": str(player_log["game_date"].min().date()),
            "end":   str(player_log["game_date"].max().date()),
        },
        "total_ast_instances":       len(qualified),
        "spread_bucket_results":     bucket_results,
        "tier_breakdown_underdog_10plus": tier_breakdown,
        "role_breakdown_underdog_10plus": role_breakdown,
        "verdict":               verdict,
        "verdict_reason":        reason,
        "rule_recommendation":   rule_rec,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else H20_JSON
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[backtest] H20 results → {out_path}")


# ── In-Game Blowout Regime Backtest (H19) ─────────────────────────────

def run_blowout_regime_analysis(
    player_log: pd.DataFrame,
    master_df: pd.DataFrame,
    args,
) -> None:
    """
    H19 — In-game blowout regime analysis.

    Tests whether tier hit rates differ systematically for:
      - Favored-side primary vs. secondary scorers in actual blowout wins (margin >= H19_BLOWOUT_MARGIN)
      - Underdog-side primary vs. secondary scorers in actual blowout losses (margin >= H19_BLOWOUT_MARGIN)

    Uses actual final score margin (not pre-game spread) to classify blowout games.
    Applies a minimum-minutes gate (H19_MIN_MINUTES_GATE) to exclude garbage-time appearances.
    Reuses build_game_result_lookup() from H6 for final-margin classification.
    """
    if master_df.empty:
        print("[backtest] WARNING: master_df is empty — cannot run H19 blowout-regime analysis.")
        return

    STATS = ["PTS", "REB", "AST", "3PM"]
    STAT_COL_MAP = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
    TIERS_MAP = {
        "PTS": [10, 15, 20, 25, 30],
        "REB": [4, 6, 8, 10, 12],
        "AST": [2, 4, 6, 8, 10, 12],
        "3PM": [1, 2, 3, 4],
    }

    window = getattr(args, "window", None) or ROLLING_WINDOW
    print(f"[backtest] H19 blowout-regime | blowout_margin≥{H19_BLOWOUT_MARGIN} | "
          f"min_minutes≥{H19_MIN_MINUTES_GATE} | window={window}")

    # ── Step 1: Build game-level result lookup (reuse H6 function) ────────
    # build_game_result_lookup uses POST_BLOWOUT_THRESHOLD=15 which equals H19_BLOWOUT_MARGIN.
    result_lookup = build_game_result_lookup(master_df)

    # ── Step 2: Build pre-game spread lookup for is_favorite ─────────────
    # {(game_id_str, team_upper): signed_spread}
    spread_map: dict = {}
    for _, row in master_df.iterrows():
        gid  = str(row.get("game_id", "")).strip()
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        hs   = row.get("home_spread")
        as_  = row.get("away_spread")
        for team, spread in [(home, hs), (away, as_)]:
            if team and not pd.isna(spread):
                spread_map[(gid, team)] = float(spread)

    # ── Step 3: Classify scorer role ─────────────────────────────────────
    df = classify_player_role(player_log, window=window)

    # ── Step 4: Add game result + spread context per player-game ──────────
    df["_date_str"] = df["game_date"].dt.strftime("%Y-%m-%d")
    df["_team_upper"] = df["team_abbrev"].str.upper().str.strip()
    df["_gid"] = df["game_id"].astype(str).str.split(".").str[0].str.strip()

    df["game_result"] = df.apply(
        lambda r: result_lookup.get((r["_team_upper"], r["_date_str"]), "neutral"),
        axis=1,
    )

    df["signed_spread"] = df.apply(
        lambda r: spread_map.get((r["_gid"], r["_team_upper"])),
        axis=1,
    )
    df["is_favorite"] = df["signed_spread"].apply(
        lambda s: (s < 0) if pd.notna(s) else None
    )

    # ── Step 5: Apply minutes gate ────────────────────────────────────────
    df = df[df["minutes_raw"] >= H19_MIN_MINUTES_GATE].copy()

    # ── Step 6: Build margin-aware lookup for blowout_win / blowout_loss ──
    margin_lookup: dict = {}  # {(team_upper, date_str): actual_margin (positive = won)}
    for _, row in master_df.iterrows():
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        game_date = row.get("game_date")
        if pd.isna(game_date):
            continue
        date_str = pd.Timestamp(game_date).strftime("%Y-%m-%d")
        home_score = pd.to_numeric(row.get("home_score"), errors="coerce")
        away_score = pd.to_numeric(row.get("away_score"), errors="coerce")
        if pd.isna(home_score) or pd.isna(away_score):
            continue
        home_margin = float(home_score) - float(away_score)
        if home:
            margin_lookup[(home, date_str)] = home_margin       # positive = home won
        if away:
            margin_lookup[(away, date_str)] = -home_margin      # positive = away won

    df["actual_margin"] = df.apply(
        lambda r: margin_lookup.get((r["_team_upper"], r["_date_str"])),
        axis=1,
    )

    def _regime(row) -> str:
        m = row["actual_margin"]
        if pd.isna(m):
            return "unknown"
        if m >= H19_BLOWOUT_MARGIN:
            return "blowout_win"
        if m <= -H19_BLOWOUT_MARGIN:
            return "blowout_loss"
        return "competitive"

    df["regime"] = df.apply(_regime, axis=1)

    # ── Step 7: Compute best tier per player-game (rolling window) ────────
    df = add_best_tiers(df, window=window)

    # ── Step 8: Compute hit rates per cell ───────────────────────────────
    def _hit_rate_cell(subset: pd.DataFrame, stat: str) -> dict:
        """Compute hit rate and avg minutes for a player-game subset at best tier."""
        col    = STAT_COL_MAP[stat]
        bt_col = f"best_tier_{stat}"
        valid  = subset[subset[bt_col].notna()].copy()
        n = len(valid)
        if n < 1:
            return {"n": 0, "hit_rate": None, "lift": None, "avg_minutes": None}
        hits = int(
            valid.apply(lambda r: float(r[col]) >= float(r[bt_col]), axis=1).sum()
        )
        hr   = round(hits / n, 3)
        mins = round(float(valid["minutes_raw"].mean()), 1)
        return {"n": n, "hit_rate": hr, "avg_minutes": mins}

    # Compute baseline (all instances, scorer_role != unknown)
    baseline_df = df[df["scorer_role"] != "unknown"].copy()
    results: dict = {}

    for stat in STATS:
        baseline    = _hit_rate_cell(baseline_df, stat)
        baseline_hr = baseline.get("hit_rate") or 0.0
        stat_results = {"baseline": baseline}

        for regime in ("blowout_win", "blowout_loss", "competitive"):
            regime_df = df[df["regime"] == regime].copy()
            for role in ("primary", "secondary"):
                cell_df = regime_df[regime_df["scorer_role"] == role].copy()
                cell    = _hit_rate_cell(cell_df, stat)
                if cell["hit_rate"] is not None and baseline_hr > 0:
                    cell["lift"] = round(cell["hit_rate"] / baseline_hr, 3)
                key = f"{regime}_{role}"
                stat_results[key] = cell

        results[stat] = stat_results

    # ── Step 9: Verdict logic ─────────────────────────────────────────────
    verdicts: dict = {}
    for stat, stat_res in results.items():
        baseline_hr = (stat_res["baseline"].get("hit_rate") or 0.0)
        bw_sec  = stat_res.get("blowout_win_secondary", {})
        bw_pri  = stat_res.get("blowout_win_primary", {})
        bl_sec  = stat_res.get("blowout_loss_secondary", {})
        bl_pri  = stat_res.get("blowout_loss_primary", {})

        v = {}

        # Favored-side secondary scorer suppression
        if (bw_sec.get("n") or 0) >= H19_MIN_N and bw_sec.get("lift") is not None:
            lift = bw_sec["lift"]
            if lift < 0.88:
                v["blowout_win_secondary"] = (
                    f"SUPPRESSED (lift={lift:.3f}, n={bw_sec['n']}) — secondary scorers on winning side "
                    f"hit tier at {bw_sec['hit_rate']*100:.1f}% vs {baseline_hr*100:.1f}% baseline"
                )
            elif lift > 1.05:
                v["blowout_win_secondary"] = (
                    f"ELEVATED (lift={lift:.3f}, n={bw_sec['n']}) — unexpected; review minutes data"
                )
            else:
                v["blowout_win_secondary"] = f"NEUTRAL (lift={lift:.3f}, n={bw_sec['n']})"
        else:
            v["blowout_win_secondary"] = f"INSUFFICIENT_SAMPLE (n={(bw_sec.get('n') or 0)})"

        # Underdog-side secondary scorer — desperation vs. collapse
        if (bl_sec.get("n") or 0) >= H19_MIN_N and bl_sec.get("lift") is not None:
            lift     = bl_sec["lift"]
            avg_mins = bl_sec.get("avg_minutes") or 0
            if lift >= 1.02:
                v["blowout_loss_secondary"] = (
                    f"DESPERATION_REGIME (lift={lift:.3f}, n={bl_sec['n']}, avg_min={avg_mins}) — "
                    f"production maintained or elevated on losing side"
                )
            elif lift < 0.88:
                v["blowout_loss_secondary"] = (
                    f"COLLAPSE_REGIME (lift={lift:.3f}, n={bl_sec['n']}, avg_min={avg_mins}) — "
                    f"production suppressed even on losing side"
                )
            else:
                v["blowout_loss_secondary"] = (
                    f"NEUTRAL (lift={lift:.3f}, n={bl_sec['n']}, avg_min={avg_mins}) — no clear regime signal"
                )
        else:
            v["blowout_loss_secondary"] = f"INSUFFICIENT_SAMPLE (n={(bl_sec.get('n') or 0)})"

        verdicts[stat] = v

    # ── Step 10: Print report ─────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  H19 — IN-GAME BLOWOUT REGIME ANALYSIS")
    print(f"  Blowout threshold: final margin ≥ {H19_BLOWOUT_MARGIN} pts")
    print(f"  Minutes gate: ≥ {H19_MIN_MINUTES_GATE} min played")
    print(f"  Date range: {player_log['game_date'].min().date()} → {player_log['game_date'].max().date()}")
    print(f"{'='*65}")

    for stat in STATS:
        sr   = results[stat]
        vd   = verdicts[stat]
        base = sr["baseline"]
        print(f"\n  {stat}  baseline: {(base.get('hit_rate') or 0)*100:.1f}%"
              f" (n={base.get('n',0)}, avg_min={base.get('avg_minutes','?')})")
        print(f"  {'─'*60}")
        header = f"  {'Cell':<32} {'n':>5}  {'hit_rate':>9}  {'lift':>6}  {'avg_min':>7}"
        print(header)
        for regime in ("blowout_win", "blowout_loss", "competitive"):
            for role in ("primary", "secondary"):
                key  = f"{regime}_{role}"
                cell = sr.get(key, {})
                hr   = f"{cell['hit_rate']*100:.1f}%" if cell.get("hit_rate") is not None else "  n/a"
                lft  = f"{cell['lift']:.3f}"          if cell.get("lift")     is not None else "   n/a"
                mins = f"{cell['avg_minutes']:.1f}"   if cell.get("avg_minutes") is not None else "  n/a"
                print(f"  {key:<32} {cell.get('n',0):>5}  {hr:>9}  {lft:>6}  {mins:>7}")
        print(f"\n  Verdicts:")
        for k, v_str in vd.items():
            print(f"    {k}: {v_str}")

    # ── Step 11: Write JSON output ────────────────────────────────────────
    out = {
        "generated_at":       dt.date.today().isoformat(),
        "mode":               "blowout-regime",
        "blowout_margin_pts": H19_BLOWOUT_MARGIN,
        "min_minutes_gate":   H19_MIN_MINUTES_GATE,
        "rolling_window":     window,
        "date_range": {
            "start": str(player_log["game_date"].min().date()),
            "end":   str(player_log["game_date"].max().date()),
        },
        "results":  results,
        "verdicts": verdicts,
    }
    out_path = Path(args.output) if getattr(args, "output", None) else H19_JSON
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H19 results → {out_path}")


# ── H21 — Miss Anatomy ────────────────────────────────────────────────

def run_miss_anatomy_analysis(player_log: pd.DataFrame, args) -> None:
    """
    H21 — Miss Anatomy: near-miss vs. blowup next-game prediction.

    For each player-stat combo with >= H21_MIN_MISSES misses at their best tier,
    classify each miss as near-miss (actual >= tier - H21_NEAR_MISS_THRESH) or
    blowup (actual < tier - H21_BLOWUP_THRESH). Then look at the next game's
    result at the same tier and compare post-near-miss vs. post-blowup hit rates.

    Also computes league-wide aggregates across all players.
    Uses shift(1).rolling() to avoid lookahead on best tier selection.
    """
    window = getattr(args, "window", None) or ROLLING_WINDOW
    print(f"[backtest] H21 miss-anatomy | window={window} | "
          f"near_miss_thresh={H21_NEAR_MISS_THRESH} | blowup_thresh={H21_BLOWUP_THRESH}")

    # ── Step 1: Compute best tiers ────────────────────────────────────────
    df = add_best_tiers(player_log, window=window)

    # ── Step 2: Build next-game lookup ────────────────────────────────────
    # For each player-game-stat where a miss occurred, find the NEXT non-DNP game
    # for that player and check the result at the same tier.

    league_results: dict = {stat: {
        "post_near_miss":  {"n": 0, "hits": 0},
        "post_blowup":     {"n": 0, "hits": 0},
        "post_other_miss": {"n": 0, "hits": 0},  # miss within (2, 3) gap — between thresholds
    } for stat in STAT_COL}

    # Player-level results: {(player_name, stat): {near_miss: {...}, blowup: {...}}}
    player_results: dict = {}

    for stat, col in STAT_COL.items():
        best_col = f"best_tier_{stat}"
        hit_col  = f"hit_actual_{stat}"

        for player_name, grp in df.groupby("player_name"):
            # Sort ascending — index order = chronological
            grp = grp.sort_values("game_date").reset_index(drop=True)

            misses = grp[
                grp[best_col].notna() &
                grp[hit_col].notna() &
                (grp[hit_col] == 0)
            ]

            if len(misses) < H21_MIN_MISSES:
                continue

            key = (player_name, stat)
            player_results[key] = {
                "near_miss":  {"n": 0, "hits": 0},
                "blowup":     {"n": 0, "hits": 0},
                "other_miss": {"n": 0, "hits": 0},
            }

            for idx, miss_row in misses.iterrows():
                tier   = miss_row[best_col]
                actual = miss_row[col]
                gap    = tier - actual  # positive = missed below tier

                # Classify miss severity
                if gap <= H21_NEAR_MISS_THRESH:
                    severity = "near_miss"
                elif gap >= H21_BLOWUP_THRESH:
                    severity = "blowup"
                else:
                    severity = "other_miss"

                # Find the next game for this player AFTER this miss
                next_games = grp[
                    (grp.index > idx) &
                    grp[best_col].notna() &
                    grp[hit_col].notna()
                ]

                if next_games.empty:
                    continue  # no qualifying next game

                next_game = next_games.iloc[0]

                # Check if next game hit at same tier as the miss game
                # (use SAME tier as miss game — tests whether this specific tier holds)
                next_actual = next_game[col]
                next_hit = int(next_actual >= tier)

                # Record player-level
                player_results[key][severity]["n"]    += 1
                player_results[key][severity]["hits"] += next_hit

                # Record league-level
                league_key = "post_" + ("near_miss" if severity == "near_miss"
                                         else "blowup" if severity == "blowup"
                                         else "other_miss")
                league_results[stat][league_key]["n"]    += 1
                league_results[stat][league_key]["hits"] += next_hit

    # ── Step 3: Compute league-level hit rates and verdict ────────────────
    league_summary: dict = {}
    for stat in STAT_COL:
        lr = league_results[stat]
        nm = lr["post_near_miss"]
        bl = lr["post_blowup"]

        nm_hr = round(nm["hits"] / nm["n"], 4) if nm["n"] > 0 else None
        bl_hr = round(bl["hits"] / bl["n"], 4) if bl["n"] > 0 else None

        if nm_hr is not None and bl_hr is not None and nm["n"] >= H21_MIN_N and bl["n"] >= H21_MIN_N:
            delta = round(nm_hr - bl_hr, 4)
            if delta >= 0.08:
                verdict = "near_miss_lift"
                reason  = f"post-near-miss {nm_hr*100:.1f}% vs post-blowup {bl_hr*100:.1f}% (delta={delta*100:.1f}pp >= 8pp)"
            elif delta <= -0.08:
                verdict = "blowup_lift"
                reason  = f"post-blowup {bl_hr*100:.1f}% vs post-near-miss {nm_hr*100:.1f}% (delta={abs(delta)*100:.1f}pp >= 8pp, inverted)"
            elif abs(delta) >= 0.04:
                verdict = "weak_signal"
                reason  = f"delta={delta*100:.1f}pp (4-8pp range)"
            else:
                verdict = "noise"
                reason  = f"delta={delta*100:.1f}pp < 4pp"
        else:
            verdict = "insufficient_sample"
            reason  = f"near_miss n={nm['n']}, blowup n={bl['n']} (need >= {H21_MIN_N} each)"

        om = lr["post_other_miss"]
        league_summary[stat] = {
            "post_near_miss":  {**nm, "hit_rate": nm_hr},
            "post_blowup":     {**bl, "hit_rate": bl_hr},
            "post_other_miss": {**om, "hit_rate": round(om["hits"] / om["n"], 4)
                                if om["n"] > 0 else None},
            "verdict":         verdict,
            "verdict_reason":  reason,
        }

    # ── Step 4: Summarize player-level results ────────────────────────────
    # Flag players with strong separation (delta >= 15pp, min 3 games each bucket)
    notable_players: list = []
    for (player_name, stat), res in player_results.items():
        nm = res["near_miss"]
        bl = res["blowup"]
        nm_hr = round(nm["hits"] / nm["n"], 4) if nm["n"] >= 3 else None
        bl_hr = round(bl["hits"] / bl["n"], 4) if bl["n"] >= 3 else None
        if nm_hr is not None and bl_hr is not None:
            delta = nm_hr - bl_hr
            if abs(delta) >= 0.15:
                notable_players.append({
                    "player":       player_name,
                    "stat":         stat,
                    "near_miss_n":  nm["n"],
                    "near_miss_hr": nm_hr,
                    "blowup_n":     bl["n"],
                    "blowup_hr":    bl_hr,
                    "delta":        round(delta, 4),
                })
    notable_players.sort(key=lambda x: abs(x["delta"]), reverse=True)

    # ── Step 5: Print report ──────────────────────────────────────────────
    print(f"\n{'='*68}")
    print(f"  H21 — MISS ANATOMY: NEAR-MISS vs. BLOWUP NEXT-GAME PREDICTION")
    print(f"  Near-miss: actual >= tier - {H21_NEAR_MISS_THRESH} | "
          f"Blowup: actual < tier - {H21_BLOWUP_THRESH}")
    print(f"  Date range: {player_log['game_date'].min().date()} "
          f"-> {player_log['game_date'].max().date()}")
    print(f"{'='*68}")

    for stat in STAT_COL:
        s = league_summary[stat]
        nm = s["post_near_miss"]
        bl = s["post_blowup"]
        nm_str = f"{nm['hit_rate']*100:.1f}%" if nm.get("hit_rate") is not None else "n/a"
        bl_str = f"{bl['hit_rate']*100:.1f}%" if bl.get("hit_rate") is not None else "n/a"
        print(f"\n  {stat}:")
        print(f"    post_near_miss  n={nm['n']:<4}  hit_rate={nm_str}")
        print(f"    post_blowup     n={bl['n']:<4}  hit_rate={bl_str}")
        print(f"    Verdict: {s['verdict'].upper()} -- {s['verdict_reason']}")

    if notable_players:
        print(f"\n  Notable players (|delta| >= 15pp, min 3 games each bucket):")
        for p in notable_players[:10]:
            direction = "near-miss lifts" if p["delta"] > 0 else "blowup lifts"
            print(f"    {p['player']} {p['stat']}: {direction} "
                  f"nm={p['near_miss_hr']*100:.0f}%(n={p['near_miss_n']}) "
                  f"bl={p['blowup_hr']*100:.0f}%(n={p['blowup_n']}) "
                  f"delta={p['delta']*100:+.0f}pp")
    else:
        print(f"\n  No notable per-player separation found (|delta| < 15pp in all cases).")

    print(f"\n{'='*68}\n")

    # ── Step 6: Write JSON ────────────────────────────────────────────────
    out = {
        "generated_at":    dt.date.today().isoformat(),
        "mode":            "miss-anatomy",
        "hypothesis":      "Near-miss severity (actual >= tier-2) predicts next-game hit rate better than blowup miss (actual < tier-3)",
        "rolling_window":  window,
        "near_miss_thresh": H21_NEAR_MISS_THRESH,
        "blowup_thresh":   H21_BLOWUP_THRESH,
        "date_range": {
            "start": str(player_log["game_date"].min().date()),
            "end":   str(player_log["game_date"].max().date()),
        },
        "league_summary":  league_summary,
        "notable_players": notable_players[:20],
        "total_player_stat_combos_evaluated": len(player_results),
    }

    out_path = Path(args.output) if getattr(args, "output", None) else H21_JSON
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[backtest] H21 results -> {out_path}")


def run_star_absence_analysis(
    player_log: pd.DataFrame,
    args,
) -> None:
    """
    H26 — Star absence teammate impact.

    For each team, identifies the leading scorer (highest PTS avg among
    whitelisted players with >= SA_MIN_STAR_GAMES non-DNP games). Finds games
    where the star was absent (DNP or entirely missing from the game log).
    Measures tier hit rate deltas for each teammate: with_star vs without_star.

    Reports per-team and population-level results.
    Writes data/backtest_star_absence.json.
    """

    STATS = ["PTS", "REB", "AST", "3PM"]
    STAT_COL_MAP = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
    TIERS_MAP = {
        "PTS": [10, 15, 20, 25, 30],
        "REB": [4, 6, 8, 10, 12],
        "AST": [2, 4, 6, 8, 10, 12],
        "3PM": [1, 2, 3, 4],
    }

    print(f"[backtest] H26 star-absence | "
          f"min_star_games={SA_MIN_STAR_GAMES} | "
          f"min_absent_games={SA_MIN_ABSENT_GAMES} | "
          f"min_condition_n={SA_MIN_CONDITION_N}")

    # ── Step 1: Load FULL game log (including DNPs) for absence detection ──
    # player_log already has DNPs excluded — we need DNP rows to know
    # which games the star missed (as opposed to games the team didn't play).
    if not GAME_LOG_CSV.exists():
        print("[backtest] ERROR: player_game_log.csv not found.")
        return
    df_full = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df_full["game_date"] = pd.to_datetime(df_full["game_date"], errors="coerce")
    df_full["_team_upper"] = df_full["team_abbrev"].astype(str).str.strip().str.upper()
    df_full["_name_lower"] = df_full["player_name"].astype(str).str.strip().str.lower()
    df_full["_dnp"] = df_full["dnp"].astype(str).str.strip() == "1"
    df_full["_date_str"] = df_full["game_date"].dt.strftime("%Y-%m-%d")

    # Apply same date filters as main player_log
    if getattr(args, "start", None):
        df_full = df_full[df_full["game_date"] >= pd.Timestamp(args.start)]
    if getattr(args, "end", None):
        df_full = df_full[df_full["game_date"] <= pd.Timestamp(args.end)]

    # ── Step 2: Identify each team's leading scorer ────────────────────────
    # Use the filtered player_log (no DNPs) to compute PTS averages.
    # Only whitelisted players are in player_log.
    team_col = player_log["team_abbrev"].astype(str).str.strip().str.upper()
    player_log = player_log.copy()
    player_log["_team_upper"] = team_col
    player_log["_name_lower"] = player_log["player_name"].astype(str).str.strip().str.lower()
    player_log["_date_str"] = player_log["game_date"].dt.strftime("%Y-%m-%d")

    # Per-player season stats
    player_season = (
        player_log.groupby(["_name_lower", "_team_upper"])
        .agg(
            pts_avg=("pts", "mean"),
            games_played=("pts", "count"),
            player_name_display=("player_name", "first"),
        )
        .reset_index()
    )
    # Filter to players with enough games
    player_season = player_season[
        player_season["games_played"] >= SA_MIN_STAR_GAMES
    ].copy()

    # Identify leading scorer per team: highest pts_avg
    stars = (
        player_season
        .sort_values("pts_avg", ascending=False)
        .drop_duplicates(subset=["_team_upper"], keep="first")
    )
    star_map: dict[str, dict] = {}  # team_upper → {name_lower, display, pts_avg, games}
    for _, row in stars.iterrows():
        star_map[row["_team_upper"]] = {
            "name_lower":   row["_name_lower"],
            "display_name": row["player_name_display"],
            "pts_avg":      round(float(row["pts_avg"]), 1),
            "games_played": int(row["games_played"]),
        }

    print(f"[backtest] Identified {len(star_map)} team leading scorers:")
    for team in sorted(star_map):
        s = star_map[team]
        print(f"  {team}: {s['display_name']} ({s['pts_avg']} PPG, {s['games_played']}g)")

    # ── Step 3: Build star-absent game sets per team ───────────────────────
    # A star is "absent" for a game if they have NO non-DNP row in the full log
    # for that (team, game_date) combination.
    #
    # First: get all (team, game_date) combos from the full log
    # (any row for this team on this date = team played that day)
    team_games = (
        df_full
        .groupby(["_team_upper", "_date_str"])
        .size()
        .reset_index(name="_count")
    )

    team_results: dict[str, dict] = {}
    for team, star_info in star_map.items():
        star_name = star_info["name_lower"]

        # All dates this team played
        team_dates = set(
            team_games.loc[team_games["_team_upper"] == team, "_date_str"]
        )

        # Dates where the star played (non-DNP row exists in full log)
        star_played_mask = (
            (df_full["_team_upper"] == team)
            & (df_full["_name_lower"] == star_name)
            & (~df_full["_dnp"])
        )
        star_played_dates = set(df_full.loc[star_played_mask, "_date_str"])

        # Star absent = team played but star didn't (DNP or missing entirely)
        star_absent_dates = team_dates - star_played_dates

        if len(star_absent_dates) < SA_MIN_ABSENT_GAMES:
            print(f"  {team}: {len(star_absent_dates)} star-absent games "
                  f"(< {SA_MIN_ABSENT_GAMES} minimum) — skipping")
            continue

        print(f"  {team}: {len(star_absent_dates)} star-absent games, "
              f"{len(star_played_dates)} star-present games")

        # ── Step 4: Compute teammate tier hit rates by condition ───────────
        # Get all teammate rows from player_log (DNPs already excluded)
        teammates = player_log[
            (player_log["_team_upper"] == team)
            & (player_log["_name_lower"] != star_name)
        ].copy()

        if teammates.empty:
            print(f"  {team}: no whitelisted teammates — skipping")
            continue

        teammates["_star_absent"] = teammates["_date_str"].isin(star_absent_dates)

        # Per-teammate, per-stat, per-tier: hit rate WITH vs WITHOUT star
        teammate_results: list[dict] = []

        for tm_name in teammates["_name_lower"].unique():
            tm_rows = teammates[teammates["_name_lower"] == tm_name]
            tm_display = tm_rows["player_name"].iloc[0]

            n_with    = int((~tm_rows["_star_absent"]).sum())
            n_without = int(tm_rows["_star_absent"].sum())

            if n_with < SA_MIN_CONDITION_N or n_without < SA_MIN_CONDITION_N:
                continue

            tm_with    = tm_rows[~tm_rows["_star_absent"]]
            tm_without = tm_rows[tm_rows["_star_absent"]]

            stat_deltas: dict[str, dict] = {}

            for stat in STATS:
                col = STAT_COL_MAP[stat]
                tiers = TIERS_MAP[stat]

                for tier in tiers:
                    hits_with = int((tm_with[col] >= tier).sum())
                    n_w       = len(tm_with)
                    hr_with   = hits_with / n_w if n_w > 0 else None

                    hits_without = int((tm_without[col] >= tier).sum())
                    n_wo         = len(tm_without)
                    hr_without   = hits_without / n_wo if n_wo > 0 else None

                    if hr_with is not None and hr_without is not None:
                        delta = round(hr_without - hr_with, 4)
                    else:
                        delta = None

                    tier_key = f"{stat}_T{tier}"
                    stat_deltas[tier_key] = {
                        "hr_with_star":    round(hr_with, 4) if hr_with is not None else None,
                        "n_with":          n_w,
                        "hr_without_star": round(hr_without, 4) if hr_without is not None else None,
                        "n_without":       n_wo,
                        "delta":           delta,
                    }

            teammate_results.append({
                "player":     tm_display,
                "n_with":     n_with,
                "n_without":  n_without,
                "tier_deltas": stat_deltas,
            })

        team_results[team] = {
            "star":              star_info,
            "star_absent_games": len(star_absent_dates),
            "star_present_games": len(star_played_dates),
            "teammates_analyzed": len(teammate_results),
            "teammates":          teammate_results,
        }

    # ── Step 5: Population-level aggregation ───────────────────────────────
    # Across all teams and teammates, compute the average tier hit rate delta
    # by stat and tier, weighted by min(n_with, n_without) for each observation.
    pop_agg: dict[str, list] = {}  # tier_key → list of (delta, weight)

    for team, tdata in team_results.items():
        for tm in tdata["teammates"]:
            for tier_key, td in tm["tier_deltas"].items():
                if td["delta"] is not None:
                    weight = min(td["n_with"], td["n_without"])
                    pop_agg.setdefault(tier_key, []).append((td["delta"], weight))

    population_summary: dict[str, dict] = {}
    for tier_key in sorted(pop_agg.keys()):
        observations = pop_agg[tier_key]
        n_obs = len(observations)
        if n_obs == 0:
            continue
        total_weight = sum(w for _, w in observations)
        if total_weight == 0:
            continue
        weighted_delta = sum(d * w for d, w in observations) / total_weight
        unweighted_delta = sum(d for d, _ in observations) / n_obs
        # Count how many show positive delta (teammate benefits)
        n_positive = sum(1 for d, _ in observations if d > 0)
        population_summary[tier_key] = {
            "weighted_avg_delta":   round(weighted_delta, 4),
            "unweighted_avg_delta": round(unweighted_delta, 4),
            "n_observations":       n_obs,
            "n_positive":           n_positive,
            "pct_positive":         round(n_positive / n_obs * 100, 1),
        }

    # ── Step 6: Print report ───────────────────────────────────────────────
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  H26 — Star Absence Teammate Impact")
    print(f"  Teams analyzed: {len(team_results)}")
    print(f"{sep}")

    for team in sorted(team_results):
        tdata = team_results[team]
        star = tdata["star"]
        print(f"\n  {team} — Star: {star['display_name']} "
              f"({star['pts_avg']} PPG, {star['games_played']}g)")
        print(f"  Star absent: {tdata['star_absent_games']}g | "
              f"Star present: {tdata['star_present_games']}g | "
              f"Teammates analyzed: {tdata['teammates_analyzed']}")

        # Show top deltas per teammate (only meaningful ones)
        for tm in tdata["teammates"]:
            notable = [
                (k, v) for k, v in tm["tier_deltas"].items()
                if v["delta"] is not None and abs(v["delta"]) >= 0.05
            ]
            if not notable:
                continue
            notable.sort(key=lambda x: abs(x[1]["delta"]), reverse=True)
            print(f"\n    {tm['player']} (with={tm['n_with']}g, without={tm['n_without']}g):")
            for k, v in notable[:6]:
                direction = "+" if v["delta"] > 0 else ""
                print(f"      {k:>10}: with={v['hr_with_star']*100:.1f}% "
                      f"without={v['hr_without_star']*100:.1f}% "
                      f"Δ={direction}{v['delta']*100:.1f}pp")

    # Population summary
    print(f"\n{sep}")
    print(f"  POPULATION SUMMARY (weighted avg delta across all teams)")
    print(f"  {'Tier':<12} {'Wtd Δ':>8} {'Unwt Δ':>8} {'n_obs':>6} {'%pos':>6}")
    print(f"  {'-'*44}")

    for stat in STATS:
        relevant = {k: v for k, v in population_summary.items() if k.startswith(stat)}
        if not relevant:
            continue
        for tier_key in sorted(relevant, key=lambda x: int(x.split("_T")[1])):
            v = relevant[tier_key]
            d = "+" if v["weighted_avg_delta"] > 0 else ""
            print(f"  {tier_key:<12} {d}{v['weighted_avg_delta']*100:>6.1f}pp "
                  f"{v['unweighted_avg_delta']*100:>7.1f}pp "
                  f"{v['n_observations']:>5} "
                  f"{v['pct_positive']:>5.0f}%")

    # Verdict
    print(f"\n{sep}")
    print(f"  VERDICT")
    print(f"  {'-'*44}")

    # Check PTS and AST deltas at key tiers
    pts_key_tiers = ["PTS_T15", "PTS_T20", "PTS_T25"]
    ast_key_tiers = ["AST_T4", "AST_T6"]
    verdict_parts = []

    for tier_key in pts_key_tiers + ast_key_tiers:
        entry = population_summary.get(tier_key)
        if entry and entry["n_observations"] >= 10:
            d = entry["weighted_avg_delta"]
            if d > 0.03:
                verdict_parts.append(
                    f"{tier_key}: +{d*100:.1f}pp lift ({entry['n_observations']} obs, "
                    f"{entry['pct_positive']:.0f}% positive) — SIGNAL"
                )
            elif d < -0.03:
                verdict_parts.append(
                    f"{tier_key}: {d*100:.1f}pp drag ({entry['n_observations']} obs) — "
                    f"negative (star presence helps)"
                )
            else:
                verdict_parts.append(
                    f"{tier_key}: {d*100:+.1f}pp ({entry['n_observations']} obs) — NOISE"
                )

    if verdict_parts:
        for v in verdict_parts:
            print(f"  {v}")
    else:
        print("  Insufficient data at key tiers for a verdict.")

    print(f"\n{sep}\n")

    # ── Step 7: Write JSON output ──────────────────────────────────────────
    output = {
        "mode":             "star-absence",
        "generated_at":     dt.date.today().isoformat(),
        "date_range": {
            "start": str(player_log["game_date"].min().date()),
            "end":   str(player_log["game_date"].max().date()),
        },
        "constants": {
            "SA_MIN_STAR_GAMES":   SA_MIN_STAR_GAMES,
            "SA_MIN_ABSENT_GAMES": SA_MIN_ABSENT_GAMES,
            "SA_MIN_CONDITION_N":  SA_MIN_CONDITION_N,
        },
        "teams_analyzed":       len(team_results),
        "star_identification":  {t: d["star"] for t, d in team_results.items()},
        "team_results":         team_results,
        "population_summary":   population_summary,
    }

    STAR_ABSENCE_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(STAR_ABSENCE_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(f"[backtest] H26 results written → {STAR_ABSENCE_JSON}")


# ── H27 — Primary Scorer Blowout PTS Performance ─────────────────────

def run_primary_blowout_analysis(
    player_log: pd.DataFrame,
    master_df: pd.DataFrame,
    args,
) -> None:
    """
    H27 — Primary Scorer Blowout PTS Performance.

    Tests whether primary scorers on the favored side reliably hit PTS tiers
    in high-spread games (spread_abs ≥ 10/12/15), using PRE-GAME SPREAD as
    the primary blowout classifier (the analyst rule fires on spread_abs,
    not final margin). Secondary analysis layer tracks whether the anticipated
    blowout actually materialized (final margin ≥ H27_ACTUAL_BLOWOUT_MARGIN)
    to reveal whether suppression (if any) is game-script dependent or baked
    into the spread itself.

    Per-player breakdown at spread_abs ≥ 15 surfaces player-specific tendencies
    (Jokic-style distributors vs. resilient primary scorers). Jokic isolation
    check computes the primary-scorer T25 hit rate with and without him.

    Motivation: blowout_t25_skip has 100% false skip rate (2/2 graded skips
    would have hit). The rule was motivated by Jokic's blowout behavior and
    may not generalize to other primary scorers.
    """
    if master_df.empty:
        print("[backtest] WARNING: master_df empty — cannot run H27.")
        return

    window = getattr(args, "window", None) or ROLLING_WINDOW
    print(f"[backtest] H27 primary-blowout | "
          f"thresholds={H27_SPREAD_THRESHOLDS} | "
          f"tiers={H27_PTS_TIERS} | "
          f"min_n={H27_MIN_N} | "
          f"min_player_n={H27_MIN_PLAYER_N} | "
          f"window={window}")

    # ── Step 1: Build spread lookup ───────────────────────────────────────
    # {(game_id_str, team_upper): signed_spread}
    spread_map: dict = {}
    for _, row in master_df.iterrows():
        gid  = str(row.get("game_id", "")).strip()
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        hs   = row.get("home_spread")
        as_  = row.get("away_spread")
        for team, spread in [(home, hs), (away, as_)]:
            if team and not pd.isna(spread):
                spread_map[(gid, team)] = float(spread)

    # ── Step 2: Classify scorer role ─────────────────────────────────────
    df = classify_player_role(player_log, window=window)

    # ── Step 3: Join spread to player-game rows ──────────────────────────
    df["_team_upper"] = df["team_abbrev"].astype(str).str.upper().str.strip()
    df["_gid"]        = df["game_id"].astype(str).str.split(".").str[0].str.strip()
    df["_date_str"]   = df["game_date"].dt.strftime("%Y-%m-%d")
    df["signed_spread"] = df.apply(
        lambda r: spread_map.get((r["_gid"], r["_team_upper"])),
        axis=1,
    )
    df["spread_abs"] = df["signed_spread"].abs()
    df["is_favorite"] = df["signed_spread"].apply(
        lambda s: (s < 0) if pd.notna(s) else None
    )

    # Filter to rows with valid spread AND known scorer role
    df = df[df["signed_spread"].notna() & (df["scorer_role"] != "unknown")].copy()

    if df.empty:
        print("[backtest] WARNING: no player-games with valid spread — cannot run H27.")
        return

    # ── Step 4: Join actual game margin (secondary analysis layer) ────────
    # {(team_upper, date_str): actual_margin (positive = this team won)}
    margin_lookup: dict = {}
    for _, row in master_df.iterrows():
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        game_date = row.get("game_date")
        if pd.isna(game_date):
            continue
        date_str = pd.Timestamp(game_date).strftime("%Y-%m-%d")
        home_score = pd.to_numeric(row.get("home_score"), errors="coerce")
        away_score = pd.to_numeric(row.get("away_score"), errors="coerce")
        if pd.isna(home_score) or pd.isna(away_score):
            continue
        home_margin = float(home_score) - float(away_score)
        if home:
            margin_lookup[(home, date_str)] = home_margin
        if away:
            margin_lookup[(away, date_str)] = -home_margin

    df["actual_margin"] = df.apply(
        lambda r: margin_lookup.get((r["_team_upper"], r["_date_str"])),
        axis=1,
    )
    # For the favorite, actual_margin > 0 means they won as expected.
    # "actual_blowout" = the anticipated blowout materialized (favorite won by >= 15).
    df["actual_blowout"] = df["actual_margin"].apply(
        lambda m: (m >= H27_ACTUAL_BLOWOUT_MARGIN) if pd.notna(m) else None
    )

    # ── Step 5: Compute tier hit rates per cell ───────────────────────────
    def _cell(subset: pd.DataFrame) -> dict:
        """Compute per-tier hit rate + avg minutes for a subset of player-games."""
        out: dict = {}
        n = len(subset)
        if n == 0:
            for tier in H27_PTS_TIERS:
                out[f"T{tier}"] = {"n": 0, "hits": 0, "hit_rate": None, "avg_minutes": None}
            return out
        avg_min = round(float(pd.to_numeric(subset["minutes_raw"], errors="coerce").mean()), 1)
        pts_series = pd.to_numeric(subset["pts"], errors="coerce")
        for tier in H27_PTS_TIERS:
            hits = int((pts_series >= tier).sum())
            out[f"T{tier}"] = {
                "n":           n,
                "hits":        hits,
                "hit_rate":    round(hits / n, 3),
                "avg_minutes": avg_min,
            }
        return out

    # Baselines — all games in df for each role (no spread filter).
    baseline_primary_df   = df[df["scorer_role"] == "primary"].copy()
    baseline_secondary_df = df[df["scorer_role"] == "secondary"].copy()
    baseline_primary      = _cell(baseline_primary_df)
    baseline_secondary    = _cell(baseline_secondary_df)

    results: dict = {}
    for threshold in H27_SPREAD_THRESHOLDS:
        key = f"spread_{threshold}"
        fav = df[(df["is_favorite"] == True) & (df["spread_abs"] >= threshold)].copy()

        primary_df   = fav[fav["scorer_role"] == "primary"].copy()
        secondary_df = fav[fav["scorer_role"] == "secondary"].copy()

        # Actual-outcome sub-splits
        pri_actual_df = primary_df[primary_df["actual_blowout"] == True].copy()
        pri_comp_df   = primary_df[primary_df["actual_blowout"] == False].copy()
        sec_actual_df = secondary_df[secondary_df["actual_blowout"] == True].copy()
        sec_comp_df   = secondary_df[secondary_df["actual_blowout"] == False].copy()

        results[key] = {
            "threshold":                threshold,
            "n_primary":                len(primary_df),
            "n_secondary":              len(secondary_df),
            "primary":                  _cell(primary_df),
            "primary_actual_blowout":   _cell(pri_actual_df),
            "primary_competitive":      _cell(pri_comp_df),
            "secondary":                _cell(secondary_df),
            "secondary_actual_blowout": _cell(sec_actual_df),
            "secondary_competitive":    _cell(sec_comp_df),
            "baseline_primary":         baseline_primary,
            "baseline_secondary":       baseline_secondary,
        }

    # ── Step 6: Per-player primary scorer breakdown (spread_abs ≥ 15) ────
    high_spread_primary = df[
        (df["is_favorite"] == True)
        & (df["spread_abs"] >= 15)
        & (df["scorer_role"] == "primary")
    ].copy()

    # Per-player full-log baselines (all games in df for this player) for comparison
    # Baseline is computed across ALL games in df (spread-valid + any role) to capture
    # the player's typical production regardless of spread context.
    all_df = df.copy()
    baseline_by_player: dict = {}
    for player, grp in all_df.groupby("player_name"):
        base_n = len(grp)
        if base_n == 0:
            continue
        base_pts = pd.to_numeric(grp["pts"], errors="coerce")
        base_min = pd.to_numeric(grp["minutes_raw"], errors="coerce")
        baseline_by_player[player] = {
            "avg_pts":     round(float(base_pts.mean()), 1),
            "avg_minutes": round(float(base_min.mean()), 1),
            "T15_rate":    round(int((base_pts >= 15).sum()) / base_n, 3),
            "T20_rate":    round(int((base_pts >= 20).sum()) / base_n, 3),
            "T25_rate":    round(int((base_pts >= 25).sum()) / base_n, 3),
            "T30_rate":    round(int((base_pts >= 30).sum()) / base_n, 3),
            "n":           base_n,
        }

    per_player_rows: list = []
    for player, grp in high_spread_primary.groupby("player_name"):
        n = len(grp)
        if n < H27_MIN_PLAYER_N:
            continue

        pts_series = pd.to_numeric(grp["pts"], errors="coerce")
        min_series = pd.to_numeric(grp["minutes_raw"], errors="coerce")

        T15_hits = int((pts_series >= 15).sum())
        T20_hits = int((pts_series >= 20).sum())
        T25_hits = int((pts_series >= 25).sum())
        T30_hits = int((pts_series >= 30).sum())

        T15_rate = round(T15_hits / n, 3)
        T20_rate = round(T20_hits / n, 3)
        T25_rate = round(T25_hits / n, 3)
        T30_rate = round(T30_hits / n, 3)

        avg_spread_abs = round(float(grp["spread_abs"].mean()), 1)
        avg_minutes    = round(float(min_series.mean()), 1)
        avg_pts        = round(float(pts_series.mean()), 1)

        actual_blowout_games = grp[grp["actual_blowout"] == True]
        competitive_games    = grp[grp["actual_blowout"] == False]
        n_actual_blowout     = len(actual_blowout_games)
        n_competitive        = len(competitive_games)

        def _sub_t25(sub: pd.DataFrame) -> "float | None":
            if len(sub) < 2:
                return None
            sub_pts = pd.to_numeric(sub["pts"], errors="coerce")
            return round(int((sub_pts >= 25).sum()) / len(sub), 3)

        actual_blowout_T25_rate = _sub_t25(actual_blowout_games)
        competitive_T25_rate    = _sub_t25(competitive_games)

        base = baseline_by_player.get(player, {})
        baseline_avg_pts     = base.get("avg_pts")
        baseline_avg_minutes = base.get("avg_minutes")
        baseline_T25_rate    = base.get("T25_rate")

        if baseline_T25_rate is not None:
            T25_delta_pp = round((T25_rate - baseline_T25_rate) * 100, 1)
        else:
            T25_delta_pp = None

        if baseline_avg_minutes is not None:
            minutes_delta = round(avg_minutes - baseline_avg_minutes, 1)
        else:
            minutes_delta = None

        # Per-player flags
        flags: list = []
        if T25_delta_pp is not None and n >= 3:
            if T25_delta_pp <= -15:
                flags.append("PLAYER_SUPPRESSED")
            elif T25_delta_pp >= 0:
                flags.append("PLAYER_RESILIENT")
        if minutes_delta is not None and minutes_delta <= -4.0:
            flags.append("MINUTES_COMPRESSED")

        # Individual game log for the evidence trail
        game_log_rows: list = []
        for _, g in grp.sort_values("game_date").iterrows():
            g_pts = pd.to_numeric(g.get("pts"), errors="coerce")
            g_min = pd.to_numeric(g.get("minutes_raw"), errors="coerce")
            g_margin = g.get("actual_margin")
            g_blowout = g.get("actual_blowout")
            g_spread = g.get("spread_abs")
            game_log_rows.append({
                "date":           str(g.get("_date_str") or ""),
                "opponent":       str(g.get("opp_abbrev") or ""),
                "spread_abs":     round(float(g_spread), 1) if pd.notna(g_spread) else None,
                "actual_margin":  round(float(g_margin), 1) if pd.notna(g_margin) else None,
                "actual_blowout": bool(g_blowout) if pd.notna(g_blowout) else None,
                "minutes":        round(float(g_min), 1) if pd.notna(g_min) else None,
                "pts":            int(g_pts) if pd.notna(g_pts) else None,
                "T20_hit":        bool(pd.notna(g_pts) and g_pts >= 20),
                "T25_hit":        bool(pd.notna(g_pts) and g_pts >= 25),
            })

        team_abbrev = str(grp["team_abbrev"].mode().iloc[0]) if not grp["team_abbrev"].mode().empty else ""

        per_player_rows.append({
            "player":                   player,
            "team":                     team_abbrev,
            "n_high_spread":            n,
            "n_actual_blowout":         n_actual_blowout,
            "n_competitive":            n_competitive,
            "avg_spread_abs":           avg_spread_abs,
            "avg_minutes":              avg_minutes,
            "avg_pts":                  avg_pts,
            "T15_hits":                 T15_hits,
            "T15_rate":                 T15_rate,
            "T20_hits":                 T20_hits,
            "T20_rate":                 T20_rate,
            "T25_hits":                 T25_hits,
            "T25_rate":                 T25_rate,
            "T30_hits":                 T30_hits,
            "T30_rate":                 T30_rate,
            "baseline_avg_pts":         baseline_avg_pts,
            "baseline_avg_minutes":     baseline_avg_minutes,
            "baseline_T25_rate":        baseline_T25_rate,
            "T25_delta_pp":             T25_delta_pp,
            "minutes_delta":            minutes_delta,
            "actual_blowout_T25_rate":  actual_blowout_T25_rate,
            "competitive_T25_rate":     competitive_T25_rate,
            "flags":                    flags,
            "game_log":                 game_log_rows,
        })

    # Sort ascending by T25_delta_pp (most suppressed first — Jokic-type outliers on top).
    # None deltas sort to the end.
    per_player_rows.sort(
        key=lambda r: (r["T25_delta_pp"] is None, r["T25_delta_pp"] if r["T25_delta_pp"] is not None else 0.0)
    )

    # ── Step 7: Verdict logic ─────────────────────────────────────────────
    verdicts: dict = {}

    # 7a — Population verdicts for primary scorers at each threshold
    for threshold in H27_SPREAD_THRESHOLDS:
        key = f"spread_{threshold}"
        cell = results[key]["primary"].get("T25", {})
        n = cell.get("n", 0) or 0
        hr = cell.get("hit_rate")
        if n < H27_MIN_N:
            verdict = f"INSUFFICIENT_SAMPLE (n={n})"
        elif hr is None:
            verdict = f"INSUFFICIENT_SAMPLE (no hit_rate, n={n})"
        elif hr >= 0.65:
            verdict = f"MAINTAINS ({hr*100:.1f}%, n={n}) — primary scorers still deliver; hard skip over-penalizes"
        elif hr >= 0.55:
            verdict = f"MARGINAL ({hr*100:.1f}%, n={n}) — confidence cap may be better than hard skip"
        else:
            verdict = f"SUPPRESSED ({hr*100:.1f}%, n={n}) — hard skip justified"
        verdicts[f"primary_T25_{key}"] = verdict

    # 7b — Actual-outcome insight at spread_abs >= 15
    key15 = "spread_15"
    pri_actual  = results[key15]["primary_actual_blowout"].get("T25", {})
    pri_comp    = results[key15]["primary_competitive"].get("T25", {})
    n_a = pri_actual.get("n", 0) or 0
    n_c = pri_comp.get("n", 0) or 0
    hr_a = pri_actual.get("hit_rate")
    hr_c = pri_comp.get("hit_rate")
    if n_a < H27_MIN_N or n_c < H27_MIN_N or hr_a is None or hr_c is None:
        outcome_insight = (
            f"OUTCOME_INSUFFICIENT_SAMPLE (actual_blowout n={n_a}, competitive n={n_c})"
        )
    else:
        delta_pp = round((hr_c - hr_a) * 100, 1)
        # "Game script dependent" means the competitive bucket scores MUCH better than the
        # actual-blowout bucket (i.e. when the game stays close, players hit; when it's a
        # real blowout, they get suppressed). Flag if delta > 10pp.
        if abs(delta_pp) > 10:
            outcome_insight = (
                f"GAME_SCRIPT_DEPENDENT (actual_blowout T25 {hr_a*100:.1f}% vs "
                f"competitive {hr_c*100:.1f}%, delta={delta_pp:+.1f}pp) — "
                f"suppression materializes only when blowout actually happens; "
                f"spread alone may not be the right trigger"
            )
        else:
            outcome_insight = (
                f"OUTCOME_INDEPENDENT (actual_blowout T25 {hr_a*100:.1f}% vs "
                f"competitive {hr_c*100:.1f}%, delta={delta_pp:+.1f}pp) — "
                f"outcome split does not meaningfully change hit rate"
            )
    verdicts["actual_outcome_insight_spread_15"] = outcome_insight

    # 7c — Jokic isolation check at spread_abs >= 15
    high15 = df[
        (df["is_favorite"] == True)
        & (df["spread_abs"] >= 15)
        & (df["scorer_role"] == "primary")
    ].copy()

    JOKIC_NAME = "Nikola Jokic"
    jokic_present = JOKIC_NAME in high15["player_name"].values

    if jokic_present:
        with_jokic_pts = pd.to_numeric(high15["pts"], errors="coerce")
        with_n = len(high15)
        with_rate = round(int((with_jokic_pts >= 25).sum()) / with_n, 3) if with_n > 0 else None

        ex_jokic = high15[high15["player_name"] != JOKIC_NAME].copy()
        ex_pts = pd.to_numeric(ex_jokic["pts"], errors="coerce")
        ex_n = len(ex_jokic)
        ex_rate = round(int((ex_pts >= 25).sum()) / ex_n, 3) if ex_n > 0 else None

        if with_rate is not None and ex_rate is not None:
            delta_pp = round((ex_rate - with_rate) * 100, 1)
            if delta_pp > 5:
                jokic_verdict = (
                    f"JOKIC_OUTLIER_CONFIRMED (T25 ex-Jokic {ex_rate*100:.1f}% "
                    f"vs with {with_rate*100:.1f}%, delta=+{delta_pp:.1f}pp, "
                    f"n_with={with_n}, n_ex={ex_n})"
                )
            else:
                jokic_verdict = (
                    f"JOKIC_OUTLIER_NOT_CONFIRMED (T25 ex-Jokic {ex_rate*100:.1f}% "
                    f"vs with {with_rate*100:.1f}%, delta={delta_pp:+.1f}pp, "
                    f"n_with={with_n}, n_ex={ex_n})"
                )
        else:
            jokic_verdict = "JOKIC_INSUFFICIENT_SAMPLE"
    else:
        jokic_verdict = "JOKIC_NOT_IN_SAMPLE (no qualifying high-spread primary games)"
    verdicts["jokic_isolation_spread_15"] = jokic_verdict

    # ── Step 8: Print report ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  H27 — PRIMARY SCORER BLOWOUT PTS PERFORMANCE")
    print(f"  Uses PRE-GAME SPREAD (not final margin)")
    print(f"  Actual-outcome overlay: margin >= {H27_ACTUAL_BLOWOUT_MARGIN} = blowout materialized")
    print(f"  Date range: {df['game_date'].min().date()} → {df['game_date'].max().date()}")
    print(f"  Favored-side only (negative spread)")
    print(f"{'='*65}")

    bucket_order = [
        ("primary",                  "primary"),
        ("pri_actual_blowout",       "primary_actual_blowout"),
        ("pri_competitive",          "primary_competitive"),
        ("secondary",                "secondary"),
        ("sec_actual_blowout",       "secondary_actual_blowout"),
        ("sec_competitive",          "secondary_competitive"),
        ("baseline_primary",         "baseline_primary"),
        ("baseline_secondary",       "baseline_secondary"),
    ]

    def _fmt_rate(cell: dict) -> str:
        hr = cell.get("hit_rate")
        n  = cell.get("n", 0) or 0
        if hr is None:
            return f"   n/a ({n})"
        return f"{hr*100:5.1f}% ({n})"

    def _fmt_min(cell: dict) -> str:
        am = cell.get("avg_minutes")
        if am is None:
            return "  n/a"
        return f"{am:5.1f}"

    for threshold in H27_SPREAD_THRESHOLDS:
        key = f"spread_{threshold}"
        r = results[key]
        n_pri = r.get("n_primary", 0)
        n_sec = r.get("n_secondary", 0)
        print(f"\n  SPREAD_ABS >= {threshold}  (n_primary={n_pri}, n_secondary={n_sec})")
        print(f"  {'─'*61}")
        header = f"  {'Bucket':<22}{'T15':>13}{'T20':>13}{'T25':>13}{'T30':>13}  {'avg_min':>7}"
        print(header)
        for label, res_key in bucket_order:
            cell_map = r.get(res_key) or {}
            t15 = _fmt_rate(cell_map.get("T15", {}))
            t20 = _fmt_rate(cell_map.get("T20", {}))
            t25 = _fmt_rate(cell_map.get("T25", {}))
            t30 = _fmt_rate(cell_map.get("T30", {}))
            # avg_minutes is invariant across tiers for a given bucket; pull from T15
            am  = _fmt_min(cell_map.get("T15", {}))
            print(f"  {label:<22}{t15:>13}{t20:>13}{t25:>13}{t30:>13}  {am:>7}")

    # Per-player table
    print(f"\n  PER-PLAYER PRIMARY SCORERS (spread_abs >= 15, n >= {H27_MIN_PLAYER_N})")
    print(f"  {'─'*61}")
    if not per_player_rows:
        print(f"  (no primary scorers with n >= {H27_MIN_PLAYER_N})")
    else:
        header = (
            f"  {'Player':<22}{'Team':<6}{'n':>3}  {'blow/comp':>9}  "
            f"{'avg_sprd':>9}  {'avg_min':>8}  {'min_d':>6}  "
            f"{'avg_pts':>8}  {'T20':>7}  {'T25':>7}  "
            f"{'base_T25':>9}  {'delta':>8}   {'flags'}"
        )
        print(header)
        for row in per_player_rows:
            player = (row["player"] or "")[:22]
            team   = (row["team"]   or "")[:5]
            n      = row["n_high_spread"]
            blow_comp = f"{row['n_actual_blowout']}/{row['n_competitive']}"
            avg_s  = row["avg_spread_abs"]
            avg_m  = row["avg_minutes"]
            min_d  = row["minutes_delta"]
            avg_p  = row["avg_pts"]
            t20_frac = f"{row['T20_hits']}/{n}"
            t25_frac = f"{row['T25_hits']}/{n}"
            base_t25 = row["baseline_T25_rate"]
            delta    = row["T25_delta_pp"]
            flags_str = ", ".join(row["flags"]) if row["flags"] else ""

            min_d_str  = f"{min_d:+.1f}" if min_d is not None else "  n/a"
            base_str   = f"{base_t25*100:.1f}%" if base_t25 is not None else "  n/a"
            delta_str  = f"{delta:+.1f}pp" if delta is not None else "    n/a"

            print(
                f"  {player:<22}{team:<6}{n:>3}  {blow_comp:>9}  "
                f"{avg_s:>9.1f}  {avg_m:>8.1f}  {min_d_str:>6}  "
                f"{avg_p:>8.1f}  {t20_frac:>7}  {t25_frac:>7}  "
                f"{base_str:>9}  {delta_str:>8}   {flags_str}"
            )

    print(f"\n  VERDICTS:")
    for threshold in H27_SPREAD_THRESHOLDS:
        vkey = f"primary_T25_spread_{threshold}"
        print(f"    spread_abs >= {threshold} primary T25: {verdicts.get(vkey, '?')}")
    print(f"    Actual-outcome insight (>= 15): {verdicts.get('actual_outcome_insight_spread_15', '?')}")
    print(f"    Jokic isolation: {verdicts.get('jokic_isolation_spread_15', '?')}")

    # ── Step 9: Write JSON output ─────────────────────────────────────────
    out = {
        "generated_at": dt.date.today().isoformat(),
        "mode":         "primary-blowout",
        "date_range": {
            "start": str(df["game_date"].min().date()),
            "end":   str(df["game_date"].max().date()),
        },
        "constants": {
            "H27_SPREAD_THRESHOLDS":     H27_SPREAD_THRESHOLDS,
            "H27_PTS_TIERS":             H27_PTS_TIERS,
            "H27_MIN_N":                 H27_MIN_N,
            "H27_MIN_PLAYER_N":          H27_MIN_PLAYER_N,
            "H27_ACTUAL_BLOWOUT_MARGIN": H27_ACTUAL_BLOWOUT_MARGIN,
            "rolling_window":            window,
        },
        "results":          results,
        "per_player":       per_player_rows,
        "verdicts":         verdicts,
    }
    out_path = Path(args.output) if getattr(args, "output", None) else PRIMARY_BLOWOUT_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H27 results → {out_path}")


# ── H28 — Playoff Career Tier Performance ───────────────────────────

def run_playoff_career_analysis(args) -> None:
    """
    H28 — Playoff Career Tier Performance.

    Compares same-player regular season vs playoff tier hit rates across
    PTS/REB/AST/3PM using multi-year career data from playoff_career_log.csv
    (seasons 2021–2025). Produces per-player flags (ELEVATOR/STABLE/SUPPRESSOR
    per stat, plus a cross-stat overall flag) that identify which players
    historically elevate their production in playoffs and which compress.

    Does NOT use load_player_log() / load_whitelist() — those expect the
    player_game_log.csv schema. Loads playoff_career_log.csv directly so
    regular and playoff comparisons use the same multi-year window and
    identical schema.

    Output feeds a future playoff context block injection into the analyst
    prompt — NOT a standalone rule. No analyst.py changes in this task.
    """
    if not PLAYOFF_CAREER_CSV.exists():
        print(f"[backtest] ERROR: {PLAYOFF_CAREER_CSV} not found.")
        return

    # ── Step 1: Load and validate data ────────────────────────────────────
    df = pd.read_csv(PLAYOFF_CAREER_CSV)

    # Filter All-Star / Rising Stars games from regular-season baseline.
    # These have non-standard team abbreviations and only appear in regular season.
    df = df[~df["team_abbrev"].isin(H28_ALLSTAR_TEAMS)].copy()
    # Filter zero-minute appearances (DNPs — no `dnp` column in this CSV)
    df = df[df["minutes"] > 0].copy()

    reg = df[df["season_type"] == "regular"].copy()
    po  = df[df["season_type"] == "playoff"].copy()

    print(f"[backtest] H28 playoff-career | "
          f"{len(reg):,} regular games, {len(po):,} playoff games")
    print(f"[backtest] {po['player_name'].nunique()} players with playoff data "
          f"(seasons {int(df['season'].min())}–{int(df['season'].max())})")

    if po.empty:
        print("[backtest] WARNING: no playoff games — cannot run H28.")
        return

    # ── Step 2: Per-player per-stat per-tier hit rates ────────────────────
    player_entries: list = []
    limited_entries: list = []

    for player_name, player_po in po.groupby("player_name"):
        n_playoff = len(player_po)
        if n_playoff < H28_LIMITED_SAMPLE_MIN:
            continue

        player_reg = reg[reg["player_name"] == player_name]
        n_regular = len(player_reg)
        if n_regular == 0:
            # No regular-season baseline — cannot compute deltas.
            continue

        sample_flag = (
            "reliable"
            if n_playoff >= H28_MIN_PLAYOFF_GAMES
            else "limited_sample"
        )

        # Per-stat detail
        stats_out: dict = {}
        flag_counts = {"ELEVATOR": 0, "STABLE": 0, "SUPPRESSOR": 0}

        for stat in H28_STATS:
            col = H28_STAT_COL[stat]
            key_tier = H28_KEY_TIER[stat]

            tiers_out: dict = {}
            key_reg_rate = None
            key_po_rate = None
            key_delta_pp = None

            for tier in H28_TIERS[stat]:
                reg_hits = int((player_reg[col] >= tier).sum())
                reg_rate = round(reg_hits / n_regular, 3) if n_regular > 0 else None
                po_hits  = int((player_po[col] >= tier).sum())
                po_rate  = round(po_hits / n_playoff, 3)
                if reg_rate is not None:
                    delta_pp = round((po_rate - reg_rate) * 100, 1)
                else:
                    delta_pp = None
                tiers_out[f"T{tier}"] = {
                    "reg_hits": reg_hits,
                    "reg_rate": reg_rate,
                    "po_hits":  po_hits,
                    "po_rate":  po_rate,
                    "delta_pp": delta_pp,
                }
                if tier == key_tier:
                    key_reg_rate = reg_rate
                    key_po_rate  = po_rate
                    key_delta_pp = delta_pp

            # Per-stat flag at key tier
            if key_delta_pp is None:
                flag = "STABLE"
            elif key_delta_pp >= H28_ELEVATOR_THRESHOLD:
                flag = "ELEVATOR"
            elif key_delta_pp <= H28_SUPPRESSOR_THRESHOLD:
                flag = "SUPPRESSOR"
            else:
                flag = "STABLE"
            flag_counts[flag] += 1

            reg_avg = round(float(player_reg[col].mean()), 1) if n_regular > 0 else None
            po_avg  = round(float(player_po[col].mean()), 1)
            avg_delta = (
                round(po_avg - reg_avg, 1) if reg_avg is not None else None
            )

            stats_out[stat] = {
                "flag":              flag,
                "key_tier":          key_tier,
                "key_tier_reg_rate": key_reg_rate,
                "key_tier_po_rate":  key_po_rate,
                "key_tier_delta_pp": key_delta_pp,
                "tiers":             tiers_out,
                "reg_avg":           reg_avg,
                "po_avg":            po_avg,
                "avg_delta":         avg_delta,
            }

        # ── Step 3: Overall flag (cross-stat pattern) ─────────────────────
        n_elev = flag_counts["ELEVATOR"]
        n_supp = flag_counts["SUPPRESSOR"]
        n_stab = flag_counts["STABLE"]
        if n_elev >= 3:
            overall_flag = "STRONG_ELEVATOR"
        elif n_elev >= 2 and n_supp == 0:
            overall_flag = "ELEVATOR"
        elif n_supp >= 3:
            overall_flag = "STRONG_SUPPRESSOR"
        elif n_supp >= 2 and n_elev == 0:
            overall_flag = "SUPPRESSOR"
        elif n_stab == 4:
            overall_flag = "STABLE"
        else:
            overall_flag = "MIXED"

        # ── Step 4: Minutes + game log + entry assembly ───────────────────
        reg_avg_min = round(float(player_reg["minutes"].mean()), 1) if n_regular > 0 else None
        po_avg_min  = round(float(player_po["minutes"].mean()), 1)
        minutes_delta = (
            round(po_avg_min - reg_avg_min, 1) if reg_avg_min is not None else None
        )

        playoff_seasons = sorted([int(s) for s in player_po["season"].unique().tolist()])

        game_log = [
            {
                "date":      str(row["game_date"]),
                "season":    int(row["season"]),
                "opponent":  str(row["opp_abbrev"]),
                "home_away": str(row["home_away"]),
                "minutes":   round(float(row["minutes"]), 1),
                "pts":       int(row["pts"]),
                "reb":       int(row["reb"]),
                "ast":       int(row["ast"]),
                "tpm":       int(row["tpm"]),
            }
            for _, row in player_po.sort_values("game_date").iterrows()
        ]

        # Total absolute delta across all 4 stat key tiers — for sorting.
        total_abs_delta = sum(
            abs(s["key_tier_delta_pp"] or 0) for s in stats_out.values()
        )

        entry = {
            "player":          player_name,
            "team":            str(player_po.sort_values("game_date")["team_abbrev"].iloc[-1]),
            "n_playoff":       n_playoff,
            "n_regular":       n_regular,
            "playoff_seasons": playoff_seasons,
            "sample_flag":     sample_flag,
            "reg_avg_minutes": reg_avg_min,
            "po_avg_minutes":  po_avg_min,
            "minutes_delta":   minutes_delta,
            "stats":           stats_out,
            "overall_flag":    overall_flag,
            "_total_abs_delta": total_abs_delta,
            "playoff_game_log": game_log,
        }

        if sample_flag == "reliable":
            player_entries.append(entry)
        else:
            limited_entries.append(entry)

    # ── Step 4b: Sort ─────────────────────────────────────────────────────
    flag_priority = {
        "STRONG_ELEVATOR":    0,
        "ELEVATOR":           1,
        "MIXED":              2,
        "STABLE":             3,
        "SUPPRESSOR":         4,
        "STRONG_SUPPRESSOR":  5,
    }
    def _sort_key(entry):
        return (
            flag_priority.get(entry["overall_flag"], 99),
            -entry["_total_abs_delta"],
            entry["player"],
        )
    player_entries.sort(key=_sort_key)
    limited_entries.sort(key=_sort_key)

    # ── Step 5: Population aggregation (pooled across qualifying players) ──
    pool_players = {e["player"] for e in player_entries + limited_entries}
    reg_pool = reg[reg["player_name"].isin(pool_players)].copy()
    po_pool  = po[po["player_name"].isin(pool_players)].copy()

    population: dict = {}
    for stat in H28_STATS:
        col = H28_STAT_COL[stat]
        stat_out: dict = {}
        for tier in H28_TIERS[stat]:
            reg_n = len(reg_pool)
            po_n  = len(po_pool)
            reg_hits = int((reg_pool[col] >= tier).sum())
            po_hits  = int((po_pool[col] >= tier).sum())
            reg_rate = round(reg_hits / reg_n, 3) if reg_n > 0 else None
            po_rate  = round(po_hits / po_n, 3)  if po_n  > 0 else None
            if reg_rate is not None and po_rate is not None:
                delta_pp = round((po_rate - reg_rate) * 100, 1)
            else:
                delta_pp = None
            stat_out[f"T{tier}"] = {
                "reg_n":    reg_n,
                "reg_hits": reg_hits,
                "reg_rate": reg_rate,
                "po_n":     po_n,
                "po_hits":  po_hits,
                "po_rate":  po_rate,
                "delta_pp": delta_pp,
            }
        population[stat] = stat_out

    # ── Step 6: Print report ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  H28 — PLAYOFF CAREER TIER PERFORMANCE")
    print(f"  Data: playoff_career_log.csv "
          f"(seasons {int(df['season'].min())}–{int(df['season'].max())})")
    print(f"  Regular: {len(reg):,} games | Playoff: {len(po):,} games | "
          f"{len(player_entries) + len(limited_entries)} players qualified")
    print(f"{'='*65}")

    # Population table
    print(f"\n  POPULATION (pooled, {len(pool_players)} qualifying players)")
    print(f"  {'─'*61}")
    print(f"  {'Stat':<6}{'Tier':<7}{'reg_rate':>10}{'po_rate':>11}{'delta':>10}")
    for stat in H28_STATS:
        for tier in H28_TIERS[stat]:
            cell = population[stat][f"T{tier}"]
            rr = cell["reg_rate"]
            pr = cell["po_rate"]
            dp = cell["delta_pp"]
            rr_s = f"{rr*100:6.1f}%" if rr is not None else "   n/a"
            pr_s = f"{pr*100:6.1f}%" if pr is not None else "   n/a"
            dp_s = f"{dp:+6.1f}pp" if dp is not None else "   n/a"
            print(f"  {stat:<6}T{tier:<6}{rr_s:>10}{pr_s:>11}{dp_s:>10}")

    # Per-player table
    def _stat_cell(entry: dict, stat: str) -> str:
        s = entry["stats"].get(stat, {})
        rr = s.get("key_tier_reg_rate")
        pr = s.get("key_tier_po_rate")
        dp = s.get("key_tier_delta_pp")
        if rr is None or pr is None:
            return "      n/a".ljust(15)
        rr_i = int(round(rr * 100))
        pr_i = int(round(pr * 100))
        dp_s = f"{dp:+5.1f}pp" if dp is not None else "   n/a"
        return f"{rr_i:>2}→{pr_i:<2} {dp_s}".ljust(15)

    header = (
        f"  {'Player':<24}{'Team':<6}{'po_n':>5}{'min_d':>7}  "
        f"{'PTS(T20)':<15}{'REB(T6)':<15}{'AST(T4)':<15}{'3PM(T2)':<15}"
        f"  {'overall'}"
    )

    if player_entries:
        print(f"\n  PER-PLAYER ADJUSTMENTS — reliable (n_playoff >= {H28_MIN_PLAYOFF_GAMES})")
        print(f"  {'─'*61}")
        print(header)
        for e in player_entries:
            player = (e["player"] or "")[:24]
            team   = (e["team"]   or "")[:5]
            po_n   = e["n_playoff"]
            md     = e["minutes_delta"]
            md_s   = f"{md:+5.1f}" if md is not None else "  n/a"
            pts_c  = _stat_cell(e, "PTS")
            reb_c  = _stat_cell(e, "REB")
            ast_c  = _stat_cell(e, "AST")
            tpm_c  = _stat_cell(e, "3PM")
            flag   = e["overall_flag"]
            print(
                f"  {player:<24}{team:<6}{po_n:>5}{md_s:>7}  "
                f"{pts_c}{reb_c}{ast_c}{tpm_c}  {flag}"
            )

    if limited_entries:
        print(f"\n  PER-PLAYER ADJUSTMENTS — ⚠ limited_sample "
              f"({H28_LIMITED_SAMPLE_MIN}–{H28_MIN_PLAYOFF_GAMES - 1} playoff games)")
        print(f"  {'─'*61}")
        print(header)
        for e in limited_entries:
            player = ("⚠ " + (e["player"] or ""))[:24]
            team   = (e["team"] or "")[:5]
            po_n   = e["n_playoff"]
            md     = e["minutes_delta"]
            md_s   = f"{md:+5.1f}" if md is not None else "  n/a"
            pts_c  = _stat_cell(e, "PTS")
            reb_c  = _stat_cell(e, "REB")
            ast_c  = _stat_cell(e, "AST")
            tpm_c  = _stat_cell(e, "3PM")
            flag   = e["overall_flag"]
            print(
                f"  {player:<24}{team:<6}{po_n:>5}{md_s:>7}  "
                f"{pts_c}{reb_c}{ast_c}{tpm_c}  {flag}"
            )

    # ── Step 7: Write JSON output ─────────────────────────────────────────
    def _clean(entry: dict) -> dict:
        """Drop private sort-helper fields before JSON serialization."""
        return {k: v for k, v in entry.items() if not k.startswith("_")}

    all_entries_clean = [_clean(e) for e in player_entries + limited_entries]
    summary = {e["player"]: e["overall_flag"] for e in all_entries_clean}

    out = {
        "metadata": {
            "generated_at":    dt.date.today().isoformat(),
            "mode":            "playoff-career",
            "data_file":       str(PLAYOFF_CAREER_CSV),
            "season_range":    [int(df["season"].min()), int(df["season"].max())],
            "n_regular_games": len(reg),
            "n_playoff_games": len(po),
            "n_players":       len(all_entries_clean),
            "n_reliable":      len(player_entries),
            "n_limited":       len(limited_entries),
            "constants": {
                "H28_MIN_PLAYOFF_GAMES":    H28_MIN_PLAYOFF_GAMES,
                "H28_LIMITED_SAMPLE_MIN":   H28_LIMITED_SAMPLE_MIN,
                "H28_ELEVATOR_THRESHOLD":   H28_ELEVATOR_THRESHOLD,
                "H28_SUPPRESSOR_THRESHOLD": H28_SUPPRESSOR_THRESHOLD,
                "H28_KEY_TIER":             H28_KEY_TIER,
                "H28_TIERS":                H28_TIERS,
            },
        },
        "population": population,
        "players":    all_entries_clean,
        "summary":    summary,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else PLAYOFF_CAREER_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H28 results → {out_path}")


# ── H29 — Player-Level Confidence Calibration ───────────────────────

def run_confidence_calibration_analysis(picks: list, args) -> None:
    """
    H29 — Player-Level Confidence Calibration.

    Audits the analyst's assigned confidence against actual hit rates,
    per player. For each player with >= H29_MIN_PICKS graded picks,
    computes the calibration delta (actual_hit_rate - avg_confidence)
    and flags OVER_CONFIDENT / UNDER_CONFIDENT / WELL_CALIBRATED.

    This is a pure meta-correction — it audits how accurately the system
    uses its existing signals for each player, without adding any new
    signal. With playoffs narrowing the pick pool to ~20 players,
    per-player calibration deltas become directly actionable confidence
    adjustments for repeated series-game picks.

    Uses picks.json exclusively via load_picks_json(). Does NOT read
    player_game_log.csv or playoff_career_log.csv.

    Output feeds future analyst prompt calibration notes — NOT a
    standalone rule. No analyst.py changes in this task.
    """
    if not picks:
        print("[backtest] WARNING: no picks provided to H29.")
        return

    # ── Step 1: Optional date filter + enrich ─────────────────────────────
    if getattr(args, "start", None):
        picks = [p for p in picks if p.get("date", "") >= args.start]
    if getattr(args, "end", None):
        picks = [p for p in picks if p.get("date", "") <= args.end]

    enriched: list = []
    for p in picks:
        conf = p.get("confidence_pct")
        if conf is None:
            continue
        try:
            conf_int = int(conf)
        except (ValueError, TypeError):
            continue
        enriched.append({
            "player":        (p.get("player_name") or "").strip(),
            "prop_type":     p.get("prop_type", ""),
            "confidence_pct": conf_int,
            "hit":           p.get("result") == "HIT",
            "pick_value":    p.get("pick_value"),
            "actual_value":  p.get("actual_value"),
            "date":          p.get("date", ""),
        })

    if not enriched:
        print("[backtest] WARNING: no picks with confidence after filtering — cannot run H29.")
        return

    total_n     = len(enriched)
    total_hits  = sum(1 for p in enriched if p["hit"])
    total_rate  = round(total_hits / total_n, 3) if total_n > 0 else None
    total_avg_conf = round(sum(p["confidence_pct"] for p in enriched) / total_n, 1)

    date_min = min(p["date"] for p in enriched if p["date"]) if enriched else ""
    date_max = max(p["date"] for p in enriched if p["date"]) if enriched else ""

    print(f"[backtest] H29 confidence-calibration | "
          f"{total_n} graded picks | "
          f"overall {total_hits}/{total_n} = {(total_rate or 0)*100:.1f}% | "
          f"avg confidence = {total_avg_conf}%")

    # ── Step 2: Population confidence band calibration ────────────────────
    population_bands: dict = {}
    for lo, hi, label in H29_CONF_BANDS:
        band_picks = [p for p in enriched if lo <= p["confidence_pct"] <= hi]
        n = len(band_picks)
        hits = sum(1 for p in band_picks if p["hit"])
        if n > 0:
            hit_rate = round(hits / n, 3)
            avg_conf = round(sum(p["confidence_pct"] for p in band_picks) / n, 1)
            delta_pp = round((hit_rate * 100) - avg_conf, 1)
        else:
            hit_rate = None
            avg_conf = None
            delta_pp = None
        population_bands[label] = {
            "n":              n,
            "hits":           hits,
            "hit_rate":       hit_rate,
            "avg_confidence": avg_conf,
            "delta_pp":       delta_pp,
            "band_lo":        lo,
            "band_hi":        hi,
        }

    # ── Step 3: Per-player calibration ────────────────────────────────────
    by_player: dict = {}
    for p in enriched:
        by_player.setdefault(p["player"], []).append(p)

    player_entries: list = []
    for player_name, player_picks in by_player.items():
        n_picks = len(player_picks)
        if n_picks < H29_MIN_PICKS:
            continue

        n_hits           = sum(1 for p in player_picks if p["hit"])
        actual_hit_rate  = round(n_hits / n_picks, 3)
        avg_confidence   = round(
            sum(p["confidence_pct"] for p in player_picks) / n_picks, 1
        )
        calibration_delta_pp = round(
            (actual_hit_rate * 100) - avg_confidence, 1
        )

        # Per-prop breakdown (props with >= H29_MIN_PROP_PICKS)
        by_prop: dict = {}
        prop_buckets: dict = {}
        for p in player_picks:
            prop_buckets.setdefault(p["prop_type"], []).append(p)
        for prop, prop_picks in prop_buckets.items():
            n_prop = len(prop_picks)
            if n_prop < H29_MIN_PROP_PICKS:
                continue
            hits_prop = sum(1 for p in prop_picks if p["hit"])
            hr_prop   = round(hits_prop / n_prop, 3)
            avg_prop  = round(
                sum(p["confidence_pct"] for p in prop_picks) / n_prop, 1
            )
            delta_prop = round((hr_prop * 100) - avg_prop, 1)
            by_prop[prop] = {
                "n":              n_prop,
                "hits":           hits_prop,
                "hit_rate":       hr_prop,
                "avg_confidence": avg_prop,
                "delta_pp":       delta_prop,
            }

        # Per-band breakdown (bands with >= H29_MIN_BAND_PICKS)
        by_band: dict = {}
        for lo, hi, label in H29_CONF_BANDS:
            band_picks = [
                p for p in player_picks
                if lo <= p["confidence_pct"] <= hi
            ]
            n_band = len(band_picks)
            if n_band < H29_MIN_BAND_PICKS:
                continue
            hits_band = sum(1 for p in band_picks if p["hit"])
            hr_band   = round(hits_band / n_band, 3)
            avg_band  = round(
                sum(p["confidence_pct"] for p in band_picks) / n_band, 1
            )
            delta_band = round((hr_band * 100) - avg_band, 1)
            by_band[label] = {
                "n":              n_band,
                "hits":           hits_band,
                "hit_rate":       hr_band,
                "avg_confidence": avg_band,
                "delta_pp":       delta_band,
            }

        # Miss severity
        misses = [p for p in player_picks if not p["hit"]]
        miss_count = len(misses)
        miss_margins: list = []
        for m in misses:
            av = m.get("actual_value")
            pv = m.get("pick_value")
            if av is None or pv is None:
                continue
            try:
                miss_margins.append(float(pv) - float(av))
            except (ValueError, TypeError):
                continue
        if miss_margins:
            avg_miss_margin = round(sum(miss_margins) / len(miss_margins), 1)
        else:
            avg_miss_margin = None

        # Step 4 — Flag
        if calibration_delta_pp <= -H29_OVER_CONF_THRESHOLD:
            flag = "OVER_CONFIDENT"
        elif calibration_delta_pp >= H29_UNDER_CONF_THRESHOLD:
            flag = "UNDER_CONFIDENT"
        else:
            flag = "WELL_CALIBRATED"

        player_dates = [p["date"] for p in player_picks if p["date"]]
        first_pick = min(player_dates) if player_dates else ""
        last_pick  = max(player_dates) if player_dates else ""

        player_entries.append({
            "player":               player_name,
            "n_picks":              n_picks,
            "n_hits":               n_hits,
            "actual_hit_rate":      actual_hit_rate,
            "avg_confidence":       avg_confidence,
            "calibration_delta_pp": calibration_delta_pp,
            "flag":                 flag,
            "miss_count":           miss_count,
            "avg_miss_margin":      avg_miss_margin,
            "by_prop":              by_prop,
            "by_band":              by_band,
            "first_pick":           first_pick,
            "last_pick":            last_pick,
        })

    # Sort by calibration_delta_pp ascending (most over-confident first)
    player_entries.sort(key=lambda e: (e["calibration_delta_pp"], e["player"]))

    # ── Step 5: Summary lists ─────────────────────────────────────────────
    over_confident  = [e for e in player_entries if e["flag"] == "OVER_CONFIDENT"]
    under_confident = [e for e in player_entries if e["flag"] == "UNDER_CONFIDENT"]
    well_calibrated = [e for e in player_entries if e["flag"] == "WELL_CALIBRATED"]

    # ── Step 6: Print report ──────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  H29 — PLAYER-LEVEL CONFIDENCE CALIBRATION")
    print(f"  Source: picks.json ({total_n} graded picks)")
    print(f"  Date range: {date_min} → {date_max}")
    print(f"  Overall: {total_hits}/{total_n} = {(total_rate or 0)*100:.1f}% | "
          f"avg assigned = {total_avg_conf}%")
    print(f"{'='*65}")

    # Population bands
    print(f"\n  POPULATION CONFIDENCE BANDS")
    print(f"  {'─'*61}")
    print(f"  {'Band':<8}{'n':>6}{'avg_conf':>11}{'actual':>11}{'delta':>12}  notes")
    for lo, hi, label in H29_CONF_BANDS:
        b = population_bands[label]
        n  = b["n"]
        ac = b["avg_confidence"]
        hr = b["hit_rate"]
        dp = b["delta_pp"]
        ac_s = f"{ac:.1f}%" if ac is not None else "   n/a"
        hr_s = f"{hr*100:.1f}%" if hr is not None else "   n/a"
        dp_s = f"{dp:+.1f}pp" if dp is not None else "    n/a"
        note = ""
        if dp is not None:
            if dp >= H29_UNDER_CONF_THRESHOLD:
                note = "UNDER_CONFIDENT"
            elif dp <= -H29_OVER_CONF_THRESHOLD:
                note = "OVER_CONFIDENT"
        print(f"  {label:<8}{n:>6}{ac_s:>11}{hr_s:>11}{dp_s:>12}  {note}")

    # Per-player table
    print(f"\n  PER-PLAYER CALIBRATION (n >= {H29_MIN_PICKS}, sorted by delta ascending)")
    print(f"  {'─'*61}")
    if not player_entries:
        print(f"  (no players with n >= {H29_MIN_PICKS})")
    else:
        header = (
            f"  {'Player':<24}{'n':>4}{'hits':>6}{'actual':>9}"
            f"{'avg_conf':>11}{'delta':>11}{'miss_mgn':>11}  flag"
        )
        print(header)
        for e in player_entries:
            player = (e["player"] or "")[:24]
            n      = e["n_picks"]
            hits   = e["n_hits"]
            actual = e["actual_hit_rate"]
            avg_c  = e["avg_confidence"]
            delta  = e["calibration_delta_pp"]
            mgn    = e["avg_miss_margin"]
            flag   = e["flag"]
            actual_s = f"{actual*100:.1f}%"
            avg_c_s  = f"{avg_c:.1f}%"
            delta_s  = f"{delta:+.1f}pp"
            mgn_s    = f"{mgn:.1f}" if mgn is not None else "n/a"
            print(
                f"  {player:<24}{n:>4}{hits:>6}{actual_s:>9}"
                f"{avg_c_s:>11}{delta_s:>11}{mgn_s:>11}  {flag}"
            )

    # Over-confident highlights
    if over_confident:
        print(f"\n  OVER-CONFIDENT PLAYERS (n >= {H29_MIN_PICKS}, delta <= -{int(H29_OVER_CONF_THRESHOLD)}pp):")
        for e in over_confident:
            print(
                f"    {e['player']}: {e['actual_hit_rate']*100:.1f}% actual vs "
                f"{e['avg_confidence']:.1f}% assigned "
                f"(delta {e['calibration_delta_pp']:+.1f}pp, n={e['n_picks']})"
            )
            for prop, b in e["by_prop"].items():
                tag = ""
                if b["delta_pp"] <= -H29_OVER_CONF_THRESHOLD:
                    tag = " ← prop-specific over-confidence"
                print(
                    f"      {prop}: {b['hit_rate']*100:.1f}% actual vs "
                    f"{b['avg_confidence']:.1f}% assigned (n={b['n']}){tag}"
                )

    # Under-confident highlights
    if under_confident:
        print(f"\n  UNDER-CONFIDENT PLAYERS (n >= {H29_MIN_PICKS}, delta >= +{int(H29_UNDER_CONF_THRESHOLD)}pp):")
        for e in under_confident:
            print(
                f"    {e['player']}: {e['actual_hit_rate']*100:.1f}% actual vs "
                f"{e['avg_confidence']:.1f}% assigned "
                f"(delta {e['calibration_delta_pp']:+.1f}pp, n={e['n_picks']})"
            )
            for prop, b in e["by_prop"].items():
                tag = ""
                if b["delta_pp"] >= H29_UNDER_CONF_THRESHOLD:
                    tag = " ← consistent under-rating"
                print(
                    f"      {prop}: {b['hit_rate']*100:.1f}% actual vs "
                    f"{b['avg_confidence']:.1f}% assigned (n={b['n']}){tag}"
                )

    # ── Step 7: Write JSON output ─────────────────────────────────────────
    out = {
        "metadata": {
            "generated_at":     dt.date.today().isoformat(),
            "mode":             "confidence-calibration",
            "n_total_picks":    total_n,
            "n_total_hits":     total_hits,
            "overall_hit_rate": total_rate,
            "avg_confidence":   total_avg_conf,
            "date_range": {
                "start": date_min,
                "end":   date_max,
            },
            "constants": {
                "H29_MIN_PICKS":            H29_MIN_PICKS,
                "H29_MIN_PROP_PICKS":       H29_MIN_PROP_PICKS,
                "H29_MIN_BAND_PICKS":       H29_MIN_BAND_PICKS,
                "H29_OVER_CONF_THRESHOLD":  H29_OVER_CONF_THRESHOLD,
                "H29_UNDER_CONF_THRESHOLD": H29_UNDER_CONF_THRESHOLD,
                "H29_CONF_BANDS":           [[lo, hi, label] for lo, hi, label in H29_CONF_BANDS],
            },
        },
        "population_bands": population_bands,
        "players":          player_entries,
        "summary": {
            "n_players":        len(player_entries),
            "n_over_confident": len(over_confident),
            "n_under_confident": len(under_confident),
            "n_well_calibrated": len(well_calibrated),
            "over_confident_players":  [e["player"] for e in over_confident],
            "under_confident_players": [e["player"] for e in under_confident],
        },
    }

    out_path = Path(args.output) if getattr(args, "output", None) else CONFIDENCE_CAL_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H29 results → {out_path}")


# ── H30 — Minutes Elasticity ─────────────────────────────────────────

def run_minutes_elasticity_analysis(player_log: pd.DataFrame, args) -> None:
    """
    H30 — Minutes Elasticity.

    Quantifies each player's production-vs-minutes relationship across four
    absolute minutes buckets: low (<30), normal (30-34), high (34-38),
    extended (38+). Elasticity is measured as the delta between "extended"
    and "normal" hit rates at each stat's key tier. Flags players as
    SCALES (delta >= +10pp), PLATEAUS (-10 to +10), or INVERTS (delta <= -10pp).

    Motivated by the structural minutes increase in playoff basketball:
    starters routinely play 36-42 min vs 32-36 regular season. Aggregate
    tier rates are diluted by low-minute games that won't recur in playoffs,
    so a player with a 50% aggregate T25 but 90% T25 at 38+ min is a
    structurally stronger playoff T25 pick than the aggregate suggests.

    Uses player_game_log.csv only (via load_player_log()). Does NOT read
    nba_master.csv, picks.json, or playoff_career_log.csv.

    Output feeds a future playoff confidence adjustment layer — NOT a
    standalone rule. No analyst.py changes in this task.
    """
    if player_log.empty:
        print("[backtest] WARNING: player_log is empty — cannot run H30.")
        return

    # ── Step 1: Add minutes buckets ──────────────────────────────────────
    df = player_log.copy()
    df["minutes_raw"] = pd.to_numeric(df["minutes_raw"], errors="coerce")
    df = df[df["minutes_raw"].notna() & (df["minutes_raw"] > 0)].copy()

    # right=False → [0,30)=low, [30,34)=normal, [34,38)=high, [38,60)=extended
    df["min_bucket"] = pd.cut(
        df["minutes_raw"],
        bins=H30_MINUTES_BINS,
        labels=H30_MINUTES_LABELS,
        right=False,
    )

    print(f"[backtest] H30 minutes-elasticity | "
          f"{len(df):,} player-games | "
          f"{df['player_name'].nunique()} unique players")
    print(f"[backtest] buckets: low(<30), normal(30-34), high(34-38), extended(38+) | "
          f"min_bucket_n={H30_MIN_BUCKET_N} | min_total_games={H30_MIN_TOTAL_GAMES}")

    # ── Step 2: Per-player, per-stat elasticity ──────────────────────────
    player_entries: list = []

    for player_name, player_games in df.groupby("player_name"):
        n_total = len(player_games)
        if n_total < H30_MIN_TOTAL_GAMES:
            continue

        team_abbrev = (
            str(player_games.sort_values("game_date")["team_abbrev"].iloc[-1])
            if not player_games.empty else ""
        )
        avg_minutes = round(float(player_games["minutes_raw"].mean()), 1)

        bucket_counts = {
            bucket: int(len(player_games[player_games["min_bucket"] == bucket]))
            for bucket in H30_MINUTES_LABELS
        }

        stats_out: dict = {}
        for stat in H30_STATS:
            col = H30_STAT_COL[stat]
            key_tier = H30_KEY_TIER[stat]

            # Overall key-tier rate (all games for this player)
            overall_hits = int((player_games[col] >= key_tier).sum())
            overall_rate = round(overall_hits / n_total, 3) if n_total > 0 else None

            # Per-tier, per-bucket detail
            tiers_out: dict = {}
            for tier in H30_TIERS[stat]:
                bucket_cells: dict = {}
                for bucket in H30_MINUTES_LABELS:
                    sub = player_games[player_games["min_bucket"] == bucket]
                    n_b = len(sub)
                    if n_b < H30_MIN_BUCKET_N:
                        continue
                    hits_b = int((sub[col] >= tier).sum())
                    rate_b = round(hits_b / n_b, 3)
                    avg_b  = round(float(sub[col].mean()), 1)
                    bucket_cells[bucket] = {
                        "n":        n_b,
                        "hits":     hits_b,
                        "hit_rate": rate_b,
                        "avg_stat": avg_b,
                    }
                tiers_out[f"T{tier}"] = bucket_cells

            # Elasticity delta at the key tier (extended - normal)
            key_cells = tiers_out.get(f"T{key_tier}", {})
            normal_rate   = key_cells.get("normal",   {}).get("hit_rate")
            extended_rate = key_cells.get("extended", {}).get("hit_rate")

            if normal_rate is not None and extended_rate is not None:
                elasticity_delta = round((extended_rate - normal_rate) * 100, 1)
            else:
                elasticity_delta = None

            if elasticity_delta is None:
                stat_flag = None
            elif elasticity_delta >= H30_SCALES_THRESHOLD:
                stat_flag = "SCALES"
            elif elasticity_delta <= H30_INVERTS_THRESHOLD:
                stat_flag = "INVERTS"
            else:
                stat_flag = "PLATEAUS"

            # Monotonicity: do rates consistently increase from low → extended
            # across all buckets with sufficient sample?
            ordered_rates = [
                key_cells[b]["hit_rate"]
                for b in H30_MINUTES_LABELS
                if b in key_cells and key_cells[b].get("hit_rate") is not None
            ]
            if len(ordered_rates) >= 3:
                monotonic_up = all(
                    ordered_rates[i] <= ordered_rates[i + 1]
                    for i in range(len(ordered_rates) - 1)
                )
                monotonic_down = all(
                    ordered_rates[i] >= ordered_rates[i + 1]
                    for i in range(len(ordered_rates) - 1)
                )
            else:
                monotonic_up = None
                monotonic_down = None

            stats_out[stat] = {
                "key_tier":            key_tier,
                "flag":                stat_flag,
                "elasticity_delta_pp": elasticity_delta,
                "monotonic_up":        monotonic_up,
                "monotonic_down":      monotonic_down,
                "tiers":               tiers_out,
                "overall_key_tier_rate": overall_rate,
            }

        # ── Step 3: Overall player flag ──────────────────────────────────
        pts_flag = stats_out["PTS"].get("flag")
        if pts_flag == "SCALES":
            overall_flag = "MINUTES_SCALER"
        elif pts_flag == "INVERTS":
            overall_flag = "MINUTES_INVERTER"
        elif pts_flag == "PLATEAUS":
            # Check if any other stat scales → SELECTIVE_SCALER
            other_scales = any(
                stats_out[s].get("flag") == "SCALES"
                for s in H30_STATS if s != "PTS"
            )
            other_inverts = any(
                stats_out[s].get("flag") == "INVERTS"
                for s in H30_STATS if s != "PTS"
            )
            if other_scales and not other_inverts:
                overall_flag = "SELECTIVE_SCALER"
            elif all(
                stats_out[s].get("flag") == "PLATEAUS"
                for s in H30_STATS
                if stats_out[s].get("flag") is not None
            ):
                overall_flag = "MINUTES_INDEPENDENT"
            else:
                overall_flag = "MIXED"
        else:
            overall_flag = "INSUFFICIENT_DATA"

        # Playoff projection insight — extended rates and delta vs overall
        extended_key_rates: dict = {}
        vs_overall_delta: dict = {}
        for stat in H30_STATS:
            key_tier = H30_KEY_TIER[stat]
            s = stats_out[stat]
            ext_cell = s["tiers"].get(f"T{key_tier}", {}).get("extended", {})
            ext_rate = ext_cell.get("hit_rate")
            if ext_rate is not None:
                extended_key_rates[stat] = ext_rate
                overall_rate = s.get("overall_key_tier_rate")
                if overall_rate is not None:
                    vs_overall_delta[stat] = round((ext_rate - overall_rate) * 100, 1)

        player_entries.append({
            "player":          player_name,
            "team":            team_abbrev,
            "n_games":         n_total,
            "avg_minutes":     avg_minutes,
            "bucket_counts":   bucket_counts,
            "stats":           stats_out,
            "overall_flag":    overall_flag,
            "playoff_projection": {
                "extended_key_rates": extended_key_rates,
                "vs_overall_delta":   vs_overall_delta,
            },
        })

    # Sort by PTS elasticity descending (biggest scalers first)
    def _sort_key(e: dict):
        pts_elast = e["stats"]["PTS"].get("elasticity_delta_pp")
        return (
            0 if pts_elast is not None else 1,   # None values last
            -(pts_elast if pts_elast is not None else 0),
            e["player"],
        )
    player_entries.sort(key=_sort_key)

    # ── Step 4: Population aggregation (pooled across starter-level players) ──
    # Keep starter-level population (avg minutes >= 28) to match the playoff question.
    player_avg_min = df.groupby("player_name")["minutes_raw"].mean()
    starter_names = set(
        player_avg_min[player_avg_min >= H30_POPULATION_MIN_MIN].index.tolist()
    )
    pool = df[df["player_name"].isin(starter_names)].copy()

    population: dict = {}
    for stat in H30_STATS:
        col = H30_STAT_COL[stat]
        tier_out: dict = {}
        for tier in H30_TIERS[stat]:
            bucket_out: dict = {}
            for bucket in H30_MINUTES_LABELS:
                sub = pool[pool["min_bucket"] == bucket]
                n_b = len(sub)
                if n_b == 0:
                    bucket_out[bucket] = {"n": 0, "hit_rate": None}
                    continue
                hits = int((sub[col] >= tier).sum())
                bucket_out[bucket] = {
                    "n":        n_b,
                    "hits":     hits,
                    "hit_rate": round(hits / n_b, 3),
                }
            # Elasticity for the population at this tier
            normal_rate   = bucket_out.get("normal",   {}).get("hit_rate")
            extended_rate = bucket_out.get("extended", {}).get("hit_rate")
            if normal_rate is not None and extended_rate is not None:
                pop_elast = round((extended_rate - normal_rate) * 100, 1)
            else:
                pop_elast = None
            bucket_out["elasticity_delta_pp"] = pop_elast
            tier_out[f"T{tier}"] = bucket_out
        population[stat] = tier_out

    # ── Step 5: Print report ──────────────────────────────────────────────
    date_min = df["game_date"].min().date() if len(df) > 0 else "?"
    date_max = df["game_date"].max().date() if len(df) > 0 else "?"

    print(f"\n{'='*65}")
    print(f"  H30 — MINUTES ELASTICITY")
    print(f"  Minutes buckets: low(<30), normal(30-34), high(34-38), extended(38+)")
    print(f"  Elasticity = extended rate - normal rate at key tier")
    print(f"  Date range: {date_min} → {date_max}")
    print(f"  Qualified players: {len(player_entries)} "
          f"(>= {H30_MIN_TOTAL_GAMES} total games)")
    print(f"{'='*65}")

    # Population table
    print(f"\n  POPULATION (pooled, {len(starter_names)} starters with "
          f"avg min >= {H30_POPULATION_MIN_MIN})")
    print(f"  {'─'*61}")
    print(f"  {'Stat':<5}{'Tier':<6}{'low':>9}{'normal':>11}{'high':>9}"
          f"{'extended':>11}{'elasticity':>13}")
    for stat in H30_STATS:
        for tier in H30_TIERS[stat]:
            cell_map = population[stat][f"T{tier}"]
            row_parts = []
            for bucket in H30_MINUTES_LABELS:
                hr = cell_map.get(bucket, {}).get("hit_rate")
                row_parts.append(f"{hr*100:5.1f}%" if hr is not None else "  n/a")
            elast = cell_map.get("elasticity_delta_pp")
            elast_s = f"{elast:+6.1f}pp" if elast is not None else "     n/a"
            print(f"  {stat:<5}T{tier:<5}{row_parts[0]:>9}{row_parts[1]:>11}"
                  f"{row_parts[2]:>9}{row_parts[3]:>11}{elast_s:>13}")

    # Per-player tables grouped by overall flag
    def _stat_progression(entry: dict, stat: str) -> str:
        key_tier = H30_KEY_TIER[stat]
        cell_map = entry["stats"][stat]["tiers"].get(f"T{key_tier}", {})
        parts = []
        for bucket in H30_MINUTES_LABELS:
            hr = cell_map.get(bucket, {}).get("hit_rate")
            if hr is not None:
                parts.append(f"{int(round(hr * 100))}%")
            else:
                parts.append("—")
        return "→".join(parts)

    def _print_group(label: str, entries: list, tail_note: str = "") -> None:
        if not entries:
            return
        print(f"\n  {label}{(' — ' + tail_note) if tail_note else ''} "
              f"({len(entries)} players)")
        print(f"  {'─'*61}")
        header = (
            f"  {'Player':<24}{'avg_min':>8}{'n_ext':>6}  "
            f"{'PTS(T20) low→norm→high→ext':<32}"
            f"{'elast':>8}   mono  flag"
        )
        print(header)
        for e in entries:
            player = (e["player"] or "")[:24]
            avg_m  = e["avg_minutes"]
            n_ext  = e["bucket_counts"].get("extended", 0)
            prog   = _stat_progression(e, "PTS")
            elast  = e["stats"]["PTS"].get("elasticity_delta_pp")
            elast_s = f"{elast:+.1f}pp" if elast is not None else "   n/a"
            mono_up = e["stats"]["PTS"].get("monotonic_up")
            mono_s  = "↑" if mono_up is True else ("·" if mono_up is False else "?")
            flag    = e["overall_flag"]
            print(
                f"  {player:<24}{avg_m:>8.1f}{n_ext:>6}  "
                f"{prog:<32}{elast_s:>8}  {mono_s:>4}   {flag}"
            )

    scalers  = [e for e in player_entries if e["overall_flag"] == "MINUTES_SCALER"]
    selective = [e for e in player_entries if e["overall_flag"] == "SELECTIVE_SCALER"]
    mixed    = [e for e in player_entries if e["overall_flag"] == "MIXED"]
    independent = [e for e in player_entries if e["overall_flag"] == "MINUTES_INDEPENDENT"]
    inverters = [e for e in player_entries if e["overall_flag"] == "MINUTES_INVERTER"]
    insufficient = [e for e in player_entries if e["overall_flag"] == "INSUFFICIENT_DATA"]

    _print_group(
        "MINUTES SCALERS",
        scalers,
        f"PTS elasticity >= +{int(H30_SCALES_THRESHOLD)}pp at key tier",
    )
    _print_group(
        "SELECTIVE SCALERS",
        selective,
        "PTS plateaus but other stat scales",
    )
    _print_group(
        "MIXED",
        mixed,
        "PTS plateaus with one or more inverting stats",
    )
    _print_group(
        "MINUTES INDEPENDENT",
        independent,
        "all stats plateau",
    )
    _print_group(
        "MINUTES INVERTERS",
        inverters,
        f"PTS elasticity <= {int(H30_INVERTS_THRESHOLD)}pp at key tier",
    )
    if insufficient:
        _print_group(
            "INSUFFICIENT DATA",
            insufficient,
            f"fewer than {H30_MIN_BUCKET_N} games in normal or extended buckets",
        )

    # ── Step 6: Write JSON output ─────────────────────────────────────────
    out = {
        "metadata": {
            "generated_at": dt.date.today().isoformat(),
            "mode":         "minutes-elasticity",
            "date_range": {
                "start": str(date_min),
                "end":   str(date_max),
            },
            "constants": {
                "H30_MIN_BUCKET_N":       H30_MIN_BUCKET_N,
                "H30_MIN_TOTAL_GAMES":    H30_MIN_TOTAL_GAMES,
                "H30_MINUTES_BINS":       H30_MINUTES_BINS,
                "H30_MINUTES_LABELS":     H30_MINUTES_LABELS,
                "H30_KEY_TIER":           H30_KEY_TIER,
                "H30_SCALES_THRESHOLD":   H30_SCALES_THRESHOLD,
                "H30_INVERTS_THRESHOLD":  H30_INVERTS_THRESHOLD,
                "H30_POPULATION_MIN_MIN": H30_POPULATION_MIN_MIN,
            },
            "n_total_games":      int(len(df)),
            "n_qualified_players": len(player_entries),
            "flag_counts": {
                "MINUTES_SCALER":      len(scalers),
                "SELECTIVE_SCALER":    len(selective),
                "MIXED":               len(mixed),
                "MINUTES_INDEPENDENT": len(independent),
                "MINUTES_INVERTER":    len(inverters),
                "INSUFFICIENT_DATA":   len(insufficient),
            },
        },
        "population": population,
        "players":    player_entries,
        "summary": {
            "scalers":          [e["player"] for e in scalers],
            "selective_scalers": [e["player"] for e in selective],
            "mixed":            [e["player"] for e in mixed],
            "independent":      [e["player"] for e in independent],
            "inverters":        [e["player"] for e in inverters],
            "insufficient":     [e["player"] for e in insufficient],
        },
    }

    out_path = Path(args.output) if getattr(args, "output", None) else MINUTES_ELASTICITY_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H30 results → {out_path}")


# ── H32 — Player Consistency Index ──────────────────────────────────

def run_consistency_index_analysis(
    player_log: pd.DataFrame,
    master_df: pd.DataFrame,
    args,
) -> None:
    """
    H32 — Player Consistency Index.

    Measures how stable each player's tier hit rate is across contextual
    slices (Home/Away, Rest: B2B/Normal/Extended, Spread: Competitive/
    Blowout-risk). Aggregate hit rates mask context variance — a player
    with 80% overall and 5pp range across contexts is fundamentally
    different from one with 80% and 25pp range.

    Formalizes the iron_floor intuition across multiple context dimensions
    and identifies each player's single worst vulnerability (stat,
    dimension, range_pp). For playoffs this matters more: games skew
    road-heavy (2-2-1-1-1), no B2Bs but dense scheduling, and higher-
    leverage spread contexts.

    Uses player_game_log.csv + nba_master.csv. Does NOT read picks.json
    or playoff_career_log.csv.

    Output feeds a future per-player context-weighted confidence layer —
    NOT a standalone rule. No analyst.py changes in this task.
    """
    if player_log.empty:
        print("[backtest] WARNING: player_log is empty — cannot run H32.")
        return
    if master_df.empty:
        print("[backtest] WARNING: master_df is empty — cannot run H32.")
        return

    window = getattr(args, "window", None) or ROLLING_WINDOW
    print(f"[backtest] H32 consistency-index | "
          f"{len(player_log):,} player-games | "
          f"window={window} | "
          f"min_slice_n={H32_MIN_SLICE_N} | "
          f"min_total_games={H32_MIN_TOTAL_GAMES}")

    # ── Step 1: Build spread lookup (mirrors H19/H27 pattern) ────────────
    spread_map: dict = {}
    for _, row in master_df.iterrows():
        gid  = str(row.get("game_id", "")).strip()
        home = str(row.get("home_team_abbrev", "")).upper().strip()
        away = str(row.get("away_team_abbrev", "")).upper().strip()
        hs   = row.get("home_spread")
        as_  = row.get("away_spread")
        for team, spread in [(home, hs), (away, as_)]:
            if team and not pd.isna(spread):
                spread_map[(gid, team)] = float(spread)

    # ── Step 2: Add context columns ──────────────────────────────────────
    df = player_log.copy()
    df = df.sort_values(["player_name", "game_date"]).reset_index(drop=True)

    # Rest days — first game per player is NaN (no prior game)
    df["rest_days"] = (
        df.groupby("player_name")["game_date"].diff().dt.days - 1
    )

    def _rest_bucket(d):
        if pd.isna(d):
            return None
        if d == 0:
            return "B2B"
        if d == 1:
            return "normal"
        if d >= 2:
            return "extended"
        return None

    df["rest_bucket"] = df["rest_days"].apply(_rest_bucket)

    # Home/Away already in df["home_away"] as "H" or "A"

    # Spread context — join to master_df
    df["_team_upper"] = df["team_abbrev"].astype(str).str.upper().str.strip()
    df["_gid"]        = df["game_id"].astype(str).str.split(".").str[0].str.strip()

    def _spread_lookup(row):
        s = spread_map.get((row["_gid"], row["_team_upper"]))
        return abs(s) if s is not None else None

    df["spread_abs"] = df.apply(_spread_lookup, axis=1)

    def _spread_bucket(s):
        if s is None or pd.isna(s):
            return None
        return "competitive" if s <= H32_SPREAD_THRESHOLD else "blowout_risk"

    df["spread_bucket"] = df["spread_abs"].apply(_spread_bucket)

    # ── Step 3: Add best tiers ───────────────────────────────────────────
    df = add_best_tiers(df, window=window)

    # ── Step 4: Per-player, per-stat consistency ─────────────────────────
    player_entries: list = []

    for player_name, player_games in df.groupby("player_name"):
        n_total = len(player_games)
        if n_total < H32_MIN_TOTAL_GAMES:
            continue

        team_abbrev = (
            str(player_games.sort_values("game_date")["team_abbrev"].iloc[-1])
            if not player_games.empty else ""
        )

        stats_out: dict = {}

        for stat in H32_STATS:
            col       = H32_STAT_COL[stat]
            bt_col    = f"best_tier_{stat}"
            # Player needs at least some qualifying games with a best_tier
            valid = player_games[player_games[bt_col].notna()]
            if len(valid) < H32_MIN_SLICE_N:
                continue

            # Modal best_tier across the player's qualifying games — their
            # "characteristic" tier. Using `.mode()` which returns a Series.
            tier_mode_series = valid[bt_col].mode()
            if tier_mode_series.empty:
                continue
            tier = int(tier_mode_series.iloc[0])

            # Overall hit rate at this tier across all games (not just qualifying)
            hits_overall = int((player_games[col] >= tier).sum())
            overall_rate = round(hits_overall / n_total, 3) if n_total > 0 else None
            n_qualifying = int((player_games[col] >= tier).sum() +
                               (player_games[col] < tier).sum())

            # Compute hit rate per context slice
            slices: dict = {}

            # Home / Away
            for ha_code, ha_label in [("H", "home"), ("A", "away")]:
                sub = player_games[player_games["home_away"] == ha_code]
                n_sub = len(sub)
                if n_sub >= H32_MIN_SLICE_N:
                    hits_sub = int((sub[col] >= tier).sum())
                    slices[ha_label] = {
                        "n":        n_sub,
                        "hits":     hits_sub,
                        "hit_rate": round(hits_sub / n_sub, 3),
                    }

            # Rest buckets
            for bucket in ("B2B", "normal", "extended"):
                sub = player_games[player_games["rest_bucket"] == bucket]
                n_sub = len(sub)
                if n_sub >= H32_MIN_SLICE_N:
                    hits_sub = int((sub[col] >= tier).sum())
                    slices[f"rest_{bucket}"] = {
                        "n":        n_sub,
                        "hits":     hits_sub,
                        "hit_rate": round(hits_sub / n_sub, 3),
                    }

            # Spread buckets
            for bucket in ("competitive", "blowout_risk"):
                sub = player_games[player_games["spread_bucket"] == bucket]
                n_sub = len(sub)
                if n_sub >= H32_MIN_SLICE_N:
                    hits_sub = int((sub[col] >= tier).sum())
                    slices[f"spread_{bucket}"] = {
                        "n":        n_sub,
                        "hits":     hits_sub,
                        "hit_rate": round(hits_sub / n_sub, 3),
                    }

            # Need at least 3 context slices for meaningful stability
            if len(slices) < 3:
                continue

            # Stability metrics
            rates = [s["hit_rate"] for s in slices.values()]
            range_pp = round((max(rates) - min(rates)) * 100, 1)
            std_pp   = round(float(np.std(rates)) * 100, 1)
            best_context  = max(slices.keys(), key=lambda k: slices[k]["hit_rate"])
            worst_context = min(slices.keys(), key=lambda k: slices[k]["hit_rate"])

            # Per-dimension ranges
            dim_ranges: dict = {}

            ha_rates = [
                slices[k]["hit_rate"]
                for k in ("home", "away")
                if k in slices
            ]
            if len(ha_rates) == 2:
                dim_ranges["home_away"] = round(
                    abs(ha_rates[0] - ha_rates[1]) * 100, 1
                )

            rest_rates = [
                slices[k]["hit_rate"]
                for k in ("rest_B2B", "rest_normal", "rest_extended")
                if k in slices
            ]
            if len(rest_rates) >= 2:
                dim_ranges["rest"] = round(
                    (max(rest_rates) - min(rest_rates)) * 100, 1
                )

            spread_rates = [
                slices[k]["hit_rate"]
                for k in ("spread_competitive", "spread_blowout_risk")
                if k in slices
            ]
            if len(spread_rates) == 2:
                dim_ranges["spread"] = round(
                    abs(spread_rates[0] - spread_rates[1]) * 100, 1
                )

            worst_dimension = (
                max(dim_ranges.keys(), key=lambda k: dim_ranges[k])
                if dim_ranges else None
            )

            # Flag
            if range_pp < H32_ALLWEATHER_RANGE:
                stat_flag = "ALL_WEATHER"
            elif range_pp >= H32_SENSITIVE_RANGE:
                stat_flag = "CONTEXT_SENSITIVE"
            else:
                stat_flag = "MODERATE"

            stats_out[stat] = {
                "tier":             tier,
                "overall_hit_rate": overall_rate,
                "n_qualifying":     n_qualifying,
                "flag":             stat_flag,
                "range_pp":         range_pp,
                "std_pp":           std_pp,
                "best_context":     best_context,
                "worst_context":    worst_context,
                "slices":           slices,
                "dim_ranges":       dim_ranges,
                "worst_dimension":  worst_dimension,
            }

        if not stats_out:
            continue

        # ── Step 5: Overall player flag + worst vulnerability ─────────────
        flags = [s["flag"] for s in stats_out.values()]
        if all(f == "ALL_WEATHER" for f in flags):
            overall_flag = "ALL_WEATHER"
        elif any(f == "CONTEXT_SENSITIVE" for f in flags):
            overall_flag = "HAS_VULNERABILITY"
        else:
            overall_flag = "MODERATE"

        # Worst vulnerability — highest range_pp across all stats, reporting
        # the dimension (from worst_dimension) and its dim-specific range.
        worst_vuln: "dict | None" = None
        worst_range = -1.0
        for stat_name, s in stats_out.items():
            wd = s.get("worst_dimension")
            if wd is None:
                continue
            dim_rng = s["dim_ranges"].get(wd, 0.0)
            if dim_rng > worst_range:
                worst_range = dim_rng
                worst_vuln = {
                    "stat":      stat_name,
                    "dimension": wd,
                    "range_pp":  dim_rng,
                }

        player_entries.append({
            "player":              player_name,
            "team":                team_abbrev,
            "n_games":             n_total,
            "overall_flag":        overall_flag,
            "worst_vulnerability": worst_vuln,
            "stats":               stats_out,
        })

    # Sort: ALL_WEATHER (by n_games desc), MODERATE, HAS_VULNERABILITY (by
    # worst vuln range desc).
    flag_priority = {
        "ALL_WEATHER":       0,
        "MODERATE":          1,
        "HAS_VULNERABILITY": 2,
    }
    def _sort_key(e: dict):
        prio = flag_priority.get(e["overall_flag"], 99)
        if prio == 0:   # ALL_WEATHER → by n_games desc
            return (prio, -e["n_games"], e["player"])
        if prio == 2:   # HAS_VULNERABILITY → by worst vuln range desc
            wv = e.get("worst_vulnerability") or {}
            return (prio, -(wv.get("range_pp") or 0.0), e["player"])
        return (prio, -e["n_games"], e["player"])
    player_entries.sort(key=_sort_key)

    all_weather        = [e for e in player_entries if e["overall_flag"] == "ALL_WEATHER"]
    moderate_group     = [e for e in player_entries if e["overall_flag"] == "MODERATE"]
    context_sensitive  = [e for e in player_entries if e["overall_flag"] == "HAS_VULNERABILITY"]

    # ── Step 6: Print report ──────────────────────────────────────────────
    date_min = df["game_date"].min().date() if len(df) > 0 else "?"
    date_max = df["game_date"].max().date() if len(df) > 0 else "?"

    print(f"\n{'='*65}")
    print(f"  H32 — PLAYER CONSISTENCY INDEX")
    print(f"  Contexts: Home/Away, Rest (B2B/Normal/Extended), Spread (Competitive/Blowout)")
    print(f"  Min slice n: {H32_MIN_SLICE_N} | Min total games: {H32_MIN_TOTAL_GAMES}")
    print(f"  Range thresholds: ALL_WEATHER <{int(H32_ALLWEATHER_RANGE)}pp, "
          f"CONTEXT_SENSITIVE ≥{int(H32_SENSITIVE_RANGE)}pp")
    print(f"  Date range: {date_min} → {date_max}")
    print(f"  Qualified players: {len(player_entries)} "
          f"(ALL_WEATHER={len(all_weather)}, MODERATE={len(moderate_group)}, "
          f"HAS_VULNERABILITY={len(context_sensitive)})")
    print(f"{'='*65}")

    def _stat_summary_cell(e: dict, stat: str) -> str:
        s = e["stats"].get(stat)
        if s is None:
            return "—".ljust(15)
        tier = s["tier"]
        overall = s.get("overall_hit_rate")
        rng = s.get("range_pp")
        overall_s = f"{int(round(overall * 100))}%" if overall is not None else "n/a"
        rng_s     = f"rng={rng:.0f}pp" if rng is not None else "rng=n/a"
        return f"T{tier} {overall_s} {rng_s}".ljust(15)

    def _print_allweather_group(label: str, entries: list) -> None:
        if not entries:
            return
        print(f"\n  {label} ({len(entries)} players)")
        print(f"  {'─'*61}")
        header = (
            f"  {'Player':<24}{'n':>5}  "
            f"{'PTS':<15}{'REB':<15}{'AST':<15}{'3PM':<15}"
        )
        print(header)
        for e in entries:
            player = (e["player"] or "")[:24]
            n      = e["n_games"]
            pts    = _stat_summary_cell(e, "PTS")
            reb    = _stat_summary_cell(e, "REB")
            ast    = _stat_summary_cell(e, "AST")
            tpm    = _stat_summary_cell(e, "3PM")
            print(f"  {player:<24}{n:>5}  {pts}{reb}{ast}{tpm}")

    def _vuln_detail(e: dict) -> str:
        wv = e.get("worst_vulnerability") or {}
        stat = wv.get("stat")
        dim  = wv.get("dimension")
        if stat is None or dim is None:
            return ""
        s = e["stats"].get(stat, {})
        tier = s.get("tier")
        slices = s.get("slices", {})
        parts = []
        if dim == "home_away":
            for key in ("home", "away"):
                if key in slices:
                    parts.append(f"{key[0].upper()}:{int(round(slices[key]['hit_rate']*100))}%")
        elif dim == "rest":
            for key in ("rest_B2B", "rest_normal", "rest_extended"):
                if key in slices:
                    label = key.replace("rest_", "")
                    parts.append(f"{label}:{int(round(slices[key]['hit_rate']*100))}%")
        elif dim == "spread":
            for key in ("spread_competitive", "spread_blowout_risk"):
                if key in slices:
                    label = "comp" if key == "spread_competitive" else "blow"
                    parts.append(f"{label}:{int(round(slices[key]['hit_rate']*100))}%")
        return " ".join(parts)

    def _print_vuln_group(label: str, entries: list) -> None:
        if not entries:
            return
        print(f"\n  {label} ({len(entries)} players)")
        print(f"  {'─'*61}")
        header = (
            f"  {'Player':<24}{'n':>5}  "
            f"{'Worst vulnerability':<34}{'Detail'}"
        )
        print(header)
        for e in entries:
            player = (e["player"] or "")[:24]
            n      = e["n_games"]
            wv     = e.get("worst_vulnerability") or {}
            vuln_str = ""
            if wv:
                stat  = wv.get("stat", "?")
                dim   = wv.get("dimension", "?")
                rng   = wv.get("range_pp")
                tier  = e["stats"].get(stat, {}).get("tier", "?")
                rng_s = f"{rng:.0f}pp" if rng is not None else "n/a"
                vuln_str = f"{stat}(T{tier}) {dim} rng={rng_s}"
            detail = _vuln_detail(e)
            print(f"  {player:<24}{n:>5}  {vuln_str:<34}{detail}")

    _print_allweather_group(
        f"ALL-WEATHER PLAYERS (range < {int(H32_ALLWEATHER_RANGE)}pp in all qualifying stats)",
        all_weather,
    )
    _print_allweather_group(
        f"MODERATE PLAYERS (all stats within {int(H32_ALLWEATHER_RANGE)}-{int(H32_SENSITIVE_RANGE)}pp range)",
        moderate_group,
    )
    _print_vuln_group(
        f"CONTEXT-SENSITIVE PLAYERS (range ≥ {int(H32_SENSITIVE_RANGE)}pp in any stat)",
        context_sensitive,
    )

    # ── Step 7: Write JSON output ─────────────────────────────────────────
    summary = {
        "n_qualified":        len(player_entries),
        "n_all_weather":      len(all_weather),
        "n_moderate":         len(moderate_group),
        "n_context_sensitive": len(context_sensitive),
        "all_weather_players":      [e["player"] for e in all_weather],
        "moderate_players":         [e["player"] for e in moderate_group],
        "context_sensitive_players": [
            {
                "player":              e["player"],
                "worst_vulnerability": e["worst_vulnerability"],
            }
            for e in context_sensitive
        ],
    }

    out = {
        "metadata": {
            "generated_at": dt.date.today().isoformat(),
            "mode":         "consistency-index",
            "date_range": {
                "start": str(date_min),
                "end":   str(date_max),
            },
            "constants": {
                "H32_MIN_SLICE_N":       H32_MIN_SLICE_N,
                "H32_MIN_TOTAL_GAMES":   H32_MIN_TOTAL_GAMES,
                "H32_ALLWEATHER_RANGE":  H32_ALLWEATHER_RANGE,
                "H32_SENSITIVE_RANGE":   H32_SENSITIVE_RANGE,
                "H32_SPREAD_THRESHOLD":  H32_SPREAD_THRESHOLD,
                "rolling_window":        window,
            },
        },
        "players": player_entries,
        "summary": summary,
    }

    out_path = Path(args.output) if getattr(args, "output", None) else CONSISTENCY_INDEX_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H32 results → {out_path}")


# ── H31 — Playoff Series Progression ────────────────────────────────

def run_series_progression_analysis(args) -> None:
    """
    H31 — Playoff Series Progression.

    Tests whether tier hit rates shift across phases of a 7-game playoff
    series: early (games 1-2), mid (games 3-4), late (games 5-7).
    Defensive scheming intensifies as a series progresses — primary scorers
    get more aggressive attention, bench rotations tighten, elimination
    pressure mounts. The question: is this measurable at the hit-rate level?

    Complements H28 (overall playoff adjustment) by adding a within-series
    temporal dimension. Population preview shows subtle effects (PTS flat,
    REB/AST slight lift, 3PM slight decline); per-player analysis may
    reveal stronger individual patterns (late risers, late faders).

    Loads playoff_career_log.csv internally (same pattern as H28). Does NOT
    use load_player_log() or load_master(). Infers series from
    (season, sorted team pair) + uses cumcount per player to assign game
    number within series.

    Output feeds a future playoff context enhancement — NOT a standalone
    rule. No analyst.py changes in this task.
    """
    if not PLAYOFF_CAREER_CSV.exists():
        print(f"[backtest] ERROR: {PLAYOFF_CAREER_CSV} not found.")
        return

    # ── Step 1: Load data ─────────────────────────────────────────────────
    raw = pd.read_csv(PLAYOFF_CAREER_CSV)
    po = raw[raw["season_type"] == "playoff"].copy()
    po = po[po["minutes"] > 0].copy()
    po["game_date"] = pd.to_datetime(po["game_date"], errors="coerce")
    po = po[po["game_date"].notna()].copy()

    if po.empty:
        print("[backtest] WARNING: no playoff games — cannot run H31.")
        return

    # ── Step 2: Infer series and assign game-in-series ───────────────────
    po["matchup_str"] = po.apply(
        lambda r: "-".join(sorted([str(r["team_abbrev"]), str(r["opp_abbrev"])])),
        axis=1,
    )
    po = po.sort_values(
        ["season", "matchup_str", "player_name", "game_date"]
    ).reset_index(drop=True)
    po["game_in_series"] = (
        po.groupby(["season", "matchup_str", "player_name"]).cumcount() + 1
    )

    def _phase(g: int) -> str:
        if g <= 2:
            return "early"
        if g <= 4:
            return "mid"
        return "late"

    po["series_phase"] = po["game_in_series"].apply(_phase)

    # Series length per player (total games this player played in this series)
    po["series_length"] = po.groupby(
        ["season", "matchup_str", "player_name"]
    )["game_in_series"].transform("max")

    n_series = po[["season", "matchup_str"]].drop_duplicates().shape[0]
    print(f"[backtest] H31 series-progression | "
          f"{len(po):,} playoff player-games | "
          f"{n_series} series | "
          f"{po['player_name'].nunique()} unique players")
    print(f"[backtest] phase distribution: "
          f"early={int((po['series_phase']=='early').sum())}, "
          f"mid={int((po['series_phase']=='mid').sum())}, "
          f"late={int((po['series_phase']=='late').sum())}")

    # ── Step 3: Population-level phase analysis ──────────────────────────
    population: dict = {}
    for stat in H31_STATS:
        col = H31_STAT_COL[stat]
        tier_out: dict = {}
        for tier in H31_TIERS[stat]:
            phase_out: dict = {}
            for phase in H31_PHASES:
                sub = po[po["series_phase"] == phase]
                n_p = len(sub)
                if n_p == 0:
                    phase_out[phase] = {
                        "n": 0, "hits": 0, "hit_rate": None,
                        "avg_stat": None, "avg_minutes": None,
                    }
                    continue
                hits = int((sub[col] >= tier).sum())
                phase_out[phase] = {
                    "n":           n_p,
                    "hits":        hits,
                    "hit_rate":    round(hits / n_p, 3),
                    "avg_stat":    round(float(sub[col].mean()), 1),
                    "avg_minutes": round(float(sub["minutes"].mean()), 1),
                }
            # early→late delta
            early_rate = phase_out.get("early", {}).get("hit_rate")
            late_rate  = phase_out.get("late",  {}).get("hit_rate")
            if early_rate is not None and late_rate is not None:
                phase_out["early_to_late_delta_pp"] = round(
                    (late_rate - early_rate) * 100, 1
                )
            else:
                phase_out["early_to_late_delta_pp"] = None
            tier_out[f"T{tier}"] = phase_out
        population[stat] = tier_out

    # ── Step 4: Per-player phase analysis ────────────────────────────────
    player_entries: list = []

    for player_name, player_po in po.groupby("player_name"):
        n_total = len(player_po)
        if n_total < H31_MIN_TOTAL_PLAYOFF:
            continue

        team_abbrev = str(player_po.sort_values("game_date")["team_abbrev"].iloc[-1])
        n_series_for_player = player_po[
            ["season", "matchup_str"]
        ].drop_duplicates().shape[0]

        phase_counts = {
            phase: int((player_po["series_phase"] == phase).sum())
            for phase in H31_PHASES
        }

        stats_out: dict = {}
        for stat in H31_STATS:
            col       = H31_STAT_COL[stat]
            key_tier  = H31_KEY_TIER[stat]

            # Per-phase at key tier
            phases_out: dict = {}
            for phase in H31_PHASES:
                sub = player_po[player_po["series_phase"] == phase]
                n_ph = len(sub)
                if n_ph < H31_MIN_PHASE_N:
                    continue
                hits = int((sub[col] >= key_tier).sum())
                phases_out[phase] = {
                    "n":           n_ph,
                    "hits":        hits,
                    "hit_rate":    round(hits / n_ph, 3),
                    "avg_stat":    round(float(sub[col].mean()), 1),
                    "avg_minutes": round(float(sub["minutes"].mean()), 1),
                }

            # Progression delta at key tier (requires both early AND late)
            early_rate = phases_out.get("early", {}).get("hit_rate")
            late_rate  = phases_out.get("late",  {}).get("hit_rate")
            if early_rate is not None and late_rate is not None:
                progression_delta = round((late_rate - early_rate) * 100, 1)
            else:
                progression_delta = None

            if progression_delta is None:
                stat_flag = None
            elif progression_delta >= H31_PROGRESSION_THRESHOLD:
                stat_flag = "LATE_RISER"
            elif progression_delta <= -H31_PROGRESSION_THRESHOLD:
                stat_flag = "LATE_FADER"
            else:
                stat_flag = "STABLE"

            # All-tier detail for completeness (per-phase hit rates at every
            # tier, only phases with >= MIN_PHASE_N included)
            all_tiers: dict = {}
            for tier in H31_TIERS[stat]:
                tier_phase_out: dict = {}
                for phase in H31_PHASES:
                    sub = player_po[player_po["series_phase"] == phase]
                    n_ph = len(sub)
                    if n_ph < H31_MIN_PHASE_N:
                        continue
                    hits = int((sub[col] >= tier).sum())
                    tier_phase_out[phase] = {
                        "n":        n_ph,
                        "hit_rate": round(hits / n_ph, 3),
                    }
                all_tiers[f"T{tier}"] = tier_phase_out

            stats_out[stat] = {
                "key_tier":             key_tier,
                "flag":                 stat_flag,
                "progression_delta_pp": progression_delta,
                "phases":               phases_out,
                "all_tiers":            all_tiers,
            }

        # ── Step 5: Per-series game log ───────────────────────────────────
        series_log: list = []
        for (season, matchup), group in player_po.groupby(["season", "matchup_str"]):
            group_sorted = group.sort_values("game_date")
            games_list = []
            for _, g in group_sorted.iterrows():
                games_list.append({
                    "game_num": int(g["game_in_series"]),
                    "phase":    str(g["series_phase"]),
                    "date":     str(g["game_date"].date()),
                    "pts":      int(g["pts"]),
                    "reb":      int(g["reb"]),
                    "ast":      int(g["ast"]),
                    "tpm":      int(g["tpm"]),
                    "minutes":  round(float(g["minutes"]), 1),
                })
            series_log.append({
                "season":        int(season),
                "matchup":       str(matchup),
                "series_length": int(group_sorted["series_length"].iloc[0]),
                "games":         games_list,
            })
        # Sort series_log chronologically: by season asc then earliest game date
        series_log.sort(
            key=lambda s: (s["season"], min(g["date"] for g in s["games"]))
        )

        # Overall player flag — driven by PTS flag (primary playoff signal),
        # falling back to any other stat flag if PTS has no data.
        pts_flag = stats_out.get("PTS", {}).get("flag")
        if pts_flag is not None:
            overall_flag = pts_flag
        else:
            # Use any non-None flag from other stats
            other_flags = [
                stats_out[s].get("flag")
                for s in H31_STATS
                if stats_out.get(s, {}).get("flag") is not None
            ]
            if other_flags:
                # If any LATE_RISER → LATE_RISER, etc.
                if "LATE_RISER" in other_flags:
                    overall_flag = "LATE_RISER"
                elif "LATE_FADER" in other_flags:
                    overall_flag = "LATE_FADER"
                else:
                    overall_flag = "STABLE"
            else:
                overall_flag = "INSUFFICIENT_DATA"

        # Max absolute progression delta (for sorting within flag groups)
        max_abs_delta = 0.0
        for s in stats_out.values():
            d = s.get("progression_delta_pp")
            if d is not None and abs(d) > max_abs_delta:
                max_abs_delta = abs(d)

        player_entries.append({
            "player":          player_name,
            "team":            team_abbrev,
            "n_playoff_games": n_total,
            "n_series":        n_series_for_player,
            "phase_counts":    phase_counts,
            "stats":           stats_out,
            "overall_flag":    overall_flag,
            "_max_abs_delta":  max_abs_delta,
            "series_log":      series_log,
        })

    # Sort: LATE_RISER (by PTS delta desc) → STABLE → LATE_FADER (by |delta| desc) → INSUFFICIENT
    flag_priority = {
        "LATE_RISER":        0,
        "STABLE":            1,
        "LATE_FADER":        2,
        "INSUFFICIENT_DATA": 3,
    }
    def _sort_key(e: dict):
        prio = flag_priority.get(e["overall_flag"], 99)
        pts_delta = e["stats"].get("PTS", {}).get("progression_delta_pp") or 0
        if prio == 0:
            return (prio, -pts_delta, e["player"])
        if prio == 2:
            return (prio, -abs(pts_delta), e["player"])
        return (prio, -e["_max_abs_delta"], e["player"])
    player_entries.sort(key=_sort_key)

    late_risers  = [e for e in player_entries if e["overall_flag"] == "LATE_RISER"]
    stable       = [e for e in player_entries if e["overall_flag"] == "STABLE"]
    late_faders  = [e for e in player_entries if e["overall_flag"] == "LATE_FADER"]
    insufficient = [e for e in player_entries if e["overall_flag"] == "INSUFFICIENT_DATA"]

    # ── Step 6: Print report ──────────────────────────────────────────────
    date_min = po["game_date"].min().date()
    date_max = po["game_date"].max().date()

    print(f"\n{'='*65}")
    print(f"  H31 — PLAYOFF SERIES PROGRESSION")
    print(f"  Phases: early(G1-2), mid(G3-4), late(G5-7)")
    print(f"  Data: playoff_career_log.csv "
          f"(seasons {int(raw['season'].min())}–{int(raw['season'].max())})")
    print(f"  {n_series} series | {len(player_entries)} players qualified "
          f"(>= {H31_MIN_TOTAL_PLAYOFF} playoff games)")
    print(f"{'='*65}")

    # Population table
    print(f"\n  POPULATION (pooled across all players)")
    print(f"  {'─'*61}")
    print(f"  {'Stat':<5}{'Tier':<6}{'early':>10}{'mid':>10}{'late':>10}{'delta(e→l)':>14}")
    for stat in H31_STATS:
        for tier in H31_TIERS[stat]:
            cell = population[stat][f"T{tier}"]
            e = cell.get("early", {}).get("hit_rate")
            m = cell.get("mid",   {}).get("hit_rate")
            l = cell.get("late",  {}).get("hit_rate")
            d = cell.get("early_to_late_delta_pp")
            e_s = f"{e*100:5.1f}%" if e is not None else "  n/a"
            m_s = f"{m*100:5.1f}%" if m is not None else "  n/a"
            l_s = f"{l*100:5.1f}%" if l is not None else "  n/a"
            d_s = f"{d:+6.1f}pp" if d is not None else "     n/a"
            print(f"  {stat:<5}T{tier:<5}{e_s:>10}{m_s:>10}{l_s:>10}{d_s:>14}")

    # Per-player groups
    def _pts_progression(entry: dict) -> str:
        phases = entry["stats"].get("PTS", {}).get("phases", {})
        parts = []
        for phase in H31_PHASES:
            hr = phases.get(phase, {}).get("hit_rate")
            parts.append(f"{int(round(hr * 100))}%" if hr is not None else "—")
        return "→".join(parts)

    def _print_group(label: str, entries: list, tail_note: str = "") -> None:
        if not entries:
            return
        print(f"\n  {label}{(' — ' + tail_note) if tail_note else ''} "
              f"({len(entries)} players)")
        print(f"  {'─'*61}")
        header = (
            f"  {'Player':<24}{'po_n':>6}{'series':>8}  "
            f"{'PTS(T20) e→m→l':<22}{'delta':>10}   flag"
        )
        print(header)
        for e in entries:
            player = (e["player"] or "")[:24]
            n      = e["n_playoff_games"]
            n_ser  = e["n_series"]
            prog   = _pts_progression(e)
            delta  = e["stats"].get("PTS", {}).get("progression_delta_pp")
            delta_s = f"{delta:+.1f}pp" if delta is not None else "    n/a"
            flag = e["overall_flag"]
            print(
                f"  {player:<24}{n:>6}{n_ser:>8}  {prog:<22}{delta_s:>10}   {flag}"
            )

    _print_group(
        "LATE_RISERS",
        late_risers,
        f"PTS delta >= +{int(H31_PROGRESSION_THRESHOLD)}pp early→late",
    )
    _print_group(
        "STABLE",
        stable,
        "PTS delta within ±8pp",
    )
    _print_group(
        "LATE_FADERS",
        late_faders,
        f"PTS delta <= -{int(H31_PROGRESSION_THRESHOLD)}pp early→late",
    )
    if insufficient:
        _print_group(
            "INSUFFICIENT_DATA",
            insufficient,
            "fewer than 5 games in early or late phase",
        )

    print(f"\n  ⚠ SAMPLE SIZE NOTE: Per-player late-phase data is inherently thin —")
    print(f"    requires multiple 5+ game series. Flags with n_late < 10 should be")
    print(f"    treated as directional, not definitive.")

    # ── Step 7: Write JSON output ─────────────────────────────────────────
    def _clean(e: dict) -> dict:
        return {k: v for k, v in e.items() if not k.startswith("_")}

    all_entries_clean = [_clean(e) for e in player_entries]

    out = {
        "metadata": {
            "generated_at":     dt.date.today().isoformat(),
            "mode":             "series-progression",
            "data_file":        str(PLAYOFF_CAREER_CSV),
            "season_range":     [int(raw["season"].min()), int(raw["season"].max())],
            "date_range": {
                "start": str(date_min),
                "end":   str(date_max),
            },
            "n_series":         n_series,
            "n_playoff_games":  len(po),
            "n_qualified_players": len(player_entries),
            "flag_counts": {
                "LATE_RISER":        len(late_risers),
                "STABLE":            len(stable),
                "LATE_FADER":        len(late_faders),
                "INSUFFICIENT_DATA": len(insufficient),
            },
            "constants": {
                "H31_MIN_PHASE_N":           H31_MIN_PHASE_N,
                "H31_MIN_TOTAL_PLAYOFF":     H31_MIN_TOTAL_PLAYOFF,
                "H31_PROGRESSION_THRESHOLD": H31_PROGRESSION_THRESHOLD,
                "H31_KEY_TIER":              H31_KEY_TIER,
                "H31_TIERS":                 H31_TIERS,
                "H31_PHASES":                H31_PHASES,
            },
        },
        "population": population,
        "players":    all_entries_clean,
        "summary": {
            "late_risers": [e["player"] for e in late_risers],
            "stable":      [e["player"] for e in stable],
            "late_faders": [e["player"] for e in late_faders],
            "insufficient": [e["player"] for e in insufficient],
        },
    }

    out_path = Path(args.output) if getattr(args, "output", None) else SERIES_PROGRESSION_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[backtest] H31 results → {out_path}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NBAgent Backtest — signal quality analysis")
    parser.add_argument("--season", type=str, help="Filter by season_end_year (e.g. 2026)")
    parser.add_argument("--start",  type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--end",    type=str, help="End date YYYY-MM-DD")
    parser.add_argument("--window", type=int, default=None,
                        help=f"Override rolling window size (default: {ROLLING_WINDOW})")
    parser.add_argument("--calibration-only", action="store_true",
                        help="Skip signal computation — only report tier calibration. Fast.")
    parser.add_argument("--output", type=str, default=None,
                        help="Override output JSON path (default: data/backtest_results.json)")
    parser.add_argument("--mode", type=str, default=None,
                        help="Analysis mode: 'bounce-back' | 'mean-reversion' | 'recency-weight' | 'player-bounce-back' | 'post-blowout' | 'opp-fatigue' | 'shooting-regression' | 'shot-volume' | 'ft-safety-margin' | 'positional-dvp' | 'opp-team-hit-rate' | '3pa-volume-gate' | 'spread-context' | 'blowout-regime' | 'losing-side-ast' | 'miss-anatomy' | 'elite-opp-rebounder' | 'star-absence' | 'primary-blowout' | 'playoff-career' | 'confidence-calibration' | 'minutes-elasticity' | 'consistency-index' | 'series-progression'")
    parser.add_argument("--stat", type=str, default=None,
                        help="Restrict to a single stat: PTS | REB | AST | 3PM")
    args = parser.parse_args()

    # ── Playoff career tier performance (H28) ────────────────────────
    # This mode reads playoff_career_log.csv directly — it does NOT need
    # player_log / team_log / master_df, so exit early before standard loaders
    # to avoid loading 20K unused rows.
    if getattr(args, "mode", None) == "playoff-career":
        run_playoff_career_analysis(args)
        sys.exit(0)

    # ── Player-level confidence calibration (H29) ────────────────────
    # This mode reads picks.json only via load_picks_json() — it does NOT need
    # player_log / team_log / master_df, so exit early before standard loaders.
    if getattr(args, "mode", None) == "confidence-calibration":
        picks = load_picks_json()
        if not picks:
            print("[backtest] No graded picks found — cannot run H29.")
            sys.exit(0)
        run_confidence_calibration_analysis(picks, args)
        sys.exit(0)

    # ── Playoff series progression (H31) ─────────────────────────────
    # This mode reads playoff_career_log.csv directly — it does NOT need
    # player_log / team_log / master_df, so exit early before standard loaders.
    if getattr(args, "mode", None) == "series-progression":
        run_series_progression_analysis(args)
        sys.exit(0)

    print("[backtest] Loading data...")
    whitelist  = load_whitelist()
    player_log = load_player_log(whitelist, args)
    team_log   = load_team_log(args)
    master_df  = load_master(args)

    if player_log.empty:
        print("[backtest] No player log data — nothing to analyze.")
        sys.exit(0)

    window = args.window if args.window else ROLLING_WINDOW

    # ── Bounce-back mode ──────────────────────────────────────────────
    if getattr(args, "mode", None) == "bounce-back":
        run_bounce_back_analysis(player_log, args)
        sys.exit(0)

    # ── Mean-reversion mode ───────────────────────────────────────────
    if getattr(args, "mode", None) == "mean-reversion":
        run_mean_reversion_analysis(player_log, team_log, args)
        sys.exit(0)

    # ── Recency-weight mode ───────────────────────────────────────────
    if getattr(args, "mode", None) == "recency-weight":
        run_recency_weight_analysis(player_log, args)
        sys.exit(0)

    # ── Player bounce-back mode ───────────────────────────────────────
    if getattr(args, "mode", None) == "player-bounce-back":
        run_player_bounce_back(player_log, args)
        sys.exit(0)

    # ── Post-blowout mode ─────────────────────────────────────────────
    if getattr(args, "mode", None) == "post-blowout":
        run_post_blowout_analysis(player_log, master_df, args)
        sys.exit(0)

    # ── Opponent fatigue mode ─────────────────────────────────────────
    if getattr(args, "mode", None) == "opp-fatigue":
        run_opp_fatigue_analysis(player_log, master_df, args)
        sys.exit(0)

    # ── Shooting regression mode ───────────────────────────────────────
    if getattr(args, "mode", None) == "shooting-regression":
        run_shooting_regression_analysis(player_log, args)
        sys.exit(0)

    # ── Shot volume mode ───────────────────────────────────────────────
    if getattr(args, "mode", None) == "shot-volume":
        run_shot_volume_analysis(player_log, args)
        sys.exit(0)

    # ── FG% safety margin mode ─────────────────────────────────────────
    if getattr(args, "mode", None) == "ft-safety-margin":
        run_ft_safety_margin_backtest(player_log, args)
        sys.exit(0)

    # ── Positional DvP mode ──────────────────────────────────────────
    if getattr(args, "mode", None) == "positional-dvp":
        whitelist_df = pd.read_csv(WHITELIST_CSV, dtype=str) if WHITELIST_CSV.exists() else pd.DataFrame()
        run_positional_dvp_analysis(player_log, team_log, whitelist_df, args)
        sys.exit(0)

    # ── Opponent team hit rate mode ──────────────────────────────────
    if getattr(args, "mode", None) == "opp-team-hit-rate":
        picks = load_picks_json()
        if not picks:
            print("[backtest] No graded picks found — cannot run H15.")
            sys.exit(0)
        run_opp_team_hit_rate_analysis(picks, args)
        sys.exit(0)

    # ── 3PA volume gate mode ──────────────────────────────────────────
    if getattr(args, "mode", None) == "3pa-volume-gate":
        picks = load_picks_json()
        if not picks:
            print("[backtest] No graded picks found — cannot run H16.")
            sys.exit(0)
        run_3pa_volume_gate_analysis(picks, player_log, args)
        sys.exit(0)

    # ── Spread context mode ───────────────────────────────────────────
    if getattr(args, "mode", None) == "spread-context":
        picks = load_picks_json()
        if not picks:
            print("[backtest] No graded picks found — cannot run H17.")
            sys.exit(0)
        run_spread_context_analysis(picks, master_df, args)
        sys.exit(0)

    # ── In-game blowout regime (H19) ─────────────────────────────────────
    if getattr(args, "mode", None) == "blowout-regime":
        run_blowout_regime_analysis(player_log, master_df, args)
        sys.exit(0)

    # ── Losing-side AST suppression (H20) ────────────────────────────────
    if getattr(args, "mode", None) == "losing-side-ast":
        run_losing_side_ast_analysis(player_log, master_df, args)
        sys.exit(0)

    # ── Miss anatomy (H21) ───────────────────────────────────────────────
    if getattr(args, "mode", None) == "miss-anatomy":
        run_miss_anatomy_analysis(player_log, args)
        sys.exit(0)

    # ── Elite opposing rebounder (H14) ───────────────────────────────────
    if getattr(args, "mode", None) == "elite-opp-rebounder":
        run_elite_opp_rebounder_analysis(player_log, team_log, args)
        sys.exit(0)

    # ── Star absence teammate impact (H26) ────────────────────────────────
    if getattr(args, "mode", None) == "star-absence":
        run_star_absence_analysis(player_log, args)
        sys.exit(0)

    # ── Primary scorer blowout PTS (H27) ─────────────────────────────
    if getattr(args, "mode", None) == "primary-blowout":
        run_primary_blowout_analysis(player_log, master_df, args)
        sys.exit(0)

    # ── Minutes elasticity (H30) ─────────────────────────────────────
    if getattr(args, "mode", None) == "minutes-elasticity":
        run_minutes_elasticity_analysis(player_log, args)
        sys.exit(0)

    # ── Player consistency index (H32) ───────────────────────────────
    if getattr(args, "mode", None) == "consistency-index":
        run_consistency_index_analysis(player_log, master_df, args)
        sys.exit(0)

    # ── Calibration-only fast path ────────────────────────────────────
    if args.calibration_only:
        print(f"[backtest] Calibration-only mode | rolling window = {window}")
        player_log = add_best_tiers(player_log, window=window)
        calibration = tier_calibration(player_log)

        # Instance counts per stat (proxy for daily pick volume)
        sep = "─" * 60
        print(f"\n{'='*60}")
        print(f"  Tier Calibration  |  window={window} games")
        print(f"  Date range: {player_log['game_date'].min().date()} → {player_log['game_date'].max().date()}")
        print(f"{'='*60}")
        total = 0
        for stat in ("PTS", "REB", "AST", "3PM"):
            n_qual = int(player_log[f"best_tier_{stat}"].notna().sum())
            total += n_qual
            print(f"\n  {stat}  ({n_qual:,} qualified instances)")
            print(f"  {sep}")
            for tier_str, entry in sorted(calibration.get(stat, {}).items(), key=lambda x: int(x[0])):
                n    = entry["n"]
                hr   = entry["hit_rate"]
                flag = "  ⚠ BELOW FLOOR" if entry.get("flag") == "threshold_concern" else ""
                print(f"    Tier {tier_str:<6} n={n:<6} hit_rate={hr*100:.1f}%{flag}")
        print(f"\n  Total qualified instances: {total:,}  (baseline window=10: 5,368)")
        print(f"  Avg instances/day: {total / max(1, (player_log['game_date'].max() - player_log['game_date'].min()).days) * 4.0:.1f} (÷ by ~4 stats × days)")
        print(f"\n{'='*60}\n")

        # Write JSON output
        out_path = Path(args.output) if args.output else RESULTS_JSON
        cal_output = {
            "generated_at":    dt.date.today().isoformat(),
            "mode":            "calibration_only",
            "rolling_window":  window,
            "date_range": {
                "start": str(player_log["game_date"].min().date()),
                "end":   str(player_log["game_date"].max().date()),
            },
            "total_instances":     total,
            "instances_by_stat":   {s: int(player_log[f"best_tier_{s}"].notna().sum()) for s in STAT_COL},
            "tier_calibration":    calibration,
        }
        with open(out_path, "w") as f:
            json.dump(cal_output, f, indent=2)
        print(f"[backtest] Calibration results written → {out_path}")
        sys.exit(0)

    # ── Compute signals ──────────────────────────────────────────────
    print("[backtest] Computing trend signals...")
    player_log = add_trend_signals(player_log)

    print("[backtest] Building opponent defense lookup...")
    opp_lookup = build_opp_defense_lookup(team_log)
    print("[backtest] Applying opponent defense signal...")
    player_log = add_opp_defense_signal(player_log, opp_lookup)

    print("[backtest] Computing pace signal...")
    player_log["pace_tag"] = add_b2b_signal(  # placeholder index align
        player_log, master_df
    )["on_b2b"]  # will be replaced; just initializing
    player_log["pace_tag"] = build_pace_lookup(team_log, player_log)

    print("[backtest] Computing B2B signal...")
    player_log = add_b2b_signal(player_log, master_df)

    print("[backtest] Computing spread risk signal...")
    player_log = add_spread_signal(player_log, master_df)

    # ── Best tier selection ──────────────────────────────────────────
    print(f"[backtest] Computing best tier hit rates (rolling window={window})...")
    player_log = add_best_tiers(player_log, window=window)

    # ── Summary stats ────────────────────────────────────────────────
    total_instances = 0
    for stat in STAT_COL:
        n = player_log[f"best_tier_{stat}"].notna().sum()
        total_instances += n
        print(f"[backtest] {stat}: {n:,} qualified instances")

    date_min = player_log["game_date"].min().strftime("%Y-%m-%d")
    date_max = player_log["game_date"].max().strftime("%Y-%m-%d")
    total_player_game_dates = player_log["player_name"].nunique() * player_log["game_date"].nunique()

    # ── Signal analysis ──────────────────────────────────────────────
    print("[backtest] Running signal analysis...")
    signal_results = {}
    for stat in STAT_COL:
        signal_results[stat] = {}
        for sig_name, sig_cols in SIGNALS.items():
            sig_col = sig_cols[stat]
            if sig_col not in player_log.columns:
                continue
            signal_results[stat][sig_name] = analyze_signal(
                player_log, stat, sig_col, sig_name
            )

    # ── Tier calibration ─────────────────────────────────────────────
    calibration = tier_calibration(player_log)

    # ── Signal combinations ──────────────────────────────────────────
    print("[backtest] Computing signal combinations...")
    combinations = top_signal_combinations(player_log, signal_results)

    # ── Recommendations ──────────────────────────────────────────────
    recommendations = build_recommendations(signal_results, calibration)

    # ── Output ───────────────────────────────────────────────────────
    meta = {
        "generated_at":          dt.date.today().isoformat(),
        "date_range":            {"start": date_min, "end": date_max},
        "total_instances":       int(total_instances),
        "total_player_game_dates": int(player_log[["player_name", "game_date"]].drop_duplicates().__len__()),
        "whitelist_players":     int(player_log["player_name"].nunique()),
    }

    output = {
        **meta,
        "signal_analysis":  signal_results,
        "tier_calibration": calibration,
        "top_combinations": combinations,
        "recommendations":  recommendations,
    }

    out_path = Path(args.output) if args.output else RESULTS_JSON
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[backtest] Results written → {out_path}")

    print_report(signal_results, calibration, meta)

    for rec in recommendations:
        print(f"  • {rec}")

    print(f"\n{'='*72}\n")


if __name__ == "__main__":
    main()
