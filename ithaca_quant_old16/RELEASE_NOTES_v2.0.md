# Ithaca Quant v2.0 — Ten Accuracy, Intelligence, Infrastructure & Risk Upgrades

**Release date:** November 14, 2026. **Scope:** Educational virtual investment research, never live execution. Based on the matching v1.4.2 release. This release implements all ten improvement *workstreams*. Some capabilities activate only after you provide legitimate data, credentials, or independent evaluation; none can guarantee better stock forecasts.

## What has been built — all 10 workstreams

### 1. Historical news, earnings and fundamental intelligence

**Code:** `news_events.py`, `news_archive.py`, `earnings_expectations.py`, expanded `fundamentals.py`, `features.py`, `model.py`.

- Previously archived headlines now become **event-specific dated features**, including earnings, management guidance, analyst actions, regulation and macro events. Simple keywords are transparent classifiers **not verified interpretations of the entire article**. Current articles are separately summarized and attributed.
- In **Accuracy lab**, upload a historical vendor-news CSV with exact fields `ticker,title,url,publisher,published_utc,first_seen_utc,sentiment,relevance`. Check the license and timestamp-provenance confirmation before import. The software validates event chronology, rejects future/invalid timestamps, and preserves the first valid record on duplicates. `first_seen_utc` must mean when the provider **originally made the item available**, not when you downloaded the CSV today. The app cannot independently certify a vendor's historical timestamp assertions or license. Never fabricate a retrospective first-seen date.
- Official SEC companyfacts now derive available **diluted EPS, EPS year-over-year growth and revenue-growth acceleration**, in addition to existing quarterly revenue growth, margin, and filing age. These become eligible only after filing dates, with prior restatements gated conservatively. Missing data stays missing/flagged.
- **Actual earnings surprises** require analysts' *prior EPS expectations*. The individual explorer now accepts an optional vendor CSV with `ticker,expectation_timestamp,release_timestamp,expected_eps,reported_eps,source`; entries with estimates dated after the result are rejected. The model learns from vendor EPS surprise only when the historical holdout has adequate coverage and improvement. SEC year-over-year EPS change is **not** an analyst consensus surprise.
- **Accuracy safeguard:** news, SEC, surprise and regime features are **candidates**. They must pass coverage and historical-selection checks to enter the main price prediction; external data isn't automatically considered predictive because it was provided.
- **Unavailable without your data:** A complete licensed historical headline feed, historically timestamped analyst expectations, authoritative company text interpretation, and validated live earnings surprise performance. The app does not create these datasets.

### 2. Stronger forecasting models and horizon-specific evaluation

**Code:** `research_lab.py`, `model.py`, optional `requirements-optional-ml.txt`.

- The individual explorer, if the new **Validate alternative forecasting models** checkbox is enabled, compares the existing HistGradientBoosting + RandomForest ensemble against Ridge and ExtraTrees (built-in) plus **optional** LightGBM, XGBoost and CatBoost (if installed).
- Candidates only replace the existing ensemble after at least **2% lower validation MAE** on a separate chronological validation segment. Ties and failed/outdated/absent model libraries fall back to the baseline. Models are re-fitted on mature history before issuing predictions. Training targets remain stock excess return vs SPY, capped for numerical stability.
- The existing 1-, 5-, 20- and 60-trading-session explorer mappings invoke separately constructed horizon-specific datasets. The broad-universe scanner deliberately keeps the lighter model path by default so that a scan over thousands of listings remains workable.
- This does **not** establish that any alternate model performs better live. If it can't demonstrate improvement, the system retains the existing ensemble.

### 3. Stronger chronological validation and real forward-tracking

**Code:** `research_lab.py`, `forecast_audit.py`, existing `backtest.py`, `validation.py`.

- The candidate selection sample has a **purged boundary**: a training example is excluded if its entire forward return label has not matured before the validation period.
- A **different later calibration block** is held out from candidate selection. There are minimum counts; insufficient history falls back to no interval.
- A new **immutable prediction ledger** saves ticker, as-of trading date, horizon, model, and original SPY-relative forecast once. Reloads don't overwrite it. As outcomes mature, it scores actual observed relative returns, MAE versus the predict-zero baseline, and direction accuracy.
- Access forward results under **Full-market dashboard → Accuracy lab**. Real forecasts require real prices; synthetic mode is excluded. The existing Walk-forward tests tab remains available for historical model comparisons.
- Warning: repeats of one ticker, overlapping forecast windows, delayed data, revisions and survivorship bias are genuine limitations. Neither held-out calibration nor a small real-forward sample provides a guarantee.

### 4. Market regime detection

**Code:** `research_lab.market_regime`, `features.py`, `model.py`.

- The system now distinguishes **upward trend, declining market, high volatility, and range-bound** SPY environments using the most recent 20-day price trend and annualized volatility.
- The exact indicator values are displayed in the explorer and Accuracy lab. The baseline model already uses continuous SPY momentum and volatility; the additional discrete regime indicators can enter the trained model **only if** they improve the historical selection check. A categorical regime by itself is not a trading signal.

### 5. Prediction intervals, not false certainty

**Code:** `research_lab.finite_interval`, explorer forecast evidence UI.

- When 50 or more valid calibration outcomes are available, the enhanced model shows an **empirical nominal 80% interval** for future **SPY-relative return**, using the conservative empirical absolute-error quantile from a separate purged calibration period. It also reports calibration MAE and predict-zero MAE.
- If the sample is inadequate or validation fails, the UI shows **no interval**, not a fabricated one. Changing market conditions can invalidate the empirical coverage, so it isn't a guaranteed probability or a full-dollar stock-price prediction interval.

### 6. Durable optional cloud database

**Code:** `remote_store.py`, modified `market_cache.py`, `news_archive.py`, `forecast_audit.py`.

- With a legitimate owner-controlled PostgreSQL connection, saved screening snapshots, incremental price histories, timestamped news and forward forecasts can persist outside Streamlit's ephemeral filesystem. SQLAlchemy + psycopg are in `requirements.txt`.
- Set `ITHACA_DATABASE_URL` **only in Streamlit Secrets** (or a secure server environment), e.g. an authorized, managed PostgreSQL URL. The application creates three tables: `iq_snapshots`, `iq_headlines`, `iq_forecasts`. Never commit or publicly display credentials.
- Without a database, the app still uses **local SQLite**. Cloud database outages are surfaced rather than silently claiming durable storage. A shared hosted database can have charges; no provider or account is bundled.

### 7. Macroeconomic/Federal Reserve context

**Code:** `macro.py`; new **Data & macro** dashboard tab.

- Optional `FRED_API_KEY` in server Secrets enables dated Federal Reserve effective rate, 10-year Treasury yield, unemployment rate, and CPI observations.
- Historical as-of requests use **FRED/ALFRED real-time vintage parameters**, preventing the UI from presenting today's revisions as if they were known years earlier.
- Macro values are **research context only** in this release, not silently fed into the trained model. A real vintage-complete macro training dataset and controlled validation must precede that.

### 8. Improved portfolio risk and virtual stress tests

**Code:** `portfolio_stress.py`; existing Virtual portfolio tab.

- The user’s selected virtual positions now receive historical **beta to SPY**, the largest allocation weight, pairwise historical stock correlations, a concentration index, historical lower-tail return estimates and illustrative **SPY down 5%, 10%, and 20%** shock responses.
- All risk calculations for the hypothetical historical entry use the pre-entry history, not data revealed after the simulated purchase. Beta-based shocks are linear simplifications and omit gap risk, liquidity, transaction costs, and correlations changing under stress.
- The existing $1 million virtual competition constraints (5–20 stocks and 25% initial cap), static-share illustrations, signals and risk-budget checks remain.

### 9. More robust data updates and optional independent scheduling

**Code:** `provider_health.py`, `scripts/refresh_job.py`, `.github/workflows/ithaca-refresh.yml`, existing `incremental.py`, `market_cache.py`.

- Existing 15-second **on-screen priority quotes**, 2-minute news cache, 5-minute deep-data check and 20-minute active-screen incremental-universe refresh remain. Provider limits, incomplete daily bars, corrections and changed split-adjusted histories are handled as before.
- An **opt-in GitHub Actions scheduled worker** can refresh a configured shortlist independently of the browser, if `ITHACA_DATABASE_URL` and `ITHACA_REFRESH_TICKERS` repository secrets are set. A local request-budget guard prevents some duplicate refresh attempts. The worker processes **at most 75 tickers by default**, not the entire unbounded exchange universe. The scheduler can be delayed or disabled by the host; it is not high-frequency institutional market infrastructure.
- **Important workflow path:** GitHub recognizes `.github/workflows/ithaca-refresh.yml` **at the repository root**, not inside your app subfolder. The ZIP contains the source under `ithaca_quant/.github/workflows/`; move **that workflow file** into the repository-root `.github/workflows/` if you want scheduling. The Python job stays at `ithaca_quant/scripts/refresh_job.py`. Do not commit secrets. The workflow is inactive for market collection until credentials/watchlist are configured.

### 10. Explainability and system health

**Code:** `research_lab.py`, Streamlit individual explorer, new **Accuracy lab** and **Data & macro** tabs.

- Forecast explanations show the **selected model**, which evidence groups passed historical gates, empirical error/range, leading feature *sensitivities*, and the current descriptive market regime.
- Each sensitivity is a change to the prediction when one current feature is replaced with its historical median. It is **not** a causal, SHAP, or verified economic contribution.
- System health displays backend readiness, latest completed-session date, provider status, macro availability and scheduling conditions. Incompatible `app.py` and package versions still trigger the explicit mismatch screen before feature imports.

## Exact folder structure and safe upgrade

In your GitHub repo `ajd4625-wq/ithaca-quant`, use:

```
ithaca_quant/                       # application folder already in your repo
  app.py                            # v2.0.0
  requirements.txt
  ithaca_quant/
    __init__.py                     # __version__ = "2.0.0"
    explorer.py
    research_lab.py
    ... all other Python files ...
  scripts/refresh_job.py
  tests/...
.github/workflows/ithaca-refresh.yml    # OPTIONAL: place at REPO ROOT
```

**Do not** upload only `app.py` or only `__init__.py`; replace the **entire contents of the matching app folder**. The release ZIP itself contains an outer `ithaca_quant/` folder intended to be merged with your existing GitHub app folder, not nested inside it again. Keep the Streamlit main-file setting `ithaca_quant/app.py`, branch `main`. Commit/redeploy, then reboot if necessary. New dependencies may require a new cloud build.

## Optional secrets (owner-controlled, authorization required)

Add the following keys only if you actually have valid, permitted services and intend to enable them. The placeholder strings below are **not valid credentials**:

```
SEC_CONTACT_EMAIL = "your-own-valid-contact@example.org"
FRED_API_KEY = "YOUR_OWN_FRED_KEY"
ITHACA_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/DB"
```

For GitHub Actions, use repository **Actions Secrets** `ITHACA_DATABASE_URL` and `ITHACA_REFRESH_TICKERS` (a comma-separated **small watchlist**), not Streamlit-only secrets.

To enable optional premium model libraries on a compatible environment, install `requirements-optional-ml.txt`. Their packages are not required by the default hosted app and are absent from its `requirements.txt` to avoid heavy, unreliable default builds. Do not install data services or credentials you aren't authorized to use.

## Current known limitations / explicit nonfeatures

- There is **no claim** of greater accuracy until real out-of-sample and forward data demonstrate it. Baseline fallback is expected when enhanced candidates fail.
- Full historic licensed market news and analyst-estimate feeds are **not bundled**; source licensing, source accuracy and past availability must be verified by the owner. Missing feeds mean inactive advanced features.
- FRED macro variables provide dated explanatory context, not trained predictive effects.
- SEC quarterly extraction is **on demand for individual stocks**, not thousands of SEC requests per entire-universe refresh.
- New advanced model selection is **individual-stock focused**. The full-market scanner still uses its practical fast baseline with separately validated optional regime/news features.
- Scheduled automation requires owner configuration. Streamlit screen-based refresh cannot guarantee updates while the page is sleeping.
- Actual exchange listing delistings and corporate actions may introduce bias; adjusted Yahoo histories and free news RSS can fail or be delayed.
- AI news text summaries and rule-based headline sentiment do not automatically override the trained return forecast.
- A price endpoint assumes future 0% SPY return for illustration, not a calibrated absolute-price prediction; 1D after-close hourly extrapolation remains disabled and its chart retains the 8:30 AM–4 PM ET axis.
- This package was **tested offline**. No live SEC/FRED/Yahoo/OpenAI/Streamlit Cloud calls, deployed UI, or paid model feeds were tested in the build container.

## How to verify after upload

1. Confirm the homepage says **v2.0.0** and the inner `ithaca_quant/__init__.py` has the matching version.
2. Load `AAPL` (or a supported ticker) in **Instant stock explorer**, select 1D (8:30 AM–4 PM ET) and a longer chart range, enable model comparison and inspect the evidence panel.
3. Confirm the full market scanner still offers saved-universe incremental refresh.
4. Open **Accuracy lab** to confirm the immutable forward ledger; new installations cannot have matured live forecasts immediately.
5. Open **Data & macro** to check SQLite versus configured remote database, provider freshness and optional vintage macro information.
6. Open the virtual portfolio tab and inspect the new shock/stress risk section.
7. Check the Streamlit **Manage app → Logs** if any startup import or external-provider error appears. Do not attempt to cure version mismatches by editing the number alone.
