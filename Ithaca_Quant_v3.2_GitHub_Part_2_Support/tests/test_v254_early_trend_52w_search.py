"""v2.5.4: early setup, 52-week news context and protective exit signals."""
from datetime import date, datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

from ithaca_quant.signals import plan_signals
from ithaca_quant.leaderboard_review import evaluate_candidate
from ithaca_quant.portfolio_lights import classify_holding
from ithaca_quant.trend_intelligence import annual_range_context, news_range_context
from ithaca_quant.features import build_panel
from ithaca_quant.universe import screen_candidates

ASOF = date(2026, 11, 19)


def model_stock(**extra):
    row = dict(ticker='TURN', close=85.0, forecast_excess=.055, prob_gain=.65,
               vol_20=.42, rel_20=-.015, ma_gap_20=.003,
               ma_gap_60=-.05, mom_5=.045, mom_20=-.025,
               mom_5_accel=.075, rel_5=.025, range_252=.42,
               has_252_range=1., volume_ratio=.24, research_score=88.)
    row.update(extra)
    return row


def test_early_entry_does_not_require_a_past_60_day_rally():
    signals = plan_signals(pd.DataFrame([model_stock()]), horizon=20)
    assert signals.iloc[0]['entry_watch'] == 'EARLY ENTRY WATCH'
    assert signals.iloc[0]['exit_review'] == 'MONITOR'
    flags = classify_holding(dict(asof=ASOF.isoformat(), entry_watch='EARLY ENTRY WATCH',
                                  forecast_excess=.055, exit_review='MONITOR',
                                  model_price=85, review_level=75), today=ASOF, latest_price=85)
    assert flags['color'] == 'GREEN' and 'EARLY ENTRY WATCH' in flags['label']


def test_risky_or_unconfirmed_early_turn_is_not_promoted():
    cases = [model_stock(forecast_excess=-.04), model_stock(mom_5_accel=-.01),
             model_stock(range_252=.89), model_stock(has_252_range=0),
             model_stock(mom_5=-.10), model_stock(ma_gap_20=-.04),
             model_stock(rel_5=-.02), model_stock(volume_ratio=-.5)]
    for row in cases:
        signal = plan_signals(pd.DataFrame([row]), horizon=20).iloc[0]
        assert signal['entry_watch'] != 'EARLY ENTRY WATCH', row
    assert plan_signals(pd.DataFrame([model_stock()]), horizon=5).iloc[0]['entry_watch'] != 'EARLY ENTRY WATCH'


def history(extra_future=False):
    # 220 true daily prices and valid point-in-time benchmark.
    ix = pd.bdate_range(end='2026-11-19', periods=220)
    px = np.r_[np.linspace(110, 70, 150), np.linspace(70, 80, 70)]
    prices = pd.DataFrame({'TURN': px, 'SPY':np.linspace(100, 110, 220)}, index=ix)
    if extra_future:
        prices.loc[pd.Timestamp('2026-12-01')] = [1000, 500]
    return prices


def test_52week_context_uses_no_future_data():
    a = annual_range_context(history(), 'TURN', ASOF)
    b = annual_range_context(history(True), 'TURN', ASOF)
    assert a == b
    assert a['position_52w'] is not None and 0 < a['position_52w'] < 1
    assert a['low_52w'] == 70.0
    assert 'News feed unavailable' in news_range_context(a, checked=False)
    assert '2 distinct' in news_range_context(a, checked=True, event_count=2)
    assert annual_range_context(history().tail(170), 'TURN', ASOF)['position_52w'] is None


def test_exit_reviews_and_acquisition_overrule_early_green():
    close = history()
    r = model_stock(close=float(close['TURN'].iloc[-1]))
    sig = plan_signals(pd.DataFrame([r]), horizon=20).iloc[0].to_dict()
    unverified = evaluate_candidate(r, sig, close, asof=ASOF, horizon=20)
    assert unverified['color'] == 'YELLOW'
    result = evaluate_candidate(r, sig, close, asof=ASOF, horizon=20, articles=[])
    assert result['color'] == 'GREEN' and result['early_trend_watch']
    assert result['position_52w'] is not None
    acquisition = [{'title':'Turn agrees to acquire Beta', 'publisher':'Reuters',
                    'published_utc':datetime(2026,11,18,tzinfo=timezone.utc),
                    'url':'https://example.com/deal'}]
    caution = evaluate_candidate(r, sig, close, asof=ASOF, horizon=20,
                                  company='Turn Inc', articles=acquisition)
    assert caution['color'] == 'YELLOW'
    assert caution['entry_sort_tier'] > result['entry_sort_tier']
    red = evaluate_candidate(r, {**sig, 'exit_review':'REVIEW EXIT'}, close,
                              asof=ASOF, horizon=20, articles=[])
    assert red['color'] == 'RED'


def test_extended_ml_features_are_point_in_time():
    base = history()
    volume = pd.DataFrame(1e6, index=base.index, columns=base.columns)
    original = build_panel(base, volume, 20)
    extended = history(True)
    volume2 = volume.reindex(extended.index).fillna(100e6)
    after = build_panel(extended, volume2, 20)
    a = original.loc[original.date == pd.Timestamp(ASOF)].iloc[0]
    b = after.loc[after.date == pd.Timestamp(ASOF)].iloc[0]
    for c in ('high_252_gap','low_252_gap','range_252','has_252_range',
              'mom_5_accel','rel_5','rel_5_accel'):
        assert np.isclose(a[c], b[c]), c
    assert 0 <= a['range_252'] <= 1


def test_shortlist_reserves_early_reversal_names():
    ix = pd.bdate_range(end='2026-11-19', periods=220)
    stocks = {'SPY': np.linspace(100, 110, 220)}
    volumes = {}
    for i in range(18):
        # All names liquid, but the liquid traditional cohort also has momentum.
        stocks[f'M{i}'] = np.linspace(20+i, 45+i, 220)
    for i in range(6):
        arr = np.r_[np.linspace(85+i, 55+i, 190),np.linspace(55+i, 55+i, 24),
                    np.linspace(55+i, 60+i, 6)]
        stocks[f'E{i}'] = arr
    frame = pd.DataFrame(stocks, index=ix)
    vol = pd.DataFrame({k:np.full(len(ix), 1e6) for k in frame}, index=ix)
    selected = screen_candidates(frame, vol, limit=12)
    assert len(selected)==12
    assert selected.early_screen.sum() >= 1


def test_search_and_leaderboard_have_same_visible_reasons():
    app = (Path(__file__).parents[1]/'app.py').read_text()
    assert 'quick_review = evaluate_candidate' in app
    assert 'show_signal_card(quick_review["signal_label"]' in app
    assert 'show_signal_card(quick_review["exit_label"]' in app
    assert 'quick_review["news_52w_context"]' in app
    assert 'Early entry watch' in app


def test_two_distinct_negative_news_events_yellow_not_red():
    close = history()
    row = model_stock(close=float(close['TURN'].iloc[-1]))
    signal = plan_signals(pd.DataFrame([row]), horizon=20).iloc[0].to_dict()
    bad = [
        {'title':'Turn misses earnings estimates and cuts forecast', 'publisher':'Reuters',
         'published_utc':datetime(2026,11,17,tzinfo=timezone.utc),
         'url':'https://example.com/earnings'},
        {'title':'Turn faces new lawsuit investigation', 'publisher':'CNBC',
         'published_utc':datetime(2026,11,18,tzinfo=timezone.utc),
         'url':'https://example.com/lawsuit'},
    ]
    result = evaluate_candidate(row, signal, close, asof=ASOF, horizon=20,
                                articles=bad, company='Turn Inc')
    assert result['color'] == 'YELLOW' and 'NEWS REVIEW' in result['signal_label']
    assert result['negative_news_events'] == 2
    assert '2 event(s)' in result['news_52w_context']
    same_event = [bad[0], {**bad[0], 'publisher':'Bloomberg',
                           'title':'Turn misses earnings forecast in quarterly report'}]
    single = evaluate_candidate(row, signal, close, asof=ASOF, horizon=20,
                                articles=same_event, company='Turn Inc')
    assert single['negative_news_events'] <= 1
    assert single['color'] == 'GREEN'
