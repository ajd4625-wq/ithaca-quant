"""Ensemble with a chronological label-availability boundary."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

from .config import MAX_AGENTS
from .features import FEATURES
from .probability import annotate_probabilities


@dataclass
class Ensemble:
    boosted: HistGradientBoostingRegressor
    forest: RandomForestRegressor

    def predict(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x = features[FEATURES].to_numpy(dtype=float)
        p1 = self.boosted.predict(x)
        p2 = self.forest.predict(x)
        # Regression models can extrapolate wildly; these are bounded model outputs.
        forecast = np.clip((p1 + p2) / 2, -0.5, 0.5)
        disagreement = abs(p1 - p2)
        return forecast, disagreement


def training_snapshot(panel: pd.DataFrame, asof: pd.Timestamp, window_years: int = 4) -> pd.DataFrame:
    """Only labels fully observed strictly before the prediction's as-of date."""
    left = pd.Timestamp(asof) - pd.DateOffset(years=window_years)
    train = panel.loc[
        (panel["date"] >= left) & (panel["date"] < asof) &
        (panel["label_end"] < asof) & panel["target"].notna()
    ].copy()
    return train


def fit_ensemble(train: pd.DataFrame, fast: bool = False) -> Ensemble:
    if len(train) < 350 or train["date"].nunique() < 100:
        raise ValueError("Not enough training history. Try more years of data.")
    if len(train) > 120_000:
        train = train.sample(n=120_000, random_state=42).sort_values("date")
    x = train[FEATURES].to_numpy(dtype=float)
    y = train["target"].to_numpy(dtype=float)
    # Truncation reduces sensitivity to extraordinary historical jumps.
    y = np.clip(y, -0.8, 0.8)
    boosted = HistGradientBoostingRegressor(
        learning_rate=0.045, max_iter=40 if fast else 90,
        max_leaf_nodes=11, max_depth=4, min_samples_leaf=25,
        l2_regularization=5, random_state=42,
        early_stopping=False,
    )
    forest = RandomForestRegressor(
        n_estimators=30 if fast else 90, max_depth=7,
        min_samples_leaf=12, max_features=0.7,
        random_state=21, n_jobs=MAX_AGENTS,
    )
    boosted.fit(x, y)
    forest.fit(x, y)
    return Ensemble(boosted, forest)


def forecast_asof(panel: pd.DataFrame, asof: pd.Timestamp, fast: bool = False,
                  boom_return: float = 0.20) -> pd.DataFrame:
    train = training_snapshot(panel, asof)
    # Large-universe scans can create millions of overlapping examples.
    # Stratified-by-time random sampling bounds training memory and runtime.
    # Sampling is from already-mature, historical labels only.
    if len(train) > 120_000:
        train = train.sample(n=120_000, random_state=42).sort_values("date")
    ensemble = fit_ensemble(train, fast=fast)
    current = panel.loc[panel["date"] == asof].copy()
    if current.empty:
        raise ValueError("No feature rows for the latest available session.")
    forecast, disagreement = ensemble.predict(current)
    current["forecast_excess"] = forecast
    current["model_disagreement"] = disagreement
    current = annotate_probabilities(current, train, boom_return=boom_return)
    return current.sort_values("forecast_excess", ascending=False).reset_index(drop=True)
