# v0.4 change log and verification

**Baseline:** User v2.8 advanced model zoo and preceding Chrome Companion v0.3 source.

| Category | Implementation | Tests / limitation |
|---|---|---|
| Genuinely fitted agents | Three independent estimators: HGB return, Ridge momentum return, logistic relative-downside event. Normal Chrome call uses fitted `independent_agents.py`, rather than a percentile formula. | Three distinct fitted algorithms confirmed via tests. Sharing market data means errors may be correlated. |
| Leakage prevention | Training snapshots require `label_end < asof`; validation fitting requires `label_end < holdout_start`; validation anchors spaced 5 trading sessions. | Synthetic future-label mutation leaves actual current prediction unchanged. Test passed. |
| Evidence gating | Fixed baseline comparisons for return MAE and downside Brier; abstain on model or gate failure. | Integration fixture correctly withheld unsupported directional signals. Baseline comparisons on synthetic inputs do not establish real-model skill. |
| Historical universe | Dated security membership with identity, future-label checks, provenance for delisting-return complete panel. | Incomplete membership, ticker reuse, missing manifest rejected. Source attestations are not proof of data quality. |
| PIT strategy test | `independent_audit.py` and CLI runner; source SHA-256 manifest, raw prediction and window exports. | Synthetic fixture test passed. No real delisting-aware history supplied. |
| Legacy model zoo | Explicitly isolated as optional research; current-survivor ranking contest cannot promote a model. | Existing v2.8 model-zoo tests pass. Still survivor biased unless supplied historical source is used by strict CLI. |
| Forward accountability | Separate v2.9 SQLite ledger with three agent outputs, evidence snapshot, real as-of prices and later realized return, no duplicates. | Ledger tests passed; no verified live-market win rate yet. |
| Weekly reporting | Wilson intervals, independent issue date counts, MAE against no-alpha zero forecast, sample-size/coverage warnings. | Synthetic ledger reporting tested, no multiple-week real-market run claimed. |
| Performance + reliability | Fast three models, 600-second caching, at most 3 analyses at once, 2 provider retries maximum. | Offline 800-row one-ticker synthetic analysis ~0.23s; hardware/data-dependent. |
| UI | Panel now shows each model, gate outcome, holdout measurements and lifelong forward evidence status. | JavaScript syntax checks pass; live installation not performed in sandbox. |

**The most important limitation:** You cannot fully eliminate survivorship bias or validate future-market accuracy from a synthetic test and a ZIP without point-in-time security and return data. The release refuses to substitute fabricated evidence.
