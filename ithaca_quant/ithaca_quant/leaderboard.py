"""Transparent, *relative* rankings of the latest model forecasts.

Ranks compare stocks inside the *currently modeled* candidate universe; neither
ranks nor research scores estimate probabilities of profits.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .agents import score_three_agents

RANKING_MODES = (
    "Balanced (upside + risk)",
    "Forecast upside",
    "Risk-adjusted forecast",
    "Boom probability (experimental)",
    "Relative momentum",
)


def _percentile(series: pd.Series, *, higher_is_better: bool = True) -> pd.Series:
    """Cross-sectional percentile (0..1); safely handle a one-name universe."""
    number = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if number.notna().sum() == 0:
        return pd.Series(0.5, index=series.index, dtype=float)
    ascending = higher_is_better
    # 'rank(pct=True)' gives 1/n for the bottom stock and 1 for the top.
    ranked = number.rank(pct=True, ascending=ascending)
    return ranked.fillna(0.0)


def boom_model_quality(rank: pd.DataFrame) -> tuple[bool, str]:
    """Whether a prior chronological holdout beats a constant-rate forecast.

    This is NOT evidence of well-calibrated live probabilities. It is a basic
    prerequisite before giving experimental event ranks any credibility.
    """
    if rank.empty:
        return False, "No models available."
    one = rank.iloc[0]
    n = pd.to_numeric(one.get("boom_holdout_n", np.nan), errors="coerce")
    brier = pd.to_numeric(one.get("boom_holdout_brier", np.nan), errors="coerce")
    base = pd.to_numeric(one.get("boom_holdout_baseline_brier", np.nan), errors="coerce")
    if pd.isna(n) or n < 80 or pd.isna(brier) or pd.isna(base):
        return False, "Insufficient chronological holdout evidence for the boom estimates."
    if float(brier) >= float(base):
        return False, "Boom probabilities did not beat the constant-rate baseline in the internal holdout."
    return True, "Boom model beat a constant-rate baseline on one chronological holdout; future accuracy remains unproven."


def rank_stocks(rank: pd.DataFrame, horizon: int, method: str = RANKING_MODES[0],
                min_price: float = 5.0, max_volatility: float | None = None,
                positive_forecast_only: bool = False) -> pd.DataFrame:
    """Create an explainable numbered leaderboard, no retraining or lookahead.

    - Balanced score combines cross-sectional percentiles of predicted SPY
      outperformance, relative momentum, lower volatility and model agreement.
    - The score is *only* an intra-universe ranking measure, NOT confidence.
    - Other methods give an equivalent within-universe percentile score; raw
      sort keys are preserved to make ordering interpretable.
    """
    if method not in RANKING_MODES:
        raise ValueError(f"Unknown ranking method: {method}")
    if horizon <= 0:
        raise ValueError("Forecast horizon must be positive")
    required = {"ticker", "close", "forecast_excess", "vol_20", "model_disagreement", "rel_20"}
    missing = required - set(rank.columns)
    if missing:
        raise ValueError(f"Missing ranking input columns: {', '.join(sorted(missing))}")
    df = rank.copy()
    numeric = ["close", "forecast_excess", "vol_20", "rel_20", "model_disagreement",
               "prob_boom", "prob_gain", "mom_20", "drawdown_60"]
    for col in numeric:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.loc[
        df["ticker"].notna() & (df["close"] > min_price) &
        df["forecast_excess"].notna() & (df["vol_20"] >= 0) &
        df["model_disagreement"].notna() & df["rel_20"].notna()
    ].copy()
    if max_volatility is not None:
        df = df.loc[df["vol_20"] <= max_volatility].copy()
    if positive_forecast_only:
        df = df.loc[df["forecast_excess"] > 0].copy()
    if df.empty:
        df["rank"] = pd.Series(dtype="int64")
        df["research_score"] = pd.Series(dtype="float64")
        df["rank_value"] = pd.Series(dtype="float64")
        df["horizon_1sigma"] = pd.Series(dtype="float64")
        return df

    agent_scores = score_three_agents(df)
    for field in ("forecast_agent_score", "momentum_agent_score", "risk_agent_score"):
        df[field] = agent_scores[field]
    f = _percentile(df["forecast_excess"])
    momentum = _percentile(df["rel_20"])
    balanced = agent_scores["balanced_agent_score"]
    df["horizon_1sigma"] = df["vol_20"] * np.sqrt(horizon / 252.0)

    if method == "Balanced (upside + risk)":
        df["rank_value"] = balanced
        df["research_score"] = (100 * balanced).round(1)
    elif method == "Forecast upside":
        df["rank_value"] = df["forecast_excess"]
        df["research_score"] = (100 * f).round(1)
    elif method == "Risk-adjusted forecast":
        # Heuristic forecast / estimated horizon volatility, penalizing model conflict.
        df["rank_value"] = df["forecast_excess"] / (
            0.02 + df["horizon_1sigma"] + df["model_disagreement"].clip(lower=0)
        )
        df["research_score"] = (100 * _percentile(df["rank_value"])).round(1)
    elif method == "Boom probability (experimental)":
        df["rank_value"] = df["prob_boom"]
        df["research_score"] = (100 * _percentile(df["prob_boom"])).round(1)
        df.loc[df["prob_boom"].isna(), "research_score"] = np.nan
    else:  # Relative momentum
        df["rank_value"] = df["rel_20"]
        df["research_score"] = (100 * momentum).round(1)

    df = df.sort_values(["rank_value", "forecast_excess", "ticker"],
                        ascending=[False, False, True], na_position="last", kind="mergesort").reset_index(drop=True)
    df.insert(0, "rank", np.arange(1, len(df) + 1, dtype=int))
    return df


def leaderboard_display(ranked: pd.DataFrame, horizon: int, boom_threshold: float,
                        signals: pd.DataFrame | None = None,
                        company_info: pd.DataFrame | None = None) -> pd.DataFrame:
    """Presentation-only columns while retaining unrounded values for CSV export."""
    df = ranked.copy()
    if company_info is not None and not company_info.empty and {"data_ticker", "name", "exchange"}.issubset(company_info.columns):
        names = company_info[["data_ticker", "name", "exchange"]].drop_duplicates("data_ticker")
        df = df.merge(names, how="left", left_on="ticker", right_on="data_ticker")
    if "company_name" in df:
        if "name" in df:
            df["name"] = df["name"].where(df["name"].notna() & df["name"].ne(""), df["company_name"])
        else:
            df["name"] = df["company_name"]
    if "market_cap" in df:
        df["market_cap_billions"] = pd.to_numeric(df["market_cap"], errors="coerce") / 1e9
    if signals is not None and {"ticker", "entry_watch", "exit_review"}.issubset(signals.columns):
        df = df.merge(signals[["ticker", "entry_watch", "exit_review"]], on="ticker", how="left")
    columns = {
        "rank": "Rank",
        "ticker": "Ticker",
        "research_score": "Research score /100",
        "forecast_agent_score": "Forecast agent /100",
        "momentum_agent_score": "Momentum agent /100",
        "risk_agent_score": "Risk agent /100",
        "close": "Adjusted daily close ($)",
        "forecast_excess": f"Forecast vs SPY ({horizon}d)",
        "prob_gain": f"P(gain, {horizon}d)*",
        "prob_boom": f"P(+{boom_threshold:.0%}, {horizon}d)*",
        "horizon_1sigma": f"Historical 1σ move ({horizon}d)**",
        "vol_20": "Annualized volatility",
        "rel_20": "20d vs SPY",
        "model_disagreement": "Model disagreement",
    }
    if "name" in df:
        columns["name"] = "Company"
    if "exchange" in df:
        columns["exchange"] = "Exchange"
    if "sector" in df:
        columns["sector"] = "Sector"
    if "industry" in df:
        columns["industry"] = "Industry"
    if "market_cap_billions" in df:
        columns["market_cap_billions"] = "Market cap ($B)"
    if "metadata_asof" in df:
        columns["metadata_asof"] = "Company data as of (UTC)"
    if "entry_watch" in df:
        columns["entry_watch"] = "Entry watch"
        columns["exit_review"] = "Exit watch"
    return df[[c for c in columns if c in df.columns]].rename(columns=columns)
