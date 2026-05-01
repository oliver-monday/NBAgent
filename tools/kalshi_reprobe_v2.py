#!/usr/bin/env python3
"""
NBAgent — Kalshi NBA Prop Re-Probe v2 (one-off, May 1 slate)

Bug-fixed sibling to tools/kalshi_reprobe.py. Same scope (four NBA
player-prop series × three matchups × floor-tier focus), corrected
orderbook parsing (orderbook_fp / yes_dollars / no_dollars) and
top-of-book promotion from per-market list response.

Usage:
    python tools/kalshi_reprobe_v2.py

No flags. Idempotent — re-runs overwrite previous artifacts.
"""

from __future__ import annotations

import json
import time
import re
import datetime as dt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT  = DATA / "kalshi_reprobe_v2"
OUT.mkdir(parents=True, exist_ok=True)

PT = ZoneInfo("America/Los_Angeles")
TIMESTAMP = dt.datetime.now(PT).strftime("%Y-%m-%dT%H:%M:%S%z")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT  = "NBAgent-Reprobe-v2/1.0 (one-off discovery; contact: nbagent)"
THROTTLE_SEC = 0.20
PAGE_LIMIT   = 200
MAX_PAGES    = 10

# Hard-coded scope — same as v1 (the bug was in parsing, not scope)
PROP_SERIES: dict[str, str] = {
    "KXNBAPTS": "PTS",
    "KXNBAREB": "REB",
    "KXNBAAST": "AST",
    "KXNBA3PT": "3PM",
}
SLATE_DATE_TICKER = "26MAY01"
SLATE_MATCHUPS = ["DETORL", "CLETOR", "LALHOU"]
FLOOR_TIER_COUNT = 2

# Liquidity classification thresholds — for the report's verdict cell.
# YES depth in $$ (price × qty summed) at any level.
LIQUIDITY_TIERS = [
    ("liquid",       50.0),    # ≥ $50 of YES depth = real two-sided market
    ("thin",          5.0),    # ≥ $5  of YES depth = some flow
    ("top_of_book",   0.01),   # any bid > $0.01 but no depth-summed amount
]
# Below all of the above = "empty" (no bids at all)


# ── HTTP + pagination helpers (lifted verbatim from v1; correct) ─────

def fetch(path: str, params: dict | None = None) -> dict | None:
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
            print(f"[reprobe-v2] WARN: HTTP {status} on {url}")
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[reprobe-v2] WARN: JSON parse failed on {url}: {e}")
            return None
    except HTTPError as e:
        print(f"[reprobe-v2] WARN: HTTP {e.code} on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except URLError as e:
        print(f"[reprobe-v2] WARN: network error on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except Exception as e:
        print(f"[reprobe-v2] WARN: unexpected error on {url}: {e}")
        time.sleep(THROTTLE_SEC)
        return None


def fetch_paginated(path: str, results_key: str,
                    params: dict | None = None) -> list:
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
        print(f"[reprobe-v2] NOTE: hit MAX_PAGES on {path} — items: {len(items)}")
    return items


# ── Step 1 — fetch slate markets (unchanged from v1) ─────────────────

def step1_fetch_slate_markets() -> dict:
    print(f"\n=== Step 1: Fetch slate markets ({SLATE_DATE_TICKER}) ===")
    by_matchup: dict[str, dict[str, list]] = {
        m: {s: [] for s in PROP_SERIES} for m in SLATE_MATCHUPS
    }
    expected_event_prefixes = {
        s: {m: f"{s}-{SLATE_DATE_TICKER}{m}" for m in SLATE_MATCHUPS}
        for s in PROP_SERIES
    }
    for series_ticker in PROP_SERIES:
        print(f"\n[reprobe-v2] Series {series_ticker} — fetching markets...")
        markets = fetch_paginated("/markets", "markets",
                                  params={"series_ticker": series_ticker,
                                          "status": "open"})
        if not markets:
            markets = fetch_paginated("/markets", "markets",
                                      params={"series_ticker": series_ticker})
        print(f"  total markets fetched: {len(markets)}")
        (OUT / f"01_markets_{series_ticker}.json").write_text(
            json.dumps(markets, indent=2), encoding="utf-8")
        for m in markets:
            evt = (m.get("event_ticker") or "")
            for matchup in SLATE_MATCHUPS:
                if evt == expected_event_prefixes[series_ticker][matchup]:
                    by_matchup[matchup][series_ticker].append(m)
                    break
        per_matchup_counts = {
            matchup: len(by_matchup[matchup][series_ticker])
            for matchup in SLATE_MATCHUPS
        }
        print(f"  filtered to slate: {per_matchup_counts} "
              f"(total: {sum(per_matchup_counts.values())})")
    (OUT / "02_slate_markets.json").write_text(
        json.dumps(by_matchup, indent=2), encoding="utf-8")
    return by_matchup


# ── Step 2 — parse_market() (mostly unchanged + new top-of-book) ─────

TICKER_TAIL_RE = re.compile(
    r"^(?P<series>KX[A-Z0-9]+)-"
    r"(?P<event_part>[0-9]{2}[A-Z]{3}[0-9]{2}[A-Z]{6})-"
    r"(?P<player_tag>[A-Z]+[0-9]+)-"
    r"(?P<tier>[0-9]+)$"
)

TITLE_RE = re.compile(r"^(?P<player>.+?):\s*(?P<tier>[0-9]+)\+\s+(?P<unit>\w+)")


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


def parse_market(market: dict, series_to_prop: dict[str, str]) -> dict:
    """Parse a Kalshi market list entry into a structured row."""
    out: dict = {
        "ok": True,
        "ticker":              market.get("ticker"),
        "event_ticker":        market.get("event_ticker"),
        "status":              market.get("status"),
        "title":               market.get("title"),
        "yes_sub_title":       market.get("yes_sub_title"),
        # Top-of-book — float-cast defensively
        "yes_bid_dollars":     _f(market.get("yes_bid_dollars")),
        "yes_ask_dollars":     _f(market.get("yes_ask_dollars")),
        "no_bid_dollars":      _f(market.get("no_bid_dollars")),
        "no_ask_dollars":      _f(market.get("no_ask_dollars")),
        "last_price_dollars":  _f(market.get("last_price_dollars")),
        # Size fields (per-side top-of-book quantity)
        "yes_bid_size_fp":     _f(market.get("yes_bid_size_fp")),
        "yes_ask_size_fp":     _f(market.get("yes_ask_size_fp")),
        # Volume / OI / liquidity hints
        "volume_fp":           _f(market.get("volume_fp")),
        "volume_24h_fp":       _f(market.get("volume_24h_fp")),
        "open_interest_fp":    _f(market.get("open_interest_fp")),
        "liquidity_dollars":   _f(market.get("liquidity_dollars")),
        # Timing
        "open_time":           market.get("open_time"),
        "close_time":          market.get("close_time"),
        "parse_warnings":      [],
    }

    tk = market.get("ticker") or ""
    tm = TICKER_TAIL_RE.match(tk)
    if tm:
        out["series_ticker"]    = tm.group("series")
        out["player_tag"]       = tm.group("player_tag")
        out["tier_from_ticker"] = int(tm.group("tier"))
    else:
        out["series_ticker"]    = None
        out["player_tag"]       = None
        out["tier_from_ticker"] = None
        out["parse_warnings"].append(f"ticker_regex_no_match: {tk}")

    title = market.get("title") or ""
    titlem = TITLE_RE.match(title)
    if titlem:
        out["player"] = titlem.group("player").strip()
        out["tier_from_title"] = int(titlem.group("tier"))
    else:
        out["player"] = None
        out["tier_from_title"] = None
        out["parse_warnings"].append(f"title_regex_no_match: {title}")

    tt = out.get("tier_from_ticker")
    tn = out.get("tier_from_title")
    if tt is not None and tn is not None and tt != tn:
        out["parse_warnings"].append(
            f"tier_mismatch: ticker={tt} title={tn}")
    out["tier"] = tn if tn is not None else tt

    out["prop_type"] = series_to_prop.get(out.get("series_ticker") or "", None)
    if out["prop_type"] is None:
        out["parse_warnings"].append(
            f"unknown_series: {out.get('series_ticker')}")

    if out["parse_warnings"]:
        out["ok"] = False
    return out


# ── Step 3 — build tier ladders (unchanged from v1) ──────────────────

def step3_build_tier_ladders(by_matchup: dict) -> dict:
    print(f"\n=== Step 3: Build per-player tier ladders ===")
    ladders: dict = {}
    parse_failures = 0
    parsed_total = 0

    for matchup, by_series in by_matchup.items():
        ladders.setdefault(matchup, {})
        for series_ticker, markets in by_series.items():
            for raw in markets:
                parsed = parse_market(raw, PROP_SERIES)
                parsed_total += 1
                if not parsed["ok"]:
                    parse_failures += 1
                    continue
                player = parsed["player"]
                prop   = parsed["prop_type"]
                tier   = parsed["tier"]
                if player is None or prop is None or tier is None:
                    parse_failures += 1
                    continue
                ladders[matchup].setdefault(player, {}).setdefault(
                    prop, {"tiers": [], "markets_by_tier": {}}
                )
                node = ladders[matchup][player][prop]
                if tier not in node["tiers"]:
                    node["tiers"].append(tier)
                node["markets_by_tier"][tier] = parsed

    for matchup, players in ladders.items():
        for player, props in players.items():
            for prop, node in props.items():
                node["tiers"] = sorted(node["tiers"])
                node["floor_tiers"]    = node["tiers"][:FLOOR_TIER_COUNT]
                node["headline_tiers"] = node["tiers"][FLOOR_TIER_COUNT:]

    print(f"[reprobe-v2] Parsed {parsed_total} markets; "
          f"{parse_failures} parse failures.")
    (OUT / "03_tier_ladders.json").write_text(
        json.dumps(ladders, indent=2), encoding="utf-8")
    return ladders


# ── Step 4 — orderbook depth probe with FIXED parsing ────────────────

def parse_orderbook(ob_response: dict | None) -> dict:
    """
    Parse an /orderbook response into a structured depth summary.

    The Kalshi orderbook response shape (verified against deep-dive
    sample on 2026-04-30):
        {"orderbook_fp": {
            "yes_dollars": [[price_str, qty_str], ...],
            "no_dollars":  [[price_str, qty_str], ...]
        }}
    Inner arrays sorted ascending by price; LAST element is top-of-book.
    Both arrays may be empty. Values are STRINGS that need float casting.
    """
    if not ob_response:
        return _empty_depth_summary()
    inner = ob_response.get("orderbook_fp")
    if not inner:
        return _empty_depth_summary()

    yes_levels = inner.get("yes_dollars") or []
    no_levels  = inner.get("no_dollars")  or []

    def _agg(levels: list) -> dict:
        n = 0
        total_qty = 0.0
        total_dollar_depth = 0.0
        top_price = None
        top_qty   = None
        for row in levels:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            price = _f(row[0])
            qty   = _f(row[1])
            if price is None or qty is None:
                continue
            n += 1
            total_qty += qty
            total_dollar_depth += price * qty
            top_price = price       # keep updating; LAST is top-of-book
            top_qty   = qty
        return {
            "n_levels":             n,
            "total_qty":            round(total_qty, 2),
            "total_dollar_depth":   round(total_dollar_depth, 2),
            "top_of_book_price":    top_price,
            "top_of_book_qty":      top_qty,
        }

    return {
        "yes": _agg(yes_levels),
        "no":  _agg(no_levels),
    }


def _empty_depth_summary() -> dict:
    empty_side = {
        "n_levels":           0,
        "total_qty":          0.0,
        "total_dollar_depth": 0.0,
        "top_of_book_price":  None,
        "top_of_book_qty":    None,
    }
    return {"yes": dict(empty_side), "no": dict(empty_side)}


def step4_orderbook_depth(ladders: dict) -> dict:
    """Fetch orderbook for every market in the ladder; parse with fixed logic."""
    print(f"\n=== Step 4: Orderbook depth — every slate market ===")
    flat_records: list[dict] = []
    n_total = 0
    n_with_yes_levels = 0
    n_with_any_levels = 0

    for matchup in sorted(ladders.keys()):
        for player in sorted(ladders[matchup].keys()):
            for prop in sorted(ladders[matchup][player].keys()):
                node = ladders[matchup][player][prop]
                for tier in node["tiers"]:
                    market = node["markets_by_tier"][tier]
                    mt = market.get("ticker")
                    if not mt:
                        continue
                    n_total += 1
                    ob_response = fetch(f"/markets/{mt}/orderbook")
                    depth = parse_orderbook(ob_response)
                    market["orderbook_depth"] = depth

                    yes_n = depth["yes"]["n_levels"]
                    no_n  = depth["no"]["n_levels"]
                    if yes_n > 0:
                        n_with_yes_levels += 1
                    if yes_n > 0 or no_n > 0:
                        n_with_any_levels += 1

                    is_floor = tier in node["floor_tiers"]
                    flat_records.append({
                        "matchup":         matchup,
                        "player":          player,
                        "prop_type":       prop,
                        "tier":            tier,
                        "is_floor_tier":   is_floor,
                        "ticker":          mt,
                        "status":          market.get("status"),
                        "title":           market.get("title"),
                        # Top-of-book from market list
                        "yes_bid_dollars":     market.get("yes_bid_dollars"),
                        "yes_ask_dollars":     market.get("yes_ask_dollars"),
                        "no_bid_dollars":      market.get("no_bid_dollars"),
                        "no_ask_dollars":      market.get("no_ask_dollars"),
                        "last_price_dollars":  market.get("last_price_dollars"),
                        "yes_bid_size_fp":     market.get("yes_bid_size_fp"),
                        "yes_ask_size_fp":     market.get("yes_ask_size_fp"),
                        # Volume / OI
                        "volume_fp":           market.get("volume_fp"),
                        "volume_24h_fp":       market.get("volume_24h_fp"),
                        "open_interest_fp":    market.get("open_interest_fp"),
                        # Orderbook-side aggregates
                        "yes_n_levels":        depth["yes"]["n_levels"],
                        "yes_total_qty":       depth["yes"]["total_qty"],
                        "yes_total_dollar_depth": depth["yes"]["total_dollar_depth"],
                        "yes_top_price":       depth["yes"]["top_of_book_price"],
                        "no_n_levels":         depth["no"]["n_levels"],
                        "no_total_qty":        depth["no"]["total_qty"],
                        "no_total_dollar_depth":  depth["no"]["total_dollar_depth"],
                        "no_top_price":        depth["no"]["top_of_book_price"],
                    })

    pct_yes = n_with_yes_levels / max(1, n_total) * 100
    pct_any = n_with_any_levels / max(1, n_total) * 100
    print(f"[reprobe-v2] Fetched {n_total} orderbooks.")
    print(f"[reprobe-v2]   With non-empty YES side: {n_with_yes_levels} ({pct_yes:.1f}%)")
    print(f"[reprobe-v2]   With any side populated: {n_with_any_levels} ({pct_any:.1f}%)")

    (OUT / "04_orderbook_records.json").write_text(
        json.dumps(flat_records, indent=2), encoding="utf-8")
    (OUT / "05_ladders_with_orderbook.json").write_text(
        json.dumps(ladders, indent=2), encoding="utf-8")
    return {"ladders": ladders, "flat": flat_records}


# ── Step 5 — write the report (expanded with top-of-book columns) ────

def classify_liquidity(record: dict) -> str:
    """
    Bucket a market into liquid / thin / top_of_book / empty using the
    YES side's dollar depth and presence of a YES bid.
    """
    yes_depth = record.get("yes_total_dollar_depth") or 0.0
    yes_bid   = record.get("yes_bid_dollars") or 0.0
    if yes_depth >= 50.0:
        return "liquid"
    if yes_depth >= 5.0:
        return "thin"
    if (yes_bid is not None) and yes_bid > 0.0:
        return "top_of_book"
    return "empty"


def step5_write_report(by_matchup: dict, ladders: dict,
                        flat_records: list) -> Path:
    lines: list[str] = []
    lines.append(f"# Kalshi NBA Re-Probe v2 — May 1 Slate")
    lines.append("")
    lines.append(f"Generated by `tools/kalshi_reprobe_v2.py` at {TIMESTAMP}.")
    lines.append("")
    lines.append("**Bug-fixed sibling to `tools/kalshi_reprobe.py`** — corrected "
                 "orderbook parsing (`orderbook_fp` outer key, `yes_dollars`/"
                 "`no_dollars` inner keys, string→float casting) and added "
                 "top-of-book columns from the per-market list response.")
    lines.append("")
    lines.append("Targeted to four series only (`KXNBAPTS`, `KXNBAREB`, "
                 "`KXNBAAST`, `KXNBA3PT`) and to three matchups "
                 f"({', '.join(SLATE_MATCHUPS)}). Read-only. "
                 "No NBAgent state modified.")
    lines.append("")

    # === Section 1 — slate market counts ===
    lines.append("## 1. Slate market counts")
    lines.append("")
    lines.append("| Matchup | PTS | REB | AST | 3PM | Total |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    grand_total = 0
    for matchup in SLATE_MATCHUPS:
        row_counts = []
        row_sum = 0
        for series in ["KXNBAPTS", "KXNBAREB", "KXNBAAST", "KXNBA3PT"]:
            n = len(by_matchup.get(matchup, {}).get(series, []))
            row_counts.append(str(n))
            row_sum += n
        grand_total += row_sum
        lines.append(f"| `{matchup}` | "
                     + " | ".join(row_counts)
                     + f" | **{row_sum}** |")
    lines.append(f"| **Total** | | | | | **{grand_total}** |")
    lines.append("")

    # === Section 2 — Per-player tier ladders ===
    lines.append("## 2. Per-player tier ladders (per matchup)")
    lines.append("")
    lines.append(f"**Bold** tiers are floor tiers (bottom {FLOOR_TIER_COUNT} of "
                 "the ladder, where NBAgent's conservative picks live).")
    lines.append("")
    for matchup in SLATE_MATCHUPS:
        lines.append(f"### {matchup}")
        lines.append("")
        players = ladders.get(matchup, {})
        if not players:
            lines.append("_(no markets)_")
            lines.append("")
            continue
        lines.append("| Player | PTS tiers | REB tiers | AST tiers | 3PM tiers |")
        lines.append("|---|---|---|---|---|")
        for player in sorted(players.keys()):
            row = [player]
            for prop in ["PTS", "REB", "AST", "3PM"]:
                node = players[player].get(prop)
                if not node:
                    row.append("—")
                    continue
                tiers = node["tiers"]
                floor = set(node["floor_tiers"])
                rendered = ", ".join(
                    f"**{t}**" if t in floor else str(t) for t in tiers
                )
                row.append(rendered)
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # === Section 3 — FLOOR-TIER LIQUIDITY (the section that matters) ===
    lines.append("## 3. Floor-tier liquidity")
    lines.append("")
    lines.append("Each row is one floor-tier market. **Implied prob** = "
                 "`yes_bid_dollars` (Kalshi binary contracts pay $1 if YES, "
                 "so the YES bid IS the implied probability of the over). "
                 "**Spread** = `yes_ask − yes_bid` (in cents). **YES depth** "
                 "is the total dollar value of YES bids across all orderbook "
                 "levels. **OI** is open interest.")
    lines.append("")

    floor_records = [r for r in flat_records if r.get("is_floor_tier")]
    n_floor = len(floor_records)

    # Liquidity-tier breakdown
    by_class: dict[str, list] = defaultdict(list)
    for r in floor_records:
        by_class[classify_liquidity(r)].append(r)

    n_liquid    = len(by_class["liquid"])
    n_thin      = len(by_class["thin"])
    n_top_only  = len(by_class["top_of_book"])
    n_empty     = len(by_class["empty"])

    lines.append("**Liquidity classification (floor markets only):**")
    lines.append("")
    lines.append(f"- **liquid** (≥$50 YES depth): {n_liquid} ({n_liquid/max(1,n_floor)*100:.1f}%)")
    lines.append(f"- **thin** ($5–$50 YES depth): {n_thin} ({n_thin/max(1,n_floor)*100:.1f}%)")
    lines.append(f"- **top-of-book only** (bid > 0 but no/minimal depth): "
                 f"{n_top_only} ({n_top_only/max(1,n_floor)*100:.1f}%)")
    lines.append(f"- **empty** (no YES bid): {n_empty} ({n_empty/max(1,n_floor)*100:.1f}%)")
    lines.append("")

    lines.append("### Floor markets — full table")
    lines.append("")
    lines.append("| Matchup | Player | Prop | Tier | YES bid | YES ask | "
                 "Implied | Spread | YES depth$ | NO depth$ | last | "
                 "vol_24h | OI | Class |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for r in sorted(
        floor_records,
        key=lambda r: (r["matchup"], r["player"], r["prop_type"], r["tier"])
    ):
        yes_b  = r.get("yes_bid_dollars")
        yes_a  = r.get("yes_ask_dollars")
        no_b   = r.get("no_bid_dollars")
        last   = r.get("last_price_dollars")
        v24    = r.get("volume_24h_fp")
        oi     = r.get("open_interest_fp")
        yes_d  = r.get("yes_total_dollar_depth")
        no_d   = r.get("no_total_dollar_depth")
        spread = (yes_a - yes_b) if (yes_a is not None and yes_b is not None) else None
        implied = yes_b
        cls    = classify_liquidity(r)

        def _fmt_dollars(v):
            return f"${v:.2f}" if isinstance(v, (int, float)) else "—"

        def _fmt_pct(v):
            if v is None: return "—"
            return f"{v*100:.0f}%"

        def _fmt_cents(v):
            if v is None: return "—"
            return f"{v*100:.1f}¢"

        lines.append(
            f"| {r['matchup']} | {r['player']} | {r['prop_type']} | "
            f"{r['tier']} | {_fmt_dollars(yes_b)} | {_fmt_dollars(yes_a)} | "
            f"{_fmt_pct(implied)} | {_fmt_cents(spread)} | "
            f"{_fmt_dollars(yes_d)} | {_fmt_dollars(no_d)} | "
            f"{_fmt_dollars(last)} | "
            f"{(int(v24) if v24 else '—')} | "
            f"{(int(oi)  if oi  else '—')} | {cls} |"
        )
    lines.append("")

    # === Section 4 — Headline tier comparison ===
    lines.append("## 4. Headline-tier liquidity (reference)")
    lines.append("")
    headline_records = [r for r in flat_records if not r.get("is_floor_tier")]
    h_by_class: dict[str, list] = defaultdict(list)
    for r in headline_records:
        h_by_class[classify_liquidity(r)].append(r)
    n_h = len(headline_records)
    lines.append("| Class | n | % |")
    lines.append("|---|---:|---:|")
    for cls in ["liquid", "thin", "top_of_book", "empty"]:
        n_c = len(h_by_class[cls])
        lines.append(f"| {cls} | {n_c} | {n_c/max(1,n_h)*100:.1f}% |")
    lines.append("")

    # === Section 5 — Volume / OI summary ===
    lines.append("## 5. Volume + open-interest summary")
    lines.append("")
    lines.append("Aggregates across all 4 series × 3 matchups (floor + headline).")
    lines.append("")
    total_v24 = sum((r.get("volume_24h_fp") or 0) for r in flat_records)
    total_vol = sum((r.get("volume_fp") or 0)     for r in flat_records)
    total_oi  = sum((r.get("open_interest_fp") or 0) for r in flat_records)
    n_with_v24 = sum(1 for r in flat_records if (r.get("volume_24h_fp") or 0) > 0)
    n_with_oi  = sum(1 for r in flat_records if (r.get("open_interest_fp") or 0) > 0)
    n_total    = len(flat_records)
    lines.append(f"- Total markets: {n_total}")
    lines.append(f"- Markets with non-zero 24h volume: {n_with_v24} "
                 f"({n_with_v24/max(1,n_total)*100:.1f}%)")
    lines.append(f"- Markets with non-zero open interest: {n_with_oi} "
                 f"({n_with_oi/max(1,n_total)*100:.1f}%)")
    lines.append(f"- Sum 24h volume across slate: {total_v24:.0f}")
    lines.append(f"- Sum lifetime volume across slate: {total_vol:.0f}")
    lines.append(f"- Sum open interest across slate: {total_oi:.0f}")
    lines.append("")

    # === Section 6 — Findings ===
    lines.append("## 6. Findings")
    lines.append("")
    lines.append("| Question | Answer |")
    lines.append("|---|---|")
    lines.append(f"| Total slate markets (4 series × 3 matchups) | {grand_total} |")
    lines.append(f"| Distinct players priced | "
                 f"{len({p for m in ladders for p in ladders[m]})} |")
    lines.append(f"| Floor markets total | {n_floor} |")
    lines.append(f"| Floor markets — liquid | {n_liquid} ({n_liquid/max(1,n_floor)*100:.1f}%) |")
    lines.append(f"| Floor markets — thin | {n_thin} ({n_thin/max(1,n_floor)*100:.1f}%) |")
    lines.append(f"| Floor markets — top-of-book only | {n_top_only} ({n_top_only/max(1,n_floor)*100:.1f}%) |")
    lines.append(f"| Floor markets — empty | {n_empty} ({n_empty/max(1,n_floor)*100:.1f}%) |")
    lines.append(f"| Floor markets — any non-empty (YES bid > 0) | "
                 f"{n_floor - n_empty} ({(n_floor-n_empty)/max(1,n_floor)*100:.1f}%) |")
    lines.append("")

    # === Section 7 — Raw artifacts ===
    lines.append("## 7. Raw artifacts")
    lines.append("")
    lines.append("All in `data/kalshi_reprobe_v2/`:")
    lines.append("- `01_markets_<SERIES>.json` — raw markets per series")
    lines.append("- `02_slate_markets.json` — filtered to slate matchups")
    lines.append("- `03_tier_ladders.json` — per-player tier ladders")
    lines.append("- `04_orderbook_records.json` — flat orderbook list "
                 "(corrected parse)")
    lines.append("- `05_ladders_with_orderbook.json` — full nested view")
    lines.append("")
    lines.append("---")
    lines.append("*Re-probe v2 is read-only and one-off. Re-running overwrites "
                 "all artifacts in `data/kalshi_reprobe_v2/`.*")

    report_path = OUT / "REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ── main() ────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[reprobe-v2] Starting Kalshi NBA re-probe v2 at {TIMESTAMP}")
    print(f"[reprobe-v2] Series: {list(PROP_SERIES.keys())}")
    print(f"[reprobe-v2] Slate: {SLATE_DATE_TICKER} × {SLATE_MATCHUPS}")
    print(f"[reprobe-v2] Output dir: {OUT}")

    by_matchup = step1_fetch_slate_markets()
    grand_total = sum(
        len(markets)
        for matchup_data in by_matchup.values()
        for markets in matchup_data.values()
    )
    if grand_total == 0:
        print(f"\n[reprobe-v2] WARNING: zero slate markets matched. "
              f"Possible causes: (a) slate not yet listed, "
              f"(b) ticker convention drift, "
              f"(c) date encoding mismatch (expected {SLATE_DATE_TICKER}). "
              f"Continuing with empty-state report.")

    ladders = step3_build_tier_ladders(by_matchup)
    result  = step4_orderbook_depth(ladders)
    report  = step5_write_report(by_matchup, ladders, result["flat"])
    print(f"\n[reprobe-v2] Done. Report: {report}")
    print(f"[reprobe-v2] Raw artifacts: {OUT}")


if __name__ == "__main__":
    main()
