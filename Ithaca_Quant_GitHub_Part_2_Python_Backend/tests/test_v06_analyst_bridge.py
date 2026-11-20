"""Synthetic fixtures ONLY: no real feed, accuracy or trading claim."""
from datetime import datetime, timezone
import json
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import numpy as np
import pandas as pd
import pytest
import analyst_bridge as bridge
import server


def prices(names):
    rng=np.random.default_rng(900)
    r=rng.normal(.0004,.007,size=(260,len(names)))
    index=pd.bdate_range(end=datetime.now(timezone.utc).date(),periods=260)
    return pd.DataFrame(100*np.cumprod(1+r,axis=0),index=index,columns=names)


def good_holdings():
    return [{'ticker':'AAPL','shares':5,'price':200},{'ticker':'MSFT','shares':2,'price':400},
            {'ticker':'NVDA','shares':4,'price':125},{'ticker':'JPM','shares':5,'price':200},
            {'ticker':'GOOGL','shares':4,'price':175}]


def fixture_opinion(t,check,provider):
    assert check(t)==t
    return {'status':'unavailable','ticker':t,'reason':'Mocked provider unavailable'}


def history(symbols):
    return prices(symbols),'SYNTHETIC TEST PRICES — NOT MARKET DATA'


def test_v32_upstream_code_and_strict_agent_retry_bounds():
    assert server.MAX_AGENTS == 3 and server.MAX_RETRIES == 2
    assert server.FITTED_AGENT_NAMES == ('Forecast','Momentum','Risk')
    assert bridge.MAX_POSITIONS == 20
    assert 'v32' in str(bridge.DB)


def test_holdings_use_raw_user_quote_for_valuation_not_adjusted_historical_price():
    payload={'holdings':good_holdings(),'cash_reserve':.10,'max_position':.25}
    result=bridge.research_portfolio(payload,server.valid_ticker,history_loader=history,
        quote_loader=lambda _: (_ for _ in ()).throw(AssertionError('No quote download for user prices')),
        opinion_loader=fixture_opinion)
    assert result['research_only'] and result['orders_placed'] is False
    assert result['portfolio_value']==4000
    assert result['positions'][0]['market_value']==1000
    assert result['positions'][0]['quote_source']=='Manual valuation provided by user'
    assert result['target_exposure']==pytest.approx(.9)
    assert sum(x['research_weight'] for x in result['positions'])==pytest.approx(.9,abs=1e-6)
    assert result['forecast_tilt_qualified_count']==0
    assert all(x['analyst_status']=='unavailable' for x in result['positions'])
    assert result['sessions']>=126


def test_incomplete_recent_history_fails_closed():
    def incomplete(symbols):
        f=prices(symbols)
        f.loc[f.index[-5],'MSFT']=np.nan
        return f,'FIXTURE'
    with pytest.raises(ValueError,match='Incomplete'):
        bridge.research_portfolio({'holdings':good_holdings()},server.valid_ticker,
            history_loader=incomplete,opinion_loader=fixture_opinion)


def test_bad_holdings_rejected_before_network():
    bad=[
      [], [{'ticker':'AAPL','shares':0}],
      [{'ticker':'AAPL','shares':1},{'ticker':'AAPL','shares':4}],
      [{'ticker':'MALICIOUS URL','shares':1}],
      [{'ticker':'AAPL','shares':float('nan')}],
      [{'ticker':'SPY','shares':5}],
      [{'ticker':'AAPL','shares':2,'price':-2}],
      [{'ticker':f'T{i}','shares':2} for i in range(21)]
    ]
    for holdings in bad:
        with pytest.raises(ValueError):
            bridge.normalize_holdings(holdings,server.valid_ticker)


def test_absent_unadjusted_quote_aborts_instead_of_using_adjusted_prices():
    raw=[{'ticker':'AAPL','shares':2}]
    with pytest.raises(ValueError,match='Unadjusted valuation quote unavailable'):
        bridge.research_portfolio({'holdings':raw},server.valid_ticker,
            quote_loader=lambda _: {},history_loader=history,opinion_loader=fixture_opinion)



def test_quote_older_than_completed_price_history_fails_closed():
    yesterday=(pd.Timestamp.now(tz='UTC')-pd.Timedelta(days=1)).isoformat()
    holding=[{'ticker':'AAPL','shares':2}]
    with pytest.raises(ValueError,match='older than last completed'):
        bridge.research_portfolio({'holdings':holding},server.valid_ticker,
            quote_loader=lambda _: {'AAPL':{'price':100,'timestamp_utc':yesterday,'source':'TEST ONLY'}},
            history_loader=history,opinion_loader=fixture_opinion)

def test_fewer_stocks_exceed_effective_cash_reserve_due_to_cap():
    payload={'holdings':[{'ticker':'AAPL','shares':5,'price':200},
                         {'ticker':'MSFT','shares':5,'price':200}],
            'cash_reserve':.1,'max_position':.2}
    out=bridge.research_portfolio(payload,server.valid_ticker,history_loader=history,
                                  opinion_loader=fixture_opinion)
    assert out['cash_effective']==pytest.approx(.6)
    assert out['target_exposure']==pytest.approx(.4)


def test_provider_exception_does_not_invent_analyst_opinion():
    out=bridge.research_portfolio({'holdings':good_holdings()},server.valid_ticker,
          history_loader=history,opinion_loader=lambda *args: (_ for _ in ()).throw(ValueError('No feed')))
    assert all(p['analyst_status']=='unavailable' for p in out['positions'])
    assert out['annualized_vol_hypothetical']>=0


def test_sensitive_provider_key_removed_from_errors(monkeypatch):
    monkeypatch.setenv('FINNHUB_API_KEY','private-secret-123')
    s=bridge._safe_provider_error(Exception('Failed https://finnhub.io/api/v1/x?token=private-secret-123'))
    assert 'private-secret-123' not in s and 'finnhub.io' not in s


def test_analyst_snapshots_saved_without_holdings_and_deduplicated(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'DB',tmp_path/'analyst.db')
    snap={'ticker':'AAPL','source':'TEST','observed_at':'2026-11-20T16:00:00+00:00',
          'rating_period':'2026-11-01','rating_counts':{'buy':5},'coverage':5,
          'historical_backtest_eligible':False}
    bridge.record_opinion(snap);bridge.record_opinion(snap)
    with sqlite3.connect(bridge.DB) as c:
        assert c.execute('select count(*) from snapshots').fetchone()[0]==1
        sql=c.execute("select sql from sqlite_master where name='snapshots'").fetchone()[0]
        assert 'shares' not in sql.lower() and 'api_key' not in sql.lower()


def test_stale_analyst_data_does_not_affect_optimistic_weight_tilt():
    from ithaca_quant.analyst_consensus import parse_consensus
    snap=parse_consensus('AAPL',counts={'strongBuy':50},source='TEST',
       observed_at='2020-11-20T11:00:00+00:00',rating_period='2020-11-01')
    def stale(t,validate,provider):
        return {'status':'available','consensus':snap} if t=='AAPL' else fixture_opinion(t,validate,provider)
    out=bridge.research_portfolio({'holdings':good_holdings()},server.valid_ticker,
            history_loader=history,opinion_loader=stale)
    p=next(x for x in out['positions'] if x['ticker']=='AAPL')
    assert p['analyst_shrunk_sentiment']==0


def test_cached_model_is_qualified_only_when_validation_passed():
    good={'state':'available','validation_passed':True,'asof':datetime.now(timezone.utc).date().isoformat(),
          'expected_excess_return':.025}
    bad={'state':'available','validation_passed':False,'asof':datetime.now(timezone.utc).date().isoformat(),
         'expected_excess_return':.9}
    out=bridge.research_portfolio({'holdings':good_holdings()},server.valid_ticker,
        history_loader=history,opinion_loader=fixture_opinion,
        forecasts={'AAPL':good,'MSFT':bad})
    assert out['forecast_tilt_qualified_count']==1
    assert next(p for p in out['positions'] if p['ticker']=='MSFT')['forecast_tilt']==0


def test_http_origin_and_json_size_protection(monkeypatch):
    from http.server import ThreadingHTTPServer
    from urllib.parse import urlparse
    service=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    server_thread=Thread(target=service.serve_forever,daemon=True)
    server_thread.start()
    url=f'http://127.0.0.1:{service.server_port}'
    good_origin='chrome-extension://'+'a'*32
    try:
        with urlopen(url+'/health',timeout=4) as r:
            h=json.load(r)
        assert h['version']=='0.6' and h['upstream_model']=='3.2.0'
        payload=json.dumps({'holdings':good_holdings()}).encode()
        request=Request(url+'/portfolio/study',data=payload,method='POST',headers={'Origin':'https://stranger.example','Content-Type':'application/json'})
        with pytest.raises(HTTPError) as e:urlopen(request,timeout=5)
        assert e.value.code==403
        monkeypatch.setattr(server,'research_portfolio',lambda *a,**kw:{'status':'test-only','orders_placed':False})
        request=Request(url+'/portfolio/study',data=payload,method='POST',headers={'Origin':good_origin,'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as r: resp=json.load(r)
        assert resp['status']=='test-only'
        request=Request(url+'/portfolio/study',data=b'{}',method='POST',headers={'Origin':good_origin,'Content-Type':'text/plain'})
        with pytest.raises(HTTPError) as e:urlopen(request,timeout=5)
        assert e.value.code==415
        request=Request(url+'/portfolio/study',data=b'a'*8193,method='POST',headers={'Origin':good_origin,'Content-Type':'application/json'})
        with pytest.raises(HTTPError) as e:urlopen(request,timeout=5)
        assert e.value.code==413
    finally:
        service.shutdown();service.server_close();server_thread.join(timeout=5)
