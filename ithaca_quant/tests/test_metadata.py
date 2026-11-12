"""Offline tests for classification, market caps and cached lookups."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ithaca_quant.metadata import (
    add_metadata, clean_company_info, fetch_company_metadata,
    load_company_metadata, market_cap_bucket,
)
from ithaca_quant.leaderboard import leaderboard_display


def test_clean_profile_missing_fields_remain_unknown():
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    row = clean_company_info("nvda", {"shortName": "Nvidia", "industry": "Semiconductors", "marketCap": "500000000000"}, asof=now)
    assert row["ticker"] == "NVDA"
    assert row["industry"] == "Semiconductors"
    assert row["sector"] == ""
    assert row["market_cap"] == 500e9
    assert "2026-11-11" in row["metadata_asof"]
    for wrong in (None, "unavailable", -50, float("inf"), 0):
        assert np.isnan(clean_company_info("X", {"marketCap": wrong})["market_cap"])


def test_fetch_uses_persistent_cache_then_refreshes_stale(tmp_path):
    path = tmp_path / "meta.sqlite3"
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    requested = []

    def fake_fetcher(symbol):
        requested.append(symbol)
        return {"shortName": f"{symbol} Corp", "sector": "Technology", "industry": "Software", "marketCap": 22e9}

    frame, status = fetch_company_metadata(["AAA", "BBB", "AAA"], cache_path=path, max_new=1,
                                           fetcher=fake_fetcher, now=now)
    assert requested == ["AAA"]
    assert len(frame) == 1
    assert status["not_loaded"] == 1
    frame, status = fetch_company_metadata(["BBB", "AAA"], cache_path=path, max_new=2,
                                           fetcher=fake_fetcher, now=now + timedelta(hours=1))
    assert requested == ["AAA", "BBB"]
    assert len(frame) == 2 and status["attempted"] == 1
    frame, status = fetch_company_metadata(["AAA", "BBB"], cache_path=path, max_new=2,
                                           fetcher=fake_fetcher, now=now + timedelta(hours=26))
    assert requested[-2:] == ["AAA", "BBB"]
    assert status["attempted"] == 2
    assert len(load_company_metadata(["AAA", "BBB"], cache_path=path)) == 2


def test_api_failure_does_not_fabricate_data(tmp_path):
    path = tmp_path / "meta.sqlite3"
    def broken(_):
        raise RuntimeError("rate limited")
    result, stats = fetch_company_metadata(["AAA"], cache_path=path, fetcher=broken)
    assert stats["errors"] == 1 and result.empty
    base = pd.DataFrame({"ticker": ["AAA", "BBB"], "screen_score": [0.8, 0.3]})
    merged = add_metadata(base, result)
    assert len(merged) == 2 and pd.isna(merged.loc[0, "market_cap"])


def test_metadata_merges_with_rank_without_reordering(tmp_path):
    path = tmp_path / "meta.sqlite3"
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    info = {"AAA": {"shortName": "A Inc", "sector": "Technology", "industry": "Semiconductors", "marketCap": 100e9},
            "BBB": {"shortName": "B Inc", "sector": "Industrials", "industry": "Machinery", "marketCap": 8e9}}
    profiles, _ = fetch_company_metadata(["BBB", "AAA"], cache_path=path, fetcher=lambda s: info[s], now=now)
    rank = pd.DataFrame({"rank": [1, 2, 3], "ticker": ["AAA", "UNKNOWN", "BBB"],
                         "research_score": [98., 75., 50.], "close": [50., 80., 20.],
                         "forecast_excess": [.2, .1, 0], "prob_boom": [.3, .2, .1],
                         "prob_gain": [.6, .5, .4], "horizon_1sigma": [.15]*3,
                         "vol_20": [.25]*3, "rel_20": [.02]*3, "model_disagreement": [.01]*3})
    enriched = add_metadata(rank, profiles)
    assert enriched["ticker"].tolist() == ["AAA", "UNKNOWN", "BBB"]
    view = leaderboard_display(enriched, 20, .2)
    assert "Sector" in view and "Industry" in view and "Market cap ($B)" in view
    assert view["Ticker"].tolist() == ["AAA", "UNKNOWN", "BBB"]
    assert view.loc[0, "Market cap ($B)"] == 100.0
    assert pd.isna(view.loc[1, "Market cap ($B)"])
    assert view.loc[2, "Company"] == "B Inc"


def test_market_cap_buckets():
    assert market_cap_bucket(float("nan")) == "Unknown"
    assert market_cap_bucket(250e9).startswith("Mega")
    assert market_cap_bucket(15e9).startswith("Large")
    assert market_cap_bucket(5e9).startswith("Mid")
    assert market_cap_bucket(1e9).startswith("Small")
    assert market_cap_bucket(100e6).startswith("Micro")


def test_cache_reads_large_universe_in_chunks(tmp_path):
    path = tmp_path / "meta.sqlite3"
    symbols = [f"T{i:04d}" for i in range(1003)]
    result = load_company_metadata(symbols, cache_path=path)
    assert result.empty and result.columns.tolist()[0] == "ticker"
