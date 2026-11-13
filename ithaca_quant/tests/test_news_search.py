from datetime import datetime, timezone
import pandas as pd
import pytest
from ithaca_quant.news import headline_score, parse_rss, news_context
from ithaca_quant.search import price_scenarios, review_dates


def test_news_sentiment():
    assert headline_score('Company beats expectations and surges') > 0
    assert headline_score('Company cuts outlook and falls') < 0


def test_rss_parsing():
    xml = b'<rss><channel><item><title>Company beats earnings</title><link>https://news.google.com/a</link><source>Yahoo Finance</source><pubDate>Wed, 11 Nov 2026 12:00:00 GMT</pubDate></item></channel></rss>'
    rows = parse_rss(xml, 'Yahoo Finance')
    assert len(rows) == 1 and rows[0]['published_utc'].tzinfo is not None
    assert parse_rss(xml, 'Fox Business') == []


def test_no_news_not_fabricated():
    assert news_context([])['score'] is None


def test_price_scenarios():
    result = price_scenarios(100, 0.1, pd.Series([1.0]), 0.4, 20)
    assert result['target'] == pytest.approx(110)
    assert result['lower_1sigma'] < 110 < result['upper_1sigma']


def test_review_dates():
    d = review_dates(pd.Timestamp('2026-11-12'), 20, 'WAIT', 'MONITOR')
    assert str(d['entry_review']) == '2026-11-13'
    assert d['entry_condition'] == 'WAIT'
