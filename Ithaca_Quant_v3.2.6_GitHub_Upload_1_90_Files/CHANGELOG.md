# v3.2.6 — SEC delisting event register + evidence-linked coverage audit

- Official EDGAR delisting filings as documented evidence; no fabricated historical trades or payoffs.
- Added event and security-archive reconciliation, fair-access bulk downloader, and older submission pages.
- Data remains incomplete: this is NOT a complete institutional-grade delisted universe.

# v3.2.4 — Private archival training + documented terminal settlement support (2026-11-21)

- Added `ithaca_quant/production_history.py`: a server-private historical archive can now supply production model training labels from permanent-ID historical securities (including delisted stocks). Yahoo is used ONLY for the contemporaneous stock features, not as a substitute for the archived training population.
- Connected the same archived mode to scheduled daily forecast logging in `scripts/daily_forecast_job.py`.
- Added `ithaca_quant/terminal_settlement.py` and `scripts/attach_delisting_settlements.py`: convert **source-documented incremental delisting settlement ratios** into as-of/entry total-return labels. Strictly rejects ratios already included in prices (e.g., inclusive CRSP CIZ returns). A last-day signal with no next-day executable quote may have a missing entry-return value; it can never become an imaginary fill.
- Added `scripts/check_historical_training.py` and synthetic regression tests for missing delisting payoffs, full production forecasting, source/date collisions, and unsafe fallbacks.
- Rejects explicitly synthetic/demo archives for production and refuses to fall back to Yahoo when a configured private archive is missing or fails quality controls.
- Archived cross-sectional ranking features are neutralized when the current Yahoo universe is not comparable in breadth.
- No licensed source credentials or original CRSP/Sharadar data were accessible in this session. The DATASET ITSELF HAS NOT BEEN ACQUIRED. No claim of independent provenance certification or verified live performance is made.

# v3.2.3 — Authenticated historical data acquisition (2026-11-21)
- Adds real Sharadar licensing-based bulk acquisition of active/delisted stocks, securities master,
  official SPY ETF benchmark and corporate actions, with no fictional prices or settlement values.
- Maps permanent security identifiers, original trading closes, full dividend/split adjusted closes
  and observed session-by-session historical stock eligibility, not today's survivor ticker list.
- Rejects missing listed securities from the vendor price file and reused ticker identities.
- Keeps credentials, raw licensed exports and generated market archives out of GitHub by default.
- Adds coverage and vendor identity reports, automatic ZIP validation and regressions.
- **Important limit:** Does not bundle or certify institution-grade U.S. equity data. A real licensed
  vendor subscription and evidence of complete delisting settlements are still required.

## v3.2.2 — data integrity, screen tradability and portfolio validation
- Keep Yahoo dividend-adjusted closing prices and separate vendor trading-close observations (`auto_adjust=False`); disclose price-only fallback when `Adj Close` is absent.
- Carry trading-price fields through market caches, completed-session truncation, incremental refresh/reconciliation and stock prediction panels; reject silent mixing with legacy Yahoo snapshots by full replacement or stale-data warning.
- Stop screening stale last-session prices as current and require recent and current observed volume and dollar-liquidity history.
- Validate every supplied portfolio weight before filtering zero holdings (including negatives, NaN and Infinity); reject duplicate dates and weekly/monthly data masquerading as daily observations.
- Make a clock-sensitive weekly-report test deterministic; preserve resolution-week logic.
- Add dedicated v3.2.2 offline tests and GitHub Actions CI preflight/regression workflow.
- No real-market accuracy improvement has been claimed. Vendor historical close values are not independently certified as original tape prices; authenticated delisted-stock histories are still unavailable.

## v3.2.1 — Exclusive model-selection routing fix (2026-11-20)

- Default individual-stock and portfolio forecasts use the three-model tournament without simultaneously enabling enhanced-lab promotion.
- The enhanced research laboratory is explicitly selectable as an alternative forecast method.
- Fixes a deterministic ValueError which prevented forecasts whenever the default enhanced sidebar switch was on.
- Add regression coverage for model-routing behavior and preserve the low-level safety assertion.

## v3.2.0 — Analyst consensus and disciplined portfolio research

- New source-attributed analyst consensus (Yahoo Finance or Finnhub), dated broker actions, and price targets; missing provider data never becomes a fabricated opinion.
- New strictly current-snapshot provenance and freshness gates; current data is prohibited from historic backtests without archived contemporaneous evidence.
- New risk-aware held-stock allocation study (no transaction execution) with a bounded analyst influence, model signal cap, historical covariance shrinkage, concentration limits, cash reserve and turnover penalty.
- Portfolio research declines to generate weight targets if quote or price histories are incomplete or the optimizer fails.
- Historical archive v3.1 integrity checks are preserved; no paid institutional dataset has been acquired.

## v3.1.0 — Historical Data Integrity (2026-11-20)
- Added SHA-256 checked historical vendor ZIPs, stable security IDs, historical membership, raw/adjusted prices, and historical-delisting-payoff validation.
- Recomputed SEC fundamentals at each original filing event to prevent later restatement leakage.
- Added original-price liquidity/eligibility and injected documented delisted outcomes into historical learning labels.
- Added archive audit/packaging scripts, source-integrity diagnostics, and Streamlit historical backtest integration.
- No independent vendor authenticity or live accuracy advantage is claimed.

## v3.0.0 (2026-11-20)

- Production tournament replay in walk-forward backtesting, strict outcome handling, historical membership and delisting archive validation.
- Paired live forward-evidence ledger and statistical confidence gating.
- Three independent information views, multiple-comparison safeguards, winner-specific probability calibration, benchmark scenario ranges, and missing-volume correction.
- See RELEASE_NOTES_v3.0.md for all behavior, tests, external-data requirements and remaining limits.

## 2.9 deployment/workflow audit follow-up

- Repaired obsolete v2.7-only folder detection in daily and weekly GitHub Actions; validate full v2.9 source at repository root instead.
- Scheduled daily job 5:20 PM and Friday report 5:45 PM America/New_York, after completed-session data cutoff; Friday report window ends at 6 PM ET.
- Weekly outcomes now reconcile every tracked symbol in batches rather than truncating at 150; missing batches are reported.
- Missing vendor closing prices are never filled with stale prices and no previous-date forecasts are logged as new forward evidence.
- Fixed scheduled refresh job's incorrect working directory and updated startup version label/documentation.

# v2.9.0 — accuracy-first, three-model stock tournament and evidence integrity

- Three **separately fitted predictive models** (Ridge, histogram gradient boosting, random forest) now compete **for each stock**. The existing ensemble stays in charge unless a ticker-specific champion beats a chronologically calibrated incumbent in both a selection block and an untouched audit block using nonoverlapping forward-return windows. Limits: per-ticker historical data can be sparse, and selection across many tickers carries multiple-testing risk; the contest is not proof of a live trading edge.
- Stock-level forecasts, winner, model disagreement, evidence status, independent selection/audit window counts, and audited MAEs are available in the Accuracy Lab, with ranked CSV export columns.
- Historical-universe strict mode accepts dated constituent snapshots from an external archived source, checks every evaluation date for complete eligible-stock outcome coverage (including delistings), and fails closed if evidence is missing. Without a real archive, results remain explicitly survivorship-biased; merely writing `historical_archive` in a CSV is not authentication.
- Historical adjusted-close loading no longer uses a **future session's** reversal to rewrite an earlier daily price (look-ahead bias); the old diagnostic function is retained solely for testable offline anomaly identification.
- Immutable forecast ledger migrates SQLite/cloud databases to store timestamp evidence status; only forecasts recorded between actual signal close and next-session close are **timestamp-eligible** for reported forward MAE. Late/backfilled outcomes are excluded from weekly evidence metrics. Timestamps alone do not provide tamper-proof auditing.
- Strict validation shows the evidence qualification status and exposes an optional CSV upload. The existing unbiased evaluation claim was removed for current-universe tests.
- Made scheduled daily-model logging exclude unfinished bars, portfolio backtests use next-session closing-price proxy rather than same-session impossible fills, and capped forecast logging cover the entire prediction distribution rather than only top names.
- Made PostgreSQL/SQLite forecast inserts atomic, and blocked price-only challengers from replacing richer independently selected evidence models without a valid head-to-head comparison.
- Added dedicated regression tests. The application still makes **no brokerage trades** and does not assert 80%, 90%, or any other unverified live accuracy figure.

## v2.8.0 — Additional model families with independent rank auditing

- Added grouped-date stock ranking comparison: Ridge baseline, histogram rank
  surrogate, fixed two-model ensemble, and optional LightGBM/XGBoost LambdaMART.
- Separated date-purged training, selection and audit; latest research scores
  are exposed only after both independent gates pass. No production promotion.
- Added Huber robust, RBF nonlinear and median-quantile candidates to the
  optional individual-stock enhanced forecast; optional InterpretML EBM.
- Enabled time-ordered CatBoost training, added asymmetric held-out residual
  intervals (not guaranteed uncertainty coverage), and a Model Zoo table/UI.
- Included safety tests for delayed labels, grouped relevance, empty history,
  audit isolation, and optional model availability.

## v2.7.0 — Independent professional-method research audit (2026-11-19)

- Added **Institutional-style Research Audit** between Walk-forward Tests and Virtual Portfolio.
- New `institutional_audit.py`: test point-in-time event availability using publication AND discovery time; future documents do not enter past signals.
- New date-block stock-ranking tear sheet: cross-sectional Spearman rank IC, top/bottom spread, top vs universe, ticker turnover, configurable round-trip cost stress, date-resampled uncertainty intervals.
- Optional sector-neutral correlation when historically appropriate group labels are supplied; not enabled silently from modern labels.
- Added the **next-close entry and exit timing proxy**, comparing optimistic signal-close fills with one-bar-delayed closing prices after costs.
- Added conservative historical price-quality warnings for stale price histories, missing coverage and extreme single-session moves.
- Added `scripts/institutional_demo.py` and `INSTITUTIONAL_DEMO_SYNTHETIC.txt`, explicitly synthetic, demonstrating tools without claiming market forecasting accuracy.
- Kept existing production forecasts, classifier, news monitoring, Form 4 monitoring, portfolio login, weekly report workflows, and signals unchanged: unverified research add-ons do not silently alter trading estimates.
- Model accuracy vs market, benchmark performance vs professional systems, live fills and survivorship-bias-free history are **NOT verified**. Research methods are inspired by published QuantConnect, Numerai, Alphalens, QuantRocket, VectorBT and Bloomberg BQuant documentation, not copies of proprietary algorithms.

## v2.6.0 — Accuracy Evidence, Forecast Notifications, Weekly Scorecards

- Added a separate purged, time-ordered stock-ranking challenger for SPY-relative direction, with fixed selection criteria and an independent audit; unverified models cannot displace the existing forecast.
- Added high-confidence prediction hit rates **with sample counts** to prevent misleading selective 80% claims.
- Extended the immutable forecast ledger with a real evaluation timestamp; old unstamped predictions are not fabricated into weekly results. Existing local and PostgreSQL tables migrate automatically.
- Added a Friday 4 PM **America/New_York** report (EST/EDT automatically), scored only from newly resolved future outcomes. Reports are saved to SQL/local snapshots and are previewable/downloadable in Accuracy Lab.
- Added optional email delivery via TLS-protected SMTP and a root-level GitHub Actions weekly workflow. No mail is sent without configured secrets.
- Added in-app notification cues and report status. This is not system push notification when the tab is closed.
- Included deployment and accuracy-claim safeguards; no unverified 80% performance claim.

## v2.5.5 — SEC Form 4 Insider Activity

- Added a separate **SEC Form 4 Insider Activity** dashboard tab immediately to the left of Ranked Leaderboard.
- Official SEC EDGAR ownership filings (Form 4 / 4/A) are retrieved per company with an administrator-configured identifying User-Agent (`SEC_CONTACT_EMAIL`).
- Parses verified issuer-matched **non-derivative** purchase (`P`) and sale (`S`) transactions, reporting owner and role, trade date, disclosure date, number of shares, per-share price, and known transaction amount. Direct links to original SEC filings are included.
- Excludes grants, exercises, compensation, and derivative transactions from the basic buy/sell summaries. Avoids double-counting repeated amended filing records.
- Displays green informational buying evidence, yellow selling/mixed evidence, neutral no-qualifying-trade status; red exit orders or buy instructions are **not** inferred from Form 4 filings.
- Conservatively throttles SEC requests, caches completed checks for 30 minutes, and processes selected forecast companies in batches of up to 10. Errors remain visible and are not incorrectly reported as no insider activity.
- Retains the established Streamlit startup path, stock rankings, stock explorer, marketwide analysis, screenshot import, Google sign-in option, and portfolio tracking.
- Insider filings are disclosure-after-the-event research data; not a prediction model, not proof of undisclosed transactions, and not evidence of forecast accuracy.

## v2.5.4 — Early trend discovery, single-ticker entry/exit colors and 52-week news context (November 19, 2026)
- Added highly visible entry and exit research cards with complete reasons to the instant stock explorer. They share the full-market leaderboard's news/acquisition review and forecast rules.
- New point-in-time 52-week range, low-gap, validity, 5-day relative strength and acceleration features enter the *existing chronologically selected* extended ML evidence group only if the model's holdout results justify it.
- Added a green, not dark-green, **EARLY ENTRY WATCH** for cautious 20-session forecast + improving short-term trend + suitable 52-week location. Missing history, severe downtrends, exit triggers and takeover run-ups cannot qualify.
- Changed the pre-model market screener to reserve up to 25% of deep modeling slots for early turns, preserving liquidity requirements; added an explanatory early-entry candidate list to the leaderboard.
- The individual-stock explorer now uses the same broad news search as the full-market leaderboard, and at least two separate negative-keyword event reports can downgrade an otherwise green entry to a yellow review (without changing model forecasts).
- Added 52-week low/high/location and distinct-news-event context columns to the modeled leaderboard and individual stock news view. Repeated articles still count as one event.
- No retrained 52-week/news causal model is claimed, and no improvement in real-world accuracy is guaranteed. See RELEASE_NOTES_v2.5.4.md.

## v2.5.3 — All-stock auto-news queue and cross-publisher event deduplication (November 19, 2026)
- Every filtered, modeled leaderboard ticker is scheduled for news screening, using bounded automatic 60-second batches and a 24-hour broad cache; top 24 prioritized candidates refresh approximately every 15 minutes.
- Switched leaderboard news fetch to one broad Google News RSS query per ticker across source-attributed publishers instead of three separate restricted publisher requests.
- Added `news_dedupe.py` for same-event clustering by event type, shared keywords, named deal target, reporting quarter and publication proximity. Repeated reports count once in live sentiment, acquisition-review screening and eligible historical news model features.
- Added progress metrics and accurate missing-data/error disclosures. No manual news button or top-12 cutoff.
- Preserved entry/exit colors, screenshot import, account sign-in and the trained stock-forecast model unchanged; no claim of increased accuracy.
- See `RELEASE_NOTES_v2.5.3.md` for full setup and limitations.

## v2.5.2 — Automatic news, exit colors, priced-in acquisition caution and screenshot repair (November 19, 2026)

- The full-market leaderboard now automatically retrieves current attributed headlines for up to the first 12 model-ranked companies using a 15-minute cache. Acquisition screening looks back 45 calendar days, not only the former 14-day feed window. News headline count (last seven days), tone, latest title and article link are displayed directly in the leaderboard. No secondary "fetch news" button is needed. Unchecked/failed feeds do not falsely clear a stock for a strong-entry label.
- Improved entry-readiness order: a recent deal with a post-announcement rally of 7%+ and excess relative to SPY of 5+ percentage points is downgraded to yellow with a large screening deduction, but the original AI forecast is NOT overwritten. A possible deal without a verifiable price reaction is yellow pending review. Acquisition/extension caution sorts below ordinary yellow watch cases, with a conservative entry-priority cap (≤20 for potential acquisitions; ≤35 for extended-price cases); model forecast remains untouched. All modeled stocks get 5-, 20-, and 60-session extension screens; large run-ups also trigger yellow caution. Results are heuristics, not evidence that a stock cannot continue rising.
- Added *independent* green/yellow/red exit conditions in the leaderboard with reasons, review levels, an exit-watch queue, and conditional color styling. Red exit-review takes precedence over a favorable entry color. No automatic orders.
- Added a local screenshot OCR extraction path with **no API key**, using Tesseract installed by `packages.txt`. It produces an editable draft with tickers and cautious share-count extraction; it deliberately leaves original purchase prices and dates blank instead of copying current stock prices. The existing optional OpenAI Vision method remains available. Image imports require user review, confirmation and duplicate-import protection.
- Retains canonical `streamlit_app.py` and the saved-portfolio SQL / Google sign-in support. Added no new market forecasting model or validated accuracy improvements.
- See `RELEASE_NOTES_v2.5.2.md` for setup, tradeoffs, and installation details.

## v2.5.1 — Full-market leaderboard colors and priced-in acquisition caution (November 18, 2026)

- Brought existing portfolio entry/exit colors directly into the modeled-stock leaderboard: dark green (strictest 20-session entry screen), green (ENTRY WATCH), yellow (wait/confirm or large run-up caution), and red (REVIEW EXIT). Stale and missing evidence never qualify for green by default.
- Checked every modeled candidate for a **large five-completed-session rise**: at least +15% for the stock AND at least +10 percentage points versus SPY. Such cases are yellow `AVOID CHASING` rather than dark green solely on favorable recent momentum.
- Added opt-in current-headline deal screening for the first ten filtered names (up to three RSS feeds per stock; cached). Only relevant, source-attributed, dated, acquisition-related headlines can qualify. If the closing price has already jumped at least +10% and +8 percentage points versus SPY since the pre-announcement close, the candidate gets a stronger review flag and screening penalty. Headlines are not definitive verification of a transaction.
- Added *Entry priority /100* screening overlay: subtract 15 points for a rapid 5d run-up; subtract 35 for a possible acquisition followed by a qualifying post-news jump. Original model research scores and AI forecasts are unchanged; users can turn entry-priority sorting off and view the model rank alongside the new rank.
- Added columns explaining every color, price response, acquisition checking status, attributable deal source, and original rank, plus color fills and CSV export. Red always overrides a favorable entry screen.
- All price calculations use saved, completed daily data at or before the forecast as-of date. No new news requests during ordinary rendering; the explicit button checks up to ten stocks only. This is an *unvalidated* caution heuristic, not a proven forecast of mean reversion or reduced upside.

## v2.5.0 — Dark-green strongest entry tier

- Added **🟩 STRONG ENTRY WATCH** (dark-green cell fill) above green for unusually favorable *but unvalidated* 20-session signals: existing ENTRY WATCH plus ≥6% modeled SPY-relative forecast, ≥70% modeled gain probability, ≤60% annualized volatility, and ≤15% current holding weight when known.
- Red exit-review signals take precedence over dark-green, and stale/missing quotes or model evidence cannot qualify. The dashboard now counts all four categories separately.
- No automatic trading and no guarantee of accuracy from the new screening thresholds.

## v2.5.0 — Entry/exit signal aligned traffic lights (finalized)

- My Portfolio colors now derive from the exact ENTRY WATCH, WATCH / CONFIRM, WAIT, and REVIEW EXIT signals used elsewhere in the application.
- Safe migration stores `entry_watch` alongside forecasts, preserving existing SQLite/PostgreSQL portfolios. Legacy forecasts remain yellow until refreshed.
- Forecast cards and holdings list display both entry and exit indicators; comparable review-level breaches appear red; unsuitable price bases are flagged yellow.
- Existing accounts, screenshot import, permanent storage option, market data and educational safeguards retained.

# Changelog

## v2.5.0 — November 18, 2026

- Added optional Google OIDC sign-in with account-isolated holdings, no user-managed recovery codes after setup. Persistent cloud data requires PostgreSQL. Existing code-based portfolios can be migrated once.
- Added screenshot holdings import via optional OpenAI Vision; returns an editable trade draft with explicit confirmation, strict missing-purchase-price checks, and duplicate image fingerprint rejection.
- Added educational green / yellow / red research flags for positions from fresh saved 20-session models, with visible reasons and stale-data safeguards.
- Added isolated unit tests and deployment instructions; no changes to the underlying predictive model or historical accuracy.



## v2.3.0 — November 16, 2026

- Added **My portfolio** separate from both the instant explorer and the full-market scanner.
- Save/retrieve private ticker-level holdings using an unguessable recovery code and its hashed owner ID.
- Record BUY/SELL fills, prices, quantities, dates and fees; support multiple purchase prices, partial sales, and corrections.
- Weighted-average cost, realized/unrealized P/L, cash, estimated equity, stale/missing quote indicators and comma-formatted dollars.
- Fetch portfolio-only quotes; optional two-minute in-tab update and manual refresh.
- Run ML forecasts for one held ticker or the holdings-only shortlist; save as-of dates, probabilities, SPY-relative estimates and review status.
- Show news across all held tickers, with sources, timestamps, links and optional 15-minute in-tab refresh.
- Atomic CSV import, CSV export, independent SQL persistence with optional PostgreSQL backend and cloud persistence warning.
- Documentation and regression tests in [RELEASE_NOTES_v2.3.md](RELEASE_NOTES_v2.3.md).
- Existing v2.2 charts/scanner/forecasting model preserved; no claim of improved market prediction accuracy.

ovember 14, 2026
- Separated forecast-scale calibration from evidence-group model selection using purged chronological data blocks.
- More honest enhanced forecast model selection: fit, scale-calibration, selection, then independent error audit.
- Added an optional HistGradientBoosting absolute-error candidate to enhanced model comparison.
- Probability blending selected on a purged calibration block and scored on later independent observations; defaults to historical base rate when sufficient calibration cannot be established.
- Added date-block bootstrapped uncertainty intervals for directional accuracy lift versus naive direction baseline.
- Updated 2.2.0 deployment version and package tests; preserved 1D/5D/1M/6M/YTD/5Y charts, news, SEC, macro, universe scanner, portfolio.
- Includes synthetic A/B comparison in RELEASE_NOTES_v2.2.md; no evidence of a real-world forecast improvement yet.

# Changelog

## v2.1.0 — November 14, 2026

- **Robust training target:** quantile (0.5%/99.5%) winsorization replaces the near-inactive ±80% clip, so rare takeover/crash outliers stop dominating squared-error fits.
- **Calibrated forecast scale:** each forecast is multiplied by a factor in [0.15, 1] learned on the embargoed chronological holdout (never amplifies, never changes ranking). Reported as `forecast_shrinkage`. The Accuracy lab applies the same idea per candidate model and computes intervals on calibrated audit errors.
- **Extended feature candidates:** 12-1 momentum, 52-week-high gap, 60d beta, idiosyncratic volatility, max-return, skew, log dollar volume, 1-day reversal and same-day cross-sectional ranks. Entered only when they beat the baseline on the chronological holdout.
- **Faster, tighter selection:** feature groups are tested alone and combined only if each passed on its own (fewer holdout comparisons, fewer model fits).
- **Probability blending:** event probabilities are blended toward the historical base rate with a weight chosen by holdout Brier score; a classifier that cannot beat the constant rate collapses toward it.
- **Bad-tick sanitation:** a >35% one-day price move that fully reverses the next session is masked as a data error before features are built.
- Adds `scripts/accuracy_benchmark.py` (A/B walk-forward: legacy vs v2.1) and `ITHACA_LEGACY_MODEL=1` to reproduce v2.0.
- 10 new regression tests (point-in-time features, shrinkage, gating, blending, tick sanitation, legacy switch).
- [Release notes](RELEASE_NOTES_v2.1.md).

## v2.0.0 — November 14, 2026

- Adds ten integrated workstreams: verified-dated news/earnings candidates, purged alternative ML selection, genuine forward forecast ledger, market regime features, empirical forecast intervals, opt-in durable SQL storage, ALFRED-vintage macro context, portfolio stress metrics, scheduled subset-refresh option, and model/host explanations.
- Adds historical licensed vendor news CSV importer and point-in-time EPS consensus surprise CSV path; absent optional sources are never fabricated.
- Retains matching cross-release startup preflight, 1D 8:30 AM–4 PM ET, full-market incremental scanner, original fallback ensemble and virtual competition constraints.
- [Full per-feature release notes](RELEASE_NOTES_v2.0.md).
- The extended model makes no automatic accuracy claims; absent evidence retains the original model.


## v1.4.2 — November 12, 2026

- Repairs mixed-version startup failure in Streamlit when v1.4.1 app.py is deployed with v1.4 `ithaca_quant/explorer.py` (v1.4 lacks `select_1d_display_window`).
- Runs release/version compatibility preflight before importing application feature modules.
- Shows a clear explanation and GitHub repair paths if required chart or presentation imports are missing.
- Adds regression tests for cross-release import compatibility and package version integrity.
- No forecasting equations or market signals changed; live cloud/browser verification remains necessary.
- [Detailed deployment repair notes](RELEASE_NOTES_v1.4.2.md).

## v1.4.1 — November 12, 2026

- [Detailed release notes](RELEASE_NOTES_v1.4.1.md) covering every feature, implications, validation and deployment.
- Fixed 1D time-axis to 8:30 AM–4:00 PM Eastern and selected only observed intraday prices within this interval. Explicit Plotly x-axis range and hourly ticks avoid midnight-to-11 PM padding.
- Added comma-separated dollar formatting for SEC/Yahoo quarterly revenue and net income, with meaningful missing values, percentages, EPS and dates. Training data remains untouched.
- Added a separate **1-session daily ML outlook** to the 1D explorer that can remain available after the 4 PM close without pretending to predict the next hours of the already completed session. The 1D intraday heuristic still requires fresh regular-session bars.
- 1D probability metric now displays the predicted next-session *gain* event when estimable, instead of emphasizing rare +20% single-day booms. Probabilities are not independently calibrated.
- Added explicit model error types and an opt-in **Retry daily data and ML forecast** button for Yahoo/feature caching errors.
- App build version v1.4.1 now warns if the package version differs, protecting against partial GitHub uploads that leave v0.5 headings.
- 88 tests passed offline, including 6 v1.4.1-specific regression tests. Live external feed/UI testing not performed.


## v1.4.0 — November 12, 2026

- [Extensive feature-by-feature release notes](RELEASE_NOTES_v1.4.md).
- Versioned local SQLite cache for NYSE/Nasdaq screened snapshots, price matrices and first-seen headline archives. Auto-resume existing saved market samples; no repeated multi-year downloads on normal refreshes.
- New **full scan** vs **incremental refresh** buttons, 20-minute active-screen auto-refresh, five-minute deep-history check, two-minute news cache, 15-second priority quote refresh with size/rate safety.
- Daily market model excludes incomplete daily bars until after 5 p.m. New York time; split-adjustment revisions trigger targeted complete history repair rather than splicing inconsistent series; stale refresh falls back visibly.
- Official SEC reported-quarter extraction, filed-date-aware revenue growth/margins and point-in-time features, with optional administrator contact and Yahoo display-only quarterly fallback.
- Conservatively timestamped news archive; historical news predictors become eligible only after sufficient actual observed history and chronological model-selection improvement. Current headlines never retroactively enter older backtests.
- Chronological model selection compares market-only against optional SEC/news factors and requires measured training-holdout MAE gains. Independent backtesting remains necessary.
- Main hypothetical price endpoint NO LONGER includes unvalidated word-level news price shifts. Experimental headline sensitivities are retained as separate labeled scenarios, not marketed as accurate market predictions.
- Preserves time-bounded 1D chart, risk estimates, quote provider alternatives, full-market portfolio, 3 research score components, 3 parallel data workers and 2 application-level retries.

## v1.3.0 — November 2026

- [Detailed per-change notes](RELEASE_NOTES_v1.3.md) for implementation details, math, usage, and limitations.
- **Automatic current-news context in the instant stock explorer:** dated source-attributed headlines retrieved and cached per ticker, with seven-day freshness, duplicate removal, relevance weighting, transparent word-level sentiment, and explicit missing-data warnings.
- **News sensitivity for individual estimates:** separate baseline and bounded hypothetical current-news scenarios for return, illustrative target price, boom estimate, and risk-stress range. Numerical changes are NOT learned or historically validated causal news effects.
- **1D news context:** only same-day ET news contributes a capped ±0.2% experimental adjustment to a valid intraday projected endpoint. It does not fabricate a 1D forecast when the market is closed or bars are stale.
- **1D chart time bounds:** exact first actual price bar to latest observed bar or valid same-day forecast endpoint; no midnight-to-open empty period, no next-day extrapolation. Hourly axis labels and precise hover timestamps retained.
- **Optional generative AI sourced headline explanation:** only when the server has an `OPENAI_API_KEY` and a visitor clicks the generate button. Private server secrets never enter code or logs. Optional model text does not control numeric scenarios.
- **Five-stock news comparison in the leaderboard:** displays price-model forecast, news sensitivity, boom scenario, stress estimate and publisher counts, sorts only the analyzed subset and exports CSV.
- **Preserved:** instant independent ticker lookup, broad-market scanner, historical price/volume ML model, backtesting without news leakage, 3 scoring agents, 3 worker limit, 2 retries, company profiles, live/delayed quotes and simulated portfolio.


## v1.2.0 — November 2026

- Chart ranges now strictly bound displayed observations: 1D uses today-only Eastern-time intraday bars; 5D uses up to five observed trading sessions; 1M, 6M, YTD and 5Y are exact historical calendar windows.
- 1D axis uses time-of-day ticks and hover timestamps; no stale yesterday-price fallback.
- Forecast extensions matched to each range: 1D next up to 2 market hours (experimental momentum heuristic), 5D next session, 1M next 5 sessions, 6M/YTD next 20 sessions and 5Y next 60 sessions (daily SPY-relative ML).
- Short-term projections are disabled outside the trading session, on stale quotes, and when intraday history is insufficient. Dotted lines remain endpoint illustrations, not per-minute predictions.
- Kept existing broad screener, news, risk metrics, 3 scoring components and 2 app-level retries.


## v1.1.0 — November 2026

- Search bar above the research settings; on-demand training for one selected
  ticker and SPY, independent of the NYSE/Nasdaq marketwide scan.
- 1D, 5D, 1M, 6M, YTD and 5Y price chart windows; short windows try intraday
  provider observations, otherwise show clearly labeled recent daily closes.
- Dotted straight segment to one model-derived endpoint (not a daily path),
  with technical review conditions, risk metrics and on-demand company news.
- Preserved the full-market workflow, 3 scoring components and two retries.

## v1.0.0 — November 2026

- Promoted the v0.8 stock search and financial news interface to a clearly
  labeled v1.0 release, with one authoritative Python version constant.
- Updated Mac and GitHub-to-Streamlit deployment instructions.
- Clarified that live news is an *unvalidated overlay*, not part of a
  historically trained news-driven forecasting model.
- Preserved existing 3-component research ranking and at most 2 application-level
  retries per failed network operation.
- Retained historical validation, broad exchange discovery, quotes, virtual
  portfolio and company metadata functions without changing their formulas.

### Known limitations

- Python environment and live external feeds must be configured and tested
  on a machine with network access.
- Yahoo quote freshness varies; optional real-time IEX covers IEX trades only.
- Watch/review dates are rules-based checkpoints, not optimal trading dates.
- No verified live-prediction edge or brokerage execution capability.
- Exchange-wide research is resource-intensive and subject to rate limits.

## v0.8

- Stock search page, news links, hypothetical price scenarios, news overlay.

## v0.7

- Three transparent ranking score components, up to two app-level retries.

## v0.6 and earlier

- Historical validation, company metadata, leaderboard, marketwide screener,
  quotes, predictions, risk analysis and hypothetical portfolio.

## v3.2.5 — Free-first historical research datasets

- Added `ithaca_quant/free_history.py`, with Yahoo/SEC data acquisition, checksummed local research bundles, strict provenance declarations, and overlap validation.
- Added `scripts/acquire_free_history.py` for self-serve, no-paid-credential price data and optional official SEC companyfacts (`SEC_CONTACT_EMAIL`).
- Connected SEC filing-vintage features and optional earlier local Yahoo historical bars to main rankings and scheduled forecast workflow.
- Added 8+ regression checks for source inventory, missing prices, price revisions, and SEC filing timing.
- Remains an observed CURRENT-ticker subset, NOT a verified historical universe or delisting settlement source.
