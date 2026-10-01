import json
import time

from salome_agent.conversation import TurnResult

CFG = {"llm": {"base_url": "http://h/v1", "model": "m", "api_key": "secret"},
       "salome": {"root": "/x"}, "policy": {"on_stage_failure": "abort",
                                            "tool_selection": "hints"}}
PLAN = [{"module": "geom", "intent": "box", "params": {}, "inputs": []}]


def write_cfg(tmp_path, cfg=None):
    p = tmp_path / "salome-agent.json"
    p.write_text(json.dumps(cfg or CFG))
    return p


class FakeConv:
    """First turn: a gate (rec["first_gate"], default a plan gate), then one
    stage. Later turns: one amend edit. Usage grows like the engine's
    conversation totals."""

    def __init__(self, rec):
        self.rec = rec
        self.degraded = False
        self.ended = False
        self.release = None
        self.next_status = None
        self.n_turns = 0

    def turn(self, text, *, images=None, on_event, on_gate, cancel):
        rec = self.rec
        rec.setdefault("turns", []).append(text)
        rec.setdefault("images", []).append(images)
        n, self.n_turns = self.n_turns, self.n_turns + 1

        def ev(kind, **data):
            on_event({"kind": kind, "run_id": "r", "data": data})

        usage = {"calls": 3 * (n + 1), "prompt_tokens": 1000 * (n + 1),
                 "completion_tokens": 100 * (n + 1), "llm_seconds": 1.5 * (n + 1)}

        ev("turn_start", turn=n, text=text)
        if self.release is not None:
            while not self.release.is_set():
                time.sleep(0.01)
        if self.next_status is not None:
            status, self.next_status = self.next_status, None
            self.degraded = status == "degraded"
            self.ended = status == "ended"
            ev("turn_done", turn=n, status=status, message=f"{status} happened", usage=usage)
            return TurnResult(status, f"{status} happened", {})
        if n == 0:
            ev("plan", stages=PLAN)
            rec["decision"] = on_gate(rec.get("first_gate", {"plan": PLAN}))
            if rec["decision"]["action"] not in ("approve", "edit", "hint", "skip"):
                ev("aborted")
                ev("turn_done", turn=n, status="failed", message="turn cancelled", usage=usage)
                return TurnResult("failed", "turn cancelled", {})
            ev("stage_start", index=0, module="geom", intent="box")
            ev("stage_done", index=0, names=["sa_0123456789ab_box_1"])
        else:
            ev("graph_edit", op="edit", node="n1", param="dz", old=40, new=60)
            ev("replay", nodes=["n1"])
        ev("report", result_py="/w/result.py", report_md="/w/report.md", text="", usage=usage)
        ev("turn_done", turn=n, status="ok", message=f"did {text}", usage=usage)
        return TurnResult("ok", f"did {text}", {})

    def undo(self):
        self.rec["undo"] = True
        return TurnResult("ok", "undone back to turn 0", {})

    def redo(self):
        return TurnResult("ok", "redone up to turn 1", {})

    def rebuild(self):
        self.degraded = False
        self.rec["rebuilt"] = self.rec.get("rebuilt", 0) + 1
        return TurnResult("ok", "rebuilt 1 node(s)", {})


def opener(rec):
    def open_fn(config, run_id, *, batch, verbose):
        rec["opened"] = rec.get("opened", 0) + 1
        rec.update(config=config, batch=batch, verbose=verbose)
        rec["conv"] = FakeConv(rec)
        return rec["conv"], lambda: rec.__setitem__("closed", rec.get("closed", 0) + 1)
    return open_fn
