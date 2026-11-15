"""v2.1 accuracy upgrades: point-in-time features, robust targets, calibrated scale,
probability blending, bad-tick sanitation and the legacy A/B switch."""
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.config import improved_accuracy
from ithaca_quant.data import demo_market_data, remove_bad_ticks
from ithaca_quant.features import build_panel, EXTENDED_FEATURES, FEATURES
from ithaca_quant.model import (forecast_asof, robust_target, shrinkage_factor,
                                choose_evidence_features, training_snapshot, MIN_SHRINKAGE)
from ithaca_quant.probability import EventModel, fit_event_model

TICKERS = [f"T{i:02d}" for i in range(12)]


@pytest.fixture(scope="module")
def market():
    return demo_market_data(TICKERS, sessions=1100)


@pytest.fixture(scope="module")
def panel(market):
    return build_panel(market.close, market.volume, horizon=20)


def test_extended_features_are_point_in_time(market, panel):
    """Cutting off the future must not change any feature value on earlier dates."""
    cut = market.close.index[800]
    short = build_panel(market.close.loc[:cut], market.volume.loc[:cut], horizon=20)
    cols = FEATURES + EXTENDED_FEATURES
    left = short.set_index(["date", "ticker"])[cols]
    right = panel.set_index(["date", "ticker"]).loc[left.index, cols]
    assert np.allclose(left.to_numpy(), right.to_numpy(), equal_nan=True)
    assert np.isfinite(panel[EXTENDED_FEATURES].to_numpy()).all()


def test_cross_sectional_ranks_are_same_day_and_bounded(panel):
    ranks = [c for c in EXTENDED_FEATURES if c.startswith("cs_rank_")]
    assert panel[ranks].min().min() >= 0 and panel[ranks].max().max() <= 1
    day = panel.loc[panel.date == panel.date.max()]
    assert abs(day["cs_rank_mom_20"].mean() - 0.5) < 0.1


def test_robust_target_winsorizes_extremes():
    rng = np.random.default_rng(0)
    y = np.append(rng.normal(0, .05, 5000), [0.79, -0.79, 0.75])
    clipped = robust_target(y)
    assert clipped.max() < 0.25 and clipped.min() > -0.25
    assert np.isclose(np.median(clipped), np.median(y))


def test_shrinkage_factor_behaviour():
    rng = np.random.default_rng(1)
    signal = rng.normal(0, .05, 4000)
    truth = signal + rng.normal(0, .05, 4000)
    assert shrinkage_factor(truth, signal) == pytest.approx(1.0, abs=0.08)
    noisy = signal + rng.normal(0, .15, 4000)  # over-dispersed predictions
    assert MIN_SHRINKAGE <= shrinkage_factor(truth, noisy) < 0.5
    assert shrinkage_factor(truth, rng.normal(0, .05, 4000)) == MIN_SHRINKAGE  # no skill
    assert shrinkage_factor(truth[:10], signal[:10]) == 1.0                    # too little data
    assert shrinkage_factor(truth, 5 * truth) == pytest.approx(0.2, abs=0.01)  # never amplifies


def test_shrinkage_never_changes_ranking_and_is_reported(panel):
    out = forecast_asof(panel, panel.date.max(), fast=True)
    assert out["forecast_excess"].is_monotonic_decreasing
    assert out["forecast_shrinkage"].between(MIN_SHRINKAGE, 1.0).all()
    assert out["forecast_excess"].nunique() == len(out)  # no ties introduced


def test_legacy_switch_restores_v20_behaviour(panel, monkeypatch):
    monkeypatch.setenv("ITHACA_LEGACY_MODEL", "1")
    assert not improved_accuracy()
    out = forecast_asof(panel, panel.date.max(), fast=True)
    assert (out["forecast_shrinkage"] == 1.0).all()
    assert shrinkage_factor([1.0] * 100, [0.1] * 100) == 1.0
    assert robust_target(np.array([5.0] * 300)).max() == 0.8
    features, _, _ = choose_evidence_features(
        training_snapshot(panel, panel.date.max()), panel.date.max(), fast=True)
    assert not set(EXTENDED_FEATURES) & set(features)


def test_extended_group_selected_only_when_it_improves_holdout(panel):
    asof = panel.date.max()
    train = training_snapshot(panel, asof).copy()
    rng = np.random.default_rng(3)
    # Noise only: the group must not be adopted merely because it exists.
    train["target"] = rng.normal(0, .06, len(train))
    noise_features, _, _ = choose_evidence_features(train, asof, fast=True)
    assert "high_252_gap" not in noise_features
    # A genuine, past-only relationship in the extended group is detected.
    train["target"] = 0.35 * train["high_252_gap"] + 0.15 * train["beta_60"] + rng.normal(0, .02, len(train))
    signal_features, note, maes = choose_evidence_features(train, asof, fast=True)
    assert "high_252_gap" in signal_features and "Extended" in note
    assert maes[1] < maes[0]


def test_remove_bad_ticks_masks_only_reversing_spikes():
    base = pd.Series(100.0 + np.arange(30) * 0.1, index=pd.bdate_range("2026-01-01", periods=30))
    spike = base.copy(); spike.iloc[10] *= 1.8                   # one-day bad print
    assert np.isnan(remove_bad_ticks(spike).iloc[10])
    assert remove_bad_ticks(spike).drop(spike.index[10]).notna().all()
    crash = base.copy(); crash.iloc[15:] *= 0.5                  # genuine persistent gap
    assert remove_bad_ticks(crash).notna().all()
    normal = base * (1 + 0.02 * np.sin(np.arange(30)))           # ordinary volatility
    assert remove_bad_ticks(normal).notna().all()
    last = base.copy(); last.iloc[-1] *= 2                       # unconfirmed final bar kept
    assert remove_bad_ticks(last).notna().all()


def test_probability_blend_pulls_useless_model_to_base_rate():
    class Always:
        def predict_proba(self, x):
            return np.column_stack([np.full(len(x), .1), np.full(len(x), .9)])
    rows = pd.DataFrame({name: [0.0, 1.0] for name in FEATURES})
    assert np.allclose(EventModel(Always(), .2, 50, 500, .3, .2, 100, blend=0.0).predict(rows), .2)
    assert np.allclose(EventModel(Always(), .2, 50, 500, .3, .2, 100, blend=.5).predict(rows), .55)
    assert np.allclose(EventModel(Always(), .2, 50, 500, .3, .2, 100).predict(rows), .9)


def test_fitted_event_model_blend_in_range_and_probabilities_valid(panel):
    train = training_snapshot(panel, panel.date.max())
    model = fit_event_model(train, event_return=0.0)
    assert 0.0 <= model.blend <= 1.0
    p = model.predict(panel.loc[panel.date == panel.date.max()])
    assert np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all()
