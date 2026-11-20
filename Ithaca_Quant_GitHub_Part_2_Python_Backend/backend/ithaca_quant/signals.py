"""Explainable research WATCH signals and hypothetical risk budgets.

These are end-of-day analysis conditions, not trade executions or forecasts
of exact buy/sell dates. Stop levels can be bypassed by price gaps.
"""
import numpy as np
import pandas as pd
from .config import INITIAL_CAPITAL, MAX_POSITION


def plan_signals(rank: pd.DataFrame, *, horizon: int, risk_budget_pct: float = 1.0,
                 portfolio_value: float = INITIAL_CAPITAL) -> pd.DataFrame:
    if not 0 < risk_budget_pct <= 5:
        raise ValueError('Risk budget must be between 0 and 5 percent.')
    rows = rank.copy()
    rows['daily_vol'] = rows['vol_20'] / np.sqrt(252)
    rows['stop_pct'] = (3.0 * rows['daily_vol']).clip(lower=0.05, upper=0.20)
    rows['review_level'] = rows['close'] * (1 - rows['stop_pct'])
    rows['moving_average_20'] = rows['close'] / (1 + rows['ma_gap_20'])
    rows['max_risk_dollars'] = portfolio_value * risk_budget_pct / 100
    rows['max_starter_value'] = np.minimum(
        portfolio_value * MAX_POSITION,
        rows['max_risk_dollars'] / rows['stop_pct']
    )
    rows['max_starter_weight_pct'] = 100 * rows['max_starter_value'] / portfolio_value
    rows['max_starter_shares'] = np.floor(rows['max_starter_value'] / rows['close']).astype(int)
    rising_trend = (rows['ma_gap_20'] > 0) & (rows['ma_gap_60'] > 0)
    relative_strength = rows['rel_20'] > 0
    model_favors = rows['forecast_excess'] > 0.02
    model_weak = rows['forecast_excess'] < -0.02
    exit_review = (rows['ma_gap_20'] < -0.02) | model_weak
    # An earlier inflection screen, not a guarantee of a coming rally.
    # It requires a favorable 20-session model outlook, a positive recent
    # *acceleration* after relative weakness, a non-extended 52-week location,
    # and sufficient liquidity/activity. Missing 52-week history cannot qualify.
    def feature(name):
        return pd.to_numeric(rows[name], errors="coerce") if name in rows else pd.Series(np.nan, index=rows.index)
    early_turn = (
        (int(horizon) == 20) & (rows['forecast_excess'] > 0.03) &
        (feature('has_252_range') == 1) &
        feature('range_252').between(0.15, 0.72) &
        feature('mom_5').between(0.01, 0.10) &
        (feature('mom_5_accel') >= 0.02) &
        (feature('rel_5') > 0.01) &
        feature('mom_20').between(-0.07, 0.10) &
        feature('ma_gap_20').between(-0.018, 0.035) &
        (feature('volume_ratio') > -0.20) &
        (feature('vol_20') <= 1.25) & (~exit_review)
    )
    rows['early_trend_watch'] = early_turn.fillna(False)
    rows['entry_watch'] = np.select(
        [rising_trend & relative_strength & model_favors,
         rows['early_trend_watch'],
         model_favors & (rising_trend | relative_strength)],
        ['ENTRY WATCH', 'EARLY ENTRY WATCH', 'WATCH / CONFIRM'],
        default='WAIT',
    )
    rows['exit_review'] = np.where(exit_review, 'REVIEW EXIT', 'MONITOR')
    rows['review_after_sessions'] = int(horizon)
    return rows
