"""Scheduled weekly forecast outcome reconciliation and report delivery.

Run via GitHub Actions Friday 4 PM America/New_York. Requires a durable DB.
Optional SMTP variables send the generated report; otherwise the saved in-app
report remains accessible. Not a real-time alert or brokerage integration.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ithaca_quant.forecast_audit import read_forecasts, reconcile_forecasts
from ithaca_quant.weekly_reports import make_weekly_report, render_report, send_weekly_email, EASTERN
from ithaca_quant.remote_store import remote_enabled

def main():
    local=datetime.now(timezone.utc).astimezone(EASTERN)
    forced='--force' in sys.argv
    if not forced and local.weekday()!=4:
        print('Not Friday in New York: no report sent.')
        return 0
    if not remote_enabled():
        print('No durable ITHACA_DATABASE_URL; weekly report job disabled to avoid empty/misleading reports.')
        return 0
    records=read_forecasts()
    tickers=sorted(set(records['ticker'].dropna().astype(str)))
    if tickers:
        from ithaca_quant.data import download_market_data
        # Use sufficient lookback to reach 60-session decisions (up to two years).
        from ithaca_quant.config import BENCHMARK
        if len(tickers)>150:
            print('Too many tracked tickers for one worker; only the first 150 are refreshed. Remaining outcomes stay pending.')
        md=download_market_data(tickers[:150], years=2, min_history=50, batch_size=40)
        reconciled=reconcile_forecasts(md.close)
        print('Newly matured predictions: '+str(reconciled))
    report=make_weekly_report()
    print(render_report(report))
    try:
        if send_weekly_email(report):
            print('Weekly email dispatched.')
        else:
            print('SMTP not configured; report saved to database for the dashboard.')
    except Exception as exc:
        print(f'Email could not be delivered: {type(exc).__name__}; stored report remains available.')
        return 1
    return 0
if __name__=='__main__':
    raise SystemExit(main())
