# Team model v3: roster ratings, back-to-backs, and the market

Team win model, log loss, out of time. Each test season's model trains on every season from 2008 up to the one before it, holding that previous season out. Shared harness: `predictions/experiments/frames.py`.

| | 2022-23 | 2023-24 | 2024-25 | 2025-26 | mean |
|---|---|---|---|---|---|
| v2 (5v5 xG, projected starter, 2008+ history) | 0.6565 | 0.6568 | 0.6626 | 0.6841 | 0.6650 |
| + roster rating (previous-game lineup) | 0.6542 | 0.6538 | 0.6617 | 0.6837 | 0.6633 |
| **+ back-to-back flags (v3)** | **0.6527** | **0.6540** | **0.6606** | **0.6835** | **0.6627** |
| Market closing line | 0.6522 | 0.6553 | 0.6582 | 0.6817 | 0.6619 |

The gap to the closing line shrank from 0.0031 to 0.0008. v3 beats the close in 2023-24 and is within 0.0005 of it in 2022-23.

## What was tried

| Idea | Result | Kept? |
|---|---|---|
| **Roster rating** (`features.skater_ratings / expected_lineups / roster_ratings`): each expected skater's career game score/60 and points/60, shrunk toward his position's league rate, × expected TOI, summed over the previous game's 18 skaters; plus TOI-weighted on-ice xG%. Ratings follow players across teams, so trades and offseason moves count immediately. | −0.0017 mean, better in all four seasons. Helps most in each season's first 10 games. Using the *actual* lineup instead (a proxy for confirmed lineups) is only 0.0006 better. | yes |
| Back-to-back flags (second night, per side) | −0.0006; chosen on pre-2022 seasons, then confirmed on 2022–25 | yes |
| Travel km, time-zone shift, games in 4/7 days, road-trip length, homecoming | no gain | no (module kept in `experiments/schedule_features.py`) |
| MoneyPuck on-ice relative-xG player ratings (5v5 on/off, PP, ixG; tuned decay and shrinkage) | weaker than the simpler roster rating; nothing on top of it | no (`experiments/onice_ratings.py`) |
| Opponent-adjusted Kalman / decayed-ridge power ratings (xG, goals) | helped 2015–21 but hurt 2022–25; no stable gain | no (`experiments/power_ratings.py`) |
| Shrinking early-season stats toward longer-run form | no gain | no |

## Against the market (`experiments/market.py`, real stored prices)

- **Closing line:** the model is 0.0007 worse (CI −0.0013 to +0.0025). Combining model and market doesn't beat the market. Flat betting at closing prices is about break-even to negative below a 4% edge. **No edge against the close.**
- **Opening line** (2023-24 to 2025-26, 3,927 games): the model is 0.0016 better than the open (CI −0.0039 to +0.0009). Flat 1-unit bets at the real opening consensus price whenever the model's edge was 2% or more: **1,534 bets, +78.4 units, ROI +5.1% (95% CI +0.4% to +9.9%)**, positive in each season (+8.8%, +4.3%, +2.8%). Quarter-Kelly ROI +6.0% (CI +0.9% to +10.9%).
- **Caveats before trusting this:**
  - The roster rating and the final feature set were evaluated on these same seasons. The roster rating was planned beforehand, not tuned, and the b2b flags were selected on pre-2022 data, but some selection optimism remains.
  - That's only three seasons.
  - Since 2024-25 the stored opening price is a single book's.
  - Opening lines have low limits, and the opening price moves.
  - The honest test is a frozen model and threshold, run forward on 2026-27, tracked alongside closing-line value (does the price move toward the model's side?).

## Bugs fixed along the way
- **Live predictions dropped tonight's games after midnight UTC**, because the container's clock is in UTC. "Today" is now UTC minus 12 hours, which matches the North American game day.
- **Skater ratings shrank toward a league rate computed over all seasons**, including future games. It's now computed as of each date. (This was found by a new leakage test.)

## Data fixes
- **Corrupt consensus prices.** The consensus median of American odds across books with mixed signs gave prices like −2.5 and 0. It now takes the median on the decimal-odds scale.
- **Opening moneylines and totals are now stored** (migration `b4e8c2d17a35`), covering 2023-24 onward.
