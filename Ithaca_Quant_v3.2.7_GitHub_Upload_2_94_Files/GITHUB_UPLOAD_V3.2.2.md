# Install Ithaca Quant v3.2.2 from two GitHub upload packages

1. Download and extract both ZIP packages to separate local folders.
2. Open your **existing** Ithaca Quant GitHub repository on the deployed branch.
3. Use **Add file → Upload files** to upload the **extracted contents** of Part 1, keeping the `ithaca_quant/` directory and the Python files in the repository root. Commit replacements.
4. Upload the **extracted contents** of Part 2 to the **same repository root**, preserving `.github/workflows/`, `scripts/`, `tests/` and all `.md` documents. Commit replacements. Do **not** upload the ZIPs as unopened files.
5. Open Streamlit Community Cloud and verify the application points to `streamlit_app.py`. Restart/redeploy it if necessary, and verify the heading says `v3.2.2`.
6. Check the repository **Actions** tab for the new preflight-and-regression workflow, or run `python scripts/preflight.py` and `python -m pytest -q` locally.

For the first Yahoo refresh after upgrading, the app may reacquire all historical prices rather than reuse cached bars without raw/trading close data. A provider failure must not produce invented prices; a stale cache warning may appear instead.

Never upload database passwords, API keys, `.env` files, `.streamlit/secrets.toml`, or portfolio records into a public GitHub repository. Existing portfolio data should be backed up before changing hosting configuration.

The two ZIPs must be **merged into one repository**, not deployed as two independent Streamlit apps.
