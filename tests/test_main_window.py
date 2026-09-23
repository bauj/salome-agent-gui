import json
import os
import subprocess
import sys
import threading
import time

import pytest
from salome_agent.conversation import TurnResult

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


class FakeConv:
    """First turn: plan gate, then one stage. Later turns: one amend edit."""

    def __init__(self, rec):
        self.rec = rec
        self.degraded = False
        self.ended = False
        self.release = None
        self.next_status = None
        self.n_turns = 0

    def turn(self, text, *, on_event, on_gate, cancel):
        rec = self.rec
        rec.setdefault("turns", []).append(text)
        n, self.n_turns = self.n_turns, self.n_turns + 1

        def ev(kind, **data):
            on_event({"kind": kind, "run_id": "r", "data": data})

        ev("turn_start", turn=n, text=text)
        if self.release is not None:
            while not self.release.is_set():
                time.sleep(0.01)
        if self.next_status is not None:
            status, self.next_status = self.next_status, None
            self.degraded = status == "degraded"
            self.ended = status == "ended"
            ev("turn_done", turn=n, status=status, message=f"{status} happened")
            return TurnResult(status, f"{status} happened", {})
        if n == 0:
            ev("plan", stages=PLAN)
            rec["decision"] = on_gate({"plan": PLAN})
            if rec["decision"]["action"] not in ("approve", "edit"):
                ev("aborted")
                ev("turn_done", turn=n, status="failed", message="turn cancelled")
                return TurnResult("failed", "turn cancelled", {})
            ev("stage_done", index=0, names=["box_1"])
        else:
            ev("graph_edit", op="edit", node="n1", param="dz", old=40, new=60)
            ev("replay", nodes=["n1"])
        ev("report", result_py="/w/result.py", report_md="/w/report.md", text="", usage=None)
        ev("turn_done", turn=n, status="ok", message=f"did {text}")
        return TurnResult("ok", f"did {text}", {})

    def undo(self):
        self.rec["undo"] = True
        return TurnResult("ok", "undone back to turn 0", {})

    def redo(self):
        return TurnResult("ok", "redone up to turn 1", {})

    def rebuild(self):
        self.degraded = False
        return TurnResult("ok", "rebuilt 1 node(s)", {})


def opener(rec):
    def open_fn(config, run_id, *, batch, verbose):
        rec["opened"] = rec.get("opened", 0) + 1
        rec.update(config=config, batch=batch, verbose=verbose)
        rec["conv"] = FakeConv(rec)
        return rec["conv"], lambda: rec.__setitem__("closed", rec.get("closed", 0) + 1)
    return open_fn


def make(qtbot, cfg_path, rec, **kw):
    w = MainWindow(cfg_path, open_fn=opener(rec), probe_fn=lambda: {"mode": "gui", "port": 4242},
                   **kw)
    qtbot.addWidget(w)
    return w


def first_turn(qtbot, w, text="make a box"):
    w.probe()
    w.input.setText(text)
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    w.chat.gate_clicked.emit("approve")
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)


def say(qtbot, w, text):
    w.input.setText(text)
    w.send()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)


def test_loads_key_fields_and_masks_the_key(qtbot, cfg_path):
    w = make(qtbot, cfg_path, {})
    assert w.base_url.text() == "http://h/v1" and w.model.text() == "m"
    assert w.api_key.text() == "secret"


def test_loads_run_options_from_config(qtbot, tmp_path):
    cfg = {**CFG, "policy": {"on_stage_failure": "continue", "tool_selection": "all"}}
    p = tmp_path / "salome-agent.json"
    p.write_text(json.dumps(cfg))
    w = make(qtbot, p, {})
    assert w.on_failure.currentText() == "continue"
    assert w.tools.currentText() == "all"
    assert w.api_key.echoMode() == w.api_key.Password


def test_probe_reports_server_and_enables_send(qtbot, cfg_path):
    w = make(qtbot, cfg_path, {})
    w.probe()
    assert "gui" in w.status.text() and "4242" in w.status.text()
    assert w.send_btn.isEnabled()


def test_key_field_edit_is_saved(qtbot, cfg_path):
    w = make(qtbot, cfg_path, {})
    w.model.setText("qwen3")
    w.model.editingFinished.emit()
    assert json.loads(cfg_path.read_text())["llm"]["model"] == "qwen3"


def test_no_server_keeps_send_disabled(qtbot, cfg_path):
    w = MainWindow(cfg_path, open_fn=opener({}), probe_fn=lambda: None)
    qtbot.addWidget(w)
    w.probe()
    assert not w.send_btn.isEnabled()
    assert "Plugins" in w.status.text()


def test_check_parent_closes_when_parent_is_gone(qtbot, cfg_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    w = make(qtbot, cfg_path, {}, parent_pid=proc.pid)
    w.show()
    w._check_parent()
    assert not w.isVisible()
    assert "exited" in w.status.text()


def test_check_parent_leaves_window_open_when_parent_is_alive(qtbot, cfg_path):
    w = make(qtbot, cfg_path, {}, parent_pid=os.getpid())
    w.show()
    w._check_parent()
    assert w.isVisible()


def test_no_parent_pid_starts_no_watch_timer(qtbot, cfg_path, monkeypatch):
    monkeypatch.delenv("SALOME_AGENT_GUI_PARENT_PID", raising=False)
    w = make(qtbot, cfg_path, {})
    assert w._parent_watch is None


def test_first_message_opens_a_conversation_and_stays_open(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    w.probe()
    w.on_failure.setCurrentText("continue")
    w.input.setText("make a box")
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    assert not w.send_btn.isEnabled() and w.stop_btn.isEnabled()
    w.chat.gate_clicked.emit("approve")
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    assert rec["config"]["policy"]["on_stage_failure"] == "continue"
    md = w.chat.markdown()
    assert "`box_1`" in md and "gate:" not in md and "**Done.** did make a box" in md
    assert w.worker is not None
    assert w.send_btn.isEnabled() and w.undo_btn.isEnabled() and w.new_btn.isEnabled()
    assert not w.rebuild_btn.isEnabled()
    assert not w.on_failure.isEnabled() and not w.batch.isEnabled()


def test_follow_up_amends_the_same_conversation(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    say(qtbot, w, "make it taller")
    assert rec["opened"] == 1 and rec["turns"] == ["make a box", "make it taller"]
    md = w.chat.markdown()
    assert "edit n1.dz: 40 -\\> 60" in md and "**Done.** did make it taller" in md


def test_edit_uses_the_injected_editor(qtbot, cfg_path):
    rec = {}
    edited = [{"module": "geom", "intent": "cyl", "params": {}, "inputs": [], "tools": []}]
    w = make(qtbot, cfg_path, rec, edit_plan=lambda parent, plan: edited)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: "gate:edit" in w.chat.markdown(), timeout=3000)
    w.chat.gate_clicked.emit("edit")
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["decision"] == {"action": "edit", "plan": edited}


def test_stop_aborts_a_pending_gate(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    w.stop_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["decision"] == {"action": "abort"}
    assert "**Turn failed:** turn cancelled" in w.chat.markdown()
    assert w.worker is not None and w.send_btn.isEnabled()


def test_undo_and_redo_add_notes(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    w.undo_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["undo"] is True
    assert "_undo: undone back to turn 0_" in w.chat.markdown()
    w.redo_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert "_redo: redone up to turn 1_" in w.chat.markdown()


def test_rebuild_is_enabled_only_when_degraded(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    rec["conv"].next_status = "degraded"
    say(qtbot, w, "break it")
    assert w.rebuild_btn.isEnabled()
    assert "**Study out of sync:** degraded happened" in w.chat.markdown()
    w.rebuild_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert not w.rebuild_btn.isEnabled()
    assert "_rebuild: rebuilt 1 node\\(s\\)_" in w.chat.markdown()


def test_new_conversation_closes_the_client_and_next_send_reopens(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    w.new_btn.click()
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    assert rec["closed"] == 1
    assert w.on_failure.isEnabled() and not w.undo_btn.isEnabled()
    first_turn(qtbot, w, "make a cylinder")
    assert rec["opened"] == 2


def test_ended_conversation_frees_the_worker_and_next_send_opens_a_new_one(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    rec["conv"].next_status = "ended"
    say(qtbot, w, "anything")
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    md = w.chat.markdown()
    assert "**Session ended:** ended happened" in md
    assert "next message starts a new conversation" in md
    assert w.send_btn.isEnabled()
    first_turn(qtbot, w, "again")
    assert rec["opened"] == 2


def test_close_defers_until_turn_completes(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    w.show()
    first_turn(qtbot, w)
    rec["conv"].release = threading.Event()
    w.input.setText("slow")
    w.send()
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    w.close()
    assert w._close_pending is True and w.worker is not None
    assert w.isVisible()
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: w.worker is None and not w.isVisible(), timeout=5000)
    assert rec["closed"] == 1


def test_done_while_close_pending_skips_probe(qtbot, cfg_path):
    rec = {}
    probe_calls = []

    def probe_fn():
        probe_calls.append(1)
        return {"mode": "gui", "port": 4242}

    w = MainWindow(cfg_path, open_fn=opener(rec), probe_fn=probe_fn)
    qtbot.addWidget(w)
    w.show()
    first_turn(qtbot, w)
    rec["conv"].release = threading.Event()
    w.input.setText("slow")
    w.send()
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    w.close()
    n_before = len(probe_calls)
    assert w._close_pending is True
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: w.worker is None and not w.isVisible(), timeout=5000)
    assert len(probe_calls) == n_before


def test_server_error_disables_send_until_reprobe(qtbot, cfg_path):
    from salome_agent.server_conn import ServerUnavailable

    def failing_open(config, run_id, *, batch, verbose):
        raise ServerUnavailable("poisoned")

    w = MainWindow(cfg_path, open_fn=failing_open, probe_fn=lambda: {"mode": "gui", "port": 4242})
    qtbot.addWidget(w)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: w.worker is None and not w._busy, timeout=3000)
    assert not w.send_btn.isEnabled()
    assert "poisoned" in w.status.text()
    w._probe_fn = lambda: {"mode": "gui", "port": 4242}
    w.probe()
    assert w.send_btn.isEnabled()


def test_failed_undo_note_says_it_failed(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    rec["conv"].undo = lambda: TurnResult("failed", "nothing to undo", {})
    w.undo_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert "_undo failed: nothing to undo_" in w.chat.markdown()
