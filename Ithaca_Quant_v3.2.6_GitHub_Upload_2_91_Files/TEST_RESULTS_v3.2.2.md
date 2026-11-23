# Ithaca Quant v3.2.2 — offline test results

Tests were run in four independently completed groups using the available offline Python environment (Python 3.13, pytest 9.0.2):

| Group | Tests passed | Result |
| --- | ---: | --- |
| Core app, feeds, UI data, releases, incremental refresh (through v1.4) | 86 | Passed |
| Holdings and v2.2–v2.5 compatibility/portfolio/news tests | 78 | Passed |
| v2.1, v2.6–v2.8 modeling, audits and ranking | 40 | Passed (1 warning) |
| v2.9–v3.2.2 audits, historical archives, model competition, analyst data, regression fixes | 86 | Passed |
| **Total** | **290** | **Passed** |

`python scripts/preflight.py` passed the folder-layout, version-label and Python-syntax checks. `python -m compileall -q app.py ithaca_quant scripts tests` also completed without errors.

The tests use offline synthetic data and mocked market-provider responses for relevant features. The app was not deployed to Streamlit Cloud, live Yahoo Finance connectivity was not exercised, and no forward market accuracy improvement was established. The full suite was split because some combined runs exceeded the interactive runtime limit; all 290 collected tests passed in four separate completed runs.

## Audit checks added

- Stale latest-session stock quote excluded from screen
- Correct vendor trading-close price used in screen when available
- Missing current volume excluded
- Adjusted and vendor close prices captured separately
- Missing `Adj Close` explicitly reported as a price-only fallback
- Trading-price fields survive SQLite cache, merged refresh and cutoff
- Negative, NaN, infinite, invalid and leveraged holdings rejected
- Weekly/monthly and duplicate-date price histories rejected by portfolio analysis
- Legacy Yahoo caches missing vendor close must be replaced rather than spliced

## Remaining limitations

Code tests do not authenticate delisted company histories, stock listings at each historical date, corporate-action coverage, point-in-time analyst ratings, broker execution, live cloud deploy, or positive predictive edge. These require external validated data and forward observation.
