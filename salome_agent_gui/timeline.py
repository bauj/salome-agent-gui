import re
import time
from dataclasses import dataclass, field
from typing import Callable

_RUN_PREFIX = re.compile(r"^sa_[0-9a-f]{12}_")
USAGE_KEYS = ("calls", "prompt_tokens", "completion_tokens", "llm_seconds")


def short_name(name) -> str:
    return _RUN_PREFIX.sub("", str(name))


@dataclass
class StageRow:
    index: int
    module: str
    intent: str
    status: str = "pending"
    attempts: int = 0
    error: str | None = None
    started_at: float | None = None
    elapsed_s: float | None = None
    objects: list[str] = field(default_factory=list)


@dataclass
class RunView:
    run_id: str | None = None
    stages: list[StageRow] = field(default_factory=list)
    gate: dict | None = None
    objects: list[str] = field(default_factory=list)
    result_py: str | None = None
    report_md: str | None = None
    usage: dict | None = None
    fatal: str | None = None
    aborted: bool = False
    finished: bool = False
    edits: list[str] = field(default_factory=list)
    turn_status: str | None = None
    turn_message: str | None = None
    gate_id: int | None = None
    edit_ops: list[dict] = field(default_factory=list)
    # "planner" / "stage:<i>" / "edit" -> [{"call", "reasoning", "prose"}]
    reasoning: dict[str, list[dict]] = field(default_factory=dict)
    usage_base: dict | None = None
    clock: Callable[[], float] = field(default=time.time, repr=False)
    batch: bool = False
    # The engine sends stage_start only once the stage's work is done, so a
    # stage's clock starts when the engine moved on to it: plan approved (or
    # the plan itself in batch mode, which has no gate) or previous stage over.
    _next_start: float | None = field(default=None, repr=False)

    def mark_resumed(self) -> None:
        self._next_start = self.clock()

    def _row(self, i: int, module: str = "?", intent: str = "") -> StageRow:
        while len(self.stages) <= i:
            self.stages.append(StageRow(len(self.stages), module, intent))
        return self.stages[i]

    def apply(self, event: dict) -> None:
        kind, d = event["kind"], event.get("data") or {}
        self.run_id = event.get("run_id") or self.run_id
        if kind == "plan":
            self.stages = [StageRow(i, s.get("module", "?"), s.get("intent", ""))
                           for i, s in enumerate(d["stages"])]
            self._next_start = self.clock() if self.batch else None
        elif kind == "stage_start":
            r = self._row(d["index"], d.get("module", "?"), d.get("intent", ""))
            r.status = "running"
            r.started_at = self._next_start if self._next_start is not None else self.clock()
            self._next_start = None
        elif kind == "stage_attempt":
            r = self._row(d["index"])
            r.attempts += 1
            r.status, r.error = ("running", None) if d.get("ok") else ("failed", d.get("error"))
        elif kind == "stage_done":
            r = self._row(d["index"])
            r.status, r.error = "ok", None
            now = self.clock()
            if r.started_at is not None:
                r.elapsed_s = round(now - r.started_at, 1)
            r.objects = list(d.get("names") or [])
            self.objects.extend(r.objects)
            self._next_start = now
        elif kind == "stage_skipped":
            self._row(d["index"]).status = "skipped"
            self._next_start = self.clock()
        elif kind == "report":
            self.result_py, self.report_md = d.get("result_py"), d.get("report_md")
            self.usage = dict(d["usage"]) if d.get("usage") else None
            self.finished = True
        elif kind == "graph_edit":
            self.edits.append(_edit_line(d))
            self.edit_ops.append(_edit_op(d))
        elif kind == "replay":
            nodes = [str(n) for n in d.get("nodes") or []]
            self.edits.append(f"rebuilding {len(nodes)} object(s): {', '.join(nodes)}")
            self.edit_ops.append({"op": "replay", "nodes": nodes})
        elif kind == "turn_done":
            self.turn_status, self.turn_message = d.get("status"), d.get("message")
            if d.get("usage"):                  # totals so far, cancelled turns included
                self.usage = dict(d["usage"])
            self.finished = True
        elif kind == "reasoning":
            calls = self.reasoning.setdefault(reasoning_key(d), [])
            if not calls or calls[-1]["call"] != d.get("call"):
                calls.append({"call": d.get("call"), "reasoning": "", "prose": ""})
            channel = "prose" if d.get("channel") == "prose" else "reasoning"
            calls[-1][channel] += str(d.get("text") or "")
        elif kind == "fatal":
            self.fatal = d.get("message")
        elif kind == "aborted":
            self.aborted = True
            self.finished = True

    def status(self) -> str:
        if self.turn_status is not None:
            return self.turn_status
        if self.aborted:
            return "aborted"
        if self.fatal:
            return "fatal"
        if self.finished:
            return "ok"
        return "running"

    def turn_usage(self) -> dict | None:
        """This turn's LLM usage: the engine reports conversation totals."""
        if not self.usage:
            return None
        base = self.usage_base or {}
        out = {}
        for k in USAGE_KEYS:
            v = self.usage.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                delta = v - (base.get(k) or 0)
                out[k] = round(delta, 1) if isinstance(delta, float) else delta
        return out or None

    def _gate_view(self) -> dict | None:
        if self.gate is None or self.gate_id is None:
            return None
        if "plan" in self.gate:
            return {"id": self.gate_id, "kind": "plan"}
        err = self.gate.get("last_error") or {}
        failing = [s.index for s in self.stages if s.status in ("failed", "running")]
        return {"id": self.gate_id, "kind": "stage_failed",
                "stage": failing[-1] if failing else None,
                "message": str(err.get("message") or ""), "line": err.get("offending_line")}

    def _moved_on_to(self) -> int | None:
        """Index of the stage the engine is working on but has not reported yet."""
        if (self._next_start is None or self.gate is not None or self.status() != "running"
                or any(s.status in ("running", "failed") for s in self.stages)):
            return None
        return next((s.index for s in self.stages if s.status == "pending"), None)

    def _stage_view(self, s: StageRow, icon_for) -> dict:
        status, started_at = s.status, s.started_at
        if s.index == self._moved_on_to():
            status, started_at = "running", self._next_start
        elif status == "running" and self.status() != "running":
            status = "stopped"                  # the turn ended under it (Stop, fatal)
        return {"index": s.index, "module": s.module, "icon": icon_for(s.module),
                "intent": s.intent, "status": status, "attempts": s.attempts,
                "started_at": started_at, "elapsed_s": s.elapsed_s, "error": s.error,
                "objects": [short_name(n) for n in s.objects],
                "reasoning": _calls(self.reasoning.get(f"stage:{s.index}"))}

    def to_view_model(self, turn_id: int, icon_for=lambda module: None) -> dict:
        return {
            "id": turn_id,
            "stages": [self._stage_view(s, icon_for) for s in self.stages],
            "edits": [dict(e) for e in self.edit_ops],
            "gate": self._gate_view(),
            "status": self.status(),
            "message": self.turn_message or self.fatal or "",
            "objects": [short_name(n) for n in self.objects],
            "files": {"result_py": self.result_py, "report_md": self.report_md},
            "usage": self.turn_usage(),
            "reasoning": {k: _calls(v) for k, v in self.reasoning.items()
                          if not k.startswith("stage:")},
        }


def reasoning_key(d: dict) -> str:
    if d.get("source") == "stage":
        return f"stage:{d.get('index')}"
    return "edit" if d.get("source") == "edit" else "planner"


def _calls(calls) -> list[dict]:
    return [dict(c) for c in calls or []]


def _edit_line(d: dict) -> str:
    if d.get("op") == "edit":
        return f"edit {d.get('node')}.{d.get('param')}: {d.get('old')} -> {d.get('new')}"
    if d.get("op") == "delete":
        return f"deleted {', '.join(str(n) for n in d.get('old') or [])}"
    return f"added {d.get('node')} ({d.get('new')})"


def _edit_op(d: dict) -> dict:
    if d.get("op") == "edit":
        return {"op": "edit", "node": str(d.get("node")), "param": str(d.get("param")),
                "old": str(d.get("old")), "new": str(d.get("new"))}
    if d.get("op") == "delete":
        return {"op": "delete", "nodes": [str(n) for n in d.get("old") or []]}
    return {"op": "add", "node": str(d.get("node")), "new": str(d.get("new"))}
