# v4: forward-test infrastructure, standings, aging, confirmed starters

## Team win model (log loss, regular season, out of time; projected starters as in all earlier experiments)

| | 2022-23 | 2023-24 | 2024-25 | 2025-26 | mean |
|---|---|---|---|---|---|
| v3 / props-v2 model | 0.6528 | 0.6540 | 0.6606 | 0.6835 | 0.6627 |
| + clinched/eliminated flags (agent B) | | | | | 0.6621 |
| + aging curve in skater ratings (agent C) | | | | | 0.6619 |
| **v4 (all combined)** | **0.6514** | **0.6538** | **0.6586** | **0.6810** | **0.6612** |
| Market closing line | 0.6522 | 0.6553 | 0.6582 | 0.6817 | 0.6619 |

- **The model beats the closing line in 3 of 4 test seasons and on average** (−0.0007). The difference is within noise, and these seasons have been looked at many times while choosing features. That's exactly why the forward-test log below exists.
- **Playoffs:** 0.6817, against 0.6730 for the market. **March–April:** 0.6450, against 0.6440.

## What was built

| Item | Result | Status |
|---|---|---|
| **Prediction log + nightly scorer** (`predictions/prediction_log.py`) | Freezes model version, win probability, every player's expected stats, and the market price at that moment (21:00 UTC, retried at 22:00; one log per game per model version). The nightly scorer computes log loss, Poisson deviance, P(over) log loss, calibration, closing-line value and flat-stake ROI at a 2% edge. `GET /admin/model-report` or `python -m predictions.prediction_log report`. | built |
| **Price path** (migration `a1b2c3d4e5f6`) | `game_odds_snapshots` / `player_prop_snapshots` are append-only. Pre-game rows are written only before puck drop, and the closing row once per game. A new 15:00 UTC morning fetch joins the 21:00 afternoon and 03:00 nightly runs. | built |
| **Score model** (3-class, Poisson GLMs) | Didn't beat the logistic for wins (3-class 0.6628, Poisson 0.6631, vs 0.6627). The Poisson goals model's implied team goals match the market's (deviance 1.0613 vs 1.0610), so they now fill in for player models **at serve time** when no odds are stored. That improves goalie predictions on games without odds (SOG 1.5655 vs 1.5798). Totals are not priced from it (P(over) worse than a constant). | partly kept |
| **Standings** | Points %, games played and the playoff gap didn't help. **Clinched/eliminated flags did** (diff columns), helping most in March–April. | kept (flags) |
| **Age** (birth dates, migration `b2c3d4e5f6a1`) | Age/age² as skater-model features: neutral, dropped. **Aging curve in skater ratings** (within-player delta method, from earlier seasons only): team model 0.6627→0.6619, first 10 games 0.6667→0.6656. | kept (ratings) |
| **Decayed career rates** | 365-day half-life on the skater per-60 rates: SOG 1.2244/1.2265 → 1.2242/1.2248, others about neutral. In skater ratings: early-season games got worse, dropped. | kept (skater rates) |
| **Confirmed starters** (migration `c3d4e5f6a1b2`) | The NHL API has no pre-game starter field. ESPN's scoreboard has `probableStartingGoalie` (Expected / Confirmed), stored in `game_starters` as the first step of the afternoon run. Used live for the team model, opposing-goalie features and goalie predictions (`starting` flag). | built |

## Review fixes before commit
- **Scorer mixed players:** the closing-price lookup filtered by prop type only, mixing every player's quotes at that line. It now filters by player.
- **Leaky "actual starter" in training reverted:** the starter is the goalie with the most ice time, so a starter pulled early made the backup the "starter" of a game already going badly. Training uses the projection again; live uses announced starters.
- **Prediction log:**
  - Isolated per game (one failure no longer loses the day).
  - Skips skaters not in the expected lineup (scratches).
  - Rebuilds the cached context so fresh starters and odds are used.
  - Retried at 22:00 without duplicating.
- **Aging curve:** players without a birth date no longer enter the curve as 19-year-olds.

## Before merging to the real DB
- Run `alembic upgrade head` (four new migrations), then `python -m app.backfill --birth-dates`.
- The forward test starts accruing the day this is deployed. **Model version = training time plus a hash of the model files,** so nightly retraining makes a new version each day. That's fine for per-day scoring; for a strictly frozen test, pin a model file and compare it with the nightly one.
