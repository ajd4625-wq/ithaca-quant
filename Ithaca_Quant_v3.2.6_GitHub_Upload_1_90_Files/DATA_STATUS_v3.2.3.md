# Historical data availability — v3.2.3

| Component | Current state | Evidence |
| --- | --- | --- |
| Vendor acquisition code | Implemented | `scripts/acquire_historical_data.py`, `ithaca_quant/historical_vendor.py` |
| Permanent IDs (provider permaticker) | Implemented in conversion | Synthetic tests; no licensed full export supplied |
| Delisted security inclusion | Implemented when present in vendor data | Requires licensed Sharadar TICKERS/STOCKS data |
| Original and adjusted closing prices | Implemented in conversion | Reads vendor `closeunadj` and `closeadj`; rejects missing |
| Missing source security detection | Implemented | Source security listing dates must have corresponding prices |
| Daily coverage >95% | Implemented screening | Fails if a stock's documented listing session history is largely missing; legitimate halts may need manual inspection |
| Corporate action audit | Partial | Reads event rows and counts ticker-change events, but does not rebuild every payout |
| Verified delisting settlement payoffs | **NOT acquired** | Cannot infer cash/stock consideration from last observed trade |
| Full licensed institution-grade U.S. equities dataset | **NOT acquired** | No authorized source credentials, entitlement, download or redistribution permission available in this environment |
| Independent data completeness certification | **NOT established** | Vendor fidelity requires reconciliation and third-party evidence |
| Institutional-scale out-of-core processing | **NOT supported by existing archive UI** | Current ZIP loader has 300 MB uncompressed file cap and pivots into memory |
| Live-market stock prediction advantage | **NOT established** | Requires mature forward-recorded forecasts |

**Practical next action:** On a system with a licensed Sharadar API entitlement, run the downloader, inspect the JSON coverage report, and provide the private generated data archive through an appropriately secured channel. Do not commit vendor history or keys to GitHub. Until this happens, data limitations are real, not repaired by this code update.
