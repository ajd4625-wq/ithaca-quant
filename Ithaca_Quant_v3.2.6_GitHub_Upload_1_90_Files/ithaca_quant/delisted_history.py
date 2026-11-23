"""Evidence-first SEC delisting register and historical-price/outcome coverage audit.

SEC Forms 25/25-NSE are evidence of an exchange delisting *filing* for
an identified registrant, NOT proof of a common-share's effective delisting,
last price, cash merger consideration or delisting return. Form 15 signals
SEC deregistration, not necessarily a delisting. No survival/return inference.

Official SEC submissions.zip can expose additional older history in `files`;
unless supplied, those filings are marked incomplete. The SEC's CIK is an
ISSUER ID and may cover multiple share classes, which we never collapse into
an invented security-specific event.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
import json
import re
from zipfile import ZipFile

import numpy as np
import pandas as pd

DEL_FORM = {'25', '25-NSE'}
DEREG_FORM = {'15', '15-12B', '15-12G', '15-15D', '15F-12B', '15F-12G', '15F-15D'}
ALL_FORMS = DEL_FORM | DEREG_FORM
CSV_FIELDS = ('cik', 'issuer_name', 'form', 'filing_date', 'accession',
              'filing_url', 'event_category', 'source', 'older_filings_missing')
MAX_JSON_BYTES = 75_000_000


def cik_id(raw):
    value = str(raw).strip()
    if not re.fullmatch(r'\d{1,10}', value):
        raise ValueError('CIK must be a 1-10 digit issuer ID, not a ticker')
    return value.zfill(10)


def _filings_from_columnar(record, cik, name, older_missing):
    if not isinstance(record, dict):
        raise ValueError('Invalid SEC filings record')
    required = {'form', 'filingDate', 'accessionNumber'}
    if not required.issubset(record):
        raise ValueError('SEC record lacks a form, filing date or accession')
    cols = {k: record[k] for k in required}
    sizes = {len(v) for v in cols.values() if isinstance(v, list)}
    if len(sizes) != 1 or len(cols) != len([v for v in cols.values() if isinstance(v, list)]):
        raise ValueError('Inconsistent SEC columnar filing lengths')
    result = []
    for form, day, accession in zip(cols['form'], cols['filingDate'], cols['accessionNumber']):
        form = str(form).strip().upper()
        if form not in ALL_FORMS:
            continue
        date = pd.to_datetime(day, errors='coerce')
        if pd.isna(date) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', str(accession)):
            raise ValueError('Invalid SEC delisting/deregistration evidence')
        acc = str(accession)
        result.append({
            'cik': cik, 'issuer_name': name, 'form': form,
            'filing_date': date.strftime('%Y-%m-%d'), 'accession': acc,
            'filing_url': f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace("-", "")}/',
            'event_category': 'EXCHANGE_DELISTING_FILING' if form in DEL_FORM else 'SEC_DEREGISTRATION_FILING',
            'source': 'SEC_EDGAR_SUBMISSIONS', 'older_filings_missing': bool(older_missing),
        })
    return result


def extract_sec_events(submission: dict, *, older_parts: list[dict] | None = None) -> list[dict]:
    """Parse official company submission JSON; never infer market outcome.

    `older_parts` are actual fetched contents of the SEC's `filings.files`
    references, not guessed synthetic extensions.
    """
    if not isinstance(submission, dict) or not isinstance(submission.get('filings'), dict):
        raise ValueError('Expected official SEC company submission JSON')
    cik = cik_id(submission.get('cik'))
    name = str(submission.get('name') or '').strip()
    if not name:
        raise ValueError('Missing registrant name')
    filings = submission['filings']
    extras = filings.get('files') or []
    if not isinstance(extras, list):
        raise ValueError('Unexpected SEC filing history extension listing')
    older_missing = bool(extras) and (older_parts is None or len(older_parts) < len(extras))
    results = _filings_from_columnar(filings.get('recent') or {}, cik, name, older_missing)
    for part in older_parts or []:
        results.extend(_filings_from_columnar(part, cik, name, older_missing))
    # De-dup by filing accession, not ticker or filing date.
    observed = {}
    for row in results:
        key = (row['cik'], row['accession'])
        if key in observed and observed[key]['form'] != row['form']:
            raise ValueError('Conflicting SEC form type for one accession')
        observed[key] = row
    return sorted(observed.values(), key=lambda x: (x['filing_date'], x['cik'], x['accession']))


def _safe_zip_member(name):
    # Official SEC bulk ZIP paths should be filer JSON files only. No arbitrary
    # path traversal or extension names are accepted in the default ingestion.
    return bool(re.fullmatch(r'(?:submissions/)?CIK\d{1,10}\.json', name, flags=re.I))


def iter_bulk_submissions(path: str | Path):
    """Stream SEC submissions ZIP, enforcing per-file size/path limits."""
    with ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if not _safe_zip_member(info.filename):
                raise ValueError(f'Unexpected filename in SEC bulk submission archive: {info.filename}')
            if info.file_size > MAX_JSON_BYTES:
                raise ValueError('SEC filer JSON exceeds configured size limit')
            with z.open(info) as f:
                data = f.read(MAX_JSON_BYTES + 1)
            if len(data) > MAX_JSON_BYTES:
                raise ValueError('SEC filer JSON too large')
            yield json.loads(data)


def _safe_event_rows(events):
    data = pd.DataFrame(events, columns=list(CSV_FIELDS))
    if data.empty:
        return data
    for col in ('cik', 'issuer_name', 'form', 'filing_date', 'accession', 'filing_url', 'event_category'):
        if data[col].isna().any():
            raise ValueError(f'Empty SEC event evidence field: {col}')
    data['cik'] = data['cik'].map(cik_id)
    data['filing_date'] = pd.to_datetime(data['filing_date'], errors='coerce')
    if data.filing_date.isna().any():
        raise ValueError('Invalid SEC filing date')
    if (~data.form.isin(ALL_FORMS)).any():
        raise ValueError('Unrecognized SEC form type')
    if data.duplicated(['cik', 'accession']).any():
        raise ValueError('Duplicated SEC filing accession')
    data['filing_date'] = data.filing_date.dt.strftime('%Y-%m-%d')
    return data.sort_values(['filing_date', 'cik', 'accession']).reset_index(drop=True)


def build_sec_register(submissions, out: str | Path, *, input_reference: str,
                       collection_complete=False, older_parts_complete=False) -> dict:
    """Write evidence index and audit manifest to a private directory.

    `collection_complete` only describes whether all targeted source records
    were supplied. Neither this nor a SHA-256 verifies US stock universe coverage.
    """
    out = Path(out)
    all_events = []
    count = 0
    issuers_with_extra_history = 0
    for submission in submissions:
        count += 1
        supplied_older = submission.pop("__ithaca_older_parts", None)
        filings = submission.get('filings') or {}
        if filings.get('files'):
            issuers_with_extra_history += 1
        all_events.extend(extract_sec_events(submission, older_parts=supplied_older))
    frame = _safe_event_rows(all_events)
    out.mkdir(parents=True, exist_ok=True)
    raw = frame.to_csv(index=False).encode('utf-8')
    dest = out/'sec_delisting_events.csv'
    tmp = dest.with_suffix('.tmp')
    tmp.write_bytes(raw); tmp.replace(dest)
    incomplete = bool(issuers_with_extra_history) and not older_parts_complete
    summary = {
        'format':'ithaca-delisting-evidence-v1',
        'source':'SEC EDGAR submissions', 'input_reference':input_reference,
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'issuers_scanned':count,
        'events_total':len(frame),
        'form25_events':int(frame.form.isin(DEL_FORM).sum()) if not frame.empty else 0,
        'form15_deregistration_events':int(frame.form.isin(DEREG_FORM).sum()) if not frame.empty else 0,
        'issuers_with_older_file_references':issuers_with_extra_history,
        'all_targeted_issuer_files_supplied':bool(collection_complete),
        'older_filing_histories_complete':bool(not incomplete and collection_complete),
        'historical_listings_verified':False,
        'security_class_verified':False,
        'historical_prices_verified':False,
        'terminal_investment_payoffs_verified':False,
        'complete_us_delisted_stock_dataset':False,
        'events_csv_sha256':sha256(raw).hexdigest(),
        'limitations':[
            'Form 25 is issuer-level filing evidence, not an authenticated common-share delisting outcome.',
            'Form 15 deregistration is NOT interchangeable with exchange delisting.',
            'CIKs identify registrants, not individual stock classes; no ticker or security ID is inferred.',
            'Filing date is not automatically the last trading date or the settlement date.',
            'SEC submissions do not provide historical market prices, exchange membership, or final investor payoffs.',
            'Older filings referenced in filings.files may be missing from this snapshot.' if incomplete else
            'Filing history depends on the completeness of the supplied SEC archive.',
        ],
    }
    mp = out/'sec_delisting_manifest.json'
    temp = mp.with_suffix('.tmp')
    temp.write_text(json.dumps(summary, indent=2));temp.replace(mp)
    return summary


def load_sec_register(directory: str | Path) -> pd.DataFrame:
    base = Path(directory)
    manifest = json.loads((base/'sec_delisting_manifest.json').read_text())
    if manifest.get('format') != 'ithaca-delisting-evidence-v1':
        raise ValueError('Unexpected SEC register format')
    raw = (base/'sec_delisting_events.csv').read_bytes()
    if sha256(raw).hexdigest() != manifest.get('events_csv_sha256'):
        raise ValueError('SEC events file failed checksum validation')
    return _safe_event_rows(pd.read_csv(BytesIO(raw), dtype={'cik':'string'}, keep_default_na=False).to_dict('records'))


def audit_delisting_coverage(bundle, events: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Compare issuer SEC events to a validated PIT market archive, conservatively.

    IMPORTANT: no inference that every SEC event relates to common shares,
    no fabricated OHLCV rows, and NO replacement for missing payoff records.
    """
    from .historical_archive import HistoricalBundle
    if not isinstance(bundle, HistoricalBundle):
        raise TypeError('Expected validated HistoricalBundle')
    events = _safe_event_rows(events.to_dict('records'))
    master = bundle.security_master.copy()
    if 'cik' not in master:
        raise ValueError('Archive security_master.csv needs evidence-backed CIK values to audit SEC delistings')
    master['cik'] = master.cik.fillna('').astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
    ids = {}
    for sid, group in master.groupby('security_id'):
        ciks = {cik_id(c) for c in group.cik if c and c.lower() != 'nan'}
        if len(ciks) > 1:
            raise ValueError('A permanent security_id cannot map to multiple SEC CIKs')
        if ciks:
            ids[sid] = next(iter(ciks))
    by_cik = {}
    for sid, cik in ids.items():
        by_cik.setdefault(cik, set()).add(sid)
    terminal = bundle.terminal_returns
    terminal_ids = set(terminal.ticker) if terminal is not None else set()
    rows = []
    for ev in events.itertuples(index=False):
        matches = sorted(by_cik.get(ev.cik, []))
        if ev.form in DEREG_FORM:
            status = 'DEREGISTRATION_ONLY_NOT_DELISTING_PROOF'
        elif not matches:
            status = 'CIK_NOT_IN_ARCHIVE_OR_NO_VERIFIED_CIK_LINK'
        elif len(matches) > 1:
            status = 'MULTIPLE_CLASSES_SECURITY_EVENT_UNRESOLVED'
        else:
            status = 'CIK_LINK_ONLY_SHARE_CLASS_NOT_VERIFIED'
        security = matches[0] if len(matches)==1 else ''
        has_prices = bool(security and security in bundle.market.close and
                          bundle.market.close[security].notna().any())
        has_terminal = bool(security and security in terminal_ids)
        rows.append({**dict(zip(CSV_FIELDS, ev)),
                     'matched_security_id':security,
                     'matching_security_id_count':len(matches),
                     'observed_any_archived_prices':has_prices,
                     'has_any_documented_terminal_payoff_rows':has_terminal,
                     'status':status})
    result = pd.DataFrame(rows)
    n25 = sum(r['form'] in DEL_FORM for r in rows)
    not_matched = sum(r['form'] in DEL_FORM and r['matching_security_id_count'] != 1 for r in rows)
    missing_pr = sum(r['form'] in DEL_FORM and not r['observed_any_archived_prices'] for r in rows)
    missing_out = sum(r['form'] in DEL_FORM and not r['has_any_documented_terminal_payoff_rows'] for r in rows)
    totals = {
        'events_checked':len(rows), 'form25_events_checked':n25,
        'form25_without_single_security_match':not_matched,
        'form25_without_archived_price_history':missing_pr,
        'form25_without_any_documented_terminal_payoff':missing_out,
        'delisting_investment_outcomes_complete':False,
        'survivorship_bias_eliminated':False,
        'note':'Payoff rows for one signal date do not establish complete outcome coverage. SEC filings cannot certify common-share status, listing history or realized return.',
    }
    return result, totals
