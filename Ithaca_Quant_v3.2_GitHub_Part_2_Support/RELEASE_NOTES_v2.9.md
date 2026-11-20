# Ithaca Quant v2.9.0 — accuracy-first audit and model arena

## What changed

1. **Independent AI models competing stock by stock:** Three different algorithms learn from labeled data: regularized Ridge regression (linear), histogram gradient boosting (nonlinear trees), and random forest (bagged trees). Their separate forecasts and a model spread are displayed in **Accuracy Lab → Three-model tournament by stock** and in the leaderboard CSV. Each stock gets its own winner, not a single global winner.
2. **Safety gate before switching a prediction:** Earlier completed labels train the contenders. A later first holdout identifies a candidate. A still-later untouched holdout must independently confirm a ≥3% improvement in that ticker's mean absolute excess-return error over a baseline model calibrated solely from earlier data. Each holdout uses nonoverlapping horizons and demands ≥8 distinct historical decision windows per ticker. If any gate fails, the existing ensemble is retained unchanged. A final model refit uses only labels matured before the current decision date. Under-powered stock histories have no promoted champion.
3. **Historical survivorship audit:** The Walk-forward tab now optionally accepts an archived dated historical membership CSV. Strict mode refuses to run if the archive, an eligible (including formerly listed) stock, or any relevant observed future return is missing. Without archived membership and historical prices, the result is explicitly **UNVERIFIED/current survivors**; the release does not pretend to source delisted historical constituents. The `provenance` field is an attestation, not cryptographic verification.
4. **Data look-ahead fix:** The market loader no longer retroactively masks a historical bar based on a future day's reversal. It preserves raw provider prices instead of creating look-ahead in the backtest. Apparent anomalous prices may remain and should be investigated separately.
5. **Real-world forward evidence:** Recording uses the first-inserted forecast. Reconciliation compares timestamp with actual signal and next-session market closes, classifying entries as `timestamp_eligible` or `late_or_unverifiable`. Qualified forward MAE and weekly reports exclude unqualified rows. Existing cloud and local ledger tables are migrated, without modifying stored original forecast values. Third-party data and storage integrity cannot be independently proven.
6. **Testing and disclosure:** New regression tests cover separately trained forecasts, per-stock fallback, stricter archive coverage, late predictions, and no look-ahead via the data loader. The tournament is tested mechanically using **synthetic** samples; no numerical real-world accuracy gain is claimed.

## Additional audit corrections

- Portfolio backtest executions are now modeled at the **next trading session's adjusted close** (rather than the already-observed signal close); missing hypothetical fills keep cash idle instead of being fabricated. Directional forecast labels remain signal-close to horizon-close, distinct from hypothetical portfolio entry returns. This still does NOT provide real executable bid/ask fills, market impact, or a live P&L statement.
- The autonomous daily logger now filters out **unfinished daily candlesticks** before it trains and records forecasts. A record made during a session cannot silently be called a completed end-of-day forecast.
- Capped forecast logging samples **across the complete forecast distribution** rather than only the most bullish 250 rows. This limits selection bias in reported forecast quality; it does not make a user-chosen universe a random market sample.
- PostgreSQL/SQLite prediction inserts are **atomic first-write-wins** to prevent a concurrent scheduled worker from changing a previously recorded prediction. Provider/database security is not independently audited.
- A price-only tournament challenger **cannot supersede an incumbent with separately qualified richer evidence features**, because the two did not undergo a valid head-to-head evaluation. It stays research-only.

## How to use

- Start the updated Streamlit app. Select your watchlist, history, and horizon as before.
- In **Accuracy Lab**, inspect per-stock Ridge/Gradient Boosting/Random Forest forecasts and their relative disagreement. A winning model only takes over if status says **Passed independent selection and audit**.
- In **Walk-forward tests**, the default test uses today's selected stocks and carries a survivorship-bias warning. To demand strict evidence, check **Require historical point-in-time membership** and upload authenticated archived constituents (each signal date listed). If you cannot provide the necessary delisted histories, leave the result explicitly exploratory.
- Enable the forecast ledger and a durable SQL backend to gather meaningful future comparisons. The weekly Friday report automatically excludes late/backfilled entries once their horizons mature.

## Deployment and monitoring reliability fixes

- Removed obsolete v2.7 folder-version checks that prevented the v2.9 scheduled jobs from running. All workflows now explicitly use a validated repository-root installation.
- Rescheduled daily immutable forecasts to **5:20 PM ET**, after the 5 PM completed-price-bar threshold, so same-day price rows are eligible to become valid forward observations. The weekly audit runs **Friday 5:45 PM ET** after bar finalization, with an **6 PM ET** reporting window cutoff. Both schedules follow Eastern daylight saving time.
- Removed short price forward-fill of missing vendor quotes, preventing invented observations and artificial delisting outcomes; if a ticker has missing data, its model history now shows real gaps.
- Daily forward records are only created when the provider actually supplies a completed bar for the current New York trading date; missing days are skipped rather than retroactively logged.
- Corrected the refresh workflow's invalid working directory for `requirements.txt` and `scripts/refresh_job.py`.
- Weekly outcome reconciliation now processes **all** tracked names in bounded batches, not only the first 150. Missing-provider batches remain pending and are disclosed rather than silently dropped. It filters out unfinished daily bars before resolving outcomes.

## Known limitations

- Public Yahoo data can be delayed, incomplete, revised, or unavailable; timestamps and membership archives are not third-party signed.
- A current-stock watchlist cannot be transformed into a historical all-listed universe merely by toggling a setting. Genuine archived exchange constituents and delisted adjusted prices must be supplied.
- Eight independent outcomes per selection/audit block are a minimum gate, **not** statistical proof of a repeatable stock-specific alpha signal. Multiple stock-by-stock competitions still introduce selection risk; repeated user-driven tuning can overfit.
- Rank scores, the forecast direction, and model agreement are neither probabilities of profit nor guaranteed buy/sell signals.
- Historical backtest fills use adjusted closing prices; live after-close execution, spreads, slippage, dividend-adjusted trade prices, taxes, and delisting returns may differ materially.
- There are exactly **three new predictive model families**, plus the existing incumbent ensemble; the latter acts as a control, not a fourth challenger agent. Provider network threads are bounded separately.
