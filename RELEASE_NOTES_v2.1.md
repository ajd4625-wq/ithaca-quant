# Ithaca Quant v2.1 — Forecast Accuracy Refinements

**Release date:** November 14, 2026. Built on the matching v2.0.0 package; every v2.0 feature, tab and safeguard is retained. Educational virtual research only — no orders, no guarantee of accuracy.

## What changed and why

| # | Change | Where | Why it should help |
|---|---|---|---|
| 1 | **Robust training target** – winsorize at the target's own 0.5%/99.5% quantiles | `model.robust_target`, used by `fit_ensemble` and the lab | The old ±80% clip almost never fired on 20-day excess returns, so takeover/crash outliers dominated squared-error fits. |
| 2 | **Calibrated forecast scale** – multiply forecasts by a factor in [0.15, 1] learned on the embargoed holdout | `model.shrinkage_factor`, `_choose_with_scale`, `research_lab` | Tree ensembles fitted to noisy returns are over-dispersed. Shrinking toward zero lowers error and never changes the ranking. Reported as `forecast_shrinkage`. |
| 3 | **Extended feature group** (12-1 momentum, 52-week-high gap, 60d beta, idiosyncratic vol, max-return, skew, log dollar volume, 1-day reversal, six same-day cross-sectional ranks) | `features.EXTENDED_FEATURES` | Standard, point-in-time cross-sectional predictors. Adopted **only** if they beat the baseline by ≥1% MAE on the chronological holdout, like the SEC/news groups. |
| 4 | **Tighter candidate search** – test each evidence group alone; combine only groups that passed alone | `choose_evidence_features` | Fewer holdout comparisons (less selection noise) and fewer model fits (faster). |
| 5 | **Probability blending** – weight between classifier and base rate chosen by holdout Brier | `probability.EventModel.blend` | A classifier that cannot beat the constant rate collapses to it instead of showing overconfident odds. |
| 6 | **Bad-tick sanitation** – mask a >35% one-day move that fully reverses next session | `data.remove_bad_ticks` | Free feeds occasionally emit a one-bar bad print, which would corrupt momentum, volatility and labels for weeks. |
| 7 | **A/B benchmark + legacy switch** | `scripts/accuracy_benchmark.py`, `ITHACA_LEGACY_MODEL=1` | Lets you measure old vs new on identical windows and restore v2.0 behaviour exactly. |

## Measured result (offline synthetic market — mechanics only)

`python scripts/accuracy_benchmark.py` — 3 synthetic markets (fat tails, volatility regimes, weak factor premia), 12 non-overlapping 20-day walk-forward windows each:

| Metric | v2.0 | v2.1 |
|---|---|---|
| Forecast MAE (zero-forecast MAE = 0.0698) | 0.0703 | **0.0701** |
| Mean rank IC | −0.012 | **+0.009** |
| P(gain) Brier (constant-rate baseline = 0.2454) | 0.2574 | **0.2499** |
| Direction hit | 0.494 | 0.492 |

Honest reading: the improvement is small and consistent in direction, and the clearest gain is less over-confident probabilities. Three seeds × 12 windows is **not** statistically conclusive, and a synthetic market built by us cannot prove anything about real stocks. Run `python scripts/accuracy_benchmark.py --live AAPL MSFT NVDA ...` with 40+ tickers on a machine with Yahoo access and trust only that.

## Behaviour changes to know about

- Forecast magnitudes are smaller (shrunk). The rule-based `ENTRY WATCH` threshold (`forecast_excess > 2%`) is therefore reached less often. Rankings are unchanged by this step.
- Model fit time is roughly 1.6× v2.0 in fast mode because the extended group adds candidate fits and more input columns.
- `forecast_asof` adds a `forecast_shrinkage` column; `EventModel` adds a `blend` field. Existing columns and function signatures are unchanged.

## Limits (unchanged from v2.0)

No live Yahoo/SEC/FRED calls were made in the build container. Survivorship bias, overlapping labels and free-data delays remain. Nothing here guarantees future forecast accuracy.

## Upgrade

Replace the **entire** application folder (app.py plus the inner `ithaca_quant/` package, `scripts/`, `tests/`). Version must read 2.1.0 on the home page. No new dependencies.
