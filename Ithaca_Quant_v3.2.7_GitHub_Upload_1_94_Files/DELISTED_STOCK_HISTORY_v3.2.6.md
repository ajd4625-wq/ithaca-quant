# Ithaca Quant v3.2.6 — delisting event evidence and historical-coverage audit

## What this upgrade actually gives you

The program can now build a **real, public SEC-filed delisting EVENT registry**. It does **not** provide a complete U.S. delisted-stock price and payoff database. The source is official EDGAR submissions, not recreated prices. The SEC's free filings cover registrants and reporting events; they are not a survivorship-free trade database.

- Form **25 / 25-NSE**: an exchange-delisting filing, not necessarily for common shares, and the filing date is not the final trading day.
- Form **15**: reporting deregistration, **not** equivalent to an exchange delisting.
- **CIK**: an issuer's identifier; it can refer to multiple share classes. Never treat it as a unique permanent security ID.
- SEC filings **do not** provide every daily stock bar, all delisting cash/stock settlement terms, or comprehensive historical index memberships.
- Older filings can be in additional EDGAR submission JSON pages. The tool can fetch them separately and marks them missing when not fetched.

## Get an evidence register from the SEC (free)

Official SEC public bulk download: `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`.

The following command must run on a computer/host with internet access and ample space. Use a genuine contact email in the environment (never in GitHub source):

```bash
export SEC_CONTACT_EMAIL='your-actual-contact@example.org'
python scripts/build_delisting_register.py --download-sec-bulk --fetch-older --out .ithaca_delistings
```

Alternatively download the ZIP yourself from the official SEC website and run:

```bash
export SEC_CONTACT_EMAIL='your-actual-contact@example.org'
python scripts/build_delisting_register.py --sec-submissions-zip /private/path/submissions.zip --fetch-older --out .ithaca_delistings
```

`--fetch-older` may require many rate-limited requests; cached pages resume automatically. The SEC download may be large. Observe SEC fair-access guidance; do not use an invented email.

Output: `sec_delisting_events.csv` and `sec_delisting_manifest.json`, with original EDGAR filing references, checksum, and explicit coverage warnings. Neither is a price file. `older_filing_histories_complete` only describes whether referenced older SEC filing pages were fetched; it is not a claim that every stock delisting exists.

## Audit an existing point-in-time market archive

If you already have a security-ID-based archive with an **evidence-backed CIK column** in `security_master.csv`, run:

```bash
python scripts/build_delisting_register.py --sec-submissions-zip /private/path/submissions.zip --fetch-older --out .ithaca_delistings --audit-archive /private/path/market-history.zip
```

This produces `delisting_coverage_audit.csv/json` with missing archive identities, missing prices, and missing *documented* terminal payouts. An SEC event linked to a CIK with multiple share classes remains unresolved. Presence of some payoff rows is not proof of complete payoff coverage.

**Do not feed `sec_delisting_events.csv` into a backtest as if it were total-return prices or membership snapshots.** To run an unbiased historical backtest you still require historical all-share security IDs, dated listing/eligibility records, original and adjusted daily prices, and security-specific terminal cash/stock distributions or defensible settlement evidence. Missing returns must remain missing and block certification.

## Data quality status (Nov 2026)

- SEC event register **code**: implemented, and verified on offline fixture data.
- Actual full SEC event register: **not downloaded in this environment** (network to SEC blocked).
- Real delisted daily OHLCV and corporate-action history: **not obtained**.
- Historical entire-U.S.-market universe: **not obtained**.
- Documented delisting payoffs for every security: **not obtained**.
- Complete, survivorship-bias-free dataset: **not achieved**. This cannot be attained solely from Yahoo Finance and EDGAR.

Possible future data sources include verified historical exchange records, security-level corporate-action records, an authorized CRSP/Sharadar-equivalent archive, or documented case-by-case terminal settlements. Use the records only within their distribution terms.

## No-terminal GitHub workflow

After uploading both application packages, create a repository secret called `SEC_CONTACT_EMAIL` containing your real SEC contact email. Go to **Actions → Build SEC delisting evidence register (manual) → Run workflow**. Optionally choose **include older filings**, recognizing that it can take a long time and may time out. When completed, GitHub Actions provides a short-lived artifact with the event CSV and quality manifest. It intentionally excludes price histories and SEC bulk ZIPs, and never labels the event list complete U.S. stock history.
