# Models settings + "Reading image" card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The salome-agent-gui drawer edits per-module models and the advanced LLM knobs, and the timeline shows the vision step live in a "Reading image" card.

**Architecture:** The engine streams LangGraph `custom` chunks out of nodes, so the vision node reports `vision_start` / `vision_check` / `vision_done` while it runs; it also tags vision reasoning and lists the module names `llm.modules` accepts. salome-agent-gui reads and writes `llm.modules` (parked under `gui.parked_modules` while the shared model is on), renders rows from the engine's module list, and turns the vision events into a card above the plan.

**Tech Stack:** Python 3.14, LangGraph 1.2.11, PyQt5 5.15 + QtWebEngine (Chromium 87), plain HTML/CSS/JS, pytest + pytest-qt.

**Spec:** `docs/superpowers/specs/2026-10-04-models-settings-vision-card-design.md` (salome-agent-gui).

## Global Constraints

- Two repos. Engine: `/storage/Projects/salome-agent`, branch `feat/vision-events` off `main`. GUI: `/storage/Projects/salome-agent-gui`, branch `feat/models-settings` (exists, holds the spec and this plan).
- Engine tests: from the salome-agent root, `.venv/bin/python -m pytest tests/unit -q` (baseline 855 passed, ~2 min). Golden runs live in `tests/unit/test_golden_runs.py` and must stay byte-identical.
- GUI tests: from the salome-agent-gui root, `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` (baseline 137 passed, 32 skipped). Page tests carry `@pytest.mark.web` and need `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web` with a `DISPLAY`.
- Commits: subject line only (`feat: ...` / `fix: ...` / `test: ...` / `chore: ...`), no body, no trailers. Stage named files only, never `git add -A` / `git add .` (untracked config files hold API keys). Never push.
- No install paths of this machine in code, comments or docs. Keep provider-agnostic: no provider names in code.
- Engine text reaches the page only through `textContent`; never `innerHTML` with engine or LLM data.
- Advanced clamps: `reasoning_budget` 0..200000 (default 20000), `vision_fix_retries` 0..5 (default 2), `timeout` 10..1800 (default 120).
- Module row keys the form owns: `model`, `base_url`, `api_key`, `ssl_cert_file`. Everything else in `llm.modules.<m>` is kept on save.
- Event envelope stays `{"kind", "run_id", "data"}`.

## Review Focus

- A hand-edited `llm.modules` that is not an object, or has a non-object entry: `read_settings` must not raise and shows no row for it (Task 4 test `test_read_settings_ignores_junk_modules`).
- An `llm.modules` entry whose name the engine does not list (a typo like `visio`): kept on save and still shown as a raw row (Task 4 test `test_unknown_module_entry_survives_a_save`, Task 6 test `test_module_rows_follow_the_engine_list_plus_unknown_entries`).
- A row whose base URL equals the shared one, with no key: allowed (the engine reuses the shared key for the same host) (Task 4 test `test_same_host_row_needs_no_key`).
- Switching to shared when both `llm.modules` and `gui.parked_modules` hold the same module: merged, `llm.modules` wins (Task 4 test `test_park_merges_and_active_wins`).
- Stop pressed while vision runs: the card stops spinning (`stopped`); a turn without images draws no vision card (Task 7 tests `test_abort_while_reading_stops_the_card`, `test_no_images_no_vision`).

---

## Part 1 — engine (salome-agent)

### Task 1: `drive()` passes custom stream chunks through as events

**Files:**
- Modify: `salome_agent/runner.py` (`EventMapper` docstring, `drive()` stream loop)
- Test: `tests/unit/test_runner.py`

**Interfaces:**
- Produces: any node may call `langgraph.config.get_stream_writer()({"kind": str, "data": dict})`; `drive()` sends it to `on_event` as `mapper.event(kind, **data)` at once, before that node's own update events.

- [ ] **Step 0: Branch**

```bash
cd /storage/Projects/salome-agent && git switch -c feat/vision-events
```

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_runner.py`; `MagicMock` is already imported there, add `from types import SimpleNamespace` and `drive` to the `salome_agent.runner` import if missing)

```python
class _StreamApp:
    """A compiled graph stand-in: yields fixed (mode, chunk) pairs."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.modes = None

    def stream(self, inp, config, stream_mode):
        self.modes = stream_mode
        yield from self.chunks

    def get_state(self, cfg):
        return SimpleNamespace(values={})


def test_drive_passes_custom_chunks_through_as_events():
    m = EventMapper("r1", "/w/r1")
    app = _StreamApp([("custom", {"kind": "vision_start", "data": {"images": 1}}),
                      ("updates", {"plan": {"plan": PLAN}})])
    events = []
    drive(app, {}, {"configurable": {}}, m, MagicMock(), events.append, None, None)
    assert app.modes == ["updates", "custom"]
    assert [e["kind"] for e in events] == ["vision_start", "plan"]
    assert events[0] == {"kind": "vision_start", "run_id": "r1", "data": {"images": 1}}
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `.venv/bin/python -m pytest tests/unit/test_runner.py::test_drive_passes_custom_chunks_through_as_events -q`
Expected: FAIL (`ValueError: too many values to unpack` or the `modes` assert: today `stream_mode="updates"` yields dicts).

- [ ] **Step 3: Implement** — in `drive()`, replace the inner stream loop header and add the custom branch:

```python
            for mode, chunk in app.stream(inp, config=cfg, stream_mode=["updates", "custom"]):
                if mode == "custom":
                    on_event(mapper.event(chunk["kind"], **(chunk.get("data") or {})))
                    continue
                for node, update in chunk.items():
                    if node == "__interrupt__":
                        pending = update[0].value
                        continue
                    for ev in mapper.events(node, update):
                        if ev["kind"] == "report":
                            ev["data"]["usage"] = getattr(llm, "usage", None)
                        on_event(ev)
                if cancelled():
                    stopped = True
                    break
```

and change the first line of the `EventMapper` docstring to:

```python
    """Turns graph.stream(stream_mode=["updates", "custom"]) chunks into UI events
```

- [ ] **Step 4: Run the runner tests, expect PASS**

Run: `.venv/bin/python -m pytest tests/unit/test_runner.py -q`
Expected: all pass (the existing run_request tests now go through the list-mode stream).

- [ ] **Step 5: Commit**

```bash
git add salome_agent/runner.py tests/unit/test_runner.py
git commit -m "feat: drive() relays custom stream chunks from nodes as events"
```

### Task 2: vision progress events

**Files:**
- Modify: `salome_agent/nodes/vision.py` (`describe_images`)
- Modify: `salome_agent/graph.py` (`_describe_image_node`)
- Test: `tests/unit/test_vision.py`, `tests/unit/test_runner.py`

**Interfaces:**
- Consumes: Task 1 (custom chunks reach `on_event`).
- Produces: `describe_images(request, images, llm, fix_retries=2, on_progress=None)`; `on_progress(kind, **data)` gets
  - `("vision_start", images=int, sizes=["WxH", ...], model=str)`
  - `("vision_check", attempt=int (1-based), of=int (fix_retries), errors=[str, ...])` — each error `"P2: message"` or `"message"`
  - `("vision_done", parts=int, conflicts=int, seconds=float)`
  
  Events on the wire: `{"kind": "vision_start" | "vision_check" | "vision_done", "run_id", "data": {...as above}}`.

- [ ] **Step 1: Write the failing tests** (append to `tests/unit/test_vision.py`)

```python
def _recorder():
    seen = []
    return seen, lambda kind, **data: seen.append((kind, data))


def test_a_clean_read_reports_start_and_done():
    llm = MagicMock()
    llm.endpoint.return_value.model = "reader"
    llm.chat.return_value = box_spec()
    seen, on_progress = _recorder()
    describe_images("make this", [_uri(_png(510, 550)), "x"], llm, on_progress=on_progress)
    llm.endpoint.assert_called_with("vision")
    assert seen[0] == ("vision_start", {"images": 2, "sizes": ["510x550"], "model": "reader"})
    kind, data = seen[1]
    assert kind == "vision_done" and len(seen) == 2
    assert (data["parts"], data["conflicts"]) == (len(box_spec()["parts"]), 0)
    assert isinstance(data["seconds"], float)


def test_each_fix_round_reports_its_problems():
    bad = box_spec()
    bad["parts"][1]["ops"] = [{"op": "fuse", "with": "P9"}]
    llm = MagicMock()
    llm.chat.side_effect = [bad, box_spec()]
    seen, on_progress = _recorder()
    describe_images("make this", ["x"], llm, fix_retries=2, on_progress=on_progress)
    assert [k for k, _ in seen] == ["vision_start", "vision_check", "vision_done"]
    assert seen[1][1] == {"attempt": 1, "of": 2,
                          "errors": ["P2: ops[1].with must name another part (P1, P2)"]}
    assert seen[2][1]["conflicts"] == 0


def test_problems_left_after_the_last_round_are_counted_as_conflicts():
    bad = box_spec()
    bad["parts"][1]["ops"] = [{"op": "fuse", "with": "P9"}]
    llm = MagicMock()
    llm.chat.return_value = bad
    seen, on_progress = _recorder()
    describe_images("make this", ["x"], llm, fix_retries=1, on_progress=on_progress)
    assert [k for k, _ in seen] == ["vision_start", "vision_check", "vision_done"]
    assert seen[2][1]["conflicts"] == 1


def test_no_callback_no_endpoint_lookup():
    llm = MagicMock()
    llm.chat.return_value = box_spec()
    describe_images("make this", ["x"], llm)
    llm.endpoint.assert_not_called()
```

- [ ] **Step 2: Run them, expect FAIL**

Run: `.venv/bin/python -m pytest tests/unit/test_vision.py -q`
Expected: the 4 new tests FAIL (`unexpected keyword argument 'on_progress'`); the old ones pass.

- [ ] **Step 3: Implement `describe_images`** — add `import time` at the top of `salome_agent/nodes/vision.py`, then replace the function body:

```python
def describe_images(request: str, images: list[str], llm, fix_retries: int = 2,
                    on_progress=None) -> dict:
    """Run the vision agent: one multimodal call that turns the reference image(s)
    into a structured spec, re-asked with the validator's errors up to
    fix_retries times; errors still left are attached as conflicts.
    `on_progress(kind, **data)`: vision_start / vision_check / vision_done, for a
    front end to show the step while it runs."""
    t0 = time.monotonic()

    def progress(kind, **data):
        if on_progress is not None:
            on_progress(kind, **data)

    def done(spec, conflicts):
        parts = spec.get("parts") if isinstance(spec, dict) else None
        progress("vision_done", parts=len(parts) if isinstance(parts, list) else 0,
                 conflicts=conflicts, seconds=round(time.monotonic() - t0, 1))
        return spec

    text = ("User request (context only -- describe the image(s), do not plan):\n"
            + request)
    # A model that measures in pixels otherwise guesses the image size, and a
    # wrong guess skews every scale it derives.
    dims = [image_size(uri) for uri in images]
    sizes = [f"image {i}: {s[0]} x {s[1]} px" for i, s in enumerate(dims, 1) if s]
    if sizes:
        text += "\n\nImage size (width x height): " + "; ".join(sizes) + "."
    if on_progress is not None:
        progress("vision_start", images=len(images),
                 sizes=[f"{s[0]}x{s[1]}" for s in dims if s],
                 model=str(llm.endpoint("vision").model))
    messages = [{"role": "system", "content": VISION_SYSTEM_PROMPT},
                {"role": "user", "content": with_images(text, images)}]
    spec = llm.chat(messages=messages, module="vision")
    for attempt in range(fix_retries + 1):
        errors = validate_spec(spec)
        if not errors:
            return done(spec, 0)
        if attempt == fix_retries:
            log.warning("vision spec still has %d problem(s); passing them on as conflicts",
                        len(errors))
            return done(attach_conflicts(spec, errors), len(errors))
        log.info("vision spec has %d problem(s), asking for a fix (%d/%d):\n%s",
                 len(errors), attempt + 1, fix_retries, format_errors(errors))
        progress("vision_check", attempt=attempt + 1, of=fix_retries,
                 errors=[f"{pid}: {msg}" if pid else msg for pid, msg in errors])
        messages = messages + [
            {"role": "assistant", "content": json.dumps(spec, ensure_ascii=False)},
            {"role": "user", "content":
                "The spec has these problems:\n" + format_errors(errors)
                + "\nRe-read the image(s) where needed, fix them, and answer with the "
                  "whole corrected JSON spec only."}]
        spec = llm.chat(messages=messages, module="vision")
    return spec
```

- [ ] **Step 4: Run vision tests, expect PASS**

Run: `.venv/bin/python -m pytest tests/unit/test_vision.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing end-to-end test** (append to `tests/unit/test_runner.py`)

```python
def test_vision_progress_reaches_on_event_before_the_plan(tmp_path, monkeypatch):
    from tests.unit.test_vision_spec import box_spec
    llm = MagicMock()
    llm.usage = None
    llm.endpoint.return_value.model = "reader"
    llm.chat.side_effect = lambda **kw: box_spec() if kw.get("module") == "vision" else ONE_STAGE
    _fake_llm(monkeypatch, llm)
    events = []
    run_request("x", _config(tmp_path), client=None, on_event=events.append,
                on_gate=lambda p: {"action": "abort"}, run_id="r1",
                reference_images=["data:image/png;base64,AAAA"])
    kinds = [e["kind"] for e in events if e["kind"] != "reasoning"]
    assert kinds[:3] == ["vision_start", "vision_done", "plan"]
    start = next(e for e in events if e["kind"] == "vision_start")
    assert start["data"] == {"images": 1, "sizes": [], "model": "reader"}
```

- [ ] **Step 6: Run it, expect FAIL**

Run: `.venv/bin/python -m pytest tests/unit/test_runner.py::test_vision_progress_reaches_on_event_before_the_plan -q`
Expected: FAIL (`kinds[:3] == ["plan", "aborted"]`: the node does not report yet).

- [ ] **Step 7: Wire the node** — in `salome_agent/graph.py` `_describe_image_node`, after `from salome_agent.nodes.vision import describe_images` add `from langgraph.config import get_stream_writer`, and change the call:

```python
    write = get_stream_writer()
    try:
        spec = describe_images(state["user_request"], images, llm, fix_retries=retries,
                               on_progress=lambda kind, **data: write({"kind": kind, "data": data}))
```

(`get_stream_writer()` is a no-op writer when the graph is not streamed in `custom` mode, e.g. `invoke()`; checked on LangGraph 1.2.11.)

- [ ] **Step 8: Run the whole unit suite, expect PASS**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: 855 + 6 new = 861 passed, goldens included.

- [ ] **Step 9: Commit**

```bash
git add salome_agent/nodes/vision.py salome_agent/graph.py tests/unit/test_vision.py tests/unit/test_runner.py
git commit -m "feat: the vision step reports start, fix rounds and done as events"
```

### Task 3: vision reasoning source + module names for front ends

**Files:**
- Modify: `salome_agent/runner.py` (`EventMapper.reasoning`)
- Modify: `salome_agent/modules.py` (new `llm_module_names`)
- Test: `tests/unit/test_runner.py`, `tests/unit/test_modules.py`

**Interfaces:**
- Produces: reasoning events from `module == "vision"` carry `source="vision"`, `index=None`. `salome_agent.modules.llm_module_names() -> list[str]`: `["planner", "vision", <registered specialists in registry order>, "amend"]`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_runner.py`:

```python
def test_vision_reasoning_has_its_own_source_with_or_without_a_plan():
    m = EventMapper("r1", "/w/r1")
    assert m.reasoning("vision", 1, "reasoning", "hmm")["data"]["source"] == "vision"
    m.events("plan", {"plan": PLAN})
    d = m.reasoning("vision", 2, "reasoning", "x")["data"]
    assert (d["source"], d["index"]) == ("vision", None)
```

In `tests/unit/test_modules.py`:

```python
def test_llm_module_names_lists_every_name_llm_modules_accepts():
    from salome_agent.modules import llm_module_names
    names = llm_module_names()
    assert names[:2] == ["planner", "vision"] and names[-1] == "amend"
    assert {"geom", "smesh", "paravis"} <= set(names)
    assert len(names) == len(set(names))
```

- [ ] **Step 2: Run them, expect FAIL**

Run: `.venv/bin/python -m pytest tests/unit/test_runner.py::test_vision_reasoning_has_its_own_source_with_or_without_a_plan tests/unit/test_modules.py::test_llm_module_names_lists_every_name_llm_modules_accepts -q`
Expected: FAIL (`'edit' == 'vision'`; `ImportError: cannot import name 'llm_module_names'`).

- [ ] **Step 3: Implement**

`EventMapper.reasoning` in `salome_agent/runner.py`:

```python
        if module == "planner":
            source, index = "planner", None
        elif module == "vision":
            source, index = "vision", None
        elif self.plan:
```

Append to `salome_agent/modules.py`:

```python
def llm_module_names() -> list[str]:
    """Every name llm.modules accepts: the planner, vision, each specialist, and
    amend (chat edits, built per turn so not in MODULES)."""
    _ensure_specialists_registered()
    return ["planner", "vision", *MODULES, "amend"]
```

- [ ] **Step 4: Run the whole unit suite, expect PASS**

Run: `.venv/bin/python -m pytest tests/unit -q`
Expected: 863 passed.

- [ ] **Step 5: Commit, then merge**

```bash
git add salome_agent/runner.py salome_agent/modules.py tests/unit/test_runner.py tests/unit/test_modules.py
git commit -m "feat: vision reasoning has its own source; llm_module_names() for front ends"
git switch main && git merge --no-ff feat/vision-events -m "Merge branch 'feat/vision-events'"
git log --oneline -1   # note this hash: the GUI bump in Task 4 points at it
```

Do not push.

---

## Part 2 — salome-agent-gui

### Task 4: submodule bump + `config_store` modules, advanced knobs, label, drift guard

**Files:**
- Modify: submodule `salome-agent` (bump)
- Modify: `salome_agent_gui/config_store.py`
- Test: `tests/test_config_store.py`

**Interfaces:**
- Consumes: engine `salome_agent.config.LLM_KNOWN_KEYS`, `MODULE_LLM_KEYS`.
- Produces (`config_store`):
  - constants `ROW_KEYS = ("model", "base_url", "api_key", "ssl_cert_file")`, `LLM_INTS` (`{"reasoning_budget": (20000, 0, 200000), "vision_fix_retries": (2, 0, 5), "timeout": (120, 10, 1800)}`), `JSON_ONLY`, `MODULE_JSON_ONLY`.
  - `read_settings(path)` gains keys: `shared_model: bool`, `modules: {name: {model, base_url, api_key, ssl_cert_file: str}}` (from `llm.modules`, or from `gui.parked_modules` while shared), `modules_json_only: {name: [sorted hidden keys]}`, `reasoning_budget: int`, `vision_fix_retries: int`, `timeout: int`.
  - `save_settings(path, fields, run_options=True)` accepts (run options only) `shared_model: bool`, `modules: {name: {ROW_KEYS...}}`, `reasoning_budget`, `vision_fix_retries`, `timeout`. Raises `ValueError("<module>: a different endpoint needs its own API key")` without writing.
  - `model_label(settings: dict) -> tuple[str, str]`: header text after the server part, tooltip (`""` when none).

- [ ] **Step 0: Bump the submodule** (hash = the merge commit from Task 3)

```bash
cd /storage/Projects/salome-agent-gui
git -C salome-agent fetch -q /storage/Projects/salome-agent main
git -C salome-agent checkout -q <merge-hash>
git add salome-agent
git ls-tree HEAD salome-agent   # still the old hash until the commit below
git commit -m "chore: bump salome-agent to <short-hash> (vision events, llm_module_names)"
git ls-tree HEAD salome-agent   # MUST print <merge-hash>
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q   # 137 passed, 32 skipped
```

(Fetching from the local engine path brings in the unpushed merge commit.)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config_store.py`)

```python
from salome_agent.config import LLM_KNOWN_KEYS, MODULE_LLM_KEYS


def _cfg(tmp_path, llm=None, gui=None):
    p = tmp_path / "c.json"
    data = {"llm": {"base_url": "http://h/v1", "model": "shared", "api_key": "k", **(llm or {})},
            "policy": {}}
    if gui is not None:
        data["gui"] = gui
    p.write_text(json.dumps(data))
    return p


def _row(**kw):
    return {"model": "", "base_url": "", "api_key": "", "ssl_cert_file": "", **kw}


def test_no_modules_reads_as_shared_with_advanced_defaults(tmp_path):
    s = cs.read_settings(_cfg(tmp_path))
    assert s["shared_model"] is True and s["modules"] == {} and s["modules_json_only"] == {}
    assert (s["reasoning_budget"], s["vision_fix_retries"], s["timeout"]) == (20000, 2, 120)


def test_rows_read_from_llm_modules_with_hidden_keys_listed(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "reader", "temperature": 0.2,
                                                   "extra_body": {"x": 1}}}})
    s = cs.read_settings(p)
    assert s["shared_model"] is False
    assert s["modules"] == {"vision": _row(model="reader")}
    assert s["modules_json_only"] == {"vision": ["extra_body", "temperature"]}


def test_read_settings_ignores_junk_modules(tmp_path):
    assert cs.read_settings(_cfg(tmp_path, llm={"modules": "vision"}))["modules"] == {}
    s = cs.read_settings(_cfg(tmp_path, llm={"modules": {"vision": "reader", "geom": {"model": "g"}}}))
    assert s["modules"] == {"geom": _row(model="g")}


def test_row_save_writes_only_non_empty_fields_and_keeps_hidden_keys(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "old", "temperature": 0.2}}})
    cs.save_settings(p, {"shared_model": False,
                         "modules": {"vision": _row(model=" reader "), "geom": _row()}})
    assert json.loads(p.read_text())["llm"]["modules"] == {
        "vision": {"model": "reader", "temperature": 0.2}}


def test_clearing_a_row_keeps_hidden_keys_and_drops_an_emptied_entry(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "r", "temperature": 0.2},
                                        "geom": {"model": "g"}}})
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row(), "geom": _row()}})
    assert json.loads(p.read_text())["llm"]["modules"] == {"vision": {"temperature": 0.2}}
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row()}})
    cs.save_settings(p, {"shared_model": False, "modules": {}})
    assert "modules" in json.loads(p.read_text())["llm"]          # temperature still there


def test_unknown_module_entry_survives_a_save(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"visio": {"model": "typo"}}})
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row(model="r")}})
    assert json.loads(p.read_text())["llm"]["modules"] == {
        "visio": {"model": "typo"}, "vision": {"model": "r"}}


def test_shared_parks_the_modules_and_unshared_brings_them_back(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "r", "extra_body": {"x": 1}}}})
    cs.save_settings(p, {"shared_model": True, "modules": {"vision": _row(model="r")}})
    data = json.loads(p.read_text())
    assert "modules" not in data["llm"]
    assert data["gui"]["parked_modules"] == {"vision": {"model": "r", "extra_body": {"x": 1}}}
    s = cs.read_settings(p)
    assert s["shared_model"] is True and s["modules"] == {"vision": _row(model="r")}
    cs.save_settings(p, {"shared_model": False, "modules": {"vision": _row(model="r")}})
    data = json.loads(p.read_text())
    assert data["llm"]["modules"] == {"vision": {"model": "r", "extra_body": {"x": 1}}}
    assert "parked_modules" not in data["gui"]


def test_park_merges_and_active_wins(tmp_path):
    p = _cfg(tmp_path, llm={"modules": {"vision": {"model": "new"}}},
             gui={"parked_modules": {"vision": {"model": "old", "temperature": 0.1}}})
    cs.save_settings(p, {"shared_model": True, "modules": {"vision": _row(model="new")}})
    assert json.loads(p.read_text())["gui"]["parked_modules"] == {
        "vision": {"model": "new", "temperature": 0.1}}


def test_other_endpoint_without_key_is_refused_and_nothing_written(tmp_path):
    p = _cfg(tmp_path)
    before = p.read_text()
    with pytest.raises(ValueError, match="vision: a different endpoint needs its own API key"):
        cs.save_settings(p, {"shared_model": False,
                             "modules": {"vision": _row(model="r", base_url="http://other/v1")}})
    assert p.read_text() == before


def test_same_host_row_needs_no_key(tmp_path):
    p = _cfg(tmp_path)
    cs.save_settings(p, {"shared_model": False,
                         "modules": {"vision": _row(model="r", base_url="http://h/v1/")}})
    assert json.loads(p.read_text())["llm"]["modules"]["vision"]["base_url"] == "http://h/v1/"


def test_parked_rows_are_not_checked_for_keys(tmp_path):
    p = _cfg(tmp_path)
    cs.save_settings(p, {"shared_model": True,
                         "modules": {"vision": _row(base_url="http://other/v1")}})
    assert json.loads(p.read_text())["gui"]["parked_modules"]["vision"] == {
        "base_url": "http://other/v1"}


def test_advanced_knobs_clamp_and_lock_with_run_options(tmp_path):
    p = _cfg(tmp_path)
    cs.save_settings(p, {"reasoning_budget": 999999, "vision_fix_retries": -3, "timeout": 5})
    llm = json.loads(p.read_text())["llm"]
    assert (llm["reasoning_budget"], llm["vision_fix_retries"], llm["timeout"]) == (200000, 0, 10)
    cs.save_settings(p, {"reasoning_budget": 0, "shared_model": False,
                         "modules": {"vision": _row(model="r")}}, run_options=False)
    data = json.loads(p.read_text())
    assert data["llm"]["reasoning_budget"] == 200000 and "modules" not in data["llm"]


def test_model_label_names_one_override_and_counts_several():
    base = {"model": "shared", "shared_model": False}
    assert cs.model_label({"model": "shared", "shared_model": True,
                           "modules": {"vision": _row(model="r")}}) == ("shared", "")
    assert cs.model_label(dict(base, modules={"vision": _row(model="r")})) == (
        "shared · vision: r", "vision: r")
    assert cs.model_label(dict(base, modules={"vision": _row(base_url="http://o")})) == (
        "shared · vision: shared", "vision: shared")
    label, tip = cs.model_label(dict(base, modules={"vision": _row(model="r"),
                                                    "geom": _row(model="g"), "smesh": _row()}))
    assert label == "shared · +2 overrides" and tip == "vision: r\ngeom: g"
    assert cs.model_label({"model": "", "shared_model": True}) == ("?", "")


def test_every_engine_llm_key_is_in_the_form_or_json_only():
    form = set(cs.KEY_FIELDS) | set(cs.LLM_INTS) | {"modules"}
    missing = sorted(LLM_KNOWN_KEYS - form - cs.JSON_ONLY)
    assert not missing, f"engine llm keys with no place in the drawer: {missing}"
    missing = sorted(MODULE_LLM_KEYS - set(cs.ROW_KEYS) - cs.MODULE_JSON_ONLY)
    assert not missing, f"engine llm.modules keys with no place in the drawer: {missing}"
```

- [ ] **Step 2: Run them, expect FAIL**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_config_store.py -q`
Expected: the new tests FAIL (`KeyError: 'shared_model'`, `AttributeError: ... 'model_label'`, ...).

- [ ] **Step 3: Implement** in `salome_agent_gui/config_store.py`

After `POLICY_INTS`, add:

```python
# llm int knobs the Advanced fold edits: (default, min, max)
LLM_INTS = {"reasoning_budget": (20000, 0, 200000), "vision_fix_retries": (2, 0, 5),
            "timeout": (120, 10, 1800)}
# llm.modules.<m> keys a module row edits; the others are kept as they are
ROW_KEYS = ("model", "base_url", "api_key", "ssl_cert_file")
# engine keys left to Edit JSON (tests/test_config_store.py checks the engine's list)
JSON_ONLY = {"extra_headers", "extra_body", "module_extra_body", "json_retries", "max_retries",
             "temperature"}
MODULE_JSON_ONLY = {"extra_headers", "extra_body", "temperature", "timeout"}
```

Replace `_policy_int` with a table-driven helper and update its call:

```python
def _clamped(section: dict, key: str, table: dict) -> int:
    default, lo, hi = table[key]
    value = _int(section.get(key))
    return default if value is None else max(lo, min(hi, value))
```

(in `read_settings`: `**{k: _clamped(policy, k, POLICY_INTS) for k in POLICY_INTS},`)

Add the module helpers above `read_settings`:

```python
def _modules(value) -> dict:
    """llm.modules / gui.parked_modules as {name: dict}; anything else dropped."""
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, dict)}


def _merge(into: dict, src: dict) -> dict:
    for name, d in src.items():
        into[name] = {**into.get(name, {}), **d}
    return into


def _save_modules(data: dict, shared: bool, rows) -> None:
    """The rows go to llm.modules, or to gui.parked_modules while every module
    uses the shared model (the engine never reads `gui`). Keys the form does not
    show are kept."""
    llm, gui = data.setdefault("llm", {}), data.setdefault("gui", {})
    store = _merge(_modules(gui.get("parked_modules")), _modules(llm.get("modules")))
    for name, row in (rows if isinstance(rows, dict) else {}).items():
        if not isinstance(row, dict):
            continue
        d = dict(store.get(name, {}))
        for key in ROW_KEYS:
            value = str(row.get(key) or "").strip()
            if value:
                d[key] = value
            else:
                d.pop(key, None)
        if d:
            store[name] = d
        else:
            store.pop(name, None)
    if not shared:
        # another host never gets the shared key (salome_agent.llm._build_endpoint)
        shared_url = str(llm.get("base_url") or "").rstrip("/")
        for name, d in store.items():
            url = str(d.get("base_url") or "").rstrip("/")
            if url and url != shared_url and not d.get("api_key"):
                raise ValueError(f"{name}: a different endpoint needs its own API key")
    llm.pop("modules", None)
    gui.pop("parked_modules", None)
    if store:
        if shared:
            gui["parked_modules"] = store
        else:
            llm["modules"] = store


def model_label(settings: dict) -> tuple[str, str]:
    """The model part of the header, and a tooltip listing each override."""
    shared = settings.get("model") or "?"
    if settings.get("shared_model", True):
        return shared, ""
    over = [(name, row.get("model") or shared)
            for name, row in (settings.get("modules") or {}).items() if any(row.values())]
    if not over:
        return shared, ""
    tip = "\n".join(f"{name}: {model}" for name, model in over)
    if len(over) == 1:
        return f"{shared} · {over[0][0]}: {over[0][1]}", tip
    return f"{shared} · +{len(over)} overrides", tip
```

In `read_settings`, after the `llm, policy, gui = ...` line add:

```python
    active = _modules(llm.get("modules"))
    shown = active or _modules(gui.get("parked_modules"))
```

and add to the returned dict:

```python
        "shared_model": not active,
        "modules": {name: {k: str(d.get(k) or "") for k in ROW_KEYS} for name, d in shown.items()},
        "modules_json_only": {name: sorted(set(d) - set(ROW_KEYS))
                              for name, d in shown.items() if set(d) - set(ROW_KEYS)},
        **{k: _clamped(llm, k, LLM_INTS) for k in LLM_INTS},
```

In `save_settings`, inside `if run_options:` (after the `POLICY_INTS` loop) add:

```python
        for key, (_, lo, hi) in LLM_INTS.items():
            value = _int(fields.get(key))
            if value is not None:
                data["llm"][key] = max(lo, min(hi, value))
        if "shared_model" in fields:
            _save_modules(data, bool(fields["shared_model"]), fields.get("modules"))
```

and update the docstring's first line to `"""Key fields and theme always; run options (policy, gui batch/verbose, models, advanced llm knobs)`.

- [ ] **Step 4: Run, expect PASS**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: 151 passed (137 + 14), 32 skipped.

- [ ] **Step 5: Commit**

```bash
git add salome_agent_gui/config_store.py tests/test_config_store.py
git commit -m "feat: config_store reads and writes per-module models and the advanced llm knobs"
```

### Task 5: bridge sends module names and the override-aware header

**Files:**
- Modify: `salome_agent_gui/bridge.py` (`_settings`, `probe`)
- Modify: `salome_agent_gui/web/app.js` (`setStatus`: tooltip)
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: Task 4 `config_store.model_label`, `read_settings` new keys; engine `llm_module_names()`.
- Produces: `setSettings` payload gains `module_names: list[str]` (plus the Task 4 keys); `setStatus` payload gains `title: str` (tooltip for the status label).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_bridge.py`, reusing its `make`, `bridges`, `cfg_path` fixtures and the `p.last(...)` page recorder)

```python
def test_settings_carry_the_engine_module_names(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    b.probe()
    b.saveSettings(json.dumps({"theme": "dark"}))
    names = p.last("setSettings")["module_names"]
    assert names[:2] == ["planner", "vision"] and "geom" in names


def test_header_names_the_vision_override(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    b.saveSettings(json.dumps({"shared_model": False,
                               "modules": {"vision": {"model": "reader"}}}))
    st = p.last("setStatus")
    assert st["label"].endswith("· vision: reader") and st["title"] == "vision: reader"
```

(If `json` is not imported in `tests/test_bridge.py`, add `import json`.)

- [ ] **Step 2: Run, expect FAIL**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_bridge.py -q`
Expected: the 2 new tests FAIL (`KeyError: 'module_names'`; label lacks the override).

- [ ] **Step 3: Implement** in `salome_agent_gui/bridge.py`

```python
    def _settings(self) -> dict:
        from salome_agent.modules import llm_module_names

        s = config_store.read_settings(self.config_path)
        return {**s, "locked": self.worker is not None, "config_path": str(self.config_path),
                "module_names": llm_module_names()}
```

In `probe()`, replace the two label lines:

```python
            models, tip = config_store.model_label(config_store.read_settings(self.config_path))
            label = f"{str(hs.get('mode', '?')).upper()} :{hs.get('port', '?')} · {models}"
            self._status = {"state": "connected", "label": label, "detail": "", "title": tip}
```

In `salome_agent_gui/web/app.js` `setStatus`, after the `status-label` textContent line:

```js
  $("status-label").title = p.title || "";
```

- [ ] **Step 4: Run, expect PASS**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: 153 passed, 32 skipped.

- [ ] **Step 5: Commit**

```bash
git add salome_agent_gui/bridge.py salome_agent_gui/web/app.js tests/test_bridge.py
git commit -m "feat: the header names model overrides; settings carry the engine module names"
```

### Task 6: drawer — "Same model for every module", module rows, Advanced

**Files:**
- Modify: `salome_agent_gui/web/index.html` (Model section)
- Modify: `salome_agent_gui/web/app.js` (settings block, `wire()`)
- Modify: `salome_agent_gui/web/app.css`
- Modify: `tools/page_fixtures.py` (SETTINGS, new state)
- Test: `tests/test_page.py` (`@pytest.mark.web`)

**Interfaces:**
- Consumes: `setSettings` payload from Task 5 (`shared_model`, `modules`, `modules_json_only`, `module_names`, `reasoning_budget`, `vision_fix_retries`, `timeout`, `locked`).
- Produces: `bridge.saveSettings` JSON gains, when not locked, `shared_model: bool`, `modules: {name: {model, base_url, api_key, ssl_cert_file}}`, `reasoning_budget`, `vision_fix_retries`, `timeout` (ints or `null`).

- [ ] **Step 1: Fixtures** — in `tools/page_fixtures.py`, extend `SETTINGS` and add a state:

```python
SETTINGS = {"base_url": "http://llm.example/v1", "model": "auto", "api_key": "sk-test",
            "ssl_cert_file": "~/certs/ca.pem", "on_stage_failure": "abort", "tool_selection": "hints", "batch": False,
            "verbose": 0, "theme": "system", "locked": False,
            "config_path": "~/.config/salome/salome-agent.json",
            "shared_model": True, "modules": {}, "modules_json_only": {},
            "module_names": ["planner", "vision", "geom", "smesh", "paravis", "amend"],
            "reasoning_budget": 20000, "vision_fix_retries": 2, "timeout": 120}
MODELS_SETTINGS = dict(SETTINGS, shared_model=False, modules={
    "vision": {"model": "drawing-reader", "base_url": "http://reader.example/v1",
               "api_key": "sk-reader", "ssl_cert_file": ""},
    "visio": {"model": "typo", "base_url": "", "api_key": "", "ssl_cert_file": ""}},
    modules_json_only={"vision": ["extra_body"]})
```

and in `STATES` add:

```python
    "settings-models": [("setSettings", MODELS_SETTINGS), ("setStatus", STATUS_OK),
                        ("setBusy", IDLE_OPEN),
                        ("__js__", "document.body.classList.add('settings-open');"
                                   "document.getElementById('set-advanced').open = true; true")],
```

- [ ] **Step 2: Write the failing page tests** (append to `tests/test_page.py`; add `MODELS_SETTINGS` to the `tools.page_fixtures` import)

```python
def saved_settings(qtbot, fake):
    qtbot.waitUntil(lambda: any(c[0] == "saveSettings" for c in fake.calls), timeout=3000)
    return [c for c in fake.calls if c[0] == "saveSettings"][-1][1]


def test_shared_model_hides_the_rows_and_saves_them_anyway(qtbot, page):
    view, fake = page
    wait_js(qtbot, view, "document.getElementById('module-rows').hidden")
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('btn-save').click(); true")
    saved = saved_settings(qtbot, fake)
    assert saved["shared_model"] is True
    assert (saved["reasoning_budget"], saved["vision_fix_retries"], saved["timeout"]) == (20000, 2, 120)
    assert set(saved["modules"]) == {"planner", "vision", "geom", "smesh", "paravis", "amend"}


def test_module_rows_follow_the_engine_list_plus_unknown_entries(qtbot, page):
    view, fake = page
    fake.emit("setSettings", MODELS_SETTINGS)
    wait_js(qtbot, view, "!document.getElementById('module-rows').hidden")
    names = run_js(qtbot, view, "[...document.querySelectorAll('.mod-row')]"
                                ".map(r => r.dataset.module).join(',')")
    assert names == "planner,vision,geom,smesh,paravis,amend,visio"
    assert run_js(qtbot, view, "document.querySelector('.mod-row[data-module=amend] .mod-name')"
                               ".textContent") == "Chat edits"
    assert run_js(qtbot, view, "document.querySelector('.mod-row[data-module=vision] .json-only')"
                               ".textContent") == "also set in JSON: extra_body"
    assert run_js(qtbot, view, "!document.querySelector('.mod-row[data-module=vision] "
                               ".mod-endpoint').hidden") is True
    assert run_js(qtbot, view, "document.querySelector('.mod-row[data-module=geom] "
                               ".mod-endpoint').hidden") is True


def test_other_endpoint_without_key_keeps_the_drawer_open(qtbot, page):
    view, fake = page
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('set-shared').click();"
                        "const r = document.querySelector('.mod-row[data-module=vision]');"
                        "r.querySelector('.linkish').click();"
                        "r.querySelector('input[data-key=model]').value = 'reader';"
                        "r.querySelector('input[data-key=base_url]').value = 'http://other/v1';"
                        "document.getElementById('btn-save').click(); true")
    wait_js(qtbot, view, "!document.getElementById('models-error').hidden")
    assert "Vision: a different endpoint needs its own API key" in run_js(
        qtbot, view, "document.getElementById('models-error').textContent")
    assert run_js(qtbot, view, "document.body.classList.contains('settings-open')") is True
    assert not any(c[0] == "saveSettings" for c in fake.calls)
    run_js(qtbot, view, "document.querySelector('.mod-row[data-module=vision] "
                        "input[data-key=api_key]').value = 'sk-2';"
                        "document.getElementById('btn-save').click(); true")
    saved = saved_settings(qtbot, fake)
    assert saved["shared_model"] is False
    assert saved["modules"]["vision"] == {"model": "reader", "base_url": "http://other/v1",
                                          "api_key": "sk-2", "ssl_cert_file": ""}


def test_models_and_advanced_lock_with_the_run_options(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(MODELS_SETTINGS, locked=True))
    wait_js(qtbot, view, "document.getElementById('set-budget').disabled")
    assert run_js(qtbot, view, "document.getElementById('set-shared').classList"
                               ".contains('disabled')") is True
    assert run_js(qtbot, view, "[...document.querySelectorAll('#module-rows input')]"
                               ".every(i => i.disabled)") is True
    run_js(qtbot, view, "document.getElementById('set-shared').click(); true")
    assert run_js(qtbot, view, "document.getElementById('set-shared').classList"
                               ".contains('on')") is False
```

- [ ] **Step 3: Run, expect FAIL**

Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest tests/test_page.py -q -m web`
Expected: the 4 new tests FAIL (no `module-rows` element); the others pass.

- [ ] **Step 4: HTML** — in `salome_agent_gui/web/index.html`, replace the Model section's title line and append after the CA certificate field (inside the same `<div>`):

```html
      <div class="section-title">Model <span class="lock-note" id="model-lock" hidden>— modules and advanced locked while a conversation is open</span></div>
```

```html
      <div class="toggle-row"><div><div class="t-label">Same model for every module</div><div class="t-help">Off: choose a model, or another endpoint, per module (e.g. a drawing reader for vision)</div></div><span class="switch" id="set-shared"></span></div>
      <div id="module-rows" class="module-rows" hidden></div>
      <div class="err-note" id="models-error" hidden></div>
      <details class="advanced" id="set-advanced"><summary>Advanced</summary>
        <div class="row2">
          <div class="field"><label for="set-budget">Reasoning budget (approx tokens, 0 = off)</label><input id="set-budget" type="number" min="0" max="200000" step="1000"></div>
          <div class="field"><label for="set-vision-fix">Vision fix rounds</label><input id="set-vision-fix" type="number" min="0" max="5" step="1"></div>
        </div>
        <div class="field"><label for="set-timeout">LLM timeout (s)</label><input id="set-timeout" type="number" min="10" max="1800" step="10"></div>
      </details>
```

- [ ] **Step 5: JS** — in `salome_agent_gui/web/app.js`, settings block. Add above `lockRunOptions`:

```js
const MODULE_LABEL = { planner: "Planner", vision: "Vision", geom: "GEOM", smesh: "SMESH",
                       paravis: "PARAVIS", amend: "Chat edits" };
const ENDPOINT_FIELDS = [["base_url", "Base URL"], ["api_key", "API key", "password"],
                         ["ssl_cert_file", "CA certificate file"]];

function moduleRow(name, row, jsonOnly, sharedModel) {
  const r = el("div", "mod-row");
  r.dataset.module = name;
  const line = el("div", "mod-line");
  line.appendChild(el("span", "mod-name", MODULE_LABEL[name] || name));
  const model = el("input", "mod-model");
  model.dataset.key = "model";
  model.placeholder = sharedModel || "shared model";
  model.value = row.model || "";
  line.appendChild(model);
  const link = el("button", "linkish", "other endpoint…");
  link.type = "button";
  line.appendChild(link);
  r.appendChild(line);
  const ep = el("div", "mod-endpoint");
  ep.hidden = !(row.base_url || row.api_key || row.ssl_cert_file);
  for (const [key, label, type] of ENDPOINT_FIELDS) {
    const f = el("div", "field");
    f.appendChild(el("label", null, label));
    const input = el("input");
    input.dataset.key = key;
    if (type) input.type = type;
    input.value = row[key] || "";
    f.appendChild(input);
    ep.appendChild(f);
  }
  ep.appendChild(el("div", "t-help", "A different endpoint does not reuse the shared key."));
  link.addEventListener("click", () => { ep.hidden = !ep.hidden; });
  r.appendChild(ep);
  if (jsonOnly && jsonOnly.length) {
    r.appendChild(el("div", "t-help json-only", `also set in JSON: ${jsonOnly.join(", ")}`));
  }
  return r;
}

function renderModuleRows(s) {
  const host = $("module-rows");
  host.textContent = "";
  const rows = s.modules || {};
  const names = [...(s.module_names || [])];
  for (const n of Object.keys(rows)) if (!names.includes(n)) names.push(n);
  for (const n of names) {
    host.appendChild(moduleRow(n, rows[n] || {}, (s.modules_json_only || {})[n], s.model));
  }
}

function readModuleRows() {
  const out = {};
  for (const r of $("module-rows").querySelectorAll(".mod-row")) {
    const row = {};
    for (const input of r.querySelectorAll("input[data-key]")) {
      row[input.dataset.key] = input.dataset.key === "api_key" ? input.value : input.value.trim();
    }
    out[r.dataset.module] = row;
  }
  return out;
}

// mirrors config_store._save_modules: another host never gets the shared key
function modulesError(shared, rows, sharedUrl) {
  if (shared) return "";
  const base = sharedUrl.replace(/\/+$/, "");
  for (const [name, r] of Object.entries(rows)) {
    const url = (r.base_url || "").replace(/\/+$/, "");
    if (url && url !== base && !r.api_key) {
      return `${MODULE_LABEL[name] || name}: a different endpoint needs its own API key`;
    }
  }
  return "";
}
```

`lockRunOptions` becomes:

```js
function lockRunOptions(locked) {
  state.locked = locked;
  for (const id of ["set-on-failure", "set-tools", "set-verbose", "set-detail", "set-cadence",
                    "set-exec-retries", "set-cap", "set-budget", "set-vision-fix",
                    "set-timeout"]) $(id).disabled = locked;
  for (const input of $("module-rows").querySelectorAll("input")) input.disabled = locked;
  $("set-batch").classList.toggle("disabled", locked);
  $("set-shared").classList.toggle("disabled", locked);
  $("auto").classList.toggle("disabled", locked);
  $("run-lock").hidden = !locked;
  $("model-lock").hidden = !locked;
}
```

In `setSettings`, before `$("config-path")...`:

```js
  const shared = s.shared_model !== false;
  $("set-shared").classList.toggle("on", shared);
  renderModuleRows(s);
  $("module-rows").hidden = shared;
  $("models-error").hidden = true;
  $("set-budget").value = String(s.reasoning_budget ?? 20000);
  $("set-vision-fix").value = String(s.vision_fix_retries ?? 2);
  $("set-timeout").value = String(s.timeout ?? 120);
```

In `saveSettings`, replace the `if (!state.locked) { ... }` block:

```js
  if (!state.locked) {
    const shared = $("set-shared").classList.contains("on");
    const modules = readModuleRows();
    const err = modulesError(shared, modules, out.base_url);
    if (err) {
      $("models-error").textContent = err;
      $("models-error").hidden = false;
      return;
    }
    Object.assign(out, {
      batch: $("set-batch").classList.contains("on"),
      on_stage_failure: $("set-on-failure").value,
      tool_selection: $("set-tools").value,
      verbose: parseInt($("set-verbose").value, 10),
      plan_detail: $("set-detail").value,
      verify_cadence: $("set-cadence").value,
      exec_retries: parseInt($("set-exec-retries").value, 10),
      tool_iteration_cap: parseInt($("set-cap").value, 10),
      shared_model: shared,
      modules,
      reasoning_budget: parseInt($("set-budget").value, 10),
      vision_fix_retries: parseInt($("set-vision-fix").value, 10),
      timeout: parseInt($("set-timeout").value, 10),
    });
  }
```

In `wire()`, next to the `set-reasoning` listener:

```js
  $("set-shared").addEventListener("click", () => {
    if (state.locked) return;
    $("module-rows").hidden = $("set-shared").classList.toggle("on");
    $("models-error").hidden = true;
  });
```

- [ ] **Step 6: CSS** — append to `salome_agent_gui/web/app.css`:

```css
.module-rows { display: flex; flex-direction: column; gap: 8px; margin: 4px 0 10px; }
.mod-row { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; background: var(--surface-2); }
.mod-line { display: flex; align-items: center; gap: 8px; }
.mod-name { flex: none; width: 76px; font-size: 12.5px; color: var(--text-2); }
.mod-model { flex: 1; min-width: 0; }
.mod-line input { padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font: inherit; font-size: 12.5px; }
.mod-line input:disabled, .mod-endpoint input:disabled { opacity: .5; }
.linkish { flex: none; border: 0; background: none; padding: 0; color: var(--accent-text); font: inherit; font-size: 12px; cursor: pointer; }
.mod-endpoint { margin-top: 8px; }
.mod-row .t-help { font-size: 12px; color: var(--text-3); }
.json-only { margin-top: 6px; }
.err-note { margin-bottom: 10px; padding: 8px 10px; border-radius: 8px; background: var(--err-soft); color: var(--err); font-size: 12.5px; }
details.advanced > summary { cursor: pointer; font-size: 13px; color: var(--text-2); margin-bottom: 8px; }
```

- [ ] **Step 7: Run all tests, expect PASS**

Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: web tests all pass (4 new); offscreen 153 passed, skipped count +4.

- [ ] **Step 8: Look at it** — `QT_QPA_PLATFORM=xcb .venv/bin/python tools/render_states.py <scratch-dir>`; open `settings-models-light.png` and `-dark.png`: rows readable, vision endpoint open, `visio` raw row, Advanced open, nothing clipped at drawer width.

- [ ] **Step 9: Commit**

```bash
git add salome_agent_gui/web/index.html salome_agent_gui/web/app.js salome_agent_gui/web/app.css tools/page_fixtures.py tests/test_page.py
git commit -m "feat: settings drawer edits per-module models and the advanced llm knobs"
```

### Task 7: timeline — vision view model

**Files:**
- Modify: `salome_agent_gui/timeline.py` (`RunView`, `reasoning_key`, `to_view_model`)
- Test: `tests/test_timeline.py`

**Interfaces:**
- Consumes: engine events `vision_start` / `vision_check` / `vision_done` (Task 2), reasoning `source="vision"` (Task 3).
- Produces: view model key `"vision"`: `None`, or `{"status": "running"|"done"|"conflicts"|"failed"|"stopped", "images": int, "sizes": [str], "model": str, "checks": [{"attempt", "of", "errors": [str]}], "parts": int|None, "conflicts": int, "started_at": float|None (only while running), "elapsed_s": float|None, "error": str|None, "reasoning": [{"call", "reasoning", "prose"}]}`. Turn-level `vm["reasoning"]` no longer carries the `vision` key.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_timeline.py`)

```python
def _reading(v, t=100.0):
    v.clock = lambda: t
    v.apply(ev("vision_start", images=1, sizes=["1200x800"], model="reader"))


def test_vision_start_check_done():
    v = RunView()
    _reading(v)
    vm = v.to_view_model(0)["vision"]
    assert (vm["status"], vm["sizes"], vm["model"], vm["started_at"]) == (
        "running", ["1200x800"], "reader", 100.0)
    v.apply(ev("vision_check", attempt=1, of=2, errors=["P2: bad", "closure"]))
    v.apply(ev("vision_done", parts=3, conflicts=0, seconds=232.4))
    vm = v.to_view_model(0)["vision"]
    assert vm["status"] == "done" and vm["parts"] == 3 and vm["elapsed_s"] == 232.4
    assert vm["checks"] == [{"attempt": 1, "of": 2, "errors": ["P2: bad", "closure"]}]
    assert vm["started_at"] is None


def test_vision_conflicts_left():
    v = RunView()
    _reading(v)
    v.apply(ev("vision_done", parts=3, conflicts=2, seconds=10.0))
    assert v.to_view_model(0)["vision"]["status"] == "conflicts"


def test_fatal_while_reading_fails_the_card():
    v = RunView()
    _reading(v)
    v.apply(ev("fatal", message="LLM endpoint 404"))
    vm = v.to_view_model(0)["vision"]
    assert (vm["status"], vm["error"]) == ("failed", "LLM endpoint 404")


def test_abort_while_reading_stops_the_card():
    v = RunView()
    _reading(v)
    v.apply(ev("aborted"))
    assert v.to_view_model(0)["vision"]["status"] == "stopped"


def test_fatal_after_reading_leaves_the_card_done():
    v = RunView()
    _reading(v)
    v.apply(ev("vision_done", parts=1, conflicts=0, seconds=3.0))
    v.apply(ev("fatal", message="planner broke"))
    assert v.to_view_model(0)["vision"]["status"] == "done"


def test_no_images_no_vision():
    v = RunView()
    v.apply(ev("vision_check", attempt=1, of=2, errors=["x"]))   # stray: ignored
    v.apply(ev("plan", stages=PLAN))
    assert v.to_view_model(0)["vision"] is None


def test_vision_reasoning_goes_to_the_card_not_the_turn():
    v = RunView()
    _reading(v)
    v.apply(ev("reasoning", source="vision", index=None, call=1, channel="reasoning", text="80 mm"))
    vm = v.to_view_model(0)
    assert vm["vision"]["reasoning"] == [{"call": 1, "reasoning": "80 mm", "prose": ""}]
    assert "vision" not in vm["reasoning"]
```

- [ ] **Step 2: Run, expect FAIL**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_timeline.py -q`
Expected: the 7 new tests FAIL (`KeyError: 'vision'`).

- [ ] **Step 3: Implement** in `salome_agent_gui/timeline.py`

Field on `RunView` (after `reasoning`):

```python
    # the image-reading step: None until vision_start (see _vision_view)
    vision: dict | None = None
```

In `apply()`, new branches before `elif kind == "fatal":`:

```python
        elif kind == "vision_start":
            self.vision = {"status": "running", "images": int(d.get("images") or 0),
                           "sizes": [str(s) for s in d.get("sizes") or []],
                           "model": str(d.get("model") or ""), "checks": [], "parts": None,
                           "conflicts": 0, "started_at": self.clock(), "elapsed_s": None,
                           "error": None}
        elif kind == "vision_check" and self.vision:
            self.vision["checks"].append({"attempt": d.get("attempt"), "of": d.get("of"),
                                          "errors": [str(e) for e in d.get("errors") or []]})
        elif kind == "vision_done" and self.vision:
            conflicts = int(d.get("conflicts") or 0)
            self.vision.update(status="conflicts" if conflicts else "done",
                               parts=d.get("parts"), conflicts=conflicts,
                               elapsed_s=d.get("seconds"))
```

and extend the `fatal` / `aborted` branches:

```python
        elif kind == "fatal":
            self.fatal = d.get("message")
            self._end_vision("failed", d.get("message"))
        elif kind == "aborted":
            self.aborted = True
            self.finished = True
            self._end_vision("stopped")
```

Methods on `RunView`:

```python
    def _end_vision(self, status: str, error=None) -> None:
        if self.vision and self.vision["status"] == "running":
            self.vision.update(status=status, error=error)

    def _vision_view(self) -> dict | None:
        if self.vision is None:
            return None
        v = dict(self.vision, sizes=list(self.vision["sizes"]),
                 checks=[dict(c, errors=list(c["errors"])) for c in self.vision["checks"]],
                 reasoning=_calls(self.reasoning.get("vision")))
        if v["status"] != "running":
            v["started_at"] = None
        return v
```

In `to_view_model`, add `"vision": self._vision_view(),` and change the reasoning filter:

```python
            "reasoning": {k: _calls(v) for k, v in self.reasoning.items()
                          if not k.startswith("stage:") and k != "vision"},
```

`reasoning_key`:

```python
def reasoning_key(d: dict) -> str:
    if d.get("source") == "stage":
        return f"stage:{d.get('index')}"
    if d.get("source") == "vision":
        return "vision"
    return "edit" if d.get("source") == "edit" else "planner"
```

- [ ] **Step 4: Run, expect PASS**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: 160 passed (153 + 7).

- [ ] **Step 5: Commit**

```bash
git add salome_agent_gui/timeline.py tests/test_timeline.py
git commit -m "feat: timeline keeps a view of the image-reading step"
```

### Task 8: the "Reading image" card

**Files:**
- Modify: `salome_agent_gui/web/app.js` (new `visionCard`, `turnNode`, `appendReasoning` host lookup)
- Modify: `salome_agent_gui/web/app.css`
- Modify: `tools/page_fixtures.py` (vision VMs + states)
- Test: `tests/test_page.py`

**Interfaces:**
- Consumes: `vm.vision` from Task 7.
- Produces: `.vision-card[data-status]` above the plan; live `reasoning` events with key `vision` land in its `.vision-reasoning` host.

- [ ] **Step 1: Fixtures** — in `tools/page_fixtures.py`, after `FAILED_VM`:

```python
def _vision(**kw):
    v = {"status": "done", "images": 1, "sizes": ["1200x800"], "model": "drawing-reader",
         "checks": [], "parts": 3, "conflicts": 0, "started_at": None, "elapsed_s": 232.0,
         "error": None, "reasoning": []}
    v.update(kw)
    return v


VISION_CONFLICTS_VM = _vm(3, vision=_vision(
    status="conflicts", conflicts=2,
    checks=[{"attempt": 1, "of": 2, "errors": ["P1: profile is not closed", "R9 - 4X: 3 arcs found"]},
            {"attempt": 2, "of": 2, "errors": ["P1: profile is not closed"]}]),
    stages=[_stage(0, "geom", "Bracket plate with four holes, 5 mm thick")],
    gate={"id": 3, "kind": "plan"})


def vision_running_vm():
    return _vm(3, vision=_vision(status="running", parts=None, elapsed_s=None,
                                 started_at=time.time() - 134,
                                 checks=[{"attempt": 1, "of": 2,
                                          "errors": ["P2: hole overlaps the outline"]}]))
```

In `resolve`, add `if payload == "vision-running": return vision_running_vm()`. In `STATES`:

```python
    "vision-running": BASE + [("setBusy", BUSY), ("addUser", "sketch-message"),
                              ("renderTurn", "vision-running")],
    "vision-conflicts": BASE + [("setBusy", BUSY), ("addUser", "sketch-message"),
                                ("renderTurn", VISION_CONFLICTS_VM)],
```

Also add `"vision": None` to the dict in `_vm` so every fixture VM has the key.

- [ ] **Step 2: Write the failing page tests** (append to `tests/test_page.py`; import `VISION_CONFLICTS_VM`, `vision_running_vm`)

```python
def test_vision_card_runs_with_a_timer_then_shows_conflicts(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", vision_running_vm())
    wait_js(qtbot, view, "!!document.querySelector('.vision-card[data-status=running]')")
    head = run_js(qtbot, view, "document.querySelector('.vision-card .card-head').textContent")
    assert head.startswith("Reading image")
    assert run_js(qtbot, view, "!!document.querySelector('.vision-card [data-start]')") is True
    assert "Fix round 1/2" in run_js(qtbot, view,
                                     "document.querySelector('.vision-card').textContent")
    fake.emit("renderTurn", VISION_CONFLICTS_VM)
    wait_js(qtbot, view, "!!document.querySelector('.vision-card[data-status=conflicts]')")
    text = run_js(qtbot, view, "document.querySelector('.vision-card').textContent")
    assert "Read 3 parts, 2 problems left for the build" in text
    assert run_js(qtbot, view, "!!document.querySelector('.vision-card [data-start]')") is False
    order = run_js(qtbot, view, "[...document.querySelectorAll('.vision-card, .steps')]"
                                ".map(n => n.className).join('|')")
    assert order.startswith("card vision-card")          # the card sits above the plan


def test_vision_errors_are_text(qtbot, page):
    view, fake = page
    vm = dict(VISION_CONFLICTS_VM, vision=dict(VISION_CONFLICTS_VM["vision"], checks=[
        {"attempt": 1, "of": 1, "errors": [EVIL]}], model=EVIL))
    fake.emit("renderTurn", vm)
    wait_js(qtbot, view, "!!document.querySelector('.vision-card')")
    assert run_js(qtbot, view, "document.querySelector('.vision-card img') === null") is True
    assert run_js(qtbot, view, "window.pwned === undefined") is True


def test_vision_reasoning_streams_into_the_card(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, show_reasoning=True))
    fake.emit("renderTurn", vision_running_vm())
    wait_js(qtbot, view, "!!document.querySelector('.vision-card')")
    fake.emit("appendReasoning", {"turn": 3, "key": "vision", "call": 1,
                                  "channel": "reasoning", "text": "the 80 is the width"})
    wait_js(qtbot, view, "document.querySelector('.vision-card details.reasoning') !== null")
    assert "the 80" in run_js(qtbot, view, "document.querySelector('.vision-card').textContent")
```

- [ ] **Step 3: Run, expect FAIL**

Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest tests/test_page.py -q -m web`
Expected: the 3 new tests FAIL (no `.vision-card`).

- [ ] **Step 4: Read `appendReasoning`** (`app.js`, ~line 161) to see how it picks its host (`turn-reasoning` for turn-level keys, the stage row for `stage:<i>`). Add a branch so key `vision` uses the vision card's `.vision-reasoning` host, mirroring the stage branch: `host = wrap.querySelector(".vision-card .vision-reasoning")`, and if absent `return` (the next `renderTurn` draws it from the view model).

- [ ] **Step 5: Implement the card** — in `app.js` after `stagesCard`:

```js
const VISION_TITLE = { running: "Reading image", done: "Image read", conflicts: "Image read",
                       failed: "Could not read the image", stopped: "Image reading stopped" };

function visionCard(vm) {
  const v = vm.vision;
  const card = el("div", "card vision-card");
  card.dataset.status = v.status;
  const head = el("div", "card-head");
  const [cls, icon] = (v.status === "running" ? STEP.running
                       : v.status === "failed" ? STEP.failed
                       : v.status === "stopped" ? STEP.stopped
                       : v.status === "conflicts" ? ["st warn", "warn"] : STEP.ok);
  const st = el("span", cls);
  if (icon) svg(st, icon);
  head.appendChild(st);
  head.appendChild(el("span", null, VISION_TITLE[v.status] || "Image"));
  head.appendChild(el("span", "count", `· ${plural(v.images, "image")}`));
  const meta = el("span", "meta");
  if (v.status === "running" && v.started_at) {
    meta.dataset.start = v.started_at;
    meta.textContent = fmtClock(Date.now() / 1000 - v.started_at);
  } else if (v.elapsed_s !== null && v.elapsed_s !== undefined) {
    meta.textContent = fmtDuration(v.elapsed_s);
  }
  head.appendChild(meta);
  card.appendChild(head);
  const body = el("div", "vision-body");
  const facts = [...(v.sizes || []).map((s) => s.replace("x", "×")), v.model].filter(Boolean);
  if (facts.length) body.appendChild(el("div", "vision-facts", facts.join(" · ")));
  for (const c of v.checks || []) {
    const d = el("details", "vision-check");
    d.appendChild(el("summary", null,
                     `Fix round ${c.attempt}/${c.of}: ${plural(c.errors.length, "problem")}`));
    const ul = el("ul");
    for (const e of c.errors) ul.appendChild(el("li", null, e));
    d.appendChild(ul);
    body.appendChild(d);
  }
  if (v.status === "done") {
    body.appendChild(el("div", "vision-result", `Read ${plural(v.parts || 0, "part")}`));
  } else if (v.status === "conflicts") {
    body.appendChild(el("div", "vision-result warn",
      `Read ${plural(v.parts || 0, "part")}, ${plural(v.conflicts, "problem")} left for the build`));
  } else if (v.status === "failed" && v.error) {
    body.appendChild(el("div", "err", v.error));
  }
  const rhost = el("div", "vision-reasoning");
  if (v.reasoning && v.reasoning.length) rhost.appendChild(reasoningNode(vm.id, "vision", v.reasoning));
  body.appendChild(rhost);
  card.appendChild(body);
  return card;
}
```

In `turnNode`, right after `body.appendChild(turnReasoning);`:

```js
  if (vm.vision) body.appendChild(visionCard(vm));
```

and make the "Thinking…" placeholder skip a running vision step:

```js
  if (!vm.stages.length && !vm.edits.length && !gate && vm.status === "running"
      && !(vm.vision && vm.vision.status === "running")) {
```

- [ ] **Step 6: CSS** — append to `app.css`:

```css
.vision-card { margin-bottom: 10px; }
.vision-card .card-head .meta { margin-left: auto; color: var(--text-3); font-size: 12px; font-weight: 500; }
.vision-card .card-head .st { width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; }
.vision-card .card-head .st svg { width: 12px; height: 12px; }
.st.warn { background: var(--warn-soft); color: var(--warn); }
.vision-body { padding: 8px 14px 10px; display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.vision-facts { color: var(--text-2); font-size: 12.5px; }
.vision-check > summary { cursor: pointer; color: var(--text-2); }
.vision-check ul { margin: 4px 0 0; padding-left: 18px; font-family: var(--mono); font-size: 12px; color: var(--text-2); }
.vision-result.warn { color: var(--warn); }
```

- [ ] **Step 7: Run all tests, expect PASS**

Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all web tests pass (3 new); offscreen 160 passed.

- [ ] **Step 8: Look at it** — `QT_QPA_PLATFORM=xcb .venv/bin/python tools/render_states.py <scratch-dir>`; open `vision-running-*.png` and `vision-conflicts-*.png` in both themes: timer visible, fix rounds collapsed, amber result line, card above the proposed plan.

- [ ] **Step 9: Commit**

```bash
git add salome_agent_gui/web/app.js salome_agent_gui/web/app.css tools/page_fixtures.py tests/test_page.py
git commit -m "feat: a Reading image card shows the vision step live above the plan"
```

### Task 9: live check (manual, with the user)

**Files:** none (no commit unless a bug is found; a bug gets its own failing test first).

- [ ] **Step 1:** User starts SALOME with the agent server; open the chat. In the drawer: untick "Same model for every module", set Vision to the drawing reader model (same gateway, model id only), Save. Header shows `… · vision: <model>`, tooltip lists it.
- [ ] **Step 2:** Attach p1, send. Expect the "Reading image" card with a running timer at once, fix rounds as they happen, then `Read N parts` (or amber conflicts), then the plan below it.
- [ ] **Step 3:** In the run's LLM trace (`-vv` / "LLM trace" log detail), check the vision calls went to the override model and the planner to the shared one.
- [ ] **Step 4:** Tick "Same model for every module" again, Save; check the file: `llm.modules` gone, `gui.parked_modules` holds the vision row; untick: the row comes back filled.
- [ ] **Step 5:** Stop during a vision read once: the card shows "Image reading stopped", no spinner.
