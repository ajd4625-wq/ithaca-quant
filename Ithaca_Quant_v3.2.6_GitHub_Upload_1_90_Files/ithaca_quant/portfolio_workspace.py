"""Isolated owned-holdings UI; avoids the costly marketwide scan entirely.

This module intentionally imports Streamlit only in the web workflow; the
ledger and accounting rules in holdings.py are independently unit-testable.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math
import os
import hashlib
import pandas as pd
try:
    import streamlit as st
except ModuleNotFoundError:
    st = None  # Unit tests can validate imports without installed web dependencies.

from . import holdings
from .account_auth import account_access_code, claims_from_user
from .portfolio_image import extract_picture_positions, extract_picture_positions_local, confirm_rows
from .portfolio_lights import classify_holding
from .config import INITIAL_CAPITAL
from .fundamentals import public_quarterly_snapshot
from .news_intelligence import analyze_news
from .news_archive import recorded_headlines
from .search import price_scenarios
from .signals import plan_signals
from .analyst_consensus import fetch_yahoo, fetch_finnhub, fetch_yahoo_actions, fetch_finnhub_actions, snapshot_to_row, is_fresh
from .portfolio_advisor import portfolio_allocation_study


def _fmt_cash(value, decimals=2):
    return 'Unavailable' if value is None or pd.isna(value) else f'${float(value):,.{decimals}f}'


def _fmt_pct(value):
    return 'Unavailable' if value is None or pd.isna(value) else f'{float(value):+.2%}'


def _signal_cell_style(value):
    """Subtle cell fill makes the actual entry/exit class visible in the table."""
    label = str(value)
    if label.startswith('🟩'):
        return 'background-color: #14532d; color: #ffffff; font-weight: bold'
    if label.startswith('🟢'):
        return 'background-color: #dcfce7; color: #14532d; font-weight: bold'
    if label.startswith('🔴'):
        return 'background-color: #fee2e2; color: #7f1d1d; font-weight: bold'
    return 'background-color: #fef3c7; color: #713f12; font-weight: bold'


def _as_float(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def _secrets_value(key, default=''):
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, KeyError, AttributeError):
        return default


def _account_configured():
    """Native OIDC is only turned on when its full credentials are present."""
    auth = _secrets_value('auth', {})
    try:
        return bool(all(auth.get(k) for k in
                        ('redirect_uri','cookie_secret','client_id','client_secret','server_metadata_url')))
    except (AttributeError, TypeError):
        return False


def _account_panel():
    st.subheader('🔐 My Portfolio — sign in to save your holdings')
    if not getattr(st.user, 'is_logged_in', False):
        st.caption('Sign in to open the same portfolio on any device. No recovery codes are required.')
        if st.button('Sign in with Google', type='primary', key='iq_oidc_login'):
            st.login()
        return None
    try:
        subject, issuer = claims_from_user(st.user)
        auth_cfg = _secrets_value('auth',{})
        secret = _secrets_value('ITHACA_ACCOUNT_ID_SECRET') or auth_cfg.get('cookie_secret','')
        code = account_access_code(subject, issuer, str(secret))
    except ValueError:
        st.error('Your identity provider did not return a stable subject and issuer. Sign-in cannot safely identify your holdings.')
        return None
    left, right = st.columns([4, 1])
    with left:
        st.success('Signed in. Your portfolio is associated with your account, not a recovery code.')
    with right:
        if st.button('Sign out', key='iq_oidc_logout'):
            st.logout()
    url = _secrets_value('ITHACA_DATABASE_URL')
    if url and not os.environ.get('ITHACA_DATABASE_URL'):
        os.environ['ITHACA_DATABASE_URL'] = str(url)
    if not holdings.is_durable_cloud_storage():
        st.warning('Account sign-in is active, but holdings are saved to local SQLite. On Streamlit Cloud, '
                   'they can disappear after a restart. Configure ITHACA_DATABASE_URL with PostgreSQL '
                   'in Streamlit Secrets before trusting cross-device persistence.')
    try:
        if not holdings.portfolio_exists(code):
            holdings.create_portfolio(code)
    except Exception as exc:
        st.error(f'Account portfolio storage unavailable ({type(exc).__name__}). Check database connectivity.')
        return None
    with st.expander('Move an older code-based portfolio into this signed-in account'):
        st.caption('One-time migration: enter the OLD recovery code only if you previously saved a portfolio under one. '
                   'Imported transactions are added to this account; do this only once to avoid duplicates.')
        with st.form('iq_migrate_legacy'):
            old_code = st.text_input('Old recovery code',type='password')
            confirm = st.checkbox('I verified this account has not already imported these transactions.')
            go = st.form_submit_button('Import old transactions')
        if go:
            if not confirm:
                st.error('Check the confirmation box before migrating.')
            else:
                try:
                    if holdings.get_trades(code):
                        raise ValueError('This signed-in portfolio already has transactions. Export first to avoid duplicates.')
                    if old_code == code:
                        raise ValueError('Use a different legacy portfolio.')
                    history = holdings.get_trades(old_code)
                    rows = [{k:r[k] for k in ('ticker','side','shares','price','trade_date','fees')} for r in history]
                    num = holdings.import_trades(code,rows)
                    st.success(f'Migrated {num} transactions. You can now sign in without the old code.')
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f'Migration failed ({type(exc).__name__}).')
    return code


def _access_panel():
    if _account_configured():
        return _account_panel()
    # Backwards compatible with existing portfolios until server auth is set up.
    st.info('Account sign-in is not configured yet. To use Google sign-in without codes, '
            'add [auth] OIDC credentials and a PostgreSQL ITHACA_DATABASE_URL in Streamlit Secrets. '
            'Your existing recovery-code portfolios remain accessible below.')
    st.subheader('💼 My Portfolio — saved holdings')
    st.caption('Save the ticker, number of shares, and actual purchase price. No marketwide scan or trading-account connection required.')
    if not holdings.is_durable_cloud_storage():
        st.warning('**Cloud persistence is not configured.** Records are saved to local SQLite, which typically survives a tab close but may disappear after a Streamlit Community Cloud reboot or redeploy. Configure ITHACA_DATABASE_URL with PostgreSQL for reliable cross-session storage, and download a CSV backup.')
    code = st.session_state.get('iq_portfolio_access')
    if code:
        if st.button('🔒 Lock portfolio on this browser', key='iq_lock'):
            st.session_state.pop('iq_portfolio_access', None)
            st.session_state.pop('iq_just_created', None)
            st.rerun()
        if st.session_state.get('iq_just_created'):
            st.success('Portfolio created. **Save this recovery code in a secure place now.** It is the only way to unlock this portfolio on a new tab or device.')
            st.code(code, language=None)
            if st.button('I saved my recovery code', key='iq_confirm_recovery'):
                st.session_state.pop('iq_just_created', None)
                st.rerun()
        return code
    create_col, unlock_col = st.columns(2)
    with create_col:
        st.markdown('**Start a new portfolio**')
        st.caption('Generate a unique access code and start entering your real competition fills.')
        if st.button('Create my saved portfolio', type='primary', key='iq_make_portfolio'):
            try:
                new_code = holdings.new_access_code()
                holdings.create_portfolio(new_code)
                st.session_state['iq_portfolio_access'] = new_code
                st.session_state['iq_just_created'] = True
                st.rerun()
            except Exception as exc:
                st.error(f'Could not create portfolio ({type(exc).__name__}). Check storage configuration.')
    with unlock_col:
        st.markdown('**Open an existing portfolio**')
        with st.form('iq_unlock_form'):
            entered = st.text_input('Saved recovery code', type='password', placeholder='IQ-…')
            submitted = st.form_submit_button('Unlock saved holdings')
        if submitted:
            try:
                if not holdings.portfolio_exists(entered):
                    raise ValueError('Not found. Verify that you used the original code and the same database.')
                st.session_state['iq_portfolio_access'] = entered.strip()
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f'Database unavailable ({type(exc).__name__}).')
    st.info('The recovery code is a private bearer key: anyone with it can view or change the portfolio. Do not post it in GitHub, public screenshots, or a shared link. If it is lost, the app cannot recover the original portfolio.')
    return None



def _picture_import_panel(code):
    with st.expander('📷 Import holdings from a screenshot', expanded=False):
        st.caption('Upload a screenshot of your virtual competition portfolio. The optional vision service '
                   'creates a draft; it does **not** save anything until you review every row and confirm. '
                   'The image is sent to the configured AI API only when you click Analyze screenshot. '
                   'Images are not stored in the portfolio database. API usage may incur charges.')
        picture = st.file_uploader('Portfolio picture (PNG, JPG or WebP, maximum 8 MB)',
                                   type=['png','jpg','jpeg','webp'], key='iq_portfolio_photo')
        if picture is not None:
            blob = picture.getvalue()
            if len(blob) > 8 * 1024 * 1024:
                st.error('The maximum image size is 8 MB.')
                return
            st.image(blob, caption='Review the screenshot before sending it for extraction', width=550)
            digest = hashlib.sha256(blob).hexdigest()
            if st.session_state.get('iq_photo_hash') != digest:
                st.session_state.pop('iq_photo_rows', None)
                st.session_state.pop('iq_photo_notes', None)
                st.session_state['iq_photo_hash'] = digest
            api_key = _secrets_value('OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY','')
            st.caption('Start with **Read locally (no key)**. If the screenshot is complex, configure '
                       'OPENAI_API_KEY and choose AI extraction. Both methods create editable drafts; '
                       'neither automatically saves transactions.')
            left, right = st.columns(2)
            local_click = left.button('📷 Read screenshot locally — no API key',
                                      key='iq_read_local_picture', type='primary')
            ai_click = right.button('✨ Read screenshot using AI', key='iq_read_picture',
                                    disabled=not bool(api_key))
            if not api_key:
                st.caption('AI reading is optional and needs OPENAI_API_KEY in Streamlit Secrets. '
                           'Local reading works without it when the OCR dependency is installed.')
            if local_click or ai_click:
                try:
                    mime = 'image/jpeg' if picture.type in ('image/jpeg', 'image/jpg') else picture.type
                    with st.spinner('Reading screenshot and preparing an editable draft…'):
                        if local_click:
                            result = extract_picture_positions_local(blob, mime)
                        else:
                            result = extract_picture_positions(blob, mime, api_key)
                    st.session_state['iq_photo_rows'] = result['positions']
                    st.session_state['iq_photo_notes'] = result['notes']
                    if not result['positions']:
                        st.warning('No stock symbols could be identified. Use the blank review row below, '
                                   'or crop/zoom the screenshot and try again.')
                except Exception as exc:
                    st.error(f'Screenshot extraction failed: {exc}')
                    st.info('You can still add positions using the manual trade form below. '
                            'For local OCR on Streamlit Cloud, install packages.txt and pytesseract.')
            if st.button('✍️ Start a blank screenshot review row', key='iq_photo_blank'):
                st.session_state['iq_photo_rows'] = [dict(ticker='', side='BUY', shares=None,
                        price=None, trade_date='', fees=0., confidence='uncertain')]
                st.session_state['iq_photo_notes'] = ['Enter the ticker, original number of shares, '
                        'actual fill price and transaction date before confirming.']
        if st.session_state.get('iq_photo_rows') is not None and st.session_state.get('iq_photo_hash'):
            rows = st.session_state['iq_photo_rows']
            if rows is not None:
                st.markdown('**Review and correct the proposed purchases**')
                st.warning('Missing values are left blank deliberately. **Current market price is not purchase price.** '
                           'Add the real purchase date and original fill price; review share counts. '
                           'A holdings screenshot cannot reconstruct prior sales or historical cash flows.')
                # Each draft position becomes ONE BUY entry, not a live trade or market order.
                grid = pd.DataFrame(rows, columns=['ticker','side','shares','price','trade_date','fees','confidence'])
                edited = st.data_editor(grid, use_container_width=True, hide_index=True,
                    num_rows='dynamic', key='iq_picture_editor',
                    column_config={
                        'ticker':st.column_config.TextColumn('Ticker',required=True),
                        'side':st.column_config.TextColumn('Side (BUY only)',disabled=True),
                        'shares':st.column_config.NumberColumn('Shares owned',min_value=0.,format='%.3f'),
                        'price':st.column_config.NumberColumn('Purchase price per share ($)',min_value=0.,format='$%.3f'),
                        'trade_date':st.column_config.TextColumn('Actual purchase date (YYYY-MM-DD)'),
                        'fees':st.column_config.NumberColumn('Fees ($)',min_value=0.,format='$%.2f'),
                        'confidence':st.column_config.TextColumn('OCR confidence',disabled=True),
                    })
                for note in st.session_state.get('iq_photo_notes', [])[:5]:
                    st.caption('Extraction note: '+note)
                previous = {r['ticker'] for r in holdings.get_trades(code)}
                overlap = sorted(set(edited['ticker'].astype(str).str.upper()) & previous)
                acknowledged = True
                if overlap:
                    st.warning('These symbols already have recorded transactions: '+', '.join(overlap)+'. '
                               'Importing a current-holdings screenshot ADDS buys; it does not replace the old portfolio.')
                    acknowledged = st.checkbox('I reviewed my existing transactions and want to ADD these purchases',
                                               key='iq_photo_add_confirm')
                if st.button('Confirm and save reviewed purchases',type='primary',key='iq_save_photo',
                             disabled=not acknowledged):
                    try:
                        checked = confirm_rows(edited.to_dict('records'))
                        count = holdings.import_trades(code,checked,
                                    source_hash=st.session_state['iq_photo_hash'])
                        st.session_state.pop('iq_photo_rows',None)
                        st.session_state.pop('iq_photo_notes',None)
                        st.success(f'Saved {count} verified purchases to your portfolio.')
                        st.rerun()
                    except (ValueError,TypeError,KeyError) as exc:
                        st.error(str(exc))
                    except Exception as exc:
                        st.error(f'Could not save image-derived purchases ({type(exc).__name__}).')
                st.caption('The same screenshot cannot be imported twice into this portfolio. '                           'For a new purchase, use the transaction form below.')


def _trade_form(code, trades):
    with st.expander('➕ Add a purchase or record a sale', expanded=not bool(trades)):
        with st.form('iq_record_trade', clear_on_submit=False):
            left, mid, right = st.columns(3)
            with left:
                side = st.radio('Transaction', ['BUY', 'SELL'], horizontal=True)
                ticker = st.text_input('Ticker', placeholder='RKLB', max_chars=12)
            with mid:
                shares = st.number_input('Number of shares', min_value=0.001, value=100.0,
                                         step=1.0, format='%.3f')
                price = st.number_input('Actual fill price per share ($)', min_value=0.001,
                                        value=100.0, step=0.01, format='%.3f')
            with right:
                trade_on = st.date_input('Transaction date', value=date.today(), max_value=date.today())
                fees = st.number_input('Trading fees ($)', min_value=0.0, value=0.0, step=0.01)
            st.caption('Enter what your team actually purchased or sold in StockTrak. Multiple buys at different prices are supported. Nothing here places an order.')
            submit = st.form_submit_button('Save transaction', type='primary')
        if submit:
            try:
                holdings.add_trade(code, ticker, side, shares, price, trade_on.isoformat(), fees)
                st.success(f'{side} transaction saved.')
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f'Could not save transaction: {type(exc).__name__}.')


def _ledger_panel(code, trades):
    with st.expander('📒 Purchase/sale history, backups and corrections'):
        if trades:
            view = pd.DataFrame([{k:r[k] for k in ('trade_date','ticker','side','shares','price','fees')} for r in trades])
            st.dataframe(view, hide_index=True, use_container_width=True, column_config={
                'shares':st.column_config.NumberColumn('Shares', format='%.3f'),
                'price':st.column_config.NumberColumn('Fill price ($)', format='$%.2f'),
                'fees':st.column_config.NumberColumn('Fees ($)', format='$%.2f'),
            })
            st.download_button('⬇️ Download transactions CSV backup', holdings.export_trades_csv(trades),
                               file_name='ithaca_quant_portfolio_trades.csv', mime='text/csv',
                               help='Backup contains trade information, not your private recovery code.')
            options = [r['id'] for r in trades]
            labels = {r['id']:f"{r['trade_date']} · {r['side']} {r['shares']:g} {r['ticker']} @ ${r['price']:,.2f}" for r in trades}
            with st.form('iq_delete_trade_form'):
                chosen = st.selectbox('Correct a mistaken transaction (remove and re-enter)', options,
                                      format_func=lambda item:labels[item])
                confirm = st.checkbox('I understand this deletes the selected entry')
                remove = st.form_submit_button('Delete selected transaction')
            if remove:
                if not confirm:
                    st.error('Check the confirmation box before deleting a transaction.')
                else:
                    try:
                        holdings.delete_trade(code, chosen)
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            st.caption('No saved transactions yet.')
        st.caption('Save your recovery code separately. CSV backups can be reviewed outside the app; do not upload confidential account information.')
        st.caption('Import is additive: importing the same CSV twice will **duplicate transactions**. Do not import a backup you already restored.')
        upload = st.file_uploader('Restore transactions from an Ithaca Quant CSV backup', type='csv', key='iq_restore_csv')
        if upload is not None:
            if st.button('Import all rows into this portfolio', key='iq_import_backup'):
                try:
                    raw = pd.read_csv(upload)
                    needed = {'ticker','side','shares','price','trade_date','fees'}
                    if not needed.issubset(raw.columns):
                        raise ValueError('CSV must include ticker, side, shares, price, trade_date and fees.')
                    if len(raw) > 5000:
                        raise ValueError('Maximum of 5,000 rows per import.')
                    rows = raw[list(needed)].to_dict('records')
                    count = holdings.import_trades(code, rows)
                    st.success(f'Imported {count} transactions.')
                    st.rerun()
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
                except Exception as exc:
                    st.error(f'Import failed ({type(exc).__name__}).')


def _forecast_one(code, ticker, horizon, *, mode, cached_single_symbol,
                  cached_panel, cached_ranking, cached_sec_quarters, sec_contact,
                  enhanced=False, fast=True):
    if mode == 'Synthetic demo':
        raise ValueError('Turn off Synthetic demo to save forecasts based on real data.')
    market = cached_single_symbol(ticker, 'Yahoo Finance', 5)
    if ticker not in market.close or market.close[ticker].dropna().empty:
        raise ValueError('No sufficient current historical prices were retrieved.')
    archive = None
    try:
        archived = recorded_headlines(ticker)
        if not archived.empty:
            archive = {ticker:archived}
    except Exception:
        pass
    fund = None
    if sec_contact:
        try:
            snapshot, company, vintage_history = cached_sec_quarters(ticker, sec_contact)
            if vintage_history is not None and not vintage_history.empty:
                fund = {ticker:vintage_history}
        except Exception:
            pass
    if market.raw_close is not None:
        panel = cached_panel(market.close, market.volume, horizon, fund, archive,
                             raw_close=market.raw_close)
    else:
        # Existing saved portfolio test adapters may supply only adjusted bars.
        panel = cached_panel(market.close, market.volume, horizon, fund, archive)
    if panel.empty:
        raise ValueError('Insufficient valid feature history for an ML forecast.')
    asof = panel['date'].max()
    predicted = cached_ranking(panel, asof, fast, 0.20, enhanced)
    row = predicted.loc[predicted['ticker'].eq(ticker)]
    if row.empty:
        raise ValueError('The trained model returned no forecast for this stock.')
    score = row.iloc[0]
    signal = plan_signals(predicted, horizon=horizon).loc[lambda df:df['ticker'].eq(ticker)].iloc[0]
    fields = dict(asof=str(pd.Timestamp(asof).date()),forecast_excess=score['forecast_excess'],
                  prob_gain=score.get('prob_gain'), prob_boom=score.get('prob_boom'),
                  vol_20=score.get('vol_20'), model_price=score['close'],
                  review_level=signal.get('review_level'), exit_review=signal.get('exit_review'),
                  entry_watch=signal.get('entry_watch'), selected_model=score.get('selected_model'))
    holdings.save_forecast(code, ticker, horizon, fields)
    return fields


def _display_portfolio(code, trades, cached_quotes):
    last_message = st.session_state.pop('iq_forecast_refresh_message', None)
    if last_message:
        st.success(last_message)
    held = sorted(set(r['ticker'] for r in trades))
    if not held:
        st.info('Enter your first purchase above, including its exact share count and buy price. The portfolio will then calculate returns automatically.')
        return []
    # Quotes are refreshable but NOT a guaranteed consolidated live feed.
    top_l, top_r = st.columns([3,1])
    with top_l:
        st.markdown('### Current positions')
    with top_r:
        if st.button('↻ Refresh prices', key='iq_force_quotes'):
            st.session_state['iq_quotes_nonce'] = st.session_state.get('iq_quotes_nonce',0)+1
            st.rerun()
    auto_quotes = st.checkbox('Automatically refresh displayed prices every 2 minutes while this page is open', value=True)

    @st.fragment(run_every='2m' if auto_quotes else None)
    def position_snapshot():
        opened = holdings.calculate_positions(trades, {})
        symbols = [p['ticker'] for p in opened['holdings']]
        now_utc = datetime.now(timezone.utc)
        try:
            quotes = cached_quotes('Yahoo', tuple(symbols), '', '', st.session_state.get('iq_quotes_nonce',0))
            price_map = dict(zip(quotes['ticker'], quotes['price'])) if quotes is not None and not quotes.empty else {}
            stamps = dict(zip(quotes['ticker'], quotes['timestamp_utc'])) if quotes is not None and not quotes.empty else {}
        except Exception as exc:
            price_map, stamps = {}, {}
            st.warning(f'Current price feed unavailable ({type(exc).__name__}); missing prices will NOT be treated as $0.')
        report = holdings.calculate_positions(trades, price_map, initial_capital=INITIAL_CAPITAL)
        c1,c2,c3,c4 = st.columns(4)
        c1.metric('Estimated portfolio value', _fmt_cash(report['equity']))
        c2.metric('Total P/L since $1M start', _fmt_cash(report['total_pnl']))
        c3.metric('Remaining virtual cash', _fmt_cash(report['cash']))
        c4.metric('Realized P/L on sales', _fmt_cash(report['realized_pnl']))
        if report['missing_quotes']:
            st.warning('Missing live/delayed quotes: '+', '.join(report['missing_quotes'])+'. Portfolio total is unavailable until all positions have usable quotes.')
        if report['cash'] < -0.01:
            st.warning('Recorded purchases exceed available virtual cash. Check your transaction history; cash is negative.')
        forecasts = holdings.get_forecasts(code, 20)
        rows = []
        light_counts = {'DARK_GREEN':0,'GREEN':0,'YELLOW':0,'RED':0}
        for item in report['holdings']:
            sym = item['ticker']
            forecast = forecasts.get(sym)
            stamp = pd.to_datetime(stamps.get(sym), utc=True, errors='coerce')
            freshness = ('unavailable' if pd.isna(stamp) else
                         ('stale' if (now_utc-stamp.to_pydatetime()).total_seconds()>20*60 else
                          f'{stamp.strftime("%b %d %H:%M UTC")}'))
            review = 'Not assessed'
            if forecast:
                review = str(forecast.get('exit_review') or 'MONITOR')
                asof = pd.to_datetime(forecast.get('asof'), errors='coerce')
                stale = pd.isna(asof) or (pd.Timestamp.now().normalize()-asof).days > 4
                threshold = _as_float(forecast.get('review_level'))
                last_price = _as_float(item.get('last_price'))
                # Advisory only: the source's adjusted training prices may
                # differ from unadjusted live quotes after corporate actions.
                if threshold and last_price and last_price <= threshold and not stale:
                    review = 'CHECK PRICE/EXIT CONDITIONS'
                if stale:
                    review += ' (stale forecast)'
            traffic = classify_holding(forecast, quote_available=(item.get('last_price') is not None),
                                       latest_price=item.get('last_price'),
                                       position_weight=item.get('portfolio_weight'))
            light_counts[traffic['color']] += 1
            rows.append({
                'Ticker':sym, 'Signal':traffic['label'], 'Why this color':traffic['reason'], 'Shares':f"{item['shares']:,.3f}",
                'Average paid':_fmt_cash(item['avg_buy_price']),
                'Cost basis':_fmt_cash(item['cost_basis']),
                'Latest quoted price':_fmt_cash(item['last_price']),
                'Market value':_fmt_cash(item['market_value']),
                'Unrealized $':_fmt_cash(item['unrealized_pnl']),
                'Unrealized %':_fmt_pct(item['unrealized_return']),
                'Portfolio weight':f"{item['portfolio_weight']:.2%}" if item['portfolio_weight'] is not None else 'Unavailable',
                'Quote time':freshness, '20-day exit watch':review})
        lightcols = st.columns(4)
        lightcols[0].metric('🟩 Strong entry watch', light_counts['DARK_GREEN'])
        lightcols[1].metric('🟢 Entry watch', light_counts['GREEN'])
        lightcols[2].metric('🟡 Wait / confirm', light_counts['YELLOW'])
        lightcols[3].metric('🔴 Exit review', light_counts['RED'])
        colored_positions = pd.DataFrame(rows)
        st.dataframe(colored_positions.style.map(_signal_cell_style, subset=['Signal']),
                     hide_index=True, use_container_width=True)
        st.caption('**Entry/exit colors:** 🟩 STRONG ENTRY WATCH (dark green) = strictest research screen: ENTRY WATCH, '
                   '>=6% modeled SPY-relative return, >=70% modeled gain probability, <=60% annualized volatility, '
                   'and <=15% existing position weight (when known). 🟢 ENTRY WATCH = standard confirmed entry setup. '
                   '🟡 WATCH / CONFIRM, WAIT, or missing data = more evidence needed. '
                   '🔴 REVIEW EXIT = exit-review condition. Red overrides both greens. '
                   '**These heuristic tiers are not validated trading instructions, and the gain probability is not a guarantee.** '
                   'Update 20-session forecasts to populate entry and exit flags.')
        st.caption('Returns are measured against **your entered fill prices and share counts**, with a weighted-average cost after additional purchases. Prices are best-effort Yahoo intraday observations; they may be delayed, stale or unavailable. Unrealized P/L excludes unrecorded corporate actions, dividends and taxes. The portfolio value assumes you entered the full trade history.')
        if any(item['portfolio_weight'] is not None and item['portfolio_weight'] > 0.25+1e-8 for item in report['holdings']):
            st.warning('At least one position currently represents >25% of portfolio value. Review competition position rules; the official initial-purchase constraint may be different from current drift.')
    position_snapshot()
    return [r['ticker'] for r in holdings.calculate_positions(trades, {})['holdings']]


def _forecast_panel(code, owned, mode, cached_single_symbol, cached_panel, cached_ranking,
                    cached_sec_quarters, sec_contact):
    st.markdown('### Forecasts and sell/review signals')
    st.caption('Each prediction analyzes **only one portfolio company and SPY**, never the whole stock universe. The SELL/REVIEW indicator is a monitoring rule, not a proven optimal trade date or an automatic sell order.')
    selected = st.selectbox('Company to review', owned, key='iq_research_ticker')
    horizon = st.selectbox('Forecast horizon (trading sessions)', [5,20,60], index=1, key='iq_research_horizon')
    enhanced = st.checkbox('Use enhanced research lab instead of three-model tournament (slower)',
                           value=False, key='iq_enhanced_forecast',
                           help='These are alternative model-promotion methods, not simultaneous options. '
                                'Leave unchecked for the stock-specific three-model tournament.')
    left,right,link = st.columns([2,2,2])
    with left:
        one = st.button('🧠 Update selected forecast', key='iq_update_one', type='primary')
    with right:
        all_forecasts = st.button('Update all held stocks', key='iq_update_all')
    with link:
        if st.button('Open detailed stock explorer', key='iq_open_explorer'):
            st.session_state['quick_requested'] = selected
            st.session_state['quick_last_input'] = selected
            st.session_state['workspace_mode'] = '⚡ Instant stock explorer'
            st.rerun()
    if one or all_forecasts:
        wanted = owned if all_forecasts else [selected]
        progress = st.progress(0, text='Forecasting holdings (no marketwide scan)…')
        issues = []
        for i, ticker in enumerate(wanted, 1):
            try:
                _forecast_one(code, ticker, horizon, mode=mode,
                              cached_single_symbol=cached_single_symbol,
                              cached_panel=cached_panel, cached_ranking=cached_ranking,
                              cached_sec_quarters=cached_sec_quarters,
                              sec_contact=sec_contact, enhanced=enhanced)
            except Exception as exc:
                issues.append(f'{ticker}: {type(exc).__name__}: {exc}')
            progress.progress(i / len(wanted), text=f'Processed {i}/{len(wanted)} holdings')
        progress.empty()
        if issues:
            st.warning('Some forecasts could not be updated:\n\n'+'\n\n'.join(issues[:10]))
        else:
            st.session_state['iq_forecast_refresh_message'] = (
                f'Updated {len(wanted)} forecast(s). Entry/exit colors now reflect the saved 20-session signals.')
            st.rerun()
    stored = holdings.get_forecasts(code, horizon)
    table = []
    for ticker in owned:
        r = stored.get(ticker)
        table.append({'Ticker':ticker,
                      'As-of daily session':r['asof'] if r else 'Not calculated',
                      'Relative forecast vs SPY':_fmt_pct(r['forecast_excess']) if r else 'Not calculated',
                      'P(gain)':_fmt_pct(r.get('prob_gain')) if r else 'Not calculated',
                      'P(+20% gain)':_fmt_pct(r.get('prob_boom')) if r else 'Not calculated',
                      'Entry signal':(r.get('entry_watch') or 'Not assessed') if r else 'Not calculated',
                      'Review signal':(r.get('exit_review') or 'MONITOR') if r else 'Not calculated',
                      'Model':(r.get('selected_model') or '') if r else ''})
    st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
    if selected in stored:
        r = stored[selected]
        a,b,c = st.columns(3)
        a.metric('Forecast vs SPY',_fmt_pct(r['forecast_excess']))
        b.metric('Illustrative price endpoint',_fmt_cash(r['model_price']*(1+r['forecast_excess'])) if r['model_price'] else 'Unavailable')
        c.metric('Review status', r.get('exit_review') or 'MONITOR')
        st.caption(f"As of {r['asof']} · {horizon} trading sessions · base daily model price {_fmt_cash(r['model_price'])}. The price endpoint assumes SPY has 0% future return; it is NOT a live absolute-price prediction or guaranteed sell target. Review-level triggers can be bypassed by price gaps. Check earnings, news and position concentration before selling.")
        cutoff = pd.to_datetime(r['asof'], errors='coerce')
        if pd.notna(cutoff):
            estimated_review = (cutoff + pd.offsets.BDay(horizon)).strftime('%b %d, %Y')
            st.caption(f'Planned **review date** (not a sell date): approximately {estimated_review}. Actual market holidays may shift this date.')
        if pd.isna(cutoff) or (pd.Timestamp.now().normalize()-cutoff).days>4:
            st.warning('Forecast is older than four calendar days. Update it before making a portfolio decision.')
    else:
        st.info('No forecast saved for this ticker and horizon. Click Update selected forecast to train it from its own price history.')




def _analyst_portfolio_panel(code, trades, owned, cached_quotes, cached_single_symbol):
    """Manual-refresh analyst research; never forces orders or backfills history."""
    st.markdown('### Portfolio intelligence — Wall Street analyst consensus + risk')
    st.caption('Current BUY/HOLD/SELL counts and broker price targets are **external opinions**, '
               'not proven model returns. Target horizons differ from Ithaca’s 20-session forecast. '
               'These observations are captured NOW and are never backfilled into historical model training.')
    provider = st.selectbox('Analyst data provider',
                            ('Yahoo Finance (best effort)', 'Finnhub (API key required)'),
                            key='iq_analyst_provider')
    reserve_pct = st.slider('Hypothetical cash reserve (%)', 0, 40, 10, 5, key='iq_analyst_cash')
    cap_pct = st.slider('Hypothetical maximum weight per stock (%)', 10, 25, 20, 5,
                         key='iq_analyst_cap', help='Only affects the research allocation, not recorded holdings.')
    st.caption('Press Refresh to request analyst data and available daily prices for held tickers only. '
               'No transaction or brokerage order is placed. Estimates may be delayed or absent.')
    key = 'iq_analyst_research_'+hashlib.sha256(code.encode()).hexdigest()[:16]
    if st.button('Refresh analyst opinions and risk research', key='iq_refresh_analyst',
                 type='primary'):
        token = str(_secrets_value('FINNHUB_API_KEY') or os.environ.get('FINNHUB_API_KEY',''))
        if provider.startswith('Finnhub') and not token:
            st.warning('Set FINNHUB_API_KEY in Streamlit Secrets or the server environment. '
                       'Do not paste private keys into portfolio tables.')
        else:
            progress = st.progress(0, text='Loading published analyst opinions…')
            snapshots, histories, problems, actions = {}, {}, [], []
            for index,ticker in enumerate(owned):
                try:
                    snapshots[ticker] = (fetch_finnhub(ticker, token) if provider.startswith('Finnhub')
                                         else fetch_yahoo(ticker))
                except Exception as exc:
                    problems.append(f'{ticker}: analyst opinions unavailable ({type(exc).__name__})')
                try:
                    actions.extend(fetch_finnhub_actions(ticker, token) if provider.startswith('Finnhub')
                                   else fetch_yahoo_actions(ticker))
                except Exception as exc:
                    problems.append(f'{ticker}: attributed rating changes unavailable ({type(exc).__name__})')
                try:
                    market = cached_single_symbol(ticker, 'Yahoo Finance', 2)
                    if ticker in market.close and not market.close[ticker].dropna().empty:
                        histories[ticker] = market.close[ticker]
                    else:
                        problems.append(f'{ticker}: daily history unavailable')
                except Exception as exc:
                    problems.append(f'{ticker}: daily price history unavailable ({type(exc).__name__})')
                progress.progress((index+1)/len(owned))
            progress.empty()
            st.session_state[key] = {'provider':provider, 'tickers':tuple(owned),
                                     'snapshots':snapshots, 'histories':histories, 'actions':actions, 'errors':problems,
                                     'retrieved_at':datetime.now(timezone.utc).isoformat()}
    data = st.session_state.get(key)
    if data is None:
        st.info('No analyst snapshot has been retrieved in this session. Refresh to compare your holdings.')
        return
    if data['tickers'] != tuple(owned) or data['provider'] != provider:
        st.warning('The stored opinions refer to different holdings/provider. Refresh before using them.')
        return
    snapshots, histories = data['snapshots'], data['histories']
    if data['errors']:
        st.warning('Data gaps (nothing has been invented or treated as a neutral opinion): '
                   + '; '.join(data['errors'][:20]))
    st.caption('Last requested: '+data['retrieved_at']+' UTC. '
               'Ratings periods reported by providers are not verified publication timestamps.')
    if not snapshots:
        st.warning('No analyst coverage could be retrieved. Risk research can still use price history '
                   'but analyst opinions will not influence the weights.')
    try:
        quotes = cached_quotes('Yahoo', tuple(owned), '', '', st.session_state.get('iq_quotes_nonce',0))
        quotes_map = dict(zip(quotes['ticker'], quotes['price'])) if quotes is not None and not quotes.empty else {}
    except Exception:
        quotes_map = {}
    if snapshots:
        table = pd.DataFrame([snapshot_to_row(x, quotes_map.get(s)) for s,x in sorted(snapshots.items())])
        st.dataframe(table, use_container_width=True, hide_index=True,
                     column_config={'Mean price target':st.column_config.NumberColumn(format='$%.2f'),
                                    'Target vs latest quote':st.column_config.NumberColumn(format='%.1%'),
                                    'Consensus score (shrunk)':st.column_config.NumberColumn(format='%.3f')})
        st.download_button('Export attributed analyst snapshot (CSV)',
                           table.to_csv(index=False).encode('utf-8'),
                           file_name='ithaca_analyst_observations.csv', mime='text/csv',
                           key='iq_analyst_export')
        if any(not is_fresh(x) for x in snapshots.values()):
            st.warning('Some analyst snapshots were retrieved over seven days ago. Refresh before interpreting them.')
        st.caption('The consensus score ranges from -1 (bearish) to +1 (bullish), then shrinks with '
                   'limited coverage; it is NOT a calibrated probability or a validated return forecast. '
                   'Price target comparisons are illustrative and have horizons set by external providers.')
    if data.get('actions'):
        with st.expander('Recent attributed analyst upgrades and downgrades'):
            st.dataframe(pd.DataFrame(data['actions']).sort_values('Date', ascending=False),
                         hide_index=True, use_container_width=True)
            st.caption('These are public provider-supplied analyst/firm actions, not verified '
                       'recommendation performance or guaranteed future outcomes.')
    opened = holdings.calculate_positions(trades, quotes_map, initial_capital=INITIAL_CAPITAL)
    if opened['missing_quotes'] or opened['equity'] is None or opened['equity'] <= 0:
        st.warning('Cannot build an allocation study: one or more held stocks lack valid prices. '
                   'No missing value will be silently converted to zero.')
        return
    if set(owned) != set(histories):
        st.warning('Cannot build an allocation study without verified daily history for every holding.')
        return
    weights = {row['ticker']:float(row['portfolio_weight']) for row in opened['holdings']}
    if any(w < 0 for w in weights.values()) or opened['cash'] < -0.01:
        st.warning('The current ledger implies borrowing or invalid weights; leveraged allocation is unsupported.')
        return
    hist_prices = pd.concat(histories, axis=1).sort_index()
    # Missing session bars must not be forward-filled through suspensions/delistings.
    try:
        report = portfolio_allocation_study(hist_prices, weights,
                           forecasts=holdings.get_forecasts(code, 20),
                           analyst_snapshots=snapshots, cash_reserve=reserve_pct/100,
                           max_position=cap_pct/100)
    except (ValueError, TypeError) as exc:
        st.warning('No reliable allocation study: '+str(exc))
        return
    left, right, third = st.columns(3)
    left.metric('Current historical annualized volatility', f'{report.annualized_vol_current:.1%}')
    right.metric('Research weights historical volatility', f'{report.annualized_vol_research:.1%}')
    third.metric('Indicative one-way turnover', f'{report.predicted_turnover_fraction:.1%}')
    allocation_rows=[]
    for sym in sorted(report.targets):
        allocation_rows.append({'Ticker':sym, 'Current weight':report.current[sym],
                                'Illustrative research weight':report.targets[sym],
                                'Difference':report.targets[sym]-report.current[sym],
                                'Current 20-session model signal':report.forecast_signal[sym],
                                'Current analyst tilt':report.analyst_signal[sym]})
    plan = pd.DataFrame(allocation_rows)
    st.dataframe(plan, use_container_width=True, hide_index=True,
                 column_config={key:st.column_config.NumberColumn(format='%.1%') for key in
                                ('Current weight','Illustrative research weight','Difference')})
    st.download_button('Export hypothetical allocation study (CSV)',
                       plan.to_csv(index=False).encode('utf-8'),
                       file_name='ithaca_risk_allocation_research.csv', mime='text/csv',
                       key='iq_analyst_allocation_export')
    st.caption(f'Risk estimate from {report.sessions} complete historical sessions · '
               f'{report.exposure:.0%} theoretical stock exposure · '
               f'cap {report.max_weight:.0%} per stock. The optimizer shrinks correlations, '
               'limits concentration and turnover, and gives only small preference tilts to '
               'recent unvalidated model forecasts and observed analyst opinions.')
    st.caption('Important: historical volatility estimates are not future loss guarantees; '
               'the weights are NOT recommended orders. Spread, market impact, taxes, '
               'sector concentration and competition constraints beyond per-stock caps are not fully modeled.')
    if report.warnings:
        with st.expander('Research caveats and missing evidence'):
            for message in report.warnings:
                st.write('- '+message)


def _news_panel(owned, cached_news):
    st.markdown('### Latest news for every holding')
    st.caption('Headlines are attributed and timestamped. News sentiment is a research note, **not** an independently validated buy/sell signal. Some publishers may have no matching articles.')
    refresh = st.button('↻ Refresh all company headlines', key='iq_news_refresh')
    if refresh:
        # Force all ticker-level RSS retrieval without altering stock prediction caches.
        cached_news.clear()
    report = []
    errors = []
    for ticker in owned:
        try:
            headlines, failures = cached_news(ticker, ticker)
            analysis = analyze_news(headlines, ticker)
            for item in analysis.get('headlines', [])[:5]:
                report.append({'Ticker':ticker,
                               'Published (UTC)':item['published_utc'],
                               'Publisher':item['publisher'],
                               'Headline':item['title'],
                               'Tone (words)':item['impact'],
                               'Article':item['url']})
            if failures:
                errors.extend(f'{ticker}: {msg}' for msg in failures[:2])
        except Exception as exc:
            errors.append(f'{ticker}: {type(exc).__name__}')
    if report:
        frame = pd.DataFrame(report).sort_values('Published (UTC)', ascending=False).head(35)
        st.dataframe(frame, hide_index=True, use_container_width=True,
                     column_config={'Article':st.column_config.LinkColumn('Read article', display_text='Open'),
                                    'Published (UTC)':st.column_config.DatetimeColumn(format='MMM DD, YYYY HH:mm')})
        st.caption(f'Displaying {len(frame)} of the newest eligible ticker-associated headlines. Full article content may not be available, and sources are not necessarily exhaustive.')
    else:
        st.info('No eligible recent articles were retrieved; that does NOT mean no news exists.')
    if errors:
        st.caption('News provider limitations: '+'; '.join(errors[:10]))


def render_portfolio(*, mode, cached_quotes, cached_single_symbol, cached_panel,
                     cached_ranking, cached_quick_news, cached_sec_quarters, sec_contact):
    code = _access_panel()
    if code is None:
        return
    try:
        trades = holdings.get_trades(code)
    except Exception as exc:
        st.error(f'Portfolio database unavailable ({type(exc).__name__}). Check ITHACA_DATABASE_URL or try again later.')
        return
    _picture_import_panel(code)
    _trade_form(code, trades)
    owned = _display_portfolio(code, trades, cached_quotes)
    if owned:
        _forecast_panel(code, owned, mode, cached_single_symbol, cached_panel,
                        cached_ranking, cached_sec_quarters, sec_contact)
        _analyst_portfolio_panel(code, trades, owned, cached_quotes, cached_single_symbol)
        auto_news = st.checkbox('Check held-company headlines every 15 minutes while this page is open', value=True)
        @st.fragment(run_every='15m' if auto_news else None)
        def news_refresh_panel():
            _news_panel(owned, cached_quick_news)
        news_refresh_panel()
    _ledger_panel(code, trades)
    st.caption('Virtual competition research only. Holdings are entered manually; Ithaca Quant cannot view or place trades in your StockTrak account. Closing a browser tab pauses refreshes; stored records remain in your configured database.')
