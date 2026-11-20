"""Ithaca Quant — Streamlit dashboard for educational stock research.

Run: streamlit run app.py
No actual orders are placed; all allocations are hypothetical.
"""
import os
import hashlib
from html import escape as html_escape
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Check the package BEFORE importing feature modules. GitHub web uploads can
# update app.py without updating the inner ithaca_quant/ package; previously
# this caused an opaque ImportError before the dashboard could show guidance.
from ithaca_quant import __version__
APP_RELEASE = "3.2.0"
st.set_page_config(page_title=f"Ithaca Quant v{APP_RELEASE}", page_icon="📈", layout="wide")
# v2.3 and v2.4 contain the same forecasting, news, chart and portfolio
# modules: only release labels differ.  Do not halt the dashboard because
# of this known, verified version-label discrepancy.
if __version__ != APP_RELEASE:
    # Minor presentation-label mismatch should not turn the entire dashboard off.
    # Actual missing feature imports are checked separately below.
    st.warning(
        f"Deployment version mismatch (nonfatal): displayed app is v{APP_RELEASE}; "
        f"Python package reports v{__version__}. If features fail, upload the "
        "complete release together rather than editing version numbers."
    )

from ithaca_quant.backtest import run_walk_forward
from ithaca_quant.config import (
    BENCHMARK, COMPETITION_END, COMPETITION_START, DEFAULT_TICKERS,
    INITIAL_CAPITAL, MAX_POSITION, MAX_STOCKS, MIN_STOCKS, RULES_URL, MAX_AGENTS, MAX_RETRIES,
)
from ithaca_quant.data import demo_market_data, download_market_data, parse_tickers
from ithaca_quant.incremental import refresh_market, completed_daily_only
from ithaca_quant.market_cache import config_key, load_screen, save_screen, age_seconds
from ithaca_quant.fundamentals import fetch_company_facts, public_quarterly_snapshot, public_quarterly_history, yahoo_latest_quarterly
from ithaca_quant.news_archive import archive_headlines, recorded_headlines, import_vendor_archive
from ithaca_quant.universe_news import update_universe_news
from ithaca_quant.insider_form4 import ticker_directory, fetch_form4_ticker, summarize_insider_activity
from ithaca_quant.universe import fetch_current_universe, pick_scan_symbols, screen_candidates
from ithaca_quant.quotes import alpaca_iex_quotes, yahoo_latest_quotes, age_minutes
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.leaderboard import RANKING_MODES, rank_stocks, leaderboard_display, boom_model_quality
from ithaca_quant.leaderboard_review import add_leaderboard_review, evaluate_candidate
from ithaca_quant.metadata import add_metadata, fetch_company_metadata, load_company_metadata, market_cap_bucket
from ithaca_quant.portfolio import historical_risk, simulate_buy_hold, validate_allocations
from ithaca_quant.signals import plan_signals
from ithaca_quant.news import fetch_news, fetch_market_news, news_context
from ithaca_quant.news_intelligence import (
    analyze_news, news_adjusted_estimates, news_breakdown_lines,
    intraday_news_shift,
)
from ithaca_quant.ai_news import summarize_stock_news
from ithaca_quant.search import price_scenarios, review_dates
# Presentation and chart utilities must be deployed together with this app.py.
# Surface an actionable error instead of exposing a cryptic startup ImportError.
try:
    from ithaca_quant.presentation import format_financial_table
    from ithaca_quant.explorer import (
        CHART_PERIODS, CHART_FORECAST_SESSIONS, CHART_FORECAST_LABELS,
        validate_symbol, select_history_window, select_today_intraday, select_1d_display_window,
        forecast_segment, download_intraday, intraday_projection, chart_axis_range,
    )
except ImportError as exc:
    st.error(
        "The dashboard could not load its chart or financial-display components. "
        "This usually means that app.py and the inner ithaca_quant/ package "
        "were uploaded from different releases or a dependency is missing. "
        "Reupload the full release folder to GitHub (especially "
        "ithaca_quant/ithaca_quant/explorer.py and presentation.py), commit, "
        "and reboot the app."
    )
    st.code(str(exc), language="text")
    st.stop()
from ithaca_quant.validation import attach_quality, overall_quality, calibration_bins
from ithaca_quant.research_lab import market_regime
from ithaca_quant.portfolio_stress import stress_summary
from ithaca_quant.forecast_audit import log_forecasts, reconcile_forecasts, forward_report, forward_model_comparison_report
from ithaca_quant.weekly_reports import make_weekly_report, load_weekly_report, render_report, report_window
from ithaca_quant.ranking_accuracy import rank_outperformance
from ithaca_quant.model_zoo import model_catalog, compare_rank_models
from ithaca_quant.institutional_audit import factor_audit, next_close_proxy, historical_data_health
from ithaca_quant.remote_store import health as storage_health, remote_enabled
from ithaca_quant.macro import macro_snapshot
from ithaca_quant.news_events import headline_event_counts
from ithaca_quant.earnings_expectations import validated_expectations
from ithaca_quant.historical_archive import load_historical_archive

# Streamlit Secrets are never displayed or placed in Git. A configured SQL
# backend persists the same snapshots across hosted restarts and workers.
try:
    _sql_url = str(st.secrets.get("ITHACA_DATABASE_URL", "") or "").strip()
    if _sql_url:
        os.environ["ITHACA_DATABASE_URL"] = _sql_url
except Exception:
    pass




@st.cache_data(show_spinner="Checking point-in-time historical archive integrity…")
def cached_historical_archive(data: bytes):
    return load_historical_archive(data)


@st.cache_data(ttl=60 * 60 * 8, show_spinner="Loading historical prices…")
def cached_data(mode: str, tickers: tuple[str, ...], years: int):
    if mode == "Synthetic demo":
        return demo_market_data(list(tickers), sessions=max(750, 252 * years))
    return download_market_data(list(tickers), years=years, batch_size=75)


@st.cache_data(ttl=60 * 60 * 6, show_spinner="Checking NYSE and Nasdaq listing directories…")
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


@st.cache_data(ttl=15, show_spinner=False)
def cached_quotes(provider: str, tickers: tuple[str, ...], key: str, secret: str, nonce: int):
    del nonce  # Used to force a manual refresh of this cache.
    if provider.startswith("IEX"):
        return alpaca_iex_quotes(list(tickers), key, secret)
    return yahoo_latest_quotes(list(tickers))


@st.cache_data(show_spinner="Computing point-in-time features…")
def cached_panel(close: pd.DataFrame, volume: pd.DataFrame, horizon: int,
                 fundamentals=None, news=None, earnings=None):
    return build_panel(close, volume, horizon, fundamentals=fundamentals,
                       news=news, earnings=earnings)


@st.cache_data(show_spinner="Training models for today's ranking…")
def cached_ranking(panel: pd.DataFrame, asof: pd.Timestamp, fast: bool, boom_return: float,
                   enhanced: bool = False):
    return forecast_asof(panel, asof, fast=fast, boom_return=boom_return, enhanced=enhanced,
                         competitive_agents=True)


@st.cache_data(show_spinner="Running embargoed, walk-forward out-of-sample tests…")
def cached_backtest(panel, close, horizon, top_n, exposure, cost_bps, periods, fast, boom_return,
                    historical_membership=None, strict_pit=False, terminal_returns=None):
    return run_walk_forward(
        panel, close, horizon=horizon, top_n=top_n, exposure=exposure,
        cost_bps=cost_bps, max_periods=periods, fast=fast, boom_return=boom_return,
        historical_membership=historical_membership, require_point_in_time=strict_pit,
        terminal_returns=terminal_returns, competitive_agents=True,
    )


def pct(value: float) -> str:
    if pd.isna(value):
        return "N/A"
    return f"{value:+.2%}"


def money(value: float) -> str:
    return f"${value:,.0f}"


def probability_pct(value: float) -> str:
    return "Insufficient history" if pd.isna(value) else f"{value:.1%}"


def show_signal_card(label: str, reason: str, color: str, *, title: str):
    """Color-coded, escaped research explanation (not a trade execution)."""
    palette = {
        "DARK_GREEN": ("#14532d", "#ffffff", "#166534"),
        "GREEN": ("#dcfce7", "#14532d", "#16a34a"),
        "YELLOW": ("#fef3c7", "#713f12", "#d97706"),
        "RED": ("#fee2e2", "#7f1d1d", "#dc2626"),
    }
    bg, text, edge = palette.get(color, palette["YELLOW"])
    st.markdown(
        f'<div style="padding:14px;border:2px solid {edge};background:{bg};'
        f'color:{text};border-radius:10px;min-height:155px">'
        f'<div style="font-size:0.85rem;font-weight:600">{html_escape(title)}</div>'
        f'<div style="font-size:1.15rem;font-weight:750;margin:7px 0">'
        f'{html_escape(str(label))}</div>'
        f'<div style="font-size:0.89rem;line-height:1.45">{html_escape(str(reason))}</div>'
        '</div>', unsafe_allow_html=True)


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


st.title(f"📈 Ithaca Quant v{APP_RELEASE}")
st.caption("Research-grade workflow prototype · Educational forecasts · Virtual portfolio only")
# Report-ready notifications do not depend on running a whole-market scan.
try:
    _, _weekly_ending = report_window()
    _saved_week = load_weekly_report(_weekly_ending.date().isoformat())
    if _saved_week is not None:
        st.sidebar.success(f"🔔 Weekly prediction scorecard ready: {_saved_week['week_ending']}")
        _toast_key = 'weekly_notice_'+_saved_week['week_ending']
        if not st.session_state.get(_toast_key):
            st.toast("🔔 Your Friday forecast accuracy report is ready in Accuracy Lab.")
            st.session_state[_toast_key] = True
except Exception:
    # Notifications should never prevent the forecast dashboard from opening.
    pass
# This form appears before the marketwide engine, so ticker searches never need
# an NYSE/Nasdaq scan or hundreds of model downloads.
with st.form("top_ticker_search", clear_on_submit=False):
    search_left, search_right = st.columns([5, 1])
    with search_left:
        quick_input = st.text_input(
            "Search any stock — instant individual research",
            value=st.session_state.get("quick_last_input", "NVDA"),
            placeholder="NVDA, AAPL, RKLB…",
            help="Search by ticker, not exchange name. Only this ticker and SPY are modeled.",
        )
    with search_right:
        st.write("")
        st.write("")
        quick_submit = st.form_submit_button("🔍 Search stock", use_container_width=True, type="primary")
if quick_submit:
    st.session_state["quick_last_input"] = quick_input
    st.session_state["quick_requested"] = quick_input
    st.session_state["workspace_mode"] = "⚡ Instant stock explorer"

workspace = st.radio(
    "Workspace", ["⚡ Instant stock explorer", "💼 My portfolio", "🌐 Full-market dashboard"],
    horizontal=True, key="workspace_mode",
    help="The private portfolio tracks your actual fills and held companies without scanning the market. Instant explorer analyzes one symbol. Full-market dashboard scans NYSE/Nasdaq.",
)

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
    enhanced_model = st.checkbox("Validate alternative forecasting models for individual-stock research",
                                  value=True,
                                  help="Ridge, ExtraTrees and optional LightGBM/XGBoost/CatBoost; "
                                       "candidates must beat the existing model on a purged chronological holdout. "
                                       "Slower than the default marketwide scan.")
    keep_forecast_ledger = st.checkbox("Log forecasts for real forward testing", value=True,
                                      help="Save an immutable prediction by ticker, trading date and horizon. "
                                           "A durable SQL database is recommended for hosted deployments.")
    st.caption("Accuracy-first: SEC quarterly factors are trained only where historical filing coverage exists "
               "and a chronological training holdout improves over the price-only model. "
               "News-sensitivity scenarios are NOT substituted for verified model estimates.")
    st.markdown(f"[Official competition rules]({RULES_URL})")

@st.cache_data(ttl=5 * 60, show_spinner="Loading historical data for this ticker and SPY only…")
def cached_single_symbol(symbol: str, source: str, years_for_chart: int):
    if source == "Synthetic demo":
        return demo_market_data([symbol], sessions=252 * years_for_chart)
    return completed_daily_only(download_market_data([symbol], years=years_for_chart,
                                min_history=30, batch_size=3))


@st.cache_data(ttl=90, show_spinner=False)
def cached_intraday_symbol(symbol: str, period: str) -> pd.Series:
    return download_intraday(symbol, period)


@st.cache_data(ttl=2 * 60, show_spinner="Checking current attributed headlines for this stock…")
def cached_quick_news(symbol: str, company: str):
    # Broad source-attributed headlines, consistent with the leaderboard.
    # The feed is event-deduplicated downstream by analyze_news and review logic.
    return fetch_market_news(symbol, company, lookback_days=45, limit=40)


@st.cache_data(ttl=15 * 60, show_spinner="Generating sourced AI news commentary…")
def cached_ai_news_summary(symbol: str, report: dict, model: str, _server_api_key: str):
    return summarize_stock_news(symbol, report, api_key=_server_api_key, model=model)


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Loading dated SEC quarterly reports…")
def cached_sec_quarters(symbol: str, contact: str):
    facts, company = fetch_company_facts(symbol, contact)
    return public_quarterly_snapshot(facts), company, public_quarterly_history(facts)


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Checking latest quarterly income-statement summaries…")
def cached_yahoo_quarters(symbol: str):
    return yahoo_latest_quarterly(symbol)


def server_sec_contact() -> str:
    try:
        return str(st.secrets.get("SEC_CONTACT_EMAIL", "") or os.environ.get("SEC_CONTACT_EMAIL", "")).strip()
    except Exception:
        return str(os.environ.get("SEC_CONTACT_EMAIL", "")).strip()


def server_openai_key() -> str:
    """Read a server-side credential only; NEVER require it from public visitors."""
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except (FileNotFoundError, KeyError, AttributeError):
        return ""


def draw_price_and_forecast(history: pd.Series, forecast_target: float | None,
                            period: str, forecast_horizon: int | None,
                            *, intraday_end: pd.Timestamp | None = None):
    """Observed points only, plus ONE explicitly illustrative forecast endpoint.

    1D bounds are strictly within the New York date, with time-of-day ticks.
    5D has five observed trading sessions and optionally the next session.
    """
    fig = go.Figure()
    if history.empty:
        return fig
    intraday = period in ("1D", "5D")
    observed_hover = ("%{x|%a %b %d, %I:%M %p} ET<br>$%{y:,.2f}"
                      if intraday else "%{x|%b %d, %Y}<br>$%{y:,.2f}")
    fig.add_trace(go.Scatter(
        x=history.index, y=history.values, mode="lines+markers" if len(history) == 1 else "lines",
        name="Observed prices", line=dict(width=2),
        hovertemplate=observed_hover + "<extra>Observed</extra>",
    ))
    future_end = None
    if forecast_target is not None and forecast_target > 0:
        if period == "1D":
            if intraday_end is not None:
                future_end = pd.Timestamp(intraday_end)
                xs = [history.index[-1], future_end]
                ys = [float(history.iloc[-1]), float(forecast_target)]
            else:
                xs = ys = None
        elif forecast_horizon is not None:
            xs, ys = forecast_segment(history.index[-1], float(history.iloc[-1]),
                                      float(forecast_target), forecast_horizon)
            future_end = xs[-1]
        else:
            xs = ys = None
        if xs is not None:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines+markers", name="Illustrative forecast endpoint",
                line=dict(dash="dot", width=3, color="#f59e0b"),
                marker=dict(size=[4, 8]),
                hovertemplate=("%{x|%a %b %d, %I:%M %p} ET" if intraday else "%{x|%b %d, %Y}")
                              + "<br>$%{y:,.2f}<extra>Illustrative, not observed</extra>",
            ))
    tickformat = {"1D": "%I:%M %p", "5D": "%a %b %d\n%I:%M %p"}.get(period, "%b %d\n%Y")
    fig.update_xaxes(tickformat=tickformat, range=chart_axis_range(history, period, future_end),
                     autorange=False,
                     title_text="Time (US Eastern)" if intraday else "Date")
    if period == "1D":
        # Always show exactly 8:30 AM–4:00 PM Eastern, even with delayed bars.
        # Using a concrete date string for Plotly avoids full-day autoranging.
        first_day = pd.Timestamp(history.index[0]).normalize()
        first_tick = first_day + pd.Timedelta(hours=8, minutes=30)
        start = first_tick.isoformat(sep=" ")
        end = (first_day + pd.Timedelta(hours=16)).isoformat(sep=" ")
        fig.update_xaxes(range=[start, end], tick0=start, dtick=60 * 60 * 1000,
                         autorange=False, tickformat="%I:%M %p")
    fig.update_layout(height=470, hovermode="x unified", margin=dict(l=0, r=0, t=14, b=0),
                      yaxis_title="Price ($)", legend=dict(orientation="h", y=1.15))
    return fig



if workspace.startswith("💼"):
    from ithaca_quant.portfolio_workspace import render_portfolio
    render_portfolio(mode=mode, cached_quotes=cached_quotes,
                     cached_single_symbol=cached_single_symbol,
                     cached_panel=cached_panel, cached_ranking=cached_ranking,
                     cached_quick_news=cached_quick_news,
                     cached_sec_quarters=cached_sec_quarters,
                     sec_contact=server_sec_contact())
    st.stop()


if workspace.startswith("⚡") or quick_submit:
    st.subheader("⚡ Individual stock explorer")
    st.caption("Independent research path: downloads ONE ticker and SPY, without scanning or training on the full-market universe. "
               "Daily model forecasts are cached; intraday prices may be delayed and are cached for 90 seconds.")
    requested = st.session_state.get("quick_requested")
    if not requested:
        st.info("Enter a ticker in the search bar above and press **Search stock** to see its charts and forecast.")
        st.stop()
    try:
        selected = validate_symbol(requested)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    periods = st.radio("Historical chart range", CHART_PERIODS, index=2, horizontal=True,
                       key="quick_period", help="1D and 5D use intraday provider data when available.")
    historical_expectations = st.file_uploader(
        "Optional timestamped historical earnings-expectations CSV (licensed data only)",
        type=['csv'], key='earnings_vendor_file',
        help="Required: ticker, expectation_timestamp, release_timestamp, "
             "expected_eps, reported_eps, source. Estimate must predate the result.")
    earnings_table = None
    if historical_expectations is not None:
        try:
            earnings_table = validated_expectations(pd.read_csv(historical_expectations))
            st.caption(f"Verified chronology for {len(earnings_table):,} vendor-provided earnings rows; "
                       "the application cannot independently authenticate vendor provenance.")
        except Exception as exc:
            st.error(f"Earnings data rejected: {exc}")
    if mode == "Synthetic demo":
        st.error("SYNTHETIC DEMO: All prices and model outputs on this page are fictional.")
    try:
        # Always request five years for the 5Y range, regardless of full-dashboard settings.
        quick = cached_single_symbol(selected, mode, max(5, years))
        if selected not in quick.close or quick.close[selected].dropna().empty:
            st.warning(f"No usable historical data was retrieved for {selected}. It may be an unsupported ticker, a recent IPO, or the provider may be rate limiting.")
            st.stop()
        daily_history = quick.close[selected].dropna()
        daily_asof = pd.Timestamp(daily_history.index[-1])
        metadata = load_company_metadata([selected])
        raw_company = metadata.iloc[0].get("company_name") if not metadata.empty else None
        company_name = str(raw_company).strip() if pd.notna(raw_company) and str(raw_company).strip() else selected
        # Live attributed headlines are fetched independently of the marketwide
        # scanner and cached for 15 minutes. Their sentiment is NOT ML-trained.
        news_rows, news_errors = [], []
        if mode != "Synthetic demo":
            try:
                news_rows, news_errors = cached_quick_news(selected, company_name)
            except Exception as news_exc:
                news_errors = [f"News unavailable: {type(news_exc).__name__}"]
        news_report = analyze_news(news_rows, selected, company_name)
        if news_report["headlines"]:
            try:
                archive_headlines(selected, news_report)
            except Exception:
                pass  # Cannot store headlines on this host; do not invent training history.
        try:
            archive_rows = recorded_headlines(selected) if mode != "Synthetic demo" else None
        except Exception:
            archive_rows = None
        sec_snapshot = None
        sec_history = None
        sec_error = ""
        if mode != "Synthetic demo":
            contact = server_sec_contact()
            if contact:
                try:
                    sec_snapshot, sec_company, sec_history = cached_sec_quarters(selected, contact)
                except Exception as e:
                    sec_error = f"SEC data unavailable: {type(e).__name__}. The price-only model remains usable."
            else:
                sec_error = "SEC filing analysis is optional. Configure SEC_CONTACT_EMAIL in server Secrets to enable official SEC companyfacts."
        chart_prices = select_history_window(daily_history, periods)
        intraday_note = ""
        if periods in ("1D", "5D"):
            if mode == "Synthetic demo":
                # No fictitious intraday bars are manufactured from daily prices.
                chart_prices = (pd.Series(dtype=float) if periods == "1D"
                                else select_history_window(daily_history, "5D"))
                intraday_note = "Synthetic demo has daily data only, not a real 1D intraday series."
            else:
                try:
                    intraday = cached_intraday_symbol(selected, periods)
                    if intraday.empty:
                        raise ValueError("Provider returned no intraday observations")
                    chart_prices = (select_1d_display_window(intraday) if periods == "1D"
                                    else select_history_window(intraday, "5D"))
                    intraday_note = ("5-minute intraday bars, timestamped US Eastern."
                                     if periods == "1D" else "30-minute intraday bars, timestamped US Eastern.")
                    if periods == "1D" and chart_prices.empty:
                        intraday_note = "No intraday observations for TODAY (US Eastern). Yesterday's prices are intentionally not displayed."
                except Exception as exc:
                    chart_prices = (pd.Series(dtype=float) if periods == "1D"
                                    else select_history_window(daily_history, "5D"))
                    intraday_note = ("Today's intraday data unavailable; no 1D chart is shown."
                                     if periods == "1D" else "Intraday data unavailable: displaying only the last five DAILY closes.")
        if periods == "5D" and not chart_prices.empty:
            unique_days = pd.DatetimeIndex(chart_prices.index).normalize().nunique()
            intraday_note += f" Showing {unique_days} observed trading sessions (up to five)."

        # Match the chart's dotted endpoint to its chosen period. 1D remains an
        # explicitly distinct short-term heuristic, not a daily model forecast.
        chart_horizon = CHART_FORECAST_SESSIONS[periods]
        # The 1D chart's hourly projection is only available during an active
        # session; a SEPARATE trained next-session daily forecast remains
        # available after hours. Never draw it on today's 1D chart.
        daily_model_horizon = chart_horizon if chart_horizon is not None else 1
        model_row, model_signal, scenario, forecast_error, news_estimates = None, None, None, None, None
        try:
            single_panel = cached_panel(
                quick.close, quick.volume, daily_model_horizon,
                {selected: sec_history} if sec_history is not None and not sec_history.empty else None,
                {selected: archive_rows} if archive_rows is not None and not archive_rows.empty else None,
                {selected: earnings_table} if earnings_table is not None and not earnings_table.empty else None)
            if single_panel.empty:
                raise ValueError("fewer than 60 valid feature-history sessions")
            point = single_panel["date"].max()
            single_rank = cached_ranking(single_panel, point, fast_mode, boom_return,
                                         enhanced=enhanced_model)
            if keep_forecast_ledger and mode != "Synthetic demo":
                try:
                    log_forecasts(single_rank, point, daily_model_horizon, limit=2)
                except Exception as ledger_exc:
                    st.warning(f"Forward forecast log unavailable: {type(ledger_exc).__name__}")
            match = single_rank.loc[single_rank["ticker"].eq(selected)]
            if match.empty:
                raise ValueError("model produced no forecast for this ticker")
            model_row = match.iloc[0]
            model_signal = plan_signals(single_rank, horizon=daily_model_horizon,
                                        risk_budget_pct=risk_budget_pct).iloc[0]
            # Regression target is EXCESS return versus SPY. 0% future SPY
            # return is assumed here purely to depict a price illustration.
            scenario = price_scenarios(float(model_row["close"]),
                                       float(model_row["forecast_excess"]),
                                       quick.close[BENCHMARK], float(model_row["vol_20"]),
                                       daily_model_horizon)
            news_estimates = news_adjusted_estimates(
                float(model_row["forecast_excess"]),
                float(model_row["prob_boom"]) if pd.notna(model_row["prob_boom"]) else None,
                float(model_row["vol_20"]), daily_model_horizon, news_report)
        except Exception as exc:
            forecast_error = f"{type(exc).__name__}: {exc}"

        plotted_target, intraday_end = None, None
        model_type = "Daily AI relative forecast; price chart is a conditional SPY scenario"
        if periods == "1D":
            model_type = "Intraday momentum heuristic (NOT the daily ML model)"
            if not chart_prices.empty and mode != "Synthetic demo":
                now_projection = intraday_projection(chart_prices)
                if now_projection is not None:
                    # Accuracy-first: unvalidated sentiment words do not move the
                    # primary projection. News sensitivities remain separate.
                    plotted_target = now_projection.target
                    intraday_end = now_projection.end_time
        elif not chart_prices.empty and model_row is not None:
            # Primary forecast is the trained model's output; the unvalidated
            # news sensitivity is available separately for comparison.
            plotted_target = float(chart_prices.iloc[-1]) * (1 + float(model_row["forecast_excess"]) + float(scenario["benchmark_scenario_return"]))

        # Search results get the SAME entry/exit, news and 52-week logic as
        # the full-market leaderboard. Do not infer a buy from news adjectives.
        quick_review = None
        st.subheader("🚦 Entry and exit research signals")
        if model_row is not None and model_signal is not None:
            quick_review = evaluate_candidate(
                {**model_row.to_dict(), "ticker": selected, "research_score": None},
                model_signal.to_dict(), quick.close, asof=pd.Timestamp(point).date(),
                horizon=daily_model_horizon,
                articles=(news_rows if not news_errors and mode != "Synthetic demo" else None),
                company=company_name)
            left_light, right_light = st.columns(2)
            with left_light:
                show_signal_card(quick_review["signal_label"], quick_review["reason"],
                                 quick_review["color"], title="ENTRY · Research opportunity")
            with right_light:
                show_signal_card(quick_review["exit_label"], quick_review["exit_reason"],
                                 quick_review["exit_color"], title="EXIT · Position risk review")
            if quick_review.get("position_52w") is not None:
                st.caption(f"52-week adjusted range: ${quick_review['low_52w']:,.2f}–"
                           f"${quick_review['high_52w']:,.2f} · current position "
                           f"{quick_review['position_52w']:.0%} of that range. "
                           f"{quick_review['week_52_status']}.")
            else:
                st.caption("52-week context unavailable: fewer than 200 complete daily observations.")
            st.caption(f"Forecast horizon: {daily_model_horizon} trading session(s). "
                       "News can downgrade an entry screen or add risk context; "
                       "unvalidated headlines never automatically increase the core ML forecast. "
                       "The EARLY ENTRY WATCH screen applies only to 20-session forecasts and "
                       "does not predict an exact breakout date.")
        else:
            st.warning("🟡 ENTRY / EXIT DATA NEEDED: A valid daily model forecast and "
                       "price history are required. No entry or exit color can be established.")

        st.markdown(f"**History:** {periods} · **Dotted extension:** {CHART_FORECAST_LABELS[periods]}")
        if periods == "1D":
            st.caption("1D chart: fixed 8:30 AM–4:00 PM **Eastern**, showing only actual prices observed in that window. The forecast line is available only during an active regular session; a next-session ML outlook remains below after hours.")
        if chart_prices.empty:
            st.info("No intraday stock prices for today (US Eastern). The 1D chart is intentionally empty instead of showing another day. Try 5D or check when the market opens.")
        else:
            st.plotly_chart(draw_price_and_forecast(
                chart_prices, plotted_target, periods, chart_horizon,
                intraday_end=intraday_end),
                use_container_width=True, key="quick_explorer_price_chart")
            if periods == "1D" and plotted_target is None:
                st.info("The 1D **next-hours** projection is only available during regular market hours when recent bars are fresh. It is correctly disabled after 4:00 PM Eastern, before the open, and for stale data. **The separate next-session ML forecast is shown below** when training succeeds.")
        if intraday_note:
            st.caption(intraday_note)
        st.caption(f"**Solid line:** actual observed provider prices · **Dotted line:** a single hypothetical future endpoint, not a real hourly/daily path. "
                   f"**Method:** {model_type}. "
                   f"Short-window prices may be delayed. Daily-model inputs end {daily_asof.date()}. "
                   "Forecast business-day dates are approximate and may land on market holidays.")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Last price in this chart", f"${float(chart_prices.iloc[-1]):,.2f}" if not chart_prices.empty else "Unavailable")
        m2.metric("Next-hours 1D endpoint" if periods == "1D" else "Daily ML price endpoint",
                  f"${plotted_target:,.2f}" if plotted_target is not None else
                  "Market closed / no fresh bars" if periods == "1D" else "Unavailable")
        if periods == "1D":
            m3.metric("ML P(gain next session)**",
                      probability_pct(model_row["prob_gain"]) if model_row is not None else "Unavailable")
        else:
            m3.metric(f"Daily-model P(+{boom_return:.0%} in {daily_model_horizon} sessions)**",
                      probability_pct(model_row["prob_boom"]) if model_row is not None else "Unavailable")
        m4.metric("Annual historical volatility (daily)",
                  f"{float(model_row['vol_20']):.1%}" if model_row is not None else "Unavailable")
        if periods == "1D":
            st.markdown("**Next trading-session machine-learning outlook** (separate from today's hourly chart)")
            nx1, nx2, nx3 = st.columns(3)
            if model_row is not None and scenario is not None:
                nx1.metric("ML return versus SPY", f"{float(model_row['forecast_excess']):+.2%}")
                nx2.metric("Next-session hypothetical price", f"${float(scenario['target']):,.2f}")
                nx3.metric("Daily model as-of", str(pd.Timestamp(model_row['date']).date()))
                st.caption("A **one-trading-session SPY-relative forecast** plus a historical benchmark return scenario, not a calibrated absolute price forecast. It is not an hourly projection. The next trading session may be a holiday-delayed date.")
            else:
                nx1.metric("Next-session return", "Unavailable")
                nx2.metric("Next-session price", "Unavailable")
                nx3.metric("Daily model", "Needs valid data")
        if model_row is not None:
            st.markdown("**Forecast validation and evidence**")
            st.write(f"**Selected forecaster:** {model_row.get('selected_model', 'Existing ensemble')}. "
                     f"**Information sources:** {model_row.get('feature_selection', 'price data')}")
            n_calibration = int(model_row.get('lab_calibration_n', 0) or 0)
            if n_calibration >= 50 and pd.notna(model_row.get('lab_interval_low')):
                st.write(f"**Empirical 80% SPY-relative return interval:** "
                         f"{float(model_row['lab_interval_low']):+.2%} to "
                         f"{float(model_row['lab_interval_high']):+.2%} · "
                         f"**separate calibration outcomes:** {n_calibration:,}")
                st.caption(f"Calibration MAE {float(model_row['lab_mae']):.2%} vs. "
                           f"predict-zero MAE {float(model_row['lab_zero_mae']):.2%}. "
                           "This is an empirical interval, not guaranteed confidence in changing markets.")
            else:
                st.caption("No defensible return interval: too few separate, mature, embargoed calibration outcomes.")
            if model_row.get('lab_explanation'):
                st.caption("**Model sensitivity (not causal impact):** " + str(model_row['lab_explanation']))
            st.caption(str(model_row.get('lab_diagnostic', '')))
            reg = market_regime(quick.close[BENCHMARK], asof=point)
            if pd.notna(reg['momentum_20']):
                st.caption(f"**Observed market regime:** {reg['name']} · SPY last 20 sessions "
                           f"{reg['momentum_20']:+.1%} · historical volatility "
                           f"{reg['volatility_20']:.1%}. Regime is descriptive, not a proven "
                           "forecasting advantage.")
            tagged = headline_event_counts(pd.DataFrame(news_report.get('headlines', [])))
            if sum(tagged.values()):
                st.caption("**Headline-event categories:** " + ", ".join(
                    f"{key} {count}" for key,count in tagged.items() if count))
        if forecast_error:
            st.warning("Daily-model forecast unavailable: " + forecast_error + ". Check SPY and ticker daily history, provider throttling, or select a longer-listed stock. "
                       "An intraday chart can still work without an ML forecast. No predicted values have been invented.")
            if st.button("↻ Retry daily data and ML forecast", key="quick_retry_forecast_v141"):
                # Explicit user-triggered recovery for stale data/provider errors,
                # not unbounded automatic Yahoo retries.
                cached_single_symbol.clear()
                cached_panel.clear()
                cached_ranking.clear()
                st.rerun()
        if scenario is not None:
            checks = review_dates(pd.Timestamp(model_row["date"]), daily_model_horizon,
                                  str(model_signal["entry_watch"]), str(model_signal["exit_review"]))
            b1, b2, b3, b4 = st.columns(4)
            b1.metric(f"{daily_model_horizon}-session risk scale (1σ)", f"±{scenario['risk_1sigma_pct']:.1f}%")
            b2.metric("Hypothetical allocation cap", f"{float(model_signal['max_starter_weight_pct']):.1f}%")
            b3.metric("Entry watch", str(model_signal["entry_watch"]))
            b4.metric("Exit review", str(model_signal["exit_review"]))
            st.write(f"**Next entry review:** {checks['entry_review']} · **Exit review:** {checks['exit_review']} "
                     "(business-day approximations, NOT predicted optimal trade dates).")
            st.caption(f"*Daily-model price illustration uses an **explicit historical SPY-return scenario** "
                       f"for the next {daily_model_horizon} sessions, not a direct absolute-price forecast. The intraday dotted line, where shown, "
                       "does NOT use this daily model. Boom probabilities are unverified without independent "
                       "calibration; annual volatility is not a maximum-loss estimate. Single-stock models "
                       "may differ from full-market rankings.")
        st.divider()
        st.subheader("🧠 Financial filing and news evidence")
        if quick_review is not None:
            st.markdown("**52-week history combined with current company-news events**")
            st.info(quick_review["news_52w_context"])
            st.caption("The model also tests 52-week range and five-day trend-inflection features "
                       "using chronological validation before selecting them for its daily price forecast. "
                       "The live-news/52-week explanation is a research screen, not an independently "
                       "trained headline-driven return forecast.")
        if sec_snapshot is not None and not sec_snapshot.empty:
            st.markdown("**Official SEC quarterly reports (filed-date-aware):**")
            sec_cols = ["period_end", "filed", "revenue_usd", "net_income_usd",
                        "revenue_yoy", "net_margin", "diluted_eps", "eps_yoy", "revenue_growth_accel"]
            rows = sec_snapshot.tail(5)[[c for c in sec_cols if c in sec_snapshot]].copy()
            st.dataframe(format_financial_table(rows), hide_index=True, use_container_width=True)
            st.caption("Filing dates, not quarter-end dates, determine when a figure becomes usable. "
                       "The model tests SEC factors against a price-only version on a chronological "
                       "training holdout and keeps them only if the tested error improves. "
                       "SEC facts may omit reports or use issuer-specific tags; missing values are never invented.")
            if model_row is not None:
                st.write("**Factor selection:** " + str(model_row.get("feature_selection", "Price-only baseline")))
                st.caption(f"Uses SEC filing features: {bool(model_row.get('uses_sec_filings', False))}; "
                           f"uses previously archived, timestamped news features: "
                           f"{bool(model_row.get('uses_news_history', False))}.")
                base_mae = model_row.get("filing_tech_holdout_mae")
                filing_mae = model_row.get("filing_model_holdout_mae")
                if pd.notna(base_mae) and pd.notna(filing_mae):
                    st.caption(f"Model-selection holdout MAE: price-only {base_mae:.4f}; "
                               f"selected evidence model {filing_mae:.4f}. This holdout was used to select the "
                               "model; it is not an untouched independent test set.")
        elif sec_error:
            st.caption(sec_error)
        if sec_snapshot is None and mode != "Synthetic demo":
            try:
                yahoo_facts = cached_yahoo_quarters(selected)
                if not yahoo_facts.empty:
                    st.write("**Latest reported quarterly figures (Yahoo Finance):**")
                    st.dataframe(format_financial_table(yahoo_facts.head(5)), hide_index=True, use_container_width=True)
                    st.caption("These Yahoo figures lack verified original filing timestamps, "
                               "so they are shown as current context ONLY and are never fed "
                               "into historical model training. Enable SEC filings for "
                               "point-in-time trainable fundamentals.")
            except Exception:
                st.caption("Quarterly Yahoo income statements are not available for this stock.")
        if archive_rows is not None:
            st.caption(f"News evidence archive: {len(archive_rows)} distinct observed headlines. "
                       "Only articles previously seen by this app may become ML inputs, and only after "
                       "chronological validation; newest articles are context, not proven return signals. "
                       "Local archives can be lost on hosted app restarts.")
            if sec_snapshot is None and model_row is not None:
                st.write("**Factor selection:** " + str(model_row.get("feature_selection", "Price-only baseline")))
        st.caption("Broad source-attributed news is retrieved automatically for the searched stock "
                   "(cached 2 minutes, looking back up to 45 calendar days). "
                   "Headline-word sentiment is shown as a separate bounded sensitivity scenario. "
                   "**Today's new headlines do not change the primary model forecast immediately.** "
                   "Previously archived, timestamped headline factors can enter the trained daily model only "
                   "if the chronological training comparison improves; independent backtesting is still needed.")
        for line in news_breakdown_lines(news_report, news_estimates, selected):
            st.markdown(line)
        if news_estimates is not None and not chart_prices.empty:
            base_endpoint = float(chart_prices.iloc[-1]) * (1 + news_estimates["base_excess"])
            news_endpoint = float(chart_prices.iloc[-1]) * (1 + news_estimates["scenario_excess"])
            st.dataframe(pd.DataFrame([
                {"Measure": "Price endpoint (daily-model illustration)",
                 "Price-data model": f"${base_endpoint:,.2f}",
                 "News scenario": f"${news_endpoint:,.2f}",
                 "Caution": "Conditional SPY scenario only; not an absolute-price forecast"},
                {"Measure": f"Large-gain event (+{boom_return:.0%})",
                 "Price-data model": probability_pct(news_estimates["base_boom"]),
                 "News scenario": probability_pct(news_estimates["scenario_boom"]),
                 "Caution": "Uncalibrated probability sensitivity, not a measured chance"},
                {"Measure": f"{daily_model_horizon}-session risk scale (1σ)",
                 "Price-data model": f"±{news_estimates['historical_sigma']:.1%}",
                 "News scenario": f"±{news_estimates['illustrative_stress_sigma']:.1%}",
                 "Caution": "Volatility-based scenarios, not worst-case risk"},
            ]), hide_index=True, use_container_width=True)
            if periods == "1D":
                st.caption(f"The 1D dotted line uses a separate intraday heuristic WITHOUT "
                       f"the unvalidated today's-headline adjustment of {intraday_news_shift(news_report):+.2%}. "
                       "The daily-model table above is NOT an hourly prediction.")
        else:
            st.info("A quantified news sensitivity scenario requires a valid daily ML forecast. "
                    "Headlines can still be read below.")
        if news_errors:
            st.warning("Some news feeds failed (no information has been invented): " + "; ".join(news_errors))
        if news_report["headlines"]:
            st.caption(f"Recent eligible headlines: {news_report['n']} from "
                       f"{news_report['source_count']} publisher(s). "
                       "Each row shows exact wording and attribution; headlines may omit important context.")
            for i, item in enumerate(news_report["headlines"][:12], 1):
                st.markdown(f"**[{i}] {item['publisher']}** · {item['published_utc'].strftime('%b %d, %Y %I:%M %p UTC')} "
                            f"· {item['impact']} · Relevance: {item['relevance']}")
                st.write(item["title"])
                st.link_button(f"Read source [{i}]", item["url"])
        else:
            st.info("No eligible recent attributed articles. The news adjustment is ZERO, not positive or negative.")
        if mode != "Synthetic demo":
            key = server_openai_key()
            if key and news_report["headlines"]:
                ai_model = os.getenv("OPENAI_NEWS_MODEL", "gpt-4.1-mini")
                st.caption("An API-backed explanation is available; it can incur costs to the app owner. "
                           "It summarizes headlines only and does NOT determine numerical predictions.")
                if st.button("✨ Generate optional AI news explanation", key="generate_ai_news_v13"):
                    try:
                        st.session_state["last_ai_news_note"] = cached_ai_news_summary(
                            selected, news_report, ai_model, key)
                        st.session_state["last_ai_news_symbol"] = selected
                    except Exception as ai_exc:
                        st.warning(f"Optional AI commentary unavailable: {type(ai_exc).__name__}. "
                                   "The transparent breakdown above still works.")
                if st.session_state.get("last_ai_news_symbol") == selected and st.session_state.get("last_ai_news_note"):
                    with st.expander("✨ Language-model interpretation of the sources", expanded=True):
                        st.write(st.session_state["last_ai_news_note"])
                        st.caption("The generative model has read *headlines*, not full publisher articles. "
                                   "Verify facts in the linked sources. Numerical news scenarios are deterministic.")
            else:
                st.caption("Optional generative AI is off. The server administrator can "
                           "add OPENAI_API_KEY through Streamlit Secrets to enable sourced "
                           "headline explanations. The free rule-based news analysis above works without a key.")
        if mode != "Synthetic demo":
            if metadata.empty:
                st.caption("Company industry / market cap not cached yet.")
            if st.button("Load or refresh company details", key="quick_metadata"):
                metadata, status = fetch_company_metadata([selected], max_new=1)
                if status["not_loaded"]:
                    st.warning("Company profile unavailable from Yahoo Finance right now.")
                else:
                    st.rerun()
            if not metadata.empty:
                rec = metadata.iloc[0]
                cap = pd.to_numeric(rec.get("market_cap"), errors="coerce")
                st.write(f"**{company_name}** · {rec.get('sector') or 'Unknown sector'} · "
                         f"{rec.get('industry') or 'Unknown industry'} · "
                         f"Market cap: {'$'+format(cap/1e9,',.2f')+'B' if pd.notna(cap) else 'Unavailable'}")
            st.caption("Company profile fields may be missing or delayed, independent of current-news coverage.")
    except Exception as exc:
        st.error(f"Could not load {selected}: {type(exc).__name__}: {exc}")
    # Active-session news refresh; sleeping/closed browser sessions do no work.
    auto_quick = st.checkbox("Auto-check news and individual research every 2 minutes (while this page is open)",
                             value=False, key="auto_quick_v14")
    @st.fragment(run_every="2m" if auto_quick else None)
    def quick_research_pulse():
        key = "quick_pulse_at_v14"
        now_utc = datetime.now(timezone.utc)
        last = st.session_state.get(key)
        if last is not None and (now_utc - last).total_seconds() >= 115:
            st.session_state[key] = now_utc
            st.rerun()
        elif last is None:
            st.session_state[key] = now_utc
        st.caption("News refresh interval: 2 minutes while the browser session is active. "
                   "Provider requests may be delayed or rate limited.")
    quick_research_pulse()
    # This explorer skips all-market scanning and hundreds of model downloads.
    st.stop()

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
        disk_screen_key = config_key("universe_screen", scan_symbols, shortlist=shortlist_count)
        stored_screen = load_screen(disk_screen_key)
        existing = (stored_screen[0] if stored_screen else
                    st.session_state.get("market_scan_data") if st.session_state.get("market_scan_key") == scan_key else None)
        auto_universe = st.checkbox(
            "Auto-refresh saved NYSE/Nasdaq universe every 20 minutes while this page is open",
            value=True, key="auto_market_universe_v14",
            help="Loads recent adjusted daily bars, not all years. May be throttled by Yahoo; "
                 "does not run with the browser closed or when hosted app sleeps.")
        now_auto = datetime.now(timezone.utc)
        last_fail = st.session_state.get("market_refresh_failed_v14")
        auto_due = (auto_universe and stored_screen is not None and
                    age_seconds(stored_screen[1]) >= 20 * 60 and
                    (last_fail is None or (now_auto - last_fail).total_seconds() >= 20 * 60))
        col_scan, col_refresh = st.columns(2)
        with col_scan:
            run_full_scan = st.button("🔍 Full NYSE + Nasdaq scan", type="primary", key="market_full_scan")
        with col_refresh:
            run_delta_scan = st.button("↻ Refresh saved universe (recent bars only)",
                                       disabled=existing is None, key="market_delta_scan")
        if stored_screen:
            age = age_seconds(stored_screen[1])
            st.caption(f"Saved screen available · last refreshed {stored_screen[1].strftime('%b %d %H:%M UTC')} "
                       f"({age / 60:.0f} minutes ago). Shared on this app instance; "
                       "local storage may not survive Streamlit Cloud restarts.")
        if run_full_scan or run_delta_scan or auto_due:
            progress_ui = st.progress(0, text="Retrieving adjusted daily price batches…")
            def progress(done, total, loaded):
                progress_ui.progress(done / total, text=f"Batch {done}/{total}: {loaded:,} symbols loaded")
            if run_full_scan:
                # Full scan explicitly discards any same-key cached price history.
                # Force a fresh complete download, not merely a delta refresh.
                from ithaca_quant.market_cache import save_market
                from ithaca_quant.data import download_market_data
                sample = completed_daily_only(download_market_data(
                    scan_symbols, years=1, min_history=140, batch_size=75, on_progress=progress))
                save_market(config_key("adjusted_daily", scan_symbols, kind="screen", years=1,
                                       min_history=140), sample)
                status = "full"
            else:
                sample, status, last_time, warnings = refresh_market(
                    scan_symbols, years=1, kind="screen", min_history=140,
                    min_interval=20 * 60, force=True, on_progress=progress)
                for warning in warnings:
                    st.warning(warning)
            progress_ui.empty()
            if status == "stale":
                st.session_state["market_refresh_failed_v14"] = datetime.now(timezone.utc)
                st.error("The refresh failed; the original scan was preserved. Rankings were not silently rebuilt from stale data.")
            else:
                all_screened = screen_candidates(sample.close, sample.volume, limit=None)
                screening = screen_candidates(sample.close, sample.volume, limit=shortlist_count)
                downloaded_count = len(sample.close.columns) - 1
                excluded_count = len(sample.excluded)
                save_screen(disk_screen_key, screening, all_screened, downloaded_count, excluded_count)
                st.session_state.pop("market_refresh_failed_v14", None)
                st.session_state["market_scan_key"] = scan_key
                st.session_state["market_scan_data"] = (screening, all_screened, downloaded_count, excluded_count)
                st.rerun()
        if existing is None:
            st.info(f"Exchange directory found {len(full_listings):,} eligible listings. "
                    f"Select Full NYSE + Nasdaq scan to analyze {len(scan_symbols):,} symbols once. "
                    "Later sessions can resume saved results, without downloading full histories.")
            st.stop()
        scan_table, full_screen_table, downloaded_count, excluded_count = existing
        if len(scan_table) < 5:
            st.error("Fewer than five eligible stocks were saved. Try a smaller scan or refresh.")
            st.stop()
        tickers = scan_table["ticker"].tolist()
        if stored_screen and age_seconds(stored_screen[1]) > 20 * 60:
            st.warning("The saved full-market screener is older than 20 minutes. "
                       "Use Refresh saved universe to update it incrementally. "
                       "The application will not pretend this is a live scan.")
        scan_summary = (len(full_listings), len(scan_symbols), downloaded_count, len(full_screen_table), len(scan_table), excluded_count)
        @st.fragment(run_every="20m" if auto_universe else None)
        def universe_refresh_pulse():
            key = "market_pulse_v14"
            now_utc = datetime.now(timezone.utc)
            previous = st.session_state.get(key)
            if previous is not None and (now_utc - previous).total_seconds() >= 19 * 60:
                st.session_state[key] = now_utc
                st.rerun()
            if previous is None:
                st.session_state[key] = now_utc
            st.caption("Auto-refresh checks every ~20 minutes in an active browser session; "
                       "the full-universe prices are not 15-second live quotes.")
        universe_refresh_pulse()
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
    if mode == "Synthetic demo":
        market = cached_data(mode, tuple(tickers), years)
        data_refresh_status = "synthetic"
        data_refresh_stamp = None
        data_refresh_warnings = []
    else:
        market, data_refresh_status, data_refresh_stamp, data_refresh_warnings = refresh_market(
            tickers, years, kind="deep", min_history=160, min_interval=5 * 60)
    if len(market.close.columns) < MIN_STOCKS + 1:
        raise ValueError("Fewer than five valid stocks loaded. Add more tickers or retry download.")
    historical_news = {}
    if mode != "Synthetic demo":
        # A shared archive can eventually teach the whole-universe model from
        # timestamped stories. Dated source coverage must clear an empirical
        # selection gate; today's RSS is never injected into historical rows.
        for ticker in tickers:
            try:
                archive_frame = recorded_headlines(ticker)
                if not archive_frame.empty:
                    historical_news[ticker] = archive_frame
            except Exception:
                break  # optional archive unavailable; price-only model remains valid
    panel = cached_panel(market.close, market.volume, horizon,
                         news=historical_news or None)
    asof = panel["date"].max()
    rank = cached_ranking(panel, asof, fast_mode, boom_return, enhanced=False)
    if keep_forecast_ledger and mode != "Synthetic demo":
        try:
            log_forecasts(rank, asof, horizon, limit=250)
            reconcile_forecasts(market.close)
        except Exception as ledger_exc:
            st.warning(f"Historical forecast log unavailable: {type(ledger_exc).__name__}")
    signals = plan_signals(rank, horizon=horizon, risk_budget_pct=risk_budget_pct)
except Exception as exc:
    st.error(f"Unable to prepare the research dataset: {exc}")
    st.write("If Yahoo Finance is unavailable, switch to **Synthetic demo** to test the app offline.")
    st.stop()

if data_refresh_warnings:
    for warning in data_refresh_warnings:
        st.warning(warning)
if data_refresh_status == "stale":
    st.error("Provider refresh failed. Saved data is shown for reference, but forecasts may be stale.")
if data_refresh_stamp is not None:
    st.caption(f"Historical data refresh: **{data_refresh_status}** · last checked "
               f"{data_refresh_stamp.strftime('%Y-%m-%d %H:%M UTC')}. "
               "Training only uses completed daily sessions, not incomplete intraday candles.")
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
if (pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timestamp(asof)).days > 4:
    st.warning("The latest historical session is more than four calendar days old. "
               "Verify data completeness before interpreting forecast numbers.")
st.caption(f"Independent forecasting models: **{MAX_AGENTS}** (Ridge, Gradient Boosting, Random Forest); stock-by-stock audited competition. "
           "Leaderboard Forecast/Momentum/Risk scores remain descriptive ranking heuristics, not independent models. · "
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


historical_membership = None
strict_pit = False
pit_signature = 'present_day_survivors'
terminal_returns = None
historical_bundle = None


def current_validation():
    if (st.session_state.get('last_run_key') == validation_key and
            st.session_state.get('last_pit_signature') == pit_signature):
        return st.session_state.get('backtest')
    return None


def run_validation():
    try:
        # Do not show stale results from a previous test after an error.
        st.session_state.pop('backtest', None)
        if historical_bundle is not None:
            # The entire historical training AND evaluation universe comes from
            # the single immutable archive, NOT currently surviving Yahoo names.
            history_panel = build_panel(historical_bundle.market.close,
                                        historical_bundle.market.volume, horizon,
                                        fundamentals=historical_bundle.fundamentals or None,
                                        raw_close=historical_bundle.market.raw_close)
            result = cached_backtest(history_panel, historical_bundle.market.close,
                                     horizon, n_top, exposure, costs, test_periods,
                                     fast_mode, boom_return, historical_bundle.membership,
                                     True, historical_bundle.terminal_returns)
        else:
            result = cached_backtest(panel, market.close, horizon, n_top, exposure,
                                     costs, test_periods, fast_mode, boom_return,
                                     historical_membership, strict_pit, terminal_returns)
        st.session_state['last_pit_signature'] = pit_signature
        st.session_state['last_run_key'] = validation_key
        st.session_state['backtest'] = result
    except Exception as exc:
        st.session_state.pop('backtest', None)
        st.error(f'Validation could not run: {exc}')


search_tab, insider_tab, leaderboard_tab, research_tab, quote_tab, screen_tab, signals_tab, validation_tab, audit_tab, portfolio_tab, about_tab, lab_tab, system_tab = st.tabs(
    ["🔍 Search stock + news", "🧾 SEC Form 4 Insider Activity", "🏆 Ranked leaderboard", "🔎 Stock rankings", "💲 Latest prices", "🌐 Marketwide screener", "🟡 Signals & risk",
     "🧪 Walk-forward tests", "🏛️ Research audit", "💼 Virtual portfolio", "📘 Methodology", "🧠 Accuracy lab", "⚙️ Data & macro"]
)

@st.cache_data(ttl=2 * 60, show_spinner="Fetching recent publisher headlines…")
def cached_publisher_news(ticker: str, company: str):
    return fetch_news(ticker, company)


@st.cache_data(ttl=15 * 60, show_spinner=False)
def cached_leader_catalysts(ticker: str, company: str):
    """Batched leaderboard headline feed: 45d for acquisition review, cached."""
    return fetch_news(ticker, company, max_per_publisher=18, lookback_days=45)


@st.cache_data(ttl=12 * 60 * 60, show_spinner=False)
def cached_sec_insider_directory(contact: str):
    return ticker_directory(contact)


@st.cache_data(ttl=30 * 60, show_spinner=False)
def cached_insider_trades(ticker: str, contact: str):
    return fetch_form4_ticker(ticker, contact, directory=cached_sec_insider_directory(contact), max_filings=5)


with insider_tab:
    st.subheader("🧾 Public SEC Form 4 — Insider Activity")
    st.caption("This tab reviews **publicly filed** insider activity; it does not see trades before "
               "disclosure, predict secret orders, or treat an insider transaction as a guaranteed "
               "buy/sell signal. The SEC filing is the primary evidence.")
    st.info("**P** = purchase on the open market **or privately**; **S** = sale. "
            "Grants, option exercises, tax withholding, and most derivative transactions are "
            "excluded from the purchase/sale summary. A planned sale is not automatically bearish.")
    _insider_contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not _insider_contact:
        try:
            _insider_contact = str(st.secrets.get("SEC_CONTACT_EMAIL", "") or "").strip()
        except Exception:
            _insider_contact = ""
    if mode == "Synthetic demo":
        st.warning("Synthetic demo prices do not reflect actual insider trades. "
                   "SEC disclosures, if fetched, are real and unrelated to fictional forecasts.")
    if not _insider_contact:
        st.warning("To fetch SEC filings, set **SEC_CONTACT_EMAIL** (administrator contact) "
                   "in Streamlit Secrets. The SEC requires an identifying User-Agent. "
                   "The rest of Ithaca Quant works without this setting.")
    _choices = ["Top 25 modeled stocks", "All modeled stocks", "Custom tickers"]
    _scope = st.selectbox("Companies to review", _choices, key="form4_scope")
    if _scope == "Custom tickers":
        _custom = st.text_input("Ticker symbols (comma-separated)", "AAOI, RKLB", key="form4_custom_symbols")
        _insider_symbols = parse_tickers(_custom)[:100]
    else:
        _insider_symbols = rank["ticker"].astype(str).str.upper().drop_duplicates().tolist()
        if _scope == "Top 25 modeled stocks":
            _insider_symbols = _insider_symbols[:25]
    _batch = st.select_slider("Symbols checked per batch", options=[2, 5, 10], value=5,
                              help="SEC requests are deliberately throttled. Each filing can require "
                                   "multiple document downloads. Data requests are on demand, not continuous.")
    if "insider_form4_results_v255" not in st.session_state:
        st.session_state["insider_form4_results_v255"] = {}
    if "insider_form4_errors_v255" not in st.session_state:
        st.session_state["insider_form4_errors_v255"] = {}
    _saved = st.session_state["insider_form4_results_v255"]
    _errs = st.session_state["insider_form4_errors_v255"]
    _c1, _c2 = st.columns([2, 1])
    with _c1:
        _check = st.button("🔎 Check next companies for SEC Form 4 filings",
                           disabled=not _insider_contact or not _insider_symbols,
                           key="insider_form4_scan", type="primary")
    with _c2:
        _reload = st.button("↻ Recheck this selection", key="insider_form4_force")
    if _reload:
        for _sym in _insider_symbols:
            _saved.pop(_sym, None)
            _errs.pop(_sym, None)
        if _insider_contact:
            cached_insider_trades.clear()
    if _check:
        _pending = [symbol for symbol in _insider_symbols if symbol not in _saved]
        _selected_batch = _pending[:_batch]
        if not _selected_batch:
            st.info("All companies in this selection have been checked for this session. "
                    "Use 'Recheck this selection' to fetch fresh disclosures.")
        else:
            _progress = st.progress(0, text="Checking SEC ownership filings…")
            for _i, _symbol in enumerate(_selected_batch, 1):
                try:
                    _saved[_symbol] = cached_insider_trades(_symbol, _insider_contact)
                    _errs.pop(_symbol, None)
                except Exception as _ex:
                    _errs[_symbol] = type(_ex).__name__ + ": " + str(_ex)[:150]
                    # Failed retrieval must not count as zero disclosed transactions.
                _progress.progress(_i / len(_selected_batch),
                                   text=f"SEC Form 4 checks: {_i}/{len(_selected_batch)}")
            _progress.empty()
    _done = sum(sym in _saved for sym in _insider_symbols)
    st.caption(f"**Reviewed {_done:,} of {len(_insider_symbols):,}** selected ticker(s) this session. "
               "Results are cached for 30 minutes. No result does not prove no trades occurred "
               "outside the latest five filings or when the source is unavailable.")
    if _insider_symbols:
        st.progress(_done / len(_insider_symbols))
    _summary = []
    _transactions = []
    _today = datetime.now(timezone.utc).date()
    _window = st.selectbox("Recently disclosed within", [7, 30, 90], index=1, key="form4_recent_days",
                           format_func=lambda n: f"{n} days")
    for _sym in _insider_symbols:
        if _sym in _saved:
            _info = summarize_insider_activity(_saved[_sym], today=_today, recent_days=_window)
            _summary.append({"Ticker":_sym, "Research label":_info["signal"],
                             "Color":_info["color"], "Disclosed purchases":_info["purchases"],
                             "Disclosed sales":_info["sales"],
                             "Distinct buyers":_info["distinct_buyers"],
                             "Known buy value ($)":_info["buy_value_known"],
                             "Known sale value ($)":_info["sale_value_known"]})
            for _trade in _saved[_sym]:
                try:
                    _file_date = datetime.fromisoformat(_trade["filed_date"]).date()
                    if (_today - _file_date).days in range(_window + 1):
                        _transactions.append(_trade)
                except (ValueError, TypeError, KeyError):
                    pass
    if _summary:
        _summary_frame = pd.DataFrame(_summary).sort_values(
            ["Distinct buyers", "Known buy value ($)", "Disclosed purchases"],
            ascending=[False, False, False], kind="mergesort")
        st.markdown("#### Insider activity by company")
        st.dataframe(_summary_frame.style.apply(
            lambda col: ["background-color: #dcfce7; color: #14532d" if v == "GREEN"
                         else "background-color: #fef3c7; color: #713f12" if v == "YELLOW"
                         else "" for v in col], subset=["Color"]),
            hide_index=True, use_container_width=True,
            column_config={"Known buy value ($)":st.column_config.NumberColumn(format="$%.0f"),
                           "Known sale value ($)":st.column_config.NumberColumn(format="$%.0f")})
        st.caption("Green = reported buying worth investigating; yellow = mixed activity or sales; "
                   "neutral = no qualifying P/S in the checked filings. This coloring does not "
                   "change Ithaca Quant's calibrated forecasts or entry rankings.")
        if _transactions:
            st.markdown("#### Individual disclosed trades — linked to SEC filings")
            _trades = pd.DataFrame(_transactions).sort_values(["filed_date", "trade_date"], ascending=False)
            _trades = _trades.rename(columns={"ticker":"Ticker", "issuer":"Company", "owner":"Reporting insider",
                     "role":"Role", "type":"Type", "shares":"Shares", "price":"Price ($)",
                     "value_usd":"Value ($)", "trade_date":"Trade date", "filed_date":"EDGAR feed date",
                     "amended":"Amendment", "filing_url":"SEC filing"})
            _columns = ["Ticker", "Reporting insider", "Role", "Type", "Shares", "Price ($)",
                        "Value ($)", "Trade date", "EDGAR feed date", "Amendment", "SEC filing"]
            st.dataframe(_trades[_columns], hide_index=True, use_container_width=True,
                         column_config={"Shares":st.column_config.NumberColumn(format="%.0f"),
                                        "Price ($)":st.column_config.NumberColumn(format="$%.2f"),
                                        "Value ($)":st.column_config.NumberColumn(format="$%.0f"),
                                        "SEC filing":st.column_config.LinkColumn(display_text="View SEC filing")})
            st.download_button("Download Form 4 research CSV", _trades[_columns].to_csv(index=False),
                               file_name="ithaca_form4_disclosed_trades.csv", mime="text/csv")
        else:
            st.info("No qualifying P/S transactions found in the checked filings and chosen disclosure window.")
    elif _errs:
        st.warning("SEC checks have not succeeded yet. Review the errors below; failed fetches are not counted as no trades.")
    else:
        st.info("Select your companies and click **Check next companies**. The tab does not trigger "
                "SEC requests in the background while you are viewing other tabs.")
    if _errs:
        with st.expander(f"SEC request errors ({len(_errs)})"):
            for _sym, _detail in _errs.items():
                st.write(f"**{_sym}:** {_detail}")
    st.caption("**Publication timing:** Form 4 normally reports trades after execution. The displayed "
               "EDGAR feed date comes from its published/updated timestamp; check the filing for "
               "the official date. The SEC can "
               "publish filings after market hours; sales under Rule 10b5-1 plans and indirect "
               "ownership need interpretation. These labels are evidence summaries, not buy/sell advice.")


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
                    c1.metric("Scenario midpoint (not absolute prediction)", f"${scenario['target']:,.2f}")
                    c2.metric("Boom estimate (unverified)", probability_pct(r['prob_boom']))
                    c3.metric("Volatility (annualized)", f"{r['vol_20']:.1%}")
                    c4.metric("Horizon volatility scale", f"±{scenario['risk_1sigma_pct']:.1f}%")
                    st.write(f"**Conditional market scenario range:** ${scenario['lower_1sigma']:,.2f} – ${scenario['upper_1sigma']:,.2f}. {scenario['method']}")
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
            st.caption("News is fetched on demand and cached for 2 minutes. Today's news does NOT enter the historically trained AI models or backtests. "
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
    leaders = apply_company_filters(leaders, prefix="leader")
    leaderboard_candidates = leaders.copy()
    @st.fragment(run_every="60s")
    def render_news_leaderboard():
        leaders = leaderboard_candidates.copy()
        st.markdown("**🚦 Entry and exit conditions · acquisition/chase protection**")
        st.caption("Entry: dark green = strictest confirmed setup; green = ENTRY WATCH or early "
                   "trend-turn candidate; "
                   "yellow = unverified catalyst, wait, deal review or already-extended price; "
                   "red = REVIEW EXIT. Exit: green = monitor, yellow = exit caution, red = "
                   "model exit-review trigger. Colors are not trade instructions or validated odds.")
        st.caption("A stock cannot receive the strongest-entry color until available acquisition "
                   "headlines have been checked. All modeled stocks get 5-, 20- and 60-session "
                   "price-run-up screens; all modeled leaderboard tickers enter the news-review queue. "
                   "A headline result is not a comprehensive corporate-event database.")
        # Legacy: cached_leader_catalysts(symbol, company) checked only 12 stocks.
        # Run a small automatic batch every 60 seconds for ALL modeled leaderboard
        # stocks. Every ticker is queued; only completed, fresh reviews are green-eligible.
        # One broad Google News RSS request per stock, with event-level deduplication.
        news_items = [(str(row["ticker"]), str(row.get("company_name") or row["ticker"]))
                      for row in leaders.to_dict("records")]
        if mode == "Synthetic demo":
            coverage = {"checked":{}, "errors":{}, "done":0, "total":len(news_items),
                        "attempted":0, "remaining":len(news_items), "unique_events":0}
        else:
            coverage = update_universe_news(news_items)
        checked = coverage["checked"]
        feed_errors = coverage["errors"]
        st.caption(f"**Automatic whole-leaderboard news review:** {coverage['done']:,}/"
                   f"{coverage['total']:,} companies checked; {coverage['remaining']:,} remain or are stale. "
                   f"{coverage['unique_events']:,} unique, keyword-grouped news events. "
                   "Checks advance automatically in bounded batches while this dashboard is active. "
                   "Top candidates refresh about every 15 minutes; the broad pool has a 24-hour cache. "
                   "News queries may be delayed or blocked by the provider; missing coverage never means no news.")
        if coverage['total']:
            st.progress(coverage['done'] / coverage['total'],
                        text=f"Company news coverage: {coverage['done']:,}/{coverage['total']:,}")
        if feed_errors:
            with st.expander(f"News unavailable for {len(feed_errors)} companies (retry later)"):
                for symbol, details in list(feed_errors.items())[:30]:
                    st.write(f"{symbol}: {details}")
        leaders = add_leaderboard_review(leaders, signals, market.close,
                                         asof=asof.date(), horizon=horizon, headlines_by_ticker=checked)
        # News text is displayed directly in every leaderboard row that was
        # checked, not hidden behind a second "fetch headlines" button.
        news_details = []
        for item in leaders.to_dict("records"):
            symbol = str(item["ticker"])
            stories = checked.get(symbol)
            if stories is None:
                news_details.append({"ticker": symbol, "news_headline_count": None,
                                     "news_tone": "Not checked / provider failed",
                                     "news_headline": "", "news_url": "",
                                     "news_event_sources":"", "news_reports_on_event":None})
                continue
            view = analyze_news(stories, symbol, str(item.get("company_name") or symbol))
            newest = view.get("headlines", [])[:1]
            story = newest[0] if newest else {}
            news_details.append({"ticker": symbol, "news_headline_count": view.get("n", 0),
                                 "news_tone": view.get("label", "No usable news"),
                                 "news_headline": story.get("title", ""),
                                 "news_url": story.get("url", "")})
        if news_details:
            leaders = leaders.merge(pd.DataFrame(news_details), on="ticker", how="left", validate="one_to_one")
        else:
            for column in ("news_headline_count", "news_tone", "news_headline", "news_url",
                           "news_event_sources", "news_reports_on_event"):
                leaders[column] = pd.Series(dtype="object")
        prefer_entry_rank = st.checkbox("Rank by entry readiness (green before yellow; red last)",
                                       value=True, key="leader_entry_sort",
                                       help="First sort by actual ENTRY/EXIT color tier, then by entry-priority "
                                            "score. Original research scores and return forecasts remain unchanged.")
        leaders["original_model_rank"] = leaders["rank"]
        if prefer_entry_rank and not leaders.empty:
            leaders = leaders.sort_values(
                ["entry_sort_tier", "entry_priority_score", "research_score", "rank"],
                ascending=[True, False, False, True], na_position="last", kind="mergesort").copy()
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
            col1.metric("#1 entry-priority candidate" if prefer_entry_rank else "#1 model-ranked candidate",
                        str(top.iloc[0]["ticker"]))
            col2.metric("Eligible modeled stocks", f"{len(leaders):,}")
            col3.metric("Shown in leaderboard", f"{len(top):,}")
            early_found = leaders.loc[
                leaders["early_trend_watch"].fillna(False) &
                leaders["color"].eq("GREEN")
            ].copy()
            with st.expander(f"🌱 Early entry watch · {len(early_found):,} pre-breakout candidates", expanded=bool(len(early_found))):
                st.caption("Requires a 20-session favorable forecast, a positive five-day relative "
                           "turn with acceleration, activity checks and a non-extended 52-week range. "
                           "Not a prediction that a rally is about to happen. Red exit-review "
                           "signals, acquisition news checks and chase warnings still override green.")
                if early_found.empty:
                    st.info("No qualifying early trend turns in the modeled subset for this horizon. "
                            "Use a 20-session forecast and allow news checks to finish; "
                            "the broad scanner now reserves some slots for these profiles.")
                else:
                    early_preview = early_found.sort_values("entry_priority_score", ascending=False).head(25)
                    early_cols = ["ticker", "signal_label", "forecast_excess", "position_52w",
                                  "entry_priority_score", "news_52w_context"]
                    st.dataframe(early_preview[early_cols].rename(columns={
                        "ticker":"Ticker", "signal_label":"Entry", "forecast_excess":"Forecast vs SPY",
                        "position_52w":"52w range position", "entry_priority_score":"Entry priority /100",
                        "news_52w_context":"News / 52w explanation"}).style.map(
                            lambda x: "background-color:#dcfce7;color:#14532d;font-weight:bold",
                            subset=["Entry"]), hide_index=True, use_container_width=True)


            company_info = directory.listings if (scan_table is not None and universe_mode.startswith("Automatic")) else None
            table = leaderboard_display(top, horizon, boom_return, signals=signals, company_info=company_info)
            table = attach_quality(table, leaderboard_validation.predictions if leaderboard_validation is not None else None)
            st.caption("Headlines appear inside the leaderboard as news-review batches complete. "
                       "To avoid ranking a potentially priced-in "
                       "acquisition as a strong entry, unchecked and recently extended stocks are "
                       "yellow until further review. News-word tone is not a trade forecast.")
            st.caption("**Model rank** is the original forecast-based order; **Rank** (with readiness sorting) "
                       "puts dark green ahead of confirmed green, early-turn green, yellow and red. Acquisition-linked jumps, deals "
                       "under review, and large 5/20/60-session run-ups lower entry priority. "
                       "Unverified acquisition coverage cannot earn a strong-entry label. The original "
                       "model forecast and research score are unchanged. These are unvalidated screens, "
                       "not probabilities of gains or proof that a deal is fully priced in.")
            formatted = table.copy()
            for col in ("OOS direction hit", "OOS forecast MAE", "OOS zero-forecast MAE"):
                formatted[col] = formatted[col].map(lambda v: "Not tested" if pd.isna(v) else f"{v:.1%}")
            for col in ("OOS boom Brier", "OOS boom baseline Brier"):
                formatted[col] = formatted[col].map(lambda v: "Not tested" if pd.isna(v) else f"{v:.4f}")
            rate_columns = [c for c in formatted.columns if c.startswith(("Forecast vs SPY", "P(gain,", "P(+", "Historical 1σ", "Annualized volatility", "20d vs SPY", "Model disagreement", "5d stock return", "5d vs SPY", "20d stock return", "20d run-up vs SPY", "60d stock return", "60d run-up vs SPY", "Distance above exit level", "Deal move vs SPY", "52w range position"))]
            for c in rate_columns:
                formatted[c] = formatted[c].map(lambda v: "N/A" if pd.isna(v) else f"{v:+.1%}" if c.startswith(("Forecast vs SPY", "20d vs SPY", "5d stock return", "5d vs SPY", "20d stock return", "20d run-up vs SPY", "60d stock return", "60d run-up vs SPY", "Distance above exit level", "Deal move vs SPY")) else f"{v:.1%}")
            def _leader_signal_style(value):
                label = str(value)
                if "🟩" in label:
                    return "background-color: #14532d; color: #ffffff; font-weight: bold"
                if "🟢" in label:
                    return "background-color: #dcfce7; color: #14532d; font-weight: bold"
                if "🔴" in label:
                    return "background-color: #fee2e2; color: #7f1d1d; font-weight: bold"
                return "background-color: #fef3c7; color: #713f12; font-weight: bold"
            st.dataframe(formatted.style.map(_leader_signal_style, subset=["Entry signal", "Exit signal"]), hide_index=True,
                use_container_width=True,
                column_config={
                    "Entry priority /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Deal source URL": st.column_config.LinkColumn("Deal source", display_text="Open"),
                    "Latest news link": st.column_config.LinkColumn("News source", display_text="Open"),
                    "Rank": st.column_config.NumberColumn(format="%d", width="small"),
                    "Research score /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Forecast agent /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Momentum agent /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Risk agent /100": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
                    "Adjusted daily close ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "Exit review level ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "52w low ($)": st.column_config.NumberColumn(format="$%.2f"),
                    "52w high ($)": st.column_config.NumberColumn(format="$%.2f"),
                })
            flagged_exits = leaders.loc[leaders["exit_color"].isin(["RED", "YELLOW"]),
                                       ["ticker", "exit_label", "exit_reason", "exit_level", "forecast_excess"]]
            with st.expander(f"🚦 Exit review queue: {len(flagged_exits):,} positions require attention"):
                if flagged_exits.empty:
                    st.success("No active exit-caution or review triggers in the modeled group.")
                else:
                    exit_queue = flagged_exits.rename(columns={
                        "ticker": "Ticker", "exit_label": "Exit signal",
                        "exit_reason": "Why it was flagged", "exit_level": "Adjusted review level ($)",
                        "forecast_excess": "Forecast vs SPY"})
                    st.dataframe(exit_queue.style.map(_leader_signal_style, subset=["Exit signal"]),
                                 hide_index=True, use_container_width=True)
            st.caption("**Exit signals are separate from entry suitability.** Red can reflect a "
                       "negative forecast, weak 20-day moving-average gap, or reached adjusted "
                       "price-review level. Yellow flags weaker/missing evidence or proximity to "
                       "the review level. Review levels are not automatic stop orders; actual "
                       "prices can gap through them.")
            st.caption("**New evidence columns:** OOS windows = number of nonoverlapping historical test windows for that "
                       "ticker; direction hit = fraction of positive/negative SPY-relative signs forecast correctly; "
                       "forecast MAE = absolute SPY-relative error. The zero-forecast MAE and historical-frequency boom "
                       "Brier are naive baselines. Fewer than 12 windows means TOO FEW TESTS, even when the hit rate "
                       "looks high. This historical evaluation cannot validate any current individual forecast.")
            st.caption("The leaderboard's Forecast/Momentum/Risk scores are descriptive ranking heuristics, "
                       "not predictive AI. The separate Ridge/Gradient Boosting/Random Forest tournament "
                       "compares independently fitted models for each stock, promoting a winner only "
                       "when distinct historical selection and audit windows beat the existing ensemble. "
                       "This is not proof of future accuracy or an authenticated historical universe.")
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

    render_news_leaderboard()

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
    auto_quotes = st.checkbox("Enable automatic priority quote updates (while this page is open)", value=False)
    requested_seconds = st.select_slider("Live quote refresh interval (seconds)",
                                        options=[15, 30, 60, 120], value=15)
    effective_seconds = max(requested_seconds, 60) if len(quote_symbols) > 25 else requested_seconds
    if effective_seconds != requested_seconds:
        st.caption("More than 25 symbols: 60-second minimum to reduce data-provider throttling.")

    @st.fragment(run_every=f"{effective_seconds}s" if auto_quotes else None)
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
            f"Refresh target: {effective_seconds} seconds (active browser session only). "
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
    strict_pit = st.checkbox('Require historical point-in-time membership (refuse survivor-only results)',
                             value=False, key='strict_pit_audit')
    membership_csv = st.file_uploader('Optional: archived historical universe snapshots (CSV)', type=['csv'],
                                      key='archived_constituents',
                                      help='Columns: date,ticker,eligible,provenance. One membership snapshot per signal date. '
                                           'provenance must be historical_archive; eligible tickers must have complete delisted returns.')
    if membership_csv is not None:
        pit_signature = hashlib.sha256(membership_csv.getvalue()).hexdigest() + str(strict_pit)
        try:
            historical_membership = pd.read_csv(membership_csv)
            if 'eligible' in historical_membership:
                values = historical_membership.eligible.astype(str).str.strip().str.lower()
                if not values.isin(['true','false','1','0']).all():
                    raise ValueError('eligible must be true or false on every row')
                historical_membership['eligible'] = values.isin(['true','1'])
            st.caption('Archived membership file loaded for strict date-by-date validation. '
                       'The claimed provenance cannot be independently authenticated.')
        except Exception as file_exc:
            historical_membership = None
            st.error(f'Historical membership file is unusable: {file_exc}')
    else:
        pit_signature = 'strict_with_no_history' if strict_pit else 'present_day_survivors'
    terminal_file=st.file_uploader('Optional: archived terminal delisting payoffs (CSV)',
        type=['csv'], key='archived_terminal_returns',
        help='Required fields: signal_date,ticker,asof_total_return,entry_total_return,source. '
             'Source must be historical_archive; these records are user-declared, not authenticated.')
    if terminal_file is not None:
        pit_signature += hashlib.sha256(terminal_file.getvalue()).hexdigest()
        try:
            terminal_returns=pd.read_csv(terminal_file)
        except Exception as err:
            st.error('Could not read archived terminal payoffs: '+type(err).__name__)
    archive_upload = st.file_uploader(
        'Point-in-time market archive (ZIP, stable security IDs and SHA-256 manifest)',
        type=['zip'], key='pit_vendor_bundle',
        help='Requires manifest.json, security_master.csv, price_history.csv and dated membership.csv. '
             'See HISTORICAL_DATA_GUIDE_v3.1.md. Overrides the legacy CSV inputs for this backtest.')
    if archive_upload is not None:
        pit_signature = hashlib.sha256(archive_upload.getvalue()).hexdigest() + 'full_historical_bundle'
        try:
            historical_bundle = cached_historical_archive(archive_upload.getvalue())
            report = historical_bundle.quality
            st.success(f"Archive checksums passed: {report['security_id_count']} stable securities, "
                       f"{report['membership_snapshot_dates']} dated membership snapshots, "
                       f"{report['terminal_payoff_rows']} documented delisting payoff rows.")
            st.caption('Historical range: ' + report['date_first'] + ' through ' + report['date_last'] +
                       ' · Declared provider: ' + report['provider_declared'] +
                       f" · Internal bar gaps: {report['price_bar_internal_gap_rate']:.2%}" +
                       f" · Adjusted-return outliers (>75%): {report['large_adjusted_move_count_over_75pct']}" +
                       f" · Unknown volume cells: {report['missing_volume_cells']}")
            st.warning('File integrity verified, but SOURCE AUTHENTICITY and universe completeness remain UNVERIFIED. '
                       'Only provider-issued, correctly sourced archives can address survivorship bias.')
        except Exception as archive_err:
            historical_bundle = None
            st.error('Archive rejected: ' + str(archive_err))
            strict_pit = True  # never silently fall back after corrupt archive input
    st.caption('Historical replay runs the production three-model tournament on the imported '
               'historical security IDs when an archive is provided. Missing delisting payoffs '
               'stop the run instead of disappearing into cash.')
    if st.button("Run walk-forward backtest", type="primary", use_container_width=True,
                 disabled=(archive_upload is not None and historical_bundle is None)):
        run_validation()
    if current_validation() is not None:
        result = current_validation()
        m = result.metrics
        cols = st.columns(4)
        cols[0].metric("Model strategy return", pct(m["portfolio_return"]))
        cols[1].metric("SPY return (same period)", pct(m["benchmark_return"]))
        cols[2].metric("Momentum baseline return", pct(m["momentum_return"]))
        cols[3].metric("Beat SPY in windows", f"{m['period_hit_rate']:.0%}")
        st.warning('Historical universe status: ' + str(m.get('backtest_evidence_status','Unknown')))
        st.caption('Production tournament replay: '+str(m.get('competition_replayed',False))+
                   '. Periods with insufficient challenger evidence retain the incumbent. '
                   'Delisting returns require sourced historical archives.')
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
        if np.isfinite(q.get('window_direction_lift_low', np.nan)):
            st.caption(
                f"Date-block bootstrap: mean directional lift vs past-majority baseline "
                f"{q['window_direction_lift']:+.1%}, exploratory 95% interval "
                f"[{q['window_direction_lift_low']:+.1%}, "
                f"{q['window_direction_lift_high']:+.1%}]. "
                "Bootstrap resamples decision dates, not individual stocks; does not remove survivorship bias."
            )
            if q['window_direction_lift_low'] <= 0:
                st.info('The date-block interval includes zero: these observations do not establish an edge over the naive direction baseline.')
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

with audit_tab:
    st.subheader("🏛️ Institutional-style Research Audit")
    st.caption("Independent factor diagnostics on already-frozen out-of-sample predictions. "
               "Methods are informed by public QuantConnect, Numerai and Alphalens documentation; "
               "this is not their proprietary technology or a claim of comparable performance.")
    st.info("First use **Walk-forward tests → Run walk-forward backtest** in this same dashboard. "
            "The audit does not refit models, choose winners using future outcomes, "
            "or change your live entry and exit signals.")
    _result=current_validation()
    if _result is None:
        st.warning("No completed walk-forward results for the current universe/settings. Run the backtest first.")
    else:
        _cost=st.slider("Assumed trading friction per side (basis points)",
                        min_value=0,max_value=100,value=10,step=5,key='institutional_cost_bps')
        _frac=st.select_slider("Top-ranked fraction evaluated",options=[.1,.2,.25,.33],value=.2,
                               format_func=lambda x:f'{x:.0%}',key='institutional_top_fraction')
        try:
            _audit=factor_audit(_result.predictions,top_fraction=_frac,
                                assumed_round_trip_bps=2*_cost)
            _m=_audit.metrics
            if _m.get('windows',0):
                _c=st.columns(4)
                _c[0].metric('Independent decision windows',f"{_m['windows']:,}")
                _c[1].metric('Mean rank information coefficient',
                             'N/A' if _m['mean_rank_ic'] is None else f"{_m['mean_rank_ic']:+.3f}")
                _c[2].metric('Top-ranked vs universe (SPY-relative)',f"{_m['top_vs_universe_excess']:+.2%}")
                _c[3].metric('Top-quintile direction hit',f"{_m['top_hit_rate']:.1%}")
                low,high=_m['uplift_ci_low'],_m['uplift_ci_high']
                if low is not None:
                    st.caption(f"Date-resampled 95% exploratory range for top-vs-universe: {low:+.2%} to {high:+.2%}. "
                               "If the range crosses zero, this does not establish a ranking advantage.")
                    if low<=0:
                        st.warning('The estimated ranking advantage is not distinguishable from zero by this date-block bootstrap.')
                else:
                    st.warning('Fewer than eight dates: insufficient distinct observations for a bootstrap interval.')
                st.caption(f"Top vs bottom SPY-relative spread: {_m['top_bottom_excess']:+.2%}; "
                           f"average name turnover: {_m['average_name_turnover']:.1%}. "
                           "These measure cross-sectional ranking, not executable profits.")
                st.dataframe(_audit.by_date,use_container_width=True,hide_index=True)
                st.download_button('Export independent factor audit CSV',_audit.by_date.to_csv(index=False),
                                   file_name='ithaca_factor_audit.csv',mime='text/csv')
                _delayed=next_close_proxy(_result.predictions,market.close,
                                          top_fraction=_frac,round_trip_bps=2*_cost)
                st.subheader('Execution-timing sensitivity: one-session delay')
                if _delayed.empty:
                    st.warning('No matching dates and following price bars exist for delayed comparison.')
                else:
                    _cc=st.columns(3)
                    _cc[0].metric('Same-close gross return',f"{_delayed.same_close_return.mean():+.2%}")
                    _cc[1].metric('Next-close gross return',f"{_delayed.next_close_return.mean():+.2%}")
                    _cc[2].metric('Next-close after assumed costs',
                                  f"{_delayed.next_close_net_return_stress.mean():+.2%}")
                    st.caption(f"{len(_delayed):,} selected ticker-windows have next-session prices. "
                               "This is a delayed close-to-close PROXY, not a live executable fill or a corrected performance claim. "
                               "Costs and actual open auction fills can differ substantially.")
                    st.download_button('Export delayed-execution comparison CSV',
                                       _delayed.to_csv(index=False),file_name='ithaca_next_close_proxy.csv',
                                       mime='text/csv')
                for _note in _audit.caveats:
                    st.caption('• '+_note)
            else:
                st.warning('Insufficient cross-sectional decision dates to audit.')
        except Exception as _exc:
            st.error(f'Research audit unavailable: {_exc}')
    with st.expander('Historical price data quality checks',expanded=False):
        try:
            _health=historical_data_health(market.close)
            _flagged=_health.loc[_health.review!='No simple flags']
            st.caption(f'{len(_flagged):,} of {len(_health):,} symbols have simple coverage or price-move review flags. '
                       'A legitimate earnings jump may be flagged. This is NOT a historical delisting audit.')
            st.dataframe(_health,hide_index=True,use_container_width=True)
            st.download_button('Export market data quality CSV',_health.to_csv(index=False),
                               file_name='ithaca_price_quality.csv',mime='text/csv')
        except Exception as _exc:
            st.error(f'Price quality audit unavailable: {_exc}')
    st.markdown('**Research method references**: '
                '[QuantConnect LEAN](https://www.lean.io/research/) · '
                '[Numerai Signals](https://docs.numer.ai/numerai-signals/scoring) · '
                '[Alphalens](https://alphalens.ml4trading.io/notebooks/overview.html) · '
                '[QuantRocket](https://www.quantrocket.com/docs/)')

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
        st.subheader("Portfolio concentration and market-shock research")
        stress = stress_summary(market.close.loc[:entry], alloc)
        if stress:
            a, b, c = st.columns(3)
            a.metric("Historical beta to SPY", f"{stress['beta_to_spy']:.2f}")
            b.metric("Largest initial position", f"{stress['max_initial_weight']:.1%}")
            c.metric("Past daily 5% tail-average return", f"{stress['daily_95pct_historical_tail_mean']:.2%}")
            st.dataframe(pd.DataFrame([{'Hypothetical market move':k, 'Approximate portfolio move':f'{v:+.1%}'}
                                       for k,v in stress['shock_scenarios'].items()]),
                         hide_index=True, use_container_width=True)
            st.caption(stress['note'])
        else:
            st.info("Insufficient pre-entry observations for market-stress analysis.")
        plan = pd.DataFrame({"ticker": list(alloc), "weight_pct": [100 * x for x in alloc.values()]})
        st.download_button("Download allocation plan CSV", plan.to_csv(index=False),
                           file_name="ithaca_allocation_plan.csv", mime="text/csv")
        st.caption(
            "Hypothetical historical buy-and-hold illustration only. Adjusted close may "
            "differ from StockTrak fills; it is not a live competition account ledger."
        )

with about_tab:
    st.subheader(f"Ithaca Quant v{APP_RELEASE} — methodology")
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
        "This app incorporates **SEC quarterly financial factors only when dated history is available "
        "and a chronological model-selection check improves**. Previously archived headlines "
        "are handled similarly, with strict first-seen timestamps. Current news sentiment does NOT "
        "automatically adjust the trained main prediction: it remains a separate unverified scenario. "
        "The model does not correct stock-universe survivorship bias or guarantee calibrated "
        "probabilities, profit, or accurate future prices. This is an educational research prototype."
    )
    st.markdown(f"[Review the official competition restrictions]({RULES_URL})")
    st.write("To extend this system, add point-in-time fundamental datasets and a completely untouched final test period before evaluating any new model.")


with lab_tab:
    st.subheader("Accuracy lab · ongoing real-world forecast verification")
    st.caption("Predictions are appended on the date they were made and are never edited. "
               "Only outcomes for fully elapsed trading horizons are scored. Historical walk-forward "
               "tests are available on the separate validation tab.")
    if mode == "Synthetic demo":
        st.warning("Synthetic prices are not eligible for real forward verification.")
    else:
        try:
            report = forward_report()
            cols = st.columns(4)
            cols[0].metric("Recorded predictions", f"{report['logged']:,}")
            cols[1].metric("Timestamp-eligible matured", f"{report.get('timestamp_eligible_resolved',0):,}")
            cols[2].metric("Timestamp-eligible MAE", "N/A" if pd.isna(report.get('timestamp_eligible_mae')) else f"{report['timestamp_eligible_mae']:.2%}")
            cols[3].metric("Eligible predict-zero MAE", "N/A" if pd.isna(report.get('timestamp_eligible_baseline_mae')) else
                           f"{report['timestamp_eligible_baseline_mae']:.2%}")
            comparison = forward_model_comparison_report(horizon=horizon)
            st.subheader('Real-forward AI champion vs incumbent')
            st.caption(comparison['status'] + '. This is a paired timestamp-eligible comparison; '
                       'no claim of superiority without independently matured observations.')
            x1,x2,x3=st.columns(3)
            x1.metric('Independent forward windows', f"{comparison['independent_windows']:,}")
            x2.metric('Winner MAE', 'N/A' if pd.isna(comparison['winner_mae']) else f"{comparison['winner_mae']:.2%}")
            x3.metric('Incumbent MAE', 'N/A' if pd.isna(comparison['incumbent_mae']) else f"{comparison['incumbent_mae']:.2%}")
            if np.isfinite(comparison['improvement_ci_low']):
                st.caption(f"Date-block bootstrap improvement interval: {comparison['improvement_ci_low']:+.2%} "
                           f"to {comparison['improvement_ci_high']:+.2%} (preliminary, not authenticated).")
            if 'agent_winner' in rank:
                st.subheader('Three-model tournament by stock')
                fields = ['ticker','agent_ridge_forecast','agent_gradient_boosting_forecast',
                          'agent_random_forest_forecast','agent_winner','agent_edge_status',
                          'agent_selection_windows','agent_audit_windows','agent_audit_mae',
                          'agent_baseline_mae','agent_vote_spread','agent_q_value',
                          'agent_feature_sources','agent_probability_status']
                st.dataframe(rank[[c for c in fields if c in rank.columns]],
                             hide_index=True, use_container_width=True)
                st.caption("Each model is trained separately. Ticker-specific winners must pass both "
                           "20+ independent sessions per period, paired directional/rank metrics, "
                           "and multi-stock false-discovery adjustment, or the incumbent stays in control. "
                           "The tournament uses available stocks only; past delistings remain unverified.")
            st.caption(f"{report['resolved']} total historical recorded outcomes; only {report.get('timestamp_eligible_resolved',0)} "
                       "were timestamp-eligible for forward verification. The database and price provider "
                       "are not independently attested. Backfilled entries are excluded from the qualifying metric.")
            if report.get('timestamp_eligible_resolved',0) < 100:
                st.info("Not yet enough genuinely forward-tested outcomes to claim reliable accuracy. "
                        "Keep the forecast log enabled and check later.")
            else:
                st.caption(f"Relative-return directional accuracy: {report['timestamp_eligible_directional_accuracy']:.1%}. "
                           "Repeated tickers and overlapping horizons are dependent observations.")
                st.dataframe(report['by_horizon'], use_container_width=True)
        except Exception as exc:
            st.warning(f"Forecast ledger unavailable: {type(exc).__name__}. "
                       "Configure a database or check local disk permissions.")
    st.divider()
    st.subheader("📬 Friday 4 PM ET forecast report & notifications")
    st.caption("Reports evaluate only predictions whose 5/20/60-session outcomes have matured. "
               "Friday delivery uses America/New_York, including daylight-saving time. "
               "Email delivery requires separate GitHub Actions and SMTP setup; the app does not "
               "send emails just by staying open.")
    _, weekly_end = report_window()
    last_report = load_weekly_report(weekly_end.date().isoformat())
    if last_report:
        st.text(render_report(last_report))
        st.download_button("Download weekly scorecard", render_report(last_report),
                           file_name=f"ithaca_weekly_{weekly_end.date()}.txt", mime="text/plain")
    else:
        st.info("No saved Friday report for this week. Use Preview to examine eligible outcomes; "
                "scheduled reports need a durable database and workflow secrets.")
    if st.button("Preview this week's actual forecast results", key="preview_friday_audit"):
        try:
            draft=make_weekly_report(persist=False)
            st.code(render_report(draft),language="text")
            if draft['evaluated']<30:
                st.warning("Too few matured predictions this week for a useful accuracy claim.")
        except Exception as exc:
            st.warning(f"Weekly preview unavailable: {type(exc).__name__}")
    if report['resolved']:
        st.info(f"🔔 {report['resolved']:,} total completed forward predictions are available for review; "
                "new results appear when refreshed price data completes their horizons.")
    st.divider()
    st.subheader("🧠 Independent stock-ranking accuracy challenge")
    st.caption("A new selected-horizon outperform-SPY classifier must improve both Brier score and "
               "top-quartile accuracy on a selection period AND repeat on a separate untouched audit. "
               "If it fails, the existing forecast remains primary. No 80% guarantee.")
    if st.button("Train & audit alternative ranking model", key="challenge_rank_model"):
        try:
            with st.spinner("Testing chronologically separated stock ranks…"):
                challenger=rank_outperformance(panel, asof=asof)
            st.write("**Audit:**", challenger.evidence)
            if challenger.selection:
                st.json({"Selection":challenger.selection,"Independent audit":challenger.audit})
            if challenger.activated:
                st.success("Candidate passed independent ranking checks; research sidecar only.")
                st.dataframe(challenger.candidates.head(30),hide_index=True,use_container_width=True)
            else:
                st.warning("No promotion: the evidence gate was not met.")
        except Exception as exc:
            st.warning(f"Ranking challenge unavailable: {type(exc).__name__}: {exc}")
    st.divider()
    st.subheader("🧬 Model Zoo · independent rank comparisons")
    st.caption("New: Qlib-inspired factor models, a fixed linear/nonlinear blend, "
               "and optional LightGBM / XGBoost LambdaMART. These learn which stocks "
               "rank ahead of other stocks ON THE SAME DAY, not buy/sell probabilities. "
               "Selection and audit periods are separate, and neither can include "
               "a future label at training time. Running this analysis is compute-heavy. "
               "It never automatically changes the main leaderboard.")
    with st.expander("Available models and what makes each different", expanded=False):
        st.dataframe(model_catalog(), hide_index=True, use_container_width=True)
        st.caption("Extra packages are optional. EBM requires InterpretML. "
                   "Foundation models such as Chronos or TimesFM are not included: "
                   "they require separate downloads and stock-specific evaluation.")
    if st.button("Compare ranking models on independent past periods", key="iq_model_zoo_ranking"):
        try:
            with st.spinner("Training grouped ranking models and testing untouched decision dates…"):
                zoo = compare_rank_models(panel, asof=asof)
            st.write(zoo.evidence)
            if not zoo.selection_table.empty:
                st.markdown("**Purged selection period**")
                st.dataframe(zoo.selection_table, hide_index=True, use_container_width=True)
            if not zoo.audit_table.empty:
                st.markdown("**Independent chronological audit**")
                st.dataframe(zoo.audit_table, hide_index=True, use_container_width=True)
            if zoo.qualified:
                st.success(f"Independent research ranking passed: {zoo.winner}. Not automatically deployed.")
                st.dataframe(zoo.current_ranks.head(40), hide_index=True, use_container_width=True)
                st.download_button("Export experimental ranked stocks", zoo.current_ranks.to_csv(index=False),
                                   file_name="ithaca_rank_challenger.csv", mime="text/csv")
            else:
                st.warning("No new ranking strategy promoted. The existing production ranks are preserved.")
        except Exception as exc:
            st.error(f"Model Zoo audit unavailable: {type(exc).__name__}: {exc}")
    st.divider()
    st.subheader("Import historical licensed news (optional)")
    st.caption("A valid historical news provider export can seed the feature archive "
               "without waiting months for RSS collection. The true vendor availability "
               "timestamp is essential; do not substitute download time or article date.")
    news_csv = st.file_uploader("Timestamped vendor-news CSV", type=['csv'], key='vendor_historical_news')
    rights = st.checkbox("I confirm licensed data use and genuine vendor first-seen timestamps",
                         value=False, key='news_rights_confirmation')
    if st.button("Import validated archive", disabled=news_csv is None or not rights):
        try:
            imported = import_vendor_archive(pd.read_csv(news_csv), provenance_confirmed=rights)
            st.success(f"Inserted {imported:,} nonduplicate, dated headline records.")
            cached_panel.clear()
            cached_ranking.clear()
        except Exception as exc:
            st.error(f"Archive import rejected: {type(exc).__name__}: {exc}")
    st.divider()
    st.subheader("Model evidence and regime indicators")
    st.write("Individual-stock forecasts can compare the existing ensemble against "
             "Ridge, robust Huber, nonlinear RBF, median quantile, ExtraTrees, and "
             "optional LightGBM/XGBoost/CatBoost/EBM candidates. "
             "Model selection requires at least 2% lower error on a separate chronological "
             "selection window; an untouched, purged final block calibrates the forecast range.")
    regime = market_regime(market.close[BENCHMARK], asof=asof)
    st.write(f"**Current SPY regime:** {regime['name']}")
    if pd.notna(regime['momentum_20']):
        cols = st.columns(2)
        cols[0].metric("SPY 20-session return", f"{regime['momentum_20']:+.2%}")
        cols[1].metric("SPY annualized 20-session volatility", f"{regime['volatility_20']:.1%}")
    st.caption(regime['description'] + " Market regimes are not automatically used to alter forecasts.")

with system_tab:
    st.subheader("Storage, refresh and macroeconomic context")
    db = storage_health()
    st.write(f"**Cache backend:** {db['backend']} · "
             f"**connection:** {'Ready' if db['reachable'] else 'Unavailable'}")
    st.caption(db['note'])
    st.write(f"**Source data:** {market.source} · **Most recent completed session:** {asof.date()} "
             f"· **last refresh:** {data_refresh_status}")
    st.caption("Quotes may be delayed. Refreshes honor available bars and active sessions; "
               "the optional CI worker runs only when database and watchlist secrets are configured. "
               "Provider rate limits and CI scheduling are not guaranteed.")
    st.divider()
    st.subheader("Federal Reserve FRED / ALFRED data")
    try:
        fred_key = str(st.secrets.get('FRED_API_KEY', '') or os.environ.get('FRED_API_KEY', '')).strip()
    except Exception:
        fred_key = str(os.environ.get('FRED_API_KEY', '')).strip()
    if fred_key:
        @st.cache_data(ttl=3600, show_spinner="Reading real-time-vintage economic series…")
        def _macro_cache(key, date_str):
            return macro_snapshot(key, date_str)
        if st.button("Load latest available macroeconomic context"):
            macro = _macro_cache(fred_key, str(asof.date()))
            st.dataframe(macro, hide_index=True, use_container_width=True)
            st.caption("The as-of query uses ALFRED vintage parameters for the selected date. "
                       "Macro figures are contextual and NOT silently inserted into the trained model.")
    else:
        st.info("Set FRED_API_KEY in Streamlit Secrets to load publication-vintage "
                "Federal Reserve rates, Treasury yields, unemployment, and CPI series.")
    st.divider()
    st.subheader("Historical-data and modeling safeguards")
    st.write("Prices: saved/incrementally refreshed · SEC: filing-date gated · "
             "news: first-seen gated · forecasts: logged immutably · models: purged validation "
             "· risk: scenario stress · optional SQL storage: persistent on restart.")
    st.caption("Live prices, cloud persistence and scheduled collection depend on external "
               "providers, valid credentials, rate limits and your deployment configuration. "
               "This dashboard does not execute real trades.")
