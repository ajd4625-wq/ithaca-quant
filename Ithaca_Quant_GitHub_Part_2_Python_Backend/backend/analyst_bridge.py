"""Read-only v3.2 analyst and portfolio study API implementation.

No trades, no broker integration, no holdings persistence. Stock positions arrive
only from an opt-in Chrome panel action, and are held for this single request.
Opinion snapshots are observed-now context, NEVER backdated model training labels.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
import json
import math
import os
import re
import sqlite3
import time

import pandas as pd

from ithaca_quant.analyst_consensus import (
    fetch_finnhub, fetch_yahoo, fetch_finnhub_actions, fetch_yahoo_actions,
    snapshot_to_row, is_fresh,
)
from ithaca_quant.config import MAX_AGENTS, MAX_RETRIES, MAX_STOCKS
from ithaca_quant.data import download_market_data
from ithaca_quant.portfolio_advisor import portfolio_allocation_study
from ithaca_quant.quotes import yahoo_latest_quotes

assert (MAX_AGENTS, MAX_RETRIES) == (3, 2)
DB = Path(__file__).resolve().parent / 'analyst_observations_v32.sqlite3'
CACHE_SECONDS = 900
MAX_POSITIONS = MAX_STOCKS
CACHE = {}
HISTORY_CACHE = {}
LOCK = Lock()


def _finite_positive(value, *, ceiling=1e9):
    try:
        n = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Holding quantities and prices must be numbers')
    if not math.isfinite(n) or n <= 0 or n > ceiling:
        raise ValueError('Holding quantities and prices must be positive, finite and within limits')
    return n


def normalize_holdings(raw, valid_ticker):
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_POSITIONS:
        raise ValueError(f'Enter 1–{MAX_POSITIONS} held stocks, not a theoretical ticker universe')
    out = []
    seen = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError('Each holding requires a ticker and shares')
        ticker = valid_ticker(entry.get('ticker',''))
        if ticker == 'SPY':
            raise ValueError('SPY is used as a benchmark, not an owned position in this study')
        if ticker in seen:
            raise ValueError('Duplicate stock: '+ticker)
        seen.add(ticker)
        shares = _finite_positive(entry.get('shares'),ceiling=1e8)
        manually_entered_price = entry.get('price')
        price = None if manually_entered_price in (None,'') else _finite_positive(manually_entered_price,ceiling=1e7)
        out.append({'ticker':ticker,'shares':shares,'manual_quote':price})
    return out


def _request_retryable(error):
    """Only transient network/5xx errors; never re-request missing, invalid or 429-rated data."""
    try:
        import requests
        if isinstance(error, requests.HTTPError):
            code = getattr(getattr(error,'response',None),'status_code',None)
            return isinstance(code,int) and code>=500
        return isinstance(error, (requests.Timeout,requests.ConnectionError))
    except ImportError:
        return isinstance(error, (TimeoutError,ConnectionError))


def _limited_call(fn):
    for attempt in range(MAX_RETRIES+1):
        try:
            return fn()
        except Exception as exc:
            if attempt == MAX_RETRIES or not _request_retryable(exc):
                raise
            time.sleep(0.35*(attempt+1))
    raise AssertionError('unreachable')


def _safe_provider_error(exc):
    """Avoid leaking the Finnhub token through requests' exception URL text."""
    code=getattr(getattr(exc,'response',None),'status_code',None)
    if isinstance(code,int):
        return f'{type(exc).__name__}: provider HTTP {code} (check plan, access and endpoint status)'
    message=str(exc)
    message=re.sub(r'https?://\S+','[provider endpoint]',message)
    secret=os.getenv('FINNHUB_API_KEY','')
    if secret:message=message.replace(secret,'[REDACTED]')
    message=re.sub(r'(?i)(token|api[_-]?key)=([^\s&]+)',r'\1=[REDACTED]',message)
    return f'{type(exc).__name__}: {message[:180]}'


def _observed_database():
    # Snapshot date is the time of receipt, not the original rating publication date.
    connection=sqlite3.connect(str(DB),timeout=5)
    connection.execute('''CREATE TABLE IF NOT EXISTS snapshots (
       id INTEGER PRIMARY KEY, ticker TEXT NOT NULL, source TEXT NOT NULL,
       observed_day TEXT NOT NULL, observed_at TEXT NOT NULL,
       rating_period TEXT NOT NULL, payload_json TEXT NOT NULL,
       UNIQUE(ticker, source, observed_day, rating_period))''')
    return connection


def record_opinion(snapshot):
    with LOCK:
        db=_observed_database()
        try:
            observed_at = snapshot['observed_at']
            with db:
                db.execute('''INSERT OR IGNORE INTO snapshots
                   (ticker,source,observed_day,observed_at,rating_period,payload_json)
                   VALUES(?,?,?,?,?,?)''',(
                     snapshot['ticker'],snapshot['source'],observed_at[:10],observed_at,
                     snapshot['rating_period'],json.dumps(snapshot,sort_keys=True,allow_nan=False)))
        finally:
            db.close()


def analyst_observation(ticker, valid_ticker, provider='yahoo', *, include_actions=False):
    ticker=valid_ticker(ticker)
    if provider not in ('yahoo','finnhub'):
        raise ValueError('Choose Yahoo or Finnhub for analyst research')
    cache_key=(ticker,provider)
    now=time.monotonic()
    with LOCK:
        cached=CACHE.get(cache_key)
    if cached and now-cached['t']<CACHE_SECONDS and is_fresh(cached['value']['consensus']):
        result=dict(cached['value'])
    else:
        try:
            if provider=='finnhub':
                key=os.getenv('FINNHUB_API_KEY','')
                if not key:
                    raise ValueError('FINNHUB_API_KEY not configured on the local Python backend')
                snapshot=_limited_call(lambda:fetch_finnhub(ticker,key))
            else:
                snapshot=_limited_call(lambda:fetch_yahoo(ticker))
            record_opinion(snapshot)
            result={'status':'available','ticker':ticker, 'consensus':snapshot,
                    'fresh_for_research':bool(is_fresh(snapshot)),'actions_status':'not_requested','actions':[]}
        except Exception as exc:
            return {'status':'unavailable','ticker':ticker,'source':provider,
                    'reason':_safe_provider_error(exc),
                    'actions_status':'not_requested','actions':[]}
        with LOCK:
            CACHE[cache_key]={'t':time.monotonic(),'value':result}
    if include_actions:
        try:
            actions=_limited_call(lambda: fetch_finnhub_actions(ticker,os.getenv('FINNHUB_API_KEY',''))
                                  if provider=='finnhub' else fetch_yahoo_actions(ticker))
            result['actions_status']='available' if actions else 'none_reported_by_provider'
            result['actions']=actions[:10]
        except Exception as exc:
            result['actions_status']='unavailable: '+_safe_provider_error(exc)
            result['actions']=[]
    result['note']='Current analyst observation only; not a historical backtest input or a trained forecast.'
    return result


def _market_quote_table(tickers):
    """Get UNADJUSTED best-effort Yahoo quotes for position valuation only."""
    rows=yahoo_latest_quotes(tickers)
    if not isinstance(rows,pd.DataFrame):
        raise ValueError('Unadjusted valuation-quote feed unavailable')
    latest={}
    now=pd.Timestamp.now(tz='UTC')
    for row in rows.to_dict('records'):
        ticker=row.get('ticker')
        try:
            p=_finite_positive(row.get('price'),ceiling=1e7)
            dt=pd.to_datetime(row.get('timestamp_utc'),utc=True,errors='coerce')
            if pd.isna(dt) or (now-dt).total_seconds() > 7*86400 or (dt-now).total_seconds()>300:
                continue
            latest[ticker]={'price':p,'timestamp_utc':dt.isoformat(),
                            'source':row.get('feed','Yahoo quote (may be delayed)')}
        except (ValueError,TypeError,OverflowError):
            continue
    return latest


def _history_for_study(tickers):
    """Daily adjusted *completed* history only. No forward fill of absent stocks."""
    # Avoid importing server until runtime, because server imports this module.
    from server import completed_daily
    key=tuple(sorted(tickers))
    with LOCK:
        cached=HISTORY_CACHE.get(key)
        if cached and time.monotonic()-cached['at']<600:
            return cached['prices'].copy(),cached['source']
    data=completed_daily(download_market_data(tickers,years=2,min_history=128,batch_size=10))
    missing=[t for t in tickers if t not in data.close]
    if missing:raise ValueError('Missing adjusted history: '+', '.join(missing))
    frame=data.close[tickers].tail(260)
    if frame.isna().any().any():
        raise ValueError('Incomplete recent price history; no hypothetical weights produced')
    if len(frame)<127:
        raise ValueError('At least 126 synchronized completed returns are required')
    spy=data.close['SPY'].dropna()
    for t in tickers:
        seen=data.close[t].dropna()
        if seen.empty or (pd.DatetimeIndex(spy.index)>seen.index[-1]).sum()>2:
            raise ValueError('Stale stock history for '+t)
    if (datetime.now(timezone.utc).date()-pd.Timestamp(frame.index[-1]).date()).days>7:
        raise ValueError('Completed price history is stale; no portfolio study')
    with LOCK:
        if len(HISTORY_CACHE)>=8:
            oldest=min(HISTORY_CACHE,key=lambda x:HISTORY_CACHE[x]['at'])
            HISTORY_CACHE.pop(oldest,None)
        HISTORY_CACHE[key]={'prices':frame.copy(),'source':data.source,'at':time.monotonic()}
    return frame, data.source


def research_portfolio(payload, valid_ticker, *, history_loader=None, quote_loader=None,
                       opinion_loader=None, forecasts=None):
    started=time.perf_counter()
    if not isinstance(payload,dict):raise ValueError('Expected a portfolio research object')
    holdings=normalize_holdings(payload.get('holdings'),valid_ticker)
    provider=str(payload.get('provider','yahoo'))
    if provider not in ('yahoo','finnhub'):raise ValueError('Unsupported analyst provider')
    try:
        reserve=float(payload.get('cash_reserve',.10))
        cap=float(payload.get('max_position',.20))
    except (TypeError,ValueError):raise ValueError('Reserve and cap must be numbers')
    if not math.isfinite(reserve) or not math.isfinite(cap) or not 0<=reserve<1 or not 0<cap<=1:
        raise ValueError('Invalid reserve or position cap')
    names=[r['ticker'] for r in holdings]
    # Any explicitly entered price is treated as a user-supplied valuation, not real-time.
    needed=[r['ticker'] for r in holdings if r['manual_quote'] is None]
    quote_loader=quote_loader or _market_quote_table
    observed_quotes=quote_loader(needed) if needed else {}
    valuations={}
    for entry in holdings:
        t=entry['ticker']
        raw=(observed_quotes.get(t) if entry['manual_quote'] is None else
             {'price':entry['manual_quote'],'timestamp_utc':None,'source':'Manual valuation provided by user'})
        if raw is None:
            raise ValueError(f'Unadjusted valuation quote unavailable for {t}; enter its current price explicitly or retry later')
        p=_finite_positive(raw['price'],ceiling=1e7)
        valuations[t]={'ticker':t,'shares':entry['shares'],
                       'price':p,'market_value':p*entry['shares'],
                       'quote_source':raw['source'],'quote_time_utc':raw.get('timestamp_utc')}
    total=sum(v['market_value'] for v in valuations.values())
    if total<=0 or not math.isfinite(total):raise ValueError('Invalid total portfolio value')
    current={t:val['market_value']/total for t,val in valuations.items()}
    history_loader=history_loader or _history_for_study
    prices,history_source=history_loader(names)
    if not isinstance(prices,pd.DataFrame) or prices.empty:
        raise ValueError('Historical source returned no synchronized adjusted prices')
    last_completed_day=pd.Timestamp(prices.index[-1]).date()
    for h in holdings:
        if h['manual_quote'] is not None:
            continue  # Explicit manual prices are labeled user-supplied, not verified.
        stamp=valuations[h['ticker']].get('quote_time_utc')
        dt=pd.to_datetime(stamp,utc=True,errors='coerce')
        if pd.isna(dt) or dt.date()<last_completed_day:
            raise ValueError(f'Unadjusted valuation quote for {h["ticker"]} is older than last completed price history; no weights generated')
    opinion_loader=opinion_loader or analyst_observation
    with ThreadPoolExecutor(max_workers=MAX_AGENTS,thread_name_prefix='analyst-v32') as pool:
        futures={t:pool.submit(opinion_loader,t,valid_ticker,provider) for t in names}
        observations={}
        for t in names:
            try:observations[t]=futures[t].result()
            except Exception as exc:
                observations[t]={'status':'unavailable','ticker':t,'reason':_safe_provider_error(exc)}
    snaps={t:v['consensus'] for t,v in observations.items() if v.get('status')=='available'}
    qualified={}
    if isinstance(forecasts,dict):
        for t in names:
            value=forecasts.get(t)
            if isinstance(value,dict) and value.get('validation_passed') and value.get('state')=='available':
                try:
                    asof=pd.Timestamp(value.get('asof'))
                    age=(datetime.now(timezone.utc).date()-asof.date()).days
                    excess=float(value.get('expected_excess_return'))
                    if not 0<=age<=4 or not math.isfinite(excess):
                        continue
                    qualified[t]={'asof':asof.date().isoformat(), 'forecast_excess':excess}
                except (TypeError,ValueError,OverflowError):
                    continue
    study=portfolio_allocation_study(prices,current,forecasts=qualified,
        analyst_snapshots=snaps,cash_reserve=reserve,max_position=cap)
    targets=study.targets
    return {'status':'illustrative_only_unvalidated','version':'3.2',
            'calculated_utc':datetime.now(timezone.utc).isoformat(),
            'data_source':history_source,'holdings_count':len(names),'portfolio_value':round(total,2),'elapsed_ms':round(1000*(time.perf_counter()-started)),
            'positions':[{**valuations[t], 'current_weight':round(current[t],8),
                         'research_weight':round(targets[t],8),
                         'analyst_status':('stale' if observations[t]['status']=='available'
                             and not is_fresh(observations[t]['consensus']) else observations[t]['status']),
                         'analyst_coverage':snaps.get(t,{}).get('coverage'),
                         'analyst_shrunk_sentiment':study.analyst_signal[t],
                         'forecast_tilt':study.forecast_signal[t]} for t in names],
            'analysts':observations,
            'cash_reserve_requested':reserve,'cash_effective':round(1-study.exposure,8),
            'max_position':cap,'target_exposure':study.exposure,
            'annualized_vol_current':study.annualized_vol_current,
            'annualized_vol_hypothetical':study.annualized_vol_research,
            'illustrative_turnover_fraction':study.predicted_turnover_fraction,
            'sessions':study.sessions,'forecast_tilt_qualified_count':len(qualified),'warnings':study.warnings + [
               'Market-value estimates use supplied unadjusted prices, not adjusted risk prices.',
               'No trading, no brokerage integration, no proven analyst alpha, no PIT analyst history.'
            ],'research_only':True,'orders_placed':False,
            'opinion_snapshots_pit_eligible':False}
