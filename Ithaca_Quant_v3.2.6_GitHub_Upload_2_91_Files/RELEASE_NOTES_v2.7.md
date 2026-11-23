# Ithaca Quant v2.7.0 — Professional-Method Research Audit

**Release date:** November 19, 2026. **Type:** research accuracy/evidence upgrade; not a demonstrated market accuracy improvement.

## What was studied and what is actually public

The items below come from the platforms' **published** documents. This is a comparison of methods that are documented, not access to proprietary trading data, private code, return histories, or a fair head-to-head performance comparison.

| Platform / research framework | Documented feature | Implemented v2.7 improvement | Still missing |
|---|---|---|---|
| QuantConnect LEAN | Event-ordered historical data, point-in-time warnings, customizable execution/slippage/fee models, survivorship-aware datasets | Event availability checks, next-session delayed price proxy and configurable cost stresses | Actual exchange/broker fill simulator; point-in-time delisted constituents |
| Numerai Signals | Neutralized signal evaluation, validation metrics, churn analysis | Date-block rank evaluation, turnover metrics, optional group-neutral IC when credible historical sector labels exist | Licensed sector factor model, live validation comparable with Numerai |
| Alphalens | Factor rank information coefficient, top/bottom quantile returns, turnover | Per-date Spearman IC, top-bottom spread, top-versus-universe, date bootstrap | Full Alphalens tear sheets and event study distributions |
| QuantRocket Moonshot | Walk-forward ML research and configurable costs | Independent time-delayed and friction-aware outcome audit | Institutional data subscriptions and brokerage execution |
| VectorBT | Costs, slippage, timing-aware portfolio simulation | Cost sensitivity and next-close execution *proxy* | Fully simulated fills, order books, spread modeling and continuous mark-to-market |
| Bloomberg BQuant | Integrated data, factor scoring and research workflows | Adds directly inspectable audit in stock dashboard | Bloomberg licensed/proprietary feeds, compute and enterprise collaboration |

### Official documentation / evidence

- QuantConnect LEAN: https://www.lean.io/research/ ; https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide
- Numerai Signals: https://docs.numer.ai/numerai-signals/scoring ; https://docs.numer.ai/numerai-signals/signals-overview
- Alphalens: https://alphalens.ml4trading.io/notebooks/overview.html
- QuantRocket: https://www.quantrocket.com/docs/
- VectorBT: https://vectorbt.pro/features/backtesting/fees-slippage-and-leverage/
- Bloomberg BQuant: https://professional.bloomberg.com/products/bloomberg-terminal/research/bquant/
- SEC point-in-time XBRL: https://www.sec.gov/search-filings/edgar-application-programming-interfaces

## Every code change explained

### 1. New **🏛️ Research audit** tab

Inserted immediately after **Walk-forward tests** in the full-market dashboard. Run the existing walk-forward backtest first; the audit operates on its **frozen prior predictions**, never on future return inputs at prediction time. A slider selects the top-ranked fraction and a second slider sets assumed per-side trading friction. These settings are research scenarios, and trying many values can overfit conclusions.

### 2. Per-decision-date ranking quality

The audit calculates Spearman rank information coefficient (IC), difference in realized SPY-relative performance between top-ranked and bottom-ranked stocks, and top-ranked performance relative to all evaluated stocks. Returns are **SPY-relative label excess** here, not total investment return. Independent windows are the **decision dates**, not the many correlated stock rows. It also shows realized top-group relative-direction hit rate.

### 3. Uncertainty, costs, and churn

A seeded 2,000-draw date-block bootstrap creates an *exploratory* 95% range for mean top-ranked stock uplift. At least eight decision dates are required; fewer show an uncertainty warning. The audit shows membership turnover and a sensitivity outcome after subtracting assumed round-trip basis-point costs. These are not the actual brokerage commissions or execution spread.

### 4. Timing-robustness comparison

`next_close_proxy` computes selected stocks' gross returns from the close of the session **after** the signal to the close of the session **after** the recorded label's ending session, whenever both exist. That avoids pretending a signal calculated at today's close could be executed at today's close. The results are a *one-bar delayed close-to-close proxy*: it is not an opening fill, actual order execution, nor a complete simulation of gap/slippage/liquidity effects. It includes a configurable cost stress and exports row-level CSV so results are auditable.

### 5. Point-in-time publication *and* discovery timestamp guard

`availability_safe_join` requires both the public-release timestamp and the system's discovery timestamp. A document enters a dated historical feature only after **both** are available. This protects against accidentally using news, earnings, or SEC filings before the system could have known them. The helper is prepared for use by future ingestion workflows; **it does not retroactively modify v2.6 model training or guarantee historical market-data integrity**.

### 6. Market-price quality screen

`historical_data_health` checks price-history completeness, stale last observations, invalid nonpositive prices, and one-session moves exceeding 60%. Those large moves can be *legitimate* earnings news or stock adjustments, so they are flagged, not deleted. A warning does not prove provider error. Historical delisted constituents are still absent unless the data vendor supplies them.

### 7. Research demonstration + reproducibility

Run `python scripts/institutional_demo.py`. Its deterministic, **synthetic** inputs simulate dates, prediction scores, and prices with an intentionally constructed statistical relationship. The saved `INSTITUTIONAL_DEMO_SYNTHETIC.txt` records the exact example outputs. **Do not use these results as evidence of real forecast accuracy or superior real-world performance.** Run a sufficiently broad historical walk-forward test using real, point-in-time market data and track live forward predictions for stronger evidence.

### 8. Existing app features and scheduling retained

`streamlit_app.py` remains the default working launcher. All v2.6 features—including news aggregation, duplicate event clustering, color-coded entry/exit signals, SEC Form 4 tab, portfolio persistence options, screenshot import, separate forecasting model, and weekly Friday reports—remain included. Updated GitHub Actions workflows locate v2.7, rather than hard-coding v2.6. Cloud execution of those workflows still requires configured secrets and active jobs.

## What accuracy was achieved?

**Unverified.** No live multi-universe out-of-sample accuracy measurement was performed or obtained from a broker here. The v2.7 changes strengthen evaluation, timing, and data checks; they do not themselves establish more predictive power or 80% directional accuracy. A selection filtered to rare, high-confidence cases must report how many forecasts qualified and the coverage percentage.

## What must happen before any superiority claim?

1. A point-in-time universe including delisted securities, adjusted corporate actions and event publication/discovery times.
2. Exactly comparable dates, symbols, label definitions, execution assumptions, transaction costs and trading constraints for each competing system.
3. A frozen model tested on unseen future observations over multiple market regimes, plus independent live paper results.
4. Statistically significant returns after costs and drawdown risk (not only win rate), plus dated, reproducible reports.
5. A verified provider and security configuration for any proprietary data feeds.

A free hobby project cannot truthfully be described as better than every professional system solely because it has similar features.

## Deployment

Unzip and replace all corresponding files **inside your already working GitHub application directory**. Keep the working Streamlit entrypoint path (`streamlit_app.py`) unchanged. Ensure `app.py` and `ithaca_quant/__init__.py` both show **2.7.0**; do not edit just one version number. Run `python scripts/preflight.py` locally to verify syntax, paths, and version matching. Push `.github/workflows/` files to the repository root if you use the optional scheduled jobs. No new credentials or dependencies are needed for this audit; live scheduled reports require the existing database and SMTP configuration.

## Test evidence

**214 automated offline tests passed in three test groups.** The Python syntax and deployment preflight also passed. These tests do not verify live external services, hosted Streamlit behavior, or real-market accuracy.


Unit tests cover event availability after publication and discovery, cross-company isolation, missing dates, rank IC, quantile uplift, date bootstrap, model-cost sensitivity, next-bar delay, lack of a future price, and price-quality flags. The package's broader historical-model regression tests should be run after code changes. Automated tests establish mechanical correctness, not trading profitability.
