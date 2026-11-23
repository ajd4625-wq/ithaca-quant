"""Offline deployment check without running the Streamlit browser.

Usage: python scripts/preflight.py
Checks the version labels, folder layout, syntax, and package-level imports.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def const_value(tree, name):
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                if isinstance(node.value, ast.Constant):
                    return node.value.value
    return None


def check():
    issues = []
    required = ['app.py', 'streamlit_app.py', 'requirements.txt',
                'ithaca_quant/__init__.py', 'ithaca_quant/explorer.py',
                'ithaca_quant/portfolio_workspace.py', 'ithaca_quant/holdings.py',
                'ithaca_quant/portfolio_image.py', 'ithaca_quant/portfolio_lights.py',
                'ithaca_quant/account_auth.py',
                'ithaca_quant/news_dedupe.py', 'ithaca_quant/universe_news.py',
                'ithaca_quant/insider_form4.py',
                'ithaca_quant/analyst_consensus.py', 'ithaca_quant/portfolio_advisor.py',
                'ithaca_quant/historical_vendor.py', 'ithaca_quant/historical_vendor_package.py',
                'scripts/acquire_historical_data.py']
    for rel in required:
        if not (ROOT / rel).is_file():
            issues.append('Missing: ' + rel)
    for py in ROOT.rglob('*.py'):
        if any(x in py.parts for x in ('.venv','.git','__pycache__')): continue
        try: ast.parse(py.read_text(encoding='utf-8'), filename=str(py))
        except SyntaxError as exc: issues.append(f'Invalid Python: {py.relative_to(ROOT)}:{exc.lineno}')
    if (ROOT / 'app.py').exists() and (ROOT / 'ithaca_quant/__init__.py').exists():
        dashboard = ast.parse((ROOT / 'app.py').read_text())
        version = ast.parse((ROOT / 'ithaca_quant/__init__.py').read_text())
        if const_value(dashboard, 'APP_RELEASE') != const_value(version, '__version__'):
            issues.append('APP_RELEASE does not match ithaca_quant.__version__')
    if issues:
        for issue in issues: print('ERROR:', issue)
        return 1
    print('PASS: Complete root layout, matching release labels and Python syntax.')
    print('NOTE: This does not verify cloud deployment, installed packages, or live data APIs.')
    return 0


if __name__ == '__main__':
    sys.exit(check())
