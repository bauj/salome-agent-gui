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
    being computed is dropped when it arrives; the next question waits for it."""

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
        self._opening: _Job | None = None
        self._asking: _Job | None = None

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

    def _wait(self, job: "_Job") -> bool:
        """True once job is done, False as soon as Stop is pressed."""
        while not job.done.wait(0.05):
            if self.cancel.is_set():
                return False
        return True

    def _stopped(self) -> None:
        self._ev("aborted")
        self._done("turn", "aborted", "stopped")

    def _answer(self, text: str):
        """(True, result) or (False, None) on Stop. raglib's session is not
        thread-safe: a question stopped earlier is waited for, never overlapped,
        and a stopped load is kept for the next question, not started again."""
        if self._asking is not None:
            if not self._asking.done.is_set():
                self._ev("rag_status", phase="waiting", agentic=self.agentic)
                if not self._wait(self._asking):
                    return False, None
            self._asking = None
        if self._session is None:
            self._ev("rag_status", phase="loading", agentic=self.agentic)
            if self._opening is None:
                chatbot, agentic, open_fn = self.chatbot, self.agentic, self._open_fn
                self._opening = _Job(lambda: open_fn(chatbot, agentic=agentic))
            if not self._wait(self._opening):
                return False, None
            job, self._opening = self._opening, None
            self._session = job.result()
        self._ev("rag_status", phase="searching", agentic=self.agentic)
        session = self._session
        self._asking = _Job(lambda: session.ask(text))
        if not self._wait(self._asking):
            return False, None
        job, self._asking = self._asking, None
        return True, job.result()

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
                finished, result = self._answer(text)
            except Exception as e:  # noqa: BLE001
                message = f"{type(e).__name__}: {e}"
                self._ev("fatal", message=message)
                self._done("turn", "failed", message)
                continue
            if not finished:
                self._stopped()
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


_running: set = set()
_running_lock = threading.Lock()


def background_busy() -> bool:
    """A raglib call is still running, maybe one whose answer was dropped by
    Stop: the index must not be rebuilt under it."""
    with _running_lock:
        return bool(_running)


class _Job:
    """fn() on a daemon thread (raglib cannot be interrupted)."""

    def __init__(self, fn):
        self.done = threading.Event()
        self._value = self._error = None
        thread = threading.Thread(target=self._run, args=(fn,), daemon=True, name="rag-ask")
        with _running_lock:
            _running.add(self)
        thread.start()

    def _run(self, fn):
        try:
            self._value = fn()
        except BaseException as e:  # noqa: BLE001
            self._error = e
        finally:
            with _running_lock:
                _running.discard(self)
            self.done.set()

    def result(self):
        if self._error is not None:
            raise self._error
        return self._value


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
