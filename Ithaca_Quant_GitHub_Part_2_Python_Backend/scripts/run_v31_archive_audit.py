#!/usr/bin/env python3
"""Local, source-declared v3.1 archive evaluation of the three fitted Chrome learners.

Never inserts retrospective rows in the forward accuracy ledger.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'))
from ithaca_quant.historical_archive import load_historical_archive
from ithaca_quant.historical_research import run_three_agent_archive_audit

if __name__ == '__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('archive', help='Verified-format v3.1 vendor market-data ZIP; NOT app source ZIP')
    a.add_argument('--windows',type=int,default=2)
    a.add_argument('--max-members',type=int,default=35,help='Reject larger universes rather than silently excluding members; increase explicitly for offline batch')
    a.add_argument('--output',default=str(ROOT/'reports'/'v31_pit_audit'))
    args=a.parse_args()
    bundle=load_historical_archive(args.archive)
    result=run_three_agent_archive_audit(bundle,windows=args.windows,max_member_count=args.max_members)
    p=Path(args.output);p.parent.mkdir(parents=True,exist_ok=True)
    Path(str(p)+'_summary.json').write_text(json.dumps(result.summary,indent=2,default=str),encoding='utf-8')
    result.forecasts.to_csv(str(p)+'_predictions.csv',index=False)
    print(json.dumps(result.summary,indent=2,default=str))
