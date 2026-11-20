"""Synthetic-only checks: never claim real historical alpha from these fixtures."""
import io
import json
import sys
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pandas as pd
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from ithaca_quant.historical_archive import load_historical_archive
from ithaca_quant.historical_research import run_three_agent_archive_audit
from test_v31_historical_data_integrity import archive_bytes
import server


def repair_synthetic_fixture():
    # Synthetic v3.1 fixture contains C001 as still eligible after delisting.
    # Repair the membership and security lifetime to represent a valid universe.
    with ZipFile(io.BytesIO(archive_bytes())) as z:
        files = {n:z.read(n) for n in z.namelist() if n != 'manifest.json'}
    memberships=pd.read_csv(io.BytesIO(files['membership.csv']))
    master=pd.read_csv(io.BytesIO(files['security_master.csv']))
    terminal=pd.read_csv(io.BytesIO(files['terminal_returns.csv']))
    event=terminal.loc[0,'event_date']
    memberships.loc[(memberships.security_id=='C001') & (memberships.date >= event),'eligible']=False
    master.loc[master.security_id=='C001','valid_to']=event
    files['membership.csv']=memberships.to_csv(index=False).encode()
    files['security_master.csv']=master.to_csv(index=False).encode()
    manifest={'format':'ithaca-historical-v1','provider':'Synthetic Test Source Only',
              'source_reference':'TEST_FIXTURE_NOT_VENDOR',
              'price_basis':'total_return_adjusted_close',
              'sha256':{name:sha256(value).hexdigest() for name,value in files.items()}}
    out=io.BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        for name,value in files.items():z.writestr(name,value)
        z.writestr('manifest.json',json.dumps(manifest))
    return out.getvalue()


def test_historical_archive_not_configured_is_transparent(monkeypatch):
    monkeypatch.setattr(server,'ARCHIVE_PATH','')
    status=server.historical_status()
    assert status['status']=='not_configured'
    assert 'not survivorship-safe' in status['note']
    with pytest.raises(ValueError,match='No PIT historical archive'):
        server.configured_archive()


def test_tampered_archive_rejected_by_backend(monkeypatch,tmp_path):
    blob=archive_bytes(bad_checksum=True)
    p=tmp_path/'invalid.zip';p.write_bytes(blob)
    monkeypatch.setattr(server,'ARCHIVE_PATH',str(p))
    monkeypatch.setitem(server.archive_cache,'fingerprint',None)
    assert server.historical_status()['status']=='rejected'
    with pytest.raises(ValueError,match='valid v3.1 provider-backed'):
        server.start_historical_audit()


def test_three_agent_archive_audit_runs_only_on_complete_pit_membership():
    data=load_historical_archive(repair_synthetic_fixture())
    result=run_three_agent_archive_audit(data,windows=2,step=20)
    assert result.summary['historical_eligible_forecasts']==15
    assert result.summary['three_learners'] is True
    assert result.summary['vendor_authenticity_verified'] is False
    assert result.summary['historical_universe_completeness_verified'] is False
    assert result.summary['no_promotion'] is True
    assert result.summary['distinct_issue_dates']==2
    # Each source-declared eligible record must be retained, including abstentions.
    assert len(result.forecasts)==15
    assert all(result.forecasts.groupby('signal_date').size().values == [8,7])


def test_missing_delisting_horizon_payoff_cannot_disappear():
    # The upstream fixture wrongly keeps delisted C001 eligible in late snapshots.
    # Retrospective audit refuses to drop it or turn it into unused cash.
    data=load_historical_archive(archive_bytes())
    with pytest.raises(ValueError,match='outcome|terminal|payoff|end|delist|missing from panel'):
        run_three_agent_archive_audit(data,windows=1)


def test_volume_missing_is_not_rewritten_to_zero():
    idx=pd.bdate_range('2026-02-02',periods=280)
    stock=pd.Series([150+.4*i for i in range(280)],index=idx)
    benchmark=pd.Series([100+.22*i for i in range(280)],index=idx)
    vol=pd.Series([200_000.]*280,index=idx)
    vol.iloc[-1]=float('nan')
    result=server.score_indicators(stock,benchmark,vol)
    assert result['volume_ratio'] is None
    assert result['early_setup'] is False
    quality=server.live_integrity(pd.DataFrame({'AAPL':stock,'SPY':benchmark}),
                                  pd.DataFrame({'AAPL':vol},index=idx),'AAPL','TEST ONLY')
    assert quality['recent_missing_volume']==1
    assert quality['point_in_time_universe_verified'] is False


def test_new_quality_gate_abstains_with_missing_latest_volume():
    from ithaca_quant.data import demo_market_data,MarketData
    source=demo_market_data(['AAPL'],sessions=760,seed=12)
    volumes=source.volume.copy();volumes.loc[volumes.index[-1],'AAPL']=float('nan')
    modified=MarketData(source.close,volumes,source.source,source.excluded)
    result=server.analyze('AAPL',provider=lambda _:modified,persist=False)
    assert result['signal']['direction_vs_spy'] is None
    assert result['signal']['label']=='DATA QUALITY HOLD'
    assert result['data_integrity']['signal_quality_gate_passed'] is False
    assert result['audited_in_weekly_ledger'] is False


def test_friday_notification_gate_waits_for_complete_session():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    et=ZoneInfo('America/New_York')
    assert server.report_ready('2026-11-20',datetime(2026,11,20,16,30,tzinfo=et)) is False
    assert server.report_ready('2026-11-20',datetime(2026,11,20,18,5,tzinfo=et)) is True
    assert server.report_ready('2026-11-13',datetime(2026,11,20,12,0,tzinfo=et)) is True
