"""Public Google News RSS headlines, publisher filtering, and transparent news context.

News is NOT a trained forecasting feature: using today's headlines to validate past
predictions would leak future information. Headline sentiment is a research overlay.
"""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlparse
import re
import xml.etree.ElementTree as ET
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import MAX_AGENTS
from .retry import retry_call

PUBLISHERS = {"Yahoo Finance": "finance.yahoo.com", "Fox Business": "foxbusiness.com", "ABC News": "abcnews.go.com"}
POS = {"beats", "surges", "rises", "growth", "profit", "upgrade", "record", "strong", "expands", "wins", "rally", "higher"}
NEG = {"misses", "falls", "drops", "loss", "downgrade", "lawsuit", "investigation", "weak", "cuts", "declines", "lower", "warning"}


def headline_score(title: str) -> int:
    words = set(re.findall(r"[a-z]+", title.lower()))
    return max(-3, min(3, len(words & POS) - len(words & NEG)))


def parse_rss(xml: bytes, publisher: str, limit: int = 12) -> list[dict]:
    root = ET.fromstring(xml)
    results = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
        # Google News wraps links; don't claim the link itself is hosted by the publisher.
        if not title or not url.startswith("https://"):
            continue
        if source and publisher.lower().split()[0] not in source.lower() and not (publisher == "Fox Business" and "fox" in source.lower()):
            continue
        try:
            ts = parsedate_to_datetime(date).astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError):
            ts = None
        results.append({"publisher": publisher, "title": title, "url": url,
                        "published_utc": ts, "sentiment": headline_score(title)})
        if len(results) >= limit:
            break
    return results


def fetch_news(ticker: str, company: str = "", max_per_publisher: int = 8) -> tuple[list[dict], list[str]]:
    """Fetch from Google News RSS indexed by publisher; never fabricate missing headlines."""
    token = re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker.upper())
    if not token:
        raise ValueError("Enter a valid ticker symbol")
    # Company name improves relevance but may be missing; ticker is always included.
    phrase = f'"{company}"' if company and len(company) >= 4 else f'"{ticker}" stock'
    articles, errors = [], []

    def one_publisher(publisher: str, domain: str):
        query = f'{phrase} site:{domain} when:14d'
        url = 'https://news.google.com/rss/search?' + urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        def request():
            response = requests.get(url, timeout=6, headers={"User-Agent": "IthacaQuant/1.3 educational research"})
            response.raise_for_status()
            return response.content
        raw = retry_call(request, usable=bool, retryable=lambda e: not (
            isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code in (401, 403, 429)))
        return parse_rss(raw, publisher, max_per_publisher)

    # Never more than three simultaneous publisher calls; retry_call imposes
    # exactly two application-level retries for each request.
    with ThreadPoolExecutor(max_workers=min(MAX_AGENTS, len(PUBLISHERS))) as pool:
        tasks = {pool.submit(one_publisher, publisher, domain): publisher
                 for publisher, domain in PUBLISHERS.items()}
        for task in as_completed(tasks):
            try:
                articles.extend(task.result())
            except (requests.RequestException, ET.ParseError, ValueError) as exc:
                errors.append(f"{tasks[task]}: {type(exc).__name__}")
    articles.sort(key=lambda x: x['published_utc'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return articles, errors


def news_context(articles: list[dict]) -> dict:
    """Heuristic headline polarity, not a calibrated market prediction."""
    recent = [a for a in articles if a.get('published_utc') is not None and
              0 <= (datetime.now(timezone.utc) - a['published_utc']).total_seconds() <= 14 * 86400]
    if not recent:
        return {"articles": 0, "score": None, "label": "No recent verified headlines"}
    avg = sum(a['sentiment'] for a in recent) / len(recent)
    return {"articles": len(recent), "score": round(avg, 2),
            "label": "Positive headline language" if avg > 0.3 else "Negative headline language" if avg < -0.3 else "Mixed/neutral headlines"}
