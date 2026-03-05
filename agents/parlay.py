#!/usr/bin/env python3
"""
NBAgent — Parlay Agent

Runs after Analyst. Reads today's picks from data/picks.json and
pre-computed correlation/pace data from data/player_stats.json.

Logic:
  1. Build all valid 2–6 leg combinations from today's picks
  2. Filter to combinations whose confidence product implies ≥ +100 American odds
  3. Score combinations on: confidence product, floor confidence (weakest leg),
     correlation quality, and game spread
  4. Pass top scored combinations to Claude for final selection + rationale
  5. Write 3–5 curated parlays to data/parlays.json

Implied odds formula (assuming independent legs):
  combined_prob = product of (confidence_pct / 100) for each leg
  american_odds = ((1 / combined_prob) - 1) * 100  [if prob < 0.5]
               = -100 / ((1 / combined_prob) - 1)  [if prob >= 0.5, i.e. favorite]
  Target: american_odds >= +100  →  combined_prob <= 0.50
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

# ── Paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PICKS_JSON        = DATA / "picks.json"
PLAYER_STATS_JSON = DATA / "player_stats.json"
PARLAYS_JSON      = DATA / "parlays.json"
AUDIT_LOG_JSON    = DATA / "audit_log.json"

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ────────────────────────────────────────────────────────────
MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 4096

MIN_LEGS = 2
MAX_LEGS = 6
TARGET_MIN_ODDS = 100   # +100 American
TARGET_MAX_ODDS = 600   # soft ceiling — avoid ultra-long shots
MIN_CONFIDENCE  = 70    # individual leg floor
TOP_N_TO_CLAUDE = 15    # how many pre-scored combos to send Claude
AUDIT_CONTEXT_ENTRIES = 3  # keep lean — parlay prompt is already large

# Correlation scoring weights
CORR_BONUS = {
    "feeder_target":       +0.10,
    "volume_game":         +0.05,
    "pace_beneficiary":    +0.05,
    "positively_correlated": +0.05,
    "independent":          0.00,
    "insufficient_data":    0.00,
    "board_rivals":        -0.05,
    "scoring_rivals":      -0.10,
    "negatively_correlated": -0.08,
}


# ── Helpers ───────────────────────────────────────────────────────────

def american_odds(combined_prob: float) -> int:
    """Convert combined probability to American odds integer."""
    if combined_prob <= 0 or combined_prob >= 1:
        return 0
    if combined_prob < 0.5:
        return round(((1 / combined_prob) - 1) * 100)
    else:
        return round(-100 / ((1 / combined_prob) - 1))


def odds_in_target(odds: int) -> bool:
    return TARGET_MIN_ODDS <= odds <= TARGET_MAX_ODDS


def format_odds(odds: int) -> str:
    return f"+{odds}" if odds >= 0 else str(odds)


# ── Loaders ───────────────────────────────────────────────────────────

def load_todays_picks() -> list[dict]:
    if not PICKS_JSON.exists():
        return []
    with open(PICKS_JSON) as f:
        all_picks = json.load(f)
    picks = [
        p for p in all_picks
        if p.get("date") == TODAY_STR
        and p.get("confidence_pct", 0) >= MIN_CONFIDENCE
        and p.get("result") is None  # ungraded = today's picks
    ]
    return picks


def load_player_stats() -> dict:
    if not PLAYER_STATS_JSON.exists():
        return {}
    with open(PLAYER_STATS_JSON) as f:
        return json.load(f)


def load_parlay_audit_feedback() -> str:
    """
    Load the most recent parlay audit feedback from audit_log.json.
    Returns a formatted string summarising parlay hits/misses and lessons
    from the last AUDIT_CONTEXT_ENTRIES days, most-recent first.
    Returns empty string gracefully if file is missing or no parlay data exists.
    """
    if not AUDIT_LOG_JSON.exists():
        return ""
    try:
        with open(AUDIT_LOG_JSON) as f:
            entries = json.load(f)
        if not isinstance(entries, list) or not entries:
            return ""
        recent = entries[-AUDIT_CONTEXT_ENTRIES:]
    except Exception:
        return ""

    lines = ["Recent parlay audit feedback (use to improve combination selection):"]
    for e in reversed(recent):
        date = e.get("date", "?")
        pr = e.get("parlay_results", {})
        if not pr:
            continue
        lines.append(
            f"\n[{date}] Parlays: {pr.get('hits', 0)} hit / "
            f"{pr.get('misses', 0)} missed of {pr.get('total', 0)}"
        )
        for r in pr.get("parlay_reinforcements", [])[:2]:
            lines.append(f"  ✓ {r}")
        for l in pr.get("parlay_lessons", [])[:2]:
            lines.append(f"  ✗ {l}")

    return "\n".join(lines)


# ── Correlation lookup ────────────────────────────────────────────────

def get_correlation_tag(p1: dict, p2: dict, player_stats: dict) -> str:
    """
    Look up the correlation tag between two picks.
    Returns a tag string from CORR_BONUS keys.
    """
    name1 = p1["player_name"]
    name2 = p2["player_name"]
    stat1 = p1["prop_type"]
    stat2 = p2["prop_type"]

    # Cross-game legs: check if they share a pace context
    if p1.get("team") != p2.get("team") and p1.get("opponent") != p2.get("team"):
        # Different games entirely — check pace
        s1 = player_stats.get(name1, {})
        pace = (s1.get("game_pace") or {}).get("pace_tag", "mid")
        if pace == "high" and stat1 == "PTS" and stat2 == "PTS":
            return "volume_game"
        return "independent"

    # Same-game, different teams (e.g. both teams score in a shootout)
    if p1.get("team") != p2.get("team"):
        s1 = player_stats.get(name1, {})
        pace = (s1.get("game_pace") or {}).get("pace_tag", "mid")
        if pace == "high":
            return "volume_game"
        return "independent"

    # Same team — look up precomputed correlation
    s1 = player_stats.get(name1, {})
    teammate_corrs = s1.get("teammate_correlations", {})
    pair_data = teammate_corrs.get(name2, {})
    corrs = pair_data.get("correlations", {})

    # Find the most relevant correlation key for these two prop types
    key = f"{stat1}_{stat2}"
    alt_key = f"{stat2}_{stat1}"
    entry = corrs.get(key) or corrs.get(alt_key)

    if entry:
        return entry.get("tag", "independent")

    return "independent"


# ── Combination scoring ───────────────────────────────────────────────

def score_combination(legs: list[dict], player_stats: dict) -> dict:
    """
    Score a parlay combination. Returns a scored dict with all metadata
    needed for Claude's prompt and the final output schema.
    """
    probs      = [p["confidence_pct"] / 100 for p in legs]
    combined_p = 1.0
    for p in probs:
        combined_p *= p
    odds = american_odds(combined_p)

    floor_conf  = min(p["confidence_pct"] for p in legs)
    avg_conf    = sum(p["confidence_pct"] for p in legs) / len(legs)

    # Games represented
    games_set = set()
    for p in legs:
        home = p["team"] if p.get("home_away") == "H" else p.get("opponent", "")
        away = p["team"] if p.get("home_away") == "A" else p.get("opponent", "")
        games_set.add(f"{away}@{home}")
    n_games = len(games_set)

    # Correlation scoring across all pairs
    corr_score  = 0.0
    corr_tags   = []
    for p1, p2 in combinations(legs, 2):
        tag = get_correlation_tag(p1, p2, player_stats)
        corr_tags.append(tag)
        corr_score += CORR_BONUS.get(tag, 0.0)

    # Determine dominant correlation type
    if any(t in ("feeder_target", "volume_game", "pace_beneficiary",
                 "positively_correlated") for t in corr_tags):
        correlation = "positive"
    elif any(t in ("scoring_rivals", "board_rivals",
                   "negatively_correlated") for t in corr_tags):
        correlation = "negative"
    else:
        correlation = "independent"

    # Parlay type
    same_game_legs = [l for l in legs if any(
        l["team"] == other["opponent"] or l["opponent"] == other["team"]
        for other in legs if other is not l
    )]
    if n_games == 1:
        parlay_type = "same_game_stack"
    elif n_games == len(legs):
        parlay_type = "multi_game"
    else:
        parlay_type = "mixed"

    # Composite score: higher = better
    # Weights: confidence product (main driver) + floor bonus + corr bonus + spread bonus
    composite = (
        combined_p * 100          # base: confidence product scaled
        + floor_conf * 0.3        # reward high floor
        + avg_conf * 0.2          # reward high average
        + corr_score * 10         # correlation quality
        + (n_games - 1) * 2       # reward game spread
    )

    return {
        "legs": legs,
        "n_legs": len(legs),
        "combined_prob": round(combined_p, 4),
        "implied_odds": format_odds(odds),
        "implied_odds_int": odds,
        "floor_confidence": floor_conf,
        "avg_confidence": round(avg_conf, 1),
        "correlation": correlation,
        "corr_tags": corr_tags,
        "parlay_type": parlay_type,
        "n_games": n_games,
        "composite_score": round(composite, 2),
    }


def build_candidates(picks: list[dict], player_stats: dict) -> list[dict]:
    """
    Generate all valid 2–6 leg combinations, filter to target odds window,
    sort by composite score, return top N.
    """
    candidates = []

    for n in range(MIN_LEGS, MAX_LEGS + 1):
        for combo in combinations(picks, n):
            legs = list(combo)

            # Skip: duplicate player in same combo
            names = [l["player_name"] for l in legs]
            if len(names) != len(set(names)):
                continue

            probs = [l["confidence_pct"] / 100 for l in legs]
            combined_p = 1.0
            for p in probs:
                combined_p *= p
            odds = american_odds(combined_p)

            if not odds_in_target(odds):
                continue

            # Skip combos with known negative correlations between same-team players
            has_negative = False
            for p1, p2 in combinations(legs, 2):
                if p1.get("team") == p2.get("team"):
                    tag = get_correlation_tag(p1, p2, player_stats)
                    if tag in ("scoring_rivals", "board_rivals"):
                        has_negative = True
                        break
            if has_negative:
                continue

            scored = score_combination(legs, player_stats)
            candidates.append(scored)

    # Sort by composite score descending
    candidates.sort(key=lambda c: c["composite_score"], reverse=True)
    return candidates[:TOP_N_TO_CLAUDE]


# ── Prompt builder ────────────────────────────────────────────────────

def build_parlay_prompt(candidates: list[dict], audit_feedback: str = "") -> str:
    # Slim down legs for prompt — Claude doesn't need full pick objects
    slim = []
    for i, c in enumerate(candidates):
        slim_legs = [
            {
                "player": l["player_name"],
                "team": l["team"],
                "opp": l.get("opponent", ""),
                "prop": l["prop_type"],
                "over": l["pick_value"],
                "conf": l["confidence_pct"],
                "hit_rate": l.get("hit_rate_display", ""),
                "trend": l.get("trend", ""),
                "opp_def": l.get("opp_defense_rating", ""),
            }
            for l in c["legs"]
        ]
        slim.append({
            "rank": i + 1,
            "n_legs": c["n_legs"],
            "implied_odds": c["implied_odds"],
            "floor_conf": c["floor_confidence"],
            "avg_conf": c["avg_confidence"],
            "correlation": c["correlation"],
            "corr_tags": list(set(c["corr_tags"])),
            "type": c["parlay_type"],
            "n_games": c["n_games"],
            "composite_score": c["composite_score"],
            "legs": slim_legs,
        })

    candidates_block = json.dumps(slim, indent=2)

    return f"""You are the Parlay Agent for NBAgent, an NBA player props prediction system.

Today is {TODAY_STR}.

## YOUR TASK
Select 3–5 of the best parlay combinations from the pre-scored candidates below.
Each candidate has already passed:
  - Implied odds filter: +100 to +600 American
  - Minimum 70% confidence per leg
  - No known negative teammate correlations (scoring_rivals, board_rivals)

## SELECTION CRITERIA — in priority order
1. **Implied odds target**: prefer +100 to +300. Above +300 is fine if all legs are very strong.
2. **Floor confidence**: the weakest leg matters most. Prefer combos where even the weakest leg is ≥75%.
3. **Positive correlation**: "feeder_target" and "volume_game" tags mean legs tend to win together — prefer these.
4. **Game spread**: multi-game parlays are more robust than same-game stacks (same-game stacks are fine if correlation is genuinely positive).
5. **Variety**: across your 3–5 selections, aim for a mix of leg counts (some tight 2-leggers, some 3–4 leg plays, maybe one 5+ if all legs are elite).

## AVOID
- Two parlays that share 3+ identical legs (provide variety)
- Combos where the rationale would be "all soft matchups" with no deeper logic
- Overly cautious 2-leggers at +100 when a 3-legger with better correlation exists at +120

## PARLAY AUDIT FEEDBACK FROM PREVIOUS DAYS
{audit_feedback if audit_feedback else "No prior parlay audit data available."}

## PRE-SCORED CANDIDATES
{candidates_block}

## OUTPUT FORMAT
Respond ONLY with a valid JSON array. No preamble, no explanation outside the JSON.

[
  {{
    "label": "short evocative name, 2-4 words, e.g. 'NYK Feeder Stack' or 'Wednesday Sweeper'",
    "type": "same_game_stack | multi_game | mixed",
    "legs": [
      {{
        "player_name": "string",
        "team": "abbrev",
        "opponent": "abbrev",
        "prop_type": "PTS | REB | AST | 3PM",
        "pick_value": number,
        "direction": "OVER",
        "confidence_pct": number,
        "correlation_role": "feeder | target | scorer | rebounder | independent | pace_play"
      }}
    ],
    "implied_odds": "+NNN",
    "confidence_product": number (0–1, 4 decimal places),
    "correlation": "positive | independent | mixed",
    "rationale": "One tight sentence: WHY these legs belong together. Reference matchup, role, or correlation. Max 20 words."
  }}
]
"""


# ── Claude call ───────────────────────────────────────────────────────

def call_parlay_agent(prompt: str) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[parlay] ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    print(f"[parlay] Calling Claude ({MODEL})...")

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
        parlays = json.loads(raw)
        if not isinstance(parlays, list):
            raise ValueError("Response is not a JSON array")
        return parlays
    except Exception as e:
        print(f"[parlay] ERROR parsing Claude response: {e}")
        print(f"[parlay] Raw response:\n{raw}")
        sys.exit(1)


# ── Output ────────────────────────────────────────────────────────────

def save_parlays(parlays: list[dict]):
    existing = []
    if PARLAYS_JSON.exists():
        try:
            with open(PARLAYS_JSON) as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # Remove today's parlays (idempotent re-run)
    existing = [p for p in existing if p.get("date") != TODAY_STR]

    # Add metadata
    for i, p in enumerate(parlays):
        p["date"]      = TODAY_STR
        p["id"]        = f"parlay_{TODAY_STR}_{i+1:02d}"
        p["result"]    = None
        p["legs_hit"]  = None
        p["legs_total"] = len(p.get("legs", []))

    updated = existing + [{
        "date": TODAY_STR,
        "parlays": parlays
    }]

    # Actually store as flat list of dated bundles
    # Re-structure: keep a list of daily bundles
    with open(PARLAYS_JSON, "w") as f:
        json.dump(updated, f, indent=2)

    print(f"[parlay] Saved {len(parlays)} parlays for {TODAY_STR} → {PARLAYS_JSON}")
    for p in parlays:
        legs_str = " | ".join(
            f"{l['player_name']} {l['prop_type']} OVER {l['pick_value']}"
            for l in p.get("legs", [])
        )
        print(f"  [{p['implied_odds']}] {p['label']}: {legs_str}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[parlay] Running for {TODAY_STR}")

    picks = load_todays_picks()
    print(f"[parlay] Loaded {len(picks)} eligible picks for today")

    if len(picks) < MIN_LEGS:
        print(f"[parlay] Not enough picks ({len(picks)}) to build parlays. Exiting.")
        sys.exit(0)

    player_stats = load_player_stats()
    print(f"[parlay] Loaded player stats for {len(player_stats)} players")

    candidates = build_candidates(picks, player_stats)
    print(f"[parlay] Built {len(candidates)} scored candidates (top {TOP_N_TO_CLAUDE} sent to Claude)")

    if not candidates:
        print("[parlay] No valid combinations found in target odds range. Exiting.")
        sys.exit(0)

    audit_feedback = load_parlay_audit_feedback()
    prompt  = build_parlay_prompt(candidates, audit_feedback)
    parlays = call_parlay_agent(prompt)
    print(f"[parlay] Claude returned {len(parlays)} parlays")

    save_parlays(parlays)


if __name__ == "__main__":
    main()
