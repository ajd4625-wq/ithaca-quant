"""Synthetic-only safeguards: they do not authenticate vendor histories."""
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np
import pandas as pd
import pytest

from ithaca_quant.historical_archive import load_historical_archive, FORMAT
from ithaca_quant.production_history import (production_panel_from_archive,
    configured_archive_path, load_private_production_archive)
from ithaca_quant.terminal_settlement import (compute_terminal_returns,
    attach_settlements, BASIS)
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof


def synthetic_archive():
    dates=pd.bdate_range('2024-01-01', periods=500)
    rng=np.random.default_rng(234)
    ids=['SPY','D000']+[f'ID{i:03d}' for i in range(7)]
    raw={};prices=[];master=[];members=[]
    for j,sid in enumerate(ids):
        trend=rng.normal(.0003,.01,len(dates))
        values=90*np.exp(np.cumsum(trend))
        raw[sid]=values
        last_index=450 if sid=='D000' else 499
        master.append({'security_id':sid,'ticker':sid if sid=='SPY' else ('DEAD' if sid=='D000' else f'L{j:03d}'),
                       'valid_from':str(dates[0].date()),'valid_to':str(dates[last_index].date())})
        for i,d in enumerate(dates[:last_index+1]):
            prices.append({'date':str(d.date()),'security_id':sid,'adjusted_close':float(values[i]),
                           'raw_close':float(values[i]),'volume':100_000+i})
            if sid!='SPY':
                members.append({'date':str(d.date()),'security_id':sid,'eligible':True})
    frames={'price_history.csv':pd.DataFrame(prices).to_csv(index=False).encode(),
            'security_master.csv':pd.DataFrame(master).to_csv(index=False).encode(),
            'membership.csv':pd.DataFrame(members).to_csv(index=False).encode()}
    manifest={'format':FORMAT,'provider':'SYNTHETIC_TEST_ONLY','source_reference':'TEST',
        'price_basis':'total_return_adjusted_close',
        'sha256':{x:sha256(payload).hexdigest() for x,payload in frames.items()}}
    output=BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as z:
        for name,payload in frames.items():z.writestr(name,payload)
        z.writestr('manifest.json',json.dumps(manifest))
    return output.getvalue(), dates


def fake_live_panel(archive,horizon):
    md=archive.market
    cols=['SPY']+[f'ID{i:03d}' for i in range(7)]
    c=md.close[cols].copy()
    v=md.volume[cols].copy()
    renamed={f'ID{i:03d}':f'L{i+2:03d}' for i in range(7)}
    return build_panel(c.rename(columns=renamed),v.rename(columns=renamed),horizon)


def event_evidence(dates):
    return pd.DataFrame([{'security_id':'D000','last_trading_date':str(dates[450].date()),
        'event_date':str(dates[451].date()),'settlement_factor':0.25,
        'return_basis':BASIS,'source_reference':'TEST - event payment document',
        'source_record_id':'MOCK_EVT_001'}])


def test_missing_terminal_losses_stop_production_training():
    archive=load_historical_archive(synthetic_archive()[0])
    live=fake_live_panel(archive,20)
    with pytest.raises(ValueError,match='Historical training blocked.*eligible matured stock outcomes'):
        production_panel_from_archive(live,archive=archive,horizon=20)


def test_event_evidence_produces_documented_training_labels_and_no_yahoo_history(tmp_path):
    raw,dates=synthetic_archive()
    original=load_historical_archive(raw)
    events=event_evidence(dates)
    outcomes=compute_terminal_returns(original,events,horizon=20)
    assert outcomes.security_id.eq('D000').all()
    assert len(outcomes)>=18
    expected_last_price=original.market.close.loc[dates[450],'D000']
    expected_signal=original.market.close.loc[dates[440],'D000']
    record=outcomes.loc[outcomes.signal_date.eq(str(dates[440].date()))].iloc[0]
    assert record.asof_total_return==pytest.approx(.25*expected_last_price/expected_signal-1)
    assert pd.isna(outcomes.loc[outcomes.signal_date.eq(str(dates[450].date())), 'entry_total_return'].iloc[0])

    source=tmp_path/'source.zip';source.write_bytes(raw)
    src_events=tmp_path/'settlement.csv';events.to_csv(src_events,index=False)
    new=tmp_path/'private_complete.zip'
    details=attach_settlements(source,src_events,new,20)
    assert details['provenance_authenticated'] is False
    assert details['terminal_rows']>=18
    assert load_historical_archive(new).quality['terminal_horizon_sessions']==20
    full=load_private_production_archive(new, allow_test_data=True)
    live=fake_live_panel(full,20)
    prod=production_panel_from_archive(live,archive=full,horizon=20)
    with pytest.raises(ValueError, match='horizon-specific archive|built for 20 sessions'):
        production_panel_from_archive(live,archive=full,horizon=5)
    assert prod.diagnostics['eligible_missing_outcomes']==0
    assert prod.diagnostics['historical_label_rows']>300
    assert prod.diagnostics['terminal_return_records']>=18
    asof=live.date.max()
    assert len(prod.panel.loc[prod.panel.date.eq(asof)])==7
    assert all(prod.panel.loc[prod.panel.date.eq(asof),'ticker'].str.startswith('L'))
    assert 'PIT_D000' in set(prod.panel.ticker)
    assert 'L002' in set(prod.panel.loc[prod.panel.date.lt(asof),'ticker'])
    assert prod.panel.duplicated(['date','ticker']).sum()==0
    assert prod.diagnostics['production_training_mode'].startswith('ARCHIVE_HISTORY_ONLY')
    assert prod.panel['cs_rank_mom_20'].eq(0.5).all()
    with pytest.raises(ValueError, match='Synthetic/demo'):
        load_private_production_archive(new)
    # Full forecasting path uses only matured archived labels and current inputs.
    predicted=forecast_asof(prod.panel,asof,fast=True,competitive_agents=False)
    assert len(predicted)==7
    assert predicted.forecast_excess.notna().all()


def test_reject_crsp_ciz_return_double_counting_and_false_current_crosswalk():
    raw,dates=synthetic_archive()
    bundle=load_historical_archive(raw)
    events=event_evidence(dates)
    events.loc[0,'return_basis']='CRSP_CIZ_DLYRET_ALREADY_INCLUDES_DELISTING'
    with pytest.raises(ValueError,match='already included|Only incremental'):
        compute_terminal_returns(bundle,events,20)
    # A stale archive's old tickers must not be asserted as today's identities.
    live=fake_live_panel(bundle,20).copy()
    live.loc[live.date.eq(live.date.max()),'date']=live.date.max()+pd.Timedelta(days=25)
    prod=production_panel_from_archive(live,archive=bundle,horizon=20,
        require_complete_outcomes=False)
    assert prod.diagnostics['permanent_ids_mapped_to_live']==0
    assert 'PIT_ID000' in set(prod.panel.ticker)


def test_missing_configured_archive_is_a_hard_failure(tmp_path):
    assert configured_archive_path(environment={}) is None
    path=tmp_path/'nonexistent.zip'
    assert configured_archive_path(environment={'ITHACA_HISTORICAL_ARCHIVE_PATH':str(path)})==path
    assert str(configured_archive_path(environment={'ITHACA_HISTORICAL_ARCHIVE_PATH':str(path),
        'ITHACA_HISTORICAL_ARCHIVE_PATH_5':'/private/five.zip'},horizon=5))=='/private/five.zip'
    with pytest.raises(ValueError,match='does not exist'):
        load_private_production_archive(path)
