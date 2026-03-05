#!/usr/bin/env python3
"""
NBAgent — Spread Backfill

One-time script to backfill historical spread data in nba_master.csv using
Pinnacle closing lines from an external odds CSV (nba_main_lines.csv).

What it does:
  1. Loads the odds CSV, takes the last timestamp per game (closing line)
  2. Normalizes one team name mismatch: "Los Angeles Clippers" → "LA Clippers"
  3. Joins to nba_master.csv on (home_team_name, away_team_name, game_date)
     with ±1 day tolerance for closing timestamps near midnight
  4. Fills home_spread / away_spread only for rows that are currently null
     (non-destructive — does not overwrite existing ESPN-sourced spreads)
  5. Writes updated nba_master.csv

Usage:
    # From repo root:
    python ingest/backfill_spreads.py \\
        --odds "/path/to/nba_main_lines.csv" \\
        --master data/nba_master.csv

    # Preview without writing:
    python ingest/backfill_spreads.py \\
        --odds "/path/to/nba_main_lines.csv" \\
        --master data/nba_master.csv \\
        --dry-run
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import pandas as pd


# ── Team name normalization ────────────────────────────────────────────
# Pinnacle uses "Los Angeles Clippers"; nba_master uses "LA Clippers".
# All other 29 team names are exact matches.
ODDS_TO_MASTER = {
    "Los Angeles Clippers": "LA Clippers",
}


def normalize(name: str) -> str:
    return ODDS_TO_MASTER.get(str(name).strip(), str(name).strip())


# ── Step 1: Load closing lines ─────────────────────────────────────────

def load_closing_lines(odds_path: str) -> pd.DataFrame:
    """
    Load the Pinnacle odds CSV and return one closing line per game.

    Closing line = the last scraped row by timestamp per game_link.
    This is the final pre-game spread — the most relevant for historical analysis.
    """
    print(f"[backfill] Loading odds CSV: {odds_path}")
    raw = pd.read_csv(odds_path)
    print(f"[backfill] Loaded {len(raw):,} rows  |  {raw['game_link'].nunique()} unique games")

    raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")

    # Last row per game_link = closing line
    closing = (
        raw.sort_values("timestamp")
        .groupby("game_link", sort=False)
        .last()
        .reset_index()
    )
    print(f"[backfill] Closing lines: {len(closing)} games")

    # Normalize team names
    closing["team1"] = closing["team1"].apply(normalize)
    closing["team2"] = closing["team2"].apply(normalize)

    # Extract closing date as YYYY-MM-DD string
    closing["closing_date"] = closing["timestamp"].dt.strftime("%Y-%m-%d")

    return closing


# ── Step 2: Build spread lookup ────────────────────────────────────────

def build_spread_map(closing: pd.DataFrame) -> dict:
    """
    Build a lookup: {(home_team_name, away_team_name, game_date_str): (home_spread, away_spread)}

    Since the odds CSV doesn't mark which team is home, we store BOTH orderings
    for each game. nba_master.csv knows which is home, so the correct key will hit.

    Tolerance window:
      - 1 day backward: handles post-midnight timestamps landing on the next calendar day
      - 3 days forward: handles Pinnacle scraper stopping collection 1-3 days before game day
        (observed for some Jan/Feb games where the scraper's last update was 2-3 days prior)
      - Only forward extension is used: closing lines after a game date by >1 day are
        NOT extended, since those are a different scheduled game instance (same matchup
        played later in the season).
    """
    spread_map: dict = {}

    for _, row in closing.iterrows():
        t1   = row["team1"]
        t2   = row["team2"]
        t1s  = float(row["team1_spread"])
        t2s  = float(row["team2_spread"])
        base = dt.date.fromisoformat(row["closing_date"])

        # Generate candidate dates:
        #   base-1 : backward 1 day (post-midnight timestamp correction)
        #   base+0 : the closing date itself
        #   base+1 : 1 day forward (typical late-night timestamp)
        #   base+2 : 2 days forward (Pinnacle stopped updating 2 days before game)
        #   base+3 : 3 days forward (Pinnacle stopped updating 3 days before game)
        dates = [
            (base + dt.timedelta(days=d)).strftime("%Y-%m-%d")
            for d in (-1, 0, 1, 2, 3)
        ]

        for d in dates:
            # Ordering A: team1 is home
            spread_map[(t1, t2, d)] = (t1s, t2s)
            # Ordering B: team2 is home
            spread_map[(t2, t1, d)] = (t2s, t1s)

    print(f"[backfill] Spread map: {len(spread_map):,} lookup entries "
          f"({len(closing)} games × 2 orderings × 5 dates)")
    return spread_map


# ── Step 3: Backfill master CSV ────────────────────────────────────────

def _is_null(val) -> bool:
    """Return True if a spread value is missing / blank."""
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    return str(val).strip() in ("", "nan", "NaN", "None")


def backfill(master_path: str, spread_map: dict, dry_run: bool = False) -> None:
    """
    For each row in nba_master.csv where home_spread is null, look up
    the spread from spread_map and fill in home_spread + away_spread.
    Only writes if --dry-run is not set.
    """
    print(f"\n[backfill] Loading master CSV: {master_path}")
    master = pd.read_csv(master_path, dtype=str)

    # Normalize game_date to YYYY-MM-DD
    master["game_date"] = (
        pd.to_datetime(master["game_date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
    )

    total        = len(master)
    null_before  = master["home_spread"].apply(_is_null).sum()
    print(f"[backfill] Master: {total} rows  |  {null_before} with null home_spread  "
          f"|  {total - null_before} already filled")

    filled               = 0
    skipped_filled       = 0
    skipped_no_match     = 0
    sample_filled: list  = []
    sample_unmatched: list = []

    for idx, row in master.iterrows():
        if not _is_null(row.get("home_spread")):
            skipped_filled += 1
            continue

        home_name = str(row.get("home_team_name") or "").strip()
        away_name = str(row.get("away_team_name") or "").strip()
        game_date = str(row.get("game_date") or "").strip()

        if not home_name or not away_name or not game_date:
            skipped_no_match += 1
            continue

        result = spread_map.get((home_name, away_name, game_date))

        if result is None:
            skipped_no_match += 1
            if len(sample_unmatched) < 5:
                sample_unmatched.append(f"  {game_date}  {home_name} vs {away_name}")
            continue

        home_spread, away_spread = result
        master.at[idx, "home_spread"] = home_spread
        master.at[idx, "away_spread"] = away_spread
        filled += 1

        if len(sample_filled) < 8:
            sample_filled.append(
                f"  {game_date}  {home_name} vs {away_name}  "
                f"home={home_spread:+.1f}  away={away_spread:+.1f}"
            )

    null_after = master["home_spread"].apply(_is_null).sum()

    # ── Summary ──────────────────────────────────────────────────────
    print(f"\n{'[DRY RUN] ' if dry_run else ''}[backfill] Results:")
    print(f"  Rows filled now:      {filled}")
    print(f"  Already had spreads:  {skipped_filled}")
    print(f"  No match found:       {skipped_no_match}  "
          f"(All-Star / missing odds coverage)")
    print(f"  Null home_spread:     {null_before} → {null_after}")
    pct = (total - null_after) / total * 100
    print(f"  Overall coverage:     {total - null_after} / {total} ({pct:.1f}%)")

    if sample_filled:
        print(f"\n  Sample matched games (first {len(sample_filled)}):")
        for s in sample_filled:
            print(s)

    if sample_unmatched:
        print(f"\n  Sample unmatched games (first {len(sample_unmatched)}):")
        for s in sample_unmatched:
            print(s)

    if dry_run:
        print("\n[backfill] DRY RUN complete — master CSV not modified.")
        return

    master.to_csv(master_path, index=False)
    print(f"\n[backfill] Written → {master_path}")


# ── Entry point ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Backfill spreads in nba_master.csv from Pinnacle closing lines."
    )
    parser.add_argument(
        "--odds",
        required=True,
        help="Path to the Pinnacle odds CSV (nba_main_lines.csv)",
    )
    parser.add_argument(
        "--master",
        default="data/nba_master.csv",
        help="Path to nba_master.csv (default: data/nba_master.csv)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to disk",
    )
    args = parser.parse_args()

    if not Path(args.odds).exists():
        print(f"[backfill] ERROR: odds file not found: {args.odds}")
        sys.exit(1)

    if not Path(args.master).exists():
        print(f"[backfill] ERROR: master file not found: {args.master}")
        sys.exit(1)

    closing    = load_closing_lines(args.odds)
    spread_map = build_spread_map(closing)
    backfill(args.master, spread_map, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
