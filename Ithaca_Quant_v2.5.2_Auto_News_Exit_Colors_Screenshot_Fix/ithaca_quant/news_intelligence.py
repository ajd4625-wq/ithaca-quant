"""Explainable *current-headline* sensitivity analysis for educational scenarios.

This module deliberately does not train on recent headlines or call the result an
out-of-sample validated return model. Headlines are untrusted and may be stale,
wrong, or irrelevant. Unavailable feeds imply a zero adjustment, not good news.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

import numpy as np

from .news import POS, NEG, headline_score

# Cap the discretionary headline-driven change in projected excess RETURN.
# It is a sensitivity overlay, NOT a measured market/news causal relationship.
MAX_NEWS_SHIFT_20D = 0.012  # 1.2 percentage points for a 20-session forecast
MAX_NEWS_SHIFT_INTRADAY = 0.002  # 0.2 percentage points, only today's headlines


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("News evaluation time must be timezone-aware")
    return value.astimezone(timezone.utc)


def analyze_news(articles: list[dict], ticker: str, company: str = "", *,
                 now: datetime | None = None, max_age_days: int = 7) -> dict[str, Any]:
    """Score timestamped, distinct, recent, source-attributed headlines.

    Uses observable word matching rather than invented story contents. The
    summary keeps per-headline evidence, not just a single opaque sentiment.
    """
    now = _aware_utc(now)
    ticker = ticker.upper().strip()
    seen: set[str] = set()
    rows = []
    company_terms = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", company) if
                     w.lower() not in {"incorporated", "corporation", "company", "limited", "holdings", "class", "common", "stock"}]
    for raw in articles:
        title = str(raw.get("title") or "").strip()[:350]
        url = str(raw.get("url") or "")
        pub = str(raw.get("publisher") or "Unspecified publisher")
        dt = raw.get("published_utc")
        if not title or not url.startswith("https://") or not isinstance(dt, datetime) or dt.tzinfo is None:
            continue
        age = (now - dt.astimezone(timezone.utc)).total_seconds() / 86400
        if not (0 <= age <= max_age_days):
            continue
        canonical = re.sub(r"[^a-z0-9]", "", title.lower())[:140]
        if canonical in seen:
            continue
        seen.add(canonical)
        words = set(re.findall(r"[a-z]+", title.lower()))
        matched_positive = sorted(words & POS)
        matched_negative = sorted(words & NEG)
        sentiment = headline_score(title)
        ticker_named = bool(re.search(rf"(?<![A-Z]){re.escape(ticker)}(?![A-Z])", title.upper()))
        company_named = bool(company_terms) and any(w in words for w in company_terms)
        # Search results can include broad articles. Untagged titles are weak evidence.
        relevance = 1.0 if ticker_named or company_named else 0.4
        weight = math.exp(-age / 2.0) * relevance
        rows.append({
            "publisher": pub, "title": title, "url": url,
            "published_utc": dt.astimezone(timezone.utc),
            "age_days": round(age, 2), "sentiment": sentiment,
            "positive_words": matched_positive, "negative_words": matched_negative,
            "relevance": "matched ticker/company" if relevance == 1.0 else "weak ticker relevance",
            "weight": weight,
            "impact": "Positive words" if sentiment > 0 else "Negative words" if sentiment < 0 else "Mixed/neutral words",
        })
    rows.sort(key=lambda r: r["published_utc"], reverse=True)
    if not rows:
        return {
            "status": "no_recent_verified_headlines", "label": "No recent eligible news",
            "headlines": [], "n": 0, "source_count": 0, "score": 0.0,
            "strength": 0.0, "shift_20d": 0.0,
            "explanation": "No verifiable recent headlines; forecast stays price-data-only.",
            "asof_utc": now,
        }
    weights = [r["weight"] for r in rows]
    weighted = sum(r["sentiment"] / 3 * r["weight"] for r in rows) / max(1e-9, sum(weights))
    coverage = min(1.0, len(rows) / 4.0)
    sources = len({r["publisher"] for r in rows})
    # More than one independent publisher modestly improves evidence weighting.
    source_factor = min(1.0, (0.7 + 0.15 * max(0, sources - 1)))
    strength = max(0.0, min(1.0, coverage * source_factor))
    news_shift = float(np.clip(MAX_NEWS_SHIFT_20D * weighted * strength,
                               -MAX_NEWS_SHIFT_20D, MAX_NEWS_SHIFT_20D))
    label = "Positive headline language" if weighted > 0.12 else "Negative headline language" if weighted < -0.12 else "Mixed/neutral headlines"
    return {
        "status": "available", "label": label, "headlines": rows,
        "n": len(rows), "source_count": sources, "score": round(weighted, 4),
        "strength": round(strength, 4), "shift_20d": news_shift,
        "explanation": (
            f"{len(rows)} recent distinct headlines from {sources} publisher(s); "
            f"word-level tone {weighted:+.2f} on a -1 to +1 scale. "
            "This is a capped sensitivity analysis, not a trained causal news model."
        ),
        "asof_utc": now,
    }


def shift_for_horizon(report: dict, sessions: int) -> float:
    """Extrapolate a bounded news sensitivity to a requested daily horizon."""
    if sessions < 1:
        raise ValueError("sessions must be positive")
    base = float(report.get("shift_20d") or 0.0)
    return float(np.clip(base * math.sqrt(sessions / 20), -0.015, 0.015))


def intraday_news_shift(report: dict, *, now: datetime | None = None) -> float:
    """Intraday overlay only if a usable headline was published today (US ET)."""
    from zoneinfo import ZoneInfo
    now = _aware_utc(now)
    et = ZoneInfo("America/New_York")
    today = now.astimezone(et).date()
    rows = [r for r in report.get("headlines", []) if r["published_utc"].astimezone(et).date() == today]
    if not rows:
        return 0.0
    weight = sum(r["weight"] for r in rows)
    if weight <= 0:
        return 0.0
    score = sum((r["sentiment"] / 3) * r["weight"] for r in rows) / weight
    return float(np.clip(score * MAX_NEWS_SHIFT_INTRADAY * min(1, len(rows) / 3),
                         -MAX_NEWS_SHIFT_INTRADAY, MAX_NEWS_SHIFT_INTRADAY))


def news_adjusted_estimates(base_excess: float, base_boom: float | None,
                            annual_vol: float, horizon: int, report: dict) -> dict:
    """Return baseline and news-sensitivity *scenario* without overwriting model.

    Probability and stress adjustments are UNSUPERVISED HEURISTICS. They must not
    be displayed or exported as calibrated market probabilities or risk forecasts.
    """
    shift = shift_for_horizon(report, horizon)
    base = float(base_excess)
    sigma = max(0.0001, float(annual_vol) * math.sqrt(horizon / 252))
    boom_value = None
    if base_boom is not None and np.isfinite(base_boom):
        p = float(np.clip(base_boom, 0.0, 1.0))
        # Local sensitivity-only transform; not trained probability calibration.
        boom_value = float(np.clip(p + 1.8 * p * (1 - p) * shift / max(0.05, sigma), 0.0, 1.0))
    # Count uncertain headline events as a small, explicitly illustrative shock buffer.
    # This does not estimate worst-case losses or guarantee coverage.
    headline_stress = 0.15 * abs(shift)
    return {
        "base_excess": base, "news_shift": shift,
        "scenario_excess": float(np.clip(base + shift, -0.50, 0.50)),
        "base_boom": float(base_boom) if base_boom is not None and np.isfinite(base_boom) else None,
        "scenario_boom": boom_value,
        "historical_sigma": sigma,
        "illustrative_stress_sigma": sigma + headline_stress,
        "news_status": report.get("status", "unknown"),
    }


def news_breakdown_lines(report: dict, estimates: dict | None, ticker: str) -> list[str]:
    """Plain, reproducible reasons for each number in the news scenario panel."""
    lines = [f"**{ticker} current news:** {report.get('label', 'Unavailable')}. {report.get('explanation', '')}"]
    if estimates is not None:
        lines.extend([
            (f"**Return scenario:** base SPY-relative estimate {estimates['base_excess']:+.2%}; "
             f"news adjustment {estimates['news_shift']:+.2%}; exploratory combined scenario "
             f"{estimates['scenario_excess']:+.2%}."),
            ("**Boom event scenario:** baseline = " +
             (f"{estimates['base_boom']:.1%}" if estimates['base_boom'] is not None else "unavailable") +
             "; headline-adjusted illustration = " +
             (f"{estimates['scenario_boom']:.1%}" if estimates['scenario_boom'] is not None else "unavailable") +
             ". Neither is a verified live probability."),
            (f"**Risk:** historical 1σ = ±{estimates['historical_sigma']:.1%}; "
             f"headline-stress illustration = ±{estimates['illustrative_stress_sigma']:.1%}. "
             "These are not maximum losses or calibrated forecast intervals."),
            "**Buy/sell review dates:** news does not predict exact optimal trade times. "
            "Recheck company announcements and price conditions at the listed review dates.",
        ])
    return lines
