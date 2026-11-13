"""Walk-forward research simulation (no future data used when making predictions).

Signal after closing price t; buy at that adjusted close, sell after H sessions.
This closing-price fill is idealized and cannot be replicated precisely live.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from .config import BENCHMARK, MAX_POSITION, MIN_PRICE
from .model import fit_ensemble, training_snapshot, choose_evidence_features
from .probability import fit_event_model
from .validation import overall_quality, validate_oos_data


@dataclass
class BacktestResult:
    periods: pd.DataFrame
    metrics: dict[str, float]
    predictions: pd.DataFrame  # one unseen ticker outcome per nonoverlapping window


def _weight_map(selected: list[str], exposure: float, max_position: float) -> dict[str, float]:
    if not selected:
        return {}
    weight = min(exposure / len(selected), max_position)
    return {ticker: weight for ticker in selected}


def _period_return(rows: pd.DataFrame, holdings: dict[str, float], prior: dict[str, float], cost_bps: float):
    rets = rows.set_index("ticker")["forward_return"].to_dict()
    # Include cash as the uninvested portion, both before and after rebalancing.
    turnover = sum(abs(holdings.get(t, 0) - prior.get(t, 0))
                   for t in set(prior) | set(holdings))
    cost = turnover * (cost_bps / 10_000)
    gross = sum(weight * float(rets.get(t, 0)) for t, weight in holdings.items())
    net = (1 + gross) * (1 - cost) - 1
    denominator = 1 + gross
    post = {t: w * (1 + rets[t]) / denominator for t, w in holdings.items()}
    return net, post, turnover


def _max_drawdown(values: pd.Series) -> float:
    if values.empty:
        return float("nan")
    return float((values / values.cummax() - 1).min())


def run_walk_forward(
    panel: pd.DataFrame,
    close: pd.DataFrame,
    *,
    horizon: int = 20,
    top_n: int = 6,
    exposure: float = 0.9,
    max_position: float = MAX_POSITION,
    cost_bps: float = 10.0,
    max_periods: int = 12,
    fast: bool = False,
    boom_return: float = 0.20,
) -> BacktestResult:
    """Nonoverlapping next-H-session evaluation windows.

    At signal date t, only prior targets whose label_end < t are used to fit.
    Entire stock universe is known in advance: survivorship bias still exists.
    """
    dates = close[BENCHMARK].dropna().index
    if not 5 <= top_n <= 20:
        raise ValueError("Choose between 5 and 20 stocks.")
    if not (0 < exposure <= 1 and 0 < max_position <= 1):
        raise ValueError("Exposure and position cap must lie between 0 and 1.")
    # Go backwards in H-session strides, end no later than final observable label.
    min_signal_idx = max(320, horizon + 120)
    last_idx = len(dates) - horizon - 1
    indices = list(range(last_idx, min_signal_idx - 1, -horizon))[:max_periods]
    indices.sort()
    if not indices:
        raise ValueError("Insufficient history for walk-forward validation.")

    nav = 1.0; momentum_nav = 1.0; spy_nav = 1.0
    prev = {}; prev_momentum = {}
    records = []
    oos_rows = []
    for idx in indices:
        when = dates[idx]
        ending = dates[idx + horizon]
        train = training_snapshot(panel, when)
        if len(train) < 350 or train["date"].nunique() < 100:
            continue
        candidates = panel.loc[
            (panel["date"] == when) & (panel["close"] > MIN_PRICE) &
            (panel["forward_return"].notna())
        ].copy()
        if len(candidates) < top_n:
            continue
        selected_features, _, _ = choose_evidence_features(train, when, fast=fast)
        ensemble = fit_ensemble(train, fast=fast, features=selected_features)
        scores, _ = ensemble.predict(candidates)
        candidates["pred"] = scores
        # Both event forecasts are fitted strictly on matured past labels.
        boom = fit_event_model(train, event_return=boom_return)
        gain = fit_event_model(train, event_return=0.000001)
        boom_p = boom.predict(candidates)
        gain_p = gain.predict(candidates)
        direction_naive = bool((train['target'] > 0).mean() >= 0.5)
        for j, candidate in enumerate(candidates.itertuples(index=False)):
            actual = float(candidate.forward_return)
            observed_relative = float(candidate.target)
            oos_rows.append({
                'signal_date': when, 'end_date': ending,
                'ticker': candidate.ticker,
                'pred_excess': float(scores[j]),
                'realized_excess': observed_relative,
                'realized_return': actual,
                'benchmark_return': float(candidate.benchmark_forward),
                'p_gain': float(gain_p[j]), 'p_boom': float(boom_p[j]),
                'gain_baseline': float(gain.event_rate),
                'boom_baseline': float(boom.event_rate),
                'gain_event': int(actual > 0.000001),
                'boom_event': int(actual >= boom_return),
                'naive_direction_positive': direction_naive,
            })
        candidates = candidates.sort_values("pred", ascending=False)
        selected = candidates.head(top_n)["ticker"].tolist()
        momentum = candidates.sort_values("rel_60", ascending=False).head(top_n)["ticker"].tolist()
        weights = _weight_map(selected, exposure, max_position)
        momweights = _weight_map(momentum, exposure, max_position)
        strat_r, prev, turnover = _period_return(candidates, weights, prev, cost_bps)
        mom_r, prev_momentum, _ = _period_return(candidates, momweights, prev_momentum, cost_bps)
        spy_r = float(close.loc[ending, BENCHMARK] / close.loc[when, BENCHMARK] - 1)
        nav *= 1 + strat_r
        momentum_nav *= 1 + mom_r
        spy_nav *= 1 + spy_r
        # Cross-sectional Spearman rank information coefficient for period.
        ic = candidates[["pred", "target"]].corr(method="spearman").iloc[0, 1]
        records.append({
            "date": when, "end": ending, "model_return": strat_r,
            "momentum_return": mom_r, "spy_return": spy_r,
            "model_nav": nav, "momentum_nav": momentum_nav, "spy_nav": spy_nav,
            "model_turnover": turnover,
            "rank_ic": float(ic) if np.isfinite(ic) else np.nan,
            "top_stocks": ", ".join(selected),
        })
    periods = pd.DataFrame(records)
    if periods.empty:
        raise ValueError("Not enough qualifying past windows to evaluate.")
    model_eq = pd.concat([pd.Series([1.0]), periods["model_nav"]], ignore_index=True)
    spy_eq = pd.concat([pd.Series([1.0]), periods["spy_nav"]], ignore_index=True)
    predictions = pd.DataFrame(oos_rows)
    validate_oos_data(predictions)
    quality = overall_quality(predictions)
    metrics = {
        "portfolio_return": float(periods["model_nav"].iloc[-1] - 1),
        "benchmark_return": float(periods["spy_nav"].iloc[-1] - 1),
        "momentum_return": float(periods["momentum_nav"].iloc[-1] - 1),
        "portfolio_max_drawdown": _max_drawdown(model_eq),
        "benchmark_max_drawdown": _max_drawdown(spy_eq),
        "mean_rank_ic": float(periods["rank_ic"].mean()),
        "period_hit_rate": float((periods["model_return"] > periods["spy_return"]).mean()),
        "periods": float(len(periods)),
        "average_turnover": float(periods["model_turnover"].mean()),
        "boom_brier": quality['boom_brier'],
        "boom_baseline_brier": quality['boom_baseline_brier'],
        "boom_observed_frequency": float(predictions.loc[predictions['p_boom'].notna(), 'boom_event'].mean()),
        "boom_mean_probability": float(predictions['p_boom'].mean()),
        "boom_evaluated_predictions": quality['boom_scored'],
        "direction_hit": quality['direction_hit'],
        "direction_baseline": quality['direction_baseline'],
        "excess_mae": quality['excess_mae'],
        "excess_zero_mae": quality['excess_zero_mae'],
        "gain_brier": quality['gain_brier'],
        "gain_baseline_brier": quality['gain_baseline_brier'],
        "gain_evaluated_predictions": quality['gain_scored'],
        "ticker_evaluations": quality['ticker_outcomes'],
        "independent_signal_windows": quality['signal_windows'],
    }
    return BacktestResult(periods=periods, metrics=metrics, predictions=predictions)
