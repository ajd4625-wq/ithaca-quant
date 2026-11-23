# Upload v3.2.1 to GitHub — both parts

1. Download Part 1 and Part 2 and extract each archive.
2. Open your repository on GitHub and upload **the extracted files and folders**, not the ZIPs.
3. Put BOTH parts into the same repository root. Keep `app.py` and `streamlit_app.py` alongside `requirements.txt` and the `ithaca_quant/` directory. GitHub Actions belongs inside `.github/workflows/`.
4. Confirm GitHub shows the latest `app.py` and `ithaca_quant/__init__.py` with version `3.2.1`.
5. Commit to the branch Streamlit Cloud deploys. Refresh or reboot Streamlit.
6. In Research settings, the 'Use enhanced research lab INSTEAD of three-model tournament' checkbox should now be **off**. The three-model tournament is the default. Test an individual-stock forecast.

If forecasts still fail with a different message, check Streamlit logs for provider throttling, insufficient stock history, or missing SPY data. The two engines must never promote simultaneously.

Verify locally with `python scripts/preflight.py` and `python -m pytest -q tests/test_v321_forecasting_mode.py`.
