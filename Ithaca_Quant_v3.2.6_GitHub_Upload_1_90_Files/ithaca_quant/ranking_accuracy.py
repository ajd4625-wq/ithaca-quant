"""Purged, auditable outperformance classifier for stock discovery.

A model is *not* promoted merely because it predicts >80% on a selected subset.
All comparisons use out-of-period outcomes, known by each decision date.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss
from .features import FEATURES, EXTENDED_FEATURES

@dataclass
class RankingResult:
    candidates: pd.DataFrame
    selection: dict
    audit: dict
    activated: bool
    evidence: str
    model: str


def _scores(truth, p, dates):
    truth=np.asarray(truth,dtype=float)
    p=np.asarray(p,dtype=float)
    idx=np.isfinite(truth) & np.isfinite(p)
    truth, p=truth[idx],p[idx]
    dates=np.asarray(dates)[idx]
    if not len(truth):
        return {'n':0,'dates':0,'brier':None,'baseline_brier':None,'accuracy':None,
                'top_quartile_hit':None,'all_hit':None,'high_confidence_n':0,'high_confidence_coverage':0.0,'high_confidence_accuracy':None}
    baseline=float(truth.mean())
    tops=[]
    for day in np.unique(dates):
        d=dates==day
        if d.sum() < 5: continue
        threshold=np.quantile(p[d],.75)
        tops.extend(truth[d & (p>=threshold)].tolist())
    confident=np.abs(p-.5)>=.20
    return {'n':int(len(truth)),'dates':int(len(np.unique(dates))),
            'brier':float(brier_score_loss(truth,p)),
            'baseline_brier':float(brier_score_loss(truth,np.full(len(truth),baseline))),
            'accuracy':float(((p>.5)==truth).mean()),
            'top_quartile_hit':float(np.mean(tops)) if tops else None,
            'all_hit':baseline,
            'high_confidence_n':int(confident.sum()),'high_confidence_coverage':float(confident.mean()),
            'high_confidence_accuracy':float(((p[confident]>.5)==truth[confident]).mean()) if confident.any() else None}


def rank_outperformance(panel:pd.DataFrame, *, asof=None, min_tickers=10):
    """Train on past dated features; select and audit on disjoint, purged periods.

    Returns an independently screened sidecar ranking, never silently replaces
    the established numerical stock-price forecast. No simulation uses today's
    future returns as a training label.
    """
    if panel.empty:
        raise ValueError('A historical multi-stock panel is required')
    df=panel.copy()
    df['date']=pd.to_datetime(df['date'])
    df['label_end']=pd.to_datetime(df['label_end'])
    now=pd.Timestamp(asof) if asof is not None else df['date'].max()
    df=df.loc[df['date']<=now]
    latest=df.loc[df['date']==df['date'].max()].copy()
    if latest['ticker'].nunique()<min_tickers:
        raise ValueError(f'Need at least {min_tickers} distinct stocks on the current date')
    cols=[k for k in FEATURES+EXTENDED_FEATURES if k in df.columns]
    df[cols]=df[cols].replace([np.inf,-np.inf],np.nan)
    df[cols]=df[cols].fillna(0).clip(-10000,10000)
    eligible=df.loc[df['target'].notna() & df['label_end'].notna() & (df['label_end']<=now)].copy()
    dates=pd.DatetimeIndex(sorted(eligible['date'].unique()))
    if len(dates)<310:
        return RankingResult(pd.DataFrame(),{}, {},False,'Not enough mature trading dates for independent fit/selection/audit periods.','none')
    sel_start, audit_start=dates[-220],dates[-110]
    fit=eligible.loc[eligible['label_end']<sel_start]
    selection=eligible.loc[(eligible['date']>=sel_start) & (eligible['label_end']<audit_start)]
    audit=eligible.loc[eligible['date']>=audit_start]
    if min(len(fit),len(selection),len(audit))<300 or min(fit.ticker.nunique(), selection.ticker.nunique(), audit.ticker.nunique())<min_tickers:
        return RankingResult(pd.DataFrame(),{}, {},False,'Insufficient independent samples in purged blocks.','none')
    fit=fit.tail(45000)
    # Evaluation policy is fixed before looking at audit performance.
    p_train=(fit['target'].astype(float)>0).astype(int)
    if p_train.nunique()<2:
        return RankingResult(pd.DataFrame(),{}, {},False,'Only one outcome class was observed in training.','none')
    model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=220,C=0.18))
    model.fit(fit[cols],p_train)
    selection_p=model.predict_proba(selection[cols])[:,1]
    s=_scores((selection['target']>0).astype(float),selection_p, selection['date'].dt.strftime('%Y-%m-%d'))
    valid=lambda m: (m['n']>=300 and m['dates']>=20 and m['brier']<m['baseline_brier']*.99 and
                     m['top_quartile_hit'] is not None and m['top_quartile_hit']>m['all_hit']+.025)
    selected=valid(s)
    a={}
    if selected:
        # Audit is completely separate and cannot tune or choose feature thresholds.
        model_audit=make_pipeline(StandardScaler(),LogisticRegression(max_iter=220,C=0.18))
        training_audit=eligible.loc[eligible['label_end']<audit_start].tail(50000)
        model_audit.fit(training_audit[cols],(training_audit['target']>0).astype(int))
        ap=model_audit.predict_proba(audit[cols])[:,1]
        a=_scores((audit['target']>0).astype(float),ap, audit['date'].dt.strftime('%Y-%m-%d'))
    qualified=selected and valid(a)
    if not selected:
        return RankingResult(pd.DataFrame(),s,{},False,
             'The candidate failed selection-period Brier and/or ranking uplift thresholds; baseline retained.','Logistic rank classifier')
    if not qualified:
        return RankingResult(pd.DataFrame(),s,a,False,
             'Candidate did not replicate on the untouched audit period; baseline retained.','Logistic rank classifier')
    production=make_pipeline(StandardScaler(),LogisticRegression(max_iter=220,C=0.18))
    production.fit(eligible.tail(60000)[cols],(eligible.tail(60000)['target']>0).astype(int))
    prob=production.predict_proba(latest[cols])[:,1]
    out=pd.DataFrame({'ticker':latest['ticker'].tolist(),'p_outperform':prob,
                      'early_mom_accel':latest['mom_5_accel'].to_numpy(float) if 'mom_5_accel' in latest else 0,
                      'return_52w_position':latest['range_252'].to_numpy(float) if 'range_252' in latest else np.nan})
    out=out.sort_values('p_outperform',ascending=False).reset_index(drop=True)
    return RankingResult(out,s,a,True,
         'Selected on a purged period and replicated on an independent audit; future accuracy remains unknown.',
         'Logistic rank classifier')
