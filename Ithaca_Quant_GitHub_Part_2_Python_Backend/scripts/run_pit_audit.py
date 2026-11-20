#!/usr/bin/env python3
"""Local point-in-time research audit: NO preset survivor list or synthetic results."""
import argparse, sys, json, hashlib
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from ithaca_quant.legacy_point_in_time import load_pit_universe
from ithaca_quant.features import build_panel
from ithaca_quant.independent_audit import run_three_agent_pit_audit

parser=argparse.ArgumentParser(description='Three-ML model PIT backtest; fails closed without complete historical source files')
parser.add_argument('--prices',required=True,help='CSV: date,ticker,total_return_index,volume; includes delisted names, delisting settlement and SPY')
parser.add_argument('--membership',required=True,help='CSV: security_id,ticker,member_from,member_to,source_id')
parser.add_argument('--provenance',required=True,help='JSON source manifest with verified delisting coverage attestations')
parser.add_argument('--output',default='reports/pit_audit')
parser.add_argument('--periods',type=int,default=10)
args=parser.parse_args()

u=load_pit_universe(args.membership,args.provenance)
raw=pd.read_csv(args.prices,parse_dates=['date'])
required={'date','ticker','total_return_index','volume'}
if not required<=set(raw.columns):parser.error('Price CSV missing '+str(required-set(raw.columns)))
if raw.duplicated(['date','ticker']).any():parser.error('Duplicate date/ticker in price CSV')
close=raw.pivot(index='date',columns='ticker',values='total_return_index').sort_index()
volume=raw.pivot(index='date',columns='ticker',values='volume').reindex(close.index)
if 'SPY' not in close:parser.error('SPY is required as the historical benchmark')
panel=build_panel(close,volume,horizon=5)
r=run_three_agent_pit_audit(panel,close,u,max_periods=args.periods)
dest=Path(args.output);dest.parent.mkdir(parents=True,exist_ok=True)
r.forecasts.to_csv(str(dest)+'_predictions.csv',index=False)
r.windows.to_csv(str(dest)+'_windows.csv',index=False)
manifest={'metrics':r.metrics,'source_provenance':u.price_provenance,
          'source_sha256':{str(f):hashlib.sha256(Path(f).read_bytes()).hexdigest() for f in (args.prices,args.membership,args.provenance)},
          'note':'Input attestations are NOT independently verified by this script. Historical results do not certify live forecasting accuracy.'}
Path(str(dest)+'_audit.json').write_text(json.dumps(manifest,indent=2,default=str))
print(json.dumps(manifest['metrics'],indent=2))
