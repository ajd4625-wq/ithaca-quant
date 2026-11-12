"""Single-symbol explorer helpers; chart windows and dots are visualizations only.

Historical candles are obtained from the market provider; the future dashed
segment interpolates two model outputs, and does not predict intermediate days.
"""
from __future__ import annotations

import re
import pandas as pd
from .retry import retry_call

CHART_PERIODS = ("1D", "5D", "1M", "6M", "YTD", "5Y")


def validate_symbol(ticker: str) -> str:
    symbol = str(ticker).strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", symbol):
        raise ValueError("Enter a valid ticker (for example NVDA, AAPL, or BRK-B).")
    return symbol


def select_history_window(prices: pd.Series, period: str) -> pd.Series:
    """Slice real price observations without any resampling or price invention."""
    if period not in CHART_PERIODS:
        raise ValueError("Unsupported chart period")
    prices = prices.dropna().sort_index()
    if prices.empty:
        return prices
    latest = pd.Timestamp(prices.index[-1])
    if period == "1D":
        lower = latest.normalize()
    elif period == "5D":
        # Exactly the last five *available trading dates*, including long weekends.
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


def forecast_segment(last_timestamp, last_price: float, target_price: float, horizon: int):
    """Only the current endpoint and horizon estimate; no invented daily prices."""
    if horizon < 1 or last_price <= 0 or target_price <= 0:
        raise ValueError("Invalid forecast endpoint")
    start = pd.Timestamp(last_timestamp)
    return [start, start + pd.offsets.BDay(horizon)], [last_price, target_price]


def close_from_yfinance(raw: pd.DataFrame, ticker: str) -> pd.Series:
    """Handle multiple yfinance dataframe column formats."""
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
    """Get actual provider observations; caller should cache briefly.

    Only 1D and 5D are requested intraday to avoid unneeded data requests.
    Each Yahoo call gets no more than two application-level retries.
    """
    ticker = validate_symbol(ticker)
    if period not in ("1D", "5D"):
        raise ValueError("Intraday downloads are only for 1D and 5D")
    import yfinance as yf
    yf_period, interval = ("1d", "5m") if period == "1D" else ("5d", "30m")
    result = retry_call(
        lambda: yf.download(
            tickers=ticker, period=yf_period, interval=interval,
            auto_adjust=True, group_by="ticker", multi_level_index=True,
            progress=False, threads=False, timeout=18,
        ),
        usable=lambda x: isinstance(x, pd.DataFrame) and not x.empty,
    )
    return close_from_yfinance(result, ticker)
