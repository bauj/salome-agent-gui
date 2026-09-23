import sys

from PyQt5.QtWidgets import QLabel

from salome_agent_gui import web_view
from tools.page_fixtures import FakeBridge


def test_web_dir_holds_the_page():
    for name in ("index.html", "app.css", "app.js", "salome-s.png"):
        assert (web_view.WEB_DIR / name).is_file(), name


def test_missing_webengine_gives_a_fallback_panel_with_the_fixes(qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "PyQt5.QtWebEngineWidgets", None)
    w = web_view.create(None, FakeBridge())
    qtbot.addWidget(w)
    assert isinstance(w, QLabel)
    assert "QTWEBENGINE_DISABLE_SANDBOX=1" in w.text()
    assert "--disable-gpu" in w.text()


def test_page_never_loads_remote_resources():
    for name in ("index.html", "app.css", "app.js"):
        text = (web_view.WEB_DIR / name).read_text()
        assert "http://" not in text and "https://" not in text.replace(
            "http://www.w3.org/2000/svg", ""), name


def test_batch_switch_says_it_also_skips_the_failure_prompt():
    html = (web_view.WEB_DIR / "index.html").read_text()
    assert "Auto-approve plans" not in html
    assert html.count("Run without asking") == 2
    assert "stage-failure prompt" in html
