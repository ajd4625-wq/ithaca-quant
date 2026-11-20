import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import numpy as np
import pandas as pd
from server import score_indicators, build_signal
from ithaca_quant.config import MAX_AGENTS, MAX_RETRIES
from ithaca_quant.agents import AGENT_NAMES

def test_agent_limit_and_retry_bound():
    assert MAX_AGENTS==3 and MAX_RETRIES==2 and len(AGENT_NAMES)==3
    from ithaca_quant.retry import retry_call
    n={'value':0}
    def fail():n['value']+=1;raise RuntimeError('failed')
    import pytest
    with pytest.raises(RuntimeError):retry_call(fail,sleep=lambda v:None)
    assert n['value']==3

def test_scores_are_strength_not_probability():
    dates=pd.bdate_range('2025-01-01',periods=300)
    close=pd.Series(np.linspace(45,75,300)+np.sin(np.arange(300)/9),index=dates)
    spy=pd.Series(np.linspace(100,120,300),index=dates)
    vol=pd.Series([1000000]*300,index=dates)
    ind=score_indicators(close,spy,vol)
    assert 0<=ind['momentum_score']<=100
    assert 0<=ind['risk_score']<=100
    f={'state':'available','expected_excess_return':0.02,'model_disagreement':.01,
       'momentum_agent_expected_excess':.018,'risk_agent_downside_probability':.24,
       'validation_passed':True}
    sig=build_signal(ind,f)
    assert len(sig['agents'])==3
    assert sum(x['weight_pct'] for x in sig['agents'])==100
    assert sig['signal_strength'] is not None
    withheld=build_signal(ind,{**f,'validation_passed':False})
    assert withheld['direction_vs_spy'] is None and withheld['signal_strength'] is None
    none=build_signal(ind,{'state':'unavailable'})
    assert none['signal_strength'] is None
    assert none['direction_vs_spy'] is None
