# Ithaca Quant v2.5 — Set up Google sign-in, permanent holdings, and screenshot import

This release adds a **sign-in option**, not a preconfigured Google account. The app owner must activate an OIDC login provider and a PostgreSQL database. Until then, old recovery-code portfolios still work. Never place passwords, API keys, database URLs, or client secrets in GitHub source files.

## 1. Keep the deployment layout that already works

If your current GitHub release is located inside `Ithaca_Quant_v2.3_Rebuilt_Streamlit_Deployment/`, the easiest update is to **replace the contents of that existing folder** with the new ZIP's files. Keep your existing main-file path pointed to that folder's `streamlit_app.py`. Do not add another nested folder, and do not change the main-file path when replacing contents in place. Alternatively, deploy at repo root with `streamlit_app.py` as the entrypoint.

Upload **all files in the release** together: `streamlit_app.py`, `app.py`, `requirements.txt`, and the `ithaca_quant` package folder. The version label is v2.5.0 throughout. No individual upload of `app.py` by itself.

## 2. Configure Google sign-in

Use Google's OAuth consent and client configuration workflow to create a **Web application** client. In the provider's authorized redirect URIs, enter exactly:

`https://YOUR-APP.streamlit.app/oauth2callback`

If you are testing on your Mac, create a separate localhost redirect URI `http://localhost:8501/oauth2callback` and use local secrets. Streamlit's official authentication tutorial documents the detailed process: https://docs.streamlit.io/develop/tutorials/authentication/google

Open your deployed app in Streamlit Community Cloud > App settings > **Secrets** and enter the following TOML **with real private values**:

```toml
ITHACA_DATABASE_URL = "postgresql://DATABASE_USER:DATABASE_PASSWORD@DATABASE_HOST:5432/DATABASE_NAME?sslmode=require"
ITHACA_ACCOUNT_ID_SECRET = "LONG_RANDOM_SECRET_AT_LEAST_32_CHARACTERS_KEEP_FOREVER"
OPENAI_API_KEY = "YOUR_PRIVATE_OPENAI_API_KEY"

[auth]
redirect_uri = "https://YOUR-APP.streamlit.app/oauth2callback"
cookie_secret = "ANOTHER_LONG_RANDOM_COOKIE_SECRET"
client_id = "YOUR_GOOGLE_OAUTH_WEB_CLIENT_ID"
client_secret = "YOUR_GOOGLE_OAUTH_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
```

`OPENAI_API_KEY` is optional and needed only for enhanced AI screenshot reading. Free local OCR is supported with `packages.txt` and `pytesseract`. It is not the ChatGPT app subscription; this requires separate API credentials and has usage charges. **Do not paste real keys in chats or GitHub.** Use your admin's account with permission to manage these services and billing; minors should have a parent/guardian or school administrator configure external provider accounts when applicable.

**Important identity rule:** `ITHACA_ACCOUNT_ID_SECRET` controls stable mapping between your authenticated identity and its saved portfolio. Set it once and **keep it unchanged** when upgrading the app. If you rotate this secret, or change OAuth providers, the old account mapping will no longer find its previous portfolio automatically. Keep CSV transaction exports as backups.

## 3. Configure PostgreSQL for real cloud persistence

You need an authorized, persistent PostgreSQL service; `ITHACA_DATABASE_URL` must be reachable by Streamlit Cloud and its credentials must be private. If you do not configure it, holdings are stored in a *local SQLite file* which **can disappear** on Streamlit Cloud after an app restart, even if Google sign-in works. The release warns about this in the UI.

A new Google-signed-in account automatically creates a portfolio associated with the identity. No recovery code is displayed or needed on subsequent logins. Portfolios are not shared across Google users.

If you have transactions under an older recovery code, sign in, open **Move an older code-based portfolio**, and import them **once**. A previously exported CSV can also be imported in the ledger area. Avoid duplicate imports.

## 4. Import from a screenshot

1. Open **💼 My portfolio** (no whole-market scan).
2. Sign in with Google, if configured.
3. Expand **📷 Import holdings from a screenshot**.
4. Crop out personal details or account numbers before uploading. Supported: PNG/JPG/WebP under 8 MB.
5. Click **Analyze screenshot**. This sends the image to the configured OpenAI API vision model for extraction. The screenshot is not stored in the app's holdings database; network/API provider policies still apply.
6. Review the draft positions. **Fix share counts, original purchase prices, and purchase dates**. If the screenshot only shows the latest stock price, the tool leaves the purchase price blank; it will not pretend that is your cost basis.
7. Click **Confirm and save reviewed purchases** once. Nothing is saved automatically. An identical image cannot be imported twice into the same portfolio: its content fingerprint is stored in the database. A different screenshot with overlapping positions can still duplicate transactions, so review the ledger first.

The app computes cost basis, unrealized P/L, realized P/L on your entered sales, and remaining virtual cash based on the full transaction history. If an imported ticker already has recorded transactions, the app requires an extra explicit acknowledgment before adding trades. A snapshot of *current* holdings alone cannot reconstruct past sales or historic cash movement.

## 5. Entry/exit-based portfolio colors

The holdings table colors use the same **ENTRY WATCH, WATCH / CONFIRM, WAIT and REVIEW EXIT** rules as Ithaca Quant's stock analysis.

- **🟩 STRONG ENTRY WATCH (dark green)**: strictest *research* entry screen. Requires an existing ENTRY WATCH, forecast ≥+6% SPY-relative excess return over 20 sessions, modeled gain probability ≥70%, annualized 20-day volatility ≤60%, and holding weight ≤15% when available. All normal freshness checks still apply and the saved exit signal must be MONITOR. Missing probabilities or volatility don't qualify. These numerical cutoffs are heuristic, **not demonstrated prediction accuracy** or a buy instruction.
- **🟢 ENTRY WATCH**: fresh, usable 20-session forecast with SPY-relative forecast >+2%, positive 20- and 60-day trends and positive 20-day relative strength, with no red exit signal and no >25% portfolio concentration warning. This is a favorable *research entry screen*, not a buy instruction.
- **🟡 WATCH / CONFIRM / WAIT**: weaker or partly confirmed entry, or insufficient/stale data. Previously saved forecasts without `entry_watch` are yellow until updated.
- **🔴 REVIEW EXIT**: existing exit-review flag, forecast excess below −2%, or verified comparable price at or below the model's review level. This calls for investigation, not a mandatory sale.

Update all holdings' **20-session** forecasts after deployment to populate their stored entry labels. Red overrides both greens; portfolio loss alone does not change a color. The database migration adds a nullable column without erasing holdings. The labels are not validated to predict profit, and they do not place any trades.

## 6. What was and wasn't tested

The source and offline tests cover account-key isolation, screenshots with missing prices/dates, atomic trade imports, traffic lights, forecasts and deployment preflight. Actual Google OIDC login, PostgreSQL connectivity, image extraction with a real API key, browser rendering, and live quotes **require testing in your deployed environment**. The release does not connect to your brokerage or place orders.

## v2.5.2: screenshot import without OpenAI API access

- Upload the complete app folder including `packages.txt`; Streamlit Cloud installs the `tesseract-ocr` binary, while `requirements.txt` installs `pytesseract` and Pillow.
- Under My Portfolio → 📷 Import holdings from a screenshot, upload a PNG/JPEG/WebP under 8 MB and click **Read screenshot locally — no API key**. This is privacy-friendlier because it does not send the image to an AI API; local OCR quality varies substantially with screenshot layout, resolution and column structure.
- Check every extracted ticker and share count in the editable draft. Enter the original purchase/fill price and purchase date yourself. Neither current market price nor reported market value can be silently treated as purchase price.
- If OCR fails, use **Start a blank screenshot review row**, or enter trades manually. AI reading is an optional separate button when the admin provides the private API key.
- Important: uploading a screenshot does not directly log into a brokerage or retrieve transactions; the screenshot can omit historical sales. The app treats confirmed imported rows as purchases, and an image content hash prevents reimporting that exact image into the same portfolio.
