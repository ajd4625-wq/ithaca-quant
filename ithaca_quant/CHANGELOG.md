# Changelog

## v1.4.0 — November 12, 2026

- [Extensive feature-by-feature release notes](RELEASE_NOTES_v1.4.md).
- Versioned local SQLite cache for NYSE/Nasdaq screened snapshots, price matrices and first-seen headline archives. Auto-resume existing saved market samples; no repeated multi-year downloads on normal refreshes.
- New **full scan** vs **incremental refresh** buttons, 20-minute active-screen auto-refresh, five-minute deep-history check, two-minute news cache, 15-second priority quote refresh with size/rate safety.
- Daily market model excludes incomplete daily bars until after 5 p.m. New York time; split-adjustment revisions trigger targeted complete history repair rather than splicing inconsistent series; stale refresh falls back visibly.
- Official SEC reported-quarter extraction, filed-date-aware revenue growth/margins and point-in-time features, with optional administrator contact and Yahoo display-only quarterly fallback.
- Conservatively timestamped news archive; historical news predictors become eligible only after sufficient actual observed history and chronological model-selection improvement. Current headlines never retroactively enter older backtests.
- Chronological model selection compares market-only against optional SEC/news factors and requires measured training-holdout MAE gains. Independent backtesting remains necessary.
- Main hypothetical price endpoint NO LONGER includes unvalidated word-level news price shifts. Experimental headline sensitivities are retained as separate labeled scenarios, not marketed as accurate market predictions.
- Preserves time-bounded 1D chart, risk estimates, quote provider alternatives, full-market portfolio, 3 research score components, 3 parallel data workers and 2 application-level retries.

## v1.3.0 — November 2026

- [Detailed per-change notes](RELEASE_NOTES_v1.3.md) for implementation details, math, usage, and limitations.
- **Automatic current-news context in the instant stock explorer:** dated source-attributed headlines retrieved and cached per ticker, with seven-day freshness, duplicate removal, relevance weighting, transparent word-level sentiment, and explicit missing-data warnings.
- **News sensitivity for individual estimates:** separate baseline and bounded hypothetical current-news scenarios for return, illustrative target price, boom estimate, and risk-stress range. Numerical changes are NOT learned or historically validated causal news effects.
- **1D news context:** only same-day ET news contributes a capped ±0.2% experimental adjustment to a valid intraday projected endpoint. It does not fabricate a 1D forecast when the market is closed or bars are stale.
- **1D chart time bounds:** exact first actual price bar to latest observed bar or valid same-day forecast endpoint; no midnight-to-open empty period, no next-day extrapolation. Hourly axis labels and precise hover timestamps retained.
- **Optional generative AI sourced headline explanation:** only when the server has an `OPENAI_API_KEY` and a visitor clicks the generate button. Private server secrets never enter code or logs. Optional model text does not control numeric scenarios.
- **Five-stock news comparison in the leaderboard:** displays price-model forecast, news sensitivity, boom scenario, stress estimate and publisher counts, sorts only the analyzed subset and exports CSV.
- **Preserved:** instant independent ticker lookup, broad-market scanner, historical price/volume ML model, backtesting without news leakage, 3 scoring agents, 3 worker limit, 2 retries, company profiles, live/delayed quotes and simulated portfolio.


## v1.2.0 — November 2026

- Chart ranges now strictly bound displayed observations: 1D uses today-only Eastern-time intraday bars; 5D uses up to five observed trading sessions; 1M, 6M, YTD and 5Y are exact historical calendar windows.
- 1D axis uses time-of-day ticks and hover timestamps; no stale yesterday-price fallback.
- Forecast extensions matched to each range: 1D next up to 2 market hours (experimental momentum heuristic), 5D next session, 1M next 5 sessions, 6M/YTD next 20 sessions and 5Y next 60 sessions (daily SPY-relative ML).
- Short-term projections are disabled outside the trading session, on stale quotes, and when intraday history is insufficient. Dotted lines remain endpoint illustrations, not per-minute predictions.
- Kept existing broad screener, news, risk metrics, 3 scoring components and 2 app-level retries.


## v1.1.0 — November 2026

- Search bar above the research settings; on-demand training for one selected
  ticker and SPY, independent of the NYSE/Nasdaq marketwide scan.
- 1D, 5D, 1M, 6M, YTD and 5Y price chart windows; short windows try intraday
  provider observations, otherwise show clearly labeled recent daily closes.
- Dotted straight segment to one model-derived endpoint (not a daily path),
  with technical review conditions, risk metrics and on-demand company news.
- Preserved the full-market workflow, 3 scoring components and two retries.

## v1.0.0 — November 2026

- Promoted the v0.8 stock search and financial news interface to a clearly
  labeled v1.0 release, with one authoritative Python version constant.
- Updated Mac and GitHub-to-Streamlit deployment instructions.
- Clarified that live news is an *unvalidated overlay*, not part of a
  historically trained news-driven forecasting model.
- Preserved existing 3-component research ranking and at most 2 application-level
  retries per failed network operation.
- Retained historical validation, broad exchange discovery, quotes, virtual
  portfolio and company metadata functions without changing their formulas.

### Known limitations

- Python environment and live external feeds must be configured and tested
  on a machine with network access.
- Yahoo quote freshness varies; optional real-time IEX covers IEX trades only.
- Watch/review dates are rules-based checkpoints, not optimal trading dates.
- No verified live-prediction edge or brokerage execution capability.
- Exchange-wide research is resource-intensive and subject to rate limits.

## v0.8

- Stock search page, news links, hypothetical price scenarios, news overlay.

## v0.7

- Three transparent ranking score components, up to two app-level retries.

## v0.6 and earlier

- Historical validation, company metadata, leaderboard, marketwide screener,
  quotes, predictions, risk analysis and hypothetical portfolio.
