# GitHub upload instructions — Ithaca Quant v3.2.4

1. Download both ZIP parts.
2. **Extract them locally** and upload their *contents* to the same GitHub repository root. Do **not** upload two ZIP files into the repo and expect GitHub/Streamlit to run their contents.
3. Preserve all paths, including hidden `.github/workflows/ithaca-ci.yml`, `.gitignore`, the `ithaca_quant/` package, `scripts/`, `tests/`, and root `streamlit_app.py`.
4. Commit to the branch used by the Streamlit deployment and restart the app. The release should display **v3.2.4**.
5. **Do not upload** `private_vendor/`, raw exports, historical archive ZIPs, real settlement CSVs, API keys, or `.streamlit/secrets.toml`. The repo has ignore patterns for these private assets; do not override them.

### Licensed source data are separate from GitHub

No historical vendor files are in these ZIPs. A licensed subscription or authorized export and verified settlement evidence are still required. The server running the Streamlit app must be able to read the private files. Setting `ITHACA_HISTORICAL_ARCHIVE_PATH` on a remote Streamlit instance to a location on your Mac will not work. If you cannot mount private archives on your deployment, the app will continue with an explicitly **unverified Yahoo-only historical training mode**.

See `HISTORICAL_PRODUCTION_GUIDE_v3.2.4.md` for the setup, data-readiness checks, and safe terminal-return import.
