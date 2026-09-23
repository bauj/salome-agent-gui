import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_webengine_pins_match_the_qt_wheels():
    deps = _pyproject()["project"]["dependencies"]
    for pin in ("PyQt5-Qt5==5.15.19", "PyQtWebEngine==5.15.7", "PyQtWebEngine-Qt5==5.15.19"):
        assert pin in deps


def test_web_assets_are_package_data():
    data = _pyproject()["tool"]["setuptools"]["package-data"]["salome_agent_gui"]
    assert "web/*" in data


def test_webengine_is_importable():
    import PyQt5.QtWebChannel  # noqa: F401
    import PyQt5.QtWebEngineWidgets  # noqa: F401


def test_logo_is_shipped():
    logo = ROOT / "salome_agent_gui" / "web" / "salome-s.png"
    assert logo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
