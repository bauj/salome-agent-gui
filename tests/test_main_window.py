import json
import os
import subprocess
import sys
import threading

import pytest
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QLabel

from salome_agent_gui.main_window import MainWindow
from tests.fakes import opener, write_cfg

GUI = {"mode": "gui", "port": 4242}


@pytest.fixture
def cfg_path(tmp_path):
    return write_cfg(tmp_path)


def make(qtbot, cfg_path, rec, **kw):
    made = {}

    def factory(parent, bridge):
        made["bridge"] = bridge
        return QLabel("page", parent)

    w = MainWindow(cfg_path, open_fn=opener(rec), probe_fn=lambda: GUI, view_factory=factory,
                   **kw)
    qtbot.addWidget(w)
    return w, made


def test_window_hosts_the_factory_view_and_its_bridge(qtbot, cfg_path):
    w, made = make(qtbot, cfg_path, {})
    assert isinstance(w.centralWidget(), QLabel)
    assert made["bridge"] is w.bridge
    assert w.bridge.connected is True            # start() probed once


def test_close_when_idle_closes_immediately(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {})
    w.show()
    w.close()
    assert not w.isVisible()


def test_close_during_a_turn_waits_for_the_worker_then_closes(qtbot, cfg_path):
    rec = {}
    w, _ = make(qtbot, cfg_path, rec)
    w.show()
    b = w.bridge
    pushes = []
    b.push.connect(lambda name, payload: pushes.append((name, json.loads(payload))))
    b.ready()
    b.send("make a box")
    qtbot.waitUntil(lambda: any(n == "renderTurn" and p["gate"] for n, p in pushes),
                    timeout=3000)
    gate = [p for n, p in pushes if n == "renderTurn" and p["gate"]][-1]["gate"]
    b.gate(gate["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    rec["conv"].release = threading.Event()
    b.send("slow")
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    w.close()
    assert w.isVisible() and b.close_pending
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: not w.isVisible(), timeout=5000)
    assert rec["closed"] == 1


def test_check_parent_closes_when_parent_is_gone(qtbot, cfg_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    w, _ = make(qtbot, cfg_path, {}, parent_pid=proc.pid)
    w.show()
    w._check_parent()
    assert not w.isVisible()


def test_check_parent_leaves_window_open_when_parent_is_alive(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {}, parent_pid=os.getpid())
    w.show()
    w._check_parent()
    assert w.isVisible()


def test_no_parent_pid_starts_no_watch_timer(qtbot, cfg_path, monkeypatch):
    monkeypatch.delenv("SALOME_AGENT_GUI_PARENT_PID", raising=False)
    w, _ = make(qtbot, cfg_path, {})
    assert w._parent_watch is None


def test_palette_decides_whether_the_system_theme_is_dark(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {})
    pal = w.palette()
    pal.setColor(QPalette.Window, QColor(20, 20, 20))
    w.setPalette(pal)
    assert w._palette_is_dark() is True
    pal.setColor(QPalette.Window, QColor(240, 240, 240))
    w.setPalette(pal)
    assert w._palette_is_dark() is False
