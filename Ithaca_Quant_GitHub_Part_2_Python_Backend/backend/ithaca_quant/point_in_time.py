"""Strict historical-universe evidence checks; never reconstruct the past from today's listings.

Accepts *dated historical snapshots*, not a present-day survivor list. Membership
and actual delisted stock total-return histories must be supplied by the user.
The checker refuses to certify data with missing eligible tickers, even when
that reduces apparent strategy performance.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

REQUIRED = {'date','ticker','eligible','provenance'}
PROVENANCE = 'historical_archive'


def validate_membership(membership: pd.DataFrame, *, signal_dates,
                        panel: pd.DataFrame, close: pd.DataFrame,
                        horizon: int, terminal_returns: pd.DataFrame | None = None) -> dict[pd.Timestamp, set[str]]:
    """Require each signal date to have a complete historical archived snapshot.

    Dates denote constituent eligibility on the historical signal day, not
    information newly obtained in the present. 'historical_archive' is a
    provenance declaration; it is NOT independently authenticated by code.
    """
    if membership is None or not REQUIRED.issubset(membership.columns):
        raise ValueError('Point-in-time validation requires date,ticker,eligible,provenance columns')
    if horizon <= 0:
        raise ValueError('Horizon must be positive')
    info = membership.copy()
    info['date'] = pd.to_datetime(info.date, errors='coerce').dt.normalize()
    info['ticker'] = info.ticker.astype(str).str.strip().str.upper()
    if info.date.isna().any() or info.ticker.eq('').any() or info.duplicated(['date','ticker']).any():
        raise ValueError('Missing/duplicate dated historical membership')
    if not info.provenance.eq(PROVENANCE).all():
        raise ValueError('Current-listing or unknown membership provenance is not historical')
    if not info.eligible.isin([True,False,0,1]).all():
        raise ValueError('Historical membership eligible must be Boolean')
    market_dates = pd.DatetimeIndex(close.index)
    allowed = {}
    for dt in pd.to_datetime(signal_dates):
        group = info.loc[info.date == pd.Timestamp(dt).normalize()]
        if group.empty:
            raise ValueError(f'Missing historical membership snapshot for {pd.Timestamp(dt).date()}')
        active = set(group.loc[group.eligible.astype(bool), 'ticker']) - {'SPY'}
        if not active:
            raise ValueError(f'No eligible historical constituents for {pd.Timestamp(dt).date()}')
        # Strict: candidate data and all H-session future returns required, or
        # delisted names are silently excluded and survivor bias persists.
        mask = panel.date == pd.Timestamp(dt)
        observed = panel.loc[mask].set_index('ticker')
        missing = active - set(observed.index)
        if missing:
            raise ValueError(f'Historical eligible tickers missing from panel ({pd.Timestamp(dt).date()}): {sorted(missing)[:10]}')
        needed = ['forward_return','benchmark_forward','close','target']
        if not set(needed).issubset(observed.columns):
            raise ValueError('Panel lacks historical total-return outcomes')
        values = observed.loc[sorted(active), needed].apply(pd.to_numeric, errors='coerce')
        if not np.isfinite(values['close']).all():
            raise ValueError('Missing decision-time closing prices for archived constituents')
        missing_outcome = set(values.index[~np.isfinite(values[['forward_return','benchmark_forward','target']].to_numpy(float)).all(axis=1)])
        if missing_outcome:
            # A delisted security must have a documented TOTAL return through the
            # horizon. Merely retaining the last quoted price is unacceptable.
            if terminal_returns is None:
                raise ValueError(f'Missing prices/outcomes for historical constituents on {pd.Timestamp(dt).date()}; provide delisted adjusted returns')
            terminal = terminal_returns.copy()
            required = {'signal_date','ticker','asof_total_return','entry_total_return','source'}
            if not required.issubset(terminal):
                raise ValueError('Terminal return archive requires signal_date,ticker,asof_total_return,entry_total_return,source')
            terminal['signal_date'] = pd.to_datetime(terminal.signal_date).dt.normalize()
            relevant = terminal.loc[terminal.signal_date.eq(pd.Timestamp(dt)) &
                                    terminal.ticker.isin(missing_outcome)]
            if relevant.duplicated(['signal_date','ticker']).any():
                raise ValueError('Duplicate archived terminal payoffs')
            covered = set(relevant.ticker)
            if (covered != missing_outcome or not relevant.source.eq('historical_archive').all() or
                  not np.isfinite(relevant[['asof_total_return','entry_total_return']].to_numpy(float)).all() or
                  (relevant[['asof_total_return','entry_total_return']].to_numpy(float) < -1).any()):
                raise ValueError('Missing or unverified terminal total-return resolution for delisted constituents')
        if pd.Timestamp(dt) not in market_dates:
            raise ValueError('Benchmark lacks historical signal date')
        position = int(market_dates.get_loc(pd.Timestamp(dt)))
        if position + horizon >= len(market_dates):
            raise ValueError('Historical signal lacks its complete forward horizon')
        end_date = market_dates[position + horizon]
        # Prefer the actual observable price series over precomputed panel
        # labels, which can become stale after a vendor quote disappears.
        no_terminal = {ticker for ticker in active if ticker not in close.columns or
             not np.isfinite(pd.to_numeric(close.at[end_date,ticker],errors='coerce')) or
             pd.to_numeric(close.at[end_date,ticker],errors='coerce') <= 0}
        if no_terminal:
            if terminal_returns is None:
                raise ValueError('Missing historical end closes / delisted total returns')
            terminal = terminal_returns.copy()
            terminal['signal_date'] = pd.to_datetime(terminal.signal_date).dt.normalize()
            matching = terminal.loc[terminal.signal_date.eq(pd.Timestamp(dt)) &
                                    terminal.ticker.isin(no_terminal)]
            if set(matching.ticker) != no_terminal or not matching.source.eq('historical_archive').all():
                raise ValueError('Historical delisting payoffs absent or unauthenticated')
        allowed[pd.Timestamp(dt)] = active
    return allowed
