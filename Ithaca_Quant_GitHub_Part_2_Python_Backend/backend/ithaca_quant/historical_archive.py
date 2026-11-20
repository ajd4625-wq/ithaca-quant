"""Fail-closed, reproducible imports of *user-supplied* point-in-time market archives.

Checksums establish byte integrity, NOT vendor authenticity or universe completeness.
A source declaration is not evidence that the vendor's histories include every delisting.
Security IDs, not mutable/recycled tickers, are the modeling/backtest identifiers.
Never fetch today's tickers to fill gaps in this archive.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile, BadZipFile

import numpy as np
import pandas as pd

from .data import MarketData

FORMAT = 'ithaca-historical-v1'
MANDATORY = ('security_master.csv', 'price_history.csv', 'membership.csv')
OPTIONAL = ('terminal_returns.csv', 'financial_facts.csv')
MAX_UNCOMPRESSED = 300_000_000


@dataclass
class HistoricalBundle:
    market: MarketData
    membership: pd.DataFrame
    terminal_returns: pd.DataFrame | None
    security_master: pd.DataFrame
    fundamentals: dict[str, pd.DataFrame]
    quality: dict
    archive_sha256: str


def _dates(frame: pd.DataFrame, col: str, *, optional=False) -> pd.Series:
    if col not in frame:
        if optional:
            return pd.Series(pd.NaT, index=frame.index, dtype='datetime64[ns]')
        raise ValueError(f'Missing required date: {col}')
    raw = frame[col]
    result = pd.to_datetime(raw, errors='coerce', utc=True).dt.tz_localize(None).dt.normalize()
    if result.isna().any() and not optional:
        raise ValueError(f'Invalid date values: {col}')
    if (result.isna() & raw.notna() & raw.astype(str).str.strip().ne('')).any():
        raise ValueError(f'Invalid date values: {col}')
    return result


def _required(frame, fields, filename):
    if not set(fields).issubset(frame):
        raise ValueError(f'{filename} is missing {sorted(set(fields)-set(frame))}')
    if frame.empty:
        raise ValueError(f'{filename} is empty')


def _identity(frame):
    out = frame.copy()
    out['security_id'] = out.security_id.astype(str).str.strip().str.upper()
    if not out.security_id.str.fullmatch(r'[A-Z0-9._-]{1,50}').all():
        raise ValueError('Invalid permanent security_id (use provider-issued stable IDs)')
    return out


def load_historical_archive(source: bytes | str | Path) -> HistoricalBundle:
    """Load zipped manifest + PIT prices, snapshots, stable security identifiers.

    Accepted files are explicit and checksummed. An attacker can still fabricate
    an entirely self-consistent archive; do NOT call it independently verified.
    """
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    digest = sha256(raw).hexdigest()
    try:
        z = ZipFile(BytesIO(raw))
    except BadZipFile as exc:
        raise ValueError('Expected a ZIP historical archive') from exc
    with z:
        names = z.namelist()
        expected = set(MANDATORY) | set(OPTIONAL) | {'manifest.json'}
        if len(names) != len(set(names)) or any('/' in name or '\\' in name or name not in expected for name in names):
            raise ValueError('Archive contains unsupported, duplicate, or unsafe paths')
        if 'manifest.json' not in names or not set(MANDATORY).issubset(names):
            raise ValueError('Archive needs manifest.json, security_master.csv, price_history.csv, membership.csv')
        if sum(v.file_size for v in z.infolist()) > MAX_UNCOMPRESSED:
            raise ValueError('Archive exceeds allowed uncompressed size')
        manifest = json.loads(z.read('manifest.json'))
        if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
            raise ValueError(f'Manifest format must be {FORMAT}')
        if manifest.get('price_basis') != 'total_return_adjusted_close':
            raise ValueError('Prices must declare total_return_adjusted_close; unadjusted prices cannot be treated as total returns')
        if not isinstance(manifest.get('provider'), str) or len(manifest['provider'].strip()) < 3:
            raise ValueError('Manifest must identify the original historical data provider')
        if not isinstance(manifest.get('source_reference'), str) or not manifest['source_reference'].strip():
            raise ValueError('Manifest requires source_reference for the archive')
        hashes = manifest.get('sha256')
        if not isinstance(hashes, dict) or set(hashes) != set(names) - {'manifest.json'}:
            raise ValueError('Manifest needs SHA-256 checksums for every and only included CSV')
        frames = {}
        for filename in sorted(hashes):
            data = z.read(filename)
            if sha256(data).hexdigest() != hashes[filename]:
                raise ValueError(f'Archive integrity failure: {filename}')
            frames[filename] = pd.read_csv(BytesIO(data), dtype={'security_id':'string'}, low_memory=False)

    master = _identity(frames['security_master.csv'])
    _required(master, ('security_id','ticker','valid_from','valid_to'), 'security_master.csv')
    master['valid_from'] = _dates(master, 'valid_from')
    master['valid_to'] = _dates(master, 'valid_to', optional=True)
    master['ticker'] = master.ticker.astype(str).str.upper().str.strip()
    if master.ticker.eq('').any() or master.ticker.eq('NAN').any():
        raise ValueError('Missing ticker history')
    if (master.valid_to.notna() & (master.valid_to < master.valid_from)).any():
        raise ValueError('Inverted security-master validity interval')
    if master.duplicated(['security_id','valid_from']).any():
        raise ValueError('Duplicate security identity history intervals')
    if 'SPY' not in set(master.security_id):
        raise ValueError('Archive must include SPY as stable benchmark security_id')
    if not master.loc[master.security_id.eq('SPY'), 'ticker'].eq('SPY').all():
        raise ValueError('Reserved benchmark security_id SPY must map to SPY')
    # For the same security, non-overlapping sequential ticker history is allowed.
    # For the same ticker, a different security may reuse it ONLY after a gap.
    for key, group in master.groupby('security_id'):
        ordered = group.sort_values('valid_from')
        for a, b in zip(ordered.iloc[:-1].itertuples(), ordered.iloc[1:].itertuples()):
            if pd.isna(a.valid_to) or a.valid_to >= b.valid_from:
                raise ValueError(f'Overlapping identity intervals for {key}')
    for tick, group in master.groupby('ticker'):
        ordered = group.sort_values('valid_from')
        for a, b in zip(ordered.iloc[:-1].itertuples(), ordered.iloc[1:].itertuples()):
            if a.security_id != b.security_id and (pd.isna(a.valid_to) or a.valid_to >= b.valid_from):
                raise ValueError(f'Ticker {tick} maps to simultaneous unrelated securities')

    prices = _identity(frames['price_history.csv'])
    _required(prices, ('date','security_id','adjusted_close','raw_close','volume'), 'price_history.csv')
    prices['date'] = _dates(prices, 'date')
    if prices.duplicated(['date','security_id']).any():
        raise ValueError('Duplicated security/date bars')
    if not set(prices.security_id).issubset(set(master.security_id)):
        raise ValueError('Historical prices contain unmapped security IDs')
    prices['adjusted_close'] = pd.to_numeric(prices.adjusted_close, errors='coerce')
    prices['raw_close'] = pd.to_numeric(prices.raw_close, errors='coerce')
    if (not np.isfinite(prices.raw_close.to_numpy(dtype=float)).all() or
            (prices.raw_close <= 0).any()):
        raise ValueError('Raw contemporaneous closes must be positive and complete')
    prices['volume'] = pd.to_numeric(prices.volume, errors='coerce')
    if (not np.isfinite(prices.adjusted_close.to_numpy(dtype=float)).all() or
            (prices.adjusted_close <= 0).any()):
        raise ValueError('Nonfinite/nonpositive adjusted closes: unknown is not a price')
    if prices.volume.lt(0).any() or (np.isinf(prices.volume.to_numpy(dtype=float))).any():
        raise ValueError('Invalid negative/infinite historical volume')
    # Do not allow bars before issuance/after historical identity expired.
    joined = prices[['date','security_id']].merge(master[['security_id','valid_from','valid_to']],on='security_id')
    within = ((joined.date >= joined.valid_from) &
              (joined.valid_to.isna() | (joined.date <= joined.valid_to)))
    # Joined identity histories may expand one bar into multiple intervals;
    # every unique original bar must match exactly one valid identity interval.
    covered = joined.loc[within, ['date','security_id']].drop_duplicates()
    if len(covered) != len(prices):
        raise ValueError('Prices outside documented security ID / ticker history')
    if ((joined.loc[within].groupby(['date','security_id']).size())>1).any():
        raise ValueError('Ambiguous security identity intervals')
    benchmark = prices.loc[prices.security_id.eq('SPY')].set_index('date').adjusted_close.sort_index()
    if len(benchmark) < 2:
        raise ValueError('Insufficient SPY historical benchmark observations')
    if (benchmark.index.dayofweek >= 5).any():
        raise ValueError('SPY benchmark contains non-trading weekend dates')
    dates = pd.DatetimeIndex(benchmark.index)
    if not set(prices.date).issubset(set(dates)):
        raise ValueError('Stock observations outside the benchmark session calendar')
    close = prices.pivot(index='date',columns='security_id',values='adjusted_close').reindex(dates)
    volume = prices.pivot(index='date',columns='security_id',values='volume').reindex(dates)
    raw_close = prices.pivot(index='date',columns='security_id',values='raw_close').reindex(dates)
    close.index.name = None; volume.index.name = None; raw_close.index.name = None
    archive_members = _identity(frames['membership.csv'])
    _required(archive_members, ('date','security_id','eligible'), 'membership.csv')
    archive_members['date'] = _dates(archive_members,'date')
    if archive_members.duplicated(['date','security_id']).any():
        raise ValueError('Duplicate membership snapshot entries')
    if not set(archive_members.date).issubset(set(dates)):
        raise ValueError('Historical membership snapshot dates must be observed benchmark sessions')
    if not set(archive_members.security_id).issubset(set(master.security_id)):
        raise ValueError('Membership contains unknown historical security identities')
    flags = archive_members.eligible.astype(str).str.lower().str.strip()
    if not flags.isin(('true','false','1','0')).all():
        raise ValueError('Membership eligibility must be explicit booleans')
    archive_members['eligible'] = flags.isin(('true','1'))
    if archive_members.loc[archive_members.eligible,'security_id'].eq('SPY').any():
        raise ValueError('SPY benchmark must not be an investable stock constituent')
    active_members = archive_members.loc[archive_members.eligible,['date','security_id']].copy()
    active_windows = active_members.merge(master[['security_id','valid_from','valid_to']],on='security_id')
    valid_member = (active_windows.date >= active_windows.valid_from)&(
        active_windows.valid_to.isna()|(active_windows.date <= active_windows.valid_to))
    active_matches = active_windows.loc[valid_member,['date','security_id']].drop_duplicates()
    if len(active_matches)!=len(active_members):
        raise ValueError('Historically eligible security falls outside documented identity/listing lifetime')
    membership = archive_members.rename(columns={'security_id':'ticker'})[['date','ticker','eligible']].copy()
    membership['provenance'] = 'historical_archive'

    terminal = None
    if 'terminal_returns.csv' in frames:
        terminal = _identity(frames['terminal_returns.csv'])
        _required(terminal, ('signal_date','security_id','asof_total_return','entry_total_return','event_date','source_reference'), 'terminal_returns.csv')
        terminal['signal_date'] = _dates(terminal, 'signal_date')
        terminal['event_date'] = _dates(terminal,'event_date')
        if terminal.duplicated(['signal_date','security_id']).any():
            raise ValueError('Conflicting terminal outcomes for same security/date')
        if not set(terminal.security_id).issubset(set(master.security_id)):
            raise ValueError('Unknown delisted security IDs in payoff archive')
        if (terminal.event_date < terminal.signal_date).any():
            raise ValueError('Delisting events cannot predate the simulated signal')
        if terminal.source_reference.isna().any() or terminal.source_reference.astype(str).str.strip().eq('').any():
            raise ValueError('Each delisting payoff requires a cited source reference')
        for col in ('asof_total_return','entry_total_return'):
            terminal[col] = pd.to_numeric(terminal[col],errors='coerce')
            if not np.isfinite(terminal[col].to_numpy(float)).all() or (terminal[col] < -1).any():
                raise ValueError('Invalid documented delisting total return')
        terminal = terminal.rename(columns={'security_id':'ticker'})
        terminal['source'] = 'historical_archive'

    # SEC archive features: source filing dates and accession IDs are mandatory.
    # We cannot authenticate these filings to EDGAR without source verification.
    fundamentals = {}
    if 'financial_facts.csv' in frames:
        fact = _identity(frames['financial_facts.csv'])
        _required(fact, ('security_id','filed','period_end','accession','revenue_usd','net_income_usd'), 'financial_facts.csv')
        fact['filed'] = _dates(fact,'filed')
        fact['period_end'] = _dates(fact,'period_end')
        if (fact.filed < fact.period_end).any() or fact.accession.isna().any() or fact.accession.astype(str).str.strip().eq('').any():
            raise ValueError('Financial fact filing times/IDs invalid')
        if not set(fact.security_id).issubset(set(master.security_id)):
            raise ValueError('Unmapped issuer in SEC filing archive')
        for col in ('revenue_usd','net_income_usd'):
            fact[col]=pd.to_numeric(fact[col],errors='coerce')
        if fact.duplicated(['security_id','period_end','filed','accession']).any():
            raise ValueError('Duplicate archival filing records')
        from .fundamentals import quarterly_history_from_records
        for sid, rows in fact.groupby('security_id'):
            fundamentals[sid] = quarterly_history_from_records(rows)

    # Diagnostic rates indicate only internal completeness, not representativeness
    # or completeness of a vendor's overall delisted universe.
    stock = close.drop(columns=['SPY'])
    gaps = (stock.isna() & stock.ffill().notna() & stock.bfill().notna()).sum().sum()
    stock_returns = stock.pct_change(fill_method=None)
    jump_count = int((stock_returns.abs() > .75).sum().sum())
    missing_volume = int(volume.drop(columns=['SPY']).isna().sum().sum())
    present_stock_bars = int(stock.notna().sum().sum())
    total = (stock.ffill().notna() & stock.bfill().notna()).sum().sum()
    quality = {
        'provider_declared': manifest['provider'].strip(),
        'source_reference': manifest['source_reference'].strip(),
        'integrity_sha256_verified': True,
        'vendor_authenticity_verified': False,
        'historical_universe_completeness_verified': False,
        'security_id_count': int(stock.shape[1]),
        'membership_snapshot_dates': int(membership.date.nunique()),
        'membership_records': int(len(membership)),
        'terminal_payoff_rows': int(len(terminal)) if terminal is not None else 0,
        'filed_fundamental_issuers': len(fundamentals),
        'price_bar_internal_gap_rate': float(gaps / total) if total else None,
        'large_adjusted_move_count_over_75pct': jump_count,
        'missing_volume_cells': missing_volume,
        'observed_stock_price_bars': present_stock_bars,
        'date_first': str(dates.min().date()),
        'date_last': str(dates.max().date()),
        'archive_sha256': digest,
        'warnings': ['Checksum integrity is NOT independent source authentication.',
                     'Historical universe completeness and delisting cash flows require external provider verification.'],
    }
    if jump_count:
        quality['warnings'].append(f'{jump_count} extreme daily adjusted changes (>75%) require split/corporate-action review.')
    if missing_volume:
        quality['warnings'].append(f'{missing_volume} unknown volume cells are preserved as missing, not zero.')
    return HistoricalBundle(MarketData(close, volume, 'PIT USER ARCHIVE: '+manifest['provider']+' (integrity checked; provenance declared)', [], raw_close=raw_close),
                            membership, terminal, master, fundamentals, quality, digest)
