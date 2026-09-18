from salome_agent_gui.timeline import RunView, render_run, render_user

PLAN = [{"module": "geom", "intent": "two boxes"}, {"module": "smesh", "intent": "mesh"}]


def ev(kind, **data):
    return {"kind": kind, "run_id": "r1", "data": data}


def test_plan_then_stage_lifecycle():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    assert [(s.module, s.status) for s in v.stages] == [("geom", "pending"), ("smesh", "pending")]
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))
    assert v.stages[0].status == "running"
    v.apply(ev("stage_attempt", index=0, phase="exec", ok=False, error="boom"))
    assert (v.stages[0].status, v.stages[0].attempts, v.stages[0].error) == ("failed", 1, "boom")
    v.apply(ev("stage_attempt", index=0, phase="exec", ok=True, error=None))
    assert (v.stages[0].status, v.stages[0].error) == ("running", None)
    v.apply(ev("stage_done", index=0, names=["box_1", "box_2"]))
    v.apply(ev("stage_skipped", index=1))
    assert [s.status for s in v.stages] == ["ok", "skipped"]
    assert v.objects == ["box_1", "box_2"]


def test_report_finishes_and_renders_links_and_usage():
    v = RunView()
    v.apply(ev("plan", stages=PLAN[:1]))
    v.apply(ev("stage_done", index=0, names=["box_1"]))
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md",
               text="# r", usage={"calls": 3, "prompt_tokens": 1200, "note": "x"}))
    assert v.finished
    md = render_run(v)
    assert "(file:///w/r1/result.py)" in md and "(file:///w/r1/report.md)" in md
    assert "`box_1`" in md
    assert "calls=3" in md and "prompt_tokens=1200" in md and "note" not in md


def test_plan_gate_renders_three_actions_and_clears():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    v.gate = {"plan": PLAN}
    md = render_run(v)
    for href in ("gate:approve", "gate:edit", "gate:abort"):
        assert f"({href})" in md
    v.gate = None
    assert "gate:" not in render_run(v)


def test_retry_gate_renders_error_and_actions():
    v = RunView()
    v.gate = {"last_error": {"message": "fillet failed", "offending_line": 7}}
    md = render_run(v)
    assert "fillet failed" in md and "line 7" in md
    for href in ("gate:hint", "gate:skip", "gate:abort"):
        assert f"({href})" in md


def test_fatal_and_aborted_render():
    v = RunView()
    v.apply(ev("fatal", message="LLM endpoint returned HTTP 502"))
    assert "HTTP 502" in render_run(v)
    v.apply(ev("aborted"))
    assert v.finished and "aborted" in render_run(v).lower()


def test_event_for_unknown_index_extends_rows():
    v = RunView()
    v.apply(ev("stage_start", index=2, module="geom", intent="late"))
    assert len(v.stages) == 3 and v.stages[2].intent == "late"


def test_user_text_cannot_inject_gate_links():
    md = render_user("[x](gate:abort) <b>")
    assert "](gate:abort)" not in md
    assert "<b>" not in md
