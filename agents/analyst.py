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

# ── Config ───────────────────────────────────────────────────────────
MODEL         = "claude-sonnet-4-6"   # default model
MODEL_LARGE   = "claude-opus-4-6"     # upgraded model for large slates
MAX_TOKENS    = 32000                 # was 16384
# Player count threshold (after injury pre-filter) above which Opus is used
LARGE_SLATE_THRESHOLD = 30
# Valid tier values per prop type — mirrors tier definitions in quant.py and the analyst prompt
VALID_TIERS = {
    "PTS": [10, 15, 20, 25, 30],
    "REB": [2, 4, 6, 8, 10, 12],
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
            lines.append(
                f"{player_name} (vs {opp} | {spread_info}{blowout_flag}{rest_flag}{dense_flag}{l7_field}{min_floor_str}{proj_min_str}{usg_spike_str}{def_rec_str}):\n"
                + (momentum_line  + "\n" if momentum_line  else "")
                + (teammates_line + "\n" if teammates_line else "")
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

def build_prompt(games: list[dict], player_context: str, injuries: dict, audit_context: str, season_context: str, quant_context: str = "", audit_summary: str = "", pre_game_news: str = "", player_profiles: str = "", playoff_picture: str = "", team_defense: str = "", lineups_section: str = "") -> str:
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
  REB tiers:  2 / 4 / 6 / 8 / 10 / 12
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
- Only output picks with confidence_pct ≥ 70
- Where a player's stats card shows bb_lift > 1.15 for a stat at their qualifying tier, treat a post-miss pick as a neutral-to-positive signal rather than a negative one. Where [iron_floor] is shown, a single prior miss carries no negative weight.
- REB props — minimum confidence floor: Do not output any REB pick with confidence_pct below 78%. REB is the system's highest-variance category (season hit rate 66.7% vs 85.7% for PTS). A REB pick that would otherwise qualify at 72% or 75% confidence does not meet the bar — skip it entirely.
- REB props — pick value gate: The pick value must be strictly below the player's L10 25th-percentile REB output. Compute this as the 3rd-lowest REB value across their last 10 games. The pick tier must be strictly less than this floor value — an exact match is not sufficient. Rationale: when the 3rd-lowest L10 value equals the pick threshold exactly, there is zero variance buffer. A single outlier game (even for a player with a 10/10 hit rate) breaks the streak with no protective cushion. If the intended tier equals or exceeds this floor, move down one tier. If no valid tier exists strictly below the floor, skip the REB prop entirely.
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

{playoff_picture_section}{team_defense_section}## PLAYER RECENT PERFORMANCE (last {RECENT_GAME_WINDOW} games)
{player_context}

## QUANT STATS — PRE-COMPUTED TIER ANALYSIS
These numbers are computed from the full season game log — larger sample than the L10 above.
"overall" = hit rate at this tier across last 10 games.
"vs_soft" / "vs_tough" = hit rate at this tier across the full season, split by opponent defensive quality.

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
- PTS, AST: insufficient sequential signal. No adjustment needed based on last-game result.

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
- "competitive" split = historical hit rate in close games (spread_abs ≤ 6.5).
  "blowout_games" split = historical hit rate in non-competitive games (spread_abs > 6.5).
  → If blowout_games hit rate is materially lower than competitive (e.g., 80%→50%), factor that
    in even when BLOWOUT_RISK is False — the pattern may be real.
- When spread=n/a (no spread data available), rely on blowout_risk flag and qualitative judgment.
- BLOWOUT_RISK SECONDARY SCORER SKIP: When a player's pick has BLOWOUT_RISK flagged AND the
  player's team is the large underdog (spread of +8 or worse, i.e. the player's team is
  expected to lose by 8+ points), AND the player is not the team's primary scoring option
  (i.e. the player does not lead the team in PPG or is not the designated first option in the
  stat line), do NOT select any PTS pick for this player regardless of hit rate. Do not apply
  the -5% BLOWOUT_RISK deduction and proceed — skip the PTS pick entirely. Secondary scorers
  on large underdogs face asymmetric usage compression in the second half of blowout games:
  they accumulate playing time without scoring efficiency as the game deteriorates, and their
  aggregate T-pick hit rates do not price in this game-script effect. The spread threshold
  (+8 or worse) is the point at which blowout probability is high enough to make this a
  reliable skip rather than a marginal reduction. Primary scorers (team PPG leaders, first
  options) are exempt from this skip because their usage is more protected even in blowout
  scenarios. If in doubt about whether a player is a primary or secondary scorer, apply the skip.

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
  higher-confidence selections. This rule applies to PTS props only. VOLATILE + 7/10 or
  8/10 at T15+ for REB or AST is handled by the existing 78% REB minimum floor and AST
  gate rules respectively. Exception: if the player has [iron_floor] on this stat AND
  trend=up, this skip does not apply — the iron_floor tag elevates the floor reliability
  above the 8/10 baseline.

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
  → If the lower tier also qualifies (≥70% hit rate), pick there instead.
  → If no lower tier qualifies, skip the PTS prop and consider REB/AST instead.
  → Document the tier drop in tier_walk and reasoning fields.
  This rule overrides positive signals at the same tier (iron_floor, soft defense, etc.).
  A FG_MARGIN_THIN player with iron_floor is still a borderline shooter — drop the tier.
- [FG_MARGIN_NEG:X%]: margin is negative — player's season FG% is below breakeven.
  Apply the same tier-drop rule. This flag is rare for whitelisted players.
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
      "skip_reason": "min_floor_tier_step | volatile_weak_combo | blowout_secondary_scorer | 3pm_trend_down_tough_dvp | 3pm_trend_down_low_minutes | ast_hard_gate | fg_margin_thin_no_valid_tier | reb_floor_skip | fg_cold_tier_step",
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


# ── Claude call ──────────────────────────────────────────────────────

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
            print(f"[analyst] ERROR parsing Claude object response: {e}")
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
            print(f"[analyst] ERROR parsing Claude response: {e}")
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

        # ── Strategy 2 (fallback): if no ✓ and no step keyword matched, look for
        # the rightmost valid tier mentioned after any → in the string. ─────────
        if final_tier is None:
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


def save_picks(picks: list[dict]):
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

    prompt = build_prompt(
        games, player_context, injuries, audit_context,
        season_context, quant_context, audit_summary,
        pre_game_news=pre_game_news,
        player_profiles=player_profiles,
        playoff_picture=playoff_picture,
        team_defense=team_defense,
        lineups_section=lineups_section,
    )

    # Select model based on slate size — Opus for large slates, Sonnet otherwise
    active_count = len(player_stats)
    model_to_use = MODEL_LARGE if active_count > LARGE_SLATE_THRESHOLD else MODEL
    if model_to_use == MODEL_LARGE:
        print(f"[analyst] Large slate ({active_count} players > threshold {LARGE_SLATE_THRESHOLD}) — upgrading to {MODEL_LARGE}")
    else:
        print(f"[analyst] Normal slate ({active_count} players) — using {MODEL}")

    picks, skips = call_analyst(prompt, model=model_to_use)
    print(f"[analyst] Claude returned {len(picks)} picks, {len(skips)} skip records")

    save_picks(picks)
    save_skips(skips)


if __name__ == "__main__":
    main()
