"""Regression tests for the v3.2.1 default-on conflicting promotion bug."""
from __future__ import annotations
import ast
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from ithaca_quant.model import forecast_asof

ROOT = Path(__file__).resolve().parents[1]


def _extract_wrapper():
    # Importing the Streamlit dashboard executes its UI. Compile only this
    # function body, so the test verifies the deployed wrapper directly.
    tree = ast.parse((ROOT / 'app.py').read_text())
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == 'cached_ranking')
    func.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[]))
    calls = []
    def spy_forecast(panel, asof, **kwargs):
        calls.append(kwargs)
        return kwargs
    ns = {'pd': pd, 'forecast_asof': spy_forecast}
    exec(compile(module, str(ROOT / 'app.py'), 'exec'), ns)
    return ns['cached_ranking'], calls


def test_default_path_runs_tournament_without_lab_promotion():
    ranking, calls = _extract_wrapper()
    out = ranking(None, pd.Timestamp('2026-11-19'), True, .20)
    assert out['enhanced'] is False
    assert out['competitive_agents'] is True
    assert len(calls) == 1


def test_enhanced_path_runs_lab_without_tournament_promotion():
    ranking, calls = _extract_wrapper()
    out = ranking(None, pd.Timestamp('2026-11-19'), True, .20, enhanced=True)
    assert out['enhanced'] is True
    assert out['competitive_agents'] is False
    assert len(calls) == 1


def test_underlying_forecaster_still_rejects_conflicting_modes():
    with pytest.raises(ValueError, match='Choose either enhanced'):
        forecast_asof(pd.DataFrame(), pd.Timestamp('2026-11-19'),
                      enhanced=True, competitive_agents=True)


def test_sidebar_default_is_tournament_and_explains_alternatives():
    source = (ROOT / 'app.py').read_text()
    assert 'Use enhanced research lab INSTEAD of three-model tournament' in source
    assert 'enhanced_model = st.checkbox' in source
    assert 'value=False' in source.split('enhanced_model = st.checkbox',1)[1].split('st.caption',1)[0]
    assert 'competitive_agents=not enhanced' in source


def test_portfolio_control_marks_lab_as_alternative():
    source = (ROOT / 'ithaca_quant' / 'portfolio_workspace.py').read_text()
    assert 'Use enhanced research lab instead of three-model tournament' in source
    assert "value=False, key='iq_enhanced_forecast'" in source
