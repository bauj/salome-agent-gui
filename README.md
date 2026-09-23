# salome-agent-gui

SALOME GUI plugin + chat window for [salome-agent](salome-agent/).

Tools > Plugins > SALOME Agent starts the in-GUI agent server and opens the chat, a web page
drawn in Qt WebEngine: the first message builds a model (plan -> stages -> result.py),
follow-ups change it, with undo / redo / rebuild and a New conversation button. Settings live
behind the gear icon and are saved in `~/.config/salome/salome-agent.json`.

Dev: `python3 -m venv .venv && .venv/bin/pip install -e ./salome-agent -e '.[dev]'`,
then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`. The page tests need a display
(Qt WebEngine does not run offscreen): `QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest -m web`.
`tools/render_states.py OUTDIR` renders the page's states to PNG for review.
Installed by SAT (product `salome_agent_gui`).
