"""v2 accuracy, point-in-time, persistence, risk and release integration tests."""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import demo_market_data
from ithaca_quant.features import build_panel, REGIME_FEATURES
from ithaca_quant.research_lab import (purged_split, finite_interval, market_regime,
                                       fit_validated_forecaster)
from ithaca_quant.earnings_expectations import validated_expectations, expectations_features
from ithaca_quant.news_events import event_flags, headline_event_counts
from ithaca_quant.forecast_audit import log_forecasts, reconcile_forecasts, forward_report, read_forecasts
from ithaca_quant.portfolio_stress import stress_summary
from ithaca_quant.provider_health import allow_request
from ithaca_quant import remote_store
from ithaca_quant.market_cache import save_snapshot, load_snapshot
from ithaca_quant.macro import fred_vintage


def test_purged_split_prevents_label_horizon_overlap():
    days = pd.bdate_range('2025-01-01', periods=160)
    table = pd.DataFrame({'date':days, 'label_end':pd.Series(days).shift(-20),
                          'ticker':'AAPL','target':1.0})
    before, after = purged_split(table, days[100], days[115])
    assert (before.label_end < days[100]).all()
    assert (after.date >= days[100]).all()
    assert (after.date < days[115]).all()


def test_uncertainty_hides_when_sparse_and_gives_finite_bounds():
    lo,hi=finite_interval([.04]*8, [.2])
    assert np.isnan(lo[0]) and np.isnan(hi[0])
    lo,hi=finite_interval([.05]*70,[.2,.1])
    assert lo.tolist() == pytest.approx([.15,.05])
    assert hi.tolist() == pytest.approx([.25,.15])


def test_asof_market_regime_ignores_future_crash():
    ix=pd.bdate_range('2025-01-01',periods=85)
    p=pd.Series(np.linspace(100,130,85),index=ix)
    early=market_regime(p,asof=ix[75])
    p.iloc[-1]=10
    late=market_regime(p,asof=ix[75])
    assert early == late
    assert early['name']=='Upward trend'


def test_regime_features_are_point_in_time():
    prices=demo_market_data(['AAPL'],sessions=240)
    panel=build_panel(prices.close,prices.volume,horizon=10)
    assert all(x in panel for x in REGIME_FEATURES)
    assert set(panel.market_regime_stress.unique()) <= {0.,1.}


def test_model_lab_keeps_separate_purged_calibration():
    prices=demo_market_data(['AAPL'],sessions=750)
    panel=build_panel(prices.close,prices.volume,horizon=10)
    asof=panel.date.max()
    train=panel[(panel.label_end<asof)&panel.target.notna()]
    current=panel[panel.date.eq(asof)]
    from ithaca_quant.features import FEATURES
    tested=fit_validated_forecaster(train,current,FEATURES,fast=True,candidate_names=('Ridge',))
    assert tested.model_name in ('Ridge','Existing ensemble')
    assert len(tested.forecast)==1
    assert np.isfinite(tested.forecast).all()
    assert tested.calibration_n >= 50
    assert tested.interval_low[0] <= tested.forecast[0] <= tested.interval_high[0]


def test_sec_consensus_surprise_requires_prior_estimate():
    table=pd.DataFrame([{
        'ticker':'AAPL','expectation_timestamp':'2026-01-25T10:00:00Z',
        'release_timestamp':'2026-01-28T22:00:00Z','expected_eps':1.0,
        'reported_eps':1.5,'source':'licensed-fixture'}])
    ix=pd.bdate_range('2026-01-27',periods=5)
    feats=expectations_features('AAPL',table,ix)
    assert feats.loc['2026-01-28','earnings_surprise_available']==0
    assert feats.loc['2026-01-29','earnings_surprise_pct']==pytest.approx(.5)
    table.loc[0,'expectation_timestamp']='2026-01-29T10:00:00Z'
    with pytest.raises(ValueError):
        validated_expectations(table)


def test_event_tags_and_counts_are_transparent():
    flags=event_flags('Company raises quarterly earnings guidance after a merger')
    assert flags['earnings']==1 and flags['guidance']==1 and flags['corporate']==1
    counts=headline_event_counts(pd.DataFrame({'title':['Federal Reserve interest rates',
                                                         'analyst rating downgrade']}))
    assert counts['macro']==1 and counts['analysts']==1


def test_forecasts_are_immutable_then_resolve_after_horizon(tmp_path):
    path=tmp_path/'ledger.sqlite'
    forecast=pd.DataFrame([{'ticker':'AAPL','forecast_excess':.08,'selected_model':'Ridge'}])
    when=pd.Timestamp('2026-01-05')
    assert log_forecasts(forecast,when,2,path=path)==1
    forecast.loc[0,'forecast_excess']=-.99
    assert log_forecasts(forecast,when,2,path=path)==0
    incomplete_ix=pd.bdate_range(when,periods=2)
    close=pd.DataFrame({'SPY':[100.,101.], 'AAPL':[100.,102.]}, index=incomplete_ix)
    assert reconcile_forecasts(close,path=path)==0
    ix=pd.bdate_range(when,periods=3)
    close=pd.DataFrame({'SPY':[100.,101.,102.], 'AAPL':[100.,102.,110.]},index=ix)
    assert reconcile_forecasts(close,path=path)==1
    ledger=read_forecasts(path)
    assert ledger.forecast.iloc[0]==pytest.approx(.08)
    assert ledger.observed.iloc[0]==pytest.approx(.08)
    report=forward_report(path)
    assert report['logged']==report['resolved']==1
    assert report['mae']==pytest.approx(0)


def test_portfolio_stress_is_pre_entry_only():
    ix=pd.bdate_range('2025-01-01',periods=200)
    vals=np.linspace(100,130,200)
    c=pd.DataFrame({'SPY':vals, 'AAPL':vals*1.1,'MSFT':vals*1.2},index=ix)
    old=stress_summary(c,{'AAPL':.2,'MSFT':.2})
    c.loc[ix[-1],'AAPL']=9999
    earlier=stress_summary(c.loc[:ix[-2]],{'AAPL':.2,'MSFT':.2})
    compare=stress_summary(c.iloc[:-1],{'AAPL':.2,'MSFT':.2})
    assert earlier==compare
    assert 'shock_scenarios' in old
    assert len(old['shock_scenarios'])==3


def test_rate_guard_blocks_duplicate_window(tmp_path):
    path=tmp_path/'guard.sqlite'
    assert allow_request('provider',2,60,path=path,now=1000)
    assert allow_request('provider',2,60,path=path,now=1001)
    assert not allow_request('provider',2,60,path=path,now=1002)
    assert allow_request('provider',2,60,path=path,now=1200)


def test_opt_in_remote_sqlite_backend_survives_local_absence(monkeypatch,tmp_path):
    pytest.importorskip('sqlalchemy')  # optional cloud-store dependency (see requirements.txt)
    url='sqlite:///'+str(tmp_path/'remote.db')
    monkeypatch.setenv('ITHACA_DATABASE_URL',url)
    remote_store._tables.cache_clear()
    assert remote_store.health()['reachable']
    save_snapshot('test:one','screen',{'a':[1,2,3]})
    result=load_snapshot('test:one','screen')
    assert result[0]=={'a':[1,2,3]}
    monkeypatch.delenv('ITHACA_DATABASE_URL')
    remote_store._tables.cache_clear()


def test_fred_uses_correct_vintage_query_no_future_revisions():
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {'observations':[{'date':'2026-02-01','value':'2.5'},
                                    {'date':'2026-01-01','value':'.'},
                                    {'date':'2026-03-01','value':'3.5'}]}
    class Session:
        def get(self,url,params,timeout):
            assert params['realtime_start']==params['realtime_end']=='2026-04-01'
            assert params['file_type']=='json'
            return Response()
    obs=fred_vintage('DFF','fixture-key','2026-04-01',client=Session())
    assert len(obs)==2 and obs.value.iloc[-1]==pytest.approx(3.5)


def test_release_and_github_workflow_have_correct_structure():
    root=Path(__file__).resolve().parents[1]
    from ithaca_quant import __version__
    assert __version__=='2.5.0'
    assert 'APP_RELEASE = "2.5.0"' in (root/'app.py').read_text()
    assert (root/'scripts/refresh_job.py').is_file()
    assert (root/'.github/workflows/ithaca-refresh.yml').is_file()
    assert 'secrets.ITHACA_DATABASE_URL' in (root/'.github/workflows/ithaca-refresh.yml').read_text()


def test_vendor_archive_requires_provenance_and_preserves_earliest_available_time(tmp_path):
    from ithaca_quant.news_archive import import_vendor_archive, recorded_headlines, archived_features
    row={'ticker':'AAPL','title':'AAPL reports quarterly earnings','url':'https://example.com/story',
         'publisher':'licensed-fixture','published_utc':'2026-01-05T12:00:00Z',
         'first_seen_utc':'2026-01-05T12:05:00Z','sentiment':2.0,'relevance':1.0}
    file=tmp_path/'headlines.sqlite'
    with pytest.raises(ValueError):
        import_vendor_archive(pd.DataFrame([row]),path=file)
    n=import_vendor_archive(pd.DataFrame([row]),path=file,provenance_confirmed=True,
                            now=datetime(2026,1,9,tzinfo=timezone.utc))
    assert n==1
    assert import_vendor_archive(pd.DataFrame([row]),path=file,provenance_confirmed=True,
                                 now=datetime(2026,1,9,tzinfo=timezone.utc))==0
    records=recorded_headlines('AAPL',path=file)
    assert records.first_seen_utc.iloc[0]==pd.Timestamp('2026-01-05T12:05:00Z')
    features=archived_features('AAPL',pd.bdate_range('2026-01-05',periods=3),path=file)
    assert features.loc['2026-01-05','news_available']==0
    assert features.loc['2026-01-06','news_earnings_7d']>0
    newer=dict(row,first_seen_utc='2025-12-01T00:00:00Z')
    with pytest.raises(ValueError):
        import_vendor_archive(pd.DataFrame([newer]),path=file,provenance_confirmed=True)
