# v3.2.1 model-mode hotfix verification

- Deployment preflight: PASS (`python scripts/preflight.py`).
- Focused mode + prior release + portfolio + chart + deploy/import tests: 49 passed.
- Independent compatibility tests (data, holdings, quotes, agents, chart, validation): 48 passed.
- Total completed tests in those two groups: **97 passed**.
- An earlier larger combination including compute-heavy model competition exceeded the command timeout without a final summary; it is **not** reported as passing.
- No live feed or hosted Streamlit app was tested from this environment. The fix corrects a deterministic flags conflict; a separate provider/data outage may still prevent a forecast.
- Existing real-market forecast accuracy is not affected or verified by this hotfix.
