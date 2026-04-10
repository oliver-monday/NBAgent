#!/usr/bin/env python3
"""
NBAgent — Post-Game Reporter

WORKFLOW NOTE: This script must run BEFORE auditor.py in the auditor workflow.
Add a step in auditor.yml to run this script immediately before the auditor.py step.

Fetches ESPN recap pages, ESPN athlete news, and Rotowire news for players
from yesterday's picks. Uses a single Claude API call to classify post-game
events and generate narratives for missed picks.

Event types:
  - injury_exit:        Mid-game injury departure
  - dnp:                Did not play (pre-game decision)
  - minutes_restriction: Played but on limited minutes
  - no_data:            Insufficient information to classify

Writes data/post_game_news.json. Consumed by auditor.py before reasoning.
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
from bs4 import BeautifulSoup

# ── Paths ─────────────────────────────────────────────────────────────
ROOT            = Path(__file__).resolve().parent.parent
DATA            = ROOT / "data"

PICKS_JSON      = DATA / "picks.json"
GAME_LOG_CSV    = DATA / "player_game_log.csv"
PLAYER_DIM_CSV  = DATA / "player_dim.csv"
POST_GAME_JSON  = DATA / "post_game_news.json"
MASTER_CSV      = DATA / "nba_master.csv"

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
ESPN_RECAP_URL   = "https://www.espn.com/nba/recap/_/gameId/{game_id}"
ROTOWIRE_NEWS_URL  = "https://www.rotowire.com/basketball/news.php"
ROTOWIRE_LOGIN_URL = "https://www.rotowire.com/users/login.php"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT       = 10   # seconds per HTTP call

# Claude config
CLAUDE_MODEL      = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 2048
RECAP_MAX_CHARS   = 3000

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


def _norm_name(name: str) -> str:
    """Normalize player name to match player_dim.csv's player_name_norm convention.
    Hyphens → space, apostrophes/periods removed, collapse whitespace, lowercase."""
    s = name.lower().strip()
    s = s.replace("-", " ")
    for ch in ("'", "\u2019", "."):
        s = s.replace(ch, "")
    return " ".join(s.split())


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


# ── ESPN recap fetch ─────────────────────────────────────────────────

def load_yesterdays_game_ids(player_teams: set[str]) -> dict[str, str]:
    """
    Read nba_master.csv and return {game_id: "HOME vs AWAY"} for yesterday's
    games that involve at least one team from player_teams.
    """
    _ABBR_NORM = {
        "GS": "GSW", "SA": "SAS", "NY": "NYK", "NO": "NOP",
        "UTAH": "UTA", "WSH": "WAS",
    }
    games: dict[str, str] = {}
    if not MASTER_CSV.exists():
        print("[post_game_reporter] nba_master.csv not found — no recap game IDs.")
        return games
    try:
        with open(MASTER_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("game_date", "") != YESTERDAY_STR:
                    continue
                gid = (row.get("game_id") or "").strip()
                home = _ABBR_NORM.get(
                    (row.get("home_team_abbrev") or "").strip().upper(),
                    (row.get("home_team_abbrev") or "").strip().upper(),
                )
                away = _ABBR_NORM.get(
                    (row.get("away_team_abbrev") or "").strip().upper(),
                    (row.get("away_team_abbrev") or "").strip().upper(),
                )
                if not gid:
                    continue
                if home in player_teams or away in player_teams:
                    games[gid] = f"{away} @ {home}"
        print(f"[post_game_reporter] Found {len(games)} yesterday games for recap fetch")
    except Exception as e:
        print(f"[post_game_reporter] WARNING: could not load nba_master.csv for game IDs: {e}")
    return games


def fetch_espn_recaps(game_ids: dict[str, str]) -> dict[str, str]:
    """
    Fetch ESPN recap pages for each game_id.
    Returns {game_id: recap_text} — truncated to RECAP_MAX_CHARS.
    Gracefully skips games where the recap is unavailable.
    """
    recaps: dict[str, str] = {}
    for gid, matchup in game_ids.items():
        url = ESPN_RECAP_URL.format(game_id=gid)
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"[post_game_reporter] recap {gid} ({matchup}): HTTP {resp.status_code}")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # ESPN recaps use <div class="Story__Body"> or article body paragraphs
            story = soup.find("div", class_="Story__Body")
            if story:
                text = story.get_text(separator=" ", strip=True)
            else:
                # Fallback: collect all <p> inside the main article area
                article = soup.find("article") or soup
                paragraphs = article.find_all("p")
                text = " ".join(p.get_text(strip=True) for p in paragraphs)
            if text:
                recaps[gid] = text[:RECAP_MAX_CHARS]
                print(f"[post_game_reporter] recap OK: {matchup} ({len(text)} chars)")
            else:
                print(f"[post_game_reporter] recap {gid} ({matchup}): no text found")
        except Exception as e:
            print(f"[post_game_reporter] recap {gid} ({matchup}) failed: {e}")
    return recaps


# ── Rotowire news fetch ─────────────────────────────────────────────

def login_rotowire() -> requests.Session | None:
    """
    Authenticate with Rotowire. Returns an authenticated Session or None.
    Same pattern as ingest/rotowire_injuries_only.py.
    """
    email = os.environ.get("ROTOWIRE_EMAIL", "")
    password = os.environ.get("ROTOWIRE_PASSWORD", "")
    if not email or not password:
        print("[post_game_reporter] ROTOWIRE_EMAIL / ROTOWIRE_PASSWORD not set — skipping Rotowire news")
        return None
    session = requests.Session()
    try:
        resp = session.post(
            ROTOWIRE_LOGIN_URL,
            data={"email": email, "password": password},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            print("[post_game_reporter] Rotowire login OK")
            return session
        else:
            print(f"[post_game_reporter] Rotowire login failed: HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"[post_game_reporter] Rotowire login error: {e}")
        return None


def fetch_rotowire_news(
    session: requests.Session,
    player_names: set[str],
) -> dict[str, list[str]]:
    """
    Fetch Rotowire news.php and extract news blurbs for relevant players.
    Returns {player_name_lower: [blurb1, blurb2, ...]}.
    """
    result: dict[str, list[str]] = {}
    try:
        resp = session.get(
            ROTOWIRE_NEWS_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"[post_game_reporter] Rotowire news.php: HTTP {resp.status_code}")
            return result
        soup = BeautifulSoup(resp.text, "html.parser")
        # Rotowire news items are typically in divs with news-update class or similar
        # Look for player name links and their associated text
        news_items = soup.find_all("div", class_=re.compile(r"news-update|news_item|news-item"))
        if not news_items:
            # Broader fallback: look for any structured news blocks
            news_items = soup.find_all("div", class_=re.compile(r"news"))
        for item in news_items:
            # Try to find player name in the item
            text = item.get_text(separator=" ", strip=True)
            if not text:
                continue
            text_lower = text.lower()
            for pname in player_names:
                # Match on last name (more robust against abbreviated first names)
                last_name = pname.split()[-1] if pname.split() else pname
                if last_name in text_lower:
                    if pname not in result:
                        result[pname] = []
                    # Truncate individual blurbs
                    result[pname].append(text[:500])
        total_blurbs = sum(len(v) for v in result.values())
        print(f"[post_game_reporter] Rotowire news: {len(result)} players, {total_blurbs} blurbs")
    except Exception as e:
        print(f"[post_game_reporter] Rotowire news fetch error: {e}")
    return result


# ── Claude classification ────────────────────────────────────────────

def call_claude_classify_events(players_context: list[dict]) -> dict[str, dict]:
    """
    Single Claude API call to classify post-game events AND generate narratives.

    players_context: list of dicts, each with:
        name, team, minutes, is_missed_pick, injury_status,
        espn_news_headlines, recap_text, rotowire_blurbs,
        pick_meta (optional: prop_type, pick_value, actual_value)

    Returns {player_name_lower: {event_type, detail, confidence, web_narrative}}.
    Returns {} on failure (graceful degradation).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[post_game_reporter] ANTHROPIC_API_KEY not set — skipping Claude classification.")
        return {}

    if not players_context:
        return {}

    # Build per-player context blocks
    player_blocks = []
    for ctx in players_context:
        name = ctx["name"]
        team = ctx.get("team", "")
        minutes = ctx.get("minutes")
        mins_str = f"{minutes:.0f}" if minutes is not None else "unknown"
        injury_status = ctx.get("injury_status", "NOT_LISTED")
        is_missed = ctx.get("is_missed_pick", False)

        block = f"PLAYER: {name} ({team})\n"
        block += f"Minutes played: {mins_str}\n"
        block += f"Pre-game injury status: {injury_status}\n"

        if is_missed:
            meta = ctx.get("pick_meta", {})
            if meta:
                block += (
                    f"MISSED PICK: {meta.get('prop_type', '')} OVER "
                    f"{meta.get('pick_value', '')} "
                    f"(actual: {meta.get('actual_value', '')})\n"
                )

        # ESPN athlete news
        headlines = ctx.get("espn_news_headlines", [])
        if headlines:
            block += "ESPN ATHLETE NEWS:\n"
            for h in headlines[:5]:
                block += f"  - {h}\n"

        # ESPN recap
        recap = ctx.get("recap_text", "")
        if recap:
            block += f"ESPN GAME RECAP EXCERPT:\n  {recap}\n"

        # Rotowire
        blurbs = ctx.get("rotowire_blurbs", [])
        if blurbs:
            block += "ROTOWIRE NEWS:\n"
            for b in blurbs[:3]:
                block += f"  - {b}\n"

        # Flag if no sources available
        if not headlines and not recap and not blurbs:
            block += "NO EXTERNAL SOURCES AVAILABLE — classify from box score only.\n"

        player_blocks.append(block)

    user_prompt = (
        f"Date: {YESTERDAY_STR}\n\n"
        f"For each player below, classify the post-game event and provide a brief narrative.\n\n"
        f"EVENT TYPES (choose exactly one per player):\n"
        f"  injury_exit — Player left the game due to injury before normal completion\n"
        f"  dnp — Player did not play at all (injury scratch, coach decision, rest)\n"
        f"  minutes_restriction — Player played but on clearly limited minutes\n"
        f"  no_data — Insufficient information to classify; normal game or no flag\n\n"
        f"CONFIDENCE (choose one):\n"
        f"  confirmed — Source explicitly states the event (injury report, quote, recap text)\n"
        f"  inferred — Classification inferred from box score + context, no explicit source\n\n"
        f"For MISSED PICK players: also provide a factual 1-2 sentence 'narrative' explaining\n"
        f"why they missed their prop (injury exit, foul trouble, blowout, cold shooting, etc.).\n"
        f"If sources don't explain the miss, set narrative to null.\n\n"
        f"For non-missed players with normal minutes and no flags: classify as no_data\n"
        f"with null narrative. Do not speculate.\n\n"
        f"Respond ONLY with valid JSON — no preamble, no markdown fences:\n"
        f'{{"players": [\n'
        f'  {{"name": "Player Name", "event_type": "...", "detail": "short description", '
        f'"confidence": "confirmed|inferred", "narrative": "string or null"}}\n'
        f"]}}\n\n"
        + "\n---\n\n".join(player_blocks)
    )

    system_prompt = (
        "You are a factual sports reporter classifying NBA post-game events. "
        "Use the provided sources (ESPN recaps, ESPN athlete news, Rotowire news) "
        "to determine what happened to each player. Prioritize explicit source evidence "
        "over inference. If a source says a player 'left with' or 'exited' or 'won't return' "
        "or 'did not return' or any variation indicating a mid-game departure, classify as "
        "injury_exit with confidence=confirmed. Return only valid JSON."
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)
        data = json.loads(raw)

        results: dict[str, dict] = {}
        for entry in data.get("players", []):
            name_key = (entry.get("name") or "").strip().lower()
            if not name_key:
                continue
            results[name_key] = {
                "event_type":  entry.get("event_type", "no_data"),
                "detail":      entry.get("detail", ""),
                "confidence":  entry.get("confidence", "inferred"),
                "web_narrative": entry.get("narrative"),
            }
        print(f"[post_game_reporter] Claude classified {len(results)} player(s)")
        return results
    except Exception as e:
        print(f"[post_game_reporter] WARNING: Claude classification failed: {e}")
        return {}


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

    # Classify each player's fetch reason for logging
    players_to_fetch: set[str] = set()
    fetch_reasons: dict[str, str] = {}
    missed_count = 0
    box_score_count = 0
    rest_count = 0
    for name in sorted(player_names):
        row = game_rows.get(name)
        _flag, reason = should_fetch(row, is_missed_pick=(name in missed_pick_names))
        fetch_reasons[name] = reason
        if reason == "missed_pick":
            missed_count += 1
            players_to_fetch.add(name)
        elif reason == "normal":
            rest_count += 1
            players_to_fetch.add(name)  # still fetch for universal coverage
        else:
            box_score_count += 1
            players_to_fetch.add(name)

    print(
        f"[post_game_reporter] Processing {len(players_to_fetch)} players"
        f" ({missed_count} missed picks, {box_score_count} box score flags,"
        f" {rest_count} routine)"
    )

    # ── Step 1: Fetch ESPN athlete news per player ────────────────────
    espn_news_by_player: dict[str, list[dict]] = {}
    fetch_errors: list[str] = []
    espn_fetch_status: dict[str, bool | None] = {}

    for name in sorted(players_to_fetch):
        aid = athlete_ids.get(_norm_name(name))
        if aid:
            news_items, fetch_ok = fetch_espn_news(aid)
            espn_news_by_player[name] = news_items
            espn_fetch_status[name] = fetch_ok
            if not fetch_ok:
                fetch_errors.append(name)
        else:
            espn_news_by_player[name] = []
            espn_fetch_status[name] = None  # no athlete ID

    # ── Step 2: Fetch ESPN recaps per game ────────────────────────────
    # Collect team abbreviations from picks for filtering game_ids
    player_teams: set[str] = set()
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
        for p in all_picks:
            if p.get("date") == YESTERDAY_STR and p.get("team"):
                player_teams.add(p["team"].strip().upper())
    except Exception:
        pass

    game_ids = load_yesterdays_game_ids(player_teams)
    recaps = fetch_espn_recaps(game_ids)

    # Map each player to their game's recap text
    # Build player→game_id map from game_rows (team_abbrev + opp_abbrev)
    player_recap: dict[str, str] = {}
    if recaps:
        # Build game_id lookup from game_log rows
        for name in players_to_fetch:
            row = game_rows.get(name)
            if not row:
                continue
            gid = (row.get("game_id") or "").strip()
            if gid and gid in recaps:
                player_recap[name] = recaps[gid]

    # ── Step 3: Fetch Rotowire news ──────────────────────────────────
    rotowire_news: dict[str, list[str]] = {}
    rw_session = login_rotowire()
    if rw_session:
        rotowire_news = fetch_rotowire_news(rw_session, players_to_fetch)

    # ── Step 4: Build context and call Claude ─────────────────────────
    players_context: list[dict] = []
    for name in sorted(players_to_fetch):
        row = game_rows.get(name)
        minutes = parse_minutes(row) if row else None
        injury_status = injury_statuses.get(name, "NOT_LISTED")
        is_missed = name in missed_pick_names

        # ESPN news headlines
        headlines = []
        for item in espn_news_by_player.get(name, []):
            h = item.get("headline", "")
            d = item.get("description", "")
            if h or d:
                headlines.append(f"{h}: {d}" if h and d else (h or d))

        # Pick meta for missed picks
        pick_meta = _get_miss_pick_meta(name) if is_missed else {}

        ctx = {
            "name": name,
            "team": pick_meta.get("team", "") or (row.get("team_abbrev", "") if row else ""),
            "minutes": minutes,
            "is_missed_pick": is_missed,
            "injury_status": injury_status,
            "espn_news_headlines": headlines[:5],
            "recap_text": player_recap.get(name, ""),
            "rotowire_blurbs": rotowire_news.get(name, [])[:3],
            "pick_meta": pick_meta,
        }
        players_context.append(ctx)

    # Call Claude for classification
    claude_results = call_claude_classify_events(players_context)

    # ── Step 5: Build players_out with fallback ───────────────────────
    players_out: dict[str, dict] = {}

    for name in sorted(players_to_fetch):
        row = game_rows.get(name)
        minutes = parse_minutes(row) if row else None
        injury_status = injury_statuses.get(name, "NOT_LISTED")
        aid = athlete_ids.get(_norm_name(name))

        # Use Claude result if available, else fall back to deterministic DNP detection
        cr = claude_results.get(name)
        if cr:
            event_type = cr["event_type"]
            detail = cr["detail"]
            confidence = cr["confidence"]
            web_narrative = cr.get("web_narrative")
        else:
            # Fallback: basic deterministic classification
            web_narrative = None
            if row is not None and is_dnp_row(row):
                event_type = "dnp"
                detail = "inferred from dnp flag in game log (Claude unavailable)"
                confidence = "inferred"
            elif minutes is not None and minutes <= MINUTES_DNP_THRESHOLD:
                event_type = "dnp"
                detail = "inferred from 0 minutes logged (Claude unavailable)"
                confidence = "inferred"
            elif minutes is not None and minutes < MINUTES_LOW_THRESHOLD:
                event_type = "minutes_restriction"
                detail = f"Logged {minutes:.0f} minutes — apparent restriction (Claude unavailable)"
                confidence = "inferred"
            else:
                event_type = "no_data"
                detail = "No classification available"
                confidence = "inferred"

        mins_display = round(minutes, 1) if minutes is not None else 0

        players_out[name] = {
            "event_type":               event_type,
            "detail":                   detail,
            "minutes_played":           mins_display,
            "source_url":               None,
            "confidence":               confidence,
            "injury_status_at_check":   injury_status,
            "injury_language_detected": False,  # legacy field — always False in new pipeline
            "injury_scan_term":         None,   # legacy field — always None in new pipeline
            "espn_fetch_ok":            espn_fetch_status.get(name),
            "web_narrative":            web_narrative,
        }

        mins_str = f"{minutes:.0f}" if minutes is not None else "?"
        print(
            f"[post_game_reporter] {name} → {event_type} ({confidence}, {mins_str} min)"
            f" [reason: {fetch_reasons.get(name, 'unknown')}]"
        )

    # ── Step 6: Write output ──────────────────────────────────────────
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
