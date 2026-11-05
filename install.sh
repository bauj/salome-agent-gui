#!/bin/bash
# Installs salome-agent-gui for an existing SALOME, without SAT.
# Usage: ./install.sh <SALOME directory> [install directory]
# Set PYTHON to choose the Python 3.10+ that runs the chat window.
set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }

[ $# -ge 1 ] && [ $# -le 2 ] || die "usage: $0 <SALOME directory> [install directory]"
SALOME_DIR=$(cd "$1" 2>/dev/null && pwd) || die "no such directory: $1"
PREFIX=${2:-$HOME/.local/share/salome-agent-gui}
PYTHON=${PYTHON:-python3}
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

[ -x "$SALOME_DIR/salome" ] || die "$SALOME_DIR has no salome launcher"
command -v "$PYTHON" >/dev/null || die "$PYTHON not found; set PYTHON to a Python 3.10+"
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "$PYTHON is older than 3.10; set PYTHON to a Python 3.10+"

echo "== Checking the Python SALOME runs on"
# salome shell splits its command on spaces, so no python3 -c here.
SALOME_PY=$("$SALOME_DIR/salome" shell -- python3 -V 2>/dev/null \
    | sed -n 's/^Python \([0-9]*\.[0-9]*\).*/\1/p' | tail -n 1) || true
[ -n "$SALOME_PY" ] || die "could not run Python through $SALOME_DIR/salome"
[ "${SALOME_PY%%.*}" -eq 3 ] && [ "${SALOME_PY##*.}" -ge 10 ] \
    || die "this SALOME runs on Python $SALOME_PY; the agent server inside it needs 3.10+"
echo "   Python $SALOME_PY"

if [ ! -f "$SRC/salome-agent/pyproject.toml" ]; then
    echo "== Fetching the salome-agent submodule"
    git -C "$SRC" submodule update --init
fi

echo "== Installing the chat window in $PREFIX"
echo "   Takes about 500 MB, mostly Qt WebEngine (Chromium); the download can take a few minutes."
"$PYTHON" -m venv "$PREFIX"
# pip builds in-tree: build from a copy so the checkout stays clean.
BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
tar -C "$SRC" --exclude=.git --exclude=.venv --exclude=./build \
    --exclude=./salome-agent/build --exclude='*.egg-info' -cf - . | tar -C "$BUILD" -xf -
(cd "$BUILD" && "$PREFIX/bin/pip" install -q -c constraints.txt ./salome-agent .)
# -I: python -c would otherwise import the checkout when run from inside it.
"$PREFIX/bin/python" -I -c \
    'import salome_agent_gui.app; from salome_agent.graph import build_graph; build_graph(batch=True)' \
    || die "the installed salome-agent-gui does not import"

SITE=$("$PREFIX/bin/python" -I -c 'import salome_agent_gui, os; print(os.path.dirname(salome_agent_gui.__file__))')
cp "$SRC/salome-agent/config.example.json" "$SITE/config.example.json"
install -m 755 "$SRC/salome-agent-gui.sh" "$PREFIX/bin/salome-agent-gui.sh"

echo "== Installing the SALOME plugin"
PLUGIN=$PREFIX/share/salome/plugins/salome_agent_gui
rm -rf "$PLUGIN"
mkdir -p "$PLUGIN"
cp "$SRC/salome_plugins.py" "$SRC/sagui_launcher.py" "$PLUGIN/"
cp -r "$SRC/salome-agent/agent_server" "$SRC/salome-agent/executor" "$PLUGIN/"
find "$PLUGIN" -name __pycache__ -prune -exec rm -rf {} +

LAUNCHER=$PREFIX/salome-with-agent
cat > "$LAUNCHER" <<EOF
#!/bin/bash
export SALOME_AGENT_GUI_ROOT_DIR="$PREFIX"
export SALOME_AGENT_GUI="$PREFIX/bin/salome-agent-gui.sh"
exec "$SALOME_DIR/salome" "\$@"
EOF
chmod 755 "$LAUNCHER"

cat <<EOF

Done. Start SALOME with:
    $LAUNCHER
then open Tools > Plugins > SALOME Agent. In the chat window, the gear icon asks
for your LLM endpoint, API key and model.
EOF
