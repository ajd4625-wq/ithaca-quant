import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import pandas as pd
from ledger import connect, record, resolve, report, lifetime_report, wilson_95


def test_new_model_snapshot_retained_and_not_claimed_verified(tmp_path):
    c=connect(tmp_path/'v29.db')
    dates=pd.bdate_range('2026-11-02', periods=8)
    stock=pd.Series([100,101,102,103,104,105,106,107],index=dates)
    spy=pd.Series([100,100.1,100.2,100.3,100.4,100.5,100.6,100.7],index=dates)
    model_snapshot={'agents':[{'name':'Forecast','prediction':.012},
                              {'name':'Momentum','prediction':.01},
                              {'name':'Risk','prediction':.2}],
                    'validation':{'skill_gate_passed':True},
                    'data_source':'TEST_ONLY'}
    kwargs=dict(ticker='TEST',asof=dates[0].strftime('%Y-%m-%d'),label='ENTRY WATCH',
                direction='UP',strength=66,expected_excess_return=.02,
                entry_stock=100,entry_spy=100,research_metadata=model_snapshot)
    assert record(c,**kwargs)
    assert not record(c,**kwargs)
    stored=c.execute('SELECT model_version,research_metadata_json FROM forecasts').fetchone()
    assert stored['model_version']=='3.2.0-three-ml'
    assert 'TEST_ONLY' in stored['research_metadata_json']
    assert resolve(c,'TEST',stock[:5],spy[:5])==0
    assert resolve(c,'TEST',stock,spy)==1
    lifetime=lifetime_report(c)
    assert lifetime['graded']==1 and lifetime['independent_issue_dates']==1
    assert lifetime['evidence_state']=='insufficient_forward_market_evidence'
    assert wilson_95(1,1)[0]<100
    r=report(c,'2026-11-13')
    assert r['lifetime']['zero_baseline_mae_pct'] is not None
    assert r['week_wilson95_pct'] is not None
    c.close()
