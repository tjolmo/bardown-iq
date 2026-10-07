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
