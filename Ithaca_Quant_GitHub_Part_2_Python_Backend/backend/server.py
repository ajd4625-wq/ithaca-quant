"""Ithaca Quant Chrome Companion v0.6 — v3.2 analyst + portfolio research API.

Upstream market/feature/archive modules from user-supplied v3.2 source.
Daily quick forecasts use three fitted learners from the existing extension.
Archive research uses provider-supplied (not assumed verified) historical data.
No orders, secrets, or live-price claims.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread, Event, BoundedSemaphore
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo
import json, math, os, re, time, traceback

import numpy as np
import pandas as pd
from ithaca_quant.config import MAX_AGENTS, MAX_RETRIES
from ithaca_quant.data import download_market_data, MarketData
from ithaca_quant.features import build_panel
from ithaca_quant.model import forecast_asof
from ithaca_quant.trend_intelligence import annual_range_context
from ithaca_quant.news import fetch_market_news, news_context
from ithaca_quant.news_dedupe import deduplicate_events
from ithaca_quant.model_zoo import compare_rank_models, model_catalog
from ithaca_quant.independent_agents import forecast_three_agents, AGENTS as FITTED_AGENT_NAMES
from ithaca_quant.insider_form4 import fetch_form4_ticker, summarize_insider_activity, SECUnavailable
from ithaca_quant.historical_archive import load_historical_archive
from ithaca_quant.historical_research import run_three_agent_archive_audit
from ledger import connect, record, resolve, report, last_friday, write_html, csv_export
from analyst_bridge import analyst_observation, research_portfolio

assert MAX_AGENTS == 3 and MAX_RETRIES == 2 and len(FITTED_AGENT_NAMES) == 3
ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / 'reports'
PORT = int(os.environ.get('ITHACA_PORT', '8765'))
HOST = '127.0.0.1'
EASTERN = ZoneInfo('America/New_York')
DATA_TTL = 600
NEWS_TTL = 1200
INSIDER_TTL = 1800
RANKING_TICKERS = ('AAPL','MSFT','NVDA','AMZN','GOOGL','META','JPM','CAT','KO','PG','HD','IBM')
# Heavy ranking comparisons are explicitly on-demand and never occupy the 3-agent scoring pool.
rank_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rank-zoo')
rank_state: dict = {'status':'idle','result':None}
rank_lock = Lock()
# The archive ZIP is supplied explicitly by a local environment variable. Never
# mistake a v3.1 source-code ZIP or Yahoo's current symbols for PIT data.
ARCHIVE_PATH = os.environ.get('ITHACA_HISTORICAL_ARCHIVE','').strip()
archive_cache: dict = {'fingerprint':None,'bundle':None}
archive_lock = Lock()
archive_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='archive-audit')
archive_audit_lock = Lock()
archive_audit_state: dict = {'status':'idle','result':None}
insider_cache: dict[str, dict] = {}
market_cache: dict[str, dict] = {}
market_lock = Lock()
MAX_TICKER_LEN = 12
cache: dict[str, dict] = {}
news_cache: dict[str, dict] = {}
locks: dict[str, Lock] = {}
cache_lock = Lock()
ledger_lock = Lock()
news_pool = ThreadPoolExecutor(max_workers=MAX_AGENTS, thread_name_prefix='news')
MAX_SIMULTANEOUS_ANALYSES = 3
workers = BoundedSemaphore(MAX_SIMULTANEOUS_ANALYSES)
portfolio_slot = BoundedSemaphore(1)  # One expensive, explicit holdings study at a time.

def safe_num(value):
    try:
        f=float(value)
        return round(f,6) if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None

def valid_ticker(ticker):
    symbol = str(ticker).upper().strip()
    if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}',symbol):
        raise ValueError('Ticker must be 1–12 letters/numbers (or . and -), e.g. AAPL or BRK-B')
    return symbol

def completed_daily(data: MarketData, at=None):
    """Never train or grade on an unfinished daily candle; ET market time."""
    at = at or datetime.now(EASTERN)
    et = at.astimezone(EASTERN)
    close, volume = data.close.copy(),data.volume.copy()
    if not close.empty:
        latest = pd.Timestamp(close.index[-1]).date()
        if latest >= et.date() and (latest > et.date() or et.hour < 17):
            keep = pd.DatetimeIndex(close.index).date < et.date()
            close, volume = close.loc[keep], volume.loc[keep]
    return MarketData(close,volume,data.source,data.excluded,
                      raw_close=data.raw_close.loc[close.index] if data.raw_close is not None else None)

def get_data(ticker):
    """Reuse source history for quick + deep research while keeping completed bars."""
    with market_lock:
        cached=market_cache.get(ticker)
        if cached and time.monotonic()-cached['at'] < DATA_TTL:
            return cached['data']
    # v3.1 Yahoo downloader uses the configured two-retry cap; no extra retry layer.
    fetched=completed_daily(download_market_data([ticker],years=6,min_history=240,batch_size=3))
    if ticker not in fetched.close or 'SPY' not in fetched.close or len(fetched.close)<252:
        raise ValueError('Insufficient completed price history for ticker and SPY')
    # Explicitly refuse stale daily series rather than showing a precise-looking
    # forecast for a symbol with a dead feed/delisting/extended outage.
    observed=fetched.close[ticker].dropna()
    if observed.empty:raise ValueError('No usable completed prices for stock')
    last=pd.Timestamp(observed.index[-1]).date()
    benchmark_index=pd.DatetimeIndex(fetched.close['SPY'].dropna().index)
    missing_last_sessions=int((benchmark_index>pd.Timestamp(last)).sum())
    if (datetime.now(EASTERN).date()-last).days>7 or missing_last_sessions>2:
        raise ValueError(f'Stock quote stale since {last} ({missing_last_sessions} newer benchmark sessions); no current research signal')
    with market_lock:
        market_cache[ticker]={'data':fetched,'at':time.monotonic()}
    return fetched

def score_indicators(stock, spy, volume):
    stock=stock.dropna(); spy=spy.reindex(stock.index).ffill(limit=2)
    if len(stock)<200: raise ValueError('Need >=200 completed prices')
    close=float(stock.iloc[-1]); ma20=float(stock.tail(20).mean()); ma50=float(stock.tail(50).mean())
    oldma20=float(stock.iloc[-25:-5].mean())
    five=close/float(stock.iloc[-6])-1
    prior=float(stock.iloc[-6]/stock.iloc[-11]-1)
    twenty=float(stock.iloc[-21]); benchmark_twenty=float(spy.iloc[-21]); benchmark_last=float(spy.iloc[-1])
    rel20=close/twenty-benchmark_last/benchmark_twenty
    daily=stock.pct_change().tail(20).dropna(); annvol=float(daily.std()*np.sqrt(252))
    # In v3.1 unknown volumes remain missing, never reinterpreted as zero.
    v=volume.reindex(stock.index)
    valid_vol=v.tail(20).dropna()
    volume_ratio=(float(v.iloc[-1]/max(float(valid_vol.mean()),1))
                  if len(valid_vol)>=15 and pd.notna(v.iloc[-1]) else float('nan'))
    low=float(stock.tail(252).min()); high=float(stock.tail(252).max())
    range_pos=(close-low)/(high-low) if high>low else 0.5
    # One transparent strength score per agent, NOT calibrated probabilities.
    mom_raw = 50 + 250*rel20 + 200*(ma20/ma50-1) + 160*(five-prior)
    momentum=float(np.clip(mom_raw,0,100))
    risk=float(np.clip(90-55*annvol-35*max(0,volume_ratio-3)-28*max(0,range_pos-.92),0,100))
    early = (0.15<=range_pos<=0.72 and -0.018 <= close/ma20-1<=0.035 and
             0.01<=five<=0.10 and five-prior >=.02 and rel20 >-.01 and
             np.isfinite(volume_ratio) and volume_ratio>=0.8 and annvol<=1.25 and ma20>=oldma20)
    return {'close':close,'sma20':ma20,'sma50':ma50,'five_day_return':five,
            'five_day_acceleration':five-prior,'rel20_vs_spy':rel20,
            'annual_volatility':annvol,'volume_ratio':volume_ratio if np.isfinite(volume_ratio) else None,
            'range_position':range_pos,'range_low':low,'range_high':high,
            'momentum_score':round(momentum,1),'risk_score':round(risk,1),
            'early_setup':bool(early), 'sma20_slope_positive':ma20>=oldma20}

def compute_forecast(data, ticker, *, enhanced=False):
    """Use the fitted three-learner monitor or on-demand upstream model zoo.

    Enhancement is opt-in: candidates are selected on embargoed past periods
    and estimated held-out residual intervals are not guaranteed coverage.
    """
    prices=data.close[['SPY',ticker]].dropna()
    volumes=data.volume.reindex(prices.index)  # v3.1: missing historical volume is not traded zero
    if len(prices)<440:
        return {'state':'unavailable','explanation':'Fewer than 440 aligned completed sessions for chronology-based fitting.','enhanced':enhanced}
    panel=build_panel(prices,volumes,horizon=5)
    asof=pd.Timestamp(prices.index[-1])
    if not enhanced:
        return forecast_three_agents(panel, asof, ticker)
    predictions=forecast_asof(panel, asof, fast=True, enhanced=enhanced)
    hit=predictions.loc[predictions['ticker']==ticker]
    if hit.empty: raise ValueError('Model returned no forecast for ticker')
    row=hit.iloc[0]
    cal_n=int(row.get('lab_calibration_n',0) or 0)
    result={'state':'available','horizon_sessions':5,
            'expected_excess_return':safe_num(row['forecast_excess']),
            'model_disagreement':safe_num(row['model_disagreement']),
            'shrinkage':safe_num(row['forecast_shrinkage']),
            'selected_model':str(row['selected_model']),
            'model_note':str(row.get('feature_selection',''))[:600],
            'enhanced':bool(enhanced),
            'uses_sec_filing_features':bool(row.get('uses_sec_filings',False)),
            'uses_historical_news_features':bool(row.get('uses_news_history',False)),
            'explanation':'v3.1 5-session forecast of stock minus SPY excess return, not a live quote, certainty or probability. Current news/insider filings are NOT injected into the ML forecast.'}
    if enhanced:
        result['model_lab']={
            'selected_model':str(row.get('selected_model','Existing ensemble')),
            'calibration_n':cal_n,
            'holdout_mae':safe_num(row.get('lab_mae')),
            'zero_forecast_mae':safe_num(row.get('lab_zero_mae')),
            'lower_excess_return':safe_num(row.get('lab_interval_low')),
            'upper_excess_return':safe_num(row.get('lab_interval_high')),
            'feature_sensitivities':str(row.get('lab_explanation',''))[:500],
            'diagnostic':str(row.get('lab_diagnostic',''))[:2500],
            'promoted_challenger':cal_n>0 and str(row.get('selected_model'))!='Existing ensemble',
            'disclaimer':'Held-out estimates and intervals are research diagnostics, not future guaranteed coverage. No candidate is promoted without its validation gate.'}
    return result

def empty_news(status='loading',errors=None):
    return {'status':status,'events':[],'event_count':None,'coverage':0,
            'explanation':'News is a dated, separately displayed research context; no unvalidated headline-derived return adjustment.',
            'errors':errors or []}

def fetch_news_async(ticker):
    try:
        articles, errors = fetch_market_news(ticker,lookback_days=14,limit=45)
        clusters=deduplicate_events(articles,ticker=ticker)
        entries=[]
        for item in clusters[:9]:
            entries.append({'title':str(item['title'])[:230], 'publisher':str(item['publisher'])[:80],
                            'url':str(item['url']), 'date_utc':item['published_utc'].isoformat(),
                            'sources':item.get('event_sources',[]),
                            'coverage_count':item.get('event_coverage_count',1),
                            'event_type':item.get('event_type','general'),
                            'sentiment_words':int(item.get('sentiment') or 0)})
        verdict=news_context(articles)
        summary={'status':'available' if articles else ('unavailable' if errors else 'no_results'),
                'event_count':len(clusters) if articles else None,
                'coverage':sum(x['coverage_count'] for x in entries),
                'label':verdict['label'], 'events':entries, 'errors':errors,
                'checked_utc':datetime.now(timezone.utc).isoformat(),
                'explanation':'Publisher headlines grouped by likely underlying event (not each syndicated copy). Tone is heuristic, not an audited alpha forecast. Coverage is best-effort, not every publisher.'}
    except Exception as exc:
        summary=empty_news('unavailable',[f'{type(exc).__name__}: {str(exc)[:150]}'])
    with cache_lock:
        news_cache[ticker]={'value':summary,'at':time.monotonic()}

def news_for(ticker):
    with cache_lock:
        item=news_cache.get(ticker)
        if item and time.monotonic()-item['at']<NEWS_TTL:
            return item['value']
        if item and item.get('pending') and time.monotonic()-item['at']<30:
            return empty_news('loading')
        news_cache[ticker]={'pending':True,'at':time.monotonic()}
    news_pool.submit(fetch_news_async,ticker)
    return empty_news()

def build_signal(ind, forecast):
    ex=forecast.get('expected_excess_return') if forecast.get('state')=='available' else None
    agreement=forecast.get('model_disagreement')
    forecast_score = float(np.clip(50+800*ex,0,100)) if ex is not None else None
    # Three separately fitted ML agents. Unavailable forecast
    # does NOT get a fabricated midpoint or produce an actionable signal.
    ml_momentum=forecast.get('momentum_agent_expected_excess')
    downside=forecast.get('risk_agent_downside_probability')
    fitted=(ml_momentum is not None and downside is not None)
    mom_score=float(np.clip(50+800*ml_momentum,0,100)) if fitted else None
    risk_score=float(np.clip(100*(1-downside),0,100)) if fitted else None
    strength = (round(.55*forecast_score+.15*mom_score+.30*risk_score,1)
                if forecast_score is not None and fitted and forecast.get('validation_passed') else None)
    ma20=ind['sma20']; ma50=ind['sma50']; price=ind['close']
    weak=(price < ma20*.98 or (ex is not None and ex < -.02))
    validated=(ex is not None and agreement is not None and math.isfinite(agreement)
               and fitted and forecast.get('validation_passed',False))
    uptrend=price>ma20 and ma20>ma50 and ind['rel20_vs_spy']>0
    if not validated:
        label='INSUFFICIENT EVIDENCE'; direction=None
        reason=('Historical validation failed its prespecified baseline gate; directional signal withheld.'
                if forecast.get('state')=='available' else
                'Chronological three-model forecast unavailable; no directional outcome assumed.')
    elif weak:
        label='EXIT RISK'; direction='DOWN' if ex < -0.01 else None
        reason='Price/model weakness suggests reviewing downside scenarios, not an automatic sell.'
    elif ind['early_setup'] and ex>.01 and risk_score>=55 and ml_momentum>0:
        label='EARLY ENTRY WATCH'; direction='UP'
        reason='Price/relative-strength recovery and model outlook align before an extended annual-high breakout.'
    elif uptrend and ex>.01 and risk_score>=55 and ml_momentum>0:
        label='ENTRY WATCH'; direction='UP'
        reason='Trend, SPY-relative strength and the 5-session model outlook align.'
    elif ex < -.01 and ml_momentum<0:
        label='UNDERPERFORMANCE WATCH'; direction='DOWN'
        reason='Weak model relative outlook and negative momentum; monitor before interpreting direction.'
    else:
        label='WAIT / MIXED';direction=None
        reason='Evidence is mixed or too weak to issue a directional research signal.'
    return {'label':label,'direction_vs_spy':direction,'signal_strength':strength,
            'reason':reason, 'agents':[
              {'name':'Forecast','weight_pct':55,'score':round(forecast_score,1) if forecast_score is not None else None},
              {'name':'Momentum','weight_pct':15,'score':round(mom_score,1) if fitted else None},
              {'name':'Risk','weight_pct':30,'score':round(risk_score,1) if fitted else None}],
            'entry_checks':[f'5-session predicted SPY-relative excess return > +1% (current {ex:+.2%})' if ex is not None else 'Forecast not yet available',
                            f'20-session average rising ({"yes" if ind["sma20_slope_positive"] else "no"})',
                            f'5-session acceleration > +2 pp ({ind["five_day_acceleration"]:+.1%})',
                            f'Volume >= 80% of trailing average ({ind["volume_ratio"]:.1f}x)' if ind['volume_ratio'] is not None else 'Recent trading volume is missing; do not assume normal liquidity',
                            f'Not extended: position in annual range {ind["range_position"]:.0%}'],
            'risk_checks':[f'Price falling below 20-day average ${ma20:.2f}',
                           f'Price falling below 50-day average ${ma50:.2f}',
                           'Negative 5-session model excess-return forecast',
                           'New earnings, dilution or regulatory event requires separate verification'],
            'disclaimer':'Research conditions, not orders, personalized investment recommendations or calibrated odds. Models can be wrong.'}

def live_integrity(closes, volumes, ticker, source):
    """Observable feed checks only; never claim an authenticated PIT archive."""
    px=closes[ticker].astype(float)
    v=volumes[ticker].reindex(px.index) if ticker in volumes else pd.Series(index=px.index,dtype=float)
    jump=px.pct_change(fill_method=None).abs().tail(60).gt(.75).sum()
    missing_volume=int(v.tail(20).isna().sum())
    missing_price=int(px.tail(20).isna().sum())
    warnings=[]
    if jump:warnings.append(f'{int(jump)} large adjusted daily moves in last 60 sessions; verify corporate actions')
    if missing_volume:warnings.append(f'{missing_volume}/20 recent volume observations unavailable, not zero-filled')
    if missing_price:warnings.append(f'{missing_price}/20 recent stock price bars missing (not forward-filled)')
    return {'mode':'current_feed_research_only','point_in_time_universe_verified':False,
        'vendor_authenticity_verified':False,'source':str(source),
        'completed_close_asof':pd.Timestamp(px.dropna().index[-1]).date().isoformat() if px.notna().any() else None,
        'aligned_sessions':int(closes[[ticker,'SPY']].dropna().shape[0]),
        'recent_missing_price':missing_price,'recent_missing_volume':missing_volume,
        'large_adjusted_move_flags':int(jump), 'warnings':warnings,
        'note':'Current Yahoo pages/history do not supply permanent security IDs or an independently verified historical delisted-stock universe. Archive backtests are separate.'}


def configured_archive():
    """Load only an explicitly configured local provider archive, cache by fingerprint."""
    if not ARCHIVE_PATH:raise ValueError('No PIT historical archive configured. Set ITHACA_HISTORICAL_ARCHIVE to a provider-data ZIP (not the v3.1 source-code ZIP).')
    path=Path(ARCHIVE_PATH).expanduser().resolve()
    if not path.is_file():raise ValueError('Configured archive path is missing')
    stat=path.stat()
    fingerprint=(str(path),stat.st_size,stat.st_mtime_ns)
    with archive_lock:
        if archive_cache.get('fingerprint')!=fingerprint:
            bundle=load_historical_archive(path)
            archive_cache.update(fingerprint=fingerprint,bundle=bundle)
        return archive_cache['bundle']


def historical_status():
    if not ARCHIVE_PATH:
        return {'status':'not_configured','source':'none',
          'note':'v3.1 integrity code is installed. No provider-backed historical archive supplied; regular Yahoo price analysis remains research-grade, not survivorship-safe.',
          'audit_status':historical_audit_status()['status']}
    try:
        b=configured_archive()
        return {'status':'loaded','quality':b.quality,
            'source':'provider-declared historical ZIP, checksum-verified',
            'audit_status':historical_audit_status()['status'],
            'note':'Checksums do NOT establish genuine vendor records or complete delisted stock coverage.'}
    except Exception as exc:
        return {'status':'rejected','error':f'{type(exc).__name__}: {str(exc)[:260]}',
           'note':'Historical audit cannot run until archive passes v3.1 integrity validation.',
           'audit_status':historical_audit_status()['status']}


def _run_historical_audit():
    try:
        bundle=configured_archive()
        outcome=run_three_agent_archive_audit(bundle, windows=2,step=20)
        report_file=REPORTS/'Ithaca_v3.1_PIT_Archive_Audit.json'
        report_file.parent.mkdir(parents=True,exist_ok=True)
        report_file.write_text(json.dumps(outcome.summary,indent=2,default=str),encoding='utf-8')
        outcome.forecasts.to_csv(REPORTS/'Ithaca_v3.1_PIT_Archive_Predictions.csv',index=False)
        with archive_audit_lock:
            archive_audit_state.update(status='complete',result=outcome.summary)
    except Exception as exc:
        with archive_audit_lock:
            archive_audit_state.update(status='error',result={
                'status':'error','error':f'{type(exc).__name__}: {str(exc)[:300]}',
                'note':'No historical accuracy result was produced; missing source data must not be imputed.'})


def start_historical_audit():
    if historical_status()['status']!='loaded':
        raise ValueError('A valid v3.1 provider-backed historical archive is required before auditing')
    with archive_audit_lock:
        if archive_audit_state['status']=='running':
            return {'status':'running','message':'One archive audit is already in progress'}
        archive_audit_state.update(status='running',result=None)
    archive_pool.submit(_run_historical_audit)
    return {'status':'running','message':'Running a strict all-member two-window historical audit on the local archive; no stock signals or weekly results will change.'}


def historical_audit_status():
    with archive_audit_lock:
        if archive_audit_state['status']=='running':return {'status':'running'}
        if archive_audit_state['result'] is not None:
            return dict(archive_audit_state['result'],status=archive_audit_state['status'])
        return {'status':archive_audit_state['status']}


def analyze(ticker, provider=get_data, persist=True, *, enhanced=False):
    ticker=valid_ticker(ticker)
    cache_key=(ticker, 'deep' if enhanced else 'fast')
    with cache_lock:
        item=cache.get(cache_key)
        lock=locks.setdefault(cache_key,Lock())
    if item and time.monotonic()-item['at'] < DATA_TTL:
        out=dict(item['value']);out['news']=news_for(ticker);out['cache_hit']=True
        return out
    with lock, workers:
        with cache_lock:
            item=cache.get(cache_key)
        if item and time.monotonic()-item['at'] < DATA_TTL:
            out=dict(item['value']);out['news']=news_for(ticker);out['cache_hit']=True
            return out
        start=time.perf_counter()
        data=provider(ticker)
        closes=data.close[[ticker,'SPY']].dropna(); volumes=data.volume
        if len(closes)<200: raise ValueError('Not enough aligned completed trading sessions')
        daily=closes[ticker]; benchmark=closes['SPY']
        ind=score_indicators(daily,benchmark,volumes[ticker])
        try:
            model=compute_forecast(data,ticker,enhanced=enhanced)
        except Exception as exc:
            model={'state':'unavailable','error':str(exc)[:230],
                   'explanation':'ML model fit failed; directional ratings are withheld (no heuristic substitution).'}
        sig=build_signal(ind,model)
        feed_quality=live_integrity(data.close[[ticker,'SPY']],volumes,ticker,data.source)
        current_vol=volumes[ticker].reindex(closes.index).iloc[-1] if ticker in volumes else None
        missing_critical=(feed_quality['recent_missing_price']>0 or
                          pd.isna(current_vol) or feed_quality['recent_missing_volume']>=4)
        feed_quality['signal_quality_gate_passed']=not missing_critical
        if missing_critical:
            # A forecast is still described as a provisional research result,
            # never an actionable directional signal with missing near-term bars.
            sig=dict(sig,label='DATA QUALITY HOLD',direction_vs_spy=None,
                     signal_strength=None,
                     reason='Recent stock-price/volume observations are missing. Directional research signal withheld until the feed is complete.')
        asof=pd.Timestamp(closes.index[-1]).date().isoformat()
        if persist and not enhanced and not str(data.source).upper().startswith('SYNTHETIC'):
            with ledger_lock:
                c=connect()
                try:
                    resolve(c,ticker,daily,benchmark)
                    record(c,ticker=ticker,asof=asof,label=sig['label'],
                           direction=sig['direction_vs_spy'], strength=sig['signal_strength'],
                           expected_excess_return=model.get('expected_excess_return'),
                           entry_stock=ind['close'],entry_spy=float(benchmark.iloc[-1]),
                           research_metadata={'data_source':data.source,'model_source':'three-fitted-ML-v3.2',
                                'agents':model.get('agents',[]),'validation':model.get('validation',{}),
                                'asof':asof})
                finally:c.close()
        data_out={'ticker':ticker,'asof':asof,'price':round(ind['close'],2),
                  'spy_close':round(float(benchmark.iloc[-1]),2),
                  'data_source':data.source,'price_type':'completed daily adjusted close; NOT real-time',
                  'data_integrity':feed_quality,
                  'model_source':'Ithaca Quant v3.2 features'+ (' · on-demand enhanced model zoo' if enhanced else ' · 3 independently fitted ML agents') + ', 5-session horizon',
                  'agents_limit':MAX_AGENTS,'retries_per_operation':MAX_RETRIES,
                  'generated_utc':datetime.now(timezone.utc).isoformat(),
                  'signal':sig,'forecast':model,
                  'metrics':{k:safe_num(v) if isinstance(v,(int,float,np.number)) else v for k,v in ind.items()},
                  'elapsed_ms':round(1000*(time.perf_counter()-start)),
                  'cache_hit':False, 'enhanced':enhanced,
                  'audited_in_weekly_ledger':not enhanced and persist and not str(data.source).upper().startswith('SYNTHETIC')}
        with cache_lock:cache[cache_key]={'value':data_out,'at':time.monotonic()}
        out=dict(data_out);out['news']=news_for(ticker)
        return out

def insider_for(ticker):
    """Public filed Form 4, fetched on explicit user request only.

    Cannot claim pre-disclosure access; lack of SEC authentication/contact is
    a clear unavailable status, not inferred zero activity.
    """
    ticker=valid_ticker(ticker)
    with cache_lock:
        item=insider_cache.get(ticker)
        if item and time.monotonic()-item['at'] < INSIDER_TTL:
            return item['value']
    contact=os.getenv('ITHACA_SEC_CONTACT','').strip()
    if not contact or '@' not in contact:
        return {'status':'unconfigured','reason':'Set ITHACA_SEC_CONTACT to your SEC-compliant email/organization identifier on the local backend; public Form 4 is optional.', 'transactions':[]}
    try:
        trades=fetch_form4_ticker(ticker,contact,max_filings=5)
        summary=summarize_insider_activity(trades)
        safe=[{k:r.get(k) for k in ('ticker','owner','role','type','shares','price','value_usd','trade_date','filed_date','amended','filing_url')} for r in trades[:18]]
        value={'status':'available','summary':summary,'transactions':safe,
               'checked_utc':datetime.now(timezone.utc).isoformat(),
               'disclaimer':'Only publicly filed Form 4 P/S transactions, not trades before disclosure. Grants and exercises are excluded. Missing filings or external errors never imply zero activity.'}
    except (SECUnavailable, ValueError) as exc:
        value={'status':'unavailable','reason':str(exc)[:190],'transactions':[]}
    with cache_lock:insider_cache[ticker]={'value':value,'at':time.monotonic()}
    return value

def _ranking_work(symbol, include_optional=False):
    """Compute the upgraded grouped, purged research contest without altering signals."""
    try:
        watch=list(dict.fromkeys([symbol,*RANKING_TICKERS]))[:16]
        downloaded=completed_daily(download_market_data(watch, years=6, min_history=350, batch_size=5))
        close=downloaded.close
        usable=[t for t in watch if t in close and close[t].notna().sum()>=440]
        if len(usable)<10:
            raise ValueError(f'Ranking needs at least 10 sufficiently historical stocks; received {len(usable)}')
        panel=build_panel(close[['SPY',*usable]],downloaded.volume.reindex(close.index),horizon=5)
        models=('Histogram rank surrogate','Fixed factor ensemble')
        if include_optional:models+=('LightGBM LambdaMART','XGBoost LambdaMART')
        result=compare_rank_models(panel,asof=pd.Timestamp(close.index[-1]),model_names=models)
        def records(table,limit=24):
            return [ {str(k): (safe_num(v) if isinstance(v,(int,float,np.integer,np.floating)) else str(v))
                      for k,v in row.items()} for row in table.head(limit).to_dict('records')]
        data={'status':'complete','asof':pd.Timestamp(close.index[-1]).date().isoformat(),
              'tickers':usable,'selected_candidate':result.winner,'qualified':False,
              'evidence':str(result.evidence)+' WARNING: current ticker snapshot has survivorship bias; results are exploratory, not point-in-time validated. No candidate may be promoted.', 'selection':records(result.selection_table),
              'audit':records(result.audit_table),'ranks':records(result.current_ranks),
              'research_only':True,'survivorship_status':'CURRENT_UNIVERSE_BIASED','disclaimer':'This comparison uses a current ticker snapshot and omits verified delisted security returns. No promotion permitted. Scores are not calibrated win probabilities.'}
        with rank_lock:rank_state.update({'status':'complete','result':data,'finished_utc':datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        with rank_lock:rank_state.update({'status':'error','result':{'status':'error','error':f'{type(exc).__name__}: {str(exc)[:220]}'}})

def start_ranking(symbol, *, include_optional=False):
    symbol=valid_ticker(symbol)
    with rank_lock:
        if rank_state['status']=='running':
            return {'status':'running','message':'One ranking contest is already running. Multiple requests are coalesced.'}
        rank_state.update({'status':'running','result':None,'started_utc':datetime.now(timezone.utc).isoformat(),
                           'ticker':symbol,'optional_models':bool(include_optional)})
    rank_pool.submit(_ranking_work,symbol,include_optional)
    return {'status':'running','message':'Ranking research launched on a 10+ stock historical panel, independent from the quick signal.'}

def ranking_status():
    with rank_lock:
        status=rank_state['status']; result=rank_state.get('result')
        return result if status in ('complete','error') and result is not None else {'status':status,'started_utc':rank_state.get('started_utc'),'ticker':rank_state.get('ticker')}

def report_ready(week_end, at=None):
    """Do not notify about the current Friday before its close is complete."""
    from datetime import date
    et=(at or datetime.now(EASTERN)).astimezone(EASTERN)
    end=date.fromisoformat(str(week_end))
    return et.date()>end or (et.date()==end and et.hour>=18)

def weekly_update():
    """Called by background scheduler while backend is running, and on startup."""
    with ledger_lock:
        c=connect()
        try:pending=[r[0] for r in c.execute('SELECT DISTINCT ticker FROM forecasts WHERE resolved_utc IS NULL').fetchall()]
        finally:c.close()
    # Limit provider fan-out. These are the previously viewed stocks only.
    for symbol in pending[:100]:
        try:
            data=get_data(symbol)
            joined=data.close[[symbol,'SPY']].dropna()
            with ledger_lock:
                c=connect()
                try:resolve(c,symbol,joined[symbol],joined['SPY'])
                finally:c.close()
        except Exception as exc:
            print('Accuracy pending',symbol,type(exc).__name__,flush=True)
    with ledger_lock:
        c=connect()
        try:
            end=last_friday(datetime.now(EASTERN).date()); out=report(c,end)
        finally:c.close()
    # Rebuild prior weekly snapshots from genuine already-logged outcomes when
    # the computer was off. This does not invent forecasts while it was off.
    with ledger_lock:
        c=connect()
        try:
            oldest=c.execute('SELECT MIN(asof) FROM forecasts').fetchone()[0]
            weeks=pd.date_range(start=oldest if oldest else end,end=end,freq='W-FRI')
            for week in list(weeks)[-52:]:
                week_end=pd.Timestamp(week).date().isoformat()
                write_html(report(c,week_end),REPORTS/f'Ithaca_Weekly_{week_end}.html')
            if not len(weeks):write_html(out,REPORTS/f'Ithaca_Weekly_{end}.html')
        finally:c.close()
    return out

shutdown = Event()
def scheduler():
    # The hourly loop catches late updates, the first completed Friday session,
    # and the next startup after a machine/terminal was off.
    last_run=None
    while not shutdown.is_set():
        now=datetime.now(EASTERN)
        day=now.date().isoformat()
        if (now.hour >= 18 or now.weekday()>=5) and last_run!=day:
            try:
                res=weekly_update()
                print('Weekly research audit updated:',res['week_end'],res['graded'],flush=True)
                last_run=day
            except Exception as exc: print('Weekly audit failed:',type(exc).__name__,str(exc)[:100],flush=True)
        shutdown.wait(900)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt,*args):
        print('%s %s'%(self.address_string(),fmt%args),flush=True)
    def do_GET(self):
        origin=self.headers.get('Origin','')
        # Restrict calls to packaged chrome extensions or local clients.
        if origin and not (re.fullmatch(r'chrome-extension://[a-p]{32}',origin) or
                           origin in ('http://localhost:8765','http://127.0.0.1:8765')):
            self.respond(403,{'error':'Origin not permitted'});return
        parsed=urlparse(self.path); query=parse_qs(parsed.query)
        try:
            if parsed.path=='/health': self.respond(200,{'status':'ok','version':'0.6','upstream_model':'3.2.0','model':'v3.2-features-three-ML-agents','max_agents':3,'max_retries':2, 'weekly_ledger':'three-ML-agent-v3.2-forward-ledger', 'ranking_status':ranking_status()['status'], 'historical_archive_configured':bool(ARCHIVE_PATH),'analyst_portfolio':{'read_only':True,'max_holdings':20,'analyst_data':'on-demand','broker_connected':False}})
            elif parsed.path=='/analyze':
                ticker=query.get('ticker',[''])[0]
                self.respond(200,analyze(ticker,enhanced=query.get('mode',['fast'])[0]=='lab'))
            elif parsed.path=='/models/catalog':
                self.respond(200,{'model_version':'3.2.0','catalog':model_catalog().to_dict('records'),
                                  'note':'Normal monitoring has three separately fitted ML learners. Analyst opinions never train them. This model zoo is on-demand research and never adds a fourth live agent.'})
            elif parsed.path=='/historical/status':
                self.respond(200,historical_status())
            elif parsed.path=='/historical/audit/status':
                self.respond(200,historical_audit_status())
            elif parsed.path=='/analysts':
                self.respond(200,analyst_observation(
                    query.get('ticker',[''])[0],valid_ticker,
                    provider=query.get('provider',['yahoo'])[0],
                    include_actions=query.get('actions',['0'])[0]=='1'))
            elif parsed.path=='/insiders':
                self.respond(200,insider_for(query.get('ticker',[''])[0]))
            elif parsed.path=='/research/ranking/start':
                self.respond(200,start_ranking(query.get('ticker',['AAPL'])[0],include_optional=query.get('optional',['0'])[0]=='1'))
            elif parsed.path=='/research/ranking/status':
                self.respond(200,ranking_status())
            elif parsed.path=='/report/latest':
                with ledger_lock:
                    c=connect()
                    try:r=report(c,last_friday(datetime.now(EASTERN).date()))
                    finally:c.close()
                r['report_ready']=report_ready(r['week_end'])
                self.respond(200,r)
            elif parsed.path=='/report/html':
                with ledger_lock:
                    c=connect()
                    try:r=report(c,last_friday(datetime.now(EASTERN).date()))
                    finally:c.close()
                out=REPORTS / f'Ithaca_Weekly_{r["week_end"]}.html'
                write_html(r,out)
                body=out.read_bytes()
                self.respond_bytes(200,body,'text/html; charset=utf-8')
            elif parsed.path=='/report/csv':
                with ledger_lock:
                    c=connect()
                    try:csv=csv_export(c)
                    finally:c.close()
                self.respond_bytes(200,csv.encode('utf-8'),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="ithaca_ledger.csv"'})
            else: self.respond(404,{'error':'No such endpoint'})
        except ValueError as exc:self.respond(422,{'error':str(exc)})
        except Exception as exc:
            print('Error in API',type(exc).__name__,str(exc)[:250],flush=True)
            self.respond(503,{'error':f'{type(exc).__name__}: {str(exc)[:230]}','note':'No signal generated; do not infer a positive result from unavailable data.'})
    def do_OPTIONS(self):
        origin=self.headers.get('Origin','')
        if not re.fullmatch(r'chrome-extension://[a-p]{32}',origin):
            self.respond(403,{'error':'Chrome extension origin required'});return
        if urlparse(self.path).path != '/portfolio/study':
            self.respond(404,{'error':'Unknown research endpoint'});return
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',origin)
        self.send_header('Access-Control-Allow-Methods','POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Content-Type')
        self.send_header('Access-Control-Max-Age','300')
        self.send_header('Content-Length','0')
        self.send_header('Vary','Origin')
        self.end_headers()

    def do_POST(self):
        origin=self.headers.get('Origin','')
        if not re.fullmatch(r'chrome-extension://[a-p]{32}',origin):
            self.respond(403,{'error':'Action requires a Chrome extension origin'});return
        path=urlparse(self.path).path
        if path not in ('/historical/audit/start','/portfolio/study'):
            self.respond(404,{'error':'No such action'});return
        try:
            if path == '/historical/audit/start':
                self.respond(200,start_historical_audit());return
            if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
                self.respond(415,{'error':'Content-Type application/json required'});return
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 8192:
                self.respond(413,{'error':'Request exceeds safe holdings input size'});return
            raw=self.rfile.read(length)
            payload=json.loads(raw.decode('utf-8'))
            # The user explicitly requests this read-only study; no holdings stored by server.
            # A fresh ticker forecast is NOT inferred from a stale quote or analyst target.
            holdings_in=payload.get('holdings') if isinstance(payload,dict) else []
            forecast_context={}
            if isinstance(holdings_in,list):
                with cache_lock:
                    for h in holdings_in[:20]:
                        if not isinstance(h,dict):continue
                        symbol=str(h.get('ticker','')).strip().upper()
                        info=cache.get((symbol,'fast'))
                        if (info and time.monotonic()-info['at']<DATA_TTL
                              and info.get('value',{}).get('signal',{}).get('direction_vs_spy')):
                            value=info['value']
                            forecast_context[symbol]={**value.get('forecast',{}),'asof':value.get('asof')}
            if not portfolio_slot.acquire(blocking=False):
                self.respond(429,{'error':'One portfolio study is already running. Try again after it finishes.'});return
            try:
                self.respond(200,research_portfolio(payload,valid_ticker,forecasts=forecast_context))
            finally:
                portfolio_slot.release()
        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            self.respond(422,{'error':str(exc)[:230]})
        except Exception as exc:
            print('Portfolio research unavailable:',type(exc).__name__,str(exc)[:220],flush=True)
            self.respond(503,{'error':f'{type(exc).__name__}: {str(exc)[:220]}',
                'note':'No hypothetical weights generated; missing prices or analyst coverage cannot be silently imputed.'})

    def respond(self,status,obj):
        self.respond_bytes(status,json.dumps(obj,default=str,allow_nan=False).encode(),'application/json; charset=utf-8')
    def respond_bytes(self,status,body,ctype,headers=None):
        self.send_response(status)
        origin=self.headers.get('Origin','')
        if origin.startswith('chrome-extension://'):self.send_header('Access-Control-Allow-Origin',origin)
        self.send_header('Vary','Origin')
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'")
        for k,v in (headers or {}).items(): self.send_header(k,v)
        self.end_headers();self.wfile.write(body)

if __name__=='__main__':
    print(f'Ithaca Quant v0.6 bridge listening on http://{HOST}:{PORT}; v3.2 features + three fitted ML agents',flush=True)
    print('Weekly reports write to:',REPORTS,flush=True)
    Thread(target=scheduler,daemon=True,name='weekly-auditor').start()
    try: ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
    except KeyboardInterrupt:shutdown.set()
