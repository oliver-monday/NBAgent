#!/usr/bin/env python3
"""
odds_today.py — OddsAPI Phase 1: Daily Player Prop Odds Collection

Fetches FanDuel NBA player prop lines from The Odds API for today's picks.
Annotates picks.json with market_line, market_implied_prob, market_book, edge_pct.
Writes a raw odds cache to data/odds_today.json (overwritten each run).

The persistent analytical record is picks.json — each matched pick carries
its odds fields permanently. odds_today.json is diagnostic/debug only.

If this workflow runs multiple times in a day (morning + afternoon refresh),
each run overwrites the odds fields with the latest data — correct behavior.

Failure behaviour: any error (missing key, API failure, parse error) prints a
warning and exits 0. picks.json is never touched on failure. The workflow
can re-run safely at any time.

Credit cost: 4 credits per NBA game with picks today (4 alternate markets × 1
bookmaker group). Free tier: 500 credits/month. Typical cost: 12–28 credits/day.

API endpoint used for player props:
  GET /v4/sports/basketball_nba/events/{eventId}/odds
  ?markets=player_points_alternate,player_rebounds_alternate,player_assists_alternate,player_threes_alternate
  &bookmakers=fanduel&regions=us&oddsFormat=american

Line matching convention: T20 → 19.5 OVER (pick_value − 0.5).
This is consistent across all prop types and tiers.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
DATA       = ROOT / "data"
PICKS_JSON = DATA / "picks.json"
ODDS_JSON  = DATA / "odds_today.json"

# ── Config ─────────────────────────────────────────────────────────────────────
ET       = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(ET).strftime("%Y-%m-%d")
API_BASE  = "https://api.the-odds-api.com/v4"
SPORT     = "basketball_nba"
BOOKMAKER = "fanduel"
REGIONS   = "us"

# OddsAPI alternate market keys → our prop types.
# Alternate markets contain the full X+ line menu at multiple thresholds,
# matching the conservative floor targets used by NBAgent's tier system.
# Main markets post only the consensus/natural line (too high for our picks).
PROP_MARKET_MAP: dict[str, str] = {
    "player_points_alternate":   "PTS",
    "player_rebounds_alternate": "REB",
    "player_assists_alternate":  "AST",
    "player_threes_alternate":   "3PM",
}

# Set of our prop type codes — used for pick filtering
VALID_PROP_TYPES: set[str] = set(PROP_MARKET_MAP.values())

# OddsAPI full team names → our abbreviations (for game matching)
TEAM_NAME_MAP = {
    "Atlanta Hawks":          "ATL",
    "Boston Celtics":         "BOS",
    "Brooklyn Nets":          "BKN",
    "Charlotte Hornets":      "CHA",
    "Chicago Bulls":          "CHI",
    "Cleveland Cavaliers":    "CLE",
    "Dallas Mavericks":       "DAL",
    "Denver Nuggets":         "DEN",
    "Detroit Pistons":        "DET",
    "Golden State Warriors":  "GSW",
    "Houston Rockets":        "HOU",
    "Indiana Pacers":         "IND",
    "Los Angeles Clippers":   "LAC",
    "Los Angeles Lakers":     "LAL",
    "Memphis Grizzlies":      "MEM",
    "Miami Heat":             "MIA",
    "Milwaukee Bucks":        "MIL",
    "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans":   "NOP",
    "New York Knicks":        "NYK",
    "Oklahoma City Thunder":  "OKC",
    "Orlando Magic":          "ORL",
    "Philadelphia 76ers":     "PHI",
    "Phoenix Suns":           "PHX",
    "Portland Trail Blazers": "POR",
    "Sacramento Kings":       "SAC",
    "San Antonio Spurs":      "SAS",
    "Toronto Raptors":        "TOR",
    "Utah Jazz":              "UTA",
    "Washington Wizards":     "WAS",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _norm_name(name: str) -> str:
    """
    Normalize a player name for matching: lowercase, strip all punctuation
    (hyphens, apostrophes, periods), collapse whitespace.
    Applied identically to both pick names and API response names.
    E.g. "Shai Gilgeous-Alexander" → "shai gilgeousalexander"
         "De'Aaron Fox"            → "deaaron fox"
         "Karl-Anthony Towns"      → "karlanthony towns"
    """
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _american_to_implied(american_odds: int | float) -> float:
    """
    Convert American odds to implied probability as a percentage (no vig removal).
    -110 → 52.38%   +150 → 40.0%
    """
    o = float(american_odds)
    if o < 0:
        return abs(o) / (abs(o) + 100) * 100
    else:
        return 100 / (o + 100) * 100


def _api_get(url: str, params: dict, api_key: str) -> dict | list | None:
    """GET with retry on rate limit (429). Returns None on any unrecoverable error."""
    params = dict(params)
    params["apiKey"] = api_key
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                remaining = r.headers.get("x-requests-remaining", "?")
                cost      = r.headers.get("x-requests-last", "?")
                print(f"[odds] API OK — credits this call: {cost}, remaining: {remaining}")
                return r.json()
            elif r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"[odds] Rate limited — waiting {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
            elif r.status_code == 401:
                print("[odds] ERROR: API key rejected (401) — check ODDS_API_KEY secret")
                return None
            else:
                print(f"[odds] WARNING: HTTP {r.status_code} for {url}")
                return None
        except requests.RequestException as e:
            print(f"[odds] Request error attempt {attempt + 1}: {e}")
            if attempt < 2:
                time.sleep(3)
    return None


def _write_odds_cache(cache: dict) -> None:
    """Write raw API responses to odds_today.json. Overwrites on every run."""
    try:
        with open(ODDS_JSON, "w") as f:
            json.dump({
                "date":       TODAY_STR,
                "fetched_at": dt.datetime.now(ET).isoformat(),
                "bookmaker":  BOOKMAKER,
                "events":     cache,
            }, f, indent=2)
        print(f"[odds] odds_today.json written ({len(cache)} event(s))")
    except Exception as e:
        print(f"[odds] WARNING: could not write odds_today.json: {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:

    # 1. Check API key
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("[odds] ODDS_API_KEY not set — skipping (no file changes)")
        sys.exit(0)

    # 2. Load picks.json
    if not PICKS_JSON.exists():
        print("[odds] picks.json not found — skipping")
        sys.exit(0)
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    except Exception as e:
        print(f"[odds] ERROR reading picks.json: {e} — skipping")
        sys.exit(0)

    today_picks = [
        p for p in all_picks
        if p.get("date") == TODAY_STR
        and not p.get("voided", False)
        and p.get("prop_type") in VALID_PROP_TYPES
    ]
    if not today_picks:
        print(f"[odds] No unvoided picks for {TODAY_STR} — skipping")
        sys.exit(0)

    print(f"[odds] {len(today_picks)} unvoided picks for {TODAY_STR}")

    # Build set of team abbreviations we need to find game IDs for
    teams_needed: set[str] = set()
    for p in today_picks:
        teams_needed.add(p.get("team", ""))
        teams_needed.add(p.get("opponent", ""))
    teams_needed.discard("")

    # 3. Fetch today's NBA events — free, does not count against quota
    events = _api_get(
        f"{API_BASE}/sports/{SPORT}/events",
        {"dateFormat": "iso"},
        api_key,
    )
    if events is None:
        print("[odds] Failed to fetch NBA events — skipping")
        sys.exit(0)

    # Filter to games involving our teams
    today_events = []
    for ev in events:
        home_abbr = TEAM_NAME_MAP.get(ev.get("home_team", ""))
        away_abbr = TEAM_NAME_MAP.get(ev.get("away_team", ""))
        if home_abbr in teams_needed or away_abbr in teams_needed:
            today_events.append({
                "event_id":     ev["id"],
                "home_abbr":    home_abbr,
                "away_abbr":    away_abbr,
                "home_team":    ev.get("home_team"),
                "away_team":    ev.get("away_team"),
                "commence_time": ev.get("commence_time"),
            })

    print(f"[odds] Matched {len(today_events)} game(s) for today's teams")
    if not today_events:
        print("[odds] No matching events — skipping")
        sys.exit(0)

    # 4. For each event, fetch FanDuel player prop odds (4 alternate markets)
    markets_str = ",".join(PROP_MARKET_MAP.keys())
    odds_cache: dict = {}
    # norm_player_name → f"{prop_type}_{line}" → {line, implied_prob, over_price}
    fetched: dict[str, dict[str, dict]] = {}

    for ev in today_events:
        event_id = ev["event_id"]
        result = _api_get(
            f"{API_BASE}/sports/{SPORT}/events/{event_id}/odds",
            {
                "regions":    REGIONS,
                "markets":    markets_str,
                "bookmakers": BOOKMAKER,
                "oddsFormat": "american",
            },
            api_key,
        )
        if result is None:
            print(f"[odds] WARNING: no odds for {ev['home_team']} vs {ev['away_team']}")
            continue

        odds_cache[event_id] = result

        bookmakers = result.get("bookmakers", [])
        fanduel = next((b for b in bookmakers if b.get("key") == BOOKMAKER), None)
        if fanduel is None:
            print(f"[odds] WARNING: FanDuel not in response for event {event_id}")
            continue

        for market in fanduel.get("markets", []):
            market_key = market.get("key", "")
            prop_type = PROP_MARKET_MAP.get(market_key)
            if prop_type is None:
                continue
            for outcome in market.get("outcomes", []):
                if outcome.get("name") != "Over":
                    continue
                player_name = outcome.get("description", "")
                line  = outcome.get("point")
                price = outcome.get("price")
                if not player_name or line is None or price is None:
                    continue
                norm = _norm_name(player_name)
                fetched.setdefault(norm, {})
                fetched[norm][f"{prop_type}_{float(line)}"] = {
                    "prop_type":    prop_type,
                    "line":         float(line),
                    "over_price":   int(price),
                    "implied_prob": round(_american_to_implied(price), 2),
                    "book":         BOOKMAKER,
                }

        print(f"[odds] Parsed: {ev['home_team']} vs {ev['away_team']}")

    if not fetched:
        print("[odds] No FanDuel prop data parsed — skipping picks.json update")
        _write_odds_cache(odds_cache)
        sys.exit(0)

    # 5. Match picks → odds and annotate in-place
    # Re-runs overwrite existing odds fields with latest data — correct behaviour.
    fetched_at = dt.datetime.now(ET).isoformat()
    n_matched = n_unmatched = 0

    for pick in all_picks:
        if pick.get("date") != TODAY_STR:
            continue
        if pick.get("voided", False):
            continue
        prop_type  = pick.get("prop_type")
        pick_value = pick.get("pick_value")
        confidence = pick.get("confidence_pct")
        if prop_type not in VALID_PROP_TYPES or pick_value is None:
            continue

        norm        = _norm_name(pick.get("player_name", ""))
        target_line = float(pick_value) - 0.5          # T20 → 19.5 OVER
        lookup_key  = f"{prop_type}_{target_line}"

        match = fetched.get(norm, {}).get(lookup_key)

        if match:
            pick["market_line"]         = match["line"]
            pick["market_implied_prob"] = match["implied_prob"]
            pick["market_book"]         = match["book"]
            pick["edge_pct"]            = (
                round(float(confidence) - match["implied_prob"], 2)
                if confidence is not None else None
            )
            pick["odds_fetched_at"]     = fetched_at
            n_matched += 1
            print(
                f"[odds] MATCH: {pick.get('player_name')} {prop_type} T{pick_value} "
                f"→ FanDuel {target_line} OVER @ {match['over_price']} "
                f"(implied {match['implied_prob']}%, edge {pick['edge_pct']}pp)"
            )
        else:
            n_unmatched += 1
            player_data = fetched.get(norm, {})
            if player_data:
                available = [k for k in player_data if k.startswith(prop_type)]
                print(
                    f"[odds] NO LINE: {pick.get('player_name')} {prop_type} T{pick_value} "
                    f"target={target_line} available={available or 'none'}"
                )
            else:
                print(
                    f"[odds] NO PLAYER: '{pick.get('player_name')}' "
                    f"(norm='{norm}') not in FanDuel data"
                )

    print(f"[odds] Matched {n_matched}/{n_matched + n_unmatched} picks")

    if n_matched == 0:
        print("[odds] Zero matches — skipping picks.json write")
        _write_odds_cache(odds_cache)
        sys.exit(0)

    # 6. Write picks.json atomically
    tmp = PICKS_JSON.with_suffix(".json.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(all_picks, f, indent=2)
        os.replace(tmp, PICKS_JSON)
        print(f"[odds] picks.json updated ({n_matched} picks annotated)")
    except Exception as e:
        print(f"[odds] ERROR writing picks.json: {e} — original preserved")
        if tmp.exists():
            tmp.unlink()
        sys.exit(0)

    # 7. Write odds cache
    _write_odds_cache(odds_cache)


if __name__ == "__main__":
    main()
