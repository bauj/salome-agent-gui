#!/bin/bash
# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
# Starts the SALOME Agent chat window from its own venv, or the MCP server:
#   salome-agent-gui.sh                          the chat window (the SALOME plugin runs this)
#   salome-agent-gui.sh --mcp                    SALOME as tools for Claude Desktop / Claude Code
#       (an MCP server on stdin/stdout; SALOME must run the agent server)
#   salome-agent-gui.sh --mcp --http [--port N]  the same, waiting for clients on
#       http://127.0.0.1:N/mcp (Tools > Plugins > AI tools > MCP server)
if [ -z "${SALOME_AGENT_GUI_ROOT_DIR}" ]; then
    export SALOME_AGENT_GUI_ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi

# SALOME's Python and Qt must not leak into the venv (sagui_launcher.clean_env
# strips the same for the plugin; `salome shell` sets them again).
unset PYTHONPATH PYTHONHOME QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QT_QPA_FONTDIR \
      LD_LIBRARY_PATH

source "${SALOME_AGENT_GUI_ROOT_DIR}/bin/activate"
if [ "$1" = "--mcp" ]; then
    shift
    exec salome-agent-mcp "$@"
fi
exec salome-agent-gui "$@"
