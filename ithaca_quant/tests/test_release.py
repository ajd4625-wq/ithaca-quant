"""Tests for released version consistency."""
from pathlib import Path
from ithaca_quant import __version__


def test_release_version():
    assert __version__ == "1.4.2"


def test_readme_and_changelog_name_version():
    root = Path(__file__).resolve().parents[1]
    assert "Ithaca Quant v1.4" in (root / "README.md").read_text()
    assert "v1.4.2" in (root / "CHANGELOG.md").read_text()


def test_deployment_release_displays_build_and_reports_package_mismatches():
    root = Path(__file__).resolve().parents[1]
    text = (root / "app.py").read_text()
    assert f'APP_RELEASE = "{__version__}"' in text
    assert 'st.title(f"📈 Ithaca Quant v{APP_RELEASE}")' in text
    assert 'if __version__ != APP_RELEASE:' in text
    assert text.index('if __version__ != APP_RELEASE:') < text.index('from ithaca_quant.explorer import (')
    assert "Deployment version mismatch" in text
