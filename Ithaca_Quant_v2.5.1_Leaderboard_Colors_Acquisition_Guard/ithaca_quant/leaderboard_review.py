"""Conservative, point-in-time entry colors and post-announcement chase checks.

No live-news heuristic modifies the trained return model or validates its
historical accuracy. Price-run-up guards are qualitative research screens.
News collection is opt-in and intentionally limited to a small leaderboard
subset to avoid exhausting public RSS endpoints.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math
import re
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import BENCHMARK
from .portfolio_lights import classify_holding

# Transparent, deliberately conservative *review* thresholds, NOT trained
# effects on subsequent returns or claims of mean reversion.
FAST_5D_ABSOLUTE = 0.15
FAST_5D_RELATIVE = 0.10
DEAL_ABSOLUTE = 0.10
DEAL_RELATIVE = 0.08

_DEAL_PATTERN = re.compile(
    r"\b(?:to acquire|agrees? to acquire|acquires?|acquired by|to be acquired|"
    r"merger agreement|merger deal|takeover (?:offer|bid|deal)|"
    r"buyout (?:offer|bid|deal)|acquisition of|announces? (?:an? )?acquisition)\b",
    re.I,
)
_UNCERTAIN_PATTERN = re.compile(
    r"\b(?:rumou?r|speculation|reportedly|could acquire|may acquire|potential (?:merger|acquisition)|"
    r"talks? (?:of|about|to)|considering (?:a|an) (?:merger|acquisition))\b", re.I,
)
_GENERIC_WORDS = {"inc", "incorporated", "corp", "corporation", "company", "holdings", "holding", "ltd", "limited", "class", "the", "group"}


def _safe_float(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def _history(close: pd.DataFrame, asof: date) -> pd.DataFrame:
    """Never look ahead to a price observation later than the model as-of day."""
    if close.empty:
        return pd.DataFrame()
    frame = close.copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_localize(None).normalize()
    frame = frame.loc[frame.index <= pd.Timestamp(asof)].sort_index()
    return frame[~frame.index.duplicated(keep="last")]


def five_day_runup(close: pd.DataFrame, ticker: str, asof: date, *,
                   prepared_history: pd.DataFrame | None = None) -> dict:
    result = {"return_5d": None, "relative_5d": None, "fast_rise": False}
    frame = prepared_history if prepared_history is not None else _history(close, asof)
    if ticker not in frame or BENCHMARK not in frame or frame.empty:
        return result
    pairs = frame[[ticker, BENCHMARK]].tail(6).apply(pd.to_numeric, errors="coerce")
    if len(pairs) != 6 or pairs.isna().any().any() or (pairs <= 0).any().any():
        return result  # No silent gap-filling or use of stale price data.
    start, end = pairs.iloc[-6], pairs.iloc[-1]
    stock_ret = float(end[ticker] / start[ticker] - 1)
    spy_ret = float(end[BENCHMARK] / start[BENCHMARK] - 1)
    result.update(return_5d=stock_ret, relative_5d=stock_ret - spy_ret,
                  fast_rise=(stock_ret >= FAST_5D_ABSOLUTE and
                             stock_ret - spy_ret >= FAST_5D_RELATIVE))
    return result


def _related(title: str, ticker: str, company: str) -> bool:
    text = title.lower()
    if re.search(rf"(?<![a-z0-9]){re.escape(ticker.lower())}(?![a-z0-9])", text):
        return True
    tokens = [w for w in re.findall(r"[a-z0-9]+", company.lower()) if w not in _GENERIC_WORDS]
    if not tokens:
        return False
    # Preserve word boundaries. Avoid matching arbitrary substrings, and don't
    # mistake a generic company name such as 'The Company' for a match.
    name = r"\W+".join(re.escape(t) for t in tokens[:3])
    return bool(re.search(rf"(?<!\w){name}(?!\w)", text))


def acquisition_headlines(articles: list[dict], ticker: str, company: str, *,
                          asof: date, max_age_days: int = 14) -> list[dict]:
    """Find only *dated*, attributed, relevant definitive-looking deal headlines.

    Headlines aren't verified transaction disclosures; the UI uses 'possible'
    and provides a URL for human verification.
    """
    result = []
    seen = set()
    for article in articles:
        stamp = article.get("published_utc")
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "")
        publisher = str(article.get("publisher") or "").strip()
        if not (isinstance(stamp, datetime) and stamp.tzinfo and title and
                url.startswith("https://") and publisher):
            continue
        local_day = stamp.astimezone(ZoneInfo("America/New_York")).date()
        age = (asof - local_day).days
        if not (0 <= age <= max_age_days):
            continue
        if not _DEAL_PATTERN.search(title) or _UNCERTAIN_PATTERN.search(title):
            continue
        if not _related(title, ticker, company):
            continue
        key = re.sub(r"\W+", "", title.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        result.append({"date": local_day, "title": title, "url": url,
                       "publisher": publisher})
    return sorted(result, key=lambda a: a["date"])


def deal_jump_since_announcement(close: pd.DataFrame, ticker: str,
                                 announcement_date: date, *, asof: date,
                                 prepared_history: pd.DataFrame | None = None) -> dict:
    """Return from previous session close to latest close *after* release day.

    Requiring a later completed close avoids claiming an after-close headline
    had already been incorporated into the same day's closing price.
    """
    out = {"deal_return": None, "deal_relative": None, "already_jumped": False}
    history = prepared_history if prepared_history is not None else _history(close, asof)
    if ticker not in history or BENCHMARK not in history:
        return out
    pairs = history[[ticker, BENCHMARK]].apply(pd.to_numeric, errors="coerce").dropna()
    baseline = pairs[pairs.index.date < announcement_date]
    afterwards = pairs[pairs.index.date > announcement_date]
    if baseline.empty or afterwards.empty or pairs.empty or pairs.index[-1] != history.index[-1]:
        return out
    first = baseline.iloc[-1]
    last = pairs.iloc[-1]
    if (first <= 0).any() or last.name <= baseline.index[-1]:
        return out
    s = float(last[ticker] / first[ticker] - 1)
    b = float(last[BENCHMARK] / first[BENCHMARK] - 1)
    out.update(deal_return=s, deal_relative=s - b,
               already_jumped=(s >= DEAL_ABSOLUTE and s - b >= DEAL_RELATIVE))
    return out


def evaluate_candidate(row: dict, signal: dict | None, close: pd.DataFrame, *,
                       asof: date, horizon: int,
                       articles: list[dict] | None = None,
                       company: str = "",
                       prepared_history: pd.DataFrame | None = None) -> dict:
    """Color research rows; a flagged event can *downgrade* but never upgrade.

    Candidate sorting uses an explanatory entry-priority score; the original
    ML forecast and source research score stay unchanged for auditability.
    """
    ticker = str(row["ticker"])
    price = _safe_float(row.get("close"))
    forecast = {
        "asof": asof.isoformat(), "forecast_excess": row.get("forecast_excess"),
        "prob_gain": row.get("prob_gain"), "vol_20": row.get("vol_20"),
        "entry_watch": (signal or {}).get("entry_watch"),
        "exit_review": (signal or {}).get("exit_review"),
        "model_price": price,
        "review_level": (signal or {}).get("review_level"),
    }
    light = classify_holding(forecast, latest_price=price,
                             quote_available=(price is not None and price > 0))
    if horizon != 20 and light["color"] == "DARK_GREEN":
        light = {"color": "GREEN", "label": "🟢 ENTRY WATCH", "reason":
                 "Dark-green thresholds are defined for 20-session forecasts only."}
    runup = five_day_runup(close, ticker, asof, prepared_history=prepared_history)
    checked = articles is not None
    acquisitions = acquisition_headlines(articles or [], ticker, company, asof=asof) if checked else []
    latest_acquisition = acquisitions[0] if acquisitions else None
    event = (deal_jump_since_announcement(close, ticker, latest_acquisition["date"],
                                          asof=asof, prepared_history=prepared_history)
             if latest_acquisition else {})
    confirmed_chase = bool(event.get("already_jumped"))
    # A *completed*, evidence-linked announcement followed by a large stock
    # rise is much stronger 'priced in' context than price movement alone.
    caution = ""
    if confirmed_chase:
        caution = (f"Possible acquisition already reflected in price: {event['deal_return']:+.1%} "
                   f"since the pre-announcement close ({event['deal_relative']:+.1%} versus SPY). "
                   "This is a heuristic, not proof that future upside is limited. Verify linked headline.")
    elif runup["fast_rise"]:
        caution = (f"Large recent 5-session increase ({runup['return_5d']:+.1%}, "
                   f"{runup['relative_5d']:+.1%} versus SPY). Consider whether news is priced in; "
                   "a surge alone does not prove overvaluation.")
    if caution and light["color"] in ("GREEN", "DARK_GREEN"):
        light = {"color": "YELLOW", "label": "🟡 AVOID CHASING", "reason": caution}
    elif caution:
        light = {**light, "reason": f"{light['reason']} {caution}"}
    elif acquisitions and event.get("deal_return") is None and light["color"] in ("GREEN", "DARK_GREEN"):
        light = {"color": "YELLOW", "label": "🟡 VERIFY DEAL REACTION", "reason":
                 "Possible acquisition headline found, but not enough completed post-event sessions to assess its price reaction."}
    # The caution score is NOT a forecast, validated probability or revised
    # research score. Red remains red, and missing inputs remain yellow.
    original = _safe_float(row.get("research_score"))
    priority = None if original is None else max(0.0, original - (35 if confirmed_chase else 15 if runup["fast_rise"] else 0))
    if not checked:
        news_label = "Not checked"
    elif acquisitions:
        news_label = f"Possible deal headline: {latest_acquisition['date']}"
    else:
        news_label = "No qualifying headline in checked feeds"
    return {
        "ticker": ticker, "color": light["color"], "signal_label": light["label"],
        "reason": light["reason"], "return_5d": runup["return_5d"],
        "relative_5d": runup["relative_5d"], "acquisition_check": news_label,
        "acquisition_title": latest_acquisition["title"] if latest_acquisition else "",
        "acquisition_url": latest_acquisition["url"] if latest_acquisition else "",
        "deal_return": event.get("deal_return"),
        "deal_relative": event.get("deal_relative"),
        "possible_priced_in": confirmed_chase, "entry_priority_score": priority,
    }


def add_leaderboard_review(ranked: pd.DataFrame, signals: pd.DataFrame,
                           close: pd.DataFrame, *, asof: date,
                           horizon: int, headlines_by_ticker: dict[str, list[dict]] | None = None) -> pd.DataFrame:
    if ranked.empty:
        return ranked.assign(color=pd.Series(dtype="object"), signal_label=pd.Series(dtype="object"),
                             entry_priority_score=pd.Series(dtype="float64"))
    by_symbol = (signals.set_index("ticker").to_dict("index")
                 if signals is not None and not signals.empty else {})
    news = headlines_by_ticker or {}
    report = []
    prepared = _history(close, asof)  # one O(history) preparation for the whole universe
    for row in ranked.to_dict("records"):
        ticker = str(row["ticker"])
        report.append(evaluate_candidate(row, by_symbol.get(ticker), close,
                                         asof=asof, horizon=horizon,
                                         articles=news.get(ticker),
                                         company=str(row.get("company_name") or ""),
                                         prepared_history=prepared))
    return ranked.merge(pd.DataFrame(report), how="left", on="ticker", validate="one_to_one")
