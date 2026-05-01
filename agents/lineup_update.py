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

import argparse
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
ODDS_AVAILABLE_JSON = DATA / "odds_available.json"

# ── Config ─────────────────────────────────────────────────────────────────────
MODEL          = "claude-sonnet-4-6"
MAX_TOKENS     = 2048
CUTOFF_MINUTES = 20    # skip picks for games tipping off within this many minutes

# ── H34 CLV warning constants (observability only — no confidence change) ──
# AST × lost_close hit rate is 62.5% (n=32) vs 77.0% AST baseline (n=113);
# delta -14.5pp validated 2026-04-30 (data/backtest_clv_ast_disagree.json).
# This block detects + LOGS the signal each pretip cycle so we accumulate
# prod-data evidence before activating any confidence haircut.
CLV_WARN_LOST_THRESHOLD   = -0.5     # live_clv_pp below this → AST warning fires
CLV_WARN_PROP_TYPES       = {"AST"}  # H34 is AST-specific; PTS/REB/3PM excluded
CLV_WARN_PROPOSED_PENALTY = 5        # Proposed confidence penalty (NOT applied;
                                     # surfaced for review only)

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


def _norm_odds_name(name: str) -> str:
    """Normalize player name to match odds_available.json player keys.

    Matches the normalization used by ingest/odds_today.py: lowercase, strip
    all punctuation (keeping only [a-z0-9 ]), collapse whitespace. DIFFERENT
    from _norm() — that one handles team abbreviations.
    """
    import re
    return re.sub(r"[^a-z0-9 ]", "", str(name).lower()).strip()


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


GAME_LOG_CSV = ROOT / "data" / "player_game_log.csv"


def load_game_log() -> "pd.DataFrame | None":
    """
    Load player_game_log.csv. Returns None on any error.
    Only imported/loaded when opportunity surfacing is triggered.
    """
    try:
        import pandas as pd
        df = pd.read_csv(GAME_LOG_CSV, dtype=str)
        return df
    except Exception as e:
        print(f"[lineup_update] WARNING: could not load game_log: {e}")
        return None


ESPN_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
)


def fetch_live_spreads() -> dict[str, "float | None"]:
    """
    Fetch current point spreads from ESPN scoreboard API for today's games.
    Returns {norm_team_abbr: signed_spread} where negative = favored.

    Example: {"OKC": -9.5, "MIN": 9.5, "CLE": -16.5, "DAL": 16.5}

    Returns {} on any network or parse error — never crashes.
    Graceful degradation: if ESPN is unavailable, spread delta is omitted
    from opportunity cards without blocking the rest of the run.
    """
    try:
        import requests as _requests
        resp = _requests.get(ESPN_SCOREBOARD_URL, timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[lineup_update] WARNING: could not fetch live spreads: {e}")
        return {}

    result: dict[str, "float | None"] = {}
    for event in data.get("events", []):
        for comp in event.get("competitions", []):
            odds_list = comp.get("odds", [])
            if not odds_list:
                continue
            # Use first odds provider entry — details field contains the spread line
            odds = odds_list[0]
            details = odds.get("details", "")  # e.g. "OKC -9.5" or "MIN +9.5"
            if not details:
                continue

            # Parse "TEAM ±X.X" format
            parts = details.strip().split()
            if len(parts) != 2:
                continue
            try:
                spread_val = float(parts[1])
            except ValueError:
                continue

            # Match each competitor to get their side of the spread
            competitors = comp.get("competitors", [])
            for comp_entry in competitors:
                abbr = _norm(
                    str(comp_entry.get("team", {}).get("abbreviation", "") or "")
                )
                if not abbr:
                    continue
                # The details field shows the favored team with negative spread.
                # Determine which side each team is on from home/away context.
                # home_team_abbr from details prefix — match by string start.
                fav_abbr = _norm(parts[0]) if parts else ""
                if abbr == fav_abbr:
                    result[abbr] = -abs(spread_val)
                else:
                    result[abbr] = abs(spread_val)

    print(f"[lineup_update] live spreads fetched for {len(result)} teams")
    return result


SKIPPED_PICKS_JSON = DATA / "skipped_picks.json"


def load_morning_skips() -> dict[str, list[str]]:
    """
    Load today's skip records from skipped_picks.json.
    Returns {player_name_lower: [skip_reason, ...]} for quick lookup.
    Used to annotate opportunity cards with morning skip context.
    """
    if not SKIPPED_PICKS_JSON.exists():
        return {}
    try:
        with open(SKIPPED_PICKS_JSON) as fh:
            skips = json.load(fh)
        result: dict[str, list[str]] = {}
        for s in skips:
            if s.get("date") != TODAY_STR:
                continue
            name = (s.get("player_name") or "").strip().lower()
            reason = s.get("skip_reason") or ""
            if name and reason:
                result.setdefault(name, []).append(reason)
        return result
    except Exception as e:
        print(f"[lineup_update] WARNING: could not load skipped_picks: {e}")
        return {}


def compute_without_player_rates(
    teammate_name: str,
    absent_player_name: str,
    game_log: "pd.DataFrame",
) -> dict:
    """
    Compute tier hit rates for `teammate_name` on dates when `absent_player_name`
    had dnp=="1" or minutes=="0" or minutes=="".

    Returns dict keyed by prop_type → {tier → hit_rate, n} for qualifying tiers.
    Returns {} when sample < 3 games (too small to show).

    Tiers checked: PTS [10,15,20,25,30], REB [4,6,8], AST [2,4,6], 3PM [1,2,3]
    Hit condition: actual >= tier (NBAgent convention — exact hit counts as HIT)
    DNP exclusion for teammate: exclude rows where teammate dnp=="1"
    """
    TIERS = {
        "PTS": [10, 15, 20, 25, 30],
        "REB": [4, 6, 8],
        "AST": [2, 4, 6],
        "3PM": [1, 2, 3],
    }
    STAT_COL = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm"}

    try:
        import pandas as pd

        # Find dates when absent player had dnp or 0 minutes
        absent_rows = game_log[
            game_log["player_name"].str.strip().str.lower()
            == absent_player_name.strip().lower()
        ]
        dnp_mask = (
            (absent_rows["dnp"].astype(str).str.strip() == "1")
            | (absent_rows["minutes"].astype(str).str.strip().isin(["0", ""]))
        )
        absent_dates: set = set(absent_rows.loc[dnp_mask, "game_date"].astype(str).str.strip())

        if len(absent_dates) < 3:
            return {}  # Insufficient sample — don't surface

        # Get teammate rows on those dates (exclude teammate DNPs)
        tm_rows = game_log[
            (game_log["player_name"].str.strip().str.lower()
             == teammate_name.strip().lower())
            & (game_log["game_date"].astype(str).str.strip().isin(absent_dates))
            & (game_log["dnp"].astype(str).str.strip() != "1")
        ]

        if len(tm_rows) < 3:
            return {}

        results: dict = {}
        for prop, tiers in TIERS.items():
            col = STAT_COL.get(prop)
            if col not in tm_rows.columns:
                continue
            vals = pd.to_numeric(tm_rows[col], errors="coerce").dropna()
            if len(vals) < 3:
                continue
            prop_result: dict = {}
            for tier in tiers:
                hits = int((vals >= tier).sum())
                n    = len(vals)
                hr   = hits / n
                if hr >= 0.70:  # same floor as analyst
                    prop_result[tier] = {"hit_rate": hr, "n": n}
            if prop_result:
                results[prop] = prop_result
        return results

    except Exception as e:
        print(f"[lineup_update] WARNING: compute_without_player_rates failed: {e}")
        return {}


OPPORTUNITY_FLAGS_JSON = DATA / "opportunity_flags.json"
CANNIBALIZATION_JSON   = DATA / "backtest_teammate_cannibalization.json"

_cannib_cache: dict | None = None


def _load_cannib_data() -> dict:
    """
    Load H33 cannibalization backtest results.
    Returns {(player_a_lower, player_b_lower, stat): {cannib_idx, label}}
    Cached at module level. Returns empty dict if file missing.
    """
    global _cannib_cache
    if _cannib_cache is not None:
        return _cannib_cache
    _cannib_cache = {}
    if not CANNIBALIZATION_JSON.exists():
        return _cannib_cache
    try:
        with open(CANNIBALIZATION_JSON) as f:
            data = json.load(f)
        for _team, tr in data.get("team_results", {}).items():
            for pair in tr.get("pair_results", []):
                key = (
                    pair["player_a"].strip().lower(),
                    pair["player_b"].strip().lower(),
                    pair["stat"],
                )
                _cannib_cache[key] = {
                    "cannib_idx": pair["cannib_idx"],
                    "label": pair["label"],
                }
    except Exception as e:
        print(f"[lineup_update] WARNING: could not load H33 data: {e}")
    return _cannib_cache


# Qualifying absence tags — only these trigger teammate surfacing
_OPPORTUNITY_TRIGGER_TAGS = {"defensive_anchor", "rim_anchor", "high_usage"}


def build_opportunity_suggestions(
    changes: list[dict],
    today_picks: list[dict],
    player_stats: dict,
    game_log: "pd.DataFrame | None",
    now_iso: str,
    injuries: dict | None = None,
) -> list[dict]:
    """
    For each whitelisted player going OUT today, surface whitelisted teammates
    and opponents who have qualifying quant tiers — as fresh-look candidates
    given the changed game context.

    Includes players who were skipped this morning (context changed).
    Deduplicates by (player_name, prop_type) — one card per player per prop.
    Annotates each card with live spread delta when available.

    When `injuries` is provided, players with status OUT / DOUBTFUL / OFS are
    excluded from the scan — they should never be surfaced as opportunities
    because they aren't available to benefit from anyone's absence. Default
    `None` preserves backward compatibility with callers that don't pass
    injuries (the filter is a no-op in that case).

    Returns list of suggestion dicts. Empty list when no qualifying absences
    or no whitelisted players with qualifying tiers found.
    """
    # Only process confirmed absences (OUT or DOUBTFUL)
    absence_changes = [c for c in changes if c.get("change_type") == "new_absence"]
    if not absence_changes:
        return []

    # Build set of players who are OUT/DOUBTFUL/OFS — never surface these as
    # opportunities. Built from two sources for robust matching:
    #
    # Source 1: voided picks (full names, confirmed OUT by lineup_watch)
    # Source 2: raw injury JSON (abbreviated Rotowire names, broader coverage)
    #
    # Both are normalized to lowercase for comparison against player_stats names.
    excluded_players: set[str] = set()

    # Source 1: voided picks — full names, no format mismatch
    for p in today_picks:
        if p.get("voided", False):
            excluded_players.add(p.get("player_name", "").strip().lower())

    # Source 2: raw injuries — resolve Rotowire abbreviated names
    # (e.g. "L. Doncic") to full player_stats names (e.g. "luka doncic")
    # via last-name + team matching. Falls back to adding the raw
    # abbreviated name when no player_stats match is found.
    #
    # Build team→full_name index from player_stats for resolution.
    _team_to_fullnames: dict[str, list[str]] = {}
    for ps_name, ps_data in player_stats.items():
        ps_team = _norm(ps_data.get("team", ""))
        if ps_team:
            _team_to_fullnames.setdefault(ps_team, []).append(
                ps_name.strip().lower()
            )

    if injuries:
        for team_key, val in injuries.items():
            if not isinstance(val, list):
                continue
            # Normalize team key from injury JSON
            inj_team = _norm(team_key)
            for row in val:
                if not isinstance(row, dict):
                    continue
                raw_name = (row.get("name") or row.get("player_name") or "").strip()
                status = (row.get("status") or "").upper()
                if status not in ("OUT", "DOUBTFUL", "OFS") or not raw_name:
                    continue

                # Always add the raw abbreviated name (backward compat)
                excluded_players.add(raw_name.lower())

                # Resolve to full name: extract last name from "F. LastName"
                # or "FirstName LastName" and match against player_stats on
                # the same team.
                name_parts = raw_name.replace(".", "").strip().split()
                if not name_parts:
                    continue
                last_name = name_parts[-1].lower()

                # Search player_stats names on the same team for last-name match
                for full_name in _team_to_fullnames.get(inj_team, []):
                    if full_name.split()[-1] == last_name:
                        excluded_players.add(full_name)

    # Load today's FanDuel market availability — used to annotate each tier
    # entry with market implied probability so users can see edge at a glance.
    # Graceful no-op on missing/stale file.
    odds_players: dict = {}
    if ODDS_AVAILABLE_JSON.exists():
        try:
            with open(ODDS_AVAILABLE_JSON) as fh:
                odds_data = json.load(fh)
            if odds_data.get("date") == TODAY_STR:
                odds_players = odds_data.get("players", {}) or {}
                print(
                    f"[lineup_update] loaded odds_available: "
                    f"{len(odds_players)} players with market lines"
                )
            else:
                print(
                    f"[lineup_update] odds_available.json stale "
                    f"(date={odds_data.get('date')} vs today={TODAY_STR}) — skipping"
                )
        except Exception as e:
            print(f"[lineup_update] WARNING: could not load odds_available.json: {e}")

    # Morning spread from player_stats (written at analyst run time)
    # Map: norm_team → spread_abs (positive float, team's perspective unsigned)
    morning_spreads: dict[str, float] = {}
    for ps_data in player_stats.values():
        team = _norm(ps_data.get("team", ""))
        sa   = ps_data.get("spread_abs")
        if team and sa is not None and team not in morning_spreads:
            morning_spreads[team] = float(sa)

    # Live spreads from ESPN — graceful empty dict on failure
    live_spreads = fetch_live_spreads()

    # Morning skips — for annotation only, not gating
    morning_skips = load_morning_skips()

    # Build dict of players already picked this morning: (name_lower, prop) → {tier, confidence}
    morning_picks_map: dict[tuple[str, str], dict] = {
        (p["player_name"].strip().lower(), p.get("prop_type", "")): {
            "tier": p.get("pick_value"),
            "confidence_pct": p.get("confidence_pct"),
        }
        for p in today_picks
        if not p.get("voided", False) and p.get("pick_value") is not None
    }

    # Dedup: player_name_lower → best suggestion so far (one card per player)
    seen: dict[str, dict] = {}

    for change in absence_changes:
        absent_name = change["player_name"]
        absent_team = _norm(change["team"])

        # Determine opposing team from player_stats
        opponent_team: "str | None" = None
        for ps_data in player_stats.values():
            if _norm(ps_data.get("team", "")) == absent_team:
                opp = _norm(ps_data.get("opponent", ""))
                if opp:
                    opponent_team = opp
                    break

        print(
            f"[lineup_update] opportunity: {absent_name} ({absent_team}) OUT — "
            f"scanning teammates + opponent {opponent_team or '?'}"
        )

        # Compute spread delta for this game
        spread_delta_str: str = ""
        if opponent_team:
            morning_sa = morning_spreads.get(absent_team) or morning_spreads.get(opponent_team)
            live_sa_team = live_spreads.get(absent_team)
            live_sa_opp  = live_spreads.get(opponent_team)
            # Use whichever live value we got; convert to abs for comparison
            live_sa = abs(live_sa_team) if live_sa_team is not None else (
                      abs(live_sa_opp)  if live_sa_opp  is not None else None)
            if morning_sa is not None and live_sa is not None:
                delta = live_sa - morning_sa
                if abs(delta) >= 3.0:
                    direction = "larger" if delta > 0 else "smaller"
                    spread_delta_str = (
                        f"spread moved {abs(delta):.1f}pts {direction} since morning "
                        f"(was {morning_sa:.1f}, now {live_sa:.1f})"
                    )

        # Scan both teams
        teams_to_scan = [
            (absent_team,   "teammate"),
            (opponent_team, "opponent"),
        ]

        for scan_team, side in teams_to_scan:
            if not scan_team:
                continue

            for tm_name, tm_stats in player_stats.items():
                if _norm(tm_stats.get("team", "")) != scan_team:
                    continue

                best_tiers = tm_stats.get("best_tiers") or {}
                trends     = tm_stats.get("trend") or {}
                volatility = tm_stats.get("volatility") or {}
                name_lower = tm_name.strip().lower()

                # Skip absent player — they cannot benefit from their own absence
                if name_lower == absent_name.strip().lower():
                    continue

                # Skip players who are themselves OUT/DOUBTFUL/OFS
                if name_lower in excluded_players:
                    continue

                # Build qualifying_tiers (new picks) and upgrade_tiers (better tier
                # than the morning pick) across all props for this player.
                qualifying_tiers: dict[str, dict] = {}
                upgrade_tiers:    dict[str, dict] = {}

                for prop in ("PTS", "REB", "AST", "3PM"):
                    best = best_tiers.get(prop)
                    if not best:
                        continue

                    tier    = best["tier"]
                    base_hr = best["hit_rate"]
                    if base_hr < 0.70:
                        continue

                    trend = trends.get(prop, "stable")
                    vol   = (volatility.get(prop) or {}).get("label", "moderate")

                    # Without-absent-player historical rates (teammate side only)
                    without_hr: "float | None" = None
                    without_n:  "int | None"   = None
                    if side == "teammate" and game_log is not None:
                        without_rates = compute_without_player_rates(
                            tm_name, absent_name, game_log
                        )
                        prop_without = without_rates.get(prop, {})
                        if prop_without:
                            best_wt = max(
                                (t for t in prop_without if prop_without[t]["hit_rate"] >= 0.70),
                                default=None,
                            )
                            if best_wt is not None:
                                without_hr = prop_without[best_wt]["hit_rate"]
                                without_n  = prop_without[best_wt]["n"]

                    tier_entry: dict = {
                        "tier":         tier,
                        "hit_rate_pct": int(round(base_hr * 100)),
                        "trend":        trend,
                        "volatility":   vol,
                    }
                    if without_hr is not None and without_n is not None and without_n >= 3:
                        tier_entry["without_player_hit_rate_pct"] = int(round(without_hr * 100))
                        tier_entry["without_player_n"]            = without_n

                    # Enrich with FanDuel market implied probability at this
                    # exact tier. Graceful no-op when no matching market line.
                    odds_key = _norm_odds_name(tm_name)
                    player_odds = odds_players.get(odds_key, {})
                    prop_odds = player_odds.get(prop, []) or []
                    for ol in prop_odds:
                        if ol.get("tier") == tier:
                            mkt_prob = ol.get("implied_prob")
                            if mkt_prob is not None:
                                tier_entry["market_implied_pct"] = mkt_prob
                            mkt_odds = ol.get("odds")
                            if mkt_odds is not None:
                                tier_entry["market_odds"] = mkt_odds
                            break

                    existing_pick = morning_picks_map.get((name_lower, prop))
                    if existing_pick is None:
                        qualifying_tiers[prop] = tier_entry
                    else:
                        # Upgrade: quant best tier is higher than the morning pick tier
                        morning_tier = existing_pick.get("tier")
                        if morning_tier is not None and tier > morning_tier:
                            tier_entry["morning_tier"]           = morning_tier
                            tier_entry["morning_confidence_pct"] = existing_pick.get("confidence_pct")
                            upgrade_tiers[prop] = tier_entry

                # Skip if nothing actionable for this player
                if not qualifying_tiers and not upgrade_tiers:
                    continue

                # Determine card type
                if qualifying_tiers and upgrade_tiers:
                    card_type = "mixed"
                elif qualifying_tiers:
                    card_type = "new_pick"
                else:
                    card_type = "upgrade"

                # Morning skip annotation
                skip_reasons    = morning_skips.get(name_lower, [])
                morning_context = (
                    f"skipped this morning ({', '.join(skip_reasons[:2])})"
                    if skip_reasons else None
                )

                # Build reasoning summary — include odds edge when available
                all_tiers = {**qualifying_tiers, **upgrade_tiers}
                reason_parts = []
                best_edge: float | None = None
                best_edge_prop: str | None = None
                for ct, td in all_tiers.items():
                    base = f"{ct} T{td['tier']} {td['hit_rate_pct']}% [{td['trend']}]"
                    mkt = td.get("market_implied_pct")
                    if mkt is not None:
                        edge = td["hit_rate_pct"] - mkt
                        base += f" (mkt {mkt:.0f}%, edge {edge:+.0f}pp)"
                        if best_edge is None or edge > best_edge:
                            best_edge = edge
                            best_edge_prop = ct
                    reason_parts.append(base)
                if spread_delta_str:
                    reason_parts.append(spread_delta_str)
                if morning_context:
                    reason_parts.append(morning_context)

                # H33 cannibalization enrichment — teammate side only
                cannib_freed = False
                cannib_idx_best: float | None = None
                cannib_detail: str | None = None
                if side == "teammate":
                    cannib = _load_cannib_data()
                    if cannib:
                        # Check each qualifying/upgrade prop for cannibalization
                        for _prop in list(qualifying_tiers.keys()) + list(upgrade_tiers.keys()):
                            if _prop not in ("PTS", "AST"):
                                continue
                            key_ab = (name_lower, absent_name.strip().lower(), _prop)
                            key_ba = (absent_name.strip().lower(), name_lower, _prop)
                            entry = cannib.get(key_ab) or cannib.get(key_ba)
                            if entry and entry["cannib_idx"] < -8.0:
                                cannib_freed = True
                                if cannib_idx_best is None or entry["cannib_idx"] < cannib_idx_best:
                                    cannib_idx_best = entry["cannib_idx"]
                                    cannib_detail = (
                                        f"{_prop} was cannibalized {entry['cannib_idx']:.1f}pp "
                                        f"by {absent_name} → freed ceiling"
                                    )

                if cannib_freed and cannib_detail:
                    reason_parts.append(f"H33: {cannib_detail}")

                suggestion = {
                    "date":              TODAY_STR,
                    "generated_at":      now_iso,
                    "triggered_by":      absent_name,
                    "triggered_by_team": absent_team,
                    "side":              side,
                    "player_name":       tm_name,
                    "team":              scan_team,
                    "card_type":         card_type,
                    "qualifying_tiers":  qualifying_tiers,
                    "upgrade_tiers":     upgrade_tiers,
                    "spread_delta":      spread_delta_str or None,
                    "morning_context":   morning_context,
                    "reasoning":         "; ".join(reason_parts),
                    "best_edge_pp":      round(best_edge, 1) if best_edge is not None else None,
                    "best_edge_prop":    best_edge_prop,
                    "priority":          "high" if cannib_freed else "standard",
                    "cannib_freed":      cannib_freed,
                    "cannib_idx":        cannib_idx_best,
                    "cannib_detail":     cannib_detail,
                }

                # Dedup by player name — keep card with more total actionable props
                dedup_key = name_lower
                existing  = seen.get(dedup_key)
                if existing is None or (
                    len(qualifying_tiers) + len(upgrade_tiers)
                    > len(existing.get("qualifying_tiers", {}))
                    + len(existing.get("upgrade_tiers", {}))
                ):
                    seen[dedup_key] = suggestion

    suggestions = sorted(
        seen.values(),
        key=lambda s: (0 if s.get("priority") == "high" else 1, s.get("player_name", "")),
    )
    print(
        f"[lineup_update] opportunity: {len(suggestions)} unique player "
        f"card(s) from {len(absence_changes)} absence(s)"
    )
    return suggestions


def save_opportunity_flags(suggestions: list[dict]) -> None:
    """
    Append today's suggestions to the cumulative opportunity_flags.json.
    Deduplicates by (date, player_name, triggered_by) so repeated hourly runs
    don't create duplicate entries. One card per player per triggering absence.
    """
    # Load existing
    existing: list[dict] = []
    if OPPORTUNITY_FLAGS_JSON.exists():
        try:
            with open(OPPORTUNITY_FLAGS_JSON) as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # Dedup key — one card per (player, triggering absence) per day
    def _key(s: dict) -> tuple:
        return (
            s.get("date", ""),
            s.get("player_name", "").strip().lower(),
            s.get("triggered_by", "").strip().lower(),
        )

    existing_keys: set = {_key(e) for e in existing}
    new_entries = [s for s in suggestions if _key(s) not in existing_keys]

    if not new_entries:
        print("[lineup_update] opportunity: no new suggestions to save")
        return

    combined = existing + new_entries
    tmp = OPPORTUNITY_FLAGS_JSON.with_suffix(".json.tmp")
    with open(tmp, "w") as fh:
        json.dump(combined, fh, indent=2)
    os.replace(tmp, OPPORTUNITY_FLAGS_JSON)
    print(
        f"[lineup_update] opportunity: saved {len(new_entries)} new suggestion(s) "
        f"({len(combined)} total in file)"
    )


# H26 population deltas at key tiers (from 2026 season backtest, n=31 obs)
# Mirror of agents/quant.py SA_POPULATION_DELTAS — copied here to avoid a
# cross-module import of quant.py constants. If the quant values change,
# update both.
_SA_POPULATION_DELTAS = {
    "PTS_T15": 11.3,
    "PTS_T20": 12.7,
    "PTS_T25": 10.5,
    "AST_T4":  9.6,
    "AST_T6":  6.7,
}


def build_skip_reconsiderations(
    changes: list[dict],
    player_stats: dict,
    game_log: "pd.DataFrame | None",
    now_iso: str,
) -> list[dict]:
    """
    Re-evaluate morning merit_below_floor skips when a team's leading scorer
    is confirmed OUT. Uses star_absence_lift data from player_stats.json (H26)
    and compute_without_player_rates() for per-player without-star hit rates.

    Only reconsiders PTS and AST skips — REB and 3PM showed no H26 signal.
    Returns list of skip_reconsideration cards for opportunity_flags.json.

    PERSONAL_DRAG_WARNING players are explicitly excluded — if the per-player
    data shows a drag, the population lift does NOT apply regardless of the
    underlying reasoning signal. This guard must fire before any reconsider
    logic to prevent the Jalen-Green-without-Booker type misses.

    Graceful no-op paths: no new_absence changes, no skip records today, no
    merit_below_floor PTS/AST skips, player not in player_stats, player has
    no star_absence_lift data (Part 1 not live yet), star not in today's
    absent_names set, game_log unavailable AND no per-player delta data,
    qualifier disqualifies reconsideration.
    """
    # Identify leading-scorer absences from today's changes
    absence_changes = [c for c in changes if c.get("change_type") == "new_absence"]
    if not absence_changes:
        return []

    # Build set of newly-absent player names (lowered for matching)
    absent_names: set[str] = {
        c["player_name"].strip().lower() for c in absence_changes
    }

    # Load today's skipped picks (keyed dict — used as existence check)
    skipped: dict[str, list[str]] = load_morning_skips()
    if not skipped:
        return []

    # Load full skip records for tier and prop details
    skip_records: list[dict] = []
    if SKIPPED_PICKS_JSON.exists():
        try:
            with open(SKIPPED_PICKS_JSON) as fh:
                all_skips = json.load(fh)
            skip_records = [
                s for s in all_skips
                if s.get("date") == TODAY_STR
                and s.get("skip_reason") == "merit_below_floor"
                and s.get("prop_type") in ("PTS", "AST")
            ]
        except Exception as e:
            print(f"[lineup_update] WARNING: could not load skip records: {e}")
            return []

    if not skip_records:
        return []

    reconsiderations: list[dict] = []

    for skip in skip_records:
        skip_player = skip.get("player_name", "").strip()
        skip_team   = _norm(skip.get("team", ""))
        skip_prop   = skip.get("prop_type", "")
        skip_tier   = skip.get("tier_considered")
        if not skip_player or not skip_prop or skip_tier is None:
            continue

        # Get this player's stats
        ps = player_stats.get(skip_player)
        if ps is None:
            continue

        # Check if this player has star_absence_lift data (requires Part 1)
        sal = ps.get("star_absence_lift")
        if sal is None:
            continue

        star_name = sal.get("star_name", "")
        qualifier = sal.get("qualifier", "")

        # Is the star newly absent today?
        if star_name.strip().lower() not in absent_names:
            continue

        # Skip if personal drag — population lift does NOT apply
        # (INVARIANT: this guard must fire before any reconsider logic.
        # If this player historically performs worse without the star,
        # reconsideration is structurally invalid regardless of other signals.)
        if qualifier == "PERSONAL_DRAG_WARNING":
            print(
                f"[lineup_update] skip-recon: {skip_player} {skip_prop} T{skip_tier} "
                f"— DRAG_WARNING for {star_name}, skipping reconsideration"
            )
            continue

        # Check without-star hit rate at the skip tier using game log
        without_hr: "float | None" = None
        without_n:  "int | None"   = None
        if game_log is not None:
            without_rates = compute_without_player_rates(
                skip_player, star_name, game_log
            )
            prop_without = without_rates.get(skip_prop, {})
            tier_data = prop_without.get(skip_tier)
            if tier_data is not None:
                without_hr = tier_data["hit_rate"]
                without_n  = tier_data["n"]

        # Determine if reconsideration is justified
        # Path A: per-player without-star rate at this tier ≥ 70%
        # Path B: no per-player data but population delta is positive and qualifier allows
        reconsider = False
        reasoning_parts: list[str] = []

        if without_hr is not None and without_n is not None and without_n >= 3:
            if without_hr >= 0.70:
                reconsider = True
                reasoning_parts.append(
                    f"without-{star_name} hit rate {int(round(without_hr * 100))}% "
                    f"(n={without_n}) at T{skip_tier} — crosses 70% floor"
                )
            else:
                reasoning_parts.append(
                    f"without-{star_name} hit rate {int(round(without_hr * 100))}% "
                    f"(n={without_n}) at T{skip_tier} — still below 70%"
                )
        else:
            # No per-player data at this specific tier — check population delta
            pop_key = f"{skip_prop}_T{skip_tier}"
            pop_delta = _SA_POPULATION_DELTAS.get(pop_key)
            if pop_delta is not None and qualifier in (
                "STRONG_PERSONAL_SIGNAL", "POPULATION_ONLY", "NEUTRAL_PERSONAL_DATA"
            ):
                # Use per-player key_deltas if available at this tier
                kd = sal.get("key_deltas") or {}
                player_delta = kd.get(pop_key)
                if player_delta is not None and player_delta > 0:
                    reconsider = True
                    reasoning_parts.append(
                        f"player-specific delta +{player_delta}pp at {pop_key} "
                        f"[{qualifier}]"
                    )
                elif qualifier != "NEUTRAL_PERSONAL_DATA":
                    reconsider = True
                    reasoning_parts.append(
                        f"population delta +{pop_delta}pp at {pop_key} "
                        f"[{qualifier}]"
                    )

        # Path C: H33 cannibalization release — player was STRONGLY suppressed
        # by the absent star. Even without sufficient without-star game history,
        # the cannibalization mechanism itself predicts a meaningful lift.
        if not reconsider:
            cannib = _load_cannib_data()
            if cannib:
                key_ab = (skip_player.strip().lower(), star_name.strip().lower(), skip_prop)
                key_ba = (star_name.strip().lower(), skip_player.strip().lower(), skip_prop)
                entry = cannib.get(key_ab) or cannib.get(key_ba)
                if entry and entry["cannib_idx"] < -15.0:
                    reconsider = True
                    reasoning_parts.append(
                        f"H33 cannibalization release: {skip_prop} was suppressed "
                        f"{entry['cannib_idx']:.1f}pp by {star_name} → ceiling freed"
                    )

        if not reconsider:
            continue

        reasoning_parts.insert(0, f"{star_name} confirmed OUT")
        reasoning_parts.append(f"original skip: merit_below_floor")

        card: dict = {
            "date":              TODAY_STR,
            "generated_at":      now_iso,
            "triggered_by":      star_name,
            "triggered_by_team": skip_team,
            "side":              "teammate",
            "player_name":       skip_player,
            "team":              skip_team,
            "card_type":         "skip_reconsideration",
            "prop_type":         skip_prop,
            "tier_considered":   skip_tier,
            "original_skip_reason": "merit_below_floor",
            "without_star_hit_rate_pct": (
                int(round(without_hr * 100)) if without_hr is not None else None
            ),
            "without_star_n":   without_n,
            "star_absence_qualifier": qualifier,
            "reasoning":        "; ".join(reasoning_parts),
            # These fields are required by the existing save_opportunity_flags dedup
            "qualifying_tiers": {},
            "upgrade_tiers":    {},
            "spread_delta":     None,
            "morning_context":  "skipped this morning (merit_below_floor)",
        }
        reconsiderations.append(card)

        print(
            f"[lineup_update] skip-recon: {skip_player} {skip_prop} T{skip_tier} "
            f"reconsidered — {'; '.join(reasoning_parts)}"
        )

    return reconsiderations


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


def classify_absent_player(player_name: str, team: str, player_stats: dict, today_picks: list[dict] | None = None) -> dict:
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

    # ── Fallback: infer from today's picks when player_stats unavailable ──────
    # If player was pre-filtered out of player_stats (e.g. already injured at analyst time),
    # use their pick history to infer role. Any whitelisted player we picked is meaningful.
    if not role_tags and today_picks:
        player_picks = [
            p for p in today_picks
            if p.get("player_name", "").strip().lower() == player_name.strip().lower()
        ]
        if player_picks:
            pts_pick = next((p for p in player_picks if p.get("prop_type") == "PTS"), None)
            if pts_pick and (pts_pick.get("pick_value") or 0) >= 20:
                role_tags.append("high_usage")
            elif pts_pick:
                role_tags.append("high_usage")  # any PTS pick = meaningful scorer
            ast_pick = next((p for p in player_picks if p.get("prop_type") == "AST"), None)
            if ast_pick and (ast_pick.get("pick_value") or 0) >= 4:
                role_tags.append("primary_creator")
            reb_pick = next((p for p in player_picks if p.get("prop_type") == "REB"), None)
            if reb_pick and (reb_pick.get("pick_value") or 0) >= 6:
                role_tags.append("rim_anchor")
                role_tags.append("defensive_anchor")
            if len(player_picks) >= 3:
                # Player with 3+ prop picks is a multi-dimensional star — always high_usage
                if "high_usage" not in role_tags:
                    role_tags.append("high_usage")
            print(
                f"[lineup_update] classify: {player_name} not in player_stats — "
                f"inferred from picks: {role_tags}"
            )

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
        profile = classify_absent_player(c["player_name"], c["team"], player_stats, today_picks=None)
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

def compute_lineup_diff(lineups: dict, injuries: dict, today_picks: list[dict] | None = None) -> list[dict]:
    """
    Diff current lineup/injury state against the morning snapshot.

    Two detection sources (both run, results merged and deduplicated):

    Source 1 — Snapshot starters: players who were in snapshot_at_analyst_run starters
    and are now OUT/DOUBTFUL in the injury report, or quietly dropped from projected starters.

    Source 2 — Picks-based: players with open picks today who are now OUT/DOUBTFUL in
    the injury report, regardless of whether they were in the snapshot starters. This catches
    bench players, load-managed stars, and any player whose status shifted after the snapshot.

    Returns a list of change dicts:
        {team, player_name, change_type, status, detail}

    change_type values:
        "new_absence"      — player OUT/DOUBTFUL (from either source)
        "starter_replaced" — player dropped from starters but not injured
    """
    snapshot = lineups.get("snapshot_at_analyst_run") or {}
    snap_teams: dict = snapshot.get("teams", {})

    # Build injury map: team → {name_lower: status}
    injury_map: dict[str, dict[str, str]] = {}
    for key, val in injuries.items():
        if key == "fetched_at" or not isinstance(val, list):
            continue
        team = _norm(key)
        injury_map[team] = {
            row["name"].strip().lower(): row.get("status", "UNKNOWN")
            for row in val
            if isinstance(row, dict) and row.get("name")
        }

    changes: list[dict] = []
    # Track (team, name_lower) pairs already added to avoid duplicates across sources
    seen: set[tuple[str, str]] = set()

    # ── Source 1: Snapshot starters ───────────────────────────────────────────
    for raw_team, snap_data in snap_teams.items():
        team = _norm(raw_team)
        morning_starters: set[str] = {
            s.strip().lower() for s in snap_data.get("starters", [])
        }

        current_data = lineups.get(raw_team) or lineups.get(team) or {}
        current_starters: set[str] = {
            s["name"].strip().lower()
            for s in current_data.get("starters", [])
            if isinstance(s, dict) and s.get("name")
        }

        team_injuries = injury_map.get(team, {})

        for name_lower in morning_starters:
            display_name = next(
                (s["name"] for s in current_data.get("starters", [])
                 if isinstance(s, dict) and s.get("name", "").strip().lower() == name_lower),
                next(
                    (s for s in snap_data.get("starters", [])
                     if s.strip().lower() == name_lower),
                    name_lower.title()
                )
            )

            key = (team, name_lower)
            if name_lower in team_injuries:
                status = team_injuries[name_lower]
                if status in ("OUT", "DOUBTFUL") and key not in seen:
                    seen.add(key)
                    changes.append({
                        "team":        team,
                        "player_name": display_name,
                        "change_type": "new_absence",
                        "status":      status,
                        "detail":      (
                            f"{display_name} ({team}) now {status} — "
                            "was expected starter at pick time"
                        ),
                        "source":      "snapshot",
                    })
            elif name_lower not in current_starters and current_starters and key not in seen:
                seen.add(key)
                changes.append({
                    "team":        team,
                    "player_name": display_name,
                    "change_type": "starter_replaced",
                    "status":      "UNKNOWN",
                    "detail":      f"{display_name} ({team}) removed from projected starters",
                    "source":      "snapshot",
                })

    # ── Source 2: Picks-based detection ───────────────────────────────────────
    # Any player with open picks today who is now OUT/DOUBTFUL = new_absence,
    # regardless of snapshot starters.
    if today_picks:
        for pick in today_picks:
            if pick.get("result") is not None:
                continue  # already graded

            p_name     = (pick.get("player_name") or "").strip()
            p_team     = _norm(pick.get("team") or "")
            name_lower = p_name.strip().lower()
            key        = (p_team, name_lower)

            if key in seen:
                continue  # already detected via snapshot source

            # Check current injury status via full-name match
            team_inj = injury_map.get(p_team, {})
            last_lower = name_lower.split()[-1] if name_lower else ""

            current_status = team_inj.get(name_lower)
            # Fallback: last-name match across all entries for this team
            if current_status is None:
                for inj_name, inj_data in team_inj.items():
                    if inj_name.split()[-1] == last_lower:
                        current_status = inj_data if isinstance(inj_data, str) else None
                        break

            # Only infer OUT from a void when the void_reason indicates an actual
            # injury/absence — NOT when the void was an amendment auto-skip
            # (confidence-based skip; player is healthy and playing).
            #
            # Known injury-style void_reason strings:
            #   - "player OUT per injury report"  (lineup_watch.py)
            #   - "injury_exit_mid_game"          (auditor.py retroactive)
            # Known NON-injury void_reason strings:
            #   - "Amendment auto-skip: revised_confidence..."  (lineup_update.py Gate 1)
            void_reason = (pick.get("void_reason") or "").lower()
            is_injury_void = (
                "player out" in void_reason
                or "injury_exit" in void_reason
                or "injury report" in void_reason
            )
            if pick.get("voided") and is_injury_void:
                inferred_status = "OUT"
            else:
                inferred_status = current_status

            if inferred_status in ("OUT", "DOUBTFUL"):
                seen.add(key)
                changes.append({
                    "team":        p_team,
                    "player_name": p_name,
                    "change_type": "new_absence",
                    "status":      inferred_status,
                    "detail":      (
                        f"{p_name} ({p_team}) {inferred_status} — "
                        "had picks this morning (detected via picks.json)"
                    ),
                    "source":      "picks",
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
    player_stats: dict | None = None,
) -> tuple[int, int, int]:
    """
    Write lineup_update sub-objects to all_picks in-place for amended picks.
    Returns (n_amended, n_up, n_down).
    """
    if player_stats is None:
        player_stats = {}
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

        direction    = amendment.get("direction", "unchanged")
        revised_conf = amendment.get(
            "revised_confidence_pct", pick.get("confidence_pct")
        )

        # ── Gate 1: Sub-70% auto-skip ─────────────────────────────────────────
        # When amendment revised confidence below 70%, void pick immediately.
        # Original lineup_update sub-object is still written for audit visibility.
        if direction == "down" and isinstance(revised_conf, (int, float)) and revised_conf < 70:
            pick["voided"]      = True
            pick["void_reason"] = (
                f"Amendment auto-skip: revised_confidence {revised_conf}% < 70 "
                f"({amendment.get('revised_reasoning', '')[:80]})"
            )
            pick["lineup_update"] = {
                "triggered_by":           [c["detail"] for c in relevant_changes_for(pick)],
                "updated_at":             now_iso,
                "direction":              "down",
                "revised_confidence_pct": revised_conf,
                "revised_reasoning":      amendment.get("revised_reasoning", ""),
            }
            n_amended += 1
            n_down    += 1
            print(
                f"[lineup_update] AUTO-SKIP: {pick.get('player_name')} "
                f"{pick.get('prop_type')} revised_conf={revised_conf}% < 70 — voided"
            )
            continue

        # ── Gate 2: B2B <5g upside block ─────────────────────────────────────
        # When player has no B2B sample for this prop AND amendment went up,
        # override to unchanged. Opponent lineup changes do not resolve B2B
        # sample uncertainty.
        if direction == "up" and player_stats:
            pname = (pick.get("player_name") or "").strip()
            prop  = pick.get("prop_type", "")
            # player_stats is keyed by player name (title case) with "team" field inside
            pstats: dict | None = None
            for ps_name, ps_entry in player_stats.items():
                if ps_name.strip().lower() == pname.lower():
                    pstats = ps_entry
                    break
            if pstats is not None:
                b2b_prop = (pstats.get("b2b_hit_rates") or {}).get(prop)
                if b2b_prop is None and pstats.get("on_back_to_back"):
                    direction    = "unchanged"
                    revised_conf = pick.get("confidence_pct")
                    print(
                        f"[lineup_update] B2B-GATE: {pname} {prop} — "
                        f"b2b_hit_rates null for {prop}, upside amendment blocked → unchanged"
                    )

        pick["lineup_update"] = {
            "triggered_by":           [c["detail"] for c in relevant_changes_for(pick)],
            "updated_at":             now_iso,
            "direction":              direction,
            "revised_confidence_pct": revised_conf,
            "revised_reasoning":      amendment.get("revised_reasoning", ""),
        }

        n_amended += 1
        if direction == "up":
            n_up += 1
        elif direction == "down":
            n_down += 1

    return n_amended, n_up, n_down


# ── Main ───────────────────────────────────────────────────────────────────────

def _retroactive_amendment_skip_patch() -> int:
    """One-time patch: un-void picks that were voided by amendment auto-skip
    (Gate 1 at revised_conf < 70). These voids have void_reason starting with
    'Amendment auto-skip:' — they're confidence-based skips, not injury voids.

    The lineup_update sub-object is preserved so the amendment history remains
    visible on the frontend. Only voided=True and void_reason are cleared.

    Safe to run repeatedly — idempotent. Remove this function at the next
    architectural refactor (when Gate 1 is rewritten to use a non-voided
    amendment_skip field).
    """
    if not PICKS_JSON.exists():
        return 0
    try:
        with open(PICKS_JSON) as f:
            all_picks = json.load(f)
    except Exception as e:
        print(f"[lineup_update] WARNING: retroactive patch could not read picks.json: {e}")
        return 0

    patched = 0
    for p in all_picks:
        if p.get("date") != TODAY_STR:
            continue
        if not p.get("voided"):
            continue
        vr = (p.get("void_reason") or "").lower()
        if vr.startswith("amendment auto-skip"):
            p["voided"] = False
            p["void_reason"] = ""
            patched += 1
            print(
                f"[lineup_update] RETRO UN-VOID: {p.get('player_name')} "
                f"{p.get('prop_type')} {p.get('pick_value')} — "
                f"was voided by amendment auto-skip (not an injury)"
            )

    if patched:
        try:
            with open(PICKS_JSON, "w") as f:
                json.dump(all_picks, f, indent=2)
        except Exception as e:
            print(f"[lineup_update] ERROR: retroactive patch write failed: {e}")
            return 0

    return patched


def detect_clv_warnings(today_picks: list[dict], now_iso: str) -> dict:
    """
    Scan today's picks for the H34 signal (AST × lost_close, live).

    Mutates each affected pick in-place by writing a `clv_warning`
    sub-object. Does NOT modify `confidence_pct`, `voided`, `result`,
    `lineup_update`, or any other existing field.

    A warning fires when ALL conditions hold:
      - pick.prop_type in CLV_WARN_PROP_TYPES (AST only)
      - pick.morning_implied_prob is not None
      - pick.market_implied_prob is not None
      - live_clv_pp < CLV_WARN_LOST_THRESHOLD (-0.5)
      - pick is not voided
      - pick has no graded result yet (result is None / not set)

    Idempotent: re-running on the same picks updates the warning's
    `live_clv_pp` and `last_observed_at` fields with the latest pretip
    data, but does not duplicate. If the live_clv_pp moves back above
    -0.5 on a later cycle, the warning is REMOVED (line moved back
    toward us; no longer a warning candidate).

    Returns: {"fired": int, "cleared": int, "skipped": int}
        fired   — picks that received a new or updated warning this cycle
        cleared — picks where a previously-set warning is now removed
                  (live_clv_pp recovered above -0.5 threshold)
        skipped — picks excluded due to filter (wrong prop, missing data,
                  voided, graded) — for diagnostic logging
    """
    fired = 0
    cleared = 0
    skipped = 0

    for p in today_picks:
        # Filter — must be AST today's pick with both odds fields and not graded/voided
        if p.get("prop_type") not in CLV_WARN_PROP_TYPES:
            skipped += 1
            continue
        if p.get("voided") is True:
            skipped += 1
            continue
        if p.get("result") in ("HIT", "MISS"):
            # Already graded (e.g. early game outcome arrived) — don't add
            # a pretip warning to a settled pick.
            skipped += 1
            continue

        morning = p.get("morning_implied_prob")
        market  = p.get("market_implied_prob")
        if morning is None or market is None:
            skipped += 1
            continue

        try:
            live_clv = round(float(market) - float(morning), 2)
        except (TypeError, ValueError):
            skipped += 1
            continue

        existing = p.get("clv_warning")

        if live_clv < CLV_WARN_LOST_THRESHOLD:
            # Warning fires (or refreshes)
            warning = {
                "type":               "ast_lost_close",
                "live_clv_pp":        live_clv,
                "morning_implied_prob": round(float(morning), 1),
                "market_implied_prob":  round(float(market), 1),
                "threshold":          CLV_WARN_LOST_THRESHOLD,
                "proposed_penalty_pp": CLV_WARN_PROPOSED_PENALTY,
                "applied":            False,
                "first_observed_at":  (existing.get("first_observed_at")
                                       if existing else now_iso),
                "last_observed_at":   now_iso,
                "source_backtest":    "H34 — backtest_clv_ast_disagree (2026-04-30)",
            }
            p["clv_warning"] = warning
            fired += 1
        elif existing is not None:
            # Warning was previously set but live_clv has recovered above
            # the threshold — clear it.
            p.pop("clv_warning", None)
            cleared += 1

    return {"fired": fired, "cleared": cleared, "skipped": skipped}


def main() -> None:
    # One-time retroactive patch — un-void amendment auto-skip picks that were
    # incorrectly carrying injury-void semantics. Idempotent; safe to run every cycle.
    _n_retro = _retroactive_amendment_skip_patch()
    if _n_retro:
        print(f"[lineup_update] Retroactive patch applied: un-voided {_n_retro} amendment auto-skip pick(s)")

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true",
                        help="Diagnostic mode — prints full state, no LLM call, no file writes")
    args = parser.parse_args()
    debug = args.debug
    if debug:
        print("[lineup_update] *** DEBUG MODE — read only, no writes, no LLM call ***\n")

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

    # ── Load picks (needed for picks-based change detection) ───────────────────
    if not PICKS_JSON.exists():
        print("[lineup_update] no picks.json found — skipping")
        return

    with open(PICKS_JSON) as fh:
        all_picks: list[dict] = json.load(fh)

    today_picks = [p for p in all_picks if p.get("date") == TODAY_STR]
    if not today_picks:
        print("[lineup_update] no picks today — skipping")
        return

    # ── Compute changes (uses both snapshot and picks-based sources) ────────────
    snap_teams_debug = (lineups.get("snapshot_at_analyst_run") or {}).get("teams", {}).keys()
    changes = compute_lineup_diff(lineups, injuries, today_picks=today_picks)

    if debug:
        print(f"[lineup_update] DEBUG: snapshot teams found: {list(snap_teams_debug)}")
        print(f"[lineup_update] DEBUG: changes detected: {len(changes)}")
        for c in changes:
            print(f"  [{c.get('source','?')}] {c['detail']}")
        if not changes:
            print("  (none — check snapshot starters and injury report overlap)")
        print()

    if not changes:
        print("[lineup_update] no changes detected — skipping LLM call")
        return

    print(f"[lineup_update] detected {len(changes)} change(s):")
    for c in changes:
        print(f"  {c['detail']}")

    # ── Find affected picks ────────────────────────────────────────────────────
    game_map       = load_game_map()
    affected_picks = get_affected_picks(today_picks, changes, game_map, now_et)

    if debug:
        print(f"[lineup_update] DEBUG: affected picks: {len(affected_picks)}")
        for p in affected_picks:
            print(f"  {p['player_name']} ({p['team']}) {p['prop_type']} OVER {p['pick_value']}")
        print()

    # ── LLM amendment path (only when open picks are affected) ─────────────────
    if affected_picks:
        if debug:
            print(f"[lineup_update] DEBUG: would call Claude for {len(affected_picks)} pick(s) — skipping in debug mode")
        else:
            print(f"[lineup_update] {len(affected_picks)} pick(s) affected — calling Claude")

            # ── Build Rotowire context for changed teams ──────────────────────
            changed_teams: set[str] = {_norm(c["team"]) for c in changes}
            rotowire_ctx = build_rotowire_context(lineups, changed_teams)
            if rotowire_ctx:
                print(f"[lineup_update] Rotowire context built for {len(changed_teams)} team(s)")

            # ── Call Claude ───────────────────────────────────────────────────
            try:
                amendments = call_lineup_update(
                    affected_picks,
                    changes,
                    rotowire_context=rotowire_ctx,
                    player_stats=player_stats,
                )
            except Exception as e:
                print(f"[lineup_update] ERROR calling Claude: {e}")
                amendments = []

            if amendments:
                # ── Apply (write deferred to end of main()) ──────────────────
                n_amended, n_up, n_down = apply_amendments(
                    all_picks, amendments, affected_picks, changes, now_iso,
                    player_stats=player_stats,
                )

                n_unchanged = n_amended - n_up - n_down
                print(
                    f"[lineup_update] changes={len(changes)} affected_picks={len(affected_picks)} "
                    f"amended={n_amended} ({n_up} up, {n_down} down, {n_unchanged} unchanged)"
                )
            else:
                print("[lineup_update] no amendments returned — no in-memory amendments applied")
    else:
        print("[lineup_update] no actionable picks affected by changes — skipping LLM call")

    # ── Opportunity surfacing — runs whenever any absence changes exist ─────────
    has_absences = any(c.get("change_type") == "new_absence" for c in changes)
    if has_absences:
        game_log = load_game_log()
        suggestions = build_opportunity_suggestions(
            changes=changes,
            today_picks=today_picks,
            player_stats=player_stats,
            game_log=game_log,
            now_iso=now_iso,
            injuries=injuries,
        )
        if suggestions:
            if debug:
                print(f"[lineup_update] DEBUG: opportunity suggestions (not saved in debug mode):")
                for s in suggestions:
                    qt_str = ", ".join(
                        f"{p} T{d['tier']} {d['hit_rate_pct']}%"
                        for p, d in s.get("qualifying_tiers", {}).items()
                    ) or "—"
                    up_str = ", ".join(
                        f"{p} T{d['morning_tier']}→T{d['tier']}"
                        for p, d in s.get("upgrade_tiers", {}).items()
                    ) or "—"
                    pri_str = " ★ HIGH" if s.get("priority") == "high" else ""
                    cannib_str = f" | H33: {s['cannib_detail']}" if s.get("cannib_detail") else ""
                    print(
                        f"  {s['player_name']} ({s['team']}) [{s['card_type']}]{pri_str} "
                        f"new={qt_str} upgrade={up_str} "
                        f"← {s['triggered_by']} ({s['side']}){cannib_str}"
                    )
            else:
                save_opportunity_flags(suggestions)
                print(f"[lineup_update] opportunity: {len(suggestions)} suggestion(s) surfaced")
        else:
            print("[lineup_update] opportunity: no qualifying teammate suggestions found")

    # ── Skip reconsideration — re-evaluate merit_below_floor skips on star absence ──
    # H26 Part 2: when a team's leading scorer is confirmed OUT today, re-check
    # morning merit_below_floor PTS/AST skips against star_absence_lift data to
    # see if any cross the 70% floor and warrant reconsideration. Outputs go to
    # opportunity_flags.json via the same save_opportunity_flags() pipeline with
    # card_type="skip_reconsideration".
    if has_absences and not debug:
        game_log_recon = game_log if game_log is not None else load_game_log()
        recons = build_skip_reconsiderations(
            changes=changes,
            player_stats=player_stats,
            game_log=game_log_recon,
            now_iso=now_iso,
        )
        if recons:
            save_opportunity_flags(recons)
            print(f"[lineup_update] skip-recon: {len(recons)} reconsideration(s) surfaced")
        else:
            print("[lineup_update] skip-recon: no qualifying reconsiderations found")
    elif has_absences and debug:
        game_log_recon = game_log if game_log is not None else load_game_log()
        recons = build_skip_reconsiderations(
            changes=changes,
            player_stats=player_stats,
            game_log=game_log_recon,
            now_iso=now_iso,
        )
        if recons:
            print(f"[lineup_update] DEBUG skip-recon: {len(recons)} reconsideration(s) (not saved):")
            for r in recons:
                print(f"  {r['player_name']} {r['prop_type']} T{r['tier_considered']} — {r['reasoning']}")
        else:
            print("[lineup_update] DEBUG skip-recon: no qualifying reconsiderations found")

    # ── H34 CLV Warning Detection (observability only — no confidence change) ──
    # Scans today's AST picks for live_clv_pp < -0.5 (the lost_close threshold
    # validated in backtest_clv_ast_disagree.json). Writes/refreshes a
    # `clv_warning` sub-object on each affected pick. Does NOT modify
    # confidence_pct, voided, result, or lineup_update fields.
    # Activation (actual confidence haircut) is a future prompt depending on
    # 7+ days of accumulated observability data.
    clv_report = detect_clv_warnings(today_picks, now_iso)
    if clv_report["fired"] or clv_report["cleared"]:
        print(
            f"[lineup_update] CLV warnings — fired: {clv_report['fired']}, "
            f"cleared: {clv_report['cleared']}, skipped: {clv_report['skipped']}"
        )
        # Diagnostic listing of currently-active warnings on today's slate
        active = [p for p in today_picks if p.get("clv_warning") is not None]
        if active:
            print(f"[lineup_update] Active CLV warnings ({len(active)}):")
            for p in active:
                w = p["clv_warning"]
                print(
                    f"  {p['player_name']} ({p['team']}) AST T{p['pick_value']} — "
                    f"live_clv {w['live_clv_pp']:+.2f}pp "
                    f"({w['morning_implied_prob']:.1f}% → {w['market_implied_prob']:.1f}%)"
                )
    else:
        print("[lineup_update] CLV warnings — no AST × lost_close fires this cycle")

    # ── Unified picks.json write ───────────────────────────────────────────
    # Single write covering all in-memory mutations (LLM amendments + CLV
    # warnings). Skipped in debug mode. Atomic via tmp + os.replace.
    if not debug:
        tmp = PICKS_JSON.with_suffix(".json.tmp")
        with open(tmp, "w") as fh:
            json.dump(all_picks, fh, indent=2)
        os.replace(tmp, PICKS_JSON)


if __name__ == "__main__":
    main()
