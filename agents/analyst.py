#!/usr/bin/env python3
"""
NBAgent — Analyst

Reads today's game slate, recent player performance, injury context,
and historical audit feedback. Calls Claude to select high-confidence
player prop picks for Points, Rebounds, Assists, and 3-pointers made.

Writes output to data/picks.json.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

MASTER_CSV     = DATA / "nba_master.csv"
GAME_LOG_CSV   = DATA / "player_game_log.csv"
DIM_CSV        = DATA / "player_dim.csv"
INJURIES_JSON  = DATA / "injuries_today.json"
AUDIT_LOG_JSON = DATA / "audit_log.json"
PICKS_JSON     = DATA / "picks.json"
WHITELIST_CSV  = ROOT / "playerprops" / "player_whitelist.csv"
CONTEXT_MD         = ROOT / "context" / "nba_season_context.md"
PLAYER_STATS_JSON  = DATA / "player_stats.json"
AUDIT_SUMMARY_JSON = DATA / "audit_summary.json"
PRE_GAME_NEWS_JSON = DATA / "pre_game_news.json"
STANDINGS_JSON                = DATA / "standings_today.json"
TEAM_DEFENSE_NARRATIVES_JSON = DATA / "team_defense_narratives.json"
LINEUPS_JSON                 = DATA / "lineups_today.json"
SKIPPED_PICKS_JSON           = DATA / "skipped_picks.json"

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

SCOUT_OMITTED_JSON           = DATA / f"scout_omitted_{TODAY_STR}.json"

# ── Config ───────────────────────────────────────────────────────────
MODEL         = "claude-sonnet-4-6"   # default model
MODEL_LARGE   = "claude-opus-4-6"     # upgraded model for large slates
MAX_TOKENS    = 32000                 # was 16384
SCOUT_MAX_TOKENS = 4096              # Scout shortlist JSON is compact; no rules, no tier_walk
# Player count threshold (after injury pre-filter) above which Opus is used
LARGE_SLATE_THRESHOLD = 30
# Valid tier values per prop type — mirrors tier definitions in quant.py and the analyst prompt
VALID_TIERS = {
    "PTS": [10, 15, 20, 25, 30],
    "REB": [4, 6, 8, 10, 12],
    "AST": [2, 4, 6, 8, 10, 12],
    "3PM": [1, 2, 3, 4],
}
# How many recent games to include per player in the prompt
RECENT_GAME_WINDOW = 10
# How many audit log entries to feed back as context (keep lean)
AUDIT_CONTEXT_ENTRIES = 5


# ── Data loaders ─────────────────────────────────────────────────────

def load_todays_games() -> list[dict]:
    """Return today's scheduled games from nba_master.csv."""
    if not MASTER_CSV.exists():
        print(f"[analyst] ERROR: {MASTER_CSV} not found.")
        sys.exit(1)

    df = pd.read_csv(MASTER_CSV, dtype=str)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    today_games = df[df["game_date"] == TODAY_STR].copy()

    if today_games.empty:
        print(f"[analyst] No games found for {TODAY_STR}. Nothing to pick.")
        sys.exit(0)

    games = []
    for _, row in today_games.iterrows():
        def _spread(val):
            try:
                f = float(val)
                return None if pd.isna(f) else round(f, 1)
            except Exception:
                return None
        games.append({
            "game_id":       row.get("game_id", ""),
            "game_time_utc": row.get("game_time_utc", ""),
            "home_team":     row.get("home_team_name", ""),
            "home_abbrev":   row.get("home_team_abbrev", ""),
            "away_team":     row.get("away_team_name", ""),
            "away_abbrev":   row.get("away_team_abbrev", ""),
            "venue_city":    row.get("venue_city", ""),
            "home_spread":   _spread(row.get("home_spread")),
            "away_spread":   _spread(row.get("away_spread")),
            "home_injuries": row.get("home_injuries", "") or "",
            "away_injuries": row.get("away_injuries", "") or "",
        })
    return games


def load_player_game_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    # Exclude today (no results yet) and DNPs
    df = df[df["game_date"] < TODAY_STR].copy()
    df = df[df["dnp"].astype(str) != "1"].copy()
    return df



def load_whitelist() -> set:
    """
    Returns set of (lowercase_name, uppercase_team) tuples for active players.
    Filtering on both name AND team prevents traded players from appearing
    under their old team when game log rows for both teams exist.
    Empty set = no filtering.
    """
    if not WHITELIST_CSV.exists():
        print(f"[analyst] WARNING: whitelist not found, no player filtering applied.")
        return set()
    try:
        df = pd.read_csv(WHITELIST_CSV, dtype=str)
        active = df[df["active"].astype(str).str.strip() == "1"]
        pairs = set(zip(
            active["player_name"].str.strip().str.lower(),
            active["team_abbr"].str.strip().str.upper()
        ))
        print(f"[analyst] Whitelist loaded: {len(pairs)} active player-team pairs")
        return pairs
    except Exception as e:
        print(f"[analyst] WARNING: could not load whitelist: {e}")
        return set()

_ABBR_NORM: dict[str, str] = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP",
    "NY": "NYK", "UTAH": "UTA", "WSH": "WAS",
}

def _norm_team(abbr: str) -> str:
    a = str(abbr).upper().strip()
    return _ABBR_NORM.get(a, a)

def _extract_last(raw_name: str) -> str:
    """Return lowercased last name from either 'F. LastName' or 'FirstName LastName'."""
    n = str(raw_name).strip()
    if len(n) >= 3 and n[1] == "." and n[2] == " ":
        return n[3:].lower()
    parts = n.split()
    return parts[-1].lower() if parts else n.lower()

def load_injuries(teams_today: list[str]) -> dict:
    if not INJURIES_JSON.exists():
        return {}
    try:
        with open(INJURIES_JSON, "r") as f:
            raw = json.load(f)
        # Strip metadata keys, keep team dicts — filtered to today's teams only
        teams_upper = {t.upper() for t in teams_today}
        return {k: v for k, v in raw.items() if isinstance(v, list) and k.upper() in teams_upper}
    except Exception:
        return {}


def load_out_players() -> set[tuple[str, str]]:
    """
    Build a set of (last_name_lower, norm_team_upper) tuples for players
    listed as OUT or DOUBTFUL in today's injury report.
    Used as a hard pre-filter before building quant context and prompt.
    """
    if not INJURIES_JSON.exists():
        return set()
    try:
        with open(INJURIES_JSON, "r") as f:
            raw = json.load(f)
    except Exception:
        return set()

    excluded: set[tuple[str, str]] = set()
    for team_key, entries in raw.items():
        if not isinstance(entries, list):
            continue
        norm_t = _norm_team(team_key)
        for entry in entries:
            status = (entry.get("status") or "").upper().strip()
            if status not in ("OUT", "DOUBTFUL"):
                continue
            raw_name = (entry.get("player_name") or entry.get("name") or "").strip()
            last = _extract_last(raw_name)
            if last:
                excluded.add((last, norm_t))
    return excluded


def load_audit_feedback() -> list[dict]:
    if not AUDIT_LOG_JSON.exists():
        return []
    try:
        with open(AUDIT_LOG_JSON, "r") as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            return []
        # Return most recent N entries
        return entries[-AUDIT_CONTEXT_ENTRIES:]
    except Exception:
        return []


def build_player_context(game_log: pd.DataFrame, teams_today: list[str],
                          whitelist: set) -> str:
    """
    For whitelisted players on teams playing today, build a compact
    recent-performance summary to include in the prompt.
    If whitelist is empty, falls back to all players on today's teams.
    """
    if game_log.empty:
        return "No player game log data available."

    recent = game_log[game_log["team_abbrev"].isin(teams_today)].copy()
    if recent.empty:
        return "No recent game log data for today's teams."

    # Apply whitelist filter: match on both player name AND current team
    # This prevents traded players from appearing under their old team
    if whitelist:
        mask = recent.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1
        )
        recent = recent[mask].copy()
        if recent.empty:
            return "No whitelisted players found for today's teams."

    # Sort by date descending, take last N games per player
    recent = recent.sort_values("game_date", ascending=False)
    recent = recent.groupby("player_id").head(RECENT_GAME_WINDOW).copy()

    lines = []
    for player_name, grp in recent.groupby("player_name"):
        grp = grp.sort_values("game_date", ascending=False)
        team = grp["team_abbrev"].iloc[0]
        games = []
        for _, r in grp.iterrows():
            games.append(
                f"{r['game_date']} vs {r['opp_abbrev']} "
                f"({'H' if r['home_away']=='H' else 'A'}): "
                f"{r['pts']}pts {r['reb']}reb {r['ast']}ast {r['tpm']}3pm "
                f"{r['minutes']}min"
            )
        lines.append(f"\n{player_name} ({team}):\n  " + "\n  ".join(games))

    return "\n".join(lines)


def build_audit_context(audit_entries: list[dict]) -> str:
    if not audit_entries:
        return "No prior audit feedback available yet."

    lines = ["Recent Auditor feedback (use this to refine your selections):"]
    for e in reversed(audit_entries):
        date = e.get("date", "?")
        hit_rate = e.get("hit_rate_pct", "?")
        hits = e.get("hits", 0)
        misses = e.get("misses", 0)
        lines.append(f"\n[{date}] Hit rate: {hit_rate}% ({hits} hits, {misses} misses)")

        if e.get("reinforcements"):
            lines.append("  What worked:")
            for r in e["reinforcements"][:3]:
                lines.append(f"    • {r}")

        if e.get("lessons"):
            lines.append("  What to avoid:")
            for l in e["lessons"][:3]:
                lines.append(f"    • {l}")

        if e.get("recommendations"):
            lines.append("  Analyst recommendations:")
            for r in e["recommendations"][:3]:
                lines.append(f"    • {r}")

    return "\n".join(lines)



def load_season_context() -> str:
    """
    Load the manually-maintained NBA season context document.
    Injected into the prompt between the injury report and player game logs
    so the Analyst can correctly interpret both before making picks.
    Returns empty string gracefully if file is missing — never blocks a run.
    """
    if not CONTEXT_MD.exists():
        print("[analyst] WARNING: context/nba_season_context.md not found, skipping.")
        return ""
    try:
        text = CONTEXT_MD.read_text(encoding="utf-8").strip()
        # Strip HTML comment header block if present
        if text.startswith("<!--"):
            end = text.find("-->")
            if end != -1:
                text = text[end + 3:].strip()
        # Strip the ## TEAM DEFENSIVE PROFILES section — now auto-generated by quant.py
        # and injected separately. Leave the file itself untouched as a reference.
        tdp_idx = text.find("## TEAM DEFENSIVE PROFILES")
        if tdp_idx != -1:
            text = text[:tdp_idx].rstrip()
        print(f"[analyst] Season context loaded ({len(text.split())} words, TEAM DEFENSIVE PROFILES stripped)")
        return text
    except Exception as e:
        print(f"[analyst] WARNING: could not load season context: {e}")
        return ""


def render_playoff_picture(standings_path=STANDINGS_JSON) -> str:
    """
    Read standings_today.json (written by espn_daily_ingest.py) and return a
    compact ## PLAYOFF PICTURE text block for prompt injection.

    Bucketing logic (per conference, by rank within the conference):
      Eliminated       — gb_from_8th > 15.0 (overrides rank)
      Clinched/Safe    — rank ≤ 8 AND ≥ 5 games ahead of 9th
      Playoff In       — rank ≤ 8 AND < 5 games ahead of 9th
      Play-In          — rank 9 or 10
      Bubble           — rank 11 or 12
      Out of Contention— rank 13–15 (and not Eliminated)

    Returns empty string if file missing or parse fails — never blocks a run.
    """
    try:
        if not Path(standings_path).exists():
            print("[analyst] standings_today.json not found — skipping playoff picture.")
            return ""
        with open(standings_path) as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[analyst] WARNING: could not load standings: {e}")
        return ""

    date_str = data.get("date", "unknown")
    lines = [f"## PLAYOFF PICTURE (as of {date_str})"]

    for conf_key, conf_label in [("East", "EAST"), ("West", "WEST")]:
        teams = data.get(conf_key, [])
        if not teams:
            continue
        teams = sorted(teams, key=lambda t: t["rank"])

        gb_8th = teams[7]["gb_leader"] if len(teams) >= 8 else None
        gb_9th = teams[8]["gb_leader"] if len(teams) >= 9 else None

        buckets: dict[str, list[str]] = {
            "Clinched/Safe": [], "Playoff In": [], "Play-In": [],
            "Bubble": [], "Out of Contention": [], "Eliminated": [],
        }

        for t in teams:
            rank = t["rank"]
            gb   = t["gb_leader"]
            entry = f"{rank}. {t['team']} ({t['wins']}-{t['losses']})"

            # Eliminated takes priority over rank
            if gb_8th is not None and (gb - gb_8th) > 15.0:
                buckets["Eliminated"].append(entry)
            elif rank <= 8:
                gb_from_9th = (gb_9th - gb) if gb_9th is not None else 0.0
                if gb_from_9th >= 5.0:
                    buckets["Clinched/Safe"].append(entry)
                else:
                    buckets["Playoff In"].append(entry)
            elif rank in (9, 10):
                buckets["Play-In"].append(entry)
            elif rank in (11, 12):
                buckets["Bubble"].append(entry)
            else:
                buckets["Out of Contention"].append(entry)

        bucket_labels = {
            "Clinched/Safe":    f"{conf_label} — Clinched/Safe (≥5 games clear of bubble):",
            "Playoff In":       f"{conf_label} — Playoff In (within 5 games of safety):",
            "Play-In":          f"{conf_label} — Play-In (9th–10th):",
            "Bubble":           f"{conf_label} — Bubble (11th–12th):",
            "Out of Contention":f"{conf_label} — Out of Contention:",
            "Eliminated":       f"{conf_label} — Eliminated:",
        }

        for key in ["Clinched/Safe", "Playoff In", "Play-In", "Bubble", "Out of Contention", "Eliminated"]:
            if not buckets[key]:
                continue
            lines.append(bucket_labels[key])
            lines.append("  " + "  ".join(buckets[key]))

        lines.append("")  # blank line between conferences

    if len(lines) <= 1:
        return ""
    print(f"[analyst] Playoff picture rendered ({date_str})")
    return "\n".join(lines).rstrip()


def format_team_defense_section(narratives_path=TEAM_DEFENSE_NARRATIVES_JSON) -> str:
    """
    Read team_defense_narratives.json (written by quant.py) and return a
    formatted ## TEAM DEFENSIVE PROFILES block for prompt injection.

    Returns a warning line if the file is missing or stale (date != today).
    Returns the warning line on any parse error — never blocks a run.

    Normal output format:
      ## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated YYYY-MM-DD)
      ATL (last 15g): Allows 112.3 PPG (rank: 18th)....
      BOS (last 15g): Allows 107.1 PPG (rank: 5th)....
      ...  (alphabetical, one line per team, no blank lines)
    """
    fallback = (
        "## TEAM DEFENSIVE PROFILES\n"
        "⚠ Team defense narratives unavailable for today — "
        "falling back to season context file."
    )
    try:
        if not Path(narratives_path).exists():
            print("[analyst] team_defense_narratives.json not found — using fallback warning.")
            return fallback
        with open(narratives_path) as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[analyst] WARNING: could not load team defense narratives: {e}")
        return fallback

    as_of = data.get("as_of", "")
    if as_of != TODAY_STR:
        print(
            f"[analyst] team_defense_narratives.json stale ({as_of} vs today {TODAY_STR})"
            " — using fallback warning."
        )
        return fallback

    narratives = data.get("narratives", {})
    if not narratives:
        print("[analyst] team_defense_narratives.json has no narratives — using fallback warning.")
        return fallback

    lines = [f"## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated {as_of})"]
    for abbr in sorted(narratives):
        lines.append(narratives[abbr])
    print(f"[analyst] Team defense narratives loaded ({len(narratives)} teams, as of {as_of})")
    return "\n".join(lines)


def format_lineups_section(lineups_path: Path = LINEUPS_JSON, today_teams: set | None = None) -> str:
    """
    Read lineups_today.json (written by rotowire_injuries_only.py) and return a
    formatted ## PROJECTED LINEUPS block for prompt injection.

    Groups by game using nba_master.csv for home/away pairing and game time.
    Cross-references injuries_today.json for key absences.

    Returns a single-line fallback if the file is missing, stale, or unparseable.
    Never raises — always returns a string.
    """
    fallback = "## PROJECTED LINEUPS\n[Lineup data unavailable — injury report only]"

    try:
        if not lineups_path.exists():
            return fallback
        with open(lineups_path) as fh:
            data = json.load(fh)
    except Exception:
        return fallback

    if data.get("asof_date") != TODAY_STR:
        return fallback

    built_at = data.get("built_at_utc", "")

    # Load injuries for key absences
    inj_by_team: dict = {}
    try:
        if INJURIES_JSON.exists():
            with open(INJURIES_JSON) as fh:
                inj_raw = json.load(fh)
            inj_by_team = {k: v for k, v in inj_raw.items() if isinstance(v, list)}
    except Exception:
        pass

    # Load today's games for pairing and game times
    games: list[dict] = []
    try:
        if MASTER_CSV.exists():
            df = pd.read_csv(MASTER_CSV, dtype=str)
            today_games = df[df["game_date"] == TODAY_STR]
            for _, row in today_games.iterrows():
                games.append({
                    "home": str(row.get("home_team_abbrev", "") or "").strip().upper(),
                    "away": str(row.get("away_team_abbrev", "") or "").strip().upper(),
                    "time_utc": str(row.get("game_time_utc", "") or "").strip(),
                })
    except Exception:
        pass

    # Normalise a team abbrev for lineup lookup
    _ABBR = {"GS": "GSW", "SA": "SAS", "NO": "NOP", "NY": "NYK", "UTAH": "UTA", "WSH": "WAS"}

    def _norm(a: str) -> str:
        return _ABBR.get(a.upper(), a.upper())

    def _game_time_pt(utc_str: str) -> str:
        try:
            ts = dt.datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            pt = ts.astimezone(ET)
            h, m = pt.hour, pt.minute
            suffix = "AM" if h < 12 else "PM"
            h12 = h % 12 or 12
            return f"{h12}:{m:02d} {suffix} PT"
        except Exception:
            return ""

    # Determine which teams we're covering
    covered_teams = set(today_teams) if today_teams else set()
    all_game_teams: set[str] = set()
    for g in games:
        all_game_teams.add(_norm(g["home"]))
        all_game_teams.add(_norm(g["away"]))

    lines = [f"## PROJECTED LINEUPS\nas_of: {built_at}\n"]

    processed: set[str] = set()

    # Game-grouped output
    for g in games:
        home = _norm(g["home"])
        away = _norm(g["away"])
        time_str = _game_time_pt(g["time_utc"])
        header = f"{away} vs {home}"
        if time_str:
            header += f" — {time_str}"
        lines.append(header)

        for team in (away, home):
            team_data = data.get(team) or data.get(g["home"] if team == home else g["away"])
            if not isinstance(team_data, dict):
                lines.append(f"{team}: Lineup not yet available")
            else:
                starters = team_data.get("starters", [])
                confirmed = team_data.get("confirmed", False)
                label = "Confirmed" if confirmed else "Expected"
                if starters:
                    parts = []
                    for s in starters:
                        entry = f"{s['position']} {s['name']}"
                        if s.get("injury_status"):
                            entry += f" [{s['injury_status']}]"
                        parts.append(entry)
                    lines.append(f"{team} ({label}): {' | '.join(parts)}")
                else:
                    lines.append(f"{team}: Lineup not yet available")

                # Key absences from injury report
                absent = []
                for entry in inj_by_team.get(team, []):
                    status = (entry.get("status") or "").upper()
                    if status in ("OUT", "DOUBT", "OFS"):
                        name = entry.get("name") or entry.get("player_name") or ""
                        if name:
                            absent.append(f"{name} ({status})")
                if absent:
                    lines.append(f"  ⚠ Key absences: {', '.join(absent)}")

            processed.add(team)

        lines.append("")

    # Any teams not matched to a game (edge case)
    if covered_teams:
        for team in sorted(covered_teams - processed):
            t = _norm(team)
            team_data = data.get(t)
            if isinstance(team_data, dict) and team_data.get("starters"):
                starters = team_data["starters"]
                confirmed = team_data.get("confirmed", False)
                label = "Confirmed" if confirmed else "Expected"
                parts = []
                for s in starters:
                    entry = f"{s['position']} {s['name']}"
                    if s.get("injury_status"):
                        entry += f" [{s['injury_status']}]"
                    parts.append(entry)
                lines.append(f"{t} ({label}): {' | '.join(parts)}")
                absent = []
                for entry in inj_by_team.get(t, []):
                    status = (entry.get("status") or "").upper()
                    if status in ("OUT", "DOUBT", "OFS"):
                        name = entry.get("name") or entry.get("player_name") or ""
                        if name:
                            absent.append(f"{name} ({status})")
                if absent:
                    lines.append(f"  ⚠ Key absences: {', '.join(absent)}")
                lines.append("")

    print(f"[analyst] Loaded projected lineups ({len(games)} games from lineups_today.json)")
    return "\n".join(lines).strip()


def write_analyst_snapshot(lineups_path: Path, picks_run_at: str) -> None:
    """
    Write a snapshot of the lineup state at analyst run time into
    lineups_today.json under the key 'snapshot_at_analyst_run'.
    This is the baseline for P5 change-detection — never updated after this point.
    """
    if not lineups_path.exists():
        return
    try:
        with open(lineups_path) as fh:
            raw = json.load(fh)
    except Exception:
        return

    if raw.get("snapshot_at_analyst_run"):
        return  # Already snapshotted this run — do not overwrite

    snapshot: dict = {"written_at": picks_run_at, "teams": {}}
    for key, val in raw.items():
        if key in ("asof_date", "built_at_utc", "source", "snapshot_at_analyst_run"):
            continue
        if isinstance(val, dict) and "starters" in val:
            snapshot["teams"][key] = {
                "starters": [s["name"] for s in val.get("starters", [])],
                "confirmed": val.get("confirmed", False),
            }

    raw["snapshot_at_analyst_run"] = snapshot
    tmp = lineups_path.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(raw, fh, indent=2)
    os.replace(tmp, lineups_path)
    print(f"[analyst] Wrote lineup snapshot for {len(snapshot['teams'])} teams")


def load_pre_game_news() -> str:
    """
    Load pre_game_news.json written by pre_game_reporter.py.
    Formats player_notes, game_notes, and context flags as a readable text block.
    Critical context flags are prepended with high-visibility formatting.
    Monitor flags are appended as a light note at the end.
    Returns empty string gracefully if file missing or empty — never blocks a run.
    """
    if not PRE_GAME_NEWS_JSON.exists():
        print("[analyst] pre_game_news.json not found — proceeding without news context.")
        return ""
    try:
        with open(PRE_GAME_NEWS_JSON) as f:
            data = json.load(f)
    except Exception as e:
        print(f"[analyst] WARNING: could not load pre_game_news.json: {e}")
        return ""

    player_notes = data.get("player_notes") or {}
    game_notes   = data.get("game_notes")   or {}
    flags        = data.get("suggested_context_updates") or []

    critical_flags = [f for f in flags if f.get("urgency") == "critical"]
    monitor_flags  = [f for f in flags if f.get("urgency") == "monitor"]

    if not player_notes and not game_notes and not critical_flags and not monitor_flags:
        print("[analyst] Pre-game news: no notable items today.")
        return ""

    sections = []

    # Critical context flags — prepended before PLAYER NEWS with high visibility
    if critical_flags:
        flag_lines = [
            "⚠ SEASON CONTEXT FLAGS — REVIEW BEFORE PICKING:",
            "These facts in the season context file may be outdated. Do not rely on the "
            "flagged entries below until the context file is manually updated. Use today's "
            "news items as the more reliable source for these players.",
            "",
        ]
        for flag in critical_flags:
            player   = flag.get("player_or_team", "Unknown")
            conflict = flag.get("conflict", "")
            flag_lines.append(f"CRITICAL: {player} — {conflict}")
        sections.append("\n".join(flag_lines))

    if player_notes:
        note_lines = ["PLAYER NEWS:"]
        for name, note in player_notes.items():
            note_lines.append(f"- {name.title()}: {note}")
        sections.append("\n".join(note_lines))

    if game_notes:
        note_lines = ["GAME NOTES:"]
        for game, note in game_notes.items():
            note_lines.append(f"- {game}: {note}")
        sections.append("\n".join(note_lines))

    # Monitor flags — lighter note appended at end
    if monitor_flags:
        monitor_lines = ["👀 MONITOR — context may be becoming stale:"]
        for flag in monitor_flags:
            player   = flag.get("player_or_team", "Unknown")
            conflict = flag.get("conflict", "")
            monitor_lines.append(f"- {player}: {conflict}")
        sections.append("\n".join(monitor_lines))

    n_crit      = len(critical_flags)
    n_all_flags = len(flags)
    flag_suffix = f", {n_all_flags} context flags (⚠ {n_crit} critical)" if critical_flags else ""
    print(
        f"[analyst] Pre-game news loaded: {len(player_notes)} player notes, "
        f"{len(game_notes)} game notes{flag_suffix}"
    )
    return "\n\n".join(sections)


def load_player_stats() -> dict:
    """Load pre-computed quant stats from player_stats.json."""
    if not PLAYER_STATS_JSON.exists():
        print("[analyst] WARNING: player_stats.json not found — quant context unavailable.")
        return {}
    try:
        with open(PLAYER_STATS_JSON, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[analyst] WARNING: could not load player_stats.json: {e}")
        return {}


def load_lineup_context() -> dict[str, dict]:
    """
    Load projected_minutes and onoff_usage from lineups_today.json.
    Returns a dict keyed by normalised team abbreviation:
        {
          "LAL": {
            "projected_minutes": {name_lower: {"minutes": 36, "section": "STARTERS"}},
            "onoff_usage":       {name_lower: {"usage_pct": 30.9, "usage_change": 10.0,
                                               "minutes_sample": 111,
                                               "absent_players": ["Anthony Davis"]}}
          },
          ...
        }
    Returns {} gracefully if file missing, stale, or unparseable — never blocks a run.
    """
    if not LINEUPS_JSON.exists():
        return {}
    try:
        with open(LINEUPS_JSON) as fh:
            raw = json.load(fh)
    except Exception as e:
        print(f"[analyst] WARNING: could not load lineup context: {e}")
        return {}

    if raw.get("asof_date") != TODAY_STR:
        print("[analyst] lineup context stale — skipping proj_min / onoff annotations")
        return {}

    result: dict[str, dict] = {}
    skip_keys = {"asof_date", "built_at_utc", "source", "snapshot_at_analyst_run"}

    for team_key, team_data in raw.items():
        if team_key in skip_keys or not isinstance(team_data, dict):
            continue
        norm = _norm_team(team_key)

        # projected_minutes: index by name_lower
        pm_list = team_data.get("projected_minutes") or []
        pm_map: dict[str, dict] = {}
        for entry in pm_list:
            name = (entry.get("name") or "").strip()
            if name:
                pm_map[name.lower()] = {
                    "minutes": entry.get("minutes", 0),
                    "section": entry.get("section", ""),
                }

        # onoff_usage: index by name_lower
        ou_list = team_data.get("onoff_usage") or []
        ou_map: dict[str, dict] = {}
        for entry in ou_list:
            name = (entry.get("name") or "").strip()
            if name:
                ou_map[name.lower()] = {
                    "usage_pct":      entry.get("usage_pct"),
                    "usage_change":   entry.get("usage_change"),
                    "minutes_sample": entry.get("minutes_sample"),
                    "absent_players": entry.get("absent_players") or [],
                }

        if pm_map or ou_map:
            result[norm] = {
                "projected_minutes": pm_map,
                "onoff_usage":       ou_map,
            }

    print(f"[analyst] Lineup context loaded: {len(result)} teams with proj_min/onoff data")
    return result


def load_player_profiles(player_stats: dict) -> str:
    """
    Extract pre-rendered player profile narratives from player_stats dict.
    Returns a formatted multi-player block for injection into the analyst prompt,
    or empty string if no profiles are available (e.g. first run before quant writes them).
    """
    blocks = []
    for player_name in sorted(player_stats):
        narrative = player_stats[player_name].get("profile_narrative")
        if narrative:
            blocks.append(narrative)
    if not blocks:
        return ""
    return "\n\n".join(blocks)


def build_player_leaderboard(game_log: pd.DataFrame, whitelist: set) -> str:
    """
    Build a compact per-stat leaderboard of whitelisted players ranked by:
      - Season average (all non-DNP games in the log)
      - L20 average (last 20 non-DNP games)

    Both rankings shown side by side — season reveals established elite status;
    L20 reveals who is surging or declining relative to their season baseline.

    Only includes active whitelisted players (same tuple filter as build_player_context).
    Top 15 per stat per ranking. Stats: PTS, REB, AST, 3PM.

    Returns a formatted ## WHITELISTED PLAYER RANKINGS block, or "" on any error.
    """
    if game_log.empty or not whitelist:
        return ""

    try:
        # Apply whitelist filter — same logic as build_player_context()
        mask = game_log.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1
        )
        wl_log = game_log[mask].copy()

        if wl_log.empty:
            return ""

        # Exclude DNPs
        wl_log = wl_log[wl_log["dnp"].astype(str) != "1"].copy()
        wl_log["game_date"] = pd.to_datetime(wl_log["game_date"], errors="coerce")
        wl_log = wl_log.dropna(subset=["game_date"])

        STAT_COLS = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}
        TOP_N = 15

        lines = ["## WHITELISTED PLAYER RANKINGS — SEASON vs L20"]
        lines.append(
            "Use to identify elite-tier players (high season avg) and surging/declining "
            "players (L20 diverging from season). Ranks are among whitelisted players only."
        )
        lines.append("")

        for stat, col in STAT_COLS.items():
            if col not in wl_log.columns:
                continue

            wl_log[col] = pd.to_numeric(wl_log[col], errors="coerce")

            # Season averages — all games in log
            season_avgs = (
                wl_log.groupby("player_name")[col]
                .mean()
                .round(1)
                .sort_values(ascending=False)
                .head(TOP_N)
            )

            # L20 averages — last 20 games per player (newest first)
            l20_avgs: dict[str, float] = {}
            for pname, grp in wl_log.groupby("player_name"):
                recent = grp.sort_values("game_date", ascending=False).head(20)
                if len(recent) >= 5:  # min 5 games to show L20
                    l20_avgs[pname] = round(recent[col].mean(), 1)

            # Build ranked rows — season rank as primary ordering
            rows = []
            for rank, (pname, s_avg) in enumerate(season_avgs.items(), start=1):
                l20_val = l20_avgs.get(pname)
                # Determine L20 rank among players who have L20 data
                if l20_val is not None and l20_avgs:
                    l20_sorted = sorted(l20_avgs.items(), key=lambda x: x[1], reverse=True)
                    l20_rank = next(
                        (i + 1 for i, (n, _) in enumerate(l20_sorted) if n == pname),
                        None
                    )
                else:
                    l20_rank = None

                # Arrow showing season→L20 rank movement
                if l20_rank is not None:
                    delta = rank - l20_rank  # positive = moved up in L20
                    if delta >= 3:
                        arrow = "↑"
                    elif delta <= -3:
                        arrow = "↓"
                    else:
                        arrow = "→"
                    l20_str = f"L20:{l20_val}({arrow}{l20_rank})"
                else:
                    l20_str = "L20:—"

                rows.append(f"{rank}. {pname} {s_avg} [{l20_str}]")

            if rows:
                lines.append(f"{stat}: " + "  |  ".join(rows))

        lines.append("")
        result = "\n".join(lines)
        print(f"[analyst] Player leaderboard built ({TOP_N} per stat, season + L20)")
        return result

    except Exception as e:
        print(f"[analyst] WARNING: could not build player leaderboard: {e}")
        return ""


def build_quant_context(player_stats: dict, lineup_context: dict | None = None) -> str:
    """
    Build a compact quant stats block for the prompt.
    Shows pre-computed best tiers and matchup-specific hit rates (vs_soft, vs_tough)
    at the best qualifying tier for each stat. Only includes players with at least
    one qualifying best tier.
    """
    if not player_stats:
        return "No quant stats available."

    lines = []
    for player_name in sorted(player_stats):
        s = player_stats[player_name]
        opp              = s.get("opponent", "?")

        # ── Lineup context lookups ────────────────────────────────────
        lc = lineup_context or {}
        player_team_lc = lc.get(_norm_team(s.get("team", ""))) or {}
        opp_team_lc    = lc.get(_norm_team(opp)) or {}

        player_name_lower = player_name.strip().lower()

        # Projected minutes for this player
        pm_entry   = (player_team_lc.get("projected_minutes") or {}).get(player_name_lower)
        proj_min   = pm_entry["minutes"] if pm_entry else None
        proj_min_str = f" proj_min={proj_min}" if proj_min is not None else ""

        # Usage spike: only fire when change >= +5.0pp AND sample >= 100 min
        ou_entry     = (player_team_lc.get("onoff_usage") or {}).get(player_name_lower)
        usg_spike_str = ""
        if ou_entry:
            change  = ou_entry.get("usage_change")
            sample  = ou_entry.get("minutes_sample") or 0
            absent  = ou_entry.get("absent_players") or []
            if change is not None and change >= 5.0 and sample >= 100:
                def _abbrev_name(n: str) -> str:
                    parts = n.strip().split()
                    if len(parts) >= 2:
                        return f"{parts[0][0]}.{parts[-1]}"
                    return n
                absent_str = "+".join(_abbrev_name(n) for n in absent[:2])
                usg_spike_str = f" [USG_SPIKE:+{change:.1f}pp vs {absent_str}]" if absent_str else f" [USG_SPIKE:+{change:.1f}pp]"

        # Opposing key absences: rotation players projected 0 or absent (section=OUT)
        opp_absence_lines: list[str] = []
        opp_pm = opp_team_lc.get("projected_minutes") or {}
        for opp_name, opp_pm_data in opp_pm.items():
            opp_minutes = opp_pm_data.get("minutes", 0)
            opp_section = opp_pm_data.get("section", "")
            if opp_section == "OUT" or opp_minutes == 0:
                display = opp_name.title()
                opp_absence_lines.append(f"  ⚠ OPP: {display} OUT (proj={opp_minutes}min)")
        # Cap at 3 opposing absences to avoid clutter
        opp_absence_str = "\n".join(opp_absence_lines[:3])

        best_tiers       = s.get("best_tiers") or {}
        matchup_hrs      = s.get("matchup_tier_hit_rates") or {}
        trends           = s.get("trend") or {}
        blowout_risk     = s.get("blowout_risk", False)
        spread_abs       = s.get("spread_abs")
        spread_splits    = s.get("spread_split_hit_rates") or {}
        on_b2b           = s.get("on_back_to_back", False)
        rest_days        = s.get("rest_days")
        games_last_7     = s.get("games_last_7", 0)
        dense_schedule   = s.get("dense_schedule", False)
        b2b_hit_rates      = s.get("b2b_hit_rates") or {}
        minutes_floor_data = s.get("minutes_floor") or {}
        games_available    = s.get("games_available", 10)

        # Team-level opp defense ratings — used for opp_today= annotations on PTS/AST stat lines
        opp_def_all = s.get("opp_defense") or {}

        # Momentum line — L10 record + avg margin for both teams
        momentum_line = ""
        tm_ctx  = s.get("team_momentum") or {}
        tm_self = tm_ctx.get("team") or {}
        tm_opp  = tm_ctx.get("opponent") or {}
        if tm_self or tm_opp:
            def _fmt_momentum(m: dict, label: str) -> str:
                if not m:
                    return ""
                w   = m.get("l10_wins", 0)
                l   = m.get("l10_losses", 0)
                mg  = m.get("l10_margin")
                tag = m.get("tag", "")
                tag_str = f" [{tag}]" if tag and tag != "neutral" else ""
                mg_str  = f" avg_margin={mg:+.1f}" if mg is not None else ""
                return f"{label}: {w}-{l} L10{mg_str}{tag_str}"
            parts = []
            self_str = _fmt_momentum(tm_self, s.get("team", "TEAM"))
            opp_str  = _fmt_momentum(tm_opp,  s.get("opponent", "OPP"))
            if self_str: parts.append(self_str)
            if opp_str:  parts.append(opp_str)
            if parts:
                momentum_line = "  Momentum — " + " | ".join(parts)

        # Whitelisted teammates line — current-season roster grounding
        wt = s.get("whitelisted_teammates") or []
        teammates_line = f"  Teammates (active/whitelisted): {', '.join(wt)}" if wt else ""

        # Key teammate absence split — shown when n >= 3
        kta = s.get("key_teammate_absent")
        kta_line = ""
        if kta and kta.get("n_games", 0) >= 3:
            tm_name   = kta["teammate_name"]
            tm_pts    = kta["teammate_avg_pts"]
            n_abs     = kta["n_games"]
            kta_parts = []
            for _st in ("PTS", "REB", "AST", "3PM"):
                _avg  = (kta.get("raw_avgs") or {}).get(_st)
                _thrs = (kta.get("tier_hit_rates") or {}).get(_st)
                if _avg is None or not _thrs:
                    continue
                # Show best 1–2 tiers (hit rate >= 50%) for readability
                _tier_strs = []
                for _t in VALID_TIERS.get(_st, []):
                    _hr = _thrs.get(str(_t))
                    if _hr is not None and _hr >= 0.50:
                        _tier_strs.append(f"T{_t}={int(round(_hr*100))}%")
                if _tier_strs:
                    kta_parts.append(f"{_st} avg={_avg} {' '.join(_tier_strs[:2])}")
            if kta_parts:
                kta_line = (
                    f"  Without {tm_name} (their avg={tm_pts}pts, n={n_abs}g): "
                    + " | ".join(kta_parts)
                )

        stat_parts = []
        bounce_back_all    = s.get("bounce_back") or {}
        volatility_all     = s.get("volatility") or {}
        shooting_reg       = s.get("shooting_regression") or {}
        ft_safety          = s.get("ft_safety_margin") or {}
        for stat in ("PTS", "REB", "AST", "3PM"):
            best = best_tiers.get(stat)
            if not best:
                continue
            tier        = best["tier"]
            overall_pct = int(round(best["hit_rate"] * 100))
            trend       = trends.get(stat, "stable")

            matchup_at_tier = (matchup_hrs.get(stat) or {}).get(str(tier)) or {}
            soft  = matchup_at_tier.get("soft")
            tough = matchup_at_tier.get("tough")
            soft_str  = f"{int(round(soft['hit_rate']*100))}%({soft['n']}g)"  if soft  else "n/a"
            tough_str = f"{int(round(tough['hit_rate']*100))}%({tough['n']}g)" if tough else "n/a"

            # Spread split at this tier
            spread_stat = (spread_splits.get(stat) or {})
            comp_data   = spread_stat.get("competitive")
            blow_data   = spread_stat.get("blowout")
            comp_str = (
                f"{int(round(comp_data['hit_rates'].get(str(tier), 0)*100))}%({comp_data['n']}g)"
                if comp_data else "n/a"
            )
            blow_str = (
                f"{int(round(blow_data['hit_rates'].get(str(tier), 0)*100))}%({blow_data['n']}g)"
                if blow_data else "n/a"
            )

            # B2B hit rate at this tier (only shown when player is on B2B today)
            b2b_stat = b2b_hit_rates.get(stat)
            if on_b2b:
                if b2b_stat is not None:
                    b2b_pct = int(round(b2b_stat["hit_rates"].get(str(tier), 0) * 100))
                    b2b_str = f"{b2b_pct}%({b2b_stat['n']}g)"
                else:
                    b2b_str = "<5g"  # signal to apply one-tier-down fallback
                b2b_field = f" b2b={b2b_str}"
            else:
                b2b_field = ""

            # Bounce-back annotation: shown when lift > 1.0 or iron_floor
            bb_data = bounce_back_all.get(stat)
            if bb_data:
                if bb_data.get("iron_floor"):
                    bb_field = " [iron_floor]"
                elif bb_data.get("lift", 1.0) > 1.0:
                    bb_field = f" bb_lift={bb_data['lift']:.2f}({bb_data['n_misses']}miss)"
                else:
                    bb_field = ""
            else:
                bb_field = ""

            # Volatility tag
            vol = volatility_all.get(stat, {})
            vol_label = vol.get("label", "")
            if vol_label == "volatile":
                vol_tag = " [VOLATILE]"
            elif vol_label == "consistent":
                vol_tag = " [consistent]"
            else:
                vol_tag = ""  # moderate or missing = baseline, no tag

            # Shooting efficiency regression tag — PTS only
            shoot_flag = ""
            if stat == "PTS":
                sr_flag      = shooting_reg.get("fg_flag")
                sr_delta_pct = shooting_reg.get("fg_delta_pct")
                if sr_flag == "hot" and sr_delta_pct is not None:
                    shoot_flag = f" [FG_HOT:+{int(round(sr_delta_pct * 100))}%]"
                elif sr_flag == "cold" and sr_delta_pct is not None:
                    shoot_flag = f" [FG_COLD:{int(round(sr_delta_pct * 100))}%]"

                # FG% safety margin annotation (H11) — PTS only, at player's best qualifying tier
                fsm_tier_data = (ft_safety.get("tiers") or {}).get(str(tier), {})
                fsm_flag_val  = fsm_tier_data.get("flag", "")
                fsm_margin    = fsm_tier_data.get("margin")
                if fsm_flag_val == "ft_dominant":
                    pass  # no annotation needed — FTs + 3s cover the tier alone
                elif fsm_flag_val == "borderline" and fsm_margin is not None:
                    shoot_flag += f" [FG_MARGIN_THIN:{int(round(fsm_margin * 100))}%]"
                elif fsm_flag_val == "fragile" and fsm_margin is not None:
                    shoot_flag += f" [FG_MARGIN_NEG:{int(round(fsm_margin * 100))}%]"
                # safe or missing: no annotation — baseline, don't clutter

            # opp_today= annotation: team-level defense rating, PTS and AST only (pre-P1 format)
            if stat in ("PTS", "AST"):
                opp_rating = (opp_def_all.get(stat) or {}).get("rating", "?")
                opp_today_str = f" opp_today={opp_rating}"
            else:
                opp_today_str = ""

            stat_parts.append(
                f"  {stat}: tier={tier} overall={overall_pct}%{opp_today_str} "
                f"vs_soft={soft_str} vs_tough={tough_str} "
                f"competitive={comp_str} blowout_games={blow_str} "
                f"trend={trend}{b2b_field}{bb_field}{vol_tag}{shoot_flag}"
            )

        floor_val = minutes_floor_data.get("floor_minutes")
        avg_val   = minutes_floor_data.get("avg_minutes")
        if floor_val is not None and avg_val is not None:
            min_floor_str = f" min_floor={floor_val}(avg={avg_val})"
        else:
            min_floor_str = ""

        # Defensive recency flag for today's opponent (L5 vs L15 divergence)
        def_recency = s.get("def_recency")
        def_rec_str = " DEF↑" if def_recency == "soft" else " DEF↓" if def_recency == "tough" else ""

        if stat_parts:
            spread_info  = f"spread_abs={spread_abs:.1f}" if spread_abs is not None else "spread=n/a"
            blowout_flag = " BLOWOUT_RISK=True" if blowout_risk else ""
            # Rest/fatigue flags in header
            if on_b2b:
                rest_flag = " B2B"
            elif rest_days is not None:
                rest_flag = f" rest={rest_days}d"
            else:
                rest_flag = ""
            dense_flag = " DENSE" if dense_schedule else ""
            l7_field   = f" L7:{games_last_7}g" if games_last_7 > 0 else ""
            ga_flag    = f" [SHORT_SAMPLE:{games_available}g]" if games_available < 8 else ""
            lines.append(
                f"{player_name} (vs {opp} | {spread_info}{blowout_flag}{rest_flag}{dense_flag}{l7_field}{ga_flag}{min_floor_str}{proj_min_str}{usg_spike_str}{def_rec_str}):\n"
                + (momentum_line  + "\n" if momentum_line  else "")
                + (teammates_line + "\n" if teammates_line else "")
                + (kta_line      + "\n" if kta_line       else "")
                + (opp_absence_str + "\n" if opp_absence_str else "")
                + "\n".join(stat_parts)
            )

    return "\n\n".join(lines) if lines else "No qualifying player quant stats."


def load_audit_summary() -> str:
    """Load rolling audit summary and format as readable text for the prompt."""
    if not AUDIT_SUMMARY_JSON.exists():
        return ""
    try:
        with open(AUDIT_SUMMARY_JSON) as f:
            s = json.load(f)
    except Exception:
        return ""

    n = s.get("entries_included", 0)
    if n < 3:
        return ""  # Not enough history to be meaningful yet

    overall = s.get("overall", {})
    hr      = overall.get("hit_rate_pct", 0)
    hits    = overall.get("hits",         0)
    misses  = overall.get("misses",       0)

    lines = [
        f"Season-to-date: {hits} hits / {misses} misses = {hr}% hit rate across {n} audit days.",
    ]

    # Per-prop breakdown
    prop_sum = s.get("prop_type_summary", {})
    if prop_sum:
        prop_parts = []
        for pt in ("PTS", "REB", "AST", "3PM"):
            d = prop_sum.get(pt)
            if d and d.get("picks", 0) >= 5:
                prop_parts.append(f"{pt}: {d['hit_rate_pct']}% ({d['hits']}/{d['picks']})")
        if prop_parts:
            lines.append("Per-prop: " + " | ".join(prop_parts))

    # Miss classification breakdown
    mc = s.get("miss_classification_totals", {})
    total_mc = sum(mc.values())
    if total_mc > 0:
        mc_parts = []
        for k in ("selection_error", "model_gap", "variance"):
            v = mc.get(k, 0)
            if v > 0:
                pct = round(v / total_mc * 100)
                mc_parts.append(f"{k}: {v} ({pct}%)")
        if mc_parts:
            lines.append("Miss classification: " + " | ".join(mc_parts))

    # Confidence calibration — helps spot over/under-confidence
    conf = s.get("confidence_calibration_totals", {})
    if conf:
        conf_parts = []
        for band in ("70-75", "76-80", "81-85", "86+"):
            d = conf.get(band)
            if d and d.get("picks", 0) >= 5:
                conf_parts.append(f"{band}%: {d['hit_rate_pct']}% ({d['picks']} picks)")
        if conf_parts:
            lines.append("Confidence calibration: " + " | ".join(conf_parts))

    # Parlay summary
    p = s.get("parlay_summary", {})
    p_total = p.get("total", 0)
    if p_total > 0:
        p_hr = round(p.get("hits", 0) / p_total * 100)
        lines.append(f"Parlays: {p.get('hits', 0)} hit / {p_total} total ({p_hr}%)")

    # Recent lessons (from last 5 audit days)
    lessons = s.get("recent_lessons", [])
    if lessons:
        lines.append("Recent lessons:")
        for l in lessons[-5:]:
            lines.append(f"  - {l}")

    # Recent reinforcements
    reinforcements = s.get("recent_reinforcements", [])
    if reinforcements:
        lines.append("Recent reinforcements:")
        for r in reinforcements[-5:]:
            lines.append(f"  + {r}")

    # Carry-forward recommendations
    recs = s.get("recent_recommendations", [])
    if recs:
        lines.append("Carry-forward recommendations:")
        for r in recs[-3:]:
            lines.append(f"  → {r}")

    return "\n".join(lines)


# ── Prompt builder ───────────────────────────────────────────────────

def build_prompt(games: list[dict], player_context: str, injuries: dict, audit_context: str, season_context: str, quant_context: str = "", audit_summary: str = "", pre_game_news: str = "", player_profiles: str = "", playoff_picture: str = "", team_defense: str = "", leaderboard: str = "", lineups_section: str = "") -> str:
    games_block = json.dumps(games, indent=2)
    injuries_block = json.dumps(injuries, indent=2)

    pre_game_section = (
        "## PRE-GAME NEWS\n"
        "The following news items were published in the last 48 hours and are material to "
        "today's picks. These supplement — do not replace — the structured injury report "
        "above. Cross-reference player availability and role notes here before finalizing "
        "confidence levels.\n\n"
        f"{pre_game_news}\n\n"
    ) if pre_game_news else ""

    playoff_picture_section = f"{playoff_picture}\n\n" if playoff_picture else ""
    team_defense_section    = f"{team_defense}\n\n"    if team_defense    else ""
    leaderboard_section     = f"{leaderboard}\n\n"     if leaderboard     else ""
    lineups_block           = f"{lineups_section}\n\n" if lineups_section else ""

    player_profiles_section = (
        "## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS\n"
        "Pre-computed from the same game log data as the quant stats above. Use these to "
        "identify structural risk factors (B2B-sensitive players, blowout-sensitive scorers, "
        "FG-dependent players in tough matchups) and to contextualize recent hit sequences "
        "(current streak, longest miss streak). These are informational — they do not override "
        "tier hit rates but help explain why a high-hit-rate player might be structurally "
        "fragile today.\n\n"
        f"{player_profiles}\n\n"
    ) if player_profiles else ""

    return f"""You are the Analyst for NBAgent, an NBA player props selection system.

Today is {TODAY_STR}.

## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE
Your model weights were frozen at a training cutoff that may be 1–2+ years behind today's date.
This means specific facts you "know" about the NBA may be significantly stale.
Apply the following rules for this session:

**Trust the injected data. Distrust your priors on anything perishable.**

Perishable knowledge — do NOT rely on your training data for:
- Player roles and usage: A player you know as a star starter may now be a bench
  reserve, traded, injured long-term, or playing reduced minutes under a new coach.
  A player you know as a role player may now be a primary option. Use QUANT STATS
  and PROJECTED LINEUPS as ground truth for current role.
- Team rosters and depth charts: Trades, free agency, two-way contracts, and injuries
  accumulate continuously. The roster you trained on is not the current roster.
  Use PROJECTED LINEUPS and INJURY REPORT as ground truth.
- Team systems and pace: Coaching changes, new offensive schemes, and style shifts
  happen every season. Do not reason about a team's pace or usage patterns from
  memory — use TEAM DEFENSIVE PROFILES and GAME CONTEXT for current indicators.
- Head-to-head matchup history: Your recollection of how a player performs against
  a specific opponent is based on games played before your training cutoff. Use
  the matchup-specific tier hit rates in QUANT STATS (vs_soft, vs_tough, matchup
  DvP) as the current ground truth for matchup quality.
- Season narratives and storylines: Any "this player is on a hot streak" or "this
  team is struggling" narrative from your training is stale. Today's form is in
  the L10 game log and QUANT STATS trend field.

Durable knowledge — APPLY freely:
- General basketball principles: how pace affects counting stats, how usage
  concentration works when creators are absent, how B2B fatigue manifests, how
  home/away splits typically behave, how playoff-race motivation affects effort.
- Tier logic and statistical reasoning: hit rate interpretation, regression to the
  mean, sample size caution, volatility effects on floor picks.
- Role archetype reasoning: what a primary ball handler's absence typically means
  for the next-usage player, how a rim protector's absence opens scoring lanes,
  how a floor spacer's absence compresses an offense.

When in doubt: if a fact is specific to a named player or team, use the injected data.
If it is a general principle about how basketball works, apply it freely.

## YOUR TASK
Select high-confidence player prop picks for today's games. Focus on:
- Points (PTS)
- Rebounds (REB)
- Assists (AST)
- 3-pointers made (3PM)

## TIER SYSTEM — HOW TO THINK ABOUT THRESHOLDS
This system targets fixed tier thresholds that match how parlays are structured on betting platforms.
Do NOT pick arbitrary lines. Only use values from these tiers:

  PTS tiers:  10 / 15 / 20 / 25 / 30
  REB tiers:  4 / 6 / 8 / 10 / 12
  AST tiers:  2 / 4 / 6 / 8 / 10 / 12
  3PM tiers:  1 / 2 / 3 / 4

**Hit definition:** A pick is a HIT if actual_value >= pick_value. Exactly hitting the threshold counts
as a hit — a player scoring exactly 20 pts on a 20-tier pick is a HIT, not a miss.

For each player/stat, your job is to find the highest tier where their hit rate across recent games
is strong enough to justify ≥70% confidence. Work DOWN from the player's ceiling until you find
a tier with a reliable floor.

Example reasoning process for PTS:
  - Player averages 21 pts but has inconsistent games (14, 22, 18, 28, 16, 24, 12, 19, 21, 17)
  - At the ≥20 tier: games with pts≥20: 22,28,24,21 = 4/10 = 40% → skip
  - At the ≥15 tier: games with pts≥15: 22,18,28,16,24,19,21,17 = 8/10 = 80% → this is the pick
  - pick_value = 15, confidence = 80%

The edge is in finding floors the market undervalues. Season averages overstate consistency.
A player who averages 21 pts but only reaches 20 half the time is a 15-tier pick, not a 20-tier pick.

## SELECTION RULES
- LINEUP CONTEXT: ## PROJECTED LINEUPS shows today's expected starters and key absences per
  game. Use this as ground truth for who is playing. A player listed as a starter with no
  injury flag is confirmed available for that game. A player not in the starting lineup but
  also not listed as OUT/DOUBTFUL may be a bench contributor — apply normal analysis. Never
  pick a player listed in Key absences as OUT or DOUBTFUL (the pre-filter should have already
  excluded them, but this is your backstop).
- Weight recent form (last 5–10 games) heavily — season averages are misleading
- Minimum 5 recent games required to evaluate any player
- INJURY EXCLUSION (HARD RULE): Players listed as OUT or DOUBTFUL have been removed from the
  quant context and player logs before this prompt was built. Do NOT generate any pick for a
  player who does not appear in the ## QUANT STATS section. If a player appears in the game
  log but not in QUANT STATS, treat them as excluded — do not pick them.
- Factor in teammate injuries (affects usage/role) and back-to-back fatigue
- Use SEASON CONTEXT to distinguish stable baselines from genuine injury-driven role changes
- Pick as many qualifying props as there are — don't limit volume artificially
- Only output picks with confidence_pct ≥ 70. This is a floor, not a target —
  do not round up from a lower honest assessment to meet it. See KEY FRAMEWORK above.
- 3PM CONFIDENCE FLOOR: For 3PM props specifically, the minimum confidence is 75%, not 70%.
  Do not output any 3PM pick with confidence_pct below 75. A 3PM pick that qualifies at
  71%, 72%, 73%, or 74% does not meet the bar — skip it entirely (no skip record needed,
  as no hard rule fired; the pick simply did not clear the prop-specific floor).
  Rationale: 3PM props have binary outcome risk (0-for-game is always possible for any
  shooter regardless of tier) and thin risk/reward at low thresholds (T1 iron_floor prices
  near -500 to -1000 on most platforms). The 5pp higher floor filters the most marginal
  3PM picks while preserving structurally sound iron_floor picks at 78%+ confidence.
  This floor applies after all penalties and caps — if confidence after VOLATILE deduction,
  blowout cap, and trend step-down lands below 75%, skip the 3PM pick.
- Where a player's stats card shows bb_lift > 1.15 for a stat at their qualifying tier, treat a post-miss pick as a neutral-to-positive signal rather than a negative one. Where [iron_floor] is shown, a single prior miss carries no negative weight.
- REB props — minimum confidence floor: Do not output any REB pick with confidence_pct below 78%. REB is the system's highest-variance category (season hit rate 66.7% vs 85.7% for PTS). A REB pick that would otherwise qualify at 72% or 75% confidence does not meet the bar — skip it entirely.
- REB props — pick value gate: The pick value must be strictly below the player's L10 25th-percentile REB output. Compute this as the 3rd-lowest REB value across their last 10 games. The pick tier must be strictly less than this floor value — an exact match is not sufficient. Rationale: when the 3rd-lowest L10 value equals the pick threshold exactly, there is zero variance buffer. A single outlier game (even for a player with a 10/10 hit rate) breaks the streak with no protective cushion. If the intended tier equals or exceeds this floor, move down one tier. If no valid tier exists strictly below the floor, skip the REB prop entirely.
  Exception — T4 minimum tier: This exact-match gate does NOT apply when pick_value = 4 (the minimum valid REB tier). At T4, there is no lower valid tier to step to, so the zero-buffer logic does not apply in the same way — validate T4 picks on hit rate merit alone. The gate still fires normally for pick_value ≥ 6.
- REB props for offensive-first players: For players whose primary role is scoring or playmaking (PTS avg > 20, or AST avg > 6 across their recent games), the 25th-percentile gate above applies with extra strictness — if the player's REB floor (lowest value in their last 10 games) is within 2 of your intended pick value, skip the REB prop and pick their scoring or assists prop instead. A thin floor at high volume is a trap. Both the 78% confidence minimum AND the floor gate must pass before any REB pick is output.
- Tier walk-down discipline: Always evaluate tiers from highest to lowest for the stat.
  Never select a tier if the tier immediately above it also qualifies (≥70% hit rate in
  recent window). The tier_walk field must document every tier evaluated — if you skipped
  tiers without checking them, that is a selection error the Auditor will flag. Show your
  work.

## TIER CEILING RULES — backed by full-season calibration data
The following tiers are systemically miscalibrated: players selected at these tiers hit
significantly below the 70% confidence floor when measured over a full season (6,437 instances).
Treat them as requiring exceptional justification — do not pick them by default.

  REB T8+: actual season hit rate 63.2% (n=247) at w10; improves to 71.0% (n=200) at w20 window.
    Only select if player has hit 7+/10 at this tier in their recent window. Otherwise cap at T6.
    Do NOT use opp_defense_rating as a justification for REB T8 — see REB rule below.

  AST T6+: actual season hit rate 65.1% (n=255). Only select if player has hit 7+/10
    at this tier AND their role context explicitly supports elevated assist load today
    (e.g. primary ball handler with multiple creators absent). Otherwise cap at T4.

  PTS T25+: actual season hit rate 66.8% (n=253) — below the 70% system threshold. For this
    tier specifically, require ≥80% hit rate in the player's recent window (8+/10 at the ≥25
    tier) before selecting. The tier calibrates below floor league-wide; a higher individual bar
    is needed to compensate. Essentially never select PTS T30 — season hit rate 56.8% (n=81).
  PTS T25 BLOWOUT HARD SKIP: If spread_abs >= 15 AND the player's team is the favored side
    (negative spread), do NOT select PTS T25 or T30 for any player regardless of hit rate,
    iron_floor tag, or elite scorer status. This is a hard skip — do not apply a confidence
    cap and proceed. Emit a skip record with skip_reason=blowout_t25_skip.
    Rationale: confirmed three times (Jokic Mar 17: spread_abs=15.5, 25min, 8 PTS; SGA Mar 18:
    spread_abs=19.5, 26min, 20 PTS; manually caught pre-game). At extreme spreads, even elite
    scorers face early rest and role subordination that makes T25 structurally unachievable.
    The current cap-at-74% approach still generates the pick; a hard skip prevents it entirely.
    Note: T20 and below for elite scorers in spread_abs 15+ games are still subject to the
    existing spread_abs >= 15 cap rule (74% max) — this hard skip applies only to T25 and T30.

  3PM T2: calibrates at 71.4% (n=441) — above the 70% threshold. No ceiling rule needed.
  3PM T3+: actual season hit rate 58.6% (n=157). Only select if player has hit 7+/10 at this
    tier in their recent window AND today's game has a high pace tag. Otherwise cap at T2.

Note: trend direction (up/stable/down) and home/away context are available in the data below
but have not shown predictive value in historical calibration. Do not weight them as primary
selection signals.

## TODAY'S GAMES
{games_block}

## CURRENT INJURY REPORT
{injuries_block}

{lineups_block}{pre_game_section}## SEASON CONTEXT — READ BEFORE INTERPRETING INJURIES OR PLAYER LOGS
{season_context if season_context else "No season context file found."}

{playoff_picture_section}{leaderboard_section}{team_defense_section}## PLAYER RECENT PERFORMANCE (last {RECENT_GAME_WINDOW} games)
{player_context}

## QUANT STATS — PRE-COMPUTED TIER ANALYSIS
These numbers are computed from the full season game log — larger sample than the L10 above.
"overall" = hit rate at this tier across last 10 games.
"vs_soft" / "vs_tough" = hit rate at this tier across the full season, split by opponent defensive quality.

KEY FRAMEWORK — HOW TO REASON WHEN RULES CONFLICT:

The rules below can conflict. When they do, use this priority order:

  1. HARD SKIPS — absolute, no override. volatile_weak_combo, blowout_secondary_scorer,
     ast_hard_gate, 3pm_blowout_trend_down, volatile_ast_t6, and all other named skip
     rules execute unconditionally. If a hard skip fires, the pick does not exist. Period.

  2. MANDATORY TIER STEPS — execute first, then re-evaluate from the new tier.
     min_floor < 24 → step down. FG_COLD ≥ 15% on T15+ → step down. After stepping,
     re-check whether the new tier qualifies on hit rate. If it does not, skip.
     These steps happen before any confidence arithmetic.

  3. CONFIDENCE PENALTIES — apply cumulatively after tier is set.
     VOLATILE -5%, BLOWOUT -10%, B2B rate substitution, DENSE -5–10%.
     Floor is 70%: if cumulative penalties push below 70%, the pick fails on merit —
     skip it. Do not round up to 70% to force a qualifying pick.

  4. CONFIDENCE CAPS — applied last, after all penalties.
     spread_abs > 8 → 80% ceiling. spread_abs ≥ 12 → 74% ceiling.
     Caps are ceilings, not targets. A pick capped at 74% should be stated as 74%,
     not inflated to 80% because the cap "allows" it.

  5. POSITIVE SIGNALS — offset penalties where explicitly documented.
     iron_floor, consistent tag, soft DvP, favorable rest. These can reduce the
     net penalty but cannot push confidence above a cap ceiling.

PENALTY STACK LIMIT: If more than 3 independent confidence penalties apply to a single pick,
stop and re-examine. Either the pick is genuinely marginal and should be skipped, or some
penalties are redundant (e.g. B2B rate already prices in fatigue — also applying DENSE -5%
is double-counting). Document each penalty in tier_walk and ask: is this adjustment
independent of the others? If not, drop the weakest one. A pick that requires 4+ penalties
to stay above 70% is not a confident pick — skip it.

TIER_WALK FORMAT — document the final state clearly:
  - Each tier checked: "T25→8/10✓" or "T20→5/10 skip"
  - Mandatory steps: "min_floor<24 → step T15→T10"
  - Confidence chain as a clean sequence: "80% base → VOLATILE -5% → 75% → spread cap → 74% final"
  - The final selected tier must be unambiguously marked ✓
  - Do NOT embed skip conclusions ("→ SKIP") in tier_walk for picks you are emitting.
    If you conclude skip at any point in the reasoning, do not emit the pick.

SANITY CHECK — before finalizing each pick, verify:
  1. Is the final tier consistent with this player's actual statistical floor?
     A T10 PTS pick on a player whose L10 minimum is 17 points is incoherent.
     Check: does the tier you selected reflect a genuine uncertainty, or did
     the penalty cascade produce a tier that real game outcomes contradict?
  2. Is the stated confidence honestly derived? If hit rate is 9/10 but confidence
     is 74%, the tier_walk must show clearly why (caps applied, not fabricated).
  3. Did your own reasoning conclude "skip" at any step? If yes, do not emit the pick.
     filter_self_skip_picks() runs in Python as a backstop, but eliminate the
     contradiction at source — don't rely on post-processing to catch your errors.
  4. Does the pick pass the smell test? You have domain knowledge. A T10 PTS pick
     on the league's leading scorer is almost certainly wrong regardless of what
     the penalty arithmetic produced. Trust that signal — skip or re-examine.

ON COMPLEX SLATES: Today's slate may include blowout games, B2B players, VOLATILE scorers,
FG_COLD flags, and players returning from injury — all simultaneously. This is normal. Each
player is evaluated independently. A 16-point spread in one game does not affect picks in
other games. When multiple risk signals co-occur on a single player:
  - Apply them in the priority order above
  - Trust the output — if the output is a skip, the skip is correct
  - Do not force picks to meet a volume target. The system generates enough picks
    across a full slate that individual skips are preferable to low-confidence
    forced picks. Quality over quantity on every player.

PLAYER TIER CONTEXT — use the leaderboard: The ## WHITELISTED PLAYER RANKINGS block shows
current season and L20 averages. Use this as ground truth for player quality standing —
do not rely on training knowledge for who is "elite" this season. Rankings shift with trades,
injuries, and role changes. A player ranked #1 in PTS among whitelisted players has a
structurally different floor than a player ranked #12, and should be treated accordingly
regardless of what your training data suggests about their historical status. The ELITE SCORER
BLOWOUT EXEMPTION (raw_avgs PTS ≥ 27.0) is most reliably applied when you have verified the
player's current season ranking in the leaderboard block.

CONFIDENCE THRESHOLD IS A FLOOR, NOT A TARGET: 70% is the minimum threshold for emitting a
pick, not a number to land on. If your honest assessment after all adjustments is 65%, skip
the pick — do not adjust your stated confidence upward to clear the threshold. A pick stated
at exactly 70% must genuinely reflect 70% conviction. Rounding up from 65% is a skip
masquerading as a pick, and the auditor will find it.

KEY RULES — MATCHUP QUALITY:
- opp_today= on PTS and AST stat lines shows today's opponent's team-level defense rating.
  Use this as the primary signal for matchup quality on those stats.
- vs_soft / vs_tough on each stat line show this player's historical hit rate split by
  opponent defensive quality — use these together with opp_today= for confirmation.
- If opp_today=tough AND vs_tough drops materially below overall (e.g. 80% → 50%),
  downgrade confidence or move to a lower tier.
- If opp_today=soft AND vs_soft is significantly higher than overall, you may pick
  a higher tier than the overall rate alone suggests.
- "n/a" on vs_soft/vs_tough means insufficient sample (<3 games) — fall back to opp_today= only.

OPPONENT DEFENSE:
Stat-specific rules:

  PTS / AST: use the opp_today= rating on each stat line as the primary defense signal.
    Soft = favorable (upgrade bias or higher confidence).
    Tough = unfavorable (downgrade one tier or reduce confidence by 5–10%).

  AST T4+ HARD GATE — low-volume passers vs non-soft defenses:
    If you are considering an AST pick at T4 or higher AND either of the following is true:
      (a) the player's position is PF or C, OR
      (b) the player's raw_avgs AST is below 4.0 per game
    → the opponent's AST opp_today rating MUST be "soft" to proceed.
    → If the AST opp_today rating is "mid" or "tough", SKIP this pick entirely — regardless of overall
      hit rate, confidence, or other signals. This gate is unconditional.
    This prevents low-volume or frontcourt passers from being picked at AST T4+ against defenses
    that historically suppress assists at that position.
    Exception — elite playmakers: This gate does NOT apply to players whose raw_avgs AST is
    ≥ 8.0 per game. A player averaging 8+ APG is a primary playmaking engine regardless of
    position — the positional gate was not designed for this profile. These players may be
    evaluated for AST T4+ picks against any defensive rating using normal tier and hit-rate
    logic. (This exemption applies to the AST volume criterion only — if you are applying
    the gate because of low raw_avgs AST below 4.0, the ≥8.0 threshold is irrelevant.)

  VOLATILE + HIGH AST TIER BLOCK: When a player carries the VOLATILE tag (shown as [volatile]
    in their volatility field) AND the selected AST tier is T6 or higher, do NOT pick the AST
    prop regardless of elite playmaker exemption status. The elite playmaker exemption
    (raw_avgs AST >= 8.0) protects against the minimum floor gate — it does not protect against
    floor instability. A VOLATILE tag means the player's AST floor is genuinely unpredictable,
    and T6+ AST picks on volatile playmakers have confirmed miss history even at high
    season-level hit rates. Apply this as a hard SKIP: VOLATILE + AST tier >= T6 = SKIP,
    no exceptions.

  REB: opp_defense does NOT make REB a valid defense signal. Do not use REB rating as
    justification for a REB over. Rebounds are driven by pace, opponent FG%, and frontcourt
    competition — not captured by allowed-per-team averages. Ignore REB rating entirely.

  3PM: opp_defense is NOISE regardless of positional granularity (lift variance 0.053 across
    6,437 instances, corrected grading). Do not weight 3PM rating in either direction.

KEY RULES — REST & FATIGUE:
- Player header shows "B2B" (back-to-back, 0 days rest), "rest=Xd" (days since last game),
  "DENSE" (4+ games in 5 nights), and "L7:Xg" (games played in last 7 days).
- When "B2B" is shown:
  → Use "b2b=" rate instead of overall hit rate for tier selection.
  → If b2b="<5g" (fewer than 5 B2B games in history), apply a conservative one-tier-down
    adjustment from your normal best tier. Do not pick the same tier as non-B2B.
- When "DENSE" is shown (even without B2B): cumulative fatigue is likely.
  → Reduce confidence by 5–10% across all stats for that player.
- rest_days ≥ 3 = well-rested; no downward adjustment needed.

IRON-FLOOR B2B ROAD GATE: The iron_floor tag does NOT override the B2B + tough defense gate
for AST props on non-primary ball-handlers. Apply this gate when ALL of the following are true:
  - on_back_to_back = True
  - home_away = "A" (road game)
  - opp_defense rating = "tough"
  - raw_avgs AST < 6.0 (non-primary ball-handler)
When all four conditions are met, require opp_defense = "soft" as a prerequisite for any AST
pick, regardless of iron_floor status. If opp_defense is "mid" or "tough", SKIP the AST pick.
Rationale: iron_floor reflects a structural historical minimum across all game contexts. On B2B
road games against championship-caliber defenses, wings with modest assist averages (SF/SG,
AST avg < 6.0) are operating in a situational context that the historical iron_floor pattern
does not capture. The floor is for stable contexts — this is not a stable context.

RETURN FROM INJURY — SHORT SAMPLE INSTABILITY:
- When a player header shows [SHORT_SAMPLE:Ng] (fewer than 8 played games in L10 window),
  the player has recently returned from injury or missed an extended stretch. Their L10
  statistical floor has not restabilized — early return games frequently show compressed
  minutes, conservative role, and below-normal production that will skew the floor downward.
- For REB and AST props: apply a mandatory one-tier step-down from your normal best tier.
  If the stepped-down tier does not qualify (hit rate <70%), skip the prop entirely.
  Rationale: REB and AST are heavily role- and minutes-dependent; a returning player's
  floor in these categories is unreliable until they have 8+ games of consistent usage.
- For PTS props: apply a confidence reduction of 5% and do not pick above T15 unless the
  player has ≥7 games in the L10 window at T20+ with a consistent or up trend.
  Rationale: elite scorers re-establish their scoring floor faster than role-dependent
  stats, but the L10 sample instability still warrants caution at higher tiers.
- Do NOT apply this rule if the player's games_available is 8 or higher — the [SHORT_SAMPLE]
  flag will not appear in that case.
- Do NOT apply this rule to ignore iron_floor tags — iron_floor reflects the historical
  record and is still informative even in a short window. But short sample + iron_floor is
  not sufficient to override the mandatory REB/AST step-down.

WITHOUT-STAR BASELINE — TWO REQUIRED GATES:
The quant context shows a "Without [Player X] (their avg=Ypt, n=Zg):" line when a key teammate
has been absent for ≥3 recent games. This Without-Star data shows the player's hit rates and
averages in a lineup without that teammate. Two gates govern its use:

GATE 1 — CONFIRMED-OUT REQUIREMENT: A Without-Star baseline may only be used as the PRIMARY
tier qualifier for a pick when the absent star is confirmed OUT in today's injury report or
projected lineups section.
  - If the star is listed as OUT or is absent from today's projected lineup: the
    Without-Star tier hit rate may be used to qualify a tier, the same as any other
    hit rate signal.
  - If the star is listed as QUES, GTD, PROBABLE, or not listed in today's injury report:
    fall back to the standard shared-lineup baseline (the overall= hit rate). If the
    standard baseline qualifies a tier at ≥70%, use that tier. If the standard baseline
    does not qualify any tier, skip the pick — do not use the Without-Star data to
    manufacture a qualifying tier when the star's absence is uncertain.
  - Do not assume the star is OUT based on recent game log absence patterns. Use only
    today's injury report and projected lineups section as the source of truth.
  Rationale: a QUES designation at pick time means the star may play. If they play,
  the Without-Star usage and role assumptions are invalid mid-game, and a tier that
  only qualified under the Without-Star baseline will be structurally unsupported once
  the star enters the lineup. LeBron PTS T15 miss on 2026-03-21 (actual 12, Luka listed
  QUES, Without-Luka n=6 used as sole qualifying path) is the prototype case.

GATE 2 — MINIMUM SAMPLE GUARD: If the Without-X sample shown in the quant annotation is
fewer than 10 games (n < 10), treat the Without-Star data as supplementary context only —
do not use it as the sole qualifying path to a tier.
  - n ≥ 10: Without-Star hit rates may serve as primary tier evidence (subject to Gate 1).
  - n < 10: Without-Star data is informational only. Use the standard shared-lineup
    baseline for tier selection. The Without-Star data may support a confidence
    adjustment (e.g., note that usage is typically higher without the star), but it
    cannot be the reason a tier qualifies. If the standard baseline does not qualify
    any tier, skip the pick.
  Rationale: six games is enough to observe a usage pattern but not enough to reliably
  estimate a 70%+ hit rate — a single game sequence can move a small sample from
  "qualifies" to "does not qualify." The 10-game threshold aligns with the general
  quant window and provides a minimum reliability floor.
  Note: n < 10 does NOT mean the data is useless. Use it in tier_walk reasoning to
  note directional support (e.g., "Without-Luka n=6 suggests T15 usage, but sample
  too small to qualify — using standard T10 baseline"). It informs but does not gate.

GATE INTERACTION: Both gates must pass before Without-Star data may be used to qualify a
tier. Gate 1 (OUT status) and Gate 2 (n ≥ 10) are independent checks — a confirmed-OUT
star with only n=5 still fails Gate 2.

Document in tier_walk whether Without-Star data was used (and which gate(s) applied):
  - "Without-Luka (OUT confirmed, n=6 <10 — Gate 2 fail): using standard T10=85%✓"
  - "Without-Luka (OUT confirmed, n=12 ✓): T15=95%✓ → primary qualifier"
  - "Without-Luka (QUES — Gate 1 fail): using standard T10=80%✓"
MINUTES FLOOR — THRESHOLD EVENT FRAGILITY:
- The min_floor= value in each player header is the 10th-percentile of their L10 minutes.
  It represents the worst-case realistic playing time in recent games.
- For PTS picks at T15 or higher: if min_floor < 24, you MUST step down exactly one full tier
  before finalizing the pick (e.g. T15 → T10, T20 → T15). Do not treat this as a confidence
  reduction option — the step-down is mandatory. Rationale: two independent audit misses (Ball
  min_floor=22.9 at T15, Flagg FG_COLD at T15) both fell exactly 1 point short of threshold in
  games where minutes fragility was the structural risk. A confidence cap alone is insufficient
  when the tier itself is exposed by a sub-24 minute floor. After stepping down, re-evaluate
  whether the lower tier qualifies (≥70% hit rate). If it does not qualify, skip the PTS pick
  entirely. Exception: if avg_minutes > 36, this rule does not apply — elite-usage players
  rarely sit regardless of game script.
- For REB and AST picks: if min_floor < 20, apply the same caution.
- If min_floor >= avg_minutes - 3 (floor is close to average = very consistent minutes),
  treat this as a mild positive signal — the player rarely has outlier-low minutes nights.
- Do NOT apply this rule when the player's avg_minutes > 36: elite-usage players rarely
  sit regardless of game script.
- MIN_FLOOR CONFIDENCE CAP: For any PTS pick where the player's floor_minutes (from the
  minutes_floor field) is below 24.0, cap the final stated confidence_pct at 84%, regardless
  of hit streak length, iron_floor tag, or any other signal. Do not assign 85%, 86%, 87%,
  88%, or higher confidence to a PTS pick on a player whose floor_minutes < 24. The iron_floor
  and consistent tags reflect historical frequency but do not account for matchup-specific
  suppression in games where the player's baseline minutes exposure is below the 24-minute
  threshold — streak-based signals overstate reliability when the underlying minutes floor
  cannot support them. Apply this cap silently; do not explain it in the reasoning field
  unless it changes what you would otherwise have stated.

KEY RULES — SEQUENTIAL GAME CONTEXT:
- REB slump-persistent (confirmed signal, n=300, window=10):
  Post-miss REB hit rate drops to 62.0% vs baseline 75.0% (lift=0.83). Rebounds do NOT bounce back
  the next game — a miss is predictive of another miss.
  → If a player missed their REB tier last game, apply −5% confidence OR prefer one tier lower.
  → This applies regardless of opponent or home/away. The pattern holds across conditions.
- 3PM cold-streak decline (confirmed signal, n=161, severe cold = L5 hit rate ≥10pp below L10/L20):
  Players in a severe 3PM cold streak hit at 68.3% next game (lift=0.87 vs baseline 78.2%).
  Unlike other stats, 3PM cold streaks do not self-correct at N+1 — the slump persists or deepens.
  → If a player's recent L5 3PM output is materially below their L10/L20 rate, apply −5% confidence
    or skip the pick. Prefer cold-streak 3PM players only if facing a soft matchup.
- 3PM trend=down mandatory step-down (live rule, motivated by observed miss pattern):
  If the trend field for a player's 3PM stat is "down", you MUST step down exactly one full tier
  from your analytically selected floor before finalizing the pick.
  Example: best qualifying tier is T2 with 9/10 hit rate → trend=down → pick T1 instead.
  Do NOT use the aggregate hit rate to override this step-down. A 9/10 overall rate at T2
  means nothing if the directional signal is declining — the 0-make outcome is within range.
  This rule does not apply to PTS or AST (trend has shown no sequential signal for those stats).
  If stepping down would take the tier below the minimum valid tier (T1 for 3PM), skip the
  3PM pick entirely for that player.
- 3PM hard skip — trend=down AND limited minutes:
  If a player's 3PM trend is "down" AND their avg_minutes_last5 is ≤ 30, SKIP all 3PM picks
  for that player, including T1. Do not apply the step-down rule — skip outright.
  Rationale: low-minute players have fewer 3PM attempts per game; a declining trend in limited
  minutes means the absolute floor on makes is very close to zero. T1 (1+ make) is not a safe
  floor in this profile.
  This gate applies to the trend=down case only. A player with trend=stable or trend=up and
  avg_minutes_last5 ≤ 30 may still qualify for T1 via normal tier selection logic.
- 3PM hard skip — trend=down AND tough DvP:
  If a player's 3PM trend is "down" AND the opponent's DvP 3PM rating is "tough", SKIP all
  3PM picks for that player, including T1. Do not apply the step-down rule — skip outright.
  Rationale: after a trend=down step-down lands at T1, there is no margin left. A single
  cold-shooting night produces zero — which is within normal variance for any shooter. When
  the opponent is also rated tough for 3PM defense at the positional level, perimeter
  opportunity is further compressed. The combination of declining trend + tough perimeter
  defense makes T1 a binary coin flip, not a floor. Historical hit rates at 8/10 or 9/10
  do not protect against this combination — both T1 miss examples in the March 9 audit
  (Mitchell 3PM, Murray 3PM) had 8/10 and 9/10 rates respectively and went 0 actual.
  Note: 3PM DvP is otherwise treated as noise (no confidence adjustments in either direction).
  This skip rule is the sole exception — it applies only when BOTH conditions are met
  (trend=down AND tough DvP). A player with trend=down alone still uses the step-down rule.
  A player with tough DvP alone and trend=stable or up is unaffected.
- 3PM hard skip — trend=down AND blowout_risk=True:
  If a player's 3PM trend is "down" AND BLOWOUT_RISK=True is shown in their header (meaning
  their team is heavily favored, spread_abs > 8), SKIP all 3PM picks for that player,
  including T1. Do not apply the step-down rule — skip outright.
  This rule overrides the [iron_floor] tag. Iron_floor reflects historical frequency of
  hitting the tier; it does not protect against game-script volume compression in blowouts.
  When a favored team's lead grows large, 3PM attempts decline disproportionately in the
  fourth quarter — stars are benched, shot selection becomes conservative, and the floor on
  3PM collapses regardless of the player's historical pattern.
  Rationale: Donovan Mitchell 3PM T1 miss on 2026-03-13 in a 33-point CLE blowout win.
  The system correctly applied BLOWOUT -10% and the trend=down step-down to T1, and the
  pick still missed. The iron_floor tag was present and provided no protection. The
  combination of declining trend + winning-side blowout makes even T1 3PM structurally
  unreliable — the mechanics that produce zero makes are in play regardless of the tier floor.
  Note: this skip applies only to BLOWOUT_RISK=True (favored team, spread_abs > 8).
  A player on the losing-side team in a blowout is subject to the existing BLOWOUT_RISK
  rules and secondary-scorer skip rules — not this rule. The mechanism here is specific to
  winning-side players whose minutes get compressed when the game is decided early.
- 3PM hard skip — extreme blowout regardless of trend (spread_abs ≥ 19):
  If BLOWOUT_RISK=True AND spread_abs ≥ 19, SKIP all 3PM picks for ALL players on the
  favored team, regardless of trend direction. This rule fires even when trend=up or
  trend=stable. Do not apply step-downs — skip outright including T1.
  Rationale: SGA went 0-for-3 on threes in a 29-point OKC blowout win on 2026-03-18
  despite trend=up and a 9/10 T1 hit rate. At spread_abs ≥ 19 the game is effectively
  decided before tip-off — shot selection collapses toward drives and free throws
  regardless of the player's trend or role. The existing trend=down rule correctly handles
  moderate blowouts; this companion rule closes the gap for extreme spreads where even
  trend=up players face structural volume compression.
  This rule is additive to the trend=down rule: if trend=down AND spread_abs ≥ 8, the
  trend=down rule fires first. If trend=up or stable AND spread_abs ≥ 19, this rule fires.
  skip_reason: 3pm_blowout_trend_down (reuse existing enum for auditor consistency).
- PTS, AST: insufficient sequential signal. No adjustment needed based on last-game result.
- 3PM confidence ceiling — 80% maximum for non-iron-floor picks:
  Do not assign confidence_pct above 80 on any 3PM pick unless iron_floor=true on that
  stat. This cap applies regardless of hit rate, trend, consistent tag, or soft matchup.
  Rationale: 3PM props have binary outcome variance (0-for-game is always possible for
  any shooter) that the tier and hit-rate system cannot fully price. A 9/10 hit rate on
  a 3PM prop means the player goes 0-for in approximately 10% of games — and when they
  do, the miss is always maximal (actual=0 vs any threshold). Confidence above 80% on
  a non-iron-floor 3PM pick overstates the system's ability to distinguish those games.
  Audit evidence: Austin Reaves 3PM T1 at 84% confidence (top_pick=true), 9/10 hit rate,
  consistent tag — actual 0, miss. The 81–85% band on 3PM props ran at 50% over the
  sample period, consistent with overcalibration at high confidence on this prop type.
  Application: after all penalties and caps are applied, if the resulting confidence_pct
  for a 3PM pick exceeds 80, reduce it to 80. If iron_floor=true on the 3PM stat, the
  80% cap does not apply — iron_floor reflects a confirmed volume floor that provides
  structural protection against the 0-for-game scenario.
  top_pick ineligibility: Do not set top_pick=true on any 3PM pick unless iron_floor=true.
  A 3PM pick without iron_floor is not a structural top pick regardless of hit rate.

KEY RULES — INJURY STATUS ON SHOOTING PROPS:
- When a player carries a QUESTIONABLE status in the injury report, check the injury
  description. If the injury involves a soft-tissue joint concern (ankle, foot, knee,
  hip, groin), apply an additional -5% confidence penalty to ALL shooting-dependent props
  (3PM and PTS) for that player, regardless of trend direction or hit rate.
- Rationale: soft-tissue joint injuries subtly alter shot mechanics and selection —
  compromised lower-body movement shifts attempts toward the paint and mid-range and away
  from the perimeter. This affects 3PM floors directly and PTS floors indirectly via
  reduced shooting efficiency. The QUESTIONABLE tag for these injury types should function
  as a hard signal for shooting props, not just a minutes-floor caution.
- This penalty applies to QUESTIONABLE status only. OUT and DOUBTFUL players are already
  excluded from the prompt via pre-filter. Players listed as PROBABLE or not listed are
  unaffected.
- If the injury description is not a soft-tissue joint concern (e.g., illness, rest,
  non-contact soreness), do not apply this penalty.
- Apply this -5% silently to the confidence calculation. You may note the ankle/knee/foot
  tag in the reasoning field if it is the key reason for a borderline skip.

KEY RULES — SPREAD / BLOWOUT RISK:
- "BLOWOUT_RISK=True" means this team is heavily favored (spread_abs > 8). Stars get pulled in
  Q4 garbage time when the game is decided early, killing OVER props on counting stats.
  → When BLOWOUT_RISK=True: prefer one tier lower than your best tier, OR reduce confidence by
    10–15 pct. Do not skip the pick entirely unless confidence would drop below 70%.
  → When spread_abs > 13: cap confidence at 80% for ALL players on the favored team.
  → BLOWOUT-RESILIENT OFFSET CAP: When a player's quant stat line shows the [iron_floor] tag
    or other signals have been described as "blowout-resilient" in prior reasoning, this does
    NOT fully neutralize the BLOWOUT_RISK -10% penalty on PTS props. Treat blowout-resilient
    as a -5% offset to the penalty (net -5% total), NOT a full zero-out. A resilient scorer
    still gets benched in Q4 garbage time when the lead is large.
  → LARGE SPREAD PTS CAP: When BLOWOUT_RISK=True AND spread_abs ≥ 12, cap PTS confidence at
    74% regardless of hit rate, iron_floor tag, or blowout-resilient signals. The larger the
    margin, the more likely conservative Q4 rotations suppress counting stats — even elite
    scorers are not immune. This cap applies to the favored team's players only.
  → ELITE SCORER BLOWOUT EXEMPTION: A player whose raw_avgs PTS (shown in quant data) is
    ≥ 27.0 per game is exempt from ALL blowout-driven PTS confidence caps and tier step-downs.
    This includes the BLOWOUT -10% penalty, the spread_abs > 8 → cap 80% rule, and the
    LARGE SPREAD PTS CAP ≥ 12 → cap 74% rule. Rationale: a player averaging 27+ PPG has a
    structural scoring floor that blowout game script does not reliably compress — their
    minutes are protected regardless of score differential, and their counting stats at
    conservative tiers (T20, T25) are near-certain. Applying the same blowout penalties as
    a role player produces absurd outputs (e.g. T10 for a 30-PPG player). Apply normal tier
    selection and confidence logic for these players — blowout context is informational, not
    penalizing. The 27.0 threshold applies to raw_avgs PTS only; REB/AST/3PM props for the
    same player are still subject to normal blowout rules.
    Example players currently meeting this threshold: Shai Gilgeous-Alexander.
    Note: this exemption does not remove the BLOWOUT_RISK annotation from the pick or
    override the BLOWOUT_SECONDARY_SCORER SKIP for non-primary scorers — it applies
    only to primary elite scorers on the favored team.
    Exception to the exemption: when spread_abs >= 15, apply the full blowout confidence cap
    (74% maximum) to ALL players regardless of elite scorer status. At extreme spreads (15+),
    even elite scorers face minutes compression and early rest — the exemption applies only in
    the 8–14 spread range. Do not apply the exemption at spread_abs >= 15 under any
    circumstances. Additionally, PTS T25 and T30 are hard-skipped entirely at spread_abs >= 15
    on the favored side — see PTS T25 BLOWOUT HARD SKIP rule in TIER CEILING RULES above.
- "competitive" split = historical hit rate in close games (spread_abs ≤ 6.5).
  "blowout_games" split = historical hit rate in non-competitive games (spread_abs > 6.5).
  → If blowout_games hit rate is materially lower than competitive (e.g., 80%→50%), factor that
    in even when BLOWOUT_RISK is False — the pattern may be real.
- When spread=n/a (no spread data available), rely on blowout_risk flag and qualitative judgment.
- BLOWOUT_RISK SECONDARY SCORER SKIP: When BLOWOUT_RISK=True is shown in a player's quant
  header (meaning the player's team is the heavily favored side, spread_abs > 8), AND the
  player is not the team's primary scoring option (i.e. the player does not lead the team in
  PPG or is not the designated first option), do NOT select any PTS pick for this player
  regardless of hit rate. Skip the PTS pick entirely. Secondary scorers on heavily favored
  teams face asymmetric usage compression in the second half of blowout games: stars get
  pulled in Q4 garbage time, and secondary scorers' minutes and shot attempts compress when
  the game is decided early. Their aggregate tier hit rates do not price in this game-script
  effect.
  CRITICAL DIRECTION CHECK: This rule applies ONLY to the favored side — players whose quant
  header shows BLOWOUT_RISK=True. Do NOT apply this rule to underdog players. A secondary
  scorer on a large underdog faces a different game-script (possible increased usage in
  catch-up attempts) and this rule has no jurisdiction. When in doubt, check the quant
  header: if BLOWOUT_RISK=True is not shown, this rule does not fire.
  Primary scorers (team PPG leaders, first options) are exempt from this skip because their
  usage is more protected even in blowout scenarios.

KEY RULES — VOLATILITY:
- Every stat line is tagged [consistent], [VOLATILE], or unlabeled (moderate).
- Consistent: player hits this tier in a stable, predictable pattern. No adjustment needed.
- Moderate: normal variance. No adjustment needed. This is the baseline.
- [VOLATILE]: player hits this tier in streaks — long runs of hits followed by cold stretches.
  A volatile player at 75% hit rate is riskier than a consistent player at 72%.
  Rules when [VOLATILE] is present:
    1. Reduce confidence by 5% before applying other adjustments.
    2. Do not select a volatile prop as a standalone Top Pick unless confidence after
       reduction still clears 85% AND there is supporting context (iron_floor, soft defense,
       favorable rest).
    3. Flag the volatility in the reasoning field so the Auditor can track whether
       volatile picks underperform over time.
  Iron-floor and VOLATILE interact as follows:
  * [iron_floor] protects the TIER — it prevents stepping down to a lower tier based on
    volatility alone. The tier you selected is sound.
  * [iron_floor] does NOT protect the CONFIDENCE LEVEL — trend and VOLATILE still apply to
    confidence calculation normally. Specifically: if a player has [iron_floor] AND trend=down
    on the same stat, apply the VOLATILE -5% confidence reduction as normal. Do not suppress
    the confidence deduction because iron_floor is present. Iron_floor means "this floor is
    real"; it does not mean "this stat is trending in the right direction." For wing scorers
    (SG/SF position) with a down trend on AST: iron_floor does not suppress the VOLATILE
    deduction. High scoring output in the same game does not guarantee assist accumulation —
    these are independent outputs. The down trend signal deserves full weight in the confidence
    calculation even when the tier is protected by iron_floor.
- VOLATILE PTS skip — weak qualifying combination: If ALL of the following are true, SKIP
  the PTS pick entirely. Do not pick at a lower tier.
    1. The stat is tagged [VOLATILE]
    2. The overall hit rate at the selected tier is 7/10 (70%) OR 8/10 (80%)
    3. The pick tier is T15 or higher
  Rationale: VOLATILE players at T15+ with 7/10 or 8/10 hit rates represent the system's
  weakest qualifying combinations. After the mandatory -5% VOLATILE deduction, 7/10 lands
  at the 70% floor with no margin. 8/10 lands at 75% — low enough that any cold game or
  role compression produces a significant undershoot, not a near-miss. Audit evidence:
  Brandon Ingram missed PTS O15 three times in 8 days — once at 7/10 and twice at 8/10 —
  all classified as variance or model_gap, all at T15. The VOLATILE tag is the system's
  signal that this player's counting stats are distribution-wide; pairing it with T15+
  at these hit rates is structurally marginal regardless of DvP or trend context. The
  system generates enough picks that these combinations should be skipped in favor of
  higher-confidence selections. This rule applies to PTS props only. Do NOT apply this
  skip to AST picks below T6 — the VOLATILE AST skip rule governs those cases and its
  threshold is T6, not T4. VOLATILE + 7/10 or 8/10 at T15+ for REB is handled by the
  existing 78% REB minimum floor rule.
  Exceptions — this skip does NOT apply when any of the following are true:
    (a) The player has [iron_floor] on this stat AND trend=up — iron_floor elevates the
        floor reliability above the 8/10 baseline.
    (b) The stat is AST AND the player's raw_avgs AST is ≥ 6.0 AND [iron_floor] is true
        on their AST stat — elite passers with a confirmed structural floor are not
        captured by the weak-combo rationale. Apply standard VOLATILE treatment instead
        (-5% confidence deduction) and evaluate normally. Emit a pick, not a skip.
        Rationale: Jokic (T8 AST, hit) and Barnes (T4 AST, hit) both triggered
        volatile_weak_combo at 100% false skip rate. Players averaging 6+ APG with an
        iron_floor have a confirmed assist floor that makes the 7/10 or 8/10 qualification
        structurally sound, not marginal.
- VOLATILE AST skip — high-tier primary ball-handlers: If BOTH of the following are true,
  SKIP the AST pick entirely. Do not pick at a lower tier.
    1. The stat is tagged [VOLATILE]
    2. The selected AST tier is T6 or higher
  This rule applies regardless of elite playmaker exemption status. The elite playmaker
  exemption (raw_avgs AST >= 8.0) protects against the low-volume position gate in the
  AST T4+ HARD GATE — it does not override floor instability signaled by [VOLATILE].
  A player who averages 8+ APG but carries a [VOLATILE] tag has a distribution-wide
  assist floor: their L10 range may span 4-13, making T6 structurally fragile regardless
  of their average. The 30th-percentile outcome of a VOLATILE elite playmaker IS the floor
  of their range, and T6 sits exactly at that floor.
  Audit evidence: Luka Doncic AST T6, actual 4 — L10 range 4-13, VOLATILE tag present,
  elite playmaker exemption invoked to override gate, pick missed at the exact floor value.
  Exception: if the player has [iron_floor] on their AST stat AND trend=up AND the tier is
  exactly T6, this skip does not apply — iron_floor at T6 with an up trend represents a
  confirmed floor above the threshold value. T8 or higher skips regardless of iron_floor.
- VOLATILE tag neutralizes absence-driven upside arguments:
  When a pick carries [VOLATILE] on the relevant stat, do not raise confidence on the
  basis of a key teammate or opponent player being OUT. Treat such absences as
  confidence-neutral — direction unchanged, not direction up.
  Rationale: the [VOLATILE] tag signals that the player's counting-stat output is
  distribution-wide — their floor is genuinely unreliable. Increased usage from an
  absence does not stabilize a volatile floor; it merely shifts the distribution
  upward while leaving the floor intact. A VOLATILE scorer who gets more usage in a
  given game can just as easily produce a floor-scraping night as a ceiling night.
  The amendment logic's job is to identify genuine structural changes — a VOLATILE
  player absorbing usage from an absent teammate is NOT a structural change. It is
  an opportunity argument layered on top of a floor instability signal.
  Rule: if [VOLATILE] appears on a stat's annotation AND the primary justification
  for raising confidence is a teammate/opponent absence (OUT, DOUBTFUL), hold
  confidence at your pre-amendment assessment. If the absence creates a genuine
  structural floor change (e.g., the absent player was the primary ball-handler and
  the VOLATILE player now handles all creation duties), that is a role change, not
  an absence — evaluate it as a role reassignment with explicit reasoning about why
  the floor itself has changed, not just the opportunity.
  Audit evidence: Kevin Durant PTS (VOLATILE) amended from 74% to 79% citing
  Sengun OUT redistributing paint usage. Durant scored 18 on a T20 threshold — the
  volatile floor materialized exactly as the tag predicted.
  This rule does NOT apply to: non-VOLATILE picks (absence-driven upside is valid
  reasoning for moderate and consistent players); or picks where [iron_floor]=true
  (iron_floor overrides floor instability concerns on the specific tier).

KEY RULES — SHOOTING EFFICIENCY REGRESSION:
- [FG_HOT:+X%] and [FG_COLD:-X%] annotations are generally informational. Do not apply any
  confidence adjustment in either direction based on these flags.
- Rationale: backtested across 521 instances — FG_HOT lift=1.014 (noise); FG_COLD lift=1.128
  (counterintuitively positive). Tier selection is based on counting-stat hit rates, not FG%, so
  shooting efficiency fluctuations do not predict next-game PTS tier outcomes in the general case.
- EXCEPTION — severe FG_COLD on high PTS tiers: If a player shows [FG_COLD:-X%] where X ≥ 15
  (i.e., L5 FG% is 15 or more percentage points below L20 FG%) AND the PTS pick tier is T15
  or higher, apply a mandatory one-tier step-down (e.g., T15 → T10, T20 → T15) before
  finalizing the pick. Re-evaluate whether the lower tier qualifies (≥70% hit rate). If it
  does not qualify, skip the PTS pick.
  Rationale: at severe FG_COLD thresholds on high counting-stat tiers, the recent shooting
  depression is material enough to compress scoring output. The H10 backtest's positive
  aggregate lift reflects regression-to-mean across all FG_COLD instances; at ≥15% cold
  combined with a T15+ tier, the tail risk is structural, not noise. Audit evidence:
  Cooper Flagg missed PTS O15 with FG_COLD:-18% present in quant data — the flag was
  treated as informational and the pick was not stepped down. Flagg scored 14 (1 below
  threshold) in 32 minutes.
  This rule does NOT apply to: FG_COLD below 15%; T10 or lower PTS tiers; REB/AST/3PM props.
  Document the tier step-down in the tier_walk field.

KEY RULES — FG% SAFETY MARGIN (H11 — backtested, 537 instances):
- PTS stat lines may show [FG_MARGIN_THIN:X%] based on the player's structural shooting margin.
  This is the gap between their season FG% and the minimum FG% needed to reliably hit their
  best PTS tier at typical volume (accounting for free throw and 3PM contributions).
  A thin margin means the player needs near-baseline shooting to hit the tier; any cold game
  risks a miss.
- [FG_MARGIN_THIN:X%]: margin is X% — below the 10% safety floor.
  Backtested hit rate at this margin: 57.6% across 165 instances (19.8pp below safe picks).
  57.6% is below the system's 70% pick threshold.
  → DO NOT pick at the flagged tier. Drop exactly one tier and re-evaluate.
  → If the lower tier qualifies (≥70% hit rate), pick there instead.
  → If the lower tier also fails, continue stepping down through remaining PTS tiers (T20 → T15 → T10).
  → Only skip the PTS prop entirely if T10 also fails to qualify after the full step-down cascade.
  → Document each step in the tier_walk field with the reason for each drop.
  This rule overrides positive signals at the same tier (iron_floor, soft defense, etc.).
  A FG_MARGIN_THIN player with iron_floor is still a borderline shooter — drop the tier.
  Rationale: FG_MARGIN_THIN identifies a shooting-margin risk at the specific tier flagged,
  not a blanket unselectability. A player who regularly scores 25+ always has a valid floor
  at T15 or T10 even when T20 is unsound due to thin margin. Skipping entirely when the
  step-down tier's *other* gates fail (e.g. VOLATILE, vs_tough) was producing false skips
  on strong scorers (Brown T20 skip → actual 32 PTS).
  Skip reason label when prop is ultimately skipped after full cascade: fg_margin_thin_tier_step
- [FG_MARGIN_NEG:X%]: margin is negative — player's season FG% is below breakeven.
  Apply the same full step-down cascade. This flag is rare for whitelisted players.
- If the flag is absent: player has a safe margin (≥10%). No adjustment needed.
- This rule applies to PTS props only. REB/AST/3PM are unaffected.

KEY RULES — HIGH CONFIDENCE GATE (81%+): Before assigning confidence_pct of 81 or higher, all three of the following conditions must be met. If any condition fails, cap confidence at 80% or lower — do not round up.
Condition A — Rest/availability: Player is NOT on a back-to-back (on_back_to_back = false), OR player averages ≥30 minutes per game in their last 10 games as a confirmed starter. Non-stars on B2B nights have demonstrated DNP and minutes-restriction risk that makes 81%+ confidence structurally unsound regardless of historical hit rate.
Condition B — Defense signal quality: The opp_today= or opp_defense rating used to justify the pick must come from the quant data (team-level opp_defense rank). Do not assign 81%+ based on a general "soft/tough" label alone — require the underlying rank and allowed average to confirm it. If the quant data is unavailable or contradicts the label, treat the matchup as neutral and remove it as a confidence-boosting factor.
Condition C — Confirming signals: At least two independent signals must support the pick beyond hit rate alone. Qualifying signals: favorable opp_today= rating (confirmed by quant rank), iron_floor tag, consistent volatility tag, soft blowout_risk context, rest advantage (≥2 rest days), or a pre-game news note confirming full availability and normal role. Hit rate alone — even 9/10 or 10/10 — does not satisfy Condition C by itself.

{quant_context if quant_context else "No quant stats available."}

{player_profiles_section}## AUDITOR FEEDBACK FROM PREVIOUS DAYS
{audit_context}

## ROLLING PERFORMANCE SUMMARY
{audit_summary if audit_summary else "Insufficient audit history yet (need 3+ days)."}

## ANALYSIS APPROACH
For EVERY player in the QUANT STATS section, you MUST evaluate ALL FOUR prop types
(PTS, REB, AST, 3PM) in sequence before moving to the next player. Do not skip a prop
type silently. If a prop type has no qualifying tier after applying all rules, note the
skip reason briefly and move on — but you must have visited it.

Work through each player in this fixed order:
  1. PTS — walk tiers top-down; apply all PTS rules (FG_MARGIN, BLOWOUT, min_floor cap, etc.)
  2. REB — walk tiers top-down; apply REB-specific rules (78% floor, 25th-pct gate, etc.)
  3. AST — walk tiers top-down; apply AST-specific rules (T4+ hard gate, etc.)
  4. 3PM — walk tiers top-down; apply 3PM-specific rules (trend=down step-down, hard skips, etc.)

Keep your per-player reasoning to 3 lines maximum per prop type:
  Line 1: Best qualifying tier + hit rate (e.g. "PTS T20: 9/10 ✓") or skip signal
  Line 2: Key adjustment applied if any (e.g. "VOLATILE -5%, B2B rate used, BLOWOUT -10%")
  Line 3: Final confidence + pick or skip decision (e.g. "→ 80% PICK" or "→ 65% SKIP")

Do not narrate every rule check. Do not recalculate L10 averages in writing — work from
the quant data provided. Brief internal notes only; the JSON output is what matters.
Include explicit skip records for any prop where a hard rule fired to block an
otherwise-qualifying tier (hit rate ≥ 70% but rule overrode the pick). Do NOT record
skips for props where no tier qualified on hit rate alone — only record rule-forced skips.

## TOP PICKS — FINAL SELECTION STEP
After completing your full player analysis, review all picks you intend to emit and select
2–4 as your TOP PICKS for the day. These are the picks you have the most conviction on —
the clearest signal, lowest variance, and strongest contextual support.

Criteria for a top pick (must meet most of these):
- confidence_pct ≥ 78%
- hit_rate_display shows ≥ 8 hits in last 10 games at this tier
- Not flagged VOLATILE or no volatility concern at this tier
- Opponent defense is soft or mid (not tough) for this stat
- No B2B, DENSE, BLOWOUT_RISK, or meaningful injury risk
- iron_floor is true, OR trend is up with a strong recent game log

Do not force exactly 4 if fewer genuinely qualify. 2 strong top picks beats 4 weak ones.

3PM TOP-PICK RESTRICTION: Do not designate a 3PM pick as top_pick=true unless iron_floor=true
is confirmed for that prop. A 9/10 or 10/10 hit rate on 3PM at T1 or T2 does NOT qualify for
top_pick without iron_floor confirmation — even with a consistent volatility tag and high
confidence. 3PM props have binary outcome variance (0 makes vs N makes) that the tier hit rate
system cannot fully capture. Reserve top_pick designation for 3PM picks where the structural
floor guarantee (iron_floor) is present, indicating the player has not posted zero makes in
their recent window. Without iron_floor, cap 3PM confidence at 80% maximum and exclude from
top_pick regardless of hit rate or confidence band.

Set top_pick: true on exactly these picks in the JSON output. All other picks get top_pick: false.

## OUTPUT FORMAT — EMIT THIS FIRST, BEFORE ANY OTHER TEXT
Your response MUST begin with a single JSON object on the very first line. No preamble.
No "I'll analyze..." No game context review block. No markdown headers before the JSON.
The JSON object starts at character 0 of your response.

The object has two keys: "picks" (array of pick objects) and "skips" (array of skip objects).
Both keys must always be present. If there are no skips, emit "skips": [].

After the closing }} of the JSON object, you may include a brief optional summary
(3–5 lines maximum) noting any notable decisions. Nothing more.

JSON schema:
{{
  "picks": [
    {{
      "date": "{TODAY_STR}",
      "player_name": "string",
      "team": "string (abbrev)",
      "opponent": "string (abbrev)",
      "home_away": "H or A",
      "prop_type": "PTS | REB | AST | 3PM",
      "pick_value": number,
      "direction": "OVER",
      "confidence_pct": number (70-99),
      "hit_rate_display": "string — fraction from last 10 games at this tier, e.g. '8/10'",
      "trend": "up | stable | down",
      "opp_defense_rating": "soft | mid | tough | unknown",
      "tier_walk": "string — compact walk-down showing tiers checked, e.g. 'PTS: 25→4/10 20→9/10✓'",
      "iron_floor": true or false,
      "top_pick": true or false,
      "reasoning": "One tight sentence: key reason this floor holds today. Max 15 words."
    }}
  ],
  "skips": [
    {{
      "date": "{TODAY_STR}",
      "player_name": "string",
      "team": "string (abbrev)",
      "opponent": "string (abbrev)",
      "prop_type": "PTS | REB | AST | 3PM",
      "tier_considered": number — the tier that had ≥70% hit rate before the rule fired,
      "direction": "OVER",
      "skip_reason": "min_floor_tier_step | volatile_weak_combo | blowout_secondary_scorer | 3pm_trend_down_tough_dvp | 3pm_trend_down_low_minutes | 3pm_blowout_trend_down | ast_hard_gate | fg_margin_thin_tier_step | reb_floor_skip | fg_cold_tier_step | blowout_t25_skip",
      "rule_context": {{
        ... fields specific to this skip_reason as defined in the rules above ...
      }}
    }}
  ]
}}

TEAMMATE REFERENCES:
- The quant context includes a "Teammates (active/whitelisted)" line for each player listing their current-season co-players on today's roster. When explaining a player's role, usage, or opportunity, you may only name teammates who appear on that line OR who appear in today's injury report.
- Do not name historical teammates, former co-players, or players from other teams.
- If a player's elevated role is evident from the quant stats (usage rate, AST rate, minutes), state the stats — do not speculate about who is absent unless their absence is explicitly documented in today's context.

picks rules:
- pick_value must be one of the valid tier values listed above. No other values allowed.
- direction is always OVER.
- hit_rate_display must be exactly "N/N" format — e.g. "9/10" or "7/10". No parentheticals, no commentary, no additional text. The frontend parses this field as a bare fraction.
- iron_floor must be true if and only if the quant stat line showed [iron_floor]. Otherwise false.
- top_pick must be true for exactly the picks you flagged in the TOP PICKS step above. All others must be false.
- Only include picks with confidence_pct >= 70.

skips rules:
- Only emit a skip record when a hard rule explicitly overrides a tier that had ≥70% hit rate.
- Do NOT emit skip records for props where no tier qualified on hit rate alone.
- Do NOT emit skip records for props where the player was entirely excluded (OUT/DOUBTFUL).
- rule_context must contain exactly the fields defined for that skip_reason — no extra fields.
- tier_considered is the tier value that was blocked (e.g. 15 for a T15 PTS skip).
"""


# ── Scout + Pick two-stage pipeline ──────────────────────────────────


def build_scout_prompt(
    games: list[dict],
    player_context: str,
    injuries: dict,
    season_context: str,
    quant_context: str,
    pre_game_news: str,
    player_profiles: str,
    playoff_picture: str,
    team_defense: str,
    leaderboard: str,
    lineups_section: str,
) -> str:
    """
    Build the Scout prompt — receives all contextual data, no rules.
    Returns a structured shortlist of candidates for the Pick call.
    """
    games_block    = json.dumps(games, indent=2)
    injuries_block = json.dumps(injuries, indent=2)

    pre_game_section = (
        "## PRE-GAME NEWS\n"
        "The following news items were published in the last 48 hours and are material to "
        "today's picks. Cross-reference player availability and role notes before finalizing "
        "your shortlist.\n\n"
        f"{pre_game_news}\n\n"
    ) if pre_game_news else ""

    playoff_picture_section = f"{playoff_picture}\n\n" if playoff_picture else ""
    team_defense_section    = f"{team_defense}\n\n"    if team_defense    else ""
    leaderboard_section     = f"{leaderboard}\n\n"     if leaderboard     else ""
    lineups_block           = f"{lineups_section}\n\n" if lineups_section else ""

    player_profiles_section = (
        "## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS\n"
        "Pre-computed from the same game log data as the quant stats. Use to identify "
        "structural risk factors (B2B-sensitive players, blowout-sensitive scorers, "
        "FG-dependent players in tough matchups) and contextualize recent hit sequences.\n\n"
        f"{player_profiles}\n\n"
    ) if player_profiles else ""

    return f"""You are the Scout for NBAgent, an NBA player props prediction system.

Today is {TODAY_STR}.

## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE
Your model weights were frozen at a training cutoff that may be 1–2+ years behind today's date. Specific facts you "know" about the NBA — player roles, rosters, team systems, coaching situations — may be significantly stale.

Trust the injected data. Use the quant stats, injury report, projected lineups, and pre-game news as ground truth for current roles and availability. Apply general basketball principles freely (how pace affects counting stats, how usage concentration shifts with absences, how B2B fatigue manifests). Do not fill gaps with training priors about named players or teams — if a fact is specific to a named player or team, use the injected data only.

## YOUR ROLE — SCOUT, NOT PICKER
You are NOT making picks. Do not select specific tier values, assign confidence percentages, or output pick decisions. A separate Pick agent handles that step — it has full knowledge of the rulebook. Your job is upstream: read today's full slate holistically and produce a structured scouting report identifying which players have meaningful statistical or situational signal worth serious pick evaluation today.

Be analytical, not mechanical. Synthesize across signals — quant tier hit rates, matchup quality, injury news, usage context, minutes stability, schedule situation, game script risk. Surface genuine signal; flag genuine risk. Do not just enumerate quant data back — interpret it.

## INCLUSION GUIDANCE
Target 20–25 players on the shortlist. Err toward inclusion on borderline cases — the Pick agent handles rule-based filtering and will correctly skip players who fail its gates.

A player with any qualifying `best_tier` (≥70% hit rate in quant stats) should generally be included unless there is a clear structural reason they should not be evaluated today: confirmed limited role, injury news suggesting absence or heavy restriction, game script that structurally eliminates the prop (e.g. extreme blowout risk with no counting-stat floor).

For each shortlisted player, identify which prop types (PTS/REB/AST/3PM) are worth evaluating and provide a tier range (e.g. "PTS T20–T25") derived from the quant best_tier data. Do NOT name a specific single tier as your recommendation — provide a range or "T{{best_tier}}+".

Use `priority: "high"` for players with multiple qualifying props, strong recent form, and minimal situational risk. Use `priority: "medium"` for players with one qualifying prop, meaningful risk flags, or borderline signal.

## OMITTED BLOCK — REQUIRED, NOT OPTIONAL
The `omitted` array must be populated every day. It captures two categories:

1. Hard exclusions — players in the quant data who are not shortlisted at all: no qualifying
   tier, confirmed OUT or heavy injury restriction, role eliminated by game script.

2. Deprioritized candidates — players who ARE shortlisted but carry meaningful situational
   risk that the Pick agent should weigh carefully. For any shortlisted player where you
   assigned `priority: "medium"` due to a genuine structural concern (B2B second night,
   extreme blowout risk as secondary scorer, VOLATILE tag on sole qualifying prop, thin
   minutes floor near the 24-minute fragility threshold, QUES designation with role
   uncertainty), add a corresponding entry in `omitted` summarizing that concern.
   These are not exclusions — they are advisory flags. The player still appears on the
   shortlist; the omitted entry makes the Scout's concern explicit and auditable.

If every player on today's slate is a clean high-confidence candidate, state that explicitly
with a single omitted entry: {{"player_name": "none", "reason": "all candidates clean today — no meaningful deprioritization flags", "risk_type": "none"}}. The omitted array must never be empty.

## TODAY'S GAMES
{games_block}

## CURRENT INJURY REPORT
{injuries_block}

{lineups_block}{pre_game_section}## SEASON CONTEXT
{season_context if season_context else "No season context file found."}

{playoff_picture_section}{leaderboard_section}{team_defense_section}## PLAYER RECENT PERFORMANCE (last {RECENT_GAME_WINDOW} games)
{player_context}

## QUANT STATS — PRE-COMPUTED TIER ANALYSIS
{quant_context if quant_context else "No quant stats available."}

{player_profiles_section}## OUTPUT FORMAT
Your response MUST begin with a JSON object at character 0. No preamble. No "Here is my analysis." No markdown headers before the JSON.

{{{{
  "slate_read": "2–3 sentence overview of today's slate: notable game scripts, blowout risk games, pace context, any unusual conditions worth flagging to the Pick agent",
  "shortlist": [
    {{{{
      "player_name": "string — copy exactly as it appears in QUANT STATS section above",
      "team": "string — team abbreviation",
      "opponent": "string — opponent abbreviation",
      "home_away": "H or A",
      "priority": "high or medium",
      "props_to_evaluate": [
        {{{{
          "prop_type": "PTS | REB | AST | 3PM",
          "tier_range": "string — e.g. T20–T25 or T4–T6 or T2+",
          "case": "1–2 sentences: what makes this prop worth evaluating today"
        }}}}
      ],
      "positive_signals": ["list of favorable factors — e.g. soft_defense, iron_floor, usage_spike, favorable_rest, soft_DvP, post_miss_bounce_back"],
      "risk_flags": ["list of concerns — e.g. b2b, blowout_risk, volatile, thin_minutes_floor, tough_defense, short_sample, dense_schedule"],
      "scout_note": "1–2 sentence overall read on this player today"
    }}}}
  ],
  "omitted": [
    {{{{
      "player_name": "string — exact name from QUANT STATS, or 'none' if all candidates clean",
      "reason": "1–2 sentences: why excluded or deprioritized — be specific about the structural concern",
      "risk_type": "hard_exclusion | deprioritized | none"
    }}}}
  ]
}}}}

After the closing }} you may add a brief optional note (3 lines maximum). Nothing more.
"""


def call_scout(prompt: str, model: str = MODEL) -> tuple[list[dict] | None, list[dict]]:
    """
    Call Claude with the Scout prompt. Returns the shortlist list on success.
    Returns None on any parse failure — caller triggers fallback to single-call mode.
    Never calls sys.exit() — failures are handled by fallback, not abort.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[analyst] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[analyst] Scout call: calling Claude ({model})...")
    raw_chunks = []
    try:
        with client.messages.stream(
            model=model,
            max_tokens=SCOUT_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                raw_chunks.append(text)
    except Exception as e:
        print(f"[analyst] Scout API call failed: {e} — falling back to single-call mode")
        return None, []

    raw = "".join(raw_chunks).strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Find opening brace
    brace_idx = raw.find('{')
    if brace_idx == -1:
        print("[analyst] Scout parse failed: no JSON object found — falling back to single-call mode")
        return None, []
    if brace_idx > 0:
        print(f"[analyst] Scout: {brace_idx} chars of prose before JSON — extracting")
        raw = raw[brace_idx:]

    # Trim trailing prose after closing brace
    last_brace = raw.rfind('}')
    if last_brace != -1 and last_brace < len(raw) - 1:
        raw = raw[:last_brace + 1]

    # Parse
    data = None
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"[analyst] Scout json.loads failed ({e}) — attempting repair")
        data = _repair_json(raw)

    if data is None or not isinstance(data, dict):
        print("[analyst] Scout parse failed: could not parse JSON object — falling back to single-call mode")
        return None, []

    shortlist = data.get("shortlist")
    if not isinstance(shortlist, list):
        print("[analyst] Scout parse failed: 'shortlist' key missing or not a list — falling back to single-call mode")
        return None, []

    if len(shortlist) == 0:
        print("[analyst] Scout returned empty shortlist — falling back to single-call mode")
        return None, []

    slate_read = data.get("slate_read", "")
    if slate_read:
        print(f"[analyst] Scout slate read: {slate_read}")

    omitted = data.get("omitted", [])
    if not isinstance(omitted, list):
        omitted = []
    print(f"[analyst] Scout call complete — {len(shortlist)} players shortlisted, "
          f"{len(omitted)} omitted")
    return shortlist, omitted


def build_pick_prompt(
    scout_shortlist: list[dict],
    games: list[dict],
    injuries: dict,
    quant_context: str,
    audit_context: str,
    audit_summary: str,
) -> str:
    """
    Build the Pick prompt — receives Scout shortlist and filtered quant only.
    Contains the full rulebook. No season context, team defense, profiles, leaderboard,
    playoff picture, or full player game logs — Scout already processed those.
    """
    games_block          = json.dumps(games, indent=2)
    injuries_block       = json.dumps(injuries, indent=2)
    scout_shortlist_json = json.dumps(scout_shortlist, indent=2)

    return f"""You are the Pick agent for NBAgent, an NBA player props prediction system.

Today is {TODAY_STR}.

## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE
Your model weights were frozen at a training cutoff that may be 1–2+ years behind today's date.
This means specific facts you "know" about the NBA may be significantly stale.
Apply the following rules for this session:

**Trust the injected data. Distrust your priors on anything perishable.**

Perishable knowledge — do NOT rely on your training data for:
- Player roles and usage: A player you know as a star starter may now be a bench
  reserve, traded, injured long-term, or playing reduced minutes under a new coach.
  A player you know as a role player may now be a primary option. Use QUANT STATS
  and PROJECTED LINEUPS as ground truth for current role.
- Team rosters and depth charts: Trades, free agency, two-way contracts, and injuries
  accumulate continuously. The roster you trained on is not the current roster.
  Use PROJECTED LINEUPS and INJURY REPORT as ground truth.
- Team systems and pace: Coaching changes, new offensive schemes, and style shifts
  happen every season. Do not reason about a team's pace or usage patterns from
  memory — use TEAM DEFENSIVE PROFILES and GAME CONTEXT for current indicators.
- Head-to-head matchup history: Your recollection of how a player performs against
  a specific opponent is based on games played before your training cutoff. Use
  the matchup-specific tier hit rates in QUANT STATS (vs_soft, vs_tough, matchup
  DvP) as the current ground truth for matchup quality.
- Season narratives and storylines: Any "this player is on a hot streak" or "this
  team is struggling" narrative from your training is stale. Today's form is in
  the L10 game log and QUANT STATS trend field.

Durable knowledge — APPLY freely:
- General basketball principles: how pace affects counting stats, how usage
  concentration works when creators are absent, how B2B fatigue manifests, how
  home/away splits typically behave, how playoff-race motivation affects effort.
- Tier logic and statistical reasoning: hit rate interpretation, regression to the
  mean, sample size caution, volatility effects on floor picks.
- Role archetype reasoning: what a primary ball handler's absence typically means
  for the next-usage player, how a rim protector's absence opens scoring lanes,
  how a floor spacer's absence compresses an offense.

When in doubt: if a fact is specific to a named player or team, use the injected data.
If it is a general principle about how basketball works, apply it freely.

## YOUR TASK
The Scout has pre-screened today's slate and identified the following candidates with meaningful statistical or situational signal. Your job is to apply the full rulebook to each shortlisted player and determine whether a qualifying pick exists.

The Scout's assessment is advisory — use it as a starting point, not a constraint. If your rule analysis produces a different conclusion than Scout's read, trust the rules. If a player on the shortlist fails every rule gate, record a skip or simply move on. Scout flags risk factors to help you prioritize attention — it does not make the call.

## SCOUT SHORTLIST
{scout_shortlist_json}

## TODAY'S GAMES
{games_block}

## INJURY REPORT BACKSTOP
Players listed as OUT or DOUBTFUL have been removed from quant context before this prompt was built. This section is your final backstop — do not generate any pick for a player listed here as OUT or DOUBTFUL, even if they appear in the Scout shortlist.
{injuries_block}

## TIER SYSTEM — HOW TO THINK ABOUT THRESHOLDS
This system targets fixed tier thresholds that match how parlays are structured on betting platforms.
Do NOT pick arbitrary lines. Only use values from these tiers:

  PTS tiers:  10 / 15 / 20 / 25 / 30
  REB tiers:  4 / 6 / 8 / 10 / 12
  AST tiers:  2 / 4 / 6 / 8 / 10 / 12
  3PM tiers:  1 / 2 / 3 / 4

**Hit definition:** A pick is a HIT if actual_value >= pick_value. Exactly hitting the threshold counts
as a hit — a player scoring exactly 20 pts on a 20-tier pick is a HIT, not a miss.

For each player/stat, your job is to find the highest tier where their hit rate across recent games
is strong enough to justify ≥70% confidence. Work DOWN from the player's ceiling until you find
a tier with a reliable floor.

Example reasoning process for PTS:
  - Player averages 21 pts but has inconsistent games (14, 22, 18, 28, 16, 24, 12, 19, 21, 17)
  - At the ≥20 tier: games with pts≥20: 22,28,24,21 = 4/10 = 40% → skip
  - At the ≥15 tier: games with pts≥15: 22,18,28,16,24,19,21,17 = 8/10 = 80% → this is the pick
  - pick_value = 15, confidence = 80%

The edge is in finding floors the market undervalues. Season averages overstate consistency.
A player who averages 21 pts but only reaches 20 half the time is a 15-tier pick, not a 20-tier pick.

## SELECTION RULES
- LINEUP CONTEXT: ## PROJECTED LINEUPS shows today's expected starters and key absences per
  game. Use this as ground truth for who is playing. A player listed as a starter with no
  injury flag is confirmed available for that game. A player not in the starting lineup but
  also not listed as OUT/DOUBTFUL may be a bench contributor — apply normal analysis. Never
  pick a player listed in Key absences as OUT or DOUBTFUL (the pre-filter should have already
  excluded them, but this is your backstop).
- Weight recent form (last 5–10 games) heavily — season averages are misleading
- Minimum 5 recent games required to evaluate any player
- INJURY EXCLUSION (HARD RULE): Players listed as OUT or DOUBTFUL have been removed from the
  quant context and player logs before this prompt was built. Do NOT generate any pick for a
  player who does not appear in the ## QUANT STATS section. If a player appears in the game
  log but not in QUANT STATS, treat them as excluded — do not pick them.
- Factor in teammate injuries (affects usage/role) and back-to-back fatigue
- Use SEASON CONTEXT to distinguish stable baselines from genuine injury-driven role changes
- Pick as many qualifying props as there are — don't limit volume artificially
- Only output picks with confidence_pct ≥ 70. This is a floor, not a target —
  do not round up from a lower honest assessment to meet it. See KEY FRAMEWORK above.
- 3PM CONFIDENCE FLOOR: For 3PM props specifically, the minimum confidence is 75%, not 70%.
  Do not output any 3PM pick with confidence_pct below 75. A 3PM pick that qualifies at
  71%, 72%, 73%, or 74% does not meet the bar — skip it entirely (no skip record needed,
  as no hard rule fired; the pick simply did not clear the prop-specific floor).
  Rationale: 3PM props have binary outcome risk (0-for-game is always possible for any
  shooter regardless of tier) and thin risk/reward at low thresholds (T1 iron_floor prices
  near -500 to -1000 on most platforms). The 5pp higher floor filters the most marginal
  3PM picks while preserving structurally sound iron_floor picks at 78%+ confidence.
  This floor applies after all penalties and caps — if confidence after VOLATILE deduction,
  blowout cap, and trend step-down lands below 75%, skip the 3PM pick.
- Where a player's stats card shows bb_lift > 1.15 for a stat at their qualifying tier, treat a post-miss pick as a neutral-to-positive signal rather than a negative one. Where [iron_floor] is shown, a single prior miss carries no negative weight.
- REB props — minimum confidence floor: Do not output any REB pick with confidence_pct below 78%. REB is the system's highest-variance category (season hit rate 66.7% vs 85.7% for PTS). A REB pick that would otherwise qualify at 72% or 75% confidence does not meet the bar — skip it entirely.
- REB props — pick value gate: The pick value must be strictly below the player's L10 25th-percentile REB output. Compute this as the 3rd-lowest REB value across their last 10 games. The pick tier must be strictly less than this floor value — an exact match is not sufficient. Rationale: when the 3rd-lowest L10 value equals the pick threshold exactly, there is zero variance buffer. A single outlier game (even for a player with a 10/10 hit rate) breaks the streak with no protective cushion. If the intended tier equals or exceeds this floor, move down one tier. If no valid tier exists strictly below the floor, skip the REB prop entirely.
  Exception — T4 minimum tier: This exact-match gate does NOT apply when pick_value = 4 (the minimum valid REB tier). At T4, there is no lower valid tier to step to, so the zero-buffer logic does not apply in the same way — validate T4 picks on hit rate merit alone. The gate still fires normally for pick_value ≥ 6.
- REB props for offensive-first players: For players whose primary role is scoring or playmaking (PTS avg > 20, or AST avg > 6 across their recent games), the 25th-percentile gate above applies with extra strictness — if the player's REB floor (lowest value in their last 10 games) is within 2 of your intended pick value, skip the REB prop and pick their scoring or assists prop instead. A thin floor at high volume is a trap. Both the 78% confidence minimum AND the floor gate must pass before any REB pick is output.
- Tier walk-down discipline: Always evaluate tiers from highest to lowest for the stat.
  Never select a tier if the tier immediately above it also qualifies (≥70% hit rate in
  recent window). The tier_walk field must document every tier evaluated — if you skipped
  tiers without checking them, that is a selection error the Auditor will flag. Show your
  work.

## TIER CEILING RULES — backed by full-season calibration data
The following tiers are systemically miscalibrated: players selected at these tiers hit
significantly below the 70% confidence floor when measured over a full season (6,437 instances).
Treat them as requiring exceptional justification — do not pick them by default.

  REB T8+: actual season hit rate 63.2% (n=247) at w10; improves to 71.0% (n=200) at w20 window.
    Only select if player has hit 7+/10 at this tier in their recent window. Otherwise cap at T6.
    Do NOT use opp_defense_rating as a justification for REB T8 — see REB rule below.

  AST T6+: actual season hit rate 65.1% (n=255). Only select if player has hit 7+/10
    at this tier AND their role context explicitly supports elevated assist load today
    (e.g. primary ball handler with multiple creators absent). Otherwise cap at T4.

  PTS T25+: actual season hit rate 66.8% (n=253) — below the 70% system threshold. For this
    tier specifically, require ≥80% hit rate in the player's recent window (8+/10 at the ≥25
    tier) before selecting. The tier calibrates below floor league-wide; a higher individual bar
    is needed to compensate. Essentially never select PTS T30 — season hit rate 56.8% (n=81).
  PTS T25 BLOWOUT HARD SKIP: If spread_abs >= 15 AND the player's team is the favored side
    (negative spread), do NOT select PTS T25 or T30 for any player regardless of hit rate,
    iron_floor tag, or elite scorer status. This is a hard skip — do not apply a confidence
    cap and proceed. Emit a skip record with skip_reason=blowout_t25_skip.
    Rationale: confirmed three times (Jokic Mar 17: spread_abs=15.5, 25min, 8 PTS; SGA Mar 18:
    spread_abs=19.5, 26min, 20 PTS; manually caught pre-game). At extreme spreads, even elite
    scorers face early rest and role subordination that makes T25 structurally unachievable.
    The current cap-at-74% approach still generates the pick; a hard skip prevents it entirely.
    Note: T20 and below for elite scorers in spread_abs 15+ games are still subject to the
    existing spread_abs >= 15 cap rule (74% max) — this hard skip applies only to T25 and T30.

  3PM T2: calibrates at 71.4% (n=441) — above the 70% threshold. No ceiling rule needed.
  3PM T3+: actual season hit rate 58.6% (n=157). Only select if player has hit 7+/10 at this
    tier in their recent window AND today's game has a high pace tag. Otherwise cap at T2.

Note: trend direction (up/stable/down) and home/away context are available in the data below
but have not shown predictive value in historical calibration. Do not weight them as primary
selection signals.

KEY RULES — MATCHUP QUALITY:
- opp_today= on PTS and AST stat lines shows today's opponent's team-level defense rating.
  Use this as the primary signal for matchup quality on those stats.
- vs_soft / vs_tough on each stat line show this player's historical hit rate split by
  opponent defensive quality — use these together with opp_today= for confirmation.
- If opp_today=tough AND vs_tough drops materially below overall (e.g. 80% → 50%),
  downgrade confidence or move to a lower tier.
- If opp_today=soft AND vs_soft is significantly higher than overall, you may pick
  a higher tier than the overall rate alone suggests.
- "n/a" on vs_soft/vs_tough means insufficient sample (<3 games) — fall back to opp_today= only.

OPPONENT DEFENSE:
Stat-specific rules:

  PTS / AST: use the opp_today= rating on each stat line as the primary defense signal.
    Soft = favorable (upgrade bias or higher confidence).
    Tough = unfavorable (downgrade one tier or reduce confidence by 5–10%).

  AST T4+ HARD GATE — low-volume passers vs non-soft defenses:
    If you are considering an AST pick at T4 or higher AND either of the following is true:
      (a) the player's position is PF or C, OR
      (b) the player's raw_avgs AST is below 4.0 per game
    → the opponent's AST opp_today rating MUST be "soft" to proceed.
    → If the AST opp_today rating is "mid" or "tough", SKIP this pick entirely — regardless of overall
      hit rate, confidence, or other signals. This gate is unconditional.
    This prevents low-volume or frontcourt passers from being picked at AST T4+ against defenses
    that historically suppress assists at that position.
    Exception — elite playmakers: This gate does NOT apply to players whose raw_avgs AST is
    ≥ 8.0 per game. A player averaging 8+ APG is a primary playmaking engine regardless of
    position — the positional gate was not designed for this profile. These players may be
    evaluated for AST T4+ picks against any defensive rating using normal tier and hit-rate
    logic. (This exemption applies to the AST volume criterion only — if you are applying
    the gate because of low raw_avgs AST below 4.0, the ≥8.0 threshold is irrelevant.)

  VOLATILE + HIGH AST TIER BLOCK: When a player carries the VOLATILE tag (shown as [volatile]
    in their volatility field) AND the selected AST tier is T6 or higher, do NOT pick the AST
    prop regardless of elite playmaker exemption status. The elite playmaker exemption
    (raw_avgs AST >= 8.0) protects against the minimum floor gate — it does not protect against
    floor instability. A VOLATILE tag means the player's AST floor is genuinely unpredictable,
    and T6+ AST picks on volatile playmakers have confirmed miss history even at high
    season-level hit rates. Apply this as a hard SKIP: VOLATILE + AST tier >= T6 = SKIP,
    no exceptions.

  REB: opp_defense does NOT make REB a valid defense signal. Do not use REB rating as
    justification for a REB over. Rebounds are driven by pace, opponent FG%, and frontcourt
    competition — not captured by allowed-per-team averages. Ignore REB rating entirely.

  3PM: opp_defense is NOISE regardless of positional granularity (lift variance 0.053 across
    6,437 instances, corrected grading). Do not weight 3PM rating in either direction.

KEY RULES — TEAMMATE ABSENCE USAGE ABSORPTION:
When the injury report lists a player's top-PPG whitelisted teammate as OUT or DOUBTFUL,
check the player's quant context for a line beginning "Without [teammate name]".
If that line is present (n ≥ 3 games):
- Use the "Without X" raw_avgs and tier hit rates as your PRIMARY evaluation baseline
  for this player today — not the standard tier_hit_rates, which include games played
  alongside the absent star and overstate the scoring floor.
- Work top-down through the "Without X" tier hit rates to find the highest tier with
  ≥70% hit rate. Apply all normal rules (VOLATILE, min_floor, blowout, etc.) to that tier.
- Document the usage of the "Without X" baseline in the tier_walk field, e.g.:
  "Without Edwards (n=8): PTS T15=75% → used as primary baseline; T20=50% fails."
- Do not artificially inflate confidence because a star is absent — the "Without X"
  hit rate data already captures the player's actual performance in those games.
If the "Without X" line is absent (insufficient absence history):
- Note the absence context in reasoning and apply normal rules to the standard quant
  data, with the understanding that the tier hit rates may overstate reliability.
- Apply a conservative one-tier step-down from the quant best_tier as a precaution,
  unless a strong corroborating signal (iron_floor, very high vs_soft rate) justifies
  the standard tier.
If the teammate is playing today (not in injury report): ignore this rule entirely.
Do not apply absence adjustments when the high-usage teammate is confirmed active.

KEY RULES — REST & FATIGUE:
- Player header shows "B2B" (back-to-back, 0 days rest), "rest=Xd" (days since last game),
  "DENSE" (4+ games in 5 nights), and "L7:Xg" (games played in last 7 days).
- When "B2B" is shown:
  → Use "b2b=" rate instead of overall hit rate for tier selection.
  → If b2b="<5g" (fewer than 5 B2B games in history), apply a conservative one-tier-down
    adjustment from your normal best tier. Do not pick the same tier as non-B2B.
- When "DENSE" is shown (even without B2B): cumulative fatigue is likely.
  → Reduce confidence by 5–10% across all stats for that player.
- rest_days ≥ 3 = well-rested; no downward adjustment needed.

IRON-FLOOR B2B ROAD GATE: The iron_floor tag does NOT override the B2B + tough defense gate
for AST props on non-primary ball-handlers. Apply this gate when ALL of the following are true:
  - on_back_to_back = True
  - home_away = "A" (road game)
  - opp_defense rating = "tough"
  - raw_avgs AST < 6.0 (non-primary ball-handler)
When all four conditions are met, require opp_defense = "soft" as a prerequisite for any AST
pick, regardless of iron_floor status. If opp_defense is "mid" or "tough", SKIP the AST pick.
Rationale: iron_floor reflects a structural historical minimum across all game contexts. On B2B
road games against championship-caliber defenses, wings with modest assist averages (SF/SG,
AST avg < 6.0) are operating in a situational context that the historical iron_floor pattern
does not capture. The floor is for stable contexts — this is not a stable context.

RETURN FROM INJURY — SHORT SAMPLE INSTABILITY:
- When a player header shows [SHORT_SAMPLE:Ng] (fewer than 8 played games in L10 window),
  the player has recently returned from injury or missed an extended stretch. Their L10
  statistical floor has not restabilized — early return games frequently show compressed
  minutes, conservative role, and below-normal production that will skew the floor downward.
- For REB and AST props: apply a mandatory one-tier step-down from your normal best tier.
  If the stepped-down tier does not qualify (hit rate <70%), skip the prop entirely.
  Rationale: REB and AST are heavily role- and minutes-dependent; a returning player's
  floor in these categories is unreliable until they have 8+ games of consistent usage.
- For PTS props: apply a confidence reduction of 5% and do not pick above T15 unless the
  player has ≥7 games in the L10 window at T20+ with a consistent or up trend.
  Rationale: elite scorers re-establish their scoring floor faster than role-dependent
  stats, but the L10 sample instability still warrants caution at higher tiers.
- Do NOT apply this rule if the player's games_available is 8 or higher — the [SHORT_SAMPLE]
  flag will not appear in that case.
- Do NOT apply this rule to ignore iron_floor tags — iron_floor reflects the historical
  record and is still informative even in a short window. But short sample + iron_floor is
  not sufficient to override the mandatory REB/AST step-down.

MINUTES FLOOR — THRESHOLD EVENT FRAGILITY:
- The min_floor= value in each player header is the 10th-percentile of their L10 minutes.
  It represents the worst-case realistic playing time in recent games.
- For PTS picks at T15 or higher: if min_floor < 24, you MUST step down exactly one full tier
  before finalizing the pick (e.g. T15 → T10, T20 → T15). Do not treat this as a confidence
  reduction option — the step-down is mandatory. Rationale: two independent audit misses (Ball
  min_floor=22.9 at T15, Flagg FG_COLD at T15) both fell exactly 1 point short of threshold in
  games where minutes fragility was the structural risk. A confidence cap alone is insufficient
  when the tier itself is exposed by a sub-24 minute floor. After stepping down, re-evaluate
  whether the lower tier qualifies (≥70% hit rate). If it does not qualify, skip the PTS pick
  entirely. Exception: if avg_minutes > 36, this rule does not apply — elite-usage players
  rarely sit regardless of game script.
- For REB and AST picks: if min_floor < 20, apply the same caution.
- If min_floor >= avg_minutes - 3 (floor is close to average = very consistent minutes),
  treat this as a mild positive signal — the player rarely has outlier-low minutes nights.
- Do NOT apply this rule when the player's avg_minutes > 36: elite-usage players rarely
  sit regardless of game script.
- MIN_FLOOR CONFIDENCE CAP: For any PTS pick where the player's floor_minutes (from the
  minutes_floor field) is below 24.0, cap the final stated confidence_pct at 84%, regardless
  of hit streak length, iron_floor tag, or any other signal. Do not assign 85%, 86%, 87%,
  88%, or higher confidence to a PTS pick on a player whose floor_minutes < 24. The iron_floor
  and consistent tags reflect historical frequency but do not account for matchup-specific
  suppression in games where the player's baseline minutes exposure is below the 24-minute
  threshold — streak-based signals overstate reliability when the underlying minutes floor
  cannot support them. Apply this cap silently; do not explain it in the reasoning field
  unless it changes what you would otherwise have stated.

KEY RULES — SEQUENTIAL GAME CONTEXT:
- REB slump-persistent (confirmed signal, n=300, window=10):
  Post-miss REB hit rate drops to 62.0% vs baseline 75.0% (lift=0.83). Rebounds do NOT bounce back
  the next game — a miss is predictive of another miss.
  → If a player missed their REB tier last game, apply −5% confidence OR prefer one tier lower.
  → This applies regardless of opponent or home/away. The pattern holds across conditions.
- 3PM cold-streak decline (confirmed signal, n=161, severe cold = L5 hit rate ≥10pp below L10/L20):
  Players in a severe 3PM cold streak hit at 68.3% next game (lift=0.87 vs baseline 78.2%).
  Unlike other stats, 3PM cold streaks do not self-correct at N+1 — the slump persists or deepens.
  → If a player's recent L5 3PM output is materially below their L10/L20 rate, apply −5% confidence
    or skip the pick. Prefer cold-streak 3PM players only if facing a soft matchup.
- 3PM trend=down mandatory step-down (live rule, motivated by observed miss pattern):
  If the trend field for a player's 3PM stat is "down", you MUST step down exactly one full tier
  from your analytically selected floor before finalizing the pick.
  Example: best qualifying tier is T2 with 9/10 hit rate → trend=down → pick T1 instead.
  Do NOT use the aggregate hit rate to override this step-down. A 9/10 overall rate at T2
  means nothing if the directional signal is declining — the 0-make outcome is within range.
  This rule does not apply to PTS or AST (trend has shown no sequential signal for those stats).
  If stepping down would take the tier below the minimum valid tier (T1 for 3PM), skip the
  3PM pick entirely for that player.
- 3PM hard skip — trend=down AND limited minutes:
  If a player's 3PM trend is "down" AND their avg_minutes_last5 is ≤ 30, SKIP all 3PM picks
  for that player, including T1. Do not apply the step-down rule — skip outright.
  Rationale: low-minute players have fewer 3PM attempts per game; a declining trend in limited
  minutes means the absolute floor on makes is very close to zero. T1 (1+ make) is not a safe
  floor in this profile.
  This gate applies to the trend=down case only. A player with trend=stable or trend=up and
  avg_minutes_last5 ≤ 30 may still qualify for T1 via normal tier selection logic.
- 3PM hard skip — trend=down AND tough DvP:
  If a player's 3PM trend is "down" AND the opponent's DvP 3PM rating is "tough", SKIP all
  3PM picks for that player, including T1. Do not apply the step-down rule — skip outright.
  Rationale: after a trend=down step-down lands at T1, there is no margin left. A single
  cold-shooting night produces zero — which is within normal variance for any shooter. When
  the opponent is also rated tough for 3PM defense at the positional level, perimeter
  opportunity is further compressed. The combination of declining trend + tough perimeter
  defense makes T1 a binary coin flip, not a floor. Historical hit rates at 8/10 or 9/10
  do not protect against this combination — both T1 miss examples in the March 9 audit
  (Mitchell 3PM, Murray 3PM) had 8/10 and 9/10 rates respectively and went 0 actual.
  Note: 3PM DvP is otherwise treated as noise (no confidence adjustments in either direction).
  This skip rule is the sole exception — it applies only when BOTH conditions are met
  (trend=down AND tough DvP). A player with trend=down alone still uses the step-down rule.
  A player with tough DvP alone and trend=stable or up is unaffected.
- 3PM trend=down in blowout context (spread_abs 8–18):
  When a player's 3PM trend is "down" AND BLOWOUT_RISK=True (spread_abs > 8 and < 19),
  do NOT apply a hard skip. Apply the existing trend=down mandatory step-down rule instead
  (one tier lower than your analytically selected floor). The step-down provides adequate
  downside coverage.
  Rationale: H19 backtest (2026-03-22, n=96–137) showed blowout_win 3PM hits at 78.8–79.2%
  (lift=1.097–1.103) — above the 71.8% baseline. Players logging 24+ minutes in blowout
  wins get catch-and-shoot opportunities in a relaxed offensive environment; the garbage-time
  volume collapse that motivated the original hard skip only affects players below the
  24-minute floor already excluded from pick consideration. The hard skip was blocking a
  high-hit-rate population.
  The trend=down step-down rule (defined in KEY RULES — SEQUENTIAL GAME CONTEXT) still
  applies normally — step down one tier, and if the stepped-down tier does not qualify on
  hit rate, skip the pick via normal merit evaluation.
  Exception — extreme spreads: spread_abs ≥ 19 is handled by the separate unconditional
  hard skip below (unchanged). Do not apply this relaxed rule at spread_abs ≥ 19.
- 3PM hard skip — extreme blowout regardless of trend (spread_abs ≥ 19):
  If BLOWOUT_RISK=True AND spread_abs ≥ 19, SKIP all 3PM picks for ALL players on the
  favored team, regardless of trend direction. This rule fires even when trend=up or
  trend=stable. Do not apply step-downs — skip outright including T1.
  Rationale: SGA went 0-for-3 on threes in a 29-point OKC blowout win on 2026-03-18
  despite trend=up and a 9/10 T1 hit rate. At spread_abs ≥ 19 the game is effectively
  decided before tip-off — shot selection collapses toward drives and free throws
  regardless of the player's trend or role. The existing trend=down rule correctly handles
  moderate blowouts; this companion rule closes the gap for extreme spreads where even
  trend=up players face structural volume compression.
  This rule is additive to the trend=down rule: if trend=down AND spread_abs ≥ 8, the
  trend=down rule fires first. If trend=up or stable AND spread_abs ≥ 19, this rule fires.
  skip_reason: 3pm_blowout_trend_down (reuse existing enum for auditor consistency).
- PTS, AST: insufficient sequential signal. No adjustment needed based on last-game result.
- 3PM confidence ceiling — 80% maximum for non-iron-floor picks:
  Do not assign confidence_pct above 80 on any 3PM pick unless iron_floor=true on that
  stat. This cap applies regardless of hit rate, trend, consistent tag, or soft matchup.
  Rationale: 3PM props have binary outcome variance (0-for-game is always possible for
  any shooter) that the tier and hit-rate system cannot fully price. A 9/10 hit rate on
  a 3PM prop means the player goes 0-for in approximately 10% of games — and when they
  do, the miss is always maximal (actual=0 vs any threshold). Confidence above 80% on
  a non-iron-floor 3PM pick overstates the system's ability to distinguish those games.
  Audit evidence: Austin Reaves 3PM T1 at 84% confidence (top_pick=true), 9/10 hit rate,
  consistent tag — actual 0, miss. The 81–85% band on 3PM props ran at 50% over the
  sample period, consistent with overcalibration at high confidence on this prop type.
  Application: after all penalties and caps are applied, if the resulting confidence_pct
  for a 3PM pick exceeds 80, reduce it to 80. If iron_floor=true on the 3PM stat, the
  80% cap does not apply — iron_floor reflects a confirmed volume floor that provides
  structural protection against the 0-for-game scenario.
  top_pick ineligibility: Do not set top_pick=true on any 3PM pick unless iron_floor=true.
  A 3PM pick without iron_floor is not a structural top pick regardless of hit rate.

KEY RULES — INJURY STATUS ON SHOOTING PROPS:
- When a player carries a QUESTIONABLE status in the injury report, check the injury
  description. If the injury involves a soft-tissue joint concern (ankle, foot, knee,
  hip, groin), apply an additional -5% confidence penalty to ALL shooting-dependent props
  (3PM and PTS) for that player, regardless of trend direction or hit rate.
- Rationale: soft-tissue joint injuries subtly alter shot mechanics and selection —
  compromised lower-body movement shifts attempts toward the paint and mid-range and away
  from the perimeter. This affects 3PM floors directly and PTS floors indirectly via
  reduced shooting efficiency. The QUESTIONABLE tag for these injury types should function
  as a hard signal for shooting props, not just a minutes-floor caution.
- This penalty applies to QUESTIONABLE status only. OUT and DOUBTFUL players are already
  excluded from the prompt via pre-filter. Players listed as PROBABLE or not listed are
  unaffected.
- If the injury description is not a soft-tissue joint concern (e.g., illness, rest,
  non-contact soreness), do not apply this penalty.
- Apply this -5% silently to the confidence calculation. You may note the ankle/knee/foot
  tag in the reasoning field if it is the key reason for a borderline skip.

KEY RULES — SPREAD / BLOWOUT RISK:
- "BLOWOUT_RISK=True" means this team is heavily favored (spread_abs > 8). Stars get pulled in
  Q4 garbage time when the game is decided early, killing OVER props on counting stats.
  → When BLOWOUT_RISK=True: prefer one tier lower than your best tier, OR reduce confidence by
    10–15 pct. Do not skip the pick entirely unless confidence would drop below 70%.
  → When spread_abs > 13: cap confidence at 80% for ALL players on the favored team.
  → BLOWOUT-RESILIENT OFFSET CAP: When a player's quant stat line shows the [iron_floor] tag
    or other signals have been described as "blowout-resilient" in prior reasoning, this does
    NOT fully neutralize the BLOWOUT_RISK -10% penalty on PTS props. Treat blowout-resilient
    as a -5% offset to the penalty (net -5% total), NOT a full zero-out. A resilient scorer
    still gets benched in Q4 garbage time when the lead is large.
  → LARGE SPREAD PTS CAP: When BLOWOUT_RISK=True AND spread_abs ≥ 12, cap PTS confidence at
    74% regardless of hit rate, iron_floor tag, or blowout-resilient signals. The larger the
    margin, the more likely conservative Q4 rotations suppress counting stats — even elite
    scorers are not immune. This cap applies to the favored team's players only.
  → ELITE SCORER BLOWOUT EXEMPTION: A player whose raw_avgs PTS (shown in quant data) is
    ≥ 27.0 per game is exempt from ALL blowout-driven PTS confidence caps and tier step-downs.
    This includes the BLOWOUT -10% penalty, the spread_abs > 8 → cap 80% rule, and the
    LARGE SPREAD PTS CAP ≥ 12 → cap 74% rule. Rationale: a player averaging 27+ PPG has a
    structural scoring floor that blowout game script does not reliably compress — their
    minutes are protected regardless of score differential, and their counting stats at
    conservative tiers (T20, T25) are near-certain. Applying the same blowout penalties as
    a role player produces absurd outputs (e.g. T10 for a 30-PPG player). Apply normal tier
    selection and confidence logic for these players — blowout context is informational, not
    penalizing. The 27.0 threshold applies to raw_avgs PTS only; REB/AST/3PM props for the
    same player are still subject to normal blowout rules.
    Example players currently meeting this threshold: Shai Gilgeous-Alexander.
    Note: this exemption does not remove the BLOWOUT_RISK annotation from the pick or
    override the BLOWOUT_SECONDARY_SCORER SKIP for non-primary scorers — it applies
    only to primary elite scorers on the favored team.
    Exception to the exemption: when spread_abs >= 15, apply the full blowout confidence cap
    (74% maximum) to ALL players regardless of elite scorer status. At extreme spreads (15+),
    even elite scorers face minutes compression and early rest — the exemption applies only in
    the 8–14 spread range. Do not apply the exemption at spread_abs >= 15 under any
    circumstances. Additionally, PTS T25 and T30 are hard-skipped entirely at spread_abs >= 15
    on the favored side — see PTS T25 BLOWOUT HARD SKIP rule in TIER CEILING RULES above.
- "competitive" split = historical hit rate in close games (spread_abs ≤ 6.5).
  "blowout_games" split = historical hit rate in non-competitive games (spread_abs > 6.5).
  → If blowout_games hit rate is materially lower than competitive (e.g., 80%→50%), factor that
    in even when BLOWOUT_RISK is False — the pattern may be real.
- When spread=n/a (no spread data available), rely on blowout_risk flag and qualitative judgment.
- BLOWOUT_RISK SECONDARY SCORER SKIP: When BLOWOUT_RISK=True is shown in a player's quant
  header AND spread_abs ≥ 15, AND the player is not the team's primary scoring option
  (i.e. the player does not lead the team in PPG or is not the designated first option),
  do NOT select any PTS pick for this player regardless of hit rate. Skip the PTS pick
  entirely and emit a skip record with skip_reason=blowout_secondary_scorer.
  At spread_abs ≥ 15, the blowout is near-certain before tip-off — secondary scorer minutes
  compress meaningfully and aggregate tier hit rates do not price in this game-script risk.
  At spread_abs 8–14 (BLOWOUT_RISK=True but below the ≥15 threshold): do NOT apply this
  hard skip. Instead, apply the standard BLOWOUT_RISK confidence penalty (-10 to -15pp)
  from KEY RULES — SPREAD / BLOWOUT RISK above. Secondary scorers at spread_abs 8–14 hit
  PTS props at above-baseline rates (H19 backtest, n=140, lift=1.083) — the hard skip was
  over-restricting picks that actually succeed.
  CRITICAL DIRECTION CHECK: This rule applies ONLY to the favored side — players whose quant
  header shows BLOWOUT_RISK=True. Do NOT apply this rule to underdog players.
  Primary scorers (team PPG leaders, first options) are exempt from this skip at all spread
  levels because their usage is more protected even in blowout scenarios.

KEY RULES — VOLATILITY:
- Every stat line is tagged [consistent], [VOLATILE], or unlabeled (moderate).
- Consistent: player hits this tier in a stable, predictable pattern. No adjustment needed.
- Moderate: normal variance. No adjustment needed. This is the baseline.
- [VOLATILE]: player hits this tier in streaks — long runs of hits followed by cold stretches.
  A volatile player at 75% hit rate is riskier than a consistent player at 72%.
  Rules when [VOLATILE] is present:
    1. Reduce confidence by 5% before applying other adjustments.
    2. Do not select a volatile prop as a standalone Top Pick unless confidence after
       reduction still clears 85% AND there is supporting context (iron_floor, soft defense,
       favorable rest).
    3. Flag the volatility in the reasoning field so the Auditor can track whether
       volatile picks underperform over time.
  Iron-floor and VOLATILE interact as follows:
  * [iron_floor] protects the TIER — it prevents stepping down to a lower tier based on
    volatility alone. The tier you selected is sound.
  * [iron_floor] does NOT protect the CONFIDENCE LEVEL — trend and VOLATILE still apply to
    confidence calculation normally. Specifically: if a player has [iron_floor] AND trend=down
    on the same stat, apply the VOLATILE -5% confidence reduction as normal. Do not suppress
    the confidence deduction because iron_floor is present. Iron_floor means "this floor is
    real"; it does not mean "this stat is trending in the right direction." For wing scorers
    (SG/SF position) with a down trend on AST: iron_floor does not suppress the VOLATILE
    deduction. High scoring output in the same game does not guarantee assist accumulation —
    these are independent outputs. The down trend signal deserves full weight in the confidence
    calculation even when the tier is protected by iron_floor.
- VOLATILE PTS skip — weak qualifying combination: If ALL of the following are true, SKIP
  the PTS pick entirely. Do not pick at a lower tier.
    1. The stat is tagged [VOLATILE]
    2. The overall hit rate at the selected tier is 7/10 (70%) OR 8/10 (80%)
    3. The pick tier is T15 or higher
  Rationale: VOLATILE players at T15+ with 7/10 or 8/10 hit rates represent the system's
  weakest qualifying combinations. After the mandatory -5% VOLATILE deduction, 7/10 lands
  at the 70% floor with no margin. 8/10 lands at 75% — low enough that any cold game or
  role compression produces a significant undershoot, not a near-miss. Audit evidence:
  Brandon Ingram missed PTS O15 three times in 8 days — once at 7/10 and twice at 8/10 —
  all classified as variance or model_gap, all at T15. The VOLATILE tag is the system's
  signal that this player's counting stats are distribution-wide; pairing it with T15+
  at these hit rates is structurally marginal regardless of DvP or trend context. The
  system generates enough picks that these combinations should be skipped in favor of
  higher-confidence selections. This rule applies to PTS props only. Do NOT apply this
  skip to AST picks below T6 — the VOLATILE AST skip rule governs those cases and its
  threshold is T6, not T4. VOLATILE + 7/10 or 8/10 at T15+ for REB is handled by the
  existing 78% REB minimum floor rule.
  Exceptions — this skip does NOT apply when any of the following are true:
    (a) The player has [iron_floor] on this stat AND trend=up — iron_floor elevates the
        floor reliability above the 8/10 baseline.
    (b) The stat is AST AND the player's raw_avgs AST is ≥ 6.0 AND [iron_floor] is true
        on their AST stat — elite passers with a confirmed structural floor are not
        captured by the weak-combo rationale. Apply standard VOLATILE treatment instead
        (-5% confidence deduction) and evaluate normally. Emit a pick, not a skip.
        Rationale: Jokic (T8 AST, hit) and Barnes (T4 AST, hit) both triggered
        volatile_weak_combo at 100% false skip rate. Players averaging 6+ APG with an
        iron_floor have a confirmed assist floor that makes the 7/10 or 8/10 qualification
        structurally sound, not marginal.
- VOLATILE AST skip — high-tier primary ball-handlers: If BOTH of the following are true,
  SKIP the AST pick entirely. Do not pick at a lower tier.
    1. The stat is tagged [VOLATILE]
    2. The selected AST tier is T6 or higher
  This rule applies regardless of elite playmaker exemption status. The elite playmaker
  exemption (raw_avgs AST >= 8.0) protects against the low-volume position gate in the
  AST T4+ HARD GATE — it does not override floor instability signaled by [VOLATILE].
  A player who averages 8+ APG but carries a [VOLATILE] tag has a distribution-wide
  assist floor: their L10 range may span 4-13, making T6 structurally fragile regardless
  of their average. The 30th-percentile outcome of a VOLATILE elite playmaker IS the floor
  of their range, and T6 sits exactly at that floor.
  Audit evidence: Luka Doncic AST T6, actual 4 — L10 range 4-13, VOLATILE tag present,
  elite playmaker exemption invoked to override gate, pick missed at the exact floor value.
  Exception: if the player has [iron_floor] on their AST stat AND trend=up AND the tier is
  exactly T6, this skip does not apply — iron_floor at T6 with an up trend represents a
  confirmed floor above the threshold value. T8 or higher skips regardless of iron_floor.
- VOLATILE tag neutralizes absence-driven upside arguments:
  When a pick carries [VOLATILE] on the relevant stat, do not raise confidence on the
  basis of a key teammate or opponent player being OUT. Treat such absences as
  confidence-neutral — direction unchanged, not direction up.
  Rationale: the [VOLATILE] tag signals that the player's counting-stat output is
  distribution-wide — their floor is genuinely unreliable. Increased usage from an
  absence does not stabilize a volatile floor; it merely shifts the distribution
  upward while leaving the floor intact. A VOLATILE scorer who gets more usage in a
  given game can just as easily produce a floor-scraping night as a ceiling night.
  The amendment logic's job is to identify genuine structural changes — a VOLATILE
  player absorbing usage from an absent teammate is NOT a structural change. It is
  an opportunity argument layered on top of a floor instability signal.
  Rule: if [VOLATILE] appears on a stat's annotation AND the primary justification
  for raising confidence is a teammate/opponent absence (OUT, DOUBTFUL), hold
  confidence at your pre-amendment assessment. If the absence creates a genuine
  structural floor change (e.g., the absent player was the primary ball-handler and
  the VOLATILE player now handles all creation duties), that is a role change, not
  an absence — evaluate it as a role reassignment with explicit reasoning about why
  the floor itself has changed, not just the opportunity.
  Audit evidence: Kevin Durant PTS (VOLATILE) amended from 74% to 79% citing
  Sengun OUT redistributing paint usage. Durant scored 18 on a T20 threshold — the
  volatile floor materialized exactly as the tag predicted.
  This rule does NOT apply to: non-VOLATILE picks (absence-driven upside is valid
  reasoning for moderate and consistent players); or picks where [iron_floor]=true
  (iron_floor overrides floor instability concerns on the specific tier).

KEY RULES — SHOOTING EFFICIENCY REGRESSION:
- [FG_HOT:+X%] and [FG_COLD:-X%] annotations are generally informational. Do not apply any
  confidence adjustment in either direction based on these flags.
- Rationale: backtested across 521 instances — FG_HOT lift=1.014 (noise); FG_COLD lift=1.128
  (counterintuitively positive). Tier selection is based on counting-stat hit rates, not FG%, so
  shooting efficiency fluctuations do not predict next-game PTS tier outcomes in the general case.
- EXCEPTION — severe FG_COLD on high PTS tiers: If a player shows [FG_COLD:-X%] where X ≥ 15
  (i.e., L5 FG% is 15 or more percentage points below L20 FG%) AND the PTS pick tier is T15
  or higher, apply a mandatory one-tier step-down (e.g., T15 → T10, T20 → T15) before
  finalizing the pick. Re-evaluate whether the lower tier qualifies (≥70% hit rate). If it
  does not qualify, skip the PTS pick.
  Rationale: at severe FG_COLD thresholds on high counting-stat tiers, the recent shooting
  depression is material enough to compress scoring output. The H10 backtest's positive
  aggregate lift reflects regression-to-mean across all FG_COLD instances; at ≥15% cold
  combined with a T15+ tier, the tail risk is structural, not noise. Audit evidence:
  Cooper Flagg missed PTS O15 with FG_COLD:-18% present in quant data — the flag was
  treated as informational and the pick was not stepped down. Flagg scored 14 (1 below
  threshold) in 32 minutes.
  This rule does NOT apply to: FG_COLD below 15%; T10 or lower PTS tiers; REB/AST/3PM props.
  Document the tier step-down in the tier_walk field.

KEY RULES — FG% SAFETY MARGIN (H11 — backtested, 537 instances):
- PTS stat lines may show [FG_MARGIN_THIN:X%] based on the player's structural shooting margin.
  This is the gap between their season FG% and the minimum FG% needed to reliably hit their
  best PTS tier at typical volume (accounting for free throw and 3PM contributions).
  A thin margin means the player needs near-baseline shooting to hit the tier; any cold game
  risks a miss.
- [FG_MARGIN_THIN:X%]: margin is X% — below the 10% safety floor.
  Backtested hit rate at this margin: 57.6% across 165 instances (19.8pp below safe picks).
  57.6% is below the system's 70% pick threshold.
  → DO NOT pick at the flagged tier. Drop exactly one tier and re-evaluate.
  → If the lower tier qualifies (≥70% hit rate), pick there instead.
  → If the lower tier also fails, continue stepping down through remaining PTS tiers (T20 → T15 → T10).
  → Only skip the PTS prop entirely if T10 also fails to qualify after the full step-down cascade.
  → Document each step in the tier_walk field with the reason for each drop.
  This rule overrides positive signals at the same tier (iron_floor, soft defense, etc.).
  A FG_MARGIN_THIN player with iron_floor is still a borderline shooter — drop the tier.
  Rationale: FG_MARGIN_THIN identifies a shooting-margin risk at the specific tier flagged,
  not a blanket unselectability. A player who regularly scores 25+ always has a valid floor
  at T15 or T10 even when T20 is unsound due to thin margin. Skipping entirely when the
  step-down tier's *other* gates fail (e.g. VOLATILE, vs_tough) was producing false skips
  on strong scorers (Brown T20 skip → actual 32 PTS).
  Skip reason label when prop is ultimately skipped after full cascade: fg_margin_thin_tier_step
- [FG_MARGIN_NEG:X%]: margin is negative — player's season FG% is below breakeven.
  Apply the same full step-down cascade. This flag is rare for whitelisted players.
- If the flag is absent: player has a safe margin (≥10%). No adjustment needed.
- This rule applies to PTS props only. REB/AST/3PM are unaffected.

KEY RULES — HIGH CONFIDENCE GATE (81%+): Before assigning confidence_pct of 81 or higher, all three of the following conditions must be met. If any condition fails, cap confidence at 80% or lower — do not round up.
Condition A — Rest/availability: Player is NOT on a back-to-back (on_back_to_back = false), OR player averages ≥30 minutes per game in their last 10 games as a confirmed starter. Non-stars on B2B nights have demonstrated DNP and minutes-restriction risk that makes 81%+ confidence structurally unsound regardless of historical hit rate.
Condition B — Defense signal quality: The opp_today= or opp_defense rating used to justify the pick must come from the quant data (team-level opp_defense rank). Do not assign 81%+ based on a general "soft/tough" label alone — require the underlying rank and allowed average to confirm it. If the quant data is unavailable or contradicts the label, treat the matchup as neutral and remove it as a confidence-boosting factor.
Condition C — Confirming signals: At least two independent signals must support the pick beyond hit rate alone. Qualifying signals: favorable opp_today= rating (confirmed by quant rank), iron_floor tag, consistent volatility tag, soft blowout_risk context, rest advantage (≥2 rest days), or a pre-game news note confirming full availability and normal role. Hit rate alone — even 9/10 or 10/10 — does not satisfy Condition C by itself.

## QUANT STATS — PRE-COMPUTED TIER ANALYSIS
These numbers are computed from the full season game log — larger sample than the L10 above.
"overall" = hit rate at this tier across last 10 games.
"vs_soft" / "vs_tough" = hit rate at this tier across the full season, split by opponent defensive quality.

KEY FRAMEWORK — HOW TO REASON WHEN RULES CONFLICT:

The rules below can conflict. When they do, use this priority order:

  1. HARD SKIPS — absolute, no override. volatile_weak_combo, blowout_secondary_scorer,
     ast_hard_gate, 3pm_blowout_trend_down, volatile_ast_t6, and all other named skip
     rules execute unconditionally. If a hard skip fires, the pick does not exist. Period.

  2. MANDATORY TIER STEPS — execute first, then re-evaluate from the new tier.
     min_floor < 24 → step down. FG_COLD ≥ 15% on T15+ → step down. After stepping,
     re-check whether the new tier qualifies on hit rate. If it does not, skip.
     These steps happen before any confidence arithmetic.

  3. CONFIDENCE PENALTIES — apply cumulatively after tier is set.
     VOLATILE -5%, BLOWOUT -10%, B2B rate substitution, DENSE -5–10%.
     Floor is 70%: if cumulative penalties push below 70%, the pick fails on merit —
     skip it. Do not round up to 70% to force a qualifying pick.

  4. CONFIDENCE CAPS — applied last, after all penalties.
     spread_abs > 8 → 80% ceiling. spread_abs ≥ 12 → 74% ceiling.
     Caps are ceilings, not targets. A pick capped at 74% should be stated as 74%,
     not inflated to 80% because the cap "allows" it.

  5. POSITIVE SIGNALS — offset penalties where explicitly documented.
     iron_floor, consistent tag, soft DvP, favorable rest. These can reduce the
     net penalty but cannot push confidence above a cap ceiling.

PENALTY STACK LIMIT: If more than 3 independent confidence penalties apply to a single pick,
stop and re-examine. Either the pick is genuinely marginal and should be skipped, or some
penalties are redundant (e.g. B2B rate already prices in fatigue — also applying DENSE -5%
is double-counting). Document each penalty in tier_walk and ask: is this adjustment
independent of the others? If not, drop the weakest one. A pick that requires 4+ penalties
to stay above 70% is not a confident pick — skip it.

TIER_WALK FORMAT — document the final state clearly:
  - Each tier checked: "T25→8/10✓" or "T20→5/10 skip"
  - Mandatory steps: "min_floor<24 → step T15→T10"
  - Confidence chain as a clean sequence: "80% base → VOLATILE -5% → 75% → spread cap → 74% final"
  - The final selected tier must be unambiguously marked ✓
  - Do NOT embed skip conclusions ("→ SKIP") in tier_walk for picks you are emitting.
    If you conclude skip at any point in the reasoning, do not emit the pick.

SANITY CHECK — before finalizing each pick, verify:
  1. Is the final tier consistent with this player's actual statistical floor?
     A T10 PTS pick on a player whose L10 minimum is 17 points is incoherent.
     Check: does the tier you selected reflect a genuine uncertainty, or did
     the penalty cascade produce a tier that real game outcomes contradict?
  2. Is the stated confidence honestly derived? If hit rate is 9/10 but confidence
     is 74%, the tier_walk must show clearly why (caps applied, not fabricated).
  3. Did your own reasoning conclude "skip" at any step? If yes, do not emit the pick.
     filter_self_skip_picks() runs in Python as a backstop, but eliminate the
     contradiction at source — don't rely on post-processing to catch your errors.
  4. Does the pick pass the smell test? You have domain knowledge. A T10 PTS pick
     on the league's leading scorer is almost certainly wrong regardless of what
     the penalty arithmetic produced. Trust that signal — skip or re-examine.

ON COMPLEX SLATES: Today's slate may include blowout games, B2B players, VOLATILE scorers,
FG_COLD flags, and players returning from injury — all simultaneously. This is normal. Each
player is evaluated independently. A 16-point spread in one game does not affect picks in
other games. When multiple risk signals co-occur on a single player:
  - Apply them in the priority order above
  - Trust the output — if the output is a skip, the skip is correct
  - Do not force picks to meet a volume target. The system generates enough picks
    across a full slate that individual skips are preferable to low-confidence
    forced picks. Quality over quantity on every player.

PLAYER TIER CONTEXT — use the leaderboard: The ## WHITELISTED PLAYER RANKINGS block shows
current season and L20 averages. Use this as ground truth for player quality standing —
do not rely on training knowledge for who is "elite" this season. Rankings shift with trades,
injuries, and role changes. A player ranked #1 in PTS among whitelisted players has a
structurally different floor than a player ranked #12, and should be treated accordingly
regardless of what your training data suggests about their historical status. The ELITE SCORER
BLOWOUT EXEMPTION (raw_avgs PTS ≥ 27.0) is most reliably applied when you have verified the
player's current season ranking in the leaderboard block.

CONFIDENCE THRESHOLD IS A FLOOR, NOT A TARGET: 70% is the minimum threshold for emitting a
pick, not a number to land on. If your honest assessment after all adjustments is 65%, skip
the pick — do not adjust your stated confidence upward to clear the threshold. A pick stated
at exactly 70% must genuinely reflect 70% conviction. Rounding up from 65% is a skip
masquerading as a pick, and the auditor will find it.

{quant_context if quant_context else "No quant stats available."}

## ANALYSIS APPROACH
For every player in the SCOUT SHORTLIST, evaluate the prop types flagged by Scout (plus any others you identify signal for in the quant data) against the full rulebook above. Work through each player in this fixed order:
  1. PTS — walk tiers top-down; apply all PTS rules (FG_MARGIN, BLOWOUT, min_floor, etc.)
  2. REB — walk tiers top-down; apply REB-specific rules (78% floor, 25th-pct gate, etc.)
  3. AST — walk tiers top-down; apply AST-specific rules (T4+ hard gate, etc.)
  4. 3PM — walk tiers top-down; apply 3PM-specific rules (trend=down step-down, hard skips, etc.)

Keep per-player reasoning to 3 lines maximum per prop type:
  Line 1: Best qualifying tier + hit rate (e.g. "PTS T20: 9/10 ✓") or skip signal
  Line 2: Key adjustment applied if any (e.g. "VOLATILE -5%, B2B rate used, BLOWOUT -10%")
  Line 3: Final confidence + pick or skip decision (e.g. "→ 80% PICK" or "→ 65% SKIP")

Do not narrate every rule check. Do not recalculate L10 averages in writing — work from the quant data provided. Brief internal notes only; the JSON output is what matters.
Include explicit skip records for any prop where a hard rule fired to block an otherwise-qualifying tier (hit rate ≥70% but rule overrode the pick). Do NOT record skips for props where no tier qualified on hit rate alone.

## TOP PICKS — FINAL SELECTION STEP
After completing your full player analysis, review all picks you intend to emit and select
2–4 as your TOP PICKS for the day. These are the picks you have the most conviction on —
the clearest signal, lowest variance, and strongest contextual support.

Criteria for a top pick (must meet most of these):
- confidence_pct ≥ 78%
- hit_rate_display shows ≥ 8 hits in last 10 games at this tier
- Not flagged VOLATILE or no volatility concern at this tier
- Opponent defense is soft or mid (not tough) for this stat
- No B2B, DENSE, BLOWOUT_RISK, or meaningful injury risk
- iron_floor is true, OR trend is up with a strong recent game log

Do not force exactly 4 if fewer genuinely qualify. 2 strong top picks beats 4 weak ones.

3PM TOP-PICK RESTRICTION: Do not designate a 3PM pick as top_pick=true unless iron_floor=true
is confirmed for that prop. A 9/10 or 10/10 hit rate on 3PM at T1 or T2 does NOT qualify for
top_pick without iron_floor confirmation — even with a consistent volatility tag and high
confidence. 3PM props have binary outcome variance (0 makes vs N makes) that the tier hit rate
system cannot fully capture. Reserve top_pick designation for 3PM picks where the structural
floor guarantee (iron_floor) is present, indicating the player has not posted zero makes in
their recent window. Without iron_floor, cap 3PM confidence at 80% maximum and exclude from
top_pick regardless of hit rate or confidence band.

Set top_pick: true on exactly these picks in the JSON output. All other picks get top_pick: false.

## OUTPUT FORMAT — EMIT THIS FIRST, BEFORE ANY OTHER TEXT
Your response MUST begin with a single JSON object on the very first line. No preamble.
No "I'll analyze..." No game context review block. No markdown headers before the JSON.
The JSON object starts at character 0 of your response.

The object has two keys: "picks" (array of pick objects) and "skips" (array of skip objects).
Both keys must always be present. If there are no skips, emit "skips": [].

After the closing }} of the JSON object, you may include a brief optional summary
(3–5 lines maximum) noting any notable decisions. Nothing more.

JSON schema:
{{{{
  "picks": [
    {{{{
      "date": "{TODAY_STR}",
      "player_name": "string",
      "team": "string (abbrev)",
      "opponent": "string (abbrev)",
      "home_away": "H or A",
      "prop_type": "PTS | REB | AST | 3PM",
      "pick_value": number,
      "direction": "OVER",
      "confidence_pct": number (70-99),
      "hit_rate_display": "string — fraction from last 10 games at this tier, e.g. '8/10'",
      "trend": "up | stable | down",
      "opp_defense_rating": "soft | mid | tough | unknown",
      "tier_walk": "string — compact walk-down showing tiers checked, e.g. 'PTS: 25→4/10 20→9/10✓'",
      "iron_floor": true or false,
      "top_pick": true or false,
      "reasoning": "One tight sentence: key reason this floor holds today. Max 15 words."
    }}}}
  ],
  "skips": [
    {{{{
      "date": "{TODAY_STR}",
      "player_name": "string",
      "team": "string (abbrev)",
      "opponent": "string (abbrev)",
      "prop_type": "PTS | REB | AST | 3PM",
      "tier_considered": number — the tier that had ≥70% hit rate before the rule fired,
      "direction": "OVER",
      "skip_reason": "min_floor_tier_step | volatile_weak_combo | blowout_secondary_scorer | 3pm_trend_down_tough_dvp | 3pm_trend_down_low_minutes | 3pm_blowout_trend_down | ast_hard_gate | fg_margin_thin_tier_step | reb_floor_skip | fg_cold_tier_step | blowout_t25_skip",
      "rule_context": {{{{
        ... fields specific to this skip_reason as defined in the rules above ...
      }}}}
    }}}}
  ]
}}}}

TEAMMATE REFERENCES:
- The quant context includes a "Teammates (active/whitelisted)" line for each player listing their current-season co-players on today's roster. When explaining a player's role, usage, or opportunity, you may only name teammates who appear on that line OR who appear in today's injury report.
- Do not name historical teammates, former co-players, or players from other teams.
- If a player's elevated role is evident from the quant stats (usage rate, AST rate, minutes), state the stats — do not speculate about who is absent unless their absence is explicitly documented in today's context.

picks rules:
- pick_value must be one of the valid tier values listed above. No other values allowed.
- direction is always OVER.
- hit_rate_display must be exactly "N/N" format — e.g. "9/10" or "7/10". No parentheticals, no commentary, no additional text. The frontend parses this field as a bare fraction.
- iron_floor must be true if and only if the quant stat line showed [iron_floor]. Otherwise false.
- top_pick must be true for exactly the picks you flagged in the TOP PICKS step above. All others must be false.
- Only include picks with confidence_pct >= 70.

skips rules:
- Only emit a skip record when a hard rule explicitly overrides a tier that had ≥70% hit rate.
- Do NOT emit skip records for props where no tier qualified on hit rate alone.
- Do NOT emit skip records for props where the player was entirely excluded (OUT/DOUBTFUL).
- rule_context must contain exactly the fields defined for that skip_reason — no extra fields.
- tier_considered is the tier value that was blocked (e.g. 15 for a T15 PTS skip).

## AUDITOR FEEDBACK FROM PREVIOUS DAYS
{audit_context}

## ROLLING PERFORMANCE SUMMARY
{audit_summary if audit_summary else "Insufficient audit history yet (need 3+ days)."}
"""


# ── Review stage (Stage 3) ──────────────────────────────────────────

def build_review_context(picks: list[dict], player_stats: dict) -> str:
    """
    Build a compact per-pick vulnerability card for the Review prompt.
    Extracts only the risk-relevant quant fields — not the full stats block.
    Returns a formatted string with one card per pick.
    """
    if not picks:
        return "No picks to review."

    lines = []
    for p in picks:
        name      = p.get("player_name", "?")
        team      = p.get("team", "?")
        opp       = p.get("opponent", "?")
        prop      = p.get("prop_type", "?")
        tier      = p.get("pick_value", "?")
        conf      = p.get("confidence_pct", "?")
        tier_walk = (p.get("tier_walk") or "").strip()
        iron      = p.get("iron_floor", False)
        ha        = p.get("home_away", "?")

        s = player_stats.get(name, {})

        # Schedule
        b2b        = s.get("on_back_to_back", False)
        rest_days  = s.get("rest_days")
        dense      = s.get("dense_schedule", False)
        games_l7   = s.get("games_last_7", 0)

        # Spread / game script
        blowout    = s.get("blowout_risk", False)
        spread_abs = s.get("spread_abs")
        today_spr  = s.get("today_spread")

        # Minutes
        mf         = s.get("minutes_floor") or {}
        floor_min  = mf.get("floor_minutes")
        avg_min    = mf.get("avg_minutes")

        # Opp defense for this prop
        opp_def    = (s.get("opp_defense") or {}).get(prop, {})
        opp_rating = opp_def.get("rating", "unknown")

        # Volatility — volatility[prop] is a dict {label, sigma, n}, not a string
        vol_label  = ((s.get("volatility") or {}).get(prop) or {}).get("label", "unknown")

        # B2B hit rate at this tier
        b2b_hr_data = (s.get("b2b_hit_rates") or {}).get(prop)
        b2b_tier_hr = None
        b2b_n       = None
        if b2b_hr_data and isinstance(b2b_hr_data, dict):
            b2b_n       = b2b_hr_data.get("n")
            tier_str    = str(tier)
            b2b_tier_hr = (b2b_hr_data.get("hit_rates") or {}).get(tier_str)

        # Bounce back
        bb   = (s.get("bounce_back") or {}).get(prop) or {}
        bb_pm_hr  = bb.get("post_miss_hit_rate")
        bb_lift   = bb.get("lift")
        bb_typ_ms = bb.get("typical_miss")

        # FT safety margin (PTS only)
        fsm       = s.get("ft_safety_margin") or {}
        fsm_label = fsm.get("label", "")
        fsm_marg  = fsm.get("margin")

        # Raw avgs
        raw_avgs  = s.get("raw_avgs") or {}
        raw_stat  = raw_avgs.get(prop)

        # Def recency
        def_recency = s.get("def_recency") or "null"

        # Team momentum
        tm_ctx  = s.get("team_momentum") or {}
        tm_tag  = (tm_ctx.get("team") or {}).get("tag", "")

        # ── Format card ──────────────────────────────────────────────
        header = (
            f"{name} ({team} {ha} vs {opp}) — "
            f"{prop} OVER {tier} | conf={conf}% | iron_floor={iron}"
        )

        schedule_parts = []
        if b2b:
            schedule_parts.append("B2B")
        if rest_days is not None:
            schedule_parts.append(f"rest={rest_days}d")
        if dense:
            schedule_parts.append(f"DENSE(L7:{games_l7}g)")
        schedule_str = " | ".join(schedule_parts) if schedule_parts else "normal_rest"

        spread_str = ""
        if spread_abs is not None and today_spr is not None:
            spread_str = f"spread={today_spr:+.1f}(abs={spread_abs:.1f})"
            if blowout:
                spread_str += " BLOWOUT_RISK"

        min_str = ""
        if floor_min is not None and avg_min is not None:
            min_str = f"min_floor={floor_min:.1f}(avg={avg_min:.1f})"

        b2b_hr_str = ""
        if b2b and b2b_tier_hr is not None and b2b_n is not None:
            b2b_hr_str = f"b2b_hit_rate_T{tier}={b2b_tier_hr:.0%}(n={b2b_n})"
        elif b2b and b2b_hr_data is None:
            b2b_hr_str = f"b2b_hit_rate=<5g(insufficient)"

        bb_str = ""
        if bb_pm_hr is not None:
            bb_str = f"post_miss_hr={bb_pm_hr:.0%}(lift={bb_lift:+.2f})"
            if bb_typ_ms is not None:
                bb_str += f" typical_miss={bb_typ_ms:.1f}pts_below"

        fsm_str = ""
        if prop == "PTS" and fsm_label:
            fsm_str = f"ft_margin={fsm_label}"
            if fsm_marg is not None:
                fsm_str += f"({fsm_marg:.1f}%)"

        tier_walk_abbrev = tier_walk[:120] + "…" if len(tier_walk) > 120 else tier_walk

        card_lines = [
            f"\n--- {header} ---",
            f"  schedule: {schedule_str}",
            f"  volatility: {vol_label} | opp_defense: {opp_rating} | def_recency: {def_recency}",
            f"  raw_avg_{prop}: {raw_stat} | team_momentum: {tm_tag or 'neutral'}",
        ]
        if spread_str:
            card_lines.append(f"  game_script: {spread_str}")
        if min_str:
            card_lines.append(f"  minutes: {min_str}")
        if b2b_hr_str:
            card_lines.append(f"  b2b_context: {b2b_hr_str}")
        if bb_str:
            card_lines.append(f"  bounce_back: {bb_str}")
        if fsm_str:
            card_lines.append(f"  ft_margin: {fsm_str}")
        if tier_walk_abbrev:
            card_lines.append(f"  pick_reasoning: {tier_walk_abbrev}")

        lines.extend(card_lines)

    return "\n".join(lines)


def build_review_prompt(
    picks: list[dict],
    review_context: str,
    audit_summary: str,
) -> str:
    """
    Build the Review prompt — adversarial stress-test of Pick's output.
    Receives vulnerability cards per pick and miss pattern history.
    No rules, no full quant blocks, no game logs.
    """
    miss_pattern_block = ""
    if audit_summary:
        # Extract only the miss classification and recent lessons lines
        lines = audit_summary.split("\n")
        relevant = [
            l for l in lines
            if any(kw in l for kw in (
                "Miss classification", "selection_error", "model_gap",
                "variance", "Recent lessons", "  -", "  +"
            ))
        ]
        miss_pattern_block = "\n".join(relevant[:20])

    return f"""You are the Review agent for NBAgent, an NBA player props prediction system.

Today is {TODAY_STR}.

## STEP 0 — SKIP-ESCAPE CHECK (do this FIRST, before any adversarial assessment)
Before evaluating any pick, scan its `reasoning` field for explicit skip language.
If a pick's reasoning contains any of the following phrases, that pick escaped the
filter incorrectly and must be flagged regardless of its statistical merits:
- "mandatory hard skip"
- "HARD SKIP fires"
- "HARD GATE FIRES"
- "hard gate fires"
- "see skip record"
- "triggers mandatory"
For any such pick: set verdict = "stay_away", confidence_in_flag = "high", and set
vulnerability = "Pick's own reasoning concluded a hard rule skip fired — this pick
should not be active. Filter escape."
Do not apply adversarial assessment to these picks — the skip language is dispositive.

## YOUR ROLE — ADVERSARIAL STRESS-TESTER
The Pick agent has already applied the full statistical rulebook and produced today's picks.
Your job is NOT to re-check the rules or re-evaluate the statistics. Assume Pick did those
steps correctly.

Your job is adversarial: for each pick, construct the strongest structural bear case you can.
Ask: what is the most credible reason a sharp bettor would fade this pick today?

Focus on structural vulnerabilities — factors that make the floor genuinely fragile in ways
the hit rate alone does not capture:
- Volatility: the player's distribution is wide; the floor is a statistical pattern, not a
  guarantee. High confidence on a volatile player is structurally softer than the number suggests.
- B2B suppression: if the player's B2B hit rate at this tier is materially below their
  overall rate, the floor shifts today.
- Blowout game script: even after the blowout penalty was applied, a large spread on the
  favored side creates Q4 rest risk for counting stats. Stars get pulled when games are
  decided early. The penalty discounts confidence; the structural risk remains.
- Minutes fragility: a floor_minutes below 24 on a PTS T15+ pick means a single low-minutes
  game — well within normal variance — produces a miss. The floor is contingent on minutes,
  not guaranteed.
- Dense schedule fatigue: 4+ games in 5 nights compresses recovery in ways the aggregate
  hit rate may not reflect if the current dense stretch is atypical.
- Post-miss sequential slump for REB: REB is confirmed slump-persistent. A player who missed
  their REB tier last game has a meaningfully lower expected hit rate next game.
- FT-dependent PTS at thin margin: a player whose scoring is heavily FT-dependent with a
  thin safety margin is one cold-FG night away from falling short. The margin buys little.

## CALIBRATION — CRITICAL
Most picks on a good day are clean. Your flags must be meaningful, not numerous.

**Expected flag rate on a typical 12-pick slate:** 2–4 flags (`concern` or `stay_away`).
**Calibration failure modes to avoid:**
- Over-flagging: marking 7+ picks as `concern` or `stay_away` on a normal slate. If you
  find yourself flagging the majority of picks, you are inventing concerns. A pick with
  9/10 recent hits, no B2B, a soft matchup, no blowout risk, and stable minutes is clean —
  do not manufacture a vulnerability where none structurally exists.
- Under-flagging: marking everything `clean`. Genuine structural risks exist on most slates.
  If you find 0 flags on a slate with B2B players, blowout games, or volatile scorers, you
  are not looking hard enough.

Use `stay_away` sparingly — only for picks with a clear, specific structural failure that
the pick should not have been made (e.g. extreme blowout + volatile secondary scorer at a
high PTS tier, or B2B with a dramatically compressed b2b hit rate at this tier specifically).

Use `concern` for picks that are reasonable but carry a meaningful vulnerability worth
noting — something a reader should know before placing the bet.

Use `clean` for picks where you genuinely cannot construct a credible bear case beyond
normal variance. Most picks should be `clean`.

## WHAT REVIEW IS NOT
- Do not flag picks simply because the confidence is "only 74%" — that is a calibrated pick
  that cleared the bar; low confidence is already reflected in the tier selection.
- Do not re-litigate the tier selection. If Pick chose T20 over T25, that reasoning is in
  the tier_walk. Do not second-guess it unless the tier_walk itself reveals an inconsistency.
- Do not use training priors about players or teams to override the quant data. Your job is
  structural vulnerability assessment, not additional statistical analysis.
- Do not assign `stay_away` to a pick just because of a risk flag that Pick already priced
  in (e.g. BLOWOUT -10% was applied, confidence is 74% — that's priced). Assign `stay_away`
  only when the structural risk is not fully captured by Pick's existing adjustments.

## HISTORICAL MISS PATTERNS (from audit history)
These categories of picks have historically underperformed. Weight them in your assessment:

{miss_pattern_block if miss_pattern_block else "Insufficient audit history yet."}

## TODAY'S PICKS — VULNERABILITY CARDS
One card per pick. Each card shows the pick parameters plus extracted risk-relevant quant
fields. The `pick_reasoning` line is an abbreviated version of Pick's tier_walk.

{review_context}

## OUTPUT FORMAT
Your response MUST begin with a JSON array at character 0. No preamble.

[
  {{{{
    "player_name": "string — exact name from the pick",
    "team": "string — team abbreviation",
    "prop_type": "PTS | REB | AST | 3PM",
    "pick_value": number,
    "verdict": "clean | concern | stay_away",
    "vulnerability": "string — the strongest bear case in 1–2 sentences. Required when verdict is concern or stay_away. Empty string when verdict is clean.",
    "confidence_in_flag": "high | medium | low — only meaningful when verdict is not clean; set to low for clean picks"
  }}}}
]

Every pick in the vulnerability cards above must appear exactly once in the output array.
Do not omit any pick. Do not add picks that were not in the input.
After the closing ] you may add a brief note (2 lines maximum). Nothing more.
"""


def call_review(prompt: str, model: str = MODEL) -> list[dict] | None:
    """
    Call Claude with the Review prompt. Returns list of verdict dicts on success.
    Returns None on any failure — caller skips writing picks_review file (non-fatal).
    Never calls sys.exit() — Review failure does not block pick delivery.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[analyst] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[analyst] Review call: calling Claude ({model})...")
    raw_chunks = []
    try:
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            for text in stream.text_stream:
                raw_chunks.append(text)
    except Exception as e:
        print(f"[analyst] Review API call failed: {e} — skipping picks_review file")
        return None

    raw = "".join(raw_chunks).strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Find opening bracket
    bracket_idx = raw.find('[')
    if bracket_idx == -1:
        print("[analyst] Review parse failed: no JSON array found — skipping picks_review file")
        return None
    if bracket_idx > 0:
        print(f"[analyst] Review: {bracket_idx} chars of prose before JSON — extracting")
        raw = raw[bracket_idx:]

    last_bracket = raw.rfind(']')
    if last_bracket != -1 and last_bracket < len(raw) - 1:
        raw = raw[:last_bracket + 1]

    data = None
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"[analyst] Review json.loads failed ({e}) — attempting repair")
        data = _repair_json(raw)

    if not isinstance(data, list):
        print("[analyst] Review parse failed: expected JSON array — skipping picks_review file")
        return None

    print(f"[analyst] Review call complete — {len(data)} verdicts received")
    return data


def apply_review_flags(
    verdicts: list[dict],
    picks: list[dict],
    review_path: Path,
) -> None:
    """
    Convert Review verdicts to picks_review_YYYY-MM-DD.json format and write the file.

    Verdict mapping:
      clean      → keep,         trim_reasons: []
      concern    → trim,         trim_reasons: [vulnerability]
      stay_away  → manual_skip,  trim_reasons: [vulnerability]

    Writes 'source': 'auto' on every entry so build_site.py can distinguish
    auto-review badges from manual ones.

    Skips writing if the picks_review file already exists (manual review takes priority).
    Skips writing if verdict list is empty or cannot be matched to any pick.
    """
    if review_path.exists():
        print(
            f"[analyst] picks_review file already exists for today — "
            f"skipping auto-review write (manual review takes priority)"
        )
        return

    if not verdicts:
        print("[analyst] Review returned no verdicts — skipping picks_review file")
        return

    # Build lookup of picks by (name_lower, prop_type, pick_value) for matching
    pick_lookup: dict[tuple, dict] = {}
    for p in picks:
        key = (
            (p.get("player_name") or "").strip().lower(),
            p.get("prop_type", ""),
            p.get("pick_value"),
        )
        pick_lookup[key] = p

    verdict_map = {
        "clean":      "keep",
        "concern":    "trim",
        "stay_away":  "manual_skip",
    }

    review_entries = []
    matched = 0
    for v in verdicts:
        vname  = (v.get("player_name") or "").strip().lower()
        pt     = v.get("prop_type", "")
        pv     = v.get("pick_value")
        raw_vd = v.get("verdict", "clean")
        vuln   = (v.get("vulnerability") or "").strip()

        verdict = verdict_map.get(raw_vd, "keep")
        trim_reasons = [vuln] if (verdict in ("trim", "manual_skip") and vuln) else []

        # Find the matching pick to get team + date
        pick = pick_lookup.get((vname, pt, pv))
        if pick is None:
            print(
                f"[analyst] Review: no matching pick for {v.get('player_name')} "
                f"{pt} T{pv} — skipping entry"
            )
            continue

        matched += 1
        review_entries.append({
            "date":         TODAY_STR,
            "player_name":  pick.get("player_name", v.get("player_name", "")),
            "team":         pick.get("team", ""),
            "prop_type":    pt,
            "pick_value":   pv,
            "verdict":      verdict,
            "trim_reasons": trim_reasons,
            "source":       "auto",
        })

    if not review_entries:
        print("[analyst] Review: no verdict entries matched picks — skipping picks_review file")
        return

    flags = sum(1 for e in review_entries if e["verdict"] in ("trim", "manual_skip"))
    stay_away = sum(1 for e in review_entries if e["verdict"] == "manual_skip")
    print(
        f"[analyst] Review flags: {flags} flagged ({stay_away} stay_away, "
        f"{flags - stay_away} concern) of {matched} matched picks"
    )

    with open(review_path, "w") as fh:
        json.dump(review_entries, fh, indent=2)
    print(f"[analyst] Saved picks_review → {review_path}")


# ── Claude call ──────────────────────────────────────────────────────

def _repair_json(raw: str) -> dict | list | None:
    """
    Attempt to repair malformed JSON from Claude's response.
    Returns parsed object/list on success, None on failure.
    Called only after json.loads() has already failed.
    """
    # --- Attempt 1: json_repair library ---
    try:
        from json_repair import repair_json  # type: ignore
        repaired = repair_json(raw)
        result = json.loads(repaired)
        print("[analyst] WARNING: JSON repair via json_repair succeeded — pick run continuing")
        return result
    except ImportError:
        pass  # library not installed; fall through to manual repair
    except Exception:
        pass  # json_repair failed; fall through to manual repair

    # --- Attempt 2: targeted control-character sanitization ---
    # Escape raw newlines and tab characters inside JSON string values.
    # This handles the most common LLM JSON breakage: an unescaped newline
    # or apostrophe-adjacent character inside a tier_walk or reasoning field.
    try:
        sanitized_chars = []
        in_string = False
        escape_next = False
        for ch in raw:
            if escape_next:
                sanitized_chars.append(ch)
                escape_next = False
                continue
            if ch == '\\':
                sanitized_chars.append(ch)
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                sanitized_chars.append(ch)
                continue
            if in_string and ch == '\n':
                sanitized_chars.append('\\n')
                continue
            if in_string and ch == '\r':
                sanitized_chars.append('\\r')
                continue
            if in_string and ch == '\t':
                sanitized_chars.append('\\t')
                continue
            sanitized_chars.append(ch)
        sanitized = "".join(sanitized_chars)
        result = json.loads(sanitized)
        print("[analyst] WARNING: JSON repair via character sanitization succeeded — pick run continuing")
        return result
    except Exception:
        pass  # sanitization also failed

    return None  # all repair attempts failed


def call_analyst(prompt: str, model: str = MODEL) -> tuple[list[dict], list[dict]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[analyst] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[analyst] Calling Claude ({model})...")
    raw_chunks = []
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            raw_chunks.append(text)
    raw = "".join(raw_chunks).strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    # Try new object format first: {"picks": [...], "skips": [...]}
    brace_idx   = raw.find('{')
    bracket_idx = raw.find('[')

    # Determine whether response leads with object or array
    use_object = (brace_idx != -1) and (brace_idx < bracket_idx or bracket_idx == -1)

    if use_object:
        if brace_idx > 0:
            print(f"[analyst] WARNING: response had {brace_idx} chars of prose before JSON — extracting object")
            raw = raw[brace_idx:]
        # Trim trailing prose after closing brace
        last_brace = raw.rfind('}')
        if last_brace != -1 and last_brace < len(raw) - 1:
            raw = raw[:last_brace + 1]
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Response is not a JSON object")
            picks = data.get("picks", [])
            skips = data.get("skips", [])
            if not isinstance(picks, list):
                raise ValueError("picks is not a list")
            if not isinstance(skips, list):
                skips = []
            return picks, skips
        except Exception as e:
            print(f"[analyst] WARNING: json.loads failed ({e}) — attempting JSON repair")
            repaired = _repair_json(raw)
            if repaired is not None and isinstance(repaired, dict):
                picks = repaired.get("picks", [])
                skips = repaired.get("skips", [])
                if not isinstance(picks, list):
                    picks = []
                if not isinstance(skips, list):
                    skips = []
                return picks, skips
            print(f"[analyst] ERROR: JSON repair failed — cannot parse Claude response")
            print(f"[analyst] Original error: {e}")
            print(f"[analyst] Raw response (first 500 chars):\n{raw[:500]}")
            sys.exit(1)
    else:
        # Fallback: old flat-array format
        if bracket_idx > 0:
            print(f"[analyst] WARNING: response had {bracket_idx} chars of prose before JSON — extracting array")
            raw = raw[bracket_idx:]
        last_bracket = raw.rfind(']')
        if last_bracket != -1 and last_bracket < len(raw) - 1:
            raw = raw[:last_bracket + 1]
        try:
            picks = json.loads(raw)
            if not isinstance(picks, list):
                raise ValueError("Response is not a JSON array")
            print(f"[analyst] WARNING: received old flat-array format — no skip records")
            return picks, []
        except Exception as e:
            print(f"[analyst] WARNING: json.loads failed ({e}) — attempting JSON repair")
            repaired = _repair_json(raw)
            if repaired is not None and isinstance(repaired, list):
                print(f"[analyst] WARNING: received old flat-array format via repair — no skip records")
                return repaired, []
            print(f"[analyst] ERROR: JSON repair failed — cannot parse Claude response")
            print(f"[analyst] Original error: {e}")
            print(f"[analyst] Raw response (first 500 chars):\n{raw[:500]}")
            sys.exit(1)


# ── Output ───────────────────────────────────────────────────────────

def reconcile_pick_values(picks: list[dict]) -> list[dict]:
    """
    Post-process picks to ensure pick_value matches the final stepped-down tier
    documented in tier_walk. Claude correctly reasons about mandatory step-downs
    (min_floor, FG_COLD, volatility, etc.) and records them in tier_walk, but
    does not always update pick_value. This function detects the mismatch and
    corrects it before writing to disk.

    Only lowers pick_value — never raises it. Skips ambiguous cases.
    """
    import re

    # Step-down indicator keywords — when these appear in tier_walk, the integer
    # that follows (or precedes via →) is the destination tier after stepping down.
    STEP_KEYWORDS = re.compile(
        r"\b(step|apply|drop|corrected|→|->)\b", re.IGNORECASE
    )

    for pick in picks:
        tier_walk = pick.get("tier_walk") or ""
        prop_type  = pick.get("prop_type", "")
        pick_value = pick.get("pick_value")

        if not tier_walk or prop_type not in VALID_TIERS or pick_value is None:
            continue

        valid = VALID_TIERS[prop_type]
        name  = pick.get("player_name", "?")

        # ── Strategy 1: find the last ✓-marked tier, then check if a step keyword
        # appears after it pointing to a lower tier. ─────────────────────────────
        # Collect all (position, tier) pairs where a valid tier value is followed by ✓
        check_hits = []
        for m in re.finditer(r"\b(\d+)\b[^✓\n]*✓", tier_walk):
            val = int(m.group(1))
            if val in valid:
                check_hits.append((m.start(), val))

        # Collect all (position, tier) pairs that appear after a step keyword
        step_hits = []
        for m in re.finditer(r"(?:step|apply|drop|corrected|→|->)[^\d]*(\d+)", tier_walk, re.IGNORECASE):
            val = int(m.group(1))
            if val in valid:
                step_hits.append((m.start(), val))

        final_tier = None

        if step_hits:
            # The rightmost step-destination is the final tier
            candidate = max(step_hits, key=lambda x: x[0])[1]
            # Only accept if it is lower than current pick_value (step-downs only)
            if candidate < pick_value:
                final_tier = candidate

        # ── Strategy 2 (fallback): if Strategy 1 found a ✓-qualified tier but no
        # step destination, scan for →T{N} arrow patterns as a fallback.
        # Gated on check_hits being non-empty — if there were no ✓ marks at all,
        # Strategy 2 could falsely match unrelated tier mentions in the text. ────
        if final_tier is None and check_hits:
            arrow_hits = []
            for m in re.finditer(r"(?:→|->)\s*T?(\d+)", tier_walk, re.IGNORECASE):
                val = int(m.group(1))
                if val in valid and val < pick_value:
                    arrow_hits.append((m.start(), val))
            if arrow_hits:
                final_tier = max(arrow_hits, key=lambda x: x[0])[1]

        if final_tier is None:
            # Could not determine a stepped-down tier unambiguously — leave as-is
            if STEP_KEYWORDS.search(tier_walk):
                # Only log when step keywords were present (genuine parse failure)
                print(
                    f"[analyst] RECONCILE_SKIP: {name} {prop_type} — "
                    f"could not parse final tier from tier_walk"
                )
            continue

        if final_tier == pick_value:
            continue  # Already correct — no action needed

        # Safety: never raise pick_value via this function
        if final_tier > pick_value:
            print(
                f"[analyst] RECONCILE_SKIP: {name} {prop_type} — "
                f"parsed tier {final_tier} > pick_value {pick_value}, skipping"
            )
            continue

        # One-tier-step guard: only accept steps of exactly one tier at a time.
        # Multi-tier jumps (e.g., T20→T10) are suspicious — the tier_walk text likely
        # mentioned both tiers in context, not as a genuine two-step cascade. Require
        # that the parsed destination equals the next valid tier below pick_value.
        if pick_value in valid:
            current_idx = valid.index(pick_value)
            if current_idx > 0:
                next_lower_tier = valid[current_idx - 1]
                if final_tier != next_lower_tier:
                    print(
                        f"[analyst] RECONCILE_SKIP: {name} {prop_type} — "
                        f"parsed step {pick_value}→{final_tier} spans more than one tier "
                        f"(expected {next_lower_tier}), skipping"
                    )
                    continue

        old_val = pick_value
        pick["pick_value"] = final_tier
        pick["tier_walk"]  = (
            tier_walk
            + f" [reconciled: pick_value corrected {old_val}→{final_tier} by Python post-processor]"
        )
        print(
            f"[analyst] RECONCILED: {name} {prop_type} pick_value {old_val}→{final_tier} "
            f"(tier_walk indicated step-down)"
        )

    return picks


def filter_self_skip_picks(picks: list[dict]) -> list[dict]:
    """
    Remove picks whose tier_walk reasoning explicitly concludes with a skip decision.

    This is a Python enforcement layer for cases where the model correctly identifies
    that a pick should be skipped in its own reasoning (tier_walk) but emits it anyway.
    Only filters on unambiguous skip language — does not attempt to re-evaluate
    the pick's merit. Conservative: when in doubt, leave the pick.

    Filters a pick if ALL of the following are true:
      1. tier_walk contains explicit skip-conclusion language (see SKIP_CONCLUSIONS below),
         including both confidence-below-threshold phrases and floor gate failure phrases
      2. The skip language appears after a confidence calculation (contains a '%'),
         OR the skip is a floor gate failure (which fires before confidence arithmetic)
      3. The skip language is not immediately followed by an override/proceed signal

    Logs every filtered pick with the matching phrase so it can be audited.
    Returns the filtered pick list.
    """
    import re

    # Phrases that unambiguously conclude "skip this pick"
    # Must appear after a percentage calculation to be considered a skip conclusion
    SKIP_CONCLUSIONS = [
        r"below\s+(?:the\s+)?(?:70|threshold)[^\w]*skip",
        r"(?:→|->)\s*(?:65|64|63|62|61|60)\s*%[^\w]*skip",
        r"drops?\s+(?:confidence\s+)?to\s+\d{2}\s*%[^\w]*below[^\w]*(?:70|threshold)[^\w]*skip",
        r"confidence\s*(?:=|:)?\s*\d{2}\s*%[^\w]*skip",
        r"\d{2}\s*%\s*[-–—]\s*below\s+(?:70|threshold|floor)[^\w]*skip",
        # Floor gate failure phrases — catches REB/AST floor gate SKIP conclusions
        # (these fire before confidence arithmetic so no % check required)
        r"floor\s+gate\s+fails?",
        r"no\s+variance\s+buffer[^\w]*(?:floor\s+gate|skip)",
        r"3rd.lowest[^\w]*(?:=|equals?)[^\w]*\d+[^\w]*(?:equals?|=)[^\w]*(?:pick\s+value|T\d)[^\w]*(?:floor\s+gate|skip|no\s+buffer)",
        r"SKIP[^\w]*3rd.lowest",
        # Named hard-gate skip phrases — fire before confidence arithmetic
        # These appear when a rule fires unconditionally (ast_hard_gate, blowout_secondary_scorer, etc.)
        r"HARD\s+GATE\s+FIRES",
        r"BLOWOUT_SECONDARY_SCORER\s+SKIP\s+fires",
        r"HARD\s+SKIP\s+fires",
        r"mandatory\s+hard\s+skip",
        r"hard\s+gate\s+fires",
        r"(?:volatile_weak_combo|ast_hard_gate|blowout_secondary_scorer|3pm_blowout_trend_down|reb_floor_skip|blowout_t25_skip|fg_margin_thin_tier_step)\s+(?:fires|skip)",
        r"SKIP\s+(?:T\d+\s+)?(?:AST|PTS|REB|3PM)[^\w]*(?:hard\s+gate|mandatory\s+skip|no\s+valid\s+tier)",
        r"mandatory\s+skip",
        r"Record\s+as\s+skip",
        # Merit-floor skips — confidence falls below prop-type minimum floor after penalties
        # Catches: "falls below 3PM 75% minimum floor", "below 78% REB minimum confidence floor"
        r"falls?\s+below\s+(?:the\s+)?(?:3PM|REB|AST|PTS)\s+\d+%\s+minimum",
        r"below\s+\d+%\s+(?:3PM|REB|AST|PTS)\s+minimum\s+(?:confidence\s+)?floor",
    ]

    # Signals that indicate the model reconsidered and chose to proceed anyway
    # If these appear AFTER the skip language, leave the pick alone
    OVERRIDE_SIGNALS = [
        "proceed", "pick anyway", "still qualifies", "exception applies",
        "iron_floor overrides", "override",
    ]

    compiled = [re.compile(p, re.IGNORECASE) for p in SKIP_CONCLUSIONS]

    kept    = []
    removed = []

    for pick in picks:
        tier_walk   = (pick.get("tier_walk") or "").strip()
        player_name = pick.get("player_name", "?")
        prop_type   = pick.get("prop_type", "?")
        pick_value  = pick.get("pick_value", "?")

        if not tier_walk:
            kept.append(pick)
            continue

        matched_phrase = None
        for pattern in compiled:
            m = pattern.search(tier_walk)
            if m:
                matched_phrase = m.group(0)
                # Check for override signal AFTER the skip language
                text_after = tier_walk[m.end():]
                if any(sig.lower() in text_after.lower() for sig in OVERRIDE_SIGNALS):
                    matched_phrase = None  # Model reconsidered — leave pick
                break

        if matched_phrase:
            removed.append(pick)
            print(
                f"[analyst] SELF_SKIP_FILTERED: {player_name} {prop_type} T{pick_value} — "
                f"tier_walk concluded skip: '{matched_phrase[:80]}'"
            )
        else:
            kept.append(pick)

    if removed:
        print(
            f"[analyst] Self-skip filter: removed {len(removed)} pick(s) "
            f"that analyst reasoning had already concluded should be skipped."
        )

    return kept


def save_scout_omitted(omitted: list[dict]) -> None:
    """
    Persist Scout's omitted block to data/scout_omitted_YYYY-MM-DD.json.
    Written once per day alongside picks_review. Used to audit whether Scout
    incorrectly dropped candidates Pick would have selected.
    """
    with open(SCOUT_OMITTED_JSON, "w") as f:
        json.dump(omitted, f, indent=2)
    print(f"[analyst] Saved {len(omitted)} Scout omissions → {SCOUT_OMITTED_JSON}")
    for entry in omitted:
        name   = entry.get("player_name", "?")
        reason = entry.get("reason", "no reason given")
        print(f"  OMITTED: {name} — {reason}")


def save_picks(picks: list[dict]):
    # Filter out picks where analyst's own tier_walk reasoning concluded skip
    picks = filter_self_skip_picks(picks)

    # Reconcile pick_value against tier_walk step-down documentation
    picks = reconcile_pick_values(picks)

    # Load existing picks (from prior days), append today's
    existing = []
    if PICKS_JSON.exists():
        try:
            with open(PICKS_JSON, "r") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # Remove any existing picks for today (idempotent re-run)
    existing = [p for p in existing if p.get("date") != TODAY_STR]

    # Tag each pick with a result field (filled by auditor later)
    for p in picks:
        p["result"] = None
        p["actual_value"] = None
        if "iron_floor" not in p:
            p["iron_floor"] = False

    updated = existing + picks

    with open(PICKS_JSON, "w") as f:
        json.dump(updated, f, indent=2)

    print(f"[analyst] Saved {len(picks)} picks for {TODAY_STR} → {PICKS_JSON}")
    for p in picks:
        print(f"  {p['player_name']} {p['prop_type']} OVER {p['pick_value']} ({p['confidence_pct']}%) — {p['reasoning'][:80]}...")
    return picks


def save_skips(skips: list[dict]) -> None:
    """
    Write today's skip records to data/skipped_picks.json.
    Overwrites the file completely — only today's skips are written.
    Auditor reads this file the next morning to grade each skip.
    """
    # Tag each skip with null grading fields (filled by auditor)
    for s in skips:
        s["actual_value"]       = None
        s["would_have_hit"]     = None
        s["skip_verdict"]       = None
        s["skip_verdict_notes"] = None

    with open(SKIPPED_PICKS_JSON, "w") as f:
        json.dump(skips, f, indent=2)

    print(f"[analyst] Saved {len(skips)} skip records for {TODAY_STR} → {SKIPPED_PICKS_JSON}")
    for s in skips:
        print(f"  SKIP: {s['player_name']} {s['prop_type']} T{s['tier_considered']} — {s['skip_reason']}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[analyst] Running for {TODAY_STR}")

    games = load_todays_games()
    print(f"[analyst] Found {len(games)} games today")

    teams_today = list({g["home_abbrev"] for g in games} | {g["away_abbrev"] for g in games})

    game_log = load_player_game_log()
    print(f"[analyst] Loaded {len(game_log)} player game log rows")

    injuries = load_injuries(teams_today)
    print(f"[analyst] Loaded injuries for {len(injuries)} of {len(teams_today)} teams playing today")

    audit_entries = load_audit_feedback()
    print(f"[analyst] Loaded {len(audit_entries)} audit log entries")

    whitelist = load_whitelist()

    player_context = build_player_context(game_log, teams_today, whitelist)

    audit_context = build_audit_context(audit_entries)

    season_context  = load_season_context()
    playoff_picture = render_playoff_picture()
    team_defense    = format_team_defense_section()
    leaderboard     = build_player_leaderboard(game_log, whitelist)
    lineups_section = format_lineups_section(today_teams=set(teams_today))

    picks_run_at = dt.datetime.now(ET).isoformat()
    write_analyst_snapshot(LINEUPS_JSON, picks_run_at)

    player_stats = load_player_stats()
    print(f"[analyst] Loaded quant stats for {len(player_stats)} players")
    lineup_context = load_lineup_context()

    # Hard pre-filter: exclude OUT/DOUBTFUL players before any prompt building
    out_players = load_out_players()
    if out_players:
        filtered_stats: dict = {}
        for pname, pdata in player_stats.items():
            last = _extract_last(pname)
            norm_t = _norm_team(pdata.get("team", ""))
            if (last, norm_t) in out_players:
                print(f"[analyst] EXCLUDED (OUT/DOUBTFUL): {pname} ({pdata.get('team', '')})")
            else:
                filtered_stats[pname] = pdata
        player_stats = filtered_stats
        print(f"[analyst] After injury pre-filter: {len(player_stats)} players remaining")

    quant_context = build_quant_context(player_stats, lineup_context=lineup_context)

    player_profiles = load_player_profiles(player_stats)
    if player_profiles:
        print(f"[analyst] Loaded player profile narratives")

    audit_summary = load_audit_summary()
    if audit_summary:
        print(f"[analyst] Loaded rolling audit summary")
    else:
        print(f"[analyst] No audit summary yet (need 3+ audit days)")

    pre_game_news = load_pre_game_news()

    # Model selection — needed for fallback path and Scout
    active_count = len(player_stats)
    model_to_use = MODEL_LARGE if active_count > LARGE_SLATE_THRESHOLD else MODEL

    # ── Stage 1: Scout ────────────────────────────────────────────────
    scout_model = MODEL_LARGE if active_count > LARGE_SLATE_THRESHOLD else MODEL
    if scout_model == MODEL_LARGE:
        print(f"[analyst] Large slate ({active_count} players) — Scout using {MODEL_LARGE}")
    else:
        print(f"[analyst] Normal slate ({active_count} players) — Scout using {MODEL}")

    scout_prompt = build_scout_prompt(
        games=games, player_context=player_context, injuries=injuries,
        season_context=season_context, quant_context=quant_context,
        pre_game_news=pre_game_news, player_profiles=player_profiles,
        playoff_picture=playoff_picture, team_defense=team_defense,
        leaderboard=leaderboard, lineups_section=lineups_section,
    )

    shortlist, scout_omitted = call_scout(scout_prompt, model=scout_model)

    # ── Fallback: Scout failed — run single-call path unchanged ───────
    if shortlist is None:
        print("[analyst] Scout fallback: running single-call analyst mode")
        fallback_prompt = build_prompt(
            games, player_context, injuries, audit_context,
            season_context, quant_context, audit_summary,
            pre_game_news=pre_game_news, player_profiles=player_profiles,
            playoff_picture=playoff_picture, team_defense=team_defense,
            leaderboard=leaderboard, lineups_section=lineups_section,
        )
        picks, skips = call_analyst(fallback_prompt, model=model_to_use)
        print(f"[analyst] Fallback returned {len(picks)} picks, {len(skips)} skip records")
        picks = save_picks(picks)
        save_skips(skips)
        return

    # ── Stage 2: Pick ─────────────────────────────────────────────────
    save_scout_omitted(scout_omitted)
    shortlist_names = {entry["player_name"] for entry in shortlist if isinstance(entry, dict)}
    print(f"[analyst] Scout shortlisted {len(shortlist_names)} players: {sorted(shortlist_names)}")

    missing = shortlist_names - set(player_stats.keys())
    if missing:
        print(f"[analyst] WARNING: Scout shortlisted {len(missing)} player(s) not in quant stats "
              f"(name mismatch — these will be absent from Pick quant context): {sorted(missing)}")

    filtered_stats = {p: player_stats[p] for p in player_stats if p in shortlist_names}

    if len(filtered_stats) < 5:
        print(f"[analyst] WARNING: Only {len(filtered_stats)} shortlisted player(s) matched "
              f"quant stats — falling back to single-call mode")
        fallback_prompt = build_prompt(
            games, player_context, injuries, audit_context,
            season_context, quant_context, audit_summary,
            pre_game_news=pre_game_news, player_profiles=player_profiles,
            playoff_picture=playoff_picture, team_defense=team_defense,
            leaderboard=leaderboard, lineups_section=lineups_section,
        )
        picks, skips = call_analyst(fallback_prompt, model=model_to_use)
        print(f"[analyst] Fallback returned {len(picks)} picks, {len(skips)} skip records")
        picks = save_picks(picks)
        save_skips(skips)
        return

    filtered_quant_context = build_quant_context(filtered_stats, lineup_context=lineup_context)
    print(f"[analyst] Pick quant context built for {len(filtered_stats)} shortlisted players")

    print(f"[analyst] Pick call using {MODEL} (shortlist: {len(filtered_stats)} players)")
    pick_prompt = build_pick_prompt(
        scout_shortlist=shortlist, games=games, injuries=injuries,
        quant_context=filtered_quant_context, audit_context=audit_context,
        audit_summary=audit_summary,
    )

    picks, skips = call_analyst(pick_prompt, model=MODEL)
    print(f"[analyst] Pick returned {len(picks)} picks, {len(skips)} skip records")

    picks = save_picks(picks)
    save_skips(skips)

    # ── Stage 3: Review ───────────────────────────────────────────────
    review_path = DATA / f"picks_review_{TODAY_STR}.json"
    if not picks:
        print("[analyst] No picks to review — skipping Review stage")
    else:
        review_context = build_review_context(picks, filtered_stats)
        review_prompt  = build_review_prompt(picks, review_context, audit_summary)
        print(f"[analyst] Review call using {MODEL} ({len(picks)} picks to stress-test)")
        verdicts = call_review(review_prompt, model=MODEL)
        if verdicts is not None:
            apply_review_flags(verdicts, picks, review_path)
        else:
            print("[analyst] Review failed — picks_review file not written today")


if __name__ == "__main__":
    main()
