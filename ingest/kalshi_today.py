#!/usr/bin/env python3
"""
kalshi_today.py — Kalshi NBA Player-Prop Mirror (Ingest P1)

Fetches Kalshi NBA player-prop markets (KXNBAPTS / KXNBAREB / KXNBAAST /
KXNBA3PT series) for today's slate, matches them to today's picks in
picks.json, and writes a parallel kalshi_* namespace on each pick.

Two modes:
  - main() (no flag): morning capture run from analyst.yml after
    odds_today.py has annotated picks with FanDuel data. Sets
    kalshi_morning_implied_prob (first capture only) and all live fields.
  - --pretip: hourly refresh run from odds_pretip.yml after the FanDuel
    pretip sweep. Refreshes live fields and applies a tip-off guard that
    preserves the last pre-tip kalshi_market_implied_prob value as the
    closing-line anchor for CLV calculations.

Failure behaviour: any error (network failure, parse error, missing
input file) prints a warning and exits 0. picks.json is never touched
on failure. The workflow can re-run safely at any time.

Cost: $0 (public endpoint, no API key). Throttle 0.20s/call. Per cycle
~16 paginated calls = ~3 seconds wall time.

Settlement note: Kalshi binary contracts settle to last fair market
price when the underlying player is DNP-active (active but doesn't
play). FanDuel voids in the same scenario. The kalshi_settlement_rule
field captures this for the auditor's future reconciliation logic
(P5, deferred).
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT           = Path(__file__).parent.parent
DATA           = ROOT / "data"
PICKS_JSON     = DATA / "picks.json"
KALSHI_JSON    = DATA / "kalshi_today.json"
NBA_MASTER_CSV = DATA / "nba_master.csv"

# ── Config ─────────────────────────────────────────────────────────────────────
ET        = ZoneInfo("America/Los_Angeles")
NOW       = dt.datetime.now(ET)
TODAY_STR = NOW.strftime("%Y-%m-%d")

KALSHI_BASE  = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT   = "NBAgent-KalshiIngest/1.0"
THROTTLE_SEC = 0.20
PAGE_LIMIT   = 200
MAX_PAGES    = 10

# Series ticker → NBAgent prop_type. 3PT in Kalshi convention, 3PM in NBAgent.
PROP_SERIES: dict[str, str] = {
    "KXNBAPTS": "PTS",
    "KXNBAREB": "REB",
    "KXNBAAST": "AST",
    "KXNBA3PT": "3PM",
}

# Prop types we accept for matching.
VALID_PROP_TYPES: set[str] = set(PROP_SERIES.values())

# All Kalshi markets settle to last fair market price (vs FanDuel void on DNP).
SETTLEMENT_RULE = "last_fair_price"

# Pre-tip grace window (mirrors odds_today.py PRETIP_GRACE_MINUTES).
# A game whose tip-off is within this many minutes in the past is still
# treated as commenced for the purposes of the tip-off guard.
PRETIP_GRACE_MINUTES = 30

# ── Regexes (lifted from kalshi_reprobe_v2.py) ────────────────────────────────
TICKER_TAIL_RE = re.compile(
    r"^(?P<series>KX[A-Z0-9]+)-"
    r"(?P<event_part>[0-9]{2}[A-Z]{3}[0-9]{2}[A-Z]{6})-"
    r"(?P<player_tag>[A-Z]+[0-9]+)-"
    r"(?P<tier>[0-9]+)$"
)

TITLE_RE = re.compile(
    r"^(?P<player>.+?):\s*(?P<tier>[0-9]+)\+\s+(?P<unit>\w+)"
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _norm_name(name: str) -> str:
    """
    Normalize a player name for matching: lowercase, strip all punctuation
    (hyphens, apostrophes, periods), collapse whitespace.
    Identical to odds_today.py._norm_name — handles Karl-Anthony Towns,
    De'Aaron Fox, Shai Gilgeous-Alexander, etc.
    """
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _f(v):
    """Coerce a possibly-string numeric to float; return None on failure."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _slate_date_ticker(d: dt.date) -> str:
    """
    Build the Kalshi event-ticker date segment for a given calendar date.
    Format: YY + uppercase 3-letter month + DD. E.g. 2026-05-01 → "26MAY01".
    """
    return f"{d.strftime('%y')}{d.strftime('%b').upper()}{d.strftime('%d')}"


def fetch(path: str, params: dict | None = None) -> dict | None:
    """
    Stdlib-based GET against the Kalshi API. Returns parsed JSON dict
    on success, None on any error (HTTP, network, parse). Never raises.
    """
    qs = "?" + urlencode(params) if params else ""
    url = f"{KALSHI_BASE}{path}{qs}"
    req = Request(url, headers={"User-Agent": USER_AGENT,
                                "Accept": "application/json"})
    try:
        with urlopen(req, timeout=15) as r:
            status = r.status
            body = r.read().decode("utf-8")
        time.sleep(THROTTLE_SEC)
        if status != 200:
            print(f"[kalshi] WARN: HTTP {status} on {url}")
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[kalshi] WARN: JSON parse failed on {url}: {e}")
            return None
    except HTTPError as e:
        print(f"[kalshi] WARN: HTTP {e.code} on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except URLError as e:
        print(f"[kalshi] WARN: network error on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except Exception as e:
        print(f"[kalshi] WARN: unexpected error on {url}: {e}")
        time.sleep(THROTTLE_SEC)
        return None


def fetch_paginated(path: str, results_key: str,
                    params: dict | None = None) -> list:
    """Paginate via cursor up to MAX_PAGES."""
    items: list = []
    cursor: str | None = None
    page = 0
    base_params = dict(params or {})
    base_params.setdefault("limit", PAGE_LIMIT)
    while page < MAX_PAGES:
        page += 1
        page_params = dict(base_params)
        if cursor:
            page_params["cursor"] = cursor
        data = fetch(path, page_params)
        if not data:
            break
        page_items = data.get(results_key, [])
        items.extend(page_items)
        cursor = data.get("cursor") or None
        if not cursor or not page_items:
            break
    if page >= MAX_PAGES:
        print(f"[kalshi] NOTE: hit MAX_PAGES on {path} — items: {len(items)}")
    return items


def parse_market(market: dict) -> dict:
    """
    Parse a Kalshi market list entry into a structured row.
    Returns a dict with: ok, ticker, event_ticker, status, title,
    yes_bid_dollars, yes_ask_dollars, volume_24h_fp, series_ticker,
    player, prop_type, tier. Sets ok=False if parsing fails.
    """
    out: dict = {
        "ok":               True,
        "ticker":           market.get("ticker"),
        "event_ticker":     market.get("event_ticker"),
        "status":           market.get("status"),
        "title":            market.get("title"),
        "yes_bid_dollars":  _f(market.get("yes_bid_dollars")),
        "yes_ask_dollars":  _f(market.get("yes_ask_dollars")),
        "volume_24h_fp":    _f(market.get("volume_24h_fp")),
        "warnings":         [],
    }

    # Ticker → series + tier
    tk = market.get("ticker") or ""
    tm = TICKER_TAIL_RE.match(tk)
    if tm:
        out["series_ticker"]    = tm.group("series")
        out["tier_from_ticker"] = int(tm.group("tier"))
    else:
        out["series_ticker"]    = None
        out["tier_from_ticker"] = None
        out["warnings"].append(f"ticker_regex_no_match: {tk}")

    # Title → player + tier
    title = market.get("title") or ""
    titlem = TITLE_RE.match(title)
    if titlem:
        out["player"]          = titlem.group("player").strip()
        out["tier_from_title"] = int(titlem.group("tier"))
    else:
        out["player"]          = None
        out["tier_from_title"] = None
        out["warnings"].append(f"title_regex_no_match: {title}")

    # Reconcile tier (title is authoritative if both present)
    tt, tn = out.get("tier_from_ticker"), out.get("tier_from_title")
    out["tier"] = tn if tn is not None else tt

    # prop_type from series
    out["prop_type"] = PROP_SERIES.get(out.get("series_ticker") or "", None)
    if out["prop_type"] is None:
        out["warnings"].append(
            f"unknown_series: {out.get('series_ticker')}"
        )

    if (out["player"] is None or out["prop_type"] is None
            or out["tier"] is None):
        out["ok"] = False

    return out


def _load_commence_times() -> dict[tuple[str, str], dt.datetime]:
    """
    Load tip-off times for today's games from nba_master.csv.

    nba_master.csv columns (per espn_daily_ingest.py):
        game_date          — "YYYY-MM-DD"
        game_time_utc      — ISO datetime (UTC)
        home_team_abbrev   — 3-letter team code
        away_team_abbrev   — 3-letter team code

    Returns a dict mapping (away_abbr, home_abbr) → tip-off datetime in PT.
    Empty dict if the file is missing, no matching rows, or any parse error.
    Used only by --pretip mode for the tip-off guard.
    """
    if not NBA_MASTER_CSV.exists():
        print("[kalshi] WARN: nba_master.csv not found — tip-off guard disabled")
        return {}
    try:
        result: dict[tuple[str, str], dt.datetime] = {}
        with open(NBA_MASTER_CSV) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("game_date") or "").strip() != TODAY_STR:
                    continue
                away = (row.get("away_team_abbrev") or "").strip().upper()
                home = (row.get("home_team_abbrev") or "").strip().upper()
                tip_str = (row.get("game_time_utc") or "").strip()
                if not (away and home and tip_str):
                    continue
                try:
                    tip = dt.datetime.fromisoformat(
                        tip_str.replace("Z", "+00:00")
                    ).astimezone(ET)
                except Exception:
                    continue
                result[(away, home)] = tip
        return result
    except Exception as e:
        print(f"[kalshi] WARN: nba_master.csv parse failed: {e} — guard disabled")
        return {}


def _load_picks() -> list:
    """Load picks.json. Returns [] on any failure (caller will sys.exit(0))."""
    if not PICKS_JSON.exists():
        return []
    try:
        with open(PICKS_JSON) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        print(f"[kalshi] ERROR reading picks.json: {e}")
        return []


def _today_pickable_picks(all_picks: list) -> list:
    """Filter picks to today, unvoided, with valid prop_type and pick_value."""
    out = []
    for p in all_picks:
        if p.get("date") != TODAY_STR:
            continue
        if p.get("voided", False):
            continue
        if p.get("prop_type") not in VALID_PROP_TYPES:
            continue
        if p.get("pick_value") is None:
            continue
        out.append(p)
    return out


def _build_team_pairs(picks: list) -> set[tuple[str, str]]:
    """
    Build the set of (team, opponent) ordered pairs from picks. Used to
    derive Kalshi matchup ticker candidates. Order is preserved per pick;
    both orderings are tried at lookup time.
    """
    pairs: set[tuple[str, str]] = set()
    for p in picks:
        t = (p.get("team") or "").strip().upper()
        o = (p.get("opponent") or "").strip().upper()
        if t and o:
            pairs.add((t, o))
    return pairs


def _build_matchup_set(team_pairs: set[tuple[str, str]]) -> set[str]:
    """
    For each (team, opponent) pair, generate BOTH orderings as candidate
    matchup ticker segments. The matching against fetched event_tickers
    will keep whichever exists.
    """
    matchups: set[str] = set()
    for t, o in team_pairs:
        matchups.add(f"{t}{o}")
        matchups.add(f"{o}{t}")
    return matchups


def _fetch_slate_markets(slate_date_ticker: str,
                         matchup_set: set[str]) -> dict:
    """
    Fetch all open markets across the four prop series, filter to today's
    slate by event_ticker, parse each, and return:
        { (norm_player, prop_type, tier): parsed_market_dict, ... }
    Plus a raw-cache dict for diagnostic write to kalshi_today.json.
    """
    expected_event_tickers: set[str] = {
        f"{series}-{slate_date_ticker}{matchup}"
        for series in PROP_SERIES
        for matchup in matchup_set
    }

    matched: dict[tuple[str, str, int], dict] = {}
    raw_cache: dict[str, list] = {}
    n_parsed = 0
    n_parse_fail = 0

    for series_ticker in PROP_SERIES:
        markets = fetch_paginated(
            "/markets", "markets",
            params={"series_ticker": series_ticker, "status": "open"},
        )
        # Fallback if empty: try without status filter (mirrors probe)
        if not markets:
            markets = fetch_paginated(
                "/markets", "markets",
                params={"series_ticker": series_ticker},
            )

        # Filter to today's slate event tickers
        slate_markets = [
            m for m in markets
            if (m.get("event_ticker") or "") in expected_event_tickers
        ]
        raw_cache[series_ticker] = slate_markets
        print(f"[kalshi] {series_ticker}: {len(markets)} total, "
              f"{len(slate_markets)} on today's slate")

        for raw in slate_markets:
            parsed = parse_market(raw)
            n_parsed += 1
            if not parsed["ok"]:
                n_parse_fail += 1
                continue
            key = (
                _norm_name(parsed["player"]),
                parsed["prop_type"],
                parsed["tier"],
            )
            matched[key] = parsed

    print(f"[kalshi] Parsed {n_parsed} slate markets "
          f"({n_parse_fail} parse failures)")
    return {"matched": matched, "raw": raw_cache}


def _write_kalshi_cache(raw_cache: dict, mode_label: str) -> None:
    """Write raw API response cache to data/kalshi_today.json. Diagnostic only."""
    try:
        with open(KALSHI_JSON, "w") as f:
            json.dump({
                "date":       TODAY_STR,
                "mode":       mode_label,
                "fetched_at": dt.datetime.now(ET).isoformat(),
                "by_series":  raw_cache,
            }, f, indent=2)
        print(f"[kalshi] kalshi_today.json written "
              f"({sum(len(v) for v in raw_cache.values())} markets, "
              f"mode={mode_label})")
    except Exception as e:
        print(f"[kalshi] WARN: could not write kalshi_today.json: {e}")


def _write_picks_atomic(all_picks: list) -> bool:
    """Atomic write of picks.json. Returns True on success."""
    tmp = PICKS_JSON.with_suffix(".json.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(all_picks, f, indent=2)
        os.replace(tmp, PICKS_JSON)
        return True
    except Exception as e:
        print(f"[kalshi] ERROR writing picks.json: {e} — original preserved")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return False


# ── main() — morning capture ──────────────────────────────────────────────────

def main() -> None:
    """
    Morning capture. Runs in analyst.yml after odds_today.py has annotated
    picks with FanDuel data. For each unvoided today's pick:
      - matched: writes all kalshi_* fields, sets kalshi_morning_implied_prob
        on first capture (idempotent)
      - unmatched: writes kalshi_market_listed: false only

    Always writes picks.json (even if zero matches) so kalshi_market_listed
    is set for the day. Always writes kalshi_today.json cache.
    """
    print(f"[kalshi] main() at {NOW.strftime('%I:%M %p PT')} for slate {TODAY_STR}")

    all_picks = _load_picks()
    if not all_picks:
        print("[kalshi] picks.json empty or missing — skipping")
        sys.exit(0)

    today_picks = _today_pickable_picks(all_picks)
    if not today_picks:
        print(f"[kalshi] No unvoided pickable picks for {TODAY_STR} — skipping")
        sys.exit(0)

    print(f"[kalshi] {len(today_picks)} unvoided picks for {TODAY_STR}")

    team_pairs   = _build_team_pairs(today_picks)
    matchup_set  = _build_matchup_set(team_pairs)
    slate_ticker = _slate_date_ticker(NOW.date())
    print(f"[kalshi] Slate date ticker: {slate_ticker}")
    print(f"[kalshi] Candidate matchups: {sorted(matchup_set)}")

    fetched = _fetch_slate_markets(slate_ticker, matchup_set)
    matched = fetched["matched"]
    _write_kalshi_cache(fetched["raw"], "morning")

    fetched_at = dt.datetime.now(ET).isoformat()
    n_matched = 0
    n_unmatched = 0

    for pick in all_picks:
        if pick.get("date") != TODAY_STR:
            continue
        if pick.get("voided", False):
            continue
        if pick.get("prop_type") not in VALID_PROP_TYPES:
            continue
        if pick.get("pick_value") is None:
            continue

        key = (
            _norm_name(pick.get("player_name", "")),
            pick.get("prop_type"),
            int(pick["pick_value"]),
        )
        m = matched.get(key)

        if m is None:
            pick["kalshi_market_listed"] = False
            n_unmatched += 1
            continue

        yes_bid = m.get("yes_bid_dollars")
        yes_ask = m.get("yes_ask_dollars")
        v24     = m.get("volume_24h_fp")

        # Implied probability = yes_bid_dollars × 100, rounded to 2 decimals.
        # (Kalshi quotes in cents, so this is always an integer-valued percent.)
        implied = round(yes_bid * 100, 2) if yes_bid is not None else None

        pick["kalshi_market_listed"]       = True
        pick["kalshi_market_ticker"]       = m.get("ticker")
        pick["kalshi_yes_bid_dollars"]     = yes_bid
        pick["kalshi_yes_ask_dollars"]     = yes_ask
        pick["kalshi_market_implied_prob"] = implied
        pick["kalshi_volume_24h_fp"]       = v24
        pick["kalshi_settlement_rule"]     = SETTLEMENT_RULE
        pick["kalshi_fetched_at"]          = fetched_at

        # First-capture morning baseline (set once, never overwritten)
        if "kalshi_morning_implied_prob" not in pick and implied is not None:
            pick["kalshi_morning_implied_prob"] = implied

        n_matched += 1
        print(
            f"[kalshi] MATCH: {pick.get('player_name')} "
            f"{pick.get('prop_type')} T{pick.get('pick_value')} "
            f"→ {m.get('ticker')} bid=${yes_bid} implied={implied}%"
        )

    coverage_pct = (n_matched / max(1, n_matched + n_unmatched)) * 100.0
    print(f"[kalshi] Coverage: {n_matched}/{n_matched + n_unmatched} "
          f"({coverage_pct:.1f}%)")

    if not _write_picks_atomic(all_picks):
        sys.exit(0)
    print(f"[kalshi] picks.json updated ({n_matched} matched, "
          f"{n_unmatched} marked unlisted)")


# ── pretip_sweep() — hourly refresh ───────────────────────────────────────────

def pretip_sweep() -> None:
    """
    Hourly refresh. Runs in odds_pretip.yml after the FanDuel pretip sweep.
    For each unvoided today's pick:
      - applies the tip-off guard: if the pick's game has already
        commenced AND the pick already has kalshi_market_implied_prob,
        skip the update (preserve closing-line anchor for CLV)
      - otherwise refresh kalshi_yes_bid_dollars / kalshi_yes_ask_dollars
        / kalshi_market_implied_prob / kalshi_volume_24h_fp / kalshi_fetched_at
      - if kalshi_morning_implied_prob is still missing on a pick (e.g.
        morning ingest failed for it), set it from the current capture as
        fallback. Better-than-nothing baseline.

    Does NOT change kalshi_market_listed: false → true. Coverage
    classification is set definitively by main(); pretip only refreshes
    already-listed picks.
    """
    print(f"[kalshi-pretip] Running at {NOW.strftime('%I:%M %p PT')}")

    all_picks = _load_picks()
    if not all_picks:
        print("[kalshi-pretip] picks.json empty or missing — skipping")
        sys.exit(0)

    today_picks = _today_pickable_picks(all_picks)
    if not today_picks:
        print(f"[kalshi-pretip] No pickable picks for {TODAY_STR} — skipping")
        sys.exit(0)

    # Build commenced_teams from nba_master.csv
    commence_times = _load_commence_times()
    commenced_teams: set[str] = set()
    for (away, home), tip in commence_times.items():
        if (NOW - tip).total_seconds() / 60.0 > -PRETIP_GRACE_MINUTES:
            # Game has tipped (or is within the grace window)
            commenced_teams.add(away)
            commenced_teams.add(home)
    if commenced_teams:
        print(f"[kalshi-pretip] Commenced teams (guard active): "
              f"{', '.join(sorted(commenced_teams))}")

    team_pairs   = _build_team_pairs(today_picks)
    matchup_set  = _build_matchup_set(team_pairs)
    slate_ticker = _slate_date_ticker(NOW.date())

    fetched = _fetch_slate_markets(slate_ticker, matchup_set)
    matched = fetched["matched"]
    _write_kalshi_cache(fetched["raw"], "pretip")

    fetched_at = dt.datetime.now(ET).isoformat()
    n_refreshed = 0
    n_guarded = 0
    n_no_match = 0
    n_movement = 0

    for pick in all_picks:
        if pick.get("date") != TODAY_STR:
            continue
        if pick.get("voided", False):
            continue
        if pick.get("prop_type") not in VALID_PROP_TYPES:
            continue
        if pick.get("pick_value") is None:
            continue

        key = (
            _norm_name(pick.get("player_name", "")),
            pick.get("prop_type"),
            int(pick["pick_value"]),
        )
        m = matched.get(key)
        if m is None:
            n_no_match += 1
            continue

        yes_bid = m.get("yes_bid_dollars")
        yes_ask = m.get("yes_ask_dollars")
        v24     = m.get("volume_24h_fp")
        implied = round(yes_bid * 100, 2) if yes_bid is not None else None

        # Tip-off guard: preserve last pre-tip implied prob as closing-line anchor
        pick_team = (pick.get("team") or "").strip().upper()
        pick_opp  = (pick.get("opponent") or "").strip().upper()
        in_commenced = (pick_team in commenced_teams or pick_opp in commenced_teams)

        if in_commenced and pick.get("kalshi_market_implied_prob") is not None:
            n_guarded += 1
            continue

        if in_commenced and pick.get("kalshi_market_implied_prob") is None:
            # No prior price + game tipped — first capture is post-tip.
            # Allow it but log a warning; CLV from this point will be unreliable.
            print(
                f"[kalshi-pretip] WARNING: first kalshi capture for "
                f"{pick.get('player_name')} {pick.get('prop_type')} "
                f"T{pick.get('pick_value')} is post-tip — CLV may be unreliable"
            )

        # Capture morning implied for movement logging
        prior_implied = pick.get("kalshi_market_implied_prob")

        pick["kalshi_market_listed"]       = True
        pick["kalshi_market_ticker"]       = m.get("ticker")
        pick["kalshi_yes_bid_dollars"]     = yes_bid
        pick["kalshi_yes_ask_dollars"]     = yes_ask
        pick["kalshi_market_implied_prob"] = implied
        pick["kalshi_volume_24h_fp"]       = v24
        pick["kalshi_settlement_rule"]     = SETTLEMENT_RULE
        pick["kalshi_fetched_at"]          = fetched_at

        # First-capture morning fallback (only if main() missed this pick)
        if "kalshi_morning_implied_prob" not in pick and implied is not None:
            pick["kalshi_morning_implied_prob"] = implied
            print(
                f"[kalshi-pretip] FALLBACK MORNING: "
                f"{pick.get('player_name')} {pick.get('prop_type')} "
                f"T{pick.get('pick_value')} = {implied}% "
                f"(morning capture missed)"
            )

        n_refreshed += 1

        # Log meaningful movement (≥1pp)
        if (prior_implied is not None and implied is not None
                and abs(implied - prior_implied) >= 1.0):
            delta = round(implied - prior_implied, 2)
            print(
                f"[kalshi-pretip] MOVEMENT: {pick.get('player_name')} "
                f"{pick.get('prop_type')} T{pick.get('pick_value')} — "
                f"{prior_implied}% → {implied}% ({delta:+.1f}pp)"
            )
            n_movement += 1

    print(f"[kalshi-pretip] Refreshed {n_refreshed}, guarded {n_guarded}, "
          f"no-match {n_no_match}, movement {n_movement}")

    if n_refreshed == 0:
        print("[kalshi-pretip] Nothing to write — picks.json unchanged")
        return

    if not _write_picks_atomic(all_picks):
        sys.exit(0)
    print(f"[kalshi-pretip] picks.json updated ({n_refreshed} picks refreshed)")


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="NBAgent Kalshi NBA player-prop ingest"
    )
    parser.add_argument("--pretip", action="store_true",
                        help="Hourly pretip refresh mode "
                             "(default: morning capture)")
    args = parser.parse_args()

    if args.pretip:
        pretip_sweep()
    else:
        main()
