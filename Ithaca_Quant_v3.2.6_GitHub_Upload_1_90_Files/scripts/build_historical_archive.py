"""Bundle your legitimate provider exports; NEVER fabricate price or delisting data.

Usage:
  python scripts/build_historical_archive.py ./my_exports ./market_archive.zip \
     --provider 'My Data Vendor' --source-reference 'contract/data extract ID'

Creates SHA-256 checksums for byte-integrity only. Does not verify whether
provider data are genuine, licensed, or complete; use trusted vendor exports.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import sys
from pathlib import Path as _Path
sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from ithaca_quant.historical_archive import FORMAT, MANDATORY, OPTIONAL, load_historical_archive


def package_archive(source_dir: Path, destination: Path, *, provider: str,
                    source_reference: str) -> dict:
    if not provider.strip() or not source_reference.strip():
        raise ValueError('Provider and source_reference are mandatory')
    names = [x for x in MANDATORY + OPTIONAL if (source_dir / x).is_file()]
    if not set(MANDATORY).issubset(names):
        raise ValueError('Supply security_master.csv, price_history.csv, and membership.csv')
    content = {name:(source_dir / name).read_bytes() for name in names}
    manifest = {'format':FORMAT, 'provider':provider.strip(),
                'source_reference':source_reference.strip(),
                'price_basis':'total_return_adjusted_close',
                'sha256':{k:sha256(v).hexdigest() for k,v in content.items()},
                'important':'Checksums prove file consistency, not the accuracy or authenticity of the original provider.'}
    buffer=io.BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as z:
        for name, raw in content.items():
            z.writestr(name,raw)
        z.writestr('manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
    # Reject invalid data before saving anything.
    bundle=load_historical_archive(buffer.getvalue())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(buffer.getvalue())
    return bundle.quality


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_directory',type=Path)
    parser.add_argument('output_zip',type=Path)
    parser.add_argument('--provider',required=True)
    parser.add_argument('--source-reference',required=True)
    args=parser.parse_args()
    print(json.dumps(package_archive(args.source_directory,args.output_zip,
                                    provider=args.provider,source_reference=args.source_reference),indent=2))
