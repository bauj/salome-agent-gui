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
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
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
