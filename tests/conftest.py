import os

import pytest
from PyQt5.QtCore import QCoreApplication, Qt

# Qt requires QtWebEngineWidgets to be imported, and context sharing switched
# on, before the QApplication exists; pytest-qt creates it on first use.
try:
    import PyQt5.QtWebEngineWidgets  # noqa: F401
    HAVE_WEBENGINE = True
except ImportError:
    HAVE_WEBENGINE = False
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)


def pytest_collection_modifyitems(config, items):
    if not HAVE_WEBENGINE:
        reason = "PyQtWebEngine is not installed"
    elif os.environ.get("QT_QPA_PLATFORM") != "xcb" or not os.environ.get("DISPLAY"):
        reason = "web tests need QT_QPA_PLATFORM=xcb and a DISPLAY (Qt WebEngine does not run offscreen)"
    else:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "web" in item.keywords:
            item.add_marker(skip)
