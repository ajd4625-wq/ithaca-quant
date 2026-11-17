"""Offline tests for discovery, ranking shortlist and quote parsing."""
import pandas as pd
import numpy as np
import pytest

from ithaca_quant.universe import parse_directory, pick_scan_symbols, screen_candidates
from ithaca_quant.quotes import alpaca_iex_quotes, age_minutes


NASDAQ = '''Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
NVDA|NVIDIA Corporation - Common Stock|Q|N|N|100|N|N
TEST|Test Security|Q|Y|N|100|N|N
QQQ|ETF Sample|Q|N|N|100|Y|N
WTEST|ABC Warrants|S|N|N|100|N|N
File Creation Time: 1111202616:00||||||||
'''
OTHER = '''ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
BRK.B|Berkshire Hathaway Class B|N|BRK.B|N|100|N|BRK/B
GE|GE Aerospace|N|GE|N|100|N|GE
ABC.PR|Example Preferred Stock|N|ABC.PR|N|100|N|ABC.PR
BATS|Other Exchange|Z|BATS|N|100|N|BATS
SPY|SPDR ETF|P|SPY|Y|100|N|SPY
File Creation Time: 1111202616:01|||||||
'''


def test_directory_filters_nyse_nasdaq_etfs_test_and_warrants():
    univ = parse_directory(NASDAQ, OTHER)
    assert set(univ.listings.ticker) == {"AAPL", "NVDA", "BRK.B", "GE"}
    assert univ.listings.set_index('ticker').loc['BRK.B', 'data_ticker'] == 'BRK-B'
    assert len(pick_scan_symbols(univ.listings, 2)) == 2
    assert pick_scan_symbols(univ.listings, 2) == pick_scan_symbols(univ.listings, 2)


def test_screen_filters_price_liquidity_short_history():
    days = pd.bdate_range('2026-01-01', periods=190)
    base = np.linspace(80, 120, 190)
    close = pd.DataFrame({'SPY': base, 'AAPL': base * 1.2,
                          'NVDA': base * 1.3, 'CHEAP': base * 0.02,
                          'ILLQ': base * 0.6}, index=days)
    volumes = pd.DataFrame({'SPY': 2e7, 'AAPL': 2e7, 'NVDA': 1e7,
                            'CHEAP': 2e7, 'ILLQ': 1}, index=days)
    results = screen_candidates(close, volumes, limit=10)
    assert set(results.ticker) == {'AAPL', 'NVDA'}
    assert results['avg_dollar_volume'].min() >= 1e6


class FakeResponse:
    status_code = 200
    def raise_for_status(self): pass
    def json(self):
        return {
            'AAPL': {'latestTrade': {'p': 220.5, 't': '2026-11-11T19:32:11Z'},
                     'latestQuote': {'bp': 220.4, 'ap': 220.6}},
            'NVDA': {'latestTrade': {'p': 150.1, 't': '2026-11-11T19:32:11Z'}},
        }


class FakeSession:
    def get(self, url, params, headers, timeout):
        assert params['feed'] == 'iex'
        assert headers['APCA-API-KEY-ID'] == 'k'
        assert 'snapshots' in url
        return FakeResponse()


def test_iex_snapshot_parsing_and_timestamps():
    q = alpaca_iex_quotes(['AAPL', 'NVDA', 'MISS'], 'k', 's', session=FakeSession())
    assert set(q.ticker) == {'AAPL', 'NVDA'}
    assert q.set_index('ticker').loc['AAPL','price'] == 220.5
    assert age_minutes('2026-11-11T19:30:00Z', '2026-11-11T19:45:00Z') == 15
    with pytest.raises(ValueError):
        alpaca_iex_quotes(['AAPL'], '', '')


def test_batched_history_loading_and_missing_symbols(monkeypatch):
    import sys
    from types import SimpleNamespace
    from ithaca_quant.data import download_market_data
    dates = pd.bdate_range('2026-01-01', periods=190, tz='UTC')
    calls = []
    def fake_download(tickers, **kwargs):
        calls.append(list(tickers))
        names = list(tickers)
        if names == ['MISSING']:
            return pd.DataFrame()
        df = pd.DataFrame(index=dates)
        for sym in names:
            if sym == 'MISSING':
                continue
            df[(sym, 'Close')] = np.linspace(100, 140, len(dates))
            df[(sym, 'Volume')] = np.full(len(dates), 1e6)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=fake_download))
    progress = []
    result = download_market_data(['AAPL', 'NVDA', 'MISSING'], years=1,
                                  min_history=140, batch_size=2,
                                  on_progress=lambda n, total, loaded: progress.append(n))
    assert calls == [['SPY', 'AAPL'], ['NVDA', 'MISSING']]
    assert list(result.close.columns) == ['SPY', 'AAPL', 'NVDA']
    assert 'MISSING' in result.excluded
    assert progress == [1, 2]


def test_full_screen_can_include_all_valid_stocks():
    days = pd.bdate_range('2026-01-01', periods=200)
    close = pd.DataFrame({'SPY': np.linspace(100, 105, len(days)),
                          **{f'T{i}': np.linspace(80 + i, 90 + i, len(days)) for i in range(15)}}, index=days)
    volume = pd.DataFrame(2e6, index=days, columns=close.columns)
    broad = screen_candidates(close, volume, limit=None)
    deep = screen_candidates(close, volume, limit=5)
    assert len(broad) == 15 and len(deep) == 5
