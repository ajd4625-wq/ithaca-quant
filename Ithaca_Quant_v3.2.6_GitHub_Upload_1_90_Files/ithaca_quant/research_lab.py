"""Chronologically selected forecasting candidates and explicit uncertainty.

No package is credited with higher accuracy until an embargoed test shows it.
Model selection uses a distinct block from the final calibration block.
Overlapping forward labels cannot cross either boundary.
"""
from __future__ import annotations
from dataclasses import dataclass
import importlib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, HuberRegressor
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.kernel_approximation import RBFSampler
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline


@dataclass
class LabResult:
    forecast: np.ndarray
    model_name: str
    calibration_n: int
    calibration_mae: float
    zero_baseline_mae: float
    selection_mae: float
    selection_baseline_mae: float
    interval_low: np.ndarray
    interval_high: np.ndarray
    interval_level: float
    explanation: list[str]
    diagnostic: str
    shrinkage: float = 1.0


def purged_split(train: pd.DataFrame, test_start, test_end=None):
    """A training row is permitted only if its *outcome* predates test_start."""
    boundary = pd.Timestamp(test_start)
    left = train.loc[(train['date'] < boundary) & (pd.to_datetime(train['label_end']) < boundary)]
    right = train.loc[train['date'] >= boundary]
    if test_end is not None:
        right = right.loc[right['date'] < pd.Timestamp(test_end)]
    return left, right


def _candidate(name: str, fast: bool = True):
    if name == 'Ridge':
        return make_pipeline(StandardScaler(), Ridge(alpha=20.0))
    if name == 'Robust MAE boosting':
        return HistGradientBoostingRegressor(loss='absolute_error', learning_rate=.055,
                                              max_iter=65 if fast else 130, max_leaf_nodes=11,
                                              min_samples_leaf=30, l2_regularization=8,
                                              early_stopping=False, random_state=42)
    if name == 'Huber robust regression':
        # Robust to unusually large return observations; scaling is learned on fit data.
        return make_pipeline(StandardScaler(), HuberRegressor(epsilon=1.6, alpha=15.0,
                                                                max_iter=240))
    if name == 'RBF nonlinear ridge':
        # Random Fourier features approximate a nonlinear RBF kernel without O(n²) memory.
        return make_pipeline(StandardScaler(),
                             RBFSampler(gamma=0.12, n_components=96 if fast else 192,
                                        random_state=42), Ridge(alpha=25.0))
    if name == 'Median quantile boosting':
        # A median forecast treats heavy-tailed price jumps differently from squared loss.
        return HistGradientBoostingRegressor(loss='quantile', quantile=0.5,
                                              learning_rate=.055, max_iter=70 if fast else 140,
                                              max_leaf_nodes=11, min_samples_leaf=25,
                                              l2_regularization=8, early_stopping=False,
                                              random_state=42)
    if name == 'Explainable boosting (EBM)':
        module = importlib.import_module('interpret.glassbox')
        return module.ExplainableBoostingRegressor(interactions=0,
               max_rounds=120 if fast else 300, outer_bags=1, n_jobs=2, random_state=42)
    if name == 'ExtraTrees':
        return ExtraTreesRegressor(n_estimators=35 if fast else 90, max_depth=7,
                                   min_samples_leaf=12, max_features=0.75, random_state=42, n_jobs=2)
    if name == 'LightGBM':
        module = importlib.import_module('lightgbm')
        return module.LGBMRegressor(n_estimators=70 if fast else 180, max_depth=5,
                                    num_leaves=15, learning_rate=0.04, min_child_samples=25,
                                    random_state=42, n_jobs=2, verbosity=-1)
    if name == 'XGBoost':
        module = importlib.import_module('xgboost')
        return module.XGBRegressor(n_estimators=70 if fast else 180, max_depth=4,
                                    learning_rate=0.045, subsample=0.85, colsample_bytree=0.8,
                                    objective='reg:squarederror', tree_method='hist', n_jobs=2,
                                    random_state=42)
    if name == 'CatBoost':
        module = importlib.import_module('catboost')
        return module.CatBoostRegressor(iterations=70 if fast else 180, depth=4,
                                        learning_rate=0.04, loss_function='RMSE',
                                        random_seed=42, has_time=True,
                                        verbose=False, thread_count=2)
    raise ValueError('Unknown candidate')


def _forecast(model, data, cols):
    # Existing Ensemble.predict returns (predictions, disagreement).
    if hasattr(model, 'feature_names'):
        values, _ = model.predict(data)
    else:
        values = model.predict(data[list(cols)].to_numpy(dtype=float))
    return np.clip(np.asarray(values, dtype=float), -0.5, 0.5)


def _fit(name, train, cols, fast):
    if name == 'Existing ensemble':
        from .model import fit_ensemble
        return fit_ensemble(train, fast=fast, features=tuple(cols))
    model = _candidate(name, fast=fast)
    from .model import robust_target
    # Deterministic, chronological inputs for order-sensitive learners (e.g. CatBoost).
    ordered = train.sort_values(['date', 'ticker'], kind='mergesort') if 'ticker' in train else train.sort_values('date', kind='mergesort')
    model.fit(ordered[list(cols)].to_numpy(dtype=float),
              robust_target(ordered['target'].to_numpy(float)))
    return model


def finite_interval(errors, predictions, confidence=0.8, min_n=50):
    """Symmetric empirical residual-quantile interval; not a coverage guarantee."""
    residuals = np.asarray(errors, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    preds = np.asarray(predictions, dtype=float)
    if len(residuals) < min_n:
        return np.full_like(preds, np.nan), np.full_like(preds, np.nan)
    q = min(1.0, np.ceil((len(residuals) + 1) * confidence) / len(residuals))
    half = float(np.quantile(np.abs(residuals), q, method='higher'))
    return preds - half, preds + half


def asymmetric_conformal_interval(errors, predictions, confidence=0.8, min_n=80):
    """Date-held-out residual-quantile interval. Not guaranteed for nonstationary returns.

    Upper and lower empirical errors are corrected with an (n+1) finite-sample
    tail adjustment; use a distinct block from all model/feature selection.
    """
    residuals = np.asarray(errors, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    preds = np.asarray(predictions, dtype=float)
    empty = np.full_like(preds, np.nan)
    if len(residuals) < min_n or not (0 < confidence < 1):
        return empty.copy(), empty.copy()
    tail = (1-confidence)/2
    n = len(residuals)
    lo_q = max(0., np.floor((n+1)*tail)/n)
    hi_q = min(1., np.ceil((n+1)*(1-tail))/n)
    low_error = float(np.quantile(residuals, lo_q, method='lower'))
    high_error = float(np.quantile(residuals, hi_q, method='higher'))
    return preds + low_error, preds + high_error


def market_regime(benchmark: pd.Series, asof=None):
    """Observable SPY regime classification; no knowledge of later bars."""
    prices = benchmark.dropna().sort_index()
    if asof is not None:
        prices = prices.loc[prices.index <= pd.Timestamp(asof)]
    if len(prices) < 65:
        return {'name':'Insufficient data', 'momentum_20':np.nan, 'volatility_20':np.nan,
                'description':'Need 65 historical trading sessions.'}
    r = prices.pct_change(fill_method=None).dropna()
    momentum = float(prices.iloc[-1] / prices.iloc[-21] - 1)
    volatility = float(r.tail(20).std() * np.sqrt(252))
    if volatility >= 0.3:
        name = 'High volatility'
    elif momentum >= 0.04:
        name = 'Upward trend'
    elif momentum <= -0.04:
        name = 'Market decline'
    else:
        name = 'Range-bound'
    return {'name':name, 'momentum_20':momentum, 'volatility_20':volatility,
            'description':'Rules-based SPY regime; descriptive, not an independently trained predictor.'}


def fit_validated_forecaster(train, current, feature_names, *, fast=True, confidence=0.8,
                             candidate_names=None):
    """Train model, select on purged validation, audit on separate purged calibration.

    On insufficient history, return the original ensemble and no fabricated intervals.
    Selection gate: at least 2% improvement on the baseline's validation MAE.
    Optional external ML libraries are skipped if not installed.
    """
    from .model import fit_ensemble
    cols = tuple(feature_names)
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(train['date'].unique())))
    if len(dates) < 480:
        model = fit_ensemble(train, fast=fast, features=cols)
        estimates = _forecast(model, current, cols)
        empty = np.full(len(estimates), np.nan)
        return LabResult(estimates, 'Existing ensemble', 0, np.nan, np.nan, np.nan, np.nan,
                         empty, empty, confidence, [],
                         'Insufficient mature history for separate purged model-selection and calibration periods.')
    # Four distinct blocks: fit -> forecast-scale calibration -> model selection
    # -> final error audit. Every boundary purges overlapping label outcomes.
    scale_start, selection_start, calibration_start = dates[-240], dates[-160], dates[-80]
    earliest, scale_all = purged_split(train, scale_start, selection_start)
    scaling = scale_all.loc[pd.to_datetime(scale_all['label_end']) < selection_start]
    _, valid_all = purged_split(train, selection_start, calibration_start)
    validation = valid_all.loc[pd.to_datetime(valid_all['label_end']) < calibration_start]
    candidate_training, audit_all = purged_split(train, calibration_start)
    if (len(earliest) < 350 or min(len(scaling), len(validation), len(audit_all)) < 50):
        model = fit_ensemble(train, fast=fast, features=cols)
        estimates = _forecast(model, current, cols)
        empty = np.full(len(estimates), np.nan)
        return LabResult(estimates, 'Existing ensemble', 0, np.nan, np.nan, np.nan, np.nan,
                         empty, empty, confidence, [], 'Insufficient purged fit/scale/selection/audit samples.')

    from .model import shrinkage_factor
    scale_truth = scaling['target'].to_numpy(dtype=float)
    truth = validation['target'].to_numpy(dtype=float)
    baseline_model = _fit('Existing ensemble', earliest, cols, fast)
    base_scale = shrinkage_factor(scale_truth, _forecast(baseline_model, scaling, cols))
    base_pred = _forecast(baseline_model, validation, cols) * base_scale
    baseline_mae = float(np.abs(truth - base_pred).mean())
    best_name, best_mae = 'Existing ensemble', baseline_mae
    shrink = base_scale
    attempted = []
    names = candidate_names if candidate_names is not None else (
        'Ridge', 'Huber robust regression', 'RBF nonlinear ridge',
        'Median quantile boosting', 'Robust MAE boosting', 'ExtraTrees',
        'LightGBM', 'XGBoost', 'CatBoost', 'Explainable boosting (EBM)')
    # EBM is opt-in via the optional InterpretML installation; missing packages are skipped.

    for name in names:
        try:
            candidate = _fit(name, earliest, cols, fast)
            candidate_scale = shrinkage_factor(scale_truth, _forecast(candidate, scaling, cols))
            predictions = _forecast(candidate, validation, cols) * candidate_scale
            error = float(np.abs(truth - predictions).mean())
            attempted.append(f'{name}: {error:.4f}')
            if np.isfinite(error) and error < baseline_mae * 0.98 and error < best_mae:
                best_name, best_mae, shrink = name, error, candidate_scale
        except ImportError:
            attempted.append(f'{name}: optional package not installed')
        except (ValueError, TypeError, FloatingPointError) as exc:
            attempted.append(f'{name}: unavailable ({type(exc).__name__})')

    # Calibration block is not used to pick the winner.
    # Scale was learned on the SELECTION block only, so audit errors stay out-of-sample.
    audit_model = _fit(best_name, candidate_training, cols, fast)
    audit_pred = _forecast(audit_model, audit_all, cols) * shrink
    audit_true = audit_all['target'].to_numpy(float)
    errors = audit_true - audit_pred
    final_model = _fit(best_name, train, cols, fast)
    estimates = _forecast(final_model, current, cols) * shrink
    low, high = asymmetric_conformal_interval(errors, estimates, confidence=confidence)
    # Counterfactual one-feature replacement is sensitivity, NOT causal attribution.
    explanations = []
    if not current.empty:
        row = current.iloc[[0]].copy()
        baseline = float(_forecast(final_model, row, cols)[0]) * shrink
        medians = train[list(cols)].median()
        for col in cols:
            alt = row.copy()
            alt[col] = medians[col]
            delta = baseline - float(_forecast(final_model, alt, cols)[0]) * shrink
            if np.isfinite(delta):
                explanations.append((col, delta))
        explanations = [f'{c}: {v:+.2%} sensitivity' for c,v in
                        sorted(explanations, key=lambda x: abs(x[1]), reverse=True)[:5]]
    return LabResult(estimates, best_name, len(audit_all),
                     float(np.abs(errors).mean()), float(np.abs(audit_true).mean()),
                     best_mae, baseline_mae, low, high, confidence, explanations,
                     'Four purged periods: fit, independent scale calibration, selection, final audit. '
                     'Asymmetric held-out residual intervals are not guaranteed under market regime shifts. '
                     'Validation candidates: ' + '; '.join(attempted)
                     + f'; forecast scale {shrink:.2f} (learned before selection block)', shrink)
