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

PICKS_JSON     = DATA / "picks.json"
AUDIT_LOG_JSON = DATA / "audit_log.json"
MASTER_CSV     = DATA / "nba_master.csv"
INJURIES_JSON  = DATA / "injuries_today.json"

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
TODAY_STR = dt.datetime.now(ET).strftime("%Y-%m-%d")


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
    Returns {team_abbrev: "7:30 PM ET"} for today's games from nba_master.csv.
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


def load_injuries_display() -> dict:
    """
    Load injuries_today.json and return a display-ready dict:
      {
        "fetched_at": "3:05 PM PT",
        "teams": {
          "LAL": [{"name": "LeBron James", "status": "QUESTIONABLE", "reason": "Ankle"},...]
        }
      }
    Non-list keys (metadata) are extracted; list keys are team rosters.
    """
    raw = load_json(INJURIES_JSON, {})
    if not raw:
        return {"fetched_at": None, "teams": {}}

    # Extract timestamp — try common key names
    fetched_at = None
    for key in ("fetched_at", "as_of", "timestamp", "updated_at", "scraped_at"):
        if key in raw and isinstance(raw[key], str):
            fetched_at = raw[key]
            break

    # Format timestamp to PT if it looks like an ISO string
    if fetched_at:
        try:
            ts = dt.datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            fetched_at = ts.astimezone(PT).strftime("%-I:%M %p PT, %b %-d")
        except Exception:
            pass  # keep raw string if parsing fails

    teams = {k: v for k, v in raw.items() if isinstance(v, list)}
    return {"fetched_at": fetched_at, "teams": teams}


def build_site():
    picks     = load_json(PICKS_JSON, [])
    audit_log = load_json(AUDIT_LOG_JSON, [])
    game_times = load_game_times()
    injuries_display = load_injuries_display()

    today_picks = [p for p in picks if p.get("date") == TODAY_STR]
    past_picks  = [p for p in picks if p.get("date") != TODAY_STR
                   and p.get("result") in ("HIT", "MISS")]

    # Attach game time to today's picks
    for p in today_picks:
        p["game_time"] = game_times.get(str(p.get("team", "")).upper(), "")

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
        "built_at": dt.datetime.now(ET).strftime("%B %d, %Y at %-I:%M %p ET"),
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
    injuries_json   = json.dumps(d.get("injuries", {"fetched_at": None, "teams": {}}))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>NBAgent</title>
  <style>
    :root {{
      --bg: #0d0d0f; --surface: #18181c; --surface2: #202026;
      --border: #2a2a32; --accent: #6c63ff; --accent2: #00d4aa;
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
    .logo {{ font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }}
    .logo span {{ color: var(--accent); }}
    .built-at {{ font-size: 11px; color: var(--muted); }}

    .tabs {{ display: flex; gap: 4px; padding: 12px 20px 0;
             border-bottom: 1px solid var(--border); background: var(--surface);
             position: sticky; top: 53px; z-index: 9; }}
    .tab {{ padding: 8px 16px; border-radius: 6px 6px 0 0; cursor: pointer;
            font-size: 13px; font-weight: 500; color: var(--muted); border: none;
            background: none; border-bottom: 2px solid transparent; transition: all 0.15s; }}
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
                  display: grid; grid-template-columns: auto 1fr auto;
                  gap: 12px; align-items: start; transition: border-color 0.15s; }}
    .pick-card:hover {{ border-color: var(--accent); }}
    .prop-badge {{ width: 44px; height: 44px; border-radius: 10px;
                   display: flex; align-items: center; justify-content: center;
                   font-size: 11px; font-weight: 700; flex-shrink: 0; }}
    .prop-PTS {{ background: rgba(249,115,22,0.15); color: var(--pts); }}
    .prop-REB {{ background: rgba(59,130,246,0.15); color: var(--reb); }}
    .prop-AST {{ background: rgba(168,85,247,0.15); color: var(--ast); }}
    .prop-3PM {{ background: rgba(234,179,8,0.15);  color: var(--3pm); }}
    .pick-main .player  {{ font-size: 16px; font-weight: 600; }}
    .pick-main .matchup {{ font-size: 12px; color: var(--muted); margin-top: 3px;
                           display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .game-time {{ font-size: 11px; background: var(--surface2); border: 1px solid var(--border);
                  border-radius: 4px; padding: 1px 6px; color: var(--accent2); white-space: nowrap; }}
    .pick-main .reasoning {{ font-size: 12px; color: var(--muted); margin-top: 7px; line-height: 1.55; }}
    .pick-right {{ text-align: right; flex-shrink: 0; }}
    .pick-line {{ font-size: 22px; font-weight: 700; color: var(--accent2); }}
    .pick-line .direction {{ font-size: 10px; color: var(--muted); font-weight: 400;
                              display: block; margin-bottom: 1px; }}
    .confidence {{ margin-top: 5px; font-size: 11px; color: var(--muted); }}
    .conf-bar {{ height: 3px; background: var(--border); border-radius: 99px;
                 overflow: hidden; margin-top: 4px; width: 64px; margin-left: auto; }}
    .conf-fill {{ height: 100%; border-radius: 99px; background: var(--accent2); }}

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
                    box-shadow: 0 4px 12px rgba(108,99,255,0.4); }}
    #back-to-top.visible {{ opacity: 1; pointer-events: auto; transform: translateY(0); }}
    #back-to-top:hover {{ background: #7c74ff; }}

    /* Streak pill */
    .streak-pill {{ display: inline-flex; align-items: center; gap: 4px;
                    font-size: 10px; font-weight: 600; padding: 2px 7px;
                    border-radius: 99px; margin-top: 5px; }}
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
    .overall-banner {{ background: linear-gradient(135deg,rgba(108,99,255,0.12),rgba(0,212,170,0.12));
                       border: 1px solid var(--border); border-radius: 12px;
                       padding: 18px 20px; display: flex; align-items: flex-start;
                       justify-content: space-between; margin-bottom: 20px;
                       flex-wrap: wrap; gap: 16px; }}
    .overall-banner .big {{ font-size: 38px; font-weight: 800; color: var(--accent2); line-height: 1; }}
    .overall-banner .sub {{ font-size: 12px; color: var(--muted); margin-top: 3px; }}

    /* Trend chart */
    .chart-wrap {{ background: var(--surface); border: 1px solid var(--border);
                   border-radius: 12px; padding: 16px; margin-bottom: 20px; }}
    .chart-title {{ font-size: 11px; color: var(--muted); margin-bottom: 12px;
                    font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
    #trend-chart {{ width: 100%; height: 120px; display: block; }}

    /* History table */
    .history-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
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
  </style>
</head>
<body>

<header>
  <div class="logo">NB<span>Agent</span></div>
  <div class="built-at">Updated {d["built_at"]}</div>
</header>

<div class="tabs">
  <button class="tab active" onclick="showTab('picks')">Today's Picks</button>
  <button class="tab" onclick="showTab('results')">Results</button>
  <button class="tab" onclick="showTab('audit')">Audit Log</button>
</div>

<button id="back-to-top" onclick="window.scrollTo({{top:0,behavior:'smooth'}})" aria-label="Back to top">↑</button>

<div id="tab-picks" class="page active">
  <div id="injury-container"></div>
  <div id="picks-container"></div>
</div>
<div id="tab-results" class="page">
  <div class="overall-banner">
    <div>
      <div class="big" id="overall-pct">—</div>
      <div class="sub" id="overall-sub">overall hit rate</div>
    </div>
    <div id="prop-streak-grid" class="prop-streak-grid" style="flex:1;max-width:440px"></div>
  </div>
  <div class="chart-wrap">
    <div class="chart-title">Daily hit rate — last 30 days</div>
    <canvas id="trend-chart"></canvas>
    <div id="chart-empty" style="display:none;text-align:center;padding:20px;color:var(--muted);font-size:13px">
      Not enough data yet — check back after a few days of picks.
    </div>
  </div>
  <div class="section-header">Pick history</div>
  <div id="results-container"></div>
</div>
<div id="tab-audit" class="page"><div id="audit-container"></div></div>

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
}};

function showTab(name) {{
  document.querySelectorAll('.tab').forEach((t,i) =>
    t.classList.toggle('active', ['picks','results','audit'][i] === name));
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
function streakPill(s) {{
  if (!s || !s.streak_type) return '';
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
  if (!inj || !inj.teams || !Object.keys(inj.teams).length) {{
    c.innerHTML = '';
    return;
  }}

  // Group teams by game using today's picks to map team → opponent
  const teamToGame = {{}};
  const gameOrder  = [];
  DATA.today_picks.forEach(p => {{
    const home = p.home_away === 'H' ? p.team : p.opponent;
    const away = p.home_away === 'A' ? p.team : p.opponent;
    const key  = `${{away}}@${{home}}`;
    const gt   = p.game_time || '';
    [p.team, p.opponent].forEach(t => {{
      if (!teamToGame[t]) {{
        teamToGame[t] = {{key, home, away, game_time: gt}};
        if (!gameOrder.find(g => g.key === key))
          gameOrder.push({{key, home, away, game_time: gt}});
      }}
    }});
  }});

  // Teams in injuries but not in picks go into an "Other" bucket
  const coveredTeams = new Set(Object.keys(teamToGame));
  const otherTeams   = Object.keys(inj.teams).filter(t => !coveredTeams.has(t));

  // Build game buckets
  const gameBuckets = gameOrder.map(g => ({{
    ...g,
    teams: [g.away, g.home].filter(t => inj.teams[t]?.length)
  }})).filter(g => g.teams.length);

  if (otherTeams.filter(t => inj.teams[t]?.length).length) {{
    gameBuckets.push({{key:'other', home:'', away:'', game_time:'',
                       teams: otherTeams.filter(t => inj.teams[t]?.length)}});
  }}

  if (!gameBuckets.length) {{ c.innerHTML = ''; return; }}

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

  gameBuckets.forEach(g => {{
    const gameLabel = g.key === 'other' ? 'Other Teams'
      : `${{g.away}} @ ${{g.home}}${{g.game_time ? ' — ' + g.game_time : ''}}`;
    html += `<div class="injury-game"><div class="injury-game-header">${{gameLabel}}</div>`;

    g.teams.forEach(team => {{
      const players = inj.teams[team] || [];
      html += `<div class="injury-team-block"><div class="injury-team-name">${{team}}</div>`;
      players.forEach(p => {{
        const name   = p.player_name || p.name || p.player || '?';
        const status = p.status || p.designation || '?';
        const reason = p.reason || p.injury || p.description || '';
        const cls    = statusClass(status);
        html += `
          <div class="injury-player-row">
            <span class="injury-player-name">${{name}}</span>
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

// ── TODAY'S PICKS ──
function renderPicks() {{
  const c = document.getElementById('picks-container');
  const picks = DATA.today_picks;
  if (!picks.length) {{
    c.innerHTML = `<div class="empty"><div class="empty-icon">🏀</div>No picks yet for ${{DATA.today_str}}.<br>Check back after 11 AM ET.</div>`;
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
  let html = `<div class="section-header">${{picks.length}} pick${{picks.length!==1?'s':''}} — ${{DATA.today_str}}</div>`;

  games.forEach((g, gi) => {{
    const timeTag = g.game_time ? `<span class="game-tip">⏰ ${{g.game_time}}</span>` : '';
    const gid = `game-${{gi}}`;
    html += `
      <div class="game-group">
        <div class="game-group-header open" id="hdr-${{gid}}" onclick="toggleGame('${{gid}}')">
          <span class="game-matchup">${{g.away}} @ ${{g.home}}</span>
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
      const pt  = p.prop_type;
      const ha  = p.home_away === 'H' ? 'vs' : '@';
      const pill = streakPill(ps[pt]);
      html += `
        <div class="pick-card">
          <div class="prop-badge ${{propColor(pt)}}">${{pt}}</div>
          <div class="pick-main">
            <div class="player">${{p.player_name}}</div>
            <div class="matchup"><span>${{p.team}} ${{ha}} ${{p.opponent}}</span></div>
            <div class="reasoning">${{p.reasoning}}</div>
            ${{pill ? `<div style="margin-top:5px">${{pill}}</div>` : ''}}
          </div>
          <div class="pick-right">
            <div class="pick-line"><span class="direction">OVER</span>${{p.pick_value}}</div>
            <div class="confidence">${{p.confidence_pct}}%
              <div class="conf-bar"><div class="conf-fill" style="width:${{p.confidence_pct}}%"></div></div>
            </div>
          </div>
        </div>`;
    }});

    html += `</div></div></div>`;
  }});

  c.innerHTML = html;
}}

// ── RESULTS ──
function renderResults() {{
  document.getElementById('overall-pct').textContent =
    DATA.total_graded ? DATA.overall_hit_rate+'%' : '—';
  document.getElementById('overall-sub').textContent =
    DATA.total_graded ? `${{DATA.total_graded}} picks graded` : 'no graded picks yet';

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

  const c = document.getElementById('results-container');
  const results = DATA.recent_results;
  if (!results.length) {{
    c.innerHTML = `<div class="empty"><div class="empty-icon">📊</div>No graded results yet.</div>`;
    return;
  }}
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
    html += `<tr>
      <td style="white-space:nowrap">${{p.date}}</td>
      <td><strong>${{p.player_name}}</strong><br><span style="font-size:11px;color:var(--muted)">${{p.team}}</span></td>
      <td><span class="prop-badge ${{propColor(p.prop_type)}}" style="${{bs}}">${{p.prop_type}}</span></td>
      <td style="white-space:nowrap">OVER ${{p.pick_value}}</td>
      <td>${{p.actual_value??'—'}}</td>
      <td>${{res}}</td>
    </tr>`;
  }});
  html += '</tbody></table>';
  c.innerHTML = html;
}}

// ── TREND CHART (vanilla canvas, no deps) ──
let chartDrawn = false;
function drawTrendChart() {{
  if (chartDrawn) return;
  chartDrawn = true;
  const trend  = DATA.daily_trend;
  const canvas = document.getElementById('trend-chart');
  const empty  = document.getElementById('chart-empty');
  if (!trend || trend.length < 2) {{
    canvas.style.display = 'none';
    empty.style.display  = 'block';
    return;
  }}
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.parentElement.clientWidth - 32;
  const H = 120;
  canvas.width  = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W+'px'; canvas.style.height = H+'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const pad = {{t:10, r:10, b:28, l:36}};
  const cw = W-pad.l-pad.r, ch = H-pad.t-pad.b;

  // Grid + y-axis labels
  [50,70,100].forEach(pct => {{
    const y = pad.t + ch - (pct/100)*ch;
    ctx.strokeStyle='#2a2a32'; ctx.lineWidth=1;
    ctx.beginPath(); ctx.moveTo(pad.l,y); ctx.lineTo(pad.l+cw,y); ctx.stroke();
    ctx.fillStyle='#888898'; ctx.font='9px system-ui'; ctx.textAlign='right';
    ctx.fillText(pct+'%', pad.l-4, y+3);
  }});

  // 70% target dashed line
  const ty = pad.t + ch - 0.7*ch;
  ctx.strokeStyle='rgba(108,99,255,0.45)'; ctx.setLineDash([3,4]); ctx.lineWidth=1;
  ctx.beginPath(); ctx.moveTo(pad.l,ty); ctx.lineTo(pad.l+cw,ty); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle='rgba(108,99,255,0.6)'; ctx.font='9px system-ui'; ctx.textAlign='left';
  ctx.fillText('target 70%', pad.l+4, ty-3);

  // Data points
  const pts = trend.map((d,i) => ({{
    x: pad.l + (trend.length>1 ? i/(trend.length-1) : 0.5)*cw,
    y: pad.t + ch - (d.pct/100)*ch,
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

  // Dots (green above target, red below)
  pts.forEach(p => {{
    ctx.beginPath(); ctx.arc(p.x,p.y,3,0,Math.PI*2);
    ctx.fillStyle = p.pct>=70 ? '#00d4aa' : '#ef4444';
    ctx.fill();
  }});

  // X-axis labels
  ctx.fillStyle='#888898'; ctx.font='9px system-ui'; ctx.textAlign='center';
  [0, Math.floor((trend.length-1)/2), trend.length-1].forEach(i => {{
    ctx.fillText(trend[i].date.slice(5), pts[i].x, H-6);
  }});
}}

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
      <div style="display:flex;gap:24px;flex-wrap:wrap">
        <div><div style="font-size:11px;color:var(--muted)">Hit Rate</div><div style="font-size:24px;font-weight:700;color:var(--accent2)">${{a.hit_rate_pct}}%</div></div>
        <div><div style="font-size:11px;color:var(--muted)">Total</div><div style="font-size:24px;font-weight:700">${{a.total_picks}}</div></div>
        <div><div style="font-size:11px;color:var(--muted)">Hits</div><div style="font-size:24px;font-weight:700;color:var(--hit)">${{a.hits}}</div></div>
        <div><div style="font-size:11px;color:var(--muted)">Misses</div><div style="font-size:24px;font-weight:700;color:var(--miss)">${{a.misses}}</div></div>
      </div>
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

renderInjuries();
renderPicks();
renderResults();
renderAudit();
</script>
</body>
</html>"""


if __name__ == "__main__":
    build_site()
