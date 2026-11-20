"""Federal Reserve FRED/ALFRED macro research with vintage-safe access.

Current context is *not* fed into historical forecasts. ALFRED vintages may be
requested for historical as-of research; never use the latest revised numbers
as if they were known years ago.
"""
from datetime import date
import pandas as pd
import requests

SERIES = {
    'DFF': 'Effective federal funds rate (%)',
    'DGS10': '10-year Treasury yield (%)',
    'UNRATE': 'Unemployment rate (%)',
    'CPIAUCSL': 'Consumer Price Index (index)',
}
URL = 'https://api.stlouisfed.org/fred/series/observations'


def fred_vintage(series: str, api_key: str, asof=None, *, client=None, limit=250):
    if series not in SERIES:
        raise ValueError('Unknown approved FRED series')
    if not api_key or not api_key.strip():
        raise ValueError('FRED_API_KEY is required for FRED data')
    selected = str(pd.Timestamp(asof or date.today()).date())
    resp = (client or requests).get(URL, params={
        'series_id':series, 'api_key':api_key, 'file_type':'json',
        'realtime_start':selected, 'realtime_end':selected,
        'sort_order':'desc', 'limit':limit,
    }, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    if 'error_code' in payload:
        raise ValueError('FRED rejected the data request')
    records = []
    for row in payload.get('observations', []):
        try:
            value = float(row['value'])
            if pd.notna(value):
                records.append({'observation_date':pd.Timestamp(row['date']), 'value':value})
        except (TypeError, ValueError, KeyError):
            continue
    return pd.DataFrame(records, columns=['observation_date','value']).sort_values('observation_date').reset_index(drop=True)


def macro_snapshot(api_key, asof=None, *, client=None):
    rows = []
    for series, label in SERIES.items():
        try:
            history = fred_vintage(series, api_key, asof, client=client)
            if history.empty:
                rows.append({'Series':label, 'Value':None, 'Observation date':None, 'Status':'Missing at requested vintage'})
            else:
                latest = history.iloc[-1]
                rows.append({'Series':label, 'Value':latest.value,
                             'Observation date':latest.observation_date.date(), 'Status':'ALFRED vintage'})
        except (requests.RequestException, ValueError, KeyError) as exc:
            rows.append({'Series':label, 'Value':None, 'Observation date':None,
                         'Status':f'Unavailable ({type(exc).__name__})'})
    return pd.DataFrame(rows)
