"""Safely train live stock rankings on a private point-in-time archive.

An archive is NOT necessarily institutionally authenticated.  This module
prevents a configured historical archive from silently becoming a present-day
survivor-only Yahoo training sample, and blocks unresolved historical outcomes.
No vendor secrets or licensed datasets are bundled in the application.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

import numpy as np
import pandas as pd

from .features import build_panel
from .historical_archive import HistoricalBundle, load_historical_archive
from .backtest import _hydrate_terminal_labels

ARCHIVE_ENV = 'ITHACA_HISTORICAL_ARCHIVE_PATH'
MAX_TRAINING_BARS = 2_500_000  # In-memory Streamlit safety, never a silent sample.


@dataclass
class ProductionHistory:
    panel: pd.DataFrame
    diagnostics: dict


def configured_archive_path(*, environment=None, horizon: int | None = None) -> Path | None:
    environment = os.environ if environment is None else environment
    special = str(environment.get(f'{ARCHIVE_ENV}_{horizon}', '') or '').strip() if horizon is not None else ''
    name = special or str(environment.get(ARCHIVE_ENV, '') or '').strip()
    return Path(name).expanduser() if name else None


def load_private_production_archive(path: str | Path, *, allow_test_data: bool = False) -> HistoricalBundle:
    """Load from a server-private mount, never from a public GitHub path.

    An explicitly configured missing/invalid archive raises, instead of
    quietly reverting to Yahoo history and falsely displaying verified mode.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError('Configured private historical archive does not exist. Check server-private mount.')
    if path.suffix.lower() != '.zip':
        raise ValueError('Private historical archive must be the Ithaca historical ZIP.')
    loaded = load_historical_archive(path)
    provider = str(loaded.quality.get('provider_declared', '')).upper()
    if not allow_test_data and ('SYNTHETIC' in provider or 'TEST_ONLY' in provider or 'DEMO' in provider):
        raise ValueError('Synthetic/demo market archives cannot be used as real-production history')
    return loaded


def _normalize_live_panel(live_panel: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    if not {'date', 'ticker', 'label_end', 'target', 'forward_return'}.issubset(live_panel):
        raise ValueError('Live panel is missing required fields')
    latest = live_panel.loc[pd.to_datetime(live_panel.date).eq(asof)].copy()
    if latest.empty or latest.ticker.duplicated().any():
        raise ValueError('Latest live observation must have unique stock tickers')
    # The as-of observation cannot possess an observed future outcome.
    latest['target'] = np.nan
    latest['forward_return'] = np.nan
    latest['benchmark_forward'] = np.nan
    return latest


def _stable_current_tickers(bundle: HistoricalBundle, asof: pd.Timestamp,
                            live_tickers: set[str]) -> dict[str, str]:
    """Only map IDs to a live ticker if the crosswalk actually covers asof.

    Do not infer that a security active at the *end of an old export* still
    owns the same ticker today. Never recycle an old delisted ticker.
    """
    master = bundle.security_master
    active = master.loc[
        (master.valid_from <= asof) &
        (master.valid_to.isna() | (master.valid_to >= asof))
    ].copy()
    active = active.loc[active.ticker.isin(live_tickers)]
    if active.ticker.duplicated().any() or active.security_id.duplicated().any():
        raise ValueError('Ambiguous current security-id to live-ticker crosswalk')
    return dict(zip(active.security_id, active.ticker))


def production_panel_from_archive(live_panel: pd.DataFrame, *,
                                  archive: HistoricalBundle, horizon: int,
                                  asof: pd.Timestamp | str | None = None,
                                  require_complete_outcomes: bool = True,
                                  max_training_bars: int = MAX_TRAINING_BARS) -> ProductionHistory:
    """Historical archive supplies *all* training rows; Yahoo only supplies today.

    Terminal returns are incorporated into training labels before filtering.
    Missing resolvable outcomes (especially delistings) fail closed when
    strict mode is requested. This intentionally may prevent live deployment
    until a legitimately complete data subscription is configured.
    """
    if horizon < 1:
        raise ValueError('Horizon must be positive')
    asof = pd.Timestamp(asof if asof is not None else live_panel.date.max()).normalize()
    current = _normalize_live_panel(live_panel, asof)
    archived_horizon = archive.quality.get('terminal_horizon_sessions')
    if archived_horizon is not None and archive.terminal_returns is not None and int(archived_horizon) != horizon:
        raise ValueError(f'Private terminal-return labels were built for {archived_horizon} sessions, not requested {horizon}. Use a horizon-specific archive.')
    md = archive.market
    if 'SPY' not in md.close or len(md.close.index) < horizon + 100:
        raise ValueError('Private historical archive lacks enough SPY sessions')
    if md.close.size > max_training_bars:
        raise ValueError('Private archive exceeds in-memory training capacity; configure a smaller DATE WINDOW, not a surviving-stock subset')

    # Price features for an ID are calculated entirely from its historical
    # point-in-time series. Current Yahoo features are calculated separately.
    historical = build_panel(md.close, md.volume, horizon=horizon,
                             fundamentals=archive.fundamentals or None,
                             raw_close=md.raw_close)
    historical = _hydrate_terminal_labels(historical, archive.terminal_returns, md.close)
    dates = pd.DatetimeIndex(md.close['SPY'].dropna().index).sort_values()
    archive_cutoff = pd.Timestamp(dates[-horizon - 1]).normalize()
    eligible = archive.membership.loc[archive.membership.eligible]
    candidate = historical.loc[
        (historical.date <= archive_cutoff) & (historical.date < asof)
    ].copy()
    # Every eligible row for which the full benchmark window has matured is
    # required to have a resolved future outcome. An unrecorded delisting or
    # trading halt is not an eligible reason to erase a loss from training.
    joins = candidate[['date', 'ticker']].merge(
        eligible[['date', 'ticker']], on=['date','ticker'], how='inner', validate='one_to_one')
    candidate = candidate.merge(joins.assign(_eligible=True), on=['date','ticker'],
                                how='left', validate='one_to_one')
    missing = candidate.loc[candidate._eligible.fillna(False) &
                            (~np.isfinite(pd.to_numeric(candidate.target, errors='coerce')))]
    if require_complete_outcomes and not missing.empty:
        examples = ', '.join(f'{r.ticker}@{pd.Timestamp(r.date).date()}' for r in missing.head(4).itertuples())
        raise ValueError(f'Historical training blocked: {len(missing)} eligible matured stock outcomes have no verified return (including possible delistings). Resolve terminal_returns.csv; examples: {examples}')
    # All history remains visible to per-security validation, but no user-
    # chosen contemporary survivor stock histories are added to the train set.
    historical = historical.loc[historical.date < asof].copy()
    historical.loc[pd.to_datetime(historical.label_end) >= asof,
                   ['target', 'forward_return', 'benchmark_forward']] = np.nan
    # Archived cross-sectional ranks span the full provider universe, while
    # today's Yahoo watchlist could contain only five names. Mixing those rank
    # distributions would make an archived feature behave differently at live
    # prediction time. Neutralize only those ranks; keep individual price,
    # 52-week, liquidity and market-regime features intact.
    cross_rank_columns = [name for name in historical if name.startswith('cs_rank_')]
    for col in cross_rank_columns:
        historical[col] = 0.5
        if col in current:
            current[col] = 0.5
    matched = _stable_current_tickers(archive, asof, set(current.ticker.astype(str)))
    historical['ticker'] = historical.ticker.map(lambda sid: matched.get(sid, f'PIT_{sid}'))
    if historical.duplicated(['date','ticker']).any():
        raise ValueError('A permanent ID crosswalk produced overlapping historical ticker rows')
    # The current observation is kept with its real Yahoo ticker; historical
    # data retains permanent security IDs for all former/recycled tickers.
    combined = pd.concat([historical.drop(columns=['_eligible'], errors='ignore'), current],
                         ignore_index=True, sort=False)
    if combined.duplicated(['date','ticker']).any():
        raise ValueError('Duplicate as-of stock observation across private and live data')
    evidence = {
        'historical_source': archive.quality['provider_declared'],
        'historical_sha256': archive.archive_sha256,
        'historical_integrity_verified': bool(archive.quality['integrity_sha256_verified']),
        'independently_authenticated': False,
        'provider_universe_certified': False,
        'terminal_return_records': int(len(archive.terminal_returns)) if archive.terminal_returns is not None else 0,
        'historical_label_rows': int(pd.to_numeric(historical.target, errors='coerce').notna().sum()),
        'eligible_missing_outcomes': int(len(missing)),
        'live_asof_rows': int(len(current)),
        'permanent_ids_mapped_to_live': int(len(matched)),
        'archive_first_date': str(dates.min().date()),
        'archive_last_date': str(dates.max().date()),
        'current_asof_date': str(asof.date()),
        'cross_sectional_features_neutralized': cross_rank_columns,
        'production_training_mode': 'ARCHIVE_HISTORY_ONLY; YAHOO_ASOF_FEATURES_ONLY',
        'warning': ('Vendor authenticity and complete delisting recovery remain independently unverified. '
                    'A correct archive still needs licensed source documents.'),
    }
    return ProductionHistory(combined, evidence)
