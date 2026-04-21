#!/usr/bin/env python3
"""
NBAgent — Season Context Updater

Automatically updates context/nba_season_context.md with playoff game results.
Runs in auditor.yml after auditor.py. Inserts series diary entries, updates
injury statuses, and bumps the timestamp.

Date-gated: no-op before PLAYOFFS_R1_DATE.

Data sources (all populated upstream in auditor.yml by the time this runs):
  - data/nba_master.csv           scores + spreads + season_type
  - data/player_game_log.csv      per-player box scores
  - data/post_game_news.json      post_game_reporter narratives
  - data/injuries_today.json      current injury list (per-team)
  - context/nba_season_context.md the file being patched in place
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

try:
    from json_repair import repair_json
except ImportError:
    repair_json = None


# ── Paths ─────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parent.parent
DATA        = ROOT / "data"
CONTEXT_MD  = ROOT / "context" / "nba_season_context.md"
MASTER_CSV  = DATA / "nba_master.csv"
GAME_LOG    = DATA / "player_game_log.csv"
POST_NEWS   = DATA / "post_game_news.json"
INJURIES    = DATA / "injuries_today.json"
BRACKET     = DATA / "playoff_bracket.json"
WHITELIST   = ROOT / "playerprops" / "player_whitelist.csv"


# ── Config ────────────────────────────────────────────────────────────
PT               = ZoneInfo("America/Los_Angeles")
TODAY            = dt.datetime.now(PT).date()
YESTERDAY        = TODAY - dt.timedelta(days=1)
YESTERDAY_STR    = YESTERDAY.strftime("%Y-%m-%d")
TODAY_STR        = TODAY.strftime("%Y-%m-%d")

PLAYOFFS_R1_DATE = "2026-04-18"
MODEL            = "claude-sonnet-4-6"
MAX_TOKENS       = 4096

# ESPN → standard abbreviations. nba_master.csv is already normalized by
# ingest, but some legacy rows may still carry ESPN codes. Defensive map.
ESPN_TO_STD = {
    "NY":   "NYK",
    "GS":   "GSW",
    "SA":   "SAS",
    "UTAH": "UTA",
    "WSH":  "WAS",
    "NO":   "NOP",
    "PHO":  "PHX",
}


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _norm_team(abbr: str) -> str:
    """Normalize a team abbreviation to the standard form used in the
    season context document (NYK, GSW, SAS, etc.)."""
    a = (abbr or "").strip().upper()
    return ESPN_TO_STD.get(a, a)


def _to_float(val) -> float | None:
    try:
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _to_int(val) -> int | None:
    f = _to_float(val)
    return int(f) if f is not None else None


def load_json_safe(path: Path):
    """Load a JSON file. Return {} (or [] if the file is a list) on missing or
    parse error. Never raises."""
    if not path.exists():
        return {}
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception as exc:
        print(f"  WARNING: failed to load {path.name}: {exc}")
        return {}


# ─────────────────────────────────────────────────────────────────────
# Data loaders
# ─────────────────────────────────────────────────────────────────────

def load_yesterday_playoff_games() -> list[dict]:
    """Read nba_master.csv, filter to completed games on YESTERDAY_STR.

    Returns a list of dicts with keys:
      home_team, away_team, home_score, away_score, home_spread

    Filters to postseason (season_type == 3) when that column is non-null.
    We're past the regular-season end date, so rows with null season_type
    are still included (defensive — older rows may lack the column).
    """
    if not MASTER_CSV.exists():
        print(f"  nba_master.csv not found at {MASTER_CSV}")
        return []

    games: list[dict] = []
    try:
        with open(MASTER_CSV, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if (row.get("game_date") or "").strip() != YESTERDAY_STR:
                    continue

                home_score = _to_int(row.get("home_score"))
                away_score = _to_int(row.get("away_score"))
                if home_score is None or away_score is None:
                    continue  # not yet completed

                # Season type filter: include postseason (3) or missing.
                stype = _to_float(row.get("season_type"))
                if stype is not None and stype != 3.0:
                    continue

                games.append({
                    "home_team":   _norm_team(row.get("home_team_abbrev")),
                    "away_team":   _norm_team(row.get("away_team_abbrev")),
                    "home_score":  home_score,
                    "away_score":  away_score,
                    "home_spread": _to_float(row.get("home_spread")),
                })
    except Exception as exc:
        print(f"  ERROR reading nba_master.csv: {exc}")
        return []

    return games


def load_whitelisted_players() -> set[str]:
    """Return the set of active whitelisted player names (lowercased)."""
    names: set[str] = set()
    if not WHITELIST.exists():
        return names
    try:
        with open(WHITELIST, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if str(row.get("active", "0")).strip() != "1":
                    continue
                name = (row.get("player_name") or "").strip().lower()
                if name:
                    names.add(name)
    except Exception as exc:
        print(f"  WARNING: failed to read whitelist: {exc}")
    return names


def load_player_stat_lines(games: list[dict]) -> dict[str, list[dict]]:
    """Read player_game_log.csv for YESTERDAY_STR and build a per-game list
    of stat dicts for whitelisted players + any non-whitelisted player with
    25+ points.

    Returns dict keyed by "{away_team}_{home_team}" with values being lists
    of stat dicts sorted by pts desc. Each stat dict carries:
      name, team, pts, reb, ast, fg3m, fgm, fga, minutes
    """
    if not GAME_LOG.exists():
        print(f"  player_game_log.csv not found at {GAME_LOG}")
        return {}

    whitelist = load_whitelisted_players()

    # Build a team → game-key lookup so each row can be routed to its game.
    # A player's team abbrev should match one of the two teams in exactly
    # one yesterday game (playoff slate is small, no team plays twice).
    team_to_key: dict[str, str] = {}
    for g in games:
        home, away = g["home_team"], g["away_team"]
        key = f"{away}_{home}"
        team_to_key[home] = key
        team_to_key[away] = key

    stat_lines: dict[str, list[dict]] = {g: [] for g in team_to_key.values()}

    try:
        with open(GAME_LOG, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if (row.get("game_date") or "").strip() != YESTERDAY_STR:
                    continue
                if str(row.get("dnp", "")).strip() == "1":
                    continue

                team = _norm_team(row.get("team_abbrev"))
                key  = team_to_key.get(team)
                if not key:
                    continue  # not in a game we care about

                name = (row.get("player_name") or "").strip()
                name_lower = name.lower()
                pts  = _to_int(row.get("pts")) or 0

                # Include whitelisted players OR notable non-whitelisted performers
                if name_lower not in whitelist and pts < 25:
                    continue

                stat_lines[key].append({
                    "name":    name,
                    "team":    team,
                    "pts":     pts,
                    "reb":     _to_int(row.get("reb")) or 0,
                    "ast":     _to_int(row.get("ast")) or 0,
                    "fg3m":    _to_int(row.get("fg3m")) or 0,
                    "fgm":     _to_int(row.get("fgm")) or 0,
                    "fga":     _to_int(row.get("fga")) or 0,
                    "minutes": _to_float(row.get("minutes")),
                })
    except Exception as exc:
        print(f"  ERROR reading player_game_log.csv: {exc}")
        return {}

    # Sort each game's players by points descending
    for key in stat_lines:
        stat_lines[key].sort(key=lambda p: p["pts"], reverse=True)

    return stat_lines


def load_post_game_news() -> dict:
    """Load the `players` dict from post_game_news.json. Empty dict on missing."""
    data = load_json_safe(POST_NEWS)
    if isinstance(data, dict):
        players = data.get("players")
        if isinstance(players, dict):
            return players
    return {}


def load_injuries() -> dict:
    """Load injuries_today.json. Returns the raw dict (keyed by team abbrev
    plus metadata keys like `asof_date`, `built_at_utc`, `source`)."""
    data = load_json_safe(INJURIES)
    return data if isinstance(data, dict) else {}


# ─────────────────────────────────────────────────────────────────────
# Series section identification
# ─────────────────────────────────────────────────────────────────────

_SERIES_HEADER_RE = re.compile(
    r"^##### +\((\d+)\) +([A-Z]{2,4}) +vs +\((\d+)\) +([A-Z]{2,4})",
    re.MULTILINE,
)
_GAME_ENTRY_RE = re.compile(r"\*\*Game \d+\b")


def find_series_sections(context_text: str) -> list[dict]:
    """Scan the season context for series diary headers.

    Returns a list of dicts:
      {
        header, team1, team2,
        header_start, section_end,
        last_game_entry_end,   # insertion point for the next **Game N** paragraph
        game_count,            # number of existing **Game N** paragraphs
      }
    """
    sections: list[dict] = []
    matches = list(_SERIES_HEADER_RE.finditer(context_text))
    if not matches:
        return sections

    # Compute the upstream boundary set once — any of these ends a section.
    # We look for the NEXT occurrence of ## header (5 hashes), ### header
    # (3 hashes), or horizontal rule after this header.
    boundary_re = re.compile(r"^(?:##### |### |---)", re.MULTILINE)

    n = len(context_text)
    for i, m in enumerate(matches):
        header_line_start = context_text.rfind("\n", 0, m.start()) + 1
        header_text_end = context_text.find("\n", m.end())
        header_line = context_text[header_line_start: header_text_end if header_text_end != -1 else n]

        # Section end: next boundary after this header.
        search_from = m.end()
        next_boundary = boundary_re.search(context_text, search_from)
        section_end = next_boundary.start() if next_boundary else n
        section_body = context_text[search_from:section_end]

        # Find all **Game N** paragraph ends within the section body.
        game_matches = list(_GAME_ENTRY_RE.finditer(section_body))
        game_count = len(game_matches)

        last_game_end_abs: int | None = None
        if game_matches:
            last_game = game_matches[-1]
            # Paragraph ends at the next blank line after the match, or the
            # section boundary.
            para_rel = last_game.end()
            blank = section_body.find("\n\n", para_rel)
            if blank == -1 or blank >= (section_end - search_from):
                # No blank line found inside this section — use section end,
                # trimming trailing whitespace so we insert before blank padding.
                last_game_end_abs = section_end
                # Walk back past whitespace-only chars so we insert before padding.
                while last_game_end_abs > 0 and context_text[last_game_end_abs - 1] in " \t\n":
                    last_game_end_abs -= 1
            else:
                last_game_end_abs = search_from + blank

        sections.append({
            "header":             header_line.strip(),
            "team1":              m.group(2),
            "team2":              m.group(4),
            "header_start":       header_line_start,
            "section_end":        section_end,
            "last_game_entry_end": last_game_end_abs,
            "game_count":         game_count,
        })

    return sections


def match_game_to_series(game: dict, series_sections: list[dict]) -> dict | None:
    """Return the series section whose team pair matches this game, or None.

    Matching is symmetric: game (home=ATL, away=NYK) matches a section with
    team1=NYK, team2=ATL just as well as team1=ATL, team2=NYK.
    """
    home = _norm_team(game.get("home_team"))
    away = _norm_team(game.get("away_team"))
    for section in series_sections:
        s_pair = {section["team1"], section["team2"]}
        if {home, away} == s_pair:
            return section
    return None


# ─────────────────────────────────────────────────────────────────────
# LLM prompt construction + response parsing
# ─────────────────────────────────────────────────────────────────────

def _format_game_block(game: dict, stat_lines: dict) -> str:
    """Format a single game's data into a text block for the LLM."""
    home = game["home_team"]
    away = game["away_team"]
    hs, as_ = game["home_score"], game["away_score"]
    margin = abs(hs - as_)
    winner = home if hs > as_ else away
    loser  = away if winner == home else home
    w_score = max(hs, as_)
    l_score = min(hs, as_)
    spread_str = f"home_spread={game['home_spread']:+.1f}" if game.get("home_spread") is not None else "home_spread=n/a"

    lines = [
        f"### {away} @ {home}  (Game {game['game_number']} of the series)",
        f"Final: {winner} {w_score}, {loser} {l_score}  (margin={margin}, {spread_str})",
    ]

    key = f"{away}_{home}"
    players = stat_lines.get(key, [])
    if players:
        lines.append("Top stat lines (pts / reb / ast):")
        for p in players[:14]:
            mins_str = f"{p['minutes']:.1f}" if p.get("minutes") is not None else "?"
            stat = (f"  {p['name']} ({p['team']}): "
                    f"{p['pts']}/{p['reb']}/{p['ast']}  "
                    f"FG {p['fgm']}-{p['fga']}, 3PM {p['fg3m']}  "
                    f"min={mins_str}")
            lines.append(stat)
    else:
        lines.append("(no stat lines available)")

    return "\n".join(lines)


def _format_post_game_news(games: list[dict], stat_lines: dict, post_news: dict) -> str:
    """Return a block of post-game narrative notes for players who appear in
    yesterday's games. Empty string if no relevant notes."""
    if not post_news:
        return ""

    # Names visible in yesterday's stat lines — these are the players the LLM
    # should see narratives for.
    relevant_names: set[str] = set()
    for g in games:
        key = f"{g['away_team']}_{g['home_team']}"
        for p in stat_lines.get(key, []):
            relevant_names.add(p["name"].lower())

    blocks = []
    for name_lower, info in post_news.items():
        if name_lower not in relevant_names:
            continue
        detail    = (info.get("detail") or "").strip()
        narrative = (info.get("web_narrative") or "").strip()
        event     = (info.get("event_type") or "").strip()
        if not (detail or narrative):
            continue
        chunk = f"- {name_lower} [event={event}]: {detail}"
        if narrative and narrative != detail:
            chunk += f"\n  narrative: {narrative}"
        blocks.append(chunk)

    if not blocks:
        return ""
    return "## POST-GAME NEWS (from post_game_reporter.py)\n" + "\n".join(blocks)


def _format_injuries(games: list[dict], injuries_data: dict) -> str:
    """Return a block of injury bullets for teams that played yesterday."""
    if not isinstance(injuries_data, dict) or not injuries_data:
        return ""
    teams_played = set()
    for g in games:
        teams_played.add(g["home_team"])
        teams_played.add(g["away_team"])

    lines = []
    for team_key, roster in injuries_data.items():
        team_norm = _norm_team(team_key)
        if team_norm not in teams_played:
            continue
        if not isinstance(roster, list):
            continue
        for entry in roster:
            if not isinstance(entry, dict):
                continue
            name    = entry.get("name") or entry.get("player_name") or "?"
            status  = entry.get("status") or "?"
            details = entry.get("details") or ""
            lines.append(f"- {team_norm}  {name}  status={status}  {details}".rstrip())

    if not lines:
        return ""
    return "## CURRENT INJURIES (teams that played yesterday)\n" + "\n".join(lines)


def build_llm_prompt(
    context_text: str,
    games_with_series: list[dict],
    stat_lines: dict,
    post_news: dict,
    injuries_data: dict,
) -> str:
    """Assemble the user prompt for the LLM."""
    game_blocks = "\n\n".join(
        _format_game_block(g, stat_lines) for g in games_with_series
    )

    post_news_block = _format_post_game_news(games_with_series, stat_lines, post_news)
    injuries_block  = _format_injuries(games_with_series, injuries_data)

    series_summary = []
    for g in games_with_series:
        sec = g.get("series_section", {})
        series_summary.append(
            f"- {g['away_team']} @ {g['home_team']}: "
            f"mapped to section '{sec.get('header', '?')}', "
            f"this is Game {g['game_number']} "
            f"({sec.get('game_count', 0)} existing entries in section)"
        )
    series_summary_text = "\n".join(series_summary)

    # Yesterday label (e.g. "Apr 20") for the diary entry headers.
    ylabel = YESTERDAY.strftime("%b %d").replace(" 0", " ")

    return f"""You are updating the NBAgent season context document for yesterday's playoff results.

The document in <season_context> tags is GROUND TRUTH — it is current as of today
and supersedes any stale training-data priors about NBA rosters, coaching, or team
identities. Use its existing series diary entries as format templates; match their
tone, depth, and structure.

Your task: produce JSON with (a) new diary entries to append to the appropriate
series sections, and (b) optional injury bullet updates where yesterday's game
performance meaningfully changes a player's injury status.

═══════════════════════════════════════════════════════════════════════
## SEASON CONTEXT — FULL DOCUMENT
═══════════════════════════════════════════════════════════════════════

<season_context>
{context_text}
</season_context>

═══════════════════════════════════════════════════════════════════════
## YESTERDAY'S GAMES ({YESTERDAY_STR})
═══════════════════════════════════════════════════════════════════════

Diary entries must use the date label "{ylabel}" in the bold result line.

Series mapping (use these exact team1/team2 identifiers in your JSON response):
{series_summary_text}

Game data:

{game_blocks}

{post_news_block}

{injuries_block}

═══════════════════════════════════════════════════════════════════════
## OUTPUT FORMAT (STRICT JSON)
═══════════════════════════════════════════════════════════════════════

Return ONLY valid JSON with this exact shape. No markdown fencing, no preamble.

{{
  "diary_entries": [
    {{
      "team1": "ATL",
      "team2": "NYK",
      "game_number": 2,
      "entry_text": "**Game 2 ({ylabel}) — ATL 107, NYK 106 | Series tied 1-1 — ATL STEALS ONE AT MSG**\\nDiary body text..."
    }}
  ],
  "injury_updates": [
    {{
      "search_line": "**Anthony Edwards (MIN)** — Right knee",
      "full_replacement": "- **Anthony Edwards (MIN)** — Right knee patellofemoral pain. G1: 22 pts, G2: 30/10/2 in 40 min — knee not limiting production."
    }}
  ]
}}

═══════════════════════════════════════════════════════════════════════
## DIARY ENTRY GUIDELINES
═══════════════════════════════════════════════════════════════════════

- Start with a bold result line:
  **Game N ({ylabel}) — WINNER SCORE, LOSER SCORE | Series status**
  - Series status examples: "CLE leads 2-0", "Series tied 1-1", "NYK leads 2-1"
  - Add context tag when notable: "— UPSET", "— BLOWOUT (margin NN)", "— OT"
- Include top stat lines for key players (pts/reb/ast format, add FG splits when notable)
- Reference prior game entries in the same series for pattern observations
  (e.g., "Johnson AST suppressed for second straight game — 3 AST in both G1 and G2")
- Note tactical / scheme observations relevant to future prop picks
- End with "GN key:" observation for the next game
- Keep entries to 3-5 substantial lines
- Match the tone and depth of existing diary entries

## INJURY UPDATE GUIDELINES

- Only update bullets where yesterday's game performance meaningfully changes the
  status (confirmed healthy, new limitation, confirmed still OUT, etc.)
- `search_line` should contain enough of the existing bullet's opening text to
  uniquely identify it (bold player name + first few words are ideal).
- Preserve the "- **Player Name (TEAM)** — ..." format.
- Include game performance data that confirms or contradicts the concern.
- If no injury updates are warranted, return `"injury_updates": []`.

## IMPORTANT

- The document inside <season_context> is AUTHORITATIVE. Your training data may
  be stale — do NOT correct rosters, coaches, or team facts against your priors.
- Do not invent stats. Only use stat lines provided in the game data above.
- Return ONLY valid JSON. No markdown fencing, no explanation, no preamble.
"""


def parse_llm_response(response_text: str) -> dict | None:
    """Parse the LLM response into a dict. Returns None on failure."""
    raw = (response_text or "").strip()
    if not raw:
        return None

    # Strategy 1: direct JSON parse
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Strategy 2: strip common markdown fences
    stripped = raw
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)
    try:
        return json.loads(stripped)
    except Exception:
        pass

    # Strategy 3: json_repair fallback
    if repair_json is not None:
        try:
            repaired = repair_json(stripped)
            if isinstance(repaired, (dict, list)):
                return repaired
            return json.loads(repaired)
        except Exception as exc:
            print(f"  json_repair also failed: {exc}")

    # Strategy 4: extract the outermost { ... }
    first = stripped.find("{")
    last  = stripped.rfind("}")
    if first != -1 and last > first:
        candidate = stripped[first: last + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


# ─────────────────────────────────────────────────────────────────────
# File patching
# ─────────────────────────────────────────────────────────────────────

def apply_diary_entries(
    context_text: str,
    diary_entries: list[dict],
    series_sections: list[dict],
) -> str:
    """Insert each diary entry after the last existing **Game N** paragraph
    in its series section. Applies bottom-up to preserve offsets.
    """
    # Build (insertion_offset, entry_text) for each diary entry
    planned: list[tuple[int, str]] = []
    for entry in diary_entries:
        t1 = (entry.get("team1") or "").strip().upper()
        t2 = (entry.get("team2") or "").strip().upper()
        text = (entry.get("entry_text") or "").strip()
        if not text or not t1 or not t2:
            print(f"  WARNING: skipping malformed diary entry: {entry}")
            continue

        # Find matching section (order-agnostic)
        matched = None
        for sec in series_sections:
            if {sec["team1"], sec["team2"]} == {t1, t2}:
                matched = sec
                break
        if not matched:
            print(f"  WARNING: no matching series section for {t1} vs {t2}")
            continue

        insert_at = matched["last_game_entry_end"]
        if insert_at is None:
            # No existing **Game N** — insert at the section end (trimmed).
            insert_at = matched["section_end"]
            while insert_at > 0 and context_text[insert_at - 1] in " \t\n":
                insert_at -= 1
        planned.append((insert_at, text))

    # Apply bottom-up so offsets don't drift
    planned.sort(key=lambda x: x[0], reverse=True)

    updated = context_text
    for insert_at, text in planned:
        prefix = updated[:insert_at]
        suffix = updated[insert_at:]
        # Ensure exactly one blank line between previous content and new entry.
        updated = prefix.rstrip() + "\n\n" + text.rstrip() + "\n" + suffix.lstrip("\n")

    return updated


def apply_injury_updates(
    context_text: str,
    injury_updates: list[dict],
) -> str:
    """For each update, find the bullet containing `search_line` and replace
    the entire bullet with `full_replacement`. Skip (with warning) if not found.
    Applies bottom-up on the final text to avoid offset drift.
    """
    if not injury_updates:
        return context_text

    # Precompute (offset, line_start, line_end, full_bullet_end, replacement)
    # then apply bottom-up.
    operations: list[tuple[int, int, str]] = []

    for upd in injury_updates:
        search = (upd.get("search_line") or "").strip()
        replacement = (upd.get("full_replacement") or "").rstrip()
        if not search or not replacement:
            print(f"  WARNING: skipping malformed injury update: {upd}")
            continue

        idx = context_text.find(search)
        if idx == -1:
            print(f"  WARNING: injury search_line not found: {search[:60]!r}")
            continue

        # Find the start of the bullet line (the "- **" at or before idx).
        line_start = context_text.rfind("\n", 0, idx) + 1
        # The bullet must actually start with "- " at line_start.
        if not context_text[line_start:].startswith("- "):
            # Search backwards until we hit a line starting with "- "
            search_pos = line_start
            while search_pos > 0:
                prev_newline = context_text.rfind("\n", 0, search_pos - 1) + 1
                if context_text[prev_newline:].startswith("- "):
                    line_start = prev_newline
                    break
                search_pos = prev_newline
                if prev_newline == 0:
                    break

        # Find the end of this bullet: next line that starts with "- ", or a
        # blank line, or a heading. The bullet may span multiple physical lines
        # of prose.
        scan = line_start
        bullet_end = len(context_text)
        while True:
            nl = context_text.find("\n", scan)
            if nl == -1:
                bullet_end = len(context_text)
                break
            next_line_start = nl + 1
            if next_line_start >= len(context_text):
                bullet_end = len(context_text)
                break
            next_line = context_text[next_line_start: context_text.find("\n", next_line_start) if context_text.find("\n", next_line_start) != -1 else len(context_text)]
            # Stop on another bullet, blank line, or heading
            if (next_line.startswith("- ")
                    or next_line.strip() == ""
                    or next_line.startswith("#")):
                bullet_end = nl
                break
            scan = next_line_start

        operations.append((line_start, bullet_end, replacement))

    if not operations:
        return context_text

    # Apply bottom-up
    operations.sort(key=lambda o: o[0], reverse=True)
    updated = context_text
    for line_start, bullet_end, replacement in operations:
        updated = updated[:line_start] + replacement + updated[bullet_end:]

    return updated


def update_timestamp(context_text: str) -> str:
    """Update the `Last updated: YYYY-MM-DD` line to TODAY_STR."""
    return re.sub(
        r"(\*Last updated: )\d{4}-\d{2}-\d{2}(\.)",
        rf"\g<1>{TODAY_STR}\g<2>",
        context_text,
        count=1,
    )


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # Date gate — no-op before playoffs
    if YESTERDAY_STR < PLAYOFFS_R1_DATE:
        print(f"Pre-playoffs ({YESTERDAY_STR} < {PLAYOFFS_R1_DATE}) "
              "— skipping season context update")
        return 0

    # Load season context
    if not CONTEXT_MD.exists():
        print(f"Season context file not found: {CONTEXT_MD}")
        return 0
    context_text = CONTEXT_MD.read_text(encoding="utf-8")
    if not context_text.strip():
        print("Season context file is empty — skipping")
        return 0

    # Load yesterday's games
    games = load_yesterday_playoff_games()
    if not games:
        print(f"No playoff games found for {YESTERDAY_STR} — skipping")
        return 0
    print(f"Found {len(games)} playoff game(s) on {YESTERDAY_STR}")

    # Find series sections
    series_sections = find_series_sections(context_text)
    if not series_sections:
        print("No series sections found in season context — skipping")
        return 0
    print(f"Found {len(series_sections)} series section(s) in document")

    # Match each game to a series + compute its game number
    matched: list[dict] = []
    for g in games:
        section = match_game_to_series(g, series_sections)
        if section:
            g["game_number"]    = section["game_count"] + 1
            g["series_section"] = section
            matched.append(g)
            print(f"  {g['away_team']} @ {g['home_team']} "
                  f"→ {section['header']}  (Game {g['game_number']})")
        else:
            print(f"  WARNING: could not match {g.get('away_team')} @ "
                  f"{g.get('home_team')} to any series section")

    if not matched:
        print("No games matched to series sections — skipping")
        return 0

    # Load supporting data
    stat_lines    = load_player_stat_lines(matched)
    post_news     = load_post_game_news()
    injuries_data = load_injuries()

    # Build LLM prompt
    prompt = build_llm_prompt(
        context_text, matched, stat_lines, post_news, injuries_data,
    )
    print(f"Prompt size: {len(prompt):,} chars")

    # Call Claude
    print(f"Calling {MODEL} for diary entries...")
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = resp.content[0].text
    except Exception as exc:
        print(f"ERROR: Claude call failed: {exc}")
        return 1
    print(f"  Response: {len(raw_text)} chars")

    # Parse
    parsed = parse_llm_response(raw_text)
    if parsed is None:
        print("ERROR: Failed to parse LLM response — season context NOT updated")
        print(f"Raw response preview: {raw_text[:400]!r}")
        return 1

    diary_entries  = parsed.get("diary_entries", []) or []
    injury_updates = parsed.get("injury_updates", []) or []
    if not isinstance(diary_entries, list) or not isinstance(injury_updates, list):
        print("ERROR: LLM response shape invalid (arrays expected)")
        return 1

    if not diary_entries:
        print("WARNING: LLM returned no diary entries — season context NOT updated")
        return 0
    print(f"  Diary entries: {len(diary_entries)}, Injury updates: {len(injury_updates)}")

    # Apply updates
    updated = context_text
    updated = update_timestamp(updated)

    # Re-find sections after timestamp update (offsets may shift a few chars)
    fresh_sections = find_series_sections(updated)
    updated = apply_diary_entries(updated, diary_entries, fresh_sections)
    updated = apply_injury_updates(updated, injury_updates)

    # Safety net — never shrink the document
    if len(updated) < len(context_text):
        print(f"ERROR: updated content is shorter "
              f"({len(updated)} < {len(context_text)}) — aborting write")
        return 1

    # Write back
    CONTEXT_MD.write_text(updated, encoding="utf-8")
    delta = len(updated) - len(context_text)
    print(f"Season context updated successfully "
          f"({len(diary_entries)} diary entries, "
          f"{len(injury_updates)} injury updates, +{delta} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
