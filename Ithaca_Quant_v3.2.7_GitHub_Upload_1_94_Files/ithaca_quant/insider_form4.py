"""Public SEC Form 4 research, strictly *after* EDGAR disclosure.

Only non-derivative P (open-market/private purchases) and S (sales) are
summarized.  A grant, exercise or disposition for taxes is not automatically
an open-market purchase or sale.  The Form 4 is the source of truth; this
module does not infer illegal or advance knowledge of undisclosed trades.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from threading import Lock
from urllib.parse import urlparse
import math
import re
import time
import xml.etree.ElementTree as ET

import requests

from .fundamentals import sec_headers, SEC_COMPANY_TICKERS, cik_from_directory

SEC_BROWSE = 'https://www.sec.gov/cgi-bin/browse-edgar'
SEC_ARCHIVES = 'https://www.sec.gov/Archives/edgar/data'
MAX_RESPONSE_BYTES = 3_000_000
_last_sec_request = 0.0
_sec_lock = Lock()


class SECUnavailable(RuntimeError):
    """SEC source failed or denied access. Do not represent it as no trades."""


def _safe_xml(blob: bytes):
    if not isinstance(blob, bytes) or len(blob) > MAX_RESPONSE_BYTES:
        raise ValueError('SEC XML is too large or not valid bytes')
    if b'<!DOCTYPE' in blob.upper() or b'<!ENTITY' in blob.upper():
        raise ValueError('SEC XML contains unsupported entity declarations')
    return ET.fromstring(blob)


def _get(client, url: str, contact: str, *, params=None, accept='application/xml'):
    # Conservative, process-wide pacing (<= 3/s), under the SEC's <= 10/s ceiling.
    global _last_sec_request
    headers = sec_headers(contact)
    headers['Accept'] = accept
    with _sec_lock:
        remaining = 0.35 - (time.monotonic() - _last_sec_request)
        if remaining > 0:
            time.sleep(remaining)
        _last_sec_request = time.monotonic()
    try:
        response = client.get(url, params=params, headers=headers, timeout=18)
        if response.status_code in (403, 429):
            raise SECUnavailable('SEC access was denied or throttled; retry after a pause')
        response.raise_for_status()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise SECUnavailable('SEC returned an oversized response')
        return response.content
    except (requests.RequestException, ValueError) as exc:
        raise SECUnavailable(f'SEC request unavailable ({type(exc).__name__})') from exc


def parse_atom_filings(blob: bytes, *, max_entries=6):
    """Extract EDGAR accession references; never trust arbitrary Atom URLs."""
    root = _safe_xml(blob)
    entries = []
    for entry in root.findall('.//{*}entry'):
        form_name = (entry.findtext('{*}category') or '').strip()
        title = entry.findtext('{*}title') or ''
        if not (re.search(r'\b4(?:/A)?\b', title) or form_name in ('4', '4/A')):
            continue
        hrefs = [n.attrib.get('href', '') for n in entry.findall('{*}link')]
        accession = None
        archive_cik = None
        filing_link = None
        for href in hrefs + [entry.findtext('{*}id') or '']:
            parsed = urlparse(href)
            if parsed.hostname not in ('www.sec.gov', 'sec.gov'):
                continue
            match = re.search(r'/Archives/edgar/data/(\d+)/(\d[\d-]{16,20})', parsed.path, re.I)
            if match:
                archive_cik = int(match.group(1))
                accession = match.group(2).replace('-', '')
                filing_link = href.split('?', 1)[0] if href.startswith('https://www.sec.gov/') else None
                break
        if not accession or not re.fullmatch(r'\d{18}', accession):
            continue
        filed_raw = entry.findtext('{*}updated') or entry.findtext('{*}published') or ''
        try:
            filed = datetime.fromisoformat(filed_raw.replace('Z', '+00:00')).date().isoformat()
        except ValueError:
            filed = ''
        entries.append({'archive_cik':archive_cik, 'accession':accession,
                        'filing_date':filed, 'amendment':bool(re.search(r'\b4/A\b', title)),
                        'filing_url':filing_link or f'{SEC_ARCHIVES}/{archive_cik}/{accession}/'})
    unique = {row['accession']:row for row in entries}
    return list(unique.values())[:max_entries]


def xml_documents(index_json: dict):
    """Only archive-local XML filenames, excluding SEC stylesheets."""
    items = index_json.get('directory', {}).get('item', [])
    names = []
    for item in items:
        name = str(item.get('name', ''))
        if (re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,150}\.xml', name, re.I)
                and not name.lower().startswith(('filingsummary', 'metadata', 'xsl'))):
            names.append(name)
    names.sort(key=lambda n: (not any(w in n.lower() for w in ('form4', 'ownership', 'primary', 'doc4')), n))
    return names[:7]


def _value(node, path):
    el = node.find(path)
    return (el.text or '').strip() if el is not None else ''


def _as_positive(value):
    try:
        v = float(str(value).replace(',', ''))
        return v if math.isfinite(v) and v >= 0 else None
    except (ValueError, TypeError):
        return None


def parse_ownership_xml(blob: bytes, *, expected_cik: int, ticker: str,
                        filing_date: str, filing_url: str, amended: bool=False):
    """Parse issuer-matched non-derivative cash P/S transactions only."""
    root = _safe_xml(blob)
    if root.tag.rsplit('}', 1)[-1] != 'ownershipDocument':
        return []
    issuer_cik = _value(root, './issuer/issuerCik')
    if not issuer_cik.isdigit() or int(issuer_cik) != int(expected_cik):
        return []  # SEC filing reporting owner != requested company
    issuer = _value(root, './issuer/issuerName')
    owners = root.findall('./reportingOwner')
    if not owners:
        return []
    owner_names = [_value(o, './reportingOwnerId/rptOwnerName') for o in owners]
    roles = []
    for owner in owners:
        relation = owner.find('./reportingOwnerRelationship')
        if relation is None: continue
        role = []
        if _value(relation, 'isOfficer').lower() in ('1', 'true'):
            role.append(_value(relation, 'officerTitle') or 'Officer')
        if _value(relation, 'isDirector').lower() in ('1', 'true'):
            role.append('Director')
        if _value(relation, 'isTenPercentOwner').lower() in ('1', 'true'):
            role.append('10% owner')
        if role: roles.append(', '.join(role))
    rows = []
    for trans in root.findall('./nonDerivativeTable/nonDerivativeTransaction'):
        code = _value(trans, './transactionCoding/transactionCode').upper()
        ad = _value(trans, './transactionAmounts/transactionAcquiredDisposedCode/value').upper()
        if (code, ad) not in (('P', 'A'), ('S', 'D')):
            continue
        shares = _as_positive(_value(trans, './transactionAmounts/transactionShares/value'))
        price = _as_positive(_value(trans, './transactionAmounts/transactionPricePerShare/value'))
        traded = _value(trans, './transactionDate/value')
        if not shares or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', traded):
            continue
        rows.append({'ticker':ticker.upper(), 'issuer':issuer, 'owner':'; '.join(filter(None,owner_names)),
                     'role':'; '.join(roles) or 'Not specified',
                     'type':'Purchase' if code == 'P' else 'Sale', 'transaction_code':code,
                     'shares':shares, 'price':price, 'value_usd':round(price * shares, 2) if price is not None else None,
                     'trade_date':traded, 'filed_date':filing_date, 'amended':amended,
                     'filing_url':filing_url})
    return rows


def deduplicate_amendments(rows: list[dict]):
    """Retain latest filing for matching transaction details, not repeated amendments."""
    seen = {}
    for item in sorted(rows, key=lambda r:(r.get('filed_date',''), r.get('amended',False))):
        key = (item.get('ticker'), item.get('owner'), item.get('type'),
               item.get('trade_date'), item.get('shares'), item.get('price'))
        seen[key] = item
    return sorted(seen.values(), key=lambda r: (r.get('filed_date',''), r.get('trade_date','')), reverse=True)


def ticker_directory(contact, *, client=None):
    response = _get(client or requests, SEC_COMPANY_TICKERS, contact, accept='application/json')
    try:
        return __import__('json').loads(response)
    except (ValueError, UnicodeError) as exc:
        raise SECUnavailable('Could not read the SEC ticker directory') from exc


def fetch_form4_ticker(ticker, contact, *, directory=None, client=None, max_filings=5):
    """Read recent public filings for a single ticker; no ticker guessing.

    Result: list of transactions.  An empty list means feed/index responded
    successfully but no supported P/S documents were found in queried entries.
    """
    client = client or requests
    mapping = directory if directory is not None else ticker_directory(contact, client=client)
    cik, _ = cik_from_directory(mapping, ticker)
    if cik is None:
        raise ValueError(f'{ticker}: ticker is not listed in SEC issuer directory')
    atom = _get(client, SEC_BROWSE, contact, params={
        'action':'getcompany', 'CIK':str(cik), 'type':'4',
        'owner':'only', 'count':str(max(10, min(40, max_filings*4))), 'output':'atom'})
    filings = parse_atom_filings(atom, max_entries=max_filings)
    results = []
    for f in filings:
        base = f'{SEC_ARCHIVES}/{f["archive_cik"]}/{f["accession"]}'
        index_bytes = _get(client, base+'/index.json', contact, accept='application/json')
        try:
            index_data = __import__('json').loads(index_bytes)
        except (ValueError, UnicodeError) as exc:
            raise SECUnavailable('SEC archive document list unavailable') from exc
        for name in xml_documents(index_data):
            body = _get(client, base+'/'+name, contact)
            try:
                records = parse_ownership_xml(body, expected_cik=cik, ticker=ticker,
                                               filing_date=f['filing_date'], filing_url=f['filing_url'],
                                               amended=f['amendment'])
            except ET.ParseError:
                continue  # some filings include unrelated XML; try next file
            if records:
                results.extend(records)
                break
    return deduplicate_amendments(results)


def summarize_insider_activity(rows: list[dict], *, today=None, recent_days=30):
    """Pure informational labels, NOT a trading recommendation."""
    today = today or date.today()
    cutoff = today - timedelta(days=recent_days)
    eligible = []
    for r in rows:
        try:
            filed = date.fromisoformat(r['filed_date'])
            if cutoff <= filed <= today:
                eligible.append(r)
        except (TypeError, ValueError, KeyError):
            continue
    purchases = [r for r in eligible if r['type'] == 'Purchase']
    sales = [r for r in eligible if r['type'] == 'Sale']
    distinct_buyers = len({r['owner'] for r in purchases if r.get('owner')})
    known_buy_value = sum(r['value_usd'] for r in purchases if r.get('value_usd') is not None)
    known_sell_value = sum(r['value_usd'] for r in sales if r.get('value_usd') is not None)
    if purchases and sales:
        signal, color = 'Mixed disclosed activity', 'YELLOW'
    elif distinct_buyers >= 2:
        signal, color = 'Multiple insiders reported purchases', 'GREEN'
    elif purchases:
        signal, color = 'Reported insider purchase', 'GREEN'
    elif sales:
        signal, color = 'Reported insider sale — review context', 'YELLOW'
    else:
        signal, color = 'No qualifying recent P/S found', 'NEUTRAL'
    return {'signal':signal, 'color':color, 'purchases':len(purchases), 'sales':len(sales),
            'distinct_buyers':distinct_buyers, 'buy_value_known':known_buy_value,
            'sale_value_known':known_sell_value, 'filed_rows':len(eligible)}
