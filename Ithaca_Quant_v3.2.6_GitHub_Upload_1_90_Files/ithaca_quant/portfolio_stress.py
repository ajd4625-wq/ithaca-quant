"""Risk attribution and scenario stress for an educational virtual portfolio."""
from __future__ import annotations
import numpy as np
import pandas as pd


def stress_summary(close:pd.DataFrame, weights:dict[str,float], benchmark='SPY'):
    stocks = [x for x,w in weights.items() if x in close and w > 0 and x != benchmark]
    if not stocks or benchmark not in close:
        return {}
    prices = close[stocks+[benchmark]].dropna().tail(756)
    returns = prices.pct_change(fill_method=None).dropna()
    if len(returns) < 65:
        return {}
    stock_return = returns[stocks]
    bench = returns[benchmark]
    w = pd.Series(weights, dtype=float).reindex(stocks).fillna(0).clip(lower=0)
    portfolio = stock_return.mul(w).sum(axis=1)
    bench_var = bench.var()
    betas = stock_return.apply(lambda s: float(s.cov(bench)/bench_var) if bench_var>0 else np.nan)
    weighted_beta = float(betas.mul(w).sum())
    corr = stock_return.corr()
    count = 0
    pairings = []
    for a, lhs in enumerate(stocks):
        for rhs in stocks[a+1:]:
            value = corr.loc[lhs,rhs]
            if pd.notna(value):
                pairings.append(float(value))
                count += 1
    worst = float(portfolio.quantile(.05))
    tail = float(portfolio[portfolio<=worst].mean())
    scenarios = {f'SPY {fall:+.0%} hypothetical shock':float(weighted_beta*fall)
                 for fall in (-.05,-.10,-.20)}
    return {'beta_to_spy':weighted_beta, 'max_initial_weight':float(w.max()),
            'herfindahl':float(w.pow(2).sum()),
            'mean_pairwise_correlation':float(np.mean(pairings)) if pairings else np.nan,
            'daily_95pct_historical_var':worst,
            'daily_95pct_historical_tail_mean':tail,
            'shock_scenarios':scenarios, 'sessions':len(returns),
            'note':'Scenario shocks use backward-looking beta, ignore nonlinear behavior '
                   'and are not guaranteed loss limits.'}
