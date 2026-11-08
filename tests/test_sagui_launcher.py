# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import json
import os
import types

import sagui_launcher as sl
from agent_server.handshake import _pid_start


def test_clean_env_strips_salome_qt_and_python_vars():
    env = {"PYTHONPATH": "a", "LD_LIBRARY_PATH": "b", "QT_PLUGIN_PATH": "c",
           "QT_QPA_PLATFORM_PLUGIN_PATH": "d", "QT_QPA_FONTDIR": "e", "HOME": "/h"}
    assert sl.clean_env(env) == {"HOME": "/h"}
    assert env["PYTHONPATH"] == "a"


def test_window_alive_reads_the_pid_file(tmp_path):
    p = tmp_path / "w.pid"
    assert not sl.window_alive(p)
    p.write_text("garbage")
    assert not sl.window_alive(p)
    p.write_text(json.dumps({"pid": os.getpid(), "pid_start": _pid_start(os.getpid())}))
    assert sl.window_alive(p)
    p.write_text(json.dumps({"pid": 999999999, "pid_start": 1}))
    assert not sl.window_alive(p)


def test_window_alive_rejects_a_recycled_pid(tmp_path):
    p = tmp_path / "w.pid"
    p.write_text(json.dumps({"pid": os.getpid(), "pid_start": _pid_start(os.getpid()) + 1}))
    assert not sl.window_alive(p)


def test_pid_path_lives_in_the_salome_agent_data_dir(monkeypatch):
    from pathlib import Path

    from salome_agent_gui import main_window

    monkeypatch.undo()                      # the real paths, not conftest's tmp ones
    data = Path.home() / ".local" / "share" / "salome-agent"
    assert sl.pid_path() == data / "salome-agent-gui.pid"
    # the window reads what the menu writes
    assert sl.request_path() == main_window.request_path()


def test_ensure_server_reuses_a_running_server():
    calls = []
    thread = types.SimpleNamespace(is_alive=lambda: True)
    core = types.SimpleNamespace(poisoned=lambda: False)
    gp = types.SimpleNamespace(_SERVER=object(), _SERVER_THREAD=thread, _CORE=core,
                               launch=lambda ctx: calls.append(ctx))
    assert sl.ensure_server("ctx", gp) == "reused"
    assert calls == []


def test_ensure_server_starts_when_none():
    calls = []

    def launch(ctx):
        calls.append(ctx)
        gp._SERVER = object()

    gp = types.SimpleNamespace(_SERVER=None, _SERVER_THREAD=None, _CORE=None, launch=launch)
    assert sl.ensure_server("ctx", gp) == "started"
    assert calls == ["ctx"]


def test_ensure_server_starts_when_the_server_thread_is_dead():
    calls = []
    thread = types.SimpleNamespace(is_alive=lambda: False)
    core = types.SimpleNamespace(poisoned=lambda: False)
    gp = types.SimpleNamespace(_SERVER=object(), _SERVER_THREAD=thread, _CORE=core,
                               launch=lambda ctx: calls.append(ctx))
    assert sl.ensure_server("ctx", gp) == "started"
    assert calls == ["ctx"]


def test_ensure_server_starts_when_the_core_is_poisoned():
    calls = []
    thread = types.SimpleNamespace(is_alive=lambda: True)
    core = types.SimpleNamespace(poisoned=lambda: True)
    gp = types.SimpleNamespace(_SERVER=object(), _SERVER_THREAD=thread, _CORE=core,
                               launch=lambda ctx: calls.append(ctx))
    assert sl.ensure_server("ctx", gp) == "started"
    assert calls == ["ctx"]


def test_launch_window_spawns_detached_with_clean_env_and_writes_pid(tmp_path):
    seen = {}

    def popen(args, **kw):
        seen.update(args=args, **kw)
        return types.SimpleNamespace(pid=os.getpid())

    path = tmp_path / "dir" / "w.pid"
    pid = sl.launch_window("/opt/x/bin/salome-agent-gui.sh", path,
                           environ={"PYTHONPATH": "p", "HOME": "/h"}, popen=popen)
    assert pid == os.getpid()
    assert seen["args"] == ["/opt/x/bin/salome-agent-gui.sh"]
    assert seen["start_new_session"] is True
    assert seen["env"] == {"HOME": "/h", "SALOME_AGENT_GUI_PARENT_PID": str(os.getpid())}
    data = json.loads(path.read_text())
    assert data["pid"] == os.getpid()
    assert data["pid_start"] == _pid_start(os.getpid())


def test_run_without_launcher_env_reports_it(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "started")
    monkeypatch.setattr(sl, "pid_path", lambda: tmp_path / "w.pid")
    monkeypatch.delenv("SALOME_AGENT_GUI", raising=False)
    assert "SALOME_AGENT_GUI" in sl.run("ctx")


def test_run_with_live_window_does_not_spawn(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "reused")
    p = tmp_path / "w.pid"
    p.write_text(json.dumps({"pid": os.getpid(), "pid_start": _pid_start(os.getpid())}))
    monkeypatch.setattr(sl, "pid_path", lambda: p)
    monkeypatch.setenv("SALOME_AGENT_GUI", "/x")
    monkeypatch.setattr(sl, "launch_window", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert sl.run("ctx") == ""
    assert json.loads(sl.request_path().read_text()) == {"family": ""}
    assert sl.run("ctx", "agent") == ""
    assert json.loads(sl.request_path().read_text()) == {"family": "agent"}


def test_ensure_server_returns_foreign_when_launch_declines():
    calls = []
    gp = types.SimpleNamespace(_SERVER=None, _SERVER_THREAD=None, _CORE=None,
                               launch=lambda ctx: calls.append(ctx))
    assert sl.ensure_server("ctx", gp) == "foreign"
    assert calls == ["ctx"]


def test_run_on_foreign_server_refuses_and_does_not_spawn(monkeypatch):
    from agent_server import handshake

    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "foreign")
    monkeypatch.setattr(sl, "launch_window", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(handshake, "live_owner",
                        lambda: {"pid": 123, "mode": "gui"})
    msg = sl.run("ctx")
    assert "Stop it first" in msg


def test_run_on_foreign_server_without_owner_details_falls_back(monkeypatch):
    from agent_server import handshake

    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "foreign")
    monkeypatch.setattr(sl, "launch_window", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(handshake, "live_owner", lambda: None)
    msg = sl.run("ctx")
    assert "Messages window" in msg


# ---- the AI tools menu ----------------------------------------------------------
def test_run_opens_the_window_on_the_menu_family(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "started")
    monkeypatch.setenv("SALOME_AGENT_GUI", "/x/salome-agent-gui.sh")
    seen = []
    monkeypatch.setattr(sl, "launch_window", lambda launcher, path, **kw: seen.append(kw["args"]))
    for family in ("agent", "rag", None, "bogus"):
        assert sl.run("ctx", family) == ""
    assert seen == [("--mode", "agent"), ("--mode", "rag"), (), ()]


def test_run_rag_needs_no_agent_server(monkeypatch):
    monkeypatch.setattr(sl, "ensure_server", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setenv("SALOME_AGENT_GUI", "/x")
    monkeypatch.setattr(sl, "launch_window", lambda *a, **k: None)
    assert sl.run("ctx", "rag") == ""

