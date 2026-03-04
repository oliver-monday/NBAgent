#!/usr/bin/env python3
"""
NBAgent — Site Builder

Reads data/picks.json and data/audit_log.json,
writes site/index.html for GitHub Pages deployment.
"""

from __future__ import annotations

import json
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"

PICKS_JSON     = DATA / "picks.json"
AUDIT_LOG_JSON = DATA / "audit_log.json"

ET = ZoneInfo("America/New_York")
TODAY_STR = dt.datetime.now(ET).strftime("%Y-%m-%d")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def build_site():
    picks = load_json(PICKS_JSON, [])
    audit_log = load_json(AUDIT_LOG_JSON, [])

    today_picks = [p for p in picks if p.get("date") == TODAY_STR]
    past_picks  = [p for p in picks if p.get("date") != TODAY_STR and p.get("result") in ("HIT", "MISS")]

    # Overall hit rate
    total_hits   = sum(1 for p in past_picks if p["result"] == "HIT")
    total_graded = len(past_picks)
    overall_pct  = round(100 * total_hits / total_graded, 1) if total_graded else 0

    # Hit rate by prop type
    prop_types = ["PTS", "REB", "AST", "3PM"]
    prop_stats = {}
    for pt in prop_types:
        subset = [p for p in past_picks if p.get("prop_type") == pt]
        h = sum(1 for p in subset if p["result"] == "HIT")
        prop_stats[pt] = {"hits": h, "total": len(subset), "pct": round(100*h/len(subset), 1) if subset else 0}

    # Last audit entry
    last_audit = audit_log[-1] if audit_log else None

    # Inject data as JSON into page
    page_data = {
        "today_str": TODAY_STR,
        "today_picks": today_picks,
        "overall_hit_rate": overall_pct,
        "total_graded": total_graded,
        "prop_stats": prop_stats,
        "last_audit": last_audit,
        "recent_results": sorted(past_picks, key=lambda p: p.get("date",""), reverse=True)[:30],
        "built_at": dt.datetime.now(ET).strftime("%B %d, %Y at %-I:%M %p ET"),
    }

    html = generate_html(page_data)

    SITE.mkdir(exist_ok=True)
    with open(SITE / "index.html", "w") as f:
        f.write(html)

    print(f"[build_site] Wrote site/index.html ({len(today_picks)} today's picks, {total_graded} graded historical)")


def generate_html(d: dict) -> str:
    picks_json = json.dumps(d["today_picks"])
    results_json = json.dumps(d["recent_results"])
    prop_stats_json = json.dumps(d["prop_stats"])
    last_audit_json = json.dumps(d["last_audit"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>NBAgent</title>
  <style>
    :root {{
      --bg: #0d0d0f;
      --surface: #18181c;
      --surface2: #202026;
      --border: #2a2a32;
      --accent: #6c63ff;
      --accent2: #00d4aa;
      --hit: #22c55e;
      --miss: #ef4444;
      --text: #e8e8f0;
      --muted: #888898;
      --pts: #f97316;
      --reb: #3b82f6;
      --ast: #a855f7;
      --3pm: #eab308;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 15px;
      min-height: 100vh;
    }}

    /* ── Header ── */
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 16px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 10;
    }}
    .logo {{ font-size: 20px; font-weight: 700; letter-spacing: -0.5px; }}
    .logo span {{ color: var(--accent); }}
    .built-at {{ font-size: 11px; color: var(--muted); }}

    /* ── Nav tabs ── */
    .tabs {{
      display: flex;
      gap: 4px;
      padding: 12px 20px 0;
      border-bottom: 1px solid var(--border);
      background: var(--surface);
    }}
    .tab {{
      padding: 8px 16px;
      border-radius: 6px 6px 0 0;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
      border: none;
      background: none;
      border-bottom: 2px solid transparent;
      transition: all 0.15s;
    }}
    .tab.active {{ color: var(--text); border-bottom-color: var(--accent); }}
    .tab:hover:not(.active) {{ color: var(--text); }}

    /* ── Page sections ── */
    .page {{ display: none; padding: 20px; max-width: 900px; margin: 0 auto; }}
    .page.active {{ display: block; }}

    /* ── Stats bar ── */
    .stats-bar {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 10px;
      margin-bottom: 20px;
    }}
    @media(min-width: 500px) {{ .stats-bar {{ grid-template-columns: repeat(4, 1fr); }} }}
    .stat-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      text-align: center;
    }}
    .stat-card .label {{ font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
    .stat-card .value {{ font-size: 24px; font-weight: 700; }}
    .stat-card.pts .value {{ color: var(--pts); }}
    .stat-card.reb .value {{ color: var(--reb); }}
    .stat-card.ast .value {{ color: var(--ast); }}
    .stat-card.tpm .value {{ color: var(--3pm); }}

    /* ── Section headers ── */
    .section-header {{
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 1px;
      color: var(--muted);
      margin-bottom: 12px;
      margin-top: 20px;
    }}
    .section-header:first-child {{ margin-top: 0; }}

    /* ── Pick cards ── */
    .picks-grid {{
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .pick-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px 16px;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 12px;
      align-items: start;
    }}
    .pick-card:hover {{ border-color: var(--accent); }}
    .prop-badge {{
      width: 44px;
      height: 44px;
      border-radius: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 700;
      flex-shrink: 0;
    }}
    .prop-PTS {{ background: rgba(249,115,22,0.15); color: var(--pts); }}
    .prop-REB {{ background: rgba(59,130,246,0.15); color: var(--reb); }}
    .prop-AST {{ background: rgba(168,85,247,0.15); color: var(--ast); }}
    .prop-3PM {{ background: rgba(234,179,8,0.15); color: var(--3pm); }}
    .pick-main .player {{ font-size: 16px; font-weight: 600; }}
    .pick-main .matchup {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
    .pick-main .reasoning {{ font-size: 12px; color: var(--muted); margin-top: 6px; line-height: 1.5; }}
    .pick-right {{ text-align: right; flex-shrink: 0; }}
    .pick-line {{ font-size: 20px; font-weight: 700; color: var(--accent2); }}
    .pick-line .direction {{ font-size: 11px; color: var(--muted); font-weight: 400; display: block; }}
    .confidence {{
      margin-top: 4px;
      font-size: 11px;
      color: var(--muted);
    }}
    .conf-bar {{
      height: 3px;
      background: var(--border);
      border-radius: 99px;
      overflow: hidden;
      margin-top: 4px;
      width: 60px;
    }}
    .conf-fill {{
      height: 100%;
      border-radius: 99px;
      background: var(--accent2);
    }}

    /* ── Result badges ── */
    .result-hit {{ color: var(--hit); font-weight: 600; font-size: 12px; }}
    .result-miss {{ color: var(--miss); font-weight: 600; font-size: 12px; }}
    .result-nd {{ color: var(--muted); font-size: 12px; }}

    /* ── History table ── */
    .history-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .history-table th {{
      text-align: left;
      font-size: 11px;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--border);
    }}
    .history-table td {{
      padding: 10px 10px;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }}
    .history-table tr:last-child td {{ border-bottom: none; }}
    .history-table tr:hover td {{ background: var(--surface2); }}

    /* ── Audit panel ── */
    .audit-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 12px;
    }}
    .audit-card h3 {{ font-size: 14px; font-weight: 600; margin-bottom: 12px; }}
    .audit-list {{ list-style: none; }}
    .audit-list li {{
      padding: 6px 0;
      font-size: 13px;
      color: var(--muted);
      border-bottom: 1px solid var(--border);
      line-height: 1.5;
    }}
    .audit-list li:last-child {{ border-bottom: none; }}
    .audit-list li::before {{ content: "→ "; color: var(--accent); }}

    /* ── Empty states ── */
    .empty {{
      text-align: center;
      padding: 48px 20px;
      color: var(--muted);
      font-size: 14px;
    }}
    .empty-icon {{ font-size: 36px; margin-bottom: 12px; }}

    /* ── Overall hit rate ── */
    .overall-stat {{
      background: linear-gradient(135deg, rgba(108,99,255,0.15), rgba(0,212,170,0.15));
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
    }}
    .overall-stat .big {{ font-size: 36px; font-weight: 800; color: var(--accent2); }}
    .overall-stat .sub {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
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

<!-- TODAY'S PICKS -->
<div id="tab-picks" class="page active">
  <div id="picks-container"></div>
</div>

<!-- RESULTS -->
<div id="tab-results" class="page">
  <div class="overall-stat">
    <div>
      <div class="big" id="overall-pct">—</div>
      <div class="sub" id="overall-sub">overall hit rate</div>
    </div>
    <div id="prop-stats-mini"></div>
  </div>
  <div id="results-container"></div>
</div>

<!-- AUDIT LOG -->
<div id="tab-audit" class="page">
  <div id="audit-container"></div>
</div>

<script>
  const DATA = {{
    today_str: {json.dumps(d["today_str"])},
    today_picks: {picks_json},
    overall_hit_rate: {d["overall_hit_rate"]},
    total_graded: {d["total_graded"]},
    prop_stats: {prop_stats_json},
    last_audit: {last_audit_json},
    recent_results: {results_json},
  }};

  function showTab(name) {{
    document.querySelectorAll('.tab').forEach((t,i) => {{
      const names = ['picks','results','audit'];
      t.classList.toggle('active', names[i] === name);
    }});
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');
  }}

  function propColor(pt) {{
    return {{PTS:'prop-PTS', REB:'prop-REB', AST:'prop-AST', '3PM':'prop-3PM'}}[pt] || '';
  }}

  function renderPicks() {{
    const c = document.getElementById('picks-container');
    const picks = DATA.today_picks;

    if (!picks.length) {{
      c.innerHTML = `<div class="empty"><div class="empty-icon">🏀</div>No picks generated yet for ${{DATA.today_str}}.<br>Check back after 11 AM ET.</div>`;
      return;
    }}

    const byProp = {{}};
    picks.forEach(p => {{ (byProp[p.prop_type] = byProp[p.prop_type]||[]).push(p); }});
    const order = ['PTS','REB','AST','3PM'];

    let html = `<div class="section-header">${{picks.length}} picks — ${{DATA.today_str}}</div><div class="picks-grid">`;
    order.forEach(pt => {{
      if (!byProp[pt]) return;
      byProp[pt].sort((a,b) => b.confidence_pct - a.confidence_pct).forEach(p => {{
        const ha = p.home_away === 'H' ? 'vs' : '@';
        html += `
          <div class="pick-card">
            <div class="prop-badge ${{propColor(p.prop_type)}}">${{p.prop_type}}</div>
            <div class="pick-main">
              <div class="player">${{p.player_name}}</div>
              <div class="matchup">${{p.team}} ${{ha}} ${{p.opponent}}</div>
              <div class="reasoning">${{p.reasoning}}</div>
            </div>
            <div class="pick-right">
              <div class="pick-line">
                <span class="direction">OVER</span>
                ${{p.pick_value}}
              </div>
              <div class="confidence">${{p.confidence_pct}}%
                <div class="conf-bar"><div class="conf-fill" style="width:${{p.confidence_pct}}%"></div></div>
              </div>
            </div>
          </div>`;
      }});
    }});
    html += '</div>';
    c.innerHTML = html;
  }}

  function renderResults() {{
    // Overall stat
    document.getElementById('overall-pct').textContent =
      DATA.total_graded ? DATA.overall_hit_rate + '%' : '—';
    document.getElementById('overall-sub').textContent =
      DATA.total_graded ? `${{DATA.total_graded}} picks graded` : 'no graded picks yet';

    // Prop breakdown
    const ps = DATA.prop_stats;
    let mini = '';
    ['PTS','REB','AST','3PM'].forEach(pt => {{
      const s = ps[pt];
      if (s && s.total > 0)
        mini += `<div style="text-align:right;margin-bottom:4px"><span style="font-size:11px;color:var(--muted)">${{pt}} </span><strong>${{s.pct}}%</strong> <span style="font-size:11px;color:var(--muted)">${{s.hits}}/${{s.total}}</span></div>`;
    }});
    document.getElementById('prop-stats-mini').innerHTML = mini;

    const c = document.getElementById('results-container');
    const results = DATA.recent_results;
    if (!results.length) {{
      c.innerHTML = `<div class="empty"><div class="empty-icon">📊</div>No graded results yet.</div>`;
      return;
    }}

    let html = `<table class="history-table">
      <thead><tr>
        <th>Date</th><th>Player</th><th>Prop</th><th>Pick</th><th>Actual</th><th>Result</th>
      </tr></thead><tbody>`;
    results.forEach(p => {{
      const res = p.result === 'HIT'
        ? `<span class="result-hit">✓ HIT</span>`
        : p.result === 'MISS'
        ? `<span class="result-miss">✗ MISS</span>`
        : `<span class="result-nd">—</span>`;
      html += `<tr>
        <td>${{p.date}}</td>
        <td><strong>${{p.player_name}}</strong><br><span style="font-size:11px;color:var(--muted)">${{p.team}}</span></td>
        <td><span class="prop-badge ${{propColor(p.prop_type)}}" style="width:36px;height:20px;border-radius:4px;font-size:10px;display:inline-flex">${{p.prop_type}}</span></td>
        <td>OVER ${{p.pick_value}}</td>
        <td>${{p.actual_value ?? '—'}}</td>
        <td>${{res}}</td>
      </tr>`;
    }});
    html += '</tbody></table>';
    c.innerHTML = html;
  }}

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
        <div style="display:flex;gap:20px;margin-bottom:12px">
          <div><div style="font-size:11px;color:var(--muted)">Hit Rate</div><div style="font-size:22px;font-weight:700;color:var(--accent2)">${{a.hit_rate_pct}}%</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Picks</div><div style="font-size:22px;font-weight:700">${{a.total_picks}}</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Hits</div><div style="font-size:22px;font-weight:700;color:var(--hit)">${{a.hits}}</div></div>
          <div><div style="font-size:11px;color:var(--muted)">Misses</div><div style="font-size:22px;font-weight:700;color:var(--miss)">${{a.misses}}</div></div>
        </div>
      </div>`;

    if (a.reinforcements?.length) {{
      html += `<div class="audit-card"><h3>✓ What Worked</h3><ul class="audit-list">`;
      a.reinforcements.forEach(r => html += `<li>${{r}}</li>`);
      html += `</ul></div>`;
    }}

    if (a.lessons?.length) {{
      html += `<div class="audit-card"><h3>✗ What Missed</h3><ul class="audit-list">`;
      a.lessons.forEach(l => html += `<li>${{l}}</li>`);
      html += `</ul></div>`;
    }}

    if (a.recommendations?.length) {{
      html += `<div class="audit-card"><h3>→ Analyst Recommendations</h3><ul class="audit-list">`;
      a.recommendations.forEach(r => html += `<li>${{r}}</li>`);
      html += `</ul></div>`;
    }}

    c.innerHTML = html;
  }}

  // Init
  renderPicks();
  renderResults();
  renderAudit();
</script>
</body>
</html>"""


if __name__ == "__main__":
    build_site()
