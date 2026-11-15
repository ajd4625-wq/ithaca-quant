"""v2.3: same-day-demeaned label (gated on independent data) and top-pick evidence."""
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import demo_market_data
from ithaca_quant.features import build_panel, FEATURES
from ithaca_quant.model import (fit_ensemble, choose_target_mode, mean_rank_ic,
                                training_snapshot, forecast_asof)
from ithaca_quant.validation import top_pick_report, overall_quality

TICKERS = [f"T{i:02d}" for i in range(14)]


@pytest.fixture(scope="module")
def panel():
    m = demo_market_data(TICKERS, sessions=1150)
    return build_panel(m.close, m.volume, horizon=20)


def test_demeaned_label_is_same_day_and_centered(panel):
    done = panel.dropna(subset=["target"])
    centered = done.groupby("date")["target_cs"].median().abs()
    assert centered.max() < 1e-9
    assert np.allclose(done["target_cs"] - done["target"],
                       -done.groupby("date")["target"].transform("median"))


def test_demeaned_label_ignores_tiny_universes():
    m = demo_market_data(["A", "B", "C"], sessions=400)
    small = build_panel(m.close, m.volume, horizon=20).dropna(subset=["target"])
    assert np.allclose(small["target"], small["target_cs"])  # fewer than 8 names: unchanged


def test_offset_restores_spy_relative_scale(panel):
    train = training_snapshot(panel, panel.date.max())
    raw = fit_ensemble(train, fast=True)
    cs = fit_ensemble(train, fast=True, target_col="target_cs")
    assert raw.offset == 0.0
    assert cs.offset == pytest.approx(float((train["target"] - train["target_cs"]).mean()))
    now = panel.loc[panel.date == panel.date.max()]
    assert abs(cs.predict(now)[0].mean() - raw.predict(now)[0].mean()) < 0.05


def test_mean_rank_ic():
    d = np.repeat(pd.date_range("2026-01-01", periods=4), 6)
    y = np.tile(np.arange(6.0), 4)
    assert mean_rank_ic(d, y, y) == pytest.approx(1.0)
    assert mean_rank_ic(d, -y, y) == pytest.approx(-1.0)
    assert np.isnan(mean_rank_ic(d[:3], y[:3], y[:3]))  # too few names per date


def _planted(train, skill, common_sd, seed):
    rng = np.random.default_rng(seed)
    day = train["date"].factorize()[0]
    common = rng.normal(0, common_sd, day.max() + 1)[day]          # shared market shock
    train = train.copy()
    train["target"] = common + skill * train["high_252_gap"].to_numpy() / 0.2 + rng.normal(0, .03, len(train))
    train["target_cs"] = train["target"] - train.groupby("date")["target"].transform("median")
    return train


def test_target_mode_adopted_when_shared_shocks_swamp_a_real_signal(panel):
    train = training_snapshot(panel, panel.date.max())
    features = tuple(FEATURES) + ("high_252_gap",)
    for seed in range(3):
        mode, scale, note = choose_target_mode(_planted(train, 0.02, 0.5, seed), features, fast=True)
        assert mode == "cs" and 0.15 <= scale <= 1.0 and "rank IC" in note


def test_target_mode_never_adopted_on_pure_noise(panel):
    train = training_snapshot(panel, panel.date.max())
    for seed in range(3):
        noise = _planted(train, 0.0, 0.5, seed)
        assert choose_target_mode(noise, tuple(FEATURES), fast=True)[0] == "raw"


def test_target_mode_respects_switches(panel, monkeypatch):
    train = training_snapshot(panel, panel.date.max())
    monkeypatch.setenv("ITHACA_DISABLE_CS_TARGET", "1")
    assert choose_target_mode(train, tuple(FEATURES), fast=True)[0] == "raw"
    monkeypatch.delenv("ITHACA_DISABLE_CS_TARGET")
    monkeypatch.setenv("ITHACA_LEGACY_MODEL", "1")
    assert choose_target_mode(train, tuple(FEATURES), fast=True)[0] == "raw"


def test_forecast_reports_mode_and_keeps_ranking(panel):
    out = forecast_asof(panel, panel.date.max(), fast=True)
    assert out["target_mode"].isin(["raw", "cs"]).all()
    assert out["forecast_excess"].is_monotonic_decreasing and np.isfinite(out["forecast_excess"]).all()


def _oos(pred_skill, windows=15, names=20, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for w in range(windows):
        real = rng.normal(0, .06, names)
        pred = pred_skill * real + rng.normal(0, .03, names)
        for i in range(names):
            rows.append({'signal_date': pd.Timestamp('2026-01-01') + pd.Timedelta(days=30 * w),
                         'end_date': pd.Timestamp('2026-01-01') + pd.Timedelta(days=30 * w + 28),
                         'ticker': f'X{i}', 'pred_excess': pred[i], 'realized_excess': real[i],
                         'realized_return': real[i], 'benchmark_return': 0.0, 'p_gain': .5, 'p_boom': .1,
                         'gain_baseline': .5, 'boom_baseline': .1, 'gain_event': int(real[i] > 0),
                         'boom_event': 0, 'naive_direction_positive': True})
    return pd.DataFrame(rows)


def test_top_pick_report_detects_skill_and_noise():
    skilled = top_pick_report(_oos(1.0))
    assert skilled['top_pick_spread'] > 0.03 and skilled['top_pick_spread_low'] > 0
    assert skilled['top_pick_hit'] > skilled['field_outperform_rate']
    noise = top_pick_report(_oos(0.0, seed=2))
    assert noise['top_pick_spread_low'] < 0 < noise['top_pick_spread_high']
    few = top_pick_report(_oos(1.0, windows=5))
    assert np.isnan(few['top_pick_spread_low']) and few['top_pick_windows'] == 5
    assert np.isnan(top_pick_report(_oos(1.0, names=3))['top_pick_spread'])  # too few names/date


def test_overall_quality_exposes_top_pick_fields():
    q = overall_quality(_oos(1.0))
    assert {'top_pick_spread', 'top_pick_hit', 'field_outperform_rate'} <= set(q)
    assert 'top_pick_spread' in overall_quality(_oos(1.0).iloc[0:0])
