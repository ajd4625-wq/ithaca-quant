# v3.2.7 testing and limitations (2026-11-23)

- 36/36 passed: cloud sample, model-selection, historical integrity, delisting checks.
- 68/68 passed: deployment/release checks, historical production, free history,
  analyst portfolio, research compatibility.
- 94/94 passed: quote/data, chart, leaderboard, metadata, news, accuracy and
  portfolio compatibility.
- 49/49 passed: additional newsletter, events, entry/watch, Form 4 and account tests.
- 69/69 passed: weekly reports, model zoo, validation, backtests, safeguards,
  historical vendor conversion.

**316 distinct tests passed in completed groups.** Five historical tests in
`test_v251_leaderboard_catalysts.py` failed, **unchanged from the original
v3.2.6 baseline**, due to pre-existing entry-signal label/score expectations;
the other six tests in that file passed. Therefore the full suite is **not
clean**. One large combined legacy test invocation timed out; do not count
that run as passed.

- Syntax compile and deployment preflight passed.
- Local synthetic 12-stock / 2-window walk-forward simulation replayed the
  actual three-model tournament successfully.
- Live Streamlit Cloud behavior, active provider rate limits, and the precise
  underlying production exception are **not verified**. No performance/return
  improvement is claimed.

This update reduces the browser validation workload, **not** the need for
complete historical records, delisting outcomes, or forward predictions.
