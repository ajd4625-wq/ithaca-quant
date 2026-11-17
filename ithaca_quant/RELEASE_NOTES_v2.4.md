# Ithaca Quant v2.4.0 — My Portfolio: Persistent Holdings, Cost Basis, News, Forecasts

**Release date:** November 16, 2026. The saved-portfolio feature set from the previously packaged v2.3 release is now consistently labeled v2.4.0. It is built on v2.2.0 and does not change its trained forecasting mathematics or marketwide scanning pipeline.

## 1. A new, independent My Portfolio workspace

The Workspace radio now has **💼 My portfolio** in addition to Instant stock explorer and Full-market dashboard. My Portfolio does not fetch an exchange directory, run a universal scan, or require a previous full-market scan. It requests only the holdings' quotes, their news, and (on demand) each selected stock's own historical market data plus SPY for forecasting. A button opens the existing stock explorer for any held ticker. The old workspaces and chart ranges remain available.

## 2. Record actual trade fills, shares, and prices

In **Add a purchase or record a sale**, enter:

- Ticker symbol (e.g. `RKLB`)
- `BUY` or `SELL`
- Exact number of shares, including fractional shares if the competition platform supports them
- Actual purchase or sale **fill price per share** (not the current price or model target)
- Trade date
- Optional trading fees

A single ticker can have multiple buys at different prices and partial sales. Inputs reject invalid tickers, negative/zero amounts, future-dated trades, non-finite prices, and sales exceeding previously recorded shares at the sale date. Deleting a buy is blocked if it would make a later sale impossible. Entries do **not** place orders in StockTrak.

## 3. Cost-basis, P/L and account accounting

The app calculates weighted-average cost per remaining share, invested cost basis, estimated current market value, unrealized dollar gain/loss and percentage return, realized gains/losses on sales (including fees), and remaining virtual cash starting from the $1,000,000 competition balance. If *all* positions have usable quotes, it computes total estimated portfolio equity and total P/L. Otherwise it marks aggregate equity **Unavailable**, rather than valuing missing quotes at $0. Fees on buys enter cost basis; fees on sales reduce realized proceeds.

All dollar amounts are formatted with thousands separators (commas). The app flags negative cash and possible position concentration. Cash/account equity will be accurate only if the manually entered trades represent the complete transaction history. Corporate actions, dividends, taxes, and externally paid fees may need additional manual adjustment; a quote can be delayed or stale.

## 4. Portfolio privacy and storage that survives closing the tab

Create a portfolio to generate a random **35-character `IQ-...` recovery code**. The database stores its SHA-256 digest, *not* the raw code. Only someone with the code can open and alter that portfolio using this app. The code is **not in the URL**, and is held only in Streamlit session state while the page is open. Save it privately; users must paste it again when opening the portfolio from a new session or device. Losing the recovery code means losing access to the original saved portfolio (unless the user has a trade CSV backup and starts a new portfolio). This access-code mechanism is **not equivalent to independently verified user accounts or multi-factor authentication**.

The app uses the existing `ITHACA_DATABASE_URL` configuration if present, via SQLAlchemy with PostgreSQL. It creates three independent tables: `iq_private_portfolios`, `iq_private_trades`, and `iq_private_forecasts`. The DB URL must be in **Streamlit Secrets** or a private environment variable, never GitHub. Use a PostgreSQL URI supported by `psycopg`:

```toml
# Streamlit Community Cloud -> Manage app -> Settings -> Secrets
# EXAMPLE FORMAT ONLY — replace placeholders; do NOT publish credentials.
ITHACA_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require"
```

Without a configured URL, records use local `.ithaca_quant_cache/private_portfolios.sqlite3` and will usually survive a browser-tab close on the same running server. **Streamlit Community Cloud may erase local files when an app sleeps, restarts, or is redeployed**, so PostgreSQL is necessary for dependable hosted persistence. The app displays a warning in that case. Holding records are not part of GitHub source control.

## 5. On-demand fresh prices and gains

Quotes are requested only for the current portfolio's held tickers using the existing best-effort Yahoo intraday source (potentially delayed, stale or rate limited). The view updates approximately **every two minutes while its browser tab remains active** when auto-refresh is checked. A manual **Refresh prices** button is available. The app shows quote timestamps/staleness, and it does not invent missing prices. Transactions themselves remain unchanged when quotes refresh.

## 6. Saved company-by-company ML forecasts

Choose a held company and a 5-, 20-, or 60-trading-session forecast horizon. Press **Update selected forecast** to fetch that ticker and SPY, rebuild the trained features, and store a timestamped result. **Update all held stocks** loops only over the portfolio holdings; it does not do a universe scan. The optional enhanced comparison can be slower. Stored results persist in the same database and are associated with that portfolio and horizon; they can be viewed on reopening without immediately retraining. Missing or stale forecasts are explicitly indicated.

The table includes as-of date, modeled SPY-relative excess return, P(gain), P(+20% at the specified horizon), the selected model, and monitoring status. The illustrative hypothetical price endpoint assumes 0% SPY future return; it is **not** a validated absolute-price prediction, a price guarantee, or a trading instruction. Probability estimates may be uncalibrated if the available history is insufficient.

## 7. Monitoring and sell/exit reviews

The dashboard carries over the existing `plan_signals` rules, including **MONITOR** and **REVIEW EXIT**, and marks stale forecasts. It can flag when a current quote is below the model's historical review threshold; adjusted-vs-unadjusted price differences after corporate actions require caution. The detailed view shows an approximate future date to **review** conditions. It never claims to know the correct day to sell. A headline or a single model score is never an automatic sell order; no trades are placed.

## 8. All-held-stocks news feed

The workspace retrieves headline results for each held ticker, filters by publication timestamp and source attribution, then shows an aggregate newest-first list with links, publishers, company tickers, and word-level sentiment tags. It supports manually refreshing all company news and an optional **15-minute active-browser auto-refresh**. The underlying Google News RSS providers can miss articles, fail, impose limits or return partial content; this is not a guaranteed exhaustive news service. A recent headline sentiment score is not substituted for the trained forecast. The detailed stock explorer still provides SEC quarterly reporting, if configured.

## 9. Backups, import, and corrections

Export all recorded buys and sales into a portable CSV. The backup does not contain the recovery code. Re-import a compatible CSV into another portfolio using an atomic, validated import—bad rows or impossible sale history cause the whole import to fail. Import is additive, so importing the same CSV twice can duplicate transactions; the UI warns about this. A transaction can be removed and re-entered, with chronology checks. Keep the CSV and recovery code private.

## 10. Compatibility and deployment

All v2.2 price charts (including 1D's 8:30 AM–4 PM ET axis), experimental headline explanations, historical validation, exchange universe scanner, SEC analysis, macro context, and competition portfolio simulation are preserved. Both `app.py` and `ithaca_quant/__init__.py` now advertise **v2.4.0**; the preflight mismatch check runs before any feature imports. New files are `ithaca_quant/holdings.py`, `ithaca_quant/portfolio_workspace.py`, and `tests/test_v23_holdings.py`.

**Important installation:** Upload *all* contents from this ZIP's top-level `ithaca_quant/` into the existing GitHub repo `ithaca_quant/` directory, including both its outer `app.py` and inner `ithaca_quant/` Python package. Keep Streamlit entrypoint `ithaca_quant/app.py`. Don't copy the folder inside itself. Reboot if the old version persists.

## Verification and limitations

**129 offline automated tests passed** in a clean pytest run, including portfolio accounting, private access, database reopening, CSV backups, held-company-only forecasts, and all legacy chart/scanner/news/model tests. The portfolio ledger and import/forecast persistence were unit-tested in isolated SQLite databases. The environment used for packaging does not have Streamlit or yfinance installed, and cannot validate the live Yahoo/SEC/Google News connections or hosted GUI. Tests do not establish the financial forecast's market accuracy. Closing the browser stops refreshes; this version **does not send push notifications or autonomously monitor holdings after the page is closed**. PostgreSQL is optional but essential for reliable persistence on hosted deployments.
