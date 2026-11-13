"""Versioned SQLite snapshots of market prices and screened universe.

SQLite survives local reruns and app restarts, but hosted Streamlit instances can
lose local files on restart. Never commit the cache or API credentials to Git.
"""
from __future__ import annotations
from datetime import datetime, timezone
from io import StringIO
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import zlib
import pandas as pd
from .data import MarketData

SCHEMA_VERSION = 1


def cache_path(root=None) -> Path:
    directory = Path(root or os.environ.get("ITHACA_CACHE_DIR", str(Path.home() / ".ithaca_quant_cache")))
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "market_cache_v1.sqlite3"


def config_key(namespace: str, symbols, **options) -> str:
    payload = json.dumps({"schema": SCHEMA_VERSION, "namespace": namespace, "symbols": list(symbols),
                          "options": options}, sort_keys=True)
    return namespace + ":" + hashlib.sha256(payload.encode()).hexdigest()


def _db(path):
    conn = sqlite3.connect(str(path), timeout=20)
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("CREATE TABLE IF NOT EXISTS snapshots(key TEXT PRIMARY KEY, kind TEXT NOT NULL, updated TEXT NOT NULL, content BLOB NOT NULL)")
    return conn


def save_snapshot(key: str, kind: str, payload: dict, path=None) -> str:
    raw = json.dumps(payload, allow_nan=False).encode("utf-8")
    data = zlib.compress(raw, level=4)
    if len(data) > 60 * 1024 * 1024:
        raise ValueError("Research snapshot exceeds cache size limit")
    stamp = datetime.now(timezone.utc).isoformat()
    with _db(path or cache_path()) as conn:
        conn.execute("INSERT OR REPLACE INTO snapshots(key,kind,updated,content) VALUES(?,?,?,?)",
                     (key, kind, stamp, data))
    return stamp


def load_snapshot(key: str, kind: str, path=None):
    with _db(path or cache_path()) as conn:
        row = conn.execute("SELECT kind,updated,content FROM snapshots WHERE key=?", (key,)).fetchone()
    if not row or row[0] != kind:
        return None
    try:
        obj = zlib.decompress(row[2])
        if len(obj) > 250 * 1024 * 1024:
            return None
        payload = json.loads(obj)
        stamp = datetime.fromisoformat(row[1])
        return payload, stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, zlib.error):
        return None


def _to_json(df):
    return df.to_json(orient="split", date_format="iso", date_unit="ms")


def _from_json(value, dates=False):
    df = pd.read_json(StringIO(value), orient="split", convert_dates=False)
    if dates:
        ix = pd.to_datetime(df.index, errors="coerce", utc=True)
        df.index = ix.tz_localize(None).normalize()
        df = df.loc[~df.index.isna()].sort_index()
    return df


def save_market(key: str, data: MarketData, path=None):
    return save_snapshot(key, "prices", {"close": _to_json(data.close), "volume": _to_json(data.volume),
                                           "excluded": data.excluded, "source": data.source}, path)


def load_market(key: str, path=None):
    item = load_snapshot(key, "prices", path)
    if item is None:
        return None
    payload, stamp = item
    try:
        prices = _from_json(payload["close"], dates=True)
        volumes = _from_json(payload["volume"], dates=True)
        if "SPY" not in prices or prices.empty:
            return None
        return MarketData(prices, volumes, payload["source"], payload["excluded"]), stamp
    except (KeyError, TypeError, ValueError):
        return None


def save_screen(key, selected, all_screened, downloaded, excluded, path=None):
    return save_snapshot(key, "screen", {"selected": _to_json(selected), "all": _to_json(all_screened),
                                          "downloaded": int(downloaded), "excluded": int(excluded)}, path)


def load_screen(key, path=None):
    item = load_snapshot(key, "screen", path)
    if item is None:
        return None
    payload, stamp = item
    try:
        return (_from_json(payload["selected"]), _from_json(payload["all"]),
                int(payload["downloaded"]), int(payload["excluded"])), stamp
    except (KeyError, TypeError, ValueError):
        return None


def age_seconds(stamp, now=None):
    return max(0, ((now or datetime.now(timezone.utc)) - stamp).total_seconds())


def cache_is_fresh(stamp, seconds, now=None):
    return age_seconds(stamp, now) < seconds
