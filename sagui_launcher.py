"""SALOME-side half of the SALOME Agent plugin: start/reuse the in-GUI agent
server and spawn the chat window (its own venv) once."""
import json
import os
import subprocess
from pathlib import Path

STRIP_VARS = ("PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH",
              "QT_QPA_FONTDIR", "LD_LIBRARY_PATH")


def clean_env(environ) -> dict:
    env = dict(environ)
    for var in STRIP_VARS:
        env.pop(var, None)
    return env


def pid_path() -> Path:
    return Path.home() / ".salome_agent" / "salome-agent-gui.pid"


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


def launch_window(launcher: str, path: Path, environ=None, popen=subprocess.Popen) -> int:
    env = clean_env(os.environ if environ is None else environ)
    env["SALOME_AGENT_GUI_PARENT_PID"] = str(os.getpid())
    proc = popen([launcher], start_new_session=True, env=env)
    try:
        from agent_server.handshake import _pid_start
        pid_start = _pid_start(proc.pid)
    except ImportError:
        pid_start = None
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": proc.pid, "pid_start": pid_start}))
    return proc.pid


def run(context) -> str:
    if ensure_server(context) == "foreign":
        from agent_server import handshake

        owner = handshake.live_owner()
        if owner is not None:
            return (f"Another SALOME agent server is already running (pid {owner['pid']}, "
                    f"{owner.get('mode')} mode). The chat window would drive that session, "
                    "not this SALOME. Stop it first, then click again.")
        return ("The SALOME agent server could not be started in this SALOME; "
                "see the Messages window.")
    path = pid_path()
    if window_alive(path):
        return "The SALOME Agent window is already open."
    launcher = os.environ.get("SALOME_AGENT_GUI")
    if not launcher:
        return ("SALOME_AGENT_GUI is not set; the agent server is running but the chat "
                "window cannot be started (install the salome_agent_gui SAT product).")
    launch_window(launcher, path)
    return ""
