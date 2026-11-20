"""v2.5.3: all-modeled-stocks queued, syndicated events counted once."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.sax.saxutils import escape
import sqlite3
import pandas as pd

from ithaca_quant.news_dedupe import deduplicate_events
from ithaca_quant.news_intelligence import analyze_news
from ithaca_quant.news_archive import archived_features
from ithaca_quant.universe_news import update_universe_news, cached_coverage
from ithaca_quant.leaderboard_review import acquisition_headlines

NOW = datetime(2026,11,19,15,0,tzinfo=timezone.utc)

def story(title, days=0, publisher='Reuters'):
    return {'title':title, 'publisher':publisher, 'published_utc':NOW-timedelta(days=days),
            'url':'https://example.com/news','sentiment':1}

def test_same_acquisition_event_from_five_outlets_only_one_event():
    headlines = [story('Acme to acquire Beta for $2 billion',publisher='Reuters'),
                 story('Acme buys Beta in $2bn deal',publisher='CNBC'),
                 story('Acme acquires Beta in major deal',publisher='Bloomberg'),
                 story('Acme agrees to acquire Beta',publisher='Yahoo Finance'),
                 story('Acme acquisition of Beta announced',publisher='MarketWatch')]
    events = deduplicate_events(headlines,ticker='ACME',company='Acme')
    assert len(events) == 1
    assert events[0]['event_coverage_count'] == 5
    assert len(events[0]['event_sources']) == 5
    report=analyze_news(headlines,'ACME','Acme',now=NOW+timedelta(hours=1))
    assert report['n']==1 and report['source_count']==5
    deals=acquisition_headlines(headlines,'ACME','Acme',asof=NOW.date())
    assert len(deals)==1

def test_different_targets_not_merged_even_same_company_day():
    rows=[story('Acme buys Beta for $2bn'),story('Acme buys Delta for $2bn')]
    assert len(deduplicate_events(rows,ticker='ACME',company='Acme'))==2

def test_different_quarter_reports_remain_separate():
    rows=[story('Acme Q3 earnings revenue beat estimates'),
          story('Acme Q4 earnings revenue beat estimates')]
    assert len(deduplicate_events(rows,company='Acme'))==2

def test_close_headlines_with_same_keywords_not_automatically_merged():
    rows=[story('Acme announces beta product launch and new mobile app'),
          story('Acme announces delta product launch and new mobile app')]
    # Shared generic words do not prove independent launches are the same event.
    assert len(deduplicate_events(rows,company='Acme'))==2

def test_news_batch_covers_all_companies_over_multiple_runs_and_caches(tmp_path):
    path=tmp_path/'news.db'
    calls=[]
    tickers=[(f'STOCK{i}','Acme Incorporated') for i in range(53)]
    def fetch(ticker,company):
        calls.append(ticker)
        return [story('Acme announces revenue results')], []
    first=update_universe_news(tickers, fetcher=fetch, batch_size=24, now=NOW, path=path)
    assert first['done']==24 and first['total']==53
    second=update_universe_news(tickers,fetcher=fetch,batch_size=24,now=NOW,path=path)
    third=update_universe_news(tickers,fetcher=fetch,batch_size=24,now=NOW,path=path)
    assert [x['done'] for x in [first,second,third]]==[24,48,53]
    assert len(calls)==53
    again=update_universe_news(tickers,fetcher=fetch,now=NOW,path=path)
    assert again['done']==53 and len(calls)==53
    saved,_errors,_ = cached_coverage([x[0] for x in tickers],now=NOW,path=path)
    assert len(saved)==53

def test_failed_fetch_not_treated_as_checked_and_retry_delayed(tmp_path):
    path=tmp_path/'news.db'; calls=[]
    def broken(ticker,company):
        calls.append(ticker)
        return [], ['HTTP 429']
    one=update_universe_news([('ACME','Acme')],fetcher=broken,now=NOW,path=path)
    two=update_universe_news([('ACME','Acme')],fetcher=broken,now=NOW+timedelta(minutes=5),path=path)
    assert one['done']==two['done']==0 and len(calls)==1
    three=update_universe_news([('ACME','Acme')],fetcher=broken,now=NOW+timedelta(minutes=16),path=path)
    assert len(calls)==2 and three['errors']

def test_old_names_are_not_trusted_if_ticker_metadata_changes(tmp_path):
    path=tmp_path/'news.db'; calls=[]
    def fetch(ticker,company):
        calls.append(company)
        return [], []
    update_universe_news([('ACME','Acme Inc')],fetcher=fetch,now=NOW,path=path)
    update_universe_news([('ACME','Acme New Name')],fetcher=fetch,now=NOW,path=path)
    assert calls==['Acme Inc','Acme New Name']

def test_historical_syndication_is_one_training_event():
    rows=pd.DataFrame([
        {'published_utc':NOW-timedelta(days=3),'first_seen_utc':NOW-timedelta(days=3),
         'title':'Acme to acquire Beta','publisher':'Reuters','relevance':1.,'sentiment':1.},
        {'published_utc':NOW-timedelta(days=3),'first_seen_utc':NOW-timedelta(days=3),
         'title':'Acme buys Beta','publisher':'CNBC','relevance':1.,'sentiment':1.},
    ])
    sessions=pd.to_datetime(['2026-11-23'],utc=True)
    f=archived_features('ACME',sessions,headlines=rows)
    assert f['news_count_7d'].iloc[0] == 1/30

def test_ui_uses_periodic_fragment_and_no_top_12_cap():
    source=(Path(__file__).resolve().parents[1]/'app.py').read_text()
    assert '@st.fragment(run_every="60s")' in source
    assert 'update_universe_news(news_items)' in source
    assert 'min(12, len(leaders))' not in source
    assert 'cached at top 12' not in source
