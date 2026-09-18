import json

import pytest

from salome_agent_gui.main_window import MainWindow

CFG = {"llm": {"base_url": "http://h/v1", "model": "m", "api_key": "secret"},
       "salome": {"root": "/x"}, "policy": {"on_stage_failure": "abort",
                                            "tool_selection": "hints"}}
PLAN = [{"module": "geom", "intent": "box", "params": {}, "inputs": []}]


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "salome-agent.json"
    p.write_text(json.dumps(CFG))
    return p


def gated_run(record):
    def run(request, config, *, run_id, on_event, on_gate, cancel, batch, verbose):
        record.update(request=request, config=config, batch=batch, verbose=verbose)
        on_event({"kind": "plan", "run_id": run_id, "data": {"stages": PLAN}})
        record["decision"] = on_gate({"plan": PLAN})
        if record["decision"]["action"] == "approve":
            on_event({"kind": "stage_done", "run_id": run_id, "data": {"index": 0, "names": ["box_1"]}})
            on_event({"kind": "report", "run_id": run_id,
                      "data": {"result_py": "/w/result.py", "report_md": "/w/report.md",
                               "text": "", "usage": None}})
        return None
    return run


def make(qtbot, cfg_path, run, **kw):
    w = MainWindow(cfg_path, run_fn=run, probe_fn=lambda: {"mode": "gui", "port": 4242}, **kw)
    qtbot.addWidget(w)
    return w


def test_loads_key_fields_and_masks_the_key(qtbot, cfg_path):
    w = make(qtbot, cfg_path, gated_run({}))
    assert w.base_url.text() == "http://h/v1" and w.model.text() == "m"
    assert w.api_key.text() == "secret"
    assert w.api_key.echoMode() == w.api_key.Password


def test_probe_reports_server_and_enables_send(qtbot, cfg_path):
    w = make(qtbot, cfg_path, gated_run({}))
    w.probe()
    assert "gui" in w.status.text() and "4242" in w.status.text()
    assert w.send_btn.isEnabled()


def test_send_approve_runs_to_done(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, gated_run(rec))
    w.probe()
    w.on_failure.setCurrentText("continue")
    w.input.setText("make a box")
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    assert not w.send_btn.isEnabled() and w.stop_btn.isEnabled()
    w.chat.gate_clicked.emit("approve")
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    assert rec["config"]["policy"]["on_stage_failure"] == "continue"
    assert "`box_1`" in w.chat.markdown() and "gate:" not in w.chat.markdown()
    assert w.send_btn.isEnabled()


def test_edit_uses_the_injected_editor(qtbot, cfg_path):
    rec = {}
    edited = [{"module": "geom", "intent": "cyl", "params": {}, "inputs": [], "tools": []}]
    w = make(qtbot, cfg_path, gated_run(rec), edit_plan=lambda parent, plan: edited)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: "gate:edit" in w.chat.markdown(), timeout=3000)
    w.chat.gate_clicked.emit("edit")
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    assert rec["decision"] == {"action": "edit", "plan": edited}


def test_stop_aborts_a_pending_gate(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, gated_run(rec))
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    w.stop_btn.click()
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    assert rec["decision"] == {"action": "abort"}


def test_key_field_edit_is_saved(qtbot, cfg_path):
    w = make(qtbot, cfg_path, gated_run({}))
    w.model.setText("qwen3")
    w.model.editingFinished.emit()
    assert json.loads(cfg_path.read_text())["llm"]["model"] == "qwen3"


def test_no_server_keeps_send_disabled(qtbot, cfg_path):
    w = MainWindow(cfg_path, run_fn=gated_run({}), probe_fn=lambda: None)
    qtbot.addWidget(w)
    w.probe()
    assert not w.send_btn.isEnabled()
    assert "Plugins" in w.status.text()
