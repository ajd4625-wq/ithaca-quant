"""Free-source Yahoo + SEC *research subset*, never a certified PIT universe.

The output is safe to inspect and reuse locally, but selecting today's ticker list
creates survivorship bias. Yahoo does not guarantee delisted-series availability,
and its adjusted prices may be revised after corporate actions. Never relabel
these observations as a complete historical stock universe or delisting outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import time

import numpy as np
import pandas as pd

from .data import MarketData, download_market_data
from .fundamentals import (SEC_COMPANY_TICKERS, SEC_FACTS, get_json,
                           cik_from_directory, public_quarterly_history)
from .incremental import completed_daily_only, overlap_conflicts

FORMAT = 'ithaca-free-research-v1'
_ALLOWED = re.compile(r'^[A-Z][A-Z0-9.\-]{0,12}$')


@dataclass
class FreeResearchBundle:
    market: MarketData
    fundamentals: dict[str, pd.DataFrame]
    quality: dict


def _safe_symbol(symbol: str) -> str:
    s = str(symbol).strip().upper()
    if not _ALLOWED.fullmatch(s):
        raise ValueError(f'Invalid Yahoo research ticker: {symbol!r}')
    return s


def _price_rows(data: MarketData) -> pd.DataFrame:
    if data.raw_close is None:
        raise ValueError('Separate Yahoo Close and Adj Close are required for research archival')
    prices = data.close.stack(future_stack=True).dropna().rename('adjusted_close').reset_index()
    prices.columns = ['date', 'ticker', 'adjusted_close']
    raw = data.raw_close.stack(future_stack=True).dropna().rename('raw_close').reset_index()
    raw.columns = ['date', 'ticker', 'raw_close']
    vol = data.volume.stack(future_stack=True).dropna().rename('volume').reset_index()
    vol.columns = ['date', 'ticker', 'volume']
    prices = prices.merge(raw, on=['date', 'ticker'], how='left', validate='one_to_one')
    prices = prices.merge(vol, on=['date', 'ticker'], how='left', validate='one_to_one')
    if prices.raw_close.isna().any():
        raise ValueError('Yahoo trading-price observations are missing from requested history')
    return prices.sort_values(['date', 'ticker']).reset_index(drop=True)


def fetch_free_sec_histories(symbols: list[str], contact: str, *,
                             directory=None, client=None, pause: float = .4,
                             sleeper=time.sleep) -> tuple[dict[str, pd.DataFrame], dict]:
    """Fetch current-issuer CIK companyfacts; no claim of historical ticker identity.

    SEC calls use a declared contact (not a secret) and a modest <10/s rate.
    If a ticker cannot be uniquely matched, preserve a diagnostic, not a guess.
    """
    if not contact:
        raise ValueError('SEC_CONTACT_EMAIL required when SEC acquisition is enabled')
    directory = directory if directory is not None else get_json(SEC_COMPANY_TICKERS, contact, client)
    results = {}
    status = {}
    for symbol in dict.fromkeys(_safe_symbol(x) for x in symbols):
        if symbol == 'SPY':
            continue
        cik, company = cik_from_directory(directory, symbol)
        if cik is None:
            status[symbol] = {'status':'no_current_SEC_CIK', 'company':company}
            continue
        try:
            facts = get_json(SEC_FACTS.format(cik=cik), contact, client)
            frame = public_quarterly_history(facts)
            if frame.empty:
                status[symbol] = {'status':'no_standardized_quarterly_facts', 'cik':cik}
            else:
                results[symbol] = frame
                status[symbol] = {'status':'fetched', 'cik':cik,
                                  'vintage_events':len(frame)}
        except Exception as exc:
            status[symbol] = {'status':'provider_error', 'cik':cik,
                              'error':type(exc).__name__}
        if pause:
            sleeper(pause)
    return results, status


def build_free_bundle(output_dir: str | Path, symbols: list[str], *,
                      years: int = 8, min_history: int = 30,
                      sec_contact: str | None = None, fetch_prices=None,
                      fetch_sec=None, completed_only=True) -> dict:
    """Acquire real free-source records with checksums; no fabricated membership.

    Missing symbols and failed SEC calls remain explicit. An existing bundle is
    replaced only after a complete new manifest and its component files exist.
    This is an observed-current-symbol subset, NOT institution-grade PIT data.
    """
    out = Path(output_dir).expanduser()
    requested = list(dict.fromkeys(_safe_symbol(x) for x in symbols if str(x).strip()))
    if not requested or years < 1 or min_history < 1:
        raise ValueError('Provide nonempty stock symbols and valid history settings')
    if 'SPY' in requested:
        requested.remove('SPY')
    downloader = fetch_prices or download_market_data
    start_date = (pd.Timestamp.now(tz='UTC') - pd.DateOffset(years=years)).strftime('%Y-%m-%d')
    market = downloader(requested, years=years, start=start_date, min_history=min_history)
    if completed_only:
        market = completed_daily_only(market)
    if 'SPY' not in market.close or market.close.empty:
        raise ValueError('Yahoo SPY benchmark observations unavailable')
    if not set(market.close.columns) <= set(requested)|{'SPY'}:
        raise ValueError('Unexpected symbol returned by free market source')
    price_rows = _price_rows(market)
    if price_rows.empty:
        raise ValueError('No complete observed market bars returned')
    files = {'prices.csv':price_rows.to_csv(index=False).encode('utf-8')}
    sec_status = {'status':'not_requested'}
    if sec_contact:
        getter = fetch_sec or fetch_free_sec_histories
        vintages, sec_status = getter(requested, sec_contact)
        for symbol, frame in vintages.items():
            if symbol not in requested:
                raise ValueError('SEC fetch returned an unrequested issuer')
            if 'asof_event' not in frame or 'filed' not in frame:
                raise ValueError('SEC history lacks dated vintage events')
            name = f'sec/{_safe_symbol(symbol)}.csv'
            files[name] = frame.to_csv(index=False).encode('utf-8')
    observed = sorted(set(market.close.columns) - {'SPY'})
    omitted = sorted(set(requested) - set(observed))
    result = {
        'format': FORMAT, 'data_grade':'FREE_OBSERVED_TICKER_SUBSET_NOT_PIT_UNIVERSE',
        'price_source':'Yahoo Finance via yfinance (unofficial, personal-use terms apply)',
        'sec_source':'SEC EDGAR XBRL companyfacts via data.sec.gov',
        'download_utc':datetime.now(timezone.utc).isoformat(),
        'requested_symbols':requested, 'observed_symbols':observed,
        'missing_symbols':omitted, 'sec_status':sec_status,
        'benchmark_sessions':int(market.close['SPY'].notna().sum()),
        'bars_by_symbol':{s:int(market.close[s].notna().sum()) for s in sorted(market.close)},
        'universe_coverage_verified':False, 'delisted_returns_verified':False,
        'issuer_mapping_historical_verified':False,
        'historical_adjustments_are_as_downloaded_now':True,
        'missing_return_outcomes_are_not_zero':True,
        'warnings':[
            'Symbols were supplied as a present-day watchlist, NOT a reconstructed historical membership universe.',
            'Yahoo generally cannot recover all defunct securities or verified bankruptcy/merger payouts.',
            'Yahoo historical adjusted closes can be revised after dividends/splits; not an archived as-known-then price tape.',
            'SEC current ticker-to-CIK mapping does not authenticate historical symbol/issuer crosswalks.',
            'No training/backtest or live advantage is certified from this bundle.',
        ],
        'sha256':{name:sha256(blob).hexdigest() for name,blob in files.items()},
    }
    out.mkdir(parents=True, exist_ok=True)
    # Commit file content before manifest so the latter is never ahead of data.
    for name, content in files.items():
        dest = out / name
        dest.parent.mkdir(parents=True,exist_ok=True)
        tmp = dest.with_name(dest.name+'.tmp')
        tmp.write_bytes(content)
        tmp.replace(dest)
    manifest_file = out/'manifest.json'
    temp_manifest = out/'manifest.json.tmp'
    temp_manifest.write_text(json.dumps(result, indent=2, sort_keys=True))
    temp_manifest.replace(manifest_file)
    return result


def load_free_bundle(root: str | Path) -> FreeResearchBundle:
    """Recheck hashes and labelled quality; never call this a PIT archive."""
    base = Path(root).expanduser()
    manifest = json.loads((base/'manifest.json').read_text())
    if manifest.get('format') != FORMAT or manifest.get('data_grade') != 'FREE_OBSERVED_TICKER_SUBSET_NOT_PIT_UNIVERSE':
        raise ValueError('Unsupported or misleading free research manifest')
    files = manifest.get('sha256', {})
    if 'prices.csv' not in files or not isinstance(files,dict):
        raise ValueError('Missing free-price archive inventory')
    for name, expected in files.items():
        if name != 'prices.csv' and not re.fullmatch(r'sec/[A-Z][A-Z0-9.\-]{0,12}\.csv',name):
            raise ValueError('Unexpected archival file')
        content = (base/name).read_bytes()
        if sha256(content).hexdigest() != expected:
            raise ValueError(f'Free-history hash mismatch: {name}')
    prices = pd.read_csv(base/'prices.csv', parse_dates=['date'])
    required = {'date','ticker','adjusted_close','raw_close','volume'}
    if (not required.issubset(prices) or prices.empty or prices.date.isna().any() or
            prices.duplicated(['date','ticker']).any()):
        raise ValueError('Incomplete or duplicated free price records')
    prices.ticker = prices.ticker.astype(str).str.upper()
    if set(prices.ticker) != set(manifest['observed_symbols'])|{'SPY'}:
        raise ValueError('Current-symbol history does not match declared coverage')
    for name in ('adjusted_close','raw_close'):
        prices[name] = pd.to_numeric(prices[name],errors='coerce')
        if not (np.isfinite(prices[name]).all() and (prices[name] > 0).all()):
            raise ValueError(f'Invalid free historical {name}')
    prices['volume'] = pd.to_numeric(prices['volume'],errors='coerce')
    if prices.volume.lt(0).any() or np.isinf(prices.volume).any():
        raise ValueError('Invalid free historical volume')
    spy_dates = pd.DatetimeIndex(sorted(prices.loc[prices.ticker.eq('SPY'),'date'].unique()))
    if spy_dates.empty or not set(prices.date).issubset(set(spy_dates)):
        raise ValueError('Free historical stocks fall outside SPY sessions')
    kwargs = {}
    for fld in ['adjusted_close','raw_close','volume']:
        kwargs[fld] = prices.pivot(index='date',columns='ticker',values=fld).reindex(spy_dates)
    fundamentals={}
    for name in files:
        if name.startswith('sec/'):
            sym = Path(name).stem
            df = pd.read_csv(base/name,parse_dates=['asof_event','filed','period_end'])
            if (df['asof_event'] < df['filed']).any():
                raise ValueError('SEC vintage date before SEC filing date')
            fundamentals[sym] = df.sort_values('asof_event')
    source = 'FREE WATCHLIST-SELECTED Yahoo + SEC; NOT historical full-universe PIT'
    market = MarketData(kwargs['adjusted_close'],kwargs['volume'],source,
                        manifest.get('missing_symbols',[]),raw_close=kwargs['raw_close'])
    return FreeResearchBundle(market,fundamentals,manifest)


def extend_with_free_history(live: MarketData, bundle: FreeResearchBundle) -> MarketData:
    """Use historical older bars only; never overwrite latest observed live quotes.

    Require an overlapping verified price scale. No forward filling. A symbol
    appearing only in the old present-day watchlist is NOT a new live candidate.
    """
    if 'SPY' not in live.close or 'SPY' not in bundle.market.close:
        raise ValueError('SPY reference missing')
    hist = bundle.market
    common = live.close.index.intersection(hist.close.index)
    if len(common) < 2:
        raise ValueError('Free archive has insufficient overlap with current Yahoo prices')
    conflicts = overlap_conflicts(hist, live, tolerance=.025)
    if conflicts:
        raise ValueError('Free archive price-adjustment conflict; rebuild from Yahoo: '+', '.join(conflicts[:8]))
    # Ensure the overlap really covers the prices of every requested stock,
    # not only SPY. Prevent a split-dislocated ticker from being spliced in.
    stocks = live.close.columns.intersection(hist.close.columns)
    for ticker in stocks:
        a = hist.close.loc[common,ticker]
        b = live.close.loc[common,ticker]
        both = a.notna() & b.notna()
        if both.sum() < 2 or ((a[both] / b[both] - 1).abs() > .025).any():
            raise ValueError(f'Insufficient agreement in Yahoo overlap for {ticker}')
    earliest = live.close.index.min()
    earlier = hist.close.index[hist.close.index < earliest]
    cols = list(live.close.columns)
    if len(earlier) == 0:
        return live
    idx = earlier.append(live.close.index)
    def _prepend(column, live_frame):
        archived = getattr(hist, column)
        source = archived.reindex(index=earlier,columns=cols)
        return pd.concat([source,live_frame],axis=0).reindex(idx)
    return MarketData(_prepend('close', live.close),_prepend('volume',live.volume),
                      live.source+' + verified older Yahoo cache (survivor-selected)',
                      live.excluded,raw_close=(_prepend('raw_close',live.raw_close)
                      if live.raw_close is not None else None))
