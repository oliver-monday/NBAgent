#!/usr/bin/env python3
"""
Diagnostic: determine why Rotowire projected-minutes returns partial coverage.

Investigates four candidate root causes (in order):
  1. Login form field-name mismatch (username vs email).
  2. CSRF token / hidden fields required on POST.
  3. Session-cookie deficiency — premium flag not granted.
  4. JavaScript rendering of premium team blocks.

Runs two full login attempts — once with data={"username": ..., "password": ...}
and once with data={"email": ..., "password": ...}. For each attempt, fetches
the projected-minutes page and prints a structural summary (team count, player
count, premium/subscribe markers, JS-framework markers). The attempt that
returns the most teams is the one that should be used in production.

Writes full results to data/minutes_diag.json. Safe to run manually; no
production files are modified.
"""

import json
import os
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROTOWIRE_BASE      = "https://www.rotowire.com"
ROTOWIRE_LOGIN_URL = f"{ROTOWIRE_BASE}/users/login.php"
PROJECTED_MIN_URL  = f"{ROTOWIRE_BASE}/basketball/projected-minutes.php"
LINEUPS_URL        = f"{ROTOWIRE_BASE}/basketball/nba-lineups.php"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

NBA_ABBREVS = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

PREMIUM_MARKERS = [
    "subscribe", "upgrade to premium", "become a premium",
    "login to view", "premium feature", "subscriber exclusive",
]
JS_MARKERS = [
    "react", "vue.", "angular", "__NEXT_DATA__", "window.__INITIAL",
    "__NUXT__", "react-dom",
]


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — inspect the login form
# ─────────────────────────────────────────────────────────────────────────────
def inspect_login_form() -> dict:
    """Fetch the login page and introspect any form fields present."""
    print("\n[diag] ─── Phase 1: login form inspection ─────────────────────")
    print(f"[diag] GET {ROTOWIRE_LOGIN_URL}")
    try:
        resp = requests.get(ROTOWIRE_LOGIN_URL,
                            headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception as exc:
        print(f"[diag] fetch error: {exc}")
        return {"error": str(exc)}
    print(f"[diag] HTTP {resp.status_code}, len={len(resp.text)}")
    html = resp.text
    soup = BeautifulSoup(html, "lxml")

    forms = soup.find_all("form")
    form_summary = []
    for i, f in enumerate(forms):
        inputs = f.find_all("input")
        if not any(inp.get("type") == "password" for inp in inputs):
            continue  # not a login form
        fields = [
            {"name": inp.get("name"), "type": inp.get("type"),
             "value": (inp.get("value") or "")[:40]}
            for inp in inputs
        ]
        form_summary.append({
            "index":  i,
            "action": f.get("action"),
            "method": f.get("method"),
            "fields": fields,
        })
        print(f"[diag] form[{i}] action={f.get('action')!r} method={f.get('method')!r}")
        for fld in fields:
            print(f"[diag]   field name={fld['name']!r:16s} "
                  f"type={fld['type']!r:10s} value={fld['value']!r}")

    if not form_summary:
        # Rotowire's login is JS-rendered; there is no <form> in server HTML.
        # Grep for hints about expected field names anyway.
        print("[diag] no <form> with password field in server HTML "
              "(login UI is likely JS-rendered)")
        hints = {}
        for pat in [r'name="username"', r'name="email"', r'name="csrf"',
                    r'csrf[_-]?token', r'_token']:
            matches = re.findall(pat, html, re.IGNORECASE)
            if matches:
                hints[pat] = len(matches)
        print(f"[diag] field-name hints in raw HTML: {hints}")
        return {"forms": [], "hints": hints}
    return {"forms": form_summary}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — probe a projected-minutes page response
# ─────────────────────────────────────────────────────────────────────────────
def summarize_page(html: str) -> dict:
    """Structural summary of a fetched projected-minutes page."""
    soup = BeautifulSoup(html, "lxml")

    # team logos with known abbrevs
    logo_re = re.compile(r"/100([A-Z]+)\.png", re.IGNORECASE)
    logo_teams = sorted({
        m.group(1).upper()
        for img in soup.find_all("img", src=logo_re)
        for m in [logo_re.search(img.get("src", ""))]
        if m and m.group(1).upper() in NBA_ABBREVS
    })

    # data-team attributes
    data_team_els = soup.find_all(attrs={"data-team": True})
    data_teams = sorted({
        el.get("data-team", "").upper()
        for el in data_team_els
        if el.get("data-team", "").upper() in NBA_ABBREVS
    })

    # player links
    player_links = soup.find_all("a", href=re.compile(r"/basketball/player"))
    player_names = [a.get_text(strip=True) for a in player_links if a.get_text(strip=True)]

    # premium / JS markers
    html_lower = html.lower()
    premium_hits = {m: html_lower.count(m) for m in PREMIUM_MARKERS if m in html_lower}
    js_hits      = {m: html_lower.count(m.lower()) for m in JS_MARKERS if m.lower() in html_lower}

    # count distinct teams via "Projected Minutes" section headers
    pm_panel_count = len(re.findall(r"Projected\s+Minutes", html))

    # sample 500 chars around first team logo and last player link
    sample_logo_ctx = ""
    logo_match = logo_re.search(html)
    if logo_match:
        start = max(0, logo_match.start() - 100)
        end = min(len(html), logo_match.end() + 400)
        sample_logo_ctx = html[start:end]
    sample_player_ctx = ""
    if player_links:
        last_name = player_names[-1] if player_names else ""
        if last_name:
            idx = html.rfind(last_name)
            if idx > 0:
                start = max(0, idx - 100)
                end = min(len(html), idx + 400)
                sample_player_ctx = html[start:end]

    return {
        "html_length":      len(html),
        "logo_teams":       logo_teams,
        "logo_team_count":  len(logo_teams),
        "data_team_values": data_teams,
        "player_link_count": len(player_links),
        "sample_player_names": player_names[:12],
        "premium_hits":     premium_hits,
        "js_hits":          js_hits,
        "pm_panel_count":   pm_panel_count,
        "sample_logo_context":   sample_logo_ctx,
        "sample_player_context": sample_player_ctx,
    }


def try_login_and_probe(field_name: str, email: str, password: str) -> dict:
    """Fresh session, login with the given field name, fetch projected-minutes."""
    print(f"\n[diag] ─── Phase 2: login attempt (field={field_name!r}) ──────")
    session = requests.Session()
    try:
        resp = session.post(
            ROTOWIRE_LOGIN_URL,
            data={field_name: email, "password": password},
            headers={"User-Agent": USER_AGENT},
            timeout=12,
            allow_redirects=True,
        )
    except Exception as exc:
        print(f"[diag] login error: {exc}")
        return {"field_name": field_name, "error": str(exc)}

    cookies = sorted(c.name for c in session.cookies)
    print(f"[diag] login HTTP {resp.status_code}, "
          f"cookies={len(session.cookies)}: {cookies}")

    try:
        page = session.get(PROJECTED_MIN_URL,
                           headers={"User-Agent": USER_AGENT}, timeout=15)
    except Exception as exc:
        print(f"[diag] projected-minutes fetch error: {exc}")
        return {"field_name": field_name, "login_status": resp.status_code,
                "cookies": cookies, "error": str(exc)}
    print(f"[diag] projected-minutes HTTP {page.status_code}, "
          f"len={len(page.text)}")
    if page.status_code != 200:
        return {"field_name": field_name, "login_status": resp.status_code,
                "cookies": cookies, "page_status": page.status_code}

    summary = summarize_page(page.text)
    print(f"[diag] logo-anchored teams ({summary['logo_team_count']}): "
          f"{summary['logo_teams']}")
    print(f"[diag] data-team values: {summary['data_team_values']}")
    print(f"[diag] player links: {summary['player_link_count']}, "
          f"sample: {summary['sample_player_names']}")
    print(f"[diag] Projected Minutes panel count: {summary['pm_panel_count']}")
    if summary["premium_hits"]:
        print(f"[diag] PREMIUM markers detected (suggests partial gating): "
              f"{summary['premium_hits']}")
    if summary["js_hits"]:
        print(f"[diag] JS framework markers: {summary['js_hits']}")

    return {
        "field_name":   field_name,
        "login_status": resp.status_code,
        "cookies":      cookies,
        "cookie_count": len(cookies),
        "page_status":  page.status_code,
        **summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — compare results across attempts
# ─────────────────────────────────────────────────────────────────────────────
def compare_attempts(attempts: list[dict]) -> dict:
    print("\n[diag] ─── Phase 3: comparison ──────────────────────────────────")
    rows = []
    for a in attempts:
        rows.append({
            "field":   a.get("field_name"),
            "status":  a.get("login_status"),
            "cookies": a.get("cookie_count"),
            "teams":   a.get("logo_team_count"),
            "players": a.get("player_link_count"),
            "panels":  a.get("pm_panel_count"),
            "premium": bool(a.get("premium_hits")),
        })
    # header
    print(f"[diag] {'field':10s} {'status':6s} {'cookies':8s} {'teams':6s} "
          f"{'players':8s} {'panels':7s} premium")
    for r in rows:
        print(f"[diag] {str(r['field'] or '-'):10s} {str(r['status']):6s} "
              f"{str(r['cookies']):8s} {str(r['teams']):6s} "
              f"{str(r['players']):8s} {str(r['panels']):7s} {r['premium']}")
    best = max(attempts, key=lambda a: a.get("logo_team_count", 0) or 0,
               default=None)
    verdict = ""
    if best and best.get("logo_team_count", 0) > 0:
        verdict = (f"field={best['field_name']!r} yields most teams "
                   f"({best['logo_team_count']}) — use this in login_rotowire")
    else:
        verdict = ("no attempt yielded teams — premium content may be "
                   "JS-rendered; consider lineups-page fallback or headless browser")
    print(f"[diag] VERDICT: {verdict}")
    return {"rows": rows, "verdict": verdict}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    email    = os.environ.get("ROTOWIRE_EMAIL", "")
    password = os.environ.get("ROTOWIRE_PASSWORD", "")
    if not email or not password:
        print("[diag] ERROR: ROTOWIRE_EMAIL / ROTOWIRE_PASSWORD not set")
        return 1

    results = {
        "login_form": inspect_login_form(),
        "attempts":   [],
    }

    # Try both candidate field names, fresh session each time.
    for field_name in ("email", "username"):
        results["attempts"].append(
            try_login_and_probe(field_name, email, password)
        )

    results["comparison"] = compare_attempts(results["attempts"])

    out_path = Path("data") / "minutes_diag.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[diag] wrote {out_path}")
    print("[diag] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
