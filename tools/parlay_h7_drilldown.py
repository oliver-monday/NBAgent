"""
Parlay Research Drilldown: H7 Same-Player Concentration in Reach.

Streams parlay_card_universe.jsonl, isolates the Reach bucket cards with
max_legs_per_player>=3 (the only positive-delta-vs-market subset in the
parlay research report at +1.7pp), and breaks down the subset by:
  - Concentration player (the player contributing 3+ legs)
  - Date
  - Player × date intersection
  - Stat-trio composition
  - Same-player leg count (3 vs 4)
  - Total card leg count

Run: python -m tools.parlay_h7_drilldown

Reads:
  - data/parlay_card_universe.jsonl   (output of tools/parlay_research_enumerate.py)

Writes:
  - data/parlay_h7_drilldown.md
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---- Paths and constants -----------------------------------------------------

REPO_ROOT     = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = REPO_ROOT / "data" / "parlay_card_universe.jsonl"
OUTPUT_PATH   = REPO_ROOT / "data" / "parlay_h7_drilldown.md"

MIN_REPORTABLE_N = 20   # lower than main analysis since we're slicing a 640-card subset

INTERPRETATION_NOTES = (
    "This drilldown is data only. Interpretation lives in chat after review. "
    "Key questions:\n"
    "1. Is the +1.7pp signal broad-based across players or concentrated in 1-2 stars?\n"
    "2. Are the cards date-clustered (suggesting hot streaks rather than structural pattern)?\n"
    "3. Does any specific stat trio outperform others significantly?\n"
    "4. Does 3-leg concentration differ meaningfully from 4-leg concentration?"
)


# ---- Card filter and feature extraction --------------------------------------

def is_target_card(card: dict) -> bool:
    """
    Target subset: Reach bucket AND max_legs_per_player >= 3.
    """
    return (
        card.get("bucket") == "Reach"
        and card.get("max_legs_per_player", 0) >= 3
    )


def extract_concentration_player(card: dict) -> tuple[str, list[str]]:
    """
    Identify the player contributing 3+ legs and return (player_name, sorted_stat_list).

    leg_player_props entries are formatted as "{player_name}|{prop_type}|{tier}".
    Returns ("", []) if no 3+ player concentration found (defensive — should not
    happen for target cards but guards against malformed entries).
    """
    leg_strs = card.get("leg_player_props", [])
    legs_parsed: list[tuple[str, str, str]] = []
    for ls in leg_strs:
        parts = ls.split("|")
        if len(parts) != 3:
            continue
        player, prop, tier = parts
        legs_parsed.append((player, prop, tier))

    by_player: dict[str, list[str]] = defaultdict(list)
    for player, prop, _tier in legs_parsed:
        by_player[player].append(prop)

    # Find player with most legs (ties broken by name for determinism)
    best_player = ""
    best_count = 0
    for player in sorted(by_player.keys()):
        cnt = len(by_player[player])
        if cnt > best_count:
            best_count = cnt
            best_player = player

    if best_count < 3:
        return ("", [])

    # Sorted stat list to produce a canonical trio key (e.g. AST|PTS|REB)
    stats = sorted(by_player[best_player])
    return (best_player, stats)


# ---- Aggregation -------------------------------------------------------------

def _new_full_agg() -> dict:
    return {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}


def _new_count_agg() -> dict:
    return {"n": 0, "hits": 0}


def run_drilldown() -> dict:
    print(f"Streaming {UNIVERSE_PATH} ...")

    overall              = _new_full_agg()
    by_player            = defaultdict(_new_full_agg)
    by_date              = defaultdict(_new_full_agg)
    by_player_date       = defaultdict(_new_count_agg)
    by_stat_trio         = defaultdict(_new_full_agg)
    by_legs_concentrated = defaultdict(_new_full_agg)
    by_total_n_legs      = defaultdict(_new_full_agg)

    n_streamed = 0
    n_target   = 0
    with open(UNIVERSE_PATH) as f:
        for line in f:
            n_streamed += 1
            card = json.loads(line)
            if not is_target_card(card):
                continue
            n_target += 1

            player, stats = extract_concentration_player(card)
            if not player:
                continue  # defensive guard; target cards by construction have player

            mp           = card["combined_market_prob"]
            sc           = card["combined_system_conf"]
            hit          = 1 if card["hit"] else 0
            date         = card["date"]
            n_legs_card  = card["n_legs"]
            n_legs_concentrated = len(stats)  # 3 or 4
            trio_key     = "|".join(stats)

            # Overall
            overall["n"]          += 1
            overall["hits"]       += hit
            overall["sum_market"] += mp
            overall["sum_system"] += sc

            # Per-player
            a = by_player[player]
            a["n"]          += 1
            a["hits"]       += hit
            a["sum_market"] += mp
            a["sum_system"] += sc

            # Per-date
            a = by_date[date]
            a["n"]          += 1
            a["hits"]       += hit
            a["sum_market"] += mp
            a["sum_system"] += sc

            # Player × date (count + hits only)
            a = by_player_date[(player, date)]
            a["n"]    += 1
            a["hits"] += hit

            # Stat trio
            a = by_stat_trio[trio_key]
            a["n"]          += 1
            a["hits"]       += hit
            a["sum_market"] += mp
            a["sum_system"] += sc

            # Concentration legs (3 vs 4)
            a = by_legs_concentrated[n_legs_concentrated]
            a["n"]          += 1
            a["hits"]       += hit
            a["sum_market"] += mp
            a["sum_system"] += sc

            # Total card legs (3, 4, or 5)
            a = by_total_n_legs[n_legs_card]
            a["n"]          += 1
            a["hits"]       += hit
            a["sum_market"] += mp
            a["sum_system"] += sc

    print(f"  streamed {n_streamed:,} total cards, {n_target:,} matched target subset")
    if n_target == 0:
        raise RuntimeError(
            "No target cards found — H7 Reach subset is empty. Investigate."
        )

    return {
        "n_streamed":           n_streamed,
        "n_target":             n_target,
        "overall":              overall,
        "by_player":            dict(by_player),
        "by_date":              dict(by_date),
        "by_player_date":       dict(by_player_date),
        "by_stat_trio":         dict(by_stat_trio),
        "by_legs_concentrated": dict(by_legs_concentrated),
        "by_total_n_legs":      dict(by_total_n_legs),
    }


def finalize(agg: dict) -> dict:
    """Convert a single aggregator dict to a finalized stats dict."""
    n = agg["n"]
    if n == 0:
        return {
            "n": 0, "hit_rate": None,
            "expected_market": None, "expected_system": None,
            "delta_vs_market": None, "delta_vs_system": None,
        }
    hr  = agg["hits"] / n
    out = {"n": n, "hits": agg["hits"], "hit_rate": round(hr, 4)}
    if "sum_market" in agg:
        em = agg["sum_market"] / n
        es = agg["sum_system"] / n
        out["expected_market"] = round(em, 4)
        out["expected_system"] = round(es, 4)
        out["delta_vs_market"] = round(hr - em, 4)
        out["delta_vs_system"] = round(hr - es, 4)
    return out


# ---- Markdown rendering helpers ----------------------------------------------

def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%"


def _delta(v) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.1f}pp"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _full_row(label: str, st: dict) -> str:
    """Render a row with all 6 stat columns (full agg with market/system data)."""
    n = st["n"]
    if n < MIN_REPORTABLE_N:
        return _row([label, f"{n:,}", str(st["hits"]), "—", "—", "—", "—",
                     "*insufficient_sample*"])
    return _row([
        label,
        f"{n:,}",
        str(st["hits"]),
        _pct(st["hit_rate"]),
        _pct(st["expected_market"]),
        _delta(st["delta_vs_market"]),
        _delta(st["delta_vs_system"]),
        "",
    ])


# ---- Markdown emitter --------------------------------------------------------

def render_markdown(results: dict) -> str:
    overall_final = finalize(results["overall"])

    md: list[str] = []

    # 1. Header & metadata
    md.append("# Parlay Research Drilldown — H7 Same-Player Concentration in Reach")
    md.append("")
    md.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    md.append("")
    md.append(f"- Source: `{UNIVERSE_PATH.relative_to(REPO_ROOT)}`")
    md.append(f"- Total cards streamed: {results['n_streamed']:,}")
    md.append(f"- Target subset size (Reach + max_legs_per_player≥3): {results['n_target']:,}")
    md.append(f"- Min reportable n per row: {MIN_REPORTABLE_N}")
    md.append("")

    # 2. Overall subset stats
    md.append("## 1. Overall Subset Stats")
    md.append("")
    md.append(_row([
        "subset", "n", "hits", "actual_hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    of = overall_final
    md.append(_row([
        "Reach + max_legs_per_player≥3",
        f"{of['n']:,}",
        str(of["hits"]),
        _pct(of["hit_rate"]),
        _pct(of["expected_market"]),
        _delta(of["delta_vs_market"]),
        _delta(of["delta_vs_system"]),
    ]))
    md.append("")

    # 3. Player breakdown — sorted by hit_rate desc, insufficient at bottom
    md.append("## 2. Player Breakdown")
    md.append("")
    md.append(
        "Cards in the subset grouped by the player contributing 3+ legs. "
        "Sorted by `hit_rate` descending; rows with n<20 are flagged "
        "*insufficient_sample* and pushed to the bottom."
    )
    md.append("")
    md.append(_row([
        "player", "n_cards", "hits", "hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system", "flag",
    ]))
    md.append(_row(["---"] * 8))
    by_player_finalized = sorted(
        [(name, finalize(agg)) for name, agg in results["by_player"].items()],
        key=lambda x: (
            1 if x[1]["n"] < MIN_REPORTABLE_N else 0,
            -(x[1]["hit_rate"] or 0.0),
        ),
    )
    for name, st in by_player_finalized:
        md.append(_full_row(name, st))
    md.append("")

    # 4. Date breakdown — sorted by date asc
    md.append("## 3. Date Breakdown")
    md.append("")
    md.append("Cards in the subset grouped by date (sorted chronologically).")
    md.append("")
    md.append(_row([
        "date", "n_cards", "hits", "hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system", "flag",
    ]))
    md.append(_row(["---"] * 8))
    by_date_finalized = [
        (date, finalize(agg)) for date, agg in results["by_date"].items()
    ]
    by_date_finalized.sort(key=lambda x: x[0])
    for date, st in by_date_finalized:
        md.append(_full_row(date, st))
    md.append("")

    # 5. Player × Date concentration — top 10 by n
    md.append("## 4. Player × Date Concentration (Top 10 by n_cards)")
    md.append("")
    md.append(
        "Top 10 (player, date) pairs by card count. A single (player, date) "
        "with >20 cards represents a heavy concentration of the subset on one slate."
    )
    md.append("")
    md.append(_row(["rank", "player", "date", "n_cards", "hits", "hit_rate"]))
    md.append(_row(["---"] * 6))
    pd_pairs = sorted(
        results["by_player_date"].items(),
        key=lambda x: -x[1]["n"],
    )[:10]
    for i, ((player, date), agg) in enumerate(pd_pairs, 1):
        n  = agg["n"]
        hr = agg["hits"] / n if n else 0
        md.append(_row([
            str(i), player, date,
            f"{n:,}", str(agg["hits"]),
            _pct(hr) if n > 0 else "—",
        ]))
    md.append("")

    # 6. Stat trio breakdown — sorted by hit_rate desc
    md.append("## 5. Stat Trio Breakdown")
    md.append("")
    md.append(
        "For 3-leg concentration the trio is one of C(4,3)=4 (PTS|REB|AST, "
        "PTS|REB|3PM, PTS|AST|3PM, REB|AST|3PM); for 4-leg concentration the "
        "trio is the unique PTS|REB|AST|3PM. Sorted by `hit_rate` descending."
    )
    md.append("")
    md.append(_row([
        "stat_trio", "n_cards", "hits", "hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system", "flag",
    ]))
    md.append(_row(["---"] * 8))
    trios_finalized = sorted(
        [(trio, finalize(agg)) for trio, agg in results["by_stat_trio"].items()],
        key=lambda x: (
            1 if x[1]["n"] < MIN_REPORTABLE_N else 0,
            -(x[1]["hit_rate"] or 0.0),
        ),
    )
    for trio, st in trios_finalized:
        md.append(_full_row(trio, st))
    md.append("")

    # 7. Concentration legs (3 vs 4)
    md.append("## 6. Concentration Legs (3 vs 4 same-player legs)")
    md.append("")
    md.append(
        "Does 3-leg same-player concentration perform differently from 4-leg "
        "same-player concentration?"
    )
    md.append("")
    md.append(_row([
        "concentration_legs", "n_cards", "hits", "hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system", "flag",
    ]))
    md.append(_row(["---"] * 8))
    legs_conc_sorted = sorted(
        results["by_legs_concentrated"].items(), key=lambda x: x[0]
    )
    for k, agg in legs_conc_sorted:
        st = finalize(agg)
        md.append(_full_row(f"{k}-leg", st))
    md.append("")

    # 8. Total card legs distribution
    md.append("## 7. Total Card Legs Distribution")
    md.append("")
    md.append(
        "Distribution of the subset by the card's TOTAL leg count (vs the "
        "player-concentrated count above). A 3-leg card with all 3 legs same "
        "player is fundamentally different from a 5-leg card with 3 legs "
        "same player + 2 other-player legs."
    )
    md.append("")
    md.append(_row([
        "total_n_legs", "n_cards", "hits", "hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system", "flag",
    ]))
    md.append(_row(["---"] * 8))
    total_legs_sorted = sorted(
        results["by_total_n_legs"].items(), key=lambda x: x[0]
    )
    for k, agg in total_legs_sorted:
        st = finalize(agg)
        md.append(_full_row(f"L={k}", st))
    md.append("")

    # 9. Interpretation notes (verbatim)
    md.append("## 8. Interpretation Notes")
    md.append("")
    md.append("> " + INTERPRETATION_NOTES.replace("\n", "\n> "))
    md.append("")

    return "\n".join(md)


# ---- CLI entry point ---------------------------------------------------------

def main():
    results  = run_drilldown()
    markdown = render_markdown(results)
    OUTPUT_PATH.write_text(markdown)

    print()
    print(f"Wrote drilldown to {OUTPUT_PATH}")
    overall_final = finalize(results["overall"])
    print(
        f"Overall subset: n={overall_final['n']:,}, "
        f"hit_rate={overall_final['hit_rate']:.1%}, "
        f"delta_vs_market={overall_final['delta_vs_market']:+.1%}, "
        f"delta_vs_system={overall_final['delta_vs_system']:+.1%}"
    )
    print(f"Unique players in subset: {len(results['by_player'])}")
    print(f"Unique dates in subset:   {len(results['by_date'])}")


if __name__ == "__main__":
    main()
