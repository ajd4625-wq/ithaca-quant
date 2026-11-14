# Ithaca Quant v1.4.0 — Full Release Details

**Release goals:** Make the whole-universe workflow much less repetitive; deliver faster, transparent refresh targets; incorporate verifiable quarterly SEC information and an accumulating, causally timestamped news dataset; make the model **prefer historical evidence over arbitrary positive/negative headline adjustments**.

This remains a **virtual-stock competition educational research tool**, not a verified market-prediction service. No release can guarantee stock-market accuracy. All source information, especially public Yahoo feeds, may be delayed, absent, inconsistent, or subject to limits.

## 1. Persistent snapshots for the NYSE and Nasdaq universe

- **Before:** Every new application session could require repeating exchange discovery and downloading up to a year of prices for thousands of symbols before selecting the ML shortlist.
- **Now:** The full-universe screen and the corresponding adjusted daily price matrix are stored as compressed JSON in a **versioned local SQLite file** (`~/.ithaca_quant_cache/market_cache_v1.sqlite3` by default). We do NOT unpickle untrusted serialized Python objects.
- The cache is keyed by the exact symbol universe, research-history length, screening shortlist size, and dataset type. A 1-year screening sample cannot masquerade as a 5-year deep-model history.
- **Full NYSE + Nasdaq scan** is still available for first setup or major history reconciliation. **Refresh saved universe** checks only recent daily market bars, while preserving prior valid observations.
- A saved screen may be loaded across application reruns or local restarts without repeating a full scan. State is kept in the shared app instance's storage instead of per-user Streamlit Session State alone.
- **Important hosting limit:** Streamlit Community Cloud's filesystem can be reset on restart/redeployment, so its local SQLite cache is **NOT durable cloud storage**. For guaranteed persistence through hosted restarts, a separately configured persistent volume/database is still necessary. The app warns about this and never claims an off-host refresh occurred.

## 2. Accurate incremental price refreshing and safeguards

- On refresh, fetch a short period beginning **nine calendar days before** the latest stored SPY session, then merge genuinely new adjusted closes and trading volumes by timestamp and ticker.
- A new missing observation stays **NaN** rather than being filled with yesterday's close as if it were today's price. A ticker lacking a valid current feature row is ineligible for an up-to-date model forecast.
- Significant changes across two or more overlapping adjusted bars trigger a **full historical refetch** for the affected symbol (up to 25 in a repair batch), instead of silently mixing pre-split and post-split price scales.
- If the vendor fails or the repair is incomplete, the original cached dataset remains intact and receives a prominent **STALE** warning. A failed refresh never silently receives a fresh timestamp. Initial full scans report missing and excluded tickers rather than inventing prices.
- For the daily forecast, *today's incomplete Yahoo daily candle is removed until 5:00 p.m. America/New_York*. This is a conservative publication time, not an exchange holiday calendar; the separate intraday price chart remains available for current trading-session monitoring.
- Two tiers: **screen universe** maintains ~1 year of adjusted daily data, while the **modeled shortlist** maintains the selected multi-year history. Cached panels/models are reused when the underlying completed daily observations have not changed.

## 3. Active-session update frequencies and provider limitations

| Data/feature | v1.4 target | Mechanism / limitation |
|---|---|---|
| Latest quotes for priority group (default 20 names) | **15 s** | Opt-in Streamlit fragment while the full-market browser page is open; 15/30/60/120 s configurable; tabs may execute when hidden, so auto quotes are OFF until enabled; may be delayed/rate-limited |
| Priority group >25 symbols | At least **60 s** | Rate-limit safeguard; up to 75 selected symbols via 25-symbol Yahoo request batches |
| News RSS lookup / fetched headline context | **2 min cache** | Search page can auto-rerun every 2 minutes if the checkbox is enabled and the browser stays active; RSS sources may not update each cycle |
| Stock exchange listing directory | **6 hours cache** | Can miss newly issued/delisted securities until next successful refresh |
| Full-universe recent daily bar reconciliation + screen | **20 min** | Active-page automatic refresh enabled by default; no historical re-download unless provider revisions force it |
| Deep model's newest completed adjusted daily bars | Minimum **5 min** between checks | Refreshes on full-market page run; expensive model retraining is avoided if completed daily prices are unchanged |
| Daily forecasts and rankings | When completed market data, configuration, or eligible archived features change | **Not necessarily new predictions every 5 min**; a 20-session model can't extract unique information from the same unchanged daily close |
| SEC public companyfacts and Yahoo income-statement fallback | **6 hours cache** | Only for selected **individual stock** in v1.4, not every symbol in the broad scanner |
| Validated feature/model selection | Whenever model input data or research horizon changes | Chronological comparison can add computation; never guarantees improved future results |

Auto-refresh works only while an interactive browser session is active. It is **not an always-on scheduled cloud worker**. Frequent large Yahoo requests can be throttled, fail, or return stale data. The active auto screen uses a 20-minute failure cooldown to reduce repeat request storms. High-frequency quote fetching is explicitly opt-in, because Streamlit tab contents can run even when a tab is not selected. Quote freshness is always reported with timestamps.

## 4. Quarterly financial reports added for single-stock research

- With a configured owner contact in server-only **`SEC_CONTACT_EMAIL`**, the explorer can call the **official U.S. SEC public issuer directory and companyfacts API** for the selected U.S. issuer. SEC data is not available for every ticker, class, ADR, or accounting taxonomy.
- Extracts attributable **quarterly revenue, net income, year-over-year quarterly revenue change, and reported net-profit margin**, where comparable 10-Q, amended 10-Q, or 10-K quarterly-duration facts are actually available.
- Excludes annual-duration financial facts that might be wrongly presented as 90-day quarterly revenue. Missing metrics remain blank.
- Tracks the **filed date**, not just the fiscal period end. Historical model features become eligible from the **next business day after their filing date**, avoiding the error of using a March 31 quarterly result to predict markets in April if the company did not file it until May.
- When SEC data is not configured/unavailable, the app still tries to show a small **Yahoo Finance quarterly income-statement summary** (revenue, net income, diluted EPS). Yahoo summaries generally lack reliable original filing timestamps, so this fallback is **for current analysis only and is never retroactively used to train the historical model**.
- SEC issuer lookup requires identifying server-side contact for fair-access compliance. Put the email in Streamlit Secrets and **never place credentials, personal contact information, or private account information into public GitHub**.

## 5. Accuracy-first model selection for SEC fundamentals

- The existing two-model ensemble (histogram gradient boosting plus random forest) remains the base model for SPY-relative stock returns.
- When sufficient SEC filed-date coverage exists, the system constructs **point-in-time numeric features** for growth, margins, report age, and a coverage flag. Missing financial metrics do not masquerade as actual zero growth.
- It compares **price-only** against **price + SEC evidence** using a later, chronological **training-period holdout**. Training features for each candidate are restricted to data available on or before the simulated signal date; the held-out window's labels cannot be used in fitting its underlying models.
- SEC factors are **accepted into the final model only after the SEC variant lowers this comparison's mean absolute error by at least 1%**. The selected model is then retrained on mature histories. The app displays whether SEC features were accepted or rejected and displays relative model-selection MAE where available.
- The holdout is used for **model selection**, so its MAE is **not** an independent confirmation of generalization. A distinct chronological walk-forward or untouched evaluation is still necessary. Additional features can overfit.
- In whole-universe modeling, the feature-selection gate requires meaningful ticker coverage, preventing the facts of one company from being inappropriately used to determine a model for hundreds of unrelated tickers.

## 6. News archive that can eventually support true trained news predictions

- Every eligible ticker-specific headline fetched during individual searches or the existing top-five news comparison can be **recorded once** in the local SQLite archive (ticker, publisher, title, link, UTC publication timestamp, first-seen timestamp, word sentiment, and relevance).
- **First-seen is authoritative:** if an app only discovers a headline on Thursday, the ML dataset may not insert that headline into Tuesday's historical features merely because its publication field says Tuesday. Only articles the app actually observed are considered. Training features become usable **next business day** after first-seen.
- Builds rolling seven-calendar-day historical news counts and weighted headline language from the observed archive. Without enough archived dates and issuer coverage, **the core ML forecast stays price-only (or price+eligible SEC)**.
- A news-based candidate must beat the price-only comparison by **at least 2%** in chronological model-selection MAE, stricter than the SEC gate. A combination of dated SEC + archived news can also be considered when both histories meet coverage thresholds.
- The trained model and the independent walk-forward runner use the same evidence-selection function. However, the archive starts empty at installation, may be erased by hosted restarts, is restricted to fetched sources, and needs **months of continuously collected historical evidence** before it can possibly qualify. This release does **not** falsely announce that a newly installed app already learned news-return relationships.

## 7. Main forecast no longer uses unsupported sentiment coefficients

- **Before v1.4:** A word-level positive/negative headline heuristic was permitted to move the main dotted daily forecast endpoint and the separate 1D momentum heuristic, even though the coefficients had not been historically fitted or validated.
- **Now:** The principal dotted endpoint comes from the trained price/optional eligible-evidence model alone. The 1D intraday hypothetical endpoint no longer receives a headline-word adjustment. The historical model's raw SPY-relative estimate remains visible.
- The previous **bounded news-sensitivity scenario** is retained in a separate research table with explicit labels, allowing comparison without mistaking it for a proven forecast. Boom and volatility sensitivities are also labeled **scenarios**, not validated calibrated probabilities.
- Today's news still receives a publisher-attributed headline breakdown, link, date, relevance and positive/negative language, and optional paid server-side generative commentary if configured. A generative model does not secretly control numeric predictions.
- SPY-relative ML return is not an absolute-price forecast: the visual hypothetical target still assumes **0% future SPY return**, and its straight dotted line does not imply a predicted intraday path.

## 8. Chart improvements and prior capabilities preserved

- The 1D graph continues to begin at the **first observed intraday bar of TODAY in U.S. Eastern time**, not midnight. It ends at the last actual observation or a valid intraday projection; missing today data means a blank chart, not yesterday's prices.
- Six historical ranges (1D, 5D, 1M, 6M, YTD, 5Y) and horizon-matched endpoints remain available.
- The whole-universe leaderboard, metadata filters, sample research rankings, latest quote panel, paper portfolio, 3 ranking components (Forecast/Momentum/Risk), up to 3 app-level parallel workers and 2 app-level retries were retained.

## 9. Configuration, installation and limitations

**Deploy:** In `https://github.com/ajd4625-wq/ithaca-quant`, replace the **contents** of the `ithaca_quant/` subfolder with the ZIP's extracted `ithaca_quant/` files, including new Python modules and tests. Do not create a second nested folder. Commit to `main`. Your Streamlit entry point stays `ithaca_quant/app.py`.

**Local Mac:** Unzip a new release alongside the old version or replace the old project files; in Terminal run `cd ~/Downloads/ithaca_quant && bash start_mac.command`.

**Optional Streamlit Secrets** (configured by app administrator, not in GitHub):

```toml
SEC_CONTACT_EMAIL = "valid-app-admin-contact@example.org"
# OPENAI_API_KEY = "..."  # optional, paid generative headline summary
```

`example.org` above is a placeholder: replace it with a real contact before making SEC requests. **No API key is required for the SEC public XBRL endpoint**, but the SEC expects a proper user-agent identity. Unconfigured SEC features fail closed and Yahoo current-only quarterly context may still appear.

**Local cache directory:** environment variable `ITHACA_CACHE_DIR` can move the SQLite files to an operator-managed disk. Do not commit or share a saved cache if its news records or organizational research settings are private. Hosted Streamlit restarts can erase default local files.

**Testing:** The v1.4 release has offline automated tests including new cache round trips, historical-only daily observations, incompatible price adjustment detection, stale provider fallback, SEC filing-date/restatement handling, article first-seen rules, anti-leakage model features, and missing-data fallback. It passed `python -m pytest -q` and Python `compileall` during packaging. Because this environment has no Streamlit/yfinance packages or external internet API access, the deployed browser UI, real SEC fetch, real Yahoo historical and 15-second quote behavior **have not been end-to-end tested here**.

### Important truth-in-advertising note

This is an effort to make the model **more verifiable and harder to mislead**, not a guarantee of greater future prediction accuracy. Filings and news can be predictive, irrelevant or misleading; historical correlations can change. We deliberately do **not** label untested, price-model + sentiment-word guesses as accurate AI forecasts.
