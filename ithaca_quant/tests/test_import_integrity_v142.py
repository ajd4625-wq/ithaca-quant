"""Catch broken partial uploads at development/test time instead of Streamlit startup."""
import ast
import importlib
from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_every_internal_app_import_exists_in_corresponding_module():
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    checks = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("ithaca_quant."):
            checks.append((node.module, [alias.name for alias in node.names]))
    assert checks
    for module_name, symbols in checks:
        module = importlib.import_module(module_name)
        missing = [name for name in symbols if not hasattr(module, name)]
        assert not missing, f"{module_name} missing {missing}; mixed-version deployment?"


def test_expected_chart_functions_present_and_preflight_is_before_import():
    source = APP_PATH.read_text(encoding="utf-8")
    explorer = importlib.import_module("ithaca_quant.explorer")
    assert callable(explorer.select_1d_display_window)
    assert callable(explorer.chart_axis_range)
    assert source.index('if __version__ != APP_RELEASE:') < source.index('from ithaca_quant.explorer import (')
    assert 'except ImportError as exc:' in source
    assert 'The dashboard could not load its chart or financial-display components.' in source


def test_display_and_package_have_same_release():
    from ithaca_quant import __version__
    assert __version__ == "1.4.2"
    assert f'APP_RELEASE = "{__version__}"' in APP_PATH.read_text(encoding="utf-8")
