"""v3.0 regression tests: strictly synthetic fixtures, not live-market evidence."""
import sqlite3
from datetime import timezone
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import demo_market_data,download_market_data
from ithaca_quant.features import build_panel
from ithaca_quant.insider_archive import archived_form4_features
from ithaca_quant.search import price_scenarios
from ithaca_quant.model_tournament import _bh_adjust,run_model_tournament
from ithaca_quant.forecast_audit import (log_forecasts,read_forecasts,
       forward_model_comparison_report)
from ithaca_quant.backtest import run_walk_forward


def _example_market():
    market=demo_market_data(['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH'],sessions=540,seed=28)
    return market,build_panel(market.close,market.volume,horizon=10)


def test_bh_correction_blocks_lucky_stock_among_many_tests():
    p=np.array([.04]+[.5]*99)
    q=_bh_adjust(p)
    assert q[0]>.05
    assert q.min()>.05
    assert _bh_adjust([.001,.001, .9]).max()<=1


def test_historical_tournament_minimum_and_uncertainty_provenance():
    market,p=_example_market()
    r=run_model_tournament(p,p.date.max(),horizon=10,fast=True)
    assert r.qualified_tickers==0  # insufficient 20 independent windows per block
    assert r.predictions.agent_picked_on_historical_evidence.eq(False).all()
    assert r.predictions.agent_vote_spread.notna().all()
    assert r.predictions.agent_prob_gain.isna().all()


def test_missing_vendor_volume_is_not_a_real_zero(monkeypatch):
    import sys
    from types import SimpleNamespace
    dates=pd.bdate_range('2026-01-05',periods=175,tz='UTC')
    def fake(tickers,**kw):
        raw={}
        for t in tickers:
            raw[(t,'Close')]=np.linspace(100,120,len(dates))
            v=np.full(len(dates),1e6)
            v[80]=np.nan
            raw[(t,'Volume')]=v
        return pd.DataFrame(raw,index=dates)
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(download=fake))
    m=download_market_data(['AAA'],min_history=120)
    assert np.isnan(m.volume.loc[m.volume.index[80],'AAA'])
    assert m.close.AAA.notna().all()
    p=build_panel(m.close,m.volume,horizon=5)
    assert not ((p.ticker=='AAA')&(p.date==m.volume.index[80])).any()


def test_form4_only_enters_after_public_filing():
    ix=pd.bdate_range('2026-11-09',periods=8)
    rows=[dict(filed_date='2026-11-11',trade_date='2026-11-10',
               type='Purchase',value_usd=10000)]
    f=archived_form4_features(rows,ix)
    assert f.loc['2026-11-11','insider_buy_count_30d']==0
    assert f.loc['2026-11-12','insider_buy_count_30d']==1
    assert f.loc['2026-11-12','insider_net_buy_log_30d']>0
    with pytest.raises(ValueError,match='future-dated'):
        archived_form4_features([dict(filed_date='2026-11-09',trade_date='2026-11-12',
                                        type='Sale',value_usd=100)],ix)


def test_spy_scenario_not_implicitly_zero():
    spy=pd.Series(np.geomspace(100,180,301))
    s=price_scenarios(100,.08,spy,.22,20)
    assert s['benchmark_scenario_return']>0
    assert s['target']>108
    assert not s['absolute_price_forecast_verified']


def test_missing_end_price_for_entered_selected_stock_must_raise(monkeypatch):
    market,p=_example_market()
    import ithaca_quant.backtest as b
    monkeypatch.setattr(b,'forecast_asof',lambda panel,asof,**kwargs:
          pd.DataFrame({'ticker':list('ABCDEFGH'),
                        'forecast_excess':np.arange(8,0,-1)*.01,
                        'prob_gain':np.full(8,.5),'prob_boom':np.full(8,.1),
                        'selected_model':['Existing ensemble']*8}).assign(
                        ticker=['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH']))
    missing=market.close.copy()
    missing.loc[missing.index[-1],'AAA']=np.nan
    with pytest.raises(ValueError,match='Missing terminal return for selected holding AAA'):
        run_walk_forward(p,missing,horizon=10,top_n=5,max_periods=1,fast=True)
    archive=pd.DataFrame([{'signal_date':missing.index[-11],'ticker':'AAA',
             'asof_total_return':-1.,'entry_total_return':-1.,'source':'historical_archive'}])
    result=run_walk_forward(p,missing,horizon=10,top_n=5,max_periods=1,fast=True,
                           terminal_returns=archive)
    assert result.metrics['portfolio_failed_fills']==0
    assert result.predictions.loc[result.predictions.ticker=='AAA','realized_return'].iloc[0]==-1
    assert result.metrics['portfolio_return']<0


def test_forecast_selection_does_not_rely_on_forward_label_availability(monkeypatch):
    market,p=_example_market()
    signal=market.close.index[-11]
    p.loc[p.date.eq(signal)&p.ticker.eq('AAA'),'forward_return']=np.nan
    import ithaca_quant.backtest as b
    def fake(panel,asof,**kwargs):
        return pd.DataFrame({'ticker':['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH'],
          'forecast_excess':[.2,.1,.09,.08,.07,.06,.05,.04],
          'prob_gain':[.5]*8,'prob_boom':[.1]*8,'selected_model':['Ridge']*8})
    monkeypatch.setattr(b,'forecast_asof',fake)
    result=run_walk_forward(p,market.close,horizon=10,top_n=5,max_periods=1,fast=True)
    assert 'AAA' in result.periods.top_stocks.iloc[0]
    assert 'AAA' in result.predictions.ticker.tolist()
    assert result.metrics['competition_replayed']


def test_live_edge_report_requires_forward_matured_paired_data(tmp_path):
    db=tmp_path/'pred.sqlite'
    rows=pd.DataFrame({'ticker':['AAA'],'forecast_excess':[.08],
                       'incumbent_forecast_excess':[.01],'selected_model':['Ridge']})
    assert log_forecasts(rows,'2026-11-11',10,path=db)==1
    initial=read_forecasts(db)
    assert initial.iloc[0].baseline_forecast==pytest.approx(.01)
    assert forward_model_comparison_report(db)['verified_advantage'] is False
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE predictions SET observed=.09, evidence_status='timestamp_eligible'")
    report=forward_model_comparison_report(db)
    assert report['paired_forecasts']==1
    assert report['independent_windows']==1
    assert report['verified_advantage'] is False
    assert 'INSUFFICIENT' in report['status']
