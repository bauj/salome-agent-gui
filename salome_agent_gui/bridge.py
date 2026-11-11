# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import json
import time
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from salome_agent_gui import config_store, module_icons, rag_backend
from salome_agent_gui.conversation_worker import ConversationWorker, default_open
from salome_agent_gui import rag_models
from salome_agent_gui.rag_worker import IndexWorker, RagWorker
from salome_agent_gui.rag_worker import background_busy as rag_background_busy
from salome_agent_gui.timeline import RunView, reasoning_key

IMAGE_ONLY_REQUEST = "Build what the attached image(s) show."
NO_SERVER = ("No agent server. Start it from Tools > Plugins > AI tools > SALOME agent in "
             "the SALOME window, then press Reconnect in the settings.")
NO_IMAGES = "Images are only read in the Agentic assistant mode; message not sent."


def parse_images(text: str) -> list[str]:
    """The page's JSON list of data: URIs, held to the engine's --images rules
    (salome_agent.cli.check_image_uris). ValueError otherwise."""
    from salome_agent.cli import check_image_uris

    return check_image_uris(json.loads(text)) if text else []


class Bridge(QObject):
    """Owns everything the chat page shows. The page calls the slots and draws
    what `push(name, json)` sends; it never interprets engine events itself."""

    push = pyqtSignal(str, str)
    close_ready = pyqtSignal()

    def __init__(self, config_path, *, open_fn=None, probe_fn=None, edit_plan=None,
                 edit_config=None, pick_config=None, open_file=None, icon_for=None, system_dark=None,
                 clock=time.time, dialog_parent=None, rag_open_fn=None, open_url=None,
                 build_index_fn=None, download_fn=None, family=None, parent=None):
        super().__init__(parent)
        if probe_fn is None:
            from agent_server import handshake
            probe_fn = handshake.live_owner
        self.config_path = Path(config_path)
        # the SALOME menu entry that opened the window: which modes it offers
        self.family = family if family in rag_backend.FAMILY_MODES else None
        self._open_fn = open_fn or default_open
        self._probe_fn = probe_fn
        self._edit_plan = edit_plan or (lambda parent, plan: None)
        self._edit_config = edit_config or (lambda parent, path: False)
        self._pick_config = pick_config or (lambda parent, current: None)
        self._open_file = open_file or (lambda path: None)
        self._open_url = open_url or (lambda url: None)
        self._rag_open_fn = rag_open_fn
        self._build_index_fn = build_index_fn
        self._download_fn = download_fn
        self._job = ""                         # what self.indexer runs: "index" or "models"
        self._models_line = ""
        self._icon_for = icon_for or module_icons.icon_for
        self._system_dark = system_dark or (lambda: False)
        self._clock = clock
        self._dialog_parent = dialog_parent

        self.worker: ConversationWorker | RagWorker | None = None
        # the open conversation's mode; the settings' mode applies to the next one
        self._worker_mode: str | None = None
        self.indexer: IndexWorker | None = None
        self._index_line = ""
        # documentation pages and files the answers cite, which openLink may open
        self._links: set[str] = set()
        self.busy = False
        self.stopping = False
        self.degraded = False
        self.connected = False
        self.server_error = False
        self.close_pending = False
        self.page_ready = False
        self._editing = False
        self._status = {"state": "offline", "label": "Not connected", "detail": NO_SERVER}
        # ("note", text), ("user", {"text", "images"}) or ("turn", id)
        self._items: list[tuple[str, object]] = []
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

    def mode(self) -> str:
        """The open conversation's mode, else the one the settings choose."""
        return self._worker_mode or config_store.read_settings(self.config_path)["mode"]

    def allowed_modes(self) -> tuple:
        return rag_backend.modes_of(self.family)

    def doc_mode(self) -> bool:
        return self.mode() in rag_backend.DOC_MODES

    def _rag_info(self) -> dict:
        """What the settings drawer shows about the documentation index."""
        try:
            data = json.loads(self.config_path.read_text())
            chatbot = rag_backend.rag_section(data)[0]
        except (OSError, ValueError, rag_backend.RagError) as e:
            return {"configured": False, "error": str(e)}
        index = rag_backend.index_path(chatbot, self.config_path)
        return {"configured": True, "index": index,
                "index_exists": bool(index) and Path(index).exists(),
                "agentic": isinstance(chatbot.get("agentic"), dict),
                "building": self.indexer is not None, "job": self._job if self.indexer else "",
                "line": self._index_line, "models_line": self._models_line}

    def _settings(self) -> dict:
        from salome_agent.modules import llm_module_names

        s = config_store.read_settings(self.config_path)
        return {**s, "locked": self.worker is not None, "config_path": str(self.config_path),
                "module_names": llm_module_names(), "active_mode": self.mode(),
                "can_switch_mode": self.can_switch_mode(),
                "mode_order": list(self.allowed_modes()), "family": self.family,
                "mode_labels": dict(rag_backend.MODE_LABEL), "rag": self._rag_info()}

    def _theme(self) -> dict:
        theme = config_store.read_settings(self.config_path)["theme"]
        dark = theme == "dark" or (theme == "system" and bool(self._system_dark()))
        return {"theme": "dark" if dark else "light"}

    def _busy_state(self) -> dict:
        doc = self.doc_mode()
        return {"busy": self.busy, "stopping": self.stopping, "open": self.worker is not None,
                "degraded": self.degraded, "doc": doc, "mode": self.mode(),
                "can_switch_mode": self.can_switch_mode(), "modes": list(self.allowed_modes()),
                "can_send": (self.connected or doc) and not self.busy
                            and not (doc and self._doc_job_note())}

    def _doc_job_note(self) -> str:
        """Why a documentation question must wait: raglib would read the index
        or the models while the background job rewrites them."""
        if self.indexer is None:
            return ""
        if self._job == "models":
            return "The models are being downloaded: ask once the download is done."
        return "The documentation index is being built: ask once it is done."

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

    def note(self, text: str) -> None:
        self._note(text)

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
            elif kind == "user":
                items.append({"type": "user", **value})
            else:
                items.append({"type": kind, "text": value})
        self._emit("replay", {"items": items})

    def page_lost(self) -> None:
        self.page_ready = False

    def start(self) -> None:
        self._enter_family()
        self.probe()
        self._poll.start()

    def _enter_family(self) -> None:
        """Opened from a menu entry whose family does not hold the saved mode:
        save the family's first mode."""
        allowed = self.allowed_modes()
        if config_store.read_settings(self.config_path)["mode"] not in allowed:
            try:
                config_store.save_settings(self.config_path, {"mode": allowed[0]})
            except (OSError, ValueError) as e:
                self._config_error(e)

    def set_family(self, family) -> bool:
        """The SALOME menu chose another entry while the window is open. An
        Agentic assistant conversation keeps the window where it is."""
        family = family if family in rag_backend.FAMILY_MODES else None
        allowed = rag_backend.modes_of(family)
        if self.mode() not in allowed and not self.can_switch_mode():
            self._note(f"End the {rag_backend.MODE_LABEL[self.mode()]} conversation (New "
                       "conversation), then choose the menu entry again.")
            return False
        self.family = family
        if self.mode() not in allowed:
            self.setMode(allowed[0])
        else:
            self._emit("setSettings", self._settings())
            self._sync()
        return True

    # ---- server ---------------------------------------------------------
    def probe(self) -> None:
        self.server_error = False
        hs = self._probe_fn()
        self.connected = hs is not None
        settings = config_store.read_settings(self.config_path)
        if self.doc_mode():
            # the documentation modes need no agent server, only the LLM endpoint
            mode = rag_backend.MODE_LABEL[self.mode()]
            self._status = {"state": "connected", "label": f"{mode} · {settings['model'] or '?'}",
                            "detail": ""}
        elif hs:
            models, tip = config_store.model_label(settings)
            label = f"{str(hs.get('mode', '?')).upper()} :{hs.get('port', '?')} · {models}"
            self._status = {"state": "connected", "label": label, "detail": "", "title": tip}
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
        if fields.get("mode") not in self.allowed_modes():
            fields.pop("mode", None)           # the window's menu entry decides the family
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

    def can_switch_mode(self) -> bool:
        """The header's mode switch works with no conversation open, or with an
        idle documentation one (its questions carry no memory, so closing it
        loses nothing). An agent conversation must be ended first."""
        if self.busy or self.indexer is not None:
            return False
        return self.worker is None or self._worker_mode in rag_backend.DOC_MODES

    @pyqtSlot(str)
    def setMode(self, mode: str) -> None:
        """Choose the assistant from the main window: saved as gui.mode."""
        if (mode not in self.allowed_modes() or mode == self.mode()
                or not self.can_switch_mode()):
            return
        try:
            config_store.save_settings(self.config_path, {"mode": mode})
        except (OSError, ValueError) as e:
            self._config_error(e)
            return
        if self.worker is not None:            # an idle documentation conversation
            self.busy = True
            self._worker_mode = None
            self.worker.close()                # _on_worker_finished re-sends the settings
        self._note(f"{rag_backend.MODE_LABEL[mode]}: {rag_backend.MODE_HINT[mode]}")
        self._emit("setSettings", self._settings())
        self._sync()
        if not self.server_error:
            self.probe()

    @pyqtSlot()
    def editConfigJson(self) -> None:
        if self._edit_config(self._dialog_parent, self.config_path):
            self._enter_family()
            self._emit("setSettings", self._settings())
            self._emit("setTheme", self._theme())
            self._sync()
            if not self.server_error:
                self.probe()

    @pyqtSlot()
    def loadConfig(self) -> None:
        """Switch to another config file; refused while a conversation is open
        (the engine got its config when the conversation started)."""
        if self.worker is not None:
            return
        path = self._pick_config(self._dialog_parent, self.config_path)
        if not path:
            return
        path = Path(path)
        try:
            config_store.load(path)
        except Exception as e:  # noqa: BLE001
            self._status = {"state": "error", "label": "Config error",
                            "detail": f"{path}: {e}"}
            self._emit("setStatus", self._status)
            return
        self.config_path = path
        self._enter_family()
        try:
            config_store.remember_config(path)
        except OSError as e:
            self._note(f"Could not remember {path} for the next start: {e}")
        self._emit("setSettings", self._settings())
        self._emit("setTheme", self._theme())
        self.probe()

    # ---- conversation ---------------------------------------------------
    def _config_error(self, e: Exception) -> bool:
        self._status = {"state": "error", "label": "Config error", "detail": str(e)}
        self._emit("setStatus", self._status)
        return False

    def _start_conversation(self) -> bool:
        s = config_store.read_settings(self.config_path)
        try:
            config = config_store.load(self.config_path)
        except Exception as e:  # noqa: BLE001
            return self._config_error(e)
        if s["mode"] in rag_backend.DOC_MODES:
            try:
                chatbot = rag_backend.resolve_chatbot(config, self.config_path)
            except rag_backend.RagError as e:
                return self._config_error(e)
            # raglib loads its models offline: say which are missing before it fails
            absent = rag_models.missing(config)
            if absent:
                names = ", ".join(f"{role} model {model}" for role, _, model in absent)
                return self._config_error(rag_backend.RagError(
                    f"not installed: {names}. Download it in the settings (Models)."))
            kw = {"open_fn": self._rag_open_fn} if self._rag_open_fn else {}
            worker = RagWorker(chatbot, agentic=s["mode"] == "rag_agentic", parent=self, **kw)
        else:
            config.setdefault("policy", {})
            config["policy"]["on_stage_failure"] = s["on_stage_failure"]
            config["policy"]["tool_selection"] = s["tool_selection"]
            worker = ConversationWorker(config, batch=s["batch"], verbose=s["verbose"],
                                        open_fn=self._open_fn, parent=self)
        self._worker_mode = s["mode"]
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

    @pyqtSlot(str, str)
    def send(self, text: str, images_json: str = "") -> None:
        """`images_json`: a JSON list of data: URIs attached to the message."""
        text = (text or "").strip()
        doc = self.doc_mode()
        if self.busy or not (self.connected or doc):
            return
        try:
            images = parse_images(images_json)
        except ValueError as e:
            self._note(f"Message not sent: {e}")
            return
        if doc and images:
            self._note(NO_IMAGES)
            return
        if doc and self._doc_job_note():
            self._note(self._doc_job_note())
            return
        if not text and not images:
            return
        if self.worker is None and not self._start_conversation():
            return
        user = {"text": text, "images": images} if images else {"text": text}
        self._items.append(("user", user))
        self._emit("addUser", user)
        turn_id = self._next_turn
        self._next_turn += 1
        self._turns[turn_id] = RunView(clock=self._clock, usage_base=self._usage_base,
                                         batch=self._batch, started_at=self._clock())
        self._items.append(("turn", turn_id))
        self._current = turn_id
        self._render()
        self.busy = True
        self.stopping = False
        self.worker.submit(text or IMAGE_ONLY_REQUEST, images)
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
        if ev.get("kind") == "rag_answer":
            for src in (ev.get("data") or {}).get("sources") or []:
                self._links.update(x for x in (src.get("url"), src.get("path")) if x)
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
        if self._worker_mode in rag_backend.DOC_MODES:
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
        self._worker_mode = None
        self.busy = False
        self.stopping = False
        self.degraded = False
        self._emit("setSettings", self._settings())
        self._sync()
        if not self.close_pending and not self.server_error:
            self.probe()
        if self.close_pending and self.indexer is None:
            self.close_ready.emit()

    # ---- files and closing ----------------------------------------------
    @pyqtSlot(str)
    def openFile(self, path: str) -> None:
        if path in self._files:
            self._open_file(path)

    @pyqtSlot(str)
    def openLink(self, target: str) -> None:
        """A page an answer cites (web URL or local file), or a web link in an
        answer's text; nothing else."""
        if target in self._links and not target.startswith(("http://", "https://")):
            self._open_file(target)
        elif target.startswith(("http://", "https://")):
            self._open_url(target)

    # ---- documentation index --------------------------------------------
    @pyqtSlot()
    def buildIndex(self) -> None:
        """raglib's extraction on the config's rag.extraction; refused while a
        documentation conversation holds the index open."""
        if self.indexer is not None:
            return
        if self.worker is not None and self._worker_mode in rag_backend.DOC_MODES:
            self._note("Close the documentation conversation (New conversation) "
                       "before rebuilding its index.")
            return
        if rag_background_busy():
            self._note("A stopped documentation question is still being answered: "
                       "rebuild the index once it is done.")
            return
        self._start_job("index", IndexWorker(self.config_path, build_fn=self._build_index_fn,
                                             parent=self))
        self._note("Building the documentation index; this can take a while.")

    def _start_job(self, job: str, worker) -> None:
        worker.line.connect(self._on_index_line)
        worker.done.connect(self._on_index_done)
        worker.finished.connect(lambda w=worker: self._on_indexer_finished(w))
        self.indexer = worker
        self._job = job
        self._set_job_line("starting…")
        worker.start()
        self._emit("setSettings", self._settings())
        self._sync()

    @pyqtSlot(str)
    def downloadModels(self, role: str) -> None:
        """Fetch the configured `embedding` or `reranker` model, or `all` missing
        ones, into the Hugging Face cache (raglib's download_models.py)."""
        if self.indexer is not None or role not in ("embedding", "reranker", "all"):
            return
        try:
            data = json.loads(self.config_path.read_text())
        except (OSError, ValueError) as e:
            self._config_error(e)
            return
        roles = ("embedding", "reranker") if role == "all" else (role,)
        # "all": what the next question needs; one model: even a reranker switched off
        items = rag_models.missing(data, roles, only_enabled=role == "all")
        if not items:
            self._note("The models are already installed.")
            self._emit("setSettings", self._settings())
            return
        download = self._download_fn or rag_models.download

        def run(_path, on_line, cancel):
            return download(items, on_line=on_line, cancel=cancel)

        self._start_job("models", IndexWorker(self.config_path, build_fn=run, parent=self))
        self._note("Downloading " + ", ".join(m for _, _, m in items) + " into the Hugging Face cache.")

    def _set_job_line(self, text: str) -> None:
        if self._job == "models":
            self._models_line = text
        else:
            self._index_line = text

    def _on_index_line(self, text: str) -> None:
        self._set_job_line(text)
        self._emit("setIndex", {"building": True, "job": self._job, "line": text})

    def _on_index_done(self, code: int, tail: str) -> None:
        if self._job == "models":
            self._models_line = "" if code == 0 else f"download failed (exit {code})"
            self._note("Models downloaded." if code == 0
                       else f"Downloading the models failed (exit {code}):\n{tail}")
            return
        if code == 0:
            self._index_line = "index built"
            self._note("Documentation index built.")
        else:
            self._index_line = f"failed (exit {code})"
            self._note(f"Building the documentation index failed (exit {code}):\n{tail}")

    def _on_indexer_finished(self, worker) -> None:
        if worker is not self.indexer:
            return
        worker.wait()
        self.indexer = None
        self._job = ""
        self._emit("setSettings", self._settings())
        self._sync()
        if self.close_pending and self.worker is None:
            self.close_ready.emit()

    def request_close(self) -> bool:
        """True: nothing is running, close now. False: the workers were asked to
        stop; `close_ready` fires once they have."""
        if self.worker is None and self.indexer is None:
            return True
        if not self.close_pending:
            self.close_pending = True
            self.stopping = True
            if self.worker is not None:
                self.worker.close()
            if self.indexer is not None:
                self.indexer.cancel.set()
            self._sync()
        return False
