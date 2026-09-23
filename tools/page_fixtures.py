"""Fixture view models and a stand-in bridge for the chat page: used by the
page tests and by tools/render_states.py."""
import json
import time

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class FakeBridge(QObject):
    push = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.ready_calls = 0
        self.lost = 0

    def emit(self, name, payload):
        self.push.emit(name, json.dumps(payload))

    def page_lost(self):
        self.lost += 1

    @pyqtSlot()
    def ready(self):
        self.ready_calls += 1

    @pyqtSlot(str)
    def send(self, text):
        self.calls.append(("send", text))

    @pyqtSlot(int, str, str)
    def gate(self, gate_id, action, text):
        self.calls.append(("gate", gate_id, action, text))

    @pyqtSlot(str)
    def command(self, name):
        self.calls.append(("command", name))

    @pyqtSlot()
    def stop(self):
        self.calls.append(("stop",))

    @pyqtSlot(str)
    def openFile(self, path):
        self.calls.append(("openFile", path))

    @pyqtSlot(str)
    def saveSettings(self, text):
        self.calls.append(("saveSettings", json.loads(text)))

    @pyqtSlot()
    def editConfigJson(self):
        self.calls.append(("editConfigJson",))

    @pyqtSlot()
    def reconnect(self):
        self.calls.append(("reconnect",))


def _stage(index, module, intent, **kw):
    s = {"index": index, "module": module, "icon": None, "intent": intent, "status": "pending",
         "attempts": 0, "started_at": None, "elapsed_s": None, "error": None}
    s.update(kw)
    return s


def _vm(turn_id, **kw):
    vm = {"id": turn_id, "stages": [], "edits": [], "gate": None, "status": "running",
          "message": "", "objects": [], "files": {"result_py": None, "report_md": None},
          "usage": None}
    vm.update(kw)
    return vm


BODY = "Car body: hull box and cabin box fused into one solid, coloured red"
WHEELS = "Four torus wheels under the hull, kept separate, coloured black"
SPOILER = "Spoiler: a thin box on two posts at the rear of the hull, red like the body"
MESH = "Tetrahedral mesh of the body, spoiler and wheels (max size 4 mm)"
USER_1 = "construct a small car with 4 torus as its wheels. make the car red and the wheels black"
USER_2 = "make the wheels bigger, and a bit wider apart"
USER_3 = "add a spoiler on the back and mesh everything"

SETTINGS = {"base_url": "http://llm.example/v1", "model": "auto", "api_key": "sk-test",
            "on_stage_failure": "abort", "tool_selection": "hints", "batch": False,
            "verbose": 0, "theme": "system", "locked": False,
            "config_path": "~/.config/salome/salome-agent.json"}
STATUS_OK = {"state": "connected", "label": "GUI :46019 · auto", "detail": ""}
STATUS_OFF = {"state": "offline", "label": "Not connected",
              "detail": "No agent server. Start it from Tools > Plugins > SALOME Agent in the "
                        "SALOME window, then press Reconnect in the settings."}
IDLE_NEW = {"busy": False, "stopping": False, "open": False, "degraded": False, "can_send": True}
IDLE_OPEN = {"busy": False, "stopping": False, "open": True, "degraded": False, "can_send": True}
BUSY = {"busy": True, "stopping": False, "open": True, "degraded": False, "can_send": False}

DONE_VM = _vm(0, status="ok", stages=[
    _stage(0, "geom", BODY, status="ok", attempts=1, elapsed_s=12.0),
    _stage(1, "geom", WHEELS, status="ok", attempts=2, elapsed_s=75.0)],
    objects=["fuse_1", "mtr_1_solid_1", "mtr_1_solid_2", "mtr_1_solid_3", "mtr_1_solid_4"],
    files={"result_py": "/tmp/run/result.py", "report_md": "/tmp/run/report.md"},
    usage={"calls": 18, "prompt_tokens": 70819, "completion_tokens": 14763, "llm_seconds": 90.2})
EDIT_VM = _vm(1, status="ok", message="Updated the wheels.", edits=[
    {"op": "edit", "node": "torus_1", "param": "radius_major", "old": "12", "new": "16"},
    {"op": "edit", "node": "mtr_1", "param": "step", "old": "60", "new": "70"},
    {"op": "replay", "nodes": ["torus_1", "rot_1", "tr_2", "mtr_1"]}],
    files={"result_py": "/tmp/run/result.py", "report_md": "/tmp/run/report.md"},
    usage={"calls": 4, "prompt_tokens": 9000, "completion_tokens": 1200, "llm_seconds": 11.0})
PLAN_VM = _vm(2, stages=[_stage(0, "geom", SPOILER), _stage(1, "smesh", MESH)],
              gate={"id": 1, "kind": "plan"})


def running_vm():
    return _vm(2, stages=[_stage(0, "geom", SPOILER, status="ok", attempts=1, elapsed_s=18.0),
                          _stage(1, "smesh", MESH, status="running", attempts=1,
                                 started_at=time.time() - 24)])


FAILED_VM = _vm(2, stages=[
    _stage(0, "geom", SPOILER, status="ok", attempts=1, elapsed_s=18.0),
    _stage(1, "smesh", MESH, status="failed", attempts=3,
           error="Compute failed: NETGEN_3D could not mesh fuse_2\n"
                 "(self-intersecting faces near the spoiler posts)")],
    gate={"id": 2, "kind": "stage_failed", "stage": 1,
          "message": "Compute failed: NETGEN_3D could not mesh fuse_2\n"
                     "(self-intersecting faces near the spoiler posts)", "line": None})

BASE = [("setSettings", SETTINGS), ("setStatus", STATUS_OK)]
HISTORY = [("addUser", {"text": USER_1}), ("renderTurn", DONE_VM),
           ("addUser", {"text": USER_2}), ("renderTurn", EDIT_VM),
           ("addUser", {"text": USER_3})]

STATES = {
    "empty": BASE + [("setBusy", IDLE_NEW)],
    "offline": [("setSettings", SETTINGS), ("setStatus", STATUS_OFF),
                ("setBusy", dict(IDLE_NEW, can_send=False))],
    "plan": BASE + [("setBusy", BUSY)] + HISTORY + [("renderTurn", PLAN_VM)],
    "running": BASE + [("setBusy", BUSY)] + HISTORY + [("renderTurn", "running")],
    "failed": BASE + [("setBusy", BUSY)] + HISTORY + [("renderTurn", FAILED_VM)],
    "conversation": BASE + [("setBusy", IDLE_OPEN)] + HISTORY[:4] + [
        ("addNote", {"text": "undo: undone back to turn 1"})],
    "settings": BASE + [("setBusy", IDLE_OPEN)] + HISTORY[:4] + [
        ("__js__", "document.body.classList.add('settings-open')")],
}


def resolve(payload):
    """`running` is built at push time so its live timer starts near 0:24."""
    return running_vm() if payload == "running" else payload
