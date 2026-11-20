"""v2.2 independent calibration, extra candidate, and honest direction uncertainty."""
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.features import FEATURES
from ithaca_quant.model import _choose_with_scale
from ithaca_quant.research_lab import _candidate
from ithaca_quant.validation import window_direction_lift_interval, overall_quality


def test_model_scale_does_not_depend_on_future_feature_selection_labels():
    dates = pd.bdate_range('2023-01-02', periods=470)
    rng = np.random.default_rng(7)
    rows = []
    for i, day in enumerate(dates):
        for ticker in ('AAA', 'BBB', 'CCC'):
            row = dict(date=day, label_end=dates[min(i + 20, len(dates)-1)],
                       ticker=ticker, target=rng.normal(0, .03))
            row.update({f: rng.normal(0, 1) for f in FEATURES})
            rows.append(row)
    data = pd.DataFrame(rows)
    _, _, old_errors, scale = _choose_with_scale(data, dates[-1], fast=True)
    altered = data.copy()
    # The final 90 sessions are only for selection, not scale fit.
    altered.loc[altered.date >= dates[-90], 'target'] += 0.30
    _, _, errors, same_scale = _choose_with_scale(altered, dates[-1], fast=True)
    assert scale == pytest.approx(same_scale, abs=1e-12)
    assert errors[0] > old_errors[0]


def test_robust_mae_candidate_trains_on_heavy_tail_sample():
    x = np.arange(150, dtype=float).reshape(-1, 1)
    y = np.sin(x[:, 0] / 10)
    y[-1] = 200
    model = _candidate('Robust MAE boosting')
    model.fit(x, y)
    p = model.predict(x[:4])
    assert np.isfinite(p).all()
    assert np.abs(p).max() < 20


def test_window_bootstrap_resamples_dates_and_is_not_reported_for_three_windows():
    rows = []
    for i in range(15):
        date = pd.Timestamp('2025-01-01') + pd.Timedelta(days=25 * i)
        for t in ['AAA', 'BBB', 'CCC', 'DDD']:
            rows.append(dict(signal_date=date, end_date=date + pd.Timedelta(days=20), ticker=t,
                             pred_excess=.05, realized_excess=.02, realized_return=.03,
                             benchmark_return=.01, p_gain=.4, p_boom=.1,
                             gain_baseline=.5, boom_baseline=.1, gain_event=1, boom_event=0,
                             naive_direction_positive=False))
    data = pd.DataFrame(rows)
    lift, lo, hi = window_direction_lift_interval(data)
    assert (lift, lo, hi) == pytest.approx((1.0, 1.0, 1.0))
    assert np.isnan(window_direction_lift_interval(data.head(12))[1])
    quality = overall_quality(data)
    assert quality['window_direction_lift_low'] == pytest.approx(1.)
