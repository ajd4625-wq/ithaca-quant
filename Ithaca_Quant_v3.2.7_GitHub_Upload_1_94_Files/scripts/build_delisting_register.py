"""Build SEC delisting evidence index, optionally audit a private PIT archive.

Recommended: use the SEC's official freely available bulk submissions.zip:
  SEC_CONTACT_EMAIL=real-contact@example.org python scripts/build_delisting_register.py \\
    --download-sec-bulk --out .ithaca_delistings
Or use a local SEC bulk submissions.zip:
  python scripts/build_delisting_register.py --sec-submissions-zip private/submissions.zip \\
    --out .ithaca_delistings --audit-archive private/history.zip

NOTE: an event registry is NOT a complete delisted-stock price/payoff archive.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import requests
import re
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ithaca_quant.delisted_history import iter_bulk_submissions, build_sec_register, load_sec_register, audit_delisting_coverage
from ithaca_quant.historical_archive import load_historical_archive

SEC_BULK_URL = 'https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip'
SEC_SUBMISSION_PREFIX = 'https://data.sec.gov/submissions/'


def fetch_older_filings(submission, *, contact, cache, pause=.16, session=None):
    """Fetch ONLY referenced SEC older filing pages, with per-file disk cache.

    A network failure stops the process; partial history is never presented as
    complete. Use SEC fair-access identification and conservative pacing.
    """
    if not contact or '@' not in contact:
        raise ValueError('SEC_CONTACT_EMAIL must identify a real contact')
    session=session or requests
    files=(submission.get('filings') or {}).get('files') or []
    result=[]
    cache.mkdir(parents=True,exist_ok=True)
    for item in files:
        name=item.get('name','') if isinstance(item,dict) else ''
        if not re.fullmatch(r'CIK\d{1,10}-submissions-\d+\.json',name,re.I):
            raise ValueError('Unexpected older SEC submission filename')
        dest=cache/name
        if dest.exists():
            payload=json.loads(dest.read_bytes())
        else:
            resp=session.get(SEC_SUBMISSION_PREFIX+name,timeout=(20,90),
                             headers={'User-Agent':f'Ithaca Quant research ({contact})',
                                      'Accept':'application/json'})
            resp.raise_for_status()
            if len(resp.content)>75_000_000:
                raise ValueError('Older SEC filing page exceeds size limit')
            payload=resp.json()
            tmp=dest.with_suffix('.tmp')
            tmp.write_bytes(resp.content);tmp.replace(dest)
            if pause:time.sleep(pause)
        result.append(payload)
    return result


def with_older_filing_pages(submissions, *, contact, cache, pause=.16):
    """Enrich an issuer stream one by one; never build the full set in RAM."""
    for submission in submissions:
        newer=dict(submission)
        newer['__ithaca_older_parts']=fetch_older_filings(
            newer,contact=contact,cache=cache,pause=pause)
        yield newer


def download_sec_bulk(path:Path, contact:str, *, max_bytes=8*1024**3, session=None):
    """Official, unauthenticated SEC download with identified User-Agent.

    Streams to disk; never commits a partially downloaded ZIP to the target.
    """
    if not contact or '@' not in contact or len(contact) > 254:
        raise ValueError('Set SEC_CONTACT_EMAIL to a real contact email for SEC fair access')
    req = session or requests
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.download')
    try:
        with req.get(SEC_BULK_URL, stream=True, timeout=(20,120),
                     headers={'User-Agent':f'Ithaca Quant academic research ({contact})',
                              'Accept':'application/zip'}) as r:
            r.raise_for_status()
            total=0
            with temp.open('wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if not chunk:
                        continue
                    total+=len(chunk)
                    if total > max_bytes:
                        raise ValueError('SEC bulk file exceeded configured maximum download size')
                    f.write(chunk)
        from zipfile import ZipFile
        with ZipFile(temp) as z:
            if z.testzip() is not None:
                raise ValueError('Corrupt SEC bulk ZIP download')
        temp.replace(path)
    finally:
        if temp.exists(): temp.unlink()
    return path


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    x=p.add_mutually_exclusive_group(required=True)
    x.add_argument('--sec-submissions-zip',type=Path,help='Downloaded official SEC submissions.zip')
    x.add_argument('--download-sec-bulk',action='store_true',help='Download official SEC bulk archive (large)')
    p.add_argument('--out',type=Path,default=Path('.ithaca_delistings'))
    p.add_argument('--audit-archive',type=Path,help='Optional validated historical PIT ZIP; must contain CIK crosswalk')
    p.add_argument('--fetch-older',action='store_true',help='Download SEC older-filing pages referenced in the bulk file (slow, resumable)')
    p.add_argument('--sec-pause',type=float,default=.16,help='Seconds between SEC older-file requests (default 0.16)')
    a=p.parse_args(argv)
    source = a.sec_submissions_zip
    if a.download_sec_bulk:
        email=os.environ.get('SEC_CONTACT_EMAIL','').strip()
        if not email:
            p.error('Set SEC_CONTACT_EMAIL to your genuine contact before accessing EDGAR')
        source=download_sec_bulk(a.out/'submissions.zip',email)
    inputs=iter_bulk_submissions(source)
    if a.fetch_older:
        if not (email := os.environ.get('SEC_CONTACT_EMAIL','').strip()):
            p.error('--fetch-older requires SEC_CONTACT_EMAIL to identify you to the SEC')
        if a.sec_pause < .12:
            p.error('Set --sec-pause >= 0.12 to respect SEC fair access')
        inputs=with_older_filing_pages(inputs,contact=email,cache=a.out/'older_sec_cache',pause=a.sec_pause)
    report=build_sec_register(inputs,a.out,
                              input_reference=f'SEC EDGAR bulk submissions.zip ({source.name})',
                              collection_complete=True,older_parts_complete=a.fetch_older)
    print(json.dumps(report,indent=2))
    if a.audit_archive:
        bundle=load_historical_archive(a.audit_archive)
        compare, metrics=audit_delisting_coverage(bundle,load_sec_register(a.out))
        compare.to_csv(a.out/'delisting_coverage_audit.csv',index=False)
        (a.out/'delisting_coverage_audit.json').write_text(json.dumps(metrics,indent=2))
        print('Coverage audit (not an all-clear):',json.dumps(metrics,indent=2))
    print('Not a complete delisted-stock price/payoff archive. Do not certify survivorship-free backtests from SEC forms alone.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
