# Ithaca Quant Chrome Companion v0.6 — v3.2 Analyst & Portfolio Intelligence

**Source model:** the user-provided `Ithaca_Quant_v3.2_Analyst_Portfolio_Intelligence(1).zip`, merged into the Chrome Companion v0.5 architecture. This ZIP contains an installable **Chrome Manifest V3 extension** and a separate **localhost Python research backend**.

**Research only:** no brokerage permissions, orders, transactions, profit guarantees, or independently verified improvement in forecasting accuracy. Normal ticker signals remain based on completed daily adjusted closes, not necessarily current intraday trading prices.

## Install / upgrade on macOS

1. Extract `Ithaca_Quant_Chrome_Companion_v0.6.zip` (do not load the ZIP directly in Chrome).
2. Open Terminal in the extracted `Ithaca_Quant_Chrome_Companion_v0.6` folder and run:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -r backend/requirements.txt
   python3 backend/server.py
   ```

   Or execute `./start_mac.command`, which runs the same server setup. Leave this Terminal window running when using the extension. The server binds to **127.0.0.1:8765** only.
3. Open Chrome at `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, and select the extracted **`extension`** directory.
4. **Disable or remove the older extension** so both versions do not monitor the same pages. Pin the new icon and open the side panel. Optional page monitoring and floating overlay remain opt-in.
5. Start by entering a ticker and pressing **Analyze**. You can request Wall Street analyst research separately and enter your own virtual holdings in the new portfolio section.

> Existing v0.5 local SQLite data is **not migrated or overwritten**. Version 0.6 starts a new forward-evidence file, `backend/research_ledger_three_ml_v32.sqlite3`, so results for different code versions do not get mixed. Preserve your older ZIP/folder if you want its previous evidence reports.

## What has changed from v0.5

| Feature | Implementation / behavior | How to use | Boundaries |
|---|---|---|---|
| v3.2 upstream source | Updated `backend/ithaca_quant` from your actual v3.2 archive, including `analyst_consensus.py`, `portfolio_advisor.py`, and the updated portfolio workspace | Installed automatically in backend | The three fitted forecasting algorithms remain as previously implemented |
| Analyst consensus | Normalizes strong-buy/buy/hold/sell/strong-sell counts, source, rating period, observation time, shrunk score, and price target range | Analyze a ticker, choose Yahoo or Finnhub, click **Check analysts for this stock** | Provider estimates are not short-horizon ML forecasts; missing opinions are marked unavailable |
| Firm rating changes | Fetches source-attributed upgrades/downgrades when returned by the selected provider | Same analyst research button | News/analyst data may be incomplete; no private or early disclosures |
| Portfolio research | Computes historical adjusted-return covariance and bounded long-only **hypothetical** weights with cash reserve, concentration and turnover controls | Enter holdings in the dedicated section, then **Research my portfolio** | Refuses missing data; no market orders, tax modeling, fees or prospective alpha certification |
| Correct price bases | Uses fresh unadjusted Yahoo intraday quotes or explicitly user-entered ordinary prices to calculate position values; adjusted closes are used only for historical risk | Enter lines `AAPL,10,250.00` or `MSFT,5` | Yahoo quotes may be delayed; manual prices are user-reported and may be stale |
| Snapshot provenance | On successful analyst research, records provider, original rating period and observation time in `backend/analyst_observations_v32.sqlite3` | Built into opt-in analyst requests | Current snapshots **cannot be inserted into earlier backtests** as though historically known |
| Offline/cache performance | Limits analyst lookup concurrency to 3; caches analyst research for 15 minutes and portfolio price history for 10 minutes; only one concurrent expensive portfolio study | Automatic during user-requested research | Real network latency, provider rate limits and CPU performance vary |
| Three fitted ML agents | Retains Forecast (Histogram Gradient Boosting), Momentum (Ridge), Risk (Logistic Regression) and the existing baseline/abstention gate | Normal page monitoring / Analyze button | Their source market histories overlap; they aren't statistically independent |
| Retry ceiling | Uses exactly `MAX_RETRIES=2` after first attempt for controllable upstream provider operations | Automatic | Some third-party libraries may internally implement their own retries |
| Weekly accuracy | Keeps immutable 5-session SPY-relative forecast outcomes and Friday reports, using a **separate v3.2 database** | **Weekly forward accuracy ledger** in the panel | Requires the backend active for recording; no claimed verified win rate initially |
| Historical integrity | Retains the prior v3.1 source-archive checksum and point-in-time audit tools | **Historical Data Integrity** section | Source-code ZIP is not a licensed historical-delisted-stock dataset |
| Existing UX | Floating overlay, side panel, opt-in recognized tickers, SEC Form 4 research, news-event grouping, on-demand model lab, screenshot preview | As before | Screenshot preview is **not** AI vision; no automatic all-screen capture |

### How to use new analyst research

1. Open a supported stock page or enter a valid stock ticker.
2. If desired, click **Analyze** for the existing 5-session three-model forecast.
3. Below SEC filings, choose **Yahoo Finance (best effort)** or **Finnhub**.
4. Click **Check analysts for this stock**. It displays the number and mix of disclosed ratings, mean/low/high target values, the published period, fetch time, and recent attributed analyst actions when available. An unavailable provider is reported as unavailable—not 0 opinions or a neutral outlook.
5. The analyst data is **not injected into the three models or graded as five-session expected outperformance**. It is contextual research, not a substitute for independently verified forward performance.

Optional Finnhub access: set `FINNHUB_API_KEY` in the backend **Terminal environment** before launching. Do **not** enter the token into the Chrome panel, CSV or a source file:

```bash
export FINNHUB_API_KEY='your-authorized-provider-token'
python3 backend/server.py
```

The backend's HTTP error processing redacts provider URLs/tokens. Finnhub endpoint permissions vary by plan. Yahoo data may be blocked or rate-limited. If you have no live credentials, Yahoo is the default best-effort provider.

### How to use the new portfolio research

1. In **My portfolio · analyst & risk study**, enter one line per holding, for example:

   ```text
   AAPL,10,250.00
   MSFT,5
   NVDA,8,180.50
   ```

   These are **examples of input syntax, not actual quotes**. Enter existing holdings only (1–20 symbols). The third column is an optional **ordinary current price per share**; when missing the backend attempts an unadjusted Yahoo intraday quote and checks its date against the completed price history.
2. Click **Save holdings locally** to store only the text in the local Chrome profile. This save action does **not** contact the backend. The backend receives the holdings only after **Research my portfolio** is clicked.
3. Set a hypothetical **cash reserve** (10% default) and **maximum single-stock weight** (20% default); both are editable.
4. Click **Research my portfolio** to request current analyst observations and synchronized adjusted daily histories for the **same currently held stocks**. The research solver uses covariance shrinkage, position caps, cash, turnover controls and only *small* conviction adjustments for fresh analyst ratings and already-computed validated Ithaca predictions (if any are cached in the running backend).
5. Review the actual-versus-hypothetical weight table, analyst availability, source, quote provenance, historical volatility, effective cash and illustrative turnover. **Export CSV** for a private research file; no trades occur.

If there are fewer holdings than can fill the chosen cap, cash can be **higher than the requested reserve**. For example, 2 holdings each capped at 20% can produce at most 40% stock exposure, leaving 60% unallocated. Lower volatility can therefore simply reflect larger cash balances—not a demonstrated forecasting improvement.

**Input quality:** Missing price quotes, stale provider quotes, missing daily price bars, fewer than 126 synchronized return observations or optimizer failure cause **no portfolio study weights**. User-entered quotes are labeled manual, so confirm their timing independently. The system cannot see your separate virtual portfolio account automatically, and it does not sync with the main Streamlit app's private login or holdings ledger.

### Automatic accuracy record and report behavior

- Regular validated, non-synthetic three-ML forecasts are recorded on the completed close in `backend/research_ledger_three_ml_v32.sqlite3` and graded after **five subsequent aligned completed stock/SPY sessions**.
- Repeated visits to the same ticker and issue date do not make duplicate predictions. Abstentions are retained but aren't counted as correct directional calls.
- Reports separate the weekly and lifetime sample counts, pending observations, correct sign rates, and forecast error versus a zero-excess-return baseline. Uncertainty estimates are labeled as not adjusted for correlated issue dates.
- A Friday report is written after the completed session **only while the backend is running**, and best-effort Chrome notifications require the extension and monitoring to be enabled. If your computer was off, the backend can grade already-recorded predictions when it next runs, but cannot retroactively create predictions it never made.
- Observed analyst snapshot dates are recorded **separately**, not graded as five-session ML outcomes. Future work can examine analyst opinions prospectively only when appropriate horizons and sufficient real observations are available.

## API endpoints added in v0.6

- `GET /analysts?ticker=SYMBOL&provider=yahoo|finnhub&actions=1`: on-demand current observed analyst research and optional recent firm actions. No bearer token returned.
- `POST /portfolio/study` with `Content-Type: application/json` and an authorized Chrome-extension Origin, for example:

  ```json
  {"holdings":[{"ticker":"AAPL","shares":10,"price":250}], "provider":"yahoo", "cash_reserve":0.10, "max_position":0.20}
  ```

  Prices in this example are user-entered **illustrations**, not verified market prices. The operation is read-only. It imposes an 8 KiB request limit and accepts a maximum of 20 positions.
- `GET /health`: reports v0.6/v3.2 model and three-agent/two-retry settings.
- Existing historical, insights, model-lab and weekly report endpoints remain available. The local server only listens at `127.0.0.1` and rejects browser requests from normal websites.

## Optional point-in-time market archive

No institutional-grade historical price/universe dataset was included in the v3.2 **code** ZIP. The original historical-data archive workflow remains intact. See `docs/HISTORICAL_DATA_GUIDE_v3.1.md` for the strict provider schemas and permanent stock IDs. A user-supplied archive needs authentic dated membership, actual terminal payouts, source and provenance; file hashes check integrity, not vendor truth. Archive studies remain **separate** from fast browser signals and from v3.2 current analyst opinions. The older v3.1 retrospective tool remains named `scripts/run_v31_archive_audit.py` because its archived-data protocol is unchanged.

## Testing and remaining limitations

At package time, **67 offline Python tests passed**, including the upstream v3.2 analyst/portfolio tests, the prior model/archive tests, local API origin rules, quote-basis separation, error handling, missing-data rejection, and weekly ledger version checks. All extension JavaScript files passed `node --check`. The code can be exercised without live Yahoo or Finnhub accounts using test fixtures.

The tests do **not** prove that any model beats SPY, that the analyst tilt improves prediction accuracy, that the portfolio allocations are better investments, or that any provider works with your live account. Actual Chrome installation and paid provider connectivity have not been independently verified in your environment. Browser signals remain uncertain and do not include taxes, commissions, execution costs or guaranteed real-time prices.

Run tests yourself:

```bash
python3 -m pip install pytest
PYTHONPATH=backend python3 -m pytest -q
node --check extension/panel.js
node --check extension/content.js
node --check extension/background.js
```

**Keep this work for education, experimentation, and research; it is not an automated investment recommendation or trading system.**
