# Model rework: results

Everything below is **out of time**. Models train on earlier seasons, early-stop on the next season, and are scored on a later season they never saw.
There are two folds: test 2024-25 (train 2020–22, early-stop 2023) and test 2025-26 (train 2020–23, early-stop 2024).
Reproduce with `python -m predictions.experiments.compare --fold test_2025` (see the module docstring for the data files it needs).

"Current" means the original setup, retrained on the same rows and splits: rolling-5 features, Tweedie regressors and separate classifiers.

## Team win probability (log loss, lower is better)

| | test 2024-25 | test 2025-26 |
|---|---|---|
| Always the home-win rate | 0.6870 | 0.6924 |
| Current model | 0.6808 | 0.6929 (worse than the home rate) |
| Elo only | 0.6672 | 0.6912 |
| **New: XGBoost + logistic blend** | **0.6653** (AUC 0.620) | **0.6870** (AUC 0.573) |

The current model's label (skater goals vs. the starting goalie's goals against) is wrong for 4.8–7.4% of games. It misses shootouts, empty-net goals and goals allowed by a relief goalie. The new label comes from the final score.
2025-26 was an unusually unpredictable season: even a tuned Elo scores 0.660 on 2021–24 but 0.691 there.

## Skaters (Poisson deviance, lower is better; test 2025-26, with 2024-25 in parentheses)

| | goals | assists | points |
|---|---|---|---|
| Player's season average | 0.794 | 0.951 | 1.059 |
| Simple rule: shrunk career rate × expected TOI | 0.589 (0.577) | 0.776 (0.770) | 0.917 (0.908) |
| Current model | 0.598 (0.587) | 0.783 (0.776) | 0.931 (0.919) |
| **New Poisson model** | **0.584 (0.573)** | **0.770 (0.762)** | **0.910 (0.897)** |

- The current models lose to the one-line rule on every stat.
- For P(at least one), goal AUC improves from 0.688 to 0.706, and log loss improves on every stat. Calibration is within about 1 point in every decile.
- The current goal classifier gave a higher scoring chance than the regressor's expected goals in 8.5–11.9% of rows. That can't happen when the probability comes from the same Poisson model (P(≥1) = 1 − e^(−λ)).
- Power-play TOI and shots on goal improved deviance by at most 0.001, because career rates already capture PP usage. They were left out so no schema migration is needed.

## Goalies, starters only (Poisson deviance; test 2025-26, with 2024-25 in parentheses)

| | goals against | shots on goal against |
|---|---|---|
| League mean | 0.919 (0.995) | 1.993 (1.894) |
| Current model | 0.918 (0.989) | 1.873 (1.814) |
| **New** | **0.903 (0.983)** | **1.583 (1.571)**, with the league-trend base margin |

League shots per game fell from about 30.5 (2021) to 27.2 (2025). The trend margin lets the shots model follow that drift, which cuts error by about 15% versus the current model. Goals against didn't drift, and the margin made it slightly worse, so goals against is trained without it.

## Data problems found along the way
- The zip scraper opened `{season}.csv`, but the 2020–24 archives store the file under a nested path, so backfills of past seasons silently failed. The DB was missing about 30% of 2020–22 skater rows and about 60–70% of 2020–22 goalie rows. This is fixed in `external/moneypuck/player.py`, and `python -m app.backfill --seasons 2020 ... 2025` refills them.
- The old incremental feature SQL filtered rows before running its window functions, so nightly runs dropped new games. All features are now computed in `predictions/features.py` from the raw logs, and that same code is used for training and live predictions.
