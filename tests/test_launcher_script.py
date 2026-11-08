# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import json
import os
import subprocess
from pathlib import Path

import sagui_launcher

SCRIPT = Path(__file__).resolve().parent.parent / "salome-agent-gui.sh"
RECORD = """#!/bin/bash
python3 - "$0" "$@" <<'EOF'
import json, os, sys
keys = ("PYTHONPATH", "PYTHONHOME", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH",
        "TOKENIZERS_PARALLELISM", "FAKE_VENV")
print(json.dumps({"cmd": os.path.basename(sys.argv[1]), "args": sys.argv[2:],
                  "cwd": os.getcwd(), "env": {k: os.environ.get(k) for k in keys}}))
EOF
"""


def fake_prefix(tmp_path):
    """A venv layout: bin/activate and the two console scripts, which print
    what they were started with."""
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    (prefix / "bin" / "activate").write_text(
        f'export FAKE_VENV=1\nexport PATH="{prefix}/bin:$PATH"\n')
    for name in ("salome-agent-gui", "salome-agent-rag-index"):
        p = prefix / "bin" / name
        p.write_text(RECORD)
        p.chmod(0o755)
    return prefix


def run(tmp_path, *args, env=None):
    prefix = fake_prefix(tmp_path)
    start = tmp_path / "where-salome-started"
    start.mkdir(exist_ok=True)
    base = {"HOME": str(tmp_path / "home"), "PATH": os.environ["PATH"],
            "SALOME_AGENT_GUI_ROOT_DIR": str(prefix)}
    out = subprocess.run(["bash", str(SCRIPT), *args], cwd=start, env={**base, **(env or {})},
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_window_starts_in_its_venv_away_from_salome_and_without_its_env(tmp_path):
    got = run(tmp_path, "--x", env={"PYTHONPATH": "/salome/py", "PYTHONHOME": "/salome",
                                    "LD_LIBRARY_PATH": "/salome/lib",
                                    "QT_PLUGIN_PATH": "/salome/qt"})
    assert got["cmd"] == "salome-agent-gui" and got["args"] == ["--x"]
    assert got["cwd"] == str(tmp_path / "home" / ".local" / "share" / "salome-agent" / "rag")
    assert got["env"] == {"PYTHONPATH": None, "PYTHONHOME": None, "LD_LIBRARY_PATH": None,
                          "QT_PLUGIN_PATH": None, "TOKENIZERS_PARALLELISM": "false",
                          "FAKE_VENV": "1"}


def test_script_strips_at_least_what_the_plugin_strips():
    text = SCRIPT.read_text()
    for var in sagui_launcher.STRIP_VARS:
        assert var in text, var


def test_data_dir_and_tokenizers_setting_can_be_overridden(tmp_path):
    got = run(tmp_path, env={"SALOME_AGENT_GUI_DATA_DIR": str(tmp_path / "data"),
                             "TOKENIZERS_PARALLELISM": "true"})
    assert got["cwd"] == str(tmp_path / "data")
    assert got["env"]["TOKENIZERS_PARALLELISM"] == "true"


def test_build_index_runs_the_indexer_with_the_config_made_absolute(tmp_path):
    got = run(tmp_path, "--build-index", "cfg/my.json")
    assert got["cmd"] == "salome-agent-rag-index"
    assert got["args"] == [str(tmp_path / "where-salome-started" / "cfg" / "my.json")]
    assert run(tmp_path, "--build-index", "/abs/c.json")["args"] == ["/abs/c.json"]
    assert run(tmp_path, "--build-index")["args"] == []
