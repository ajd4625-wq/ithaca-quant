# v3.2.4 test record — 2026-11-21

Python runtime used: 3.13 in the test container.

| Test group | Result |
|---|---|
| `test_agents_retries.py` through `test_pipeline.py` (10 modules) | **63 passed** |
| `test_release.py` through `test_v253_all_news_event_dedupe.py` (10 modules) | **78 passed** |
| `test_v254_early_trend_52w_search.py` through `test_v30_verified_pipeline.py` (10 modules) | **100 passed**, one sklearn / LGBM feature-name warning |
| `test_v31_historical_data_integrity.py`, `test_v321_forecasting_mode.py`, `test_v322_audit_repairs.py`, `test_v323_vendor_historical_data.py`, `test_v324_production_history.py`, `test_v32_analyst_portfolio.py`, `test_validation.py` (7 modules) | **62 passed** |
| Deployment preflight `python scripts/preflight.py` | **PASS** |
| Pytest collection | **303 collected** |

**Total: 303 / 303 passed across four completed groups.** This is not a claim that a single uninterrupted all-in-one execution passed. The historical-production end-to-end tests use **synthetic** data with documented synthetic outcomes to test controls. No real-market predictive performance or licensed provider data quality was verified.

### Out-of-scope / external dependencies

- Live Sharadar/CRSP access: not available; no credentials.
- Streamlit Cloud private persistent storage: not tested.
- Independent settlement source authentication: not available.
- Proven complete point-in-time historical U.S. stock coverage: not established.
- Live portfolio profitability or forecasting superiority: not established.
