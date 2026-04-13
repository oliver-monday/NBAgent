#!/usr/bin/env python3
"""
NBAgent — Injury & Availability Profiles

Computes per-player injury risk and availability metrics from historical game log
data, overlaid with current injury report status. Writes data/injury_profiles.json.

Runs daily in analyst.yml after quant.py. Can also be run standalone.

Output status:
  OUT          — Currently listed as OUT in injuries_today.json
  DOUBTFUL     — Currently listed as DOUBTFUL
  QUESTIONABLE — Currently listed as QUESTIONABLE
  ACTIVE       — Not on injury report or no injury data available

Risk classification is NOT automated — the curated PLAYOFF INJURY LANDSCAPE
in nba_season_context.md provides the qualitative intelligence layer. This
agent provides the quantitative data foundation only.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Paths ─────────────────────────────────────────────────────────────
ROOT           = Path(__file__).resolve().parent.parent
DATA           = ROOT / "data"
WHITELIST_CSV  = ROOT / "playerprops" / "player_whitelist.csv"
GAME_LOG_CSV   = DATA / "player_game_log.csv"
MASTER_CSV     = DATA / "nba_master.csv"
INJURIES_JSON  = DATA / "injuries_today.json"
OUTPUT_JSON    = DATA / "injury_profiles.json"

# ── Config ────────────────────────────────────────────────────────────
PT = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(PT).date()

ESPN_TO_STANDARD = {
    "GS": "GSW", "SA": "SAS", "NY": "NYK", "UTAH": "UTA",
    "NO": "NOP", "WSH": "WAS",
}

# No automated risk classification — data provider only.
# See context/nba_season_context.md PLAYOFF INJURY LANDSCAPE for curated risk assessment.
MIN_GAMES_FOR_PROFILE = 5      # need at least this many games for meaningful stats


def _norm_team(abbr: str) -> str:
    """Normalize ESPN short team codes to standard abbreviation."""
    up = abbr.strip().upper()
    return ESPN_TO_STANDARD.get(up, up)


def _norm_name(name: str) -> str:
    """Normalize player name: hyphens→space, apostrophes/periods removed, lowercase."""
    s = name.lower().strip()
    s = s.replace("-", " ")
    for ch in ("'", "\u2019", "."):
        s = s.replace(ch, "")
    return " ".join(s.split())


# ── Data loaders ──────────────────────────────────────────────────────

def load_whitelist() -> list[dict]:
    """Load active whitelisted players. Returns list of {name, name_norm, team}."""
    players = []
    if not WHITELIST_CSV.exists():
        print("[injury_profiles] player_whitelist.csv not found.")
        return players
    with open(WHITELIST_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("active", "0")).strip() != "1":
                continue
            name = (row.get("player_name") or "").strip()
            team = (row.get("team_abbr") or "").strip().upper()
            if name and team:
                players.append({
                    "name": name,
                    "name_norm": _norm_name(name),
                    "team": team,
                })
    return players


def load_game_log() -> dict[str, list[dict]]:
    """
    Load player_game_log.csv. Returns {name_norm: [rows]} sorted newest→oldest.
    Each row includes parsed game_date as a date object.
    """
    log: dict[str, list[dict]] = defaultdict(list)
    if not GAME_LOG_CSV.exists():
        print("[injury_profiles] player_game_log.csv not found.")
        return log
    with open(GAME_LOG_CSV, newline="") as f:
        for row in csv.DictReader(f):
            name = _norm_name(row.get("player_name", ""))
            if not name:
                continue
            try:
                gd = dt.date.fromisoformat(row["game_date"])
            except (KeyError, ValueError):
                continue
            row["_date"] = gd
            row["_team_std"] = _norm_team(row.get("team_abbrev", ""))
            row["_is_dnp"] = str(row.get("dnp", "0")).strip() == "1"
            try:
                row["_minutes"] = float(row.get("minutes", 0) or 0)
            except (ValueError, TypeError):
                row["_minutes"] = 0.0
            log[name].append(row)
    # Sort each player newest→oldest
    for name in log:
        log[name].sort(key=lambda r: r["_date"], reverse=True)
    return log


def load_team_schedules() -> dict[str, list[dt.date]]:
    """
    Load nba_master.csv. Returns {team_std: [game_dates]} sorted newest→oldest.
    Each team appears in both home and away entries.
    """
    schedule: dict[str, set[dt.date]] = defaultdict(set)
    if not MASTER_CSV.exists():
        print("[injury_profiles] nba_master.csv not found.")
        return {}
    with open(MASTER_CSV, newline="") as f:
        for row in csv.DictReader(f):
            try:
                gd = dt.date.fromisoformat(row["game_date"])
            except (KeyError, ValueError):
                continue
            home = _norm_team(row.get("home_team_abbrev", ""))
            away = _norm_team(row.get("away_team_abbrev", ""))
            if home:
                schedule[home].add(gd)
            if away:
                schedule[away].add(gd)
    # Convert to sorted lists (newest→oldest)
    return {t: sorted(dates, reverse=True) for t, dates in schedule.items()}


def load_current_injuries() -> dict[str, dict]:
    """
    Load injuries_today.json. Returns {name_norm: {status, details, team}}.
    If a player appears under multiple teams, most severe status wins.
    """
    SEVERITY = {"OUT": 4, "DOUBTFUL": 3, "QUESTIONABLE": 2}
    injuries: dict[str, dict] = {}
    if not INJURIES_JSON.exists():
        return injuries
    try:
        with open(INJURIES_JSON) as f:
            data = json.load(f)
        for team, entries in data.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                name = _norm_name(entry.get("name", ""))
                status = (entry.get("status") or "").strip().upper()
                details = (entry.get("details") or entry.get("reason") or "").strip()
                if not name or not status:
                    continue
                existing = injuries.get(name)
                if existing is None or SEVERITY.get(status, 0) > SEVERITY.get(existing["status"], 0):
                    injuries[name] = {
                        "status": status,
                        "details": details,
                        "team": team,
                    }
    except Exception as e:
        print(f"[injury_profiles] WARNING: could not load injuries_today.json: {e}")
    return injuries


# ── Computation functions ─────────────────────────────────────────────

def compute_availability(
    player_games: list[dict], team_dates: list[dt.date], team: str
) -> dict | None:
    """Compute availability metrics for a single player."""
    if not team_dates:
        return None

    # Filter player games to only those for this team
    played_dates = {
        r["_date"] for r in player_games
        if r["_team_std"] == team and not r["_is_dnp"]
    }
    # Also count DNP dates (player was on team but didn't play)
    dnp_dates = {
        r["_date"] for r in player_games
        if r["_team_std"] == team and r["_is_dnp"]
    }

    team_games = len(team_dates)
    games_played = len(played_dates)
    games_dnp = len(dnp_dates)
    total_absences = team_games - games_played  # includes DNPs + untracked absences

    pct = round(100.0 * games_played / team_games, 1) if team_games > 0 else 0.0

    return {
        "games_played": games_played,
        "team_games": team_games,
        "pct": pct,
        "total_absences": total_absences,
        "dnp_count": games_dnp,
    }


def compute_absence_profile(
    player_games: list[dict], team_dates: list[dt.date], team: str
) -> dict | None:
    """Compute absence streaks and recency for a single player."""
    if not team_dates:
        return None

    played_dates = {
        r["_date"] for r in player_games
        if r["_team_std"] == team and not r["_is_dnp"]
    }

    # Team dates oldest→newest for streak computation
    dates_asc = sorted(team_dates)

    # Find all absence dates
    absence_dates = [d for d in dates_asc if d not in played_dates]

    # Longest absence streak
    longest_streak = 0
    current_streak = 0
    streak_count = 0
    for d in dates_asc:
        if d not in played_dates:
            current_streak += 1
        else:
            if current_streak > 0:
                streak_count += 1
                longest_streak = max(longest_streak, current_streak)
            current_streak = 0
    if current_streak > 0:
        streak_count += 1
        longest_streak = max(longest_streak, current_streak)

    # Absences in last 14 and 30 days
    cutoff_14 = TODAY - dt.timedelta(days=14)
    cutoff_30 = TODAY - dt.timedelta(days=30)
    team_dates_14 = [d for d in dates_asc if d >= cutoff_14]
    team_dates_30 = [d for d in dates_asc if d >= cutoff_30]
    played_14 = {d for d in played_dates if d >= cutoff_14}
    played_30 = {d for d in played_dates if d >= cutoff_30}
    absences_14d = len(team_dates_14) - len(played_14)
    absences_30d = len(team_dates_30) - len(played_30)

    # Days since last game played
    if played_dates:
        last_played = max(played_dates)
        days_since_last = (TODAY - last_played).days
        last_game_date = last_played.isoformat()
    else:
        days_since_last = None
        last_game_date = None

    return {
        "longest_streak": longest_streak,
        "streak_count": streak_count,
        "absences_last_14d": absences_14d,
        "absences_last_30d": absences_30d,
        "days_since_last_game": days_since_last,
        "last_game_date": last_game_date,
    }


def compute_minutes_profile(player_games: list[dict], team: str) -> dict | None:
    """Compute minutes averages and trend. player_games is newest→oldest."""
    # Filter to non-DNP games for this team
    games = [r for r in player_games if r["_team_std"] == team and not r["_is_dnp"]]

    if len(games) < MIN_GAMES_FOR_PROFILE:
        return None

    # Games are newest→oldest, so [:N] = most recent N
    l5 = [g["_minutes"] for g in games[:5]]
    l20 = [g["_minutes"] for g in games[:20]]
    season = [g["_minutes"] for g in games]

    l5_avg = round(sum(l5) / len(l5), 1) if l5 else None
    l20_avg = round(sum(l20) / len(l20), 1) if l20 else None
    season_avg = round(sum(season) / len(season), 1)

    # Trend classification
    trend = "stable"
    if l5_avg is not None and l20_avg is not None and l20_avg > 0:
        delta_pct = (l5_avg - l20_avg) / l20_avg * 100
        if delta_pct <= -15.0:
            trend = "declining"
        elif delta_pct >= 15.0:
            trend = "increasing"

    return {
        "season_avg": season_avg,
        "l5_avg": l5_avg,
        "l20_avg": l20_avg,
        "trend": trend,
    }


def compute_b2b_profile(
    player_games: list[dict], team_dates: list[dt.date], team: str
) -> dict | None:
    """Compute back-to-back pattern. B2B = team has games on consecutive dates."""
    if not team_dates:
        return None

    dates_asc = sorted(team_dates)
    played_dates = {
        r["_date"] for r in player_games
        if r["_team_std"] == team and not r["_is_dnp"]
    }

    # Identify B2B second-night dates
    b2b_dates = []
    for i in range(1, len(dates_asc)):
        if (dates_asc[i] - dates_asc[i - 1]).days == 1:
            b2b_dates.append(dates_asc[i])

    if not b2b_dates:
        return {"b2b_total": 0, "b2b_played": 0, "b2b_sat": 0, "sit_rate_pct": None}

    b2b_played = sum(1 for d in b2b_dates if d in played_dates)
    b2b_sat = len(b2b_dates) - b2b_played
    sit_rate = round(100.0 * b2b_sat / len(b2b_dates), 1)

    return {
        "b2b_total": len(b2b_dates),
        "b2b_played": b2b_played,
        "b2b_sat": b2b_sat,
        "sit_rate_pct": sit_rate,
    }


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[injury_profiles] Running for {TODAY}")

    whitelist = load_whitelist()
    if not whitelist:
        print("[injury_profiles] No active players — exiting.")
        return

    game_log = load_game_log()
    schedules = load_team_schedules()
    injuries = load_current_injuries()

    # Determine game_log_through date (latest game date in the log)
    all_dates = []
    for rows in game_log.values():
        for r in rows:
            all_dates.append(r["_date"])
    game_log_through = max(all_dates).isoformat() if all_dates else None

    print(f"[injury_profiles] {len(whitelist)} active players, game log through {game_log_through}")

    players_out: dict[str, dict] = {}
    status_counts = {"OUT": 0, "DOUBTFUL": 0, "QUESTIONABLE": 0, "ACTIVE": 0}

    for wp in whitelist:
        name = wp["name"]
        name_norm = wp["name_norm"]
        team = wp["team"]

        player_games = game_log.get(name_norm, [])
        team_dates = schedules.get(team, [])

        availability = compute_availability(player_games, team_dates, team)
        absence_profile = compute_absence_profile(player_games, team_dates, team)
        minutes_profile = compute_minutes_profile(player_games, team)
        b2b_profile = compute_b2b_profile(player_games, team_dates, team)

        injury = injuries.get(name_norm)

        # Derive current status from injury overlay (no automated risk classification)
        if injury and injury.get("status"):
            current_status = injury["status"]  # OUT, DOUBTFUL, QUESTIONABLE
        else:
            current_status = "ACTIVE"
        status_counts[current_status] = status_counts.get(current_status, 0) + 1

        entry = {
            "team": team,
            "current_status": current_status,
            "availability": availability,
            "absence_profile": absence_profile,
            "minutes_profile": minutes_profile,
            "b2b_profile": b2b_profile,
            "current_injury": {
                "status": injury["status"] if injury else None,
                "details": injury["details"] if injury else None,
            } if injury else None,
        }

        players_out[name] = entry

        # Log players with injury report status
        if current_status != "ACTIVE":
            inj_str = f" [{injury['status']}: {injury['details']}]" if injury else ""
            print(f"  {current_status}: {name} ({team}){inj_str}")

    # ── Write output ──────────────────────────────────────────────────
    output = {
        "generated_at": dt.datetime.now(PT).isoformat(),
        "game_log_through": game_log_through,
        "total_players": len(players_out),
        "status_summary": status_counts,
        "players": players_out,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(
        f"[injury_profiles] Saved injury_profiles.json"
        f" (OUT={status_counts.get('OUT', 0)}, DOUBTFUL={status_counts.get('DOUBTFUL', 0)},"
        f" QUESTIONABLE={status_counts.get('QUESTIONABLE', 0)}, ACTIVE={status_counts.get('ACTIVE', 0)})"
    )


if __name__ == "__main__":
    main()
