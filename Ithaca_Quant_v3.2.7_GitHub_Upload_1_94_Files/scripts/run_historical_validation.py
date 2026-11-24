"""Run full three-agent historical validation OUTSIDE Streamlit's web worker.

Example (free, survivor-only, UNVERIFIED historical universe):
  python scripts/run_historical_validation.py --tickers AAPL MSFT NVDA AMZN META JPM ... --out ./validation_results

Example (private point-in-time historical archive):
  python scripts/run_historical_validation.py --archive /private/historical.zip --out ./validation_results

Caution: A complete archive is necessary to claim that delistings/universe bias
were addressed. This tool does not authenticate the vendor or establish a live
forecasting advantage. Keep licensed inputs and exports private as required.
"""
from __future__ import annotations

import argparse
import math
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ithaca_quant.data import download_market_data
from ithaca_quant.features import build_panel
from ithaca_quant.historical_archive import load_historical_archive
from ithaca_quant.backtest import run_walk_forward


def _finite_json(value):
    """Produce portable strict JSON (unavailable measures become null)."""
    if isinstance(value, dict):
        return {str(k):_finite_json(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [_finite_json(v) for v in value]
    if isinstance(value, (float,int)):
        return value if (not isinstance(value,float) or math.isfinite(value)) else None
    if hasattr(value,'item'):
        return _finite_json(value.item())
    return value


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--archive', type=Path, help='Private point-in-time market archive ZIP')
    source.add_argument('--tickers', nargs='+', help='Free Yahoo history (survivor-biased)')
    parser.add_argument('--years', type=int, default=6)
    parser.add_argument('--horizon', type=int, default=20)
    parser.add_argument('--periods', type=int, default=12)
    parser.add_argument('--top-n', type=int, default=6)
    parser.add_argument('--cost-bps', type=float, default=10)
    parser.add_argument('--out', type=Path, default=Path('validation_results'))
    args=parser.parse_args(argv)
    if args.archive:
        archive=load_historical_archive(args.archive.read_bytes())
        market=archive.market
        fundamental_history=archive.fundamentals or None
        membership=archive.membership
        terminal_returns=archive.terminal_returns
        strict=True
    else:
        print('WARNING: CURRENT-SYMBOL UNIVERSE. Survivorship bias and missing delisting returns remain.')
        market=download_market_data(args.tickers, years=args.years, min_history=300)
        fundamental_history=None
        membership=None
        terminal_returns=None
        strict=False
    panel=build_panel(market.close,market.volume,args.horizon,
                      fundamentals=fundamental_history, raw_close=market.raw_close)
    result=run_walk_forward(panel,market.close,horizon=args.horizon,top_n=args.top_n,
                 max_periods=args.periods,cost_bps=args.cost_bps,fast=True,
                 historical_membership=membership,require_point_in_time=strict,
                 terminal_returns=terminal_returns,competitive_agents=True)
    args.out.mkdir(parents=True,exist_ok=True)
    result.periods.to_csv(args.out/'walk_forward_periods.csv',index=False)
    result.predictions.to_csv(args.out/'walk_forward_predictions.csv',index=False)
    (args.out/'walk_forward_metrics.json').write_text(json.dumps(
             _finite_json({'metrics':result.metrics,'evidence':result.evidence}),
             indent=2,default=str,allow_nan=False))
    print('Saved evaluation outputs to',args.out)
    print('Evidence status:',result.metrics.get('backtest_evidence_status'))
    print('Test windows:',len(result.periods),'scored outcomes:',len(result.predictions))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
