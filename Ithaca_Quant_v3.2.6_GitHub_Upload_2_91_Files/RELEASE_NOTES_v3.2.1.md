# Ithaca Quant v3.2.1 — Model-mode conflict hotfix

## Why v3.2 stock forecasting failed

The dashboard's cached ranking wrapper always requested `competitive_agents=True`, while the sidebar enabled `enhanced=True` by default. The underlying forecasting routine correctly rejects simultaneous promotions by the research lab and the three-model tournament; as a result, the individual-stock view displayed a ValueError and no daily forecast. This is a code-configuration error, not proof of invalid stock-price data.

## Changes

- The default is now the **three-model stock-specific tournament**. The alternative enhanced research lab is OFF by default.
- Enabling the research lab **switches** the primary forecast method instead of requesting both promotion engines at once.
- The sidebar and portfolio screen explicitly label the research lab as an alternative rather than an additive setting.
- The model's underlying fail-fast assertion remains unchanged: API callers cannot accidentally request conflicting promotions.
- Streamlit app and package version identifiers now match v3.2.1. `streamlit_app.py` displays the correct release.
- No changes to market-data provenance, model win criteria, portfolio holdings, or real-market performance claims.

## Deployment

Extract **both** GitHub Part 1 and Part 2 archives into the same repository root, preserving folders and hidden `.github/` contents. Commit replacements of existing files. Deploy using `streamlit_app.py`, and refresh the app. Saved predictions are not edited by this fix. Avoid mixing v3.2.1 `app.py` with an older `ithaca_quant` package.

## Verification

`python scripts/preflight.py` and `python -m pytest -q tests/test_v321_forecasting_mode.py` check root consistency and the exclusive routing. These do not establish live forecasting accuracy or vendor reliability. Run full regression suite where practical.
