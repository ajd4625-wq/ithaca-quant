"""Scheduled opt-in market-data increment; remote database needed in ephemeral CI.

Run: python scripts/refresh_job.py --tickers AAPL,MSFT,GOOGL --years 3
No transactions are placed, and no background daemon is launched.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ithaca_quant.data import parse_tickers
from ithaca_quant.incremental import refresh_market
from ithaca_quant.market_cache import save_snapshot
from ithaca_quant.provider_health import allow_request
from ithaca_quant.remote_store import health, remote_enabled


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', default=os.environ.get('ITHACA_REFRESH_TICKERS',''))
    parser.add_argument('--years',type=int,default=4)
    parser.add_argument('--max-tickers',type=int,default=75)
    args = parser.parse_args(argv)
    tickers = parse_tickers(args.tickers)[:max(1,min(args.max_tickers,150))]
    if len(tickers)<1:
        print('No watchlist set; skip without provider calls.')
        return 0
    if not remote_enabled():
        print('ITHACA_DATABASE_URL is unset; scheduled CI would not preserve results. Skipped.')
        return 0
    check = health()
    if not check['reachable']:
        print('Persistent database is unavailable; no provider requests made.')
        return 1
    if not allow_request('scheduled_market_refresh', 2, 20*60):
        print('Scheduled refresh already attempted recently; rate guard skips duplicate.')
        return 0
    try:
        market, status, asof, warnings = refresh_market(
            tickers, years=args.years, kind='deep', min_history=160,
            min_interval=20*60)
        if market.close.empty:
            raise ValueError('No valid market prices')
        save_snapshot('scheduled:latest', 'scheduler_metadata', {'tickers':tickers,
                      'status':status,'latest_price_day':str(market.close.index.max().date()),
                      'warnings':warnings[:10]})
        print(f'Refresh status={status} tickers={len(tickers)} rows={len(market.close)}')
        return 0
    except Exception as exc:
        print(f'Worker failed safely: {type(exc).__name__}')
        return 1

if __name__=='__main__':
    raise SystemExit(main())
