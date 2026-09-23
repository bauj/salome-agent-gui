# salome-agent-gui ConversationWorker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the salome-agent-gui chat window from "one message = one run" into a conversation. The first message builds the model, follow-ups amend it, and the window gets Undo, Redo, Rebuild and New conversation.

**Architecture:** A long-lived `ConversationWorker` (`QThread`) replaces the per-request `RunWorker`. It opens one agent-server connection and one `salome_agent.conversation.Conversation` for the conversation's life, and runs commands (turn / undo / redo / rebuild) from a `queue.Queue`, so the socket stays on one thread. The signal surface stays `event` and `gate`; `done` becomes `turn_done`, which fires once per command. `timeline.RunView` learns the four conversation event kinds (`turn_start`, `graph_edit`, `replay`, `turn_done`), and `ChatView` gains plain note items for undo/redo/rebuild results.

**Tech Stack:** Python 3.10+, PyQt5, pytest + pytest-qt (`qtbot`), salome-agent as the `salome-agent/` git submodule (editable install).

**Spec:** `salome-agent/docs/superpowers/specs/2026-09-21-agentic-chat-design.md` (in the submodule once Task 1 bumps it), section "salome-agent-gui" (plus "The conversation engine" for the `Conversation` API). This is the follow-up named at the end of `salome-agent/docs/superpowers/plans/2026-09-22-agentic-chat.md`.

## Global Constraints

- All changes are in the **salome-agent-gui** repo, on branch `feat/conversation-worker` (already created; this plan is committed on it). Never commit to its `main` directly.
- salome-agent itself does not change in this plan. The engine API used is exactly what is on salome-agent `main` at `222090c`: `Conversation(config, client, run_id, *, batch=False, verbose=0, request_timeout=None, llm=None)`, `.turn(text, *, selection=None, on_event, on_gate, cancel=None) -> TurnResult`, `.undo()`, `.redo()`, `.rebuild()`, attributes `.degraded`, `.ended`, `.run_dir`; `TurnResult(status, message, final_state)` with status in `ok | needs_input | failed | degraded | ended`.
- `server_conn.connect(run_id, record_path=None, hold=False)`. The conversation connects with `hold=True`, as the CLI `--chat` does.
- Events are `{"kind", "run_id", "data"}` dicts. `graph_edit` data: `{"op": "edit", "node", "param", "old", "new"}`, `{"op": "delete", "old": [node ids]}`, or `{"op": "add", "node", "new": tool}`. `replay` data: `{"nodes": [ids]}`. `turn_done` data: `{"turn", "status", "message"}`.
- Commit messages: a subject line only, no body, no trailers. Stage named files only, never `git add -A` / `git add .`.
- No distro paths (the local SALOME install path) in repo code, comments, tests or docs.
- Run tests with `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest` from the salome-agent-gui root.

## Review Focus

1. **A message sent while no conversation is open, after the previous one ended** (server died mid-turn, `status == "ended"`). A person expects the next Send to start a fresh conversation, not to be silently dropped. Pinned by `test_ended_conversation_frees_the_worker_and_next_send_opens_a_new_one` (Task 4).
2. **Stop pressed while a plan gate is waiting.** A person expects the turn to abort and the conversation to stay open for the next message. Pinned by `test_stop_aborts_pending_gate_and_keeps_the_conversation` (Task 3) and `test_stop_aborts_a_pending_gate` (Task 4).
3. **Stop pressed while idle, then a new message.** The next turn must not start already cancelled. Pinned by `test_submit_clears_a_stale_cancel` (Task 3).
4. **An exception escaping `Conversation.turn`** (a bug, not a TurnResult). A person expects an error in the transcript and a window that still works. Pinned by `test_exception_in_a_command_is_fatal_but_the_worker_lives` (Task 3).
5. **Closing the window while a turn is running.** The close waits for the turn, then closes the client. Pinned by `test_close_defers_until_turn_completes` (Task 4) and `test_close_closes_the_client` (Task 3).

---

## File Structure

- `salome-agent` (submodule pointer): bumped to salome-agent `222090c` (Task 1).
- `salome_agent_gui/timeline.py`: `RunView` gains `edits`, `turn_status`, `turn_message`; new `Note` dataclass + `render_note`; `render_run` renders edits and the turn outcome (Task 2).
- `salome_agent_gui/chat_view.py`: `add_note(text)`; `refresh()` renders `Note` items (Task 2).
- `salome_agent_gui/conversation_worker.py` (new): `ConversationWorker`, `default_open` (Task 3).
- `salome_agent_gui/run_worker.py`: deleted, with `tests/test_run_worker.py` (Task 4).
- `salome_agent_gui/main_window.py`: conversation lifecycle, new buttons, help text (Task 4).
- `README.md`: one-line description updated (Task 4).
- Tests: `tests/test_timeline.py`, `tests/test_chat_view.py` (Task 2), `tests/test_conversation_worker.py` (new, Task 3), `tests/test_main_window.py` (Task 4).

---

### Task 1: Bump the salome-agent submodule to the agentic-chat engine

**Files:**
- Modify: `salome-agent` (submodule pointer)

**Interfaces:**
- Consumes: nothing.
- Produces: `from salome_agent.conversation import Conversation, TurnResult` importable in the salome-agent-gui venv.

- [ ] **Step 1: Confirm you are on the branch**

Run: `git branch --show-current`
Expected: `feat/conversation-worker`

- [ ] **Step 2: Point the submodule at salome-agent `222090c` (on `origin/main`)**

```bash
git -C salome-agent fetch origin
git -C salome-agent checkout 222090c
```

- [ ] **Step 3: Confirm the engine imports and the existing suite still passes**

Run: `.venv/bin/python -c "from salome_agent.conversation import Conversation, TurnResult; print('ok')"`
Expected: `ok` (the submodule is an editable install; `pyproject.toml` deps did not change between `6c90d0e` and `222090c`).

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add salome-agent
git commit -m "chore: bump salome-agent submodule to 222090c (agentic chat)"
```

---

### Task 2: Timeline renders conversation turns and notes

**Files:**
- Modify: `salome_agent_gui/timeline.py`
- Modify: `salome_agent_gui/chat_view.py`
- Test: `tests/test_timeline.py`, `tests/test_chat_view.py`

**Interfaces:**
- Consumes: event dicts as in Global Constraints.
- Produces: `RunView.edits: list[str]`, `RunView.turn_status: str | None`, `RunView.turn_message: str | None`; `STATUS_LABEL: dict[str, str]`; `@dataclass Note(text: str)`; `render_note(note: Note) -> str`; `ChatView.add_note(text: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_timeline.py` (and extend its import line to `from salome_agent_gui.timeline import Note, RunView, render_note, render_run, render_user`):

```python
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
```

Append to `tests/test_chat_view.py`:

```python
def test_notes_render_between_turns(qtbot):
    v = ChatView()
    qtbot.addWidget(v)
    v.add_user("make a box")
    v.add_run()
    v.add_note("undo: undone back to turn 0")
    assert v.markdown().rstrip().endswith("_undo: undone back to turn 0_")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_timeline.py tests/test_chat_view.py -q`
Expected: FAIL with `ImportError: cannot import name 'Note'`.

- [ ] **Step 3: Implement in `salome_agent_gui/timeline.py`**

Add after the `ICON` line:

```python
STATUS_LABEL = {"ok": "Done.", "needs_input": "Question:", "failed": "Turn failed:",
                "degraded": "Study out of sync:", "ended": "Session ended:"}
```

Add three fields at the end of `RunView` (after `finished: bool = False`):

```python
    edits: list[str] = field(default_factory=list)
    turn_status: str | None = None
    turn_message: str | None = None
```

In `RunView.apply`, add these branches before the `elif kind == "fatal":` branch:

```python
        elif kind == "graph_edit":
            self.edits.append(_edit_line(d))
        elif kind == "replay":
            nodes = [str(n) for n in d.get("nodes") or []]
            self.edits.append(f"rebuilding {len(nodes)} object(s): {', '.join(nodes)}")
        elif kind == "turn_done":
            self.turn_status, self.turn_message = d.get("status"), d.get("message")
            self.finished = True
```

Add the helper and the note type after the `RunView` class:

```python
def _edit_line(d: dict) -> str:
    if d.get("op") == "edit":
        return f"edit {d.get('node')}.{d.get('param')}: {d.get('old')} -> {d.get('new')}"
    if d.get("op") == "delete":
        return f"deleted {', '.join(str(n) for n in d.get('old') or [])}"
    return f"added {d.get('node')} ({d.get('new')})"


@dataclass
class Note:
    text: str
```

Add after `render_user`:

```python
def render_note(note: Note) -> str:
    return f"_{_escape(note.text)}_"
```

Replace the whole `render_run` function with:

```python
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
```

(The branch without `turn_status` keeps today's rendering byte-for-byte, so the existing timeline tests stay green.)

- [ ] **Step 4: Implement in `salome_agent_gui/chat_view.py`**

Change the import to:

```python
from salome_agent_gui.timeline import Note, RunView, render_note, render_run, render_user
```

Add a module-level helper above the class:

```python
def _render(item) -> str:
    if isinstance(item, RunView):
        return render_run(item)
    if isinstance(item, Note):
        return render_note(item)
    return render_user(item)
```

Add the method after `add_run`:

```python
    def add_note(self, text: str) -> None:
        self._items.append(Note(text))
        self.refresh()
```

In `refresh`, replace the `parts = ...` line with:

```python
        parts = [_render(i) for i in self._items]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_timeline.py tests/test_chat_view.py -q`
Expected: PASS (old and new tests).

- [ ] **Step 6: Commit**

```bash
git add salome_agent_gui/timeline.py salome_agent_gui/chat_view.py tests/test_timeline.py tests/test_chat_view.py
git commit -m "feat: transcript renders amend edits, replays, turn outcomes and notes"
```

---

### Task 3: ConversationWorker

**Files:**
- Create: `salome_agent_gui/conversation_worker.py`
- Test: `tests/test_conversation_worker.py`

**Interfaces:**
- Consumes: `salome_agent.conversation.Conversation` / `TurnResult`, `salome_agent.server_conn.connect` (Global Constraints).
- Produces:
  - `default_open(config: dict, run_id: str, *, batch: bool, verbose: int) -> tuple[Conversation, Callable[[], None]]`, returning the conversation and a close function for its client.
  - `class ConversationWorker(QThread)` with signals `event(dict)`, `gate(dict)`, `turn_done(dict)`. `turn_done` payload: `{"command": "turn" | "undo" | "redo" | "rebuild", "status": str, "message": str, "degraded": bool, "ended": bool}`.
  - `__init__(self, config, *, batch=False, verbose=0, open_fn=default_open, parent=None)`; attributes `run_id: str`, `cancel: threading.Event`.
  - Methods: `submit(text)`, `undo()`, `redo()`, `rebuild()`, `stop()` (cancel the running command; a pending gate answers abort), `close()` (stop, then end the thread and close the client), `gate_pending() -> bool`, `answer_gate(decision: dict)`.
  - The thread exits by itself when the conversation reports `ended`, when opening fails, or after `close()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_conversation_worker.py`:

```python
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

    def turn(self, text, *, on_event, on_gate, cancel):
        self.calls.append(("turn", text))
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_conversation_worker.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'salome_agent_gui.conversation_worker'`.

- [ ] **Step 3: Implement `salome_agent_gui/conversation_worker.py`**

```python
import queue
import threading
import uuid

from PyQt5.QtCore import QThread, pyqtSignal


def default_open(config, run_id, *, batch, verbose):
    from salome_agent import server_conn
    from salome_agent.conversation import Conversation

    client = server_conn.connect(run_id, hold=True)
    try:
        conv = Conversation(config, client, run_id, batch=batch, verbose=verbose)
    except Exception:
        client.close()
        raise

    def close():
        try:
            client.close()
        except Exception:
            pass

    return conv, close


class ConversationWorker(QThread):
    """One thread owning one Conversation (and its agent-server socket) for the
    conversation's life; commands arrive through a queue."""

    event = pyqtSignal(dict)
    gate = pyqtSignal(dict)
    turn_done = pyqtSignal(dict)

    def __init__(self, config, *, batch=False, verbose=0, open_fn=default_open, parent=None):
        super().__init__(parent)
        self.config = config
        self.batch, self.verbose = batch, verbose
        self.run_id = uuid.uuid4().hex[:12]
        self.cancel = threading.Event()
        self._open_fn = open_fn
        self._queue: queue.Queue = queue.Queue()
        self._answered = threading.Event()
        self._decision = None
        self._pending = False

    # ---- called from the GUI thread ------------------------------------
    def submit(self, text: str) -> None:
        self.cancel.clear()
        self._queue.put(("turn", text))

    def undo(self) -> None:
        self._queue.put(("undo", None))

    def redo(self) -> None:
        self._queue.put(("redo", None))

    def rebuild(self) -> None:
        self._queue.put(("rebuild", None))

    def stop(self) -> None:
        self.cancel.set()
        if self._pending:
            self.answer_gate({"action": "abort"})

    def close(self) -> None:
        self.stop()
        self._queue.put(None)

    def gate_pending(self) -> bool:
        return self._pending

    def answer_gate(self, decision) -> None:
        self._decision = decision
        self._answered.set()

    # ---- worker thread -------------------------------------------------
    def _fatal(self, e: BaseException) -> str:
        message = f"{type(e).__name__}: {e}"
        self.event.emit({"kind": "fatal", "run_id": self.run_id, "data": {"message": message}})
        return message

    def run(self):
        try:
            conv, close = self._open_fn(self.config, self.run_id, batch=self.batch,
                                        verbose=self.verbose)
        except Exception as e:  # noqa: BLE001
            message = self._fatal(e)
            self.turn_done.emit({"command": "turn", "status": "ended", "message": message,
                                 "degraded": False, "ended": True})
            return
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    return
                command, arg = item
                try:
                    if command == "turn":
                        r = conv.turn(arg, on_event=self.event.emit, on_gate=self._on_gate,
                                      cancel=self.cancel)
                    else:
                        r = getattr(conv, command)()
                    status, message = r.status, r.message
                except Exception as e:  # noqa: BLE001
                    status, message = "failed", self._fatal(e)
                self.turn_done.emit({"command": command, "status": status, "message": message,
                                     "degraded": bool(conv.degraded), "ended": bool(conv.ended)})
                if conv.ended:
                    return
        finally:
            close()

    def _on_gate(self, payload):
        self._answered.clear()
        self._decision = None
        self._pending = True
        if self.cancel.is_set():
            self._pending = False
            return {"action": "abort"}
        self.gate.emit(payload)
        self._answered.wait()
        self._pending = False
        return self._decision or {"action": "abort"}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_conversation_worker.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add salome_agent_gui/conversation_worker.py tests/test_conversation_worker.py
git commit -m "feat: ConversationWorker owns one Conversation and runs turns from a queue"
```

---

### Task 4: MainWindow drives a conversation

**Files:**
- Modify: `salome_agent_gui/main_window.py`
- Modify: `README.md`
- Delete: `salome_agent_gui/run_worker.py`, `tests/test_run_worker.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: `ConversationWorker`, `default_open` (Task 3); `ChatView.add_note`, `RunView.turn_status` / `turn_message` (Task 2).
- Produces: `MainWindow(config_path, *, open_fn=None, probe_fn=None, ask_hint=None, edit_plan=None, parent_pid=None)`, where `run_fn` is replaced by `open_fn`. New buttons `undo_btn`, `redo_btn`, `rebuild_btn`, `new_btn`. State: `worker: ConversationWorker | None` (the open conversation), `_busy: bool` (a command is running or the conversation is closing), `_degraded: bool`.

- [ ] **Step 1: Rewrite the window tests**

Replace `tests/test_main_window.py` from its imports down to (not including) `test_loads_key_fields_and_masks_the_key` with:

```python
import json
import os
import subprocess
import sys
import threading
import time

import pytest
from salome_agent.conversation import TurnResult

from salome_agent_gui.main_window import MainWindow

CFG = {"llm": {"base_url": "http://h/v1", "model": "m", "api_key": "secret"},
       "salome": {"root": "/x"}, "policy": {"on_stage_failure": "abort",
                                            "tool_selection": "hints"}}
PLAN = [{"module": "geom", "intent": "box", "params": {}, "inputs": []}]


@pytest.fixture
def cfg_path(tmp_path):
    p = tmp_path / "salome-agent.json"
    p.write_text(json.dumps(CFG))
    return p


class FakeConv:
    """First turn: plan gate, then one stage. Later turns: one amend edit."""

    def __init__(self, rec):
        self.rec = rec
        self.degraded = False
        self.ended = False
        self.release = None
        self.next_status = None

    def turn(self, text, *, on_event, on_gate, cancel):
        rec = self.rec
        rec.setdefault("turns", []).append(text)
        n = len(rec["turns"]) - 1

        def ev(kind, **data):
            on_event({"kind": kind, "run_id": "r", "data": data})

        ev("turn_start", turn=n, text=text)
        if self.release is not None:
            while not self.release.is_set():
                time.sleep(0.01)
        if self.next_status is not None:
            status, self.next_status = self.next_status, None
            self.degraded = status == "degraded"
            self.ended = status == "ended"
            ev("turn_done", turn=n, status=status, message=f"{status} happened")
            return TurnResult(status, f"{status} happened", {})
        if n == 0:
            ev("plan", stages=PLAN)
            rec["decision"] = on_gate({"plan": PLAN})
            if rec["decision"]["action"] not in ("approve", "edit"):
                ev("aborted")
                ev("turn_done", turn=n, status="failed", message="turn cancelled")
                return TurnResult("failed", "turn cancelled", {})
            ev("stage_done", index=0, names=["box_1"])
        else:
            ev("graph_edit", op="edit", node="n1", param="dz", old=40, new=60)
            ev("replay", nodes=["n1"])
        ev("report", result_py="/w/result.py", report_md="/w/report.md", text="", usage=None)
        ev("turn_done", turn=n, status="ok", message=f"did {text}")
        return TurnResult("ok", f"did {text}", {})

    def undo(self):
        self.rec["undo"] = True
        return TurnResult("ok", "undone back to turn 0", {})

    def redo(self):
        return TurnResult("ok", "redone up to turn 1", {})

    def rebuild(self):
        self.degraded = False
        return TurnResult("ok", "rebuilt 1 node(s)", {})


def opener(rec):
    def open_fn(config, run_id, *, batch, verbose):
        rec["opened"] = rec.get("opened", 0) + 1
        rec.update(config=config, batch=batch, verbose=verbose)
        rec["conv"] = FakeConv(rec)
        return rec["conv"], lambda: rec.__setitem__("closed", rec.get("closed", 0) + 1)
    return open_fn


def make(qtbot, cfg_path, rec, **kw):
    w = MainWindow(cfg_path, open_fn=opener(rec), probe_fn=lambda: {"mode": "gui", "port": 4242},
                   **kw)
    qtbot.addWidget(w)
    return w


def first_turn(qtbot, w, text="make a box"):
    w.probe()
    w.input.setText(text)
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    w.chat.gate_clicked.emit("approve")
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)


def say(qtbot, w, text):
    w.input.setText(text)
    w.send()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
```

In the remaining existing tests:
- `test_loads_key_fields_and_masks_the_key`, `test_loads_run_options_from_config`, `test_probe_reports_server_and_enables_send`, `test_key_field_edit_is_saved`, `test_check_parent_leaves_window_open_when_parent_is_alive`, `test_no_parent_pid_starts_no_watch_timer`: change `make(qtbot, cfg_path, gated_run({}))` / `make(qtbot, p, gated_run({}))` to `make(qtbot, cfg_path, {})` / `make(qtbot, p, {})`.
- `test_no_server_keeps_send_disabled`: change `MainWindow(cfg_path, run_fn=gated_run({}), probe_fn=lambda: None)` to `MainWindow(cfg_path, open_fn=opener({}), probe_fn=lambda: None)`.
- `test_check_parent_closes_when_parent_is_gone`: change `make(qtbot, cfg_path, gated_run({}), parent_pid=proc.pid)` to `make(qtbot, cfg_path, {}, parent_pid=proc.pid)`.

Replace `test_send_approve_runs_to_done`, `test_edit_uses_the_injected_editor`, `test_stop_aborts_a_pending_gate`, `test_close_defers_until_run_completes`, `test_done_while_close_pending_skips_probe` and `test_server_error_disables_send_until_reprobe` with:

```python
def test_first_message_opens_a_conversation_and_stays_open(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    w.probe()
    w.on_failure.setCurrentText("continue")
    w.input.setText("make a box")
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    assert not w.send_btn.isEnabled() and w.stop_btn.isEnabled()
    w.chat.gate_clicked.emit("approve")
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    assert rec["config"]["policy"]["on_stage_failure"] == "continue"
    md = w.chat.markdown()
    assert "`box_1`" in md and "gate:" not in md and "**Done.** did make a box" in md
    assert w.worker is not None
    assert w.send_btn.isEnabled() and w.undo_btn.isEnabled() and w.new_btn.isEnabled()
    assert not w.rebuild_btn.isEnabled()
    assert not w.on_failure.isEnabled() and not w.batch.isEnabled()


def test_follow_up_amends_the_same_conversation(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    say(qtbot, w, "make it taller")
    assert rec["opened"] == 1 and rec["turns"] == ["make a box", "make it taller"]
    md = w.chat.markdown()
    assert "edit n1.dz: 40 -\\> 60" in md and "**Done.** did make it taller" in md


def test_edit_uses_the_injected_editor(qtbot, cfg_path):
    rec = {}
    edited = [{"module": "geom", "intent": "cyl", "params": {}, "inputs": [], "tools": []}]
    w = make(qtbot, cfg_path, rec, edit_plan=lambda parent, plan: edited)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: "gate:edit" in w.chat.markdown(), timeout=3000)
    w.chat.gate_clicked.emit("edit")
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["decision"] == {"action": "edit", "plan": edited}


def test_stop_aborts_a_pending_gate(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: "gate:approve" in w.chat.markdown(), timeout=3000)
    w.stop_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["decision"] == {"action": "abort"}
    assert "**Turn failed:** turn cancelled" in w.chat.markdown()
    assert w.worker is not None and w.send_btn.isEnabled()


def test_undo_and_redo_add_notes(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    w.undo_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert rec["undo"] is True
    assert "_undo: undone back to turn 0_" in w.chat.markdown()
    w.redo_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert "_redo: redone up to turn 1_" in w.chat.markdown()


def test_rebuild_is_enabled_only_when_degraded(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    rec["conv"].next_status = "degraded"
    say(qtbot, w, "break it")
    assert w.rebuild_btn.isEnabled()
    assert "**Study out of sync:** degraded happened" in w.chat.markdown()
    w.rebuild_btn.click()
    qtbot.waitUntil(lambda: not w._busy, timeout=3000)
    assert not w.rebuild_btn.isEnabled()
    assert "_rebuild: rebuilt 1 node\\(s\\)_" in w.chat.markdown()


def test_new_conversation_closes_the_client_and_next_send_reopens(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    w.new_btn.click()
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    assert rec["closed"] == 1
    assert w.on_failure.isEnabled() and not w.undo_btn.isEnabled()
    first_turn(qtbot, w, "make a cylinder")
    assert rec["opened"] == 2


def test_ended_conversation_frees_the_worker_and_next_send_opens_a_new_one(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    first_turn(qtbot, w)
    rec["conv"].next_status = "ended"
    say(qtbot, w, "anything")
    qtbot.waitUntil(lambda: w.worker is None, timeout=3000)
    md = w.chat.markdown()
    assert "**Session ended:** ended happened" in md
    assert "next message starts a new conversation" in md
    assert w.send_btn.isEnabled()
    first_turn(qtbot, w, "again")
    assert rec["opened"] == 2


def test_close_defers_until_turn_completes(qtbot, cfg_path):
    rec = {}
    w = make(qtbot, cfg_path, rec)
    w.show()
    first_turn(qtbot, w)
    rec["conv"].release = threading.Event()
    w.input.setText("slow")
    w.send()
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    w.close()
    assert w._close_pending is True and w.worker is not None
    assert w.isVisible()
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: w.worker is None and not w.isVisible(), timeout=5000)
    assert rec["closed"] == 1


def test_done_while_close_pending_skips_probe(qtbot, cfg_path):
    rec = {}
    probe_calls = []

    def probe_fn():
        probe_calls.append(1)
        return {"mode": "gui", "port": 4242}

    w = MainWindow(cfg_path, open_fn=opener(rec), probe_fn=probe_fn)
    qtbot.addWidget(w)
    w.show()
    first_turn(qtbot, w)
    rec["conv"].release = threading.Event()
    w.input.setText("slow")
    w.send()
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    w.close()
    n_before = len(probe_calls)
    assert w._close_pending is True
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: w.worker is None and not w.isVisible(), timeout=5000)
    assert len(probe_calls) == n_before


def test_server_error_disables_send_until_reprobe(qtbot, cfg_path):
    from salome_agent.server_conn import ServerUnavailable

    def failing_open(config, run_id, *, batch, verbose):
        raise ServerUnavailable("poisoned")

    w = MainWindow(cfg_path, open_fn=failing_open, probe_fn=lambda: {"mode": "gui", "port": 4242})
    qtbot.addWidget(w)
    w.probe()
    w.input.setText("x")
    w.send()
    qtbot.waitUntil(lambda: w.worker is None and not w._busy, timeout=3000)
    assert not w.send_btn.isEnabled()
    assert "poisoned" in w.status.text()
    w._probe_fn = lambda: {"mode": "gui", "port": 4242}
    w.probe()
    assert w.send_btn.isEnabled()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_main_window.py -q`
Expected: FAIL with `TypeError: MainWindow.__init__() got an unexpected keyword argument 'open_fn'`.

- [ ] **Step 3: Implement in `salome_agent_gui/main_window.py`**

Replace the import `from salome_agent_gui.run_worker import RunWorker, default_run` with:

```python
from salome_agent_gui.conversation_worker import ConversationWorker, default_open
```

Replace `HELP` with:

```python
HELP = ("The first message starts a conversation: the planner proposes stages, you approve, "
        "edit or abort, and each stage is built in this SALOME session. Follow-up messages "
        "change that model (\"make the roof taller\", \"add a chimney\"). Undo and Redo step "
        "through turns; Rebuild recreates the study from the model when they got out of sync; "
        "New conversation starts over. While a conversation is open it keeps the agent "
        "server to itself. result.py and report.md are linked after each turn.")
```

In `MainWindow.__init__`, change the signature and the stored callables:

```python
    def __init__(self, config_path: Path, *, open_fn=None, probe_fn=None,
                 ask_hint=None, edit_plan=None, parent_pid: int | None = None):
```

and replace `self._run_fn = run_fn or default_run` with `self._open_fn = open_fn or default_open`, replace `self.worker: RunWorker | None = None` with:

```python
        self.worker: ConversationWorker | None = None
        self._busy = False
        self._degraded = False
```

In `_build`, change the placeholder and the button row. Replace from `self.input.setPlaceholderText(...)` to the end of the `for b in (...)` loop with:

```python
        self.input.setPlaceholderText("Describe what to build, then ask for changes…")
        self.input.returnPressed.connect(self.send)
        self.send_btn, self.stop_btn = QPushButton("Send"), QPushButton("Stop")
        self.send_btn.clicked.connect(self.send)
        self.stop_btn.clicked.connect(self._stop)
        self.undo_btn, self.redo_btn = QPushButton("Undo"), QPushButton("Redo")
        self.rebuild_btn, self.new_btn = QPushButton("Rebuild"), QPushButton("New conversation")
        self.undo_btn.clicked.connect(lambda: self._command("undo"))
        self.redo_btn.clicked.connect(lambda: self._command("redo"))
        self.rebuild_btn.clicked.connect(lambda: self._command("rebuild"))
        self.new_btn.clicked.connect(self._new_conversation)
        help_btn, quit_btn = QPushButton("Help"), QPushButton("Quit")
        help_btn.clicked.connect(lambda: QMessageBox.information(self, "SALOME Agent", HELP))
        quit_btn.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        for b in (self.send_btn, self.stop_btn, self.undo_btn, self.redo_btn,
                  self.rebuild_btn, self.new_btn, help_btn, quit_btn):
            row.addWidget(b)
```

In `_check_parent`, replace `self.worker.stop()` with `self.worker.close()`.

Replace everything from the `# ---- runs ----` comment to the end of the file with:

```python
    # ---- conversation ---------------------------------------------------
    def _sync_buttons(self):
        open_, busy = self.worker is not None, self._busy
        self.send_btn.setEnabled(self._connected and not busy)
        self.stop_btn.setEnabled(busy)
        for b in (self.undo_btn, self.redo_btn, self.new_btn):
            b.setEnabled(open_ and not busy)
        self.rebuild_btn.setEnabled(open_ and not busy and self._degraded)
        for w in (self.batch, self.on_failure, self.tools, self.verbose):
            w.setEnabled(not open_)

    def _start_conversation(self) -> bool:
        self._save_key_fields()
        try:
            config = config_store.load(self.config_path)
        except Exception as e:  # noqa: BLE001
            self.status.setText(f"Config error: {e}")
            return False
        config.setdefault("policy", {})
        config["policy"]["on_stage_failure"] = self.on_failure.currentText()
        config["policy"]["tool_selection"] = self.tools.currentText()
        worker = ConversationWorker(config, batch=self.batch.isChecked(),
                                    verbose=self.verbose.value(), open_fn=self._open_fn,
                                    parent=self)
        worker.event.connect(self._on_event)
        worker.gate.connect(self._on_gate)
        worker.turn_done.connect(self._on_turn_done)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self.worker = worker
        self._degraded = False
        worker.start()
        return True

    def send(self):
        text = self.input.text().strip()
        if not text or self._busy or not self._connected:
            return
        if self.worker is None and not self._start_conversation():
            return
        self.input.remember(text)
        self.input.clear()
        self.chat.add_user(text)
        self._view = self.chat.add_run()
        self._busy = True
        self.worker.submit(text)
        self._sync_buttons()

    def _command(self, name: str):
        if self.worker is None or self._busy:
            return
        self._busy = True
        getattr(self.worker, name)()
        self._sync_buttons()

    def _new_conversation(self):
        if self.worker is None or self._busy:
            return
        self._busy = True
        self.worker.close()
        self.chat.add_note("New conversation: the next message starts a fresh model.")
        self._sync_buttons()

    def _on_event(self, ev: dict):
        if self._view is None:
            return
        self._view.apply(ev)
        self.chat.refresh()
        if ev.get("kind") == "fatal":
            message = ev.get("data", {}).get("message", "")
            if message.startswith("ServerUnavailable"):
                self._connected = False
                self._server_error = True
                self.status.setText(message)
                self._sync_buttons()

    def _on_gate(self, payload: dict):
        self._view.gate = payload
        self.chat.refresh()

    def _on_gate_clicked(self, action: str):
        if self.worker is None or not self._view or not self._view.gate:
            return
        payload = self._view.gate
        if action == "edit":
            plan = self._edit_plan(self, payload.get("plan") or [])
            if plan is None:
                return
            decision = {"action": "edit", "plan": plan}
        elif action == "hint":
            hint = self._ask_hint(self)
            if not hint:
                return
            decision = {"action": "hint", "hint": hint}
        elif action in ("approve", "skip", "abort"):
            decision = {"action": action}
        else:
            return
        self._view.gate = None
        self.chat.refresh()
        self.worker.answer_gate(decision)

    def _stop(self):
        if self.worker is not None and self._busy:
            self.status.setText("Stopping the current turn…")
            self.worker.stop()

    def _on_turn_done(self, payload: dict):
        self._busy = False
        self._degraded = bool(payload.get("degraded"))
        command = payload.get("command")
        if command != "turn":
            self.chat.add_note(f"{command}: {payload.get('message', '')}")
        elif self._view is not None:
            if self._view.turn_status is None:
                self._view.turn_status = payload.get("status")
                self._view.turn_message = payload.get("message")
            self._view.gate = None
            self._view.finished = True
        if payload.get("ended"):
            self._busy = True
            self.chat.add_note("The conversation has ended; the next message starts a new "
                               "conversation.")
        self.chat.refresh()
        self._sync_buttons()
        if not self._close_pending and not self._server_error:
            self.probe()

    def _on_worker_finished(self, worker):
        if worker is not self.worker:
            return
        worker.wait(2000)
        self.worker = None
        self._busy = False
        self._degraded = False
        self._sync_buttons()
        if self._close_pending:
            self.close()

    def closeEvent(self, e):
        if self.worker is not None:
            self.worker.close()
            if not self.worker.wait(3000):
                self._close_pending = True
                self.status.setText("Stopping the current turn…")
                e.ignore()
                return
        super().closeEvent(e)
```

Rendered text goes through `timeline._escape`, so `>`, `(`, `)` and `_` appear backslash-escaped in `ChatView.markdown()`; the tests assert on the escaped form.

(`_busy` stays `True` after an `ended` payload until the thread's `finished` arrives, so a Send cannot race into a worker that is shutting down. `_on_worker_finished` then clears it.)

- [ ] **Step 4: Delete RunWorker and update the README**

```bash
git rm salome_agent_gui/run_worker.py tests/test_run_worker.py
```

In `README.md`, replace the line `each message is one agent run (plan -> stages -> result.py).` with:

```
the first message builds a model (plan -> stages -> result.py), follow-ups change it,
with undo / redo / rebuild and a New conversation button.
```

- [ ] **Step 5: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: PASS, with no remaining reference to `run_worker` (`grep -rn run_worker salome_agent_gui tests` prints nothing).

- [ ] **Step 6: Commit**

```bash
git add salome_agent_gui/main_window.py README.md tests/test_main_window.py
git commit -m "feat: chat window keeps one conversation with undo, redo, rebuild and new conversation"
```

(The `git rm` in Step 4 already staged the two deletions.)

---

### Task 5: Live check against the SALOME GUI agent server

Mocked conversations cannot catch threading, signal or real-engine problems. Run against a real SALOME GUI with the agent server started from **Tools ▸ Plugins**, the real LLM, and the salome-agent-gui venv.

**Files:** none committed (the driver lives in the session scratchpad).

- [ ] **Step 1: Launch SALOME, start the agent server from the plugin menu, and confirm `~/.salome_agent/server.json` says `"mode": "gui"`.**

- [ ] **Step 2: Drive the window offscreen**

Copy the salome-agent `config.json` into the scratchpad first; the window writes its key fields back to the file it is given. Then run this driver with `QT_QPA_PLATFORM=offscreen <salome-agent-gui>/.venv/bin/python drive_window.py <copied config.json>`:

```python
import sys
import time
from pathlib import Path

from PyQt5.QtWidgets import QApplication

app = QApplication([])
from salome_agent_gui.main_window import MainWindow  # noqa: E402

w = MainWindow(Path(sys.argv[1]))


def until(pred, timeout=900):
    t0 = time.time()
    while not pred():
        app.processEvents()
        time.sleep(0.05)
        if time.time() - t0 > timeout:
            print(w.chat.markdown())
            raise SystemExit("timeout")


def turn(text, approve=False):
    w.input.setText(text)
    w.send()
    if approve:
        until(lambda: "gate:approve" in w.chat.markdown())
        w.chat.gate_clicked.emit("approve")
    until(lambda: not w._busy)


until(lambda: w._connected, 30)
turn("a small house: 200x120x80mm box base with a 200x120x40mm prism roof on top", approve=True)
turn("make the roof taller")
turn("add a 20x20x60mm chimney on the roof")
for b in (w.undo_btn, w.redo_btn, w.undo_btn):
    b.click()
    until(lambda: not w._busy)
print(w.chat.markdown())
print("run_id", w.worker.run_id)
w.new_btn.click()
until(lambda: w.worker is None)
w.close()
```

- [ ] **Step 3: Check, and record each result in task 194's follow-up task**

1. The transcript shows the plan + stage lines for turn 1, `edit …` and `rebuilding …` lines for turn 2, `added …` lines for turn 3, and `_undo: …_`, `_redo: …_`, `_undo: …_` notes.
2. Each turn ends with a `**Done.** …` line and result.py / report.md links.
3. After the last undo, the SALOME viewer shows the house with the taller roof and no chimney. Check by eye in the SALOME window, or with the scratchpad `gui_probe.py` (`SalomePyQt.dumpView`).
4. After **New conversation** (`w.worker is None`), a CLI `salome-agent "a 10mm cube"` against the same GUI server connects. The held connection was released.
5. The run dir `~/.local/share/salome-agent/runs/<run_id>/` has `result.py`, `build_graph.json` and `report.md` with a section per turn.

- [ ] **Step 4: The user opens the real chat window from the SALOME plugin menu once and clicks through one turn + Undo. Anything that fails becomes a new task with the run id, not a silent fix.**
