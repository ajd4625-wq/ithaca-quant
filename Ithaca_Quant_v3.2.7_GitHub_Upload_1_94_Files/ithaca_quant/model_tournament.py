"""Fail-closed, three-model stock-by-stock competition.

Research only. Historical selection and audit labels are strictly matured before
an as-of signal; audit tests use non-overlapping H-session decision windows.
A one-sided paired test and Benjamini-Hochberg adjustment protect against
thousands of spurious ticker-specific winning claims.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import t as student_t
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss

from .features import FEATURES, EXTENDED_FEATURES, REGIME_FEATURES, NEWS_FEATURES, FUNDAMENTAL_FEATURES
from .model import fit_ensemble, robust_target, training_snapshot, _choose_with_scale
from .earnings_expectations import EARNINGS_FEATURES

AGENT_MODELS = ('Ridge', 'Gradient Boosting', 'Random Forest')

@dataclass
class TournamentResult:
    predictions: pd.DataFrame
    audit: pd.DataFrame
    status: str
    qualified_tickers: int


def _feature_families(frame: pd.DataFrame):
    """Independent feature views; unavailable archived inputs are never invented.

    A recent Form 4 API fetch is NOT a historical Form 4 archive. Insider features
    join only when the panel explicitly contains date-eligible archived signals.
    """
    def add_available(cols, extras, minimum_dates=0, flag=None):
        if not all(key in frame for key in extras):
            return cols
        if flag is not None:
            if flag not in frame or frame.loc[frame[flag] > 0, 'date'].nunique() < minimum_dates:
                return cols
        if not np.isfinite(frame[extras].to_numpy(float)).all():
            return cols
        return cols + [c for c in extras if c not in cols]

    technical = list(FEATURES)
    ridge = add_available(technical.copy(), list(REGIME_FEATURES))
    boosted = add_available(technical.copy(), list(EXTENDED_FEATURES))
    boosted = add_available(boosted, list(NEWS_FEATURES), minimum_dates=60, flag='news_available')
    boosted = add_available(boosted, list(EARNINGS_FEATURES), minimum_dates=60,
                            flag='earnings_surprise_available')
    forest = add_available(technical.copy(), list(EXTENDED_FEATURES))
    forest = add_available(forest, list(FUNDAMENTAL_FEATURES), minimum_dates=60, flag='sec_available')
    forest = add_available(forest, ['insider_net_buy_log_30d', 'insider_buy_count_30d',
                                     'insider_available'], minimum_dates=60, flag='insider_available')
    return {'Ridge':ridge, 'Gradient Boosting':boosted, 'Random Forest':forest}


def _fit_agents(frame: pd.DataFrame, cols: dict[str,list[str]], *, fast: bool):
    if frame.empty or len(frame) < 350 or frame.date.nunique() < 100:
        raise ValueError('Insufficient mature observations for independent model training')
    if len(frame) > 40_000:
        frame = frame.sample(40_000, random_state=43).sort_values(['date','ticker'])
    y = robust_target(frame.target.to_numpy(float))
    models = {
        'Ridge': make_pipeline(StandardScaler(), Ridge(alpha=75)),
        'Gradient Boosting': HistGradientBoostingRegressor(
            learning_rate=.045, max_iter=40 if fast else 75, max_leaf_nodes=11,
            max_depth=4, min_samples_leaf=30, l2_regularization=10,
            early_stopping=False, random_state=41),
        'Random Forest': RandomForestRegressor(
            n_estimators=25 if fast else 55, max_depth=7, min_samples_leaf=18,
            max_features=.75, random_state=29, n_jobs=3),
    }
    for name, model in models.items():
        model.fit(frame[cols[name]].to_numpy(float), y)
    return models


def _predictions(models, frame, cols):
    return pd.DataFrame({name: np.clip(model.predict(frame[cols[name]].to_numpy(float)), -.5, .5)
                         for name, model in models.items()}, index=frame.index)


def _independent_dates(frame, horizon):
    dates = pd.DatetimeIndex(sorted(frame.date.unique()))
    if len(dates) == 0:
        return frame.iloc[:0].copy()
    return frame.loc[frame.date.isin(set(dates[::max(1,int(horizon))]))].copy()


def _observations(frame, scores, baseline, horizon):
    cols = ['ticker','date','target'] + [c for c in ['forward_return','vol_20','market_mom_20'] if c in frame]
    rows = frame[cols].copy()
    for k in AGENT_MODELS:
        rows[k] = scores[k].to_numpy()
    rows['Baseline'] = np.asarray(baseline,float)
    return _independent_dates(rows,horizon)


def _one_sided_pvalue(differences):
    """Test positive paired baseline-MAE minus challenger-MAE; conservative for low N."""
    diffs = np.asarray(differences,float)
    diffs = diffs[np.isfinite(diffs)]
    if len(diffs) < 3 or not np.isfinite(diffs.std(ddof=1)) or diffs.std(ddof=1) <= 1e-12:
        return 0.0 if len(diffs)>=3 and diffs.min() > 1e-12 else 1.0
    t = diffs.mean() / (diffs.std(ddof=1)/np.sqrt(len(diffs)))
    return float(student_t.sf(t, df=len(diffs)-1))


def _bh_adjust(p_values):
    """Benjamini-Hochberg adjusted q values across ALL ticker challenges."""
    p=np.asarray(p_values,float)
    if not len(p): return np.array([])
    order=np.argsort(p)
    ranked=p[order]
    reverse=np.minimum.accumulate((ranked * len(p) / np.arange(1,len(p)+1))[::-1])[::-1]
    out=np.ones(len(p))
    out[order]=np.clip(reverse,0,1)
    return out




def _rank_and_portfolio_quality(observed: pd.DataFrame, predictions: np.ndarray,
                                top_n: int = 5, cost_bps: float = 10):
    """Ranking IC and simple cost-aware top-N paper Sharpe across audit dates.

    For tournament *gating only*. Full next-close tradability and delisting
    treatment are implemented by the separate production walk-forward engine.
    """
    work=observed[['date','ticker','target']].copy()
    work['score']=np.asarray(predictions,float)
    correlations=[]; net=[]; prev=set()
    for _, group in work.groupby('date',sort=True):
        if len(group)<3: continue
        corr=group[['score','target']].corr(method='spearman').iloc[0,1]
        if np.isfinite(corr): correlations.append(float(corr))
        selected=group.sort_values(['score','ticker'],ascending=[False,True]).head(top_n)
        tickers=set(selected.ticker)
        turnover=len(tickers.symmetric_difference(prev)) / (2*max(1,len(selected)))
        ret=float(selected.target.mean()) - turnover*cost_bps/10000
        net.append(ret)
        prev=tickers
    ic=float(np.mean(correlations)) if correlations else np.nan
    sharpe=float(np.mean(net)/(np.std(net,ddof=1)+1e-8)) if len(net)>=3 else np.nan
    return ic,sharpe

def _conditional_event_odds(selection, audit, current, name, threshold):
    """Winner-aligned absolute-event probabilities, trained on selection alone.

    Require honest independent audit improvement over a constant-rate baseline;
    otherwise return NaN instead of presenting an unrelated event model as
    calibrated to the tournament winner.
    """
    if not {'forward_return','vol_20','market_mom_20'}.issubset(selection.columns):
        return np.nan
    xcols=[name, 'vol_20', 'market_mom_20']
    early=selection.dropna(subset=['forward_return']+xcols)
    later=audit.dropna(subset=['forward_return']+xcols)
    if len(early)<150 or len(later)<80 or early.date.nunique()<20 or later.date.nunique()<10:
        return np.nan
    y=(early.forward_return.to_numpy(float)>=threshold).astype(int)
    ytest=(later.forward_return.to_numpy(float)>=threshold).astype(int)
    if min(y.sum(),len(y)-y.sum())<15 or min(ytest.sum(),len(ytest)-ytest.sum())<5:
        return np.nan
    model=make_pipeline(StandardScaler(), LogisticRegression(C=.03,max_iter=300))
    model.fit(early[xcols].to_numpy(float),y)
    check=model.predict_proba(later[xcols].to_numpy(float))[:,1]
    rate=float(y.mean())
    if brier_score_loss(ytest,check) >= brier_score_loss(ytest,np.full(len(ytest),rate)):
        return np.nan
    row=np.array([[current[name],current['vol_20'],current['market_mom_20']]],float)
    if not np.isfinite(row).all(): return np.nan
    return float(model.predict_proba(row)[0,1])


def run_model_tournament(panel: pd.DataFrame, asof, *, horizon: int = 20,
                         fast: bool = True, baseline_forecasts: pd.DataFrame | None = None,
                         production_features: tuple[str,...] | None = None,
                         min_windows: int = 20, min_improvement: float = .03,
                         max_false_discovery_rate: float = .05,
                         boom_return: float = .20) -> TournamentResult:
    """A challenger must improve BOTH time-block MAEs and survive FDR testing.

    All evidence is historical, not forward-live evidence. Fixed production
    feature family and fast/full setting used for every incumbent comparison.
    """
    if horizon < 1 or min_windows < 12 or not 0 < min_improvement < 1 or not 0 < max_false_discovery_rate <= .2:
        raise ValueError('Invalid horizon or evidence requirements')
    asof=pd.Timestamp(asof)
    missing=set(FEATURES+['ticker','date','label_end','target']) - set(panel.columns)
    if missing: raise ValueError('Missing tournament columns: '+', '.join(sorted(missing)))
    current=panel.loc[panel.date==asof].copy()
    base=pd.DataFrame({'ticker':current.ticker.to_numpy()},index=current.index)
    base['agent_winner']='Existing ensemble'
    base['agent_edge_status']='Unverified: insufficient independent evidence'
    base['agent_selection_windows']=0
    base['agent_audit_windows']=0
    base['agent_audit_mae']=np.nan
    base['agent_baseline_mae']=np.nan
    base['agent_picked_on_historical_evidence']=False
    base['agent_vote_spread']=np.nan
    base['agent_baseline_equivalent']=False
    base['agent_baseline_selection_features']=''
    base['agent_baseline_audit_features']=''
    base['agent_q_value']=np.nan
    base['agent_forecast_error_scale']=np.nan
    base['agent_prob_gain']=np.nan
    base['agent_prob_boom']=np.nan
    base['agent_probability_status']='Not verified for winning model'
    base['agent_feature_sources']=''
    for name in AGENT_MODELS:
        base['agent_'+name.lower().replace(' ','_')+'_forecast']=np.nan
    base['agent_winning_forecast']=np.nan
    if current.empty: return TournamentResult(base,pd.DataFrame(),'No current tickers',0)
    if not np.isfinite(current[FEATURES].to_numpy(float)).all():
        raise ValueError('Nonfinite current model features')
    # Six years of potential audit history; PRODUCTION incumbent still uses its
    # exact four-year training lookback on every historical fit date.
    history=training_snapshot(panel,asof,window_years=6)
    days=pd.DatetimeIndex(sorted(history.date.unique()))
    block=max(80,horizon*(min_windows+1))
    if len(days)<160+2*block:
        if len(history)>=350 and history.date.nunique()>=100:
            families=_feature_families(history)
            agents=_fit_agents(history,families,fast=fast)
            guesses=_predictions(agents,current,families)
            for name in AGENT_MODELS:
                base['agent_'+name.lower().replace(' ','_')+'_forecast']=guesses[name].to_numpy()
            base['agent_vote_spread']=(guesses.max(axis=1)-guesses.min(axis=1)).to_numpy()
        return TournamentResult(base,pd.DataFrame(columns=['ticker','selected_champion','audit_qualified']),
                'Insufficient non-overlapping history; baseline retained.',0)
    selection_start=days[-2*block]; audit_start=days[-block]
    fit_selection=history.loc[(history.date >= selection_start-pd.DateOffset(years=4)) &
                               (history.label_end<selection_start)]
    selection=history.loc[(history.date>=selection_start)&(history.label_end<audit_start)]
    fit_audit=history.loc[(history.date>=audit_start-pd.DateOffset(years=4)) &
                           (history.label_end<audit_start)]
    audit=history.loc[history.date>=audit_start]
    if min(len(fit_selection),len(selection),len(fit_audit),len(audit))<100 or fit_selection.date.nunique()<100:
        return TournamentResult(base,pd.DataFrame(),'Insufficient embargoed history',0)
    # Reproduce the TRUE production incumbent's dynamic feature selection,
    # scaling and fast/full model sizing as they stood at each historical date.
    # If those distinct historical models don't match today's incumbent feature
    # schema, audit evidence cannot justify replacing the production model.
    sel_features,_,_,sel_scale=_choose_with_scale(fit_selection,selection_start,fast=fast)
    aud_features,_,_,aud_scale=_choose_with_scale(fit_audit,audit_start,fast=fast)
    if production_features is None:
        production_features=_choose_with_scale(training_snapshot(panel,asof),asof,fast=fast)[0]
    production_features=tuple(production_features)
    same_pipeline=tuple(sel_features)==tuple(aud_features)==production_features
    same_pipeline=same_pipeline and all(c in panel for c in production_features) and all(
        np.isfinite(f[list(production_features)].to_numpy(float)).all()
        for f in [fit_selection,selection,fit_audit,audit,current])
    base['agent_baseline_equivalent']=bool(same_pipeline)
    base['agent_baseline_selection_features']=','.join(sel_features)
    base['agent_baseline_audit_features']=','.join(aud_features)
    if not same_pipeline:
        return TournamentResult(base,pd.DataFrame(columns=['ticker','selected_champion','audit_qualified']),
            'Production feature schema changed across historical audits; no promotions',0)
    families=_feature_families(fit_selection)
    # Preserve feature definition in all periods; a newly available archive
    # may not silently rewrite the evaluation feature schema.
    for cols in families.values():
        for f in [selection,fit_audit,audit,current]:
            if not set(cols).issubset(f.columns) or not np.isfinite(f[cols].to_numpy(float)).all():
                return TournamentResult(base,pd.DataFrame(),
                   'Challenger features not continuously available; no promotions',0)
    sel_models=_fit_agents(fit_selection,families,fast=fast)
    baseline_sel=fit_ensemble(fit_selection,fast=fast,features=production_features)
    sel_ensemble,_=baseline_sel.predict(selection)
    sel_shrink=sel_scale
    # Conservative incumbent calibration: use a purged pre-selection block,
    # never selection/audit outcome labels to estimate slope.
    selection_rows=_observations(selection,_predictions(sel_models,selection,families),
                                   sel_ensemble*sel_shrink,horizon)
    audit_models=_fit_agents(fit_audit,families,fast=fast)
    audit_ensemble=fit_ensemble(fit_audit,fast=fast,features=production_features)
    aud_ensemble,_=audit_ensemble.predict(audit)
    audit_shrink=aud_scale
    audit_rows=_observations(audit,_predictions(audit_models,audit,families),
                             aud_ensemble*audit_shrink,horizon)
    # Freeze champion based only on selection, then audit a SINGLE champion per ticker.
    candidates=[]
    # Global model ranking diagnostics computed once; avoid O(tickers^2)
    # full-universe sorts during a large stock screen.
    base_ic,base_sharpe=_rank_and_portfolio_quality(audit_rows,audit_rows.Baseline.to_numpy(float))
    ranking_checks={name:_rank_and_portfolio_quality(audit_rows,audit_rows[name].to_numpy(float))
                    for name in AGENT_MODELS}
    for ticker in current.ticker:
        s=selection_rows.loc[selection_rows.ticker==ticker]
        a=audit_rows.loc[audit_rows.ticker==ticker]
        base.loc[base.ticker==ticker,'agent_selection_windows']=int(s.date.nunique())
        base.loc[base.ticker==ticker,'agent_audit_windows']=int(a.date.nunique())
        if min(s.date.nunique(),a.date.nunique()) < min_windows: continue
        champion=min(AGENT_MODELS,key=lambda k:(np.abs(s.target-s[k]).mean(),k))
        se=float(np.abs(s.target-s[champion]).mean())
        sb=float(np.abs(s.target-s.Baseline).mean())
        ae=float(np.abs(a.target-a[champion]).mean())
        ab=float(np.abs(a.target-a.Baseline).mean())
        gain=np.abs(a.target-a.Baseline).to_numpy(float)-np.abs(a.target-a[champion]).to_numpy(float)
        pvalue=_one_sided_pvalue(gain)
        # Selection is independent of audit. Compare actual cross-sectional
        # ranking and cost-aware paper performance to the incumbent too.
        contender_ic,contender_sharpe=ranking_checks[champion]
        nondegradation=(not np.isfinite(base_ic) or contender_ic>=base_ic-.01) and (
             not np.isfinite(base_sharpe) or contender_sharpe>=base_sharpe-.05)
        dir_agent=float(((a[champion]>0)==(a.target>0)).mean())
        dir_base=float(((a.Baseline>0)==(a.target>0)).mean())
        good=bool(se < sb*(1-min_improvement) and ae < ab*(1-min_improvement)
                  and ae < np.abs(a.target).mean() and dir_agent>=dir_base and nondegradation)
        candidates.append({'ticker':ticker,'selected_champion':champion,
            'selection_windows':len(s),'audit_windows':len(a),
            'selection_mae':se,'selection_baseline_mae':sb,
            'audit_mae':ae,'audit_baseline_mae':ab,'audit_p_value':pvalue,
            'audit_direction_hit':dir_agent,'audit_baseline_direction_hit':dir_base,
            'baseline_equivalent':True,'selection_baseline_features':','.join(production_features),
            'audit_baseline_features':','.join(production_features),'preliminary_pass':good,
            'agent_features':','.join(families[champion]),
            'audit_rank_ic':contender_ic,'audit_baseline_rank_ic':base_ic,
            'audit_paper_sharpe':contender_sharpe,'audit_baseline_paper_sharpe':base_sharpe,
            'error_scale':float(np.std(a.target-a[champion],ddof=1)),
            'selected_audit_rows':a})
    if not candidates:
        # Even with insufficient audited evidence, show independently trained
        # predictions (never promote them) when there is mature fit history.
        if len(final_train := training_snapshot(panel,asof,window_years=4))>=350 and final_train.date.nunique()>=100:
            families_now=_feature_families(final_train)
            models_now=_fit_agents(final_train,families_now,fast=fast)
            guesses=_predictions(models_now,current,families_now)
            for name in AGENT_MODELS:
                base['agent_'+name.lower().replace(' ','_')+'_forecast']=guesses[name].to_numpy()
            base['agent_vote_spread']=(guesses.max(axis=1)-guesses.min(axis=1)).to_numpy()
        return TournamentResult(base,pd.DataFrame(columns=['ticker','selected_champion','audit_qualified']),
                    'All stock competitions lacked sufficient independent observations',0)
    adjusted=_bh_adjust([row['audit_p_value'] for row in candidates])
    selected={}
    for row,q in zip(candidates,adjusted):
        ticker=row['ticker']; champion=row['selected_champion']
        qualifies=bool(row['preliminary_pass'] and q<=max_false_discovery_rate)
        row['audit_q_value']=float(q)
        row['audit_qualified']=qualifies
        sel=base.ticker==ticker
        base.loc[sel,'agent_audit_mae']=row['audit_mae']
        base.loc[sel,'agent_baseline_mae']=row['audit_baseline_mae']
        base.loc[sel,'agent_q_value']=float(q)
        if qualifies:
            selected[ticker]=row
            base.loc[sel,'agent_winner']=champion
            base.loc[sel,'agent_edge_status']='Passed embargoed holdouts, direction and FDR test; historical only'
            base.loc[sel,'agent_picked_on_historical_evidence']=True
            base.loc[sel,'agent_forecast_error_scale']=row['error_scale']
            base.loc[sel,'agent_feature_sources']=row['agent_features']
        else:
            base.loc[sel,'agent_edge_status']='No statistically qualified audit lift; baseline retained'
    # Only after the entire contest is frozen do we refit on matured labels.
    final_train=training_snapshot(panel,asof,window_years=4)
    live_families=_feature_families(final_train)
    if live_families!=families:
        for ticker in selected:
            sel=base.ticker==ticker
            base.loc[sel,'agent_winner']='Existing ensemble'
            base.loc[sel,'agent_picked_on_historical_evidence']=False
            base.loc[sel,'agent_edge_status']='Predictor input schema drifted; baseline retained'
        selected={}
    models=_fit_agents(final_train,families,fast=fast)
    live=_predictions(models,current,families)
    for name in AGENT_MODELS:
        base['agent_'+name.lower().replace(' ','_')+'_forecast']=live[name].to_numpy()
    base['agent_vote_spread']=(live.max(axis=1)-live.min(axis=1)).to_numpy()
    for i,(_,r) in enumerate(current.iterrows()):
        if r.ticker in selected:
            champion=selected[r.ticker]['selected_champion']
            base.iloc[i,base.columns.get_loc('agent_winning_forecast')]=float(live.iloc[i][champion])
            # Probabilities are only shown when calibrated for this actual
            # winning regressor, using selection to train and audit to check.
            event_sel=selection_rows; event_aud=audit_rows
            odds_gain=_conditional_event_odds(event_sel,event_aud,
                 {'vol_20':r.get('vol_20',np.nan),'market_mom_20':r.get('market_mom_20',np.nan),
                  champion:float(live.iloc[i][champion])},champion,0.000001)
            odds_boom=_conditional_event_odds(event_sel,event_aud,
                 {'vol_20':r.get('vol_20',np.nan),'market_mom_20':r.get('market_mom_20',np.nan),
                  champion:float(live.iloc[i][champion])},champion,boom_return)
            base.iloc[i,base.columns.get_loc('agent_prob_gain')]=odds_gain
            base.iloc[i,base.columns.get_loc('agent_prob_boom')]=odds_boom
            base.iloc[i,base.columns.get_loc('agent_probability_status')]=(
                'Selection-calibrated and independently checked' if np.isfinite(odds_gain) and np.isfinite(odds_boom)
                else 'Insufficient independent calibration; some odds unavailable')
    if baseline_forecasts is not None:
        fallback=baseline_forecasts.set_index('ticker')['forecast_excess']
        base['agent_winning_forecast']=base['agent_winning_forecast'].fillna(base.ticker.map(fallback))
    # Keep only scalar audit artifacts; never serialize historical label rows.
    evidence=pd.DataFrame([{k:v for k,v in x.items() if k!='selected_audit_rows'} for x in candidates])
    return TournamentResult(base.reset_index(drop=True),evidence,
         f'Three independent trained families challenged the full production baseline; '
         f'{len(selected)} ticker winners passed selection, audit and FDR.',len(selected))
