import itertools
import json
import threading
import time

import pytest
from salome_agent.conversation import TurnResult

from salome_agent_gui.bridge import Bridge
from tests.fakes import CFG, opener, write_cfg

GUI = {"mode": "gui", "port": 4242}


class Pushes:
    def __init__(self, bridge):
        self.items = []
        bridge.push.connect(lambda name, payload: self.items.append((name, json.loads(payload))))

    def all(self, name):
        return [p for n, p in self.items if n == name]

    def last(self, name):
        found = self.all(name)
        return found[-1] if found else None

    def names(self):
        return [n for n, _ in self.items]


@pytest.fixture
def cfg_path(tmp_path):
    return write_cfg(tmp_path)


@pytest.fixture
def bridges():
    made = []
    yield made
    for b in made:
        if b.worker is not None:
            b.worker.close()
            b.worker.wait(3000)


def make(bridges, cfg_path, rec, *, ready=True, probe=lambda: GUI, **kw):
    b = Bridge(cfg_path, open_fn=opener(rec), probe_fn=probe, **kw)
    bridges.append(b)
    p = Pushes(b)
    if ready:
        b.ready()
    return b, p


def vm(p):
    return p.last("renderTurn")


def wait_gate(qtbot, p):
    qtbot.waitUntil(lambda: (vm(p) or {}).get("gate") is not None, timeout=3000)
    return vm(p)["gate"]


def first_turn(qtbot, b, p, text="make a box"):
    b.probe()
    b.send(text)
    b.gate(wait_gate(qtbot, p)["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)


def say(qtbot, b, text):
    b.send(text)
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)


def test_pushes_wait_for_ready_then_the_full_state_goes_out(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {}, ready=False)
    b.probe()
    assert p.items == []
    b.ready()
    assert p.names()[:5] == ["setSettings", "setTheme", "setStatus", "setBusy", "replay"]
    s = p.last("setSettings")
    assert (s["base_url"], s["model"], s["locked"]) == ("http://h/v1", "m", False)
    assert s["config_path"] == str(cfg_path)
    assert p.last("setTheme") == {"theme": "light"}
    st = p.last("setStatus")
    assert st["state"] == "connected" and "GUI :4242" in st["label"] and "m" in st["label"]
    assert p.last("replay") == {"items": []}


def test_no_server_keeps_send_disabled_and_explains(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {}, probe=lambda: None)
    b.probe()
    st = p.last("setStatus")
    assert st["state"] == "offline" and "Plugins" in st["detail"]
    assert p.last("setBusy")["can_send"] is False
    b.send("x")
    assert b.worker is None and p.last("addUser") is None


def test_first_message_opens_a_conversation_and_stays_open(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("  make a box  ")
    assert p.last("addUser") == {"text": "make a box"}
    gate = wait_gate(qtbot, p)
    assert gate["kind"] == "plan" and vm(p)["stages"][0]["module"] == "geom"
    busy = p.last("setBusy")
    assert busy["busy"] and busy["open"] and not busy["can_send"]
    assert p.last("setSettings")["locked"] is True
    b.gate(gate["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    last = vm(p)
    assert last["gate"] is None and last["status"] == "ok" and last["message"] == "did make a box"
    assert last["objects"] == ["box_1"]
    assert last["files"] == {"result_py": "/w/result.py", "report_md": "/w/report.md"}
    assert b.worker is not None
    assert p.last("setBusy") == {"busy": False, "stopping": False, "open": True,
                                 "degraded": False, "can_send": True}


def test_saved_run_options_reach_the_conversation(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.saveSettings(json.dumps({"on_stage_failure": "continue", "tool_selection": "all",
                               "batch": True, "verbose": 1}))
    first_turn(qtbot, b, p)
    assert rec["config"]["policy"]["on_stage_failure"] == "continue"
    assert rec["config"]["policy"]["tool_selection"] == "all"
    assert (rec["batch"], rec["verbose"]) == (True, 1)


def test_follow_up_amends_the_same_conversation_with_per_turn_usage(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    assert vm(p)["usage"] == {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                              "llm_seconds": 1.5}
    say(qtbot, b, "make it taller")
    assert rec["opened"] == 1 and rec["turns"] == ["make a box", "make it taller"]
    last = vm(p)
    assert last["id"] == 1
    assert last["edits"] == [{"op": "edit", "node": "n1", "param": "dz", "old": "40", "new": "60"},
                             {"op": "replay", "nodes": ["n1"]}]
    assert last["usage"] == {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                             "llm_seconds": 1.5}


def test_edit_uses_the_injected_editor_and_cancel_keeps_the_gate(qtbot, bridges, cfg_path):
    rec = {}
    answers = [None, [{"module": "geom", "intent": "cyl", "params": {}, "inputs": []}]]
    b, p = make(bridges, cfg_path, rec, edit_plan=lambda parent, plan: answers.pop(0))
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    b.gate(gate["id"], "edit", "")
    qtbot.wait(100)
    assert "decision" not in rec and vm(p)["gate"] == gate
    b.gate(gate["id"], "edit", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"]["action"] == "edit" and rec["decision"]["plan"][0]["intent"] == "cyl"


def test_hint_sends_the_typed_text_and_a_blank_hint_is_ignored(qtbot, bridges, cfg_path):
    rec = {"first_gate": {"last_error": {"message": "fillet failed\nsecond line",
                                         "offending_line": 7}}}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    assert gate["kind"] == "stage_failed" and gate["message"] == "fillet failed\nsecond line"
    assert gate["line"] == 7
    b.gate(gate["id"], "hint", "   ")
    qtbot.wait(100)
    assert "decision" not in rec
    b.gate(gate["id"], "hint", "  try r=2 ")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "hint", "hint": "try r=2"}


def test_stale_gate_id_is_ignored(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    b.gate(gate["id"] + 1, "abort", "")
    qtbot.wait(100)
    assert "decision" not in rec
    b.gate(gate["id"], "approve", "")
    b.gate(gate["id"], "abort", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    assert vm(p)["status"] == "ok"


def test_stop_aborts_a_pending_gate_and_keeps_the_conversation(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x")
    wait_gate(qtbot, p)
    b.stop()
    assert p.last("setBusy")["stopping"] is True
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "abort"}
    last = vm(p)
    assert (last["status"], last["message"]) == ("failed", "turn cancelled")
    assert b.worker is not None and p.last("setBusy")["can_send"] is True
    assert p.last("setBusy")["stopping"] is False


def test_undo_and_redo_add_notes(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    b.command("undo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    b.command("redo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["undo"] is True
    assert [n["text"] for n in p.all("addNote")] == ["undo: undone back to turn 0",
                                                     "redo: redone up to turn 1"]


def test_failed_undo_note_says_it_failed(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    rec["conv"].undo = lambda: TurnResult("failed", "nothing to undo", {})
    b.command("undo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert p.last("addNote") == {"text": "undo failed: nothing to undo"}


def test_rebuild_only_runs_when_degraded(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    b.command("rebuild")
    assert not b.busy and "rebuilt" not in rec
    rec["conv"].next_status = "degraded"
    say(qtbot, b, "break it")
    assert p.last("setBusy")["degraded"] is True and vm(p)["status"] == "degraded"
    b.command("rebuild")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["rebuilt"] == 1 and p.last("setBusy")["degraded"] is False
    assert p.last("addNote") == {"text": "rebuild: rebuilt 1 node(s)"}


def test_new_conversation_closes_the_client_and_restarts_usage(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    say(qtbot, b, "taller")
    b.command("new")
    qtbot.waitUntil(lambda: b.worker is None, timeout=3000)
    assert rec["closed"] == 1
    assert "New conversation" in p.last("addNote")["text"]
    assert p.last("setSettings")["locked"] is False
    first_turn(qtbot, b, p, "make a cylinder")
    assert rec["opened"] == 2 and vm(p)["usage"]["calls"] == 3


def test_ended_conversation_frees_the_worker_and_next_send_opens_a_new_one(qtbot, bridges,
                                                                          cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    rec["conv"].next_status = "ended"
    b.send("anything")
    qtbot.waitUntil(lambda: b.worker is None, timeout=3000)
    assert vm(p)["status"] == "ended"
    assert "next message starts a new conversation" in p.last("addNote")["text"]
    assert p.last("setBusy")["can_send"] is True
    first_turn(qtbot, b, p, "again")
    assert rec["opened"] == 2


def test_request_close_when_idle_returns_true(bridges, cfg_path):
    b, _ = make(bridges, cfg_path, {})
    assert b.request_close() is True


def test_request_close_during_a_turn_does_not_block(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    rec["conv"].release = threading.Event()
    b.send("slow")
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    closed = []
    b.close_ready.connect(lambda: closed.append(1))
    t0 = time.monotonic()
    assert b.request_close() is False
    assert time.monotonic() - t0 < 0.5
    assert b.close_pending and p.last("setBusy")["stopping"] is True
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: closed == [1], timeout=5000)
    assert b.worker is None and rec["closed"] == 1


def test_done_while_close_pending_skips_the_probe(qtbot, bridges, cfg_path):
    rec, calls = {}, []

    def probe():
        calls.append(1)
        return GUI

    b, p = make(bridges, cfg_path, rec, probe=probe)
    first_turn(qtbot, b, p)
    rec["conv"].release = threading.Event()
    b.send("slow")
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    b.request_close()
    n = len(calls)
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: b.worker is None, timeout=5000)
    assert len(calls) == n


def test_server_error_disables_send_until_reconnect(qtbot, bridges, cfg_path):
    from salome_agent.server_conn import ServerUnavailable

    def failing_open(config, run_id, *, batch, verbose):
        raise ServerUnavailable("poisoned")

    b = Bridge(cfg_path, open_fn=failing_open, probe_fn=lambda: GUI)
    bridges.append(b)
    p = Pushes(b)
    b.ready()
    b.probe()
    b.send("x")
    qtbot.waitUntil(lambda: b.worker is None and not b.busy, timeout=3000)
    st = p.last("setStatus")
    assert st["state"] == "error" and "poisoned" in st["detail"]
    assert p.last("setBusy")["can_send"] is False
    b.reconnect()
    assert p.last("setStatus")["state"] == "connected"
    assert p.last("setBusy")["can_send"] is True


def test_run_options_are_refused_while_a_conversation_is_open(qtbot, bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    first_turn(qtbot, b, p)
    b.saveSettings(json.dumps({"model": "m2", "theme": "dark", "on_stage_failure": "continue",
                               "batch": True}))
    data = json.loads(cfg_path.read_text())
    assert data["llm"]["model"] == "m2" and data["gui"]["theme"] == "dark"
    assert data["policy"]["on_stage_failure"] == "abort" and "batch" not in data["gui"]
    assert p.last("setTheme") == {"theme": "dark"}
    assert "m2" in p.last("setStatus")["label"]


def test_bad_settings_json_is_ignored(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    before = cfg_path.read_text()
    b.saveSettings("{not json")
    b.saveSettings("[1, 2]")
    assert cfg_path.read_text() == before


def test_ready_again_replays_the_whole_transcript(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    b.command("undo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    b.page_lost()
    n = len(p.items)
    say(qtbot, b, "taller")
    assert len(p.items) == n
    b.ready()
    items = p.last("replay")["items"]
    assert [i["type"] for i in items] == ["user", "turn", "note", "user", "turn"]
    assert items[0]["text"] == "make a box" and items[1]["vm"]["objects"] == ["box_1"]
    assert items[4]["vm"]["edits"][0]["op"] == "edit"


def test_open_file_only_opens_files_a_run_reported(qtbot, bridges, cfg_path):
    opened = []
    b, p = make(bridges, cfg_path, {}, open_file=opened.append)
    b.openFile("/w/result.py")
    assert opened == []
    first_turn(qtbot, b, p)
    b.openFile("/etc/passwd")
    b.openFile("/w/result.py")
    assert opened == ["/w/result.py"]


def test_edit_config_json_pushes_the_new_settings(bridges, cfg_path):
    def editor(parent, path):
        data = json.loads(path.read_text())
        data["llm"]["model"] = "edited"
        path.write_text(json.dumps(data))
        return True

    b, p = make(bridges, cfg_path, {}, edit_config=editor)
    b.editConfigJson()
    assert p.last("setSettings")["model"] == "edited"


def test_stage_icons_and_times_come_from_the_injected_lookups(qtbot, bridges, cfg_path):
    ticks = itertools.chain([100.0, 112.5], itertools.repeat(200.0))
    b, p = make(bridges, cfg_path, {}, icon_for=lambda m: f"file:///icons/{m}.png",
                clock=lambda: next(ticks))
    first_turn(qtbot, b, p)
    stage = vm(p)["stages"][0]
    assert stage["icon"] == "file:///icons/geom.png"
    assert (stage["started_at"], stage["elapsed_s"]) == (100.0, 12.5)


def test_system_theme_follows_the_palette_and_an_explicit_theme_wins(tmp_path, bridges):
    path = write_cfg(tmp_path, {**CFG, "gui": {"theme": "system"}})
    b, p = make(bridges, path, {}, system_dark=lambda: True)
    assert p.last("setTheme") == {"theme": "dark"}
    b.saveSettings(json.dumps({"theme": "light"}))
    assert p.last("setTheme") == {"theme": "light"}


def test_double_edit_while_the_dialog_is_open_sends_one_answer(qtbot, bridges, cfg_path):
    rec = {}
    plan = [{"module": "geom", "intent": "cyl", "params": {}, "inputs": []}]
    holder = {}

    def editor(parent, current):
        if "reentered" not in holder:
            holder["reentered"] = True
            holder["b"].gate(holder["id"], "edit", "")     # second click, inside the dialog loop
        return plan

    b, p = make(bridges, cfg_path, rec, edit_plan=editor)
    holder["b"] = b
    b.probe()
    b.send("x")
    holder["id"] = wait_gate(qtbot, p)["id"]
    answers = []
    orig = b.worker.answer_gate
    b.worker.answer_gate = lambda d: (answers.append(d), orig(d))
    b.gate(holder["id"], "edit", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert len(answers) == 1


def test_worker_gone_while_the_edit_dialog_is_open_does_not_crash(qtbot, bridges, cfg_path):
    rec = {}
    holder = {}

    def editor(parent, current):
        holder["b"].worker = None                           # SALOME exited under the dialog
        return [{"module": "geom", "intent": "cyl", "params": {}, "inputs": []}]

    b, p = make(bridges, cfg_path, rec, edit_plan=editor)
    holder["b"] = b
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    worker = b.worker
    b.gate(gate["id"], "edit", "")
    worker.close()
    worker.wait(3000)


def test_cancelled_edit_re_renders_the_turn(qtbot, bridges, cfg_path):
    b, p = make(bridges, cfg_path, {}, edit_plan=lambda parent, plan: None)
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    n = len(p.all("renderTurn"))
    b.gate(gate["id"], "edit", "")
    assert len(p.all("renderTurn")) == n + 1 and vm(p)["gate"] == gate


def test_a_broken_config_file_is_reported_not_fatal(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    cfg_path.write_text("{not json")
    b.probe()
    b.saveSettings(json.dumps({"model": "m2"}))
    b.send("make a box")
    st = p.last("setStatus")
    assert st["state"] == "error" and st["label"] == "Config error"
    assert b.worker is None and p.last("addUser") is None
    assert cfg_path.read_text() == "{not json"


def _first_plan_render(p):
    return next(v for v in p.all("renderTurn") if v["stages"])


@pytest.mark.parametrize("batch, first", [(False, "pending"), (True, "running")])
def test_plan_starts_the_stage_clock_only_in_batch_mode(qtbot, bridges, cfg_path, batch, first):
    b, p = make(bridges, cfg_path, {})
    b.saveSettings(json.dumps({"batch": batch}))
    first_turn(qtbot, b, p)
    assert _first_plan_render(p)["stages"][0]["status"] == first


def test_approving_the_plan_shows_the_first_stage_running_at_once(qtbot, bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    b.gate(gate["id"], "approve", "")
    right_after = vm(p)                      # rendered by gate() itself, before any worker event
    assert right_after["gate"] is None and right_after["stages"][0]["status"] == "running"
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)


def test_a_cancelled_turn_keeps_its_usage_out_of_the_next_turn(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("make a box")
    b.gate(wait_gate(qtbot, p)["id"], "abort", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert vm(p)["usage"] == {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                              "llm_seconds": 1.5}
    say(qtbot, b, "again")
    assert vm(p)["usage"] == {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                              "llm_seconds": 1.5}


def test_reasoning_event_appends_without_re_rendering_the_turn(qtbot, bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    first_turn(qtbot, b, p)
    renders = len(p.all("renderTurn"))
    b._on_event({"kind": "reasoning", "run_id": "r", "data": {
        "source": "stage", "index": 0, "call": 2, "channel": "reasoning", "text": "hmm"}})
    assert len(p.all("renderTurn")) == renders
    turn = vm(p)["id"]
    assert p.last("appendReasoning") == {"turn": turn, "key": "stage:0", "call": 2,
                                         "channel": "reasoning", "text": "hmm"}
    b._render()
    assert vm(p)["stages"][0]["reasoning"] == [{"call": 2, "reasoning": "hmm", "prose": ""}]


PNG = "data:image/png;base64,iVBORw0KGgo="


def test_images_go_to_the_turn_and_into_the_transcript(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send(" like this ", json.dumps([PNG]))
    assert p.last("addUser") == {"text": "like this", "images": [PNG]}
    b.gate(wait_gate(qtbot, p)["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    say(qtbot, b, "taller")
    assert rec["turns"] == ["like this", "taller"]
    assert rec["images"] == [[PNG], None]
    b.ready()
    users = [i for i in p.last("replay")["items"] if i["type"] == "user"]
    assert users == [{"type": "user", "text": "like this", "images": [PNG]},
                     {"type": "user", "text": "taller"}]


def test_images_alone_are_sent_with_a_stock_request(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("", json.dumps([PNG]))
    assert p.last("addUser") == {"text": "", "images": [PNG]}
    wait_gate(qtbot, p)
    assert rec["turns"] == ["Build what the attached image(s) show."]


@pytest.mark.parametrize("images", [
    "not json", json.dumps(PNG), json.dumps([PNG] * 11), json.dumps([1]),
    json.dumps(["data:image/svg+xml;base64,PHN2Zz4="]),
    json.dumps(["data:text/html;base64,PGI+"]),
    json.dumps(['data:image/png;base64,AA"onerror=x']),
    json.dumps(["data:image/png;base64,aGVsbG8="]),
])
def test_bad_images_are_refused_with_a_note(bridges, cfg_path, images):
    b, p = make(bridges, cfg_path, {})
    b.probe()
    b.send("x", images)
    assert b.worker is None and p.last("addUser") is None
    assert p.last("addNote")["text"].startswith("Message not sent:")


def test_images_past_the_size_budget_are_refused(bridges, cfg_path, monkeypatch):
    from salome_agent import cli

    monkeypatch.setattr(cli, "MAX_IMAGE_BYTES", 10)
    b, p = make(bridges, cfg_path, {})
    b.probe()
    b.send("x", json.dumps([PNG, PNG]))
    assert "MB of images" in p.last("addNote")["text"] and b.worker is None


def test_an_image_is_labelled_by_its_content(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x", json.dumps(["data:image/png;base64,/9j/4A=="]))   # a JPEG saved as .png
    assert p.last("addUser")["images"] == ["data:image/jpeg;base64,/9j/4A=="]
    wait_gate(qtbot, p)
    assert rec["images"] == [["data:image/jpeg;base64,/9j/4A=="]]


def test_nothing_to_send_without_text_or_images(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    b.probe()
    b.send("   ", "[]")
    assert b.worker is None and p.last("addUser") is None and p.last("addNote") is None
