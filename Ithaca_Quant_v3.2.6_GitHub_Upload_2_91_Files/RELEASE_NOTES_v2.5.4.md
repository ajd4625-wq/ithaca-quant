# Ithaca Quant v2.5.4 — Early trend discovery, 52-week price/news context, color-coded stock search

**Release date:** November 19, 2026. **Purpose:** Make research signals explainable at the individual-stock search screen and reduce the market scanner's existing bias toward companies that have already rallied. This release changes feature engineering and candidate screens, **not demonstrated live return accuracy**.

## 1. Large, highly visible entry/exit cards for every ticker search

In **Instant Stock Explorer**, after downloading a single company and SPY and producing a valid daily forecast, the app now calls the **same `evaluate_candidate` module** as the full-market leaderboard. It displays a large color-coded **ENTRY** card with label, rationale and acquisition/chase safeguards, alongside a separate **EXIT** card listing model exit conditions, weakening 20-day trends and adjusted-price review levels. Dark green means the strictest existing confirmed entry tier; green means either standard ENTRY WATCH or the new EARLY ENTRY WATCH; yellow means unconfirmed, missing news, large run-up or caution; red means exit review. No model, no invented status: a yellow DATA NEEDED explanation appears. Current news is retrieved independently of marketwide scanning. News provider failures do not grant green clearance. A negative exit warning can override favorable entry indications.

The search now uses the same broad source-attributed Google News RSS lookup as the leaderboard (one request per company, up to 45 days), rather than only the older three publisher-specific searches. The news analysis deduplicates syndicated events before counting them. When **two distinct, relevant recent news events** contain negative keywords, an otherwise green entry becomes **yellow NEWS REVIEW** until investigated; this never creates an automatic red sell order and does not change the trained return forecast. Headline-word tone is not deep semantic fact checking and could misinterpret events.

The entry/exit cards reflect the **selected chart's daily forecast horizon** (1D uses a separate next-trading-session ML forecast). The early-trend screen is only defined for the **20-session horizon**; it is not an hourly prediction, a predicted optimal entry time, or an order.

## 2. Added 52-week data to the model's selectable, chronologically tested evidence

`features.py` now computes these point-in-time candidate features using observations available by each date:

- `range_252`: where the adjusted close lies between the observed rolling 252-session low/high, requiring at least 200 observed sessions;
- `low_252_gap`: price change relative to its rolling annual low;
- `has_252_range`: whether sufficient valid history exists (prevents early-watch classification from treating missing history as a neutral midrange);
- `rel_5`: previous five completed sessions versus SPY;
- `mom_5_accel`: last 5-session momentum minus the preceding 5-session momentum;
- `rel_5_accel`: that change in relative strength versus SPY.

These features join the existing **extended evidence group**. The forecaster's existing chronological holdout selection decides whether that group reduces historical prediction error; it **does not force** 52-week inputs into a model when they hurt the selection score. A 252-session trailing window is not a literal 365-calendar-day financial report. Price data may be split adjusted; quote and adjusted-close bases differ.

## 3. New EARLY ENTRY WATCH to find candidates before an extended rally

`signals.plan_signals` still recognizes confirmed ENTRY WATCH. In addition, **20-session** research may label an EARLY ENTRY WATCH when it observes all of the following **simultaneously**:

- positive modeled excess return versus SPY **above 3%**;
- a valid rolling-252-session range with at least 200 daily prices, position between **15% and 72%** of the observed low/high;
- most recent 5-session return **+1% to +10%**, accelerating by **at least 2 percentage points** versus the preceding 5 sessions;
- last 5-session return beating SPY by **over 1 percentage point**;
- trailing 20-session return between **−7% and +10%**, price within **−1.8% to +3.5%** of its 20-day moving average, and activity relative to its 20-day baseline greater than **−20%**;
- historical annualized 20-session volatility **at most 125%** and **no existing exit-review trigger**.

The signal is **green**, not dark green. It is a transparent, **unvalidated early-turn heuristic**, not evidence that the stock will go up. A rising 5-day price alone does not qualify. Strong-entry classification still requires the original dark-green thresholds.

## 4. Broaden the market shortlist *before* AI modeling

Previously `screen_candidates` favored high dollar volume, strong 60-session momentum and volatility, and so tended to exclude turnaround/reversal stocks before the ML stage. It now calculates a separate point-in-time 52-week-range and 5-day-acceleration screen while retaining all minimum price, volume and history gates. When a model shortlist limit is used, it reserves **up to 25%** for eligible early-turn profiles, filling unused slots with the previous liquid/momentum/volatility pool. No candidates are added solely for being down from their 52-week high, and the full ALL-eligible universe remains available as before.

The final model ranks the expanded subset using its trained forecast. The shortlist reservation **does not** ensure an early-turn stock is profitable or even a positive model forecast.

## 5. Show price/news 52-week context and early stock discovery

For searched companies and every modeled leaderboard row, show the 52-week low, high and normalized range position. The news panel compares separate positive/negative headline-word events and explains how *distinct recent headline events* relate to that position (e.g. an announcement arrives near the high after a run-up, or near the lower-middle range while the trend is beginning to improve). Syndicated sources still count as one event using v2.5.3 clustering. News analysis is **descriptive**: today’s headline sentiment or range position cannot arbitrarily increase the primary model forecast.

In **Full-market Dashboard → Ranked Leaderboard**, a new expandable **Early entry watch** shortlist displays all already-news-checked, green early candidates and their supporting 52-week context, while standard green entries still appear higher in the usual entry-readiness ordering. Separate entry and exit colors and acquisition run-up penalties remain.

## 6. Safety, reproducibility and test details

- Price and technical indicators use data at/before the forecast date; future observations are excluded from 52-week statistics.
- Missing or invalid 52-week history never produces an early entry signal.
- Red exit warnings and acquisition / post-news chase checks override entry colors.
- Today's headlines are not quietly inserted into historical model training; archived historical features retain dated evidence and must pass the existing independent selection process.
- The trading model still predicts **relative SPY return**, not guaranteed absolute stock price appreciation.
- Tests cover missing history, new features, point-in-time calculations, early-trend conditions, acquisition overrides, duplicate news context, and shortlist coverage. A passing test suite is **not** a verified improvement in forecast accuracy.
- This build has not been live-tested against the deployed Streamlit Cloud browser, SEC, Yahoo or Google News providers. Validate results on real out-of-sample market dates before placing substantial weight on the new labels.

## Deployment

Keep the **currently working Streamlit entrypoint**. Replace the complete contents of your existing GitHub app directory with this package: `app.py`, `streamlit_app.py`, the inner `ithaca_quant/` package (including `trend_intelligence.py`), `requirements.txt`, `packages.txt`, tests and documentation. Do not create an extra nested release directory. Commit to `main`; Streamlit should redeploy. Changing only the startup file will not install the new screening logic.

No additional API credentials are required for the 52-week price logic beyond the existing quote/history provider; news and optional sign-in/data persistence retain their existing setup requirements.
