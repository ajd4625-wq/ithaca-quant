"""Cached company classification and market cap for *display*, not model features.

Yahoo Finance company profiles are best-effort, often missing or delayed, and
may be throttled. Market cap is current metadata, never historical point-in-time
metadata, and must not leak into walk-forward research features/backtests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from .retry import retry_call

CACHE_PATH = Path(__file__).resolve().parent.parent / ".company_metadata_cache.sqlite3"
COLUMNS = ["ticker", "company_name", "sector", "industry", "market_cap", "metadata_asof", "metadata_source"]


def _normalize(symbols: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))


def _connect(cache_path: str | Path):
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS company_metadata (
        ticker TEXT PRIMARY KEY,
        company_name TEXT,
        sector TEXT,
        industry TEXT,
        market_cap REAL,
        metadata_asof TEXT NOT NULL,
        metadata_source TEXT NOT NULL
    )""")
    return conn


def clean_company_info(ticker: str, info: dict, *, asof: datetime | None = None) -> dict:
    """Parse provider data conservatively. Unknown values remain unknown."""
    info = info if isinstance(info, dict) else {}
    asof = asof or datetime.now(timezone.utc)
    asof = asof.astimezone(timezone.utc)
    raw_cap = info.get("marketCap")
    try:
        cap = float(raw_cap)
        if not np.isfinite(cap) or cap <= 0:
            cap = np.nan
    except (TypeError, ValueError, OverflowError):
        cap = np.nan

    def clean_text(value):
        value = str(value or "").strip()
        return value if value and value.lower() not in {"none", "nan", "n/a"} else ""

    return {
        "ticker": ticker.strip().upper(),
        "company_name": clean_text(info.get("shortName") or info.get("longName")),
        "sector": clean_text(info.get("sector")),
        "industry": clean_text(info.get("industry")),
        "market_cap": cap,
        "metadata_asof": asof.isoformat(timespec="seconds"),
        "metadata_source": "Yahoo Finance company profile (may be stale)",
    }


def load_company_metadata(symbols: Iterable[str], *, cache_path: str | Path = CACHE_PATH) -> pd.DataFrame:
    """Read all cached rows (including old ones); fetches nothing."""
    requested = _normalize(symbols)
    if not requested:
        return pd.DataFrame(columns=COLUMNS)
    with _connect(cache_path) as conn:
        # Chunk to avoid SQLite's variable limit with an entire exchange universe.
        rows = []
        for start in range(0, len(requested), 400):
            chunk = requested[start:start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(conn.execute(
                f"SELECT {', '.join(COLUMNS)} FROM company_metadata WHERE ticker IN ({placeholders})", chunk
            ).fetchall())
    return pd.DataFrame(rows, columns=COLUMNS)


def fetch_company_metadata(
    symbols: Iterable[str], *, cache_path: str | Path = CACHE_PATH,
    max_new: int = 25, ttl_hours: float = 24,
    fetcher: Callable[[str], dict] | None = None,
    progress: Callable[[int, int], None] | None = None,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Download at most max_new missing/stale company profiles, cache on disk.

    Returns all cached rows for the requested symbols and status counts.
    The provider function can be injected for offline tests. Failures do not
    invent company fields or crash the rest of the dashboard.
    """
    if max_new < 1:
        raise ValueError("max_new must be positive")
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    requested = _normalize(symbols)
    stored = load_company_metadata(requested, cache_path=cache_path)
    previous = {r["ticker"]: r for r in stored.to_dict("records")}

    def stale(ticker):
        row = previous.get(ticker)
        if not row:
            return True
        try:
            timestamp = datetime.fromisoformat(str(row["metadata_asof"]))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            return (now - timestamp).total_seconds() > ttl_hours * 3600
        except (ValueError, TypeError, OverflowError):
            return True

    pending = [ticker for ticker in requested if stale(ticker)][:max_new]
    if fetcher is None:
        import yfinance as yf
        fetcher = lambda ticker: yf.Ticker(ticker).get_info()
    errors = []
    with _connect(cache_path) as conn:
        for i, ticker in enumerate(pending, start=1):
            try:
                info = retry_call(lambda: fetcher(ticker))
                record = clean_company_info(ticker, info, asof=now)
                if not any((record["company_name"], record["sector"], record["industry"], pd.notna(record["market_cap"]))):
                    errors.append(ticker)
                    # Missing metadata isn't cached as successful, to allow a later retry.
                    if progress:
                        progress(i, len(pending))
                    continue
                conn.execute("""INSERT OR REPLACE INTO company_metadata
                    (ticker, company_name, sector, industry, market_cap, metadata_asof, metadata_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", tuple(
                        None if key == "market_cap" and pd.isna(record[key]) else record[key] for key in COLUMNS
                    ))
                conn.commit()
            except Exception:
                errors.append(ticker)
            if progress:
                progress(i, len(pending))
    result = load_company_metadata(requested, cache_path=cache_path)
    status = {"requested": len(requested), "attempted": len(pending),
              "errors": len(errors), "not_loaded": len(requested) - len(result)}
    return result, status


def add_metadata(frame: pd.DataFrame, metadata: pd.DataFrame, *, ticker_col: str = "ticker") -> pd.DataFrame:
    """Left join preserving existing order; missing company data is left blank."""
    frame = frame.copy()
    if metadata is None or metadata.empty:
        for col in ["company_name", "sector", "industry", "market_cap", "metadata_asof"]:
            if col not in frame:
                frame[col] = np.nan if col == "market_cap" else ""
        return frame
    fields = ["ticker", "company_name", "sector", "industry", "market_cap", "metadata_asof"]
    return frame.merge(metadata[fields].drop_duplicates("ticker"),
                       left_on=ticker_col, right_on="ticker", how="left", sort=False,
                       suffixes=("", "_meta")).drop(columns=["ticker_meta"], errors="ignore")


def market_cap_bucket(value: float) -> str:
    if pd.isna(value) or value <= 0:
        return "Unknown"
    if value >= 200e9:
        return "Mega (≥$200B)"
    if value >= 10e9:
        return "Large ($10B–$200B)"
    if value >= 2e9:
        return "Mid ($2B–$10B)"
    if value >= 300e6:
        return "Small ($300M–$2B)"
    return "Micro (<$300M)"
