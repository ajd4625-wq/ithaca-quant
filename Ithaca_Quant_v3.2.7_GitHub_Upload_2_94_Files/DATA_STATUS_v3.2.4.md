# v3.2.4 — Actual data availability status

| Component | Implemented in code? | Authentic records delivered in this package? |
|---|---|---|
| Authorized Sharadar API acquisition | Yes, inherited from v3.2.3 | **No credentials or live download** |
| Historical active + delisted securities | Yes, from licensed exports | **No full market export** |
| Point-in-time permanent identities | Yes | **No authenticated provider identity files** |
| Original and adjusted close prices | Yes | **No authenticated prices** |
| Documented settlement payoff importer | Yes, v3.2.4 | **No source settlement records** |
| Delisting labels included in model training | Yes, v3.2.4 | Requires authenticated payoffs |
| Private archive source used in actual production predictions | Yes, v3.2.4 | Enabled only when configured and sufficiently complete |
| Private archive source used in scheduled predictions | Yes, v3.2.4 | Enabled only when configured |
| Real-market outperformance proven | No | **No** |

**Test evidence:** Synthetic end-to-end checks verify integration, loss preservation, missing-data refusal and source selection. Tests cannot certify vendor honesty or licensed redistribution. A compiled application and a data vendor contract are different things.
