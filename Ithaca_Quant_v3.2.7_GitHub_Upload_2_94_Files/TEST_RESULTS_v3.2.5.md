# v3.2.5 regression report (2026-11-21)

Python 3.13.5, pytest 9.0.2.

| Isolated group | Result |
|---|---:|
| Old source/import/quotes/explorer modules (9 modules) | 53 passed |
| Old release/holdings/news modules (10 modules) | 78 passed |
| Earlier model/audit modules (10 modules) | 100 passed, 1 warning |
| Historical/forecast/analyst/new free-source modules (8 modules) | 70 passed |
| Legacy `tests/test_pipeline.py` | 10 passed |
| **Total** | **311 passed** |

Deployment `python scripts/preflight.py`: PASS (matched v3.2.5 labels, imports/layout, Python syntax).

**Limits:** 5 isolated groups completed; this is not a claim of a single completed all-at-once test run. New Yahoo/SEC source tests used fake injection/mocked responses and offline market samples. Live provider API calls and hosted Streamlit persistence were not verified in this environment. No claims of enhanced live trading returns, point-in-time full universe, or delisting settlement completeness.
