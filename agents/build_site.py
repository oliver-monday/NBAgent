#!/usr/bin/env python3
"""
NBAgent — Site Builder v2

Reads data/picks.json, data/audit_log.json, and data/nba_master.csv,
writes site/index.html for GitHub Pages deployment.

Features:
  - Game time on each pick card
  - Hit rate trend chart (daily, last 30 days)
  - Per-prop-type streak indicator
"""

from __future__ import annotations

import json
import datetime as dt
from collections import defaultdict
import re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"

PT = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(PT).strftime("%Y-%m-%d")
PLAYOFFS_R1_DATE = "2026-04-18"

PICKS_JSON              = DATA / "picks.json"
PARLAYS_JSON            = DATA / "parlays.json"
AUDIT_LOG_JSON          = DATA / "audit_log.json"
AUDIT_SUMMARY_JSON      = DATA / "audit_summary.json"
MASTER_CSV              = DATA / "nba_master.csv"
INJURIES_JSON           = DATA / "injuries_today.json"
OPPORTUNITY_FLAGS_JSON  = DATA / "opportunity_flags.json"
PICKS_REVIEW_JSON       = DATA / f"picks_review_{TODAY_STR}.json"
ODDS_AVAILABLE_JSON     = DATA / "odds_available.json"
PLAYER_STATS_JSON       = DATA / "player_stats.json"
WHITELIST_CSV           = ROOT / "playerprops" / "player_whitelist.csv"

# Team abbreviation normalization — nba_master.csv sometimes uses legacy short forms
_ABBR_NORM = {
    "GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP",
    "UTAH": "UTA", "WSH": "WAS", "UTH": "UTA",
}

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def load_game_times() -> dict:
    """
    Returns {team_abbrev: "7:30 PM PT"} for today's games from nba_master.csv.
    """
    if not MASTER_CSV.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_csv(MASTER_CSV, dtype=str)
        df["game_date"] = df["game_date"].astype(str).str[:10]
        today = df[df["game_date"] == TODAY_STR].copy()
        times = {}
        for _, row in today.iterrows():
            raw = row.get("game_time_utc", "")
            if not raw or str(raw).strip() in ("", "nan"):
                label = "TBD"
            else:
                try:
                    utc = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                    if utc.tzinfo is None:
                        utc = utc.replace(tzinfo=dt.timezone.utc)
                    pt = utc.astimezone(PT)
                    label = pt.strftime("%-I:%M %p PT")
                except Exception:
                    label = "TBD"
            for abbrev in [row.get("home_team_abbrev", ""), row.get("away_team_abbrev", "")]:
                if abbrev and str(abbrev) != "nan":
                    times[str(abbrev).upper()] = label
        return times
    except Exception:
        return {}


def load_game_ml_odds() -> dict:
    """
    Returns {canonical_team_abbrev: implied_win_pct_int} for today's games.
    Converts American ML to implied probability (raw, not vig-removed).
    """
    if not MASTER_CSV.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_csv(MASTER_CSV, dtype=str)
        df["game_date"] = df["game_date"].astype(str).str[:10]
        today = df[df["game_date"] == TODAY_STR]
        odds: dict = {}
        for _, row in today.iterrows():
            for abbrev_col, ml_col in [("home_team_abbrev", "home_ml"),
                                        ("away_team_abbrev", "away_ml")]:
                raw_abbrev = str(row.get(abbrev_col, "") or "").strip()
                ml_raw     = str(row.get(ml_col, "") or "").strip()
                if not raw_abbrev or raw_abbrev.lower() == "nan":
                    continue
                if not ml_raw or ml_raw.lower() == "nan":
                    continue
                try:
                    raw       = raw_abbrev.upper()
                    canonical = _ABBR_NORM.get(raw, raw)
                    ml = float(ml_raw)
                    prob = (-ml) / (-ml + 100) * 100 if ml < 0 else 100 / (ml + 100) * 100
                    val = round(prob)
                    odds[raw]       = val  # keep raw key (e.g. GS, SA)
                    odds[canonical] = val  # also canonical key (e.g. GSW, SAS)
                except Exception:
                    pass
        return odds
    except Exception:
        return {}


def compute_streak(picks: list, prop_type: str) -> dict:
    """
    Compute current consecutive hit/miss streak and last-10 record
    for a given prop type.
    """
    graded = [p for p in picks
              if p.get("prop_type") == prop_type
              and p.get("result") in ("HIT", "MISS")]
    graded = sorted(graded, key=lambda p: p.get("date", ""), reverse=True)

    streak_count = 0
    streak_type = None
    for p in graded:
        if streak_type is None:
            streak_type = p["result"]
            streak_count = 1
        elif p["result"] == streak_type:
            streak_count += 1
        else:
            break

    last10 = graded[:10]
    l10_hits = sum(1 for p in last10 if p["result"] == "HIT")
    l10_total = len(last10)

    return {
        "streak_type": streak_type,
        "streak_count": streak_count,
        "last10_hits": l10_hits,
        "last10_total": l10_total,
        "last10_pct": round(100 * l10_hits / l10_total, 0) if l10_total else 0,
    }


def compute_daily_trend(picks: list) -> list:
    """
    Returns [{date, hits, total, pct}] sorted ascending for the trend chart.
    """
    by_date = defaultdict(lambda: {"hits": 0, "total": 0})
    for p in picks:
        if p.get("result") not in ("HIT", "MISS"):
            continue
        d = p.get("date", "")
        by_date[d]["total"] += 1
        if p["result"] == "HIT":
            by_date[d]["hits"] += 1

    trend = []
    for date in sorted(by_date.keys()):
        h = by_date[date]["hits"]
        t = by_date[date]["total"]
        trend.append({"date": date, "hits": h, "total": t,
                      "pct": round(100 * h / t, 1) if t else 0})
    return trend[-30:]


def build_rotation_lookup(top_n: int = 9, window: int = 15) -> dict[str, set[str]]:
    """
    Returns {team_abbrev_upper: {last_name_lower, ...}} for the top N players
    by average minutes per game over the last `window` games in player_game_log.csv.
    Used to filter non-whitelisted injury entries to key rotation players only.
    Falls back to empty dict on any error — never blocks site build.
    """
    try:
        game_log_csv = DATA / "player_game_log.csv"
        if not game_log_csv.exists():
            return {}
        import pandas as pd
        df = pd.read_csv(game_log_csv, dtype={"game_id": str, "player_id": str})

        # Filter out DNP rows
        if "dnp" in df.columns:
            df = df[df["dnp"].astype(str).str.strip() != "1"]

        # Filter out rows where minutes is null or zero
        df["minutes_num"] = pd.to_numeric(df["minutes"], errors="coerce")
        df = df[df["minutes_num"].fillna(0) > 0]

        if df.empty:
            return {}

        # Convert game_date to datetime, sort descending
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
        df = df.dropna(subset=["game_date"])
        df = df.sort_values("game_date", ascending=False)

        # Keep last `window` played games per player-team pair
        df = df.groupby(["player_name", "team_abbrev"], group_keys=False).head(window)

        # Mean minutes per player-team pair
        avg_min = (
            df.groupby(["team_abbrev", "player_name"])["minutes_num"]
            .mean()
            .reset_index()
            .rename(columns={"minutes_num": "avg_min"})
        )

        def _extract_last(raw_name: str) -> str:
            n = str(raw_name).strip()
            if len(n) >= 3 and n[1] == "." and n[2] == " ":
                return n[3:]
            parts = n.split(" ", 1)
            return parts[1] if len(parts) > 1 else n

        result: dict[str, set[str]] = {}
        for team_abbrev, group in avg_min.groupby("team_abbrev"):
            top = group.nlargest(top_n, "avg_min")
            team_key = _ABBR_NORM.get(str(team_abbrev).upper(), str(team_abbrev).upper())
            result[team_key] = {_extract_last(name).lower() for name in top["player_name"]}

        return result
    except Exception:
        return {}


def load_injuries_display() -> dict:
    """
    Build injury display data grouped by today's games from nba_master.csv.
    Only whitelisted active players are shown. No 'Other Teams' bucket.

    Returns:
      {
        "fetched_at": "3:05 PM PT, Mar 5",
        "games": [
          {
            "away": "LAL", "home": "GSW", "game_time": "7:30 PM PT",
            "teams": {
              "LAL": [{"player_name": "...", "status": "OUT", "reason": "..."}, ...],
              "GSW": [...]
            }
          }, ...
        ]
      }
    """
    raw = load_json(INJURIES_JSON, {})
    if not raw:
        return {"fetched_at": None, "games": []}

    # ── Format timestamp ────────────────────────────────────────────────
    fetched_at = None
    for key in ("fetched_at", "built_at_utc", "as_of", "timestamp", "updated_at", "scraped_at"):
        if key in raw and isinstance(raw[key], str):
            fetched_at = raw[key]
            break
    if fetched_at:
        try:
            ts = dt.datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            fetched_at = ts.astimezone(PT).strftime("%-I:%M %p PT, %b %-d")
        except Exception:
            pass

    # ── Raw injury data: team_abbrev → player list ──────────────────────
    inj_teams = {k: v for k, v in raw.items() if isinstance(v, list)}

    # ── Whitelist: (canonical_team, last_name) pairs + abbrev alt map ───
    # Rotowire uses abbreviated names ("C. Flagg", "M. Buzelis") so we
    # match on last name scoped to the canonical team abbreviation.
    whitelist_team_last = set()   # {(canonical_abbr, last_name_lower)}
    abbr_alt_map        = {}      # alt_abbr.upper() → canonical_abbr.upper()
    if WHITELIST_CSV.exists():
        try:
            import pandas as pd
            wl = pd.read_csv(WHITELIST_CSV, dtype=str)
            wl["active"] = wl["active"].fillna("1")
            active = wl[wl["active"].str.strip() == "1"]
            for _, row in active.iterrows():
                canonical = str(row["team_abbr"]).strip().upper()
                alt = str(row.get("team_abbr_alt", "") or "").strip().upper()
                if alt:
                    abbr_alt_map[alt] = canonical
                full_name = str(row["player_name"]).strip()
                last = full_name.rsplit(" ", 1)[-1].lower()
                whitelist_team_last.add((canonical, last))
        except Exception:
            pass

    rotation_lookup = build_rotation_lookup()

    def normalize(abbr: str) -> str:
        a = str(abbr).strip().upper()
        return abbr_alt_map.get(a) or _ABBR_NORM.get(a, a)

    def extract_last(raw_name: str) -> str:
        """Extract last name from Rotowire format ('C. Flagg' or 'Seth Curry')."""
        n = str(raw_name).strip()
        # "F. LastName" abbreviated format
        if len(n) >= 3 and n[1] == "." and n[2] == " ":
            return n[3:]
        # Full name — everything after first space
        parts = n.split(" ", 1)
        return parts[1] if len(parts) > 1 else n

    def filtered_injuries(team_abbr: str) -> list:
        """Return injuries: all whitelisted players + top-rotation non-whitelisted (OUT/DOUBTFUL only)."""
        norm = normalize(team_abbr)
        players = inj_teams.get(norm) or inj_teams.get(team_abbr) or []
        rotation_set = rotation_lookup.get(norm, set())
        result = []
        for p in players:
            raw_name = p.get("player_name") or p.get("name") or ""
            last = extract_last(raw_name).lower()
            status = (p.get("status") or p.get("designation") or "").upper().strip()
            is_whitelisted = (norm, last) in whitelist_team_last
            in_rotation = last in rotation_set
            if is_whitelisted:
                p["is_whitelisted"] = True
                result.append(p)
            elif in_rotation and status in ("OUT", "DOUBTFUL"):
                p["is_whitelisted"] = False
                result.append(p)
        return result

    # ── Today's games from nba_master.csv ───────────────────────────────
    games = []
    if not MASTER_CSV.exists():
        return {"fetched_at": fetched_at, "games": games}
    try:
        import pandas as pd
        df = pd.read_csv(MASTER_CSV, dtype=str)
        df["game_date"] = df["game_date"].astype(str).str[:10]
        today_rows = df[df["game_date"] == TODAY_STR]
        for _, row in today_rows.iterrows():
            away = normalize(str(row.get("away_team_abbrev", "") or "").strip())
            home = normalize(str(row.get("home_team_abbrev", "") or "").strip())
            if not away or not home or away == "NAN" or home == "NAN":
                continue

            raw_time = str(row.get("game_time_utc", "") or "").strip()
            if not raw_time or raw_time == "nan":
                time_label = "TBD"
            else:
                try:
                    utc = dt.datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                    if utc.tzinfo is None:
                        utc = utc.replace(tzinfo=dt.timezone.utc)
                    time_label = utc.astimezone(PT).strftime("%-I:%M %p PT")
                except Exception:
                    time_label = "TBD"

            away_inj = filtered_injuries(away)
            home_inj = filtered_injuries(home)
            if not away_inj and not home_inj:
                continue  # no whitelisted injuries in this game — skip entirely

            team_blocks = {}
            if away_inj:
                team_blocks[away] = away_inj
            if home_inj:
                team_blocks[home] = home_inj
            games.append({"away": away, "home": home,
                          "game_time": time_label, "teams": team_blocks})
    except Exception:
        pass

    return {"fetched_at": fetched_at, "games": games}


def load_todays_parlays() -> dict:
    """
    Load today's parlay bundle and compute historical parlay stats.
    Returns {
      "today": [...],          # today's parlays (ungraded)
      "hits": N, "misses": N, "total": N, "hit_rate_pct": X
    }
    """
    raw = load_json(PARLAYS_JSON, [])
    if not isinstance(raw, list):
        return {"today": [], "hits": 0, "misses": 0, "total": 0, "hit_rate_pct": 0}

    today_parlays = []
    hits = misses = 0
    past_parlays: list = []

    for bundle in raw:
        parlays = bundle.get("parlays", [])
        bundle_date = bundle.get("date", "")
        if bundle_date == TODAY_STR:
            today_parlays = parlays
        else:
            for p in parlays:
                r = p.get("result")
                if r == "HIT":
                    hits += 1
                elif r == "MISS":
                    misses += 1
                if r in ("HIT", "MISS", "PARTIAL"):
                    past_parlays.append({
                        "date": bundle_date,
                        "label": p.get("label"),
                        "result": r,
                        "implied_odds": p.get("implied_odds"),
                        "legs": p.get("legs", []),
                        "leg_results": p.get("leg_results", []),
                    })

    total = hits + misses
    hit_rate = round(100 * hits / total, 1) if total else 0
    past_parlays_sorted = sorted(past_parlays, key=lambda x: x.get("date", ""), reverse=True)

    return {
        "today": today_parlays,
        "hits": hits,
        "misses": misses,
        "total": total,
        "hit_rate_pct": hit_rate,
        "history": past_parlays_sorted[:60],
    }


def load_yesterday_summary() -> dict:
    """
    Reads audit_summary.json for season-level stats used on the Results tab.
    Returns {} gracefully if file is missing or malformed.
    """
    try:
        summary = load_json(AUDIT_SUMMARY_JSON, {})
        if not isinstance(summary, dict):
            return {}
        return summary
    except Exception:
        return {}


def load_opportunity_flags() -> list:
    """
    Reads opportunity_flags.json and returns today's suggestions only.
    Returns [] gracefully if file is missing or malformed.
    """
    try:
        flags = load_json(OPPORTUNITY_FLAGS_JSON, [])
        if not isinstance(flags, list):
            return []
        return [f for f in flags if f.get("date") == TODAY_STR]
    except Exception:
        return []


def build_explorer_data() -> dict:
    """
    Builds the player explorer dataset for the Research tab.
    Returns a dict keyed by player_name (active whitelisted players only),
    each containing a list of game records with context fields.
    Returns {} on any error — never blocks site build.
    """
    try:
        import pandas as pd

        game_log_csv = DATA / "player_game_log.csv"
        if not game_log_csv.exists() or not MASTER_CSV.exists():
            return {}

        # Load active whitelisted players
        if not WHITELIST_CSV.exists():
            return {}
        wl = pd.read_csv(WHITELIST_CSV, dtype=str)
        wl = wl[wl["active"].astype(str).str.strip() == "1"]
        active_players = set(wl["player_name"].str.strip().str.lower())

        # Load game log — exclude DNPs
        gl = pd.read_csv(game_log_csv, dtype=str)
        if "dnp" in gl.columns:
            gl = gl[gl["dnp"].astype(str).str.strip() != "1"]
        gl["game_date"] = pd.to_datetime(gl["game_date"], errors="coerce")
        gl = gl.dropna(subset=["game_date"])

        # Filter to active whitelisted players only
        gl = gl[gl["player_name"].str.strip().str.lower().isin(active_players)]
        if gl.empty:
            return {}

        # Load master for spread + game result context
        master = pd.read_csv(MASTER_CSV, dtype=str)
        master["game_date"] = pd.to_datetime(master["game_date"], errors="coerce")
        master = master.dropna(subset=["game_date"])

        # Normalize game_id join key — same pattern as quant.py
        gl["_gid"]     = gl["game_id"].astype(str).str.split(".").str[0].str.strip()
        master["_gid"] = master["game_id"].astype(str).str.split(".").str[0].str.strip()

        # Columns needed from master
        master_cols = ["_gid", "home_team_abbrev", "away_team_abbrev",
                       "home_spread", "away_spread", "home_score", "away_score"]
        master_cols = [c for c in master_cols if c in master.columns]

        # Deduplicate master on _gid before merging (safety)
        master_slim = master[master_cols].drop_duplicates(subset=["_gid"])

        # Left join — keep all game log rows; unmatched get NaN context
        merged = gl.merge(master_slim, on="_gid", how="left")

        # Diagnostic: report match rate during build
        spread_col = "home_spread" if "home_spread" in merged.columns else None
        matched = int(merged[spread_col].notna().sum()) if spread_col else 0
        total   = len(merged)
        pct     = (100 * matched // total) if total else 0
        print(f"[build_explorer_data] spread join: {matched}/{total} rows matched ({pct}%)")

        # Build per-player game records
        def safe_int(val):
            try:
                return int(float(str(val).strip()))
            except (ValueError, TypeError):
                return None

        def safe_float(val):
            try:
                if val is None:
                    return None
                s = str(val).strip()
                if s.lower() in ("nan", "none", ""):
                    return None
                return float(s)
            except (ValueError, TypeError):
                return None

        merged_sorted = merged.sort_values(["player_name", "game_date"], ascending=[True, True])

        result: dict = {}
        for player_name, grp in merged_sorted.groupby("player_name"):
            grp = grp.sort_values("game_date", ascending=True).reset_index(drop=True)
            records = []
            prev_date = None
            for _, row in grp.iterrows():
                gd_str = row["game_date"].strftime("%Y-%m-%d")
                team = str(row.get("team_abbrev", "") or "").strip().upper()
                team = _ABBR_NORM.get(team, team)

                # Rest days → bucket
                if prev_date is not None:
                    rest = (row["game_date"] - prev_date).days - 1
                    rest_bucket = 0 if rest == 0 else (1 if rest == 1 else (2 if rest == 2 else 3))
                else:
                    rest_bucket = None
                prev_date = row["game_date"]

                # Stats — game_log already has correct column names
                pts  = safe_int(row.get("pts"))
                reb  = safe_int(row.get("reb"))
                ast  = safe_int(row.get("ast"))
                tpm  = safe_int(row.get("tpm"))
                mins = safe_int(row.get("minutes"))

                # H/A and opponent — from game log
                ha  = str(row.get("home_away", "") or "").strip().upper()
                opp = str(row.get("opp_abbrev", "") or "").strip().upper()
                opp = _ABBR_NORM.get(opp, opp)

                # Determine home/away from master columns to derive signed spread
                home_abbrev = str(row.get("home_team_abbrev", "") or "").strip().upper()
                away_abbrev = str(row.get("away_team_abbrev", "") or "").strip().upper()
                home_norm = _ABBR_NORM.get(home_abbrev, home_abbrev)
                away_norm = _ABBR_NORM.get(away_abbrev, away_abbrev)
                is_home = (team == home_norm)
                is_away = (team == away_norm)

                # Signed spread from player's perspective
                # home_spread is negative when home team is the favorite
                home_spread_val = safe_float(row.get("home_spread"))
                away_spread_val = safe_float(row.get("away_spread"))

                if is_home and home_spread_val is not None:
                    player_spread = round(home_spread_val, 1)
                elif is_away and away_spread_val is not None:
                    player_spread = round(away_spread_val, 1)
                elif is_home and away_spread_val is not None:
                    player_spread = round(-away_spread_val, 1)
                elif is_away and home_spread_val is not None:
                    player_spread = round(-home_spread_val, 1)
                else:
                    player_spread = None

                spread_abs = round(abs(player_spread), 1) if player_spread is not None else None

                # Game result and margin
                home_score = safe_float(row.get("home_score"))
                away_score = safe_float(row.get("away_score"))
                if home_score is not None and away_score is not None:
                    home_won = home_score > away_score
                    margin   = round(abs(home_score - away_score), 0)
                    won      = home_won if is_home else (not home_won if is_away else None)
                else:
                    won    = None
                    margin = None

                records.append({
                    "date":          gd_str,
                    "pts":           pts,
                    "reb":           reb,
                    "ast":           ast,
                    "tpm":           tpm,
                    "mins":          mins,
                    "rest":          rest_bucket,
                    "ha":            ha if ha else None,
                    "opp":           opp if opp else None,
                    "player_spread": player_spread,
                    "spread_abs":    spread_abs,
                    "won":           won,
                    "margin":        int(margin) if margin is not None else None,
                })

            if records:
                result[player_name] = records

        return result

    except Exception as e:
        print(f"[build_explorer_data] error: {e}")
        return {}


def build_playoff_data() -> dict:
    """
    Build playoff career profiles + game-level data for the Research tab.
    Reads data/playoff_career_log.csv (populated by espn_playoff_backfill.py +
    daily ingest dual-write) and returns {"profiles": [...], "games": {...}}.
    Returns {} on any error — never blocks site build.
    """
    try:
        import pandas as pd

        playoff_csv = DATA / "playoff_career_log.csv"
        if not playoff_csv.exists():
            print("[build_playoff_data] playoff_career_log.csv not found — skipping")
            return {}

        df = pd.read_csv(playoff_csv, dtype={"game_id": str, "player_id": str})
        if df.empty:
            return {}

        # Coerce numeric columns
        num_cols = ["minutes", "pts", "reb", "ast", "tpm", "fgm", "fga",
                    "fg3m", "fg3a", "ftm", "fta"]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Filter out zero-minute rows (DNP-equivalent in playoff data)
        df = df[df["minutes"].fillna(0) > 0]

        # Filter out All-Star game rows (EAST / WEST team abbreviations)
        valid_teams = {
            "ATL","BKN","BOS","CHA","CHI","CLE","DAL","DEN","DET","GSW",
            "HOU","IND","LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK",
            "OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS",
        }
        df = df[df["team_abbrev"].isin(valid_teams)]

        # Whitelist → current team lookup (for card headers)
        wl_teams: dict = {}
        if WHITELIST_CSV.exists():
            try:
                wl = pd.read_csv(WHITELIST_CSV, dtype=str)
                wl = wl[wl["active"].astype(str).str.strip() == "1"]
                for _, row in wl.iterrows():
                    wl_teams[row["player_name"].strip().lower()] = row["team_abbr"].strip().upper()
            except Exception:
                pass

        stat_cols = ["pts", "reb", "ast", "tpm"]
        profiles: list = []
        games_by_player: dict = {}

        for player_name, pgroup in df.groupby("player_name"):
            name_lower = str(player_name).strip().lower()
            po_rows = pgroup[pgroup["season_type"] == "playoff"]
            if len(po_rows) < 5:
                continue  # Skip players with fewer than 5 career playoff games

            reg_rows = pgroup[pgroup["season_type"] == "regular"]
            po_seasons = set(po_rows["season"].unique())
            # Same-season comparison: only regular rows from seasons with playoff data
            reg_rows = reg_rows[reg_rows["season"].isin(po_seasons)]

            # Career playoff averages
            po_avgs = {col: round(float(po_rows[col].mean()), 1) for col in stat_cols}
            po_avgs["min"] = round(float(po_rows["minutes"].mean()), 1)
            # FG% from aggregate totals — not per-game mean of percentages
            po_fga = float(po_rows["fga"].sum())
            po_fgm = float(po_rows["fgm"].sum())
            po_avgs["fg_pct"] = round(100 * po_fgm / po_fga, 1) if po_fga > 0 else None

            # Regular-season comparison averages
            if not reg_rows.empty:
                reg_avgs = {col: round(float(reg_rows[col].mean()), 1) for col in stat_cols}
                reg_avgs["min"] = round(float(reg_rows["minutes"].mean()), 1)
                reg_fga = float(reg_rows["fga"].sum())
                reg_fgm = float(reg_rows["fgm"].sum())
                reg_avgs["fg_pct"] = round(100 * reg_fgm / reg_fga, 1) if reg_fga > 0 else None
            else:
                reg_avgs = {col: None for col in stat_cols}
                reg_avgs["min"] = None
                reg_avgs["fg_pct"] = None

            # Deltas (playoff − regular)
            deltas: dict = {}
            for col in stat_cols:
                if reg_avgs.get(col) is not None:
                    deltas[col] = round(po_avgs[col] - reg_avgs[col], 1)
                else:
                    deltas[col] = None
            if po_avgs.get("fg_pct") is not None and reg_avgs.get("fg_pct") is not None:
                deltas["fg_pct"] = round(po_avgs["fg_pct"] - reg_avgs["fg_pct"], 1)
            else:
                deltas["fg_pct"] = None

            # Per-season breakdown
            seasons_detail: list = []
            for season in sorted(po_seasons):
                s_po = po_rows[po_rows["season"] == season]
                s_reg = reg_rows[reg_rows["season"] == season]
                s_po_avgs = {col: round(float(s_po[col].mean()), 1) for col in stat_cols}
                s_reg_avgs: dict = {}
                if not s_reg.empty:
                    s_reg_avgs = {col: round(float(s_reg[col].mean()), 1) for col in stat_cols}
                seasons_detail.append({
                    "year": int(season),
                    "games": int(len(s_po)),
                    "po": s_po_avgs,
                    "reg": s_reg_avgs,
                })

            profiles.append({
                "name": str(player_name).strip(),
                "team": wl_teams.get(name_lower, str(po_rows.iloc[0].get("team_abbrev", "?"))),
                "total_games": int(len(po_rows)),
                "seasons": seasons_detail,
                "deltas": deltas,
                "po_avgs": po_avgs,
                "reg_avgs": reg_avgs,
            })

            # Game-level playoff log — infer series number from sequential opponent changes
            po_sorted = po_rows.sort_values("game_date")
            game_list: list = []
            for season in sorted(po_seasons):
                s_games = po_sorted[po_sorted["season"] == season]
                series_num = 0
                last_opp = None
                for _, g in s_games.iterrows():
                    opp = str(g.get("opp_abbrev", "") or "")
                    if opp != last_opp:
                        series_num += 1
                        last_opp = opp
                    fg_pct = None
                    fga_v = g.get("fga")
                    fgm_v = g.get("fgm")
                    if pd.notna(fga_v) and fga_v > 0 and pd.notna(fgm_v):
                        fg_pct = round(100 * float(fgm_v) / float(fga_v), 1)
                    def _ival(x):
                        try:
                            return int(x) if pd.notna(x) else None
                        except (ValueError, TypeError):
                            return None
                    game_list.append({
                        "d":     str(g.get("game_date", ""))[:10],
                        "s":     int(season),
                        "r":     series_num,
                        "opp":   opp,
                        "ha":    str(g.get("home_away", "") or "")[:1],
                        "min":   _ival(g.get("minutes")),
                        "pts":   _ival(g.get("pts")),
                        "reb":   _ival(g.get("reb")),
                        "ast":   _ival(g.get("ast")),
                        "tpm":   _ival(g.get("tpm")),
                        "fgm":   _ival(g.get("fgm")),
                        "fga":   _ival(g.get("fga")),
                        "ftm":   _ival(g.get("ftm")),
                        "fta":   _ival(g.get("fta")),
                        "fg_pct": fg_pct,
                    })
            games_by_player[name_lower] = game_list

        # Sort profiles by total playoff games descending
        profiles.sort(key=lambda p: p["total_games"], reverse=True)

        total_games = sum(len(g) for g in games_by_player.values())
        print(f"[build_playoff_data] {len(profiles)} playoff profiles, "
              f"{total_games} total game rows")
        return {"profiles": profiles, "games": games_by_player}

    except Exception as e:
        print(f"[build_playoff_data] error: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_top_picks(picks: list, max_picks: int = 5) -> list:
    """
    Returns today's top picks.
    Primary: picks where analyst set top_pick=True (LLM-driven selection).
    Fallback: mechanical >= 85% confidence gate (backwards-compat for older picks).
    Returns [] if no qualifying picks.
    """
    open_picks = [p for p in picks if (
        p.get("result") is None and
        not p.get("voided", False) and
        p.get("lineup_risk") != "high"
    )]

    # Primary: analyst-flagged top picks
    flagged = [p for p in open_picks if p.get("top_pick") is True]
    if flagged:
        return flagged[:max_picks]

    # Fallback: legacy confidence gate
    STAT_PRIORITY = {"PTS": 0, "3PM": 1, "AST": 2, "REB": 3}
    candidates = [p for p in open_picks if p.get("confidence_pct", 0) >= 85]

    def score(p):
        hr_str = p.get("hit_rate_display", "0/10")
        try:
            hits = int(hr_str.split("/")[0])
        except Exception:
            hits = 0
        iron     = 1 if p.get("iron_floor") else 0
        stat_pri = STAT_PRIORITY.get(p.get("prop_type", "REB"), 3)
        conf     = p.get("confidence_pct", 0)
        return (iron, conf, hits, -stat_pri)

    return sorted(candidates, key=score, reverse=True)[:max_picks]


def enrich_alt_tiers(today_picks: list[dict]) -> None:
    """Attach alt_tiers data to each today pick for the Odds + Sizing drawer.

    Joins odds_available.json (FanDuel lines at all tiers) with
    player_stats.json (quant tier hit rates) to produce a list of
    alternate tiers per pick — tiers the system did NOT pick but which
    have FanDuel markets.

    Mutates picks in-place: adds pick["alt_tiers"] = [...].
    Graceful no-op when either data file is missing or stale.
    """
    odds_data = load_json(ODDS_AVAILABLE_JSON, None)
    if not odds_data or not isinstance(odds_data, dict):
        return
    if odds_data.get("date") != TODAY_STR:
        return  # stale odds data — skip
    odds_players = odds_data.get("players", {})
    if not odds_players:
        return

    stats_data = load_json(PLAYER_STATS_JSON, None)
    if not stats_data or not isinstance(stats_data, dict):
        return

    def _norm(name: str) -> str:
        return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()

    # Build normalised-name → stats lookup
    stats_by_norm: dict[str, dict] = {}
    for display_name, sdata in stats_data.items():
        stats_by_norm[_norm(display_name)] = sdata

    for pick in today_picks:
        pick_name = pick.get("player_name", "")
        prop_type = pick.get("prop_type", "")
        pick_value = pick.get("pick_value")
        if not pick_name or not prop_type or pick_value is None:
            continue

        norm_name = _norm(pick_name)
        market_entry = odds_players.get(norm_name)
        if not market_entry:
            continue

        market_tiers = market_entry.get(prop_type, [])
        if not market_tiers:
            continue

        # Get tier_hit_rates from player_stats
        player_stats = stats_by_norm.get(norm_name, {})
        hit_rates = (player_stats.get("tier_hit_rates") or {}).get(prop_type, {})
        games = min(player_stats.get("games_available", 20), 20)

        alt_tiers = []
        for mt in market_tiers:
            tier = mt.get("tier")
            if tier is None or tier == pick_value:
                continue  # skip the picked tier
            implied = mt.get("implied_prob")
            line = mt.get("line")
            if implied is None or line is None:
                continue  # insufficient data

            rate = hit_rates.get(str(tier))
            if rate is None:
                continue  # no quant data at this tier

            hits = round(rate * games)
            hit_pct = round(rate * 100, 1)

            alt_tiers.append({
                "tier": tier,
                "line": line,
                "mkt_prob": round(implied, 1),
                "hits": hits,
                "games": games,
                "hit_pct": hit_pct,
            })

        # Sort by tier ascending and deduplicate
        alt_tiers.sort(key=lambda a: a["tier"])
        seen: set = set()
        deduped = []
        for at in alt_tiers:
            if at["tier"] not in seen:
                seen.add(at["tier"])
                deduped.append(at)
        pick["alt_tiers"] = deduped


CANNIBALIZATION_JSON = DATA / "backtest_teammate_cannibalization.json"


def build_cannib_lookup() -> dict:
    """
    Build a slim H33 cannibalization lookup for the frontend.
    Key: "name_a|name_b|STAT" (names sorted, lowercased).
    Value: {"idx": float, "label": str}
    Returns {} gracefully if data file is missing.
    """
    if not CANNIBALIZATION_JSON.exists():
        return {}
    try:
        with open(CANNIBALIZATION_JSON) as f:
            data = json.load(f)
        lookup = {}
        for team, tr in data.get("team_results", {}).items():
            for pair in tr.get("pair_results", []):
                names = sorted([
                    pair["player_a"].strip().lower(),
                    pair["player_b"].strip().lower(),
                ])
                stat = pair["stat"]
                label = pair.get("label", "")
                # Only include MODERATE or STRONG signals
                if "MODERATE" not in label and "STRONG" not in label:
                    continue
                key = f"{names[0]}|{names[1]}|{stat}"
                lookup[key] = {
                    "idx": round(pair["cannib_idx"], 1),
                    "label": label,
                }
        print(f"[build_site] cannib lookup: {len(lookup)} pairs")
        return lookup
    except Exception as e:
        print(f"[build_site] WARNING: cannib lookup failed: {e}")
        return {}


def build_corr_lookup(today_picks: list) -> dict:
    """
    Build a slim correlation tag lookup for the frontend builder.
    Reads teammate_correlations from player_stats.json for today's players.
    Key: "player_a_lower|player_b_lower|STATA_STATB" (direction-aware, NOT sorted).
    Value: {"tag": str, "r": float|null}
    Returns {} gracefully if data file is missing.
    """
    if not PLAYER_STATS_JSON.exists():
        return {}
    try:
        stats = load_json(PLAYER_STATS_JSON, {})
        if not stats:
            return {}

        # Only extract for today's players (reduces payload)
        today_names = {(p.get("player_name") or "").strip() for p in today_picks}
        today_names.discard("")

        lookup = {}
        for player_name in today_names:
            pdata = stats.get(player_name, {})
            tc = pdata.get("teammate_correlations", {})
            for teammate_name, entry in tc.items():
                if teammate_name not in today_names:
                    continue
                for stat_pair, corr_data in entry.get("correlations", {}).items():
                    tag = corr_data.get("tag", "independent")
                    r_val = corr_data.get("r")
                    key = f"{player_name.lower()}|{teammate_name.lower()}|{stat_pair}"
                    lookup[key] = {
                        "tag": tag,
                        "r": round(r_val, 2) if r_val is not None else None,
                    }

        print(f"[build_site] corr lookup: {len(lookup)} entries")
        return lookup
    except Exception as e:
        print(f"[build_site] WARNING: corr lookup failed: {e}")
        return {}


def build_site():
    picks     = load_json(PICKS_JSON, [])
    audit_log = load_json(AUDIT_LOG_JSON, [])
    game_times = load_game_times()
    injuries_display = load_injuries_display()
    ml_odds = load_game_ml_odds()
    parlays_data      = load_todays_parlays()
    yesterday_summary = load_yesterday_summary()
    opportunity_flags = load_opportunity_flags()
    explorer_data     = build_explorer_data()
    playoff_data      = build_playoff_data()
    cannib_lookup     = build_cannib_lookup()

    # Build lookup dict from review file: key → {verdict, trim_reasons, auto_reviewed}
    # Covers both auto (source="auto") and manual (no source field) review entries.
    review_lookup: dict[tuple, dict] = {}
    try:
        if PICKS_REVIEW_JSON.exists():
            review_entries = load_json(PICKS_REVIEW_JSON, [])
            for e in review_entries:
                key = (
                    (e.get("player_name") or "").strip().lower(),
                    e.get("prop_type", ""),
                    e.get("pick_value"),
                )
                review_lookup[key] = {
                    "verdict":       e.get("verdict", ""),
                    "trim_reasons":  e.get("trim_reasons") or [],
                    "auto_reviewed": e.get("source") == "auto",
                }
    except Exception:
        pass

    today_picks = [p for p in picks if p.get("date") == TODAY_STR]
    past_picks  = [p for p in picks if p.get("date") != TODAY_STR
                   and p.get("result") in ("HIT", "MISS")]

    past_top_picks = [p for p in past_picks if
                      p.get("top_pick") is True or p.get("confidence_pct", 0) >= 85]
    tp_hits   = sum(1 for p in past_top_picks if p["result"] == "HIT")
    tp_total  = len(past_top_picks)
    tp_pct    = round(100 * tp_hits / tp_total, 1) if tp_total else 0

    # Playoff stats — all graded picks from R1 onwards
    playoff_graded = [p for p in past_picks if p.get("date", "") >= PLAYOFFS_R1_DATE]
    playoff_hits   = sum(1 for p in playoff_graded if p["result"] == "HIT")
    playoff_total  = len(playoff_graded)
    playoff_pct    = round(100 * playoff_hits / playoff_total, 1) if playoff_total else 0
    playoff_voided = sum(
        1 for p in picks
        if p.get("date", "") >= PLAYOFFS_R1_DATE
        and p.get("voided", False)
    )

    # Attach game time and review verdict to today's picks
    for p in today_picks:
        p["game_time"] = game_times.get(str(p.get("team", "")).upper(), "")
        name_lower = (p.get("player_name") or "").strip().lower()
        key = (name_lower, p.get("prop_type", ""), p.get("pick_value"))
        review_entry = review_lookup.get(key)
        if review_entry:
            p["human_verdict"]  = review_entry["verdict"]
            p["trim_reasons"]   = review_entry["trim_reasons"]
            p["auto_reviewed"]  = review_entry["auto_reviewed"]
        else:
            p["human_verdict"]  = ""
            p["trim_reasons"]   = []
            p["auto_reviewed"]  = False

    enrich_alt_tiers(today_picks)
    corr_lookup       = build_corr_lookup(today_picks)

    top_picks = get_top_picks(today_picks)

    # Best Bets: picks with POSITIVE or STRONG calibrated edge, ranked by edge
    best_bets = [
        p for p in today_picks
        if not p.get("voided", False)
        and p.get("result") is None
        and p.get("bet_recommendation", {}).get("recommendation_tier") in ("POSITIVE", "STRONG")
    ]
    best_bets.sort(
        key=lambda p: p.get("bet_recommendation", {}).get("calibrated_edge_pct", 0),
        reverse=True,
    )

    total_hits   = sum(1 for p in past_picks if p["result"] == "HIT")
    total_graded = len(past_picks)
    overall_pct  = round(100 * total_hits / total_graded, 1) if total_graded else 0

    prop_types = ["PTS", "REB", "AST", "3PM"]
    prop_stats = {}
    for pt in prop_types:
        subset = [p for p in past_picks if p.get("prop_type") == pt]
        h = sum(1 for p in subset if p["result"] == "HIT")
        streak = compute_streak(past_picks, pt)
        prop_stats[pt] = {
            "hits": h,
            "total": len(subset),
            "pct": round(100 * h / len(subset), 1) if subset else 0,
            **streak,
        }

    daily_trend = compute_daily_trend(past_picks)
    last_audit  = audit_log[-1] if audit_log else None

    page_data = {
        "today_str":      TODAY_STR,
        "today_picks":    today_picks,
        "overall_hit_rate": overall_pct,
        "total_graded":   total_graded,
        "prop_stats":     prop_stats,
        "daily_trend":    daily_trend,
        "last_audit":     last_audit,
        "recent_results": sorted(past_picks,
                                  key=lambda p: p.get("date", ""),
                                  reverse=True)[:40],
        "injuries":  injuries_display,
        "parlays":   parlays_data,
        "ml_odds":          ml_odds,
        "yesterday_summary":  yesterday_summary,
        "opportunity_flags":  opportunity_flags,
        "explorer":           explorer_data,
        "playoff":            playoff_data,
        "cannib_lookup":      cannib_lookup,
        "corr_lookup":        corr_lookup,
        "top_picks": top_picks,
        "best_bets": best_bets,
        "top_picks_history": {
            "hits": tp_hits,
            "total": tp_total,
            "pct": tp_pct,
            "picks": sorted(past_top_picks, key=lambda p: p.get("date", ""), reverse=True)[:40],
        },
        "playoff_stats": {
            "hits": playoff_hits,
            "total": playoff_total,
            "pct": playoff_pct,
            "voided": playoff_voided,
        },
        "built_at": dt.datetime.now(PT).strftime("%B %d, %Y at %-I:%M %p PT"),
    }

    html = generate_html(page_data)
    SITE.mkdir(exist_ok=True)
    with open(SITE / "index.html", "w") as f:
        f.write(html)

    print(f"[build_site] Wrote site/index.html "
          f"({len(today_picks)} today's picks, "
          f"{total_graded} graded, "
          f"{len(daily_trend)} trend days)")


def generate_html(d: dict) -> str:
    picks_json      = json.dumps(d["today_picks"])
    results_json    = json.dumps(d["recent_results"])
    prop_stats_json = json.dumps(d["prop_stats"])
    last_audit_json = json.dumps(d["last_audit"])
    trend_json      = json.dumps(d["daily_trend"])
    injuries_json   = json.dumps(d.get("injuries", {"fetched_at": None, "games": []}))
    parlays_json    = json.dumps(d.get("parlays", {"today": [], "hits": 0, "misses": 0, "total": 0, "hit_rate_pct": 0}))
    ml_odds_json    = json.dumps(d.get("ml_odds", {}))
    top_picks_json          = json.dumps(d.get("top_picks", []))
    best_bets_json          = json.dumps(d.get("best_bets", []))
    top_picks_history_json  = json.dumps(d.get("top_picks_history", {"hits": 0, "total": 0, "pct": 0, "picks": []}))
    playoff_stats_json      = json.dumps(d.get("playoff_stats", {"hits": 0, "total": 0, "pct": 0, "voided": 0}))
    yesterday_summary_json  = json.dumps(d.get("yesterday_summary", {}))
    opportunity_flags_json  = json.dumps(d.get("opportunity_flags", []))
    explorer_json           = json.dumps(d.get("explorer", {}))
    playoff_json            = json.dumps(d.get("playoff", {}))
    cannib_json             = json.dumps(d.get("cannib_lookup", {}))
    corr_json               = json.dumps(d.get("corr_lookup", {}))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>NBAgent</title>
  <link rel="icon" href="favicon.ico" />
  <link rel="icon" type="image/png" sizes="192x192" href="icon-192x192.png" />
  <link rel="apple-touch-icon" href="apple-touch-icon.png" />
  <link rel="manifest" href="manifest.json" />
  <meta name="theme-color" content="#0d0d0f" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black" />
  <meta name="apple-mobile-web-app-title" content="NBAgent" />
  <style>
    :root {{
      --bg: #0d0d0f; --surface: #18181c; --surface2: #202026;
      --border: #2a2a32; --accent: #E8703A; --accent2: #00d4aa;
      --hit: #22c55e; --miss: #ef4444; --text: #e8e8f0; --muted: #888898;
      --pts: #f97316; --reb: #3b82f6; --ast: #a855f7; --3pm: #eab308;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 15px; min-height: 100vh; }}

    header {{ background: var(--surface); border-bottom: 1px solid var(--border);
              padding: 16px 20px; display: flex; align-items: center;
              justify-content: space-between; position: sticky; top: 0; z-index: 10; }}
    .logo {{
      font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 29px;
      font-weight: 900;
      letter-spacing: -0.04em;
      line-height: 1;
      display: flex;
      align-items: baseline;
    }}
    .logo-nb {{ color: #f0f0f8; }}
    .logo-a {{
      background: linear-gradient(90deg, #f0f0f8 0%, #f0f0f8 15%, #E8703A 55%, #E8703A 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }}
    .logo-gent {{ color: #E8703A; }}
    .built-at {{ font-size: 11px; color: var(--muted); }}

    .tabs {{ display: flex; gap: 4px; padding: 12px 20px 0;
             border-bottom: 1px solid var(--border); background: var(--surface);
             position: sticky; top: 53px; z-index: 9; overflow-x: auto; white-space: nowrap; }}
    .tab {{ padding: 8px 16px; border-radius: 6px 6px 0 0; cursor: pointer;
            font-size: 13px; font-weight: 500; color: var(--muted); border: none;
            background: none; border-bottom: 2px solid transparent; transition: all 0.15s;
            white-space: nowrap; }}
    .tab.active {{ color: var(--text); border-bottom-color: var(--accent); }}
    .tab:hover:not(.active) {{ color: var(--text); }}

    .page {{ display: none; padding: 20px; max-width: 900px; margin: 0 auto; }}
    .page.active {{ display: block; }}

    .section-header {{ font-size: 11px; font-weight: 600; text-transform: uppercase;
                       letter-spacing: 1px; color: var(--muted);
                       margin-bottom: 12px; margin-top: 24px; }}
    .section-header:first-child {{ margin-top: 0; }}

    /* Pick cards */
    .picks-grid {{ display: flex; flex-direction: column; gap: 10px; }}
    .pick-card {{ background: var(--surface); border: 1px solid var(--border);
                  border-radius: 12px; padding: 14px 16px;
                  display: grid; grid-template-columns: 1fr auto;
                  gap: 12px; align-items: start; transition: border-color 0.15s; }}
    .pick-card:hover {{ border-color: var(--accent); }}
    .pick-card.voided {{ opacity: 0.55; border-color: rgba(239,68,68,0.3); }}
    .pick-card.voided .player {{ text-decoration: line-through; color: var(--muted); }}
    .void-badge {{ display: inline-block; font-size: 10px; font-weight: 700;
                   padding: 2px 7px; border-radius: 4px;
                   background: rgba(239,68,68,0.15); color: #ef4444; }}
    .risk-badge-high {{ display: inline-block; font-size: 10px; font-weight: 700;
                        padding: 2px 7px; border-radius: 4px;
                        background: rgba(249,115,22,0.15); color: #f97316; }}
    .risk-badge-moderate {{ display: inline-block; font-size: 10px; font-weight: 700;
                            padding: 2px 7px; border-radius: 4px;
                            background: rgba(234,179,8,0.15); color: #eab308; }}
    .review-badge-trim {{ display: inline-block; font-size: 10px; font-weight: 700;
                          padding: 2px 8px; border-radius: 4px; letter-spacing: 0.05em;
                          background: rgba(245,166,35,0.12); color: #F5A623;
                          border: 1px solid rgba(245,166,35,0.3); margin-right: 4px; }}
    .review-badge-skip {{ display: inline-block; font-size: 10px; font-weight: 700;
                          padding: 2px 8px; border-radius: 4px; letter-spacing: 0.05em;
                          background: rgba(239,68,68,0.10); color: #ef4444;
                          border: 1px solid rgba(239,68,68,0.25); margin-right: 4px; }}
    .parlay-risk-banner {{ font-size: 11px; font-weight: 600; color: #f97316;
                           padding: 5px 8px; margin-top: 6px;
                           background: rgba(249,115,22,0.08);
                           border-radius: 4px; border-left: 3px solid #f97316; }}
    .prop-badge {{ width: 44px; height: 44px; border-radius: 10px;
                   display: flex; align-items: center; justify-content: center;
                   font-size: 11px; font-weight: 700; flex-shrink: 0; }}
    .prop-PTS {{ background: rgba(249,115,22,0.15); color: var(--pts); }}
    .prop-REB {{ background: rgba(59,130,246,0.15); color: var(--reb); }}
    .prop-AST {{ background: rgba(168,85,247,0.15); color: var(--ast); }}
    .prop-3PM {{ background: rgba(234,179,8,0.15);  color: var(--3pm); }}
    .pick-main .player  {{ font-size: 16px; font-weight: 600; }}
    .pick-main .reasoning {{ font-size: 12px; color: var(--muted); margin-top: 7px; line-height: 1.5; font-style: italic; }}
    .tier-walk {{ font-size: 10px; color: var(--muted); margin-top: 4px; font-family: monospace; opacity: 0.7; }}
    .tier-walk-toggle {{ display: inline-flex; align-items: center; gap: 4px; margin-top: 6px;
      font-size: 10px; color: var(--muted); cursor: pointer; user-select: none;
      background: none; border: 1px solid var(--border); border-radius: 4px;
      padding: 2px 7px; line-height: 1.6; }}
    .tier-walk-toggle:hover {{ border-color: var(--accent); color: var(--accent); }}
    .tier-walk-body {{ display: none; }}
    .lineup-update-badge-up   {{ color: #22c55e; font-size: 11px; cursor: pointer; background: none;
      border: 1px solid rgba(34,197,94,0.3); border-radius: 4px; padding: 2px 7px;
      margin-top: 5px; display: inline-flex; align-items: center; user-select: none; }}
    .lineup-update-badge-down {{ color: #f59e0b; font-size: 11px; cursor: pointer; background: none;
      border: 1px solid rgba(245,158,11,0.3); border-radius: 4px; padding: 2px 7px;
      margin-top: 5px; display: inline-flex; align-items: center; user-select: none; }}
    .lineup-update-body {{ display: none; font-size: 11px; color: var(--muted);
      margin-top: 4px; line-height: 1.5; }}
    .micro-stats {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }}
    .micro-pill {{ font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 99px;
                   background: var(--surface2); border: 1px solid var(--border); color: var(--muted); }}
    .micro-pill.up    {{ color: var(--hit);  background: rgba(34,197,94,0.08);  border-color: rgba(34,197,94,0.2); }}
    .micro-pill.down  {{ color: var(--miss); background: rgba(239,68,68,0.08);  border-color: rgba(239,68,68,0.2); }}
    .micro-pill.soft  {{ color: var(--hit);  background: rgba(34,197,94,0.08);  border-color: rgba(34,197,94,0.2); }}
    .micro-pill.tough {{ color: var(--miss); background: rgba(239,68,68,0.08);  border-color: rgba(239,68,68,0.2); }}
    .pick-right {{ text-align: right; flex-shrink: 0; }}
    .pick-line {{ font-size: 26px; font-weight: 800; color: var(--accent2);
                  display: flex; align-items: baseline; gap: 5px; justify-content: flex-end; }}
    .pick-line .stat-type {{ font-size: 11px; font-weight: 700; padding: 2px 6px;
                              border-radius: 5px; line-height: 1; align-self: center; }}
    .hit-rate-block {{ margin-top: 8px; text-align: right; }}
    .hit-rate-fraction {{ font-size: 13px; font-weight: 700; color: var(--text); }}
    .hit-rate-label {{ font-size: 10px; color: var(--muted); margin-left: 2px; }}
    .hit-bar {{ height: 4px; background: var(--border); border-radius: 99px;
                overflow: hidden; margin-top: 4px; width: 64px; margin-left: auto; }}
    .hit-fill {{ height: 100%; border-radius: 99px; }}
    .conf-line {{ font-size: 10px; color: var(--muted); margin-top: 6px; }}
    .edge-line {{ font-size: 10px; font-weight: 600; margin-top: 4px; white-space: nowrap; }}
    .edge-line.strong  {{ color: #22c55e; }}
    .edge-line.positive {{ color: #2dd4bf; }}
    .edge-line.neutral {{ color: var(--muted); }}
    .edge-line.fade    {{ color: #ef4444; }}
    .movement-line {{ font-size: 10px; margin-top: 6px; line-height: 1.5; }}
    .movement-line.agrees {{ color: #2dd4bf; }}
    .movement-line.disagrees {{ color: #FF9800; }}
    .movement-line.significant {{ font-weight: 600; }}
    .movement-line .edge-shift {{ font-size: 9px; opacity: 0.8; }}
    .movement-line .edge-shift s {{ text-decoration-color: inherit; opacity: 0.6; }}
    .movement-drawer {{ font-size: 10px; color: var(--muted); margin-top: 2px;
      line-height: 1.6; font-family: monospace; opacity: 0.75; }}
    .odds-sizing-toggle {{ display: inline-flex; align-items: center; gap: 4px; margin-top: 6px;
      font-size: 10px; color: var(--muted); cursor: pointer; user-select: none;
      background: none; border: 1px solid var(--border); border-radius: 4px;
      padding: 2px 7px; line-height: 1.6; }}
    .odds-sizing-toggle:hover {{ border-color: var(--accent); color: var(--accent); }}
    .odds-sizing-body {{ display: none; font-size: 11px; color: var(--muted);
      margin-top: 4px; line-height: 1.7; font-family: monospace; opacity: 0.85; }}
    .alt-tiers-header {{ font-size: 10px; color: var(--muted); margin-top: 8px;
      border-top: 1px solid var(--border); padding-top: 6px; opacity: 0.6; }}
    .alt-tier-row {{ font-size: 11px; color: var(--muted); font-family: monospace;
      line-height: 1.7; opacity: 0.85; }}
    .alt-tier-row.has-edge {{ color: #2dd4bf; opacity: 1; }}

    /* Injury report dropdown */
    .injury-dropdown {{ margin-bottom: 20px; }}
    .injury-header {{ background: var(--surface); border: 1px solid var(--border);
                      border-radius: 10px; padding: 12px 16px;
                      display: flex; align-items: center; justify-content: space-between;
                      cursor: pointer; user-select: none; transition: border-color 0.15s; }}
    .injury-header:hover {{ border-color: var(--accent); }}
    .injury-header.open {{ border-radius: 10px 10px 0 0; border-bottom-color: transparent; }}
    .injury-header-left {{ display: flex; align-items: center; gap: 10px; }}
    .injury-title {{ font-size: 13px; font-weight: 600; }}
    .injury-as-of {{ font-size: 11px; color: var(--muted); }}
    .injury-chevron {{ font-size: 12px; color: var(--muted); transition: transform 0.2s; }}
    .injury-chevron.open {{ transform: rotate(180deg); }}
    .injury-body {{ background: var(--surface); border: 1px solid var(--border);
                    border-top: none; border-radius: 0 0 10px 10px;
                    padding: 12px 16px; display: none; }}
    .injury-body.open {{ display: block; }}
    .injury-game {{ margin-bottom: 16px; }}
    .injury-game:last-child {{ margin-bottom: 0; }}
    .injury-game-header {{ font-size: 11px; font-weight: 700; color: var(--muted);
                           text-transform: uppercase; letter-spacing: 0.8px;
                           margin-bottom: 8px; }}
    .injury-team-block {{ margin-bottom: 10px; }}
    .injury-team-name {{ font-size: 12px; font-weight: 600; margin-bottom: 5px; color: var(--text); }}
    .injury-player-row {{ display: flex; align-items: center; gap: 8px;
                          padding: 4px 0; border-bottom: 1px solid var(--border);
                          font-size: 12px; }}
    .injury-player-row:last-child {{ border-bottom: none; }}
    .injury-player-rotation {{ opacity: 0.6; font-style: italic; }}
    .injury-player-name {{ flex: 1; }}
    .injury-reason {{ color: var(--muted); font-size: 11px; flex: 2; }}
    .status-OUT  {{ background: rgba(239,68,68,0.15);  color: #ef4444;
                    font-size: 10px; font-weight: 700; padding: 2px 6px;
                    border-radius: 4px; white-space: nowrap; }}
    .status-DOUBTFUL {{ background: rgba(249,115,22,0.15); color: #f97316;
                        font-size: 10px; font-weight: 700; padding: 2px 6px;
                        border-radius: 4px; white-space: nowrap; }}
    .status-QUESTIONABLE {{ background: rgba(234,179,8,0.15); color: #eab308;
                            font-size: 10px; font-weight: 700; padding: 2px 6px;
                            border-radius: 4px; white-space: nowrap; }}
    .status-PROBABLE {{ background: rgba(34,197,94,0.15); color: #22c55e;
                        font-size: 10px; font-weight: 700; padding: 2px 6px;
                        border-radius: 4px; white-space: nowrap; }}
    .status-OTHER {{ background: var(--surface2); color: var(--muted);
                     font-size: 10px; font-weight: 700; padding: 2px 6px;
                     border-radius: 4px; white-space: nowrap; }}

    /* Game group headers */
    .game-group {{ margin-bottom: 12px; }}
    .game-group-header {{ display: flex; align-items: center; gap: 10px;
                          padding: 11px 14px; border-radius: 10px;
                          background: var(--surface); border: 1px solid var(--border);
                          cursor: pointer; user-select: none;
                          transition: border-color 0.15s; }}
    .game-group-header:hover {{ border-color: var(--accent); }}
    .game-group-header.open {{ border-radius: 10px 10px 0 0; border-bottom-color: transparent; }}
    .game-matchup {{ font-size: 14px; font-weight: 700; letter-spacing: -0.3px; }}
    .ml-pct {{ font-size: 11px; font-weight: 400; color: var(--muted); letter-spacing: 0; }}
    .game-tip {{ font-size: 11px; color: var(--accent2); background: var(--surface2);
                 border: 1px solid var(--border); border-radius: 4px;
                 padding: 2px 7px; white-space: nowrap; }}
    .game-pick-count {{ font-size: 11px; color: var(--muted); margin-left: auto; }}
    .game-chevron {{ font-size: 11px; color: var(--muted); transition: transform 0.2s;
                     flex-shrink: 0; }}
    .game-chevron.open {{ transform: rotate(180deg); }}
    .game-body {{ background: var(--surface); border: 1px solid var(--border);
                  border-top: none; border-radius: 0 0 10px 10px;
                  padding: 10px 10px 12px; display: none; }}
    .game-body.open {{ display: block; }}

    /* Back to top */
    #back-to-top {{ position: fixed; bottom: 24px; right: 24px;
                    width: 40px; height: 40px; border-radius: 50%;
                    background: var(--accent); color: #fff;
                    border: none; cursor: pointer; font-size: 16px;
                    display: flex; align-items: center; justify-content: center;
                    opacity: 0; pointer-events: none;
                    transition: opacity 0.25s, transform 0.25s;
                    transform: translateY(8px); z-index: 100;
                    box-shadow: 0 4px 12px rgba(232,112,58,0.4); }}
    #back-to-top.visible {{ opacity: 1; pointer-events: auto; transform: translateY(0); }}
    #back-to-top:hover {{ background: #cf622f; }}

    /* Streak pill */
    .streak-pill {{ display: inline-flex; align-items: center; gap: 4px;
                    font-size: 10px; font-weight: 600; padding: 2px 7px;
                    border-radius: 99px; }}
    .streak-hit  {{ background: rgba(34,197,94,0.15);  color: var(--hit); }}
    .streak-miss {{ background: rgba(239,68,68,0.15);  color: var(--miss); }}

    /* Prop streak cards */
    .prop-streak-grid {{ display: grid; grid-template-columns: repeat(2,1fr);
                         gap: 10px; margin-bottom: 20px; }}
    @media(min-width:500px) {{ .prop-streak-grid {{ grid-template-columns: repeat(4,1fr); }} }}
    .prop-streak-card {{ background: var(--surface); border: 1px solid var(--border);
                         border-radius: 10px; padding: 12px 14px; }}
    .psc-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase;
                  letter-spacing: 0.5px; margin-bottom: 6px;
                  display: flex; justify-content: space-between; align-items: center; }}
    .psc-pct {{ font-size: 22px; font-weight: 700; }}
    .psc-sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}

    /* Overall banner */
    .overall-banner {{ background: linear-gradient(135deg,rgba(232,112,58,0.12),rgba(0,212,170,0.12));
                       border: 1px solid var(--border); border-radius: 12px;
                       padding: 18px 20px; display: flex; align-items: flex-start;
                       justify-content: space-between; margin-bottom: 20px;
                       flex-wrap: wrap; gap: 16px; }}
    .overall-banner .big {{ font-size: 38px; font-weight: 800; color: var(--accent2); line-height: 1; }}
    .overall-banner .sub {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}

    /* Results tab — stat cards */
    .results-cards-row {{ display: grid; grid-template-columns: repeat(4, 1fr);
                          gap: 12px; margin-bottom: 16px; }}
    .results-card {{ background: var(--surface); border: 1px solid var(--border);
                     border-radius: 12px; padding: 16px 18px; }}
    .results-card-wide {{ grid-column: 1 / -1; }}
    .results-card-header {{ font-size: 10px; font-weight: 700; text-transform: uppercase;
                            letter-spacing: 0.6px; color: var(--muted); margin-bottom: 8px; }}
    .results-hero-num {{ font-size: 36px; font-weight: 800; color: var(--accent2); line-height: 1; }}
    .results-hero-sub {{ font-size: 11px; color: var(--muted); margin-top: 4px; }}
    @media (max-width: 480px) {{
      .results-cards-row {{ grid-template-columns: 1fr 1fr; }}
      .results-card-wide {{ grid-column: 1 / -1; }}
    }}

    /* Trend chart */
    .chart-wrap {{ background: var(--surface); border: 1px solid var(--border);
                   border-radius: 12px; padding: 16px; margin-bottom: 20px; }}
    .chart-title {{ font-size: 11px; color: var(--muted); margin-bottom: 12px;
                    font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
    #trend-chart {{ width: 100%; height: 160px; display: block; }}

    /* History table */
    .history-table {{ min-width: 100%; border-collapse: collapse; font-size: 13px; }}
    .history-table th {{ text-align: left; font-size: 10px; font-weight: 600;
                         color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px;
                         padding: 8px 10px; border-bottom: 1px solid var(--border); }}
    .history-table td {{ padding: 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
    .history-table tr:last-child td {{ border-bottom: none; }}
    .history-table tr:hover td {{ background: var(--surface2); }}
    .result-hit  {{ color: var(--hit);  font-weight: 600; font-size: 12px; }}
    .result-miss {{ color: var(--miss); font-weight: 600; font-size: 12px; }}
    .result-nd   {{ color: var(--muted); font-size: 12px; }}

    /* Audit */
    .audit-card {{ background: var(--surface); border: 1px solid var(--border);
                   border-radius: 12px; padding: 16px; margin-bottom: 12px; }}
    .audit-card h3 {{ font-size: 14px; font-weight: 600; margin-bottom: 12px; }}
    .audit-list {{ list-style: none; }}
    .audit-list li {{ padding: 7px 0; font-size: 13px; color: var(--muted);
                      border-bottom: 1px solid var(--border); line-height: 1.5; }}
    .audit-list li:last-child {{ border-bottom: none; }}
    .audit-list li::before {{ content: "→ "; color: var(--accent); }}

    .empty {{ text-align: center; padding: 48px 20px; color: var(--muted); font-size: 14px; }}
    .empty-icon {{ font-size: 36px; margin-bottom: 12px; }}

    /* Parlays */
    .parlay-tier-drawer {{ margin-bottom: 10px; }}
    .parlay-tier-drawer .drawer-header {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 10px 14px; background: var(--surface);
      border: 1px solid var(--border); border-radius: 10px;
      cursor: pointer; user-select: none; font-size: 14px;
    }}
    .parlay-tier-drawer .drawer-header:hover {{ border-color: var(--accent); }}
    .parlay-tier-drawer .drawer-body {{ padding-top: 8px; }}
    .tier-header-label {{ font-weight: 700; }}
    .tier-range {{ font-size: 11px; color: var(--muted); font-weight: 500; margin-left: 4px; }}
    .tier-count {{ font-size: 11px; color: var(--muted); font-weight: 500; }}

    .parlay-card {{ background: var(--surface); border: 1px solid var(--border);
                    border-radius: 12px; padding: 16px; margin-bottom: 12px;
                    transition: border-color 0.15s; }}
    .parlay-card:hover {{ border-color: var(--accent); }}
    .parlay-card-header-lean {{
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 10px; min-height: 20px;
    }}
    .parlay-header-spacer {{ flex: 1; }}
    .parlay-header-right {{ font-size: 15px; font-weight: 700; }}
    .parlay-odds {{ font-size: 15px; font-weight: 700; color: var(--accent); }}
    .parlay-result-hit  {{ font-size: 11px; font-weight: 700; color: var(--hit);
                           background: rgba(34,197,94,0.12); padding: 2px 8px;
                           border-radius: 99px; white-space: nowrap; }}
    .parlay-result-miss {{ font-size: 11px; font-weight: 700; color: var(--miss);
                           background: rgba(239,68,68,0.12); padding: 2px 8px;
                           border-radius: 99px; white-space: nowrap; }}
    .parlay-result-partial {{ font-size: 11px; font-weight: 700; color: var(--3pm);
                              background: rgba(234,179,8,0.12); padding: 2px 8px;
                              border-radius: 99px; white-space: nowrap; }}
    .parlay-legs {{ border-top: 1px solid var(--border); padding-top: 10px; display: flex; flex-direction: column; gap: 7px; }}
    .parlay-leg {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
    .leg-main {{ flex: 1; min-width: 0; }}
    .leg-player {{ font-size: 13px; font-weight: 600; white-space: nowrap;
                   overflow: hidden; text-overflow: ellipsis; }}
    .leg-team {{ font-size: 11px; color: var(--muted); }}
    .leg-stat {{ display: flex; align-items: baseline; gap: 4px; flex-shrink: 0; }}
    .leg-stat-value {{ font-size: 18px; font-weight: 800; color: var(--text); }}
    .leg-stat-type {{ font-size: 10px; font-weight: 700; padding: 2px 5px;
                      border-radius: 4px; line-height: 1; }}
    .leg-conf {{ font-size: 10px; color: var(--muted); margin-left: 4px; white-space: nowrap; }}
    .leg-result-hit  {{ font-size: 13px; color: var(--hit);  margin-left: 6px; flex-shrink: 0; }}
    .leg-result-miss {{ font-size: 13px; color: var(--miss); margin-left: 6px; flex-shrink: 0; }}
    .parlay-rationale {{ font-size: 12px; color: var(--muted); font-style: italic;
                         border-top: 1px solid var(--border); padding-top: 10px;
                         margin-top: 10px; line-height: 1.5; }}

    /* Spec 3: cannibalization badges between parlay legs */
    .cannib-badge {{ display: flex; align-items: center; gap: 5px;
                     font-size: 10px; font-weight: 600; padding: 2px 0;
                     margin: -2px 0 -2px 8px; }}
    .cannib-badge.cannib-neg {{ color: #f59e0b; }}
    .cannib-badge.cannib-pos {{ color: var(--accent2); }}

    /* Parlay Builder */
    .builder-section {{ margin-top: 32px; border-top: 1px solid var(--border); padding-top: 24px; }}
    .builder-header {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                       letter-spacing: 1.5px; color: var(--accent); margin-bottom: 16px;
                       display: flex; align-items: center; gap: 8px; }}
    .builder-layout {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
    @media (max-width: 700px) {{
      .builder-layout {{ grid-template-columns: 1fr; }}
    }}
    .builder-picks {{ max-height: 500px; overflow-y: auto; }}
    .builder-game-group {{ margin-bottom: 12px; }}
    .builder-game-header {{ font-size: 11px; font-weight: 700; color: var(--muted);
                            text-transform: uppercase; letter-spacing: 0.5px;
                            padding: 6px 0; border-bottom: 1px solid var(--border);
                            margin-bottom: 6px; display: flex; justify-content: space-between; }}
    .builder-pick-row {{ display: flex; align-items: center; justify-content: space-between;
                         padding: 8px 10px; border-radius: 8px; cursor: pointer;
                         transition: background 0.12s; border: 1px solid transparent;
                         margin-bottom: 2px; }}
    .builder-pick-row:hover {{ background: var(--surface2); }}
    .builder-pick-row.selected {{ background: rgba(232,112,58,0.08);
                                  border-color: var(--accent); }}
    .builder-pick-row.voided {{ opacity: 0.35; cursor: not-allowed;
                                text-decoration: line-through; }}
    .builder-pick-left {{ display: flex; align-items: center; gap: 8px; min-width: 0; }}
    .builder-pick-name {{ font-size: 13px; font-weight: 600; white-space: nowrap;
                          overflow: hidden; text-overflow: ellipsis; }}
    .builder-pick-stat {{ font-size: 11px; font-weight: 700; padding: 1px 5px;
                          border-radius: 4px; }}
    .builder-pick-tier {{ font-size: 14px; font-weight: 800; }}
    .builder-pick-conf {{ font-size: 11px; color: var(--muted); white-space: nowrap; }}

    .builder-card {{ background: var(--surface); border: 1px solid var(--border);
                     border-radius: 12px; padding: 16px; position: sticky; top: 110px; }}
    .builder-card-empty {{ color: var(--muted); font-size: 13px;
                           text-align: center; padding: 24px 0; }}
    .builder-leg-row {{ display: flex; align-items: center; justify-content: space-between;
                        padding: 6px 0; border-bottom: 1px solid var(--border); }}
    .builder-leg-row:last-of-type {{ border-bottom: none; }}
    .builder-leg-remove {{ color: var(--miss); cursor: pointer; font-size: 12px;
                           background: none; border: none; padding: 2px 6px; }}
    .builder-leg-remove:hover {{ background: rgba(239,68,68,0.1); border-radius: 4px; }}
    .builder-stats-row {{ display: flex; gap: 16px; flex-wrap: wrap;
                          padding: 12px 0; border-top: 1px solid var(--border);
                          margin-top: 8px; }}
    .builder-stat {{ text-align: center; }}
    .builder-stat .val {{ font-size: 18px; font-weight: 800; }}
    .builder-stat .lbl {{ font-size: 10px; color: var(--muted); text-transform: uppercase;
                          letter-spacing: 0.3px; }}
    .builder-edge-pos {{ color: var(--hit); }}
    .builder-edge-neg {{ color: var(--miss); }}
    .builder-edge-neutral {{ color: var(--muted); }}
    .builder-warnings {{ margin-top: 10px; padding-top: 10px;
                         border-top: 1px solid var(--border); }}
    .builder-warning-item {{ font-size: 11px; padding: 3px 0; display: flex;
                             align-items: center; gap: 5px; }}
    .builder-actions {{ display: flex; gap: 8px; margin-top: 12px;
                        padding-top: 12px; border-top: 1px solid var(--border); }}
    .builder-btn {{ padding: 7px 16px; border-radius: 6px; font-size: 12px;
                    font-weight: 600; cursor: pointer; border: 1px solid var(--border);
                    background: var(--surface2); color: var(--text);
                    transition: all 0.12s; }}
    .builder-btn:hover {{ border-color: var(--accent); }}
    .builder-btn-accent {{ background: var(--accent); color: #000;
                           border-color: var(--accent); }}
    .builder-btn-accent:hover {{ opacity: 0.85; }}
    .builder-copied {{ font-size: 11px; color: var(--hit); margin-left: 8px;
                       opacity: 0; transition: opacity 0.2s; }}
    .builder-copied.show {{ opacity: 1; }}

    /* Top Picks section */
    .top-picks-header {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                         letter-spacing: 1.5px; color: var(--accent); margin-bottom: 10px; }}
    .top-picks-grid {{ display: flex; flex-direction: column; gap: 8px; }}
    .top-pick-card {{ background: var(--surface); border: 1px solid var(--border);
                      border-left-width: 4px;
                      border-radius: 10px; padding: 16px 18px;
                      display: grid; grid-template-columns: 1fr auto;
                      gap: 12px; align-items: start; }}
    .tp-left {{ min-width: 0; }}
    .tp-player {{ font-size: 16px; font-weight: 700; }}
    .tp-meta {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}
    .tp-iron-badge {{ display: inline-block; font-size: 10px; font-weight: 700;
                      padding: 2px 7px; border-radius: 4px; margin-top: 6px;
                      background: rgba(34,197,94,0.12); color: var(--hit); }}
    .tp-reasoning {{ font-size: 12px; color: var(--muted); margin-top: 8px;
                     line-height: 1.5; font-style: italic; }}
    .tp-right {{ text-align: right; flex-shrink: 0; }}
    .tp-conf {{ font-size: 12px; font-weight: 700; color: var(--accent); margin-top: 6px; }}
    .top-picks-divider {{ height: 1px; background: var(--border); margin: 20px 0 16px; }}

    /* Best Bets section */
    .best-bets-header {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
                         letter-spacing: 1.5px; color: #2dd4bf; margin-bottom: 10px; }}
    .best-bets-grid {{ display: flex; flex-direction: column; gap: 8px; }}
    .best-bet-card {{ background: var(--surface); border: 1px solid var(--border);
                      border-left: 4px solid #2dd4bf;
                      border-radius: 10px; padding: 16px 18px;
                      display: grid; grid-template-columns: 1fr auto;
                      gap: 12px; align-items: start; }}
    .bb-edge {{ font-size: 13px; font-weight: 700; color: #2dd4bf; margin-top: 4px; }}
    .bb-edge.strong {{ color: #22c55e; }}
    .best-bets-divider {{ height: 1px; background: var(--border); margin: 20px 0 16px; }}

    /* History drawers */
    .history-drawer {{ margin-bottom: 10px; border: 1px solid var(--border); border-radius: 10px; overflow: visible; }}
    .drawer-header {{ background: var(--surface); padding: 12px 16px; cursor: pointer;
      display: flex; justify-content: space-between; align-items: center;
      font-size: 13px; font-weight: 600; user-select: none; }}
    .drawer-header:hover {{ border-color: var(--accent); }}
    .drawer-body {{ padding: 12px 16px 16px; background: var(--bg); overflow-x: auto; }}
    .drawer-chevron {{ font-size: 12px; color: var(--muted); transition: transform 0.2s; }}
    .drawer-chevron.open {{ transform: rotate(180deg); }}
  </style>
</head>
<body>

<header>
  <div class="logo"><span class="logo-nb">NB</span><span class="logo-a">A</span><span class="logo-gent">gent</span></div>
  <div class="built-at">Updated {d["built_at"]}</div>
</header>

<div class="tabs">
  <button class="tab active" onclick="showTab('picks')">Today's Picks</button>
  <button class="tab" onclick="showTab('parlays')">Parlays</button>
  <button class="tab" onclick="showTab('results')">Results</button>
  <button class="tab" onclick="showTab('audit')">Audit Log</button>
  <button class="tab" onclick="showTab('research')">Research</button>
</div>

<button id="back-to-top" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" aria-label="Back to top">↑</button>

<div id="tab-picks" class="page active">
  <div id="injury-container"></div>
  <div id="top-picks-container"></div>
  <div id="best-bets-container"></div>
  <div id="picks-container"></div>
</div>
<div id="tab-parlays" class="page"><div id="parlays-container"></div><div id="parlay-builder-container"></div></div>
<div id="tab-results" class="page">
  <div class="results-cards-row">
    <div class="results-card">
      <div class="results-card-header">Overall</div>
      <div class="results-hero-num" id="overall-pct">—</div>
      <div class="results-hero-sub" id="overall-sub">no graded picks yet</div>
    </div>
    <div class="results-card">
      <div class="results-card-header">Yesterday</div>
      <div class="results-hero-num" id="yesterday-pct">—</div>
      <div class="results-hero-sub" id="yesterday-sub">no audit yet</div>
    </div>
    <div class="results-card">
      <div class="results-card-header">⚡ Top Picks</div>
      <div class="results-hero-num" id="tp-pct">—</div>
      <div class="results-hero-sub" id="tp-sub">need 3+ graded</div>
    </div>
    <div class="results-card">
      <div class="results-card-header">🏆 Playoffs</div>
      <div class="results-hero-num" id="playoff-pct">—</div>
      <div class="results-hero-sub" id="playoff-sub">no playoff picks yet</div>
    </div>
    <div class="results-card results-card-wide">
      <div class="results-card-header">Props</div>
      <div id="prop-streak-grid" class="prop-streak-grid"></div>
    </div>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Daily hit rate — last 30 days</div>
    <canvas id="trend-chart"></canvas>
    <div id="chart-empty" style="display:none;text-align:center;padding:20px;color:var(--muted);font-size:13px">
      Not enough data yet — check back after a few days of picks.
    </div>
  </div>
  <div class="history-drawer">
    <div class="drawer-header" onclick="toggleDrawer('top-picks-drawer')">
      <span>⚡ Top Picks History</span><span class="drawer-chevron" id="top-picks-drawer-chevron">▼</span>
    </div>
    <div class="drawer-body" id="top-picks-drawer" style="display:none">
      <div id="top-picks-history-container"></div>
    </div>
  </div>
  <div class="history-drawer">
    <div class="drawer-header" onclick="toggleDrawer('pick-history-drawer')">
      <span>📋 Pick History</span><span class="drawer-chevron" id="pick-history-drawer-chevron">▼</span>
    </div>
    <div class="drawer-body" id="pick-history-drawer" style="display:none">
      <div id="results-container"></div>
    </div>
  </div>
  <div class="history-drawer">
    <div class="drawer-header" onclick="toggleDrawer('parlay-history-drawer')">
      <span>🎰 Parlay History</span><span class="drawer-chevron" id="parlay-history-drawer-chevron">▼</span>
    </div>
    <div class="drawer-body" id="parlay-history-drawer" style="display:none">
      <div id="parlay-history-container"></div>
    </div>
  </div>
</div>
<div id="tab-audit" class="page"><div id="audit-container"></div></div>
<div id="tab-research" class="page"><div id="research-container"></div></div>

<script>
const DATA = {{
  today_str:        {json.dumps(d["today_str"])},
  today_picks:      {picks_json},
  overall_hit_rate: {d["overall_hit_rate"]},
  total_graded:     {d["total_graded"]},
  prop_stats:       {prop_stats_json},
  daily_trend:      {trend_json},
  last_audit:       {last_audit_json},
  recent_results:   {results_json},
  injuries:         {injuries_json},
  parlays:          {parlays_json},
  ml_odds:          {ml_odds_json},
  top_picks:         {top_picks_json},
  best_bets:         {best_bets_json},
  top_picks_history: {top_picks_history_json},
  playoff_stats:     {playoff_stats_json},
  yesterday_summary: {yesterday_summary_json},
  opportunity_flags: {opportunity_flags_json},
  explorer:          {explorer_json},
  playoff:           {playoff_json},
  cannib_lookup:     {cannib_json},
  corr_lookup:       {corr_json},
}};

function showTab(name) {{
  document.querySelectorAll('.tab').forEach((t,i) =>
    t.classList.toggle('active', ['picks','parlays','results','audit','research'][i] === name));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  if (name === 'results') drawTrendChart();
}}

function propColor(pt) {{
  return {{PTS:'prop-PTS',REB:'prop-REB',AST:'prop-AST','3PM':'prop-3PM'}}[pt]||'';
}}
function propVar(pt) {{
  return {{PTS:'var(--pts)',REB:'var(--reb)',AST:'var(--ast)','3PM':'var(--3pm)'}}[pt]||'var(--muted)';
}}
// Normalize legacy 2-char team abbrevs (e.g. GS→GSW, SA→SAS) that can appear
// in picks.json when analyst.py reads opponent names from nba_master.csv.
// Mirrors _ABBR_NORM in Python — must be kept in sync.
const _ABBR_NORM_JS = {{
  GS:'GSW', NY:'NYK', SA:'SAS', NO:'NOP', UTAH:'UTA', WSH:'WAS', UTH:'UTA'
}};
function normAbbr(a) {{ return _ABBR_NORM_JS[a] || a; }}
function streakPill(s) {{
  if (!s || !s.streak_type || s.streak_count < 5) return '';
  const cls  = s.streak_type==='HIT' ? 'streak-hit' : 'streak-miss';
  const icon = s.streak_type==='HIT' ? '🔥' : '❄️';
  return `<span class="streak-pill ${{cls}}">${{icon}} ${{s.streak_count}} ${{s.streak_type.toLowerCase()}} streak</span>`;
}}

// ── INJURY REPORT ──
function statusClass(s) {{
  if (!s) return 'status-OTHER';
  const u = s.toUpperCase();
  if (u.includes('OUT'))          return 'status-OUT';
  if (u.includes('DOUBT'))        return 'status-DOUBTFUL';
  if (u.includes('QUEST'))        return 'status-QUESTIONABLE';
  if (u.includes('PROB'))         return 'status-PROBABLE';
  return 'status-OTHER';
}}

function toggleTierWalk(btn) {{
  const body = btn.nextElementSibling;
  const open = body.style.display === 'block';
  body.style.display = open ? 'none' : 'block';
  btn.innerHTML = open ? '&#9656; show reasoning' : '&#9662; hide reasoning';
}}

function toggleLineupUpdate(btn) {{
  const body = btn.nextElementSibling;
  const open = body.style.display === 'block';
  body.style.display = open ? 'none' : 'block';
}}

function toggleOddsSizing(btn) {{
  const body = btn.nextElementSibling;
  const open = body.style.display === 'block';
  body.style.display = open ? 'none' : 'block';
  btn.innerHTML = open ? '&#9656; Odds + Sizing' : '&#9662; Odds + Sizing';
}}

function toggleDrawer(id) {{
  const body    = document.getElementById(id);
  const chevron = document.getElementById(id + '-chevron');
  const open    = body.style.display === 'none';
  body.style.display = open ? 'block' : 'none';
  if (chevron) chevron.classList.toggle('open', open);
}}

function toggleInjuries() {{
  const header  = document.getElementById('injury-header');
  const body    = document.getElementById('injury-body');
  const chevron = document.getElementById('injury-chevron');
  const open = body.classList.toggle('open');
  header.classList.toggle('open', open);
  chevron.classList.toggle('open', open);
}}

function renderInjuries() {{
  const c = document.getElementById('injury-container');
  const inj = DATA.injuries;
  if (!inj || !inj.games || !inj.games.length) {{ c.innerHTML = ''; return; }}

  const asOf = inj.fetched_at ? `as of ${{inj.fetched_at}}` : 'latest data';
  let html = `
    <div class="injury-dropdown">
      <div class="injury-header" id="injury-header" onclick="toggleInjuries()">
        <div class="injury-header-left">
          <span class="injury-title">🏥 Injury Report</span>
          <span class="injury-as-of">${{asOf}}</span>
        </div>
        <span class="injury-chevron" id="injury-chevron">▼</span>
      </div>
      <div class="injury-body" id="injury-body">`;

  inj.games.forEach(g => {{
    const gameLabel = `${{g.away}} @ ${{g.home}}${{g.game_time ? ' — ' + g.game_time : ''}}`;
    html += `<div class="injury-game"><div class="injury-game-header">${{gameLabel}}</div>`;
    Object.entries(g.teams).forEach(([team, players]) => {{
      html += `<div class="injury-team-block"><div class="injury-team-name">${{team}}</div>`;
      players.forEach(p => {{
        const name   = p.player_name || p.name || p.player || '?';
        const status = p.status || p.designation || '?';
        const reason = p.reason || p.injury || p.description || '';
        const cls    = statusClass(status);
        const rotCls = p.is_whitelisted === false ? ' injury-player-rotation' : '';
        const rotTag = p.is_whitelisted === false ? ' <span style="font-size:10px;color:var(--muted)">(rotation)</span>' : '';
        html += `
          <div class="injury-player-row${{rotCls}}">
            <span class="injury-player-name">${{name}}${{rotTag}}</span>
            <span class="injury-reason">${{reason}}</span>
            <span class="${{cls}}">${{status.toUpperCase()}}</span>
          </div>`;
      }});
      html += `</div>`;
    }});
    html += `</div>`;
  }});

  html += `</div></div>`;
  c.innerHTML = html;
}}

// ── PICK CARD HELPERS ──
function buildHitRate(p) {{
  const raw = p.hit_rate_display || '';
  if (!raw) return '';
  // Extract only the leading "N/N" fraction — discard any trailing analyst commentary
  const match = raw.match(/^(\d+)\/(\d+)/);
  if (!match) return '';
  const frac = match[1] + '/' + match[2];
  const pct = Math.round(100 * parseInt(match[1]) / parseInt(match[2]));
  const fillColor = pct >= 80 ? 'var(--hit)' : pct >= 70 ? 'var(--accent2)' : 'var(--muted)';
  return `
    <div class="hit-rate-block">
      <span class="hit-rate-fraction">${{frac}}</span><span class="hit-rate-label">L10</span>
      <div class="hit-bar"><div class="hit-fill" style="width:${{pct}}%;background:${{fillColor}}"></div></div>
    </div>`;
}}

// Escape HTML special chars in analyst-generated free-text fields (tier_walk,
// reasoning, rationale). Without this, any '<' or '&' in the text (e.g. the
// analyst writing 'pick<floor') breaks the DOM — the browser parses 'pick<floor'
// as a fake opening tag and swallows subsequent content as attributes, which
// collapses the card grid. Applied to every interpolation of free-text below.
function escapeHtml(s) {{
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}}

function buildMicroStats(p) {{
  const pills = [];
  // Trend
  if (p.trend === 'up')   pills.push(`<span class="micro-pill up">↑ trending</span>`);
  if (p.trend === 'down') pills.push(`<span class="micro-pill down">↓ trending</span>`);
  // Opponent defense
  const def = p.opp_defense_rating;
  if (def === 'soft')  pills.push(`<span class="micro-pill soft">soft def</span>`);
  if (def === 'tough') pills.push(`<span class="micro-pill tough">tough def</span>`);
  if (def === 'mid')   pills.push(`<span class="micro-pill">mid def</span>`);
  if (!pills.length) return '';
  return `<div class="micro-stats">${{pills.join('')}}</div>`;
}}

function buildEdgeLine(p) {{
  const br = p.bet_recommendation;
  if (!br || !br.recommendation_tier || br.recommendation_tier === 'NO_MARKET') return '';
  const tier = br.recommendation_tier;
  const cls = tier.toLowerCase();
  const edge = br.calibrated_edge_pct;
  const edgeStr = edge != null ? ` (${{edge > 0 ? '+' : ''}}${{edge.toFixed(1)}}pp)` : '';
  return `<div class="edge-line ${{cls}}">${{tier}}${{edgeStr}}</div>`;
}}

function buildMovementLine(p) {{
  // Line movement indicator — shows market direction since morning
  // Card face: >3pp moves only. Drawer: all moves >0.5pp via buildOddsSizing.
  if (p.voided) return '';
  const morning = p.morning_implied_prob;
  const current = p.market_implied_prob;
  if (morning == null || current == null) return '';

  const delta = current - morning;
  const absDelta = Math.abs(delta);

  // Dead zone — movement too small to be meaningful
  if (absDelta < 3.0) return '';  // <3pp only in drawer, not card face

  const agrees = delta > 0;  // market prob UP = agrees with our OVER pick
  const arrow = agrees ? '↑' : '↓';
  const label = agrees ? 'Market agrees' : 'Market disagrees';
  const cls = agrees ? 'agrees' : 'disagrees';

  // Prob shift display (rounded to integers for compactness)
  const probStr = `${{Math.round(morning)}}→${{Math.round(current)}}%`;

  // Edge shift — show old edge (strikethrough) → new edge
  const br = p.bet_recommendation || {{}};
  const calProb = br.calibrated_prob;
  let edgeStr = '';
  if (calProb != null) {{
    const morningEdge = (calProb - morning).toFixed(1);
    const currentEdge = (calProb - current).toFixed(1);
    const mSign = morningEdge >= 0 ? '+' : '';
    const cSign = currentEdge >= 0 ? '+' : '';
    edgeStr = ` <span class="edge-shift">edge <s>${{mSign}}${{morningEdge}}</s> → ${{cSign}}${{currentEdge}}pp</span>`;
  }}

  return `<div class="movement-line significant ${{cls}}">${{label}} ${{arrow}}&nbsp; ${{probStr}}${{edgeStr}}</div>`;
}}

// Headline confidence shown on pick cards. Prefers the calibrated probability
// from bet_recommendation (system's actual expected hit rate after historical
// calibration) — falls back to raw confidence_pct when no market data exists.
function displayConf(p) {{
  const br = p.bet_recommendation;
  if (br && br.calibrated_prob != null) {{
    return Math.round(br.calibrated_prob);
  }}
  return p.confidence_pct;
}}

function buildOddsSizing(p) {{
  const br = p.bet_recommendation;
  if (!br || !br.recommendation_tier || br.recommendation_tier === 'NO_MARKET') return '';
  const lines = [];
  // System conf (raw stated confidence) shown alongside calibrated data so the
  // user can see both numbers when they care about the distinction. Only rendered
  // when bet_recommendation exists — otherwise the headline already shows raw conf.
  if (p.confidence_pct != null) lines.push(`<div>System conf: ${{p.confidence_pct}}%</div>`);
  if (p.market_line != null) lines.push(`<div>Market line: ${{p.market_line}}</div>`);
  if (br.market_implied_prob != null) lines.push(`<div>Market prob: ${{br.market_implied_prob.toFixed(1)}}%</div>`);
  if (br.calibration_band) lines.push(`<div>Calibration band: ${{br.calibration_band}}</div>`);
  if (br.calibrated_prob != null) lines.push(`<div>Calibrated prob: ${{br.calibrated_prob.toFixed(1)}}%</div>`);
  if (br.calibrated_edge_pct != null) lines.push(`<div>Edge: ${{br.calibrated_edge_pct > 0 ? '+' : ''}}${{br.calibrated_edge_pct.toFixed(1)}}pp</div>`);
  if (br.kelly_quarter != null) lines.push(`<div>Quarter-Kelly: ${{(br.kelly_quarter * 100).toFixed(1)}}%</div>`);

  // Line movement detail (inside drawer — shows all moves >0.5pp)
  const _morning = p.morning_implied_prob;
  const _current = p.market_implied_prob;
  if (_morning != null && _current != null) {{
    const _delta = _current - _morning;
    const _absDelta = Math.abs(_delta);
    if (_absDelta >= 0.5) {{
      const _dir = _delta > 0 ? 'agrees ↑' : 'disagrees ↓';
      const _color = _delta > 0 ? '#2dd4bf' : '#FF9800';
      lines.push(`<div class="movement-drawer">── Line Movement ──</div>`);
      lines.push(`<div style="color:${{_color}}">Market ${{_dir}} ${{_delta > 0 ? '+' : ''}}${{_delta.toFixed(1)}}pp</div>`);
      lines.push(`<div>Morning prob: ${{_morning.toFixed(1)}}%</div>`);
      lines.push(`<div>Current prob: ${{_current.toFixed(1)}}%</div>`);
      if (br.calibrated_prob != null) {{
        const _mEdge = br.calibrated_prob - _morning;
        const _cEdge = br.calibrated_prob - _current;
        lines.push(`<div>Morning edge: ${{_mEdge > 0 ? '+' : ''}}${{_mEdge.toFixed(1)}}pp</div>`);
        lines.push(`<div>Current edge: ${{_cEdge > 0 ? '+' : ''}}${{_cEdge.toFixed(1)}}pp</div>`);
      }}
    }}
  }}

  const alts = p.alt_tiers || [];
  if (alts.length) {{
    lines.push(`<div class="alt-tiers-header">── Alt Tiers (FanDuel) ──</div>`);
    alts.forEach(a => {{
      const gap = a.hit_pct - a.mkt_prob;
      const cls = gap >= 5 ? 'alt-tier-row has-edge' : 'alt-tier-row';
      lines.push(`<div class="${{cls}}">T${{a.tier}}&nbsp;&nbsp;${{a.line}} OVER&nbsp;&nbsp;mkt ${{a.mkt_prob}}%&nbsp;&nbsp;hit ${{a.hits}}/${{a.games}} (${{a.hit_pct}}%)</div>`);
    }});
  }}

  if (!lines.length) return '';
  return `<button class="odds-sizing-toggle" onclick="toggleOddsSizing(this)">&#9656; Odds + Sizing</button>` +
    `<div class="odds-sizing-body">${{lines.join('')}}</div>`;
}}

// ── TODAY'S PICKS ──
function renderPicks() {{
  const c = document.getElementById('picks-container');
  const picks = DATA.today_picks;
  if (!picks.length) {{
    c.innerHTML = `<div class="empty"><div class="empty-icon">🏀</div>No picks yet for ${{DATA.today_str}}.<br>Check back after 8 AM PT.</div>`;
    return;
  }}

  // Build a game key → metadata map, preserving tip-off sort order
  const gameMap = {{}};
  picks.forEach(p => {{
    const ha = p.home_away === 'H' ? 'H' : 'A';
    // Normalize: always store as "AWAY @ HOME"
    const home = ha === 'H' ? p.team : p.opponent;
    const away = ha === 'A' ? p.team : p.opponent;
    const key  = `${{away}}@${{home}}`;
    if (!gameMap[key]) {{
      gameMap[key] = {{
        key, home, away,
        game_time: p.game_time || '',
        picks: []
      }};
    }}
    gameMap[key].picks.push(p);
  }});

  // Sort games by tip-off time (TBD goes last)
  function timeToMinutes(t) {{
    if (!t || t === 'TBD') return 9999;
    const m = t.match(/(\d+):(\d+)\s*(AM|PM)/i);
    if (!m) return 9999;
    let h = parseInt(m[1]), min = parseInt(m[2]);
    if (m[3].toUpperCase() === 'PM' && h !== 12) h += 12;
    if (m[3].toUpperCase() === 'AM' && h === 12) h = 0;
    return h * 60 + min;
  }}
  const games = Object.values(gameMap).sort((a,b) =>
    timeToMinutes(a.game_time) - timeToMinutes(b.game_time));

  const ps = DATA.prop_stats;
  const voidedCount = picks.filter(p => p.voided).length;
  const activeCount = picks.length - voidedCount;
  const voidedNote  = voidedCount > 0 ? ` <span style="color:var(--miss);font-size:12px">(${{voidedCount}} voided)</span>` : '';
  let html = `<div class="section-header">${{activeCount}} pick${{activeCount!==1?'s':''}}${{voidedNote}} — ${{DATA.today_str}}</div>`;

  games.forEach((g, gi) => {{
    const timeTag  = g.game_time ? `<span class="game-tip">⏰ ${{g.game_time}}</span>` : '';
    const ml       = DATA.ml_odds || {{}};
    const awayLabel = normAbbr(g.away);
    const homeLabel = normAbbr(g.home);
    const awayPct  = ml[awayLabel] !== undefined ? ` <span class="ml-pct">(${{ml[awayLabel]}}%)</span>` : '';
    const homePct  = ml[homeLabel] !== undefined ? ` <span class="ml-pct">(${{ml[homeLabel]}}%)</span>` : '';
    const gid = `game-${{gi}}`;
    html += `
      <div class="game-group">
        <div class="game-group-header open" id="hdr-${{gid}}" onclick="toggleGame('${{gid}}')">
          <span class="game-matchup">${{awayLabel}}${{awayPct}} @ ${{homeLabel}}${{homePct}}</span>
          ${{timeTag}}
          <span class="game-pick-count">${{g.picks.length}} pick${{g.picks.length!==1?'s':''}}</span>
          <span class="game-chevron open" id="chv-${{gid}}">▼</span>
        </div>
        <div class="game-body open" id="body-${{gid}}">
          <div class="picks-grid">`;

    // Sort picks within game by prop type order, then confidence desc
    const propOrder = {{'PTS':0,'REB':1,'AST':2,'3PM':3}};
    g.picks.sort((a,b) =>
      (propOrder[a.prop_type]??9) - (propOrder[b.prop_type]??9) ||
      b.confidence_pct - a.confidence_pct
    ).forEach(p => {{
      const pt         = p.prop_type;
      const ha         = p.home_away === 'H' ? 'vs' : '@';
      const voidedCls  = p.voided ? ' voided' : '';
      const reviewVerdict = p.human_verdict || '';
      const isAutoReview  = p.auto_reviewed === true;
      const reviewBadge = reviewVerdict === 'manual_skip'
        ? `<span class="review-badge-skip">${{isAutoReview ? '🤖 Stay Away' : '⚠ Flagged'}}</span>`
        : '';
      const reviewReasons = (p.trim_reasons && p.trim_reasons.length && reviewVerdict === 'manual_skip')
        ? `<span style="font-size:10px;color:var(--muted);margin-left:4px">${{escapeHtml(p.trim_reasons.join(' · '))}}</span>`
        : '';
      const reviewHtml = reviewBadge
        ? `<div style="margin-top:4px">${{reviewBadge}}${{reviewReasons}}</div>`
        : '';
      const statusBadge = p.voided
        ? `<div style="margin-top:4px"><span class="void-badge">VOIDED — Player OUT</span></div>`
        : p.lineup_risk === 'high'
          ? `<div style="margin-top:4px"><span class="risk-badge-high">⚠ DOUBTFUL</span></div>`
          : p.lineup_risk === 'moderate'
            ? `<div style="margin-top:4px"><span class="risk-badge-moderate">QUESTIONABLE</span></div>`
            : '';
      html += `
        <div class="pick-card${{voidedCls}}">
          <div class="pick-main">
            <div class="player">${{p.player_name}}</div>
            ${{statusBadge}}
            ${{reviewHtml}}
            ${{buildMicroStats(p)}}
            ${{p.reasoning ? `<div class="reasoning">${{escapeHtml(p.reasoning)}}</div>` : ''}}
            ${{(function() {{
              const lu = p.lineup_update;
              if (!lu || lu.direction === 'unchanged') return '';
              const cls = lu.direction === 'up' ? 'lineup-update-badge-up' : 'lineup-update-badge-down';
              const arrow = lu.direction === 'up' ? '↑' : '↓';
              const timeStr = lu.updated_at ? new Date(lu.updated_at).toLocaleTimeString('en-US', {{hour:'numeric',minute:'2-digit'}}) : '';
              const triggered = (lu.triggered_by || []).join('; ');
              return `<button class="${{cls}}" onclick="toggleLineupUpdate(this)">${{arrow}} Updated ${{timeStr}}</button>` +
                `<div class="lineup-update-body">Triggered by: ${{escapeHtml(triggered)}}<br>` +
                `Revised (${{lu.revised_confidence_pct}}%): ${{escapeHtml(lu.revised_reasoning)}}<br>` +
                `Morning (${{p.confidence_pct}}%): ${{escapeHtml(p.reasoning)}}</div>`;
            }})()}}
            ${{buildMovementLine(p)}}
            ${{buildOddsSizing(p)}}
            ${{p.tier_walk ? `<button class="tier-walk-toggle" onclick="toggleTierWalk(this)">&#9656; show reasoning</button><div class="tier-walk tier-walk-body">${{escapeHtml(p.tier_walk)}}</div>` : ''}}
          </div>
          <div class="pick-right">
            <div class="pick-line">
              ${{p.pick_value}}<span class="stat-type ${{propColor(pt)}}">${{pt}}</span>
            </div>
            ${{buildHitRate(p)}}
            <div class="conf-line">${{displayConf(p)}}% conf</div>
            ${{buildEdgeLine(p)}}
          </div>
        </div>`;
    }});

    html += `</div></div></div>`;
  }});

  // ── Opportunity flags — amber/blue cards below main picks ───────────────
  const voidedNames = new Set((DATA.today_picks || []).filter(p => p.voided).map(p => (p.player_name || '').toLowerCase()));
  const opps = (DATA.opportunity_flags || []).filter(f => f.date === DATA.today_str && !voidedNames.has((f.player_name || '').toLowerCase()));
  if (opps.length) {{
    html += `<div class="section-header" style="margin-top:24px;color:#F5A623;">⚡ OPPORTUNITIES — Late-Scratch Pickups</div>`;
    opps.forEach(opp => {{
      const triggeredBy = opp.triggered_by || 'Unknown absence';
      const sideLabel   = opp.side === 'opponent' ? ' (opp)' : '';
      const cardType    = opp.card_type || 'new_pick';

      // New-pick rows (qualifying_tiers)
      const qtiers  = opp.qualifying_tiers || {{}};
      const qtLines = Object.entries(qtiers).map(([stat, info]) => {{
        const hr  = info.hit_rate_pct !== undefined ? `${{info.hit_rate_pct}}%` : '';
        const whr = info.without_player_hit_rate_pct !== undefined
          ? ` · ${{info.without_player_hit_rate_pct}}% w/o ${{triggeredBy.split(' ').pop()}}`
          : '';
        const mkt = (info.market_implied_pct !== undefined && info.market_implied_pct !== null)
          ? ` <span style="color:${{info.market_implied_pct <= (info.hit_rate_pct || 0) ? '#4CAF50' : '#FF9800'}};font-size:10px">(mkt ${{Math.round(info.market_implied_pct)}}%)</span>`
          : '';
        return `<div style="margin:3px 0"><span style="color:#F5A623;font-weight:600">${{stat}} T${{info.tier}}</span>` +
               ` <span style="color:var(--muted);font-size:11px">${{hr}}${{whr}}</span>${{mkt}}</div>`;
      }}).join('');

      // Upgrade rows (upgrade_tiers — existing pick, higher tier now available)
      const utiers  = opp.upgrade_tiers || {{}};
      const utLines = Object.entries(utiers).map(([stat, info]) => {{
        const hr      = info.hit_rate_pct !== undefined ? ` ${{info.hit_rate_pct}}%` : '';
        const morning = info.morning_tier !== undefined ? `T${{info.morning_tier}}→` : '';
        const mkt = (info.market_implied_pct !== undefined && info.market_implied_pct !== null)
          ? ` <span style="color:${{info.market_implied_pct <= (info.hit_rate_pct || 0) ? '#4CAF50' : '#FF9800'}};font-size:10px">(mkt ${{Math.round(info.market_implied_pct)}}%)</span>`
          : '';
        return `<div style="margin:3px 0"><span style="color:#64B5F6;font-weight:600">${{stat}} ${{morning}}T${{info.tier}}</span>` +
               ` <span style="color:var(--muted);font-size:11px">${{hr}} (upgrade)</span>${{mkt}}</div>`;
      }}).join('');

      const tierContent = (qtLines + utLines) ||
        `<span style="color:var(--muted)">No qualifying tiers</span>`;

      const rightColor = cardType === 'upgrade' ? '#64B5F6' : '#F5A623';
      const rightLabel = cardType === 'upgrade' ? 'UPGRADE' : cardType === 'mixed' ? 'MIXED' : 'OPPORTUNITY';
      const rightSub   = cardType === 'upgrade' ? 'Better tier<br>available'
                       : cardType === 'mixed'   ? 'New + upgrade'
                       :                          'Not picked<br>this morning';

      html += `
        <div class="pick-card" style="border-color:${{rightColor}};border-left-width:4px;">
          <div class="pick-main">
            <div class="player">${{opp.player_name}} <span style="font-size:11px;color:var(--muted)">(${{opp.team}})</span></div>
            <div style="margin:4px 0;font-size:12px;color:var(--muted)">↗ Triggered by: ${{triggeredBy}}${{sideLabel}}</div>
            <div style="margin-top:4px;font-size:12px;">${{tierContent}}</div>
          </div>
          <div class="pick-right">
            <div style="font-size:11px;color:${{rightColor}};font-weight:700;text-align:center;margin-bottom:4px;">${{rightLabel}}</div>
            <div style="font-size:11px;color:var(--muted);text-align:center;">${{rightSub}}</div>
          </div>
        </div>`;
    }});
  }}

  c.innerHTML = html;
}}

// ── RESULTS ──
function renderResults() {{
  // ── Overall card ──
  document.getElementById('overall-pct').textContent =
    DATA.total_graded ? DATA.overall_hit_rate + '%' : '—';
  document.getElementById('overall-sub').textContent =
    DATA.total_graded ? `${{DATA.total_graded}} picks graded` : 'no graded picks yet';

  // ── Yesterday card ──
  const la = DATA.last_audit;
  if (la && la.total_picks > 0) {{
    const laVoids   = la.voided_picks || 0;
    const laValid   = (la.hits || 0) + (la.misses || 0);
    const laHitRate = laValid > 0 ? Math.round(10 * 100 * la.hits / laValid) / 10 : 0;
    document.getElementById('yesterday-pct').textContent = laHitRate + '%';
    const voidedStr = laVoids > 0 ? ` · ${{laVoids}} voided` : '';
    document.getElementById('yesterday-sub').textContent =
      `${{la.hits}} hits / ${{laValid}} valid picks${{voidedStr}}`;
  }}

  // ── Top Picks card ──
  const tph = DATA.top_picks_history;
  if (tph && tph.total >= 3) {{
    document.getElementById('tp-pct').textContent = tph.pct + '%';
    document.getElementById('tp-sub').textContent = `${{tph.hits}}/${{tph.total}} top picks`;
  }}

  // ── Playoffs card ──
  const ps2 = DATA.playoff_stats;
  if (ps2 && ps2.total > 0) {{
    document.getElementById('playoff-pct').textContent = ps2.pct + '%';
    const voidedStr = ps2.voided > 0 ? ` · ${{ps2.voided}} voided` : '';
    document.getElementById('playoff-sub').textContent =
      `${{ps2.hits}} hits / ${{ps2.total}} valid picks${{voidedStr}}`;
  }}

  // ── Props card ──
  const ps  = DATA.prop_stats;
  const grid = document.getElementById('prop-streak-grid');
  let gh = '';
  ['PTS','REB','AST','3PM'].forEach(pt => {{
    const s = ps[pt]||{{}};
    if (!s.total) return;
    const col = propVar(pt);
    gh += `
      <div class="prop-streak-card">
        <div class="psc-label"><span>${{pt}}</span><span style="color:${{col}};font-weight:700">${{s.pct}}%</span></div>
        <div class="psc-pct" style="color:${{col}}">${{s.last10_hits}}/${{s.last10_total}}</div>
        <div class="psc-sub">last ${{s.last10_total}} picks</div>
        ${{s.streak_type ? `<div style="margin-top:6px">${{streakPill(s)}}</div>` : ''}}
      </div>`;
  }});
  grid.innerHTML = gh;

  // ── Pick History drawer ──
  const c = document.getElementById('results-container');
  const results = DATA.recent_results;
  if (!results.length) {{
    c.innerHTML = `<div class="empty"><div class="empty-icon">📊</div>No graded results yet.</div>`;
  }} else {{
    let html = `<table class="history-table"><thead><tr>
      <th>Date</th><th>Player</th><th>Prop</th><th>Pick</th><th>Actual</th><th>Result</th>
    </tr></thead><tbody>`;
    results.forEach(p => {{
      const res = p.result==='HIT'
        ? `<span class="result-hit">✓ HIT</span>`
        : p.result==='MISS'
        ? `<span class="result-miss">✗ MISS</span>`
        : `<span class="result-nd">—</span>`;
      const bs = `width:32px;height:18px;border-radius:4px;font-size:9px;display:inline-flex;align-items:center;justify-content:center`;
      const d = p.date ? p.date.split('-') : ['','',''];
      const fmt = d.length===3 ? `${{parseInt(d[1])}}/${{parseInt(d[2])}}/${{d[0].slice(2)}}` : p.date;
      const tp = p.top_pick ? ' ⚡' : '';
      html += `<tr>
        <td style="white-space:nowrap">${{fmt}}</td>
        <td><strong>${{p.player_name}}${{tp}}</strong><br><span style="font-size:11px;color:var(--muted)">${{p.team}}</span></td>
        <td><span class="prop-badge ${{propColor(p.prop_type)}}" style="${{bs}}">${{p.prop_type}}</span></td>
        <td style="white-space:nowrap">${{p.pick_value}}</td>
        <td>${{p.actual_value??'—'}}</td>
        <td>${{res}}</td>
      </tr>`;
    }});
    html += '</tbody></table>';
    c.innerHTML = html;
  }}

  // ── Top Picks History drawer ──
  const tpContainer = document.getElementById('top-picks-history-container');
  if (tpContainer) {{
    const tpPicks = (DATA.top_picks_history || {{}}).picks || [];
    if (!tpPicks.length) {{
      tpContainer.innerHTML = '<div class="empty">No graded Top Picks yet.</div>';
    }} else {{
      let tpHtml = `<table class="history-table"><thead><tr>
        <th>Date</th><th>Player</th><th>Prop</th><th>Pick</th><th>Actual</th><th>Conf</th><th>Result</th>
      </tr></thead><tbody>`;
      tpPicks.forEach(p => {{
        const d = p.date ? p.date.split('-') : ['','',''];
        const fmt = d.length===3 ? `${{parseInt(d[1])}}/${{parseInt(d[2])}}/${{d[0].slice(2)}}` : p.date;
        const res = p.result==='HIT'
          ? `<span class="result-hit">✓ HIT</span>`
          : `<span class="result-miss">✗ MISS</span>`;
        const bs = `width:32px;height:18px;border-radius:4px;font-size:9px;display:inline-flex;align-items:center;justify-content:center`;
        tpHtml += `<tr>
          <td style="white-space:nowrap">${{fmt}}</td>
          <td><strong>⚡ ${{p.player_name}}</strong><br><span style="font-size:11px;color:var(--muted)">${{p.team}}</span></td>
          <td><span class="prop-badge ${{propColor(p.prop_type)}}" style="${{bs}}">${{p.prop_type}}</span></td>
          <td style="white-space:nowrap">${{p.pick_value}}</td>
          <td>${{p.actual_value??'—'}}</td>
          <td style="font-size:11px;color:var(--muted)">${{p.confidence_pct}}%</td>
          <td>${{res}}</td>
        </tr>`;
      }});
      tpHtml += '</tbody></table>';
      tpContainer.innerHTML = tpHtml;
    }}
  }}

  // ── Parlay History drawer ──
  const phContainer = document.getElementById('parlay-history-container');
  if (phContainer) {{
    const parlayHistory = (DATA.parlays || {{}}).history || [];
    if (!parlayHistory.length) {{
      phContainer.innerHTML = '<div class="empty">No graded parlays yet.</div>';
    }} else {{
      let phHtml = '';
      parlayHistory.forEach(p => {{
        const d = p.date ? p.date.split('-') : ['','',''];
        const fmt = d.length===3 ? `${{parseInt(d[1])}}/${{parseInt(d[2])}}/${{d[0].slice(2)}}` : p.date;
        let resultBadge = '';
        if (p.result==='HIT')       resultBadge = `<span class="parlay-result-hit">✓ HIT</span>`;
        else if (p.result==='MISS') resultBadge = `<span class="parlay-result-miss">✗ MISS</span>`;
        const legs = (p.leg_results || []).map(l => {{
          const lr = l.result==='HIT' ? `<span class="result-hit">✓</span>` : `<span class="result-miss">✗</span>`;
          return `<div style="font-size:11px;padding:2px 0">${{lr}} ${{l.player_name}} ${{l.prop_type}} OVER ${{l.pick_value}} → ${{l.actual_value??'—'}}</div>`;
        }}).join('');
        phHtml += `
          <div style="border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
              <span style="font-size:12px;font-weight:600">${{p.label||'Parlay'}}</span>
              <span style="display:flex;gap:8px;align-items:center">
                <span style="font-size:11px;color:var(--muted)">${{fmt}}</span>
                ${{resultBadge}}
              </span>
            </div>
            ${{legs}}
          </div>`;
      }});
      phContainer.innerHTML = phHtml;
    }}
  }}
}}

// ── TREND CHART (vanilla canvas, no deps) ──
function drawTrendChart() {{
  const trend  = DATA.daily_trend;
  const canvas = document.getElementById('trend-chart');
  const empty  = document.getElementById('chart-empty');
  if (!trend || trend.length < 2) {{
    canvas.style.display = 'none';
    if (empty) empty.style.display = 'block';
    return;
  }}

  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.clientWidth - 32;
  const H = 160;
  canvas.width  = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W+'px'; canvas.style.height = H+'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const pad = {{t:14, r:10, b:28, l:38}};
  const cw = W-pad.l-pad.r, ch = H-pad.t-pad.b;

  // ── Dynamic Y-axis ─────────────────────────────────────────────────────────
  // Normal floor: 65% (buffer below 70% target line).
  // If any data point dips below 65%, extend floor to 5pp below the minimum.
  const TARGET = 70;
  const minPct = Math.min(...trend.map(d => d.pct));
  const maxPct = Math.max(...trend.map(d => d.pct));
  const yFloor = minPct < 65 ? Math.floor(minPct / 5) * 5 - 5 : 65;
  const yCeil  = Math.min(100, Math.ceil((maxPct + 3) / 5) * 5);  // headroom above max, cap 100%
  const yRange = yCeil - yFloor;

  // Map a pct value to canvas y
  const toY = pct => pad.t + ch - ((pct - yFloor) / yRange) * ch;

  // ── Grid + y-axis labels ───────────────────────────────────────────────────
  // Choose grid lines: always include TARGET; add floor, ceil, and midpoint
  const rawGridLines = new Set([yFloor, TARGET, yCeil]);
  // Add a mid grid line if gap is big enough
  const mid = Math.round((yFloor + yCeil) / 2 / 5) * 5;
  if (mid !== TARGET && mid !== yFloor && mid !== yCeil) rawGridLines.add(mid);
  const gridLines = [...rawGridLines].sort((a,b)=>a-b);

  gridLines.forEach(pct => {{
    const y = toY(pct);
    ctx.strokeStyle = pct === TARGET ? 'rgba(232,112,58,0.0)' : '#2a2a32';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(pad.l+cw,y); ctx.stroke();
    ctx.fillStyle='#888898'; ctx.font='9px system-ui'; ctx.textAlign='right';
    ctx.fillText(pct+'%', pad.l-4, y+3);
  }});

  // ── 70% target dashed line ────────────────────────────────────────────────
  const ty = toY(TARGET);
  ctx.strokeStyle='rgba(232,112,58,0.5)'; ctx.setLineDash([3,4]); ctx.lineWidth=1;
  ctx.beginPath(); ctx.moveTo(pad.l,ty); ctx.lineTo(pad.l+cw,ty); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle='rgba(232,112,58,0.7)'; ctx.font='9px system-ui'; ctx.textAlign='left';
  ctx.fillText('target 70%', pad.l+4, ty-3);

  // ── Data points ────────────────────────────────────────────────────────────
  const pts = trend.map((d,i) => ({{
    x: pad.l + (trend.length>1 ? i/(trend.length-1) : 0.5)*cw,
    y: toY(d.pct),
    pct: d.pct, date: d.date
  }}));

  // Fill
  const grad = ctx.createLinearGradient(0,pad.t,0,pad.t+ch);
  grad.addColorStop(0,'rgba(0,212,170,0.2)'); grad.addColorStop(1,'rgba(0,212,170,0)');
  ctx.beginPath(); ctx.moveTo(pts[0].x, pad.t+ch);
  pts.forEach(p => ctx.lineTo(p.x,p.y));
  ctx.lineTo(pts[pts.length-1].x, pad.t+ch); ctx.closePath();
  ctx.fillStyle=grad; ctx.fill();

  // Line
  ctx.beginPath(); ctx.strokeStyle='#00d4aa'; ctx.lineWidth=2; ctx.lineJoin='round';
  pts.forEach((p,i) => i===0 ? ctx.moveTo(p.x,p.y) : ctx.lineTo(p.x,p.y));
  ctx.stroke();

  // Dots
  pts.forEach(p => {{
    ctx.beginPath(); ctx.arc(p.x,p.y,3,0,Math.PI*2);
    ctx.fillStyle = p.pct>=TARGET ? '#00d4aa' : '#ef4444';
    ctx.fill();
  }});

  // X-axis date labels
  ctx.fillStyle='#888898'; ctx.font='9px system-ui'; ctx.textAlign='center';
  [0, Math.floor((trend.length-1)/2), trend.length-1].forEach(i => {{
    ctx.fillText(trend[i].date.slice(5), pts[i].x, H-6);
  }});
}}

// Responsive: redraw on container resize
(function() {{
  const canvas = document.getElementById('trend-chart');
  if (!canvas) return;
  let lastW = 0;
  const ro = new ResizeObserver(() => {{
    const w = canvas.parentElement.clientWidth;
    if (Math.abs(w - lastW) > 4) {{ lastW = w; drawTrendChart(); }}
  }});
  ro.observe(canvas.parentElement);
}})();

// ── AUDIT ──
function renderAudit() {{
  const c = document.getElementById('audit-container');
  const a = DATA.last_audit;
  if (!a) {{
    c.innerHTML = `<div class="empty"><div class="empty-icon">🔍</div>No audit data yet.<br>The Auditor runs each morning after box scores are ingested.</div>`;
    return;
  }}
  let html = `
    <div class="audit-card">
      <h3>Last Audit — ${{a.date}}</h3>
      ${{(()=>{{
        const aVoids = a.voided_picks || 0;
        const aValid = (a.hits || 0) + (a.misses || 0);
        const aHitRate = aValid > 0 ? Math.round(10 * 100 * a.hits / aValid) / 10 : 0;
        return `<div style="display:flex;gap:24px;flex-wrap:wrap">
          <div><div style="font-size:11px;color:var(--muted)">Hit Rate</div><div style="font-size:24px;font-weight:700;color:var(--accent2)">${{aHitRate}}%</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Total</div><div style="font-size:24px;font-weight:700">${{aValid}}</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Hits</div><div style="font-size:24px;font-weight:700;color:var(--hit)">${{a.hits}}</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Misses</div><div style="font-size:24px;font-weight:700;color:var(--miss)">${{a.misses}}</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Voids</div><div style="font-size:24px;font-weight:700;color:var(--muted)">${{aVoids}}</div></div>
        </div>`;
      }})()}}
    </div>`;
  if (a.reinforcements?.length) {{
    html += `<div class="audit-card"><h3>✓ What Worked</h3><ul class="audit-list">`;
    a.reinforcements.forEach(r => html += `<li>${{r}}</li>`);
    html += `</ul></div>`;
  }}
  if (a.lessons?.length) {{
    html += `<div class="audit-card"><h3>✗ What to Avoid</h3><ul class="audit-list">`;
    a.lessons.forEach(l => html += `<li>${{l}}</li>`);
    html += `</ul></div>`;
  }}
  if (a.recommendations?.length) {{
    html += `<div class="audit-card"><h3>→ Analyst Instructions</h3><ul class="audit-list">`;
    a.recommendations.forEach(r => html += `<li>${{r}}</li>`);
    html += `</ul></div>`;
  }}
  const pr = a.parlay_results || {{}};
  const parlayHits    = pr.hits ?? 0;
  const parlayTotal   = pr.total ?? 0;
  const parlaySummary = pr.parlay_summary || '';
  const parlayLessons = pr.parlay_lessons || [];
  const parlayReinf   = pr.parlay_reinforcements || [];
  if (parlayTotal > 0) {{
    let phtml = `<div class="audit-card">
      <h3>🎰 Parlay Results — ${{parlayHits}}/${{parlayTotal}} hit</h3>`;
    if (parlaySummary) {{
      phtml += `<div style="font-size:13px;color:var(--muted);margin-bottom:10px;font-style:italic">${{parlaySummary}}</div>`;
    }}
    if (parlayReinf.length) {{
      phtml += `<div style="font-size:12px;font-weight:600;color:var(--hit);margin-bottom:4px">✓ What worked</div>
        <ul class="audit-list">`;
      parlayReinf.forEach(r => phtml += `<li>${{r}}</li>`);
      phtml += `</ul>`;
    }}
    if (parlayLessons.length) {{
      phtml += `<div style="font-size:12px;font-weight:600;color:var(--miss);margin-top:8px;margin-bottom:4px">✗ Notes for next card</div>
        <ul class="audit-list">`;
      parlayLessons.forEach(l => phtml += `<li>${{l}}</li>`);
      phtml += `</ul>`;
    }}
    phtml += `</div>`;
    html += phtml;
  }}
  c.innerHTML = html;
}}

// ── COLLAPSIBLE GAME GROUPS ──
function toggleGame(gid) {{
  const hdr  = document.getElementById('hdr-'  + gid);
  const body = document.getElementById('body-' + gid);
  const chv  = document.getElementById('chv-'  + gid);
  const open = body.classList.toggle('open');
  hdr.classList.toggle('open', open);
  chv.classList.toggle('open', open);
}}

// ── BACK TO TOP ──
(function() {{
  const btn = document.getElementById('back-to-top');
  window.addEventListener('scroll', function() {{
    btn.classList.toggle('visible', window.scrollY > 300);
  }}, {{passive: true}});
}})();

// ── TOP PICKS ──
function renderTopPicks() {{
  const c = document.getElementById('top-picks-container');
  const tops = DATA.top_picks || [];
  if (!tops.length) {{ c.innerHTML = ''; return; }}

  const STAT_COLOR = {{
    PTS: 'var(--pts)', REB: 'var(--reb)',
    AST: 'var(--ast)', '3PM': 'var(--3pm)'
  }};

  let html = `<div class="top-picks-header">⚡ TOP PICKS</div>
              <div class="top-picks-grid">`;

  tops.forEach(p => {{
    const pt        = p.prop_type || '';
    const color     = STAT_COLOR[pt] || 'var(--muted)';
    const gameTime  = p.game_time ? ` · ${{p.game_time}}` : '';
    const ironBadge = p.iron_floor
      ? `<div><span class="tp-iron-badge">🔒 Iron Floor</span></div>` : '';
    const reasoning = p.reasoning
      ? `<div class="tp-reasoning">${{escapeHtml(p.reasoning)}}</div>` : '';
    const tierWalk = p.tier_walk
      ? `<button class="tier-walk-toggle" onclick="toggleTierWalk(this)">&#9656; show reasoning</button><div class="tier-walk tier-walk-body">${{escapeHtml(p.tier_walk)}}</div>` : '';
    const lineupUpdateBadge = (function() {{
      const lu = p.lineup_update;
      if (!lu || lu.direction === 'unchanged') return '';
      const cls = lu.direction === 'up' ? 'lineup-update-badge-up' : 'lineup-update-badge-down';
      const arrow = lu.direction === 'up' ? '↑' : '↓';
      const timeStr = lu.updated_at ? new Date(lu.updated_at).toLocaleTimeString('en-US', {{hour:'numeric',minute:'2-digit'}}) : '';
      const triggered = (lu.triggered_by || []).join('; ');
      return `<button class="${{cls}}" onclick="toggleLineupUpdate(this)">${{arrow}} Updated ${{timeStr}}</button>` +
        `<div class="lineup-update-body">Triggered by: ${{escapeHtml(triggered)}}<br>` +
        `Revised (${{lu.revised_confidence_pct}}%): ${{escapeHtml(lu.revised_reasoning)}}<br>` +
        `Morning (${{p.confidence_pct}}%): ${{escapeHtml(p.reasoning)}}</div>`;
    }})();

    html += `
      <div class="top-pick-card" style="border-left-color:${{color}}">
        <div class="tp-left">
          <div class="tp-player">${{p.player_name}}</div>
          <div class="tp-meta">${{p.team}}${{gameTime}}</div>
          ${{ironBadge}}
          ${{reasoning}}
          ${{lineupUpdateBadge}}
          ${{buildOddsSizing(p)}}
          ${{tierWalk}}
        </div>
        <div class="tp-right">
          <div class="pick-line">
            ${{p.pick_value}}<span class="stat-type ${{propColor(pt)}}">${{pt}}</span>
          </div>
          <div class="tp-conf">${{displayConf(p)}}% conf</div>
          ${{buildEdgeLine(p)}}
        </div>
      </div>`;
  }});

  html += `</div><div class="top-picks-divider"></div>`;
  c.innerHTML = html;
}}

function renderBestBets() {{
  const c = document.getElementById('best-bets-container');
  const bets = DATA.best_bets || [];
  if (!bets.length) {{ c.innerHTML = ''; return; }}

  const STAT_COLOR = {{
    PTS: 'var(--pts)', REB: 'var(--reb)',
    AST: 'var(--ast)', '3PM': 'var(--3pm)'
  }};

  let html = `<div class="best-bets-header">💰 BEST BETS</div>
              <div class="best-bets-grid">`;

  bets.forEach(p => {{
    const pt       = p.prop_type || '';
    const br       = p.bet_recommendation || {{}};
    const edgePct  = br.calibrated_edge_pct;
    const tier     = br.recommendation_tier || '';
    const edgeStr  = edgePct != null ? `+${{edgePct.toFixed(1)}}pp edge` : '';
    const edgeCls  = tier === 'STRONG' ? 'strong' : '';
    const borderColor = tier === 'STRONG' ? '#22c55e' : '#2dd4bf';
    const gameTime = p.game_time ? ` · ${{p.game_time}}` : '';
    const reasoning = p.reasoning
      ? `<div class="tp-reasoning">${{escapeHtml(p.reasoning)}}</div>` : '';
    const tierWalk = p.tier_walk
      ? `<button class="tier-walk-toggle" onclick="toggleTierWalk(this)">&#9656; show reasoning</button><div class="tier-walk tier-walk-body">${{escapeHtml(p.tier_walk)}}</div>` : '';

    html += `
      <div class="best-bet-card" style="border-left-color:${{borderColor}}">
        <div class="tp-left">
          <div class="tp-player">${{p.player_name}}</div>
          <div class="tp-meta">${{p.team}}${{gameTime}}</div>
          ${{reasoning}}
          ${{buildOddsSizing(p)}}
          ${{tierWalk}}
        </div>
        <div class="tp-right">
          <div class="pick-line">
            ${{p.pick_value}}<span class="stat-type ${{propColor(pt)}}">${{pt}}</span>
          </div>
          <div class="tp-conf">${{displayConf(p)}}% conf</div>
          <div class="bb-edge ${{edgeCls}}">${{edgeStr}}</div>
        </div>
      </div>`;
  }});

  html += `</div><div class="best-bets-divider"></div>`;
  c.innerHTML = html;
}}

renderInjuries();
renderTopPicks();
renderBestBets();
renderPicks();
renderResults();
renderAudit();

// ── PARLAYS ──
function renderParlayCard(p, voidedPlayerNames) {{
  const legs = p.legs || [];
  const odds = p.implied_odds || '';

  // Voided legs risk banner (preserved)
  const voidedLegs = legs.filter(leg =>
    voidedPlayerNames.has((leg.player_name || '').toLowerCase())
  );
  const riskBanner = voidedLegs.length > 0
    ? `<div class="parlay-risk-banner">⚠ ${{voidedLegs.map(l => l.player_name).join(', ')}} listed OUT — parlay affected</div>`
    : '';

  // Header-right indicator: result badge after grading, else odds
  let headerRight = '';
  if (p.result === 'HIT') {{
    headerRight = `<span class="parlay-result-hit">✓ HIT</span>`;
  }} else if (p.result === 'MISS') {{
    headerRight = `<span class="parlay-result-miss">✗ MISS</span>`;
  }} else if (p.result === 'PARTIAL') {{
    headerRight = `<span class="parlay-result-partial">~ PARTIAL</span>`;
  }} else {{
    headerRight = `<span class="parlay-odds">${{odds}}</span>`;
  }}

  let html = `
    <div class="parlay-card">
      ${{riskBanner}}
      <div class="parlay-card-header-lean">
        <div class="parlay-header-spacer"></div>
        <div class="parlay-header-right">${{headerRight}}</div>
      </div>
      <div class="parlay-legs">`;

  legs.forEach((leg, legIdx) => {{
    const pt   = leg.prop_type || leg.prop || '';
    const team = leg.team || '';
    const opp  = leg.opponent || '';
    const ha   = leg.home_away === 'H' ? 'vs' : '@';
    const conf = leg.confidence_pct ? `${{leg.confidence_pct}}%` : '';

    let legResultIcon = '';
    const lr = leg.result;
    if (lr === 'HIT')  legResultIcon = `<span class="leg-result-hit">✓</span>`;
    else if (lr === 'MISS') legResultIcon = `<span class="leg-result-miss">✗</span>`;

    // Cannibalization badge — preserved (H33 pair signal between consecutive same-team same-stat legs)
    if (legIdx > 0) {{
      const prev = legs[legIdx - 1];
      const prevPt = prev.prop_type || prev.prop || '';
      if (pt === prevPt && (leg.team || '') === (prev.team || '')) {{
        const pair = [
          (prev.player_name || '').toLowerCase(),
          (leg.player_name || '').toLowerCase()
        ].sort();
        const cKey = pair[0] + '|' + pair[1] + '|' + pt;
        const ce = (DATA.cannib_lookup || {{}})[cKey];
        if (ce) {{
          const isNeg = ce.idx < 0;
          const icon = isNeg ? '⊖' : '⊕';
          const cls  = isNeg ? 'cannib-neg' : 'cannib-pos';
          const word = isNeg ? 'cannibalization' : 'synergy';
          html += `<div class="cannib-badge ${{cls}}" title="${{pt}} pair: ${{ce.idx > 0 ? '+' : ''}}${{ce.idx}}pp">${{icon}} ${{word}}</div>`;
        }}
      }}
    }}

    html += `
      <div class="parlay-leg">
        <div class="leg-main">
          <div class="leg-player">${{leg.player_name || ''}}</div>
          <div class="leg-team">${{team}} ${{ha}} ${{opp}}</div>
        </div>
        <div class="leg-stat">
          <span class="leg-stat-value">${{leg.pick_value}}</span>
          <span class="leg-stat-type prop-${{pt}}">${{pt}}</span>
          <span class="leg-conf">${{conf}}</span>
          ${{legResultIcon}}
        </div>
      </div>`;
  }});

  html += `</div>`;

  if (p.rationale) {{
    html += `<div class="parlay-rationale">${{escapeHtml(p.rationale)}}</div>`;
  }}

  html += `</div>`;
  return html;
}}

function renderParlays() {{
  const c = document.getElementById('parlays-container');
  const pd = DATA.parlays;
  const today = pd?.today || [];

  let html = '';

  if (!today.length) {{
    html += `<div class="empty"><div class="empty-icon">🎰</div>No parlays yet for ${{DATA.today_str}}.<br>Check back after picks are generated.</div>`;
    c.innerHTML = html;
    return;
  }}

  // Build set of voided player names from today's picks for leg-risk detection
  const voidedPlayerNames = new Set(
    (DATA.today_picks || [])
      .filter(pk => pk.voided)
      .map(pk => (pk.player_name || '').toLowerCase())
  );

  // Group today's cards by bucket (Safe / Reach / Degen)
  const byBucket = {{
    'Safe':  [],
    'Reach': [],
    'Degen': [],
  }};
  today.forEach(p => {{
    const b = p.bucket || 'Safe';  // defensive default
    if (byBucket[b]) byBucket[b].push(p);
    else byBucket['Safe'].push(p);  // any unknown bucket lumps into Safe
  }});

  const TIER_CONFIG = [
    {{ key: 'Safe',  label: 'Safe',  range: '+100 to +200', defaultOpen: true  }},
    {{ key: 'Reach', label: 'Reach', range: '+200 to +350', defaultOpen: false }},
    {{ key: 'Degen', label: 'Degen', range: '+350 to +600', defaultOpen: false }},
  ];

  TIER_CONFIG.forEach(tier => {{
    const cards = byBucket[tier.key];
    if (!cards || !cards.length) return;  // skip empty tiers entirely

    const drawerId = `parlay-tier-${{tier.key.toLowerCase()}}`;
    const display  = tier.defaultOpen ? 'block' : 'none';
    const chevClass = tier.defaultOpen ? 'drawer-chevron open' : 'drawer-chevron';

    html += `
      <div class="parlay-tier-drawer">
        <div class="drawer-header" onclick="toggleDrawer('${{drawerId}}')">
          <span class="tier-header-label">${{tier.label}} <span class="tier-range">${{tier.range}}</span> <span class="tier-count">· ${{cards.length}}</span></span>
          <span class="${{chevClass}}" id="${{drawerId}}-chevron">▼</span>
        </div>
        <div class="drawer-body" id="${{drawerId}}" style="display:${{display}}">`;

    cards.forEach(p => {{
      html += renderParlayCard(p, voidedPlayerNames);
    }});

    html += `
        </div>
      </div>`;
  }});

  c.innerHTML = html;
}}

renderParlays();

// ── CUSTOM PARLAY BUILDER ──

function renderBuilder() {{
  const container = document.getElementById('parlay-builder-container');
  if (!container) return;
  const picks = (DATA.today_picks || []).map((p, i) => ({{ ...p, _origIdx: i }})).filter(p => !p.voided && p.result == null);
  if (!picks.length) {{ container.innerHTML = ''; return; }}

  // Group picks by game matchup
  const games = {{}};
  picks.forEach((p, i) => {{
    const team = p.team || '';
    const opp  = p.opponent || '';
    const gameKey = [team, opp].sort().join('_');
    const gt = p.game_time || '';
    if (!games[gameKey]) games[gameKey] = {{ teams: [team, opp].sort(), time: gt, picks: [] }};
    games[gameKey].picks.push({{ ...p, _idx: p._origIdx }});
  }});

  // State: set of selected pick indices
  if (!window._builderState) window._builderState = new Set();
  const selected = window._builderState;

  // Build pick list (left column)
  let pickListHtml = '';
  Object.values(games).forEach(g => {{
    const label = g.teams.join(' vs ') + (g.time ? ' · ' + g.time : '');
    pickListHtml += `<div class="builder-game-group">`;
    pickListHtml += `<div class="builder-game-header"><span>${{label}}</span></div>`;
    g.picks.forEach(p => {{
      const sel = selected.has(p._idx);
      const pt = p.prop_type || '';
      const propCls = {{'PTS':'prop-PTS','REB':'prop-REB','AST':'prop-AST','3PM':'prop-3PM'}}[pt] || '';
      const conf = p.confidence_pct ? p.confidence_pct + '%' : '';
      const edge = (p.bet_recommendation || {{}}).calibrated_edge_pct;
      const edgeStr = edge != null ? (edge > 0 ? '+' : '') + edge.toFixed(1) + 'pp' : '';
      const edgeCls = edge > 0 ? 'builder-edge-pos' : edge < 0 ? 'builder-edge-neg' : 'builder-edge-neutral';
      pickListHtml += `<div class="builder-pick-row ${{sel ? 'selected' : ''}}"
        onclick="toggleBuilderLeg(${{p._idx}})">
        <div class="builder-pick-left">
          <span class="builder-pick-name">${{p.player_name || ''}}</span>
          <span class="builder-pick-stat ${{propCls}}">${{pt}}</span>
          <span class="builder-pick-tier">T${{p.pick_value}}</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="builder-pick-conf">${{conf}}</span>
          ${{edgeStr ? `<span class="builder-pick-conf ${{edgeCls}}">${{edgeStr}}</span>` : ''}}
        </div>
      </div>`;
    }});
    pickListHtml += `</div>`;
  }});

  // Build "Your Parlay" card (right column)
  const allPicks = DATA.today_picks || [];
  const legs = [...selected].map(i => allPicks[i]).filter(Boolean);
  let cardHtml = '';

  if (!legs.length) {{
    cardHtml = `<div class="builder-card">
      <div style="font-size:13px;font-weight:700;margin-bottom:8px">Your Parlay</div>
      <div class="builder-card-empty">Click picks on the left to build a parlay</div>
    </div>`;
  }} else {{
    // Compute combined probability
    // Combined MARKET probability (FanDuel) — drives COMBINED PROB, ODDS, PAYOUT
    let combinedMarketProb = 1;
    let anyMarketMissing = false;
    legs.forEach(leg => {{
      const p = leg.market_implied_prob;
      if (p == null) {{ anyMarketMissing = true; }}
      else {{ combinedMarketProb *= p / 100; }}
    }});

    // Combined CALIBRATED probability (system's internal prediction) — drives NET EDGE
    let combinedCalibratedProb = 1;
    let anyCalibratedMissing = false;
    legs.forEach(leg => {{
      const p = (leg.bet_recommendation || {{}}).calibrated_prob;
      if (p == null) {{ anyCalibratedMissing = true; }}
      else {{ combinedCalibratedProb *= p / 100; }}
    }});

    // American odds — derived from MARKET prob (actual payout at book)
    let oddsInt = 0;
    if (!anyMarketMissing && combinedMarketProb > 0 && combinedMarketProb < 1) {{
      oddsInt = combinedMarketProb < 0.5
        ? Math.round(((1 / combinedMarketProb) - 1) * 100)
        : Math.round(-100 / ((1 / combinedMarketProb) - 1));
    }}
    const oddsStr = anyMarketMissing ? '—' : (oddsInt >= 0 ? '+' + oddsInt : '' + oddsInt);

    // Payout for $10 bet — market odds
    let payout = '—';
    if (!anyMarketMissing) {{
      let payout10;
      if (oddsInt >= 100) {{
        payout10 = (10 * oddsInt / 100) + 10;
      }} else if (oddsInt <= -100) {{
        payout10 = (10 * 100 / Math.abs(oddsInt)) + 10;
      }} else {{
        payout10 = 10;
      }}
      payout = payout10.toFixed(2);
    }}

    // Combined prob display
    const combinedProbStr = anyMarketMissing ? '—' : (combinedMarketProb * 100).toFixed(1) + '%';

    // Net edge — combined calibrated prob minus combined market prob (pp)
    let netEdgePp = null;
    if (!anyMarketMissing && !anyCalibratedMissing) {{
      netEdgePp = (combinedCalibratedProb * 100) - (combinedMarketProb * 100);
    }}
    const edgeCls = netEdgePp == null ? 'builder-edge-neutral'
      : netEdgePp > 0 ? 'builder-edge-pos'
      : netEdgePp < 0 ? 'builder-edge-neg' : 'builder-edge-neutral';
    const edgeSign = netEdgePp != null && netEdgePp > 0 ? '+' : '';
    const edgeStr = netEdgePp == null ? '—' : edgeSign + netEdgePp.toFixed(1) + 'pp';

    // Render legs
    let legsHtml = '';
    const cannib = DATA.cannib_lookup || {{}};
    const corr   = DATA.corr_lookup || {{}};

    legs.forEach((leg, i) => {{
      const pt = leg.prop_type || '';
      const propCls = {{'PTS':'prop-PTS','REB':'prop-REB','AST':'prop-AST','3PM':'prop-3PM'}}[pt] || '';
      const mp = leg.market_implied_prob;
      const prob = mp != null ? mp.toFixed(1) + '%' : '—';
      const idx = [...selected][i];

      legsHtml += `<div class="builder-leg-row">
        <div style="display:flex;align-items:center;gap:8px;min-width:0">
          <span style="font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${{leg.player_name}}</span>
          <span class="builder-pick-stat ${{propCls}}" style="flex-shrink:0">${{pt}}</span>
          <span style="font-weight:800;flex-shrink:0">T${{leg.pick_value}}</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <span style="font-size:12px;color:var(--muted)">${{prob}}</span>
          <button class="builder-leg-remove" onclick="toggleBuilderLeg(${{idx}})">✕</button>
        </div>
      </div>`;
    }});

    // Warnings: cannib + correlation
    let warningsHtml = '';
    for (let i = 0; i < legs.length; i++) {{
      for (let j = i + 1; j < legs.length; j++) {{
        const a = legs[i], b = legs[j];
        const aName = (a.player_name || '').toLowerCase();
        const bName = (b.player_name || '').toLowerCase();
        const aTeam = a.team || '', bTeam = b.team || '';
        const aPt = a.prop_type || '', bPt = b.prop_type || '';

        // Same team, same stat: check cannib
        if (aTeam === bTeam && aPt === bPt) {{
          const pair = [aName, bName].sort();
          const cKey = pair[0] + '|' + pair[1] + '|' + aPt;
          const ce = cannib[cKey];
          if (ce) {{
            const isNeg = ce.idx < 0;
            const icon = isNeg ? '⊖' : '⊕';
            const color = isNeg ? 'var(--3pm)' : 'var(--accent2)';
            const word = isNeg ? 'cannibalization' : 'synergy';
            warningsHtml += `<div class="builder-warning-item" style="color:${{color}}">
              ${{icon}} ${{a.player_name}} ↔ ${{b.player_name}} ${{aPt}}: ${{word}} (${{ce.idx > 0 ? '+' : ''}}${{ce.idx}}pp)
            </div>`;
            continue;
          }}
        }}

        // Same team: check correlation
        if (aTeam === bTeam) {{
          const corrKey = aName + '|' + bName + '|' + aPt + '_' + bPt;
          const corrKeyRev = aName + '|' + bName + '|' + bPt + '_' + aPt;
          const ce = corr[corrKey] || corr[corrKeyRev];
          if (ce && ce.tag && ce.tag !== 'independent' && ce.tag !== 'insufficient_data') {{
            const isPos = ['feeder_target', 'volume_game', 'pace_beneficiary', 'positively_correlated', 'cannibalization_synergy'].includes(ce.tag);
            const icon = isPos ? '⊕' : '⊖';
            const color = isPos ? 'var(--accent2)' : 'var(--3pm)';
            const tagDisplay = ce.tag.replace(/_/g, ' ');
            warningsHtml += `<div class="builder-warning-item" style="color:${{color}}">
              ${{icon}} ${{a.player_name}} ↔ ${{b.player_name}}: ${{tagDisplay}}${{ce.r != null ? ' (r=' + ce.r + ')' : ''}}
            </div>`;
          }}
        }}
      }}
    }}

    cardHtml = `<div class="builder-card">
      <div style="font-size:13px;font-weight:700;margin-bottom:10px">Your Parlay · ${{legs.length}} leg${{legs.length !== 1 ? 's' : ''}}</div>
      ${{legsHtml}}
      <div class="builder-stats-row">
        <div class="builder-stat">
          <div class="val">${{combinedProbStr}}</div>
          <div class="lbl">combined prob</div>
        </div>
        <div class="builder-stat">
          <div class="val">${{oddsStr}}</div>
          <div class="lbl">odds</div>
        </div>
        <div class="builder-stat">
          <div class="val">${{payout === '—' ? '—' : '$' + payout}}</div>
          <div class="lbl">$10 payout</div>
        </div>
        <div class="builder-stat">
          <div class="val ${{edgeCls}}">${{edgeStr}}</div>
          <div class="lbl">net edge</div>
        </div>
      </div>
      ${{warningsHtml ? `<div class="builder-warnings">${{warningsHtml}}</div>` : ''}}
      <div class="builder-actions">
        <button class="builder-btn" onclick="clearBuilder()">Clear</button>
        <button class="builder-btn builder-btn-accent" onclick="copyBuilder()">Copy to clipboard</button>
        <span class="builder-copied" id="builder-copied-msg">Copied!</span>
      </div>
    </div>`;
  }}

  container.innerHTML = `
    <div class="builder-section">
      <div class="builder-header">🔧 Parlay Builder</div>
      <div class="builder-layout">
        <div class="builder-picks">${{pickListHtml}}</div>
        <div>${{cardHtml}}</div>
      </div>
    </div>`;
}}

function toggleBuilderLeg(idx) {{
  if (!window._builderState) window._builderState = new Set();
  if (window._builderState.has(idx)) {{
    window._builderState.delete(idx);
  }} else {{
    window._builderState.add(idx);
  }}
  renderBuilder();
}}

function clearBuilder() {{
  window._builderState = new Set();
  renderBuilder();
}}

function copyBuilder() {{
  const allPicks = DATA.today_picks || [];
  const legs = [...(window._builderState || [])].map(i => allPicks[i]).filter(Boolean);
  if (!legs.length) return;

  // Combined MARKET probability (FanDuel) — drives odds and payout
  let combinedMarketProb = 1;
  let anyMarketMissing = false;
  legs.forEach(leg => {{
    const p = leg.market_implied_prob;
    if (p == null) {{ anyMarketMissing = true; }}
    else {{ combinedMarketProb *= p / 100; }}
  }});

  const lines = legs.map(leg => leg.player_name + ' ' + leg.pick_value + ' ' + leg.prop_type);

  let oddsStr = '—';
  let payoutStr = '—';
  let combinedStr = '—';
  if (!anyMarketMissing && combinedMarketProb > 0 && combinedMarketProb < 1) {{
    const oddsInt = combinedMarketProb < 0.5
      ? Math.round(((1 / combinedMarketProb) - 1) * 100)
      : Math.round(-100 / ((1 / combinedMarketProb) - 1));
    oddsStr = oddsInt >= 0 ? '+' + oddsInt : '' + oddsInt;
    let payout10;
    if (oddsInt >= 100) payout10 = (10 * oddsInt / 100) + 10;
    else if (oddsInt <= -100) payout10 = (10 * 100 / Math.abs(oddsInt)) + 10;
    else payout10 = 10;
    payoutStr = '$' + payout10.toFixed(2);
    combinedStr = (combinedMarketProb * 100).toFixed(1) + '%';
  }}

  const text = 'NBAgent Custom Parlay — ' + DATA.today_str + '\\n'
    + lines.join('\\n')
    + '\\nCombined: ' + combinedStr + ' | ' + oddsStr + ' | $10 → ' + payoutStr;

  navigator.clipboard.writeText(text).then(() => {{
    const msg = document.getElementById('builder-copied-msg');
    if (msg) {{ msg.classList.add('show'); setTimeout(() => msg.classList.remove('show'), 1500); }}
  }}).catch(() => {{}});
}}

renderBuilder();

// ── PLAYER EXPLORER ──
// ── Round label helper (inferred from series order within each season) ──
const ROUND_LABELS = {{1:'R1', 2:'R2', 3:'CF', 4:'Finals', 5:'Finals'}};
function roundLabel(n) {{ return ROUND_LABELS[n] || 'R'+n; }}
function round1(v) {{ return Math.round(v * 10) / 10; }}

// ── Playoff Career Profiles (collapsible overview) ──
function renderPlayoffProfiles(container) {{
  if (!container) return;
  const pd = DATA.playoff || {{}};
  const profiles = pd.profiles || [];
  if (!profiles.length) return;

  let sortKey = 'total_games';
  let sortDir = -1;

  function renderCards() {{
    const sorted = [...profiles].sort((a,b) => {{
      if (sortKey === 'name') {{
        return sortDir * a.name.localeCompare(b.name);
      }}
      let va, vb;
      if (sortKey === 'total_games') {{
        va = a.total_games; vb = b.total_games;
      }} else {{
        va = (a.deltas||{{}})[sortKey]; vb = (b.deltas||{{}})[sortKey];
        va = (va !== null && va !== undefined) ? va : -999;
        vb = (vb !== null && vb !== undefined) ? vb : -999;
      }}
      return sortDir * (va - vb);
    }});

    const deltaCell = (val, suffix) => {{
      if (val === null || val === undefined) return '<span style="color:var(--muted)">—</span>';
      const color = val > 0 ? 'var(--hit)' : val < 0 ? 'var(--miss)' : 'var(--muted)';
      const sign  = val > 0 ? '+' : '';
      return `<span style="color:${{color}};font-weight:600">${{sign}}${{val}}${{suffix || ''}}</span>`;
    }};

    return sorted.map(p => {{
      const seasonChips = p.seasons.map(s =>
        `<span style="background:var(--border);border-radius:4px;padding:2px 6px;font-size:10px;color:var(--muted)">'${{String(s.year).slice(2)}}: ${{s.games}}g</span>`
      ).join(' ');

      const sampleBadge = p.total_games < 10
        ? '<span style="background:var(--miss);color:#000;border-radius:4px;padding:1px 6px;font-size:10px;font-weight:600;margin-left:6px">small sample</span>'
        : '';

      const statCols = ['pts','reb','ast','tpm'];
      const seasonRows = p.seasons.map(s => {{
        const cells = statCols.map(st => {{
          const po  = (s.po||{{}})[st];
          const reg = (s.reg||{{}})[st];
          if (po === undefined || po === null) return '<td style="padding:3px 6px;text-align:center;color:var(--muted)">—</td>';
          const regStr   = (reg !== undefined && reg !== null) ? reg : '—';
          const delta    = (reg !== undefined && reg !== null) ? round1(po - reg) : null;
          const deltaStr = delta !== null ? ` (${{delta > 0 ? '+' : ''}}${{delta}})` : '';
          return `<td style="padding:3px 6px;text-align:center;font-size:11px;color:var(--fg)">${{po}}<span style="color:var(--muted);font-size:10px"> vs ${{regStr}}${{deltaStr}}</span></td>`;
        }}).join('');
        return `<tr><td style="padding:3px 6px;font-size:11px;color:var(--muted)">${{s.year}} (${{s.games}}g)</td>${{cells}}</tr>`;
      }}).join('');

      return `
        <div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div>
              <span style="font-size:14px;font-weight:700;color:var(--fg)">${{p.name}}</span>
              <span style="font-size:12px;color:var(--muted);margin-left:6px">${{p.team}} · ${{p.total_games}}g</span>
              ${{sampleBadge}}
            </div>
          </div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px">
            <span style="font-size:12px">PTS ${{deltaCell(p.deltas.pts)}}</span>
            <span style="font-size:12px">REB ${{deltaCell(p.deltas.reb)}}</span>
            <span style="font-size:12px">AST ${{deltaCell(p.deltas.ast)}}</span>
            <span style="font-size:12px">3PM ${{deltaCell(p.deltas.tpm)}}</span>
            <span style="font-size:12px">FG% ${{deltaCell(p.deltas.fg_pct, '%')}}</span>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px">${{seasonChips}}</div>
          <div style="font-size:11px;color:var(--muted)">
            Playoff: ${{p.po_avgs.pts}} PPG · ${{p.po_avgs.reb}} RPG · ${{p.po_avgs.ast}} APG · ${{p.po_avgs.min}} MPG
          </div>
          <details style="margin-top:8px">
            <summary style="font-size:11px;color:var(--accent);cursor:pointer">Per-season breakdown</summary>
            <table style="width:100%;border-collapse:collapse;margin-top:6px;font-size:11px">
              <thead><tr style="color:var(--muted)">
                <th style="text-align:left;padding:3px 6px">Season</th>
                <th style="text-align:center;padding:3px 6px">PTS</th>
                <th style="text-align:center;padding:3px 6px">REB</th>
                <th style="text-align:center;padding:3px 6px">AST</th>
                <th style="text-align:center;padding:3px 6px">3PM</th>
              </tr></thead>
              <tbody>${{seasonRows}}</tbody>
            </table>
          </details>
        </div>`;
    }}).join('');
  }}

  const sortOptions = [
    {{key:'total_games', label:'Games'}},
    {{key:'pts',         label:'PTS Δ'}},
    {{key:'reb',         label:'REB Δ'}},
    {{key:'ast',         label:'AST Δ'}},
    {{key:'tpm',         label:'3PM Δ'}},
    {{key:'fg_pct',      label:'FG% Δ'}},
    {{key:'name',        label:'A–Z'}},
  ];

  const sortBtns = sortOptions.map(o =>
    `<button onclick="sortPlayoffProfiles('${{o.key}}')" id="po-sort-${{o.key}}" style="background:var(--border);color:var(--muted);border:none;border-radius:4px;padding:4px 10px;font-size:11px;cursor:pointer;font-weight:600">${{o.label}}</button>`
  ).join(' ');

  container.innerHTML = `
    <details open style="margin-bottom:24px">
      <summary style="font-size:16px;font-weight:700;color:var(--fg);cursor:pointer;margin-bottom:12px">
        Playoff Career Profiles
        <span style="font-size:12px;font-weight:400;color:var(--muted);margin-left:8px">${{profiles.length}} players · 2021–2025</span>
      </summary>
      <div style="margin:12px 0 10px;display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <span style="font-size:11px;color:var(--muted);margin-right:4px">Sort:</span>
        ${{sortBtns}}
      </div>
      <div id="po-cards">${{renderCards()}}</div>
    </details>`;

  const activeBtn = document.getElementById('po-sort-' + sortKey);
  if (activeBtn) {{
    activeBtn.style.background = 'var(--accent)';
    activeBtn.style.color      = '#000';
  }}

  window.sortPlayoffProfiles = function(key) {{
    if (sortKey === key) {{
      sortDir *= -1;
    }} else {{
      sortKey = key;
      sortDir = (key === 'name') ? 1 : -1;
    }}
    const cardsDiv = document.getElementById('po-cards');
    if (cardsDiv) cardsDiv.innerHTML = renderCards();
    sortOptions.forEach(o => {{
      const btn = document.getElementById('po-sort-' + o.key);
      if (btn) {{
        btn.style.background = (o.key === sortKey) ? 'var(--accent)' : 'var(--border)';
        btn.style.color      = (o.key === sortKey) ? '#000' : 'var(--muted)';
      }}
    }});
  }};
}}

// ── Playoff Game Explorer (collapsible filterable explorer) ──
function renderPlayoffExplorer(container) {{
  if (!container) return;
  const pd = DATA.playoff || {{}};
  const gamesData = pd.games || {{}};
  const profiles  = pd.profiles || [];
  const players   = profiles.map(p => p.name).sort();
  if (!players.length) return;

  const allOpponents = new Set();
  const allSeasons   = new Set();
  Object.values(gamesData).forEach(games => {{
    games.forEach(g => {{
      if (g.opp) allOpponents.add(g.opp);
      if (g.s)   allSeasons.add(g.s);
    }});
  }});
  const sortedOpps    = Array.from(allOpponents).sort();
  const sortedSeasons = Array.from(allSeasons).sort();

  container.innerHTML = `
    <details style="margin-bottom:24px">
      <summary style="font-size:16px;font-weight:700;color:var(--fg);cursor:pointer;margin-bottom:12px">
        Playoff Game Explorer
        <span style="font-size:12px;font-weight:400;color:var(--muted);margin-left:8px">2021–2025 postseason game logs</span>
      </summary>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin:12px 0 16px">
        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Player *</div>
          <select id="pex-player" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">— select player —</option>
            ${{players.map(p => `<option value="${{p}}">${{p}}</option>`).join('')}}
          </select>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Stat</div>
          <select id="pex-stat" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="pts">PTS</option>
            <option value="reb">REB</option>
            <option value="ast">AST</option>
            <option value="tpm">3PM</option>
          </select>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Season</div>
          <select id="pex-season" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">All</option>
            ${{sortedSeasons.map(s => `<option value="${{s}}">${{s-1}}–${{String(s).slice(2)}}</option>`).join('')}}
          </select>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Round</div>
          <select id="pex-round" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">All</option>
            <option value="1">R1</option>
            <option value="2">R2</option>
            <option value="3">Conf Finals</option>
            <option value="4">Finals</option>
          </select>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Opponent</div>
          <select id="pex-opp" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            ${{sortedOpps.map(o => `<option value="${{o}}">${{o}}</option>`).join('')}}
          </select>
        </div>
        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Home / Away</div>
          <select id="pex-ha" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            <option value="H">Home</option>
            <option value="A">Away</option>
          </select>
        </div>
      </div>

      <button onclick="runPlayoffExplorer()" style="background:var(--accent);color:#000;border:none;border-radius:6px;padding:9px 24px;font-size:13px;font-weight:700;cursor:pointer;margin-bottom:24px">
        Search
      </button>
      <div id="pex-results"></div>
    </details>`;
}}

function runPlayoffExplorer() {{
  const pd        = DATA.playoff || {{}};
  const gamesData = pd.games || {{}};
  const playerName = document.getElementById('pex-player').value;
  const stat       = document.getElementById('pex-stat').value;
  const seasonF    = document.getElementById('pex-season').value;
  const roundF     = document.getElementById('pex-round').value;
  const oppF       = document.getElementById('pex-opp').value;
  const haF        = document.getElementById('pex-ha').value;
  const out        = document.getElementById('pex-results');

  if (!playerName) {{
    out.innerHTML = '<div style="color:var(--muted);font-size:13px">Select a player to get started.</div>';
    return;
  }}

  const games = gamesData[playerName.toLowerCase()] || [];
  const filtered = games.filter(g => {{
    if (seasonF && String(g.s) !== seasonF) return false;
    if (roundF  && String(g.r) !== roundF)  return false;
    if (oppF    && g.opp !== oppF)          return false;
    if (haF     && g.ha  !== haF)           return false;
    return true;
  }});

  if (!filtered.length) {{
    out.innerHTML = '<div style="color:var(--muted);font-size:13px">No playoff games match the selected filters.</div>';
    return;
  }}

  const TIERS       = {{ pts:[10,15,20,25,30], reb:[2,4,6,8,10,12], ast:[2,4,6,8,10,12], tpm:[1,2,3,4] }};
  const STAT_COLORS = {{ pts:'var(--pts)', reb:'var(--reb)', ast:'var(--ast)', tpm:'var(--3pm)' }};
  const STAT_LABELS = {{ pts:'PTS', reb:'REB', ast:'AST', tpm:'3PM' }};
  const tiers = TIERS[stat];
  const color = STAT_COLORS[stat];
  const label = STAT_LABELS[stat];
  const n     = filtered.length;

  const tierRows = tiers.map(t => {{
    const valid = filtered.filter(g => g[stat] !== null && g[stat] !== undefined);
    const hits  = valid.filter(g => g[stat] >= t).length;
    const pct   = valid.length ? (hits / valid.length * 100) : null;
    return {{ tier: t, hits, n: valid.length, pct }};
  }});

  const vals   = filtered.map(g => g[stat]).filter(v => v !== null && v !== undefined);
  const avg    = vals.length ? (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1) : '—';
  const mn     = vals.length ? Math.min(...vals) : '—';
  const mx     = vals.length ? Math.max(...vals) : '—';
  const sorted = [...vals].sort((a,b)=>a-b);
  const med    = sorted.length ? sorted[Math.floor(sorted.length/2)] : '—';

  const filterParts = [];
  if (seasonF) filterParts.push(`${{seasonF-1}}–${{String(seasonF).slice(2)}}`);
  if (roundF)  filterParts.push(roundLabel(parseInt(roundF)));
  if (oppF)    filterParts.push(`vs ${{oppF}}`);
  if (haF)     filterParts.push(haF === 'H' ? 'Home' : 'Away');
  const filterStr = filterParts.length ? ` · ${{filterParts.join(' · ')}}` : '';

  let html = `
    <div style="margin-bottom:12px">
      <span style="font-size:15px;font-weight:700;color:var(--fg)">${{playerName}}</span>
      <span style="font-size:13px;color:var(--muted);margin-left:8px">${{label}} · ${{n}} playoff game${{n!==1?'s':''}}${{filterStr}}</span>
      ${{n < 10 ? '<span style="font-size:11px;color:var(--miss);margin-left:8px">⚠ small sample</span>' : ''}}
    </div>

    <div style="display:flex;gap:20px;margin-bottom:16px;flex-wrap:wrap">
      <div style="font-size:12px;color:var(--muted)">Avg <span style="color:var(--fg);font-weight:600">${{avg}}</span></div>
      <div style="font-size:12px;color:var(--muted)">Med <span style="color:var(--fg);font-weight:600">${{med}}</span></div>
      <div style="font-size:12px;color:var(--muted)">Min <span style="color:var(--fg);font-weight:600">${{mn}}</span></div>
      <div style="font-size:12px;color:var(--muted)">Max <span style="color:var(--fg);font-weight:600">${{mx}}</span></div>
    </div>

    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:13px">
      <thead>
        <tr style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em">
          <th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)">Tier</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:1px solid var(--border)">Hit Rate</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:1px solid var(--border)">Hits / Games</th>
          <th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)"></th>
        </tr>
      </thead>
      <tbody>
        ${{tierRows.map(r => {{
          const pctStr   = r.pct !== null ? r.pct.toFixed(1) + '%' : '—';
          const barW     = r.pct !== null ? Math.round(r.pct) : 0;
          const barColor = r.pct === null ? 'var(--muted)' : r.pct >= 70 ? color : 'var(--muted)';
          return `<tr>
            <td style="padding:6px 8px;color:var(--fg);font-weight:600">${{label}} ${{r.tier}}+</td>
            <td style="padding:6px 8px;text-align:right;color:${{barColor}};font-weight:${{r.pct !== null && r.pct >= 70 ? '700' : '400'}}">${{pctStr}}</td>
            <td style="padding:6px 8px;text-align:right;color:var(--muted)">${{r.hits}}/${{r.n}}</td>
            <td style="padding:6px 8px;width:120px">
              <div style="height:6px;border-radius:3px;background:var(--border);overflow:hidden">
                <div style="height:100%;width:${{barW}}%;background:${{barColor}};border-radius:3px"></div>
              </div>
            </td>
          </tr>`;
        }}).join('')}}
      </tbody>
    </table>`;

  // Group-by-series game log (chronological within each series)
  const displayGames = [...filtered].sort((a,b) => a.d.localeCompare(b.d));
  let lastSeriesKey = '';

  html += `
    <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Playoff Game Log</div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="color:var(--muted);font-size:11px">
          <th style="text-align:left;padding:5px 6px;border-bottom:1px solid var(--border)">Date</th>
          <th style="text-align:left;padding:5px 6px;border-bottom:1px solid var(--border)">Season</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border)">Round</th>
          <th style="text-align:left;padding:5px 6px;border-bottom:1px solid var(--border)">Opp</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border)">H/A</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border)">Mins</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border)">FG</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border)">FG%</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border)">FT</th>
          <th style="text-align:center;padding:5px 6px;border-bottom:1px solid var(--border);color:${{color}}">${{label}}</th>
        </tr>
      </thead>
      <tbody>
        ${{displayGames.map(g => {{
          const val = g[stat];
          const valColor = (val !== null && val !== undefined && tiers.length && val >= tiers[0]) ? color : 'var(--fg)';
          const seriesKey = `${{g.s}}-${{g.opp}}`;
          const showSeriesHeader = seriesKey !== lastSeriesKey;
          lastSeriesKey = seriesKey;
          const headerRow = showSeriesHeader
            ? `<tr><td colspan="10" style="padding:8px 6px 4px;font-size:11px;font-weight:700;color:var(--accent);border-bottom:1px solid var(--border)">${{g.s-1}}–${{String(g.s).slice(2)}} ${{roundLabel(g.r)}} vs ${{g.opp}}</td></tr>`
            : '';
          return `${{headerRow}}<tr style="border-bottom:1px solid var(--border)">
            <td style="padding:5px 6px;color:var(--muted)">${{g.d}}</td>
            <td style="padding:5px 6px;color:var(--muted)">${{g.s-1}}–${{String(g.s).slice(2)}}</td>
            <td style="padding:5px 6px;text-align:center;color:var(--muted)">${{roundLabel(g.r)}}</td>
            <td style="padding:5px 6px;color:var(--fg)">${{g.opp || '—'}}</td>
            <td style="padding:5px 6px;text-align:center;color:var(--muted)">${{g.ha || '—'}}</td>
            <td style="padding:5px 6px;text-align:center;color:var(--muted)">${{g.min !== null && g.min !== undefined ? g.min : '—'}}</td>
            <td style="padding:5px 6px;text-align:center;color:var(--muted)">${{g.fgm !== null && g.fgm !== undefined ? g.fgm+'-'+g.fga : '—'}}</td>
            <td style="padding:5px 6px;text-align:center;color:var(--muted)">${{g.fg_pct !== null && g.fg_pct !== undefined ? g.fg_pct+'%' : '—'}}</td>
            <td style="padding:5px 6px;text-align:center;color:var(--muted)">${{g.ftm !== null && g.ftm !== undefined ? g.ftm+'-'+g.fta : '—'}}</td>
            <td style="padding:5px 6px;text-align:center;font-weight:700;color:${{valColor}}">${{val !== null && val !== undefined ? val : '—'}}</td>
          </tr>`;
        }}).join('')}}
      </tbody>
    </table>
    </div>`;

  out.innerHTML = html;
}}

// ── Research tab: renders three stacked sections ──
function renderResearch() {{
  const c = document.getElementById('research-container');
  if (!c) return;

  c.innerHTML = `
    <div style="max-width:780px;margin:0 auto;padding:16px 0">
      <div id="playoff-profiles-section"></div>
      <div id="playoff-explorer-section"></div>
      <div id="current-explorer-section"></div>
    </div>`;

  renderPlayoffProfiles(document.getElementById('playoff-profiles-section'));
  renderPlayoffExplorer(document.getElementById('playoff-explorer-section'));
  renderCurrentSeasonExplorer(document.getElementById('current-explorer-section'));
}}

// ── Current-season Player Explorer (extracted from old renderResearch body) ──
function renderCurrentSeasonExplorer(container) {{
  if (!container) return;

  const explorerData = DATA.explorer || {{}};
  const players = Object.keys(explorerData).sort();

  if (!players.length) {{
    container.innerHTML = '<div style="padding:32px;color:var(--muted);font-size:13px">No player game log data available.</div>';
    return;
  }}

  // Collect all opponents for the opponent filter dropdown
  const allOpponents = new Set();
  players.forEach(p => {{
    (explorerData[p] || []).forEach(g => {{ if (g.opp) allOpponents.add(g.opp); }});
  }});
  const sortedOpps = Array.from(allOpponents).sort();

  let html = `
    <details open style="margin-bottom:24px">
      <summary style="font-size:16px;font-weight:700;color:var(--fg);cursor:pointer;margin-bottom:12px">
        Player Explorer
        <span style="font-size:12px;font-weight:400;color:var(--muted);margin-left:8px">2025-26 season game logs</span>
      </summary>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin:12px 0 16px">

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Player *</div>
          <select id="ex-player" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">— select player —</option>
            ${{players.map(p => `<option value="${{p}}">${{p}}</option>`).join('')}}
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Stat</div>
          <select id="ex-stat" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="pts">PTS</option>
            <option value="reb">REB</option>
            <option value="ast">AST</option>
            <option value="tpm">3PM</option>
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Home / Away</div>
          <select id="ex-ha" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            <option value="H">Home</option>
            <option value="A">Away</option>
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Rest Days</div>
          <select id="ex-rest" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            <option value="0">0 (B2B)</option>
            <option value="1">1</option>
            <option value="2">2</option>
            <option value="3">3+</option>
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Fav / Dog</div>
          <select id="ex-favdog" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            <option value="fav">Favorite</option>
            <option value="dog">Underdog</option>
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Spread</div>
          <select id="ex-spread" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            <option value="0-3">0 – 3.5 (Pick'em)</option>
            <option value="4-6">3.5 – 6.5 (Competitive)</option>
            <option value="7-9">6.5 – 9.5 (Moderate)</option>
            <option value="10-13">9.5 – 13.5 (Large)</option>
            <option value="14+">14+ (Blowout risk)</option>
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Game Result</div>
          <select id="ex-result" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            <option value="W">Win</option>
            <option value="L">Loss</option>
          </select>
        </div>

        <div>
          <div style="font-size:11px;color:var(--muted);margin-bottom:4px;text-transform:uppercase;letter-spacing:.05em">Opponent</div>
          <select id="ex-opp" style="width:100%;background:var(--card);color:var(--fg);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:13px">
            <option value="">Any</option>
            ${{sortedOpps.map(o => `<option value="${{o}}">${{o}}</option>`).join('')}}
          </select>
        </div>

      </div>

      <button onclick="runExplorer()" style="background:var(--accent);color:#000;border:none;border-radius:6px;padding:9px 24px;font-size:13px;font-weight:700;cursor:pointer;margin-bottom:24px">
        Search
      </button>

      <div id="ex-results"></div>
    </details>`;

  container.innerHTML = html;
}}

function runExplorer() {{
  const explorerData = DATA.explorer || {{}};
  const playerName   = document.getElementById('ex-player').value;
  const stat         = document.getElementById('ex-stat').value;
  const haFilter     = document.getElementById('ex-ha').value;
  const restFilter   = document.getElementById('ex-rest').value;
  const spreadFilter = document.getElementById('ex-spread').value;
  const resultFilter = document.getElementById('ex-result').value;
  const oppFilter    = document.getElementById('ex-opp').value;
  const favdogFilter = document.getElementById('ex-favdog').value;
  const out          = document.getElementById('ex-results');

  if (!playerName) {{
    out.innerHTML = '<div style="color:var(--muted);font-size:13px">Select a player to get started.</div>';
    return;
  }}

  const games = explorerData[playerName] || [];

  const filtered = games.filter(g => {{
    if (haFilter && g.ha !== haFilter) return false;
    if (restFilter !== '' && String(g.rest) !== restFilter) return false;
    if (oppFilter && g.opp !== oppFilter) return false;
    if (resultFilter) {{
      if (resultFilter === 'W' && g.won !== true)  return false;
      if (resultFilter === 'L' && g.won !== false) return false;
    }}
    if (favdogFilter) {{
      if (g.player_spread === null || g.player_spread === undefined) return false;
      if (favdogFilter === 'fav' && g.player_spread >= 0) return false;
      if (favdogFilter === 'dog' && g.player_spread <= 0) return false;
    }}
    if (spreadFilter) {{
      if (g.spread_abs === null || g.spread_abs === undefined) return false;
      const s = g.spread_abs;
      if (spreadFilter === '0-3'   && !(s < 3.5))             return false;
      if (spreadFilter === '4-6'   && !(s >= 3.5 && s < 6.5)) return false;
      if (spreadFilter === '7-9'   && !(s >= 6.5 && s < 9.5)) return false;
      if (spreadFilter === '10-13' && !(s >= 9.5 && s < 13.5)) return false;
      if (spreadFilter === '14+'   && !(s >= 13.5))            return false;
    }}
    return true;
  }});

  if (!filtered.length) {{
    out.innerHTML = '<div style="color:var(--muted);font-size:13px">No games match the selected filters.</div>';
    return;
  }}

  const TIERS       = {{ pts:[10,15,20,25,30], reb:[2,4,6,8,10,12], ast:[2,4,6,8,10,12], tpm:[1,2,3,4] }};
  const STAT_COLORS = {{ pts:'var(--pts)', reb:'var(--reb)', ast:'var(--ast)', tpm:'var(--3pm)' }};
  const STAT_LABELS = {{ pts:'PTS', reb:'REB', ast:'AST', tpm:'3PM' }};
  const tiers = TIERS[stat];
  const color = STAT_COLORS[stat];
  const label = STAT_LABELS[stat];
  const n = filtered.length;

  const tierRows = tiers.map(t => {{
    const valid = filtered.filter(g => g[stat] !== null && g[stat] !== undefined);
    const hits  = valid.filter(g => g[stat] >= t).length;
    const pct   = valid.length ? (hits / valid.length * 100) : null;
    return {{ tier: t, hits, n: valid.length, pct }};
  }});

  const vals   = filtered.map(g => g[stat]).filter(v => v !== null && v !== undefined);
  const avg    = vals.length ? (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1) : '—';
  const mn     = vals.length ? Math.min(...vals) : '—';
  const mx     = vals.length ? Math.max(...vals) : '—';
  const sorted = [...vals].sort((a,b)=>a-b);
  const med    = sorted.length ? sorted[Math.floor(sorted.length/2)] : '—';

  let html = `
    <div style="margin-bottom:12px">
      <span style="font-size:15px;font-weight:700;color:var(--fg)">${{playerName}}</span>
      <span style="font-size:13px;color:var(--muted);margin-left:8px">${{label}} · ${{n}} game${{n!==1?'s':''}}</span>
      ${{n < 10 ? '<span style="font-size:11px;color:var(--miss);margin-left:8px">⚠ small sample</span>' : ''}}
    </div>

    <div style="display:flex;gap:20px;margin-bottom:16px;flex-wrap:wrap">
      <div style="font-size:12px;color:var(--muted)">Avg <span style="color:var(--fg);font-weight:600">${{avg}}</span></div>
      <div style="font-size:12px;color:var(--muted)">Med <span style="color:var(--fg);font-weight:600">${{med}}</span></div>
      <div style="font-size:12px;color:var(--muted)">Min <span style="color:var(--fg);font-weight:600">${{mn}}</span></div>
      <div style="font-size:12px;color:var(--muted)">Max <span style="color:var(--fg);font-weight:600">${{mx}}</span></div>
    </div>

    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:13px">
      <thead>
        <tr style="color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em">
          <th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)">Tier</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:1px solid var(--border)">Hit Rate</th>
          <th style="text-align:right;padding:6px 8px;border-bottom:1px solid var(--border)">Hits / Games</th>
          <th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border)"></th>
        </tr>
      </thead>
      <tbody>
        ${{tierRows.map(r => {{
          const pct      = r.pct !== null ? r.pct.toFixed(1) + '%' : '—';
          const barW     = r.pct !== null ? Math.round(r.pct) : 0;
          const barColor = r.pct === null ? 'var(--muted)' : r.pct >= 70 ? color : 'var(--muted)';
          return `<tr>
            <td style="padding:6px 8px;color:var(--fg);font-weight:600">${{label}} ${{r.tier}}+</td>
            <td style="padding:6px 8px;text-align:right;color:${{barColor}};font-weight:${{r.pct !== null && r.pct >= 70 ? '700' : '400'}}">${{pct}}</td>
            <td style="padding:6px 8px;text-align:right;color:var(--muted)">${{r.hits}}/${{r.n}}</td>
            <td style="padding:6px 8px;width:120px">
              <div style="height:6px;border-radius:3px;background:var(--border);overflow:hidden">
                <div style="height:100%;width:${{barW}}%;background:${{barColor}};border-radius:3px"></div>
              </div>
            </td>
          </tr>`;
        }}).join('')}}
      </tbody>
    </table>`;

  const displayGames = [...filtered].sort((a,b) => b.date.localeCompare(a.date));

  html += `
    <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">Game Log</div>
    <div style="overflow-x:auto">
    <table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead>
        <tr style="color:var(--muted);font-size:11px">
          <th style="text-align:left;padding:5px 8px;border-bottom:1px solid var(--border)">Date</th>
          <th style="text-align:left;padding:5px 8px;border-bottom:1px solid var(--border)">Opp</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border)">H/A</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border)">Spread</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border)">Result</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border)">Margin</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border)">Rest</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border)">Mins</th>
          <th style="text-align:center;padding:5px 8px;border-bottom:1px solid var(--border);color:${{color}}">${{label}}</th>
        </tr>
      </thead>
      <tbody>
        ${{displayGames.map(g => {{
          const val      = g[stat];
          const valColor = val !== null && val !== undefined && tiers.length && val >= tiers[0] ? color : 'var(--fg)';
          const restLabel = g.rest === null ? '—' : g.rest === 0 ? 'B2B' : g.rest === 3 ? '3+' : String(g.rest);
          const wonLabel  = g.won === true  ? '<span style="color:var(--hit)">W</span>'
                          : g.won === false ? '<span style="color:var(--miss)">L</span>' : '—';
          return `<tr style="border-bottom:1px solid var(--border)">
            <td style="padding:5px 8px;color:var(--muted)">${{g.date}}</td>
            <td style="padding:5px 8px;color:var(--fg)">${{g.opp || '—'}}</td>
            <td style="padding:5px 8px;text-align:center;color:var(--muted)">${{g.ha || '—'}}</td>
            <td style="padding:5px 8px;text-align:center;color:var(--muted)">${{g.player_spread !== null && g.player_spread !== undefined ? g.player_spread : '—'}}</td>
            <td style="padding:5px 8px;text-align:center">${{wonLabel}}</td>
            <td style="padding:5px 8px;text-align:center;color:var(--muted)">${{g.margin !== null && g.margin !== undefined ? '+'+g.margin : '—'}}</td>
            <td style="padding:5px 8px;text-align:center;color:var(--muted)">${{restLabel}}</td>
            <td style="padding:5px 8px;text-align:center;color:var(--muted)">${{g.mins !== null && g.mins !== undefined ? g.mins : '—'}}</td>
            <td style="padding:5px 8px;text-align:center;font-weight:700;color:${{valColor}}">${{val !== null && val !== undefined ? val : '—'}}</td>
          </tr>`;
        }}).join('')}}
      </tbody>
    </table>
    </div>`;

  out.innerHTML = html;
}}

renderResearch();
</script>
</body>
</html>"""


if __name__ == "__main__":
    build_site()
