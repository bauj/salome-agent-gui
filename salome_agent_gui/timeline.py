from dataclasses import dataclass, field
from pathlib import Path

ICON = {"pending": "·", "running": "⟳", "ok": "✓", "failed": "✗", "skipped": "↷"}


@dataclass
class StageRow:
    index: int
    module: str
    intent: str
    status: str = "pending"
    attempts: int = 0
    error: str | None = None


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
            self._row(d["index"], d.get("module", "?"), d.get("intent", "")).status = "running"
        elif kind == "stage_attempt":
            r = self._row(d["index"])
            r.attempts += 1
            r.status, r.error = ("running", None) if d.get("ok") else ("failed", d.get("error"))
        elif kind == "stage_done":
            r = self._row(d["index"])
            r.status, r.error = "ok", None
            self.objects.extend(d.get("names") or [])
        elif kind == "stage_skipped":
            self._row(d["index"]).status = "skipped"
        elif kind == "report":
            self.result_py, self.report_md = d.get("result_py"), d.get("report_md")
            self.usage = d.get("usage")
            self.finished = True
        elif kind == "fatal":
            self.fatal = d.get("message")
        elif kind == "aborted":
            self.aborted = True
            self.finished = True


def _escape(text: str) -> str:
    for ch in "\\`*_[]()<>#":
        text = text.replace(ch, "\\" + ch)
    return text


def _code(text: str) -> str:
    return "`" + text.replace("`", "'") + "`"


def render_user(text: str) -> str:
    return f"**You:** {_escape(text)}"


def _file_link(label: str, path: str) -> str:
    return f"[{label}]({Path(path).as_uri()})"


def render_run(view: RunView) -> str:
    lines = ["**Agent**", ""]
    for s in view.stages:
        tries = f" (attempt {s.attempts})" if s.attempts > 1 else ""
        lines.append(f"{s.index + 1}. {ICON.get(s.status, '?')} {_code(s.module)} "
                     f"{_escape(s.intent)}{tries}")
        if s.error and s.status == "failed":
            lines.append(f"    ↳ {_escape(s.error)}")
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
    if view.fatal:
        lines.append(f"**Run failed:** {_escape(view.fatal)}")
    if view.aborted:
        lines.append("_Run aborted._")
    elif view.finished:
        links = [_file_link(n, p) for n, p in (("result.py", view.result_py),
                                               ("report.md", view.report_md)) if p]
        if view.fatal:
            if links:
                lines.append("")
                lines.append(" · ".join(links))
        else:
            objs = ", ".join(_code(n) for n in view.objects) or "none"
            lines.append(f"**Done.** Objects: {objs}")
            lines.append("")
            if links:
                lines.append(" · ".join(links))
            if view.usage:
                nums = ", ".join(f"{k}={v}" for k, v in view.usage.items()
                                 if isinstance(v, (int, float)) and not isinstance(v, bool))
                lines.append("")
                lines.append(f"_LLM usage: {nums}_")
    return "\n".join(lines)
