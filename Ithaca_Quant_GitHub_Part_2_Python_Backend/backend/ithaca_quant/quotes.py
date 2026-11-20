"""Optional latest available quotes. NEVER merge quote values into adjusted-price model.

Alpaca IEX provides venue-limited real-time latest trades when properly authorized;
Yahoo 1-minute data can be delayed, stale, or unavailable. No trading functions.
"""
from datetime import datetime, timezone
import pandas as pd
import requests

from .config import MAX_AGENTS
from .retry import retry_call


def age_minutes(value, now=None) -> float | None:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return None
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    return max(0.0, (now - timestamp).total_seconds() / 60)


def alpaca_iex_quotes(tickers: list[str], key: str, secret: str,
                       session: requests.Session | None = None) -> pd.DataFrame:
    """Read-only snapshot endpoint. Free IEX is NOT consolidated SIP market data."""
    if not key.strip() or not secret.strip():
        raise ValueError("An authorized Alpaca market-data key and secret are required for IEX quotes.")
    sess = session or requests
    headers = {"APCA-API-KEY-ID": key.strip(), "APCA-API-SECRET-KEY": secret.strip()}
    results = []
    for start in range(0, len(tickers), 50):
        symbols = list(dict.fromkeys(tickers[start:start + 50]))
        if not symbols:
            continue
        def request_snapshot():
            response = sess.get(
                "https://data.alpaca.markets/v2/stocks/snapshots",
                params={"symbols": ",".join(symbols), "feed": "iex"},
                headers=headers, timeout=20,
            )
            # Retry temporary server errors, not auth failures or 429 throttling.
            if response.status_code >= 500:
                response.raise_for_status()
            return response
        response = retry_call(request_snapshot, retryable=lambda exc: isinstance(exc, requests.RequestException))
        if response.status_code in (401, 403):
            raise ValueError("The IEX feed rejected these credentials or permissions. Check your authorized data access.")
        if response.status_code == 429:
            raise ValueError("The quote service rate limit was reached. Refresh less often.")
        response.raise_for_status()
        parsed = response.json()
        # Official Alpaca multi-snapshot API returns a top-level ticker map;
        # tolerate wrapped responses used by some clients/proxies.
        data = parsed.get("snapshots", parsed)
        if not isinstance(data, dict):
            raise ValueError("Unexpected snapshot response from market-data provider.")
        for ticker in symbols:
            snap = data.get(ticker) or {}
            trade = snap.get("latestTrade") or {}
            quote = snap.get("latestQuote") or {}
            value = trade.get("p")
            ts = trade.get("t")
            if value is None or value <= 0:
                continue
            results.append({"ticker": ticker, "price": float(value),
                            "bid": quote.get("bp"), "ask": quote.get("ap"),
                            "timestamp_utc": str(ts), "feed": "Alpaca IEX (venue-limited real-time)"})
    return pd.DataFrame(results, columns=["ticker", "price", "bid", "ask", "timestamp_utc", "feed"])


def yahoo_latest_quotes(tickers: list[str]) -> pd.DataFrame:
    """Best-effort Yahoo intraday bars; MAY BE DELAYED and not execution quotes."""
    import yfinance as yf
    tickers = list(dict.fromkeys(tickers))
    results = []
    for i in range(0, len(tickers), 25):
        batch = tickers[i:i + 25]
        try:
            raw = retry_call(
                lambda: yf.download(tickers=batch, period="2d", interval="1m", auto_adjust=False,
                                    group_by="ticker", multi_level_index=True,
                                    progress=False, threads=MAX_AGENTS, timeout=15),
                usable=lambda frame: frame is not None and not frame.empty,
            )
        except Exception:
            continue
        for ticker in batch:
            if isinstance(raw.columns, pd.MultiIndex):
                if ticker not in raw.columns.get_level_values(0):
                    continue
                frame = raw[ticker]
            else:
                if len(batch) != 1:
                    continue
                frame = raw
            if "Close" not in frame:
                continue
            prices = pd.to_numeric(frame["Close"], errors="coerce").dropna()
            prices = prices[prices > 0]
            if prices.empty:
                continue
            price = float(prices.iloc[-1])
            stamp = pd.to_datetime(prices.index[-1], utc=True)
            results.append({"ticker": ticker, "price": price,
                            "bid": None, "ask": None, "timestamp_utc": stamp.isoformat(),
                            "feed": "Yahoo intraday (may be delayed)"})
    return pd.DataFrame(results, columns=["ticker", "price", "bid", "ask", "timestamp_utc", "feed"])
