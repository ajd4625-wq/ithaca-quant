"""Single-symbol chart windows and clearly labeled, horizon-matched projections.

Short-window projections are *unvalidated statistical illustrations*, not
trained intraday AI predictions or recommendations to trade.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .retry import retry_call

CHART_PERIODS = ("1D", "5D", "1M", "6M", "YTD", "5Y")
ONE_DAY_DISPLAY_START = pd.Timedelta(hours=8, minutes=30)  # Eastern time
ONE_DAY_DISPLAY_END = pd.Timedelta(hours=16)  # Eastern time
# How far the *dotted extension* goes, NOT the historical-window length.
# The 1D hourly estimate is distinct from the daily ML research model.
CHART_FORECAST_SESSIONS = {"1D": None, "5D": 1, "1M": 5, "6M": 20,
                           "YTD": 20, "5Y": 60}
CHART_FORECAST_LABELS = {"1D": "Next up to 2 market hours", "5D": "Next trading session",
                         "1M": "Next 5 trading sessions", "6M": "Next 20 trading sessions",
                         "YTD": "Next 20 trading sessions", "5Y": "Next 60 trading sessions"}
EASTERN = ZoneInfo("America/New_York")


def validate_symbol(ticker: str) -> str:
    symbol = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol):
        raise ValueError("Enter a valid ticker (for example NVDA, AAPL, or BRK-B).")
    return symbol


def select_history_window(prices: pd.Series, period: str) -> pd.Series:
    """Return only observed points within the requested historical window.

    1D selects the most recent session present in the series; the app separately
    requires that session to match *today* in Eastern time, not yesterday.
    5D selects five observed distinct sessions, accounting for long weekends.
    """
    if period not in CHART_PERIODS:
        raise ValueError("Unsupported chart period")
    prices = prices.dropna().sort_index()
    if prices.empty:
        return prices
    latest = pd.Timestamp(prices.index[-1])
    if period == "1D":
        lower = latest.normalize()
    elif period == "5D":
        dates = pd.DatetimeIndex(prices.index).normalize()
        wanted = dates.unique()[-5:]
        return prices.loc[dates.isin(wanted)]
    elif period == "1M":
        lower = latest - pd.DateOffset(months=1)
    elif period == "6M":
        lower = latest - pd.DateOffset(months=6)
    elif period == "YTD":
        lower = pd.Timestamp(year=latest.year, month=1, day=1, tz=latest.tz)
    else:
        lower = latest - pd.DateOffset(years=5)
    return prices.loc[prices.index >= lower]


def select_today_intraday(prices: pd.Series, *, now_et: datetime | None = None) -> pd.Series:
    """Restrict 1D to the current New York calendar date (never yesterday)."""
    now_et = now_et or datetime.now(EASTERN)
    if now_et.tzinfo is None:
        raise ValueError("now_et must be timezone-aware")
    today = now_et.astimezone(EASTERN).date()
    if prices.empty:
        return prices
    dates = pd.DatetimeIndex(prices.index)
    if dates.tz is not None:
        dates = dates.tz_convert(EASTERN).tz_localize(None)
    return prices.loc[dates.date == today].sort_index()


def select_1d_display_window(prices: pd.Series, *, now_et: datetime | None = None) -> pd.Series:
    """Only today's real bars between 8:30 AM and 4 PM Eastern (no invented bars)."""
    today = select_today_intraday(prices, now_et=now_et)
    if today.empty:
        return today
    ix = pd.DatetimeIndex(today.index)
    if ix.tz is not None:
        # Provider price observations and the 1D chart must share the same
        # Eastern wall-clock coordinate system, including DST changes.
        ix = ix.tz_convert(EASTERN).tz_localize(None)
        today = today.copy()
        today.index = ix
    since_midnight = ix - ix.normalize()
    return today.iloc[np.flatnonzero((since_midnight >= ONE_DAY_DISPLAY_START) &
                                     (since_midnight <= ONE_DAY_DISPLAY_END))]


def next_market_session(asof: pd.Timestamp) -> pd.Timestamp:
    """Next nominal US business-session close; exchange holidays not modeled."""
    stamp = pd.Timestamp(asof)
    return stamp.normalize() + pd.offsets.BDay(1) + pd.Timedelta(hours=16)


def forecast_segment(last_timestamp, last_price: float, target_price: float, horizon: int):
    """One next-session-close endpoint (business-day calendar approximation)."""
    if horizon < 1 or not np.isfinite(last_price) or not np.isfinite(target_price) or last_price <= 0 or target_price <= 0:
        raise ValueError("Invalid forecast endpoint")
    start = pd.Timestamp(last_timestamp)
    next_close = start.normalize() + pd.offsets.BDay(horizon) + pd.Timedelta(hours=16)
    return [start, next_close], [float(last_price), float(target_price)]


@dataclass(frozen=True)
class IntradayProjection:
    end_time: pd.Timestamp
    target: float
    minutes_ahead: int
    move_pct: float


def intraday_projection(prices: pd.Series, *, now_et: datetime | None = None,
                        interval_minutes: int = 5, max_hours: int = 2) -> IntradayProjection | None:
    """Heuristic next-hours extrapolation using *observed* intraday prices.

    Not an ML model: recent log-return momentum is heavily shrunk toward zero
    and capped relative to observed short-term variation. No synthetic points
    between current price and the single forecast endpoint are generated.
    Never forecasts past the approximate regular-session close (4pm ET).
    """
    now_et = now_et or datetime.now(EASTERN)
    if now_et.tzinfo is None:
        raise ValueError("now_et must be timezone-aware")
    now_local = now_et.astimezone(EASTERN).replace(tzinfo=None)
    prices = prices.dropna().sort_index()
    if len(prices) < 6 or interval_minutes < 1 or max_hours < 1:
        return None
    # A premarket observation may be plotted on the 1D chart, but a
    # regular-session momentum estimate must be based on regular-session bars.
    today_prices = select_1d_display_window(prices, now_et=now_et)
    market_open = pd.Timestamp(now_local).normalize() + pd.Timedelta(hours=9, minutes=30)
    today_prices = today_prices.loc[today_prices.index >= market_open]
    if now_local < market_open or len(today_prices) < 6:
        return None
    last = pd.Timestamp(today_prices.index[-1])
    if last.tzinfo is not None:
        last = last.tz_convert(EASTERN).tz_localize(None)
    close_time = last.normalize() + pd.Timedelta(hours=16)
    # Outside market hours or stale historical bars are not forward predictions.
    if now_local >= close_time or last > now_local + pd.Timedelta(minutes=5):
        return None
    # If the quote hasn't updated for an hour, it is too stale to extrapolate.
    if now_local - last > pd.Timedelta(minutes=60):
        return None
    remaining = int((close_time - last).total_seconds() // 60)
    n = min(max_hours * 60, remaining) // interval_minutes
    if n < 1:
        return None
    recent = np.log(today_prices.astype(float)).diff().dropna().tail(15)
    recent = recent[np.isfinite(recent)]
    if len(recent) < 4:
        return None
    sigma = float(recent.std(ddof=1)) if len(recent) > 1 else 0.0
    mean = float(recent.mean())
    # Aggressively shrink a noisy, short-term signal; constrain exaggeration.
    per_bar_drift = float(np.clip(mean * 0.20, -max(0.0003, 0.35 * sigma), max(0.0003, 0.35 * sigma)))
    projected_log_move = float(np.clip(per_bar_drift * n,
                                        -min(0.08, max(0.015, 1.5 * sigma * np.sqrt(n))),
                                        min(0.08, max(0.015, 1.5 * sigma * np.sqrt(n)))))
    target = float(today_prices.iloc[-1] * np.exp(projected_log_move))
    return IntradayProjection(end_time=last + pd.Timedelta(minutes=n * interval_minutes),
                              target=target, minutes_ahead=n * interval_minutes,
                              move_pct=(target / float(today_prices.iloc[-1]) - 1) * 100)


def chart_axis_range(history: pd.Series, period: str, future_end=None):
    """Keep plot bounds faithful to the range even with a future dot."""
    if history.empty:
        return None
    first = pd.Timestamp(history.index[0]); last = pd.Timestamp(history.index[-1])
    if period == "1D":
        # Intentionally fixed session axis, requested by the user. No midnight
        # padding and no after-hours extension, even if an invalid future
        # endpoint is supplied. Pre-8:30 bars are not displayed by the caller.
        day = first.normalize()
        return [day + ONE_DAY_DISPLAY_START, day + ONE_DAY_DISPLAY_END]
    if period == "5D":
        # Some providers only return daily closes. Do not clip away a
        # midnight-stamped daily observation by forcing a 09:30 start.
        stamps = pd.DatetimeIndex(history.index)
        daily_fallback = bool((stamps.hour == 0).all() and (stamps.minute == 0).all())
        left = first if daily_fallback else first.normalize() + pd.Timedelta(hours=9, minutes=30)
    else:
        left = first
    right = pd.Timestamp(future_end) if future_end is not None else last
    if right <= left:
        right = left + pd.Timedelta(hours=1)
    return [left, right]


def close_from_yfinance(raw: pd.DataFrame, ticker: str) -> pd.Series:
    """Handle multiple yfinance dataframe column formats, Eastern timestamps."""
    if raw is None or raw.empty:
        return pd.Series(dtype=float)
    frame = raw
    if isinstance(frame.columns, pd.MultiIndex):
        for level in (0, 1):
            if ticker in frame.columns.get_level_values(level):
                frame = frame.xs(ticker, axis=1, level=level)
                break
        else:
            return pd.Series(dtype=float)
    if "Close" not in frame.columns:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame["Close"], errors="coerce")
    if isinstance(values, pd.DataFrame):
        values = values.iloc[:, 0]
    values = values.where(values > 0).dropna().sort_index()
    if values.empty:
        return values
    index = pd.to_datetime(values.index, utc=True).tz_convert("America/New_York").tz_localize(None)
    values.index = index
    return values.loc[~values.index.duplicated(keep="last")]


def download_intraday(ticker: str, period: str) -> pd.Series:
    """Get actual provider observations, up to two app-level retries.

    1D: 5-minute data, 5D: 30-minute data, up to 5 recent sessions.
    """
    ticker = validate_symbol(ticker)
    if period not in ("1D", "5D"):
        raise ValueError("Intraday downloads are only for 1D and 5D")
    import yfinance as yf
    # Fetch 2 calendar days for the latest session when Yahoo is briefly stale;
    # select_today_intraday still prohibits showing yesterday on the 1D chart.
    yf_period, interval = ("2d", "5m") if period == "1D" else ("5d", "30m")
    result = retry_call(
        lambda: yf.download(
            tickers=ticker, period=yf_period, interval=interval,
            auto_adjust=True, group_by="ticker", multi_level_index=True,
            progress=False, threads=False, timeout=18,
        ),
        usable=lambda x: isinstance(x, pd.DataFrame) and not x.empty,
    )
    return close_from_yfinance(result, ticker)
