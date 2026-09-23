from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QTextBrowser

from salome_agent_gui.timeline import Note, RunView, render_note, render_run, render_user


def _render(item) -> str:
    if isinstance(item, RunView):
        return render_run(item)
    if isinstance(item, Note):
        return render_note(item)
    return render_user(item)


class ChatView(QTextBrowser):
    gate_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._on_anchor)
        self._items: list = []
        self._md = ""

    def add_user(self, text: str) -> None:
        self._items.append(text)
        self.refresh()

    def add_run(self) -> RunView:
        view = RunView()
        self._items.append(view)
        self.refresh()
        return view

    def add_note(self, text: str) -> None:
        self._items.append(Note(text))
        self.refresh()

    def markdown(self) -> str:
        return self._md

    def refresh(self) -> None:
        parts = [_render(i) for i in self._items]
        self._md = "\n\n---\n\n".join(parts)
        self.setMarkdown(self._md)
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_anchor(self, url) -> None:
        if url.scheme() == "gate":
            self.gate_clicked.emit(url.path())
        else:
            QDesktopServices.openUrl(url)
