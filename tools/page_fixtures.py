# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
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
    def loadConfig(self):
        self.calls.append(("loadConfig",))

    @pyqtSlot()
    def reconnect(self):
        self.calls.append(("reconnect",))

    @pyqtSlot(str)
    def openLink(self, target):
        self.calls.append(("openLink", target))

    @pyqtSlot()
    def buildIndex(self):
        self.calls.append(("buildIndex",))


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
            "verbose": 0, "theme": "system", "locked": False, "active_mode": "agent", "can_switch_mode": True,
            "config_path": "~/.config/salome/salome-agent.json",
            "shared_model": True, "modules": {}, "modules_json_only": {},
            "module_names": ["planner", "vision", "geom", "smesh", "amend"],
            "reasoning_budget": 20000, "vision_fix_retries": 2, "timeout": 120,
            "rag_options": {"k_standard": 40, "top_n_after_rerank": 15, "expansion_char_budget": 60000,
                            "max_tokens": 5000, "bm25_enabled": True, "title_boost_enabled": True,
                            "hyde_enabled": False, "temperature": 0.0, "reranker": True,
                            "max_steps": 20, "max_chars_per_page": 8000, "section_top_n": 5,
                            "section_char_budget": 15000}}
MODELS_SETTINGS = dict(SETTINGS, shared_model=False, modules={
    "vision": {"model": "drawing-reader", "base_url": "http://reader.example/v1",
               "api_key": "sk-reader", "ssl_cert_file": ""},
    "visio": {"model": "typo", "base_url": "", "api_key": "", "ssl_cert_file": ""}},
    modules_json_only={"vision": ["extra_body"]})
STATUS_OK = {"state": "connected", "label": "GUI :46019 · auto", "detail": ""}
STATUS_OFF = {"state": "offline", "label": "Not connected",
              "detail": "No agent server. Start it from Tools > Plugins > AI tools > SALOME agent in the "
                        "SALOME window, then press Reconnect in the settings."}
IDLE_NEW = {"busy": False, "stopping": False, "open": False, "degraded": False, "can_send": True,
            "mode": "agent", "can_switch_mode": True}
IDLE_OPEN = {"busy": False, "stopping": False, "open": True, "degraded": False, "can_send": True,
             "mode": "agent", "can_switch_mode": False}
BUSY = {"busy": True, "stopping": False, "open": True, "degraded": False, "can_send": False,
        "mode": "agent", "can_switch_mode": False}

DOC_RAG = {"configured": True, "index": "~/.local/share/salome-agent/rag/salome_docs_extracted/chromadb",
           "index_exists": True, "agentic": True, "building": False, "line": ""}
DOC_ROOT = "/opt/SALOME-9.16.0/INSTALL/DOCUMENTATION/share/doc/salome"
DOC_SOURCES = [
    {"name": m, "description": d, "dev_path": f"${{DOCUMENTATION_ROOT_DIR:-${m}_ROOT_DIR}}/share/doc/salome/tui/{m}",
     "user_path": f"${{DOCUMENTATION_ROOT_DIR:-${m}_ROOT_DIR}}/share/doc/salome/gui/{m}",
     "cite_dev": f"https://docs.salome-platform.org/latest/tui/{m}",
     "cite_user": f"https://docs.salome-platform.org/latest/gui/{m}", "json_only": [],
     "dev_state": {"state": "ok", "resolved": f"{DOC_ROOT}/tui/{m}", "vars": []},
     "user_state": {"state": "ok", "resolved": f"{DOC_ROOT}/gui/{m}", "vars": []}}
    for m, d in (("GEOM", "Geometry module: CAD construction and manipulation."),
                 ("SMESH", "Mesh module: meshing algorithms and mesh editing."))]
DOC_SOURCES.append({"name": "MYDOCS", "description": "", "dev_path": "", "user_path": "$MYDOCS_ROOT/html",
                    "cite_dev": "", "cite_user": "", "json_only": ["methodology_path"],
                    "dev_state": {"state": "empty", "resolved": "", "vars": []},
                    "user_state": {"state": "unset", "resolved": "$MYDOCS_ROOT/html", "vars": ["MYDOCS_ROOT"]}})
DOC_MODELS = {
    "embedding": {"model": "all-MiniLM-L6-v2", "type": "local",
                  "status": {"state": "installed", "repo": "sentence-transformers/all-MiniLM-L6-v2",
                             "path": "~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2",
                             "size": "87.3 MB"}},
    "reranker": {"model": "BAAI/bge-reranker-v2-m3", "type": "cross_encoder", "enabled": True,
                 "status": {"state": "missing", "repo": "BAAI/bge-reranker-v2-m3",
                            "path": "~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3", "size": ""}},
    "cache": "~/.cache/huggingface/hub",
    "choices": {"embedding": [{"model": "all-MiniLM-L6-v2", "note": "small and fast"}],
                "reranker": [{"model": "answerdotai/answerai-colbert-small-v1", "type": "late_interaction",
                              "note": "ColBERT"},
                             {"model": "BAAI/bge-reranker-v2-m3", "type": "cross_encoder", "note": "cross-encoder"}]}}
DOC_SETTINGS = dict(SETTINGS, mode="rag_agentic", active_mode="rag_agentic", rag=DOC_RAG,
                    doc_sources=DOC_SOURCES, rag_models=DOC_MODELS)
DOC_STATUS = {"state": "connected", "label": "Agentic RAG · auto", "detail": ""}
DOC_IDLE = dict(IDLE_NEW, doc=True, mode="rag_agentic")
DOC_BUSY = dict(BUSY, doc=True, mode="rag_agentic")
DOC_QUESTION = "How do I set a local mesh size on a face in SMESH?"
DOC_ANSWER = """Use a **local hypothesis** on a sub-mesh of that face:

1. Create the mesh on the whole shape with a global size.
2. Add a sub-mesh on the face and give it its own `NETGEN 2D Parameters`, or a
   *Max. Element Area* hypothesis.

```python
face_mesh = mesh.Triangle(algo=smeshBuilder.NETGEN_2D, geom=face)
params = face_mesh.Parameters()
params.SetMaxSize(2.0)
mesh.Compute()
```

> The sub-mesh wins over the global hypothesis on that face only.

See [Constructing sub-meshes](https://docs.salome-platform.org/latest/gui/SMESH/constructing_submeshes.html)."""
DOC_SOURCES = [
    {"title": "Constructing sub-meshes", "module": "SMESH", "category": "user",
     "url": "https://docs.salome-platform.org/latest/gui/SMESH/constructing_submeshes.html", "path": ""},
    {"title": "NETGEN 2D Parameters", "module": "SMESH", "category": "user",
     "url": "https://docs.salome-platform.org/latest/gui/SMESH/netgen_2d_3d_hypo.html", "path": ""},
    {"title": "smeshBuilder.Mesh", "module": "SMESH", "category": "dev", "url": "",
     "path": "/opt/salome/SMESH/share/doc/salome/tui/SMESH/classsmeshBuilder_1_1Mesh.html"}]


def _doc_rag(**kw):
    return {"status": "done", "phase": "searching", "agentic": True, "answer": DOC_ANSWER,
            "sources": DOC_SOURCES, "usage": {"input_tokens": 18400, "output_tokens": 410},
            "degraded": False, "steps": 9, "seconds": 21.4, **kw}


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
                                   "document.getElementById('set-advanced').open = true;"
                                   "document.getElementById('set-advanced').scrollIntoView(); true")],
    "vision-running": BASE + [("setBusy", BUSY), ("addUser", "sketch-message"),
                              ("renderTurn", "vision-running")],
    "vision-conflicts": BASE + [("setBusy", BUSY), ("addUser", "sketch-message"),
                                ("renderTurn", VISION_CONFLICTS_VM)],
    "edit-running": BASE + [("setBusy", BUSY), ("addUser", {"text": "make the wheels bigger"}),
                            ("renderTurn", "edit-running")],
    "edit-done": BASE + [("setBusy", IDLE_OPEN), ("addUser", {"text": "make the wheels bigger"}),
                         ("renderTurn", dict(EDIT_VM, elapsed_s=14.2))],
    "images": BASE + [("setBusy", IDLE_OPEN), ("addUser", "sketch-message"),
                      ("renderTurn", DONE_VM), ("__js__", "attach-sketches")],
}


DOC_VM = _vm(0, status="ok", elapsed_s=21.4, rag=_doc_rag())
DOC_BASE = [("setSettings", DOC_SETTINGS), ("setStatus", DOC_STATUS)]
STATES.update({
    "doc-empty": DOC_BASE + [("setBusy", DOC_IDLE)],
    "doc-running": DOC_BASE + [("setBusy", DOC_BUSY), ("addUser", {"text": DOC_QUESTION}),
                               ("renderTurn", "doc-running")],
    "doc-answer": DOC_BASE + [("setBusy", dict(DOC_IDLE, open=True)),
                              ("addUser", {"text": DOC_QUESTION}), ("renderTurn", DOC_VM)],
    "doc-settings": DOC_BASE + [("setBusy", DOC_IDLE),
                                ("__js__", "document.body.classList.add('settings-open');"
                                           "document.querySelector('.drawer-body').scrollTop = 0; true")],
    "doc-settings-rag": [("setSettings", dict(DOC_SETTINGS, mode="rag", active_mode="rag")),
                         ("setStatus", DOC_STATUS), ("setBusy", DOC_IDLE),
                         ("__js__", "document.body.classList.add('settings-open');"
                                    "document.querySelector('.drawer-body').scrollTop = 9999; true")],
    "doc-settings-models": DOC_BASE + [
        ("setBusy", DOC_IDLE),
        ("__js__", "document.body.classList.add('settings-open');"
                   "document.getElementById('set-emb-model').closest('div[data-modes]').scrollIntoView(); true")],
    "doc-settings-downloading": DOC_BASE + [
        ("setBusy", DOC_IDLE),
        ("setIndex", {"building": True, "job": "models",
                      "line": "Downloading the reranker model BAAI/bge-reranker-v2-m3…"}),
        ("__js__", "document.body.classList.add('settings-open');"
                   "document.getElementById('set-emb-model').closest('div[data-modes]').scrollIntoView(); true")],
    "doc-settings-agentic-scrolled": DOC_BASE + [
        ("setBusy", DOC_IDLE),
        ("__js__", "document.body.classList.add('settings-open');"
                   "document.querySelector('.drawer-body').scrollTop = 9999; true")],
})


def resolve(payload):
    """`running` is built at push time so its live timer starts near 0:24; the
    sketches need the QApplication."""
    if payload == "running":
        return running_vm()
    if payload == "doc-running":
        return _vm(0, status="running", started_at=time.time() - 6,
                   rag=_doc_rag(status="running", answer="", sources=[], usage=None, steps=None))
    if payload == "vision-running":
        return vision_running_vm()
    if payload == "edit-running":
        return dict(EDIT_VM, status="running", edits=[], started_at=time.time() - 9)
    if payload == "sketch-message":
        return {"text": "A bracket like this sketch, 5 mm thick",
                "images": [sketch_uri("bracket")]}
    if payload == "attach-sketches":
        files = [{"name": "house-front.png", "url": sketch_uri("house")},
                 {"name": "bracket.png", "url": sketch_uri("bracket")}]
        return (f"attached = {json.dumps(files)}; renderAttachments(); "
                "document.getElementById('input').value = 'Now add a house like these'; true")
    return payload
