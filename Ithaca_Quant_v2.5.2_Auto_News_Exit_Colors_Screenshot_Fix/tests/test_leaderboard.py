"""Deterministic, offline regression tests of ranking policies and UI data."""
import numpy as np
import pandas as pd
import pytest

from ithaca_quant.leaderboard import (
    RANKING_MODES, rank_stocks, leaderboard_display, boom_model_quality,
)


@pytest.fixture
def models():
    return pd.DataFrame({
        "ticker": ["ALFA", "BETA", "GAMM", "LOW", "NULL"],
        "close": [100., 110., 80., 3., 130.],
        "forecast_excess": [0.16, 0.08, -0.02, 0.70, 0.05],
        "rel_20": [0.05, 0.03, 0.00, 0.60, -0.05],
        "vol_20": [0.72, 0.27, 0.24, 0.9, 0.30],
        "model_disagreement": [0.05, 0.01, 0.02, 0.02, 0.01],
        "prob_boom": [0.25, 0.10, 0.02, 0.50, np.nan],
        "prob_gain": [0.65, 0.60, 0.45, 0.95, np.nan],
        "boom_holdout_n": [210]*5,
        "boom_holdout_brier": [0.05]*5,
        "boom_holdout_baseline_brier": [0.08]*5,
    })


def test_each_ranking_mode_outputs_numbered_sorted_rows(models):
    for mode in RANKING_MODES:
        out = rank_stocks(models, horizon=20, method=mode)
        assert out["ticker"].tolist() == list(dict.fromkeys(out["ticker"].tolist()))
        assert out["rank"].tolist() == [1, 2, 3, 4]
        assert "LOW" not in out["ticker"].tolist()   # price <= $5
        assert out["rank_value"].dropna().is_monotonic_decreasing
        assert out["research_score"].dropna().between(0, 100).all()
        assert out["horizon_1sigma"].notna().all()


def test_forecast_and_risk_adjusted_rank_differ(models):
    upside = rank_stocks(models, 20, "Forecast upside")
    adjusted = rank_stocks(models, 20, "Risk-adjusted forecast")
    assert upside.iloc[0]["ticker"] == "ALFA"
    assert adjusted.iloc[0]["ticker"] == "BETA"


def test_filters_are_applied_before_ranking(models):
    out = rank_stocks(models, 20, max_volatility=0.35, positive_forecast_only=True)
    assert out["ticker"].tolist() == ["BETA", "NULL"] or out["ticker"].tolist() == ["NULL", "BETA"]
    assert out["rank"].tolist() == [1, 2]
    empty = rank_stocks(models, 20, max_volatility=0.01)
    assert empty.empty and "rank" in empty.columns


def test_boom_nan_appears_at_bottom(models):
    result = rank_stocks(models, 20, "Boom probability (experimental)")
    assert result.iloc[-1]["ticker"] == "NULL"
    assert pd.isna(result.iloc[-1]["research_score"])


def test_leaderboard_display_merges_signals_and_names(models):
    r = rank_stocks(models, 20).head(2)
    signals = pd.DataFrame({"ticker": ["ALFA", "BETA"], "entry_watch": ["WATCH", "WAIT"],
                            "exit_review": ["MONITOR", "MONITOR"]})
    listings = pd.DataFrame({"data_ticker": ["ALFA", "BETA"], "name": ["Alpha Inc", "Beta Inc"],
                             "exchange": ["NASDAQ", "NYSE"]})
    display = leaderboard_display(r, 20, 0.20, signals, listings)
    assert "Company" in display.columns and "Exchange" in display.columns
    assert "Entry watch" in display.columns
    assert display.loc[0, "Ticker"] == r.loc[0, "ticker"]


def test_holdout_note_does_not_claim_verified_accuracy(models):
    ok, note = boom_model_quality(models)
    assert ok and "unproven" in note
    bad = models.copy()
    bad["boom_holdout_brier"] = 0.09
    ok2, note2 = boom_model_quality(bad)
    assert not ok2 and "baseline" in note2
    bad["boom_holdout_n"] = np.nan
    assert boom_model_quality(bad)[0] is False
