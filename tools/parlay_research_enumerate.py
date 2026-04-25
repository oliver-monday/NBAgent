"""
Parlay Research — Card Universe Enumeration (Prompt 1 of 2).

Enumerates all L=2 through L=5 parlay card combinations from graded picks,
computes structural features per card, filters to in-bucket range
(combined_market_prob in [0.10, 0.85]), and writes a JSONL universe file
for hypothesis analysis. Buckets: Stable / Safe / Reach / Degen.

Run: python -m tools.parlay_research_enumerate

Reads:
  - data/picks.json         (graded picks; voided + null-result excluded)
  - data/nba_master.csv     (per-date team→game lookup for cross-game features)

Writes:
  - data/parlay_card_universe.jsonl    (one card per line)

A separate followup script (tools/parlay_research_analyze.py — Prompt 2) loads
this universe and produces the hypothesis-test report.

Note on data conventions: production picks.json stores `market_implied_prob`
and `confidence_pct` as percentages (0–100, e.g. 87.5), NOT decimals. We filter
on the percentage range and divide by 100 at compute time so the universe
output's `combined_market_prob` and `combined_system_conf` are in 0.0–1.0
form, matching the spec's [0.10, 0.66] bucket boundaries.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path
from typing import Optional

# ---- Bucket boundaries -------------------------------------------------------

BUCKET_DEFS = [
    ("Stable", 0.66, 0.85),  # right-open lower bound enforced in compute_card_features()
    ("Safe",   0.45, 0.66),
    ("Reach",  0.30, 0.45),
    ("Degen",  0.10, 0.30),
]
UNIVERSE_LOWER = 0.10
UNIVERSE_UPPER = 0.85

# ---- Enumeration parameters --------------------------------------------------

LEG_COUNTS = [2, 3, 4, 5]

# ---- Paths -------------------------------------------------------------------

REPO_ROOT       = Path(__file__).resolve().parent.parent
PICKS_PATH      = REPO_ROOT / "data" / "picks.json"
NBA_MASTER_PATH = REPO_ROOT / "data" / "nba_master.csv"
OUTPUT_PATH     = REPO_ROOT / "data" / "parlay_card_universe.jsonl"

# ---- Stat normalization ------------------------------------------------------

STAT_TYPES = ("PTS", "REB", "AST", "3PM")


# ---- Filter and load picks ---------------------------------------------------

def is_valid_pick(p: dict) -> bool:
    """
    Pick is included in enumeration only if all of:
      - result is exactly "HIT" or "MISS" (drops null/voided/ungraded)
      - voided is not True
      - market_implied_prob present, in (0, 100)  [stored as percentage]
      - confidence_pct present, in (0, 100)       [stored as percentage]
      - prop_type is one of the four supported types
      - player_name and team are present
    """
    if p.get("result") not in ("HIT", "MISS"):
        return False
    if p.get("voided") is True:
        return False
    mip = p.get("market_implied_prob")
    if mip is None or not (0.0 < float(mip) < 100.0):
        return False
    cp = p.get("confidence_pct")
    if cp is None or not (0.0 < float(cp) < 100.0):
        return False
    if p.get("prop_type") not in STAT_TYPES:
        return False
    if not p.get("player_name") or not p.get("team"):
        return False
    return True


def load_valid_picks_by_date() -> dict[str, list[dict]]:
    """
    Load picks.json, filter to valid picks, group by date.
    Returns {date_str: [pick_dict, ...]}.
    """
    with open(PICKS_PATH) as f:
        all_picks = json.load(f)
    by_date: dict[str, list[dict]] = defaultdict(list)
    for p in all_picks:
        if not is_valid_pick(p):
            continue
        date = p.get("date")
        if not date:
            continue
        by_date[date].append(p)
    return dict(by_date)


# ---- Per-date game lookup ----------------------------------------------------

def load_game_lookup() -> dict[str, dict[str, str]]:
    """
    Build {date: {team_abbr: game_id}} from nba_master.csv.

    game_id is a canonical string sorted([home, away]) joined with '_',
    so two teams in the same game share the same game_id regardless of
    which slot they occupy.

    Reads the CSV schema directly from disk — does not assume specific
    column names. Identifies the date column and two team columns by
    inspecting the header row. Production schema is:
      game_date / home_team_abbrev / away_team_abbrev

    Defensive: if a row is malformed, skip it. If the CSV is missing or
    unreadable, return an empty dict and let the caller handle (cards
    will simply have all legs flagged as "unknown game" via fallback).
    """
    if not NBA_MASTER_PATH.exists():
        return {}
    lookup: dict[str, dict[str, str]] = defaultdict(dict)
    try:
        with open(NBA_MASTER_PATH, newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []

            date_col = next(
                (c for c in fieldnames if "date" in c.lower()),
                None,
            )
            home_col = next(
                (
                    c for c in fieldnames
                    if ("home" in c.lower() and "team" in c.lower())
                    or c.lower() in ("home", "home_abbr", "home_team_abbr")
                ),
                None,
            )
            away_col = next(
                (
                    c for c in fieldnames
                    if ("away" in c.lower() and "team" in c.lower())
                    or c.lower() in ("away", "away_abbr", "away_team_abbr")
                ),
                None,
            )
            # Permissive fallback if the strict patterns failed
            if not home_col:
                home_col = next((c for c in fieldnames if "home" in c.lower()), None)
            if not away_col:
                away_col = next((c for c in fieldnames if "away" in c.lower()), None)
            if not (date_col and home_col and away_col):
                return {}

            for row in reader:
                try:
                    date = (row.get(date_col) or "").strip()
                    home = (row.get(home_col) or "").strip().upper()
                    away = (row.get(away_col) or "").strip().upper()
                    if not (date and home and away):
                        continue
                    pair = sorted([home, away])
                    game_id = f"{pair[0]}_{pair[1]}"
                    lookup[date][home] = game_id
                    lookup[date][away] = game_id
                except Exception:
                    continue
    except Exception:
        return {}
    return dict(lookup)


def get_game_id(date: str, team: str, game_lookup: dict) -> str:
    """
    Return the game_id for (date, team). If lookup fails, return a
    pseudo-unique fallback so that the team's pick is treated as its
    own game (avoids false same-game grouping).
    """
    team_u = team.strip().upper()
    if date in game_lookup and team_u in game_lookup[date]:
        return game_lookup[date][team_u]
    return f"UNK_{date}_{team_u}"


# ---- Per-card feature computation -------------------------------------------

def compute_card_features(legs: tuple[dict, ...], game_lookup: dict) -> Optional[dict]:
    """
    Given a tuple of pick dicts forming a card, compute all features.

    Returns None if the card's combined_market_prob is outside the universe
    range [UNIVERSE_LOWER, UNIVERSE_UPPER]. Otherwise returns a dict of
    features per the universe schema (see module docstring + spec).
    """
    n_legs = len(legs)
    date = legs[0].get("date")  # all legs share a date by construction

    # Combined probabilities (independent assumption).
    # Both fields stored as percentages (0–100); convert to decimals here.
    combined_market_prob = math.prod(
        float(p["market_implied_prob"]) / 100.0 for p in legs
    )
    combined_system_conf = math.prod(
        float(p["confidence_pct"]) / 100.0 for p in legs
    )

    # Bucket filter
    if not (UNIVERSE_LOWER <= combined_market_prob <= UNIVERSE_UPPER):
        return None

    bucket: Optional[str] = None
    # Stable is right-exclusive on the lower bound — a card at exactly 0.66 lands in Safe
    if 0.66 < combined_market_prob <= 0.85:
        bucket = "Stable"
    elif 0.45 <= combined_market_prob <= 0.66:
        bucket = "Safe"
    elif 0.30 <= combined_market_prob < 0.45:
        bucket = "Reach"
    elif 0.10 <= combined_market_prob < 0.30:
        bucket = "Degen"
    if bucket is None:
        return None  # safety; should be unreachable given the range check above

    # Hit determination (all legs HIT = card HIT, otherwise MISS)
    hit = all(p["result"] == "HIT" for p in legs)

    # Hypothesis 1: prop mix
    prop_counts = Counter(p["prop_type"] for p in legs)
    prop_counts_dict = {s: prop_counts.get(s, 0) for s in STAT_TYPES}
    all_same_prop = len(prop_counts) == 1
    most_common = prop_counts.most_common()
    if (
        len(most_common) == 1
        or (len(most_common) > 1 and most_common[0][1] > most_common[1][1])
    ):
        prop_dominant = most_common[0][0]
    else:
        prop_dominant = "mixed"

    # Hypothesis 2: cross-game vs same-game
    game_ids = [get_game_id(date, p["team"], game_lookup) for p in legs]
    game_counts = Counter(game_ids)
    n_unique_games = len(game_counts)
    all_cross_game = n_unique_games == n_legs
    max_legs_per_game = max(game_counts.values())

    # Hypothesis 3: iron_floor concentration
    n_iron_floor = sum(1 for p in legs if p.get("iron_floor") is True)
    all_iron_floor = n_iron_floor == n_legs

    # Hypothesis 4: confidence dispersion (already-decimalized leg confidences)
    confidences = [float(p["confidence_pct"]) / 100.0 for p in legs]
    min_leg_conf = min(confidences)
    max_leg_conf = max(confidences)
    confidence_dispersion = round(max_leg_conf - min_leg_conf, 4)

    # Hypothesis 5: same-team concentration
    teams = [p["team"].strip().upper() for p in legs]
    team_counts = Counter(teams)
    n_unique_teams = len(team_counts)
    max_legs_per_team = max(team_counts.values())

    # Hypothesis 6: implicit in conf_minus_market — computed in the return dict.

    # Hypothesis 7: per-player concentration
    players = [p["player_name"] for p in legs]
    player_counts = Counter(players)
    n_unique_players = len(player_counts)
    max_legs_per_player = max(player_counts.values())

    return {
        "date": date,
        "n_legs": n_legs,
        "leg_player_props": [
            f"{p['player_name']}|{p['prop_type']}|{p['pick_value']}"
            for p in legs
        ],
        "combined_market_prob": round(combined_market_prob, 6),
        "combined_system_conf": round(combined_system_conf, 6),
        "conf_minus_market":   round(combined_system_conf - combined_market_prob, 6),
        "bucket": bucket,
        "hit":    hit,
        # Hypothesis features
        "prop_counts":           prop_counts_dict,
        "prop_dominant":         prop_dominant,
        "all_same_prop":         all_same_prop,
        "n_unique_games":        n_unique_games,
        "all_cross_game":        all_cross_game,
        "max_legs_per_game":     max_legs_per_game,
        "n_iron_floor":          n_iron_floor,
        "all_iron_floor":        all_iron_floor,
        "min_leg_conf":          round(min_leg_conf, 4),
        "max_leg_conf":          round(max_leg_conf, 4),
        "confidence_dispersion": confidence_dispersion,
        "n_unique_teams":        n_unique_teams,
        "max_legs_per_team":     max_legs_per_team,
        "n_unique_players":      n_unique_players,
        "max_legs_per_player":   max_legs_per_player,
    }


# ---- Main enumeration loop ---------------------------------------------------

def enumerate_universe() -> dict:
    """
    Enumerate all L=2..5 cards across all dates, compute features, filter
    to in-bucket range, write JSONL.

    Returns summary stats dict for stdout reporting.
    """
    print("Loading picks...")
    picks_by_date = load_valid_picks_by_date()
    n_dates       = len(picks_by_date)
    n_picks_total = sum(len(p) for p in picks_by_date.values())
    print(f"  Loaded {n_picks_total} valid picks across {n_dates} dates.")

    print("Loading game lookup from nba_master.csv...")
    game_lookup = load_game_lookup()
    n_games = sum(len(v) // 2 for v in game_lookup.values())
    print(f"  Loaded {n_games} games across {len(game_lookup)} dates.")

    print(f"Enumerating L={LEG_COUNTS} cards per date...")
    bucket_counts: Counter = Counter()
    bucket_hits:   Counter = Counter()
    n_total_cards_enumerated = 0
    n_total_cards_retained   = 0

    sorted_dates = sorted(picks_by_date.keys())
    with open(OUTPUT_PATH, "w") as out:
        for di, date in enumerate(sorted_dates):
            picks = picks_by_date[date]
            if len(picks) < 2:
                continue
            for L in LEG_COUNTS:
                if L > len(picks):
                    continue
                for combo in combinations(picks, L):
                    n_total_cards_enumerated += 1
                    features = compute_card_features(combo, game_lookup)
                    if features is None:
                        continue
                    n_total_cards_retained += 1
                    bucket_counts[features["bucket"]] += 1
                    if features["hit"]:
                        bucket_hits[features["bucket"]] += 1
                    out.write(json.dumps(features) + "\n")

            # Progress every 5 dates
            if (di + 1) % 5 == 0:
                print(
                    f"  Processed through {date}: "
                    f"{n_total_cards_retained:,} retained / "
                    f"{n_total_cards_enumerated:,} enumerated."
                )

    summary = {
        "n_dates":                  n_dates,
        "n_picks_total":            n_picks_total,
        "n_games":                  n_games,
        "n_dates_with_games":       len(game_lookup),
        "n_total_cards_enumerated": n_total_cards_enumerated,
        "n_total_cards_retained":   n_total_cards_retained,
        "bucket_counts":            dict(bucket_counts),
        "bucket_hit_rates": {
            b: round(bucket_hits[b] / bucket_counts[b], 4) if bucket_counts[b] else None
            for b in ("Stable", "Safe", "Reach", "Degen")
        },
    }
    return summary


def main():
    summary = enumerate_universe()
    print()
    print("=" * 60)
    print("ENUMERATION COMPLETE")
    print("=" * 60)
    print(f"Output: {OUTPUT_PATH}")
    print(f"Dates processed: {summary['n_dates']}")
    print(f"Valid picks: {summary['n_picks_total']:,}")
    print(f"Cards enumerated: {summary['n_total_cards_enumerated']:,}")
    print(f"Cards retained (in-bucket): {summary['n_total_cards_retained']:,}")
    print()
    print("Per-bucket breakdown:")
    for bucket in ("Stable", "Safe", "Reach", "Degen"):
        n  = summary["bucket_counts"].get(bucket, 0)
        hr = summary["bucket_hit_rates"].get(bucket)
        hr_str = f"{hr:.1%}" if hr is not None else "n/a"
        print(f"  {bucket:>6}: {n:>10,} cards | actual hit rate {hr_str}")

    if summary["n_games"] == 0:
        print()
        print(
            "[WARN] nba_master.csv lookup yielded zero games — "
            "all n_unique_games will equal n_legs (UNK fallback)."
        )


if __name__ == "__main__":
    main()
