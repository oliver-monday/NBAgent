#!/usr/bin/env python3
"""
lineup_update.py — Afternoon Lineup Amendment Agent

Runs hourly after lineup_watch.py. Diffs current lineup/injury state against
the morning snapshot written by analyst.py, then calls Claude to assess impact
on affected picks. Writes a `lineup_update` sub-object to each affected pick
in picks.json.

No-op conditions:
  - lineups_today.json missing → skip
  - snapshot_at_analyst_run not in lineups_today.json → skip
  - no starter changes detected → skip (no LLM call)
  - no open picks affected by the changes → skip
  - all affected picks past tip-off cutoff → skip
"""

import json
import os
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).parent.parent
DATA          = ROOT / "data"
PICKS_JSON    = DATA / "picks.json"
LINEUPS_JSON  = DATA / "lineups_today.json"
INJURIES_JSON = DATA / "injuries_today.json"
MASTER_CSV    = DATA / "nba_master.csv"

# ── Config ─────────────────────────────────────────────────────────────────────
MODEL          = "claude-sonnet-4-6"
MAX_TOKENS     = 2048
CUTOFF_MINUTES = 20    # skip picks for games tipping off within this many minutes
ET             = ZoneInfo("America/Los_Angeles")   # repo-wide convention
TODAY_STR      = dt.datetime.now(ET).strftime("%Y-%m-%d")

# Team abbreviation normalization — mirrors analyst.py / lineup_watch.py
_ABBR_NORM: dict[str, str] = {
    "GS": "GSW", "SA": "SAS", "NO": "NOP",
    "NY": "NYK", "UTAH": "UTA", "WSH": "WAS",
}


def _norm(abbr: str) -> str:
    a = str(abbr).upper().strip()
    return _ABBR_NORM.get(a, a)


# ── Player stats helpers ────────────────────────────────────────────────────────

PLAYER_STATS_JSON = DATA / "player_stats.json"


def load_player_stats() -> dict:
    """Load player_stats.json written by quant.py. Returns {} on any error."""
    if not PLAYER_STATS_JSON.exists():
        return {}
    try:
        with open(PLAYER_STATS_JSON) as fh:
            return json.load(fh)
    except Exception as e:
        print(f"[lineup_update] WARNING: could not load player_stats.json: {e}")
        return {}


def build_pick_quant_summary(player_name: str, prop_type: str, player_stats: dict) -> str:
    """
    Build a slim quant summary for a single pick player + prop type.
    Returns empty string when player not in player_stats (graceful degradation).

    Output format (single line):
      quant: tier=T vs_soft=X%(Ng) vs_tough=X%(Ng) trend=up/stable/down
             opp_def=soft/mid/tough bb_lift=X.XX [iron_floor] [VOLATILE/consistent]
             min_floor=X(avg=Y)
    Fields are omitted when not available — never show "n/a" or "null".
    """
    s = player_stats.get(player_name) or player_stats.get(player_name.strip())
    if not s:
        return ""

    best_tiers  = s.get("best_tiers") or {}
    best        = best_tiers.get(prop_type)
    if not best:
        return ""

    tier        = best["tier"]
    overall_pct = int(round(best["hit_rate"] * 100))
    trend       = (s.get("trend") or {}).get(prop_type, "stable")

    # Matchup hit rates at this tier
    matchup_hrs  = s.get("matchup_tier_hit_rates") or {}
    matchup_stat = (matchup_hrs.get(prop_type) or {}).get(str(tier)) or {}
    soft_data    = matchup_stat.get("soft")
    tough_data   = matchup_stat.get("tough")
    soft_str  = f"{int(round(soft_data['hit_rate']*100))}%({soft_data['n']}g)"  if soft_data  else ""
    tough_str = f"{int(round(tough_data['hit_rate']*100))}%({tough_data['n']}g)" if tough_data else ""

    # Opponent defense rating (team-level)
    opp_def    = (s.get("opp_defense") or {}).get(prop_type, {})
    opp_rating = opp_def.get("rating", "")  # "soft" | "mid" | "tough"

    # Bounce-back
    bb_data = (s.get("bounce_back") or {}).get(prop_type) or {}
    if bb_data.get("iron_floor"):
        bb_str = " [iron_floor]"
    elif bb_data.get("lift", 1.0) > 1.0:
        bb_str = f" bb_lift={bb_data['lift']:.2f}({bb_data['n_misses']}miss)"
    else:
        bb_str = ""

    # Volatility
    vol_label = ((s.get("volatility") or {}).get(prop_type) or {}).get("label", "")
    vol_str = " [VOLATILE]" if vol_label == "volatile" else " [consistent]" if vol_label == "consistent" else ""

    # Minutes floor
    mf        = s.get("minutes_floor") or {}
    floor_val = mf.get("floor_minutes")
    avg_val   = mf.get("avg_minutes")
    mf_str    = f" min_floor={floor_val}(avg={avg_val})" if floor_val is not None and avg_val is not None else ""

    parts = [f"tier=T{tier} overall={overall_pct}%"]
    if soft_str:
        parts.append(f"vs_soft={soft_str}")
    if tough_str:
        parts.append(f"vs_tough={tough_str}")
    parts.append(f"trend={trend}")
    if opp_rating:
        parts.append(f"opp_def={opp_rating}")
    return f"  quant: {' '.join(parts)}{bb_str}{vol_str}{mf_str}"


def classify_absent_player(player_name: str, team: str, player_stats: dict) -> dict:
    """
    Classify an absent player by their impact archetype using player_stats.json.
    Used to help Claude reason about downstream effects — especially for
    opponent-side elite defenders or high-usage teammates.

    Returns a dict:
        {
          "name": str,
          "team": str,
          "role_tags": list[str],   # e.g. ["high_usage", "rim_anchor", "primary_creator"]
          "avg_pts": float | None,
          "avg_reb": float | None,
          "avg_ast": float | None,
          "summary": str            # one-line plain-text for prompt injection
        }

    role_tags logic (non-exclusive — a player can have multiple):
        "high_usage"      — avg_pts >= 20
        "primary_creator" — avg_ast >= 6
        "rim_anchor"      — avg_reb >= 9 AND position in ("C", "PF", "F-C", "C-F")
        "perimeter_threat"— best 3PM tier exists with overall >= 72%
        "defensive_anchor"— avg_reb >= 8 AND avg_pts >= 15  (proxy for star big)

    Falls back gracefully — if player not in player_stats, returns minimal dict
    with name/team and empty role_tags (agent still functions, just with less context).
    """
    s          = player_stats.get(player_name) or player_stats.get(player_name.strip()) or {}
    raw_avgs   = s.get("raw_avgs") or {}
    best_tiers = s.get("best_tiers") or {}
    position   = s.get("position", "")  # from whitelist via quant

    avg_pts = raw_avgs.get("PTS")
    avg_reb = raw_avgs.get("REB")
    avg_ast = raw_avgs.get("AST")

    role_tags: list[str] = []

    if avg_pts is not None and avg_pts >= 20:
        role_tags.append("high_usage")
    if avg_ast is not None and avg_ast >= 6:
        role_tags.append("primary_creator")
    if avg_reb is not None and avg_reb >= 9 and any(
        pos in position for pos in ("C", "PF", "F-C", "C-F")
    ):
        role_tags.append("rim_anchor")

    tpm_best = best_tiers.get("3PM")
    if tpm_best and int(round(tpm_best["hit_rate"] * 100)) >= 72:
        role_tags.append("perimeter_threat")

    if avg_reb is not None and avg_pts is not None and avg_reb >= 8 and avg_pts >= 15:
        role_tags.append("defensive_anchor")

    # Build summary line
    stat_parts = []
    if avg_pts is not None:
        stat_parts.append(f"{avg_pts:.1f}pts")
    if avg_reb is not None:
        stat_parts.append(f"{avg_reb:.1f}reb")
    if avg_ast is not None:
        stat_parts.append(f"{avg_ast:.1f}ast")

    stat_str = " / ".join(stat_parts) if stat_parts else "stats unavailable"
    tag_str  = ", ".join(role_tags) if role_tags else "role player"
    summary  = f"{player_name} ({team}) OUT — {stat_str} [{tag_str}]"

    return {
        "name":      player_name,
        "team":      team,
        "role_tags": role_tags,
        "avg_pts":   avg_pts,
        "avg_reb":   avg_reb,
        "avg_ast":   avg_ast,
        "summary":   summary,
    }


def build_absent_player_profiles(changes: list[dict], player_stats: dict) -> str:
    """
    Build a structured block describing absent players for the Claude prompt.
    Only includes players with change_type == "new_absence" (OUT or DOUBTFUL).
    Returns empty string if no new absences.
    """
    absence_lines: list[str] = []
    for c in changes:
        if c.get("change_type") != "new_absence":
            continue
        profile = classify_absent_player(c["player_name"], c["team"], player_stats)
        absence_lines.append(f"- {profile['summary']}")

    if not absence_lines:
        return ""
    return "## ABSENT PLAYER PROFILES\n" + "\n".join(absence_lines)


# ── Game-time helpers ──────────────────────────────────────────────────────────

def load_game_map() -> dict[str, str]:
    """Return {norm_team_abbr: game_time_utc} for today's games from nba_master.csv."""
    try:
        import pandas as pd
        df = pd.read_csv(MASTER_CSV, dtype=str)
        df["game_date"] = df["game_date"].astype(str).str.strip()
        today = df[df["game_date"] == TODAY_STR]
        game_map: dict[str, str] = {}
        for _, row in today.iterrows():
            t = str(row.get("game_time_utc", "") or "").strip()
            h = _norm(str(row.get("home_team_abbrev", "") or ""))
            a = _norm(str(row.get("away_team_abbrev", "") or ""))
            if h:
                game_map[h] = t
            if a:
                game_map[a] = t
        return game_map
    except Exception as e:
        print(f"[lineup_update] WARNING: could not load game_map: {e}")
        return {}


def game_is_actionable(game_time_utc: str, now_et: dt.datetime) -> bool:
    """True if tip-off is more than CUTOFF_MINUTES away. Returns True on parse failure."""
    if not game_time_utc:
        return True
    try:
        tip = dt.datetime.fromisoformat(game_time_utc.replace("Z", "+00:00"))
        tip_et = tip.astimezone(ET)
        minutes_to_tip = (tip_et - now_et).total_seconds() / 60
        return minutes_to_tip > CUTOFF_MINUTES
    except Exception:
        return True   # safe default — don't skip on parse error


# ── Diff computation ───────────────────────────────────────────────────────────

def compute_lineup_diff(lineups: dict, injuries: dict) -> list[dict]:
    """
    Diff current lineup/injury state against the morning snapshot.

    Returns a list of change dicts:
        {team, player_name, change_type, status, detail}

    change_type values:
        "new_absence"      — player was in morning starters, now OUT/DOUBTFUL in injury report
        "starter_replaced" — player was in morning starters, no longer in current starters,
                             and not listed as injured (e.g. late scratch, load management)
    """
    snapshot = lineups.get("snapshot_at_analyst_run") or {}
    snap_teams: dict = snapshot.get("teams", {})

    if not snap_teams:
        return []

    # Build injury map: team → {name_lower: status}
    injury_map: dict[str, dict[str, str]] = {}
    for key, val in injuries.items():
        if key == "fetched_at" or not isinstance(val, list):
            continue
        team = _norm(key)
        injury_map[team] = {
            row["player_name"].strip().lower(): row.get("status", "UNKNOWN")
            for row in val
            if isinstance(row, dict) and row.get("player_name")
        }

    changes: list[dict] = []

    for raw_team, snap_data in snap_teams.items():
        team = _norm(raw_team)
        morning_starters: set[str] = {
            s.strip().lower() for s in snap_data.get("starters", [])
        }

        # Current starters — try both raw_team key and normalized key
        current_data = lineups.get(raw_team) or lineups.get(team) or {}
        current_starters: set[str] = {
            s["name"].strip().lower()
            for s in current_data.get("starters", [])
            if isinstance(s, dict) and s.get("name")
        }

        team_injuries = injury_map.get(team, {})

        for name_lower in morning_starters:
            # Recover display-case name from current starters or snapshot list
            display_name = next(
                (s["name"] for s in current_data.get("starters", [])
                 if isinstance(s, dict) and s.get("name", "").strip().lower() == name_lower),
                next(
                    (s for s in snap_data.get("starters", [])
                     if s.strip().lower() == name_lower),
                    name_lower.title()
                )
            )

            if name_lower in team_injuries:
                status = team_injuries[name_lower]
                if status in ("OUT", "DOUBTFUL"):
                    changes.append({
                        "team":        team,
                        "player_name": display_name,
                        "change_type": "new_absence",
                        "status":      status,
                        "detail":      (
                            f"{display_name} ({team}) now {status} — "
                            "was expected starter at pick time"
                        ),
                    })
            elif name_lower not in current_starters and current_starters:
                # Still not injured but quietly dropped from projected starters
                changes.append({
                    "team":        team,
                    "player_name": display_name,
                    "change_type": "starter_replaced",
                    "status":      "UNKNOWN",
                    "detail":      f"{display_name} ({team}) removed from projected starters",
                })

    return changes


# ── Pick selection ─────────────────────────────────────────────────────────────

def get_affected_picks(
    today_picks: list[dict],
    changes: list[dict],
    game_map: dict[str, str],
    now_et: dt.datetime,
) -> list[dict]:
    """
    Return open today picks whose team or opponent matches a change team,
    and whose game is still actionable (tip-off > CUTOFF_MINUTES away).
    """
    changed_teams: set[str] = {_norm(c["team"]) for c in changes}

    affected: list[dict] = []
    for pick in today_picks:
        if pick.get("result") is not None:
            continue
        if pick.get("voided", False):
            continue

        pick_team = _norm(pick.get("team", ""))
        pick_opp  = _norm(pick.get("opponent", ""))

        if pick_team not in changed_teams and pick_opp not in changed_teams:
            continue

        tip_utc = game_map.get(pick_team) or game_map.get(pick_opp) or ""
        if not game_is_actionable(tip_utc, now_et):
            print(
                f"[lineup_update] game_cutoff: {pick_team}@{pick_opp} — "
                f"{pick.get('player_name')} skipped (tip-off < {CUTOFF_MINUTES} min)"
            )
            continue

        affected.append(pick)

    return affected


# ── Claude call ────────────────────────────────────────────────────────────────

def build_rotowire_context(lineups: dict, changed_teams: set) -> str:
    """
    Build a plain-text Rotowire projections block for each changed team.
    Returns empty string when no projected_minutes or onoff_usage data is present
    (graceful degradation for unauthenticated runs).
    """
    lines: list[str] = []
    for raw_team in sorted(changed_teams):
        team = _norm(raw_team)
        team_data = lineups.get(raw_team) or lineups.get(team) or {}
        if not isinstance(team_data, dict):
            continue
        proj_min = team_data.get("projected_minutes") or []
        onoff    = team_data.get("onoff_usage") or []
        if not proj_min and not onoff:
            continue
        lines.append(f"{team} — Rotowire projections:")
        if proj_min:
            starters = [p for p in proj_min if p.get("section") == "STARTERS"]
            bench    = [p for p in proj_min if p.get("section") == "BENCH"]
            out_pl   = [p for p in proj_min if p.get("section") == "OUT"]
            if starters:
                parts = [f"{p['name']} {p['minutes']}min" for p in starters]
                lines.append(f"  Projected starters: {', '.join(parts)}")
            if bench:
                parts = [f"{p['name']} {p['minutes']}min" for p in bench]
                lines.append(f"  Projected bench: {', '.join(parts)}")
            if out_pl:
                parts = [p["name"] for p in out_pl]
                lines.append(f"  Out: {', '.join(parts)}")
        if onoff:
            usage_lines: list[str] = []
            for p in onoff:
                uc = p.get("usage_change")
                if uc is None:
                    continue
                up     = p.get("usage_pct")
                ms     = p.get("minutes_sample")
                absent = ", ".join(p.get("absent_players") or [])
                sign        = "+" if uc >= 0 else ""
                sample      = f" ({ms}min sample)" if ms else ""
                absent_str  = f" when {absent} OUT" if absent else ""
                usage_str   = f" (usage={up}%)" if up is not None else ""
                usage_lines.append(
                    f"  {p['name']}: {sign}{uc}pp USG{usage_str}{absent_str}{sample}"
                )
            if usage_lines:
                lines.append("  On/Off usage deltas:")
                lines.extend(usage_lines)
        lines.append("")
    return "\n".join(lines).strip()


def call_lineup_update(
    affected_picks: list[dict],
    changes: list[dict],
    rotowire_context: str = "",
    player_stats: dict | None = None,
) -> list[dict]:
    """
    Single Claude call. Returns list of amendment dicts:
        {player_name, prop_type, direction, revised_confidence_pct, revised_reasoning}
    """
    client = anthropic.Anthropic()
    player_stats = player_stats or {}

    system_prompt = (
        "You are a sports analyst reviewing NBA player prop picks made this morning.\n"
        "Lineup changes have occurred since picks were generated. Re-assess each affected pick.\n\n"

        "For each pick, return one JSON object with:\n"
        '  "player_name":            string (exact match from AFFECTED PICKS)\n'
        '  "prop_type":              "PTS" | "REB" | "AST" | "3PM"\n'
        '  "direction":              "up" | "down" | "unchanged"\n'
        '  "revised_confidence_pct": integer 70–99 (same as original when unchanged)\n'
        '  "revised_reasoning":      string, max 25 words\n\n'

        "## REASONING FRAMEWORK\n\n"

        "Step 1 — Identify each absent player's role from ABSENT PLAYER PROFILES:\n"
        "  Tags tell you what type of impact to expect:\n"
        "  - high_usage / primary_creator: significant offensive redistribution on their team\n"
        "  - rim_anchor: affects rebounding and paint defense on BOTH sides of the ball\n"
        "  - defensive_anchor: when OUT, opposing offensive players get easier looks and higher volume\n"
        "    especially bigs driving into the paint, and guards getting open mid-range/3PM\n"
        "  - perimeter_threat: their absence changes spacing for their teammates\n\n"

        "Step 2 — Determine which picks are affected and how:\n"
        "  TEAMMATE pick (pick player on SAME team as absent player):\n"
        "    PTS up  — if absent player was high_usage/primary_creator → usage/shots redistribute\n"
        "    PTS down — if absent player was a spacing threat whose absence collapses defense on pick player\n"
        "    REB up  — if absent player was rim_anchor and pick player competes for boards\n"
        "    AST up  — if absent player was primary_creator and pick player becomes secondary creator\n"
        "    AST down — if absent player was primary scoring target → fewer viable receivers\n\n"
        "  OPPONENT pick (pick player on OPPOSING team vs. absent player's team):\n"
        "    PTS up  — if absent player had defensive_anchor or rim_anchor tags\n"
        "               → opponent bigs get easier paint access, higher FG%, more volume\n"
        "               → opponent guards benefit from less help-side presence\n"
        "               → magnitude scales with absent player's avg_reb and avg_pts\n"
        "    REB up  — if absent player was rim_anchor → pick player competes against weaker frontcourt\n"
        "    3PM up  — if absent player was rim_anchor/defensive_anchor → less help-side deterrence\n"
        "               means more open corner 3s from kick-outs on broken paint possessions\n"
        "    AST    — usually unchanged unless absent player was the primary ball-pressure defender\n\n"

        "Step 3 — Calibrate magnitude using quant data:\n"
        "  Use the quant block under each pick:\n"
        "  - vs_soft vs vs_tough spread tells you how much this player benefits from matchup shifts\n"
        "  - trend=up + opponent absence = amplified upside\n"
        "  - [VOLATILE] = high variance, be conservative on revisions\n"
        "  - [iron_floor] = floor protected, absence mainly affects ceiling\n"
        "  Use Rotowire projected minutes and on/off usage data (when provided) to calibrate\n"
        "  magnitude: larger projected minute shifts → larger confidence revisions (±5–15pp);\n"
        "  minor shifts → ±3–5pp. When quant data is absent, use ±3–5pp as default.\n\n"

        "Step 4 — Apply the DEFAULT RULE:\n"
        "  When in doubt, use 'unchanged'. Only override original confidence when the connection\n"
        "  between the lineup change and this specific pick is direct and meaningful.\n"
        "  A role player going OUT rarely justifies any revision.\n"
        "  An elite defensive anchor going OUT for an opposing big IS a meaningful revision.\n\n"

        "Respond ONLY with a JSON array. No prose, no markdown fences."
    )

    # Build absent player profiles block
    absent_profiles_block = build_absent_player_profiles(changes, player_stats)

    # Build per-pick quant summaries
    picks_lines: list[str] = []
    for p in affected_picks:
        quant_line = build_pick_quant_summary(
            p["player_name"], p.get("prop_type", ""), player_stats
        )
        pick_line = (
            f"- {p['player_name']} ({p['team']}) vs {p['opponent']}: "
            f"{p['prop_type']} OVER {p['pick_value']} "
            f"[conf={p.get('confidence_pct', '?')}%, reasoning={p.get('reasoning', '')!r}]"
        )
        if quant_line:
            pick_line += f"\n{quant_line}"
        picks_lines.append(pick_line)

    changes_block = "\n".join(f"- {c['detail']}" for c in changes)
    picks_block   = "\n".join(picks_lines)

    rotowire_section = (
        f"\n## ROTOWIRE PROJECTIONS FOR CHANGED TEAMS\n{rotowire_context}\n"
        if rotowire_context else ""
    )

    absent_section = f"\n{absent_profiles_block}\n" if absent_profiles_block else ""

    user_msg = (
        f"## LINEUP CHANGES SINCE MORNING PICKS\n{changes_block}\n"
        f"{absent_section}"
        f"\n## AFFECTED PICKS\n{picks_block}\n"
        f"{rotowire_section}"
        "Return a JSON array with one object per pick listed above."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": user_msg}],
        system=system_prompt,
    )

    raw = response.content[0].text.strip()
    start = raw.find("[")
    end   = raw.rfind("]") + 1
    if start == -1 or end == 0:
        print(f"[lineup_update] WARNING: no JSON array in response: {raw[:200]}")
        return []

    return json.loads(raw[start:end])


# ── Apply amendments ───────────────────────────────────────────────────────────

def apply_amendments(
    all_picks: list[dict],
    amendments: list[dict],
    affected_picks: list[dict],
    changes: list[dict],
    now_iso: str,
) -> tuple[int, int, int]:
    """
    Write lineup_update sub-objects to all_picks in-place for amended picks.
    Returns (n_amended, n_up, n_down).
    """
    # (player_name_lower, prop_type) → amendment
    amend_map: dict[tuple[str, str], dict] = {
        (a["player_name"].strip().lower(), a.get("prop_type", "")): a
        for a in amendments
        if a.get("player_name") and a.get("prop_type")
    }

    def relevant_changes_for(pick: dict) -> list[dict]:
        pick_team = _norm(pick.get("team", ""))
        pick_opp  = _norm(pick.get("opponent", ""))
        return [c for c in changes if _norm(c["team"]) in {pick_team, pick_opp}]

    affected_keys: set[tuple[str, str]] = {
        (p["player_name"].strip().lower(), p.get("prop_type", ""))
        for p in affected_picks
    }

    n_amended = n_up = n_down = 0

    for pick in all_picks:
        key = (pick.get("player_name", "").strip().lower(), pick.get("prop_type", ""))
        if key not in affected_keys:
            continue

        amendment = amend_map.get(key)
        if amendment is None:
            continue

        direction = amendment.get("direction", "unchanged")
        pick["lineup_update"] = {
            "triggered_by":         [c["detail"] for c in relevant_changes_for(pick)],
            "updated_at":           now_iso,
            "direction":            direction,
            "revised_confidence_pct": amendment.get(
                "revised_confidence_pct", pick.get("confidence_pct")
            ),
            "revised_reasoning":    amendment.get("revised_reasoning", ""),
        }

        n_amended += 1
        if direction == "up":
            n_up += 1
        elif direction == "down":
            n_down += 1

    return n_amended, n_up, n_down


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    now_et  = dt.datetime.now(ET)
    now_iso = now_et.isoformat()

    # ── Load lineups ───────────────────────────────────────────────────────────
    if not LINEUPS_JSON.exists():
        print("[lineup_update] no lineups_today.json found — skipping")
        return

    try:
        with open(LINEUPS_JSON) as fh:
            lineups = json.load(fh)
    except Exception as e:
        print(f"[lineup_update] ERROR reading lineups: {e} — skipping")
        return

    if not lineups.get("snapshot_at_analyst_run"):
        print("[lineup_update] no snapshot found — skipping")
        return

    # ── Load injuries ──────────────────────────────────────────────────────────
    injuries: dict = {}
    if INJURIES_JSON.exists():
        try:
            with open(INJURIES_JSON) as fh:
                injuries = json.load(fh)
        except Exception as e:
            print(f"[lineup_update] WARNING: could not load injuries: {e}")

    # ── Load player stats (for quant context + absent player profiling) ────────
    player_stats = load_player_stats()
    if player_stats:
        print(f"[lineup_update] loaded player_stats for {len(player_stats)} players")
    else:
        print("[lineup_update] WARNING: player_stats.json unavailable — reasoning without quant context")

    # ── Compute changes ────────────────────────────────────────────────────────
    changes = compute_lineup_diff(lineups, injuries)
    if not changes:
        print("[lineup_update] no changes detected — skipping LLM call")
        return

    print(f"[lineup_update] detected {len(changes)} change(s):")
    for c in changes:
        print(f"  {c['detail']}")

    # ── Load picks ─────────────────────────────────────────────────────────────
    if not PICKS_JSON.exists():
        print("[lineup_update] no picks.json found — skipping")
        return

    with open(PICKS_JSON) as fh:
        all_picks: list[dict] = json.load(fh)

    today_picks = [p for p in all_picks if p.get("date") == TODAY_STR]
    if not today_picks:
        print("[lineup_update] no picks today — skipping")
        return

    # ── Find affected picks ────────────────────────────────────────────────────
    game_map      = load_game_map()
    affected_picks = get_affected_picks(today_picks, changes, game_map, now_et)

    if not affected_picks:
        print("[lineup_update] no actionable picks affected by changes — skipping LLM call")
        return

    print(f"[lineup_update] {len(affected_picks)} pick(s) affected — calling Claude")

    # ── Build Rotowire context for changed teams ────────────────────────────────
    changed_teams: set[str] = {_norm(c["team"]) for c in changes}
    rotowire_ctx = build_rotowire_context(lineups, changed_teams)
    if rotowire_ctx:
        print(f"[lineup_update] Rotowire context built for {len(changed_teams)} team(s)")

    # ── Call Claude ────────────────────────────────────────────────────────────
    try:
        amendments = call_lineup_update(
            affected_picks,
            changes,
            rotowire_context=rotowire_ctx,
            player_stats=player_stats,
        )
    except Exception as e:
        print(f"[lineup_update] ERROR calling Claude: {e}")
        return

    if not amendments:
        print("[lineup_update] no amendments returned — skipping write")
        return

    # ── Apply + write ──────────────────────────────────────────────────────────
    n_amended, n_up, n_down = apply_amendments(
        all_picks, amendments, affected_picks, changes, now_iso
    )

    tmp = PICKS_JSON.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(all_picks, fh, indent=2)
    os.replace(tmp, PICKS_JSON)

    n_unchanged = n_amended - n_up - n_down
    print(
        f"[lineup_update] changes={len(changes)} affected_picks={len(affected_picks)} "
        f"amended={n_amended} ({n_up} up, {n_down} down, {n_unchanged} unchanged)"
    )


if __name__ == "__main__":
    main()
