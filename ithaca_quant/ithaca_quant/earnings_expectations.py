"""Point-in-time licensed earnings expectation snapshots.

A true EPS earnings *surprise* requires an estimate known before the actual
announcement. SEC growth alone is not a consensus surprise.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

REQUIRED = ('ticker','expectation_timestamp','release_timestamp','expected_eps','reported_eps','source')
EARNINGS_FEATURES = ['earnings_surprise_pct','earnings_surprise_available']


def validated_expectations(source):
    """Return an explicit, conservatively validated release-date table."""
    frame = pd.DataFrame(source).copy()
    missing = set(REQUIRED)-set(frame.columns)
    if missing:
        raise ValueError('Missing earnings fields: '+', '.join(sorted(missing)))
    frame['ticker'] = frame['ticker'].astype(str).str.upper().str.strip()
    for k in ('expectation_timestamp','release_timestamp'):
        frame[k] = pd.to_datetime(frame[k],utc=True,errors='coerce')
    for k in ('expected_eps','reported_eps'):
        frame[k] = pd.to_numeric(frame[k],errors='coerce')
    valid = (frame['ticker'].str.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}') &
             frame['expectation_timestamp'].notna() & frame['release_timestamp'].notna() &
             (frame['expectation_timestamp'] < frame['release_timestamp']) &
             frame['source'].astype(str).str.strip().ne('') &
             np.isfinite(frame['expected_eps']) & np.isfinite(frame['reported_eps']))
    clean = frame.loc[valid, list(REQUIRED)].copy()
    if len(clean) != len(frame):
        raise ValueError(f'{len(frame)-len(clean)} entries have missing or impossible release/estimate timestamps')
    return clean.sort_values('release_timestamp').reset_index(drop=True)


def expectations_features(ticker, expectations, sessions):
    ix = pd.DatetimeIndex(pd.to_datetime(sessions)).tz_localize(None).normalize()
    out = pd.DataFrame(0.0,index=ix,columns=EARNINGS_FEATURES)
    if expectations is None or len(expectations)==0:
        return out
    data = validated_expectations(expectations)
    data = data.loc[data.ticker.eq(ticker.upper())].copy()
    if data.empty:
        return out
    known = data['release_timestamp'].dt.tz_convert('UTC').dt.tz_localize(None).dt.normalize()
    data['effective'] = known + pd.offsets.BDay(1)
    data['surprise'] = ((data['reported_eps']-data['expected_eps']) /
                       data['expected_eps'].abs().clip(lower=.01)).clip(-5,5)
    for day in ix:
        known_at = data.loc[data['effective']<=day]
        if known_at.empty:
            continue
        latest = known_at.iloc[-1]
        out.loc[day, 'earnings_surprise_pct'] = latest['surprise']
        out.loc[day, 'earnings_surprise_available'] = 1.0
    return out
