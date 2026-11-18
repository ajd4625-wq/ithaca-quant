"""Single canonical Streamlit Community Cloud entrypoint for Ithaca Quant v2.5.1

Deploy from the GitHub repository root with main file ``streamlit_app.py``.
The complete original application remains in ``app.py``.  This wrapper
catches ordinary startup exceptions so a missing file/dependency is visible
inside the app, instead of silently displaying only a generic error page.
"""
from __future__ import annotations

from pathlib import Path
import logging
import runpy
import sys
import traceback

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def launch():
    dashboard = ROOT / "app.py"
    if not dashboard.is_file():
        raise FileNotFoundError("The repository-root app.py file is missing.")
    package = ROOT / "ithaca_quant" / "__init__.py"
    if not package.is_file():
        raise FileNotFoundError("The repository-root ithaca_quant/__init__.py file is missing.")
    runpy.run_path(str(dashboard), run_name="__main__")


def present_startup_error(exc: Exception) -> None:
    # Never show the raw exception message: SQL URLs, provider credentials,
    # and other private configuration can sometimes appear in exceptions.
    import streamlit as st
    st.error("Ithaca Quant could not finish starting. This is a deployment or Python error, not a stock forecast.")
    st.write("**Error type:** `" + type(exc).__name__ + "`")
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        trace_lines = [f"{Path(frame.filename).name}:{frame.lineno}  ({frame.name})"
                       for frame in frames[-8:]]
        st.code("\n".join(trace_lines), language="text")
    st.info("Check Streamlit > Manage app > Logs for the complete traceback. "
            "Deploy the entire rebuilt ZIP to your GitHub repository ROOT, and use "
            "streamlit_app.py as the main file. Do not upload into ithaca_quant_old16.")
    st.caption("Package: Ithaca Quant v2.5.1. This page hides raw exception values to protect secrets.")


if __name__ == "__main__":
    try:
        launch()
    except Exception as error:
        logging.error("Ithaca Quant startup failed: %s", type(error).__name__)
        present_startup_error(error)
