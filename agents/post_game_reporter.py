#!/usr/bin/env python3
"""
NBAgent — Post-Game Reporter

WORKFLOW NOTE: This script must run BEFORE auditor.py in the auditor workflow.
Add a step in auditor.yml to run this script immediately before the auditor.py step.

Scrapes ESPN player news for any player from yesterday's picks who logged
suspiciously low minutes or zero-stat lines. Detects post-game facts the
Auditor cannot infer from box scores alone:
  - In-game injury exits
  - DNP confirmations
  - Severe minutes restrictions (load management / coach decision)

Only fetches news for players meeting one or more criteria:
  1. Zero minutes logged (dnp flag or 0 minutes)
  2. Minutes < 15 (potential injury exit or restriction)
  3. Any stat category = 0 AND minutes < 20

Players with normal minutes (>= 20) and non-zero stats across categories
are skipped entirely — no fetch, no entry in output.

Writes data/post_game_news.json. Consumed by auditor.py before reasoning.
Pure Python — no Claude API call.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ── Paths ─────────────────────────────────────────────────────────────
ROOT            = Path(__file__).resolve().parent.parent
DATA            = ROOT / "data"

PICKS_JSON      = DATA / "picks.json"
GAME_LOG_CSV    = DATA / "player_game_log.csv"
PLAYER_DIM_CSV  = DATA / "player_dim.csv"
POST_GAME_JSON  = DATA / "post_game_news.json"

# ── Time ──────────────────────────────────────────────────────────────
ET            = ZoneInfo("America/Los_Angeles")
TODAY         = dt.datetime.now(ET).date()
YESTERDAY     = TODAY - dt.timedelta(days=1)
YESTERDAY_STR = YESTERDAY.strftime("%Y-%m-%d")

# ── Config ────────────────────────────────────────────────────────────
ESPN_NEWS_URL    = (
    "https://site.api.espn.com/apis/common/v3/sports/basketball/nba"
    "/athletes/{athlete_id}/news"
)
REQUEST_TIMEOUT       = 10   # seconds per HTTP call

# Flagging thresholds
MINUTES_DNP_THRESHOLD    = 0    # zero minutes → DNP candidate
MINUTES_LOW_THRESHOLD    = 15   # < 15 min → potential injury exit or restriction
MINUTES_STAT_THRESHOLD   = 20   # < 20 min AND any zero stat → investigate


# ── Data loaders ──────────────────────────────────────────────────────

def load_yesterdays_player_names() -> set[str]:
    """Return unique lowercase player names from yesterday's picks."""
    if not PICKS_JSON.exists():
        print("[post_game_reporter] picks.json not found.")
        return set()
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
        names = {
            p["player_name"].strip().lower()
            for p in all_picks
            if p.get("date") == YESTERDAY_STR and p.get("player_name")
        }
        return names
    except Exception as e:
        print(f"[post_game_reporter] ERROR loading picks.json: {e}")
        return set()


def load_athlete_id_map() -> dict[str, str]:
    """
    Load player_dim.csv and return {player_name_norm (lowercase): player_id}.
    Uses player_name_norm column which is already lowercase.
    Where a player appears multiple times, the most recent row wins.
    """
    id_map: dict[str, str] = {}
    if not PLAYER_DIM_CSV.exists():
        print("[post_game_reporter] player_dim.csv not found — no athlete IDs available.")
        return id_map
    try:
        with open(PLAYER_DIM_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("player_name_norm") or "").strip().lower()
                aid  = (row.get("player_id") or "").strip()
                if name and aid:
                    id_map[name] = aid
    except Exception as e:
        print(f"[post_game_reporter] WARNING: could not load player_dim.csv: {e}")
    return id_map


def load_yesterday_game_rows(player_names: set[str]) -> dict[str, dict]:
    """
    Scan player_game_log.csv for yesterday's rows matching our player list.
    Returns {player_name.lower(): row_dict}.
    Includes DNP rows — callers use the dnp column to detect non-play.
    """
    rows: dict[str, dict] = {}
    if not GAME_LOG_CSV.exists():
        print("[post_game_reporter] player_game_log.csv not found.")
        return rows
    try:
        with open(GAME_LOG_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("game_date", "") != YESTERDAY_STR:
                    continue
                name = (row.get("player_name") or "").strip().lower()
                if name in player_names:
                    rows[name] = row
    except Exception as e:
        print(f"[post_game_reporter] ERROR loading game log: {e}")
    return rows


# ── Flagging logic ────────────────────────────────────────────────────

def parse_minutes(row: dict) -> float | None:
    """
    Parse minutes from a game log row.
    Tries the 'minutes' column first (stored as float string e.g. '32.0'),
    then falls back to 'minutes_raw' for MM:SS format.
    Returns None if unparseable.
    """
    # Primary: minutes column (float string)
    raw = str(row.get("minutes", "") or "").strip()
    if raw and raw not in ("", "nan", "None", "0.0"):
        try:
            return float(raw)
        except ValueError:
            pass

    # Fallback: minutes_raw (may be MM:SS or plain integer)
    raw = str(row.get("minutes_raw", "") or "").strip()
    if not raw or raw in ("", "nan", "None"):
        return None
    m = re.match(r"^(\d+):(\d{2})$", raw)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    try:
        return float(raw)
    except ValueError:
        return None


def is_dnp_row(row: dict) -> bool:
    """Return True if the game log row is flagged as a DNP."""
    try:
        return float(row.get("dnp", 0) or 0) >= 1.0
    except (ValueError, TypeError):
        return False


def should_fetch(game_row: dict | None) -> tuple[bool, str]:
    """
    Determine whether to fetch ESPN news for a player based on their box score.
    Returns (fetch: bool, reason: str).
    """
    if game_row is None:
        # No game log row at all — can't infer anything; skip
        return False, "no_game_row"

    if is_dnp_row(game_row):
        return True, "dnp_flag"

    minutes = parse_minutes(game_row)

    if minutes is not None and minutes <= MINUTES_DNP_THRESHOLD:
        return True, "zero_minutes"

    if minutes is not None and minutes < MINUTES_LOW_THRESHOLD:
        return True, f"low_minutes_{minutes:.1f}"

    # Any zero stat AND minutes < 20
    if minutes is not None and minutes < MINUTES_STAT_THRESHOLD:
        for stat_col in ("pts", "reb", "ast", "tpm"):
            try:
                val = float(game_row.get(stat_col, 1) or 1)
                if val == 0.0:
                    return True, f"zero_{stat_col}_at_{minutes:.0f}min"
            except (ValueError, TypeError):
                pass

    return False, "normal"


# ── ESPN news fetch ───────────────────────────────────────────────────

def fetch_espn_news(athlete_id: str) -> tuple[list[dict], bool]:
    """
    Fetch news items from ESPN athlete news endpoint.
    Returns (news_items, fetch_ok).
    fetch_ok=False means an HTTP/network error occurred.
    """
    url = ESPN_NEWS_URL.format(athlete_id=athlete_id)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("feed", []), True
    except Exception:
        return [], False


# ── Classification ────────────────────────────────────────────────────

_INJURY_EXIT_TERMS = [
    "left the game", "left early", "did not return", "exited", "left in",
    "injured during", "forced from", "helped off", "came off injured",
    "left with", "suffered", "sustained",
]
_DNP_TERMS = [
    "did not play", "dnp", "inactive", "sat out", "scratched",
    "ruled out", "held out", "out due",
]
_RESTRICTION_TERMS = [
    "load management", "minutes restriction", "limited to", "held to",
    "limited minutes", " resting", "rest day", "precautionary",
]


def _extract_url(item: dict) -> str | None:
    links = item.get("links", {})
    if isinstance(links, dict):
        return links.get("web", {}).get("href")
    return None


def classify_from_news(
    news_items: list[dict],
    minutes: float | None,
    game_row: dict | None,
) -> tuple[str, str, str | None, bool]:
    """
    Returns (event_type, detail, source_url, from_news).
    from_news=True means the classification came from explicit ESPN text.
    from_news=False means it was inferred from box score data.

    Scans news items in order — first match wins.
    Falls back to box score inference if no news match found.
    """
    for item in news_items:
        headline    = (item.get("headline") or "").lower()
        description = (item.get("description") or "").lower()
        text        = headline + " " + description
        url         = _extract_url(item)
        raw_detail  = item.get("headline") or item.get("description") or ""

        if any(t in text for t in _INJURY_EXIT_TERMS):
            return "injury_exit", raw_detail, url, True

        if any(t in text for t in _DNP_TERMS):
            return "dnp", raw_detail, url, True

        if any(t in text for t in _RESTRICTION_TERMS):
            return "minutes_restriction", raw_detail, url, True

    # ── Box score inference (no news match) ───────────────────────────
    if game_row is not None and is_dnp_row(game_row):
        return "dnp", "inferred from dnp flag in game log, no ESPN confirmation", None, False

    if minutes is not None and minutes <= MINUTES_DNP_THRESHOLD:
        return "dnp", "inferred from 0 minutes logged, no ESPN confirmation available", None, False

    if minutes is not None and minutes < MINUTES_LOW_THRESHOLD:
        return (
            "minutes_restriction",
            f"Logged {minutes:.0f} minutes — apparent restriction, no ESPN news confirmation",
            None, False,
        )

    return "no_data", "No relevant news found and box score data insufficient to classify", None, False


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[post_game_reporter] Running for {YESTERDAY_STR}")

    player_names = load_yesterdays_player_names()
    if not player_names:
        print("[post_game_reporter] No yesterday's picks found — exiting.")
        _write_empty()
        return

    print(f"[post_game_reporter] Yesterday's picks: {len(player_names)} unique players")

    athlete_ids = load_athlete_id_map()
    game_rows   = load_yesterday_game_rows(player_names)

    # Determine which players need a news fetch
    to_fetch: list[tuple[str, str]] = []  # (name, flag_reason)
    for name in sorted(player_names):
        row = game_rows.get(name)
        flag, reason = should_fetch(row)
        if flag:
            to_fetch.append((name, reason))

    print(
        f"[post_game_reporter] Players flagged for news fetch: {len(to_fetch)}"
        f" (low minutes or zero stats)"
    )

    players_out: dict[str, dict] = {}
    fetch_errors: list[str] = []

    for name, flag_reason in to_fetch:
        game_row = game_rows.get(name)
        minutes  = parse_minutes(game_row) if game_row else None
        aid      = athlete_ids.get(name)

        news_items: list[dict] = []
        if aid:
            news_items, fetch_ok = fetch_espn_news(aid)
            if not fetch_ok:
                fetch_errors.append(name)
        # No athlete_id → proceed with box score inference (not a fetch error)

        event_type, detail, source_url, from_news = classify_from_news(
            news_items, minutes, game_row
        )

        confidence = "confirmed" if from_news else "inferred"
        mins_display = round(minutes, 1) if minutes is not None else 0

        players_out[name] = {
            "event_type":    event_type,
            "detail":        detail,
            "minutes_played": mins_display,
            "source_url":    source_url,
            "confidence":    confidence,
        }

        mins_str = f"{minutes:.0f}" if minutes is not None else "?"
        print(
            f"[post_game_reporter] {name} → {event_type} ({confidence}, {mins_str} min)"
        )

    output = {
        "date":         YESTERDAY_STR,
        "generated_at": dt.datetime.now(ET).isoformat(),
        "players":      players_out,
        "fetch_errors": fetch_errors,
    }

    with open(POST_GAME_JSON, "w") as f:
        json.dump(output, f, indent=2)

    n_events = sum(
        1 for v in players_out.values() if v["event_type"] != "no_data"
    )
    print(
        f"[post_game_reporter] Saved post_game_news.json"
        f" ({n_events} events, {len(fetch_errors)} fetch errors)"
    )


def _write_empty() -> None:
    """Write an empty post_game_news.json so auditor.py never fails on missing file."""
    output = {
        "date":         YESTERDAY_STR,
        "generated_at": dt.datetime.now(ET).isoformat(),
        "players":      {},
        "fetch_errors": [],
    }
    with open(POST_GAME_JSON, "w") as f:
        json.dump(output, f, indent=2)


if __name__ == "__main__":
    main()
