from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QLabel

WEB_DIR = Path(__file__).resolve().parent / "web"
WEBENGINE_HELP = (
    "The chat page could not start ({error}).\n\n"
    "Qt WebEngine (Chromium) failed to load. Start SALOME again with one of these set:\n"
    "    QTWEBENGINE_DISABLE_SANDBOX=1\n"
    "    QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu\n"
    "and check that PyQtWebEngine is installed in the salome_agent_gui environment.")


def fallback(parent, error) -> QLabel:
    label = QLabel(WEBENGINE_HELP.format(error=error), parent)
    label.setWordWrap(True)
    label.setMargin(24)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def create(parent, bridge):
    try:
        from PyQt5.QtWebChannel import QWebChannel
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError as e:
        return fallback(parent, e)
    view = QWebEngineView(parent)
    view.setContextMenuPolicy(Qt.NoContextMenu)
    # Drops reach the page (images to attach); app.js handles every drop, so a
    # dropped file never makes the view navigate away from the chat.
    channel = QWebChannel(view.page())
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)
    view._channel = channel                     # the page does not own it; keep it alive

    def on_crash(status, code):
        bridge.page_lost()
        view.reload()

    view.page().renderProcessTerminated.connect(on_crash)
    view.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))
    return view
