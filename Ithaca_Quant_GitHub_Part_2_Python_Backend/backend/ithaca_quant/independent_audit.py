"""Historical three-ML-agent audit, blocked without point-in-time data.

Designed for a real historical membership + delisting-aware total return dataset.
This module never downloads a universe or assumes present-day membership was
also true historically. Predictions are re-fit as of each old signal date.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .legacy_point_in_time import PITUniverse, apply_membership
from .independent_agents import forecast_three_agents
from .config import BENCHMARK

@dataclass
class AuditResult:
    windows:pd.DataFrame
    forecasts:pd.DataFrame
    metrics:dict


def run_three_agent_pit_audit(panel, close, universe:PITUniverse, *, horizon=5,
                              step=20, max_periods=12, top_n=6, cost_bps=10):
    """Fixed historical schedule; freeze predictions before later outcomes.

    Uses a conservative cash-when-unvalidated policy, only up to 25% per name,
    cost on entry + exit. Close-to-close adjusted-return fills remain idealized
    and results are NOT brokerage-executable performance.
    """
    if not isinstance(universe,PITUniverse):
        raise ValueError('Rigorous historical evaluation requires a verified-input PITUniverse; no current-list fallback.')
    if horizon!=5 or step<horizon or not 1<=top_n<=20:
        raise ValueError('Audit expects five sessions and nonoverlapping windows')
    filtered=apply_membership(panel,universe)
    dates=pd.DatetimeIndex(close[BENCHMARK].dropna().index)
    last=len(dates)-horizon-1
    idxs=list(range(max(520,last-(max_periods-1)*step),last+1,step))
    idxs=[idx for idx in idxs if idx>=520 and idx+horizon<len(dates)]
    if not idxs:raise ValueError('Too little date history for an independent held-out audit')
    records=[]; periods=[]; nav=1.; bnav=1.
    for idx in idxs:
        when=dates[idx]; outcome=dates[idx+horizon]
        today=filtered.loc[(filtered.date==when) & (filtered.close>0)].copy()
        # No silent deletion of missing future labels (including delisted stocks).
        if today['forward_return'].isna().any() or today['target'].isna().any():
            raise ValueError('Missing five-session total return for PIT member; cannot compute an unbiased audit')
        if today.empty:continue
        signals=[]
        for row in today.itertuples(index=False):
            try:
                pred=forecast_three_agents(filtered,when,str(row.ticker))
                valid=bool(pred['validation_passed'])
                ex=float(pred['expected_excess_return'])
                downside=float(pred['risk_agent_downside_probability'])
                why='qualified' if valid else 'internal baseline gate failed'
            except (ValueError,TypeError) as exc:
                valid=False;ex=np.nan;downside=np.nan
                why='insufficient historical features or risk class coverage'
            records.append({'asof':when,'outcome_date':outcome,'ticker':row.ticker,
                            'forecast_excess':ex,'realized_excess':row.target,
                            'realized_return':row.forward_return,'validation_passed':valid,
                            'reason':why,'risk_probability':downside})
            if valid and np.isfinite(ex) and ex>.01 and downside<.45:
                signals.append((row.ticker,ex,float(row.forward_return)))
        chosen=sorted(signals,key=lambda x:(-x[1],x[0]))[:top_n]
        weight=min(.90/max(1,len(chosen)),.25)
        gross=sum(weight*ret for _,_,ret in chosen)
        # Entry + exit commissions/slippage, conservative simple approximation.
        cost=2*len(chosen)*weight*(cost_bps/10000)
        net=(1+gross)*(1-cost)-1
        spy=float(close.loc[outcome,BENCHMARK]/close.loc[when,BENCHMARK]-1)
        nav*=1+net; bnav*=1+spy
        periods.append({'asof':when,'outcome_date':outcome,'picks':','.join(x[0] for x in chosen),
                        'positions':len(chosen),'strategy_return':net,'spy_return':spy,
                        'strategy_nav':nav,'spy_nav':bnav})
    forecasts=pd.DataFrame(records);windows=pd.DataFrame(periods)
    if forecasts.empty or windows.empty:raise ValueError('No valid historical audit windows')
    observed=forecasts.loc[forecasts.validation_passed & forecasts.forecast_excess.notna()]
    accurate=(np.sign(observed.forecast_excess)==np.sign(observed.realized_excess)).sum() if len(observed) else 0
    return AuditResult(windows,forecasts,{
        'horizon_sessions':5,'periods':len(windows),
        'qualified_predictions':len(observed),'abstained_predictions':len(forecasts)-len(observed),
        'directional_accuracy_pct':round(100*accurate/len(observed),2) if len(observed) else None,
        'forecast_mae':round(float((observed.forecast_excess-observed.realized_excess).abs().mean()),5) if len(observed) else None,
        'zero_excess_baseline_mae':round(float(observed.realized_excess.abs().mean()),5) if len(observed) else None,
        'strategy_return':round(nav-1,5),'spy_return':round(bnav-1,5),
        'point_in_time_universe_input':True,
        'survivorship_warning':'Depends entirely on supplied member history, delisting return completeness, dates, and data supplier verification; file metadata alone does not prove coverage.',
        'execution_warning':'Idealized adjusted-close returns, approximated transaction costs, no actual broker fills or latency modeled.',
    })
