"""Private-code, manually recorded virtual holdings for Ithaca Quant.

A portfolio is unlocked with an unguessable recovery code. The database stores
only its SHA-256 digest, never the recovery code. Users MUST save their code.
No orders are transmitted to a brokerage or competition platform.

Local SQLite is convenient for development but not durable across Streamlit
Community Cloud restarts. Set ITHACA_DATABASE_URL to PostgreSQL for persistence.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from hashlib import sha256
from math import isfinite
from pathlib import Path
import os
import re
import secrets
from uuid import uuid4

import pandas as pd
from sqlalchemy import Column, Float, Index, MetaData, String, Table, create_engine, insert, select, delete, update, inspect, text

_CODE = re.compile(r"IQ-[A-Za-z0-9_-]{32}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,11}")


def new_access_code() -> str:
    return 'IQ-' + secrets.token_urlsafe(24)


def owner_id(access_code: str) -> str:
    code = str(access_code).strip()
    if not _CODE.fullmatch(code):
        raise ValueError('Enter the complete 35-character portfolio recovery code beginning with IQ-.')
    return sha256(code.encode('ascii')).hexdigest()


def validate_trade(symbol: str, side: str, shares: float, price: float,
                   trade_date: str, fees: float = 0) -> dict:
    symbol = str(symbol).strip().upper()
    side = str(side).strip().upper()
    if not _SYMBOL.fullmatch(symbol) or symbol == 'SPY':
        raise ValueError('Enter a valid individual NYSE/Nasdaq ticker (not SPY).')
    if side not in ('BUY', 'SELL'):
        raise ValueError('Trade type must be BUY or SELL.')
    for key, value in [('Shares', shares), ('Price', price), ('Fees', fees)]:
        if not isfinite(float(value)):
            raise ValueError(f'{key} must be finite.')
    if float(shares) <= 0 or float(shares) > 1e9:
        raise ValueError('Number of shares must be positive.')
    if float(price) <= 0 or float(price) > 1e9:
        raise ValueError('Trade price must be positive.')
    if float(fees) < 0 or float(fees) > 1e6:
        raise ValueError('Fees must be zero or positive.')
    try:
        on = date.fromisoformat(str(trade_date))
    except (ValueError, TypeError) as exc:
        raise ValueError('Purchase/sale date must use YYYY-MM-DD.') from exc
    if on > datetime.now(timezone.utc).date():
        raise ValueError('Future-dated transactions cannot be recorded.')
    return {'ticker':symbol, 'side':side, 'shares':float(shares),
            'price':float(price), 'fees':float(fees), 'trade_date':on.isoformat()}


def _db_url() -> str:
    url = os.environ.get('ITHACA_DATABASE_URL', '').strip()
    if url:
        if url.startswith('postgresql://'):
            url = 'postgresql+psycopg://' + url[len('postgresql://'):]
        if not url.startswith(('postgresql+psycopg://', 'sqlite:///')):
            raise ValueError('Only PostgreSQL or local SQLite databases are supported.')
        return url
    folder = Path.cwd() / '.ithaca_quant_cache'
    folder.mkdir(parents=True, exist_ok=True)
    return 'sqlite:///' + str(folder / 'private_portfolios.sqlite3')


@lru_cache(maxsize=4)
def _tables(url: str):
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800)
    meta = MetaData()
    portfolios = Table('iq_private_portfolios', meta,
        Column('owner_hash', String(64), primary_key=True),
        Column('created_utc', String(50), nullable=False),
        Column('updated_utc', String(50), nullable=False))
    trades = Table('iq_private_trades', meta,
        Column('id', String(36), primary_key=True),
        Column('owner_hash', String(64), nullable=False),
        Column('ticker', String(16), nullable=False),
        Column('side', String(4), nullable=False),
        Column('shares', Float, nullable=False),
        Column('price', Float, nullable=False),
        Column('fees', Float, nullable=False),
        Column('trade_date', String(10), nullable=False),
        Column('created_utc', String(50), nullable=False))
    forecasts = Table('iq_private_forecasts', meta,
        Column('owner_hash', String(64), primary_key=True),
        Column('ticker', String(16), primary_key=True),
        Column('horizon', String(8), primary_key=True),
        Column('asof', String(10), nullable=False),
        Column('updated_utc', String(50), nullable=False),
        Column('forecast_excess', Float, nullable=False),
        Column('prob_gain', Float),
        Column('prob_boom', Float),
        Column('vol_20', Float),
        Column('model_price', Float),
        Column('review_level', Float),
        Column('exit_review', String(60)),
        Column('entry_watch', String(60)),
        Column('selected_model', String(100)))
    # Persisted upload fingerprints prevent accidental double-import after an app restart.
    Table('iq_private_imports', meta,
        Column('owner_hash', String(64), primary_key=True),
        Column('source_hash', String(64), primary_key=True),
        Column('created_utc', String(50), nullable=False))
    Index('ix_iq_private_trades_owner', trades.c.owner_hash)
    meta.create_all(engine)
    # v2.5 migration: create_all does not add columns to existing databases.
    # Ensure previously saved PostgreSQL and SQLite portfolios remain usable.
    existing = {col['name'] for col in inspect(engine).get_columns('iq_private_forecasts')}
    if 'entry_watch' not in existing:
        with engine.begin() as con:
            con.execute(text('ALTER TABLE iq_private_forecasts ADD COLUMN entry_watch VARCHAR(60)'))
    return engine, portfolios, trades, forecasts


def tables():
    return _tables(_db_url())


def is_durable_cloud_storage() -> bool:
    return _db_url().startswith('postgresql+psycopg://')


def create_portfolio(code: str) -> None:
    owner = owner_id(code)
    engine, portfolios, _, _ = tables()
    stamp = datetime.now(timezone.utc).isoformat()
    with engine.begin() as con:
        if con.execute(select(portfolios.c.owner_hash).where(portfolios.c.owner_hash == owner)).first():
            raise ValueError('A portfolio with this code already exists.')
        con.execute(insert(portfolios).values(owner_hash=owner, created_utc=stamp, updated_utc=stamp))


def portfolio_exists(code: str) -> bool:
    owner = owner_id(code)
    engine, portfolios, _, _ = tables()
    with engine.connect() as con:
        return con.execute(select(portfolios.c.owner_hash).where(portfolios.c.owner_hash == owner)).first() is not None


def _read_trades(con, trades_table, owner: str) -> list[dict]:
    records = con.execute(select(trades_table).where(trades_table.c.owner_hash == owner)
        .order_by(trades_table.c.trade_date, trades_table.c.created_utc, trades_table.c.id)).mappings().all()
    return [dict(r) for r in records]


def get_trades(code: str) -> list[dict]:
    owner = owner_id(code)
    engine, portfolios, trades, _ = tables()
    with engine.connect() as con:
        if con.execute(select(portfolios.c.owner_hash).where(portfolios.c.owner_hash == owner)).first() is None:
            raise ValueError('Portfolio not found. Verify the recovery code and database configuration.')
        return _read_trades(con, trades, owner)


def _check_chronology(records: list[dict]) -> None:
    open_qty: dict[str, float] = {}
    for trade in sorted(records, key=lambda x:(x['trade_date'], x['created_utc'], x['id'])):
        symbol = trade['ticker']
        qty = float(trade['shares'])
        was = open_qty.get(symbol, 0.)
        if trade['side'] == 'SELL' and qty > was + 1e-8:
            raise ValueError(f'{symbol}: cannot sell {qty:g} shares; only {was:g} owned at that date.')
        open_qty[symbol] = was + qty if trade['side'] == 'BUY' else max(0., was - qty)


def add_trade(code: str, symbol: str, side: str, shares: float, price: float,
              trade_date: str, fees: float = 0.) -> str:
    owner = owner_id(code)
    row = validate_trade(symbol, side, shares, price, trade_date, fees)
    row.update({'id':str(uuid4()), 'owner_hash':owner, 'created_utc':datetime.now(timezone.utc).isoformat()})
    engine, portfolios, trades, _ = tables()
    with engine.begin() as con:
        if con.execute(select(portfolios.c.owner_hash).where(portfolios.c.owner_hash == owner)).first() is None:
            raise ValueError('The portfolio was not found.')
        _check_chronology(_read_trades(con, trades, owner) + [row])
        con.execute(insert(trades).values(**row))
        con.execute(update(portfolios).where(portfolios.c.owner_hash == owner)
                    .values(updated_utc=datetime.now(timezone.utc).isoformat()))
    return row['id']


def import_trades(code: str, rows: list[dict], *, source_hash: str | None = None) -> int:
    """Atomically add a verified CSV backup; never partially import a bad file."""
    owner = owner_id(code)
    if source_hash is not None and not re.fullmatch(r'[0-9a-f]{64}', str(source_hash)):
        raise ValueError('Invalid source image fingerprint.')
    if len(rows) > 5000:
        raise ValueError('Maximum 5,000 transactions per import.')
    stamp = datetime.now(timezone.utc)
    prepared = []
    for i, raw in enumerate(rows):
        checked = validate_trade(raw['ticker'], raw['side'], raw['shares'], raw['price'],
                                 raw['trade_date'], raw.get('fees', 0))
        checked.update({'id':str(uuid4()), 'owner_hash':owner,
                        'created_utc':stamp.isoformat(timespec='microseconds')+f'-{i:05}'})
        prepared.append(checked)
    engine, portfolios, trades, _ = tables()
    with engine.begin() as con:
        if con.execute(select(portfolios.c.owner_hash).where(portfolios.c.owner_hash == owner)).first() is None:
            raise ValueError('Portfolio not found.')
        imports = portfolios.metadata.tables['iq_private_imports']
        if source_hash is not None:
            used = con.execute(select(imports.c.owner_hash).where(
                (imports.c.owner_hash == owner) & (imports.c.source_hash == source_hash))).first()
            if used:
                raise ValueError('This screenshot has already been imported into this portfolio. No duplicate trades were added.')
        _check_chronology(_read_trades(con, trades, owner) + prepared)
        if prepared:
            con.execute(insert(trades), prepared)
            if source_hash is not None:
                con.execute(insert(imports).values(owner_hash=owner,
                            source_hash=source_hash, created_utc=stamp.isoformat()))
            con.execute(update(portfolios).where(portfolios.c.owner_hash == owner)
                        .values(updated_utc=stamp.isoformat()))
    return len(prepared)


def delete_trade(code: str, trade_id: str) -> None:
    owner = owner_id(code)
    engine, portfolios, trades, _ = tables()
    with engine.begin() as con:
        prior = _read_trades(con, trades, owner)
        if not any(row['id'] == trade_id for row in prior):
            raise ValueError('Trade not found in this portfolio.')
        _check_chronology([row for row in prior if row['id'] != trade_id])
        con.execute(delete(trades).where((trades.c.owner_hash == owner) & (trades.c.id == trade_id)))
        con.execute(update(portfolios).where(portfolios.c.owner_hash == owner)
                    .values(updated_utc=datetime.now(timezone.utc).isoformat()))


def calculate_positions(trades: list[dict], latest_prices: dict[str,float|None],
                        initial_capital: float = 1_000_000.) -> dict:
    """Weighted-average purchase cost; realized gains include sell fees.

    Missing quotes produce UNKNOWN values, not zero-value securities. Portfolio
    total is unavailable unless all held symbols have a usable quote.
    """
    if not isfinite(float(initial_capital)) or initial_capital < 0:
        raise ValueError('Invalid starting virtual capital')
    book = {}
    cash = float(initial_capital)
    realized = 0.
    for row in sorted(trades, key=lambda x:(x['trade_date'], x.get('created_utc',''), x.get('id',''))):
        sym = row['ticker']
        qty = float(row['shares'])
        price = float(row['price'])
        fees = float(row.get('fees', 0.))
        state = book.setdefault(sym, {'shares':0., 'cost_basis':0., 'realized':0.})
        if row['side'] == 'BUY':
            cash -= qty * price + fees
            state['shares'] += qty
            state['cost_basis'] += qty * price + fees
        else:
            if qty > state['shares'] + 1e-8:
                raise ValueError(f'Trade ledger oversells {sym}')
            avg = state['cost_basis'] / state['shares'] if state['shares'] else 0.
            cost_removed = avg * qty
            gain = qty * price - fees - cost_removed
            state['realized'] += gain
            realized += gain
            cash += qty * price - fees
            state['shares'] -= qty
            state['cost_basis'] = max(0., state['cost_basis'] - cost_removed)
    holdings = []
    missing = []
    for sym in sorted(book):
        state = book[sym]
        if state['shares'] < 1e-8:
            continue
        raw = latest_prices.get(sym)
        quote = float(raw) if raw is not None else float('nan')
        valid = isfinite(quote) and quote > 0
        market_value = state['shares'] * quote if valid else None
        cost = state['cost_basis']
        holdings.append({
            'ticker':sym, 'shares':state['shares'], 'avg_buy_price':cost / state['shares'],
            'cost_basis':cost, 'last_price':quote if valid else None,
            'market_value':market_value,
            'unrealized_pnl':market_value-cost if valid else None,
            'unrealized_return':(market_value-cost)/cost if valid and cost>0 else None,
            'realized_pnl':state['realized'],
        })
        if not valid:
            missing.append(sym)
    equity = cash + sum(row['market_value'] for row in holdings) if not missing else None
    total_pnl = equity - float(initial_capital) if equity is not None else None
    for row in holdings:
        row['portfolio_weight'] = (row['market_value']/equity if equity and row['market_value'] is not None else None)
    return {'holdings':holdings, 'cash':cash, 'realized_pnl':realized,
            'equity':equity, 'total_pnl':total_pnl, 'missing_quotes':missing,
            'initial_capital':initial_capital}


def save_forecast(code: str, ticker: str, horizon: int, fields: dict) -> None:
    owner = owner_id(code)
    ticker = ticker.upper().strip()
    if not _SYMBOL.fullmatch(ticker) or not 1 <= int(horizon) <= 252:
        raise ValueError('Invalid ticker or prediction horizon')
    num = {}
    for name in ('forecast_excess','prob_gain','prob_boom','vol_20','model_price','review_level'):
        value = fields.get(name)
        num[name] = float(value) if value is not None and pd.notna(value) and isfinite(float(value)) else None
    if num['forecast_excess'] is None:
        raise ValueError('Forecast must contain a finite return estimate.')
    row = dict(owner_hash=owner,ticker=ticker,horizon=str(int(horizon)),
               asof=str(fields['asof'])[:10],updated_utc=datetime.now(timezone.utc).isoformat(),
               exit_review=str(fields.get('exit_review') or '')[:60],
               entry_watch=str(fields.get('entry_watch') or '')[:60],
               selected_model=str(fields.get('selected_model') or '')[:100],**num)
    engine, portfolios, _, forecasts = tables()
    with engine.begin() as con:
        if con.execute(select(portfolios.c.owner_hash).where(portfolios.c.owner_hash == owner)).first() is None:
            raise ValueError('Portfolio not found')
        match = ((forecasts.c.owner_hash == owner) & (forecasts.c.ticker == ticker) &
                 (forecasts.c.horizon == row['horizon']))
        if con.execute(select(forecasts.c.owner_hash).where(match)).first():
            con.execute(update(forecasts).where(match).values(**row))
        else:
            con.execute(insert(forecasts).values(**row))


def get_forecasts(code: str, horizon: int) -> dict[str,dict]:
    owner = owner_id(code)
    engine, _, _, forecasts = tables()
    with engine.connect() as con:
        rows = con.execute(select(forecasts).where((forecasts.c.owner_hash == owner) &
                                  (forecasts.c.horizon == str(int(horizon))))).mappings().all()
    return {r['ticker']:dict(r) for r in rows}


def export_trades_csv(trades: list[dict]) -> bytes:
    """CSV backup contains fill records but no access code or DB credential."""
    columns = ['trade_date','ticker','side','shares','price','fees']
    return pd.DataFrame([{c:r[c] for c in columns} for r in trades], columns=columns).to_csv(index=False).encode('utf-8')
