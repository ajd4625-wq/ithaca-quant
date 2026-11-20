"""Independent, research-only audits inspired by professional quant workflows.

These utilities do NOT train or improve the prediction model by themselves.
They evaluate frozen, out-of-sample predictions with date-block uncertainty,
future-free evidence availability, and a delayed, cost-aware price proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
import numpy as np
import pandas as pd


@dataclass
class FactorAudit:
    metrics: dict
    by_date: pd.DataFrame
    selected: pd.DataFrame
    caveats: tuple[str, ...]


def availability_safe_join(signals: pd.DataFrame, events: pd.DataFrame, *,
                           group_key: str = "ticker", signal_time: str = "signal_time",
                           published_at: str = "published_at", discovered_at: str = "discovered_at",
                           value_columns: tuple[str, ...] = ("event_score",)) -> pd.DataFrame:
    """Attach most recently *public and observed* event to each dated signal.

    A filing's economic-period end or trade date is NOT its availability date.
    Both timestamps are required; unknown discovery dates are not guessed.
    Left rows are preserved in their original order. A later correction cannot
    retroactively change an earlier signal through this join.
    """
    if signals.empty:
        return signals.copy()
    need_s={group_key, signal_time}
    need_e={group_key, published_at, discovered_at, *value_columns}
    if need_s - set(signals) or need_e - set(events):
        raise ValueError("Missing signal or event availability columns")
    signal=signals.copy()
    signal['_audit_order']=range(len(signal))
    signal['_signal_utc']=pd.to_datetime(signal[signal_time], utc=True, errors='coerce')
    if signal['_signal_utc'].isna().any():
        raise ValueError('Signals require dated timestamps')
    if events.empty:
        for col in (*value_columns,'_last_event_available_at'):
            signal[col]=pd.NA
        return signal.drop(columns=['_audit_order','_signal_utc'])
    event=events.copy()
    pub=pd.to_datetime(event[published_at], utc=True, errors='coerce')
    seen=pd.to_datetime(event[discovered_at], utc=True, errors='coerce')
    event['_available_utc']=pd.concat([pub,seen],axis=1).max(axis=1)
    event=event.loc[pub.notna() & seen.notna()].copy()
    # Avoid duplicating input signals and avoid overwriting ambiguous event fields.
    if any(col in signal for col in value_columns):
        raise ValueError('Event output column collides with a signal column')
    result=[]
    for symbol, left in signal.groupby(group_key,sort=False,dropna=False):
        right=event.loc[event[group_key] == symbol].sort_values('_available_utc')
        left=left.sort_values('_signal_utc').copy()
        if len(right):
            right=right.drop_duplicates('_available_utc',keep='last')
            matched=pd.merge_asof(left, right[['_available_utc',*value_columns]],
                                  left_on='_signal_utc',right_on='_available_utc',direction='backward')
            matched=matched.rename(columns={'_available_utc':'_last_event_available_at'})
        else:
            matched=left
            for col in (*value_columns,'_last_event_available_at'):
                matched[col]=pd.NA
        result.append(matched)
    out=pd.concat(result,ignore_index=True).sort_values('_audit_order')
    return out.drop(columns=['_audit_order','_signal_utc']).reset_index(drop=True)


def _date_bootstrap(values: np.ndarray, *, draws: int=2000, seed: int=41):
    values=np.asarray(values,dtype=float)
    values=values[np.isfinite(values)]
    if len(values)<8: return (None,None)
    rng=np.random.default_rng(seed)
    indices=rng.integers(0,len(values),size=(draws,len(values)))
    return tuple(map(float,np.quantile(values[indices].mean(axis=1),[.025,.975])))


def factor_audit(predictions: pd.DataFrame, *, top_fraction: float=.2,
                 assumed_round_trip_bps: float=20.0,
                 sectors: dict[str,str] | None=None) -> FactorAudit:
    """Date-block factor tear sheet: rank IC, top-minus-bottom, turnover, costs.

    Only pre-recorded model predictions and *matured* outcomes qualify.
    `assumed_round_trip_bps` is a sensitivity parameter, NOT a measured fee.
    These are overlapping stocks inside independent signal-date blocks, so
    intervals bootstrap decision dates, never individual ticker observations.
    """
    required={'signal_date','end_date','ticker','pred_excess','realized_excess'}
    if required-set(predictions):
        raise ValueError('Missing pre-recorded OOS prediction fields: '+', '.join(sorted(required-set(predictions))))
    if not .02 <= top_fraction <= .5 or assumed_round_trip_bps<0:
        raise ValueError('Choose a top fraction between 2% and 50%, and nonnegative costs')
    x=predictions.copy()
    x['signal_date']=pd.to_datetime(x['signal_date'],errors='coerce')
    x['end_date']=pd.to_datetime(x['end_date'],errors='coerce')
    x['pred_excess']=pd.to_numeric(x['pred_excess'],errors='coerce')
    x['realized_excess']=pd.to_numeric(x['realized_excess'],errors='coerce')
    if x.duplicated(['signal_date','ticker']).any():
        raise ValueError('Duplicate ticker/date results would inflate evidence')
    if (x['end_date'].notna() & x['signal_date'].notna() & (x['end_date']<=x['signal_date'])).any():
        raise ValueError('A label must end after its signal')
    x=x.loc[x[['signal_date','end_date','pred_excess','realized_excess']].notna().all(axis=1)].copy()
    x=x.replace([np.inf,-np.inf],np.nan).dropna(subset=['pred_excess','realized_excess'])
    rows=[]; selected=[]; previous=set()
    for date,g in x.groupby('signal_date',sort=True):
        if g.ticker.nunique()<5: continue
        ordered=g.sort_values(['pred_excess','ticker'],ascending=[False,True]); n=max(1,int(ceil(len(g)*top_fraction)))
        top=ordered.head(n).copy(); bottom=ordered.tail(n).copy()
        selected.append(top.assign(_selected_date=date))
        current=set(top.ticker)
        # Symmetric set turnover normalized to top names, first selection incurs entry.
        turnover=(len(current-previous)+len(previous-current))/(2*n) if previous else 1.0
        previous=current
        ic=g['pred_excess'].corr(g['realized_excess'],method='spearman')
        spread=float(top.realized_excess.mean()-bottom.realized_excess.mean())
        top_uplift=float(top.realized_excess.mean()-g.realized_excess.mean())
        gross_top=float(top.realized_excess.mean())
        after_cost=gross_top-assumed_round_trip_bps/10000
        row={'signal_date':date,'n_stocks':len(g),'selected':n,'rank_ic':float(ic) if pd.notna(ic) else np.nan,
             'top_minus_bottom_excess':spread,'top_vs_universe_excess':top_uplift,
             'top_mean_excess':gross_top,'top_mean_excess_after_cost_stress':after_cost,
             'name_turnover':turnover,'top_direction_hit':float((top.realized_excess>0).mean())}
        if sectors:
            group=g.assign(_sector=g.ticker.map(sectors).fillna('Unknown'))
            group=group.assign(_neutral_prediction=group.pred_excess-group.groupby('_sector').pred_excess.transform('mean'),
                               _neutral_outcome=group.realized_excess-group.groupby('_sector').realized_excess.transform('mean'))
            row['sector_neutral_ic']=float(group._neutral_prediction.corr(group._neutral_outcome,method='spearman'))
        rows.append(row)
    per=pd.DataFrame(rows)
    if per.empty:
        return FactorAudit({'windows':0,'ticker_outcomes':0,'status':'Insufficient cross-sectional windows'},per,pd.DataFrame(),
                           ('At least five stocks are required per decision date.',))
    auc=per.rank_ic.mean()
    confidence=_date_bootstrap(per.top_vs_universe_excess.to_numpy())
    summary={'windows':len(per),'ticker_outcomes':int(per.n_stocks.sum()),'mean_rank_ic':float(auc) if pd.notna(auc) else None,
             'top_vs_universe_excess':float(per.top_vs_universe_excess.mean()),
             'top_bottom_excess':float(per.top_minus_bottom_excess.mean()),
             'top_hit_rate':float(per.top_direction_hit.mean()),
             'cost_stressed_top_excess':float(per.top_mean_excess_after_cost_stress.mean()),
             'average_name_turnover':float(per.name_turnover.mean()),
             'uplift_ci_low':confidence[0],'uplift_ci_high':confidence[1],
             'assumed_round_trip_bps':float(assumed_round_trip_bps),
             'status':'Exploratory, no live proof'}
    if sectors and 'sector_neutral_ic' in per:
        v=per.sector_neutral_ic.mean()
        summary['mean_sector_neutral_ic']=float(v) if pd.notna(v) else None
    return FactorAudit(summary,per,pd.concat(selected,ignore_index=True),(
        'Selected tickers may omit delisted companies: survivorship bias is unresolved.',
        'Same-close historical results are not executable closing fills.',
        'Cost stress subtracts assumed round-trip bps from each selected-window return, not a brokerage quote.',
        'Confidence intervals bootstrap dates and remain optimistic if settings were chosen after seeing these results.',
    ))


def next_close_proxy(predictions: pd.DataFrame, close: pd.DataFrame, *,
                     benchmark: str='SPY', top_fraction: float=.2,
                     round_trip_bps: float=20.0) -> pd.DataFrame:
    """Compare signal-close prices with a one-bar-later entry/exit proxy.

    A signal produced after close(t) could not transact at close(t). We measure
    entering at close(t+1), exiting at close(end+1) when both are observed.
    This is still *not* an execution fill or a guarantee of getting that price.
    """
    if benchmark not in close or not .02<=top_fraction<=.5 or round_trip_bps<0:
        raise ValueError('Missing benchmark or invalid sizing/cost inputs')
    if not isinstance(close.index,pd.DatetimeIndex) or not close.index.is_monotonic_increasing:
        raise ValueError('Price dates must be sorted')
    need={'signal_date','end_date','ticker','pred_excess'}
    if need-set(predictions): raise ValueError('Missing dated prediction fields')
    p=predictions.copy()
    p['signal_date']=pd.to_datetime(p.signal_date);p['end_date']=pd.to_datetime(p.end_date)
    p['pred_excess']=pd.to_numeric(p.pred_excess,errors='coerce')
    rows=[]
    for date,g in p.groupby('signal_date'):
        g=g.dropna(subset=['pred_excess']);n=max(1,ceil(len(g)*top_fraction))
        if len(g)<5:continue
        eligible=g.sort_values('pred_excess',ascending=False).head(n)
        for r in eligible.itertuples(index=False):
            if r.ticker not in close.columns:continue
            start_idx=close.index.searchsorted(r.signal_date)
            end_idx=close.index.searchsorted(r.end_date)
            if start_idx>=len(close) or end_idx>=len(close):continue
            if close.index[start_idx]!=r.signal_date or close.index[end_idx]!=r.end_date:continue
            if end_idx+1>=len(close) or start_idx+1>=len(close):continue
            old_a,old_b=close.iloc[start_idx][r.ticker],close.iloc[end_idx][r.ticker]
            new_a,new_b=close.iloc[start_idx+1][r.ticker],close.iloc[end_idx+1][r.ticker]
            bm_a,bm_b=close.iloc[start_idx+1][benchmark],close.iloc[end_idx+1][benchmark]
            prices=np.asarray([old_a,old_b,new_a,new_b,bm_a,bm_b],dtype=float)
            if not np.isfinite(prices).all() or (prices<=0).any():continue
            gross=float(new_b/new_a-1)
            bm=float(bm_b/bm_a-1)
            rows.append({'signal_date':date,'ticker':r.ticker,
                         'same_close_return':float(old_b/old_a-1),
                         'next_close_return':gross,
                         'next_close_spy_return':bm,
                         'next_close_relative_return':gross-bm,
                         'next_close_net_return_stress':gross-round_trip_bps/10000,
                         'entry_proxy_date':close.index[start_idx+1],
                         'exit_proxy_date':close.index[end_idx+1]})
    return pd.DataFrame(rows)


def historical_data_health(close: pd.DataFrame, *, benchmark: str='SPY',
                           min_coverage: float=.95) -> pd.DataFrame:
    """Flag suspicious/missing price histories before interpreting a backtest.

    A large daily move may be legitimate news, a split correction, or bad data;
    it is only a review flag. Current constituents cannot reveal delisted names.
    """
    if benchmark not in close or not isinstance(close.index,pd.DatetimeIndex):
        raise ValueError('A dated matrix with SPY is required')
    if close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise ValueError('Dates must be unique and sorted')
    if not (0 < min_coverage <= 1):
        raise ValueError('min_coverage must be between 0 and 1')
    rows=[]
    expected=close[benchmark].dropna().index
    for ticker in close.columns:
        price=pd.to_numeric(close[ticker].reindex(expected), errors='coerce')
        valid=price.notna() & np.isfinite(price) & (price>0)
        observed=price.where(valid)
        one_day=observed.pct_change(fill_method=None)
        coverage=float(valid.mean()) if len(valid) else 0.
        huge=int(one_day.abs().gt(.60).sum())
        last=observed.last_valid_index()
        trailing_gaps=(len(expected)-1-expected.get_loc(last)) if last is not None and len(expected) else len(expected)
        flags=[]
        if coverage<min_coverage:flags.append('Incomplete historical coverage')
        if trailing_gaps>2:flags.append('Stale last price')
        if huge:flags.append('Large one-session move: verify splits/news')
        if not valid.any():flags.append('No valid positive prices')
        rows.append({'ticker':ticker,'observed_sessions':int(valid.sum()),
                     'expected_sessions':len(expected),'coverage':coverage,
                     'missing_at_end_sessions':int(trailing_gaps),
                     'large_daily_move_flags':huge,'review':'; '.join(flags) or 'No simple flags'})
    return pd.DataFrame(rows)
