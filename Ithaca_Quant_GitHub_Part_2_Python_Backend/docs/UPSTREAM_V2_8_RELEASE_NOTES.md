# Ithaca Quant v2.8.0 — Model Zoo and independent rank research

**Scope:** More forecasting families and rank-oriented models, not a claimed improvement in live market prediction accuracy. The existing production model, leaderboard, portfolio, news, SEC Form 4, screenshot import, and Friday reporting remain intact.

## 1. What we researched and where the ideas came from

| Public system / method | Distinctive idea | v2.8 implementation | Limits |
|---|---|---|---|
| Microsoft Qlib (https://github.com/microsoft/qlib) | Many price/volume factors; comparing ML models by rank IC and rolling tests | Auditable, date-grouped, cross-sectional model contest using the existing observed price/52-week factor columns | Does **not** import Qlib's Alpha158/Alpha360 dataset or trained weights |
| LightGBM LGBMRanker (https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRanker.html) | LambdaMART ranks results in *query groups* | Optional LambdaMART with **each stock decision date as a group** and 0–4 within-date return relevance | Needs the optional `lightgbm` package; rank scores are not probabilities |
| XGBoost learning-to-rank (https://xgboost.readthedocs.io/en/stable/tutorials/learning_to_rank.html) | NDCG group-aware rank objective | Optional `rank:ndcg` XGBRanker with chronologically sorted `qid` groups | Needs the optional `xgboost` package; time and memory costs increase |
| AutoGluon Tabular (https://auto.gluon.ai/stable/api/autogluon.tabular.TabularPredictor.fit.html) | Ensembles multiple model families | **Lightweight inspired approach:** a *fixed* 50/50 blend of linear and nonlinear rank scores, with scaling learned on historical fit data only | Not the actual AutoGluon package/AutoML optimizer, because automatic validation folds can be unsafe in finance |
| InterpretML EBM (https://interpret.ml/docs/python/api/ExplainableBoostingRegressor.html) | Explainable nonlinear per-feature shapes | Optional EBM forecasting candidate, tried by enhanced model comparison if `interpret-core` is installed | The model is not automatically installed; no future-accuracy claim |
| Robust loss and kernel approximation | Heavy-tail robustness and nonlinear shape modeling | Huber robust regression, median quantile gradient boosting, random Fourier feature RBF ridge | A more complex return model is only promoted if historical selection MAE is at least 2% better than the existing ensemble |
| CatBoost ordered training (https://catboost.ai/docs/en/references/training-parameters/common) | Uses data sequence when deciding tree splits | CatBoost candidate now trained with deterministic historical ordering and `has_time=True` | Model may still be rejected by the selection gate |
| Conformal prediction (https://mapie.readthedocs.io/en/stable/content/conformal-prediction/) | Uncertainty from errors on a separate calibration set | Asymmetric quantiles of **final holdout residuals** replace a symmetric residual band | Not a guarantee of statistical coverage for serially dependent market returns, and MAPIE itself is not installed |
| Chronos-2 (https://huggingface.co/amazon/chronos-2), TimesFM (https://github.com/google-research/timesfm), Nixtla NeuralForecast (https://github.com/Nixtla/neuralforecast) | Pretrained forecasting transformers and neural sequence methods | **Researched, not integrated** | Heavy model files, RAM/GPU requirements, possible extra licensing, and no stock-relative out-of-sample validation. No fabricated integration or results |

## 2. Exactly how the new stock-ranking contest works

1. Reuse the app's dated factor/target panel. Require **at least ten tickers per signal date** and **310 mature dates** so the test has separate history, selection, and audit periods.
2. Exclude rows whose forward-return outcome is not known by the requested current date.
3. Train a ranking baseline and challengers on historical rows whose `label_end` is strictly **before** the selection start. Each day's stocks are assigned a *separate* ordinal relevance score (0–4), avoiding a global price-label threshold.
4. Evaluate Ridge, nonlinear histogram boosting, a fixed 50/50 ensemble, optional LightGBM LambdaMART, and optional XGBoost LambdaMART in a **purged model-selection period**.
5. Choose a challenger *without looking at the final audit period*: it must exceed Ridge by 0.01 in mean date-wise Spearman rank IC and by 0.10 percentage point in mean top-20%-versus-universe return. These are research criteria, not optimized trading parameters.
6. Refit the selected challenger using only outcomes known before the untouched audit period. It then must beat the Ridge audit by 0.005 rank IC and 0.05 percentage point in top-20% relative lift; uplift also must be positive. If it fails, output **no promoted ranking**.
7. Only after both checks pass, refit on matured history and emit an experimental ranking of the latest modeled stocks. **The actual production leaderboard does not change.**
8. Model-research training/testing uses a fixed, ticker-hash selected subset of at most 200 stocks per historical date on especially large universes to limit Streamlit load; the latest eligible stocks remain available for ranking. This is a *research subset*, not a survivorship-bias solution.
9. Report **rank IC**, mean top-quintile excess return versus that day's universe, mean NDCG of the top 20%, date counts, and sample counts. Ranking scores are **not** probabilities of profits, green-entry probabilities, or the portfolio's validated future accuracy.

The challenger is not selected based on its untouched final audit, nor is a final audit promoted just because one of many challengers did well there. The report remains a *research sidecar*, even after successful checks, pending repeated real-world forward tests.

## 3. Return-forecast Model Zoo

The existing individual-stock **Enhanced model comparison** now considers:

- **Huber robust regression**: standardized linear model with a robust Huber loss to reduce the influence of outliers.
- **RBF nonlinear ridge**: standardization, random Fourier kernel features, and regularized regression—nonlinear effects without storing a huge kernel matrix.
- **Median quantile boosting**: histogram gradient boosting estimates a median-like return, which is often less affected by extremely large price movements than mean-square loss.
- **Existing Ridge, robust MAE boosting, ExtraTrees, LightGBM, XGBoost, and CatBoost**: preserved, with chronological validation before adoption.
- **InterpretML Explainable Boosting**: optional when `interpret-core` is installed; learns separate nonlinear feature effects that can be inspected by developers. The interface shows availability; it does not claim causal explanations.

The model-selection rule from v2.7 is **unchanged**: candidates must reduce mean absolute forecast error by 2% in the purged selection period. A separate later block is used to estimate error bounds. The new error interval uses separate upper/lower held-out residual quantiles, **not** a guaranteed return range.

## 4. How to use

**On the deployed website:** Full-Market Dashboard → **Accuracy Lab** → **Model Zoo · independent rank comparisons** → **Compare ranking models on independent past periods**. Read both the selection and audit tables and the qualification text before interpreting any proposed research rankings. You need a sufficiently long price-history panel and a modeled multi-stock universe.

**On the individual company explorer:** enable **Enhanced model comparison (slower)** to let the enlarged set of return-forecast candidates compete. If the period-history criteria fail, the existing ensemble remains primary.

**Optional packages:** `requirements-optional-ml.txt` lists LightGBM, XGBoost, CatBoost, and `interpret-core`. They're NOT automatically installed by default, to avoid memory exhaustion on a free Streamlit host. Without them, built-in candidates remain available, and missing optional entries report availability accurately.

## 5. Demonstration and honesty about accuracy

An offline synthetic panel of 340 business dates × 12 stocks, **deliberately constructed** with a strong linear relationship between an observed factor and a future artificial return, produced (purged selection only):

| Rank challenger | Mean rank IC | Mean top-20% excess lift |
|---|---:|---:|
| Ridge baseline | 0.9922 | +2.2531% |
| Histogram surrogate | 0.9898 | +2.2534% |
| Fixed two-model blend | 0.9925 | +2.2549% |
| LightGBM LambdaMART | 0.9905 | +2.2523% |
| XGBoost LambdaMART | 0.9903 | +2.2561% |

**Result:** None of the challengers cleared the *predefined independent selection gate*. No new model was promoted. This synthetic dataset was intentionally easy for linear regression and is **not** evidence that Ridge achieves ~99% ranking skill on real stocks. It shows that the new machinery can reject a complex model when the evidence does not favor it.

**Verified tests:** Tests of the model catalog, grouped relevance, time order, duplicate rejection, robustness, optional ranker APIs, untouched-audit isolation, and short-history refusal; full regression suite and deployment preflight in the release manifest.

## 6. Deployment and limitations

Keep the *same currently working Streamlit main-file path*; update `app.py`, `streamlit_app.py`, and the entire `ithaca_quant/` directory together, along with `requirements-optional-ml.txt` and documentation. Do not upload an extra nested application folder. The startup version in both `app.py` and `ithaca_quant/__init__.py` is **2.8.0**. The default `requirements.txt` stays lightweight.

- The app is not verified to outperform any third-party quant platform or achieve a particular market accuracy.
- Independent real stock tests may find no improvement or may find the new models perform worse.
- Current news, insider activity and SEC filings do not suddenly become predictive features merely because more model families exist; timestamped historical evidence and feature selection still govern them.
- The app's ranking research still uses a *currently modeled stock universe* and cannot correct historic delisting/survivorship bias on its own.
- Extra model training consumes more CPU and may time out on Streamlit free hosting.
- No live-broker execution, order routing, or autonomous trading was added.
