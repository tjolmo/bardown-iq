# Team model v2: more history, 5v5 strength, starting goalie, market benchmark

Team win model only, scored on four out-of-time test seasons (2022-23 through 2025-26). Each test season's model trains on every earlier season except the one right before it, which is held out for early stopping.
Reproduce with `python -m predictions.experiments.team_v2 --games <games csv> --train-start 2008`.

## Log loss by test season (lower is better)

| | 2022-23 | 2023-24 | 2024-25 | 2025-26 | mean |
|---|---|---|---|---|---|
| Always the home-win rate | 0.693 | 0.690 | 0.686 | 0.693 | |
| Elo only | 0.6602 | 0.6608 | 0.6674 | 0.6902 | 0.6697 |
| v1 model (trained from 2020) | – | – | 0.6661 | 0.6873 | |
| v1 features, trained from 2008 | 0.6571 | 0.6576 | 0.6629 | 0.6868 | 0.6661 |
| **v2: + 5v5 adjusted xG + projected starter (logistic)** | **0.6563** | **0.6567** | **0.6627** | **0.6842** | **0.6650** |
| same, with the *actual* starter (an upper bound for confirmed starters) | 0.6571 | 0.6563 | 0.6617 | 0.6839 | 0.6647 |
| **Betting market closing line (ESPN)** | **0.6522** | **0.6553** | **0.6582** | **0.6817** | **0.6619** |

- **More history (#1):** training from 2008 gave about 17k training games instead of 3.5–5k. It's worth about 0.002, mostly because the model gets less noisy.
- **Better strength features (#2):** 5v5 score- and venue-adjusted xG share consistently helps. Power-play/penalty-kill rates and an xG-blended Elo helped one season and hurt others, so they were dropped.
- **Starting goalie (#4):** the projected starter's shrunk GSAx/60 helps a little. The projection picks the actual starter only 65% of the time, but using the real starter improves log loss by just 0.0003 more. Scraping confirmed starters isn't worth it for the win model.
- **Model type:** with these features, logistic regression beat XGBoost and the old 50/50 blend in every fold. The production team model is now a logistic regression on 11 inputs.
- **Against the market:** the model trails the closing line by 0.001–0.005 and correlates 0.90–0.96 with it. A model+market stacker doesn't beat the market alone. The model is competitive with the market but has no edge over it.
- **Known weakness:** early in a season the model can't see offseason roster changes, though the market can. Example: on 2026-10-06 the model gave TOR–NSH 50% and the market 60%. Shrinking season-to-date stats didn't help. A roster-based team rating is the next lever.

## Data added (scratch DB `nhl_experiments`)
- **`games` back to 2008-09:** `python -m app.backfill --games-seasons 2008 ... 2019`. Relocated franchises (ATL, PHX) are handled.
- **Skater/goalie logs back to 2008:** `--seasons 2008 ... 2019`, about 1,600 historical players.
- **`team_game_stats`:** MoneyPuck team game-by-game data by situation, 2008 onward (`--team-stats-seasons`), refreshed nightly for the current season.
- **`game_odds`:** ESPN closing moneyline/total consensus, 2019 playoffs onward, refreshed nightly (`--odds START END`). Training reports the market's log loss next to the model's.
