"""Acquire FREE Yahoo price history + optional SEC point-in-time filing vintages.

Examples:
  python scripts/acquire_free_history.py --tickers AAPL,MSFT,GOOGL --years 12 \\
      --out .ithaca_free_history
  SEC_CONTACT_EMAIL=researcher@example.org python scripts/acquire_free_history.py \\
      --tickers AAPL,MSFT,GOOGL --years 12 --with-sec --out .ithaca_free_history

Output is a partial current-symbol universe, never a certified historical index
or a substitute for documented delisting returns. Run privately; do not commit
retrieved Yahoo data to a public GitHub repository.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ithaca_quant.free_history import build_free_bundle
from ithaca_quant.data import parse_tickers


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tickers', required=True,help='Comma-separated watchlist, not historical index members')
    p.add_argument('--out',type=Path,default=Path('.ithaca_free_history'))
    p.add_argument('--years',type=int,default=8)
    p.add_argument('--with-sec',action='store_true',help='Download official EDGAR companyfacts using SEC_CONTACT_EMAIL')
    p.add_argument('--require-all',action='store_true',help='Fail if Yahoo omits any requested stocks')
    a=p.parse_args(argv)
    symbols=parse_tickers(a.tickers)
    if not symbols:
        p.error('No valid stock tickers provided')
    contact=os.environ.get('SEC_CONTACT_EMAIL','').strip() if a.with_sec else None
    if a.with_sec and not contact:
        p.error('Set SEC_CONTACT_EMAIL to your genuine contact email for SEC fair access; do not use a fake identity')
    result=build_free_bundle(a.out,symbols,years=a.years,sec_contact=contact)
    print(json.dumps({k:v for k,v in result.items() if k not in {'sha256','sec_status'}},indent=2))
    print('Full coverage evidence and per-symbol SEC statuses:',a.out/'manifest.json')
    if a.require_all and result['missing_symbols']:
        print('ERROR: some Yahoo stocks are missing; no inference about their outcomes',file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':
    raise SystemExit(main())
