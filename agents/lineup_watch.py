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

import argparse
import datetime as dt
import difflib
import json
import sys
from collections import Counter
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

# Team abbrev normalisation — mirrors build_site.py _ABBR_NORM
_ABBR_NORM: dict[str, str] = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP",
    "NY": "NYK", "UTAH": "UTA", "WSH": "WAS",
}


def _norm_team(abbr: str) -> str:
    a = str(abbr).upper().strip()
    return _ABBR_NORM.get(a, a)


def _extract_last(raw_name: str) -> str:
    """Return lowercased last name from either 'F. LastName' or 'FirstName LastName'."""
    n = str(raw_name).strip()
    # Rotowire abbreviated format: "L. James"
    if len(n) >= 3 and n[1] == "." and n[2] == " ":
        return n[3:].lower()
    # Full name: "LeBron James" → "james"
    parts = n.split()
    return parts[-1].lower() if parts else n.lower()


# ── Data loaders ─────────────────────────────────────────────────────

def load_injury_lookup() -> dict[tuple, dict]:
    """
    Build injury lookup keyed by (norm_team_upper, last_name_lower).

    Handles both Rotowire abbreviated names ("L. James") and full names
    ("LeBron James") via _extract_last(). Team abbrevs are normalised
    via _norm_team() to handle GS/GSW, SA/SAS, NY/NYK, etc.

    Returns:
        {("LAL", "james"): {"status": "OUT", "reason": "Knee"}, ...}
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

    lookup: dict[tuple, dict] = {}
    for team_key, val in raw.items():
        if not isinstance(val, list):
            continue  # skip metadata keys like "fetched_at"
        norm_t = _norm_team(team_key)
        for entry in val:
            raw_name = (entry.get("player_name") or entry.get("name") or "").strip()
            last = _extract_last(raw_name)
            status_str = (entry.get("status") or "").upper().strip()
            if last:
                key = (norm_t, last)
                # If duplicate last name on same team, keep the higher-severity entry
                existing = lookup.get(key)
                if existing is None or (
                    _SEVERITY.get(status_str, 0) > _SEVERITY.get(existing["status"], 0)
                ):
                    lookup[key] = {
                        "status": status_str,
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Diagnostic mode — read only, no writes")
    args = parser.parse_args()
    debug = args.debug
    if debug:
        print("[lineup_watch] *** DEBUG MODE — read only, no picks.json writes ***\n")

    print(f"[lineup_watch] Running for {TODAY_STR}")

    injury_lookup = load_injury_lookup()
    if not injury_lookup:
        print("[lineup_watch] No injury data — exiting.")
        return

    if debug:
        print(f"[debug] injuries_today.json: {len(injury_lookup)} players listed")
        print(f"[debug] Injury statuses present:")
        status_counts = Counter(v["status"] for v in injury_lookup.values())
        for status, count in sorted(status_counts.items()):
            print(f"         {status}: {count}")
        flagged_in_report = {
            name: v for name, v in injury_lookup.items()
            if v["status"] in ("OUT", "DOUBTFUL", "QUESTIONABLE")
        }
        print(f"\n[debug] Players with notable injury status ({len(flagged_in_report)}):")
        for name, v in sorted(flagged_in_report.items()):
            print(f"         {v['status']:12s} {name}  ({v['reason']})")
        print()

    picks = load_picks()
    if not picks:
        print("[lineup_watch] No picks — exiting.")
        return

    # Snapshot timestamp for this run
    now_ts = dt.datetime.now(ET).isoformat()

    # Write injury snapshot fields to ALL of today's picks (including voided)
    all_today = [p for p in picks if p.get("date") == TODAY_STR]

    if debug:
        pick_names = sorted({(p.get("player_name") or "").strip() for p in all_today})
        print(f"[debug] Today's pick players ({len(pick_names)}):")
        for name in pick_names:
            p_last = _extract_last(name)
            p_team = _norm_team(next((p.get("team","") for p in all_today if p.get("player_name","").strip()==name), ""))
            inj = injury_lookup.get((p_team, p_last))
            if inj:
                status = inj["status"]
                reason = inj["reason"]
                marker = "⚠ MATCH" if status in ("OUT", "DOUBTFUL", "QUESTIONABLE") else "  listed"
                print(f"         {marker:10s} {name}  → {status} ({reason})")
            else:
                print(f"         no match   {name}")
        print()

        injury_lasts = [k[1] for k in injury_lookup.keys()]
        print(f"[debug] Fuzzy near-miss check (pick players with no exact injury match):")
        found_nearmiss = False
        for name in pick_names:
            p_last = _extract_last(name)
            p_team = _norm_team(next((p.get("team","") for p in all_today if p.get("player_name","").strip()==name), ""))
            if injury_lookup.get((p_team, p_last)):
                continue  # already matched exactly
            close = difflib.get_close_matches(p_last, injury_lasts, n=3, cutoff=0.7)
            if close:
                found_nearmiss = True
                print(f"         NEAR-MISS: '{name}' (last='{p_last}') ≈ last names {close}")
                for c in close:
                    matches = {k: v for k, v in injury_lookup.items() if k[1] == c}
                    for mk, mv in matches.items():
                        print(f"                   injury report has: {mk} → {mv['status']}")
        if not found_nearmiss:
            print("         No near-misses found — name formats appear consistent")
        print()

        print(f"[debug] Current pick state in picks.json:")
        for p in all_today:
            name    = p.get("player_name", "")
            prop    = p.get("prop_type", "")
            val     = p.get("pick_value", "")
            voided  = p.get("voided", False)
            risk    = p.get("lineup_risk", "none")
            status  = p.get("injury_status_at_check", "not_recorded")
            checked = p.get("injury_check_time", "never")
            flag = ""
            if voided:
                flag = "  ← VOIDED"
            elif risk in ("high", "moderate"):
                flag = f"  ← {risk.upper()} RISK"
            print(f"         {name} {prop} {val}  |  voided={voided}  risk={risk}  last_status={status}  checked={checked}{flag}")
        print()

    for p in all_today:
        p_last = _extract_last(p.get("player_name") or "")
        p_team = _norm_team(p.get("team") or "")
        inj  = injury_lookup.get((p_team, p_last))
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
        if not debug:
            save_picks(picks)
        else:
            print("[debug] Skipping picks.json write (debug mode)")
            print("[lineup_watch] Debug run complete — no files modified")
        return

    print(f"[lineup_watch] Checking {len(open_today)} open picks...")

    voided_count  = 0
    flagged_count = 0
    unchanged     = 0

    for p in open_today:
        p_last = _extract_last(p.get("player_name") or "")
        p_team = _norm_team(p.get("team") or "")
        inj    = injury_lookup.get((p_team, p_last))

        status = (inj["status"] if inj else "")
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
            # Not listed or PROBABLE — clear any stale flags from a prior run
            had_flag = p.get("voided") or p.get("lineup_risk")
            p["voided"] = False
            p.pop("lineup_risk", None)
            if had_flag:
                print(f"[lineup_watch] CLEAR → {label} (no longer listed as injured)")
            unchanged += 1

    if not debug:
        save_picks(picks)
    else:
        print("[debug] Skipping picks.json write (debug mode)")
        print("[lineup_watch] Debug run complete — no files modified")
    print(
        f"[lineup_watch] Done — "
        f"{voided_count} voided, {flagged_count} flagged, {unchanged} unchanged"
    )


if __name__ == "__main__":
    run()
