"""Integration safeguards for historical analyst capture and portfolio research."""
from datetime import datetime, timedelta, timezone
import sys
import types
import numpy as np
import pandas as pd
import pytest
from ithaca_quant.analyst_consensus import parse_consensus, is_fresh, snapshot_to_row, fetch_yahoo, fetch_finnhub
from ithaca_quant.portfolio_advisor import portfolio_allocation_study, _cap_normalize

NOW=datetime(2026,11,20,15,30,tzinfo=timezone.utc)


def sample(ticker='AAA', n=10, seen=NOW):
    return parse_consensus(ticker,counts={'strongBuy':2,'buy':n-2,'hold':0,'sell':0,'strongSell':0},
                           targets={'mean':125,'low':80,'high':140},
                           source='fixture (not real)', observed_at=seen.isoformat(),rating_period='2026-11-01')


def prices(n=260):
    rng=np.random.default_rng(114)
    dates=pd.bdate_range('2025-11-20',periods=n)
    ret=rng.normal(.0003,.013,(n,5))
    return pd.DataFrame(100*np.cumprod(1+ret,axis=0),index=dates,
                        columns=['AAA','BBB','CCC','DDD','EEE'])


def test_normalize_consensus_and_retrieval_provenance():
    row=sample()
    assert row['coverage']==10
    assert row['shrunk_sentiment']>0
    assert row['historical_backtest_eligible'] is False
    assert snapshot_to_row(row,100)['Target vs latest quote']==.25


def test_missing_coverage_no_fake_neutral():
    snap=sample(n=2)
    assert snap['shrunk_sentiment'] is None
    assert parse_consensus('BBB',counts={},source='fixture',observed_at=NOW.isoformat())['shrunk_sentiment'] is None


@pytest.mark.parametrize('count', [-1, 2.5, float('nan')])
def test_invalid_analyst_counts_rejected(count):
    with pytest.raises(ValueError):
        parse_consensus('AAPL',counts={'buy':count},source='a',observed_at=NOW.isoformat())


def test_bad_price_target_rejected():
    with pytest.raises(ValueError):
        parse_consensus('AAPL',counts={'buy':10},targets={'low':200,'high':100},
                        source='a', observed_at=NOW.isoformat())


def test_stale_analysts_ignored():
    assert is_fresh(sample(), at=NOW)
    assert not is_fresh(sample(seen=NOW-timedelta(days=8)), at=NOW)
    assert not is_fresh(sample(seen=NOW+timedelta(hours=2)), at=NOW)


def test_waterfill_constraints():
    x=_cap_normalize([2,1,1,1,1],.90,.25)
    assert sum(x)==pytest.approx(.90)
    assert x.max()<=.25000001


def test_portfolio_study_limited_allocation_and_no_auto_trades():
    current={x:.15 for x in prices().columns}
    forecasts={'AAA':{'asof':NOW.date().isoformat(),'forecast_excess':.10},
               'BBB':{'asof':'2024-01-02','forecast_excess':.50}}
    snaps={'AAA':sample(), 'BBB':sample('BBB',seen=NOW-timedelta(days=10))}
    result=portfolio_allocation_study(prices(),current,forecasts,snaps,as_of=NOW)
    assert sum(result.targets.values())==pytest.approx(.9,abs=1e-5)
    assert max(result.targets.values())<=.250001
    assert result.forecast_signal['BBB']==0
    assert result.analyst_signal['BBB']==0
    assert result.analyst_signal['AAA']>0
    assert result.annualized_vol_research>0
    assert result.predicted_turnover_fraction>=0


def test_concentrated_underfilled_portfolio_keeps_rest_in_cash():
    p=prices()[['AAA','BBB']]
    result=portfolio_allocation_study(p,{'AAA':.55,'BBB':.35},as_of=NOW)
    assert sum(result.targets.values())==pytest.approx(.5)
    assert max(result.targets.values())<=.25+1e-6


def test_missing_historical_bars_fail_closed():
    p=prices();p.loc[p.index[-3],'AAA']=np.nan
    with pytest.raises(ValueError,match='Incomplete'):
        portfolio_allocation_study(p,{x:.15 for x in p},as_of=NOW)


def test_insufficient_history_rejected():
    p=prices().tail(90)
    with pytest.raises(ValueError,match='126'):
        portfolio_allocation_study(p,{x:.15 for x in p},as_of=NOW)


def test_high_or_invalid_cash_reserve_rejected():
    p=prices()
    with pytest.raises(ValueError):
        portfolio_allocation_study(p,{'AAA':.2},cash_reserve=1.,as_of=NOW)


def test_finnhub_adapter_uses_latest_period_without_backtest_eligibility(monkeypatch):
    calls=[]
    class Resp:
        def __init__(self,val): self.val=val
        def raise_for_status(self):pass
        def json(self):return self.val
    def get(url,params,timeout):
        calls.append((url,params,timeout))
        assert params['token']=='secret'
        if url.endswith('recommendation'):
            return Resp([{'period':'2026-10-01','buy':3}, {'period':'2026-11-01','buy':7,'hold':2}])
        return Resp({'targetMean':123})
    monkeypatch.setitem(sys.modules,'requests',types.SimpleNamespace(get=get,RequestException=Exception))
    x=fetch_finnhub('AAA','secret')
    assert x['coverage']==9
    assert x['price_targets']['mean']==123
    assert x['historical_backtest_eligible'] is False
    assert len(calls)==2


def test_yahoo_uses_only_current_month(monkeypatch):
    class T:
        def __init__(self,sym):pass
        def get_recommendations_summary(self):
            return pd.DataFrame([{'period':'-1m','buy':100},{'period':'0m','buy':6,'hold':1}])
        def get_analyst_price_targets(self):return {'mean':120}
    monkeypatch.setitem(sys.modules,'yfinance',types.SimpleNamespace(Ticker=T))
    x=fetch_yahoo('AAA')
    assert x['coverage']==7
    assert x['price_targets']['mean']==120


def test_yahoo_attributed_actions(monkeypatch):
    from ithaca_quant.analyst_consensus import fetch_yahoo_actions
    moment=pd.Timestamp.now(tz='UTC')
    class T:
        def __init__(self,sym):pass
        def get_upgrades_downgrades(self):
            return pd.DataFrame([{'Firm':'Example Securities','Action':'up',
                                  'FromGrade':'Hold','ToGrade':'Buy'},
                                 {'Firm':'Old Firm','Action':'down','FromGrade':'Buy','ToGrade':'Sell'}],
                       index=[moment-pd.Timedelta(days=2),moment-pd.Timedelta(days=180)])
    monkeypatch.setitem(sys.modules,'yfinance',types.SimpleNamespace(Ticker=T))
    rows=fetch_yahoo_actions('AAA')
    assert len(rows)==1
    assert rows[0]['Analyst firm']=='Example Securities'
    assert rows[0]['New grade']=='Buy'


def test_finnhub_attributed_action_date_filter(monkeypatch):
    from ithaca_quant.analyst_consensus import fetch_finnhub_actions
    now=int(datetime.now(timezone.utc).timestamp())
    class Resp:
        def raise_for_status(self):pass
        def json(self):return [
            {'gradeTime':now-86400,'company':'Research Firm','fromGrade':'Hold','toGrade':'Buy','action':'up'},
            {'gradeTime':now-200*86400,'company':'Old Firm','toGrade':'Buy','action':'up'}]
    monkeypatch.setitem(sys.modules,'requests',types.SimpleNamespace(get=lambda *a,**kw:Resp()))
    assert len(fetch_finnhub_actions('AAA','token',days=90))==1


def test_old_ratings_fetched_today_do_not_affect_optimizer():
    old=parse_consensus('AAA',counts={'buy':20},targets={},source='Finnhub',
                        observed_at=NOW.isoformat(),rating_period='2025-04-01')
    assert not is_fresh(old,at=NOW)
    current={x:.14 for x in prices().columns}
    result=portfolio_allocation_study(prices(),current,analyst_snapshots={'AAA':old},as_of=NOW)
    assert result.analyst_signal['AAA']==0
