# Audit — v3.2.1 problems and v3.2.2 disposition

| Area | Observed v3.2.1 issue | Disposition in v3.2.2 |
| --- | --- | --- |
| Marketwide scans | A missing latest quote was forward-filled up to two trading sessions, making non-current stocks appear tradable | **Fixed:** require observed last-session quote and volume |
| Marketwide scans | Missing volume was turned into zero and recently quoted liquidity coverage was not separately checked | **Fixed:** retain missingness and require 15/25 sessions of volume and observed dollar-liquidity coverage |
| Historical price sources | Yahoo downloaded `auto_adjust=True` only, so the separate vendor trading-price series was unavailable | **Fixed:** capture `Adj Close` and vendor `Close`, with explicit price-only fallback if needed |
| Data refresh & cache | MarketData `raw_close` was discarded by completed-session trimming, cache serialization and merging | **Fixed:** preserve matching dates and symbols throughout refresh and cache lifecycle |
| Upgrade path | v3.2.1's price-only cache could otherwise mix with the new raw/adjusted schema | **Fixed:** full replacement or retain as visibly stale on provider failure |
| Portfolio allocation | Negative/NaN/Infinity positions disappeared before validation when choosing positive holdings | **Fixed:** validate the full supplied weight dictionary first |
| Portfolio risk | Duplicate trading dates and weekly bars could distort annualized daily risk | **Fixed:** reject duplicate/missing dates and obviously non-daily series |
| Regression suite | A weekly-scorecard assertion depended on the day the test happened to execute | **Fixed test:** deterministic resolution timestamp in the correct week; weekly report logic intentionally unchanged |
| Deployment reliability | No repo push/PR regression gate in the GitHub package | **Fixed:** added `ithaca-ci.yml` |
| External market coverage | No independently authenticated, complete historical delisted-security dataset | **Not solved by code:** authorized external records still required |
| Predictive validation | No independent live-market proof of alpha | **Not solved:** accumulate and score timestamp-eligible real-world forecasts |

**Scope:** This is a focused source and regression audit, not an exhaustive static/dynamic/security assessment. It cannot establish that all possible bugs were found.
