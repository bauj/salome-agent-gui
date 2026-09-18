from salome_agent_gui.run_worker import RunWorker


def _ev(kind):
    return {"kind": kind, "run_id": "r", "data": {}}


def make_run(events=(), gate_payload=None, raises=None):
    seen = {}

    def run(request, config, *, run_id, on_event, on_gate, cancel, batch, verbose):
        seen.update(request=request, batch=batch, verbose=verbose, run_id=run_id)
        if raises:
            raise raises
        for e in events:
            on_event(e)
        if gate_payload is not None:
            seen["decision"] = on_gate(gate_payload)
        return "RESULT"

    return run, seen


def test_events_then_done(qtbot):
    run, seen = make_run([_ev("plan"), _ev("report")])
    w = RunWorker("make a box", {}, batch=True, verbose=1, run_fn=run)
    got = []
    w.event.connect(got.append)
    with qtbot.waitSignal(w.done, timeout=3000) as blk:
        w.start()
    assert blk.args == ["RESULT"]
    qtbot.waitUntil(lambda: len(got) == 2)
    assert [e["kind"] for e in got] == ["plan", "report"]
    assert seen["request"] == "make a box" and seen["batch"] is True and seen["verbose"] == 1
    assert seen["run_id"] == w.run_id


def test_gate_blocks_until_answered(qtbot):
    run, seen = make_run(gate_payload={"plan": []})
    w = RunWorker("x", {}, run_fn=run)
    w.gate.connect(lambda payload: w.answer_gate({"action": "approve"}))
    with qtbot.waitSignal(w.done, timeout=3000):
        w.start()
    assert seen["decision"] == {"action": "approve"}


def test_stop_answers_a_pending_gate_with_abort(qtbot):
    run, seen = make_run(gate_payload={"last_error": {"message": "x"}})
    w = RunWorker("x", {}, run_fn=run)
    with qtbot.waitSignal(w.gate, timeout=3000):
        w.start()
    qtbot.waitUntil(w.gate_pending)
    with qtbot.waitSignal(w.done, timeout=3000):
        w.stop()
    assert seen["decision"] == {"action": "abort"}
    assert w.cancel.is_set()


def test_exception_becomes_fatal_event(qtbot):
    run, _ = make_run(raises=RuntimeError("no server"))
    w = RunWorker("x", {}, run_fn=run)
    got = []
    w.event.connect(got.append)
    with qtbot.waitSignal(w.done, timeout=3000) as blk:
        w.start()
    assert blk.args == [None]
    qtbot.waitUntil(lambda: bool(got))
    assert got[0]["kind"] == "fatal"
    assert "no server" in got[0]["data"]["message"]


def test_cancel_before_start_prevents_gate_signal(qtbot):
    run, seen = make_run(gate_payload={"plan": []})
    w = RunWorker("x", {}, run_fn=run)
    gate_signals = []
    w.gate.connect(lambda payload: gate_signals.append(payload))
    w.cancel.set()
    with qtbot.waitSignal(w.done, timeout=3000):
        w.start()
    w.wait()
    assert seen["decision"] == {"action": "abort"}
    assert len(gate_signals) == 0
