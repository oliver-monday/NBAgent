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
RESULTS_JSON       = DATA / "backtest_results.json"
BOUNCE_BACK_JSON   = DATA / "backtest_bounce_back.json"

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
            df[hit_col] = (df[col] > tier).astype(float)
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

        # Actual hit: actual stat > best_tier_value
        actual_hit = pd.Series(np.nan, index=df.index, dtype="float64")
        has_tier = best.notna()
        if has_tier.any():
            actual_hit[has_tier] = (
                df.loc[has_tier, col] > df.loc[has_tier, f"best_tier_{stat}"]
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
        df[f"_hit_{tier}"] = (df[col] > tier).astype(float)
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
                        help="Analysis mode: 'bounce-back' for sequential-game analysis")
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
