# v3.2.4 — Finish historical-data production integration

## What is now implemented

Ithaca v3.2.4 can use historical data **for live model training**, not only walk-forward tests. The real-time as-of observation comes from the currently observed Yahoo stock bars; all historical **training** examples come from the private archive. Permanent security IDs keep delisted/reused-ticker securities distinct. The scheduled forecast job uses the same source-selection rule. If the configured archive cannot be read or has unresolved eligible historical outcomes, forecasting stops rather than silently falling back to surviving stocks.

**Not delivered:** Complete authenticated licensed U.S. daily equity records and authenticated delisting settlements. Neither the files nor an entitlement were available in the build environment. The published GitHub code has no vendor history. No code can certify provenance from a user-entered provider name or source-reference string. For additional sources, see `HISTORICAL_DATA_SOURCE_v3.2.3.md`.

## 1. Acquire records privately (a subscription is required)

Using an authorized Sharadar account, run in the cloned repository on a machine with network access:

```bash
export SHARADAR_API_KEY='YOUR_AUTHORIZED_KEY'
python scripts/acquire_historical_data.py download --private-dir ./private_vendor --start 2020-01-01 --end 2026-11-20
python scripts/acquire_historical_data.py build --private-dir ./private_vendor --start 2023-01-03 --end 2026-11-20 --output ./private_vendor/history_2023_2026.zip --source-reference 'Vendor export identifier and date'
```

These commands use the authorized provider. They have **not** been executed against a live vendor account here. The archive builder can require shorter date windows to fit the Streamlit in-memory limit; do not make the dataset look complete by dropping delisted securities. Licensed data must stay in a private location, **never GitHub**.

## 2. Document and reconcile terminal settlements

To avoid falsely erasing delisting losses, import source-documented **incremental** settlement factors. The input event CSV must include:

```
security_id,last_trading_date,event_date,settlement_factor,return_basis,source_reference,source_record_id
```

`settlement_factor` is the explicitly documented total-value ratio from **the last observed adjusted price to the final settled proceeds**, **excluding** any delisting payment already reflected in the adjusted price. It can be 0 only when a reliable source establishes a zero recovery. `return_basis` must be exactly:

```
incremental_to_last_adjusted_close_excluding_prior_delist_return
```

Example invocation, after obtaining *real* records from authorized sources:

```bash
python scripts/attach_delisting_settlements.py --archive ./private_vendor/history_2023_2026.zip --events ./private_vendor/settlements.csv --horizon 20 --output ./private_vendor/history_20_session_settlements.zip
```

**Never apply this to CRSP CIZ daily returns if the delisting return is already included**, because that would double-count the event. Reconcile event definitions, payment forms, dividends, split factors and your license before using this conversion. The program checks dates, permanent IDs, arithmetic, conflicts and source references; it **cannot independently authenticate** the reference or obtain a missing corporate-action payoff. It does not invent losses or merger consideration. A given archive is constructed for a specified horizon when settlement labels are attached; use a separate properly constructed archive for 5-session and 20-session predictions when the outcomes differ.

## 3. Validate before enabling production

```bash
python scripts/check_historical_training.py --archive ./private_vendor/history_20_session_settlements.zip --horizons 20
```

The report lists resolved and unresolved historical training labels. It will not call the dataset institutionally certified. Even a zero unresolved count only establishes *internal consistency within the exported records*, not completeness of the entire historical universe.

## 4. Configure production securely

Set `ITHACA_HISTORICAL_ARCHIVE_PATH` (or the horizon-specific `ITHACA_HISTORICAL_ARCHIVE_PATH_5` / `ITHACA_HISTORICAL_ARCHIVE_PATH_20`) to the **absolute path** of the private archive **on the same machine that actually runs the Streamlit server**:

```bash
export ITHACA_HISTORICAL_ARCHIVE_PATH='/absolute/private/path/history_20_session_settlements.zip'
streamlit run streamlit_app.py
```

The file is never stored in GitHub. GitHub Actions and Streamlit Community Cloud generally do **not** share your personal computer's files or mounted volumes: simply adding a path to a Streamlit secret does not upload the dataset. Use a private persistent server/disk or a controlled licensed-data delivery mechanism with suitable redistribution rights.

If no private path is configured, Ithaca displays a warning that its Yahoo-only training is **not** a survivor-bias-free institutional dataset. If a path is configured but missing, corrupt, synthetically generated or contains unresolved eligible historical labels, production forecasting will stop rather than claim archived accuracy.

## 5. What the production training mode does

- Builds historical technical and point-in-time SEC features from archived securities.
- Applies supplied documented terminal returns to training labels **before** model fitting.
- Rejects incomplete matured labels for documented eligible historical members, including delistings.
- Maps a permanent historical ID to a present ticker only when its dated crosswalk covers the current signal day. Stale ticker associations are not guessed.
- Uses current live prices and features for the new prediction, **not** current Yahoo stocks' past returns as training labels.
- Neutralizes cross-sectional rank features that would otherwise have inconsistent coverage between an institution-sized past universe and today's smaller watchlist.
- Keeps the original model competition, with the same source selection used for scheduled prediction logging.

## Known limitations

- **The dataset is not supplied:** access to Sharadar/CRSP or licensed exports is still required. It is not legitimate to invent that history.
- Vendor securities master completeness, corporate action fidelity and reference authentication must be independently reconciled.
- Real private archives above the app's current 300 MB extracted-size limit or 2.5 million-price-cell in-memory ceiling require a larger data-engine architecture; no silent truncation occurs.
- The current `terminal_returns.csv` schema identifies signal-date outcomes for a **specific horizon**; identical archives should not be assumed valid for every horizon.
- A historically active ticker in a stale archive cannot necessarily be mapped to the same company today. Those stocks remain independent archival IDs and cannot qualify for per-stock tournaments without an up-to-date identity crosswalk.
- Archive-backed training cannot by itself prove superior real-market accuracy, full universe coverage or live execution profits.

## Provider references

- https://sharadar.com/docs/stocks
- https://sharadar.com/docs/tickers
- https://sharadar.com/docs/actions
- https://www.crsp.org/research/crsp-us-stock-databases-2025-layout/
