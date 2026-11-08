# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import json
import os
from pathlib import Path

from PyQt5.QtCore import QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QPalette
from PyQt5.QtWidgets import QMainWindow

from salome_agent_gui import config_store, dialogs, web_view
from salome_agent_gui.bridge import Bridge


def request_path() -> Path:
    """Where the SALOME menu (sagui_launcher.request_family) asks the open
    window for another family of modes."""
    return Path.home() / ".local" / "share" / "salome-agent" / "gui-request.json"


def take_request(path: Path) -> str | None:
    """The family a pending request asks for, removing the request; None
    without one. A request with no family ("") reopens the window as is."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return str(data.get("family") or "") if isinstance(data, dict) else None


def _open_file(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def _open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class MainWindow(QMainWindow):
    """Thin shell: the chat is a web page; the Bridge holds the state."""

    def __init__(self, config_path: Path, *, open_fn=None, probe_fn=None, edit_plan=None,
                 parent_pid: int | None = None, view_factory=None, system_dark=None,
                 notice: str | None = None, family: str | None = None,
                 request_file: Path | None = None):
        super().__init__()
        self.setWindowTitle("SALOME agentic assistants")
        self.resize(900, 780)
        geometry = config_store.window_geometry()
        if geometry:
            self.restoreGeometry(geometry)
        self._closing = False
        self.bridge = Bridge(config_path, open_fn=open_fn, probe_fn=probe_fn,
                             edit_plan=edit_plan or dialogs.edit_plan,
                             edit_config=dialogs.edit_config, pick_config=dialogs.pick_config,
                             open_file=_open_file, open_url=_open_url,
                             system_dark=system_dark or self._palette_is_dark,
                             dialog_parent=self, family=family, parent=self)
        self.bridge.close_ready.connect(self._close_now)
        if notice:
            self.bridge.note(notice)
        self.view = (view_factory or web_view.create)(self, self.bridge)
        self.setCentralWidget(self.view)
        self.bridge.start()

        self._request_file = request_file or request_path()
        take_request(self._request_file)        # a stale one predates this window
        self._request_watch = QTimer(self)
        self._request_watch.setInterval(700)
        self._request_watch.timeout.connect(self._check_request)
        self._request_watch.start()

        if parent_pid is None:
            try:
                parent_pid = int(os.environ["SALOME_AGENT_GUI_PARENT_PID"])
            except (KeyError, ValueError):
                parent_pid = None
        self._parent_pid = parent_pid
        self._parent_watch = None
        if self._parent_pid is not None:
            self._parent_watch = QTimer(self)
            self._parent_watch.setInterval(2000)
            self._parent_watch.timeout.connect(self._check_parent)
            self._parent_watch.start()

    def _check_request(self):
        family = take_request(self._request_file)
        if family is None:
            return
        if family:
            self.bridge.set_family(family)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _palette_is_dark(self) -> bool:
        return self.palette().color(QPalette.Window).lightness() < 128

    def _check_parent(self):
        try:
            os.kill(self._parent_pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            return
        else:
            return
        self._parent_watch.stop()
        self.close()

    def _close_now(self):
        self._closing = True
        self.close()

    def closeEvent(self, e):
        if self._closing or self.bridge.request_close():
            try:
                config_store.save_window_geometry(bytes(self.saveGeometry()))
            except OSError:
                pass
            super().closeEvent(e)
            return
        e.ignore()
