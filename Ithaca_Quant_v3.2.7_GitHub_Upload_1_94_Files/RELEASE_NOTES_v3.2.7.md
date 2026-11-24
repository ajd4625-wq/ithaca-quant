# v3.2.7 — Historical validation button stability (November 23, 2026)

## Problem and cause assessment

Pressing **Run historical validation and add evidence to rankings** in v3.2.6
calls `run_walk_forward` from inside the Streamlit web process. For 200+ stocks
and eight or more decision windows, it can repeatedly retrain several model
families and evaluate the three-agent tournament. Streamlit cannot catch an
external memory/resource kill, so the interface can show **Oh no. Error running
app** with no Python exception. This workload is a **plausible** cause, not
proven without the Cloud logs. Repeated `use_container_width` output in the
screenshot is a deprecation warning, not the root error.

## Implemented safeguards

- Both web buttons now run a deterministic sample of up to **12 current
  tickers** for at most **2** non-overlapping decision windows, preserving the
  same ML tournament for sampled stocks.
- No stock is chosen by future return, current rank or selected model. The
  sample is still drawn from the present-day survivor universe and **is not
  institutional-grade evidence**. All untested stocks remain *Not tested*.
- The browser uses a bounded six-year-ish tail (1,600 trading dates) and caps
  panel rows before model training or caching. An error is displayed and logged
  rather than silently treated as a successful backtest.
- Strict archived, point-in-time histories **are not silently downsampled**:
  the app requires their full-universe replay to run offline.
- Replaced 46 deprecated Streamlit width arguments using the official
  `width="stretch"` replacement. Minimum Streamlit version is 1.55.

## Full historical evaluation outside Streamlit

On a machine with enough RAM and CPU, run:

```bash
python scripts/run_historical_validation.py \
  --tickers AAPL MSFT NVDA AMZN META JPM XOM AMD COST TSLA ORCL ADBE \
  --years 6 --periods 12 --horizon 20 --out ./validation_results
```

This is *survivor-biased*, because the supplied Yahoo tickers are current.
For a properly dated private archive including delisted securities:

```bash
python scripts/run_historical_validation.py \
  --archive /private/path/to/point_in_time_archive.zip \
  --periods 12 --horizon 20 --out ./validation_results
```

The script creates three reports: `walk_forward_periods.csv`,
`walk_forward_predictions.csv`, and `walk_forward_metrics.json`. It does not
submit trades. Do not publish licensed market data or source documents to
GitHub without redistribution permission.

## Verification scope and limitations

- New deterministic sampler tests and a synthetic end-to-end three-model test
  exercise the web preview logic.
- Source syntax and offline deployment preflight checked.
- No real Streamlit Cloud session, vendor Yahoo API, or memory-termination logs
  were accessible. Live deployment stability remains **unverified**.
- Historical validation and forecast superiority are **not** established by
  synthetic tests or two-window browser previews.

## If it still crashes

Check **Streamlit Cloud → Manage app → Logs** for the first exception around the
click, or signs of a worker restart/out-of-memory kill. Ignore the old
`use_container_width` warnings. Supply the last 20–30 error lines *with all
secrets removed* to trace any second failure path.
