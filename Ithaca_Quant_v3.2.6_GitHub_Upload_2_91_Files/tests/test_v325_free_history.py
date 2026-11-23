"""Offline source-integrity and as-of regressions; NOT market accuracy proof."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import MarketData
from ithaca_quant.features import build_panel
from ithaca_quant.free_history import (build_free_bundle, load_free_bundle,
                                        extend_with_free_history, fetch_free_sec_histories)


def fake_market(days=240, end='2026-10-16', names=('SPY','AAPL','MSFT')):
    ix=pd.bdate_range(end=end,periods=days)
    close=pd.DataFrame({n:np.arange(days,dtype=float)*(.2+i*.1)+100+i for i,n in enumerate(names)}, index=ix)
    volume=pd.DataFrame({n:np.full(days,100000+i) for i,n in enumerate(names)}, index=ix)
    raw=close.mul(.97)
    return MarketData(close,volume,'MOCK SOURCE',[],raw)


def test_local_free_cache_roundtrip_and_sources(tmp_path):
    market=fake_market()
    q=build_free_bundle(tmp_path,['AAPL','MSFT'],years=5,
                        fetch_prices=lambda tickers,**kwargs:market,completed_only=False)
    assert q['universe_coverage_verified'] is False
    assert q['delisted_returns_verified'] is False
    assert q['observed_symbols']==['AAPL','MSFT']
    assert q['data_grade']=='FREE_OBSERVED_TICKER_SUBSET_NOT_PIT_UNIVERSE'
    loaded=load_free_bundle(tmp_path)
    pd.testing.assert_frame_equal(loaded.market.close.sort_index(axis=1).rename_axis(None,axis=1),market.close.sort_index(axis=1),check_freq=False)
    pd.testing.assert_frame_equal(loaded.market.volume.sort_index(axis=1).rename_axis(None,axis=1),market.volume.sort_index(axis=1),check_freq=False,check_dtype=False)
    pd.testing.assert_frame_equal(loaded.market.raw_close.sort_index(axis=1).rename_axis(None,axis=1),market.raw_close.sort_index(axis=1),check_freq=False)


def test_cache_checksum_catches_bogus_edited_price(tmp_path):
    build_free_bundle(tmp_path,['AAPL'],fetch_prices=lambda tickers,**kw:fake_market(names=('SPY','AAPL')),
                      completed_only=False)
    f=tmp_path/'prices.csv'
    f.write_bytes(f.read_bytes().replace(b'AAPL',b'ZZZZ',1))
    with pytest.raises(ValueError,match='hash mismatch'):
        load_free_bundle(tmp_path)


def test_missing_symbols_not_reported_as_success(tmp_path):
    q=build_free_bundle(tmp_path,['AAPL','MSFT'],fetch_prices=lambda tickers,**kw:fake_market(names=('SPY','AAPL')),
                        completed_only=False)
    assert q['missing_symbols']==['MSFT']
    assert load_free_bundle(tmp_path).market.close.columns.tolist()==['AAPL','SPY']


def test_reject_unverified_current_ticker_scope_instead_of_pit_label(tmp_path):
    build_free_bundle(tmp_path,['AAPL'],fetch_prices=lambda tickers,**kw:fake_market(names=('SPY','AAPL')),
                      completed_only=False)
    manifest=json.loads((tmp_path/'manifest.json').read_text())
    manifest['data_grade']='INSTITUTIONAL_PIT_CERTIFIED'
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='misleading'):
        load_free_bundle(tmp_path)


def test_no_stale_stock_forward_fill_on_free_price_extension(tmp_path):
    historic=fake_market(days=240)
    build_free_bundle(tmp_path,['AAPL','MSFT'],fetch_prices=lambda tickers,**kw:historic,
                      completed_only=False)
    present=fake_market(days=50)
    present.close.loc[present.close.index[-1],'MSFT']=np.nan
    present.volume.loc[present.volume.index[-1],'MSFT']=np.nan
    present.raw_close.loc[present.raw_close.index[-1],'MSFT']=np.nan
    # Source values for overlap have same simulated price trend when aligned.
    aligned=historic.close.loc[present.close.index]
    present.close.loc[:,['SPY','AAPL','MSFT']]=aligned
    present.raw_close.loc[:,['SPY','AAPL','MSFT']]=historic.raw_close.loc[present.close.index]
    present.close.loc[present.close.index[-1],'MSFT']=np.nan
    present.raw_close.loc[present.raw_close.index[-1],'MSFT']=np.nan
    merged=extend_with_free_history(present,load_free_bundle(tmp_path))
    assert len(merged.close)==len(historic.close)
    assert np.isnan(merged.close.loc[merged.close.index[-1],'MSFT'])
    assert not merged.close.loc[merged.close.index[-1],'AAPL'] == 0


def test_overlap_rejects_revised_or_mismatched_adjustment_scale(tmp_path):
    historic=fake_market()
    build_free_bundle(tmp_path,['AAPL','MSFT'],fetch_prices=lambda tickers,**kw:historic,
                      completed_only=False)
    live=MarketData(historic.close.tail(50).copy(),historic.volume.tail(50).copy(),
                    'LIVE',[],historic.raw_close.tail(50).copy())
    live.close['AAPL'] *= .8
    with pytest.raises(ValueError,match='conflict|agreement'):
        extend_with_free_history(live,load_free_bundle(tmp_path))


def test_sec_vintage_filing_used_only_next_session(tmp_path):
    hist=fake_market(end='2026-06-01',names=('SPY','AAPL'))
    events=pd.DataFrame([{'asof_event':'2026-02-05','filed':'2026-02-05',
        'period_end':'2025-12-31','revenue_usd':130,'net_income_usd':23,
        'revenue_yoy':.3,'net_margin':.1769,'eps_yoy':np.nan,
        'revenue_growth_accel':np.nan}])
    build_free_bundle(tmp_path,['AAPL'],fetch_prices=lambda tickers,**kw:hist,
                      fetch_sec=lambda symbols, contact:({'AAPL':events},{'AAPL':{'status':'mock'}}),
                      sec_contact='research@example.org',completed_only=False)
    archive=load_free_bundle(tmp_path)
    panel=build_panel(archive.market.close,archive.market.volume,horizon=5,
                      fundamentals=archive.fundamentals)
    before=panel.loc[(panel.date==pd.Timestamp('2026-02-05'))&panel.ticker.eq('AAPL')]
    after=panel.loc[(panel.date==pd.Timestamp('2026-02-06'))&panel.ticker.eq('AAPL')]
    # If the synthetic data window does not include the date, extend it.
    assert len(before)==1 and len(after)==1
    assert before.iloc[0].sec_available==0
    assert after.iloc[0].sec_available==1
    assert after.iloc[0].sec_revenue_yoy==pytest.approx(.3)


def test_sec_only_looks_up_current_cik_and_exposes_missing():
    directory={'0':{'cik_str':320193,'ticker':'AAPL','title':'Apple Inc.'}}
    fake_facts={'facts':{'us-gaap':{
       'RevenueFromContractWithCustomerExcludingAssessedTax':{'units':{'USD':[
          {'start':'2025-10-01','end':'2025-12-31','filed':'2026-02-05',
           'val':100.0,'form':'10-Q'}]}},
    }}}
    class Reply:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return fake_facts
    class Client:
        def get(self,url,headers,timeout):
            assert 'CIK0000320193' in url
            assert 'research@example.org' in headers['User-Agent']
            return Reply()
    got,status=fetch_free_sec_histories(['AAPL','NOPE'],'research@example.org',
              directory=directory,client=Client(),pause=0)
    assert status['NOPE']['status']=='no_current_SEC_CIK'
    assert 'AAPL' in got and not got['AAPL'].empty
