#!/usr/bin/env python3
"""
repair_void_grading.py — One-time repair for corrupted void/grading data.

Fixes two historical bugs:
  Bug A: picks with voided=True were still graded result="MISS" instead of result=null
  Bug B: picks with void_reason set (post-hoc late DNP) but voided=False were graded
         result="MISS", actual_value=0.0, miss_classification="workflow_gap"
         instead of being promoted to voided=True, result=null

Affected dates:
  2026-03-12: 4 Derrick White picks (voided=True, result="MISS") → Bug A
  2026-03-13: 2 Alperen Sengun picks (voided=False, void_reason set, actual=0.0) → Bug B

After patching picks.json, recomputes the two affected audit_log.json entries and
regenerates audit_summary.json.

SAFE TO RE-RUN: idempotent — already-patched picks are skipped.

DO NOT EDIT: picks.json schema, audit_log.json schema, or audit_summary.json schema.
"""

import json
import sys
import os
from pathlib import Path
from collections import defaultdict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).resolve().parent.parent
DATA        = REPO_ROOT / "data"
PICKS_JSON  = DATA / "picks.json"
AUDIT_JSON  = DATA / "audit_log.json"
SUMMARY_JSON = DATA / "audit_summary.json"

AFFECTED_DATES = {"2026-03-12", "2026-03-13"}


# ---------------------------------------------------------------------------
# Step 1 — Repair picks.json
# ---------------------------------------------------------------------------

def repair_picks() -> tuple[list[dict], int, int]:
    """
    Returns (patched_picks, n_bug_a_fixed, n_bug_b_fixed).
    Writes patched picks back to picks.json.
    """
    with open(PICKS_JSON, "r") as f:
        picks = json.load(f)

    n_bug_a = 0
    n_bug_b = 0

    for p in picks:
        if p.get("date") not in AFFECTED_DATES:
            continue

        # Bug A: voided=True but result was set to MISS
        if p.get("voided") is True and p.get("result") == "MISS":
            p["result"] = None
            p["actual_value"] = None
            n_bug_a += 1
            print(f"[repair] BUG_A fixed: {p['date']} {p['player_name']} "
                  f"{p['prop_type']} {p['pick_value']} → result=null")

        # Bug B: void_reason set, voided=False, result=MISS, actual=0.0
        elif (
            not p.get("voided")
            and p.get("void_reason")
            and p.get("result") == "MISS"
            and p.get("actual_value") == 0.0
        ):
            p["voided"] = True
            p["result"] = None
            p["actual_value"] = None
            n_bug_b += 1
            print(f"[repair] BUG_B fixed: {p['date']} {p['player_name']} "
                  f"{p['prop_type']} {p['pick_value']} "
                  f"void_reason='{p['void_reason']}' → voided=True, result=null")

    with open(PICKS_JSON, "w") as f:
        json.dump(picks, f, indent=2)

    print(f"\n[repair] picks.json patched — Bug A: {n_bug_a}, Bug B: {n_bug_b}")
    return picks, n_bug_a, n_bug_b


# ---------------------------------------------------------------------------
# Step 2 — Recompute affected audit_log.json entries
# ---------------------------------------------------------------------------

def recompute_audit_log(picks: list[dict]) -> None:
    """
    Recomputes hits/misses/voided_picks/hit_rate_pct for the two affected dates
    and writes them back to audit_log.json.
    """
    with open(AUDIT_JSON, "r") as f:
        audit_log = json.load(f)

    # Build per-date pick summary from the (already-patched) picks
    date_stats: dict[str, dict] = defaultdict(lambda: {
        "hits": 0, "misses": 0, "no_data": 0, "voided": 0
    })

    for p in picks:
        d = p.get("date", "")
        if d not in AFFECTED_DATES:
            continue
        result = p.get("result")
        if p.get("voided") is True:
            date_stats[d]["voided"] += 1
        elif result == "HIT":
            date_stats[d]["hits"] += 1
        elif result == "MISS":
            date_stats[d]["misses"] += 1
        elif result in ("NO_DATA", None):
            date_stats[d]["no_data"] += 1

    # Patch audit_log entries
    for entry in audit_log:
        d = entry.get("date", "")
        if d not in AFFECTED_DATES:
            continue

        stats = date_stats[d]
        hits    = stats["hits"]
        misses  = stats["misses"]
        voided  = stats["voided"]
        gradeable = hits + misses

        # Adjust for injury_exclusions already recorded in the entry
        injury_excl = entry.get("injury_exclusions", 0)
        adjusted = gradeable - injury_excl
        hit_rate = round(hits / adjusted * 100, 1) if adjusted > 0 else 0.0

        old_hits    = entry.get("hits", "?")
        old_misses  = entry.get("misses", "?")
        old_voided  = entry.get("voided_picks", "?")
        old_rate    = entry.get("hit_rate_pct", "?")

        entry["hits"]         = hits
        entry["misses"]       = misses
        entry["voided_picks"] = voided
        entry["total_picks"]  = gradeable  # active only (matches build_audit_prompt contract)
        entry["hit_rate_pct"] = hit_rate

        print(f"[repair] audit_log {d}: "
              f"hits {old_hits}→{hits}, misses {old_misses}→{misses}, "
              f"voided {old_voided}→{voided}, hit_rate {old_rate}→{hit_rate}%")

    with open(AUDIT_JSON, "w") as f:
        json.dump(audit_log, f, indent=2)

    print("[repair] audit_log.json updated.")


# ---------------------------------------------------------------------------
# Step 3 — Regenerate audit_summary.json via auditor.save_audit_summary()
# ---------------------------------------------------------------------------

def recompute_audit_summary(picks: list[dict]) -> None:
    """
    Calls auditor.save_audit_summary() to regenerate audit_summary.json from
    the corrected audit_log.json.  Falls back to manual recomputation if the
    import fails (e.g. missing dependencies).
    """
    try:
        # Add agents/ to path so we can import auditor
        agents_dir = str(REPO_ROOT / "agents")
        if agents_dir not in sys.path:
            sys.path.insert(0, agents_dir)

        import auditor  # type: ignore
        with open(AUDIT_JSON, "r") as f:
            audit_log = json.load(f)

        # Load skipped picks for skip_validation block (may not exist)
        skipped: list[dict] = []
        skipped_path = DATA / "skipped_picks.json"
        if skipped_path.exists():
            with open(skipped_path, "r") as f:
                skipped = json.load(f)

        auditor.save_audit_summary(audit_log, all_skips=skipped or None)
        print("[repair] audit_summary.json regenerated via auditor.save_audit_summary().")

    except Exception as exc:
        print(f"[repair] WARNING: could not import auditor ({exc}). "
              "Falling back to manual summary recomputation.")
        _manual_recompute_summary(picks)


def _manual_recompute_summary(picks: list[dict]) -> None:
    """
    Minimal fallback: reads audit_log.json and recomputes overall hit/miss/voided
    counts then writes the corrected totals into audit_summary.json without
    changing the per-prop or calibration breakdown (those are already correct
    except for the two affected dates).
    """
    with open(AUDIT_JSON, "r") as f:
        audit_log = json.load(f)

    if not SUMMARY_JSON.exists():
        print("[repair] audit_summary.json not found — skipping manual fallback.")
        return

    with open(SUMMARY_JSON, "r") as f:
        summary = json.load(f)

    # Recompute overall totals from corrected audit_log
    total_hits    = sum(e.get("hits",         0) for e in audit_log)
    total_misses  = sum(e.get("misses",       0) for e in audit_log)
    total_voided  = sum(e.get("voided_picks", 0) for e in audit_log)
    total_injury  = sum(e.get("injury_exclusions", 0) for e in audit_log)

    gradeable_adj = (total_hits + total_misses) - total_injury
    hit_rate = round(total_hits / gradeable_adj * 100, 1) if gradeable_adj > 0 else 0.0

    overall = summary.get("overall", {})
    overall["hits"]               = total_hits
    overall["misses"]             = total_misses
    overall["voided"]             = total_voided
    overall["hit_rate_pct"]       = hit_rate
    overall["injury_exclusions"]  = total_injury
    summary["overall"] = overall

    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[repair] audit_summary.json manually updated: "
          f"hits={total_hits}, misses={total_misses}, voided={total_voided}, "
          f"hit_rate={hit_rate}%")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify(picks: list[dict]) -> None:
    print("\n--- VERIFICATION ---")

    # picks.json: no voided pick should have a non-null result
    bad_voided = [
        p for p in picks
        if p.get("voided") is True and p.get("result") in ("HIT", "MISS")
    ]
    if bad_voided:
        print(f"[FAIL] {len(bad_voided)} voided picks still have HIT/MISS result:")
        for p in bad_voided:
            print(f"  {p['date']} {p['player_name']} {p['prop_type']} result={p['result']}")
    else:
        print("[PASS] picks.json: no voided pick has HIT/MISS result")

    # audit_log: check affected dates
    with open(AUDIT_JSON, "r") as f:
        audit_log = json.load(f)

    for entry in audit_log:
        if entry.get("date") in AFFECTED_DATES:
            v = entry.get("voided_picks", 0)
            print(f"[INFO] audit_log {entry['date']}: "
                  f"hits={entry['hits']}, misses={entry['misses']}, "
                  f"voided={v}, hit_rate={entry['hit_rate_pct']}%")

    # audit_summary: show corrected season totals
    if SUMMARY_JSON.exists():
        with open(SUMMARY_JSON, "r") as f:
            summary = json.load(f)
        o = summary.get("overall", {})
        print(f"[INFO] audit_summary overall: "
              f"hits={o.get('hits')}, misses={o.get('misses')}, "
              f"voided={o.get('voided')}, hit_rate={o.get('hit_rate_pct')}%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== repair_void_grading.py ===\n")

    print("Step 1: Patching picks.json ...")
    picks, n_a, n_b = repair_picks()

    if n_a == 0 and n_b == 0:
        print("[INFO] No picks needed patching — already clean or wrong dates?")
        print("       Proceeding to recompute summary anyway to ensure consistency.")

    print("\nStep 2: Recomputing audit_log.json ...")
    recompute_audit_log(picks)

    print("\nStep 3: Regenerating audit_summary.json ...")
    recompute_audit_summary(picks)

    verify(picks)
    print("\nDone.")
