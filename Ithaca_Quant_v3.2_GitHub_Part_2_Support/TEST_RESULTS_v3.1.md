# Ithaca Quant v3.1.0 — Regression and data-integrity test report

**Environment:** Python 3.13, pandas/numpy/sklearn available. **Date:** 2026-11-20.

## Completed tests

- Group 1: **50 passed**, including historical archive integrity and the new strict delisting backtest.
- Group 2: **44 passed**, with one optional LightGBM feature-name warning.
- Group 3: **69 passed**.
- Group 4: **47 passed**.
- Group 5: **43 passed**, executed as six independent modules: 3 + 10 + 3 + 9 + 10 + 8.

**Total: 253/253 tests passed in completed isolated runs.** The full all-in-one single-process suite was *not* claimed as completed: earlier combined runs exceeded the process time limit. This report counts only completed test runs.

**Preflight:** `python scripts/preflight.py` passed: matched release versions, checked required package layout, parsed the Python source.

**End-to-end mock tests:** a synthetic PIT archive was loaded, its historical securities reconstructed, exact active membership enforced, and a delisting total-loss payoff scored rather than erased. An earlier SEC restatement was tested against later amended vintages. These are software correctness tests, **not live stock forecast accuracy tests**.

## Limitations not verified

- No genuine vendor dataset was supplied. Data integrity checks prove the input files are unchanged after manifest creation, **not** that the source is authentic or complete.
- No complete delisted stock universe, independently validated historic index membership, actual delisting payoffs, or original market-adjustment methodology were acquired. Users must provide these from licensed/primary sources.
- No prospective or independently verified live-market return advantage was demonstrated.
- Historical next-close simulation remains a non-executable research proxy.
- Streamlit Cloud deployment, cloud persistent jobs, and external data-provider reachability were not tested here.
