"""Transparent event tagging; keyword matches are not LLM-verified facts."""
from __future__ import annotations
import re
import pandas as pd

EVENTS = {
    'earnings': ('earnings','quarterly results','revenue','profit','eps','10-q','10-k'),
    'guidance': ('outlook','guidance','forecast raised','forecast cut','full-year forecast'),
    'analysts': ('price target','rating upgrade','downgrade','analyst estimates','consensus'),
    'regulatory': ('sec investigation','lawsuit','regulator','antitrust','federal trade'),
    'corporate': ('acquisition','merger','product launch','partnership','chief executive'),
    'macro': ('federal reserve','interest rates','inflation','jobs report','tariff'),
}

def event_flags(title: str):
    title = re.sub(r'\s+', ' ', str(title).lower())
    return {key: int(any(re.search(r'\b'+re.escape(term)+r'\b', title) for term in terms))
            for key,terms in EVENTS.items()}


def headline_event_counts(rows: pd.DataFrame):
    values = {k:0 for k in EVENTS}
    if rows is None or rows.empty or 'title' not in rows.columns:
        return values
    for title in rows['title']:
        for tag, indicator in event_flags(title).items():
            values[tag] += indicator
    return values
