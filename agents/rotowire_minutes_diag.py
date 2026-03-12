#!/usr/bin/env python3
"""
Diagnostic: probe Rotowire projected minutes data sources.
Logs structural info to help determine best parse approach.
Run once manually; does not modify any production files.
"""

import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROTOWIRE_LOGIN_URL = "https://www.rotowire.com/users/login.php"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

CANDIDATES = {
    "projections_today": "https://www.rotowire.com/basketball/projections.php?type=today",
    "projected_minutes": "https://www.rotowire.com/basketball/projected-minutes.php",
}

# Structural signals to probe for — presence/count of each
PROBE_STRINGS = [
    # Table signals
    "projected-minutes", "proj-minutes", "projections",
    "<table", "<tbody", "<thead", "<tr", "<td",
    # Known class fragments from existing scraper
    "lineups-viz", "minutes-meter", "lineups-viz__player-name",
    # Player/team signals
    "data-team", "data-athlete-id",
    # MIN column signals
    ">MIN<", ">Min<", ">min<", "\"min\"", "'min'",
    # Auth signals (presence = not logged in)
    "login", "subscribe", "upgrade", "premium",
    # JS framework signals (presence = likely JS-rendered)
    "react", "vue", "angular", "__NEXT_DATA__", "window.__",
]


def login(session: requests.Session) -> bool:
    email    = os.environ.get("ROTOWIRE_EMAIL", "")
    password = os.environ.get("ROTOWIRE_PASSWORD", "")
    if not email or not password:
        print("[diag] ERROR: ROTOWIRE_EMAIL / ROTOWIRE_PASSWORD not set")
        return False
    resp = session.post(
        ROTOWIRE_LOGIN_URL,
        data={"username": email, "password": password},
        headers={"User-Agent": USER_AGENT},
        timeout=12,
        allow_redirects=True,
    )
    ok = resp.status_code == 200
    print(f"[diag] login: HTTP {resp.status_code} → {'OK' if ok else 'FAIL'}")
    return ok


def probe_page(label: str, url: str, session: requests.Session) -> dict:
    print(f"\n[diag] === {label} ===")
    print(f"[diag] URL: {url}")

    try:
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception as e:
        print(f"[diag] fetch error: {e}")
        return {"url": url, "error": str(e)}

    print(f"[diag] HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        return {"url": url, "http_status": resp.status_code}

    html = resp.text
    html_len = len(html)
    print(f"[diag] HTML length: {html_len:,} chars")

    # Probe string presence/counts
    probes = {}
    for s in PROBE_STRINGS:
        count = html.lower().count(s.lower())
        if count:
            probes[s] = count
            print(f"[diag]   '{s}': {count}")

    # First 800 chars of <body> (skip <head>)
    body_start = ""
    body_match = re.search(r"<body[^>]*>(.*)", html, re.DOTALL | re.IGNORECASE)
    if body_match:
        body_start = body_match.group(1)[:800].strip()
    else:
        body_start = html[:800].strip()
    print(f"[diag] body start (800 chars):\n{body_start}\n")

    # BeautifulSoup structural summary
    soup = BeautifulSoup(html, "lxml")

    # Tables
    tables = soup.find_all("table")
    print(f"[diag] <table> count: {len(tables)}")
    for i, tbl in enumerate(tables[:3]):
        cls = tbl.get("class", [])
        tid = tbl.get("id", "")
        headers = [th.get_text(strip=True) for th in tbl.find_all("th")][:15]
        rows = tbl.find_all("tr")
        print(f"[diag]   table[{i}] id={tid!r} class={cls} headers={headers} rows={len(rows)}")
        # Sample first data row
        data_rows = tbl.find_all("tr")[1:3]
        for row in data_rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td","th"])][:10]
            print(f"[diag]     sample row: {cells}")

    # data-team attributes
    data_team_els = soup.find_all(attrs={"data-team": True})
    teams_found = sorted({el.get("data-team","").upper() for el in data_team_els if el.get("data-team")})
    print(f"[diag] data-team values ({len(teams_found)}): {teams_found}")

    # Player links
    player_links = soup.find_all("a", href=re.compile(r"/basketball/player"))
    player_names = [a.get_text(strip=True) for a in player_links[:10] if a.get_text(strip=True)]
    print(f"[diag] player link count: {len(player_links)}")
    print(f"[diag] sample player names: {player_names}")

    # Any element with "MIN" header
    min_headers = [
        el.get_text(strip=True)
        for el in soup.find_all(["th", "td"])
        if el.get_text(strip=True).upper() in ("MIN", "MINUTES", "PROJ MIN", "PROJ. MIN")
    ]
    print(f"[diag] MIN header elements: {min_headers[:10]}")

    return {
        "url": url,
        "http_status": resp.status_code,
        "html_length": html_len,
        "probe_hits": probes,
        "table_count": len(tables),
        "data_team_values": teams_found,
        "player_link_count": len(player_links),
        "sample_player_names": player_names,
        "min_headers_found": min_headers[:10],
        "body_start_800": body_start,
    }


def main():
    session = requests.Session()
    authenticated = login(session)
    if not authenticated:
        print("[diag] WARNING: proceeding unauthenticated — premium content may be gated")

    results = {"authenticated": authenticated, "pages": {}}
    for label, url in CANDIDATES.items():
        results["pages"][label] = probe_page(label, url, session)

    out_path = Path("data") / "minutes_diag.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[diag] wrote {out_path}")
    print("[diag] done")


if __name__ == "__main__":
    main()
