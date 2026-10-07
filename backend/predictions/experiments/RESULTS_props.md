# Player props: data, model changes, and the market

## Data added (scratch DB `nhl_experiments`)
- **`player_prop_odds`** (migration `d6b2e4f8a012`): 391k ESPN prop markets.
  - **Coverage:** Feb 2024 to now, one book per era (ESPN BET to Dec 2025, DraftKings after). Dec 2025–Apr 2026 is mostly missing (about 100 of 1,000 games). ESPN posts player props only on game day.
  - **Prop types:** points, assists, goals, shots on goal, saves, PP points, blocked shots and hits (over/under); anytime/first/last goal (one-sided); DraftKings "N+" ladders.
  - **Prices:** current (last pre-game) and opening, including when the opening line differs.
  - **Matching:** 98% of ESPN athletes are matched to NHL player ids.
  - **DraftKings over/under:** the sides are unlabeled; they're inferred from row order and checked three ways.
  - Backfill: `python -m app.backfill --props START END`.
- **`skater_game_logs` new columns** (migration `c5a1d3e7f901`): `shots_on_goal`, `pp_toi`, `pp_points`, backfilled 2008 onward. Summed skater shots match the opposing goalies' shots faced within 1 shot in 98.9% of team-games.
- **New scheduled job:** an afternoon (21:00 UTC) refresh of game odds and player props, so pre-game prices are captured every day. The 3am nightly run only sees finished games.

## Model changes (out of time: test 2024-25 and 2025-26; Poisson deviance)

| | goals | assists | points | shots on goal |
|---|---|---|---|---|
| current skater model | 0.5776 | 0.7651 | 0.9016 | 1.2520 (new target) |
| + market-implied team goals, opposing starter | 0.5778 | 0.7650 | 0.9015 | 1.2534 |
| + recent shots / PP TOI / PP points history | 0.5774 | 0.7642 | 0.9007 | 1.2396 |
| + league-trend base margin (shots only) | – | – | – | **1.2261** |

| goalie (starters) | goals against | shots against | saves |
|---|---|---|---|
| current | 0.9414 | 1.5732 | 1.7401 |
| **+ market-implied goals, opposing context** | **0.9396** | **1.5587** | **1.7269** |

- **Market context:** it barely matters for skaters, but it improves goalies by about 1% on shots and saves.
- **Saves:** now its own model, trained on saves directly, instead of shots minus goals.
- **Shots on goal:** league shots per skater fell about 10% in 2024–25. Without the trend margin the model overpredicted shots by 10%, and so overpriced every over.
- **Distribution:** a negative binomial (allowing extra spread) did worse than Poisson for SOG/points probabilities, so Poisson stays.

## Against prop prices (out-of-sample model, ESPN prices)

| Market (two-sided) | Lines | Model vs market log loss | Betting |
|---|---|---|---|
| Points | 27k | tie (+0.0002, CI ±0.001) | about break-even |
| Assists | 27k | tie (−0.0009, CI includes 0) | about break-even |
| Shots on goal | 6k | market slightly better (+0.0026, CI −0.0001 to +0.0053) | −1% at close, +1% at open (CIs include 0) |
| Goals | 60k | model −0.0040 (significant), but this comes from juiced overs distorting the vig-free market probability | loses at close (about −4%) |
| **Saves** | 3.3k | model −0.0025 (CI includes 0) | **+4.6% to +7.6% ROI at close, CI excludes 0**, but mostly from 2024-25 (2025-26 about 0) |

**Bottom line:** the skater models are now about as good as the book's lines on points, assists and shots, which makes them a fair reference, but they have no betting edge. Goalie saves is the one candidate edge. It has too few lines and is too concentrated in one season to claim. Forward-test it: freeze the model and a 2–5% threshold, then log pre-game picks with the afternoon prop snapshot.

## Product
- `GET /players/props/{player_id}` now returns `model_prob` (the model's chance that side wins) and `edge` (expected return per unit at the listed odds) for each prop, using the same Poisson rates.
- Skater predictions include expected `shots_on_goal`. Goalie saves come from the direct saves model.
