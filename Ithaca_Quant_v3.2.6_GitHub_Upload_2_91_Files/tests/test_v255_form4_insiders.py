"""Offline SEC Form 4 parsing, access, and interpretation safeguards."""
from datetime import date
import json
import pytest

from ithaca_quant.insider_form4 import (
    SECUnavailable, parse_ownership_xml, deduplicate_amendments, xml_documents,
    parse_atom_filings, summarize_insider_activity, fetch_form4_ticker,
)

OWNERSHIP = b'''<?xml version="1.0"?>
<ownershipDocument>
  <documentType>4</documentType>
  <issuer><issuerCik>0000123456</issuerCik><issuerName>Example Inc</issuerName><issuerTradingSymbol>EXAM</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerName>Chris Executive</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>0</isOfficer></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction><transactionDate><value>2026-11-18</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>2000</value></transactionShares>
        <transactionPricePerShare><value>42.50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction><transactionDate><value>2026-11-18</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>50</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction><transactionDate><value>2026-11-18</value></transactionDate>
      <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>500</value></transactionShares>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable><derivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding></derivativeTransaction></derivativeTable>
</ownershipDocument>'''


def test_parse_non_derivative_purchases_sales_not_grants():
    rows = parse_ownership_xml(OWNERSHIP, expected_cik=123456, ticker='EXAM',
                               filing_date='2026-11-19', filing_url='https://www.sec.gov/Archives/edgar/data/x')
    assert [r['type'] for r in rows] == ['Purchase', 'Sale']
    assert rows[0]['value_usd'] == 85000
    assert rows[0]['owner'] == 'Chris Executive'
    assert rows[0]['role'] == 'Director'
    assert rows[0]['trade_date'] != rows[0]['filed_date']
    assert parse_ownership_xml(OWNERSHIP, expected_cik=999, ticker='EXAM',
                                filing_date='2026-11-19', filing_url='test') == []


def test_reject_xml_entities_and_oversized_response():
    with pytest.raises(ValueError):
        parse_ownership_xml(b'<!DOCTYPE x [<!ENTITY x "foo">]><ownershipDocument/>',
                            expected_cik=123456, ticker='EXAM', filing_date='', filing_url='')
    with pytest.raises(ValueError):
        parse_atom_filings(b' ' * 3_000_001)


def test_atom_feed_parses_real_edgar_path_only():
    feed = b'''<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry><title>4 - Example</title>
    <updated>2026-11-19T18:30:00Z</updated>
    <link href="https://www.sec.gov/Archives/edgar/data/123456/000095017026123456/x-20261119-index.htm"/>
    </entry><entry><title>4 - Pretend</title>
    <link href="https://evil.example/Archives/edgar/data/123456/000095017026123456/file.htm"/>
    </entry><entry><title>8-K - Example</title>
    <link href="https://www.sec.gov/Archives/edgar/data/123456/000095017026888888/x.htm"/></entry></feed>'''
    found = parse_atom_filings(feed)
    assert len(found) == 1
    assert found[0]['accession'] == '000095017026123456'
    assert found[0]['filing_date'] == '2026-11-19'
    assert found[0]['filing_url'].endswith('x-20261119-index.htm')


def test_document_choices_exclude_paths_and_other_files():
    docs = xml_documents({'directory':{'item':[
        {'name':'xslF345X05/form4.xml'}, {'name':'../outside.xml'},
        {'name':'form4.xml'}, {'name':'xslstyles.xml'}, {'name':'notes.txt'}]}})
    assert docs == ['form4.xml']


def test_summaries_distinguish_buys_sales_and_stale_disclosures():
    rows = parse_ownership_xml(OWNERSHIP, expected_cik=123456, ticker='EXAM',
                               filing_date='2026-11-19', filing_url='https://www.sec.gov')
    mixed = summarize_insider_activity(rows, today=date(2026, 11, 19))
    assert mixed['color'] == 'YELLOW' and mixed['purchases'] == 1 and mixed['sales'] == 1
    green = summarize_insider_activity(rows[:1], today=date(2026, 11, 19))
    assert green['color'] == 'GREEN'
    assert summarize_insider_activity(rows, today=date(2027, 1, 1))['color'] == 'NEUTRAL'


def test_amended_filing_not_counted_twice():
    row = parse_ownership_xml(OWNERSHIP, expected_cik=123456, ticker='EXAM',
                              filing_date='2026-11-18', filing_url='old')[0]
    newer = {**row, 'filing_url':'new', 'filed_date':'2026-11-19', 'amended':True}
    result = deduplicate_amendments([row, newer])
    assert len(result) == 1 and result[0]['filing_url'] == 'new'


class FakeResponse:
    def __init__(self, data, status_code=200):
        self.content = data
        self.status_code = status_code
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeClient:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append(url)
        data = self.payloads[url]
        return FakeResponse(data)


def test_entire_sec_fetch_pipeline_and_isolation():
    acc = '000095017026123456'
    atom = f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>4 - Example</title>
      <updated>2026-11-19T10:00:00Z</updated><link href="https://www.sec.gov/Archives/edgar/data/123456/{acc}/abc-index.htm"/></entry></feed>'''.encode()
    base = f'https://www.sec.gov/Archives/edgar/data/123456/{acc}'
    client = FakeClient({
        'https://www.sec.gov/cgi-bin/browse-edgar':atom,
        base+'/index.json':json.dumps({'directory':{'item':[{'name':'form4.xml'}]}}).encode(),
        base+'/form4.xml':OWNERSHIP,
    })
    mapping = {'0': {'ticker':'EXAM', 'cik_str':123456, 'title':'Example Inc'}}
    rows = fetch_form4_ticker('EXAM', 'Admin@example.com', directory=mapping, client=client, max_filings=2)
    assert len(rows) == 2 and rows[0]['ticker'] == 'EXAM'
    assert len(client.calls) == 3


def test_ticker_missing_is_explicit_error_not_zero_trades():
    with pytest.raises(ValueError, match='not listed'):
        fetch_form4_ticker('NOTREAL', 'Admin@example.com', directory={'0':{'ticker':'EXAM','cik_str':123456}}, client=FakeClient({}))


def test_insider_tab_precedes_rankings_without_changing_forecast():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    content = (root/'app.py').read_text()
    assert 'search_tab, insider_tab, leaderboard_tab,' in content
    assert 'with insider_tab:' in content
    assert '"🧾 SEC Form 4 Insider Activity", "🏆 Ranked leaderboard"' in content
    assert 'from ithaca_quant.insider_form4 import ticker_directory' in content
