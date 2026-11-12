# Changelog

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
