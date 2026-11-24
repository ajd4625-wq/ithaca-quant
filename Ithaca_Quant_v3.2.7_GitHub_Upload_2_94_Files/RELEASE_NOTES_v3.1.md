# Ithaca Quant v3.1.0 — Historical Data Integrity

This update targets **correct historical training inputs and more defensible walk-forward research**, rather than claiming a new prediction-accuracy percentage.

## Implemented changes

1. **Permanent issuer/security identification.** A historical archive distinguishes a stable security ID from a mutable stock ticker, catches simultaneous conflicting ticker mappings, and validates trading dates against identity intervals.
2. **PIT archive import and secure manifest integrity.** A ZIP now carries provider metadata and mandatory SHA-256 digests for CSV data. Imports reject modified files, duplicate bars, invalid prices/volumes, impossible dates, unmapped securities, incomplete source fields, and inconsistent historical membership. **Checksums do not authenticate a source.**
3. **True historical backtest dataset path.** The Walk-forward Tests tab accepts an entire archive and builds its *own* prices, volumes, security-universe snapshots, and model features. It does not mix in current Yahoo survivors. Missing dated snapshots or terminal payouts fail closed.
4. **Original versus adjusted prices.** Archive requires both `raw_close` and `adjusted_close`. Investment eligibility and dollar liquidity use contemporaneous prices; historical return features use adjusted prices. Missing volumes remain unavailable, not zero.
5. **SEC fundamentals without late restatement leakage.** Historical features are recomputed at each original filing vintage. An amendment filed later does not revise the model's input for earlier dates. Both one-stock research and portfolio forecast paths now use event-vintage features, not the current latest/restated table.
6. **Historical delisted-stock learning labels.** Sourced terminal payouts now fill the corresponding training label (when the full horizon would have matured) as well as the simulated end-of-horizon return. This prevents a known delisting loss from being omitted from the model's historical learning data. Conflicts with actual complete-price observations fail.
7. **Data-health metrics.** Reports source-declared coverage dates, stable security IDs, membership snapshots, documented terminal payoffs, internal gaps, missing trading volume, and extreme daily return outliers.
8. **Practical packaging and auditing commands.** `scripts/build_historical_archive.py` and `scripts/audit_historical_archive.py`; see `HISTORICAL_DATA_GUIDE_v3.1.md`.

## What was NOT possible to supply automatically

- A complete authenticated U.S. universe including delisted stocks; this needs primary-source or licensed vendor historical exports.
- Independently verified corporate-action/delisting records and original price vintages across the entire market.
- Verified forward-market predictive superiority. The audit and regression tests do not establish a trading edge.

The Yahoo market mode stays explicitly **research-grade and survivor-biased** for long historical strategy testing. Only an appropriate imported archive can address the missing historical coverage, and even then completeness is externally dependent.
