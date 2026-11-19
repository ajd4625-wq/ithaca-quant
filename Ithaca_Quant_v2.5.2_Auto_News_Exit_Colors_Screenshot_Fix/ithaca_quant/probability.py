"""Experimental conditional event probabilities with chronological holdout checks.

An event is measured at the horizon's CLOSING price. This is not the
probability of the price touching a level at any time during the window.
No estimates are represented as clinically/financially calibrated odds.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import improved_accuracy
from .features import FEATURES


@dataclass
class EventModel:
    classifier: object | None
    event_rate: float
    events: int
    rows: int
    validation_brier: float
    validation_baseline_brier: float
    validation_count: int
    # Weight on the classifier; the remainder goes to the historical base rate.
    # Chosen on a purged chronological calibration block so a model that does not beat the
    # constant-rate baseline is automatically pulled toward that baseline.
    blend: float = 1.0

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        if self.classifier is None:
            return np.full(len(rows), np.nan)
        raw = np.asarray(self.classifier.predict_proba(rows[FEATURES].to_numpy(dtype=float))[:, 1], dtype=float)
        if self.blend >= 1.0:
            return raw
        return self.blend * raw + (1.0 - self.blend) * self.event_rate


def _fit(x: np.ndarray, y: np.ndarray):
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.04, max_iter=500, random_state=42),
    ).fit(x, y)


def fit_event_model(train: pd.DataFrame, *, event_return: float = 0.20) -> EventModel:
    """Estimate P(forward_return >= event_return) from mature historical labels.

    Time-ordered internal holdout uses only earlier *matured* labels for its fit.
    Need enough observed positive/negative events, otherwise show N/A rather
    than make up a number. Even with events, estimates may be miscalibrated.
    """
    clean = train.loc[train['forward_return'].notna()].copy()
    clean = clean.sort_values(['date', 'ticker'])
    if len(clean) > 120_000:
        clean = clean.sample(n=120_000, random_state=113).sort_values(['date', 'ticker'])
    y = (clean['forward_return'].to_numpy(dtype=float) >= event_return).astype(int)
    count = len(y)
    positives = int(y.sum())
    base = float(y.mean()) if count else float('nan')
    missing = EventModel(None, base, positives, count, float('nan'), float('nan'), 0)
    if count < 500 or positives < 20 or count - positives < 100 or clean['date'].nunique() < 150:
        return missing

    # Strictly ordered fit / probability-blend calibration / evaluation.
    # Selection of the blend weight cannot use the later reported Brier score.
    dates = clean['date'].drop_duplicates().sort_values().to_numpy()
    calibration_start = pd.Timestamp(dates[int(len(dates) * .60)])
    evaluation_start = pd.Timestamp(dates[int(len(dates) * .80)])
    early = clean.loc[clean['label_end'] < calibration_start]
    calibration = clean.loc[(clean['date'] >= calibration_start) &
                            (clean['date'] < evaluation_start) &
                            (clean['label_end'] < evaluation_start)]
    evaluation = clean.loc[clean['date'] >= evaluation_start]
    val_brier, base_brier, val_n = float('nan'), float('nan'), 0
    # If calibration is impossible, show the observed base rate instead of
    # unvalidated conditional odds.
    blend = 0.0 if improved_accuracy() else 1.0
    if len(early) >= 350 and len(calibration) >= 60 and len(evaluation) >= 60:
        early_y = (early['forward_return'].to_numpy(dtype=float) >= event_return).astype(int)
        cal_y = (calibration['forward_return'].to_numpy(dtype=float) >= event_return).astype(int)
        eval_y = (evaluation['forward_return'].to_numpy(dtype=float) >= event_return).astype(int)
        if early_y.sum() >= 10 and (len(early_y) - early_y.sum()) >= 50:
            evaluator = _fit(early[FEATURES].to_numpy(dtype=float), early_y)
            rate = float(early_y.mean())
            cal_pred = evaluator.predict_proba(calibration[FEATURES].to_numpy(dtype=float))[:, 1]
            if improved_accuracy():
                grid = (0.0, 0.25, 0.5, 0.75, 1.0)
                scores = [brier_score_loss(cal_y, weight * cal_pred + (1 - weight) * rate)
                          for weight in grid]
                blend = float(grid[int(np.argmin(scores))])
            eval_pred = evaluator.predict_proba(evaluation[FEATURES].to_numpy(dtype=float))[:, 1]
            eval_blend = blend * eval_pred + (1 - blend) * rate
            val_brier = float(brier_score_loss(eval_y, eval_blend))
            base_brier = float(brier_score_loss(eval_y, np.full(len(eval_y), rate)))
            val_n = len(evaluation)

    full = _fit(clean[FEATURES].to_numpy(dtype=float), y)
    return EventModel(full, base, positives, count, val_brier, base_brier, val_n, blend)


def annotate_probabilities(current: pd.DataFrame, train: pd.DataFrame, *, boom_return: float = 0.20) -> pd.DataFrame:
    result = current.copy()
    gain_model = fit_event_model(train, event_return=0.000001)
    boom_model = fit_event_model(train, event_return=boom_return)
    result['prob_gain'] = gain_model.predict(result)
    result['prob_boom'] = boom_model.predict(result)
    result['boom_base_rate'] = boom_model.event_rate
    result['boom_event_count'] = boom_model.events
    result['boom_train_rows'] = boom_model.rows
    result['boom_holdout_brier'] = boom_model.validation_brier
    result['boom_holdout_baseline_brier'] = boom_model.validation_baseline_brier
    result['boom_holdout_n'] = boom_model.validation_count
    return result
