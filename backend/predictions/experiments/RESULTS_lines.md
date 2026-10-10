# Projected lines (app/line_projection.py)

`python -m predictions.experiments.line_projection_eval --season 2025`

Every team's game is projected from the games before it, then compared with what the team actually ran in that game,
read off its own shift chart the same way (its most-used trios, pairs and units). Lines are scored with the game's
real dressed lineup handed over (the NHL posts it shortly before puck drop), so only the line building counts.
"Lineup (blind)" projects the dressed skaters with no roster and no injury report (neither is stored
historically), so the live projection, which drops players ESPN lists out, does better.

* **F lines exact**: actual forward trios projected exactly. **F pairs kept**: of every two forwards on the same
  actual line, the share projected on one line.
* **D pairs exact**: actual defense pairs projected exactly.
* **PP1 / PK1 players**: players shared by the projected and actual first units.
* **last game**: copy the previous game's lines (the baseline). **decay d**: the last six games, each weighing d
  times the one after it. **flat n**: the last n games equally.

## 2025-26 regular season (2,560 team-games, 1,312 games, every shift chart present)

| setting | F lines exact | F pairs kept | D pairs exact | PP1 players | PK1 players | lineup (blind) |
|---|---|---|---|---|---|---|
| last game | 66.5% | 76.2% | 82.5% | 82.6% | 59.0% | 94.1% |
| decay 0.3 | 66.4% | 76.1% | 82.8% | 84.6% | 62.0% | 94.1% |
| **decay 0.5** (live) | **66.7%** | **76.3%** | **83.0%** | **85.3%** | 64.0% | 94.1% |
| decay 0.7 | 62.7% | 73.4% | 81.6% | 85.1% | 65.1% | 94.1% |
| flat 3 | 59.6% | 71.1% | 80.4% | 84.4% | 64.3% | 94.1% |
| flat 6 | 53.1% | 66.3% | 77.1% | 83.6% | 65.2% | 94.1% |

## 2026-27 so far (74 team-games, as of Oct 10 2026)

| setting | F lines exact | F pairs kept | D pairs exact | PP1 players | PK1 players | lineup (blind) |
|---|---|---|---|---|---|---|
| last game | 62.5% | 73.4% | 85.6% | 90.3% | 55.2% | 95.1% |
| **decay 0.5** (live) | 62.9% | 73.3% | 83.3% | 88.5% | 61.3% | 95.1% |

## Takeaways

* Even-strength lines are mostly "what the coach did last game": a decay of 0.5 matches copying the last game on
  forward lines and defense pairs and never trails it by much, while longer memories (decay 0.7, flat windows) lose
  up to 13 points of exact lines, since coaches reshuffle lines often and the latest change is the one that sticks.
* Special teams are steadier than one game shows: one game's power play is a small sample (a team may get one
  short power play), so pooling recent games helps (PP1 +2.7 points, PK1 +5.0 over the last game alone).
* A ceiling: about a third of forward lines change from one game to the next, which no projection from past
  deployment can see coming. Once the NHL posts the lineup, the dressed players are certain; the lines stay
  projected until the game starts.
* An earlier version brought back any regular who had missed the last game, which also undid healthy scratches:
  blind lineup accuracy was 88.5%. Bringing back only players returning from the injury report raised it to 94.1%
  (the backtest has no injury history, so there the rule never fires).
