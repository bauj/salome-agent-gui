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

    @pyqtSlot(str, str)
    def send(self, text, images):
        self.calls.append(("send", text, json.loads(images or "[]")))

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
         "attempts": 0, "started_at": None, "elapsed_s": None, "error": None, "objects": []}
    s.update(kw)
    return s


def _vm(turn_id, **kw):
    vm = {"id": turn_id, "stages": [], "edits": [], "gate": None, "status": "running",
          "message": "", "objects": [], "files": {"result_py": None, "report_md": None},
          "usage": None, "vision": None}
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
            "ssl_cert_file": "~/certs/ca.pem", "on_stage_failure": "abort", "tool_selection": "hints", "batch": False,
            "verbose": 0, "theme": "system", "locked": False,
            "config_path": "~/.config/salome/salome-agent.json",
            "shared_model": True, "modules": {}, "modules_json_only": {},
            "module_names": ["planner", "vision", "geom", "smesh", "paravis", "amend"],
            "reasoning_budget": 20000, "vision_fix_retries": 2, "timeout": 120}
MODELS_SETTINGS = dict(SETTINGS, shared_model=False, modules={
    "vision": {"model": "drawing-reader", "base_url": "http://reader.example/v1",
               "api_key": "sk-reader", "ssl_cert_file": ""},
    "visio": {"model": "typo", "base_url": "", "api_key": "", "ssl_cert_file": ""}},
    modules_json_only={"vision": ["extra_body"]})
STATUS_OK = {"state": "connected", "label": "GUI :46019 · auto", "detail": ""}
STATUS_OFF = {"state": "offline", "label": "Not connected",
              "detail": "No agent server. Start it from Tools > Plugins > SALOME Agent in the "
                        "SALOME window, then press Reconnect in the settings."}
IDLE_NEW = {"busy": False, "stopping": False, "open": False, "degraded": False, "can_send": True}
IDLE_OPEN = {"busy": False, "stopping": False, "open": True, "degraded": False, "can_send": True}
BUSY = {"busy": True, "stopping": False, "open": True, "degraded": False, "can_send": False}

DONE_VM = _vm(0, status="ok", stages=[
    _stage(0, "geom", BODY, status="ok", attempts=1, elapsed_s=12.0, objects=["fuse_1"]),
    _stage(1, "geom", WHEELS, status="ok", attempts=2, elapsed_s=75.0,
           objects=["mtr_1_solid_1", "mtr_1_solid_2", "mtr_1_solid_3", "mtr_1_solid_4"])],
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

def _vision(**kw):
    v = {"status": "done", "images": 1, "sizes": ["1200x800"], "model": "drawing-reader",
         "checks": [], "parts": 3, "conflicts": 0, "started_at": None, "elapsed_s": 232.0,
         "error": None, "reasoning": []}
    v.update(kw)
    return v


VISION_CONFLICTS_VM = _vm(3, vision=_vision(
    status="conflicts", conflicts=2,
    checks=[{"attempt": 1, "of": 2, "errors": ["P1: profile is not closed", "R9 - 4X: 3 arcs found"]},
            {"attempt": 2, "of": 2, "errors": ["P1: profile is not closed"]}]),
    stages=[_stage(0, "geom", "Bracket plate with four holes, 5 mm thick")],
    gate={"id": 3, "kind": "plan"})


def vision_running_vm():
    return _vm(3, vision=_vision(status="running", parts=None, elapsed_s=None,
                                 started_at=time.time() - 134,
                                 checks=[{"attempt": 1, "of": 2,
                                          "errors": ["P2: hole overlaps the outline"]}]))


BASE = [("setSettings", SETTINGS), ("setStatus", STATUS_OK)]
HISTORY = [("addUser", {"text": USER_1}), ("renderTurn", DONE_VM),
           ("addUser", {"text": USER_2}), ("renderTurn", EDIT_VM),
           ("addUser", {"text": USER_3})]

def sketch_uri(kind: str) -> str:
    """A small drawing as a PNG data: URI, standing in for a user's photo or
    sketch. Needs a QGuiApplication (built at push time, like `running`)."""
    import base64

    from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPointF, Qt
    from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

    img = QImage(480, 360, QImage.Format_RGB32)
    img.fill(QColor("#fbfaf6"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#2b3a55"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == "bracket":
        p.drawPolygon(QPolygonF([QPointF(*xy) for xy in
                                 ((80, 60), (160, 60), (160, 230), (400, 230), (400, 300),
                                  (80, 300))]))
        for x, y in ((120, 110), (120, 170), (250, 265), (340, 265)):
            p.drawEllipse(QPointF(x, y), 14, 14)
    else:
        p.drawRect(90, 150, 300, 150)
        p.drawPolygon(QPolygonF([QPointF(70, 150), QPointF(240, 50), QPointF(410, 150)]))
        p.drawRect(210, 210, 60, 90)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")


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
    "settings-models": [("setSettings", MODELS_SETTINGS), ("setStatus", STATUS_OK),
                        ("setBusy", IDLE_NEW),
                        ("__js__", "document.body.classList.add('settings-open');"
                                   "document.getElementById('set-advanced').open = true; true")],
    "vision-running": BASE + [("setBusy", BUSY), ("addUser", "sketch-message"),
                              ("renderTurn", "vision-running")],
    "vision-conflicts": BASE + [("setBusy", BUSY), ("addUser", "sketch-message"),
                                ("renderTurn", VISION_CONFLICTS_VM)],
    "images": BASE + [("setBusy", IDLE_OPEN), ("addUser", "sketch-message"),
                      ("renderTurn", DONE_VM), ("__js__", "attach-sketches")],
}


def resolve(payload):
    """`running` is built at push time so its live timer starts near 0:24; the
    sketches need the QApplication."""
    if payload == "running":
        return running_vm()
    if payload == "vision-running":
        return vision_running_vm()
    if payload == "sketch-message":
        return {"text": "A bracket like this sketch, 5 mm thick",
                "images": [sketch_uri("bracket")]}
    if payload == "attach-sketches":
        files = [{"name": "house-front.png", "url": sketch_uri("house")},
                 {"name": "bracket.png", "url": sketch_uri("bracket")}]
        return (f"attached = {json.dumps(files)}; renderAttachments(); "
                "document.getElementById('input').value = 'Now add a house like these'; true")
    return payload
