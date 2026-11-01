# salome-agent-gui

SALOME GUI plugin + chat window for [salome-agent](salome-agent/).

**Tools > Plugins > SALOME Agent** starts the agent server inside the SALOME GUI and opens the
chat, a web page drawn in Qt WebEngine. The first message builds a model (plan -> stages ->
`result.py`); follow-up messages change it. The objects appear in the Object Browser and the 3D
viewer as they are built, prefixed `sa_<run_id>_`.

## Chat window

- **Images:** attach reference pictures with the paperclip, drag and drop, or paste. A
  *Reading image* card shows the vision step live above the plan.
- **Plan and stage gates:** unless batch mode is on, the *Proposed plan* waits for you
  (*Approve & build*, *Edit plan*, or abort). A failed stage offers *Give a hint*,
  *Skip stage* or *Abort run*.
- **Reasoning:** a settings switch shows the model's reasoning live under each stage and turn.
- **Stop** ends the turn in progress; the run still writes its `report.md`.
- **Result line:** each turn ends with a summary line and, when the engine reports any, its
  warnings under it: a value the user gave kept against a check (`request_conflict`), or a
  stage accepted while missing a check.
- **History:** undo, redo, rebuild (replays the whole study from the model when it went out
  of sync) and *New conversation*.

## Settings

The gear icon opens the settings drawer: endpoint, API key, model and CA certificate file,
a model per engine module, plan detail, self-check, retries, the tool-call cap, batch mode and
theme. Every option explains itself in a tooltip; the rarer `llm` knobs are edited as JSON.
They are saved in the salome-agent config format (see salome-agent's README for each key) in
`~/.config/salome/salome-agent.json`. **Load config** switches to another config file; the
choice is remembered for the next start in `~/.config/salome/salome-agent-gui.json`.

## Install

Installed by SAT (product `salome_agent_gui`), which pins its Python dependencies with
`constraints.txt`. To pick up a pushed change: `git pull` and `git submodule update --init`
in the application's `SOURCES/salome_agent_gui`, then
`sat compile <application> -p salome_agent_gui --force` with SALOME closed, and restart SALOME.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ./salome-agent -e '.[dev]'
QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest   # all tests; needs a display
```

The page tests (marker `web`) need Qt WebEngine and a real display; with
`QT_QPA_PLATFORM=offscreen` or no `DISPLAY` they are skipped and the rest still run.
`tools/render_states.py OUTDIR` renders the page's states to PNG for review.

The `salome-agent` submodule pins the engine; after bumping it, check that
`git ls-tree HEAD salome-agent` shows the intended engine commit.
