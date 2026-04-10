#!/usr/bin/env python3
"""
espn_playoff_backfill.py — One-time backfill of historical NBA playoff + regular
season box scores from the ESPN public API.

Fetches per-player gamelogs for seasons 2021-2025 (both regular season and playoff)
for all active whitelisted players. Writes to data/playoff_career_log.csv.

Usage:
    python ingest/espn_playoff_backfill.py                    # Full backfill (2021-2025)
    python ingest/espn_playoff_backfill.py --probe            # Probe one player, print raw response
    python ingest/espn_playoff_backfill.py --seasons 2024,2025  # Specific seasons only
    python ingest/espn_playoff_backfill.py --player "LeBron James"  # Single player only

Output: data/playoff_career_log.csv
Re-runnable: upserts by (player_id, game_id, season_type) — safe to re-run.
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).parent.parent
WHITELIST_CSV = ROOT / "playerprops" / "player_whitelist.csv"
PLAYER_DIM_CSV = ROOT / "data" / "player_dim.csv"
OUTPUT_CSV = ROOT / "data" / "playoff_career_log.csv"

GAMELOG_URL = (
    "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"
    "/athletes/{athlete_id}/gamelog"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/604.1"
)

# Seasons to backfill — 2021 through 2025 (skipping 2020 COVID bubble)
DEFAULT_SEASONS = [2021, 2022, 2023, 2024, 2025]

# Season types: 2 = regular season, 3 = postseason
SEASON_TYPE_REGULAR = 2
SEASON_TYPE_PLAYOFF = 3

# Rate limit: seconds between API calls
REQUEST_DELAY = 0.5

# ESPN → Rotowire team abbreviation normalization
# Mirrors ingest/espn_daily_ingest.py — kept standalone by design.
ESPN_TO_ROTO = {
    "WSH": "WAS",
    "NO":  "NOP",
    "NY":  "NYK",
    "GS":  "GSW",
    "SA":  "SAS",
    "UTAH": "UTA",
    "PHO": "PHX",
    "CHA": "CHA",
}

OUTPUT_COLUMNS = [
    "season",
    "season_type",
    "game_id",
    "game_date",
    "team_abbrev",
    "opp_abbrev",
    "home_away",
    "player_id",
    "player_name",
    "started",
    "minutes",
    "pts",
    "reb",
    "ast",
    "tpm",
    "fgm",
    "fga",
    "fg3m",
    "fg3a",
    "ftm",
    "fta",
]


# ── Utility functions ────────────────────────────────────────────────

def to_roto_code(code: str) -> str:
    """Normalize ESPN team abbreviation to Rotowire-standard code."""
    c = (code or "").upper().strip()
    return ESPN_TO_ROTO.get(c, c)


def _norm_name(name: str) -> str:
    """Normalize player name to match player_dim.csv's player_name_norm convention.
    Hyphens → space, apostrophes/periods removed, collapse whitespace, lowercase."""
    s = name.lower().strip()
    s = s.replace("-", " ")
    for ch in ("'", "\u2019", "."):
        s = s.replace(ch, "")
    return " ".join(s.split())


def load_whitelist() -> list[dict]:
    """Load active players from whitelist CSV."""
    players = []
    with open(WHITELIST_CSV, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("active", "0")).strip() == "1":
                players.append({
                    "player_name": row["player_name"].strip(),
                    "team_abbr": row["team_abbr"].strip().upper(),
                })
    return players


def load_athlete_id_map() -> dict[str, str]:
    """
    Load player_dim.csv → {player_name_lower: athlete_id}.
    Last row wins when duplicates exist.
    """
    id_map: dict[str, str] = {}
    if not PLAYER_DIM_CSV.exists():
        print("[backfill] WARNING: player_dim.csv not found")
        return id_map
    with open(PLAYER_DIM_CSV, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        use_norm = "player_name_norm" in fieldnames
        for row in reader:
            if use_norm:
                name = (row.get("player_name_norm") or "").strip().lower()
            else:
                name = (row.get("player_name") or "").strip().lower()
            aid = (row.get("player_id") or "").strip()
            if name and aid:
                id_map[name] = aid
    return id_map


def fetch_gamelog(athlete_id: str, season: int, season_type: int) -> dict | None:
    """
    Fetch a single gamelog from ESPN.
    Returns the raw JSON response dict, or None on any error.
    """
    params = {"season": season, "seasontype": season_type}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    try:
        resp = requests.get(
            GAMELOG_URL.format(athlete_id=athlete_id),
            params=params,
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 404:
            return None  # Player didn't exist in this season
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(
            f"[backfill] ERROR fetching athlete {athlete_id} season {season} "
            f"type {season_type}: {e}"
        )
        return None


# ── Probe mode ───────────────────────────────────────────────────────

def probe(athlete_id: str = "1966") -> None:
    """
    Fetch one gamelog (LeBron James 2024 playoffs by default) and print
    the raw JSON structure to stdout for format discovery.
    """
    print(
        f"[probe] Fetching gamelog for athlete {athlete_id}, "
        f"season 2024, seasontype 3 (playoff)..."
    )
    data = fetch_gamelog(athlete_id, 2024, SEASON_TYPE_PLAYOFF)
    if data is None:
        print("[probe] No data returned — check athlete ID or network.")
        return

    print(f"\n[probe] Top-level keys: {list(data.keys())}")

    for key in data.keys():
        val = data[key]
        if isinstance(val, list):
            print(f"\n[probe] '{key}': list of {len(val)} items")
            if val:
                first = val[0]
                if isinstance(first, dict):
                    print(f"  First item keys: {list(first.keys())}")
                    print(f"  First item (truncated): {json.dumps(first, indent=2)[:1000]}")
                else:
                    print(f"  First item: {first}")
        elif isinstance(val, dict):
            print(f"\n[probe] '{key}': dict with keys {list(val.keys())}")
            for sub_key in list(val.keys())[:5]:
                sub_val = val[sub_key]
                if isinstance(sub_val, list):
                    print(f"  '{sub_key}': list of {len(sub_val)} items")
                    if sub_val and isinstance(sub_val[0], dict):
                        print(f"    First item keys: {list(sub_val[0].keys())}")
                elif isinstance(sub_val, dict):
                    print(f"  '{sub_key}': dict with keys {list(sub_val.keys())[:10]}")
                else:
                    print(f"  '{sub_key}': {type(sub_val).__name__} = {str(sub_val)[:200]}")
        else:
            print(f"\n[probe] '{key}': {type(val).__name__} = {str(val)[:200]}")

    probe_path = ROOT / "data" / "probe_gamelog_response.json"
    with open(probe_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\n[probe] Full response written to {probe_path}")
    print("[probe] Inspect this file to verify the parser logic below matches the actual format.")


# ── Response parser ──────────────────────────────────────────────────

def _safe_float(val: Any) -> float | None:
    """Convert a stat value to float. Returns None if unparseable."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val: Any) -> int | None:
    """Convert a stat value to int. Returns None if unparseable."""
    f = _safe_float(val)
    return int(f) if f is not None else None


def _extract_game_meta(event: dict) -> dict:
    """
    Extract game metadata (game_id, date, teams, home/away) from an event dict.
    ESPN event objects vary in structure — try multiple known patterns.
    """
    meta: dict[str, Any] = {}

    # Game ID
    meta["game_id"] = str(
        event.get("id") or event.get("eventId") or event.get("gameId") or ""
    ).strip()

    # Game date — normalize to YYYY-MM-DD
    raw_date = event.get("gameDate") or event.get("date") or ""
    if raw_date:
        date_str = str(raw_date).strip()[:10]
        if len(date_str) == 8 and date_str.isdigit():
            date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        meta["game_date"] = date_str
    else:
        meta["game_date"] = ""

    # Opponent
    opp = event.get("opponent") or event.get("opponentTeam") or {}
    if isinstance(opp, dict):
        meta["opp_abbrev"] = to_roto_code(
            opp.get("abbreviation") or opp.get("abbrev") or ""
        )
    else:
        meta["opp_abbrev"] = ""

    # Team
    team = event.get("team") or event.get("playerTeam") or {}
    if isinstance(team, dict):
        meta["team_abbrev"] = to_roto_code(
            team.get("abbreviation") or team.get("abbrev") or ""
        )
    else:
        meta["team_abbrev"] = ""

    # Home/away
    ha = event.get("homeAway") or ""
    if not ha:
        at_vs = str(event.get("atVs") or event.get("gameResult") or "").strip()
        if at_vs.startswith("@"):
            ha = "A"
        elif at_vs.startswith("vs"):
            ha = "H"
    meta["home_away"] = ha.upper()[:1] if ha else ""

    started = event.get("starter")
    meta["started"] = "1" if started else ("0" if started is False else "")

    return meta


def _extract_row_from_labels(
    event: dict,
    stat_row: list,
    label_idx: dict[str, int],
    athlete_id: str,
    player_name: str,
    season: int,
    season_type_label: str,
) -> dict | None:
    """Extract a single game row from a labels + parallel stats array."""

    meta = _extract_game_meta(event)
    if not meta.get("game_id"):
        return None

    def get_stat(label: str) -> Any:
        """Look up a stat by label name (case-insensitive). Try common aliases."""
        aliases = {
            "MIN": ["MIN", "MINS", "MINUTES"],
            "PTS": ["PTS", "POINTS"],
            "REB": ["REB", "REBS", "REBOUNDS", "TREB"],
            "AST": ["AST", "ASTS", "ASSISTS"],
            "3PM": ["3PM", "TPM", "FG3M", "3PT"],
            "FGM": ["FGM"],
            "FGA": ["FGA"],
            "FG3M": ["FG3M", "3PM", "TPM", "3PT"],
            "FG3A": ["FG3A", "3PA", "TPA"],
            "FTM": ["FTM"],
            "FTA": ["FTA"],
        }
        for alias in aliases.get(label, [label]):
            idx = label_idx.get(alias.upper())
            if idx is not None and idx < len(stat_row):
                return stat_row[idx]
        return None

    # Parse minutes — ESPN may format as "32:15" (MM:SS) or just "32"
    raw_min = get_stat("MIN")
    minutes = None
    if raw_min is not None:
        raw_min_str = str(raw_min).strip()
        if ":" in raw_min_str:
            parts = raw_min_str.split(":")
            try:
                minutes = int(parts[0]) + int(parts[1]) / 60
            except (ValueError, IndexError):
                minutes = _safe_float(raw_min_str.split(":")[0])
        else:
            minutes = _safe_float(raw_min_str)

    fgm = _safe_int(get_stat("FGM"))
    fga = _safe_int(get_stat("FGA"))
    fg3m = _safe_int(get_stat("FG3M"))
    fg3a = _safe_int(get_stat("FG3A"))
    ftm = _safe_int(get_stat("FTM"))
    fta = _safe_int(get_stat("FTA"))

    # Compound fields like "8-15" for FGM-FGA
    if fgm is None or fga is None:
        fg_compound = get_stat("FG")
        if fg_compound and isinstance(fg_compound, str) and "-" in fg_compound:
            parts = fg_compound.split("-")
            if len(parts) == 2:
                fgm = fgm if fgm is not None else _safe_int(parts[0])
                fga = fga if fga is not None else _safe_int(parts[1])

    if fg3m is None or fg3a is None:
        fg3_compound = get_stat("3PT") or get_stat("3P")
        if fg3_compound and isinstance(fg3_compound, str) and "-" in fg3_compound:
            parts = fg3_compound.split("-")
            if len(parts) == 2:
                fg3m = fg3m if fg3m is not None else _safe_int(parts[0])
                fg3a = fg3a if fg3a is not None else _safe_int(parts[1])

    if ftm is None or fta is None:
        ft_compound = get_stat("FT")
        if ft_compound and isinstance(ft_compound, str) and "-" in ft_compound:
            parts = ft_compound.split("-")
            if len(parts) == 2:
                ftm = ftm if ftm is not None else _safe_int(parts[0])
                fta = fta if fta is not None else _safe_int(parts[1])

    return {
        "season": season,
        "season_type": season_type_label,
        "game_id": meta["game_id"],
        "game_date": meta["game_date"],
        "team_abbrev": meta["team_abbrev"],
        "opp_abbrev": meta["opp_abbrev"],
        "home_away": meta["home_away"],
        "player_id": athlete_id,
        "player_name": player_name,
        "started": meta["started"],
        "minutes": round(minutes, 1) if minutes is not None else None,
        "pts": _safe_int(get_stat("PTS")),
        "reb": _safe_int(get_stat("REB")),
        "ast": _safe_int(get_stat("AST")),
        "tpm": fg3m,
        "fgm": fgm,
        "fga": fga,
        "fg3m": fg3m,
        "fg3a": fg3a,
        "ftm": ftm,
        "fta": fta,
    }


def _extract_row_from_dict(
    event: dict,
    stats: dict,
    athlete_id: str,
    player_name: str,
    season: int,
    season_type_label: str,
) -> dict | None:
    """Extract a single game row when stats are a dict (Pattern C)."""
    meta = _extract_game_meta(event)
    if not meta.get("game_id"):
        return None

    def gs(key: str, *alts: str) -> Any:
        for k in (key, *alts):
            v = stats.get(k) or stats.get(k.upper()) or stats.get(k.lower())
            if v is not None:
                return v
        return None

    raw_min = gs("MIN", "MINS", "minutes")
    minutes = None
    if raw_min is not None:
        raw_min_str = str(raw_min).strip()
        if ":" in raw_min_str:
            parts = raw_min_str.split(":")
            try:
                minutes = int(parts[0]) + int(parts[1]) / 60
            except (ValueError, IndexError):
                pass
        else:
            minutes = _safe_float(raw_min_str)

    return {
        "season": season,
        "season_type": season_type_label,
        "game_id": meta["game_id"],
        "game_date": meta["game_date"],
        "team_abbrev": meta["team_abbrev"],
        "opp_abbrev": meta["opp_abbrev"],
        "home_away": meta["home_away"],
        "player_id": athlete_id,
        "player_name": player_name,
        "started": meta["started"],
        "minutes": round(minutes, 1) if minutes is not None else None,
        "pts": _safe_int(gs("PTS", "points")),
        "reb": _safe_int(gs("REB", "REBS", "rebounds", "TREB")),
        "ast": _safe_int(gs("AST", "ASTS", "assists")),
        "tpm": _safe_int(gs("3PM", "TPM", "FG3M", "threes")),
        "fgm": _safe_int(gs("FGM")),
        "fga": _safe_int(gs("FGA")),
        "fg3m": _safe_int(gs("FG3M", "3PM", "TPM")),
        "fg3a": _safe_int(gs("FG3A", "3PA")),
        "ftm": _safe_int(gs("FTM")),
        "fta": _safe_int(gs("FTA")),
    }


def _season_type_matches(display_name: str, season_type_code: int) -> bool:
    """
    Decide whether an ESPN seasonType displayName should be included when
    the caller asked for regular (2) or playoff (3) data.

    displayName examples seen on the v3 gamelog endpoint:
      "2023-24 Postseason"             → playoff
      "2023-24 Regular Season"         → regular
      "2023-24 Play In Regular Season" → regular (play-in tournament)
      "2023-24 Preseason"              → skip entirely
    """
    dn = (display_name or "").lower()
    if not dn or "preseason" in dn:
        return False
    if season_type_code == SEASON_TYPE_PLAYOFF:
        # Strict: only postseason (play-in is labeled as regular by ESPN)
        return "postseason" in dn
    # Regular season request: accept both Regular Season and Play In Regular Season
    return "regular season" in dn


def _extract_row_from_top_level(
    event_meta: dict,
    stat_row: list,
    label_idx: dict[str, int],
    athlete_id: str,
    player_name: str,
    season: int,
    season_type_label: str,
) -> dict | None:
    """
    Extract a row from the actual ESPN v3 gamelog format:
      - meta comes from top-level events[event_id] dict
      - stat_row is the parallel stats array inside
        seasonTypes[].categories[].events[].stats
      - label_idx was built from the top-level `labels` list
      - Compound fields (FG="11-21", 3PT="3-7", FT="5-7") are split inline
    """
    meta = _extract_game_meta(event_meta)
    if not meta.get("game_id"):
        return None

    def _cell(label: str) -> Any:
        idx = label_idx.get(label.upper())
        if idx is None or idx >= len(stat_row):
            return None
        return stat_row[idx]

    def _split_compound(val: Any) -> tuple[int | None, int | None]:
        if val is None:
            return None, None
        s = str(val).strip()
        if "-" not in s:
            return None, None
        parts = s.split("-", 1)
        if len(parts) != 2:
            return None, None
        return _safe_int(parts[0]), _safe_int(parts[1])

    # Minutes ("32" or "32:15")
    raw_min = _cell("MIN")
    minutes = None
    if raw_min is not None:
        raw_min_str = str(raw_min).strip()
        if ":" in raw_min_str:
            parts = raw_min_str.split(":")
            try:
                minutes = int(parts[0]) + int(parts[1]) / 60
            except (ValueError, IndexError):
                minutes = _safe_float(parts[0])
        else:
            minutes = _safe_float(raw_min_str)

    # Compound shooting fields
    fgm, fga = _split_compound(_cell("FG"))
    fg3m, fg3a = _split_compound(_cell("3PT"))
    ftm, fta = _split_compound(_cell("FT"))

    return {
        "season": season,
        "season_type": season_type_label,
        "game_id": meta["game_id"],
        "game_date": meta["game_date"],
        "team_abbrev": meta["team_abbrev"],
        "opp_abbrev": meta["opp_abbrev"],
        "home_away": meta["home_away"],
        "player_id": athlete_id,
        "player_name": player_name,
        "started": meta["started"],
        "minutes": round(minutes, 1) if minutes is not None else None,
        "pts": _safe_int(_cell("PTS")),
        "reb": _safe_int(_cell("REB")),
        "ast": _safe_int(_cell("AST")),
        "tpm": fg3m,
        "fgm": fgm,
        "fga": fga,
        "fg3m": fg3m,
        "fg3a": fg3a,
        "ftm": ftm,
        "fta": fta,
    }


def parse_gamelog_response(
    data: dict,
    athlete_id: str,
    player_name: str,
    season: int,
    season_type_code: int,
) -> list[dict]:
    """
    Parse an ESPN gamelog response into flat row dicts matching OUTPUT_COLUMNS.

    Primary path is the actual v3 gamelog format discovered via --probe:
      {
        "labels": [...],
        "events": {event_id: {game metadata}},
        "seasonTypes": [
          {"displayName": "2023-24 Postseason",
           "categories": [{"events": [{"eventId": "...", "stats": [...]}]}]}
        ]
      }
    Falls back to legacy Pattern B/C parsers if the primary path finds nothing.
    """
    season_type_label = "regular" if season_type_code == SEASON_TYPE_REGULAR else "playoff"
    rows: list[dict] = []

    # ── Primary path: top-level labels + top-level events dict + seasonTypes ──
    # If this path is runnable (labels + seasonTypes both present), its result
    # is authoritative — an empty return means "player had no games matching
    # the requested season type" (e.g. a team that missed the playoffs), not
    # a parse failure. Do NOT fall through to legacy fallbacks in that case.
    top_labels = data.get("labels") or []
    season_types = data.get("seasonTypes") or []
    event_meta_map = data.get("events") if isinstance(data.get("events"), dict) else {}
    primary_runnable = bool(top_labels) and isinstance(season_types, list) and bool(season_types)

    if primary_runnable:
        label_idx = {str(lbl).upper(): i for i, lbl in enumerate(top_labels)}
        for st in season_types:
            if not isinstance(st, dict):
                continue
            if not _season_type_matches(st.get("displayName", ""), season_type_code):
                continue
            for cat in (st.get("categories") or []):
                if not isinstance(cat, dict):
                    continue
                for evt_entry in (cat.get("events") or []):
                    if not isinstance(evt_entry, dict):
                        continue
                    event_id = str(evt_entry.get("eventId") or "").strip()
                    stat_row = evt_entry.get("stats") or []
                    if not event_id or not isinstance(stat_row, list) or not stat_row:
                        continue
                    meta_event = event_meta_map.get(event_id) or {"id": event_id}
                    row = _extract_row_from_top_level(
                        meta_event, stat_row, label_idx,
                        athlete_id, player_name, season, season_type_label,
                    )
                    if row:
                        rows.append(row)
        return rows  # Authoritative — even if empty

    # ── Fallback: Pattern B (flat categories with per-category labels) ──
    cats_flat = data.get("categories")
    if isinstance(cats_flat, list) and cats_flat:
        for cat in cats_flat:
            if not isinstance(cat, dict):
                continue
            labels = cat.get("labels") or []
            events = cat.get("events") or []
            stats_grid = cat.get("stats") or []
            if not labels or not events or not stats_grid:
                continue
            label_idx = {str(lbl).upper(): i for i, lbl in enumerate(labels)}
            for i, event in enumerate(events):
                if i >= len(stats_grid):
                    break
                stat_row = stats_grid[i]
                row = _extract_row_from_labels(
                    event, stat_row, label_idx,
                    athlete_id, player_name, season, season_type_label,
                )
                if row:
                    rows.append(row)
        if rows:
            return rows

    # ── Fallback: Pattern C (flat events list with nested stats dicts) ──
    events_list = data.get("events")
    if isinstance(events_list, list):
        for event in events_list:
            if not isinstance(event, dict):
                continue
            stats = event.get("stats")
            if isinstance(stats, dict):
                row = _extract_row_from_dict(
                    event, stats,
                    athlete_id, player_name, season, season_type_label,
                )
                if row:
                    rows.append(row)
        if rows:
            return rows

    print(
        f"[backfill] WARNING: unrecognized response format for athlete {athlete_id} "
        f"season {season}. Top-level keys: {list(data.keys())}"
    )
    return rows


# ── CSV write with upsert ────────────────────────────────────────────

def write_csv(new_rows: list[dict]) -> None:
    """
    Write rows to playoff_career_log.csv with upsert-by-(player_id, game_id, season_type).
    If the file exists, existing rows with matching keys are replaced.
    Rows are sorted by player_name, season, game_date for readability.
    """
    def row_key(r: dict) -> str:
        return f"{r['player_id']}_{r['game_id']}_{r['season_type']}"

    existing: dict[str, dict] = {}
    if OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row_key(row)] = row

    updated = 0
    inserted = 0
    for row in new_rows:
        key = row_key(row)
        if key in existing:
            updated += 1
        else:
            inserted += 1
        existing[key] = row

    all_rows = sorted(
        existing.values(),
        key=lambda r: (
            str(r.get("player_name", "")).lower(),
            int(r.get("season", 0) or 0),
            str(r.get("game_date", "")),
        ),
    )

    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    total = len(all_rows)
    print(
        f"[backfill] Wrote {total} rows to {OUTPUT_CSV} "
        f"({inserted} new, {updated} updated)"
    )


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="ESPN playoff career data backfill")
    parser.add_argument(
        "--probe", action="store_true",
        help="Fetch one player gamelog and print raw JSON structure (format discovery mode)",
    )
    parser.add_argument(
        "--probe-id", type=str, default="1966",
        help="ESPN athlete ID to use for probe (default: 1966 = LeBron James)",
    )
    parser.add_argument(
        "--seasons", type=str, default=None,
        help="Comma-separated list of seasons to fetch (default: 2021,2022,2023,2024,2025)",
    )
    parser.add_argument(
        "--player", type=str, default=None,
        help="Fetch only this player (exact name match from whitelist). For testing.",
    )
    parser.add_argument(
        "--sleep", type=float, default=REQUEST_DELAY,
        help=f"Seconds between API calls (default: {REQUEST_DELAY})",
    )
    parser.add_argument(
        "--playoff-only", action="store_true",
        help="Fetch only playoff gamelogs (skip regular season). Faster for re-runs.",
    )
    args = parser.parse_args()

    if args.probe:
        probe(args.probe_id)
        return

    seasons = DEFAULT_SEASONS
    if args.seasons:
        seasons = [int(s.strip()) for s in args.seasons.split(",")]

    season_types = [SEASON_TYPE_PLAYOFF]
    if not args.playoff_only:
        season_types = [SEASON_TYPE_REGULAR, SEASON_TYPE_PLAYOFF]

    whitelist = load_whitelist()
    athlete_ids = load_athlete_id_map()

    if args.player:
        whitelist = [
            p for p in whitelist if p["player_name"].lower() == args.player.lower()
        ]
        if not whitelist:
            print(f"[backfill] Player '{args.player}' not found in active whitelist.")
            return

    players_to_fetch: list[tuple[str, str, str]] = []
    missing_ids: list[str] = []
    for p in whitelist:
        name_key = _norm_name(p["player_name"])
        aid = athlete_ids.get(name_key)
        if aid:
            players_to_fetch.append((aid, p["player_name"], p["team_abbr"]))
        else:
            missing_ids.append(p["player_name"])

    if missing_ids:
        print(f"[backfill] WARNING: {len(missing_ids)} players have no ESPN athlete ID:")
        for name in missing_ids:
            print(f"  - {name}")

    total_calls = len(players_to_fetch) * len(seasons) * len(season_types)
    est_minutes = (total_calls * args.sleep) / 60
    print(
        f"[backfill] Fetching {len(players_to_fetch)} players × {len(seasons)} seasons "
        f"× {len(season_types)} types = {total_calls} API calls (~{est_minutes:.1f} min)"
    )

    all_rows: list[dict] = []
    errors: list[str] = []
    call_count = 0

    for aid, player_name, team in players_to_fetch:
        player_rows = 0
        for season in seasons:
            for st in season_types:
                st_label = "regular" if st == SEASON_TYPE_REGULAR else "playoff"
                call_count += 1

                data = fetch_gamelog(aid, season, st)
                time.sleep(args.sleep)

                if data is None:
                    continue

                rows = parse_gamelog_response(data, aid, player_name, season, st)

                for r in rows:
                    if not r.get("team_abbrev"):
                        r["team_abbrev"] = team

                player_rows += len(rows)
                all_rows.extend(rows)

                if rows:
                    print(
                        f"  [{call_count}/{total_calls}] {player_name} "
                        f"{season} {st_label}: {len(rows)} games"
                    )

        if player_rows == 0:
            pass  # Player may legitimately have no playoff history

    reg_count = sum(1 for r in all_rows if r["season_type"] == "regular")
    po_count = sum(1 for r in all_rows if r["season_type"] == "playoff")
    unique_players = len(set(r["player_name"] for r in all_rows))

    print(
        f"\n[backfill] Total: {len(all_rows)} game rows "
        f"({reg_count} regular, {po_count} playoff) for {unique_players} players"
    )

    if not all_rows:
        print("[backfill] No data collected — check probe output for API format issues.")
        return

    pts_null = sum(1 for r in all_rows if r.get("pts") is None)
    if pts_null > len(all_rows) * 0.5:
        print(
            f"[backfill] WARNING: {pts_null}/{len(all_rows)} rows have null PTS. "
            f"Parser may not match API response format. Run --probe to inspect."
        )

    write_csv(all_rows)

    if errors:
        print(f"\n[backfill] {len(errors)} fetch errors:")
        for e in errors:
            print(f"  - {e}")

    print("[backfill] Done.")


if __name__ == "__main__":
    main()
