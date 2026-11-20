"""Conservative same-company news-event clustering.

A syndicated event gets one vote even if five publishers report it. Event
identity depends on event type, key entities / quarter, content tokens and
publication proximity; identical keywords alone are NOT sufficient evidence.
There is no claim that this is an LLM fact-checker or a comprehensive feed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

EVENT_TYPES = {
    'acquisition': r'\b(?:acquir(?:e|es|ed|ing)|acquisition|merg(?:e|er|es|ed)|takeover|buyout|buys|buying|purchase(?:s|d)?)\b',
    'earnings': r'\b(?:earnings|revenue|profit|eps|quarterly|quarter|results|beat(?:s)? estimates|miss(?:es)? estimates)\b',
    'guidance': r'\b(?:guidance|outlook|forecasts?|raises forecast|cuts forecast)\b',
    'analyst': r'\b(?:analyst|upgrad(?:e|es|ed)|downgrad(?:e|es|ed)|price target|rating)\b',
    'regulatory': r'\b(?:lawsuit|investigation|sec probe|ftc|antitrust|regulat(?:or|ory))\b',
    'contract': r'\b(?:contract|partnership|customer deal|supply agreement|award)\b',
    'product': r'\b(?:product|launch|approval|clinical trial)\b',
}
STOP = set('the and for with from after before that this will over into amid its their its on to at of in a an as by is are was were has have says said stock shares company inc corp corporation limited holdings reports report announces announced announces new major more big price market rally jumps surges rises gains falls drops latest today shares a deal agreement news'.split())
ACTION_STOP = set('acquisition acquire acquires acquired acquiring merger merges merged takeover buyout buy buys buying purchase purchases purchased'.split())


def event_type(title: str) -> str:
    s = str(title).lower()
    for k, p in EVENT_TYPES.items():
        if re.search(p, s):
            return k
    return 'general'


def keywords(title: str, company: str = '') -> set[str]:
    words = re.findall(r'[a-z0-9]+', str(title).lower())
    company_tokens = set(re.findall(r'[a-z0-9]+', company.lower()))
    return {w for w in words if len(w) >= 3 and w not in STOP and w not in company_tokens}


def _quarter(title: str) -> str:
    found = re.search(r'\bq\s*([1-4])\b|\b(?:first|second|third|fourth)\s+quarter\b', title.lower())
    if not found:
        return ''
    if found.group(1):
        return 'q' + found.group(1)
    return {'first quarter':'q1','second quarter':'q2','third quarter':'q3','fourth quarter':'q4'}[found.group(0)]


def _deal_target(title: str, company: str = '') -> str:
    """Extract conservative named counterparty token for explicit deals."""
    text = str(title).lower()
    patterns = [r'\b(?:acquir(?:e|es|ed|ing)|buy(?:s|ing)?|purchas(?:e|es|ed)|takeover of)\s+(?:the\s+)?([\w.-]+)',
                r'\b(?:acquisition of|merger with|deal to buy)\s+([\w.-]+)']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match and match.group(1) not in STOP | ACTION_STOP and match.group(1) not in set(company.lower().split()):
            return match.group(1)
    return ''


def _same_event(a: dict, b: dict, company: str = '') -> bool:
    at, bt = event_type(a['title']), event_type(b['title'])
    if at != bt:
        return False
    da, db = a.get('published_utc'), b.get('published_utc')
    if not isinstance(da, datetime) or not isinstance(db, datetime) or not da.tzinfo or not db.tzinfo:
        return False
    # Deals can remain in headlines longer; do not merge separate announcements weeks apart.
    if abs((da - db).total_seconds()) > (10 if at == 'acquisition' else 3) * 86400:
        return False
    qa, qb = _quarter(a['title']), _quarter(b['title'])
    if qa and qb and qa != qb:
        return False
    if at == 'acquisition':
        ta, tb = _deal_target(a['title'], company), _deal_target(b['title'], company)
        if ta and tb and ta != tb:
            return False
        if ta and tb and ta == tb:
            return True
    ak, bk = keywords(a['title'], company), keywords(b['title'], company)
    intersection = len(ak & bk)
    if not ak or not bk:
        return False
    # Need specific shared content; pure generic earnings words aren't sufficient.
    threshold = 0.85 if at in ("product", "contract", "regulatory", "general") else 0.6
    return intersection >= 2 and (intersection / min(len(ak), len(bk))) >= threshold


def deduplicate_events(articles: list[dict], *, ticker: str = '', company: str = '') -> list[dict]:
    """Return one article per likely real-world event, preserving cross-source provenance.

    Newest dated article represents a cluster. `event_sources` and
    `event_coverage_count` retain publisher coverage without inflating event counts.
    Different acquisitions / different quarters remain separate.
    """
    valid = [dict(a) for a in articles if isinstance(a.get('published_utc'), datetime)
             and a['published_utc'].tzinfo is not None and str(a.get('title', '')).strip()]
    valid.sort(key=lambda x: x['published_utc'], reverse=True)
    groups: list[list[dict]] = []
    for item in valid:
        group = next((g for g in groups if any(_same_event(item, old, company) for old in g)), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    result = []
    for group in groups:
        representative = dict(group[0])
        # Preserve provenance if a batch already contains grouped events from
        # the persistent cache; do not turn five reporters into one source.
        sources = set()
        total_coverage = 0
        for item in group:
            sources.update(str(src).strip() for src in (item.get('event_sources') or
                           [item.get('publisher')]) if src)
            total_coverage += max(1, int(item.get('event_coverage_count') or 1))
        representative['event_sources'] = sorted(sources)
        representative['event_coverage_count'] = total_coverage
        representative['event_type'] = event_type(representative['title'])
        result.append(representative)
    return result
