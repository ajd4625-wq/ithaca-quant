"""52-week/early-inflection research context; price is historical adjusted close.

This module never changes a validated forecast from current headline adjectives.
No hindsight: all inputs are truncated to the decision date.
"""
from __future__ import annotations
from datetime import date
import numpy as np
import pandas as pd


def annual_range_context(close: pd.DataFrame, ticker: str, asof: date,
                         *, prepared_history: pd.DataFrame | None = None) -> dict:
    """52-week position needs >=200 observed closes; otherwise unknown."""
    result = dict(low_52w=None, high_52w=None, position_52w=None,
                  week_52_status='Insufficient 52-week price history',
                  observed_sessions=0, recent_5d=None, previous_5d=None)
    if prepared_history is None:
        from .leaderboard_review import _history
        prepared_history = _history(close, asof)
    if ticker not in prepared_history:
        return result
    # Prevent partial series / early IPO data being called a full-year range.
    raw = pd.to_numeric(prepared_history[ticker].tail(252), errors='coerce')
    result['observed_sessions'] = int(raw.notna().sum())
    if len(raw) < 200 or raw.isna().any() or (raw <= 0).any():
        return result
    low, high, last = float(raw.min()), float(raw.max()), float(raw.iloc[-1])
    position = 0.5 if np.isclose(high, low) else float(np.clip((last-low)/(high-low), 0, 1))
    result.update(low_52w=low, high_52w=high, position_52w=position)
    if len(raw) >= 11:
        result.update(recent_5d=float(raw.iloc[-1]/raw.iloc[-6]-1),
                      previous_5d=float(raw.iloc[-6]/raw.iloc[-11]-1))
    result['week_52_status'] = ('Near the lower end of the annual range; a falling trend is still possible' if position < .25 else
                                'In the lower-middle annual range; check for an early turn' if position < .60 else
                                'In the upper-middle annual range; assess recent acceleration' if position < .85 else
                                'Near the annual high; check whether good news is already reflected in price')
    return result


def news_range_context(year: dict, *, checked: bool, event_count: int | None = None,
                       negative_events: int = 0, positive_events: int = 0) -> str:
    """52-week price context for *distinct* news events, never a return adjustment."""
    if not checked:
        return 'News feed unavailable or not yet checked; no news-based entry clearance.'
    pos = year.get('position_52w')
    if pos is None:
        return 'Current news checked; fewer than 200 valid sessions for 52-week price context.'
    label = f"Price at {pos:.0%} of the observed 52-week low-to-high range. "
    if event_count is None:
        events = 'News-event count unavailable. '
    elif event_count == 0:
        events = 'No qualifying recent distinct headlines returned. '
    else:
        events = f'{event_count} distinct recent news event(s), not publisher article count. '
    if negative_events:
        events += f'{negative_events} event(s) contain negative headline keywords. '
    if positive_events:
        events += f'{positive_events} event(s) contain positive headline keywords. '
    caution = ''
    if pos >= .85 and positive_events:
        caution = 'Positive headlines near an annual high may already be partly reflected in price; avoid assuming unlimited upside. '
    elif pos < .25 and negative_events:
        caution = 'Negative headlines near the annual low increase uncertainty; a rebound is not confirmed. '
    elif .25 <= pos < .65 and positive_events:
        caution = 'Potential catalyst below the annual high; wait for price/volume confirmation before calling it a new trend. '
    elif negative_events:
        caution = 'Review the negative company news separately from the numerical forecast. '
    return (label + events + caution + year['week_52_status'] +
            '. Headline-word tone is not a validated return effect; the primary forecast stays separate.')
