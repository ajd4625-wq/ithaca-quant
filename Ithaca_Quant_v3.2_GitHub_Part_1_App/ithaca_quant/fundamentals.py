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
    eps = last_asof(concept_quarters(facts, EPS_TAGS, unit="USD/shares"), when)
    result = []
    for _, row in revenue.iterrows():
        end = row["end"]
        quarter = {"period_end": end, "filed": row["filed"],
                   "revenue_usd": row["value"], "net_income_usd": np.nan,
                   "revenue_yoy": np.nan, "net_margin": np.nan, "tag": row["tag"],
                   "diluted_eps": np.nan, "eps_yoy": np.nan}
        if not profit.empty:
            matched = profit.loc[(profit["end"] == end) & (profit["start"] == row["start"])]
            if not matched.empty:
                p = matched.iloc[-1]
                # Respect both publication dates for the combined ratio.
                quarter["filed"] = max(row["filed"], p["filed"])
                quarter["net_income_usd"] = float(p["value"])
                if row["value"]:
                    quarter["net_margin"] = float(p["value"] / row["value"])
        if not eps.empty:
            eligible_eps = eps.loc[(eps["end"] == end) & (eps["start"] == row["start"])]
            if not eligible_eps.empty:
                e = eligible_eps.iloc[-1]
                quarter["diluted_eps"] = float(e["value"])
                quarter["filed"] = max(quarter["filed"], e["filed"])
                year_before = eps.loc[(eps["end"] < end) &
                                      ((end - eps["end"]).dt.days.between(315, 410))]
                if not year_before.empty:
                    old = year_before.iloc[(year_before["end"] - (end - pd.DateOffset(years=1))).abs().argmin()]
                    if abs(old["value"]) > 1e-12:
                        quarter["eps_yoy"] = float(e["value"] / abs(old["value"]) -
                                                   (1 if old["value"] > 0 else -1))
                        quarter["filed"] = max(quarter["filed"], old["filed"])
        previous = revenue.loc[(revenue["end"] < end) &
                               ((end - revenue["end"]).dt.days.between(315, 410))]
        if not previous.empty:
            prior = previous.iloc[(previous["end"] - (end - pd.DateOffset(years=1))).abs().argmin()]
            if prior["value"] > 0:
                quarter["revenue_yoy"] = float(row["value"] / prior["value"] - 1)
                quarter["filed"] = max(quarter["filed"], prior["filed"])
        result.append(quarter)
    frame = pd.DataFrame(result).sort_values("period_end").reset_index(drop=True)
    frame["revenue_growth_accel"] = frame["revenue_yoy"].diff()
    return frame



def public_quarterly_history(facts: dict, asof=None) -> pd.DataFrame:
    """Create a vintage SEC factor ledger, recomputed as known on EACH filing day.

    Crucially, this must be used for training instead of taking today's
    restated quarterly snapshot and pretending it was known years earlier.
    `filed` dates lack acceptance times, so availability begins the next
    business session; source retrieval today does not authenticate EDGAR's
    first real-time dissemination timestamp.
    """
    when = pd.Timestamp(asof or datetime.now().date()).normalize()
    columns = ['asof_event','period_end','filed','revenue_usd','net_income_usd',
               'revenue_yoy','net_margin','eps_yoy','revenue_growth_accel','tag']
    published = []
    for tags, unit in ((REVENUE_TAGS,'USD'), (PROFIT_TAGS,'USD'),(EPS_TAGS,'USD/shares')):
        df = concept_quarters(facts,tags,unit)
        if not df.empty:
            published.extend(pd.Timestamp(x) for x in df.filed if pd.notna(x) and x <= when)
    events = []
    for day in sorted(set(published)):
        vintage = public_quarterly_snapshot(facts, asof=day)
        if vintage.empty:
            continue
        last = vintage.sort_values('period_end').iloc[-1].to_dict()
        last['asof_event'] = day
        events.append(last)
    return pd.DataFrame(events,columns=columns) if events else pd.DataFrame(columns=columns)


def quarterly_history_from_records(facts: pd.DataFrame) -> pd.DataFrame:
    """Vintage snapshots from vendor-provided SEC filing rows with accession IDs.

    Rows are revised only from their original filing dates onward. Period-end
    growth never uses a restatement with a later file date. The source CSV
    must provide actual observed filing dates; self-declaration is not proof.
    """
    columns = ['asof_event','period_end','filed','revenue_usd','net_income_usd',
               'revenue_yoy','net_margin','eps_yoy','revenue_growth_accel']
    if facts is None or facts.empty:
        return pd.DataFrame(columns=columns)
    data = facts.copy()
    for name in ('filed','period_end'):
        data[name] = pd.to_datetime(data[name]).dt.normalize()
    data = data.sort_values(['filed','period_end','accession'])
    result = []
    for day in sorted(data.filed.unique()):
        eligible = (data.loc[data.filed <= day].sort_values(['filed','accession'])
                    .drop_duplicates('period_end',keep='last').sort_values('period_end'))
        if eligible.empty:
            continue
        latest = eligible.iloc[-1]
        revenue = float(latest.revenue_usd) if pd.notna(latest.revenue_usd) else np.nan
        profit = float(latest.net_income_usd) if pd.notna(latest.net_income_usd) else np.nan
        prior = eligible.loc[(eligible.period_end < latest.period_end)&
                             ((latest.period_end - eligible.period_end).dt.days.between(315,410))]
        growth=np.nan
        if not prior.empty and pd.notna(revenue):
            base = prior.iloc[(prior.period_end - (latest.period_end-pd.DateOffset(years=1))).abs().argmin()]
            if pd.notna(base.revenue_usd) and base.revenue_usd > 0:
                growth = revenue / float(base.revenue_usd) - 1
        snapshot={'asof_event':pd.Timestamp(day),'filed':latest.filed,
                  'period_end':latest.period_end,'revenue_usd':revenue,
                  'net_income_usd':profit,'revenue_yoy':growth,
                  'net_margin':profit/revenue if np.isfinite(profit) and np.isfinite(revenue) and revenue!=0 else np.nan,
                  'eps_yoy':np.nan,'revenue_growth_accel':np.nan}
        result.append(snapshot)
    return pd.DataFrame(result,columns=columns)

def filing_features(snapshot: pd.DataFrame, sessions: pd.DatetimeIndex):
    """Create leakage-resistant fundamental features, known only after filing.

    Missing reported data is represented with 0 plus an explicit availability
    flag. This does NOT mean true revenue growth or margins equal zero.
    """
    index = pd.DatetimeIndex(pd.to_datetime(sessions)).tz_localize(None).normalize()
    result = pd.DataFrame(index=index, columns=["sec_revenue_yoy", "sec_net_margin",
                                                "sec_filing_age", "sec_available",
                                                "sec_eps_yoy", "sec_revenue_accel"], dtype=float)
    result.loc[:, :] = 0.0
    if snapshot.empty:
        return result
    snap = snapshot.copy()
    # An event ledger explicitly records the vintage's as-of date; a simple
    # quarterly display is only backwards compatible with already-vintage rows.
    # NEVER construct historical training factors from today's final snapshot.
    evidence_day = 'asof_event' if 'asof_event' in snap else 'filed'
    snap["effective"] = pd.to_datetime(snap[evidence_day]) + pd.offsets.BDay(1)
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
        if "eps_yoy" in latest and pd.notna(latest["eps_yoy"]):
            result.loc[current, "sec_eps_yoy"] = float(np.clip(latest["eps_yoy"], -3, 5))
        if "revenue_growth_accel" in latest and pd.notna(latest["revenue_growth_accel"]):
            result.loc[current, "sec_revenue_accel"] = float(np.clip(latest["revenue_growth_accel"], -3, 5))
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
