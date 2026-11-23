"""Synthetic fixtures only: verify licensed-vendor conversion invariants."""
import io
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from ithaca_quant.historical_vendor import (
    normalize_tickers, build_from_sharadar_exports, download_sharadar_table,
    HistoricalVendorError, download_spy_funds)
from ithaca_quant.historical_archive import load_historical_archive


def fixture_data(tmp_path):
    dates=pd.bdate_range('2023-01-02',periods=100)
    tick=pd.DataFrame([
        dict(table='STOCKS',permaticker='1001',ticker='ALFA',category='Domestic Common Stock',
             firstpricedate='2022-01-01',lastpricedate=dates[-1].strftime('%Y-%m-%d'),isdelisted='N'),
        dict(table='STOCKS',permaticker='1002',ticker='OLD1',category='Domestic Common Stock',
             firstpricedate='2022-01-01',lastpricedate=dates[69].strftime('%Y-%m-%d'),isdelisted='Y'),
        dict(table='STOCKS',permaticker='1010',ticker='PREF',category='Domestic Preferred Stock',
             firstpricedate='2022-01-01',lastpricedate=dates[-1].strftime('%Y-%m-%d'),isdelisted='N')
    ]);tick.to_csv(tmp_path/'tickers.csv',index=False)
    stock=[];spy=[]
    for n,d in enumerate(dates):
        spy.append({'ticker':'SPY','date':d.strftime('%Y-%m-%d'),'closeadj':400+n,
                    'closeunadj':400+n,'volume':300_000})
        for t,stop in [('ALFA',100),('OLD1',70),('PREF',100)]:
            if n>=stop:continue
            stock.append({'ticker':t,'date':d.strftime('%Y-%m-%d'),
                          'closeadj':30+n/10,'closeunadj':40+n/10,'volume':600_000})
    pd.DataFrame(stock).to_csv(tmp_path/'stocks.csv',index=False)
    pd.DataFrame(spy).to_csv(tmp_path/'spy.csv',index=False)
    return dates


def do_build(tmp_path, **kwargs):
    fixture_data(tmp_path)
    return build_from_sharadar_exports(tickers_path=tmp_path/'tickers.csv',
        stocks_path=tmp_path/'stocks.csv',spy_path=tmp_path/'spy.csv',
        output_path=tmp_path/'history.zip',
        start='2023-01-02',end='2023-05-19',source_reference='test fixture: fake vendor records',**kwargs)


def test_permanent_ids_delisting_and_benchmark(tmp_path):
    report=do_build(tmp_path)
    bundle=load_historical_archive(tmp_path/'history.zip')
    assert report['observed_delisted_issue_ids']==1
    assert set(bundle.market.close.columns)=={'SPY','SH1001','SH1002'}
    assert bundle.market.close['SH1002'].notna().sum()==70
    assert bundle.market.close['SH1002'].iloc[-1]!=bundle.market.close['SH1002'].iloc[-1]  # NaN after delist
    assert bundle.membership.loc[bundle.membership.ticker.eq('SH1002')].shape[0]==70
    assert bundle.quality['historical_universe_completeness_verified'] is False
    assert report['terminal_payoffs_verified']==0
    assert (tmp_path/'history.quality.json').exists()


def test_missing_adjusted_prices_fail_closed(tmp_path):
    fixture_data(tmp_path)
    p=tmp_path/'stocks.csv';frame=pd.read_csv(p)
    frame.loc[frame.ticker.eq('ALFA').idxmax(),'closeadj']=np.nan;frame.to_csv(p,index=False)
    with pytest.raises(HistoricalVendorError,match='cannot silently impute'):
        build_from_sharadar_exports(tickers_path=tmp_path/'tickers.csv',stocks_path=p,
            spy_path=tmp_path/'spy.csv',output_path=tmp_path/'bad.zip',
            start='2023-01-02',end='2023-05-19')
    assert not (tmp_path/'bad.zip').exists()


def test_no_delisted_issues_is_not_claimed_complete(tmp_path):
    fixture_data(tmp_path)
    t=pd.read_csv(tmp_path/'tickers.csv');t=t[t.ticker.ne('OLD1')]
    t.to_csv(tmp_path/'tickers.csv',index=False)
    with pytest.raises(HistoricalVendorError,match='delisted'):
        build_from_sharadar_exports(tickers_path=tmp_path/'tickers.csv',
            stocks_path=tmp_path/'stocks.csv',spy_path=tmp_path/'spy.csv',
            output_path=tmp_path/'bad.zip',start='2023-01-02',end='2023-05-19')


def test_reused_ticker_requires_crosswalk():
    f=pd.DataFrame([dict(table='stocks',permaticker='1',ticker='OOPS',category='Domestic Common Stock',
            firstpricedate='2022-01-01',lastpricedate='2022-12-31',isdelisted='Y'),
            dict(table='stocks',permaticker='2',ticker='OOPS',category='Domestic Common Stock',
            firstpricedate='2023-01-01',lastpricedate='2024-12-31',isdelisted='N')])
    with pytest.raises(HistoricalVendorError,match='crosswalk'):
        normalize_tickers(f)


def test_no_key_refuses_vendor_download(tmp_path):
    with pytest.raises(HistoricalVendorError,match='SHARADAR_API_KEY'):
        download_sharadar_table('tickers',tmp_path/'download.zip',api_key='')


def test_spy_download_checks_entitlements_and_completeness(tmp_path):
    class Response:
        ok=True;status_code=200
        content=b'ticker,date,closeadj,closeunadj,volume\nSPY,2023-01-01,100,100,1\n'
    class Session:
        def get(self,*args,**kwargs):return Response()
    with pytest.raises(HistoricalVendorError,match='incomplete'):
        download_spy_funds(tmp_path/'spy.csv',api_key='fake',start='2023-01-01',end='2023-02-01',session=Session())
    assert not (tmp_path/'spy.csv').exists()


def test_incomplete_vendor_stock_export_cannot_pass_universe_check(tmp_path):
    fixture_data(tmp_path)
    f=pd.read_csv(tmp_path/'stocks.csv')
    f=f[f.ticker.ne('ALFA')]
    f.to_csv(tmp_path/'stocks.csv',index=False)
    with pytest.raises(HistoricalVendorError,match='Incomplete vendor STOCKS export'):
        build_from_sharadar_exports(tickers_path=tmp_path/'tickers.csv',
            stocks_path=tmp_path/'stocks.csv',spy_path=tmp_path/'spy.csv',
            output_path=tmp_path/'bad.zip',start='2023-01-02',end='2023-05-19')
    assert not (tmp_path/'bad.zip').exists()


def test_missing_daily_history_is_not_marked_complete(tmp_path):
    fixture_data(tmp_path)
    p=tmp_path/'stocks.csv';f=pd.read_csv(p)
    dates=f.loc[f.ticker.eq('ALFA'),'date'].iloc[20:40]
    f=f[~(f.ticker.eq('ALFA') & f.date.isin(dates))]
    f.to_csv(p,index=False)
    with pytest.raises(HistoricalVendorError,match='below 95%'):
        build_from_sharadar_exports(tickers_path=tmp_path/'tickers.csv',stocks_path=p,
             spy_path=tmp_path/'spy.csv',output_path=tmp_path/'bad.zip',
             start='2023-01-02',end='2023-05-19')


def test_official_vendor_zip_download_streams_and_hashes(tmp_path):
    from zipfile import ZipFile
    from hashlib import sha256
    output=io.BytesIO()
    with ZipFile(output,'w') as z:z.writestr('tickers.csv','ticker,permaticker\nAAPL,42\n')
    payload=output.getvalue()
    class Response:
        ok=True; status_code=200
        url='https://api.sharadar.com/download/temporary'
        def __enter__(self): return self
        def __exit__(self,*args): return False
        def iter_content(self,chunk_size):
            yield payload[:12];yield payload[12:]
    class Session:
        def get(self,*args,**kwargs):
            assert kwargs['params']['api_key']=='mock-secret'
            return Response()
    destination=tmp_path/'tickers.zip'
    result=download_sharadar_table('tickers',destination,api_key='mock-secret',session=Session())
    assert destination.read_bytes()==payload
    assert result['sha256']==sha256(payload).hexdigest()
    assert 'mock-secret' not in str(result)
