from salome_agent_gui.timeline import RunView

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


def test_event_for_unknown_index_extends_rows():
    v = RunView()
    v.apply(ev("stage_start", index=2, module="geom", intent="late"))
    assert len(v.stages) == 3 and v.stages[2].intent == "late"


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


def test_report_usage_is_a_snapshot_not_the_live_counter():
    usage = {"calls": 8}
    v = RunView()
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md", text="",
               usage=usage))
    usage["calls"] = 17
    assert v.to_view_model(0)["usage"] == {"calls": 8}


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
             "attempts": 0, "started_at": None, "elapsed_s": None, "error": None, "objects": [],
             "reasoning": []},
            {"index": 1, "module": "smesh", "icon": None, "intent": "mesh", "status": "pending",
             "attempts": 0, "started_at": None, "elapsed_s": None, "error": None, "objects": [],
             "reasoning": []}],
        "edits": [], "gate": None, "status": "running", "message": "", "objects": [],
        "files": {"result_py": None, "report_md": None}, "usage": None, "reasoning": {}}


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


def test_stage_clock_starts_when_the_previous_stage_ends():
    # the engine sends stage_start only after the stage's work is done
    ticks = iter([100.0, 151.0, 181.0])
    v = RunView(clock=lambda: next(ticks), batch=True)                 # no approval gate
    v.apply(ev("plan", stages=PLAN))                                    # 100
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))
    v.apply(ev("stage_done", index=0, names=["b1"]))                   # 151
    v.apply(ev("stage_start", index=1, module="smesh", intent="mesh"))
    v.apply(ev("stage_done", index=1, names=["m1"]))                   # 181
    stages = v.to_view_model(0)["stages"]
    assert [(s["started_at"], s["elapsed_s"]) for s in stages] == [(100.0, 51.0), (151.0, 30.0)]


def test_approving_the_plan_restarts_the_stage_clock():
    ticks = iter([130.0, 160.0])
    v = RunView(clock=lambda: next(ticks))
    v.apply(ev("plan", stages=PLAN))
    v.mark_resumed()                                                    # 130: plan approved
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))
    v.apply(ev("stage_done", index=0, names=[]))                       # 160
    s = v.to_view_model(0)["stages"][0]
    assert (s["started_at"], s["elapsed_s"]) == (130.0, 30.0)


def test_next_stage_shows_running_before_its_late_stage_start():
    ticks = iter([130.0])
    v = RunView(clock=lambda: next(ticks))
    v.apply(ev("plan", stages=PLAN))
    v.gate, v.gate_id = {"plan": PLAN}, 1
    assert [s["status"] for s in v.to_view_model(0)["stages"]] == ["pending", "pending"]
    v.gate, v.gate_id = None, None
    v.mark_resumed()
    stages = v.to_view_model(0)["stages"]
    assert [(s["status"], s["started_at"]) for s in stages] == [("running", 130.0), ("pending", None)]


def test_finished_turn_shows_no_guessed_running_stage():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    v.apply(ev("aborted"))
    assert [s["status"] for s in v.to_view_model(0)["stages"]] == ["pending", "pending"]


def test_each_stage_lists_the_objects_it_made():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))
    v.apply(ev("stage_done", index=0, names=["sa_0123456789ab_box_1", "sa_0123456789ab_box_2"]))
    stages = v.to_view_model(0)["stages"]
    assert stages[0]["objects"] == ["box_1", "box_2"] and stages[1]["objects"] == []


def test_a_stage_still_running_when_the_turn_ends_shows_stopped():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    v.mark_resumed()
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))   # arrives on Stop
    v.apply(ev("aborted"))
    v.apply(ev("turn_done", turn=0, status="failed", message="turn cancelled"))
    assert [s["status"] for s in v.to_view_model(0)["stages"]] == ["stopped", "pending"]


def test_a_running_stage_mid_turn_is_not_stopped():
    v = RunView()
    v.apply(ev("plan", stages=PLAN))
    v.apply(ev("stage_start", index=0, module="geom", intent="two boxes"))
    assert v.to_view_model(0)["stages"][0]["status"] == "running"


def test_turn_done_usage_counts_for_a_turn_with_no_report():
    v = RunView(usage_base=USAGE_3)
    v.apply(ev("aborted"))
    v.apply(ev("turn_done", turn=1, status="failed", message="turn cancelled",
               usage={"calls": 5, "prompt_tokens": 1800, "completion_tokens": 160,
                      "llm_seconds": 4.3}))
    assert v.to_view_model(1)["usage"] == {"calls": 2, "prompt_tokens": 800,
                                           "completion_tokens": 60, "llm_seconds": 2.8}


def _r(source, call, channel, text, index=None):
    return ev("reasoning", source=source, index=index, call=call, channel=channel, text=text)


def test_reasoning_blocks_by_source_and_call():
    v = RunView()
    v.apply(_r("planner", 1, "reasoning", "plan "))
    v.apply(_r("planner", 1, "reasoning", "it"))
    v.apply(ev("plan", stages=PLAN))
    v.apply(_r("stage", 2, "reasoning", "box?", index=0))
    v.apply(_r("stage", 2, "prose", "Making a box.", index=0))
    v.apply(_r("stage", 3, "prose", "Done.", index=0))
    vm = v.to_view_model(1)
    assert vm["reasoning"] == {"planner": [{"call": 1, "reasoning": "plan it", "prose": ""}]}
    assert vm["stages"][0]["reasoning"] == [
        {"call": 2, "reasoning": "box?", "prose": "Making a box."},
        {"call": 3, "reasoning": "", "prose": "Done."}]
    assert vm["stages"][1]["reasoning"] == []


def test_edit_turn_reasoning_is_turn_level():
    v = RunView()
    v.apply(_r("edit", 1, "prose", "Widening the box."))
    assert v.to_view_model(1)["reasoning"] == {
        "edit": [{"call": 1, "reasoning": "", "prose": "Widening the box."}]}
