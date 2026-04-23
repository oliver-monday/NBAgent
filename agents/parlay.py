#!/usr/bin/env python3
"""
NBAgent — Parlay Agent (Combinatorial Menu Builder)

Runs after Analyst. Pure-Python — no LLM call, zero API cost.

Reads today's picks from data/picks.json and constructs a ranked menu of
parlay cards across three odds buckets (Value / Standard / Reach). Uses
market_implied_prob (FanDuel) for odds construction — that's what determines
the actual payout — and confidence_pct (system's stated confidence) for
ranking — that's the system's prediction of which card is most likely to hit.

The two are intentionally separated:
  - market_implied_prob → odds bucket placement + advertised payout
  - confidence_pct      → ranking score (highest combined confidence wins)

Why no LLM:
  The previous LLM-based selection hit 59.8% (52/87) despite individual picks
  hitting at 85.7%. Random 2-leg construction would have hit ~73%. The LLM
  destroyed value by selecting legs that correlate on failure modes and
  over-indexing on narrative coherence. Combinatorial enumeration with
  game-independence as the structural guard is strictly better.

Output: 5-10 cards per day, written to data/parlays.json in the existing
[{date, parlays: [...]}] bundle format. Card schema is compatible with
auditor grading and frontend rendering.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from itertools import combinations
from pathlib import Path
from zoneinfo import ZoneInfo


# ── Paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PICKS_JSON        = DATA / "picks.json"
PARLAYS_JSON      = DATA / "parlays.json"
INJURIES_JSON     = DATA / "injuries_today.json"
PICKS_REVIEW_DIR  = DATA  # daily files: data/picks_review_YYYY-MM-DD.json

ET = ZoneInfo("America/Los_Angeles")
TODAY = dt.datetime.now(ET).date()
TODAY_STR = TODAY.strftime("%Y-%m-%d")


# ── Config ────────────────────────────────────────────────────────────
# Odds buckets: (label, min_american_odds, max_american_odds, target_cards)
ODDS_BUCKETS = [
    ("Value",    100,  200, 4),
    ("Standard", 200,  350, 3),
    ("Reach",    350,  600, 2),
]

MAX_LEGS         = 8     # absolute ceiling per card
MAX_COMBO_POOL   = 25    # cap legs before combo generation (performance)
MIN_LEGS         = 2     # minimum legs per card
MIN_CONFIDENCE   = 70    # individual leg confidence floor (matches analyst's PTS/AST grace zone)
MAX_CANDIDATES   = 50    # early-termination threshold per bucket
MAX_PLAYER_CARDS = 2     # no player appears in more than this many cards


# ── Injury exclusion helpers ──────────────────────────────────────────

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


def _load_out_players() -> set[tuple[str, str]]:
    """Return (last_name_lower, norm_team_upper) tuples for OUT/DOUBTFUL players."""
    if not INJURIES_JSON.exists():
        return set()
    try:
        with open(INJURIES_JSON) as f:
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


# ── Odds math ─────────────────────────────────────────────────────────

def american_odds(combined_prob: float) -> int:
    """Convert combined probability to American odds integer."""
    if combined_prob <= 0 or combined_prob >= 1:
        return 0
    if combined_prob < 0.5:
        return round(((1 / combined_prob) - 1) * 100)
    else:
        return round(-100 / ((1 / combined_prob) - 1))


def format_odds(odds: int) -> str:
    return f"+{odds}" if odds >= 0 else str(odds)


# ── Loaders ───────────────────────────────────────────────────────────

def load_todays_picks_review() -> dict[tuple, str]:
    """
    Load today's picks review file.
    Returns {(player_name_lower, prop_type, pick_value): verdict} for quick lookup.
    Returns {} gracefully if file is absent or malformed.
    verdict values: "keep" | "trim" | "manual_skip"
    """
    path = DATA / f"picks_review_{TODAY_STR}.json"
    if not path.exists():
        return {}
    try:
        with open(path) as fh:
            entries = json.load(fh)
        result: dict[tuple, str] = {}
        for e in entries:
            name    = (e.get("player_name") or "").strip().lower()
            pt      = e.get("prop_type", "")
            pv      = e.get("pick_value")
            verdict = e.get("verdict", "")
            if name and pt and pv is not None and verdict in ("keep", "trim", "manual_skip"):
                result[(name, pt, pv)] = verdict
        print(f"[parlay] Loaded picks review: {len(result)} entries")
        return result
    except Exception as e:
        print(f"[parlay] WARNING: could not load picks review: {e}")
        return {}


def load_todays_picks() -> list[dict]:
    """Load today's eligible picks for parlay construction.

    Filters applied:
      - date == TODAY_STR
      - confidence_pct >= MIN_CONFIDENCE
      - result is None (not already graded)
      - voided != True
      - player not OUT/DOUBTFUL in injuries_today.json
      - human_verdict != "manual_skip" (from picks_review_YYYY-MM-DD.json)
      - market_implied_prob is not None (required for odds construction)

    Each returned pick carries `_human_verdict` ("trim", "keep", or None).
    """
    if not PICKS_JSON.exists():
        return []
    with open(PICKS_JSON) as f:
        all_picks = json.load(f)

    out_players  = _load_out_players()
    picks_review = load_todays_picks_review()

    picks: list[dict] = []
    n_no_market = 0
    for p in all_picks:
        if p.get("date") != TODAY_STR:
            continue
        if p.get("confidence_pct", 0) < MIN_CONFIDENCE:
            continue
        if p.get("result") is not None:  # already graded
            continue
        if p.get("voided", False):
            continue
        # Hard exclude OUT/DOUBTFUL even if not yet voided by lineup_watch
        if out_players:
            last   = _extract_last(p.get("player_name") or "")
            norm_t = _norm_team(p.get("team") or "")
            if (last, norm_t) in out_players:
                print(f"[parlay] EXCLUDED (OUT/DOUBTFUL): {p.get('player_name')} ({p.get('team')})")
                continue
        # Apply human review verdict
        review_key = (
            (p.get("player_name") or "").strip().lower(),
            p.get("prop_type", ""),
            p.get("pick_value"),
        )
        verdict = picks_review.get(review_key)
        if verdict == "manual_skip":
            print(f"[parlay] EXCLUDED (manual_skip): {p.get('player_name')} {p.get('prop_type')} T{p.get('pick_value')}")
            continue
        # Require market_implied_prob — without it we can't construct odds
        if p.get("market_implied_prob") is None:
            n_no_market += 1
            continue
        # Carry verdict through
        p = p.copy()
        p["_human_verdict"] = verdict  # "trim", "keep", or None
        picks.append(p)

    if n_no_market:
        print(f"[parlay] EXCLUDED ({n_no_market} picks): no market_implied_prob")
    return picks


# ── Card construction helpers ────────────────────────────────────────

def _game_key(pick: dict) -> str:
    """Return a canonical game key for independence checking."""
    team = (pick.get("team") or "").upper()
    opp  = (pick.get("opponent") or "").upper()
    return "_".join(sorted([team, opp]))


def find_min_legs_for_bucket(legs_sorted: list[dict], target_max_prob: float) -> int:
    """Find the minimum number of legs needed to push combined market prob
    below target_max_prob. Uses the highest-probability legs (safest picks)
    as the optimistic bound — this is the FEWEST legs that could possibly
    place a card in this bucket.

    `legs_sorted` must be sorted by market_implied_prob DESCENDING.

    Returns the leg count, or -1 if even the full pool can't reach the target.
    """
    prob = 1.0
    for i, leg in enumerate(legs_sorted):
        prob *= leg["market_implied_prob"] / 100
        if prob <= target_max_prob:
            return i + 1
    return -1


def build_leg_dict(pick: dict) -> dict:
    """Extract the per-leg fields needed in the parlay output schema."""
    return {
        "player_name":         pick["player_name"],
        "prop_type":           pick["prop_type"],
        "pick_value":          pick["pick_value"],
        "direction":           pick.get("direction", "OVER"),
        "confidence_pct":      pick.get("confidence_pct"),
        "market_implied_prob": pick.get("market_implied_prob"),
        "iron_floor":          pick.get("iron_floor", False),
    }


def rank_score(card: dict) -> float:
    """Composite ranking score. Higher = better.

    Primary signal is the system's combined confidence product (× 1000 to
    dominate the bonuses). Game independence and iron_floor add structural
    certainty bonuses. Slight preference for fewer legs at the same odds
    (each leg multiplies failure risk).
    """
    return (
        card["combined_confidence"] * 1000   # primary: system confidence product
        + card["n_games"]            * 5     # bonus: game independence
        + card["iron_floor_count"]   * 3     # bonus: structural certainty
        - card["n_legs"]             * 1     # slight preference for fewer legs
    )


def enforce_player_cap(cards: list[dict], max_appearances: int) -> list[dict]:
    """Drop lower-ranked cards that would push any single player above
    `max_appearances` total cards in the menu. Cards are processed in
    rank order (highest first) — if an incoming card would put any of its
    players over the cap, it's dropped.
    """
    appearances: dict[str, int] = {}
    kept: list[dict] = []
    for card in cards:
        names = [leg["player_name"] for leg in card["legs"]]
        # Would adding this card push any player over the cap?
        violates = any(appearances.get(n, 0) + 1 > max_appearances for n in names)
        if violates:
            continue
        for n in names:
            appearances[n] = appearances.get(n, 0) + 1
        kept.append(card)
    dropped = len(cards) - len(kept)
    if dropped:
        print(f"[parlay] enforce_player_cap: dropped {dropped} card(s) "
              f"to keep max {max_appearances} appearances per player")
    return kept


# ── Output ────────────────────────────────────────────────────────────

def save_parlays(parlays: list[dict]):
    """Append today's parlay bundle to data/parlays.json (idempotent re-run).

    Schema preserved exactly: list of {date, parlays: [...]} bundles. Each
    parlay gains date, id, result=null, legs_hit=null, legs_total at save time.
    The auditor and frontend depend on this structure.
    """
    existing = []
    if PARLAYS_JSON.exists():
        try:
            with open(PARLAYS_JSON) as f:
                existing = json.load(f)
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

    # Remove today's bundle (idempotent re-run)
    existing = [b for b in existing if b.get("date") != TODAY_STR]

    # Add metadata required by the auditor + frontend
    for i, p in enumerate(parlays):
        p["date"]       = TODAY_STR
        p["id"]         = f"parlay_{TODAY_STR}_{i+1:02d}"
        p["result"]     = None
        p["legs_hit"]   = None
        p["legs_total"] = len(p.get("legs", []))

    updated = existing + [{
        "date":    TODAY_STR,
        "parlays": parlays,
    }]

    with open(PARLAYS_JSON, "w") as f:
        json.dump(updated, f, indent=2)

    print(f"[parlay] Saved {len(parlays)} parlays for {TODAY_STR} → {PARLAYS_JSON}")
    for p in parlays:
        legs_str = " | ".join(
            f"{l['player_name']} {l['prop_type']} OVER {l['pick_value']}"
            for l in p.get("legs", [])
        )
        print(f"  [{p['implied_odds']}] {p['label']}  "
              f"(conf={p['combined_confidence']:.3f}, "
              f"games={p['n_games']}, iron={p['iron_floor_count']}): "
              f"{legs_str}")


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print(f"[parlay] Running combinatorial builder for {TODAY_STR}")

    picks = load_todays_picks()
    print(f"[parlay] Loaded {len(picks)} eligible picks (with market odds)")

    if len(picks) < 3:
        print(f"[parlay] Not enough picks with market odds ({len(picks)}). Exiting.")
        return

    # Cap pool for performance — C(25, 8) ≈ 1.1M is workable; larger blows up
    if len(picks) > MAX_COMBO_POOL:
        picks = sorted(picks, key=lambda p: p["confidence_pct"], reverse=True)[:MAX_COMBO_POOL]
        print(f"[parlay] Capped to top {MAX_COMBO_POOL} by confidence")

    # Sort by market_implied_prob descending — used for the min_legs computation
    # (the safest legs first give the optimistic bound on how few legs are needed)
    picks_by_prob = sorted(picks, key=lambda p: p["market_implied_prob"], reverse=True)

    all_cards: list[dict] = []
    for bucket_label, min_odds, max_odds, target_n in ODDS_BUCKETS:
        # American odds → probability bounds
        # +100 → 0.50, +200 → 0.333, +350 → 0.222, +600 → 0.143
        max_prob = 100 / (min_odds + 100)   # lower odds = higher prob = upper bound
        min_prob = 100 / (max_odds + 100)   # higher odds = lower prob = lower bound

        min_legs = find_min_legs_for_bucket(picks_by_prob, max_prob)
        if min_legs < 0 or min_legs > MAX_LEGS:
            print(f"[parlay] {bucket_label}: cannot reach +{min_odds} within "
                  f"{MAX_LEGS} legs — skipping bucket")
            continue
        if min_legs < MIN_LEGS:
            min_legs = MIN_LEGS

        print(f"[parlay] {bucket_label} (+{min_odds} to +{max_odds}): "
              f"min {min_legs} legs needed")

        candidates: list[dict] = []
        upper_n = min(min_legs + 4, MAX_LEGS + 1)
        for n in range(min_legs, upper_n):
            if len(candidates) >= MAX_CANDIDATES:
                break
            for combo in combinations(picks, n):
                # No duplicate players
                names = set()
                dupe = False
                for leg in combo:
                    name = leg["player_name"]
                    if name in names:
                        dupe = True
                        break
                    names.add(name)
                if dupe:
                    continue

                # Compute combined market probability
                combined_market = 1.0
                for leg in combo:
                    combined_market *= leg["market_implied_prob"] / 100
                if combined_market > max_prob or combined_market < min_prob:
                    continue

                # Confirm odds bucket placement
                odds = american_odds(combined_market)
                if odds < min_odds or odds > max_odds:
                    continue

                # System confidence product (used for ranking)
                combined_conf = 1.0
                for leg in combo:
                    combined_conf *= leg["confidence_pct"] / 100

                # Game independence
                game_keys = set(_game_key(leg) for leg in combo)
                n_games = len(game_keys)

                # Iron floor count
                iron_count = sum(1 for leg in combo if leg.get("iron_floor"))

                card = {
                    "legs":                 [build_leg_dict(leg) for leg in combo],
                    "n_legs":               len(combo),
                    "combined_market_prob": round(combined_market, 4),
                    "combined_confidence":  round(combined_conf, 4),
                    "implied_odds":         format_odds(odds),
                    "implied_odds_int":     odds,
                    "n_games":              n_games,
                    "iron_floor_count":     iron_count,
                    "bucket":               bucket_label,
                }
                card["rank_score"] = round(rank_score(card), 2)

                # Correlation label (frontend badge)
                if n_games == len(combo):
                    card["correlation"] = "independent"
                elif n_games == 1:
                    card["correlation"] = "positive"
                else:
                    card["correlation"] = "mixed"

                candidates.append(card)

        # Rank within bucket and select top N
        candidates.sort(key=lambda c: c["rank_score"], reverse=True)
        selected = candidates[:target_n]

        # Label cards in rank order
        for i, card in enumerate(selected):
            card["label"] = f"{bucket_label} #{i + 1}"

        all_cards.extend(selected)
        print(f"[parlay] {bucket_label}: {len(candidates)} candidates → "
              f"selected {len(selected)}")

    if not all_cards:
        print("[parlay] No valid parlay cards generated. Exiting.")
        return

    # Final pass: cap each player's appearances across the whole menu
    # (cards are already in rank order within buckets; sort all_cards by
    # rank_score globally so the cap drops the weakest duplicates first)
    all_cards.sort(key=lambda c: c["rank_score"], reverse=True)
    all_cards = enforce_player_cap(all_cards, max_appearances=MAX_PLAYER_CARDS)

    # Re-label after cap (so labels stay sequential within their bucket)
    by_bucket: dict[str, list[dict]] = {}
    for card in all_cards:
        by_bucket.setdefault(card["bucket"], []).append(card)
    for label, cards in by_bucket.items():
        cards.sort(key=lambda c: c["rank_score"], reverse=True)
        for i, card in enumerate(cards):
            card["label"] = f"{label} #{i + 1}"
    # Reassemble in bucket order (Value → Standard → Reach)
    all_cards = []
    for bucket_label, *_ in ODDS_BUCKETS:
        all_cards.extend(by_bucket.get(bucket_label, []))

    save_parlays(all_cards)
    print(f"[parlay] Total: {len(all_cards)} cards across "
          f"{sum(1 for k in by_bucket if by_bucket[k])} bucket(s)")


if __name__ == "__main__":
    sys.exit(main() or 0)
