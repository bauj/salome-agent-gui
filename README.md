# salome-agent-gui

> **Not part of SALOME yet.** For now this plugin is installed separately (see [Install](#install)).
> It will probably ship directly in the next SALOME version.

**Chat with SALOME and watch your model take shape!** Describe what you want in plain words, or
drop in a picture of it, and [salome-agent](salome-agent/) builds it for you, right inside SALOME.

[![Présentation de SALOME Agent (video, in French)](https://img.youtube.com/vi/iFKYA-E-_0o/hqdefault.jpg)](https://www.youtube.com/watch?v=iFKYA-E-_0o&t=31s)

*Click to watch the presentation on YouTube (in French).*

To get going, open **Tools > Plugins > SALOME Agent**: this starts the agent server inside the
SALOME GUI and opens the chat. Your first message builds a model (plan -> stages -> `result.py`),
and follow-up messages change it. The objects appear in the Object Browser and the 3D viewer as
they are built, prefixed `sa_<run_id>_`, and you keep a script that rebuilds it all.

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
