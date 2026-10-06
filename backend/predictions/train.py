import asyncio
import joblib
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, log_loss, roc_auc_score
from xgboost import XGBRegressor, XGBClassifier
from sqlalchemy.ext.asyncio import AsyncSession
from .config import (
    SKATER_FEATURE_COLUMNS,
    SKATER_TARGET_COLUMNS,
    SKATER_CLF_TARGET_COLUMNS,
    SKATER_XGB_PARAMS,
    SKATER_XGB_CLF_PARAMS,
    skater_model_path,
    skater_clf_model_path,
    GOALIE_FEATURE_COLUMNS,
    GOALIE_TARGET_COLUMNS,
    GOALIE_XGB_PARAMS,
    goalie_model_path,
    TEAM_FEATURE_COLUMNS,
    TEAM_CLF_TARGET_COLUMNS,
    TEAM_XGB_CLF_PARAMS,
    team_clf_model_path,
)
from .data import load_skater_training_data, load_goalie_training_data, load_team_training_data

async def train_skater_models(session: AsyncSession) -> dict[str, float]:
    df = await load_skater_training_data(session)
    if df.empty:
        print("No training data found.  Make sure SkaterGameFeatures and "
              "SkaterGameLog are populated.")
        return {}
    # CPU-bound fitting runs in a worker thread so the event loop (API + scheduler) stays responsive
    return await asyncio.to_thread(_fit_skater_models, df)

def _fit_skater_models(df) -> dict:
    X = df[SKATER_FEATURE_COLUMNS].astype(np.float32)
    results: dict[str, float] = {}
    X_train, X_val, idx_train, idx_val = train_test_split(
        X, df.index, test_size=0.2, random_state=42
    )
    for target in SKATER_TARGET_COLUMNS:
        y = df[target].astype(np.float32)
        y_train, y_val = y.iloc[idx_train], y.iloc[idx_val]
        model = XGBRegressor(**SKATER_XGB_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        preds = model.predict(X_val)
        mae = mean_absolute_error(y_val, preds)
        results[target] = round(float(mae), 4)
        path = skater_model_path(target)
        joblib.dump(model, path)
        print(f"  {target:>20s}  MAE={mae:.4f}  → saved to {path}")
    return results

async def train_skater_classifiers(session: AsyncSession) -> dict[str, dict]:
    df = await load_skater_training_data(session)
    if df.empty:
        print("No training data found.  Make sure SkaterGameFeatures and "
              "SkaterGameLog are populated.")
        return {}

    # CPU-bound fitting runs in a worker thread so the event loop (API + scheduler) stays responsive
    return await asyncio.to_thread(_fit_skater_classifiers, df)

def _fit_skater_classifiers(df) -> dict:
    X = df[SKATER_FEATURE_COLUMNS].astype(np.float32)
    results: dict[str, dict] = {}

    X_train, X_val, idx_train, idx_val = train_test_split(
        X, df.index, test_size=0.2, random_state=42
    )
    binary_targets = {
        "goals":   (df["goals"] >= 1).astype(np.int32),
        "assists": ((df["primary_assists"] + df["secondary_assists"]) >= 1).astype(np.int32),
        "points":  (df["points"] >= 1).astype(np.int32),
    }
    for target in SKATER_CLF_TARGET_COLUMNS:
        y = binary_targets[target]
        y_train, y_val = y.iloc[idx_train], y.iloc[idx_val]

        model = XGBClassifier(**SKATER_XGB_CLF_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        proba = model.predict_proba(X_val)[:, 1]
        ll = log_loss(y_val, proba)
        auc = roc_auc_score(y_val, proba)

        pos_rate = y_train.mean()
        results[target] = {
            "logloss": round(float(ll), 4),
            "auc": round(float(auc), 4),
            "pos_rate": round(float(pos_rate), 4),
        }

        path = skater_clf_model_path(target)
        joblib.dump(model, path)
        print(f"  {target + '_clf':>20s}  logloss={ll:.4f}  AUC={auc:.4f}  "
              f"pos_rate={pos_rate:.2%}  → saved to {path}")

    return results

async def train_goalie_models(session: AsyncSession) -> dict[str, float]:
    df = await load_goalie_training_data(session)
    if df.empty:
        print("No training data found.  Make sure GoalieGameFeatures and "
              "GoalieGameLog are populated.")
        return {}
    # CPU-bound fitting runs in a worker thread so the event loop (API + scheduler) stays responsive
    return await asyncio.to_thread(_fit_goalie_models, df)

def _fit_goalie_models(df) -> dict:
    X = df[GOALIE_FEATURE_COLUMNS].astype(np.float32)
    results: dict[str, float] = {}
    X_train, X_val, idx_train, idx_val = train_test_split(
        X, df.index, test_size=0.2, random_state=42
    )
    for target in GOALIE_TARGET_COLUMNS:
        y = df[target].astype(np.float32)
        y_train, y_val = y.iloc[idx_train], y.iloc[idx_val]
        model = XGBRegressor(**GOALIE_XGB_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        preds = model.predict(X_val)
        mae = mean_absolute_error(y_val, preds)
        results[target] = round(float(mae), 4)
        path = goalie_model_path(target)
        joblib.dump(model, path)
        print(f"  {target:>20s}  MAE={mae:.4f}  → saved to {path}")
    return results

async def train_team_classifiers(session: AsyncSession) -> dict[str, dict]:
    df = await load_team_training_data(session)
    if df.empty:
        print("No training data found.  Make sure TeamGameLog and "
              "TeamGameFeatures are populated.")
        return {}

    # CPU-bound fitting runs in a worker thread so the event loop (API + scheduler) stays responsive
    return await asyncio.to_thread(_fit_team_classifiers, df)

def _fit_team_classifiers(df) -> dict:
    df_home = df[df["is_home"] == 1].reset_index(drop=True)
    print(f"  Home-perspective rows for classifier: {len(df_home)} "
          f"(total rows with opponent features: {len(df)})")

    if df_home.empty:
        print("  WARNING: No home-team rows found after filtering. "
              "This usually means the self-join found no games where both teams "
              "have 5-game rolling features, OR home_away values differ from 'H'.\n"
              "  Falling back to all rows (label = goals > goals_against).")
        df_home = df.reset_index(drop=True)

    if df_home.empty:
        print("  No training data available for team classifier. Skipping.")
        return {}

    X = df_home[TEAM_FEATURE_COLUMNS].astype(np.float32)
    results: dict[str, dict] = {}

    X_train, X_val, idx_train, idx_val = train_test_split(
        X, df_home.index, test_size=0.2, random_state=42
    )
    binary_targets = {
        "win": (df_home["goals"] > df_home["goals_against"]).astype(np.int32),
    }
    for target in TEAM_CLF_TARGET_COLUMNS:
        y = binary_targets[target]
        y_train, y_val = y.iloc[idx_train], y.iloc[idx_val]

        model = XGBClassifier(**TEAM_XGB_CLF_PARAMS)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        proba = model.predict_proba(X_val)[:, 1]
        ll = log_loss(y_val, proba)
        auc = roc_auc_score(y_val, proba)

        pos_rate = y_train.mean()
        results[target] = {
            "logloss": round(float(ll), 4),
            "auc": round(float(auc), 4),
            "pos_rate": round(float(pos_rate), 4),
        }

        path = team_clf_model_path(target)
        joblib.dump(model, path)
        print(f"  {target + '_clf':>20s}  logloss={ll:.4f}  AUC={auc:.4f}  "
              f"pos_rate={pos_rate:.2%}  → saved to {path}")

    return results

