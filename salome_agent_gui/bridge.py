import json
import time
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from salome_agent_gui import config_store, module_icons
from salome_agent_gui.conversation_worker import ConversationWorker, default_open
from salome_agent_gui.timeline import RunView, reasoning_key

NO_SERVER = ("No agent server. Start it from Tools > Plugins > SALOME Agent in the SALOME "
             "window, then press Reconnect in the settings.")


class Bridge(QObject):
    """Owns everything the chat page shows. The page calls the slots and draws
    what `push(name, json)` sends; it never interprets engine events itself."""

    push = pyqtSignal(str, str)
    close_ready = pyqtSignal()

    def __init__(self, config_path, *, open_fn=None, probe_fn=None, edit_plan=None,
                 edit_config=None, open_file=None, icon_for=None, system_dark=None,
                 clock=time.time, dialog_parent=None, parent=None):
        super().__init__(parent)
        if probe_fn is None:
            from agent_server import handshake
            probe_fn = handshake.live_owner
        self.config_path = Path(config_path)
        self._open_fn = open_fn or default_open
        self._probe_fn = probe_fn
        self._edit_plan = edit_plan or (lambda parent, plan: None)
        self._edit_config = edit_config or (lambda parent, path: False)
        self._open_file = open_file or (lambda path: None)
        self._icon_for = icon_for or module_icons.icon_for
        self._system_dark = system_dark or (lambda: False)
        self._clock = clock
        self._dialog_parent = dialog_parent

        self.worker: ConversationWorker | None = None
        self.busy = False
        self.stopping = False
        self.degraded = False
        self.connected = False
        self.server_error = False
        self.close_pending = False
        self.page_ready = False
        self._editing = False
        self._status = {"state": "offline", "label": "Not connected", "detail": NO_SERVER}
        self._items: list[tuple[str, object]] = []   # ("user"|"note", text) or ("turn", id)
        self._turns: dict[int, RunView] = {}
        self._current: int | None = None
        self._next_turn = 0
        self._next_gate = 0
        self._usage_base: dict | None = None
        self._batch = False
        self._icons: dict[str, str | None] = {}
        self._files: set[str] = set()
        self._polls = 0
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._poll_tick)

    # ---- output ---------------------------------------------------------
    def _emit(self, name: str, payload) -> None:
        if self.page_ready:
            self.push.emit(name, json.dumps(payload))

    def _settings(self) -> dict:
        s = config_store.read_settings(self.config_path)
        return {**s, "locked": self.worker is not None, "config_path": str(self.config_path)}

    def _theme(self) -> dict:
        theme = config_store.read_settings(self.config_path)["theme"]
        dark = theme == "dark" or (theme == "system" and bool(self._system_dark()))
        return {"theme": "dark" if dark else "light"}

    def _busy_state(self) -> dict:
        return {"busy": self.busy, "stopping": self.stopping, "open": self.worker is not None,
                "degraded": self.degraded, "can_send": self.connected and not self.busy}

    def _icon(self, module: str):
        if module not in self._icons:
            self._icons[module] = self._icon_for(module)
        return self._icons[module]

    def _vm(self, turn_id: int) -> dict:
        return self._turns[turn_id].to_view_model(turn_id, self._icon)

    def _sync(self) -> None:
        self._emit("setBusy", self._busy_state())

    def _render(self) -> None:
        if self._current is not None:
            self._emit("renderTurn", self._vm(self._current))

    def _note(self, text: str) -> None:
        self._items.append(("note", text))
        self._emit("addNote", {"text": text})

    # ---- page lifecycle -------------------------------------------------
    @pyqtSlot()
    def ready(self) -> None:
        self.page_ready = True
        self._emit("setSettings", self._settings())
        self._emit("setTheme", self._theme())
        self._emit("setStatus", self._status)
        self._emit("setBusy", self._busy_state())
        items = []
        for kind, value in self._items:
            if kind == "turn":
                items.append({"type": "turn", "vm": self._vm(value)})
            else:
                items.append({"type": kind, "text": value})
        self._emit("replay", {"items": items})

    def page_lost(self) -> None:
        self.page_ready = False

    def start(self) -> None:
        self.probe()
        self._poll.start()

    # ---- server ---------------------------------------------------------
    def probe(self) -> None:
        self.server_error = False
        hs = self._probe_fn()
        self.connected = hs is not None
        if hs:
            model = config_store.read_settings(self.config_path)["model"] or "?"
            label = f"{str(hs.get('mode', '?')).upper()} :{hs.get('port', '?')} · {model}"
            self._status = {"state": "connected", "label": label, "detail": ""}
        else:
            self._status = {"state": "offline", "label": "Not connected", "detail": NO_SERVER}
        self._emit("setStatus", self._status)
        self._sync()

    def _poll_tick(self) -> None:
        self._polls += 1
        if self.connected or self._polls >= 10 or self.server_error:
            self._poll.stop()
            return
        self.probe()

    @pyqtSlot()
    def reconnect(self) -> None:
        self._polls = 0
        self.probe()

    # ---- settings -------------------------------------------------------
    @pyqtSlot(str)
    def saveSettings(self, text: str) -> None:
        try:
            fields = json.loads(text)
        except ValueError:
            return
        if not isinstance(fields, dict):
            return
        try:
            config_store.save_settings(self.config_path, fields, run_options=self.worker is None)
        except (OSError, ValueError) as e:
            self._status = {"state": "error", "label": "Config error", "detail": str(e)}
            self._emit("setStatus", self._status)
            return
        self._emit("setSettings", self._settings())
        self._emit("setTheme", self._theme())
        if not self.server_error:
            self.probe()

    @pyqtSlot()
    def editConfigJson(self) -> None:
        if self._edit_config(self._dialog_parent, self.config_path):
            self._emit("setSettings", self._settings())
            self._emit("setTheme", self._theme())

    # ---- conversation ---------------------------------------------------
    def _start_conversation(self) -> bool:
        s = config_store.read_settings(self.config_path)
        try:
            config = config_store.load(self.config_path)
        except Exception as e:  # noqa: BLE001
            self._status = {"state": "error", "label": "Config error", "detail": str(e)}
            self._emit("setStatus", self._status)
            return False
        config.setdefault("policy", {})
        config["policy"]["on_stage_failure"] = s["on_stage_failure"]
        config["policy"]["tool_selection"] = s["tool_selection"]
        worker = ConversationWorker(config, batch=s["batch"], verbose=s["verbose"],
                                    open_fn=self._open_fn, parent=self)
        worker.event.connect(self._on_event)
        worker.gate.connect(self._on_gate)
        worker.turn_done.connect(self._on_turn_done)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self.worker = worker
        self._batch = s["batch"]
        self.degraded = False
        self._usage_base = None
        worker.start()
        self._emit("setSettings", self._settings())
        return True

    @pyqtSlot(str)
    def send(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self.busy or not self.connected:
            return
        if self.worker is None and not self._start_conversation():
            return
        self._items.append(("user", text))
        self._emit("addUser", {"text": text})
        turn_id = self._next_turn
        self._next_turn += 1
        self._turns[turn_id] = RunView(clock=self._clock, usage_base=self._usage_base,
                                         batch=self._batch)
        self._items.append(("turn", turn_id))
        self._current = turn_id
        self._render()
        self.busy = True
        self.stopping = False
        self.worker.submit(text)
        self._sync()

    def _on_event(self, ev: dict) -> None:
        view = self._turns.get(self._current)
        if view is None:
            return
        view.apply(ev)
        if ev.get("kind") == "reasoning":
            # streamed many times a second: append in place, no full re-render
            d = ev.get("data") or {}
            self._emit("appendReasoning", {"turn": self._current, "key": reasoning_key(d),
                                           "call": d.get("call"), "channel": d.get("channel"),
                                           "text": d.get("text")})
            return
        for path in (view.result_py, view.report_md):
            if path:
                self._files.add(path)
        self._render()
        if ev.get("kind") == "fatal":
            message = (ev.get("data") or {}).get("message", "")
            if message.startswith("ServerUnavailable"):
                self.connected = False
                self.server_error = True
                self._status = {"state": "error", "label": "Server error", "detail": message}
                self._emit("setStatus", self._status)
                self._sync()

    def _on_gate(self, payload: dict) -> None:
        view = self._turns.get(self._current)
        if view is None:
            return
        self._next_gate += 1
        view.gate, view.gate_id = payload, self._next_gate
        self._render()

    @pyqtSlot(int, str, str)
    def gate(self, gate_id: int, action: str, text: str) -> None:
        view = self._turns.get(self._current)
        if self.worker is None or view is None or view.gate is None or view.gate_id != gate_id:
            return
        if action == "edit":
            if self._editing:
                return
            self._editing = True
            try:
                plan = self._edit_plan(self._dialog_parent, view.gate.get("plan") or [])
            finally:
                self._editing = False
            # the dialog ran a nested event loop: the gate may be gone by now
            if self.worker is None or view.gate is None or view.gate_id != gate_id:
                return
            if plan is None:
                self._render()
                return
            decision = {"action": "edit", "plan": plan}
        elif action == "hint":
            hint = (text or "").strip()
            if not hint:
                return
            decision = {"action": "hint", "hint": hint}
        elif action in ("approve", "skip", "abort"):
            decision = {"action": action}
        else:
            return
        view.gate, view.gate_id = None, None
        if action != "abort":
            view.mark_resumed()
        self._render()
        self.worker.answer_gate(decision)

    @pyqtSlot(str)
    def command(self, name: str) -> None:
        if name == "new":
            self._new_conversation()
            return
        if name not in ("undo", "redo", "rebuild") or self.worker is None or self.busy:
            return
        if name == "rebuild" and not self.degraded:
            return
        self.busy = True
        getattr(self.worker, name)()
        self._sync()

    def _new_conversation(self) -> None:
        if self.worker is None or self.busy:
            return
        self.busy = True
        self.worker.close()
        self._note("New conversation: the next message starts a fresh model.")
        self._sync()

    @pyqtSlot()
    def stop(self) -> None:
        if self.worker is not None and self.busy:
            self.stopping = True
            self.worker.stop()
            self._sync()

    def _on_turn_done(self, payload: dict) -> None:
        self.busy = False
        self.stopping = False
        self.degraded = bool(payload.get("degraded"))
        command = payload.get("command")
        if command != "turn":
            failed = " failed" if payload.get("status") == "failed" else ""
            self._note(f"{command}{failed}: {payload.get('message', '')}")
        else:
            view = self._turns.get(self._current)
            if view is not None:
                if view.turn_status is None:
                    view.turn_status = payload.get("status")
                    view.turn_message = payload.get("message")
                view.gate, view.gate_id = None, None
                view.finished = True
                if view.usage:
                    self._usage_base = dict(view.usage)
                self._render()
        if payload.get("ended"):
            self.busy = True
            self._note("The conversation has ended; the next message starts a new conversation.")
        self._sync()
        if not self.close_pending and not self.server_error:
            self.probe()

    def _on_worker_finished(self, worker) -> None:
        if worker is not self.worker:
            return
        worker.wait()
        self.worker = None
        self.busy = False
        self.stopping = False
        self.degraded = False
        self._emit("setSettings", self._settings())
        self._sync()
        if self.close_pending:
            self.close_ready.emit()

    # ---- files and closing ----------------------------------------------
    @pyqtSlot(str)
    def openFile(self, path: str) -> None:
        if path in self._files:
            self._open_file(path)

    def request_close(self) -> bool:
        """True: nothing is running, close now. False: the worker was asked to
        stop; `close_ready` fires once it has."""
        if self.worker is None:
            return True
        if not self.close_pending:
            self.close_pending = True
            self.stopping = True
            self.worker.close()
            self._sync()
        return False
