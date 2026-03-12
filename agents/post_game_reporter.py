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

import os

import anthropic
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

# Web narrative config
WEB_SEARCH_MODEL  = "claude-sonnet-4-6"
WEB_SEARCH_TOKENS = 2048
BRAVE_SEARCH_URL  = "https://api.search.brave.com/res/v1/web/search"

# Injury language scan terms — broader than _INJURY_EXIT_TERMS, for detection only
INJURY_SCAN_TERMS = [
    "injur", "injured", "injury",          # covers 'injury', 'injured', 'injuries'
    "left the game", "left early",
    "did not return", "did not finish",
    "exited", "forced out", "helped off",
    "knee", "ankle", "hamstring", "calf", "shoulder", "wrist", "hand",
    "groin", "back", "hip", "foot", "achilles",
    "sprain", "strain", "soreness", "tightness",
    "bruised", "bruise", "contusion",
    "concussion", "head",
]


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


def load_yesterdays_missed_pick_names() -> set[str]:
    """
    Return lowercase player names from yesterday's picks where result == "MISS".
    Ungraded picks (result=None) are excluded — the reporter runs before the auditor
    grades picks, so including None would treat every ungraded pick as a missed pick
    and fetch Brave/ESPN for all players regardless of outcome.
    Only explicitly-graded MISSes trigger web narrative enrichment.
    """
    if not PICKS_JSON.exists():
        return set()
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
        names = {
            p["player_name"].strip().lower()
            for p in all_picks
            if p.get("date") == YESTERDAY_STR
            and p.get("player_name")
            and p.get("result") == "MISS"
        }
        return names
    except Exception as e:
        print(f"[post_game_reporter] ERROR loading picks for miss check: {e}")
        return set()


def load_yesterdays_picks_with_status() -> dict[str, str]:
    """
    Return {player_name.lower(): injury_status_at_check} for yesterday's picks.
    Only includes players where injury_status_at_check is present.
    If a player has multiple picks yesterday, the most severe status wins
    (OUT > DOUBTFUL > QUESTIONABLE > NOT_LISTED).
    """
    SEVERITY = {"OUT": 4, "DOUBTFUL": 3, "QUESTIONABLE": 2, "NOT_LISTED": 1}
    if not PICKS_JSON.exists():
        return {}
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
        result: dict[str, str] = {}
        for p in all_picks:
            if p.get("date") != YESTERDAY_STR:
                continue
            name   = (p.get("player_name") or "").strip().lower()
            status = (p.get("injury_status_at_check") or "").strip().upper()
            if not name or not status:
                continue
            existing = result.get(name)
            if existing is None or SEVERITY.get(status, 0) > SEVERITY.get(existing, 0):
                result[name] = status
        return result
    except Exception as e:
        print(f"[post_game_reporter] WARNING: could not load injury statuses: {e}")
        return {}


def _get_miss_pick_meta(player_name_lower: str) -> dict:
    """
    Return prop context for a missed-pick player: prop_type, pick_value, actual_value, team.
    Uses the first MISS (or ungraded) pick found for this player on YESTERDAY_STR.
    Returns empty dict if not found.
    """
    if not PICKS_JSON.exists():
        return {}
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
        for p in all_picks:
            if (
                p.get("date") == YESTERDAY_STR
                and (p.get("player_name") or "").strip().lower() == player_name_lower
                and p.get("result") in ("MISS", None)
            ):
                return {
                    "prop_type":    p.get("prop_type", ""),
                    "pick_value":   str(p.get("pick_value", "")),
                    "actual_value": str(p.get("actual_value", "")),
                    "team":         p.get("team", ""),
                }
    except Exception:
        pass
    return {}


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


def should_fetch(game_row: dict | None, is_missed_pick: bool = False) -> tuple[bool, str]:
    """
    Determine whether to fetch ESPN news for a player based on their box score.
    Returns (fetch: bool, reason: str).
    """
    if is_missed_pick:
        return True, "missed_pick"

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


# ── Injury language scanner ───────────────────────────────────────────

def news_contains_injury_language(news_items: list[dict]) -> tuple[bool, str]:
    """
    Scan all news items for injury-related language.
    Returns (found: bool, matched_term: str).
    Checks headline + description of each item.
    First match wins.
    """
    for item in news_items:
        headline    = (item.get("headline") or "").lower()
        description = (item.get("description") or "").lower()
        text        = headline + " " + description
        for term in INJURY_SCAN_TERMS:
            if term in text:
                return True, term
    return False, ""


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


# ── Web narrative fetch + summarisation ───────────────────────────────

def fetch_web_narratives(missed_players: list[dict]) -> dict[str, str]:
    """
    For each missed-pick player, run a Brave web search for a game recap
    and return {player_name_lower: raw_snippet_text}.

    missed_players is a list of dicts: [{"name": str, "team": str, "prop": str,
    "pick_value": str, "actual": str, "minutes": float|None}]

    Returns empty dict if BRAVE_API_KEY is not set or all searches fail.
    Never crashes — logs warnings and returns partial results on error.
    """
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        print("[post_game_reporter] BRAVE_API_KEY not set — skipping web narrative fetch.")
        return {}

    results: dict[str, str] = {}
    date_str = YESTERDAY.strftime("%B %-d, %Y")   # e.g. "March 10, 2026"

    for player in missed_players:
        name  = player["name"]
        team  = player.get("team", "")
        query = f"{name} {team} NBA recap {date_str}"
        try:
            resp = requests.get(
                BRAVE_SEARCH_URL,
                headers={
                    "Accept":              "application/json",
                    "Accept-Encoding":     "gzip",
                    "X-Subscription-Token": api_key,
                },
                params={"q": query, "count": 3, "search_lang": "en"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            snippets = []
            for result in data.get("web", {}).get("results", []):
                title       = result.get("title", "")
                description = result.get("description", "")
                if title or description:
                    snippets.append(f"{title}: {description}")
            if snippets:
                results[name.lower()] = "\n".join(snippets)
                print(f"[post_game_reporter] web search OK: {name} ({len(snippets)} snippets)")
            else:
                print(f"[post_game_reporter] web search: no snippets for {name}")
        except Exception as e:
            print(f"[post_game_reporter] WARNING: web search failed for {name}: {e}")

    return results


def call_claude_summarise_narratives(
    missed_players: list[dict],
    raw_snippets:   dict[str, str],
) -> dict[str, str]:
    """
    Single Claude call: given web search snippets for all missed-pick players,
    extract a concise factual narrative per player explaining why they missed
    their prop (ejection, foul trouble, early exit, game script, etc.).

    missed_players: same list of dicts as passed to fetch_web_narratives().
    raw_snippets: {player_name_lower: snippet_text} from fetch_web_narratives().

    Returns {player_name_lower: narrative_string} for players where a
    meaningful narrative was found. Returns {} on any API failure.
    Never crashes.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[post_game_reporter] ANTHROPIC_API_KEY not set — skipping narrative summarisation.")
        return {}

    # Only include players where we have snippets
    players_with_snippets = [
        p for p in missed_players if p["name"].lower() in raw_snippets
    ]
    if not players_with_snippets:
        print("[post_game_reporter] No web snippets to summarise.")
        return {}

    # Build the user prompt
    player_blocks = []
    for p in players_with_snippets:
        name    = p["name"]
        prop    = p.get("prop", "")
        pick_v  = p.get("pick_value", "")
        actual  = p.get("actual", "")
        mins    = p.get("minutes")
        mins_str = f"{mins:.0f}" if mins is not None else "unknown"
        snippets = raw_snippets[name.lower()]
        player_blocks.append(
            f"PLAYER: {name}\n"
            f"MISSED PICK: {prop} OVER {pick_v} (actual: {actual}, minutes: {mins_str})\n"
            f"WEB SEARCH SNIPPETS:\n{snippets}"
        )

    user_prompt = (
        f"Today is {YESTERDAY_STR}. The following NBA players missed their prop picks last night.\n"
        f"For each player, use the web search snippets to extract a factual one-to-two sentence\n"
        f"explanation of WHY they missed — e.g. ejection, foul trouble, early injury exit,\n"
        f"coaching decision, blowout garbage time, cold shooting, etc.\n\n"
        f"Be factual and specific. If the snippets do not explain the miss clearly, write null.\n"
        f"Do not speculate beyond what the snippets confirm.\n\n"
        f"Respond ONLY with a JSON object — no preamble, no markdown fences:\n"
        f'{{"players": [{{"name": "player name", "narrative": "one-to-two sentence explanation or null"}}]}}\n\n'
        + "\n\n---\n\n".join(player_blocks)
    )

    system_prompt = (
        "You are a factual sports reporter extracting game narrative from web search snippets. "
        "Return only valid JSON. If snippets are insufficient to explain a miss factually, "
        "return null for that player's narrative. Never invent facts not in the snippets."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=WEB_SEARCH_MODEL,
            max_tokens=WEB_SEARCH_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)
        narratives: dict[str, str] = {}
        for entry in data.get("players", []):
            name_key  = (entry.get("name") or "").strip().lower()
            narrative = entry.get("narrative")
            if name_key and narrative:
                narratives[name_key] = narrative
        print(f"[post_game_reporter] Claude narratives: {len(narratives)} player(s) summarised")
        return narratives
    except Exception as e:
        print(f"[post_game_reporter] WARNING: Claude narrative summarisation failed: {e}")
        return {}


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
    injury_status: str = "NOT_LISTED",
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

    # ── Pre-game status inference ──────────────────────────────────────
    # If player was QUESTIONABLE or DOUBTFUL pre-game and has no/zero box score,
    # the DNP is likely injury-related even without an explicit ESPN news match.
    if injury_status in ("QUESTIONABLE", "DOUBTFUL", "OUT"):
        if game_row is None or (minutes is not None and minutes <= MINUTES_DNP_THRESHOLD):
            status_detail = (
                f"Player was {injury_status} pre-game and logged 0 minutes. "
                f"Likely DNP due to pre-game injury designation — no ESPN confirmation found."
            )
            return "dnp", status_detail, None, False
        elif minutes is not None and minutes < MINUTES_LOW_THRESHOLD:
            status_detail = (
                f"Player was {injury_status} pre-game and logged only {minutes:.0f} minutes. "
                f"Possible early exit or minutes restriction — no ESPN confirmation found."
            )
            return "minutes_restriction", status_detail, None, False

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

    athlete_ids       = load_athlete_id_map()
    game_rows         = load_yesterday_game_rows(player_names)
    missed_pick_names = load_yesterdays_missed_pick_names()
    injury_statuses   = load_yesterdays_picks_with_status()

    # Classify each player's fetch reason for logging, but fetch ALL players
    missed_count    = 0
    box_score_count = 0
    rest_count      = 0
    fetch_reasons: dict[str, str] = {}
    for name in sorted(player_names):
        row = game_rows.get(name)
        _flag, reason = should_fetch(row, is_missed_pick=(name in missed_pick_names))
        fetch_reasons[name] = reason
        if reason == "missed_pick":
            missed_count += 1
        elif reason == "normal":
            rest_count += 1
        else:
            box_score_count += 1

    print(
        f"[post_game_reporter] Fetching news for {len(player_names)} players"
        f" ({missed_count} missed picks, {box_score_count} box score flags,"
        f" {rest_count} routine checks)"
    )

    players_out: dict[str, dict] = {}
    fetch_errors: list[str] = []

    for name in sorted(player_names):
        flag_reason = fetch_reasons[name]
        game_row    = game_rows.get(name)
        minutes     = parse_minutes(game_row) if game_row else None
        aid         = athlete_ids.get(name)

        news_items: list[dict] = []
        fetch_ok = None  # None = no athlete ID (ESPN not attempted)
        if aid:
            news_items, fetch_ok = fetch_espn_news(aid)
            if not fetch_ok:
                fetch_errors.append(name)
        # No athlete_id → proceed with box score inference (not a fetch error)

        injury_status = injury_statuses.get(name, "NOT_LISTED")
        event_type, detail, source_url, from_news = classify_from_news(
            news_items, minutes, game_row, injury_status=injury_status
        )

        inj_detected, inj_term = news_contains_injury_language(news_items)

        # Promote no_data → dnp/injury_exit when injury language exists in news
        # but the classifier couldn't find an exact term match.
        if event_type == "no_data" and inj_detected:
            if minutes is None or minutes <= MINUTES_DNP_THRESHOLD:
                event_type = "dnp"
                detail = (
                    f"Promoted from no_data: injury language detected in ESPN news "
                    f"(matched: '{inj_term}') and player logged 0 or no minutes. "
                    f"Likely DNP due to injury — exact classification unconfirmed."
                )
                from_news = True
            elif minutes is not None and minutes < MINUTES_LOW_THRESHOLD:
                event_type = "injury_exit"
                detail = (
                    f"Promoted from no_data: injury language detected in ESPN news "
                    f"(matched: '{inj_term}') and player logged only {minutes:.0f} minutes. "
                    f"Possible mid-game injury exit — exact classification unconfirmed."
                )
                from_news = True

            if event_type != "no_data":
                print(
                    f"[post_game_reporter] ↑ {name}: promoted no_data → {event_type}"
                    f" (injury term: '{inj_term}')"
                )

        if inj_detected and event_type == "no_data":
            print(
                f"[post_game_reporter] ⚠ {name}: injury language detected"
                f" ('{inj_term}') but minutes normal ({minutes} min) — no promotion, check manually"
            )

        confidence   = "confirmed" if from_news else "inferred"
        mins_display = round(minutes, 1) if minutes is not None else 0

        players_out[name] = {
            "event_type":               event_type,
            "detail":                   detail,
            "minutes_played":           mins_display,
            "source_url":               source_url,
            "confidence":               confidence,
            "injury_status_at_check":   injury_status,
            "injury_language_detected": inj_detected,
            "injury_scan_term":         inj_term if inj_detected else None,
            "espn_fetch_ok":            fetch_ok if aid else None,  # None = no athlete ID
            "web_narrative":            None,  # populated later for missed picks
        }

        mins_str = f"{minutes:.0f}" if minutes is not None else "?"
        print(
            f"[post_game_reporter] {name} → {event_type} ({confidence}, {mins_str} min)"
            f" [reason: {flag_reason}]"
        )

    # ── Web narrative enrichment (missed picks only) ───────────────────
    missed_player_records: list[dict] = []
    for name in sorted(missed_pick_names):
        row     = game_rows.get(name)
        minutes = parse_minutes(row) if row else None
        # Pull pick details from picks.json for context
        # We use the first MISS pick for this player (prop + pick_value + actual)
        pick_meta = _get_miss_pick_meta(name)
        missed_player_records.append({
            "name":       name,
            "team":       pick_meta.get("team", ""),
            "prop":       pick_meta.get("prop_type", ""),
            "pick_value": pick_meta.get("pick_value", ""),
            "actual":     pick_meta.get("actual_value", ""),
            "minutes":    minutes,
        })

    web_narratives: dict[str, str] = {}
    if missed_player_records:
        raw_snippets   = fetch_web_narratives(missed_player_records)
        web_narratives = call_claude_summarise_narratives(missed_player_records, raw_snippets)

    # Merge web_narrative into players_out entries
    for name, narrative in web_narratives.items():
        if name in players_out:
            players_out[name]["web_narrative"] = narrative
        else:
            # Player had no ESPN event but has a web narrative — create minimal entry
            players_out[name] = {
                "event_type":               "no_data",
                "detail":                   "No ESPN news or box score flag. Web narrative only.",
                "minutes_played":           None,
                "source_url":               None,
                "confidence":               "web_search",
                "injury_status_at_check":   "NOT_LISTED",
                "injury_language_detected": False,
                "injury_scan_term":         None,
                "espn_fetch_ok":            None,  # no athlete ID lookup for narrative-only entries
                "web_narrative":            narrative,
            }

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
