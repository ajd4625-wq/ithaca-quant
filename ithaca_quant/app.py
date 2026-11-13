"""Ithaca Quant — Streamlit dashboard for educational stock research.

Run: streamlit run app.py
No actual orders are placed; all allocations are hypothetical.
"""
import os
from datetime import datetime, timezone
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Check the package BEFORE importing feature modules. GitHub web uploads can
# update app.py without updating the inner ithaca_quant/ package; previously
# this caused an opaque ImportError before the dashboard could show guidance.
from ithaca_quant import __version__
APP_RELEASE = "1.4.2"
st.set_page_config(page_title=f"Ithaca Quant v{APP_RELEASE}", page_icon="📈", layout="wide")
if __version__ != APP_RELEASE:
    st.error(
        f"Deployment version mismatch: app.py is v{APP_RELEASE}, but the imported "
        f"ithaca_quant package is v{__version__}. Your GitHub deployment contains "
        "files from different releases. Replace the ENTIRE contents of the repo's "
        "ithaca_quant/ folder with those from the same release ZIP, including "
        "ithaca_quant/ithaca_quant/__init__.py and explorer.py, commit to main, "
        "and then reboot the Streamlit app."
    )
    st.stop()

from ithaca_quant.backtest import run_walk_forward
from ithaca_quant.config import (
    BENCHMARK, COMPETITION_END, COMPETITION_START, DEFAULT_TICKERS,
    INITIAL_CAPITAL, MAX_POSITION, MAX_STOCKS, MIN_STOCKS, RULES_URL, MAX_AGENTS, MAX_RETRIES,
)
from ithaca_quant.data import demo_market_data, download_market_data, parse_tickers
from ithaca_quant.incremental import refresh_market, completed_daily_only
from ithaca_quant.market_cache import config_key, load_screen, save_screen, age_seconds
from ithaca_quant.fundamentals import fetch_company_facts, public_quarterly_snapshot, yahoo_latest_quarterly
from ithaca_quant.news_archive import archive_headlines, recorded_headlines
from ithaca_quant.universe import fetch_current_universe, pick_scan_symbols, screen_candidates
from ithaca_quant.quotes import alpaca_iex_quotes, yahoo_latest_quotes, age_minutes
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.leaderboard import RANKING_MODES, rank_stocks, leaderboard_display, boom_model_quality
from ithaca_quant.metadata import add_metadata, fetch_company_metadata, load_company_metadata, market_cap_bucket
from ithaca_quant.portfolio import historical_risk, simulate_buy_hold, validate_allocations
from ithaca_quant.signals import plan_signals
from ithaca_quant.news import fetch_news, news_context
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
def cached_panel(close: pd.DataFrame, volume: pd.DataFrame, horizon: int, fundamentals=None, news=None):
    return build_panel(close, volume, horizon, fundamentals=fundamentals, news=news)


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


st.title(f"📈 Ithaca Quant v{APP_RELEASE}")
st.caption("Research-grade workflow prototype · Educational forecasts · Virtual portfolio only")
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
    "Workspace", ["⚡ Instant stock explorer", "🌐 Full-market dashboard"],
    horizontal=True, key="workspace_mode",
    help="Instant explorer analyzes only one symbol. Full-market dashboard runs the broad NYSE/Nasdaq scanner.",
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
    return fetch_news(symbol, company)


@st.cache_data(ttl=15 * 60, show_spinner="Generating sourced AI news commentary…")
def cached_ai_news_summary(symbol: str, report: dict, model: str, _server_api_key: str):
    return summarize_stock_news(symbol, report, api_key=_server_api_key, model=model)


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Loading dated SEC quarterly reports…")
def cached_sec_quarters(symbol: str, contact: str):
    facts, company = fetch_company_facts(symbol, contact)
    return public_quarterly_snapshot(facts), company


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
        sec_error = ""
        if mode != "Synthetic demo":
            contact = server_sec_contact()
            if contact:
                try:
                    sec_snapshot, sec_company = cached_sec_quarters(selected, contact)
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
                {selected: sec_snapshot} if sec_snapshot is not None and not sec_snapshot.empty else None,
                {selected: archive_rows} if archive_rows is not None and not archive_rows.empty else None)
            if single_panel.empty:
                raise ValueError("fewer than 60 valid feature-history sessions")
            point = single_panel["date"].max()
            single_rank = cached_ranking(single_panel, point, fast_mode, boom_return)
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
        model_type = "Daily ensemble (SPY-relative; illustrative 0% SPY return)"
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
            plotted_target = float(chart_prices.iloc[-1]) * (1 + float(model_row["forecast_excess"]))

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
                st.caption("This is a **one-trading-session SPY-relative ML forecast**, displayed as a hypothetical price assuming 0% SPY movement. It is not an hourly forecast and does not appear as a dotted line on today's chart. The next session may be a market holiday.")
            else:
                nx1.metric("Next-session return", "Unavailable")
                nx2.metric("Next-session price", "Unavailable")
                nx3.metric("Daily model", "Needs valid data")
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
            st.caption(f"*Daily-model price illustration assumes **0% SPY return** over the next "
                       f"{daily_model_horizon} sessions. The intraday dotted line, where shown, "
                       "does NOT use this daily model. Boom probabilities are unverified without independent "
                       "calibration; annual volatility is not a maximum-loss estimate. Single-stock models "
                       "may differ from full-market rankings.")
        st.divider()
        st.subheader("🧠 Financial filing and news evidence")
        if sec_snapshot is not None and not sec_snapshot.empty:
            st.markdown("**Official SEC quarterly reports (filed-date-aware):**")
            rows = sec_snapshot.tail(5)[["period_end", "filed", "revenue_usd", "net_income_usd", "revenue_yoy", "net_margin"]].copy()
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
        st.caption("News is retrieved automatically for the searched stock (cached 2 minutes). "
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
                 "Caution": "SPY assumed unchanged; neither is a validated price target"},
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
    rank = cached_ranking(panel, asof, fast_mode, boom_return)
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

@st.cache_data(ttl=2 * 60, show_spinner="Fetching recent publisher headlines…")
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
    st.markdown("**📰 Current-news sensitivity ranking (top-five research subset)**")
    st.caption("Select up to the first five modeled leaders to fetch dated Yahoo Finance, "
               "Fox Business, and ABC News headlines. A capped news scenario then modifies "
               "the **illustrative** return and boom-event estimate and reorders only the "
               "ANALYZED subset. Stocks without fetched headlines have no news adjustment. "
               "This is not an independently tested news-trained stock ranking.")
    news_data_key = (tuple(tickers), str(asof.date()), horizon,
                     tuple((str(rec['ticker']), round(float(rec['forecast_excess']), 6))
                           for _, rec in leaders.head(5).iterrows()))
    if st.button("📰 Analyze top five with current news", key="leader_news_fetch"):
        news_views = []
        for _, item in leaders.head(5).iterrows():
            symbol = str(item['ticker'])
            company = str(item.get('company_name') or symbol)
            try:
                stories, feed_errors = cached_publisher_news(symbol, company)
            except Exception as exc:
                stories, feed_errors = [], [f"Request failed: {type(exc).__name__}"]
            report = analyze_news(stories, symbol, company)
            base_p = item.get('prob_boom')
            compare = news_adjusted_estimates(float(item['forecast_excess']),
                float(base_p) if pd.notna(base_p) else None,
                float(item['vol_20']), horizon, report)
            news_views.append({
                'Ticker': symbol, 'Base AI excess return': compare['base_excess'],
                'News sensitivity': compare['news_shift'],
                'News-adjusted scenario': compare['scenario_excess'],
                'Base boom estimate': compare['base_boom'],
                'News boom scenario': compare['scenario_boom'],
                'Historical risk 1σ': compare['historical_sigma'],
                'News stress 1σ': compare['illustrative_stress_sigma'],
                'News language': report['label'],
                'Headlines': report['n'], 'Publishers': report['source_count'],
                'Feed issues': '; '.join(feed_errors),
            })
        st.session_state['leader_news_context_v13'] = news_views
        st.session_state['leader_news_key_v13'] = news_data_key
    if st.session_state.get('leader_news_key_v13') == news_data_key:
        top_news = pd.DataFrame(st.session_state.get('leader_news_context_v13', []))
        if not top_news.empty:
            top_news = top_news.sort_values('News-adjusted scenario', ascending=False).reset_index(drop=True)
            top_news.insert(0, 'News-subset rank', range(1, len(top_news)+1))
            shown_news = top_news.copy()
            for col in ('Base AI excess return', 'News sensitivity', 'News-adjusted scenario',
                        'Base boom estimate', 'News boom scenario',
                        'Historical risk 1σ', 'News stress 1σ'):
                shown_news[col] = pd.to_numeric(shown_news[col], errors='coerce').map(
                    lambda v: f"{v:+.2%}" if pd.notna(v) else "Unavailable")
            st.dataframe(shown_news, hide_index=True, use_container_width=True)
            st.caption("The news-driven ranking covers ONLY the analyzed subset; it does not "
                       "re-sort all 600 modeled stocks. Neither scenario nor boom estimates "
                       "are historically calibrated news forecasts. CSV values are decimal fractions.")
            st.download_button('Download news-subset scenarios CSV',
                top_news.to_csv(index=False).encode('utf-8'),
                file_name='ithaca_news_scenarios.csv', mime='text/csv', key='leader_news_export')
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
