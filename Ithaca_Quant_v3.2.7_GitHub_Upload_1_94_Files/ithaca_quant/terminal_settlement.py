"""Build auditable delisting labels from independently supplied settlement evidence.

Never infer a 100% loss, zero payout or merger proceeds from the last quote.
The optional input is a *documented incremental* total-return factor from the
last observed adjusted close to final settlement, not a CRSP CIZ daily return
that already includes the delisting.  Veracity of source documents must be
verified by the data subscriber before use.  This module verifies arithmetic
and consistency, NOT truthfulness of a source_reference string.
"""
from __future__ import annotations

from io import BytesIO
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd

from .historical_archive import load_historical_archive

NEEDED = {'security_id','last_trading_date','event_date','settlement_factor',
          'return_basis','source_reference','source_record_id'}
BASIS = 'incremental_to_last_adjusted_close_excluding_prior_delist_return'


def compute_terminal_returns(archive, settlement_events: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Calculate selected signal-date payoffs, never substitute guessed values.

    A terminal event must occur within the model's forward horizon, its
    last trading date must match archive history, and no forward endpoint
    price can already exist (prevents double-counted settlements).
    """
    if horizon < 1:
        raise ValueError('Forecast horizon must be positive')
    if not NEEDED.issubset(settlement_events.columns):
        raise ValueError('Settlement evidence missing: ' + ', '.join(sorted(NEEDED-set(settlement_events.columns))))
    if settlement_events.empty:
        raise ValueError('No documented settlement records supplied')
    events = settlement_events.copy()
    events['security_id'] = events.security_id.astype(str).str.upper().str.strip()
    for name in ('last_trading_date','event_date'):
        events[name] = pd.to_datetime(events[name], errors='coerce').dt.normalize()
        if events[name].isna().any():
            raise ValueError(f'Invalid {name} in settlement evidence')
    events['settlement_factor'] = pd.to_numeric(events.settlement_factor, errors='coerce')
    if not np.isfinite(events.settlement_factor.to_numpy(float)).all() or events.settlement_factor.lt(0).any():
        raise ValueError('Settlement factor must be a documented nonnegative finite ratio')
    if not events.return_basis.eq(BASIS).all():
        raise ValueError('Only incremental settlement factors not already included in adjusted prices are supported; CRSP CIZ inclusive daily returns must not be multiplied again')
    for name in ('source_reference','source_record_id'):
        if events[name].isna().any() or events[name].astype(str).str.strip().eq('').any():
            raise ValueError(f'All terminal events require a documented {name}')
    if events.duplicated(['security_id','event_date']).any():
        raise ValueError('Duplicate security/event settlement evidence')
    master = archive.security_master
    known = set(master.security_id) - {'SPY'}
    if not set(events.security_id).issubset(known):
        raise ValueError('Settlement evidence refers to unknown permanent security IDs')
    md = archive.market
    close = md.close
    sessions = pd.DatetimeIndex(close['SPY'].dropna().index).sort_values()
    index = {pd.Timestamp(x).normalize(): i for i,x in enumerate(sessions)}
    existing = set()
    if archive.terminal_returns is not None:
        existing = {(pd.Timestamp(r.signal_date).normalize(), str(r.ticker))
                    for r in archive.terminal_returns.itertuples()}
    outcomes = []
    for event in events.itertuples(index=False):
        sid = event.security_id
        series = pd.to_numeric(close[sid], errors='coerce').dropna()
        if series.empty or pd.Timestamp(series.index[-1]).normalize() != event.last_trading_date:
            raise ValueError(f'Last trading date for {sid} does not match its observed price history')
        if not event.last_trading_date < event.event_date:
            raise ValueError('Terminal settlement event must follow last observed trade')
        if event.last_trading_date not in index:
            raise ValueError('Last trading date missing benchmark calendar')
        last_index = index[event.last_trading_date]
        settlement_value = float(series.iloc[-1]) * float(event.settlement_factor)
        if not np.isfinite(settlement_value):
            raise ValueError('Nonfinite final settlement value')
        for i in range(max(0,last_index-horizon+1), last_index+1):
            signal = pd.Timestamp(sessions[i]).normalize()
            if i+horizon >= len(sessions):
                continue
            future_end = pd.Timestamp(sessions[i+horizon]).normalize()
            if event.event_date > future_end:
                continue
            if np.isfinite(pd.to_numeric(close.at[future_end,sid],errors='coerce')):
                raise ValueError(f'Already observed forward close for {sid}: settlement would be counted twice')
            if (signal,sid) in existing:
                raise ValueError(f'Duplicate terminal outcome {sid} on {signal.date()}')
            asof = pd.to_numeric(close.at[signal,sid],errors='coerce')
            if not np.isfinite(asof) or asof <= 0:
                continue
            entry_date = pd.Timestamp(sessions[i+1]).normalize()
            entry = pd.to_numeric(close.at[entry_date,sid],errors='coerce')
            entry_return = float(settlement_value/entry-1) if np.isfinite(entry) and entry>0 else np.nan
            outcomes.append({'signal_date':str(signal.date()),'security_id':sid,
                'asof_total_return':float(settlement_value/asof-1),
                'entry_total_return':entry_return,
                'event_date':str(event.event_date.date()),
                'source_reference':str(event.source_reference),
                'source_record_id':str(event.source_record_id)})
    if not outcomes:
        raise ValueError('No settlement events fall inside fully observed model horizons; nothing to import')
    return pd.DataFrame(outcomes).sort_values(['signal_date','security_id']).reset_index(drop=True)


def attach_settlements(archive_zip: str | Path, events_csv: str | Path,
                       output_zip: str | Path, horizon: int) -> dict:
    """Repackage ZIP with event-level evidence; validate before writing.

    If multiple horizons are needed, build a separate archive for each or
    merge outcome rows with independent interval keys. Existing schema indexes
    one terminal outcome per signal date/security and is horizon-specific.
    """
    raw = Path(archive_zip).read_bytes()
    original = load_historical_archive(raw)
    events = pd.read_csv(events_csv, dtype={'security_id':'string'})
    outcomes = compute_terminal_returns(original, events, horizon)
    with ZipFile(BytesIO(raw)) as src:
        files = {name:src.read(name) for name in src.namelist() if name != 'manifest.json'}
        manifest = json.loads(src.read('manifest.json'))
    if 'terminal_returns.csv' in files:
        existing = pd.read_csv(BytesIO(files['terminal_returns.csv']))
        # Existing source columns may include additional audit fields.
        outcomes = pd.concat([existing, outcomes], ignore_index=True)
        if outcomes.duplicated(['signal_date','security_id']).any():
            raise ValueError('New terminal payoffs conflict with existing documented events')
    files['terminal_returns.csv'] = outcomes.to_csv(index=False).encode('utf-8')
    manifest['sha256'] = {name:sha256(payload).hexdigest() for name,payload in files.items()}
    manifest['terminal_horizon_sessions'] = int(horizon)
    manifest['terminal_evidence'] = ('Source-reference strings and event arithmetic validated. '
       'Independent source authentication and CRSP inclusive-return reconciliation NOT performed.')
    buffer = BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as z:
        for name,contents in sorted(files.items()):
            z.writestr(name,contents)
        z.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
    # Existing archive validation is performed before writing any destination.
    imported = load_historical_archive(buffer.getvalue())
    dest = Path(output_zip)
    if dest.exists():
        raise ValueError('Refusing to overwrite existing archived market data')
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(buffer.getvalue())
    return {'output':str(dest),'archive_sha256':imported.archive_sha256,
        'terminal_rows':len(imported.terminal_returns),
        'event_records':len(events),
        'provenance_authenticated':False,
        'claim':'Documented supplied events, not independently certified source records'}
