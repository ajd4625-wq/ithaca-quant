# Ithaca Quant v1.0 — Stock Research Dashboard

A local Python + Streamlit **educational research dashboard** for the Ithaca College
virtual $1,000,000 high-school investment competition. It does **not** place orders,
log in to StockTrak, or reliably predict prices.

## v1.0 release overview (November 2026)

**Ithaca Quant v1.0.0** is a versioned packaging and documentation release of the
working v0.8 research prototype. It does **not** introduce a newly trained or
proven-accurate forecasting model; forecasts, news and probabilities remain
experimental research tools. Previous features are preserved:

- **Search stock + news:** ticker search, historical chart, scenario-based price
  forecast where the ticker was modeled, historical risk estimates, review dates,
  experimental boom probability, sector, industry, market cap and links to recent
  Google News RSS articles indexed from Yahoo Finance, Fox Business and ABC News.
- **Ranked leaderboard:** multiple sorting methods, the three transparent
  Forecast/Momentum/Risk scoring components, industry and market-cap filters,
  news context overlay and downloadable CSV.
- **History and validation:** embargoed walk-forward tests, historical model
  performance versus baselines, calibration checks and clear sample-size warnings.
- **Marketwide screener and prices:** large NYSE/Nasdaq watchlist discovery;
  latest available Yahoo prices, and optional authorized Alpaca IEX quotes.
- **Virtual portfolio:** hypothetical $1,000,000 competition allocation and
  risk-management tools. It does not trade or sync actual StockTrak positions.

**Release safeguards:** at most 3 workers per supported task; at most 2 app-level
retries following an initial network request. Model outputs are not reliable
predictions of exact returns, price targets, or buy/sell dates. Headlines are
**not** fed into the historical ML training pipeline; optional headline scoring
is an unvalidated research overlay.

### Deploy to Streamlit Community Cloud (share with your team)

Upload the contents of the extracted `ithaca_quant` project folder to GitHub.
Do not upload `.venv`, credentials, `.env`, API keys or local SQLite caches.
For a repository named `ithaca-quant` with all application files inside a
subdirectory named `ithaca_quant`, configure Streamlit deployment like this:

- Repository: `YOUR_GITHUB_USERNAME/ithaca-quant`
- Branch: `main`
- Main file path: `ithaca_quant/app.py`

If `app.py` and `requirements.txt` are at the repository root instead, set the
main file path to `app.py`. If the deployment tool reports the repository does
not exist, verify GitHub authorization/visibility before changing file paths.

**Cloud hosting limits:** Full-market scans and large backtests can run out of
RAM or encounter rate limits on free hosting. Begin with a manual shortlist or
modest scan. Each browser session can use significant compute; this release
has no shared database and changes to virtual holdings are not synchronized
across users. Keep API credentials in Streamlit secrets, not public GitHub.

### Run the full regression tests

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

See `CHANGELOG.md` for release history and known limitations.

## Update your version on Mac

1. In the old Terminal app, press **Control+C** to stop Streamlit.
2. Rename the existing `~/Downloads/ithaca_quant` folder to `ithaca_quant_old`
   so the new files do not get merged with the old version.
3. Download the **v1.0** ZIP and double-click it to extract a NEW `ithaca_quant` folder
   inside Downloads.
4. Open Terminal and enter these commands **one at a time**:

```bash
cd ~/Downloads/ithaca_quant
bash start_mac.command
```

5. Open **http://localhost:8501** in Chrome. Keep Terminal open while using the app.
   Python 3.11+ and internet access are required for the first install and real data.

If you receive `No such file or directory`, use Finder to confirm where the
new `ithaca_quant` folder was extracted. If another Streamlit app is running,
it may choose port 8502 instead of 8501; use the URL Terminal reports.

## NEW in v0.6: Measured historical accuracy next to each ranked stock

Go to **🏆 Ranked leaderboard** and click **🧪 Run historical validation and add evidence to rankings**. This evaluates your selected model against historical outcomes that were **not in the model's training labels at the time of each forecast**. You can also run the same test in **🧪 Walk-forward tests**. These tabs share results only when the universe, forecast horizon, model settings, and other test inputs match.

The leaderboard and **🔎 Stock rankings** now show:

- **OOS windows** — number of distinct, nonoverlapping historical decision dates observed for that stock. A single stock may have only 8–24 observations, even when the whole model has thousands of ticker-outcomes.
- **OOS direction hit** — how often the stock's predicted **SPY-relative** outperformance sign matched the realized positive/negative sign. It does NOT mean how often the stock price rose.
- **OOS forecast MAE** — historical absolute percentage-point error of the relative-return forecast. Compare it to **OOS zero-forecast MAE**, a deliberately basic benchmark which always predicts zero outperformance.
- **OOS boom Brier** — squared probability error for the user-selected +10/+15/+20/+30% closing-price event (lower is better). Compare to the **OOS boom baseline Brier** that uses only the event frequency known at each historical decision date.
- **OOS evidence** — `Not tested`, `Too few OOS windows`, `Boom model lagged baseline`, or `Preliminary; unverified live`. Even a positive preliminary score does **not** establish reliable live performance.

The **Walk-forward tests** tab now includes model-versus-baseline accuracy metrics and **reliability tables/plots** that group past probability forecasts by their expected event frequency and compare against the **observed** fraction of events. Use the dropdown to switch **boom** or **gain**. Download **all historical ticker-window predictions and actual outcomes as CSV** to audit the reported accuracy.

**How to interpret:** A 100% OOS direction hit across 3 windows is **not** reliable accuracy evidence. Less than 12 windows is explicitly flagged too sparse. Even 24 windows provide only *preliminary* evidence, and stocks tested in the same market window are correlated. The system **does not recalibrate current probabilities** from the historical chart or claim any specific stock's current probability is verified. It does not learn from future event outcomes when forming historical forecasts.

**Important limitations:** Current U.S. exchange listings and screened survivors are used for historical tests: delisted stocks are absent (**survivorship bias**). The backtest uses idealized historical adjusted closing prices, not replicable execution prices; it does not predict precise buy/sell timing. Repeatedly optimizing settings against these test windows invalidates their out-of-sample status; a genuinely untouched final set is needed before stronger claims.

**Suggested starting settings:** 5 historical years, 20 trading-day forecast, 10% boom threshold to get a less sparse event dataset, 8 test periods for an initial check, then 16–24 periods if performance allows. Large 600-stock scans with many tests can take significant CPU/RAM. It is fine to begin with 50–100 modeled stocks and expand.

## Included since v0.5: Industry, sector, and market capitalization

The **🏆 Ranked leaderboard**, **🔎 Stock rankings**, and **🌐 Marketwide screener**
now include **Industry** and **Market cap ($B)** columns where company details
are available. The leaderboard and marketwide screen also support:

- **Sector filters** (for example, Technology or Healthcare)
- **Industry filters** (for example, Semiconductors or Software)
- **Market-cap buckets**: Mega (>= $200B), Large ($10B–$200B), Mid ($2B–$10B),
  Small ($300M–$2B), Micro (< $300M), plus all/known-only
- Click the **Market cap ($B)** column header to sort the table by size.
- CSV exports include these extra company fields and the last profile retrieval timestamp.

**How to load the fields:** Go to **🏆 Ranked leaderboard**, select **Load details
for top** (10, 25, 50, or 100), then press **Load next missing/stale company
profiles**. Profiles are downloaded from Yahoo Finance one ticker at a time;
repeat the button to cover further modeled companies. The broad-screen tab has
its **own** button to load the next 10–100 company profiles from the much larger
screened list. Exchange directories provide names and exchange but **do not**
provide reliable industry or market capitalization, so those fields begin blank
until their company profiles are retrieved. Large runs may take some time or
encounter provider rate limits. Yahoo may lack industry/cap for some companies.

Downloaded company profiles are cached locally in
`.company_metadata_cache.sqlite3` in the project folder. Each profile is
rechecked after 24h upon pressing the load button. Values are **latest
available reference metadata, not streaming real-time prices or historical
point-in-time valuations**. The app does NOT use current market cap or industry
metadata as features in its historical prediction or backtesting pipeline
(which would introduce future-information leakage). Market cap and the profile's
`metadata_asof` timestamp are shown for transparency. If the provider fails,
fields remain blank instead of being guessed. Existing rankings, risk tools,
quote panel, and virtual portfolio continue to operate without metadata.

## Ranked stock leaderboard with numbered rankings

Go to the first dashboard tab, **🏆 Ranked leaderboard**. It ranks the stocks
that successfully completed the deeper ML analysis; it is **not** a ranking
of every exchange listing (the broad screen has its own numbered basic ranking).

- **Balanced (upside + risk)** (default): relative score = 55% forecast
  SPY-relative return percentile + 15% historical SPY-relative momentum
  percentile + 20% lower-volatility percentile + 10% model-agreement percentile.
- **Forecast upside**: highest predicted excess return over SPY first.
- **Risk-adjusted forecast**: excess-return prediction divided by (2% plus
  horizon historical volatility plus model disagreement). Research heuristic.
- **Boom probability (experimental)**: estimated close-to-close probability
  of reaching the configured 10/15/20/30% event threshold. An internal
  chronological holdout comparison is shown when available; predictions are
  *not* proven calibrated probabilities.
- **Relative momentum**: highest historical 20-session return vs SPY.

Limit the maximum allowed historical volatility, show only positive model
forecasts, select the number of displayed rows, inspect history vs SPY,
and export the leaderboard as CSV. A basic stock-price eligibility filter
excludes stocks priced at $5 or below.

**A research score out of 100 is strictly a comparative cross-sectional rank,
not a 100% probability of making money.** Rankings depend on the stocks
available and the filters chosen, and may change without price moves if the
candidate universe changes. The quotes overlay (optional; up to 50 symbols)
shows Yahoo's latest *available* quote with a timestamp; it may be delayed or
stale, and it does not retrain the end-of-day forecasts.

The **Marketwide screener** also now has an explicit numbered leaderboard
for every stock passing its simple price/liquidity screen. These broad-screen
ranks use a heuristic rather than AI predictions.

## A much larger U.S. stock universe

1. In the sidebar select **Yahoo Finance** and **Automatic NYSE + Nasdaq universe**.
2. Choose **Listings to scan**: 500, 1,500, 3,000 or **ALL available**.
   ALL attempts to scan every current candidate obtained from Nasdaq Trader's
   NYSE/Nasdaq listing files; actual data coverage depends on provider limits.
3. Choose **Stocks to model deeply** (50 to 600).
4. Press **Scan NYSE + Nasdaq stocks**. Downloading thousands of symbols may
   take minutes and sometimes fail due to provider rate limits. You can start
   with 500–1,500 stocks and 100–200 model candidates.
5. In **Marketwide screener**, browse/export ALL stocks that passed price and
   liquidity rules; an explicitly labeled shortlist receives ML forecasts.
6. In **Stock rankings**, analyze predictions and hypothetical boom probabilities
   on the deep-modeled shortlist. **A screening score is not an AI prediction.**

The broad scan:
- Downloads one year of daily prices in chunks of 75 symbols.
- Filters for stock price >$5, at least $1 million median daily dollar
  volume, and adequate historical coverage.
- Selects a mixed candidate shortlist using liquidity, momentum and volatility.
- Downloads 3–8 years of price history for those candidates and applies the
  existing walk-forward research pipeline.
- Limits ML training row counts to contain runtime and memory on a laptop.
- Caches current exchange listings for 12h, scans for 6h and deep price data for 8h.

The Nasdaq Trader symbol directories are *current listings*. Backtests using
this candidate selection have **survivorship and selection bias**, because they
exclude previously delisted stocks and the broad screen is based on recent
performance. **Do not interpret these backtests as unbiased evidence of an edge.**
The exchange list is a candidate universe, NOT an eligibility guarantee.
Verify any instrument against the actual StockTrak competition rules.

## NEW: Latest available prices (separate from forecast inputs)

Open **Latest prices** in the dashboard.

**Option A: Yahoo intraday** — no credential needed, up to 75 requested
symbols. It fetches the latest available 1-minute bars. Prices may be delayed,
stale, or missing. **Do not treat Yahoo intraday as a real-time execution feed.**

**Option B: IEX real-time latest trades (optional)** — read-only Alpaca Market Data
API. Requires appropriately authorized market-data credentials; never bypass
account permissions, eligibility, or age requirements. If you already have
permission, enter the API key/secret in the sidebar of the prices tab or set
`APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` environment variables. The app only
calls `GET https://data.alpaca.markets/v2/stocks/snapshots?feed=iex` and does
not trade. Free IEX quotes cover **IEX only**, not consolidated U.S. exchange
prices; the most recent trade can still be old for less liquid securities.

Choose manual refresh or optional ~60-second refresh. The table displays
last traded price, bid/ask where available, source, precise UTC timestamp and
quote age. Quotes over 15 minutes old are flagged **STALE**. After hours or
weekends, quotes can be hours/days old even when the feed is real-time.

**Never substitute these raw intraday quotes for adjusted daily closes used
by the ML and portfolio simulation.** These differ after dividends and stock
splits; also signals are end-of-day research flags, not execution instructions.

## Existing features

- Two-model educational price/benchmark-relative return estimates (Random
  Forest and HistGradientBoosting), 10/20/40-session forecasts.
- Experimental probability of a positive return or 10/15/20/30% gain as of the
  chosen forecast horizon. NOT verified accurate or calibrated odds.
- Hypothetical entry/exit watch conditions and risk-budgeted example positions.
- Chronological, embargoed walk-forward backtests versus SPY and momentum.
  Includes boom-probability Brier score against a historical-frequency baseline.
- $1,000,000 virtual portfolio with 5–20 holdings, max 25% initial position,
  historical risk diagnostics and hypothetical P&L.
- CSV exports. **No actual investment recommendations or orders**.
- Synthetic demo mode for offline illustration only; demo predictions are
  completely fictional.

## Development and tests

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
streamlit run app.py
```

Offline tests cover feature building, chronological training, backtests,
portfolio rules, NYSE/Nasdaq listing parsing, screening, batched downloads and
IEX quote parsing. The full interactive browser workflow and public API feeds
must still be verified on the user's computer with a working network.

### Project structure

```text
app.py                            Streamlit UI with version label
ithaca_quant/__init__.py          Version constant and package identity
ithaca_quant/config.py            Competition research constraints
ithaca_quant/universe.py          Exchange listing discovery + broad screen
ithaca_quant/data.py              Yahoo historical batch downloader + demo
ithaca_quant/quotes.py            Yahoo intraday and optional read-only IEX quotes
ithaca_quant/features.py          Technical feature panel
ithaca_quant/model.py             Two-model return forecasts
ithaca_quant/probability.py       Experimental event models
ithaca_quant/backtest.py          Historical walk-forward tests
ithaca_quant/signals.py           Risk-budget and entry/exit watch rules
ithaca_quant/portfolio.py         Virtual portfolio and historical risk
ithaca_quant/leaderboard.py       Explainable rank formulas, filters, display
ithaca_quant/metadata.py          Yahoo company details, 24-hour SQLite cache
ithaca_quant/news.py              Google News RSS / headline analysis overlay
ithaca_quant/search.py            Stock search / review-date scenarios
start_mac.command                 Setup/launch script
requirements.txt                  Python dependencies
tests/                            Offline regression tests
```

### Official reference documentation

- Nasdaq symbol-directory data definitions:
  https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs
- Alpaca snapshot endpoint (read-only data):
  https://docs.alpaca.markets/us/reference/stocksnapshots-1
- Ithaca College competition information:
  https://www.ithaca.edu/academics/school-business/high-school-investment-competition

## Research limitations

Historical returns do not ensure future returns. Broad-market scanning and
trading signals are hypotheses, not guaranteed profitable trading strategies.
Yahoo's unofficial public endpoint can throttle or deliver incomplete data,
and may be unsuitable for scanning thousands of stocks regularly. Prices can
be adjusted or revised; snapshots are not execution prices. Free IEX quote
feeds cover only IEX, not all exchanges. This app does not provide a real
StockTrak holdings sync or automatic order execution.

## NEW in v0.7: 3 scoring agents and at most 2 app-level retries

- Exactly three **transparent ranking components**: **Forecast** (model-predicted SPY-relative upside),
  **Momentum** (relative strength vs SPY), and **Risk** (lower historical volatility and better model agreement).
  They are score components, **not three autonomous AI chat agents**. Their weights reproduce the previous
  Balanced score: Forecast 55%, Momentum 15%, Risk 30%. All three agent sub-scores appear in the Ranked leaderboard.
- Network requests are attempted **once, with at most two additional retries** for a failing request.
  This applies to Yahoo price-history batches, intraday quote batches, Nasdaq directory requests,
  and individual company profile requests. Alpaca IEX snapshot requests retry transient server failures,
  but do NOT retry invalid credentials or 429 rate limits.
- `yfinance.download(threads=3)` and the random forest `n_jobs=3` limit per-task concurrency.
  The launcher also caps major numerical libraries to 3 threads. These are per-operation bounds,
  not a promise about the behavior of third-party APIs, internal retries, OS threads, or multiple app sessions.
- Batches with no valid response after the retries are excluded; nothing is fabricated.
  Large universe scans may still take time and provider throttling may prevent full coverage.

## v0.8 — Stock search and public news

- New **Search stock + news** tab: enter a ticker and press Analyze stock. The historical adjusted-price chart works even for a stock outside the current ML universe (when Yahoo data is available). To obtain AI forecasts for that stock, include it in the trained universe and rerun the app.
- Shows a **scenario price target** derived from the model's SPY-*relative* forecast under an explicit 0% SPY return assumption, plus an uncalibrated volatility range. These are not verified absolute price forecasts.
- Shows historical volatility, experimental boom event estimate, risk-budgeted position sizing, sector, industry, and market cap (click Update company profile to fetch metadata).
- Shows **entry and exit REVIEW dates**, not predicted optimal trading dates. Dates are business-day approximations and do not account for market holidays.
- On-demand Google News RSS search restricted to Yahoo Finance, Fox Business, and ABC News publisher domains. Displays links, publication timestamps and source; some publishers/tickers may have no matches. Google News may change feeds or block requests.
- News context is an explicitly unvalidated keyword sentiment heuristic. Optional leaderboard news overlay is separate from the machine-learning model and historical backtests; it cannot establish news-driven predictive performance. To train on news properly, collect licensed, timestamped historical headlines and redo chronological out-of-sample validation.
- News cached 15 minutes. Existing maximum of 3 workers and 2 app-level retries remains. Never place secrets in public GitHub.
