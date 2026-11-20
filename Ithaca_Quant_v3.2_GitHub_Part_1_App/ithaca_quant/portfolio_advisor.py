"""Risk-aware, long-only VIRTUAL portfolio allocation research.

Never initiates trades. Forecasts and analyst sentiment are deliberately small
bounded tilts, not assumed real expected returns. All price returns are observed
only, without filling missing prices or survivorship assertions.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from .analyst_consensus import is_fresh


@dataclass
class AllocationStudy:
    targets: dict[str, float]
    current: dict[str, float]
    forecast_signal: dict[str, float]
    analyst_signal: dict[str, float]
    annualized_vol_current: float
    annualized_vol_research: float
    predicted_turnover_fraction: float
    max_weight: float
    exposure: float
    sessions: int
    warnings: list[str]
    status: str = 'illustrative_only_unvalidated'


def _cap_normalize(weights, total, cap):
    """Bounded simplex distribution using water filling; no leverage or hidden excess."""
    w = np.maximum(np.asarray(weights, dtype=float), 0)
    if not np.all(np.isfinite(w)) or total < 0 or cap <= 0 or total > len(w)*cap+1e-8:
        raise ValueError('Invalid target exposure or concentration constraint')
    output = np.zeros(len(w))
    remaining = total
    active = np.ones(len(w), dtype=bool)
    for _ in range(len(w)+2):
        if remaining <= 1e-12:
            break
        shares = w[active]
        shares = shares / shares.sum() if shares.sum() > 0 else np.ones(shares.size)/shares.size
        proposal = remaining*shares
        blocked = proposal > cap+1e-12
        if not blocked.any():
            output[active] = proposal
            remaining = 0
            break
        positions = np.where(active)[0]
        output[positions[blocked]] = cap
        remaining -= float(cap*blocked.sum())
        active[positions[blocked]] = False
    if remaining > 1e-7:
        raise ValueError('Unable to allocate within position limits')
    return output


def portfolio_allocation_study(prices: pd.DataFrame, current_weights: dict[str, float],
                               forecasts: dict[str, dict] | None = None,
                               analyst_snapshots: dict[str, dict] | None = None,
                               *, cash_reserve: float = .10, max_position: float = .25,
                               as_of: datetime | None = None) -> AllocationStudy:
    """Study a basket of currently held stocks; no ticker discovery or recommendations.

    Missing data fails closed. A conservative covariance model and modest signals
    suggest hypothetical *weights*, not trades. No performance lift is claimed.
    """
    forecasts, analyst_snapshots = forecasts or {}, analyst_snapshots or {}
    names = sorted([s for s, w in current_weights.items() if float(w) > 0])
    if not names:
        raise ValueError('No positive-weight holdings')
    if not 0 <= cash_reserve < 1 or not 0 < max_position <= 1:
        raise ValueError('Invalid cash reserve or position maximum')
    if any(s not in prices for s in names):
        raise ValueError('Price history is missing for: '+', '.join(s for s in names if s not in prices))
    if any(not np.isfinite(float(current_weights[s])) or float(current_weights[s]) < 0 for s in names):
        raise ValueError('Holdings weights must be finite and nonnegative')
    subset = prices[names].apply(pd.to_numeric, errors='coerce').sort_index()
    # Fail closed on missing bars instead of backfilling through delistings/outages.
    subset = subset.tail(300)
    if subset.isna().any().any() or (subset <= 0).any().any():
        raise ValueError('Incomplete historical bars: cannot calculate risk safely')
    ret = subset.pct_change(fill_method=None).dropna()
    if len(ret) < 126:
        raise ValueError('Need at least 126 synchronized daily return observations')
    if (ret <= -1).any().any() or not np.isfinite(ret.to_numpy()).all():
        raise ValueError('Invalid historical returns; review adjusted prices/corporate actions')
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('as_of needs timezone')
    n = len(names)
    exposure = min(1-cash_reserve, n*max_position)
    sample_cov = ret.cov().to_numpy() * 252
    # Diagonal shrinkage stabilizes short samples and near-collinear stocks.
    cov = .45*sample_cov + .55*np.diag(np.diag(sample_cov)) + np.eye(n)*1e-7
    if not np.isfinite(cov).all():
        raise ValueError('Historical covariance is not finite')
    hist_vol = np.sqrt(np.clip(np.diag(cov), 1e-8, None))
    inverse_risk = 1 / np.maximum(hist_vol, .08)
    inv_base = _cap_normalize(inverse_risk, exposure, max_position)
    model_scores, analyst_scores = {}, {}
    warnings=[]
    for name in names:
        data = forecasts.get(name) or {}
        predicted = data.get('forecast_excess')
        try:
            asof = pd.Timestamp(data.get('asof'))
            age = (now.date() - asof.date()).days
            value = float(predicted)
            if 0 <= age <= 4 and np.isfinite(value):
                model_scores[name] = float(np.clip(value / .10, -1, 1))
            else:
                model_scores[name] = 0.
        except (ValueError, TypeError):
            model_scores[name] = 0.
        snap = analyst_snapshots.get(name)
        score = snap.get('shrunk_sentiment') if snap and is_fresh(snap, at=now) else None
        analyst_scores[name] = float(np.clip(score, -1, 1)) if score is not None and np.isfinite(score) else 0.
        if model_scores[name] == 0 and analyst_scores[name] == 0:
            warnings.append(name+': no fresh qualified conviction input; risk-only treatment')
    # Analysed, but not assumed to be proven alpha. Analyst and model signals are
    # small preference tilts; uncertain evidence never forces a position.
    conviction = np.array([.35*model_scores[t] + .20*analyst_scores[t] for t in names])
    ideal = _cap_normalize(inverse_risk * (1 + .20*conviction), exposure, max_position)
    curr = np.array([float(current_weights[t]) for t in names])
    if sum(curr) > 1 + 1e-6:
        raise ValueError('Holdings total above 100%: short leverage unsupported')
    def objective(w):
        return (2.0*(w @ cov @ w) + .32*np.sum((w-ideal)**2)
                + .20*np.sum((w-curr)**2) - .01*np.dot(conviction,w))
    opt = minimize(objective, x0=ideal, bounds=[(0.,max_position)]*n,
                   constraints=[{'type':'eq','fun':lambda w:float(sum(w)-exposure)}],
                   method='SLSQP', options={'maxiter':500,'ftol':1e-11})
    if not opt.success or not np.isfinite(opt.x).all() or abs(sum(opt.x)-exposure)>1e-5:
        raise ValueError('Risk allocation optimizer did not converge; no target generated')
    proposed = np.clip(opt.x,0,max_position)
    annual_curr = float(np.sqrt(max(curr @ cov @ curr, 0)))
    annual_prop = float(np.sqrt(max(proposed @ cov @ proposed, 0)))
    if len(names) < 5:
        warnings.append('Fewer than five holdings; concentration can be unusually high')
    warnings.append('Analyst opinions may be stale, biased or unavailable; no demonstrated positive alpha')
    return AllocationStudy(targets=dict(zip(names, map(float,proposed))),
                           current=dict(zip(names, map(float,curr))),
                           forecast_signal=model_scores, analyst_signal=analyst_scores,
                           annualized_vol_current=annual_curr,
                           annualized_vol_research=annual_prop,
                           predicted_turnover_fraction=float(np.abs(proposed-curr).sum()/2),
                           max_weight=max_position, exposure=exposure,
                           sessions=len(ret), warnings=warnings)
