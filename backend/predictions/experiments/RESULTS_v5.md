# v5

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
