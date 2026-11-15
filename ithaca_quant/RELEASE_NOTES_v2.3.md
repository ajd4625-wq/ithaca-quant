# Ithaca Quant v2.3 — Cleaner Labels & Top-Pick Evidence

**Date:** November 14, 2026. Built on the user-supplied v2.2.0. All v2.2 gates, tabs and safeguards are retained. Educational research only; no accuracy guarantee.

## What changed

### 1. Same-day-demeaned training label (gated)
Each stock's SPY-relative return contains a large component shared by every stock on the same date (market and universe-wide moves). A stock-picking model cannot predict it, and it is most of the label noise. v2.3 builds `target_cs` = target minus the same-date universe median (dates with at least 8 names; otherwise unchanged) and may train on it. Code: `features.build_panel`, `model.choose_target_mode`, `fit_ensemble(target_col=...)`.

- **Gate (v2.2's independent blocks):** fit on the early block, scale learned on the middle block, compared on the last block. Adopted only if mean per-date rank IC improves by at least 0.01 with paired t >= 2 across dates and absolute error on the true label is within 1%. Otherwise the raw label is kept. Reported per forecast as `target_mode` / `target_mode_note`.
- The removed constant (`offset`) is added back so forecasts stay on the SPY-relative scale; rankings, `forecast_shrinkage` and the Accuracy lab behave as in v2.2. The lab's own candidate comparison still uses the raw label.
- **Gate behaviour measured on planted data** (shared shock sd 0.5, weak real signal): adopted in 12/12 runs, raising rank IC by +0.1 to +0.3. On pure noise it was adopted in 1/12 runs (about 8%, a false positive; harmless because both models then give similar forecasts). With a strong, easy signal the trees already find it on the raw label and the gate correctly keeps raw.
- Absolute error is a weak guard here (a shared shock dominates it), which is why rank IC with a t-test is the main criterion.

### 2. "Do the top picks beat the field?" report
`validation.top_pick_report` plus a new panel in **Walk-forward tests**. Per decision date it takes the top 20% of ranked stocks and reports: share beating SPY vs the whole field's share (the honest always-pick baseline), and the average return spread of top picks minus field, with a bootstrap 95% interval over decision dates (needs 12+ windows; stocks on one date share market risk so rows are not independent). Flows into `overall_quality`.

### 3. Tooling
`per_date_rank_ic`, `mean_rank_ic`, `ITHACA_DISABLE_CS_TARGET=1` (restore v2.2 label), benchmark script now compares v2.0 / v2.2 / v2.3. 10 new tests.

## Measured result (offline synthetic market — mechanics only)
`python scripts/accuracy_benchmark.py`: 3 synthetic markets, 12 nonoverlapping 20-day windows each.

| Metric (mean) | v2.0 | v2.2 raw label | v2.3 |
|---|---|---|---|
| Forecast MAE (zero baseline 0.0698) | 0.0703 | 0.0699 | 0.0698 |
| Mean rank IC | −0.012 | −0.005 | −0.010 |
| Top-20% picks beat SPY (field: 51.5%) | 45.5% | 47.2% | 49.7% |
| Top-20% minus field return | −0.28% | −0.26% | −0.12% |
| Gain Brier (baseline 0.2454) | 0.2574 | 0.2475 | 0.2475 |

**Honest reading:** v2.3 vs v2.2 is a wash within noise (one seed identical, one slightly better, one slightly worse; rank IC marginally lower, top-pick metrics marginally higher). No arm shows a real ranking edge on this synthetic market, and top picks still do not beat the field. Gains over v2.0 come mostly from v2.1/v2.2 (probability calibration, shrinkage). v2.3's value shows up in the controlled planted-signal test above, where shared shocks swamp a real signal; whether real stocks look like that is unknown. Judge only with `--live` on 40+ tickers and the forward ledger.

## Estimated real-world accuracy
Unchanged: no live data was available, so there is no verified number. A low-confidence guess for SPY-relative direction is still roughly 50–55%, and the realistic ranking edge is a small positive IC (about 0.01–0.05) that can be zero or negative in some periods. v2.3 does not justify raising it.

## Limits
Offline only; no Yahoo/SEC/FRED calls. Survivorship, overlapping labels, multiple-comparison risk (the gate reuses one selection block) and free-data delays remain. Fit time is about 2 extra fast fits per forecast.

## Upgrade
Replace the entire outer `ithaca_quant/` application folder (app.py, inner package, scripts, tests). Header must show v2.3.0. No new dependencies.
