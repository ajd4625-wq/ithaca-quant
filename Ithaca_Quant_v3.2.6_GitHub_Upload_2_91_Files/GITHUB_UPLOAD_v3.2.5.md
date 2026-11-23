# GitHub two-part installation — v3.2.5

1. Download **both** ZIPs and extract them locally.
2. Open your GitHub repository, choose **Add file → Upload files**.
3. Upload the extracted files from Part 1 into the repository root.
4. Upload the extracted files from Part 2 into the **same repository root**, preserving `.github/workflows/` and `tests/`.
5. Commit and redeploy Streamlit using `streamlit_app.py`. Do **not** upload the ZIPs directly; GitHub does not extract them into source files.
6. Verify the application displays v3.2.5 and GitHub Actions tests pass.

Nothing in the ZIPs includes live Yahoo/SEC downloads, licensing records, or passwords. Optional private Yahoo+SEC cache path and `SEC_CONTACT_EMAIL` setup: `FREE_HISTORICAL_DATA_v3.2.5.md`. Set SEC email privately in Streamlit Secrets. `ITHACA_FREE_HISTORY_DIR` only works on hosts with a persistent private filesystem; omit on ephemeral Streamlit Cloud to use direct Yahoo plus optional SEC.
