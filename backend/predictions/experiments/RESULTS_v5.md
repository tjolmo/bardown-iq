# v5

## 1. Historical starters from play-by-play

**Who started every game since 2008 is now stored** (`game_starters`, source `nhl`, status `actual`; 23,249 finished regular-season and playoff games, both teams in every one). Training uses these instead of "the goalie with the most ice time". That stand-in names the reliever whenever a starter is pulled, which happened in 3–4% of team-games.

The goalie model gets better on the rows saves props settle on. The win model and the skater models don't move. Even knowing the starter for certain adds nothing measurable to the win model.

### Sources and coverage

| | |
|---|---|
| Play-by-play `goalieInNetId` on shot events | Present in every season back to 2008-09. That season lists only shots on goal and goals, with no missed shots, which is enough. Empty-net shots carry no goalie and are skipped. Shootout attempts are ignored. |
| Boxscore `starter` flag | Present on finished games in every season back to 2008. The old comment in `games.py` said there was none, but it only appears once the game is final. |
| Agreement | The two sources disagreed on **5 of 46,498** team-games. Twice the starter left hurt before facing a shot (Francouz after 0:31, Rask after 1:12): the flag is right, and the play-by-play names the reliever. Three times the flag sat on the reliever of a starter pulled after 10–16 minutes (Vanecek, and Hellebuyck twice): the play-by-play is right. **Rule:** use the first shot faced, unless the flagged goalie played but faced no shots. |
| Coverage | 100% of games have both starters, in every season 2008-09 through 2026-27 so far. There were no fetch failures and no play-by-play fallbacks. |

| Season | 08 | 09 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Most-ice-time goalie ≠ starter | 3.8% | 4.0% | 4.1% | 4.2% | 4.4% | 3.8% | 3.9% | 3.7% | 3.6% | 4.3% | 3.5% | 3.0% | 3.1% | 3.1% | 2.7% | 3.8% | 2.7% | 2.8% |
| Projection right (v4 history) | 70.0% | 69.4% | 68.4% | 69.5% | 68.0% | 67.7% | 71.1% | 69.5% | 69.8% | 69.7% | 68.2% | 66.5% | 60.5% | 63.7% | 63.6% | 66.4% | 67.1% | 65.7% |
| Projection right (true-starter history) | 70.4% | 70.0% | 68.4% | 68.9% | 68.8% | 67.0% | 71.7% | 69.1% | 70.3% | 70.9% | 68.0% | 65.5% | 60.1% | 63.6% | 63.4% | 66.1% | 67.3% | 65.1% |

Counting the projection's "last 10 starts" from true starters doesn't make it more accurate: it ranges ±1 point by season with no net change. The two projections disagree mostly when a starter was pulled, and the team usually goes back to him next game anyway.

### Team win model (log loss, regular season, out of time)

Every row uses the same games and the same v4 features. Only the goalie behind `diff_starter_gsax60` changes. "Train" is what the model learned from; "test" is what it was given for the test games.

| Train / test | 2022-23 | 2023-24 | 2024-25 | 2025-26 | mean | Playoffs |
|---|---|---|---|---|---|---|
| **v4:** projected (most-TOI history) / projected | 0.6514 | 0.6538 | 0.6586 | 0.6810 | 0.6612 | 0.6754 |
| Projected (true history) / projected (true history) | 0.6513 | 0.6539 | 0.6587 | 0.6811 | 0.6612 | 0.6754 |
| **Actual / actual** (starter known before the game) | 0.6517 | 0.6539 | 0.6583 | 0.6810 | 0.6612 | 0.6754 |
| **Actual / projected** (starter not announced) | 0.6513 | 0.6535 | 0.6587 | 0.6811 | 0.6612 | 0.6754 |
| Projected / actual | 0.6517 | 0.6540 | 0.6584 | 0.6810 | 0.6613 | 0.6755 |
| Market closing line | 0.6522 | 0.6553 | 0.6582 | 0.6817 | 0.6619 | 0.6699 |

- **Knowing the starter is worth nothing to the win model as built.** Train on the actual starter and test with him (the upper bound, roughly what confirmed starters give live): 0.6612, the same as projected/projected. So the eval with true starters doesn't overstate anything here, because there's no gain to overstate. The starter's shrunk GSAx/60 is a weak signal next to the team-level GSAx and xG features.
- I also tried features that only a known starter makes possible. All were trained and tested with actual starters:

| Feature | Mean log loss |
|---|---|
| Backup flag (starter ≠ projected) | 0.6615 |
| Starter's share of the last 10 starts | 0.6615 |
| Both | 0.6615 |
| GSAx prior 10 h | 0.6613 |
| GSAx prior 50 h | 0.6612 |

  None helped. The market moves on backup starts; this model can't find that signal in public goalie stats.
- **Adopted:** training on actual starters (`TRAIN_ON_ACTUAL_STARTERS = True`). It's no better and no worse in either test mode. It's adopted because live predictions use ESPN confirmed/expected starters whenever they're announced, so training now matches serving, and without the v4 leak.

### Goalie model (Poisson deviance on true-starter rows, 2022-23 .. 2025-26 mean)

Scored on the actual starter's full game, pulled or not, which is how saves props settle. Production parameters, three seeds averaged. Bias is mean predicted minus mean actual, per game.

| Training rows | Goals against | Shots against | Saves | Saves bias | SOG bias |
|---|---|---|---|---|---|
| v4: most ice time | **0.9270** | 1.9216 | 2.1904 | +0.53 | +0.60 |
| True starters | 0.9276 | **1.9163** | **2.1852** | **+0.19** | **+0.30** |

Per season, saves deviance:

| Training rows | 2022-23 | 2023-24 | 2024-25 | 2025-26 |
|---|---|---|---|---|
| v4 | 2.2503 | 2.3265 | 2.0811 | 2.1037 |
| True starters | 2.2596 | 2.2923 | 2.0777 | 2.1111 |

- **True-starter rows win on saves and SOG** (−0.005 deviance) **and cut the over-prediction for the starter by about two thirds** (saves +0.53 → +0.19 per game). The v4 model had never seen a pulled starter's short game, so it priced every starter as if he'd play 60 minutes.
- The per-season deviance is mixed (better in 2 of 4 seasons), but the bias drop holds in every season. For over/under pricing the bias matters more.
- Goals against is flat (+0.0006, within seed noise).
- The opposing goalie used for context (projected vs actual) makes no difference for goalie models (±0.0004).
- **Adopted** for all three targets: `_fit_goalies` keeps `F.starter_rows(df, known)`. A pulled starter counts as the starter; his reliever doesn't.
- On v4's own evaluation rows (most ice time), the new model looks worse: saves 1.7780 → 1.7853. That's expected: it now predicts some starters get pulled, while those rows contain only the goalies who finished.

### Skater models (opponent starter quality, `opp_starter_gsax60`; Poisson deviance, fast settings)

| Train / test | Goals 24-25 | Goals 25-26 | SOG 24-25 | SOG 25-26 | Points 24-25 | Points 25-26 |
|---|---|---|---|---|---|---|
| Projected / projected (v4) | 0.5716 | 0.5832 | 1.2242 | 1.2246 | 0.8943 | 0.9056 |
| Projected / actual | 0.5716 | 0.5831 | 1.2242 | 1.2245 | 0.8941 | 0.9055 |
| Actual / projected | 0.5717 | 0.5831 | 1.2240 | 1.2246 | 0.8944 | 0.9057 |
| Actual / actual | 0.5716 | 0.5831 | 1.2240 | 1.2246 | 0.8942 | 0.9057 |

Neutral (±0.0002). Skater models follow the team setting (actual starters in training).

### What was built

| Item | Status |
|---|---|
| **Parsers** (`external/nhl/games.py`): `parse_boxscore_starters` and `parse_actual_starters`. `parse_pbp_starters` now skips shootout attempts. | built |
| **Storage:** migration `d4e5f6a1b2c3`. `game_starters` is keyed on `(game_id, team, source)`, so the ESPN pre-game pick (`espn`: probable/confirmed) and the actual starter (`nhl`: actual) are both kept. Neither overwrites the other, so ESPN's accuracy can be measured later. Rows written by the old in-progress play-by-play path (`nhl_pbp` / confirmed) become `nhl` / actual. | built |
| **Backfill:** `python -m app.backfill --actual-starters [--starter-seasons 2008 2025] [--starters-log FILE]`. It's resumable: it only fetches finished games without both starters and commits every 200 games. It runs 4 games at a time (boxscore + play-by-play each) through the retrying shared client. Took about 75 min for 2008–2026. | built, run on `nhl_experiments` |
| **Nightly / full refresh:** new "actual starters" step before training, which fills any finished game this season that's missing them (at most 400 per run). The afternoon starters step now stores in-progress play-by-play starters as `nhl` / actual. | built |
| **Features:** `starter_picks` has three layers. The projection is learned from true starters. ESPN confirmed/probable starters override it. With `prefer_actual`, the true starter overrides that, and the most-ice-time goalie is never used. Helpers `most_ice_time`, `true_starters`, `actual_starters` and `starter_rows` replace the old `actual_starters` (most TOI). | built |
| **Live serving:** unchanged in spirit. ESPN confirmed/expected starter, else the projection; the actual starter once a game is under way. | |

### Before merging to the real DB
- Run `alembic upgrade head` (includes `d4e5f6a1b2c3`), then `python -m app.backfill --actual-starters`. That's about 23k games and 75 minutes. Without it, training falls back to the most-ice-time goalie and the old projection.
