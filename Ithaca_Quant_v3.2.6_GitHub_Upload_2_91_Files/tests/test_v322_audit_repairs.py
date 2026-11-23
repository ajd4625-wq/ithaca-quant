"""Offline, deterministic regressions for v3.2.2, NOT real-market validation."""
from datetime import datetime, timezone
import sys
import types

import numpy as np
import pandas as pd
import pytest

from ithaca_quant.data import MarketData, download_market_data
from ithaca_quant.incremental import completed_daily_only, merge_market, refresh_market
from ithaca_quant.market_cache import config_key, load_market, save_market
from ithaca_quant.features import build_panel
from ithaca_quant.portfolio_advisor import portfolio_allocation_study
from ithaca_quant.universe import screen_candidates

NOW = datetime(2026, 11, 20, 17, tzinfo=timezone.utc)


def sample_bars(days=260):
    dates = pd.bdate_range('2025-10-01', periods=days)
    p = pd.DataFrame({'SPY': np.linspace(95, 112, days),
                      'AAA': np.linspace(20, 41, days),
                      'BBB': np.linspace(70, 88, days)}, index=dates)
    v = pd.DataFrame(2e6, index=dates, columns=p.columns)
    return p, v


def test_screen_does_not_promote_stale_latest_quote():
    prices, volume = sample_bars()
    prices.iloc[-1, prices.columns.get_loc('AAA')] = np.nan
    result = screen_candidates(prices, volume, limit=None)
    assert 'AAA' not in set(result.ticker)
    assert 'BBB' in set(result.ticker)


def test_screen_uses_trading_quote_for_liquidity_and_eligibility():
    prices, volume = sample_bars()
    trading = prices.copy()
    trading['AAA'] = 1.0  # a split-adjusted/adjustment discrepancy fixture
    eligible = screen_candidates(prices, volume, limit=None, raw_close=trading)
    assert 'AAA' not in set(eligible.ticker)
    assert 'BBB' in set(eligible.ticker)


def test_screen_missing_current_volume_cannot_qualify():
    prices, volume = sample_bars()
    volume.loc[volume.index[-1], 'AAA'] = np.nan
    assert 'AAA' not in set(screen_candidates(prices, volume, limit=None).ticker)


def test_yahoo_separates_total_return_price_and_trading_quote(monkeypatch):
    index = pd.bdate_range('2025-01-01', periods=200, tz='UTC')
    def download(tickers, **kwargs):
        assert kwargs['auto_adjust'] is False
        entries = {}
        for sym in tickers:
            entries[(sym, 'Close')] = np.full(len(index), 100.0)
            entries[(sym, 'Adj Close')] = np.linspace(75, 90, len(index))
            entries[(sym, 'Volume')] = np.full(len(index), 2e6)
        return pd.DataFrame(entries, index=index)
    monkeypatch.setitem(sys.modules, 'yfinance', types.SimpleNamespace(download=download))
    market = download_market_data(['AAA'], years=1, min_history=140)
    assert market.close['AAA'].iloc[0] == pytest.approx(75)
    assert market.raw_close['AAA'].iloc[0] == pytest.approx(100)
    panel = build_panel(market.close, market.volume, horizon=20, raw_close=market.raw_close)
    assert panel.loc[panel.ticker.eq('AAA'), 'raw_close'].iloc[-1] == pytest.approx(100)


def test_adj_close_missing_is_explicitly_disclosed(monkeypatch):
    index = pd.bdate_range('2025-01-01', periods=200, tz='UTC')
    def download(tickers, **kwargs):
        return pd.DataFrame({(t, x): np.full(len(index), v)
                             for t in tickers for x, v in [('Close', 50.), ('Volume', 1e6)]}, index=index)
    monkeypatch.setitem(sys.modules, 'yfinance', types.SimpleNamespace(download=download))
    market=download_market_data(['AAA'],years=1,min_history=140)
    assert 'price-only' in market.source
    assert market.raw_close['AAA'].iloc[0] == pytest.approx(market.close['AAA'].iloc[0])


def test_cache_incremental_and_close_cutoff_keep_raw_price(tmp_path):
    p,v=sample_bars()
    raw=p*1.1
    data=MarketData(p, v, 'fixture', [], raw_close=raw)
    path=tmp_path/'p.sqlite'
    save_market('sample',data,path)
    restored,_ = load_market('sample',path)
    pd.testing.assert_frame_equal(restored.raw_close,raw,check_freq=False,check_dtype=False)
    later = MarketData(pd.DataFrame({'SPY':[120.],'AAA':[45.],'BBB':[91.]},index=[p.index[-1]+pd.offsets.BDay()]),
                       pd.DataFrame({'SPY':[1e6],'AAA':[1e6],'BBB':[1e6]},index=[p.index[-1]+pd.offsets.BDay()]),
                       'delta',[],raw_close=pd.DataFrame({'SPY':[121.],'AAA':[46.],'BBB':[92.]},index=[p.index[-1]+pd.offsets.BDay()]))
    merged=merge_market(restored,later)
    assert merged.raw_close.loc[later.close.index[-1],'AAA']==46
    before=completed_daily_only(merged,datetime(2026,1,1,17,tzinfo=timezone.utc))
    assert before.raw_close.index.equals(before.close.index)


@pytest.mark.parametrize('wrong', [float('nan'),float('inf'),-.1,'bad'])
def test_optimizer_rejects_every_invalid_weight(wrong):
    p,_=sample_bars()
    with pytest.raises(ValueError,match='weights|numeric'):
        portfolio_allocation_study(p, {'AAA': .5, 'BBB': wrong}, as_of=NOW)


def test_optimizer_rejects_negative_hidden_position_with_full_cash():
    p,_=sample_bars()
    with pytest.raises(ValueError):
        portfolio_allocation_study(p,{'AAA':.9,'BBB':-.2},as_of=NOW)


def test_optimizer_rejects_irregular_price_frequency():
    p,_=sample_bars(days=1000)
    p=p.iloc[::5]
    with pytest.raises(ValueError,match='daily'):
        portfolio_allocation_study(p,{'AAA':.3,'BBB':.3},as_of=NOW)


def test_optimizer_rejects_duplicate_dates():
    p,_=sample_bars()
    p=pd.concat([p, p.tail(1)])
    with pytest.raises(ValueError,match='duplicate'):
        portfolio_allocation_study(p,{'AAA':.3,'BBB':.3},as_of=NOW)


def test_legacy_yahoo_cache_must_upgrade_entire_history(tmp_path, monkeypatch):
    p,v=sample_bars()
    key=config_key('adjusted_daily',['AAA'],kind='deep',years=5,min_history=160)
    path=tmp_path/'cached.sqlite'
    save_market(key,MarketData(p,v,'Yahoo Finance (old price schema)',[]),path=path)
    seen=[]
    def fetch(*a,**kw):
        seen.append(kw)
        return MarketData(p,v,'new',[],raw_close=p*1.25)
    monkeypatch.setattr('ithaca_quant.incremental.download_market_data',fetch)
    upgraded,status,_,notes=refresh_market(['AAA'],5,kind='deep',min_interval=120,path=path)
    assert status=='full'
    assert len(seen)==1 and 'start' not in seen[0]
    assert upgraded.raw_close is not None
    assert notes
