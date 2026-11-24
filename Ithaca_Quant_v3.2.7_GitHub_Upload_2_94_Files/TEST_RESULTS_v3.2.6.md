# v3.2.6 test results (Nov 23, 2026)

- **47/47 passed:** historical archive integrity, vendor conversion, archive production training, Yahoo+SEC free-history compatibility, verified forecast pipeline, and 11 new delisting-event registry tests.
- **71/71 passed:** release/version checks, import integrity, v2 adapter compatibility, core portfolio and tournament safeguards, analyst/portfolio compatibility, and v3.2.2 data-quality repairs.
- **Deployment preflight passed:** Python parsing, files and app/package version sync.
- SEC register CLI exercised end to end with a **synthetic SEC-format ZIP fixture**; generated 2 labeled filing events and a correctly non-certified coverage manifest.
- Another combined legacy test group **timed out without completing**. Its partial dot output is NOT counted as a pass or as proof of a failure.
- **External download NOT tested:** local runtime DNS/network access to SEC and Yahoo unavailable. No complete real delisting price or settlement dataset was acquired.

**Total independently completed tests in this v3.2.6 run: 118 passed.** The previous v3.2.5 report counted 311 tests on its version; those results are not evidence that the entire v3.2.6 suite passed.
