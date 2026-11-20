import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import pandas as pd
import numpy as np
from ithaca_quant.independent_audit import run_three_agent_pit_audit
from ithaca_quant.legacy_point_in_time import validate_pit_universe
from ithaca_quant.features import build_panel

def test_pit_audit_always_reports_validation_and_abstentions():
    rng=np.random.default_rng(17)
    dates=pd.bdate_range('2023-01-02',periods=640)
    market=rng.normal(.0004,.012,len(dates))
    prices=pd.DataFrame({'SPY':100*np.cumprod(1+market)},index=dates)
    for t in ('AONE','BTWO'):
        prices[t]=60*np.cumprod(1+market+rng.normal(0,.018,len(dates)))
    volume=pd.DataFrame(1000000,index=dates,columns=prices.columns)
    panel=build_panel(prices,volume,horizon=5)
    members=pd.DataFrame([dict(security_id=t,ticker=t,member_from='2023-01-02',member_to='',source_id='SYNTHETIC') for t in ('AONE','BTWO')])
    manifest=dict(membership_history_includes_delisted=True,
                 total_return_history_includes_delisting_returns=True,
                 historical_symbols_preserved=True,
                 provider='SYNTHETIC_UNIT_TEST',dataset_description='Synthetic test, NOT real evidence')
    u=validate_pit_universe(members,manifest)
    result=run_three_agent_pit_audit(panel,prices,u,max_periods=1,top_n=2)
    assert result.metrics['periods']==1
    assert result.metrics['point_in_time_universe_input']
    assert result.metrics['qualified_predictions']+result.metrics['abstained_predictions']==len(result.forecasts)
    assert set(result.forecasts['ticker']) == {'AONE','BTWO'}
