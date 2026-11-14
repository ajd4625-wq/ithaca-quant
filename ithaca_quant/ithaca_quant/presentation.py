"""Display-only data formatting. Numerical research features are never modified."""
from __future__ import annotations

import numpy as np
import pandas as pd

QUARTER_LABELS = {
    "period_end": "Quarter ended",
    "filed": "Filed with SEC",
    "revenue_usd": "Revenue (USD)",
    "net_income_usd": "Net income (USD)",
    "revenue_yoy": "Revenue growth (YoY)",
    "net_margin": "Net margin",
    "diluted_eps": "Diluted EPS (USD)",
}


def format_money(value: object, *, decimals: int = 0) -> str:
    """Currency with thousands separators; never turn missing facts into $0."""
    try:
        num = float(value)
        if not np.isfinite(num):
            return "Not reported"
        return f"-${abs(num):,.{decimals}f}" if num < 0 else f"${num:,.{decimals}f}"
    except (TypeError, ValueError):
        return "Not reported"


def format_financial_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Human-readable copy of SEC/Yahoo filings, retaining all source numbers."""
    result = frame.copy()
    for col in ("revenue_usd", "net_income_usd"):
        if col in result:
            result[col] = result[col].map(format_money)
    if "diluted_eps" in result:
        result["diluted_eps"] = result["diluted_eps"].map(lambda x: format_money(x, decimals=2))
    for col in ("revenue_yoy", "net_margin"):
        if col in result:
            result[col] = result[col].map(
                lambda x: f"{float(x):+,.1%}" if pd.notna(x) and np.isfinite(float(x)) else "Not reported"
            )
    for col in ("period_end", "filed"):
        if col in result:
            result[col] = pd.to_datetime(result[col], errors="coerce").dt.strftime("%b %d, %Y").fillna("Not reported")
    return result.rename(columns=QUARTER_LABELS)
