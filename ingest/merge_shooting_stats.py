#!/usr/bin/env python3
"""
Merge backfilled shooting stats into player_game_log.csv.

Run this ONLY after data/player_game_log_shooting_backfill.csv has been
manually verified (spot-check values, confirm row counts look right, etc.).

Run from repo root:
  python ingest/merge_shooting_stats.py            # applies merge in-place
  python ingest/merge_shooting_stats.py --dry-run  # prints summary, no write
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GAME_LOG_PATH = "data/player_game_log.csv"
BACKFILL_PATH = "data/player_game_log_shooting_backfill.csv"
SHOOTING_COLS = ["fgm", "fga", "fg3m", "fg3a"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Merge data/player_game_log_shooting_backfill.csv into "
            "data/player_game_log.csv (in-place). "
            "Run only after the backfill has been manually verified."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print merge summary and sample without writing the file.",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Verify input files exist
    # ------------------------------------------------------------------
    if not os.path.exists(GAME_LOG_PATH):
        sys.exit(f"[merge] ERROR: {GAME_LOG_PATH} not found.")
    if not os.path.exists(BACKFILL_PATH):
        sys.exit(
            f"[merge] ERROR: {BACKFILL_PATH} not found. "
            f"Run ingest/backfill_shooting_stats.py first."
        )

    # ------------------------------------------------------------------
    # Load inputs as all-string DataFrames to preserve exact values
    # ------------------------------------------------------------------
    print(f"[merge] Loading {GAME_LOG_PATH}...")
    df_log = pd.read_csv(GAME_LOG_PATH, dtype=str)
    original_len = len(df_log)
    print(f"[merge] Loaded {original_len} rows from game log.")

    print(f"[merge] Loading {BACKFILL_PATH}...")
    df_bf = pd.read_csv(BACKFILL_PATH, dtype=str)
    print(f"[merge] Loaded {len(df_bf)} rows from backfill.")

    # ------------------------------------------------------------------
    # Validate backfill columns
    # ------------------------------------------------------------------
    required_bf_cols = {"game_id", "player_id"} | set(SHOOTING_COLS)
    missing = required_bf_cols - set(df_bf.columns)
    if missing:
        sys.exit(f"[merge] ERROR: backfill file is missing columns: {sorted(missing)}")

    # ------------------------------------------------------------------
    # Normalize join keys
    # game_id may be stored as float string ("401234.0") in the CSV;
    # normalize to plain integer string on both sides before joining.
    # ------------------------------------------------------------------
    def norm_game_id(s: str) -> str:
        s = str(s).strip()
        if not s:
            return ""
        try:
            return str(int(float(s)))
        except (ValueError, TypeError):
            return s

    df_log["game_id"]   = df_log["game_id"].astype(str).map(norm_game_id)
    df_log["player_id"] = df_log["player_id"].astype(str).str.strip()
    df_bf["game_id"]    = df_bf["game_id"].astype(str).map(norm_game_id)
    df_bf["player_id"]  = df_bf["player_id"].astype(str).str.strip()

    # ------------------------------------------------------------------
    # Drop shooting columns if they already exist in game log
    # (prevents _x/_y suffixes on re-run)
    # ------------------------------------------------------------------
    cols_to_drop = [c for c in SHOOTING_COLS if c in df_log.columns]
    if cols_to_drop:
        print(f"[merge] Dropping existing columns from game log: {cols_to_drop}")
        df_log = df_log.drop(columns=cols_to_drop)

    # ------------------------------------------------------------------
    # Deduplicate backfill on (game_id, player_id) — last row wins
    # Multiple rows for the same pair would inflate the join result.
    # ------------------------------------------------------------------
    bf_dupes = len(df_bf) - df_bf.drop_duplicates(
        subset=["game_id", "player_id"]
    ).shape[0]
    if bf_dupes > 0:
        print(
            f"[merge] WARNING: {bf_dupes} duplicate (game_id, player_id) pairs in "
            f"backfill — keeping last occurrence."
        )
    df_bf = df_bf.drop_duplicates(subset=["game_id", "player_id"], keep="last")

    # ------------------------------------------------------------------
    # Left join: game_log LEFT JOIN backfill ON (game_id, player_id)
    # ------------------------------------------------------------------
    df_merged = df_log.merge(
        df_bf[["game_id", "player_id"] + SHOOTING_COLS],
        on=["game_id", "player_id"],
        how="left",
    )

    # ------------------------------------------------------------------
    # Validate: left join must be length-preserving
    # ------------------------------------------------------------------
    if len(df_merged) != original_len:
        sys.exit(
            f"[merge] ABORT: Row count changed after merge! "
            f"Before={original_len}, After={len(df_merged)}. "
            f"This indicates remaining duplicate (game_id, player_id) pairs in "
            f"the backfill. Inspect and deduplicate before re-running."
        )

    # ------------------------------------------------------------------
    # Reorder columns: insert shooting cols immediately after 'tpm'
    # Resulting order: ..., tpm, fgm, fga, fg3m, fg3a, dnp, ...
    # ------------------------------------------------------------------
    if "tpm" not in df_merged.columns:
        sys.exit(
            "[merge] ERROR: 'tpm' column not found in game log — "
            "cannot determine insert position."
        )

    # Build new column order
    cols = [c for c in df_merged.columns if c not in SHOOTING_COLS]
    tpm_idx = cols.index("tpm")
    for j, col in enumerate(SHOOTING_COLS):
        cols.insert(tpm_idx + 1 + j, col)

    df_merged = df_merged[cols]

    # ------------------------------------------------------------------
    # Fill NaN shooting values with "" (rows not present in backfill)
    # ------------------------------------------------------------------
    for col in SHOOTING_COLS:
        df_merged[col] = df_merged[col].fillna("")

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------
    has_any_shooting = (
        (df_merged["fgm"]  != "") |
        (df_merged["fga"]  != "") |
        (df_merged["fg3m"] != "") |
        (df_merged["fg3a"] != "")
    )
    rows_with_stats = int(has_any_shooting.sum())
    rows_empty      = original_len - rows_with_stats

    pivot_cols = ["tpm"] + SHOOTING_COLS + (["dnp"] if "dnp" in cols else [])
    print(f"\n[merge] === MERGE SUMMARY ===")
    print(f"  Total rows:               {original_len}")
    print(f"  Rows with shooting stats: {rows_with_stats}")
    print(f"  Rows still empty:         {rows_empty}")
    print(f"  Column sequence around tpm: {pivot_cols}")

    # 5-row sample of rows that received shooting stats
    print(f"\n[merge] 5-row sample (rows with shooting stats):")
    sample_cols = (
        ["game_id", "player_id"]
        + (["player_name"] if "player_name" in df_merged.columns else [])
        + (["pts"] if "pts" in df_merged.columns else [])
        + ["tpm"] + SHOOTING_COLS
    )
    sample = df_merged.loc[has_any_shooting, sample_cols].head(5)
    if sample.empty:
        print(
            "  (no rows with shooting stats — backfill may be all empty or "
            "join keys did not match)"
        )
    else:
        print(sample.to_string(index=False))

    # ------------------------------------------------------------------
    # Write (unless --dry-run)
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f"\n[merge] --dry-run: {GAME_LOG_PATH} was NOT modified.")
        return

    df_merged.to_csv(GAME_LOG_PATH, index=False)
    print(f"\n[merge] Wrote {len(df_merged)} rows → {GAME_LOG_PATH}")
    print(f"[merge] New column order (around tpm): {pivot_cols}")


if __name__ == "__main__":
    main()
