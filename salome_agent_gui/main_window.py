import json
import os
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout,
                             QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
                             QSpinBox, QSplitter, QVBoxLayout, QWidget)

from salome_agent_gui import config_store, dialogs
from salome_agent_gui.chat_view import ChatView
from salome_agent_gui.conversation_worker import ConversationWorker, default_open

HELP = ("The first message starts a conversation: the planner proposes stages, you approve, "
        "edit or abort, and each stage is built in this SALOME session. Follow-up messages "
        "change that model (\"make the roof taller\", \"add a chimney\"). Undo and Redo step "
        "through turns; Rebuild recreates the study from the model when they got out of sync; "
        "New conversation starts over. While a conversation is open it keeps the agent "
        "server to itself. result.py and report.md are linked after each turn.")
NO_SERVER = "No agent server. Start it from Tools > Plugins > SALOME Agent."


class HistoryLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: list[str] = []
        self._pos = 0

    def remember(self, text: str) -> None:
        self._history.append(text)
        self._pos = len(self._history)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Up and self._history:
            self._pos = max(0, self._pos - 1)
            self.setText(self._history[self._pos])
        elif e.key() == Qt.Key_Down and self._history:
            self._pos = min(len(self._history), self._pos + 1)
            self.setText(self._history[self._pos] if self._pos < len(self._history) else "")
        else:
            super().keyPressEvent(e)


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path, *, open_fn=None, probe_fn=None,
                 ask_hint=None, edit_plan=None, parent_pid: int | None = None):
        super().__init__()
        from agent_server import handshake

        self.config_path = Path(config_path)
        self._open_fn = open_fn or default_open
        self._probe_fn = probe_fn or handshake.live_owner
        self._ask_hint = ask_hint or dialogs.ask_hint
        self._edit_plan = edit_plan or dialogs.edit_plan
        self.worker: ConversationWorker | None = None
        self._busy = False
        self._degraded = False
        self._view = None
        self._connected = False
        self._close_pending = False
        self._server_error = False
        self.setWindowTitle("SALOME Agent")
        self.resize(1200, 780)
        self._build()
        self._load_key_fields()
        self._polls = 0
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._poll_tick)
        self._poll.start()
        self.probe()

        if parent_pid is None:
            try:
                parent_pid = int(os.environ["SALOME_AGENT_GUI_PARENT_PID"])
            except (KeyError, ValueError):
                parent_pid = None
        self._parent_pid = parent_pid
        self._parent_watch = None
        if self._parent_pid is not None:
            self._parent_watch = QTimer(self)
            self._parent_watch.setInterval(2000)
            self._parent_watch.timeout.connect(self._check_parent)
            self._parent_watch.start()

    # ---- layout ---------------------------------------------------------
    def _build(self):
        conn = QGroupBox("Connection")
        form = QFormLayout(conn)
        path_lbl = QLabel(str(self.config_path))
        path_lbl.setWordWrap(True)
        form.addRow("Config:", path_lbl)
        edit_cfg = QPushButton("Edit configuration…")
        edit_cfg.clicked.connect(self._edit_config)
        form.addRow("", edit_cfg)
        self.base_url, self.model, self.api_key = QLineEdit(), QLineEdit(), QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        for label, w in (("LLM base URL:", self.base_url), ("Model:", self.model),
                         ("API key:", self.api_key)):
            w.editingFinished.connect(self._save_key_fields)
            form.addRow(label, w)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        form.addRow("Server:", self.status)
        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self.probe)
        form.addRow("", connect_btn)

        opts = QGroupBox("Run options")
        of = QFormLayout(opts)
        self.batch = QCheckBox("Batch (no approval gates)")
        self.on_failure = QComboBox()
        self.on_failure.addItems(["abort", "continue"])
        self.tools = QComboBox()
        self.tools.addItems(["hints", "all"])
        self.verbose = QSpinBox()
        self.verbose.setRange(0, 2)
        of.addRow("", self.batch)
        of.addRow("On stage failure:", self.on_failure)
        of.addRow("Tool selection:", self.tools)
        of.addRow("Verbosity:", self.verbose)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(conn)
        ll.addWidget(opts)
        ll.addStretch(1)

        self.chat = ChatView()
        self.chat.gate_clicked.connect(self._on_gate_clicked)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.chat)
        split.setStretchFactor(1, 1)

        self.input = HistoryLineEdit()
        self.input.setPlaceholderText("Describe what to build, then ask for changes…")
        self.input.returnPressed.connect(self.send)
        self.send_btn, self.stop_btn = QPushButton("Send"), QPushButton("Stop")
        self.send_btn.clicked.connect(self.send)
        self.stop_btn.clicked.connect(self._stop)
        self.undo_btn, self.redo_btn = QPushButton("Undo"), QPushButton("Redo")
        self.rebuild_btn, self.new_btn = QPushButton("Rebuild"), QPushButton("New conversation")
        self.undo_btn.clicked.connect(lambda: self._command("undo"))
        self.redo_btn.clicked.connect(lambda: self._command("redo"))
        self.rebuild_btn.clicked.connect(lambda: self._command("rebuild"))
        self.new_btn.clicked.connect(self._new_conversation)
        help_btn, quit_btn = QPushButton("Help"), QPushButton("Quit")
        help_btn.clicked.connect(lambda: QMessageBox.information(self, "SALOME Agent", HELP))
        quit_btn.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        for b in (self.send_btn, self.stop_btn, self.undo_btn, self.redo_btn,
                  self.rebuild_btn, self.new_btn, help_btn, quit_btn):
            row.addWidget(b)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.addWidget(split, 1)
        cl.addLayout(row)
        self.setCentralWidget(central)
        self._sync_buttons()

    # ---- config ---------------------------------------------------------
    def _load_key_fields(self):
        f = config_store.read_key_fields(self.config_path)
        self.base_url.setText(f["base_url"])
        self.model.setText(f["model"])
        self.api_key.setText(f["api_key"])
        policy = json.loads(self.config_path.read_text()).get("policy", {})
        on_failure = policy.get("on_stage_failure")
        if on_failure in [self.on_failure.itemText(i) for i in range(self.on_failure.count())]:
            self.on_failure.setCurrentText(on_failure)
        tools = policy.get("tool_selection")
        if tools in [self.tools.itemText(i) for i in range(self.tools.count())]:
            self.tools.setCurrentText(tools)

    def _save_key_fields(self):
        config_store.save_key_fields(self.config_path, {
            "base_url": self.base_url.text().strip(), "model": self.model.text().strip(),
            "api_key": self.api_key.text()})

    def _edit_config(self):
        if dialogs.edit_config(self, self.config_path):
            self._load_key_fields()

    # ---- server ---------------------------------------------------------
    def probe(self):
        self._server_error = False
        hs = self._probe_fn()
        self._connected = hs is not None
        self.status.setText(f"{hs.get('mode', '?')} server on port {hs.get('port', '?')}"
                            if hs else NO_SERVER)
        self._sync_buttons()

    def _poll_tick(self):
        self._polls += 1
        if self._connected or self._polls >= 10 or self._server_error:
            self._poll.stop()
            return
        self.probe()

    def _check_parent(self):
        try:
            os.kill(self._parent_pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            return
        else:
            return
        self._parent_watch.stop()
        self.status.setText("SALOME has exited — closing")
        if self.worker is not None:
            self.worker.close()
        self.close()

    # ---- conversation ---------------------------------------------------
    def _sync_buttons(self):
        open_, busy = self.worker is not None, self._busy
        self.send_btn.setEnabled(self._connected and not busy)
        self.stop_btn.setEnabled(busy)
        for b in (self.undo_btn, self.redo_btn, self.new_btn):
            b.setEnabled(open_ and not busy)
        self.rebuild_btn.setEnabled(open_ and not busy and self._degraded)
        for w in (self.batch, self.on_failure, self.tools, self.verbose):
            w.setEnabled(not open_)

    def _start_conversation(self) -> bool:
        self._save_key_fields()
        try:
            config = config_store.load(self.config_path)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Config error: {e}")
            return False
        config.setdefault("policy", {})
        config["policy"]["on_stage_failure"] = self.on_failure.currentText()
        config["policy"]["tool_selection"] = self.tools.currentText()
        worker = ConversationWorker(config, batch=self.batch.isChecked(),
                                    verbose=self.verbose.value(), open_fn=self._open_fn,
                                    parent=self)
        worker.event.connect(self._on_event)
        worker.gate.connect(self._on_gate)
        worker.turn_done.connect(self._on_turn_done)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self.worker = worker
        self._degraded = False
        worker.start()
        return True

    def send(self):
        text = self.input.text().strip()
        if not text or self._busy or not self._connected:
            return
        if self.worker is None and not self._start_conversation():
            return
        self.input.remember(text)
        self.input.clear()
        self.chat.add_user(text)
        self._view = self.chat.add_run()
        self._busy = True
        self.worker.submit(text)
        self._sync_buttons()

    def _command(self, name: str):
        if self.worker is None or self._busy:
            return
        self._busy = True
        getattr(self.worker, name)()
        self._sync_buttons()

    def _new_conversation(self):
        if self.worker is None or self._busy:
            return
        self._busy = True
        self.worker.close()
        self.chat.add_note("New conversation: the next message starts a fresh model.")
        self._sync_buttons()

    def _on_event(self, ev: dict):
        if self._view is None:
            return
        self._view.apply(ev)
        self.chat.refresh()
        if ev.get("kind") == "fatal":
            message = ev.get("data", {}).get("message", "")
            if message.startswith("ServerUnavailable"):
                self._connected = False
                self._server_error = True
                self.status.setText(message)
                self._sync_buttons()

    def _on_gate(self, payload: dict):
        self._view.gate = payload
        self.chat.refresh()

    def _on_gate_clicked(self, action: str):
        if self.worker is None or not self._view or not self._view.gate:
            return
        payload = self._view.gate
        if action == "edit":
            plan = self._edit_plan(self, payload.get("plan") or [])
            if plan is None:
                return
            decision = {"action": "edit", "plan": plan}
        elif action == "hint":
            hint = self._ask_hint(self)
            if not hint:
                return
            decision = {"action": "hint", "hint": hint}
        elif action in ("approve", "skip", "abort"):
            decision = {"action": action}
        else:
            return
        self._view.gate = None
        self.chat.refresh()
        self.worker.answer_gate(decision)

    def _stop(self):
        if self.worker is not None and self._busy:
            self.status.setText("Stopping the current turn…")
            self.worker.stop()

    def _on_turn_done(self, payload: dict):
        self._busy = False
        self._degraded = bool(payload.get("degraded"))
        command = payload.get("command")
        if command != "turn":
            self.chat.add_note(f"{command}: {payload.get('message', '')}")
        elif self._view is not None:
            if self._view.turn_status is None:
                self._view.turn_status = payload.get("status")
                self._view.turn_message = payload.get("message")
            self._view.gate = None
            self._view.finished = True
        if payload.get("ended"):
            self._busy = True
            self.chat.add_note("The conversation has ended; the next message starts a new "
                               "conversation.")
        self.chat.refresh()
        self._sync_buttons()
        if not self._close_pending and not self._server_error:
            self.probe()

    def _on_worker_finished(self, worker):
        if worker is not self.worker:
            return
        worker.wait(2000)
        self.worker = None
        self._busy = False
        self._degraded = False
        self._sync_buttons()
        if self._close_pending:
            self.close()

    def closeEvent(self, e):
        if self.worker is not None:
            self.worker.close()
            if not self.worker.wait(3000):
                self._close_pending = True
                self.status.setText("Stopping the current turn…")
                e.ignore()
                return
        super().closeEvent(e)
