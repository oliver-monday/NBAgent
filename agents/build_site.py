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
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"

PT = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(PT).strftime("%Y-%m-%d")

PICKS_JSON              = DATA / "picks.json"
PARLAYS_JSON            = DATA / "parlays.json"
AUDIT_LOG_JSON          = DATA / "audit_log.json"
AUDIT_SUMMARY_JSON      = DATA / "audit_summary.json"
MASTER_CSV              = DATA / "nba_master.csv"
INJURIES_JSON           = DATA / "injuries_today.json"
OPPORTUNITY_FLAGS_JSON  = DATA / "opportunity_flags.json"
PICKS_REVIEW_JSON       = DATA / f"picks_review_{TODAY_STR}.json"
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

    top_picks = get_top_picks(today_picks)

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
        "top_picks": top_picks,
        "top_picks_history": {
            "hits": tp_hits,
            "total": tp_total,
            "pct": tp_pct,
            "picks": sorted(past_top_picks, key=lambda p: p.get("date", ""), reverse=True)[:40],
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
    top_picks_history_json  = json.dumps(d.get("top_picks_history", {"hits": 0, "total": 0, "pct": 0, "picks": []}))
    yesterday_summary_json  = json.dumps(d.get("yesterday_summary", {}))
    opportunity_flags_json  = json.dumps(d.get("opportunity_flags", []))
    explorer_json           = json.dumps(d.get("explorer", {}))

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
    .results-cards-row {{ display: grid; grid-template-columns: repeat(3, 1fr);
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
    .parlay-stats-banner {{ background: linear-gradient(135deg,rgba(232,112,58,0.10),rgba(234,179,8,0.08));
                            border: 1px solid var(--border); border-radius: 12px;
                            padding: 16px 20px; display: flex; gap: 24px; flex-wrap: wrap;
                            margin-bottom: 20px; align-items: center; }}
    .parlay-stats-banner .big {{ font-size: 34px; font-weight: 800; color: var(--3pm); line-height: 1; }}
    .parlay-stats-banner .sub {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
    .parlay-stat-item {{ text-align: center; }}
    .parlay-stat-item .val {{ font-size: 20px; font-weight: 700; }}
    .parlay-stat-item .lbl {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }}
    .parlay-card {{ background: var(--surface); border: 1px solid var(--border);
                    border-radius: 12px; padding: 16px; margin-bottom: 12px;
                    transition: border-color 0.15s; }}
    .parlay-card:hover {{ border-color: var(--accent); }}
    .parlay-card-header {{ display: flex; align-items: flex-start;
                           justify-content: space-between; gap: 12px; margin-bottom: 12px; }}
    .parlay-label {{ font-size: 15px; font-weight: 700; }}
    .parlay-meta {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 5px; align-items: center; }}
    .parlay-result-hit  {{ font-size: 11px; font-weight: 700; color: var(--hit);
                           background: rgba(34,197,94,0.12); padding: 2px 8px;
                           border-radius: 99px; white-space: nowrap; }}
    .parlay-result-miss {{ font-size: 11px; font-weight: 700; color: var(--miss);
                           background: rgba(239,68,68,0.12); padding: 2px 8px;
                           border-radius: 99px; white-space: nowrap; }}
    .parlay-result-partial {{ font-size: 11px; font-weight: 700; color: var(--3pm);
                              background: rgba(234,179,8,0.12); padding: 2px 8px;
                              border-radius: 99px; white-space: nowrap; }}
    .corr-badge {{ font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 99px; }}
    .corr-positive  {{ background: rgba(34,197,94,0.12);  color: var(--hit); }}
    .corr-mixed     {{ background: rgba(234,179,8,0.12);  color: var(--3pm); }}
    .corr-independent {{ background: var(--surface2); color: var(--muted); border: 1px solid var(--border); }}
    .type-badge {{ font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 99px;
                   background: var(--surface2); color: var(--muted); border: 1px solid var(--border); }}
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
  <div id="picks-container"></div>
</div>
<div id="tab-parlays" class="page"><div id="parlays-container"></div></div>
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
  top_picks_history: {top_picks_history_json},
  yesterday_summary: {yesterday_summary_json},
  opportunity_flags: {opportunity_flags_json},
  explorer:          {explorer_json},
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

// ── TODAY'S PICKS ──
function renderPicks() {{
  const c = document.getElementById('picks-container');
  const picks = DATA.today_picks;
  if (!picks.length) {{
    c.innerHTML = `<div class="empty"><div class="empty-icon">🏀</div>No picks yet for ${{DATA.today_str}}.<br>Check back after 11 AM PT.</div>`;
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
      const reviewBadge = reviewVerdict === 'trim'
        ? `<span class="review-badge-trim">${{isAutoReview ? '🤖 Auto-Review' : '⚠ Caution'}}</span>`
        : reviewVerdict === 'manual_skip'
          ? `<span class="review-badge-skip">${{isAutoReview ? '🤖 Stay Away' : '⚠ Flagged'}}</span>`
          : '';
      const reviewReasons = (p.trim_reasons && p.trim_reasons.length && reviewVerdict !== '')
        ? `<span style="font-size:10px;color:var(--muted);margin-left:4px">${{p.trim_reasons.join(' · ')}}</span>`
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
            ${{p.reasoning ? `<div class="reasoning">${{p.reasoning}}</div>` : ''}}
            ${{(function() {{
              const lu = p.lineup_update;
              if (!lu || lu.direction === 'unchanged') return '';
              const cls = lu.direction === 'up' ? 'lineup-update-badge-up' : 'lineup-update-badge-down';
              const arrow = lu.direction === 'up' ? '↑' : '↓';
              const timeStr = lu.updated_at ? new Date(lu.updated_at).toLocaleTimeString('en-US', {{hour:'numeric',minute:'2-digit'}}) : '';
              const triggered = (lu.triggered_by || []).join('; ');
              return `<button class="${{cls}}" onclick="toggleLineupUpdate(this)">${{arrow}} Updated ${{timeStr}}</button>` +
                `<div class="lineup-update-body">Triggered by: ${{triggered}}<br>` +
                `Revised (${{lu.revised_confidence_pct}}%): ${{lu.revised_reasoning}}<br>` +
                `Morning (${{p.confidence_pct}}%): ${{p.reasoning}}</div>`;
            }})()}}
            ${{p.tier_walk ? `<button class="tier-walk-toggle" onclick="toggleTierWalk(this)">&#9656; show reasoning</button><div class="tier-walk tier-walk-body">${{p.tier_walk}}</div>` : ''}}
          </div>
          <div class="pick-right">
            <div class="pick-line">
              ${{p.pick_value}}<span class="stat-type ${{propColor(pt)}}">${{pt}}</span>
            </div>
            ${{buildHitRate(p)}}
            <div class="conf-line">${{p.confidence_pct}}% conf</div>
          </div>
        </div>`;
    }});

    html += `</div></div></div>`;
  }});

  // ── Opportunity flags — amber/blue cards below main picks ───────────────
  const opps = (DATA.opportunity_flags || []).filter(f => f.date === DATA.today_str);
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
        return `<div style="margin:3px 0"><span style="color:#F5A623;font-weight:600">${{stat}} T${{info.tier}}</span>` +
               ` <span style="color:var(--muted);font-size:11px">${{hr}}${{whr}}</span></div>`;
      }}).join('');

      // Upgrade rows (upgrade_tiers — existing pick, higher tier now available)
      const utiers  = opp.upgrade_tiers || {{}};
      const utLines = Object.entries(utiers).map(([stat, info]) => {{
        const hr      = info.hit_rate_pct !== undefined ? ` ${{info.hit_rate_pct}}%` : '';
        const morning = info.morning_tier !== undefined ? `T${{info.morning_tier}}→` : '';
        return `<div style="margin:3px 0"><span style="color:#64B5F6;font-weight:600">${{stat}} ${{morning}}T${{info.tier}}</span>` +
               ` <span style="color:var(--muted);font-size:11px">${{hr}} (upgrade)</span></div>`;
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

  let html = `<div class="top-picks-header">⚡ TOP PICKS TODAY</div>
              <div class="top-picks-grid">`;

  tops.forEach(p => {{
    const pt        = p.prop_type || '';
    const color     = STAT_COLOR[pt] || 'var(--muted)';
    const gameTime  = p.game_time ? ` · ${{p.game_time}}` : '';
    const ironBadge = p.iron_floor
      ? `<div><span class="tp-iron-badge">🔒 Iron Floor</span></div>` : '';
    const reasoning = p.reasoning
      ? `<div class="tp-reasoning">${{p.reasoning}}</div>` : '';
    const tierWalk = p.tier_walk
      ? `<button class="tier-walk-toggle" onclick="toggleTierWalk(this)">&#9656; show reasoning</button><div class="tier-walk tier-walk-body">${{p.tier_walk}}</div>` : '';
    const lineupUpdateBadge = (function() {{
      const lu = p.lineup_update;
      if (!lu || lu.direction === 'unchanged') return '';
      const cls = lu.direction === 'up' ? 'lineup-update-badge-up' : 'lineup-update-badge-down';
      const arrow = lu.direction === 'up' ? '↑' : '↓';
      const timeStr = lu.updated_at ? new Date(lu.updated_at).toLocaleTimeString('en-US', {{hour:'numeric',minute:'2-digit'}}) : '';
      const triggered = (lu.triggered_by || []).join('; ');
      return `<button class="${{cls}}" onclick="toggleLineupUpdate(this)">${{arrow}} Updated ${{timeStr}}</button>` +
        `<div class="lineup-update-body">Triggered by: ${{triggered}}<br>` +
        `Revised (${{lu.revised_confidence_pct}}%): ${{lu.revised_reasoning}}<br>` +
        `Morning (${{p.confidence_pct}}%): ${{p.reasoning}}</div>`;
    }})();

    html += `
      <div class="top-pick-card" style="border-left-color:${{color}}">
        <div class="tp-left">
          <div class="tp-player">${{p.player_name}}</div>
          <div class="tp-meta">${{p.team}}${{gameTime}}</div>
          ${{ironBadge}}
          ${{reasoning}}
          ${{lineupUpdateBadge}}
          ${{tierWalk}}
        </div>
        <div class="tp-right">
          <div class="pick-line">
            ${{p.pick_value}}<span class="stat-type ${{propColor(pt)}}">${{pt}}</span>
          </div>
          <div class="tp-conf">${{p.confidence_pct}}% conf</div>
        </div>
      </div>`;
  }});

  html += `</div><div class="top-picks-divider"></div>`;
  c.innerHTML = html;
}}

renderInjuries();
renderTopPicks();
renderPicks();
renderResults();
renderAudit();

// ── PARLAYS ──
function renderParlays() {{
  const c = document.getElementById('parlays-container');
  const pd = DATA.parlays;
  const today = pd?.today || [];

  let html = '';

  // Stats banner (only if historical data exists)
  if (pd && pd.total > 0) {{
    html += `
      <div class="parlay-stats-banner">
        <div>
          <div class="big">${{pd.hit_rate_pct}}%</div>
          <div class="sub">parlay hit rate</div>
        </div>
        <div class="parlay-stat-item"><div class="val" style="color:var(--hit)">${{pd.hits}}</div><div class="lbl">hits</div></div>
        <div class="parlay-stat-item"><div class="val" style="color:var(--miss)">${{pd.misses}}</div><div class="lbl">misses</div></div>
        <div class="parlay-stat-item"><div class="val">${{pd.total}}</div><div class="lbl">graded</div></div>
      </div>`;
  }}

  if (!today.length) {{
    html += `<div class="empty"><div class="empty-icon">🎰</div>No parlays yet for ${{DATA.today_str}}.<br>Check back after picks are generated.</div>`;
    c.innerHTML = html;
    return;
  }}

  html += `<div class="section-header">${{today.length}} parlay${{today.length !== 1 ? 's' : ''}} — ${{DATA.today_str}}</div>`;

  // Build set of voided player names from today's picks for leg-risk detection
  const voidedPlayerNames = new Set(
    (DATA.today_picks || [])
      .filter(pk => pk.voided)
      .map(pk => (pk.player_name || '').toLowerCase())
  );

  today.forEach(p => {{
    const legs  = p.legs || [];
    const corr  = p.correlation || 'independent';
    const corrCls = corr === 'positive' ? 'corr-positive' : corr === 'mixed' ? 'corr-mixed' : 'corr-independent';
    const corrLabel = corr === 'positive' ? '⚡ positive' : corr === 'mixed' ? '~ mixed' : '· independent';
    const typeLabel = (p.type || '').replace(/_/g, ' ');

    // Result badge
    let resultBadge = '';
    if (p.result === 'HIT')     resultBadge = `<span class="parlay-result-hit">✓ HIT</span>`;
    else if (p.result === 'MISS') resultBadge = `<span class="parlay-result-miss">✗ MISS</span>`;
    else if (p.result === 'PARTIAL') resultBadge = `<span class="parlay-result-partial">~ PARTIAL</span>`;

    const voidedLegs = legs.filter(leg =>
      voidedPlayerNames.has((leg.player_name || '').toLowerCase())
    );
    const riskBanner = voidedLegs.length > 0
      ? `<div class="parlay-risk-banner">⚠ ${{voidedLegs.map(l => l.player_name).join(', ')}} listed OUT — parlay affected</div>`
      : '';

    html += `
      <div class="parlay-card">
        <div class="parlay-card-header">
          <div>
            <div class="parlay-label">${{p.label || 'Parlay'}}</div>
            <div class="parlay-meta">
              <span class="corr-badge ${{corrCls}}">${{corrLabel}}</span>
              <span class="type-badge">${{typeLabel}}</span>
              <span class="type-badge">${{legs.length}} legs</span>
              ${{resultBadge}}
            </div>
            ${{riskBanner}}
          </div>
        </div>
        <div class="parlay-legs">`;

    legs.forEach(leg => {{
      const pt   = leg.prop_type || leg.prop || '';
      const team = leg.team || '';
      const opp  = leg.opponent || '';
      const ha   = leg.home_away === 'H' ? 'vs' : '@';
      const conf = leg.confidence_pct ? `${{leg.confidence_pct}}%` : '';

      // Leg result icon (after grading)
      let legResultIcon = '';
      const lr = leg.result;
      if (lr === 'HIT')  legResultIcon = `<span class="leg-result-hit">✓</span>`;
      else if (lr === 'MISS') legResultIcon = `<span class="leg-result-miss">✗</span>`;

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
      html += `<div class="parlay-rationale">${{p.rationale}}</div>`;
    }}

    html += `</div>`;
  }});

  c.innerHTML = html;
}}

renderParlays();

// ── PLAYER EXPLORER ──
function renderResearch() {{
  const c = document.getElementById('research-container');
  if (!c) return;

  const explorerData = DATA.explorer || {{}};
  const players = Object.keys(explorerData).sort();

  if (!players.length) {{
    c.innerHTML = '<div style="padding:32px;color:var(--muted);font-size:13px">No player game log data available.</div>';
    return;
  }}

  // Collect all opponents for the opponent filter dropdown
  const allOpponents = new Set();
  players.forEach(p => {{
    (explorerData[p] || []).forEach(g => {{ if (g.opp) allOpponents.add(g.opp); }});
  }});
  const sortedOpps = Array.from(allOpponents).sort();

  let html = `
    <div style="max-width:780px;margin:0 auto;padding:16px 0">
      <div style="font-size:18px;font-weight:700;margin-bottom:16px;color:var(--fg)">Player Explorer</div>
      <div style="font-size:12px;color:var(--muted);margin-bottom:20px">
        Customizable search of the 2025-26 season game log.
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px;margin-bottom:16px">

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
    </div>`;

  c.innerHTML = html;
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
