import itertools
import numpy as np
import pandas as pd
from scipy.stats import poisson
from predictions import features as F

NORTH = ["CGY", "EDM", "MTL", "OTT", "TOR", "VAN", "WPG"]   # 2020-21 North division: 7 teams, 4 playoff spots

def _north_season(winner=lambda home, away: home):
    """One game between every pair of North teams, one per date, all played; plus one playoff game."""
    rows = []
    for i, (home, away) in enumerate(itertools.combinations(NORTH, 2)):
        w = winner(home, away)
        rows.append({"id": 2020020001 + i, "season": 2020, "date": 20210101 + i, "home_team_tri_code": home,
                     "away_team_tri_code": away, "home_score": 3.0 if w == home else 1.0, "away_score": 3.0 if w == away else 1.0})
    rows.append({"id": 2020030111, "season": 2020, "date": 20210601, "home_team_tri_code": "TOR",
                 "away_team_tri_code": "CGY", "home_score": np.nan, "away_score": np.nan})
    return pd.DataFrame(rows)

def _by_rank(home, away):
    # the team earlier in NORTH always wins: CGY wins all six, WPG loses all six
    return home if NORTH.index(home) < NORTH.index(away) else away

def test_standings_flags_use_only_earlier_dates():
    games = _north_season()
    base = F.standings_flags(games)
    k = 10
    flipped = games.copy()
    flipped.loc[k, ["home_score", "away_score"]] = flipped.loc[k, ["away_score", "home_score"]].to_numpy()
    changed = F.standings_flags(flipped)
    upto = games.loc[games["date"] <= games.loc[k, "date"], "id"]
    pick = lambda df: df[df["game_id"].isin(upto)].sort_values(["game_id", "team"]).reset_index(drop=True)
    # a game's result never reaches its own date's (or earlier) pre-game flags
    pd.testing.assert_frame_equal(pick(base), pick(changed))

def test_standings_flags_arithmetic():
    flags = F.standings_flags(_north_season(_by_rank))
    first = flags[flags["game_id"] == 2020020001]
    assert (first[["team_clinched", "team_eliminated"]] == 0).all().all()
    # playoff games carry the final regular season (points 12, 10, 8, 6, 4, 2, 0 in NORTH order); only the
    # playoff game's two teams get rows
    final = flags[flags["game_id"] == 2020030111].set_index("team")
    assert final.loc["CGY", "team_clinched"] == 1.0 and final.loc["CGY", "team_eliminated"] == 0.0
    # TOR (5th, 4 points) has four teams above it, as many as there are spots
    assert final.loc["TOR", "team_clinched"] == 0.0 and final.loc["TOR", "team_eliminated"] == 1.0

def test_standings_flags_mid_season_elimination():
    games = _north_season(_by_rank)
    flags = F.standings_flags(games).merge(games[["id", "date"]].rename(columns={"id": "game_id"}), on="game_id")
    wpg = flags[flags["team"] == "WPG"].sort_values("date")
    # WPG ends up eliminated before its last game, never clinched, and the flag never turns off once on
    assert wpg["team_eliminated"].iloc[-1] == 1.0 and wpg["team_clinched"].max() == 0.0
    assert wpg["team_eliminated"].is_monotonic_increasing

def test_team_model_frame_has_standings_diffs():
    games = _north_season(_by_rank)
    tg = []
    for g in games.itertuples():
        for team, opp, home in ((g.home_team_tri_code, g.away_team_tri_code, 1.0), (g.away_team_tri_code, g.home_team_tri_code, 0.0)):
            tg.append({"game_id": g.id, "team": team, "opponent": opp, "season": 2020, "game_date": g.date, "is_home": home,
                       **{s: 1.0 for s in F.TEAM_STATS}})
    feats = F.team_history_features(F.build_team_games(pd.DataFrame(tg)))
    frame = F.build_team_model_frame(games, feats)
    po = frame[frame["game_id"] == 2020030111].iloc[0]
    # home TOR was eliminated, away CGY clinched
    assert po["diff_clinched"] == -1.0 and po["diff_eliminated"] == 1.0
    assert {"diff_clinched", "diff_eliminated"} <= set(F.TEAM_FEATURE_COLUMNS)

def test_regulation_outcome_probs_match_brute_force():
    lh, la = np.array([3.1, 2.0]), np.array([2.6, 2.0])
    p, tie = F.regulation_outcome_probs(lh, la)
    for i in range(2):
        g = np.arange(30)
        joint = np.outer(poisson.pmf(g, lh[i]), poisson.pmf(g, la[i]))
        assert abs(tie[i] - np.trace(joint)) < 1e-6
        assert abs(p[i] - (np.tril(joint, -1).sum() + 0.5 * np.trace(joint))) < 1e-6
    # equal teams and a fair overtime are a coin flip
    assert abs(p[1] - 0.5) < 1e-9

def test_regulation_outcome_probs_tie_inflation_keeps_a_distribution():
    lh, la = np.array([3.4]), np.array([2.5])
    p0, tie0 = F.regulation_outcome_probs(lh, la)
    p, tie = F.regulation_outcome_probs(lh, la, tie_inflation=1.2, ot_home_share=0.0)
    assert abs(tie[0] - 1.2 * tie0[0]) < 1e-12
    # with no overtime wins for the home side, P(home) is the regulation-win share of the non-tie mass
    reg_win = p0[0] - 0.5 * tie0[0]
    assert abs(p[0] - reg_win * (1 - tie[0]) / (1 - tie0[0])) < 1e-12
    p_all, _ = F.regulation_outcome_probs(lh, la, tie_inflation=1.2, ot_home_share=1.0)
    # home win + away win + tie split always sums to one: P(home) moves by exactly the tie mass
    assert abs(p_all[0] - p[0] - tie[0]) < 1e-12

def test_went_to_overtime_from_moneypuck_goals_and_goalie_time():
    frame = pd.DataFrame({"game_id": [2024020001, 2024020002, 2024020003, 2024020004, 2024030001],
                          "home_score": [3, 2, 4, 1, 3], "away_score": [2, 3, 1, 2, 2]})
    # MoneyPuck goals (no shootout goals): game 1 tied -> shootout; game 2 regulation-looking but a goalie played 62 min
    tg = pd.DataFrame({"game_id": [2024020001, 2024020002, 2024020003, 2024020004, 2024030001], "is_home": 1.0,
                       "gf": [2.0, 2.0, 4.0, 1.0, 3.0], "ga": [2.0, 3.0, 1.0, 2.0, 2.0]})
    goalies = pd.DataFrame({"game_id": [2024020001, 2024020002, 2024020003, 2024020004], "team": "AAA",
                            "toi": [3900.0, 3720.0, 3600.0, 3580.0]})
    # game 3 is a 3-goal win, game 4 a regulation one-goal game, the playoff game has no flag
    assert F.went_to_overtime(frame, tg, goalies).tolist() == [True, True, False, False, False]

def test_player_context_fallback_fills_only_missing_market_goals():
    tf = pd.DataFrame({"game_id": [1, 1, 2, 2], "team": ["AAA", "BBB", "AAA", "BBB"]})
    implied = pd.DataFrame({"game_id": [1, 1], "team": ["AAA", "BBB"], "team_implied_goals": [3.4, 2.6]})
    fallback = pd.DataFrame({"game_id": [1, 1, 2, 2], "team": ["AAA", "BBB", "AAA", "BBB"], "team_implied_goals": [9.0, 9.0, 3.1, 2.9]})
    out = F.add_player_context(tf, implied, None, fallback=fallback)
    assert out["team_implied_goals"].tolist() == [3.4, 2.6, 3.1, 2.9]
    assert F.add_player_context(tf, implied, None)["team_implied_goals"].isna().sum() == 2
