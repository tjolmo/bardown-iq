import asyncio
import datetime
import json
import os
import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, mean_poisson_deviance, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy.ext.asyncio import AsyncSession
from xgboost import XGBClassifier, XGBRegressor
from . import features as F
from .config import (
    SKATER_BUNDLE, GOALIE_BUNDLE, TEAM_BUNDLE, METRICS_PATH, SKATER_TARGETS, GOALIE_TARGETS, GOALIE_TREND_TARGETS,
    VALIDATION_FRACTION, POISSON_PARAMS, GOALIE_POISSON_PARAMS, TEAM_XGB_PARAMS, TEAM_LOGISTIC_FEATURES,
)
from .data import load_skater_logs, load_goalie_logs, load_team_offense, load_games

async def train_all_models(db: AsyncSession) -> dict:
    skaters = await load_skater_logs(db)
    goalies = await load_goalie_logs(db)
    team_offense = await load_team_offense(db)
    games = await load_games(db)
    if skaters.empty or games.empty:
        print("No training data found. Make sure game logs and games are populated.")
        return {}
    # CPU-bound fitting runs in a worker thread so the event loop (API + scheduler) stays responsive
    return await asyncio.to_thread(_fit_all, skaters, goalies, team_offense, games)

def _fit_all(skaters, goalies, team_offense, games) -> dict:
    team_feats = F.team_history_features(F.build_team_games(team_offense))
    metrics = {"trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    metrics["skaters"] = _fit_skaters(skaters, team_feats)
    if not goalies.empty:
        metrics["goalies"] = _fit_goalies(goalies, team_feats)
    metrics["teams"] = _fit_teams(games, team_feats)
    METRICS_PATH.write_text(json.dumps(metrics, indent=1))
    return metrics

# ---------- shared ----------

def _time_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Holds out the most recent game dates, so validation always lies in the training data's future."""
    dates = np.sort(df["date"].unique())
    cutoff = dates[int(len(dates) * (1 - VALIDATION_FRACTION))]
    return df[df["date"] < cutoff], df[df["date"] >= cutoff]

def _margin(df, col):
    return np.log(df[col].to_numpy()) if col else None

def _fit_count_models(df, targets, cols, params, baselines, trend_targets=()) -> tuple[dict, dict]:
    """Fits one Poisson model per target: early-stopped on the held-out recent games, then refit on everything."""
    train, valid = _time_split(df)
    X_train, X_valid, X_all = (d[cols].astype(np.float32) for d in (train, valid, df))
    models, metrics = {}, {"train_rows": len(train), "valid_rows": len(valid)}
    for target in targets:
        margin = f"trend_{target}" if target in trend_targets else None
        model = XGBRegressor(**params)
        model.fit(X_train, train[target], base_margin=_margin(train, margin), eval_set=[(X_valid, valid[target])],
                  base_margin_eval_set=[_margin(valid, margin)] if margin else None, verbose=False)
        mu = model.predict(X_valid, base_margin=_margin(valid, margin))
        y = valid[target].to_numpy()
        n_trees = model.best_iteration + 1
        m = {"poisson_deviance": _dev(y, mu), "trees": n_trees}
        for name, base in baselines(train, valid, target).items():
            m[f"baseline_{name}"] = _dev(y, base)
        m["p_at_least_one_logloss"] = log_loss((y >= 1).astype(int), np.clip(1 - np.exp(-mu), 1e-6, 1 - 1e-6), labels=[0, 1])
        metrics[target] = m
        print(f"  {target:>15s}  deviance={m['poisson_deviance']:.4f}  "
              + "  ".join(f"{k}={v:.4f}" for k, v in m.items() if k.startswith("baseline_")))

        final = XGBRegressor(**(params | {"n_estimators": n_trees, "early_stopping_rounds": None}))
        final.fit(X_all, df[target], base_margin=_margin(df, margin), verbose=False)
        models[target] = final
    return models, metrics

def _save(bundle: dict, path) -> None:
    # write then swap, so a request never loads a half-written file
    tmp = path.with_suffix(".tmp")
    joblib.dump(bundle, tmp)
    os.replace(tmp, path)

def _dev(y, mu) -> float:
    return round(float(mean_poisson_deviance(y, np.clip(mu, 1e-6, None))), 4)

# ---------- skaters ----------

def _fit_skaters(skaters: pd.DataFrame, team_feats: pd.DataFrame) -> dict:
    df, league_rates = F.skater_features(skaters, team_feats)
    df = df[df["games_career"] >= 1]    # a player's first game has no history to predict from

    def baselines(train, valid, target):
        return {"league_mean": np.full(len(valid), train[target].mean()), "rate_x_toi": valid[f"exp_{target}"].to_numpy()}

    print("Training skater models")
    models, metrics = _fit_count_models(df, SKATER_TARGETS, F.SKATER_FEATURE_COLUMNS, POISSON_PARAMS, baselines)
    _save({"models": models, "features": F.SKATER_FEATURE_COLUMNS, "league_rates": league_rates}, SKATER_BUNDLE)
    return metrics

# ---------- goalies ----------

def _fit_goalies(goalies: pd.DataFrame, team_feats: pd.DataFrame) -> dict:
    df = F.goalie_features(goalies, team_feats)
    # predictions are for the goalie who starts, so learn from the goalie who played most of each game
    starter = df["toi"] == df.groupby(["game_id", "team"])["toi"].transform("max")
    df = df[starter & (df["games_career"] >= 1)].copy()
    for target in GOALIE_TREND_TARGETS:
        df[f"trend_{target}"] = F.league_trend(df, target)

    def baselines(train, valid, target):
        return {"league_mean": np.full(len(valid), train[target].mean())}

    print("Training goalie models")
    models, metrics = _fit_count_models(df, GOALIE_TARGETS, F.GOALIE_FEATURE_COLUMNS, GOALIE_POISSON_PARAMS,
                                        baselines, GOALIE_TREND_TARGETS)
    # live predictions use the latest league level (retrained nightly, and the trend moves slowly)
    trends = {t: F.latest_league_trend(df, t) for t in GOALIE_TREND_TARGETS}
    _save({"models": models, "features": F.GOALIE_FEATURE_COLUMNS, "trends": trends}, GOALIE_BUNDLE)
    return metrics

# ---------- teams ----------

def _team_logistic():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=1000))

def _fit_teams(games: pd.DataFrame, team_feats: pd.DataFrame) -> dict:
    df = F.build_team_model_frame(games, team_feats)
    regular = df["game_id"] // 10000 % 100 == 2
    df = df[regular & df["home_win"].notna() & df["home_games_season"].notna()].copy()
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    df["home_win"] = df["home_win"].astype(int)
    train, valid = _time_split(df)
    cols = F.TEAM_FEATURE_COLUMNS

    print("Training team win model")
    xgb = XGBClassifier(**TEAM_XGB_PARAMS)
    xgb.fit(train[cols].astype(np.float32), train["home_win"],
            eval_set=[(valid[cols].astype(np.float32), valid["home_win"])], verbose=False)
    logistic = _team_logistic().fit(train[TEAM_LOGISTIC_FEATURES], train["home_win"])
    p = (xgb.predict_proba(valid[cols].astype(np.float32))[:, 1]
         + logistic.predict_proba(valid[TEAM_LOGISTIC_FEATURES])[:, 1]) / 2
    y = valid["home_win"].to_numpy()
    metrics = {
        "train_rows": len(train), "valid_rows": len(valid), "trees": xgb.best_iteration + 1,
        "logloss": round(float(log_loss(y, p)), 4), "auc": round(float(roc_auc_score(y, p)), 4),
        "accuracy": round(float(np.mean((p > 0.5) == y)), 4),
        "baseline_home_rate_logloss": round(float(log_loss(y, np.full(len(y), train["home_win"].mean()))), 4),
        "baseline_elo_logloss": round(float(log_loss(y, valid["elo_prob"])), 4),
    }
    print(f"  {'win':>15s}  logloss={metrics['logloss']:.4f}  AUC={metrics['auc']:.4f}  acc={metrics['accuracy']:.3f}  "
          f"home_rate={metrics['baseline_home_rate_logloss']:.4f}  elo={metrics['baseline_elo_logloss']:.4f}")

    final_xgb = XGBClassifier(**(TEAM_XGB_PARAMS | {"n_estimators": metrics["trees"], "early_stopping_rounds": None}))
    final_xgb.fit(df[cols].astype(np.float32), df["home_win"], verbose=False)
    final_logistic = _team_logistic().fit(df[TEAM_LOGISTIC_FEATURES], df["home_win"])
    _save({"xgb": final_xgb, "logistic": final_logistic, "features": cols,
                 "logistic_features": TEAM_LOGISTIC_FEATURES}, TEAM_BUNDLE)
    return metrics

async def _main():
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await train_all_models(db)

if __name__ == "__main__":
    # retrain by hand: python -m predictions.train
    asyncio.run(_main())
