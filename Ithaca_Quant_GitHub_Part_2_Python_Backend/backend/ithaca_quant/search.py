"""Search panel arithmetic: forecast ranges, risk estimates and review dates."""
import numpy as np
import pandas as pd


def price_scenarios(last_price: float, excess: float, spy_history: pd.Series,
                    annual_vol: float, horizon: int) -> dict:
    """Return conditional benchmark scenarios; NEVER assume a guaranteed flat SPY.

    Historical SPY median is a transparent scenario, NOT an independently
    verified stock-price forecast. Uncertainty includes SPY's own horizon
    variation, so the range is wider than an idiosyncratic stock-only band.
    """
    if last_price <= 0 or horizon < 1 or not np.isfinite(last_price) or not np.isfinite(excess):
        raise ValueError('Invalid latest adjusted price, forecast or horizon')
    spy=pd.to_numeric(spy_history, errors='coerce').dropna()
    if len(spy)>=max(120,horizon*4):
        # Use non-overlapping observed H-day market windows for distribution.
        outcomes=spy.iloc[::horizon].pct_change(fill_method=None).dropna()
        if len(outcomes)<5:
            outcomes=spy.pct_change(horizon,fill_method=None).dropna()
        low_bm, assumed, high_bm=np.quantile(outcomes,[.10,.50,.90])
        source=f'Historical SPY {horizon}-session returns (10th/50th/90th percentile), not a future SPY prediction'
    else:
        low_bm,assumed,high_bm=-.1,0.,.1
        source='Insufficient SPY history: fallback scenarios -10%, 0%, +10%; no absolute forecast'
    sigma=max(0,float(annual_vol))*np.sqrt(horizon/252)
    target=last_price*(1+float(excess)+assumed)
    lower=max(0,last_price*(1+float(excess)+low_bm-sigma))
    upper=last_price*(1+float(excess)+high_bm+sigma)
    return {'target':target,'lower_1sigma':lower,'upper_1sigma':upper,
            'risk_1sigma_pct':sigma*100,'benchmark_scenario_return':float(assumed),
            'benchmark_low_return':float(low_bm),'benchmark_high_return':float(high_bm),
            'absolute_price_forecast_verified':False,
            'method':'Conditional market scenario, not a calibrated absolute target. '+source}


def review_dates(asof: pd.Timestamp, horizon: int, entry_watch: str, exit_review: str) -> dict:
    """Dates for *checking conditions*, never claimed optimal execution dates."""
    asof = pd.Timestamp(asof).normalize()
    return {"entry_review": (asof + pd.offsets.BDay(1)).date(),
            "exit_review": (asof + pd.offsets.BDay(horizon)).date(),
            "entry_condition": entry_watch, "exit_condition": exit_review}
