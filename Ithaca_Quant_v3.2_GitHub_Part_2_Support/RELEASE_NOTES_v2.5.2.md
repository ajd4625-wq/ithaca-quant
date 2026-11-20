# Ithaca Quant 2.5.2 — Every change explained

Release date: November 19, 2026. This is a code release; do not assume it is deployed until you upload all files into the already-working GitHub app folder.

## 1. Separate entry and exit conditions, now both color-coded

Each modeled leaderboard row shows **Entry signal**, **Entry conditions**, **Exit signal**, **Exit conditions**, **Exit review level ($)** and distance from that review level. Green exit = no model review condition; yellow = caution, missing data or near review level; red = model exit-review trigger or reached adjusted review level. Entry uses dark green/green/yellow/red. A red exit screen takes precedence over a green entry screen. These are transparent research screens, not proven sell instructions. The **Exit review queue** is expandable and lists every yellow/red case.

## 2. Stronger acquisition / already-priced-in protection

A model may favor a stock because of its impressive recent momentum even after a deal announcement. This app now checks 5-, 20-, and 60-session run-ups relative to SPY for every modeled candidate. A dated acquisition-related headline can lower entry priority when the company's closing price has risen ≥7% since the previous pre-announcement close and outperformed SPY by ≥5 percentage points. A deal headline without sufficient future closes is still yellow pending review. A large rally without an acquisition headline can also downgrade green to yellow to flag chasing risk. This does not claim the acquisition is fully priced in or that the stock cannot rise further. Original ML predictions and research scores remain visible and unchanged. The default entry-readiness order puts green/dark green ahead of ordinary yellow, then acquisition/price-chase yellow, and red last. Acquisition/possible-deal warnings have an entry-priority maximum of 20/100; other price-extension warnings have a maximum of 35/100. These caps are human-readable risk-screening heuristics, not measured expected returns.

## 3. No additional news-fetch click

The leaderboard automatically retrieves publisher-indexed Google News RSS headlines for the first 12 model-ranked stocks, with up to 3 publisher feeds per ticker, using a 15-minute cache. Acquisition lookup requests go back 45 calendar days; the displayed news-tone summary uses dated headlines from the past seven days. The actual headline, source link, count and sentiment are inserted into the table. Stocks beyond the capped automatically checked subset, and stocks whose news feed is unavailable, are marked unverified and not assigned premium green entry status. Public news search can miss stories and doesn't validate a merger, split, corporate action or future returns. To avoid overwhelming Streamlit and public news providers, the app deliberately does not send thousands of per-stock news requests during a marketwide scan.

## 4. Screenshot holdings import repaired, with a free local option

Before v2.5.2, screenshot extraction depended on a configured OpenAI API key. Now a local **Read screenshot locally — no API key** option uses the server's installed Tesseract OCR engine, accessed via Pillow and pytesseract. The new `packages.txt` tells Streamlit Cloud to install the Tesseract binary, while `requirements.txt` installs its Python wrappers. The screenshot importer creates an editable holdings draft. It extracts possible symbols and share counts only when OCR finds a clear quantity header; it leaves cost basis and dates blank rather than confusing the current price with the purchase price. You must verify and correct every row before confirming a purchase. If OCR cannot read a screenshot, use the blank review row or the existing manual trade form. Optional OpenAI AI Vision extraction remains available when an admin configures OPENAI_API_KEY. A transaction cannot be saved with missing/invalid share count, cost basis or date, and repeated uploads of identical screenshot content to the same account are blocked by a database fingerprint.

## 5. Existing features preserved

- Full NYSE/Nasdaq screener, model forecasts, charts, risk estimation, research lab and validation.
- Saved holdings, multiple purchases and sales, portfolio news, and separate individual-stock forecasts.
- Optional Google OAuth account sign-in and PostgreSQL durable persistence; these still require independent setup and credentials.
- Streamlit entrypoint: **do not change the working path**. Replace the files in your currently working app folder, do not nest the extracted folder again.

## 6. Validation limits

Python syntax checks and offline tests validate the new logic, but real Streamlit Cloud startup, actual publisher feeds, Tesseract installation and third-party credentials have to be checked on the deployed site. New run-up and deal-risk thresholds are unvalidated screens, not claimed statistical gains. The app uses an illustrative news sentiment score; it is not evidence of profitable trades. These changes do not alter the underlying ML forecasts.
