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
PLAYER_STATS_JSON = DATA / "player_stats.json"

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
REB_TIERS = [2, 4, 6, 8, 10, 12]
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
    MIN_POST_MISS = 5

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

            player_profile[stat] = {
                "tier": best_t,
                "post_miss_hit_rate": round(post_miss_hr, 3),
                "lift": lift,
                "consecutive_miss_rate": round(consec_miss_rate, 3),
                "max_consecutive_misses": max_streak,
                "iron_floor": iron_floor,
                "n_misses": n_misses,
            }

        profiles[player_name] = player_profile

    return profiles


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
        raw_avgs          = {stat: round(games_10[STAT_COL[stat]].mean(), 1) for stat in TIERS}
        on_b2b            = team in b2b_teams
        opp_context       = opp_defense.get(opponent) if opponent else None

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

        stats_out[player_name] = {
            "team": team,
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
            "raw_avgs": raw_avgs,
            "opp_defense": opp_context,
            "game_pace": pace_ctx,
            "teammate_correlations": teammate_corr,
            "bounce_back": bounce_back,
            "volatility": volatility,
        }

    return stats_out


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

    game_pace = build_game_pace(team_log, todays_games)
    print(f"[quant] Game pace computed for {len(game_pace)} matchups")

    game_spreads = build_game_spreads(todays_games)
    n_with_spread = sum(1 for v in game_spreads.values() if v.get("spread") is not None)
    print(f"[quant] Game spreads: {len(game_spreads)} teams ({n_with_spread} with spread data)")

    teams_today = set()
    for g in todays_games:
        teams_today.add(g["home"].upper())
        teams_today.add(g["away"].upper())

    teammate_correlations = build_teammate_correlations(player_log, teams_today, whitelist)
    print(f"[quant] Teammate correlations computed for {len(teammate_correlations)} players")

    player_stats = build_player_stats(
        player_log, b2b_teams, opp_defense, game_pace,
        todays_games, teammate_correlations, whitelist,
        game_spreads=game_spreads, master_df=master_df,
        b2b_game_ids=b2b_game_ids,
    )
    print(f"[quant] Built stats cards for {len(player_stats)} players")

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
