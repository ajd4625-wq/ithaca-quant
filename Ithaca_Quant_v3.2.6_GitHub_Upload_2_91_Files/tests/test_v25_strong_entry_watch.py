"""Extra-strict dark-green entry screen does not override safety checks."""
from datetime import date

from ithaca_quant.portfolio_lights import classify_holding
from ithaca_quant.portfolio_workspace import _signal_cell_style

TODAY = date(2026, 11, 18)


def good_record():
    return dict(asof='2026-11-18', forecast_excess=0.08,
                prob_gain=0.73, vol_20=0.43,
                entry_watch='ENTRY WATCH', exit_review='MONITOR',
                model_price=100., review_level=89.)


def light(record, **kwargs):
    return classify_holding(record, today=TODAY, **kwargs)


def test_dark_green_only_for_strongest_screen():
    a = light(good_record(), latest_price=100., position_weight=0.10)
    assert a['color'] == 'DARK_GREEN'
    assert 'STRONG ENTRY WATCH' in a['label']
    assert 'not been proven' in a['reason']
    assert '#14532d' in _signal_cell_style(a['label'])
    assert '#ffffff' in _signal_cell_style(a['label'])


def test_dark_green_is_not_triggered_by_one_optimistic_number():
    for override in ({'forecast_excess': 0.059}, {'prob_gain': 0.69},
                     {'prob_gain': None}, {'vol_20': None},
                     {'vol_20': .61}, {'entry_watch': 'WATCH / CONFIRM'},
                     {'entry_watch': 'WAIT'}):
        outcome = light({**good_record(), **override}, position_weight=.10)
        assert outcome['color'] != 'DARK_GREEN', override
    assert light(good_record(), position_weight=.16)['color'] == 'GREEN'
    assert light(good_record(), position_weight=.30)['color'] == 'YELLOW'


def test_exit_unsafe_prices_and_stale_records_override_dark_green():
    f = good_record()
    assert light({**f, 'exit_review': 'REVIEW EXIT'})['color'] == 'RED'
    assert light({**f, 'forecast_excess': -0.03})['color'] == 'RED'
    assert light(f, latest_price=89.)['color'] == 'RED'
    assert light(f, latest_price=40.)['color'] == 'YELLOW'
    assert light(f, quote_available=False)['color'] == 'YELLOW'
    assert light({**f, 'asof': '2026-10-01'})['color'] == 'YELLOW'


def test_color_table_has_four_categories():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1]/'ithaca_quant'/'portfolio_workspace.py').read_text()
    assert "'DARK_GREEN':0" in source
    assert '🟩 Strong entry watch' in source
    assert 'lightcols = st.columns(4)' in source
    assert 'Red overrides both greens' in source
