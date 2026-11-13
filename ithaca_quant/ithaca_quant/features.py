"""Point-in-time technical indicators and future labels.

All predictors use prices observed at/before the signal date. Targets use
forward data solely for supervised training and historical evaluation.
"""
import numpy as np
import pandas as pd

from .config import BENCHMARK

FUNDAMENTAL_FEATURES = ["sec_revenue_yoy", "sec_net_margin", "sec_filing_age", "sec_available"]
NEWS_FEATURES = ["news_sentiment_7d", "news_count_7d", "news_available"]

FEATURES = [
    "mom_5", "mom_20", "mom_60", "rel_20", "rel_60", "vol_20", "vol_60",
    "ma_gap_20", "ma_gap_60", "drawdown_60", "volume_ratio",
    "market_mom_20", "market_vol_20",
]


def build_panel(close: pd.DataFrame, volume: pd.DataFrame, horizon: int = 20,
                fundamentals: dict | None = None, news: dict | None = None) -> pd.DataFrame:
    if BENCHMARK not in close.columns:
        raise ValueError("SPY benchmark missing.")
    if horizon < 1:
        raise ValueError("Forecast horizon must be positive.")
    benchmark = close[BENCHMARK]
    bm20 = benchmark.pct_change(20, fill_method=None)
    bm60 = benchmark.pct_change(60, fill_method=None)
    bmvol = benchmark.pct_change(fill_method=None).rolling(20).std() * np.sqrt(252)
    bmforward = benchmark.shift(-horizon) / benchmark - 1
    ending = pd.Series(close.index, index=close.index).shift(-horizon)
    frames = []
    for symbol in close.columns.drop(BENCHMARK):
        p = close[symbol]
        r = p.pct_change(fill_method=None)
        v = volume[symbol] if symbol in volume else pd.Series(np.nan, index=p.index)
        top60 = p.rolling(60).max()
        features = pd.DataFrame({
            "date": close.index,
            "ticker": symbol,
            "close": p,
            "mom_5": p.pct_change(5, fill_method=None),
            "mom_20": p.pct_change(20, fill_method=None),
            "mom_60": p.pct_change(60, fill_method=None),
            "rel_20": p.pct_change(20, fill_method=None) - bm20,
            "rel_60": p.pct_change(60, fill_method=None) - bm60,
            "vol_20": r.rolling(20).std() * np.sqrt(252),
            "vol_60": r.rolling(60).std() * np.sqrt(252),
            "ma_gap_20": p / p.rolling(20).mean() - 1,
            "ma_gap_60": p / p.rolling(60).mean() - 1,
            "drawdown_60": p / top60 - 1,
            "volume_ratio": v / v.rolling(20).mean().replace(0, np.nan) - 1,
            "market_mom_20": bm20,
            "market_vol_20": bmvol,
            "forward_return": p.shift(-horizon) / p - 1,
            "benchmark_forward": bmforward,
            "label_end": ending,
        }, index=close.index)
        features["target"] = features["forward_return"] - features["benchmark_forward"]
        if fundamentals is not None:
            from .fundamentals import filing_features
            snapshot = fundamentals.get(symbol)
            extras = filing_features(snapshot if snapshot is not None else pd.DataFrame(), close.index)
            for column in FUNDAMENTAL_FEATURES:
                features[column] = extras[column].to_numpy(dtype=float)
        if news is not None:
            from .news_archive import archived_features
            sample = news.get(symbol)
            extras = archived_features(symbol, close.index, headlines=sample)
            for column in NEWS_FEATURES:
                features[column] = extras[column].to_numpy(dtype=float)
        frames.append(features)
    panel = pd.concat(frames, ignore_index=True)
    # A missing future label is intentional: latest dates must remain rankable.
    valid = panel[FEATURES].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    return panel.loc[valid & (panel["close"] > 0)].reset_index(drop=True)
