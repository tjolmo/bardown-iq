# v5: model and data improvements

## 3. Live hits pricing

**Hits can't be priced live from either feed right now. The Odds API has no NHL hits market, and ESPN stopped carrying hits when DraftKings replaced ESPN BET.**

| Check | Result |
|---|---|
| Odds API docs, NHL player prop markets | points, PP points, assists, blocked shots, shots on goal, goals, total saves, first/last/anytime goal scorer, plus their `_alternate` versions. **No hits.** |
| `/events/{id}/markets` for tonight's WPG game (1 credit, 12 US books) | 50+ market keys across books. **No hits.** No book listed `player_blocked_shots` either (morning of game day). |
| ESPN `player_prop_odds`, hits markets by month | ESPN BET only: 1,238 markets in Oct 2025, 1,505 in Nov, 45 in Dec, then **none**. DraftKings via ESPN (Dec 2025 on, 2,541 games): 0 hits markets. |

- The backtest's 2.8k hits lines (RESULTS_props_v2.md) are almost all ESPN BET, Oct–Nov 2025. That book's feed is gone, so the hits edge has no live price source today.
- **What was built anyway:** the player-page props endpoint (`GET /players/props/{id}`) now merges ESPN's markets (`player_prop_odds`) into the Odds API rows, for any market key the Odds API didn't return for that game. Each ESPN row is priced with the model probability and edge, using the same `prop_probability` path, so hits use the negative binomial (alpha 0.12). Rows carry `source` (`odds_api` / `espn`) and `book`. The frontend prop card now shows all market names, the model's probability and edge, and the ESPN book.
  - Hits appear automatically if ESPN carries them again.
  - Today the rows this adds are mostly the anytime-goal price and blocked shots (DraftKings posts them for some players, closer to puck drop). When the Odds API fetch is missing (quota, see section 5), ESPN's markets show on their own.
- The Odds API request is unchanged, with no cost increase. A `player_hits` key would return nothing and cost nothing.
- **Bug fixed on the way: since props v2, every Odds API props save failed.** `PlayerPropOut` gained `model_prob` / `edge`, and `upsert_player_props` dumped them into the `props` insert ("Unconsumed column names"). The per-event `except` swallowed it. The book quotes were saved after the props, so `odds_api_prop_quotes` never got a row either. The credits were still spent. The fix:
  - The insert dumps only the table's columns.
  - Quotes are stored first, independently of the props save.
  - A test compiles the real Postgres statement.
- To price hits live, a new source is needed (a book's own API or another odds vendor). Neither free feed has the market.

## 5. Props forward-test coverage

The forward test isn't deployed, so there is no week of logs. Coverage was measured three ways: ESPN history in `nhl_experiments`, tonight's 3 games fetched live at 21:00 UTC from both feeds, and the 942 rows already in `player_prediction_log` (one test run at 05:24 UTC).

**ESPN coverage, share of skater-games with a two-sided ESPN line (players who played):**

| Period (book) | points | assists | SOG | blocks | hits | goals | PP pts | saves (starters) |
|---|---|---|---|---|---|---|---|---|
| 2024-25 (ESPN BET) | 42% | 42% | 0% | 12% | 0% | 98% | 28% | 94% |
| Oct–Nov 2025 (ESPN BET) | 45% | 45% | 38% | 12% | 19% | 97% | 30% | 94% |
| Dec 2025–Mar 2026 (DraftKings) | 0.9% | 0.9% | 0.7% | 0.2% | 0.1% | 0.6% | 0.7% | 1.5% |
| Apr–Jun 2026 (DraftKings) | 1.9% | 1.9% | 1.7% | 0.3% | 0% | 0% | 1.4% | – |
| Sep–Oct 2026 (DraftKings) | 59% | 59% | 46% | 4.5% | 0% | **0%** | 0% | 98% |

- DraftKings via ESPN covered almost no games in 2025-26. It covers every game so far this season, but only about half the skaters.
- DraftKings via ESPN prices goals only as one-sided anytime/milestone prices. Those have no vig-free price, so **goals never get an ESPN line**.

**Tonight at 21:00 UTC (3 games; 132 logged skater rows per stat, which includes about 24 projected scratches):**

| Stat | ESPN line | Odds API line | either | both |
|---|---|---|---|---|
| goals | 0 | 18 | **18** | 0 |
| assists | 50 | 61 | 62 | 49 |
| points | 51 | 63 | 64 | 50 |
| shots on goal | 48 | 52 | 53 | 47 |
| blocked shots | 0 | 0 | 0 | 0 |
| hits | 0 | 0 | 0 | 0 |
| saves (6 goalies) | 6 | 6 | 6 | 6 |

- The Odds API had 1,151 quotes from 6 books (BetMGM, DraftKings, BetOnline, BetRivers, FanDuel, Bovada) across 5 markets.
- **Nobody posted blocked shots by 21:00.** DraftKings' blocks on ESPN show up for a few players nearer puck drop.
- The 05:24 UTC test log had a line on 11 of 942 rows: ESPN posts props on game day.
- **Fallback implemented:**
  - A logged player stat takes ESPN's two-sided line if there is one, else the Odds API consensus. The consensus is the main line most books quote, with median prices and the same multiplicative de-vig as before (`pick_market`, `odds_api_book_rows`).
  - `player_prediction_log.market_source` records `espn` / `odds_api` (migration `a7b8c9d0e1f2`; older lined rows backfill to `espn`).
  - The scorer reads the close from the same feed. For `odds_api` rows that is the last Odds API fetch before puck drop, rebuilt from `first_seen` / `last_seen`, and pulled quotes are dropped.
  - Tonight the fallback adds goals (0 → 18 rows) and a few points/assists/SOG rows. ESPN and the Odds API mostly cover the same players, so the gain outside goals is small.
- **Model report:** `/admin/model-report` now has:
  - `coverage`: logged rows per priced stat with an `espn` / `odds_api` / `none` line, games with a line per feed, and games with none. It counts unscored rows too, so it's readable the morning after the first run.
  - `player_by_source`: log loss, CLV and ROI per stat and feed.

**Caveats:**
- **Odds API quota: the key has 500 credits a month.** Each event costs about 5 credits (unique markets returned × 1 region). The nightly props step alone is about 50–75 credits a night in-season, so the quota runs out within roughly a week. After that the fallback has no quotes (the API returns 429s, logged). Before relying on this, upgrade the plan or cut the request to the markets ESPN misses.
- Odds API quotes are fetched once a night (03:00 UTC, about 20 hours before puck drop). So `odds_api` lines are older than ESPN's 21:00 snapshot, and their "close" is usually the same fetch. Expect CLV of about 0 on that feed unless a pre-game Odds API fetch is added, which would double the credit cost.
