"""Daily adjusted-close data collection. No orders or brokerage access."""
from dataclasses import dataclass
import re

import numpy as np
import pandas as pd

from .config import BENCHMARK, MAX_AGENTS, improved_accuracy
from .retry import retry_call


@dataclass
class MarketData:
    close: pd.DataFrame
    volume: pd.DataFrame
    source: str
    excluded: list[str]
    raw_close: pd.DataFrame | None = None


def parse_tickers(text: str) -> list[str]:
    symbols = re.findall(r"[A-Za-z][A-Za-z0-9.\-]{0,12}", text.upper())
    return [x for x in dict.fromkeys(symbols) if x != BENCHMARK]


def remove_bad_ticks(prices: pd.Series, *, jump: float = 0.35, residual: float = 0.10) -> pd.Series:
    """Mask one-day price spikes that fully reverse the next session.

    Free feeds occasionally emit a bad print (a split not applied for one bar,
    a misplaced decimal). A >35% move that is >90% reversed the next day is
    treated as a data error and set to missing (the loader's short forward-fill
    then bridges it). Genuine, persistent gaps and crashes are never touched.
    """
    p = prices.astype(float)
    r1 = p.pct_change(fill_method=None)            # move INTO day t
    r2 = r1.shift(-1)                              # move OUT of day t
    round_trip = (1 + r1) * (1 + r2) - 1
    bad = (r1.abs() > jump) & (np.sign(r1) != np.sign(r2)) & (round_trip.abs() < residual)
    return p.mask(bad.fillna(False))


def _ticker_frame(downloaded: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Read either yfinance group-by layout and the single-ticker layout."""
    if isinstance(downloaded.columns, pd.MultiIndex):
        for level in (0, 1):
            if ticker in downloaded.columns.get_level_values(level):
                return downloaded.xs(ticker, axis=1, level=level)
        return pd.DataFrame(index=downloaded.index)
    return downloaded if ticker == downloaded.attrs.get("single_ticker") else pd.DataFrame(index=downloaded.index)


def download_market_data(tickers: list[str], years: int = 6, *,
                         min_history: int = 160, batch_size: int = 75,
                         on_progress=None, start: str | None = None) -> MarketData:
    """Retrieve Yahoo prices in bounded batches so large universes fit in memory.

    The service is unofficial and may throttle, fail, or supply delayed data.
    Missing symbols are excluded rather than silently filled with invented prices.
    """
    import yfinance as yf

    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        raise ValueError("Enter at least one ticker.")
    requested = [BENCHMARK, *[s for s in tickers if s != BENCHMARK]]
    close, volume, raw_close, excluded = {}, {}, {}, []
    if batch_size < 1 or min_history < 1 or years < 1:
        raise ValueError("Invalid market-data download parameters")
    fallback_symbols = []
    batches = [requested[i:i + batch_size] for i in range(0, len(requested), batch_size)]
    for i, batch in enumerate(batches):
        try:
            period_args = {"start": start} if start else {"period": f"{years}y"}
            raw = retry_call(
                lambda: yf.download(tickers=batch, interval="1d", **period_args,
                                    auto_adjust=False, group_by="ticker", multi_level_index=True,
                                    progress=False, threads=MAX_AGENTS, timeout=18),
                usable=lambda frame: frame is not None and not frame.empty,
            )
        except Exception:
            raw = None  # Exclude missing batches rather than invent historical data.
        if raw is None or raw.empty:
            excluded.extend(batch)
        else:
            raw.index = pd.to_datetime(raw.index, utc=True).tz_localize(None).normalize()
            raw = raw.loc[~raw.index.duplicated(keep="last")].sort_index()
            for ticker in batch:
                frame = _ticker_frame(raw, ticker)
                if frame.empty or "Close" not in frame:
                    excluded.append(ticker)
                    continue
                # With auto_adjust=False, Yahoo exposes both close (vendor's
                # split-adjusted trading quote) and dividend-adjusted close.
                # Use adjusted values to label returns; keep vendor Close for
                # dollar liquidity and minimum-price screening. Never combine
                # adjusted and unadjusted bars within the same ticker history.
                quoted = pd.to_numeric(frame["Close"], errors="coerce").where(lambda x: x > 0)
                if "Adj Close" in frame:
                    c = pd.to_numeric(frame["Adj Close"], errors="coerce").where(lambda x: x > 0)
                else:
                    # Mock/limited vendor feeds may omit dividends. This is a
                    # LOWER-QUALITY price-only fallback, explicitly disclosed.
                    c = quoted.copy()
                    fallback_symbols.append(ticker)
                # Do not mask a past bar because of what NEXT session did:
                # remove_bad_ticks uses r(t+1) and would leak future knowledge
                # into every historical prediction. Retain original source bars
                # and flag anomalies for a separate data-quality review.
                v = pd.to_numeric(frame.get("Volume", pd.Series(index=c.index, dtype=float)), errors="coerce")
                if c.notna().sum() < min_history:
                    excluded.append(ticker)
                    continue
                close[ticker] = c
                raw_close[ticker] = quoted
                volume[ticker] = v
        if on_progress is not None:
            on_progress(i + 1, len(batches), len(close))
    if BENCHMARK not in close:
        raise ValueError("SPY benchmark data unavailable. Yahoo Finance might be rate limiting downloads; retry later.")
    dates = close[BENCHMARK].dropna().index
    # Never synthesize stale trades for an unavailable ticker; even two days of
    # forward-filled delisting prices can fabricate observable outcomes.
    prices = pd.DataFrame(close).reindex(dates)
    volumes = pd.DataFrame(volume).reindex(dates)  # Unknown volume is NOT zero.
    trading = pd.DataFrame(raw_close).reindex(dates).reindex(columns=prices.columns)
    source = "Yahoo Finance (dividend-adjusted where available; vendor Close is not guaranteed as-traded PIT tape)"
    if fallback_symbols:
        source += f"; WARNING {len(fallback_symbols)} symbols lack Adj Close and use price-only returns"
    return MarketData(prices, volumes, source, excluded, raw_close=trading)


def demo_market_data(tickers: list[str], sessions: int = 1500, seed: int = 19) -> MarketData:
    """Deterministic synthetic prices for offline testing. NOT real market forecasts."""
    if not tickers:
        raise ValueError("Enter at least one ticker.")
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-11-10", periods=sessions)
    common = rng.normal(0.0003, 0.011, sessions)
    close, volume = {}, {}
    for i, symbol in enumerate([BENCHMARK, *tickers]):
        if symbol == BENCHMARK:
            r = common
        else:
            # Mild factor predictability, with random idiosyncratic variation.
            noise = rng.normal(0, 0.015 + (i % 4) * 0.003, sessions)
            r = (0.8 + (i % 7) * 0.14) * common + noise + (i % 5 - 2) * 0.00013
            r[1:] += 0.09 * r[:-1]
        close[symbol] = 110.0 * np.exp(np.cumsum(np.clip(r, -0.3, 0.3)))
        volume[symbol] = rng.lognormal(14.5, 0.3, sessions).round()
    return MarketData(
        pd.DataFrame(close, index=dates),
        pd.DataFrame(volume, index=dates),
        "SYNTHETIC DEMO — NOT LIVE OR HISTORICAL MARKET DATA", [],
    )
