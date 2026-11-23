# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import pytest
from PyQt5.QtWidgets import QLabel, QTabBar

from salome_agent_gui import doc_browser


def test_targets_become_urls():
    assert doc_browser.to_url("https://example.org/x#y").toString() == "https://example.org/x#y"
    assert doc_browser.to_url("/docs/a b.html").toLocalFile() == "/docs/a b.html"
    url = doc_browser.to_url("/docs/page.html#section")
    assert url.toLocalFile() == "/docs/page.html" and url.fragment() == "section"


def test_the_chat_is_a_fixed_first_tab(qtbot):
    tabs = doc_browser.WindowTabs(QLabel("chat"))
    qtbot.addWidget(tabs)
    assert tabs.count() == 1 and tabs.tabText(0) == doc_browser.CHAT_TAB_TITLE
    assert tabs.tabBar().tabButton(0, QTabBar.RightSide) is None
    tabs.close_tab(0)
    assert tabs.count() == 1


@pytest.mark.web
def test_each_link_opens_a_new_tab_beside_the_chat(qtbot, tmp_path):
    page = tmp_path / "page.html"
    page.write_text("<html><head><title>GEOM page</title></head><body>hi</body></html>")
    chat = QLabel("chat")
    tabs = doc_browser.WindowTabs(chat)
    qtbot.addWidget(tabs)
    tabs.show()
    tabs.open(str(page))
    tabs.open(str(page) + "#x")
    assert tabs.count() == 3 and tabs.currentIndex() == 2
    assert not tabs.tabBar().isHidden()
    qtbot.waitUntil(lambda: tabs.tabText(2) == "GEOM page", timeout=10000)
    assert tabs.currentWidget().view.url().fragment() == "x"
    tabs.close_docs()
    assert tabs.count() == 1 and tabs.widget(0) is chat and tabs.tabBar().isHidden()
