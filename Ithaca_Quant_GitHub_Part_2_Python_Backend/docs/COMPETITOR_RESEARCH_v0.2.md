# Competitive research and accuracy plan — 19 November 2026

Research method: public Chrome Web Store listings, vendor documentation and Chrome's official APIs. Listings describe **claimed features**, not independently tested model performance, latency, or prediction accuracy. The extension code of third-party competitors was not reverse-engineered or copied. The proposed alternatives reproduce broad interaction patterns with newly written code and reuse only the user's own supplied Ithaca Quant model.

## Products examined

| Product | Publicly described advantage | Likely engineering pattern (inference unless documented) | Ithaca approach | Status |
|---|---|---|---|---|
| **WickScan AI Chart Scanner** | Floating chart scan action, AI chart pattern detection, support/resistance, screenshot analysis, side panel, three-engine consensus | On-demand visible-tab image capture and remote vision processing based on its stated workflow | Floating widget + side panel + manual screenshot preview; no outsourced vision and no claim of AI chart OCR | **Partially implemented** |
| **Tradestie Stock Score** | Score 0–100; Yahoo Finance on-page badge; technical factors including MACD/RSI, risk | Vendor states it extracts ticker only from Yahoo page URL and obtains a daily score | Supported finance URL parsing and transparent 3-component strength scores using supplied model | **Implemented subset** |
| **FinSignal – AI Finance Agents** | On-page ticker badge, watchlists, multi-agent cited analysis, document interpretation, PDF export; listing advertises eight agents | Browsing context + user-selected model providers; exact calibration and outcomes not independently verified | **Only 3 scoring components** as requested, visible data provenance, CSV + HTML accuracy audits; no PDF 10-K analysis | **Implemented subset** |
| **TradeSgnl TradingView AI Assistant** | Reads chart symbol/timeframe/indicators; side panel and strategy/alert tooling; performance analytics via connected accounts | Chart-context adapters to vendor backend and TradingView workflows, per product docs | URL ticker adapter + end-of-day 5-session research; does not control chart, alerts or brokerage | **Implemented subset** |
| **InvestFellow Stock Ticker & AI Stock Insights** | Watchlist bar, hover insights and data-refresh cadence; some plans advertise faster prices | Persistent content widget + service that periodically refreshes vendor data | Lightweight floating signal card, 45-second UI refresh, data freshness label, model cached by backend; no tick-by-tick quotes | **Implemented subset** |
| **TradingView Remix AI Chart Copilot** | Chart assistant and indicator/chart automation | Vendor-specific chart integration and LLM/tool interaction | Side panel and supported URL detection; no chart automation or LLM chat | **Implemented subset** |

**Primary public references** (accessed November 2026):

1. WickScan Chrome listing: https://chromewebstore.google.com/detail/gpjpijeihganiinjmkmmppomackgjhol
2. Tradestie listing: https://chromewebstore.google.com/detail/gffdfmjdieclfpphppdkghnmnkakicee
3. FinSignal listing: https://chromewebstore.google.com/detail/epcgnknaidobnklhlhdohlbdainbbegl
4. TradeSgnl listing: https://chromewebstore.google.com/detail/eobcggdohjhgpoielljmfolbgmmofpco ; official docs https://docs.tradesgnl.com/tradingview-ai
5. InvestFellow listing: https://chromewebstore.google.com/detail/cihiajappnfnilbfhglonfcjhmeliilh
6. TradingView Remix listing: https://chromewebstore.google.com/detail/fchmejnoncmdhlebgdgifdnehoibalnd
7. Chrome side panel API: https://developer.chrome.com/docs/extensions/reference/api/sidePanel
8. Chrome tab screenshot permissions/limits: https://developer.chrome.com/docs/extensions/reference/api/tabs
9. Chrome tabCapture restrictions: https://developer.chrome.com/docs/extensions/reference/api/tabCapture
10. Chrome alarms and sleep/period caveats: https://developer.chrome.com/docs/extensions/reference/api/alarms
11. Chrome permission minimization: https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions

## What makes the competition useful

**Low interaction cost:** the best ideas are an in-page affordance (WickScan/Tradestie/InvestFellow) and a persistent side panel (TradeSgnl), both of which reduce context switching. Implemented via MV3 content script, isolated ShadowRoot for overlay CSS, sidePanel API for detail, and a shared localhost research bridge. The Chrome monitor is off unless enabled. Only supported finance domain URLs can activate the overlay.

**Trust:** the competitors often use a score or confidence-looking number. A number without an audited outcome base can create false certainty. Ithaca shows exactly what 0–100 means (a deterministic composite strength score), refuses to call it a probability, and freezes model outputs in an append-only SQLite audit. News is labeled separately, with URLs, dated publisher sources and clustered events. A failed data source is a visible failure rather than a vote against the stock.

**Performance:** a ticker URL requires no OCR, image upload or remote multimodal inference. End-of-day prices are collected only by the local bridge. Requests for the same ticker coalesce behind one lock and reuse 10-minute results, while RSS news is cached for 20 minutes and fetched asynchronously. The selected 5-day forecast is built using the **actual supplied v2.5.4 price/volume feature builder and ensemble**, fast training mode. This is a speed optimization, not proof of superior market accuracy.

**Privacy:** full screen captures are costly and sensitive. A visible-tab screenshot requires a direct user action. The view is a local preview and is not sent to an AI model. Actual live visible-tab analysis would require a deliberately requested camera/tab stream permission and a separately evaluated vision model. Using ticker URLs avoids collecting browsing data or financial account credentials unnecessarily.

## What could genuinely improve accuracy (measured, not promised)

### Implemented now

1. **Point-in-time logging:** one immutable ticker/as-of/horizon forecast in SQLite; refreshes cannot create multiple wins from one event.
2. **Completed-bar discipline:** the current daily bar is withheld before 5 p.m. ET, because its final close is not yet observed; no false intraday update masquerades as a new trained daily forecast.
3. **Horizon/target matching:** the companion explicitly forecasts 5-session return **minus SPY** and grades exactly that target. A 5-session excess forecast is not presented as a prediction of today's next tick or guaranteed upside.
4. **Outcome maturity:** only settle when five later common, complete sessions exist. Pending and abstentions are counted separately; no hindsight or cherry-picking.
5. **Missing-evidence abstention:** the forecast component is `null` if model fitting fails; a plausible-looking fallback score is not invented.
6. **Three constrained scorers / two retries:** the user requested max three agents and two retries. In v0.2, scoring uses Forecast, Momentum and Risk only; provider requests use initial call + maximum two retries, and the Chrome bridge adds none.
7. **Independent news narrative:** clustered dated headlines provide research context, not an unvalidated additive return forecast. Multiple syndications do not increase the count of independent events.
8. **Early-inflection filters:** demands improving momentum rather than buying every stock near its observed 52-week high; avoids a simplistic 'price low = cheap' assumption.

### NOT IMPLEMENTED or NOT VERIFIED

- **True chart-image AI pattern recognition:** screenshot preview exists; visual AI extraction does not. A model calling screenshots a breakout without validated bar prices would be a reliability regression.
- **Low-latency real-time prices:** Yahoo adjusted daily feeds do not provide guaranteed real-time market data. UI refresh should never be sold as fresh market quotes.
- **True calibrated probability of profit:** a 0–100 composite signal score is not a calibration curve. Calibrate only after a large enough honest holdout.
- **Large out-of-sample performance study:** requires many historically dated research snapshots. Single-ticker retraining may differ sharply from full-universe ranking. No evidence the extension outperforms a simple momentum, SPY, or random baseline.
- **Full company events/SEC Form 4 research:** existing model package contains related hooks, but the browser bridge has not wired an insider filings tab or evidence-aware first-seen audit.
- **Cloud push or ChatGPT-delivered weekly research:** the local server writes HTML; Chrome sends notifications only while the browser and bridge are running and reachable. The assistant cannot retrieve local future reports without the user sharing them.
- **Automated execution / account integrations:** intentionally absent.

## Recommended reproducible accuracy study

First collect predictions **before** their maturity dates. Segment data by up/down/neutral signals, sector, liquidity, volatility, market regime, and annual-range position. Report denominator and coverage, directional accuracy vs SPY, mean excess return, mean absolute prediction error, abstention rate, and baseline comparisons. Use chronological holdout and walk-forward evaluation with embargoes at least as long as the five-session target; don't tune thresholds on the same week being scored. Add confidence intervals before making any claims of improvement; treat sample sizes below 30 as clearly unstable. Corporate-action-adjusted historical data can revise later, so evaluation must use a consistently adjusted basis.

**No competitor model accuracy was independently substantiated by this research.** The novel combination is the user's model + site-aware overlay + strict three-agent implementation + non-duplicated news context + auditable five-session relative outcome ledger. Novelty of a combination is not a market-performance guarantee.
