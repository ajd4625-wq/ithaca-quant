"""Regression checks for independent single-ticker explorer and forecast chart."""
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.explorer import (
    CHART_PERIODS, close_from_yfinance, forecast_segment, select_history_window,
    validate_symbol,
)
from ithaca_quant.data import demo_market_data
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof


def test_ranges_and_last_observation():
    data = pd.Series(np.arange(252 * 6, dtype=float) + 10,
                     index=pd.bdate_range('2020-01-01', periods=252 * 6))
    assert CHART_PERIODS == ("1D", "5D", "1M", "6M", "YTD", "5Y")
    for window in CHART_PERIODS:
        subset = select_history_window(data, window)
        assert not subset.empty and subset.index[-1] == data.index[-1]
        assert subset.is_monotonic_increasing
    assert len(select_history_window(data, '5Y')) < len(data)
    assert len(select_history_window(data, '6M')) < len(select_history_window(data, '5Y'))
    assert select_history_window(data, 'YTD').index[0].year == data.index[-1].year


def test_exact_intraday_window_and_future_dotted_endpoints():
    ix = pd.to_datetime(['2026-11-11 09:30', '2026-11-11 10:30', '2026-11-12 09:30'])
    s = pd.Series([10., 11., 12.], index=ix)
    one_day = select_history_window(s, '1D')
    assert len(one_day) == 1 and one_day.iloc[-1] == 12
    xs, ys = forecast_segment(one_day.index[-1], 12, 15, 20)
    assert len(xs) == len(ys) == 2  # no made-up daily points
    assert ys == [12, 15]
    assert xs[1] > xs[0]


def test_symbol_validation():
    assert validate_symbol(' nvda ') == 'NVDA'
    assert validate_symbol('brk-b') == 'BRK-B'
    for bad in ['', 'NYSE/NASDAQ', 'NVDA;DROP', 'A' * 20]:
        with pytest.raises(ValueError):
            validate_symbol(bad)


def test_price_parser_single_and_multiindex():
    idx = pd.date_range('2026-11-11', periods=2, freq='h', tz='UTC')
    base = pd.DataFrame({'Close':[12.,13.], 'Volume':[15,22]}, index=idx)
    close = close_from_yfinance(base, 'AMD')
    assert list(close) == [12,13]
    assert close.index.tz is None
    grouped = pd.concat({'AMD':base}, axis=1)
    assert list(close_from_yfinance(grouped,'AMD')) == [12,13]
    assert close_from_yfinance(grouped,'TSLA').empty


def test_single_ticker_forecast_does_not_need_other_stocks():
    market = demo_market_data(['AMD'],sessions=252*5)
    assert set(market.close.columns) == {'SPY','AMD'}
    panel = build_panel(market.close, market.volume, horizon=20)
    row = forecast_asof(panel, panel['date'].max(), fast=True, boom_return=0.2)
    assert list(row['ticker']) == ['AMD']
    assert np.isfinite(row['forecast_excess'].iloc[0])


def test_no_unknown_period():
    with pytest.raises(ValueError):
        select_history_window(pd.Series([1],index=pd.date_range('2026-11-12',periods=1)), 'MAX')


def test_lookups_precede_the_full_market_scanner():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text()
    assert source.index('with st.form("top_ticker_search"') < source.index('scan_table = None')
    assert source.index('if workspace.startswith("⚡") or quick_submit:') < source.index('scan_table = None')
    assert 'st.session_state["workspace_mode"] = "⚡ Instant stock explorer"' in source
