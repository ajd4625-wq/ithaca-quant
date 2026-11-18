# Ithaca Quant v2.2.0 — Detailed Release Notes

**Source:** the user-provided `Ithaca_Quant_v2.1_Accuracy_Upgrade.zip`. **Date:** November 14, 2026. **Scope:** precision and credibility of forecasts, not guaranteed directional accuracy or real-money investment advice. Existing v2.1 modules, front-end features, market scan, schedule, portfolio settings, storage and dependency lists remain.

## 1. More independent calibration of forecast magnitude

In v2.1, the same recent historical holdout could both choose extra feature groups and calibrate their return magnitudes, making apparent differences overly optimistic. Now training observations, magnitude-calibration observations, and feature-selection observations occupy *different chronological blocks*. Any training row whose forward-return label completes on or after the next block's start is excluded. The scale is set before examining the feature-selection block; this reduces double-dipping and false confidence in an additional predictor. It does **not** guarantee lower future prediction errors.

Code: `ithaca_quant/model.py` `_choose_with_scale`. With too little clean history for all blocks, it uses the baseline instead of choosing extras on inadequate data. SEC, news, earnings surprises, market-regime and extended price features remain gated on historical availability and separate selection accuracy. Multiple-comparison risk remains; the historical walk-forward test still matters.

## 2. Four-way enhanced model comparison

`ithaca_quant/research_lab.py` now partitions matured labels into **fit**, **forecast-scale calibration**, **feature/model selection**, and **untouched error audit**. All boundaries purge labels ending after the next period begins. An enhanced model must beat the existing ensemble's selection-period MAE by at least 2% before replacing it; the later audit is not used to choose the winner. Final model is re-trained on all mature labels, with its calibration scale fixed from the earlier block. An out-of-sample residual interval requires enough audit examples. With inadequate data, no empirical interval is claimed.

This is only enabled when the optional enhanced model comparison is used. Whole-universe scanning keeps the streamlined existing ensemble so it does not become impractically slow.

## 3. MAE-robust forecasting candidate

Added `Robust MAE boosting` as a new candidate in enhanced individual-stock comparisons. This is `HistGradientBoostingRegressor(loss='absolute_error')` with regularization. Since extreme event returns can distort squared-error fits, this model may prove useful on some historical ranges. It competes with Ridge, ExtraTrees, and optionally LightGBM, XGBoost, CatBoost under the **same** chronological rules. No particular model is declared the winner in advance.

## 4. Honest probability calibration and checking

Event probability modeling now separates **classification fit**, **blend-weight calibration**, and a **later Brier evaluation**. The blend between classifier probabilities and the historical event rate is chosen on the calibration block; the published Brier evaluates it on previously unseen subsequent dates. This avoids reporting the same block as both tuning and held-out evidence. If there isn't enough calibration history, the probability model defaults to the observed base rate, not an untested conditional probability. The definition of boom remains closing-price return over the selected horizon.

Code: `ithaca_quant/probability.py`. Actual future calibration is still unknown.

## 5. Accuracy intervals that recognize correlated stocks

Historical backtests can score many tickers per date, but those stocks experience the **same market event**; treating them as independent overstates confidence. Added a seeded bootstrap of **entire decision dates**, producing exploratory 95% bounds around hit-rate *lift relative to the past-majority baseline*. The UI shows the bounds with at least 12 distinct decision windows and explicitly warns if the interval includes zero. This is a descriptive interval, not a correction for look-ahead from survivorship or repeated strategy tuning.

Code: `ithaca_quant/validation.py` and the Walk-forward tests section of `app.py`.

## 6. Release integrity

Set both the app release and package version to **2.2.0**; update release consistency tests. The entire outer `ithaca_quant` application folder and its inner Python package must be deployed together. Main Streamlit file remains `ithaca_quant/app.py` in the previously discussed repository structure. No new required dependencies or API keys.

## Controlled offline comparison — **not live accuracy**

A small repeatable synthetic example with **12 generated stocks**, **850 business-day sessions**, **20-session horizon**, **3 nonoverlapping decision windows**, and an identical random seed (7) was run against the user-supplied v2.1 and new v2.2 code. The same generator, target and evaluation method were used:

| Metric (illustrative synthetic observations) | v2.1 | v2.2 |
|---|---:|---:|
| Directional hit | 52.78% | 52.78% |
| Past-majority baseline hit | 38.89% | 38.89% |
| Relative-return MAE (lower better) | 7.108% | 7.151% |
| Predict-zero MAE | 7.173% | 7.173% |
| Gain Brier (lower better) | 0.25194 | 0.25156 |
| Gain Brier historical-frequency baseline | 0.25194 | 0.25194 |
| Mean rank IC | −0.212 | −0.212 |

Interpretation: **mixed, not a demonstrated accuracy improvement.** The stricter gating reduced optimistic model selection, but this one small synthetic case showed slightly worse return-MAE, unchanged direction and slightly better probability error. Three decision windows are far too few to infer persistent skill. The synthetic universe is not evidence of performance on current NYSE/Nasdaq stocks.

### Estimated real-world directional hit rate

No live market-history data, actual prior forecasts, or externally verified outcomes were available in this environment to measure the real-world hit rate. A *subjective, low-confidence guess* remains **about 50–55% (midpoint approximately 52–53%) for SPY-relative direction**, not a verified v2.2 number. The 2.2 implementation alone does **not** justify raising the earlier estimate. Real performance can be below 50%.

To measure: on a machine with permitted market-data access, run full walk-forward tests across a sufficiently broad ticker sample and many nonoverlapping windows, then record actual future predictions in Accuracy Lab. Compare MAE against predicting zero, direction versus the past-majority baseline, Brier versus event rate, and strategy returns versus SPY **after transaction costs**. Current-survivor ticker selection and repeated parameter tuning can inflate historical scores.

## Test verification

**118 tests passed in two independent pytest batches** (86 existing integration/unit tests and 32 forecasting/validation tests), with pytest third-party autoload disabled to avoid unrelated environment plugins. A single all-tests invocation exceeded the command time limit after reporting 90 completed tests; the split batch runs both finished successfully. Python compile checks passed. No deployment or live market-data validation was possible.

## Installation

1. Unzip the release into your project workspace.
2. In the `ajd4625-wq/ithaca-quant` repository replace the **whole** `ithaca_quant/` application folder, including `app.py`, inner `ithaca_quant/`, scripts and tests. Do not replace just `app.py`.
3. Commit all matching files to `main`, keeping Streamlit entry point `ithaca_quant/app.py`.
4. Reboot the Streamlit app if it doesn't redeploy; its header should display v2.2.0.
5. Check logs and that the new Walk-forward confidence-interval caption appears after at least 12 periods.
6. For scheduled GitHub Actions refresh, as before put its workflow under repository-root `.github/workflows/`, not the nested application folder.

## Limitations

- No Yahoo, SEC, macro, or external API calls were available for this build. End-to-end cloud deployment and real-data accuracy have not been verified.
- Original data and structural risks remain: historical survivor universes, stale/missing free feeds, corporate-action data cleaning and execution differences.
- Reusing validation data for multiple experiments can still overfit; use fresh future paper outcomes for final judgment.
- Longer holdouts require sufficient history; the fallback remains intentionally conservative.
- Historical news and analyst surprises still require archived point-in-time data to be used in a validated prediction.
