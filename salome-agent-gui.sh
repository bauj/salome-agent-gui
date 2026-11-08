#!/bin/bash
# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
# Starts the SALOME Agent chat window from its own venv, or builds the
# documentation index for the documentation modes:
#   salome-agent-gui.sh [--mode agent|rag]      the chat window (the SALOME plugin runs this)
#   salome-agent-gui.sh --mcp [--config CONFIG]  SALOME as tools for Claude Desktop / Claude Code
#       (an MCP server on stdin/stdout; SALOME must run the agent server)
#   salome-agent-gui.sh --mcp --http [--port N]  the same, waiting for clients on
#       http://127.0.0.1:N/mcp (Tools > Plugins > AI tools > MCP server)
#   salome-agent-gui.sh --build-index [CONFIG]  index the SALOME documentation (raglib);
#       run it in SALOME's environment so $DOCUMENTATION_ROOT_DIR (or $GEOM_ROOT_DIR etc.) is set, e.g.
#       <SALOME>/salome shell -- <prefix>/bin/salome-agent-gui.sh --build-index
if [ -z "${SALOME_AGENT_GUI_ROOT_DIR}" ]; then
    export SALOME_AGENT_GUI_ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi

# SALOME's Python and Qt must not leak into the venv (sagui_launcher.clean_env
# strips the same for the plugin; `salome shell` sets them again).
unset PYTHONPATH PYTHONHOME QT_PLUGIN_PATH QT_QPA_PLATFORM_PLUGIN_PATH QT_QPA_FONTDIR \
      LD_LIBRARY_PATH

# HuggingFace tokenizers (embeddings, reranker) warn, and can deadlock, when the
# process forks after using them, as the index build does.
export TOKENIZERS_PARALLELISM=${TOKENIZERS_PARALLELISM:-false}

# raglib writes relative to the working directory (the agentic mode creates
# debug_traces/ there): keep that out of wherever SALOME was started.
START_DIR=$PWD
DATA_DIR=${SALOME_AGENT_GUI_DATA_DIR:-$HOME/.local/share/salome-agent/rag}
mkdir -p "$DATA_DIR" && cd "$DATA_DIR" || exit 1

source "${SALOME_AGENT_GUI_ROOT_DIR}/bin/activate"
if [ "$1" = "--mcp" ]; then
    shift
    exec salome-agent-mcp "$@"
fi
if [ "$1" = "--build-index" ]; then
    shift
    # a relative CONFIG is relative to where the command was typed
    if [ -n "$1" ] && [ "${1#/}" = "$1" ]; then
        set -- "$START_DIR/$1" "${@:2}"
    fi
    exec salome-agent-rag-index "$@"
fi
exec salome-agent-gui "$@"
