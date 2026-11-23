# Ithaca Quant v3.2 — Test summary

- **271 collected pytest tests** passed in three separate, completed runs (65 + 94 + 112). No all-in-one pytest pass is claimed.
- New v3.2 analyst and allocation tests: **18 passed**, included in the final 112-test group. These use controlled fixtures and mocked provider responses.
- Core model/data/portfolio regression batch: **65 passed**.
- Additional market research and holdings regression batch: **94 passed**.
- Final release, v2.5–v3.1 integrity, and v3.2 tests: **112 passed**.
- Deployment preflight: **passed** matching app/package version, source structure and Python syntax checks.
- One existing optional LightGBM test emitted a non-fatal scikit-learn feature-name warning.

## Boundaries of the test results

No live Yahoo Finance/Finnhub service calls were made from the development runtime; external entitlement, API stability and rate limits remain unverified. The risk optimization was tested for bound/cash/concentration constraints and missing data, not proven outperformance. No licensed CRSP/WRDS dataset was provided, so the historical universe is **not** validated as institutional-grade. The new analyst inputs are observed at fetch time only and are deliberately excluded from historical machine-learning backtests.
