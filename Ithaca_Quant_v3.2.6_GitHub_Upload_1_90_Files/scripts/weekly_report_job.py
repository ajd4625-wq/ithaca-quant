"""Scheduled weekly forecast outcome reconciliation and report delivery.

Run via GitHub Actions Friday after 5 PM America/New_York.
Finalized daily bars are required before reconciling actual outcomes. Requires a durable DB.
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
        from ithaca_quant.incremental import completed_daily_only
        # Full tracked universe is required for an unbiased forward report. A
        # partial first-N refresh silently drops outcomes for later symbols.
        total_reconciled=0
        errors=[]
        for offset in range(0,len(tickers),120):
            group=tickers[offset:offset+120]
            try:
                md=download_market_data(group,years=2,min_history=50,batch_size=40)
                md=completed_daily_only(md)
                if md.close.empty:
                    raise ValueError('No completed daily price observations')
                total_reconciled+=reconcile_forecasts(md.close)
            except Exception as exc:
                errors.append(f'Batch {(offset//120)+1}: {type(exc).__name__}')
        print('Newly matured predictions: '+str(total_reconciled))
        if errors:
            print('Unreconciled ticker batches (outcomes remain pending): '+', '.join(errors))
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
