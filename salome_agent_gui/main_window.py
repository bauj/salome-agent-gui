import os
from pathlib import Path

from PyQt5.QtCore import QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QPalette
from PyQt5.QtWidgets import QMainWindow

from salome_agent_gui import dialogs, web_view
from salome_agent_gui.bridge import Bridge


def _open_file(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class MainWindow(QMainWindow):
    """Thin shell: the chat is a web page; the Bridge holds the state."""

    def __init__(self, config_path: Path, *, open_fn=None, probe_fn=None, edit_plan=None,
                 parent_pid: int | None = None, view_factory=None, system_dark=None):
        super().__init__()
        self.setWindowTitle("SALOME Agent")
        self.resize(900, 780)
        self._closing = False
        self.bridge = Bridge(config_path, open_fn=open_fn, probe_fn=probe_fn,
                             edit_plan=edit_plan or dialogs.edit_plan,
                             edit_config=dialogs.edit_config, open_file=_open_file,
                             system_dark=system_dark or self._palette_is_dark,
                             dialog_parent=self, parent=self)
        self.bridge.close_ready.connect(self._close_now)
        self.view = (view_factory or web_view.create)(self, self.bridge)
        self.setCentralWidget(self.view)
        self.bridge.start()

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
            super().closeEvent(e)
            return
        e.ignore()
