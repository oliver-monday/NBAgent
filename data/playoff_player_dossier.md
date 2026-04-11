# NBAgent — Playoff Player Dossier
## Synthesized from H27–H32 Backtests (2026-04-11)

### How to Read This Dossier

Each player gets a **net adjustment** for playoffs based on six dimensions:
- **H28 Playoff Career**: regular→playoff tier rate delta (5 seasons, per-stat)
- **H30 Minutes Elasticity**: production curve at 38+ min (playoff minutes)
- **H31 Series Progression**: early→late series phase delta (within-series)
- **H29 Confidence Calibration**: system over/under-confidence (current season picks)
- **H32 Context Stability**: worst vulnerability and playoff neutralization status
- **H27 Blowout Resilience**: PTS performance in high-spread games

**Net direction**: BOOST (multiple signals say system underrates this player in playoffs), NEUTRAL (signals cancel or player is already well-calibrated), CAUTION (multiple signals say system overrates), or PROP-SPECIFIC (direction depends on which stat).

**Sample gate**: findings marked ⚠ have thin samples (n < 10 in the relevant bucket) and should be treated as directional, not directive.

---

## Tier 1 — Strongest Composite Signals

### Shai Gilgeous-Alexander
**Net: NEUTRAL (already optimal — trust the system's picks, they're correct)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STABLE: all 4 stats within ±4pp. No adjustment needed |
| H30 Minutes Elasticity | PLATEAUS: 100% T20 at every minutes bucket. T25 scales 71→100% at 38+ min |
| H31 Series Progression | PTS LATE_RISER (+8.3pp), 3PM LATE_RISER (+25pp). Gets stronger in elimination games |
| H29 Confidence Cal | UNDER_CONFIDENT (+13.5pp). System underrates him — 90.9% actual vs 77.4% assigned |
| H32 Context Stability | Worst vuln: AST rest (29pp range). NEUTRALIZED in playoffs (no B2Bs) |
| H27 Blowout | -6.6pp at T25 (n=21), game-script dependent. T20: reliable |
**Playoff pick guidance:** SGA is the safest pick in the system. PTS T20 is near-certain. PTS T25 is strong and gets stronger in late-series games. AST and 3PM are reliable. Confidence is systematically underrated — can trust higher tiers than the system typically selects. No prop to avoid.

### Nikola Jokic
**Net: BOOST (PTS/3PM), NEUTRAL (REB), SLIGHT CAUTION (AST at high tiers)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | ELEVATOR: PTS +9.4pp, 3PM +16.0pp. AST stable at T4 but suppressed at T6/T8 (-12 to -13pp) |
| H30 Minutes Elasticity | SCALES: T25 42%→72% at 38+ min (+30.5pp) |
| H31 Series Progression | All 4 stats STABLE. Most series-consistent player in the dataset |
| H29 Confidence Cal | UNDER_CONFIDENT (+10.6pp). AST especially: 10/10 at 100% vs 75.1% assigned |
| H32 Context Stability | Worst vuln: AST rest (40pp, B2B=57% vs norm=97%). NEUTRALIZED in playoffs |
| H27 Blowout | Only 1 game at spread_abs ≥ 15 — insufficient data |
**Playoff pick guidance:** PTS elevates in playoffs AND scales with minutes AND is series-stable — triple-confirmed boost. 3PM elevates significantly (+16pp). AST at T4 is safe (100% regular season, slight playoff dip) but avoid T6+ in playoffs per H28. B2B vulnerability eliminated in playoff scheduling. Most reliable overall playoff player.

### Anthony Edwards
**Net: BOOST (games 1-4), PROP-SPECIFIC CAUTION (games 5-7)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_ELEVATOR: PTS +7.1pp, REB +20.5pp, AST +22.7pp |
| H30 Minutes Elasticity | SCALES massively: T25 25%→50%→70%→86% (+36.4pp) |
| H31 Series Progression | PTS LATE_FADER (-15pp), 3PM LATE_FADER (-15pp). AST LATE_RISER (+11pp) |
| H29 Confidence Cal | WELL_CALIBRATED (+6.3pp, n=11) |
| H32 Context Stability | Worst vuln: PTS rest (24pp). NEUTRALIZED in playoffs |
| H27 Blowout | Not in per-player table at spread_abs ≥ 15 |
**Playoff pick guidance:** Strongest combined elevator signal in the dataset — playoff intensity + extended minutes both boost him. BUT he fades as a specific series progresses (games 5-7). In early-round games 1-4: BOOST PTS/REB/AST aggressively. In games 5-7: shift to AST (which rises late) and be cautious on PTS/3PM. System confidence is well-calibrated — no adjustment needed there.

### Luka Doncic
**Net: BOOST (PTS), SLIGHT CAUTION (AST in playoffs)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | MIXED: PTS stable, REB +5.4pp↑, AST -5.5pp↓. 3PM stable |
| H30 Minutes Elasticity | Already maxed: T20 100% at high and extended. T25 88→93→94% |
| H31 Series Progression | PTS STABLE, REB LATE_RISER (+11pp), Luka stable across phases |
| H29 Confidence Cal | UNDER_CONFIDENT (+15.7pp). PTS: 12/12 (100%). 3PM: 8/8 (100%) |
| H32 Context Stability | Worst vuln: AST rest (32pp). NEUTRALIZED in playoffs |
| H27 Blowout | MINUTES_COMPRESSED (-10.3 min) at spread_abs ≥ 15, ⚠ n=3 |
**Playoff pick guidance:** System massively underrates Luka — hasn't missed a PTS or 3PM pick all analysis window. PTS is near-certain at playoff minutes. AST dips slightly in playoffs per H28 (-5.5pp) — still pickable but don't reach for high AST tiers. REB rises as series deepen. No series fade on PTS. Rest vulnerability neutralized.

---

## Tier 2 — Clear Directional Signals

### Jayson Tatum
**Net: PROP-SPECIFIC — pick AST/REB, be cautious on PTS/3PM**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | MIXED: PTS -6.5pp↓, AST +16.6pp↑↑, 3PM -11.4pp↓. REB stable |
| H31 Series Progression | AST/REB LATE_RISER (+16.4pp each). PTS stable |
| H29 Confidence Cal | Not in qualified set (n < 10 in analysis window) |
| H32 Context Stability | Not in uploaded results |
**Playoff pick guidance:** Tatum shifts to facilitator mode in playoffs — AST is the pick, especially in late-series games where it rises further. REB also lifts. PTS suppresses and 3PM drops significantly (-11pp). Do NOT pick Tatum 3PM in playoffs. AST T4 or T6 is the sweet spot.

### Donovan Mitchell
**Net: CAUTION (PTS fragile, 3PM AVOID), SAFE (AST)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | MIXED: PTS +5.7pp↑, REB +10.7pp↑, 3PM -7.5pp↓ |
| H30 Minutes Elasticity | INVERTS: T20 drops 88%→57% at 38+ min. ⚠ n_ext=7 |
| H31 Series Progression | PTS STABLE, AST LATE_FADER (-20.8pp), REB LATE_RISER (+35.5pp) |
| H29 Confidence Cal | OVER_CONFIDENT (-10.4pp). 3PM catastrophic: 42.9% actual vs 76.1% assigned |
| H32 Context Stability | PTS rest (34pp range). NEUTRALIZED in playoffs |
| H27 Blowout | PLAYER_RESILIENT (+17.2pp), ⚠ n=6 |
**Playoff pick guidance:** Mitchell is the most complex case. H28 says PTS elevates but H30 says extended minutes hurt him and H29 says the system overrates him. 3PM is a HARD AVOID — over-confident by 33pp in regular season AND suppressed in playoffs. AST T4 is well-calibrated and safe for early-series games, but fades late. REB rises as series deepen. Net: PTS is pickable early-series at conservative tiers (T20 not T25). 3PM: never. AST: early-series only. REB: late-series opportunity.

### Jaylen Brown
**Net: BOOST (REB/AST), NEUTRAL (PTS), CAUTION (3PM)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | MIXED: REB +17.4pp↑↑, AST -6.6pp↓, 3PM -7.5pp↓. PTS stable |
| H31 Series Progression | PTS STABLE, REB LATE_RISER (+11.9pp), AST LATE_RISER (+12.2pp) |
| H29 Confidence Cal | UNDER_CONFIDENT (+18.3pp). AST 8/8 (100%). PTS 11/12 (91.7%) |
| H32 Context Stability | MODERATE (closest to all-weather: max range 18pp). NEUTRALIZED |
**Playoff pick guidance:** System massively underrates Brown — 95.7% actual hit rate. REB elevates in playoffs AND rises further in late series (double boost). AST shows slight H28 playoff suppression but H31 says it rises late — net: safe. PTS is stable and well-calibrated. 3PM dips in playoffs. Most context-stable player in the dataset — minimal vulnerability. Strong all-around playoff pick.

### Jalen Brunson
**Net: BOOST (PTS)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | MIXED: PTS +17.0pp↑↑ (54.6%→71.6% T20). Rest stable |
| H31 Series Progression | PTS STABLE across phases. No fade |
| H29 Confidence Cal | Not in qualified set |
**Playoff pick guidance:** Biggest pure PTS elevator in the dataset with a reliable sample (67 playoff games). Goes from borderline T20 in regular season to reliable. PTS T20 is the target pick. No series fade. Other stats are neutral.

### James Harden
**Net: CAUTION (PTS — especially late series), SAFE (AST only)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | SUPPRESSOR: PTS -8.0pp↓, 3PM -7.2pp↓. AST stable |
| H31 Series Progression | PTS LATE_FADER (-33.1pp!! 56→23%). AST stays 100% in mid/late |
| H29 Confidence Cal | UNDER_CONFIDENT (+10.2pp) — but this is regular season calibration |
| H32 Context Stability | 3PM rest (35.7pp range). NEUTRALIZED |
**Playoff pick guidance:** Harden's PTS collapses in playoffs (-8pp overall) and collapses FURTHER as series deepen (-33pp, the largest fade in the dataset). The H29 under-confidence is misleading — it's measuring regular-season performance where he's fine. In playoffs, ONLY pick Harden AST. His AST is bulletproof: 100% in mid and late games across 45 playoff games. PTS and 3PM: AVOID, especially games 5-7.

### Stephen Curry
**Net: PROP-SPECIFIC (PTS early-series, AST late-series)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | ELEVATOR: PTS +5.0pp↑, 3PM +5.0pp↑ |
| H31 Series Progression | PTS LATE_FADER (-15.3pp). AST LATE_RISER (+19.6pp) |
| H29 Confidence Cal | Not in qualified set |
**Playoff pick guidance:** Curry elevates in playoffs overall but fades as specific series deepen. PTS is a good pick in games 1-4, then shifts to AST in games 5-7 as defenses adjust and he distributes more. 3PM is stable across series. The late-series fade is the key nuance — the aggregate H28 elevation masks the within-series decline.

### Jamal Murray
**Net: BOOST (early-series PTS), CAUTION (late-series everything)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | ELEVATOR: PTS +6.9pp↑, REB +14.8pp↑ |
| H30 Minutes Elasticity | SCALES: T25 30%→69% at 38+ min (+39.2pp) |
| H31 Series Progression | Comprehensive LATE_FADER: PTS -11.7pp, REB -22.4pp, AST -16.1pp |
| H29 Confidence Cal | WELL_CALIBRATED (+7.8pp) |
| H32 Context Stability | MODERATE. PTS H/A 19pp (85% away, 66% home) — road games are opportunities |
**Playoff pick guidance:** Murray elevates in playoffs AND scales with minutes — both positive. But he fades comprehensively as series deepen (PTS, REB, AST all decline in games 5-7). Best pick in games 1-4. In deep series: caution across all props. Road games are better than home (19pp split). 3PM is stable throughout.

### Devin Booker
**Net: PROP-SPECIFIC — pick REB (rises in playoffs + late series), avoid AST/3PM**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | MIXED: REB +12.6pp↑↑, AST -9.5pp↓, 3PM -6.6pp↓. PTS stable |
| H31 Series Progression | PTS LATE_FADER (-22.2pp), REB LATE_RISER (+36.1pp), AST LATE_FADER (-27.8pp) |
| H29 Confidence Cal | WELL_CALIBRATED (+7.0pp) |
| H32 Context Stability | PTS spread (20pp range). PARTIALLY NEUTRALIZED |
**Playoff pick guidance:** Booker's REB is the standout — elevates in playoffs AND rises further in late series. PTS fades hard in late games (-22pp). AST fades even harder (-27.8pp). 3PM dips. In playoffs, pick REB. PTS only in early-series games. Avoid AST.

---

## Tier 3 — Caution Players

### Joel Embiid
**Net: STRONG CAUTION (PTS/AST), NEUTRAL (REB)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | SUPPRESSOR: PTS -12.3pp↓↓, AST -17.6pp↓↓. REB stable |
| H31 Series Progression | PTS STABLE (no additional fade within series) |
| H32 Context Stability | PTS spread (48pp!! comp=52%, blowout=100%). STILL ACTIVE — competitive games suppress him |
**Playoff pick guidance:** Triple-confirmed PTS suppression: H28 overall playoff drop, H32 competitive-game vulnerability (52% in tight games), and playoff games are inherently competitive. REB is his only safe playoff prop. PTS and AST: AVOID.

### Karl-Anthony Towns
**Net: STRONG CAUTION (PTS/AST/3PM), NEUTRAL (REB)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_SUPPRESSOR: PTS -16.1pp↓↓, AST -36.1pp↓↓, 3PM -19.5pp↓↓. REB stable |
| H31 Series Progression | PTS LATE_RISER (+17.7pp) — improves within series, partially offsetting H28 |
| H29 Confidence Cal | Not in qualified set |
**Playoff pick guidance:** Massive across-the-board playoff suppression except REB. The H31 late-riser signal on PTS partially offsets — he may warm up within a series (44%→62%). But the H28 baseline is so suppressed that even with late-series improvement, he's below system thresholds. REB only. If picking PTS at all, only in games 4+.

### Tyler Herro
**Net: STRONG CAUTION (all props)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_SUPPRESSOR: PTS -37.0pp↓↓, REB -23.8pp↓↓, AST -31.4pp↓↓, 3PM -29.9pp↓↓ |
| H32 Context Stability | PTS rest (41pp range). NEUTRALIZED in playoffs, but H28 suppression is structural |
**Playoff pick guidance:** Catastrophic across every stat in 29 playoff games over 5 seasons. This is not variance — it's structural. His regular-season context vulnerabilities get neutralized in playoffs but his fundamental playoff suppression remains. AVOID all Herro props in playoffs.

### Tyrese Maxey
**Net: CAUTION (PTS/AST/3PM), NUANCED**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_SUPPRESSOR: PTS -10.4pp↓, AST -24.1pp↓↓, 3PM -10.0pp↓. REB +14.9pp↑ |
| H30 Minutes Elasticity | SCALES massively: T25 33%→81% at 38+ min (+47.7pp) |
| H31 Series Progression | PTS LATE_FADER (-11.5pp), AST LATE_RISER (+24.8pp) |
| H29 Confidence Cal | Not in qualified set |
**Playoff pick guidance:** Conflicting signals. Minutes scaling suggests he should produce more with playoff minutes, but career playoff data shows consistent suppression (likely schematic — teams game-plan him). AST rises late in series despite overall playoff suppression. Net: cautious on PTS/3PM in playoffs. AST may be viable in late-series games. REB elevates. The minutes-scaling is real but gets overridden by playoff defensive attention.

---

## Tier 4 — Supporting Cast with Signal

### Jalen Williams
**Net: BOOST (PTS/REB/AST), AVOID (3PM in competitive games)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_ELEVATOR: all 4 stats lift (+8 to +28pp) |
| H31 Series Progression | REB LATE_RISER (+25pp), AST LATE_FADER (-22pp) |
| H32 Context Stability | 3PM spread (64pp!! 0% competitive, 64% blowout). STILL ACTIVE |
**Playoff pick guidance:** Massive elevator across the board. OKC's #2 becomes a monster. PTS/REB are strong. AST elevates overall but fades late-series. 3PM is extremely spread-dependent — AVOID in competitive playoff games (0% hit rate in competitive-spread regular season games).

### Austin Reaves
**Net: BOOST (broad lift)**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_ELEVATOR: PTS +14.1pp, REB +6.8pp, AST +8.8pp, 3PM +11.7pp |
| H31 Series Progression | PTS LATE_FADER (-13.3pp) but REB +40pp↑, AST +33pp↑ late |
| H29 Confidence Cal | UNDER_CONFIDENT (+13.5pp) |
**Playoff pick guidance:** Broad elevator, system underrates him. PTS fades in late series but REB/AST rise dramatically. Early-series: pick PTS. Late-series: shift to REB/AST.

### Kawhi Leonard
**Net: BOOST (PTS/REB) — health permitting**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | ELEVATOR: PTS +18.7pp↑↑, REB +18.4pp↑↑ |
| H31 Series Progression | PTS LATE_RISER (+20pp) ⚠ n_late=6 |
| H29 Confidence Cal | UNDER_CONFIDENT (+11.2pp). PTS: 8/8 (100%) |
| H32 Context Stability | 3PM H/A (24pp range). STILL ACTIVE |
**Playoff pick guidance:** Massive PTS/REB elevator AND late-riser. System underrates him significantly. When healthy, one of the strongest playoff picks. 3PM has home/away split — check venue. The perennial caveat: health/availability is the gating factor, not the data.

### Paolo Banchero
**Net: BOOST**
| Dimension | Finding |
|-----------|---------|
| H28 Playoff Career | STRONG_ELEVATOR (limited sample, ⚠ n=12) |
| H30 Minutes Elasticity | SCALES: T25 17%→55% at 38+ min (+38.3pp) |
| H29 Confidence Cal | UNDER_CONFIDENT (+19.5pp). PTS: 14/14 (100%). Largest miscalibration in dataset |
**Playoff pick guidance:** System massively underrates Banchero — hasn't missed a PTS pick. Scales dramatically with minutes. Limited playoff career sample but all signals point positive. Strong playoff pick, especially PTS.

---

## Structural Findings for Analyst Prompt

### 1. Playoff AST Suppression Is Widespread
Population AST drops -5pp in playoffs. Most non-primary-ball-handler players see AST decline: Tatum (except he rises — role expansion), Luka, Brown, Booker, Embiid, KAT, Maxey, Herro, Bridges. **Default adjustment: be cautious on AST picks in playoffs unless the player is a confirmed AST elevator (Edwards, Williams, Tatum).**

### 2. Late-Series Role Shift Pattern
Multiple stars show PTS fade + AST rise in games 5-7: Curry, Edwards, Harden, Maxey, Reaves. Defensive scheming forces primary scorers into distribution. **In deep series (games 5+), weight AST props more and PTS props less for players showing this pattern.**

### 3. Rest Vulnerabilities Are Neutralized
59% of context-sensitive stat-player combinations are rest-driven. Playoffs eliminate B2Bs entirely. **This is a structural positive for the entire pick pool — most regular-season vulnerabilities simply disappear.**

### 4. Minutes Elasticity Compounds Playoff Elevation
Players who both elevate in playoffs (H28) AND scale with minutes (H30) get a compounding boost: Edwards, Jokic, Banchero, Murray (early-series). Players who INVERT at extended minutes (Mitchell, LeBron) get their playoff elevation partially offset.

### 5. System Is Systematically Under-Confident
18 of 31 qualified players are under-confident by 8+pp. Only 2 are over-confident (Ingram, Mitchell). **The system's confidence numbers are conservative — actual hit rates are ~10pp higher than assigned. This matters most for parlay construction and bet sizing, not pick/no-pick decisions.**

---

## Implementation Note

**Do not implement these as 6 separate rules.** The dossier should be injected as a single `## PLAYOFF PLAYER ADJUSTMENTS` context block in the analyst prompt, activated by date gate (≥ April 18). Each player gets one entry with a net direction and a per-prop guidance line. The analyst reads one integrated signal per player, not six overlapping modifiers.

**Sample gate for directive rules:** Per Code's recommendation, only flag per-player adjustments as directive when supported by n ≥ 10 in the relevant bucket. Below that threshold, flag as directional (informational annotation, not confidence modifier).

**Calibration double-counting:** The existing `confidence_calibration_totals` in `audit_summary.json` feeds `_get_calibrated_prob()` in `odds_today.py`. Any per-player calibration layer must slot in before or replace that band lookup, not stack on top of it.
