# Changelog

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
