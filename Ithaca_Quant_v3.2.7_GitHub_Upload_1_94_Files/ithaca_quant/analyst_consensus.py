"""Attributed, CURRENT analyst consensus for portfolio research.

Analyst snapshots are observations made *when fetched*, not point-in-time records
for historic backtests. We deliberately do not backfill snapshots into prior dates,
or assume a published price target predicts a 20-day relative return.
"""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite
import re
from typing import Any

RATING_KEYS = ('strongBuy', 'buy', 'hold', 'sell', 'strongSell')
_SYMBOL = re.compile(r'^[A-Z0-9][A-Z0-9.\-]{0,14}$')


def _number(value: Any) -> float | None:
    try:
        x = float(value)
        return x if isfinite(x) else None
    except (TypeError, ValueError):
        return None


def parse_consensus(ticker: str, *, counts: dict[str, Any], targets: dict[str, Any] | None = None,
                    source: str, observed_at: str, rating_period: str = 'unknown') -> dict:
    """Normalize observed recommendation counts; no fabricated neutral fallback."""
    t = ticker.upper().strip()
    if not _SYMBOL.fullmatch(t):
        raise ValueError('Invalid symbol')
    if not source.strip() or not observed_at:
        raise ValueError('Analyst observation requires source and fetch time')
    dt = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Fetch timestamp must contain a timezone')
    normalized = {}
    for key in RATING_KEYS:
        raw = _number(counts.get(key, 0))
        if raw is None or raw < 0 or not raw.is_integer():
            raise ValueError(f'Invalid analyst count: {key}')
        normalized[key] = int(raw)
    n = sum(normalized.values())
    bullish = normalized['strongBuy'] + normalized['buy']
    bearish = normalized['sell'] + normalized['strongSell']
    raw_score = (2*normalized['strongBuy'] + normalized['buy'] - normalized['sell']
                 - 2*normalized['strongSell']) / (2*n) if n else None
    # As an exploratory conviction input, require coverage and shrink aggressively.
    score = raw_score * n/(n+20) if n >= 3 else None
    targets = targets or {}
    normalized_targets = {}
    for key in ('low', 'mean', 'median', 'high'):
        value = _number(targets.get(key))
        normalized_targets[key] = value if value is not None and value > 0 else None
    if (normalized_targets['low'] is not None and normalized_targets['high'] is not None
            and normalized_targets['low'] > normalized_targets['high']):
        raise ValueError('Analyst target low exceeds high')
    return {'ticker': t, 'source': source, 'observed_at': dt.astimezone(timezone.utc).isoformat(),
            'rating_period': str(rating_period), 'rating_counts': normalized, 'coverage': n,
            'bullish_share': bullish/n if n else None,
            'bearish_share': bearish/n if n else None,
            'raw_sentiment': raw_score, 'shrunk_sentiment': score,
            'price_targets': normalized_targets,
            'historical_backtest_eligible': False}


def _latest_finnhub(rows):
    if not isinstance(rows, list):
        raise ValueError('Finnhub returned invalid recommendation data')
    valid = [r for r in rows if isinstance(r, dict) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(r.get('period', '')))]
    return max(valid, key=lambda x: x['period']) if valid else None


def fetch_finnhub(ticker: str, api_key: str) -> dict:
    """Use official API requests; key is never embedded in returned metadata."""
    import requests
    if not api_key.strip():
        raise ValueError('FINNHUB_API_KEY is not configured')
    t = ticker.upper().strip()
    if not _SYMBOL.fullmatch(t):
        raise ValueError('Invalid symbol')
    observed = datetime.now(timezone.utc).isoformat()
    base = 'https://finnhub.io/api/v1/'
    def get(path):
        response = requests.get(base+path, params={'symbol': t, 'token': api_key}, timeout=12)
        response.raise_for_status()
        return response.json()
    rec = _latest_finnhub(get('stock/recommendation'))
    if rec is None:
        raise ValueError(f'No current analyst consensus returned for {t}')
    try:
        targets = get('stock/price-target')
        targets = {k: targets.get('target'+k.capitalize()) for k in ('low','mean','median','high')} if isinstance(targets,dict) else {}
    except (requests.RequestException, ValueError):
        targets = {}
    return parse_consensus(t, counts=rec, targets=targets, source='Finnhub',
                           observed_at=observed, rating_period=str(rec['period']))


def fetch_yahoo(ticker: str) -> dict:
    """Best-effort Yahoo Finance recommendations; sometimes unavailable/rate-limited."""
    import yfinance as yf
    t = ticker.upper().strip()
    if not _SYMBOL.fullmatch(t):
        raise ValueError('Invalid symbol')
    observed = datetime.now(timezone.utc).isoformat()
    obj = yf.Ticker(t)
    rec = obj.get_recommendations_summary()
    if rec is None or getattr(rec, 'empty', True):
        raise ValueError(f'No current analyst recommendations returned for {t}')
    if 'period' in rec.columns:
        recent = rec.loc[rec['period'].astype(str).eq('0m')]
        if recent.empty:
            raise ValueError('Yahoo returned no current-month consensus')
        row = recent.iloc[0]
    else:
        raise ValueError('Yahoo recommendations are missing period labels')
    try:
        targets = obj.get_analyst_price_targets() or {}
    except (ValueError, KeyError, TypeError, RuntimeError):
        targets = {}
    return parse_consensus(t, counts={key: row.get(key,0) for key in RATING_KEYS},
                           targets=targets, source='Yahoo Finance via yfinance',
                           observed_at=observed, rating_period='0m (current snapshot)')


def is_fresh(snapshot: dict, *, at: datetime | None = None, max_age_days: int = 7) -> bool:
    try:
        now = at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            return False
        observed = datetime.fromisoformat(snapshot['observed_at'].replace('Z', '+00:00'))
        age = (now - observed).total_seconds()
        if not (0 <= age <= max_age_days*86400):
            return False
        # An API response retrieved today may still contain very old ratings.
        # Finnhub supplies period dates; '0m' is Yahoo's live snapshot label.
        period = str(snapshot.get('rating_period',''))
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',period):
            source_period = datetime.fromisoformat(period).date()
            period_age = (now.date()-source_period).days
            if not 0 <= period_age <= 65:
                return False
        return True
    except (KeyError, TypeError, ValueError):
        return False


def snapshot_to_row(snap: dict, quote_price: float | None = None) -> dict:
    target = snap.get('price_targets', {}).get('mean')
    price = _number(quote_price)
    upside = target/price - 1 if target and price and price > 0 else None
    return {'Ticker': snap['ticker'], 'Provider': snap['source'],
            'Period': snap['rating_period'], 'Analysts': snap['coverage'],
            'Buy/strong buy': snap['rating_counts']['buy']+snap['rating_counts']['strongBuy'],
            'Hold': snap['rating_counts']['hold'],
            'Sell/strong sell': snap['rating_counts']['sell']+snap['rating_counts']['strongSell'],
            'Consensus score (shrunk)': snap.get('shrunk_sentiment'),
            'Mean price target': target, 'Target vs latest quote': upside,
            'Observed (UTC)': snap['observed_at'],
            'Historical PIT eligible': False}


def _actions_frame(ticker: str, items: list[dict], source: str, *, limit: int = 15):
    """Lightweight attributed opinion-history view, never model-training history."""
    rows = []
    for raw in items:
        firm = str(raw.get('firm') or raw.get('company') or '').strip()[:120]
        when = str(raw.get('date') or raw.get('published') or '').strip()[:32]
        action = str(raw.get('action') or '').strip()[:80]
        old = str(raw.get('from_grade') or raw.get('fromGrade') or '').strip()[:80]
        new = str(raw.get('to_grade') or raw.get('toGrade') or '').strip()[:80]
        if not firm or not when or not (action or new):
            continue
        rows.append({'Ticker':ticker, 'Date':when, 'Analyst firm':firm,
                     'Change':action or 'rating published', 'Prior grade':old,
                     'New grade':new, 'Provider':source})
    return sorted(rows, key=lambda x:x['Date'], reverse=True)[:limit]


def fetch_finnhub_actions(ticker: str, api_key: str, *, days: int = 90):
    """Most recent firm-level actions supplied by Finnhub; date filter enforced."""
    from datetime import timedelta
    import requests
    t=ticker.upper().strip()
    if not _SYMBOL.fullmatch(t) or not api_key.strip():
        raise ValueError('Ticker and Finnhub key required')
    end = datetime.now(timezone.utc).date()
    start = end-timedelta(days=days)
    response=requests.get('https://finnhub.io/api/v1/stock/upgrade-downgrade',
                          params={'symbol':t,'from':start.isoformat(),'to':end.isoformat(),
                                  'token':api_key},timeout=12)
    response.raise_for_status()
    raw=response.json()
    if not isinstance(raw,list):
        raise ValueError('Invalid analyst action response')
    actions=[]
    for item in raw:
        if not isinstance(item,dict):continue
        stamp=item.get('gradeTime')
        try:
            if isinstance(stamp,(int,float)):
                on=datetime.fromtimestamp(stamp,timezone.utc).date()
            else:
                on=datetime.fromisoformat(str(stamp).replace('Z','+00:00')).date()
            if not start<=on<=end:continue
            actions.append({**item,'date':on.isoformat(), 'firm':item.get('company')})
        except (ValueError,TypeError,OverflowError):
            continue
    return _actions_frame(t,actions,'Finnhub')


def fetch_yahoo_actions(ticker: str, *, days: int = 90):
    """Firm-attributed Yahoo upgrades/downgrades; timestamps as reported."""
    import yfinance as yf
    import pandas as pd
    t=ticker.upper().strip()
    if not _SYMBOL.fullmatch(t):
        raise ValueError('Invalid ticker')
    frame=yf.Ticker(t).get_upgrades_downgrades()
    if frame is None or getattr(frame,'empty',True):
        return []
    end=pd.Timestamp.now(tz='UTC')
    start=end-pd.Timedelta(days=days)
    rows=[]
    for dt,item in frame.iterrows():
        stamp=pd.to_datetime(dt,utc=True,errors='coerce')
        if pd.isna(stamp) or not start<=stamp<=end:
            continue
        rows.append({'date':stamp.date().isoformat(),'firm':item.get('Firm',item.get('firm')),
                     'action':item.get('Action',item.get('action')),
                     'from_grade':item.get('FromGrade',item.get('fromGrade')),
                     'to_grade':item.get('ToGrade',item.get('toGrade'))})
    return _actions_frame(t,rows,'Yahoo Finance via yfinance')
