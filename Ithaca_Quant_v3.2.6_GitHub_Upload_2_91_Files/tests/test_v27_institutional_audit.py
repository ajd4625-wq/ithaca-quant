"""Tests for point-in-time institutional research audit, no market internet needed."""
import numpy as np
import pandas as pd
import pytest
from ithaca_quant.institutional_audit import availability_safe_join, factor_audit, next_close_proxy


def test_reject_future_news_and_missing_discovery_time():
    s=pd.DataFrame({'ticker':['AAOI']*4,'signal_time':[
        '2026-11-16T15:00Z','2026-11-17T15:00Z','2026-11-18T15:00Z','2026-11-20T15:00Z']})
    e=pd.DataFrame({'ticker':['AAOI']*3,
        'published_at':['2026-11-15T12:00Z','2026-11-17T12:00Z','2026-11-18T12:00Z'],
        'discovered_at':['2026-11-17T12:00Z','2026-11-19T12:00Z',None],
        'event_score':[3,5,999]})
    out=availability_safe_join(s,e)
    assert pd.isna(out.event_score.iloc[0])
    assert out.event_score.iloc[1]==3
    assert out.event_score.iloc[2]==3
    assert out.event_score.iloc[3]==5
    assert 999 not in out.event_score.tolist()


def test_no_cross_ticker_events_and_row_order_preserved():
    s=pd.DataFrame({'ticker':['B','A','B'],'signal_time':['2026-01-10']*3})
    e=pd.DataFrame({'ticker':['A','B'],'published_at':['2026-01-09']*2,
                    'discovered_at':['2026-01-09']*2,'event_score':[1,2]})
    o=availability_safe_join(s,e)
    assert o.ticker.tolist()==['B','A','B']
    assert o.event_score.tolist()==[2,1,2]


def test_signal_collision_and_missing_columns_rejected():
    s=pd.DataFrame({'ticker':['A'],'signal_time':['2026-01-10'],'event_score':[0]})
    e=pd.DataFrame({'ticker':['A'],'published_at':['2026-01-09'],'discovered_at':['2026-01-09'],'event_score':[3]})
    with pytest.raises(ValueError,match='collides'):
        availability_safe_join(s,e)
    with pytest.raises(ValueError,match='Missing'):
        availability_safe_join(s,e.drop(columns=['discovered_at']))


def make_panel(periods=12):
    rows=[]
    for d in pd.bdate_range('2025-01-01',periods=periods*5,freq='B')[::5]:
        for j in range(10):
            x=j-4.5
            rows.append({'signal_date':d,'end_date':d+pd.Timedelta(days=7),
                         'ticker':f'S{j}','pred_excess':x,'realized_excess':.01*x,
                         'realized_return':.01*x+.01})
    return pd.DataFrame(rows)


def test_factor_audit_rank_ic_cost_and_date_bootstrap():
    table=make_panel()
    a=factor_audit(table,top_fraction=.2,assumed_round_trip_bps=20)
    assert a.metrics['windows']==12
    assert a.metrics['ticker_outcomes']==120
    assert np.isclose(a.metrics['mean_rank_ic'],1)
    assert a.metrics['top_vs_universe_excess']>0
    assert a.metrics['uplift_ci_low']>0
    assert (a.by_date.top_mean_excess_after_cost_stress < a.by_date.top_mean_excess).all()
    assert np.isclose(a.by_date.iloc[0].top_mean_excess - a.by_date.iloc[0].top_mean_excess_after_cost_stress, .002)
    assert set(a.selected.ticker)=={'S8','S9'}


def test_factor_audit_sectors_and_short_windows():
    s={'S'+str(i):('Tech' if i<5 else 'Health') for i in range(10)}
    a=factor_audit(make_panel(3),sectors=s)
    assert a.metrics['uplift_ci_low'] is None
    assert 'mean_sector_neutral_ic' in a.metrics


def test_factor_rejects_duplicate_dates_and_nonchronological_outcomes():
    x=make_panel(1)
    with pytest.raises(ValueError,match='Duplicate'):
        factor_audit(pd.concat([x,x.iloc[:1]]))
    x.loc[x.index[0],'end_date']=x.iloc[0].signal_date
    with pytest.raises(ValueError,match='after its signal'):
        factor_audit(x)


def test_next_close_proxy_uses_next_day_not_signal_day():
    dates=pd.bdate_range('2026-11-09',periods=10)
    spy=np.linspace(100,109,len(dates))
    close=pd.DataFrame({'SPY':spy,**{f'S{j}':np.linspace(100+j,120+j,10) for j in range(10)}},index=dates)
    p=pd.DataFrame([{'signal_date':dates[1], 'end_date':dates[5],
                     'ticker':f'S{j}', 'pred_excess':j} for j in range(10)])
    out=next_close_proxy(p,close,top_fraction=.2,round_trip_bps=20)
    assert len(out)==2
    assert (out.entry_proxy_date==dates[2]).all()
    assert (out.exit_proxy_date==dates[6]).all()
    assert np.isclose(out.iloc[0].next_close_return-out.iloc[0].next_close_net_return_stress,.002)
    assert (out.next_close_return != out.same_close_return).all()


def test_next_close_proxy_fails_closed_if_no_future_bar():
    ix=pd.bdate_range('2026-11-09',periods=7)
    close=pd.DataFrame({'SPY':[100]*7, **{f'S{j}':[100]*7 for j in range(10)}},index=ix)
    p=pd.DataFrame([{'signal_date':ix[1],'end_date':ix[-1], 'ticker':f'S{j}','pred_excess':j} for j in range(10)])
    assert next_close_proxy(p,close).empty


def test_lookahead_earnings_cannot_be_backfilled():
    s=pd.DataFrame({'ticker':['A','A'],'signal_time':['2026-02-15','2026-03-01']})
    e=pd.DataFrame({'ticker':['A'],'published_at':['2026-02-20'],'discovered_at':['2026-02-21'],'event_score':[.99]})
    matched=availability_safe_join(s,e)
    assert pd.isna(matched.iloc[0].event_score) and matched.iloc[1].event_score==.99


def test_price_quality_flags_missing_stale_and_extreme_bars():
    from ithaca_quant.institutional_audit import historical_data_health
    d=pd.bdate_range('2025-01-01',periods=10)
    cl=pd.DataFrame({'SPY':[100+i for i in range(10)],
                     'CLEAN':[100+i for i in range(10)],
                     'STALE':[100+i for i in range(7)]+[np.nan]*3,
                     'SPIKE':[10]*5+[100]+[100]*4},index=d)
    h=historical_data_health(cl)
    assert h.set_index('ticker').loc['CLEAN','review']=='No simple flags'
    assert 'Stale' in h.set_index('ticker').loc['STALE','review']
    assert h.set_index('ticker').loc['SPIKE','large_daily_move_flags']==1


def test_price_quality_rejects_duplicate_dates():
    from ithaca_quant.institutional_audit import historical_data_health
    d=pd.to_datetime(['2026-01-05','2026-01-05'])
    with pytest.raises(ValueError,match='unique'):
        historical_data_health(pd.DataFrame({'SPY':[100,101]},index=d))
