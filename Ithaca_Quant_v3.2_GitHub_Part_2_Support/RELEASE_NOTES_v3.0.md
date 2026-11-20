# Ithaca Quant v3.0.0 — Accuracy-first integrity update

**Status:** Code and synthetic regression tests can establish software behavior, **not actual forecasting improvement**. Historical membership provenance and genuine forward performance remain externally dependent.

## The four original critical issues

1. **Production replay:** `run_walk_forward()` now calls `forecast_asof(..., competitive_agents=True)` for every signal. Results capture which stock's forecast was actually promoted, not a different baseline-only strategy. The model is refit with only **then-matured** labels.
2. **Future-outcome filtering:** Eligibility uses only signal-day close, historical constituent membership (when supplied), and technical features. `forward_return.notna()` no longer affects which stocks are selected. Missing observations are counted explicitly.
3. **Survivorship bias:** The `point_in_time.validate_membership()` strict path requires dated archived constituents and complete, documented terminal return records for missing horizon prices. Missing companies, duplicate snapshots, incomplete outcomes, and bogus provenance labels fail closed. The code **cannot authenticate** a claimed archive or supply a complete CRSP/Nasdaq historical database itself. Survivor-universe backtests remain labeled unverified.
4. **Faithful baseline:** The tournament retrains the actual `fast=True/False` ensemble, reproduces its chronological feature selection **and** forecast shrinkage in both historical blocks. If the feature schema differs from the present production baseline, challenger promotion is prohibited.

## Additional accuracy improvements

5. **Live edge:** A database migration saves the first-seen tournament and incumbent forecasts as an immutable pair. `forward_model_comparison_report()` scores only time-eligible, resolved, paired forecasts; it requires at least **24 independent nonoverlapping outcome windows**, then checks a date-block bootstrap improvement interval. Until enough genuine observations mature it reports *INSUFFICIENT FORWARD EVIDENCE*. Passing this preliminary test is not independently authenticated or an external clinical/statistical guarantee.
6. **Delistings:** Once a stock could have been entered at the next-session price, missing endpoint quotes raise an error unless `terminal_returns` supplies the archive's `entry_total_return`. A real total loss (-100%) remains a total loss. A missing **entry** quote remains unfilled cash; later outcomes cannot retroactively change the selection.
7. **More credible statistical tests:** At least **20 nonoverlapping matured H-day outcome windows** in EACH of selection and audit, at least 3% relative improvement over incumbent MAE in both, plus evidence of better-than-zero absolute MAE and no directional performance degradation. A one-sided paired test is adjusted across all audited tickers using **Benjamini-Hochberg at q ≤ 0.05**. No winner is guaranteed, and large H may require more than 6 years of observations.
8. **Independent information views:** Ridge uses technical+regime inputs; Gradient Boosting can use archived news and earnings along with technical extensions; Random Forest can use archived SEC financials and SEC Form 4 insider activity. Any archive must have sufficient historical coverage, otherwise models remain technical-only, and no source is fabricated. Form 4 trades without an intraday filing timestamp are only eligible from the **next business session** after the public filing date.
9. **Appropriate metrics:** The audit includes directional hits, cross-sectional Spearman IC, and a cost-aware top-N hypothetical Sharpe proxy. The real execution simulation separately evaluates next-session close entry, turnover, estimated costs and terminal payoffs. None is a guarantee of real trade execution.
10. **Consistent uncertainty:** The winner's risk-panel `model_disagreement` is replaced by the contemporaneous **three-model vote spread**; the winning model's independent historical residual scale is reported separately, rather than leaving the retired incumbent's disagreement in use.
11. **No fabricated volume:** The Yahoo loader preserves missing volume as NA instead of zero. Panel rows with missing mandatory volume-ratio features cannot be used for model training or ranking.
12. **Price-target assumption corrected:** A simple conditional *historical SPY-return distribution scenario* replaces an assumed 0% SPY return. The app labels scenario prices as not validated absolute forecasts. With insufficient SPY history, fallback -10/0/+10% scenarios are transparently disclosed.
13. **Winner-specific event odds:** Independently trained historical selection logistic maps forecast values/volatility/market context to an outcome likelihood, and only emits odds if audit Brier beats a constant baseline. Otherwise promoted-stock gain/boom odds are N/A, **not the incumbent's unrelated event-classifier probabilities**. Any available event odds are preliminary, not proven calibrated. The baseline retains its own event model.
14. **Forward and weekly reporting:** The Accuracy Lab now shows paired tournament-vs-incumbent forward evidence; Friday reports can include that summary. Fewer than 24 independent matured windows means no evidence of a verified live advantage.

## Deployment and usage

- Replace the whole repository with the ZIP contents, keeping `streamlit_app.py` at the root. Run `python scripts/preflight.py`.
- Install pinned dependencies from `requirements.txt`; configure `ITHACA_DATABASE_URL` for durable cross-worker forecast storage and scheduling secrets for the existing jobs.
- Visit **Walk-forward tests** to enable strict historical constituent validation and upload a CSV with `date,ticker,eligible,provenance=historical_archive`; use the additional terminal payoffs upload for genuinely delisted positions (`signal_date,ticker,asof_total_return,entry_total_return,source=historical_archive`). These are **claimed**, not independently verified, archive records.
- Visit **Accuracy lab** for three individual forecasts, selected champion, adjusted evidence, and genuinely forward-recorded out-of-sample paired results.
- To supply archived **Form 4** signals directly to the library, use `build_panel(..., insider={ticker: archived_rows})`. The optional browser SEC Form 4 tab only fetches current filings and intentionally **does not rewrite historical training data**.
- As more historical signal dates are evaluated, tournament replay can be expensive. Full mode is especially CPU-intensive for thousands of tickers. The app retains the original ensemble if challenger evidence or data coverage is insufficient.

## Data and validation limits that code cannot eliminate

- **No authenticated full historical security master, delisted adjusted returns, historical fundamentals or broad historical insider/news archive is bundled.** Today's stock list is still a survivor-biased universe until such data is provided and independently vetted.
- **No verified superior real-market performance currently exists in the codebase.** 24 forward windows at a 20-session horizon require a substantial amount of real passage of market time. The score will remain pending until logged forecasts and actual market outcomes accrue.
- Yahoo Finance adjustment and availability, SEC filing coverage, scheduled-job reliability, market regime changes, price slippage, bid/ask spread, illiquidity, and broker execution remain material uncertainties.
- `model_disagreement` is a model spread, not a calibrated risk limit; the historical vote/residual uncertainty is not a guaranteed confidence interval.
- The projected price midpoint is a *conditional scenario*, not a verified absolute-price forecast.
- Paired tests/bootstrap can be invalidated by data quality, correlated markets or repeated experimentation; they do not guarantee profit.

**Testing:** `tests/test_v30_verified_pipeline.py` uses synthetic fixtures exclusively. See `TEST_RESULTS_v3.0.md` for the exact tests run and their results. Never present synthetic test success as live accuracy.
