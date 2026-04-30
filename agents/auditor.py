#!/usr/bin/env python3
"""
NBAgent — Auditor

Cross-references yesterday's picks from data/picks.json against
actual box scores in data/player_game_log.csv.

Scores each pick as HIT/MISS/NO_DATA, performs root cause analysis,
and writes structured feedback to data/audit_log.json for the Analyst
to read on its next run.

Parlay grading was removed on 2026-04-24 — the parlay agent shifted
to a deterministic combinatorial menu builder, so per-card grading is
a category error (the cards are configurable options, not predictions).
data/parlays.json continues to be written daily by agents/parlay.py;
its `result` and per-leg outcome fields stay null with no consumer.
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
AUDIT_LOG_JSON    = DATA / "audit_log.json"
CONTEXT_MD         = ROOT / "context" / "nba_season_context.md"
AUDIT_SUMMARY_JSON  = DATA / "audit_summary.json"
AUDIT_REPORTS_DIR   = DATA / "audit_reports"
POST_GAME_NEWS_JSON  = DATA / "post_game_news.json"
STANDINGS_JSON       = DATA / "standings_today.json"
SKIPPED_PICKS_JSON   = DATA / "skipped_picks.json"
SKIP_ARCHIVE_JSON    = DATA / "skipped_picks_archive.json"
MASTER_CSV           = DATA / "nba_master.csv"
PICKS_REVIEW_DIR     = DATA  # daily files: data/picks_review_YYYY-MM-DD.json

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
YESTERDAY = TODAY - dt.timedelta(days=1)
YESTERDAY_STR = YESTERDAY.strftime("%Y-%m-%d")
PLAYOFFS_R1_DATE = "2026-04-18"
PLAYOFF_CAL_MIN_PICKS = 15   # min graded playoff picks before check fires
PLAYOFF_CAL_DIVERGE_PP = 10  # pp divergence threshold for warning

# ── Config ───────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8192

# High-conviction subset: picks where the FanDuel market itself is heavily
# confident (market_implied_prob >= 85.0). Empirically the safest band per
# data/single_leg_edge_report.md (2026-04-25). Used for both the auditor
# secondary calc and the frontend Today's Picks toggle. picks.json stores
# market_implied_prob as a 0-100 percentage, so the comparison is on that scale.
HIGH_CONVICTION_THRESHOLD = 85.0


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


def load_game_log() -> pd.DataFrame:
    if not GAME_LOG_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(GAME_LOG_CSV, dtype={"game_id": str, "player_id": str})
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


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


def render_playoff_picture(standings_path=STANDINGS_JSON) -> str:
    """
    Read standings_today.json (written by espn_daily_ingest.py) and return a
    compact ## PLAYOFF PICTURE text block for prompt injection.

    Bucketing logic (per conference, by rank within the conference):
      Eliminated       — gb_from_8th > 15.0 (overrides rank)
      Clinched/Safe    — rank ≤ 8 AND ≥ 5 games ahead of 9th
      Playoff In       — rank ≤ 8 AND < 5 games ahead of 9th
      Play-In          — rank 9 or 10
      Bubble           — rank 11 or 12
      Out of Contention— rank 13–15 (and not Eliminated)

    Returns empty string if file missing or parse fails — never blocks a run.
    """
    try:
        if not Path(standings_path).exists():
            print("[auditor] standings_today.json not found — skipping playoff picture.")
            return ""
        with open(standings_path) as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[auditor] WARNING: could not load standings: {e}")
        return ""

    date_str = data.get("date", "unknown")
    lines = [f"## PLAYOFF PICTURE (as of {date_str})"]

    for conf_key, conf_label in [("East", "EAST"), ("West", "WEST")]:
        teams = data.get(conf_key, [])
        if not teams:
            continue
        teams = sorted(teams, key=lambda t: t["rank"])

        gb_8th = teams[7]["gb_leader"] if len(teams) >= 8 else None
        gb_9th = teams[8]["gb_leader"] if len(teams) >= 9 else None

        buckets: dict[str, list[str]] = {
            "Clinched/Safe": [], "Playoff In": [], "Play-In": [],
            "Bubble": [], "Out of Contention": [], "Eliminated": [],
        }

        for t in teams:
            rank = t["rank"]
            gb   = t["gb_leader"]
            entry = f"{rank}. {t['team']} ({t['wins']}-{t['losses']})"

            # Eliminated takes priority over rank
            if gb_8th is not None and (gb - gb_8th) > 15.0:
                buckets["Eliminated"].append(entry)
            elif rank <= 8:
                gb_from_9th = (gb_9th - gb) if gb_9th is not None else 0.0
                if gb_from_9th >= 5.0:
                    buckets["Clinched/Safe"].append(entry)
                else:
                    buckets["Playoff In"].append(entry)
            elif rank in (9, 10):
                buckets["Play-In"].append(entry)
            elif rank in (11, 12):
                buckets["Bubble"].append(entry)
            else:
                buckets["Out of Contention"].append(entry)

        bucket_labels = {
            "Clinched/Safe":    f"{conf_label} — Clinched/Safe (≥5 games clear of bubble):",
            "Playoff In":       f"{conf_label} — Playoff In (within 5 games of safety):",
            "Play-In":          f"{conf_label} — Play-In (9th–10th):",
            "Bubble":           f"{conf_label} — Bubble (11th–12th):",
            "Out of Contention":f"{conf_label} — Out of Contention:",
            "Eliminated":       f"{conf_label} — Eliminated:",
        }

        for key in ["Clinched/Safe", "Playoff In", "Play-In", "Bubble", "Out of Contention", "Eliminated"]:
            if not buckets[key]:
                continue
            lines.append(bucket_labels[key])
            lines.append("  " + "  ".join(buckets[key]))

        lines.append("")  # blank line between conferences

    if len(lines) <= 1:
        return ""
    print(f"[auditor] Playoff picture rendered ({date_str})")
    return "\n".join(lines).rstrip()


def load_post_game_news() -> dict:
    """
    Load post_game_news.json written by post_game_reporter.py.
    Returns player event dict keyed by player_name.lower().
    Returns empty dict gracefully if file missing — never blocks a run.
    """
    if not POST_GAME_NEWS_JSON.exists():
        print("[auditor] post_game_news.json not found — proceeding without news context.")
        return {}
    try:
        with open(POST_GAME_NEWS_JSON) as f:
            data = json.load(f)
        players = data.get("players", {})
        print(f"[auditor] Post-game news loaded: {len(players)} player events")
        return players
    except Exception as e:
        print(f"[auditor] WARNING: could not load post_game_news.json: {e}")
        return {}


def load_game_results() -> dict[str, dict]:
    """
    Load yesterday's final scores from nba_master.csv.
    Returns a dict keyed by team abbreviation (both home and away) for O(1) lookup.

    Each value:
        {
            "home": str,           # home team abbrev
            "away": str,           # away team abbrev
            "home_score": int,
            "away_score": int,
            "margin": int,         # abs(home_score - away_score)
            "winner": str,         # abbrev of winning team
            "loser": str,          # abbrev of losing team
            "game_script": str,    # "blowout" | "competitive" | "close"
        }

    game_script thresholds:
        margin >= 20  → "blowout"
        margin >= 10  → "competitive"
        margin <  10  → "close"

    Returns empty dict on any error (file missing, parse failure, etc.).
    """
    if not MASTER_CSV.exists():
        print("[auditor] nba_master.csv not found — skipping game results")
        return {}
    try:
        master = pd.read_csv(MASTER_CSV)
        yesterday_games = master[master["game_date"] == YESTERDAY_STR].copy()
        if yesterday_games.empty:
            print(f"[auditor] No games found in nba_master for {YESTERDAY_STR}")
            return {}

        results: dict[str, dict] = {}
        for _, row in yesterday_games.iterrows():
            home = str(row.get("home_team_abbrev", "")).strip().upper()
            away = str(row.get("away_team_abbrev", "")).strip().upper()
            try:
                hs  = int(row["home_score"])
                as_ = int(row["away_score"])
            except (ValueError, TypeError):
                continue  # score not yet filled (game not played or ingest gap)

            margin = abs(hs - as_)
            winner = home if hs > as_ else away
            loser  = away if hs > as_ else home

            if margin >= 20:
                script = "blowout"
            elif margin >= 10:
                script = "competitive"
            else:
                script = "close"

            game_dict = {
                "home": home,
                "away": away,
                "home_score": hs,
                "away_score": as_,
                "margin": margin,
                "winner": winner,
                "loser": loser,
                "game_script": script,
            }
            # Key by both team abbrevs for O(1) lookup from either side
            results[home] = game_dict
            results[away] = game_dict

        print(f"[auditor] Loaded game results for {len(yesterday_games)} yesterday games")
        return results
    except Exception as e:
        print(f"[auditor] Warning: could not load game results — {e}")
        return {}


def build_game_results_block(game_results: dict[str, dict]) -> str:
    """
    Format yesterday's game results as a prompt-injectable block.
    Deduplicates games (each game appears once despite being keyed twice).
    """
    if not game_results:
        return ""

    seen: set = set()
    lines: list[str] = []
    for team, g in game_results.items():
        game_key = f"{g['home']}_{g['away']}"
        if game_key in seen:
            continue
        seen.add(game_key)
        script_label = g["game_script"].upper()
        lines.append(
            f"  {g['away']} @ {g['home']}: "
            f"{g['away_score']}–{g['home_score']} "
            f"({g['winner']} won by {g['margin']}) [{script_label}]"
        )

    if not lines:
        return ""

    return (
        "## GAME RESULTS — YESTERDAY\n"
        "Final scores for all yesterday's games. Use these to establish game-script\n"
        "context BEFORE analyzing individual misses. A blowout margin affects all\n"
        "players on both sides of the game — do not require per-player web narratives\n"
        "to apply game-script reasoning when the margin is already visible here.\n\n"
        + "\n".join(sorted(lines))
        + "\n\nGame script labels: BLOWOUT = margin ≥20pts; COMPETITIVE = margin 10–19pts; "
          "CLOSE = margin <10pts.\n"
    )


def load_skipped_picks() -> list[dict]:
    """
    Load skipped_picks.json written by analyst.py for today's run.
    Returns empty list gracefully if file missing.
    """
    if not SKIPPED_PICKS_JSON.exists():
        return []
    try:
        with open(SKIPPED_PICKS_JSON) as f:
            skips = json.load(f)
        print(f"[auditor] Loaded {len(skips)} skip records from {SKIPPED_PICKS_JSON}")
        return skips
    except Exception as e:
        print(f"[auditor] WARNING: could not load skipped_picks.json: {e}")
        return []


def load_picks_review(date_str: str) -> dict[tuple, dict]:
    """
    Load the human picks review file for the given date.
    Returns a dict keyed by (player_name_lower, prop_type, pick_value) → review entry.
    Returns {} gracefully if file is absent or malformed.
    """
    path = DATA / f"picks_review_{date_str}.json"
    if not path.exists():
        print(f"[auditor] No picks review file found for {date_str} — skipping human_verdict tagging")
        return {}
    try:
        with open(path) as fh:
            entries = json.load(fh)
        if not isinstance(entries, list):
            return {}
        result: dict[tuple, dict] = {}
        for e in entries:
            name    = (e.get("player_name") or "").strip().lower()
            pt      = e.get("prop_type", "")
            pv      = e.get("pick_value")
            verdict = e.get("verdict", "")
            if name and pt and pv is not None and verdict in ("keep", "trim", "manual_skip"):
                result[(name, pt, pv)] = e
        print(f"[auditor] Loaded picks review for {date_str}: {len(result)} reviewed picks")
        return result
    except Exception as e:
        print(f"[auditor] WARNING: could not load picks review: {e}")
        return {}


def apply_human_verdicts(
    graded_picks: list[dict],
    review: dict[tuple, dict],
) -> list[dict]:
    """
    Tag each graded pick with human_verdict from the review file.
    Modifies picks in-place and returns the list.
    verdict values: "keep" | "trim" | "manual_skip" | None (not reviewed)
    trim_reasons list is also copied across when present.
    """
    if not review:
        return graded_picks
    tagged = 0
    for p in graded_picks:
        name  = (p.get("player_name") or "").strip().lower()
        pt    = p.get("prop_type", "")
        pv    = p.get("pick_value")
        key   = (name, pt, pv)
        entry = review.get(key)
        if entry:
            p["human_verdict"] = entry.get("verdict")
            p["trim_reasons"]  = entry.get("trim_reasons", [])
            tagged += 1
        else:
            p["human_verdict"] = None
            p["trim_reasons"]  = []
    print(f"[auditor] human_verdict: tagged {tagged}/{len(graded_picks)} picks from review file")
    return graded_picks


def build_game_log_rows_for_yesterday() -> dict[str, dict]:
    """
    Build a lookup of yesterday's actual game rows: {player_name_lower: row_dict}.
    Used for grading skip records — did the player actually hit the skipped tier?
    """
    if not GAME_LOG_CSV.exists():
        return {}
    try:
        df = pd.read_csv(GAME_LOG_CSV, dtype=str)
        df = df[df["game_date"] == YESTERDAY_STR]
        df = df[df.get("dnp", pd.Series(["0"] * len(df))) != "1"]
        rows: dict[str, dict] = {}
        for _, row in df.iterrows():
            name_lower = str(row.get("player_name", "")).strip().lower()
            if name_lower:
                rows[name_lower] = row.to_dict()
        return rows
    except Exception as e:
        print(f"[auditor] WARNING: could not build game log rows for yesterday: {e}")
        return {}


SKIP_PROP_COL_MAP = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "3PM": "tpm",
}


def grade_skips(skips: list[dict], game_log_rows: dict[str, dict]) -> list[dict]:
    """
    Grade each skip record: did the player hit the tier that was skipped?
    Fills would_have_hit and skip_verdict fields in-place.
    Returns the same list with fields filled.
    """
    for skip in skips:
        player_lower = skip.get("player_name", "").strip().lower()
        prop_type    = skip.get("prop_type", "")
        tier         = skip.get("tier_considered")
        col          = SKIP_PROP_COL_MAP.get(prop_type)

        if not player_lower or not col or tier is None:
            skip["would_have_hit"]     = None
            skip["skip_verdict"]       = "no_data"
            skip["skip_verdict_notes"] = "missing player/prop/tier"
            continue

        row = game_log_rows.get(player_lower)
        if row is None:
            skip["would_have_hit"]     = None
            skip["skip_verdict"]       = "no_data"
            skip["skip_verdict_notes"] = "player not found in yesterday's game log"
            continue

        try:
            actual = float(row.get(col, 0) or 0)
        except (ValueError, TypeError):
            skip["would_have_hit"]     = None
            skip["skip_verdict"]       = "no_data"
            skip["skip_verdict_notes"] = "could not parse actual value"
            continue

        skip["actual_value"]   = actual
        skip["would_have_hit"] = actual >= float(tier)
        skip["skip_verdict"]   = "false_skip" if skip["would_have_hit"] else "correct_skip"
        skip["skip_verdict_notes"] = (
            f"Actual {actual} {'≥' if skip['would_have_hit'] else '<'} tier {tier}"
        )

    return skips


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

        # Fix 1A — skip voided picks at grading time; preserve result=null sentinel
        if p.get("voided") is True:
            p["result"] = None
            p["actual_value"] = None
            graded.append(p)
            continue

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

    # Fix 1B — detect post-hoc late DNPs: void_reason set but voided not flipped
    # A pick graded MISS with actual=0.0 and a non-empty void_reason is a late DNP
    for p in graded:
        if (
            p.get("result") == "MISS"
            and p.get("actual_value") == 0.0
            and p.get("void_reason")
            and not p.get("voided")
        ):
            p["voided"] = True
            p["result"] = None
            p["actual_value"] = None
            print(f"[auditor] LATE_DNP_PROMOTED: {p.get('player_name')} "
                  f"{p.get('prop_type')} {p.get('pick_value')} — "
                  f"void_reason='{p.get('void_reason')}' → voided=True, result=null")

    return graded


def promote_injury_event_voids(
    graded_picks: list[dict],
    audit_entry: dict,
) -> int:
    """Promote picks classified as injury_event by the auditor LLM to voided
    status. This ensures picks.json, the daily audit entry, and the frontend
    all exclude mid-game injury exits from hit-rate calculations.

    Returns the number of picks promoted.
    """
    miss_details = audit_entry.get("miss_details", [])
    if not miss_details:
        return 0

    # Build a set of (player_name_lower, prop_type, pick_value) for injury_event misses
    injury_keys: set[tuple] = set()
    for miss in miss_details:
        if miss.get("miss_classification") != "injury_event":
            continue
        name = (miss.get("player_name") or "").strip().lower()
        prop = (miss.get("prop_type") or "").strip()
        val  = miss.get("pick_value")
        if name and prop and val is not None:
            injury_keys.add((name, prop, val))

    if not injury_keys:
        return 0

    promoted = 0
    for p in graded_picks:
        if p.get("voided") or p.get("result") != "MISS":
            continue
        name = (p.get("player_name") or "").strip().lower()
        prop = (p.get("prop_type") or "").strip()
        val  = p.get("pick_value")
        if (name, prop, val) in injury_keys:
            p["voided"] = True
            p["result"] = None
            p["void_reason"] = "injury_exit_mid_game"
            promoted += 1
            print(f"[auditor] INJURY_EVENT_VOID: {p.get('player_name')} "
                  f"{prop} {val} — mid-game injury exit → voided=True, result=null")

    # Recompute daily audit entry counts to reflect the exclusions
    if promoted > 0:
        active = [p for p in graded_picks if not p.get("voided", False)]
        hits   = sum(1 for p in active if p.get("result") == "HIT")
        misses = sum(1 for p in active if p.get("result") == "MISS")
        total  = hits + misses
        voided = sum(1 for p in graded_picks if p.get("voided", False))

        audit_entry["total_picks"]  = total
        audit_entry["voided_picks"] = voided
        audit_entry["hits"]         = hits
        audit_entry["misses"]       = misses
        audit_entry["hit_rate_pct"] = round(100 * hits / total, 1) if total > 0 else 0.0

        # Recompute prop_type_breakdown
        ptb = audit_entry.get("prop_type_breakdown", {})
        if ptb:
            for pt_key, pt_data in ptb.items():
                pt_active = [p for p in active
                             if p.get("prop_type") == pt_key
                             and p.get("result") in ("HIT", "MISS")]
                pt_hits = sum(1 for p in pt_active if p["result"] == "HIT")
                pt_data["picks"] = len(pt_active)
                pt_data["hits"]  = pt_hits
                pt_data["hit_rate_pct"] = round(100 * pt_hits / len(pt_active), 1) if pt_active else 0.0

        # Recompute confidence_calibration
        ccb = audit_entry.get("confidence_calibration", {})
        if ccb:
            bands = {"70-75": (70, 75), "76-80": (76, 80), "81-85": (81, 85), "86+": (86, 100)}
            for band, (lo, hi) in bands.items():
                if band not in ccb:
                    continue
                subset = [p for p in active
                          if lo <= p.get("confidence_pct", 0) <= hi
                          and p.get("result") in ("HIT", "MISS")]
                h = sum(1 for p in subset if p["result"] == "HIT")
                ccb[band]["picks"] = len(subset)
                ccb[band]["hits"]  = h
                ccb[band]["hit_rate_pct"] = round(100 * h / len(subset), 1) if subset else 0.0

        print(f"[auditor] Recomputed daily counts after {promoted} injury_event void(s): "
              f"{hits}/{total} = {audit_entry['hit_rate_pct']}%")

    return promoted


def compute_high_conviction_breakdown(
    graded_picks: list[dict],
    audit_entry: dict,
) -> dict:
    """Compute the high-conviction subset stats (market_implied_prob ≥ 85.0)
    and write them to audit_entry["high_conviction_breakdown"].

    Deterministic — no LLM call. Mirrors the shape of prop_type_breakdown so
    the frontend and audit_summary aggregator can render it the same way.

    Returns the breakdown dict (also assigned in-place on audit_entry).
    Must run AFTER promote_injury_event_voids() so HC totals reflect the
    final voided set.
    """
    high_conv = [
        p for p in graded_picks
        if not p.get("voided")
        and p.get("market_implied_prob") is not None
        and float(p["market_implied_prob"]) >= HIGH_CONVICTION_THRESHOLD
        and p.get("result") in ("HIT", "MISS")
    ]
    n_hc = len(high_conv)
    hits_hc = sum(1 for p in high_conv if p["result"] == "HIT")
    misses_hc = n_hc - hits_hc
    hit_rate_hc = round(100.0 * hits_hc / n_hc, 1) if n_hc else None

    overall_hr = audit_entry.get("hit_rate_pct")
    delta_pp = (
        round(hit_rate_hc - overall_hr, 1)
        if hit_rate_hc is not None and overall_hr is not None
        else None
    )

    breakdown = {
        "threshold_market_implied_prob": HIGH_CONVICTION_THRESHOLD,
        "n_picks": n_hc,
        "hits": hits_hc,
        "misses": misses_hc,
        "hit_rate_pct": hit_rate_hc,
        "delta_vs_overall_pp": delta_pp,
    }
    audit_entry["high_conviction_breakdown"] = breakdown
    return breakdown


def _retroactive_injury_void_patch() -> int:
    """One-time patch for injury_event picks graded before the auto-void logic.

    Safe to run repeatedly — only patches picks that match ALL criteria:
    date=2026-04-21, player=Victor Wembanyama, result=MISS, voided!=True.
    Remove this function after it has run once in production (or leave — it's idempotent).
    """
    if not PICKS_JSON.exists():
        return 0
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    except Exception:
        return 0

    patched = 0
    for p in all_picks:
        if (p.get("date") == "2026-04-21"
                and (p.get("player_name") or "").strip().lower() == "victor wembanyama"
                and p.get("result") == "MISS"
                and not p.get("voided")):
            p["voided"] = True
            p["result"] = None
            p["void_reason"] = "injury_exit_mid_game"
            patched += 1

    if patched:
        with open(PICKS_JSON, "w") as f:
            json.dump(all_picks, f, indent=2)

        # Also patch the audit_log entry for 2026-04-21
        if AUDIT_LOG_JSON.exists():
            try:
                with open(AUDIT_LOG_JSON) as f:
                    audit_log = json.load(f)
                for entry in audit_log:
                    if entry.get("date") != "2026-04-21":
                        continue
                    # Subtract the injury_event misses from the daily counts
                    entry["voided_picks"] = entry.get("voided_picks", 0) + patched
                    entry["total_picks"]  = entry.get("total_picks", 0) - patched
                    entry["misses"]       = entry.get("misses", 0) - patched
                    total = entry.get("total_picks", 0)
                    hits  = entry.get("hits", 0)
                    entry["hit_rate_pct"] = round(100 * hits / total, 1) if total > 0 else 0.0
                    break
                with open(AUDIT_LOG_JSON, "w") as f:
                    json.dump(audit_log, f, indent=2)
            except Exception as e:
                print(f"[auditor] WARNING: could not patch audit_log for retro fix: {e}")

    return patched


# ── Prompt builder ───────────────────────────────────────────────────

def build_absence_context(graded_picks: list[dict]) -> str:
    """
    Build a plain-text block listing players confirmed OUT yesterday.
    Sources:
      1. Picks with voided=True (lineup_watch confirmed OUT pre-game)
      2. Picks with injury_status_at_check == "OUT"
    Deduplicates by player name. Returns empty string if none found.
    """
    absent: dict[str, str] = {}  # player_name -> team
    for p in graded_picks:
        name = p.get("player_name", "")
        team = p.get("team", "")
        if not name:
            continue
        if p.get("voided") is True:
            absent[name] = team
        elif p.get("injury_status_at_check") == "OUT":
            absent[name] = team
    if not absent:
        return ""
    lines = [
        f"  - {name} ({team}): confirmed OUT pre-game"
        for name, team in sorted(absent.items())
    ]
    return (
        "## YESTERDAY'S NOTABLE ABSENCES\n"
        "These players were confirmed OUT yesterday. When evaluating hits and misses,\n"
        "check whether a teammate or opponent absence amplified or suppressed usage.\n"
        "A pick overperforming its tier may reflect absence-driven usage expansion.\n"
        "A pick missing despite favorable signals may have been undermined by an\n"
        "unexpected absence that reduced pace, possessions, or role definition.\n\n"
        + "\n".join(lines) + "\n"
    )


def build_audit_prompt(graded_picks: list[dict], season_context: str = "", post_game_news: dict | None = None, playoff_picture: str = "", game_results_block: str = "") -> str:
    # Split voided (confirmed OUT pre-game) from active picks.
    # Voided picks are excluded from all counting and statistical breakdowns —
    # the system should not be docked for picks that were correctly voided.
    # build_absence_context() still receives all graded_picks to detect voided players.
    voided_picks = [p for p in graded_picks if p.get("voided") is True]
    active_picks = [p for p in graded_picks if not p.get("voided", False)]

    hits    = [p for p in active_picks if p["result"] == "HIT"]
    misses  = [p for p in active_picks if p["result"] == "MISS"]
    no_data = [p for p in active_picks if p["result"] == "NO_DATA"]

    total_gradeable = len(hits) + len(misses)
    hit_rate = round(100 * len(hits) / total_gradeable, 1) if total_gradeable > 0 else 0

    playoff_picture_section = f"{playoff_picture}\n\n" if playoff_picture else ""

    # ── Pre-computed breakdown stats ──────────────────────────────────
    prop_breakdown: dict = defaultdict(lambda: {"picks": 0, "hits": 0})
    for p in active_picks:
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
        subset = [p for p in active_picks
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

    hits_and_misses = [p for p in active_picks if p["result"] in ("HIT", "MISS")]

    # Annotate picks where post_game_news indicates injury_exit — gives Claude
    # a direct signal in the pick object, independent of the news block parsing.
    if post_game_news:
        for p in hits_and_misses:
            name_lower = (p.get("player_name") or "").strip().lower()
            news_entry = post_game_news.get(name_lower, {})
            if news_entry.get("event_type") == "injury_exit":
                p["post_game_event"] = "injury_exit"
                p["post_game_detail"] = news_entry.get("detail", "")

    picks_block   = json.dumps(hits_and_misses, indent=2)
    no_data_block_str = json.dumps(no_data, indent=2) if no_data else "[]"

    # ── Absence context block — uses all graded_picks (voided players ARE the absences)
    absence_block = build_absence_context(graded_picks)

    # ── Post-game news block ──────────────────────────────────────────
    news_block = ""
    if post_game_news:
        news_lines = []
        for name, event in post_game_news.items():
            et       = event.get("event_type", "no_data").upper().replace("_", " ")
            detail   = event.get("detail", "")
            mins     = event.get("minutes_played", "?")
            conf     = event.get("confidence", "unknown")
            inj_flag = " ⚠ INJURY LANGUAGE IN NEWS" if event.get("injury_language_detected") else ""
            narrative_str = ""
            web_narr = event.get("web_narrative")
            if web_narr:
                narrative_str = f"\n  📰 WEB RECAP: {web_narr}"
            news_lines.append(f"{name}: {et} — {detail} ({mins} min played) [{conf}]{inj_flag}{narrative_str}")
        news_block = (
            "## POST-GAME NEWS CONTEXT\n"
            "The following post-game facts were confirmed or inferred for yesterday's players.\n"
            "Use this section as ground truth when classifying misses. Do NOT guess at DNP/injury\n"
            "status for any player listed here — treat these facts as definitive.\n\n"
            + "\n".join(news_lines)
            + "\n\nPlayers NOT listed above: no notable post-game event detected."
              " Standard box score analysis applies.\n"
        )

    return f"""You are the Auditor for NBAgent, an NBA player props selection system.

Today is {dt.datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")}.
You are auditing picks and parlays made for {YESTERDAY_STR}.

## IMPORTANT: YOUR TRAINING KNOWLEDGE IS POTENTIALLY YEARS OUT OF DATE
Your model weights were frozen at a training cutoff that may be 1–2+ years behind today's date.
When grading picks and classifying misses, this creates a specific risk: you may reason about
a player's role, usage, or team context from stale training memory rather than from the data
that was actually available to the Analyst at pick time.

**Trust the injected data. Distrust your priors on anything perishable.**

Perishable knowledge — do NOT rely on your training data when grading:
- Player roles and usage: A player you know as a star may now be a bench reserve,
  or vice versa. Do not assume a miss is "variance" because you remember the player
  as reliable — check the hit_rate_display and tier_walk in the pick object.
- Team rosters and depth charts: Trades, injuries, and role changes accumulate
  continuously. Do not reason about a player's expected output from memory — use
  the raw_avgs, trend, and opp_defense fields in the pick object as ground truth
  for what the Analyst had available.
- Team systems and pace: Do not reason about how a team "typically" plays from
  memory. Use the game_pace and opp_defense fields in the pick context.
- Season narratives: Any "this player is on a hot streak" recollection from your
  training is stale. Today's form is in the L10 game log fields and trend tag
  in the pick object. Use those.

Durable knowledge — APPLY freely when grading:
- General basketball principles: how usage concentration works, how B2B fatigue
  manifests, how pace affects counting stats, how a key player's absence typically
  redistributes production.
- Statistical reasoning: hit rate interpretation, regression to the mean, sample
  size caution, what constitutes a sound pick vs. a marginal one.
- Miss classification logic: what distinguishes selection_error from model_gap_signal
  vs. model_gap_rule vs. variance — these are analytical frameworks, not player facts.

When in doubt about a player-specific fact: use the injected pick object fields, quant
context, and SEASON CONTEXT doc as ground truth. Do not override them with your training
recollection.

## GRADING RULE — READ FIRST
A pick is a HIT if actual_value >= pick_value. Exact threshold matches are HITs, not misses.
Do not flag exact-threshold results as near-misses or line-value problems in your analysis.

## SEASON CONTEXT — READ BEFORE ANALYZING ANY PICK
{season_context if season_context else "No season context file found."}

{game_results_block}
{playoff_picture_section}Players marked OFS all season are permanent absences. Their teammates' current roles are baselines,
not elevations. Do not cite these absences as a causal factor in any pick reasoning or audit
analysis.

## PICK GRADED RESULTS SUMMARY
- Total picks (active): {len(active_picks)} | Voided (DNP/OUT pre-game): {len(voided_picks)} | Hits: {len(hits)} | Misses: {len(misses)}
- No data (DNP/missing, active only): {len(no_data)}
- Hit rate (gradeable only, voided excluded): {hit_rate}%

## PRE-COMPUTED STATISTICS
Use these values exactly when filling prop_type_breakdown and confidence_calibration in your output.
These are pre-calculated from the graded picks — do not recalculate.

By prop type (HITs + MISSes only, excluding NO_DATA):
{prop_stats_block}

By confidence band (HITs + MISSes only):
{conf_stats_block}

## FULL GRADED PICKS (HIT and MISS only)
{picks_block}

## NO_DATA PICKS (box score not found — player may have DNP'd)
These picks returned no box score data. They are NOT misses — do not classify them as
selection_error, model_gap_signal, model_gap_rule, or variance. Handle them exclusively
in the NO_DATA ANALYSIS TASK below.

{no_data_block_str}

## QUANT CONTEXT — READ FROM PICK OBJECTS
Each pick object in FULL GRADED PICKS contains the quant data that was live at pick time:
- "reasoning": the analyst's original thesis — read this for every miss
- "hit_rate_display": e.g. "8/10" — reference this explicitly in root cause
- "trend": up/stable/down at pick time
- "tier_walk": the analyst's walk-down, e.g. "PTS: 30→3/10 25→5/10 20→8/10✓"
- "opponent": yesterday's opponent (correct at pick time)
- "confidence_pct", "prop_type", "pick_value": as set by the analyst
- "lineup_update": sub-object present when the afternoon lineup agent amended the pick.
  Fields: direction ("up"/"down"/"unchanged"), revised_confidence_pct, revised_reasoning,
  triggered_by (list of change strings). Absent when no amendment was triggered.

Do NOT attempt to load or reference external player stats data. The pick objects are the
authoritative record of what the system knew at pick time.

{absence_block}{news_block}## NO_DATA ANALYSIS TASK

For each pick in NO_DATA PICKS above, perform this analysis:

PRE-CHECK — POST-GAME NEWS: First look up the player's name (lowercase) in the POST-GAME
NEWS CONTEXT section. If an entry exists:
  - Use its event_type and detail as the authoritative explanation.
  - A "dnp" entry = player did not play. A "injury_exit" entry = player exited mid-game.
  - Set no_data_classification to the event_type value from that entry.
  - Set no_data_explanation to the detail string from that entry.
  - If confidence = "confirmed", state this in your explanation.

If NO post-game news entry exists for this player:
  - Look at their injury_status_at_check field on the pick object.
  - "OUT" or "DOUBTFUL" at pick time → no_data_classification = "workflow_gap"
  - "QUESTIONABLE" → no_data_classification = "dnp_unconfirmed" and note the ambiguity.
  - NOT_LISTED with no news → no_data_classification = "data_gap" and note this is
    unexplained — the post-game reporter may not have had an ESPN entry for this player.

DO NOT generate lessons, recommendations, or analytical critique for NO_DATA picks. These
are availability or data pipeline events, not analytical failures. The only exception: if
no_data_classification = "workflow_gap" (player was OUT pre-game but not voided), write one
sentence in no_data_explanation noting the workflow timing gap.

Add each NO_DATA pick to the "no_data_details" array in your output (see OUTPUT FORMAT).

## PICK ANALYSIS TASK

For every miss, perform analysis in this exact order before writing root_cause:

STEP 0 — ESTABLISH GAME CONTEXT: Before analyzing any individual miss, look up the player's
team abbreviation in the ## GAME RESULTS — YESTERDAY section above.
  - Identify the final score and margin for their game.
  - Note the game_script label: BLOWOUT / COMPETITIVE / CLOSE.
  - If the game was a BLOWOUT (margin ≥ 20), apply game-script reasoning to ALL
    players from that game — both the winning side (garbage-time production compression,
    star resting once lead is safe) and the losing side (starters benched in the fourth
    quarter, offensive rhythm disrupted). Do NOT require a separate web narrative to
    apply blowout game-script reasoning when the margin is already established here.
  - When multiple misses share the same game, establish the game context ONCE and
    carry it forward as shared evidence for all players in that game. Do not re-derive
    or contradict it per player.
  - Game-script context established in STEP 0 is an input to STEP 2 miss classification.
    A miss explained by blowout on either side is typically model_gap_rule (the signal —
    pre-game spread — existed but the rule threshold was too permissive) or variance
    (spread was already flagged and pick was made at reduced confidence). Use the
    pre-game spread and blowout_risk field from the pick object alongside the actual
    margin to determine which applies.
  - If the game was COMPETITIVE or CLOSE: note this as neutral context. Game script
    is not a causal factor for misses in these games.
  - If game results are unavailable (## GAME RESULTS section is empty or player's
    team not listed): proceed to STEP 1 using post-game news and pick object fields
    as normal.

STEP 1 — CHECK ACTIVITY: Did the player record any non-zero stat in any category (REB, AST,
minutes implied by any non-zero output)? If actual_value is 0 for the picked stat, check all
other stat fields before concluding DNP. Do not conclude DNP or lineup failure unless ALL stats
are zero AND no minutes evidence exists.

STEP 2 — CHECK INJURY STATUS, THEN CLASSIFY THE MISS as exactly one of:

  FAST PATH — CHECK POST-GAME NEWS FIRST:
  Before reading the pick object fields, look up the player's name (lowercase) in
  ## POST-GAME NEWS CONTEXT. If event_type = "injury_exit" is listed there:
    → Classify as "injury_event" immediately.
    → Do NOT proceed to model_gap_rule, model_gap_signal, or variance analysis.
    → Root cause: one sentence: "In-game injury exit confirmed by post-game news —
      [detail from news entry]. Player active at pick time; miss not attributable to
      pick selection logic."
    → Do NOT write a lesson or recommendation for this miss.
  This fast path applies regardless of confidence level ("confirmed" or "inferred").
  An inferred injury exit from injury language in ESPN news is still a stronger
  signal than box score analysis alone — do not override it with game-script reasoning.
  Also check the pick object itself: if post_game_event = "injury_exit" is set on the
  pick, that is a direct annotation from the post-game news pipeline — treat it the
  same as finding injury_exit in the news block above.

  If no injury_exit event in POST-GAME NEWS and no post_game_event field on the pick,
  inspect the pick object's injury_status_at_check and voided fields before choosing
  any classification. Prefer injury_event or workflow_gap when the evidence supports
  them — these take priority over selection_error, model_gap_signal, model_gap_rule, or variance.

  - "injury_event": player was confirmed active at pick time (injury_status_at_check
    was NOT_LISTED or QUESTIONABLE) but exited the game mid-game due to injury.
    Evidence: very low minutes logged (< 10 minutes) regardless of individual stat
    values — a player can score 6 PTS in 5 minutes and still be an injury_exit if
    they were forced out with a Q1 injury. Also applies when stats are near-zero
    across all categories with confirmed low minutes. Check the POST-GAME NEWS CONTEXT
    block first: if event_type = "injury_exit" is listed for the player (with any
    confidence level), that is the authoritative classification — use injury_event
    regardless of what the individual stat values show. Do NOT classify as
    model_gap_rule, model_gap_signal, or variance when POST-GAME NEWS CONTEXT
    shows an injury exit event for this player.
  - "workflow_gap": player was listed OUT or DOUBTFUL pre-game (injury_status_at_check
    = "OUT" or "DOUBTFUL" on the pick object) but voided = false. This is a timing
    or workflow failure — lineup_watch did not void the pick before game time. Use
    this whenever pre-game OUT/DOUBTFUL status explains the miss.
  - "selection_error": the pick was wrong given data available at pick time
    (bad hit rate, wrong tier, ignored injury context, etc.)
  - "model_gap_signal": pick was reasonable but the system lacks the signal entirely —
    no quant field, annotation, or prompt rule exists that could have caught this.
    Examples: teammate rebounding competition, scheme-type DvP mismatch (switching vs.
    drop coverage), assist suppression by specific defensive structure.
    Use when the miss required a signal NBAgent doesn't compute yet.
  - "model_gap_rule": the signal existed in quant data or context at pick time, but the
    analyst rule didn't correctly handle the combination.
    Examples: blowout-resilient tag overcorrected on a large spread, QUESTIONABLE ankle
    tag not penalized on a shooting prop, B2B penalty not applied to secondary scorer.
    Use when the miss would have been caught by a tighter or better-tuned prompt rule,
    using data already present in the pick object or quant context.
  - "variance": pick was sound, player had an off night. Hit rate and context
    supported the pick; outcome was within normal variance range.

IMPORTANT — RECOMMENDATION CONTAMINATION GUARDS:

Three classes of pick outcomes must NOT drive tightening recommendations
that target the Analyst's selection logic. These guards exist because
recommendations roll up into the Analyst's next-run feedback and become
de-facto rules; recommendations grounded in non-signal must be filtered
at write time.

GUARD 1 — INJURY AND WORKFLOW MISSES:
For any miss classified as injury_event or workflow_gap, do NOT write a
lesson or recommendation targeting the Analyst's pick selection logic.
These are not analytical errors. Write a single neutral note in
root_cause only (e.g. "Workflow gap: player listed OUT pre-game, pick
not voided in time" or "Injury event: player exited mid-game, near-zero
output despite active pre-game status"). Exclude these picks entirely
from the lessons and recommendations arrays.

This guard cannot be bypassed by reframing the recommendation around the
pick's risk profile (e.g. "Players combining FG_COLD + VOLATILE + 70%
confidence should be skip-eligible — see Ingram"). If a pick missed
because of an injury event, NO recommendation may cite that pick or its
risk profile, even indirectly. The risk profile that "would have been
fragile if the player had actually played" is not evidence — the player
did not play long enough to test the profile.

GUARD 2 — VARIANCE MISSES:
For any miss classified as variance, do NOT write a recommendation
targeting the Analyst's pick selection logic. By the variance
classification's own definition ("pick was sound, player had an off
night; outcome was within normal variance range"), the pick was correct
and the outcome was noise. Tightening selection logic in response to
noise is overfitting.

You may write a lesson noting the outcome for context (e.g. "Mobley AST
T2 missed by 1 — within distribution for a player averaging ~2.0 AST in
playoffs"), but the lessons array entry must NOT propose a rule change.
Lessons describe; recommendations prescribe. Variance can drive a
description but never a prescription.

GUARD 3 — HITS:
The recommendations array exists exclusively to address actual MISSES.
A pick that HIT, regardless of how marginally or how uncomfortable the
auditor felt about it, may NOT motivate a tightening recommendation. If
two players (e.g. Mobley PTS T10 and Harden PTS T10) both hit at 68%
confidence with LATE_FADER and VOLATILE tags, the recommendation array
must NOT contain "skip such picks in future." The picks worked. The
threshold the system used was correct.

If you observe a pattern of marginal hits and want to surface it, use
the reinforcements array: "LATE_FADER + VOLATILE + 68% confidence
picks (Mobley PTS, Harden PTS) both hit despite carrying multiple
structural warnings — the minimum confidence floor is calibrated
correctly for these cases." Do not redirect this pattern observation
into a tightening recommendation.

NARROW MISS NOTE (not a hard guard, but informational):
A miss by exactly 1 unit on PTS, REB, or AST (e.g. Sengun PTS 14 vs
T15, LeBron REB 3 vs T4) typically indicates the tier was correctly at
the edge of viability; the player simply landed on the wrong side of
the threshold. Such misses can legitimately be classified as
model_gap_rule or model_gap_signal IF a specific structural mechanism
is identified (e.g. "no T10 market existed; the inability to step down
materially raised tail risk" or "opponent's league-leading OREB%
structurally compresses opponent REB volume"). They should NOT be
classified as model_gap on purely "the system should have been more
cautious" grounds — that reasoning applies to every miss-by-1 by
construction and would tighten the system into producing zero picks.

When in doubt on a miss-by-1, prefer the variance classification over
model_gap. Variance is the correct floor classification when the pick's
hit-rate, matchup, and minutes evidence all supported the selection.

SUMMARY OF WHAT IS ALLOWED IN RECOMMENDATIONS:
The recommendations array should contain prescriptive rule changes
motivated by ONE OR MORE of:
  - selection_error misses (analyst chose a tier that quant data did
    not support);
  - model_gap_rule misses where the structural mechanism is explicit
    and reproducible;
  - model_gap_signal misses where the missing signal is identifiable
    and could be operationalized;
  - patterns of repeated misses across multiple picks that reveal a
    systematic blind spot (not single-instance outcomes).

Recommendations must NOT be motivated by injury_event misses,
workflow_gap misses, variance misses, hits the auditor felt
uncomfortable with, or single miss-by-1 outcomes lacking a specific
mechanism.

If the slate had no qualifying misses for recommendations, write
recommendations addressing reinforcements ("the analyst is correctly
applying X — continue") or simply state that no rule changes are
warranted from this slate. An empty or short recommendations array is
preferable to a contaminated one.

STEP 3 — CRITIQUE THE ORIGINAL REASONING: The pick object includes a "reasoning" field
containing the analyst's original thesis. Read it. If the pick missed, identify specifically
what was wrong or missing in that reasoning. If the pick hit, identify what the reasoning got
right. Do not ignore this field.

STEP 4 — REFERENCE HIT RATE DATA: Every pick includes hit_rate_display (e.g. "8/10") and
trend ("up"/"stable"/"down"). Reference these explicitly in your root cause. A miss on an
8/10 hit rate pick is different from a miss on a 5/10 pick.

STEP 5 — INSPECT TIER WALK: Every pick includes a "tier_walk" field documenting the
analyst's walk-down (e.g. "PTS: 30→3/10 25→5/10 20→8/10✓"). For misses classified as
"selection_error", check whether:
  (a) A higher tier also qualified (≥70% hit rate) but was skipped — flag as tier_skip_error
      in root_cause
  (b) The selected tier's hit rate in tier_walk contradicts the hit_rate_display field —
      flag as data_conflict in root_cause
  (c) Only one tier was evaluated and it was marginal (≤72%) — flag as insufficient_walk
      in root_cause
For variance and model_gap misses, note the tier_walk only if it reveals something
unexpected (e.g. the selected tier was the only viable option, confirming the pick was
sound despite the miss).
If the pick has no tier_walk field (older picks pre-dating this feature), skip STEP 5.

STEP 6 — CHECK AMENDMENT STATUS: For every pick (hit or miss), check whether a
"lineup_update" sub-object is present.
  If present and direction = "down":
    - If the pick MISSED: note in root_cause that the afternoon amendment correctly flagged
      downside risk. Phrase as: "Amendment correctly flagged: [triggered_by summary]. Revised
      down to [revised_confidence_pct]% — pick still ran and missed." This is a feature
      validation data point.
    - If the pick HIT: note in root_cause that the amendment was overcautious. Phrase as:
      "Amendment flagged downside (revised to [revised_confidence_pct]%) but pick hit."
  If present and direction = "up":
    - If the pick HIT: note briefly in root_cause that the amendment correctly identified
      upside. Phrase as: "Amendment flagged upside (revised to [revised_confidence_pct]%)."
    - If the pick MISSED: note in root_cause that the amendment missed the real risk. Phrase
      as: "Amendment flagged upside (revised to [revised_confidence_pct]%) but pick missed."
  If present and direction = "unchanged":
    - No comment needed in root_cause. The amendment found no meaningful update.
  If absent:
    - No comment needed. The pick was not evaluated by the afternoon agent (either no lineup
      changes were detected for this player's game, or the agent had not yet run).
Do NOT change the miss_classification based on amendment status alone. Amendments are
contextual notes on the feature's performance, not a reclassification trigger.

For hits: identify what the Analyst got right — specific statistical patterns, matchup reads,
or reasoning that proved correct.

Synthesize 3–5 concrete, actionable recommendations for the Analyst's next run based on
patterns across the full set of picks. Be specific — reference player names, prop types,
and numbers.

## OUTPUT FORMAT
Respond ONLY with valid JSON. No preamble.

{{
  "date": "{YESTERDAY_STR}",
  "total_picks": {len(active_picks)},
  "voided_picks": {len(voided_picks)},
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
      "miss_classification": "selection_error | model_gap_signal | model_gap_rule | variance | injury_event | workflow_gap",
      "tier_walk_flag": "tier_skip_error | data_conflict | insufficient_walk | null",
      "root_cause": "string"
    }}
  ],
  "no_data_details": [
    {{
      "player_name": "string",
      "prop_type": "string",
      "pick_value": number,
      "no_data_classification": "dnp | injury_exit | minutes_restriction | workflow_gap | dnp_unconfirmed | data_gap",
      "no_data_explanation": "string — one sentence, sourced from post_game_news or pick object fields"
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

def save_skip_archive(graded_skips: list[dict]) -> None:
    """Append today's graded skip records to the persistent skip archive."""
    if not graded_skips:
        return
    existing: list[dict] = []
    if SKIP_ARCHIVE_JSON.exists():
        try:
            with open(SKIP_ARCHIVE_JSON) as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    # Remove any existing entries for the same date to prevent duplicates on re-run
    date_str = graded_skips[0].get("date", YESTERDAY_STR)
    existing = [s for s in existing if s.get("date") != date_str]
    existing.extend(graded_skips)
    with open(SKIP_ARCHIVE_JSON, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"[auditor] Archived {len(graded_skips)} graded skips → {SKIP_ARCHIVE_JSON}")


def save_audit(audit_entry: dict, graded_picks: list[dict]):
    # Update picks.json with graded results
    all_picks = []
    if PICKS_JSON.exists():
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    non_yesterday = [p for p in all_picks if p.get("date") != YESTERDAY_STR]
    updated_picks = non_yesterday + graded_picks

    # Compute per-pick CLV for yesterday's graded picks
    n_clv = 0
    for p in graded_picks:
        morning = p.get("morning_implied_prob")
        pretip  = p.get("market_implied_prob")
        if morning is not None and pretip is not None and p.get("result") in ("HIT", "MISS"):
            clv = round(float(pretip) - float(morning), 2)
            p["clv_pp"] = clv
            n_clv += 1
    if n_clv:
        print(f"[auditor] CLV computed for {n_clv} picks")

    with open(PICKS_JSON, "w") as f:
        json.dump(updated_picks, f, indent=2)
    print(f"[auditor] Updated picks.json with graded results")

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

    # ── Grade yesterday's skip records ────────────────────────────────
    skips = load_skipped_picks()
    if skips:
        game_log_rows = build_game_log_rows_for_yesterday()
        skips = grade_skips(skips, game_log_rows)
        try:
            with open(SKIPPED_PICKS_JSON, "w") as f:
                json.dump(skips, f, indent=2)
            print(f"[auditor] Graded {len(skips)} skip records → {SKIPPED_PICKS_JSON}")
        except Exception as e:
            print(f"[auditor] WARNING: could not write graded skips: {e}")
        save_skip_archive(skips)

    save_audit_summary(existing_log, all_skips=skips if skips else None)
    save_audit_report(audit_entry, graded_picks, skips=skips)


def _compute_playoff_calibration(
    regular_season_bands: dict,
) -> tuple[dict | None, list[str]]:
    """
    Compute playoff-specific confidence calibration from picks.json.
    Compares playoff-only hit rates per band to regular-season baselines.

    Returns (playoff_cal_dict, warnings) where:
      - playoff_cal_dict: per-band playoff stats, or None if insufficient data
      - warnings: list of warning strings for divergent bands (empty if none)

    Only fires when >= PLAYOFF_CAL_MIN_PICKS graded playoff picks exist.
    """
    warnings: list[str] = []

    if not PICKS_JSON.exists():
        return None, warnings

    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    except Exception as e:
        print(f"[auditor] WARNING: could not read picks.json for playoff cal: {e}")
        return None, warnings

    # Filter to graded playoff picks (date >= PLAYOFFS_R1_DATE, non-voided, HIT or MISS)
    playoff_picks = [
        p for p in all_picks
        if p.get("date", "") >= PLAYOFFS_R1_DATE
        and not p.get("voided", False)
        and p.get("result") in ("HIT", "MISS")
    ]

    if len(playoff_picks) < PLAYOFF_CAL_MIN_PICKS:
        if playoff_picks:
            print(f"[auditor] Playoff calibration: {len(playoff_picks)} picks — "
                  f"waiting for {PLAYOFF_CAL_MIN_PICKS} before analysis")
        return None, warnings

    # Group by confidence band
    bands_map = {
        "70-75": (70.0, 75.99),
        "76-80": (76.0, 80.99),
        "81-85": (81.0, 85.99),
        "86+":   (86.0, 999.0),
    }
    band_data: dict = {b: {"picks": 0, "hits": 0} for b in bands_map}

    for p in playoff_picks:
        conf = p.get("confidence_pct")
        result = p.get("result")
        if conf is None:
            continue
        sc = float(conf)
        for band_label, (lo, hi) in bands_map.items():
            if lo <= sc <= hi:
                band_data[band_label]["picks"] += 1
                if result == "HIT":
                    band_data[band_label]["hits"] += 1
                break

    # Build playoff calibration summary
    playoff_cal: dict = {}
    total_playoff = sum(d["picks"] for d in band_data.values())
    total_playoff_hits = sum(d["hits"] for d in band_data.values())

    for band_label, d in band_data.items():
        n = d["picks"]
        h = d["hits"]
        rate = round(h / n * 100, 1) if n > 0 else None

        # Compare to regular-season band
        rs_band = regular_season_bands.get(band_label, {})
        rs_rate = rs_band.get("hit_rate_pct")
        divergence = round(rate - rs_rate, 1) if rate is not None and rs_rate is not None else None

        playoff_cal[band_label] = {
            "picks":               n,
            "hits":                h,
            "hit_rate_pct":        rate,
            "regular_season_pct":  rs_rate,
            "divergence_pp":       divergence,
        }

        # Warn on significant underperformance
        if (divergence is not None
                and divergence <= -PLAYOFF_CAL_DIVERGE_PP
                and n >= 5):  # require at least 5 picks in the band
            msg = (f"[PLAYOFF CALIBRATION WARNING] {band_label}% band: "
                   f"playoff {rate}% vs regular-season {rs_rate}% "
                   f"(Δ{divergence:+.1f}pp, n={n})")
            print(msg)
            warnings.append(
                f"Playoff calibration divergence in {band_label}% band: "
                f"{rate}% actual vs {rs_rate}% regular-season "
                f"({divergence:+.1f}pp, n={n}). Investigate whether this is "
                f"structural (playoff defense, scheme adaptation) or variance."
            )

    # Overall playoff hit rate
    overall_rate = round(total_playoff_hits / total_playoff * 100, 1) if total_playoff > 0 else None
    playoff_cal["_overall"] = {
        "picks":        total_playoff,
        "hits":         total_playoff_hits,
        "hit_rate_pct": overall_rate,
        "date_range": {
            "start": min(p.get("date", "") for p in playoff_picks),
            "end":   max(p.get("date", "") for p in playoff_picks),
        },
    }

    print(f"[auditor] Playoff calibration check: {total_playoff} picks, "
          f"{overall_rate}% overall"
          f"{f', {len(warnings)} warning(s)' if warnings else ''}")

    return playoff_cal, warnings


def save_audit_summary(audit_log: list[dict], all_skips: list[dict] | None = None):
    """Roll up all audit entries into a longitudinal summary for the Analyst."""
    if not audit_log:
        return

    # ── Overall totals ─────────────────────────────────────────────────
    total_picks  = sum(e.get("total_picks",  0) for e in audit_log)
    total_voided = sum(e.get("voided_picks", 0) for e in audit_log)  # older entries return 0 via .get()
    total_hits   = sum(e.get("hits",         0) for e in audit_log)
    total_misses = sum(e.get("misses",       0) for e in audit_log)
    gradeable    = total_hits + total_misses

    # ── Per-prop aggregation (from prop_type_breakdown in each entry) ──
    prop_agg: dict = defaultdict(lambda: {"picks": 0, "hits": 0})
    for entry in audit_log:
        ptb = entry.get("prop_type_breakdown") or {}
        for pt, d in ptb.items():
            prop_agg[pt]["picks"] += d.get("picks", 0)
            prop_agg[pt]["hits"]  += d.get("hits",  0)

    # injury_event exclusions — these misses are not predictive failures
    injury_event_by_prop: dict = defaultdict(int)
    for entry in audit_log:
        for miss in entry.get("miss_details", []):
            if miss.get("miss_classification") == "injury_event":
                pt = miss.get("prop_type", "")
                if pt:
                    injury_event_by_prop[pt] += 1

    prop_summary = {}
    for pt, d in prop_agg.items():
        p    = d["picks"]
        h    = d["hits"]
        excl = injury_event_by_prop.get(pt, 0)
        adjusted_denom = p - excl
        prop_summary[pt] = {
            "picks":             p,
            "hits":              h,
            "injury_exclusions": excl,
            "hit_rate_pct":      round(h / adjusted_denom * 100, 1) if adjusted_denom > 0 else 0.0,
        }

    # ── Miss classification breakdown ──────────────────────────────────
    miss_classes: dict = defaultdict(int)
    for entry in audit_log:
        for miss in entry.get("miss_details", []):
            mc = miss.get("miss_classification", "")
            if mc in ("selection_error", "model_gap_signal", "model_gap_rule", "variance", "injury_event", "workflow_gap"):
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

    # ── Overall hit rate (injury_event exclusions applied) ────────────
    total_injury_exclusions = sum(injury_event_by_prop.values())
    gradeable_adjusted      = gradeable - total_injury_exclusions
    overall_hr              = round(total_hits / gradeable_adjusted * 100, 1) if gradeable_adjusted > 0 else 0.0

    # ── Skip validation rollup ─────────────────────────────────────────
    skip_validation: dict = {}
    if all_skips:
        by_rule: dict = defaultdict(lambda: {"total": 0, "false_skips": 0, "no_data": 0})
        for s in all_skips:
            rule    = s.get("skip_reason", "unknown")
            verdict = s.get("skip_verdict", "no_data")
            by_rule[rule]["total"] += 1
            if verdict == "false_skip":
                by_rule[rule]["false_skips"] += 1
            elif verdict == "no_data":
                by_rule[rule]["no_data"] += 1
        for rule, counts in by_rule.items():
            gradeable_skips = counts["total"] - counts["no_data"]
            skip_validation[rule] = {
                "total":           counts["total"],
                "false_skips":     counts["false_skips"],
                "correct_skips":   gradeable_skips - counts["false_skips"],
                "no_data":         counts["no_data"],
                "false_skip_rate": round(
                    counts["false_skips"] / gradeable_skips * 100, 1
                ) if gradeable_skips > 0 else None,
            }

    # ── Human flag precision rollup ────────────────────────────────────────
    # Accumulate hit/miss counts by human_verdict across all graded picks
    # in picks.json (which has been updated by save_audit() before this call).
    human_flag_precision: dict = {}
    try:
        if PICKS_JSON.exists():
            with open(PICKS_JSON) as fh:
                all_picks_for_precision = json.load(fh)
            verdict_buckets: dict = defaultdict(lambda: {"hits": 0, "misses": 0})
            for px in all_picks_for_precision:
                verdict = px.get("human_verdict")
                result  = px.get("result")
                if verdict in ("trim", "manual_skip", "keep") and result in ("HIT", "MISS"):
                    verdict_buckets[verdict]["hits"]   += (1 if result == "HIT" else 0)
                    verdict_buckets[verdict]["misses"] += (1 if result == "MISS" else 0)
            for verdict, counts in verdict_buckets.items():
                total = counts["hits"] + counts["misses"]
                human_flag_precision[verdict] = {
                    "hits":         counts["hits"],
                    "misses":       counts["misses"],
                    "total":        total,
                    "hit_rate_pct": round(counts["hits"] / total * 100, 1) if total > 0 else None,
                }
    except Exception as e:
        print(f"[auditor] WARNING: could not compute human_flag_precision: {e}")
        human_flag_precision = {}

    # ── CLV (Closing Line Value) rollup ──────────────────────────────────
    # Scan all graded picks for morning vs pretip odds data.
    # CLV = pretip_implied - morning_implied. Positive = beat the close.
    clv_summary: dict = {}
    try:
        if PICKS_JSON.exists():
            with open(PICKS_JSON) as fh:
                all_picks_for_clv = json.load(fh)
            clv_picks = []
            for px in all_picks_for_clv:
                clv = px.get("clv_pp")
                result = px.get("result")
                if clv is not None and result in ("HIT", "MISS"):
                    clv_picks.append({"clv": float(clv), "hit": result == "HIT"})

            if clv_picks:
                total       = len(clv_picks)
                beat_close  = [c for c in clv_picks if c["clv"] > 0.5]
                lost_close  = [c for c in clv_picks if c["clv"] < -0.5]
                no_movement = [c for c in clv_picks if abs(c["clv"]) <= 0.5]
                avg_clv     = round(sum(c["clv"] for c in clv_picks) / total, 2)

                beat_hits  = sum(1 for c in beat_close if c["hit"])
                lost_hits  = sum(1 for c in lost_close if c["hit"])

                clv_summary = {
                    "total_with_clv":          total,
                    "beat_close":              len(beat_close),
                    "lost_close":              len(lost_close),
                    "no_movement":             len(no_movement),
                    "avg_clv_pp":              avg_clv,
                    "beat_close_pct":          round(len(beat_close) / total * 100, 1) if total > 0 else 0.0,
                    "beat_close_hit_rate_pct": round(beat_hits / len(beat_close) * 100, 1) if beat_close else None,
                    "lost_close_hit_rate_pct": round(lost_hits / len(lost_close) * 100, 1) if lost_close else None,
                    "no_move_hit_rate_pct":    round(
                        sum(1 for c in no_movement if c["hit"]) / len(no_movement) * 100, 1
                    ) if no_movement else None,
                }
                print(f"[auditor] CLV summary: {total} picks with data, "
                      f"avg CLV {avg_clv:+.1f}pp, "
                      f"{len(beat_close)} beat close, {len(lost_close)} lost close")
    except Exception as e:
        print(f"[auditor] WARNING: could not compute clv_summary: {e}")
        clv_summary = {}

    # ── High-conviction subset rollup ──────────────────────────────────
    # Aggregates the per-day high_conviction_breakdown blocks across all
    # audit entries that carry the field. Historical entries (pre-2026-04-25)
    # lack the field — they're skipped via .get() and do not count toward
    # n_days_included. The threshold is fixed at module level
    # (HIGH_CONVICTION_THRESHOLD = 85.0).
    hc_total = 0
    hc_hits = 0
    hc_misses = 0
    n_days_with_hc = 0
    for entry in audit_log:
        hcb = entry.get("high_conviction_breakdown")
        if not hcb or hcb.get("n_picks", 0) == 0:
            continue
        hc_total += hcb["n_picks"]
        hc_hits += hcb["hits"]
        hc_misses += hcb["misses"]
        n_days_with_hc += 1

    hc_hit_rate = round(100.0 * hc_hits / hc_total, 1) if hc_total else None
    hc_delta_pp = (
        round(hc_hit_rate - overall_hr, 1)
        if hc_hit_rate is not None and overall_hr is not None
        else None
    )

    high_conviction_summary = {
        "threshold_market_implied_prob": HIGH_CONVICTION_THRESHOLD,
        "n_days_included":               n_days_with_hc,
        "n_picks":                       hc_total,
        "hits":                          hc_hits,
        "misses":                        hc_misses,
        "hit_rate_pct":                  hc_hit_rate,
        "delta_vs_overall_pp":           hc_delta_pp,
    }

    summary = {
        "generated_at":    TODAY.strftime("%Y-%m-%d"),
        "entries_included": len(audit_log),
        "overall": {
            "total_picks":       total_picks,
            "voided":            total_voided,
            "hits":              total_hits,
            "misses":            total_misses,
            "injury_exclusions": total_injury_exclusions,
            "hit_rate_pct":      overall_hr,
        },
        "prop_type_summary":             prop_summary,
        "high_conviction_summary":       high_conviction_summary,
        "miss_classification_totals":    dict(miss_classes),
        "confidence_calibration_totals": conf_summary,
        "recent_lessons":          recent_lessons[-10:],
        "recent_reinforcements":   recent_reinforcements[-10:],
        "recent_recommendations":  recent_recommendations[-10:],
        "skip_validation":         skip_validation,
        "human_flag_precision":    human_flag_precision,
        "clv_summary":             clv_summary,
    }

    # ── Playoff calibration early warning (P1.5) ──────────────────────
    playoff_cal, playoff_warnings = _compute_playoff_calibration(conf_summary)
    if playoff_cal is not None:
        summary["playoff_calibration"] = playoff_cal
    if playoff_warnings:
        # Append warnings to recent_recommendations so the Analyst sees them
        existing_recs = summary.get("recent_recommendations", [])
        summary["recent_recommendations"] = existing_recs + playoff_warnings

    with open(AUDIT_SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[auditor] Saved rolling audit summary ({len(audit_log)} entries) → {AUDIT_SUMMARY_JSON}")


def save_audit_report(audit_entry: dict, graded_picks: list[dict], skips: list[dict] | None = None) -> None:
    """
    Write a human-readable markdown audit report to data/audit_reports/YYYY-MM-DD.md.
    One file per day, generated at end of auditor run. Permanent archive — never overwritten
    once written (idempotent: skip if file already exists for this date).
    """
    try:
        AUDIT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        output_path = AUDIT_REPORTS_DIR / f"{YESTERDAY_STR}.md"

        if output_path.exists():
            print(f"[auditor] Audit report already exists for {YESTERDAY_STR} — skipping")
            return

        # Pull top-level stats
        total_picks    = audit_entry.get("total_picks", 0)
        hits           = audit_entry.get("hits", 0)
        misses         = audit_entry.get("misses", 0)
        hit_rate_pct   = audit_entry.get("hit_rate_pct", 0)

        md_lines: list[str] = []

        # ── Title ─────────────────────────────────────────────────────
        md_lines.append(f"# Audit Report — {YESTERDAY_STR}")
        md_lines.append("")

        # ── Summary ───────────────────────────────────────────────────
        md_lines.append("## Summary")
        md_lines.append(
            f"- Total picks: {total_picks} | Hits: {hits} | Misses: {misses}"
            f" | Hit rate: {hit_rate_pct}%"
        )
        md_lines.append("")

        # ── Prop Type Breakdown ───────────────────────────────────────
        md_lines.append("## Prop Type Breakdown")
        ptb = audit_entry.get("prop_type_breakdown", {})
        if ptb:
            md_lines.append("| Prop | Picks | Hits | Hit Rate |")
            md_lines.append("|------|-------|------|----------|")
            for prop in ["PTS", "REB", "AST", "3PM"]:
                d  = ptb.get(prop, {})
                p  = d.get("picks", 0)
                h  = d.get("hits", 0)
                hr = d.get("hit_rate_pct", 0)
                md_lines.append(f"| {prop} | {p} | {h} | {hr}% |")
        else:
            md_lines.append("_No prop breakdown available._")
        md_lines.append("")

        # ── High-Conviction Subset ────────────────────────────────────
        hcb = audit_entry.get("high_conviction_breakdown") or {}
        threshold = hcb.get("threshold_market_implied_prob", HIGH_CONVICTION_THRESHOLD)
        md_lines.append(f"## High-Conviction Subset (market_implied_prob ≥ {threshold})")
        if not hcb or hcb.get("n_picks", 0) == 0:
            md_lines.append(
                f"No high-conviction picks today (no picks with market_implied_prob ≥ {threshold})."
            )
        else:
            n_hc      = hcb.get("n_picks", 0)
            hits_hc   = hcb.get("hits", 0)
            misses_hc = hcb.get("misses", 0)
            hr_hc     = hcb.get("hit_rate_pct")
            delta_pp  = hcb.get("delta_vs_overall_pp")
            hr_str    = f"{hr_hc}%" if hr_hc is not None else "—"
            delta_str = f"{delta_pp:+.1f}pp" if delta_pp is not None else "—"
            md_lines.append("| metric | value |")
            md_lines.append("| --- | --- |")
            md_lines.append(f"| n_picks | {n_hc} |")
            md_lines.append(f"| hits | {hits_hc} |")
            md_lines.append(f"| misses | {misses_hc} |")
            md_lines.append(f"| hit_rate | {hr_str} |")
            md_lines.append(f"| delta_vs_overall | {delta_str} |")
        md_lines.append("")

        # ── Confidence Calibration ────────────────────────────────────
        ccb = audit_entry.get("confidence_calibration", {})
        if isinstance(ccb, dict) and ccb:
            md_lines.append("## Confidence Calibration")
            md_lines.append("| Band | Picks | Hits | Actual HR% | Expected HR% |")
            md_lines.append("|------|-------|------|------------|--------------|")
            for band in ["70-75", "76-80", "81-85", "86+"]:
                d           = ccb.get(band, {})
                p           = d.get("picks", 0)
                h           = d.get("hits", 0)
                actual_hr   = d.get("hit_rate_pct", 0)
                expected_hr = d.get("expected_hit_rate_pct", 0)
                md_lines.append(f"| {band}% | {p} | {h} | {actual_hr}% | {expected_hr}% |")
            md_lines.append("")

        # ── Miss Details ──────────────────────────────────────────────
        miss_details = audit_entry.get("miss_details", [])
        if miss_details:
            md_lines.append("## Miss Details")
            for miss in miss_details:
                player    = miss.get("player_name", "Unknown")
                prop_type = miss.get("prop_type", "?")
                pick_val  = miss.get("pick_value", "?")
                actual    = miss.get("actual_value", "?")
                md_lines.append(f"### {player} — {prop_type} OVER {pick_val} (actual: {actual})")
                mc = miss.get("miss_classification", "unclassified")
                md_lines.append(f"- **Classification:** {mc}")
                md_lines.append(f"- **Root cause:** {miss.get('root_cause', '')}")
                md_lines.append("")

        # ── Reinforcements ────────────────────────────────────────────
        reinforcements = audit_entry.get("reinforcements", [])
        md_lines.append("## Reinforcements")
        if reinforcements:
            for item in reinforcements:
                md_lines.append(f"- {item}")
        else:
            md_lines.append("_None._")
        md_lines.append("")

        # ── Lessons ───────────────────────────────────────────────────
        lessons = audit_entry.get("lessons", [])
        md_lines.append("## Lessons")
        if lessons:
            for item in lessons:
                md_lines.append(f"- {item}")
        else:
            md_lines.append("_None._")
        md_lines.append("")

        # ── Recommendations for Analyst ───────────────────────────────
        recommendations = audit_entry.get("recommendations", [])
        md_lines.append("## Recommendations for Analyst")
        if recommendations:
            for i, item in enumerate(recommendations, 1):
                md_lines.append(f"{i}. {item}")
        else:
            md_lines.append("_None._")
        md_lines.append("")

        # ── Skip Validation ───────────────────────────────────────────
        if skips:
            graded_skips  = [s for s in skips if s.get("skip_verdict") not in (None, "no_data")]
            false_skips   = [s for s in skips if s.get("skip_verdict") == "false_skip"]
            correct_skips = [s for s in skips if s.get("skip_verdict") == "correct_skip"]
            no_data_skips = [s for s in skips if s.get("skip_verdict") in (None, "no_data")]
            false_skip_rate = (
                round(len(false_skips) / len(graded_skips) * 100, 1)
                if graded_skips else None
            )
            md_lines.append("## Skip Validation")
            md_lines.append(
                f"- Total skips: {len(skips)} | "
                f"False skips (would have hit): {len(false_skips)} | "
                f"Correct skips: {len(correct_skips)} | "
                f"No data: {len(no_data_skips)}"
            )
            if false_skip_rate is not None:
                md_lines.append(f"- False skip rate: {false_skip_rate}%")
            if skips:
                md_lines.append("")
                md_lines.append("| Player | Prop | Tier | Skip Reason | Would Hit? | Actual |")
                md_lines.append("|--------|------|------|-------------|------------|--------|")
                for s in skips:
                    player  = s.get("player_name", "?")
                    prop    = s.get("prop_type", "?")
                    tier    = s.get("tier_considered", "?")
                    reason  = s.get("skip_reason", "?")
                    verdict = s.get("skip_verdict", "no_data")
                    actual  = s.get("actual_value")
                    actual_str = str(actual) if actual is not None else "—"
                    would_hit_str = (
                        "✓ YES" if verdict == "false_skip"
                        else ("✗ NO" if verdict == "correct_skip" else "—")
                    )
                    md_lines.append(f"| {player} | {prop} | {tier} | {reason} | {would_hit_str} | {actual_str} |")
            md_lines.append("")

        output_path.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"[auditor] Saved audit report → {output_path}")

    except Exception as e:
        print(f"[auditor] WARNING: could not save audit report: {e}")


def print_summary(graded_picks: list[dict], audit_entry: dict):
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

    print(f"\nRecommendations for Analyst:")
    for r in audit_entry.get("recommendations", []):
        print(f"  → {r}")
    print()


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[auditor] Running for {YESTERDAY_STR}")

    # ── One-time retroactive fix: Wemby 2026-04-21 injury_event picks ──
    # These were graded as MISS before the injury_event auto-void logic existed.
    # Patch them to voided=True, result=null to correct historical hit rates.
    _retro_patched = _retroactive_injury_void_patch()
    if _retro_patched:
        print(f"[auditor] Retroactive injury void patch applied: {_retro_patched} pick(s)")

    picks = load_yesterdays_picks()
    if not picks:
        sys.exit(0)

    game_log = load_game_log()
    print(f"[auditor] Loaded {len(game_log)} game log rows")

    graded_picks = grade_picks(picks, game_log)

    # Apply human verdicts from the daily picks review file (if present)
    picks_review = load_picks_review(YESTERDAY_STR)
    graded_picks = apply_human_verdicts(graded_picks, picks_review)

    hits   = sum(1 for p in graded_picks if p["result"] == "HIT")
    misses = sum(1 for p in graded_picks if p["result"] == "MISS")
    print(f"[auditor] Picks graded: {hits} hits, {misses} misses, "
          f"{len(graded_picks)-hits-misses} no data")

    if hits + misses == 0:
        print("[auditor] No gradeable picks — box scores may not be ingested yet.")
        sys.exit(0)

    season_context     = load_season_context()
    playoff_picture    = render_playoff_picture()
    post_game_news     = load_post_game_news()
    game_results       = load_game_results()
    game_results_block = build_game_results_block(game_results)
    prompt = build_audit_prompt(
        graded_picks, season_context, post_game_news,
        playoff_picture=playoff_picture,
        game_results_block=game_results_block,
    )
    audit_entry = call_auditor(prompt)

    # Promote injury_event misses to voided status before saving
    n_injury_voids = promote_injury_event_voids(graded_picks, audit_entry)
    if n_injury_voids:
        print(f"[auditor] Promoted {n_injury_voids} injury_event pick(s) to voided")

    # Compute high-conviction subset stats (deterministic, runs after voids
    # are finalized so HC totals reflect the same denominator).
    hc = compute_high_conviction_breakdown(graded_picks, audit_entry)
    if hc["n_picks"]:
        print(f"[auditor] High-conviction subset: {hc['hits']}/{hc['n_picks']} = "
              f"{hc['hit_rate_pct']}% (Δ vs overall {hc['delta_vs_overall_pp']:+.1f}pp)")
    else:
        print("[auditor] High-conviction subset: no picks today with market_implied_prob ≥ 85.0")

    save_audit(audit_entry, graded_picks)
    print_summary(graded_picks, audit_entry)


if __name__ == "__main__":
    main()
