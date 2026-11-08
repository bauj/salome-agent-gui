# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
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


def test_window_opens_at_the_size_it_was_closed_at(qtbot, cfg_path, gui_state):
    w, _ = make(qtbot, cfg_path, {})
    w.show()
    w.resize(640, 500)
    w.close()
    assert json.loads(gui_state.read_text())["window_geometry"]
    again, _ = make(qtbot, cfg_path, {})
    assert (again.width(), again.height()) == (640, 500)


def test_window_opens_at_the_default_size_without_a_saved_one(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {})
    assert (w.width(), w.height()) == (900, 780)


def test_window_ignores_an_unreadable_saved_geometry(qtbot, cfg_path, gui_state):
    gui_state.parent.mkdir(parents=True, exist_ok=True)
    gui_state.write_text(json.dumps({"window_geometry": "not base64!"}))
    w, _ = make(qtbot, cfg_path, {})
    assert (w.width(), w.height()) == (900, 780)


# ---- requests from the SALOME menu (sagui_launcher.request_family) -------------
def test_a_menu_request_moves_the_window_to_the_family(qtbot, cfg_path, tmp_path):
    import sagui_launcher

    from salome_agent_gui import main_window

    req = tmp_path / "req.json"
    w, made = make(qtbot, cfg_path, {}, family="agent", request_file=req)
    assert made["bridge"].family == "agent"
    sagui_launcher.request_family("rag", req)
    w._check_request()
    assert made["bridge"].family == "rag" and not req.exists()
    assert main_window.take_request(req) is None
    sagui_launcher.request_family("", req)              # only raises the window
    assert main_window.take_request(req) == ""


def test_a_request_left_before_the_window_opened_is_dropped(qtbot, cfg_path, tmp_path):
    import sagui_launcher

    req = tmp_path / "req.json"
    sagui_launcher.request_family("rag", req)
    w, made = make(qtbot, cfg_path, {}, family="agent", request_file=req)
    assert not req.exists() and made["bridge"].family == "agent"


def test_app_takes_the_menu_family_out_of_qts_arguments():
    from salome_agent_gui.app import split_family

    assert split_family(["prog", "--mode", "rag", "-style", "x"]) == ("rag", ["prog", "-style", "x"])
    assert split_family(["prog", "--mode=agent"]) == ("agent", ["prog"])
    assert split_family(["prog"]) == (None, ["prog"])
