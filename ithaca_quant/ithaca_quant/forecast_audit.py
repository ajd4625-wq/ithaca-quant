"""Immutable daily forecasts, subsequently scored against actual closes.

Never updates a recorded forecast after it was first saved. Backtests are not
interchangeable with genuine live-forward records.
"""
from __future__ import annotations
from datetime import datetime, timezone
import sqlite3
import pandas as pd
import numpy as np
from .market_cache import cache_path
from . import remote_store


def _local(path=None):
    conn = sqlite3.connect(str(path or cache_path()), timeout=20)
    conn.execute('''CREATE TABLE IF NOT EXISTS predictions (
        ticker TEXT NOT NULL, asof TEXT NOT NULL, horizon INTEGER NOT NULL,
        forecast REAL NOT NULL, observed REAL, model TEXT NOT NULL,
        created_utc TEXT NOT NULL, PRIMARY KEY(ticker, asof, horizon))''')
    return conn


def log_forecasts(rows: pd.DataFrame, asof, horizon: int, *, path=None, limit=250):
    """Append as-of excess returns to immutable ledger (never synthetic)."""
    if horizon < 1 or 'ticker' not in rows or 'forecast_excess' not in rows:
        raise ValueError('A positive horizon and model forecast rows are required')
    when = str(pd.Timestamp(asof).date())
    stamp = datetime.now(timezone.utc).isoformat()
    count = 0
    if path is None and remote_store.remote_enabled():
        for _, r in rows.head(limit).iterrows():
            if pd.notna(r.forecast_excess):
                remote_store.save_prediction(str(r.ticker), when, horizon, float(r.forecast_excess),
                                             r.get('selected_model', 'Existing ensemble'))
                count += 1
        return count
    with _local(path) as conn:
        for _, r in rows.head(limit).iterrows():
            if not np.isfinite(float(r.forecast_excess)):
                continue
            cursor = conn.execute('''INSERT OR IGNORE INTO predictions
                    (ticker,asof,horizon,forecast,observed,model,created_utc)
                    VALUES(?,?,?,?,?,?,?)''',
                    (str(r.ticker), when, horizon, float(r.forecast_excess), None,
                     str(r.get('selected_model', 'Existing ensemble')), stamp))
            count += max(0, cursor.rowcount)
    return count


def read_forecasts(path=None):
    cols = ['ticker','asof','horizon','forecast','observed','model','created_utc']
    if path is None and remote_store.remote_enabled():
        return pd.DataFrame(remote_store.fetch_predictions(), columns=cols)
    with _local(path) as conn:
        rows = conn.execute('''SELECT ticker,asof,horizon,forecast,observed,model,created_utc
                               FROM predictions ORDER BY asof DESC''').fetchall()
    return pd.DataFrame(rows, columns=cols)


def reconcile_forecasts(close: pd.DataFrame, *, path=None):
    """Resolve outcomes only after all *horizon* future trading sessions exist."""
    if 'SPY' not in close:
        return 0
    records = read_forecasts(path)
    if records.empty:
        return 0
    market = close.sort_index()
    ix = pd.DatetimeIndex(market.index).normalize()
    locations = {str(x.date()):i for i,x in enumerate(ix)}
    updates = []
    for r in records.itertuples():
        if pd.notna(r.observed) or r.ticker not in market or r.asof not in locations:
            continue
        at = locations[r.asof]
        target = at + int(r.horizon)
        if target >= len(ix):
            continue
        prices = [market.iloc[at][r.ticker],market.iloc[target][r.ticker],
                  market.iloc[at]['SPY'],market.iloc[target]['SPY']]
        if not all(np.isfinite(float(p)) and float(p) > 0 for p in prices):
            continue
        actual = float(prices[1]/prices[0] - prices[3]/prices[2])
        updates.append((r.ticker, r.asof, int(r.horizon), actual))
    if not updates:
        return 0
    if path is None and remote_store.remote_enabled():
        remote_store.save_observations(updates)
    else:
        with _local(path) as conn:
            conn.executemany('''UPDATE predictions SET observed=? WHERE ticker=? AND asof=?
                                AND horizon=? AND observed IS NULL''',
                             [(value,ticker,asof,horizon) for ticker,asof,horizon,value in updates])
    return len(updates)


def forward_report(path=None):
    records = read_forecasts(path)
    if records.empty:
        return {'logged':0,'resolved':0,'mae':np.nan,'baseline_mae':np.nan,
                'directional_accuracy':np.nan,'by_horizon':pd.DataFrame()}
    resolved = records.loc[records['observed'].notna()].copy()
    if resolved.empty:
        return {'logged':len(records),'resolved':0,'mae':np.nan,'baseline_mae':np.nan,
                'directional_accuracy':np.nan,'by_horizon':pd.DataFrame()}
    resolved['absolute_error'] = (resolved['observed']-resolved['forecast']).abs()
    resolved['baseline_abs_error'] = resolved['observed'].abs()
    resolved['direction_correct'] = ((resolved['observed'] > 0) == (resolved['forecast'] > 0)).astype(float)
    return {'logged':len(records),'resolved':len(resolved),
            'mae':float(resolved.absolute_error.mean()),
            'baseline_mae':float(resolved.baseline_abs_error.mean()),
            'directional_accuracy':float(resolved.direction_correct.mean()),
            'by_horizon':resolved.groupby('horizon')[['absolute_error','baseline_abs_error',
                                                       'direction_correct']].agg(['mean','count'])}
