"""v1.4 edge cases: historical data refresh, SEC dates, news history, accuracy gate."""
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from ithaca_quant.data import MarketData, demo_market_data
from ithaca_quant.incremental import (completed_daily_only, overlap_conflicts,
                                      merge_market, AdjustmentConflict, refresh_market)
from ithaca_quant.market_cache import (config_key, load_screen, save_screen, load_market,
                                       save_market, cache_is_fresh)
from ithaca_quant.fundamentals import (concept_quarters, public_quarterly_snapshot,
                                      filing_features, sec_headers, cik_from_directory)
from ithaca_quant.news_archive import archive_headlines, recorded_headlines, archived_features
from ithaca_quant.features import build_panel, NEWS_FEATURES, FUNDAMENTAL_FEATURES
from ithaca_quant.model import choose_evidence_features
from ithaca_quant.news_intelligence import analyze_news


def history():
    idx = pd.bdate_range("2026-10-20", periods=12)
    p = pd.DataFrame({"SPY": np.arange(100, 112.0), "AAPL": np.arange(50, 62.0)}, index=idx)
    v = pd.DataFrame({"SPY": 1e6, "AAPL": 2e6}, index=idx)
    return MarketData(p, v, "fixture", [])


def test_sqlite_market_round_trip_and_versioned_keys(tmp_path):
    path = tmp_path / "cache.sqlite"
    data = history()
    key = config_key("adjusted_daily", ["AAPL"], kind="deep", years=5)
    assert key != config_key("adjusted_daily", ["AAPL"], kind="screen", years=1)
    save_market(key, data, path)
    item = load_market(key, path)
    assert item is not None
    pd.testing.assert_frame_equal(item[0].close, data.close, check_freq=False, check_dtype=False)
    assert cache_is_fresh(item[1], 300)


def test_sqlite_screen_round_trip(tmp_path):
    path = tmp_path / "screen.sqlite"
    frame = pd.DataFrame({"ticker": ["ABC", "DEF"], "screen_score": [0.8, 0.2]})
    save_screen("screen:test", frame.head(1), frame, 2, 0, path)
    (selected, all_names, loaded, excluded), _ = load_screen("screen:test", path)
    assert selected["ticker"].tolist() == ["ABC"]
    assert all_names["screen_score"].tolist() == pytest.approx([.8, .2])
    assert loaded == 2 and excluded == 0


def test_merging_adds_only_real_new_bar_not_invented_illiquid_price():
    old = history()
    ix = pd.bdate_range(old.close.index[-3], periods=4)
    recent = MarketData(pd.DataFrame({"SPY": [109., 110., 111., 112.]}, index=ix),
                        pd.DataFrame({"SPY": [1e6]*4}, index=ix), "delta", [])
    merged = merge_market(old, recent)
    assert merged.close.loc[ix[-1], "SPY"] == 112
    assert pd.isna(merged.close.loc[ix[-1], "AAPL"])
    assert merged.close.loc[ix[-2], "AAPL"] == 61


def test_adjusted_history_rewrite_triggers_repair_not_blind_splice():
    old = history()
    dates = old.close.index[-4:]
    new = MarketData(old.close.loc[dates] * .5, old.volume.loc[dates], "split", [])
    assert set(overlap_conflicts(old, new)) == {"SPY", "AAPL"}
    with pytest.raises(AdjustmentConflict):
        merge_market(old, new)


def test_daily_close_is_ineligible_before_5pm_ny():
    index = pd.to_datetime(["2026-11-11", "2026-11-12"])
    data = MarketData(pd.DataFrame({"SPY": [110, 111], "AAPL": [40, 41]}, index=index),
                      pd.DataFrame({"SPY": [1000, 1000], "AAPL": [1000, 1000]}, index=index),
                      "provider", [])
    before = completed_daily_only(data, datetime(2026, 11, 12, 20, 45, tzinfo=timezone.utc))
    after = completed_daily_only(data, datetime(2026, 11, 12, 23, 0, tzinfo=timezone.utc))
    assert before.close.index.max().date().isoformat() == "2026-11-11"
    assert after.close.index.max().date().isoformat() == "2026-11-12"


def test_failed_delta_keeps_prior_cache_and_flags_stale(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite"
    stock = history()
    key = config_key("adjusted_daily", ["AAPL"], kind="deep", years=5, min_history=160)
    save_market(key, stock, path)
    def fail(*args, **kwargs):
        raise RuntimeError("provider failure")
    monkeypatch.setattr("ithaca_quant.incremental.download_market_data", fail)
    fetched, status, stamp, warnings = refresh_market(["AAPL"], 5, kind="deep",
                           min_interval=0, force=True, path=path)
    assert status == "stale"
    assert warnings and "failed" in warnings[0].lower()
    pd.testing.assert_frame_equal(fetched.close, stock.close, check_freq=False, check_dtype=False)


def _quarter_value(start, end, filed, value, form="10-Q"):
    return {"start": start, "end": end, "filed": filed, "val": value, "form": form}


def _sec_fixture():
    return {"facts": {"us-gaap": {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            _quarter_value("2025-01-01", "2025-03-31", "2025-05-10", 100),
            _quarter_value("2026-01-01", "2026-03-31", "2026-05-10", 130),
            # Restatement is NOT known until August 2026:
            _quarter_value("2026-01-01", "2026-03-31", "2026-08-10", 155),
            _quarter_value("2026-01-01", "2026-12-31", "2027-02-10", 500, "10-K"),
        ]}},
        "NetIncomeLoss": {"units": {"USD": [
            _quarter_value("2025-01-01", "2025-03-31", "2025-05-10", 20),
            _quarter_value("2026-01-01", "2026-03-31", "2026-05-10", 30),
        ]}},
    }}}


def test_sec_quarter_filter_and_restatement_dates():
    facts = _sec_fixture()
    quarters = concept_quarters(facts, ("RevenueFromContractWithCustomerExcludingAssessedTax",))
    assert len(quarters) == 3  # 2 reported Q1 years + a restated Q1
    snap = public_quarterly_snapshot(facts, asof="2026-06-01")
    assert len(snap) == 2
    assert snap.iloc[-1]["revenue_usd"] == 130
    assert snap.iloc[-1]["revenue_yoy"] == pytest.approx(.3)
    restated = public_quarterly_snapshot(facts, asof="2026-09-01")
    assert restated.iloc[-1]["revenue_usd"] == 155
    assert restated.iloc[-1]["filed"] == pd.Timestamp("2026-08-10")


def test_quarter_report_unavailable_before_next_business_day():
    snap = public_quarterly_snapshot(_sec_fixture(), "2026-06-01")
    dates = pd.bdate_range("2026-05-08", "2026-05-13")
    feats = filing_features(snap, dates)
    # May 10, 2026 is Sunday, BDay(1) next Monday May 11
    assert feats.loc["2026-05-08", "sec_available"] == 1.0  # Prior May 2025 report known
    assert feats.loc["2026-05-11", "sec_revenue_yoy"] == pytest.approx(.3)
    assert feats.loc["2026-05-08", "sec_revenue_yoy"] == 0


def test_sec_requires_owner_contact_and_maps_cik():
    with pytest.raises(ValueError, match="SEC_CONTACT_EMAIL"):
        sec_headers("")
    cik, company = cik_from_directory({"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Example"}}, "aapl")
    assert (cik, company) == (320193, "Example")


def test_news_archive_uses_first_seen_not_original_publication(tmp_path):
    path = tmp_path / "news.sqlite"
    published = datetime(2026, 1, 5, 13, tzinfo=timezone.utc)
    first_seen = datetime(2026, 1, 8, 22, tzinfo=timezone.utc)
    raw = [{"title": "AAPL shares rally on growth", "publisher": "Yahoo Finance",
            "url": "https://example.com/story", "published_utc": published}]
    report = analyze_news(raw, "AAPL", now=first_seen)
    assert archive_headlines("AAPL", report, path=path, now=first_seen) == 1
    assert archive_headlines("AAPL", report, path=path, now=first_seen) == 0
    observed = recorded_headlines("AAPL", path=path)
    assert len(observed) == 1
    assert observed.iloc[0]["first_seen_utc"].date().isoformat() == "2026-01-08"
    days = pd.bdate_range("2026-01-06", "2026-01-13")
    features = archived_features("AAPL", days, path=path)
    assert features.loc["2026-01-08", "news_available"] == 0
    assert features.loc["2026-01-09", "news_available"] == 1
    assert features.loc["2026-01-09", "news_sentiment_7d"] > 0


def test_optional_filing_news_features_dont_leak_into_older_panel_dates():
    prices = demo_market_data(["AAPL"], sessions=450)
    dates = prices.close.index
    filing = pd.DataFrame([{"period_end": dates[-60], "filed": dates[-50],
        "revenue_usd": 100, "net_income_usd": 20, "revenue_yoy": .25,
        "net_margin": .2, "tag": "Revenues"}])
    news = pd.DataFrame([{"published_utc": pd.Timestamp(dates[-20], tz="UTC"),
                          "first_seen_utc": pd.Timestamp(dates[-15], tz="UTC"),
                          "sentiment": 2, "relevance": 1.0, "publisher": "Yahoo Finance"}])
    panel = build_panel(prices.close, prices.volume, horizon=20,
                        fundamentals={"AAPL": filing}, news={"AAPL": news})
    assert all(c in panel.columns for c in FUNDAMENTAL_FEATURES + NEWS_FEATURES)
    older = panel.loc[panel["date"] < dates[-50]]
    assert older["sec_available"].eq(0).all()
    before_news = panel.loc[panel["date"] <= dates[-15]]
    assert before_news["news_available"].eq(0).all()


def test_evidence_selection_doesnt_activate_on_empty_history():
    prices = demo_market_data(["AAPL", "MSFT"], sessions=650)
    panel = build_panel(prices.close, prices.volume, 20)
    train = panel.loc[(panel["target"].notna()) & (panel["date"] < panel.date.max())]
    feats, note, maes = choose_evidence_features(train, panel.date.max(), fast=True)
    assert "news_sentiment_7d" not in feats
    assert "sec_revenue_yoy" not in feats
    assert "Price" in note


def test_failed_reconciliation_does_not_mutate_stale_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite"
    stock = history()
    key = config_key("adjusted_daily", ["AAPL"], kind="deep", years=5, min_history=160)
    save_market(key, stock, path)
    dates = stock.close.index[-4:]
    rewritten = MarketData(stock.close.loc[dates] * .5, stock.volume.loc[dates], "new", [])
    calls = []
    def simulated_download(*args, **kwargs):
        calls.append(kwargs)
        if kwargs.get("start"):
            return rewritten
        raise RuntimeError("full adjustment repair failed")
    monkeypatch.setattr("ithaca_quant.incremental.download_market_data", simulated_download)
    result, status, _, alerts = refresh_market(["AAPL"], 5, kind="deep", min_interval=0,
                                                 force=True, path=path)
    assert status == "stale"
    assert alerts
    pd.testing.assert_frame_equal(result.close, stock.close, check_dtype=False, check_freq=False)
    assert set(result.close.columns) == {"SPY", "AAPL"}
    assert len(calls) == 2


def test_yahoo_quarterly_fallback_is_display_only_and_sparse():
    from ithaca_quant.fundamentals import parse_yahoo_quarterly_income
    sample = pd.DataFrame({pd.Timestamp("2026-06-30"): [155., 35., 2.3],
                           pd.Timestamp("2026-03-31"): [100., 20., 1.0]},
                          index=["Total Revenue", "Net Income", "Diluted EPS"])
    parsed = parse_yahoo_quarterly_income(sample)
    assert parsed.iloc[0]["revenue_usd"] == 155
    assert parsed.iloc[0]["net_income_usd"] == 35
    assert parsed.iloc[0]["diluted_eps"] == pytest.approx(2.3)
    assert "filed" not in parsed.columns  # do NOT pretend timestamps are available
