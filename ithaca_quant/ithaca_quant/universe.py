"""Discover current NYSE/Nasdaq listings and screen a broad stock universe.

IMPORTANT: this is today's listings, not a historical point-in-time universe.
Using it for backtests creates survivorship bias. Excludes ETFs, test securities,
funds, warrants, units, rights and preferred shares where identifiable.
"""
from dataclasses import dataclass
from io import StringIO
import re
import numpy as np
import pandas as pd
import requests

from .retry import retry_call

NASDAQ_LIST = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LIST = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
# These are often legally distinct instruments, not operating-company common stock.
EXCLUDE_NAMES = re.compile(
    r"\b(?:warrant(?:s)?|right(?:s)?|unit(?:s)?|preferred|preference|"
    r"depositary share(?:s)?|depositary shares representing|"
    r"etf|exchange traded fund|closed.end fund|mutual fund|"
    r"notes due|senior notes|debentures|bond(?:s)?|"
    r"trust preferred|contingent value right(?:s)?)\b", re.I,
)


@dataclass
class Universe:
    listings: pd.DataFrame
    directory_dates: dict[str, str]


def parse_directory(nasdaq_text: str, other_text: str) -> Universe:
    """Read Nasdaq Trader pipe-delimited issuer directories, preserve exchange."""
    def rows(text: str) -> pd.DataFrame:
        df = pd.read_csv(StringIO(text), sep="|", dtype=str, on_bad_lines="skip")
        df.columns = [str(c).strip() for c in df.columns]
        return df.fillna("")

    na = rows(nasdaq_text)
    ot = rows(other_text)
    required_n = {"Symbol", "Security Name", "Test Issue", "ETF"}
    required_o = {"ACT Symbol", "Security Name", "Exchange", "ETF", "Test Issue"}
    if not required_n.issubset(na.columns) or not required_o.issubset(ot.columns):
        raise ValueError("Nasdaq directory format is unrecognized; cannot verify exchange eligibility.")
    na = na.loc[(na["Test Issue"] == "N") & (na["ETF"] == "N"), ["Symbol", "Security Name"]].copy()
    na.columns = ["ticker", "name"]
    na["exchange"] = "NASDAQ"
    ot = ot.loc[(ot["Exchange"] == "N") & (ot["Test Issue"] == "N") &
                (ot["ETF"] == "N"), ["ACT Symbol", "Security Name"]].copy()
    ot.columns = ["ticker", "name"]
    ot["exchange"] = "NYSE"
    result = pd.concat([na, ot], ignore_index=True)
    result["ticker"] = result["ticker"].str.strip().str.upper()
    result["name"] = result["name"].str.strip()
    result = result.loc[
        result["ticker"].str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}").fillna(False) &
        ~result["name"].str.contains(EXCLUDE_NAMES, na=False)
    ].copy()
    # Yahoo Finance calls dotted class symbols with hyphens; preserve listing symbol separately.
    result["data_ticker"] = result["ticker"].str.replace(".", "-", regex=False)
    result = result.drop_duplicates("data_ticker").sort_values(["exchange", "ticker"])
    result = result.reset_index(drop=True)
    stamps = {}
    for key, text in (("NASDAQ", nasdaq_text), ("NYSE", other_text)):
        match = re.search(r"File Creation Time:\s*([^|\n]+)", text)
        stamps[key] = match.group(1).strip() if match else "Not supplied"
    if result.empty:
        raise ValueError("No eligible symbols were found in the exchange directories.")
    return Universe(result, stamps)


def fetch_current_universe(session: requests.Session | None = None) -> Universe:
    """Fresh U.S. listed symbols. Directory service might be temporarily unavailable."""
    client = session or requests
    headers = {"User-Agent": "Mozilla/5.0 IthacaQuant-Research/0.3"}
    try:
        def directory_response(url):
            def get():
                response = client.get(url, headers=headers, timeout=25)
                response.raise_for_status()
                return response
            return retry_call(get, retryable=lambda exc: isinstance(exc, requests.RequestException))
        a = directory_response(NASDAQ_LIST)
        b = directory_response(OTHER_LIST)
    except requests.RequestException as exc:
        raise ValueError(f"Listing-directory download failed: {exc}. Retry later or choose manual tickers.") from exc
    return parse_directory(a.text, b.text)


def pick_scan_symbols(listings: pd.DataFrame, limit: int | None) -> list[str]:
    """Deterministic random sampling across exchanges, not alphabetical first-N bias."""
    frame = listings
    if limit is not None and limit < len(frame):
        frame = frame.sample(n=limit, random_state=47)
    return frame["data_ticker"].tolist()


def screen_candidates(close: pd.DataFrame, volume: pd.DataFrame,
                      limit: int | None = 300, min_price: float = 5.0,
                      min_dollar_volume: float = 1_000_000) -> pd.DataFrame:
    """Lightweight market-wide screen; not an AI forecast or trading recommendation."""
    if "SPY" not in close.columns:
        raise ValueError("SPY benchmark is needed for screening.")
    symbols = [c for c in close.columns if c != "SPY"]
    if not symbols:
        return pd.DataFrame(columns=["ticker", "price", "avg_dollar_volume", "momentum_20", "momentum_60", "volatility_20"])
    px = close[symbols]
    vol = volume.reindex(index=px.index, columns=symbols).fillna(0)
    pxlast = px.ffill(limit=2).iloc[-1]
    dollar = (px * vol).tail(25).median()
    mom20 = pxlast / px.shift(20).iloc[-1] - 1
    mom60 = pxlast / px.shift(60).iloc[-1] - 1
    volatility = px.pct_change(fill_method=None).tail(40).std() * np.sqrt(252)
    history = px.notna().sum()
    candidate = pd.DataFrame({"ticker": symbols, "price": pxlast.to_numpy(),
                              "avg_dollar_volume": dollar.to_numpy(),
                              "momentum_20": mom20.to_numpy(),
                              "momentum_60": mom60.to_numpy(),
                              "volatility_20": volatility.to_numpy(),
                              "history_days": history.to_numpy()})
    valid = candidate.loc[
        (candidate["price"] > min_price) &
        (candidate["avg_dollar_volume"] >= min_dollar_volume) &
        (candidate["history_days"] >= 140)
    ].dropna(subset=["momentum_20", "momentum_60", "volatility_20"]).copy()
    if valid.empty:
        return valid
    valid["screen_score"] = (valid["avg_dollar_volume"].rank(pct=True) * 0.5 +
                             valid["momentum_60"].rank(pct=True) * 0.3 +
                             valid["volatility_20"].rank(pct=True) * 0.2)
    if limit is None:
        return valid.sort_values("screen_score", ascending=False).reset_index(drop=True)
    # Broad liquid coverage + momentum + volatile watchlist, never promise best picks.
    # Use all eligible candidates if fewer than requested.
    pieces = [
        valid.nlargest(limit, "avg_dollar_volume"),
        valid.nlargest(max(1, limit // 5), "momentum_60"),
        valid.nlargest(max(1, limit // 5), "volatility_20"),
    ]
    combined = pd.concat(pieces).drop_duplicates("ticker")
    # Prefer liquid and moderately strong momentum while keeping volatile candidates.
    result = combined.nlargest(limit, "screen_score").reset_index(drop=True)
    return result
