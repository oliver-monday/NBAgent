#!/usr/bin/env python3
"""
NBAgent — CLV Analysis (read-only, one-off)

Decomposes Closing Line Value data across multiple dimensions to inform
whether CLV signal should drive system changes. Reads picks.json, writes
a Markdown report to data/clv_analysis_YYYY-MM-DD.md.

Usage:
    python tools/clv_analysis.py

No flags. No mutations. Idempotent. Safe to run multiple times.
"""

from __future__ import annotations

import json
import datetime as dt
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PT = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(PT).strftime("%Y-%m-%d")

PICKS_JSON  = DATA / "picks.json"
OUTPUT_PATH = DATA / f"clv_analysis_{TODAY_STR}.md"


# ── Filter + bucket helpers ───────────────────────────────────────────

def is_clv_pick(pick: dict) -> bool:
    """True if pick qualifies for CLV analysis (matches auditor filter)."""
    if pick.get("clv_pp") is None:
        return False
    if pick.get("result") not in ("HIT", "MISS"):
        return False
    if pick.get("voided") is True:
        return False
    return True


def direction_bucket(clv: float) -> str:
    if clv > 0.5:
        return "beat_close"
    if clv < -0.5:
        return "lost_close"
    return "no_movement"


def magnitude_bucket(clv: float) -> str:
    a = abs(clv)
    if a <= 0.5:
        return "no_move"
    if a <= 2.0:
        return "small"
    if a <= 5.0:
        return "medium"
    return "large"


def confidence_band(conf) -> str | None:
    if conf is None:
        return None
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return None
    if 70 <= c <= 75:
        return "70-75"
    if 76 <= c <= 80:
        return "76-80"
    if 81 <= c <= 85:
        return "81-85"
    if c >= 86:
        return "86+"
    return None  # below floor — excluded


# ── Aggregation primitives ────────────────────────────────────────────

def rollup_cell(picks: list[dict]) -> dict:
    """
    Compute the standard CLV rollup over a list of CLV-qualified picks.
    Returns a dict mirroring audit_summary.clv_summary fields plus
    `hit_rate_pct` (overall) and per-bucket hit rates.
    """
    n = len(picks)
    if n == 0:
        return {"n": 0}
    beat = [p for p in picks if p["clv_pp"] > 0.5]
    lost = [p for p in picks if p["clv_pp"] < -0.5]
    nom  = [p for p in picks if abs(p["clv_pp"]) <= 0.5]
    avg  = round(sum(p["clv_pp"] for p in picks) / n, 2)
    hits = sum(1 for p in picks if p["result"] == "HIT")
    return {
        "n":             n,
        "avg_clv_pp":    avg,
        "hit_rate_pct":  round(hits / n * 100, 1),
        "beat_close":    len(beat),
        "lost_close":    len(lost),
        "no_movement":   len(nom),
        "beat_hr_pct":   round(sum(1 for p in beat if p["result"] == "HIT") / len(beat) * 100, 1) if beat else None,
        "lost_hr_pct":   round(sum(1 for p in lost if p["result"] == "HIT") / len(lost) * 100, 1) if lost else None,
        "nomove_hr_pct": round(sum(1 for p in nom  if p["result"] == "HIT") / len(nom)  * 100, 1) if nom else None,
    }


def directional_cell(picks: list[dict]) -> dict:
    """Reduced rollup for magnitude × direction sub-splits."""
    n = len(picks)
    if n == 0:
        return {"n": 0, "avg_clv_pp": None, "hit_rate_pct": None}
    avg = round(sum(p["clv_pp"] for p in picks) / n, 2)
    hits = sum(1 for p in picks if p["result"] == "HIT")
    return {
        "n":            n,
        "avg_clv_pp":   avg,
        "hit_rate_pct": round(hits / n * 100, 1),
    }


# ── Breakdowns ────────────────────────────────────────────────────────

def build_prop_type_breakdown(picks: list[dict]) -> dict:
    out = {}
    for prop in ("PTS", "REB", "AST", "3PM"):
        subset = [p for p in picks if p.get("prop_type") == prop]
        out[prop] = rollup_cell(subset)
    return out


def build_confidence_band_breakdown(picks: list[dict]) -> dict:
    out = {b: [] for b in ("70-75", "76-80", "81-85", "86+")}
    excluded = 0
    for p in picks:
        band = confidence_band(p.get("confidence_pct"))
        if band is None:
            excluded += 1
            continue
        out[band].append(p)
    cells = {b: rollup_cell(out[b]) for b in out}
    cells["_excluded"] = excluded
    return cells


def build_magnitude_breakdown(picks: list[dict]) -> dict:
    by_mag = defaultdict(list)
    by_mag_dir = defaultdict(list)
    for p in picks:
        mag = magnitude_bucket(p["clv_pp"])
        by_mag[mag].append(p)
        if mag == "no_move":
            continue
        # Directional split for non-no_move buckets
        d = "beat" if p["clv_pp"] > 0 else "lost"
        by_mag_dir[f"{mag}_{d}"].append(p)

    out = {}
    for bucket in ("no_move", "small", "medium", "large"):
        out[bucket] = rollup_cell(by_mag[bucket])
    for key in ("small_beat", "small_lost", "medium_beat", "medium_lost", "large_beat", "large_lost"):
        out[key] = directional_cell(by_mag_dir[key])
    return out


def build_miss_classification_breakdown(picks: list[dict]) -> dict:
    """
    Group misses by miss_classification. Within each group compute the
    directional split (beat / lost / no_move counts) plus avg_clv_pp.
    """
    misses = [p for p in picks if p["result"] == "MISS"]
    by_cls = defaultdict(list)
    for p in misses:
        cls = p.get("miss_classification") or "unclassified"
        by_cls[cls].append(p)

    out = {}
    for cls, group in by_cls.items():
        n = len(group)
        beat = sum(1 for p in group if p["clv_pp"] > 0.5)
        lost = sum(1 for p in group if p["clv_pp"] < -0.5)
        nomv = sum(1 for p in group if abs(p["clv_pp"]) <= 0.5)
        avg  = round(sum(p["clv_pp"] for p in group) / n, 2) if n else None
        out[cls] = {
            "n_misses":    n,
            "beat_pct":    round(beat / n * 100, 1) if n else None,
            "lost_pct":    round(lost / n * 100, 1) if n else None,
            "nomove_pct":  round(nomv / n * 100, 1) if n else None,
            "avg_clv_pp":  avg,
        }
    return out


def build_per_player_breakdown(picks: list[dict], min_picks: int = 5) -> dict:
    by_player = defaultdict(list)
    for p in picks:
        name = p.get("player_name") or "?"
        by_player[name].append(p)

    n_total = len(by_player)
    qualified = []
    for name, group in by_player.items():
        if len(group) < min_picks:
            continue
        n = len(group)
        avg = round(sum(p["clv_pp"] for p in group) / n, 2)
        hits = sum(1 for p in group if p["result"] == "HIT")
        beat = sum(1 for p in group if p["clv_pp"] > 0.5)
        lost = sum(1 for p in group if p["clv_pp"] < -0.5)
        nomv = sum(1 for p in group if abs(p["clv_pp"]) <= 0.5)
        qualified.append({
            "player_name":  name,
            "n":            n,
            "avg_clv_pp":   avg,
            "hit_rate_pct": round(hits / n * 100, 1),
            "beat_close":   beat,
            "lost_close":   lost,
            "no_movement":  nomv,
        })

    top    = sorted(qualified, key=lambda x: x["avg_clv_pp"], reverse=True)[:10]
    bottom = sorted(qualified, key=lambda x: x["avg_clv_pp"])[:10]
    return {
        "top_clv":              top,
        "bottom_clv":           bottom,
        "n_players_qualifying": len(qualified),
        "n_players_total":      n_total,
    }


# ── Renderer ──────────────────────────────────────────────────────────

def _fmt_int(x):    return "—" if x is None else f"{int(x)}"
def _fmt_pct(x):    return "—" if x is None else f"{x:.1f}%"
def _fmt_clv(x):    return "—" if x is None else f"{x:+.2f}"
def _fmt_pct_raw(x): return "—" if x is None else f"{x:.1f}"


def _row_rollup(label: str, c: dict) -> str:
    if c.get("n", 0) == 0:
        return f"| {label} | 0 | — | — | — | — | — | — | — | — |"
    return (
        f"| {label} "
        f"| {c['n']} "
        f"| {_fmt_clv(c['avg_clv_pp'])} "
        f"| {_fmt_pct_raw(c['hit_rate_pct'])} "
        f"| {c['beat_close']} "
        f"| {_fmt_pct_raw(c['beat_hr_pct'])} "
        f"| {c['lost_close']} "
        f"| {_fmt_pct_raw(c['lost_hr_pct'])} "
        f"| {c['no_movement']} "
        f"| {_fmt_pct_raw(c['nomove_hr_pct'])} |"
    )


def _row_dir(bucket: str, direction_label: str, c: dict) -> str:
    if c.get("n", 0) == 0:
        return f"| {bucket} | {direction_label} | 0 | — | — |"
    return (
        f"| {bucket} | {direction_label} "
        f"| {c['n']} "
        f"| {_fmt_clv(c['avg_clv_pp'])} "
        f"| {_fmt_pct_raw(c['hit_rate_pct'])} |"
    )


def render_report(*, clv_picks, all_picks_count, excluded_voided,
                  headline, by_prop, by_band, by_mag, by_miss, by_player) -> str:
    n = headline["n"]
    coverage = (n / all_picks_count * 100) if all_picks_count else 0.0
    timestamp = dt.datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S %Z")

    lines: list[str] = []
    a = lines.append

    a(f"# CLV Analysis — {TODAY_STR}")
    a("")
    a("Read-only retrospective on Closing Line Value across all graded picks")
    a("with morning + pretip odds data. Generated by `tools/clv_analysis.py`.")
    a("")
    a("## Coverage")
    a("")
    a(f"- Total picks in `picks.json`: {all_picks_count}")
    a(f"- CLV-qualified picks (clv_pp set, graded HIT/MISS, not voided): {n}")
    a(f"- Coverage rate: {coverage:.1f}%")
    a(f"- Voided picks excluded with clv_pp set (defensive): {excluded_voided}")
    a("")
    a("## Headline (sanity check vs `audit_summary.json.clv_summary`)")
    a("")
    a("| Metric | Value |")
    a("|---|---|")
    a(f"| n | {n} |")
    a(f"| avg_clv_pp | {_fmt_clv(headline['avg_clv_pp'])} |")
    a(f"| Overall hit rate | {_fmt_pct_raw(headline['hit_rate_pct'])}% |")
    a(f"| beat_close (>+0.5pp) | {headline['beat_close']} ({headline['beat_close']/n*100:.1f}%) |")
    a(f"| lost_close (<−0.5pp) | {headline['lost_close']} ({headline['lost_close']/n*100:.1f}%) |")
    a(f"| no_movement (\\|clv\\|≤0.5) | {headline['no_movement']} ({headline['no_movement']/n*100:.1f}%) |")
    a(f"| beat_close hit rate | {_fmt_pct_raw(headline['beat_hr_pct'])}% |")
    a(f"| lost_close hit rate | {_fmt_pct_raw(headline['lost_hr_pct'])}% |")
    a(f"| no_movement hit rate | {_fmt_pct_raw(headline['nomove_hr_pct'])}% |")
    a("")
    a("## Breakdown 1: By prop type")
    a("")
    a("| Prop | n | avg_clv | hit% | beat | beat_hr% | lost | lost_hr% | nomove | nomove_hr% |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for prop in ("PTS", "REB", "AST", "3PM"):
        a(_row_rollup(prop, by_prop[prop]))
    a("")
    a("## Breakdown 2: By confidence band")
    a("")
    a("| Band | n | avg_clv | hit% | beat | beat_hr% | lost | lost_hr% | nomove | nomove_hr% |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for band in ("70-75", "76-80", "81-85", "86+"):
        a(_row_rollup(band, by_band[band]))
    excl = by_band.get("_excluded", 0)
    if excl:
        a("")
        a(f"*Footnote: {excl} picks excluded due to confidence_pct outside the 70+ range.*")
    a("")
    a("## Breakdown 3: By CLV magnitude")
    a("")
    a("| Bucket | Threshold | n | avg_clv | hit% |")
    a("|---|---|---:|---:|---:|")
    bucket_labels = [
        ("no_move", "|clv| ≤ 0.5"),
        ("small",   "0.5 < |clv| ≤ 2.0"),
        ("medium",  "2.0 < |clv| ≤ 5.0"),
        ("large",   "|clv| > 5.0"),
    ]
    for bucket, thr in bucket_labels:
        c = by_mag[bucket]
        if c.get("n", 0) == 0:
            a(f"| {bucket} | {thr} | 0 | — | — |")
        else:
            a(f"| {bucket} | {thr} | {c['n']} | {_fmt_clv(c['avg_clv_pp'])} | {_fmt_pct_raw(c['hit_rate_pct'])} |")
    a("")
    a("### Directional split")
    a("")
    a("| Bucket | direction | n | avg_clv | hit% |")
    a("|---|---|---:|---:|---:|")
    a(_row_dir("small",  "beat (+0.5 to +2.0)",  by_mag["small_beat"]))
    a(_row_dir("small",  "lost (−2.0 to −0.5)",  by_mag["small_lost"]))
    a(_row_dir("medium", "beat (+2.0 to +5.0)",  by_mag["medium_beat"]))
    a(_row_dir("medium", "lost (−5.0 to −2.0)",  by_mag["medium_lost"]))
    a(_row_dir("large",  "beat (>+5.0)",         by_mag["large_beat"]))
    a(_row_dir("large",  "lost (<−5.0)",         by_mag["large_lost"]))
    a("")
    a("## Breakdown 4: Miss classification co-occurrence")
    a("")
    a("| classification | n_misses | beat% | lost% | no_move% | avg_clv |")
    a("|---|---:|---:|---:|---:|---:|")
    # Stable ordering: known classifications first, then alphabetical
    known_order = ["selection_error", "model_gap_rule", "model_gap_signal",
                   "variance", "injury_event", "workflow_gap", "unclassified"]
    seen_keys = set(by_miss.keys())
    ordered = [k for k in known_order if k in seen_keys] + \
              sorted(k for k in seen_keys if k not in known_order)
    for cls in ordered:
        m = by_miss[cls]
        a(
            f"| {cls} "
            f"| {m['n_misses']} "
            f"| {_fmt_pct_raw(m['beat_pct'])} "
            f"| {_fmt_pct_raw(m['lost_pct'])} "
            f"| {_fmt_pct_raw(m['nomove_pct'])} "
            f"| {_fmt_clv(m['avg_clv_pp'])} |"
        )
    a("")
    a("## Breakdown 5: Per-player CLV (min 5 picks)")
    a("")
    a(f"Total distinct players in CLV-qualified set: {by_player['n_players_total']}")
    a(f"Players with ≥5 CLV picks: {by_player['n_players_qualifying']}")
    a("")
    a("### Top 10 — strongest beat-the-close")
    a("")
    a("| Player | n | avg_clv | hit% | beat | lost | nomove |")
    a("|---|---:|---:|---:|---:|---:|---:|")
    for r in by_player["top_clv"]:
        a(
            f"| {r['player_name']} "
            f"| {r['n']} "
            f"| {_fmt_clv(r['avg_clv_pp'])} "
            f"| {_fmt_pct_raw(r['hit_rate_pct'])} "
            f"| {r['beat_close']} "
            f"| {r['lost_close']} "
            f"| {r['no_movement']} |"
        )
    a("")
    a("### Bottom 10 — strongest lost-the-close")
    a("")
    a("| Player | n | avg_clv | hit% | beat | lost | nomove |")
    a("|---|---:|---:|---:|---:|---:|---:|")
    for r in by_player["bottom_clv"]:
        a(
            f"| {r['player_name']} "
            f"| {r['n']} "
            f"| {_fmt_clv(r['avg_clv_pp'])} "
            f"| {_fmt_pct_raw(r['hit_rate_pct'])} "
            f"| {r['beat_close']} "
            f"| {r['lost_close']} "
            f"| {r['no_movement']} |"
        )
    a("")
    a("---")
    a(f"*Generated {timestamp} from {PICKS_JSON.name}. Read-only — no system state modified.*")
    a("")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    if not PICKS_JSON.exists():
        print(f"[clv_analysis] ERROR: {PICKS_JSON} not found")
        return

    with open(PICKS_JSON) as f:
        all_picks = json.load(f)

    clv_picks = [p for p in all_picks if is_clv_pick(p)]
    excluded_voided = sum(
        1 for p in all_picks
        if p.get("voided") is True and p.get("clv_pp") is not None
    )

    headline  = rollup_cell(clv_picks)
    by_prop   = build_prop_type_breakdown(clv_picks)
    by_band   = build_confidence_band_breakdown(clv_picks)
    by_mag    = build_magnitude_breakdown(clv_picks)
    by_miss   = build_miss_classification_breakdown(clv_picks)
    by_player = build_per_player_breakdown(clv_picks, min_picks=5)

    md = render_report(
        clv_picks=clv_picks,
        all_picks_count=len(all_picks),
        excluded_voided=excluded_voided,
        headline=headline,
        by_prop=by_prop,
        by_band=by_band,
        by_mag=by_mag,
        by_miss=by_miss,
        by_player=by_player,
    )

    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"[clv_analysis] Wrote {OUTPUT_PATH} — {len(clv_picks)} CLV picks analyzed")
    print(
        f"[clv_analysis] Headline: avg_clv={headline['avg_clv_pp']:+.2f}pp, "
        f"beat={headline['beat_close']} ({headline['beat_hr_pct']}%), "
        f"lost={headline['lost_close']} ({headline['lost_hr_pct']}%), "
        f"no_move={headline['no_movement']} ({headline['nomove_hr_pct']}%)"
    )


if __name__ == "__main__":
    main()
