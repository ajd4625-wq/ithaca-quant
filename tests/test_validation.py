import numpy as np
import pandas as pd
import pytest

from ithaca_quant.validation import (
    attach_quality, calibration_bins, overall_quality, per_ticker_quality,
    validate_oos_data,
)


def rows():
    # Three independent signal dates. Each entry's true horizon end is later.
    result = []
    for i, (p, outcome) in enumerate([(0.9, 1), (0.7, 1), (0.3, 0)]):
        start = pd.Timestamp('2024-01-01') + pd.Timedelta(days=25 * i)
        end = start + pd.Timedelta(days=20)
        for ticker in ('AAA', 'BBB'):
            result.append(dict(signal_date=start, end_date=end, ticker=ticker,
                pred_excess=.08 if outcome else -.03, realized_excess=.04 if outcome else -.02,
                realized_return=.12 if outcome else -.04, benchmark_return=.08 if outcome else -.02,
                p_gain=p, p_boom=p, gain_baseline=.50, boom_baseline=.50,
                gain_event=outcome, boom_event=outcome, naive_direction_positive=True))
    return pd.DataFrame(result)


def test_oos_aggregate_beats_baseline():
    q = overall_quality(rows())
    assert q['ticker_outcomes'] == 6
    assert q['signal_windows'] == 3
    assert q['direction_hit'] == pytest.approx(1.0)
    assert q['direction_baseline'] == pytest.approx(2/3)
    assert q['boom_brier'] < q['boom_baseline_brier']
    assert q['gain_brier'] < q['gain_baseline_brier']
    assert q['evidence'].startswith('Insufficient')


def test_per_stock_sample_size_warning():
    result = per_ticker_quality(rows())
    assert result['oos_windows'].tolist() == [3, 3]
    assert result['oos_evidence'].eq('Too few OOS windows').all()
    assert result['oos_direction_hit'].eq(1.0).all()


def test_calibration_is_empirical_and_auditable():
    hist = calibration_bins(rows(), 'boom')
    assert hist['n'].sum() == 6
    assert (hist['mean_predicted'].between(0,1)).all()
    assert (hist['observed_frequency'].between(0,1)).all()
    with pytest.raises(ValueError):
        calibration_bins(rows(), 'bad-event')


def test_accuracy_table_does_not_change_stock_order():
    d = pd.DataFrame({'Rank':[1,2], 'Ticker':['BBB', 'AAA'], 'Research score /100':[90,80]})
    result = attach_quality(d, rows())
    assert result['Ticker'].tolist() == ['BBB', 'AAA']
    assert result['Rank'].tolist() == [1, 2]
    assert result['OOS windows'].tolist() == [3, 3]
    untested = attach_quality(d, None)
    assert untested['OOS evidence'].eq('Not tested').all()
    assert untested['OOS windows'].eq(0).all()


def test_rejects_duplicate_ticker_date_and_invalid_future_label():
    data = rows()
    with pytest.raises(ValueError, match='Duplicate'):
        validate_oos_data(pd.concat([data, data.iloc[[0]]], ignore_index=True))
    bad = data.copy()
    bad.loc[0, 'end_date'] = bad.loc[0, 'signal_date']
    with pytest.raises(ValueError, match='before'):
        validate_oos_data(bad)
