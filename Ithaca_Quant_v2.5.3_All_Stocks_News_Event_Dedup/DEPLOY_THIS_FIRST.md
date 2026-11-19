# Deploy Ithaca Quant v2.5.3

Your existing Streamlit deployment is working; keep it running until the new release is verified.

1. Unzip the complete v2.5.3 ZIP.
2. In GitHub, **replace the contents of the folder that currently contains `streamlit_app.py`**. Upload all the files together, including `app.py`, `requirements.txt`, and the inner `ithaca_quant/` package. Do not create a further nested folder.
3. Keep the same main-file path as your current working deployment. E.g., if it is `Ithaca_Quant_v2.3_Rebuilt_Streamlit_Deployment/streamlit_app.py`, keep that path. If deploying at repository root, the path is simply `streamlit_app.py`.
4. Commit the changes and let Streamlit redeploy. The app should display v2.5.3.
5. Set up Streamlit Secrets for Google OIDC sign-in, PostgreSQL durable storage, and optional OpenAI screenshot extraction. Read `SETUP_SIGN_IN_AND_PHOTOS.md`.

**You can use the existing recovery-code portfolio without new secrets; account sign-in requires configuration.** Please keep a CSV backup of previous transactions.

Test first: `python scripts/preflight.py` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_v25_accounts_images_lights.py`.

We cannot guarantee live login, external APIs, or cloud storage until the secrets and provider are configured and verified on Streamlit Cloud.

## v2.5.3 screenshot OCR without credentials

Upload the new `packages.txt` beside `streamlit_app.py` with all other files. Streamlit Cloud must install its `tesseract-ocr` system package alongside `pytesseract` from `requirements.txt`. This permits the `📷 Read screenshot locally — no API key` action. Crop private information before uploading. AI Vision is optional and requires your own `OPENAI_API_KEY` secret. The extraction returns a reviewable draft: verify share counts and enter actual fill prices and dates before saving.

## v2.5.3 whole-leaderboard automatic news

The first 12 model-ranked stocks receive automatic 45-day headline checks with a 15-minute cache. An unchecked headline feed does not qualify a stock for green or dark green. Entry and exit conditions are separate columns. Public news feeds are not an exhaustive corporate-action database.

## v2.5.3: all-stock news coverage and event deduplication
- **No extra deployment path**: keep your currently working `streamlit_app.py` entrypoint.
- Upload the entire matching release together, including `ithaca_quant/news_dedupe.py` and `ithaca_quant/universe_news.py`.
- The full leaderboard processes up to 24 names per 60-second active dashboard interval (not thousands at once). A large universe takes multiple intervals to complete; provider errors are visible and retried later.
- Reports about the same deal count once, even when several outlets publish related headlines. Matching is heuristic; review links for ambiguous stories.
- Streamlit cloud ephemeral storage: review progress may reset on server restart.
