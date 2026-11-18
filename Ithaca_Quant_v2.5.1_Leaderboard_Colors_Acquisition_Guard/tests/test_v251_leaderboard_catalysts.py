"""v2.5.1: color-coded leaderboard and acquisition run-up safeguards."""
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ithaca_quant.leaderboard_review import (
    five_day_runup, acquisition_headlines, deal_jump_since_announcement,
    evaluate_candidate, add_leaderboard_review,
)
from ithaca_quant.leaderboard import leaderboard_display

ASOF = date(2026, 11, 18)


def prices(symbol="ACME", *, late_rally=True):
    idx = pd.bdate_range("2026-10-21", "2026-11-18")
    spy = np.linspace(100, 101, len(idx))
    stock = np.linspace(100, 102, len(idx))
    if late_rally:
        stock[-6:] = [101, 105, 109, 115, 120, 122]
    return pd.DataFrame({symbol: stock, "SPY": spy}, index=idx)


def row(symbol="ACME"):
    return dict(ticker=symbol, close=122, forecast_excess=.08, prob_gain=.75,
                vol_20=.35, research_score=95., rank=1, rel_20=.05)


def sig(exit_review="MONITOR", entry_watch="ENTRY WATCH"):
    return dict(entry_watch=entry_watch, exit_review=exit_review, review_level=95)


def article(headline="Acme agrees to acquire Beta in major deal", day=16,
            pub="Yahoo Finance", symbol="ACME"):
    return {"title": headline, "publisher": pub, "url": "https://example.com/acme",
            "published_utc": datetime(2026, 11, day, 16, tzinfo=timezone.utc)}


def test_all_stocks_get_baseline_colors_without_headlines():
    close = prices(late_rally=False)
    result = evaluate_candidate(row(), sig(), close, asof=ASOF, horizon=20)
    assert result["color"] == "DARK_GREEN"
    assert result["acquisition_check"] == "Not checked"
    assert result["entry_priority_score"] == 95


def test_rapid_growth_downgrades_dark_green_and_reduces_priority():
    result = evaluate_candidate(row(), sig(), prices(), asof=ASOF, horizon=20)
    assert result["color"] == "YELLOW"
    assert "AVOID CHASING" in result["signal_label"]
    assert result["return_5d"] > .15
    assert result["entry_priority_score"] == 80
    assert "Not checked" in result["acquisition_check"]


def test_acquisition_only_flagged_if_relevant_specific_and_time_valid():
    items = [article("Other company agrees to acquire Beta"),
             article("ACME reportedly in talks to acquire Beta"),
             article("Acme agrees to acquire Beta in major deal", day=19),
             article("Acme agrees to acquire Beta in major deal", day=16),
             article("Acme agrees to acquire Beta in major deal", day=16)]
    got = acquisition_headlines(items, "ACME", "Acme Inc", asof=ASOF)
    assert len(got) == 1
    assert got[0]["date"] == date(2026, 11, 16)
    assert got[0]["url"].startswith("https:")


def test_confirmed_acquisition_runup_gets_stronger_penalty():
    result = evaluate_candidate(row(), sig(), prices(), asof=ASOF, horizon=20,
                                articles=[article()], company="Acme Inc")
    assert result["possible_priced_in"] is True
    assert result["color"] == "YELLOW"
    assert result["entry_priority_score"] == 60
    assert "deal" in result["acquisition_check"].lower()
    assert "not proof" in result["reason"].lower()


def test_announced_today_has_no_proven_post_event_reaction():
    news = [article(day=18)]
    result = evaluate_candidate(row(), sig(), prices(late_rally=False), asof=ASOF,
                                horizon=20, articles=news, company="Acme Inc")
    assert result["possible_priced_in"] is False
    assert result["color"] == "YELLOW"
    assert "VERIFY DEAL REACTION" in result["signal_label"]
    assert deal_jump_since_announcement(prices(), "ACME", ASOF, asof=ASOF)["deal_return"] is None


def test_no_acquisition_headline_no_spike_maintains_favorable_color():
    result = evaluate_candidate(row(), sig(), prices(late_rally=False), asof=ASOF,
                                horizon=20, articles=[article("Acme announces dividend")],
                                company="Acme Inc")
    assert result["color"] == "DARK_GREEN"
    assert "No qualifying" in result["acquisition_check"]


def test_red_exit_never_overridden_by_good_forecast_or_news():
    result = evaluate_candidate(row(), sig(exit_review="REVIEW EXIT"), prices(),
                                asof=ASOF, horizon=20, articles=[article()], company="Acme Inc")
    assert result["color"] == "RED"
    assert "REVIEW EXIT" in result["signal_label"]


def test_stale_signal_and_horizon_not_assumed_reliable():
    result = evaluate_candidate(row(), sig(), prices(late_rally=False),
                                asof=date(2026, 11, 1), horizon=20)
    assert result["color"] == "YELLOW"
    result = evaluate_candidate(row(), sig(), prices(late_rally=False),
                                asof=ASOF, horizon=5)
    assert result["color"] != "DARK_GREEN"


def test_price_runup_requires_same_day_valid_data_no_forward_leakage():
    close = prices()
    earlier = five_day_runup(close, "ACME", date(2026, 11, 10))
    later = five_day_runup(close, "ACME", ASOF)
    assert later["fast_rise"]
    assert not earlier["fast_rise"]
    close.loc[close.index[-1], "ACME"] = np.nan
    assert five_day_runup(close, "ACME", ASOF)["return_5d"] is None


def test_table_keeps_original_forecast_and_rank_and_includes_research_columns():
    original = pd.DataFrame([row()])
    signal_table = pd.DataFrame([{"ticker": "ACME", **sig()}])
    review = add_leaderboard_review(original, signal_table, prices(), asof=ASOF, horizon=20,
                                    headlines_by_ticker={"ACME": [article()]})
    assert review.loc[0, "forecast_excess"] == .08
    assert review.loc[0, "research_score"] == 95
    review["original_model_rank"] = review["rank"]
    display = leaderboard_display(review, 20, .20, signals=signal_table)
    assert "Entry signal" in display.columns
    assert "Why this color" in display.columns
    assert "Entry priority /100" in display.columns
    assert "Model rank" in display.columns
    assert "Acquisition check" in display.columns
    assert "Deal source URL" in display.columns


def test_ui_renders_colored_leaderboard_and_explicit_checked_news_button():
    text = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert "leader_deal_fetch" in text
    assert "leader_entry_sort" in text
    assert "formatted.style.map(_leader_signal_style" in text
    assert 'headlines_by_ticker=checked' in text
    assert "Original research scores and return forecasts remain unchanged" in text
