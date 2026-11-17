# Ithaca Quant v2.3 — clean deployment (read this first)

This rebuilt ZIP is **ready to upload at the GitHub repository root**. Do **not** nest it inside any `ithaca_quant` or `ithaca_quant_old16` folder.

## What changed

- `streamlit_app.py` is the **single canonical cloud startup file**. It runs the existing `app.py` and, when an ordinary Python exception occurs during startup, shows a safe, useful error message and traceback locations.
- Original full dashboard lives in `app.py`. Its displayed version remains **2.3.0**.
- `ithaca_quant/__init__.py` also reports **2.3.0**. The package includes the portfolio, news, chart, forecasting, accuracy and scanner modules.
- `requirements.txt` is at the repository root so Streamlit sees the third-party dependencies.
- `scripts/preflight.py` checks the layout and version numbers before deployment.
- All source code and tests are present **once**. No double nested app folders.

## Install in GitHub (recommended)

1. Extract this ZIP to an empty folder on your Mac.
2. Open https://github.com/ajd4625-wq/ithaca-quant and choose the `main` branch.
3. At the **repository root**, use **Add file > Upload files**, and drag the **contents of the extracted ZIP** (not the containing folder) to GitHub. Make sure the pending file list includes `streamlit_app.py`, `app.py`, `requirements.txt`, and `ithaca_quant/__init__.py`. Commit them.
4. Keep `ithaca_quant_old16` as a backup for now, but do not use it as the Streamlit entrypoint.
5. In Streamlit Community Cloud, deploy the repository **`ajd4625-wq/ithaca-quant`**, branch **`main`**, main file path exactly **`streamlit_app.py`**.
   - If the existing deployment is permanently tied to an obsolete main file path, create a new deployment with this path instead of repeatedly changing package labels. You can choose an available app URL in the deployment flow.
6. Open the app. It should display **Ithaca Quant v2.3.0** and provide the original 3 workspaces: Instant Stock Explorer, My Portfolio, and Full-Market Dashboard.

### Repository layout

```
ithaca-quant/                 (GitHub repository root)
├── streamlit_app.py         <-- Streamlit Cloud MAIN FILE
├── app.py                   <-- existing full dashboard
├── requirements.txt         <-- dependencies
├── ithaca_quant/            <-- Python package, ONE nested folder
│   ├── __init__.py          <-- version 2.3.0
│   ├── holdings.py
│   ├── portfolio_workspace.py
│   ├── explorer.py
│   └── ...
├── scripts/
├── tests/
└── ithaca_quant_old16/      <-- previous backup; optional
```

Run `python scripts/preflight.py` to verify the download before deployment. For local use after installing dependencies, run `streamlit run streamlit_app.py` from this directory.

## If the website still displays "Oh no"

Click **Manage app > Logs**, locate the first Python error, and share the log text with any access codes, tokens, or database URLs removed. A generic "Oh no" screen alone does not identify the cause. Errors that stop Streamlit before Python starts (bad main-file path, dependency build error, exhausted cloud resources) cannot be repaired by a Python startup wrapper.

## Persistence

Local SQLite can retain holdings while the app remains on the same machine, but **Cloud restarts can erase locally saved holdings**. For reliable persistence between cloud restarts, configure `ITHACA_DATABASE_URL` in Streamlit Secrets with a PostgreSQL database. Keep portfolio recovery codes private and export CSV backups.

## Accuracy

The app includes research-oriented forecasts and news context. Those estimates are not guarantees; news only enters numerical models when the historical evidence requirements are met. This release repairs deployment layout, not forecasting quality.
