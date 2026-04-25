# Home/Away Root Cause Investigation — 2026-04-25

Generated: 2026-04-25 (UTC; investigator-local clock)
Investigator: Claude Code

This report investigates two distinct home/away inversion failures observed
on the 2026-04-25 slate: a mixed split-drawer pattern on DET-ORL
(Manifestation A) and a uniformly-flipped pattern on MIN-DEN
(Manifestation B). All findings are read-only quotes from production data
files and a programmatic reproduction of `analyst.load_todays_games()`.
No code, agent, schema, prompt text, or workflow file was modified.

---

## 1. Verified Input Data

`data/nba_master.csv` header:

```
game_id,game_date,game_time_utc,season_type,home_team_name,home_team_abbrev,home_score,home_ml,home_spread,away_team_name,away_team_abbrev,away_score,away_ml,away_spread,venue_city,venue_state,home_injuries,away_injuries
```

The two target rows for 2026-04-25, verbatim:

```
401869414,2026-04-25,2026-04-25T17:00Z,3.0,Orlando Magic,ORL,0,114.0,2.5,Detroit Pistons,DET,0,-135.0,-2.5,Orlando,FL,,
401869399,2026-04-25,2026-04-26T00:30Z,3.0,Minnesota Timberwolves,MIN,0,102.0,1.5,Denver Nuggets,DEN,0,-122.0,-1.5,Minneapolis,MN,,P. Watson (Out)
```

> **Row 401869414**: home=ORL, away=DET. ORL is host. Confirmed correct
> per ESPN.
>
> **Row 401869399**: home=MIN, away=DEN. MIN is host. Confirmed correct
> per ESPN.

All four 2026-04-25 rows for completeness:

```
401869414  ORL home / DET away  (G3 — DET hosted G1+G2)
401869370  PHX home / OKC away  (G3 — OKC hosted G1+G2)
401869391  ATL home / NYK away  (G4 — NYK hosted G1+G2, ATL hosted G3)
401869399  MIN home / DEN away  (G4 — DEN hosted G1+G2, MIN hosted G3)
```

All four are 2-2-1-1-1 format games where the lower seed hosts G3+G4
after the higher seed hosted G1+G2. Master CSV is correct on all four.

---

## 2. picks.json — actual LLM outputs

26 picks total for 2026-04-25; 5 in DET-ORL, 10 in MIN-DEN.

### 2A. DET-ORL picks (game 401869414) — truth: ORL home / DET away

| player_name | team | opponent | home_away | pick_value | prop | conf | TRUTH vs PICK |
|---|---|---|---|---|---|---|---|
| Paolo Banchero | ORL | DET | H | 15 | PTS | 78 | **OK** |
| Paolo Banchero | ORL | DET | H | 4 | REB | 80 | **OK** |
| Cade Cunningham | DET | ORL | H | 6 | AST | 72 | **FLIPPED** |
| Jalen Duren | DET | ORL | H | 6 | REB | 72 | **FLIPPED** |
| Desmond Bane | ORL | DET | A | 10 | PTS | 72 | **FLIPPED** |

3 of 5 picks are flipped. Both Banchero picks (ORL=H, correct) cohabit
the file with three picks that encode the inverse (DET=H or ORL=A) for
the same game.

Reasoning / tier_walk excerpts (200-char prefixes):

- **Paolo Banchero (ORL) PTS T15** — reasoning: "FG_MARGIN_THIN steps T20→T15;
  playoff STRONG_ELEVATOR with 88% vs_tough rate supports floor." No venue
  language.
- **Paolo Banchero (ORL) REB T4** — reasoning: "Offensive-first gate steps T6→T4;
  95% consistent floor holds at minimum tier across all contexts." No venue
  language.
- **Cade Cunningham (DET) AST T6** — reasoning: "Primary creator with 7.5
  series AST avg; stepped to T6 to clear VOLATILE+T8 penalties." No venue
  language. tier_walk does not contain "home" or "road".
- **Jalen Duren (DET) REB T6** — reasoning: "Dual-signal degradation steps
  T8→T6; 5/6 H2H floor with **32 proj_min in home playoff game**." Direct
  evidence: the LLM's reasoning explicitly says DET is at home for today's
  game, which is wrong (DET is away tonight).
- **Desmond Bane (ORL) PTS T10** — reasoning: "FG_MARGIN_NEG steps T15→T10;
  perfect 6/6 H2H floor holds despite cold shooting stretch." No venue
  language.

### 2B. MIN-DEN picks (game 401869399) — truth: MIN home / DEN away

| player_name | team | opponent | home_away | pick_value | prop | conf | TRUTH vs PICK |
|---|---|---|---|---|---|---|---|
| Nikola Jokic | DEN | MIN | H | 20 | PTS | 80 | **FLIPPED** |
| Nikola Jokic | DEN | MIN | H | 10 | REB | 72 | **FLIPPED** |
| Nikola Jokic | DEN | MIN | H | 6 | AST | 70 | **FLIPPED** |
| Jamal Murray | DEN | MIN | H | 15 | PTS | 70 | **FLIPPED** |
| Jamal Murray | DEN | MIN | H | 4 | AST | 82 | **FLIPPED** |
| Anthony Edwards | MIN | DEN | A | 2 | AST | 82 | **FLIPPED** |
| Julius Randle | MIN | DEN | A | 10 | PTS | 72 | **FLIPPED** |
| Julius Randle | MIN | DEN | A | 4 | REB | 72 | **FLIPPED** |
| Jaden McDaniels | MIN | DEN | A | 10 | PTS | 75 | **FLIPPED** |
| Jaden McDaniels | MIN | DEN | A | 2 | AST | 76 | **FLIPPED** |

**10 of 10 picks flipped — uniform inversion.** All DEN players carry
`home_away="H"`; all MIN players carry `home_away="A"`. The opposite of
truth.

Reasoning / tier_walk excerpts:

- **Nikola Jokic (DEN) PTS T20** — reasoning: "Iron-floor center in
  **must-win home game**; 97% competitive rate confirms T20 structural
  floor." Direct evidence: LLM believes DEN is home.
- **Nikola Jokic (DEN) REB T10** — reasoning: "7/7 H2H at T12 and playoff
  REB boost; step to T10 for 25th-pct gate safety." No venue language but
  tier_walk references "Jok…" for series stats.
- **Nikola Jokic (DEN) AST T6** — reasoning: "MIN suppressor stepped from
  T10 to T6; 7/7 H2H floor supports despite down trend." No venue
  language.
- **Jamal Murray (DEN) PTS T15** — reasoning: "FG_MARGIN_NEG steps T20→T15;
  **must-win home game** with 40 proj_min ensures full load." Direct
  evidence: LLM believes DEN is home.
- **Jamal Murray (DEN) AST T4** — reasoning: "95% consistent floor at T4;
  MIN suppressor doesn't target Murray's own AST production." No venue
  language.
- **Anthony Edwards (MIN) AST T2** — reasoning: "95% consistent AST floor
  with perfect 6/6 H2H; **DEN desperation ensures competitive game and
  full minutes**." Implicitly assumes DEN is desperate (trailing 1-2),
  which is true in series sense, but the pick orientation has MIN tagged
  as away.
- **Julius Randle (MIN) PTS T10** — reasoning: "FG_MARGIN_NEG steps
  T15→T10; 8-game PTS streak with 6/7 H2H provides solid floor at T10."
  No venue language.
- **Jaden McDaniels (MIN) PTS T10** — reasoning: "Playoff STRONG BOOST
  dossier; 3/3 series hits at T10 with fully healthy 37-min workload
  confirmed." No venue language.

**Manifestation A (DET-ORL split-drawer)** is confirmed exactly as
described in the spec: 2 correct picks (ORL=H) coexist with 3 flipped
picks (DET=H or ORL=A) for the same game — the LLM disagreed with
itself across the slate. The Duren reasoning ("home playoff game") shows
the LLM's mental model thought DET was hosting, but Banchero's picks
escaped that mental model.

**Manifestation B (MIN-DEN uniform flip)** is confirmed exactly as
described: 10 of 10 picks have inverted `home_away`/`opponent`. Two
Jokic picks and one Murray pick contain free-text reasoning ("must-win
home game") that shows the LLM's mental model has DEN as the home team
for today, which is the inverse of master truth.

---

## 3. player_stats.json — quant outputs

Per-player today_spread + spread_abs + blowout_risk + is_favorite for
all DET / ORL / MIN / DEN whitelisted players in `data/player_stats.json`:

| player_name | team | opp | today_spread | spread_abs | blowout_risk | is_favorite |
|---|---|---|---|---|---|---|
| Aaron Gordon | DEN | MIN | -1.5 | 1.5 | False | True |
| Anthony Edwards | MIN | DEN | +1.5 | 1.5 | False | False |
| Ausar Thompson | DET | ORL | -2.5 | 2.5 | False | True |
| Cade Cunningham | DET | ORL | -2.5 | 2.5 | False | True |
| Cameron Johnson | DEN | MIN | -1.5 | 1.5 | False | True |
| Desmond Bane | ORL | DET | +2.5 | 2.5 | False | False |
| Jaden McDaniels | MIN | DEN | +1.5 | 1.5 | False | False |
| Jalen Duren | DET | ORL | -2.5 | 2.5 | False | True |
| Jamal Murray | DEN | MIN | -1.5 | 1.5 | False | True |
| Julius Randle | MIN | DEN | +1.5 | 1.5 | False | False |
| Nikola Jokic | DEN | MIN | -1.5 | 1.5 | False | True |
| Paolo Banchero | ORL | DET | +2.5 | 2.5 | False | False |
| Rudy Gobert | MIN | DEN | +1.5 | 1.5 | False | False |

Truth vs computed:

- DET (away, favored) → today_spread should be -2.5 → **all DET players are -2.5 ✓**
- ORL (home, +2.5) → +2.5 → **all ORL players are +2.5 ✓**
- MIN (home, +1.5) → +1.5 → **all MIN players are +1.5 ✓**
- DEN (away, favored) → -1.5 → **all DEN players are -1.5 ✓**

**All `today_spread` signs are correct.** This is the canonical signal
that, if used by the analyst, would unambiguously identify each team's
favored/underdog status, which combined with master CSV would resolve
home/away. Quant has the truth; the LLM does not consume it as an
explicit home/away.

### Explicit home/away field check

The full top-level field set for a sample player_stats entry:

```
['avg_minutes_last5', 'b2b_hit_rates', 'best_tiers', 'blowout_risk',
 'bounce_back', 'def_recency', 'dense_schedule', 'ft_safety_margin',
 'game_pace', 'games_available', 'games_last_7', 'h2h_splits',
 'home_away_splits', 'key_teammate_absent', 'last_updated',
 'matchup_tier_hit_rates', 'minutes_floor', 'minutes_trend',
 'on_back_to_back', 'opp_defense', 'opponent', 'playoff_profile',
 'playoff_series_state', 'positional_dvp', 'raw_avgs', 'rest_days',
 'shooting_regression', 'spread_abs', 'spread_split_hit_rates',
 'star_absence_lift', 'team', 'team_momentum', 'teammate_correlations',
 'tier_hit_rates', 'today_spread', 'trend', 'volatility',
 'whitelisted_teammates']
```

The only field with "home" in the name is `home_away_splits` — that is
the player's HISTORICAL splits over their season (already-played games),
NOT today's home/away.

> **player_stats.json does NOT expose an explicit today-home/away
> field. The analyst LLM must infer it from the games_block + opponent
> matching, OR the prompt must surface a derived field.**

There is, however, a structurally-correct latent signal in
`playoff_series_state.is_road_game` per player. Sample dumps:

```json
Nikola Jokic (DEN):
{ "team_wins": 1, "opp_wins": 2, "series_game_number": 4,
  "is_road_game": true, "opp_trailing_by": 0,
  "is_desperate_host_opp": false }

Anthony Edwards (MIN):
{ "team_wins": 2, "opp_wins": 1, "series_game_number": 4,
  "is_road_game": false, "opp_trailing_by": 1,
  "is_desperate_host_opp": false }

Cade Cunningham (DET):
{ "team_wins": 1, "opp_wins": 1, "series_game_number": 3,
  "is_road_game": true, "opp_trailing_by": 0,
  "is_desperate_host_opp": false }

Paolo Banchero (ORL):
{ "team_wins": 1, "opp_wins": 1, "series_game_number": 3,
  "is_road_game": false, "opp_trailing_by": 0,
  "is_desperate_host_opp": false }
```

`is_road_game` is correctly populated for every player in both
games — DEN and DET are road; MIN and ORL are home. **Quant has the
truth.** The question is whether the LLM is shown this field — see
Section 7.

---

## 4. playoff_matchup.json — series context block

`data/playoff_matchup.json` exists. Top-level keys:
`['date', 'generated_at', 'mode', 'round', 'season', 'series', 'context_block']`.
date=2026-04-25, mode=playoffs, 8 series entries.

### DEN vs MIN entry — structural fields (verbatim)

```
series_id:    W3
conference:   West
home_team:    DEN
away_team:    MIN
home_wins:    1
away_wins:    2
games_played: 3
game_in_series: 4
series_phase:   mid
game_today:     True
series_state:   {'home_state': 'trailing', 'away_state': 'favorable',
                 'note': 'Competitive series — both teams playing to win
                 every game. Standard game scripts apply.'}
game_log: [
  {date:'2026-04-18', home_abbrev:'DEN', away_abbrev:'MIN', winner:'DEN', score 116-105},
  {date:'2026-04-20', home_abbrev:'DEN', away_abbrev:'MIN', winner:'MIN', score 114-119},
  {date:'2026-04-23', home_abbrev:'MIN', away_abbrev:'DEN', winner:'MIN', score 113-96},
]
```

The `home_team`/`away_team` fields are **bracket-seeding labels**, not
today's host. DEN is the higher seed (3 vs 6) and was the bracket-home
host of G1+G2. The game_log carries the correct per-game host, but the
top-level `home_team:DEN` framing is preserved throughout.

### DEN vs MIN — section in `context_block` (verbatim, 5,324 chars)

```
=== DEN vs MIN — West | MIN leads 2-1 | GAME 4 (MID) ===
State: DEN [TRAILING] / MIN [FAVORABLE]
Note: Competitive series — both teams playing to win every game. Standard game scripts apply.
Game log:
  Game 1 (2026-04-18, DEN home): DEN 116 — MIN 105 (W: DEN)
  Game 2 (2026-04-20, DEN home): DEN 114 — MIN 119 (W: MIN)
  Game 3 (2026-04-23, DEN away): MIN 113 — DEN 96 (W: MIN)
```

(per-player series + H2H tables follow; not relevant to the venue
question)

Substring matches from this block:

- `DEN home`: 2 hits (both correct historical — G1 and G2 were DEN home)
- `DEN away`: 1 hit (correct — G3 was DEN away)
- `at MIN` / `at Minneapolis` / `Game 4 at MIN`: **0 hits**
- `GAME 4`: 1 hit (in the section header, no venue annotation)
- `home_team:DEN` (bracket framing): present in JSON structural
  fields; the heading "=== DEN vs MIN" lists DEN first

> **The series_context block does NOT contain any explicit "Game 4
> tonight at MIN" or "Game 4 at Minneapolis" anchor.** The LLM must
> infer from the G3 game_log line ("DEN away: MIN 113 — DEN 96") that
> G4 in 2-2-1-1-1 format also takes place at MIN. This is one
> indirect inference vs multiple direct DEN-first textual cues.

### DET vs ORL entry — structural fields (verbatim)

```
series_id:    E1
conference:   East
home_team:    DET
away_team:    ORL
home_wins:    1
away_wins:    1
games_played: 2
game_in_series: 3
series_phase:   mid
game_today:     True
series_state:   {'home_state': 'trailing', 'away_state': 'trailing',
                 'note': 'Competitive series — both teams playing to win
                 every game. Standard game scripts apply.'}
game_log: [
  {date:'2026-04-19', home_abbrev:'DET', away_abbrev:'ORL', winner:'ORL', score 101-112},
  {date:'2026-04-22', home_abbrev:'DET', away_abbrev:'ORL', winner:'DET', score 98-83},
]
```

### DET vs ORL — section in `context_block` (verbatim, 3,443 chars)

```
=== DET vs ORL — East | Tied 1-1 | GAME 3 (MID) ===
State: DET [TRAILING] / ORL [TRAILING]
Note: Competitive series — both teams playing to win every game. Standard game scripts apply.
Game log:
  Game 1 (2026-04-19, DET home): DET 101 — ORL 112 (W: ORL)
  Game 2 (2026-04-22, DET home): DET 98 — ORL 83 (W: DET)
```

Substring matches:

- `DET home`: 2 hits (both correct historical)
- `at ORL` / `at Orlando` / `Game 3 at ORL`: **0 hits**
- `GAME 3`: 1 hit (header only, no venue)

Same structure as DEN-MIN — bracket-home is the first-listed team, no
explicit "today at <venue>" line, LLM must infer from format.

### Top-level `context_block` lead text

```
## SERIES CONTEXT — PLAYOFFS
Per-series performance data computed from completed playoff games + full regular season H2H matchup history. Season H2H is shown for ALL series regardless of games played — it is the baseline that captures the player-vs-opponent relationship across home/away environments. Series stats reflect actual playoff performance to date.

Use this section to supplement QUANT STATS:
  - Series-specific trend (over/under-performing vs season baseline?)
  - Series state — dominant/desperate teams have structurally different game scripts
  - Home/away H2H split — home court matters in a 7-game series
  - First playoff meeting (0 H2H games) — treat as higher variance; lean on season DvP and pace signals instead
```

The lead text mentions "Home/away H2H split" but never asserts WHICH
team is home tonight. The LLM is told to "use this section" but the
section itself omits today's venue.

---

## 5. nba_season_context.md — DEN-MIN diary references

Headings present in `context/nba_season_context.md` (8 total):
```
##### (3) NYK vs (6) ATL
##### (4) CLE vs (5) TOR
##### (1) DET vs (8) ORL
##### (2) BOS vs (7) PHI
##### (3) DEN vs (6) MIN
##### (4) LAL vs (5) HOU
##### (1) OKC vs (8) PHX
##### (2) SAS vs (7) POR
```

### DEN-MIN section, 5,484 chars, verbatim heading + Pre-Series Intel

```
##### (3) DEN vs (6) MIN
*(Game 1: Apr 18, 3:30 PM ET at Denver. DEN won season series 3-1. Third playoff meeting in 4 years.)*

**Pre-Series Intel (sources: NBA.com, The Athletic, SI, ESPN — Apr 13):**
- Rivalry series: DEN won 2023 R1 (4-1), MIN won 2024 R2 (4-3). Teams know each other intimately. DEN enters on 12-game win streak, NBA's #1 offense (121.2 ORtg).
- Jokic-Murray two-man game is the engine: 170 Murray assists to Jokic (most in NBA), 894 Jokic ball-screens for Murray (most to any single teammate), 453 Jokic handoffs to Murray (165 more than any other combo). Disrupting this connection is MIN's primary defensive objective.
- DEN's defensive weakness: 21st-ranked defense. Perimeter defenders (Murray, Braun, Cam Johnson) cannot guard Edwards — "Nuggets don't have anyone they can count on to guard Edwards" (SI). Edwards' driving game should feast against DEN's perimeter D. This is MIN's undeniable advantage.
- Edwards health update (The Athletic, Krawczynski): "All signs are he will be ready to roll. McDaniels is 100 percent. Naz Reid's shoulder appears to be improving. Gobert and Randle got rest in final 3 games."
- MIN concern: Naz Reid's shooting (3P% dropped from 38.5% to 27.8% since ASB). MIN needs his bench scoring. Ayo Dosunmu has been "outstanding" since trade deadline as secondary creator.
- Pace factor: DEN's #1 offense suggests high-scoring games. MIN's switching defense (H15 note: MIN×AST suppressor confirmed) will try to compress pace. Christmas Day game went to OT (Jokic 56/16/15, Edwards 44) — expect fireworks.
- Tim Hardaway Jr. venue factor: Had two explosive 3rd-quarter performances in Minneapolis this season (5-for-5 from 3 in one game). Monitor as a bench scoring wildcard.
```

### DEN-MIN G1, G2, G3 paragraphs (verbatim)

```
**Game 1 (Apr 18) — DEN 116, MIN 105 | DEN leads 1-0**
Murray 30 (16-16 FT, 0-8 3PT — scoring via FTs and paint, zero 3PM). Jokic triple-double (25/10+/10+, slow first half but imposed will in second). Edwards 22 — kept MIN in it but not enough. DEN's 12-game win streak momentum carried into playoffs. Murray's 3PT shooting was ice-cold (0-for-8) but he compensated through free throws (perfect 16-16) and driving — this is an important data point for his 3PM props going forward. Jokic AST volume held despite MIN×AST suppressor (7+ AST in triple-double). G2 key: MIN must solve DEN's FT advantage (Murray alone was +16 from the line) and find bench scoring. DEN's perimeter defense on Edwards was solid but not lockdown — Edwards' knee health looked functional.

**Game 2 (Apr 20) — MIN 119, DEN 114 | Series tied 1-1 — MIN STEALS ONE IN DENVER**
MIN evens the series with a road win — the result DEN tried to prevent. Edwards 30/10reb (scoring-mode carry, but only 2 AST in 40 min — AST compressed by isolation-heavy comeback role). Randle 24/9reb/6ast — dominant all-around game. McDaniels 14 in 37 min (steady contributor). Murray 30 in 43 min for DEN in the loss — matched Edwards' output but it wasn't enough. Jokic 24/15reb/8ast in 40 min (dominated boards but couldn't close). Close game throughout (5-pt final margin). MIN's bench and secondary scoring made the difference. Edwards' knee confirmed not limiting — 30 pts in 40 full minutes. G3 key: Series shifts to Minnesota. DEN's home-court advantage is gone. Jokic's AST volume (8) held through MIN×AST suppressor in a competitive loss — the suppressor may be less effective when DEN is playing from behind. Edwards AST self-suppression pattern (2 AST in scoring-carry mode) is a real signal — do not trust regular-season AST rates for Edwards in close playoff games where he's the primary offensive option.

**Game 3 (Apr 23) — MIN 113, DEN 96 | MIN leads 2-1 — MIN TAKES SERIES LEAD AT HOME (margin 17)**
MIN takes a 2-1 series lead with a commanding home performance — the 8-seed that nearly won in Denver twice has now seized control. Dosunmu 25/3/9 (10-15 FG) was the offensive engine in a game where Edwards (17/5/3, 6-15 FG, only 24 min) was clearly managed on minutes — the reduced minutes are the most significant development of the game and confirm ongoing knee management; with Edwards limited, Dosunmu's secondary creator role expanded dramatically and his 9 AST is the most by a MIN reserve this series. McDaniels 20/10/3 (9-13 FG, 41 min) — a breakout playoff performance that validates his full recovery from the patella tendinopathy; his 41 minutes confirms his ramp-up is complete and he is now a reliable two-way contributor. Jokic 27/15/3 (7-26 FG) — a historically efficient rebounding performance (15 boards) but the 3 AST is his lowest in the series and the MIN×AST suppressor is asserting itself emphatically; his shooting volume (26 FGA) in a 17-point blowout loss suggests DEN leaned on him heavily but the game script compressed his playmaking. Murray 16 (5-17 FG, 0 3PM) continued his cold 3-point shooting (0-for-8 in G1, 0-for-3 combined in G2/G3 based on series pattern) — his perimeter shooting concerns from G1 have not resolved. Aaron Gordon (QUES pre-game) status requires monitoring — if he was unavailable or limited, DEN's defensive anchor was compromised in a game that got away from them. G4 key: Edwards' 24-minute load management is the defining variable — if Finch increases his minutes in a must-win road game, MIN's offensive ceiling rises sharply; DEN needs Murray to find his 3-point shot and Jokic to generate assists in a competitive game script rather than an isolation-heavy blowout role, or MIN will close out the series at home in G5.
```

### DEN-MIN — explicit venue-anchor scan with surrounding context

| Phrase | Found? | Excerpt |
|---|---|---|
| `at Denver` | yes (1) | "(Game 1: Apr 18, 3:30 PM ET at Denver. DEN won season series…" — historical / G1 only |
| `Series shifts to Minnesota` | yes (1) | "G3 key: Series shifts to Minnesota. DEN's home-court advantage is gone." — correct for G3 |
| `MIN STEALS ONE IN DENVER` | yes (1) | G2 heading — confirms G2 was at DEN |
| `won in Denver twice` | yes (1) | "the 8-seed that nearly won in Denver twice has now seized control" — historical |
| `MIN…road win` | yes (1) | "MIN evens the series with a road win" — historical, G2 |
| `must-win road game` | **yes (1)** | "if Finch increases his minutes in a **must-win road game**, MIN's offensive ceiling rises sharply" |
| `MIN will close out the series at home in G5` | **yes (1)** | end of G3 paragraph |

**Two factually wrong venue claims in the G3 paragraph (last paragraph
of the diary, the most recent context the LLM sees):**

1. **"if Finch increases his minutes in a must-win road game"** —
   referring to MIN's upcoming G4. Truth: G4 is at MIN (per master row
   401869399). MIN is at home for G4, not on the road. The phrase
   anchors the LLM to MIN-as-road / DEN-as-home for tonight.

2. **"MIN will close out the series at home in G5"** — In 2-2-1-1-1
   format with DEN as the 3-seed (higher seed), G5 is at DEN, not at
   MIN. If MIN won G4 they would close out away in G5. The phrase
   compounds the venue inversion across upcoming games.

These are the only two G4-venue-relevant statements in the entire
DEN-MIN diary. **Both are wrong. Both anchor the LLM to DEN-as-home
for tonight.**

### DET-ORL section — Pre-Series Intel + diary (verbatim, abbreviated)

```
##### (1) DET vs (8) ORL
*(Game 1: Apr 19, 6:30 PM ET at Detroit. Season series 2-2, each team won once on other's floor.)*

[Pre-Series Intel paragraphs — no venue forecasting beyond G1]

**Game 1 (Apr 19) — ORL 112, DET 101 | ORL leads 1-0 — UPSET**
8-seed ORL stuns 1-seed DET on the road. Wire-to-wire win — Suggs hit a 3 for the opening bucket and ORL never trailed. […] DET's 1-seed home court advantage immediately surrendered. […] DET must reclaim home court in G2 (Apr 22).

**Game 2 (Apr 22) — DET 98, ORL 83 | Series tied 1-1 — DET RECLAIMS HOME COURT**
Cunningham 27/6/11 (11-19 FG, 37 min) — his minutes ramp-up is fully complete […] G3 key: Series shifts to Orlando where ORL's home crowd and G1 momentum could re-energize their defense […]
```

### DET-ORL — explicit venue-anchor scan

| Phrase | Found? | Excerpt |
|---|---|---|
| `at Detroit` | yes (1) | "(Game 1: Apr 19, 6:30 PM ET at Detroit…" — historical / G1 |
| `Series shifts to Orlando` | yes (1) | "G3 key: Series shifts to Orlando where ORL's home crowd…" — **correct for tonight's G3** |
| `DET's 1-seed home court advantage immediately surrendered` | yes (1) | historical / G1 |
| `DET must reclaim home court in G2` | yes (1) | historical / G2 forecast (correct at the time) |
| `must-win road game` | **no** | not present for DET-ORL |
| `at home in G…` (any) referring to upcoming venue | **no** | not present |

> **The DET-ORL diary's G2 closing paragraph correctly anchors today's
> G3 venue ("Series shifts to Orlando where ORL's home crowd…").** No
> conflicting or wrong upcoming-venue claims.

---

## 6. Reproduced analyst prompt — TODAY'S GAMES block

`agents/analyst.py:112` `load_todays_games()` reads `MASTER_CSV` directly
(no flipping) and emits one dict per row, copying `home_team_abbrev` and
`away_team_abbrev` verbatim into `home_abbrev` / `away_abbrev`.

A direct import of the analyst module fails locally (no `httpx`/`anthropic`
available in this environment), but the source code at lines 112–147
contains no transformation — `row.get("home_team_abbrev", "")` is
copied 1:1 to `home_abbrev`. Reproducing the same logic with the stdlib
`csv` module yields:

```json
[
  {
    "game_id": "401869414",
    "game_time_utc": "2026-04-25T17:00Z",
    "home_team": "Orlando Magic",     "home_abbrev": "ORL",
    "away_team": "Detroit Pistons",   "away_abbrev": "DET",
    "venue_city": "Orlando",
    "home_spread": 2.5,  "away_spread": -2.5
  },
  {
    "game_id": "401869370",
    "game_time_utc": "2026-04-25T19:30Z",
    "home_team": "Phoenix Suns",            "home_abbrev": "PHX",
    "away_team": "Oklahoma City Thunder",   "away_abbrev": "OKC",
    "venue_city": "Phoenix",
    "home_spread": 9.5,  "away_spread": -9.5
  },
  {
    "game_id": "401869391",
    "game_time_utc": "2026-04-25T22:00Z",
    "home_team": "Atlanta Hawks",       "home_abbrev": "ATL",
    "away_team": "New York Knicks",     "away_abbrev": "NYK",
    "venue_city": "Atlanta",
    "home_spread": 2.5,  "away_spread": -2.5
  },
  {
    "game_id": "401869399",
    "game_time_utc": "2026-04-26T00:30Z",
    "home_team": "Minnesota Timberwolves",  "home_abbrev": "MIN",
    "away_team": "Denver Nuggets",          "away_abbrev": "DEN",
    "venue_city": "Minneapolis",
    "home_spread": 1.5,  "away_spread": -1.5
  }
]
```

> The `## TODAY'S GAMES` block matches master CSV truth exactly. ORL
> is the home team for game 401869414. MIN is the home team for game
> 401869399. **There is no flipping step between master and games_block.**
> H2 (pipeline flips home/away) is **RULED OUT**.

---

## 7. Reproduced analyst prompt — full DEN-MIN-relevant context

The analyst module's runtime imports (`httpx`, `anthropic`, etc.) are not
available in this read-only investigation environment, so a full
`build_prompt()` reproduction would error out. Instead the relevant
context blocks are recovered by reading the source files those loaders
read, which is byte-equivalent to what the LLM saw on the production
analyst run that wrote today's picks.

### TODAY'S GAMES block — see Section 6.

ORL=home for 401869414, MIN=home for 401869399. **Correct.**

### `## SERIES CONTEXT — PLAYOFFS` — DEN-MIN section

Reproduced verbatim in Section 4. Key facts:

- Heading: `=== DEN vs MIN — West | MIN leads 2-1 | GAME 4 (MID) ===`
  (DEN listed first as bracket-home)
- State line: `State: DEN [TRAILING] / MIN [FAVORABLE]` (DEN listed first)
- Game log entries each carry correct historical (home/away) annotation
- **No explicit "Game 4 tonight at MIN" line.**
- DEN appears 50+ times in the DEN-MIN block; MIN appears ~50 times;
  the framing is balanced once you read carefully, but the
  bracket-home (DEN) is always listed first.

### Per-player quant_context lines for DEN/MIN/DET/ORL whitelisted players

`agents/analyst.py:1872` reads `s.get("playoff_series_state")` and
emits `[DESPERATE_HOST_OPP:{opp_wins}-{team_wins}]` ONLY when
`is_desperate_host_opp` is True. From Section 3 dumps:

- Jokic / Edwards (MIN-DEN G4): `is_desperate_host_opp=False` →
  **no DESPERATE_HOST_OPP tag emitted**
- Cunningham / Banchero (DET-ORL G3): `is_desperate_host_opp=False` →
  **no tag emitted**

`is_desperate_host_opp` requires `is_road_game=True AND opp_trailing_by >= 2`.
For Jokic this morning: `is_road_game=true, opp_trailing_by=0` (MIN is
LEADING 2-1, not trailing) → False. For Cunningham: same → False.

> **`build_quant_context()` does NOT surface `is_road_game` to the LLM
> in any other code path.** The conditional `[DESPERATE_HOST_OPP:...]`
> tag is the only place the per-player home/away signal could appear,
> and it does not fire for either of today's two affected games.
> **The LLM has no explicit per-player home/away annotation in
> quant_context lines.**

### `## SEASON CONTEXT — POSTSEASON DIARY` — DEN-MIN section

Reproduced verbatim in Section 5. Headline finding:

The G3 closing paragraph (the most recent forward-looking commentary
in the DEN-MIN diary) contains TWO factually wrong G4-venue statements:

1. `must-win road game` — the LLM is told MIN's G4 is on the road. **Wrong.**
2. `MIN will close out the series at home in G5` — the LLM is told G5
   is at MIN. **Wrong** (G5 in 2-2-1-1-1 with DEN as 3-seed is at DEN).

Coarse anchor tally across the DEN-MIN combined corpus (series_context
+ season_context, ~10,800 chars):

| Anchor type | Hits | Examples |
|---|---|---|
| DEN-as-home (correct historical for G1/G2) | 4 | "Game 1 at Denver", "DEN home" in G1/G2 logs, "won in Denver twice" |
| DEN-bracket-home framing (structural) | many | "DEN vs MIN" header order, "DEN [TRAILING]" first listing |
| MIN-as-home (correct, G3) | 3 | "Series shifts to Minnesota", "MIN TAKES SERIES LEAD AT HOME", "MIN…commanding home performance" |
| MIN-as-road / DEN-as-home for upcoming G4 | **2 (both wrong)** | "must-win road game" (MIN), "MIN will close out…at home in G5" |

The two wrong anchors are the only forward-looking venue statements
about tonight's G4. They contradict the (correct) historical anchors
and the (correct) `## TODAY'S GAMES` block.

### `## SEASON CONTEXT — POSTSEASON DIARY` — DET-ORL section

Reproduced in Section 5. The G2 closing paragraph correctly anchors G3:

- `G3 key: Series shifts to Orlando where ORL's home crowd and G1
  momentum could re-energize their defense`

No wrong upcoming-venue claims in the DET-ORL diary.

### Substring tally across the assembled DEN-MIN-relevant corpus

For each phrase that would mislead the LLM about tonight's venue:

| Phrase | DEN-MIN corpus | DET-ORL corpus |
|---|---|---|
| `at Denver` | 1 hit (G1, historical) | n/a |
| `at Minneapolis` / `at MIN` | 0 hits | n/a |
| `Denver hosts` / `MIN hosts` | 0 / 0 | n/a |
| `at Detroit` | n/a | 1 hit (G1, historical) |
| `at Orlando` (or "shifts to Orlando") | n/a | 1 hit (forward, correct) |
| `must-win road game` | **1 hit (wrong, MIN G4)** | 0 |
| `at home in G5` (any) | **1 hit (wrong, MIN G5)** | 0 |
| `Game 4 at` | 0 hits | n/a |
| `Game 3 at` | n/a | 0 hits |

**The DEN-MIN corpus is the only one of the two with explicit wrong
venue claims about today/tomorrow's games. The DET-ORL corpus is
clean.**

---

## 8. Hypothesis evaluation

### H1. Master CSV is wrong
**RULED OUT** by Section 1. Both rows verified.

### H2. Analyst pipeline flips home/away between master and games_block
**RULED OUT** by Section 6. `load_todays_games()` (analyst.py:112) reads
`home_team_abbrev` directly from master and copies it to `home_abbrev`
without transformation. The reproduced `## TODAY'S GAMES` block has
ORL=home, MIN=home — matches master truth.

### H3. `today_spread` sign is wrong in player_stats.json, misleading the LLM
**RULED OUT** by Section 3. All 13 DET/ORL/MIN/DEN players have
correctly signed `today_spread`: DEN=-1.5, MIN=+1.5, DET=-2.5, ORL=+2.5.
Spread sign is not the misleading signal.

### H4. `series_context` from `playoff_matchup.json` has wrong home/away for G4
**INCONCLUSIVE — leans toward STRUCTURAL RISK.** The series_context
block does not contain wrong factual claims, but it ALSO does not
contain a single explicit "Game 4 tonight at MIN" or "Game 3 tonight at
ORL" anchor. The block leads with "DEN vs MIN" and "DEN [TRAILING] /
MIN [FAVORABLE]" framing — DEN is structurally first in every
positional cue. The historical game log carries correct per-game home/
away, which a careful reader can use to extrapolate G4's venue from
the 2-2-1-1-1 format. But the block omits the most direct anchor
("today at MIN") that would foreclose the inference. This is a
structural weakness, not a factual error.

### H5. Season context has prose that anchors the LLM to wrong venue
**SUPPORTED for Manifestation B (DEN-MIN).** Section 5's tally finds
**two** wrong venue claims in the DEN-MIN G3 closing paragraph:

1. `if Finch increases his minutes in a must-win road game` — claims
   MIN G4 is on the road. False (G4 is at MIN per master).
2. `MIN will close out the series at home in G5` — claims G5 is at
   MIN. False (G5 is at DEN per 2-2-1-1-1 with DEN as 3-seed).

Both phrases occur in the same paragraph. They are mutually consistent
in their inversion — both treat MIN as if it were the higher seed (and
DEN as the lower seed) for upcoming games. Together they form a
self-reinforcing factual error pattern that anchors the LLM to
DEN-as-home for tonight's G4. **This is the most likely root cause
for Manifestation B (the uniform 10/10 flip).**

The matching reasoning text on Jokic and Murray picks ("must-win home
game") strongly suggests the LLM was reading these anchors and
applying them to its venue inference.

**RULED OUT for Manifestation A (DET-ORL).** The DET-ORL diary's G2
closing paragraph correctly states "G3 key: Series shifts to Orlando"
— there are no wrong upcoming-venue claims. Manifestation A cannot be
attributed to misleading season context.

### H6. Multiple references in the assembled prompt to "DEN home" outweigh one correct line in TODAY'S GAMES
**SUPPORTED for Manifestation B.** Counting bracket-home framing as
DEN-home cues:

- DEN-as-home or DEN-bracket-home anchors: 4 historical + many
  structural (header order, state ordering) + 2 wrong forward
  statements
- MIN-as-home anchors: 3 correct historical/G3 + 0 forward statements

Even if the LLM correctly read `## TODAY'S GAMES` (one line, "MIN home"),
the surrounding context is ~10,800 chars dominated by DEN-first
framing AND two wrong forward statements. The arithmetic of conflicting
references favors DEN-as-home.

This is a structural risk independent of H5 — even if H5's two wrong
phrases were corrected, the bracket framing alone could still mislead
on close calls.

### H7. LLM-only failure (correct input, hallucinated output) — Manifestation A
**SUPPORTED for Manifestation A specifically.** Section 5 confirms the
DET-ORL season context has no wrong venue claims, and Section 6
confirms `## TODAY'S GAMES` is correct. Yet 3 of 5 DET-ORL picks were
flipped — including Duren's reasoning explicitly saying "in home
playoff game" for a road game. With clean input and mixed (not
uniform) output, this is consistent with classic LLM inattention/noise
across the slate, not a systematic input error.

### H8. LLM-only failure for Manifestation B too
**RULED OUT.** Section 5's smoking gun (two wrong forward statements
in the DEN-MIN G3 closing paragraph) plus Section 7's anchor tally
(DEN-as-home anchors outnumber MIN-as-home anchors in upcoming-game
framing) provide a self-consistent input-side explanation for the
uniform 10/10 flip. Combined with the LLM's free-text reasoning
echoing "must-win home game" for DEN, an LLM-only-noise account is
not necessary and not the simplest explanation.

> **Manifestation A (DET-ORL split-drawer) is most consistent with
> H7 (LLM-only inattention). Manifestation B (DEN-MIN uniform flip) is
> most consistent with H5 + H6 (wrong forward-venue prose in the season
> context's G3 paragraph, compounded by DEN-bracket-home framing across
> all injected blocks). The single highest-leverage input fix is to
> correct the two wrong sentences in the DEN-MIN G3 diary entry of
> `context/nba_season_context.md` AND add an explicit "Game 4 tonight
> at MIN" line to the series_context block emitter, and the highest-
> leverage output validation is a deterministic per-pick reconciliation
> in `analyst.save_picks()` that overwrites `home_away` and `opponent`
> from master CSV before writing.**

---

## 9. Recommended next steps

Ranked by leverage. Each numbered item names the specific
function/file, the change semantics, the manifestation it addresses,
and a complexity estimate.

### 1. Input-side fix — correct the wrong DEN-MIN G3 prose (small, A=No, B=Yes)

**File:** `context/nba_season_context.md`, DEN-MIN G3 closing paragraph
(currently the last paragraph of the `##### (3) DEN vs (6) MIN`
section).

**Change:** Replace the two factually wrong sentences with their
truth-aligned counterparts:

- `must-win road game` → `must-win home game` (or, more
  defensively, `must-win G4 at home in Minneapolis`).
- `MIN will close out the series at home in G5` → `MIN will close
  out the series on the road in G5 at Denver` (or simply remove the
  `at home` qualifier and let the bracket format speak for itself).

**Addresses:** Manifestation B only. Cleanest single-edit fix.

**Complexity:** Small — one paragraph in a manually-maintained markdown
file. The fix can also be applied retroactively to similar
forward-looking claims in other series' G3 paragraphs to prevent the
same class of error in future rounds.

### 2. Input-side fix — series_context block needs an explicit "today at" line (small, A=Yes, B=Yes)

**File:** `agents/playoff_matchup.py`, `format_series_block()` (or
equivalent function that produces the per-series text in
`context_block`).

**Change:** Add a line under each series header that explicitly states
today's host for `game_today=True` series. The information is already
present — the function knows `game_in_series`, the bracket-home, and
the 2-2-1-1-1 format pattern. Emit something like:

```
=== DEN vs MIN — West | MIN leads 2-1 | GAME 4 (MID) ===
TONIGHT: Game 4 at MIN (Minneapolis). DEN on the road.
State: DEN [TRAILING] / MIN [FAVORABLE]
```

**Addresses:** Both A and B. Removes the LLM's burden of extrapolating
from format alone. Complements (does not replace) recommendation #1.

**Complexity:** Small — one new line in the series-block emitter. The
host can be derived from `nba_master.csv` for the matching `game_id`
or from the 2-2-1-1-1 lookup already implicit in the schema.

### 3. Defensive analyst-side fix — surface `is_road_game` in quant_context (small, A=Yes, B=Yes)

**Files:** `agents/quant.py` (already populates `playoff_series_state.is_road_game`
correctly per Section 3) + `agents/analyst.py:build_quant_context()`
(currently only emits `[DESPERATE_HOST_OPP]` when both is_road AND
opp_trailing≥2; needs to emit a simpler `[H]`/`[A]` tag unconditionally).

**Change:** In the player header that already reads `playoff_series_state`
at analyst.py:1872, emit `[H]` or `[A]` for every player based on
`playoff_series_state.is_road_game`. Annotation only. Existing
`[DESPERATE_HOST_OPP:...]` tag continues to fire on its current
condition.

Optional companion: add a top-level `today_is_home: bool` field to
each player_stats.json entry (one line in `quant.build_player_stats()`
that sets `today_is_home = not playoff_series_state.is_road_game`),
even though the analyst can read it through `playoff_series_state`
directly.

**Addresses:** Both A and B. Most robust because it gives the LLM a
deterministic per-player venue tag adjacent to every stat line. Even
if all other context blocks are wrong or ambiguous, the per-player
`[H]`/`[A]` tag is unambiguous and salient.

**Complexity:** Small — ~3 lines in `analyst.py:build_quant_context()`
plus ~1 line in `quant.py:build_player_stats()` if a top-level field
is added. Pattern mirrors the existing `[DESPERATE_HOST_OPP]` emit.

### 4. Output-side reconciliation — overwrite `home_away`/`opponent` from master (small, A=Yes, B=Yes)

**File:** `agents/analyst.py`, `save_picks()` post-processor chain
(already runs `filter_self_skip_picks()` → `reconcile_pick_values()`
→ `enforce_market_gate()`).

**Change:** Add a new `reconcile_game_attribution(picks)` step that
loads today's master CSV slate once, builds `{team_abbrev: {home, away}}`
(same shape as `build_team_to_game_today()` shipped to `build_site.py`
on 2026-04-25), and overwrites `pick["home_away"]` and `pick["opponent"]`
from that lookup before `picks.json` is written. Defense-in-depth —
even if the LLM produces wrong values, the persisted file is always
correct.

**Addresses:** Both A and B. Repairs the data on write so downstream
consumers (auditor, frontend, lineup_watch, lineup_update) all see the
correct values. Complementary to #1, #2, #3 — does not address the
LLM's free-text reasoning, but locks the structured fields.

**Complexity:** Small — ~25 lines, mirrors the existing
`reconcile_pick_values()` pattern. The `build_team_to_game_today()`
helper logic is already implemented in `agents/build_site.py` (shipped
2026-04-25) and can be ported across.

### 5. Reasoning text validation — observation only (out of scope for code fix)

Even with #1–#4 implemented, the LLM's free-form `reasoning` and
`tier_walk` text fields can still contain wrong venue phrasing
("must-win home game" written by the LLM about DEN even when DEN is
on the road). This affects user trust on pick cards but does not
break any structured data path. A future enhancement could add a
post-write LLM check that rewrites venue language inconsistent with
the (now-canonical) `home_away` field, but this is high cost / low
leverage relative to recommendations #1–#4 and is **NOT recommended
in the immediate fix**.

**Recommended ordering:** ship #1 (one paragraph edit, kills the
B-specific factual errors immediately), then #2 (small emitter
change, removes the inference burden across all series and rounds),
then #3 (per-player `[H]`/`[A]` tag, robust against any future input
slip), then #4 (defense-in-depth on the structured fields). #5
remains an open observation.
