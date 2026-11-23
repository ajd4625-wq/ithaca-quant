# Ithaca Quant v3.2.3 — real historical-data sourcing

**Implemented:** A downloader for official licensed Sharadar stocks, permanent security IDs, corporate actions and SPY benchmark; a converter to point-in-time market archives; complete expected-security presence checks; price/corporate-action basis separation; identifier collision protection; explicit missing terminal-payoff handling; license-safe `.gitignore`; UI signposting and synthetic integration tests.

**Not implemented/NOT delivered:** A complete historical U.S. equity dataset, licensed CRSP rights, verified cash-merger and delisting settlements, direct streaming of multi-gigabyte history in Streamlit, or actual measured predictive improvement. Those require external authorized provider records and/or further engineering. The data vendor service was not reachable in this sandbox, and no license credentials were supplied. No vendor download has been claimed successful.

**Use:** Follow `HISTORICAL_DATA_SOURCE_v3.2.3.md`, create a private historical ZIP on a system with source credentials, then upload it to the existing Walk-forward tests tab. Keep raw vendor data out of GitHub.
