"""Defaults based on the public Ithaca 2026-27 competition description."""
INITIAL_CAPITAL = 1_000_000
MAX_POSITION = 0.25
MIN_STOCKS = 5
MAX_STOCKS = 20
MIN_PRICE = 5.0
BENCHMARK = "SPY"  # Benchmark only; the stock universe excludes ETFs by convention.
DEFAULT_TICKERS = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AVGO", "AMD",
    "TSLA", "PLTR", "CRM", "NFLX", "ORCL", "UBER", "CAT", "GE",
    "JPM", "LLY", "COST", "WMT",
]
COMPETITION_START = "2026-11-16"
COMPETITION_END = "2027-04-02"
RULES_URL = "https://edu.stocktrak.com/ithaca/high-school-investing-challenge-rules/"

# Bound research-agent scoring and per-operation concurrency.
MAX_AGENTS = 3
# Exactly two retry opportunities after the initial attempt (3 total).
MAX_RETRIES = 2

import os as _os
# v2.1 accuracy upgrades (robust targets, forecast shrinkage, extended feature
# candidates, probability blending, bad-tick sanitation). Set the environment
# variable ITHACA_LEGACY_MODEL=1 to reproduce v2.0 behaviour for A/B comparison.
def improved_accuracy() -> bool:
    return _os.environ.get("ITHACA_LEGACY_MODEL", "").strip().lower() not in ("1", "true", "yes")


def cross_sectional_target_enabled() -> bool:
    """v2.3: allow the same-day-demeaned training label (still gated on independent data).

    Set ITHACA_DISABLE_CS_TARGET=1 to force the raw SPY-relative label (v2.2 behaviour).
    """
    return improved_accuracy() and _os.environ.get("ITHACA_DISABLE_CS_TARGET", "").strip().lower() not in ("1", "true", "yes")
