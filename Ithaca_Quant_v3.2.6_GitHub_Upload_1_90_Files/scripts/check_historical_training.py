"""Audit configured private historical training readiness without downloading data.

  python scripts/check_historical_training.py --archive ./private_vendor/archive.zip --horizons 5 20

Synthetic test fixtures and self-reported manifest provenance are not proof of
independently verified institutional market coverage.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ithaca_quant.production_history import load_private_production_archive
from ithaca_quant.features import build_panel
from ithaca_quant.backtest import _hydrate_terminal_labels
import pandas as pd
import numpy as np


def audit(path: Path, horizons: tuple[int,...] = (5,20)) -> dict:
    archive=load_private_production_archive(path)
    dates=pd.DatetimeIndex(archive.market.close['SPY'].dropna().index)
    report={'archive_sha256':archive.archive_sha256,
        'provider_declared':archive.quality['provider_declared'],
        'independent_vendor_authenticity_verified':False,
        'complete_universe_certified':False,
        'licensed_records_are_not_in_public_repository':True,
        'from':str(dates.min().date()),'through':str(dates.max().date()),
        'horizons':{}}
    for horizon in horizons:
        if horizon < 1 or len(dates)<horizon+100:
            report['horizons'][str(horizon)]={'ready':False,'reason':'Too little historical session coverage'}
            continue
        panel=build_panel(archive.market.close,archive.market.volume,horizon=horizon,
                          raw_close=archive.market.raw_close,
                          fundamentals=archive.fundamentals or None)
        panel=_hydrate_terminal_labels(panel,archive.terminal_returns,archive.market.close)
        maturity_cutoff=dates[-horizon-1]
        eligible=archive.membership.loc[archive.membership.eligible,['date','ticker']]
        mature=panel.loc[panel.date.le(maturity_cutoff),['date','ticker','target']]
        eligible_mature=mature.merge(eligible,on=['date','ticker'],how='inner',validate='one_to_one')
        missing=eligible_mature.loc[~np.isfinite(pd.to_numeric(eligible_mature.target,errors='coerce'))]
        report['horizons'][str(horizon)]={
            'ready_for_internal_consistency':bool(len(eligible_mature)>350 and missing.empty),
            'resolved_matured_labels':int(len(eligible_mature)-len(missing)),
            'unresolved_eligible_labels':int(len(missing)),
            'missing_examples':[{'security_id':r.ticker,'date':str(r.date.date())}
                                for r in missing.head(6).itertuples(index=False)],
            'terminal_event_records':int(len(archive.terminal_returns)) if archive.terminal_returns is not None else 0,
            'provenance_authenticated':False,
        }
    return report


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--archive',type=Path,required=True)
    cli.add_argument('--horizons',nargs='+',type=int,default=[5,20])
    args=cli.parse_args()
    print(json.dumps(audit(args.archive,tuple(args.horizons)),indent=2))


if __name__=='__main__':main()
