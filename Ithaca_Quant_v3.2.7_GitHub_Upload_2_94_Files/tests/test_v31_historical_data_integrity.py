"""Synthetic fixture tests verify data controls, NOT stock predictive accuracy."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import pytest

from ithaca_quant.historical_archive import load_historical_archive, FORMAT
from ithaca_quant.fundamentals import (public_quarterly_history, filing_features,
                                       quarterly_history_from_records)
from ithaca_quant.features import build_panel
from ithaca_quant.backtest import _hydrate_terminal_labels,run_walk_forward


def archive_bytes(*,bad_checksum=False,missing_payoff=False,second_identity=False,with_financials=False):
    rng=np.random.default_rng(27)
    dates=pd.bdate_range('2024-01-02',periods=510)
    names=['SPY','C001','C002','C003','C004','C005','C006','C007','C008']
    m=[]
    for i,sid in enumerate(names):
        m.append({'security_id':sid,'ticker':'SPY' if sid=='SPY' else ('AAA' if sid=='C001' else f'X{i:03d}'),
                  'valid_from':str(dates[0].date()),'valid_to':''})
    if second_identity:
        m[2]['ticker']='AAA'  # same symbol on overlapping dates => reject
    security=pd.DataFrame(m)
    price=[]
    for i,sid in enumerate(names):
        r=rng.normal(.0004,.012, len(dates))
        p=100*np.exp(np.cumsum(r))
        for j,d in enumerate(dates):
            # C001 disappears before the final test horizon.
            if sid=='C001' and j>500:
                continue
            price.append({'date':str(d.date()),'security_id':sid,
                          'adjusted_close':float(p[j]),'raw_close':float(p[j]),'volume':float(100_000+j)})
    px=pd.DataFrame(price)
    membership=pd.DataFrame([{'date':str(dt.date()),'security_id':sid,'eligible':sid!='SPY'}
                             for dt in dates for sid in names if sid!='SPY'])
    payoff=pd.DataFrame([{'signal_date':str(dates[-11].date()), 'security_id':'C001',
                          'asof_total_return':-1.,'entry_total_return':-1.,
                          'event_date':str(dates[-8].date()),
                          'source_reference':'archived corporate-action terminal record A'}])
    frames={'security_master.csv':security.to_csv(index=False).encode(),
            'price_history.csv':px.to_csv(index=False).encode(),
            'membership.csv':membership.to_csv(index=False).encode()}
    if not missing_payoff:
        frames['terminal_returns.csv']=payoff.to_csv(index=False).encode()
    if with_financials:
        facts=pd.DataFrame([{'security_id':'C002','filed':a,'period_end':b,
                             'accession':f'000111-{i}', 'revenue_usd':rev,'net_income_usd':rev/10}
                            for i,(a,b,rev) in enumerate([
                                ('2025-05-05','2025-03-31',100),
                                ('2026-05-05','2026-03-31',130),
                                ('2026-08-05','2026-03-31',160)])])
        frames['financial_facts.csv']=facts.to_csv(index=False).encode()
    manifest={'format':FORMAT,'provider':'Synthetic Test Data - NOT REAL','source_reference':'TEST_ONLY',
              'price_basis':'total_return_adjusted_close',
              'sha256':{name:sha256(content).hexdigest() for name,content in frames.items()}}
    if bad_checksum:
        manifest['sha256']['price_history.csv']='0'*64
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(manifest))
        for name,content in frames.items():
            z.writestr(name,content)
    return out.getvalue()


def test_import_uses_permanent_identity_and_checks_all_data_files():
    archive=load_historical_archive(archive_bytes(with_financials=True))
    assert 'C001' in archive.market.close
    assert 'AAA' not in archive.market.close  # historical symbols are never model IDs
    assert archive.market.volume.loc[archive.market.close.index[0],'C001']>0
    assert archive.membership.ticker.nunique()==8
    assert archive.quality['integrity_sha256_verified'] is True
    assert archive.quality['vendor_authenticity_verified'] is False
    assert archive.quality['historical_universe_completeness_verified'] is False
    assert archive.quality['terminal_payoff_rows']==1
    assert 'C002' in archive.fundamentals
    history=archive.fundamentals['C002']
    before=filing_features(history,pd.bdate_range('2026-05-06','2026-08-07'))
    assert before.loc['2026-05-06','sec_revenue_yoy']==pytest.approx(.3)
    assert before.loc['2026-08-04','sec_revenue_yoy']==pytest.approx(.3)
    assert before.loc['2026-08-06','sec_revenue_yoy']==pytest.approx(.6)


def test_import_rejects_modified_data_and_ticker_identity_collisions():
    with pytest.raises(ValueError,match='integrity'):
        load_historical_archive(archive_bytes(bad_checksum=True))
    with pytest.raises(ValueError,match='simultaneous unrelated'):
        load_historical_archive(archive_bytes(second_identity=True))


def test_missing_delisting_payoff_fails_closed_in_strict_historical_backtest():
    data=load_historical_archive(archive_bytes(missing_payoff=True))
    panel=build_panel(data.market.close,data.market.volume,horizon=10)
    with pytest.raises(ValueError,match='delist|end closes|outcomes|terminal|payoff|end',):
        run_walk_forward(panel,data.market.close,top_n=5,horizon=10,max_periods=1,fast=True,
                         historical_membership=data.membership,require_point_in_time=True)


def test_terminal_payoff_repairs_missing_labels_from_real_delisting_records():
    data=load_historical_archive(archive_bytes())
    panel=build_panel(data.market.close,data.market.volume,horizon=10)
    signal=data.market.close.index[-11]
    before=panel.loc[panel.date.eq(signal)&panel.ticker.eq('C001')].iloc[0]
    assert pd.isna(before.forward_return)
    fixed=_hydrate_terminal_labels(panel,data.terminal_returns,data.market.close)
    after=fixed.loc[fixed.date.eq(signal)&fixed.ticker.eq('C001')].iloc[0]
    assert after.forward_return==-1
    assert after.target == pytest.approx(-1-after.benchmark_forward)
    # This preserves a known loss as a training label after the horizon matures.


def test_authoritative_sec_filing_vintages_never_retroactively_restate():
    def fact(start,end,filed,val):
        return {'start':start,'end':end,'filed':filed,'val':val,'form':'10-Q'}
    facts={'facts':{'us-gaap':{'RevenueFromContractWithCustomerExcludingAssessedTax':{'units':{'USD':[
          fact('2025-01-01','2025-03-31','2025-05-05',100),
          fact('2026-01-01','2026-03-31','2026-05-05',130),
          fact('2026-01-01','2026-03-31','2026-08-05',160)]}}}}}
    hist=public_quarterly_history(facts,'2026-12-01')
    dates=pd.bdate_range('2026-05-05','2026-08-07')
    signals=filing_features(hist,dates)
    assert signals.loc['2026-05-05','sec_revenue_yoy']==0
    assert signals.loc['2026-05-06','sec_revenue_yoy']==pytest.approx(.3)
    assert signals.loc['2026-08-04','sec_revenue_yoy']==pytest.approx(.3)
    assert signals.loc['2026-08-06','sec_revenue_yoy']==pytest.approx(.6)


def test_strict_walk_forward_from_archive_includes_delisted_security():
    """Synthetic completion check. Not real historical investing performance."""
    archive=load_historical_archive(archive_bytes())
    panel=build_panel(archive.market.close,archive.market.volume,horizon=10,
                      raw_close=archive.market.raw_close)
    result=run_walk_forward(panel,archive.market.close,horizon=10,top_n=5,
                            max_periods=1,fast=True,
                            historical_membership=archive.membership,
                            require_point_in_time=True,
                            terminal_returns=archive.terminal_returns)
    assert result.metrics['pit_universe_qualified'] is True
    assert result.metrics['missing_nonholding_outcomes']==0
    assert result.metrics['ticker_evaluations']==8
    resolved=result.predictions.loc[result.predictions.ticker.eq('C001')].iloc[0]
    assert resolved.realized_return == -1.0


def test_raw_trade_price_not_adjusted_index_drives_historical_liquidity():
    archive=load_historical_archive(archive_bytes())
    raw=archive.market.raw_close.copy()
    raw['C002'] = raw['C002'] * 0.001  # ex-post adjusted series is not the raw quote
    panel=build_panel(archive.market.close,archive.market.volume,horizon=10,raw_close=raw)
    last=panel.loc[panel.ticker.eq('C002')].iloc[-1]
    assert last.raw_close < 2
    assert last.close > 20
    assert last.log_dollar_vol_20 < np.log1p(100_000*last.close)
