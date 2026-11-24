"""Cloud-safe historical validation scope tests; not evidence of market accuracy."""
import pandas as pd
import pytest

from ithaca_quant.validation_limits import (
    browser_validation_sample, BROWSER_MAX_PANEL_ROWS,
    BROWSER_MAX_PERIODS, BROWSER_MAX_SYMBOLS,
)
from ithaca_quant.backtest import run_walk_forward
from ithaca_quant.features import build_panel
from ithaca_quant.data import demo_market_data


def fixture_panel(n=24, sessions=1080):
    symbols=['SPY']+[f'S{i:02d}' for i in range(n)]
    market=demo_market_data(symbols, sessions=sessions)
    return build_panel(market.close, market.volume, 20, raw_close=market.raw_close), market.close


def test_browser_validation_is_capped_and_includes_benchmark():
    panel, close=fixture_panel()
    small=browser_validation_sample(panel,close,portfolio_size=12,periods=20)
    assert len(small.tickers)==BROWSER_MAX_SYMBOLS
    assert small.excluded_tickers==24-BROWSER_MAX_SYMBOLS
    assert small.periods==BROWSER_MAX_PERIODS
    assert small.portfolio_size==12
    assert list(small.close.columns)[0]=='SPY'
    assert set(small.panel.ticker)==set(small.tickers)
    assert len(small.panel)<=BROWSER_MAX_PANEL_ROWS


def test_browser_symbol_choice_does_not_depend_on_future_returns():
    panel, close=fixture_panel(n=20)
    first=browser_validation_sample(panel,close,portfolio_size=6,periods=4)
    altered=panel.copy()
    altered['forward_return']=12345.0
    altered['target']=-9999.0
    second=browser_validation_sample(altered,close,portfolio_size=6,periods=4)
    assert first.tickers==second.tickers


def test_browser_rejects_missing_benchmark_and_small_universe():
    p,c=fixture_panel(n=6)
    with pytest.raises(ValueError,match='benchmark'):
        browser_validation_sample(p,c.drop(columns=['SPY']),portfolio_size=6,periods=4)
    with pytest.raises(ValueError,match='five'):
        browser_validation_sample(p[p.ticker.isin(['S00','S01','S02'])],c,portfolio_size=6,periods=4)


def test_browser_bound_works_with_eight_year_histories():
    p,c=fixture_panel(n=20,sessions=2016)
    sample=browser_validation_sample(p,c,portfolio_size=20,periods=24)
    assert sample.panel.date.nunique()<=1600
    assert len(sample.panel)<=BROWSER_MAX_PANEL_ROWS


def test_sampled_tournament_runs_real_walk_forward():
    p,c=fixture_panel(n=12,sessions=1040)
    s=browser_validation_sample(p,c,portfolio_size=6,periods=2)
    result=run_walk_forward(s.panel,s.close,horizon=20,top_n=s.portfolio_size,
                max_periods=s.periods,fast=True,competitive_agents=True)
    assert len(result.periods)==2
    assert result.metrics['competition_replayed'] is True
    assert not result.metrics['pit_universe_qualified']
    assert set(result.predictions.ticker).issubset(set(s.tickers))
