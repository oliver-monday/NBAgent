"""
Parlay Research — Hypothesis Analysis (Prompt 2 of 2).

Streams data/parlay_card_universe.jsonl, computes per-bucket per-hypothesis
hit rates (Stable / Safe / Reach / Degen) with deltas vs combined_market_prob
and combined_system_conf, runs 10 hand-picked compound archetypes per bucket,
drills into the Stable and Reach bucket distributions, and emits a markdown
report.

Run: python -m tools.parlay_research_analyze

Reads:
  - data/parlay_card_universe.jsonl   (output of tools/parlay_research_enumerate.py)

Writes:
  - data/parlay_research_report.md
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ---- Constants ---------------------------------------------------------------

REPO_ROOT     = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = REPO_ROOT / "data" / "parlay_card_universe.jsonl"
PICKS_PATH    = REPO_ROOT / "data" / "picks.json"
OUTPUT_PATH   = REPO_ROOT / "data" / "parlay_research_report.md"

BUCKETS    = ("Stable", "Safe", "Reach", "Degen")
STAT_TYPES = ("PTS", "REB", "AST", "3PM")

MIN_REPORTABLE_N = 100   # subsets with fewer cards are flagged insufficient_sample

CAVEAT_TEMPLATE = (
    "**Caveat: small base-pick pool.** This analysis enumerates combinations "
    "of {n_picks} graded picks across {n_dates} dates. Findings reflect the "
    "structural patterns in *this season's pick distribution*, not universal "
    "parlay truths. Patterns identified should be re-validated as the picks "
    "dataset grows. Subgroups with n<100 are excluded from interpretation."
)


def load_pick_pool_size() -> tuple[int, int]:
    """
    Read picks.json and count picks that would have qualified for enumeration,
    plus distinct dates among them. Used for the Caveat block — drives
    n_picks / n_dates programmatically rather than hardcoding.

    Filter MUST match `tools.parlay_research_enumerate.is_valid_pick` exactly,
    otherwise the reported caveat won't reflect the actual universe inputs:
      - result in ("HIT", "MISS")
      - voided != True
      - market_implied_prob present and in (0, 100)  [stored as percentage]
      - confidence_pct present and in (0, 100)
      - prop_type in {PTS, REB, AST, 3PM}
      - player_name and team present

    Returns (n_picks, n_dates). Returns (0, 0) gracefully if picks.json is
    missing or malformed (caveat will read "0 graded picks across 0 dates"
    which is conspicuous enough to flag).
    """
    if not PICKS_PATH.exists():
        return (0, 0)
    try:
        with open(PICKS_PATH) as f:
            all_picks = json.load(f)
    except Exception:
        return (0, 0)
    n_picks = 0
    dates: set[str] = set()
    for p in all_picks:
        if p.get("result") not in ("HIT", "MISS"):
            continue
        if p.get("voided") is True:
            continue
        mip = p.get("market_implied_prob")
        if mip is None:
            continue
        try:
            if not (0.0 < float(mip) < 100.0):
                continue
        except (TypeError, ValueError):
            continue
        cp = p.get("confidence_pct")
        if cp is None:
            continue
        try:
            if not (0.0 < float(cp) < 100.0):
                continue
        except (TypeError, ValueError):
            continue
        if p.get("prop_type") not in STAT_TYPES:
            continue
        if not p.get("player_name") or not p.get("team"):
            continue
        date = p.get("date")
        if not date:
            continue
        n_picks += 1
        dates.add(date)
    return (n_picks, len(dates))


# ---- Aggregator --------------------------------------------------------------

class Aggregator:
    """
    Streaming aggregator. For each subset key (defined by hypothesis + bucket
    + subgroup label), tracks: count, hits, sum_market_prob, sum_system_conf.

    Final stats computed by finalize() at end.
    """

    def __init__(self):
        # key: (hypothesis_id, bucket, subgroup_label) → dict of running totals
        self.aggregates = defaultdict(
            lambda: {
                "n":          0,
                "hits":       0,
                "sum_market": 0.0,
                "sum_system": 0.0,
            }
        )

    def add(self, key: tuple, card: dict) -> None:
        a = self.aggregates[key]
        a["n"]          += 1
        a["hits"]       += 1 if card["hit"] else 0
        a["sum_market"] += card["combined_market_prob"]
        a["sum_system"] += card["combined_system_conf"]

    def finalize(self) -> dict:
        """
        Return {key: {n, hits, hit_rate, expected_market, expected_system,
                      delta_vs_market, delta_vs_system}}.
        """
        out: dict = {}
        for key, a in self.aggregates.items():
            n = a["n"]
            if n == 0:
                continue
            hr = a["hits"] / n
            em = a["sum_market"] / n
            es = a["sum_system"] / n
            out[key] = {
                "n":               n,
                "hits":            a["hits"],
                "hit_rate":        round(hr, 4),
                "expected_market": round(em, 4),
                "expected_system": round(es, 4),
                "delta_vs_market": round(hr - em, 4),
                "delta_vs_system": round(hr - es, 4),
            }
        return out


# ---- Subgroup classification logic -------------------------------------------

def h1_prop_mix_subgroups(card: dict) -> list[str]:
    """Returns list of subgroup labels for H1 (a card may belong to multiple)."""
    labels = [card["prop_dominant"]]
    if card["all_same_prop"]:
        # Also tag with all_<STAT> rollup
        labels.append(f"all_{card['prop_dominant']}")
    return labels


def h2_cross_game_subgroups(card: dict) -> list[str]:
    labels = []
    labels.append("all_cross_game" if card["all_cross_game"] else "has_same_game")
    if card["max_legs_per_game"] == 2:
        labels.append("max_per_game_2")
    elif card["max_legs_per_game"] >= 3:
        labels.append("max_per_game_3plus")
    return labels


def h3_iron_floor_subgroups(card: dict) -> list[str]:
    labels = []
    if card["all_iron_floor"]:
        labels.append("all_iron_floor")
    elif card["n_iron_floor"] == 0:
        labels.append("zero_iron_floor")
    elif card["n_iron_floor"] == 1:
        labels.append("one_iron_floor")
    elif card["n_iron_floor"] >= 2:
        labels.append("two_plus_iron_floor_not_all")
    return labels


def h4_dispersion_subgroups(card: dict) -> list[str]:
    d = card["confidence_dispersion"]
    if d < 0.05:
        return ["dispersion_lt_05"]
    elif d < 0.10:
        return ["dispersion_05_10"]
    elif d < 0.20:
        return ["dispersion_10_20"]
    else:
        return ["dispersion_gte_20"]


def h5_same_team_subgroups(card: dict) -> list[str]:
    m = card["max_legs_per_team"]
    if m == 1:
        return ["all_different_teams"]
    elif m == 2:
        return ["one_team_2_legs"]
    else:
        return ["one_team_3plus_legs"]


def h6_conf_vs_market_subgroups(card: dict) -> list[str]:
    cmm = card["conf_minus_market"]
    if cmm < 0:
        return ["system_pessimistic"]
    elif cmm < 0.05:
        return ["edge_small"]
    elif cmm < 0.10:
        return ["edge_medium"]
    else:
        return ["edge_large"]


def h7_per_player_subgroups(card: dict) -> list[str]:
    m = card["max_legs_per_player"]
    if m == 1:
        return ["all_different_players"]
    elif m == 2:
        return ["one_player_2_legs"]
    else:
        return ["one_player_3plus_legs"]


# ---- Compound archetypes -----------------------------------------------------

def matches_archetype(card: dict, archetype_id: str) -> bool:
    """Return True if the card matches the named compound archetype."""
    if archetype_id == "A1":
        return card["all_cross_game"] and card["n_legs"] == 2
    if archetype_id == "A2":
        return card["all_cross_game"] and card["n_legs"] == 3
    if archetype_id == "A3":
        return card["all_cross_game"] and card["prop_dominant"] == "REB"
    if archetype_id == "A4":
        return card["all_iron_floor"] and card["n_legs"] <= 3
    if archetype_id == "A5":
        return card["n_iron_floor"] >= 2 and card["n_legs"] <= 4
    if archetype_id == "A6":
        return (
            card["all_cross_game"]
            and card["all_same_prop"]
            and card["prop_dominant"] == "REB"
        )
    if archetype_id == "A7":
        return (
            card["max_legs_per_game"] == 1
            and card["prop_dominant"] in ("PTS", "REB")
        )
    if archetype_id == "A8":
        return card["min_leg_conf"] >= 0.80 and card["n_legs"] == 2
    if archetype_id == "A9":
        return card["min_leg_conf"] >= 0.80 and card["n_legs"] == 3
    if archetype_id == "A10":
        return card["confidence_dispersion"] < 0.05 and card["n_legs"] == 2
    return False


ARCHETYPES = ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]
ARCHETYPE_DESCRIPTIONS = {
    "A1":  "all cross-game, 2 legs",
    "A2":  "all cross-game, 3 legs",
    "A3":  "all cross-game, REB-dominant",
    "A4":  "all iron_floor, ≤3 legs",
    "A5":  "≥2 iron_floor legs, ≤4 legs",
    "A6":  "all cross-game, all REB",
    "A7":  "all unique games, PTS or REB dominant",
    "A8":  "min leg conf ≥ 80%, 2 legs",
    "A9":  "min leg conf ≥ 80%, 3 legs",
    "A10": "tight uniform conf (dispersion <5pp), 2 legs",
}


# ---- Stable bucket investigator ----------------------------------------------

class StableInvestigator:
    """Tracks Stable-bucket distribution by leg count and combined_market_prob bin."""

    def __init__(self):
        self.by_legs = defaultdict(
            lambda: {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}
        )
        # 0.01-wide bins for (0.66, 0.85] — same convention as ReachInvestigator
        self.by_market_bin = defaultdict(
            lambda: {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}
        )

    def add(self, card: dict) -> None:
        if card["bucket"] != "Stable":
            return
        # By legs
        l = card["n_legs"]
        b = self.by_legs[l]
        b["n"]          += 1
        b["hits"]       += 1 if card["hit"] else 0
        b["sum_market"] += card["combined_market_prob"]
        b["sum_system"] += card["combined_system_conf"]

        # By market-prob bin (0.01-wide)
        cmp_v  = card["combined_market_prob"]
        bin_lo = round(int(cmp_v * 100) / 100, 2)
        bin_hi = round(bin_lo + 0.01, 2)
        bin_key = f"{bin_lo:.2f}_{bin_hi:.2f}"
        bb = self.by_market_bin[bin_key]
        bb["n"]          += 1
        bb["hits"]       += 1 if card["hit"] else 0
        bb["sum_market"] += card["combined_market_prob"]
        bb["sum_system"] += card["combined_system_conf"]

    def finalize_dict(self, src: dict) -> list[dict]:
        out = []
        for k, v in src.items():
            if v["n"] == 0:
                continue
            hr = v["hits"] / v["n"]
            em = v["sum_market"] / v["n"]
            es = v["sum_system"] / v["n"]
            out.append({
                "key":             k,
                "n":               v["n"],
                "hits":            v["hits"],
                "hit_rate":        round(hr, 4),
                "expected_market": round(em, 4),
                "expected_system": round(es, 4),
                "delta_vs_market": round(hr - em, 4),
                "delta_vs_system": round(hr - es, 4),
            })
        return out


# ---- Reach bucket investigator -----------------------------------------------

class ReachInvestigator:
    """Tracks Reach-bucket distribution by leg count and combined_market_prob bin."""

    def __init__(self):
        self.by_legs = defaultdict(
            lambda: {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}
        )
        self.by_market_bin = defaultdict(
            lambda: {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}
        )

    def add(self, card: dict) -> None:
        if card["bucket"] != "Reach":
            return
        # By legs
        l = card["n_legs"]
        b = self.by_legs[l]
        b["n"]          += 1
        b["hits"]       += 1 if card["hit"] else 0
        b["sum_market"] += card["combined_market_prob"]
        b["sum_system"] += card["combined_system_conf"]

        # By market-prob bin (0.01-wide bins between 0.30 and 0.45)
        cmp_v  = card["combined_market_prob"]
        bin_lo = round(int(cmp_v * 100) / 100, 2)
        bin_hi = round(bin_lo + 0.01, 2)
        bin_key = f"{bin_lo:.2f}_{bin_hi:.2f}"
        bb = self.by_market_bin[bin_key]
        bb["n"]          += 1
        bb["hits"]       += 1 if card["hit"] else 0
        bb["sum_market"] += card["combined_market_prob"]
        bb["sum_system"] += card["combined_system_conf"]

    def finalize_dict(self, src: dict) -> list[dict]:
        out = []
        for k, v in src.items():
            if v["n"] == 0:
                continue
            hr = v["hits"] / v["n"]
            em = v["sum_market"] / v["n"]
            es = v["sum_system"] / v["n"]
            out.append({
                "key":             k,
                "n":               v["n"],
                "hits":            v["hits"],
                "hit_rate":        round(hr, 4),
                "expected_market": round(em, 4),
                "expected_system": round(es, 4),
                "delta_vs_market": round(hr - em, 4),
                "delta_vs_system": round(hr - es, 4),
            })
        return out


# ---- Universe-level summary aggregator ---------------------------------------

class UniverseSummary:
    """Tracks bucket totals and per-bucket per-leg-count breakdowns."""

    def __init__(self):
        self.bucket_totals = defaultdict(
            lambda: {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}
        )
        self.bucket_by_legs = defaultdict(
            lambda: defaultdict(
                lambda: {"n": 0, "hits": 0, "sum_market": 0.0, "sum_system": 0.0}
            )
        )
        self.n_total = 0

    def add(self, card: dict) -> None:
        self.n_total += 1
        b = card["bucket"]
        bt = self.bucket_totals[b]
        bt["n"]          += 1
        bt["hits"]       += 1 if card["hit"] else 0
        bt["sum_market"] += card["combined_market_prob"]
        bt["sum_system"] += card["combined_system_conf"]

        bbl = self.bucket_by_legs[b][card["n_legs"]]
        bbl["n"]          += 1
        bbl["hits"]       += 1 if card["hit"] else 0
        bbl["sum_market"] += card["combined_market_prob"]
        bbl["sum_system"] += card["combined_system_conf"]


# ---- Main streaming loop -----------------------------------------------------

def run_analysis() -> dict:
    print(f"Streaming {UNIVERSE_PATH} ...")
    summary    = UniverseSummary()
    reach_inv  = ReachInvestigator()
    stable_inv = StableInvestigator()
    h1, h2, h3, h4, h5, h6, h7 = [Aggregator() for _ in range(7)]
    archetype_agg = Aggregator()

    n_processed = 0
    with open(UNIVERSE_PATH) as f:
        for line in f:
            card = json.loads(line)
            n_processed += 1
            bucket = card["bucket"]

            summary.add(card)
            reach_inv.add(card)
            stable_inv.add(card)

            for label in h1_prop_mix_subgroups(card):
                h1.add(("H1", bucket, label), card)
            for label in h2_cross_game_subgroups(card):
                h2.add(("H2", bucket, label), card)
            for label in h3_iron_floor_subgroups(card):
                h3.add(("H3", bucket, label), card)
            for label in h4_dispersion_subgroups(card):
                h4.add(("H4", bucket, label), card)
            for label in h5_same_team_subgroups(card):
                h5.add(("H5", bucket, label), card)
            for label in h6_conf_vs_market_subgroups(card):
                h6.add(("H6", bucket, label), card)
            for label in h7_per_player_subgroups(card):
                h7.add(("H7", bucket, label), card)

            for arch_id in ARCHETYPES:
                if matches_archetype(card, arch_id):
                    archetype_agg.add(("ARCH", bucket, arch_id), card)

            if n_processed % 100_000 == 0:
                print(f"  processed {n_processed:,} cards...")

    print(f"  total processed: {n_processed:,}")

    return {
        "universe":   summary,
        "stable":     stable_inv,
        "reach":      reach_inv,
        "h1":         h1.finalize(),
        "h2":         h2.finalize(),
        "h3":         h3.finalize(),
        "h4":         h4.finalize(),
        "h5":         h5.finalize(),
        "h6":         h6.finalize(),
        "h7":         h7.finalize(),
        "archetypes": archetype_agg.finalize(),
    }


# ---- Markdown rendering helpers ----------------------------------------------

def _pct(v: float) -> str:
    """Render a 0–1 float as percentage with 1 decimal (e.g. 0.3325 → '33.3%')."""
    return f"{v * 100:.1f}%"


def _delta(v: float) -> str:
    """Render a delta with explicit sign in pp."""
    return f"{v * 100:+.1f}pp"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _bucket_total_row(bucket: str, bt: dict) -> str:
    n  = bt["n"]
    if n == 0:
        return _row([bucket, "0", "—", "—", "—", "—", "—"])
    hr = bt["hits"] / n
    em = bt["sum_market"] / n
    es = bt["sum_system"] / n
    return _row([
        bucket,
        f"{n:,}",
        _pct(hr),
        _pct(em),
        _pct(es),
        _delta(hr - em),
        _delta(hr - es),
    ])


def _format_subset(label: str, stats: dict) -> str:
    """Render one row of a per-hypothesis sub-table."""
    n = stats["n"]
    if n < MIN_REPORTABLE_N:
        return _row([label, f"{n:,}", "—", "—", "—", "—", "— *insufficient_sample*"])
    return _row([
        label,
        f"{n:,}",
        _pct(stats["hit_rate"]),
        _pct(stats["expected_market"]),
        _pct(stats["expected_system"]),
        _delta(stats["delta_vs_market"]),
        _delta(stats["delta_vs_system"]),
    ])


def _hyp_section(
    hypothesis_id: str,
    title: str,
    finalized: dict,
    expected_subgroups: list[str],
) -> list[str]:
    """
    Render a hypothesis section: one heading + three sub-tables (per bucket).
    Within each sub-table, rows are in the order of `expected_subgroups`
    (any subgroup that didn't appear in the data is omitted; subgroups with
    n < MIN_REPORTABLE_N are flagged but kept).
    """
    out = [f"### {hypothesis_id}: {title}", ""]
    for bucket in BUCKETS:
        # Collect subgroups that appeared for this (hypothesis, bucket)
        rows_in_data = {
            key[2]: stats
            for key, stats in finalized.items()
            if key[0] == hypothesis_id and key[1] == bucket
        }
        if not rows_in_data:
            continue
        out.append(f"**{bucket} bucket**")
        out.append("")
        out.append(_row([
            "subgroup", "n", "actual_hit_rate",
            "expected_market", "expected_system",
            "delta_vs_market", "delta_vs_system",
        ]))
        out.append(_row(["---"] * 7))

        # Sort within bucket by delta_vs_market descending; insufficient_sample
        # rows go to the bottom (sort key uses -infinity proxy for those).
        def _sort_key(item):
            label, st = item
            if st["n"] < MIN_REPORTABLE_N:
                return (1, label)              # insufficient → bottom
            return (0, -st["delta_vs_market"])  # then by delta desc

        # Filter to subgroups in the expected_subgroups order or any extras
        ordered_keys = [s for s in expected_subgroups if s in rows_in_data]
        # append any extras not in expected list
        for k in rows_in_data:
            if k not in ordered_keys:
                ordered_keys.append(k)
        # Now sort by the key above
        ordered_pairs = sorted(
            [(k, rows_in_data[k]) for k in ordered_keys],
            key=_sort_key,
        )
        for label, stats in ordered_pairs:
            out.append(_format_subset(label, stats))
        out.append("")

    return out


# ---- Markdown emitter --------------------------------------------------------

def render_markdown(results: dict) -> str:
    summary    = results["universe"]
    stable_inv = results["stable"]
    reach_inv  = results["reach"]
    n_picks, n_dates = load_pick_pool_size()
    caveat_block = CAVEAT_TEMPLATE.format(n_picks=n_picks, n_dates=n_dates)

    md: list[str] = []

    # 1. Header & metadata
    md.append("# Parlay Research Hypothesis Analysis")
    md.append("")
    md.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    md.append("")
    md.append(f"- Source: `{UNIVERSE_PATH.relative_to(REPO_ROOT)}`")
    md.append(f"- Total cards processed: {summary.n_total:,}")
    md.append(f"- Min reportable subgroup size: n ≥ {MIN_REPORTABLE_N}")
    md.append("")

    # 2. Caveat block
    md.append("## Caveat")
    md.append("")
    md.append(caveat_block)
    md.append("")

    # 3. Universe-level summary table
    md.append("## 1. Universe-Level Summary")
    md.append("")
    md.append(_row([
        "bucket", "n", "actual_hit_rate",
        "expected_market", "expected_system",
        "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    for b in BUCKETS:
        md.append(_bucket_total_row(b, summary.bucket_totals[b]))
    # Cross-bucket totals row
    total_n   = sum(summary.bucket_totals[b]["n"] for b in BUCKETS)
    total_h   = sum(summary.bucket_totals[b]["hits"] for b in BUCKETS)
    total_sm  = sum(summary.bucket_totals[b]["sum_market"] for b in BUCKETS)
    total_ss  = sum(summary.bucket_totals[b]["sum_system"] for b in BUCKETS)
    if total_n > 0:
        hr = total_h / total_n
        em = total_sm / total_n
        es = total_ss / total_n
        md.append(_row([
            "**ALL**",
            f"**{total_n:,}**",
            f"**{_pct(hr)}**",
            f"**{_pct(em)}**",
            f"**{_pct(es)}**",
            f"**{_delta(hr - em)}**",
            f"**{_delta(hr - es)}**",
        ]))
    md.append("")

    # 4. Bucket × leg count
    md.append("## 2. Bucket × Leg Count")
    md.append("")
    leg_counts = sorted({
        L for b in BUCKETS for L in summary.bucket_by_legs[b].keys()
    })
    header_cells = ["leg_count"]
    for b in BUCKETS:
        header_cells.extend([f"{b} n", f"{b} hit_rate", f"{b} delta_vs_market"])
    md.append(_row(header_cells))
    md.append(_row(["---"] * len(header_cells)))
    for L in leg_counts:
        cells = [f"L={L}"]
        for b in BUCKETS:
            d = summary.bucket_by_legs[b].get(L)
            if d is None or d["n"] == 0:
                cells.extend(["0", "—", "—"])
            else:
                hr = d["hits"] / d["n"]
                em = d["sum_market"] / d["n"]
                cells.extend([f"{d['n']:,}", _pct(hr), _delta(hr - em)])
        md.append(_row(cells))
    md.append("")

    # 3. Stable bucket investigation (parallel to Reach below)
    md.append("## 3. Stable Bucket Investigation")
    md.append("")

    md.append("### 3a. Stable by Leg Count")
    md.append("")
    md.append(_row([
        "leg_count", "n", "actual_hit_rate",
        "expected_market", "expected_system",
        "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    s_by_legs = stable_inv.finalize_dict(stable_inv.by_legs)
    s_by_legs.sort(key=lambda x: x["key"])
    for row in s_by_legs:
        if row["n"] < MIN_REPORTABLE_N:
            md.append(_row([
                f"L={row['key']}", f"{row['n']:,}", "—", "—", "—", "—",
                "— *insufficient_sample*",
            ]))
        else:
            md.append(_row([
                f"L={row['key']}",
                f"{row['n']:,}",
                _pct(row["hit_rate"]),
                _pct(row["expected_market"]),
                _pct(row["expected_system"]),
                _delta(row["delta_vs_market"]),
                _delta(row["delta_vs_system"]),
            ]))
    md.append("")

    md.append("### 3b. Stable by combined_market_prob bin (0.01-wide)")
    md.append("")
    md.append(_row([
        "bin", "n", "actual_hit_rate",
        "expected_market", "expected_system",
        "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    s_by_bin = stable_inv.finalize_dict(stable_inv.by_market_bin)
    s_by_bin.sort(key=lambda x: x["key"])
    for row in s_by_bin:
        if row["n"] < MIN_REPORTABLE_N:
            md.append(_row([
                row["key"], f"{row['n']:,}", "—", "—", "—", "—",
                "— *insufficient_sample*",
            ]))
        else:
            md.append(_row([
                row["key"],
                f"{row['n']:,}",
                _pct(row["hit_rate"]),
                _pct(row["expected_market"]),
                _pct(row["expected_system"]),
                _delta(row["delta_vs_market"]),
                _delta(row["delta_vs_system"]),
            ]))
    md.append("")

    # 3c/3d: top 5 / bottom 5 single-hypothesis subgroups within Stable
    stable_subs: list[tuple] = []
    for hyp_key in ("h1", "h2", "h3", "h4", "h5", "h6", "h7"):
        for key, stats in results[hyp_key].items():
            if key[1] != "Stable":
                continue
            if stats["n"] < MIN_REPORTABLE_N:
                continue
            stable_subs.append((key[0], key[2], stats))
    stable_subs_top    = sorted(stable_subs, key=lambda x: -x[2]["delta_vs_market"])[:5]
    stable_subs_bottom = sorted(stable_subs, key=lambda x: x[2]["delta_vs_market"])[:5]

    md.append("### 3c. Stable — Top 5 Single-Hypothesis Subgroups (by delta_vs_market)")
    md.append("")
    md.append(_row([
        "hypothesis", "subgroup", "n", "actual_hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    for hid, label, st in stable_subs_top:
        md.append(_row([
            hid, label, f"{st['n']:,}",
            _pct(st["hit_rate"]),
            _pct(st["expected_market"]),
            _delta(st["delta_vs_market"]),
            _delta(st["delta_vs_system"]),
        ]))
    md.append("")

    md.append("### 3d. Stable — Bottom 5 Single-Hypothesis Subgroups (by delta_vs_market)")
    md.append("")
    md.append(_row([
        "hypothesis", "subgroup", "n", "actual_hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    for hid, label, st in stable_subs_bottom:
        md.append(_row([
            hid, label, f"{st['n']:,}",
            _pct(st["hit_rate"]),
            _pct(st["expected_market"]),
            _delta(st["delta_vs_market"]),
            _delta(st["delta_vs_system"]),
        ]))
    md.append("")

    # 4. Reach bucket investigation
    md.append("## 4. Reach Bucket Investigation")
    md.append("")

    md.append("### 4a. Reach by Leg Count")
    md.append("")
    md.append(_row([
        "leg_count", "n", "actual_hit_rate",
        "expected_market", "expected_system",
        "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    by_legs = reach_inv.finalize_dict(reach_inv.by_legs)
    by_legs.sort(key=lambda x: x["key"])
    for row in by_legs:
        if row["n"] < MIN_REPORTABLE_N:
            md.append(_row([
                f"L={row['key']}", f"{row['n']:,}", "—", "—", "—", "—",
                "— *insufficient_sample*",
            ]))
        else:
            md.append(_row([
                f"L={row['key']}",
                f"{row['n']:,}",
                _pct(row["hit_rate"]),
                _pct(row["expected_market"]),
                _pct(row["expected_system"]),
                _delta(row["delta_vs_market"]),
                _delta(row["delta_vs_system"]),
            ]))
    md.append("")

    md.append("### 4b. Reach by combined_market_prob bin (0.01-wide)")
    md.append("")
    md.append(_row([
        "bin", "n", "actual_hit_rate",
        "expected_market", "expected_system",
        "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    by_bin = reach_inv.finalize_dict(reach_inv.by_market_bin)
    by_bin.sort(key=lambda x: x["key"])
    for row in by_bin:
        if row["n"] < MIN_REPORTABLE_N:
            md.append(_row([
                row["key"], f"{row['n']:,}", "—", "—", "—", "—",
                "— *insufficient_sample*",
            ]))
        else:
            md.append(_row([
                row["key"],
                f"{row['n']:,}",
                _pct(row["hit_rate"]),
                _pct(row["expected_market"]),
                _pct(row["expected_system"]),
                _delta(row["delta_vs_market"]),
                _delta(row["delta_vs_system"]),
            ]))
    md.append("")

    # 4c/4d: top 5 / bottom 5 single-hypothesis subgroups within Reach
    reach_subs: list[tuple] = []
    for hyp_key in ("h1", "h2", "h3", "h4", "h5", "h6", "h7"):
        for key, stats in results[hyp_key].items():
            if key[1] != "Reach":
                continue
            if stats["n"] < MIN_REPORTABLE_N:
                continue
            reach_subs.append((key[0], key[2], stats))
    reach_subs_top    = sorted(reach_subs, key=lambda x: -x[2]["delta_vs_market"])[:5]
    reach_subs_bottom = sorted(reach_subs, key=lambda x: x[2]["delta_vs_market"])[:5]

    md.append("### 4c. Reach — Top 5 Single-Hypothesis Subgroups (by delta_vs_market)")
    md.append("")
    md.append(_row([
        "hypothesis", "subgroup", "n", "actual_hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    for hid, label, st in reach_subs_top:
        md.append(_row([
            hid, label, f"{st['n']:,}",
            _pct(st["hit_rate"]),
            _pct(st["expected_market"]),
            _delta(st["delta_vs_market"]),
            _delta(st["delta_vs_system"]),
        ]))
    md.append("")

    md.append("### 4d. Reach — Bottom 5 Single-Hypothesis Subgroups (by delta_vs_market)")
    md.append("")
    md.append(_row([
        "hypothesis", "subgroup", "n", "actual_hit_rate",
        "expected_market", "delta_vs_market", "delta_vs_system",
    ]))
    md.append(_row(["---"] * 7))
    for hid, label, st in reach_subs_bottom:
        md.append(_row([
            hid, label, f"{st['n']:,}",
            _pct(st["hit_rate"]),
            _pct(st["expected_market"]),
            _delta(st["delta_vs_market"]),
            _delta(st["delta_vs_system"]),
        ]))
    md.append("")

    # 5. Per-hypothesis sections H1-H7
    md.append("## 5. Per-Hypothesis Tables")
    md.append("")
    md.append(
        "Each row sorted by `delta_vs_market` descending within bucket. "
        "Rows with n<100 retain their position by label and are flagged "
        "*insufficient_sample*; they are excluded from the top/bottom rankings "
        "in section 7 but remain present here for reference."
    )
    md.append("")

    md.extend(_hyp_section(
        "H1", "Prop mix",
        results["h1"],
        ["PTS", "REB", "AST", "3PM", "mixed",
         "all_PTS", "all_REB", "all_AST", "all_3PM"],
    ))
    md.extend(_hyp_section(
        "H2", "Cross-game vs same-game",
        results["h2"],
        ["all_cross_game", "has_same_game",
         "max_per_game_2", "max_per_game_3plus"],
    ))
    md.extend(_hyp_section(
        "H3", "Iron_floor concentration",
        results["h3"],
        ["all_iron_floor", "two_plus_iron_floor_not_all",
         "one_iron_floor", "zero_iron_floor"],
    ))
    md.extend(_hyp_section(
        "H4", "Confidence dispersion",
        results["h4"],
        ["dispersion_lt_05", "dispersion_05_10",
         "dispersion_10_20", "dispersion_gte_20"],
    ))
    md.extend(_hyp_section(
        "H5", "Same-team concentration",
        results["h5"],
        ["all_different_teams", "one_team_2_legs", "one_team_3plus_legs"],
    ))
    md.extend(_hyp_section(
        "H6", "Confidence vs market delta",
        results["h6"],
        ["edge_large", "edge_medium", "edge_small", "system_pessimistic"],
    ))
    md.extend(_hyp_section(
        "H7", "Per-player concentration",
        results["h7"],
        ["all_different_players", "one_player_2_legs", "one_player_3plus_legs"],
    ))

    # 7. Compound archetypes
    md.append("## 6. Compound Archetypes")
    md.append("")
    md.append(
        "Pre-defined parlay-construction strategies. One table per bucket. "
        "Rows sorted by `delta_vs_market` descending."
    )
    md.append("")

    arch = results["archetypes"]
    for bucket in BUCKETS:
        rows_in_bucket = {
            key[2]: stats
            for key, stats in arch.items()
            if key[1] == bucket
        }
        if not rows_in_bucket:
            continue
        md.append(f"### {bucket} bucket — compound archetypes")
        md.append("")
        md.append(_row([
            "archetype", "description", "n", "actual_hit_rate",
            "expected_market", "delta_vs_market", "delta_vs_system",
        ]))
        md.append(_row(["---"] * 7))

        def _arch_sort_key(item):
            arch_id, st = item
            if st["n"] < MIN_REPORTABLE_N:
                return (1, arch_id)
            return (0, -st["delta_vs_market"])

        ordered = sorted(rows_in_bucket.items(), key=_arch_sort_key)
        for arch_id, st in ordered:
            desc = ARCHETYPE_DESCRIPTIONS.get(arch_id, "")
            n = st["n"]
            if n < MIN_REPORTABLE_N:
                md.append(_row([
                    arch_id, desc, f"{n:,}", "—", "—", "—",
                    "— *insufficient_sample*",
                ]))
            else:
                md.append(_row([
                    arch_id, desc, f"{n:,}",
                    _pct(st["hit_rate"]),
                    _pct(st["expected_market"]),
                    _delta(st["delta_vs_market"]),
                    _delta(st["delta_vs_system"]),
                ]))
        md.append("")

    # 8. Top 10 / Bottom 10 archetypes overall
    pool: list[tuple] = []
    # Single-hypothesis subgroups
    for hyp_key in ("h1", "h2", "h3", "h4", "h5", "h6", "h7"):
        for key, stats in results[hyp_key].items():
            if stats["n"] < MIN_REPORTABLE_N:
                continue
            pool.append((key[0], key[1], key[2], stats))
    # Compound archetypes
    for key, stats in results["archetypes"].items():
        if stats["n"] < MIN_REPORTABLE_N:
            continue
        pool.append(("ARCH", key[1], key[2], stats))

    top10 = sorted(pool, key=lambda x: -x[3]["delta_vs_market"])[:10]
    bot10 = sorted(pool, key=lambda x: x[3]["delta_vs_market"])[:10]

    md.append("## 7. Top 10 / Bottom 10 Archetypes (Universe)")
    md.append("")
    md.append("Pool: all single-hypothesis subgroups + compound archetypes with n ≥ 100.")
    md.append("")

    md.append("### 7a. Top 10 by delta_vs_market (descending)")
    md.append("")
    md.append(_row([
        "rank", "hypothesis", "bucket", "subgroup",
        "n", "actual_hit_rate", "delta_vs_market",
    ]))
    md.append(_row(["---"] * 7))
    for i, (hid, bucket, label, st) in enumerate(top10, 1):
        md.append(_row([
            str(i), hid, bucket, label,
            f"{st['n']:,}",
            _pct(st["hit_rate"]),
            _delta(st["delta_vs_market"]),
        ]))
    md.append("")

    md.append("### 7b. Bottom 10 by delta_vs_market (ascending)")
    md.append("")
    md.append(_row([
        "rank", "hypothesis", "bucket", "subgroup",
        "n", "actual_hit_rate", "delta_vs_market",
    ]))
    md.append(_row(["---"] * 7))
    for i, (hid, bucket, label, st) in enumerate(bot10, 1):
        md.append(_row([
            str(i), hid, bucket, label,
            f"{st['n']:,}",
            _pct(st["hit_rate"]),
            _delta(st["delta_vs_market"]),
        ]))
    md.append("")

    return "\n".join(md)


# ---- CLI entry point ---------------------------------------------------------

def main():
    results = run_analysis()
    markdown = render_markdown(results)
    OUTPUT_PATH.write_text(markdown)

    print()
    print(f"Wrote analysis report to {OUTPUT_PATH}")
    print(f"Total cards analyzed: {results['universe'].n_total:,}")
    print()
    print("Bucket headlines:")
    for b in BUCKETS:
        bt = results["universe"].bucket_totals[b]
        n  = bt["n"]
        if n == 0:
            continue
        hr = bt["hits"] / n
        em = bt["sum_market"] / n
        print(
            f"  {b:>5}: n={n:>10,}  hit_rate={hr:.1%}  "
            f"expected_market={em:.1%}  delta={hr - em:+.1%}"
        )


if __name__ == "__main__":
    main()
