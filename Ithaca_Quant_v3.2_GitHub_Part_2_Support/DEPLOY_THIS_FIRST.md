# Deploy Ithaca Quant v3.2 — Portfolio intelligence upgrade

Install the **complete** v3.2 archive at the repository root, preserving `streamlit_app.py`, `app.py`, `ithaca_quant/`, `.github/`, `scripts/` and `requirements.txt`. Do not combine older versions or commit credentials. Back up your portfolio database before replacing the existing app.

1. `pip install -r requirements.txt`
2. `python scripts/preflight.py`
3. `python -m pytest -q tests/test_v32_analyst_portfolio.py`
4. Start/deploy with `streamlit_app.py` and open **My portfolio**. Use Yahoo Finance best-effort analyst data by default. For an authorized Finnhub API account, add `FINNHUB_API_KEY` to Streamlit Secrets or the server environment; never write it to CSV, GitHub or visible app source.
5. Click **Refresh analyst opinions and risk research** after recording your virtual holdings. The panel runs only on demand and never transmits orders.

Cloud deployment, provider entitlements and live broker data have **not** been tested here. Past v3.1 point-in-time archive imports still require independently sourced historical data. See `RELEASE_NOTES_v3.2.md` and `ANALYST_PORTFOLIO_GUIDE_v3.2.md`.

---

## Archived deployment notes from previous releases

## New in v3.1: historical data integrity

Ithaca now supports point-in-time historical market archive ZIPs with stable security identities, exact raw and adjusted closes, dated membership snapshots, documented delisting payoffs, and SEC filing-vintage data. **No complete authenticated stock database is bundled.** See `HISTORICAL_DATA_GUIDE_v3.1.md` and `RELEASE_NOTES_v3.1.md`.

## v3.0.0 deployment — current release

Use the complete v3.0 archive, preserving the root `streamlit_app.py`. Run `python scripts/preflight.py`. Configure an externally maintained archived historical security master and terminal delisting payoffs if you need point-in-time audited backtests. See RELEASE_NOTES_v3.0.md for implementation and limitations.

# Deploy v2.9 (current release): accuracy-first model arena

**Use this section rather than the archived v2.5–v2.8 deployment notes below.** Unzip the complete archive directly into the root of the deployed GitHub repository (the folder containing `app.py`, `streamlit_app.py`, `requirements.txt`, `scripts/`, `ithaca_quant/` and `.github/`). Commit the entire application together; do not overwrite only the wrapper or dashboard file. The scheduled workflows now **require** this repository-root layout, instead of guessing from obsolete version strings. For a different repository layout, adapt the workflow paths yourself.

Install dependencies with `pip install -r requirements.txt`; run `python scripts/preflight.py` and `python -m pytest -q`. Deploy with `streamlit_app.py` as the Streamlit Community Cloud entrypoint. Back up the durable database before deploying: existing prediction tables undergo an `evidence_status` column migration. No actual trades are executed.

**Optional live evidence and weekly reports:** Supply the **same** persistent `ITHACA_DATABASE_URL` to Streamlit Secrets and GitHub Actions Secrets. Configure `ITHACA_REFRESH_TICKERS` (≥5 ticker symbols) in GitHub Actions. The scheduled daily forward-ledger worker runs **5:20 PM New York time Monday–Friday**, after the 5 PM completed-bar cutoff. The weekly reconciliation runs **5:45 PM New York time Friday**, processing every tracked ticker in batches. Friday reporting is saved to the persistent database, and optionally sent via configured SMTP secrets. Schedules can be delayed, and holidays/provider outages can prevent timely evidence. Without a durable database, no automatic true forward history will accumulate.

Real historical survivorship-free testing requires independently obtained archived dated membership, delisted stock price histories and actual returns. Without those, the backtest explicitly remains **unverified**. Per-stock model wins have only synthetic behavior-test evidence, **not** established live-market superiority.

---

## Archived deployment instructions from earlier releases (not current)

## v2.9 upgrade

Upload the **entire** v2.9 directory, including `ithaca_quant/model_tournament.py`, `ithaca_quant/point_in_time.py`, the updated dashboard, ledger and SQL migration code, and the tests. Deploying only `app.py` creates an inconsistent version. No additional ML packages are required for the three independently trained prediction models. Existing SQLite and PostgreSQL forecast tables are migrated automatically to add `evidence_status`; please back up persistent data before deployment. The new model arena performs additional fits, so allow more CPU resources than v2.8. You can reproduce earlier model output by invoking `forecast_asof(..., competitive_agents=False)` in a research script; the dashboard and scheduled daily logger enable the accuracy-gated contest by default.

# Deploy Ithaca Quant v2.5.5

**Keep your existing, working Streamlit Cloud main-file path.** Replace all the files in the GitHub directory holding your current `streamlit_app.py`, including the complete `ithaca_quant/` package. Do **not** create another wrapper folder or modify the deployment path unless you moved your repo files yourself. Commit on `main` and refresh the site. App code and package both report v2.5.5.

The new model and news/52-week code lives in `ithaca_quant/features.py`, `signals.py`, `leaderboard_review.py`, `trend_intelligence.py`, and `universe.py`, not the startup wrapper alone.

**Test offline:** `python scripts/preflight.py` then `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`.

Optional Google account login, SQL persistence, and screenshot OCR still require the setup described in `SETUP_SIGN_IN_AND_PHOTOS.md` and `packages.txt`.

**SEC Form 4 tab:** Add an administrator contact as `SEC_CONTACT_EMAIL` to Streamlit Secrets if not already configured. Form 4 uses the same SEC contact configuration as official quarterly financial filings. The tab fetches public filings only when you click its Check button; it will never fetch undisclosed trading information.


### Weekly Friday 4 PM report (v2.6)

Place `.github/workflows/ithaca-weekly-report.yml` in your **repository root**. This is especially important if the Streamlit app is inside a nested `Ithaca_Quant_...` folder. Use the SAME `ITHACA_DATABASE_URL` in GitHub Actions Secrets and Streamlit Secrets. Configure the SMTP secrets for automatic emails; without them reports are saved but not mailed. The workflow's working directory must point to your actual repo application directory. Default in this ZIP: repository root. If you keep your nested deployment, update GitHub Actions `pip install -r ...` and Python script paths to include that folder.

The two new workflows detect the v2.6 app folder automatically, including subfolder deployments. Install **both** `ithaca-daily-forecasts.yml` and `ithaca-weekly-report.yml` at the root `.github/workflows/` directory. To log new predictions while the browser is closed, set `ITHACA_REFRESH_TICKERS` (at least five ticker symbols) in GitHub Actions Secrets. Scheduled jobs require the database secret in both Streamlit Secrets and GitHub Actions Secrets; an installed workflow is not the same as an active notification subscription.


### v2.7.0 added Research Audit

Replace `app.py`, `streamlit_app.py`, and the entire `ithaca_quant` package
**together** in the same directory as your currently working Streamlit entrypoint.
Do not create another nested folder. Set the GitHub workflow files at the repo root
and use the v2.7 versions (they locate v2.7's package rather than the old v2.6).
New audit functions require no new API credentials or pip packages.
The Research Audit uses the *already computed* Walk-forward results, so run that first.

### v2.8.0 Model Zoo update

**Do not change the currently working Streamlit entrypoint path.** Replace the complete current application files, including both `app.py` and the inner `ithaca_quant` Python package. The root `streamlit_app.py` is unchanged in location. Both `app.py` and the inner package must report **2.8.0**; uploading a new `app.py` without its package will cause another mismatch.

Full-Market Dashboard → Accuracy Lab → Model Zoo for the stock-ranking research challenge. Per-stock Enhanced model comparison includes extra robust/nonlinear candidate families; the main model is retained if challengers fail its independent selection tests. **No extra installation** is required for the built-in models. For optional accelerated models, install from `requirements-optional-ml.txt` only if your hosting memory and operating environment support them.

Run `python scripts/preflight.py` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q` locally. Do not confuse tests of code execution with market forecasting accuracy.
