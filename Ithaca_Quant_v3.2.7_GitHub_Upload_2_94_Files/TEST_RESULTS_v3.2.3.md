# v3.2.3 test report

Verified with locally installed Python/Pandas/sklearn dependencies and mock/synthetic data, **not** with licensed historical records or a live Sharadar API connection.

| Test group | Result |
| --- | --- |
| Group 1 (9 existing modules) | 76 passed |
| Group 2 (8 existing modules + 8 new vendor tests) | 78 passed |
| Group 3 (9 existing modules) | 75 passed; one optional LightGBM feature-name warning |
| Group 4 (9 existing modules) | 69 passed |
| Additional vendor streaming/credential protection test | 1 passed |
| **Distinct tests passed** | **299** |
| `scripts/preflight.py` | PASS |
| `scripts/acquire_historical_data.py --help` | PASS |

Regression cases include permanent security IDs, delisted stocks in full history, missing adjusted prices, stock-universe omissions, ticker reuse, intrahistory missing bars, no-key failure, SPY response validation, ZIP streaming and no credential logging in results.

**Not tested/available:** Real Sharadar API entitlement or downloads, licensed institutional history, actual delisting settlement histories, full-provider-data completeness, Streamlit Cloud deployment with large archives, genuinely forward-recorded predictive returns. A full historical dataset cannot be certified from these offline checks.
