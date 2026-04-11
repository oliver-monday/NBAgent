#!/usr/bin/env python3
"""
merge_picks.py — Merge guard for picks.json during injuries.yml commits.

Compares the local (post-lineup_watch / post-lineup_update) picks.json against
the origin (post-git-pull) version. If origin has MORE today-picks than local,
the analyst must have pushed a new pick set between our checkout and commit —
we use origin as the base and overlay local's injury-mutation fields onto the
matching picks. Otherwise, local is kept as-is (normal path, no-op merge).

Mutation fields carried from local → origin on overlapping picks:
  voided
  void_reason
  lineup_risk
  injury_status_at_check
  injury_check_time
  lineup_update    (full sub-object)

Key for overlap matching:
  (player_name.lower(), prop_type, pick_value, date)

Matches the recovery logic used manually on 2026-04-10 to restore the clobbered
33-pick re-run (see commit a131c1f for the incident post-mortem).

Usage:
    python ingest/merge_picks.py --local data/picks.json.local \\
                                  --origin data/picks.json.origin \\
                                  --output data/picks.json

Exit codes:
    0 — success (merged or no-op)
    1 — error (falls back to local copy, prints warning)

The script is defensive: any uncaught exception triggers a fallback to the
local copy so the injuries workflow never regresses behind its pre-guard
behavior. Worst case the guard is inert; it can never make things worse.
"""

import argparse
import datetime as dt
import json
import shutil
import sys
from zoneinfo import ZoneInfo

PT = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(PT).strftime("%Y-%m-%d")

# Fields that lineup_watch.py and lineup_update.py write onto picks.
# These are the ONLY fields that should be carried from local → origin.
# Every other field on each pick is trusted from origin.
MUTATION_FIELDS = [
    "voided",
    "void_reason",
    "lineup_risk",
    "injury_status_at_check",
    "injury_check_time",
    "lineup_update",
]


def pick_key(p: dict) -> tuple:
    """Unique identity of a pick across local and origin versions."""
    return (
        (p.get("player_name") or "").strip().lower(),
        p.get("prop_type", ""),
        p.get("pick_value"),
        p.get("date", ""),
    )


def merge(local_path: str, origin_path: str, output_path: str) -> None:
    with open(local_path) as f:
        local_picks = json.load(f)
    with open(origin_path) as f:
        origin_picks = json.load(f)

    local_today  = [p for p in local_picks  if p.get("date") == TODAY_STR]
    origin_today = [p for p in origin_picks if p.get("date") == TODAY_STR]

    print(
        f"[merge_picks] today={TODAY_STR} | "
        f"local today-picks={len(local_today)} | "
        f"origin today-picks={len(origin_today)}"
    )

    if len(origin_today) <= len(local_today):
        # Normal path: local has as many (or more) today-picks as origin.
        # No race condition detected — use local as-is.
        print("[merge_picks] local has >= origin today-picks — using local (no merge needed)")
        with open(output_path, "w") as f:
            json.dump(local_picks, f, indent=2)
        return

    # Race detected: origin has MORE today-picks than local.
    # The analyst must have pushed new picks between our checkout and now.
    # Use origin as the base and overlay local's injury mutations onto
    # matching picks (by key). Non-overlapping fresh picks on origin are
    # preserved unchanged — the next injuries.yml run will mutate them
    # against the current injuries_today.json from a fresh checkout.
    print(
        f"[merge_picks] MERGE TRIGGERED — origin has {len(origin_today)} today-picks "
        f"vs local {len(local_today)}. Using origin as base, overlaying injury mutations."
    )

    # Build mutation lookup from local's today-picks
    local_mutations: dict[tuple, dict] = {}
    for p in local_today:
        key = pick_key(p)
        mutations = {f: p[f] for f in MUTATION_FIELDS if f in p}
        if mutations:
            local_mutations[key] = mutations

    # Apply mutations to origin's today-picks (modify in place)
    applied = 0
    for p in origin_picks:
        if p.get("date") != TODAY_STR:
            continue
        key = pick_key(p)
        if key in local_mutations:
            for field, value in local_mutations[key].items():
                p[field] = value
            applied += 1

    overlap_possible = sum(1 for k in local_mutations if k in {pick_key(p) for p in origin_picks if p.get("date") == TODAY_STR})
    fresh_count = len(origin_today) - overlap_possible
    print(
        f"[merge_picks] Applied injury mutations to {applied} pick(s) "
        f"({overlap_possible} overlap, {fresh_count} fresh)"
    )

    with open(output_path, "w") as f:
        json.dump(origin_picks, f, indent=2)
    print(
        f"[merge_picks] Wrote merged picks.json: "
        f"{len(origin_picks)} total picks, {len(origin_today)} for {TODAY_STR}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge guard for picks.json in injuries.yml")
    parser.add_argument("--local",  required=True, help="Path to local (post-lineup_watch) picks.json")
    parser.add_argument("--origin", required=True, help="Path to origin (post-git-pull) picks.json")
    parser.add_argument("--output", required=True, help="Path to write merged result")
    args = parser.parse_args()

    try:
        merge(args.local, args.origin, args.output)
    except Exception as e:
        print(f"[merge_picks] ERROR: {e} — falling back to local copy")
        # Fallback: preserve current (pre-guard) behavior on any failure.
        # Worst case the guard is inert; it can never make things worse.
        try:
            shutil.copy2(args.local, args.output)
        except Exception as e2:
            print(f"[merge_picks] FATAL: fallback copy also failed: {e2}")
            sys.exit(1)
        sys.exit(1)


if __name__ == "__main__":
    main()
