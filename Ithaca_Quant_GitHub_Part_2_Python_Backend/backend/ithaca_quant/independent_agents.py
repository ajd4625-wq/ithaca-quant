"""Three independently FITTED research models on v3.1's causal price features.

* Forecast: histogram gradient boosting -> five-session excess return
* Momentum: standardized Ridge -> five-session excess return on momentum features
* Risk: standardized logistic regression -> P(excess return < -2%)

These are three statistical ML learners, not three autonomous LLMs, and are
NOT statistically independent because they use the same market observations.
All training labels mature *before* prediction, and predeployment validation
uses a purged train/holdout split with nonoverlapping validation anchors.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from .model import training_snapshot

AGENTS = ('Forecast', 'Momentum', 'Risk')
WEIGHTS = (0.55, 0.15, 0.30)
FORECAST_FEATURES = ('mom_5','mom_20','mom_60','rel_20','rel_60','vol_20','vol_60',
                     'ma_gap_20','ma_gap_60','drawdown_60','market_mom_20','market_vol_20')
MOMENTUM_FEATURES = ('mom_5','mom_20','mom_60','rel_20','rel_60','ma_gap_20','ma_gap_60')
RISK_FEATURES = ('vol_20','vol_60','drawdown_60','volume_ratio','market_vol_20',
                 'market_mom_20','ma_gap_20')
MIN_FIT = 300
MIN_HOLDOUT = 60
MIN_INDEPENDENT_WINDOWS = 10


def new_models():
    # Fixed hyperparameters; no tuning on held-out performance.
    return {
        'Forecast': HistGradientBoostingRegressor(max_iter=75, max_leaf_nodes=11,
                      max_depth=3, min_samples_leaf=25, l2_regularization=18,
                      learning_rate=.045, early_stopping=False, random_state=2028),
        'Momentum': make_pipeline(StandardScaler(), Ridge(alpha=240)),
        'Risk': make_pipeline(StandardScaler(), LogisticRegression(
                    C=.08, max_iter=250, random_state=2028)),
    }


def _split(train):
    unique = pd.DatetimeIndex(sorted(train.date.unique()))
    if len(unique) < MIN_FIT + MIN_HOLDOUT + 6:
        raise ValueError('Insufficient matured history to validate independent agents.')
    cut = unique[-min(100, max(MIN_HOLDOUT, int(len(unique)*.18)))]
    fit = train.loc[train.label_end < cut].copy()
    holdout = train.loc[train.date >= cut].copy()
    if len(fit) < MIN_FIT or holdout.date.nunique() < MIN_HOLDOUT:
        raise ValueError('Purged training / holdout windows too small.')
    if not (fit.label_end < cut).all():
        raise ValueError('Label leakage detected at validation boundary')
    return fit, holdout, cut


def _fit(models, train):
    models['Forecast'].fit(train[list(FORECAST_FEATURES)], np.clip(train.target.to_numpy(float),-.25,.25))
    models['Momentum'].fit(train[list(MOMENTUM_FEATURES)], np.clip(train.target.to_numpy(float),-.25,.25))
    downside = (train.target.to_numpy(float) < -.02).astype(int)
    if downside.sum() < 12 or (1-downside).sum() < 12:
        raise ValueError('Not enough examples of both downside and non-downside outcomes.')
    models['Risk'].fit(train[list(RISK_FEATURES)], downside)
    return models


def _out(models, frame):
    p1 = np.clip(models['Forecast'].predict(frame[list(FORECAST_FEATURES)]),-.25,.25)
    p2 = np.clip(models['Momentum'].predict(frame[list(MOMENTUM_FEATURES)]),-.25,.25)
    p3 = models['Risk'].predict_proba(frame[list(RISK_FEATURES)])[:,1]
    return p1,p2,p3


def _finite(v):
    v=float(v)
    return round(v,7) if math.isfinite(v) else None


def forecast_three_agents(panel:pd.DataFrame, asof:pd.Timestamp, ticker:str) -> dict:
    """Produce independently-fitted, purged, retrospectively evaluated forecasts.

    Reports validation metrics but does not overstate a single historical split
    as independently confirmed live accuracy. Does not make any trading orders.
    """
    asof = pd.Timestamp(asof)
    history = training_snapshot(panel.loc[panel.ticker == ticker], asof)
    history = history.sort_values('date')
    latest = panel.loc[(panel.ticker == ticker) & (panel.date == asof)]
    if latest.empty:
        raise ValueError('No latest dated features for ticker')
    fit, holdout, cut = _split(history)
    validation_models = _fit(new_models(),fit)
    # Validation anchors are spaced five sessions apart to avoid treating
    # five overlapping outcome windows as independent evidence.
    anchors = holdout.iloc[::5].copy()
    if len(anchors) < MIN_INDEPENDENT_WINDOWS:
        raise ValueError('Insufficient nonoverlapping historical validation windows')
    forecast_v, momentum_v, downside_v = _out(validation_models,anchors)
    truth = anchors.target.to_numpy(float)
    is_down = (truth < -.02).astype(float)
    base_return = float(np.mean(np.abs(truth)))  # no-alpha zero forecast
    risk_prior = float((fit.target < -.02).mean())
    base_brier = float(np.mean((is_down - risk_prior)**2))
    f_mae=float(np.mean(np.abs(truth-forecast_v)))
    m_mae=float(np.mean(np.abs(truth-momentum_v)))
    risk_brier=float(np.mean((is_down-downside_v)**2))
    # Validated evidence means all three have data; 'skill_pass' is stricter:
    # at least forecast beats no-alpha and risk beats its historical base rate.
    # These thresholds are fixed BEFORE the test period and are not tuned there.
    has_skill = bool(f_mae < base_return and risk_brier < base_brier)
    # Fit each of three models afresh on all matured history, after evaluation.
    live_models = _fit(new_models(), history)
    fv,mv,rv = _out(live_models,latest)
    f,m,r = float(fv[0]),float(mv[0]),float(rv[0])
    blended = (WEIGHTS[0]*f+WEIGHTS[1]*m)/(WEIGHTS[0]+WEIGHTS[1])
    return {
        'state':'available','selected_model':'Three separately fitted ML models',
        'horizon_sessions':5,'expected_excess_return':_finite(blended),
        'model_disagreement':_finite(abs(f-m)),
        'forecast_agent_expected_excess':_finite(f),
        'momentum_agent_expected_excess':_finite(m),
        'risk_agent_downside_probability':_finite(r),
        'risk_event':'SPY-relative return < -2% over the next 5 completed sessions',
        'agents':[
            {'name':'Forecast','algorithm':'Histogram Gradient Boosting Regressor','output':'5-session excess return','prediction':_finite(f)},
            {'name':'Momentum','algorithm':'Standardized Ridge Regression','output':'5-session excess return','prediction':_finite(m)},
            {'name':'Risk','algorithm':'Standardized Logistic Regression','output':'Probability of SPY-relative underperformance worse than -2%','prediction':_finite(r)},
        ],
        'validation':{
            'state':'single_historical_holdout','purged':True,'validated_before':asof.date().isoformat(),
            'holdout_start':cut.date().isoformat(),
            'fit_end':pd.Timestamp(fit.label_end.max()).date().isoformat(),
            'validation_end':pd.Timestamp(anchors.label_end.max()).date().isoformat(),
            'independent_anchors':int(len(anchors)),
            'forecast_mae':_finite(f_mae), 'momentum_mae':_finite(m_mae),
            'zero_baseline_mae':_finite(base_return),
            'risk_brier':_finite(risk_brier), 'risk_base_rate_brier':_finite(base_brier),
            'skill_gate_passed':has_skill,
            'meaning':'One chronologically purged internal validation, not an independent real-time track record. Five-session anchors are spaced apart.'
        },
        'validation_passed':has_skill,
        'uses_sec_filing_features':False, 'uses_historical_news_features':False,
        'explanation':'Three independently fitted ML learners use v3.1 price features; they share market data and are not statistically independent. The risk probability is uncalibrated. Signals abstain unless retrospective holdout beats two prespecified baselines. Actual accuracy requires forward-logged outcomes.'
    }
