"""Real historical market data acquisition for Ithaca Quant.

This downloads/uses *licensed* provider TICKERS, STOCKS, ACTIONS, and SPY FUNDS.
It never makes up discontinued securities or missing delisting settlements.

Fetch the official vendor tables (may be many GB; downloads are NOT public):
  export SHARADAR_API_KEY='your-key'           # DO NOT commit to git
  python scripts/acquire_historical_data.py download --private-dir ./private_vendor \
      --start 2020-01-01 --end 2025-12-31

Obtain SPY FUNDS CSV from the vendor and convert a research window:
  python scripts/acquire_historical_data.py build --private-dir ./private_vendor \
      --spy ./private_vendor/funds_SPY.csv --start 2024-01-01 --end 2025-12-31 \
      --output ./private_vendor/ithaca_vendor_2024_2025.zip \
      --source-reference 'Sharadar account export ID + date'

Securities and outcomes outside the licensed data remain unavailable, not
synthetically filled or represented as institutional-grade.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ithaca_quant.historical_vendor import (HistoricalVendorError,download_sharadar_table,
                                            build_from_sharadar_exports,download_spy_funds)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='command',required=True)
    dl=sub.add_parser('download',help='Download full Sharadar vendor datasets privately')
    dl.add_argument('--private-dir',type=Path,required=True)
    dl.add_argument('--start',required=True,help='First SPY benchmark session, YYYY-MM-DD')
    dl.add_argument('--end',required=True,help='Last SPY benchmark session, YYYY-MM-DD')
    build=sub.add_parser('build',help='Create audited point-in-time universe from downloaded vendor exports')
    build.add_argument('--private-dir',type=Path,required=True)
    build.add_argument('--spy',type=Path,help='Optional official SPY FUNDS export (defaults to private-dir/funds_SPY.csv)')
    build.add_argument('--start',required=True);build.add_argument('--end',required=True)
    build.add_argument('--output',type=Path,required=True)
    build.add_argument('--source-reference',required=True)
    build.add_argument('--min-delisted-issues',type=int,default=1)
    args=ap.parse_args(argv)
    if args.command=='download':
        key=os.getenv('SHARADAR_API_KEY')
        if not key: raise HistoricalVendorError('SHARADAR_API_KEY not found. Authenticated source access is required.')
        for table in ('tickers','stocks','actions'):
            report=download_sharadar_table(table,args.private_dir/f'{table}.csv.zip',api_key=key)
            print(json.dumps(report))
        print(json.dumps(download_spy_funds(args.private_dir/'funds_SPY.csv',
             api_key=key,start=args.start,end=args.end)))
    else:
        report=build_from_sharadar_exports(tickers_path=args.private_dir/'tickers.csv.zip',
             stocks_path=args.private_dir/'stocks.csv.zip',spy_path=(args.spy or args.private_dir/'funds_SPY.csv'),
             actions_path=args.private_dir/'actions.csv.zip' if (args.private_dir/'actions.csv.zip').exists() else None,
             start=args.start,end=args.end,output_path=args.output,
             min_delisted_issues=args.min_delisted_issues,source_reference=args.source_reference)
        print(json.dumps(report,indent=2,default=str))


if __name__=='__main__':
    try:main()
    except HistoricalVendorError as exc:
        print('Historical vendor data error: '+str(exc),file=sys.stderr)
        sys.exit(2)
