"""A/B walk-forward accuracy benchmark: legacy v2.0 model vs v2.2 upgrades.

    python scripts/accuracy_benchmark.py                 # offline synthetic market
    python scripts/accuracy_benchmark.py --live AAPL MSFT NVDA ...   # real Yahoo data

Both arms use the SAME panel, windows, embargo and evaluator; only the model
switch (ITHACA_LEGACY_MODEL) differs. Lower MAE / higher rank IC is better.
The synthetic market only proves the pipeline mechanics; judge real accuracy
with --live on your own universe (>= 40 tickers recommended).
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ithaca_quant.backtest import run_walk_forward  # noqa: E402
from ithaca_quant.data import MarketData  # noqa: E402
from ithaca_quant.features import build_panel  # noqa: E402


def structured_market(n_stocks=40, sessions=1300, seed=0) -> MarketData:
    """Fat-tailed returns, volatility regimes, betas and weak, realistic factor premia."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-11-10", periods=sessions)
    regime = np.zeros(sessions, dtype=int)
    for t in range(1, sessions):
        regime[t] = regime[t - 1] if rng.random() > 0.01 else rng.integers(0, 2)
    market_vol = np.where(regime == 1, 0.017, 0.008)
    market = rng.standard_t(5, sessions) * market_vol / np.sqrt(5 / 3) + 0.0004
    beta = rng.uniform(0.5, 1.7, n_stocks)
    idio = rng.uniform(0.010, 0.026, n_stocks)
    quality = rng.normal(0, 1, n_stocks)
    close, volume = {"SPY": 100 * np.exp(np.cumsum(market))}, {"SPY": rng.lognormal(17, .2, sessions)}
    state = np.zeros((sessions, n_stocks))
    rets = np.zeros((sessions, n_stocks))
    for t in range(1, sessions):
        mom_signal = state[max(0, t - 252):max(1, t - 21)].sum(0) if t > 252 else np.zeros(n_stocks)
        mom_z = (mom_signal - mom_signal.mean()) / (mom_signal.std() + 1e-9)
        rev_z = -(rets[max(0, t - 5):t].sum(0) - rets[max(0, t - 5):t].sum(0).mean())
        rev_z = rev_z / (rev_z.std() + 1e-9)
        alpha = 0.00008 * mom_z + 0.00006 * rev_z + 0.00005 * quality - 0.00005 * (idio - idio.mean()) / idio.std()
        shock = rng.standard_t(4, n_stocks) * idio / np.sqrt(2)
        rets[t] = beta * market[t] + alpha + shock
        state[t] = rets[t]
    for i in range(n_stocks):
        close[f"S{i:02d}"] = 80 * np.exp(np.cumsum(np.clip(rets[:, i], -.4, .4)))
        volume[f"S{i:02d}"] = rng.lognormal(14.5 + .3 * quality[i], .35, sessions).round()
    return MarketData(pd.DataFrame(close, index=dates), pd.DataFrame(volume, index=dates), "synthetic", [])


def arm(panel, close, legacy, horizon, periods):
    os.environ["ITHACA_LEGACY_MODEL"] = "1" if legacy else "0"
    m = run_walk_forward(panel, close, horizon=horizon, top_n=6, max_periods=periods, fast=True).metrics
    return {"excess_mae": m["excess_mae"], "zero_mae": m["excess_zero_mae"],
            "rank_ic": m["mean_rank_ic"], "direction_hit": m["direction_hit"],
            "gain_brier": m["gain_brier"], "gain_base_brier": m["gain_baseline_brier"],
            "boom_brier": m["boom_brier"], "boom_base_brier": m["boom_baseline_brier"],
            "model_return": m["portfolio_return"], "spy_return": m["benchmark_return"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", nargs="*", help="tickers to download from Yahoo instead of synthetic data")
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--periods", type=int, default=12)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    rows = []
    if a.live:
        from ithaca_quant.data import download_market_data
        md = download_market_data(a.live, years=6)
        panel = build_panel(md.close, md.volume, a.horizon)
        for name, legacy in (("v2.0 legacy", True), ("v2.2", False)):
            rows.append({"arm": name, "seed": "live", **arm(panel, md.close, legacy, a.horizon, a.periods)})
    else:
        for seed in range(a.seeds):
            md = structured_market(seed=seed)
            panel = build_panel(md.close, md.volume, a.horizon)
            for name, legacy in (("v2.0 legacy", True), ("v2.2", False)):
                rows.append({"arm": name, "seed": seed, **arm(panel, md.close, legacy, a.horizon, a.periods)})
    table = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print(table.round(4).to_string(index=False))
    print("\nMean by arm:")
    print(table.drop(columns="seed").groupby("arm").mean(numeric_only=True).round(4).T.to_string())


if __name__ == "__main__":
    main()
