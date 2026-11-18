# Deploy Ithaca Quant v2.5

Your existing Streamlit deployment is working; keep it running until the new release is verified.

1. Unzip the complete v2.5 ZIP.
2. In GitHub, **replace the contents of the folder that currently contains `streamlit_app.py`**. Upload all the files together, including `app.py`, `requirements.txt`, and the inner `ithaca_quant/` package. Do not create a further nested folder.
3. Keep the same main-file path as your current working deployment. E.g., if it is `Ithaca_Quant_v2.3_Rebuilt_Streamlit_Deployment/streamlit_app.py`, keep that path. If deploying at repository root, the path is simply `streamlit_app.py`.
4. Commit the changes and let Streamlit redeploy. The app should display v2.5.0.
5. Set up Streamlit Secrets for Google OIDC sign-in, PostgreSQL durable storage, and optional OpenAI screenshot extraction. Read `SETUP_SIGN_IN_AND_PHOTOS.md`.

**You can use the existing recovery-code portfolio without new secrets; account sign-in requires configuration.** Please keep a CSV backup of previous transactions.

Test first: `python scripts/preflight.py` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_v25_accounts_images_lights.py`.

We cannot guarantee live login, external APIs, or cloud storage until the secrets and provider are configured and verified on Streamlit Cloud.
