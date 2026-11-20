"""Optional vision-powered screenshot-to-trades draft, never automatic trading.

A screenshot's latest price must not be mistaken for the user's buy price.
Uploads are processed only on explicit user action, sent to an API provider,
and not persisted by this module. Users must review and confirm all rows.
"""
from __future__ import annotations

import base64
from datetime import date
import json
import math
import re
from io import BytesIO
from typing import Any

from .holdings import validate_trade

_MAX_BYTES = 8 * 1024 * 1024
_ALLOWED = {'image/png', 'image/jpeg', 'image/webp'}


SYSTEM_INSTRUCTION = ("You are extracting manually-entered VIRTUAL STOCK PORTFOLIO transactions "
    "from a brokerage or competition screenshot. Return STRICT JSON with one object: "
    "{\"positions\":[{\"ticker\":\"RKLB\",\"shares\":123,\"purchase_price\":45.67,"
    "\"trade_date\":\"2026-11-16\",\"fees\":0,\"confidence\":\"high\"}], "
    "\"notes\":[\"...\"]}. Each row is a currently HELD position as a draft BUY. "
    "Only include individual stock tickers shown in the screenshot; do not invent assets. "
    "shares must be the number of SHARES, NOT position dollars. purchase_price must be "
    "the ORIGINAL fill/average cost per share, never current/last/market price. "
    "If original fill price is absent or uncertain, use null. "
    "If purchase date is absent use null, NEVER today's date. "
    "If shares are absent or uncertain use null. fees should be 0 unless directly stated. "
    "Do not infer an investment recommendation or future price. Add short notes for missing/ambiguous fields. "
    "Only output JSON, with no markdown.")


def extract_picture_positions(image_data: bytes, mime: str, api_key: str,
                              model: str = 'gpt-4.1-mini') -> dict:
    if mime not in _ALLOWED:
        raise ValueError('Upload a PNG, JPG or WebP picture.')
    if not image_data or len(image_data) > _MAX_BYTES:
        raise ValueError('Screenshot must be nonempty and at most 8 MB.')
    if not api_key or not str(api_key).strip():
        raise ValueError('OPENAI_API_KEY is required to read screenshot images.')
    from openai import OpenAI  # Imported only when the user requests screenshot analysis.
    encoded = base64.b64encode(image_data).decode('ascii')
    client = OpenAI(api_key=str(api_key).strip(), timeout=35.0, max_retries=1)
    response = client.responses.create(
        model=model,
        store=False,
        input=[{'role': 'user', 'content': [
            {'type':'input_text', 'text': SYSTEM_INSTRUCTION},
            {'type':'input_image', 'image_url':f'data:{mime};base64,{encoded}', 'detail':'high'},
        ]}],
        text={'format':{'type':'json_object'}},
    )
    try:
        payload = json.loads(response.output_text)
    except (ValueError, TypeError) as exc:
        raise ValueError('Image service did not return valid portfolio JSON.') from exc
    return clean_draft(payload)


def clean_draft(payload: dict[str, Any]) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get('positions'), list):
        raise ValueError('The image response did not include a positions list.')
    if len(payload['positions']) > 100:
        raise ValueError('Only 100 stock positions can be imported at once.')
    result = []
    for row in payload['positions']:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get('ticker') or '').upper().strip()
        if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', ticker) or ticker == 'SPY':
            continue
        def number(value):
            try:
                if value is None or isinstance(value, bool):
                    return None
                x = float(str(value).replace(',','').replace('$','').strip())
                return x if math.isfinite(x) and x > 0 else None
            except (ValueError, TypeError):
                return None
        qty = number(row.get('shares'))
        paid = number(row.get('purchase_price'))
        fees = number(row.get('fees')) or 0.0
        raw_date = str(row.get('trade_date') or '').strip()
        try:
            day = date.fromisoformat(raw_date).isoformat() if raw_date else ''
        except ValueError:
            day = ''
        confidence = str(row.get('confidence') or 'uncertain').lower()
        if confidence not in {'high','medium','low'}:
            confidence='uncertain'
        result.append(dict(ticker=ticker,side='BUY',shares=qty,price=paid,
                           trade_date=day,fees=fees,confidence=confidence))
    notes = payload.get('notes') or []
    if not isinstance(notes, list):
        notes=[]
    return {'positions':result, 'notes':[str(x)[:250] for x in notes[:10]]}


def confirm_rows(rows: list[dict]) -> list[dict]:
    """Require a complete user-confirmed trade record for every draft row."""
    if not rows:
        raise ValueError('No stock positions were detected.')
    if len(rows) > 100:
        raise ValueError('A maximum of 100 rows is allowed.')
    checked = []
    for idx, row in enumerate(rows, 1):
        try:
            if row.get('shares') is None or row.get('price') is None or not row.get('trade_date'):
                raise ValueError('shares, original purchase price and purchase date are required')
            checked.append(validate_trade(row['ticker'], 'BUY', row['shares'], row['price'],
                                          row['trade_date'], row.get('fees',0)))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f'Row {idx}: {exc}') from exc
    return checked


# Local OCR is deliberately conservative: it never infers an original buy price
# from a current quote, total position value, or a potentially ambiguous column.
_NON_TICKER_WORDS = frozenset({
    "STOCK", "STOCKS", "TOTAL", "SHARES", "SHARE", "SYMBOL", "TICKER", "PRICE",
    "COST", "VALUE", "PORTFOLIO", "HOLDINGS", "ACCOUNT", "MARKET", "CURRENT",
    "TODAY", "TRADE", "TRADES", "BUY", "SELL", "LOSS", "GAIN", "CASH", "OPEN",
    "DATE", "TIME", "CHANGE", "QUANTITY", "QTY", "PERCENT", "PENDING", "ORDER",
    "LONG", "SHORT", "UNIT", "AVG", "AVERAGE", "ASSET", "INVESTED", "EQUITY",
})


def parse_ocr_holdings_text(raw_text: str) -> dict:
    """Return an editable draft, or an empty draft when OCR has no clear tickers.

    No numeric field is filled without an unambiguous header. A row in a holdings
    view is NOT evidence of a new purchase; the user must confirm each trade.
    """
    if not isinstance(raw_text, str):
        raise ValueError('OCR result must be text.')
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    has_shares_header = any(re.search(r'\b(?:shares|quantity|qty)\b', l, re.I) for l in lines[:12])
    found = {}
    for line in lines[:150]:
        # Avoid treating all-caps labels or company names as positions.
        match = re.match(r'^\s*\$?([A-Z]{1,5}(?:[.-][A-Z])?)\b(?:\s+|[|,])', line)
        if not match:
            continue
        ticker = match.group(1)
        if ticker in _NON_TICKER_WORDS or ticker in {'SPY', 'USD'}:
            continue
        # Require an adjacent number to rule out title words and menu items.
        trailing = line[match.end():].strip()
        amount_match = re.match(r'^\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\b', trailing)
        if not amount_match:
            continue
        # Only the *share count*, not the original price, can be extracted
        # from the first numeric column with a clear quantity/shares header.
        shares = None
        if has_shares_header:
            try:
                shares = float(amount_match.group(1).replace(',', ''))
                if not (0 < shares < 1e9 and math.isfinite(shares)):
                    shares = None
            except ValueError:
                pass
        found.setdefault(ticker, {
            'ticker': ticker, 'side': 'BUY', 'shares': shares, 'price': None,
            'trade_date': '', 'fees': 0.0, 'confidence': 'low'
        })
    notes = [
        'Local OCR recognized possible tickers. Verify every row: the image may show current holdings, not original purchases.',
        'Original purchase price and purchase date were intentionally left blank; enter actual fills before saving.',
    ]
    if not has_shares_header:
        notes.append('Share counts were left blank because a clear Shares/Quantity header was not detected.')
    if not found:
        notes.append('No confident ticker rows identified; add rows manually in the review table or use AI extraction.')
    return {'positions': list(found.values()), 'notes': notes}


def extract_picture_positions_local(image_data: bytes, mime: str) -> dict:
    """Try Tesseract OCR locally without an API key, storing no screenshot bytes.

    Requires the optional system tesseract executable and Python pytesseract,
    installed by packages.txt and requirements.txt on Community Cloud.
    """
    if mime not in _ALLOWED:
        raise ValueError('Upload a PNG, JPG or WebP image.')
    if not image_data or len(image_data) > _MAX_BYTES:
        raise ValueError('Screenshot must be nonempty and at most 8 MB.')
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
        import pytesseract
        with Image.open(BytesIO(image_data)) as image:
            if image.width * image.height > 24_000_000:
                raise ValueError('Screenshot resolution is too large (maximum 24 megapixels).')
            image = ImageOps.exif_transpose(image).convert('RGB')
            recognized = pytesseract.image_to_string(image, config='--psm 6', timeout=15)
    except (ImportError, FileNotFoundError) as exc:
        raise RuntimeError('Local OCR is not installed. Add packages.txt (tesseract-ocr) and pytesseract, or set OPENAI_API_KEY.') from exc
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError('Tesseract is missing on the server. Deploy packages.txt with tesseract-ocr.') from exc
    except pytesseract.TesseractError as exc:
        raise RuntimeError('Local OCR could not read this screenshot. Try a clearer image or use AI reading.') from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError('This file could not be decoded as an image.') from exc
    return parse_ocr_holdings_text(recognized)
