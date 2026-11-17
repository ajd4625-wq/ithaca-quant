"""Timestamped archive of fetched headlines for possible *future* ML training.

A story is not known to the model until it was FIRST SEEN by this app, even if
its publication timestamp is earlier. This prevents the common look-ahead bug
of rebuilding an old forecast with a headline downloaded weeks later.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import re
import sqlite3
import pandas as pd
import numpy as np
from .market_cache import cache_path


def _db(path=None):
    conn = sqlite3.connect(str(path or cache_path()), timeout=20)
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("""CREATE TABLE IF NOT EXISTS news_archive (
        ticker TEXT NOT NULL, headline_key TEXT NOT NULL, publisher TEXT NOT NULL,
        title TEXT NOT NULL, url TEXT NOT NULL, published_utc TEXT NOT NULL,
        first_seen_utc TEXT NOT NULL, sentiment REAL NOT NULL, relevance REAL NOT NULL,
        PRIMARY KEY(ticker, headline_key))""")
    return conn


def archive_headlines(ticker: str, report: dict, *, path=None, now=None) -> int:
    ticker = ticker.upper().strip()
    if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker):
        raise ValueError("Invalid ticker for news archival")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Archive timestamp must be UTC-aware")
    inserted = 0
    from . import remote_store
    remote_rows = []
    with _db(path) as conn:
        for item in report.get("headlines", []):
            title = str(item.get("title", ""))
            url = str(item.get("url", ""))
            published = item.get("published_utc")
            if not title or not url.startswith("https://") or not isinstance(published, datetime) or published.tzinfo is None:
                continue
            if published > now or (now - published).days > 7:
                continue
            h = hashlib.sha256(re.sub(r"[^a-z0-9]", "", title.lower()).encode()).hexdigest()
            row = (ticker, h, str(item.get("publisher", "")), title[:350], url,
                   published.astimezone(timezone.utc).isoformat(), now.astimezone(timezone.utc).isoformat(),
                   float(item.get("sentiment") or 0.0),
                   1.0 if item.get("relevance") == "matched ticker/company" else 0.4)
            remote_rows.append(dict(zip(('ticker','headline_key','publisher','title','url',
                            'published_utc','first_seen_utc','sentiment','relevance'), row)))
            changed = conn.execute("""INSERT OR IGNORE INTO news_archive(
                ticker,headline_key,publisher,title,url,published_utc,first_seen_utc,sentiment,relevance)
                VALUES(?,?,?,?,?,?,?,?,?)""", row)
            inserted += max(0, changed.rowcount)
    if path is None and remote_store.remote_enabled() and remote_rows:
        remote_store.put_headlines(remote_rows)
    return inserted


def recorded_headlines(ticker: str, path=None) -> pd.DataFrame:
    from . import remote_store
    if path is None and remote_store.remote_enabled():
        rows = remote_store.get_headlines(ticker.upper())
    else:
        with _db(path) as conn:
            rows = conn.execute("""SELECT published_utc, first_seen_utc, sentiment, relevance, publisher, title
                               FROM news_archive WHERE ticker=? ORDER BY first_seen_utc ASC""",
                            (ticker.upper(),)).fetchall()
    cols = ["published_utc", "first_seen_utc", "sentiment", "relevance", "publisher", "title"]
    result = pd.DataFrame(rows, columns=cols)
    if not result.empty:
        result["published_utc"] = pd.to_datetime(result["published_utc"], utc=True)
        result["first_seen_utc"] = pd.to_datetime(result["first_seen_utc"], utc=True)
    return result


def archived_features(ticker, sessions, *, path=None, headlines=None):
    """Seven-calendar-day observed news features, usable NEXT business day.

    An empty news archive gives an explicit 0 availability indicator, never an
    invented bullish/neutral signal. Cached provider outages never inject fake
    historical events or change previously recorded first-seen timestamps.
    """
    days = pd.DatetimeIndex(pd.to_datetime(sessions, utc=True)).tz_localize(None).normalize()
    records = headlines if headlines is not None else recorded_headlines(ticker, path)
    columns = ["news_sentiment_7d", "news_count_7d", "news_available",
               "news_earnings_7d", "news_guidance_7d", "news_analysts_7d",
               "news_regulatory_7d", "news_macro_7d"]
    out = pd.DataFrame(0.0, index=days, columns=columns)
    if records.empty:
        return out
    data = records.copy()
    data["known_date"] = pd.to_datetime(data["first_seen_utc"], utc=True).dt.tz_localize(None).dt.normalize()
    data["published_date"] = pd.to_datetime(data["published_utc"], utc=True).dt.tz_localize(None).dt.normalize()
    # Next business day is conservative for news published during or after the
    # session. Explicitly no same-session lookahead even for 9am headlines.
    data["effective"] = data["known_date"] + pd.offsets.BDay(1)
    for day in days:
        recent = data.loc[(data["effective"] <= day) &
                          (data["effective"] >= day - pd.Timedelta(days=7)) &
                          (data["published_date"] >= day - pd.Timedelta(days=14))]
        if recent.empty:
            continue
        weights = pd.to_numeric(recent["relevance"], errors="coerce").fillna(0)
        if weights.sum() <= 0:
            continue
        out.loc[day, "news_sentiment_7d"] = float(np.clip(np.average(recent["sentiment"], weights=weights) / 3, -1, 1))
        out.loc[day, "news_count_7d"] = float(min(30, len(recent)) / 30)
        out.loc[day, "news_available"] = 1.0
        from .news_events import headline_event_counts
        counts = headline_event_counts(recent)
        for tag in ("earnings", "guidance", "analysts", "regulatory", "macro"):
            out.loc[day, f"news_{tag}_7d"] = float(min(20, counts[tag]) / 20.0)
    return out


def import_vendor_archive(frame: pd.DataFrame, *, provenance_confirmed=False,
                          path=None, now=None) -> int:
    """Load a timestamped news vendor export, never invent historical first-seen.

    Caller must confirm rights to use the export and that first_seen_utc is
    when the data provider originally made the item available (NOT import time).
    This assertion cannot be verified by software; audit the vendor contract.
    """
    if not provenance_confirmed:
        raise ValueError('Historical availability and data-use rights must be confirmed')
    required = {'ticker','title','url','publisher','published_utc',
                'first_seen_utc','sentiment','relevance'}
    missing = required-set(frame.columns)
    if missing:
        raise ValueError('Missing archive columns: '+', '.join(sorted(missing)))
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Current timestamp must be timezone-aware')
    prepared = []
    for r in frame.to_dict('records'):
        ticker = str(r['ticker']).upper().strip()
        if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}',ticker):
            raise ValueError('Invalid ticker')
        pub = pd.to_datetime(r['published_utc'],utc=True,errors='coerce')
        seen = pd.to_datetime(r['first_seen_utc'],utc=True,errors='coerce')
        if pd.isna(pub) or pd.isna(seen) or seen < pub or seen > now:
            raise ValueError('News timestamps are missing, in the future, or out of order')
        url = str(r['url']).strip()
        title = str(r['title']).strip()[:350]
        if not url.startswith('https://') or not title:
            raise ValueError('Each news item needs a valid HTTPS URL and title')
        score = float(r['sentiment'])
        relevance = float(r['relevance'])
        if not (np.isfinite(score) and -3 <= score <= 3 and
                np.isfinite(relevance) and 0 <= relevance <= 1):
            raise ValueError('Sentiment must be -3..3; relevance 0..1')
        h = hashlib.sha256(re.sub(r'[^a-z0-9]','',title.lower()).encode()).hexdigest()
        prepared.append((ticker,h,str(r['publisher'])[:100],title,url,pub.isoformat(),
                         seen.isoformat(),score,relevance))
    # Validate the entire import before changing the database.
    if not prepared:
        return 0
    from . import remote_store
    if path is None and remote_store.remote_enabled():
        cols = ('ticker','headline_key','publisher','title','url','published_utc',
                'first_seen_utc','sentiment','relevance')
        return remote_store.put_headlines([dict(zip(cols,row)) for row in prepared])
    with _db(path) as conn:
        old_count = conn.total_changes
        conn.executemany('''INSERT OR IGNORE INTO news_archive (
              ticker,headline_key,publisher,title,url,published_utc,first_seen_utc,sentiment,relevance)
              VALUES (?,?,?,?,?,?,?,?,?)''', prepared)
        return conn.total_changes - old_count
