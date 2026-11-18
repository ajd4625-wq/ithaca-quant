"""Incremental daily price maintenance with stale-data and adjustment safeguards.

Refresh only the newest bars, plus overlap for detecting vendor revisions. Never
silently splice incompatible split-adjusted series. Never use today's incomplete
daily candle as a completed-session training observation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
from .config import BENCHMARK
from .data import MarketData, download_market_data
from .market_cache import (config_key, load_market, save_market, age_seconds)


class AdjustmentConflict(ValueError):
    pass


def completed_daily_only(data: MarketData, now: datetime | None = None) -> MarketData:
    """Remove unfinished US session; wait until 5pm New York time to trust today's daily bar.

    This is a conservative publication policy, NOT an exchange calendar; holiday
    and shortened-session rows are only included after 5pm ET.
    """
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("now must include a timezone")
    et = instant.astimezone(ZoneInfo("America/New_York"))
    cutoff = pd.Timestamp(et.date())
    if et.hour < 17:
        keep = data.close.index < cutoff
        close = data.close.loc[keep].copy()
        volume = data.volume.reindex(close.index).copy()
    else:
        keep = data.close.index <= cutoff
        close = data.close.loc[keep].copy()
        volume = data.volume.reindex(close.index).copy()
    return MarketData(close, volume, data.source, data.excluded.copy())


def overlap_conflicts(old: MarketData, new: MarketData, tolerance=0.025) -> list[str]:
    """Changed overlapping adjusted bars may mean a split, revision, or corrupt batch."""
    common_days = old.close.index.intersection(new.close.index)
    problematic = []
    if len(common_days) < 2:
        return []
    for sym in old.close.columns.intersection(new.close.columns):
        before = old.close.loc[common_days, sym]
        after = new.close.loc[common_days, sym]
        both = before.notna() & after.notna() & (before > 0)
        if both.sum() < 2:
            continue
        diff = (after[both] / before[both] - 1).abs()
        # Daily bar still being finalized can have small revisions; large
        # systematic changes require fetching full adjusted history.
        if (diff > tolerance).sum() >= 2:
            problematic.append(sym)
    return problematic


def merge_market(old: MarketData, incoming: MarketData) -> MarketData:
    if BENCHMARK not in incoming.close:
        raise ValueError("No SPY data in incremental refresh; original snapshot preserved")
    bad = overlap_conflicts(old, incoming)
    if bad:
        raise AdjustmentConflict("Adjusted historical price revisions detected: " + ", ".join(bad[:20]))
    dates = old.close.index.union(incoming.close.index).sort_values()
    prices = old.close.reindex(dates).copy()
    volume = old.volume.reindex(dates).copy()
    for sym in incoming.close.columns:
        if sym not in prices:
            prices[sym] = np.nan
            volume[sym] = np.nan
        new_close = incoming.close[sym].reindex(dates)
        observed = new_close.notna() & (new_close > 0)
        prices.loc[observed, sym] = new_close.loc[observed]
        if sym in incoming.volume:
            new_vol = incoming.volume[sym].reindex(dates)
            volume.loc[observed, sym] = new_vol.loc[observed]
    # No forward-fill across newly uncovered sessions. A stock with no new
    # observation must not get a made-up current price and model feature row.
    spy_dates = prices[BENCHMARK].dropna().index
    prices = prices.reindex(spy_dates)
    volume = volume.reindex(spy_dates)
    excluded = sorted(set(old.excluded).union(incoming.excluded) - set(prices.columns))
    return MarketData(prices, volume, old.source + " · incrementally refreshed", excluded)


def refresh_market(tickers, years, *, kind="deep", min_history=160,
                   batch_size=75, min_interval=20 * 60, force=False,
                   on_progress=None, path=None, now=None):
    """Returns (data, status, refresh_time, warnings).

    `status` distinguishes cache hit, full fetch, delta fetch, or stale fallback.
    On provider error a saved result may be displayed with a prominent warning;
    the caller decides whether that stale observation is suitable for a forecast.
    """
    tickers = list(dict.fromkeys(tickers))
    key = config_key("adjusted_daily", tickers, kind=kind, years=years, min_history=min_history)
    saved = load_market(key, path)
    if saved and not force and age_seconds(saved[1], now) < min_interval:
        return saved[0], "cache", saved[1], []
    warnings = []
    if saved:
        old, previous_stamp = saved
        last = old.close[BENCHMARK].dropna()
        if last.empty:
            raise ValueError("Saved SPY series is empty")
        overlap_start = (last.index[-1] - pd.Timedelta(days=9)).strftime("%Y-%m-%d")
        try:
            delta = download_market_data(tickers, years=years, min_history=1,
                                         batch_size=batch_size, start=overlap_start,
                                         on_progress=on_progress)
            delta = completed_daily_only(delta, now)
            conflicts = overlap_conflicts(old, delta)
            if conflicts:
                if len(conflicts) > 25:
                    raise AdjustmentConflict(f"{len(conflicts)} revised symbols; full reconciliation required")
                # Re-fetch all prices for revised symbols (including benchmark if
                # necessary), rather than mixing incompatible adjusted history.
                repair = download_market_data([s for s in conflicts if s != BENCHMARK],
                                              years=years, min_history=min_history,
                                              batch_size=batch_size)
                repair = completed_daily_only(repair, now)
                # Mutate a detached copy; on any reconciliation failure the
                # original cache must remain untouched and can be shown stale.
                candidate = MarketData(old.close.copy(), old.volume.copy(), old.source,
                                       old.excluded.copy())
                for sym in conflicts:
                    if sym not in repair.close or repair.close[sym].notna().sum() < min_history:
                        raise AdjustmentConflict(f"Complete adjusted-history repair failed for {sym}")
                    if sym == BENCHMARK:
                        candidate.close[sym] = repair.close[sym].reindex(candidate.close.index)
                        candidate.volume[sym] = repair.volume[sym].reindex(candidate.close.index)
                        delta.close[sym] = repair.close[sym].reindex(delta.close.index)
                        delta.volume[sym] = repair.volume[sym].reindex(delta.close.index)
                        continue
                    candidate.close = candidate.close.drop(columns=[sym], errors="ignore")
                    candidate.volume = candidate.volume.drop(columns=[sym], errors="ignore")
                    delta.close = delta.close.drop(columns=[sym], errors="ignore")
                    delta.volume = delta.volume.drop(columns=[sym], errors="ignore")
                candidate = merge_market(candidate, delta)
                for sym in conflicts:
                    candidate.close[sym] = repair.close[sym].reindex(candidate.close.index)
                    candidate.volume[sym] = repair.volume[sym].reindex(candidate.close.index)
                warnings.append(f"Full adjusted-history reconciliation completed for {len(conflicts)} symbols")
                new_data = candidate
            else:
                new_data = merge_market(old, delta)
            save_market(key, new_data, path)
            return new_data, "incremental", datetime.now(timezone.utc), warnings
        except Exception as exc:
            return old, "stale", previous_stamp, [f"Incremental refresh failed ({type(exc).__name__}). Cached prices were kept; verify timestamps before using forecasts."]
    full = download_market_data(tickers, years=years, min_history=min_history,
                                batch_size=batch_size, on_progress=on_progress)
    full = completed_daily_only(full, now)
    if full.close.empty:
        raise ValueError("No completed daily bars available")
    save_market(key, full, path)
    return full, "full", datetime.now(timezone.utc), warnings
