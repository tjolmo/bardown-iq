# NHL Prediction Capstone

Game win probabilities, skater and goalie stat predictions and player prop pricing for every NHL game, with a
forward test that logs each day's predictions next to the market and scores them after the games.

## Running it

1. Create `.env` from `.env.example` and fill it in (`PROPLINE_API_KEY` is needed for props and moneylines,
   `ADMIN_TOKEN` for the admin endpoints).
2. Start everything:

```bash
docker compose up -d --build
```

One compose file, one database. The services:

| Service | Container | URL | What it does |
|---|---|---|---|
| `db` | `postgres_db` | `localhost:5433` | Postgres 15; data in `./postgres_data` |
| `backend` | `fastapi_backend` | http://localhost:8002 (API docs at `/docs`) | This checkout's code, live-reloaded. Serves the site. Runs no scheduled jobs (`SCHEDULER_ENABLED=0`) |
| `frontend` | `react_frontend` | http://localhost:5174 | The site, live-reloaded |
| `forward` | `fwd_fastapi_backend` | http://localhost:8004 | The frozen forward test: runs every scheduled job (fetching, prediction log, scoring, weekly training) |

The two backends share the database, so only one of them may run the scheduled jobs. The forward container always
does; set `DEV_SCHEDULER_ENABLED=1` in `.env` only if you take the forward container down and want the dev
backend to do the fetching instead.

### The forward container

The forward test's point is a model that doesn't change under it, so its code is baked into the image
`nhl-fwd-backend` (no bind mount, no `--reload`) and `docker compose up --build` never rebuilds it. Its model
bundles live in the `nhl-fwd_fwd_models` volume and are retrained every Monday at 03:00 UTC (`TRAIN_SCHEDULE=weekly`,
`TRAIN_WEEKDAY=0`); each training makes a new `model_version` that the prediction log records.

To move it to new code, commit first (the commit is printed at startup and is how a `model_version` is traced
back), then:

```bash
docker build --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) -t nhl-fwd-backend ./backend
```

```bash
docker compose up -d forward
```

A code rebuild keeps the bundles in the volume, so `model_version` only changes when training runs.

### Environment switches

| Variable | Default | Meaning |
|---|---|---|
| `SCHEDULER_ENABLED` | `1` | `0` turns off every scheduled job and the startup refresh (set per service in `docker-compose.yml`) |
| `TRAIN_SCHEDULE` | `weekly` | When the 03:00 UTC nightly run retrains: `weekly` (on `TRAIN_WEEKDAY`, 0 = Monday), `nightly`, `off`. Features still update from the fresh logs every night; only the fitted weights wait |
| `TRAIN_ON_STARTUP` | unset | `always` forces training at startup. Otherwise startup trains only when a model bundle is missing, so a restart never starts a new `model_version` |
| `GIT_COMMIT` | `unknown` | Build arg of the backend image, printed at startup |
| `LIVE_SCORES_POLL_MINUTES` | `10` | How often the NHL score feed is polled while games are under way: the live-scores job, and how long the site reuses the feed for the period, clock and intermission time on today's games (the intermission countdown runs between polls; the game clock shows as of the last poll). The forward container picks it up after its next rebuild |

## Scheduled jobs (all times UTC)

| When | Job | Steps |
|---|---|---|
| 03:00 | nightly | schedules, rosters, MoneyPuck player logs and team stats, skater shares, last night's actual starters, ESPN odds and prop odds, scoring of yesterday's logged predictions, PropLine props, training (per `TRAIN_SCHEDULE`) |
| 15:00 | morning | injury report, ESPN odds and prop odds, PropLine props, edge board |
| 21:00 and 22:00 | pregame | starting goalies, injury report, ESPN odds and prop odds, PropLine props, **prediction log**, edge board |
| every 10 min (`LIVE_SCORES_POLL_MINUTES`) | live scores | only while a game is about to start or under way |
| every 30 min | game lines | one bulk PropLine request for the site's moneylines |

A container that starts between 21:00 and 06:00 UTC runs the pregame pipeline first, so a late start still logs
today's games. The jobs share one lock, so a nightly run never overlaps a manual refresh.

PropLine's free tier is 1,000 requests a day: about 48 for game lines, 30 per props run, and one per event for
its market list.

## Refreshing data manually

A full refresh (teams, schedules, rosters, game logs, team stats, shares, scores, starters, odds, props, training)
runs in the background and returns `202`, or `409` if one is already running:

```bash
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8004/admin/refresh
```

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8004/admin/refresh
```

Both are also on the API docs page (**Authorize** with the token, then **Try it out**). Use port 8002 to run it
in the dev backend instead; it retrains that container's bundles, not the forward test's.

## Backfills

The database already holds everything below (games and team stats from 2008-09, player logs from 2008-09 with
shots, hits, blocks and power-play columns, ESPN closing odds from 2019, ESPN player props from Feb 2024, actual
starters for every game since 2008, birth dates, deployment shares). The commands exist for adding a season,
repairing a gap, or standing up a fresh database. Every one is an upsert, so re-running is safe. Run them inside a
backend container:

```bash
docker compose exec backend python -m app.backfill --seasons 2026
```

| Command | Fills | Notes |
|---|---|---|
| `python -m app.backfill --games-seasons 2008 … 2019` | `games`: schedules and final scores of past seasons | Relocated franchises (ATL, PHX) are added as teams first |
| `python -m app.backfill --seasons 2008 … 2026` | `skater_game_logs`, `goalie_game_logs` from MoneyPuck | Re-scrape a season to fill columns added later |
| `python -m app.backfill --team-stats-seasons 2008 … 2026` | `team_game_stats` (MoneyPuck team game-by-game by situation) | The team model's strength features |
| `python -m app.backfill --odds 2019-04-01 2026-10-08 [--odds-cache DIR]` | `game_odds` (ESPN closing and opening lines) and the price-path snapshots | Run after `--games-seasons`; the cache dir avoids refetching on a retry |
| `python -m app.backfill --props 2024-02-01 2026-10-08 [--odds-cache DIR]` | `player_prop_odds` (ESPN player props) | Run after games, players and logs exist |
| `python -m app.backfill --birth-dates` | `players.birth_date` from the NHL API | For the aging curve |
| `python -m app.backfill --actual-starters [--starter-seasons 2008 2026] [--starters-log FILE]` | `game_starters` (source `nhl`): who started every finished game, from play-by-play with the boxscore flag as fallback | Resumable; about 75 minutes for everything |
| `python -m predictions.shares refresh [--all]` | `skater_game_shares` | About a minute for everything; `--all` after re-scraping an old season |
| `python -m predictions.train` | Retrains the three model bundles | About 30 minutes, ~4.3 GB peak memory |

The nightly run keeps the current season of all of these up to date on its own.

## Migrations

Alembic, in `backend/migrations`. Both backend containers run `alembic upgrade head` at startup. To add one after
changing `backend/app/models.py`:

```bash
docker compose exec backend alembic revision --autogenerate -m "what changed"
```

## The forward test

`predictions/prediction_log.py` freezes, at 21:00 UTC, the win probability of every game today and the expected
counts of every expected skater and goalie, next to the market price at that moment (ESPN's line, else the
PropLine consensus). The nightly run scores them against results and the closing line: log loss, Poisson
deviance, calibration, closing-line value and flat-stake return at a 2% edge.

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8004/admin/model-report?start=20261001"
```

The same report, and manual log/score runs, from the command line inside the forward container:

```bash
docker compose exec forward python -m predictions.prediction_log report
```

Model experiments and their results, version by version, are in `backend/predictions/experiments/RESULTS*.md`.

## Tests

The suite uses an in-memory SQLite engine and needs `pytest` and `aiosqlite`, which aren't in the image:

```bash
docker compose exec backend sh -c "pip install -q pytest aiosqlite && python -m pytest -q"
```

## Data sources and attribution

This project relies on data provided by **MoneyPuck**, the **NHL**, **ESPN** and **PropLine**.

- [MoneyPuck](https://moneypuck.com): player and team game-by-game data, the core of the models.
- [NHL API](https://www.nhl.com/): teams, rosters, schedules, scores, play-by-play.
- ESPN: closing odds, player prop history, injury report, probable starting goalies.
- [PropLine](https://prop-line.com): live player props and game lines from every book.

> **Disclaimer:** This project is an independent analysis and is not affiliated with, endorsed by, or sponsored
> by the National Hockey League (NHL), MoneyPuck.com, ESPN or PropLine. All NHL logos and marks are the property
> of the NHL.
