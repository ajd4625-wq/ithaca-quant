"""Color-coded review flags driven by the app's actual entry and exit signals.

Not trading instructions or validated probabilities. A refreshed 20-session
forecast is required; old forecast records never acquire a green signal by
assuming that a positive return alone is an ENTRY WATCH.
"""
from __future__ import annotations

from datetime import date
import math


def _number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _flag(color, label, reason):
    return {'color': color, 'label': label, 'reason': reason}


def classify_holding(forecast: dict | None, *, today: date | None = None,
                     quote_available: bool = True, position_weight: float | None = None,
                     latest_price: float | None = None) -> dict:
    """Map real `plan_signals` outputs to cautious colors for owned holdings.

    Priority: missing/stale information -> yellow; confirmed exit-review -> red;
    over-concentration -> yellow; exceptionally strong qualifying entry -> dark
    green; normal qualifying entry -> green; otherwise yellow. The position's
    own profit/loss does not mechanically set its color.

    Dark green is an *extra strict research screen*, not a measured confidence
    level. It does not assert that a stock has a 70% chance of appreciating.
    """
    today = today or date.today()
    if not forecast:
        return _flag('YELLOW', '🟡 UPDATE FORECAST',
                     'No saved 20-session forecast. Run Update selected forecast first.')
    try:
        asof = date.fromisoformat(str(forecast.get('asof', ''))[:10])
    except (ValueError, TypeError):
        asof = None
    if asof is None or (today-asof).days > 4 or asof > today:
        return _flag('YELLOW', '🟡 UPDATE FORECAST',
                     'Forecast is stale or invalid; refresh before interpreting entry or exit conditions.')
    if not quote_available:
        return _flag('YELLOW', '🟡 VERIFY PRICE',
                     'No usable current/delayed price; cannot safely assess the position.')

    excess = _number(forecast.get('forecast_excess'))
    if excess is None:
        return _flag('YELLOW', '🟡 UPDATE FORECAST', 'No usable 20-session return forecast.')

    entry = str(forecast.get('entry_watch') or '').strip().upper()
    exit_label = str(forecast.get('exit_review') or '').strip().upper()
    if 'REVIEW EXIT' in exit_label or excess < -0.02:
        return _flag('RED', '🔴 REVIEW EXIT',
                     'The saved exit-review signal or negative SPY-relative forecast triggered an exit review; not an automatic sale.')

    # The review level uses the model's daily price basis; comparing it to a
    # split-adjusted or otherwise incompatible quote could cause a false alert.
    current = _number(latest_price)
    review_level = _number(forecast.get('review_level'))
    reference = _number(forecast.get('model_price'))
    if current is not None and review_level is not None and reference is not None and reference > 0:
        if current > 0 and (current/reference < 0.5 or current/reference > 2):
            return _flag('YELLOW', '🟡 VERIFY PRICE',
                         'Quote and model-price bases differ substantially; check corporate actions before using the review level.')
        if current <= review_level:
            return _flag('RED', '🔴 REVIEW EXIT',
                         'Current quoted price reached the model review level; verify price adjustments and investigate, not an automatic sale.')

    weight = _number(position_weight)
    if weight is not None and weight > 0.25:
        return _flag('YELLOW', '🟡 POSITION RISK',
                     'Holding exceeds 25% of total portfolio value; review concentration before considering additions.')

    if entry == 'ENTRY WATCH' and excess > 0.02:
        # All standard ENTRY WATCH conditions have already been computed by
        # plan_signals (positive 20/60d trends, positive relative strength,
        # >2% SPY-relative forecast). The dark-green tier additionally requires
        # substantial model edge, a usable calibrated probability, controlled
        # annualized volatility, and reasonable existing position sizing.
        # Missing estimates *never* silently qualify for the top tier.
        gain_probability = _number(forecast.get('prob_gain'))
        annual_volatility = _number(forecast.get('vol_20'))
        if (excess >= 0.06 and gain_probability is not None and gain_probability >= 0.70
                and annual_volatility is not None and 0 <= annual_volatility <= 0.60
                and exit_label == 'MONITOR' and (weight is None or weight <= 0.15)):
            return _flag('DARK_GREEN', '🟩 STRONG ENTRY WATCH',
                         'Strictest entry screen: ENTRY WATCH plus >=6% modeled SPY-relative return, '
                         '>=70% modeled gain probability, <=60% annualized volatility, '
                         'and <=15% holding weight when known. Research tier only: these thresholds '
                         'have not been proven to identify profitable buys.')
        return _flag('GREEN', '🟢 ENTRY WATCH',
                     'Positive SPY-relative forecast (>2%), positive 20/60-day trends and positive relative strength; '
                     'does not meet every extra dark-green criterion. Not a buy order.')
    if entry == 'WATCH / CONFIRM':
        return _flag('YELLOW', '🟡 WATCH / CONFIRM',
                     'The model favors this stock but not all trend/relative-strength conditions confirm the entry.')
    if entry == 'WAIT':
        return _flag('YELLOW', '🟡 WAIT',
                     'The existing entry screen has not found enough favorable evidence.')
    return _flag('YELLOW', '🟡 UPDATE FORECAST',
                 'This older forecast does not contain an entry signal. Update it to apply the new colors.')
