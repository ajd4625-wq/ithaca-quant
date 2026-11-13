"""Search panel arithmetic: forecast ranges, risk estimates and review dates."""
import numpy as np
import pandas as pd


def price_scenarios(last_price: float, excess: float, spy_history: pd.Series,
                    annual_vol: float, horizon: int) -> dict:
    """Convert relative forecast to an illustrative price using ZERO SPY forecast.

    This is NOT an absolute-return model. Market benchmark uncertainty is omitted
    from the center estimate, but the volatility range is explicitly shown.
    """
    if last_price <= 0 or horizon < 1 or not np.isfinite(last_price):
        raise ValueError("Invalid latest adjusted price or horizon")
    sigma = max(0.0, float(annual_vol)) * np.sqrt(horizon / 252)
    return {"target": last_price * (1 + float(excess)),
            "lower_1sigma": max(0, last_price * (1 + float(excess) - sigma)),
            "upper_1sigma": last_price * (1 + float(excess) + sigma),
            "risk_1sigma_pct": sigma * 100,
            "method": "Excess-return forecast with 0% assumed benchmark return; ±1 historical-volatility scale (not calibrated interval)."}


def review_dates(asof: pd.Timestamp, horizon: int, entry_watch: str, exit_review: str) -> dict:
    """Dates for *checking conditions*, never claimed optimal execution dates."""
    asof = pd.Timestamp(asof).normalize()
    return {"entry_review": (asof + pd.offsets.BDay(1)).date(),
            "exit_review": (asof + pd.offsets.BDay(horizon)).date(),
            "entry_condition": entry_watch, "exit_condition": exit_review}
