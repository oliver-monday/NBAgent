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
ODDS_PRETIP_JSON    = DATA / "odds_pretip.json"
AUDIT_SUMMARY_JSON  = DATA / "audit_summary.json"
CONFIDENCE_CAL_JSON = DATA / "backtest_confidence_calibration.json"
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

# Pre-tip sweep: allow games that started up to this many minutes ago.
# FanDuel pre-game lines linger briefly after tip-off; this grace period
# ensures delayed GitHub Actions runs can still capture recently-tipped games.
PRETIP_GRACE_MINUTES = 30

# Minimum improvement in minutes-to-tip to justify a re-fetch of the same game.
# Prevents marginal re-fetches from wasting credits (e.g., two cron runs 5 min apart
# due to GitHub Actions jitter). With hourly cron, typical improvement is ~60 min.
CLOSING_LINE_MIN_IMPROVEMENT = 30

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


def _parse_fanduel_outcomes(fanduel_bookmaker: dict) -> dict[str, dict[str, dict]]:
    """
    Parse a FanDuel bookmaker response into a dict of player odds.
    Returns: norm_name -> f"{prop_type}_{line}" -> {prop_type, line, over_price, implied_prob, book}
    Shared by main() and pretip_sweep() to avoid duplicating the parsing logic.
    """
    parsed: dict[str, dict[str, dict]] = {}
    for market in fanduel_bookmaker.get("markets", []):
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
            norm = _norm_name(player_name)
            parsed.setdefault(norm, {})
            parsed[norm][f"{prop_type}_{float(line)}"] = {
                "prop_type":    prop_type,
                "line":         float(line),
                "over_price":   int(price),
                "implied_prob": round(_american_to_implied(price), 2),
                "book":         BOOKMAKER,
            }
    return parsed


def _save_morning_baseline(morning_events: dict[str, dict]) -> None:
    """
    Save the morning odds fetch as the baseline snapshot in odds_pretip.json.
    Creates a fresh file for today (overwrites any prior day's data).
    Pre-tip sweeps will append their snapshots alongside this baseline.
    """
    if not morning_events:
        return
    pretip_data = {
        "date":             TODAY_STR,
        "morning_snapshot":  morning_events,
        "snapshots":         {},
    }
    try:
        with open(ODDS_PRETIP_JSON, "w") as f:
            json.dump(pretip_data, f, indent=2)
        print(f"[odds] Morning baseline saved to odds_pretip.json "
              f"({len(morning_events)} event(s))")
    except Exception as e:
        print(f"[odds] WARNING: could not write morning baseline: {e}")


def _write_pretip_file(pretip_data: dict) -> None:
    """Write odds_pretip.json. Accumulates morning + pretip snapshots for the day."""
    try:
        with open(ODDS_PRETIP_JSON, "w") as f:
            json.dump(pretip_data, f, indent=2)
        n_morning = len(pretip_data.get("morning_snapshot", {}))
        n_pretip = len(pretip_data.get("snapshots", {}))
        print(f"[odds-pretip] odds_pretip.json written "
              f"(morning: {n_morning} events, pretip: {n_pretip} events)")
    except Exception as e:
        print(f"[odds-pretip] WARNING: could not write odds_pretip.json: {e}")


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
        cal = summary.get("confidence_calibration_totals", {})
        if not cal:
            print("[odds] No confidence_calibration_totals in audit_summary.json")
            return None
        bands = {}
        for band_label, band_data in cal.items():
            rate = band_data.get("hit_rate_pct")
            if rate is not None:
                bands[band_label] = float(rate) / 100.0
        if not bands:
            return None
        print(f"[odds] Calibration bands loaded: {bands}")
        return bands
    except Exception as e:
        print(f"[odds] WARNING: could not load calibration: {e}")
        return None


# Minimum graded picks for per-player calibration override
PER_PLAYER_CAL_MIN_PICKS = 10


def _load_per_player_calibration() -> dict[str, float] | None:
    """
    Load per-player actual hit rates from H29 backtest output.
    Returns a dict mapping normalized player name → actual hit rate (0-1 scale).
    Only includes players with >= PER_PLAYER_CAL_MIN_PICKS graded picks.
    Returns None if the file doesn't exist or has no player data.
    """
    if not CONFIDENCE_CAL_JSON.exists():
        print("[odds] backtest_confidence_calibration.json not found — per-player calibration unavailable")
        return None
    try:
        with open(CONFIDENCE_CAL_JSON) as f:
            data = json.load(f)
        players = data.get("players", [])
        if not players:
            print("[odds] No player calibration data in H29 output")
            return None
        cal = {}
        for p in players:
            name = p.get("player", "")
            n = p.get("n_picks", 0)
            rate = p.get("actual_hit_rate")
            if name and n >= PER_PLAYER_CAL_MIN_PICKS and rate is not None:
                cal[_norm_name(name)] = float(rate)
        print(f"[odds] Per-player calibration loaded: {len(cal)} players")
        return cal if cal else None
    except Exception as e:
        print(f"[odds] WARNING: could not load per-player calibration: {e}")
        return None


def _get_calibrated_prob(
    stated_confidence: float,
    bands: dict[str, float],
    player_name: str | None = None,
    per_player: dict[str, float] | None = None,
) -> tuple[float, str]:
    """
    Map a stated confidence percentage to a calibrated probability.

    Priority:
      1. Per-player actual hit rate from H29 data (if player has >= 10 picks)
      2. Population-level calibration band from audit_summary.json
      3. Stated confidence unchanged (conservative fallback)

    Returns (calibrated_probability, source) where source is one of:
      "per_player", "population_band", "fallback"
    """
    # Priority 1: per-player override
    if per_player and player_name:
        norm = _norm_name(player_name)
        if norm in per_player:
            return per_player[norm], "per_player"

    # Priority 2: population band
    if bands:
        sc = float(stated_confidence)
        if sc >= 86.0:
            rate = bands.get("86+")
        elif sc >= 81.0:
            rate = bands.get("81-85")
        elif sc >= 76.0:
            rate = bands.get("76-80")
        elif sc >= 70.0:
            rate = bands.get("70-75")
        else:
            rate = None

        if rate is not None:
            return float(rate), "population_band"

    # Priority 3: fallback to stated confidence
    return float(stated_confidence) / 100.0, "fallback"


def pretip_sweep(window_minutes: int = 360) -> None:
    """
    Pre-tip odds sweep: fetch FanDuel odds for games within the capture window.
    Updates picks.json with latest pre-tip odds (overwriting the morning
    market_implied_prob) and logs line movement vs. the morning baseline
    (morning_implied_prob, set by main()).

    Window logic: a game is fetchable when it tips off within `window_minutes`
    from now OR started within the last PRETIP_GRACE_MINUTES (30 min default).
    This grace period compensates for GitHub Actions cron delays (typically 1–6
    hours). Combined with deduplication (each game fetched at most once), the
    wide window has zero extra credit cost.

    Credit cost: 4 credits per newly-captured game. Already-captured games are
    skipped via dedup on event_id.

    Args:
        window_minutes: How many minutes before tip-off a game becomes fetchable.
                        Default 360 (6 hours — captures games as soon as FanDuel
                        posts props, regardless of GitHub scheduling delays).
    """
    api_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not api_key:
        print("[odds-pretip] ODDS_API_KEY not set — skipping")
        sys.exit(0)

    now = dt.datetime.now(ET)
    print(f"[odds-pretip] Running at {now.strftime('%I:%M %p PT')} "
          f"(window: {window_minutes} min before tip, "
          f"{PRETIP_GRACE_MINUTES} min grace after tip)")

    # 1. Load picks.json — need today's picks to annotate
    if not PICKS_JSON.exists():
        print("[odds-pretip] picks.json not found — skipping")
        sys.exit(0)
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    except Exception as e:
        print(f"[odds-pretip] ERROR reading picks.json: {e} — skipping")
        sys.exit(0)

    today_picks = [
        p for p in all_picks
        if p.get("date") == TODAY_STR
        and not p.get("voided", False)
        and p.get("prop_type") in VALID_PROP_TYPES
    ]
    if not today_picks:
        print(f"[odds-pretip] No unvoided picks for {TODAY_STR} — skipping")
        sys.exit(0)

    # 2. Fetch today's NBA events (free endpoint — no credit cost)
    events = _api_get(
        f"{API_BASE}/sports/{SPORT}/events",
        {"dateFormat": "iso"},
        api_key,
    )
    if events is None:
        print("[odds-pretip] Failed to fetch NBA events — skipping")
        sys.exit(0)

    # Build set of teams we have picks for
    teams_needed: set[str] = set()
    for p in today_picks:
        teams_needed.add(p.get("team", ""))
        teams_needed.add(p.get("opponent", ""))
    teams_needed.discard("")

    # 3. Filter to games in the pre-tip window
    #    In-window: now >= commence_time - window_minutes AND now < commence_time
    in_window_events = []
    skipped_early = 0
    skipped_started = 0
    skipped_no_team = 0

    for ev in events:
        home_abbr = TEAM_NAME_MAP.get(ev.get("home_team", ""))
        away_abbr = TEAM_NAME_MAP.get(ev.get("away_team", ""))

        # Only fetch games we have picks for
        if home_abbr not in teams_needed and away_abbr not in teams_needed:
            skipped_no_team += 1
            continue

        commence_str = ev.get("commence_time", "")
        if not commence_str:
            continue
        try:
            commence = dt.datetime.fromisoformat(
                commence_str.replace("Z", "+00:00")
            ).astimezone(ET)
        except Exception:
            continue

        minutes_to_tip = (commence - now).total_seconds() / 60.0

        if minutes_to_tip > window_minutes:
            skipped_early += 1
            continue
        if minutes_to_tip < -PRETIP_GRACE_MINUTES:
            skipped_started += 1
            continue

        in_window_events.append({
            "event_id":       ev["id"],
            "home_abbr":      home_abbr,
            "away_abbr":      away_abbr,
            "home_team":      ev.get("home_team"),
            "away_team":      ev.get("away_team"),
            "commence_time":  commence_str,
            "minutes_to_tip": round(minutes_to_tip),
        })

    print(f"[odds-pretip] {len(in_window_events)} game(s) in window "
          f"(skipped: {skipped_early} too early, "
          f"{skipped_started} started >{PRETIP_GRACE_MINUTES}min ago, "
          f"{skipped_no_team} no picks)")

    # Build set of team abbreviations whose games have already commenced.
    # Used in step 6 to prevent overwriting market_implied_prob with live lines
    # — the grace window still allows fetch/dedup/snapshot for these games, but
    # picks with an existing pre-game price must preserve it so CLV stays clean.
    commenced_teams: set[str] = set()
    for ev in in_window_events:
        if ev["minutes_to_tip"] < 0:
            if ev["home_abbr"]:
                commenced_teams.add(ev["home_abbr"])
            if ev["away_abbr"]:
                commenced_teams.add(ev["away_abbr"])
    if commenced_teams:
        print(f"[odds-pretip] Commenced teams (live line guard active): "
              f"{', '.join(sorted(commenced_teams))}")

    if not in_window_events:
        print("[odds-pretip] No games in pre-tip window — nothing to fetch")
        sys.exit(0)

    # 4. Load existing pretip file to check for already-fetched events
    pretip_data: dict = {"date": TODAY_STR, "morning_snapshot": {}, "snapshots": {}}
    if ODDS_PRETIP_JSON.exists():
        try:
            with open(ODDS_PRETIP_JSON) as f:
                loaded = json.load(f)
            if loaded.get("date") == TODAY_STR:
                pretip_data = loaded
            else:
                print(f"[odds-pretip] odds_pretip.json is stale ({loaded.get('date')}) "
                      f"— starting fresh")
        except Exception as e:
            print(f"[odds-pretip] WARNING: could not read odds_pretip.json: {e}")

    # Closing-line model: re-fetch games when we're meaningfully closer to
    # tip-off than the prior snapshot, converging on the true closing line.
    # The tip-off guard in step 6 prevents post-tip contamination — the last
    # successful pre-tip fetch becomes the definitive closing line.
    prior_snapshots = pretip_data.get("snapshots", {})
    to_fetch = []
    n_refetch = 0
    n_skip_commenced = 0
    n_skip_marginal = 0

    for ev in in_window_events:
        eid = ev["event_id"]
        current_mtt = ev["minutes_to_tip"]  # minutes to tip right now

        # Never re-fetch games that have already started — snapshot is locked
        if current_mtt < 0:
            n_skip_commenced += 1
            continue

        prior = prior_snapshots.get(eid)
        if prior is None:
            # First fetch for this game — always include
            to_fetch.append(ev)
            continue

        prior_mtt = prior.get("minutes_to_tip")
        if prior_mtt is None:
            # Prior snapshot missing minutes_to_tip — re-fetch to be safe
            to_fetch.append(ev)
            n_refetch += 1
            continue

        improvement = prior_mtt - current_mtt
        if improvement >= CLOSING_LINE_MIN_IMPROVEMENT:
            to_fetch.append(ev)
            n_refetch += 1
        else:
            n_skip_marginal += 1

    status_parts = []
    if n_refetch:
        status_parts.append(f"{n_refetch} re-fetch (closer to tip)")
    if n_skip_commenced:
        status_parts.append(f"{n_skip_commenced} commenced (locked)")
    if n_skip_marginal:
        status_parts.append(f"{n_skip_marginal} marginal (<{CLOSING_LINE_MIN_IMPROVEMENT}min improvement)")
    first_fetch = len(to_fetch) - n_refetch
    if first_fetch > 0:
        status_parts.append(f"{first_fetch} first capture")
    print(f"[odds-pretip] Closing-line filter: {', '.join(status_parts) or 'no events'}")

    if not to_fetch:
        print(f"[odds-pretip] No games qualify for fetch — skipping")
        sys.exit(0)

    print(f"[odds-pretip] Fetching odds for {len(to_fetch)} game(s) "
          f"(~{len(to_fetch) * 4} credits)")

    # 5. Fetch FanDuel odds for in-window games
    markets_str = ",".join(PROP_MARKET_MAP.keys())
    # Flat dict for pick matching (same structure as main())
    fetched: dict[str, dict[str, dict]] = {}

    for ev in to_fetch:
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
            print(f"[odds-pretip] WARNING: no odds for "
                  f"{ev['home_team']} vs {ev['away_team']}")
            continue

        bookmakers = result.get("bookmakers", [])
        fanduel = next((b for b in bookmakers if b.get("key") == BOOKMAKER), None)
        if fanduel is None:
            print(f"[odds-pretip] WARNING: FanDuel not in response for "
                  f"{ev['home_team']} vs {ev['away_team']}")
            continue

        event_parsed = _parse_fanduel_outcomes(fanduel)
        for norm, props in event_parsed.items():
            fetched.setdefault(norm, {}).update(props)

        # Save per-event snapshot
        pretip_data.setdefault("snapshots", {})[event_id] = {
            "home":           ev["home_abbr"],
            "away":           ev["away_abbr"],
            "commence_time":  ev["commence_time"],
            "fetched_at":     dt.datetime.now(ET).isoformat(),
            "minutes_to_tip": ev["minutes_to_tip"],
            "players":        event_parsed,
        }

        prior = prior_snapshots.get(event_id)
        if prior and prior.get("minutes_to_tip") is not None:
            print(f"[odds-pretip] Re-fetched: {ev['away_abbr']} @ {ev['home_abbr']} "
                  f"(was +{prior['minutes_to_tip']}min, now +{ev['minutes_to_tip']}min to tip)")
        else:
            print(f"[odds-pretip] Fetched: {ev['away_abbr']} @ {ev['home_abbr']} "
                  f"(tips in {ev['minutes_to_tip']} min)")

    if not fetched:
        # Still save the pretip file even if no FanDuel data parsed —
        # records the attempt so we don't re-fetch
        _write_pretip_file(pretip_data)
        print("[odds-pretip] No FanDuel data parsed — skipping picks.json update")
        sys.exit(0)

    # 6. Match picks → odds and update in-place (same logic as main())
    #    Also log line movement vs morning prices.
    morning_snapshot = pretip_data.get("morning_snapshot", {})
    fetched_at = dt.datetime.now(ET).isoformat()
    n_matched = 0
    n_movement = 0

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
        target_line = float(pick_value) - 0.5
        lookup_key  = f"{prop_type}_{target_line}"

        match = fetched.get(norm, {}).get(lookup_key)
        if not match:
            continue

        # Tip-off guard: do not overwrite market_implied_prob with post-tip lines.
        # If the pick's game has commenced and it already has a pre-game price,
        # the existing value is more trustworthy than a potentially live line.
        pick_team = pick.get("team", "")
        pick_opp  = pick.get("opponent", "")
        if (pick_team in commenced_teams or pick_opp in commenced_teams):
            if pick.get("market_implied_prob") is not None:
                # Already has pre-game price — skip to preserve CLV integrity
                continue
            # No prior price — this is the first capture. Allow it through
            # but log a warning since it's post-tip.
            print(
                f"[odds-pretip] WARNING: first odds capture for "
                f"{pick.get('player_name')} {pick.get('prop_type')} "
                f"T{pick.get('pick_value')} is post-tip — CLV may be unreliable"
            )

        # Capture morning implied prob before overwriting
        morning_implied = pick.get("market_implied_prob")

        # Persist morning odds for CLV tracking (set once, never overwritten by later pretip runs)
        if "morning_implied_prob" not in pick and morning_implied is not None:
            pick["morning_implied_prob"] = morning_implied

        # Overwrite with latest odds
        pick["market_line"]         = match["line"]
        pick["market_implied_prob"] = match["implied_prob"]
        pick["market_book"]         = match["book"]
        pick["edge_pct"]            = (
            round(float(confidence) - match["implied_prob"], 2)
            if confidence is not None else None
        )
        pick["odds_fetched_at"]     = fetched_at
        n_matched += 1

        # Log line movement
        if morning_implied is not None:
            delta = round(match["implied_prob"] - float(morning_implied), 2)
            if abs(delta) >= 0.5:  # Only log meaningful movement (>=0.5pp)
                morning_edge = (
                    round(float(confidence) - float(morning_implied), 2)
                    if confidence is not None else None
                )
                new_edge = pick["edge_pct"]
                if delta > 0:
                    direction = "market up (edge shrinks — market agrees more)"
                else:
                    direction = "market down (edge grows — market disagrees more)"

                print(
                    f"[odds-pretip] MOVEMENT: {pick.get('player_name')} "
                    f"{prop_type} T{pick_value} — "
                    f"morning {morning_implied}% -> pretip {match['implied_prob']}% "
                    f"({delta:+.1f}pp) {direction}"
                )
                if morning_edge is not None and new_edge is not None:
                    print(
                        f"[odds-pretip]   edge: {morning_edge:+.1f}pp -> "
                        f"{new_edge:+.1f}pp"
                    )
                n_movement += 1

    print(f"[odds-pretip] Updated {n_matched} picks, "
          f"{n_movement} with line movement")

    if n_matched > 0:
        # Recompute calibration edge with updated odds
        n_edge = compute_edge(all_picks)
        if n_edge:
            print(f"[odds-pretip] Edge recomputed for {n_edge} picks")

        # Write picks.json atomically
        tmp = PICKS_JSON.with_suffix(".json.tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(all_picks, f, indent=2)
            os.replace(tmp, PICKS_JSON)
            print(f"[odds-pretip] picks.json updated ({n_matched} picks)")
        except Exception as e:
            print(f"[odds-pretip] ERROR writing picks.json: {e}")
            if tmp.exists():
                tmp.unlink()

    # 7. Write pretip snapshot file
    _write_pretip_file(pretip_data)


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
    per_player = _load_per_player_calibration()

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

        # Compute calibrated probability (per-player H29 override → population band → fallback)
        player_name = pick.get("player_name", "")
        cal_prob, cal_source = _get_calibrated_prob(confidence, bands, player_name, per_player)
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
            "calibration_source":  cal_source,
            "calibrated_edge_pct": edge_pct,
            "market_implied_prob": market_pct,
            "kelly_quarter":       kelly_quarter,
            "recommendation_tier": tier,
        }
        n_enriched += 1

        print(
            f"[odds] EDGE: {pick.get('player_name')} {pick.get('prop_type')} T{pick.get('pick_value')} — "
            f"stated {confidence}% → cal {cal_prob_pct}% ({cal_source}) vs market {market_pct}% → "
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

    # Sort each player's tiers ascending and deduplicate by tier
    for norm, pdata in players.items():
        for prop_type in ["PTS", "REB", "AST", "3PM"]:
            if prop_type in pdata:
                pdata[prop_type].sort(key=lambda x: x["tier"])
                seen_tiers: set[int] = set()
                deduped: list[dict] = []
                for entry in pdata[prop_type]:
                    if entry["tier"] not in seen_tiers:
                        seen_tiers.add(entry["tier"])
                        deduped.append(entry)
                pdata[prop_type] = deduped

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
    # Per-event snapshot for morning baseline in odds_pretip.json
    morning_events: dict[str, dict] = {}

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

        event_parsed = _parse_fanduel_outcomes(fanduel)
        for norm, props in event_parsed.items():
            fetched.setdefault(norm, {}).update(props)

        # Save per-event snapshot for morning baseline
        morning_events[event_id] = {
            "home":           ev.get("home_abbr"),
            "away":           ev.get("away_abbr"),
            "commence_time":  ev.get("commence_time"),
            "fetched_at":     dt.datetime.now(ET).isoformat(),
            "players":        event_parsed,
        }

        print(f"[odds] Parsed: {ev['home_team']} vs {ev['away_team']}")

    if not fetched:
        print("[odds] No FanDuel prop data parsed — skipping picks.json update")
        _write_odds_cache(odds_cache)
        sys.exit(0)

    # 4b. Save morning baseline to odds_pretip.json
    _save_morning_baseline(morning_events)

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

            # Capture morning baseline for CLV tracking (set once per pick per day).
            # Later pretip runs overwrite market_implied_prob with pre-tip odds;
            # morning_implied_prob preserves the original morning line so
            # auditor.save_audit() can compute clv_pp = market (pretip) − morning.
            if "morning_implied_prob" not in pick:
                pick["morning_implied_prob"] = match["implied_prob"]

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
    parser.add_argument("--pretip", action="store_true",
                        help="Pre-tip sweep: fetch odds for games tipping within window")
    parser.add_argument("--window-minutes", type=int, default=360,
                        help="Pre-tip window in minutes before tip-off (default: 360)")
    args = parser.parse_args()

    if args.prefetch:
        prefetch_all_markets()
    elif args.pretip:
        pretip_sweep(window_minutes=args.window_minutes)
    else:
        main()
