from salome_agent_gui.timeline import Note, RunView, render_note, render_run, render_user

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


def test_fatal_run_that_finishes_skips_done_but_keeps_report_link():
    v = RunView()
    v.apply(ev("plan", stages=PLAN[:1]))
    v.apply(ev("fatal", message="LLM endpoint down"))
    v.apply(ev("report", result_py=None, report_md="/w/r1/report.md", text="# r"))
    md = render_run(v)
    assert v.finished and not v.aborted
    assert "LLM endpoint down" in md
    assert "Done." not in md
    assert "(file:///w/r1/report.md)" in md


def test_fatal_run_with_no_paths_emits_no_empty_links_line():
    v = RunView()
    v.apply(ev("fatal", message="boom"))
    v.apply(ev("report", result_py=None, report_md=None, text="# r"))
    md = render_run(v)
    assert md.rstrip("\n").splitlines()[-1] == "**Run failed:** boom"


def test_event_for_unknown_index_extends_rows():
    v = RunView()
    v.apply(ev("stage_start", index=2, module="geom", intent="late"))
    assert len(v.stages) == 3 and v.stages[2].intent == "late"


def test_user_text_cannot_inject_gate_links():
    md = render_user("[x](gate:abort) <b>")
    assert "](gate:abort)" not in md
    assert "<b>" not in md


def test_object_name_with_backtick_cannot_break_code_span():
    v = RunView()
    v.apply(ev("plan", stages=PLAN[:1]))
    v.apply(ev("stage_done", index=0, names=["x`[a](gate:abort)`"]))
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md", text="# r"))
    md = render_run(v)
    assert "`x'[a](gate:abort)'`" in md


def test_amend_turn_renders_edits_and_outcome():
    v = RunView()
    v.apply(ev("turn_start", turn=1, text="make the roof taller"))
    v.apply(ev("graph_edit", op="edit", node="n2", param="dz", old=40, new=60))
    v.apply(ev("replay", nodes=["n2", "n3", "n4"]))
    v.apply(ev("graph_edit", op="add", node="n5", new="make_box"))
    v.apply(ev("graph_edit", op="delete", old=["n6", "n7"]))
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md", text="# r"))
    v.apply(ev("turn_done", turn=1, status="ok", message="Raised the roof to 60 mm."))
    assert v.finished
    assert v.edits == ["edit n2.dz: 40 -> 60", "rebuilding 3 object(s): n2, n3, n4",
                       "added n5 (make_box)", "deleted n6, n7"]
    md = render_run(v)
    assert "- edit n2.dz: 40 -\\> 60" in md
    assert "- added n5 \\(make\\_box\\)" in md
    assert "**Done.** Raised the roof to 60 mm." in md
    assert "Objects:" not in md
    assert "(file:///w/r1/result.py)" in md


def test_turn_statuses_have_their_own_labels():
    for status, label in (("needs_input", "Question:"), ("failed", "Turn failed:"),
                          ("degraded", "Study out of sync:"), ("ended", "Session ended:")):
        v = RunView()
        v.apply(ev("turn_done", turn=0, status=status, message="m"))
        assert f"**{label}** m" in render_run(v)


def test_turn_outcome_replaces_aborted_and_fatal_lines():
    v = RunView()
    v.apply(ev("fatal", message="LLM endpoint down"))
    v.apply(ev("aborted"))
    v.apply(ev("turn_done", turn=0, status="failed", message="LLM endpoint down"))
    md = render_run(v)
    assert md.count("LLM endpoint down") == 1
    assert "aborted" not in md.lower()
    assert "**Turn failed:** LLM endpoint down" in md


def test_first_turn_keeps_its_object_list():
    v = RunView()
    v.apply(ev("plan", stages=PLAN[:1]))
    v.apply(ev("stage_done", index=0, names=["box_1"]))
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md", text="# r"))
    v.apply(ev("turn_done", turn=0, status="ok", message="done"))
    md = render_run(v)
    assert "**Done.** done" in md and "Objects: `box_1`" in md


def test_note_escapes_markdown():
    assert render_note(Note("undo: [x](gate:abort)")) == "_undo: \\[x\\]\\(gate:abort\\)_"


def test_report_usage_is_a_snapshot_not_the_live_counter():
    usage = {"calls": 8}
    v = RunView()
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md", text="",
               usage=usage))
    usage["calls"] = 17
    assert "calls=8" in render_run(v)


from salome_agent_gui.timeline import short_name

USAGE_3 = {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100, "llm_seconds": 1.5}


def test_short_name_strips_only_the_run_prefix():
    assert short_name("sa_0123456789ab_fuse_1") == "fuse_1"
    assert short_name("fuse_1") == "fuse_1"
    assert short_name("sa_xyz_fuse_1") == "sa_xyz_fuse_1"


def test_view_model_stage_times_come_from_the_clock():
    ticks = iter([100.0, 112.54])
    v = RunView(clock=lambda: next(ticks))
    v.apply(ev("plan", stages=PLAN))
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))
    s = v.to_view_model(0)["stages"][0]
    assert (s["status"], s["started_at"], s["elapsed_s"]) == ("running", 100.0, None)
    v.apply(ev("stage_done", index=0, names=["sa_0123456789ab_box_1"]))
    vm = v.to_view_model(0)
    assert vm["stages"][0]["elapsed_s"] == 12.5
    assert vm["objects"] == ["box_1"]
    assert vm["status"] == "running"


def test_view_model_shape_for_a_fresh_plan():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    assert v.to_view_model(3) == {
        "id": 3,
        "stages": [
            {"index": 0, "module": "geom", "icon": None, "intent": "two boxes", "status": "pending",
             "attempts": 0, "started_at": None, "elapsed_s": None, "error": None},
            {"index": 1, "module": "smesh", "icon": None, "intent": "mesh", "status": "pending",
             "attempts": 0, "started_at": None, "elapsed_s": None, "error": None}],
        "edits": [], "gate": None, "status": "running", "message": "", "objects": [],
        "files": {"result_py": None, "report_md": None}, "usage": None}


def test_view_model_icons_come_from_the_lookup():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    vm = v.to_view_model(0, icon_for=lambda m: f"file:///i/{m}.png")
    assert [s["icon"] for s in vm["stages"]] == ["file:///i/geom.png", "file:///i/smesh.png"]


def test_view_model_usage_is_this_turn_only():
    v = RunView(usage_base=USAGE_3)
    v.apply(ev("report", result_py=None, report_md=None, text="",
               usage={"calls": 5, "prompt_tokens": 1800, "completion_tokens": 160,
                      "llm_seconds": 4.3, "metered_calls": 5, "approx_prompt_tokens": 9}))
    assert v.to_view_model(1)["usage"] == {"calls": 2, "prompt_tokens": 800,
                                           "completion_tokens": 60, "llm_seconds": 2.8}


def test_view_model_usage_without_base_is_the_whole_count_and_none_without_report():
    v = RunView()
    assert v.to_view_model(0)["usage"] is None
    v.apply(ev("report", result_py=None, report_md=None, text="", usage=dict(USAGE_3)))
    assert v.to_view_model(0)["usage"] == USAGE_3


def test_view_model_gates():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    v.gate, v.gate_id = {"plan": PLAN}, 4
    assert v.to_view_model(0)["gate"] == {"id": 4, "kind": "plan"}
    v.apply(ev("stage_start", index=1, module="smesh", intent="mesh"))
    v.apply(ev("stage_attempt", index=1, phase="exec", ok=False, error="NETGEN failed\nline 2"))
    v.gate, v.gate_id = {"last_error": {"message": "NETGEN failed\nline 2", "offending_line": 12}}, 5
    assert v.to_view_model(0)["gate"] == {"id": 5, "kind": "stage_failed", "stage": 1,
                                          "message": "NETGEN failed\nline 2", "line": 12}
    assert v.to_view_model(0)["stages"][1]["error"] == "NETGEN failed\nline 2"
    v.gate, v.gate_id = None, None
    assert v.to_view_model(0)["gate"] is None


def test_view_model_status_and_message():
    v = RunView()
    assert v.status() == "running"
    v.apply(ev("report", result_py="/w/r.py", report_md="/w/r.md", text="", usage=None))
    assert v.status() == "ok"
    v = RunView()
    v.apply(ev("fatal", message="LLM endpoint down"))
    vm = v.to_view_model(0)
    assert (vm["status"], vm["message"]) == ("fatal", "LLM endpoint down")
    v.apply(ev("turn_done", turn=0, status="failed", message="turn failed: endpoint"))
    vm = v.to_view_model(0)
    assert (vm["status"], vm["message"]) == ("failed", "turn failed: endpoint")


def test_aborted_run_keeps_its_files():
    v = RunView()
    v.apply(ev("report", result_py="/w/r.py", report_md="/w/r.md", text="", usage=None))
    v.apply(ev("aborted"))
    vm = v.to_view_model(0)
    assert vm["status"] == "aborted"
    assert vm["files"] == {"result_py": "/w/r.py", "report_md": "/w/r.md"}


def test_view_model_edit_ops():
    v = RunView()
    v.apply(ev("graph_edit", op="edit", node="n2", param="dz", old=40, new=60))
    v.apply(ev("replay", nodes=["n2", "n3"]))
    v.apply(ev("graph_edit", op="add", node="n5", new="make_box"))
    v.apply(ev("graph_edit", op="delete", old=["n6", "n7"]))
    assert v.to_view_model(0)["edits"] == [
        {"op": "edit", "node": "n2", "param": "dz", "old": "40", "new": "60"},
        {"op": "replay", "nodes": ["n2", "n3"]},
        {"op": "add", "node": "n5", "new": "make_box"},
        {"op": "delete", "nodes": ["n6", "n7"]}]
