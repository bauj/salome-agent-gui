# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""SALOME-side half of the SALOME Agent plugin (Tools > Plugins > AI tools):
start/reuse the in-GUI agent server and spawn the chat window (its own venv)
once, on the family of modes the menu entry chose. Stdlib only: this runs in
SALOME's Python."""
import json
import os
import subprocess
from pathlib import Path

# the menu entries' families of modes (salome_agent_gui.rag_backend.FAMILY_MODES)
FAMILIES = ("agent", "rag")
TITLE = "SALOME AI tools"

STRIP_VARS = ("PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
              "QT_QPA_FONTDIR", "LD_LIBRARY_PATH")


def clean_env(environ) -> dict:
    env = dict(environ)
    for var in STRIP_VARS:
        env.pop(var, None)
    return env


def data_dir() -> Path:
    return Path.home() / ".local" / "share" / "salome-agent"


def pid_path() -> Path:
    return data_dir() / "salome-agent-gui.pid"


def request_path() -> Path:
    """Read by the open window (salome_agent_gui.main_window.request_path)."""
    return data_dir() / "gui-request.json"


def _write_private(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def window_alive(path: Path) -> bool:
    try:
        data = json.loads(Path(path).read_text())
        pid = int(data["pid"])
        stored_start = data.get("pid_start")
    except (OSError, ValueError, KeyError, TypeError):
        return False
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)   # reap our own exited child (else a zombie looks alive)
        if done == pid:
            return False
    except ChildProcessError:
        pass
    try:
        from agent_server.handshake import _pid_start
    except ImportError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    live_start = _pid_start(pid)
    if live_start is None:
        return False
    if stored_start is not None and stored_start != live_start:
        return False               # pid was reused by an unrelated process
    return True


def ensure_server(context, gui_plugin=None) -> str:
    if gui_plugin is None:
        from agent_server import gui_plugin
    thread = getattr(gui_plugin, "_SERVER_THREAD", None)
    core = getattr(gui_plugin, "_CORE", None)
    if (gui_plugin._SERVER is not None and thread is not None and thread.is_alive()
            and core is not None and not core.poisoned()):
        return "reused"
    gui_plugin.launch(context)
    if gui_plugin._SERVER is None:
        return "foreign"
    return "started"


def launch_window(launcher: str, path: Path, environ=None, popen=subprocess.Popen,
                  args=()) -> int:
    """Spawn `launcher args...` detached, with SALOME's environment stripped, and
    record its pid in `path`."""
    env = clean_env(os.environ if environ is None else environ)
    env["SALOME_AGENT_GUI_PARENT_PID"] = str(os.getpid())
    proc = popen([launcher, *args], start_new_session=True, env=env)
    try:
        from agent_server.handshake import _pid_start
        pid_start = _pid_start(proc.pid)
    except ImportError:
        pid_start = None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": proc.pid, "pid_start": pid_start}))
    return proc.pid


def request_family(family: str, path: Path | None = None) -> None:
    """Ask the open window to show `family` ("" only raises it)."""
    _write_private(path or request_path(), {"family": family or ""})


def _server_problem(context, what: str) -> str:
    """Start or reuse the agent server; a message when it is not this SALOME's."""
    if ensure_server(context) != "foreign":
        return ""
    from agent_server import handshake

    owner = handshake.live_owner()
    if owner is not None:
        return (f"Another SALOME agent server is already running (pid {owner['pid']}, "
                f"{owner.get('mode')} mode). {what} would drive that session, "
                "not this SALOME. Stop it first, then click again.")
    return ("The SALOME agent server could not be started in this SALOME; "
            "see the Messages window.")


def run(context, family: str | None = None) -> str:
    """Open the chat window on `family` ("agent": the Agentic assistant, "rag":
    the documentation modes), or bring the open one to it. A message for the
    user, or "" when done."""
    family = family if family in FAMILIES else None
    if family != "rag":               # the documentation modes need no agent server
        problem = _server_problem(context, "The chat window")
        if problem:
            return problem
    path = pid_path()
    if window_alive(path):
        request_family(family or "")
        return ""
    launcher = os.environ.get("SALOME_AGENT_GUI")
    if not launcher:
        return ("SALOME_AGENT_GUI is not set; the chat window cannot be started "
                "(install the salome_agent_gui SAT product).")
    launch_window(launcher, path, args=("--mode", family) if family else ())
    return ""


# ---- the menu entries (salome_plugins.py) -------------------------------------
def _parent_window():
    try:
        from PyQt5.QtWidgets import QApplication
        return QApplication.activeWindow()
    except Exception:  # noqa: BLE001
        return None


def menu_window(context, family: str) -> None:
    """Tools > Plugins > AI tools > SALOME agent / Documentation (RAG)."""
    from PyQt5.QtWidgets import QMessageBox

    try:
        msg = run(context, family)
    except Exception as e:  # noqa: BLE001
        QMessageBox.warning(_parent_window(), TITLE, f"Failed to open the window:\n{e}")
        return
    if msg:
        QMessageBox.information(_parent_window(), TITLE, msg)
