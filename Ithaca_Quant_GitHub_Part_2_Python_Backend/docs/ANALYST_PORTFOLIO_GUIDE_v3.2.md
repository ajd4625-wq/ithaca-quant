# Analyst and portfolio research in v3.2

## Where to go

Open **My portfolio** → unlock your portfolio → **Portfolio intelligence — Wall Street analyst consensus + risk**.

Yahoo Finance is selected by default and uses `yfinance.Ticker.get_recommendations_summary()`, `get_analyst_price_targets()`, and `get_upgrades_downgrades()`. These methods may be temporarily unavailable. Official documentation: <https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html>.

For Finnhub, set the `FINNHUB_API_KEY` server secret. The implementation uses the official recommendation trends, price-target and upgrade/downgrade API endpoints. Consult <https://finnhub.io/docs/api> for plan availability and terms. Do not put a key into your holdings CSV or publicly share it.

## Interpreting the analyst information

- **Analyst count** is the number of recommendations in the provider's latest reported snapshot, not a claim that all analysts are independent or updated today.
- **Strong buy / buy / hold / sell / strong sell** are external opinions; they are not guaranteed predictive signals.
- **Mean price target** comes from an outside provider and may use a longer horizon than Ithaca's 20-session forecast. Its difference from today's quote is not an expected 20-session stock return.
- **Attributed actions** show actual provider-supplied broker firms and their latest upgrade/downgrade directions. These are context, not a trading algorithm.
- **Observed UTC** indicates when Ithaca requested data, not when the provider originally received the opinion. A fresh download does not make stale ratings fresh.

## How portfolio study weights are computed

The study uses currently owned securities, never invents a new universe or silently buys/sells companies. With current quotes and complete daily price histories, it estimates annualized covariance, shrinks the matrix toward individual variances to avoid noisy correlations, and solves a constrained long-only portfolio allocation. It limits concentration by the selected cap, holds a cash reserve where feasible, penalizes sudden changes to current holdings, and gives only a modest preference to recent Ithaca forecasts and sufficiently covered, fresh analyst opinions.

If a stock has no valid price, fewer than 126 synchronized return observations, or a missing/invalid quote, no portfolio weights are produced. The purpose is to prevent false precision, not to guarantee lower future risk.

The weight differences are **not orders**. The app has no brokerage permissions or automated execution capability. Downloaded CSVs contain research outputs only.

## Historical market-data quality

The prior v3.1 point-in-time stock data archive system remains supported. A research-grade history requires a legitimate security-level historical provider export including delistings, price adjustments, and dated universe membership. You must obtain the records with appropriate permissions; no institutional dataset is bundled or simulated. Analyst data fetched today must never be backdated for historical model testing. Save genuine observed snapshots prospectively if you want to evaluate those opinions later. See `HISTORICAL_DATA_GUIDE_v3.1.md`.
