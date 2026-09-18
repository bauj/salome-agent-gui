# salome-agent-gui

SALOME GUI plugin + chat window for [salome-agent](salome-agent/).
Tools > Plugins > SALOME Agent starts the in-GUI agent server and opens the chat;
each message is one agent run (plan -> stages -> result.py).

Dev: `python3 -m venv .venv && .venv/bin/pip install -e ./salome-agent -e '.[dev]'`,
then `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest`.
Installed by SAT (product `salome_agent_gui`).
