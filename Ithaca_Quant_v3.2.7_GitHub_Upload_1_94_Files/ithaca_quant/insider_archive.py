"""Historical SEC Form 4 features with conservative publication timing.

No current/last-five-filing snapshot is ever retroactively assigned to the past.
File dates without time are usable from the NEXT business session only.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

INSIDER_FEATURES=['insider_net_buy_log_30d','insider_buy_count_30d','insider_available']


def archived_form4_features(rows, dates):
    idx=pd.DatetimeIndex(pd.to_datetime(dates)).normalize()
    out=pd.DataFrame(0.0,index=idx,columns=INSIDER_FEATURES)
    if rows is None or len(rows)==0: return out
    filings=pd.DataFrame(rows).copy()
    needed={'filed_date','trade_date','type','value_usd'}
    if not needed.issubset(filings):
        raise ValueError('Archived Form 4 data must include original filed_date,trade_date,type,value_usd')
    filings['filed_date']=pd.to_datetime(filings.filed_date,errors='coerce').dt.normalize()
    filings['trade_date']=pd.to_datetime(filings.trade_date,errors='coerce').dt.normalize()
    filings['value_usd']=pd.to_numeric(filings.value_usd,errors='coerce')
    if (filings.filed_date.isna().any() or filings.trade_date.isna().any() or
        (filings.trade_date>filings.filed_date).any() or
        filings.value_usd.isna().any() or (filings.value_usd<0).any() or
        not filings.type.isin(['Purchase','Sale']).all()):
        raise ValueError('Invalid or future-dated SEC Form 4 archive')
    filings['available_at']=filings.filed_date+pd.offsets.BDay(1)
    for dt in idx:
        eligible=filings.loc[(filings.available_at<=dt) &
            (filings.available_at>dt-pd.Timedelta(days=30))]
        previously=filings.available_at.le(dt).any()
        out.at[dt,'insider_available']=float(previously)
        if eligible.empty: continue
        values=np.where(eligible.type.eq('Purchase'),eligible.value_usd,-eligible.value_usd)
        net=float(np.sum(values))
        out.at[dt,'insider_net_buy_log_30d']=np.sign(net)*np.log1p(abs(net))
        out.at[dt,'insider_buy_count_30d']=float(eligible.type.eq('Purchase').sum())
    return out
