"""Immutable daily forecasts, subsequently scored against actual closes.

Never updates a recorded forecast after it was first saved. Backtests are not
interchangeable with genuine live-forward records.
"""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import sqlite3
import pandas as pd
import numpy as np
from .market_cache import cache_path
from . import remote_store


def _local(path=None):
    conn = sqlite3.connect(str(path or cache_path()), timeout=20)
    conn.execute('''CREATE TABLE IF NOT EXISTS predictions (
        ticker TEXT NOT NULL, asof TEXT NOT NULL, horizon INTEGER NOT NULL,
        forecast REAL NOT NULL, baseline_forecast REAL, observed REAL, model TEXT NOT NULL,
        created_utc TEXT NOT NULL, resolved_utc TEXT, evidence_status TEXT, PRIMARY KEY(ticker, asof, horizon))''')
    cols = [x[1] for x in conn.execute('PRAGMA table_info(predictions)').fetchall()]
    if 'baseline_forecast' not in cols:
        conn.execute('ALTER TABLE predictions ADD COLUMN baseline_forecast REAL')
    if 'resolved_utc' not in cols:
        conn.execute('ALTER TABLE predictions ADD COLUMN resolved_utc TEXT')
    if 'evidence_status' not in cols:
        conn.execute('ALTER TABLE predictions ADD COLUMN evidence_status TEXT')
    return conn


def log_forecasts(rows: pd.DataFrame, asof, horizon: int, *, path=None, limit=250):
    """Append immutable forecasts from every prediction stratum (never synthetic).

    When capped, sample evenly through sorted model forecasts so a leaderboard
    of 1,500 names doesn't record only the most positive 250 predictions and
    then misleadingly call that top-pick sample representative of all stocks.
    """
    if horizon < 1 or limit < 1 or 'ticker' not in rows or 'forecast_excess' not in rows:
        raise ValueError('A positive horizon, limit, and model forecast rows are required')
    candidates = rows.copy()
    candidates['forecast_excess'] = pd.to_numeric(candidates['forecast_excess'], errors='coerce')
    candidates = candidates.loc[np.isfinite(candidates.forecast_excess)].copy()
    candidates = candidates.drop_duplicates('ticker', keep='first')
    if len(candidates) > limit:
        candidates = candidates.sort_values(['forecast_excess', 'ticker'], ascending=[False,True])
        sample = np.linspace(0, len(candidates)-1, limit).round().astype(int)
        candidates = candidates.iloc[sample].copy()
    when = str(pd.Timestamp(asof).date())
    stamp = datetime.now(timezone.utc).isoformat()
    count = 0
    if path is None and remote_store.remote_enabled():
        for _, r in candidates.iterrows():
            if remote_store.save_prediction(str(r.ticker), when, horizon, float(r.forecast_excess),
                                            r.get('selected_model', 'Existing ensemble'),
                                            baseline_forecast=r.get('incumbent_forecast_excess')):
                count += 1
        return count
    with _local(path) as conn:
        for _, r in candidates.iterrows():
            if not np.isfinite(float(r.forecast_excess)):
                continue
            cursor = conn.execute('''INSERT OR IGNORE INTO predictions
                    (ticker,asof,horizon,forecast,baseline_forecast,observed,model,created_utc,evidence_status)
                    VALUES(?,?,?,?,?,?,?,?,?)''',
                    (str(r.ticker), when, horizon, float(r.forecast_excess),
                     float(r.incumbent_forecast_excess) if 'incumbent_forecast_excess' in r and pd.notna(r.incumbent_forecast_excess) else None, None,
                     str(r.get('selected_model', 'Existing ensemble')), stamp, 'pending'))
            count += max(0, cursor.rowcount)
    return count


def read_forecasts(path=None):
    cols = ['ticker','asof','horizon','forecast','observed','model','created_utc','resolved_utc','evidence_status','baseline_forecast']
    if path is None and remote_store.remote_enabled():
        return pd.DataFrame(remote_store.fetch_predictions(), columns=cols)
    with _local(path) as conn:
        rows = conn.execute('''SELECT ticker,asof,horizon,forecast,observed,model,created_utc,resolved_utc,evidence_status,baseline_forecast
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
        # Using actual future benchmark session dates avoids weekend/holiday
        # shortcuts. Passing this timestamp test is not cryptographic proof.
        recorded = pd.to_datetime(r.created_utc, errors='coerce', utc=True)
        if at + 1 < len(ix):
            eastern = ZoneInfo('America/New_York')
            signal_close = (pd.Timestamp(ix[at].date(), tz=eastern) + pd.Timedelta(hours=16)).tz_convert('UTC')
            next_close = (pd.Timestamp(ix[at+1].date(), tz=eastern) + pd.Timedelta(hours=16)).tz_convert('UTC')
            timely = bool(pd.notna(recorded) and signal_close <= recorded < next_close)
        else:
            timely = False
        status = 'timestamp_eligible' if timely else 'late_or_unverifiable'
        updates.append((r.ticker, r.asof, int(r.horizon), actual, status))
    if not updates:
        return 0
    if path is None and remote_store.remote_enabled():
        remote_store.save_observations(updates)
    else:
        with _local(path) as conn:
            conn.executemany('''UPDATE predictions SET observed=?,resolved_utc=?,evidence_status=? WHERE ticker=? AND asof=?
                                AND horizon=? AND observed IS NULL''',
                             [(value,datetime.now(timezone.utc).isoformat(),status,ticker,asof,horizon)
                              for ticker,asof,horizon,value,status in updates])
    return len(updates)


def forward_report(path=None):
    records = read_forecasts(path)
    if records.empty:
        return {'logged':0,'resolved':0,'mae':np.nan,'baseline_mae':np.nan,
                'directional_accuracy':np.nan,'by_horizon':pd.DataFrame(),
                'timestamp_eligible_resolved':0,'timestamp_eligible_mae':np.nan,
                'timestamp_eligible_baseline_mae':np.nan,'timestamp_eligible_directional_accuracy':np.nan}
    resolved = records.loc[records['observed'].notna()].copy()
    if resolved.empty:
        return {'logged':len(records),'resolved':0,'mae':np.nan,'baseline_mae':np.nan,
                'directional_accuracy':np.nan,'by_horizon':pd.DataFrame(),
                'timestamp_eligible_resolved':0,'timestamp_eligible_mae':np.nan,
                'timestamp_eligible_baseline_mae':np.nan,'timestamp_eligible_directional_accuracy':np.nan}
    resolved['absolute_error'] = (resolved['observed']-resolved['forecast']).abs()
    resolved['baseline_abs_error'] = resolved['observed'].abs()
    resolved['direction_correct'] = ((resolved['observed'] > 0) == (resolved['forecast'] > 0)).astype(float)
    timestamp_ok = resolved.loc[resolved['evidence_status'].eq('timestamp_eligible')].copy()
    timestamp_dir = ((timestamp_ok['observed'] > 0) == (timestamp_ok['forecast'] > 0)).mean() if len(timestamp_ok) else np.nan
    return {'logged':len(records),'resolved':len(resolved),
            'mae':float(resolved.absolute_error.mean()),
            'baseline_mae':float(resolved.baseline_abs_error.mean()),
            'directional_accuracy':float(resolved.direction_correct.mean()),
            'timestamp_eligible_resolved':int(len(timestamp_ok)),
            'timestamp_eligible_mae':float(timestamp_ok.absolute_error.mean()) if len(timestamp_ok) else np.nan,
            'timestamp_eligible_baseline_mae':float(timestamp_ok.baseline_abs_error.mean()) if len(timestamp_ok) else np.nan,
            'timestamp_eligible_directional_accuracy':float(timestamp_dir),
            'by_horizon':timestamp_ok.groupby('horizon')[['absolute_error','baseline_abs_error',
                                                       'direction_correct']].agg(['mean','count'])}


def forward_model_comparison_report(path=None, *, horizon: int | None = None,
                                    min_windows: int = 24, seed: int = 84) -> dict:
    """Truly forward FIRST-RECORDED winner-vs-incumbent paired report.

    Refrains from verifying an advantage until 24 independent eligible
    forecast-date periods are available with positive bootstrap confidence.
    The platform timestamp is not cryptographically authenticated; archived
    data may still have unknown vendor/provenance problems.
    """
    if min_windows < 12: raise ValueError('Need at least twelve independent forward periods')
    raw=read_forecasts(path)
    empty={'status':'INSUFFICIENT FORWARD EVIDENCE','independent_windows':0,
           'paired_forecasts':0,'winner_mae':np.nan,'incumbent_mae':np.nan,
           'mae_improvement':np.nan,'improvement_ci_low':np.nan,
           'improvement_ci_high':np.nan,'verified_advantage':False, 'preliminary_edge':False}
    if raw.empty or 'baseline_forecast' not in raw: return empty
    rows=raw.loc[raw.observed.notna() & raw.evidence_status.eq('timestamp_eligible') &
            raw.baseline_forecast.notna() &
            ~raw.model.eq('Existing ensemble')].copy()
    if horizon is not None: rows=rows.loc[rows.horizon.astype(int).eq(horizon)]
    if rows.empty: return empty
    # Can't pool 1-day and 20-day overlapping outcomes and treat as one test.
    row_horizons=rows.horizon.unique()
    if len(row_horizons)!=1:
        return {**empty,'status':'Choose a single forecast horizon to compare'}
    h=int(row_horizons[0])
    rows['asof']=pd.to_datetime(rows['asof'])
    rows['mae_lift']=(rows.observed-rows.baseline_forecast).abs()-(rows.observed-rows.forecast).abs()
    by_date=rows.groupby('asof')['mae_lift'].mean().sort_index()
    independent=[]; prev=None
    for day,delta in by_date.items():
        if prev is None or len(pd.bdate_range(prev,day))-1>=h:
            independent.append(float(delta)); prev=day
    arr=np.array(independent,float)
    result={**empty,'independent_windows':len(arr),'paired_forecasts':len(rows),
            'winner_mae':float((rows.observed-rows.forecast).abs().mean()),
            'incumbent_mae':float((rows.observed-rows.baseline_forecast).abs().mean()),
            'mae_improvement':float(np.mean(arr)) if len(arr) else np.nan}
    if len(arr)<min_windows:
        result['status']=f'INSUFFICIENT FORWARD EVIDENCE: {len(arr)}/{min_windows} independent periods'
        return result
    rng=np.random.default_rng(seed)
    draws=rng.choice(arr,size=(4000,len(arr)),replace=True).mean(axis=1)
    low,high=np.quantile(draws,[.025,.975])
    result['improvement_ci_low']=float(low)
    result['improvement_ci_high']=float(high)
    # No independent external price/feed attestations: reserve 'verified' for a
    # separate audit. A positive date-bootstrap result is preliminary only.
    result['verified_advantage']=False
    result['preliminary_edge']=bool(low>0)
    result['status']=('PRELIMINARY FORWARD EDGE: timestamp eligible, bootstrap CI above zero'
             if low>0 else 'NO FORWARD EDGE CONFIRMED: interval overlaps zero')
    return result
