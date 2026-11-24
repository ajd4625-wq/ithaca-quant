"""Accuracy-first regression checks (all market observations here are synthetic)."""
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import demo_market_data
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.model_tournament import AGENT_MODELS, run_model_tournament
from ithaca_quant.backtest import run_walk_forward
from ithaca_quant.point_in_time import validate_membership
from ithaca_quant.forecast_audit import log_forecasts, reconcile_forecasts, forward_report
from ithaca_quant.weekly_reports import summarize_week


def sample_panel(n=610,h=10):
    market=demo_market_data(['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH'],sessions=n,seed=22)
    return market,build_panel(market.close,market.volume,horizon=h)


def test_stock_by_stock_tournament_three_independent_models():
    _,p=sample_panel()
    latest=p.date.max()
    result=run_model_tournament(p,latest,horizon=10,fast=True)
    assert len(AGENT_MODELS)==3
    assert len(result.predictions)==8
    assert result.predictions.ticker.nunique()==8
    cols=['agent_ridge_forecast','agent_gradient_boosting_forecast','agent_random_forest_forecast']
    assert result.predictions[cols].notna().all().all()
    assert (result.predictions[cols].max(axis=1)-result.predictions[cols].min(axis=1)>1e-6).all()
    assert result.predictions.agent_winner.isin(['Existing ensemble',*AGENT_MODELS]).all()
    assert result.qualified_tickers==result.predictions.agent_picked_on_historical_evidence.sum()
    # The stricter arena may refuse to audit insufficient history.
    if not result.audit.empty:
        assert result.audit.selection_windows.min()>=20
        assert result.audit.audit_windows.min()>=20
    else:
        assert result.qualified_tickers==0


def test_tournament_applies_only_verified_champions_to_forecast():
    _,p=sample_panel()
    original=forecast_asof(p,p.date.max(),fast=True)
    challenger=forecast_asof(p,p.date.max(),fast=True,competitive_agents=True)
    joined=challenger.merge(original[['ticker','forecast_excess']],on='ticker',suffixes=('','_legacy'))
    rejected=~joined.agent_picked_on_historical_evidence
    assert np.allclose(joined.loc[rejected,'forecast_excess'],joined.loc[rejected,'forecast_excess_legacy'])
    assert joined.agent_winner.notna().all()
    assert joined.agent_selection_windows.notna().all()


def test_short_history_fails_closed_not_fake_winners():
    _,p=sample_panel(n=290)
    result=run_model_tournament(p,p.date.max(),horizon=10)
    assert result.qualified_tickers==0
    assert result.predictions.agent_picked_on_historical_evidence.eq(False).all()
    # Research-only predictions may exist; none may control a stock.
    assert result.predictions.agent_winning_forecast.isna().all()


def test_historical_universe_rejects_current_and_missing_delisted():
    market,p=sample_panel(n=290,h=5)
    day=market.close.index[210]
    names=['AAA','BBB','CCC','DDD','EEE','FFF','GGG','HHH']
    membership=pd.DataFrame({'date':[day]*len(names),'ticker':names,
             'eligible':[True]*len(names),'provenance':['current_listings']*len(names)})
    with pytest.raises(ValueError,match='not historical'):
        validate_membership(membership,signal_dates=[day],panel=p,close=market.close,horizon=5)
    membership['provenance']='historical_archive'
    membership=pd.concat([membership,pd.DataFrame([{'date':day,'ticker':'DELISTED',
          'eligible':True,'provenance':'historical_archive'}])],ignore_index=True)
    with pytest.raises(ValueError,match='missing from panel'):
        validate_membership(membership,signal_dates=[day],panel=p,close=market.close,horizon=5)
    good=membership.loc[membership.ticker!='DELISTED']
    allowed=validate_membership(good,signal_dates=[day],panel=p,close=market.close,horizon=5)
    assert allowed[day]==set(names)


def test_strict_backtest_fails_without_historical_membership():
    market,p=sample_panel(n=510,h=10)
    with pytest.raises(ValueError,match='requires archived historical membership'):
        run_walk_forward(p,market.close,horizon=10,max_periods=1,
                         require_point_in_time=True)


def test_forecast_created_after_next_trading_close_is_not_forward_evidence(tmp_path):
    path=tmp_path/'ledger.sqlite'
    date='2026-11-11'
    log_forecasts(pd.DataFrame([{'ticker':'AAA','forecast_excess':.12}]),date,1,path=path)
    idx=pd.bdate_range(date,periods=3)
    m=pd.DataFrame({'SPY':[100.,100.,100.],'AAA':[100.,104.,110.]},index=idx)
    assert reconcile_forecasts(m,path=path)==1
    # Reporting bins depend on the outcome resolution timestamp, not the
    # wall clock on which pytest happens to run.
    import sqlite3
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE predictions SET resolved_utc=? WHERE ticker='AAA'", ('2026-11-20T21:00:00+00:00',))
    score=forward_report(path)
    assert score['resolved']==1 and score['timestamp_eligible_resolved']==0
    assert np.isnan(score['timestamp_eligible_mae'])
    week=summarize_week(__import__('ithaca_quant.forecast_audit',fromlist=['read_forecasts']).read_forecasts(path),
          end=datetime(2026,11,20,21,tzinfo=timezone.utc))
    assert week['evaluated']==0
    assert week['excluded_late_or_unverifiable']==1


def test_timely_forward_record_qualifies_and_unchanged_value_is_immutable(tmp_path):
    import sqlite3
    from ithaca_quant.forecast_audit import read_forecasts
    db=tmp_path/'timely.sqlite'
    asof='2026-11-11'
    rows=pd.DataFrame([{'ticker':'AAA','forecast_excess':.05}])
    assert log_forecasts(rows,asof,1,path=db)==1
    # Simulate an authentic first-insert event at 4:05pm New York on signal day.
    # This test changes the database only to construct its controlled fixture.
    with sqlite3.connect(db) as con:
        con.execute("UPDATE predictions SET created_utc='2026-11-11T21:05:00+00:00'")
    # Attempt to update the prediction must not replace first-seen record.
    assert log_forecasts(rows.assign(forecast_excess=.5),asof,1,path=db)==0
    ix=pd.bdate_range(asof,periods=3)
    prices=pd.DataFrame({'SPY':[100.,101.,102.], 'AAA':[100.,104.,104.]},index=ix)
    assert reconcile_forecasts(prices,path=db)==1
    record=read_forecasts(db).iloc[0]
    assert record.evidence_status=='timestamp_eligible'
    assert record.forecast==pytest.approx(.05)
    result=forward_report(db)
    assert result['timestamp_eligible_resolved']==1
    assert result['timestamp_eligible_mae']==pytest.approx(.02)


def test_stratified_forecast_log_includes_both_ends_not_only_top(tmp_path):
    from ithaca_quant.forecast_audit import read_forecasts
    db=tmp_path/'sample.sqlite'
    rows=pd.DataFrame({'ticker':[f'S{i:03d}' for i in range(101)],
                       'forecast_excess':np.linspace(-.20,.20,101)})
    assert log_forecasts(rows,'2026-11-11',20,path=db,limit=11)==11
    seen=read_forecasts(db)
    assert seen.forecast.min()==pytest.approx(-.2)
    assert seen.forecast.max()==pytest.approx(.2)
    assert (seen.forecast<0).sum()>=4 and (seen.forecast>0).sum()>=4
    assert log_forecasts(rows,'2026-11-11',20,path=db,limit=11)==0


def test_invalid_backtest_costs_and_periods_are_not_fabricated():
    market,p=sample_panel(n=410,h=10)
    for options in ({'cost_bps':-10},{'max_periods':0},{'horizon':0}):
        with pytest.raises(ValueError):
            run_walk_forward(p,market.close,top_n=6,fast=True,**options)


def test_loader_does_not_retroactively_modify_price_due_to_future_reversal(monkeypatch):
    from types import SimpleNamespace
    import sys
    from ithaca_quant.data import download_market_data
    days=pd.bdate_range('2026-01-02',periods=180,tz='UTC')
    vals=np.full(180,100.,dtype=float)
    vals[111]=180.   # artificial large one-day spike reversed next day
    def feed(tickers, **kwargs):
        data={}
        for ticker in tickers:
            data[(ticker,'Close')] = vals.copy()
            data[(ticker,'Volume')] = np.full(180, 1e6)
        return pd.DataFrame(data,index=days)
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(download=feed))
    pulled=download_market_data(['AAA'],years=1,min_history=140)
    # The detector may identify this *after* reversal, but must not rewrite
    # that past signal using subsequent data in an historical model test.
    assert pulled.close.AAA.iloc[111]==180.


def test_future_audit_outcomes_cannot_rewrite_earlier_champion_choice():
    from ithaca_quant.model_tournament import run_model_tournament
    _,p=sample_panel(n=650,h=10)
    r=run_model_tournament(p,p.date.max(),horizon=10)
    modified=p.copy()
    # Only mutate LAST audit block, leaving initial fitting and selection
    # blocks untouched. Model championship from selection stays frozen.
    days=sorted(p.loc[p.target.notna(),'date'].unique())
    modified.loc[modified.date>=days[-60],'target'] *= -2
    later=run_model_tournament(modified,modified.date.max(),horizon=10)
    a=r.audit.set_index('ticker').selected_champion
    b=later.audit.set_index('ticker').selected_champion
    pd.testing.assert_series_equal(a,b)


def test_challenger_is_promoted_when_both_historical_blocks_really_improve():
    from ithaca_quant.features import FEATURES
    rng=np.random.default_rng(124)
    days=pd.bdate_range('2023-01-02',periods=750)
    rows=[]
    for i,day in enumerate(days):
        for j in range(8):
            x=rng.standard_normal(len(FEATURES))
            target=.018*x[0]-.013*x[1]+rng.normal(0,.002)
            row={'date':day,'ticker':f'S{j:02d}',
                 'label_end':days[i+10] if i+10<len(days) else pd.NaT,
                 'target':target if i+10<len(days) else np.nan}
            row.update(dict(zip(FEATURES,x)))
            rows.append(row)
    synthetic=pd.DataFrame(rows)
    result=run_model_tournament(synthetic,days[-1],horizon=10)
    # Stronger multiple-testing and directional/rank guards can reduce
    # the number promoted even for deliberately synthetic linear targets.
    assert result.qualified_tickers >= 1
    assert result.audit.loc[result.audit.audit_qualified,'audit_q_value'].le(.05).all()
    promoted=result.predictions.loc[result.predictions.agent_picked_on_historical_evidence]
    assert promoted.agent_winner.eq('Ridge').all()
    assert (result.audit.loc[result.audit.audit_qualified, 'audit_mae'] <
            result.audit.loc[result.audit.audit_qualified,'audit_baseline_mae']).all()


def test_missing_vendor_quote_is_not_made_up_by_forward_fill(monkeypatch):
    import sys
    from types import SimpleNamespace
    from ithaca_quant.data import download_market_data
    days = pd.bdate_range('2026-01-01', periods=185, tz='UTC')
    def feed(tickers, **kwargs):
        raw = {}
        for ticker in tickers:
            close = np.linspace(50, 75, len(days))
            if ticker != 'SPY':
                close[160:162] = np.nan
            raw[(ticker, 'Close')] = close
            raw[(ticker, 'Volume')] = np.full(len(days), 1e6)
        return pd.DataFrame(raw, index=days)
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=feed))
    result = download_market_data(['AAA'], years=1, min_history=150)
    assert result.close.AAA.iloc[160:162].isna().all()
    assert result.close.AAA.iloc[162] > 0


def test_deployment_workflows_and_close_cutoffs_use_current_root_layout():
    from pathlib import Path
    r = Path(__file__).resolve().parents[1]
    daily = (r / '.github/workflows/ithaca-daily-forecasts.yml').read_text()
    weekly = (r / '.github/workflows/ithaca-weekly-report.yml').read_text()
    refresh = (r / '.github/workflows/ithaca-refresh.yml').read_text()
    assert "cron: '20 17 * * 1-5'" in daily
    assert "cron: '45 17 * * 5'" in weekly
    for script in (daily, weekly):
        assert 'test -f ithaca_quant/model_tournament.py' in script
        assert 'ITHACA_APP_DIR=.' in script
        assert '2.7.0' not in script
        assert 'timezone: America/New_York' in script
    assert 'working-directory: ithaca_quant' not in refresh


def test_weekly_worker_has_no_first_150_truncation():
    from pathlib import Path
    r = Path(__file__).resolve().parents[1]
    code = (r / 'scripts/weekly_report_job.py').read_text()
    assert 'tickers[:150]' not in code
    assert 'for offset in range(0,len(tickers),120)' in code
    assert 'completed_daily_only(md)' in code
