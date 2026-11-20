"""Offline tests for exactly three ranking components and bounded retry logic."""
from types import SimpleNamespace
import sys

import numpy as np
import pandas as pd
import pytest

from ithaca_quant.agents import AGENT_NAMES, AGENT_WEIGHTS, score_three_agents
from ithaca_quant.config import MAX_AGENTS, MAX_RETRIES
from ithaca_quant.data import download_market_data
from ithaca_quant.leaderboard import rank_stocks, leaderboard_display
from ithaca_quant.retry import retry_call


def test_agent_count_and_score_formula_matches_legacy_balance():
    assert MAX_AGENTS == 3
    assert AGENT_NAMES == ("Forecast", "Momentum", "Risk")
    assert len(AGENT_WEIGHTS) == 3
    stocks = pd.DataFrame({
        "ticker": ["AAA", "BBB", "CCC"],
        "close": [25., 35., 45.],
        "forecast_excess": [.06, -.01, .03],
        "rel_20": [.01, .03, -.02],
        "vol_20": [.6, .3, .4],
        "model_disagreement": [.02, .01, .03],
    })
    out = rank_stocks(stocks, 20)
    for c in ("forecast_agent_score", "momentum_agent_score", "risk_agent_score"):
        assert c in out and out[c].between(0, 100).all()
    display = leaderboard_display(out, 20, .20)
    assert {"Forecast agent /100", "Momentum agent /100", "Risk agent /100"}.issubset(display.columns)
    # Unrounded old balanced formula remains invariant.
    expected = (0.55 * stocks.forecast_excess.rank(pct=True) +
                0.15 * stocks.rel_20.rank(pct=True) +
                0.20 * stocks.vol_20.rank(pct=True, ascending=False) +
                0.10 * stocks.model_disagreement.rank(pct=True, ascending=False))
    for ticker, value in zip(stocks.ticker, expected):
        got = out.set_index("ticker").loc[ticker, "rank_value"]
        assert got == pytest.approx(value)


def test_two_retries_then_stop_even_on_persistent_failure():
    assert MAX_RETRIES == 2
    attempts = []
    def broken():
        attempts.append(True)
        raise ConnectionError("no connection")
    with pytest.raises(ConnectionError):
        retry_call(broken, sleep=lambda _: None)
    assert len(attempts) == 3


def test_recovery_on_third_attempt_and_no_retry_for_protected_errors():
    attempts = []
    def recover():
        attempts.append(True)
        if len(attempts) < 3:
            raise ConnectionError("temporary")
        return "good"
    assert retry_call(recover, sleep=lambda _: None) == "good"
    assert len(attempts) == 3
    attempts.clear()
    with pytest.raises(ZeroDivisionError):
        retry_call(lambda: (attempts.append(True), 1 / 0)[1],
                   retryable=lambda err: isinstance(err, ConnectionError),
                   sleep=lambda _: None)
    assert len(attempts) == 1


def test_empty_responses_retry_twice_and_yahoo_uses_three_threads(monkeypatch):
    dates = pd.bdate_range('2026-01-01', periods=190, tz='UTC')
    calls = []
    def fake_download(tickers, **kwargs):
        calls.append(kwargs.get('threads'))
        if len(calls) < 3:
            return pd.DataFrame()
        symbols = list(tickers)
        data = {}
        for sym in symbols:
            data[(sym, 'Close')] = np.linspace(100, 140, len(dates))
            data[(sym, 'Volume')] = np.full(len(dates), 1e6)
        return pd.DataFrame(data, index=dates)
    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(download=fake_download))
    # Force the wait to be a no-op in the test by replacing retry's global time.sleep default? 
    # Two pauses are short and limited (<2 seconds).
    data = download_market_data(['AAA'], years=1, min_history=140)
    assert len(calls) == 3 and calls == [3, 3, 3]
    assert 'AAA' in data.close.columns
