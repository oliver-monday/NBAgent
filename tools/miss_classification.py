#!/usr/bin/env python3
"""
tools/miss_classification.py — Miss Classification Population Analysis

Read-only descriptive analysis over data/audit_log.json. Produces
data/miss_classification_report.md, a planning document that surfaces
population-level patterns within graded miss data.

This is decision input for the next major workstream choice (multi-agent
expert architecture vs new data pipelines vs rule additions vs calibration
recalibration). It is NOT a directive — no rules ship from this script.

Usage:
    python tools/miss_classification.py

Output:
    data/miss_classification_report.md

Idempotent: running twice produces byte-identical output (the audit-log
date range is the version anchor; no clock-time stamps appear in the body).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent.parent
DATA       = ROOT / "data"
AUDIT_LOG  = DATA / "audit_log.json"
PICKS_JSON = DATA / "picks.json"
REPORT_OUT = DATA / "miss_classification_report.md"

# Confidence-band definitions (v2). Lower-bound inclusive, upper-bound exclusive
# except the open-ended top band. Picks with confidence_pct < 70 → None (only
# 3 picks ever per data audit; graceful-null).
CONFIDENCE_BANDS = ["70_74", "75_79", "80_84", "85_89", "90_plus"]
# Midpoint hit-rate "expected" for each band — used to compute overshoot.
# 90_plus is open-ended; use 95.0 as the midpoint of [90, 100).
BAND_EXPECTED_HR = {
    "70_74":  72.5,
    "75_79":  77.5,
    "80_84":  82.5,
    "85_89":  87.5,
    "90_plus": 95.0,
}

# ── Taxonomy mappings ──────────────────────────────────────────────────────────
# 7 classifications observed in production. `model_gap` is the legacy alias for
# `model_gap_signal`; bucketed identically but reported separately so audit-time
# taxonomy drift remains visible.
CLASSIFICATION_TO_BUCKET: dict[str, str] = {
    "selection_error":  "catchable_with_current_signals",
    "model_gap_signal": "catchable_with_new_data",
    "model_gap":        "catchable_with_new_data",   # legacy alias
    "model_gap_rule":   "deterministic_rule_catchable",
    "workflow_gap":     "deterministic_rule_catchable",
    "variance":         "inherent_variance",
    "injury_event":     "inherent_variance",
}

BUCKET_TO_CLASSES: dict[str, list[str]] = {
    "catchable_with_current_signals": ["selection_error"],
    "catchable_with_new_data":        ["model_gap_signal", "model_gap"],
    "deterministic_rule_catchable":   ["model_gap_rule", "workflow_gap"],
    "inherent_variance":              ["variance", "injury_event"],
}

# 4-bucket display order (largest-to-smallest by intuitive rule-leverage)
BUCKET_ORDER = [
    "catchable_with_current_signals",
    "deterministic_rule_catchable",
    "catchable_with_new_data",
    "inherent_variance",
]

# Stable display order for the 7 classes (descending by initial population observation)
CLASS_ORDER = [
    "variance", "model_gap_rule", "model_gap_signal", "model_gap",
    "injury_event", "workflow_gap", "selection_error",
]

# v2 keyword groups for root_cause pattern extraction. Causal-phrase tightening
# (active phrasing implying causal attribution, not mere mention) plus negation
# guards (see detect_keywords). Two patterns added vs v1: near_miss_variance
# and structural_ceiling — they pair with the miss-margin distribution data to
# distinguish razor variance from wrong-bucket variance.
KEYWORD_PATTERNS: dict[str, list[str]] = {
    "blowout": [
        "blowout context",
        "garbage time",
        "minutes restriction",
        "pulled at",
        "pulled in q",
        "spread blowout",
        "lopsided",
    ],
    "fg_margin_thin": [
        "FG_MARGIN_THIN",
        "FG_MARGIN_NEG",
        "shooting margin thin",
        "below the safety floor",
        "below the 10% safety",
    ],
    "fg_cold": [
        "FG_COLD",
        "cold shooting streak",
        "shooting cold",
    ],
    "suppressor_cross_prop": [
        "PHI suppressor",
        "HOU suppressor",
        "LAL suppressor",
        "scheme suppressor",
        "cross-prop suppressor",
        "suppressor leakage",
    ],
    "foul_trouble": [
        "foul trouble",
        "fouled out",
        "early fouls limited",
        "in foul trouble",
    ],
    "injury_exit": [
        "injury_exit",
        "exited the game",
        "left the game",
        "did not return",
        "MRI pending",
        "MRI results",
    ],
    "rebounding_competition": [
        "rebounding competition",
        "opposing center grabbed",
        "boards split with",
        "competing with Gobert",
    ],
    "minutes_compression": [
        "minutes restriction",
        "limited minutes",
        "pulled early",
        "minutes pulled",
        "rotation tightening",
    ],
    "h2h_thin": [
        "H2H sample is thin",
        "first playoff meeting",
        "small H2H sample",
        "limited H2H",
    ],
    "tier_walk_market": [
        "no FanDuel market",
        "no T10 market",
        "no T15 market",
        "no T20 market",
        "tier walk blocked",
        "walk to T",
        "step-down blocked",
    ],
    "playoff_intensity": [
        "playoff intensity",
        "elimination intensity",
        "rotation tightening for playoffs",
        "playoff rotation",
    ],
    "volatile_tag": [
        "VOLATILE+",
        "volatile distribution",
        "volatile signal flagged",
        "volatility penalty applied",
    ],
    "near_miss_variance": [
        "missed by 1",
        "missed by 2",
        "missed by exactly",
        "by exactly 1",
        "by exactly 2",
        "near-miss",
    ],
    "structural_ceiling": [
        "ceiling miss",
        "structural ceiling",
        "ceiling not reached",
        "well below the threshold",
        "missed by a wide margin",
    ],
}

# Negation markers for v2 detect_keywords — match-position must NOT be within
# 30 characters after one of these. Matches the auditor's structured Step 0
# negation phrasing ("No blowout context", "this is not a foul trouble", etc.)
# without over-suppressing legitimate co-occurrences.
NEGATION_MARKERS = [
    "no ", "not ", "without ", "never ", "absent",
    "isn't", "wasn't", "didn't",
]
NEGATION_LOOKBACK = 30

# Display order for keyword patterns (alphabetical for stable output)
PATTERN_ORDER = sorted(KEYWORD_PATTERNS.keys())

PLAYOFF_START = date(2026, 4, 18)
MIN_CLASS_N = 5  # below this n, keyword-pattern table is suppressed


# ── Loading ────────────────────────────────────────────────────────────────────

def _confidence_band(c) -> str | None:
    """Derive band label from confidence_pct. Returns None for <70 or null."""
    if c is None:
        return None
    try:
        cf = float(c)
    except (TypeError, ValueError):
        return None
    if cf < 70:
        return None
    if cf < 75:
        return "70_74"
    if cf < 80:
        return "75_79"
    if cf < 85:
        return "80_84"
    if cf < 90:
        return "85_89"
    return "90_plus"


def _is_high_conviction(m) -> bool | None:
    """Derive is_high_conviction flag from market_implied_prob (>= 85.0)."""
    if m is None:
        return None
    try:
        return float(m) >= 85.0
    except (TypeError, ValueError):
        return None


def load_picks_lookup() -> dict:
    """Build a dict keyed by (date, player_name, prop_type, pick_value) →
    enriched fields {confidence_pct, confidence_band, market_implied_prob,
    is_high_conviction}. Includes all picks (graded, voided, ungraded) since
    this lookup is for enrichment, not filtering. Join key is unique across
    picks.json (verified)."""
    with PICKS_JSON.open() as f:
        picks = json.load(f)
    lookup = {}
    for p in picks:
        key = (p.get("date"), p.get("player_name"),
               p.get("prop_type"), p.get("pick_value"))
        lookup[key] = {
            "confidence_pct":      p.get("confidence_pct"),
            "confidence_band":     _confidence_band(p.get("confidence_pct")),
            "market_implied_prob": p.get("market_implied_prob"),
            "is_high_conviction":  _is_high_conviction(p.get("market_implied_prob")),
        }
    return lookup


def load_picks_baseline() -> pd.DataFrame:
    """Return DataFrame of graded picks (HIT or MISS, not voided) for volume
    baselines. This is the rate denominator for all v2 miss-rate computations.
    Excludes voided, NO_DATA, and null-result picks.

    Columns: date, player_name, prop_type, pick_value, confidence_pct,
             confidence_band, market_implied_prob, is_high_conviction,
             result, is_playoff.
    """
    with PICKS_JSON.open() as f:
        picks = json.load(f)
    rows = []
    for p in picks:
        if p.get("voided"):
            continue
        if p.get("result") not in ("HIT", "MISS"):
            continue
        d = p.get("date", "")
        try:
            ymd = date.fromisoformat(d) if d else None
        except ValueError:
            ymd = None
        rows.append({
            "date":                d,
            "player_name":         p.get("player_name", ""),
            "prop_type":           p.get("prop_type", ""),
            "pick_value":          p.get("pick_value"),
            "confidence_pct":      p.get("confidence_pct"),
            "confidence_band":     _confidence_band(p.get("confidence_pct")),
            "market_implied_prob": p.get("market_implied_prob"),
            "is_high_conviction":  _is_high_conviction(p.get("market_implied_prob")),
            "result":              p.get("result"),
            "is_playoff":          (ymd is not None and ymd >= PLAYOFF_START),
        })
    return pd.DataFrame(rows)


def load_misses() -> pd.DataFrame:
    """Load audit_log.json, flatten miss_details across all entries, attach the
    entry date to each miss row. Excludes rows with null/empty miss_classification.
    v2: enriches each row with picks.json fields (confidence_pct, confidence_band,
    market_implied_prob, is_high_conviction) via the (date, player, prop, tier)
    join key. Logs a single warning to stdout if any audit miss rows fail to
    match picks.json.

    Returns DataFrame with columns:
        date, player_name, prop_type, pick_value, actual_value,
        miss_classification, bucket, root_cause, is_playoff, miss_margin,
        confidence_pct, confidence_band, market_implied_prob, is_high_conviction.
    """
    raw = json.loads(AUDIT_LOG.read_text())
    picks_lookup = load_picks_lookup()
    rows: list[dict] = []
    unmatched = 0
    for entry in raw:
        d = entry.get("date", "")
        for m in entry.get("miss_details", []) or []:
            cls = m.get("miss_classification")
            if not cls:  # excludes None and "" — ungraded
                continue
            actual = m.get("actual_value")
            pick_v = m.get("pick_value")
            try:
                margin = (float(pick_v) - float(actual)) if (pick_v is not None and actual is not None) else None
            except (TypeError, ValueError):
                margin = None
            try:
                ymd = date.fromisoformat(d) if d else None
            except ValueError:
                ymd = None
            row = {
                "date":                d,
                "player_name":         m.get("player_name", ""),
                "prop_type":           m.get("prop_type", ""),
                "pick_value":          pick_v,
                "actual_value":        actual,
                "miss_classification": cls,
                "bucket":              CLASSIFICATION_TO_BUCKET.get(cls, "unknown"),
                "root_cause":          m.get("root_cause", "") or "",
                "is_playoff":          (ymd is not None and ymd >= PLAYOFF_START),
                "miss_margin":         margin,
            }
            key = (d, row["player_name"], row["prop_type"], pick_v)
            enrichment = picks_lookup.get(key)
            if enrichment is None:
                unmatched += 1
                row.update({
                    "confidence_pct":      None,
                    "confidence_band":     None,
                    "market_implied_prob": None,
                    "is_high_conviction":  None,
                })
            else:
                row.update(enrichment)
            rows.append(row)
    if unmatched > 0:
        print(
            f"[miss_classification] Warning: {unmatched} audit miss rows did not "
            f"match picks.json on (date, player, prop, tier)"
        )
    return pd.DataFrame(rows)


# ── Pattern detection ──────────────────────────────────────────────────────────

def detect_keywords(root_cause: str) -> list[str]:
    """v2: causal-phrase matching with negation guards.

    A pattern matches if any of its phrase variants appears in root_cause AND
    the match position is NOT within `NEGATION_LOOKBACK` characters after a
    negation marker (e.g., "No blowout context" suppresses the blowout match;
    "this is not a foul trouble" suppresses foul_trouble; etc.).

    Returns sorted list of pattern keys that matched. A single root_cause text
    can match multiple keys; counts are independent across patterns. At most
    one count per pattern_key per text — duplicate phrase hits don't double-count.
    """
    if not root_cause:
        return []
    text = root_cause.lower()
    matched: list[str] = []
    for key, phrases in KEYWORD_PATTERNS.items():
        found = False
        for phrase in phrases:
            phrase_lower = phrase.lower()
            idx = text.find(phrase_lower)
            while idx != -1:
                window_start = max(0, idx - NEGATION_LOOKBACK)
                window = text[window_start:idx]
                if not any(neg in window for neg in NEGATION_MARKERS):
                    matched.append(key)
                    found = True
                    break  # one match per pattern_key per text is enough
                idx = text.find(phrase_lower, idx + 1)
            if found:
                break
    return sorted(matched)


# ── Markdown helpers ───────────────────────────────────────────────────────────

def _pct(n: int, total: int) -> str:
    if total <= 0:
        return "—"
    return f"{(100.0 * n / total):.1f}%"


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    """Produce a GitHub-flavored markdown table. All cells stringified."""
    sep = "|" + "|".join(["---"] * len(header)) + "|"
    head = "|" + "|".join(header) + "|"
    body = "\n".join("|" + "|".join(str(c) for c in r) + "|" for r in rows)
    return "\n".join([head, sep, body])


# ── Sections ───────────────────────────────────────────────────────────────────

def section_overview(df: pd.DataFrame, baseline: pd.DataFrame) -> str:
    dates = sorted(df["date"].dropna().unique().tolist())
    date_min = dates[0] if dates else "—"
    date_max = dates[-1] if dates else "—"
    n_unique_dates = len(dates)
    total = len(df)
    baseline_total = len(baseline)
    matched = int(df["confidence_pct"].notna().sum())
    match_pct = (100.0 * matched / total) if total > 0 else 0.0

    # Re-derive null-excluded count from raw audit log for transparency
    raw = json.loads(AUDIT_LOG.read_text())
    raw_total = sum(len(e.get("miss_details", []) or []) for e in raw)
    n_null = raw_total - total

    body = (
        "## 1. Overview\n\n"
        "Population characterization of graded miss data. This is descriptive "
        "analysis only — no rules ship from this report. Output informs the "
        "offseason workstream-choice conversation.\n\n"
        f"- Date range: **{date_min} → {date_max}**\n"
        f"- Audit entries (unique slate dates): **{n_unique_dates}**\n"
        f"- Total miss rows analyzed: **{total}**\n"
        f"- Null/ungraded `miss_classification` rows excluded: **{n_null}**\n"
        f"- Total graded picks in baseline (denominator for miss rates): **{baseline_total}**\n"
        f"- Audit miss rows successfully joined to picks.json: **{matched} of {total} ({match_pct:.1f}%)**\n"
        "- Keyword detection: **v2** with negation guards (30-char lookback) and causal-phrase tightening\n"
        "- `model_gap` (legacy alias) and `model_gap_signal` are bucketed identically "
        "as `catchable_with_new_data` but reported separately so audit-time "
        "taxonomy drift remains visible.\n"
    )
    return body


def section_taxonomy_breakdown(df: pd.DataFrame) -> str:
    total = len(df)
    counts = df["miss_classification"].value_counts().to_dict()
    rows = []
    for cls in CLASS_ORDER:
        n = counts.get(cls, 0)
        rows.append([cls, str(n), _pct(n, total)])
    rows.append(["**TOTAL**", f"**{total}**", "**100.0%**"])
    table = _md_table(["classification", "count", "% of total"], rows)
    return (
        "## 2. Taxonomy Breakdown (7 classes)\n\n"
        "Counts and percentages by raw `miss_classification` value. "
        "`model_gap` is the legacy alias for `model_gap_signal`.\n\n"
        + table
    )


def section_four_bucket_rollup(df: pd.DataFrame) -> str:
    total = len(df)
    rows = []
    for bucket in BUCKET_ORDER:
        classes = BUCKET_TO_CLASSES[bucket]
        n = int(df[df["bucket"] == bucket].shape[0])
        rows.append([
            bucket,
            ", ".join(classes),
            str(n),
            _pct(n, total),
        ])
    rows.append(["**TOTAL**", "—", f"**{total}**", "**100.0%**"])
    table = _md_table(
        ["roadmap bucket", "underlying classes", "count", "% of total"],
        rows,
    )
    return (
        "## 3. Four-Bucket Roll-up (Roadmap View)\n\n"
        "Roll-up of the 7-class taxonomy into the four buckets named in "
        "`docs/ROADMAP_active.md`. Sums must equal the 7-class total.\n\n"
        + table
    )


def section_keyword_patterns_within_bucket(df: pd.DataFrame) -> str:
    body = [
        "## 4. Keyword Pattern Frequency Within Each Classification\n\n"
        "For each classification with `n >= 5`, the top-5 keyword patterns. "
        "v2 detection: causal-phrase matching with negation guards (a phrase "
        "match is suppressed if a negation marker — `no`, `not`, `without`, "
        "`never`, `absent`, `isn't`, `wasn't`, `didn't` — appears within 30 "
        "characters before the match position). A single miss can match multiple "
        "patterns; counts are independent. This is the core analytical output — "
        "pattern dominance within a class points to the highest-leverage "
        "workstream for that class."
    ]
    for cls in CLASS_ORDER:
        sub = df[df["miss_classification"] == cls]
        n = len(sub)
        body.append(f"\n### {cls} (n={n})")
        if n < MIN_CLASS_N:
            body.append(f"\n_(insufficient sample, n={n})_")
            continue
        # Count pattern matches across this class's root_cause population
        pattern_counts: Counter[str] = Counter()
        for rc in sub["root_cause"].tolist():
            for key in detect_keywords(rc):
                pattern_counts[key] += 1
        if not pattern_counts:
            body.append("\n_(no keyword pattern matches found in this class)_")
            continue
        # Top 5 by match count, with deterministic tiebreak by pattern name
        top5 = sorted(pattern_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        rows = [[k, str(v), _pct(v, n)] for k, v in top5]
        body.append("\n" + _md_table(
            ["pattern_key", "matches", "% of misses in this class"],
            rows,
        ))
    return "\n".join(body)


def section_prop_type_concentration(df: pd.DataFrame, baseline: pd.DataFrame) -> str:
    total = len(df)
    baseline_total = len(baseline)
    rows = []
    for prop in ["PTS", "REB", "AST", "3PM"]:
        sub = df[df["prop_type"] == prop]
        n = len(sub)
        prop_picks = int((baseline["prop_type"] == prop).sum())
        if n == 0 and prop_picks == 0:
            rows.append([prop, "0", "—", "0", "—", "—"])
            continue
        if n == 0:
            top3 = "—"
        else:
            cls_counts = sub["miss_classification"].value_counts().head(3)
            top3 = ", ".join(f"{cls} {_pct(int(cnt), n)}" for cls, cnt in cls_counts.items())
        miss_rate = f"{(100.0 * n / prop_picks):.1f}%" if prop_picks > 0 else "—"
        rows.append([prop, str(n), _pct(n, total), str(prop_picks), miss_rate, top3])
    rows.append([
        "**TOTAL**",
        f"**{total}**", "**100.0%**",
        f"**{baseline_total}**", "—", "—",
    ])
    table = _md_table(
        ["prop_type", "miss count", "% of total misses",
         "total picks (graded)", "miss rate %", "top-3 classifications"],
        rows,
    )
    return (
        "## 5. Prop-Type Concentration\n\n"
        "Miss distribution across the 4 prop types, with v2 miss-rate column. "
        "Miss rate denominator is graded picks only (HIT or MISS, not voided) "
        "from picks.json. The top-3 classification column is the per-prop view "
        "(denominator = misses in that prop), not the global view.\n\n"
        + table
    )


def section_confidence_band_analysis(df: pd.DataFrame, baseline: pd.DataFrame) -> str:
    """v2 Section 5a — Confidence Band × Miss Bucket cross-tab.

    Three sub-tables:
      5a.1 — Pick volume by confidence band (incl. expected hit rate, overshoot).
      5a.2 — Miss classification breakdown within each band.
      5a.3 — Razor-margin variance concentration by band.
    """
    body = [
        "## 5a. Confidence Band Analysis (v2)\n\n"
        "Cross-tab of pick volume and miss patterns against the system's "
        "stated `confidence_pct`. Bands defined as `70_74` / `75_79` / "
        "`80_84` / `85_89` / `90_plus`. Expected hit rate uses the band "
        "midpoint (95.0 for the open-ended top band). Overshoot = actual − "
        "expected; positive means the system is over-performing the band's "
        "confidence label, indicating a calibration gap. **All denominators "
        "in this section come from picks.json graded baseline (HIT or MISS, "
        "not voided), not audit_log.json.**"
    ]

    # 5a.1 — Pick volume by band
    body.append("\n### 5a.1 — Pick volume by confidence band\n")
    band_rows = []
    grand_picks = grand_hits = grand_misses = 0
    for b in CONFIDENCE_BANDS:
        sub = baseline[baseline["confidence_band"] == b]
        n_total = len(sub)
        n_hits = int((sub["result"] == "HIT").sum())
        n_misses = int((sub["result"] == "MISS").sum())
        grand_picks += n_total
        grand_hits += n_hits
        grand_misses += n_misses
        if n_total == 0:
            band_rows.append([b, "0", "0", "0", "—", f"{BAND_EXPECTED_HR[b]:.1f}", "—"])
            continue
        actual_hr = 100.0 * n_hits / n_total
        expected_hr = BAND_EXPECTED_HR[b]
        overshoot = actual_hr - expected_hr
        band_rows.append([
            b, str(n_total), str(n_hits), str(n_misses),
            f"{actual_hr:.1f}",
            f"{expected_hr:.1f}",
            f"{overshoot:+.1f}",
        ])
    # Unbanded row — picks with confidence_pct < 70 (graceful-null in derivation
    # but counted here so the column-total matches the graded-picks baseline).
    unbanded = baseline[baseline["confidence_band"].isna()]
    n_unbanded = len(unbanded)
    if n_unbanded > 0:
        n_u_hits = int((unbanded["result"] == "HIT").sum())
        n_u_miss = int((unbanded["result"] == "MISS").sum())
        u_hr = (100.0 * n_u_hits / n_unbanded) if n_unbanded else 0.0
        grand_picks += n_unbanded
        grand_hits += n_u_hits
        grand_misses += n_u_miss
        band_rows.append([
            "<70 (unbanded)",
            str(n_unbanded), str(n_u_hits), str(n_u_miss),
            f"{u_hr:.1f}",
            "—",
            "—",
        ])
    band_rows.append([
        "**TOTAL**",
        f"**{grand_picks}**",
        f"**{grand_hits}**",
        f"**{grand_misses}**",
        "—", "—", "—",
    ])
    body.append(_md_table(
        ["confidence_band", "total picks (graded)", "hits", "misses",
         "hit rate %", "expected hit rate %", "overshoot pp"],
        band_rows,
    ))

    # 5a.2 — Miss classification breakdown within each band
    body.append("\n### 5a.2 — Miss classification breakdown within each band\n")
    body.append(
        "Of misses within each confidence band, what fraction falls into each "
        "classification? Rows with `n_misses < 5` show insufficient-sample "
        "placeholder rather than degenerate percentages.\n"
    )
    cls_rows = []
    for b in CONFIDENCE_BANDS:
        sub = df[df["confidence_band"] == b]
        n = len(sub)
        if n < MIN_CLASS_N:
            cls_rows.append([b, f"_(insufficient sample, n={n})_"] + ["—"] * len(CLASS_ORDER))
            continue
        counts = sub["miss_classification"].value_counts().to_dict()
        row = [b, str(n)]
        for cls in CLASS_ORDER:
            c = counts.get(cls, 0)
            row.append(_pct(c, n))
        cls_rows.append(row)
    body.append(_md_table(
        ["confidence_band", "n misses"] + [f"{c} %" for c in CLASS_ORDER],
        cls_rows,
    ))

    # 5a.3 — Razor variance concentration by band
    body.append("\n### 5a.3 — Razor-margin variance concentration by band\n")
    body.append(
        "Of misses with `miss_classification == \"variance\"` AND "
        "`miss_margin <= 1` (razor), how do they distribute by band? This "
        "directly diagnoses whether band overshoot is concentrated in "
        "close-call variance — the central calibration recalibration question. "
        "If the lowest-confidence band's overshoot is large AND its razor-"
        "variance share is dominant, the band is over-predicting hits on "
        "near-miss cases (calibration target). Razor share denominator is "
        "all misses in the band, including injury_event rows where margin "
        "is null (those rows are excluded from the razor count by construction)."
    )
    razor_rows = []
    for b in CONFIDENCE_BANDS:
        sub_band = df[df["confidence_band"] == b]
        total_band_misses = len(sub_band)
        razor_var = sub_band[
            (sub_band["miss_classification"] == "variance")
            & (sub_band["miss_margin"].notna())
            & (sub_band["miss_margin"].astype(float) <= 1.0)
        ]
        n_razor = len(razor_var)
        razor_rows.append([
            b,
            str(n_razor),
            str(total_band_misses),
            _pct(n_razor, total_band_misses),
        ])
    body.append(_md_table(
        ["confidence_band", "razor variance misses", "total band misses",
         "razor share of band misses"],
        razor_rows,
    ))
    return "\n".join(body)


def section_player_concentration(df: pd.DataFrame, baseline: pd.DataFrame) -> str:
    """v2: adds total_picks + miss_rate columns from baseline. Dossier candidate
    flag now requires BOTH `total_misses >= 5` AND `miss_rate_pct >= 15` so
    that high-volume players with average miss rates are NOT flagged."""
    total = len(df)
    counts = df["player_name"].value_counts()
    top10 = counts.head(10)
    # Pre-compute per-player baseline pick counts once (vector op)
    pick_counts = baseline["player_name"].value_counts().to_dict()
    rows = []
    flagged = []
    for player, n in top10.items():
        n = int(n)
        sub = df[df["player_name"] == player]
        cls_counts = sub["miss_classification"].value_counts()
        breakdown = ", ".join(f"{cls}={cnt}" for cls, cnt in cls_counts.items())
        share = 100.0 * n / total if total else 0.0
        total_picks = int(pick_counts.get(player, 0))
        miss_rate = (100.0 * n / total_picks) if total_picks > 0 else 0.0
        miss_rate_str = f"{miss_rate:.1f}%" if total_picks > 0 else "—"
        # v2 dossier flag: BOTH conditions required
        is_dossier = (n >= 5) and (miss_rate >= 15.0)
        flag = "⚠" if is_dossier else ""
        rows.append([
            player,
            str(n),
            str(total_picks),
            miss_rate_str,
            _pct(n, total),
            breakdown,
            flag,
        ])
        if is_dossier:
            flagged.append((player, n, total_picks, miss_rate, share))
    table = _md_table(
        ["player_name", "total_misses", "total_picks", "miss rate %",
         "% of all misses", "classification breakdown", "dossier candidate"],
        rows,
    )
    notes = ""
    if flagged:
        bullet_lines = "\n".join(
            f"- **{p}** ({n} misses on {tp} picks = {mr:.1f}% miss rate, "
            f"{s:.1f}% of all misses) — candidate for player-specific dossier review."
            for p, n, tp, mr, s in flagged
        )
        notes = (
            "\n\nPlayers flagged as dossier-review candidates (both "
            "`total_misses >= 5` AND `miss_rate_pct >= 15%`):\n\n"
            + bullet_lines
        )
    return (
        "## 6. Player Concentration\n\n"
        "Top-10 players by total miss count, with v2 miss-rate column. Total "
        "picks denominator comes from picks.json graded baseline. Dossier-"
        "review flag requires BOTH `total_misses >= 5` AND `miss_rate_pct "
        ">= 15%` — this surfaces players whose miss rate is structurally "
        "elevated, not high-volume players with average rates.\n\n"
        + table
        + notes
    )


def section_miss_margin_distribution(df: pd.DataFrame) -> str:
    margin_buckets = [
        ("razor (≤1)", lambda m: m <= 1),
        ("small (2–3)", lambda m: 2 <= m <= 3),
        ("medium (4–6)", lambda m: 4 <= m <= 6),
        ("large (7+)", lambda m: m >= 7),
    ]
    body = [
        "## 7. Miss Margin Distribution\n\n"
        "For each classification, the distribution of `miss_margin = pick_value - actual_value`. "
        "Rows where `actual_value` is `None` (typical of `injury_event`) are excluded "
        "from this section. This is critical for distinguishing 'near-miss variance' "
        "(razor/small margins, system was nearly right) from 'structural ceiling miss' "
        "(medium/large margins, system was wrong about the player's range)."
    ]
    rows = []
    for cls in CLASS_ORDER:
        sub = df[(df["miss_classification"] == cls) & (df["miss_margin"].notna())]
        n = len(sub)
        if n == 0:
            rows.append([cls, "0", "—", "—", "—", "—", "—"] + ["0"] * len(margin_buckets))
            continue
        margins = sub["miss_margin"].astype(float)
        mean_m = f"{margins.mean():.2f}"
        med_m  = f"{margins.median():.2f}"
        p25    = f"{margins.quantile(0.25):.2f}"
        p75    = f"{margins.quantile(0.75):.2f}"
        max_m  = f"{margins.max():.2f}"
        bucket_counts = []
        for _, fn in margin_buckets:
            cnt = int(margins.apply(fn).sum())
            bucket_counts.append(str(cnt))
        rows.append([cls, str(n), mean_m, med_m, p25, p75, max_m] + bucket_counts)
    header = ["classification", "n", "mean", "median", "p25", "p75", "max"] + [b[0] for b in margin_buckets]
    table = _md_table(header, rows)
    return "\n".join(body) + "\n\n" + table


def section_regular_season_vs_playoff(df: pd.DataFrame) -> str:
    total = len(df)
    n_reg = int((~df["is_playoff"]).sum())
    n_po  = int(df["is_playoff"].sum())
    rows = []
    flagged_divergent: list[tuple[str, float, float, float]] = []
    for cls in CLASS_ORDER:
        sub_reg = int(((df["miss_classification"] == cls) & (~df["is_playoff"])).sum())
        sub_po  = int(((df["miss_classification"] == cls) & (df["is_playoff"])).sum())
        pct_reg = (100.0 * sub_reg / n_reg) if n_reg else 0.0
        pct_po  = (100.0 * sub_po  / n_po)  if n_po  else 0.0
        delta = pct_po - pct_reg
        flag = "⚠" if abs(delta) > 5.0 else ""
        if abs(delta) > 5.0 and (sub_reg + sub_po) > 0:
            flagged_divergent.append((cls, pct_reg, pct_po, delta))
        rows.append([
            cls,
            str(sub_reg),
            f"{pct_reg:.1f}%",
            str(sub_po),
            f"{pct_po:.1f}%",
            f"{delta:+.1f}pp",
            flag,
        ])
    rows.append([
        "**TOTAL**",
        f"**{n_reg}**", "**100.0%**",
        f"**{n_po}**", "**100.0%**",
        "—", "—",
    ])
    table = _md_table(
        ["classification", "reg-season n", "% of reg", "playoff n", "% of playoff", "delta (pp)", "divergent (>5pp)"],
        rows,
    )
    notes = ""
    if flagged_divergent:
        bullet_lines = "\n".join(
            f"- **{cls}**: regular {r:.1f}% → playoff {p:.1f}% ({d:+.1f}pp) — investigate."
            for cls, r, p, d in flagged_divergent
        )
        notes = f"\n\nClassifications with >5pp playoff-vs-regular divergence:\n\n{bullet_lines}"
    return (
        "## 8. Regular-Season vs. Playoff Split\n\n"
        f"Regular-season slates: {n_reg} miss rows. Playoff slates "
        f"(date ≥ {PLAYOFF_START.isoformat()}): {n_po} miss rows. "
        "Playoff sample is small as of session date; classifications with "
        ">5pp divergence are flagged but should be investigated rather than "
        "treated as structural changes.\n\n"
        + table
        + notes
    )


def section_findings_and_workstream_recommendation(df: pd.DataFrame, baseline: pd.DataFrame) -> str:
    total = len(df)
    bucket_counts: dict[str, int] = {b: int((df["bucket"] == b).sum()) for b in BUCKET_ORDER}
    catchable_total = sum(bucket_counts[b] for b in BUCKET_ORDER if b != "inherent_variance")

    # v2: Per-band overshoot for the calibration diagnostic
    band_stats: dict[str, dict] = {}
    for b in CONFIDENCE_BANDS:
        sub = baseline[baseline["confidence_band"] == b]
        n_total = len(sub)
        if n_total == 0:
            band_stats[b] = {"n": 0, "actual_hr": None, "expected": BAND_EXPECTED_HR[b], "overshoot": None}
            continue
        n_hits = int((sub["result"] == "HIT").sum())
        actual_hr = 100.0 * n_hits / n_total
        band_stats[b] = {
            "n":         n_total,
            "actual_hr": actual_hr,
            "expected":  BAND_EXPECTED_HR[b],
            "overshoot": actual_hr - BAND_EXPECTED_HR[b],
        }
    # Razor-variance share within each band — used for calibration diagnostic
    razor_var_shares: dict[str, tuple[int, int, float]] = {}
    for b in CONFIDENCE_BANDS:
        sub_band = df[df["confidence_band"] == b]
        total_band = len(sub_band)
        razor_var_n = len(sub_band[
            (sub_band["miss_classification"] == "variance")
            & (sub_band["miss_margin"].notna())
            & (sub_band["miss_margin"].astype(float) <= 1.0)
        ])
        share = (100.0 * razor_var_n / total_band) if total_band > 0 else 0.0
        razor_var_shares[b] = (razor_var_n, total_band, share)

    # v2: Per-prop miss rates for the per-prop diagnostic
    prop_miss_rates: dict[str, tuple[int, int, float]] = {}
    for prop in ["PTS", "REB", "AST", "3PM"]:
        n_misses = int((df["prop_type"] == prop).sum())
        n_picks = int((baseline["prop_type"] == prop).sum())
        rate = (100.0 * n_misses / n_picks) if n_picks > 0 else 0.0
        prop_miss_rates[prop] = (n_misses, n_picks, rate)

    # Top-3 keyword patterns within each "actionable" bucket
    def _top_patterns_for_classes(class_list: list[str], k: int = 3) -> list[tuple[str, int]]:
        sub = df[df["miss_classification"].isin(class_list)]
        n = len(sub)
        if n == 0:
            return []
        cnt: Counter[str] = Counter()
        for rc in sub["root_cause"].tolist():
            for key in detect_keywords(rc):
                cnt[key] += 1
        return sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))[:k]

    det_top = _top_patterns_for_classes(["model_gap_rule", "workflow_gap"])
    new_data_top = _top_patterns_for_classes(["model_gap_signal", "model_gap"])

    # Player concentration > 5%
    counts = df["player_name"].value_counts()
    high_share = [(p, int(c)) for p, c in counts.items() if (100.0 * c / total) > 5.0]

    # Variance-margin profile: of variance misses with margin data, how many are razor/small?
    var_sub = df[(df["miss_classification"] == "variance") & (df["miss_margin"].notna())]
    var_n = len(var_sub)
    if var_n > 0:
        razor_small_n = int((var_sub["miss_margin"].astype(float) <= 3).sum())
        razor_small_pct = 100.0 * razor_small_n / var_n
    else:
        razor_small_pct = 0.0

    # Catchable-population shares (excluding inherent_variance)
    def _catchable_share(b: str) -> str:
        if catchable_total <= 0:
            return "—"
        return f"{100.0 * bucket_counts[b] / catchable_total:.1f}% of catchable population"

    body = [
        "## 9. Findings & Workstream Recommendation\n\n"
        "This section surfaces population patterns to inform the next major "
        "workstream choice. **It does not prescribe rule changes.** Any rule "
        "candidate named below requires its own backtest before shipping, per "
        "project discipline.\n",
    ]

    body.append("### What dominates the catchable population?\n")
    body.append(
        f"Excluding `inherent_variance` ({bucket_counts['inherent_variance']} rows, "
        f"{_pct(bucket_counts['inherent_variance'], total)} of all misses), the "
        f"catchable population is {catchable_total} rows. Bucket shares within "
        "the catchable population:\n"
    )
    body.append("")
    catchable_rows = []
    for b in BUCKET_ORDER:
        if b == "inherent_variance":
            continue
        catchable_rows.append([b, str(bucket_counts[b]), _catchable_share(b)])
    body.append(_md_table(["bucket", "count", "% of catchable population"], catchable_rows))
    body.append("")
    # Identify largest catchable bucket
    largest = max(
        (b for b in BUCKET_ORDER if b != "inherent_variance"),
        key=lambda b: bucket_counts[b],
    )
    body.append(
        f"\n**Largest catchable bucket:** `{largest}` — points toward this as "
        "the highest-leverage workstream class. Per-pattern analysis below names "
        "the candidate areas for that bucket.\n"
    )

    body.append("\n### Within `deterministic_rule_catchable` (model_gap_rule + workflow_gap):\n")
    if det_top:
        body.append("Top-3 keyword patterns — candidates for new prompt rules. Each requires its own backtest.\n")
        body.append("")
        body.append(_md_table(
            ["pattern_key", "matches"],
            [[k, str(v)] for k, v in det_top],
        ))
    else:
        body.append("_(no patterns matched — population may use root_cause vocabulary not in KEYWORD_PATTERNS)_")

    body.append("\n### Within `catchable_with_new_data` (model_gap_signal + model_gap):\n")
    if new_data_top:
        body.append("Top-3 keyword patterns — candidates for new data fields in `agents/quant.py` or new ingest pipelines.\n")
        body.append("")
        body.append(_md_table(
            ["pattern_key", "matches"],
            [[k, str(v)] for k, v in new_data_top],
        ))
    else:
        body.append("_(no patterns matched)_")

    body.append("\n### Notable single-pick concentration\n")
    if high_share:
        bullets = "\n".join(
            f"- **{p}** ({n} misses, {100.0*n/total:.1f}% of total) — dossier-review candidate."
            for p, n in high_share
        )
        body.append(bullets)
    else:
        body.append("_(no player accounts for >5% of total misses — concentration is healthy / league-wide patterns dominate)_")

    body.append("\n### Calibration check\n")
    var_share = bucket_counts["inherent_variance"] / total if total else 0.0
    if var_share >= 0.40 and razor_small_pct >= 60.0:
        body.append(
            f"- `variance` accounts for {_pct(bucket_counts['inherent_variance'], total)} of total misses "
            f"and {razor_small_pct:.1f}% of variance misses are razor/small (margin ≤ 3 units).\n"
            f"- This pattern suggests **calibration** is the dominant issue, not new signals. "
            "Consider per-band confidence floor recalibration or per-player calibration extension "
            "as the next workstream rather than new rules."
        )
    elif var_share >= 0.40:
        body.append(
            f"- `variance` accounts for {_pct(bucket_counts['inherent_variance'], total)} of total misses, "
            f"but only {razor_small_pct:.1f}% of variance misses are razor/small. "
            "The variance population includes structural ceiling misses, not just near-miss noise — "
            "suggests new signals or ceiling-cap rules rather than pure recalibration."
        )
    else:
        body.append(
            f"- `variance` is {_pct(bucket_counts['inherent_variance'], total)} of total misses — "
            "below the 40% threshold where calibration would be the dominant lever."
        )

    # v2: Confidence band overshoot diagnostic
    body.append("\n### Confidence band overshoot diagnostic (v2)\n")
    overshoot_lines = []
    for b in CONFIDENCE_BANDS:
        st = band_stats[b]
        if st["n"] == 0:
            overshoot_lines.append(f"- `{b}`: no graded picks in baseline.")
            continue
        rv = razor_var_shares[b]
        overshoot_lines.append(
            f"- `{b}`: actual hit rate {st['actual_hr']:.1f}% vs expected "
            f"{st['expected']:.1f}% → overshoot {st['overshoot']:+.1f}pp on "
            f"{st['n']} graded picks. Razor-variance share of band misses: "
            f"{rv[0]}/{rv[1]} = {rv[2]:.1f}%."
        )
    body.append("\n".join(overshoot_lines))
    # Recalibration framing
    bottom_band = "70_74"
    bb = band_stats[bottom_band]
    bb_razor = razor_var_shares[bottom_band]
    if bb["n"] > 0 and bb["overshoot"] is not None and bb["overshoot"] > 5.0:
        if bb_razor[2] > 50.0:
            body.append(
                f"\nThe `{bottom_band}` band overshoot ({bb['overshoot']:+.1f}pp) "
                f"is concentrated in razor variance ({bb_razor[2]:.1f}% of band "
                "misses are razor-margin variance). This is the calibration "
                "recalibration target — the system is winning the close calls "
                "in the lowest-confidence band more often than its label says."
            )
        else:
            body.append(
                f"\nThe `{bottom_band}` band has overshoot ({bb['overshoot']:+.1f}pp) "
                "but the variance is not concentrated in razor margins "
                f"({bb_razor[2]:.1f}% razor share). The diagnosis is more "
                "nuanced — recalibration alone may not capture the full "
                "structure of band misses."
            )
    else:
        body.append(
            f"\nThe `{bottom_band}` band does not show large overshoot "
            "(threshold: >5pp). Recalibration is not the immediate lever for "
            "this band."
        )

    # v2: Per-prop miss rate diagnostic
    body.append("\n### Per-prop miss rate diagnostic (v2)\n")
    nonzero = {p: r for p, r in prop_miss_rates.items() if r[1] > 0}
    if not nonzero:
        body.append("_(no graded picks in baseline)_")
    else:
        min_rate = min(r[2] for r in nonzero.values())
        rate_rows = []
        flagged_props: list[tuple[str, int, int, float, float]] = []
        for prop in ["PTS", "REB", "AST", "3PM"]:
            n_m, n_p, rate = prop_miss_rates[prop]
            if n_p == 0:
                rate_rows.append([prop, str(n_m), "0", "—", "—", ""])
                continue
            ratio = (rate / min_rate) if min_rate > 0 else 0.0
            flag = "⚠" if ratio > 1.5 else ""
            rate_rows.append([
                prop, str(n_m), str(n_p),
                f"{rate:.1f}%",
                f"{ratio:.2f}x",
                flag,
            ])
            if ratio > 1.5:
                flagged_props.append((prop, n_m, n_p, rate, ratio))
        body.append(_md_table(
            ["prop_type", "misses", "picks", "miss rate %", "ratio vs min", "flagged (>1.5×)"],
            rate_rows,
        ))
        if flagged_props:
            body.append(
                "\nProp(s) flagged with miss rate >1.5× the lowest-rate prop:\n"
            )
            for prop, n_m, n_p, rate, ratio in flagged_props:
                body.append(
                    f"- **{prop}**: {n_m} misses on {n_p} picks ({rate:.1f}%), "
                    f"{ratio:.2f}× the lowest-rate prop. Worth investigating "
                    "whether this prop's tier rules / volatility handling needs review."
                )
        else:
            body.append(
                "\nNo prop is more than 1.5× the lowest-rate prop. Per-prop "
                "miss rates are roughly proportional."
            )

    body.append("\n### Open question for human review\n")
    # Construct an open question grounded in the data
    if largest == "deterministic_rule_catchable" and det_top:
        top_pat = det_top[0][0]
        body.append(
            f"Given that `deterministic_rule_catchable` is the largest catchable bucket "
            f"and `{top_pat}` is its top pattern: is the next workstream a "
            f"`{top_pat}`-rule expansion (with backtest), or do we accept that variance level "
            "and prioritize the next-largest bucket instead?"
        )
    elif largest == "catchable_with_new_data" and new_data_top:
        top_pat = new_data_top[0][0]
        body.append(
            f"Given that `catchable_with_new_data` is the largest catchable bucket "
            f"and `{top_pat}` is its top pattern: is the next workstream a new data "
            f"signal for `{top_pat}` (with ingest changes), or do we keep accepting "
            "those misses and prioritize a different bucket?"
        )
    elif largest == "catchable_with_current_signals":
        body.append(
            "`catchable_with_current_signals` is the largest catchable bucket — meaning "
            "the analyst is selecting poorly given existing data. Is the next workstream "
            "a prompt-rule tightening, a multi-agent expert review layer, or per-player "
            "calibration?"
        )
    else:
        body.append(
            "Population is dominated by `inherent_variance`. Is the next workstream "
            "calibration recalibration (per-band or per-player), or do we accept the "
            "variance level as a structural floor and pursue a different goal?"
        )

    return "\n".join(body)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    df = load_misses()
    baseline = load_picks_baseline()
    sections = [
        section_overview(df, baseline),
        section_taxonomy_breakdown(df),
        section_four_bucket_rollup(df),
        section_keyword_patterns_within_bucket(df),
        section_prop_type_concentration(df, baseline),
        section_confidence_band_analysis(df, baseline),
        section_player_concentration(df, baseline),
        section_miss_margin_distribution(df),
        section_regular_season_vs_playoff(df),
        section_findings_and_workstream_recommendation(df, baseline),
    ]
    header = (
        "# Miss Classification Population Analysis\n\n"
        "_Read-only descriptive analysis over `data/audit_log.json`. "
        "Decision input for the next major workstream choice. No rules ship "
        "from this report._\n\n"
        "_v2 enrichment: this report includes confidence-band analysis and "
        "per-prop/per-player miss rates (computed from picks.json volume "
        "baseline), and uses tightened keyword detection with negation guards. "
        "v1 sections retain their structure._\n"
    )
    report = header + "\n---\n\n" + "\n\n---\n\n".join(sections) + "\n"
    REPORT_OUT.write_text(report)
    print(f"[miss_classification] Wrote {REPORT_OUT} ({len(df)} miss rows analyzed)")


if __name__ == "__main__":
    main()
