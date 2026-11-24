# Ithaca Quant v3.2.5 — Free-first historical research data

This release **uses Yahoo Finance and official SEC EDGAR data without a paid institutional subscription**. It does NOT recover an exhaustive historical U.S. equity universe. It intentionally marks every current-watchlist export as **survivorship-biased / NOT a point-in-time membership archive**.

## What is enabled

- Existing ranking and scheduled forecasts continue to fetch Yahoo historical adjusted close, vendor `Close` (not guaranteed an original trade tape), and observed volume. No synthetic prices, volume, or zero-return delisting assumptions are inserted.
- When `SEC_CONTACT_EMAIL` is configured, the ranking view and scheduled forecast job additionally try to use **dated** SEC XBRL quarterly vintage features for up to the first 12 watchlist stocks. On unavailable SEC records, those stocks remain price-only and the app displays limited coverage. SEC facts are used from the *next business day* after the disclosed filing date, never the quarter-end date.
- A new **free archive builder** downloads deeper Yahoo watchlist histories and optional SEC vintage data, then records a source inventory, missing symbols, original and adjusted closes, observed volume, and SHA-256 file hashes.
- Optional **private cached-history extension** preserves genuinely observed older Yahoo bars when they overlap consistently with live Yahoo data; never forward-fills a missing latest quote.

## Quick start: prices only (no credentials)

From your locally extracted repository:

```bash
python -m pip install -r requirements.txt
python scripts/acquire_free_history.py --tickers AAPL,MSFT,GOOGL,NVDA,AMZN --years 12 --out .ithaca_free_history
```

This is a request to Yahoo through the unofficial `yfinance` library. Symbols that fail are listed in `manifest.json`; providers can rate-limit or block it. The downloader attempts only currently known tickers supplied by you, **not a historical all-stock archive**.

## Add SEC official historical filings (free; genuine contact required)

Set `SEC_CONTACT_EMAIL` as an environment variable to a legitimate email address, for example using your shell's private secret/environment management. Do not commit it to GitHub. Then run:

```bash
python scripts/acquire_free_history.py --tickers AAPL,MSFT,GOOGL,NVDA,AMZN --years 12 --with-sec --out .ithaca_free_history
```

SEC supports documented rate-limited REST `companyfacts` and issuer directory access. Companyfacts JSON is a current retrieval containing data reported at different **filed** dates: the vintage builder reconstructs values that could have been known on each reporting date, conservatively effective the next business day. The current ticker-to-CIK directory is **not** a historical company identity map, and older SEC tags may be absent.

## Use the cached free history with the application

For local or other persistent hosts only, set:

```text
ITHACA_FREE_HISTORY_DIR=/absolute/path/to/.ithaca_free_history
```

Run `streamlit run streamlit_app.py`. The historical research panel will use archived **earlier** observed bars where they overlap with latest Yahoo bars, and optional SEC vintage files for the tickers present. If the data's price adjustment changed in incompatible ways, you get a clear error telling you to rebuild the archive. The latest live bars always come from the live quote retrieval, not an old cache.

**Streamlit Cloud caveat:** it may erase local files on redeploy/restart. Never commit downloaded Yahoo or any licensed provider records to a public GitHub repository. Use ephemeral downloads or a correctly permissioned persistent private storage mount; the `.gitignore` excludes `.ithaca_free_history/`. If that storage is unavailable, leave `ITHACA_FREE_HISTORY_DIR` unset and use the existing Yahoo live history and optional direct SEC features; the app works without the bundle.

`ITHACA_HISTORICAL_ARCHIVE_PATH` still refers to the separate, strict institutional point-in-time archive contract. **Do not point it at the free-history directory.** The free bundle neither forges permanent issuer IDs nor makes a fake membership.csv or fake delisting payouts.

## Still incomplete / not to be claimed

- Delisted securities and terminal bankruptcy/merger distributions are not systematically covered by free Yahoo history.
- Current ticker lists, including today's exchange listings, cannot be retroactively certified as historical memberships.
- Retrospectively adjusted Yahoo prices may change after splits and dividends and are not verified as originally available on each date.
- No claim of unbiased all-stock backtesting, institutional-quality data, or verified predictive advantage is made. Those require independent records and prospective evidence.
- Code and mocks were tested offline. Live Yahoo/SEC provider access was not authenticated in this environment.

## Official references

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC fair access: https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- yfinance library: https://github.com/ranaroussi/yfinance
