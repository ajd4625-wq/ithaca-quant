# Ithaca Quant v1.4.1 — 1D Market Window, Readable Financials, Next-Session Forecasts

Released November 12, 2026. This is a maintenance release built on the complete v1.4 accuracy-first, SEC/news-evidence and incremental-refresh release. **It does not introduce a newly backtested financial forecasting model.** It changes chart presentation, forecast usability and the way errors are explained, without altering the model's core mathematical training procedure.

## 1. The 1D chart now always runs 8:30 AM–4:00 PM Eastern

**Previously:** the chart could appear to show a midnight-to-11 PM time axis on a deployed Streamlit screen. In the prior code, the intended range depended on the earliest actual bar and future endpoint. That is not the explicit visual window you requested.

**Now:** the 1D chart uses a fixed clock-time axis of **08:30 to 16:00 in America/New_York**, on the current New York calendar date. The Plotly x-axis receives explicit start and end datetimes, disables automatic ranging, and starts hourly ticks at 08:30. The app also filters 1D input to real provider observations within that same window; it does **not** manufacture bars for empty minutes.

- At 8:30 ET (7:30 Central in November) the chart starts even if the first observed bar is at 9:30 ET; the interval is intentionally blank until the first actual price.
- The first available real price is plotted at its true clock time, not moved backward to 8:30.
- Data from yesterday, before 8:30, or after 4 PM is not included in 1D.
- Even if a caller requests a forecast endpoint after 4 PM or on another date, the 1D x-axis does not extend beyond the allowed session window.
- The other chart ranges—5D, 1M, 6M, YTD and 5Y—retain their existing history and daily-forecast horizons.
- The time axis uses Eastern time (not the visitor's local computer time). Standard US regular market trading starts at 9:30 AM Eastern; the extra 8:30–9:30 segment exists only because the user requested it. If the provider returns premarket data in that segment, those real observations can be displayed.

**Limitation:** Exchange-specific holidays, special half-day sessions, and provider outages are not modeled as separate 1D axis configurations; the nominal 4 PM boundary remains even on early-close days.

## 2. Quarterly financial reports show commas, currency and readable dates

**Previously:** SEC and Yahoo Finance quarterly-report tables could show raw values such as `145234567890` or `1.452e+11`, which are hard to read.

**Now:** a new pure formatting module, `ithaca_quant/presentation.py`, formats *display copies only* of the quarterly figures. For example:

| Item | Previous display | v1.4.1 display |
|---|---|---|
| Quarterly revenue | 145234567890 | **$145,234,567,890** |
| Net income | -1234567890 | **-$1,234,567,890** |
| YoY revenue growth | 0.12754 | **+12.8%** |
| Net margin | -0.08435 | **-8.4%** |
| Diluted EPS | 1.1875 | **$1.19** |
| Date of filing | Timestamp object | **Nov 03, 2026** |
| Missing revenue | NaN / blank | **Not reported** |

Both the official SEC panel and the latest Yahoo quarterly-income display use the formatter. The formatting does **not** change numerical underlying data, model features, original earnings reports, or model training. A zero value remains `$0`, distinct from a genuinely missing value (`Not reported`). Yahoo data continues to be shown as current context only unless verified original SEC filing dates are available for model training.

## 3. Forecasts remain accessible after the market closes

**The root of the confusing “forecast not working” symptom:** the screenshot was taken after the regular market close, when v1.4 correctly disabled the **intraday** next-hours heuristic. That prevents a made-up forecast from being drawn from stale last-session prices. The result was an “Unavailable” hourly projection that looked like the entire forecasting feature was broken.

**Now the 1D view distinguishes two separate products:**

### A. Same-day next-hours illustration (1D dotted line)

- Uses the already-present, *unvalidated* shrunk intraday momentum heuristic.
- Requires at least six recent genuine regular-session bars, fresh provider data and a time before 4 PM Eastern.
- The heuristic now explicitly excludes premarket observations from its momentum calculation, even though premarket prices may appear on the 8:30-to-4 chart.
- It will **not** extrapolate into the next day. After 4 PM, before the open, or when data is stale, the dotted hourly projection remains absent on purpose.
- The main chart describes exactly why no hourly dot appears.

### B. Separate next-trading-session machine-learning outlook

- When **1D** is selected, the app requests a **1-trading-session horizon** from its existing daily machine-learning pipeline, independently of the hourly plot. Previously, 1D defaulted to the sidebar's 20/10/40-session horizon for the associated daily ML information, which could be confusing.
- The separate results section displays the model's predicted **SPY-relative return**, a hypothetical next-session price, and the date of the daily input data. The price assumes an illustrative **0% SPY return**; it is not a guaranteed executable close.
- The daily model can display a result *after hours* if enough verified historical ticker and SPY data are available. It does not require a current live quote.
- No next-day endpoint is drawn on today's fixed 1D chart. This avoids misrepresenting a next-day daily model forecast as the next few hours of today.
- In the 1D headline metrics, **P(gain next session)** replaces “P(+20% in one session).” A very large one-day boom event can be too rare to support an individual model; standard gain probabilities are more appropriate. They are **still not independently calibrated probabilities**, and the model shows “Insufficient history” when not estimable.
- For 5D, 1M, 6M, YTD and 5Y, the existing daily SPY-relative projections are preserved: respectively 1, 5, 20, 20 and 60 future trading sessions.

**What “forecast available” does NOT mean:** The daily ensemble has been trained and produces an estimate; it is not proof that this estimate will beat the market. A single-stock daily estimate remains a noisy, educational research forecast and should be interpreted alongside the app's untouched historical validation results.

## 4. Clearer forecast failures and a user-triggered retry

**Previously:** a failed daily model could produce a generic unavailable message. Users had to guess whether the error came from insufficient history, missing SPY data, rate limiting, or the fact that the market had closed.

**Now:**

- A disabled **hourly** forecast is explained separately from a failed **daily model**.
- If the daily ML computation actually raises an error, the interface displays its exception class and a concise error message, including troubleshooting suggestions. It does not substitute an invented forecast number.
- A **Retry daily data and ML forecast** button appears after genuine model errors. This clears the single-symbol data cache and relevant feature/model caches, then reruns the app once.
- This action occurs only on a direct button click. It does not add infinite network retries or hammer Yahoo Finance while the user is idle. Existing bounded app-level retries and three-worker safety rules remain unchanged.
- If the data provider is still unavailable or the model has too little usable history, the app continues to show a truthful unavailable status.

## 5. Version display now exposes mixed deployments

**Previously:** a Streamlit site could show modern features but still display an old version such as `v0.5.0`, because the visible heading came from the imported package `__version__`, which may not have been updated alongside `app.py`.

**Now:** the deployed app file labels itself **Ithaca Quant v1.4.1**, while the package also declares `1.4.1` in `ithaca_quant/__init__.py`. If the versions disagree, an explicit warning tells the user that some GitHub files are mismatched and which folder to replace.

**Important:** This check can detect an obvious mismatch; it does not prove that every other dependency in a remote Streamlit deployment is correct. You still need to upload all application files, not only `app.py`.

## 6. Preserved v1.4 systems

The patch leaves unchanged the persistent SQLite universe snapshots, incremental 20-minute active-page universe refresh, quote refresh controls, headline retrieval and archive, official SEC companyfacts, optional OpenAI headline explanations, accuracy-gated dated evidence features, historical testing, portfolio simulation, exchange listings, and risk/leaderboard features.

No unsupported current-headline score is silently added to the primary ML forecast. If SEC and archived news history do not pass chronological coverage and holdout checks, the core model remains price/volume based.

## 7. Install and verify

1. Extract `Ithaca_Quant_v1.4.1_Charts_Forecasts_Commas.zip`.
2. Open your GitHub repository `ajd4625-wq/ithaca-quant`. Replace the **contents** of the existing GitHub `ithaca_quant` directory with the files under the ZIP's `ithaca_quant` directory. Do not create an extra nested application directory.
3. Confirm that `ithaca_quant/app.py` and `ithaca_quant/ithaca_quant/__init__.py` both come from the same new ZIP.
4. Commit to `main`. In Streamlit Cloud, keep the main file path `ithaca_quant/app.py`. Reboot the app if it remains on an old build; restarting may delete locally stored market scans on Streamlit Community Cloud.
5. Choose **Instant stock explorer**, search a well-established ticker such as `AAPL` or `NVDA`, and select **1D**. Confirm the 8:30 AM–4 PM ET x-axis, comma-separated SEC/Yahoo figures, and the separate **Next trading-session machine-learning outlook**.
6. If the ML outlook says unavailable and shows an actual model error, use **Retry daily data and ML forecast** once. If the provider is rate limiting, do not retry indefinitely.

## 8. Verification performed

- **88 offline automated tests passed**, including a synthetic five-year 1-session ML forecast, after-hours intraday safety, display formatting, same-day filtering, and existing regression checks.
- Python source compiles, and the complete ZIP was checked for integrity.
- The build environment does not have `streamlit` or `yfinance` installed, so **the deployed browser UI and live Yahoo/SEC endpoints were not tested in this environment**. Client-side Plotly rendering should be checked on Streamlit Cloud after installation.

### Honesty about forecast accuracy

This is a reliability and UI improvement, not a verified jump in prediction accuracy. Data-provider gaps and rare-event probabilities still impose genuine limits. A next-day ML number can be produced after-hours without fabricating intraday data; it cannot accurately forecast market-moving news that has not yet occurred. The simulated portfolio does not place real trades.
