# Props v2: new markets, better pricing, model refinements

Everything is out of time. Test seasons are 2024-25 and 2025-26 for the player models, and 2022–25 for the team model (selection on earlier seasons).

## What held up, and what didn't

| Idea | Result | Kept? |
|---|---|---|
| **Hits, blocked shots, PP points targets** (new MoneyPuck columns `hits`, `blocked_shots`, migration `e1a2b3c4d5f6`, backfilled 2008+) | Clearly beat league-mean and player-average baselines (e.g. blocks 1.115/1.092 vs 1.138/1.110 shrunk player average) | yes |
| **Negative binomial for hits and blocks** (alpha 0.12 / 0.08) | Hits are over-dispersed (var/mean 1.15–1.29). Poisson overpriced the over at 0.5 (0.629 vs 0.583 actual). Points/SOG/PP points stay Poisson. | yes |
| **Shin vig removal** (`predictions/vig.py`; also additive and power) | Lowest market log loss on every market. The old proportional split overstated juiced overs (goals P(over) 0.1745 vs 0.1516 actual; Shin gives 0.1499). | yes (benchmark default) |
| **Playoff-aware team model** (train on regular season + playoffs) | Playoff log loss 2019–25: 0.6872 → 0.6846. Regular season unchanged (0.6627). An `is_playoff` flag or recalibration was worse. | yes |
| **Deployment shares** (PP-time share, TOI rank within team and F/D, share of team SOG/xG) **+ teammate quality** (expected lineup's rating without the player) | Small but consistent: assists 0.7605→0.7601, points 0.8946→0.8940, SOG 1.2249→1.2242 (2024-25). Never worse. | yes |
| Time-varying home advantage (rolling league home-win rate; also inside Elo) | No gain (0.6627→0.6627–0.6629). Season home rates move 0.52–0.57, mostly noise. | no |
| Goalie workload (consecutive starts, starts in last 7/14 days, back-to-back) | No stable gain for team or goalie models | no |
| League-trend margin for goals/assists/points | Equal or worse (SOG keeps its margin) | no |
| Recency weighting (half-life 1.5/3/6 seasons) | Validation and test disagreed; no stable gain for skaters or goalies | no |

## Against prop prices (Shin vig removal, ESPN history, out-of-sample models)

| Market | Lines | Model vs market log loss | Flat-bet ROI at closing price (95% CI) |
|---|---|---|---|
| **Blocked shots** | 7.3k | **−0.0042 (CI −0.0071 to −0.0010)** | **+4.9% at 2%+ edge (+1.8% to +8.1%), +5.6% at 5%+**, about +5% in both seasons |
| **Hits** (negative binomial) | 2.8k | **−0.0058 (CI −0.0115 to −0.0003)** | **+6.8% at 2%+ (+1.4% to +12.1%)**, mostly 2025-26 lines |
| Saves | 3.3k | −0.0025 (CI includes 0) | +4.6% (CI +0.9% to +8.4%), almost all 2024-25 |
| Goals | 60k | tie (−0.0005); the old "edge" was the vig-removal artifact | loses |
| Points, assists | 27k each | tie | about break-even |
| Shots on goal | 6k | market slightly better (+0.0026) | about −1% |
| PP points | 18k | market better (+0.0018) | −2% to −3% |

**Reading this honestly:**
- Blocked shots is the strongest result: the most lines, significant on log loss and ROI, and steady across both seasons. That fits the view that niche markets are softer.
- Hits and saves are promising but thinner.
- These are still backtests against one book per era, with "closing" prices that are often hours before puck drop.
- The negative-binomial alpha for hits was measured on the same seasons it's scored on (some optimism).
- Next step: forward-test blocks, hits and saves with frozen thresholds on the new multi-book quote table.

## Pricing and data infrastructure
- **`odds_api_prop_quotes`** (migration `f2b3c4d5e6a7`): every bookmaker's quote from each Odds API fetch, with first-seen and last-seen prices, so future backtests price the same "best book at consensus line" the product uses. `props_benchmark --quotes` runs that backtest once data accumulates.
- **Odds API request now includes blocked shots and shots on goal.** This costs more credits per call. It's needed to price the blocks market where the model looks strongest.
- **Live props endpoint** prices with the same rates and dispersion. Skater predictions now also return `blocked_shots`, `hits` and `pp_points`.

## Review fixes and operational notes
- **Power-play points are not priced live.** MoneyPuck's PP points count 5-on-4 time only, but books settle on every power-play strength (5-on-3, 4-on-3, …), so the model would show false under edges. The benchmark's PP-points result is biased the same way.
- **Teammate-quality ratings are now saved with the skater model as well,** so live skater features don't go missing if the team model file is absent.
- **A quote-storage failure no longer looks like a failed props save.** Anytime-goal (yes/no) quotes, which have no line, now parse as 0.5. The benchmark drops pushes on whole-number lines.
- **Memory:** the new skater features first ran the 7.6 GB Docker VM out of memory during training. With float32 features and a single shared feature matrix, peak memory is now about 4.3 GB. That fits, but nightly training needs that much headroom next to the other containers. If it gets tight, training skaters from 2012 instead of 2008 is the easy lever.
