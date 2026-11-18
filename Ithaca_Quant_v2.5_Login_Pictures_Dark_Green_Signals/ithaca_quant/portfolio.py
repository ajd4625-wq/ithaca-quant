"""Hypothetical buy-and-hold virtual portfolio and historical risk analytics."""
import numpy as np
import pandas as pd

from .config import MAX_POSITION, MAX_STOCKS, MIN_PRICE, MIN_STOCKS


def validate_allocations(
    allocations: dict[str, float], close: pd.DataFrame,
    entry_date: pd.Timestamp, max_position: float = MAX_POSITION,
) -> list[str]:
    errors = []
    if any(not np.isfinite(float(w)) or float(w) < 0 for w in allocations.values()):
        errors.append("All weights must be finite and nonnegative.")
    allocations = {t.upper(): float(w) for t, w in allocations.items()
                   if np.isfinite(float(w)) and float(w) > 0}
    if not MIN_STOCKS <= len(allocations) <= MAX_STOCKS:
        errors.append(f"Hold {MIN_STOCKS}–{MAX_STOCKS} individual stocks (StockTrak description).")
    if any(w > max_position + 1e-9 for w in allocations.values()):
        errors.append(f"No initial position may exceed {max_position:.0%}.")
    if any(w < 0 for w in allocations.values()) or sum(allocations.values()) > 1.0000001:
        errors.append("Weights must be nonnegative and sum to 100% or less.")
    if entry_date not in close.index:
        errors.append("Entry date is not a price-data trading day.")
    else:
        for ticker in allocations:
            if ticker not in close or not np.isfinite(close.loc[entry_date, ticker]):
                errors.append(f"No valid entry price for {ticker} on this date.")
            elif close.loc[entry_date, ticker] <= MIN_PRICE:
                errors.append(f"{ticker} must trade above ${MIN_PRICE:g} at entry.")
    return errors


def simulate_buy_hold(
    close: pd.DataFrame,
    entry_date: pd.Timestamp,
    allocations: dict[str, float],
    capital: float = 1_000_000,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Hypothetical shares purchased at historical adjusted close on entry day.

    This is *not* a reconstruction of StockTrak actual fills or holdings.
    """
    errors = validate_allocations(allocations, close, entry_date)
    if errors:
        raise ValueError(" ".join(errors))
    shares = {}
    invested = 0.0
    for ticker, weight in allocations.items():
        if weight <= 0:
            continue
        buy_price = float(close.loc[entry_date, ticker])
        quantity = int(np.floor(capital * weight / buy_price))
        shares[ticker] = quantity
        invested += quantity * buy_price
    cash = capital - invested
    history = close.loc[entry_date:, list(shares)].ffill(limit=2)
    if history.isna().any().any():
        raise ValueError("Price history has gaps that cannot be reliably filled.")
    value = history.mul(pd.Series(shares)).sum(axis=1) + cash
    equity = pd.DataFrame({"portfolio": value, "return_pct": value / capital - 1})
    held = pd.DataFrame({
        "ticker": list(shares),
        "shares": list(shares.values()),
    })
    held["entry_price"] = held["ticker"].map(close.loc[entry_date].to_dict())
    held["latest_price"] = held["ticker"].map(close.iloc[-1].to_dict())
    held["initial_value"] = held["shares"] * held["entry_price"]
    held["market_value"] = held["shares"] * held["latest_price"]
    held["pnl"] = held["market_value"] - held["initial_value"]
    return equity, held, cash


def historical_risk(close: pd.DataFrame, allocations: dict[str, float], horizon: int = 20) -> dict:
    """Backward-looking risk estimates for a static-weight illustrative basket."""
    tickers = [t for t, w in allocations.items() if w > 0 and t in close]
    if not tickers:
        return {}
    returns = close[tickers].pct_change(fill_method=None).dropna(how="any")
    returns = returns.tail(504)
    if len(returns) < max(100, horizon + 20):
        return {}
    weights = pd.Series({t: allocations[t] for t in tickers})
    daily = returns.mul(weights).sum(axis=1)
    windows = (1 + daily).rolling(horizon).apply(np.prod, raw=True).dropna() - 1
    var = float(windows.quantile(0.05))
    cvar = float(windows[windows <= var].mean())
    equity = (1 + daily).cumprod()
    return {
        "annualized_volatility": float(daily.std() * np.sqrt(252)),
        "historical_95pct_20d_return": var,
        "historical_95pct_20d_tail_avg": cvar,
        "historical_max_drawdown": float((equity / equity.cummax() - 1).min()),
        "lookback_days": int(len(daily)),
    }
