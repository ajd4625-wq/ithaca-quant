import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import pandas as pd
from datetime import date
from ledger import connect,record,resolve,report,last_friday,write_html


def test_no_duplicate_and_no_future_leak(tmp_path):
    c=connect(tmp_path/'ledger.db')
    # Six common sessions: last mark is five sessions AFTER signal date.
    dates=pd.bdate_range('2026-11-02',periods=6)
    stock=pd.Series([100,101,102,103,104,110],index=dates)
    spy=pd.Series([200,201,202,203,204,206],index=dates)
    issued=dates[0].date().isoformat()
    p={'ticker':'TEST','asof':issued,'label':'ENTRY WATCH','direction':'UP',
       'strength':70,'expected_excess_return':.05,'entry_stock':100,'entry_spy':200}
    assert record(c,**p)
    assert not record(c,**p)
    assert resolve(c,'TEST',stock.iloc[:5],spy.iloc[:5])==0
    assert resolve(c,'TEST',stock,spy)==1
    assert resolve(c,'TEST',stock,spy)==0
    r=report(c,'2026-11-13')
    assert r['issued']==0 and r['graded']==1 and r['correct']==1
    assert r['accuracy_pct']==100.0
    assert r['mean_excess_return_pct']>0
    # Report writes tangible HTML even without anything due this week.
    p=tmp_path/'report.html';write_html(r,p)
    assert 'Weekly Accuracy Audit' in p.read_text()
    c.close()


def test_abstention_and_absolute_vs_spy(tmp_path):
    c=connect(tmp_path/'ledger.db')
    dates=pd.bdate_range('2026-11-02',periods=6)
    stock=pd.Series([100,101,101,102,103,103],index=dates)
    spy=pd.Series([100,102,103,104,108,111],index=dates)
    record(c,ticker='ZZZ',asof='2026-11-02',label='WAIT',direction=None,
           strength=None,expected_excess_return=None,entry_stock=100,entry_spy=100)
    record(c,ticker='YYY',asof='2026-11-02',label='UNDERPERFORMANCE WATCH',direction='DOWN',
           strength=12,expected_excess_return=-.025,entry_stock=100,entry_spy=100)
    assert resolve(c,'ZZZ',stock,spy)==1
    assert resolve(c,'YYY',stock,spy)==1
    r=report(c,'2026-11-13')
    assert r['graded']==2-1 and r['correct']==1
    assert report(c,'2026-11-06')['abstained_issued']==1
    c.close()


def test_no_look_ahead_or_weak_source(tmp_path):
    from server import completed_daily, valid_ticker
    from ithaca_quant.data import MarketData
    from datetime import datetime
    from zoneinfo import ZoneInfo
    idx=pd.to_datetime(['2026-11-18','2026-11-19'])
    m=MarketData(pd.DataFrame({'SPY':[1,2],'TEST':[3,4]},index=idx),
                 pd.DataFrame({'SPY':[5,6],'TEST':[7,8]},index=idx),'test',[])
    x=completed_daily(m,datetime(2026,11,19,15,30,tzinfo=ZoneInfo('America/New_York')))
    assert len(x.close)==1
    assert valid_ticker('brk-b')=='BRK-B'
    import pytest
    with pytest.raises(ValueError):valid_ticker('AV; DROP TABLE forecasts')
