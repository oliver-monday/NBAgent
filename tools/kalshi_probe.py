#!/usr/bin/env python3
"""
NBAgent — Kalshi NBA Prop Market Probe (one-off discovery)

Probes Kalshi's public market-data API to enumerate available NBA player
prop markets. Read-only. No authentication. No mutations to NBAgent state.
Results written to data/kalshi_probe/ for offline review.

Usage:
    python tools/kalshi_probe.py

No flags. Idempotent — re-runs overwrite previous probe artifacts in
data/kalshi_probe/. Safe to run repeatedly. Polite throttling between
requests (200ms default sleep).
"""

from __future__ import annotations

import json
import time
import datetime as dt
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT  = DATA / "kalshi_probe"
OUT.mkdir(parents=True, exist_ok=True)

PT = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(PT).strftime("%Y-%m-%d")
TIMESTAMP = dt.datetime.now(PT).strftime("%Y-%m-%dT%H:%M:%S%z")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
USER_AGENT  = "NBAgent-Probe/1.0 (one-off discovery; contact: nbagent)"
THROTTLE_SEC = 0.20      # polite sleep between requests
PAGE_LIMIT   = 200       # per-page cap on list endpoints
MAX_PAGES    = 10        # safety ceiling for any paginated walk
ORDERBOOK_SAMPLE_N = 5   # how many markets to sample orderbooks for


# ── HTTP helper ───────────────────────────────────────────────────────

def fetch(path: str, params: dict | None = None) -> dict | None:
    """
    GET against the Kalshi API. Returns parsed JSON dict, or None on
    any failure (HTTP error, network error, JSON parse error). Logs
    failures with status / reason. Polite throttle after each call.
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
            print(f"[probe] WARN: {status} on {url}")
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[probe] WARN: JSON parse failed on {url}: {e}")
            return None
    except HTTPError as e:
        print(f"[probe] WARN: HTTP {e.code} on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except URLError as e:
        print(f"[probe] WARN: network error on {url}: {e.reason}")
        time.sleep(THROTTLE_SEC)
        return None
    except Exception as e:
        print(f"[probe] WARN: unexpected error on {url}: {e}")
        time.sleep(THROTTLE_SEC)
        return None


# ── Pagination helper ─────────────────────────────────────────────────

def fetch_paginated(path: str, results_key: str,
                    params: dict | None = None) -> list:
    """
    Walks cursor-paginated results. Returns flat list of items. Stops at
    MAX_PAGES safety ceiling.
    """
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
        print(f"[probe] NOTE: hit MAX_PAGES={MAX_PAGES} on {path} — "
              f"total items so far: {len(items)}")
    return items


# ── Step 1: enumerate Sports series ───────────────────────────────────

def step1_find_series() -> list[dict]:
    """
    List all Kalshi series in the Sports category. Filter heuristically
    for NBA / basketball / player-prop matches. Print + dump raw to disk.
    """
    print(f"\n=== Step 1: Sports series enumeration ===")
    all_sports = fetch_paginated("/series", "series",
                                 params={"category": "Sports"})
    print(f"[probe] Total Sports series returned: {len(all_sports)}")

    # Dump raw for offline review
    (OUT / "01_sports_series_raw.json").write_text(
        json.dumps(all_sports, indent=2), encoding="utf-8")

    # Heuristic filter — case-insensitive substring match on title + ticker
    nba_keywords = ["nba", "basketball", "points", "rebound",
                    "assist", "three-point", "3pm", "3pt"]
    candidates = []
    for s in all_sports:
        haystack = " ".join([
            (s.get("ticker") or ""),
            (s.get("title") or ""),
            (s.get("subtitle") or ""),
            (s.get("category") or ""),
            (s.get("description") or ""),
        ]).lower()
        if any(kw in haystack for kw in nba_keywords):
            candidates.append(s)

    print(f"[probe] NBA / basketball / prop-keyword series: {len(candidates)}")
    for s in candidates:
        ticker = s.get("ticker", "")
        title  = s.get("title", "")
        freq   = s.get("frequency", "")
        print(f"  {ticker:30}  {title[:70]}  [{freq}]")

    (OUT / "02_nba_candidate_series.json").write_text(
        json.dumps(candidates, indent=2), encoding="utf-8")
    return candidates


# ── Step 2: enumerate events + markets per candidate series ──────────

def step2_enumerate_markets(candidates: list[dict]) -> dict:
    """
    For each NBA-candidate series, list events + markets. Build
    structured summary. Dump raw to disk.
    """
    print(f"\n=== Step 2: Events + markets per candidate series ===")
    summary: dict = {}
    for s in candidates:
        ticker = s.get("ticker", "")
        if not ticker:
            continue
        print(f"\n[probe] Probing series: {ticker}")

        # Events under this series
        events = fetch_paginated("/events", "events",
                                 params={"series_ticker": ticker,
                                         "status": "open"})
        print(f"  events (open): {len(events)}")

        # Markets under this series — also try with status=open then
        # without status filter if the first returns zero (some series
        # use different conventions for "active")
        markets = fetch_paginated("/markets", "markets",
                                  params={"series_ticker": ticker,
                                          "status": "open"})
        if not markets:
            markets = fetch_paginated("/markets", "markets",
                                      params={"series_ticker": ticker})
        print(f"  markets (any status): {len(markets)}")

        # Surface key shape signals on the first market
        sample_market = markets[0] if markets else None

        # Per-player x prop x tier coverage analysis
        # (heuristic — title parsing; the structured key for player /
        # prop / threshold may differ per series, so this is best-effort)
        players_seen: set[str] = set()
        prop_types_seen: dict[str, int] = {}
        thresholds_per_player_prop: dict[tuple[str, str], list] = {}
        for m in markets:
            title = (m.get("title") or "")
            sub   = (m.get("subtitle") or "")
            yes_sub = (m.get("yes_sub_title") or "")
            full = f"{title} | {sub} | {yes_sub}"
            # Heuristic prop type tagging
            full_l = full.lower()
            if "point" in full_l or " pts" in full_l or full_l.endswith("pts"):
                ptype = "PTS"
            elif "rebound" in full_l or " reb" in full_l:
                ptype = "REB"
            elif "assist" in full_l or " ast" in full_l:
                ptype = "AST"
            elif "three" in full_l or "3-point" in full_l or "3pt" in full_l or "3pm" in full_l:
                ptype = "3PM"
            else:
                ptype = "OTHER"
            prop_types_seen[ptype] = prop_types_seen.get(ptype, 0) + 1

        summary[ticker] = {
            "title":        s.get("title", ""),
            "n_events":     len(events),
            "n_markets":    len(markets),
            "prop_types_seen": prop_types_seen,
            "sample_market_keys": (
                sorted(sample_market.keys()) if sample_market else []
            ),
            "sample_market_excerpt": _sample_market_excerpt(sample_market),
        }

        # Dump raw for this series
        safe_t = ticker.replace("/", "_")
        (OUT / f"03_events_{safe_t}.json").write_text(
            json.dumps(events, indent=2), encoding="utf-8")
        (OUT / f"04_markets_{safe_t}.json").write_text(
            json.dumps(markets, indent=2), encoding="utf-8")

    (OUT / "05_series_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _sample_market_excerpt(m: dict | None) -> dict:
    """Pull the most decision-relevant fields from one market for the
    summary report."""
    if not m: return {}
    keys_of_interest = [
        "ticker", "event_ticker", "title", "subtitle", "yes_sub_title",
        "status", "open_time", "close_time", "expiration_time",
        "yes_bid", "yes_ask", "no_bid", "no_ask", "last_price",
        "volume", "volume_24h", "liquidity", "open_interest",
        "rules_primary", "rules_secondary",
    ]
    return {k: m.get(k) for k in keys_of_interest if k in m}


# ── Step 3: orderbook depth sample ────────────────────────────────────

def step3_orderbook_sample(summary: dict) -> list[dict]:
    """
    Fetch orderbooks for a small sample of markets across the candidate
    series. Compute basic depth metrics so we can judge liquidity.
    """
    print(f"\n=== Step 3: Orderbook depth sample ===")
    samples: list[dict] = []
    sampled_count = 0

    # Walk dumped markets per series, take first N markets per series
    for ticker, info in summary.items():
        if sampled_count >= ORDERBOOK_SAMPLE_N:
            break
        safe_t = ticker.replace("/", "_")
        path = OUT / f"04_markets_{safe_t}.json"
        if not path.exists():
            continue
        try:
            markets = json.loads(path.read_text())
        except Exception:
            continue
        for m in markets[:2]:  # Up to 2 per series
            if sampled_count >= ORDERBOOK_SAMPLE_N:
                break
            mt = m.get("ticker")
            if not mt:
                continue
            ob = fetch(f"/markets/{mt}/orderbook")
            if not ob:
                continue
            ob_root = ob.get("orderbook", {}) or {}
            yes_bids = ob_root.get("yes") or []
            no_bids  = ob_root.get("no")  or []

            yes_total_qty = sum((b[1] for b in yes_bids if isinstance(b, list) and len(b) >= 2), 0)
            no_total_qty  = sum((b[1] for b in no_bids  if isinstance(b, list) and len(b) >= 2), 0)
            yes_top = yes_bids[-1] if yes_bids else None
            no_top  = no_bids[-1]  if no_bids  else None

            sample = {
                "series":          ticker,
                "market_ticker":   mt,
                "market_title":    m.get("title") or m.get("subtitle"),
                "yes_levels":      len(yes_bids),
                "no_levels":       len(no_bids),
                "yes_total_qty":   yes_total_qty,
                "no_total_qty":    no_total_qty,
                "yes_top_bid":     yes_top,
                "no_top_bid":      no_top,
                "last_price":      m.get("last_price"),
                "volume":          m.get("volume"),
                "volume_24h":      m.get("volume_24h"),
                "liquidity_field": m.get("liquidity"),
            }
            samples.append(sample)
            sampled_count += 1
            print(f"  [{sampled_count}] {mt}: yes_levels={len(yes_bids)} "
                  f"no_levels={len(no_bids)} yes_qty={yes_total_qty} "
                  f"no_qty={no_total_qty} last={m.get('last_price')}")

    (OUT / "06_orderbook_samples.json").write_text(
        json.dumps(samples, indent=2), encoding="utf-8")
    return samples


# ── Step 4: deep-dive on one market ───────────────────────────────────

def step4_deep_dive(summary: dict) -> dict | None:
    """
    Pick the most-active candidate market and fetch all available detail
    on it: event detail, market detail, orderbook. Dump everything.
    """
    print(f"\n=== Step 4: Deep dive on one market ===")

    best = None
    best_volume = -1
    for ticker in summary.keys():
        safe_t = ticker.replace("/", "_")
        path = OUT / f"04_markets_{safe_t}.json"
        if not path.exists(): continue
        try:
            markets = json.loads(path.read_text())
        except Exception:
            continue
        for m in markets:
            v = m.get("volume") or m.get("volume_24h") or 0
            try: v = int(v)
            except (TypeError, ValueError): v = 0
            if v > best_volume:
                best_volume = v
                best = m

    if not best:
        print("[probe] No market available for deep-dive")
        return None

    mt = best.get("ticker")
    ev = best.get("event_ticker")
    print(f"[probe] Deep-diving market {mt} (event {ev}, volume {best_volume})")

    market_detail = fetch(f"/markets/{mt}")
    event_detail  = fetch(f"/events/{ev}") if ev else None
    orderbook     = fetch(f"/markets/{mt}/orderbook")

    bundle = {
        "summary_volume":  best_volume,
        "list_excerpt":    _sample_market_excerpt(best),
        "market_detail":   market_detail,
        "event_detail":    event_detail,
        "orderbook":       orderbook,
    }
    (OUT / "07_deep_dive.json").write_text(
        json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle


# ── Step 5: write human-readable Markdown report ──────────────────────

def step5_write_report(candidates: list[dict],
                        summary: dict,
                        ob_samples: list[dict],
                        deep: dict | None) -> Path:
    """
    Write a human-readable Markdown summary at
    data/kalshi_probe/REPORT.md. Answers the seven probe questions
    based on data observed; flags unknowns where data is missing.
    """
    lines: list[str] = []
    lines.append(f"# Kalshi NBA Prop Market Probe — {TODAY_STR}")
    lines.append("")
    lines.append(f"Generated by `tools/kalshi_probe.py` at {TIMESTAMP}.")
    lines.append("All requests unauthenticated, read-only. No NBAgent state modified.")
    lines.append("")
    lines.append("## 1. NBA-prop series tickers found")
    lines.append("")
    if candidates:
        lines.append("| Ticker | Title | Frequency |")
        lines.append("|---|---|---|")
        for s in candidates:
            lines.append(f"| `{s.get('ticker','')}` | {s.get('title','')} | "
                         f"{s.get('frequency','')} |")
    else:
        lines.append("**None found.** No Sports series matched NBA / "
                     "basketball / player-prop keywords. The probe may "
                     "need a wider keyword set, or the series may live "
                     "under a non-Sports category.")
    lines.append("")
    lines.append("## 2. Prop categories observed")
    lines.append("")
    lines.append("Per-series count of markets categorized by heuristic "
                 "title-parsing into PTS / REB / AST / 3PM / OTHER:")
    lines.append("")
    if summary:
        all_props = set()
        for info in summary.values():
            all_props.update(info.get("prop_types_seen", {}).keys())
        prop_order = ["PTS", "REB", "AST", "3PM", "OTHER"]
        prop_order += sorted(p for p in all_props if p not in prop_order)
        header = "| Series | n_events | n_markets | " + " | ".join(prop_order) + " |"
        sep    = "|---|---:|---:|" + "|".join("---:" for _ in prop_order) + "|"
        lines.append(header)
        lines.append(sep)
        for ticker, info in summary.items():
            counts = info.get("prop_types_seen", {})
            row = (f"| `{ticker}` | {info.get('n_events',0)} | "
                   f"{info.get('n_markets',0)} | "
                   + " | ".join(str(counts.get(p, 0)) for p in prop_order)
                   + " |")
            lines.append(row)
    else:
        lines.append("_(No series summary available.)_")
    lines.append("")
    lines.append("## 3. Player + threshold coverage")
    lines.append("")
    lines.append("Sample market fields (keys present on the first observed "
                 "market across candidate series — informative for the "
                 "ingest schema):")
    lines.append("")
    for ticker, info in summary.items():
        keys = info.get("sample_market_keys", [])
        if keys:
            lines.append(f"**`{ticker}`** sample keys: `{', '.join(keys)}`")
            ex = info.get("sample_market_excerpt", {})
            if ex:
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(ex, indent=2))
                lines.append("```")
            lines.append("")
    lines.append("## 4. Orderbook depth sample")
    lines.append("")
    if ob_samples:
        lines.append("| Series | Market | yes_lvls | no_lvls | yes_qty | no_qty | last | vol_24h |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|")
        for s in ob_samples:
            lines.append(
                f"| `{s.get('series','')}` | `{s.get('market_ticker','')}` | "
                f"{s.get('yes_levels',0)} | {s.get('no_levels',0)} | "
                f"{s.get('yes_total_qty',0)} | {s.get('no_total_qty',0)} | "
                f"{s.get('last_price','—')} | {s.get('volume_24h','—')} |"
            )
    else:
        lines.append("_(No orderbook samples gathered.)_")
    lines.append("")
    lines.append("## 5. Deep-dive market")
    lines.append("")
    if deep:
        ex = deep.get("list_excerpt", {})
        lines.append("Single most-active market across candidate series. "
                     "Full detail in `07_deep_dive.json`.")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(ex, indent=2))
        lines.append("```")
    else:
        lines.append("_(No deep-dive market available.)_")
    lines.append("")
    lines.append("## 6. Findings — answers to probe questions")
    lines.append("")
    lines.append("| # | Question | Finding |")
    lines.append("|---|---|---|")
    n_series = len(candidates)
    n_markets = sum(info.get("n_markets", 0) for info in summary.values())
    prop_coverage = set()
    for info in summary.values():
        for p, c in info.get("prop_types_seen", {}).items():
            if c > 0 and p != "OTHER":
                prop_coverage.add(p)
    lines.append(f"| 1 | Series tickers covering NBA props? | "
                 f"{n_series} candidate series found "
                 f"({', '.join('`'+s.get('ticker','')+'`' for s in candidates) or 'NONE'}) |")
    lines.append(f"| 2 | Which props (PTS/REB/AST/3PM)? | "
                 f"Observed: {', '.join(sorted(prop_coverage)) or 'NONE'} |")
    lines.append(f"| 3 | How many total markets? | {n_markets} markets across "
                 f"all candidate series |")
    lines.append(f"| 4 | Tier / threshold structure | "
                 f"See market-detail dump in `07_deep_dive.json` — "
                 f"single line per player/prop, or alternates? Inspect manually. |")
    lines.append(f"| 5 | Orderbook depth | See section 4 — "
                 f"yes_levels / no_levels columns indicate book depth. |")
    lines.append(f"| 6 | Implied probability format | "
                 f"`yes_bid` / `no_bid` returned in **cents** (0-100). "
                 f"Implied prob = yes_bid / 100. |")
    lines.append(f"| 7 | Settlement / DNP handling | See `rules_primary` "
                 f"and `rules_secondary` fields in deep-dive market detail. "
                 f"Inspect manually. |")
    lines.append("")
    lines.append("## 7. Raw artifacts")
    lines.append("")
    lines.append("All raw JSON dumped to `data/kalshi_probe/`:")
    lines.append("")
    lines.append("- `01_sports_series_raw.json` — every Sports series")
    lines.append("- `02_nba_candidate_series.json` — keyword-filtered candidates")
    lines.append("- `03_events_<TICKER>.json` — events per candidate series")
    lines.append("- `04_markets_<TICKER>.json` — markets per candidate series")
    lines.append("- `05_series_summary.json` — structured roll-up")
    lines.append("- `06_orderbook_samples.json` — orderbook depth samples")
    lines.append("- `07_deep_dive.json` — full detail on one example market")
    lines.append("")
    lines.append("---")
    lines.append("*Probe is read-only and one-off. Re-running overwrites "
                 "all artifacts in `data/kalshi_probe/`.*")
    report_path = OUT / "REPORT.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ── main() ────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[probe] Starting Kalshi NBA prop probe at {TIMESTAMP}")
    print(f"[probe] Output dir: {OUT}")
    candidates = step1_find_series()
    if not candidates:
        # Fallback: try a wider net — list ALL series (not just Sports)
        # and re-filter. Sports category may not be the right home for
        # NBA props.
        print(f"\n[probe] Sports-category search returned no NBA "
              f"candidates — widening to ALL series")
        all_series = fetch_paginated("/series", "series")
        print(f"[probe] Total series across all categories: {len(all_series)}")
        (OUT / "01b_all_series_raw.json").write_text(
            json.dumps(all_series, indent=2), encoding="utf-8")
        nba_keywords = ["nba", "basketball", "points", "rebound",
                        "assist", "three-point", "3pm", "3pt"]
        candidates = [
            s for s in all_series
            if any(kw in (
                f"{s.get('ticker','')} {s.get('title','')} "
                f"{s.get('subtitle','')} {s.get('description','')}"
            ).lower() for kw in nba_keywords)
        ]
        print(f"[probe] Wide-net NBA candidates: {len(candidates)}")
        for s in candidates:
            print(f"  {s.get('ticker','')}: {s.get('title','')} "
                  f"[category: {s.get('category','')}]")
        (OUT / "02_nba_candidate_series.json").write_text(
            json.dumps(candidates, indent=2), encoding="utf-8")

    summary    = step2_enumerate_markets(candidates) if candidates else {}
    ob_samples = step3_orderbook_sample(summary)     if summary    else []
    deep       = step4_deep_dive(summary)            if summary    else None
    report     = step5_write_report(candidates, summary, ob_samples, deep)

    print(f"\n[probe] Done. Report: {report}")
    print(f"[probe] Raw artifacts in: {OUT}")


if __name__ == "__main__":
    main()
