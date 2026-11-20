"""Bounded, automatic news review for every modeled leaderboard company.

One RSS request per ticker; work advances in batches on Streamlit fragment reruns.
A database row holds last check time, errors, and source-attributed article data.
Local SQLite survives browser reruns but is *not* durable on Streamlit Cloud.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import json
import sqlite3
from pathlib import Path

from .market_cache import cache_path
from .news_dedupe import deduplicate_events
from .news import fetch_market_news

FRESH_SECONDS = 24 * 60 * 60
PRIORITY_FRESH_SECONDS = 15 * 60
ERROR_RETRY_SECONDS = 15 * 60
MAX_PER_BATCH = 24
MAX_PARALLEL = 3


def _db(path=None):
    conn = sqlite3.connect(str(path or cache_path()), timeout=20)
    conn.execute('PRAGMA busy_timeout=20000')
    conn.execute('''CREATE TABLE IF NOT EXISTS universe_news (
        ticker TEXT PRIMARY KEY, company TEXT NOT NULL, checked_utc TEXT NOT NULL,
        state TEXT NOT NULL, data TEXT NOT NULL, detail TEXT NOT NULL)''')
    return conn


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def _encode(items):
    return json.dumps([{**a, 'published_utc': a['published_utc'].isoformat()}
                       for a in items if isinstance(a.get('published_utc'), datetime)
                       and a['published_utc'].tzinfo], ensure_ascii=False)


def _decode(value):
    try:
        rows = json.loads(value)
        for r in rows:
            r['published_utc'] = _time(r.get('published_utc'))
        return rows
    except (TypeError, ValueError, KeyError):
        return []


def cached_coverage(symbols: list[str], *, now=None, path=None, priority_count=24):
    """A successful empty feed is checked; failed and stale feeds aren't."""
    now = now or datetime.now(timezone.utc)
    if not symbols:
        return {}, {}, {}
    unique = set(symbols)
    priority = set(symbols[:priority_count])
    checked, errors, timestamps = {}, {}, {}
    with _db(path) as conn:
        # Read once, rather than making one DB query per ticker.
        for ticker, company, ts, state, payload, detail in conn.execute(
                'SELECT ticker, company, checked_utc, state, data, detail FROM universe_news'):
            if ticker not in unique:
                continue
            age = max(0, (now - _time(ts)).total_seconds())
            timestamps[ticker] = (age, state, company)
            ttl = PRIORITY_FRESH_SECONDS if ticker in priority else FRESH_SECONDS
            if state == 'success' and age < ttl:
                checked[ticker] = _decode(payload)
            elif state == 'error' and age < ERROR_RETRY_SECONDS:
                errors[ticker] = detail
    return checked, errors, timestamps


def update_universe_news(items: list[tuple[str, str]], *, fetcher=fetch_market_news,
                         batch_size=MAX_PER_BATCH, now=None, path=None):
    """Check next missing/stale tickers in priority order. No manual click needed.

    A failed source isn't marked checked. We throttle failures for 15 minutes,
    and save a distinct copy per ticker, keeping two companies' events separate.
    """
    now = now or datetime.now(timezone.utc)
    selected = []
    seen = set()
    for ticker, company in items:
        key = str(ticker).upper().strip()
        if key and key not in seen:
            seen.add(key)
            selected.append((key, str(company or key)))
    before, errors, ages = cached_coverage([k for k, _ in selected], now=now, path=path)
    pending = []
    for index, (ticker, name) in enumerate(selected):
        age, state, old_name = ages.get(ticker, (float('inf'), 'missing', ''))
        ttl = (PRIORITY_FRESH_SECONDS if index < 24 else FRESH_SECONDS) if state == 'success' else ERROR_RETRY_SECONDS
        # A ticker's company name can change following a deal / reorganization;
        # stale-company search results must never be silently reused.
        if old_name != name or age >= ttl:
            pending.append((ticker, name))
    pending = pending[:max(0, min(int(batch_size), MAX_PER_BATCH))]
    results = []
    if pending:
        with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(pending))) as pool:
            tasks = {pool.submit(fetcher, ticker, name): (ticker, name) for ticker, name in pending}
            for task in as_completed(tasks):
                ticker, name = tasks[task]
                try:
                    articles, failures = task.result()
                    if failures:
                        results.append((ticker, name, 'error', [], '; '.join(map(str, failures))))
                    else:
                        distinct = deduplicate_events(articles, ticker=ticker, company=name)
                        results.append((ticker, name, 'success', distinct, ''))
                except Exception as exc:
                    results.append((ticker, name, 'error', [], type(exc).__name__))
        with _db(path) as conn:
            for ticker, name, state, articles, detail in results:
                conn.execute('''INSERT INTO universe_news(ticker,company,checked_utc,state,data,detail)
                                VALUES (?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET
                                company=excluded.company, checked_utc=excluded.checked_utc,
                                state=excluded.state, data=excluded.data, detail=excluded.detail''',
                             (ticker, name, now.isoformat(), state, _encode(articles), detail))
    checked, errors, _ = cached_coverage([k for k, _ in selected], now=now, path=path)
    return {'checked':checked, 'errors':errors, 'done':len(checked),
            'total':len(selected), 'attempted':len(results),
            'remaining':max(0,len(selected)-len(checked)),
            'unique_events':sum(len(v) for v in checked.values())}
