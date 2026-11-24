"""Resource-bounded, explicitly *sampled* in-browser historical validation.

The Streamlit process must not train thousands of three-agent models at once.
This is an exploratory survivor-universe preview, not a substitute for a full,
point-in-time archival backtest or for verified forward-market accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import pandas as pd

from .config import BENCHMARK

# Set deliberately below typical shared Streamlit Cloud CPU/memory budgets.
BROWSER_MAX_SYMBOLS = 12
BROWSER_MAX_PERIODS = 2
BROWSER_MAX_PANEL_ROWS = 30_000
BROWSER_MAX_ARCHIVE_BYTES = 15 * 1024 * 1024


@dataclass(frozen=True)
class BrowserSample:
    panel: pd.DataFrame
    close: pd.DataFrame
    tickers: tuple[str, ...]
    excluded_tickers: int
    periods: int
    portfolio_size: int


def browser_validation_sample(panel: pd.DataFrame, close: pd.DataFrame, *,
                              portfolio_size: int, periods: int,
                              max_symbols: int = BROWSER_MAX_SYMBOLS,
                              max_periods: int = BROWSER_MAX_PERIODS) -> BrowserSample:
    """Bound memory BEFORE fitting; never choose symbols from future returns.

    A stable symbol hash samples names without referring to future returns,
    current rankings or later delisting outcomes. Input remains a
    *current-listed* Yahoo universe, and results are labelled accordingly.
    The genuine three-model tournament still runs for the sampled stocks.
    """
    if 'ticker' not in panel or 'date' not in panel or BENCHMARK not in close:
        raise ValueError('Market data are missing ticker/date/benchmark information')
    if max_symbols < 5 or max_periods < 1:
        raise ValueError('Invalid browser validation limits')
    eligible = sorted(set(panel['ticker'].dropna().astype(str)) & (set(close.columns)-{BENCHMARK}))
    if len(eligible) < 5:
        raise ValueError('At least five eligible stocks are required for exploratory validation')
    # Stable, reproducible sampling that does NOT look at returns or model ranks.
    chosen = tuple(sorted(eligible, key=lambda s: sha256(s.encode('utf-8')).hexdigest())[:max_symbols])
    # Oldest training rows beyond approximately six years add cache/memory
    # pressure while the production forecaster uses a four-year lookback.
    # Retain enough rows for that lookback plus the validation windows.
    recent_index = close.index[-1600:]
    limited_panel = panel.loc[panel['ticker'].isin(chosen) &
                              panel['date'].isin(recent_index)].copy()
    limited_close = close.loc[recent_index, [BENCHMARK, *chosen]].copy()
    if len(limited_panel) > BROWSER_MAX_PANEL_ROWS:
        raise ValueError('Historical input is too large for in-browser validation; use the offline runner')
    return BrowserSample(limited_panel, limited_close, chosen,
                         len(eligible)-len(chosen), min(int(periods), max_periods),
                         min(int(portfolio_size), len(chosen)))
