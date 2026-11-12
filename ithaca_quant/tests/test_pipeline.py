import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import demo_market_data, parse_tickers
from ithaca_quant.features import build_panel, FEATURES
from ithaca_quant.model import training_snapshot, forecast_asof
from ithaca_quant.backtest import run_walk_forward
from ithaca_quant.portfolio import validate_allocations, simulate_buy_hold, historical_risk

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "ORCL", "JPM"]


@pytest.fixture(scope="module")
def data():
    return demo_market_data(TICKERS, sessions=940)


@pytest.fixture(scope="module")
def panel(data):
    return build_panel(data.close, data.volume, horizon=20)


def test_ticker_parser():
    assert parse_tickers("aapl, NVDA SPY AAPL, MSFT") == ["AAPL", "NVDA", "MSFT"]


def test_future_targets_only_in_labels(panel):
    latest = panel["date"].max()
    assert len(panel.loc[panel.date == latest]) == len(TICKERS)
    assert panel.loc[panel.date == latest, "target"].isna().all()
    earlier = latest - pd.Timedelta(days=75)
    train = training_snapshot(panel, earlier)
    assert not train.empty
    assert (train["label_end"] < earlier).all()
    assert (train["date"] < earlier).all()


def test_forecast_rankings(panel):
    result = forecast_asof(panel, panel.date.max(), fast=True)
    assert len(result) == len(TICKERS)
    assert np.isfinite(result["forecast_excess"]).all()
    assert result["forecast_excess"].is_monotonic_decreasing


def test_nonoverlapping_walkforward(panel, data):
    result = run_walk_forward(panel, data.close, horizon=20, top_n=6,
                              max_periods=3, fast=True)
    assert len(result.periods) == 3
    assert (result.periods["date"].iloc[1:].to_numpy() >=
            result.periods["end"].iloc[:-1].to_numpy()).all()
    assert np.isfinite(result.metrics["portfolio_return"])


def test_portfolio_limits_and_math(data):
    when = data.close.index[-80]
    alloc = {t: 0.15 for t in TICKERS[:6]}
    assert validate_allocations(alloc, data.close, when) == []
    equity, holdings, cash = simulate_buy_hold(data.close, when, alloc)
    assert abs(equity.portfolio.iloc[0] - 1_000_000) < 1e-5
    assert cash >= 100_000 - 1e-3
    assert np.isfinite(equity.portfolio).all()
    assert validate_allocations({t: 0.3 for t in TICKERS[:5]}, data.close, when)
    risk = historical_risk(data.close.loc[:when], alloc)
    assert risk["annualized_volatility"] >= 0


def test_probability_event_is_point_in_time(panel):
    from ithaca_quant.probability import fit_event_model, annotate_probabilities
    latest = panel.date.max()
    mature = training_snapshot(panel, latest)
    event_model = fit_event_model(mature, event_return=0.10)
    assert (mature['label_end'] < latest).all()
    assert event_model.rows == len(mature)
    recent = panel[panel.date == latest]
    annotated = annotate_probabilities(recent, mature, boom_return=0.10)
    assert 0 <= annotated['boom_base_rate'].iloc[0] <= 1
    if event_model.classifier is not None:
        assert annotated['prob_boom'].between(0, 1).all()
        assert annotated['prob_gain'].between(0, 1).all()
        assert np.isfinite(annotated['boom_holdout_brier']).all()


def test_probability_rare_event_has_no_fabricated_odds(panel):
    from ithaca_quant.probability import fit_event_model
    model = fit_event_model(training_snapshot(panel, panel.date.max()), event_return=10.0)
    assert model.classifier is None
    assert np.isnan(model.predict(panel.head(2))).all()


def test_signal_risk_budget_position_cap(panel):
    from ithaca_quant.model import forecast_asof
    from ithaca_quant.signals import plan_signals
    ranking = forecast_asof(panel, panel.date.max(), fast=True, boom_return=0.10)
    plans = plan_signals(ranking, horizon=20, risk_budget_pct=1)
    assert plans['max_starter_value'].le(250_000.001).all()
    assert (plans['max_starter_value'] * plans['stop_pct'] <= 10_000.01).all()
    assert plans['entry_watch'].isin(['ENTRY WATCH','WATCH / CONFIRM','WAIT']).all()
    assert plans['exit_review'].isin(['REVIEW EXIT','MONITOR']).all()


def test_backtest_boom_probabilities_are_evaluated(panel, data):
    result = run_walk_forward(panel, data.close, horizon=20, top_n=6,
                              max_periods=3, fast=True, boom_return=0.10)
    assert result.metrics['boom_evaluated_predictions'] > 0
    assert np.isfinite(result.metrics['boom_brier'])
    assert np.isfinite(result.metrics['boom_baseline_brier'])


def test_walkforward_saves_each_unseen_prediction(panel, data):
    from ithaca_quant.validation import overall_quality, per_ticker_quality
    result = run_walk_forward(panel, data.close, horizon=20, top_n=6,
                              max_periods=3, fast=True, boom_return=0.10)
    scored = result.predictions
    assert not scored.empty
    assert len(scored) == len(TICKERS) * len(result.periods)
    assert set(scored['ticker']) == set(TICKERS)
    assert not scored.duplicated(['ticker', 'signal_date']).any()
    assert (scored['end_date'] > scored['signal_date']).all()
    for col in ['p_gain', 'p_boom']:
        assert scored[col].dropna().between(0, 1).all()
    assert (abs(scored['realized_return'] - scored['benchmark_return'] -
                scored['realized_excess']) < 1e-8).all()
    q = overall_quality(scored)
    assert q['signal_windows'] == len(result.periods)
    assert (per_ticker_quality(scored)['oos_windows'] == len(result.periods)).all()
