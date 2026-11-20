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

`OPENAI_API_KEY` is optional and needed only for screenshot import. It is not the ChatGPT app subscription; this requires separate API credentials and has usage charges. **Do not paste real keys in chats or GitHub.** Use your admin's account with permission to manage these services and billing; minors should have a parent/guardian or school administrator configure external provider accounts when applicable.

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

## 5. Traffic-light entry and exit signals (updated)

The **My Portfolio** holdings table uses Ithaca Quant's actual `plan_signals` entry/exit flags—not an independent score. Update the saved **20-trading-session** forecasts for all holdings to receive these colors. The screenshot reader imports verified purchases; it does not manufacture a bullish signal from a picture.

- **🟩 STRONG ENTRY WATCH (dark green):** new strictest *research* tier above green. Requires the actual ENTRY WATCH signal, a modeled > or equal to **+6% SPY-relative excess return** over 20 sessions, a modeled **gain probability ≥70%**, **annualized volatility ≤60%**, and (when a current weight is known) the position must be **≤15%** of portfolio equity. All forecast/quote freshness checks apply, and the saved exit signal must be MONITOR. The extra cutoffs are heuristic, not validated success probabilities. Missing model probability or volatility does **not** qualify for dark green.
- **🟢 ENTRY WATCH (green):** the standard confirmed entry condition. The predicted SPY-relative excess return must exceed +2%, both 20- and 60-day trends must be positive, and 20-day relative strength must be positive. Additionally, the saved model must be recent, the quote usable, no exit-review rule active, and the position must not exceed the portfolio's 25% concentration check.
- **🟡 WATCH / CONFIRM (yellow):** positive forecast and partial indicator confirmation, but not the strongest entry setup.
- **🟡 WAIT (yellow):** weak entry conditions; missing or stale forecasts, missing quotes, legacy saved forecasts without a stored entry flag, or oversized positions also remain yellow.
- **🔴 REVIEW EXIT (red):** the underlying exit rule triggers (20-day moving-average gap below -2% or forecast SPY-relative excess return below -2%), or a comparable current quote reaches the model's stored price-review level. Red overrides **both greens**. There is no automatic trade.

**Notes:** Dark green is only the strongest of *these screening conditions*, not proof that the stock is the best investment. These signals are research labels, **not validated buy/sell recommendations**. The entry flags don't measure the probability of making money, and the forecast is *relative to SPY*. Price-review thresholds should be checked manually against corporate actions and split adjustments. Existing saved forecasts need to be refreshed once to capture the new `entry_watch` field. The database upgrades the existing `iq_private_forecasts` table with a nullable `entry_watch` column and preserves all prior trades and forecasts.

## 6. What was and wasn't tested

The source and offline tests cover account-key isolation, screenshots with missing prices/dates, atomic trade imports, traffic lights, forecasts and deployment preflight. Actual Google OIDC login, PostgreSQL connectivity, image extraction with a real API key, browser rendering, and live quotes **require testing in your deployed environment**. The release does not connect to your brokerage or place orders.
