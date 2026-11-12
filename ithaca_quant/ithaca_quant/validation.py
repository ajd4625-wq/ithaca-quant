"""Auditable out-of-sample forecast evidence, separate from current model scores.

All outcomes here must be sourced from the walk-forward evaluator, which evaluates
forecasts at past signal dates using models trained only on then-matured labels.
Cross-sectional samples from the same signal period are correlated, so a large
number of ticker-window rows does NOT imply equally many independent tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED = (
    'signal_date', 'end_date', 'ticker', 'pred_excess', 'realized_excess',
    'realized_return', 'benchmark_return', 'p_gain', 'p_boom',
    'gain_baseline', 'boom_baseline', 'gain_event', 'boom_event',
    'naive_direction_positive',
)


def validate_oos_data(data: pd.DataFrame) -> None:
    missing = set(REQUIRED).difference(data.columns)
    if missing:
        raise ValueError('Missing walk-forward prediction fields: ' + ', '.join(sorted(missing)))
    if not data.empty:
        starts = pd.to_datetime(data['signal_date'])
        ends = pd.to_datetime(data['end_date'])
        if not (ends > starts).all():
            raise ValueError('An outcome was evaluated before its forecast horizon ended.')
        if data.duplicated(['ticker', 'signal_date']).any():
            raise ValueError('Duplicate ticker/date out-of-sample evaluation.')


def _brier(table: pd.DataFrame, probability: str, event: str) -> tuple[float, int]:
    p = pd.to_numeric(table[probability], errors='coerce')
    y = pd.to_numeric(table[event], errors='coerce')
    valid = p.between(0, 1) & y.isin([0, 1])
    if not valid.any():
        return np.nan, 0
    return float(np.mean(np.square(p.loc[valid] - y.loc[valid]))), int(valid.sum())


def overall_quality(data: pd.DataFrame) -> dict[str, float | int | str]:
    validate_oos_data(data)
    if data.empty:
        return {'ticker_outcomes': 0, 'signal_windows': 0,
                'evidence': 'Not tested', 'direction_hit': np.nan,
                'direction_baseline': np.nan, 'excess_mae': np.nan,
                'excess_zero_mae': np.nan, 'gain_brier': np.nan,
                'gain_baseline_brier': np.nan, 'boom_brier': np.nan,
                'boom_baseline_brier': np.nan, 'boom_scored': 0, 'gain_scored': 0}
    predicted_positive = pd.to_numeric(data['pred_excess']) > 0
    observed_positive = pd.to_numeric(data['realized_excess']) > 0
    naive_direction = data['naive_direction_positive'].astype(bool)
    event_brier, boom_n = _brier(data, 'p_boom', 'boom_event')
    event_baseline, _ = _brier(data.loc[data['p_boom'].notna()], 'boom_baseline', 'boom_event')
    gain_brier, gain_n = _brier(data, 'p_gain', 'gain_event')
    gain_baseline, _ = _brier(data.loc[data['p_gain'].notna()], 'gain_baseline', 'gain_event')
    n_dates = int(pd.to_datetime(data['signal_date']).nunique())
    evidence = 'Insufficient windows (<12)' if n_dates < 12 else 'Preliminary only — not verified live'
    if np.isfinite(event_brier) and np.isfinite(event_baseline) and event_brier >= event_baseline:
        evidence += '; boom model did not beat baseline'
    return {
        'ticker_outcomes': int(len(data)),
        'signal_windows': n_dates,
        'evidence': evidence,
        'direction_hit': float((predicted_positive == observed_positive).mean()),
        'direction_baseline': float((naive_direction == observed_positive).mean()),
        'excess_mae': float(np.mean(abs(data['pred_excess'] - data['realized_excess']))),
        'excess_zero_mae': float(np.mean(abs(data['realized_excess']))),
        'gain_brier': gain_brier, 'gain_baseline_brier': gain_baseline,
        'boom_brier': event_brier, 'boom_baseline_brier': event_baseline,
        'boom_scored': boom_n, 'gain_scored': gain_n,
    }


def per_ticker_quality(data: pd.DataFrame) -> pd.DataFrame:
    """Only historical observations from this ticker; flags sample limitations."""
    validate_oos_data(data)
    columns = ['ticker', 'oos_windows', 'oos_direction_hit', 'oos_excess_mae',
               'oos_excess_baseline_mae', 'oos_boom_brier',
               'oos_boom_baseline_brier', 'oos_boom_n', 'oos_boom_avg_p',
               'oos_boom_realized_rate', 'oos_evidence']
    if data.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for ticker, sub in data.groupby('ticker', sort=True):
        p = sub['p_boom'].astype(float)
        observed = sub['boom_event'].astype(float)
        valid = p.between(0, 1) & observed.isin([0, 1])
        brier, n = _brier(sub, 'p_boom', 'boom_event')
        base_brier, _ = _brier(sub.loc[valid], 'boom_baseline', 'boom_event')
        n_windows = int(sub['signal_date'].nunique())
        if n_windows < 12:
            label = 'Too few OOS windows'
        elif n < 12:
            label = 'Boom odds untested'
        elif brier >= base_brier:
            label = 'Boom model lagged baseline'
        else:
            label = 'Preliminary; unverified live'
        rows.append({
            'ticker': ticker, 'oos_windows': n_windows,
            'oos_direction_hit': float(((sub['pred_excess'] > 0) ==
                                        (sub['realized_excess'] > 0)).mean()),
            'oos_excess_mae': float(np.mean(abs(sub['pred_excess'] - sub['realized_excess']))),
            'oos_excess_baseline_mae': float(np.mean(abs(sub['realized_excess']))),
            'oos_boom_brier': brier, 'oos_boom_baseline_brier': base_brier,
            'oos_boom_n': n,
            'oos_boom_avg_p': float(p.loc[valid].mean()) if n else np.nan,
            'oos_boom_realized_rate': float(observed.loc[valid].mean()) if n else np.nan,
            'oos_evidence': label,
        })
    return pd.DataFrame(rows, columns=columns)


def calibration_bins(data: pd.DataFrame, event: str, bins: tuple[float, ...] = (0, .1, .2, .4, .6, .8, 1)) -> pd.DataFrame:
    """Empirical reliability table; no adjustments are made to current probabilities."""
    validate_oos_data(data)
    if event not in ('gain', 'boom'):
        raise ValueError('event must be gain or boom')
    columns = ['bucket', 'n', 'mean_predicted', 'observed_frequency', 'difference']
    if data.empty:
        return pd.DataFrame(columns=columns)
    prob = pd.to_numeric(data['p_' + event], errors='coerce')
    event_flag = pd.to_numeric(data[event + '_event'], errors='coerce')
    valid = prob.between(0, 1) & event_flag.isin([0, 1])
    if not valid.any():
        return pd.DataFrame(columns=columns)
    cut = pd.cut(prob[valid], bins=bins, include_lowest=True, right=True)
    sub = pd.DataFrame({'bucket': cut, 'p': prob[valid], 'y': event_flag[valid]})
    grouped = sub.groupby('bucket', observed=True).agg(n=('y', 'size'), mean_predicted=('p', 'mean'),
                                                        observed_frequency=('y', 'mean')).reset_index()
    grouped['bucket'] = grouped['bucket'].map(lambda x: f'{max(0, x.left):.0%}–{x.right:.0%}').astype(str)
    grouped['difference'] = grouped['observed_frequency'] - grouped['mean_predicted']
    return grouped[columns]


def attach_quality(display: pd.DataFrame, data: pd.DataFrame | None, *, ticker_column: str = 'Ticker') -> pd.DataFrame:
    """Add OOS fields to a ranking without ever altering its model rank."""
    frame = display.copy()
    if data is None:
        frame['OOS windows'] = 0
        frame['OOS direction hit'] = np.nan
        frame['OOS forecast MAE'] = np.nan
        frame['OOS zero-forecast MAE'] = np.nan
        frame['OOS boom Brier'] = np.nan
        frame['OOS boom baseline Brier'] = np.nan
        frame['OOS boom scored'] = 0
        frame['OOS evidence'] = 'Not tested'
        return frame
    metrics = per_ticker_quality(data)
    renamed = metrics.rename(columns={
        'ticker': ticker_column, 'oos_windows': 'OOS windows',
        'oos_direction_hit': 'OOS direction hit',
        'oos_excess_mae': 'OOS forecast MAE',
        'oos_excess_baseline_mae': 'OOS zero-forecast MAE',
        'oos_boom_brier': 'OOS boom Brier',
        'oos_boom_baseline_brier': 'OOS boom baseline Brier',
        'oos_boom_n': 'OOS boom scored', 'oos_evidence': 'OOS evidence'
    })
    desired = [ticker_column, 'OOS windows', 'OOS direction hit', 'OOS forecast MAE',
               'OOS zero-forecast MAE', 'OOS boom Brier', 'OOS boom baseline Brier',
               'OOS boom scored', 'OOS evidence']
    # Preserve row order and leaderboard ranks.
    frame = frame.merge(renamed[desired], on=ticker_column, how='left', sort=False, validate='many_to_one')
    frame['OOS windows'] = frame['OOS windows'].fillna(0).astype(int)
    frame['OOS boom scored'] = frame['OOS boom scored'].fillna(0).astype(int)
    frame['OOS evidence'] = frame['OOS evidence'].fillna('Not tested')
    return frame
