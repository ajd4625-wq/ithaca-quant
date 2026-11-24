# Ithaca Quant v3.2.2 — verified source-code repairs

## Changes
1. **Market return prices:** `download_market_data` now fetches the Yahoo `Adj Close` field for dividend-adjusted return calculations and retains vendor `Close` separately for trading-price, minimum-price and dollar-volume research. It requests `auto_adjust=False` so these separate fields can be captured. If `Adj Close` is absent, the ticker uses a price-only fallback, which is explicitly disclosed in the `MarketData.source` text. No fictitious adjusted return is created.
2. **End-to-end price-field preservation:** The raw close is now preserved across SQLite market caching, completed-session cutoff, incremental data refresh, full price-series reconciliation, single-stock/portfolio forecast panels, and the universe screener. A legacy Yahoo snapshot lacking trading-price history must be fully replaced or returned **stale** with a warning; new and old price schemas are not silently joined.
3. **Stock screening:** Stocks with an absent most-recent quote are not promoted into the current scan via two-session forward fill. Missing last-session volume or insufficient recent quoted-volume coverage also fails the screen. Liquidity and price thresholds use vendor trading close if available.
4. **Portfolio optimizer:** Rejects negative, nonfinite, nonnumeric, or leveraged holding weights before any zero-weight filtering. Refuses duplicate/missing dates and weekly/monthly price histories that would create misleading annualized risk metrics.
5. **Weekly report regression:** The old test assumed the calendar date of test execution; it now fixes the resolution time within the requested report week. Report code is unchanged because the earlier behavior correctly filters by the resolution week.
6. **Continuous checks:** New GitHub Actions CI runs the preflight and regression tests on code pushes/PRs, with no account secrets embedded.

## How to use
Extract both GitHub ZIP parts into a single repository root; the Streamlit entry point remains `streamlit_app.py`. Price caches may require an additional full Yahoo history refresh. The three-model tournament still defaults on and is mutually exclusive with the optional enhanced lab.

## Limitations
- Real Yahoo Finance calls, Streamlit Cloud deployment, and live prediction accuracy **have not been verified by offline tests**.
- Yahoo vendor `Close` can be retrospectively split-adjusted; this cannot be described as a certified point-in-time original trade tape. Corporate-action and delisting archives still require authenticated provider records.
- The source accepts missing `Adj Close` with a prominently disclosed price-only fallback for compatibility, so that ticker's historical return quality is lower.
- Trading simulation remains hypothetical, and none of the models has a verified live-market advantage over the incumbent.
