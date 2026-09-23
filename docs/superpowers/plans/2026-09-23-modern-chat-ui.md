# Modern chat UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the salome-agent-gui chat window (settings form + markdown `QTextBrowser` + a row of buttons) with a modern chat page drawn in a `QWebEngineView`, driven by a Python `Bridge` that owns all state.

**Architecture:** `MainWindow` becomes a thin shell around a `QWebEngineView` that loads local files from `salome_agent_gui/web/`. A `Bridge` QObject, registered on a `QWebChannel`, owns the `ConversationWorker`, one `RunView` per agent turn, settings and server status; it pushes JSON (`push(name, json)`) and the page only draws it. `RunView.to_view_model()` turns engine events into the JSON the page renders.

**Tech Stack:** Python 3.14, PyQt5 5.15.11 (Qt 5.15.19), PyQtWebEngine 5.15.7 (Chromium 87), QtWebChannel, pytest + pytest-qt, plain HTML/CSS/JS (no framework, no network).

**Spec:** `docs/superpowers/specs/2026-09-23-modern-chat-ui-design.md` (approved), with the mockup `docs/superpowers/specs/2026-09-23-modern-chat-ui/chat-mockup.html` and its screenshots. Read both before starting a task.

## Model tiers (for subagent-driven execution)

| Task | Implementer | Why |
|---|---|---|
| 1 Dependencies, logo, test harness | haiku | every file given verbatim |
| 2 Module icons | haiku | every file given verbatim |
| 3 Settings in config_store | haiku | every file given verbatim |
| 4 Timeline view model | sonnet | edits an existing module with tests that must keep passing |
| 5 Bridge | sonnet | the state machine; ports 20+ behaviours |
| 6 Web page + loader | sonnet | HTML/CSS/JS renderer; security rule |
| 7 Window shell, cleanup | sonnet | rewires the app, deletes old code |
| 8 Render-states tool | haiku | file given verbatim |
| 9 Live check in SALOME | controller (not a subagent) | needs SAT, SALOME and a person |

Every reviewer is sonnet. **Guard for haiku tasks:** the code blocks are the deliverable. The implementer pastes them unchanged (no renames, no "improvements", no extra helpers). The reviewer checks it mechanically: for each file the task creates, copy the plan's code block to a temporary file and `diff` it against the committed file. Any difference that is not whitespace is a rejection, even when the tests pass.

## Global Constraints

- Repo: **salome-agent-gui** only. salome-agent (the `salome-agent/` submodule) does not change.
- Branch: `feat/modern-chat-ui`, created in Task 1 from `spec/modern-chat-ui` (which carries the spec and this plan). Never commit to `main`.
- Commit messages: a subject line only, no body, no trailers. Stage named files only; never `git add -A` or `git add .`.
- No install paths of the local SALOME (or any machine path) in code, tests, comments or docs. Module icons come from `$<MODULE>_ROOT_DIR` at runtime; they are never copied into the repo.
- Default test command, from the salome-agent-gui root: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`. Qt WebEngine cannot run offscreen (checked: it crashes creating the renderer), so tests that build a real web view carry `@pytest.mark.web` and are skipped unless run with `QT_QPA_PLATFORM=xcb` and a `DISPLAY`: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web`.
- No test outside the `web` marker may construct a `QWebEngineView`.
- Engine and LLM text (stage intents, errors, messages, object names, user text) is **never** inserted into the page as HTML: only `textContent` / `createTextNode`. `innerHTML` / `insertAdjacentHTML` are allowed only with the constant SVG strings in `app.js`.
- CSS and JS must run on Chromium 87: no `color-mix()`, no `:has()`, no optional chaining in CSS, no top-level `await`.
- No network: the page loads only its own files and `qrc:///qtwebchannel/qwebchannel.js`.
- Dependency pins, exactly: `PyQt5-Qt5==5.15.19`, `PyQtWebEngine==5.15.7`, `PyQtWebEngine-Qt5==5.15.19`.
- Bridge push names (Python to page), exactly: `addUser`, `renderTurn`, `addNote`, `setBusy`, `setStatus`, `setSettings`, `setTheme`, `reset`, `replay`. Bridge slots (page to Python), exactly: `ready()`, `send(str)`, `gate(int, str, str)`, `command(str)`, `stop()`, `openFile(str)`, `saveSettings(str)`, `editConfigJson()`, `reconnect()`.
- One deliberate refinement of the spec: pushes made while the page is not ready are dropped, not queued, and `ready()` pushes the full state (settings, theme, status, busy, and the whole transcript as `replay`). Same result for the user, and a page reload after a crash uses the same path.

## Review Focus

1. **Model output containing HTML or script** (a stage intent, an error, a turn message or an object name such as `<img src=x onerror=...>`). A person expects to see the text literally and nothing to run. Pinned by `test_engine_text_is_never_html` (Task 6).
2. **Double-clicking Approve, or clicking a card from an earlier gate.** Exactly one answer must reach the worker. Pinned by `test_stale_gate_id_is_ignored` (Task 5) and `test_approve_click_reaches_the_bridge_and_disables_the_buttons` (Task 6).
3. **The page reloads mid-conversation** (renderer crash). The whole transcript, including the running turn, comes back. Pinned by `test_ready_again_replays_the_whole_transcript` (Task 5).
4. **Saving settings while a conversation is open.** Model, key and theme save; run options (auto-approve, stage failure, tools, log detail) stay as they were. Pinned by `test_save_settings_without_run_options_keeps_them` (Task 3) and `test_run_options_are_refused_while_a_conversation_is_open` (Task 5).
5. **Closing the window during a turn.** The UI must not freeze; the window closes once the worker stops. Pinned by `test_request_close_during_a_turn_does_not_block` (Task 5) and `test_close_during_a_turn_waits_for_the_worker_then_closes` (Task 7).

---

## File Structure

- `pyproject.toml`: new dependency pins; `web/*` package data (Task 1).
- `pytest.ini`: `web` marker (Task 1).
- `tests/conftest.py` (new): imports QtWebEngine before the QApplication exists; skips `web` tests without a display (Task 1).
- `salome_agent_gui/web/salome-s.png` (new, copied from the spec folder) (Task 1); `index.html`, `app.css`, `app.js` (new) (Task 6).
- `salome_agent_gui/module_icons.py` (new): module icon lookup (Task 2).
- `salome_agent_gui/config_store.py`: `read_settings`, `save_settings` (Task 3).
- `salome_agent_gui/timeline.py`: stage times, gate ids, edit ops, `to_view_model()` (Task 4); markdown renderers removed (Task 7).
- `salome_agent_gui/bridge.py` (new): the `Bridge` (Task 5).
- `tests/fakes.py` (new): `FakeConv`, `opener`, `CFG`, shared by bridge and window tests (Task 5).
- `salome_agent_gui/web_view.py` (new): builds the web view and channel, or a fallback panel (Task 6).
- `tools/__init__.py`, `tools/page_fixtures.py` (new): fake bridge and fixture view models for page tests and the render tool (Task 6).
- `salome_agent_gui/main_window.py`: rewritten as the shell (Task 7).
- `salome_agent_gui/app.py`: WebEngine import order (Task 7).
- `salome_agent_gui/chat_view.py`, `tests/test_chat_view.py`: deleted (Task 7).
- `tools/render_states.py` (new) (Task 8).
- `README.md`: updated (Task 7).
- Tests: `tests/test_packaging.py` (1), `tests/test_module_icons.py` (2), `tests/test_config_store.py` (3), `tests/test_timeline.py` (4, 7), `tests/test_bridge.py` (5), `tests/test_page.py`, `tests/test_web_view.py` (6), `tests/test_main_window.py` (7).

---

### Task 1: Dependencies, logo and test harness

**Implementer: haiku. Guard: `tests/conftest.py` and `tests/test_packaging.py` must match the blocks below exactly.**

**Files:**
- Modify: `pyproject.toml`
- Modify: `pytest.ini`
- Create: `tests/conftest.py`
- Create: `salome_agent_gui/web/salome-s.png` (copy)
- Test: `tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PyQt5.QtWebEngineWidgets` and `PyQt5.QtWebChannel` importable in `.venv`; the `web` pytest marker; `salome_agent_gui/web/salome-s.png`.

- [ ] **Step 1: Create the branch**

```bash
git switch spec/modern-chat-ui
git switch -c feat/modern-chat-ui
git branch --show-current
```
Expected: `feat/modern-chat-ui`

- [ ] **Step 2: Write the failing test** — create `tests/test_packaging.py`:

```python
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pyproject():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_webengine_pins_match_the_qt_wheels():
    deps = _pyproject()["project"]["dependencies"]
    for pin in ("PyQt5-Qt5==5.15.19", "PyQtWebEngine==5.15.7", "PyQtWebEngine-Qt5==5.15.19"):
        assert pin in deps


def test_web_assets_are_package_data():
    data = _pyproject()["tool"]["setuptools"]["package-data"]["salome_agent_gui"]
    assert "web/*" in data


def test_webengine_is_importable():
    import PyQt5.QtWebChannel  # noqa: F401
    import PyQt5.QtWebEngineWidgets  # noqa: F401


def test_logo_is_shipped():
    logo = ROOT / "salome_agent_gui" / "web" / "salome-s.png"
    assert logo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 3: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_packaging.py`
Expected: 4 FAILED (pins missing, `KeyError`/assert on package data, `ModuleNotFoundError: No module named 'PyQt5.QtWebEngineWidgets'`, logo missing).

- [ ] **Step 4: Update `pyproject.toml`**

Replace the `dependencies` line with:

```toml
dependencies = ["salome-agent", "PyQt5", "PyQt5-Qt5==5.15.19", "PyQtWebEngine==5.15.7",
                "PyQtWebEngine-Qt5==5.15.19"]
```

Replace the `[tool.setuptools.package-data]` table with:

```toml
[tool.setuptools.package-data]
salome_agent_gui = ["config.example.json", "web/*"]
```

- [ ] **Step 5: Install the pins into the dev venv**

Run: `.venv/bin/pip install "PyQt5-Qt5==5.15.19" "PyQtWebEngine==5.15.7" "PyQtWebEngine-Qt5==5.15.19"`
Expected: ends with `Successfully installed PyQtWebEngine-5.15.7 PyQtWebEngine-Qt5-5.15.19` (PyQt5-Qt5 already satisfied).

- [ ] **Step 6: Copy the logo**

```bash
mkdir -p salome_agent_gui/web
cp docs/superpowers/specs/2026-09-23-modern-chat-ui/salome-s.png salome_agent_gui/web/salome-s.png
```

- [ ] **Step 7: Add the `web` marker** — replace `pytest.ini` with:

```ini
[pytest]
testpaths = tests
qt_api = pyqt5
pythonpath = .
markers =
    web: needs Qt WebEngine and a real display (run with QT_QPA_PLATFORM=xcb)
```

- [ ] **Step 8: Create `tests/conftest.py`**

```python
import os

import pytest
from PyQt5.QtCore import QCoreApplication, Qt

# Qt requires QtWebEngineWidgets to be imported, and context sharing switched
# on, before the QApplication exists; pytest-qt creates it on first use.
try:
    import PyQt5.QtWebEngineWidgets  # noqa: F401
    HAVE_WEBENGINE = True
except ImportError:
    HAVE_WEBENGINE = False
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)


def pytest_collection_modifyitems(config, items):
    if not HAVE_WEBENGINE:
        reason = "PyQtWebEngine is not installed"
    elif os.environ.get("QT_QPA_PLATFORM") != "xcb" or not os.environ.get("DISPLAY"):
        reason = "web tests need QT_QPA_PLATFORM=xcb and a DISPLAY (Qt WebEngine does not run offscreen)"
    else:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if "web" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 9: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all pass (the 68 existing tests plus the 4 new ones: 72 passed).

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml pytest.ini tests/conftest.py tests/test_packaging.py salome_agent_gui/web/salome-s.png
git commit -m "build: add Qt WebEngine pins, the web package data, the logo and a web test marker"
```

---

### Task 2: Module icons

**Implementer: haiku. Guard: `salome_agent_gui/module_icons.py` and `tests/test_module_icons.py` must match the blocks below exactly.**

**Files:**
- Create: `salome_agent_gui/module_icons.py`
- Test: `tests/test_module_icons.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `module_icons.icon_for(module: str, environ: Mapping | None = None) -> str | None` — a `file://` URL of the module's SALOME icon, or `None`.

- [ ] **Step 1: Write the failing test** — create `tests/test_module_icons.py`:

```python
from salome_agent_gui.module_icons import icon_for

PNG = b"\x89PNG\r\n\x1a\n"


def _install(tmp_path, module, icon="ModuleGeom.png", *, with_file=True, xml=None):
    root = tmp_path / module.upper()
    res = root / "share" / "salome" / "resources" / module
    res.mkdir(parents=True)
    (res / "SalomeApp.xml").write_text(
        xml or f'<document><section name="{module.upper()}">'
               f'<parameter name="name" value="Geometry"/>'
               f'<parameter name="icon" value="{icon}"/></section></document>')
    if with_file:
        (res / icon).write_bytes(PNG)
    return root


def test_icon_is_found_through_the_root_dir_and_salomeapp_xml(tmp_path):
    root = _install(tmp_path, "geom")
    url = icon_for("geom", {"GEOM_ROOT_DIR": str(root)})
    assert url == (root / "share/salome/resources/geom/ModuleGeom.png").as_uri()


def test_module_name_is_case_insensitive(tmp_path):
    root = _install(tmp_path, "smesh", "ModuleMesh.png")
    assert icon_for("SMESH", {"SMESH_ROOT_DIR": str(root)}).endswith("/ModuleMesh.png")


def test_missing_root_dir_variable_gives_none():
    assert icon_for("geom", {}) is None


def test_missing_icon_file_gives_none(tmp_path):
    root = _install(tmp_path, "geom", with_file=False)
    assert icon_for("geom", {"GEOM_ROOT_DIR": str(root)}) is None


def test_broken_xml_gives_none(tmp_path):
    root = _install(tmp_path, "geom", xml="<document><section")
    assert icon_for("geom", {"GEOM_ROOT_DIR": str(root)}) is None


def test_xml_without_icon_parameter_gives_none(tmp_path):
    root = _install(tmp_path, "geom", xml="<document><section name='GEOM'/></document>")
    assert icon_for("geom", {"GEOM_ROOT_DIR": str(root)}) is None


def test_module_name_with_path_characters_gives_none(tmp_path):
    assert icon_for("../geom", {"../GEOM_ROOT_DIR": str(tmp_path)}) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_module_icons.py`
Expected: FAIL, `ModuleNotFoundError: No module named 'salome_agent_gui.module_icons'`.

- [ ] **Step 3: Create `salome_agent_gui/module_icons.py`**

```python
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def icon_for(module: str, environ=None) -> str | None:
    """file:// URL of a SALOME module's own icon, read from
    $<MODULE>_ROOT_DIR/share/salome/resources/<module>/SalomeApp.xml, or None."""
    env = os.environ if environ is None else environ
    name = str(module).lower()
    if not name.isalnum():
        return None
    root = env.get(f"{name.upper()}_ROOT_DIR")
    if not root:
        return None
    res = Path(root) / "share" / "salome" / "resources" / name
    try:
        tree = ET.parse(res / "SalomeApp.xml")
    except (OSError, ET.ParseError):
        return None
    for param in tree.iter("parameter"):
        value = param.get("value")
        if param.get("name") == "icon" and value:
            icon = res / value
            return icon.as_uri() if icon.is_file() else None
    return None
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_module_icons.py`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add salome_agent_gui/module_icons.py tests/test_module_icons.py
git commit -m "feat: look up SALOME module icons through the module root dirs"
```

---

### Task 3: Settings in config_store

**Implementer: haiku. Guard: the added functions and tests must match the blocks below exactly.**

**Files:**
- Modify: `salome_agent_gui/config_store.py` (append)
- Test: `tests/test_config_store.py` (append)

**Interfaces:**
- Consumes: existing `config_store._write`, `KEY_FIELDS`, `load`.
- Produces:
  - `config_store.read_settings(path) -> dict` with keys `base_url, model, api_key, on_stage_failure, tool_selection, batch, verbose, theme`.
  - `config_store.save_settings(path, fields: dict, *, run_options: bool = True) -> None`. Run options are `on_stage_failure`, `tool_selection` (in `policy`) and `batch`, `verbose` (in `gui`); `theme` is in `gui`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_config_store.py`:

```python
def test_read_settings_defaults_when_sections_are_missing(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    assert cs.read_settings(user) == {
        "base_url": "", "model": "", "api_key": "", "on_stage_failure": "abort",
        "tool_selection": "hints", "batch": False, "verbose": 0, "theme": "system"}


def test_save_settings_writes_llm_policy_and_gui(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"base_url": "http://h/v1", "model": "m", "api_key": "k",
                            "on_stage_failure": "continue", "tool_selection": "all",
                            "batch": True, "verbose": 2, "theme": "dark"})
    assert cs.read_settings(user) == {
        "base_url": "http://h/v1", "model": "m", "api_key": "k", "on_stage_failure": "continue",
        "tool_selection": "all", "batch": True, "verbose": 2, "theme": "dark"}
    data = json.loads(user.read_text())
    assert data["salome"] == SEED["salome"]
    assert data["gui"] == {"theme": "dark", "batch": True, "verbose": 2}


def test_save_settings_without_run_options_keeps_them(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"on_stage_failure": "continue", "batch": True, "verbose": 1})
    cs.save_settings(user, {"model": "m2", "theme": "light", "on_stage_failure": "abort",
                            "tool_selection": "all", "batch": False, "verbose": 0},
                     run_options=False)
    s = cs.read_settings(user)
    assert s["model"] == "m2" and s["theme"] == "light"
    assert (s["on_stage_failure"], s["tool_selection"], s["batch"], s["verbose"]) == \
        ("continue", "hints", True, 1)


def test_save_settings_ignores_bad_values(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"theme": "purple", "on_stage_failure": "explode",
                            "tool_selection": "some", "verbose": 9})
    s = cs.read_settings(user)
    assert (s["theme"], s["on_stage_failure"], s["tool_selection"], s["verbose"]) == \
        ("system", "abort", "hints", 2)


def test_gui_section_is_accepted_by_the_agent_config_loader(tmp_path):
    user = cs.ensure_user_config(tmp_path / "u.json", [_seed(tmp_path)])
    cs.save_settings(user, {"base_url": "http://h", "model": "m", "theme": "dark"})
    assert cs.load(user)["llm"]["model"] == "m"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_config_store.py`
Expected: 5 FAILED with `AttributeError: module 'salome_agent_gui.config_store' has no attribute 'read_settings'` (or `save_settings`).

- [ ] **Step 3: Append to `salome_agent_gui/config_store.py`**

```python
THEMES = ("system", "light", "dark")
ON_FAILURE = ("abort", "continue")
TOOL_SELECTION = ("hints", "all")


def read_settings(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    llm, policy, gui = data.get("llm", {}), data.get("policy", {}), data.get("gui", {})
    return {
        **{k: llm.get(k, "") or "" for k in KEY_FIELDS},
        "on_stage_failure": policy.get("on_stage_failure") if policy.get("on_stage_failure") in ON_FAILURE else "abort",
        "tool_selection": policy.get("tool_selection") if policy.get("tool_selection") in TOOL_SELECTION else "hints",
        "batch": bool(gui.get("batch", False)),
        "verbose": int(gui.get("verbose", 0) or 0),
        "theme": gui.get("theme") if gui.get("theme") in THEMES else "system",
    }


def save_settings(path: Path, fields: dict, *, run_options: bool = True) -> None:
    """Key fields and theme always; run options (policy + gui batch/verbose)
    only when `run_options` — they are fixed while a conversation is open."""
    data = json.loads(Path(path).read_text())
    data.setdefault("llm", {}).update({k: fields[k] for k in KEY_FIELDS if k in fields})
    gui = data.setdefault("gui", {})
    if fields.get("theme") in THEMES:
        gui["theme"] = fields["theme"]
    if run_options:
        policy = data.setdefault("policy", {})
        if fields.get("on_stage_failure") in ON_FAILURE:
            policy["on_stage_failure"] = fields["on_stage_failure"]
        if fields.get("tool_selection") in TOOL_SELECTION:
            policy["tool_selection"] = fields["tool_selection"]
        if "batch" in fields:
            gui["batch"] = bool(fields["batch"])
        if "verbose" in fields:
            gui["verbose"] = max(0, min(2, int(fields["verbose"])))
    _write(Path(path), data)
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_config_store.py`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add salome_agent_gui/config_store.py tests/test_config_store.py
git commit -m "feat: read and save the chat settings, with run options lockable"
```

---

### Task 4: Timeline view model

**Implementer: sonnet.**

**Files:**
- Modify: `salome_agent_gui/timeline.py`
- Test: `tests/test_timeline.py` (append; existing tests keep passing — the markdown renderers stay until Task 7)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `timeline.short_name(name: str) -> str` — strips a leading `sa_<12 hex>_`.
  - `timeline.USAGE_KEYS = ("calls", "prompt_tokens", "completion_tokens", "llm_seconds")`.
  - `StageRow` gains `started_at: float | None`, `elapsed_s: float | None`.
  - `RunView(clock=time.time, usage_base=None)` gains fields `gate_id: int | None`, `edit_ops: list[dict]`, and methods `status() -> str`, `turn_usage() -> dict | None`, `to_view_model(turn_id: int, icon_for=lambda module: None) -> dict`.
  - `RunView.gate` stays the raw worker gate payload (`{"plan": [...]}` or `{"last_error": {...}}`); the Bridge sets `gate` and `gate_id` together.
  - View model: exactly the spec's shape — `{"id", "stages": [{"index", "module", "icon", "intent", "status", "attempts", "started_at", "elapsed_s", "error"}], "edits", "gate", "status", "message", "objects", "files": {"result_py", "report_md"}, "usage"}`. `gate` is `None`, `{"id", "kind": "plan"}` or `{"id", "kind": "stage_failed", "stage", "message", "line"}`. `edits` items: `{"op": "edit", "node", "param", "old", "new"}` (strings), `{"op": "delete", "nodes": [...]}`, `{"op": "add", "node", "new"}`, `{"op": "replay", "nodes": [...]}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_timeline.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_timeline.py`
Expected: the new tests FAIL (`ImportError: cannot import name 'short_name'`), which fails the whole module at import. That is expected.

- [ ] **Step 3: Implement in `salome_agent_gui/timeline.py`**

Add at the top (after the existing imports):

```python
import re
import time
from typing import Callable

_RUN_PREFIX = re.compile(r"^sa_[0-9a-f]{12}_")
USAGE_KEYS = ("calls", "prompt_tokens", "completion_tokens", "llm_seconds")


def short_name(name) -> str:
    return _RUN_PREFIX.sub("", str(name))
```

Add two fields at the end of `StageRow`:

```python
    started_at: float | None = None
    elapsed_s: float | None = None
```

Add these fields at the end of `RunView` (after `turn_message`):

```python
    gate_id: int | None = None
    edit_ops: list[dict] = field(default_factory=list)
    usage_base: dict | None = None
    clock: Callable[[], float] = field(default=time.time, repr=False)
```

In `RunView.apply`, change these branches (everything else stays):

```python
        elif kind == "stage_start":
            r = self._row(d["index"], d.get("module", "?"), d.get("intent", ""))
            r.status = "running"
            r.started_at = self.clock()
        ...
        elif kind == "stage_done":
            r = self._row(d["index"])
            r.status, r.error = "ok", None
            if r.started_at is not None:
                r.elapsed_s = round(self.clock() - r.started_at, 1)
            self.objects.extend(d.get("names") or [])
        ...
        elif kind == "graph_edit":
            self.edits.append(_edit_line(d))
            self.edit_ops.append(_edit_op(d))
        elif kind == "replay":
            nodes = [str(n) for n in d.get("nodes") or []]
            self.edits.append(f"rebuilding {len(nodes)} object(s): {', '.join(nodes)}")
            self.edit_ops.append({"op": "replay", "nodes": nodes})
```

Add these methods to `RunView`:

```python
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
```

Add this module-level function next to `_edit_line`:

```python
def _edit_op(d: dict) -> dict:
    if d.get("op") == "edit":
        return {"op": "edit", "node": str(d.get("node")), "param": str(d.get("param")),
                "old": str(d.get("old")), "new": str(d.get("new"))}
    if d.get("op") == "delete":
        return {"op": "delete", "nodes": [str(n) for n in d.get("old") or []]}
    return {"op": "add", "node": str(d.get("node")), "new": str(d.get("new"))}
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_timeline.py`
Expected: 26 passed (16 existing timeline tests + 10 new).

- [ ] **Step 5: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add salome_agent_gui/timeline.py tests/test_timeline.py
git commit -m "feat: timeline builds a JSON view model per turn with stage times, gate ids and per-turn usage"
```

---

### Task 5: Bridge

**Implementer: sonnet.**

**Files:**
- Create: `salome_agent_gui/bridge.py`
- Create: `tests/fakes.py`
- Test: `tests/test_bridge.py`

**Interfaces:**
- Consumes: `RunView(clock=, usage_base=)`, `.apply`, `.gate`, `.gate_id`, `.to_view_model(turn_id, icon_for)` (Task 4); `config_store.read_settings`, `save_settings`, `load` (Task 3); `module_icons.icon_for` (Task 2); `ConversationWorker(config, *, batch, verbose, open_fn, parent)` with signals `event(dict)`, `gate(dict)`, `turn_done(dict)`, `finished`, and methods `submit`, `undo`, `redo`, `rebuild`, `stop`, `close`, `answer_gate` (unchanged, `salome_agent_gui/conversation_worker.py`).
- Produces (used by Tasks 6 and 7):
  - `class Bridge(QObject)` with signals `push(str, str)` (name, JSON) and `close_ready()`.
  - `Bridge(config_path, *, open_fn=None, probe_fn=None, edit_plan=None, edit_config=None, open_file=None, icon_for=None, system_dark=None, clock=time.time, dialog_parent=None, parent=None)`.
  - Slots (callable from the page): `ready()`, `send(str)`, `gate(int, str, str)`, `command(str)`, `stop()`, `openFile(str)`, `saveSettings(str)`, `editConfigJson()`, `reconnect()`.
  - Python-side methods: `start()` (first probe + polling), `probe()`, `page_lost()`, `request_close() -> bool`.
  - Public attributes read by tests and the window: `worker`, `busy`, `stopping`, `connected`, `degraded`, `close_pending`, `page_ready`.
  - Payloads: `setSettings` = `read_settings(...)` + `{"locked": bool, "config_path": str}`; `setTheme` = `{"theme": "light"|"dark"}`; `setStatus` = `{"state": "connected"|"offline"|"error", "label": str, "detail": str}`; `setBusy` = `{"busy", "stopping", "open", "degraded", "can_send"}`; `addUser`/`addNote` = `{"text"}`; `renderTurn` = a view model; `replay` = `{"items": [{"type": "user", "text"} | {"type": "note", "text"} | {"type": "turn", "vm"}]}`.

- [ ] **Step 1: Create `tests/fakes.py`** (shared test doubles):

```python
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

    def turn(self, text, *, on_event, on_gate, cancel):
        rec = self.rec
        rec.setdefault("turns", []).append(text)
        n, self.n_turns = self.n_turns, self.n_turns + 1

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
            rec["decision"] = on_gate(rec.get("first_gate", {"plan": PLAN}))
            if rec["decision"]["action"] not in ("approve", "edit", "hint", "skip"):
                ev("aborted")
                ev("turn_done", turn=n, status="failed", message="turn cancelled")
                return TurnResult("failed", "turn cancelled", {})
            ev("stage_start", index=0, module="geom", intent="box")
            ev("stage_done", index=0, names=["sa_0123456789ab_box_1"])
        else:
            ev("graph_edit", op="edit", node="n1", param="dz", old=40, new=60)
            ev("replay", nodes=["n1"])
        usage = {"calls": 3 * (n + 1), "prompt_tokens": 1000 * (n + 1),
                 "completion_tokens": 100 * (n + 1), "llm_seconds": 1.5 * (n + 1)}
        ev("report", result_py="/w/result.py", report_md="/w/report.md", text="", usage=usage)
        ev("turn_done", turn=n, status="ok", message=f"did {text}")
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
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_bridge.py`:

```python
import itertools
import json
import threading
import time

import pytest
from salome_agent.conversation import TurnResult

from salome_agent_gui.bridge import Bridge
from tests.fakes import CFG, opener, write_cfg

GUI = {"mode": "gui", "port": 4242}


class Pushes:
    def __init__(self, bridge):
        self.items = []
        bridge.push.connect(lambda name, payload: self.items.append((name, json.loads(payload))))

    def all(self, name):
        return [p for n, p in self.items if n == name]

    def last(self, name):
        found = self.all(name)
        return found[-1] if found else None

    def names(self):
        return [n for n, _ in self.items]


@pytest.fixture
def cfg_path(tmp_path):
    return write_cfg(tmp_path)


@pytest.fixture
def bridges():
    made = []
    yield made
    for b in made:
        if b.worker is not None:
            b.worker.close()
            b.worker.wait(3000)


def make(bridges, cfg_path, rec, *, ready=True, probe=lambda: GUI, **kw):
    b = Bridge(cfg_path, open_fn=opener(rec), probe_fn=probe, **kw)
    bridges.append(b)
    p = Pushes(b)
    if ready:
        b.ready()
    return b, p


def vm(p):
    return p.last("renderTurn")


def wait_gate(qtbot, p):
    qtbot.waitUntil(lambda: (vm(p) or {}).get("gate") is not None, timeout=3000)
    return vm(p)["gate"]


def first_turn(qtbot, b, p, text="make a box"):
    b.probe()
    b.send(text)
    b.gate(wait_gate(qtbot, p)["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)


def say(qtbot, b, text):
    b.send(text)
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)


def test_pushes_wait_for_ready_then_the_full_state_goes_out(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {}, ready=False)
    b.probe()
    assert p.items == []
    b.ready()
    assert p.names()[:5] == ["setSettings", "setTheme", "setStatus", "setBusy", "replay"]
    s = p.last("setSettings")
    assert (s["base_url"], s["model"], s["locked"]) == ("http://h/v1", "m", False)
    assert s["config_path"] == str(cfg_path)
    assert p.last("setTheme") == {"theme": "light"}
    st = p.last("setStatus")
    assert st["state"] == "connected" and "GUI :4242" in st["label"] and "m" in st["label"]
    assert p.last("replay") == {"items": []}


def test_no_server_keeps_send_disabled_and_explains(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {}, probe=lambda: None)
    b.probe()
    st = p.last("setStatus")
    assert st["state"] == "offline" and "Plugins" in st["detail"]
    assert p.last("setBusy")["can_send"] is False
    b.send("x")
    assert b.worker is None and p.last("addUser") is None


def test_first_message_opens_a_conversation_and_stays_open(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("  make a box  ")
    assert p.last("addUser") == {"text": "make a box"}
    gate = wait_gate(qtbot, p)
    assert gate["kind"] == "plan" and vm(p)["stages"][0]["module"] == "geom"
    busy = p.last("setBusy")
    assert busy["busy"] and busy["open"] and not busy["can_send"]
    assert p.last("setSettings")["locked"] is True
    b.gate(gate["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    last = vm(p)
    assert last["gate"] is None and last["status"] == "ok" and last["message"] == "did make a box"
    assert last["objects"] == ["box_1"]
    assert last["files"] == {"result_py": "/w/result.py", "report_md": "/w/report.md"}
    assert b.worker is not None
    assert p.last("setBusy") == {"busy": False, "stopping": False, "open": True,
                                 "degraded": False, "can_send": True}


def test_saved_run_options_reach_the_conversation(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.saveSettings(json.dumps({"on_stage_failure": "continue", "tool_selection": "all",
                               "batch": True, "verbose": 1}))
    first_turn(qtbot, b, p)
    assert rec["config"]["policy"]["on_stage_failure"] == "continue"
    assert rec["config"]["policy"]["tool_selection"] == "all"
    assert (rec["batch"], rec["verbose"]) == (True, 1)


def test_follow_up_amends_the_same_conversation_with_per_turn_usage(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    assert vm(p)["usage"] == {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                              "llm_seconds": 1.5}
    say(qtbot, b, "make it taller")
    assert rec["opened"] == 1 and rec["turns"] == ["make a box", "make it taller"]
    last = vm(p)
    assert last["id"] == 1
    assert last["edits"] == [{"op": "edit", "node": "n1", "param": "dz", "old": "40", "new": "60"},
                             {"op": "replay", "nodes": ["n1"]}]
    assert last["usage"] == {"calls": 3, "prompt_tokens": 1000, "completion_tokens": 100,
                             "llm_seconds": 1.5}


def test_edit_uses_the_injected_editor_and_cancel_keeps_the_gate(qtbot, bridges, cfg_path):
    rec = {}
    answers = [None, [{"module": "geom", "intent": "cyl", "params": {}, "inputs": []}]]
    b, p = make(bridges, cfg_path, rec, edit_plan=lambda parent, plan: answers.pop(0))
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    b.gate(gate["id"], "edit", "")
    qtbot.wait(100)
    assert "decision" not in rec and vm(p)["gate"] == gate
    b.gate(gate["id"], "edit", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"]["action"] == "edit" and rec["decision"]["plan"][0]["intent"] == "cyl"


def test_hint_sends_the_typed_text_and_a_blank_hint_is_ignored(qtbot, bridges, cfg_path):
    rec = {"first_gate": {"last_error": {"message": "fillet failed\nsecond line",
                                         "offending_line": 7}}}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    assert gate["kind"] == "stage_failed" and gate["message"] == "fillet failed\nsecond line"
    assert gate["line"] == 7
    b.gate(gate["id"], "hint", "   ")
    qtbot.wait(100)
    assert "decision" not in rec
    b.gate(gate["id"], "hint", "  try r=2 ")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "hint", "hint": "try r=2"}


def test_stale_gate_id_is_ignored(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x")
    gate = wait_gate(qtbot, p)
    b.gate(gate["id"] + 1, "abort", "")
    qtbot.wait(100)
    assert "decision" not in rec
    b.gate(gate["id"], "approve", "")
    b.gate(gate["id"], "abort", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "approve"}
    assert vm(p)["status"] == "ok"


def test_stop_aborts_a_pending_gate_and_keeps_the_conversation(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    b.probe()
    b.send("x")
    wait_gate(qtbot, p)
    b.stop()
    assert p.last("setBusy")["stopping"] is True
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["decision"] == {"action": "abort"}
    last = vm(p)
    assert (last["status"], last["message"]) == ("failed", "turn cancelled")
    assert b.worker is not None and p.last("setBusy")["can_send"] is True
    assert p.last("setBusy")["stopping"] is False


def test_undo_and_redo_add_notes(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    b.command("undo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    b.command("redo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["undo"] is True
    assert [n["text"] for n in p.all("addNote")] == ["undo: undone back to turn 0",
                                                     "redo: redone up to turn 1"]


def test_failed_undo_note_says_it_failed(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    rec["conv"].undo = lambda: TurnResult("failed", "nothing to undo", {})
    b.command("undo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert p.last("addNote") == {"text": "undo failed: nothing to undo"}


def test_rebuild_only_runs_when_degraded(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    b.command("rebuild")
    assert not b.busy and "rebuilt" not in rec
    rec["conv"].next_status = "degraded"
    say(qtbot, b, "break it")
    assert p.last("setBusy")["degraded"] is True and vm(p)["status"] == "degraded"
    b.command("rebuild")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["rebuilt"] == 1 and p.last("setBusy")["degraded"] is False
    assert p.last("addNote") == {"text": "rebuild: rebuilt 1 node(s)"}


def test_new_conversation_closes_the_client_and_restarts_usage(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    say(qtbot, b, "taller")
    b.command("new")
    qtbot.waitUntil(lambda: b.worker is None, timeout=3000)
    assert rec["closed"] == 1
    assert "New conversation" in p.last("addNote")["text"]
    assert p.last("setSettings")["locked"] is False
    first_turn(qtbot, b, p, "make a cylinder")
    assert rec["opened"] == 2 and vm(p)["usage"]["calls"] == 3


def test_ended_conversation_frees_the_worker_and_next_send_opens_a_new_one(qtbot, bridges,
                                                                          cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    rec["conv"].next_status = "ended"
    b.send("anything")
    qtbot.waitUntil(lambda: b.worker is None, timeout=3000)
    assert vm(p)["status"] == "ended"
    assert "next message starts a new conversation" in p.last("addNote")["text"]
    assert p.last("setBusy")["can_send"] is True
    first_turn(qtbot, b, p, "again")
    assert rec["opened"] == 2


def test_request_close_when_idle_returns_true(bridges, cfg_path):
    b, _ = make(bridges, cfg_path, {})
    assert b.request_close() is True


def test_request_close_during_a_turn_does_not_block(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    rec["conv"].release = threading.Event()
    b.send("slow")
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    closed = []
    b.close_ready.connect(lambda: closed.append(1))
    t0 = time.monotonic()
    assert b.request_close() is False
    assert time.monotonic() - t0 < 0.5
    assert b.close_pending and p.last("setBusy")["stopping"] is True
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: closed == [1], timeout=5000)
    assert b.worker is None and rec["closed"] == 1


def test_done_while_close_pending_skips_the_probe(qtbot, bridges, cfg_path):
    rec, calls = {}, []

    def probe():
        calls.append(1)
        return GUI

    b, p = make(bridges, cfg_path, rec, probe=probe)
    first_turn(qtbot, b, p)
    rec["conv"].release = threading.Event()
    b.send("slow")
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    b.request_close()
    n = len(calls)
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: b.worker is None, timeout=5000)
    assert len(calls) == n


def test_server_error_disables_send_until_reconnect(qtbot, bridges, cfg_path):
    from salome_agent.server_conn import ServerUnavailable

    def failing_open(config, run_id, *, batch, verbose):
        raise ServerUnavailable("poisoned")

    b = Bridge(cfg_path, open_fn=failing_open, probe_fn=lambda: GUI)
    bridges.append(b)
    p = Pushes(b)
    b.ready()
    b.probe()
    b.send("x")
    qtbot.waitUntil(lambda: b.worker is None and not b.busy, timeout=3000)
    st = p.last("setStatus")
    assert st["state"] == "error" and "poisoned" in st["detail"]
    assert p.last("setBusy")["can_send"] is False
    b.reconnect()
    assert p.last("setStatus")["state"] == "connected"
    assert p.last("setBusy")["can_send"] is True


def test_run_options_are_refused_while_a_conversation_is_open(qtbot, bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    first_turn(qtbot, b, p)
    b.saveSettings(json.dumps({"model": "m2", "theme": "dark", "on_stage_failure": "continue",
                               "batch": True}))
    data = json.loads(cfg_path.read_text())
    assert data["llm"]["model"] == "m2" and data["gui"]["theme"] == "dark"
    assert data["policy"]["on_stage_failure"] == "abort" and "batch" not in data["gui"]
    assert p.last("setTheme") == {"theme": "dark"}
    assert "m2" in p.last("setStatus")["label"]


def test_bad_settings_json_is_ignored(bridges, cfg_path):
    b, p = make(bridges, cfg_path, {})
    before = cfg_path.read_text()
    b.saveSettings("{not json")
    b.saveSettings("[1, 2]")
    assert cfg_path.read_text() == before


def test_ready_again_replays_the_whole_transcript(qtbot, bridges, cfg_path):
    rec = {}
    b, p = make(bridges, cfg_path, rec)
    first_turn(qtbot, b, p)
    b.command("undo")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    b.page_lost()
    n = len(p.items)
    say(qtbot, b, "taller")
    assert len(p.items) == n
    b.ready()
    items = p.last("replay")["items"]
    assert [i["type"] for i in items] == ["user", "turn", "note", "user", "turn"]
    assert items[0]["text"] == "make a box" and items[1]["vm"]["objects"] == ["box_1"]
    assert items[4]["vm"]["edits"][0]["op"] == "edit"


def test_open_file_only_opens_files_a_run_reported(qtbot, bridges, cfg_path):
    opened = []
    b, p = make(bridges, cfg_path, {}, open_file=opened.append)
    b.openFile("/w/result.py")
    assert opened == []
    first_turn(qtbot, b, p)
    b.openFile("/etc/passwd")
    b.openFile("/w/result.py")
    assert opened == ["/w/result.py"]


def test_edit_config_json_pushes_the_new_settings(bridges, cfg_path):
    def editor(parent, path):
        data = json.loads(path.read_text())
        data["llm"]["model"] = "edited"
        path.write_text(json.dumps(data))
        return True

    b, p = make(bridges, cfg_path, {}, edit_config=editor)
    b.editConfigJson()
    assert p.last("setSettings")["model"] == "edited"


def test_stage_icons_and_times_come_from_the_injected_lookups(qtbot, bridges, cfg_path):
    ticks = itertools.chain([100.0, 112.5], itertools.repeat(200.0))
    b, p = make(bridges, cfg_path, {}, icon_for=lambda m: f"file:///icons/{m}.png",
                clock=lambda: next(ticks))
    first_turn(qtbot, b, p)
    stage = vm(p)["stages"][0]
    assert stage["icon"] == "file:///icons/geom.png"
    assert (stage["started_at"], stage["elapsed_s"]) == (100.0, 12.5)


def test_system_theme_follows_the_palette_and_an_explicit_theme_wins(tmp_path, bridges):
    path = write_cfg(tmp_path, {**CFG, "gui": {"theme": "system"}})
    b, p = make(bridges, path, {}, system_dark=lambda: True)
    assert p.last("setTheme") == {"theme": "dark"}
    b.saveSettings(json.dumps({"theme": "light"}))
    assert p.last("setTheme") == {"theme": "light"}
```

- [ ] **Step 3: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_bridge.py`
Expected: FAIL at import, `ModuleNotFoundError: No module named 'salome_agent_gui.bridge'`.

- [ ] **Step 4: Create `salome_agent_gui/bridge.py`**

```python
import json
import time
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal, pyqtSlot

from salome_agent_gui import config_store, module_icons
from salome_agent_gui.conversation_worker import ConversationWorker, default_open
from salome_agent_gui.timeline import RunView

NO_SERVER = ("No agent server. Start it from Tools > Plugins > SALOME Agent in the SALOME "
             "window, then press Reconnect in the settings.")


class Bridge(QObject):
    """Owns everything the chat page shows. The page calls the slots and draws
    what `push(name, json)` sends; it never interprets engine events itself."""

    push = pyqtSignal(str, str)
    close_ready = pyqtSignal()

    def __init__(self, config_path, *, open_fn=None, probe_fn=None, edit_plan=None,
                 edit_config=None, open_file=None, icon_for=None, system_dark=None,
                 clock=time.time, dialog_parent=None, parent=None):
        super().__init__(parent)
        if probe_fn is None:
            from agent_server import handshake
            probe_fn = handshake.live_owner
        self.config_path = Path(config_path)
        self._open_fn = open_fn or default_open
        self._probe_fn = probe_fn
        self._edit_plan = edit_plan or (lambda parent, plan: None)
        self._edit_config = edit_config or (lambda parent, path: False)
        self._open_file = open_file or (lambda path: None)
        self._icon_for = icon_for or module_icons.icon_for
        self._system_dark = system_dark or (lambda: False)
        self._clock = clock
        self._dialog_parent = dialog_parent

        self.worker: ConversationWorker | None = None
        self.busy = False
        self.stopping = False
        self.degraded = False
        self.connected = False
        self.server_error = False
        self.close_pending = False
        self.page_ready = False
        self._status = {"state": "offline", "label": "Not connected", "detail": NO_SERVER}
        self._items: list[tuple[str, object]] = []   # ("user"|"note", text) or ("turn", id)
        self._turns: dict[int, RunView] = {}
        self._current: int | None = None
        self._next_turn = 0
        self._next_gate = 0
        self._usage_base: dict | None = None
        self._icons: dict[str, str | None] = {}
        self._files: set[str] = set()
        self._polls = 0
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._poll_tick)

    # ---- output ---------------------------------------------------------
    def _emit(self, name: str, payload) -> None:
        if self.page_ready:
            self.push.emit(name, json.dumps(payload))

    def _settings(self) -> dict:
        s = config_store.read_settings(self.config_path)
        return {**s, "locked": self.worker is not None, "config_path": str(self.config_path)}

    def _theme(self) -> dict:
        theme = config_store.read_settings(self.config_path)["theme"]
        dark = theme == "dark" or (theme == "system" and bool(self._system_dark()))
        return {"theme": "dark" if dark else "light"}

    def _busy_state(self) -> dict:
        return {"busy": self.busy, "stopping": self.stopping, "open": self.worker is not None,
                "degraded": self.degraded, "can_send": self.connected and not self.busy}

    def _icon(self, module: str):
        if module not in self._icons:
            self._icons[module] = self._icon_for(module)
        return self._icons[module]

    def _vm(self, turn_id: int) -> dict:
        return self._turns[turn_id].to_view_model(turn_id, self._icon)

    def _sync(self) -> None:
        self._emit("setBusy", self._busy_state())

    def _render(self) -> None:
        if self._current is not None:
            self._emit("renderTurn", self._vm(self._current))

    def _note(self, text: str) -> None:
        self._items.append(("note", text))
        self._emit("addNote", {"text": text})

    # ---- page lifecycle -------------------------------------------------
    @pyqtSlot()
    def ready(self) -> None:
        self.page_ready = True
        self._emit("setSettings", self._settings())
        self._emit("setTheme", self._theme())
        self._emit("setStatus", self._status)
        self._emit("setBusy", self._busy_state())
        items = []
        for kind, value in self._items:
            if kind == "turn":
                items.append({"type": "turn", "vm": self._vm(value)})
            else:
                items.append({"type": kind, "text": value})
        self._emit("replay", {"items": items})

    def page_lost(self) -> None:
        self.page_ready = False

    def start(self) -> None:
        self.probe()
        self._poll.start()

    # ---- server ---------------------------------------------------------
    def probe(self) -> None:
        self.server_error = False
        hs = self._probe_fn()
        self.connected = hs is not None
        if hs:
            model = config_store.read_settings(self.config_path)["model"] or "?"
            label = f"{str(hs.get('mode', '?')).upper()} :{hs.get('port', '?')} · {model}"
            self._status = {"state": "connected", "label": label, "detail": ""}
        else:
            self._status = {"state": "offline", "label": "Not connected", "detail": NO_SERVER}
        self._emit("setStatus", self._status)
        self._sync()

    def _poll_tick(self) -> None:
        self._polls += 1
        if self.connected or self._polls >= 10 or self.server_error:
            self._poll.stop()
            return
        self.probe()

    @pyqtSlot()
    def reconnect(self) -> None:
        self._polls = 0
        self.probe()

    # ---- settings -------------------------------------------------------
    @pyqtSlot(str)
    def saveSettings(self, text: str) -> None:
        try:
            fields = json.loads(text)
        except ValueError:
            return
        if not isinstance(fields, dict):
            return
        config_store.save_settings(self.config_path, fields, run_options=self.worker is None)
        self._emit("setSettings", self._settings())
        self._emit("setTheme", self._theme())
        if not self.server_error:
            self.probe()

    @pyqtSlot()
    def editConfigJson(self) -> None:
        if self._edit_config(self._dialog_parent, self.config_path):
            self._emit("setSettings", self._settings())
            self._emit("setTheme", self._theme())

    # ---- conversation ---------------------------------------------------
    def _start_conversation(self) -> bool:
        s = config_store.read_settings(self.config_path)
        try:
            config = config_store.load(self.config_path)
        except Exception as e:  # noqa: BLE001
            self._status = {"state": "error", "label": "Config error", "detail": str(e)}
            self._emit("setStatus", self._status)
            return False
        config.setdefault("policy", {})
        config["policy"]["on_stage_failure"] = s["on_stage_failure"]
        config["policy"]["tool_selection"] = s["tool_selection"]
        worker = ConversationWorker(config, batch=s["batch"], verbose=s["verbose"],
                                    open_fn=self._open_fn, parent=self)
        worker.event.connect(self._on_event)
        worker.gate.connect(self._on_gate)
        worker.turn_done.connect(self._on_turn_done)
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self.worker = worker
        self.degraded = False
        self._usage_base = None
        worker.start()
        self._emit("setSettings", self._settings())
        return True

    @pyqtSlot(str)
    def send(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self.busy or not self.connected:
            return
        if self.worker is None and not self._start_conversation():
            return
        self._items.append(("user", text))
        self._emit("addUser", {"text": text})
        turn_id = self._next_turn
        self._next_turn += 1
        self._turns[turn_id] = RunView(clock=self._clock, usage_base=self._usage_base)
        self._items.append(("turn", turn_id))
        self._current = turn_id
        self._render()
        self.busy = True
        self.stopping = False
        self.worker.submit(text)
        self._sync()

    def _on_event(self, ev: dict) -> None:
        view = self._turns.get(self._current)
        if view is None:
            return
        view.apply(ev)
        for path in (view.result_py, view.report_md):
            if path:
                self._files.add(path)
        self._render()
        if ev.get("kind") == "fatal":
            message = (ev.get("data") or {}).get("message", "")
            if message.startswith("ServerUnavailable"):
                self.connected = False
                self.server_error = True
                self._status = {"state": "error", "label": "Server error", "detail": message}
                self._emit("setStatus", self._status)
                self._sync()

    def _on_gate(self, payload: dict) -> None:
        view = self._turns.get(self._current)
        if view is None:
            return
        self._next_gate += 1
        view.gate, view.gate_id = payload, self._next_gate
        self._render()

    @pyqtSlot(int, str, str)
    def gate(self, gate_id: int, action: str, text: str) -> None:
        view = self._turns.get(self._current)
        if self.worker is None or view is None or view.gate is None or view.gate_id != gate_id:
            return
        if action == "edit":
            plan = self._edit_plan(self._dialog_parent, view.gate.get("plan") or [])
            if plan is None:
                return
            decision = {"action": "edit", "plan": plan}
        elif action == "hint":
            hint = (text or "").strip()
            if not hint:
                return
            decision = {"action": "hint", "hint": hint}
        elif action in ("approve", "skip", "abort"):
            decision = {"action": action}
        else:
            return
        view.gate, view.gate_id = None, None
        self._render()
        self.worker.answer_gate(decision)

    @pyqtSlot(str)
    def command(self, name: str) -> None:
        if name == "new":
            self._new_conversation()
            return
        if name not in ("undo", "redo", "rebuild") or self.worker is None or self.busy:
            return
        if name == "rebuild" and not self.degraded:
            return
        self.busy = True
        getattr(self.worker, name)()
        self._sync()

    def _new_conversation(self) -> None:
        if self.worker is None or self.busy:
            return
        self.busy = True
        self.worker.close()
        self._note("New conversation: the next message starts a fresh model.")
        self._sync()

    @pyqtSlot()
    def stop(self) -> None:
        if self.worker is not None and self.busy:
            self.stopping = True
            self.worker.stop()
            self._sync()

    def _on_turn_done(self, payload: dict) -> None:
        self.busy = False
        self.stopping = False
        self.degraded = bool(payload.get("degraded"))
        command = payload.get("command")
        if command != "turn":
            failed = " failed" if payload.get("status") == "failed" else ""
            self._note(f"{command}{failed}: {payload.get('message', '')}")
        else:
            view = self._turns.get(self._current)
            if view is not None:
                if view.turn_status is None:
                    view.turn_status = payload.get("status")
                    view.turn_message = payload.get("message")
                view.gate, view.gate_id = None, None
                view.finished = True
                if view.usage:
                    self._usage_base = dict(view.usage)
                self._render()
        if payload.get("ended"):
            self.busy = True
            self._note("The conversation has ended; the next message starts a new conversation.")
        self._sync()
        if not self.close_pending and not self.server_error:
            self.probe()

    def _on_worker_finished(self, worker) -> None:
        if worker is not self.worker:
            return
        worker.wait()
        self.worker = None
        self.busy = False
        self.stopping = False
        self.degraded = False
        self._emit("setSettings", self._settings())
        self._sync()
        if self.close_pending:
            self.close_ready.emit()

    # ---- files and closing ----------------------------------------------
    @pyqtSlot(str)
    def openFile(self, path: str) -> None:
        if path in self._files:
            self._open_file(path)

    def request_close(self) -> bool:
        """True: nothing is running, close now. False: the worker was asked to
        stop; `close_ready` fires once it has."""
        if self.worker is None:
            return True
        if not self.close_pending:
            self.close_pending = True
            self.stopping = True
            self.worker.close()
            self._sync()
        return False
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_bridge.py`
Expected: 25 passed.

- [ ] **Step 6: Run the whole suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all pass (the old `MainWindow` and its tests are untouched in this task).

- [ ] **Step 7: Commit**

```bash
git add salome_agent_gui/bridge.py tests/fakes.py tests/test_bridge.py
git commit -m "feat: Bridge owns the chat state and pushes it to the page as JSON"
```

---

### Task 6: Web page and loader

**Implementer: sonnet.** Visual reference: the spec's mockup and screenshots. The CSS below is the mockup's, with the mockup-only parts removed.

**Files:**
- Create: `salome_agent_gui/web/index.html`, `salome_agent_gui/web/app.css`, `salome_agent_gui/web/app.js`
- Create: `salome_agent_gui/web_view.py`
- Create: `tools/__init__.py` (empty), `tools/page_fixtures.py`
- Test: `tests/test_page.py` (marker `web`), `tests/test_web_view.py` (runs offscreen)

**Interfaces:**
- Consumes: the Bridge protocol (Task 5 "Produces"): slots `ready, send, gate, command, stop, openFile, saveSettings, editConfigJson, reconnect`; signal `push(name, json)`; payload shapes; view model shape (Task 4).
- Produces:
  - `web_view.create(parent, bridge) -> QWidget` — a `QWebEngineView` showing `web/index.html` with `bridge` registered as `"bridge"` on a `QWebChannel`, or a fallback `QLabel` when WebEngine cannot be imported. On a renderer crash it calls `bridge.page_lost()` and reloads.
  - `web_view.WEB_DIR`, `web_view.WEBENGINE_HELP`.
  - `tools.page_fixtures.FakeBridge` (same slots; records `calls`, counts `ready_calls`; `emit(name, payload)`), fixture view models and `STATES` (used by Task 8).

- [ ] **Step 1: Create `tools/__init__.py`** (empty file) **and `tools/page_fixtures.py`**:

```python
"""Fixture view models and a stand-in bridge for the chat page: used by the
page tests and by tools/render_states.py."""
import json
import time

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot


class FakeBridge(QObject):
    push = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.calls = []
        self.ready_calls = 0
        self.lost = 0

    def emit(self, name, payload):
        self.push.emit(name, json.dumps(payload))

    def page_lost(self):
        self.lost += 1

    @pyqtSlot()
    def ready(self):
        self.ready_calls += 1

    @pyqtSlot(str)
    def send(self, text):
        self.calls.append(("send", text))

    @pyqtSlot(int, str, str)
    def gate(self, gate_id, action, text):
        self.calls.append(("gate", gate_id, action, text))

    @pyqtSlot(str)
    def command(self, name):
        self.calls.append(("command", name))

    @pyqtSlot()
    def stop(self):
        self.calls.append(("stop",))

    @pyqtSlot(str)
    def openFile(self, path):
        self.calls.append(("openFile", path))

    @pyqtSlot(str)
    def saveSettings(self, text):
        self.calls.append(("saveSettings", json.loads(text)))

    @pyqtSlot()
    def editConfigJson(self):
        self.calls.append(("editConfigJson",))

    @pyqtSlot()
    def reconnect(self):
        self.calls.append(("reconnect",))


def _stage(index, module, intent, **kw):
    s = {"index": index, "module": module, "icon": None, "intent": intent, "status": "pending",
         "attempts": 0, "started_at": None, "elapsed_s": None, "error": None}
    s.update(kw)
    return s


def _vm(turn_id, **kw):
    vm = {"id": turn_id, "stages": [], "edits": [], "gate": None, "status": "running",
          "message": "", "objects": [], "files": {"result_py": None, "report_md": None},
          "usage": None}
    vm.update(kw)
    return vm


BODY = "Car body: hull box and cabin box fused into one solid, coloured red"
WHEELS = "Four torus wheels under the hull, kept separate, coloured black"
SPOILER = "Spoiler: a thin box on two posts at the rear of the hull, red like the body"
MESH = "Tetrahedral mesh of the body, spoiler and wheels (max size 4 mm)"
USER_1 = "construct a small car with 4 torus as its wheels. make the car red and the wheels black"
USER_2 = "make the wheels bigger, and a bit wider apart"
USER_3 = "add a spoiler on the back and mesh everything"

SETTINGS = {"base_url": "http://llm.example/v1", "model": "auto", "api_key": "sk-test",
            "on_stage_failure": "abort", "tool_selection": "hints", "batch": False,
            "verbose": 0, "theme": "system", "locked": False,
            "config_path": "~/.config/salome/salome-agent.json"}
STATUS_OK = {"state": "connected", "label": "GUI :46019 · auto", "detail": ""}
STATUS_OFF = {"state": "offline", "label": "Not connected",
              "detail": "No agent server. Start it from Tools > Plugins > SALOME Agent in the "
                        "SALOME window, then press Reconnect in the settings."}
IDLE_NEW = {"busy": False, "stopping": False, "open": False, "degraded": False, "can_send": True}
IDLE_OPEN = {"busy": False, "stopping": False, "open": True, "degraded": False, "can_send": True}
BUSY = {"busy": True, "stopping": False, "open": True, "degraded": False, "can_send": False}

DONE_VM = _vm(0, status="ok", stages=[
    _stage(0, "geom", BODY, status="ok", attempts=1, elapsed_s=12.0),
    _stage(1, "geom", WHEELS, status="ok", attempts=2, elapsed_s=75.0)],
    objects=["fuse_1", "mtr_1_solid_1", "mtr_1_solid_2", "mtr_1_solid_3", "mtr_1_solid_4"],
    files={"result_py": "/tmp/run/result.py", "report_md": "/tmp/run/report.md"},
    usage={"calls": 18, "prompt_tokens": 70819, "completion_tokens": 14763, "llm_seconds": 90.2})
EDIT_VM = _vm(1, status="ok", message="Updated the wheels.", edits=[
    {"op": "edit", "node": "torus_1", "param": "radius_major", "old": "12", "new": "16"},
    {"op": "edit", "node": "mtr_1", "param": "step", "old": "60", "new": "70"},
    {"op": "replay", "nodes": ["torus_1", "rot_1", "tr_2", "mtr_1"]}],
    files={"result_py": "/tmp/run/result.py", "report_md": "/tmp/run/report.md"},
    usage={"calls": 4, "prompt_tokens": 9000, "completion_tokens": 1200, "llm_seconds": 11.0})
PLAN_VM = _vm(2, stages=[_stage(0, "geom", SPOILER), _stage(1, "smesh", MESH)],
              gate={"id": 1, "kind": "plan"})


def running_vm():
    return _vm(2, stages=[_stage(0, "geom", SPOILER, status="ok", attempts=1, elapsed_s=18.0),
                          _stage(1, "smesh", MESH, status="running", attempts=1,
                                 started_at=time.time() - 24)])


FAILED_VM = _vm(2, stages=[
    _stage(0, "geom", SPOILER, status="ok", attempts=1, elapsed_s=18.0),
    _stage(1, "smesh", MESH, status="failed", attempts=3,
           error="Compute failed: NETGEN_3D could not mesh fuse_2\n"
                 "(self-intersecting faces near the spoiler posts)")],
    gate={"id": 2, "kind": "stage_failed", "stage": 1,
          "message": "Compute failed: NETGEN_3D could not mesh fuse_2\n"
                     "(self-intersecting faces near the spoiler posts)", "line": None})

BASE = [("setSettings", SETTINGS), ("setStatus", STATUS_OK)]
HISTORY = [("addUser", {"text": USER_1}), ("renderTurn", DONE_VM),
           ("addUser", {"text": USER_2}), ("renderTurn", EDIT_VM),
           ("addUser", {"text": USER_3})]

STATES = {
    "empty": BASE + [("setBusy", IDLE_NEW)],
    "offline": [("setSettings", SETTINGS), ("setStatus", STATUS_OFF),
                ("setBusy", dict(IDLE_NEW, can_send=False))],
    "plan": BASE + [("setBusy", BUSY)] + HISTORY + [("renderTurn", PLAN_VM)],
    "running": BASE + [("setBusy", BUSY)] + HISTORY + [("renderTurn", "running")],
    "failed": BASE + [("setBusy", BUSY)] + HISTORY + [("renderTurn", FAILED_VM)],
    "conversation": BASE + [("setBusy", IDLE_OPEN)] + HISTORY[:4] + [
        ("addNote", {"text": "undo: undone back to turn 1"})],
    "settings": BASE + [("setBusy", IDLE_OPEN)] + HISTORY[:4] + [
        ("__js__", "document.body.classList.add('settings-open')")],
}


def resolve(payload):
    """`running` is built at push time so its live timer starts near 0:24."""
    return running_vm() if payload == "running" else payload
```

- [ ] **Step 2: Write the failing loader test** — create `tests/test_web_view.py`:

```python
import sys

from PyQt5.QtWidgets import QLabel

from salome_agent_gui import web_view
from tools.page_fixtures import FakeBridge


def test_web_dir_holds_the_page():
    for name in ("index.html", "app.css", "app.js", "salome-s.png"):
        assert (web_view.WEB_DIR / name).is_file(), name


def test_missing_webengine_gives_a_fallback_panel_with_the_fixes(qtbot, monkeypatch):
    monkeypatch.setitem(sys.modules, "PyQt5.QtWebEngineWidgets", None)
    w = web_view.create(None, FakeBridge())
    qtbot.addWidget(w)
    assert isinstance(w, QLabel)
    assert "QTWEBENGINE_DISABLE_SANDBOX=1" in w.text()
    assert "--disable-gpu" in w.text()


def test_page_never_loads_remote_resources():
    for name in ("index.html", "app.css", "app.js"):
        text = (web_view.WEB_DIR / name).read_text()
        assert "http://" not in text and "https://" not in text.replace(
            "http://www.w3.org/2000/svg", ""), name
```

- [ ] **Step 3: Write the failing page tests** — create `tests/test_page.py`:

```python
import time

import pytest

from salome_agent_gui import web_view
from tools.page_fixtures import (BUSY, DONE_VM, EDIT_VM, FAILED_VM, IDLE_OPEN, PLAN_VM,
                                 SETTINGS, STATUS_OFF, STATUS_OK, FakeBridge)

pytestmark = pytest.mark.web

EVIL = '<img src=x onerror="window.pwned=1">'


def run_js(qtbot, view, code):
    box = []
    view.page().runJavaScript(code, box.append)
    qtbot.waitUntil(lambda: len(box) == 1, timeout=5000)
    return box[0]


def wait_js(qtbot, view, code, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if run_js(qtbot, view, code):
            return
        qtbot.wait(50)
    raise AssertionError(f"never true: {code}")


@pytest.fixture
def page(qtbot):
    fake = FakeBridge()
    view = web_view.create(None, fake)
    qtbot.addWidget(view)
    view.resize(900, 760)
    view.show()
    qtbot.waitUntil(lambda: fake.ready_calls == 1, timeout=20000)
    fake.emit("setSettings", SETTINGS)
    fake.emit("setStatus", STATUS_OK)
    fake.emit("setBusy", IDLE_OPEN)
    return view, fake


def test_page_calls_ready_and_starts_empty(qtbot, page):
    view, _ = page
    wait_js(qtbot, view, "document.body.classList.contains('is-empty')")
    assert run_js(qtbot, view, "document.getElementById('status-label').textContent") == \
        "GUI :46019 · auto"


def test_turn_shows_steps_with_icons_or_badges(qtbot, page):
    view, fake = page
    vm = dict(PLAN_VM, stages=[dict(PLAN_VM["stages"][0], icon="file:///nowhere/geom.png"),
                               PLAN_VM["stages"][1]])
    fake.emit("renderTurn", vm)
    wait_js(qtbot, view, "document.querySelectorAll('.step').length === 2")
    assert run_js(qtbot, view, "document.querySelector('.step img.mod').title") == "GEOM"
    assert run_js(qtbot, view, "document.querySelector('.step .badge').textContent") == "smesh"
    assert run_js(qtbot, view, "document.body.classList.contains('is-empty')") is False


def test_engine_text_is_never_html(qtbot, page):
    view, fake = page
    vm = dict(DONE_VM, status="failed", message=EVIL, objects=[EVIL],
              stages=[dict(DONE_VM["stages"][0], intent=EVIL, error=EVIL, status="failed")],
              edits=[{"op": "edit", "node": EVIL, "param": EVIL, "old": EVIL, "new": EVIL}])
    fake.emit("addUser", {"text": EVIL})
    fake.emit("addNote", {"text": EVIL})
    fake.emit("renderTurn", vm)
    wait_js(qtbot, view, "document.querySelectorAll('.msg-agent').length === 1")
    assert run_js(qtbot, view,
                  "document.querySelectorAll('#col img:not(.avatar):not(.mod)').length") == 0
    assert run_js(qtbot, view, "window.pwned === undefined") is True
    assert run_js(qtbot, view,
                  "document.getElementById('col').textContent.includes('<img src=x')") is True


def test_approve_click_reaches_the_bridge_and_disables_the_buttons(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    wait_js(qtbot, view, "!!document.querySelector('[data-action=approve]')")
    run_js(qtbot, view, "document.querySelector('[data-action=approve]').click();"
                        "document.querySelector('[data-action=approve]').click(); true")
    qtbot.waitUntil(lambda: ("gate", 1, "approve", "") in fake.calls, timeout=3000)
    qtbot.wait(200)
    assert [c for c in fake.calls if c[0] == "gate"] == [("gate", 1, "approve", "")]
    assert run_js(qtbot, view, "document.querySelector('[data-action=abort]').disabled") is True


def test_edit_plan_click_keeps_the_buttons_enabled(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    wait_js(qtbot, view, "!!document.querySelector('[data-action=edit]')")
    run_js(qtbot, view, "document.querySelector('[data-action=edit]').click(); true")
    qtbot.waitUntil(lambda: ("gate", 1, "edit", "") in fake.calls, timeout=3000)
    assert run_js(qtbot, view, "document.querySelector('[data-action=approve]').disabled") is False


def test_hint_needs_text_and_sends_it(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", FAILED_VM)
    wait_js(qtbot, view, "!!document.querySelector('[data-action=show-hint]')")
    assert run_js(qtbot, view, "document.querySelector('.gate-warn .err').textContent") == \
        FAILED_VM["gate"]["message"]
    run_js(qtbot, view, "document.querySelector('[data-action=show-hint]').click();"
                        "document.querySelector('[data-action=hint]').click(); true")
    qtbot.wait(200)
    assert not [c for c in fake.calls if c[0] == "gate"]
    run_js(qtbot, view, "document.querySelector('.hint-box textarea').value = 'use r=2';"
                        "document.querySelector('[data-action=hint]').click(); true")
    qtbot.waitUntil(lambda: ("gate", 2, "hint", "use r=2") in fake.calls, timeout=3000)


def test_busy_turns_send_into_stop(qtbot, page):
    view, fake = page
    fake.emit("setBusy", BUSY)
    wait_js(qtbot, view, "document.getElementById('send').classList.contains('stop')")
    assert run_js(qtbot, view, "document.getElementById('btn-undo').disabled") is True
    run_js(qtbot, view, "document.getElementById('send').click(); true")
    qtbot.waitUntil(lambda: ("stop",) in fake.calls, timeout=3000)
    fake.emit("setBusy", dict(BUSY, stopping=True))
    wait_js(qtbot, view, "document.getElementById('send').disabled")
    assert "Stopping" in run_js(qtbot, view, "document.getElementById('hint').textContent")


def test_enter_sends_and_shift_enter_does_not(qtbot, page):
    view, fake = page
    wait_js(qtbot, view, "!document.getElementById('send').disabled")
    key = ("document.getElementById('input').dispatchEvent(new KeyboardEvent('keydown',"
           "{key: 'Enter', shiftKey: %s, bubbles: true, cancelable: true})); true")
    run_js(qtbot, view, "document.getElementById('input').value = 'line one'; true")
    run_js(qtbot, view, key % "true")
    qtbot.wait(200)
    assert not [c for c in fake.calls if c[0] == "send"]
    run_js(qtbot, view, key % "false")
    qtbot.waitUntil(lambda: ("send", "line one") in fake.calls, timeout=3000)
    assert run_js(qtbot, view, "document.getElementById('input').value") == ""


def test_result_shows_objects_file_chips_and_usage(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", DONE_VM)
    wait_js(qtbot, view, "!!document.querySelector('.result')")
    assert run_js(qtbot, view, "document.querySelector('.result-line').textContent") == \
        "Built 5 objects"
    assert run_js(qtbot, view, "document.querySelectorAll('.objects .chip').length") == 5
    usage = run_js(qtbot, view, "document.querySelector('.usage').textContent")
    assert "18 LLM calls" in usage and "71k in / 15k out" in usage
    run_js(qtbot, view, "document.querySelector('[data-file=result_py]').click(); true")
    qtbot.waitUntil(lambda: ("openFile", "/tmp/run/result.py") in fake.calls, timeout=3000)


def test_edits_card_lists_changes(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", EDIT_VM)
    wait_js(qtbot, view, "document.querySelectorAll('.edits li').length === 2")
    assert "4 objects rebuilt" in run_js(qtbot, view,
                                         "document.querySelector('.card-head').textContent")


def test_render_turn_replaces_the_same_turn(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    fake.emit("renderTurn", dict(PLAN_VM, gate=None, status="aborted"))
    wait_js(qtbot, view, "!!document.querySelector('.result')")
    assert run_js(qtbot, view, "document.querySelectorAll('.msg-agent').length") == 1


def test_replay_rebuilds_the_transcript(qtbot, page):
    view, fake = page
    fake.emit("addUser", {"text": "old"})
    fake.emit("replay", {"items": [{"type": "user", "text": "a"},
                                   {"type": "turn", "vm": DONE_VM},
                                   {"type": "note", "text": "undo: done"}]})
    wait_js(qtbot, view, "document.querySelectorAll('#col > *').length === 3")
    assert run_js(qtbot, view, "document.querySelector('.msg-user').textContent") == "a"


def test_offline_status_shows_the_banner(qtbot, page):
    view, fake = page
    fake.emit("setStatus", STATUS_OFF)
    wait_js(qtbot, view, "!document.getElementById('banner').hidden")
    assert "Plugins" in run_js(qtbot, view, "document.getElementById('banner').textContent")


def test_settings_lock_run_options_and_save(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, locked=True))
    wait_js(qtbot, view, "document.getElementById('set-on-failure').disabled")
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('set-model').value = 'qwen';"
                        "document.getElementById('set-theme').value = 'dark';"
                        "document.getElementById('btn-save').click(); true")
    qtbot.waitUntil(lambda: any(c[0] == "saveSettings" for c in fake.calls), timeout=3000)
    saved = [c for c in fake.calls if c[0] == "saveSettings"][-1][1]
    assert saved == {"base_url": "http://llm.example/v1", "model": "qwen", "api_key": "sk-test",
                     "theme": "dark"}


def test_theme_push_sets_the_theme(qtbot, page):
    view, fake = page
    fake.emit("setTheme", {"theme": "dark"})
    wait_js(qtbot, view, "document.documentElement.dataset.theme === 'dark'")
```

- [ ] **Step 4: Run them to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_web_view.py`
Expected: FAIL, `ImportError: cannot import name 'web_view'`.
Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web tests/test_page.py`
Expected: FAIL for the same reason.

- [ ] **Step 5: Create `salome_agent_gui/web_view.py`**

```python
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QLabel

WEB_DIR = Path(__file__).resolve().parent / "web"
WEBENGINE_HELP = (
    "The chat page could not start ({error}).\n\n"
    "Qt WebEngine (Chromium) failed to load. Start SALOME again with one of these set:\n"
    "    QTWEBENGINE_DISABLE_SANDBOX=1\n"
    "    QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu\n"
    "and check that PyQtWebEngine is installed in the salome_agent_gui environment.")


def fallback(parent, error) -> QLabel:
    label = QLabel(WEBENGINE_HELP.format(error=error), parent)
    label.setWordWrap(True)
    label.setMargin(24)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def create(parent, bridge):
    try:
        from PyQt5.QtWebChannel import QWebChannel
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError as e:
        return fallback(parent, e)
    view = QWebEngineView(parent)
    view.setContextMenuPolicy(Qt.NoContextMenu)
    view.setAcceptDrops(False)
    channel = QWebChannel(view.page())
    channel.registerObject("bridge", bridge)
    view.page().setWebChannel(channel)
    view._channel = channel                     # the page does not own it; keep it alive

    def on_crash(status, code):
        bridge.page_lost()
        view.reload()

    view.page().renderProcessTerminated.connect(on_crash)
    view.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))
    return view
```

- [ ] **Step 6: Create `salome_agent_gui/web/index.html`**

```html
<!doctype html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<title>SALOME Agent</title>
<link rel="stylesheet" href="app.css">
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="app.js" defer></script>
</head>
<body class="is-empty">

<header class="header">
  <div class="brand"><img class="logo" src="salome-s.png" alt="">SALOME Agent</div>
  <span class="status off" id="status"><span class="dot"></span><span id="status-label">Not connected</span></span>
  <span class="spacer"></span>
  <button class="icon-btn" id="btn-undo" data-tip="Undo last turn" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg></button>
  <button class="icon-btn" id="btn-redo" data-tip="Redo" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/></svg></button>
  <button class="icon-btn" id="btn-rebuild" data-tip="Rebuild the study from the model" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/></svg></button>
  <span class="hdr-sep"></span>
  <button class="icon-btn" id="btn-new" data-tip="New conversation" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg></button>
  <button class="icon-btn" id="btn-help" data-tip="Help"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01"/></svg></button>
  <button class="icon-btn" id="btn-settings" data-tip="Settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg></button>
</header>

<div class="banner" id="banner" hidden></div>
<div class="help" id="help" hidden>
  The first message starts a conversation: I propose a plan, you approve or edit it, and each
  stage is built in this SALOME study. Follow-up messages change that model ("make the roof
  taller", "add a chimney"). Undo and Redo step through turns; Rebuild recreates the study from
  the model when they got out of sync; New conversation starts over. While a conversation is
  open it keeps the agent server to itself. result.py and report.md are linked after each turn.
</div>

<div class="empty">
  <img class="logo-big" src="salome-s.png" alt="">
  <h2>What should we build?</h2>
  <p>Describe a part or an assembly. I'll propose a plan, build it in this SALOME study, and you can keep refining it by chatting.</p>
  <div class="suggestions">
    <button class="suggestion" data-text="A small car with 4 torus wheels, red body and black wheels">A small car with 4 torus wheels<small>red body, black wheels</small></button>
    <button class="suggestion" data-text="A vase with a 2 mm wall, revolved profile and a filleted rim">A vase with a 2 mm wall<small>revolved profile, filleted rim</small></button>
    <button class="suggestion" data-text="A bracket with 4 mounting holes, then mesh it with tetrahedra">A bracket with 4 mounting holes<small>then mesh it with tetrahedra</small></button>
    <button class="suggestion" data-text="A simple house with walls, a pitched roof and a door">A simple house<small>walls, pitched roof, a door</small></button>
  </div>
</div>

<main class="transcript" id="transcript"><div class="col" id="col"></div></main>

<div class="composer-wrap">
  <div class="composer">
    <textarea id="input" rows="1" placeholder="Describe what to build, or ask for a change…"></textarea>
    <div class="composer-row">
      <span class="mode" id="auto" title="Build without the plan approval step"><span class="switch small" id="batch-sw"></span>Auto-approve plans</span>
      <span class="spacer"></span>
      <span class="hint" id="hint">Enter to send · Shift+Enter for a new line</span>
      <button class="send" id="send" title="Send" disabled></button>
    </div>
  </div>
</div>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer">
  <div class="drawer-head">Settings<span class="spacer"></span>
    <button class="icon-btn" id="btn-close-settings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg></button>
  </div>
  <div class="drawer-body">
    <div>
      <div class="section-title">Agent server</div>
      <div class="conn-card" id="conn-card"><span class="dot"></span><span id="conn-label"></span><span class="spacer"></span><button class="btn ghost small" id="btn-reconnect">Reconnect</button></div>
    </div>
    <div>
      <div class="section-title">Model</div>
      <div class="field"><label for="set-base-url">LLM base URL</label><input id="set-base-url"></div>
      <div class="row2">
        <div class="field"><label for="set-model">Model</label><input id="set-model"></div>
        <div class="field"><label for="set-api-key">API key</label><input id="set-api-key" type="password"></div>
      </div>
    </div>
    <div>
      <div class="section-title">Runs <span class="lock-note" id="run-lock" hidden>— locked while a conversation is open</span></div>
      <div class="toggle-row"><div><div class="t-label">Auto-approve plans</div><div class="t-help">Build without the approval step</div></div><span class="switch" id="set-batch"></span></div>
      <div class="row2">
        <div class="field"><label for="set-on-failure">When a stage fails</label><select id="set-on-failure"><option value="abort">Stop the run</option><option value="continue">Continue</option></select></div>
        <div class="field"><label for="set-tools">Tools offered</label><select id="set-tools"><option value="hints">Planner hints</option><option value="all">All tools</option></select></div>
      </div>
      <div class="field"><label for="set-verbose">Log detail</label><select id="set-verbose"><option value="0">Normal</option><option value="1">Verbose</option><option value="2">LLM trace (-vv)</option></select></div>
    </div>
    <div>
      <div class="section-title">Appearance</div>
      <div class="field"><label for="set-theme">Theme</label><select id="set-theme"><option value="system">Same as SALOME</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
    </div>
    <div>
      <div class="section-title">Configuration file</div>
      <div class="path" id="config-path"></div>
      <div class="drawer-actions"><button class="btn" id="btn-edit-json">Edit JSON…</button></div>
    </div>
  </div>
  <div class="drawer-foot"><button class="btn" id="btn-cancel">Cancel</button><button class="btn primary" id="btn-save">Save</button></div>
</aside>

</body>
</html>
```

- [ ] **Step 7: Create `salome_agent_gui/web/app.css`**

```css
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-2: #f1f3f6;
  --border: #e3e6eb;
  --text: #1d2330;
  --text-2: #5b6474;
  --text-3: #8b93a1;
  --accent: #2f6fec;
  --accent-soft: #e8f0fe;
  --accent-text: #ffffff;
  --user-bubble: #2f6fec;
  --ok: #1f9d55;
  --ok-soft: #e6f6ec;
  --warn: #c77700;
  --warn-soft: #fff4e0;
  --err: #d64545;
  --err-soft: #fdecec;
  --badge-geom: #7a4fd6;
  --badge-geom-soft: #f1ebfd;
  --badge-smesh: #0e8a7e;
  --badge-smesh-soft: #e3f5f3;
  --badge-paravis: #c2410c;
  --badge-paravis-soft: #fdebdc;
  --shadow: 0 1px 2px rgba(20, 30, 50, .06), 0 4px 16px rgba(20, 30, 50, .06);
  --radius: 14px;
  --mono: ui-monospace, "JetBrains Mono", "DejaVu Sans Mono", monospace;
}
[data-theme="dark"] {
  --bg: #15181e;
  --surface: #1c2028;
  --surface-2: #232833;
  --border: #2e3440;
  --text: #e6e9ef;
  --text-2: #a4acba;
  --text-3: #6f7888;
  --accent: #5b8ff9;
  --accent-soft: #1f2d4a;
  --user-bubble: #3a6ff0;
  --ok: #4cc27f;
  --ok-soft: #173325;
  --warn: #f0a93b;
  --warn-soft: #3a2c14;
  --err: #f07171;
  --err-soft: #3d1c1f;
  --badge-geom: #b39af5;
  --badge-geom-soft: #2d2445;
  --badge-smesh: #4fd1c1;
  --badge-smesh-soft: #163531;
  --badge-paravis: #f59e6b;
  --badge-paravis-soft: #3a2518;
  --shadow: 0 1px 2px rgba(0,0,0,.3), 0 6px 20px rgba(0,0,0,.25);
}

* { box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { margin: 0; height: 100%; }
body {
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", Cantarell, "Noto Sans", sans-serif;
  background: var(--bg);
  color: var(--text);
  display: flex; flex-direction: column;
  overflow: hidden; position: relative;
}
button { font: inherit; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 999px; border: 2px solid var(--bg); }
::-webkit-scrollbar-thumb:hover { background: var(--text-3); }
::-webkit-scrollbar-button { display: none; }

/* ---- header ---- */
.header {
  flex: none;
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.brand { display: flex; align-items: center; gap: 8px; font-weight: 650; }
.brand .logo { width: 24px; height: 24px; object-fit: contain; }
.status {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 3px 10px; border-radius: 999px;
  background: var(--surface-2); color: var(--text-2); font-size: 12.5px;
  border: 1px solid var(--border);
}
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); flex: none; }
.status.off .dot, .conn-card.off .dot { background: var(--err); box-shadow: 0 0 0 3px var(--err-soft); }
.spacer { flex: 1; }
.icon-btn {
  width: 32px; height: 32px; border-radius: 8px;
  border: 1px solid transparent; background: transparent; color: var(--text-2);
  display: grid; place-items: center; cursor: pointer; position: relative; padding: 0;
}
.icon-btn:hover:not(:disabled) { background: var(--surface-2); color: var(--text); border-color: var(--border); }
.icon-btn:disabled { opacity: .35; cursor: default; }
.icon-btn svg { width: 18px; height: 18px; }
.icon-btn[data-tip]:hover:not(:disabled)::after {
  content: attr(data-tip);
  position: absolute; top: 38px; right: 0; white-space: nowrap; z-index: 5;
  background: var(--text); color: var(--surface); font-size: 12px;
  padding: 4px 8px; border-radius: 6px;
}
.hdr-sep { width: 1px; height: 22px; background: var(--border); }

.banner {
  flex: none; margin: 10px 18px 0; padding: 10px 14px; border-radius: 10px;
  background: var(--err-soft); color: var(--err); font-size: 13px;
}
.help {
  flex: none; margin: 10px 18px 0; padding: 12px 14px; border-radius: 10px;
  background: var(--surface); border: 1px solid var(--border); color: var(--text-2); font-size: 13px;
}

/* ---- transcript ---- */
.transcript { flex: 1; overflow-y: auto; padding: 20px 0 8px; }
.col { max-width: 720px; margin: 0 auto; padding: 0 18px; display: flex; flex-direction: column; gap: 18px; }

.msg-user { display: flex; justify-content: flex-end; }
.msg-user .bubble {
  max-width: 78%;
  background: var(--user-bubble); color: #fff;
  padding: 9px 14px; border-radius: 18px 18px 4px 18px;
  white-space: pre-wrap; word-break: break-word;
}

.msg-agent { display: flex; gap: 10px; align-items: flex-start; }
.avatar { flex: none; width: 26px; height: 26px; object-fit: contain; margin-top: 3px; }
.agent-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 10px; }
.agent-text { color: var(--text); }
.agent-text .muted, .agent-text.muted { color: var(--text-2); }

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.card-head {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; border-bottom: 1px solid var(--border);
  font-weight: 600; font-size: 13.5px;
}
.card-head svg { width: 16px; height: 16px; flex: none; }
.card-head .count { color: var(--text-3); font-weight: 500; }
.card-foot {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px;
  padding: 10px 14px; border-top: 1px solid var(--border); background: var(--surface-2);
}

.steps { list-style: none; margin: 0; padding: 6px 0; }
.step { display: flex; gap: 10px; align-items: flex-start; padding: 7px 14px; }
.step .st { flex: none; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; margin-top: 1px; }
.step .st svg { width: 12px; height: 12px; }
.st.ok { background: var(--ok-soft); color: var(--ok); }
.st.run { color: var(--accent); }
.st.fail { background: var(--err-soft); color: var(--err); }
.st.pend { border: 1.5px dashed var(--text-3); }
.st.skip { background: var(--surface-2); color: var(--text-3); }
.step .main { flex: 1; min-width: 0; }
.step .line { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.step .intent { color: var(--text); word-break: break-word; }
.step.pending .intent { color: var(--text-2); }
.step .meta { color: var(--text-3); font-size: 12px; margin-left: auto; white-space: nowrap; }
.err {
  margin-top: 6px; padding: 8px 10px; border-radius: 8px;
  background: var(--err-soft); color: var(--err); font-size: 12.5px; white-space: pre-wrap;
  font-family: var(--mono); word-break: break-word;
}
.mod { width: 20px; height: 20px; flex: none; object-fit: contain; }
.badge {
  display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .04em;
  padding: 1px 7px; border-radius: 6px; text-transform: uppercase;
  color: var(--text-2); background: var(--surface-2);
}
.badge.geom { color: var(--badge-geom); background: var(--badge-geom-soft); }
.badge.smesh { color: var(--badge-smesh); background: var(--badge-smesh-soft); }
.badge.paravis { color: var(--badge-paravis); background: var(--badge-paravis-soft); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 550;
  padding: 6px 12px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--text);
}
.btn:hover:not(:disabled) { background: var(--surface-2); }
.btn:disabled { opacity: .5; cursor: default; }
.btn svg { width: 15px; height: 15px; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-text); }
.btn.primary:hover:not(:disabled) { background: var(--accent); filter: brightness(1.07); }
.btn.ghost { border-color: transparent; background: transparent; color: var(--text-2); }
.btn.ghost:hover:not(:disabled) { background: var(--surface); border-color: var(--border); }
.btn.danger, .btn.ghost.danger { color: var(--err); }
.btn.small { padding: 2px 8px; }

.gate-warn { border-color: var(--warn); }
.gate-warn .card-head { color: var(--warn); background: var(--warn-soft); }
.gate-body { padding: 10px 14px; }
.gate-body .err { margin-top: 0; }
.err-line { margin-top: 6px; color: var(--text-3); font-size: 12px; }
.hint-box { display: flex; gap: 8px; align-items: flex-end; padding: 10px 14px; border-top: 1px solid var(--border); }
.hint-box textarea {
  flex: 1; font: inherit; color: var(--text); background: var(--surface-2);
  border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px; resize: vertical;
}

.result { display: flex; flex-direction: column; gap: 8px; }
.result-line { display: flex; align-items: center; gap: 8px; font-weight: 600; flex-wrap: wrap; }
.result-line .result-msg { font-weight: 400; color: var(--text-2); }
.res-ic { display: grid; }
.res-ic svg { width: 18px; height: 18px; }
.result-line.ok .res-ic { color: var(--ok); }
.result-line.bad .res-ic { color: var(--err); }
.result-line.warn .res-ic { color: var(--warn); }
.result-line.info .res-ic { color: var(--accent); }
.result-line.muted .res-ic { color: var(--text-3); }
.result > .err { margin-top: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px; font-size: 12.5px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text-2);
}
button.chip { cursor: pointer; }
button.chip:hover { color: var(--accent); border-color: var(--accent); }
.chip svg { width: 13px; height: 13px; }
details.objects summary {
  cursor: pointer; color: var(--text-2); font-size: 13px; list-style: none;
  display: inline-flex; align-items: center; gap: 4px;
}
details.objects summary::-webkit-details-marker { display: none; }
details.objects summary svg { width: 14px; height: 14px; transition: transform .15s; }
details.objects[open] summary svg { transform: rotate(90deg); }
details.objects .chips { margin-top: 8px; }
.usage { color: var(--text-3); font-size: 12px; display: flex; gap: 6px; flex-wrap: wrap; font-weight: 400; }
.usage span + span::before { content: "·"; margin-right: 6px; }

.edits { list-style: none; margin: 0; padding: 8px 14px; display: flex; flex-direction: column; gap: 6px; }
.edits li { display: flex; gap: 8px; align-items: baseline; font-size: 13px; flex-wrap: wrap; }
.edits code {
  font-family: var(--mono); font-size: 12.5px; background: var(--surface-2);
  padding: 1px 6px; border-radius: 5px; word-break: break-all;
}
.edits .old { color: var(--err); text-decoration: line-through; }
.edits .new { color: var(--ok); font-weight: 600; }
.edits .arrow { color: var(--text-3); }

.note {
  align-self: center; color: var(--text-3); font-size: 12.5px;
  display: flex; align-items: center; gap: 10px; width: 100%; text-align: center;
}
.note::before, .note::after { content: ""; flex: 1; height: 1px; background: var(--border); }

/* ---- empty state ---- */
.empty {
  flex: 1; display: none; flex-direction: column; align-items: center; justify-content: center;
  gap: 14px; padding: 24px; text-align: center;
}
.empty .logo-big { width: 72px; height: 72px; object-fit: contain; }
.empty h2 { margin: 0; font-size: 20px; }
.empty p { margin: 0; color: var(--text-2); max-width: 440px; }
.suggestions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 6px; width: 100%; max-width: 520px; }
.suggestion {
  text-align: left; padding: 10px 12px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font-size: 13px;
}
.suggestion:hover { border-color: var(--accent); }
.suggestion small { display: block; color: var(--text-3); font-size: 12px; }
body.is-empty .transcript { display: none; }
body.is-empty .empty { display: flex; }

/* ---- composer ---- */
.composer-wrap { flex: none; padding: 8px 18px 14px; }
.composer {
  max-width: 720px; margin: 0 auto;
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  box-shadow: var(--shadow);
  display: flex; flex-direction: column;
  transition: border-color .15s, box-shadow .15s;
}
.composer:focus-within { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.composer textarea {
  border: 0; outline: 0; resize: none; background: transparent; color: var(--text);
  font: inherit; padding: 12px 14px 4px; min-height: 24px; max-height: 180px;
}
.composer textarea::placeholder { color: var(--text-3); }
.composer-row { display: flex; align-items: center; gap: 8px; padding: 6px 8px 8px 12px; }
.composer-row .hint { color: var(--text-3); font-size: 12px; }
.mode {
  display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2);
  padding: 3px 8px; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border);
  cursor: pointer; user-select: none;
}
.mode.disabled { opacity: .5; cursor: default; }
.send {
  width: 34px; height: 34px; border-radius: 10px; border: 0; cursor: pointer;
  background: var(--accent); color: #fff; display: grid; place-items: center; padding: 0;
}
.send svg { width: 17px; height: 17px; }
.send.stop { background: var(--text); color: var(--surface); }
.send:disabled { opacity: .4; cursor: default; }

/* ---- settings drawer ---- */
.scrim {
  position: absolute; inset: 0; background: rgba(10, 14, 22, .35);
  opacity: 0; pointer-events: none; transition: opacity .2s;
}
.drawer {
  position: absolute; top: 0; right: 0; bottom: 0; width: 380px; max-width: 92%;
  background: var(--surface); border-left: 1px solid var(--border);
  box-shadow: -10px 0 30px rgba(0,0,0,.15);
  transform: translateX(105%); transition: transform .22s ease;
  display: flex; flex-direction: column;
}
body.settings-open .scrim { opacity: 1; pointer-events: auto; }
body.settings-open .drawer { transform: none; }
.drawer-head { display: flex; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); font-weight: 650; }
.drawer-body { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 14px 16px; display: flex; flex-direction: column; gap: 18px; }
.drawer-foot { padding: 12px 16px; border-top: 1px solid var(--border); display: flex; gap: 8px; justify-content: flex-end; }
.drawer-actions { margin-top: 8px; }
.section-title { font-size: 11.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); margin-bottom: 8px; }
.lock-note { text-transform: none; letter-spacing: 0; font-weight: 500; }
.field { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; }
.field label { font-size: 12.5px; color: var(--text-2); }
.field input, .field select {
  font: inherit; font-size: 13.5px; color: var(--text); min-width: 0; width: 100%;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 7px 10px;
}
.field input:focus, .field select:focus { outline: 2px solid var(--accent-soft); border-color: var(--accent); }
.field select:disabled { opacity: .5; }
.row2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 0; }
.toggle-row .t-label { font-size: 13.5px; }
.toggle-row .t-help { font-size: 12px; color: var(--text-3); }
.switch { width: 36px; height: 20px; border-radius: 999px; background: var(--border); position: relative; flex: none; cursor: pointer; }
.switch::after { content: ""; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: left .15s; }
.switch.on { background: var(--accent); }
.switch.on::after { left: 18px; }
.switch.small { transform: scale(.75); margin: -2px -4px; }
.switch.disabled { opacity: .5; cursor: default; }
.conn-card { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 10px; background: var(--ok-soft); color: var(--ok); font-size: 13px; }
.conn-card.off { background: var(--err-soft); color: var(--err); }
.path { font-family: var(--mono); font-size: 12px; color: var(--text-2); word-break: break-all; }
```

- [ ] **Step 8: Create `salome_agent_gui/web/app.js`**

```javascript
"use strict";

// Constant SVG markup only. Everything that comes from the engine or the LLM is
// set with textContent; never pass it to innerHTML / insertAdjacentHTML.
const ICON = {
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  fail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  run: '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg>',
  skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>',
  approve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
};
const STEP = { ok: ["st ok", "ok"], running: ["st run", "run"], failed: ["st fail", "fail"],
               skipped: ["st skip", "skip"], pending: ["st pend", null] };
const LEAD = { needs_input: "Question", failed: "Turn failed", fatal: "Run failed",
               degraded: "Study out of sync", ended: "Session ended", aborted: "Run aborted" };
const TONE = { ok: "ok", needs_input: "info", degraded: "warn", ended: "warn", aborted: "muted" };

let bridge = null;
const state = { busy: false, open: false, canSend: false, stopping: false, locked: false, settings: null };
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}
function svg(parent, name) { parent.insertAdjacentHTML("beforeend", ICON[name]); return parent; }
function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }
function ordinal(n) {
  const t = n % 100;
  if (t >= 11 && t <= 13) return `${n}th`;
  return n + ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
}
function fmtDuration(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${s % 60} s`;
}
function fmtClock(s) {
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function fmtTokens(n) {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
}

// ---- transcript -------------------------------------------------------
function col() { return $("col"); }
function nearBottom() {
  const t = $("transcript");
  return t.scrollHeight - t.scrollTop - t.clientHeight < 80;
}
function scrollEnd() { const t = $("transcript"); t.scrollTop = t.scrollHeight; }
function updateEmpty() { document.body.classList.toggle("is-empty", col().children.length === 0); }
function append(node) {
  const stick = nearBottom();
  col().appendChild(node);
  updateEmpty();
  if (stick) scrollEnd();
}

function userNode(text) {
  const d = el("div", "msg-user");
  d.appendChild(el("div", "bubble", text));
  return d;
}
function noteNode(text) { return el("div", "note", text); }

function btn(label, cls, action, onClick, icon) {
  const b = el("button", "btn" + (cls ? " " + cls : ""));
  b.dataset.action = action;
  if (icon) svg(b, icon);
  b.appendChild(document.createTextNode(label));
  b.addEventListener("click", onClick);
  return b;
}
function answer(gate, action, text, container) {
  container.querySelectorAll("button, textarea").forEach((x) => { x.disabled = true; });
  bridge.gate(gate.id, action, text || "");
}

function stepRow(s, vm) {
  const li = el("li", "step" + (s.status === "pending" ? " pending" : ""));
  const [cls, icon] = STEP[s.status] || STEP.pending;
  const st = el("span", cls);
  if (icon) svg(st, icon);
  li.appendChild(st);
  const main = el("div", "main");
  const line = el("div", "line");
  if (s.icon) {
    const img = el("img", "mod");
    img.src = s.icon;
    img.alt = s.module;
    img.title = String(s.module).toUpperCase();
    line.appendChild(img);
  } else {
    const known = ["geom", "smesh", "paravis"].includes(s.module) ? " " + s.module : "";
    line.appendChild(el("span", "badge" + known, s.module));
  }
  line.appendChild(el("span", "intent", s.intent));
  const meta = el("span", "meta");
  if (s.status === "running" && s.started_at) {
    meta.dataset.start = s.started_at;
    meta.textContent = fmtClock(Date.now() / 1000 - s.started_at);
  } else {
    const bits = [];
    if (s.elapsed_s !== null && s.elapsed_s !== undefined) bits.push(fmtDuration(s.elapsed_s));
    if (s.status === "failed" && s.attempts > 0) bits.push(plural(s.attempts, "attempt"));
    else if (s.attempts > 1) bits.push(`${ordinal(s.attempts)} attempt`);
    meta.textContent = bits.join(" · ");
  }
  line.appendChild(meta);
  main.appendChild(line);
  const gateShowsError = vm.gate && vm.gate.kind === "stage_failed";
  if (s.error && s.status === "failed" && !gateShowsError) main.appendChild(el("div", "err", s.error));
  li.appendChild(main);
  return li;
}

function planFoot(gate) {
  const f = el("div", "card-foot");
  f.appendChild(btn("Approve & build", "primary", "approve", () => answer(gate, "approve", "", f), "approve"));
  f.appendChild(btn("Edit plan", null, "edit", () => bridge.gate(gate.id, "edit", "")));
  f.appendChild(el("span", "spacer"));
  f.appendChild(btn("Abort", "ghost danger", "abort", () => answer(gate, "abort", "", f)));
  return f;
}

function stagesCard(vm) {
  const card = el("div", "card");
  const head = el("div", "card-head");
  const n = vm.stages.length;
  let title = "Plan";
  let count = `· ${plural(n, "stage")}`;
  if (vm.gate && vm.gate.kind === "plan") title = "Proposed plan";
  else if (vm.gate && vm.gate.kind === "stage_failed") { title = "Building"; count = "· waiting for you"; }
  else if (vm.status === "running") {
    title = "Building";
    const cur = vm.stages.findIndex((s) => s.status === "running");
    if (cur >= 0) count = `· stage ${cur + 1} of ${n}`;
  }
  head.appendChild(el("span", null, title));
  head.appendChild(el("span", "count", count));
  const total = vm.stages.reduce((a, s) => a + (s.elapsed_s || 0), 0);
  if (vm.status !== "running" && total > 0) {
    head.appendChild(el("span", "spacer"));
    head.appendChild(el("span", "usage", `built in ${fmtDuration(total)}`));
  }
  card.appendChild(head);
  const ol = el("ol", "steps");
  for (const s of vm.stages) ol.appendChild(stepRow(s, vm));
  card.appendChild(ol);
  if (vm.gate && vm.gate.kind === "plan") card.appendChild(planFoot(vm.gate));
  return card;
}

function editsCard(edits) {
  const card = el("div", "card");
  const head = el("div", "card-head");
  const changes = edits.filter((e) => e.op !== "replay");
  const replay = edits.find((e) => e.op === "replay");
  head.appendChild(el("span", null, "Changes"));
  let count = `· ${plural(changes.length, "edit")}`;
  if (replay) count += `, ${plural(replay.nodes.length, "object")} rebuilt`;
  head.appendChild(el("span", "count", count));
  card.appendChild(head);
  const ul = el("ul", "edits");
  for (const e of changes) {
    const li = el("li");
    if (e.op === "edit") {
      li.appendChild(el("code", null, `${e.node}.${e.param}`));
      li.appendChild(el("span", "old", e.old));
      li.appendChild(el("span", "arrow", "→"));
      li.appendChild(el("span", "new", e.new));
    } else if (e.op === "delete") {
      li.appendChild(el("span", "old", "removed"));
      li.appendChild(el("code", null, e.nodes.join(", ")));
    } else {
      li.appendChild(el("span", "new", "added"));
      li.appendChild(el("code", null, `${e.node} (${e.new})`));
    }
    ul.appendChild(li);
  }
  card.appendChild(ul);
  return card;
}

function failCard(vm, gate) {
  const card = el("div", "card gate-warn");
  const head = el("div", "card-head");
  svg(head, "warn");
  const stage = gate.stage !== null && gate.stage !== undefined ? vm.stages[gate.stage] : null;
  let title = stage ? `Stage ${gate.stage + 1} failed` : "Stage failed";
  if (stage && stage.attempts > 1) title += ` after ${stage.attempts} attempts`;
  head.appendChild(el("span", null, title));
  card.appendChild(head);
  const body = el("div", "gate-body");
  body.appendChild(el("div", "err", gate.message || "(no message)"));
  if (gate.line) body.appendChild(el("div", "err-line", `at line ${gate.line}`));
  card.appendChild(body);
  const hintBox = el("div", "hint-box");
  hintBox.hidden = true;
  const ta = el("textarea");
  ta.rows = 2;
  ta.placeholder = "Tell the specialist what to try…";
  hintBox.appendChild(ta);
  hintBox.appendChild(btn("Send hint", "primary", "hint", () => {
    if (ta.value.trim()) answer(gate, "hint", ta.value, card);
  }));
  const f = el("div", "card-foot");
  f.appendChild(btn("Give a hint", "primary", "show-hint", () => { hintBox.hidden = false; ta.focus(); }));
  f.appendChild(btn("Skip stage", null, "skip", () => answer(gate, "skip", "", card)));
  f.appendChild(el("span", "spacer"));
  f.appendChild(btn("Abort run", "ghost danger", "abort", () => answer(gate, "abort", "", card)));
  card.appendChild(hintBox);
  card.appendChild(f);
  return card;
}

function resultBlock(vm) {
  const r = el("div", "result");
  const line = el("div", "result-line " + (TONE[vm.status] || "bad"));
  svg(line.appendChild(el("span", "res-ic")), vm.status === "ok" ? "done" : "warn");
  const msg = vm.message || "";
  const block = msg.includes("\n") || vm.status === "failed" || vm.status === "fatal";
  if (vm.status === "ok") {
    const n = vm.objects.length;
    line.appendChild(el("span", null, msg || (n ? `Built ${plural(n, "object")}` : "Done")));
  } else {
    line.appendChild(el("span", null, LEAD[vm.status] || vm.status));
    if (msg && !block) line.appendChild(el("span", "result-msg", msg));
  }
  r.appendChild(line);
  if (msg && block && vm.status !== "ok") r.appendChild(el("div", "err", msg));
  if (vm.objects.length) {
    const d = el("details", "objects");
    const s = el("summary");
    svg(s, "chevron");
    s.appendChild(document.createTextNode(`Show ${plural(vm.objects.length, "object")}`));
    d.appendChild(s);
    const chips = el("div", "chips");
    for (const name of vm.objects) chips.appendChild(el("span", "chip", name));
    d.appendChild(chips);
    r.appendChild(d);
  }
  const files = el("div", "chips");
  for (const [key, label, icon] of [["result_py", "result.py", "code"], ["report_md", "report.md", "doc"]]) {
    const path = vm.files && vm.files[key];
    if (!path) continue;
    const b = el("button", "chip");
    b.dataset.file = key;
    b.title = path;
    svg(b, icon);
    b.appendChild(document.createTextNode(label));
    b.addEventListener("click", () => bridge.openFile(path));
    files.appendChild(b);
  }
  if (files.children.length) r.appendChild(files);
  if (vm.usage) {
    const u = el("div", "usage");
    const x = vm.usage;
    if (x.calls !== undefined) u.appendChild(el("span", null, plural(x.calls, "LLM call")));
    if (x.prompt_tokens !== undefined) {
      u.appendChild(el("span", null, `${fmtTokens(x.prompt_tokens)} in / ${fmtTokens(x.completion_tokens || 0)} out`));
    }
    if (x.llm_seconds !== undefined) u.appendChild(el("span", null, `${fmtDuration(x.llm_seconds)} waiting on the model`));
    r.appendChild(u);
  }
  return r;
}

function turnNode(vm) {
  const wrap = el("div", "msg-agent");
  wrap.dataset.turn = String(vm.id);
  const av = el("img", "avatar");
  av.src = "salome-s.png";
  av.alt = "";
  const body = el("div", "agent-body");
  wrap.appendChild(av);
  wrap.appendChild(body);
  const gate = vm.gate;
  if (gate && gate.kind === "plan") {
    const t = el("div", "agent-text", "Here's the plan. ");
    t.appendChild(el("span", "muted", "Approve it to start building, or edit the stages first."));
    body.appendChild(t);
  }
  if (vm.stages.length) body.appendChild(stagesCard(vm));
  if (vm.edits.length) body.appendChild(editsCard(vm.edits));
  if (gate && gate.kind === "stage_failed") body.appendChild(failCard(vm, gate));
  if (!gate && vm.status !== "running") body.appendChild(resultBlock(vm));
  if (!vm.stages.length && !vm.edits.length && !gate && vm.status === "running") {
    body.appendChild(el("div", "agent-text muted", "Thinking…"));
  }
  return wrap;
}

function renderTurn(vm) {
  const node = turnNode(vm);
  const old = col().querySelector(`[data-turn="${vm.id}"]`);
  if (!old) { append(node); return; }
  const stick = nearBottom();
  old.replaceWith(node);
  if (stick) scrollEnd();
}

function replay(p) {
  col().textContent = "";
  for (const it of p.items) {
    if (it.type === "user") col().appendChild(userNode(it.text));
    else if (it.type === "note") col().appendChild(noteNode(it.text));
    else col().appendChild(turnNode(it.vm));
  }
  updateEmpty();
  scrollEnd();
}

// ---- header, status, busy ---------------------------------------------
function setBusy(p) {
  Object.assign(state, { busy: p.busy, open: p.open, canSend: p.can_send, stopping: p.stopping });
  const idleOpen = p.open && !p.busy;
  $("btn-undo").disabled = !idleOpen;
  $("btn-redo").disabled = !idleOpen;
  $("btn-new").disabled = !idleOpen;
  $("btn-rebuild").disabled = !(idleOpen && p.degraded);
  const send = $("send");
  send.classList.toggle("stop", p.busy);
  send.innerHTML = p.busy ? ICON.stop : ICON.send;
  send.title = p.busy ? "Stop" : "Send";
  send.disabled = p.busy ? p.stopping : !p.can_send;
  $("hint").textContent = p.stopping ? "Stopping…"
    : (p.busy ? "Working… press Stop to cancel" : "Enter to send · Shift+Enter for a new line");
  lockRunOptions(p.open);
}

function setStatus(p) {
  const connected = p.state === "connected";
  $("status").classList.toggle("off", !connected);
  $("status-label").textContent = p.label;
  $("banner").hidden = connected;
  $("banner").textContent = p.detail || "";
  $("conn-card").classList.toggle("off", !connected);
  $("conn-label").textContent = connected ? `Connected — ${p.label}` : (p.detail || p.label);
}

function setTheme(p) { document.documentElement.dataset.theme = p.theme === "dark" ? "dark" : "light"; }

// ---- settings -----------------------------------------------------------
function lockRunOptions(locked) {
  state.locked = locked;
  for (const id of ["set-on-failure", "set-tools", "set-verbose"]) $(id).disabled = locked;
  $("set-batch").classList.toggle("disabled", locked);
  $("auto").classList.toggle("disabled", locked);
  $("run-lock").hidden = !locked;
}

function setSettings(s) {
  state.settings = s;
  $("set-base-url").value = s.base_url || "";
  $("set-model").value = s.model || "";
  $("set-api-key").value = s.api_key || "";
  $("set-on-failure").value = s.on_stage_failure;
  $("set-tools").value = s.tool_selection;
  $("set-verbose").value = String(s.verbose);
  $("set-theme").value = s.theme;
  $("set-batch").classList.toggle("on", !!s.batch);
  $("batch-sw").classList.toggle("on", !!s.batch);
  $("config-path").textContent = s.config_path || "";
  lockRunOptions(!!s.locked);
}

function openSettings() { document.body.classList.add("settings-open"); }
function closeSettings() { document.body.classList.remove("settings-open"); }
function cancelSettings() { if (state.settings) setSettings(state.settings); closeSettings(); }

function saveSettings() {
  const out = {
    base_url: $("set-base-url").value.trim(),
    model: $("set-model").value.trim(),
    api_key: $("set-api-key").value,
    theme: $("set-theme").value,
  };
  if (!state.locked) {
    Object.assign(out, {
      batch: $("set-batch").classList.contains("on"),
      on_stage_failure: $("set-on-failure").value,
      tool_selection: $("set-tools").value,
      verbose: parseInt($("set-verbose").value, 10),
    });
  }
  bridge.saveSettings(JSON.stringify(out));
  closeSettings();
}

// ---- composer -----------------------------------------------------------
function autosize() {
  const t = $("input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 180) + "px";
}

function submit() {
  if (state.busy) {
    if (!state.stopping) bridge.stop();
    return;
  }
  const text = $("input").value.trim();
  if (!text || !state.canSend) return;
  bridge.send(text);
  $("input").value = "";
  autosize();
}

function tick() {
  const now = Date.now() / 1000;
  document.querySelectorAll("[data-start]").forEach((m) => {
    m.textContent = fmtClock(now - parseFloat(m.dataset.start));
  });
}

function wire() {
  $("btn-undo").addEventListener("click", () => bridge.command("undo"));
  $("btn-redo").addEventListener("click", () => bridge.command("redo"));
  $("btn-rebuild").addEventListener("click", () => bridge.command("rebuild"));
  $("btn-new").addEventListener("click", () => bridge.command("new"));
  $("btn-help").addEventListener("click", () => { $("help").hidden = !$("help").hidden; });
  $("btn-settings").addEventListener("click", openSettings);
  for (const id of ["btn-close-settings", "btn-cancel", "scrim"]) $(id).addEventListener("click", cancelSettings);
  $("btn-save").addEventListener("click", saveSettings);
  $("btn-reconnect").addEventListener("click", () => bridge.reconnect());
  $("btn-edit-json").addEventListener("click", () => bridge.editConfigJson());
  $("set-batch").addEventListener("click", () => {
    if (!state.locked) $("set-batch").classList.toggle("on");
  });
  $("auto").addEventListener("click", () => {
    if (state.locked) return;
    const on = !$("batch-sw").classList.contains("on");
    $("batch-sw").classList.toggle("on", on);
    bridge.saveSettings(JSON.stringify({ batch: on }));
  });
  const input = $("input");
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  });
  $("send").addEventListener("click", submit);
  document.querySelectorAll(".suggestion").forEach((s) => s.addEventListener("click", () => {
    input.value = s.dataset.text;
    autosize();
    input.focus();
  }));
  setInterval(tick, 1000);
}

const handlers = {
  addUser: (p) => append(userNode(p.text)),
  addNote: (p) => append(noteNode(p.text)),
  renderTurn,
  setBusy,
  setStatus,
  setSettings,
  setTheme,
  reset: () => { col().textContent = ""; updateEmpty(); },
  replay,
};

function boot() {
  wire();
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bridge.push.connect((name, payload) => {
      const handler = handlers[name];
      if (handler) handler(JSON.parse(payload));
    });
    bridge.ready();
  });
}

document.addEventListener("DOMContentLoaded", boot);
```

- [ ] **Step 9: Run the loader tests (offscreen)**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_web_view.py tests/test_page.py`
Expected: `3 passed, 15 skipped` (the page tests skip offscreen).

- [ ] **Step 10: Run the page tests (real display)**

Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web`
Expected: 15 passed. If `test_page_calls_ready_and_starts_empty` times out waiting for `ready_calls`, the channel never connected: check the browser console by temporarily connecting `view.page().javaScriptConsoleMessage` in a scratch script. Do not change the tests to hide it.

- [ ] **Step 11: Run the whole suite offscreen**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all pass, the `web` tests skipped.

- [ ] **Step 12: Commit**

```bash
git add salome_agent_gui/web/index.html salome_agent_gui/web/app.css salome_agent_gui/web/app.js salome_agent_gui/web_view.py tools/__init__.py tools/page_fixtures.py tests/test_web_view.py tests/test_page.py
git commit -m "feat: chat page (HTML/CSS/JS) drawn from the bridge's pushes, and its web view loader"
```

---

### Task 7: Window shell, app start-up and cleanup

**Implementer: sonnet.**

**Files:**
- Modify (rewrite): `salome_agent_gui/main_window.py`
- Modify: `salome_agent_gui/app.py`
- Modify: `salome_agent_gui/timeline.py` (remove the markdown renderers)
- Modify: `tests/test_timeline.py` (remove renderer tests)
- Delete: `salome_agent_gui/chat_view.py`, `tests/test_chat_view.py`
- Modify (rewrite): `tests/test_main_window.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `Bridge` (Task 5): constructor, `start()`, `request_close()`, `close_ready`, `ready()`, `probe()`, `send()`, `gate()`, `push`; `web_view.create(parent, bridge)` (Task 6); `dialogs.edit_plan(parent, plan)`, `dialogs.edit_config(parent, path)` (unchanged).
- Produces: `MainWindow(config_path, *, open_fn=None, probe_fn=None, edit_plan=None, parent_pid=None, view_factory=None, system_dark=None)` with attributes `bridge`, `view`, `_parent_watch`, and `_palette_is_dark() -> bool`.

- [ ] **Step 1: Rewrite `tests/test_main_window.py`**

```python
import json
import os
import subprocess
import sys
import threading

import pytest
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QLabel

from salome_agent_gui.main_window import MainWindow
from tests.fakes import opener, write_cfg

GUI = {"mode": "gui", "port": 4242}


@pytest.fixture
def cfg_path(tmp_path):
    return write_cfg(tmp_path)


def make(qtbot, cfg_path, rec, **kw):
    made = {}

    def factory(parent, bridge):
        made["bridge"] = bridge
        return QLabel("page", parent)

    w = MainWindow(cfg_path, open_fn=opener(rec), probe_fn=lambda: GUI, view_factory=factory,
                   **kw)
    qtbot.addWidget(w)
    return w, made


def test_window_hosts_the_factory_view_and_its_bridge(qtbot, cfg_path):
    w, made = make(qtbot, cfg_path, {})
    assert isinstance(w.centralWidget(), QLabel)
    assert made["bridge"] is w.bridge
    assert w.bridge.connected is True            # start() probed once


def test_close_when_idle_closes_immediately(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {})
    w.show()
    w.close()
    assert not w.isVisible()


def test_close_during_a_turn_waits_for_the_worker_then_closes(qtbot, cfg_path):
    rec = {}
    w, _ = make(qtbot, cfg_path, rec)
    w.show()
    b = w.bridge
    pushes = []
    b.push.connect(lambda name, payload: pushes.append((name, json.loads(payload))))
    b.ready()
    b.send("make a box")
    qtbot.waitUntil(lambda: any(n == "renderTurn" and p["gate"] for n, p in pushes),
                    timeout=3000)
    gate = [p for n, p in pushes if n == "renderTurn" and p["gate"]][-1]["gate"]
    b.gate(gate["id"], "approve", "")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    rec["conv"].release = threading.Event()
    b.send("slow")
    qtbot.waitUntil(lambda: "slow" in rec.get("turns", []), timeout=3000)
    w.close()
    assert w.isVisible() and b.close_pending
    rec["conv"].release.set()
    qtbot.waitUntil(lambda: not w.isVisible(), timeout=5000)
    assert rec["closed"] == 1


def test_check_parent_closes_when_parent_is_gone(qtbot, cfg_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    w, _ = make(qtbot, cfg_path, {}, parent_pid=proc.pid)
    w.show()
    w._check_parent()
    assert not w.isVisible()


def test_check_parent_leaves_window_open_when_parent_is_alive(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {}, parent_pid=os.getpid())
    w.show()
    w._check_parent()
    assert w.isVisible()


def test_no_parent_pid_starts_no_watch_timer(qtbot, cfg_path, monkeypatch):
    monkeypatch.delenv("SALOME_AGENT_GUI_PARENT_PID", raising=False)
    w, _ = make(qtbot, cfg_path, {})
    assert w._parent_watch is None


def test_palette_decides_whether_the_system_theme_is_dark(qtbot, cfg_path):
    w, _ = make(qtbot, cfg_path, {})
    pal = w.palette()
    pal.setColor(QPalette.Window, QColor(20, 20, 20))
    w.setPalette(pal)
    assert w._palette_is_dark() is True
    pal.setColor(QPalette.Window, QColor(240, 240, 240))
    w.setPalette(pal)
    assert w._palette_is_dark() is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_main_window.py`
Expected: FAIL, `TypeError: MainWindow.__init__() got an unexpected keyword argument 'view_factory'`.

- [ ] **Step 3: Rewrite `salome_agent_gui/main_window.py`**

```python
import os
from pathlib import Path

from PyQt5.QtCore import QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QPalette
from PyQt5.QtWidgets import QMainWindow

from salome_agent_gui import dialogs, web_view
from salome_agent_gui.bridge import Bridge


def _open_file(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class MainWindow(QMainWindow):
    """Thin shell: the chat is a web page; the Bridge holds the state."""

    def __init__(self, config_path: Path, *, open_fn=None, probe_fn=None, edit_plan=None,
                 parent_pid: int | None = None, view_factory=None, system_dark=None):
        super().__init__()
        self.setWindowTitle("SALOME Agent")
        self.resize(900, 780)
        self._closing = False
        self.bridge = Bridge(config_path, open_fn=open_fn, probe_fn=probe_fn,
                             edit_plan=edit_plan or dialogs.edit_plan,
                             edit_config=dialogs.edit_config, open_file=_open_file,
                             system_dark=system_dark or self._palette_is_dark,
                             dialog_parent=self, parent=self)
        self.bridge.close_ready.connect(self._close_now)
        self.view = (view_factory or web_view.create)(self, self.bridge)
        self.setCentralWidget(self.view)
        self.bridge.start()

        if parent_pid is None:
            try:
                parent_pid = int(os.environ["SALOME_AGENT_GUI_PARENT_PID"])
            except (KeyError, ValueError):
                parent_pid = None
        self._parent_pid = parent_pid
        self._parent_watch = None
        if self._parent_pid is not None:
            self._parent_watch = QTimer(self)
            self._parent_watch.setInterval(2000)
            self._parent_watch.timeout.connect(self._check_parent)
            self._parent_watch.start()

    def _palette_is_dark(self) -> bool:
        return self.palette().color(QPalette.Window).lightness() < 128

    def _check_parent(self):
        try:
            os.kill(self._parent_pid, 0)
        except ProcessLookupError:
            pass
        except PermissionError:
            return
        else:
            return
        self._parent_watch.stop()
        self.close()

    def _close_now(self):
        self._closing = True
        self.close()

    def closeEvent(self, e):
        if self._closing or self.bridge.request_close():
            super().closeEvent(e)
            return
        e.ignore()
```

- [ ] **Step 4: Update `salome_agent_gui/app.py`**

```python
import sys


def main(argv=None) -> int:
    from PyQt5.QtCore import QCoreApplication, Qt

    # Qt WebEngine must be imported, and GL context sharing switched on,
    # before the QApplication exists.
    try:
        import PyQt5.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        pass                     # web_view.create shows the fallback panel
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    from PyQt5.QtWidgets import QApplication

    from salome_agent.logs import setup_logging
    from salome_agent_gui import config_store
    from salome_agent_gui.main_window import MainWindow

    setup_logging(0)
    path = config_store.ensure_user_config()
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SALOME Agent")
    window = MainWindow(path)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Remove the markdown renderers**

In `salome_agent_gui/timeline.py` delete: `ICON`, `STATUS_LABEL`, the `Note` dataclass, `_escape`, `_code`, `render_user`, `render_note`, `_file_link`, `_links_and_usage`, `render_run`, and the `from pathlib import Path` import if nothing else uses it. Keep `_edit_line` and `RunView.edits` (the strings stay as a readable log; `edit_ops` is what the page uses).

Delete the files:

```bash
git rm salome_agent_gui/chat_view.py tests/test_chat_view.py
```

In `tests/test_timeline.py`:
- change the first import line to `from salome_agent_gui.timeline import RunView`;
- delete these tests: `test_report_finishes_and_renders_links_and_usage`, `test_plan_gate_renders_three_actions_and_clears`, `test_retry_gate_renders_error_and_actions`, `test_fatal_and_aborted_render`, `test_fatal_run_that_finishes_skips_done_but_keeps_report_link`, `test_fatal_run_with_no_paths_emits_no_empty_links_line`, `test_user_text_cannot_inject_gate_links`, `test_object_name_with_backtick_cannot_break_code_span`, `test_turn_statuses_have_their_own_labels`, `test_turn_outcome_replaces_aborted_and_fatal_lines`, `test_first_turn_keeps_its_object_list`, `test_note_escapes_markdown`;
- in `test_amend_turn_renders_edits_and_outcome`, delete the lines from `md = render_run(v)` to the end of the test (the `v.edits` assertion stays);
- replace `test_report_usage_is_a_snapshot_not_the_live_counter` with:

```python
def test_report_usage_is_a_snapshot_not_the_live_counter():
    usage = {"calls": 8}
    v = RunView()
    v.apply(ev("report", result_py="/w/r1/result.py", report_md="/w/r1/report.md", text="",
               usage=usage))
    usage["calls"] = 17
    assert v.to_view_model(0)["usage"] == {"calls": 8}
```

- [ ] **Step 6: Check nothing still uses the old code**

Run: `grep -rn "render_run\|render_note\|render_user\|ChatView\|chat_view\|Note(" salome_agent_gui tests tools`
Expected: no output.

- [ ] **Step 7: Update `README.md`** — replace its second paragraph (the one starting "Tools > Plugins > SALOME Agent") with:

```markdown
Tools > Plugins > SALOME Agent starts the in-GUI agent server and opens the chat, a web page
drawn in Qt WebEngine: the first message builds a model (plan -> stages -> result.py),
follow-ups change it, with undo / redo / rebuild and a New conversation button. Settings live
behind the gear icon and are saved in `~/.config/salome/salome-agent.json`.
```

and replace the "Dev:" paragraph with:

```markdown
Dev: `python3 -m venv .venv && .venv/bin/pip install -e ./salome-agent -e '.[dev]'`,
then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`. The page tests need a display
(Qt WebEngine does not run offscreen): `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -m web`.
`tools/render_states.py OUTDIR` renders the page's states to PNG for review.
```

- [ ] **Step 8: Run everything**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`
Expected: all pass, `web` tests skipped.
Run: `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -q -m web`
Expected: 15 passed.

- [ ] **Step 9: Smoke-start the real window against no server**

Run: `QT_QPA_PLATFORM=xcb timeout 15 .venv/bin/python -m salome_agent_gui.app; echo "exit=$?"`
Expected: a window titled "SALOME Agent" shows the welcome screen with a red "Not connected" pill and the banner; it is killed by `timeout` (exit 124) with no Python traceback in the output.

- [ ] **Step 10: Commit**

```bash
git add salome_agent_gui/main_window.py salome_agent_gui/app.py salome_agent_gui/timeline.py tests/test_timeline.py tests/test_main_window.py README.md
git commit -m "feat: the chat window is a thin shell around the web page; the markdown transcript is gone"
```

(`git rm` in Step 5 already staged the two deletions.)

---

### Task 8: Render-states tool

**Implementer: haiku. Guard: `tools/render_states.py` must match the block below exactly.**

**Files:**
- Create: `tools/render_states.py`

**Interfaces:**
- Consumes: `web_view.create` (Task 6); `tools.page_fixtures.FakeBridge`, `STATES`, `resolve` (Task 6).
- Produces: a script writing `<state>-<theme>.png` for every entry of `STATES`, in light and dark.

- [ ] **Step 1: Create `tools/render_states.py`**

```python
"""Render the chat page's fixture states to PNG, light and dark, for review
without SALOME. Needs a display:
    QT_QPA_PLATFORM=xcb .venv/bin/python tools/render_states.py OUTDIR"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv) -> int:
    from PyQt5.QtCore import QCoreApplication, Qt, QTimer
    import PyQt5.QtWebEngineWidgets  # noqa: F401
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from PyQt5.QtWidgets import QApplication

    from salome_agent_gui import web_view
    from tools.page_fixtures import STATES, FakeBridge, resolve

    out = Path(argv[1] if len(argv) > 1 else "render-states")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(argv[:1])
    fake = FakeBridge()
    view = web_view.create(None, fake)
    view.resize(900, 760)
    view.show()
    jobs = [(name, theme) for name in STATES for theme in ("light", "dark")]

    def shoot(path):
        view.grab().save(str(path))
        print(path)
        step()

    def step():
        if not jobs:
            app.quit()
            return
        name, theme = jobs.pop(0)
        view.page().runJavaScript("document.body.classList.remove('settings-open')")
        fake.emit("reset", {})
        fake.emit("setTheme", {"theme": theme})
        for push_name, payload in STATES[name]:
            if push_name == "__js__":
                view.page().runJavaScript(payload)
            else:
                fake.emit(push_name, resolve(payload))
        QTimer.singleShot(900, lambda: shoot(out / f"{name}-{theme}.png"))

    def wait_ready():
        if fake.ready_calls:
            step()
        else:
            QTimer.singleShot(100, wait_ready)

    wait_ready()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 2: Run it**

Run: `QT_QPA_PLATFORM=xcb .venv/bin/python tools/render_states.py /tmp/render-states && ls /tmp/render-states | wc -l`
Expected: 14 paths printed (7 states × 2 themes), then `14`.

- [ ] **Step 3: Check the files are real images**

Run: `.venv/bin/python -c "import sys; from pathlib import Path; bad=[p for p in Path('/tmp/render-states').glob('*.png') if p.stat().st_size < 20000]; print(bad); sys.exit(1 if bad else 0)"`
Expected: `[]`.

- [ ] **Step 4: Commit**

```bash
git add tools/render_states.py
git commit -m "chore: tools/render_states.py renders the chat page states to PNG"
```

---

### Task 9: Live check in SALOME (controller, not a subagent)

This task needs SAT, the SALOME master build and the user. The controller runs it after the whole-branch review. Paths come from the environment: `$SALOME_ROOT` is the SALOME master build directory; never write it into the repo.

- [ ] **Step 1: Review the rendered states** — run Task 8's tool into the session scratchpad and look at all 14 PNGs against the spec's screenshots. Fix differences before going on.

- [ ] **Step 2: Rebuild the SAT product from this branch**

Check which source the `salome_agent_gui` SAT product builds from (its pyconf in the SAT_SALOME project) and point it at `feat/modern-chat-ui` the way that pyconf expects. Then run `sat compile <application> --products salome_agent_gui` and check, in the product's install venv, that `python -c "import PyQt5.QtWebEngineWidgets"` works. Do not hand-patch the install venv.

- [ ] **Step 3: Launch SALOME and run the car request end to end**

Launch with `QT_QPA_PLATFORM=xcb ./salome` from `$SALOME_ROOT`, open Tools > Plugins > SALOME Agent. Take a screenshot at each point:
1. Welcome screen, connected pill.
2. "construct a small car with 4 torus as its wheels. make the car red and the wheels black": plan card with the GEOM module icon, Approve & build.
3. Live stages with timers, then the result: object list, `result.py` / `report.md` chips (click both: they open), usage line.
4. Follow-up "make the wheels bigger": the Changes card.
5. Undo, then Redo (notes appear).
6. Send a new request and press Stop during it.
7. Settings: change the theme to Dark, Save; close and reopen the window; the theme and the model are still set.
8. Stop the agent server; Reconnect shows the red pill and banner.
9. Start a request and close the window during it: the window closes once the turn stops, without freezing.

- [ ] **Step 4: User click-through** — hand over to the user for their own run before merging. SALOME 9.16 is not covered; say so in the report.
