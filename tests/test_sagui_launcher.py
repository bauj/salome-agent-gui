import os
import types

import sagui_launcher as sl


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
    p.write_text(str(os.getpid()))
    assert sl.window_alive(p)
    p.write_text("999999999")
    assert not sl.window_alive(p)


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
    gp = types.SimpleNamespace(_SERVER=None, _SERVER_THREAD=None, _CORE=None,
                               launch=lambda ctx: calls.append(ctx))
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
        return types.SimpleNamespace(pid=4321)

    pid = sl.launch_window("/opt/x/bin/salome-agent-gui.sh", tmp_path / "w.pid",
                           environ={"PYTHONPATH": "p", "HOME": "/h"}, popen=popen)
    assert pid == 4321
    assert seen["args"] == ["/opt/x/bin/salome-agent-gui.sh"]
    assert seen["start_new_session"] is True
    assert seen["env"] == {"HOME": "/h", "SALOME_AGENT_GUI_PARENT_PID": str(os.getpid())}
    assert (tmp_path / "w.pid").read_text() == "4321"


def test_run_without_launcher_env_reports_it(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "started")
    monkeypatch.setattr(sl, "pid_path", lambda: tmp_path / "w.pid")
    monkeypatch.delenv("SALOME_AGENT_GUI", raising=False)
    assert "SALOME_AGENT_GUI" in sl.run("ctx")


def test_run_with_live_window_does_not_spawn(monkeypatch, tmp_path):
    monkeypatch.setattr(sl, "ensure_server", lambda ctx, gui_plugin=None: "reused")
    p = tmp_path / "w.pid"
    p.write_text(str(os.getpid()))
    monkeypatch.setattr(sl, "pid_path", lambda: p)
    monkeypatch.setenv("SALOME_AGENT_GUI", "/x")
    monkeypatch.setattr(sl, "launch_window", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert "already open" in sl.run("ctx")
