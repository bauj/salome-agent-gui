import threading

from salome_agent.conversation import TurnResult

from salome_agent_gui.conversation_worker import ConversationWorker


class FakeConv:
    def __init__(self, gate_payload=None, raises=None, ends=False):
        self.degraded = False
        self.ended = False
        self.calls = []
        self.gate_payload = gate_payload
        self.raises = raises
        self.ends = ends
        self.decision = None
        self.cancelled_at_start = None

    def turn(self, text, *, images=None, on_event, on_gate, cancel):
        self.calls.append(("turn", text))
        self.images = images
        self.cancelled_at_start = cancel.is_set()
        if self.raises:
            exc, self.raises = self.raises, None
            raise exc
        on_event({"kind": "turn_start", "run_id": "r", "data": {"turn": 0, "text": text}})
        if self.gate_payload is not None:
            self.decision = on_gate(self.gate_payload)
        if self.ends:
            self.ended = True
            return TurnResult("ended", "session gone", {})
        return TurnResult("ok", f"did {text}", {})

    def undo(self):
        self.calls.append(("undo", None))
        return TurnResult("ok", "undone back to turn 0", {})

    def redo(self):
        self.calls.append(("redo", None))
        return TurnResult("ok", "redone up to turn 1", {})

    def rebuild(self):
        self.calls.append(("rebuild", None))
        self.degraded = False
        return TurnResult("ok", "rebuilt 3 node(s)", {})


def opener(conv, rec):
    def open_fn(config, run_id, *, batch, verbose):
        rec["opened"] = rec.get("opened", 0) + 1
        rec.update(config=config, run_id=run_id, batch=batch, verbose=verbose)
        return conv, lambda: rec.__setitem__("closed", True)
    return open_fn


def start(qtbot, conv, rec, **kw):
    w = ConversationWorker({"k": 1}, open_fn=opener(conv, rec), **kw)
    done = []
    w.turn_done.connect(done.append)
    w.start()
    return w, done


def test_turns_run_in_order_on_one_conversation(qtbot):
    conv, rec = FakeConv(), {}
    w, done = start(qtbot, conv, rec, batch=True, verbose=2)
    w.submit("make a box")
    w.submit("make it taller")
    qtbot.waitUntil(lambda: len(done) == 2, timeout=3000)
    assert conv.calls == [("turn", "make a box"), ("turn", "make it taller")]
    assert rec["opened"] == 1 and rec["run_id"] == w.run_id
    assert rec["batch"] is True and rec["verbose"] == 2 and rec["config"] == {"k": 1}
    assert done[1] == {"command": "turn", "status": "ok", "message": "did make it taller",
                       "degraded": False, "ended": False}
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_images_reach_the_conversation_and_none_means_no_images(qtbot):
    conv, rec = FakeConv(), {}
    w, done = start(qtbot, conv, rec)
    w.submit("like this", ["data:image/png;base64,AAAA"])
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    assert conv.images == ["data:image/png;base64,AAAA"]
    w.submit("taller")
    qtbot.waitUntil(lambda: len(done) == 2, timeout=3000)
    assert conv.images is None
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_turn_events_are_forwarded(qtbot):
    conv, rec = FakeConv(), {}
    w, done = start(qtbot, conv, rec)
    got = []
    w.event.connect(got.append)
    w.submit("x")
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    assert got[0]["kind"] == "turn_start"
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_undo_redo_rebuild_dispatch(qtbot):
    conv, rec = FakeConv(), {}
    w, done = start(qtbot, conv, rec)
    w.undo()
    w.redo()
    w.rebuild()
    qtbot.waitUntil(lambda: len(done) == 3, timeout=3000)
    assert [c for c, _ in conv.calls] == ["undo", "redo", "rebuild"]
    assert [d["command"] for d in done] == ["undo", "redo", "rebuild"]
    assert done[0]["message"] == "undone back to turn 0"
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_gate_blocks_until_answered(qtbot):
    conv, rec = FakeConv(gate_payload={"plan": []}), {}
    w, done = start(qtbot, conv, rec)
    w.gate.connect(lambda payload: w.answer_gate({"action": "approve"}))
    w.submit("x")
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    assert conv.decision == {"action": "approve"}
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_stop_aborts_pending_gate_and_keeps_the_conversation(qtbot):
    conv, rec = FakeConv(gate_payload={"plan": []}), {}
    w, done = start(qtbot, conv, rec)
    w.submit("x")
    qtbot.waitUntil(w.gate_pending, timeout=3000)
    w.stop()
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    assert conv.decision == {"action": "abort"}
    assert not w.isFinished()
    conv.gate_payload = None
    w.submit("y")
    qtbot.waitUntil(lambda: len(done) == 2, timeout=3000)
    assert conv.calls[-1] == ("turn", "y")
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_submit_clears_a_stale_cancel(qtbot):
    conv, rec = FakeConv(), {}
    w, done = start(qtbot, conv, rec)
    w.stop()
    w.submit("x")
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    assert conv.cancelled_at_start is False
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_exception_in_a_command_is_fatal_but_the_worker_lives(qtbot):
    conv, rec = FakeConv(raises=RuntimeError("bug")), {}
    w, done = start(qtbot, conv, rec)
    got = []
    w.event.connect(got.append)
    w.submit("x")
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    assert done[0]["status"] == "failed" and "RuntimeError: bug" in done[0]["message"]
    qtbot.waitUntil(lambda: any(e["kind"] == "fatal" for e in got), timeout=3000)
    w.submit("y")
    qtbot.waitUntil(lambda: len(done) == 2, timeout=3000)
    assert done[1]["status"] == "ok"
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)


def test_open_failure_is_fatal_and_ends_the_worker(qtbot):
    from salome_agent.server_conn import ServerUnavailable

    def open_fn(config, run_id, *, batch, verbose):
        raise ServerUnavailable("poisoned")

    w = ConversationWorker({}, open_fn=open_fn)
    got, done = [], []
    w.event.connect(got.append)
    w.turn_done.connect(done.append)
    w.submit("x")
    w.start()
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    qtbot.waitUntil(w.isFinished, timeout=3000)
    assert done[0]["ended"] is True and done[0]["command"] == "turn"
    qtbot.waitUntil(lambda: bool(got), timeout=3000)
    assert got[0]["kind"] == "fatal"
    assert got[0]["data"]["message"].startswith("ServerUnavailable")


def test_ended_conversation_ends_the_worker_and_closes_the_client(qtbot):
    conv, rec = FakeConv(ends=True), {}
    w, done = start(qtbot, conv, rec)
    w.submit("x")
    qtbot.waitUntil(lambda: len(done) == 1, timeout=3000)
    qtbot.waitUntil(w.isFinished, timeout=3000)
    assert done[0]["ended"] is True and rec.get("closed") is True


def test_close_closes_the_client(qtbot):
    conv, rec = FakeConv(), {}
    w, done = start(qtbot, conv, rec)
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)
    assert rec.get("closed") is True


def test_close_during_a_gate_aborts_it(qtbot):
    conv, rec = FakeConv(gate_payload={"plan": []}), {}
    w, done = start(qtbot, conv, rec)
    w.submit("x")
    qtbot.waitUntil(w.gate_pending, timeout=3000)
    w.close()
    qtbot.waitUntil(w.isFinished, timeout=3000)
    assert conv.decision == {"action": "abort"} and rec.get("closed") is True
