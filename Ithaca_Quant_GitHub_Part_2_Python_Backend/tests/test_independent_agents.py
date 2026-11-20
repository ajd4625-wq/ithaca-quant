import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import numpy as np
import pandas as pd
from ithaca_quant.features import build_panel
from ithaca_quant.independent_agents import forecast_three_agents, AGENTS


def sample(seed=21, n=730):
    rng=np.random.default_rng(seed)
    dates=pd.bdate_range('2022-01-03', periods=n)
    # Synthetic returns: tests only data flow; they are NOT market evidence.
    bm=rng.normal(.0003,.011,n)
    conditional=rng.normal(.0003,.022,n)
    # Induce some mean reversion so risk events have both classes.
    conditional[1:]+= -.12*conditional[:-1]
    prices=pd.DataFrame({'SPY':100*np.cumprod(1+bm),
                         'TEST':48*np.cumprod(1+bm+conditional)},index=dates)
    volume=pd.DataFrame({'SPY':1_000_000,'TEST':1_200_000},index=dates)
    return build_panel(prices,volume,horizon=5)


def test_three_are_fitted_models_not_formulas():
    data=sample()
    asof=data.loc[data.ticker=='TEST','date'].max()
    r=forecast_three_agents(data, asof, 'TEST')
    assert len(r['agents'])==3
    assert [x['name'] for x in r['agents']]==list(AGENTS)
    assert len(set(x['algorithm'] for x in r['agents']))==3
    assert r['validation']['purged'] is True
    assert r['validation']['fit_end'] < r['validation']['holdout_start']
    assert r['validation']['validation_end'] < str(pd.Timestamp(asof).date())
    assert r['validation']['independent_anchors']>=10
    assert -0.25 <= r['expected_excess_return'] <= .25
    assert 0<=r['risk_agent_downside_probability']<=1


def test_changing_latest_unrealized_target_never_changes_forecast():
    data=sample(seed=7)
    asof=data.loc[data.ticker=='TEST','date'].max()
    first=forecast_three_agents(data, asof, 'TEST')
    changed=data.copy()
    # Simulates someone injecting future knowledge into the outcome column
    changed.loc[(changed.ticker=='TEST')&(changed.date>=asof),'target']=99999
    changed.loc[(changed.ticker=='TEST')&(changed.date>=asof),'label_end']=asof+pd.Timedelta(days=20)
    after=forecast_three_agents(changed,asof,'TEST')
    assert first['expected_excess_return']==after['expected_excess_return']
    assert first['risk_agent_downside_probability']==after['risk_agent_downside_probability']
