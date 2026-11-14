"""Ensemble with a chronological label-availability boundary."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor

from .config import MAX_AGENTS
from .features import FEATURES, FUNDAMENTAL_FEATURES, NEWS_FEATURES
from .probability import annotate_probabilities


@dataclass
class Ensemble:
    boosted: HistGradientBoostingRegressor
    forest: RandomForestRegressor
    feature_names: tuple[str, ...] = tuple(FEATURES)

    def predict(self, features: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        x = features[list(self.feature_names)].to_numpy(dtype=float)
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


def fit_ensemble(train: pd.DataFrame, fast: bool = False,
                 features: tuple[str, ...] | None = None) -> Ensemble:
    if len(train) < 350 or train["date"].nunique() < 100:
        raise ValueError("Not enough training history. Try more years of data.")
    if len(train) > 120_000:
        train = train.sample(n=120_000, random_state=42).sort_values("date")
    columns = tuple(features or FEATURES)
    x = train[list(columns)].to_numpy(dtype=float)
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
    return Ensemble(boosted, forest, columns)


def choose_evidence_features(train: pd.DataFrame, asof, fast=False):
    """Select dated SEC / archived news features only if they improve train holdout.

    Selection holdout is chronological and embargoed. This is NOT independent
    out-of-sample evidence; run the unchanged walk-forward test separately.
    Empty/unavailable news histories NEVER manufacture an 'AI news' predictor.
    """
    base = tuple(FEATURES)
    dates = train["date"].sort_values().unique()
    if len(dates) < 300:
        return base, "Price/volume baseline (not enough chronology)", None
    cutoff = pd.Timestamp(dates[len(dates) - 100])
    early = train.loc[(train["date"] < cutoff) & (train["label_end"] < cutoff)]
    holdout = train.loc[train["date"] >= cutoff]
    if len(early) < 350 or len(holdout) < 50:
        return base, "Price/volume baseline (insufficient embargoed holdout)", None
    candidates = []
    issuer_min = max(1, int(np.ceil(train["ticker"].nunique() * .10)))
    if all(f in train for f in FUNDAMENTAL_FEATURES):
        filing_issuers = early.loc[early["sec_available"] > 0, "ticker"].nunique()
        if (filing_issuers >= issuer_min and early["sec_available"].sum() >= 100 and
                holdout["sec_available"].sum() >= 25):
            candidates.append((tuple(FUNDAMENTAL_FEATURES), "Dated SEC quarterly filings"))
    if all(f in train for f in NEWS_FEATURES):
        # Archived stories must have been observed across meaningful historical
        # time, before and during model selection. A handful of today's headlines
        # cannot qualify as a news-trained return model.
        early_observed = early.loc[early["news_available"] > 0, "date"].nunique()
        recent_observed = holdout.loc[holdout["news_available"] > 0, "date"].nunique()
        archival_issuers = early.loc[early["news_available"] > 0, "ticker"].nunique()
        if archival_issuers >= issuer_min and early_observed >= 65 and recent_observed >= 25:
            candidates.append((tuple(NEWS_FEATURES), "Timestamped news archive"))
    if not candidates:
        return base, "Price-only: not enough dated SEC/news training coverage", None
    technical = fit_ensemble(early, fast=True, features=base)
    truth = holdout["target"].to_numpy(dtype=float)
    baseline, _ = technical.predict(holdout)
    baseline_mae = float(np.abs(truth - baseline).mean())
    selected = base
    selected_note = "Price-only model retained: no evidence feature improved chronological MAE"
    best_mae = baseline_mae
    available_groups = list(candidates)
    if len(candidates) == 2:
        available_groups.append((candidates[0][0] + candidates[1][0], "SEC filings + dated news archive"))
    # Candidate variants and the acceptance threshold are fixed in advance;
    # this does not make the reuse of the holdout a fully independent test.
    for extras, name in available_groups:
        variant = fit_ensemble(early, fast=True, features=base + extras)
        pred, _ = variant.predict(holdout)
        mae = float(np.abs(truth - pred).mean())
        improvement = 0.02 if any(x in extras for x in NEWS_FEATURES) else 0.01
        if mae < best_mae and mae < baseline_mae * (1 - improvement):
            selected = base + extras
            selected_note = f"{name} selected on chronological training holdout"
            best_mae = mae
    return selected, selected_note, (baseline_mae, best_mae)


def choose_financial_features(train: pd.DataFrame, asof, fast=False):
    """Backwards-compatible alias for SEC/news evidence-aware feature selection."""
    return choose_evidence_features(train, asof, fast=fast)


def forecast_asof(panel: pd.DataFrame, asof: pd.Timestamp, fast: bool = False,
                  boom_return: float = 0.20) -> pd.DataFrame:
    train = training_snapshot(panel, asof)
    # Large-universe scans can create millions of overlapping examples.
    # Stratified-by-time random sampling bounds training memory and runtime.
    # Sampling is from already-mature, historical labels only.
    if len(train) > 120_000:
        train = train.sample(n=120_000, random_state=42).sort_values("date")
    feature_set, selection_note, holdout_maes = choose_evidence_features(train, asof, fast=fast)
    ensemble = fit_ensemble(train, fast=fast, features=feature_set)
    current = panel.loc[panel["date"] == asof].copy()
    if current.empty:
        raise ValueError("No feature rows for the latest available session.")
    forecast, disagreement = ensemble.predict(current)
    current["forecast_excess"] = forecast
    current["model_disagreement"] = disagreement
    current["feature_selection"] = selection_note
    current["uses_sec_filings"] = "sec_revenue_yoy" in feature_set
    current["uses_news_history"] = "news_sentiment_7d" in feature_set
    current["filing_tech_holdout_mae"] = holdout_maes[0] if holdout_maes else np.nan
    current["filing_model_holdout_mae"] = holdout_maes[1] if holdout_maes else np.nan
    current = annotate_probabilities(current, train, boom_return=boom_return)
    return current.sort_values("forecast_excess", ascending=False).reset_index(drop=True)
