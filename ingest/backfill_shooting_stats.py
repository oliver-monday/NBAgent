#!/usr/bin/env python3
"""
Backfill shooting stats (fgm, fga, fg3m, fg3a) for historical rows in
player_game_log.csv.

Writes ONLY to data/player_game_log_shooting_backfill.csv.
Never touches player_game_log.csv.

Run from repo root:
  python ingest/backfill_shooting_stats.py
  python ingest/backfill_shooting_stats.py --dry-run
  python ingest/backfill_shooting_stats.py --limit 10
  python ingest/backfill_shooting_stats.py --sleep 0.5
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GAME_LOG_PATH = "data/player_game_log.csv"
BACKFILL_PATH = "data/player_game_log_shooting_backfill.csv"
SUMMARY_URL   = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
USER_AGENT    = "Mozilla/5.0 (compatible; NBAgent-backfill/1.0)"

# 2025-26 regular season starts Oct 22, 2025; skip earlier rows (preseason)
REGULAR_SEASON_START = dt.date(2025, 10, 22)

# 2026 All-Star weekend — skip these game dates entirely
ALLSTAR_START = dt.date(2026, 2, 14)
ALLSTAR_END   = dt.date(2026, 2, 16)

BACKFILL_COLUMNS = ["game_id", "player_id", "fgm", "fga", "fg3m", "fg3a"]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_summary(session: requests.Session, game_id: str) -> Dict[str, Any]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    resp = session.get(
        SUMMARY_URL, params={"event": game_id}, headers=headers, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Shooting stat extraction
# ---------------------------------------------------------------------------

def parse_made_attempted(raw: Optional[str]) -> Tuple[str, str]:
    """
    Parse 'made-attempted' string (e.g. '5-12') → (made, attempted) as strings.
    Returns ('', '') on any parse failure or missing input.
    """
    if raw is None:
        return "", ""
    s = str(raw).strip()
    if s in ("", "--"):
        return "", ""
    # Normalize various dash/hyphen characters ESPN occasionally uses
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        s = s.replace(ch, "-")
    if "-" in s:
        parts = s.split("-", 1)
        try:
            made     = str(int(parts[0].strip()))
            attempted = str(int(parts[1].strip()))
            return made, attempted
        except (ValueError, IndexError):
            return "", ""
    return "", ""


def extract_shooting_stats(summary_json: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """
    Parse ESPN summary boxscore JSON → {athlete_id: {fgm, fga, fg3m, fg3a}}.

    Players not found in the response are absent from the returned dict.
    Tries both 'labels' and 'keys' for the column-name array to handle
    any ESPN API variation.
    """
    result: Dict[str, Dict[str, str]] = {}

    box = summary_json.get("boxscore") or {}
    players_blocks = box.get("players") or []

    for team_block in players_blocks:
        stats_groups = team_block.get("statistics") or []

        for grp in stats_groups:
            # ESPN may use 'labels' or 'keys' for the column names
            labels: List[str] = grp.get("labels") or grp.get("keys") or []

            # Build uppercase label → index map
            label_to_idx: Dict[str, int] = {}
            for i, lab in enumerate(labels):
                key = str(lab).upper()
                if key not in label_to_idx:
                    label_to_idx[key] = i

            def get_stat(stats_list: List[str], key: str) -> Optional[str]:
                idx = label_to_idx.get(key.upper())
                if idx is None:
                    return None
                if idx >= len(stats_list):
                    return None
                return stats_list[idx]

            athletes = grp.get("athletes") or []
            for a in athletes:
                athlete    = a.get("athlete") or {}
                athlete_id = str(athlete.get("id") or "").strip()
                if not athlete_id:
                    continue

                stats_list: List[str] = a.get("stats") or []

                fg_raw  = get_stat(stats_list, "FG")
                tpt_raw = get_stat(stats_list, "3PT")

                fgm,  fga  = parse_made_attempted(fg_raw)
                fg3m, fg3a = parse_made_attempted(tpt_raw)

                result[athlete_id] = {
                    "fgm":  fgm,
                    "fga":  fga,
                    "fg3m": fg3m,
                    "fg3a": fg3a,
                }

    return result


# ---------------------------------------------------------------------------
# Game log helpers
# ---------------------------------------------------------------------------

def norm_game_id(v: str) -> str:
    """Normalize game_id to plain integer string (handles '401234.0' → '401234')."""
    s = str(v).strip()
    if not s:
        return ""
    try:
        return str(int(float(s)))
    except (ValueError, TypeError):
        return s


def load_game_log() -> List[Dict[str, str]]:
    """Read player_game_log.csv as list of row dicts (all string values)."""
    with open(GAME_LOG_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def filter_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Keep only regular-season rows (game_date >= 2025-10-22).
    Skip All-Star weekend (2026-02-14 to 2026-02-16 inclusive).
    Rows with unparseable dates are silently dropped.
    """
    out: List[Dict[str, str]] = []
    for r in rows:
        date_str = r.get("game_date", "").strip()
        try:
            d = dt.date.fromisoformat(date_str)
        except ValueError:
            continue
        if d < REGULAR_SEASON_START:
            continue
        if ALLSTAR_START <= d <= ALLSTAR_END:
            continue
        out.append(r)
    return out


def build_game_players(
    filtered_rows: List[Dict[str, str]],
) -> Dict[str, Dict[str, bool]]:
    """
    Build {game_id: {player_id: is_dnp}} from filtered game log rows.
    Deduplicates on (game_id, player_id) — last row wins for dnp flag.
    """
    game_players: Dict[str, Dict[str, bool]] = {}
    for r in filtered_rows:
        gid = norm_game_id(r.get("game_id", ""))
        pid = str(r.get("player_id", "")).strip()
        is_dnp = str(r.get("dnp", "")).strip() == "1"
        if gid and pid:
            game_players.setdefault(gid, {})[pid] = is_dnp
    return game_players


def load_existing_backfill() -> Set[str]:
    """
    Return the set of game_ids already present in the backfill CSV.
    Used for resume-safe operation — if the script is interrupted,
    re-running skips game_ids already written.
    """
    if not os.path.exists(BACKFILL_PATH):
        return set()
    existing: Set[str] = set()
    with open(BACKFILL_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gid = norm_game_id(row.get("game_id", ""))
            if gid:
                existing.add(gid)
    return existing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill fgm/fga/fg3m/fg3a for historical player_game_log.csv rows. "
            "Writes to data/player_game_log_shooting_backfill.csv only."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print game_ids that would be fetched and exit without making any requests.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N game_ids (useful for spot-checking).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.3,
        metavar="FLOAT",
        help="Sleep seconds between each game_id fetch (default: 0.3).",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Load and filter game log
    # ------------------------------------------------------------------
    print(f"[backfill] Reading {GAME_LOG_PATH}...")
    all_rows = load_game_log()
    print(f"[backfill] Total rows: {len(all_rows)}")

    filtered = filter_rows(all_rows)
    print(f"[backfill] After regular-season + All-Star filter: {len(filtered)} rows")

    game_players = build_game_players(filtered)
    game_ids_all = sorted(game_players.keys())

    # ------------------------------------------------------------------
    # Resume: skip game_ids already present in backfill output
    # ------------------------------------------------------------------
    already_done = load_existing_backfill()
    game_ids_todo = [gid for gid in game_ids_all if gid not in already_done]

    print(f"[backfill] Unique game_ids in filtered log: {len(game_ids_all)}")
    print(f"[backfill] Already backfilled (will skip):  {len(already_done)}")
    print(f"[backfill] Remaining to fetch:              {len(game_ids_todo)}")

    # ------------------------------------------------------------------
    # Dry-run
    # ------------------------------------------------------------------
    if args.dry_run:
        limit = args.limit if args.limit is not None else len(game_ids_todo)
        print(f"\n[dry-run] Game IDs that would be fetched (first {min(limit, len(game_ids_todo))}):")
        for gid in game_ids_todo[:limit]:
            players = game_players[gid]
            dnp_count = sum(1 for is_dnp in players.values() if is_dnp)
            print(f"  {gid}  ({len(players)} players, {dnp_count} DNP)")
        if args.limit is not None and args.limit < len(game_ids_todo):
            print(f"  ... (showing first {args.limit} of {len(game_ids_todo)})")
        print(
            f"\n[dry-run] Total game_ids that would be fetched: "
            f"{min(len(game_ids_todo), limit)}"
        )
        return

    # ------------------------------------------------------------------
    # Apply --limit
    # ------------------------------------------------------------------
    if args.limit is not None:
        game_ids_todo = game_ids_todo[: args.limit]
        print(f"[backfill] --limit {args.limit} applied; fetching {len(game_ids_todo)} game_ids")

    if not game_ids_todo:
        print("[backfill] Nothing to fetch. Exiting.")
        return

    # ------------------------------------------------------------------
    # Open output file for appending (write header only if file is new/empty)
    # ------------------------------------------------------------------
    os.makedirs(os.path.dirname(BACKFILL_PATH), exist_ok=True)
    file_is_new = (
        not os.path.exists(BACKFILL_PATH) or os.path.getsize(BACKFILL_PATH) == 0
    )
    out_f = open(BACKFILL_PATH, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_f, fieldnames=BACKFILL_COLUMNS)
    if file_is_new:
        writer.writeheader()

    # ------------------------------------------------------------------
    # Fetch + write
    # ------------------------------------------------------------------
    session = build_session()
    total_player_rows_written = 0
    total_empty_rows          = 0
    failed_game_ids: List[str] = []

    try:
        for i, gid in enumerate(game_ids_todo, start=1):
            players_for_game: Dict[str, bool] = game_players[gid]

            # Fetch ESPN summary
            shooting_map: Dict[str, Dict[str, str]] = {}
            fetch_ok = False
            try:
                summary      = fetch_summary(session, gid)
                shooting_map = extract_shooting_stats(summary)
                fetch_ok     = True
            except Exception as exc:
                print(f"[backfill] WARNING: fetch failed for game_id={gid}: {exc}")
                failed_game_ids.append(gid)

            # Write one row per (game_id, player_id) in this game
            for pid, is_dnp in players_for_game.items():
                if is_dnp or not fetch_ok:
                    # DNP rows and fetch-failure rows → empty shooting stats
                    row_out: Dict[str, str] = {
                        "game_id":  gid,
                        "player_id": pid,
                        "fgm":  "",
                        "fga":  "",
                        "fg3m": "",
                        "fg3a": "",
                    }
                    total_empty_rows += 1
                else:
                    # Normalize player_id before lookup: game_log stores ids as
                    # float strings ("4711294.0"); ESPN keyed map uses "4711294"
                    stats = shooting_map.get(norm_game_id(pid), {})
                    row_out = {
                        "game_id":  gid,
                        "player_id": pid,
                        "fgm":  stats.get("fgm",  ""),
                        "fga":  stats.get("fga",  ""),
                        "fg3m": stats.get("fg3m", ""),
                        "fg3a": stats.get("fg3a", ""),
                    }
                    # Player not found in ESPN response → all empty
                    if not any(row_out[c] for c in ["fgm", "fga", "fg3m", "fg3a"]):
                        total_empty_rows += 1

                writer.writerow(row_out)
                total_player_rows_written += 1

            if i % 25 == 0:
                print(f"[backfill] {i}/{len(game_ids_todo)} games fetched...")

            # Rate limiting
            if args.sleep > 0 and i < len(game_ids_todo):
                time.sleep(args.sleep)

    finally:
        out_f.close()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print(f"\n[backfill] === SUMMARY ===")
    print(f"  Game IDs processed:    {len(game_ids_todo)}")
    print(f"  Player rows written:   {total_player_rows_written}")
    print(
        f"  Rows with empty stats: {total_empty_rows}"
        f"  (DNPs + fetch failures + player not in ESPN response)"
    )
    if failed_game_ids:
        print(f"  Failed fetches ({len(failed_game_ids)}): {failed_game_ids}")
    else:
        print(f"  Failed fetches:        0")
    print(f"  Output: {BACKFILL_PATH}")


if __name__ == "__main__":
    main()
