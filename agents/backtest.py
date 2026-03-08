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

# ── Tier definitions (mirrors quant.py) ───────────────────────────────
PTS_TIERS = [10, 15, 20, 25, 30]
REB_TIERS = [2, 4, 6, 8, 10, 12]
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

# FG% safety margin mode constants
FSM_JSON        = DATA / "backtest_ft_safety_margin.json"
FSM_L20_WINDOW  = 20    # games used to compute season averages
FSM_MIN_GAMES   = 10    # min valid (non-DNP, fga>0) games in L20 to qualify
FSM_SAFE_THRESH = 0.05  # margin >= this → safe
FSM_FRAG_THRESH = 0.00  # margin <  this → fragile (else borderline)
FSM_MIN_N       = 20    # min instances per fragility bucket for a verdict


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
                        help="Analysis mode: 'bounce-back' | 'mean-reversion' | 'recency-weight' | 'player-bounce-back' | 'post-blowout' | 'opp-fatigue' | 'shooting-regression' | 'shot-volume' | 'ft-safety-margin'")
    parser.add_argument("--stat", type=str, default=None,
                        help="Restrict to a single stat: PTS | REB | AST | 3PM")
    args = parser.parse_args()

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
