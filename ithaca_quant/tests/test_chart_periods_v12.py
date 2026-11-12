"""v1.2: charts represent exactly the chosen history and forecast horizon."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from ithaca_quant.explorer import (
    CHART_FORECAST_SESSIONS, CHART_FORECAST_LABELS, CHART_PERIODS,
    select_history_window, select_today_intraday, intraday_projection,
    forecast_segment, chart_axis_range,
)

ET = ZoneInfo("America/New_York")


def make_session(day="2026-11-12", start="11:35", steps=12, price=100):
    times = pd.date_range(f"{day} {start}", periods=steps, freq="5min")
    return pd.Series(price + np.linspace(0, 1, steps), index=times)


def test_specific_forecast_horizon_for_every_range():
    assert tuple(CHART_FORECAST_SESSIONS) == CHART_PERIODS
    assert [CHART_FORECAST_SESSIONS[k] for k in CHART_PERIODS] == [None, 1, 5, 20, 20, 60]
    assert len(CHART_FORECAST_LABELS) == len(CHART_PERIODS)


def test_one_day_only_today_and_not_yesterday():
    now = datetime(2026, 11, 12, 12, 31, tzinfo=ET)
    yday = make_session("2026-11-11")
    today = make_session()
    all_prices = pd.concat([yday, today])
    assert select_today_intraday(all_prices, now_et=now).equals(today)
    assert select_today_intraday(yday, now_et=now).empty


def test_1d_axes_confined_to_one_day_with_clock_timestamps():
    today = make_session()
    bounds = chart_axis_range(today, "1D", today.index[-1] + pd.Timedelta(hours=2))
    assert bounds[0] == pd.Timestamp("2026-11-12 00:00")
    assert bounds[1] == pd.Timestamp("2026-11-12 23:59:59")
    assert (bounds[1] - bounds[0]).total_seconds() < 24 * 3600


def test_5d_is_five_trading_sessions_despite_weekend():
    days = ["2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
    prices = pd.concat([make_session(day) for day in days])
    subset = select_history_window(prices, "5D")
    kept = pd.DatetimeIndex(subset.index).normalize().unique()
    assert len(kept) == 5
    assert kept[0] == pd.Timestamp("2026-11-06")
    assert kept[-1] == pd.Timestamp("2026-11-12")


def test_5d_forecast_next_session_near_4pm():
    xs, ys = forecast_segment(pd.Timestamp("2026-11-12 13:30"), 101, 102, 1)
    assert xs[-1] == pd.Timestamp("2026-11-13 16:00")
    assert ys == [101., 102.]


def test_intraday_projection_only_next_two_hours_and_no_invented_intermediate_bars():
    today = make_session()
    now = datetime(2026, 11, 12, 12, 31, tzinfo=ET)
    result = intraday_projection(today, now_et=now)
    assert result is not None
    assert result.end_time == pd.Timestamp("2026-11-12 14:30")
    assert result.minutes_ahead == 120
    assert np.isfinite(result.target) and result.target > 0


def test_intraday_projection_stops_at_regular_session_close():
    near_close = make_session(start="14:55", steps=12)
    now = datetime(2026, 11, 12, 15, 51, tzinfo=ET)
    result = intraday_projection(near_close, now_et=now)
    assert result is not None
    assert result.end_time == pd.Timestamp("2026-11-12 16:00")
    assert result.minutes_ahead == 10
    after_close = datetime(2026, 11, 12, 16, 10, tzinfo=ET)
    assert intraday_projection(near_close, now_et=after_close) is None


def test_intraday_projection_stale_or_old_session_disabled():
    data = make_session()
    assert intraday_projection(data, now_et=datetime(2026, 11, 12, 15, 30, tzinfo=ET)) is None
    assert intraday_projection(data, now_et=datetime(2026, 11, 13, 12, 30, tzinfo=ET)) is None
    assert intraday_projection(data.iloc[:3], now_et=datetime(2026, 11, 12, 12, 30, tzinfo=ET)) is None


def test_other_periods_do_not_leak_older_history():
    series = pd.Series(range(2000), index=pd.bdate_range("2019-01-01", periods=2000))
    for period in ("1M", "6M", "YTD", "5Y"):
        selected = select_history_window(series, period)
        assert selected.index[-1] == series.index[-1]
        assert selected.index[0] >= (series.index[-1] - pd.DateOffset(years=5))
        assert len(selected) <= len(series)


def test_app_uses_1d_intraday_heuristic_and_horizon_matched_daily_forecast():
    code = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert "select_today_intraday(intraday)" in code
    assert "chart_horizon = CHART_FORECAST_SESSIONS[periods]" in code
    assert "intraday_projection(chart_prices)" in code
    assert "dtick=4 * 60 * 60 * 1000" in code
    assert "if chart_prices.empty:" in code
