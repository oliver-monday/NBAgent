#!/usr/bin/env python3
"""
NBAgent — Auditor

Cross-references yesterday's picks from data/picks.json against
actual box scores in data/player_game_log.csv.

Scores each pick as HIT or MISS, performs root cause analysis,
and writes structured feedback to data/audit_log.json for the
Analyst to read on its next run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GAME_LOG_CSV   = DATA / "player_game_log.csv"
PICKS_JSON     = DATA / "picks.json"
AUDIT_LOG_JSON = DATA / "audit_log.json"

ET = ZoneInfo("America/New_York")
TODAY = dt.datetime.now(ET).date()
YESTERDAY = TODAY - dt.timedelta(days=1)
YESTERDAY_STR = YESTERDAY.strftime("%Y-%m-%d")

# ── Config ───────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048


# ── Data loaders ─────────────────────────────────────────────────────

def load_yesterdays_picks() -> list[dict]:
    if not PICKS_JSON.exists():
        print(f"[auditor] No picks.json found.")
        return []

    with open(PICKS_JSON, "r") as f:
        all_picks = json.load(f)

    yesterday_picks = [p for p in all_picks if p.get("date") == YESTERDAY_STR]

    if not yesterday_picks:
        print(f"[auditor] No picks found for {YESTERDAY_STR}. Nothing to audit.")

    return yesterday_picks


def load_game_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


# ── Grading ──────────────────────────────────────────────────────────

PROP_COL_MAP = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "3PM": "tpm",
}

def grade_picks(picks: list[dict], game_log: pd.DataFrame) -> list[dict]:
    """
    Match each pick to yesterday's box score row and grade as HIT/MISS/NO_DATA.
    Returns enriched picks with result and actual_value filled in.
    """
    yesterday_log = game_log[game_log["game_date"] == YESTERDAY_STR].copy()

    graded = []
    for pick in picks:
        p = pick.copy()
        player_name = p.get("player_name", "")
        prop_type = p.get("prop_type", "")
        pick_value = p.get("pick_value")
        team = p.get("team", "")

        col = PROP_COL_MAP.get(prop_type)
        if not col:
            p["result"] = "NO_DATA"
            p["actual_value"] = None
            graded.append(p)
            continue

        # Match by player name (case-insensitive) and team
        mask = yesterday_log["player_name"].str.lower() == player_name.lower()
        if team:
            team_mask = yesterday_log["team_abbrev"].str.upper() == team.upper()
            row = yesterday_log[mask & team_mask]
            if row.empty:
                row = yesterday_log[mask]  # fallback: name only
        else:
            row = yesterday_log[mask]

        if row.empty:
            # Player didn't appear in box score — likely DNP or game not yet ingested
            p["result"] = "NO_DATA"
            p["actual_value"] = None
        else:
            actual = pd.to_numeric(row.iloc[0][col], errors="coerce")
            p["actual_value"] = float(actual) if pd.notna(actual) else None

            if p["actual_value"] is None:
                p["result"] = "NO_DATA"
            elif p["actual_value"] > float(pick_value):
                p["result"] = "HIT"
            else:
                p["result"] = "MISS"

        graded.append(p)

    return graded


# ── Prompt builder ───────────────────────────────────────────────────

def build_audit_prompt(graded_picks: list[dict]) -> str:
    hits   = [p for p in graded_picks if p["result"] == "HIT"]
    misses = [p for p in graded_picks if p["result"] == "MISS"]
    no_data = [p for p in graded_picks if p["result"] == "NO_DATA"]

    total_gradeable = len(hits) + len(misses)
    hit_rate = round(100 * len(hits) / total_gradeable, 1) if total_gradeable > 0 else 0

    picks_block = json.dumps(graded_picks, indent=2)

    return f"""You are the Auditor for NBAgent, an NBA player props selection system.

Today is {dt.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")}.
You are auditing picks made for {YESTERDAY_STR}.

## GRADED RESULTS SUMMARY
- Total picks: {len(graded_picks)}
- Hits: {len(hits)}
- Misses: {len(misses)}
- No data (DNP/missing): {len(no_data)}
- Hit rate (gradeable only): {hit_rate}%

## FULL GRADED PICKS
{picks_block}

## YOUR TASK
1. For each HIT: identify what the Analyst got right (specific statistical patterns, matchup reads, etc.)
2. For each MISS: perform root cause analysis. Was it a bad line? Ignored injury impact? Overweighted season avg vs recent form? Wrong matchup read? Variance?
3. Synthesize 3–5 concrete, actionable recommendations for the Analyst's next run.

Focus on patterns across multiple picks, not just individual flukes.
Be specific — reference player names, prop types, and numbers.

## OUTPUT FORMAT
Respond ONLY with valid JSON. No preamble.

{{
  "date": "{YESTERDAY_STR}",
  "total_picks": {len(graded_picks)},
  "hits": {len(hits)},
  "misses": {len(misses)},
  "no_data": {len(no_data)},
  "hit_rate_pct": {hit_rate},
  "reinforcements": [
    "string: what worked and why — be specific"
  ],
  "lessons": [
    "string: what failed and why — be specific"
  ],
  "recommendations": [
    "string: concrete instruction for the Analyst to adjust selection logic"
  ],
  "miss_details": [
    {{
      "player_name": "string",
      "prop_type": "string",
      "pick_value": number,
      "actual_value": number,
      "root_cause": "string"
    }}
  ]
}}
"""


# ── Claude call ──────────────────────────────────────────────────────

def call_auditor(prompt: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[auditor] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[auditor] Calling Claude ({MODEL})...")
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Response is not a JSON object")
        return result
    except Exception as e:
        print(f"[auditor] ERROR parsing Claude response: {e}")
        print(f"[auditor] Raw response:\n{raw}")
        sys.exit(1)


# ── Output ───────────────────────────────────────────────────────────

def save_audit(audit_entry: dict, graded_picks: list[dict]):
    # Update picks.json with graded results
    all_picks = []
    if PICKS_JSON.exists():
        with open(PICKS_JSON, "r") as f:
            all_picks = json.load(f)

    # Replace yesterday's picks with graded versions
    non_yesterday = [p for p in all_picks if p.get("date") != YESTERDAY_STR]
    updated_picks = non_yesterday + graded_picks

    with open(PICKS_JSON, "w") as f:
        json.dump(updated_picks, f, indent=2)

    print(f"[auditor] Updated picks.json with graded results")

    # Append to audit_log.json
    existing_log = []
    if AUDIT_LOG_JSON.exists():
        try:
            with open(AUDIT_LOG_JSON, "r") as f:
                existing_log = json.load(f)
            if not isinstance(existing_log, list):
                existing_log = []
        except Exception:
            existing_log = []

    # Remove any existing entry for yesterday (idempotent)
    existing_log = [e for e in existing_log if e.get("date") != YESTERDAY_STR]
    existing_log.append(audit_entry)

    with open(AUDIT_LOG_JSON, "w") as f:
        json.dump(existing_log, f, indent=2)

    print(f"[auditor] Saved audit entry for {YESTERDAY_STR} → {AUDIT_LOG_JSON}")


def print_summary(graded_picks: list[dict], audit_entry: dict):
    hits   = [p for p in graded_picks if p["result"] == "HIT"]
    misses = [p for p in graded_picks if p["result"] == "MISS"]

    print(f"\n{'='*50}")
    print(f"AUDIT SUMMARY — {YESTERDAY_STR}")
    print(f"{'='*50}")
    print(f"Hit rate: {audit_entry.get('hit_rate_pct', '?')}% ({len(hits)}/{len(hits)+len(misses)} gradeable)")

    if hits:
        print(f"\n✓ HITS ({len(hits)}):")
        for p in hits:
            print(f"  {p['player_name']} {p['prop_type']} OVER {p['pick_value']} → actual {p['actual_value']}")

    if misses:
        print(f"\n✗ MISSES ({len(misses)}):")
        for p in misses:
            print(f"  {p['player_name']} {p['prop_type']} OVER {p['pick_value']} → actual {p['actual_value']}")

    print(f"\nRecommendations for Analyst:")
    for r in audit_entry.get("recommendations", []):
        print(f"  → {r}")
    print()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[auditor] Running for {YESTERDAY_STR}")

    picks = load_yesterdays_picks()
    if not picks:
        sys.exit(0)

    game_log = load_game_log()
    print(f"[auditor] Loaded {len(game_log)} game log rows")

    graded_picks = grade_picks(picks, game_log)

    hits   = sum(1 for p in graded_picks if p["result"] == "HIT")
    misses = sum(1 for p in graded_picks if p["result"] == "MISS")
    print(f"[auditor] Graded: {hits} hits, {misses} misses, {len(graded_picks)-hits-misses} no data")

    if hits + misses == 0:
        print("[auditor] No gradeable picks (all NO_DATA). Box scores may not be ingested yet.")
        sys.exit(0)

    prompt = build_audit_prompt(graded_picks)
    audit_entry = call_auditor(prompt)

    save_audit(audit_entry, graded_picks)
    print_summary(graded_picks, audit_entry)


if __name__ == "__main__":
    main()
