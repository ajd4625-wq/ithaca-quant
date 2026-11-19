"""Local/provider budget guard for scheduled batch jobs; optional hard limits."""
from datetime import datetime, timezone
import sqlite3
from .market_cache import cache_path


def allow_request(name, maximum, window_seconds, path=None, now=None):
    if maximum < 1 or window_seconds < 1:
        raise ValueError('Request limits must be positive')
    epoch = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    with sqlite3.connect(str(path or cache_path()), timeout=15) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS request_log(name TEXT, at REAL)')
        conn.execute('DELETE FROM request_log WHERE at<?', (epoch-86400,))
        count = conn.execute('SELECT COUNT(*) FROM request_log WHERE name=? AND at>?',
                             (name, epoch-window_seconds)).fetchone()[0]
        if count >= maximum:
            return False
        conn.execute('INSERT INTO request_log(name, at) VALUES (?,?)', (name,epoch))
    return True
