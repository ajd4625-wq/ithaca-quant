"""Regression coverage for v1.4.1 session window, financial display, forecasts."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ithaca_quant.data import demo_market_data
from ithaca_quant.explorer import (
    chart_axis_range, intraday_projection, select_1d_display_window,
)
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.presentation import format_money, format_financial_table

ET = ZoneInfo("America/New_York")


def test_quarterly_numbers_have_commas_and_dates_and_source_is_unchanged():
    raw = pd.DataFrame({
        "period_end": [pd.Timestamp("2026-09-30"), pd.Timestamp("2026-06-30")],
        "filed": [pd.Timestamp("2026-11-03"), pd.NaT],
        "revenue_usd": [145_234_567_890, np.nan],
        "net_income_usd": [-1_234_567_890, 0.0],
        "revenue_yoy": [.12754, np.nan],
        "net_margin": [-.08435, .1],
        "diluted_eps": [1.1875, np.nan],
    })
    rendered = format_financial_table(raw)
    assert rendered.iloc[0]["Revenue (USD)"] == "$145,234,567,890"
    assert rendered.iloc[1]["Revenue (USD)"] == "Not reported"
    assert rendered.iloc[0]["Net income (USD)"] == "-$1,234,567,890"
    assert rendered.iloc[1]["Net income (USD)"] == "$0"
    assert rendered.iloc[0]["Revenue growth (YoY)"] == "+12.8%"
    assert rendered.iloc[0]["Net margin"] == "-8.4%"
    assert rendered.iloc[0]["Diluted EPS (USD)"] == "$1.19"
    assert rendered.iloc[0]["Filed with SEC"] == "Nov 03, 2026"
    assert pd.isna(raw.iloc[1]["revenue_usd"])
    assert raw.iloc[0]["revenue_usd"] == 145_234_567_890
    assert format_money("bad") == "Not reported"


def test_one_day_shows_only_today_830_to_1600_eastern_even_after_hours():
    bars = pd.to_datetime(["2026-11-11 09:30", "2026-11-12 08:00", "2026-11-12 08:30",
                           "2026-11-12 09:30", "2026-11-12 16:00", "2026-11-12 16:05"])
    prices = pd.Series(range(6), index=bars, dtype=float)
    shown = select_1d_display_window(prices, now_et=datetime(2026, 11, 12, 21, 0, tzinfo=ET))
    assert list(shown.index) == list(bars[2:5])
    assert chart_axis_range(shown, "1D") == [pd.Timestamp("2026-11-12 08:30"), pd.Timestamp("2026-11-12 16:00")]
    assert chart_axis_range(shown, "1D", pd.Timestamp("2026-11-13 12:00"))[1] == pd.Timestamp("2026-11-12 16:00")
    assert select_1d_display_window(prices, now_et=datetime(2026, 11, 13, 11, 0, tzinfo=ET)).empty


def test_1d_timezone_aware_prices_render_in_eastern_wall_clock():
    utc_bars = pd.date_range("2026-07-09 12:00", periods=5, freq="30min", tz="UTC")
    prices = pd.Series(np.arange(5, dtype=float), index=utc_bars)
    shown = select_1d_display_window(prices, now_et=datetime(2026, 7, 9, 13, 0, tzinfo=ET))
    # UTC 12:00 = 8:00 Eastern in July; 8:00 excluded, 8:30 onward included.
    assert shown.index[0] == pd.Timestamp("2026-07-09 08:30")
    assert shown.index.tz is None


def test_after_close_hourly_projection_disabled_not_faked():
    stamps = pd.date_range("2026-11-12 15:00", periods=12, freq="5min")
    prices = pd.Series(np.linspace(99, 101, 12), index=stamps)
    assert intraday_projection(prices, now_et=datetime(2026, 11, 12, 15, 56, tzinfo=ET)) is not None
    assert intraday_projection(prices, now_et=datetime(2026, 11, 12, 16, 5, tzinfo=ET)) is None
    premarket = pd.Series(np.linspace(99, 101, 12), index=pd.date_range("2026-11-12 08:30", periods=12, freq="5min"))
    assert intraday_projection(premarket, now_et=datetime(2026, 11, 12, 9, 26, tzinfo=ET)) is None


def test_next_session_ml_forecast_remains_available_when_hourly_projection_closed():
    data = demo_market_data(["AAPL"], sessions=252 * 5)
    panel = build_panel(data.close, data.volume, horizon=1)
    estimate = forecast_asof(panel, panel["date"].max(), fast=True, boom_return=.2)
    assert estimate.iloc[0]["ticker"] == "AAPL"
    assert np.isfinite(estimate.iloc[0]["forecast_excess"])
    assert float(estimate.iloc[0]["close"]) > 0


def test_ui_wires_filing_formatting_and_separate_1d_ml_forecast():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert "format_financial_table(rows)" in source
    assert "format_financial_table(yahoo_facts.head(5))" in source
    assert "daily_model_horizon = chart_horizon if chart_horizon is not None else 1" in source
    assert "Next trading-session machine-learning outlook" in source
    assert 'first_day + pd.Timedelta(hours=16)' in source
    assert 'autorange=False' in source
