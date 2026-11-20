import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import pytest
import pandas as pd
from ithaca_quant.legacy_point_in_time import validate_pit_universe, apply_membership
from ithaca_quant.backtest import run_walk_forward

PROVENANCE={
 'membership_history_includes_delisted':True,
 'total_return_history_includes_delisting_returns':True,
 'historical_symbols_preserved':True,
 'provider':'FICTITIOUS_SOURCE_FOR_UNIT_TEST_ONLY',
 'dataset_description':'Synthetic PIT acceptance test, NOT real historical evidence'
}

def membership():
 return pd.DataFrame([
    dict(security_id='0001',ticker='ALIVE',member_from='2024-01-01',member_to='',source_id='test'),
    dict(security_id='0002',ticker='DELIST',member_from='2024-01-01',member_to='2024-01-09',source_id='test'),
 ])

def test_membership_drops_delisted_after_effective_date_only():
 u=validate_pit_universe(membership(),PROVENANCE)
 dates=pd.date_range('2024-01-02',periods=8,freq='D')
 panel=pd.DataFrame([{'date':d,'ticker':t,'target':.01} for d in dates for t in ['ALIVE','DELIST']])
 filtered=apply_membership(panel,u)
 assert ('DELIST' in set(filtered.loc[filtered.date==pd.Timestamp('2024-01-08'),'ticker']))
 assert ('DELIST' not in set(filtered.loc[filtered.date==pd.Timestamp('2024-01-09'),'ticker']))

def test_incomplete_old_universe_cannot_falsely_validate():
 u=validate_pit_universe(membership(),PROVENANCE)
 dates=pd.date_range('2024-01-02',periods=8,freq='D')
 panel=pd.DataFrame([{'date':d,'ticker':'ALIVE'} for d in dates])
 with pytest.raises(ValueError,match='incomplete'):
  apply_membership(panel,u)

def test_backtest_blocks_current_only_stock_universe():
 with pytest.raises((ValueError,KeyError)):
  run_walk_forward(pd.DataFrame(),pd.DataFrame({'SPY':[]}),max_periods=2,require_point_in_time=True)

def test_missing_provenance_and_reused_tickers_rejected():
 with pytest.raises(ValueError,match='requires independently sourced'):
  validate_pit_universe(membership(),{})
 reused=pd.concat([membership(),pd.DataFrame([{
    'security_id':'0003','ticker':'ALIVE','member_from':'2025-01-01',
    'member_to':'','source_id':'test'}])],ignore_index=True)
 with pytest.raises(ValueError,match='reused'):
  validate_pit_universe(reused,PROVENANCE)
