#!/usr/bin/env python3
"""
NBAgent — Pre-Game Reporter

WORKFLOW NOTE: This script must run AFTER quant.py and BEFORE analyst.py
in the analyst workflow. Add it as a step in analyst.yml between the
quant.py step and the analyst.py step.

Fetches ESPN news for every whitelisted player on today's slate.
Filters raw news items to only those material to prop selection.
Calls Claude once (batch, not per-player) to distill filtered items
into concise per-player and per-game summaries.
Writes data/pre_game_news.json for the Analyst to consume before
generating picks.

Filtering logic: drop items that contain noise keywords (contracts, fines,
etc.) AND lack any prop-relevant keyword (out, questionable, minutes, etc.).
Items that reference availability, role, or minutes are always kept.

Fully failure-safe — never blocks a run. On any error (missing file, ESPN
fetch failure, Claude failure), writes the output file with empty
player_notes and game_notes so analyst.py always finds the file.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import requests

# ── Paths ─────────────────────────────────────────────────────────────
ROOT           = Path(__file__).resolve().parent.parent
DATA           = ROOT / "data"

MASTER_CSV       = DATA / "nba_master.csv"
WHITELIST_CSV    = ROOT / "playerprops" / "player_whitelist.csv"
PLAYER_DIM_CSV   = DATA / "player_dim.csv"
PRE_GAME_JSON    = DATA / "pre_game_news.json"
CONTEXT_MD       = ROOT / "context" / "nba_season_context.md"
CONTEXT_FLAGS_MD = DATA / "context_flags.md"

# ── Time ──────────────────────────────────────────────────────────────
ET        = ZoneInfo("America/Los_Angeles")
NOW       = dt.datetime.now(ET)
TODAY     = NOW.date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ────────────────────────────────────────────────────────────
ESPN_ATHLETE_NEWS_URL = (
    "https://site.api.espn.com/apis/common/v3/sports/basketball/nba"
    "/athletes/{athlete_id}/news"
)
ESPN_LEAGUE_NEWS_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=50"
)
REQUEST_TIMEOUT    = 10   # seconds per HTTP call
NEWS_MAX_AGE_HOURS = 48   # discard items older than this

MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 2048

# ── Filter keyword lists ───────────────────────────────────────────────
_NOISE_KEYWORDS = [
    "contract", "fine", "suspension appeal", "trade rumor", "extension",
    "arrested", "charity", "endorsement", "draft", "summer league",
]
_PROP_KEYWORDS = [
    "out", "questionable", "doubtful", "probable", "minutes", "rest",
    "load", "return", "cleared", "scratch", "lineup", "start", "bench",
    "role", "restricted", "limited", "back-to-back", "injury", "ankle",
    "knee", "shoulder", "hamstring", "hip", "illness", "personal",
    "coach", "rotation",
]


# ── Data loaders ──────────────────────────────────────────────────────

def load_todays_teams() -> set[str]:
    """
    Return set of team abbreviations (uppercase) playing today.
    Reads nba_master.csv and filters to TODAY_STR rows.
    """
    if not MASTER_CSV.exists():
        print("[pre_game_reporter] ERROR: nba_master.csv not found.")
        return set()
    try:
        teams: set[str] = set()
        with open(MASTER_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize the date field — stored as YYYY-MM-DD or ISO datetime
                raw_date = (row.get("game_date") or "").strip()[:10]
                if raw_date != TODAY_STR:
                    continue
                for col in ("home_team_abbrev", "away_team_abbrev"):
                    abbr = (row.get(col) or "").strip().upper()
                    if abbr:
                        teams.add(abbr)
        return teams
    except Exception as e:
        print(f"[pre_game_reporter] ERROR loading nba_master.csv: {e}")
        return set()


def load_target_players(teams_today: set[str]) -> list[dict]:
    """
    Load active whitelisted players whose team is playing today.
    Returns list of {"player_name": str (title-case), "team_abbr": str (uppercase)}.
    Only players on teams in teams_today are included — never the full whitelist.
    """
    if not WHITELIST_CSV.exists():
        print("[pre_game_reporter] WARNING: player_whitelist.csv not found.")
        return []
    try:
        players: list[dict] = []
        with open(WHITELIST_CSV, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("active", "0")).strip() != "1":
                    continue
                team = (row.get("team_abbr") or "").strip().upper()
                name = (row.get("player_name") or "").strip()
                if team in teams_today and name:
                    players.append({"player_name": name, "team_abbr": team})
        return players
    except Exception as e:
        print(f"[pre_game_reporter] ERROR loading player_whitelist.csv: {e}")
        return []


def load_athlete_id_map() -> dict[str, str]:
    """
    Load player_dim.csv → {player_name_norm (lowercase): player_id}.
    Uses player_name_norm column if present; falls back to lowercasing player_name.
    Where a player appears multiple times, the most recent row wins (last-write).
    """
    id_map: dict[str, str] = {}
    if not PLAYER_DIM_CSV.exists():
        print("[pre_game_reporter] player_dim.csv not found — ESPN athlete lookups unavailable.")
        return id_map
    try:
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
    except Exception as e:
        print(f"[pre_game_reporter] WARNING: could not load player_dim.csv: {e}")
    return id_map


# ── ESPN news fetch ───────────────────────────────────────────────────

def _parse_item(item: dict, player_name: str) -> dict | None:
    """
    Parse a single ESPN news item dict.
    Returns None if the item is older than NEWS_MAX_AGE_HOURS or has no text content.
    Attaches player_name to the returned dict.
    """
    headline    = (item.get("headline") or "").strip()
    description = (item.get("description") or "").strip()
    published   = (item.get("published") or item.get("lastModified") or "").strip()

    # Discard items older than NEWS_MAX_AGE_HOURS
    if published:
        try:
            pub_dt    = dt.datetime.fromisoformat(published.replace("Z", "+00:00"))
            now_utc   = NOW.astimezone(dt.timezone.utc)
            age_hours = (now_utc - pub_dt.astimezone(dt.timezone.utc)).total_seconds() / 3600
            if age_hours > NEWS_MAX_AGE_HOURS:
                return None
        except Exception:
            pass  # Unparseable timestamp — keep item rather than silently drop

    if not headline and not description:
        return None

    return {
        "player_name": player_name,
        "headline":    headline,
        "description": description,
        "published":   published,
    }


def fetch_player_news(athlete_id: str, player_name_lower: str) -> tuple[list[dict], bool]:
    """
    Fetch athlete-specific news from ESPN.
    Returns (parsed_items, fetch_ok). fetch_ok=False on any HTTP/network error.
    """
    url = ESPN_ATHLETE_NEWS_URL.format(athlete_id=athlete_id)
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        raw_items = data.get("feed", [])
        parsed = [
            r for item in raw_items
            if (r := _parse_item(item, player_name_lower)) is not None
        ]
        return parsed, True
    except Exception:
        return [], False


def fetch_league_news(target_names_lower: set[str]) -> list[dict]:
    """
    Fetch the league-wide NBA news feed once.
    Matches items to whitelisted players by checking if the player's full name
    or last name (len > 3) appears in the headline or description (case-insensitive).
    Unmatched items are tagged player_name="_game" for potential game-level notes.
    Returns parsed items that are within the age window.
    """
    try:
        resp = requests.get(ESPN_LEAGUE_NEWS_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        # ESPN site/v2 news endpoint uses "articles"; athlete endpoint uses "feed"
        raw_items = data.get("articles", data.get("feed", []))
    except Exception as e:
        print(f"[pre_game_reporter] WARNING: league news fetch failed: {e}")
        return []

    results: list[dict] = []
    for item in raw_items:
        headline    = (item.get("headline") or "").strip()
        description = (item.get("description") or "").strip()
        combined    = (headline + " " + description).lower()

        # Try to match a whitelisted player by name
        matched_name = "_game"
        for name_lower in target_names_lower:
            parts = name_lower.split()
            last  = parts[-1] if parts else ""
            if name_lower in combined or (len(last) > 3 and last in combined):
                matched_name = name_lower
                break

        parsed = _parse_item(item, matched_name)
        if parsed:
            results.append(parsed)

    return results


# ── Relevance filtering ───────────────────────────────────────────────

def is_prop_relevant(item: dict) -> bool:
    """
    Keep an item if it contains any prop-relevant keyword, OR if it contains
    no noise keywords at all.
    Drop only when it is "pure noise": has a noise keyword AND lacks any
    prop-relevant keyword.
    """
    text     = (item.get("headline", "") + " " + item.get("description", "")).lower()
    has_noise = any(kw in text for kw in _NOISE_KEYWORDS)
    has_prop  = any(kw in text for kw in _PROP_KEYWORDS)
    return has_prop or not has_noise


# ── Claude summarization ──────────────────────────────────────────────

def call_claude_summarize(
    filtered_items: list[dict],
    target_names_lower: set[str],
) -> tuple[dict, dict]:
    """
    Single Claude API call covering all filtered items.
    Returns (player_notes, game_notes). Both are dicts; returns ({}, {}) on any failure.
    Claude is only called when filtered_items is non-empty — this is enforced in main().
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[pre_game_reporter] WARNING: ANTHROPIC_API_KEY not set — skipping Claude call.")
        return {}, {}

    distinct_players = {
        i["player_name"] for i in filtered_items if i["player_name"] != "_game"
    }
    print(
        f"[pre_game_reporter] Calling Claude to summarize {len(filtered_items)} items "
        f"for {len(distinct_players)} players..."
    )

    system_prompt = (
        "You are summarizing pre-game NBA news for a player props betting system. "
        "Your job: distill raw ESPN news items into short, actionable notes that affect "
        "prop selection confidence for Points, Rebounds, Assists, and 3-pointers made. "
        "Focus only on: availability (in/out/questionable), minutes restrictions, role changes, "
        "lineup changes, matchup-relevant notes. Ignore: contracts, fines, personal news. "
        "Be terse. Each note should be 1-2 sentences max. "
        "Return only JSON — no preamble."
    )

    user_message = (
        f"Here are the filtered ESPN news items for today's NBA slate ({TODAY_STR}):\n\n"
        f"{json.dumps(filtered_items, indent=2)}\n\n"
        "Summarize these into the following JSON format. Only include players where the news "
        "is genuinely material to prop selection. If a player's items contain nothing "
        "prop-relevant after reading them, omit that player from player_notes entirely. "
        "Do not pad with 'no notable news' entries.\n\n"
        "For game_notes, only include a game entry if there is a material note affecting "
        "tracked players (e.g. a non-whitelisted player ruled out causing a rotation shift). "
        "Use 'TEAM1 vs TEAM2' format (uppercase team abbreviations) for game keys. "
        "Omit games with nothing material.\n\n"
        "Return exactly this JSON structure:\n"
        "{\n"
        '  "player_notes": {\n'
        '    "player name lowercase": "1-2 sentence actionable summary",\n'
        "    ...\n"
        "  },\n"
        '  "game_notes": {\n'
        '    "TEAM1 vs TEAM2": "1-2 sentence note if material, else omit this game entirely",\n'
        "    ...\n"
        "  }\n"
        "}"
    )

    try:
        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result       = json.loads(raw)
        player_notes = result.get("player_notes") or {}
        game_notes   = result.get("game_notes")   or {}
        return player_notes, game_notes

    except json.JSONDecodeError as e:
        print(f"[pre_game_reporter] WARNING: Claude response JSON parse failed: {e}")
        return {}, {}
    except Exception as e:
        print(f"[pre_game_reporter] WARNING: Claude call failed: {e}")
        return {}, {}


# ── Context staleness check ───────────────────────────────────────────

def call_claude_staleness_check(
    context_text: str,
    news_items: list[dict],
) -> list[dict]:
    """
    Single Claude call to detect conflicts between the season context doc and today's news.
    Returns list of flag dicts, or [] on any failure. Never crashes.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[pre_game_reporter] WARNING: ANTHROPIC_API_KEY not set — skipping staleness check.")
        return []

    system_prompt = (
        "You are a fact-checker for an NBA player props system. Your job is to identify "
        "conflicts between a season context document and today's breaking news. The season "
        "context contains facts that agents rely on daily — stale facts cause bad picks. "
        "Be conservative: only flag clear, direct conflicts or confirmed new developments. "
        "Do not flag speculative items or rumors. Return only JSON — no preamble."
    )

    user_message = (
        f"Today's date: {TODAY_STR}\n\n"
        f"SEASON CONTEXT DOCUMENT:\n{context_text}\n\n"
        f"TODAY'S NEWS ITEMS:\n{json.dumps(news_items, indent=2)}\n\n"
        "Identify any conflicts between the season context facts and today's news. "
        "Return a JSON object in this exact format:\n"
        "{\n"
        '  "flags": [\n'
        "    {\n"
        '      "player_or_team": "string",\n'
        '      "current_context_fact": "string — quote the relevant fact from the context doc",\n'
        '      "conflict": "string — what today\'s news says that contradicts or updates it",\n'
        '      "urgency": "critical | monitor",\n'
        '      "suggested_action": "string — what to change in the context doc"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "urgency values:\n"
        "  critical — fact is directly wrong today (player returning, trade reversed, role completely changed)\n"
        "  monitor — fact may be becoming stale (player ramping up, role shifting, minutes changing)\n"
        'If no conflicts found, return {"flags": []}.'
    )

    try:
        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()
        result = json.loads(raw)
        return result.get("flags") or []
    except json.JSONDecodeError as e:
        print(f"[pre_game_reporter] WARNING: staleness check JSON parse failed: {e}")
        return []
    except Exception as e:
        print(f"[pre_game_reporter] WARNING: staleness check Claude call failed: {e}")
        return []


def write_context_flags_md(flags: list[dict]) -> None:
    """Write data/context_flags.md. Always writes — even when no flags."""
    now_str = NOW.strftime("%H:%M")
    lines = [
        "# NBAgent — Season Context Flags",
        f"Generated: {TODAY_STR} at {now_str} PT",
        "",
    ]

    if not flags:
        lines.append("✅ No conflicts detected. Season context appears current.")
        CONTEXT_FLAGS_MD.write_text("\n".join(lines))
        return

    lines += [
        "Review each flag below and update `context/nba_season_context.md` before the "
        "next workflow run. Commit the updated file to trigger a clean Analyst run with "
        "correct context.",
        "",
        "---",
        "",
    ]

    critical_flags = [f for f in flags if f.get("urgency") == "critical"]
    monitor_flags  = [f for f in flags if f.get("urgency") == "monitor"]

    if critical_flags:
        lines.append("## ⚠ CRITICAL — Action required before today's picks")
        lines.append("")
        for flag in critical_flags:
            lines.append(f"### {flag.get('player_or_team', 'Unknown')}")
            lines.append(f"**Current context:** {flag.get('current_context_fact', '')}")
            lines.append(f"**Conflict:** {flag.get('conflict', '')}")
            lines.append(f"**Suggested action:** {flag.get('suggested_action', '')}")
            lines.append("")
            lines.append("---")
            lines.append("")

    if monitor_flags:
        lines.append("## 👀 MONITOR — Review when convenient")
        lines.append("")
        for flag in monitor_flags:
            lines.append(f"### {flag.get('player_or_team', 'Unknown')}")
            lines.append(f"**Current context:** {flag.get('current_context_fact', '')}")
            lines.append(f"**Conflict:** {flag.get('conflict', '')}")
            lines.append(f"**Suggested action:** {flag.get('suggested_action', '')}")
            lines.append("")
            lines.append("---")
            lines.append("")

    lines.append("_This file is overwritten daily. If no flags appear tomorrow, context is current._")
    CONTEXT_FLAGS_MD.write_text("\n".join(lines))


def run_context_staleness_check(
    filtered_items: list[dict],
    all_raw_items: list[dict],
) -> list[dict]:
    """
    Orchestrates the context staleness check after the summarization step.
    Runs if filtered_item_count > 0 OR the context file's Last updated date != TODAY.
    Always writes context_flags.md. Returns list of flag dicts (may be []).
    Never crashes — gracefully skips on any file/API error.
    """
    # Load context file
    if not CONTEXT_MD.exists():
        print("[pre_game_reporter] Context staleness check skipped — context file not found.")
        write_context_flags_md([])
        return []
    try:
        context_text_raw = CONTEXT_MD.read_text(encoding="utf-8").strip()
    except Exception as e:
        print(f"[pre_game_reporter] Context staleness check skipped — unreadable: {e}")
        write_context_flags_md([])
        return []

    # Parse Last updated: date from HTML comment header
    last_updated: dt.date | None = None
    for line in context_text_raw.splitlines():
        if "Last updated:" in line:
            try:
                date_str = line.split("Last updated:")[-1].strip()
                last_updated = dt.date.fromisoformat(date_str)
            except Exception:
                pass
            break

    context_is_stale = (last_updated is not None and last_updated != TODAY)
    has_news         = len(filtered_items) > 0

    if not has_news and not context_is_stale:
        print("[pre_game_reporter] Context staleness check skipped — no news items and context is current")
        write_context_flags_md([])
        return []

    # Strip HTML comment header before sending to Claude
    context_text = context_text_raw
    if context_text.startswith("<!--"):
        end = context_text.find("-->")
        if end != -1:
            context_text = context_text[end + 3:].strip()

    # Use filtered items if available; fall back to all raw items
    items_for_check = filtered_items if filtered_items else all_raw_items

    print("[pre_game_reporter] Running context staleness check...")
    flags = call_claude_staleness_check(context_text, items_for_check)
    write_context_flags_md(flags)

    n_critical = sum(1 for f in flags if f.get("urgency") == "critical")
    n_monitor  = sum(1 for f in flags if f.get("urgency") == "monitor")
    if flags:
        print(
            f"[pre_game_reporter] Context flags: {n_critical} critical, "
            f"{n_monitor} monitor → data/context_flags.md"
        )
    else:
        print("[pre_game_reporter] Context staleness check: no conflicts found")

    return flags


# ── Output writers ────────────────────────────────────────────────────

def write_output(
    player_notes:   dict,
    game_notes:     dict,
    raw_count:      int,
    filtered_count: int,
    fetch_errors:   list[str],
    context_flags:  list | None = None,
) -> None:
    output = {
        "date":                      TODAY_STR,
        "generated_at":              NOW.isoformat(),
        "player_notes":              player_notes,
        "game_notes":                game_notes,
        "raw_item_count":            raw_count,
        "filtered_item_count":       filtered_count,
        "fetch_errors":              fetch_errors,
        "suggested_context_updates": context_flags if context_flags is not None else [],
    }
    with open(PRE_GAME_JSON, "w") as f:
        json.dump(output, f, indent=2)
    print(
        f"[pre_game_reporter] Saved pre_game_news.json "
        f"({len(player_notes)} player notes, {len(game_notes)} game notes)"
    )


def write_empty(fetch_errors: list[str] | None = None) -> None:
    """Write an empty pre_game_news.json so analyst.py never sees a missing file."""
    write_output({}, {}, 0, 0, fetch_errors or [])


# ── Main ──────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[pre_game_reporter] Running for {TODAY_STR}")

    # Step 1 — determine today's players to track
    teams_today = load_todays_teams()
    if not teams_today:
        print("[pre_game_reporter] No teams found for today — writing empty output.")
        write_empty()
        return

    target_players = load_target_players(teams_today)
    if not target_players:
        print("[pre_game_reporter] No whitelisted players on today's slate — writing empty output.")
        write_empty()
        return

    n_games = len(teams_today) // 2
    print(
        f"[pre_game_reporter] Today's slate: ~{n_games} games, "
        f"{len(target_players)} tracked players"
    )

    # Build athlete_id lookup and name set for league news matching
    athlete_id_map     = load_athlete_id_map()
    target_names_lower = {p["player_name"].lower() for p in target_players}

    # Step 2 — fetch ESPN news per player (only today's tracked players)
    all_raw_items: list[dict] = []
    fetch_errors:  list[str]  = []

    for player in target_players:
        name = player["player_name"]
        aid  = athlete_id_map.get(name.lower())
        if not aid:
            fetch_errors.append(name)
            continue
        items, ok = fetch_player_news(aid, name.lower())
        if not ok:
            fetch_errors.append(name)
        all_raw_items.extend(items)

    print(
        f"[pre_game_reporter] ESPN news fetched: {len(target_players)} players, "
        f"{len(fetch_errors)} fetch errors"
    )

    # Fetch league-wide news once — matched to tracked players or tagged "_game"
    league_items = fetch_league_news(target_names_lower)
    all_raw_items.extend(league_items)

    raw_count = len(all_raw_items)

    # Step 3 — filter to prop-relevant items only
    filtered_items = [item for item in all_raw_items if is_prop_relevant(item)]
    filtered_count = len(filtered_items)

    print(f"[pre_game_reporter] Raw news items: {raw_count} | After filter: {filtered_count}")

    # Step 4 — single Claude batch summarization call (only when filtered items exist)
    player_notes: dict = {}
    game_notes:   dict = {}
    if filtered_items:
        player_notes, game_notes = call_claude_summarize(filtered_items, target_names_lower)
    else:
        print("[pre_game_reporter] No prop-relevant items after filtering — skipping summarization.")

    # Step 5 — context staleness check (runs after summarization; always writes context_flags.md)
    context_flags = run_context_staleness_check(filtered_items, all_raw_items)

    # Step 6 — write output
    write_output(player_notes, game_notes, raw_count, filtered_count, fetch_errors, context_flags)


if __name__ == "__main__":
    main()
