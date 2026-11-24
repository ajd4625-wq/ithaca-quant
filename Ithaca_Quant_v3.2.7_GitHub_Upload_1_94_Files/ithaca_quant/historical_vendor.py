"""Acquire and normalize licensed Sharadar historical equity records.

This module does NOT pretend that metadata plus checksums certify a complete
historical market.  Its purpose is to consume actual licensed vendor tables,
retain delisted issues, use permanent IDs, and leave unverified payouts missing.

Vendor documentation: https://sharadar.com/docs/{stocks,tickers,funds,actions}
A supplier key and export rights are necessary to fetch the underlying records.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, is_zipfile
import io
import json
import os
import re
import tempfile

import numpy as np
import pandas as pd
import requests

from .historical_archive import load_historical_archive

API_BASE = 'https://api.sharadar.com/v1.0/data'
COMMON_STOCK_CATEGORIES = {'Domestic Common Stock', 'Domestic Common Stock Primary Class',
                           'Domestic Common Stock Secondary Class'}
REQUIRED_TICKERS = {'table','permaticker','ticker','category','firstpricedate','lastpricedate','isdelisted'}
REQUIRED_STOCKS = {'ticker','date','closeadj','closeunadj','volume'}
MAX_VENDOR_FILE_BYTES = 3_000_000_000


class HistoricalVendorError(ValueError):
    """Non-sensitive quality failure, without vendor secrets in error details."""


def _validate_date(value: str) -> pd.Timestamp:
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise HistoricalVendorError('Use valid YYYY-MM-DD dates.') from exc
    if ts.tzinfo is not None or ts.strftime('%Y-%m-%d') != value:
        raise HistoricalVendorError('Dates must use YYYY-MM-DD without timezone.')
    return ts


def download_sharadar_table(table: str, destination: Path, *, api_key: str,
                            session=None, max_bytes: int = MAX_VENDOR_FILE_BYTES) -> dict:
    """Download full vendor ZIP to a private directory; stream instead of buffering.

    Does not log complete URLs: the vendor uses api_key as a query parameter.
    Only official HTTPS endpoint and its provider redirect are followed.
    """
    if table not in ('stocks','tickers','actions'):
        raise HistoricalVendorError('Unsupported vendor table')
    if not api_key:
        raise HistoricalVendorError('Set SHARADAR_API_KEY through an environment variable.')
    if destination.exists():
        raise HistoricalVendorError(f'Refusing to overwrite existing vendor file {destination.name}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    http = session or requests.Session()
    try:
        with http.get(f'{API_BASE}/{table}',
                      params={'api_key':api_key,'years':'full'},
                      stream=True,timeout=(15,120),allow_redirects=True) as response:
            if not response.ok:
                raise HistoricalVendorError(f'Vendor {table} download failed (HTTP {response.status_code}). Check entitlement.')
            if response.url and not response.url.startswith('https://'):
                raise HistoricalVendorError('Insecure vendor download redirect refused.')
            digest=sha256();size=0
            temp=destination.with_suffix('.partial')
            try:
                with temp.open('wb') as out:
                    for part in response.iter_content(chunk_size=1024*1024):
                        if not part: continue
                        size += len(part)
                        if size > max_bytes:
                            raise HistoricalVendorError(f'Vendor table {table} exceeds the configured size limit.')
                        out.write(part);digest.update(part)
                if not is_zipfile(temp):
                    raise HistoricalVendorError(f'Vendor {table} response was not a ZIP file.')
                temp.replace(destination)
            finally:
                temp.unlink(missing_ok=True)
    except requests.RequestException as exc:
        # Do not print request URLs -- the request query contains the user's API key.
        raise HistoricalVendorError(f'Unable to retrieve vendor {table} table; check connectivity and credentials.') from None
    return {'table':table,'download_bytes':size,'sha256':digest.hexdigest()}



def download_spy_funds(destination: Path, *, api_key: str, start: str, end: str,
                       session=None) -> dict:
    """Fetch licensed SPY FUND prices explicitly; STOCKS excludes ETFs.

    Range-scoped request avoids downloading all funds. Large limits are checked
    against the requested number of sessions; no implicit pagination/truncation.
    """
    start_ts,end_ts=_validate_date(start),_validate_date(end)
    if end_ts<=start_ts:
        raise HistoricalVendorError('Invalid SPY download date interval.')
    if not api_key:
        raise HistoricalVendorError('SHARADAR_API_KEY is required.')
    if destination.exists():
        raise HistoricalVendorError('Refusing to overwrite an existing SPY vendor file.')
    http=session or requests.Session()
    try:
        response=http.get(f'{API_BASE}/funds',params={'api_key':api_key,'format':'csv',
             'ticker':'SPY','from':start,'to':end,'limit':100000},timeout=(15,120))
        if not response.ok:
            raise HistoricalVendorError(f'Sharadar SPY FUNDS download failed HTTP {response.status_code}.')
        if len(response.content)>20_000_000:
            raise HistoricalVendorError('SPY vendor download exceeds size limit.')
        spy=pd.read_csv(io.BytesIO(response.content))
    except requests.RequestException:
        raise HistoricalVendorError('Could not retrieve authorized SPY FUNDS price records.') from None
    except (pd.errors.ParserError,UnicodeDecodeError) as exc:
        raise HistoricalVendorError('Provider SPY response is not valid CSV.') from exc
    if not REQUIRED_STOCKS.issubset(spy):
        raise HistoricalVendorError('Provider SPY response lacks full price adjustment fields.')
    spy_dates=pd.to_datetime(spy.date,errors='coerce')
    if (len(spy)<40 or not _symbols(spy.ticker).eq('SPY').all() or
            spy_dates.isna().any() or spy_dates.duplicated().any() or
            (spy_dates<start_ts).any() or (spy_dates>end_ts).any()):
        raise HistoricalVendorError('Provider SPY response is incomplete, malformed or outside requested dates.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(response.content)
    return {'table':'funds_SPY','rows':len(spy),'sha256':sha256(response.content).hexdigest()}

def read_vendor_table(path: Path, required: set[str], *, chunksize: int | None = None):
    """Read vendor ZIP/CSV with safe single-member ZIP handling.

    A chunksize returns a pandas TextFileReader, which holds the opened archive
    (caller must keep the contextmanager open); intended for large stocks data.
    """
    path=Path(path)
    if not path.exists():
        raise HistoricalVendorError(f'Missing licensed vendor export {path.name}')
    if path.suffix.lower()=='.csv':
        if chunksize:
            return pd.read_csv(path,chunksize=chunksize,low_memory=False)
        frame=pd.read_csv(path,low_memory=False)
    elif path.suffix.lower()=='.zip':
        with ZipFile(path) as z:
            names=[n for n in z.namelist() if n.lower().endswith('.csv') and '/' not in n and '\\' not in n]
            if len(names)!=1:
                raise HistoricalVendorError(f'{path.name} must contain exactly one root-level vendor CSV.')
            info=z.getinfo(names[0])
            if info.file_size>10_000_000_000:
                raise HistoricalVendorError('Vendor ZIP uncompressed size exceeds safety limit.')
            # For large exports, process one chunk at a time under an open ZipFile;
            # no entire-file read into memory.
            if chunksize is not None:
                raise HistoricalVendorError('Use iter_vendor_csv_chunks for large compressed files.')
            with z.open(names[0]) as handle:
                frame=pd.read_csv(handle,low_memory=False)
    else:
        raise HistoricalVendorError('Expected vendor CSV or zipped CSV export.')
    missing=required-set(frame.columns)
    if missing: raise HistoricalVendorError(f'{path.name} missing columns: {sorted(missing)}')
    return frame


def iter_vendor_csv_chunks(path: Path, *, chunksize=80_000):
    path=Path(path)
    if path.suffix.lower()=='.csv':
        yield from pd.read_csv(path,chunksize=chunksize,low_memory=False)
        return
    if path.suffix.lower()!='.zip':
        raise HistoricalVendorError('Vendor stock history must be CSV or ZIP.')
    with ZipFile(path) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv') and '/' not in n and '\\' not in n]
        if len(names)!=1:
            raise HistoricalVendorError('Vendor ZIP must contain exactly one root-level CSV.')
        if z.getinfo(names[0]).file_size>10_000_000_000:
            raise HistoricalVendorError('Vendor ZIP uncompressed size exceeds safety limit.')
        with z.open(names[0]) as handle:
            yield from pd.read_csv(handle,chunksize=chunksize,low_memory=False)


def _symbols(frame: pd.DataFrame) -> pd.Series:
    return frame.astype('string').str.strip().str.upper()


def normalize_tickers(tickers: pd.DataFrame) -> pd.DataFrame:
    if not REQUIRED_TICKERS.issubset(tickers):
        raise HistoricalVendorError(f'TICKERS missing: {sorted(REQUIRED_TICKERS-set(tickers))}')
    tick=tickers.copy()
    tick['table']=_symbols(tick['table'])
    tick=tick[tick['table'].eq('STOCKS') & tick['category'].isin(COMMON_STOCK_CATEGORIES)].copy()
    if tick.empty: raise HistoricalVendorError('No domestic common stocks in TICKERS export.')
    tick['ticker']=_symbols(tick['ticker'])
    tick['security_id']='SH'+tick['permaticker'].astype('string').str.strip()
    for col in ('firstpricedate','lastpricedate'):
        tick[col]=pd.to_datetime(tick[col],errors='coerce').dt.normalize()
    if tick[['firstpricedate','lastpricedate']].isna().any().any():
        raise HistoricalVendorError('Missing dated listing bounds in vendor security master.')
    if (tick.lastpricedate<tick.firstpricedate).any():
        raise HistoricalVendorError('Inverted vendor listing interval.')
    if tick.security_id.str.fullmatch(r'SH[A-Za-z0-9._-]{1,48}').ne(True).any():
        raise HistoricalVendorError('Invalid vendor-issued permaticker.')
    if tick.ticker.str.fullmatch(r'[A-Z0-9._-]+').ne(True).any():
        raise HistoricalVendorError('Invalid ticker in source table.')
    if tick.security_id.duplicated().any():
        raise HistoricalVendorError('Duplicate permaticker in source table.')
    if tick.ticker.duplicated().any():
        # Multiple tickers including reused symbols require an explicit dated
        # crosswalk. Never pick one identity from today's mapping.
        raise HistoricalVendorError('Non-unique ticker in TICKERS; dated security crosswalk needed.')
    return tick[['ticker','security_id','firstpricedate','lastpricedate','isdelisted','category']]


def _write_append(path: Path, df: pd.DataFrame, *, header: bool):
    df.to_csv(path,mode='w' if header else 'a',index=False,header=header)


def build_from_sharadar_exports(*, tickers_path: Path, stocks_path: Path,
                                spy_path: Path, output_path: Path,
                                start: str, end: str,
                                actions_path: Path | None = None,
                                min_delisted_issues: int = 1,
                                source_reference: str = 'vendor export; verify extract ID',
                                chunksize: int = 80_000) -> dict:
    """Build real historical constituent archive from LICENSED Sharadar exports.

    The universe is **all observed domestic common-stock bars** in the licensed
    complete TICKERS+STOCKS export within the requested interval, not S&P 500
    index membership.  Selection happens after that session's close.  This does
    not invent delisting settlement payoffs; missing outcomes fail in backtests.

    Full universe size may exceed Streamlit memory/upload limits; use bounded
    historical windows for the existing in-memory engine.
    """
    from ithaca_quant.historical_vendor_package import package_vendor_archive
    start_ts,end_ts=_validate_date(start),_validate_date(end)
    if end_ts<=start_ts: raise HistoricalVendorError('End date must follow start date.')
    if min_delisted_issues<0: raise HistoricalVendorError('Invalid minimum delisted count.')
    tick=normalize_tickers(read_vendor_table(Path(tickers_path),REQUIRED_TICKERS))
    expected_ids=set(tick.loc[(tick.firstpricedate<=end_ts)&
                              (tick.lastpricedate>=start_ts),'security_id'])
    if not expected_ids:
        raise HistoricalVendorError('No securities were documented as listed in the requested historical window.')
    # SPY should be taken from actual vendor FUNDS data, not synthesized from
    # stock data and never treated as an investable stock.
    spy_frames=[]
    for c in iter_vendor_csv_chunks(Path(spy_path),chunksize=chunksize):
        if not REQUIRED_STOCKS.issubset(c):
            raise HistoricalVendorError('FUNDS export needs ticker,date,closeadj,closeunadj,volume.')
        c=c.loc[_symbols(c.ticker).eq('SPY')].copy()
        if c.empty: continue
        c['date']=pd.to_datetime(c.date,errors='coerce').dt.normalize()
        c=c[(c.date>=start_ts)&(c.date<=end_ts)]
        spy_frames.append(c)
    if not spy_frames:
        raise HistoricalVendorError('Missing actual vendor SPY total-return benchmark for the window.')
    spy=pd.concat(spy_frames,ignore_index=True)
    if spy.date.isna().any() or spy.date.duplicated().any():
        raise HistoricalVendorError('Invalid or duplicate SPY vendor dates.')
    spy['adjusted_close']=pd.to_numeric(spy.closeadj,errors='coerce')
    spy['raw_close']=pd.to_numeric(spy.closeunadj,errors='coerce')
    spy['volume']=pd.to_numeric(spy.volume,errors='coerce')
    if spy[['adjusted_close','raw_close']].isna().any().any() or (spy[['adjusted_close','raw_close']]<=0).any().any():
        raise HistoricalVendorError('Missing positive original/adjusted benchmark prices.')
    spy_sessions=set(spy.date)
    if len(spy_sessions)<40:
        raise HistoricalVendorError('At least 40 observed SPY sessions required.')
    observed=Counter();observed_delisted=set();absent=set(tick.ticker.tolist());chunk_count=0
    with tempfile.TemporaryDirectory(prefix='ithaca_vendor_') as scratch:
        root=Path(scratch)
        price_out=root/'price_history.csv';member_out=root/'membership.csv';master_out=root/'security_master.csv'
        price_header=member_header=True
        uniq_dates=set()
        for chunk in iter_vendor_csv_chunks(Path(stocks_path),chunksize=chunksize):
            chunk_count+=1
            if not REQUIRED_STOCKS.issubset(chunk):
                raise HistoricalVendorError('STOCKS export missing mandatory OHLCV fields.')
            chunk=chunk.copy()
            chunk['ticker']=_symbols(chunk.ticker)
            chunk['date']=pd.to_datetime(chunk.date,errors='coerce').dt.normalize()
            if chunk.date.isna().any():
                raise HistoricalVendorError('Invalid STOCKS price date.')
            chunk=chunk[(chunk.date>=start_ts)&(chunk.date<=end_ts)]
            if chunk.empty: continue
            # Unknown ticker rows may be preferreds, ADRs or ETFs; they are
            # deliberately excluded, not silently joined to a different firm.
            chunk=chunk.merge(tick,on='ticker',how='inner',validate='many_to_one')
            if chunk.empty: continue
            if ((chunk.date < chunk.firstpricedate)|(chunk.date>chunk.lastpricedate)).any():
                raise HistoricalVendorError('Price date outside vendor security listing dates.')
            if not chunk.date.isin(spy_sessions).all():
                raise HistoricalVendorError('Vendor prices outside observed benchmark sessions.')
            price=pd.DataFrame({'date':chunk.date.dt.strftime('%Y-%m-%d'),
                                'security_id':chunk.security_id,
                                'adjusted_close':pd.to_numeric(chunk.closeadj,errors='coerce'),
                                'raw_close':pd.to_numeric(chunk.closeunadj,errors='coerce'),
                                'volume':pd.to_numeric(chunk.volume,errors='coerce')})
            if price[['adjusted_close','raw_close']].isna().any().any() or (price[['adjusted_close','raw_close']]<=0).any().any():
                raise HistoricalVendorError('Vendor missing total-return or original close; cannot silently impute.')
            if ((price.volume<0)|np.isinf(price.volume.to_numpy(float))).any():
                raise HistoricalVendorError('Invalid vendor share volume.')
            # CSV chunks may split a ticker's history; global duplicates are
            # detected by the archive integrity loader.
            _write_append(price_out,price,header=price_header);price_header=False
            memb=price[['date','security_id']].copy();memb['eligible']=True
            _write_append(member_out,memb,header=member_header);member_header=False
            for t in chunk.ticker.unique(): absent.discard(t)
            observed.update(chunk.security_id.value_counts().to_dict())
            observed_delisted.update(chunk.loc[_symbols(chunk.isdelisted).eq('Y'),'security_id'])
            uniq_dates.update(chunk.date.unique())
        if not observed:
            raise HistoricalVendorError('No common-stock bars downloaded for the selected period.')
        missing_listed=expected_ids-set(observed)
        if missing_listed:
            raise HistoricalVendorError(
                f'Incomplete vendor STOCKS export: {len(missing_listed)} historically listed '
                'common stocks have zero prices in the requested window. '
                'Check full export coverage before proceeding. ' +
                ', '.join(sorted(missing_listed)[:6]))
        # A ticker with one surviving price bar is not evidence of a complete
        # daily history. Reject large internal gaps; do not forward-fill them.
        calendar=np.array(sorted(spy_sessions),dtype='datetime64[ns]')
        price_coverage_issues=[]
        for row in tick.loc[tick.security_id.isin(expected_ids)].itertuples():
            lo=max(start_ts,row.firstpricedate)
            hi=min(end_ts,row.lastpricedate)
            expected_sessions=int(((calendar>=np.datetime64(lo))&
                                   (calendar<=np.datetime64(hi))).sum())
            if expected_sessions>=20 and observed.get(row.security_id,0)/expected_sessions<.95:
                price_coverage_issues.append((row.security_id,observed.get(row.security_id,0),expected_sessions))
        if price_coverage_issues:
            raise HistoricalVendorError(
                f'Incomplete daily vendor prices for {len(price_coverage_issues)} securities '
                '(below 95% of documented listing-session coverage). '
                'Check vendor missing bars versus verified trading suspensions: '+
                str(price_coverage_issues[:5]))
        if len(observed_delisted)<min_delisted_issues:
            raise HistoricalVendorError('Historical archive lacks required delisted security coverage; cannot call it survivor-bias-safe.')
        s=spy[['date','adjusted_close','raw_close','volume']].copy()
        s['date']=s.date.dt.strftime('%Y-%m-%d');s['security_id']='SPY'
        _write_append(price_out,s[['date','security_id','adjusted_close','raw_close','volume']],header=price_header)
        # Only securities with observed actual prices enter the archive; no
        # placeholder identifiers, synthetic bars or fabricated eligibility.
        historical_ids=set(observed)
        master=tick[tick.security_id.isin(historical_ids)].copy()
        master['valid_from']=master.firstpricedate.dt.strftime('%Y-%m-%d')
        # No prices beyond lastpricedate. For all source shares, bound the
        # historical identity interval (including currently active issues).
        master['valid_to']=master.lastpricedate.dt.strftime('%Y-%m-%d')
        master=master[['security_id','ticker','valid_from','valid_to']]
        master=pd.concat([master,pd.DataFrame([{'security_id':'SPY','ticker':'SPY',
                   'valid_from':spy.date.min().strftime('%Y-%m-%d'),
                   'valid_to':spy.date.max().strftime('%Y-%m-%d')}])],ignore_index=True)
        master.to_csv(master_out,index=False)
        # Never construct payoffs from last observed trade alone. Actions do
        # not guarantee cash settlement or bankrupt recovery terms.
        action_count=0
        ticker_change_events=0
        if actions_path:
            action=read_vendor_table(Path(actions_path),{'ticker','date','action'})
            action['date']=pd.to_datetime(action.date,errors='coerce').dt.normalize()
            if action.date.isna().any():
                raise HistoricalVendorError('Invalid corporate-action event dates.')
            action_count=len(action)
            relevant_action=action[(action.date>=start_ts)&(action.date<=end_ts)]
            ticker_change_events=int(relevant_action.action.astype(str).str.lower().str.contains('tickerchange').sum())
        output_path=Path(output_path)
        quality=package_vendor_archive(root,output_path,provider='Sharadar licensed exports',
             source_reference=source_reference)
    summary={
      'archive':str(output_path),'provenance':'LICENSED_VENDOR_EXPORT; NOT INDEPENDENTLY CERTIFIED',
      'window_start':start,'window_end':end,
      'observed_common_stock_security_ids':len(historical_ids),
      'observed_delisted_issue_ids':len(observed_delisted),
      'listed_metadata_without_window_prices':len(absent),
      'benchmark_sessions':len(spy_sessions),
      'price_rows':sum(observed.values())+len(spy),
      'corporate_action_rows_supplied':action_count,
      'ticker_change_events_in_window':ticker_change_events,
      'terminal_payoffs_verified':0,
      'institutional_grade_certified':False,
      'warnings':[
        'Source fidelity and full delisting universe need vendor reconciliation; import alone cannot certify them.',
        'Delisting/merger payouts are NOT inferred from the last close; strict backtests fail if a payoff is required.',
        'Historical eligible universe means observed domestic common stocks, not historical index membership.',
        'Corporate-action records are inspected but ticker-change histories and settlement details are not independently reconstructed.',
        'Licensed vendor data must remain private; never upload your generated market archive to public GitHub.'
      ],
      'archive_validation':quality,
    }
    summary_path=output_path.with_suffix('.quality.json')
    summary_path.write_text(json.dumps(summary,indent=2,default=str))
    return summary
