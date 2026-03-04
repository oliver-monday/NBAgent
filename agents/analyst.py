#!/usr/bin/env python3
"""
NBAgent — Analyst

Reads today's game slate, recent player performance, injury context,
and historical audit feedback. Calls Claude to select high-confidence
player prop picks for Points, Rebounds, Assists, and 3-pointers made.

Writes output to data/picks.json.
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

MASTER_CSV     = DATA / "nba_master.csv"
GAME_LOG_CSV   = DATA / "player_game_log.csv"
DIM_CSV        = DATA / "player_dim.csv"
INJURIES_JSON  = DATA / "injuries_today.json"
AUDIT_LOG_JSON = DATA / "audit_log.json"
PICKS_JSON     = DATA / "picks.json"

ET = ZoneInfo("America/New_York")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ───────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192
# How many recent games to include per player in the prompt
RECENT_GAME_WINDOW = 10
# How many audit log entries to feed back as context (keep lean)
AUDIT_CONTEXT_ENTRIES = 5


# ── Data loaders ─────────────────────────────────────────────────────

def load_todays_games() -> list[dict]:
    """Return today's scheduled games from nba_master.csv."""
    if not MASTER_CSV.exists():
        print(f"[analyst] ERROR: {MASTER_CSV} not found.")
        sys.exit(1)

    df = pd.read_csv(MASTER_CSV, dtype=str)
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    today_games = df[df["game_date"] == TODAY_STR].copy()

    if today_games.empty:
        print(f"[analyst] No games found for {TODAY_STR}. Nothing to pick.")
        sys.exit(0)

    games = []
    for _, row in today_games.iterrows():
        games.append({
            "game_id": row.get("game_id", ""),
            "game_time_utc": row.get("game_time_utc", ""),
            "home_team": row.get("home_team_name", ""),
            "home_abbrev": row.get("home_team_abbrev", ""),
            "away_team": row.get("away_team_name", ""),
            "away_abbrev": row.get("away_team_abbrev", ""),
            "venue_city": row.get("venue_city", ""),
            "home_injuries": row.get("home_injuries", "") or "",
            "away_injuries": row.get("away_injuries", "") or "",
        })
    return games


def load_player_game_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    # Exclude today (no results yet) and DNPs
    df = df[df["game_date"] < TODAY_STR].copy()
    df = df[df["dnp"].astype(str) != "1"].copy()
    return df


def load_injuries(teams_today: list[str]) -> dict:
    if not INJURIES_JSON.exists():
        return {}
    try:
        with open(INJURIES_JSON, "r") as f:
            raw = json.load(f)
        # Strip metadata keys, keep team dicts — filtered to today's teams only
        teams_upper = {t.upper() for t in teams_today}
        return {k: v for k, v in raw.items() if isinstance(v, list) and k.upper() in teams_upper}
    except Exception:
        return {}


def load_audit_feedback() -> list[dict]:
    if not AUDIT_LOG_JSON.exists():
        return []
    try:
        with open(AUDIT_LOG_JSON, "r") as f:
            entries = json.load(f)
        if not isinstance(entries, list):
            return []
        # Return most recent N entries
        return entries[-AUDIT_CONTEXT_ENTRIES:]
    except Exception:
        return []


def build_player_context(game_log: pd.DataFrame, teams_today: list[str]) -> str:
    """
    For players on teams playing today, build a compact recent-performance
    summary string to include in the prompt.
    """
    if game_log.empty:
        return "No player game log data available."

    recent = game_log[game_log["team_abbrev"].isin(teams_today)].copy()
    if recent.empty:
        return "No recent game log data for today's teams."

    # Sort by date descending, take last N games per player
    recent = recent.sort_values("game_date", ascending=False)
    recent = recent.groupby("player_id").head(RECENT_GAME_WINDOW).copy()

    lines = []
    for player_name, grp in recent.groupby("player_name"):
        grp = grp.sort_values("game_date", ascending=False)
        team = grp["team_abbrev"].iloc[0]
        games = []
        for _, r in grp.iterrows():
            games.append(
                f"{r['game_date']} vs {r['opp_abbrev']} "
                f"({'H' if r['home_away']=='H' else 'A'}): "
                f"{r['pts']}pts {r['reb']}reb {r['ast']}ast {r['tpm']}3pm "
                f"{r['minutes']}min"
            )
        lines.append(f"\n{player_name} ({team}):\n  " + "\n  ".join(games))

    return "\n".join(lines)


def build_audit_context(audit_entries: list[dict]) -> str:
    if not audit_entries:
        return "No prior audit feedback available yet."

    lines = ["Recent Auditor feedback (use this to refine your selections):"]
    for e in reversed(audit_entries):
        date = e.get("date", "?")
        hit_rate = e.get("hit_rate_pct", "?")
        hits = e.get("hits", 0)
        misses = e.get("misses", 0)
        lines.append(f"\n[{date}] Hit rate: {hit_rate}% ({hits} hits, {misses} misses)")

        if e.get("reinforcements"):
            lines.append("  What worked:")
            for r in e["reinforcements"][:3]:
                lines.append(f"    • {r}")

        if e.get("lessons"):
            lines.append("  What to avoid:")
            for l in e["lessons"][:3]:
                lines.append(f"    • {l}")

        if e.get("recommendations"):
            lines.append("  Analyst recommendations:")
            for r in e["recommendations"][:3]:
                lines.append(f"    • {r}")

    return "\n".join(lines)


# ── Prompt builder ───────────────────────────────────────────────────

def build_prompt(games: list[dict], player_context: str, injuries: dict, audit_context: str) -> str:
    games_block = json.dumps(games, indent=2)
    injuries_block = json.dumps(injuries, indent=2)

    return f"""You are the Analyst for NBAgent, an NBA player props selection system.

Today is {TODAY_STR}.

## YOUR TASK
Select high-confidence player prop picks for today's games. Focus on:
- Points (PTS)
- Rebounds (REB)
- Assists (AST)
- 3-pointers made (3PM)

## SELECTION PHILOSOPHY
- Prioritize SAFE, high hit-rate thresholds over "reach" picks
- Season averages can be misleading — weight recent form (last 5–10 games) heavily
- Consider matchup context: opponent's defensive stats, pace, home/away splits
- Factor in rest/back-to-back situations
- Injuries to key teammates change usage — factor this in
- Only pick players with enough recent data (minimum 5 games)
- Skip players listed as OUT or DOUBTFUL
- Express confidence as a percentage (only include picks with ≥70% confidence)
- Pick as many qualifying props as there are — don't artificially limit volume

## TODAY'S GAMES
{games_block}

## CURRENT INJURY REPORT
{injuries_block}

## PLAYER RECENT PERFORMANCE (last {RECENT_GAME_WINDOW} games)
{player_context}

## AUDITOR FEEDBACK FROM PREVIOUS DAYS
{audit_context}

## OUTPUT FORMAT
Respond ONLY with a valid JSON array. No preamble, no explanation outside the JSON.
Each pick must follow this exact schema:

[
  {{
    "date": "{TODAY_STR}",
    "player_name": "string",
    "team": "string (abbrev)",
    "opponent": "string (abbrev)",
    "home_away": "H or A",
    "prop_type": "PTS | REB | AST | 3PM",
    "pick_value": number,
    "direction": "OVER",
    "confidence_pct": number (70-99),
    "reasoning": "2-3 sentence statistical justification referencing specific recent numbers"
  }}
]

Pick value should be the threshold the player needs to EXCEED (i.e., the line).
Always set direction to OVER — we only pick overs on safe floors.
Only include picks with confidence_pct >= 70.
"""


# ── Claude call ──────────────────────────────────────────────────────

def call_analyst(prompt: str) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[analyst] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    print(f"[analyst] Calling Claude ({MODEL})...")
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        picks = json.loads(raw)
        if not isinstance(picks, list):
            raise ValueError("Response is not a JSON array")
        return picks
    except Exception as e:
        print(f"[analyst] ERROR parsing Claude response: {e}")
        print(f"[analyst] Raw response:\n{raw}")
        sys.exit(1)


# ── Output ───────────────────────────────────────────────────────────

def save_picks(picks: list[dict]):
    # Load existing picks (from prior days), append today's
    existing = []
    if PICKS_JSON.exists():
        try:
            with open(PICKS_JSON, "r") as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # Remove any existing picks for today (idempotent re-run)
    existing = [p for p in existing if p.get("date") != TODAY_STR]

    # Tag each pick with a result field (filled by auditor later)
    for p in picks:
        p["result"] = None
        p["actual_value"] = None

    updated = existing + picks

    with open(PICKS_JSON, "w") as f:
        json.dump(updated, f, indent=2)

    print(f"[analyst] Saved {len(picks)} picks for {TODAY_STR} → {PICKS_JSON}")
    for p in picks:
        print(f"  {p['player_name']} {p['prop_type']} OVER {p['pick_value']} ({p['confidence_pct']}%) — {p['reasoning'][:80]}...")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[analyst] Running for {TODAY_STR}")

    games = load_todays_games()
    print(f"[analyst] Found {len(games)} games today")

    teams_today = list({g["home_abbrev"] for g in games} | {g["away_abbrev"] for g in games})

    game_log = load_player_game_log()
    print(f"[analyst] Loaded {len(game_log)} player game log rows")

    injuries = load_injuries(teams_today)
    print(f"[analyst] Loaded injuries for {len(injuries)} of {len(teams_today)} teams playing today")

    audit_entries = load_audit_feedback()
    print(f"[analyst] Loaded {len(audit_entries)} audit log entries")

    player_context = build_player_context(game_log, teams_today)

    audit_context = build_audit_context(audit_entries)

    prompt = build_prompt(games, player_context, injuries, audit_context)

    picks = call_analyst(prompt)
    print(f"[analyst] Claude returned {len(picks)} picks")

    save_picks(picks)


if __name__ == "__main__":
    main()
