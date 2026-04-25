"""
Single-Leg Edge Analysis: Conf-vs-Market Delta vs Actual Hit Rate.

Tests whether the system's confidence-versus-market delta predicts pick
outcomes at the single-leg level. Two banding passes:
  - Pass A: data-led deciles (no imposed boundaries)
  - Pass B: semantic-tag bands (deep_fade / fade / mild_fade / mild_edge /
            medium_edge / strong_edge)

Per-prop breakdown for the semantic-tag pass.

Run: python -m tools.single_leg_edge_analysis

Reads:
  - data/picks.json

Writes:
  - data/single_leg_edge_report.md

Companion to the parlay research analysis pipeline. The parlay research
report (data/parlay_research_report.md) showed that combined system_conf
was poorly calibrated at the parlay level. This script tests whether the
underlying single-leg conf-vs-market delta is itself predictive at all.

Note on data conventions: production picks.json stores `market_implied_prob`
and `confidence_pct` as percentages (0–100, e.g. 87.5), NOT decimals. We
filter on the percentage range and divide by 100 at compute time, so the
output's `delta`, `mean_conf`, and `mean_market` are in 0.0–1.0 form.

The picks dataset is truncated: it only contains picks the analyst chose
to emit (typically confidence_pct ≥ 70). Findings describe the relationship
between delta and hit rate within the emitted subset; they do NOT predict
what would happen if the filter were tightened. Additionally, market_implied_prob
coverage is partial across the season (earlier-season picks pre-OddsAPI lack
the field). The report reflects only the period since odds coverage began.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parent.parent
PICKS_PATH = REPO_ROOT / "data" / "picks.json"
OUTPUT_PATH = REPO_ROOT / "data" / "single_leg_edge_report.md"

PROP_TYPES = ("PTS", "REB", "AST", "3PM")
MIN_REPORTABLE_N_PER_PROP_BAND = 15
HIST_BIN_WIDTH = 0.01

# (label, lo_inclusive, hi_exclusive) — None = unbounded on that side
SEMANTIC_BANDS: list[tuple[str, float | None, float | None]] = [
    ("deep_fade",   None,  -0.10),
    ("fade",        -0.10, -0.05),
    ("mild_fade",   -0.05,  0.00),
    ("mild_edge",    0.00,  0.05),
    ("medium_edge",  0.05,  0.10),
    ("strong_edge",  0.10,  None),
]
SEMANTIC_BAND_ORDER = [b[0] for b in SEMANTIC_BANDS]


# ────────────────────────────────────────────────────────────────────
# Filter + features
# ────────────────────────────────────────────────────────────────────

def is_valid_pick(p: dict) -> bool:
    """
    Mirrors tools/parlay_research_enumerate.py is_valid_pick(), minus the
    player_name/team requirement which is unnecessary for this analysis.
    """
    if p.get("result") not in ("HIT", "MISS"):
        return False
    if p.get("voided") is True:
        return False
    cp = p.get("confidence_pct")
    if cp is None:
        return False
    try:
        cp_f = float(cp)
    except (TypeError, ValueError):
        return False
    if not (0.0 < cp_f < 100.0):
        return False
    mip = p.get("market_implied_prob")
    if mip is None:
        return False
    try:
        mip_f = float(mip)
    except (TypeError, ValueError):
        return False
    if not (0.0 < mip_f < 100.0):
        return False
    if p.get("prop_type") not in PROP_TYPES:
        return False
    return True


def load_valid_picks() -> tuple[list[dict], int]:
    with open(PICKS_PATH) as f:
        all_picks = json.load(f)
    valid = [p for p in all_picks if is_valid_pick(p)]
    return valid, len(all_picks)


def compute_features(p: dict) -> dict:
    conf = float(p["confidence_pct"]) / 100.0
    market = float(p["market_implied_prob"]) / 100.0
    return {
        "date": p.get("date", ""),
        "prop_type": p["prop_type"],
        "conf": conf,
        "market": market,
        "delta": conf - market,
        "hit": 1 if p["result"] == "HIT" else 0,
    }


# ────────────────────────────────────────────────────────────────────
# Banding
# ────────────────────────────────────────────────────────────────────

def assign_deciles_inplace(records: list[dict]) -> None:
    """
    Assign integer decile in [0, 9] to each record's "decile" key.

    Sorts records by delta, then walks the sorted list assigning decile
    by rank: decile = min(9, rank * 10 // n). This yields decile sizes
    of either floor(n/10) or floor(n/10)+1 (the final decile may absorb
    the remainder), which is the spec's "approximately equal" target.
    Ties at decile boundaries are broken by sort order (sorted() is
    stable on equal keys).
    """
    n = len(records)
    if n == 0:
        return
    sorted_records = sorted(records, key=lambda r: r["delta"])
    for rank, r in enumerate(sorted_records):
        r["decile"] = min(9, (rank * 10) // n)


def assign_semantic_band(delta: float) -> str:
    for label, lo, hi in SEMANTIC_BANDS:
        lo_ok = lo is None or delta >= lo
        hi_ok = hi is None or delta < hi
        if lo_ok and hi_ok:
            return label
    raise ValueError(f"No band matched for delta={delta}")  # unreachable: bands cover ℝ


def semantic_band_range_str(label: str) -> str:
    """Human-readable range string for the band, matching the spec's table."""
    for lbl, lo, hi in SEMANTIC_BANDS:
        if lbl != label:
            continue
        if lo is None and hi is not None:
            return f"delta < {hi:+.2f}"
        if lo is not None and hi is None:
            return f"delta ≥ {lo:+.2f}"
        return f"{lo:+.2f} ≤ delta < {hi:+.2f}"
    return ""


# ────────────────────────────────────────────────────────────────────
# Aggregation
# ────────────────────────────────────────────────────────────────────

def aggregate(records: list[dict], key_fn) -> dict:
    """
    Group records by key_fn(record); compute n / hits / hit_rate / mean_delta /
    mean_conf / mean_market for each group, plus min_delta / max_delta which
    the decile and distribution views need.
    """
    by_key = defaultdict(list)
    for r in records:
        by_key[key_fn(r)].append(r)

    out: dict = {}
    for k, rs in by_key.items():
        deltas = [r["delta"] for r in rs]
        out[k] = {
            "n": len(rs),
            "hits": sum(r["hit"] for r in rs),
            "hit_rate": round(sum(r["hit"] for r in rs) / len(rs), 4),
            "mean_delta": round(mean(deltas), 4),
            "min_delta": round(min(deltas), 4),
            "max_delta": round(max(deltas), 4),
            "mean_conf": round(mean(r["conf"] for r in rs), 4),
            "mean_market": round(mean(r["market"] for r in rs), 4),
        }
    return out


# ────────────────────────────────────────────────────────────────────
# Distribution
# ────────────────────────────────────────────────────────────────────

def compute_quantile_summary(values: list[float]) -> dict[str, float]:
    """
    Return {label: value} for min, p05, p10, p25, p50, p75, p90, p95, max.
    Uses simple index-based extraction (linear interpolation not required
    for descriptive purposes here).
    """
    sv = sorted(values)
    n = len(sv)
    if n == 0:
        return {}

    def at(p: float) -> float:
        idx = int(round(p * (n - 1)))
        return sv[max(0, min(n - 1, idx))]

    return {
        "min":  round(sv[0], 4),
        "p05":  round(at(0.05), 4),
        "p10":  round(at(0.10), 4),
        "p25":  round(at(0.25), 4),
        "p50":  round(at(0.50), 4),
        "p75":  round(at(0.75), 4),
        "p90":  round(at(0.90), 4),
        "p95":  round(at(0.95), 4),
        "max":  round(sv[-1], 4),
    }


def histogram(values: list[float], bin_width: float = HIST_BIN_WIDTH) -> list[tuple[float, float, int]]:
    """
    Bucket values into bins of width bin_width, half-open [lo, hi).

    Returns a list of (bin_lo, bin_hi, count) sorted by bin_lo. Uses
    math.floor() for correct negative-value handling: a value of -0.073
    falls into the bin [-0.08, -0.07) — int() would truncate toward zero
    and yield the wrong bin.
    """
    counts: dict[float, int] = defaultdict(int)
    for v in values:
        bin_lo = math.floor(v / bin_width) * bin_width
        bin_lo = round(bin_lo, 4)
        counts[bin_lo] += 1
    rows = sorted(counts.items())
    return [(lo, round(lo + bin_width, 4), n) for lo, n in rows]


# ────────────────────────────────────────────────────────────────────
# Markdown rendering
# ────────────────────────────────────────────────────────────────────

def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_delta(x: float) -> str:
    return f"{x:+.4f}"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def render_distribution_section(quantiles: dict[str, float], hist: list[tuple[float, float, int]]) -> str:
    lines: list[str] = []
    lines.append("## Section 3: Distribution of delta values")
    lines.append("")
    lines.append("### 3a — Quantile summary")
    lines.append("")
    lines.append(_row(["statistic", "delta"]))
    lines.append(_row(["---", "---"]))
    for label in ("min", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "max"):
        if label in quantiles:
            lines.append(_row([label, _fmt_delta(quantiles[label])]))
    lines.append("")
    lines.append(f"### 3b — Histogram (bin width = {HIST_BIN_WIDTH}, half-open [lo, hi))")
    lines.append("")
    lines.append(_row(["bin", "n"]))
    lines.append(_row(["---", "---"]))
    for lo, hi, n in hist:
        bin_label = f"[{lo:+.2f}, {hi:+.2f})"
        lines.append(_row([bin_label, str(n)]))
    return "\n".join(lines)


def render_decile_section(by_decile: dict) -> str:
    lines: list[str] = []
    lines.append("## Section 4: Banding A — Deciles (data-led)")
    lines.append("")
    lines.append(_row([
        "decile", "delta_min", "delta_max", "mean_delta",
        "n", "hits", "hit_rate", "mean_conf", "mean_market",
    ]))
    lines.append(_row(["---"] * 9))
    for d in range(10):
        if d not in by_decile:
            lines.append(_row([str(d), "—", "—", "—", "0", "0", "—", "—", "—"]))
            continue
        agg = by_decile[d]
        lines.append(_row([
            str(d),
            _fmt_delta(agg["min_delta"]),
            _fmt_delta(agg["max_delta"]),
            _fmt_delta(agg["mean_delta"]),
            str(agg["n"]),
            str(agg["hits"]),
            _fmt_pct(agg["hit_rate"]),
            _fmt_delta(agg["mean_conf"]),
            _fmt_delta(agg["mean_market"]),
        ]))
    return "\n".join(lines)


def render_semantic_section(by_band: dict, *, header_title: str, prop_filter: str | None = None) -> str:
    lines: list[str] = []
    lines.append(f"### {header_title}")
    lines.append("")
    lines.append(_row([
        "band", "delta_range", "n", "hits", "hit_rate",
        "mean_delta", "mean_conf", "mean_market", "flag",
    ]))
    lines.append(_row(["---"] * 9))
    for label in SEMANTIC_BAND_ORDER:
        agg = by_band.get(label)
        if agg is None:
            lines.append(_row([
                label, semantic_band_range_str(label),
                "0", "0", "—", "—", "—", "—",
                "no_data" if prop_filter is None else "no_data",
            ]))
            continue
        flag = ""
        if prop_filter is not None and agg["n"] < MIN_REPORTABLE_N_PER_PROP_BAND:
            flag = "insufficient_sample"
        lines.append(_row([
            label,
            semantic_band_range_str(label),
            str(agg["n"]),
            str(agg["hits"]),
            _fmt_pct(agg["hit_rate"]),
            _fmt_delta(agg["mean_delta"]),
            _fmt_delta(agg["mean_conf"]),
            _fmt_delta(agg["mean_market"]),
            flag,
        ]))
    return "\n".join(lines)


def render_markdown(
    *,
    n_total_picks: int,
    n_picks: int,
    date_min: str,
    date_max: str,
    overall_hit_rate: float,
    quantiles: dict,
    hist: list[tuple[float, float, int]],
    by_decile: dict,
    by_band: dict,
    by_prop_band: dict,
) -> str:
    out: list[str] = []

    # ── Section 1: Header & metadata ──
    out.append("# Single-Leg Edge Analysis: Conf-vs-Market Delta vs Actual Hit Rate")
    out.append("")
    out.append("## Section 1: Header & metadata")
    out.append("")
    out.append(_row(["field", "value"]))
    out.append(_row(["---", "---"]))
    out.append(_row(["date_generated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]))
    out.append(_row(["source_file", "data/picks.json"]))
    out.append(_row(["total_picks_loaded", str(n_total_picks)]))
    out.append(_row(["picks_passing_filter", str(n_picks)]))
    out.append(_row(["date_range_min", date_min]))
    out.append(_row(["date_range_max", date_max]))
    out.append(_row(["overall_hit_rate", _fmt_pct(overall_hit_rate)]))
    out.append("")

    # ── Section 2: Caveats ──
    out.append("## Section 2: Caveats")
    out.append("")
    out.append(
        "**Truncated distribution.** This analysis covers only picks the analyst "
        "emitted, typically those with `confidence_pct ≥ 70`. Findings describe "
        "the relationship between delta and hit rate within the emitted subset. "
        "They do NOT predict what would happen if the filter were tightened to "
        "high-delta picks only."
    )
    out.append("")
    out.append(
        "**Partial odds coverage.** market_implied_prob is missing for earlier-"
        "season picks (before OddsAPI infrastructure shipped). Filtering for "
        "picks with the field reduces the dataset substantially. Findings "
        "represent the period since odds coverage began."
    )
    out.append("")

    # ── Section 3: Distribution ──
    out.append(render_distribution_section(quantiles, hist))
    out.append("")

    # ── Section 4: Deciles ──
    out.append(render_decile_section(by_decile))
    out.append("")

    # ── Section 5: Semantic bands (overall) ──
    out.append("## Section 5: Banding B — Semantic tags (overall, all props)")
    out.append("")
    out.append(render_semantic_section(by_band, header_title="5a — All props", prop_filter=None))
    out.append("")

    # ── Section 6: Per-prop semantic bands ──
    out.append("## Section 6: Banding B — Per-prop breakdown")
    out.append("")
    for prop in PROP_TYPES:
        prop_bands = {k[1]: v for k, v in by_prop_band.items() if k[0] == prop}
        out.append(render_semantic_section(
            prop_bands,
            header_title=f"6.{PROP_TYPES.index(prop) + 1} — {prop}",
            prop_filter=prop,
        ))
        out.append("")

    # ── Section 7: No interpretive commentary ──
    out.append("## Section 7: No interpretive commentary")
    out.append("")
    out.append(
        "This report is data only. Interpretation of whether deciles trend up, "
        "whether semantic tags map to anything meaningful, or what the action "
        "implication is — lives in chat, not in this file."
    )
    out.append("")

    return "\n".join(out)


# ────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Loading picks from {PICKS_PATH} ...")
    picks, total_loaded = load_valid_picks()
    print(f"  {total_loaded} total picks; {len(picks)} valid (HIT/MISS, with odds, not voided).")

    if not picks:
        raise SystemExit("No valid picks after filter; aborting.")

    records = [compute_features(p) for p in picks]

    # Decile assignment (in-place, modifies records via shared reference)
    assign_deciles_inplace(records)
    for r in records:
        r["band"] = assign_semantic_band(r["delta"])

    # Aggregations
    by_decile = aggregate(records, lambda r: r["decile"])
    by_band = aggregate(records, lambda r: r["band"])
    by_prop_band = aggregate(records, lambda r: (r["prop_type"], r["band"]))

    # Distribution view
    quantiles = compute_quantile_summary([r["delta"] for r in records])
    hist = histogram([r["delta"] for r in records])

    # Header metadata
    dates = sorted({r["date"] for r in records if r.get("date")})
    overall_hit_rate = sum(r["hit"] for r in records) / len(records)

    md = render_markdown(
        n_total_picks=total_loaded,
        n_picks=len(records),
        date_min=dates[0] if dates else "",
        date_max=dates[-1] if dates else "",
        overall_hit_rate=overall_hit_rate,
        quantiles=quantiles,
        hist=hist,
        by_decile=by_decile,
        by_band=by_band,
        by_prop_band=by_prop_band,
    )

    OUTPUT_PATH.write_text(md)
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Overall: n={len(records)}, hit_rate={overall_hit_rate:.1%}")

    # Brief stdout summary
    print("\nDecile sizes:", [by_decile.get(d, {}).get("n", 0) for d in range(10)])
    print("Band sizes:  ", [(b, by_band.get(b, {}).get("n", 0)) for b in SEMANTIC_BAND_ORDER])


if __name__ == "__main__":
    main()
