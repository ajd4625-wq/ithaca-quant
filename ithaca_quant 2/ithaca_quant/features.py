"""Point-in-time technical indicators and future labels.

All predictors use prices observed at/before the signal date. Targets use
forward data solely for supervised training and historical evaluation.
"""
import numpy as np
import pandas as pd

from .config import BENCHMARK

FUNDAMENTAL_FEATURES = ["sec_revenue_yoy", "sec_net_margin", "sec_filing_age", "sec_available", "sec_eps_yoy", "sec_revenue_accel"]
REGIME_FEATURES = ["market_regime_trend", "market_regime_stress"]
NEWS_FEATURES = ["news_sentiment_7d", "news_count_7d", "news_available",
                 "news_earnings_7d", "news_guidance_7d", "news_analysts_7d",
                 "news_regulatory_7d", "news_macro_7d"]

# v2.1 candidate evidence group. These are point-in-time price/liquidity and
# same-day cross-sectional features. They enter the forecast ONLY if they
# improve a chronological, embargoed holdout (see model.choose_evidence_features).
EXTENDED_FEATURES = [
    "mom_1", "mom_252_skip", "high_252_gap", "beta_60", "idio_vol_60",
    "max_ret_20", "skew_60", "log_dollar_vol_20",
    "cs_rank_mom_20", "cs_rank_mom_60", "cs_rank_vol_20", "cs_rank_rel_60",
    "cs_rank_drawdown_60", "cs_rank_volume_ratio",
]
# Neutral values used when a long look-back is not yet available.
_EXTENDED_NEUTRAL = {"mom_1": 0.0, "mom_252_skip": 0.0, "high_252_gap": 0.0, "beta_60": 1.0,
                     "idio_vol_60": 0.0, "max_ret_20": 0.0, "skew_60": 0.0,
                     "log_dollar_vol_20": 0.0}

FEATURES = [
    "mom_5", "mom_20", "mom_60", "rel_20", "rel_60", "vol_20", "vol_60",
    "ma_gap_20", "ma_gap_60", "drawdown_60", "volume_ratio",
    "market_mom_20", "market_vol_20",
]


def build_panel(close: pd.DataFrame, volume: pd.DataFrame, horizon: int = 20,
                fundamentals: dict | None = None, news: dict | None = None,
                earnings: dict | None = None) -> pd.DataFrame:
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
            "market_regime_trend": pd.Series(np.where(bm20 > .04, 1.0,
                                                        np.where(bm20 < -.04, -1.0, 0.0)), index=bm20.index),
            "market_regime_stress": (bmvol >= .30).astype(float),
            "forward_return": p.shift(-horizon) / p - 1,
            "benchmark_forward": bmforward,
            "label_end": ending,
        }, index=close.index)
        features["target"] = features["forward_return"] - features["benchmark_forward"]
        # --- v2.1 extended point-in-time features (use data at/before the row date) ---
        rb = benchmark.pct_change(fill_method=None)
        cov60 = r.rolling(60, min_periods=40).cov(rb)
        var60 = rb.rolling(60, min_periods=40).var()
        beta60 = (cov60 / var60.replace(0, np.nan)).clip(-3, 5)
        total_var = r.rolling(60, min_periods=40).var()
        resid_var = (total_var - beta60.pow(2) * var60).clip(lower=0)
        features["mom_1"] = r
        features["mom_252_skip"] = p.shift(21) / p.shift(252) - 1
        features["high_252_gap"] = p / p.rolling(252, min_periods=120).max() - 1
        features["beta_60"] = beta60
        features["idio_vol_60"] = np.sqrt(resid_var) * np.sqrt(252)
        features["max_ret_20"] = r.rolling(20, min_periods=15).max()
        features["skew_60"] = r.rolling(60, min_periods=40).skew().clip(-5, 5)
        dollar = (p * v).rolling(20, min_periods=15).mean()
        features["log_dollar_vol_20"] = np.log1p(dollar.where(dollar > 0))
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
        if earnings is not None:
            from .earnings_expectations import expectations_features, EARNINGS_FEATURES
            extras = expectations_features(symbol, earnings.get(symbol), close.index)
            for column in EARNINGS_FEATURES:
                features[column] = extras[column].to_numpy(dtype=float)
        frames.append(features)
    panel = pd.concat(frames, ignore_index=True)
    # Same-day cross-sectional ranks (only information available on that date).
    by_date = panel.groupby("date")
    breadth = by_date["ticker"].transform("size")
    for source, name in (("mom_20", "cs_rank_mom_20"), ("mom_60", "cs_rank_mom_60"),
                         ("vol_20", "cs_rank_vol_20"), ("rel_60", "cs_rank_rel_60"),
                         ("drawdown_60", "cs_rank_drawdown_60"),
                         ("volume_ratio", "cs_rank_volume_ratio")):
        ranked = by_date[source].rank(pct=True)
        # Ranks are meaningless for a tiny same-day universe.
        panel[name] = ranked.where(breadth >= 5).fillna(0.5)
    for name, neutral in _EXTENDED_NEUTRAL.items():
        panel[name] = panel[name].replace([np.inf, -np.inf], np.nan).fillna(neutral)
    # A missing future label is intentional: latest dates must remain rankable.
    valid = panel[FEATURES].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    return panel.loc[valid & (panel["close"] > 0)].reset_index(drop=True)
