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
