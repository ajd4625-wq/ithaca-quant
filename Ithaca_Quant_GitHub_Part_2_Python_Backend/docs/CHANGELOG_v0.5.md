# v0.5 implementation and test record

## Applied from the supplied v3.1 model

- Refreshed the entire upstream Python model/data package, including historical security-master identity, archive SHA-256 and safe filenames, raw/adjusted price separation, SEC filing-vintage features, future-label and delisting payoff corrections, model tournament code, feature generation and data-health behavior.
- Kept Chrome extension v0.4's three fitted agent pipeline and two provider retries.
- Added `historical_research.py` for the *same three fitted ML models* evaluated on source-declared dated membership snapshots. All eligible members must be observed or supplied with valid terminal outcomes. No current Yahoo survivor universe can fill missing archive bars.
- Added opt-in audit and status endpoints and a Chrome side panel archive-quality section; single audit worker and separate research output CSV/JSON.
- Preserved unknown volume as missing (including around forecasting and early-trend checks), and rejected stale ticker feeds rather than treating a recently updated benchmark as evidence the ticker is current.
- Isolated new forward accuracy database for v3.1; no copying/rescoring older release predictions.

## Technical caveats

- Neither the uploaded source code nor this extension package contains licensed/authenticated all-market delisted-stock history. Hashing cannot validate the truth of the original source.
- This release does **not** train on independently archived SEC, contemporaneous articles, or actual insider transactions for normal Chrome predictions.
- Live Chrome extension installation, vendor Yahoo/SEC responses, and prospective five-session directional accuracy still require observation on the user's machine.
- Upstream Streamlit UI is not bundled, only the current v3.1 backend research modules; Streamlit-only packages are excluded to keep the extension lightweight.
- The previous v0.4 PIT CSV scripts remain explicitly legacy; v3.1 ZIP workflow is preferable for new archives.
