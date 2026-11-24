# Ithaca Quant v3.2.4 — Private Historical Training Integration

Released 2026-11-21. This is a software integration release, **not** the delivery of a licensed institutional market dataset.

## Changes implemented

1. **Production training now supports historical archives.** `ithaca_quant/production_history.py` connects the existing validated archive format to the actual `forecast_asof` forecasting entry point in `app.py`. The private archive supplies *every historical training row*; live Yahoo provides only the new as-of stock features. Without a configured archive, the app explicitly warns about survivor-universe limitations.
2. **Scheduled forecasts use the same source selection.** `scripts/daily_forecast_job.py` can use private archives. If a private archive is configured and invalid, it refuses to substitute Yahoo history silently.
3. **Delisted-stock outcomes influence model training.** Archived documented terminal returns are applied to the historical training labels before model fitting. Missing matured outcomes for eligible historical securities cause a hard failure rather than invisible exclusion.
4. **Documented terminal settlement converter.** `ithaca_quant/terminal_settlement.py` and `scripts/attach_delisting_settlements.py` accept externally sourced event-level incremental settlement factors, validate permanent security IDs and date ranges, reject source/price conflicts, and produce horizon-specific terminal return records. A stock without a next-day executable price may have a missing entry return; no imaginary trade is created.
5. **Avoid double-counting inclusive delisting returns.** An event factor already reflected in adjusted prices or an inclusive CRSP CIZ daily return is explicitly rejected as an incremental settlement adjustment.
6. **Stricter archive provenance and identity handling.** Synthetic/demo manifests cannot be activated in real-production archive mode. Historical securities remain keyed by permanent IDs; current ticker mapping is only allowed with a dated valid identity record.
7. **Cross-sectional feature consistency.** Cross-sectional rank features are neutralized when historical training uses a broad provider universe while live forecasting uses a smaller Yahoo watchlist. Other price, trend, and liquidity features remain available.
8. **Horizon-specific archive protection.** Archives containing 20-session terminal outcomes cannot silently be used for a 5-session forecast; use `ITHACA_HISTORICAL_ARCHIVE_PATH_5` and `_20` when horizons need distinct settlement records.
9. **Readiness diagnostics.** `scripts/check_historical_training.py` reviews missing eligible matured labels before deployment and explicitly marks vendor authenticity as unverified.

## Usage

- First acquire a *licensed*, provider-supplied full historical securities master, historical prices and authoritative event settlement outcomes; never fabricate missing data.
- Build the private historical archive using `scripts/acquire_historical_data.py` from v3.2.3.
- If authoritative additional terminal outcome evidence exists, convert it with `scripts/attach_delisting_settlements.py` and keep a source reference for each event.
- Run `scripts/check_historical_training.py` on the final archive.
- Set a private server-side `ITHACA_HISTORICAL_ARCHIVE_PATH` (or `_5` / `_20`) and restart the app.
- See `HISTORICAL_PRODUCTION_GUIDE_v3.2.4.md` for exact syntax and caveats.

## Testing

- `303/303` tests passed across 4 completed independent pytest groups: 63, 78, 100, and 62 tests.
- Deployment preflight passed.
- New end-to-end synthetic test verified archived training, historical delisting settlement arithmetic, source selection and actual model forecasting.
- **NOT TESTED:** live licensed vendor download, full institutional market database, cloud filesystem mounts, historical provider authenticity, or live-market predictive superiority.
- Existing warning in the model zoo regarding feature-name metadata is unrelated to this upgrade.

## Not completed (requires authorized external access)

- **Actual authenticated institutional equity dataset:** absent. No CRSP or Sharadar provider credentials, archival tables, or redistribution rights were available here. The two GitHub packages intentionally contain code and tests, not licensed data.
- **Independent authentication of delisting settlement events:** absent. The new converter checks event-record structure and financial arithmetic, but a `source_reference` text value is not independent verification of the cash/stock consideration. Do not use the event factors without verifying their underlying records.
- Real-market predictive advantage remains unknown.
