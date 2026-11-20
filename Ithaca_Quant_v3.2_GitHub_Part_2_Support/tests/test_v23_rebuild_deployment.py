from pathlib import Path
import ast
import importlib.util
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_exactly_one_repo_root_package_and_app():
    assert (ROOT / 'ithaca_quant' / '__init__.py').is_file()
    assert (ROOT / 'app.py').is_file()
    assert (ROOT / 'streamlit_app.py').is_file()
    assert not (ROOT / 'ithaca_quant' / 'ithaca_quant').exists()


def test_version_matches():
    import ithaca_quant
    assert ithaca_quant.__version__ == '3.2.0'
    assert 'APP_RELEASE = "3.2.0"' in (ROOT / 'app.py').read_text()


def test_launch_file_has_diagnostic_guard():
    src = (ROOT / 'streamlit_app.py').read_text()
    ast.parse(src)
    assert 'runpy.run_path' in src
    assert 'present_startup_error' in src
    assert 'raise FileNotFoundError' in src
    assert 'streamlit_app.py as the main file' in src


def test_preflight_passes():
    result = subprocess.run([sys.executable, str(ROOT/'scripts'/'preflight.py')],
                            capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
