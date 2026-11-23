"""Offline PIT archive diagnostic: python scripts/audit_historical_archive.py path.zip"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from ithaca_quant.historical_archive import load_historical_archive

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive')
    args=p.parse_args()
    q=load_historical_archive(args.archive).quality
    print(json.dumps(q,indent=2))
    print('DECLARED SOURCE ONLY: independent provider authenticity and universe completeness NOT established.')
