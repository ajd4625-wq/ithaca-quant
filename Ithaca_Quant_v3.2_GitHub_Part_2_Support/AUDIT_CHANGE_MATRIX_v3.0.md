# Ithaca Quant v3.0.0 — Issue-by-issue resolution matrix

The table distinguishes **implemented code repairs** from evidence that **cannot be supplied or certified by modifying code**.

| # | Issue | Code update | Status |
|---|---|---|---|
| 1 | Backtesting did not replay the three-model competition | Production `forecast_asof(..., competitive_agents=True)` invoked for every signal date with trained-only-on-matured labels | Implemented; synthetic integration tested |
| 2 | Backtest filtered selections on later outcome availability | Candidate selection no longer reads `forward_return.notna()` | Implemented; regression tested |
| 3 | Today's survivors contaminate historical universe | Archived dated constituency check, missing constituent/outcome failures, optional archived delisting payoffs; **cannot verify whether a supplied universe is complete** | Guardrails implemented; authentic archive externally required |
| 4 | Challenger faced a reduced incumbent | Identical full/fast sizing, dynamic feature selection, shrinkage pipeline for incumbent at each historical checkpoint; reject changing feature schemas | Implemented; tested on synthetic data |
| 5 | No demonstrated live advantage | Immutable champion and incumbent pairs, identical stock/time, forward-only resolution, independent-window bootstrap, pending/uncertain state | Instrumentation implemented; **advantage not established** |
| 6 | Missing terminal closes silently erase losses | Selected/entered positions must have real final closes or archived end-of-horizon total-return payoffs; otherwise stop, with bankruptcy `-100%` counted | Implemented; regression tested |
| 7 | Eight windows insufficient to pick winners | Minimum 20 nonoverlapping observations in EACH selection and audit block; immature sample fails closed | Implemented; may sharply reduce winners |
| 8 | Overfitting to many stock/model contests | Select only using selection block, independent audit paired p-value, BH false discovery adjustment q≤0.05 | Implemented; no statistical test guarantees future performance |
| 9 | Three agents trained on same 13 inputs | Distinct technical/regime, technical/news/earnings, and technical/fundamental/Form4 feature views where point-in-time archives exist; no retroactive data usage | Code supports; authentic old filings/news not bundled |
| 10 | MAE alone is not portfolio/ranking objective | Additional directional, cross-sectional Spearman rank IC, and cost-aware top-N paper performance nondegradation gates; actual next-close simulation for final strategy | Implemented; paper metrics not executable performance |
| 11 | Uncertainty based on losing model | Winning forecast uses contemporaneous three-agent vote spread; OOS residual error separately retained | Implemented |
| 12 | Missing volume treated as 0 | Null volume preserved and rows without mandatory volume observations excluded | Implemented; regression tested |
| 13 | Absolute price target presumed flat SPY | Conditional historical SPY-return scenario and clearly marked scenario ranges instead of a standalone guaranteed target | Implemented; absolute-market skill not demonstrated |
| 14 | Gain/boom probabilities not calibrated to winner | Winner-linked selection-trained mapping, independently checked Brier; unverified odds suppressed as NA | Implemented; may leave many NAs |

## Performance claims that are *not* made

- No assertion of 80%, 90%, or other fixed stock-price prediction accuracy.
- No assertion of live superiority until adequate, timestamp-eligible **real** outcomes mature and demonstrate improvement. Even a statistically supported *preliminary* forward edge is not independently authenticated.
- No assertion that the default currently traded universe is survivorship-bias-free.
- No assertion that `historical_archive` in a CSV is cryptographically or independently authenticated.
- No assertion that all 246 software tests prove prediction performance: they use mock/synthetic datasets for model-validation tests.

See `RELEASE_NOTES_v3.0.md` for precise usage, limitations, and data prerequisites.
