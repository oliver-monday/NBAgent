#!/usr/bin/env python3
"""
NBAgent — Stats Builder

Runs after ingest, before Analyst. Reads player_game_log.csv,
team_game_log.csv, and nba_master.csv to produce data/player_stats.json —
a pre-computed stats card per player that replaces raw game log lines
in the Analyst prompt.

Per-player outputs:
  - Tier hit rates (last 10 games)
  - Best qualifying tier per stat (≥70% hit rate, or null)
  - Trend: up / stable / down (last 5 vs last 10 avg)
  - Home/away splits (best tier per split)
  - Minutes trend
  - Back-to-back flag for today's game
  - Opponent defensive context (last 15 games): rank + raw avg allowed
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GAME_LOG_CSV    = DATA / "player_game_log.csv"
TEAM_LOG_CSV    = DATA / "team_game_log.csv"
MASTER_CSV      = DATA / "nba_master.csv"
WHITELIST_CSV   = ROOT / "playerprops" / "player_whitelist.csv"
PLAYER_STATS_JSON = DATA / "player_stats.json"

ET = ZoneInfo("America/New_York")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ────────────────────────────────────────────────────────────
PLAYER_WINDOW       = 10   # games for tier hit rates + trend base
TREND_SHORT_WINDOW  = 5    # games for "recent" trend comparison
TREND_THRESHOLD     = 0.10 # >10% delta = up/down
MINUTES_THRESHOLD   = 3.0  # >3 min delta = increasing/decreasing
MIN_GAMES           = 5    # skip players with fewer games
OPP_WINDOW          = 15   # games for opponent defensive context
CONFIDENCE_FLOOR    = 0.70 # minimum hit rate for a "best tier" pick

# Tier definitions
PTS_TIERS  = [10, 15, 20, 25, 30]
REB_TIERS  = [2, 4, 6, 8, 10, 12]
AST_TIERS  = [2, 4, 6, 8, 10, 12]
TPM_TIERS  = [1, 2, 3, 4]

TIERS = {"PTS": PTS_TIERS, "REB": REB_TIERS, "AST": AST_TIERS, "3PM": TPM_TIERS}
STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}


# ── Loaders ───────────────────────────────────────────────────────────

def load_player_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        print("[stats_builder] ERROR: player_game_log.csv not found.")
        sys.exit(1)
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    # Exclude today and DNPs
    df = df[df["game_date"] < TODAY_STR].copy()
    df = df[df["dnp"].astype(str) != "1"].copy()
    for col in ["pts", "reb", "ast", "tpm", "minutes_raw"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("game_date", ascending=False)


def load_team_log() -> pd.DataFrame:
    if not TEAM_LOG_CSV.exists():
        print("[stats_builder] WARNING: team_game_log.csv not found — skipping opp context.")
        return pd.DataFrame()
    df = pd.read_csv(TEAM_LOG_CSV, dtype={"game_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df[df["game_date"] < TODAY_STR].copy()
    for col in ["team_pts", "team_reb", "team_ast", "team_tpm"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df.sort_values("game_date", ascending=False)


def load_todays_games() -> list[dict]:
    """Return today's games with home/away team abbrevs."""
    if not MASTER_CSV.exists():
        return []
    df = pd.read_csv(MASTER_CSV, dtype=str)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    today = df[df["game_date"] == TODAY_STR].copy()
    games = []
    for _, row in today.iterrows():
        games.append({
            "game_date": TODAY_STR,
            "home": row.get("home_team_abbrev", ""),
            "away": row.get("away_team_abbrev", ""),
        })
    return games


def load_whitelist() -> set:
    if not WHITELIST_CSV.exists():
        return set()
    try:
        df = pd.read_csv(WHITELIST_CSV, dtype=str)
        active = df[df["active"].astype(str).str.strip() == "1"]
        return set(active["player_name"].str.strip().str.lower().tolist())
    except Exception:
        return set()


# ── Back-to-back detection ─────────────────────────────────────────────

def build_b2b_teams(master_df: pd.DataFrame) -> set[str]:
    """
    Returns set of team abbrevs playing today on a back-to-back
    (i.e. they also played yesterday).
    """
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


# ── Opponent defensive context ────────────────────────────────────────

def build_opp_defense(team_log: pd.DataFrame) -> dict:
    """
    For each team, compute how much they ALLOW per game (last 15 games).
    We derive this by looking at what opponents scored against them:
    for each team's game row, the opponent's stats = what that team allowed.

    Returns:
      {
        "LAL": {
          "PTS": {"allowed_pg": 112.3, "rank": 8, "rating": "mid"},
          "REB": {...},
          "AST": {...},
          "3PM": {...}
        }, ...
      }
    """
    if team_log.empty:
        return {}

    stat_map = {
        "PTS": "team_pts",
        "REB": "team_reb",
        "AST": "team_ast",
        "3PM": "team_tpm",
    }

    # For each row, opp_abbrev scored team_pts/reb/ast/tpm *against* team_abbrev.
    # So to get what team_abbrev ALLOWS: group by team_abbrev, look at
    # what opp_abbrev scored in those rows.
    # Each row: team_abbrev played opp_abbrev. The opponent scored = allowed by team.
    # We need the mirror: for each game, get the opponent's row.
    # Simpler: join each game's two rows (same game_id) so we can see
    # what each team allowed.

    # Build allowed stats: for each game_id, team A allowed what team B scored
    # team_log has one row per team per game. So for game_id X:
    #   row1: team=LAL, opp=BOS, team_pts=110  → BOS allowed 110 from LAL
    #   row2: team=BOS, opp=LAL, team_pts=105  → LAL allowed 105 from BOS
    # So "allowed by team" = look at the OTHER team's team_pts in same game.

    tl = team_log[["game_id", "game_date", "team_abbrev", "opp_abbrev",
                    "team_pts", "team_reb", "team_ast", "team_tpm"]].copy()

    # Self-join on game_id: for each row, find the opponent's row
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

    # Pre-compute per-team allowed averages (last 15 games)
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

    # Rank teams by each stat (1 = best defense = allows fewest)
    n_teams = len(team_avgs)
    for stat in ["PTS", "REB", "AST", "3PM"]:
        sorted_teams = sorted(team_avgs.keys(),
                              key=lambda t: team_avgs[t][stat])
        for rank, team in enumerate(sorted_teams, 1):
            if team not in result:
                result[team] = {}
            avg = team_avgs[team][stat]
            if n_teams > 0:
                if rank <= max(1, round(n_teams * 0.33)):
                    rating = "tough"
                elif rank <= max(1, round(n_teams * 0.67)):
                    rating = "mid"
                else:
                    rating = "soft"
            else:
                rating = "mid"
            result[team][stat] = {
                "allowed_pg": avg,
                "rank": rank,
                "n_teams": n_teams,
                "rating": rating,
            }

    return result


# ── Per-player stats computation ──────────────────────────────────────

def compute_tier_hit_rates(games: pd.DataFrame, stat: str) -> dict:
    """Hit rate for each tier over the provided game rows."""
    col = STAT_COL[stat]
    tiers = TIERS[stat]
    n = len(games)
    if n == 0:
        return {}
    return {
        str(t): round((games[col] > t).sum() / n, 3)
        for t in tiers
    }


def best_tier(hit_rates: dict) -> dict | None:
    """
    Return the highest tier with hit_rate >= CONFIDENCE_FLOOR, or None.
    hit_rates keys are string tier values.
    """
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


def build_player_stats(
    player_log: pd.DataFrame,
    b2b_teams: set[str],
    opp_defense: dict,
    todays_games: list[dict],
    whitelist: set,
) -> dict:

    # Map each team to today's opponent
    team_to_opp = {}
    for g in todays_games:
        h = g["home"].upper()
        a = g["away"].upper()
        team_to_opp[h] = a
        team_to_opp[a] = h

    teams_today = set(team_to_opp.keys())

    # Filter log to players on teams playing today
    log = player_log[player_log["team_abbrev"].str.upper().isin(teams_today)].copy()

    if whitelist:
        log = log[log["player_name"].str.strip().str.lower().isin(whitelist)].copy()

    stats_out = {}

    for player_name, grp in log.groupby("player_name"):
        grp = grp.sort_values("game_date", ascending=False)
        games_10 = grp.head(PLAYER_WINDOW)
        games_5  = grp.head(TREND_SHORT_WINDOW)

        if len(games_10) < MIN_GAMES:
            continue

        team = games_10["team_abbrev"].iloc[0].upper()
        opponent = team_to_opp.get(team, "")

        # ── Tier hit rates ──
        tier_hit_rates = {}
        for stat in TIERS:
            tier_hit_rates[stat] = compute_tier_hit_rates(games_10, stat)

        # ── Best tiers (≥70% only) ──
        best_tiers = {}
        for stat in TIERS:
            bt = best_tier(tier_hit_rates[stat])
            best_tiers[stat] = bt  # None if nothing clears floor

        # ── Trends ──
        trend = {stat: compute_trend(games_10, games_5, stat) for stat in TIERS}

        # ── Home/away splits — best tier per split ──
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

        # ── Minutes ──
        avg_minutes_last5 = round(games_5["minutes_raw"].mean(), 1)
        minutes_trend = compute_minutes_trend(games_10, games_5)

        # ── Raw averages (for context only) ──
        raw_avgs = {
            stat: round(games_10[STAT_COL[stat]].mean(), 1)
            for stat in TIERS
        }

        # ── Back-to-back ──
        on_b2b = team in b2b_teams

        # ── Opponent defensive context ──
        opp_context = None
        if opponent and opponent in opp_defense:
            opp_context = opp_defense[opponent]

        stats_out[player_name] = {
            "team": team,
            "opponent": opponent,
            "games_available": len(games_10),
            "last_updated": TODAY_STR,
            "on_back_to_back": on_b2b,
            "tier_hit_rates": tier_hit_rates,
            "best_tiers": best_tiers,
            "trend": trend,
            "home_away_splits": home_away_splits,
            "minutes_trend": minutes_trend,
            "avg_minutes_last5": avg_minutes_last5,
            "raw_avgs": raw_avgs,
            "opp_defense": opp_context,
        }

    return stats_out


# ── Main ──────────────────────────────────────────────────────────────

def main():
    print(f"[stats_builder] Running for {TODAY_STR}")

    player_log = load_player_log()
    print(f"[stats_builder] Loaded {len(player_log)} player game log rows")

    team_log = load_team_log()
    print(f"[stats_builder] Loaded {len(team_log)} team game log rows")

    whitelist = load_whitelist()
    print(f"[stats_builder] Whitelist: {len(whitelist)} active players")

    todays_games = load_todays_games()
    print(f"[stats_builder] Today's games: {len(todays_games)}")

    if not todays_games:
        print("[stats_builder] No games today — nothing to compute.")
        sys.exit(0)

    master_df = pd.read_csv(MASTER_CSV, dtype=str) if MASTER_CSV.exists() else pd.DataFrame()
    b2b_teams = build_b2b_teams(master_df)
    if b2b_teams:
        print(f"[stats_builder] Back-to-back teams: {', '.join(sorted(b2b_teams))}")

    opp_defense = build_opp_defense(team_log)
    print(f"[stats_builder] Opponent defense computed for {len(opp_defense)} teams")

    player_stats = build_player_stats(
        player_log, b2b_teams, opp_defense, todays_games, whitelist
    )
    print(f"[stats_builder] Built stats cards for {len(player_stats)} players")

    with open(PLAYER_STATS_JSON, "w") as f:
        json.dump(player_stats, f, indent=2)

    print(f"[stats_builder] Wrote {PLAYER_STATS_JSON}")

    # Print a quick summary
    for name, s in sorted(player_stats.items()):
        b = s["best_tiers"]
        picks = [f"{stat}≥{b[stat]['tier']}({int(b[stat]['hit_rate']*100)}%)"
                 for stat in b if b[stat]]
        b2b_flag = " [B2B]" if s["on_back_to_back"] else ""
        opp = s.get("opp_defense") or {}
        opp_pts = opp.get("PTS", {}).get("rating", "?")
        print(f"  {name} ({s['team']} vs {s['opponent']}{b2b_flag}) "
              f"opp-PTS:{opp_pts} | {' '.join(picks) if picks else 'no qualifying tiers'}")


if __name__ == "__main__":
    main()
