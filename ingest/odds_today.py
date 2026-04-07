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
ODDS_JSON           = DATA / "odds_today.json"
ODDS_AVAILABLE_JSON = DATA / "odds_available.json"
AUDIT_SUMMARY_JSON  = DATA / "audit_summary.json"
WHITELIST_CSV       = ROOT / "playerprops" / "player_whitelist.csv"

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

# Valid tier thresholds per prop type — mirrors VALID_TIERS in analyst.py.
# Used to filter prefetched odds lines to only tiers the system can pick.
# Line convention: FD line = tier_value - 0.5 (e.g. T20 PTS → 19.5 OVER).
VALID_TIERS: dict[str, list[int]] = {
    "PTS": [10, 15, 20, 25, 30],
    "REB": [4, 6, 8, 10, 12],
    "AST": [2, 4, 6, 8, 10, 12],
    "3PM": [1, 2, 3, 4],
}

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


def _load_whitelist_teams() -> set[str]:
    """
    Load active team abbreviations from the player whitelist.
    Used to filter prefetch to games with whitelisted players only — saves API credits.
    Returns empty set on any error (which means: fetch all games).
    """
    import csv
    if not WHITELIST_CSV.exists():
        print("[odds] WARNING: whitelist not found — will fetch all games")
        return set()
    try:
        teams: set[str] = set()
        with open(WHITELIST_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if str(row.get("active", "0")).strip() == "1":
                    teams.add(row["team_abbr"].strip().upper())
        print(f"[odds] Whitelist teams loaded: {sorted(teams)} ({len(teams)} teams)")
        return teams
    except Exception as e:
        print(f"[odds] WARNING: could not load whitelist: {e} — will fetch all games")
        return set()


def _load_calibration_bands() -> dict[str, float] | None:
    """
    Load confidence calibration bands from audit_summary.json.
    Returns a dict mapping band labels to actual hit rates, e.g.:
      {"70-75%": 0.85, "76-80%": 0.873, "81-85%": 0.879, "86%+": 0.941}
    Returns None if audit_summary.json is missing or has no calibration data.
    """
    if not AUDIT_SUMMARY_JSON.exists():
        print("[odds] audit_summary.json not found — calibration unavailable")
        return None
    try:
        with open(AUDIT_SUMMARY_JSON) as f:
            summary = json.load(f)
        cal = summary.get("confidence_calibration", {})
        if not cal:
            print("[odds] No confidence_calibration in audit_summary.json")
            return None
        bands = {}
        for band_label, band_data in cal.items():
            rate = band_data.get("rate")
            if rate is not None:
                bands[band_label] = float(rate)
        if not bands:
            return None
        print(f"[odds] Calibration bands loaded: {bands}")
        return bands
    except Exception as e:
        print(f"[odds] WARNING: could not load calibration: {e}")
        return None


def _get_calibrated_prob(stated_confidence: float, bands: dict[str, float]) -> float:
    """
    Map a stated confidence percentage to a calibrated probability using
    the calibration bands from audit_summary.json.

    Band mapping:
      70-75%  → stated 70.0–75.99
      76-80%  → stated 76.0–80.99
      81-85%  → stated 81.0–85.99
      86%+    → stated 86.0+

    If bands are missing or the stated confidence doesn't fall in any band,
    returns the stated confidence unchanged (conservative fallback).
    """
    if not bands:
        return stated_confidence / 100.0

    sc = float(stated_confidence)
    if sc >= 86.0:
        rate = bands.get("86%+")
    elif sc >= 81.0:
        rate = bands.get("81-85%")
    elif sc >= 76.0:
        rate = bands.get("76-80%")
    elif sc >= 70.0:
        rate = bands.get("70-75%")
    else:
        rate = None

    if rate is not None:
        return float(rate)
    # Fallback: return stated confidence as decimal
    return sc / 100.0


def compute_edge(all_picks: list[dict]) -> int:
    """
    Compute calibration-corrected edge and bet recommendations for today's picks.
    Reads calibration bands from audit_summary.json. For each today's pick that has
    odds data (market_implied_prob), computes:
      - calibrated_prob: actual expected hit rate from calibration data
      - calibrated_edge_pct: calibrated_prob - market_implied_prob (in pp)
      - kelly_quarter: quarter-Kelly fraction (% of bankroll)
      - recommendation_tier: STRONG / POSITIVE / NEUTRAL / FADE / NO_MARKET

    Writes a 'bet_recommendation' sub-object to each today's pick in the picks list.
    Returns count of picks enriched.

    Picks without market data get recommendation_tier = "NO_MARKET".
    """
    bands = _load_calibration_bands()

    n_enriched = 0
    for pick in all_picks:
        if pick.get("date") != TODAY_STR:
            continue
        if pick.get("voided", False):
            continue

        confidence = pick.get("confidence_pct")
        if confidence is None:
            continue

        market_implied = pick.get("market_implied_prob")

        # No market data — mark as NO_MARKET
        if market_implied is None:
            pick["bet_recommendation"] = {
                "calibrated_prob":     None,
                "calibration_band":    None,
                "calibrated_edge_pct": None,
                "market_implied_prob": None,
                "kelly_quarter":       None,
                "recommendation_tier": "NO_MARKET",
            }
            n_enriched += 1
            continue

        # Compute calibrated probability
        cal_prob = _get_calibrated_prob(confidence, bands)
        cal_prob_pct = round(cal_prob * 100, 1)
        market_pct = float(market_implied)

        # Calibrated edge in percentage points
        edge_pct = round(cal_prob_pct - market_pct, 2)

        # Determine calibration band label for reference
        sc = float(confidence)
        if sc >= 86.0:
            band_label = "86%+"
        elif sc >= 81.0:
            band_label = "81-85%"
        elif sc >= 76.0:
            band_label = "76-80%"
        else:
            band_label = "70-75%"

        # Quarter-Kelly calculation
        kelly_quarter = 0.0
        if edge_pct > 0 and market_pct > 0 and market_pct < 100:
            # Decimal odds from implied probability
            odds_decimal = 100.0 / market_pct
            # Full Kelly: edge / (odds - 1)
            edge_decimal = edge_pct / 100.0
            kelly_full = edge_decimal / (odds_decimal - 1.0) if odds_decimal > 1.0 else 0.0
            kelly_quarter = round(max(0.0, kelly_full / 4.0), 4)

        # Recommendation tier
        if edge_pct > 8.0:
            tier = "STRONG"
        elif edge_pct > 3.0:
            tier = "POSITIVE"
        elif edge_pct >= -3.0:
            tier = "NEUTRAL"
        else:
            tier = "FADE"

        pick["bet_recommendation"] = {
            "calibrated_prob":     cal_prob_pct,
            "calibration_band":    band_label,
            "calibrated_edge_pct": edge_pct,
            "market_implied_prob": market_pct,
            "kelly_quarter":       kelly_quarter,
            "recommendation_tier": tier,
        }
        n_enriched += 1

        print(
            f"[odds] EDGE: {pick.get('player_name')} {pick.get('prop_type')} T{pick.get('pick_value')} — "
            f"stated {confidence}% → cal {cal_prob_pct}% vs market {market_pct}% → "
            f"edge {edge_pct:+.1f}pp → {tier}"
            f"{f' (¼K={kelly_quarter:.1%})' if kelly_quarter > 0 else ''}"
        )

    return n_enriched


def prefetch_all_markets() -> None:
    """
    Prefetch mode: fetch ALL available FanDuel alternate player prop markets
    for today's games (filtered to games with whitelisted players).

    Writes data/odds_available.json with structure:
    {
      "date": "2026-04-07",
      "fetched_at": "...",
      "bookmaker": "fanduel",
      "games_fetched": 8,
      "players": {
        "normalized_name": {
          "display_name": "Jaylen Brown",
          "PTS": [{"tier": 15, "line": 14.5, "implied_prob": 97.56, "odds": -4000}, ...],
          "REB": [...],
          ...
        }
      }
    }

    Only includes tiers in VALID_TIERS. Non-system tiers (e.g. PTS 22.5) are discarded.

    Credit cost: 4 credits per game (4 alternate markets × 1 bookmaker).
    With whitelist filtering, typically 6-10 games in regular season, 2-8 in playoffs.

    Failure behavior: prints warning and exits 0. Does NOT write odds_available.json
    on failure — downstream analyst.py checks for file existence and skips the market
    gate gracefully when the file is missing.
    """
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("[odds] ODDS_API_KEY not set — skipping prefetch (no file changes)")
        sys.exit(0)

    # Load whitelist teams for credit-saving filter
    wl_teams = _load_whitelist_teams()

    # Fetch today's NBA events (free endpoint — no credit cost)
    events = _api_get(
        f"{API_BASE}/sports/{SPORT}/events",
        {"dateFormat": "iso"},
        api_key,
    )
    if events is None:
        print("[odds] Failed to fetch NBA events — skipping prefetch")
        sys.exit(0)

    # Filter to games with at least one whitelisted team (or all games if whitelist empty)
    target_events = []
    for ev in events:
        home_abbr = TEAM_NAME_MAP.get(ev.get("home_team", ""))
        away_abbr = TEAM_NAME_MAP.get(ev.get("away_team", ""))
        if not wl_teams or home_abbr in wl_teams or away_abbr in wl_teams:
            target_events.append({
                "event_id":      ev["id"],
                "home_abbr":     home_abbr,
                "away_abbr":     away_abbr,
                "home_team":     ev.get("home_team"),
                "away_team":     ev.get("away_team"),
                "commence_time": ev.get("commence_time"),
            })

    print(f"[odds] Prefetch: {len(target_events)} game(s) to fetch "
          f"(filtered from {len(events)} total events)")
    if not target_events:
        print("[odds] No target games — skipping prefetch")
        sys.exit(0)

    # Build set of valid lines for quick lookup: line_value → (prop_type, tier)
    valid_lines: dict[str, tuple[str, int]] = {}
    for prop_type, tiers in VALID_TIERS.items():
        for tier in tiers:
            line = float(tier) - 0.5   # T20 → 19.5
            valid_lines[f"{prop_type}_{line}"] = (prop_type, tier)

    # Fetch all 4 alternate markets for each game
    markets_str = ",".join(PROP_MARKET_MAP.keys())
    # norm_name → {"display_name": str, "PTS": [...], "REB": [...], ...}
    players: dict[str, dict] = {}
    games_fetched = 0

    for ev in target_events:
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

        games_fetched += 1
        bookmakers = result.get("bookmakers", [])
        fanduel = next((b for b in bookmakers if b.get("key") == BOOKMAKER), None)
        if fanduel is None:
            print(f"[odds] WARNING: FanDuel not in response for {ev['home_team']} vs {ev['away_team']}")
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
                line = outcome.get("point")
                price = outcome.get("price")
                if not player_name or line is None or price is None:
                    continue

                # Check if this line maps to a valid system tier
                lookup = f"{prop_type}_{float(line)}"
                if lookup not in valid_lines:
                    continue  # Non-system tier (e.g. PTS 22.5) — skip

                _, tier = valid_lines[lookup]
                norm = _norm_name(player_name)

                if norm not in players:
                    players[norm] = {"display_name": player_name}

                if prop_type not in players[norm]:
                    players[norm][prop_type] = []

                players[norm][prop_type].append({
                    "tier":         tier,
                    "line":         float(line),
                    "implied_prob": round(_american_to_implied(price), 2),
                    "odds":         int(price),
                })

        print(f"[odds] Prefetch parsed: {ev['home_team']} vs {ev['away_team']}")

    if not players:
        print("[odds] Prefetch: no player data parsed — odds_available.json not written")
        sys.exit(0)

    # Sort each player's tiers ascending for readability
    for norm, pdata in players.items():
        for prop_type in ["PTS", "REB", "AST", "3PM"]:
            if prop_type in pdata:
                pdata[prop_type].sort(key=lambda x: x["tier"])

    # Write odds_available.json
    output = {
        "date":          TODAY_STR,
        "fetched_at":    dt.datetime.now(ET).isoformat(),
        "bookmaker":     BOOKMAKER,
        "games_fetched": games_fetched,
        "players":       players,
    }
    try:
        with open(ODDS_AVAILABLE_JSON, "w") as f:
            json.dump(output, f, indent=2)
        print(f"[odds] odds_available.json written: {len(players)} players, "
              f"{games_fetched} games, "
              f"{sum(len(pdata.get(pt, [])) for pdata in players.values() for pt in ['PTS','REB','AST','3PM'])} total lines")
    except Exception as e:
        print(f"[odds] ERROR writing odds_available.json: {e}")
        sys.exit(0)


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

    # 6. Compute calibration-corrected edge and bet recommendations
    n_edge = compute_edge(all_picks)
    if n_edge:
        print(f"[odds] Edge computed for {n_edge} picks")

    # 7. Write picks.json atomically (includes both odds annotations and edge data)
    tmp = PICKS_JSON.with_suffix(".json.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(all_picks, f, indent=2)
        os.replace(tmp, PICKS_JSON)
        print(f"[odds] picks.json updated ({n_matched} picks annotated, {n_edge} edge-enriched)")
    except Exception as e:
        print(f"[odds] ERROR writing picks.json: {e} — original preserved")
        if tmp.exists():
            tmp.unlink()
        sys.exit(0)

    # 8. Write odds cache
    _write_odds_cache(odds_cache)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NBAgent odds collection")
    parser.add_argument("--prefetch", action="store_true",
                        help="Prefetch all available FanDuel markets (run before analyst)")
    args = parser.parse_args()

    if args.prefetch:
        prefetch_all_markets()
    else:
        main()
