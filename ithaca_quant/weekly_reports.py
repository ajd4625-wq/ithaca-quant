"""Weekly forward-forecast scorecards and opt-in notifications.

Only genuinely resolved forward predictions enter performance measurements.
Reports are grouped by outcome evaluation time, not by when a forecast was made.
The Friday schedule is in America/New_York (EST in winter, EDT in summer).
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
import os
import smtplib
import numpy as np
import pandas as pd
from .forecast_audit import read_forecasts
from .market_cache import save_snapshot, load_snapshot

EASTERN = ZoneInfo('America/New_York')

def report_window(when: datetime | None = None):
    dt = when or datetime.now(timezone.utc)
    local = dt.astimezone(EASTERN)
    friday = (local - timedelta(days=(local.weekday() - 4) % 7)).date()
    # A report is issued on a Friday for the trailing 7 calendar days.
    end = datetime.combine(friday, datetime.min.time(), EASTERN).replace(hour=16)
    start = end - timedelta(days=7)
    return start, end

def summarize_week(records: pd.DataFrame, *, end: datetime | None = None):
    """Evaluate observations resolved this week; older rows without a resolution stamp are excluded."""
    start, finish = report_window(end)
    total = len(records)
    clean = records.copy()
    if 'resolved_utc' not in clean:
        clean['resolved_utc'] = pd.NaT
    if 'observed' not in clean:
        clean['observed'] = np.nan
    resolved_at = pd.to_datetime(clean['resolved_utc'], utc=True, errors='coerce')
    start_utc = pd.Timestamp(start.astimezone(timezone.utc))
    end_utc = pd.Timestamp(finish.astimezone(timezone.utc))
    eligible = clean.loc[resolved_at.ge(start_utc) & resolved_at.le(end_utc) & clean['observed'].notna()].copy()
    report = {'week_ending': finish.date().isoformat(), 'window_start_utc': start_utc.isoformat(),
              'window_end_utc': end_utc.isoformat(), 'logged_total': total,
              'evaluated': int(len(eligible)), 'directional_accuracy': None,
              'baseline_mae': None, 'forecast_mae': None,
              'top_positive_hit_rate': None, 'top_positive_n': 0,
              'horizons': {}, 'status': 'insufficient_evidence'}
    if eligible.empty:
        report['status'] = 'no_matured_forecasts'
        return report
    truth = eligible['observed'].astype(float)
    pred = eligible['forecast'].astype(float)
    finite = np.isfinite(truth) & np.isfinite(pred)
    eligible = eligible.loc[finite].copy()
    if eligible.empty:
        report['status'] = 'no_matured_forecasts'
        report['evaluated'] = 0
        return report
    truth, pred = eligible['observed'].astype(float), eligible['forecast'].astype(float)
    report['evaluated'] = len(eligible)
    report['directional_accuracy'] = float(((pred > 0) == (truth > 0)).mean())
    report['forecast_mae'] = float((pred - truth).abs().mean())
    report['baseline_mae'] = float(truth.abs().mean())
    picks = eligible.loc[pred > 0]
    report['top_positive_n'] = len(picks)
    report['top_positive_hit_rate'] = float((picks['observed'] > 0).mean()) if len(picks) else None
    for horizon, part in eligible.groupby('horizon'):
        p = part['forecast'].astype(float)
        t = part['observed'].astype(float)
        report['horizons'][str(int(horizon))] = {
            'n': len(part), 'directional_accuracy': float(((p > 0) == (t > 0)).mean()),
            'mae': float((p - t).abs().mean())}
    # 30 resolved predictions over >= 5 different prediction dates is a modest report
    # floor, NOT sufficient to establish an investment edge or 80% accuracy.
    unique_dates = eligible['asof'].nunique()
    report['status'] = ('preliminary' if len(eligible) >= 30 and unique_dates >= 5
                        else 'insufficient_evidence')
    report['unique_forecast_dates'] = int(unique_dates)
    return report

def render_report(r: dict) -> str:
    def val(x, pct=True):
        return 'Not available' if x is None else (f'{x:.1%}' if pct else f'{x:.2%}')
    lines = [f"Ithaca Quant — Weekly Forecast Report (week ending {r['week_ending']})",
             f"Predictions stored in total: {r['logged_total']}",
             f"Forecasts with outcomes first evaluated this week: {r['evaluated']}",
             f"SPY-relative directional hit rate: {val(r['directional_accuracy'])}",
             f"Model mean absolute error: {val(r['forecast_mae'])}",
             f"Predict-zero mean absolute error: {val(r['baseline_mae'])}",
             f"Positive-signal hit rate: {val(r['top_positive_hit_rate'])} ({r['top_positive_n']} evaluated)",
             'By prediction horizon:']
    for h, b in sorted(r['horizons'].items(), key=lambda v:int(v[0])):
        lines.append(f"  {h} sessions: {b['n']} resolved; {val(b['directional_accuracy'])} direction; {val(b['mae'])} MAE")
    lines += ['', 'Evidence quality: '+r['status'].replace('_',' '),
              'Results describe only resolved forward predictions, not current or unfinished ones.',
              'The report is NOT proof of 80% prediction accuracy or a guaranteed future return.',
              'No trading or brokerage action is taken.']
    return '\n'.join(lines)

def save_weekly_report(report: dict, *, path=None):
    return save_snapshot('weekly:'+report['week_ending'], 'weekly_forecast_report', report, path=path)

def load_weekly_report(week_ending: str, *, path=None):
    saved = load_snapshot('weekly:'+week_ending, 'weekly_forecast_report', path=path)
    return saved[0] if saved else None

def make_weekly_report(*, when=None, path=None, persist=True):
    report = summarize_week(read_forecasts(path), end=when)
    if persist:
        save_weekly_report(report, path=path)
    return report

def send_weekly_email(report: dict, *, environ=None, sender=None):
    """Opt-in SMTP delivery. No embedded passwords; no message sent without configuration."""
    env = os.environ if environ is None else environ
    required = ('ITHACA_REPORT_EMAIL_TO', 'ITHACA_SMTP_HOST', 'ITHACA_SMTP_USER', 'ITHACA_SMTP_PASSWORD')
    if any(not str(env.get(k, '')).strip() for k in required):
        return False
    message = EmailMessage()
    message['From'] = sender or env.get('ITHACA_REPORT_EMAIL_FROM') or env['ITHACA_SMTP_USER']
    message['To'] = env['ITHACA_REPORT_EMAIL_TO']
    message['Subject'] = 'Ithaca Quant weekly forecast report — '+report['week_ending']
    message.set_content(render_report(report))
    port = int(env.get('ITHACA_SMTP_PORT') or '465')
    # Enforce TLS; never send credentials over plaintext SMTP.
    with smtplib.SMTP_SSL(env['ITHACA_SMTP_HOST'], port, timeout=20) as smtp:
        smtp.login(env['ITHACA_SMTP_USER'], env['ITHACA_SMTP_PASSWORD'])
        smtp.send_message(message)
    return True
