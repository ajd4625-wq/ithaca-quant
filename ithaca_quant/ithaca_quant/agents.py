"""Exactly three deterministic stock-research scoring agents.

These are transparent score components, NOT autonomous LLMs or independent
forecasters; all use the preexisting model and indicators. The subscores are
relative percentiles, not calibrated probabilities of any gain.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

AGENT_NAMES = ("Forecast", "Momentum", "Risk")
AGENT_WEIGHTS = (0.55, 0.15, 0.30)


def percentile(s: pd.Series, *, high_is_good: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if x.notna().sum() == 0:
        return pd.Series(0.5, index=s.index, dtype=float)
    return x.rank(pct=True, ascending=high_is_good).fillna(0.0)


def score_three_agents(df: pd.DataFrame) -> pd.DataFrame:
    """Use exactly Forecast, Momentum and Risk agents to score candidates."""
    forecast = percentile(df["forecast_excess"])
    momentum = percentile(df["rel_20"])
    low_vol = percentile(df["vol_20"], high_is_good=False)
    agreement = percentile(df["model_disagreement"], high_is_good=False)
    # 2/3 low-vol + 1/3 model agreement matches legacy 20% + 10% weighting.
    risk = (2 * low_vol + agreement) / 3
    out = pd.DataFrame(index=df.index)
    out["forecast_agent_score"] = (100 * forecast).round(1)
    out["momentum_agent_score"] = (100 * momentum).round(1)
    out["risk_agent_score"] = (100 * risk).round(1)
    out["balanced_agent_score"] = 0.55 * forecast + 0.15 * momentum + 0.30 * risk
    return out
