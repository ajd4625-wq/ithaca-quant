# Ithaca Quant v1.4.2 — Streamlit ImportError Repair

Released November 12, 2026. This is a **deployment/startup reliability** patch built on v1.4.1. Forecast features and their numerical calculations are unchanged.

## 1. Why the site crashed

The Streamlit screenshot shows a Python `ImportError` while executing `ithaca_quant/app.py` line 39, the import from `ithaca_quant.explorer`. The error text was redacted by Streamlit, so the exact missing name cannot be confirmed from the screenshot alone. There is a known cross-release incompatibility: v1.4.1 `app.py` imports `select_1d_display_window`, while v1.4 `ithaca_quant/explorer.py` does not export that function. This specific mismatch is consistent with a partial GitHub upload and the line shown in the screenshot.

## 2. What is fixed

- **Consistent release tree:** the ZIP includes `app.py`, the inner `ithaca_quant/explorer.py`, `ithaca_quant/presentation.py`, and `ithaca_quant/__init__.py` from the same release. They are required together.
- **Early compatibility gate:** before importing the rest of the app's feature modules, the dashboard checks that the version in `app.py` equals the inner package `__version__`. A mismatch produces a human-readable explanation, including the exact GitHub folder to replace, rather than proceeding into a likely cryptic error.
- **Safer chart import:** if the chart or formatting import still fails, the app catches the `ImportError` and prints a specific, sanitized instruction for uploading the complete package and checking dependencies. A broken import is not silently ignored.
- **Regression tests:** the release tests verify that the app imports only symbols exposed by the corresponding package modules and that the preflight runs before the vulnerable import.

## 3. Install instructions (important: folder nesting)

The repository should look like this:

```
ithaca-quant/                 ← GitHub repo root
└── ithaca_quant/             ← existing app directory
    ├── app.py               ← v1.4.2
    ├── requirements.txt
    ├── ithaca_quant/        ← inner Python package
    │   ├── __init__.py      ← __version__ = "1.4.2"
    │   ├── explorer.py      ← includes select_1d_display_window
    │   ├── presentation.py  ← includes format_financial_table
    │   └── ... other code
    └── tests/
```

1. Download and unzip `Ithaca_Quant_v1.4.2_Streamlit_Import_Fix.zip`.
2. In GitHub, open `ajd4625-wq/ithaca-quant` on `main`. Replace the **contents** of the existing `ithaca_quant` app directory using the ZIP's `ithaca_quant` directory. **Do not create another extra folder level**. In particular, replace *both* `ithaca_quant/app.py` and `ithaca_quant/ithaca_quant/explorer.py`, not only the main app.
3. Verify `ithaca_quant/ithaca_quant/__init__.py` contains `__version__ = "1.4.2"` and `explorer.py` contains `def select_1d_display_window`.
4. Commit changes to `main`. Confirm Streamlit Cloud is configured with main file `ithaca_quant/app.py` and branch `main`.
5. Reboot the Streamlit app if it does not redeploy. Note that cloud reboots may discard locally cached market-scan SQLite files; full stock-history reconstruction may be necessary if cloud storage was ephemeral.
6. Verify the header reads **Ithaca Quant v1.4.2** and that the instant explorer and full-market dashboard open.

## 4. Preserved features

The fixed 8:30 AM–4 PM ET 1D axis, next-session daily ML forecast, commas in quarterly reporting, SEC filing/news evidence gates, universe incremental refresh, risk tables, virtual portfolio, and chart history ranges remain available. No calculation, model training, or accuracy claims have been changed.

## 5. Testing and limitations

The ZIP is checked for integrity; Python source is compiled; the offline test suite and the new cross-version import-compatibility regression tests are run: **91 tests passed**. The environment lacks Streamlit/yfinance and live Yahoo/SEC access, so the actual Streamlit Cloud startup must still be checked after deployment. This patch repairs the **known mixed-file condition** and produces clearer diagnostics for other missing imports; the screenshot alone cannot prove which file is stale.
