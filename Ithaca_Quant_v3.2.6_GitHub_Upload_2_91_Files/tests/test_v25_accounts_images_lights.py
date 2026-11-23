"""v2.5 account isolation, screenshot import safeguards, and traffic lights."""
from datetime import date, timedelta
from pathlib import Path
import importlib
import io
import re
import sys
from types import SimpleNamespace

import pytest

from ithaca_quant import holdings
from ithaca_quant.account_auth import account_access_code, claims_from_user
from ithaca_quant.portfolio_image import (clean_draft, confirm_rows, extract_picture_positions,
                                          SYSTEM_INSTRUCTION)
from ithaca_quant.portfolio_lights import classify_holding


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv('ITHACA_DATABASE_URL','sqlite:///'+str(tmp_path/'v25.sqlite3'))
    holdings._tables.cache_clear()
    yield
    holdings._tables.cache_clear()


def test_oidc_identity_is_stable_isolated_private_and_valid(db):
    secret='long-private-server-secret-value-stays-stable-across-deploys'
    a=account_access_code('google-user-1','https://accounts.google.com',secret)
    b=account_access_code('google-user-2','https://accounts.google.com',secret)
    c=account_access_code('google-user-1','https://other.example',secret)
    assert a==account_access_code('google-user-1','https://accounts.google.com',secret)
    assert len({a,b,c})==3 and all(re.fullmatch('IQ-[A-Za-z0-9_-]{32}',x) for x in (a,b,c))
    assert 'google-user-1' not in a
    holdings.create_portfolio(a);holdings.create_portfolio(b)
    holdings.add_trade(a,'AAOI','BUY',2004,46.93,'2026-11-16')
    assert len(holdings.get_trades(a))==1
    assert holdings.get_trades(b)==[]
    assert not holdings.portfolio_exists(c)
    with pytest.raises(ValueError):
        account_access_code('google-user-1','https://accounts.google.com','too-short')
    with pytest.raises(ValueError):
        account_access_code('','https://accounts.google.com',secret)


def test_claims_requires_verified_identity():
    class MockUser(dict):
        is_logged_in=True
    assert claims_from_user(MockUser(sub='sub123',iss='https://auth.example'))==('sub123','https://auth.example')
    with pytest.raises(ValueError):
        claims_from_user(SimpleNamespace(is_logged_in=False))


def test_picture_extract_is_draft_not_saved_and_leaves_unknowns_empty(db):
    payload={'positions':[{'ticker':'aaoi','shares':'2,004','purchase_price':None,
                           'trade_date':None,'confidence':'medium', 'market_price':'39.63'},
                          {'ticker':'GNRC','shares':50,'purchase_price':189.50,'trade_date':'2026-11-16'}],
             'notes':['Screenshot only lists a current price, not cost basis.']}
    draft=clean_draft(payload)
    assert len(draft['positions'])==2
    first=draft['positions'][0]
    assert first['ticker']=='AAOI' and first['shares']==2004 and first['price'] is None
    assert first['trade_date']==''
    with pytest.raises(ValueError,match='Row 1'):
        confirm_rows(draft['positions'])
    first['price']=46.93
    first['trade_date']='2026-11-16'
    trades=confirm_rows(draft['positions'])
    assert len(trades)==2 and trades[0]['price']==46.93
    assert 'never current/last/market price' in SYSTEM_INSTRUCTION
    key=holdings.new_access_code();holdings.create_portfolio(key)
    assert len(holdings.get_trades(key))==0
    assert holdings.import_trades(key,trades)==2
    assert holdings.calculate_positions(holdings.get_trades(key),{'AAOI':39.63,'GNRC':190})['holdings'][0]['shares']==2004


def test_image_safety_validation_and_untrusted_payload():
    for bad in ({'positions':'not-list'},{}, {'positions':[{'ticker':'$$$'}]*101}):
        with pytest.raises(ValueError): clean_draft(bad)
    with pytest.raises(ValueError):
        extract_picture_positions(b'123','image/bmp','fake')
    with pytest.raises(ValueError):
        extract_picture_positions(b'abc','image/png','')
    with pytest.raises(ValueError):
        extract_picture_positions(b'a'*(8*1024*1024+1),'image/png','fake')
    with pytest.raises(ValueError):
        confirm_rows([{'ticker':'TEM','shares':10,'price':20,'trade_date':'2999-01-01'}])


def test_vision_api_called_only_when_explicitly_requested(monkeypatch):
    result={'positions':[{'ticker':'TEM','shares':12,'purchase_price':65.25,'trade_date':None}], 'notes':[]}
    class Responses:
        def create(self,**kw):
            assert kw['store'] is False
            assert kw['model']=='gpt-4.1-mini'
            assert kw['input'][0]['content'][1]['type']=='input_image'
            assert kw['input'][0]['content'][1]['image_url'].startswith('data:image/png;base64,')
            return SimpleNamespace(output_text=__import__('json').dumps(result))
    class FakeOpenAI:
        def __init__(self,**kw):
            assert kw['api_key']=='server-key'
            self.responses=Responses()
    monkeypatch.setitem(sys.modules,'openai',SimpleNamespace(OpenAI=FakeOpenAI))
    assert extract_picture_positions(b'valid-looking-image-bytes','image/png','server-key')['positions'][0]['price']==65.25


def test_lights_never_green_on_stale_or_missing_data():
    today=date(2026,11,18)
    fresh={'asof':'2026-11-17','forecast_excess':0.08,'prob_gain':0.68,
           'entry_watch':'ENTRY WATCH', 'exit_review':'MONITOR'}
    assert classify_holding(fresh,today=today)['color']=='GREEN'
    assert classify_holding(fresh,today=today,quote_available=False)['color']=='YELLOW'
    assert classify_holding(fresh,today=today,position_weight=0.30)['color']=='YELLOW'
    assert classify_holding({**fresh,'prob_gain':None},today=today)['color']=='GREEN'
    assert classify_holding({**fresh,'asof':'2026-11-01'},today=today)['color']=='YELLOW'
    assert classify_holding(None,today=today)['color']=='YELLOW'
    assert classify_holding({**fresh,'exit_review':'REVIEW EXIT'},today=today)['color']=='RED'
    assert classify_holding({**fresh,'forecast_excess':-0.035},today=today)['color']=='RED'
    assert 'not an automatic sale' in classify_holding({**fresh,'exit_review':'REVIEW EXIT'},today=today)['reason']


def test_new_workspace_wired_to_picture_login_and_status():
    source=(Path(__file__).resolve().parents[1]/'ithaca_quant'/'portfolio_workspace.py').read_text()
    assert 'st.login()' in source and 'st.logout()' in source
    assert '_picture_import_panel(code)' in source
    assert 'classify_holding(' in source
    assert 'Confirm and save reviewed purchases' in source
    assert 'st.data_editor(' in source
    assert '🟢 Entry watch' in source


def test_screenshot_import_cannot_be_repeated_after_reopening(db):
    fingerprint = 'a'*64
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    row={'ticker':'AAOI','side':'BUY','shares':2004,'price':46.93,
         'trade_date':'2026-11-16','fees':0.0}
    assert holdings.import_trades(key,[row],source_hash=fingerprint)==1
    engine,*_=holdings.tables()
    engine.dispose(); holdings._tables.cache_clear()
    with pytest.raises(ValueError,match='already been imported'):
        holdings.import_trades(key,[row],source_hash=fingerprint)
    assert len(holdings.get_trades(key))==1
    # Another account may import the same screenshot once; ownership remains isolated.
    other=holdings.new_access_code();holdings.create_portfolio(other)
    assert holdings.import_trades(other,[row],source_hash=fingerprint)==1


def test_entry_exit_signals_are_real_and_exit_takes_priority():
    today=date(2026,11,18)
    fresh={'asof':'2026-11-18','forecast_excess':0.09,'entry_watch':'ENTRY WATCH',
           'exit_review':'MONITOR','model_price':100.,'review_level':91.}
    result=classify_holding(fresh,today=today,latest_price=98)
    assert result['color']=='GREEN' and 'ENTRY WATCH' in result['label']
    assert classify_holding({**fresh,'entry_watch':'WATCH / CONFIRM'},today=today)['color']=='YELLOW'
    assert classify_holding({**fresh,'entry_watch':'WAIT'},today=today)['color']=='YELLOW'
    assert classify_holding({**fresh,'entry_watch':None},today=today)['color']=='YELLOW'
    red=classify_holding({**fresh,'exit_review':'REVIEW EXIT'},today=today)
    assert red['color']=='RED' and 'automatic sale' in red['reason']
    assert classify_holding(fresh,today=today,latest_price=90)['color']=='RED'
    assert classify_holding(fresh,today=today,latest_price=40)['color']=='YELLOW'  # adjusted/split quote
    assert classify_holding({**fresh,'forecast_excess':-0.025},today=today)['color']=='RED'


def test_entry_signal_persists_and_old_sqlite_schema_migrates(tmp_path, monkeypatch):
    import sqlite3
    path=tmp_path/'legacy.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE iq_private_forecasts (
            owner_hash VARCHAR(64), ticker VARCHAR(16), horizon VARCHAR(8),
            asof VARCHAR(10) NOT NULL, updated_utc VARCHAR(50) NOT NULL,
            forecast_excess FLOAT NOT NULL, prob_gain FLOAT, prob_boom FLOAT,
            vol_20 FLOAT, model_price FLOAT, review_level FLOAT,
            exit_review VARCHAR(60), selected_model VARCHAR(100),
            PRIMARY KEY(owner_hash,ticker,horizon))""")
    monkeypatch.setenv('ITHACA_DATABASE_URL', 'sqlite:///'+str(path))
    holdings._tables.cache_clear()
    try:
        key=holdings.new_access_code(); holdings.create_portfolio(key)
        data={'asof':'2026-11-18','forecast_excess':0.035, 'entry_watch':'ENTRY WATCH',
              'exit_review':'MONITOR','model_price':100,'review_level':90}
        holdings.save_forecast(key,'GNRC',20,data)
        assert holdings.get_forecasts(key,20)['GNRC']['entry_watch']=='ENTRY WATCH'
        holdings._tables.cache_clear()
        assert holdings.get_forecasts(key,20)['GNRC']['entry_watch']=='ENTRY WATCH'
    finally:
        holdings._tables.cache_clear()


def test_entry_signal_is_saved_from_forecasting_pipeline():
    source=(Path(__file__).resolve().parents[1]/'ithaca_quant'/'portfolio_workspace.py').read_text()
    assert "entry_watch=signal.get('entry_watch')" in source
    assert "'Entry signal':" in source


def test_dataframe_cells_have_explicit_signal_colors():
    from ithaca_quant.portfolio_workspace import _signal_cell_style
    assert '#dcfce7' in _signal_cell_style('🟢 ENTRY WATCH')
    assert '#fef3c7' in _signal_cell_style('🟡 WATCH / CONFIRM')
    assert '#fee2e2' in _signal_cell_style('🔴 REVIEW EXIT')
