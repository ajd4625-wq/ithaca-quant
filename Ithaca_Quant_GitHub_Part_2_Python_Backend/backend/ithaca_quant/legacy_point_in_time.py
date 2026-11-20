"""Fail-closed point-in-time security membership for rigorous historical audits.

Requires user-supplied historical constituents including delisted securities and
an authoritative total-return feed including delisting returns. A list of
currently trading symbols, even with historic prices, cannot verify this.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import pandas as pd

COLUMNS={'security_id','ticker','member_from','member_to','source_id'}

@dataclass(frozen=True)
class PITUniverse:
    rows:pd.DataFrame
    price_provenance:dict


def load_pit_universe(membership_csv, price_provenance_json) -> PITUniverse:
    records=pd.read_csv(membership_csv,dtype={'security_id':str,'ticker':str,'source_id':str},keep_default_na=False)
    details=json.loads(Path(price_provenance_json).read_text(encoding='utf-8'))
    return validate_pit_universe(records, details)


def validate_pit_universe(records, details) -> PITUniverse:
    missing=COLUMNS-set(records.columns)
    if missing:raise ValueError('Point-in-time membership missing: '+', '.join(sorted(missing)))
    rows=records.copy()
    if rows.empty:raise ValueError('Empty historical membership universe')
    for column in ('security_id','ticker','source_id','member_from'):
        if rows[column].isna().any() or (rows[column].astype(str).str.strip()=='').any():
            raise ValueError(f'Missing {column} in historical membership')
    rows['ticker']=rows['ticker'].astype(str).str.upper().str.strip()
    rows['member_from']=pd.to_datetime(rows['member_from'],errors='raise').dt.normalize()
    rows['member_to']=pd.to_datetime(rows['member_to'].replace('',pd.NaT),errors='coerce').dt.normalize()
    if ((rows.member_to.notna()) & (rows.member_to<=rows.member_from)).any():
        raise ValueError('Membership interval end must be strictly after start (exclusive).')
    if rows.groupby('ticker').security_id.nunique().max()>1:
        raise ValueError('Ticker symbol reused across security IDs: immutable price series cannot safely distinguish them.')
    for _, frame in rows.groupby('security_id'):
        frame=frame.sort_values('member_from')
        prior_end=None
        for row in frame.itertuples(index=False):
            if prior_end is not None and row.member_from < prior_end:
                raise ValueError('Overlapping membership intervals for one security')
            prior_end=row.member_to if pd.notna(row.member_to) else pd.Timestamp.max
    required=('membership_history_includes_delisted','total_return_history_includes_delisting_returns',
              'historical_symbols_preserved','provider','dataset_description')
    if not isinstance(details,dict) or any(not details.get(k) for k in required):
        raise ValueError('Rigorous PIT backtest requires independently sourced historic membership AND delisting-aware total returns in the provenance manifest.')
    if not all(details[k] is True for k in required[:3]):
        raise ValueError('All three explicit price-history coverage attestations must be true.')
    return PITUniverse(rows.reset_index(drop=True), dict(details))


def apply_membership(panel:pd.DataFrame, universe:PITUniverse, *, require_price_completeness=True):
    """Select only members actually eligible at each date and reject missing securities.

    Membership is inclusive member_from, exclusive member_to. Prior to calling,
    caller must supply trustworthy point-in-time price and delisting return data.
    """
    if not {'date','ticker'}<=set(panel.columns):
        raise ValueError('Panel must include date and ticker')
    if panel.duplicated(['date','ticker']).any():
        raise ValueError('Duplicate security/date prices')
    panel=panel.copy()
    panel['date']=pd.to_datetime(panel.date).dt.normalize()
    # Vectorized join instead of scanning a full multi-million row panel once
    # for every security. Filters are applied at each historical decision date.
    eligible=panel.merge(universe.rows[['ticker','member_from','member_to']],
                          on='ticker',how='inner',sort=False)
    eligible=eligible.loc[(eligible.date>=eligible.member_from) &
          (eligible.member_to.isna() | (eligible.date<eligible.member_to))]
    eligible=eligible.drop(columns=['member_from','member_to'])
    if eligible.empty:raise ValueError('No historical prices overlap the supplied PIT membership')
    if eligible.duplicated(['date','ticker']).any():
        raise ValueError('Ambiguous overlapping membership: duplicate rows')
    if require_price_completeness:
        # Every member with an active membership interval must have observations
        # on every decision date covered by the panel. Never silently exclude
        # delisted or data-missing securities from a ranking competition.
        dates=pd.DatetimeIndex(sorted(panel.date.unique()))
        availability=eligible.groupby('date').ticker.apply(set).to_dict()
        violations=[]
        for when in dates:
            active=universe.rows.loc[(universe.rows.member_from<=when)&
                     (universe.rows.member_to.isna() | (universe.rows.member_to>when)),'ticker']
            missing=set(active)-availability.get(when,set())
            if missing:violations.append((when.date().isoformat(),sorted(missing)[:4]))
        if violations:
            example=violations[0]
            raise ValueError(f'PIT coverage is incomplete on {example[0]}: {example[1]}. Do not silently skip missing/delisted stocks.')
    return eligible.sort_values(['date','ticker']).reset_index(drop=True)
