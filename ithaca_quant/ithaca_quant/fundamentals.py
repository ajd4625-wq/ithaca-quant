"""Point-in-time SEC XBRL financial facts for US reporting companies.

SEC's XBRL companyfacts data is public, but standardized fields vary by issuer;
unsupported tags are explicitly missing. Publication is the filing date (not
the quarter end). For daily ML, every fact is available from the NEXT weekday,
conservatively avoiding filings made after the closing bell.
"""
from __future__ import annotations
from datetime import datetime
import re
import pandas as pd
import numpy as np
import requests
from .retry import retry_call

REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet",
)
PROFIT_TAGS = ("NetIncomeLoss", "ProfitLoss")
EPS_TAGS = ("EarningsPerShareDiluted",)
SEC_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def sec_headers(contact: str):
    if not contact or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact.strip()):
        raise ValueError("Set SEC_CONTACT_EMAIL to your valid administrator contact email to use SEC fundamentals")
    return {"User-Agent": f"IthacaQuant academic-research {contact.strip()}",
            "Accept": "application/json"}


def get_json(url, contact, client=None):
    session = client or requests
    headers = sec_headers(contact)
    def get():
        response = session.get(url, headers=headers, timeout=20)
        if response.status_code in (403, 429):
            raise ValueError("SEC access refused or rate-limited; do not keep retrying")
        response.raise_for_status()
        return response.json()
    return retry_call(get, retryable=lambda e: isinstance(e, requests.RequestException))


def cik_from_directory(payload, ticker: str):
    for value in payload.values() if isinstance(payload, dict) else payload:
        if str(value.get("ticker", "")).upper().strip() == ticker.upper().strip():
            return int(value["cik_str"]), str(value.get("title", ticker))
    return None, ticker


def fetch_company_facts(ticker, contact, client=None):
    mapping = get_json(SEC_COMPANY_TICKERS, contact, client)
    cik, name = cik_from_directory(mapping, ticker)
    if cik is None:
        raise ValueError("Ticker not found in SEC issuer directory")
    return get_json(SEC_FACTS.format(cik=cik), contact, client), name


def concept_quarters(facts, tags, unit="USD"):
    """One observed quarterly duration per filing-period, retain restatement dates."""
    taxonomy = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        concept = taxonomy.get(tag, {})
        rows = concept.get("units", {}).get(unit, [])
        items = []
        for item in rows:
            if item.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A"):
                continue
            if not all(k in item for k in ("start", "end", "filed", "val")):
                continue
            start = pd.to_datetime(item["start"], errors="coerce")
            end = pd.to_datetime(item["end"], errors="coerce")
            filed = pd.to_datetime(item["filed"], errors="coerce")
            if pd.isna(start) or pd.isna(end) or pd.isna(filed):
                continue
            if not (65 <= (end - start).days <= 115):
                continue
            try:
                value = float(item["val"])
                if not np.isfinite(value):
                    continue
            except (TypeError, ValueError):
                continue
            items.append({"start": start, "end": end, "filed": filed, "value": value,
                          "form": str(item["form"]), "tag": tag})
        if items:
            out = pd.DataFrame(items)
            # If multiple rows from one filing/period, prefer consistent unique
            # first record; later restatements remain for point-in-time selection.
            return out.sort_values(["end", "filed"]).drop_duplicates(
                ["start", "end", "filed"], keep="last").reset_index(drop=True)
    return pd.DataFrame(columns=["start", "end", "filed", "value", "form", "tag"])


def last_asof(quart: pd.DataFrame, asof):
    """Latest known fact for each reported period as of the chosen date."""
    if quart.empty:
        return quart.copy()
    eligible = quart.loc[quart["filed"] <= pd.Timestamp(asof)].copy()
    return eligible.sort_values("filed").drop_duplicates(["start", "end"], keep="last").sort_values("end")


def public_quarterly_snapshot(facts, asof=None):
    """Return quarterly revenues, net income, growth and provenance without guessing."""
    when = pd.Timestamp(asof or datetime.now().date())
    revenue = last_asof(concept_quarters(facts, REVENUE_TAGS), when)
    profit = last_asof(concept_quarters(facts, PROFIT_TAGS), when)
    if revenue.empty:
        return pd.DataFrame(columns=["period_end", "filed", "revenue_usd", "net_income_usd",
                                     "revenue_yoy", "net_margin", "tag"])
    result = []
    for _, row in revenue.iterrows():
        end = row["end"]
        quarter = {"period_end": end, "filed": row["filed"],
                   "revenue_usd": row["value"], "net_income_usd": np.nan,
                   "revenue_yoy": np.nan, "net_margin": np.nan, "tag": row["tag"]}
        if not profit.empty:
            matched = profit.loc[(profit["end"] == end) & (profit["start"] == row["start"])]
            if not matched.empty:
                p = matched.iloc[-1]
                # Respect both publication dates for the combined ratio.
                quarter["filed"] = max(row["filed"], p["filed"])
                quarter["net_income_usd"] = float(p["value"])
                if row["value"]:
                    quarter["net_margin"] = float(p["value"] / row["value"])
        previous = revenue.loc[(revenue["end"] < end) &
                               ((end - revenue["end"]).dt.days.between(315, 410))]
        if not previous.empty:
            prior = previous.iloc[(previous["end"] - (end - pd.DateOffset(years=1))).abs().argmin()]
            if prior["value"] > 0:
                quarter["revenue_yoy"] = float(row["value"] / prior["value"] - 1)
                quarter["filed"] = max(quarter["filed"], prior["filed"])
        result.append(quarter)
    return pd.DataFrame(result).sort_values("period_end").reset_index(drop=True)


def filing_features(snapshot: pd.DataFrame, sessions: pd.DatetimeIndex):
    """Create leakage-resistant fundamental features, known only after filing.

    Missing reported data is represented with 0 plus an explicit availability
    flag. This does NOT mean true revenue growth or margins equal zero.
    """
    index = pd.DatetimeIndex(pd.to_datetime(sessions)).tz_localize(None).normalize()
    result = pd.DataFrame(index=index, columns=["sec_revenue_yoy", "sec_net_margin",
                                                "sec_filing_age", "sec_available"], dtype=float)
    result.loc[:, :] = 0.0
    if snapshot.empty:
        return result
    snap = snapshot.copy()
    snap["effective"] = pd.to_datetime(snap["filed"]) + pd.offsets.BDay(1)
    snap = snap.sort_values("effective").drop_duplicates("effective", keep="last")
    for current in index:
        eligible = snap.loc[snap["effective"] <= current]
        if eligible.empty:
            continue
        latest = eligible.iloc[-1]
        if pd.notna(latest["revenue_yoy"]):
            result.loc[current, "sec_revenue_yoy"] = float(np.clip(latest["revenue_yoy"], -2.0, 5.0))
            result.loc[current, "sec_available"] = 1.0
        if pd.notna(latest["net_margin"]):
            result.loc[current, "sec_net_margin"] = float(np.clip(latest["net_margin"], -2.0, 2.0))
            result.loc[current, "sec_available"] = 1.0
        result.loc[current, "sec_filing_age"] = float(np.clip((current - latest["filed"]).days / 365.0, 0, 3))
    return result


def parse_yahoo_quarterly_income(raw: pd.DataFrame) -> pd.DataFrame:
    """Recent unverified financial-statement figures (display ONLY).

    Yahoo's income-statement table does not reliably contain original SEC filing
    timestamps, so these numbers must never be inserted into historical ML.
    """
    cols = ["period_end", "revenue_usd", "net_income_usd", "diluted_eps"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    def find(names):
        for name in names:
            if name in raw.index:
                return raw.loc[name]
        return pd.Series(dtype=float)
    revenue = find(["Total Revenue", "Operating Revenue"])
    income = find(["Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"])
    eps = find(["Diluted EPS"])
    rows = []
    for column in raw.columns:
        day = pd.to_datetime(column, errors="coerce")
        if pd.isna(day):
            continue
        def value(series):
            v = pd.to_numeric(series.get(column, np.nan), errors="coerce")
            return float(v) if pd.notna(v) else np.nan
        rows.append({"period_end": day, "revenue_usd": value(revenue),
                     "net_income_usd": value(income), "diluted_eps": value(eps)})
    return pd.DataFrame(rows, columns=cols).sort_values("period_end", ascending=False).reset_index(drop=True)


def yahoo_latest_quarterly(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    return parse_yahoo_quarterly_income(yf.Ticker(ticker).quarterly_income_stmt)
