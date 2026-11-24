# Ithaca Quant v3.2.6 — SEC delisting evidence audit (free-source upgrade)

## Implemented

1. Added `ithaca_quant/delisted_history.py` to parse SEC submissions for delisting-event filings, separating Forms 25/25-NSE and deregistration Forms 15.
2. Added `scripts/build_delisting_register.py` to download (when run with network access) the SEC public submissions ZIP, fetch older filing pages with fair-access identification, and save an auditable event register.
3. Added archive-vs-SEC audit using evidence-backed CIK crosswalks with explicit detection of missing prices, missing terminal settlements and share-class ambiguity.
4. Added checksums and defensive SEC ZIP member/size validation; ignored SEC form data cannot be transformed into a claimed trade price.
5. Added 11 new regression tests, a manually triggered GitHub SEC-data workflow, and kept historical source data out of GitHub.

## What is not solved

No live SEC data was fetched in the generation environment. This package does not include a complete list of historical securities, daily prices of delisted stocks, or verified terminal payoffs. A free SEC delisting register cannot replace a survivorship-bias-free US equity security master or trading archive. Current Yahoo live research still has the known survivorship limitations.

See `DELISTED_STOCK_HISTORY_v3.2.6.md` for setup and audit limitations.
