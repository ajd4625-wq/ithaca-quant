# Ithaca Quant v3.2 — Analyst-informed portfolio research

## Overview

This update builds on v3.1 without changing the existing three-model tournament. It adds a separately labeled analyst-research workflow to **My portfolio** and a risk-aware hypothetical weight study for currently owned positions.

### What it does and how to use it

1. Open **My portfolio** and unlock your existing saved virtual holdings. Complete share counts and purchase prices are still read from the existing ledger.
2. Open **Portfolio intelligence — Wall Street analyst consensus + risk**. Select **Yahoo Finance (best effort)**, or configure an authorized **Finnhub** token with `FINNHUB_API_KEY` in Streamlit Secrets and choose Finnhub.
3. Set an **illustrative cash reserve** and per-position cap. Defaults are 10% and 20%. Existing holdings are never changed by the controls.
4. Press **Refresh analyst opinions and risk research**. The code requests fresh third-party analyst recommendation counts and mean price targets for each owned stock, plus recent firm-attributed upgrades/downgrades when available. A missing feed is reported as unavailable, not imputed.
5. Review coverage, source, provider period, timestamp, target upside relative to the latest retrieved quote, and named firm actions. Download the observed analyst snapshot as CSV for your personal research records.
6. Where quotes and at least 126 synchronized daily returns are complete for every holding, review a **hypothetical weight study**. It compares current weights with bounded risk-aware weights, cash reserve, turnover, historical volatility and per-stock risk/conviction signals. Export CSV if useful. **No orders are placed.**

### Modeling and safeguards

- The three production forecasting models **do not change**. Broker analyst opinions influence only the new **research allocation** and are deliberately given a small tilt; their historical predictive value has not been proven. Actual consensus counts are shrunk to zero when there are fewer than 3 analyst opinions.
- The new research optimizer uses approximately 2 years of synchronized historical adjusted daily prices, requires at least 126 complete daily returns, shrinks covariances 55% toward independent asset risk, and includes turnover and position cap controls. It refuses missing prices, unavailable quotes or incomplete securities.
- Broker targets can have horizons that differ from the program's 20-session forecasts; they are **not** treated as future 20-day excess returns.
- Recommendation history returned today **is not point-in-time historical training evidence**. Snapshots carry provider, retrieval timestamp and source period; old returned rating periods fail freshness checks. There is **no claimed uplift** in accuracy from analyst opinions.
- Data from Yahoo Finance can be absent or rate-limited. Finnhub requires a valid paid/free account and an active key with the required endpoint entitlements. Access rights and licensing are the user's responsibility. No credentials are stored in exported CSV files.
- Sector constraints, taxes, market impact, granular order execution and independently verified prospective alpha are **not solved** by this upgrade. Weights are hypothetical research signals, not investment instructions or real trading advice.

### Known evidence and data constraints

- No live Yahoo/Finnhub account credentials were available in the development environment; provider adapters were tested using mocked responses and official field structures, not against a live subscription.
- No authorized CRSP/WRDS institutional dataset was provided. Earlier historical-data integrity features remain available but cannot certify dataset provenance or completeness without external source files.
- Historic performance of the analyst-influenced allocation has **not** been measured in a point-in-time test because contemporaneous analyst history is not bundled. The existing model's past results must not be presented as proof of this allocation strategy.

Run `python scripts/preflight.py` and `pytest -q tests/test_v32_analyst_portfolio.py` to verify the major added code paths.
