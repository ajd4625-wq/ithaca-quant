# GitHub deployment — v3.2.7

Two ZIP packages contain **fewer than 100 files each** and together recreate one
complete repository tree. They are upload batches, **not** separate apps.

1. Extract Upload 1 and Upload 2 separately on your computer.
2. In the existing GitHub repository, upload the **contents** of Upload 1,
   preserving nested paths (`ithaca_quant/`, `scripts/`, `.github/`). Commit.
3. Upload the **contents** of Upload 2 into **the same repository root**. Commit.
4. Ensure `app.py`, `streamlit_app.py`, and `requirements.txt` are all replaced.
5. Reboot the deployed Streamlit app; its header should display **v3.2.7**.
6. In Full-market dashboard → Ranked leaderboard, click
   **Run bounded historical preview**. The browser will not attempt a
   full-universe model competition.

**Do not upload ZIPs as ZIP files** expecting Streamlit to read the code inside.
**Do not upload secrets, raw private data, or local history caches.**

The two batches have disjoint relative paths, include all original v3.2.6
release files, and add cloud-resource safeguards and regression tests.

A verified historical-market edge requires an actual point-in-time universe
and enough forward-market observations. Browser preview results are very
limited and marked exploratory.
