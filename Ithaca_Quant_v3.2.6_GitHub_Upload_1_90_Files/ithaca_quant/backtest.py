"""Walk-forward replay of the ACTUAL production model tournament.

Signal-date eligibility precedes evaluation of outcomes; no position is
silently canceled because its subsequent closing price disappeared.
Trading simulation uses next-session adjusted CLOSE, a non-executable proxy.
Never represent this research simulation as a verified live track record.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from .config import BENCHMARK,MAX_POSITION,MIN_PRICE
from .model import forecast_asof, training_snapshot
from .validation import overall_quality,validate_oos_data
from .point_in_time import validate_membership

@dataclass
class BacktestResult:
    periods:pd.DataFrame
    metrics:dict
    predictions:pd.DataFrame
    evidence:dict|None=None


def _weight_map(selected,exposure,max_position):
    if not selected: return {}
    size=min(exposure/len(selected),max_position)
    return {ticker:size for ticker in selected}


def _period_return(rows,holdings,prior,cost_bps):
    rets=rows.set_index('ticker')['forward_return'].to_dict()
    # Never silently replace a missing / delisted return with zero.
    missing=set(holdings)-set(rets)
    if missing: raise ValueError('Missing terminal return for held stock: '+', '.join(sorted(missing)))
    if any(not np.isfinite(rets[t]) or rets[t] < -1 for t in holdings):
        raise ValueError('Invalid settled holding return; resolve delisting first')
    turnover=sum(abs(holdings.get(t,0)-prior.get(t,0)) for t in set(prior)|set(holdings))
    cost=turnover*(cost_bps/10_000)
    gross=sum(w*rets[t] for t,w in holdings.items())
    net=(1+gross)*(1-cost)-1
    post={t:w*(1+rets[t])/(1+gross) for t,w in holdings.items()}
    return net,post,turnover


def _max_drawdown(values):
    return float((values/values.cummax()-1).min()) if len(values) else float('nan')


def _archived_terminal(terminal_returns):
    if terminal_returns is None: return {}
    required={'signal_date','ticker','asof_total_return','entry_total_return','source'}
    if not required.issubset(terminal_returns.columns):
        raise ValueError('Archived terminal returns require signal_date,ticker,asof_total_return,entry_total_return,source')
    records=terminal_returns.copy()
    records['signal_date']=pd.to_datetime(records.signal_date).dt.normalize()
    records['ticker']=records.ticker.astype(str).str.upper()
    if records.duplicated(['signal_date','ticker']).any() or not records.source.eq('historical_archive').all():
        raise ValueError('Duplicate or unauthenticated archived terminal returns')
    x=records[['asof_total_return','entry_total_return']].apply(pd.to_numeric,errors='coerce')
    if (not np.isfinite(x['asof_total_return'].to_numpy(float)).all() or
            np.isinf(x['entry_total_return'].to_numpy(float)).any() or
            (x.to_numpy(float)<-1).any()):
        raise ValueError('Invalid archived terminal total returns')
    return {(pd.Timestamp(r.signal_date),r.ticker):
           (float(r.asof_total_return),float(r.entry_total_return)) for r in records.itertuples()}



def _hydrate_terminal_labels(panel, terminal_returns, close):
    """Include documented delisted-stock outcomes in TRAINING as well as scoring.

    Earlier versions repaired only realized portfolio returns, leaving
    delisted firms absent from model labels. This retains their historical
    outcomes, while training_snapshot still embargoes labels not yet matured.
    """
    if terminal_returns is None or terminal_returns.empty:
        return panel
    terminal = terminal_returns.copy()
    for col in ('signal_date',):
        terminal[col]=pd.to_datetime(terminal[col],errors='raise').dt.normalize()
    if terminal.duplicated(['signal_date','ticker']).any():
        raise ValueError('Conflicting delisting terminal outcomes')
    updated = panel.copy()
    dates = pd.to_datetime(updated.date).dt.normalize()
    # Only issuer histories already present in the decision-time panel can be patched.
    # Delisting outcomes must not fabricate observations before listing.
    for row in terminal.itertuples(index=False):
        mask = dates.eq(row.signal_date)&updated.ticker.eq(str(row.ticker).upper())
        if not mask.any():
            continue
        if 'event_date' in terminal.columns and pd.notna(getattr(row,'event_date',None)):
            event = pd.Timestamp(row.event_date).normalize()
            end = pd.to_datetime(updated.loc[mask,'label_end'])
            if (event < row.signal_date) or (end < event).any():
                raise ValueError('Delisting payoff event outside label horizon')
        ret = float(row.asof_total_return)
        if not np.isfinite(ret) or ret < -1:
            raise ValueError('Invalid delisted stock return')
        bm = pd.to_numeric(updated.loc[mask,'benchmark_forward'],errors='coerce')
        if bm.isna().any():
            raise ValueError('Missing benchmark needed to label archived delisting return')
        # Report conflicts, rather than overwrite independently known returns
        # that contradict the supplied delisting archive.
        old = pd.to_numeric(updated.loc[mask,'forward_return'],errors='coerce')
        # A stale panel might have been built before a vendor bar was withdrawn.
        # Only a CURRENT available end bar can contradict the archived payoff.
        end_date = pd.Timestamp(updated.loc[mask,'label_end'].iloc[0])
        current_end = (pd.to_numeric(close.at[end_date, str(row.ticker).upper()], errors='coerce')
                       if end_date in close.index and str(row.ticker).upper() in close else np.nan)
        if (np.isfinite(current_end) and current_end > 0 and old.notna().any()
                and not np.allclose(old.dropna(), ret, atol=.005, rtol=0)):
            raise ValueError('Delisting archive conflicts with observed complete-return history')
        updated.loc[mask,'forward_return'] = ret
        updated.loc[mask,'target'] = ret - bm.to_numpy(float)
    return updated


def run_walk_forward(panel,close,*,horizon=20,top_n=6,exposure=.9,
                     max_position=MAX_POSITION,cost_bps=10.,max_periods=12,
                     fast=False,boom_return=.20,historical_membership=None,
                     require_point_in_time=False,terminal_returns=None,
                     competitive_agents=True):
    """Replay forecast_asof with EXACT production competition and parameters."""
    if not 5<=top_n<=20: raise ValueError('Choose between 5 and 20 stocks.')
    if not 0<exposure<=1 or not 0<max_position<=1:
        raise ValueError('Exposure and cap must be (0,1].')
    if horizon<1 or cost_bps<0 or max_periods<1: raise ValueError('Invalid horizon, costs, periods')
    panel=_hydrate_terminal_labels(panel, terminal_returns, close)
    dates=pd.DatetimeIndex(close[BENCHMARK].dropna().index)
    first=max(320,horizon+120)
    last=len(dates)-horizon-1
    signal_indices=list(range(last,first-1,-horizon))[:max_periods][::-1]
    if not signal_indices: raise ValueError('Insufficient history for walk-forward evaluation')
    snapshots=[dates[i] for i in signal_indices]
    membership_map=None
    if historical_membership is not None:
        membership_map=validate_membership(historical_membership,signal_dates=snapshots,
                     panel=panel,close=close,horizon=horizon,terminal_returns=terminal_returns)
    elif require_point_in_time:
        raise ValueError('Strict backtesting requires archived historical membership; present-day survivors cannot be certified')
    terminal=_archived_terminal(terminal_returns)
    nav=momentum_nav=spy_nav=1.0
    prev={}; prev_momentum={}
    periods=[]; observations=[]; missing_unselected=0; agent_wins=0
    for idx in signal_indices:
        signal_date=dates[idx]; horizon_end=dates[idx+horizon]; execution_date=dates[idx+1]
        train=training_snapshot(panel,signal_date)
        if len(train)<350 or train.date.nunique()<100: continue
        # No future label or return appears in candidate eligibility.
        candidates=panel.loc[(panel.date==signal_date)&
            ((panel['raw_close'] if 'raw_close' in panel else panel['close'])>MIN_PRICE)].copy()
        if membership_map is not None:
            candidates=candidates.loc[candidates.ticker.isin(membership_map[signal_date])].copy()
        if len(candidates)<top_n:
            if membership_map is not None: raise ValueError('Incomplete archived eligibility panel')
            continue
        # forecast_asof uses only matured target rows and decision-time predictors.
        forecasts=forecast_asof(panel,signal_date,fast=fast,boom_return=boom_return,
                                competitive_agents=competitive_agents)
        score_cols=['ticker','forecast_excess','prob_gain','prob_boom','selected_model']
        scored=candidates.merge(forecasts[score_cols],on='ticker',validate='one_to_one',how='left')
        if scored.forecast_excess.isna().any():
            raise ValueError('Live model cannot forecast all eligible historical stocks')
        scored=scored.sort_values(['forecast_excess','ticker'],ascending=[False,True])
        picks=scored.head(top_n).ticker.tolist()
        mom_picks=scored.sort_values(['rel_60','ticker'],ascending=[False,True]).head(top_n).ticker.tolist()
        agent_wins += int(scored.selected_model.isin(['Ridge','Gradient Boosting','Random Forest']).sum())
        next_px=pd.to_numeric(close.loc[execution_date].reindex(scored.ticker),errors='coerce')
        end_px=pd.to_numeric(close.loc[horizon_end].reindex(scored.ticker),errors='coerce')
        asof_px=pd.to_numeric(close.loc[signal_date].reindex(scored.ticker),errors='coerce')
        resolved=[]; fill_returns={}; fillable=set()
        bm_forward=float(close.loc[horizon_end,BENCHMARK]/close.loc[signal_date,BENCHMARK]-1)
        if not np.isfinite(bm_forward): raise ValueError('Benchmark horizon missing')
        for row in scored.itertuples(index=False):
            t=row.ticker
            current=asof_px.loc[t]; entry=next_px.loc[t]; end=end_px.loc[t]
            archive=terminal.get((pd.Timestamp(signal_date),t))
            asof_return=(float(end/current)-1 if np.isfinite(current) and current>0
                        and np.isfinite(end) and end>0 else (archive[0] if archive else np.nan))
            entry_return=(float(end/entry)-1 if np.isfinite(entry) and entry>0
                         and np.isfinite(end) and end>0 else (archive[1] if archive else np.nan))
            # No execution based on end-date availability. If an entry quote is
            # present, a missing ending payoff is a DATA ERROR, not cash.
            if np.isfinite(entry) and entry>0:
                fillable.add(t)
                if np.isfinite(entry_return): fill_returns[t]=float(entry_return)
                if (t in picks or t in mom_picks) and not np.isfinite(entry_return):
                    raise ValueError(f'Missing terminal return for selected holding {t} at {signal_date.date()}; supply archived delisting payoff')
            if not np.isfinite(asof_return):
                missing_unselected += 1
                if membership_map is not None:
                    raise ValueError(f'Unresolved archived constituent {t} return')
                continue  # prediction still existed; marked unscorable, not selected away
            observed=float(asof_return)-bm_forward
            prob_gain=getattr(row,'prob_gain',np.nan)
            prob_boom=getattr(row,'prob_boom',np.nan)
            observations.append({'signal_date':signal_date,'end_date':horizon_end,
              'ticker':t,'pred_excess':float(row.forecast_excess),
              'realized_excess':observed,'realized_return':float(asof_return),
              'benchmark_return':bm_forward,'p_gain':float(prob_gain),
              'p_boom':float(prob_boom),'gain_baseline':float((train.forward_return>0).mean()),
              'boom_baseline':float((train.forward_return>=boom_return).mean()),
              'gain_event':int(asof_return>0),'boom_event':int(asof_return>=boom_return),
              'naive_direction_positive':bool((train.target>0).mean()>=.5),
              'selected_model':row.selected_model})
            resolved.append({'ticker':t,'forward_return':asof_return,'target':observed,
                            'pred':float(row.forecast_excess)})
        execution=pd.DataFrame([{'ticker':t,'forward_return':ret} for t,ret in fill_returns.items()])
        selected_weights={t:w for t,w in _weight_map(picks,exposure,max_position).items() if t in fillable}
        momentum_weights={t:w for t,w in _weight_map(mom_picks,exposure,max_position).items() if t in fillable}
        strat,prev,turnover=_period_return(execution,selected_weights,prev,cost_bps)
        mom,prev_momentum,_=_period_return(execution,momentum_weights,prev_momentum,cost_bps)
        bm_return=float(close.loc[horizon_end,BENCHMARK]/close.loc[execution_date,BENCHMARK]-1)
        nav*=1+strat; momentum_nav*=1+mom; spy_nav*=1+bm_return
        resolved_df=pd.DataFrame(resolved)
        ic=float(resolved_df[['pred','target']].corr(method='spearman').iloc[0,1]) if len(resolved_df)>1 else np.nan
        periods.append({'date':signal_date,'end':horizon_end,'model_return':strat,
            'momentum_return':mom,'spy_return':bm_return,'model_nav':nav,
            'momentum_nav':momentum_nav,'spy_nav':spy_nav,'model_turnover':turnover,
            'model_filled_names':len(selected_weights),
            'model_unfilled_names':len(picks)-len(selected_weights),
            'execution_date':execution_date,'rank_ic':ic,'top_stocks':', '.join(picks),
            'model_competition':competitive_agents})
    period_frame=pd.DataFrame(periods)
    if period_frame.empty: raise ValueError('Not enough qualifying past windows')
    predictions=pd.DataFrame(observations)
    validate_oos_data(predictions)
    quality=overall_quality(predictions)
    meq=pd.concat([pd.Series([1.]),period_frame.model_nav],ignore_index=True)
    beq=pd.concat([pd.Series([1.]),period_frame.spy_nav],ignore_index=True)
    metrics={'portfolio_return':float(period_frame.model_nav.iloc[-1]-1),
        'benchmark_return':float(period_frame.spy_nav.iloc[-1]-1),
        'momentum_return':float(period_frame.momentum_nav.iloc[-1]-1),
        'portfolio_max_drawdown':_max_drawdown(meq),
        'benchmark_max_drawdown':_max_drawdown(beq),
        'mean_rank_ic':float(period_frame.rank_ic.mean()),
        'period_hit_rate':float((period_frame.model_return>period_frame.spy_return).mean()),
        'periods':float(len(period_frame)),
        'average_turnover':float(period_frame.model_turnover.mean()),
        'portfolio_failed_fills':int(period_frame.model_unfilled_names.sum()),
        'execution_assumption':'Next-session adjusted close: simulated, not executable',
        'boom_brier':quality['boom_brier'],'boom_baseline_brier':quality['boom_baseline_brier'],
        'boom_observed_frequency':float(predictions.loc[predictions.p_boom.notna(),'boom_event'].mean()),
        'boom_mean_probability':float(predictions.p_boom.mean()),
        'boom_evaluated_predictions':quality['boom_scored'],
        'direction_hit':quality['direction_hit'],'direction_baseline':quality['direction_baseline'],
        'excess_mae':quality['excess_mae'],'excess_zero_mae':quality['excess_zero_mae'],
        'gain_brier':quality['gain_brier'],'gain_baseline_brier':quality['gain_baseline_brier'],
        'gain_evaluated_predictions':quality['gain_scored'],
        'ticker_evaluations':quality['ticker_outcomes'],
        'independent_signal_windows':quality['signal_windows'],
        'pit_universe_qualified':membership_map is not None,
        'backtest_evidence_status':('User-declared historical membership, provenance not independently authenticated'
           if membership_map is not None else 'UNVERIFIED: current survivor-universe sample'),
        'competition_replayed':bool(competitive_agents),
        'champion_predictions':agent_wins,
        'missing_nonholding_outcomes':missing_unselected}
    evidence={'point_in_time_universe':membership_map is not None,
        'tournament_replayed':competitive_agents,
        'limitations':'Unverified archival provenance and historical data completeness' if membership_map is not None else
          'Current listed symbols only; survivorship bias not eliminated'}
    return BacktestResult(period_frame,metrics,predictions,evidence)
