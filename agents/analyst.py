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

MASTER_CSV        = DATA / "nba_master.csv"
GAME_LOG_CSV      = DATA / "player_game_log.csv"
DIM_CSV           = DATA / "player_dim.csv"
INJURIES_JSON     = DATA / "injuries_today.json"
AUDIT_LOG_JSON    = DATA / "audit_log.json"
PICKS_JSON        = DATA / "picks.json"
PLAYER_STATS_JSON = DATA / "player_stats.json"
WHITELIST_CSV     = ROOT / "playerprops" / "player_whitelist.csv"

ET = ZoneInfo("America/New_York")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ───────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16384
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


def load_player_stats() -> dict:
    """Load pre-computed player stats from stats_builder output."""
    if not PLAYER_STATS_JSON.exists():
        print(f"[analyst] WARNING: player_stats.json not found — falling back to empty context.")
        return {}
    try:
        with open(PLAYER_STATS_JSON, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[analyst] WARNING: could not load player_stats.json: {e}")
        return {}


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


def build_player_context(player_stats: dict) -> str:
    """
    Convert pre-computed player stats cards into a compact prompt block.
    One player per section; all signal is pre-digested.
    """
    if not player_stats:
        return "No player stats data available."

    lines = []
    for player_name, s in sorted(player_stats.items()):
        team     = s.get("team", "?")
        opponent = s.get("opponent", "?")
        b2b      = " [B2B]" if s.get("on_back_to_back") else ""
        games_n  = s.get("games_available", 0)
        mins     = s.get("avg_minutes_last5", "?")
        m_trend  = s.get("minutes_trend", "stable")

        best     = s.get("best_tiers", {})
        trend    = s.get("trend", {})
        splits   = s.get("home_away_splits", {})
        raw      = s.get("raw_avgs", {})
        opp_def  = s.get("opp_defense") or {}

        # Build stat lines — only include stats with a qualifying best tier
        stat_lines = []
        for stat in ["PTS", "REB", "AST", "3PM"]:
            bt = best.get(stat)
            if not bt:
                continue
            tr    = trend.get(stat, "stable")
            ha    = splits.get(stat, {})
            h_bt  = ha.get("H")
            a_bt  = ha.get("A")
            split_str = ""
            if h_bt and a_bt:
                split_str = f" | H:{int(h_bt['hit_rate']*100)}% A:{int(a_bt['hit_rate']*100)}%"
            elif h_bt:
                split_str = f" | H:{int(h_bt['hit_rate']*100)}%"
            elif a_bt:
                split_str = f" | A:{int(a_bt['hit_rate']*100)}%"

            opp_stat = opp_def.get(stat, {})
            opp_str  = f" | opp allows {opp_stat.get('allowed_pg','?')} {stat}/g ({opp_stat.get('rating','?')} defense, #{opp_stat.get('rank','?')})" if opp_stat else ""

            stat_lines.append(
                f"  {stat}: floor={bt['tier']} hit={int(bt['hit_rate']*100)}%"
                f" trend={tr}{split_str}{opp_str}"
            )

        if not stat_lines:
            continue  # no qualifying tiers — skip entirely

        lines.append(
            f"\n{player_name} ({team} vs {opponent}{b2b}) "
            f"| {games_n}g | {mins}min avg ({m_trend})"
        )
        lines.extend(stat_lines)

    return "\n".join(lines) if lines else "No players with qualifying tier hit rates today."


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
    games_block    = json.dumps(games, indent=2)
    injuries_block = json.dumps(injuries, indent=2)

    return f"""You are the Analyst for NBAgent, an NBA player props selection system.

Today is {TODAY_STR}.

## YOUR TASK
Select high-confidence player prop picks for today's games. Focus on:
- Points (PTS)
- Rebounds (REB)
- Assists (AST)
- 3-pointers made (3PM)

## TIER SYSTEM
Picks use fixed tier thresholds only. No arbitrary lines.

  PTS tiers:  10 / 15 / 20 / 25 / 30
  REB tiers:  2 / 4 / 6 / 8 / 10 / 12
  AST tiers:  2 / 4 / 6 / 8 / 10 / 12
  3PM tiers:  1 / 2 / 3 / 4

Each player's stats card already shows the highest tier with ≥70% hit rate (the "floor").
Your job is to validate that floor and set confidence, then decide whether to pick it.

## HOW TO READ THE STATS CARD
Each player entry shows:
  STAT: floor=<tier> hit=<pct>% trend=<up/stable/down> | H:<pct>% A:<pct>% | opp allows X/g (<rating> defense, #N)

- floor: highest tier clearing 70% in last 10 games — this is your pick_value
- hit%: exact hit rate at that tier
- trend: last 5 vs last 10 average — up/down/stable
- H/A splits: hit rate at that tier home vs away — use this when today's game is H or A
- opp defense: how many of this stat the opponent allows per game, their rank, and rating (tough/mid/soft)
- [B2B]: player's team is on a back-to-back today — apply caution, especially for PTS/minutes
- mins avg: average minutes last 5 games — flag if low (<25) or declining

## SELECTION RULES
- Only pick stats that appear in a player's card (pre-filtered to ≥70% floor)
- Adjust confidence up/down based on: trend direction, H/A split for today's context, opponent rating, B2B flag
- Skip players listed as OUT or DOUBTFUL in the injury report
- Pick as many qualifying props as there are — don't limit volume
- Only output picks with confidence_pct ≥ 70

## TODAY'S GAMES
{games_block}

## CURRENT INJURY REPORT
{injuries_block}

## PLAYER STATS CARDS
{player_context}

## AUDITOR FEEDBACK FROM PREVIOUS DAYS
{audit_context}

## OUTPUT FORMAT
Respond ONLY with a valid JSON array. No preamble, no explanation outside the JSON.

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
    "reasoning": "2-3 sentences: cite the floor hit rate, note trend/split/matchup context that raises or tempers confidence"
  }}
]

pick_value must be one of the valid tier values listed above.
direction is always OVER.
Only include picks with confidence_pct >= 70.
"""


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

    injuries = load_injuries(teams_today)
    print(f"[analyst] Loaded injuries for {len(injuries)} of {len(teams_today)} teams playing today")

    audit_entries = load_audit_feedback()
    print(f"[analyst] Loaded {len(audit_entries)} audit log entries")

    player_stats = load_player_stats()
    print(f"[analyst] Loaded stats cards for {len(player_stats)} players")

    player_context = build_player_context(player_stats)

    audit_context = build_audit_context(audit_entries)

    prompt = build_prompt(games, player_context, injuries, audit_context)

    picks = call_analyst(prompt)
    print(f"[analyst] Claude returned {len(picks)} picks")

    save_picks(picks)


if __name__ == "__main__":
    main()
