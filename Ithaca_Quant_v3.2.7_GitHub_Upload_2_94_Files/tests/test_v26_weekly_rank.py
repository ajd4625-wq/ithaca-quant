"""Major accuracy + weekly reporting feature tests."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from ithaca_quant.weekly_reports import report_window, summarize_week, render_report, make_weekly_report, load_weekly_report, send_weekly_email
from ithaca_quant.forecast_audit import log_forecasts, read_forecasts, reconcile_forecasts
from ithaca_quant.ranking_accuracy import rank_outperformance, _scores


def test_friday_window_dst():
    winter_start, winter_end = report_window(datetime(2026, 11, 20, 21, tzinfo=timezone.utc))
    summer_start, summer_end = report_window(datetime(2026, 7, 10, 20, tzinfo=timezone.utc))
    assert winter_end.hour == summer_end.hour == 18
    assert winter_end.utcoffset().total_seconds() == -5*3600
    assert summer_end.utcoffset().total_seconds() == -4*3600
    assert winter_end.weekday() == summer_end.weekday() == 4


def test_weekly_filters_by_resolution_not_forecast_date():
    report_at = datetime(2026,11,20,21,tzinfo=timezone.utc)
    data = pd.DataFrame([
        dict(ticker='AAOI',asof='2026-10-01',horizon=20,forecast=.1,observed=.08,
             resolved_utc='2026-11-19T14:00:00+00:00'),
        dict(ticker='RKLB',asof='2026-11-01',horizon=5,forecast=.2,observed=-.1,
             resolved_utc='2026-11-10T14:00:00+00:00'),
        dict(ticker='TEM',asof='2026-11-10',horizon=20,forecast=.4,observed=np.nan,
             resolved_utc=None),
    ])
    r = summarize_week(data, end=report_at)
    assert r['evaluated'] == 1
    assert r['directional_accuracy'] == 1
    assert r['forecast_mae'] == .02 or np.isclose(r['forecast_mae'],.02)
    assert 'insufficient evidence' in render_report(r)


def test_old_rows_are_not_invented_for_a_week():
    past = pd.DataFrame([dict(asof='2026-11-02',ticker='A',horizon=5,forecast=.1,observed=.1)])
    r=summarize_week(past, end=datetime(2026,11,20,21,tzinfo=timezone.utc))
    assert r['evaluated']==0 and r['directional_accuracy'] is None


def test_ledger_writes_resolution_once_and_migrates(tmp_path):
    path=tmp_path/'market.db'
    log_forecasts(pd.DataFrame([{'ticker':'AAPL','forecast_excess':.01}]),'2026-11-11',2,path=path)
    close=pd.DataFrame({'SPY':[100,101,103], 'AAPL':[100,103,105]},index=pd.bdate_range('2026-11-11',periods=3))
    assert reconcile_forecasts(close,path=path)==1
    x=read_forecasts(path)
    assert x.resolved_utc.notna().all()
    assert reconcile_forecasts(close,path=path)==0


def test_report_persistence(tmp_path):
    path=tmp_path/'market.db'
    log_forecasts(pd.DataFrame([{'ticker':'AAPL','forecast_excess':.01}]),'2026-11-11',2,path=path)
    r=make_weekly_report(path=path,when=datetime(2026,11,20,21,tzinfo=timezone.utc))
    assert load_weekly_report('2026-11-20',path=path)==r


def test_no_unconfigured_email_sent():
    r=summarize_week(pd.DataFrame(),end=datetime(2026,11,20,21,tzinfo=timezone.utc))
    assert send_weekly_email(r,environ={}) is False


def test_rank_scoring_reports_coverage_not_just_accuracy():
    dates=['2026-11-12']*4 + ['2026-11-13']*4
    outcome=[1,0,1,0,1,1,0,0]
    p=[.9,.1,.75,.2,.88,.76,.25,.3]
    m=_scores(outcome,p,dates)
    assert m['n']==8 and m['dates']==2
    assert m['high_confidence_n']>=2
    assert m['high_confidence_accuracy'] is not None


def test_rank_insufficient_history_fails_closed():
    ix=pd.bdate_range('2026-01-01',periods=30)
    frame=pd.DataFrame([{'date':day,'ticker':name,'target':.1,'label_end':day+pd.Timedelta(days=2),
                         'mom_5':.1} for day in ix for name in ['A','B','C','D','E','F','G','H','I','J']])
    r=rank_outperformance(frame)
    assert not r.activated and r.candidates.empty


def test_ranking_challenger_separates_selection_from_audit():
    # Designed synthetic signal: yesterday's observable feature predicts future
    # SPY-relative direction. This verifies pipeline mechanics, not live accuracy.
    rng=np.random.default_rng(5)
    dates=pd.bdate_range('2024-01-02',periods=380)
    rows=[]
    for day_i,day in enumerate(dates):
        for symbol_i in range(12):
            x=rng.normal()
            label=0.03 if x > 0 else -0.03
            record={'date':day,'ticker':f'T{symbol_i:02d}',
                    'target':label,'label_end':dates[min(day_i+5,len(dates)-1)],
                    'mom_20':x,'mom_5_accel':x/10,'range_252':.5}
            rows.append(record)
    panel=pd.DataFrame(rows)
    out=rank_outperformance(panel)
    assert out.selection['n'] >= 300
    assert out.selection['dates'] >= 20
    assert out.audit['n'] >= 300
    assert out.audit['dates'] >= 20
    assert out.activated
    assert len(out.candidates)==12
    assert 0.0 <= out.candidates.p_outperform.min() <= out.candidates.p_outperform.max() <= 1.0


def test_daily_worker_skips_without_persistent_database(monkeypatch):
    monkeypatch.delenv('ITHACA_DATABASE_URL',raising=False)
    import importlib.util
    import pathlib
    spec=importlib.util.spec_from_file_location('daily_job',pathlib.Path(__file__).resolve().parents[1]/'scripts/daily_forecast_job.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main()==0
