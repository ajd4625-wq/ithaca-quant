"""SEC delisting evidence must not become made-up stock prices or payoffs."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile
import json
import pandas as pd
import pytest

from ithaca_quant.delisted_history import (
    extract_sec_events, build_sec_register, load_sec_register,
    audit_delisting_coverage, iter_bulk_submissions)
from ithaca_quant.historical_archive import HistoricalBundle
from ithaca_quant.data import MarketData


def filings(form, date, accession):
    return {'form':form,'filingDate':date,'accessionNumber':accession}


def submission():
    return {'cik':123456, 'name':'Test company', 'tickers':['TCST'],
            'filings':{'recent':filings(['10-K','25-NSE','15-12G'],
                ['2025-03-01','2025-04-01','2025-05-01'],
                ['0000123456-25-000001','0000123456-25-000002','0000123456-25-000003']),
                'files':[{'name':'CIK0000123456-submissions-001.json','filingFrom':'2000-01-01'}]}}


def sample_bundle(multiple_classes=False, missing_price=False, terminal=False):
    dates = pd.to_datetime(['2025-03-31','2025-04-01','2025-04-02'])
    close = pd.DataFrame({'SPY':[500,501,502],'SEC001':[5,5.1,5.2]},index=dates)
    if missing_price: close['SEC001']=float('nan')
    if multiple_classes: close['SEC002']=[12,11.8,11.9]
    vol = close.copy();vol[:]=100
    market=MarketData(close,vol,'synthetic-test',[],raw_close=close.copy())
    master=pd.DataFrame({'security_id':['SPY','SEC001']+(['SEC002'] if multiple_classes else []),
                         'ticker':['SPY','TCST']+(['TCST.B'] if multiple_classes else []),
                         'cik':['',123456]+([123456] if multiple_classes else []),
                         'valid_from':pd.to_datetime(['2010-01-01','2020-01-01']+(['2020-01-01'] if multiple_classes else []))})
    terminals=pd.DataFrame({'ticker':['SEC001'],'event_date':pd.to_datetime(['2025-04-02'])}) if terminal else None
    return HistoricalBundle(market,pd.DataFrame(),terminals,master,{}, {},'abc')


def test_distinguish_exchange_delisting_from_deregistration():
    events=extract_sec_events(submission())
    assert len(events)==2
    assert [e['event_category'] for e in events]==['EXCHANGE_DELISTING_FILING','SEC_DEREGISTRATION_FILING']
    assert all(e['older_filings_missing'] for e in events)
    assert events[0]['cik']=='0000123456'
    assert events[0]['filing_date']=='2025-04-01'  # NOT inferred market effective date
    assert events[0]['filing_url'].endswith('/000012345625000002/')
    assert 'terminal_return' not in events[0]
    assert 'ticker' not in events[0]  # no guesses from currently reported ticker


def test_older_filing_pages_are_not_silently_included():
    item=submission()
    older=filings(['25'],['2005-01-03'],['0000123456-05-000002'])
    assert len(extract_sec_events(item,older_parts=[older]))==3
    assert all(not ev['older_filings_missing'] for ev in extract_sec_events(item,older_parts=[older]))


def test_reject_bad_sec_record():
    item=submission()
    item['filings']['recent']['accessionNumber']=['short']
    with pytest.raises(ValueError):extract_sec_events(item)


def test_sec_bulk_stream_only_expected_paths(tmp_path):
    zpath=tmp_path/'submissions.zip'
    with ZipFile(zpath,'w') as z: z.writestr('CIK0000123456.json',json.dumps(submission()))
    assert len(list(iter_bulk_submissions(zpath)))==1
    with ZipFile(zpath,'w') as z: z.writestr('../evil.json',json.dumps(submission()))
    with pytest.raises(ValueError,match='Unexpected filename'):
        list(iter_bulk_submissions(zpath))


def test_build_register_checksums_and_provenance(tmp_path):
    result=build_sec_register([submission()],tmp_path,input_reference='SEC official bulk snapshot',collection_complete=True)
    assert result['events_total']==2
    assert result['form25_events']==1
    assert result['form15_deregistration_events']==1
    assert not result['older_filing_histories_complete']
    assert not result['complete_us_delisted_stock_dataset']
    assert len(load_sec_register(tmp_path))==2
    (tmp_path/'sec_delisting_events.csv').write_text('hacked')
    with pytest.raises(ValueError,match='checksum'):
        load_sec_register(tmp_path)


def test_coverage_marks_price_and_payoff_gaps(tmp_path):
    build_sec_register([submission()],tmp_path,input_reference='SEC')
    frame,totals=audit_delisting_coverage(sample_bundle(missing_price=True),load_sec_register(tmp_path))
    assert totals['form25_without_archived_price_history']==1
    assert totals['form25_without_any_documented_terminal_payoff']==1
    assert not totals['survivorship_bias_eliminated']
    assert frame.loc[frame.form.eq('15-12G'),'status'].iat[0]=='DEREGISTRATION_ONLY_NOT_DELISTING_PROOF'


def test_cik_multiple_classes_not_security_specific(tmp_path):
    build_sec_register([submission()],tmp_path,input_reference='SEC')
    frame,totals=audit_delisting_coverage(sample_bundle(multiple_classes=True),load_sec_register(tmp_path))
    event=frame.loc[frame.form.eq('25-NSE')].iloc[0]
    assert event.status=='MULTIPLE_CLASSES_SECURITY_EVENT_UNRESOLVED'
    assert not event.matched_security_id
    assert totals['form25_without_single_security_match']==1


def test_one_terminal_record_does_not_claim_complete_outcome(tmp_path):
    build_sec_register([submission()],tmp_path,input_reference='SEC')
    _, totals=audit_delisting_coverage(sample_bundle(terminal=True),load_sec_register(tmp_path))
    assert totals['form25_without_any_documented_terminal_payoff']==0
    assert totals['delisting_investment_outcomes_complete'] is False


def test_missing_cik_crosswalk_blocks_audit(tmp_path):
    build_sec_register([submission()],tmp_path,input_reference='SEC')
    bundle=sample_bundle()
    bundle.security_master=bundle.security_master.drop(columns=['cik'])
    with pytest.raises(ValueError, match='CIK'):
        audit_delisting_coverage(bundle,load_sec_register(tmp_path))


def test_fetch_older_sec_pages_and_cache(tmp_path):
    from scripts.build_delisting_register import fetch_older_filings
    class Reply:
        content=json.dumps(filings(['25'],['2005-02-01'],['0000123456-05-000002'])).encode()
        def raise_for_status(self): pass
        def json(self):return json.loads(self.content)
    class Session:
        def __init__(self):self.calls=0
        def get(self, url, **kwargs):
            assert 'CIK0000123456-submissions-001.json' in url
            assert 'User-Agent' in kwargs['headers']
            self.calls+=1
            return Reply()
    session=Session()
    records=fetch_older_filings(submission(),contact='research@example.org',cache=tmp_path,pause=0,session=session)
    assert len(records)==1 and session.calls==1
    records=fetch_older_filings(submission(),contact='research@example.org',cache=tmp_path,pause=0,session=session)
    assert len(records)==1 and session.calls==1

def test_register_with_fetched_older_parts_is_marked_complete(tmp_path):
    from scripts.build_delisting_register import with_older_filing_pages
    item=submission()
    item['__ithaca_older_parts']=[filings(['25'],['2005-02-01'],['0000123456-05-000002'])]
    result=build_sec_register([item],tmp_path,input_reference='fixture',
                              collection_complete=True,older_parts_complete=True)
    assert result['older_filing_histories_complete']
    assert result['events_total']==3
    assert result['complete_us_delisted_stock_dataset'] is False
