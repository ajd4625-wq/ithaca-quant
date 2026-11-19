"""v2.5.2: acquisition coverage, exit triage, no-key screenshot importer."""
from datetime import date, datetime, timezone
from pathlib import Path
from io import BytesIO
import sys
from types import SimpleNamespace
import pandas as pd
import numpy as np
import pytest

from ithaca_quant.leaderboard_review import (exit_review_status, evaluate_candidate,
                                               longer_runup, acquisition_headlines)
from ithaca_quant.portfolio_image import (parse_ocr_holdings_text,
                                           extract_picture_positions_local, confirm_rows)

NOW = date(2026, 11, 19)

def _market():
    dates = pd.bdate_range('2026-07-01', '2026-11-19')
    data = pd.DataFrame({'SPY':np.linspace(100,105,len(dates)),
                         'DEAL':np.linspace(50,51,len(dates))},index=dates)
    data.loc[data.index[-6]:,'DEAL']=[51,55,59,64,68,70]
    return data

def _stock():
    return {'ticker':'DEAL','close':70.,'forecast_excess':.09,
            'prob_gain':.76,'vol_20':.3,'research_score':99,'rank':1}

def _signal(**kwargs):
    return {'entry_watch':'ENTRY WATCH','exit_review':'MONITOR','review_level':55.,
            'ma_gap_20':0.08,**kwargs}

def _news(title='Deal announces acquisition of Partner',days_old=4):
    return {'title':title,'publisher':'Yahoo Finance','url':'https://example.com/deal',
            'published_utc': datetime(2026,11,19,16,tzinfo=timezone.utc)-pd.Timedelta(days=days_old)}


def test_unchecked_leader_cannot_be_dark_green_and_deal_not_top_entry():
    a=evaluate_candidate(_stock(),_signal(),_market(),asof=NOW,horizon=20)
    assert a['color']=='YELLOW' and 'CHASING' in a['signal_label']
    b=evaluate_candidate(_stock(),_signal(),_market(),asof=NOW,horizon=20,
                         articles=[_news()],company='Deal Inc')
    assert b['color']=='YELLOW'
    assert b['entry_priority_score'] < a['entry_priority_score']
    assert b['possible_priced_in']
    assert b['entry_sort_tier']==3


def test_exit_columns_separate_from_entry_and_explain_triggers():
    price=100.
    green=exit_review_status({'forecast_excess':.06},_signal(),price=price)
    assert green['exit_color']=='GREEN'
    caut=exit_review_status({'forecast_excess':-.01},_signal(),price=price)
    assert caut['exit_color']=='YELLOW'
    red=exit_review_status({'forecast_excess':-.03},{'exit_review':'REVIEW EXIT','ma_gap_20':-.03,'review_level':95}, price=90)
    assert red['exit_color']=='RED' and 'review' in red['exit_reason']


def test_45_day_news_lookback_and_no_future_event():
    from ithaca_quant import news
    assert 'lookback_days' in news.fetch_news.__code__.co_varnames
    d=acquisition_headlines([_news(days_old=20),_news(days_old=51),_news(days_old=-1)],
                            'DEAL','Deal Inc',asof=NOW)
    assert len(d)==1


def test_ocr_parser_never_copies_current_market_price_into_cost_basis():
    text='Symbol   Quantity   Last Price   Market Value\nAAOI 2,004 39.63 79,418\nRKLB 500 63.10 31,550'
    draft=parse_ocr_holdings_text(text)
    assert [r['ticker'] for r in draft['positions']]==['AAOI','RKLB']
    assert draft['positions'][0]['shares']==2004
    assert draft['positions'][0]['price'] is None
    assert not draft['positions'][0]['trade_date']
    with pytest.raises(ValueError,match='Row 1'):
        confirm_rows(draft['positions'])


def test_ocr_unlabeled_numbers_are_not_share_counts():
    x=parse_ocr_holdings_text('AAOI 2004 39.63\nTEM 300 75')
    assert x['positions'][0]['shares'] is None
    assert x['positions'][0]['price'] is None


def test_local_screenshot_image_upload_without_api_key(monkeypatch):
    from PIL import Image
    image=Image.new('RGB',(240,100),'white')
    out=BytesIO();image.save(out,format='PNG')
    import pytesseract
    monkeypatch.setattr(pytesseract,'image_to_string',lambda *_args,**_kw:
                        'Ticker Shares Last Price\nAAOI 2,004 39.63')
    draft=extract_picture_positions_local(out.getvalue(),'image/png')
    assert draft['positions'][0]['ticker']=='AAOI'
    assert draft['positions'][0]['shares']==2004
    assert draft['positions'][0]['price'] is None


def test_deployment_includes_local_ocr_and_no_manual_news_button():
    root=Path(__file__).resolve().parents[1]
    app=(root/'app.py').read_text()
    panel=(root/'ithaca_quant/portfolio_workspace.py').read_text()
    assert (root/'packages.txt').read_text().strip()=='tesseract-ocr'
    assert 'pytesseract' in (root/'requirements.txt').read_text()
    assert 'Read screenshot locally' in panel
    assert 'leader_news_fetch' not in app
    assert 'leader_deal_fetch' not in app
