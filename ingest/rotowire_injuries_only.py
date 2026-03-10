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


def fetch_rotowire_html() -> str | None:
    try:
        resp = requests.get(
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
    The Expected Lineup section (PG→SG→SF→PF→C) appears before the MAY NOT PLAY
    section within each team block. Position labels and player <a> tags are the
    reliable structural anchors.

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
        soup = BeautifulSoup(html, "lxml")

        # Walk every <li> on the page. Position-labeled starter rows have:
        #   - A descendant element whose stripped text is exactly a position abbrev
        #   - An <a> tag with the player name
        # Both conditions together are highly specific to the lineup table rows.
        for li in soup.find_all("li"):
            # Find a descendant with exactly a position label
            pos_text = None
            for desc in li.descendants:
                if not hasattr(desc, "get_text"):
                    continue
                t = desc.get_text(strip=True).upper()
                if t in POSITIONS:
                    pos_text = t
                    break
            if not pos_text:
                continue

            # Must have a player <a> link in the same <li>
            a_tag = li.find("a")
            if not a_tag:
                continue
            name = a_tag.get_text(strip=True)
            if not name or len(name) < 3:
                continue

            # Check for an inline injury status on this starter
            inj_status = None
            for tag in li.find_all(True):
                cls = " ".join(tag.get("class", []))
                if "inj" in cls.lower() or "status" in cls.lower():
                    raw = tag.get_text(strip=True)
                    # Avoid picking up broad class names as status text
                    if raw and len(raw) <= 20 and raw.upper() not in {"STATUS", "INJURY"}:
                        inj_status = _short_status(raw)
                        break

            # Walk up ancestors to find team abbreviation
            team = ""
            confirmed = False
            for ancestor in list(li.parents):
                # data-team attribute takes precedence (used by buttons/containers)
                dt = ancestor.get("data-team", "").upper()
                if dt and dt in NBA_ABBREVS:
                    team = dt
                    break
                # Look for a direct child element whose sole text is a team abbrev
                # (e.g. <div class="lineup__abbrev">PHI</div>)
                for child in ancestor.find_all(True, recursive=False):
                    t = child.get_text(strip=True).upper()
                    if t in NBA_ABBREVS:
                        team = t
                        break
                if team:
                    # Check for "Confirmed" text within this same ancestor section
                    section_text = ancestor.get_text(" ", strip=True)
                    if re.search(r"\bconfirm", section_text, re.IGNORECASE):
                        confirmed = True
                    break

            if not team:
                continue

            # Build or update the team entry
            if team not in lineups:
                lineups[team] = {"starters": [], "confirmed": False}
            if confirmed:
                lineups[team]["confirmed"] = True

            # Deduplicate by position — keep first occurrence
            existing_positions = {s["position"] for s in lineups[team]["starters"]}
            if pos_text not in existing_positions:
                lineups[team]["starters"].append({
                    "position": pos_text,
                    "name": name,
                    "injury_status": inj_status,
                })

    except Exception as e:
        print(f"[lineups] ERROR parsing lineups: {e}")

    # Drop teams with zero starters (shouldn't happen but guard it)
    return {t: d for t, d in lineups.items() if d["starters"]}


def write_lineups_json(lineups: dict, asof_date: str, built_at_utc: str) -> None:
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    out_path = data_dir / "lineups_today.json"
    tmp_path = data_dir / "lineups_today.json.tmp"

    payload = {
        "asof_date": asof_date,
        "built_at_utc": built_at_utc,
        "source": "rotowire",
        **lineups,
    }
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

    html = fetch_rotowire_html()
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

    if lineup_teams == 0 and existing_lineups_teams > 0 and existing_lineups_asof == asof_date:
        print(f"[lineups] Guard: parsed 0 teams; keeping existing lineups_today.json for asof_date={asof_date}")
    else:
        write_lineups_json(lineups, asof_date, built_at_utc)
        print(f"[lineups] wrote lineups_today.json teams={lineup_teams} starters={lineup_starters}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
