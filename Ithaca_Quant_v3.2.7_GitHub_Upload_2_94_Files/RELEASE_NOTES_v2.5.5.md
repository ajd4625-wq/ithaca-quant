# Ithaca Quant v2.5.5 — SEC Form 4 Insider Activity

## Overview
This release adds a separate **SEC Form 4 Insider Activity** research tab immediately to the **left of Ranked Leaderboard** in the Full-Market Dashboard. The app checks public SEC ownership filings, differentiates reported insider purchases and sales, and presents dated evidence with SEC-source links.

## 1. New tab
- Open **Full-market dashboard → 🧾 SEC Form 4 Insider Activity**.
- Select **Top 25 modeled stocks**, **All modeled stocks**, or **Custom tickers**. Set the number of symbols per batch (2, 5, or 10) and press **Check next companies for SEC Form 4 filings**.
- The new tab is positioned between **Search stock + news** and **Ranked leaderboard**. No change to Streamlit deployment entrypoint.
- Results are cached for 30 minutes on the app instance and retained across normal same-session interactions. Click **Recheck** for a fresh source attempt. Data is not silently assumed to be up to date after restart.

## 2. What a Form 4 report includes
The table presents ticker, reporting owner, insider role if reported, transaction code, shares, transaction price, calculated known dollar value, date of the trade, date of the SEC Atom feed publication/update (not necessarily official filing date), whether an amendment was detected, and a link to the SEC filing.

The initial parser includes **non-derivative P purchases** and **S sales** only. P can describe open-market **or private** purchases. It does not label option exercises (M), gifts, grants, or derivative transactions as standard share buys. With multiple reporting owners, the names may be combined rather than attributing each line to a particular owner; consult the source filing.

## 3. Evidence indicators, not buy/sell signals
- **Green:** one or more qualifying public purchases; multiple independent buyers are separately noted.
- **Yellow:** sale disclosures or a mix of buys and sales, requiring context.
- **Neutral:** no qualifying P or S found among the latest sampled filings and selected 7-, 30-, or 90-day publication window.

A sale may be scheduled under Rule 10b5-1, tied to diversification, or associated with tax and compensation considerations. **No sell instruction is generated automatically.** Insider records are not used to adjust the existing historically trained price model or to create new dark-green entry signals.

## 4. SEC data and access
The feature uses the SEC's public company ticker directory, issuer-specific EDGAR Atom ownership filings feed, archive file index, and ownership XML. It requires `SEC_CONTACT_EMAIL` in Streamlit Secrets or the environment for a declared User-Agent. Requests are deliberately throttled and performed only in batches after a user clicks; access may fail under fair-access rules or cloud hosting restrictions. A failing request is recorded as an error, not zero transactions. The app does not access material nonpublic information or trades before Form 4 publication.

## 5. Deployment and setup
Keep your existing working `streamlit_app.py` main-file path. Extract the ZIP and replace matching project files, especially `app.py`, `streamlit_app.py`, and all files in the `ithaca_quant` package. Include the new module `ithaca_quant/insider_form4.py`, tests and docs. Set SEC_CONTACT_EMAIL in Streamlit Secrets with a valid administrator contact address if needed. **Do not commit secret values to GitHub.**

## 6. Validation and limitations
Offline fixture tests check ownership XML, filtering, issuer identity, feed parsing, duplicate amendments, secure SEC URL selection, and buying/selling categorization. The test suite and preflight check confirm the repo structure and release consistency. However, these tests do not prove live EDGAR access from Streamlit Community Cloud, nor do they validate Form 4 activity as a prediction signal. Form 4 reports are typically disclosed after the trades and can arrive after market hours; the first version samples the latest five matching filings per requested company rather than comprehensive insider history. Transaction amendments changing shares or price may appear as separate records and require human reconciliation.
