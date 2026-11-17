# Ithaca Quant v1.3.0 — Detailed Update Notes

**Release scope:** Real-world headline breakdowns, optional generative-AI source interpretation, bounded **news-sensitivity** price/probability scenarios, and an intraday chart that starts at the first real price timestamp. This is an educational paper-trading research tool, **not** a demonstrated news-trained price-prediction model.

## Every change, in detail

### 1. Automatic ticker-specific news lookup

When you search a ticker at the top, the instant explorer now attempts to retrieve recent attributed financial headlines as part of that single-ticker lookup. The scan of the entire NYSE/Nasdaq universe is **not** required. News requests are cached for **15 minutes**. The search fetches relevant results indexed from Yahoo Finance, Fox Business and ABC News through public Google News RSS search results. These sources are not guaranteed to have an article for every stock, nor does the app hold a publisher content license.

**How to use:** Type a ticker, choose a chart period, and scroll to **News explanation for every estimate**. The page lists source, timestamp in UTC, headline language, a relevance warning, and a link to the original reporting. A missing headline or failed source produces an explicit warning, never fabricated coverage.

### 2. Deduplication, freshness and ticker relevance

The analysis excludes headlines lacking a verifiable date or HTTPS link, headlines older than seven days, and headlines dated in the future. Duplicates with identical normalized headlines are counted once. Headlines explicitly naming the searched ticker or company are weighted more heavily; broad unmatched results are marked "weak ticker relevance" and down-weighted. Language polarity is a transparent positive/negative keyword heuristic, using age-based weighting and the number of distinct publishers. Headlines do not equal complete articles and can be misleading.

### 3. A bounded daily news sensitivity on price projections

The underlying machine-learning forecast remains an **SPY-relative** expected excess return based on historical price/volume features. The new news layer computes a separate *scenario* adjustment, not a fitted historical news coefficient. A 20-trading-session scenario can change the underlying model forecast by at most **±1.2 percentage points**; other supported horizons scale approximately with the square root of the session count and are capped at **±1.5 percentage points**.

For each selected stock the explorer shows the **base model forecast**, the **news adjustment**, and the **combined hypothetical scenario**. The dotted price endpoint for daily views is based on the combined scenario when current qualifying news is available. Absolute-price illustrations still assume 0% future SPY return; no path between endpoints is predicted. If no news qualifies, the adjustment is **exactly zero**.

**Limits:** These adjustment limits are design choices for analysis stability, **not** empirically validated effects of news on prices. A news-adjusted scenario is not evidence of forecasting skill.

### 4. Boom probability: baseline and news scenario are separate

The original boom estimate from the existing model is still displayed without alteration. An additional news sensitivity number shows how the estimate might move under a simple bounded approximation using headline shift, baseline boom probability and estimated historical volatility. It is explicitly labeled a **scenario**, not a calibrated probability. If no baseline event estimate exists, neither does a news-adjusted one.

**Read this carefully:** If the scenario shows 25%, it does **not** mean a validated one-in-four chance. The correct test would require timestamped historical news and a clean independent chronological holdout, which this version does not yet have.

### 5. Volatility/risk and entry/exit review dates

Historical volatility remains unchanged, because today's headline words do not change the observed historical price data. A separate illustrative headline-stress scale adds a modest shock sensitivity to the historical one-sigma range; it is **not** a worst-case loss estimate, confidence interval, stop-loss, or position recommendation. Technical entry/exit labels are still watch/review conditions, not scientifically predicted optimal buy/sell dates.

### 6. 1D intraday news scenario, separate from daily ML

For 1D only, the short-term dotted endpoint continues to come from the heavily shrunk intraday momentum heuristic. Headlines may shift that endpoint by at most **±0.2%**, and **only if published today in U.S. Eastern time**. Headlines from yesterday do not alter today's intraday projection. If the intraday data is stale, insufficient, or outside market hours, there is no hourly projection; the news layer cannot invent one.

### 7. The 1D chart starts exactly when price data starts

Previously the horizontal axis ran from 12:00 a.m. to 11:59 p.m. for the selected day, leaving a large empty portion before regular trading began. Now the left axis boundary equals the timestamp of the **first actually observed price bar for today**. The right boundary is the **last actual bar or same-day forecast endpoint**, if one exists. It never extends into tomorrow. The hover tooltip still displays exact Eastern time; x-axis labels now use hourly ticks.

This change **does not** add artificial pre-market data or show yesterday as today. After a market holiday, with no eligible current-session observations, the 1D chart remains empty rather than inventing prices.

### 8. Optional generative AI to interpret real headlines

An app owner may configure a server-side `OPENAI_API_KEY` in Streamlit Community Cloud's Secrets panel. A **Generate optional AI news explanation** button then requests a source-numbered narrative (drivers, possible upside, downside, missing context, and caveats) from an OpenAI model. The model is only shown recent **headlines and publisher/date labels**, not full articles. It is instructed not to follow commands embedded in headlines, infer unseen facts or generate trade recommendations.

This feature is **off without a key**, and a call may incur an API charge. Never upload a real API key into GitHub or expose it in front-end code. LLM prose does **not** determine numerical news adjustments. Without a key, the entire deterministic news/evidence panel still works.

### 9. Top-five news scenario view on the leaderboard

The previous optional leaderboard adjustment of just a research score has been replaced with a table showing base AI excess return, news-sensitivity adjustment, combined scenario, base boom estimate, news-adjusted boom scenario, and historical versus illustrative stress risk. Press **Analyze top five with current news** on the leaderboard to run the comparisons. The table clearly ranks **only the five fetched stocks**, not the whole market universe. You can export its figures to CSV. A broad 600-stock scan does **not** automatically fetch the article feeds for all 600 names, preventing long waits and provider rate-limit pressure.

### 10. Existing performance and limits preserved

- The instant search still models one ticker plus SPY without a broad scan.
- The original historical price-data ML models, walk-forward tests, stock watchlist, Yahoo metadata, virtual portfolio and ranking modes remain available.
- The original three score components are **Forecast, Momentum, Risk**; the headline overlay is not a fourth research-scoring agent.
- Market/news service calls respect at most **three parallel worker threads** at the application level and at most **two retries per failed call** (three total attempts). Third-party libraries may have their own internal retry behavior.
- Current headlines are *never fed into a backtest of historical dates*; doing so would invalidate the results through look-ahead bias.

## Installation and publishing

**Mac:** Stop the old process with Control+C, unzip the new release into `~/Downloads/ithaca_quant`, then run `cd ~/Downloads/ithaca_quant` followed by `bash start_mac.command` in Terminal. Open `http://localhost:8501`.

**Shared Streamlit app:** In your existing GitHub repo, replace the files **inside** the `ithaca_quant/` folder with the contents of the new extracted folder. Keep `ithaca_quant/app.py` as the Streamlit entry point if your repo still has that layout. After committing, allow Streamlit Cloud to redeploy.

**Optional server-side AI key:** In Streamlit Community Cloud's App Settings > Secrets, add (without pasting this in GitHub):

```toml
OPENAI_API_KEY = "your-own-server-side-api-key"
```

API use is optional and may cost money. If the secret is absent, the program uses the free transparent headline analyzer.

## Verification and limitations

Tests run **offline** against deterministic fixtures and synthetic price series, including the news dates, duplicate filter, bounds, absent-news fallback, analysis output and 1D chart bounds. The app's source passes Python syntax checks. The complete Streamlit browser UI, external provider availability, and paid AI endpoint cannot be exercised in this build container; they must be tested after deployment. Never treat the synthetic test numbers as current market forecasts or trade recommendations.
