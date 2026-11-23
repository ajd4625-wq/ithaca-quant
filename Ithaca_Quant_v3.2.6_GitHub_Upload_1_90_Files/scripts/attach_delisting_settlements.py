"""Attach privately licensed *event-level* delisting settlement evidence.

The input CSV must explicitly identify the return as incremental to the last
adjusted close, not already contained in historical prices (CRSP CIZ). The
script validates arithmetic, identities and documentation references; it does
NOT download licensed events or prove those references are authentic.

  python scripts/attach_delisting_settlements.py \\
      --archive private_vendor/history.zip \\
      --events private_vendor/settlements.csv \\
      --horizon 20 --output private_vendor/history_with_payoffs.zip
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ithaca_quant.terminal_settlement import attach_settlements


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--archive',type=Path,required=True)
    cli.add_argument('--events',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--horizon',type=int,required=True)
    args=cli.parse_args()
    print(json.dumps(attach_settlements(args.archive,args.events,args.output,args.horizon),indent=2))


if __name__=='__main__':
    main()
