"""Opt-in durable SQL store for Streamlit and scheduled worker.

Set ITHACA_DATABASE_URL to a PostgreSQL connection URL. Data is shared across
workers. Local SQLite continues to work without credentials. Never log URL.
"""
from __future__ import annotations
import os
from functools import lru_cache
from datetime import datetime, timezone


def remote_enabled():
    return bool(os.environ.get('ITHACA_DATABASE_URL', '').strip())


@lru_cache(maxsize=4)
def _tables(url):
    from sqlalchemy import create_engine, MetaData, Table, Column, String, LargeBinary, Text, Float
    from sqlalchemy import UniqueConstraint
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)
    meta = MetaData()
    snapshots = Table('iq_snapshots', meta,
        Column('key', String(160), primary_key=True), Column('kind', String(40)),
        Column('updated', Text), Column('content', LargeBinary))
    headlines = Table('iq_headlines', meta,
        Column('ticker', String(16), primary_key=True),
        Column('headline_key', String(64), primary_key=True),
        Column('publisher', Text), Column('title', Text), Column('url', Text),
        Column('published_utc', Text), Column('first_seen_utc', Text),
        Column('sentiment', Float), Column('relevance', Float))
    forecasts = Table('iq_forecasts', meta,
        Column('ticker', String(16), primary_key=True),
        Column('asof', String(20), primary_key=True),
        Column('horizon', String(8), primary_key=True),
        Column('forecast', Float), Column('observed', Float),
        Column('model', String(100)), Column('created_utc', Text), Column('resolved_utc', Text))
    meta.create_all(engine)
    # Existing cloud databases may predate the evaluation timestamp field.
    from sqlalchemy import inspect, text
    if 'resolved_utc' not in {c['name'] for c in inspect(engine).get_columns('iq_forecasts')}:
        with engine.begin() as conn:
            conn.execute(text('ALTER TABLE iq_forecasts ADD COLUMN resolved_utc TEXT'))
    return engine, snapshots, headlines, forecasts


def tables():
    url = os.environ.get('ITHACA_DATABASE_URL', '').strip()
    if not url:
        raise RuntimeError('Cloud database is not configured')
    if not url.startswith(('postgresql+psycopg://', 'postgresql://', 'sqlite:///')):
        raise ValueError('Database URL must be PostgreSQL or SQLite; credentials are never shown')
    if url.startswith('postgresql://'):
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    return _tables(url)


def put_snapshot(key, kind, stamp, content):
    from sqlalchemy import select, insert, update
    engine, table, _, _ = tables()
    with engine.begin() as con:
        exists = con.execute(select(table.c.key).where(table.c.key == key)).first()
        values = dict(key=key, kind=kind, updated=stamp, content=content)
        if exists:
            con.execute(update(table).where(table.c.key == key).values(**values))
        else:
            con.execute(insert(table).values(**values))


def get_snapshot(key, kind):
    from sqlalchemy import select
    engine, table, _, _ = tables()
    with engine.connect() as con:
        row = con.execute(select(table.c.kind, table.c.updated, table.c.content).where(table.c.key == key)).first()
    return row if row and row[0] == kind else None


def put_headlines(rows):
    from sqlalchemy import insert, select
    engine, _, table, _ = tables()
    added = 0
    with engine.begin() as con:
        for r in rows:
            exists = con.execute(select(table.c.headline_key).where(
                (table.c.ticker == r['ticker']) & (table.c.headline_key == r['headline_key']))).first()
            if not exists:
                con.execute(insert(table).values(**r))
                added += 1
    return added


def get_headlines(ticker):
    from sqlalchemy import select
    engine, _, table, _ = tables()
    with engine.connect() as con:
        return con.execute(select(table.c.published_utc, table.c.first_seen_utc,
                                  table.c.sentiment, table.c.relevance, table.c.publisher,
                                  table.c.title).where(table.c.ticker == ticker).order_by(table.c.first_seen_utc)).all()


def save_prediction(ticker, asof, horizon, forecast, model):
    from sqlalchemy import insert, select
    engine, _, _, table = tables()
    values = {'ticker':ticker, 'asof':asof, 'horizon':str(horizon),
              'forecast':float(forecast), 'observed':None, 'model':str(model)[:100],
              'created_utc':datetime.now(timezone.utc).isoformat(), 'resolved_utc':None}
    with engine.begin() as con:
        previous = con.execute(select(table.c.ticker).where(
            (table.c.ticker == ticker) & (table.c.asof == asof) &
            (table.c.horizon == str(horizon)))).first()
        if not previous:
            con.execute(insert(table).values(**values))


def fetch_predictions():
    from sqlalchemy import select
    engine, _, _, table = tables()
    with engine.connect() as con:
        return [dict(r) for r in con.execute(select(table)).mappings().all()]


def save_observations(updates):
    from sqlalchemy import update
    engine, _, _, table = tables()
    with engine.begin() as con:
        for ticker, asof, horizon, value in updates:
            con.execute(update(table).where((table.c.ticker == ticker) &
                (table.c.asof == asof) & (table.c.horizon == str(horizon)) &
                table.c.observed.is_(None)).values(observed=float(value),resolved_utc=datetime.now(timezone.utc).isoformat()))


def health():
    if not remote_enabled():
        return {'backend':'Local SQLite', 'reachable':True,
                'note':'Local files may disappear on Streamlit Cloud restart.'}
    try:
        from sqlalchemy import text
        engine, *_ = tables()
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return {'backend':'Configured SQL database', 'reachable':True, 'note':'Durable backend responding.'}
    except Exception as exc:
        return {'backend':'Configured SQL database', 'reachable':False,
                'note':f'Database connection unavailable ({type(exc).__name__}).'}
