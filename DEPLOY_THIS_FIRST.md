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
