"""Tests for released version consistency."""
from pathlib import Path
from ithaca_quant import __version__


def test_release_version():
    assert __version__ == "1.0.0"


def test_readme_and_changelog_name_version():
    root = Path(__file__).resolve().parents[1]
    assert "Ithaca Quant v1.0" in (root / "README.md").read_text()
    assert "v1.0.0" in (root / "CHANGELOG.md").read_text()


def test_app_uses_single_version_constant():
    root = Path(__file__).resolve().parents[1]
    text = (root / "app.py").read_text()
    assert 'st.title(f"📈 Ithaca Quant v{__version__}")' in text
