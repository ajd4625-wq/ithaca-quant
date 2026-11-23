# v3.2.3 — Obtain REAL historical market data (not just validate an empty importer)

## What changed and what didn't

Previously, Ithaca had an archive importer but did **not** fetch a comprehensive historical dataset. This version contains a **working provider acquisition command** which, on a computer with network access and an authorized Sharadar subscription, downloads historical stock prices and historical metadata for active *and delisted* U.S. common stocks.

Data comes from the original provider, not from a current Yahoo ticker list. It retains Sharadar's unique `permaticker` security identifiers; `closeunadj` for observed trading prices; `closeadj` for split/dividend/spinoff-adjusted total returns; observed share volume; and daily security eligibility drawn from all historical bars. The SPY benchmark is obtained from the vendor's **FUNDS** table (not STOCKS). ACTIONS metadata are downloaded for reconciliation.

**No licensed data, account credentials, verified delisting settlements, or institutional-grade dataset were supplied to this session. Therefore a complete institutional-quality data archive cannot be bundled or claimed delivered.** We do not pretend that code checksums establish vendor authenticity or delisting payoff completeness. This source link is a tangible acquisition path, not a magic replacement for data rights.

## One-time data download (private; not GitHub)

Sharadar provides historical stocks since approximately December 1997, current and delisted issues, and corporate actions. See original documentation:

- https://sharadar.com/docs/stocks
- https://sharadar.com/docs/tickers
- https://sharadar.com/docs/actions
- https://sharadar.com/docs/funds

1. Get an appropriately licensed Sharadar subscription and API key. Confirm your license allows local research/derived outputs.
2. On your Mac/PC, open a terminal in the extracted Ithaca repository root, and create a Python environment with `requirements.txt` installed.
3. Store your vendor key in an **environment variable**, not in Python files or GitHub:

```bash
export SHARADAR_API_KEY="<your-authorized-key>"
python scripts/acquire_historical_data.py download \
  --private-dir ./private_vendor --start 2020-01-01 --end 2025-12-31
```

This retrieves full-history `tickers.csv.zip`, `stocks.csv.zip`, `actions.csv.zip` and date-scoped `funds_SPY.csv`. Stock ZIP downloads can be gigabytes and take time and free disk space. Never commit these records or the key to GitHub; `.gitignore` prevents incidental addition under `private_vendor/`.

4. Build a **dated historical market slice** from those actual records:

```bash
python scripts/acquire_historical_data.py build \
  --private-dir ./private_vendor \
  --start 2022-01-03 --end 2023-12-29 \
  --output ./private_vendor/ithaca_history_2022_2023.zip \
  --source-reference "Sharadar account export; include your extraction date and data entitlement ID"
```

A quality JSON report is written next to the ZIP. A licensed export may be large enough that you must use a narrower window with the *current* Streamlit archive/in-memory limits (uncompressed ZIP CSVs limited to 300 MB). **Never select a hand-picked list of only present-day surviving stocks** to solve that limit. Shrink the *date range*, not the stock universe.

5. Open the application's **Walk-forward tests** tab and upload the generated ZIP under **Point-in-time market archive**. The ZIP includes the historical price and security master records; it is private. The model then uses the archived universe for dated evaluation.

## What the downloader checks and refuses to guess

- Checks every domestic-common-stock TICKERS record whose first/last trading dates overlap the requested window. If ANY expected issue has no price history, the import fails instead of silently dropping that stock.
- Supports all three domestic common-stock class categories (primary and secondary), preserving distinct provider-issued permatickers.
- Refuses source ticker collisions, invalid dates, unmapped identities, missing SPY, missing total-return-adjusted or unadjusted closing prices, invalid volume, duplicated dates, and overlapping security identities.
- Preserves delisted securities' price histories. **A delisting is not automatically a 100% loss.** Neither the last trading price nor the action's name proves the cash/securities ultimately received. For historical horizons spanning a delisting, the strict backtest still needs authenticated terminal settlement records (`terminal_returns.csv`), such as from a properly licensed CRSP return dataset or verifiable cash merger terms. Without them, it fails closed.
- Records provider coverage and quality, but explicitly reports `institutional_grade_certified = false` and `terminal_payoffs_verified = 0` until valid external records are supplied.
- Checks ZIP content integrity without claiming external authenticity. Missing published vendor histories cannot be manufactured by software.

## Data gaps not solved by the download alone

- A full market archive may exceed Streamlit Cloud file uploads and its current in-memory wide-data pivot. It is not appropriate to upload gigabytes of licensed data to a public GitHub repository.
- Vendor coverage still needs independent reconciliation, event-specific settlement returns, original trading timestamps, historical delisted cash flows, and potentially historical exchange listing/suspension coverage.
- Historical fundamentals, original SEC amendments, analyst revisions, and institutional news archives must be sourced separately. Current filing snapshots are not a point-in-time substitute.
- A clean data archive does not prove model accuracy. The model tournament requires unobserved future outcomes for prospective comparison.

Official CRSP stock files document a deeper security-history and delisting-return source, usually licensed through authorized institutional access: https://www.crsp.org/research/crsp-us-stock-databases-2025-layout/ .
