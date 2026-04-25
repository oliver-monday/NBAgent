"""
Playoff Trajectory Sweep — one-off analysis utility.

Computes per-player per-stat playoff trajectory across seasons (cross-season,
not within-series), applies sweep criteria with trajectory override logic,
and emits a markdown candidate list for human review.

Run: python -m tools.playoff_trajectory_sweep

Reads:
  - data/backtest_playoff_career.json   (H28 output)
  - playerprops/player_whitelist.csv    (active=1 filter)
  - data/playoff_bracket.json           (active playoff teams)
  - data/playoff_player_dossier.md      (existing-coverage cross-ref)

Writes:
  - data/sweep_candidates.md
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

# ---- Sweep criteria ----------------------------------------------------------

MIN_PLAYOFF_SEASONS = 3            # require >=3 prior playoff seasons
MIN_GAMES_PER_SEASON = 3           # a season counts only if player played >=3 games
DIRECTIONAL_CONSISTENCY_NUM = 2    # 2 of 3 same direction satisfies (loosened criterion)

# Magnitude floor: |delta| in stat units (career playoff avg vs career RS avg)
MAGNITUDE_FLOOR = {
    "PTS": 1.0,
    "REB": 0.5,
    "AST": 0.5,
    "3PM": 0.3,
}

# Trajectory classification thresholds
TRAJECTORY_FLAT_BAND = 0.5        # |last - first| <= 0.5 -> flat
TRAJECTORY_NET_THRESHOLD = 0.5    # |last - first| > 0.5 to be net_up/net_down

# Stat name -> game log key
STAT_KEY = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}

# ---- Paths -------------------------------------------------------------------

REPO_ROOT      = Path(__file__).resolve().parent.parent
H28_PATH       = REPO_ROOT / "data" / "backtest_playoff_career.json"
WHITELIST_PATH = REPO_ROOT / "playerprops" / "player_whitelist.csv"
BRACKET_PATH   = REPO_ROOT / "data" / "playoff_bracket.json"
DOSSIER_PATH   = REPO_ROOT / "data" / "playoff_player_dossier.md"
OUTPUT_PATH    = REPO_ROOT / "data" / "sweep_candidates.md"

# All 30 NBA team abbreviations — fallback when bracket file is unreadable.
_ALL_NBA_TEAMS: set[str] = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


# ---- Data loaders ------------------------------------------------------------

def load_h28() -> dict:
    with open(H28_PATH) as f:
        return json.load(f)


def load_active_whitelist() -> list[dict]:
    """Load whitelist rows where active=1, normalized."""
    rows: list[dict] = []
    with open(WHITELIST_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("active", "0")).strip() == "1":
                rows.append({
                    "player_name": row["player_name"].strip(),
                    "team_abbr":   row["team_abbr"].strip().upper(),
                    "position":    (row.get("position") or "").strip(),
                })
    return rows


def load_active_playoff_teams() -> set[str]:
    """
    Read playoff_bracket.json and return the set of teams in active series.

    Bracket schema (verified 2026-04-24):
      {
        "series": [{"series_id", "conference", "home_team", "away_team", "best_of"}, ...],
        "eliminated": [team_abbr, ...],   # play-in losers and any series-eliminated teams
        ...
      }

    Active = team appears in `series` AND is not listed in `eliminated`. Falls
    back to all 30 NBA team abbrevs if the file is missing/malformed (script
    will degrade more gracefully on other validations).
    """
    try:
        with open(BRACKET_PATH) as f:
            bracket = json.load(f)
    except Exception:
        return set(_ALL_NBA_TEAMS)

    eliminated = {
        str(t).strip().upper() for t in (bracket.get("eliminated") or [])
    }

    active: set[str] = set()
    for s in (bracket.get("series") or []):
        for slot in ("home_team", "away_team"):
            t = str(s.get(slot) or "").strip().upper()
            if t and t not in eliminated:
                active.add(t)

    if not active:
        # Defensive: bracket present but no active teams found — fall back.
        return set(_ALL_NBA_TEAMS)
    return active


def load_dossier_player_names() -> set[str]:
    """Extract player names from H3 (### {name}) headers in the curated dossier."""
    if not DOSSIER_PATH.exists():
        return set()
    with open(DOSSIER_PATH) as f:
        text = f.read()
    return {m.group(1).strip() for m in re.finditer(r"^### (.+?)$", text, re.MULTILINE)}


# ---- Trajectory computation --------------------------------------------------

def compute_per_season_playoff_avg(
    game_log: list[dict],
    stat_key: str,
    min_games: int = MIN_GAMES_PER_SEASON,
) -> list[dict]:
    """
    Group playoff games by season and compute per-season averages.

    Returns a list of dicts sorted by season ascending:
        [{"season": 2021, "n": 10, "avg": 26.4}, ...]

    Excludes seasons with fewer than min_games games (sample too thin).
    """
    by_season: dict[int, list[dict]] = defaultdict(list)
    for g in game_log:
        season = g.get("season")
        if season is None:
            continue
        by_season[season].append(g)

    result: list[dict] = []
    for season in sorted(by_season.keys()):
        games = by_season[season]
        if len(games) < min_games:
            continue
        values = [g[stat_key] for g in games if stat_key in g]
        if not values:
            continue
        avg = sum(values) / len(values)
        result.append({"season": season, "n": len(games), "avg": round(avg, 2)})
    return result


def classify_trajectory(deltas: list[float]) -> str:
    """
    Classify a sequence of per-season deltas (oldest -> newest).

    Categories:
      - monotonic_up:    each value strictly greater than previous
      - monotonic_down:  each value strictly less than previous
      - net_up:          last > first by > TRAJECTORY_NET_THRESHOLD, not strictly monotonic
      - net_down:        last < first by > TRAJECTORY_NET_THRESHOLD, not strictly monotonic
      - flat:            |last - first| <= TRAJECTORY_FLAT_BAND
      - insufficient_sample: < 2 deltas
    """
    if len(deltas) < 2:
        return "insufficient_sample"

    if all(deltas[i] < deltas[i + 1] for i in range(len(deltas) - 1)):
        return "monotonic_up"
    if all(deltas[i] > deltas[i + 1] for i in range(len(deltas) - 1)):
        return "monotonic_down"

    diff = deltas[-1] - deltas[0]
    if abs(diff) <= TRAJECTORY_FLAT_BAND:
        return "flat"
    if diff > TRAJECTORY_NET_THRESHOLD:
        return "net_up"
    if diff < -TRAJECTORY_NET_THRESHOLD:
        return "net_down"
    return "flat"


def directional_consistency(deltas: list[float]) -> dict:
    """
    Count how many deltas are negative vs positive vs near-zero.

    Returns:
      {
        "n_negative": int,
        "n_positive": int,
        "n_neutral":  int,    # |delta| < 0.25 — treated as no signal
        "dominant_direction": "negative" | "positive" | "mixed",
      }

    Dominant direction requires the count meets DIRECTIONAL_CONSISTENCY_NUM
    out of total non-neutral deltas; otherwise "mixed".
    """
    n_neg = sum(1 for d in deltas if d < -0.25)
    n_pos = sum(1 for d in deltas if d >  0.25)
    n_neu = len(deltas) - n_neg - n_pos

    n_directional = n_neg + n_pos
    if n_directional < DIRECTIONAL_CONSISTENCY_NUM:
        dominant = "mixed"
    elif n_neg >= DIRECTIONAL_CONSISTENCY_NUM and n_neg > n_pos:
        dominant = "negative"
    elif n_pos >= DIRECTIONAL_CONSISTENCY_NUM and n_pos > n_neg:
        dominant = "positive"
    else:
        dominant = "mixed"

    return {
        "n_negative":         n_neg,
        "n_positive":         n_pos,
        "n_neutral":          n_neu,
        "dominant_direction": dominant,
    }


# ---- Override logic ----------------------------------------------------------

def evaluate_stat_candidate(
    static_avg_delta: float,
    season_deltas: list[float],
    stat: str,
) -> dict:
    """
    Apply the sweep criteria + trajectory override.

    Returns a dict with verdict + supporting fields. See module docstring /
    spec for the full verdict taxonomy.
    """
    floor = MAGNITUDE_FLOOR.get(stat, 0.5)
    magnitude_passes = abs(static_avg_delta) >= floor
    direction_summary = directional_consistency(season_deltas)
    traj_class = (
        classify_trajectory(season_deltas)
        if len(season_deltas) >= 2
        else "insufficient_sample"
    )

    static_negative = static_avg_delta < 0 and magnitude_passes
    static_positive = static_avg_delta > 0 and magnitude_passes

    # ---- Suppress (negative) cases ----
    if static_negative and direction_summary["dominant_direction"] == "negative":
        if traj_class == "monotonic_up":
            verdict   = "suppress_candidate"
            rationale = "Static suppression but monotonic improvement — player fixing it"
        elif traj_class == "net_up":
            verdict   = "demote_to_watch"
            rationale = "Static suppression, improving but not strictly monotonic — WATCH"
        elif traj_class == "monotonic_down":
            verdict   = "ship_strong_caution"
            rationale = "Static suppression worsening over time — strong CAUTION"
        else:  # flat, net_down, insufficient_sample
            verdict   = "ship_caution"
            rationale = "Static suppression, stable or worsening trajectory"

    # ---- Boost (positive) cases ----
    elif static_positive and direction_summary["dominant_direction"] == "positive":
        if traj_class == "monotonic_up":
            verdict   = "ship_strong_boost"
            rationale = "Static boost reinforced by monotonic improvement"
        elif traj_class == "monotonic_down":
            verdict   = "suppress_eroding_boost"
            rationale = "Static boost but eroding — do not ship a positive annotation; flag for watch"
        else:
            verdict   = "ship_boost"
            rationale = "Static boost, stable or net-up trajectory"

    # ---- No static signal but trajectory-only ----
    elif not magnitude_passes:
        if traj_class in ("monotonic_up", "monotonic_down"):
            verdict   = "ship_trajectory_only"
            rationale = f"No static signal, but {traj_class} trajectory across seasons"
        else:
            verdict   = "no_signal"
            rationale = "Neither static nor trajectory signal"

    # ---- Static signal but mixed directional (rare edge case) ----
    else:
        verdict   = "no_signal"
        rationale = "Static delta passes magnitude but per-season directions are mixed"

    return {
        "verdict":                 verdict,
        "trajectory_class":        traj_class,
        "directional_consistency": direction_summary,
        "magnitude_passes":        magnitude_passes,
        "static_avg_delta":        round(static_avg_delta, 2),
        "rationale":               rationale,
    }


# ---- Sweep main loop ---------------------------------------------------------

def run_sweep() -> dict:
    h28           = load_h28()
    whitelist     = load_active_whitelist()
    active_teams  = load_active_playoff_teams()
    dossier_names = load_dossier_player_names()

    active_whitelist_players = [
        p for p in whitelist if p["team_abbr"] in active_teams
    ]

    h28_by_name       = {p["player"]: p for p in h28["players"]}
    h28_by_name_lower = {p["player"].lower(): p for p in h28["players"]}

    candidates_by_player: list[dict] = []
    for wp in active_whitelist_players:
        h28_entry = (
            h28_by_name.get(wp["player_name"])
            or h28_by_name_lower.get(wp["player_name"].lower())
        )

        if h28_entry is None:
            candidates_by_player.append({
                "player":           wp,
                "h28_status":       "no_h28_entry",
                "stats_evaluated":  {},
                "in_dossier":       wp["player_name"] in dossier_names,
            })
            continue

        playoff_seasons = h28_entry.get("playoff_seasons", []) or []
        if len(playoff_seasons) < MIN_PLAYOFF_SEASONS:
            candidates_by_player.append({
                "player":          wp,
                "h28_status":      "insufficient_seasons",
                "n_seasons":       len(playoff_seasons),
                "n_playoff_games": h28_entry.get("n_playoff", 0),
                "stats_evaluated": {},
                "in_dossier":      wp["player_name"] in dossier_names,
            })
            continue

        stats_evaluated: dict[str, dict] = {}
        for stat in ["PTS", "REB", "AST", "3PM"]:
            stat_data = (h28_entry.get("stats") or {}).get(stat)
            if not stat_data:
                continue

            static_avg_delta = stat_data.get("avg_delta", 0.0) or 0.0
            game_log         = h28_entry.get("playoff_game_log", []) or []
            stat_key         = STAT_KEY[stat]

            per_season = compute_per_season_playoff_avg(
                game_log, stat_key, min_games=MIN_GAMES_PER_SEASON
            )
            if len(per_season) < 2:
                continue

            rs_baseline = stat_data.get("reg_avg")
            if rs_baseline is None:
                continue
            season_deltas = [s["avg"] - rs_baseline for s in per_season]

            verdict = evaluate_stat_candidate(static_avg_delta, season_deltas, stat)

            stats_evaluated[stat] = {
                "rs_baseline":       round(rs_baseline, 2),
                "po_career_avg":     round(stat_data.get("po_avg", 0.0) or 0.0, 2),
                "static_avg_delta":  round(static_avg_delta, 2),
                "per_season":        per_season,
                "season_deltas":     [round(d, 2) for d in season_deltas],
                "evaluation":        verdict,
                "h28_flag":          stat_data.get("flag"),
                "key_tier":          stat_data.get("key_tier"),
                "key_tier_delta_pp": stat_data.get("key_tier_delta_pp"),
            }

        candidates_by_player.append({
            "player":          wp,
            "h28_status":      "evaluated",
            "n_seasons":       len(playoff_seasons),
            "n_playoff_games": h28_entry.get("n_playoff", 0),
            "in_dossier":      wp["player_name"] in dossier_names,
            "stats_evaluated": stats_evaluated,
        })

    return {
        "active_team_count":      len(active_teams),
        "active_whitelist_count": len(active_whitelist_players),
        "candidates":             candidates_by_player,
    }


# ---- Annotation templates ----------------------------------------------------

# Verdict groupings for output sections
SHIP_VERDICTS = {
    "ship_strong_caution",
    "ship_caution",
    "demote_to_watch",
    "ship_strong_boost",
    "ship_boost",
    "ship_trajectory_only",
}
SUPPRESS_VERDICTS = {
    "suppress_candidate",
    "suppress_eroding_boost",
}
NO_SIGNAL_VERDICTS = {"no_signal"}


def _trajectory_treatment_phrase(traj_class: str) -> str:
    """One-line direction summary for trajectory-only ships."""
    if traj_class == "monotonic_up":
        return "Each playoff is better than the last — emerging BOOST candidate; annotation only."
    if traj_class == "monotonic_down":
        return "Each playoff is worse than the last — emerging CAUTION candidate; annotation only."
    return "Annotation only — analyst weighs alongside other context."


def render_annotation(player: str, stat: str, stat_eval: dict) -> str:
    """
    Build a one-paragraph recommended annotation from a stat evaluation.
    Returns a plain string ready to paste into nba_season_context.md PLAYER NOTES.
    """
    ev          = stat_eval["evaluation"]
    verdict     = ev["verdict"]
    traj_class  = ev["trajectory_class"]
    direction   = ev["directional_consistency"]
    rs_baseline = stat_eval["rs_baseline"]
    po_avg      = stat_eval["po_career_avg"]
    delta       = stat_eval["static_avg_delta"]
    key_tier    = stat_eval.get("key_tier")
    per_season  = stat_eval["per_season"]
    n_games     = sum(s["n"] for s in per_season)
    n_seasons   = len(per_season)
    n_total     = direction["n_negative"] + direction["n_positive"] + direction["n_neutral"]
    n_neg       = direction["n_negative"]
    n_pos       = direction["n_positive"]

    base_stats = (
        f"career playoff avg {po_avg:.1f} vs RS career {rs_baseline:.1f} "
        f"({delta:+.1f} across {n_games} games / {n_seasons} playoff seasons)"
    )
    consistency = (
        f"{n_neg} of {n_total} prior playoffs below RS"
        if verdict in ("ship_caution", "ship_strong_caution", "demote_to_watch")
        else f"{n_pos} of {n_total} prior playoffs above RS"
    )
    tier_clause = f" T{key_tier}+" if key_tier is not None else ""

    if verdict == "ship_caution":
        return (
            f"{player} {stat} playoff suppression: {base_stats}. "
            f"{consistency}. Trajectory: {traj_class}. "
            f"Apply caution to {stat}{tier_clause} in playoffs."
        )
    if verdict == "ship_strong_caution":
        return (
            f"{player} {stat} playoff suppression: {base_stats}. "
            f"{consistency}. Trajectory: {traj_class} — pattern is worsening over time, strengthened CAUTION. "
            f"Apply strong caution to {stat}{tier_clause} in playoffs."
        )
    if verdict == "demote_to_watch":
        return (
            f"{player} {stat} playoff WATCH: historical suppression ({base_stats}) but "
            f"trajectory is improving (net_up). Annotation only — analyst weighs alongside other context."
        )
    if verdict == "ship_boost":
        return (
            f"{player} {stat} playoff boost: {base_stats}. "
            f"{consistency}. Trajectory: {traj_class}. "
            f"System under-rates this prop in playoffs — consider BOOST."
        )
    if verdict == "ship_strong_boost":
        return (
            f"{player} {stat} playoff boost: {base_stats}. "
            f"{consistency}. Trajectory: {traj_class} — monotonically improving, strengthened BOOST. "
            f"System under-rates this prop in playoffs."
        )
    if verdict == "suppress_eroding_boost":
        return (
            f"{player} {stat} playoff WATCH: historically a boost ({base_stats}) but "
            f"trajectory is monotonically declining. Do not assume past playoff lift continues; "
            f"annotation only."
        )
    if verdict == "ship_trajectory_only":
        return (
            f"{player} {stat} emerging playoff trend: no career-aggregate signal "
            f"({delta:+.1f} across {n_games} games / {n_seasons} seasons) but "
            f"trajectory is {traj_class}. {_trajectory_treatment_phrase(traj_class)}"
        )
    if verdict == "suppress_candidate":
        return (
            f"{player} {stat} suppress_candidate (do NOT ship): static suppression "
            f"({delta:+.1f}) but monotonic improvement across seasons — player is fixing it; "
            f"do not annotate as caution."
        )
    return (
        f"{player} {stat} no actionable signal: {base_stats}. "
        f"Trajectory: {traj_class}, dominant direction: {direction['dominant_direction']}."
    )


# ---- Markdown emitter --------------------------------------------------------

def _format_per_season_table(per_season: list[dict], rs_baseline: float) -> str:
    lines = [
        "  | Season | n_games | PO avg | Δ vs RS |",
        "  |--------|---------|--------|---------|",
    ]
    for s in per_season:
        delta = s["avg"] - rs_baseline
        lines.append(
            f"  | {s['season']} | {s['n']} | {s['avg']:.2f} | {delta:+.2f} |"
        )
    return "\n".join(lines)


def _format_stat_block(player: str, stat: str, stat_eval: dict) -> str:
    ev          = stat_eval["evaluation"]
    verdict     = ev["verdict"]
    traj_class  = ev["trajectory_class"]
    direction   = ev["directional_consistency"]
    rs_baseline = stat_eval["rs_baseline"]
    po_avg      = stat_eval["po_career_avg"]
    delta       = stat_eval["static_avg_delta"]
    key_tier    = stat_eval.get("key_tier")
    key_pp      = stat_eval.get("key_tier_delta_pp")
    h28_flag    = stat_eval.get("h28_flag")
    season_dts  = stat_eval["season_deltas"]
    per_season  = stat_eval["per_season"]

    n_total = direction["n_negative"] + direction["n_positive"] + direction["n_neutral"]

    first_d = season_dts[0]  if season_dts else 0.0
    last_d  = season_dts[-1] if season_dts else 0.0

    annotation = render_annotation(player, stat, stat_eval)

    pp_str = ""
    if key_tier is not None and key_pp is not None:
        pp_str = f" (key_tier T{key_tier}, delta_pp {key_pp:+.1f}pp)"
    elif key_tier is not None:
        pp_str = f" (key_tier T{key_tier})"

    block = [
        f"**{stat}** — `{verdict}`",
        f"- Career RS baseline: {rs_baseline:.2f} | Career PO avg: {po_avg:.2f} | Static delta: {delta:+.2f}",
        f"- H28 flag: {h28_flag}{pp_str}",
        "- Per-season:",
        _format_per_season_table(per_season, rs_baseline),
        f"- Trajectory: **{traj_class}** ({first_d:+.2f} → {last_d:+.2f})",
        f"- Directional consistency: {direction['n_negative']}/{n_total} below RS, "
        f"{direction['n_positive']}/{n_total} above RS, "
        f"{direction['n_neutral']}/{n_total} neutral (dominant: {direction['dominant_direction']})",
        f"- Rationale: {ev['rationale']}",
        "",
        "**Recommended annotation** (drop into `nba_season_context.md` PLAYER NOTES):",
        f"> {annotation}",
        "",
    ]
    return "\n".join(block)


def _player_section(c: dict, dominant_verdict: str) -> str:
    p = c["player"]
    name = p["player_name"]
    team = p["team_abbr"]
    pos  = p["position"] or "?"
    in_dossier      = "yes" if c.get("in_dossier") else "no"
    n_seasons       = c.get("n_seasons", 0)
    n_playoff_games = c.get("n_playoff_games", 0)

    lines = [
        f"### {name} ({team}, {pos}) — {dominant_verdict}",
        f"*Already in dossier: {in_dossier} | n_playoff_games: {n_playoff_games} | n_seasons: {n_seasons}*",
        "",
    ]

    # Render each evaluated stat block, in stable order
    for stat in ["PTS", "REB", "AST", "3PM"]:
        if stat in c["stats_evaluated"]:
            lines.append(_format_stat_block(name, stat, c["stats_evaluated"][stat]))

    return "\n".join(lines)


def render_markdown(result: dict) -> str:
    candidates    = result["candidates"]
    today         = dt.date.today().strftime("%Y-%m-%d")

    # Bucket players by their dominant verdict (worst-case priority order):
    #   ship_strong_* > ship_* > demote_to_watch > suppress_* > trajectory_only > no_signal
    verdict_priority = [
        "ship_strong_caution",
        "ship_strong_boost",
        "ship_caution",
        "ship_boost",
        "demote_to_watch",
        "ship_trajectory_only",
        "suppress_eroding_boost",
        "suppress_candidate",
        "no_signal",
    ]

    def player_dominant_verdict(c: dict) -> str | None:
        verdicts = {
            stat_eval["evaluation"]["verdict"]
            for stat_eval in c.get("stats_evaluated", {}).values()
        }
        for v in verdict_priority:
            if v in verdicts:
                return v
        return None

    ship_players: list[tuple[dict, str]] = []
    suppress_players: list[tuple[dict, str]] = []
    no_signal_players: list[dict] = []
    insufficient: list[dict] = []
    no_h28: list[dict] = []

    verdict_counts: dict[str, int] = defaultdict(int)
    for c in candidates:
        if c["h28_status"] == "no_h28_entry":
            no_h28.append(c)
            continue
        if c["h28_status"] == "insufficient_seasons":
            insufficient.append(c)
            continue
        # evaluated
        for stat_eval in c["stats_evaluated"].values():
            verdict_counts[stat_eval["evaluation"]["verdict"]] += 1
        dom = player_dominant_verdict(c)
        if dom is None or dom in NO_SIGNAL_VERDICTS:
            no_signal_players.append(c)
        elif dom in SHIP_VERDICTS:
            ship_players.append((c, dom))
        elif dom in SUPPRESS_VERDICTS:
            suppress_players.append((c, dom))
        else:
            no_signal_players.append(c)

    # ---- Build markdown ----
    md: list[str] = []
    md.append("# Playoff Trajectory Sweep — Candidate Annotations")
    md.append(f"*Generated: {today}*")
    md.append("")
    md.append("This file is the OUTPUT of `tools/playoff_trajectory_sweep.py`. ")
    md.append("It is overwritten on each run. Review each candidate, approve/reject, ")
    md.append("then batch-ship approved annotations to `context/nba_season_context.md` ")
    md.append("via the followup prompt.")
    md.append("")
    md.append("## Summary")
    md.append(f"- Active playoff teams: {result['active_team_count']}")
    md.append(f"- Active whitelisted players analyzed: {result['active_whitelist_count']}")
    md.append("- Per-stat verdict counts (across all evaluated players):")
    for v in verdict_priority:
        md.append(f"  - `{v}`: {verdict_counts.get(v, 0)}")
    md.append(f"- Players with no H28 entry: {len(no_h28)}")
    md.append(f"- Players with insufficient playoff seasons (<{MIN_PLAYOFF_SEASONS}): {len(insufficient)}")
    md.append(f"- Players evaluated but no actionable signal: {len(no_signal_players)}")
    md.append("")
    md.append("---")
    md.append("")

    # ---- Candidates to Ship ----
    md.append("## Candidates to Ship")
    md.append("")
    if not ship_players:
        md.append("*No candidates met ship criteria.*")
        md.append("")
    else:
        # Order: strongest verdicts first
        ship_players.sort(key=lambda t: verdict_priority.index(t[1]))
        for c, dom in ship_players:
            md.append(_player_section(c, dom))
            md.append("---")
            md.append("")

    # ---- Suppressed by Trajectory ----
    md.append("## Candidates Suppressed by Trajectory")
    md.append("")
    if not suppress_players:
        md.append("*No candidates were suppressed by trajectory.*")
        md.append("")
    else:
        suppress_players.sort(key=lambda t: verdict_priority.index(t[1]))
        for c, dom in suppress_players:
            md.append(_player_section(c, dom))
            md.append("---")
            md.append("")

    # ---- Insufficient sample ----
    md.append("## Insufficient Sample / No H28 Coverage")
    md.append("")
    md.append(f"### Players with <{MIN_PLAYOFF_SEASONS} playoff seasons")
    if not insufficient:
        md.append("*(none)*")
    else:
        for c in sorted(insufficient, key=lambda x: x["player"]["player_name"]):
            p = c["player"]
            md.append(
                f"- **{p['player_name']}** ({p['team_abbr']}) — "
                f"{c.get('n_seasons', 0)} prior playoff season(s), "
                f"{c.get('n_playoff_games', 0)} game(s)"
            )
    md.append("")

    md.append("### Players with no H28 entry")
    if not no_h28:
        md.append("*(none)*")
    else:
        for c in sorted(no_h28, key=lambda x: x["player"]["player_name"]):
            p = c["player"]
            md.append(f"- **{p['player_name']}** ({p['team_abbr']})")
    md.append("")

    # ---- Evaluated but no signal ----
    if no_signal_players:
        md.append("## Evaluated but No Actionable Signal")
        md.append("")
        md.append(
            "*These players have ≥3 playoff seasons in H28 but produced no "
            "ship-worthy verdict on any stat. Listed for completeness — no action.*"
        )
        md.append("")
        for c in sorted(no_signal_players, key=lambda x: x["player"]["player_name"]):
            p = c["player"]
            in_doss = "yes" if c.get("in_dossier") else "no"
            md.append(
                f"- **{p['player_name']}** ({p['team_abbr']}) — "
                f"{c.get('n_seasons', 0)} seasons, in dossier: {in_doss}"
            )
        md.append("")

    return "\n".join(md)


# ---- CLI entry point ---------------------------------------------------------

def main():
    result   = run_sweep()
    markdown = render_markdown(result)
    OUTPUT_PATH.write_text(markdown)

    print(f"[sweep] Wrote {OUTPUT_PATH}")
    print(f"[sweep] Active playoff teams: {result['active_team_count']}")
    print(f"[sweep] Active whitelisted players analyzed: {result['active_whitelist_count']}")

    # Verdict tallies
    counts: dict[str, int] = defaultdict(int)
    no_h28 = 0
    insufficient = 0
    for c in result["candidates"]:
        if c["h28_status"] == "no_h28_entry":
            no_h28 += 1
        elif c["h28_status"] == "insufficient_seasons":
            insufficient += 1
        else:
            for stat_eval in c["stats_evaluated"].values():
                counts[stat_eval["evaluation"]["verdict"]] += 1

    print(f"[sweep] No H28 entry: {no_h28}")
    print(f"[sweep] Insufficient playoff seasons: {insufficient}")
    print("[sweep] Per-stat verdict tallies:")
    for v in [
        "ship_strong_caution", "ship_strong_boost",
        "ship_caution", "ship_boost",
        "demote_to_watch", "ship_trajectory_only",
        "suppress_eroding_boost", "suppress_candidate",
        "no_signal",
    ]:
        print(f"  {v:24s} {counts.get(v, 0)}")


if __name__ == "__main__":
    main()
