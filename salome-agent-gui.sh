#!/bin/bash
if [ -z "${SALOME_AGENT_GUI_ROOT_DIR}" ]; then
    export SALOME_AGENT_GUI_ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
fi
source "${SALOME_AGENT_GUI_ROOT_DIR}/bin/activate"
exec salome-agent-gui "$@"
