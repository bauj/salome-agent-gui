from dataclasses import dataclass, field
from pathlib import Path
import re
import time
from typing import Callable

_RUN_PREFIX = re.compile(r"^sa_[0-9a-f]{12}_")
USAGE_KEYS = ("calls", "prompt_tokens", "completion_tokens", "llm_seconds")


def short_name(name) -> str:
    return _RUN_PREFIX.sub("", str(name))

ICON = {"pending": "·", "running": "⟳", "ok": "✓", "failed": "✗", "skipped": "↷"}
STATUS_LABEL = {"ok": "Done.", "needs_input": "Question:", "failed": "Turn failed:",
                "degraded": "Study out of sync:", "ended": "Session ended:"}


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
    usage_base: dict | None = None
    clock: Callable[[], float] = field(default=time.time, repr=False)

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
        elif kind == "stage_start":
            r = self._row(d["index"], d.get("module", "?"), d.get("intent", ""))
            r.status = "running"
            r.started_at = self.clock()
        elif kind == "stage_attempt":
            r = self._row(d["index"])
            r.attempts += 1
            r.status, r.error = ("running", None) if d.get("ok") else ("failed", d.get("error"))
        elif kind == "stage_done":
            r = self._row(d["index"])
            r.status, r.error = "ok", None
            if r.started_at is not None:
                r.elapsed_s = round(self.clock() - r.started_at, 1)
            self.objects.extend(d.get("names") or [])
        elif kind == "stage_skipped":
            self._row(d["index"]).status = "skipped"
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
            self.finished = True
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

    def to_view_model(self, turn_id: int, icon_for=lambda module: None) -> dict:
        return {
            "id": turn_id,
            "stages": [{"index": s.index, "module": s.module, "icon": icon_for(s.module),
                        "intent": s.intent, "status": s.status, "attempts": s.attempts,
                        "started_at": s.started_at, "elapsed_s": s.elapsed_s, "error": s.error}
                       for s in self.stages],
            "edits": [dict(e) for e in self.edit_ops],
            "gate": self._gate_view(),
            "status": self.status(),
            "message": self.turn_message or self.fatal or "",
            "objects": [short_name(n) for n in self.objects],
            "files": {"result_py": self.result_py, "report_md": self.report_md},
            "usage": self.turn_usage(),
        }


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


@dataclass
class Note:
    text: str


def _escape(text: str) -> str:
    for ch in "\\`*_[]()<>#":
        text = text.replace(ch, "\\" + ch)
    return text


def _code(text: str) -> str:
    return "`" + text.replace("`", "'") + "`"


def render_user(text: str) -> str:
    return f"**You:** {_escape(text)}"


def render_note(note: Note) -> str:
    return f"_{_escape(note.text)}_"


def _file_link(label: str, path: str) -> str:
    return f"[{label}]({Path(path).as_uri()})"


def _links_and_usage(view: RunView, lines: list[str]) -> None:
    links = [_file_link(n, p) for n, p in (("result.py", view.result_py),
                                           ("report.md", view.report_md)) if p]
    if links:
        lines.append("")
        lines.append(" · ".join(links))
    if view.usage:
        nums = ", ".join(f"{k}={v}" for k, v in view.usage.items()
                         if isinstance(v, (int, float)) and not isinstance(v, bool))
        lines.append("")
        lines.append(f"_LLM usage: {nums}_")


def render_run(view: RunView) -> str:
    lines = ["**Agent**", ""]
    for s in view.stages:
        tries = f" (attempt {s.attempts})" if s.attempts > 1 else ""
        lines.append(f"{s.index + 1}. {ICON.get(s.status, '?')} {_code(s.module)} "
                     f"{_escape(s.intent)}{tries}")
        if s.error and s.status == "failed":
            lines.append(f"    ↳ {_escape(s.error)}")
    if view.edits:
        if view.stages:
            lines.append("")
        lines.extend(f"- {_escape(e)}" for e in view.edits)
    lines.append("")
    if view.gate and "plan" in view.gate:
        lines.append("**Approve this plan?** [Approve](gate:approve) · "
                     "[Edit](gate:edit) · [Abort](gate:abort)")
    elif view.gate and "last_error" in view.gate:
        err = view.gate["last_error"] or {}
        where = f" (line {err['offending_line']})" if err.get("offending_line") else ""
        lines.append(f"**Stage failed{where}:** {_escape(err.get('message') or '')}")
        lines.append("")
        lines.append("[Hint](gate:hint) · [Skip stage](gate:skip) · [Abort run](gate:abort)")
    if view.turn_status is not None:
        label = STATUS_LABEL.get(view.turn_status, view.turn_status)
        lines.append(f"**{label}** {_escape(view.turn_message or '')}")
        if view.objects:
            lines.append("")
            lines.append("Objects: " + ", ".join(_code(n) for n in view.objects))
        _links_and_usage(view, lines)
        return "\n".join(lines)
    if view.fatal:
        lines.append(f"**Run failed:** {_escape(view.fatal)}")
    if view.aborted:
        lines.append("_Run aborted._")
    elif view.finished:
        if view.fatal:
            links = [_file_link(n, p) for n, p in (("result.py", view.result_py),
                                                   ("report.md", view.report_md)) if p]
            if links:
                lines.append("")
                lines.append(" · ".join(links))
        else:
            objs = ", ".join(_code(n) for n in view.objects) or "none"
            lines.append(f"**Done.** Objects: {objs}")
            _links_and_usage(view, lines)
    return "\n".join(lines)
