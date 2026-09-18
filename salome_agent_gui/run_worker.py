import threading
import uuid

from PyQt5.QtCore import QThread, pyqtSignal


def default_run(request, config, *, run_id, on_event, on_gate, cancel, batch, verbose):
    from salome_agent import server_conn
    from salome_agent.runner import run_request

    client = server_conn.connect(run_id)
    try:
        return run_request(request, config, client=client, on_event=on_event,
                           on_gate=on_gate, cancel=cancel, batch=batch,
                           verbose=verbose, run_id=run_id)
    finally:
        try:
            client.close()
        except Exception:
            pass


class RunWorker(QThread):
    event = pyqtSignal(dict)
    gate = pyqtSignal(dict)
    done = pyqtSignal(object)

    def __init__(self, request, config, *, batch=False, verbose=0, run_fn=default_run,
                 parent=None):
        super().__init__(parent)
        self.request, self.config = request, config
        self.batch, self.verbose = batch, verbose
        self.run_id = uuid.uuid4().hex[:12]
        self.cancel = threading.Event()
        self._run_fn = run_fn
        self._answered = threading.Event()
        self._decision = None
        self._pending = False

    def run(self):
        result = None
        try:
            result = self._run_fn(self.request, self.config, run_id=self.run_id,
                                  on_event=self.event.emit, on_gate=self._on_gate,
                                  cancel=self.cancel, batch=self.batch, verbose=self.verbose)
        except Exception as e:  # noqa: BLE001
            self.event.emit({"kind": "fatal", "run_id": self.run_id,
                             "data": {"message": f"{type(e).__name__}: {e}"}})
        self.done.emit(result)

    def _on_gate(self, payload):
        self._answered.clear()
        self._decision = None
        self._pending = True
        self.gate.emit(payload)
        self._answered.wait()
        self._pending = False
        return self._decision or {"action": "abort"}

    def gate_pending(self) -> bool:
        return self._pending

    def answer_gate(self, decision):
        self._decision = decision
        self._answered.set()

    def stop(self):
        self.cancel.set()
        if self._pending:
            self.answer_gate({"action": "abort"})
