# Point-in-time audit input specification

**No point-in-time complete universe was supplied.** This release does not claim that its historical full-market skill has been verified. The strict audit is an import-and-validation pathway for a reputable data supplier, not a data vendor.

## 1. Membership CSV: `--membership`

Required columns: `security_id,ticker,member_from,member_to,source_id`

- `security_id`: immutable ID; ticker re-use across different securities is explicitly rejected by this import (rename appropriately using independently sourced identity mapping if necessary).
- `ticker`: historical provider symbol matching the total-return price file, including securities **no longer trading**.
- `member_from`: inclusive ISO date on which the stock first qualified under the **predeclared** universe rule.
- `member_to`: exclusive ISO date on which qualification ended; blank if still active.
- `source_id`: traceable historical membership source ID (not invented).
- Every historical member on a tested decision date must appear in the price panel or the audit aborts. Surviving-only lists fail if proper membership is provided. Never derive eligibility from future-known performance or current index constituents.

## 2. Price CSV: `--prices`

Required columns: `date,ticker,total_return_index,volume`.

- Daily chronological market data must include `SPY` as a total-return benchmark, plus **every historical member**, including securities that later delisted. Use an appropriate total-return index or corporate-action-adjusted and delisting-settled return path.
- **A generic adjusted-close price feed is NOT sufficient to demonstrate complete delisting treatment.** The `total_return_index` field must genuinely incorporate delisting/settlement returns, not be a relabeled today's stock-price series.
- A five-day forward return across a delisting must have valid liquidation/settlement methodology; if no trustworthy terminal price or cash-settlement value is available, do not assign zero or drop the security. The audit rejects missing future labels. Missing holidays are okay only if benchmark and securities share actual completed sessions; suspended trading requires a documented policy.
- The historical audit assumes idealized signal-close-to-close returns, fixed transaction cost estimates and partial cash exposure. It does not simulate after-hours execution, opening auctions or full real broker fills.

## 3. Provenance JSON: `--provenance`

The file must identify its genuine source. Minimal shape:

```json
{
  "provider": "YOUR_ACTUAL_DATA_PROVIDER",
  "dataset_description": "Actual coverage, period, adjustments, delisting-return treatment and audit notes",
  "membership_history_includes_delisted": true,
  "total_return_history_includes_delisting_returns": true,
  "historical_symbols_preserved": true
}
```

**These booleans are claims made by the data supplier/user, not something software can independently prove from a CSV.** Source audits and reconciliations must establish their truth; do not set `true` just to bypass the input guard. A reliable historical-security database (for example a properly licensed complete research feed) is necessary for credible results.

## 4. Evaluation protocol

The audit operates at **fixed historical times**, uses matured training labels and a purged holdout for each fitted model, and grades later returns without allowing the model to access them while fitting. Tests use nonoverlapping 20-trading-day strategy windows with a five-session target, up to six names and a position cap. Forecasts failing the predeclared validation gate remain abstentions. Exports contain raw forecast/outcome rows, window-level returns, model coverage, and hashes for the original inputs.

Cautions: conditioning on the availability of a ticker’s history can introduce listing-age selection effects; corporate-action corrections can alter returns; data vendor revisions can still cause lookahead. Even a PIT constituent universe is not sufficient if the associated price/return panel omits dead stocks. A full unbiased backtest cannot be guaranteed by file names, flags, a working importer, or unit tests alone.
