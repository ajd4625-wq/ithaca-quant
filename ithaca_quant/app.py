"""Ithaca Quant — Streamlit dashboard for educational stock research.

Run: streamlit run app.py
No actual orders are placed; all allocations are hypothetical.
"""
import os
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ithaca_quant.backtest import run_walk_forward
from ithaca_quant.config import (
    BENCHMARK, COMPETITION_END, COMPETITION_START, DEFAULT_TICKERS,
    INITIAL_CAPITAL, MAX_POSITION, MAX_STOCKS, MIN_STOCKS, RULES_URL, MAX_AGENTS, MAX_RETRIES,
)
from ithaca_quant.data import demo_market_data, download_market_data, parse_tickers
from ithaca_quant.universe import fetch_current_universe, pick_scan_symbols, screen_candidates
from ithaca_quant.quotes import alpaca_iex_quotes, yahoo_latest_quotes, age_minutes
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.leaderboard import RANKING_MODES, rank_stocks, leaderboard_display, boom_model_quality
from ithaca_quant.metadata import add_metadata, fetch_company_metadata, load_company_metadata, market_cap_bucket
from ithaca_quant.portfolio import historical_risk, simulate_buy_hold, validate_allocations
from ithaca_quant.signals import plan_signals
from ithaca_quant.news import fetch_news, news_context
from ithaca_quant import __version__
from ithaca_quant.search import price_scenarios, review_dates
from ithaca_quant.validation import attach_quality, overall_quality, calibration_bins

st.set_page_config(page_title=f"Ithaca Quant v{__version__}", page_icon="📈", layout="wide")


@st.cache_data(ttl=60 * 60 * 8, show_spinner="Loading historical prices…")
def cached_data(mode: str, tickers: tuple[str, ...], years: int):
    if mode == "Synthetic demo":
        return demo_market_data(list(tickers), sessions=max(750, 252 * years))
    return download_market_data(list(tickers), years=years, batch_size=75)


@st.cache_data(ttl=60 * 60 * 12, show_spinner="Checking NYSE and Nasdaq listing directories…")
def cached_exchange_universe():
    return fetch_current_universe()


@st.cache_data(ttl=60 * 60 * 6, show_spinner="Scanning current U.S. listings in Yahoo price batches…")
def cached_screen(symbols: tuple[str, ...], shortlist_count: int, _progress=None):
    sample = download_market_data(
        list(symbols), years=1, min_history=140, batch_size=75, on_progress=_progress
    )
    all_screened = screen_candidates(sample.close, sample.volume, limit=None)
    finalists = screen_candidates(sample.close, sample.volume, limit=shortlist_count)
    return finalists, all_screened, len(sample.close.columns) - 1, len(sample.excluded)


@st.cache_data(ttl=50, show_spinner=False)
def cached_quotes(provider: str, tickers: tuple[str, ...], key: str, secret: str, nonce: int):
    del nonce  # Used to force a manual refresh of this cache.
    if provider.startswith("IEX"):
        return alpaca_iex_quotes(list(tickers), key, secret)
    return yahoo_latest_quotes(list(tickers))


@st.cache_data(show_spinner="Computing point-in-time features…")
def cached_panel(close: pd.DataFrame, volume: pd.DataFrame, horizon: int):
    return build_panel(close, volume, horizon)


@st.cache_data(show_spinner="Training models for today's ranking…")
def cached_ranking(panel: pd.DataFrame, asof: pd.Timestamp, fast: bool, boom_return: float):
    return forecast_asof(panel, asof, fast=fast, boom_return=boom_return)


@st.cache_data(show_spinner="Running embargoed, walk-forward out-of-sample tests…")
def cached_backtest(panel, close, horizon, top_n, exposure, cost_bps, periods, fast, boom_return):
    return run_walk_forward(
        panel, close, horizon=horizon, top_n=top_n, exposure=exposure,
        cost_bps=cost_bps, max_periods=periods, fast=fast, boom_return=boom_return,
    )


def pct(value: float) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:+.2%}"


def money(value: float) -> str:
    return f"${value:,.0f}"


def probability_pct(value: float) -> str:
    return "Insufficient history" if pd.isna(value) else f"{value:.1%}"


def stock_table(rank: pd.DataFrame, horizon: int, threshold: float) -> pd.DataFrame:
    result = pd.DataFrame({
        "Ticker": rank["ticker"],
        "Price (adjusted)": rank["close"].map(lambda x: f"${x:,.2f}"),
        f"Predicted {horizon}d excess vs SPY*": rank["forecast_excess"].map(pct),
        f"P(gain by {horizon}d)**": rank["prob_gain"].map(probability_pct),
        f"P(+{threshold:.0%} by {horizon}d)**": rank["prob_boom"].map(probability_pct),
        "Historical volatility": rank["vol_20"].map(lambda x: f"{x:.1%}"),
        "20d momentum": rank["mom_20"].map(pct),
    })
    if "industry" in rank:
        result.insert(1, "Industry", rank["industry"].fillna(""))
    if "market_cap" in rank:
        result.insert(2, "Market cap ($B)", pd.to_numeric(rank["market_cap"], errors="coerce") / 1e9)
    return result


def apply_company_filters(frame: pd.DataFrame, *, prefix: str) -> pd.DataFrame:
    """Filter only displayed stocks. No current metadata is fed to a forecast or historical backtest."""
    c1, c2, c3 = st.columns(3)
    known_sectors = sorted(v for v in frame["sector"].dropna().unique() if v)
    known_industries = sorted(v for v in frame["industry"].dropna().unique() if v)
    with c1:
        sectors = st.multiselect("Filter sector", known_sectors, key=f"{prefix}_sectors")
    with c2:
        industries = st.multiselect("Filter industry", known_industries, key=f"{prefix}_industries")
    with c3:
        sizes = ["All (including unknown)", "Known market cap only", "Mega (≥$200B)",
                 "Large ($10B–$200B)", "Mid ($2B–$10B)", "Small ($300M–$2B)", "Micro (<$300M)"]
        size = st.selectbox("Filter market cap", sizes, key=f"{prefix}_size")
    out = frame.copy()
    if sectors:
        out = out.loc[out["sector"].isin(sectors)]
    if industries:
        out = out.loc[out["industry"].isin(industries)]
    if size == "Known market cap only":
        out = out.loc[out["market_cap"].notna()]
    elif size != "All (including unknown)":
        out = out.loc[out["market_cap"].map(market_cap_bucket).eq(size)]
    return out.reset_index(drop=True)


def make_line_chart(df: pd.DataFrame, fields: dict[str, str], *, normalization: bool = False):
    fig = go.Figure()
    for field, name in fields.items():
        values = df[field]
        if normalization and len(values) and values.iloc[0] != 0:
            values = values / values.iloc[0]
        fig.add_trace(go.Scatter(x=df.index, y=values, name=name, mode="lines"))
    fig.update_layout(
        height=390, margin=dict(l=0, r=0, t=8, b=8),
        hovermode="x unified", legend=dict(orientation="h", y=1.12),
    )
    return fig


st.title(f"📈 Ithaca Quant v{__version__}")
st.caption("Research-grade workflow prototype · Educational forecasts · Virtual portfolio only")
st.info(
    f"**Competition:** ${INITIAL_CAPITAL:,.0f} virtual capital · "
    f"{MIN_STOCKS}–{MAX_STOCKS} stocks · maximum {MAX_POSITION:.0%} initial position "
    f"· {COMPETITION_START} to {COMPETITION_END}. "
    "Check each company's exchange eligibility with StockTrak."
)
with st.sidebar:
    st.header("Research settings")
    mode = st.radio("Historical data source", ["Yahoo Finance", "Synthetic demo"])
    if mode == "Synthetic demo":
        st.warning("DEMO: All prices and predictions are fictional.")
    universe_mode = st.radio(
        "Stock discovery",
        ["Automatic NYSE + Nasdaq universe", "Manual watchlist"],
        help="Automatic scans current listings, then trains deep models on a resource-limited shortlist.",
    )
    if universe_mode.startswith("Automatic"):
        scan_size = st.selectbox("Listings to scan", [500, 1500, 3000, "ALL available"], index=1,
                                 help="ALL may take minutes and can be limited by Yahoo's public data service.")
        shortlist_count = st.select_slider("Stocks to model deeply", options=[50, 100, 200, 300, 400, 600], value=200)
        min_dv = st.caption("Shortlist screen: >$5 stock price, at least $1M median daily dollar volume, and adequate price history.")
    else:
        universe_text = st.text_area(
            "Stock research universe (comma-separated)",
            value=", ".join(DEFAULT_TICKERS), height=110,
            help="SPY is only a performance benchmark, not a portfolio candidate.",
        )
    years = st.select_slider("Historical years for deep model", options=[3, 4, 5, 6, 7, 8], value=5)
    horizon = st.select_slider("Forecast horizon (sessions)", options=[10, 20, 40], value=20)
    boom_pct = st.select_slider("Boom event: gain at horizon close", options=[10, 15, 20, 30], value=20)
    boom_return = boom_pct / 100.0
    risk_budget_pct = st.slider("Max hypothetical risk per stock (% of portfolio)", 0.25, 2.0, 1.0, step=0.25)
    n_top = st.slider("Number of stocks in virtual portfolio", min_value=5, max_value=20, value=6)
    exposure = st.slider("Investment allocation (%)", 50, 100, 90, step=5) / 100
    costs = st.slider("Hypothetical turnover cost (basis points)", 0, 50, 10, step=5)
    test_periods = st.slider("Walk-forward test periods", 4, 24, 8, step=2)
    fast_mode = st.checkbox("Faster model (fewer trees)", value=True)
    st.markdown(f"[Official competition rules]({RULES_URL})")

scan_table = None
full_screen_table = None
scan_summary = None
if universe_mode.startswith("Automatic") and mode == "Yahoo Finance":
    try:
        directory = cached_exchange_universe()
        full_listings = directory.listings
        limit = None if scan_size == "ALL available" else int(scan_size)
        scan_symbols = pick_scan_symbols(full_listings, limit)
        scan_key = (tuple(scan_symbols), shortlist_count)
        st.info(
            f"Exchange directory found **{len(full_listings):,}** plausible non-ETF NYSE/Nasdaq "
            f"listings. Selected **{len(scan_symbols):,}** for the broad scan. "
            "Only the selected, filtered shortlist receives expensive ML forecasts."
        )
        if st.session_state.get("market_scan_key") != scan_key:
            st.warning("Run the broad scan once to select candidates for machine-learning forecasts.")
            if st.button("🔍 Scan NYSE + Nasdaq stocks", type="primary"):
                progress_ui = st.progress(0, text="Collecting batches of historical stock prices…")
                def progress(done, total, loaded):
                    progress_ui.progress(done / total, text=f"Batch {done}/{total}: {loaded:,} symbols loaded")
                screening, all_screened, downloaded_count, excluded_count = cached_screen(
                    tuple(scan_symbols), shortlist_count, _progress=progress
                )
                progress_ui.empty()
                st.session_state["market_scan_key"] = scan_key
                st.session_state["market_scan_data"] = (screening, all_screened, downloaded_count, excluded_count)
                st.rerun()
            st.stop()
        scan_table, full_screen_table, downloaded_count, excluded_count = st.session_state["market_scan_data"]
        if len(scan_table) < 5:
            st.error("Fewer than five liquid, eligible stocks were retrieved. Yahoo may be rate limiting; try a smaller scan.")
            st.stop()
        tickers = scan_table["ticker"].tolist()
        scan_summary = (len(full_listings), len(scan_symbols), downloaded_count, len(full_screen_table), len(scan_table), excluded_count)
    except Exception as exc:
        st.error(f"Automatic scan unavailable: {exc}")
        st.info("You can select Manual watchlist in the sidebar while the market-data sources are unavailable.")
        st.stop()
else:
    if universe_mode.startswith("Automatic") and mode == "Synthetic demo":
        st.info("Synthetic demo uses the default 20 fictional tickers, not the live exchange listing directory.")
        tickers = DEFAULT_TICKERS.copy()
    else:
        tickers = parse_tickers(universe_text)

if len(tickers) < 5 or len(tickers) > 1500:
    st.error("Enter between 5 and 1,500 distinct symbols for manual research. Automatic scanning supports wider listing coverage.")
    st.stop()

try:
    market = cached_data(mode, tuple(tickers), years)
    if len(market.close.columns) < MIN_STOCKS + 1:
        raise ValueError("Fewer than five valid stocks loaded. Add more tickers or retry download.")
    panel = cached_panel(market.close, market.volume, horizon)
    asof = panel["date"].max()
    rank = cached_ranking(panel, asof, fast_mode, boom_return)
    signals = plan_signals(rank, horizon=horizon, risk_budget_pct=risk_budget_pct)
except Exception as exc:
    st.error(f"Unable to prepare the research dataset: {exc}")
    st.write("If Yahoo Finance is unavailable, switch to **Synthetic demo** to test the app offline.")
    st.stop()

if market.excluded:
    st.warning(f"Missing or short-history symbols ({len(market.excluded):,}): "
               f"{', '.join(market.excluded[:20])}{' …' if len(market.excluded) > 20 else ''}")
if len(rank) < n_top:
    st.error(f"Only {len(rank)} rankable stocks are available; reduce the requested number or add tickers.")
    st.stop()

st.caption(
    f"Source: **{market.source}** · Last available trading session: **{asof.date()}** · "
    f"Universe: **{len(rank)} stocks** · Forecast horizon: **{horizon} sessions**. "
    "Market data is not a live execution feed."
)
st.caption(f"Research scoring agents: **{MAX_AGENTS}** (Forecast, Momentum, Risk) · "
           f"Data tasks use up to **{MAX_AGENTS}** parallel workers and at most "
           f"**{MAX_RETRIES} retries** after the first attempt. Provider-internal retries, "
           "if any, are outside this app's control.")
if mode == "Synthetic demo":
    st.error("SYNTHETIC DATA — do not use these rankings as real investment predictions.")

# Results are attached ONLY to the exact research configuration that was tested.
# Changes to the history, universe, horizon, threshold, model, etc. invalidate them.
validation_key = (
    tuple(tickers), mode, years, horizon, n_top, exposure, costs,
    test_periods, fast_mode, boom_return, str(asof.date()),
)


def current_validation():
    if st.session_state.get('last_run_key') == validation_key:
        return st.session_state.get('backtest')
    return None


def run_validation():
    try:
        # Do not show stale results from a previous test after an error.
        st.session_state.pop('backtest', None)
        result = cached_backtest(panel, market.close, horizon, n_top, exposure,
                                 costs, test_periods, fast_mode, boom_return)
        st.session_state['last_run_key'] = validation_key
        st.session_state['backtest'] = result
    except Exception as exc:
        st.session_state.pop('backtest', None)
        st.error(f'Validation could not run: {exc}')


search_tab, leaderboard_tab, research_tab, quote_tab, screen_tab, signals_tab, validation_tab, portfolio_tab, about_tab = st.tabs(
    ["🔍 Search stock + news", "🏆 Ranked leaderboard", "🔎 Stock rankings", "💲 Latest prices", "🌐 Marketwide screener", "🟡 Signals & risk",
     "🧪 Walk-forward tests", "💼 Virtual portfolio", "📘 Methodology"]
)

@st.cache_data(ttl=900, show_spinner="Fetching recent publisher headlines…")
def cached_publisher_news(ticker: str, company: str):
    return fetch_news(ticker, company)


with search_tab:
    st.subheader("🔍 Individual stock research + current headlines")
    st.caption("Search any U.S. ticker. If it is not in the trained universe, the app can show history and news, but will NOT invent an AI forecast.")
    symbol = st.text_input("Stock ticker", value="NVDA", max_chars=12, key="stock_search").strip().upper()
    if st.button("Analyze stock", key="analyze_search") and symbol:
        st.session_state["searched_symbol"] = symbol
    selected = st.session_state.get("searched_symbol", "NVDA")
    if not selected or not __import__('re').fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', selected):
        st.warning("Enter a valid stock ticker.")
    else:
        try:
            if selected in market.close.columns:
                history = market.close[selected].dropna()
            elif mode == "Synthetic demo":
                history = pd.Series(dtype=float)
            else:
                extra = cached_data("Yahoo Finance", (selected,), years)
                history = extra.close[selected].dropna() if selected in extra.close else pd.Series(dtype=float)
            if st.button("Update company profile", key="search_profile"):
                fetch_company_metadata([selected], max_new=1)
            company_frame = load_company_metadata([selected])
            company_name = ""
            if not company_frame.empty and 'company_name' in company_frame.columns:
                company_name = str(company_frame.iloc[0].get('company_name') or '')
            if history.empty:
                st.warning("No historical price series available for this ticker. Try another ticker or retry later.")
            else:
                st.line_chart(history.tail(504), x_label="Date", y_label="Adjusted historical close ($)")
                st.caption("Historical adjusted closes are NOT live quotes. Price targets below use adjusted closes for consistency.")
                row = rank.loc[rank['ticker'].eq(selected)]
                sig = signals.loc[signals['ticker'].eq(selected)]
                if row.empty:
                    st.info("This ticker was not in the modeled universe. Add it to the manual watchlist, or run a new broad scan that includes it, to get a model forecast and boom estimate.")
                else:
                    r = row.iloc[0]
                    z = sig.iloc[0]
                    scenario = price_scenarios(float(r['close']), float(r['forecast_excess']),
                                               market.close[BENCHMARK], float(r['vol_20']), horizon)
                    dates = review_dates(asof, horizon, str(z['entry_watch']), str(z['exit_review']))
                    c1,c2,c3,c4 = st.columns(4)
                    c1.metric("Illustrative target", f"${scenario['target']:,.2f}")
                    c2.metric("Boom estimate (unverified)", probability_pct(r['prob_boom']))
                    c3.metric("Volatility (annualized)", f"{r['vol_20']:.1%}")
                    c4.metric("Horizon volatility scale", f"±{scenario['risk_1sigma_pct']:.1f}%")
                    st.write(f"**Illustrative target range:** ${scenario['lower_1sigma']:,.2f} – ${scenario['upper_1sigma']:,.2f}. {scenario['method']}")
                    st.write(f"**Entry review date:** {dates['entry_review']} ({dates['entry_condition']}). "
                             f"**Exit review date:** {dates['exit_review']} ({dates['exit_condition']}). "
                             "These are scheduled condition checks, NOT predicted best buy/sell dates.")
                    st.write(f"**Hypothetical position risk budget:** {risk_budget_pct:.2f}% of portfolio; "
                             f"**risk-review threshold:** {z['stop_pct']:.1%} below adjusted close; "
                             f"**suggested maximum initial allocation under risk budget:** {z['max_starter_weight_pct']:.1f}%. "
                             "Price gaps can exceed these levels.")
                if not company_frame.empty:
                    m = company_frame.iloc[0]
                    cap = pd.to_numeric(m.get('market_cap'), errors='coerce')
                    st.write(f"**Company:** {company_name or selected} · **Sector:** {m.get('sector') or 'Unknown'} · "
                             f"**Industry:** {m.get('industry') or 'Unknown'} · "
                             f"**Market cap:** {'$'+format(cap/1e9,',.2f')+'B' if pd.notna(cap) else 'Unavailable'}")
            st.divider()
            st.subheader("📰 Recent financial news (Yahoo Finance, Fox Business, ABC News)")
            if mode == "Synthetic demo":
                st.warning("Synthetic demo forecasts are fictional. Headlines, when fetched, are real-world articles and must not be interpreted as validating synthetic prices.")
            if st.button("Fetch latest news", key="search_news_button"):
                st.session_state['news_lookup'] = (selected, company_name)
            if st.session_state.get('news_lookup', (None,None))[0] == selected:
                articles, errors = cached_publisher_news(selected, company_name)
                context = news_context(articles)
                st.write(f"**News context:** {context['label']} · {context['articles']} recent dated headlines · "
                         "simple keyword heuristic, NOT an AI price forecast")
                if errors:
                    st.caption("Unavailable sources: " + "; ".join(errors))
                if not articles:
                    st.info("No matching articles were retrieved from these publishers. Sources can have limited ticker coverage.")
                for article in articles[:24]:
                    date = article['published_utc'].strftime('%Y-%m-%d %H:%M UTC') if article['published_utc'] else 'Date unavailable'
                    st.markdown(f"**{article['publisher']}** · {date} · [Read article]({article['url']})")
                    st.write(article['title'])
            st.caption("News is fetched on demand and cached for 15 minutes. Today's news does NOT enter the historically trained AI models or backtests. "
                       "Adding news to ML predictions requires a licensed, timestamped historical news dataset and new point-in-time validation.")
        except Exception as exc:
            st.error(f"Stock lookup unavailable: {type(exc).__name__}: {exc}")

with leaderboard_tab:
    st.subheader("🏆 Ranked stock leaderboard")
    st.write(
        "Compare the companies with a full AI forecast. **Rank 1 means highest under the selected "
        "research formula, not the most likely guaranteed winner.** The broad-market screen "
        "covers more stocks, but only the modeled shortlist has AI forecasts."
    )
    st.markdown("**Out-of-sample accuracy & calibration**")
    if st.button("🧪 Run historical validation and add evidence to rankings",
                 key="lb_validation_button", type="primary"):
        run_validation()
    leaderboard_validation = current_validation()
    if leaderboard_validation is None:
        st.warning("No out-of-sample evidence for these settings. All rows will say "
                   "'Not tested' until you run validation. The model scores are NOT measured hit rates.")
    else:
        vm = leaderboard_validation.metrics
        vq = overall_quality(leaderboard_validation.predictions)
        summary_cols = st.columns(4)
        summary_cols[0].metric("OOS decision windows", f"{vq['signal_windows']}")
        summary_cols[1].metric("Relative direction hit", f"{vq['direction_hit']:.1%}")
        summary_cols[2].metric("Past-majority baseline", f"{vq['direction_baseline']:.1%}")
        summary_cols[3].metric("Boom event Brier", "N/A" if pd.isna(vq['boom_brier']) else f"{vq['boom_brier']:.4f}")
        st.caption(f"{vq['evidence']} · {vq['ticker_outcomes']:,} ticker-window evaluations across "
                   "correlated stocks; each stock generally has only one outcome per decision window. "
                   "Brier: lower is better. Compare to baseline in Walk-forward tests.")
    method = st.selectbox("Ranking method", RANKING_MODES, index=0,
        help="Balanced is a relative research score. The other methods rank their named indicator; none is a verified prediction of profit.")
    cfilter1, cfilter2, cfilter3 = st.columns(3)
    with cfilter1:
        leaderboard_size = st.select_slider("Show top stocks", options=[5, 10, 15, 20, 25, 50, 100, 200, 600], value=25)
    with cfilter2:
        max_vol_pct = st.slider("Maximum historical annual volatility (%)", 20, 300, 200, 10)
    with cfilter3:
        positives_only = st.checkbox("Positive forecast only", value=False)
    leaders = rank_stocks(rank, horizon, method=method, min_price=5.0,
                          max_volatility=max_vol_pct / 100.0,
                          positive_forecast_only=positives_only)
    st.markdown("**Company industry and market capitalization**")
    st.caption("Company profiles come from Yahoo Finance, are cached for 24 hours, and may be unavailable. "
               "Market cap is latest available company metadata, **not live**, and is never used in the backtest.")
    mcol1, mcol2 = st.columns([2, 3])
    with mcol1:
        detail_count = st.selectbox("Profiles to fetch per click", [10, 25, 50, 100], index=1, key="leader_meta_count")
    with mcol2:
        load_detail = st.button("↻ Load next missing/stale company profiles", key="leader_meta_button")
    if load_detail and not leaders.empty:
        progress_ui = st.progress(0, text="Loading company profiles from Yahoo Finance…")
        def metadata_progress(done, total):
            progress_ui.progress(done / max(total, 1), text=f"Company profiles: {done}/{total}")
        _, status = fetch_company_metadata(leaders["ticker"],
                                           max_new=detail_count, progress=metadata_progress)
        progress_ui.empty()
        st.session_state["leader_meta_status"] = status
    if "leader_meta_status" in st.session_state:
        status = st.session_state["leader_meta_status"]
        st.caption(f"Last request: {status['attempted']} downloaded/checked, "
                   f"{status['errors']} unavailable. Downloaded details are cached locally.")
    leader_metadata = load_company_metadata(leaders["ticker"])
    leaders = add_metadata(leaders, leader_metadata)
    st.caption(f"Company profiles cached: **{leaders['metadata_asof'].notna().sum():,} "
               f"of {len(leaders):,}** modeled names. Unavailable fields are shown blank, not guessed.")
    st.markdown("**Optional current-news overlay (experimental)**")
    st.caption("Fetches public Yahoo Finance, Fox Business and ABC News headlines for up to 5 top stocks. "
               "News language adds at most 5 points to the *displayed research score only*. "
               "It does not alter the trained AI forecasts or historically validated rankings.")
    if st.button("📰 Fetch news and build current-news ranking", key="leader_news_fetch"):
        news_rows = []
        for _, item in leaders.head(5).iterrows():
            articles, errors = cached_publisher_news(item['ticker'], str(item.get('company_name') or ''))
            ctx = news_context(articles)
            news_rows.append({'ticker': item['ticker'], 'News headlines': ctx['articles'],
                              'News sentiment': ctx['label'], 'news_score': ctx['score']})
        st.session_state['leader_news_context'] = news_rows
        st.session_state['leader_news_key'] = (tuple(tickers), str(asof.date()))
    if st.session_state.get('leader_news_key') == (tuple(tickers), str(asof.date())):
        overlays = pd.DataFrame(st.session_state.get('leader_news_context', []))
        if not overlays.empty:
            leaders = leaders.merge(overlays, on='ticker', how='left')
            leaders['News overlay score'] = (leaders['research_score'] +
                pd.to_numeric(leaders['news_score'], errors='coerce').fillna(0).clip(-3, 3) * (5/3)).round(1)
            st.dataframe(leaders.loc[leaders['news_score'].notna(),
                ['ticker', 'research_score', 'News overlay score', 'News headlines', 'News sentiment']]
                .sort_values('News overlay score', ascending=False), hide_index=True, use_container_width=True)
            st.caption("Only stocks with fetched news are comparable in this optional overlay. "
                       "The news score has no measured predictive accuracy and must not be read as a probability.")
    leaders = apply_company_filters(leaders, prefix="leader")
    leaders["rank"] = range(1, len(leaders) + 1)
    top = leaders.head(leaderboard_size)
    if leaders.empty:
        st.warning("No modeled stocks meet these filters. Raise the volatility limit or disable positive-forecast-only.")
    else:
        if method == "Balanced (upside + risk)":
            st.caption("**Balanced formula:** 55% predicted SPY-relative return rank + 15% "
                "20-day SPY-relative momentum + 20% low-volatility rank + 10% model-agreement rank. "
                "A 0–100 research score is **relative to the filtered shortlist**, not a success probability.")
        elif method == "Risk-adjusted forecast":
            st.caption("**Risk-adjusted formula:** predicted SPY-relative return ÷ "
                "(2% + historical horizon volatility + model disagreement). This is a heuristic, not a forecast Sharpe ratio.")
        elif method == "Boom probability (experimental)":
            quality, message = boom_model_quality(rank)
            (st.info if quality else st.warning)(message)
            if top["prob_boom"].isna().all():
                st.warning("No usable event probabilities for this threshold; try a smaller boom threshold or longer history.")
            st.caption("The +%d%% event means the horizon's closing price reaches the threshold. "
                "These probabilities are experimental and may be seriously miscalibrated." % boom_pct)
        elif method == "Forecast upside":
            st.caption("Ranked by predicted **excess** return over SPY, not the stock's absolute return. "
                "A model can forecast SPY-relative outperformance even while a stock falls.")
        else:
            st.caption("Ranked using 20-day historical stock performance minus SPY's. "
                "Past momentum is not a predicted future return.")

        col1, col2, col3 = st.columns(3)
        col1.metric("#1 research candidate", str(top.iloc[0]["ticker"]))
        col2.metric("Eligible modeled stocks", f"{len(leaders):,}")
        col3.metric("Shown in leaderboard", f"{len(top):,}")

        company_info = directory.listings if (scan_table is not None and universe_mode.startswith("Automatic")) else None
        table = leaderboard_display(top, horizon, boom_return, signals=signals, company_info=company_info)
        table = attach_quality(table, leaderboard_validation.predictions if leaderboard_validation is not None else None)
        formatted = table.copy()
        for col in ("OOS direction hit", "OOS forecast MAE", "OOS zero-forecast MAE"):
            formatted[col] = formatted[col].map(lambda v: "Not tested" if pd.isna(v) else f"{v:.1%}")
        for col in ("OOS boom Brier", "OOS boom baseline Brier"):
            formatted[col] = formatted[col].map(lambda v: "Not tested" if pd.isna(v) else f"{v:.4f}")
        rate_columns = [c for c in formatted.columns if c.startswith(("Forecast vs SPY", "P(gain,", "P(+", "Historical 1σ", "Annualized volatility", "20d vs SPY", "Model disagreement"))]
        for c in rate_columns:
            formatted[c] = formatted[c].map(lambda v: "N/A" if pd.isna(v) else f"{v:+.1%}" if c.startswith(("Forecast vs SPY", "20d vs SPY")) else f"{v:.1%}")
        st.dataframe(formatted, hide_index=True, use_container_width=True,
            column_config={
                "Rank": st.column_config.NumberColumn(format="%d", width="small"),
                "Research score /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Forecast agent /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Momentum agent /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Risk agent /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                "Adjusted daily close ($)": st.column_config.NumberColumn(format="$%.2f"),
            })
        st.caption("**New evidence columns:** OOS windows = number of nonoverlapping historical test windows for that "
                   "ticker; direction hit = fraction of positive/negative SPY-relative signs forecast correctly; "
                   "forecast MAE = absolute SPY-relative error. The zero-forecast MAE and historical-frequency boom "
                   "Brier are naive baselines. Fewer than 12 windows means TOO FEW TESTS, even when the hit rate "
                   "looks high. This historical evaluation cannot validate any current individual forecast.")
        st.caption("The Forecast, Momentum and Risk agents are the only three deterministic scoring "
                   "components; they do not independently call AI services. The values are ranks, "
                   "not probabilities of profit.")
        st.caption("The leaderboard ranks stocks relative to the screened universe. "
                   "* Experimental event estimates, not proven probabilities. "
                   "** 1σ is a historical-volatility approximation under square-root-of-time scaling; "
                   "actual outcomes may be far outside this range. Adjusted closes are not live trade prices.")
        st.caption("Click the Market cap ($B) column heading to sort by company size. "
                   "Current company data is not part of the AI score; filters re-number the displayed ranking.")
        st.download_button("Download ranked stocks CSV", table.to_csv(index=False),
                           file_name="ithaca_ranked_stock_leaderboard.csv", mime="text/csv")
        st.markdown("**Latest-price overlay (optional)**")
        show_quotes = st.checkbox("Show latest available quotes for the top stocks (up to 50)", value=False,
                                  help="Quotes can be delayed or stale. This does not recalculate end-of-day ML forecasts.")
        if show_quotes:
            if st.button("↻ Refresh leaderboard quotes"):
                st.session_state["leaderboard_quote_nonce"] = st.session_state.get("leaderboard_quote_nonce", 0) + 1
            quote_symbols = tuple(top.head(50)["ticker"])
            try:
                q = cached_quotes("Yahoo intraday (may be delayed)", quote_symbols, "", "",
                                  st.session_state.get("leaderboard_quote_nonce", 0))
                if q.empty:
                    st.warning("No latest quotes received from Yahoo; try again later.")
                else:
                    quote_view = q[["ticker", "price", "timestamp_utc", "feed"]].copy()
                    quote_view["Age (minutes)"] = quote_view["timestamp_utc"].map(age_minutes)
                    quote_view = quote_view.rename(columns={"ticker": "Ticker", "price": "Latest available raw price ($)",
                        "timestamp_utc": "Trade time (UTC)", "feed": "Quote source"})
                    merged = table[["Rank", "Ticker"]].merge(quote_view, how="left", on="Ticker")
                    st.dataframe(merged, hide_index=True, use_container_width=True)
                    st.warning("Yahoo's latest quotes may be delayed or stale. Forecasts and ranks use historical daily data "
                               "and do NOT refresh with these quotes; quote prices may differ from split-adjusted closes.")
            except Exception as exc:
                st.warning(f"Latest price overlay is unavailable: {exc}")
        inspect = st.selectbox("Inspect a ranked stock", top["ticker"].tolist(), key="leaderboard_chart")
        history = market.close[[inspect, BENCHMARK]].dropna().tail(252)
        if len(history) > 1:
            st.plotly_chart(make_line_chart(history, {inspect: inspect, BENCHMARK: "SPY"}, normalization=True),
                            use_container_width=True)
            st.caption("Historical one-year price comparison, normalized to 1; not a forecast.")

with research_tab:
    st.subheader("Research rankings")
    st.write(
        "The two models estimate **excess return versus SPY** over the next "
        f"**{horizon} trading sessions**. Scores are uncertain model outputs, "
        "not guaranteed gains, probabilities, or buy signals."
    )
    research_info = add_metadata(rank, load_company_metadata(rank["ticker"]))
    research_table = stock_table(research_info, horizon, boom_return)
    research_validation = current_validation()
    research_table = attach_quality(research_table, research_validation.predictions if research_validation is not None else None)
    st.dataframe(research_table, hide_index=True, use_container_width=True)
    if research_validation is None:
        st.caption("OOS validation not run for these settings. Use the leaderboard's validation button or Walk-forward tests tab.")
    else:
        st.caption("The OOS columns describe past nonoverlapping forecast windows, NOT verified live reliability. "
                   "Small per-ticker samples are inconclusive. Lower mean absolute error and Brier are better.")
    st.download_button('Download research rankings with validation CSV', research_table.to_csv(index=False),
                       file_name='ithaca_rankings_accuracy.csv', mime='text/csv')
    st.caption(
        "* Excess return = forecast stock return minus forecast SPY return; this is not an "
        "absolute-price target. ** Probabilities come from historical event classifiers and "
        "have NOT been proven reliable out-of-sample. A 'boom' means the stock CLOSES "
        f"up at least {boom_pct}% after {horizon} sessions, not that it touches that level earlier."
    )
    best = rank.iloc[0]
    a, b, c, d = st.columns(4)
    a.metric("Highest model-ranked ticker", best["ticker"])
    b.metric("Its 20d historical momentum", pct(best["mom_20"]))
    c.metric("Its annualized 20d volatility", f"{best['vol_20']:.1%}")
    d.metric("Available stock candidates", len(rank))
    selected_ticker = st.selectbox("Inspect historical prices", options=rank["ticker"].tolist())
    shown = market.close[[selected_ticker, BENCHMARK]].dropna().tail(252)
    st.plotly_chart(make_line_chart(shown, {selected_ticker: selected_ticker, BENCHMARK: "SPY"}, normalization=True), use_container_width=True)
    st.caption("Both price series normalized to 1 at the start of the displayed year; historical performance only.")
    event = rank.iloc[0]
    if pd.notna(event['prob_boom']):
        st.caption(
            f"Current training-set historical event frequency for +{boom_pct}%: "
            f"{event['boom_base_rate']:.1%} ({int(event['boom_event_count'])} events "
            f"in {int(event['boom_train_rows']):,} overlapping training rows). "
            "A sample event rate is not a forecast for any individual stock."
        )
        if pd.notna(event['boom_holdout_brier']):
            st.write(
                f"Chronological holdout Brier score (smaller is better): "
                f"model **{event['boom_holdout_brier']:.4f}**, "
                f"constant-rate baseline **{event['boom_holdout_baseline_brier']:.4f}** "
                f"on {int(event['boom_holdout_n']):,} test rows. "
                "This check is not a guarantee of future calibration."
            )
    else:
        st.warning('Too few historical boom events to estimate this threshold reliably. Try a smaller threshold or longer history.')

with quote_tab:
    st.subheader("Latest available stock prices and quotes")
    st.warning(
        "**Forecast model prices are split/dividend-adjusted daily closes, NOT live executable prices.** "
        "Quote prices below are raw last trades. Yahoo intraday bars can be delayed or stale. "
        "IEX real-time quotes cover only IEX activity, not the entire U.S. market."
    )
    quote_source = st.radio("Quote source", ["Yahoo intraday (may be delayed)", "IEX real-time (authorized Alpaca market-data credentials)"],
                            horizontal=True)
    n_quote = st.slider("Number of top-ranked symbols to refresh", 5, 50, 20, 5)
    extra_quotes = st.text_input("Additional symbols to watch (comma separated)", value="",
                                 help="Optional symbols not in the ranked shortlist")
    quote_symbols = tuple(dict.fromkeys(rank.head(n_quote)["ticker"].tolist() + parse_tickers(extra_quotes)))[:75]
    alpaca_key = ""
    alpaca_secret = ""
    if quote_source.startswith("IEX"):
        st.info("IEX quotes require an authorized market-data API key. Use only credentials you are permitted to access; do not bypass provider age or account requirements.")
        alpaca_key = st.text_input("Market-data API key ID", value=os.environ.get("APCA_API_KEY_ID", ""), type="password")
        alpaca_secret = st.text_input("Market-data API secret", value=os.environ.get("APCA_API_SECRET_KEY", ""), type="password")
    auto_quotes = st.checkbox("Refresh quote panel approximately every 60 seconds", value=False)

    @st.fragment(run_every="60s" if auto_quotes else None)
    def show_latest_quotes():
        if quote_source.startswith("IEX") and (not alpaca_key or not alpaca_secret):
            st.info("Enter authorized data-access credentials above to load IEX latest trades.")
            return
        if st.button("↻ Refresh prices now", key="refresh_prices"):
            st.session_state["quote_refresh_nonce"] = st.session_state.get("quote_refresh_nonce", 0) + 1
        nonce = st.session_state.get("quote_refresh_nonce", 0)
        try:
            prices = cached_quotes(quote_source, quote_symbols, alpaca_key, alpaca_secret, nonce)
        except Exception as exc:
            st.error(f"Quote refresh failed: {exc}")
            return
        if prices.empty:
            st.warning("No latest trade bars were returned. Check symbols/provider access or try later.")
            return
        prices = prices.copy()
        prices["Age (minutes)"] = prices["timestamp_utc"].map(age_minutes)
        prices["Quote status"] = prices["Age (minutes)"].map(
            lambda a: "Unknown" if a is None or pd.isna(a) else "STALE (>15m)" if a > 15 else "Recent (<=15m)"
        )
        prices = prices.rename(columns={"ticker":"Ticker", "price":"Last trade (raw)",
                                         "bid":"Bid (raw)", "ask":"Ask (raw)",
                                         "timestamp_utc":"Trade time (UTC)", "feed":"Source"})
        st.dataframe(prices[["Ticker", "Last trade (raw)", "Bid (raw)", "Ask (raw)",
                             "Trade time (UTC)", "Age (minutes)", "Quote status", "Source"]],
                     hide_index=True, use_container_width=True,
                     column_config={"Last trade (raw)": st.column_config.NumberColumn(format="$%.2f"),
                                    "Bid (raw)": st.column_config.NumberColumn(format="$%.2f"),
                                    "Ask (raw)": st.column_config.NumberColumn(format="$%.2f"),
                                    "Age (minutes)": st.column_config.NumberColumn(format="%.1f")})
        st.caption(
            f"Quote panel loaded {len(prices)} of {len(quote_symbols)} requested symbols · "
            f"Checked {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC. "
            "Markets close overnight/weekends; last trade may not be current. Prices are informational, "
            "not guaranteed fills or synchronized StockTrak prices."
        )
    show_latest_quotes()

with screen_tab:
    st.subheader("Broad market coverage and screen")
    if scan_table is None:
        st.info("Switch the sidebar to **Automatic NYSE + Nasdaq universe** and select Yahoo Finance to run the broad scan.")
    else:
        a, b, c, d, e, f = scan_summary
        columns = st.columns(5)
        columns[0].metric("Possible current listings", f"{a:,}")
        columns[1].metric("Requested for screening", f"{b:,}")
        columns[2].metric("Retrieved with basic history", f"{c:,}")
        columns[3].metric("Price/liquidity eligible", f"{d:,}")
        columns[4].metric("Deep ML shortlist", f"{e:,}")
        st.caption(f"{f:,} missing/short-history ticker downloads excluded from the broad scan. "
                   "Directory and price-provider coverage vary; listing is NOT proof of StockTrak eligibility.")
        st.write("**All price/liquidity eligible stocks — numbered basic screening leaderboard**")
        st.caption("The basic screen ranks by liquidity (50%), recent 60-day momentum (30%), and historical volatility (20%). "
                   "It does **not** produce AI return predictions. High volatility can lead to large losses.")
        st.caption("Industry/market cap are supplied by a separate company-profile lookup. "
                   "They are unknown for un-enriched stocks; retrieving thousands of profiles at once may be rate-limited.")
        n_detail = st.selectbox("Screened profiles to fetch per click", [10, 25, 50, 100], index=1, key="screen_meta_count")
        if st.button("↻ Load next missing/stale screened company profiles", key="screen_meta_button"):
            progress_ui = st.progress(0, text="Loading company profiles…")
            def screen_metadata_progress(done, total):
                progress_ui.progress(done / max(total, 1), text=f"Company profiles: {done}/{total}")
            _, status = fetch_company_metadata(full_screen_table["ticker"],
                                               max_new=n_detail, progress=screen_metadata_progress)
            progress_ui.empty()
            st.session_state["screen_meta_status"] = status
        if "screen_meta_status" in st.session_state:
            status = st.session_state["screen_meta_status"]
            st.caption(f"Last metadata request: {status['attempted']} attempted, {status['errors']} unavailable.")
        broad_ranked = add_metadata(full_screen_table.reset_index(drop=True),
                                    load_company_metadata(full_screen_table["ticker"]))
        broad_ranked = broad_ranked.merge(
            directory.listings[["data_ticker", "name", "exchange"]].drop_duplicates("data_ticker"),
            how="left", left_on="ticker", right_on="data_ticker", sort=False
        )
        broad_ranked["company_name"] = broad_ranked["company_name"].where(
            broad_ranked["company_name"].notna() & broad_ranked["company_name"].ne(""),
            broad_ranked["name"]
        )
        st.caption(f"Loaded metadata for {broad_ranked['metadata_asof'].notna().sum():,} of "
                   f"{len(broad_ranked):,} screened names. Market caps may be stale.")
        broad_ranked = apply_company_filters(broad_ranked, prefix="screen")
        broad_ranked.insert(0, "rank", range(1, len(broad_ranked) + 1))
        broad_ranked["Market cap ($B)"] = pd.to_numeric(broad_ranked["market_cap"], errors="coerce") / 1e9
        broad_visible = broad_ranked[["rank", "ticker", "company_name", "exchange", "sector", "industry", "Market cap ($B)",
                                      "price", "avg_dollar_volume", "momentum_20", "momentum_60", "volatility_20", "screen_score", "metadata_asof"]]
        st.dataframe(broad_visible, use_container_width=True, hide_index=True,
                     column_config={"Market cap ($B)": st.column_config.NumberColumn(format="%.2f")})
        st.download_button("Export displayed eligible screened stocks CSV", broad_visible.to_csv(index=False),
                           file_name="ithaca_all_screened_stocks.csv", mime="text/csv")
        st.write("**Shortlist receiving the full forecasting models**")
        shortlist = add_metadata(scan_table, load_company_metadata(scan_table["ticker"]))
        shortlist = shortlist.merge(
            directory.listings[["data_ticker", "name", "exchange"]].drop_duplicates("data_ticker"),
            how="left", left_on="ticker", right_on="data_ticker", sort=False
        )
        shortlist["company_name"] = shortlist["company_name"].where(
            shortlist["company_name"].notna() & shortlist["company_name"].ne(""), shortlist["name"]
        )
        shortlist["Market cap ($B)"] = pd.to_numeric(shortlist["market_cap"], errors="coerce") / 1e9
        st.dataframe(shortlist, use_container_width=True, hide_index=True)
        st.download_button("Export deep-model shortlist CSV", shortlist.to_csv(index=False),
                           file_name="ithaca_ml_shortlist.csv", mime="text/csv")
        st.warning("This screen is NOT a model ranking. Current-listing backtests omit delisted companies (survivorship bias).")

with signals_tab:
    st.subheader('End-of-day entry / exit watches and risk budgeting')
    st.info(
        '**No exact buy/sell timestamps can be predicted.** Signals use only the latest '
        "available daily closing data. Review them **before the next market session**, "
        "check the actual live price and StockTrak rules, and re-evaluate at least after "
        f"{horizon} trading sessions. This dashboard does not place orders."
    )
    st.write(
        'ENTRY WATCH requires positive predicted excess return, positive relative ' 
        '20-day momentum and a price above both its 20- and 60-day averages. ' 
        'REVIEW EXIT flags a price materially below the 20-day average or a negative ' 
        'excess-return forecast. These are transparent research rules, not validated trading signals.'
    )
    display = pd.DataFrame({
        'Ticker': signals['ticker'],
        'Entry condition': signals['entry_watch'],
        'Exit watch': signals['exit_review'],
        'Adjusted last close*': signals['close'].map(lambda x: f'${x:,.2f}'),
        '20d moving avg*': signals['moving_average_20'].map(lambda x: f'${x:,.2f}'),
        'Illustrative risk-review level*': signals['review_level'].map(lambda x: f'${x:,.2f}'),
        'Risk distance': signals['stop_pct'].map(lambda x: f'{x:.1%}'),
        'Max illustrative position': signals['max_starter_value'].map(money),
        'Max initial shares': signals['max_starter_shares'],
    })
    st.dataframe(display, hide_index=True, use_container_width=True)
    st.caption(
        f'Position limit = smaller of 25% of $1,000,000 and a {risk_budget_pct:.2f}% portfolio-risk budget ' 
        'divided by a hypothetical stop distance. This is a risk-sizing example, not ' 
        'a recommended trade. Gaps and slippage can cause losses far beyond any stop level. ' 
        '*Adjusted historical closes and calculated reference levels are NOT executable quotes.'
    )
    ticker_signal = st.selectbox('Inspect a signal', signals['ticker'].tolist(), key='signal_ticker')
    chosen = signals.set_index('ticker').loc[ticker_signal]
    c1, c2, c3 = st.columns(3)
    c1.metric('Entry watch', str(chosen['entry_watch']))
    c2.metric('Exit watch', str(chosen['exit_review']))
    c3.metric('Review-level distance', f"{chosen['stop_pct']:.1%}")
    st.write(
        f"For **{ticker_signal}**, review market conditions at the **next open session**. "
        f"The trailing model's {horizon}-session horizon is approximately "
        f"{horizon/5:.0f} trading weeks. The reference risk level "
        f"(${chosen['review_level']:.2f}) is a hypothetical risk alert, not a "
        "forecasted bottom or an automatic sell order."
    )
    st.download_button('Export signals and risk plan CSV',
                       signals.to_csv(index=False), file_name='ithaca_signals.csv',
                       mime='text/csv')

with validation_tab:
    st.subheader("Walk-forward out-of-sample validation")
    st.write(
        "At each historical decision date, training includes only examples whose "
        "**forecast outcome was already known**. The model then selects stocks "
        "and is scored over the next nonoverlapping test window."
    )
    st.warning(
        "Important: The hand-picked, currently available tickers introduce "
        "survivorship bias. Results are experimental, not proof of predictive skill. "
        "Re-running the test while selecting the best settings also causes overfitting."
    )
    if st.button("Run walk-forward backtest", type="primary", use_container_width=True):
        run_validation()
    if current_validation() is not None:
        result = current_validation()
        m = result.metrics
        cols = st.columns(4)
        cols[0].metric("Model strategy return", pct(m["portfolio_return"]))
        cols[1].metric("SPY return (same period)", pct(m["benchmark_return"]))
        cols[2].metric("Momentum baseline return", pct(m["momentum_return"]))
        cols[3].metric("Beat SPY in windows", f"{m['period_hit_rate']:.0%}")
        st.caption(
            f"{int(m['periods'])} nonoverlapping evaluated windows · "
            f"average rank correlation (Spearman IC): {m['mean_rank_ic']:.3f} · "
            f"model maximum observed window-end drawdown: {m['portfolio_max_drawdown']:.1%} · "
            f"average model turnover: {m['average_turnover']:.0%}"
        )
        st.subheader('Historical relative-return forecast accuracy')
        q = overall_quality(result.predictions)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('Direction correctly predicted', f"{q['direction_hit']:.1%}")
        c2.metric('Past-majority direction baseline', f"{q['direction_baseline']:.1%}")
        c3.metric('Forecast excess-return MAE', f"{q['excess_mae']:.1%}")
        c4.metric('Predict-zero MAE baseline', f"{q['excess_zero_mae']:.1%}")
        st.caption(f"{q['signal_windows']} distinct, nonoverlapping decision windows and "
                   f"{q['ticker_outcomes']:,} ticker outcomes; dates, tickers and observed results "
                   "are exportable below. Forecast directional hit rate is for SPY-RELATIVE sign, "
                   "not whether the stock price went up. Signals from the same window share market risk.")
        if q['signal_windows'] < 12:
            st.warning('Fewer than 12 independent decision windows: accuracy is too noisy to interpret as reliable.')
        elif q['direction_hit'] <= q['direction_baseline'] or q['excess_mae'] >= q['excess_zero_mae']:
            st.warning('At least one forecast accuracy measure fails its naive baseline. Results do not support a reliable edge.')
        else:
            st.info('Some out-of-sample metrics beat naive baselines. This is still preliminary and is not live evidence.')
        st.subheader(f'Out-of-sample boom-probability check (+{boom_pct}% at {horizon} sessions)')
        if m['boom_evaluated_predictions']:
            if m['boom_brier'] >= m['boom_baseline_brier']:
                st.warning('The boom classifier did NOT outperform a historical-frequency baseline on these windows. Do not treat its probabilities as reliable signals.')
            else:
                st.info('The boom classifier beat its simple baseline on these windows, but the test is small and does not establish reliable probability calibration.')
            bs1, bs2, bs3 = st.columns(3)
            bs1.metric('Model Brier (lower better)', f"{m['boom_brier']:.4f}")
            bs2.metric('Past-frequency baseline Brier', f"{m['boom_baseline_brier']:.4f}")
            bs3.metric('Observed event frequency', f"{m['boom_observed_frequency']:.1%}")
            st.caption(
                f"{m['boom_evaluated_predictions']} scored historical ticker-window outcomes; "
                f"mean model probability {m['boom_mean_probability']:.1%}. "
                "Overlapping stocks and repeated horizons are correlated; these estimates are noisy. "
                "Model probabilities should not be trusted if they do not beat the baseline."
            )
        else:
            st.warning('Insufficient observed boom events in these training windows to evaluate a probability model.')
        st.subheader('Probability calibration: predicted vs. observed frequency')
        st.caption('Compare past predicted event rates with actual event frequencies, grouped by predicted chance. '
                   'Brier measures squared probability error (lower is better). A close match is NOT proof of '
                   'live calibration; bins with very few observations are extremely noisy.')
        gain_score = q['gain_brier']
        boom_score = q['boom_brier']
        cg, cb = st.columns(2)
        cg.metric('Gain Brier / historical baseline',
                  'N/A' if pd.isna(gain_score) else f"{gain_score:.4f} / {q['gain_baseline_brier']:.4f}")
        cb.metric('Boom Brier / historical baseline',
                  'N/A' if pd.isna(boom_score) else f"{boom_score:.4f} / {q['boom_baseline_brier']:.4f}")
        event_type = st.radio('Which historical event?', ['boom', 'gain'], horizontal=True)
        cal = calibration_bins(result.predictions, event_type)
        if cal.empty:
            st.warning('No valid out-of-sample probability predictions were available for this event.')
        else:
            cal_display = cal.copy()
            st.dataframe(cal_display, hide_index=True, use_container_width=True)
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode='lines', name='Perfect calibration',
                                     line=dict(dash='dash', color='gray')))
            fig.add_trace(go.Scatter(x=cal['mean_predicted'], y=cal['observed_frequency'],
                                     text=cal['bucket'] + ' · n=' + cal['n'].astype(str),
                                     name='Historical bins', mode='markers+lines',
                                     marker=dict(size=10)))
            fig.update_layout(height=330, xaxis=dict(range=[0, 1], title='Mean predicted probability'),
                              yaxis=dict(range=[0, 1], title='Observed event frequency'),
                              margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"{len(cal)} populated calibration bins; bins with fewer than 20 evaluations "
                       "are especially unstable. Current displayed scores are not re-calibrated by this chart.")
        st.download_button('Download all historical OOS predictions CSV',
                           result.predictions.to_csv(index=False),
                           file_name='ithaca_oos_predictions_and_outcomes.csv', mime='text/csv')
        equity = result.periods.set_index("end")[["model_nav", "momentum_nav", "spy_nav"]].copy()
        equity.loc[pd.Timestamp(result.periods.iloc[0]["date"])] = [1.0, 1.0, 1.0]
        equity = equity.sort_index()
        st.plotly_chart(make_line_chart(equity, {
            "model_nav": "Model portfolio", "momentum_nav": "Momentum baseline", "spy_nav": "SPY",
        }), use_container_width=True)
        table = result.periods[["date", "end", "model_return", "spy_return", "rank_ic", "top_stocks"]].copy()
        table["date"] = table["date"].dt.date
        table["end"] = table["end"].dt.date
        table["model_return"] = table["model_return"].map(pct)
        table["spy_return"] = table["spy_return"].map(pct)
        table["rank_ic"] = table["rank_ic"].round(3)
        st.dataframe(table, hide_index=True, use_container_width=True)
        st.download_button("Download backtest periods CSV", result.periods.to_csv(index=False),
                           file_name="ithaca_walkforward.csv", mime="text/csv")
    else:
        st.info("Press **Run walk-forward backtest** to train and compare historical strategies.")

with portfolio_tab:
    st.subheader("$1,000,000 simulated buy-and-hold portfolio")
    st.write(
        "Edit ticker symbols and desired **initial portfolio weights** below. "
        "For a selected historical starting close, the app buys whole shares and "
        "marks them to the last available adjusted close. It does **not** sync "
        "with StockTrak or execute orders."
    )
    if n_top == 6:
        initial_weights = [round(w * exposure / 0.90, 2)
                           for w in [20.0, 18.0, 16.0, 14.0, 12.0, 10.0]]
    else:
        initial_weights = [round(min(100 * exposure / n_top, MAX_POSITION * 100), 2)] * n_top
    default_alloc = pd.DataFrame({
        "ticker": rank.head(n_top)["ticker"].tolist(),
        "weight_pct": initial_weights,
    })
    allocation_input = st.data_editor(
        default_alloc, num_rows="dynamic", hide_index=True, use_container_width=True,
        key=f"alloc-{mode}-{horizon}-{hash(tuple(tickers))}-{n_top}-{asof.date()}",
        column_config={"ticker": st.column_config.TextColumn("Ticker"),
                       "weight_pct": st.column_config.NumberColumn("Weight (%)", min_value=0.0, max_value=100.0, step=1.0)},
    )
    errors = []
    alloc = {}
    for _, row in allocation_input.iterrows():
        ticker = str(row["ticker"]).strip().upper()
        if not ticker or ticker == "NAN":
            continue
        try:
            weight = float(row["weight_pct"]) / 100
        except (TypeError, ValueError):
            errors.append(f"Invalid weight for {ticker}.")
            continue
        if ticker in alloc:
            errors.append(f"Duplicate ticker {ticker}.")
        if weight < 0:
            errors.append(f"Weight for {ticker} must not be negative.")
        alloc[ticker] = weight

    dates = market.close.index[-min(252, len(market.close)):].tolist()
    possible_dates = [dt for dt in dates if dt <= asof]
    if not possible_dates:
        st.error("No historical session is available for a portfolio entry date.")
        st.stop()
    competition_candidates = [dt for dt in possible_dates if dt >= pd.Timestamp(COMPETITION_START)]
    default_entry = competition_candidates[0] if competition_candidates else possible_dates[max(0, len(possible_dates) - 21)]
    entry = st.select_slider(
        "Hypothetical purchase date (at adjusted closing prices)",
        options=possible_dates, value=default_entry,
        format_func=lambda d: d.strftime("%b %d, %Y"),
    )
    errors.extend(validate_allocations(alloc, market.close, entry))
    if errors:
        for err in dict.fromkeys(errors):
            st.error(err)
    else:
        equity, holdings, cash = simulate_buy_hold(market.close, entry, alloc, INITIAL_CAPITAL)
        latest_value = float(equity["portfolio"].iloc[-1])
        risk = historical_risk(market.close.loc[:entry], alloc, horizon=horizon)
        cols = st.columns(4)
        cols[0].metric("Current hypothetical value", money(latest_value))
        cols[1].metric("Hypothetical total P&L", money(latest_value - INITIAL_CAPITAL))
        cols[2].metric("Hypothetical return", pct(latest_value / INITIAL_CAPITAL - 1))
        cols[3].metric("Cash remaining", money(cash))
        st.plotly_chart(make_line_chart(equity, {"portfolio": "Model portfolio value"}), use_container_width=True)
        st.dataframe(
            holdings.rename(columns={
                "ticker": "Ticker", "shares": "Shares", "entry_price": "Entry adjusted price",
                "latest_price": "Latest adjusted price", "initial_value": "Initial value",
                "market_value": "Marked value", "pnl": "Unrealized P&L",
            }).style.format({
                "Entry adjusted price": "${:,.2f}", "Latest adjusted price": "${:,.2f}",
                "Initial value": "${:,.0f}", "Marked value": "${:,.0f}", "Unrealized P&L": "${:,.0f}",
            }), hide_index=True, use_container_width=True,
        )
        st.subheader('Hypothetical risk-budget checks')
        plan_for_risk = signals.set_index('ticker')
        risk_checks = []
        for sym, weight in alloc.items():
            if weight <= 0 or sym not in plan_for_risk.index:
                continue
            planned_distance = float(plan_for_risk.loc[sym, 'stop_pct'])
            estimated_portfolio_risk_pct = 100 * weight * planned_distance
            risk_checks.append({
                'Ticker': sym,
                'Planned allocation': f'{weight:.1%}',
                'Reference stop distance': f'{planned_distance:.1%}',
                'Hypothetical risk if reference reached': f'{estimated_portfolio_risk_pct:.2f}% of portfolio',
                'Above individual risk budget': estimated_portfolio_risk_pct > risk_budget_pct + 1e-9,
            })
        if risk_checks:
            risk_table = pd.DataFrame(risk_checks)
            st.dataframe(risk_table, hide_index=True, use_container_width=True)
            if risk_table['Above individual risk budget'].any():
                st.warning('One or more selected positions exceed the hypothetical per-stock loss budget. Review initial weights on the portfolio tab.')
            st.caption('Reference levels are not executable orders, and losses can exceed this simplistic risk estimate.')
        st.subheader("Historical risk snapshot (before selected entry date)")
        if risk:
            rcols = st.columns(4)
            rcols[0].metric("Annualized historical vol", f"{risk['annualized_volatility']:.1%}")
            rcols[1].metric(f"Past {horizon}d 5th-percentile return", pct(risk["historical_95pct_20d_return"]))
            rcols[2].metric(f"Past {horizon}d avg tail return", pct(risk["historical_95pct_20d_tail_avg"]))
            rcols[3].metric("Historical maximum drawdown", pct(risk["historical_max_drawdown"]))
            st.caption(
                "Risk is estimated from trailing weighted returns BEFORE the hypothetical purchase "
                "date. Overlapping rolling periods are not independent; tail estimates are unstable."
            )
        else:
            st.info("Not enough pre-entry price history for a risk estimate.")
        plan = pd.DataFrame({"ticker": list(alloc), "weight_pct": [100 * x for x in alloc.values()]})
        st.download_button("Download allocation plan CSV", plan.to_csv(index=False),
                           file_name="ithaca_allocation_plan.csv", mime="text/csv")
        st.caption(
            "Hypothetical historical buy-and-hold illustration only. Adjusted close may "
            "differ from StockTrak fills; it is not a live competition account ledger."
        )

with about_tab:
    st.subheader(f"Ithaca Quant v{__version__} — methodology")
    st.markdown("""
1. **Inputs:** adjusted daily closing prices and volume; benchmark SPY.
2. **Features:** 5/20/60-session momentum, relative strength, trailing volatility,
   price-versus-moving-average gaps, rolling drawdown and volume ratios.
3. **Target:** stock's next 20-session total return **minus** SPY's return
   (the duration is adjustable in the sidebar).
4. **Models:** Histogram Gradient Boosting and Random Forest; forecasts are averaged.
5. **Training boundary:** a past training example enters the dataset only if its
   entire forward return window ended **before** the signal date.
6. **Validation:** a repeated walk-forward simulation retrains on matured historical labels,
   records ticker-level out-of-sample forecasts and realized outcomes for nonoverlapping windows,
   checks relative directional accuracy and forecast error against simple baselines,
   and compares a simulated portfolio against SPY and momentum.
7. **Probability checks:** boom/gain forecasts are compared to realized event frequencies,
   Brier scores and training-window prevalence baselines. Binned reliability plots illustrate
   calibration; individual stock estimates are often TOO SPARSE to validate.
8. **Portfolio:** integer-share hypothetical buy-and-hold marks with an
   uninvested cash reserve, optional allocation CSV export and historical risk.
""")
    st.warning(
        "This app does **not** incorporate fundamentals, financial statements, "
        "earnings dates, historically trained news sentiment, stock-universe survivorship correction, "
        "realistic brokerage executions, or proven live calibration of probabilities. "
        "Today’s news appears only as a separate, unvalidated headline overlay. "
        "It is a transparent research prototype—not a verified market-predicting AI."
    )
    st.markdown(f"[Review the official competition restrictions]({RULES_URL})")
    st.write("To extend this system, add point-in-time fundamental datasets and a completely untouched final test period before evaluating any new model.")
