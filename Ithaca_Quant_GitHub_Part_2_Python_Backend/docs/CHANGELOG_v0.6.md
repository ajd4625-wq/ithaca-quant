# Chrome Companion v0.6 — v3.2 merge

**Source:** user-supplied `Ithaca_Quant_v3.2_Analyst_Portfolio_Intelligence(1).zip`.

1. Copied the v3.2 `ithaca_quant` package into the local research bridge (retained companion-specific independent 3-ML agents, historical research, and ledger modules).
2. Added `backend/analyst_bridge.py` with source-attributed current opinion snapshots, explicit provider failure states, bounded transient retries, sensitive URL/key redaction, a small observation-only SQLite database, and 15-minute opinion cache.
3. Added a read-only 20-stock portfolio research API using v3.2 `portfolio_allocation_study`. Current value is calculated from unadjusted intraday quotes (if provider returns them) or explicitly user-supplied unadjusted price inputs; historical volatility uses *separate* adjusted daily closes. Rejects stale quotes relative to completed bars and incomplete price histories.
4. Added on-demand analysts and a virtual-holdings input workflow to the side panel. Holdings are saved in Chrome local storage only when the user explicitly clicks Save; the backend does not persist portfolio holdings and places no orders. Supports CSV export.
5. Added an endpoint-size bound, Chrome origin restriction, and one-at-a-time portfolio study limiter, with at most 3 analyst-fetch workers and at most 2 controlled retries per operation.
6. Kept analyst sentiment **out of** the trained model. It can affect a small research-only portfolio preference if fresh; up to three previously cached, validated forecast inputs per model type can contribute, without retraining or altering the accuracy ledger.
7. Kept historical v3.1 audit code, legacy CLI compatibility, three fitted learners, news/SEC research, overlay and 52-week diagnostics.
8. Started a **separate** v3.2 three-ML forward-outcome SQLite ledger, so version comparison remains possible without silently mixing predictions. New analyst snapshots are observation-only and not historically backfilled.
9. Tests: 67 Python offline cases passed; JavaScript syntax checks passed. No live-market predictive advantage verified.

### Known limitations

- Analysts and price targets can be delayed, incomplete, subject to licensing, or reflect very different time horizons.
- Source-code checksums cannot validate the existence or authenticity of a complete market-history dataset.
- Normal Chrome stock forecasts are based on completed daily adjusted closes, not visually interpreted charts or guaranteed real-time quotes.
- The portfolio study is a hypothetical long-only covariance research tool and excludes real-world execution, taxes and independently verified prospective alpha.
- Opening the extension in Chrome and authenticated provider endpoints must be tested on the user's own system.
