#!/usr/bin/env python3
"""
NBAgent — Lineup Watch

Post-processing pass that runs after each Rotowire injury refresh.
Reads today's open picks and updates them in-place based on the
current injury report:

  OUT          → voided=True, void_reason set, lineup_risk="high"
  DOUBTFUL     → lineup_risk="high"
  QUESTIONABLE → lineup_risk="moderate"  (only if not already "high")

Severity is sticky upward: a pick already flagged "high" is never
downgraded to "moderate", and a voided pick is never touched again.

Team abbreviation mismatch (NYK/NY, GS/GSW, etc.) is sidestepped
entirely: the injury lookup is keyed by player_name.lower() across
all teams, so no team key matching is needed.

Writes back to picks.json. build_site.py reads voided/lineup_risk
and renders cards with strikethrough badges or risk pills.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT          = Path(__file__).resolve().parent.parent
DATA          = ROOT / "data"
PICKS_JSON    = DATA / "picks.json"
INJURIES_JSON = DATA / "injuries_today.json"

ET        = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(ET).date().strftime("%Y-%m-%d")

# Severity rank — only upgrade, never downgrade
_SEVERITY = {"moderate": 1, "high": 2}


# ── Data loaders ─────────────────────────────────────────────────────

def load_injury_lookup() -> dict[str, dict]:
    """
    Flatten ALL injury entries across all teams into a single dict
    keyed by player_name.lower().

    Team abbrev keys in injuries_today.json are ignored — this
    sidesteps NYK/NY, GS/GSW, SAS/SA, etc. mismatches completely.

    Returns:
        {"jalen brunson": {"status": "OUT", "reason": "Knee"}, ...}
    """
    if not INJURIES_JSON.exists():
        print("[lineup_watch] injuries_today.json not found — skipping.")
        return {}

    try:
        with open(INJURIES_JSON) as f:
            raw = json.load(f)
    except Exception as e:
        print(f"[lineup_watch] ERROR reading injuries: {e}")
        return {}

    lookup: dict[str, dict] = {}
    for key, val in raw.items():
        if not isinstance(val, list):
            continue  # skip metadata keys like "fetched_at"
        for entry in val:
            name = (entry.get("player_name") or "").strip().lower()
            if name:
                lookup[name] = {
                    "status": (entry.get("status") or "").upper().strip(),
                    "reason": (entry.get("reason") or "").strip(),
                }

    print(f"[lineup_watch] Injury lookup built: {len(lookup)} players")
    return lookup


def load_picks() -> list[dict]:
    if not PICKS_JSON.exists():
        print("[lineup_watch] picks.json not found — nothing to do.")
        return []
    try:
        with open(PICKS_JSON) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[lineup_watch] ERROR reading picks.json: {e}")
        return []


def save_picks(picks: list[dict]) -> None:
    with open(PICKS_JSON, "w") as f:
        json.dump(picks, f, indent=2)


# ── Main logic ───────────────────────────────────────────────────────

def run() -> None:
    print(f"[lineup_watch] Running for {TODAY_STR}")

    injury_lookup = load_injury_lookup()
    if not injury_lookup:
        print("[lineup_watch] No injury data — exiting.")
        return

    picks = load_picks()
    if not picks:
        print("[lineup_watch] No picks — exiting.")
        return

    # Snapshot timestamp for this run
    now_ts = dt.datetime.now(ET).isoformat()

    # Write injury snapshot fields to ALL of today's picks (including voided)
    all_today = [p for p in picks if p.get("date") == TODAY_STR]
    for p in all_today:
        name = (p.get("player_name") or "").strip().lower()
        inj  = injury_lookup.get(name)
        if inj is None:
            status_str = "NOT_LISTED"
        else:
            raw = inj["status"]
            status_str = raw if raw in ("OUT", "DOUBTFUL", "QUESTIONABLE") else "NOT_LISTED"
        p["injury_status_at_check"] = status_str
        p["injury_check_time"]      = now_ts

    # Only touch today's ungraded picks for voiding/flagging
    open_today = [p for p in all_today if p.get("result") is None]

    if not open_today:
        print(f"[lineup_watch] No open picks for {TODAY_STR} — saving snapshot updates.")
        save_picks(picks)
        return

    print(f"[lineup_watch] Checking {len(open_today)} open picks...")

    voided_count  = 0
    flagged_count = 0
    unchanged     = 0

    for p in open_today:
        name = (p.get("player_name") or "").strip().lower()
        inj  = injury_lookup.get(name)

        if inj is None:
            unchanged += 1
            continue

        status = inj["status"]
        label  = f"{p.get('player_name')} ({p.get('team')} {p.get('prop_type')} OVER {p.get('pick_value')})"

        if status == "OUT":
            if p.get("voided"):
                unchanged += 1  # already voided; leave it
            else:
                p["voided"]      = True
                p["void_reason"] = "player OUT per injury report"
                p["lineup_risk"] = "high"
                voided_count += 1
                print(f"[lineup_watch] VOID  → {label} (OUT)")

        elif status == "DOUBTFUL":
            if p.get("voided"):
                unchanged += 1  # never downgrade from voided
            else:
                current_sev = _SEVERITY.get(p.get("lineup_risk", ""), 0)
                if current_sev < _SEVERITY["high"]:
                    p["lineup_risk"] = "high"
                    flagged_count += 1
                    print(f"[lineup_watch] FLAG  → {label} lineup_risk=high (DOUBTFUL)")
                else:
                    unchanged += 1

        elif status == "QUESTIONABLE":
            if p.get("voided"):
                unchanged += 1
            else:
                current_sev = _SEVERITY.get(p.get("lineup_risk", ""), 0)
                if current_sev < _SEVERITY["moderate"]:
                    p["lineup_risk"] = "moderate"
                    flagged_count += 1
                    print(f"[lineup_watch] FLAG  → {label} lineup_risk=moderate (QUESTIONABLE)")
                else:
                    unchanged += 1  # already high or already moderate — no change

        else:
            # PROBABLE or anything else — no action
            unchanged += 1

    save_picks(picks)
    print(
        f"[lineup_watch] Done — "
        f"{voided_count} voided, {flagged_count} flagged, {unchanged} unchanged"
    )


if __name__ == "__main__":
    run()
