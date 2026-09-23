import queue
import threading
import uuid

from PyQt5.QtCore import QThread, pyqtSignal


def default_open(config, run_id, *, batch, verbose):
    from salome_agent import server_conn
    from salome_agent.conversation import Conversation

    client = server_conn.connect(run_id, hold=True)
    try:
        conv = Conversation(config, client, run_id, batch=batch, verbose=verbose)
    except Exception:
        client.close()
        raise

    def close():
        try:
            client.close()
        except Exception:
            pass

    return conv, close


class ConversationWorker(QThread):
    """One thread owning one Conversation (and its agent-server socket) for the
    conversation's life; commands arrive through a queue."""

    event = pyqtSignal(dict)
    gate = pyqtSignal(dict)
    turn_done = pyqtSignal(dict)

    def __init__(self, config, *, batch=False, verbose=0, open_fn=default_open, parent=None):
        super().__init__(parent)
        self.config = config
        self.batch, self.verbose = batch, verbose
        self.run_id = uuid.uuid4().hex[:12]
        self.cancel = threading.Event()
        self._open_fn = open_fn
        self._queue: queue.Queue = queue.Queue()
        self._answered = threading.Event()
        self._decision = None
        self._pending = False

    # ---- called from the GUI thread ------------------------------------
    def submit(self, text: str) -> None:
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
        if self._pending:
            self.answer_gate({"action": "abort"})

    def close(self) -> None:
        self.stop()
        self._queue.put(None)

    def gate_pending(self) -> bool:
        return self._pending

    def answer_gate(self, decision) -> None:
        self._decision = decision
        self._answered.set()

    # ---- worker thread -------------------------------------------------
    def _fatal(self, e: BaseException) -> str:
        message = f"{type(e).__name__}: {e}"
        self.event.emit({"kind": "fatal", "run_id": self.run_id, "data": {"message": message}})
        return message

    def run(self):
        try:
            conv, close = self._open_fn(self.config, self.run_id, batch=self.batch,
                                        verbose=self.verbose)
        except Exception as e:  # noqa: BLE001
            message = self._fatal(e)
            self.turn_done.emit({"command": "turn", "status": "ended", "message": message,
                                 "degraded": False, "ended": True})
            return
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                command, arg = item
                try:
                    if command == "turn":
                        r = conv.turn(arg, on_event=self.event.emit, on_gate=self._on_gate,
                                      cancel=self.cancel)
                    else:
                        r = getattr(conv, command)()
                    status, message = r.status, r.message
                except Exception as e:  # noqa: BLE001
                    status, message = "failed", self._fatal(e)
                self.turn_done.emit({"command": command, "status": status, "message": message,
                                     "degraded": bool(conv.degraded), "ended": bool(conv.ended)})
                if conv.ended:
                    return
        finally:
            close()

    def _on_gate(self, payload):
        self._answered.clear()
        self._decision = None
        self._pending = True
        if self.cancel.is_set():
            self._pending = False
            return {"action": "abort"}
        self.gate.emit(payload)
        self._answered.wait()
        self._pending = False
        return self._decision or {"action": "abort"}
