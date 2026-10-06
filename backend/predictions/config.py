from pathlib import Path

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(exist_ok=True, parents=True)

# each bundle holds the fitted models plus everything live prediction needs to rebuild the same features
SKATER_BUNDLE = MODEL_DIR / "skater.joblib"
GOALIE_BUNDLE = MODEL_DIR / "goalie.joblib"
TEAM_BUNDLE = MODEL_DIR / "team.joblib"
METRICS_PATH = MODEL_DIR / "metrics.json"

# one Poisson model per stat; P(at least one) = 1 - exp(-expected), so counts and probabilities always agree
SKATER_TARGETS = ["goals", "assists", "points"]
GOALIE_TARGETS = ["goals_against", "sog"]
# targets whose league level drifts over time get the league trend as their Poisson base margin
# (shots per game fell ~10% from 2021 to 2025; goals against didn't drift, and the trend made it slightly worse)
GOALIE_TREND_TARGETS = ["sog"]

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
