# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""SALOME-side half of the SALOME Agent plugin (Tools > Plugins > AI tools):
start/reuse the in-GUI agent server, spawn the chat window (its own venv) once
on the family of modes the menu entry chose, or start the MCP server that
Claude Code, Gemini CLI and other MCP clients connect to. Stdlib only, plus
PyQt5 for the MCP dialog: this runs in SALOME's Python."""
import json
import os
import secrets
import signal
import socket
import subprocess
from pathlib import Path

# the menu entries' families of modes (salome_agent_gui.rag_backend.FAMILY_MODES)
FAMILIES = ("agent", "rag")
TITLE = "SALOME AI tools"
MCP_NAME = "salome-agent"
MCP_DEFAULT_PORT = 47801         # salome_agent_gui.mcp_server.DEFAULT_PORT

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


def mcp_pid_path() -> Path:
    return data_dir() / "salome-agent-mcp.pid"


def mcp_log_path() -> Path:
    return data_dir() / "salome-agent-mcp.log"


def mcp_settings_path() -> Path:
    """Port and token of the MCP server (salome_agent_gui.mcp_server.HTTP_FILE)."""
    return data_dir() / "mcp-http.json"


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


process_alive = window_alive


def launch_window(launcher: str, path: Path, environ=None, popen=subprocess.Popen,
                  args=(), **popen_kw) -> int:
    """Spawn `launcher args...` detached, with SALOME's environment stripped, and
    record its pid in `path`. Also starts the MCP server (args --mcp --http)."""
    env = clean_env(os.environ if environ is None else environ)
    env["SALOME_AGENT_GUI_PARENT_PID"] = str(os.getpid())
    proc = popen([launcher, *args], start_new_session=True, env=env, **popen_kw)
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


# ---- the MCP server ----------------------------------------------------------
def mcp_settings(path: Path | None = None) -> dict:
    """{"port", "token"}, created on first use and kept, so a client is
    registered once. Same file and format as salome_agent_gui.mcp_server.http_settings."""
    path = Path(path or mcp_settings_path())
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    port, token = data.get("port"), data.get("token")
    if not isinstance(port, int) or not isinstance(token, str) or len(token) < 16:
        port = port if isinstance(port, int) else MCP_DEFAULT_PORT
        token = token if isinstance(token, str) and len(token) >= 16 else secrets.token_urlsafe(24)
        _write_private(path, {"port": port, "token": token})
    return {"port": port, "token": token}


def mcp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def client_commands(port: int, token: str) -> dict:
    """Kept equal to salome_agent_gui.mcp_server.client_commands (a test checks)."""
    url, auth = mcp_url(port), f"Authorization: Bearer {token}"
    # flags before the name for gemini and agy (agy rejects them after it, and has
    # no --transport: it sees the http URL); claude's --header takes several
    # values, so it goes last. --scope user: every folder, not only the current one.
    return {"Claude Code": f'claude mcp add --scope user --transport http {MCP_NAME} {url} '
                           f'--header "{auth}"',
            "Gemini CLI": f'gemini mcp add --scope user --transport http --header "{auth}" '
                          f'{MCP_NAME} {url}',
            "Antigravity (agy)": f'agy mcp add --header "{auth}" {MCP_NAME} {url}',
            "Other MCP clients": f"URL {url}, header {auth}"}


def port_open(port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def run_mcp(context, popen=subprocess.Popen) -> dict:
    """Start (or reuse) the agent server and the MCP server waiting for clients.
    {"error": message} or {"port", "token", "started", "log"}."""
    problem = _server_problem(context, "The MCP server")
    if problem:
        return {"error": problem}
    settings = mcp_settings()
    info = {**settings, "started": False, "log": str(mcp_log_path())}
    if process_alive(mcp_pid_path()):
        return info
    launcher = os.environ.get("SALOME_AGENT_GUI")
    if not launcher:
        return {"error": "SALOME_AGENT_GUI is not set; the MCP server cannot be started "
                         "(install the salome_agent_gui SAT product)."}
    if port_open(settings["port"]):
        return {"error": f"Port {settings['port']} is already in use by another program. "
                         f"Choose another \"port\" in {mcp_settings_path()}, then click again "
                         "(and register the clients again with the new address)."}
    log = mcp_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        launch_window(launcher, mcp_pid_path(), popen=popen, args=("--mcp", "--http"),
                      stdin=subprocess.DEVNULL, stdout=out, stderr=out)
    info["started"] = True
    return info


def stop_mcp() -> bool:
    path = mcp_pid_path()
    if not process_alive(path):
        return False
    try:
        os.kill(int(json.loads(path.read_text())["pid"]), signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        return False
    return True


_DIALOG = None      # the open MCP dialog, kept alive (it is not modal)


def show_mcp_dialog(info: dict, parent=None, alive_fn=None, port_fn=None, stop_fn=None):
    """A small window: whether the MCP server listens, and the commands that
    connect Claude Code, Gemini CLI or another client to it. Closing it leaves
    the server running."""
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont, QGuiApplication
    from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit,
                                 QPushButton, QVBoxLayout)

    global _DIALOG
    alive_fn = alive_fn or (lambda: process_alive(mcp_pid_path()))
    port_fn = port_fn or port_open
    stop_fn = stop_fn or stop_mcp
    if _DIALOG is not None:
        try:
            _DIALOG.close()
        except RuntimeError:
            pass
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"{TITLE}: MCP server")
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.setMinimumWidth(720)
    lay = QVBoxLayout(dlg)
    url = mcp_url(info["port"])
    status = QLabel()
    status.setTextFormat(Qt.RichText)
    lay.addWidget(status)
    intro = QLabel(
        "SALOME is served to AI clients over the Model Context Protocol: the client holds "
        "the conversation and builds in this study with the GEOM, SHAPER and SMESH tools, and "
        "searches the SALOME documentation. Register the server once in your client, in a "
        "terminal (the address and token are kept for the next sessions):")
    intro.setWordWrap(True)
    lay.addWidget(intro)
    grid = QGridLayout()
    mono = QFont("Monospace")
    mono.setStyleHint(QFont.TypeWriter)
    for row, (name, line) in enumerate(client_commands(info["port"], info["token"]).items()):
        grid.addWidget(QLabel(f"<b>{name}</b>"), row, 0)
        edit = QLineEdit(line)
        edit.setReadOnly(True)
        edit.setFont(mono)
        edit.setCursorPosition(0)
        edit.setObjectName(f"cmd-{row}")
        grid.addWidget(edit, row, 1)
        copy = QPushButton("Copy")
        copy.clicked.connect(lambda _=False, t=line: QGuiApplication.clipboard().setText(t))
        grid.addWidget(copy, row, 2)
    lay.addLayout(grid)
    notes = QLabel(
        "Then ask the client for something in SALOME, e.g. <i>make a 10 mm cube with a 2 mm "
        "fillet</i>. The server runs until SALOME closes or you stop it; closing this window "
        "leaves it running. The agent server serves one client at a time: keep the chat window "
        "out of an Agentic assistant conversation while a client builds.<br>Claude Desktop "
        "starts its own server instead: <tt>salome-agent-gui.sh --mcp --desktop-config</tt> "
        f"prints its entry. Log: <tt>{info.get('log', '')}</tt>")
    notes.setWordWrap(True)
    notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lay.addWidget(notes)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    stop = buttons.addButton("Stop server", QDialogButtonBox.DestructiveRole)
    buttons.rejected.connect(dlg.close)
    lay.addWidget(buttons)

    ticks = {"n": 0}

    def refresh():
        ticks["n"] += 1
        if port_fn(info["port"]) and alive_fn():
            status.setText(f"<b>MCP server running</b>, waiting for clients on <tt>{url}</tt>")
            stop.setEnabled(True)
        elif alive_fn() and ticks["n"] < 60:
            status.setText("<b>MCP server starting…</b>")
            stop.setEnabled(True)
        else:
            status.setText("<b>MCP server not running.</b> Choose Tools &gt; Plugins &gt; AI "
                           f"tools &gt; MCP server to start it; see the log if it stopped.")
            stop.setEnabled(False)

    def stop_clicked():
        stop_fn()
        ticks["n"] = 60
        QTimer.singleShot(300, refresh)

    stop.clicked.connect(stop_clicked)
    timer = QTimer(dlg)
    timer.setInterval(500)
    timer.timeout.connect(refresh)
    timer.start()
    refresh()
    dlg.timer = timer
    dlg.show()
    _DIALOG = dlg
    return dlg


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


def menu_mcp(context) -> None:
    """Tools > Plugins > AI tools > MCP server."""
    from PyQt5.QtWidgets import QMessageBox

    try:
        info = run_mcp(context)
    except Exception as e:  # noqa: BLE001
        QMessageBox.warning(_parent_window(), TITLE, f"Failed to start the MCP server:\n{e}")
        return
    if info.get("error"):
        QMessageBox.information(_parent_window(), TITLE, info["error"])
        return
    show_mcp_dialog(info, parent=_parent_window())
