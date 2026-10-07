# v5: model improvements

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

## 2. Injuries feed for expected lineups

The roster rating's expected lineup is the team's previous game's 18 skaters, so it learns of an injury one game late. ESPN's league-wide injury report is known before the game. Players it lists out are now dropped from upcoming games' expected lineups before the afternoon log.

### The feed (`external/espn/injuries.py`, table `player_injuries`, migration `e5f6a1b2c3d4`)
- **Source:** `site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries` is one request for the whole league, with teams that have no injuries left out. On 2026-10-07 it listed 117 players: 92 IR, 16 day-to-day, 9 out.
- **Fields:**
  - `status`: Injured Reserve / Out / Day-To-Day.
  - `details.fantasyStatus`: IR, IR-NR, IR-LT (LTIR), OUT, Day-To-Day.
  - `details.type`: the body part, or Suspension (listed as IR-NR), Contract Dispute or Personal.
  - `details.returnDate`: ESPN's estimate.
  - `date`: when the entry was last updated, not when the injury happened.
  - The athlete's ESPN roster status: active / minors / injured.
  - The ESPN athlete id appears only in the athlete's links and uid.
- **Normalized status:** `out`, `ir`, `ltir`, `suspended` or `day_to_day`.
- **No history:** resolved injuries vanish. The per-athlete core API (`sports.core.api.espn.com/.../seasons/YYYY/athletes/ID/injuries`) returns only open entries; past seasons come back empty. Old game summaries show *today's* report. **The stored snapshots are the only record of what was known pre-game.**
- **Matching to NHL ids:**
  - ESPN ids already paired in `player_prop_odds` are used first.
  - Otherwise the name, with goalie/skater agreeing: an exact or loose name ("Sam"/"Samuel") on the listed team, else the only exact namesake in the league.
  - Players on IR are dropped from the NHL roster endpoint (`current_team` NULL), so that last step matters.
  - Live: 101/117 matched. The 16 unmatched are prospects not in `players`, mostly ESPN "minors", who aren't in any lineup.
- **Storage:** `player_injuries` is append-only, one full snapshot per fetch with `fetched_at`.
- **Schedule:** fetched as a step of the 15:00 morning run and of the 21:00/22:00 afternoon run, after starting goalies and before odds and the prediction log.

### Live use (`features.listed_out / drop_listed_out / replace_out_starters`, `predict._build_context`)
- **Which listings count:**
  - out / IR / LTIR / suspended drop the player. **Day-to-day players are kept** (most play).
  - **Stale listings are ignored:** a player seen playing on a later game day than the entry's last update is back, even if ESPN hasn't cleared him. An injury in last night's game is reported after it, on the same game day, so it still counts.
- **Which games a listing covers:** games up to the day before ESPN's estimated return, and always at least tonight. A listing with no date covers a week. For example, Hellebuyck's suspension (return 10-17) doesn't reach November games.
- **Replacement:** each dropped skater is replaced by the healthy, rostered skater of his position group (F/D) with the most expected ice time who isn't already in the lineup. If there is none, the lineup stays at 17.
- **Goalies:** a *projected* starter who is listed out gives way to the team's healthy rostered goalie with the most recent starts. ESPN-confirmed starters are left alone.
- **What follows the adjusted lineups:** the same lineups feed the team model's roster rating, every skater's teammate quality (the injured player's teammates lose his rating, and his replacement gains it), and the prediction log's expected-dressing set.
  - The log skips listed-out skaters (`skaters_listed_out`) and now logs the replacement.
  - The summary records which report was used (`injury_report_at`).
- **Share features are unchanged.** They are each player's own prior-game shares, in training and live alike.
- **Only upcoming games are touched.** Training and played games keep previous-game lineups. There is no historical report, so **nothing is retrained.**
- **Graceful degradation (tested live):**
  - ESPN unreachable or a bad payload: nothing is written.
  - Predictions keep using the last report up to 36 hours old, then fall back to exactly the old behaviour.
  - A missing table is caught like `game_starters`.
- **On 2026-10-07's slate:** 85 players were listed out after the stale and horizon filters. Win probabilities moved on about a third of games, by up to 0.024 (MTL without Demidov: 0.688 → 0.664).

### How big is the problem (2022-23 to 2025-26 regular seasons, 10,496 team-games, production lineups)
| | |
|---|---|
| Expected skaters who didn't play | 5.5% of lineup slots, 0.99 per team-game |
| Team-games with ≥1 / a regular (top-9 F, top-4 D) missing | 66% / 30% |
| Share of expected roster game score that didn't play | 3.9% |
| Misses that are one game only (scratch, late scratch) | 31% |
| Misses that start a 2+ game absence (what a report would plausibly list) | 69% (18% the rest of the season) |
| Skaters who played but weren't expected (returns, call-ups) | 0.99 per team-game |

**Model vs closing line, by game:**
- On games where a regular's absence starts (the roster rating still counts him), the model is level with the close: +0.0001.
- On the other games it beats the close by 0.0015.
- So the market's edge sits in exactly the games where lineup news is fresh.

### Proxy backtest (`experiments/injury_eval.py`)
The real feed can't be backtested. As a proxy, the backtest drops the absences a report would plausibly have listed, using the live code. Each team-game's replacement pool is the skaters who played for the team in its previous 10 games. The models are trained on production lineups, which is how the live change runs.

| Test-time lineup | 2022-23 | 2023-24 | 2024-25 | 2025-26 | mean |
|---|---|---|---|---|---|
| Previous game (production) | 0.6514 | 0.6538 | 0.6586 | 0.6810 | 0.6612 |
| **Drop regulars out 2+ games, fill** (closest to an injury report) | 0.6515 | 0.6532 | 0.6575 | 0.6802 | **0.6606** |
| Same, no fill (17 skaters) | 0.6516 | 0.6532 | 0.6583 | 0.6811 | 0.6611 |
| Drop anyone out 2+ games, fill | 0.6514 | 0.6534 | 0.6566 | 0.6794 | 0.6602 |
| Drop every miss, fill | 0.6515 | 0.6542 | 0.6565 | 0.6803 | 0.6606 |
| Actual lineup (ceiling) | 0.6519 | 0.6534 | 0.6569 | 0.6808 | 0.6607 |
| Market closing line | 0.6522 | 0.6553 | 0.6582 | 0.6817 | 0.6619 |

- **The conservative proxy is worth about −0.0006,** helping in 3 of 4 seasons. That's the same size as RESULTS_v3's "actual lineup" gain, and well inside noise.
- **Replacing the dropped player matters.** Without a replacement, most of the gain disappears, because a 17-man roster rating understates the team.
- **"Drop anyone 2+"** (−0.0010) includes multi-game healthy scratches, which ESPN doesn't list, so treat it as an upper bound.
- **The proxy is optimistic** in assuming every multi-game absence is announced before the first game. It is pessimistic in ignoring single-game injuries that are announced. **The live benefit needs the forward test:** `prediction_log` now records which report each log used, and `player_injuries` keeps every snapshot, so the injury report can be backtested properly from this season on.

### Not done / risks
- **Returning players aren't added back.** That is about 1 per team-game, the mirror of the problem above. A player who drops off the report and was on IR could be re-inserted; that's the natural next step once snapshots accrue.
- **Replacements come from the NHL roster.** When a team has no healthy extra (e.g. CHI on 10-08), the lineup stays short until the call-up's first game.
- **ESPN's return dates are rough.** Day-to-day entries often just say "tomorrow", and IR-NR entries often say "in 3 days". That is why only the out statuses act on them, and tonight is always covered.
- **Volume:** about 120 rows per fetch × 3 fetches a day. Small, but there is no pruning.

## 4. Out-of-sample dispersion

The negative-binomial alphas that price hits and blocks (0.12 / 0.08) were set by hand on the same test seasons they were scored on. Training now fits alpha for every count target from the validation split, using maximum likelihood of the NB2 (variance = mu(1 + alpha mu)) on the validation model's predictions. The alphas are saved in the skater and goalie bundles and in `metrics.json`, so they refresh with the nightly retrain (`predictions/dispersion.py`).

**The rule:**
- Alpha is clamped to [0, 1].
- A target is priced as a negative binomial only if that beats the Poisson by at least 0.0005 nats per row of validation log likelihood. Otherwise it stays Poisson (alpha 0).
- Method of moments is reported next to the MLE as a cross-check.

**Fitted alphas:**

| Target | Old (hand-set) | Nightly (validation 2024–26) | Out of sample, fold → 2024-25 / 2025-26 | Fit on the test season itself ("oracle") | Moments (nightly) |
|---|---|---|---|---|---|
| Hits | 0.12 | **0.131** | 0.142 / 0.137 | 0.138 / 0.106 | 0.090 |
| Blocked shots | 0.08 | **0.087** | 0.089 / 0.088 | 0.090 / 0.084 | 0.078 |
| Skater SOG | 0 | **0.054** | 0.048 / 0.058 | 0.059 / 0.060 | 0.038 |
| Goalie saves | 0 | **0.030** | 0.029 / 0.029 | 0.029 / 0.029 | 0.027 |
| Goalie SOG against | 0 | **0.021** | 0.020 / 0.020 | 0.020 / 0.020 | 0.019 |
| Goals, assists, points, PP points, goals against | 0 | 0 | 0 | 0 | 0 |

- **Goals, assists, points and PP points are under-dispersed** given their mean, which is expected for counts that are mostly 0/1. The likelihood peaks at alpha 0, so they stay Poisson. Nothing changed for them.
- **Moments come in lower than the MLE for hits.** The moment estimate is driven by a few large squared residuals and is noisier from season to season (0.068–0.099), so pricing uses the MLE.

**Test-season scoring** (`experiments/dispersion_eval.py`). The setup:
- `props_models` folds: train on seasons before the validation season, early-stop on it, and fit alpha on the same season. The test season is never used.
- Every skater-game is scored, about 47k per season.
- "P(over) near-mean" is the log loss at the half-point line nearest each player's mean, which is where books put their lines.

| | Poisson | Old alphas | **Fitted out of sample** | Oracle |
|---|---|---|---|---|
| Hits, log lik/row 2024-25 / 2025-26 | −1.34760 / −1.29610 | −1.34052 / −1.29188 | **−1.34044 / −1.29208** | −1.34043 / −1.29183 |
| Hits, P(over) near-mean | 0.65658 / 0.65112 | 0.65492 / 0.64950 | **0.65471 / 0.64935** | 0.65474 / 0.64964 |
| Blocks, P(over) near-mean | 0.65723 / 0.65018 | 0.65695 / 0.64965 | **0.65694 / 0.64961** | 0.65694 / 0.64963 |
| SOG, P(over) near-mean | 0.66209 / 0.66711 | (Poisson) | **0.66150 / 0.66708** | 0.66139 / 0.66708 |
| Goalie saves, P(over) near-mean (2.6k rows/season) | 0.69196 / 0.69359 | (Poisson) | 0.69132 / 0.69412 | 0.69132 / 0.69413 |

**Against prop prices** (`props_benchmark`, Shin vig removal, ESPN history, 2024-25 + 2025-26):

| Market | Lines | Model − market log loss: Poisson / old / **fitted** | Flat-bet ROI at 2%+ edge: Poisson / old / **fitted** (95% CI for fitted) |
|---|---|---|---|
| **Hits** | 2.8k | −0.0045 / −0.0063 / **−0.0064** (CI −0.0119 to −0.0007) | +3.5% / +7.7% / **+7.8%** (+2.5% to +13.1%) |
| **Blocked shots** | 7.3k | −0.0033 / −0.0044 / **−0.0044** (CI −0.0074 to −0.0014) | +4.4% / +4.8% / **+4.9%** (+1.6% to +8.0%); 2025-26 +1.9% → +3.5% |
| Saves | 3.3k | −0.0025 / (Poisson) / **−0.0045** (CI −0.0094 to +0.0006) | +5.1% / (Poisson) / **+6.7%** (+2.4% to +11.0%); still about 0 in 2025-26 |
| Shots on goal | 6.1k | +0.0015 / (Poisson) / +0.0013 | −0.7% / (Poisson) / −2.7% |

**Reading this honestly:**
- **The fitted alphas match the hand-set ones where those existed, and the market edge holds without the in-sample choice.** Hits and blocks with out-of-sample alphas are as good as the old values on log loss and ROI. The hits edge over the market (−0.0064, CI excluding 0) no longer depends on an alpha picked on those seasons.
- **The selection optimism in the old values is real but small.** The old hits alpha of 0.12 sits between the two test seasons' own optima (0.138, 0.106), which is what tuning on them would produce. Out of sample, 2025-26 wanted 0.137 against its oracle of 0.106. That cost 0.0002 nats per row of likelihood against the old value, and P(over) and market results are unchanged. Hits dispersion moves from season to season (scorer and arena effects), and a nightly refit tracks that better than a constant.
- **Goalie saves are clearly over-dispersed** (alpha 0.03 at about 25 saves makes the variance 1.75× the Poisson's) and were priced as Poisson until now. On market lines the NB improves log loss by 0.0020, and ROI rises at the 2% edge. The model was overpricing the over in its top fifth (0.614 predicted vs 0.552 actual; with the NB, 0.573). The near-mean scores on the 2.6k-row eval split one season each way, which is noise at that size. The market comparison is what supports it.
- **SOG is a wash, and it's the one to watch.** The NB is slightly better on the all-player likelihood and P(over) in both seasons, and on market log loss (+0.0015 → +0.0013). But it shifts the mean P(over) on market lines from 0.517 to 0.506, against an actual rate of 0.516. Flat-bet ROI drops from −0.7% to −2.7%. That isn't enough to override the validation rule, and the market beats the model on SOG either way, so it isn't a betting market. If SOG ever gets bet, revisit this.
- **No target got worse on P(over) log loss out of sample, so no NB target was restricted by hand.** The 0.0005-nat gate keeps every 0/1-type stat on the Poisson.

**What changed:**
- `_fit_count_models` fits `fit_alpha(y, mu)` on the validation predictions. It runs in both the nightly `train_models` job and `python -m predictions.train`, with no extra model fits.
- `predict.prop_dispersion()` reads the bundles. It is used by the live props endpoint and by the prediction-log scorer (through `prop_probability`).
- `config.PROP_DISPERSION` is now only the fallback for bundles trained before this change.
- `props_models` saves the per-fold alpha. `props_benchmark --fitted-alpha` prices with it.

**Caveats:**
- **The validation predictions come from the early-stopped model.** The number of trees was chosen on the same rows, which slightly understates residual variance. The served model is refit on all games, which leaves slightly less. The two effects run in opposite directions, and both are small.
- **The prediction-log scorer prices old logs with the current bundle's alphas.** The log stores expected values, not alphas. Nightly alphas move in the third decimal place, so this barely matters. A strictly frozen forward test should pin the bundle, as noted in v4.

## 6. Precomputed deployment shares

The share features (PP share, ice-time rank, shot and xG share) need every skater of a player's past games, so each skater prediction loaded about 40 rows per career game. The afternoon log does this for every expected skater on the slate. **Measured first:** dry run of the afternoon log (`predictions/experiments/shares_benchmark.py`: commits become flushes, rolled back at the end) for 2026-10-08 (10 games, 359 skaters, 44 goalies, 2,573 player rows) in `nhl_experiments`. Profiled with cProfile.

| | v4 | fallback only (no table) | **v5** |
|---|---|---|---|
| Afternoon log, wall | 115.9 s | 80.1 s | **53.9 s** |
| `predict_skater` in the log, median | 257 ms | 160 ms | **94 ms** |
| … teammates' logs + `skater_shares` | 43.7 s | 40.5 s | — |
| … stored shares lookup | — | — | 4.9 s (9 ms median) |
| … player's own logs (`load_skater_logs`) | 34.1 s | 3.2 s | 4.0 s |
| … `skater_features` | 20.6 s | 15.3 s | 21.3 s |
| Single prediction (API path, context warm, 40 skaters), median / max | 304 / 1490 ms | 128 / 355 ms | **72 / 131 ms** |

"Fallback only" is the v5 code with the table hidden: the index and the lineup cut, but shares still computed from every teammate's logs.

- **The teammate load was 37% of the log** (43.7 of 115.9 s). It was also the slowest part of a veteran's prediction: up to 1.4 s for a ~1,000-game career.
- **A second cost the task didn't name:** `skater_game_logs` had no index on `player_id`, only the `(game_id, player_id)` primary key. Loading one player's own history was a parallel sequential scan of 779k rows (~80–90 ms, up to 0.9 s under load), 29% of the log. A plain index fixes it (~5 ms).
- **What remains is compute, not I/O.** In the v5 profile, `skater_features` (pandas, ~45 ms a skater) and xgboost's pandas-to-DMatrix conversion on 7 single-row predicts per skater (~21 s) take most of the time, plus the 9–12 s team context build. Batching all of a slate's skaters into one frame would be the next step; it isn't done here.
- Timings share the Docker VM with the other v5 agents' jobs, so expect about ±15% between runs. The v4 run had no index yet; the other two ran after it was built.

### What was built

| Item | Detail |
|---|---|
| `skater_game_shares` (migration `f6a1b2c3d4e5`) | One row per (player, game): the 4 per-game values of `features.skater_shares`. PK `(player_id, game_id)` plus an index on `game_id`. The migration also adds `ix_skater_game_logs_player_id`. |
| `predictions/shares.py` | `refresh_skater_shares` rewrites whole games, from all of a game's logs, in chunks of 1,000 games. The games it picks are every game of the latest logged season (the nightly scrape rewrites it) plus any game with a log row that has no share row. `python -m predictions.shares refresh [--all]`. |
| Nightly hook (`app/schedules.py`) | The `skater shares` step runs right after the log and team-stats scrape, before props and training, in both `nightly_pipeline` and `full_refresh`. It runs even when the scrape fails, because it only mirrors whatever the logs hold. |
| `predict_skater` | Reads the player's stored rows. Games without one (scraped since the refresh, or the table not migrated) are computed the old way for those games only. The read is inside a savepoint, so a missing table can't roll back the prediction log's pending rows. |
| Lineups cut to the player's games | `teammate_quality` works per team-game, so `predict_skater` now passes only the lineups of the player's own games instead of the whole season's. The lineups are still built at serve time, from the context's expected lineups, so the injuries feed's lineup changes flow through unchanged. |

### Equivalence
- **Only the per-game values are stored.** The pre-game summaries (last 5, EWM, season, career) are still built at serve time by `skater_features` from strictly earlier games, as in training. A stored row is `skater_shares` of the same log rows, so the as-of logic can't change.
- **Full slate:** `predictions/experiments/shares_equivalence.py` runs `predict_skater` against a copy of v4's `predict_skater` for every skater the log would predict. On 2026-10-08, all 359 skaters' model inputs were identical (same NaN pattern, max diff 0.0), and **all 359 × 7 expected counts were bitwise equal.** The same holds on 2026-10-10 (14 games, 503 skaters).
- **Tests** (`tests/test_skater_shares_table.py`):
  - Stored shares equal `skater_shares`, with NaN stored as NULL (e.g. a team without PP time).
  - The refresh picks only the latest season and games with new rows.
  - Live shares match the full computation with an empty, partial or missing table.
  - The lineup cut leaves teammate quality unchanged, including for a player with no lineup at all.

### Cost and caveats
- **Backfill:** 779k rows for 21,643 games took 63 s. A nightly refresh (latest season so far, 43 games) takes about 1 s plus container start.
- **Stale rows:** a share row can go stale only if a game's logs change outside the latest season without adding a row (e.g. a re-scrape of an old season through `app.backfill`). Run `python -m predictions.shares refresh --all` after such a backfill.
- **Partial games:** a game scraped partially before the refresh and completed later is caught. The new rows have no share row, so the whole game is redone.

### Before merging to the real DB
Run `alembic upgrade head`. The migration's plain `CREATE INDEX` briefly blocks writes to `skater_game_logs`. To avoid that, build `ix_skater_game_logs_player_id` first with `CREATE INDEX CONCURRENTLY`; the migration skips an index that already exists. Then run `python -m predictions.shares refresh` once to backfill (about 1 minute). Until then, predictions fall back to the v4 computation, which gives the same results.
