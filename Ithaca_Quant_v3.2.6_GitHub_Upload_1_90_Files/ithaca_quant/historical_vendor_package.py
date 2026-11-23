"""Package locally normalized authorized vendor exports using existing audit rules."""
from __future__ import annotations
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from hashlib import sha256
from io import BytesIO
import json

from .historical_archive import FORMAT, MANDATORY, OPTIONAL, load_historical_archive


def package_vendor_archive(source_dir: Path, destination: Path, *, provider: str, source_reference: str):
    names=[x for x in MANDATORY+OPTIONAL if (source_dir/x).exists()]
    if not set(MANDATORY).issubset(names): raise ValueError('Missing required archive tables')
    # The max uncompressed size is enforced by load_historical_archive to avoid
    # quietly attempting a multi-GB Streamlit pivot. No silent truncation.
    files={n:(source_dir/n).read_bytes() for n in names}
    hashes={n:sha256(blob).hexdigest() for n,blob in files.items()}
    manifest={'format':FORMAT,'provider':provider,'source_reference':source_reference,
              'price_basis':'total_return_adjusted_close','sha256':hashes,
              'limits':'This archive is a dated subset of a vendor export, not a universe completeness certificate.'}
    destination.parent.mkdir(parents=True,exist_ok=True)
    buf=BytesIO()
    with ZipFile(buf,'w',ZIP_DEFLATED) as z:
        for name,blob in files.items():z.writestr(name,blob)
        z.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
    # No user ZIP will be persisted if fails structural/integrity validation.
    quality=load_historical_archive(buf.getvalue()).quality
    destination.write_bytes(buf.getvalue())
    return quality
