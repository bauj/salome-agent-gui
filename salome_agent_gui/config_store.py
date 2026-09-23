import json
import os
import tempfile
from pathlib import Path

USER_CONFIG = Path.home() / ".config" / "salome" / "salome-agent.json"
KEY_FIELDS = ("base_url", "model", "api_key")


def seed_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [here / "config.example.json",                       # SAT install copies it here
            here.parent / "salome-agent" / "config.example.json"]  # dev checkout


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)                        # covers a pre-existing tmp file
    os.replace(tmp, path)


def ensure_user_config(path: Path | None = None, seeds: list[Path] | None = None) -> Path:
    path = Path(path or USER_CONFIG)
    if path.exists():
        return path
    for seed in seeds if seeds is not None else seed_candidates():
        if Path(seed).exists():
            _write(path, json.loads(Path(seed).read_text()))
            return path
    raise FileNotFoundError(f"no config.example.json found to seed {path}")


def read_key_fields(path: Path) -> dict:
    llm = json.loads(Path(path).read_text()).get("llm", {})
    return {k: llm.get(k, "") or "" for k in KEY_FIELDS}


def save_key_fields(path: Path, fields: dict) -> None:
    data = json.loads(Path(path).read_text())
    data.setdefault("llm", {}).update({k: fields[k] for k in KEY_FIELDS if k in fields})
    _write(Path(path), data)


def load(path: Path) -> dict:
    from salome_agent.config import load_config

    return load_config(str(path))


def save_raw(path: Path, text: str) -> None:
    data = json.loads(text)
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "probe.json"
        probe.write_text(json.dumps(data))
        load(probe)
    _write(Path(path), data)


THEMES = ("system", "light", "dark")
ON_FAILURE = ("abort", "continue")
TOOL_SELECTION = ("hints", "all")


def _section(data, name: str) -> dict:
    value = data.get(name) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def _verbose(value) -> int:
    try:
        return max(0, min(2, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def read_settings(path: Path) -> dict:
    """Never raises: a missing or broken file reads as defaults, and the
    conversation start (config_store.load) reports the real error."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        data = {}
    llm, policy, gui = _section(data, "llm"), _section(data, "policy"), _section(data, "gui")
    return {
        **{k: llm.get(k, "") or "" for k in KEY_FIELDS},
        "on_stage_failure": policy.get("on_stage_failure") if policy.get("on_stage_failure") in ON_FAILURE else "abort",
        "tool_selection": policy.get("tool_selection") if policy.get("tool_selection") in TOOL_SELECTION else "hints",
        "batch": bool(gui.get("batch", False)),
        "verbose": _verbose(gui.get("verbose")),
        "theme": gui.get("theme") if gui.get("theme") in THEMES else "system",
    }


def save_settings(path: Path, fields: dict, *, run_options: bool = True) -> None:
    """Key fields and theme always; run options (policy + gui batch/verbose)
    only when `run_options` — they are fixed while a conversation is open."""
    data = json.loads(Path(path).read_text())
    data.setdefault("llm", {}).update({k: fields[k] for k in KEY_FIELDS if k in fields})
    gui = data.setdefault("gui", {})
    if fields.get("theme") in THEMES:
        gui["theme"] = fields["theme"]
    if run_options:
        policy = data.setdefault("policy", {})
        if fields.get("on_stage_failure") in ON_FAILURE:
            policy["on_stage_failure"] = fields["on_stage_failure"]
        if fields.get("tool_selection") in TOOL_SELECTION:
            policy["tool_selection"] = fields["tool_selection"]
        if "batch" in fields:
            gui["batch"] = bool(fields["batch"])
        if "verbose" in fields:
            gui["verbose"] = max(0, min(2, int(fields["verbose"])))
    _write(Path(path), data)
