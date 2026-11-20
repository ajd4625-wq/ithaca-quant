"""Three-learner historical audit on a v3.1 integrity-checked archive ONLY.

Importantly, the archive manifest is declared by its provider and is not
independent proof that every historically eligible security was supplied.
No current Yahoo tickers/prices are used in this historical research path.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd
from .historical_archive import HistoricalBundle
from .features import build_panel
from .backtest import _hydrate_terminal_labels
from .point_in_time import validate_membership
from .independent_agents import forecast_three_agents

@dataclass
class ArchiveAudit:
    summary: dict
    forecasts: pd.DataFrame


def run_three_agent_archive_audit(bundle: HistoricalBundle, *, horizon=5, windows=2,
                                  step=20, max_member_count=35) -> ArchiveAudit:
    """Chronological, nonoverlapping five-session predictions from frozen PIT data.

    Runs on ALL eligible securities on each audited date or refuses the job;
    never quietly samples current survivors. The cap is operational, not a
    way to exclude inconvenient stocks. Use an offline batch for larger universes.
    """
    if horizon != 5 or not 1 <= windows <= 12 or step < horizon or max_member_count < 5:
        raise ValueError('Five-session audit requires 1–12 windows and step >= 5')
    close = bundle.market.close
    if 'SPY' not in close.columns or bundle.market.raw_close is None:
        raise ValueError('PIT archive requires SPY and contemporaneous raw closes')
    panel = build_panel(close,bundle.market.volume,horizon=horizon,
                        raw_close=bundle.market.raw_close,fundamentals=bundle.fundamentals)
    panel = _hydrate_terminal_labels(panel,bundle.terminal_returns,close)
    dates = pd.DatetimeIndex(close['SPY'].dropna().index)
    last = len(dates)-horizon-1
    # A model needs a long enough history for its purged validation split.
    anchors = list(range(last,max(439,last - windows*step)-1,-step))[:windows]
    if len(anchors) != windows:
        raise ValueError('Not enough source-declared history for requested audit windows')
    anchors = sorted(anchors)
    signal_dates = [dates[i] for i in anchors]
    allowed = validate_membership(bundle.membership,signal_dates=signal_dates,
        panel=panel,close=close,horizon=horizon,terminal_returns=bundle.terminal_returns)
    if any(len(v)>max_member_count for v in allowed.values()):
        raise ValueError(f'Archive has >{max_member_count} eligible securities in a signal window. Run a full-universe offline batch; never truncate membership for convenience.')
    rows=[]
    for when in signal_dates:
        members = sorted(allowed[when])
        observed = panel.loc[panel.date.eq(when) & panel.ticker.isin(members)].set_index('ticker')
        if set(observed.index)!=set(members):
            raise ValueError('Incomplete historical eligible panel: refusing to drop a constituent')
        for security_id in members:
            r=observed.loc[security_id]
            actual=float(r['target'])
            if not math.isfinite(actual):
                raise ValueError('Historical constituent lacks terminal-resolved return')
            try:
                forecast=forecast_three_agents(panel,when,security_id)
                qualified=bool(forecast['validation_passed'])
                predicted=float(forecast['expected_excess_return'])
                risk=float(forecast['risk_agent_downside_probability'])
                if not math.isfinite(predicted) or not math.isfinite(risk):
                    raise ValueError('Nonfinite fitted learner prediction')
                reason='passed internal holdout gate' if qualified else 'holdout gate failed'
            except (ValueError,TypeError,KeyError) as exc:
                # Show an abstention, but retain the eligible ticker in evidence.
                qualified=False;predicted=np.nan;risk=np.nan
                reason=f'cannot qualify: {type(exc).__name__}'
            rows.append({'signal_date':when.date().isoformat(),'security_id':security_id,
                'label_end':pd.Timestamp(r.label_end).date().isoformat(),
                'pred_excess':predicted,'realized_excess':actual,
                'validated':qualified,'risk_downside_probability':risk,
                'correct':bool((predicted>0)==(actual>0)) if qualified else None,
                'status':reason})
    predictions = pd.DataFrame(rows)
    graded=predictions.loc[predictions.validated]
    errors=(graded.pred_excess-graded.realized_excess).abs()
    zero=graded.realized_excess.abs()
    # Each issue date is an overlapping cluster of outcomes. Do not suggest
    # ticker rows constitute independent experimental replicates.
    summary={
        'archive_sha256':bundle.archive_sha256,
        'provider_declared':bundle.quality['provider_declared'],
        'integrity_sha256_verified':True,
        'vendor_authenticity_verified':False,
        'historical_universe_completeness_verified':False,
        'model_version':'3.1.0-three-ml',
        'three_learners':True,
        'horizon_sessions':5,
        'windows':len(signal_dates),'distinct_issue_dates':len(signal_dates),
        'historical_eligible_forecasts':len(predictions),
        'qualified_forecasts':len(graded),
        'abstained_forecasts':len(predictions)-len(graded),
        'direction_accuracy_pct':round(float(graded.correct.mean())*100,2) if len(graded) else None,
        'mae_pct':round(float(errors.mean())*100,3) if len(errors) else None,
        'zero_baseline_mae_pct':round(float(zero.mean())*100,3) if len(zero) else None,
        'no_promotion':True,
        'research_only':True,
        'warning':'Offline retrospective exercise on source-declared records. Hash verification is not vendor authentication. Only forward-logged predictions can establish prospective performance. The three fitted learners currently use market features, not archived SEC filings.',
    }
    return ArchiveAudit(summary,predictions)
