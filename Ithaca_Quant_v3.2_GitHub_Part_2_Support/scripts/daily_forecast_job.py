"""Daily forward prediction recording for a *configured* stock watchlist.

This is independent of Streamlit browser sessions; predictions are recorded
once by trading date/ticker/horizon in the shared SQL database. No trades.
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ithaca_quant.data import parse_tickers, download_market_data
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.incremental import completed_daily_only
from ithaca_quant.forecast_audit import log_forecasts, reconcile_forecasts
from ithaca_quant.remote_store import remote_enabled


def main():
    if not remote_enabled():
        print('Daily prediction logger disabled: persistent ITHACA_DATABASE_URL required.')
        return 0
    symbols=parse_tickers(os.getenv('ITHACA_REFRESH_TICKERS',''))[:60]
    if len(symbols)<5:
        print('Daily logger disabled: specify at least 5 names in ITHACA_REFRESH_TICKERS.')
        return 0
    if datetime.now(ZoneInfo('America/New_York')).weekday()>=5:
        return 0
    data=download_market_data(symbols,years=3,min_history=180,batch_size=40)
    data=completed_daily_only(data)
    if data.close.empty or 'SPY' not in data.close:
        print('No verified daily market data; do not invent predictions.')
        return 1
    asof=data.close.index.max()
    # A delayed/provider-missing bar must never generate a backfilled "forward"
    # forecast for yesterday or last week. A holiday run logs no predictions.
    if asof.date() != datetime.now(ZoneInfo('America/New_York')).date():
        print('Current completed session is unavailable; no stale predictions recorded.')
        return 1
    count=0
    for horizon in (5,20):
        try:
            panel=build_panel(data.close,data.volume,horizon=horizon)
            ranked=forecast_asof(panel,panel['date'].max(),fast=True,competitive_agents=True)
            count+=log_forecasts(ranked,panel['date'].max(),horizon,limit=60)
        except Exception as exc:
            print(f'{horizon}-session prediction generation unavailable: {type(exc).__name__}')
    mature=reconcile_forecasts(data.close)
    print(f'Immutable forecasts logged: {count}; previously recorded forecasts resolved: {mature}')
    return 0 if count or mature else 1

if __name__=='__main__':
    raise SystemExit(main())
