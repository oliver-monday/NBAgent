#!/usr/bin/env python3
"""
NBAgent — Auditor

Cross-references yesterday's picks from data/picks.json against
actual box scores in data/player_game_log.csv.

Also grades yesterday's parlays from data/parlays.json — a parlay
is a HIT only if every leg hits.

Scores each pick as HIT/MISS/NO_DATA, scores each parlay as HIT/MISS/PARTIAL/NO_DATA,
performs root cause analysis, and writes structured feedback to
data/audit_log.json for the Analyst to read on its next run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import pandas as pd

# ── Paths ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

GAME_LOG_CSV      = DATA / "player_game_log.csv"
PICKS_JSON        = DATA / "picks.json"
PARLAYS_JSON      = DATA / "parlays.json"
AUDIT_LOG_JSON    = DATA / "audit_log.json"
CONTEXT_MD         = ROOT / "context" / "nba_season_context.md"
PLAYER_STATS_JSON  = DATA / "player_stats.json"
AUDIT_SUMMARY_JSON = DATA / "audit_summary.json"

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
YESTERDAY = TODAY - dt.timedelta(days=1)
YESTERDAY_STR = YESTERDAY.strftime("%Y-%m-%d")

# ── Config ───────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192


# ── Data loaders ─────────────────────────────────────────────────────

def load_yesterdays_picks() -> list[dict]:
    if not PICKS_JSON.exists():
        print(f"[auditor] No picks.json found.")
        return []
    with open(PICKS_JSON) as f:
        all_picks = json.load(f)
    yesterday_picks = [p for p in all_picks if p.get("date") == YESTERDAY_STR]
    if not yesterday_picks:
        print(f"[auditor] No picks found for {YESTERDAY_STR}.")
    return yesterday_picks


def load_yesterdays_parlays() -> list[dict]:
    """Load yesterday's parlay bundle from parlays.json."""
    if not PARLAYS_JSON.exists():
        return []
    try:
        with open(PARLAYS_JSON) as f:
            all_bundles = json.load(f)
        for bundle in all_bundles:
            if bundle.get("date") == YESTERDAY_STR:
                return bundle.get("parlays", [])
    except Exception as e:
        print(f"[auditor] WARNING: could not load parlays.json: {e}")
    return []


def load_game_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def load_player_stats_for_audit(graded_picks: list[dict]) -> dict:
    """
    Load player_stats.json and return only entries for players in yesterday's picks.
    Slimmed to fields relevant to audit reasoning — raw game logs dropped to keep
    prompt lean. player_stats.json reflects today's computed data; close enough for
    audit purposes since rosters and roles are stable game-to-game.
    """
    if not PLAYER_STATS_JSON.exists():
        print("[auditor] player_stats.json not found — skipping stats context.")
        return {}
    try:
        with open(PLAYER_STATS_JSON) as f:
            all_stats = json.load(f)
    except Exception as e:
        print(f"[auditor] WARNING: could not load player_stats.json: {e}")
        return {}

    players_needed = {p["player_name"] for p in graded_picks}
    slim: dict = {}
    for name in players_needed:
        s = all_stats.get(name)
        if not s:
            continue
        slim[name] = {
            "team":                  s.get("team"),
            "opponent":              s.get("opponent"),
            "on_back_to_back":       s.get("on_back_to_back"),
            "best_tiers":            s.get("best_tiers"),
            "tier_hit_rates":        s.get("tier_hit_rates"),
            "trend":                 s.get("trend"),
            "opp_defense":           s.get("opp_defense"),
            "game_pace":             s.get("game_pace"),
            "teammate_correlations": s.get("teammate_correlations"),
        }

    print(f"[auditor] Player stats context loaded for {len(slim)} players")
    return slim


# ── Season context ───────────────────────────────────────────────────

def load_season_context() -> str:
    """
    Load the manually-maintained NBA season context document.
    Injected into the audit prompt so the Auditor can correctly interpret
    permanent absences vs. game-level factors before assigning root causes.
    Returns empty string gracefully if file is missing — never blocks a run.
    """
    if not CONTEXT_MD.exists():
        print("[auditor] WARNING: context/nba_season_context.md not found, skipping.")
        return ""
    try:
        text = CONTEXT_MD.read_text(encoding="utf-8").strip()
        # Strip HTML comment header block if present
        if text.startswith("<!--"):
            end = text.find("-->")
            if end != -1:
                text = text[end + 3:].strip()
        print(f"[auditor] Season context loaded ({len(text.split())} words)")
        return text
    except Exception as e:
        print(f"[auditor] WARNING: could not load season context: {e}")
        return ""


# ── Grading ──────────────────────────────────────────────────────────

PROP_COL_MAP = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "3PM": "tpm",
}


def grade_picks(picks: list[dict], game_log: pd.DataFrame) -> list[dict]:
    yesterday_log = game_log[game_log["game_date"] == YESTERDAY_STR].copy()
    graded = []

    for pick in picks:
        p = pick.copy()
        player_name = p.get("player_name", "")
        prop_type   = p.get("prop_type", "")
        pick_value  = p.get("pick_value")
        team        = p.get("team", "")

        col = PROP_COL_MAP.get(prop_type)
        if not col:
            p["result"] = "NO_DATA"
            p["actual_value"] = None
            graded.append(p)
            continue

        mask = yesterday_log["player_name"].str.lower() == player_name.lower()
        if team:
            team_mask = yesterday_log["team_abbrev"].str.upper() == team.upper()
            row = yesterday_log[mask & team_mask]
            if row.empty:
                row = yesterday_log[mask]
        else:
            row = yesterday_log[mask]

        if row.empty:
            p["result"] = "NO_DATA"
            p["actual_value"] = None
        else:
            actual = pd.to_numeric(row.iloc[0][col], errors="coerce")
            p["actual_value"] = float(actual) if pd.notna(actual) else None

            if p["actual_value"] is None:
                p["result"] = "NO_DATA"
            elif p["actual_value"] >= float(pick_value):
                p["result"] = "HIT"
            else:
                p["result"] = "MISS"

        graded.append(p)

    return graded


def grade_parlays(parlays: list[dict], graded_picks: list[dict]) -> list[dict]:
    """
    Grade each parlay using the already-graded picks as source of truth.
    Parlay result:
      HIT     — all legs hit
      MISS    — at least one leg missed
      PARTIAL — some legs hit, at least one NO_DATA (can't fully grade)
      NO_DATA — all legs are NO_DATA
    """
    # Build a lookup: (player_name.lower, prop_type, pick_value) → result + actual
    pick_lookup: dict[tuple, dict] = {}
    for p in graded_picks:
        key = (p["player_name"].lower(), p["prop_type"], float(p["pick_value"]))
        pick_lookup[key] = {"result": p.get("result"), "actual_value": p.get("actual_value")}

    graded_parlays = []
    for parlay in parlays:
        p = parlay.copy()
        legs = p.get("legs", [])
        leg_results = []

        for leg in legs:
            key = (leg["player_name"].lower(), leg["prop_type"], float(leg["pick_value"]))
            leg_data = pick_lookup.get(key, {})
            leg_result = leg_data.get("result", "NO_DATA")
            actual = leg_data.get("actual_value")
            leg_results.append({
                "player_name": leg["player_name"],
                "prop_type": leg["prop_type"],
                "pick_value": leg["pick_value"],
                "result": leg_result,
                "actual_value": actual,
            })

        hits     = sum(1 for r in leg_results if r["result"] == "HIT")
        misses   = sum(1 for r in leg_results if r["result"] == "MISS")
        no_data  = sum(1 for r in leg_results if r["result"] == "NO_DATA")
        total    = len(leg_results)

        if misses > 0:
            parlay_result = "MISS"
        elif no_data == total:
            parlay_result = "NO_DATA"
        elif no_data > 0:
            parlay_result = "PARTIAL"
        else:
            parlay_result = "HIT"

        p["result"]      = parlay_result
        p["legs_hit"]    = hits
        p["legs_total"]  = total
        p["leg_results"] = leg_results
        graded_parlays.append(p)

    return graded_parlays


# ── Prompt builder ───────────────────────────────────────────────────

def build_audit_prompt(graded_picks: list[dict], graded_parlays: list[dict], season_context: str = "", player_stats_context: dict | None = None) -> str:
    hits    = [p for p in graded_picks if p["result"] == "HIT"]
    misses  = [p for p in graded_picks if p["result"] == "MISS"]
    no_data = [p for p in graded_picks if p["result"] == "NO_DATA"]

    total_gradeable = len(hits) + len(misses)
    hit_rate = round(100 * len(hits) / total_gradeable, 1) if total_gradeable > 0 else 0

    # ── Pre-computed breakdown stats ──────────────────────────────────
    prop_breakdown: dict = defaultdict(lambda: {"picks": 0, "hits": 0})
    for p in graded_picks:
        pt = p.get("prop_type", "")
        prop_breakdown[pt]["picks"] += 1
        if p.get("result") == "HIT":
            prop_breakdown[pt]["hits"] += 1
    for pt in list(prop_breakdown.keys()):
        n = prop_breakdown[pt]["picks"]
        h = prop_breakdown[pt]["hits"]
        prop_breakdown[pt]["hit_rate_pct"] = round(100 * h / n, 1) if n else 0.0

    bands = {"70-75": (70, 75), "76-80": (76, 80), "81-85": (81, 85), "86+": (86, 100)}
    conf_breakdown: dict = {}
    for band, (lo, hi) in bands.items():
        subset = [p for p in graded_picks
                  if lo <= p.get("confidence_pct", 0) <= hi
                  and p.get("result") in ("HIT", "MISS")]
        h = sum(1 for p in subset if p["result"] == "HIT")
        mid = (lo + hi) / 2 if hi < 100 else 90.0
        conf_breakdown[band] = {
            "picks": len(subset), "hits": h,
            "hit_rate_pct": round(100 * h / len(subset), 1) if subset else 0.0,
            "expected_hit_rate_pct": mid,
        }

    # Readable summary strings for the prompt
    prop_rows = []
    for stat in ["PTS", "REB", "AST", "3PM"]:
        d = prop_breakdown.get(stat, {"picks": 0, "hits": 0, "hit_rate_pct": 0})
        prop_rows.append(
            f"  {stat}: {d['picks']} picks, {d['hits']} hits, {d['hit_rate_pct']}%"
        )
    prop_stats_block = "\n".join(prop_rows)

    conf_rows = []
    for band in ["70-75", "76-80", "81-85", "86+"]:
        d = conf_breakdown[band]
        conf_rows.append(
            f"  {band}%: {d['picks']} picks, {d['hits']} hits, "
            f"{d['hit_rate_pct']}% actual vs {d['expected_hit_rate_pct']}% expected"
        )
    conf_stats_block = "\n".join(conf_rows)

    # Serialized schema values (pre-filled so Claude doesn't recalculate)
    prop_schema: dict = {}
    for stat in ["PTS", "REB", "AST", "3PM"]:
        d = prop_breakdown.get(stat, {"picks": 0, "hits": 0, "hit_rate_pct": 0})
        prop_schema[stat] = {
            "picks": d["picks"],
            "hits": d["hits"],
            "hit_rate_pct": d["hit_rate_pct"],
        }
    prop_schema_str = json.dumps(prop_schema, indent=2)

    conf_schema = {}
    for band in ["70-75", "76-80", "81-85", "86+"]:
        d = conf_breakdown[band]
        conf_schema[band] = {
            "picks": d["picks"],
            "hits": d["hits"],
            "hit_rate_pct": d["hit_rate_pct"],
            "expected_hit_rate_pct": d["expected_hit_rate_pct"],
        }
    conf_schema_str = json.dumps(conf_schema, indent=2)

    # Player stats context block (pre-serialized for the f-string)
    player_stats_block_str = (
        json.dumps(player_stats_context, indent=2)
        if player_stats_context
        else "No player stats available for this audit run."
    )

    # Parlay summary
    p_hits    = sum(1 for p in graded_parlays if p["result"] == "HIT")
    p_misses  = sum(1 for p in graded_parlays if p["result"] == "MISS")
    p_partial = sum(1 for p in graded_parlays if p["result"] == "PARTIAL")

    picks_block   = json.dumps(graded_picks, indent=2)
    parlays_block = json.dumps(graded_parlays, indent=2) if graded_parlays else "[]"

    parlay_section = ""
    if graded_parlays:
        parlay_section = f"""
## PARLAY GRADED RESULTS
- Total parlays: {len(graded_parlays)}
- Hits (all legs): {p_hits}
- Misses (any leg missed): {p_misses}
- Partial (no miss but some NO_DATA): {p_partial}

## FULL GRADED PARLAYS
{parlays_block}

## PARLAY ANALYSIS TASK
4. For each PARLAY HIT: identify what made the combination work — correlation logic, matchup stack, game script.
5. For each PARLAY MISS: which leg failed and why? Was the correlation assumption wrong? Was a leg too aggressive?
6. Add 1–2 parlay-specific recommendations to help the Parlay Agent select better combinations.
"""

    return f"""You are the Auditor for NBAgent, an NBA player props selection system.

Today is {dt.datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")}.
You are auditing picks and parlays made for {YESTERDAY_STR}.

## GRADING RULE — READ FIRST
A pick is a HIT if actual_value >= pick_value. Exact threshold matches are HITs, not misses.
Do not flag exact-threshold results as near-misses or line-value problems in your analysis.

## SEASON CONTEXT — READ BEFORE ANALYZING ANY PICK
{season_context if season_context else "No season context file found."}

Players marked OFS all season are permanent absences. Their teammates' current roles are baselines,
not elevations. Do not cite these absences as a causal factor in any pick reasoning or audit
analysis.

## PICK GRADED RESULTS SUMMARY
- Total picks: {len(graded_picks)}
- Hits: {len(hits)}
- Misses: {len(misses)}
- No data (DNP/missing): {len(no_data)}
- Hit rate (gradeable only): {hit_rate}%

## PRE-COMPUTED STATISTICS
Use these values exactly when filling prop_type_breakdown and confidence_calibration in your output.
These are pre-calculated from the graded picks — do not recalculate.

By prop type (HITs + MISSes only, excluding NO_DATA):
{prop_stats_block}

By confidence band (HITs + MISSes only):
{conf_stats_block}

## FULL GRADED PICKS
{picks_block}
{parlay_section}
## PLAYER STATS CONTEXT (at time of pick)
The following pre-computed data was available to the Analyst when picks were made.
Use this to evaluate whether picks were well-founded, and to identify model gaps where
available data should have changed the selection.

{player_stats_block_str}

Key fields to use in audit reasoning:
- tier_hit_rates: the actual hit rates at each tier threshold across last 20 games
- teammate_correlations: Pearson r and tag between teammates — check if board_rivals
  or scoring_rivals flags existed for players who cannibalized each other's stats
- opp_defense: what the quant data said about the opponent — verify this matched
  the analyst's opp_defense_rating on each pick
- on_back_to_back: flag whether fatigue context was available and used correctly
- game_pace: check whether pace context supported or contradicted the pick thesis

## PICK ANALYSIS TASK

For every miss, perform analysis in this exact order before writing root_cause:

STEP 1 — CHECK ACTIVITY: Did the player record any non-zero stat in any category (REB, AST,
minutes implied by any non-zero output)? If actual_value is 0 for the picked stat, check all
other stat fields before concluding DNP. Do not conclude DNP or lineup failure unless ALL stats
are zero AND no minutes evidence exists.

STEP 2 — CHECK INJURY STATUS, THEN CLASSIFY THE MISS as exactly one of:
  First, inspect the pick object's injury_status_at_check and voided fields before
  choosing any classification. Prefer injury_event or workflow_gap when the evidence
  supports them — these take priority over selection_error, model_gap, or variance.

  - "injury_event": player was confirmed active at pick time (injury_status_at_check
    was NOT_LISTED or QUESTIONABLE) but exited the game mid-game due to injury.
    Evidence: non-zero minutes logged but near-zero stats across ALL categories,
    and/or actual output near-zero despite no pre-game red flag. Use this when an
    in-game injury exit explains the miss, not a pre-game availability failure.
  - "workflow_gap": player was listed OUT or DOUBTFUL pre-game (injury_status_at_check
    = "OUT" or "DOUBTFUL" on the pick object) but voided = false. This is a timing
    or workflow failure — lineup_watch did not void the pick before game time. Use
    this whenever pre-game OUT/DOUBTFUL status explains the miss.
  - "selection_error": the pick was wrong given data available at pick time
    (bad hit rate, wrong tier, ignored injury context, etc.)
  - "model_gap": pick was reasonable but system lacks a signal that would
    have caught this (e.g. teammate rebounding competition, assist suppression
    by defense type, usage redistribution nuance)
  - "variance": pick was sound, player had an off night. Hit rate and context
    supported the pick; outcome was within normal variance range.

IMPORTANT — INJURY AND WORKFLOW MISSES: For any miss classified as injury_event or
workflow_gap, do NOT write a lesson or recommendation targeting the Analyst's pick
selection logic. These are not analytical errors. Instead, write a single neutral
note in root_cause only (e.g. "Workflow gap: player listed OUT pre-game, pick not
voided in time" or "Injury event: player exited mid-game, near-zero output despite
active pre-game status"). Exclude these picks entirely from the lessons and
recommendations arrays — they must not pollute the Analyst's feedback loop.

STEP 3 — CRITIQUE THE ORIGINAL REASONING: The pick object includes a "reasoning" field
containing the analyst's original thesis. Read it. If the pick missed, identify specifically
what was wrong or missing in that reasoning. If the pick hit, identify what the reasoning got
right. Do not ignore this field.

STEP 4 — REFERENCE HIT RATE DATA: Every pick includes hit_rate_display (e.g. "8/10") and
trend ("up"/"stable"/"down"). Reference these explicitly in your root cause. A miss on an
8/10 hit rate pick is different from a miss on a 5/10 pick.

For hits: identify what the Analyst got right — specific statistical patterns, matchup reads,
or reasoning that proved correct.

Synthesize 3–5 concrete, actionable recommendations for the Analyst's next run based on
patterns across the full set of picks. Be specific — reference player names, prop types,
and numbers.

## OUTPUT FORMAT
Respond ONLY with valid JSON. No preamble.

{{
  "date": "{YESTERDAY_STR}",
  "total_picks": {len(graded_picks)},
  "hits": {len(hits)},
  "misses": {len(misses)},
  "no_data": {len(no_data)},
  "hit_rate_pct": {hit_rate},
  "prop_type_breakdown": {prop_schema_str},
  "confidence_calibration": {conf_schema_str},
  "reinforcements": ["string: what worked and why — be specific"],
  "lessons": ["string: what failed and why — be specific"],
  "recommendations": ["string: concrete instruction for the Analyst to adjust selection logic"],
  "miss_details": [
    {{
      "player_name": "string",
      "prop_type": "string",
      "pick_value": number,
      "actual_value": number,
      "miss_classification": "selection_error | model_gap | variance | injury_event | workflow_gap",
      "root_cause": "string"
    }}
  ],
  "parlay_results": {{
    "total": {len(graded_parlays)},
    "hits": {p_hits},
    "misses": {p_misses},
    "partial": {p_partial},
    "parlay_lessons": ["string: what the Parlay Agent should do differently"],
    "parlay_reinforcements": ["string: what combination logic worked well"]
  }}
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

def save_audit(audit_entry: dict, graded_picks: list[dict], graded_parlays: list[dict]):
    # Update picks.json with graded results
    all_picks = []
    if PICKS_JSON.exists():
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    non_yesterday = [p for p in all_picks if p.get("date") != YESTERDAY_STR]
    updated_picks = non_yesterday + graded_picks
    with open(PICKS_JSON, "w") as f:
        json.dump(updated_picks, f, indent=2)
    print(f"[auditor] Updated picks.json with graded results")

    # Update parlays.json with graded results
    if graded_parlays and PARLAYS_JSON.exists():
        try:
            with open(PARLAYS_JSON) as f:
                all_bundles = json.load(f)
            updated_bundles = [b for b in all_bundles if b.get("date") != YESTERDAY_STR]
            updated_bundles.append({"date": YESTERDAY_STR, "parlays": graded_parlays})
            with open(PARLAYS_JSON, "w") as f:
                json.dump(updated_bundles, f, indent=2)
            print(f"[auditor] Updated parlays.json with graded results")
        except Exception as e:
            print(f"[auditor] WARNING: could not update parlays.json: {e}")

    # Append to audit_log.json
    existing_log = []
    if AUDIT_LOG_JSON.exists():
        try:
            with open(AUDIT_LOG_JSON) as f:
                existing_log = json.load(f)
            if not isinstance(existing_log, list):
                existing_log = []
        except Exception:
            existing_log = []

    existing_log = [e for e in existing_log if e.get("date") != YESTERDAY_STR]
    existing_log.append(audit_entry)
    with open(AUDIT_LOG_JSON, "w") as f:
        json.dump(existing_log, f, indent=2)
    print(f"[auditor] Saved audit entry for {YESTERDAY_STR} → {AUDIT_LOG_JSON}")

    save_audit_summary(existing_log)


def save_audit_summary(audit_log: list[dict]):
    """Roll up all audit entries into a longitudinal summary for the Analyst."""
    if not audit_log:
        return

    # ── Overall totals ─────────────────────────────────────────────────
    total_picks  = sum(e.get("total_picks", 0) for e in audit_log)
    total_hits   = sum(e.get("hits",        0) for e in audit_log)
    total_misses = sum(e.get("misses",      0) for e in audit_log)
    gradeable    = total_hits + total_misses
    overall_hr   = round(total_hits / gradeable * 100, 1) if gradeable > 0 else 0.0

    # ── Per-prop aggregation (from prop_type_breakdown in each entry) ──
    prop_agg: dict = defaultdict(lambda: {"picks": 0, "hits": 0})
    for entry in audit_log:
        ptb = entry.get("prop_type_breakdown") or {}
        for pt, d in ptb.items():
            prop_agg[pt]["picks"] += d.get("picks", 0)
            prop_agg[pt]["hits"]  += d.get("hits",  0)
    prop_summary = {}
    for pt, d in prop_agg.items():
        p = d["picks"]
        h = d["hits"]
        prop_summary[pt] = {
            "picks":        p,
            "hits":         h,
            "hit_rate_pct": round(h / p * 100, 1) if p > 0 else 0.0,
        }

    # ── Miss classification breakdown ──────────────────────────────────
    miss_classes: dict = defaultdict(int)
    for entry in audit_log:
        for miss in entry.get("miss_details", []):
            mc = miss.get("miss_classification", "")
            if mc in ("selection_error", "model_gap", "variance", "injury_event", "workflow_gap"):
                miss_classes[mc] += 1

    # ── Confidence calibration aggregation ────────────────────────────
    conf_agg: dict = defaultdict(lambda: {"picks": 0, "hits": 0})
    for entry in audit_log:
        ccb = entry.get("confidence_calibration") or {}
        if not isinstance(ccb, dict):
            continue
        for band, d in ccb.items():
            conf_agg[band]["picks"] += d.get("picks", 0)
            conf_agg[band]["hits"]  += d.get("hits",  0)
    conf_summary = {}
    for band, d in conf_agg.items():
        p = d["picks"]
        h = d["hits"]
        conf_summary[band] = {
            "picks":        p,
            "hits":         h,
            "hit_rate_pct": round(h / p * 100, 1) if p > 0 else 0.0,
        }

    # ── Recent lessons, reinforcements, recommendations (last 5 days) ──
    recent_entries        = audit_log[-5:]
    recent_lessons        = [l for e in recent_entries for l in e.get("lessons",         [])]
    recent_reinforcements = [r for e in recent_entries for r in e.get("reinforcements",  [])]
    recent_recommendations = [r for e in recent_entries for r in e.get("recommendations", [])]

    # ── Parlay totals ──────────────────────────────────────────────────
    p_total   = sum(e.get("parlay_results", {}).get("total",   0) for e in audit_log)
    p_hits    = sum(e.get("parlay_results", {}).get("hits",    0) for e in audit_log)
    p_misses  = sum(e.get("parlay_results", {}).get("misses",  0) for e in audit_log)
    p_partial = sum(e.get("parlay_results", {}).get("partial", 0) for e in audit_log)

    summary = {
        "generated_at":    TODAY.strftime("%Y-%m-%d"),
        "entries_included": len(audit_log),
        "overall": {
            "total_picks":  total_picks,
            "hits":         total_hits,
            "misses":       total_misses,
            "hit_rate_pct": overall_hr,
        },
        "prop_type_summary":             prop_summary,
        "miss_classification_totals":    dict(miss_classes),
        "confidence_calibration_totals": conf_summary,
        "parlay_summary": {
            "total":   p_total,
            "hits":    p_hits,
            "misses":  p_misses,
            "partial": p_partial,
        },
        "recent_lessons":          recent_lessons[-10:],
        "recent_reinforcements":   recent_reinforcements[-10:],
        "recent_recommendations":  recent_recommendations[-10:],
    }

    with open(AUDIT_SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[auditor] Saved rolling audit summary ({len(audit_log)} entries) → {AUDIT_SUMMARY_JSON}")


def print_summary(graded_picks: list[dict], graded_parlays: list[dict], audit_entry: dict):
    hits   = [p for p in graded_picks if p["result"] == "HIT"]
    misses = [p for p in graded_picks if p["result"] == "MISS"]

    print(f"\n{'='*55}")
    print(f"AUDIT SUMMARY — {YESTERDAY_STR}")
    print(f"{'='*55}")
    print(f"Pick hit rate: {audit_entry.get('hit_rate_pct', '?')}% "
          f"({len(hits)}/{len(hits)+len(misses)} gradeable)")

    if hits:
        print(f"\n✓ HITS ({len(hits)}):")
        for p in hits:
            print(f"  {p['player_name']} {p['prop_type']} OVER {p['pick_value']} "
                  f"→ actual {p['actual_value']}")

    if misses:
        print(f"\n✗ MISSES ({len(misses)}):")
        for p in misses:
            print(f"  {p['player_name']} {p['prop_type']} OVER {p['pick_value']} "
                  f"→ actual {p['actual_value']}")

    if graded_parlays:
        p_hits   = sum(1 for p in graded_parlays if p["result"] == "HIT")
        p_misses = sum(1 for p in graded_parlays if p["result"] == "MISS")
        print(f"\n🎰 PARLAYS: {p_hits} hit, {p_misses} missed of {len(graded_parlays)}")
        for p in graded_parlays:
            icon = "✓" if p["result"] == "HIT" else ("✗" if p["result"] == "MISS" else "~")
            legs_str = ", ".join(
                f"{l['player_name']} {l['prop_type']} ({l.get('result','?')})"
                for l in p.get("leg_results", [])
            )
            print(f"  {icon} [{p.get('implied_odds','')}] {p.get('label','')}: {legs_str}")

    print(f"\nRecommendations for Analyst:")
    for r in audit_entry.get("recommendations", []):
        print(f"  → {r}")

    pr = audit_entry.get("parlay_results", {})
    if pr.get("parlay_lessons"):
        print(f"\nParlay Agent notes:")
        for r in pr["parlay_lessons"]:
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
    print(f"[auditor] Picks graded: {hits} hits, {misses} misses, "
          f"{len(graded_picks)-hits-misses} no data")

    if hits + misses == 0:
        print("[auditor] No gradeable picks — box scores may not be ingested yet.")
        sys.exit(0)

    # Grade parlays using already-graded picks as source of truth
    parlays = load_yesterdays_parlays()
    graded_parlays = grade_parlays(parlays, graded_picks) if parlays else []
    if graded_parlays:
        p_hits = sum(1 for p in graded_parlays if p["result"] == "HIT")
        print(f"[auditor] Parlays graded: {p_hits}/{len(graded_parlays)} hit")

    season_context      = load_season_context()
    player_stats_context = load_player_stats_for_audit(graded_picks)
    prompt      = build_audit_prompt(graded_picks, graded_parlays, season_context, player_stats_context)
    audit_entry = call_auditor(prompt)

    save_audit(audit_entry, graded_picks, graded_parlays)
    print_summary(graded_picks, graded_parlays, audit_entry)


if __name__ == "__main__":
    main()
