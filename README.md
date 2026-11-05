# salome-agent-gui

> **Not part of SALOME yet.** For now this plugin is installed separately (see [Install](#install)).
> It will probably ship directly in the next SALOME version.

**Chat with SALOME and watch your model take shape!** Describe what you want in plain words, or
drop in a picture of it, and [salome-agent](salome-agent/) builds it for you, right inside SALOME.

<p align="center">
  <a href="https://www.youtube.com/watch?v=iFKYA-E-_0o&t=31s">
    <img src="https://img.youtube.com/vi/iFKYA-E-_0o/hqdefault.jpg" alt="Présentation de SALOME Agent (video, in French)">
  </a>
  <br>
  <em>Click to watch the presentation on YouTube (in French).</em>
</p>

To get going, open **Tools > Plugins > SALOME Agent**: this starts the agent server inside the
SALOME GUI and opens the chat. Your first message builds a model (plan -> stages -> `result.py`),
and follow-up messages change it. The objects appear in the Object Browser and the 3D viewer as
they are built, prefixed `sa_<run_id>_`, and you keep a script that rebuilds it all.

## What it can do

<p align="center">
  <img src="docs/salome-agent-gui.png" alt="SALOME with a meshed plate in the 3D viewer, next to the SALOME Agent chat window">
  <br>
  <em>A plate built in SHAPER and meshed in SMESH, then changed with a follow-up message in the chat.</em>
</p>

SALOME covers the whole simulation workflow; the agent handles **geometry and meshing** today.
It works through three SALOME modules, using each one's own tools:

| Module | Used for | What the agent can do |
|---|---|---|
| **SHAPER** (default for geometry) | Parametric CAD | Constrained sketches; extrude, revolve, pipe, loft, filling; primitives; fuse, cut, common, partition, split; fillets and chamfers; moves, mirrors, patterns and alignment; groups |
| **GEOM** (when you ask for it by name) | CAD | Primitives, wires and faces; prism, revolution, pipe, thick solids, filling; booleans; fillets and chamfers; moves, mirrors, patterns and alignment |
| **SMESH** | Meshing | Tetrahedra, triangles, structured and body-fitted hexahedra, prisms; local sizes, viscous layers; groups from geometry; quality checks, quadratic elements; export to MED, UNV, STL (faces only) or CGNS |

A single request can cross modules, for example build a part in SHAPER and then mesh it in SMESH.

**From a request to a model**

- **Describe it in words or pictures.** Attach drawings, sketches or photos (up to 10 images); this
  needs a vision-capable model.
- **Review the plan first.** The agent splits the job into stages and waits for your approval,
  or runs straight through in batch mode.
- **Each stage is checked as it goes.** The agent measures what it built, and a stage that fails
  stops and lets you give a hint, skip it or abort.
- **Keep talking to refine it.** "Make the roof taller" changes only that object and what depends
  on it, keeping the same names. Undo, redo and rebuild are one click away.

**What you get**

- The objects, live in your study: the Object Browser and the 3D viewer update as they are built.
- `result.py`, a standalone script that rebuilds everything in SALOME without the agent.
- `report.md`, a record of the run.

**Bring your own model.** It works with any OpenAI-compatible endpoint, local or hosted, and you
can choose a different model per module.

**Not there yet:** the agent does not set up or run solvers, or post-process results. Always
check what it builds: quality depends on the model you use, especially when reading images.

## Chat window

- **Images:** use the paperclip, drag and drop, or paste. A *Reading image* card shows the vision
  step live above the plan.
- **Plan:** *Approve & build* or *Edit plan* before anything is built.
- **Reasoning:** a settings switch shows the model's reasoning live under each stage and turn.
- **Stop** ends the turn in progress; the run still writes its `report.md`.
- **Result line:** each turn ends with a summary and any warnings: a value you gave kept against
  a check (`request_conflict`), or a stage accepted while missing a check.
- **Rebuild** replays the whole study from the model when it went out of sync.

## Settings

The gear icon opens the settings drawer: endpoint, API key, model and CA certificate file,
a model per engine module, plan detail, self-check, retries, the tool-call cap, batch mode and
theme. Every option explains itself in a tooltip; the rarer `llm` knobs are edited as JSON.
They are saved in the salome-agent config format (see salome-agent's README for each key) in
`~/.config/salome/salome-agent.json`. **Load config** switches to another config file; the
choice is remembered for the next start in `~/.config/salome/salome-agent-gui.json`.

## Install

Two ways, both tested on the SALOME 9.16.0 Fedora 44 package. You need a SALOME that runs on
Python 3.10 or newer, internet access for GitHub and PyPI, and an OpenAI-compatible LLM endpoint.
Python dependencies are pinned by `constraints.txt`.

Either way, the install takes about 500 MB, most of it Qt and Chromium: the chat window is a
web page drawn in Qt WebEngine, and SALOME does not provide WebEngine, so a full copy is embedded.

### With the install script

Use this if you have already unpacked a SALOME package and do not want to use SAT. You also
need a Python 3.10+ on your system to run the chat window; set `PYTHON` to use a specific one.

**1. Find your SALOME directory.** It is the directory you unpacked the SALOME package into,
the one holding the `salome` launcher you normally start SALOME with:

```
~/SALOME-9.16.0-native-FD44-SRC/
├── salome
├── env_launch.sh
├── BINARIES-FD44/
└── ...
```

**2. Install**, giving that directory:

```bash
git clone --recursive https://github.com/bauj/salome-agent-gui.git
cd salome-agent-gui
./install.sh ~/SALOME-9.16.0-native-FD44-SRC
```

Everything goes in `~/.local/share/salome-agent-gui` (give another directory as a second
argument). Nothing is written in your SALOME directory.

**3. Start SALOME through the launcher the install created:**

```bash
~/.local/share/salome-agent-gui/salome-with-agent
```

Use this launcher every time: your usual `salome` still works, but does not show the plugin.

To update: `git pull`, `git submodule update --init`, then run `install.sh` again.
To uninstall: delete `~/.local/share/salome-agent-gui`.

### With SAT

For a package that includes SAT (`-SRC` in its name). This adds `salome_agent_gui` to the
package as a product, using the [sat_salome fork](https://github.com/bauj/sat_salome/tree/feat/salome-agent-gui).

```bash
tar xf SALOME-9.16.0-native-FD44-SRC.tar.gz
mv SALOME-9.16.0-native-FD44-SRC SALOME-9.16.0-native-FD44   # SAT expects <application>-<distribution>
(cd SALOME-9.16.0-native-FD44 && ./install_bin.sh)

git clone -b feat/salome-agent-gui https://github.com/bauj/sat_salome.git SAT_SALOME
cp -r SALOME-9.16.0-native-FD44/sat SAT
SAT/sat init --reset_projects
SAT/sat init --add_project "$PWD/SAT_SALOME/salome.pyconf"

SAT/sat prepare SALOME-9.16.0-native -p salome_agent_gui
SAT/sat compile SALOME-9.16.0-native -p salome_agent_gui
SAT/sat launcher SALOME-9.16.0-native
SAT/sat environ SALOME-9.16.0-native
SALOME-9.16.0-native-FD44/salome
```

To pick up a pushed change: `git pull` and `git submodule update --init` in the application's
`SOURCES/salome_agent_gui`, then `sat compile <application> -p salome_agent_gui --force` with
SALOME closed, and restart SALOME.

### First start

Open **Tools > Plugins > SALOME Agent**, then set the endpoint, API key and model under the
gear icon in the chat window.

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

## License

GNU Lesser General Public License, version 2.1 or later: see `COPYING`.
