"""Persistence, accounting, access control and forecast storage for v2.3."""
from datetime import date
from pathlib import Path
import io
import math
import re

import pytest

from ithaca_quant import holdings


@pytest.fixture()
def sql_db(tmp_path, monkeypatch):
    monkeypatch.setenv('ITHACA_DATABASE_URL', 'sqlite:///' + str(tmp_path/'portfolio.sqlite3'))
    holdings._tables.cache_clear()
    yield tmp_path
    holdings._tables.cache_clear()


def test_code_random_hash_and_isolation(sql_db):
    first = holdings.new_access_code()
    second = holdings.new_access_code()
    assert first != second and re.fullmatch(r'IQ-[\w-]{32}',first)
    holdings.create_portfolio(first)
    holdings.create_portfolio(second)
    assert holdings.portfolio_exists(first) and holdings.portfolio_exists(second)
    assert holdings.owner_id(first) != holdings.owner_id(second)
    with pytest.raises(ValueError):
        holdings.get_trades('IQ-' + 'a'*32)
    holdings.add_trade(first, 'TEM', 'BUY', 100, 70, '2026-11-11')
    assert len(holdings.get_trades(first)) == 1
    assert holdings.get_trades(second) == []
    assert first not in (sql_db/'portfolio.sqlite3').read_bytes().decode('utf-8', errors='ignore')


def test_buy_more_partial_sale_basis_and_profit(sql_db):
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    holdings.add_trade(key, 'RKLB', 'BUY', 100, 50., '2026-11-09')
    holdings.add_trade(key, 'RKLB', 'BUY', 100, 70., '2026-11-10')
    holdings.add_trade(key, 'RKLB', 'SELL', 50, 80., '2026-11-11', fees=5.)
    result = holdings.calculate_positions(holdings.get_trades(key), {'RKLB':75})
    line=result['holdings'][0]
    assert line['ticker']=='RKLB'
    assert line['shares']==150
    assert line['avg_buy_price']==60
    assert line['cost_basis']==9000
    assert line['market_value']==11250
    assert line['unrealized_pnl']==2250
    assert result['realized_pnl']==995
    assert result['total_pnl']==3245
    assert result['cash']==1_000_000-5000-7000+3995


def test_sell_more_than_owned_is_rejected_and_never_saved(sql_db):
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    holdings.add_trade(key, 'GNRC', 'BUY', 12, 180, '2026-11-09')
    with pytest.raises(ValueError, match='cannot sell'):
        holdings.add_trade(key, 'GNRC','SELL', 13,180, '2026-11-10')
    assert len(holdings.get_trades(key))==1
    with pytest.raises(ValueError):
        holdings.add_trade(key, 'GNRC','SELL',12,180, '2026-11-05')
    assert len(holdings.get_trades(key))==1


def test_remove_buy_preserves_sale_integrity(sql_db):
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    buy=holdings.add_trade(key, 'TEM','BUY',50,90,'2026-11-08')
    holdings.add_trade(key, 'TEM','SELL',25,100,'2026-11-11')
    with pytest.raises(ValueError):
        holdings.delete_trade(key,buy)
    assert len(holdings.get_trades(key))==2
    assert holdings.get_trades(key)[0]['id']==buy


def test_prices_missing_are_not_zero_and_cash_is_accurate(sql_db):
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    holdings.add_trade(key, 'LSCC','BUY', 10,100, '2026-11-10', fees=2)
    result=holdings.calculate_positions(holdings.get_trades(key),{})
    assert result['equity'] is None
    assert result['total_pnl'] is None
    assert result['missing_quotes']==['LSCC']
    assert result['cash']==998998


def test_code_validation_and_bad_trades(sql_db):
    for code in ['123','IQ-short','IQ-'+'!'*32]:
        with pytest.raises(ValueError):
            holdings.owner_id(code)
    for q,p in [(0,50),(1,float('nan')),(1,-1)]:
        with pytest.raises(ValueError):
            holdings.validate_trade('TEM','BUY',q,p,'2026-11-12')
    with pytest.raises(ValueError):
        holdings.validate_trade('TEM','BUY',10,50,'2999-01-01')
    with pytest.raises(ValueError):
        holdings.validate_trade('SPY','BUY',10,50,'2026-11-12')


def test_reopen_after_engine_cache_clear(sql_db):
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    holdings.add_trade(key,'YPF','BUY',10,38,'2026-11-10')
    for engine,*_ in [holdings.tables()]:
        engine.dispose()
    holdings._tables.cache_clear()
    assert holdings.portfolio_exists(key)
    assert holdings.get_trades(key)[0]['ticker']=='YPF'


def test_forecast_records_are_private_and_persist(sql_db):
    one=holdings.new_access_code(); two=holdings.new_access_code()
    holdings.create_portfolio(one); holdings.create_portfolio(two)
    info={'asof':'2026-11-13','forecast_excess':0.04,'prob_gain':0.55,
          'prob_boom':0.20,'vol_20':0.24,'model_price':115.,'review_level':103.,
          'exit_review':'MONITOR','selected_model':'Existing ensemble'}
    holdings.save_forecast(one,'LSCC',20,info)
    assert holdings.get_forecasts(one,20)['LSCC']['forecast_excess']==0.04
    assert holdings.get_forecasts(two,20)=={}
    info['forecast_excess']=-0.01
    holdings.save_forecast(one,'LSCC',20,info)
    assert len(holdings.get_forecasts(one,20)) == 1
    assert holdings.get_forecasts(one,20)['LSCC']['forecast_excess']==-0.01
    assert holdings.get_forecasts(one,5)=={}


def test_csv_backup_atomic_import(sql_db):
    key=holdings.new_access_code(); holdings.create_portfolio(key)
    holdings.add_trade(key,'RKLB','BUY',20,61.50,'2026-11-12')
    csv_data=holdings.export_trades_csv(holdings.get_trades(key))
    assert b'RKLB' in csv_data and key.encode('utf-8') not in csv_data
    new_key=holdings.new_access_code(); holdings.create_portfolio(new_key)
    import pandas as pd
    rows=pd.read_csv(io.BytesIO(csv_data)).to_dict('records')
    assert holdings.import_trades(new_key,rows)==1
    assert len(holdings.get_trades(new_key))==1
    before=len(holdings.get_trades(new_key))
    bad=[{'ticker':'TEM','side':'BUY','shares':10,'price':5,'trade_date':'2026-11-11','fees':0},
         {'ticker':'TEM','side':'SELL','shares':11,'price':10,'trade_date':'2026-11-12','fees':0}]
    with pytest.raises(ValueError):
        holdings.import_trades(new_key,bad)
    assert len(holdings.get_trades(new_key))==before


def test_forecast_one_uses_only_held_symbol_and_benchmark(sql_db, monkeypatch):
    """Portfolio forecast does not request an exchange directory or broad screen."""
    import pandas as pd
    from ithaca_quant import portfolio_workspace as workspace
    from ithaca_quant.data import MarketData
    symbol='GNRC'
    calls=[]
    dates=pd.bdate_range('2026-10-01', periods=6)
    frame=pd.DataFrame({'SPY':[500]*6, 'GNRC':[187]*6}, index=dates)
    def only_symbol(ticker, source, years):
        calls.append(('download',ticker,source,years))
        assert ticker==symbol and source=='Yahoo Finance' and years==5
        return MarketData(close=frame, volume=frame.copy(), source='fixture', excluded=[])
    def panel(close, volume, horizon, fundamentals, archive):
        calls.append(('panel',horizon))
        return pd.DataFrame({'date':[dates[-1]],'ticker':[symbol]})
    def rank(panel, when, fast, boom, enhanced):
        calls.append(('model',int(fast),int(enhanced)))
        return pd.DataFrame([{'ticker':symbol,'date':dates[-1],
                'close':187.,'forecast_excess':0.021,'prob_gain':0.55,
                'prob_boom':0.09,'vol_20':0.4,'ma_gap_20':0.01,
                'ma_gap_60':0.02,'rel_20':0.03,'selected_model':'fixture-ensemble'}])
    monkeypatch.setattr(workspace,'recorded_headlines',lambda ticker:pd.DataFrame())
    key=holdings.new_access_code();holdings.create_portfolio(key)
    result=workspace._forecast_one(key,symbol,20,mode='Yahoo Finance',
        cached_single_symbol=only_symbol,cached_panel=panel,cached_ranking=rank,
        cached_sec_quarters=lambda *args: (_ for _ in ()).throw(AssertionError('Should not fetch SEC without contact')),
        sec_contact='',enhanced=False)
    assert result['forecast_excess']==pytest.approx(0.021)
    assert calls==[('download','GNRC','Yahoo Finance',5),('panel',20),('model',1,0)]
    assert holdings.get_forecasts(key,20)['GNRC']['selected_model']=='fixture-ensemble'


def test_new_workspace_routes_before_any_universe_scan():
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/'app.py').read_text()
    assert '"💼 My portfolio"' in source
    assert 'if workspace.startswith("💼"):' in source
    assert source.index('if workspace.startswith("💼"):') < source.index('if workspace.startswith("⚡") or quick_submit:')
    assert 'st.stop()' in source[source.index('if workspace.startswith("💼"):'):source.index('if workspace.startswith("⚡") or quick_submit:')]
