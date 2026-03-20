#!/usr/bin/env python3
"""
NBAgent — Quant

Runs after ingest, before Analyst. Reads player_game_log.csv,
team_game_log.csv, and nba_master.csv to produce data/player_stats.json —
a pre-computed stats card per player that the Analyst and Parlay agents consume.

Per-player outputs:
  - Tier hit rates (last 20 games)
  - Best qualifying tier per stat (≥70% hit rate, or null)
  - Trend: up / stable / down (last 5 vs last 10 avg)
  - Home/away splits (best tier per split)
  - Minutes trend
  - Back-to-back flag for today's game
  - Opponent defensive context (last 15 games): rank + raw avg allowed
  - Teammate correlations: Pearson r + correlation_tag for each stat pair
  - Game pace context: combined scoring avg for today's matchup
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GAME_LOG_CSV      = DATA / "player_game_log.csv"
TEAM_LOG_CSV      = DATA / "team_game_log.csv"
MASTER_CSV        = DATA / "nba_master.csv"
WHITELIST_CSV     = ROOT / "playerprops" / "player_whitelist.csv"
PLAYER_STATS_JSON             = DATA / "player_stats.json"
TEAM_DEFENSE_NARRATIVES_JSON  = DATA / "team_defense_narratives.json"

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ────────────────────────────────────────────────────────────
PLAYER_WINDOW        = 20   # games for tier hit rates + trend base
TREND_SHORT_WINDOW   = 5    # games for "recent" trend comparison
TREND_THRESHOLD      = 0.10 # >10% delta = up/down
MINUTES_THRESHOLD    = 3.0  # >3 min delta = increasing/decreasing
MIN_GAMES            = 5    # skip players with fewer games
OPP_WINDOW           = 15   # games for opponent defensive context
CONFIDENCE_FLOOR     = 0.70 # minimum hit rate for a "best tier" pick
CORR_MIN_GAMES       = 8    # minimum shared games for teammate correlation
CORR_STRONG          = 0.35 # |r| >= this = strong correlation
CORR_MODERATE        = 0.15 # |r| >= this = moderate correlation
PACE_WINDOW          = 10   # games for game pace / combined scoring context
MIN_MATCHUP_GAMES    = 3    # minimum games per opp-rating bucket for matchup splits
SPREAD_COMPETITIVE   = 6.5  # spread_abs ≤ this = competitive game
SPREAD_BLOWOUT_RISK  = 8.0  # spread_abs > this for favored team → blowout risk flag
SPREAD_BIG_FAVORITE  = 13.0 # spread_abs > this → cap analyst confidence at 80%
MIN_SPREAD_GAMES     = 5    # min games per spread bucket for historical split
B2B_MIN_GAMES        = 5    # min B2B games to compute b2b_hit_rates (else → one-tier-down flag)
REST_DENSE_DAYS      = 5    # look-back window (days) for dense schedule detection
REST_DENSE_THRESHOLD = 4    # games in REST_DENSE_DAYS window = dense schedule

# Tier definitions
PTS_TIERS = [10, 15, 20, 25, 30]
REB_TIERS = [4, 6, 8, 10, 12]
AST_TIERS = [2, 4, 6, 8, 10, 12]
TPM_TIERS = [1, 2, 3, 4]

TIERS    = {"PTS": PTS_TIERS, "REB": REB_TIERS, "AST": AST_TIERS, "3PM": TPM_TIERS}
STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}


# ── Loaders ───────────────────────────────────────────────────────────

def load_player_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        print("[quant] ERROR: player_game_log.csv not found.")
        sys.exit(1)
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["game_date"] < TODAY_STR].copy()
    df = df[df["dnp"].astype(str) != "1"].copy()
    for col in ["pts", "reb", "ast", "tpm", "minutes_raw"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("game_date", ascending=False)


def load_team_log() -> pd.DataFrame:
    if not TEAM_LOG_CSV.exists():
        print("[quant] WARNING: team_game_log.csv not found — skipping opp context.")
        return pd.DataFrame()
    df = pd.read_csv(TEAM_LOG_CSV, dtype={"game_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["game_date"] < TODAY_STR].copy()
    for col in ["team_pts", "team_reb", "team_ast", "team_tpm"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("game_date", ascending=False)


def load_todays_games() -> list[dict]:
    if not MASTER_CSV.exists():
        return []
    df = pd.read_csv(MASTER_CSV, dtype=str)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    today = df[df["game_date"] == TODAY_STR].copy()
    games = []
    for _, row in today.iterrows():
        def _spread(val):
            try:
                f = float(val)
                return None if pd.isna(f) else round(f, 1)
            except Exception:
                return None
        games.append({
            "game_date":   TODAY_STR,
            "home":        row.get("home_team_abbrev", ""),
            "away":        row.get("away_team_abbrev", ""),
            "home_spread": _spread(row.get("home_spread")),
            "away_spread": _spread(row.get("away_spread")),
        })
    return games


def load_whitelist() -> set:
    """
    Returns set of (lowercase_name, uppercase_team) tuples for active players.
    Filtering on both name AND team prevents traded players from appearing
    under their old team when game log rows for both teams exist.
    """
    if not WHITELIST_CSV.exists():
        return set()
    try:
        df = pd.read_csv(WHITELIST_CSV, dtype=str)
        active = df[df["active"].astype(str).str.strip() == "1"]
        pairs = set(zip(
            active["player_name"].str.strip().str.lower(),
            active["team_abbr"].str.strip().str.upper()
        ))
        return pairs
    except Exception:
        return set()


def load_whitelist_positions() -> dict:
    """Returns {lowercase_player_name: position} for active players."""
    if not WHITELIST_CSV.exists():
        return {}
    try:
        df = pd.read_csv(WHITELIST_CSV, dtype=str)
        active = df[df["active"].astype(str).str.strip() == "1"]
        return {
            row["player_name"].strip().lower(): row.get("position", "").strip()
            for _, row in active.iterrows()
        }
    except Exception:
        return {}


# ── Back-to-back detection ─────────────────────────────────────────────

def build_b2b_teams(master_df: pd.DataFrame) -> set[str]:
    yesterday = (TODAY - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    master_df["game_date"] = pd.to_datetime(
        master_df["game_date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")

    yesterday_games = master_df[master_df["game_date"] == yesterday]
    teams_yesterday = set()
    for _, row in yesterday_games.iterrows():
        h = str(row.get("home_team_abbrev", "")).upper()
        a = str(row.get("away_team_abbrev", "")).upper()
        if h: teams_yesterday.add(h)
        if a: teams_yesterday.add(a)

    today_games = master_df[master_df["game_date"] == TODAY_STR]
    teams_today = set()
    for _, row in today_games.iterrows():
        h = str(row.get("home_team_abbrev", "")).upper()
        a = str(row.get("away_team_abbrev", "")).upper()
        if h: teams_today.add(h)
        if a: teams_today.add(a)

    return teams_yesterday & teams_today


def build_b2b_game_ids(master_df: pd.DataFrame) -> dict:
    """
    For each team, identify which historical game_ids represent a back-to-back
    second night (the team played the previous calendar day).

    Returns: {TEAM_ABBREV_UPPER: set_of_normalized_game_id_strings}

    Used by compute_b2b_hit_rates() to split a player's game log into
    B2B vs normal-rest games for quantified tier analysis.
    """
    df = master_df.copy()
    df["_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.date
    df["_gid"]  = df["game_id"].astype(str).str.split(".").str[0].str.strip()

    # Build flat list of (team, date, game_id)
    records = []
    for _, row in df.iterrows():
        gid   = row["_gid"]
        gdate = row["_date"]
        if pd.isna(gdate):
            continue
        h = str(row.get("home_team_abbrev", "") or "").upper().strip()
        a = str(row.get("away_team_abbrev", "") or "").upper().strip()
        if h: records.append((h, gdate, gid))
        if a: records.append((a, gdate, gid))

    if not records:
        return {}

    rdf = pd.DataFrame(records, columns=["team", "date", "game_id"])
    rdf = rdf.sort_values(["team", "date"]).reset_index(drop=True)

    b2b: dict = {}
    for team, grp in rdf.groupby("team"):
        grp = grp.sort_values("date").reset_index(drop=True)
        for i in range(1, len(grp)):
            prev_date = grp.loc[i - 1, "date"]
            curr_date = grp.loc[i, "date"]
            if isinstance(prev_date, dt.date) and isinstance(curr_date, dt.date):
                if (curr_date - prev_date).days == 1:
                    b2b.setdefault(team, set()).add(grp.loc[i, "game_id"])

    return b2b


# ── Game spread context ───────────────────────────────────────────────

def build_game_spreads(todays_games: list[dict]) -> dict:
    """
    For each team playing today, derive spread context from the home_spread /
    away_spread already parsed into todays_games by load_todays_games().

    Spread convention: negative = this team is favored.
      home_spread = -6.5 → home team is giving 6.5 points.

    Returns:
      {
        "NYK": {
          "spread":       -6.5,   # signed from this team's perspective (neg = favored)
          "spread_abs":    6.5,
          "is_favorite":   True,
          "blowout_risk":  False, # True when is_favorite AND spread_abs > SPREAD_BLOWOUT_RISK
        }, ...
      }
    Teams with no spread data get spread=None, blowout_risk=False.
    """
    result: dict = {}
    for g in todays_games:
        home = (g.get("home") or "").upper()
        away = (g.get("away") or "").upper()
        hs   = g.get("home_spread")   # signed for home team
        as_  = g.get("away_spread")   # signed for away team

        for team, spread in [(home, hs), (away, as_)]:
            if not team:
                continue
            if spread is not None:
                spread_abs = round(abs(spread), 1)
                is_fav     = spread < 0
                blowout    = is_fav and spread_abs > SPREAD_BLOWOUT_RISK
            else:
                spread_abs = None
                is_fav     = None
                blowout    = False
            result[team] = {
                "spread":       spread,
                "spread_abs":   spread_abs,
                "is_favorite":  is_fav,
                "blowout_risk": blowout,
            }
    return result


def build_team_momentum(master_df: pd.DataFrame, teams_today: set[str]) -> dict:
    """
    Compute L10 win/loss record and average point margin for each team playing today.

    Uses completed games only (games where both home_score and away_score are non-null
    and the game_date is before TODAY_STR).

    Returns:
        {
            "HOU": {
                "l10_wins":   4,
                "l10_losses": 6,
                "l10_pct":    0.4,
                "l10_margin": -3.2,   # avg point differential (positive = winning)
                "tag":        "cold"  # "hot" (7+W), "cold" (≤3W), "neutral" otherwise
            },
            ...
        }
    Returns {} if master_df is empty or None.
    """
    if master_df is None or master_df.empty:
        return {}

    df = master_df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    # Completed games only: both scores present, date before today
    df = df[df["game_date"] < TODAY_STR].copy()
    for col in ["home_score", "away_score"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["home_score", "away_score"])

    momentum: dict = {}

    for team in teams_today:
        team = team.upper()
        # Find all games where this team was home or away
        home_mask = df["home_team_abbrev"].str.upper() == team
        away_mask = df["away_team_abbrev"].str.upper() == team
        team_games = df[home_mask | away_mask].sort_values("game_date", ascending=False)

        last10 = team_games.head(10)
        if last10.empty:
            continue

        wins = 0
        losses = 0
        margins = []

        for _, row in last10.iterrows():
            is_home = str(row.get("home_team_abbrev", "")).upper() == team
            if is_home:
                team_pts = row["home_score"]
                opp_pts  = row["away_score"]
            else:
                team_pts = row["away_score"]
                opp_pts  = row["home_score"]
            margin = team_pts - opp_pts
            margins.append(margin)
            if margin > 0:
                wins += 1
            else:
                losses += 1

        n = wins + losses
        l10_pct    = round(wins / n, 3) if n > 0 else None
        l10_margin = round(sum(margins) / len(margins), 1) if margins else None

        if wins >= 7:
            tag = "hot"
        elif wins <= 3:
            tag = "cold"
        else:
            tag = "neutral"

        momentum[team] = {
            "l10_wins":   wins,
            "l10_losses": losses,
            "l10_pct":    l10_pct,
            "l10_margin": l10_margin,
            "tag":        tag,
        }

    return momentum


# ── Opponent defensive context ────────────────────────────────────────

def build_opp_defense(team_log: pd.DataFrame) -> dict:
    if team_log.empty:
        return {}

    tl = team_log[["game_id", "game_date", "team_abbrev", "opp_abbrev",
                    "team_pts", "team_reb", "team_ast", "team_tpm"]].copy()

    tl_opp = tl.rename(columns={
        "team_abbrev": "opp_check",
        "opp_abbrev":  "team_check",
        "team_pts":    "allowed_pts",
        "team_reb":    "allowed_reb",
        "team_ast":    "allowed_ast",
        "team_tpm":    "allowed_tpm",
    })

    merged = tl.merge(
        tl_opp[["game_id", "opp_check", "team_check",
                 "allowed_pts", "allowed_reb", "allowed_ast", "allowed_tpm"]],
        left_on=["game_id", "team_abbrev", "opp_abbrev"],
        right_on=["game_id", "team_check", "opp_check"],
        how="inner"
    )

    result = {}
    all_teams = merged["team_abbrev"].unique()

    team_avgs = {}
    for team in all_teams:
        rows = merged[merged["team_abbrev"] == team].sort_values(
            "game_date", ascending=False
        ).head(OPP_WINDOW)
        if len(rows) < 3:
            continue
        team_avgs[team] = {
            "PTS": round(rows["allowed_pts"].mean(), 1),
            "REB": round(rows["allowed_reb"].mean(), 1),
            "AST": round(rows["allowed_ast"].mean(), 1),
            "3PM": round(rows["allowed_tpm"].mean(), 1),
        }

    n_teams = len(team_avgs)
    for stat in ["PTS", "REB", "AST", "3PM"]:
        sorted_teams = sorted(team_avgs.keys(), key=lambda t: team_avgs[t][stat])
        for rank, team in enumerate(sorted_teams, 1):
            if team not in result:
                result[team] = {}
            avg = team_avgs[team][stat]
            if rank <= max(1, round(n_teams * 0.33)):
                rating = "tough"
            elif rank <= max(1, round(n_teams * 0.67)):
                rating = "mid"
            else:
                rating = "soft"
            result[team][stat] = {
                "allowed_pg": avg,
                "rank": rank,
                "n_teams": n_teams,
                "rating": rating,
            }

    return result


# ── Opponent defensive recency split ─────────────────────────────────

DEF_RECENCY_SHORT   = 5    # recent window for recency comparison
DEF_RECENCY_THRESH  = 0.08 # ≥8% divergence from L15 = trending flag
DEF_RECENCY_MIN_L5  = 3    # minimum games in L5 window to compute flag


def compute_opp_defense_recency(team_log: pd.DataFrame) -> dict:
    """
    For each team in team_log, compare their allowed PTS average over the last
    DEF_RECENCY_SHORT (5) games vs. the last OPP_WINDOW (15) games.

    Flags when the L5 average diverges from the L15 average by ≥ DEF_RECENCY_THRESH (8%):
      - "soft"  when L5 allowed avg ≥ 8% ABOVE L15 (defense trending softer — leaking more)
      - "tough" when L5 allowed avg ≥ 8% BELOW L15 (defense trending tougher — locking down)
      - None    otherwise (neutral / insufficient data)

    Uses PTS only as the primary recency signal (most stable indicator of defensive trend).

    Returns:
        {
            "HOU": {
                "flag":      "soft",   # "soft" | "tough" | None
                "l5_avg":    115.4,    # allowed PTS per game, last 5 games
                "l15_avg":   110.2,    # allowed PTS per game, last 15 games
                "delta_pct": 0.047,    # (l5_avg - l15_avg) / l15_avg; positive = trending soft
                "n_l5":      5,
                "n_l15":     15,
            },
            ...
        }
    Returns {} if team_log is empty.
    """
    if team_log.empty:
        return {}

    # Mirror the self-join from build_opp_defense() to get allowed_pts per game
    tl = team_log[["game_id", "game_date", "team_abbrev", "opp_abbrev", "team_pts"]].copy()
    tl_opp = tl.rename(columns={
        "team_abbrev": "opp_check",
        "opp_abbrev":  "team_check",
        "team_pts":    "allowed_pts",
    })
    merged = tl.merge(
        tl_opp[["game_id", "opp_check", "team_check", "allowed_pts"]],
        left_on=["game_id", "team_abbrev", "opp_abbrev"],
        right_on=["game_id", "team_check", "opp_check"],
        how="inner",
    )

    if merged.empty:
        return {}

    result: dict = {}
    for team in merged["team_abbrev"].unique():
        rows = (
            merged[merged["team_abbrev"] == team]
            .sort_values("game_date", ascending=False)  # newest first
        )
        l15_rows = rows.head(OPP_WINDOW)          # last 15
        l5_rows  = rows.head(DEF_RECENCY_SHORT)   # last 5

        n_l15 = len(l15_rows)
        n_l5  = len(l5_rows)

        if n_l15 < 3 or n_l5 < DEF_RECENCY_MIN_L5:
            continue

        l15_avg = round(l15_rows["allowed_pts"].mean(), 1)
        l5_avg  = round(l5_rows["allowed_pts"].mean(), 1)

        if l15_avg == 0:
            continue

        delta_pct = (l5_avg - l15_avg) / l15_avg  # positive = leaking more (soft trend)

        if delta_pct >= DEF_RECENCY_THRESH:
            flag = "soft"
        elif delta_pct <= -DEF_RECENCY_THRESH:
            flag = "tough"
        else:
            flag = None

        result[team] = {
            "flag":      flag,
            "l5_avg":    l5_avg,
            "l15_avg":   l15_avg,
            "delta_pct": round(delta_pct, 4),
            "n_l5":      n_l5,
            "n_l15":     n_l15,
        }

    return result


def _ordinal(n: int) -> str:
    """Return e.g. 1→'1st', 2→'2nd', 3→'3rd', 4→'4th', 11→'11th', 21→'21st'."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def build_team_defense_narratives(team_log: pd.DataFrame) -> dict[str, str]:
    """
    Compute a one-line defensive narrative per team from team_game_log.csv,
    using the last OPP_WINDOW (15) games — same window as build_opp_defense().

    Narrative format:
      {ABBR} (last 15g): Allows {ppg:.1f} PPG (rank: {ordinal}).{perimeter_clause}{pace_clause}

    Perimeter clause: requires fg3_pct_allowed column — omitted if unavailable.
    Pace clause:      requires possessions column — omitted if unavailable.
    (Current team_game_log schema lacks both; function is structured for easy expansion.)

    Writes data/team_defense_narratives.json and returns the narratives dict.
    Fails silently — never blocks the main quant run.
    """
    if team_log.empty:
        print("[quant] WARNING: team_log empty — skipping team defense narratives.")
        return {}

    # ── Mirror the self-join from build_opp_defense() to get pts_allowed ──
    has_3p   = "fg3_pct_allowed" in team_log.columns  # not in current schema
    has_pace = "possessions" in team_log.columns        # not in current schema

    base_cols = ["game_id", "game_date", "team_abbrev", "opp_abbrev", "team_pts"]
    extra_cols = []
    if has_3p:
        extra_cols.append("fg3_pct_allowed")
    if has_pace:
        extra_cols.append("possessions")
    tl = team_log[[c for c in base_cols + extra_cols if c in team_log.columns]].copy()

    rename_map: dict[str, str] = {
        "team_abbrev": "opp_check",
        "opp_abbrev":  "team_check",
        "team_pts":    "allowed_pts",
    }
    if has_3p:
        rename_map["fg3_pct_allowed"] = "allowed_fg3_pct"
    tl_opp = tl.rename(columns=rename_map)

    merge_right_cols = ["game_id", "opp_check", "team_check", "allowed_pts"]
    if has_3p:
        merge_right_cols.append("allowed_fg3_pct")

    merged = tl.merge(
        tl_opp[merge_right_cols],
        left_on=["game_id", "team_abbrev", "opp_abbrev"],
        right_on=["game_id", "team_check", "opp_check"],
        how="inner",
    )

    if merged.empty:
        print("[quant] WARNING: team_log merge empty — skipping team defense narratives.")
        return {}

    # ── Per-team averages over last OPP_WINDOW games ──────────────────────
    team_avgs: dict[str, dict] = {}
    for team in merged["team_abbrev"].unique():
        rows = (
            merged[merged["team_abbrev"] == team]
            .sort_values("game_date", ascending=False)
            .head(OPP_WINDOW)
        )
        if len(rows) < 3:
            continue
        avgs: dict = {
            "allowed_pts": round(float(rows["allowed_pts"].mean()), 1),
            "n": len(rows),
        }
        if has_3p and "allowed_fg3_pct" in rows.columns:
            avgs["allowed_fg3_pct"] = round(float(rows["allowed_fg3_pct"].mean()), 1)
        if has_pace and "possessions" in rows.columns:
            avgs["possessions"] = round(float(rows["possessions"].mean()), 1)
        team_avgs[team] = avgs

    if not team_avgs:
        return {}

    n_teams = len(team_avgs)

    # ── League ranks ──────────────────────────────────────────────────────
    # PPG allowed: rank 1 = best defense (fewest points allowed)
    sorted_by_pts = sorted(team_avgs, key=lambda t: team_avgs[t]["allowed_pts"])
    ppg_ranks = {team: rank for rank, team in enumerate(sorted_by_pts, start=1)}

    # 3P% allowed: rank 1 = best perimeter defense (lowest %)
    fg3_ranks: dict[str, int] = {}
    if has_3p:
        teams_with_fg3 = [t for t in team_avgs if "allowed_fg3_pct" in team_avgs[t]]
        sorted_by_fg3 = sorted(teams_with_fg3, key=lambda t: team_avgs[t]["allowed_fg3_pct"])
        fg3_ranks = {team: rank for rank, team in enumerate(sorted_by_fg3, start=1)}

    # Pace: rank 1 = most possessions (fastest pace)
    pace_ranks: dict[str, int] = {}
    if has_pace:
        teams_with_pace = [t for t in team_avgs if "possessions" in team_avgs[t]]
        sorted_by_pace = sorted(
            teams_with_pace, key=lambda t: team_avgs[t]["possessions"], reverse=True
        )
        pace_ranks = {team: rank for rank, team in enumerate(sorted_by_pace, start=1)}

    # ── Assemble narratives ───────────────────────────────────────────────
    narratives: dict[str, str] = {}
    for team in sorted(team_avgs):
        avgs = team_avgs[team]
        ppg  = avgs["allowed_pts"]
        ppg_rank = ppg_ranks[team]

        line = f"{team} (last 15g): Allows {ppg:.1f} PPG (rank: {_ordinal(ppg_rank)})."

        # Perimeter clause
        if has_3p and team in fg3_ranks:
            fg3_pct  = avgs["allowed_fg3_pct"]
            fg3_rank = fg3_ranks[team]
            if fg3_rank <= 10:
                label = "Strong perimeter defense"
            elif fg3_rank <= 20:
                label = "Average perimeter defense"
            else:
                label = "Weak perimeter defense"
            line += (
                f" {label} — opponents shooting {fg3_pct:.1f}% from 3"
                f" (rank: {_ordinal(fg3_rank)})."
            )

        # Pace clause — only for clearly high/low pace; average is omitted
        if has_pace and team in pace_ranks:
            poss      = avgs["possessions"]
            pace_rank = pace_ranks[team]
            if pace_rank <= 8:
                line += f" High pace ({poss:.1f} poss/g). Inflates all counting stats."
            elif pace_rank >= n_teams - 7:
                line += f" Low pace ({poss:.1f} poss/g). Suppresses counting stats."

        narratives[team] = line

    # ── Write JSON ────────────────────────────────────────────────────────
    output = {"as_of": TODAY_STR, "narratives": narratives}
    try:
        with open(TEAM_DEFENSE_NARRATIVES_JSON, "w") as fh:
            json.dump(output, fh, indent=2)
        print(
            f"[quant] Team defense narratives: {len(narratives)} teams → "
            f"{TEAM_DEFENSE_NARRATIVES_JSON}"
        )
    except Exception as e:
        print(f"[quant] WARNING: could not write team defense narratives: {e}")

    return narratives


def compute_positional_dvp(player_log: pd.DataFrame, position_map: dict) -> dict:
    """
    For each team, compute average allowed PTS/REB/AST/3PM broken down by
    opponent player position (PG/SG/SF/PF/C).

    Returns:
    {
      "BOS": {
        "PG": {"pts_allowed_avg": 18.2, "reb_allowed_avg": 3.1,
               "ast_allowed_avg": 6.4, "tpm_allowed_avg": 2.1,
               "pts_rating": "soft", "reb_rating": "mid",
               "ast_rating": "tough", "tpm_rating": "soft", "n": 42},
        ...
      },
      ...
    }

    Minimum 10 player-game observations per (team, position) cell.
    Ratings are percentile-ranked within each position group across all teams
    (not globally), using the same 33/67 thresholds as build_opp_defense().
    """
    POSITIONS = ["PG", "SG", "SF", "PF", "C"]
    MIN_OBS   = 10

    if player_log.empty or not position_map:
        return {}

    # Exclude DNP rows
    df = player_log[player_log["dnp"].astype(str).str.strip() != "1"].copy()

    # Attach position from whitelist
    df["position"] = df["player_name"].str.strip().str.lower().map(position_map)
    df = df[df["position"].notna() & (df["position"].str.strip() != "")]

    # Convert stat columns to numeric
    for col in ["pts", "reb", "ast", "tpm"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["pts", "reb", "ast", "tpm"])

    # opp_abbrev = the defending team; group by (defending_team, position)
    grouped = df.groupby(["opp_abbrev", "position"])

    # Build per-cell averages; enforce minimum observations
    cell_data = {}  # {(team_upper, pos): {avg data}}
    for (team, pos), grp in grouped:
        n = len(grp)
        if n < MIN_OBS:
            continue
        cell_data[(team.upper(), pos)] = {
            "pts_allowed_avg": round(grp["pts"].mean(), 1),
            "reb_allowed_avg": round(grp["reb"].mean(), 1),
            "ast_allowed_avg": round(grp["ast"].mean(), 1),
            "tpm_allowed_avg": round(grp["tpm"].mean(), 1),
            "n": n,
        }

    if not cell_data:
        return {}

    # Assign soft/mid/tough ratings per position group per stat.
    # Within each position group, rank teams lowest-to-highest allowed avg;
    # lowest = toughest defense (same direction as build_opp_defense).
    result = {}

    stat_specs = [
        ("pts_rating", "pts_allowed_avg"),
        ("reb_rating", "reb_allowed_avg"),
        ("ast_rating", "ast_allowed_avg"),
        ("tpm_rating", "tpm_allowed_avg"),
    ]

    for pos in POSITIONS:
        pos_cells = [(team, data) for (team, p), data in cell_data.items() if p == pos]
        if not pos_cells:
            continue
        n_pos_teams = len(pos_cells)

        for rating_key, avg_key in stat_specs:
            sorted_cells = sorted(pos_cells, key=lambda x: x[1][avg_key])
            for rank, (team, data) in enumerate(sorted_cells, 1):
                if rank <= max(1, round(n_pos_teams * 0.33)):
                    rating = "tough"
                elif rank <= max(1, round(n_pos_teams * 0.67)):
                    rating = "mid"
                else:
                    rating = "soft"

                if team not in result:
                    result[team] = {}
                if pos not in result[team]:
                    # Copy all base avg fields on first write for this cell
                    result[team][pos] = dict(cell_data[(team, pos)])
                result[team][pos][rating_key] = rating

    return result


# ── Game pace context ─────────────────────────────────────────────────

def build_game_pace(team_log: pd.DataFrame, todays_games: list[dict]) -> dict:
    """
    For each today's matchup, compute:
      - combined_pts_avg: avg total points scored in last N head-to-head games
        (falls back to sum of each team's offensive avg if <3 H2H games)
      - pace_tag: "high" (>220), "mid" (200-220), "low" (<200)

    Returns: {"NYK_MIA": {"combined_pts_avg": 228.4, "pace_tag": "high"}, ...}
    Key is always "{away}_{home}" normalized.
    """
    if team_log.empty:
        return {}

    result = {}

    for g in todays_games:
        home = g["home"].upper()
        away = g["away"].upper()
        key  = f"{away}_{home}"

        # Try head-to-head first
        h2h = team_log[
            ((team_log["team_abbrev"] == home) & (team_log["opp_abbrev"] == away)) |
            ((team_log["team_abbrev"] == away) & (team_log["opp_abbrev"] == home))
        ].copy()

        # Deduplicate by game_id, summing both teams' points
        if len(h2h) >= 2:
            game_totals = h2h.groupby("game_id")["team_pts"].sum().reset_index()
            game_totals = game_totals.sort_values("game_id", ascending=False).head(PACE_WINDOW)
            if len(game_totals) >= 3:
                combined_avg = round(game_totals["team_pts"].mean(), 1)
                pace_tag = "high" if combined_avg > 220 else "low" if combined_avg < 200 else "mid"
                result[key] = {"combined_pts_avg": combined_avg, "pace_tag": pace_tag, "source": "h2h"}
                continue

        # Fallback: sum each team's offensive avg (last PACE_WINDOW games)
        home_rows = team_log[team_log["team_abbrev"] == home].head(PACE_WINDOW)
        away_rows = team_log[team_log["team_abbrev"] == away].head(PACE_WINDOW)

        if len(home_rows) >= 3 and len(away_rows) >= 3:
            combined_avg = round(home_rows["team_pts"].mean() + away_rows["team_pts"].mean(), 1)
            pace_tag = "high" if combined_avg > 220 else "low" if combined_avg < 200 else "mid"
            result[key] = {"combined_pts_avg": combined_avg, "pace_tag": pace_tag, "source": "avg"}

    return result


# ── Teammate correlation ──────────────────────────────────────────────

def pearson_r(x: pd.Series, y: pd.Series) -> float | None:
    """Safe Pearson r, returns None if insufficient variance."""
    if len(x) < CORR_MIN_GAMES:
        return None
    if x.std() == 0 or y.std() == 0:
        return None
    try:
        r = float(np.corrcoef(x.values, y.values)[0, 1])
        return round(r, 3) if not np.isnan(r) else None
    except Exception:
        return None


def correlation_tag(r: float | None, stat_a: str, stat_b: str) -> str:
    """
    Assign a human-readable tag based on the stat pair and correlation strength.

    Key pairings:
      AST/PTS (same team): positive = feeder_target, negative = unusual
      PTS/PTS (same team): negative = scoring_rivals (zero-sum), positive = volume game
      REB/REB (same team): negative = board_rivals
      Any pair, low r:     independent
    """
    if r is None:
        return "insufficient_data"

    abs_r = abs(r)
    strong   = abs_r >= CORR_STRONG
    moderate = abs_r >= CORR_MODERATE

    if not moderate:
        return "independent"

    # AST → PTS same team: positive correlation = feeder relationship
    if set([stat_a, stat_b]) == {"AST", "PTS"}:
        return "feeder_target" if r > 0 else "independent"

    # PTS/PTS same team: negative = they trade usage
    if stat_a == "PTS" and stat_b == "PTS":
        if r < -CORR_MODERATE:
            return "scoring_rivals"
        if r > CORR_MODERATE:
            return "volume_game"  # both score in high-pace nights
        return "independent"

    # REB/REB same team: negative = splitting boards
    if stat_a == "REB" and stat_b == "REB":
        return "board_rivals" if r < -CORR_MODERATE else "independent"

    # Generic
    if strong:
        return "positively_correlated" if r > 0 else "negatively_correlated"
    return "independent"


def build_teammate_correlations(
    player_log: pd.DataFrame,
    teams_today: set[str],
    whitelist: set,
) -> dict:
    """
    For each pair of whitelisted players on the same team playing today,
    compute correlations across their shared games.

    Returns:
    {
      "Jalen Brunson": {
        "Karl-Anthony Towns": {
          "shared_games": 22,
          "correlations": {
            "AST_PTS": {"r": 0.71, "tag": "feeder_target"},
            "PTS_PTS": {"r": -0.12, "tag": "independent"},
            ...
          }
        }
      },
      ...
    }
    """
    log = player_log[player_log["team_abbrev"].str.upper().isin(teams_today)].copy()
    if whitelist:
        mask = log.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1
        )
        log = log[mask].copy()

    result: dict = {}

    # Group by team
    for team, team_grp in log.groupby("team_abbrev"):
        players = team_grp["player_name"].unique().tolist()
        if len(players) < 2:
            continue

        for p1_name, p2_name in combinations(sorted(players), 2):
            p1 = team_grp[team_grp["player_name"] == p1_name][["game_id", "pts", "reb", "ast", "tpm"]]
            p2 = team_grp[team_grp["player_name"] == p2_name][["game_id", "pts", "reb", "ast", "tpm"]]

            # Shared games only
            shared = p1.merge(p2, on="game_id", suffixes=("_a", "_b"))
            n = len(shared)

            if n < CORR_MIN_GAMES:
                tag_entry = {"shared_games": n, "correlations": {}, "note": "insufficient_data"}
            else:
                corrs = {}
                # Key pairs: AST/PTS (feeder), PTS/PTS (rivals), REB/REB (boards)
                pairs = [
                    ("AST", "PTS"),
                    ("PTS", "PTS"),
                    ("REB", "REB"),
                    ("AST", "AST"),
                    ("PTS", "REB"),
                ]
                for s_a, s_b in pairs:
                    col_a = f"{STAT_COL[s_a]}_a"
                    col_b = f"{STAT_COL[s_b]}_b"
                    if col_a not in shared.columns or col_b not in shared.columns:
                        continue
                    r = pearson_r(shared[col_a], shared[col_b])
                    tag = correlation_tag(r, s_a, s_b)
                    corrs[f"{s_a}_{s_b}"] = {"r": r, "tag": tag}

                tag_entry = {"shared_games": n, "correlations": corrs}

            # Store bidirectionally
            result.setdefault(p1_name, {})[p2_name] = tag_entry
            result.setdefault(p2_name, {})[p1_name] = tag_entry

    return result


# ── Per-player stats computation ──────────────────────────────────────

def compute_tier_hit_rates(games: pd.DataFrame, stat: str) -> dict:
    col = STAT_COL[stat]
    tiers = TIERS[stat]
    n = len(games)
    if n == 0:
        return {}
    return {str(t): round((games[col] >= t).sum() / n, 3) for t in tiers}


def compute_volatility(game_log: list, stat: str, tier: int, window: int = 20) -> dict:
    """
    Compute rolling volatility of binary hit outcomes at the given tier.
    Uses last `window` games where the player was not DNP.
    Returns volatility label and raw sigma.

    game_log must be sorted oldest→newest so that played[-window:] yields
    the most recent `window` games.
    """
    import statistics as _statistics

    played = [g for g in game_log if not g.get("dnp") and g.get(stat) is not None]
    recent = played[-window:]

    if len(recent) < 5:
        return {"label": "insufficient_data", "sigma": None, "n": len(recent)}

    outcomes = [1 if g[stat] >= tier else 0 for g in recent]

    if len(outcomes) < 2:
        return {"label": "insufficient_data", "sigma": None, "n": len(outcomes)}

    sigma = _statistics.stdev(outcomes)

    if sigma < 0.3:
        label = "consistent"
    elif sigma <= 0.4:
        label = "moderate"
    else:
        label = "volatile"

    return {"label": label, "sigma": round(sigma, 3), "n": len(outcomes)}


def compute_shooting_regression(grp: pd.DataFrame) -> dict:
    """
    Compute L5 vs L20 FG% and 3P% delta for a player.

    grp is sorted newest→oldest (descending game_date), so head(N) = most recent N games.
    Requires fgm/fga/fg3m/fg3a columns; returns empty-flag dict if columns are absent or
    insufficient data exists.

    Returns:
      flag         — "hot" | "cold" | "neutral" | "insufficient_data"
      fg_flag      — same enum, FG-specific
      fg_delta_pct — (l5_fg_pct - l20_fg_pct) / l20_fg_pct; positive = shooting hotter
      l20_fg_pct   — season FG% baseline (last 20 games with shots)
      l5_fg_pct    — recent FG% (last 5 games with shots)
      l20_3p_pct   — season 3P% baseline (last 20 games with 3PA > 0)
      l5_3p_pct    — recent 3P% (last 5 games with 3PA > 0)
      3p_delta_pct — relative delta for 3P%; None when insufficient
      games_with_shots — count of non-DNP games with fga > 0
    """
    # Ensure numeric types for shooting columns
    g = grp.copy()
    for col in ("fgm", "fga", "fg3m", "fg3a"):
        if col in g.columns:
            g[col] = pd.to_numeric(g[col], errors="coerce")
        else:
            g[col] = float("nan")

    # Exclude DNP rows
    dnp_mask = pd.to_numeric(g["dnp"], errors="coerce").fillna(0) == 1
    valid = g[~dnp_mask & (g["fga"].fillna(0) > 0)].copy()
    n_valid = len(valid)

    if n_valid < 10:
        return {"flag": "insufficient_data", "games_with_shots": n_valid}

    # grp is newest→oldest; head(N) = most recent N rows
    l20_rows = valid.head(20)
    l5_rows  = valid.head(5)

    if len(l5_rows) < 3:
        return {"flag": "insufficient_data", "games_with_shots": n_valid}

    # FG%
    l20_fga = l20_rows["fga"].sum()
    l5_fga  = l5_rows["fga"].sum()
    l20_fg_pct = (l20_rows["fgm"].sum() / l20_fga) if l20_fga > 0 else None
    l5_fg_pct  = (l5_rows["fgm"].sum()  / l5_fga)  if l5_fga  > 0 else None

    fg_delta_pct: float | None = None
    fg_flag: str = "neutral"
    if l20_fg_pct and l5_fg_pct is not None and l20_fg_pct > 0:
        fg_delta_pct = (l5_fg_pct - l20_fg_pct) / l20_fg_pct
        if fg_delta_pct >= 0.08:
            fg_flag = "hot"
        elif fg_delta_pct <= -0.08:
            fg_flag = "cold"

    # 3P% — only on games where player attempted 3s
    valid_3p   = g[~dnp_mask & (g["fg3a"].fillna(0) > 0)].copy()
    l20_3p = valid_3p.head(20)
    l5_3p  = valid_3p.head(5)
    l20_3pa = l20_3p["fg3a"].sum() if len(l20_3p) >= 5 else 0
    l5_3pa  = l5_3p["fg3a"].sum()  if len(l5_3p)  >= 3 else 0
    l20_3p_pct = (l20_3p["fg3m"].sum() / l20_3pa) if l20_3pa > 0 else None
    l5_3p_pct  = (l5_3p["fg3m"].sum()  / l5_3pa)  if l5_3pa  > 0 else None

    _3p_delta_pct: float | None = None
    if l20_3p_pct and l5_3p_pct is not None and l20_3p_pct > 0:
        _3p_delta_pct = (l5_3p_pct - l20_3p_pct) / l20_3p_pct

    return {
        "flag":          fg_flag,
        "fg_flag":       fg_flag,
        "fg_delta_pct":  round(fg_delta_pct, 3) if fg_delta_pct is not None else None,
        "l20_fg_pct":    round(l20_fg_pct,   3) if l20_fg_pct  is not None else None,
        "l5_fg_pct":     round(l5_fg_pct,    3) if l5_fg_pct   is not None else None,
        "l20_3p_pct":    round(l20_3p_pct,   3) if l20_3p_pct  is not None else None,
        "l5_3p_pct":     round(l5_3p_pct,    3) if l5_3p_pct   is not None else None,
        "3p_delta_pct":  round(_3p_delta_pct, 3) if _3p_delta_pct is not None else None,
        "games_with_shots": n_valid,
    }


def compute_ft_safety_margin(grp: pd.DataFrame) -> dict:
    """
    Compute FG% safety margin per PTS tier.

    Answers: "How much FG% buffer does this player have before their field-goal
    shooting alone would cause them to miss their PTS tier?"

    Breakeven FG% = (tier - season_ftm_avg - season_3pm_avg) / (season_fga_avg * 2)
    Safety margin  = season_fg_pct - breakeven_fg_pct

    Fragility classification (backtest-validated, 537 instances):
      margin >= 0.10 → "safe"        (hit rate 72.6%; baseline noise — no adjustment)
      margin >= 0.00 → "borderline"  (hit rate 56.1% / 57.6% at <0.10; PREDICTIVE → drop one tier)
      margin <  0.00 → "fragile"     (player needs above-baseline FG% — rare for whitelisted players)

    ft_dominant: when (season_ftm_avg + season_3pm_avg * 1) >= tier, the player
      can reach the tier from FTs and 3s alone — FG% becomes irrelevant for that tier.

    grp is sorted newest→oldest (descending game_date); head(20) = most recent 20 games.
    Requires fgm, fga, ftm, fta, tpm columns.

    Returns:
      {
        "n_games": int,
        "season_fg_pct":  float,
        "season_ftm_avg": float,
        "season_fta_avg": float,
        "season_fga_avg": float,
        "season_3pm_avg": float,
        "tiers": {
          "20": {"flag": "safe"|"borderline"|"fragile"|"ft_dominant",
                 "breakeven_fg_pct": float|None, "margin": float|None},
          "25": {...},
          "30": {...},
        }
      }
    or {"flag": "insufficient_data"} if fewer than 10 valid games.
    """
    g = grp.copy()

    # Ensure numeric types
    for col in ("fgm", "fga", "ftm", "fta", "tpm"):
        if col in g.columns:
            g[col] = pd.to_numeric(g[col], errors="coerce")
        else:
            g[col] = float("nan")

    # Exclude DNP rows; require at least one shot attempted (fga > 0)
    dnp_mask = pd.to_numeric(g["dnp"], errors="coerce").fillna(0) == 1
    valid = g[~dnp_mask & (g["fga"].fillna(0) > 0)].head(20)
    n_valid = len(valid)

    if n_valid < 10:
        return {"flag": "insufficient_data"}

    # Season averages (aggregated totals, not mean of per-game rates)
    total_fgm = valid["fgm"].sum()
    total_fga = valid["fga"].sum()
    season_fg_pct  = float(total_fgm / total_fga) if total_fga > 0 else None
    season_fga_avg = float(total_fga / n_valid)

    # FTM/FTA averages — include non-shooting games (DNPs already excluded above,
    # but a player can have 0 FTA in a game; that is a real data point, not missing)
    ft_valid = g[~dnp_mask].head(20)  # same L20 window, all active games
    season_ftm_avg = float(ft_valid["ftm"].fillna(0).mean())
    season_fta_avg = float(ft_valid["fta"].fillna(0).mean())

    # 3PM average — from same L20 active games
    season_3pm_avg = float(ft_valid["tpm"].fillna(0).mean())

    if season_fg_pct is None or season_fga_avg == 0:
        return {"flag": "insufficient_data"}

    # Per-tier fragility
    tier_results: dict = {}
    for tier in PTS_TIERS:
        pts_from_ft_and_3s = season_ftm_avg + season_3pm_avg

        if pts_from_ft_and_3s >= tier:
            # Player can reach the tier from FTs + 3s alone — FG% is irrelevant
            tier_results[str(tier)] = {
                "flag":             "ft_dominant",
                "breakeven_fg_pct": None,
                "margin":           None,
            }
            continue

        # Breakeven: how many FGM needed from remaining pts / 2 pts per FGM
        pts_needed_from_fg = tier - pts_from_ft_and_3s
        breakeven_fg_pct   = pts_needed_from_fg / (season_fga_avg * 2)

        if breakeven_fg_pct > 1.0:
            # Physically impossible — player would need FG% > 100%
            tier_results[str(tier)] = {
                "flag":             "impossible",
                "breakeven_fg_pct": round(breakeven_fg_pct, 3),
                "margin":           round(season_fg_pct - breakeven_fg_pct, 3),
            }
            continue

        margin = season_fg_pct - breakeven_fg_pct
        if margin >= 0.10:
            flag = "safe"
        elif margin >= 0.00:
            flag = "borderline"
        else:
            flag = "fragile"

        tier_results[str(tier)] = {
            "flag":             flag,
            "breakeven_fg_pct": round(breakeven_fg_pct, 3),
            "margin":           round(margin, 3),
        }

    return {
        "n_games":        n_valid,
        "season_fg_pct":  round(season_fg_pct,  3),
        "season_ftm_avg": round(season_ftm_avg, 2),
        "season_fta_avg": round(season_fta_avg, 2),
        "season_fga_avg": round(season_fga_avg, 2),
        "season_3pm_avg": round(season_3pm_avg, 2),
        "tiers":          tier_results,
    }


def compute_matchup_tier_hit_rates(
    all_games: pd.DataFrame,
    opp_defense: dict,
    stat: str,
) -> dict:
    """
    Split a player's full historical game log by today's opponent defensive ratings
    (soft / mid / tough) and compute tier hit rates within each bucket.

    Uses current opp_defense ratings as a proxy for season-long classification —
    a valid approximation within a single season.

    Returns: {str(tier): {"soft": {"hit_rate": float, "n": int}, ...}}
    Only includes rating buckets with >= MIN_MATCHUP_GAMES games.
    """
    col = STAT_COL[stat]
    tiers = TIERS[stat]

    if all_games.empty:
        return {}

    def get_rating(opp: str):
        entry = opp_defense.get(opp.upper(), {})
        return (entry.get(stat) or {}).get("rating")

    games = all_games.copy()
    games["_opp_rating"] = games["opp_abbrev"].str.upper().apply(get_rating)

    result: dict = {}
    for t in tiers:
        bucket: dict = {}
        for rating in ("soft", "mid", "tough"):
            subset = games[games["_opp_rating"] == rating]
            n = len(subset)
            if n >= MIN_MATCHUP_GAMES:
                hit_rate = round(float((subset[col] >= t).sum()) / n, 3)
                bucket[rating] = {"hit_rate": hit_rate, "n": n}
        if bucket:
            result[str(t)] = bucket
    return result


def compute_spread_split_hit_rates(
    player_games: pd.DataFrame,
    master_df: pd.DataFrame,
    stat: str,
) -> dict:
    """
    Split a player's historical games into competitive (spread_abs ≤ SPREAD_COMPETITIVE)
    and blowout (spread_abs > SPREAD_COMPETITIVE) buckets using nba_master.csv spreads.

    player_games: all historical games for one player (pre-filtered to this player, no DNPs).
    master_df:    nba_master.csv as a DataFrame.

    Returns:
      {
        "competitive": {"hit_rates": {str(tier): float, ...}, "n": int},
        "blowout":     {"hit_rates": {str(tier): float, ...}, "n": int},
      }
    Only includes buckets with >= MIN_SPREAD_GAMES games.
    Note: spread coverage is limited to games where ESPN collected spread data.
    """
    if player_games.empty or master_df.empty:
        return {}

    col   = STAT_COL[stat]
    tiers = TIERS[stat]

    # Normalize game_id: player_log stores "401809234.0", master stores "401809234"
    pgl = player_games.copy()
    pgl["_gid"] = pgl["game_id"].astype(str).str.split(".").str[0].str.strip()

    mdf = master_df.copy()
    mdf["_gid"] = mdf["game_id"].astype(str).str.split(".").str[0].str.strip()

    spread_cols = ["_gid", "home_spread", "away_spread"]
    avail = [c for c in spread_cols if c in mdf.columns]
    merged = pgl.merge(mdf[avail], on="_gid", how="inner")

    if merged.empty:
        return {}

    # Get this player's signed spread for each game using their home/away designation
    def _team_spread(row) -> float | None:
        ha = str(row.get("home_away", "")).upper()
        try:
            val = row["home_spread"] if ha == "H" else row["away_spread"]
            f = float(val)
            return None if pd.isna(f) else f
        except (TypeError, ValueError):
            return None

    merged["_spread"] = merged.apply(_team_spread, axis=1)
    merged = merged[merged["_spread"].notna()].copy()

    if merged.empty:
        return {}

    merged["_spread_abs"] = merged["_spread"].abs()
    merged["_bucket"] = merged["_spread_abs"].apply(
        lambda x: "competitive" if x <= SPREAD_COMPETITIVE else "blowout"
    )

    result: dict = {}
    for bucket in ("competitive", "blowout"):
        subset = merged[merged["_bucket"] == bucket]
        n = len(subset)
        if n < MIN_SPREAD_GAMES:
            continue
        rates = {str(t): round(float((subset[col] >= t).sum()) / n, 3) for t in tiers}
        result[bucket] = {"hit_rates": rates, "n": n}

    return result


def compute_b2b_hit_rates(
    player_games: pd.DataFrame,
    b2b_game_ids: dict,
    team: str,
    stat: str,
) -> dict | None:
    """
    Compute tier hit rates specifically on back-to-back second-night games
    for this player.

    Returns {"hit_rates": {str(tier): float}, "n": int} when sample ≥ B2B_MIN_GAMES.
    Returns None when sample is too small — caller should apply one-tier-down fallback.
    """
    team_b2bs = b2b_game_ids.get(team.upper(), set())
    if not team_b2bs or player_games.empty:
        return None

    pgl = player_games.copy()
    pgl["_gid"] = pgl["game_id"].astype(str).str.split(".").str[0].str.strip()

    b2b_games = pgl[pgl["_gid"].isin(team_b2bs)]
    n = len(b2b_games)
    if n < B2B_MIN_GAMES:
        return None

    col   = STAT_COL[stat]
    tiers = TIERS[stat]
    hit_rates = {str(t): round(float((b2b_games[col] >= t).sum()) / n, 3) for t in tiers}
    return {"hit_rates": hit_rates, "n": n}


def compute_rest_context(team_abbrev: str, master_df: pd.DataFrame) -> dict:
    """
    Compute rest and schedule-density context for a team relative to TODAY.

    Looks at all games before today to determine:
      - rest_days:      int — days since the team's last game
                        (0 = back-to-back, 1 = one day rest, etc.)
      - games_last_7:   int — games played in the 7 days before today
      - dense_schedule: bool — True if REST_DENSE_THRESHOLD+ games in REST_DENSE_DAYS days

    Returns: {"rest_days": int | None, "games_last_7": int, "dense_schedule": bool}
    """
    if master_df.empty:
        return {"rest_days": None, "games_last_7": 0, "dense_schedule": False}

    team = team_abbrev.upper().strip()
    df   = master_df.copy()
    df["_date"] = pd.to_datetime(df["game_date"], errors="coerce")

    today_ts = pd.Timestamp(TODAY)

    # All past games for this team
    team_games = df[
        (
            (df["home_team_abbrev"].astype(str).str.upper().str.strip() == team) |
            (df["away_team_abbrev"].astype(str).str.upper().str.strip() == team)
        ) &
        (df["_date"] < today_ts)
    ].sort_values("_date", ascending=False)

    if team_games.empty:
        return {"rest_days": None, "games_last_7": 0, "dense_schedule": False}

    last_date  = team_games.iloc[0]["_date"]
    rest_days  = int((today_ts - last_date).days)

    cutoff_7   = today_ts - pd.Timedelta(days=7)
    cutoff_den = today_ts - pd.Timedelta(days=REST_DENSE_DAYS)

    games_last_7   = int((team_games["_date"] >= cutoff_7).sum())
    games_last_den = int((team_games["_date"] >= cutoff_den).sum())
    dense          = games_last_den >= REST_DENSE_THRESHOLD

    return {
        "rest_days":      rest_days,
        "games_last_7":   games_last_7,
        "dense_schedule": dense,
    }


def best_tier(hit_rates: dict) -> dict | None:
    tiers_sorted = sorted(hit_rates.keys(), key=lambda x: int(x), reverse=True)
    for t in tiers_sorted:
        if hit_rates[t] >= CONFIDENCE_FLOOR:
            return {"tier": int(t), "hit_rate": hit_rates[t]}
    return None


def compute_trend(games_10: pd.DataFrame, games_5: pd.DataFrame, stat: str) -> str:
    col = STAT_COL[stat]
    if games_10.empty or games_5.empty:
        return "stable"
    avg_10 = games_10[col].mean()
    avg_5  = games_5[col].mean()
    if avg_10 == 0:
        return "stable"
    delta = (avg_5 - avg_10) / avg_10
    if delta > TREND_THRESHOLD:
        return "up"
    if delta < -TREND_THRESHOLD:
        return "down"
    return "stable"


def compute_minutes_trend(games_10: pd.DataFrame, games_5: pd.DataFrame) -> str:
    if games_10.empty or games_5.empty:
        return "stable"
    avg_10 = games_10["minutes_raw"].mean()
    avg_5  = games_5["minutes_raw"].mean()
    delta = avg_5 - avg_10
    if delta > MINUTES_THRESHOLD:
        return "increasing"
    if delta < -MINUTES_THRESHOLD:
        return "decreasing"
    return "stable"


def compute_minutes_floor(grp: pd.DataFrame, window: int = 10) -> dict | None:
    """
    Compute the 10th-percentile minutes floor over the last `window` non-DNP games.

    Returns:
        {
            "floor_minutes": float,   # 10th-percentile of L10 minutes_raw
            "avg_minutes":   float,   # mean of same window (for context)
            "n":             int,     # games used
        }
    Returns None if fewer than MIN_GAMES valid rows.

    grp is expected to be sorted newest→oldest (same convention as all other per-player
    compute functions). DNP rows are filtered defensively even though load_player_log()
    already removes them.
    """
    # Defensive DNP exclusion
    if "dnp" in grp.columns:
        grp = grp[grp["dnp"].astype(str) != "1"]

    # L{window} window (most recent games first → head gives most recent)
    window_rows = grp.head(window)

    if len(window_rows) < MIN_GAMES:
        return None

    # Coerce minutes_raw defensively; drop rows where coercion yields NaN
    mins = pd.to_numeric(window_rows["minutes_raw"], errors="coerce").dropna()

    if len(mins) < MIN_GAMES:
        return None

    floor_minutes = round(float(np.percentile(mins, 10)), 1)
    avg_minutes   = round(float(mins.mean()), 1)
    n             = len(mins)

    return {
        "floor_minutes": floor_minutes,
        "avg_minutes":   avg_minutes,
        "n":             n,
    }


def build_bounce_back_profiles(
    player_log: pd.DataFrame,
    whitelist: set,
) -> dict:
    """
    Compute per-player bounce-back profiles at each player's best qualifying tier
    (≥70% full-season hit rate, strict >) across their full season history.

    Returns:
        {player_name: {"PTS": {...or None}, "REB": {...or None}, "AST": {...or None}, "3PM": {...or None}}}

    Fields per stat (or None if < 5 post-miss observations):
        post_miss_hit_rate  — fraction of games player hit tier immediately after a miss
        lift                — post_miss_hit_rate / overall_hit_rate
        consecutive_miss_rate — fraction of misses followed by another miss
        max_consecutive_misses — longest consecutive miss streak
        iron_floor          — True when max_consecutive_misses == 1 AND n_misses >= 5
        n_misses            — total misses in full history at this tier
    """
    MIN_POST_MISS    = 5
    NEAR_MISS_MARGIN = 2   # miss by ≤ this many units = near-miss
    MIN_MISS_N       = 5   # min misses required to compute severity split

    # Filter to whitelisted players using full log (not today-filtered)
    if whitelist:
        mask = player_log.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1,
        )
        log = player_log[mask].copy()
    else:
        log = player_log.copy()

    log = log[log["dnp"] != "1"].copy()
    log["game_date"] = pd.to_datetime(log["game_date"])

    profiles: dict = {}

    for player_name, grp in log.groupby("player_name"):
        grp = grp.sort_values("game_date", ascending=True)
        player_profile: dict = {}

        for stat, col in STAT_COL.items():
            tiers = TIERS[stat]
            values = grp[col].to_numpy(dtype=float)
            n_total = len(values)

            if n_total < 10:
                player_profile[stat] = None
                continue

            # Find best qualifying tier using full-season hit rate (>=)
            best_t = None
            overall_hr = 0.0
            for t in sorted(tiers, reverse=True):
                hr = float((values >= t).mean())
                if hr >= CONFIDENCE_FLOOR:
                    best_t = t
                    overall_hr = hr
                    break

            if best_t is None:
                player_profile[stat] = None
                continue

            # Build hit sequence at best_t
            hits = (values >= best_t).astype(int).tolist()
            n = len(hits)

            # Shortfall per game: 0 on hits, positive amount below tier on misses
            shortfalls = [max(0.0, float(best_t) - float(v)) for v in values]

            # Compute bounce-back metrics from the hit sequence
            post_miss_hits = []
            consec_misses = 0
            max_streak = 0
            cur_streak = 0

            for i in range(n):
                if hits[i] == 0:  # miss
                    cur_streak += 1
                    if i + 1 < n:
                        post_miss_hits.append(hits[i + 1])
                else:
                    if cur_streak > max_streak:
                        max_streak = cur_streak
                    cur_streak = 0

            # Close out final streak
            if cur_streak > max_streak:
                max_streak = cur_streak

            n_misses = hits.count(0)
            n_post = len(post_miss_hits)

            if n_post < MIN_POST_MISS:
                player_profile[stat] = None
                continue

            post_miss_hr = float(sum(post_miss_hits) / n_post)
            consec_miss_rate = 1.0 - post_miss_hr  # fraction of misses followed by another miss
            lift = round(post_miss_hr / overall_hr, 3) if overall_hr > 0 else 1.0
            iron_floor = (max_streak == 1) and (n_misses >= 5)

            # Miss anatomy — severity classification
            miss_shortfalls = [shortfalls[i] for i in range(n) if hits[i] == 0]
            n_misses_total  = len(miss_shortfalls)
            near_miss_rate  = None
            blowup_rate     = None
            typical_miss    = None
            if n_misses_total >= MIN_MISS_N:
                near_count     = sum(1 for s in miss_shortfalls if s <= NEAR_MISS_MARGIN)
                blow_count     = sum(1 for s in miss_shortfalls if s > NEAR_MISS_MARGIN)
                near_miss_rate = round(near_count / n_misses_total, 3)
                blowup_rate    = round(blow_count / n_misses_total, 3)
                typical_miss   = round(float(np.median(miss_shortfalls)), 1)

            player_profile[stat] = {
                "tier": best_t,
                "post_miss_hit_rate": round(post_miss_hr, 3),
                "lift": lift,
                "consecutive_miss_rate": round(consec_miss_rate, 3),
                "max_consecutive_misses": max_streak,
                "iron_floor": iron_floor,
                "n_misses": n_misses,
                "near_miss_rate": near_miss_rate,  # fraction of misses within 2 units of tier; None if < 5 misses
                "blowup_rate":    blowup_rate,      # fraction of misses 3+ units below tier; None if < 5 misses
                "typical_miss":   typical_miss,     # median shortfall on miss games (units); None if < 5 misses
            }

        profiles[player_name] = player_profile

    return profiles


def compute_teammate_absence_splits(
    player_log: pd.DataFrame,
    player_name: str,
    team: str,
    whitelist: set,
) -> dict | None:
    """
    For the given player, identify their top-PPG whitelisted teammate on the same team
    and compute the player's per-stat averages and tier hit rates in games where that
    teammate was absent (DNP or not in log for that game_id).
    Returns a dict with teammate name, their avg PPG, sample size, and the player's
    raw_avgs + tier_hit_rates in the absence window.
    Returns None if fewer than 3 qualifying absence games exist, or no teammates found.
    """
    MIN_ABSENCE_GAMES = 3
    team_upper = team.upper()
    # Get all whitelisted teammates on same team (excluding the player themselves)
    team_log = player_log[player_log["team_abbrev"].str.upper() == team_upper].copy()
    if whitelist:
        mask = team_log.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1
        )
        team_log = team_log[mask].copy()
    teammates = [p for p in team_log["player_name"].unique() if p != player_name]
    if not teammates:
        return None
    # Identify top-PPG teammate by season average (non-DNP games)
    top_teammate = None
    top_avg_pts = 0.0
    for tm in teammates:
        tm_games = team_log[
            (team_log["player_name"] == tm) &
            (pd.to_numeric(team_log["dnp"], errors="coerce").fillna(0) != 1)
        ]
        if len(tm_games) < 5:
            continue
        avg_pts = float(tm_games["pts"].mean())
        if avg_pts > top_avg_pts:
            top_avg_pts = avg_pts
            top_teammate = tm
    if top_teammate is None:
        return None
    # Find all game_ids where top_teammate was absent:
    # absent = DNP row exists OR no row at all for that game_id
    all_team_game_ids = set(
        player_log[player_log["team_abbrev"].str.upper() == team_upper]["game_id"].unique()
    )
    tm_active_game_ids = set(
        team_log[
            (team_log["player_name"] == top_teammate) &
            (pd.to_numeric(team_log["dnp"], errors="coerce").fillna(0) != 1)
        ]["game_id"].unique()
    )
    absent_game_ids = all_team_game_ids - tm_active_game_ids
    if len(absent_game_ids) < MIN_ABSENCE_GAMES:
        return None
    # Get the player's active (non-DNP) games in those absent game_ids
    player_full_log = player_log[player_log["player_name"] == player_name].copy()
    dnp_mask = pd.to_numeric(player_full_log["dnp"], errors="coerce").fillna(0) == 1
    player_active = player_full_log[~dnp_mask]
    absence_games = player_active[player_active["game_id"].isin(absent_game_ids)].copy()
    n = len(absence_games)
    if n < MIN_ABSENCE_GAMES:
        return None
    # Compute raw averages and tier hit rates for each stat
    raw_avgs = {}
    tier_hit_rates = {}
    for stat in ("PTS", "REB", "AST", "3PM"):
        col = STAT_COL[stat]
        if col not in absence_games.columns:
            continue
        valid = absence_games[absence_games[col].notna()]
        if len(valid) == 0:
            continue
        raw_avgs[stat] = round(float(valid[col].mean()), 1)
        tier_hit_rates[stat] = {
            str(t): round(float((valid[col] >= t).sum() / len(valid)), 3)
            for t in TIERS[stat]
        }
    return {
        "teammate_name": top_teammate,
        "teammate_avg_pts": round(top_avg_pts, 1),
        "n_games": n,
        "raw_avgs": raw_avgs,
        "tier_hit_rates": tier_hit_rates,
    }


def build_player_stats(
    player_log: pd.DataFrame,
    b2b_teams: set[str],
    opp_defense: dict,
    game_pace: dict,
    todays_games: list[dict],
    teammate_correlations: dict,
    whitelist: set,
    game_spreads: dict | None = None,
    master_df: pd.DataFrame | None = None,
    b2b_game_ids: dict | None = None,
    positional_dvp_data: dict | None = None,
    position_map: dict | None = None,
    team_momentum: dict | None = None,
    opp_defense_recency: dict | None = None,
) -> dict:

    # Bounce-back profiles use full player_log (all season history, not today-filtered)
    bounce_back_profiles = build_bounce_back_profiles(player_log, whitelist)

    team_to_opp = {}
    team_to_game_key = {}
    for g in todays_games:
        h = g["home"].upper()
        a = g["away"].upper()
        team_to_opp[h] = a
        team_to_opp[a] = h
        key = f"{a}_{h}"
        team_to_game_key[h] = key
        team_to_game_key[a] = key

    teams_today = set(team_to_opp.keys())

    # Pre-compute rest context per team (avoid recomputing for every player)
    _rest_cache: dict = {}
    if master_df is not None and not master_df.empty:
        for _team in teams_today:
            _rest_cache[_team] = compute_rest_context(_team, master_df)

    log = player_log[player_log["team_abbrev"].str.upper().isin(teams_today)].copy()
    if whitelist:
        mask = log.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1
        )
        log = log[mask].copy()

    stats_out = {}

    for player_name, grp in log.groupby("player_name"):
        grp = grp.sort_values("game_date", ascending=False)
        games_10 = grp.head(PLAYER_WINDOW)
        games_5  = grp.head(TREND_SHORT_WINDOW)

        if len(games_10) < MIN_GAMES:
            continue

        team     = games_10["team_abbrev"].iloc[0].upper()
        opponent = team_to_opp.get(team, "")

        tier_hit_rates = {stat: compute_tier_hit_rates(games_10, stat) for stat in TIERS}
        best_tiers     = {stat: best_tier(tier_hit_rates[stat]) for stat in TIERS}

        # Volatility scores at each stat's best qualifying tier
        player_games = grp.sort_values("game_date", ascending=True).to_dict("records")
        volatility = {}
        for _stat in ["pts", "reb", "ast", "tpm"]:
            _stat_key = _stat.upper() if _stat != "tpm" else "3PM"
            _best = best_tiers.get(_stat_key)
            if _best is not None:
                volatility[_stat_key] = compute_volatility(player_games, _stat, _best["tier"], window=20)

        # Shooting efficiency regression (L5 vs L20 FG%/3P% delta)
        # grp is already newest→oldest; compute_shooting_regression uses .head(N)
        shooting_regression = compute_shooting_regression(grp)

        # FG% safety margin per PTS tier — requires ftm/fta columns (post-backfill)
        ft_safety_margin = compute_ft_safety_margin(grp)

        trend          = {stat: compute_trend(games_10, games_5, stat) for stat in TIERS}
        # Matchup-specific split: full history on current team, split by opp defensive rating
        matchup_tier_hit_rates = {
            stat: compute_matchup_tier_hit_rates(grp, opp_defense, stat)
            for stat in TIERS
        }

        home_games = grp[grp["home_away"] == "H"].head(PLAYER_WINDOW)
        away_games = grp[grp["home_away"] == "A"].head(PLAYER_WINDOW)
        home_away_splits = {}
        for stat in TIERS:
            h_rates = compute_tier_hit_rates(home_games, stat) if len(home_games) >= 3 else {}
            a_rates = compute_tier_hit_rates(away_games, stat) if len(away_games) >= 3 else {}
            home_away_splits[stat] = {
                "H": best_tier(h_rates) if h_rates else None,
                "A": best_tier(a_rates) if a_rates else None,
            }

        avg_minutes_last5 = round(games_5["minutes_raw"].mean(), 1)
        minutes_trend     = compute_minutes_trend(games_10, games_5)
        minutes_floor     = compute_minutes_floor(grp)
        raw_avgs          = {stat: round(games_10[STAT_COL[stat]].mean(), 1) for stat in TIERS}
        # B2B flag: True only if BOTH the team played yesterday AND this player
        # appeared in yesterday's game. A player who sat out (DNP, load management,
        # injury rest) is rested regardless of team schedule — do not apply B2B
        # hit rates or the B2B annotation to a player who did not play last night.
        _yesterday_str = (TODAY - dt.timedelta(days=1)).strftime("%Y-%m-%d")
        _player_played_yesterday = (
            not grp.empty
            and str(grp["game_date"].iloc[0]) == _yesterday_str
        )
        on_b2b = (team in b2b_teams) and _player_played_yesterday
        opp_context       = opp_defense.get(opponent) if opponent else None

        # Positional DvP — position-specific opponent defense rating
        player_position = (position_map or {}).get(player_name.lower(), "")
        _pos_dvp  = ((positional_dvp_data or {}).get(opponent) or {}).get(player_position, {}) if opponent else {}
        _opp_ctx  = opp_context or {}
        positional_dvp_entry = {
            "position": player_position,
            "pts_rating": _pos_dvp.get("pts_rating", (_opp_ctx.get("PTS") or {}).get("rating", "mid")),
            "reb_rating": _pos_dvp.get("reb_rating", (_opp_ctx.get("REB") or {}).get("rating", "mid")),
            "ast_rating": _pos_dvp.get("ast_rating", (_opp_ctx.get("AST") or {}).get("rating", "mid")),
            "tpm_rating": _pos_dvp.get("tpm_rating", (_opp_ctx.get("3PM") or {}).get("rating", "mid")),
            "n": _pos_dvp.get("n", 0),
            "source": "positional" if _pos_dvp.get("n", 0) >= 10 else "team_fallback",
        }

        # Game pace for this player's matchup
        game_key   = team_to_game_key.get(team, "")
        pace_ctx   = game_pace.get(game_key)

        # Teammate correlations for this player
        teammate_corr = teammate_correlations.get(player_name, {})

        # Spread context for today's game
        spread_ctx   = (game_spreads or {}).get(team, {})
        today_spread = spread_ctx.get("spread")        # signed (neg = favored)
        spread_abs   = spread_ctx.get("spread_abs")
        blowout_risk = spread_ctx.get("blowout_risk", False)

        # Team momentum context for this player's team and opponent
        momentum_team = (team_momentum or {}).get(team)
        momentum_opp  = (team_momentum or {}).get(opponent) if opponent else None
        team_momentum_ctx = {
            "team":     momentum_team,
            "opponent": momentum_opp,
        } if (momentum_team or momentum_opp) else None

        # Defensive recency flag for today's opponent (L5 vs L15 divergence)
        def_recency = (opp_defense_recency or {}).get(opponent) if opponent else None

        # Historical spread split hit rates (competitive vs blowout games)
        if master_df is not None and not master_df.empty:
            spread_split_hit_rates = {
                stat: compute_spread_split_hit_rates(grp, master_df, stat)
                for stat in TIERS
            }
        else:
            spread_split_hit_rates = {}

        # B2B quantified hit rates — per stat, using historical B2B second-night games
        if b2b_game_ids is not None:
            b2b_hit_rates = {
                stat: compute_b2b_hit_rates(grp, b2b_game_ids, team, stat)
                for stat in TIERS
            }
        else:
            b2b_hit_rates = {stat: None for stat in TIERS}

        # Rest / schedule density context for today
        rest_ctx      = _rest_cache.get(team, {})
        rest_days     = rest_ctx.get("rest_days")
        games_last_7  = rest_ctx.get("games_last_7", 0)
        dense_schedule = rest_ctx.get("dense_schedule", False)

        # Bounce-back profile for this player (full-season, pre-computed)
        bb_raw = bounce_back_profiles.get(player_name, {})
        bounce_back = {stat: bb_raw.get(stat) for stat in TIERS}

        # Teammate absence splits — performance baseline when top-PPG teammate is out
        key_teammate_absent = compute_teammate_absence_splits(
            player_log, player_name, team, whitelist
        )

        stats_out[player_name] = {
            "team": team,
            "whitelisted_teammates": sorted(teammate_corr.keys()),
            "opponent": opponent,
            "games_available": len(games_10),
            "last_updated": TODAY_STR,
            "on_back_to_back": on_b2b,
            "rest_days": rest_days,
            "games_last_7": games_last_7,
            "dense_schedule": dense_schedule,
            "b2b_hit_rates": b2b_hit_rates,
            "today_spread": today_spread,
            "spread_abs": spread_abs,
            "blowout_risk": blowout_risk,
            "tier_hit_rates": tier_hit_rates,
            "matchup_tier_hit_rates": matchup_tier_hit_rates,
            "spread_split_hit_rates": spread_split_hit_rates,
            "best_tiers": best_tiers,
            "trend": trend,
            "home_away_splits": home_away_splits,
            "minutes_trend": minutes_trend,
            "avg_minutes_last5": avg_minutes_last5,
            "minutes_floor":     minutes_floor,
            "raw_avgs": raw_avgs,
            "opp_defense": opp_context,
            "game_pace": pace_ctx,
            "teammate_correlations": teammate_corr,
            "bounce_back": bounce_back,
            "key_teammate_absent": key_teammate_absent,
            "volatility": volatility,
            "shooting_regression": shooting_regression,
            "ft_safety_margin": ft_safety_margin,
            "team_momentum":    team_momentum_ctx,
            "def_recency":      def_recency,
            "positional_dvp": positional_dvp_entry,
        }

    return stats_out


def build_player_profiles(
    player_log: pd.DataFrame,
    player_stats: dict,
    whitelist: set,
) -> dict:
    """
    Build per-player narrative profile blocks for players with a qualifying PTS tier.
    Computed fresh daily. Returns {player_name: str} where the value is a pre-rendered
    multi-line text block ready for direct injection into the analyst prompt.

    Only profiles players present in player_stats with a non-null best_tiers["PTS"].
    player_log should be the raw log (pre-DNP-filter); this function applies its own
    DNP exclusion internally.
    Minimum 10 non-DNP games required — players below this are silently skipped.
    """
    profiles: dict = {}

    # Coerce numeric columns (raw log may have string values)
    numeric_cols = ["pts", "tpm", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "minutes"]
    log = player_log.copy()
    for col in numeric_cols:
        if col in log.columns:
            log[col] = pd.to_numeric(log[col], errors="coerce")

    for player_name, s in player_stats.items():
        best_tiers_map = s.get("best_tiers") or {}
        best_pts = best_tiers_map.get("PTS")
        if not best_pts:
            continue  # No qualifying PTS tier — skip

        best_pts_tier    = int(best_pts["tier"])
        overall_hit_rate = float(best_pts.get("hit_rate", 0.0))

        # Filter to this player's games
        pmask = log["player_name"].str.lower() == player_name.lower()
        plog  = log[pmask].copy()

        # Apply DNP exclusion
        dnp_col  = pd.to_numeric(plog["dnp"].astype(str), errors="coerce").fillna(0)
        plog     = plog[dnp_col != 1].copy()

        # Sort descending by date (most recent first)
        plog = plog.sort_values("game_date", ascending=False).reset_index(drop=True)

        if len(plog) < 10:
            continue  # Minimum data requirement

        # L20 window (most recent 20 non-DNP games)
        l20     = plog.head(20).copy()
        n_games = len(l20)

        # ── 1. PTS hit sequence ──────────────────────────────────────
        hits_arr  = (l20["pts"].fillna(0) >= best_pts_tier).astype(int).tolist()
        hit_count = sum(hits_arr)

        # Current streak (index 0 = most recent game)
        current_val = hits_arr[0]
        current_len = 0
        for h in hits_arr:
            if h == current_val:
                current_len += 1
            else:
                break
        streak_word    = "hit" if current_val == 1 else "miss"
        streak_summary = f"current: {current_len}-{streak_word} streak"

        # Longest hit and miss streaks in L20
        max_hit_streak = max_miss_streak = 0
        cur_h = cur_m = 0
        for h in hits_arr:
            if h == 1:
                cur_h += 1; cur_m = 0
                max_hit_streak  = max(max_hit_streak,  cur_h)
            else:
                cur_m += 1; cur_h = 0
                max_miss_streak = max(max_miss_streak, cur_m)

        pct          = int(round(hit_count / n_games * 100))
        sequence_line = (
            f"  Hit sequence: {hit_count}/{n_games} ({pct}%) | "
            f"{streak_summary} | "
            f"longest hit-streak: {max_hit_streak} | "
            f"longest miss-streak: {max_miss_streak}"
        )

        # ── 2. Scoring channel breakdown ─────────────────────────────
        has_fg_data  = ("fgm" in log.columns and not l20["fgm"].isna().all())
        has_ft_data  = (
            "ftm" in log.columns and "fta" in log.columns
            and not l20["ftm"].isna().all()
        )

        if not has_fg_data:
            channel_line = "  Scoring channels: [shooting data unavailable]"
        else:
            shooting_games = l20[l20["fga"].fillna(0) > 0].copy()
            if len(shooting_games) < 5:
                channel_line = "  Scoring channels: [insufficient shooting data]"
            else:
                shooting_games["fg_pts"]  = shooting_games["fgm"].fillna(0) * 2
                shooting_games["tpm_pts"] = shooting_games["tpm"].fillna(0) * 1
                shooting_games["ft_pts"]  = (
                    shooting_games["ftm"].fillna(0) * 1 if has_ft_data else 0.0
                )
                shooting_games["total_pts"] = (
                    shooting_games["fg_pts"]
                    + shooting_games["tpm_pts"]
                    + shooting_games["ft_pts"]
                )
                valid = shooting_games[shooting_games["total_pts"] > 0]
                if len(valid) < 3:
                    channel_line = "  Scoring channels: [insufficient data]"
                else:
                    avg_fg  = float(valid["fg_pts"].mean())
                    avg_tpm = float(valid["tpm_pts"].mean())
                    avg_ft  = float(valid["ft_pts"].mean()) if has_ft_data else 0.0
                    avg_tot = float(valid["total_pts"].mean())

                    fg_pct  = int(round(avg_fg  / avg_tot * 100))
                    tpm_pct = int(round(avg_tpm / avg_tot * 100))
                    ft_pct  = int(round(avg_ft  / avg_tot * 100)) if has_ft_data else 0

                    labels: list[str] = []
                    if has_ft_data and (avg_ft / avg_tot) >= 0.25:
                        labels.append("FT-contributor")
                    if (avg_fg / avg_tot) >= 0.68:
                        labels.append("FG-dependent")
                    if (avg_tpm / avg_tot) >= 0.18:
                        labels.append("3PM-contributor")
                    if not labels:
                        labels.append("balanced")

                    label_str = " ".join(f"[{lb}]" for lb in labels)

                    if has_ft_data:
                        channel_line = (
                            f"  Scoring channels: FG={fg_pct}% FT={ft_pct}% 3PM={tpm_pct}%"
                            f"  {label_str}"
                        )
                    else:
                        channel_line = (
                            f"  Scoring channels: FG={fg_pct}% 3PM={tpm_pct}%"
                            f"  {label_str}  [FT data unavailable]"
                        )

        # ── 3. B2B sensitivity ───────────────────────────────────────
        b2b_data = (s.get("b2b_hit_rates") or {}).get("PTS")
        if b2b_data and b2b_data.get("n", 0) >= 5:
            b2b_hr_raw = b2b_data["hit_rates"].get(str(best_pts_tier))
            b2b_n      = b2b_data["n"]
            if b2b_hr_raw is not None:
                b2b_hr   = float(b2b_hr_raw)
                pp_delta = b2b_hr - overall_hit_rate
                b2b_hits = int(round(b2b_hr * b2b_n))
                b2b_pct  = int(round(b2b_hr * 100))
                if pp_delta <= -0.10:
                    b2b_label = "[B2B-sensitive]"
                elif pp_delta >= 0.00:
                    b2b_label = "[B2B-resilient]"
                else:
                    b2b_label = "[B2B-mixed]"
                b2b_line = (
                    f"  B2B: {b2b_hits}/{b2b_n} ({b2b_pct}%) on B2B second nights"
                    f"  ({pp_delta:+.0%} vs baseline {int(round(overall_hit_rate*100))}%)"
                    f"  {b2b_label}"
                )
            else:
                b2b_line = "  B2B: insufficient sample (<5 games)"
        else:
            b2b_line = "  B2B: insufficient sample (<5 games)"

        # ── 4. Blowout context ───────────────────────────────────────
        blowout_line: str | None = None
        spread_splits = (s.get("spread_split_hit_rates") or {}).get("PTS") or {}
        comp_data = spread_splits.get("competitive")
        blow_data = spread_splits.get("blowout")
        if comp_data and blow_data:
            comp_hr_raw = comp_data.get("hit_rates", {}).get(str(best_pts_tier))
            blow_hr_raw = blow_data.get("hit_rates", {}).get(str(best_pts_tier))
            comp_n      = comp_data.get("n", 0)
            blow_n      = blow_data.get("n", 0)
            if (
                comp_hr_raw is not None and blow_hr_raw is not None
                and comp_n >= 5 and blow_n >= 5
            ):
                comp_hr   = float(comp_hr_raw)
                blow_hr   = float(blow_hr_raw)
                pp_delta  = blow_hr - comp_hr
                comp_pct  = int(round(comp_hr * 100))
                blow_pct  = int(round(blow_hr * 100))
                comp_hits = int(round(comp_hr * comp_n))
                blow_hits = int(round(blow_hr * blow_n))
                if pp_delta <= -0.10:
                    blow_label = "[blowout-sensitive]"
                elif pp_delta >= 0.00:
                    blow_label = "[blowout-resilient]"
                else:
                    blow_label = "[blowout-mixed]"
                blowout_line = (
                    f"  Blowout context: {blow_hits}/{blow_n} ({blow_pct}%) in blowout games"
                    f" vs {comp_hits}/{comp_n} ({comp_pct}%) competitive"
                    f"  ({pp_delta:+.0%} vs competitive)"
                    f"  {blow_label}"
                )

        # ── 5. Miss anatomy (conditional — only if parallel task has landed) ──
        miss_line: str | None = None
        bb_pts       = (s.get("bounce_back") or {}).get("PTS") or {}
        near_miss_rt = bb_pts.get("near_miss_rate")
        blowup_rt    = bb_pts.get("blowup_rate")
        typical_miss = bb_pts.get("typical_miss")
        n_misses_bb  = bb_pts.get("n_misses")
        if near_miss_rt is not None and n_misses_bb:
            pct_near   = int(round(near_miss_rt * 100))
            pct_blowup = (
                int(round(blowup_rt * 100)) if blowup_rt is not None
                else 100 - pct_near
            )
            tm_str = f"{typical_miss:.1f}u" if typical_miss is not None else "n/a"
            miss_line = (
                f"  Miss anatomy ({n_misses_bb} misses): "
                f"{pct_near}% near-miss (≤2u) / "
                f"{pct_blowup}% blowup (>2u), "
                f"typical shortfall={tm_str}"
            )

        # ── 6. Minutes floor (conditional — only if parallel task has landed) ──
        minutes_line: str | None = None
        mf = s.get("minutes_floor")
        if mf is not None:
            floor_min = mf.get("floor_minutes")
            avg_min   = mf.get("avg_minutes")
            if floor_min is not None and avg_min is not None and avg_min > 0:
                ratio = floor_min / avg_min
                minutes_line = (
                    f"  Minutes floor (L10): floor={floor_min:.1f}min"
                    f" avg={avg_min:.1f}min"
                    f" (ratio={ratio:.2f})"
                )

        # ── Assemble narrative ───────────────────────────────────────
        header = (
            f"{player_name} — Scoring Portrait"
            f" (L{n_games} games, best PTS tier: T{best_pts_tier}):"
        )
        parts = [header, sequence_line, channel_line, b2b_line]
        if blowout_line:
            parts.append(blowout_line)
        if miss_line:
            parts.append(miss_line)
        if minutes_line:
            parts.append(minutes_line)

        profiles[player_name] = "\n".join(parts)

    return profiles


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print(f"[quant] Running for {TODAY_STR}")

    player_log = load_player_log()
    print(f"[quant] Loaded {len(player_log)} player game log rows")

    team_log = load_team_log()
    print(f"[quant] Loaded {len(team_log)} team game log rows")

    whitelist = load_whitelist()
    print(f"[quant] Whitelist: {len(whitelist)} active player-team pairs")

    todays_games = load_todays_games()
    print(f"[quant] Today's games: {len(todays_games)}")

    if not todays_games:
        print("[quant] No games today — nothing to compute.")
        sys.exit(0)

    master_df = pd.read_csv(MASTER_CSV, dtype=str) if MASTER_CSV.exists() else pd.DataFrame()
    b2b_teams = build_b2b_teams(master_df)
    if b2b_teams:
        print(f"[quant] Back-to-back teams: {', '.join(sorted(b2b_teams))}")

    b2b_game_ids = build_b2b_game_ids(master_df)
    print(f"[quant] B2B game IDs built for {len(b2b_game_ids)} teams")

    opp_defense = build_opp_defense(team_log)
    print(f"[quant] Opponent defense computed for {len(opp_defense)} teams")

    opp_defense_recency = compute_opp_defense_recency(team_log)
    n_flagged = sum(1 for v in opp_defense_recency.values() if v is not None)
    print(f"[quant] Defensive recency computed for {len(opp_defense_recency)} teams ({n_flagged} flagged)")

    build_team_defense_narratives(team_log)  # writes team_defense_narratives.json; best-effort

    position_map = load_whitelist_positions()
    positional_dvp_data = compute_positional_dvp(player_log, position_map)
    print(f"[quant] Positional DvP computed for {len(positional_dvp_data)} teams")

    game_pace = build_game_pace(team_log, todays_games)
    print(f"[quant] Game pace computed for {len(game_pace)} matchups")

    game_spreads = build_game_spreads(todays_games)
    n_with_spread = sum(1 for v in game_spreads.values() if v.get("spread") is not None)
    print(f"[quant] Game spreads: {len(game_spreads)} teams ({n_with_spread} with spread data)")

    teams_today = set()
    for g in todays_games:
        teams_today.add(g["home"].upper())
        teams_today.add(g["away"].upper())

    team_momentum = build_team_momentum(master_df, teams_today)
    print(f"[quant] Team momentum computed for {len(team_momentum)} teams")

    teammate_correlations = build_teammate_correlations(player_log, teams_today, whitelist)
    print(f"[quant] Teammate correlations computed for {len(teammate_correlations)} players")

    player_stats = build_player_stats(
        player_log, b2b_teams, opp_defense, game_pace,
        todays_games, teammate_correlations, whitelist,
        game_spreads=game_spreads, master_df=master_df,
        b2b_game_ids=b2b_game_ids,
        positional_dvp_data=positional_dvp_data,
        position_map=position_map,
        team_momentum=team_momentum,
        opp_defense_recency=opp_defense_recency,
    )
    print(f"[quant] Built stats cards for {len(player_stats)} players")

    # Load raw player log (pre-DNP filter) for profile builder — separate from the
    # filtered load_player_log() so build_player_profiles() can apply its own exclusions.
    player_log_raw = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    player_log_raw["game_date"] = (
        pd.to_datetime(player_log_raw["game_date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
    )
    player_log_raw = player_log_raw[player_log_raw["game_date"] < TODAY_STR].copy()

    player_profiles_map = build_player_profiles(player_log_raw, player_stats, whitelist)
    for name, narrative in player_profiles_map.items():
        if name in player_stats:
            player_stats[name]["profile_narrative"] = narrative
    print(f"[quant] Built {len(player_profiles_map)} player profile narratives")

    with open(PLAYER_STATS_JSON, "w") as f:
        json.dump(player_stats, f, indent=2)

    print(f"[quant] Wrote {PLAYER_STATS_JSON}")

    # Summary
    for name, s in sorted(player_stats.items()):
        b = s["best_tiers"]
        picks = [f"{stat}≥{b[stat]['tier']}({int(b[stat]['hit_rate']*100)}%)"
                 for stat in b if b[stat]]
        b2b_flag  = " [B2B]" if s["on_back_to_back"] else ""
        rest_info = f" rest={s.get('rest_days', '?')}d" if not s["on_back_to_back"] else ""
        dense_flag = " [DENSE]" if s.get("dense_schedule") else ""
        opp       = s.get("opp_defense") or {}
        opp_pts   = opp.get("PTS", {}).get("rating", "?")
        pace      = s.get("game_pace") or {}
        pace_tag  = pace.get("pace_tag", "?")
        n_corr    = len(s.get("teammate_correlations", {}))
        print(f"  {name} ({s['team']} vs {s['opponent']}{b2b_flag}{rest_info}{dense_flag}) "
              f"opp-PTS:{opp_pts} pace:{pace_tag} corr-partners:{n_corr} | "
              f"{' '.join(picks) if picks else 'no qualifying tiers'}")


if __name__ == "__main__":
    main()
