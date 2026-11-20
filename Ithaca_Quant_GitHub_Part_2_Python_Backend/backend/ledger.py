"""Immutable, point-in-time forward research signal ledger with SPY-relative grading.

The price+SPY comparison matches the supplied Ithaca Quant model's *excess-return*
target. No scoring before five complete later sessions; neutral is an abstention.
Never store demo market data in the real ledger.
"""
from __future__ import annotations
from datetime import datetime, timezone, date, timedelta
from pathlib import Path
import csv, io, sqlite3, html, json, math

# Separate v3.2 ledger and earlier models; never conflate their outcomes.
DEFAULT_DB = Path(__file__).resolve().parent / 'research_ledger_three_ml_v32.sqlite3'
MODEL_VERSION = '3.2.0-three-ml' 

def connect(path=DEFAULT_DB):
    c = sqlite3.connect(str(path), timeout=20, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS forecasts (
      id INTEGER PRIMARY KEY,
      ticker TEXT NOT NULL,
      model_version TEXT NOT NULL DEFAULT '3.2.0-three-ml',
      asof TEXT NOT NULL,
      logged_utc TEXT NOT NULL,
      horizon INTEGER NOT NULL DEFAULT 5,
      direction TEXT,
      label TEXT NOT NULL,
      signal_strength REAL,
      expected_excess_return REAL,
      entry_stock REAL NOT NULL,
      entry_spy REAL NOT NULL,
      outcome_date TEXT,
      outcome_stock REAL,
      outcome_spy REAL,
      stock_return REAL,
      spy_return REAL,
      realized_excess_return REAL,
      correct INTEGER,
      resolved_utc TEXT,
      research_metadata_json TEXT,
      UNIQUE(ticker, asof, horizon)
    );
    ''')
    return c

def record(c, *, ticker, asof, label, direction, strength,
           expected_excess_return, entry_stock, entry_spy, horizon=5, research_metadata=None):
    if direction not in ('UP', 'DOWN', None):
        raise ValueError('Invalid direction')
    if horizon != 5 or entry_stock <= 0 or entry_spy <= 0:
        raise ValueError('Invalid horizon/entry prices')
    if strength is not None and not 0 <= strength <= 100:
        raise ValueError('Invalid signal strength')
    with c:
        q = c.execute('''INSERT OR IGNORE INTO forecasts
          (ticker,model_version,asof,logged_utc,horizon,direction,label,signal_strength,
          expected_excess_return,entry_stock,entry_spy,research_metadata_json)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (
          ticker, MODEL_VERSION, str(asof), datetime.now(timezone.utc).isoformat(),horizon,
          direction,label,strength,expected_excess_return,entry_stock,entry_spy,
          json.dumps(research_metadata or {},sort_keys=True,default=str)
        ))
    return q.rowcount == 1

def resolve(c, ticker, stock, spy):
    """Resolve when >=5 later *common* sessions of completed adjusted closes exist.

    Index may be pd.Timestamp or ISO date; fully completed-bar filtering happens
    before this function, in the data provider. Never interpolate missing dates.
    """
    import pandas as pd
    paired = pd.concat([pd.to_numeric(stock, errors='coerce'), pd.to_numeric(spy, errors='coerce')], axis=1)
    paired = paired.dropna().sort_index()
    paired = paired[(paired.iloc[:, 0] > 0) & (paired.iloc[:, 1] > 0)]
    dates = [x.date().isoformat() if hasattr(x, 'date') else str(x)[:10] for x in paired.index]
    pending = c.execute('SELECT * FROM forecasts WHERE ticker=? AND resolved_utc IS NULL', (ticker,)).fetchall()
    updated = 0
    for p in pending:
        if p['asof'] not in dates: continue
        ix = dates.index(p['asof']) + p['horizon']
        if ix >= len(paired): continue
        stock_end, spy_end = map(float, paired.iloc[ix])
        # Use entry and exit on one consistently back-adjusted data basis.
        # Frozen original entry prices remain in the ledger for provenance,
        # but would be inconsistent following later stock splits/dividends.
        common_entry_stock, common_entry_spy = map(float, paired.iloc[ix-p['horizon']])
        stock_r = stock_end / common_entry_stock - 1
        spy_r = spy_end / common_entry_spy - 1
        ex = stock_r - spy_r
        right = None if p['direction'] is None else int((ex > 0) if p['direction']=='UP' else (ex < 0))
        with c:
            c.execute('''UPDATE forecasts SET outcome_date=?, outcome_stock=?,
            outcome_spy=?, stock_return=?, spy_return=?, realized_excess_return=?,
            correct=?, resolved_utc=? WHERE id=? AND resolved_utc IS NULL''', (
              dates[ix],stock_end,spy_end,stock_r,spy_r,ex,right,
              datetime.now(timezone.utc).isoformat(),p['id']))
        updated += 1
    return updated

def wilson_95(successes, n):
    """95% Wilson score interval for binomial directions (not adjusted for clusters)."""
    if not n:return None
    z=1.95996398454
    p=successes/n
    denominator=1+z*z/n
    center=(p+z*z/(2*n))/denominator
    margin=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denominator
    return [round(100*max(0,center-margin),1),round(100*min(1,center+margin),1)]


def independent_date_accuracy(rows):
    """Count date cohorts separately; same-day ticker outcomes are correlated."""
    cohorts={}
    for row in rows:
        cohorts.setdefault(row['asof'],[]).append(int(row['correct']))
    if not cohorts:return None
    return round(100*sum(sum(values)/len(values) for values in cohorts.values())/len(cohorts),1)


def lifetime_report(c):
    # Preserved across all weeks; don't let one unusually good week masquerade
    # as a sufficiently long production record.
    records=c.execute('SELECT * FROM forecasts WHERE resolved_utc IS NOT NULL AND correct IS NOT NULL').fetchall()
    n=len(records); k=sum(int(x['correct']) for x in records)
    issued=c.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0]
    distinct=len(set(x['asof'] for x in records))
    abs_errors=[abs(x['realized_excess_return']-x['expected_excess_return']) for x in records if x['expected_excess_return'] is not None]
    zero_errors=[abs(x['realized_excess_return']) for x in records if x['expected_excess_return'] is not None]
    return {'graded':n,'correct':k,'accuracy_pct':round(100*k/n,1) if n else None,
            'wilson95_pct':wilson_95(k,n),'independent_issue_dates':distinct,
            'date_cohort_accuracy_pct':independent_date_accuracy(records),
            'issued_total':issued,'directional_coverage_pct':round(100*n/max(1,issued),1),
            'forecast_mae_pct':round(100*sum(abs_errors)/len(abs_errors),2) if abs_errors else None,
            'zero_baseline_mae_pct':round(100*sum(zero_errors)/len(zero_errors),2) if zero_errors else None,
            'evidence_state': ('forward_track_record_developing' if n>=100 and distinct>=30
                               else 'insufficient_forward_market_evidence'),
            'caveat':'Multiple tickers from the same issue date are not statistically independent. Even 100 outcomes across 30 dates are preliminary evidence, not proof of future profitability.'}


def bounds(week_end):
    end = date.fromisoformat(week_end)
    if end.weekday()!=4: raise ValueError('End date must be Friday')
    return (end - timedelta(days=4)).isoformat(),end.isoformat()

def last_friday(now=None):
    now = now or date.today()
    return (now - timedelta(days=(now.weekday()-4)%7)).isoformat()

def report(c, week_end):
    start, end = bounds(week_end)
    issued = c.execute('SELECT * FROM forecasts WHERE asof BETWEEN ? AND ?', (start,end)).fetchall()
    settled = c.execute('''SELECT * FROM forecasts WHERE outcome_date BETWEEN ? AND ? AND resolved_utc IS NOT NULL
                           ORDER BY outcome_date DESC, ticker''',(start,end)).fetchall()
    graded = [x for x in settled if x['direction'] is not None and x['correct'] is not None]
    score = lambda xs: round(100*sum(int(x['correct']) for x in xs)/len(xs),1) if xs else None
    up = [x for x in graded if x['direction']=='UP']; down = [x for x in graded if x['direction']=='DOWN']
    average = lambda k: round(100*sum(x[k] for x in graded)/len(graded),2) if graded else None
    lifetime=lifetime_report(c)
    return {
        'lifetime':lifetime,
        'week_start':start,'week_end':end,'model_version':MODEL_VERSION,
        'issued':len(issued),'directional_issued':sum(x['direction'] is not None for x in issued),
        'abstained_issued':sum(x['direction'] is None for x in issued),
        'resolved_this_week':len(settled), 'graded':len(graded),
        'correct':sum(x['correct'] for x in graded),'accuracy_pct':score(graded),
        'up_accuracy_pct':score(up),'down_accuracy_pct':score(down),
        'mean_excess_return_pct':average('realized_excess_return'),
        'mean_stock_return_pct':average('stock_return'),
        'mean_spy_return_pct':average('spy_return'),
        'mean_abs_error_pct':round(100*sum(abs(x['realized_excess_return']-x['expected_excess_return']) for x in graded if x['expected_excess_return'] is not None)/len([x for x in graded if x['expected_excess_return'] is not None]),2) if any(x['expected_excess_return'] is not None for x in graded) else None,
        'minimum_sample_warning':len(graded) < 30,
        'week_wilson95_pct':wilson_95(sum(x['correct'] for x in graded),len(graded)),
        'pending_total':c.execute('SELECT COUNT(*) FROM forecasts WHERE resolved_utc IS NULL').fetchone()[0],
        'methodology':'Model v3.2 independently fitted three-ML-agent signals only; opt-in model-zoo forecasts are excluded. Forecasts are fixed on the observed completed close. A forecast predicts 5-session SPY-relative excess return, not a guaranteed rising share price. Correct means realized excess-return sign matched the frozen direction, measured after exactly five subsequent common completed trading sessions. Repeated page refreshes never duplicate a ticker/date forecast. Historical split/dividend adjustments may revise the adjusted return calculation, while the prediction remains frozen. Directionless signals are logged but excluded from directional accuracy. Same-date signals are correlated, and Wilson intervals assume independent events, so they can be too narrow. Forecast MAE is compared against a zero excess-return baseline. No fees, slippage, executions or verified point-in-time historical-stock-universe audit.',
        'rows':[{'ticker':x['ticker'],'asof':x['asof'],'direction':x['direction'] or 'ABSTAIN',
                 'label':x['label'],'model_version':x['model_version'],'outcome_date':x['outcome_date'],
                 'actual_excess_pct':round(100*x['realized_excess_return'],2),
                 'expected_excess_pct':round(100*x['expected_excess_return'],2) if x['expected_excess_return'] is not None else None,
                 'correct':bool(x['correct']) if x['correct'] is not None else None} for x in settled[:200]],
    }

def csv_export(c):
    rows = c.execute('SELECT * FROM forecasts ORDER BY logged_utc DESC').fetchall()
    fields = [d[1] for d in c.execute('PRAGMA table_info(forecasts)')]
    buffer=io.StringIO(); writer=csv.DictWriter(buffer,fieldnames=fields); writer.writeheader()
    for row in rows: writer.writerow(dict(row))
    return buffer.getvalue()

def write_html(r, path):
    esc=lambda v: html.escape('—' if v is None else str(v))
    accuracy = f"{r['accuracy_pct']:.1f}%" if r['accuracy_pct'] is not None else 'Not enough resolved signals'
    parts=[f'<tr><td>{esc(x["ticker"])}</td><td>{esc(x["asof"])}</td><td>{esc(x["direction"])}</td><td>{esc(x["outcome_date"])}</td><td>{esc(x["actual_excess_pct"])}%</td><td>{esc(x["correct"])}</td></tr>' for x in r['rows']]
    content=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Ithaca Quant Weekly Research Audit {esc(r['week_end'])}</title><style>
    body{{background:#0b1326;color:#e5effb;font:16px system-ui;margin:auto;max-width:900px;padding:42px}}
    h1{{font-size:30px}}.small{{color:#9cafc8}}.tile{{padding:22px;background:#14223c;border:1px solid #29405f;border-radius:14px;display:inline-block;margin:6px}}
    .big{{font-size:27px;font-weight:750}}table{{width:100%;border-collapse:collapse}}td,th{{padding:11px;border-bottom:1px solid #293e5b;text-align:left}}th{{color:#9eb8d7}}
    </style><h1>Ithaca Quant · Weekly Accuracy Audit</h1><p class="small">{esc(r['week_start'])} – {esc(r['week_end'])} · actual recorded signals</p>
    <div class="tile"><div class="small">5-session SPY-relative directional accuracy</div><div class="big">{accuracy}</div></div>
    <div class="tile"><div class="small">Graded outcomes</div><div class="big">{r['graded']}</div></div>
    <div class="tile"><div class="small">Signals logged this week</div><div class="big">{r['issued']}</div></div>
    <div class="tile"><div class="small">Pending</div><div class="big">{r['pending_total']}</div></div>
    <p class="small">Lifetime forward record: {r['lifetime']['graded']} mature directional forecasts over {r['lifetime']['independent_issue_dates']} independent issue dates. Accuracy: {esc(r['lifetime']['accuracy_pct'])}%; Wilson 95% (assumes independence): {esc(r['lifetime']['wilson95_pct'])}. MAE: {esc(r['lifetime']['forecast_mae_pct'])}% versus 0-excess baseline {esc(r['lifetime']['zero_baseline_mae_pct'])}%. Evidence: {esc(r['lifetime']['evidence_state'])}.</p>
    <p>{'⚠ Fewer than 30 graded results: accuracy is statistically unstable.' if r['minimum_sample_warning'] else 'Sample count is shown; outcomes are still not guaranteed.'}</p>
    <h2>Resolved signals</h2><table><thead><tr><th>Stock</th><th>Issued</th><th>Forecast</th><th>Checked</th><th>Excess return</th><th>Correct</th></tr></thead><tbody>{''.join(parts) or '<tr><td colspan="6">No resolved forecasts this week. Monitoring starts accruing data after installation.</td></tr>'}</tbody></table>
    <h2>Methodology</h2><p class="small">{esc(r['methodology'])}</p></html>'''
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(content,encoding='utf-8')
    return path
