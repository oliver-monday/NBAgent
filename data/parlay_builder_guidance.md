## Parlay Builder — Empirical Construction Guide

A backtest of every possible 2-5 leg parlay combination across the season's graded picks (1.05M cards from 348 graded picks) found that **no parlay archetype produces positive expected value** versus FanDuel's pricing. Even the cleanest combinations bleed 5-12% per bet long-term. Slate-correlation effects (blowouts, cold shooting nights, game-script suppression) drag combined hit rates well below independent multiplication.

If you build parlays here, build with eyes open. **Single picks are where the system has edge.** What follows is empirical guidance for users who want to build anyway.

### Best practices

- **Fewer legs = better.** Each added leg costs 5-15pp vs market expectation. L=2 cards bleed least (~5-12pp); L=5 cards bleed most (~19-25pp).
- **Stay near even money.** The Safe range (combined market 0.45-0.66, roughly +120 to -200 American odds) is the cleanest tier — bleed averages -5pp on the cleanest archetypes there. Heavy favorites (-200 and shorter) bleed harder; longer underdogs (+150 and longer) bleed harder.
- **REB-dominant cards consistently beat other prop mixes**, especially when paired with cross-game distribution. REB is least sensitive to game script.
- **At underdog odds (+120 to +230, combined market 0.30-0.45), prefer cards with ≥2 iron_floor legs.** Iron_floor concentration improves hit rates by ~14pp absolute in this range.
- **PTS-dominant only outperforms REB at heavy-favorite odds (-200 and shorter, combined market 0.66+).** Below that, REB-dominant is consistently the better play.

### What to avoid

- **AST-heavy parlays.** AST props correlate strongly to game flow — close games suppress them, blowouts suppress them. AST-dominant cards in the +120 to +230 underdog range hit 9% (priced at 40%). Catastrophic.
- **3PM-heavy parlays.** Variance is too high for parlay multiplication. 3PM-dominant cards underperform across every tier we measured.
- **All-iron-floor parlays at heavy-favorite odds (-200 and shorter).** Counterintuitively the worst archetype in the dataset (-49pp). Cap iron_floor concentration at 2 legs for L=3+ cards in this range.
- **Wide confidence dispersion at underdog odds (legs spanning 10+ confidence-percentage points).** Combines unevenly — drops hit rate to ~6% in the +120 to +230 range (-35pp).
- **Same-player concentration (3+ legs from one player).** Looks like correlation upside; in practice it's binary. The player has a great game and you sweep, or has a bad game and the whole card dies.

### Sample-size caveat

Findings are based on 21 days of playoff + late-regular-season picks. Patterns may shift as the season's pick distribution evolves. Re-validate before treating any guidance as durable.
