# Ithaca Quant v2.5.1 — Leaderboard Colors & Priced-In Acquisition Screening

**Released:** November 18, 2026  
**Type:** Dashboard research-screening update; no change to trained return models.  
**Streamlit startup:** `streamlit_app.py` in your currently working application directory.

## 1. Why the leaderboard previously had no colors

v2.5.0 applied dark green, green, yellow and red traffic lights to the **My Portfolio** holdings table only. The separately rendered **🏆 Ranked stock leaderboard** still used the older, plain `st.dataframe` view. Version 2.5.1 connects the underlying `portfolio_lights.classify_holding` decision logic to **each modeled leaderboard row** and shades the **Entry signal** column with the appropriate background colors. It also shows a plain-language **Why this color** explanation for every stock.

- **Dark green / STRONG ENTRY WATCH**: The existing `ENTRY WATCH` condition is satisfied, modeled SPY-relative excess return at 20 sessions is at least 6%, modeled gain probability at least 70%, and annualized historical volatility no higher than 60%. This is the strictest *unvalidated screen*, not a measured 70% chance of success. Portfolio concentration may further limit dark-green eligibility in My Portfolio; a full-market list has no ownership information.
- **Green / ENTRY WATCH**: Positive SPY-relative model output (over +2%), positive 20- and 60-session moving-average gaps, positive 20-session relative strength, with no triggered exit warning or chase guard.
- **Yellow**: `WATCH / CONFIRM`, `WAIT`, missing or outdated model evidence, `AVOID CHASING`, or `VERIFY DEAL REACTION`. These are not automatic sell signals.
- **Red / REVIEW EXIT**: The original exit-review condition, a strongly negative SPY-relative forecast, or a compatible model review-level breach. Red is never overridden by a favorable headline or forecast.

**Important:** On horizons other than 20 sessions, the program does not award the special dark-green color using a 5d or 60d forecast. All labels are conditional research prompts, not execution signals.

## 2. All-stock five-session run-up check

The leaderboard uses locally stored **completed daily adjusted closing prices** for all the already modeled stocks. It computes:

- Five-session stock return = latest completed close / close five completed sessions earlier − 1.
- Five-session market-adjusted movement = that return − SPY's return over the same dates.

If **both** the stock return is at least +15% and the stock exceeds SPY by at least +10 percentage points, the stock gets an `AVOID CHASING` warning. Green/dark-green entries become yellow, but existing red warnings stay red. The check is unavailable—not inferred—if any of the required six daily price observations is missing. A large previous gain can precede further gains; this guard is deliberately conservative and has **not** been validated as a predictor of price reversal.

## 3. Acquisition headline screening (opt-in)

A button on the leaderboard, **Check acquisition headlines for top 10 stocks**, fetches recent dated results from the existing public Yahoo Finance, Fox Business and ABC News-indexed Google News RSS search. It does **not** query thousands of stocks automatically, to avoid traffic spikes and provider rate limits. Existing news caching is reused.

The guard requires a source URL, dated article, publisher, a plausible acquisition/merger/takeover headline, and a ticker or company-name match. It excludes obviously speculative headlines such as rumors and generic takeover speculation. This remains **headline matching, not verification of a signed transaction**. The table includes a clickable source URL and headline for manual verification.

For a possible acquisition, the program checks the price change from the last available close **before the announcement date** to the latest eligible completed daily close **after** that date. A risk flag requires BOTH:

- Stock return since that earlier close of **at least +10%**, AND
- Return above SPY over the same interval of **at least +8 percentage points**.

The entry label becomes `AVOID CHASING` (yellow) instead of dark green/green when those conditions hold. A headline from the current day cannot claim that prices have reacted until a *later completed session* is available. While waiting, a would-be green entry may show `VERIFY DEAL REACTION` in yellow. **No article found** and **not checked** are different statuses. Requests that fail are reported as feed errors rather than falsely presented as clean screens.

Announcements can cause repricing that continues for weeks or months; this guard does not claim that acquisition-driven returns are over or predict an exact ceiling. Historical testing of these thresholds remains needed.

## 4. Separate entry-priority ranking and original model ranking

The **Prioritize entry readiness** checkbox is on by default. It sorts the current *filtered modeled shortlist* by an explicitly heuristic entry-priority score while retaining its original model rank:

| Condition | Entry-priority deduction |
|---|---:|
| No eligible recent run-up | 0 points |
| Large five-session run-up (+15% stock, +10pp vs SPY) | 15 points |
| Possible acquisition headline followed by qualifying post-event jump | 35 points (instead of 15) |

The deductions are not cumulative. Entry priority is clamped to a minimum of zero. Turn the checkbox off to display the original research-ranking order. Columns `Model rank`, `Research score /100`, `Entry priority /100`, `Forecast vs SPY`, and `Why this color` all remain visible. The optional overlay **never changes forecasts, historical validation outcomes, or trained weights**. Research scores, probability estimates, and the new entry-priority score are distinct quantities and should not be confused.

## 5. Full-market performance and data consistency

- No full-market scan is triggered by the visual color enhancement: it runs on the stocks that are already loaded and modeled.
- Daily history is converted to model-as-of sessions and prepared **once for the entire shortlist**, not once per ticker. The five-session window uses exactly six dates with valid stock and SPY prices.
- News checks run **only on button click**, up to 10 selected tickers per click. Sites may block or delay access, and coverage is incomplete.
- No future-dated headlines or post-as-of price observations are allowed in the current evaluation.
- Company news and price levels may be delayed or split-adjusted; confirm official disclosures and executable prices independently.
- Color fills and new columns are included in the dashboard table; raw numerical scores and source links are exported to `ithaca_ranked_stock_leaderboard.csv`.

## 6. Files changed

- `app.py`: leaderboard signal calculation, color-filled table, optional acquisition fetch, entry-priority sorting, visible caveats and export.
- `ithaca_quant/leaderboard_review.py`: new, independently testable point-in-time price/news screening engine.
- `ithaca_quant/leaderboard.py`: new display columns, including the original model rank and deal source.
- `ithaca_quant/__init__.py`, `streamlit_app.py`: matching v2.5.1 version labels.
- `tests/test_v251_leaderboard_catalysts.py`: deterministic tests for light levels, missing data, deal relevance, price reactions, chronological safeguards and baseline-model preservation.
- `CHANGELOG.md`, `README.md`, `DEPLOY_THIS_FIRST.md`, and this file: release documentation.

## 7. Deploy without changing the working Streamlit URL

1. **Keep a backup** of your currently functioning repository and exported portfolio transactions. Do not remove your PostgreSQL records or Streamlit Secrets.
2. Extract the ZIP and replace the contents of the **same working GitHub application folder** that already contains `streamlit_app.py` and `app.py`. Include the entire `ithaca_quant` package folder. Do **not** add an extra named parent folder.
3. Keep your current Streamlit entrypoint path. If it was `Ithaca_Quant_v2.3_Rebuilt_Streamlit_Deployment/streamlit_app.py`, it remains that exact path. If you deploy from repository root, use `streamlit_app.py`.
4. Commit your changes to `main`. Streamlit will usually redeploy automatically; reboot if needed.
5. Open **Full-market dashboard → Ranked leaderboard**. The entry colors now appear directly in the table. Click the optional acquisition-headline button to check the first ten names on that leaderboard before interpreting deal risk.
6. Optional smoke test on your computer: `python scripts/preflight.py`; then `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`.

## 8. Testing and limitations

Offline regression tests and ZIP integrity can verify Python behavior and release layout but **cannot prove** live Yahoo/Google News availability, official event timing, model profit accuracy, or reliable cloud startup with your particular credentials. The new numeric thresholds are **educational judgment screens**, not a historically trained discovery of post-acquisition alpha. They should be formally backtested and evaluated in forward tracking before anyone relies on them as an edge.

The v2.5 Google sign-in, screenshot import, persistent PostgreSQL option, portfolio accounting, entry/exit signals, six stock-chart ranges, full-market scanning, virtual-portfolio rules and existing forecasting models remain unchanged.
