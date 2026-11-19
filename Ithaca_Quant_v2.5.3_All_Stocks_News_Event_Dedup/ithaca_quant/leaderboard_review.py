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
FAST_20D_ABSOLUTE = 0.25
FAST_20D_RELATIVE = 0.15
FAST_60D_ABSOLUTE = 0.40
FAST_60D_RELATIVE = 0.25
DEAL_ABSOLUTE = 0.07
DEAL_RELATIVE = 0.05
ACQUISITION_LOOKBACK_DAYS = 45
ENTRY_COLOR_ORDER = {"DARK_GREEN": 0, "GREEN": 1, "YELLOW": 2, "RED": 3}

_DEAL_PATTERN = re.compile(
    r"\b(?:to acquire|agrees? to acquire|acquires?|acquired by|to be acquired|"
    r"merger agreement|merger deal|takeover (?:offer|bid|deal)|"
    r"buyout (?:offer|bid|deal)|acquisition of|announces? (?:an? )?acquisition|"
    r"completes? (?:an? )?acquisition|completed (?:the )?acquisition|"
    r"to buy|buys|purchase of|merges? with|merger with|being acquired)\b",
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


def longer_runup(close: pd.DataFrame, ticker: str, asof: date, *,
                 sessions: int, prepared_history: pd.DataFrame | None = None) -> dict:
    """Measured cumulative price excess over 20 or 60 completed sessions.

    This is not an acquisition detector: it is only a broad anti-chasing screen.
    """
    if sessions not in (20, 60):
        raise ValueError("Supported windows: 20 or 60 sessions")
    frame = prepared_history if prepared_history is not None else _history(close, asof)
    out = {"return": None, "relative": None, "extended": False}
    if ticker not in frame or BENCHMARK not in frame:
        return out
    pair = frame[[ticker, BENCHMARK]].tail(sessions + 1).apply(pd.to_numeric, errors="coerce")
    if len(pair) != sessions + 1 or pair.isna().any().any() or (pair <= 0).any().any():
        return out
    stock = float(pair[ticker].iloc[-1] / pair[ticker].iloc[0] - 1)
    spy = float(pair[BENCHMARK].iloc[-1] / pair[BENCHMARK].iloc[0] - 1)
    limit, rel_limit = ((FAST_20D_ABSOLUTE, FAST_20D_RELATIVE) if sessions == 20
                        else (FAST_60D_ABSOLUTE, FAST_60D_RELATIVE))
    return {"return": stock, "relative": stock - spy,
            "extended": stock >= limit and stock - spy >= rel_limit}


def exit_review_status(row: dict, signal: dict | None, *, price: float | None) -> dict:
    """Independent color/reasons for exit monitoring, never a trading instruction.

    Adjusted daily model closes are compared only with review levels generated
    on the same basis. A missing signal is unknown, not a healthy position.
    """
    signal = signal or {}
    if price is None or price <= 0 or not signal:
        return {"exit_color": "YELLOW", "exit_label": "🟡 EXIT DATA NEEDED",
                "exit_reason": "A usable adjusted close and fresh exit-screen data are required.",
                "exit_level": None, "exit_distance_pct": None}
    excess = _safe_float(row.get("forecast_excess"))
    ma20 = _safe_float(signal.get("ma_gap_20"))
    level = _safe_float(signal.get("review_level"))
    gap = None if level is None or level <= 0 else price / level - 1
    trigger = []
    if str(signal.get("exit_review") or "").upper() == "REVIEW EXIT":
        if ma20 is not None and ma20 < -0.02:
            trigger.append(f"20-day moving-average gap {ma20:+.1%} (below -2%)")
        if excess is not None and excess < -0.02:
            trigger.append(f"modeled SPY-relative return {excess:+.1%} (below -2%)")
        if not trigger:
            trigger.append("model's exit-review condition was triggered")
    if gap is not None and gap <= 0:
        trigger.append(f"adjusted close reached the review level (${level:,.2f})")
    if trigger:
        return {"exit_color": "RED", "exit_label": "🔴 REVIEW EXIT",
                "exit_reason": "; ".join(trigger) + ". Investigate; no automatic sale.",
                "exit_level": level, "exit_distance_pct": gap}
    caution = []
    if excess is None:
        caution.append("missing modeled return")
    elif excess <= 0:
        caution.append(f"weak SPY-relative forecast ({excess:+.1%})")
    if ma20 is not None and ma20 < 0:
        caution.append(f"below 20-day moving average ({ma20:+.1%})")
    if gap is not None and gap <= 0.05:
        caution.append(f"only {gap:+.1%} above price-review level")
    if not signal.get("exit_review"):
        caution.append("no up-to-date exit-review label")
    if caution:
        return {"exit_color": "YELLOW", "exit_label": "🟡 EXIT CAUTION",
                "exit_reason": "; ".join(caution) + ". Review rather than automatically selling.",
                "exit_level": level, "exit_distance_pct": gap}
    return {"exit_color": "GREEN", "exit_label": "🟢 MONITOR",
            "exit_reason": "No active exit-review trigger under the current model screen; not a hold guarantee.",
            "exit_level": level, "exit_distance_pct": gap}


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
                          asof: date, max_age_days: int = ACQUISITION_LOOKBACK_DAYS) -> list[dict]:
    """Find only *dated*, attributed, relevant definitive-looking deal headlines.

    Headlines aren't verified transaction disclosures; the UI uses 'possible'
    and provides a URL for human verification.
    """
    result = []
    seen = set()
    eligible = []
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
        eligible.append(article)
    # Apply temporal/relevance filters BEFORE grouping, so a later article
    # (after `asof`) cannot hide an earlier qualifying announcement.
    from .news_dedupe import deduplicate_events
    for article in deduplicate_events(eligible, ticker=ticker, company=company):
        title = str(article['title']).strip()
        key = re.sub(r"\W+", "", title.lower())[:120]
        if key in seen:
            continue
        seen.add(key)
        local_day = article['published_utc'].astimezone(ZoneInfo("America/New_York")).date()
        result.append({"date": local_day, "title": title, "url": str(article['url']),
                       "publisher": str(article['publisher'])})
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
    exit_check = exit_review_status(row, signal, price=price)
    runup = five_day_runup(close, ticker, asof, prepared_history=prepared_history)
    run20 = longer_runup(close, ticker, asof, sessions=20, prepared_history=prepared_history)
    run60 = longer_runup(close, ticker, asof, sessions=60, prepared_history=prepared_history)
    checked = articles is not None
    acquisitions = acquisition_headlines(articles or [], ticker, company, asof=asof) if checked else []
    # The original implementation accidentally used the *oldest* acquisition.
    # Evaluate all qualifying articles, then prefer an evidenced jump, otherwise
    # the most recent item requiring review. Never use a future article.
    events = [(a, deal_jump_since_announcement(close, ticker, a["date"],
                 asof=asof, prepared_history=prepared_history)) for a in acquisitions]
    with_jump = [(a, e) for a, e in events if e.get("already_jumped")]
    latest_acquisition, event = (max(with_jump, key=lambda x: (x[1].get("deal_relative") or 0, x[0]["date"]))
                                 if with_jump else (events[-1] if events else (None, {})))
    confirmed_chase = bool(event.get("already_jumped"))
    extended = bool(run20["extended"] or run60["extended"])
    caution = ""
    penalty = 0
    if confirmed_chase:
        caution = (f"Possible acquisition already reflected in price: {event['deal_return']:+.1%} "
                   f"since pre-announcement close ({event['deal_relative']:+.1%} versus SPY). "
                   "Research warning, not proof of limited future upside; verify linked headline.")
        penalty = 55
    elif acquisitions:
        caution = ("Recent possible acquisition (past 45 days) requires event-risk review. "
                   "No verified large post-deal jump with available completed sessions; "
                   "cannot assume this is a fresh entry opportunity.")
        penalty = 30
    elif extended:
        selected = (20, run20) if run20["extended"] else (60, run60)
        caution = (f"Already extended over {selected[0]} sessions: {selected[1]['return']:+.1%} "
                   f"({selected[1]['relative']:+.1%} versus SPY). Avoid chasing on a forecast alone; "
                   "a long rally is not proof of overvaluation.")
        penalty = 30
    elif runup["fast_rise"]:
        caution = (f"Large 5-session rise ({runup['return_5d']:+.1%}, "
                   f"{runup['relative_5d']:+.1%} versus SPY). Review price chasing risk.")
        penalty = 18
    elif not checked and light["color"] in ("GREEN", "DARK_GREEN"):
        # Do not certify an unknown acquisition status as a strong buy.
        caution = ("Acquisition/news feeds have not verified this company; "
                   "strong-entry eligibility is withheld until a new cached check succeeds.")
        penalty = 10

    if caution and light["color"] in ("GREEN", "DARK_GREEN"):
        label = ("🟡 ACQUISITION PRICED-IN" if confirmed_chase else
                 "🟡 DEAL REVIEW" if acquisitions else
                 "🟡 AVOID CHASING" if (extended or runup["fast_rise"]) else
                 "🟡 NEWS NOT CHECKED")
        light = {"color": "YELLOW", "label": label, "reason": caution}
    elif caution:
        light = {**light, "reason": f"{light['reason']} {caution}"}

    original = _safe_float(row.get("research_score"))
    priority = None if original is None else max(0.0, original - penalty)
    # Do not let a large pre-announcement research score push an acquisition-
    # inflated stock above ordinary unconfirmed yellow entries. Keep the raw
    # research score as-is: only screening priority and ordering change.
    elevated_chase = bool(confirmed_chase or acquisitions or extended or runup["fast_rise"])
    if priority is not None and elevated_chase:
        priority = min(priority, 20.0 if (confirmed_chase or acquisitions) else 35.0)
    tier = ENTRY_COLOR_ORDER[light["color"]]
    if light["color"] == "YELLOW" and elevated_chase:
        tier = 3  # stronger caution than ordinary yellow WAIT / incomplete news
    if light["color"] == "RED":
        tier = 4  # never promote a red exit-watch over an entry candidate
    if not checked:
        news_label = "Not checked — no acquisition clearance"
    elif acquisitions:
        news_label = (f"Possible deal ({latest_acquisition['date']}) — price reaction "
                      + ("flagged" if confirmed_chase else "under review"))
    else:
        news_label = "No qualifying headline in checked feeds (not a full news audit)"
    return {
        "ticker": ticker, "color": light["color"], "signal_label": light["label"],
        "reason": light["reason"], "return_5d": runup["return_5d"],
        "relative_5d": runup["relative_5d"], "return_20d": run20["return"],
        "relative_20d": run20["relative"], "return_60d": run60["return"],
        "relative_60d": run60["relative"], "acquisition_check": news_label,
        "acquisition_title": latest_acquisition["title"] if latest_acquisition else "",
        "acquisition_url": latest_acquisition["url"] if latest_acquisition else "",
        "deal_return": event.get("deal_return"), "deal_relative": event.get("deal_relative"),
        "possible_priced_in": confirmed_chase, "entry_priority_score": priority,
        "entry_sort_tier": tier,
        "catalyst_screen_penalty": penalty, **exit_check,
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
