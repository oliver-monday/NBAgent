#!/usr/bin/env python3
"""
NBAgent — Playoff Matchup Agent

Generates per-series context for the Analyst: series record, game-by-game results,
per-player series stats, and season H2H stats (always shown alongside series data).

Pure Python — no LLM call. Runs after quant.py, before analyst.py.

REQUIRES: data/playoff_bracket.json (created manually by Oliver when bracket is set).
If that file does not exist, this agent exits immediately with no output — safe to
keep in the workflow year-round.

Writes: data/playoff_matchup.json (consumed by analyst.py via load_series_context()).

data/playoff_bracket.json format:
{
  "season": "2025-26",
  "round": 1,
  "playoff_start_date": "2026-04-18",  // first day of R1 games
  "series": [
    {
      "series_id": "W1",
      "conference": "West",
      "home_team": "OKC",   // higher seed — home court advantage
      "away_team": "MEM",
      "best_of": 7
    }
  ]
}
All team abbreviations must match nba_master.csv and player_game_log.csv values.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Paths ─────────────────────────────────────────────────────────────
ROOT              = Path(__file__).resolve().parent.parent
DATA              = ROOT / "data"
BRACKET_JSON      = DATA / "playoff_bracket.json"
MATCHUP_JSON      = DATA / "playoff_matchup.json"
MASTER_CSV        = DATA / "nba_master.csv"
GAME_LOG_CSV      = DATA / "player_game_log.csv"
WHITELIST_CSV     = ROOT / "playerprops" / "player_whitelist.csv"

# ── Time ──────────────────────────────────────────────────────────────
ET        = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(ET).date().strftime("%Y-%m-%d")

# ── Tier thresholds (mirrors quant.py and analyst.py) ─────────────────
TIER_THRESHOLDS: dict[str, list[int]] = {
    "PTS": [10, 15, 20, 25, 30],
    "REB": [4, 6, 8, 10, 12],
    "AST": [2, 4, 6, 8, 10, 12],
    "TPM": [1, 2, 3, 4],
}

# Stat column names in player_game_log.csv
STAT_COLS: dict[str, str] = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "TPM": "tpm",
}

# Team abbreviation normalisation
_ABBR_NORM: dict[str, str] = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP",
    "NY": "NYK", "UTAH": "UTA", "WSH": "WAS",
}


def _norm(abbr: str) -> str:
    a = str(abbr).upper().strip()
    return _ABBR_NORM.get(a, a)


# ── Data loaders ──────────────────────────────────────────────────────

def load_bracket() -> dict | None:
    """Load playoff_bracket.json. Returns None if file absent."""
    if not BRACKET_JSON.exists():
        print("[playoff_matchup] data/playoff_bracket.json not found — regular season mode, exiting.")
        return None
    try:
        with open(BRACKET_JSON) as f:
            return json.load(f)
    except Exception as e:
        print(f"[playoff_matchup] ERROR reading playoff_bracket.json: {e}")
        return None


def load_whitelist() -> dict[str, str]:
    """Return {player_name_lower: team_abbr_upper} for active whitelisted players."""
    result: dict[str, str] = {}
    if not WHITELIST_CSV.exists():
        return result
    try:
        with open(WHITELIST_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("active", "0")).strip() != "1":
                    continue
                name = (row.get("player_name") or "").strip()
                team = _norm((row.get("team_abbr") or "").strip())
                if name and team:
                    result[name.lower()] = team
    except Exception as e:
        print(f"[playoff_matchup] WARNING: could not load whitelist: {e}")
    return result


def load_today_teams() -> set[str]:
    """Return set of normalised team abbreviations playing today."""
    teams: set[str] = set()
    if not MASTER_CSV.exists():
        return teams
    try:
        with open(MASTER_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("game_date") or "")[:10] != TODAY_STR:
                    continue
                for col in ("home_team_abbrev", "away_team_abbrev"):
                    abbr = _norm((row.get(col) or "").strip())
                    if abbr:
                        teams.add(abbr)
    except Exception as e:
        print(f"[playoff_matchup] WARNING: could not load today's teams: {e}")
    return teams


def load_today_host(home_team: str, away_team: str) -> str | None:
    """
    For today's slate, find the game between home_team and away_team and
    return the canonical abbreviation of the team hosting tonight.

    Returns None when the matchup is not on today's slate (i.e.
    game_today=False) or when nba_master.csv is unavailable.

    The returned host is whichever team is in nba_master's
    `home_team_abbrev` column for the matching row — the canonical
    source of truth for per-game venue, not the bracket-seeding
    `home_team` field on the playoff_bracket.json series object
    (which reflects which team has the higher seed, not which team
    hosts a specific game).
    """
    if not MASTER_CSV.exists():
        return None
    try:
        with open(MASTER_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("game_date") or "")[:10] != TODAY_STR:
                    continue
                h = _norm((row.get("home_team_abbrev") or "").strip())
                a = _norm((row.get("away_team_abbrev") or "").strip())
                if {h, a} == {home_team, away_team}:
                    return h
    except Exception as e:
        print(f"[playoff_matchup] WARNING: could not resolve today's host for "
              f"{home_team}/{away_team}: {e}")
    return None


def load_series_game_results(
    home_team: str,
    away_team: str,
    playoff_start_date: str,
) -> list[dict]:
    """
    Scan nba_master.csv for completed games between home_team and away_team
    on or after playoff_start_date. Returns game results in date order.

    Returns: [{"date": str, "home_abbrev": str, "away_abbrev": str,
               "home_score": int, "away_score": int, "winner": str}, ...]
    """
    games: list[dict] = []
    if not MASTER_CSV.exists():
        return games
    try:
        with open(MASTER_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                date = (row.get("game_date") or "")[:10]
                if date < playoff_start_date:
                    continue
                h = _norm((row.get("home_team_abbrev") or "").strip())
                a = _norm((row.get("away_team_abbrev") or "").strip())
                # Match either orientation (bracket home/away may not match game home/away
                # due to how the CSV stores home/away per game)
                if not ({h, a} == {home_team, away_team}):
                    continue
                try:
                    hs = int(float(row.get("home_score") or 0))
                    as_ = int(float(row.get("away_score") or 0))
                except (ValueError, TypeError):
                    continue
                if hs == 0 and as_ == 0:
                    continue  # game not yet played
                winner = h if hs > as_ else a
                games.append({
                    "date": date,
                    "home_abbrev": h,
                    "away_abbrev": a,
                    "home_score": hs,
                    "away_score": as_,
                    "winner": winner,
                })
    except Exception as e:
        print(f"[playoff_matchup] WARNING: error reading series game results: {e}")
    games.sort(key=lambda g: g["date"])
    return games


def _compute_avgs_and_hits(rows: list[dict]) -> dict:
    """
    Given a list of player_game_log rows (non-DNP), compute:
    - per-stat averages (pts, reb, ast, tpm, minutes)
    - per-stat tier hit counts: {stat: {T20: [hits, games], T25: [hits, games], ...}}
      Only includes tiers where at least 1 hit occurred OR the player's avg is within
      striking distance (avg >= tier - 3).
    """
    if not rows:
        return {}

    n = len(rows)
    avgs: dict[str, float] = {}
    tier_hits: dict[str, dict[str, list[int]]] = {}

    for stat_key, col in STAT_COLS.items():
        vals: list[float] = []
        for r in rows:
            try:
                v = float(r.get(col) or 0)
                vals.append(v)
            except (ValueError, TypeError):
                vals.append(0.0)
        avg = sum(vals) / n if n > 0 else 0.0
        avgs[stat_key.lower()] = round(avg, 1)

        stat_tiers: dict[str, list[int]] = {}
        for thresh in TIER_THRESHOLDS[stat_key]:
            hits = sum(1 for v in vals if v >= thresh)
            tier_label = f"T{thresh}"
            # Include tier if any hit occurred, or average is within reach
            if hits > 0 or avg >= thresh - 3:
                stat_tiers[tier_label] = [hits, n]
        if stat_tiers:
            tier_hits[stat_key] = stat_tiers

    # Minutes
    min_vals: list[float] = []
    for r in rows:
        try:
            m = float(r.get("minutes") or 0)
            if m > 0:
                min_vals.append(m)
        except (ValueError, TypeError):
            pass
    avgs["minutes"] = round(sum(min_vals) / len(min_vals), 1) if min_vals else 0.0

    return {"n": n, "avgs": avgs, "tier_hits": tier_hits}


def load_player_stats_for_matchup(
    player_name_lower: str,
    player_team: str,
    opp_team: str,
    series_dates: set[str],
    playoff_start_date: str,
) -> dict:
    """
    For a given player, compute:
    1. series_stats: stats from completed playoff series games (dates in series_dates)
    2. season_h2h: stats from regular season games vs opp_team (before playoff_start_date)
       with home/away split within those H2H games

    Returns: {
      "series_stats": {n, avgs, tier_hits} or None if 0 series games,
      "season_h2h": {
        "all": {n, avgs, tier_hits},
        "home": {n, avgs, tier_hits},   # games where player's team was home
        "away": {n, avgs, tier_hits},   # games where player's team was away
      } or None if 0 H2H games
    }
    Never crashes — returns {"series_stats": None, "season_h2h": None} on any error.
    """
    result: dict = {"series_stats": None, "season_h2h": None}
    if not GAME_LOG_CSV.exists():
        return result

    series_rows: list[dict] = []
    h2h_rows_home: list[dict] = []
    h2h_rows_away: list[dict] = []
    h2h_rows_all: list[dict] = []

    try:
        with open(GAME_LOG_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Exclude DNPs
                if str(row.get("dnp") or "0").strip() == "1":
                    continue
                name_in_log = (row.get("player_name") or "").strip().lower()
                if name_in_log != player_name_lower:
                    continue
                team_in_log = _norm((row.get("team_abbrev") or "").strip())
                if team_in_log != player_team:
                    continue
                opp_in_log = _norm((row.get("opp_abbrev") or "").strip())
                date = (row.get("game_date") or "")[:10]

                # Series game: date in series_dates AND vs this opponent
                if date in series_dates and opp_in_log == opp_team:
                    series_rows.append(row)

                # Season H2H: vs same opponent, before playoffs started
                elif opp_in_log == opp_team and date < playoff_start_date:
                    h2h_rows_all.append(row)
                    ha = (row.get("home_away") or "").strip().upper()
                    if ha == "H":
                        h2h_rows_home.append(row)
                    elif ha == "A":
                        h2h_rows_away.append(row)

    except Exception as e:
        print(f"[playoff_matchup] WARNING: error reading game log for {player_name_lower}: {e}")
        return result

    if series_rows:
        result["series_stats"] = _compute_avgs_and_hits(series_rows)

    if h2h_rows_all:
        h2h: dict = {"all": _compute_avgs_and_hits(h2h_rows_all)}
        if h2h_rows_home:
            h2h["home"] = _compute_avgs_and_hits(h2h_rows_home)
        if h2h_rows_away:
            h2h["away"] = _compute_avgs_and_hits(h2h_rows_away)
        result["season_h2h"] = h2h

    return result


def compute_series_state(home_wins: int, away_wins: int) -> dict:
    """
    Compute series state tags for each team.
    Returns: {
      "home_state": str,  # from home team's perspective
      "away_state": str,  # from away team's perspective
      "note": str         # plain-English implication for game script
    }

    State labels: "dominant" | "favorable" | "even" | "trailing" | "desperate"
    """
    total = home_wins + away_wins

    def _state(wins: int, losses: int) -> str:
        if wins == 0 and losses == 0:
            return "even"
        if wins > losses:
            diff = wins - losses
            if diff >= 2:
                return "dominant"
            return "favorable"
        else:
            diff = losses - wins
            if diff >= 2:
                return "desperate"
            return "trailing"

    home_state = _state(home_wins, away_wins)
    away_state = _state(away_wins, home_wins)

    if total == 0:
        note = "Pre-series. No games played yet — see Season H2H below for baseline."
    elif home_state == "dominant":
        note = (
            f"{'Away' if away_wins == 0 else 'Home'} team faces potential sweep/"
            f"elimination pressure. Expect star usage spike, tighter rotation, "
            f"desperation pace from the trailing team. Leading team may conserve "
            f"in late blowouts."
        )
    elif away_state == "dominant":
        note = (
            f"Home team faces elimination pressure. Expect star usage spike, tighter "
            f"rotation, desperation pace. Away team may conserve in late blowouts."
        )
    elif home_state == "even" and total >= 2:
        note = "Tied series — each game is effectively a best-of-N from here. Standard game scripts apply."
    elif home_state in ("favorable", "trailing") or away_state in ("favorable", "trailing"):
        note = "Competitive series — both teams playing to win every game. Standard game scripts apply."
    else:
        note = "Series in progress. Monitor rotation tightness and usage trends game-to-game."

    return {
        "home_state": home_state,
        "away_state": away_state,
        "note": note,
    }


# ── Text formatting ───────────────────────────────────────────────────

def _fmt_tier_hits(tier_hits: dict[str, dict[str, list[int]]]) -> str:
    """Format tier hits as compact string: 'PTS: T20 2/2 T25 1/2 | REB: T8 2/2'"""
    parts: list[str] = []
    for stat in ("PTS", "REB", "AST", "TPM"):
        if stat not in tier_hits:
            continue
        tiers = tier_hits[stat]
        tier_strs = [f"{t} {v[0]}/{v[1]}" for t, v in sorted(
            tiers.items(), key=lambda x: int(x[0][1:])
        )]
        if tier_strs:
            parts.append(f"{stat}: {' | '.join(tier_strs)}")
    return "  " + "\n  ".join(parts) if parts else "  (insufficient data)"


def format_series_block(series_data: dict) -> str:
    """
    Format a single series dict into readable text for prompt injection.
    Returns a multi-line string block.
    """
    home = series_data["home_team"]
    away = series_data["away_team"]
    hw   = series_data["home_wins"]
    aw   = series_data["away_wins"]
    conf = series_data.get("conference", "")
    state = series_data["series_state"]
    total_played = hw + aw

    # Header
    if total_played == 0:
        series_record = "0-0 (not yet started)"
    elif hw > aw:
        series_record = f"{home} leads {hw}-{aw}"
    elif aw > hw:
        series_record = f"{away} leads {aw}-{hw}"
    else:
        series_record = f"Tied {hw}-{aw}"

    conf_str = f" — {conf}" if conf else ""
    game_num = series_data.get("game_in_series", total_played + 1)
    phase    = series_data.get("series_phase", "early")
    lines: list[str] = [
        f"=== {home} vs {away}{conf_str} | {series_record} | GAME {game_num} ({phase.upper()}) ===",
    ]

    # TONIGHT line — the explicit per-game host anchor for the analyst.
    # Only emitted when game_today=True AND today_host resolves cleanly.
    # Without this anchor the LLM must extrapolate venue from format
    # patterns + game log (the structural weakness that produced the
    # 2026-04-25 MIN-DEN uniform inversion).
    today_host = series_data.get("today_host")
    if series_data.get("game_today") and today_host:
        next_game_n = total_played + 1
        road_team = away if today_host == home else home
        lines.append(
            f"TONIGHT: Game {next_game_n} at {today_host}. "
            f"{road_team} on the road."
        )

    lines.extend([
        f"State: {home} [{state['home_state'].upper()}] / {away} [{state['away_state'].upper()}]",
        f"Note: {state['note']}",
    ])

    # Game log
    game_log = series_data.get("game_log", [])
    if game_log:
        lines.append("Game log:")
        for i, g in enumerate(game_log, 1):
            loc = "home" if g["home_abbrev"] == home else "away"
            lines.append(
                f"  Game {i} ({g['date']}, {home} {loc}): "
                f"{g['home_abbrev']} {g['home_score']} — {g['away_abbrev']} {g['away_score']} "
                f"(W: {g['winner']})"
            )
    else:
        lines.append("  No games played yet.")

    # Players
    players = series_data.get("players", {})
    if players:
        lines.append("")
        for pname, pdata in players.items():
            player_team = pdata.get("team", "")
            lines.append(f"--- {pname.title()} ({player_team}) ---")

            # Series stats (only if games played)
            ss = pdata.get("series_stats")
            if ss and ss.get("n", 0) > 0:
                a = ss["avgs"]
                lines.append(
                    f"  THIS SERIES ({ss['n']} games): "
                    f"{a.get('pts', 0)} PTS / {a.get('reb', 0)} REB / "
                    f"{a.get('ast', 0)} AST / {a.get('tpm', 0)} 3PM  "
                    f"({a.get('minutes', 0)} min avg)"
                )
                lines.append("  Series tier hits:")
                lines.append(_fmt_tier_hits(ss.get("tier_hits", {})))
            else:
                lines.append("  THIS SERIES: No games played yet.")

            # Season H2H — always shown
            h2h = pdata.get("season_h2h")
            if h2h and h2h.get("all", {}).get("n", 0) > 0:
                all_h2h = h2h["all"]
                a = all_h2h["avgs"]
                lines.append(
                    f"  SEASON H2H vs {away if player_team == home else home} "
                    f"({all_h2h['n']} regular season games): "
                    f"{a.get('pts', 0)} PTS / {a.get('reb', 0)} REB / "
                    f"{a.get('ast', 0)} AST / {a.get('tpm', 0)} 3PM"
                )
                lines.append("  H2H tier hits:")
                lines.append(_fmt_tier_hits(all_h2h.get("tier_hits", {})))
                # Home/away split within H2H
                splits: list[str] = []
                for loc_key, loc_label in (("home", "home"), ("away", "away")):
                    loc_data = h2h.get(loc_key)
                    if loc_data and loc_data.get("n", 0) > 0:
                        la = loc_data["avgs"]
                        splits.append(
                            f"{loc_label.upper()} ({loc_data['n']}g): "
                            f"{la.get('pts', 0)} PTS / {la.get('reb', 0)} REB / "
                            f"{la.get('ast', 0)} AST"
                        )
                if splits:
                    lines.append(f"  H2H splits: {' | '.join(splits)}")
            else:
                lines.append(
                    f"  SEASON H2H: No regular season meetings found "
                    f"(first-time playoff opponent or data gap)."
                )

    return "\n".join(lines)


def format_context_block(series_list: list[dict]) -> str:
    """Build the full ## SERIES CONTEXT text block for analyst injection."""
    if not series_list:
        return ""
    active = [s for s in series_list if s.get("game_today")]
    if not active:
        return ""

    header = (
        "## SERIES CONTEXT — PLAYOFFS\n"
        "Per-series performance data computed from completed playoff games + full regular "
        "season H2H matchup history. Season H2H is shown for ALL series regardless of games "
        "played — it is the baseline that captures the player-vs-opponent relationship across "
        "home/away environments. Series stats reflect actual playoff performance to date.\n\n"
        "Use this section to supplement QUANT STATS:\n"
        "  - Series-specific trend (over/under-performing vs season baseline?)\n"
        "  - Series state — dominant/desperate teams have structurally different game scripts\n"
        "  - Home/away H2H split — home court matters in a 7-game series\n"
        "  - First playoff meeting (0 H2H games) — treat as higher variance; "
        "lean on season DvP and pace signals instead\n"
    )
    series_blocks = "\n\n".join(format_series_block(s) for s in active)
    return header + series_blocks


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[playoff_matchup] Running for {TODAY_STR}")

    bracket = load_bracket()
    if bracket is None:
        return  # regular season mode — no output file written

    playoff_start_date = bracket.get("playoff_start_date", "")
    if not playoff_start_date:
        print("[playoff_matchup] ERROR: playoff_bracket.json missing 'playoff_start_date' — exiting.")
        return

    whitelist = load_whitelist()
    today_teams = load_today_teams()

    print(f"[playoff_matchup] Bracket: {len(bracket.get('series', []))} series | "
          f"Today's teams: {sorted(today_teams)}")

    all_series_data: list[dict] = []

    for series in bracket.get("series", []):
        home = _norm(series.get("home_team", ""))
        away = _norm(series.get("away_team", ""))
        series_id = series.get("series_id", "?")
        conf = series.get("conference", "")
        if not home or not away:
            continue

        game_today = bool(today_teams & {home, away})

        # Load completed series games
        game_results = load_series_game_results(home, away, playoff_start_date)
        series_dates = {g["date"] for g in game_results}

        # Count wins
        home_wins = sum(1 for g in game_results if g["winner"] == home)
        away_wins = sum(1 for g in game_results if g["winner"] == away)

        series_state = compute_series_state(home_wins, away_wins)

        # Next game number in this series (1-indexed)
        game_in_series = len(game_results) + 1
        if game_in_series <= 2:
            series_phase = "early"
        elif game_in_series <= 4:
            series_phase = "mid"
        else:
            series_phase = "late"

        # Build per-player stats for whitelisted players on these two teams
        players_out: dict[str, dict] = {}
        for player_lower, player_team in whitelist.items():
            if player_team not in {home, away}:
                continue
            opp_team = away if player_team == home else home
            stats = load_player_stats_for_matchup(
                player_lower, player_team, opp_team,
                series_dates, playoff_start_date
            )
            # Only include if there's at least some data (series or H2H)
            has_series = stats.get("series_stats") and stats["series_stats"].get("n", 0) > 0
            has_h2h    = stats.get("season_h2h") and stats["season_h2h"].get("all", {}).get("n", 0) > 0
            if has_series or has_h2h:
                players_out[player_lower] = {
                    "team": player_team,
                    "series_stats": stats.get("series_stats"),
                    "season_h2h": stats.get("season_h2h"),
                }

        today_host = load_today_host(home, away) if game_today else None

        series_entry = {
            "series_id":    series_id,
            "conference":   conf,
            "home_team":    home,
            "away_team":    away,
            "home_wins":    home_wins,
            "away_wins":    away_wins,
            "games_played": len(game_results),
            "game_in_series": game_in_series,
            "series_phase":   series_phase,
            "game_today":   game_today,
            "today_host":   today_host,
            "series_state": series_state,
            "game_log":     game_results,
            "players":      players_out,
        }
        all_series_data.append(series_entry)

        print(
            f"[playoff_matchup] {series_id}: {home} {home_wins}-{away_wins} {away} | "
            f"G{game_in_series} ({series_phase}) | "
            f"{len(game_results)} games played | {len(players_out)} WL players | "
            f"game_today={game_today}"
        )

    # Precompute formatted context block (stored for analyst to use directly)
    context_block = format_context_block(all_series_data)

    output = {
        "date":          TODAY_STR,
        "generated_at":  dt.datetime.now(ET).isoformat(),
        "mode":          "playoffs",
        "round":         bracket.get("round", 1),
        "season":        bracket.get("season", ""),
        "series":        all_series_data,
        "context_block": context_block,   # pre-formatted text for analyst injection
    }

    with open(MATCHUP_JSON, "w") as f:
        json.dump(output, f, indent=2)

    active_count = sum(1 for s in all_series_data if s["game_today"])
    print(
        f"[playoff_matchup] Wrote playoff_matchup.json | "
        f"{len(all_series_data)} series | {active_count} with game today"
    )


if __name__ == "__main__":
    main()
