# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""The window's tabs: the chat is the first one, and each page a documentation
answer cites opens in a new tab beside it, instead of in the system browser."""
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWidgets import (QAction, QLineEdit, QShortcut, QTabBar, QTabWidget, QToolBar,
                             QVBoxLayout, QWidget)

try:
    from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineView
except ImportError:                              # no Qt WebEngine: the system browser
    QWebEnginePage = QWebEngineView = None

NEW_TAB_TITLE = "Loading…"
CHAT_TAB_TITLE = "Chat"


def to_url(target: str) -> QUrl:
    """A web URL, a file:// URL or a local path (with or without #anchor)."""
    if target.startswith(("http://", "https://", "file://")):
        return QUrl(target)
    path, sep, anchor = target.partition("#")
    url = QUrl.fromLocalFile(path)
    if sep:
        url.setFragment(anchor)
    return url


def available() -> bool:
    """Whether pages can open in the window (Qt WebEngine is there)."""
    return QWebEngineView is not None


def open_externally(target: str) -> None:
    QDesktopServices.openUrl(to_url(target))


if QWebEnginePage is not None:
    class _Page(QWebEnginePage):
        """A link asking for a new window (target=_blank, middle click) opens a
        new tab of the same window."""

        def __init__(self, tabs, parent=None):
            super().__init__(parent)
            self._tabs = tabs

        def createWindow(self, _type):
            return self._tabs.new_tab().view.page()


class DocTab(QWidget):
    """One documentation page: a navigation bar over its web view."""

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self.view = QWebEngineView(self)
        self.view.setPage(_Page(tabs, self.view))
        bar = QToolBar("Navigation", self)
        bar.setMovable(False)
        self._back = self._action(bar, "Back", QKeySequence.Back, self.view.back)
        self._forward = self._action(bar, "Forward", QKeySequence.Forward, self.view.forward)
        self._action(bar, "Reload", QKeySequence.Refresh, self.view.reload)
        self.address = QLineEdit(self)
        self.address.returnPressed.connect(self._go)
        bar.addWidget(self.address)
        external = QAction("Open in system browser", self)
        external.setToolTip("Open this page in the system's web browser")
        external.triggered.connect(self._external)
        bar.addAction(external)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(bar)
        layout.addWidget(self.view, 1)
        self.view.urlChanged.connect(self._on_url)
        self._sync_history()

    def _action(self, bar, text, keys, fn):
        a = QAction(text, self)
        a.setShortcut(keys)
        a.setShortcutContext(Qt.WidgetWithChildrenShortcut)   # not while the chat is shown
        a.triggered.connect(fn)
        bar.addAction(a)
        self.addAction(a)
        return a

    def _on_url(self, url):
        self.address.setText(url.toString())
        self._sync_history()

    def _sync_history(self):
        history = self.view.history()
        self._back.setEnabled(history.canGoBack())
        self._forward.setEnabled(history.canGoForward())

    def _go(self):
        text = self.address.text().strip()
        if text:
            self.view.load(QUrl.fromUserInput(text))

    def _external(self):
        if not self.view.url().isEmpty():
            QDesktopServices.openUrl(self.view.url())


class WindowTabs(QTabWidget):
    """The chat as a fixed first tab, then one closable tab per opened page.
    The tab bar shows only once a page is open."""

    def __init__(self, chat: QWidget, parent=None):
        super().__init__(parent)
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setMovable(False)
        self.setTabBarAutoHide(True)
        self.chat = chat
        self.addTab(chat, CHAT_TAB_TITLE)
        for side in (QTabBar.LeftSide, QTabBar.RightSide):
            self.tabBar().setTabButton(0, side, None)          # the chat cannot be closed
        self.tabCloseRequested.connect(self.close_tab)
        QShortcut(QKeySequence.Close, self, activated=lambda: self.close_tab(self.currentIndex()))

    def doc_tabs(self) -> list:
        return [self.widget(i) for i in range(1, self.count())]

    def new_tab(self) -> DocTab:
        tab = DocTab(self, self)
        index = self.addTab(tab, NEW_TAB_TITLE)
        tab.view.titleChanged.connect(lambda title, t=tab: self._set_title(t, title))
        self.setCurrentIndex(index)
        return tab

    def open(self, target: str) -> None:
        """`target` in a new tab, shown."""
        self.new_tab().view.load(to_url(target))

    def close_tab(self, index: int) -> None:
        if index <= 0:                                          # the chat stays
            return
        tab = self.widget(index)
        if tab is None:
            return
        self.removeTab(index)
        tab.deleteLater()

    def close_docs(self) -> None:
        while self.count() > 1:
            self.close_tab(self.count() - 1)

    def _set_title(self, tab, title):
        index = self.indexOf(tab)
        if index < 0:
            return
        url = tab.view.url()
        text = title or url.fileName() or url.toString()
        self.setTabText(index, text if len(text) <= 32 else text[:31] + "…")
        self.setTabToolTip(index, title or url.toString())
