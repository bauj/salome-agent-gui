# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import queue
import threading
import time
import uuid

from PyQt5.QtCore import QThread, pyqtSignal


def default_open(chatbot: dict, *, agentic: bool):
    from salome_agent_gui import rag_backend

    return rag_backend.open_session(chatbot, agentic=agentic)


class RagWorker(QThread):
    """The documentation modes behind ConversationWorker's interface, so the bridge
    drives both alike. Each question is answered on its own from raglib (no
    conversation memory); there is no plan, gate, undo or study to rebuild.

    raglib cannot be interrupted: Stop ends the turn at once and the answer still
    being computed is dropped when it arrives."""

    event = pyqtSignal(dict)
    gate = pyqtSignal(dict)                     # never emitted; the bridge connects it
    turn_done = pyqtSignal(dict)

    def __init__(self, chatbot: dict, *, agentic: bool, open_fn=default_open, parent=None):
        super().__init__(parent)
        self.chatbot = chatbot
        self.agentic = agentic
        self.run_id = uuid.uuid4().hex[:12]
        self.cancel = threading.Event()
        self._open_fn = open_fn
        self._queue: queue.Queue = queue.Queue()
        self._session = None

    # ---- called from the GUI thread ------------------------------------
    def submit(self, text: str, images: list[str] | None = None) -> None:
        self.cancel.clear()
        self._queue.put(("turn", text))

    def undo(self) -> None:
        self._queue.put(("undo", None))

    def redo(self) -> None:
        self._queue.put(("redo", None))

    def rebuild(self) -> None:
        self._queue.put(("rebuild", None))

    def stop(self) -> None:
        self.cancel.set()

    def close(self) -> None:
        self.stop()
        self._queue.put(None)

    def gate_pending(self) -> bool:
        return False

    def answer_gate(self, decision) -> None:
        pass

    # ---- worker thread -------------------------------------------------
    def _ev(self, kind: str, **data) -> None:
        self.event.emit({"kind": kind, "run_id": self.run_id, "data": data})

    def _done(self, command: str, status: str, message: str) -> None:
        if command == "turn":                   # stops the turn's clock, like the engine's
            self._ev("turn_done", status=status, message=message)
        self.turn_done.emit({"command": command, "status": status, "message": message,
                             "degraded": False, "ended": False})

    def _in_background(self, fn):
        """fn() on a daemon thread; (True, result) or (False, None) once Stop is
        pressed. Exceptions are re-raised here."""
        box = {}
        done = threading.Event()

        def target():
            try:
                box["value"] = fn()
            except BaseException as e:  # noqa: BLE001
                box["error"] = e
            done.set()

        threading.Thread(target=target, daemon=True, name="rag-ask").start()
        while not done.wait(0.05):
            if self.cancel.is_set():
                return False, None
        if "error" in box:
            raise box["error"]
        return True, box.get("value")

    def _stopped(self) -> None:
        self._ev("aborted")
        self._done("turn", "aborted", "stopped")

    def run(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            command, text = item
            if command != "turn":
                self._done(command, "failed", "not available in the documentation modes")
                continue
            started = time.time()
            try:
                if self._session is None:
                    self._ev("rag_status", phase="loading", agentic=self.agentic)
                    finished, session = self._in_background(
                        lambda: self._open_fn(self.chatbot, agentic=self.agentic))
                    if not finished:
                        self._stopped()
                        continue
                    self._session = session
                self._ev("rag_status", phase="searching", agentic=self.agentic)
                finished, result = self._in_background(lambda: self._session.ask(text))
                if not finished:
                    self._stopped()
                    continue
            except Exception as e:  # noqa: BLE001
                message = f"{type(e).__name__}: {e}"
                self._ev("fatal", message=message)
                self._done("turn", "failed", message)
                continue
            result = result if isinstance(result, dict) else {}
            if result.get("error"):
                message = str(result["error"])
                self._ev("fatal", message=message)
                self._done("turn", "failed", message)
                continue
            filters = result.get("filters") if isinstance(result.get("filters"), dict) else {}
            from salome_agent_gui.rag_backend import sources_view

            self._ev("rag_answer", answer=str(result.get("answer") or ""),
                     sources=sources_view(result.get("sources")),
                     usage=filters.get("token_usage") or None,
                     degraded=bool(filters.get("degraded_answer")),
                     steps=filters.get("steps_used"), seconds=round(time.time() - started, 1))
            self._done("turn", "ok", "")


class IndexWorker(QThread):
    """Builds the documentation index (raglib's extraction) off the GUI thread."""

    line = pyqtSignal(str)
    done = pyqtSignal(int, str)                  # exit code, last lines or the error

    def __init__(self, config_path, *, build_fn=None, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.cancel = threading.Event()
        self._build_fn = build_fn

    def run(self):
        from salome_agent_gui import rag_backend

        build = self._build_fn or rag_backend.build_index
        tail: list[str] = []

        def on_line(text):
            if text.strip():
                tail.append(text)
                del tail[:-8]
                self.line.emit(text)

        try:
            code = build(self.config_path, on_line=on_line, cancel=self.cancel)
        except Exception as e:  # noqa: BLE001
            self.done.emit(1, f"{type(e).__name__}: {e}")
            return
        self.done.emit(code, "\n".join(tail))
