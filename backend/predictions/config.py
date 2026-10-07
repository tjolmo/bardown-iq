from pathlib import Path

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(exist_ok=True, parents=True)

# each bundle holds the fitted models plus everything live prediction needs to rebuild the same features
SKATER_BUNDLE = MODEL_DIR / "skater.joblib"
GOALIE_BUNDLE = MODEL_DIR / "goalie.joblib"
TEAM_BUNDLE = MODEL_DIR / "team.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"

# one Poisson model per stat; P(at least one) = 1 - exp(-expected), so counts and probabilities always agree
SKATER_TARGETS = ["goals", "assists", "points", "shots_on_goal"]
# skater stats beyond the core box score (stored since the shots/power-play backfill), used as extra inputs
SKATER_EXTRA_STATS = ("shots_on_goal", "pp_toi", "pp_points")
# shots per skater fell ~10% from 2023 to 2025; the league trend keeps shots-on-goal predictions unbiased
SKATER_TREND_TARGETS = ["shots_on_goal"]
GOALIE_TARGETS = ["goals_against", "sog", "saves"]
# targets whose league level drifts over time get the league trend as their Poisson base margin
# (shots per game fell ~10% from 2021 to 2025; goals against didn't drift, and the trend made it slightly worse)
GOALIE_TREND_TARGETS = ["sog", "saves"]

# the most recent fraction of game dates is held out to pick the number of trees and report out-of-time metrics;
# the saved model is then refit on all games with that many trees
VALIDATION_FRACTION = 0.2

POISSON_PARAMS = {
    "objective": "count:poisson",
    "tree_method": "hist",
    "eval_metric": "poisson-nloglik",
    "n_estimators": 4000,
    "learning_rate": 0.02,
    "max_depth": 4,
    "subsample": 0.8,
    "colsample_bytree": 0.6,
    "min_child_weight": 50,
    "reg_lambda": 5.0,
    "max_delta_step": 0.7,
    "random_state": 42,
    "early_stopping_rounds": 150,
}
GOALIE_POISSON_PARAMS = POISSON_PARAMS | {"min_child_weight": 20}
