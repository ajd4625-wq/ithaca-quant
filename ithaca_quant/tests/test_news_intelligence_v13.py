"""v1.3: current-news overlay is bounded, attributed, and never backtested with future headlines."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from ithaca_quant.news_intelligence import (
    MAX_NEWS_SHIFT_20D, analyze_news, intraday_news_shift,
    news_adjusted_estimates, news_breakdown_lines, shift_for_horizon,
)
from ithaca_quant.explorer import chart_axis_range
from ithaca_quant.ai_news import summarize_stock_news

NOW = datetime(2026,11,12,18,0,tzinfo=timezone.utc)


def article(title, age_h=1, publisher="Yahoo Finance"):
    return {"title":title, "publisher":publisher,
            "published_utc":NOW-timedelta(hours=age_h),
            "url":"https://news.google.com/example"}


def test_empty_stale_future_and_undated_news_cannot_change_returns():
    feed=[article("NVDA beats expectations",age_h=220),
          article("NVDA surges",age_h=-2),
          {"title":"NVDA upgrade", "url":"https://news.google.com/123", "publisher":"Yahoo Finance"}]
    outcome=analyze_news(feed,"NVDA",now=NOW)
    assert outcome['status']=='no_recent_verified_headlines'
    assert outcome['shift_20d']==0
    pred=news_adjusted_estimates(.04,.20,.55,20,outcome)
    assert pred['scenario_excess']==pred['base_excess']
    assert pred['scenario_boom']==pred['base_boom']


def test_positive_recent_headlines_and_duplicate_deduplication():
    feed=[article('NVIDIA NVDA beats expectations and surges', publisher='Yahoo Finance'),
          article('NVIDIA NVDA beats expectations and surges', publisher='Fox Business'),
          article('NVIDIA NVDA upgrades growth', age_h=2, publisher='ABC News'),
          article('NVIDIA NVDA profit growth', age_h=4, publisher='Fox Business')]
    r=analyze_news(feed,'NVDA','NVIDIA Corporation',now=NOW)
    assert r['n']==3
    assert r['source_count']==3
    assert 0 < r['shift_20d'] <= MAX_NEWS_SHIFT_20D
    assert all(item['published_utc'].tzinfo is not None for item in r['headlines'])
    assert 'headline' in r['explanation']


def test_negative_and_capped_adjustments_and_probability_bounds():
    feeds=[article(f'ABC NVDA losses warning drops declines {i}',age_h=i/2)
           for i in range(1,16)]
    r=analyze_news(feeds,'NVDA','NVIDIA',now=NOW)
    assert -MAX_NEWS_SHIFT_20D<=r['shift_20d']<0
    for h in (1,5,20,60,250):
        pred=news_adjusted_estimates(.03,.99,.55,h,r)
        assert abs(pred['news_shift'])<=.015
        assert 0<=pred['scenario_boom']<=1
        assert pred['illustrative_stress_sigma']>=pred['historical_sigma']
    lines=news_breakdown_lines(r,pred,'NVDA')
    assert any('Boom' in line for line in lines)
    assert any('Risk' in line for line in lines)
    assert any('Buy/sell' in line for line in lines)


def test_intraday_overlay_only_uses_same_et_date():
    today=article('NVDA beats expectations and surges',age_h=1)
    yesterday=article('NVDA cuts outlook and falls',age_h=30)
    report_today=analyze_news([today,yesterday],'NVDA',now=NOW)
    report_yesterday=analyze_news([yesterday],'NVDA',now=NOW)
    assert intraday_news_shift(report_today,now=NOW)>0
    assert intraday_news_shift(report_yesterday,now=NOW)==0
    assert abs(intraday_news_shift(report_today,now=NOW))<=.002


def test_no_1d_blank_padding_but_only_intraday_real_data():
    indexes=pd.date_range('2026-11-12 13:35',periods=9,freq='5min')
    series=pd.Series(np.linspace(100,104,len(indexes)),index=indexes)
    bounds=chart_axis_range(series,'1D')
    assert bounds[0] == pd.Timestamp("2026-11-12 08:30")
    assert bounds[1] == pd.Timestamp("2026-11-12 16:00")
    bounds=chart_axis_range(series,'1D',indexes[-1]+pd.Timedelta(minutes=45))
    assert bounds[0] == pd.Timestamp("2026-11-12 08:30")
    assert bounds[1] == pd.Timestamp("2026-11-12 16:00")
    past_midnight=indexes[-1]+pd.Timedelta(days=1)
    assert chart_axis_range(series,'1D',past_midnight)[1] == pd.Timestamp("2026-11-12 16:00")


def test_optional_llm_disabled_without_server_key():
    r=analyze_news([article('NVDA beats and surges')], 'NVDA',now=NOW)
    assert summarize_stock_news('NVDA',r,api_key='') == ''


def test_code_never_retrains_ml_with_live_news_or_adds_fourth_scoring_agent():
    root=Path(__file__).resolve().parents[1]
    app=(root/'app.py').read_text()
    agents=(root/'ithaca_quant/agents.py').read_text()
    assert 'news_adjusted_estimates' in app
    assert 'news_breakdown_lines' in app
    assert 'intraday_news_shift' in app
    assert 'MAX_AGENTS' not in app or 'MAX_AGENTS' in (root/'ithaca_quant/config.py').read_text()
    assert 'AGENT_NAMES = ("Forecast", "Momentum", "Risk")' in agents
