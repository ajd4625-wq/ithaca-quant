"""Offline synthetic data demonstration of audit plumbing, NOT stock accuracy."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from ithaca_quant.institutional_audit import factor_audit, next_close_proxy, availability_safe_join, historical_data_health


def synthetic_inputs(seed=23):
    rng=np.random.default_rng(seed)
    dates=pd.bdate_range('2025-01-02',periods=280)
    stocks=[f'T{i:02d}' for i in range(20)]
    close=pd.DataFrame(index=dates)
    close['SPY']=100*np.exp(np.cumsum(rng.normal(.0002,.007,len(dates))))
    for symbol in stocks:
        close[symbol]=100*np.exp(np.cumsum(rng.normal(.0004,.018,len(dates))))
    rows=[]
    for index in range(50,250,10):
        start=dates[index]; end=dates[index+5]
        for stock in stocks:
            # Simulated score may be statistically related to outcome by design;
            # this does not imply any edge in actual markets.
            projected=rng.normal()
            realized=.007*projected+rng.normal(0,.024)
            rows.append({'ticker':stock,'signal_date':start,'end_date':end,
                         'pred_excess':projected,'realized_excess':realized})
    return pd.DataFrame(rows),close


def main():
    p,close=synthetic_inputs()
    a=factor_audit(p,top_fraction=.2,assumed_round_trip_bps=30)
    delay=next_close_proxy(p,close,top_fraction=.2,round_trip_bps=30)
    health=historical_data_health(close)
    print('SYNTHETIC DEMONSTRATION ONLY — NOT A LIVE BACKTEST OR ACCURACY CLAIM')
    print('Cross-sectional ranking signal test (constructed statistical relationship):')
    print(f"Independent dates: {a.metrics['windows']} | ticker outcomes: {a.metrics['ticker_outcomes']}")
    print(f"Mean Spearman IC: {a.metrics['mean_rank_ic']:+.3f}")
    print(f"Top vs average excess: {a.metrics['top_vs_universe_excess']:+.2%}")
    print(f"Date-block 95% interval: {a.metrics['uplift_ci_low']:+.2%} to {a.metrics['uplift_ci_high']:+.2%}")
    print(f"Next-close price proxy windows: {len(delay)} | mean delayed stock return: {delay.next_close_return.mean():+.2%}")
    print(f"Data quality symbols with flags: {(health.review!='No simple flags').sum()} / {len(health)}")
    print('LIMITS: synthetic data; constructed outcomes; price-proxy is not executable; survivorship unresolved.')


if __name__=='__main__':main()
