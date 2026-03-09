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
WHITELIST_CSV  = ROOT / "playerprops" / "player_whitelist.csv"
CONTEXT_MD         = ROOT / "context" / "nba_season_context.md"
PLAYER_STATS_JSON  = DATA / "player_stats.json"
AUDIT_SUMMARY_JSON = DATA / "audit_summary.json"
PRE_GAME_NEWS_JSON = DATA / "pre_game_news.json"
STANDINGS_JSON                = DATA / "standings_today.json"
TEAM_DEFENSE_NARRATIVES_JSON = DATA / "team_defense_narratives.json"

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")

# ── Config ───────────────────────────────────────────────────────────
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 16384
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
        def _spread(val):
            try:
                f = float(val)
                return None if pd.isna(f) else round(f, 1)
            except Exception:
                return None
        games.append({
            "game_id":       row.get("game_id", ""),
            "game_time_utc": row.get("game_time_utc", ""),
            "home_team":     row.get("home_team_name", ""),
            "home_abbrev":   row.get("home_team_abbrev", ""),
            "away_team":     row.get("away_team_name", ""),
            "away_abbrev":   row.get("away_team_abbrev", ""),
            "venue_city":    row.get("venue_city", ""),
            "home_spread":   _spread(row.get("home_spread")),
            "away_spread":   _spread(row.get("away_spread")),
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



def load_whitelist() -> set:
    """
    Returns set of (lowercase_name, uppercase_team) tuples for active players.
    Filtering on both name AND team prevents traded players from appearing
    under their old team when game log rows for both teams exist.
    Empty set = no filtering.
    """
    if not WHITELIST_CSV.exists():
        print(f"[analyst] WARNING: whitelist not found, no player filtering applied.")
        return set()
    try:
        df = pd.read_csv(WHITELIST_CSV, dtype=str)
        active = df[df["active"].astype(str).str.strip() == "1"]
        pairs = set(zip(
            active["player_name"].str.strip().str.lower(),
            active["team_abbr"].str.strip().str.upper()
        ))
        print(f"[analyst] Whitelist loaded: {len(pairs)} active player-team pairs")
        return pairs
    except Exception as e:
        print(f"[analyst] WARNING: could not load whitelist: {e}")
        return set()

_ABBR_NORM: dict[str, str] = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP",
    "NY": "NYK", "UTAH": "UTA", "WSH": "WAS",
}

def _norm_team(abbr: str) -> str:
    a = str(abbr).upper().strip()
    return _ABBR_NORM.get(a, a)

def _extract_last(raw_name: str) -> str:
    """Return lowercased last name from either 'F. LastName' or 'FirstName LastName'."""
    n = str(raw_name).strip()
    if len(n) >= 3 and n[1] == "." and n[2] == " ":
        return n[3:].lower()
    parts = n.split()
    return parts[-1].lower() if parts else n.lower()

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


def load_out_players() -> set[tuple[str, str]]:
    """
    Build a set of (last_name_lower, norm_team_upper) tuples for players
    listed as OUT or DOUBTFUL in today's injury report.
    Used as a hard pre-filter before building quant context and prompt.
    """
    if not INJURIES_JSON.exists():
        return set()
    try:
        with open(INJURIES_JSON, "r") as f:
            raw = json.load(f)
    except Exception:
        return set()

    excluded: set[tuple[str, str]] = set()
    for team_key, entries in raw.items():
        if not isinstance(entries, list):
            continue
        norm_t = _norm_team(team_key)
        for entry in entries:
            status = (entry.get("status") or "").upper().strip()
            if status not in ("OUT", "DOUBTFUL"):
                continue
            raw_name = (entry.get("player_name") or entry.get("name") or "").strip()
            last = _extract_last(raw_name)
            if last:
                excluded.add((last, norm_t))
    return excluded


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


def build_player_context(game_log: pd.DataFrame, teams_today: list[str],
                          whitelist: set) -> str:
    """
    For whitelisted players on teams playing today, build a compact
    recent-performance summary to include in the prompt.
    If whitelist is empty, falls back to all players on today's teams.
    """
    if game_log.empty:
        return "No player game log data available."

    recent = game_log[game_log["team_abbrev"].isin(teams_today)].copy()
    if recent.empty:
        return "No recent game log data for today's teams."

    # Apply whitelist filter: match on both player name AND current team
    # This prevents traded players from appearing under their old team
    if whitelist:
        mask = recent.apply(
            lambda r: (
                r["player_name"].strip().lower(),
                r["team_abbrev"].strip().upper()
            ) in whitelist,
            axis=1
        )
        recent = recent[mask].copy()
        if recent.empty:
            return "No whitelisted players found for today's teams."

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



def load_season_context() -> str:
    """
    Load the manually-maintained NBA season context document.
    Injected into the prompt between the injury report and player game logs
    so the Analyst can correctly interpret both before making picks.
    Returns empty string gracefully if file is missing — never blocks a run.
    """
    if not CONTEXT_MD.exists():
        print("[analyst] WARNING: context/nba_season_context.md not found, skipping.")
        return ""
    try:
        text = CONTEXT_MD.read_text(encoding="utf-8").strip()
        # Strip HTML comment header block if present
        if text.startswith("<!--"):
            end = text.find("-->")
            if end != -1:
                text = text[end + 3:].strip()
        # Strip the ## TEAM DEFENSIVE PROFILES section — now auto-generated by quant.py
        # and injected separately. Leave the file itself untouched as a reference.
        tdp_idx = text.find("## TEAM DEFENSIVE PROFILES")
        if tdp_idx != -1:
            text = text[:tdp_idx].rstrip()
        print(f"[analyst] Season context loaded ({len(text.split())} words, TEAM DEFENSIVE PROFILES stripped)")
        return text
    except Exception as e:
        print(f"[analyst] WARNING: could not load season context: {e}")
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
            print("[analyst] standings_today.json not found — skipping playoff picture.")
            return ""
        with open(standings_path) as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[analyst] WARNING: could not load standings: {e}")
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
    print(f"[analyst] Playoff picture rendered ({date_str})")
    return "\n".join(lines).rstrip()


def format_team_defense_section(narratives_path=TEAM_DEFENSE_NARRATIVES_JSON) -> str:
    """
    Read team_defense_narratives.json (written by quant.py) and return a
    formatted ## TEAM DEFENSIVE PROFILES block for prompt injection.

    Returns a warning line if the file is missing or stale (date != today).
    Returns the warning line on any parse error — never blocks a run.

    Normal output format:
      ## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated YYYY-MM-DD)
      ATL (last 15g): Allows 112.3 PPG (rank: 18th)....
      BOS (last 15g): Allows 107.1 PPG (rank: 5th)....
      ...  (alphabetical, one line per team, no blank lines)
    """
    fallback = (
        "## TEAM DEFENSIVE PROFILES\n"
        "⚠ Team defense narratives unavailable for today — "
        "falling back to season context file."
    )
    try:
        if not Path(narratives_path).exists():
            print("[analyst] team_defense_narratives.json not found — using fallback warning.")
            return fallback
        with open(narratives_path) as fh:
            data = json.load(fh)
    except Exception as e:
        print(f"[analyst] WARNING: could not load team defense narratives: {e}")
        return fallback

    as_of = data.get("as_of", "")
    if as_of != TODAY_STR:
        print(
            f"[analyst] team_defense_narratives.json stale ({as_of} vs today {TODAY_STR})"
            " — using fallback warning."
        )
        return fallback

    narratives = data.get("narratives", {})
    if not narratives:
        print("[analyst] team_defense_narratives.json has no narratives — using fallback warning.")
        return fallback

    lines = [f"## TEAM DEFENSIVE PROFILES (last 15 games — auto-generated {as_of})"]
    for abbr in sorted(narratives):
        lines.append(narratives[abbr])
    print(f"[analyst] Team defense narratives loaded ({len(narratives)} teams, as of {as_of})")
    return "\n".join(lines)


def load_pre_game_news() -> str:
    """
    Load pre_game_news.json written by pre_game_reporter.py.
    Formats player_notes, game_notes, and context flags as a readable text block.
    Critical context flags are prepended with high-visibility formatting.
    Monitor flags are appended as a light note at the end.
    Returns empty string gracefully if file missing or empty — never blocks a run.
    """
    if not PRE_GAME_NEWS_JSON.exists():
        print("[analyst] pre_game_news.json not found — proceeding without news context.")
        return ""
    try:
        with open(PRE_GAME_NEWS_JSON) as f:
            data = json.load(f)
    except Exception as e:
        print(f"[analyst] WARNING: could not load pre_game_news.json: {e}")
        return ""

    player_notes = data.get("player_notes") or {}
    game_notes   = data.get("game_notes")   or {}
    flags        = data.get("suggested_context_updates") or []

    critical_flags = [f for f in flags if f.get("urgency") == "critical"]
    monitor_flags  = [f for f in flags if f.get("urgency") == "monitor"]

    if not player_notes and not game_notes and not critical_flags and not monitor_flags:
        print("[analyst] Pre-game news: no notable items today.")
        return ""

    sections = []

    # Critical context flags — prepended before PLAYER NEWS with high visibility
    if critical_flags:
        flag_lines = [
            "⚠ SEASON CONTEXT FLAGS — REVIEW BEFORE PICKING:",
            "These facts in the season context file may be outdated. Do not rely on the "
            "flagged entries below until the context file is manually updated. Use today's "
            "news items as the more reliable source for these players.",
            "",
        ]
        for flag in critical_flags:
            player   = flag.get("player_or_team", "Unknown")
            conflict = flag.get("conflict", "")
            flag_lines.append(f"CRITICAL: {player} — {conflict}")
        sections.append("\n".join(flag_lines))

    if player_notes:
        note_lines = ["PLAYER NEWS:"]
        for name, note in player_notes.items():
            note_lines.append(f"- {name.title()}: {note}")
        sections.append("\n".join(note_lines))

    if game_notes:
        note_lines = ["GAME NOTES:"]
        for game, note in game_notes.items():
            note_lines.append(f"- {game}: {note}")
        sections.append("\n".join(note_lines))

    # Monitor flags — lighter note appended at end
    if monitor_flags:
        monitor_lines = ["👀 MONITOR — context may be becoming stale:"]
        for flag in monitor_flags:
            player   = flag.get("player_or_team", "Unknown")
            conflict = flag.get("conflict", "")
            monitor_lines.append(f"- {player}: {conflict}")
        sections.append("\n".join(monitor_lines))

    n_crit      = len(critical_flags)
    n_all_flags = len(flags)
    flag_suffix = f", {n_all_flags} context flags (⚠ {n_crit} critical)" if critical_flags else ""
    print(
        f"[analyst] Pre-game news loaded: {len(player_notes)} player notes, "
        f"{len(game_notes)} game notes{flag_suffix}"
    )
    return "\n\n".join(sections)


def load_player_stats() -> dict:
    """Load pre-computed quant stats from player_stats.json."""
    if not PLAYER_STATS_JSON.exists():
        print("[analyst] WARNING: player_stats.json not found — quant context unavailable.")
        return {}
    try:
        with open(PLAYER_STATS_JSON, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"[analyst] WARNING: could not load player_stats.json: {e}")
        return {}


def load_player_profiles(player_stats: dict) -> str:
    """
    Extract pre-rendered player profile narratives from player_stats dict.
    Returns a formatted multi-player block for injection into the analyst prompt,
    or empty string if no profiles are available (e.g. first run before quant writes them).
    """
    blocks = []
    for player_name in sorted(player_stats):
        narrative = player_stats[player_name].get("profile_narrative")
        if narrative:
            blocks.append(narrative)
    if not blocks:
        return ""
    return "\n\n".join(blocks)


def build_quant_context(player_stats: dict) -> str:
    """
    Build a compact quant stats block for the prompt.
    Shows pre-computed best tiers and matchup-specific hit rates (vs_soft, vs_tough)
    at the best qualifying tier for each stat. Only includes players with at least
    one qualifying best tier.
    """
    if not player_stats:
        return "No quant stats available."

    lines = []
    for player_name in sorted(player_stats):
        s = player_stats[player_name]
        opp              = s.get("opponent", "?")
        best_tiers       = s.get("best_tiers") or {}
        matchup_hrs      = s.get("matchup_tier_hit_rates") or {}
        trends           = s.get("trend") or {}
        blowout_risk     = s.get("blowout_risk", False)
        spread_abs       = s.get("spread_abs")
        spread_splits    = s.get("spread_split_hit_rates") or {}
        on_b2b           = s.get("on_back_to_back", False)
        rest_days        = s.get("rest_days")
        games_last_7     = s.get("games_last_7", 0)
        dense_schedule   = s.get("dense_schedule", False)
        b2b_hit_rates      = s.get("b2b_hit_rates") or {}
        minutes_floor_data = s.get("minutes_floor") or {}

        # DvP line — one line per player showing positional defense ratings for all stats
        dvp         = s.get("positional_dvp") or {}
        source_tag  = "" if dvp.get("source") == "positional" else " (team-lvl)"
        dvp_pos     = dvp.get("position", "")
        defense_line = (
            f"  DvP [{dvp_pos}]{source_tag}: "
            f"PTS={dvp.get('pts_rating', '?')} "
            f"REB={dvp.get('reb_rating', '?')} "
            f"AST={dvp.get('ast_rating', '?')} "
            f"3PM={dvp.get('tpm_rating', '?')} "
            f"(n={dvp.get('n', 0)})"
        ) if dvp else ""

        stat_parts = []
        bounce_back_all    = s.get("bounce_back") or {}
        volatility_all     = s.get("volatility") or {}
        shooting_reg       = s.get("shooting_regression") or {}
        ft_safety          = s.get("ft_safety_margin") or {}
        for stat in ("PTS", "REB", "AST", "3PM"):
            best = best_tiers.get(stat)
            if not best:
                continue
            tier        = best["tier"]
            overall_pct = int(round(best["hit_rate"] * 100))
            trend       = trends.get(stat, "stable")

            matchup_at_tier = (matchup_hrs.get(stat) or {}).get(str(tier)) or {}
            soft  = matchup_at_tier.get("soft")
            tough = matchup_at_tier.get("tough")
            soft_str  = f"{int(round(soft['hit_rate']*100))}%({soft['n']}g)"  if soft  else "n/a"
            tough_str = f"{int(round(tough['hit_rate']*100))}%({tough['n']}g)" if tough else "n/a"

            # Spread split at this tier
            spread_stat = (spread_splits.get(stat) or {})
            comp_data   = spread_stat.get("competitive")
            blow_data   = spread_stat.get("blowout")
            comp_str = (
                f"{int(round(comp_data['hit_rates'].get(str(tier), 0)*100))}%({comp_data['n']}g)"
                if comp_data else "n/a"
            )
            blow_str = (
                f"{int(round(blow_data['hit_rates'].get(str(tier), 0)*100))}%({blow_data['n']}g)"
                if blow_data else "n/a"
            )

            # B2B hit rate at this tier (only shown when player is on B2B today)
            b2b_stat = b2b_hit_rates.get(stat)
            if on_b2b:
                if b2b_stat is not None:
                    b2b_pct = int(round(b2b_stat["hit_rates"].get(str(tier), 0) * 100))
                    b2b_str = f"{b2b_pct}%({b2b_stat['n']}g)"
                else:
                    b2b_str = "<5g"  # signal to apply one-tier-down fallback
                b2b_field = f" b2b={b2b_str}"
            else:
                b2b_field = ""

            # Bounce-back annotation: shown when lift > 1.0 or iron_floor
            bb_data = bounce_back_all.get(stat)
            if bb_data:
                if bb_data.get("iron_floor"):
                    bb_field = " [iron_floor]"
                elif bb_data.get("lift", 1.0) > 1.0:
                    bb_field = f" bb_lift={bb_data['lift']:.2f}({bb_data['n_misses']}miss)"
                else:
                    bb_field = ""
            else:
                bb_field = ""

            # Volatility tag
            vol = volatility_all.get(stat, {})
            vol_label = vol.get("label", "")
            if vol_label == "volatile":
                vol_tag = " [VOLATILE]"
            elif vol_label == "consistent":
                vol_tag = " [consistent]"
            else:
                vol_tag = ""  # moderate or missing = baseline, no tag

            # Shooting efficiency regression tag — PTS only
            shoot_flag = ""
            if stat == "PTS":
                sr_flag      = shooting_reg.get("fg_flag")
                sr_delta_pct = shooting_reg.get("fg_delta_pct")
                if sr_flag == "hot" and sr_delta_pct is not None:
                    shoot_flag = f" [FG_HOT:+{int(round(sr_delta_pct * 100))}%]"
                elif sr_flag == "cold" and sr_delta_pct is not None:
                    shoot_flag = f" [FG_COLD:{int(round(sr_delta_pct * 100))}%]"

                # FG% safety margin annotation (H11) — PTS only, at player's best qualifying tier
                fsm_tier_data = (ft_safety.get("tiers") or {}).get(str(tier), {})
                fsm_flag_val  = fsm_tier_data.get("flag", "")
                fsm_margin    = fsm_tier_data.get("margin")
                if fsm_flag_val == "ft_dominant":
                    pass  # no annotation needed — FTs + 3s cover the tier alone
                elif fsm_flag_val == "borderline" and fsm_margin is not None:
                    shoot_flag += f" [FG_MARGIN_THIN:{int(round(fsm_margin * 100))}%]"
                elif fsm_flag_val == "fragile" and fsm_margin is not None:
                    shoot_flag += f" [FG_MARGIN_NEG:{int(round(fsm_margin * 100))}%]"
                # safe or missing: no annotation — baseline, don't clutter

            stat_parts.append(
                f"  {stat}: tier={tier} overall={overall_pct}% "
                f"vs_soft={soft_str} vs_tough={tough_str} "
                f"competitive={comp_str} blowout_games={blow_str} "
                f"trend={trend}{b2b_field}{bb_field}{vol_tag}{shoot_flag}"
            )

        floor_val = minutes_floor_data.get("floor_minutes")
        avg_val   = minutes_floor_data.get("avg_minutes")
        if floor_val is not None and avg_val is not None:
            min_floor_str = f" min_floor={floor_val}(avg={avg_val})"
        else:
            min_floor_str = ""

        if stat_parts:
            spread_info  = f"spread_abs={spread_abs:.1f}" if spread_abs is not None else "spread=n/a"
            blowout_flag = " BLOWOUT_RISK=True" if blowout_risk else ""
            # Rest/fatigue flags in header
            if on_b2b:
                rest_flag = " B2B"
            elif rest_days is not None:
                rest_flag = f" rest={rest_days}d"
            else:
                rest_flag = ""
            dense_flag = " DENSE" if dense_schedule else ""
            l7_field   = f" L7:{games_last_7}g" if games_last_7 > 0 else ""
            lines.append(
                f"{player_name} (vs {opp} | {spread_info}{blowout_flag}{rest_flag}{dense_flag}{l7_field}{min_floor_str}):\n"
                + (defense_line + "\n" if defense_line else "")
                + "\n".join(stat_parts)
            )

    return "\n\n".join(lines) if lines else "No qualifying player quant stats."


def load_audit_summary() -> str:
    """Load rolling audit summary and format as readable text for the prompt."""
    if not AUDIT_SUMMARY_JSON.exists():
        return ""
    try:
        with open(AUDIT_SUMMARY_JSON) as f:
            s = json.load(f)
    except Exception:
        return ""

    n = s.get("entries_included", 0)
    if n < 3:
        return ""  # Not enough history to be meaningful yet

    overall = s.get("overall", {})
    hr      = overall.get("hit_rate_pct", 0)
    hits    = overall.get("hits",         0)
    misses  = overall.get("misses",       0)

    lines = [
        f"Season-to-date: {hits} hits / {misses} misses = {hr}% hit rate across {n} audit days.",
    ]

    # Per-prop breakdown
    prop_sum = s.get("prop_type_summary", {})
    if prop_sum:
        prop_parts = []
        for pt in ("PTS", "REB", "AST", "3PM"):
            d = prop_sum.get(pt)
            if d and d.get("picks", 0) >= 5:
                prop_parts.append(f"{pt}: {d['hit_rate_pct']}% ({d['hits']}/{d['picks']})")
        if prop_parts:
            lines.append("Per-prop: " + " | ".join(prop_parts))

    # Miss classification breakdown
    mc = s.get("miss_classification_totals", {})
    total_mc = sum(mc.values())
    if total_mc > 0:
        mc_parts = []
        for k in ("selection_error", "model_gap", "variance"):
            v = mc.get(k, 0)
            if v > 0:
                pct = round(v / total_mc * 100)
                mc_parts.append(f"{k}: {v} ({pct}%)")
        if mc_parts:
            lines.append("Miss classification: " + " | ".join(mc_parts))

    # Confidence calibration — helps spot over/under-confidence
    conf = s.get("confidence_calibration_totals", {})
    if conf:
        conf_parts = []
        for band in ("70-75", "76-80", "81-85", "86+"):
            d = conf.get(band)
            if d and d.get("picks", 0) >= 5:
                conf_parts.append(f"{band}%: {d['hit_rate_pct']}% ({d['picks']} picks)")
        if conf_parts:
            lines.append("Confidence calibration: " + " | ".join(conf_parts))

    # Parlay summary
    p = s.get("parlay_summary", {})
    p_total = p.get("total", 0)
    if p_total > 0:
        p_hr = round(p.get("hits", 0) / p_total * 100)
        lines.append(f"Parlays: {p.get('hits', 0)} hit / {p_total} total ({p_hr}%)")

    # Recent lessons (from last 5 audit days)
    lessons = s.get("recent_lessons", [])
    if lessons:
        lines.append("Recent lessons:")
        for l in lessons[-5:]:
            lines.append(f"  - {l}")

    # Recent reinforcements
    reinforcements = s.get("recent_reinforcements", [])
    if reinforcements:
        lines.append("Recent reinforcements:")
        for r in reinforcements[-5:]:
            lines.append(f"  + {r}")

    # Carry-forward recommendations
    recs = s.get("recent_recommendations", [])
    if recs:
        lines.append("Carry-forward recommendations:")
        for r in recs[-3:]:
            lines.append(f"  → {r}")

    return "\n".join(lines)


# ── Prompt builder ───────────────────────────────────────────────────

def build_prompt(games: list[dict], player_context: str, injuries: dict, audit_context: str, season_context: str, quant_context: str = "", audit_summary: str = "", pre_game_news: str = "", player_profiles: str = "", playoff_picture: str = "", team_defense: str = "") -> str:
    games_block = json.dumps(games, indent=2)
    injuries_block = json.dumps(injuries, indent=2)

    pre_game_section = (
        "## PRE-GAME NEWS\n"
        "The following news items were published in the last 48 hours and are material to "
        "today's picks. These supplement — do not replace — the structured injury report "
        "above. Cross-reference player availability and role notes here before finalizing "
        "confidence levels.\n\n"
        f"{pre_game_news}\n\n"
    ) if pre_game_news else ""

    playoff_picture_section = f"{playoff_picture}\n\n" if playoff_picture else ""
    team_defense_section    = f"{team_defense}\n\n"    if team_defense    else ""

    player_profiles_section = (
        "## PLAYER PROFILES — LIVE STATISTICAL PORTRAITS\n"
        "Pre-computed from the same game log data as the quant stats above. Use these to "
        "identify structural risk factors (B2B-sensitive players, blowout-sensitive scorers, "
        "FG-dependent players in tough matchups) and to contextualize recent hit sequences "
        "(current streak, longest miss streak). These are informational — they do not override "
        "tier hit rates but help explain why a high-hit-rate player might be structurally "
        "fragile today.\n\n"
        f"{player_profiles}\n\n"
    ) if player_profiles else ""

    return f"""You are the Analyst for NBAgent, an NBA player props selection system.

Today is {TODAY_STR}.

## YOUR TASK
Select high-confidence player prop picks for today's games. Focus on:
- Points (PTS)
- Rebounds (REB)
- Assists (AST)
- 3-pointers made (3PM)

## TIER SYSTEM — HOW TO THINK ABOUT THRESHOLDS
This system targets fixed tier thresholds that match how parlays are structured on betting platforms.
Do NOT pick arbitrary lines. Only use values from these tiers:

  PTS tiers:  10 / 15 / 20 / 25 / 30
  REB tiers:  2 / 4 / 6 / 8 / 10 / 12
  AST tiers:  2 / 4 / 6 / 8 / 10 / 12
  3PM tiers:  1 / 2 / 3 / 4

**Hit definition:** A pick is a HIT if actual_value >= pick_value. Exactly hitting the threshold counts
as a hit — a player scoring exactly 20 pts on a 20-tier pick is a HIT, not a miss.

For each player/stat, your job is to find the highest tier where their hit rate across recent games
is strong enough to justify ≥70% confidence. Work DOWN from the player's ceiling until you find
a tier with a reliable floor.

Example reasoning process for PTS:
  - Player averages 21 pts but has inconsistent games (14, 22, 18, 28, 16, 24, 12, 19, 21, 17)
  - At the ≥20 tier: games with pts≥20: 22,28,24,21 = 4/10 = 40% → skip
  - At the ≥15 tier: games with pts≥15: 22,18,28,16,24,19,21,17 = 8/10 = 80% → this is the pick
  - pick_value = 15, confidence = 80%

The edge is in finding floors the market undervalues. Season averages overstate consistency.
A player who averages 21 pts but only reaches 20 half the time is a 15-tier pick, not a 20-tier pick.

## SELECTION RULES
- Weight recent form (last 5–10 games) heavily — season averages are misleading
- Minimum 5 recent games required to evaluate any player
- INJURY EXCLUSION (HARD RULE): Players listed as OUT or DOUBTFUL have been removed from the
  quant context and player logs before this prompt was built. Do NOT generate any pick for a
  player who does not appear in the ## QUANT STATS section. If a player appears in the game
  log but not in QUANT STATS, treat them as excluded — do not pick them.
- Factor in teammate injuries (affects usage/role) and back-to-back fatigue
- Use SEASON CONTEXT to distinguish stable baselines from genuine injury-driven role changes
- Pick as many qualifying props as there are — don't limit volume artificially
- Only output picks with confidence_pct ≥ 70
- Where a player's stats card shows bb_lift > 1.15 for a stat at their qualifying tier, treat a post-miss pick as a neutral-to-positive signal rather than a negative one. Where [iron_floor] is shown, a single prior miss carries no negative weight.
- REB props — minimum confidence floor: Do not output any REB pick with confidence_pct below 78%. REB is the system's highest-variance category (season hit rate 66.7% vs 85.7% for PTS). A REB pick that would otherwise qualify at 72% or 75% confidence does not meet the bar — skip it entirely.
- REB props — pick value gate: The pick value must be at or below the player's L10 25th-percentile REB output. Compute this as the 3rd-lowest REB value across their last 10 games. If the intended tier exceeds this floor, move down one tier. If no valid tier exists at or below the floor, skip the REB prop entirely.
- REB props for offensive-first players: For players whose primary role is scoring or playmaking (PTS avg > 20, or AST avg > 6 across their recent games), the 25th-percentile gate above applies with extra strictness — if the player's REB floor (lowest value in their last 10 games) is within 2 of your intended pick value, skip the REB prop and pick their scoring or assists prop instead. A thin floor at high volume is a trap. Both the 78% confidence minimum AND the floor gate must pass before any REB pick is output.
- Tier walk-down discipline: Always evaluate tiers from highest to lowest for the stat.
  Never select a tier if the tier immediately above it also qualifies (≥70% hit rate in
  recent window). The tier_walk field must document every tier evaluated — if you skipped
  tiers without checking them, that is a selection error the Auditor will flag. Show your
  work.

## TIER CEILING RULES — backed by full-season calibration data
The following tiers are systemically miscalibrated: players selected at these tiers hit
significantly below the 70% confidence floor when measured over a full season (6,437 instances).
Treat them as requiring exceptional justification — do not pick them by default.

  REB T8+: actual season hit rate 63.2% (n=247) at w10; improves to 71.0% (n=200) at w20 window.
    Only select if player has hit 7+/10 at this tier in their recent window. Otherwise cap at T6.
    Do NOT use opp_defense_rating as a justification for REB T8 — see REB rule below.

  AST T6+: actual season hit rate 65.1% (n=255). Only select if player has hit 7+/10
    at this tier AND their role context explicitly supports elevated assist load today
    (e.g. primary ball handler with multiple creators absent). Otherwise cap at T4.

  PTS T25+: actual season hit rate 66.8% (n=253) — below the 70% system threshold. For this
    tier specifically, require ≥80% hit rate in the player's recent window (8+/10 at the ≥25
    tier) before selecting. The tier calibrates below floor league-wide; a higher individual bar
    is needed to compensate. Essentially never select PTS T30 — season hit rate 56.8% (n=81).

  3PM T2: calibrates at 71.4% (n=441) — above the 70% threshold. No ceiling rule needed.
  3PM T3+: actual season hit rate 58.6% (n=157). Only select if player has hit 7+/10 at this
    tier in their recent window AND today's game has a high pace tag. Otherwise cap at T2.

Note: trend direction (up/stable/down) and home/away context are available in the data below
but have not shown predictive value in historical calibration. Do not weight them as primary
selection signals.

## TODAY'S GAMES
{games_block}

## CURRENT INJURY REPORT
{injuries_block}

{pre_game_section}## SEASON CONTEXT — READ BEFORE INTERPRETING INJURIES OR PLAYER LOGS
{season_context if season_context else "No season context file found."}

{playoff_picture_section}{team_defense_section}## PLAYER RECENT PERFORMANCE (last {RECENT_GAME_WINDOW} games)
{player_context}

## QUANT STATS — PRE-COMPUTED TIER ANALYSIS
These numbers are computed from the full season game log — larger sample than the L10 above.
"overall" = hit rate at this tier across last 10 games.
"vs_soft" / "vs_tough" = hit rate at this tier across the full season, split by opponent defensive quality.

KEY RULES — MATCHUP QUALITY:
- The DvP line shows today's opponent's defense rating for this player's position.
  Use the DvP PTS rating (when source=positional) as the primary signal for matchup quality.
- vs_soft / vs_tough on each stat line show this player's historical hit rate split by
  opponent defensive quality — use these together with the DvP rating for confirmation.
- If the DvP rating is "tough" AND vs_tough drops materially below overall (e.g. 80% → 50%),
  downgrade confidence or move to a lower tier.
- If the DvP rating is "soft" AND vs_soft is significantly higher than overall, you may pick
  a higher tier than the overall rate alone suggests.
- "n/a" on vs_soft/vs_tough means insufficient sample (<3 games) — fall back to DvP line only.

OPPONENT DEFENSE — POSITIONAL DvP:
Each player has a "DvP [POS]" line showing position-specific allowed averages for PTS/REB/AST/3PM
against today's opponent. Ratings are soft/mid/tough, ranked within that position group across
all 30 teams (not team-level overall).

  When source is positional (no "team-lvl" tag): use the per-stat rating directly — it reflects
  how that opponent defends this player's specific position group. More precise than team-level.

  When source is team-level fallback (tagged "team-lvl"): the positional sample was too small
  (<10 games). Treat with normal weight as before.

  The (n=) value is the number of player-game observations behind the rating.
  Weight more heavily when n ≥ 20. Treat n < 15 with mild skepticism even if source=positional.

Stat-specific rules remain unchanged:

  PTS / AST: use the positional DvP rating as the primary defense signal when source=positional.
    Soft = favorable (upgrade bias or higher confidence).
    Tough = unfavorable (downgrade one tier or reduce confidence by 5–10%).

  AST T4+ HARD GATE — low-volume passers vs non-soft defenses:
    If you are considering an AST pick at T4 or higher AND either of the following is true:
      (a) the player's position is PF or C, OR
      (b) the player's raw_avgs AST is below 4.0 per game
    → the opponent's AST DvP rating MUST be "soft" to proceed.
    → If the AST DvP rating is "mid" or "tough", SKIP this pick entirely — regardless of overall
      hit rate, confidence, or other signals. This gate is unconditional.
    This prevents low-volume or frontcourt passers from being picked at AST T4+ against defenses
    that historically suppress assists at that position.

  REB: positional DvP does NOT make REB a valid defense signal. Do not use REB rating as
    justification for a REB over. Rebounds are driven by pace, opponent FG%, and frontcourt
    competition — none captured by allowed-per-position averages. Ignore REB rating entirely.

  3PM: opp_defense is NOISE regardless of positional granularity (lift variance 0.053 across
    6,437 instances, corrected grading). Do not weight 3PM rating in either direction.

KEY RULES — REST & FATIGUE:
- Player header shows "B2B" (back-to-back, 0 days rest), "rest=Xd" (days since last game),
  "DENSE" (4+ games in 5 nights), and "L7:Xg" (games played in last 7 days).
- When "B2B" is shown:
  → Use "b2b=" rate instead of overall hit rate for tier selection.
  → If b2b="<5g" (fewer than 5 B2B games in history), apply a conservative one-tier-down
    adjustment from your normal best tier. Do not pick the same tier as non-B2B.
- When "DENSE" is shown (even without B2B): cumulative fatigue is likely.
  → Reduce confidence by 5–10% across all stats for that player.
- rest_days ≥ 3 = well-rested; no downward adjustment needed.

MINUTES FLOOR — THRESHOLD EVENT FRAGILITY:
- The min_floor= value in each player header is the 10th-percentile of their L10 minutes.
  It represents the worst-case realistic playing time in recent games.
- For PTS picks at T20 or higher: if min_floor < 24, apply mild caution — the player has
  shown capacity for sub-24 minute games recently, which creates structural risk for high
  point totals. Consider stepping down one tier or reducing confidence by 3-5%.
- For REB and AST picks: if min_floor < 20, apply the same caution.
- If min_floor >= avg_minutes - 3 (floor is close to average = very consistent minutes),
  treat this as a mild positive signal — the player rarely has outlier-low minutes nights.
- Do NOT apply this rule when the player's avg_minutes > 36: elite-usage players rarely
  sit regardless of game script.
- MIN_FLOOR CONFIDENCE CAP: For any PTS pick where the player's floor_minutes (from the
  minutes_floor field) is below 24.0, cap the final stated confidence_pct at 84%, regardless
  of hit streak length, iron_floor tag, or any other signal. Do not assign 85%, 86%, 87%,
  88%, or higher confidence to a PTS pick on a player whose floor_minutes < 24. The iron_floor
  and consistent tags reflect historical frequency but do not account for matchup-specific
  suppression in games where the player's baseline minutes exposure is below the 24-minute
  threshold — streak-based signals overstate reliability when the underlying minutes floor
  cannot support them. Apply this cap silently; do not explain it in the reasoning field
  unless it changes what you would otherwise have stated.

KEY RULES — SEQUENTIAL GAME CONTEXT:
- REB slump-persistent (confirmed signal, n=300, window=10):
  Post-miss REB hit rate drops to 62.0% vs baseline 75.0% (lift=0.83). Rebounds do NOT bounce back
  the next game — a miss is predictive of another miss.
  → If a player missed their REB tier last game, apply −5% confidence OR prefer one tier lower.
  → This applies regardless of opponent or home/away. The pattern holds across conditions.
- 3PM cold-streak decline (confirmed signal, n=161, severe cold = L5 hit rate ≥10pp below L10/L20):
  Players in a severe 3PM cold streak hit at 68.3% next game (lift=0.87 vs baseline 78.2%).
  Unlike other stats, 3PM cold streaks do not self-correct at N+1 — the slump persists or deepens.
  → If a player's recent L5 3PM output is materially below their L10/L20 rate, apply −5% confidence
    or skip the pick. Prefer cold-streak 3PM players only if facing a soft matchup.
- 3PM trend=down mandatory step-down (live rule, motivated by observed miss pattern):
  If the trend field for a player's 3PM stat is "down", you MUST step down exactly one full tier
  from your analytically selected floor before finalizing the pick.
  Example: best qualifying tier is T2 with 9/10 hit rate → trend=down → pick T1 instead.
  Do NOT use the aggregate hit rate to override this step-down. A 9/10 overall rate at T2
  means nothing if the directional signal is declining — the 0-make outcome is within range.
  This rule does not apply to PTS or AST (trend has shown no sequential signal for those stats).
  If stepping down would take the tier below the minimum valid tier (T1 for 3PM), skip the
  3PM pick entirely for that player.
- 3PM hard skip — trend=down AND limited minutes:
  If a player's 3PM trend is "down" AND their avg_minutes_last5 is ≤ 30, SKIP all 3PM picks
  for that player, including T1. Do not apply the step-down rule — skip outright.
  Rationale: low-minute players have fewer 3PM attempts per game; a declining trend in limited
  minutes means the absolute floor on makes is very close to zero. T1 (1+ make) is not a safe
  floor in this profile.
  This gate applies to the trend=down case only. A player with trend=stable or trend=up and
  avg_minutes_last5 ≤ 30 may still qualify for T1 via normal tier selection logic.
- PTS, AST: insufficient sequential signal. No adjustment needed based on last-game result.

KEY RULES — SPREAD / BLOWOUT RISK:
- "BLOWOUT_RISK=True" means this team is heavily favored (spread_abs > 8). Stars get pulled in
  Q4 garbage time when the game is decided early, killing OVER props on counting stats.
  → When BLOWOUT_RISK=True: prefer one tier lower than your best tier, OR reduce confidence by
    10–15 pct. Do not skip the pick entirely unless confidence would drop below 70%.
  → When spread_abs > 13: cap confidence at 80% for ALL players on the favored team.
- "competitive" split = historical hit rate in close games (spread_abs ≤ 6.5).
  "blowout_games" split = historical hit rate in non-competitive games (spread_abs > 6.5).
  → If blowout_games hit rate is materially lower than competitive (e.g., 80%→50%), factor that
    in even when BLOWOUT_RISK is False — the pattern may be real.
- When spread=n/a (no spread data available), rely on blowout_risk flag and qualitative judgment.
- BLOWOUT_RISK SECONDARY SCORER SKIP: When a player's pick has BLOWOUT_RISK flagged AND the
  player's team is the large underdog (spread of +8 or worse, i.e. the player's team is
  expected to lose by 8+ points), AND the player is not the team's primary scoring option
  (i.e. the player does not lead the team in PPG or is not the designated first option in the
  stat line), do NOT select any PTS pick for this player regardless of hit rate. Do not apply
  the -5% BLOWOUT_RISK deduction and proceed — skip the PTS pick entirely. Secondary scorers
  on large underdogs face asymmetric usage compression in the second half of blowout games:
  they accumulate playing time without scoring efficiency as the game deteriorates, and their
  aggregate T-pick hit rates do not price in this game-script effect. The spread threshold
  (+8 or worse) is the point at which blowout probability is high enough to make this a
  reliable skip rather than a marginal reduction. Primary scorers (team PPG leaders, first
  options) are exempt from this skip because their usage is more protected even in blowout
  scenarios. If in doubt about whether a player is a primary or secondary scorer, apply the skip.

KEY RULES — VOLATILITY:
- Every stat line is tagged [consistent], [VOLATILE], or unlabeled (moderate).
- Consistent: player hits this tier in a stable, predictable pattern. No adjustment needed.
- Moderate: normal variance. No adjustment needed. This is the baseline.
- [VOLATILE]: player hits this tier in streaks — long runs of hits followed by cold stretches.
  A volatile player at 75% hit rate is riskier than a consistent player at 72%.
  Rules when [VOLATILE] is present:
    1. Reduce confidence by 5% before applying other adjustments.
    2. Do not select a volatile prop as a standalone Top Pick unless confidence after
       reduction still clears 85% AND there is supporting context (iron_floor, soft defense,
       favorable rest).
    3. Flag the volatility in the reasoning field so the Auditor can track whether
       volatile picks underperform over time.
  Do not apply the volatility penalty if the player has [iron_floor] on this stat —
  iron floor already captures the consistency signal more precisely.

KEY RULES — SHOOTING EFFICIENCY REGRESSION:
- [FG_HOT:+X%] and [FG_COLD:-X%] annotations are informational only. Do not apply any confidence
  adjustment in either direction based on these flags.
- Rationale: backtested across 521 instances — FG_HOT lift=1.014 (noise); FG_COLD lift=1.128
  (counterintuitively positive). Tier selection is based on counting-stat hit rates, not FG%, so
  shooting efficiency fluctuations do not predict next-game PTS tier outcomes. Treat both flags
  as context only — visible in the quant block for transparency, not directive.

KEY RULES — FG% SAFETY MARGIN (H11 — backtested, 537 instances):
- PTS stat lines may show [FG_MARGIN_THIN:X%] based on the player's structural shooting margin.
  This is the gap between their season FG% and the minimum FG% needed to reliably hit their
  best PTS tier at typical volume (accounting for free throw and 3PM contributions).
  A thin margin means the player needs near-baseline shooting to hit the tier; any cold game
  risks a miss.
- [FG_MARGIN_THIN:X%]: margin is X% — below the 10% safety floor.
  Backtested hit rate at this margin: 57.6% across 165 instances (19.8pp below safe picks).
  57.6% is below the system's 70% pick threshold.
  → DO NOT pick at the flagged tier. Drop exactly one tier and re-evaluate.
  → If the lower tier also qualifies (≥70% hit rate), pick there instead.
  → If no lower tier qualifies, skip the PTS prop and consider REB/AST instead.
  → Document the tier drop in tier_walk and reasoning fields.
  This rule overrides positive signals at the same tier (iron_floor, soft defense, etc.).
  A FG_MARGIN_THIN player with iron_floor is still a borderline shooter — drop the tier.
- [FG_MARGIN_NEG:X%]: margin is negative — player's season FG% is below breakeven.
  Apply the same tier-drop rule. This flag is rare for whitelisted players.
- If the flag is absent: player has a safe margin (≥10%). No adjustment needed.
- This rule applies to PTS props only. REB/AST/3PM are unaffected.

KEY RULES — HIGH CONFIDENCE GATE (81%+): Before assigning confidence_pct of 81 or higher, all three of the following conditions must be met. If any condition fails, cap confidence at 80% or lower — do not round up.
Condition A — Rest/availability: Player is NOT on a back-to-back (on_back_to_back = false), OR player averages ≥30 minutes per game in their last 10 games as a confirmed starter. Non-stars on B2B nights have demonstrated DNP and minutes-restriction risk that makes 81%+ confidence structurally unsound regardless of historical hit rate.
Condition B — Defense signal quality: The opp_defense or DvP rating used to justify the pick must come from the quant data (positional DvP with n ≥ 15, or team-level opp_defense rank). Do not assign 81%+ based on a general "soft/tough" label alone — require the underlying rank and allowed average to confirm it. If the quant data is unavailable or contradicts the label, treat the matchup as neutral and remove it as a confidence-boosting factor.
Condition C — Confirming signals: At least two independent signals must support the pick beyond hit rate alone. Qualifying signals: favorable DvP rating (confirmed by quant rank), iron_floor tag, consistent volatility tag, soft blowout_risk context, rest advantage (≥2 rest days), or a pre-game news note confirming full availability and normal role. Hit rate alone — even 9/10 or 10/10 — does not satisfy Condition C by itself.

{quant_context if quant_context else "No quant stats available."}

{player_profiles_section}## AUDITOR FEEDBACK FROM PREVIOUS DAYS
{audit_context}

## ROLLING PERFORMANCE SUMMARY
{audit_summary if audit_summary else "Insufficient audit history yet (need 3+ days)."}

## ANALYSIS APPROACH
Work through each player mentally before writing output. Keep your per-player reasoning
to 3 lines maximum:
  Line 1: Best qualifying tier + hit rate (e.g. "PTS T20: 9/10 ✓")
  Line 2: Key adjustment applied if any (e.g. "VOLATILE -5%, B2B rate used, BLOWOUT -10%")
  Line 3: Final confidence + pick or skip decision (e.g. "→ 80% PICK" or "→ 65% SKIP")
Do not narrate every rule check. Do not recalculate L10 averages in writing — work from
the quant data provided. Brief internal notes only; the JSON output is what matters.

## OUTPUT FORMAT — EMIT THIS FIRST, BEFORE ANY OTHER TEXT
Your response MUST begin with the JSON array on the very first line. No preamble.
No "I'll analyze..." No game context review block. No markdown headers before the JSON.
The JSON array starts at character 0 of your response.

After the closing ] of the JSON array, you may include a brief optional summary
(3–5 lines maximum) noting any notable skips or edge cases. Nothing more.

JSON schema — each pick:
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
    "hit_rate_display": "string — fraction from last 10 games at this tier, e.g. '8/10'",
    "trend": "up | stable | down",
    "opp_defense_rating": "soft | mid | tough | unknown",
    "tier_walk": "string — compact walk-down showing tiers checked, e.g. 'PTS: 25→4/10 20→9/10✓'",
    "iron_floor": "true | false",
    "reasoning": "One tight sentence: key reason this floor holds today. Max 15 words."
  }}
]

pick_value must be one of the valid tier values listed above. No other values allowed.
direction is always OVER.
iron_floor must be true if and only if the quant stat line for this pick showed [iron_floor]. Otherwise false.
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

    # Fallback: if response has prose before the JSON array, find the array start
    bracket_idx = raw.find('[')
    if bracket_idx > 0:
        print(f"[analyst] WARNING: response had {bracket_idx} chars of prose before JSON — extracting array")
        raw = raw[bracket_idx:]
    # Also handle case where response ends after ] with trailing prose
    last_bracket = raw.rfind(']')
    if last_bracket != -1 and last_bracket < len(raw) - 1:
        raw = raw[:last_bracket + 1]

    try:
        picks = json.loads(raw)
        if not isinstance(picks, list):
            raise ValueError("Response is not a JSON array")
        return picks
    except Exception as e:
        print(f"[analyst] ERROR parsing Claude response: {e}")
        print(f"[analyst] Raw response (first 500 chars):\n{raw[:500]}")
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
        if "iron_floor" not in p:
            p["iron_floor"] = False

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

    whitelist = load_whitelist()

    player_context = build_player_context(game_log, teams_today, whitelist)

    audit_context = build_audit_context(audit_entries)

    season_context  = load_season_context()
    playoff_picture = render_playoff_picture()
    team_defense    = format_team_defense_section()

    player_stats = load_player_stats()
    print(f"[analyst] Loaded quant stats for {len(player_stats)} players")

    # Hard pre-filter: exclude OUT/DOUBTFUL players before any prompt building
    out_players = load_out_players()
    if out_players:
        filtered_stats: dict = {}
        for pname, pdata in player_stats.items():
            last = _extract_last(pname)
            norm_t = _norm_team(pdata.get("team", ""))
            if (last, norm_t) in out_players:
                print(f"[analyst] EXCLUDED (OUT/DOUBTFUL): {pname} ({pdata.get('team', '')})")
            else:
                filtered_stats[pname] = pdata
        player_stats = filtered_stats
        print(f"[analyst] After injury pre-filter: {len(player_stats)} players remaining")

    quant_context = build_quant_context(player_stats)

    player_profiles = load_player_profiles(player_stats)
    if player_profiles:
        print(f"[analyst] Loaded player profile narratives")

    audit_summary = load_audit_summary()
    if audit_summary:
        print(f"[analyst] Loaded rolling audit summary")
    else:
        print(f"[analyst] No audit summary yet (need 3+ audit days)")

    pre_game_news = load_pre_game_news()

    prompt = build_prompt(
        games, player_context, injuries, audit_context,
        season_context, quant_context, audit_summary,
        pre_game_news=pre_game_news,
        player_profiles=player_profiles,
        playoff_picture=playoff_picture,
        team_defense=team_defense,
    )

    picks = call_analyst(prompt)
    print(f"[analyst] Claude returned {len(picks)} picks")

    save_picks(picks)


if __name__ == "__main__":
    main()
