# salome-agent-gui

SALOME GUI plugin + chat window for [salome-agent](salome-agent/).
Tools > Plugins > SALOME Agent starts the in-GUI agent server and opens the chat;
the first message builds a model (plan -> stages -> result.py), follow-ups change it,
with undo / redo / rebuild and a New conversation button.

Dev: `python3 -m venv .venv && .venv/bin/pip install -e ./salome-agent -e '.[dev]'`,
then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`.
Installed by SAT (product `salome_agent_gui`).
