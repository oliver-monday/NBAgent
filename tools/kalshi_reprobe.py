#!/usr/bin/env python3
"""
NBAgent — Kalshi NBA Prop Re-Probe (one-off, May 1 slate)

Targeted follow-up to tools/kalshi_probe.py. Hits ONLY the four NBA
player-prop series (KXNBAPTS/REB/AST/3PT), filters events to tomorrow's
three matchups (DET-ORL, CLE-TOR, LAL-HOU), and probes orderbook
liquidity at every market — with explicit floor-tier separation since
that's where NBAgent's picks actually live.

Usage:
    python tools/kalshi_reprobe.py

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
OUT  = DATA / "kalshi_reprobe"
OUT.mkdir(parents=True, exist_ok=True)

PT = ZoneInfo("America/Los_Angeles")
TIMESTAMP = dt.datetime.now(PT).strftime("%Y-%m-%dT%H:%M:%S%z")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT  = "NBAgent-Reprobe/1.0 (one-off discovery; contact: nbagent)"
THROTTLE_SEC = 0.20
PAGE_LIMIT   = 200
MAX_PAGES    = 10

# ── HARD-CODED SCOPE ──────────────────────────────────────────────────
# The four NBA player-prop series we care about, mapped to NBAgent props.
PROP_SERIES: dict[str, str] = {
    "KXNBAPTS": "PTS",
    "KXNBAREB": "REB",
    "KXNBAAST": "AST",
    "KXNBA3PT": "3PM",
}

# Tomorrow's slate — the three NBA matchups for May 1, 2026.
# Date format matches Kalshi ticker convention (YY + MMM upper + DD).
SLATE_DATE_TICKER = "26MAY01"
SLATE_MATCHUPS = [
    "DETORL",   # DET @ ORL (East R1 G6)
    "CLETOR",   # CLE @ TOR (East R1 G6)
    "LALHOU",   # LAL @ HOU (West R1 G6)
]

# Floor-tier definition: bottom 2 tiers of each (player, prop) ladder
# are the "floor" — that's where NBAgent's conservative picks live.
# Higher tiers in the ladder are "headline" markets we don't price.
FLOOR_TIER_COUNT = 2


# ── HTTP + pagination helpers ─────────────────────────────────────────

def fetch(path: str, params: dict | None = None) -> dict | None:
    """GET against the Kalshi API. Returns parsed JSON or None on failure."""
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
            print(f"[reprobe] WARN: HTTP {status} on {url}")
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[reprobe] WARN: JSON parse failed on {url}: {e}")
            return None
    except HTTPError as e:
        print(f"[reprobe] WARN: HTTP {e.code} on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except URLError as e:
        print(f"[reprobe] WARN: network error on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except Exception as e:
        print(f"[reprobe] WARN: unexpected error on {url}: {e}")
        time.sleep(THROTTLE_SEC)
        return None


def fetch_paginated(path: str, results_key: str,
                    params: dict | None = None) -> list:
    """Walks cursor-paginated results. Stops at MAX_PAGES."""
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
        print(f"[reprobe] NOTE: hit MAX_PAGES on {path} — items: {len(items)}")
    return items


# ── Step 1: fetch + filter markets per series × matchup ──────────────

def step1_fetch_slate_markets() -> dict:
    """
    For each of the four target series, fetch all markets (any status),
    filter to events matching the slate date + one of the three matchups.

    Returns a nested dict keyed by [matchup][series] = list of markets.
    Also dumps raw per-series fetches to disk for offline inspection.
    """
    print(f"\n=== Step 1: Fetch slate markets ({SLATE_DATE_TICKER}) ===")
    by_matchup: dict[str, dict[str, list]] = {
        m: {s: [] for s in PROP_SERIES} for m in SLATE_MATCHUPS
    }

    # Pre-build the expected event_ticker prefix patterns so filter is exact.
    expected_event_prefixes = {
        s: {m: f"{s}-{SLATE_DATE_TICKER}{m}" for m in SLATE_MATCHUPS}
        for s in PROP_SERIES
    }

    for series_ticker in PROP_SERIES:
        print(f"\n[reprobe] Series {series_ticker} — fetching markets...")
        # First try with status=open; fall back to no-status if empty.
        markets = fetch_paginated("/markets", "markets",
                                  params={"series_ticker": series_ticker,
                                          "status": "open"})
        if not markets:
            markets = fetch_paginated("/markets", "markets",
                                      params={"series_ticker": series_ticker})
        print(f"  total markets fetched: {len(markets)}")

        # Dump raw for this series
        (OUT / f"01_markets_{series_ticker}.json").write_text(
            json.dumps(markets, indent=2), encoding="utf-8")

        # Local filter — keep only tomorrow's three matchups
        for m in markets:
            evt = (m.get("event_ticker") or "")
            for matchup in SLATE_MATCHUPS:
                if evt == expected_event_prefixes[series_ticker][matchup]:
                    by_matchup[matchup][series_ticker].append(m)
                    break

        # Per-series filtering summary
        per_matchup_counts = {
            matchup: len(by_matchup[matchup][series_ticker])
            for matchup in SLATE_MATCHUPS
        }
        print(f"  filtered to slate: {per_matchup_counts} "
              f"(total: {sum(per_matchup_counts.values())})")

    # Dump structured slate-only result
    (OUT / "02_slate_markets.json").write_text(
        json.dumps(by_matchup, indent=2), encoding="utf-8")
    return by_matchup


# ── Step 2: parse player + tier from each market ticker ──────────────

TICKER_TAIL_RE = re.compile(
    r"^(?P<series>KX[A-Z0-9]+)-"
    r"(?P<event_part>[0-9]{2}[A-Z]{3}[0-9]{2}[A-Z]{6})-"
    r"(?P<player_tag>[A-Z]+[0-9]+)-"
    r"(?P<tier>[0-9]+)$"
)

TITLE_RE = re.compile(r"^(?P<player>.+?):\s*(?P<tier>[0-9]+)\+\s+(?P<unit>\w+)")


def parse_market(market: dict, series_to_prop: dict[str, str]) -> dict:
    """
    Parse a Kalshi market into a structured row.
    Returns dict with keys: ok, ticker, prop_type, player, tier,
        event_ticker, status, title, yes_bid_dollars, yes_ask_dollars,
        no_bid_dollars, no_ask_dollars, last_price_dollars,
        volume_24h_fp, liquidity_dollars, parse_warnings (list).
    `ok` is True only if all parses succeeded.
    """
    out = {
        "ok": True,
        "ticker":              market.get("ticker"),
        "event_ticker":        market.get("event_ticker"),
        "status":              market.get("status"),
        "title":               market.get("title"),
        "yes_sub_title":       market.get("yes_sub_title"),
        "yes_bid_dollars":     market.get("yes_bid_dollars"),
        "yes_ask_dollars":     market.get("yes_ask_dollars"),
        "no_bid_dollars":      market.get("no_bid_dollars"),
        "no_ask_dollars":      market.get("no_ask_dollars"),
        "last_price_dollars":  market.get("last_price_dollars"),
        "volume_24h_fp":       market.get("volume_24h_fp"),
        "volume_fp":           market.get("volume_fp"),
        "liquidity_dollars":   market.get("liquidity_dollars"),
        "open_interest_fp":    market.get("open_interest_fp"),
        "parse_warnings":      [],
    }

    # Parse ticker → series, player_tag, tier
    tk = market.get("ticker") or ""
    tm = TICKER_TAIL_RE.match(tk)
    if tm:
        out["series_ticker"] = tm.group("series")
        out["player_tag"]    = tm.group("player_tag")
        out["tier_from_ticker"] = int(tm.group("tier"))
    else:
        out["series_ticker"] = None
        out["player_tag"]    = None
        out["tier_from_ticker"] = None
        out["parse_warnings"].append(f"ticker_regex_no_match: {tk}")

    # Parse title → player display name + tier
    title = market.get("title") or ""
    titlem = TITLE_RE.match(title)
    if titlem:
        out["player"] = titlem.group("player").strip()
        out["tier_from_title"] = int(titlem.group("tier"))
    else:
        out["player"] = None
        out["tier_from_title"] = None
        out["parse_warnings"].append(f"title_regex_no_match: {title}")

    # Cross-check tier consistency
    tt = out.get("tier_from_ticker")
    tn = out.get("tier_from_title")
    if tt is not None and tn is not None and tt != tn:
        out["parse_warnings"].append(
            f"tier_mismatch: ticker={tt} title={tn}")
    out["tier"] = tn if tn is not None else tt

    # Map series → NBAgent prop type
    out["prop_type"] = series_to_prop.get(out.get("series_ticker") or "", None)
    if out["prop_type"] is None:
        out["parse_warnings"].append(
            f"unknown_series: {out.get('series_ticker')}")

    if out["parse_warnings"]:
        out["ok"] = False
    return out


# ── Step 3: build per-player tier ladders + identify floor tiers ─────

def step3_build_tier_ladders(by_matchup: dict) -> dict:
    """
    Build per-(matchup, player, prop) tier ladder. Returns a nested dict.
    """
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

    # Sort tiers + identify floor / headline
    for matchup, players in ladders.items():
        for player, props in players.items():
            for prop, node in props.items():
                node["tiers"] = sorted(node["tiers"])
                node["floor_tiers"]    = node["tiers"][:FLOOR_TIER_COUNT]
                node["headline_tiers"] = node["tiers"][FLOOR_TIER_COUNT:]

    print(f"[reprobe] Parsed {parsed_total} markets; "
          f"{parse_failures} parse failures.")

    (OUT / "03_tier_ladders.json").write_text(
        json.dumps(ladders, indent=2), encoding="utf-8")
    return ladders


# ── Step 4: orderbook depth probe across ALL markets ─────────────────

def step4_orderbook_depth(ladders: dict) -> dict:
    """
    Fetch orderbook for every market in the ladder. Annotate each market
    with depth metrics. Returns dict {ladders, flat}.
    """
    print(f"\n=== Step 4: Orderbook depth — every slate market ===")
    flat_records: list[dict] = []
    n_total = 0
    n_with_yes_levels = 0

    # Walk in sorted, deterministic order so the run is reproducible
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
                    ob = fetch(f"/markets/{mt}/orderbook")
                    ob_root = (ob or {}).get("orderbook") or {}
                    yes_bids = ob_root.get("yes") or []
                    no_bids  = ob_root.get("no")  or []
                    # NOTE: Kalshi may use either 'yes'/'no' arrays of [price, qty]
                    # in cents, or 'yes_dollars'/'no_dollars' arrays of [price, qty]
                    # in dollars. Capture both shapes defensively.
                    if not yes_bids and "yes_dollars" in ob_root:
                        yes_bids = ob_root.get("yes_dollars") or []
                    if not no_bids and "no_dollars" in ob_root:
                        no_bids = ob_root.get("no_dollars") or []
                    yes_total_qty = sum(
                        (b[1] for b in yes_bids
                         if isinstance(b, list) and len(b) >= 2),
                        0,
                    )
                    no_total_qty = sum(
                        (b[1] for b in no_bids
                         if isinstance(b, list) and len(b) >= 2),
                        0,
                    )
                    yes_top = yes_bids[-1] if yes_bids else None
                    no_top  = no_bids[-1]  if no_bids  else None

                    is_floor = tier in node["floor_tiers"]
                    market["orderbook"] = {
                        "yes_levels":    len(yes_bids),
                        "no_levels":     len(no_bids),
                        "yes_total_qty": yes_total_qty,
                        "no_total_qty":  no_total_qty,
                        "yes_top_bid":   yes_top,
                        "no_top_bid":    no_top,
                    }
                    if len(yes_bids) > 0:
                        n_with_yes_levels += 1

                    flat_records.append({
                        "matchup":         matchup,
                        "player":          player,
                        "prop_type":       prop,
                        "tier":            tier,
                        "is_floor_tier":   is_floor,
                        "ticker":          mt,
                        "status":          market.get("status"),
                        "title":           market.get("title"),
                        "yes_levels":      len(yes_bids),
                        "no_levels":       len(no_bids),
                        "yes_total_qty":   yes_total_qty,
                        "no_total_qty":    no_total_qty,
                        "yes_top_bid":     yes_top,
                        "no_top_bid":      no_top,
                        "yes_bid_dollars": market.get("yes_bid_dollars"),
                        "yes_ask_dollars": market.get("yes_ask_dollars"),
                        "no_bid_dollars":  market.get("no_bid_dollars"),
                        "no_ask_dollars":  market.get("no_ask_dollars"),
                        "last_price_dollars": market.get("last_price_dollars"),
                        "volume_24h_fp":   market.get("volume_24h_fp"),
                        "open_interest_fp": market.get("open_interest_fp"),
                    })

    print(f"[reprobe] Fetched {n_total} orderbooks; "
          f"{n_with_yes_levels} with non-empty YES side "
          f"({(n_with_yes_levels / max(1, n_total) * 100):.1f}%).")

    (OUT / "04_orderbook_records.json").write_text(
        json.dumps(flat_records, indent=2), encoding="utf-8")
    (OUT / "05_ladders_with_orderbook.json").write_text(
        json.dumps(ladders, indent=2), encoding="utf-8")
    return {"ladders": ladders, "flat": flat_records}


# ── Step 5: write the focused report ─────────────────────────────────

def step5_write_report(by_matchup: dict, ladders: dict,
                        flat_records: list) -> Path:
    lines: list[str] = []
    lines.append(f"# Kalshi NBA Re-Probe — May 1 Slate")
    lines.append("")
    lines.append(f"Generated by `tools/kalshi_reprobe.py` at {TIMESTAMP}.")
    lines.append("")
    lines.append("Targeted to four series only (`KXNBAPTS`, `KXNBAREB`, "
                 "`KXNBAAST`, `KXNBA3PT`) and to three matchups "
                 f"({', '.join(SLATE_MATCHUPS)}). Read-only. "
                 "No NBAgent state modified.")
    lines.append("")

    # === Section 1 — Slate market counts ===
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

    # === Section 2 — Per-player tier ladder (per matchup) ===
    lines.append("## 2. Per-player tier ladders (per matchup)")
    lines.append("")
    lines.append("Each row is one player's full tier ladder per prop. "
                 f"**Bold** tiers are floor tiers (bottom {FLOOR_TIER_COUNT} "
                 "of the ladder, where NBAgent's conservative picks live).")
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

    # === Section 3 — Orderbook liquidity, FLOOR TIERS ONLY ===
    lines.append("## 3. Orderbook liquidity — FLOOR TIERS ONLY")
    lines.append("")
    lines.append("This is the section that matters. NBAgent picks "
                 "structurally conservative tiers; liquidity at headline "
                 "tiers (e.g. LeBron 5+ threes) is irrelevant for our "
                 "use case. Only floor-tier markets shown below.")
    lines.append("")
    floor_records = [r for r in flat_records if r.get("is_floor_tier")]
    n_floor = len(floor_records)
    n_floor_yes = sum(1 for r in floor_records if r["yes_levels"] > 0)
    n_floor_no  = sum(1 for r in floor_records if r["no_levels"] > 0)
    n_floor_either = sum(
        1 for r in floor_records
        if r["yes_levels"] > 0 or r["no_levels"] > 0
    )
    pct_yes  = n_floor_yes  / max(1, n_floor) * 100
    pct_no   = n_floor_no   / max(1, n_floor) * 100
    pct_eith = n_floor_either / max(1, n_floor) * 100
    lines.append(f"**Floor markets total:** {n_floor}")
    lines.append("")
    lines.append(f"- With ≥1 YES bid level: {n_floor_yes} ({pct_yes:.1f}%)")
    lines.append(f"- With ≥1 NO bid level:  {n_floor_no} ({pct_no:.1f}%)")
    lines.append(f"- With either side bid:  {n_floor_either} ({pct_eith:.1f}%)")
    lines.append("")
    lines.append("### Floor markets WITH any orderbook depth")
    lines.append("")
    bid_having = [
        r for r in floor_records
        if r["yes_levels"] > 0 or r["no_levels"] > 0
    ]
    if bid_having:
        lines.append("| Matchup | Player | Prop | Tier | YES lvls | NO lvls "
                     "| YES qty | NO qty | YES bid | NO bid | last | OI |")
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for r in bid_having:
            yes_b = r["yes_bid_dollars"]
            no_b  = r["no_bid_dollars"]
            last  = r["last_price_dollars"]
            oi    = r["open_interest_fp"]
            lines.append(
                f"| {r['matchup']} | {r['player']} | {r['prop_type']} | "
                f"{r['tier']} | {r['yes_levels']} | {r['no_levels']} | "
                f"{r['yes_total_qty']} | {r['no_total_qty']} | "
                f"{yes_b if yes_b is not None else '—'} | "
                f"{no_b  if no_b  is not None else '—'} | "
                f"{last  if last  is not None else '—'} | "
                f"{oi    if oi    is not None else '—'} |"
            )
    else:
        lines.append("_(No floor-tier markets had any orderbook depth at "
                     "the time of this probe.)_")
    lines.append("")

    # === Section 4 — Headline-tier liquidity (for reference only) ===
    lines.append("## 4. Headline-tier liquidity (reference only)")
    lines.append("")
    lines.append("Higher tiers in each player's ladder. Included for "
                 "comparison — these are NOT NBAgent's pricing surface.")
    lines.append("")
    headline_records = [r for r in flat_records if not r.get("is_floor_tier")]
    n_head = len(headline_records)
    n_head_either = sum(
        1 for r in headline_records
        if r["yes_levels"] > 0 or r["no_levels"] > 0
    )
    pct_head = n_head_either / max(1, n_head) * 100
    lines.append(f"**Headline markets total:** {n_head}")
    lines.append(f"- With either side bid: {n_head_either} ({pct_head:.1f}%)")
    lines.append("")

    # === Section 5 — Player coverage vs NBAgent whitelist (informational) ===
    lines.append("## 5. Players observed (cross-reference manually with "
                 "NBAgent whitelist)")
    lines.append("")
    all_players: set[str] = set()
    for matchup in ladders:
        for p in ladders[matchup]:
            all_players.add(p)
    lines.append(f"**Distinct players priced across slate:** {len(all_players)}")
    lines.append("")
    by_matchup_players: dict[str, set] = defaultdict(set)
    for matchup, players in ladders.items():
        for p in players:
            by_matchup_players[matchup].add(p)
    for matchup in SLATE_MATCHUPS:
        ps = sorted(by_matchup_players.get(matchup, set()))
        if ps:
            lines.append(f"- **{matchup}** ({len(ps)} players): " + ", ".join(ps))
        else:
            lines.append(f"- **{matchup}**: _(none)_")
    lines.append("")

    # === Section 6 — Findings ===
    lines.append("## 6. Findings")
    lines.append("")
    lines.append("| Question | Answer |")
    lines.append("|---|---|")
    lines.append(f"| Total NBA player-prop markets across the 3-game slate "
                 f"(4 series × 3 matchups) | **{grand_total}** |")
    lines.append(f"| Distinct players priced | **{len(all_players)}** |")
    lines.append(f"| Floor-tier markets (bottom-{FLOOR_TIER_COUNT} per "
                 f"player×prop) | **{n_floor}** |")
    lines.append(f"| Floor-tier markets with non-empty orderbook (either side) "
                 f"| **{n_floor_either} ({pct_eith:.1f}%)** |")
    lines.append(f"| Headline-tier markets with non-empty orderbook "
                 f"| **{n_head_either} of {n_head} ({pct_head:.1f}%)** |")
    lines.append("")
    lines.append("Liquidity verdict (compare floor% vs headline%): if floor "
                 "% materially exceeds headline %, that supports the "
                 "hypothesis that conservative-tier markets see real flow. "
                 "If floor % matches or undershoots headline %, the liquidity "
                 "story across all NBA props is uniformly thin and Kalshi "
                 "implied probabilities are unreliable as a second source "
                 "at present.")
    lines.append("")

    # === Section 7 — Raw artifacts ===
    lines.append("## 7. Raw artifacts")
    lines.append("")
    lines.append("All in `data/kalshi_reprobe/`:")
    lines.append("- `01_markets_<SERIES>.json` — raw markets per series")
    lines.append("- `02_slate_markets.json` — filtered to slate matchups")
    lines.append("- `03_tier_ladders.json` — per-player tier ladders")
    lines.append("- `04_orderbook_records.json` — flat orderbook list")
    lines.append("- `05_ladders_with_orderbook.json` — full nested view")
    lines.append("")
    lines.append("---")
    lines.append("*Re-probe is read-only and one-off. Re-running overwrites "
                 "all artifacts in `data/kalshi_reprobe/`.*")

    report_path = OUT / "REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ── main() ────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[reprobe] Starting Kalshi NBA re-probe at {TIMESTAMP}")
    print(f"[reprobe] Series: {list(PROP_SERIES.keys())}")
    print(f"[reprobe] Slate: {SLATE_DATE_TICKER} × {SLATE_MATCHUPS}")
    print(f"[reprobe] Output dir: {OUT}")

    by_matchup = step1_fetch_slate_markets()

    # Sanity check — if every (series × matchup) returned zero markets,
    # something is wrong upstream (Kalshi outage, ticker convention drift,
    # or the slate hasn't been listed yet). Log loudly but continue —
    # the empty-state report still has signal.
    grand_total = sum(
        len(markets)
        for matchup_data in by_matchup.values()
        for markets in matchup_data.values()
    )
    if grand_total == 0:
        print(f"\n[reprobe] WARNING: zero slate markets matched. Possible "
              f"causes: (a) slate hasn't been listed by Kalshi yet, "
              f"(b) ticker convention has changed since 2026-04-30, "
              f"(c) date encoding mismatch (expected {SLATE_DATE_TICKER}). "
              f"Continuing with empty-state report.")

    ladders = step3_build_tier_ladders(by_matchup)
    result  = step4_orderbook_depth(ladders)
    report  = step5_write_report(by_matchup, ladders, result["flat"])

    print(f"\n[reprobe] Done. Report: {report}")
    print(f"[reprobe] Raw artifacts: {OUT}")


if __name__ == "__main__":
    main()
