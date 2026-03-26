#!/usr/bin/env python3
"""
Fetch Rotowire injuries and update data/injuries_today.json + logs/injury_log.csv.
Best-effort only: if scrape fails or yields empty, do not overwrite existing JSON.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

ROTOWIRE_URL = "https://www.rotowire.com/basketball/nba-lineups.php"
ROTOWIRE_LOGIN_URL = "https://www.rotowire.com/users/login.php"
ROTOWIRE_MINUTES_URL = "https://www.rotowire.com/basketball/projected-minutes.php"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def _short_status(s: str) -> str:
    t = (s or "").strip().lower()
    if not t:
        return ""
    if "out for season" in t or "ofs" in t:
        return "OFS"
    if "out" in t:
        return "OUT"
    if "doubt" in t:
        return "DOUBT"
    if "question" in t:
        return "QUES"
    if "prob" in t:
        return "PROB"
    if "day-to-day" in t or "dtd" in t:
        return "DTD"
    if "gtd" in t or "game-time" in t:
        return "GTD"
    if "rest" in t:
        return "REST"
    if "susp" in t:
        return "SUSP"
    return s.strip().upper()


def login_rotowire(session: requests.Session) -> bool:
    """
    POST credentials to Rotowire login endpoint.
    Returns True on success, False on failure.
    Credentials are read from env vars ROTOWIRE_EMAIL and ROTOWIRE_PASSWORD.
    """
    email    = os.environ.get("ROTOWIRE_EMAIL", "")
    password = os.environ.get("ROTOWIRE_PASSWORD", "")
    if not email or not password:
        print("[injuries] ROTOWIRE_EMAIL / ROTOWIRE_PASSWORD not set — skipping auth")
        return False
    try:
        resp = session.post(
            ROTOWIRE_LOGIN_URL,
            data={"username": email, "password": password},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
            allow_redirects=True,
        )
        if resp.status_code == 200:
            print("[injuries] Rotowire login succeeded")
            return True
        print(f"[injuries] Rotowire login HTTP {resp.status_code}")
        return False
    except Exception as exc:
        print(f"[injuries] Rotowire login error: {exc}")
        return False


def fetch_rotowire_html(session: requests.Session | None = None) -> str | None:
    try:
        requester = session if session is not None else requests
        resp = requester.get(
            ROTOWIRE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
    except Exception as exc:
        print(f"[injuries] Rotowire fetch error: {exc}")
        return None
    if resp.status_code != 200:
        print(f"[injuries] Rotowire HTTP {resp.status_code}, skipping.")
        return None
    return resp.text


def fetch_rotowire_minutes_html(session: requests.Session) -> str | None:
    """Fetch the dedicated projected-minutes page (subscription required)."""
    try:
        resp = session.get(
            ROTOWIRE_MINUTES_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
    except Exception as exc:
        print(f"[injuries] projected-minutes fetch error: {exc}")
        return None
    if resp.status_code != 200:
        print(f"[injuries] projected-minutes HTTP {resp.status_code}, skipping.")
        return None
    return resp.text


def parse_rotowire_injuries(html: str) -> Dict[str, List[Dict[str, str]]]:
    injuries_today: Dict[str, List[Dict[str, str]]] = {}
    team_abbrevs = {
        "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW","HOU","IND",
        "LAC","LAL","MEM","MIA","MIL","MIN","NOP","NYK","OKC","ORL","PHI","PHX",
        "POR","SAC","SAS","TOR","UTA","WAS",
    }

    def normalize_status_raw(raw: str) -> tuple[str, str]:
        t = (raw or "").strip().lower()
        if "out for season" in t or "ofs" in t:
            return "OFS", "OFS"
        if "out" in t:
            return "OUT", "Out"
        if "doubt" in t:
            return "DOUBT", "Doubt"
        if "question" in t or t.startswith("ques"):
            return "QUES", "Ques"
        if "prob" in t:
            return "PROB", "Prob"
        if "gtd" in t or "game-time" in t:
            return "GTD", "GTD"
        if "day-to-day" in t or "dtd" in t:
            return "DTD", "DTD"
        if "rest" in t:
            return "REST", "Rest"
        if "susp" in t:
            return "SUSP", "Susp"
        return _short_status(raw), raw.strip()

    team_block_pattern = re.compile(
        r'data-team="([A-Z]{2,3})"[^>]*>On/Off Court Stats</button>(.*?)</ul>',
        re.DOTALL,
    )
    matches = team_block_pattern.findall(html)

    for team, block in matches:
        team = team.upper()
        entries: List[Dict[str, str]] = []

        for player_html, status_html in re.findall(
            r'<li[^>]*has-injury-status[^>]*>.*?'
            r'<a[^>]*>(.*?)</a>.*?'
            r'<span class="lineup__inj">(.*?)</span>',
            block,
            flags=re.DOTALL,
        ):
            name = re.sub(r"<.*?>", "", player_html).strip()
            status_raw = re.sub(r"<.*?>", "", status_html).strip()
            if not status_raw:
                m = re.search(r"\(([^)]+)\)", status_html)
                if m:
                    status_raw = m.group(1).strip()
            if not name or not status_raw:
                continue

            status_lower = status_raw.lower()
            keep = any(
                key in status_lower
                for key in (
                    "out",
                    "out for season",
                    "ofs",
                    "doubt",
                    "question",
                    "ques",
                    "prob",
                    "day-to-day",
                    "dtd",
                    "gtd",
                    "game-time",
                    "rest",
                    "susp",
                    "ill",
                )
            ) or status_raw.upper() == "OFS"
            if not keep:
                continue

            status = _short_status(status_raw)
            details = f"{name} ({status_raw})"
            entries.append({"name": name, "status": status, "details": details})

        if entries:
            deduped = {(e["name"].strip(), e["status"].strip(), e["details"].strip()): e for e in entries}
            injuries_today[team] = list(deduped.values())

    # Second pass: scrape "May Not Play" style statuses from the full page.
    soup = BeautifulSoup(html, "lxml")
    status_pattern = re.compile(
        r"^(prob|ques|question|doubt|gtd|day-to-day|dtd|out|ofs|rest|susp)",
        re.IGNORECASE,
    )
    for s in soup.find_all(string=status_pattern):
        status_raw = str(s).strip()
        if not status_raw:
            continue
        status_code, status_display = normalize_status_raw(status_raw)
        if not status_code:
            continue

        el = s.parent
        row = el.find_parent(lambda tag: tag.find("a") is not None)
        if not row:
            continue
        name_tag = row.find("a")
        name = name_tag.get_text(strip=True) if name_tag else ""
        if not name:
            continue

        team = ""
        for ancestor in [row] + list(row.parents):
            for text in ancestor.stripped_strings:
                txt = str(text).strip().upper()
                if txt in team_abbrevs:
                    team = txt
                    break
            if team:
                break
        if not team:
            continue

        details = f"{name} ({status_display})"
        injuries_today.setdefault(team, []).append(
            {"name": name, "status": status_code, "details": details}
        )

    # De-dupe per team by (name,status).
    for team, entries in list(injuries_today.items()):
        deduped = {}
        for e in entries:
            key = (e.get("name", "").strip(), e.get("status", "").strip())
            deduped[key] = e
        injuries_today[team] = list(deduped.values())

    # Debug counts
    counts = {}
    total = 0
    for entries in injuries_today.values():
        for e in entries:
            total += 1
            counts[e.get("status", "")] = counts.get(e.get("status", ""), 0) + 1
    print(f"[injuries] kept={total}")
    print(f"[injuries] status_counts={counts}")

    return injuries_today


def parse_rotowire_lineups(html: str) -> dict:
    """
    Parse projected starting lineups from the Rotowire nba-lineups.php page.

    Uses the data-team attribute on the 'On/Off Court Stats' button as the team anchor —
    the same reliable anchor used by parse_rotowire_injuries. The Expected Lineup section
    for each team appears in the HTML immediately before its On/Off button.

    Returns {team_abbr: {"starters": [...], "confirmed": bool}} with only teams
    that have at least one starter entry.
    """
    POSITIONS = {"PG", "SG", "SF", "PF", "C"}
    NBA_ABBREVS = {
        "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
        "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
    }
    lineups: dict = {}

    try:
        # Find all On/Off Court Stats buttons — each carries data-team for one team.
        # The Expected Lineup section for that team precedes this button in the HTML.
        onoff_re = re.compile(
            r'data-team="([A-Z]{2,3})"[^>]*>On/Off Court Stats</button>',
            re.DOTALL,
        )
        matches = list(onoff_re.finditer(html))
        if not matches:
            print("[lineups] No On/Off Court Stats buttons found — page structure may have changed")
            return {}

        for i, m in enumerate(matches):
            team = m.group(1).upper()
            if team not in NBA_ABBREVS:
                continue
            if team in lineups:
                continue

            # Grab the HTML chunk between the previous match end and this button start.
            # This chunk contains the Expected Lineup section for this team.
            prev_end = matches[i - 1].end() if i > 0 else 0
            section_html = html[prev_end: m.start()]

            section_soup = BeautifulSoup(section_html, "lxml")

            starters: list[dict] = []
            confirmed = False
            in_expected = False

            for li in section_soup.find_all("li"):
                text = li.get_text(" ", strip=True)

                # Section boundary markers
                if "Expected Lineup" in text and not li.find("a"):
                    in_expected = True
                    continue
                if any(marker in text for marker in (
                    "Projected Minutes", "On/Off Court Stats", "MAY NOT PLAY", "May Not Play",
                )):
                    in_expected = False
                    continue
                if re.search(r"\bConfirm", text, re.IGNORECASE):
                    confirmed = True

                if not in_expected:
                    continue

                # Position + player row: first word must be a position label
                words = text.split()
                if not words:
                    continue
                pos = words[0].upper()
                if pos not in POSITIONS:
                    continue

                a_tag = li.find("a")
                if not a_tag:
                    continue

                # title attribute holds the full name; link text may be abbreviated
                name = a_tag.get("title", "").strip() or a_tag.get_text(strip=True)
                if not name or len(name) < 3:
                    continue

                # Inline injury status — check for known status keywords in li text
                inj_status = None
                STATUS_WORDS = {"ques", "doubt", "out", "prob", "gtd", "ofs", "rest", "susp", "dtd"}
                for word in words:
                    w = word.lower().rstrip(".,")
                    if w in STATUS_WORDS:
                        inj_status = _short_status(word.rstrip(".,"))
                        break

                # Deduplicate by position — first occurrence wins
                if pos not in {s["position"] for s in starters}:
                    starters.append({
                        "position":      pos,
                        "name":          name,
                        "injury_status": inj_status,
                    })

            if starters:
                lineups[team] = {"starters": starters, "confirmed": confirmed}

    except Exception as e:
        print(f"[lineups] ERROR parsing lineups: {e}")

    # Drop teams with zero starters
    return {t: d for t, d in lineups.items() if d["starters"]}


def parse_projected_minutes(soup: BeautifulSoup) -> dict[str, list[dict]]:
    """
    Parse the Projected Minutes panel from rotowire.com/basketball/projected-minutes.php.

    Team sections are anchored by team logo images with src pattern /100{ABBREV}.png.
    Each section contains STARTERS / BENCH / MAY NOT PLAY / OUT sub-sections with
    per-player projected minute integers and optional injury status.

    Returns:
        {
          "LAL": [
            {"name": "LeBron James", "minutes": 36, "section": "STARTERS", "injury_status": None},
            {"name": "Austin Reaves", "minutes": 28, "section": "BENCH",    "injury_status": None},
            {"name": "Jarred Vanderbilt", "minutes": 0, "section": "OUT",   "injury_status": "Out"},
          ],
          ...
        }
    Returns {} on any parse error.
    """
    NBA_ABBREVS = {
        "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
        "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
    }
    SECTION_MAP = {
        "starters":     "STARTERS",
        "bench":        "BENCH",
        "may not play": "MAY NOT PLAY",
        "out":          "OUT",
    }
    STATUS_WORDS = {"questionable", "doubtful", "out", "probable", "gtd", "ofs",
                    "rest", "susp", "dtd", "day-to-day"}
    result: dict[str, list[dict]] = {}

    try:
        logo_re = re.compile(r'/100([A-Z]+)\.png', re.IGNORECASE)

        for img in soup.find_all("img", src=logo_re):
            m = logo_re.search(img.get("src", ""))
            if not m:
                continue
            team = m.group(1).upper()
            if team not in NBA_ABBREVS or team in result:
                continue

            # Walk up ancestors to find a container with player links
            player_link_re = re.compile(r'/basketball/player/')
            for ancestor in img.parents:
                player_links = ancestor.find_all("a", href=player_link_re)
                if len(player_links) < 2:
                    continue

                # Check for "Subscriber Exclusive" gating — skip if present
                if "Subscriber Exclusive" in ancestor.get_text():
                    break  # This team's data is subscription-gated; stop here

                players: list[dict] = []
                current_section = "STARTERS"

                # Walk all descendants in order to capture section headers and player rows
                for el in ancestor.descendants:
                    if not hasattr(el, "name"):
                        # NavigableString — check for section headers
                        text = str(el).strip()
                        tl = text.lower()
                        for key, val in SECTION_MAP.items():
                            if tl == key:
                                current_section = val
                                break
                        continue

                    if el.name != "a":
                        continue
                    href = el.get("href", "")
                    if "/basketball/player/" not in href:
                        continue

                    name = el.get_text(strip=True)
                    if not name or len(name) < 2:
                        continue

                    # Extract minutes + injury status from the enclosing <li>.
                    # The minutes integer is a sibling of the <a> tag, not inside
                    # its immediate parent wrapper — find_parent("li") is required.
                    parent = el.find_parent("li") or el.parent
                    if not parent:
                        continue
                    full_text = parent.get_text(" ", strip=True)
                    # Remove the player name from text to isolate status + minutes
                    remainder = full_text.replace(name, "", 1).strip()

                    minutes = 0
                    inj_status = None
                    for token in remainder.split():
                        if token.isdigit():
                            minutes = int(token)
                        elif token.lower().rstrip(".,") in STATUS_WORDS:
                            inj_status = _short_status(token.rstrip(".,"))

                    # Deduplicate by name
                    if name not in {p["name"] for p in players}:
                        players.append({
                            "name":          name,
                            "minutes":       minutes,
                            "section":       current_section,
                            "injury_status": inj_status,
                        })

                if players:
                    result[team] = players
                    break  # Found data for this team; stop walking up

    except Exception as e:
        print(f"[injuries] ERROR parsing projected minutes: {e}")
        return {}

    populated = sum(
        1 for players in result.values()
        for p in players
        if isinstance(p.get("minutes"), int) and p["minutes"] > 0
    )
    print(f"[injuries] projected_minutes: parsed {len(result)} teams, "
          f"{populated} players with minutes > 0")
    return result


def parse_onoff_usage(soup: BeautifulSoup) -> dict[str, list[dict]]:
    """
    On/Off Court Stats are loaded via JavaScript after a button click and are not
    present in the server-rendered HTML fetched by requests.get(). This function
    always returns {} cleanly.

    Keeping the function signature intact so callers in main() require no changes.
    A future implementation using a headless browser (e.g. Playwright) could populate
    this data; see ROADMAP_offseason.md for that deferred item.
    """
    print("[injuries] onoff_usage: skipped (data is JS-loaded, not in server HTML)")
    return {}


def write_lineups_json(
    lineups: dict,
    asof_date: str,
    built_at_utc: str,
    projected_minutes: dict | None = None,
    onoff_usage: dict | None = None,
) -> None:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "lineups_today.json"
    tmp_path = data_dir / "lineups_today.json.tmp"

    # Preserve the analyst snapshot key if already written this morning.
    # This key is written by analyst.py after picks run and must survive
    # hourly Rotowire refreshes — without it, lineup_update.py always skips.
    existing_snapshot = None
    if out_path.exists():
        try:
            with open(out_path) as _fh:
                _existing = json.load(_fh)
            existing_snapshot = _existing.get("snapshot_at_analyst_run")
        except Exception:
            pass  # If we can't read it, just proceed without preserving

    payload = {
        "asof_date": asof_date,
        "built_at_utc": built_at_utc,
        "source": "rotowire",
        **lineups,
    }

    # Re-inject snapshot if it existed
    if existing_snapshot:
        payload["snapshot_at_analyst_run"] = existing_snapshot

    # Merge projected_minutes and onoff_usage into per-team entries
    if projected_minutes:
        for team, minutes_data in projected_minutes.items():
            if team in payload and isinstance(payload[team], dict):
                payload[team]["projected_minutes"] = minutes_data
            else:
                payload[team] = {"starters": [], "confirmed": False,
                                 "projected_minutes": minutes_data}
    if onoff_usage:
        for team, usage_data in onoff_usage.items():
            if team in payload and isinstance(payload[team], dict):
                payload[team]["onoff_usage"] = usage_data
            else:
                payload[team] = {"starters": [], "confirmed": False,
                                 "onoff_usage": usage_data}

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp_path, out_path)


def append_injury_log(injuries_today: Dict[str, List[Dict[str, str]]], asof_date: str) -> None:
    if not injuries_today:
        return

    rows = []
    for team, entries in injuries_today.items():
        for e in entries:
            rows.append({
                "asof_date": asof_date,
                "team_abbrev": team,
                "player_name": e.get("name", ""),
                "status": e.get("status", ""),
                "details": e.get("details", ""),
                "source": "rotowire",
            })

    if not rows:
        return

    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "injury_log.csv"

    new_df = pd.DataFrame(rows)
    if log_path.exists():
        old_df = pd.read_csv(log_path, dtype=str)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined = combined.drop_duplicates(
        subset=["asof_date", "team_abbrev", "player_name"],
        keep="last",
    )
    combined.to_csv(log_path, index=False)


def write_injuries_json(injuries_today: Dict[str, List[Dict[str, str]]]) -> bool:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "injuries_today.json"
    tmp_path = data_dir / "injuries_today.json.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(injuries_today, f, indent=2)
    os.replace(tmp_path, out_path)
    return True


def injuries_count(injuries_today: Dict[str, List[Dict[str, str]]]) -> int:
    total = 0
    for items in injuries_today.values():
        if isinstance(items, list):
            total += len(items)
    return total


def load_existing(out_path: Path):
    if not out_path.exists():
        return None
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="Slate date YYYY-MM-DD (PT). Default: today PT")
    args = ap.parse_args()

    if args.date:
        asof_date = args.date
    else:
        asof_date = dt.datetime.now(ZoneInfo("America/Los_Angeles")).date().strftime("%Y-%m-%d")

    # ── Session setup + auth ─────────────────────────────────────────────
    session = requests.Session()
    authenticated = login_rotowire(session)

    html = fetch_rotowire_html(session)
    if not html:
        return 0

    injuries_today = parse_rotowire_injuries(html)
    entry_count = injuries_count(injuries_today)

    built_at_utc = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    payload = {
        "asof_date": asof_date,
        "built_at_utc": built_at_utc,
        "source": "rotowire",
        **injuries_today,
    }

    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "injuries_today.json"
    existing = load_existing(out_path)
    existing_asof = existing.get("asof_date") if isinstance(existing, dict) else None
    existing_count = injuries_count(existing) if isinstance(existing, dict) else 0

    guard = False
    if entry_count == 0 and existing_count > 0 and existing_asof == asof_date:
        guard = True
        print(f"[injuries] Guard: computed empty injuries; keeping existing injuries_today.json for asof_date={asof_date}")
    else:
        write_injuries_json(payload)
        if entry_count:
            append_injury_log(injuries_today, asof_date)
        print(f"[injuries] wrote injuries_today.json teams={len(injuries_today)} entries={entry_count}")

    print(f"[injuries] asof_date={asof_date} entries={entry_count} guard={guard}")

    # ── Lineup parsing ────────────────────────────────────────────────
    lineups = parse_rotowire_lineups(html)
    lineup_teams = len(lineups)
    lineup_starters = sum(len(d["starters"]) for d in lineups.values())

    lineups_path = Path("data") / "lineups_today.json"
    existing_lineups = load_existing(lineups_path)
    existing_lineups_asof = existing_lineups.get("asof_date") if isinstance(existing_lineups, dict) else None
    existing_lineups_teams = sum(
        1 for k, v in (existing_lineups or {}).items()
        if isinstance(v, dict) and v.get("starters")
    )

    # ── New panels (subscription-gated) ──────────────────────────────────
    projected_minutes: dict = {}
    onoff_usage: dict = {}
    if authenticated:
        minutes_html = fetch_rotowire_minutes_html(session)
        if minutes_html:
            soup_minutes = BeautifulSoup(minutes_html, "lxml")
            projected_minutes = parse_projected_minutes(soup_minutes)
            onoff_usage = parse_onoff_usage(soup_minutes)
        else:
            print("[injuries] projected-minutes page unavailable — skipping premium panels")
    else:
        print("[injuries] Skipping projected_minutes + onoff_usage — not authenticated")

    # ── Write lineups_today.json ──────────────────────────────────────────
    if lineup_teams == 0 and existing_lineups_teams > 0 and existing_lineups_asof == asof_date:
        print(f"[lineups] Guard: parsed 0 teams; keeping existing lineups_today.json for asof_date={asof_date}")
    else:
        write_lineups_json(lineups, asof_date, built_at_utc, projected_minutes, onoff_usage)
        print(f"[lineups] wrote lineups_today.json teams={lineup_teams} starters={lineup_starters}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
