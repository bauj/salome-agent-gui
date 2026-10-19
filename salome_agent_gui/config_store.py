import json
import os
import tempfile
from pathlib import Path

USER_CONFIG = Path.home() / ".config" / "salome" / "salome-agent.json"
KEY_FIELDS = ("base_url", "model", "api_key", "ssl_cert_file")


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
VERIFY_CADENCE = ("none", "final", "strict")
PLAN_DETAIL = ("coarse", "balanced", "fine")
# policy int knobs: (default, min, max)
POLICY_INTS = {"tool_iteration_cap": (12, 1, 60)}
# llm int knobs the Advanced fold edits: (default, min, max)
LLM_INTS = {"reasoning_budget": (20000, 0, 200000), "vision_fix_retries": (2, 0, 5),
            "timeout": (120, 10, 1800)}
# llm.modules.<m> keys a module row edits; the others are kept as they are
ROW_KEYS = ("model", "base_url", "api_key", "ssl_cert_file")
# engine keys left to Edit JSON (tests/test_config_store.py checks the engine's list)
JSON_ONLY = {"extra_headers", "extra_body", "module_extra_body", "json_retries", "max_retries",
             "temperature", "carry_reasoning", "loop_retries", "text_tool_calls"}
MODULE_JSON_ONLY = {"extra_headers", "extra_body", "temperature", "timeout"}


def _section(data, name: str) -> dict:
    value = data.get(name) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def _verbose(value) -> int:
    try:
        return max(0, min(2, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamped(section: dict, key: str, table: dict) -> int:
    default, lo, hi = table[key]
    value = _int(section.get(key))
    return default if value is None else max(lo, min(hi, value))


def _modules(value) -> dict:
    """llm.modules / gui.parked_modules as {name: dict}; anything else dropped."""
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, dict)}


def _merge(into: dict, src: dict) -> dict:
    for name, d in src.items():
        into[name] = {**into.get(name, {}), **d}
    return into


def _save_modules(data: dict, shared: bool, rows) -> None:
    """The rows go to llm.modules, or to gui.parked_modules while every module
    uses the shared model (the engine never reads `gui`). Keys the form does not
    show are kept."""
    llm, gui = data.setdefault("llm", {}), data.setdefault("gui", {})
    store = _merge(_modules(gui.get("parked_modules")), _modules(llm.get("modules")))
    edited = set()
    for name, row in (rows if isinstance(rows, dict) else {}).items():
        if not isinstance(row, dict):
            continue
        old = store.get(name, {})
        d = dict(old)
        for key in ROW_KEYS:
            value = str(row.get(key) or "").strip()
            if value:
                d[key] = value
            else:
                d.pop(key, None)
        if any(d.get(k) != old.get(k) for k in ("base_url", "api_key")):
            edited.add(name)
        if d:
            store[name] = d
        else:
            store.pop(name, None)
    if not shared:
        # another host never gets the shared key (salome_agent.llm._build_endpoint)
        shared_url = str(llm.get("base_url") or "").rstrip("/")
        # only endpoints edited here: a keyless one set in JSON (a local
        # gateway) must not block every later save
        for name in edited & set(store):
            d = store[name]
            url = str(d.get("base_url") or "").rstrip("/")
            if url and url != shared_url and not d.get("api_key"):
                raise ValueError(f"{name}: a different endpoint needs its own API key")
    llm.pop("modules", None)
    gui.pop("parked_modules", None)
    if store:
        if shared:
            gui["parked_modules"] = store
        else:
            llm["modules"] = store


def model_label(settings: dict) -> tuple[str, str]:
    """The model part of the header, and a tooltip listing each override."""
    shared = settings.get("model") or "?"
    if settings.get("shared_model", True):
        return shared, ""
    over = [(name, row.get("model") or shared)
            for name, row in (settings.get("modules") or {}).items() if any(row.values())]
    if not over:
        return shared, ""
    tip = "\n".join(f"{name}: {model}" for name, model in over)
    if len(over) == 1:
        return f"{shared} · {over[0][0]}: {over[0][1]}", tip
    return f"{shared} · +{len(over)} overrides", tip


def read_settings(path: Path) -> dict:
    """Never raises: a missing or broken file reads as defaults, and the
    conversation start (config_store.load) reports the real error."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        data = {}
    llm, policy, gui = _section(data, "llm"), _section(data, "policy"), _section(data, "gui")
    active = _modules(llm.get("modules"))
    shown = _merge(_modules(gui.get("parked_modules")), active)
    return {
        **{k: llm.get(k, "") or "" for k in KEY_FIELDS},
        "on_stage_failure": policy.get("on_stage_failure") if policy.get("on_stage_failure") in ON_FAILURE else "abort",
        "tool_selection": policy.get("tool_selection") if policy.get("tool_selection") in TOOL_SELECTION else "hints",
        "batch": bool(gui.get("batch", False)),
        "verbose": _verbose(gui.get("verbose")),
        "theme": gui.get("theme") if gui.get("theme") in THEMES else "system",
        "show_reasoning": bool(gui.get("show_reasoning", False)),
        "verify_cadence": policy.get("verify_cadence") if policy.get("verify_cadence") in VERIFY_CADENCE else "final",
        "plan_detail": policy.get("plan_detail") if policy.get("plan_detail") in PLAN_DETAIL else "balanced",
        **{k: _clamped(policy, k, POLICY_INTS) for k in POLICY_INTS},
        "shared_model": not active,
        "modules": {name: {k: str(d.get(k) or "") for k in ROW_KEYS} for name, d in shown.items()},
        "modules_json_only": {name: sorted(set(d) - set(ROW_KEYS))
                              for name, d in shown.items() if set(d) - set(ROW_KEYS)},
        **{k: _clamped(llm, k, LLM_INTS) for k in LLM_INTS},
    }


def save_settings(path: Path, fields: dict, *, run_options: bool = True) -> None:
    """Key fields and theme always; run options (policy, gui batch/verbose, models,
    advanced llm knobs) only when `run_options` — they are fixed while a
    conversation is open."""
    data = json.loads(Path(path).read_text())
    data.setdefault("llm", {}).update({k: fields[k] for k in KEY_FIELDS if k in fields})
    gui = data.setdefault("gui", {})
    if fields.get("theme") in THEMES:
        gui["theme"] = fields["theme"]
    if "show_reasoning" in fields:
        gui["show_reasoning"] = bool(fields["show_reasoning"])
    if run_options:
        policy = data.setdefault("policy", {})
        if fields.get("on_stage_failure") in ON_FAILURE:
            policy["on_stage_failure"] = fields["on_stage_failure"]
        if fields.get("tool_selection") in TOOL_SELECTION:
            policy["tool_selection"] = fields["tool_selection"]
        if fields.get("verify_cadence") in VERIFY_CADENCE:
            policy["verify_cadence"] = fields["verify_cadence"]
        if fields.get("plan_detail") in PLAN_DETAIL:
            policy["plan_detail"] = fields["plan_detail"]
        for key, (_, lo, hi) in POLICY_INTS.items():
            value = _int(fields.get(key))
            if value is not None:
                policy[key] = max(lo, min(hi, value))
        for key, (_, lo, hi) in LLM_INTS.items():
            value = _int(fields.get(key))
            if value is not None:
                data["llm"][key] = max(lo, min(hi, value))
        if "shared_model" in fields:
            _save_modules(data, bool(fields["shared_model"]), fields.get("modules"))
        if "batch" in fields:
            gui["batch"] = bool(fields["batch"])
        if "verbose" in fields:
            gui["verbose"] = max(0, min(2, int(fields["verbose"])))
    _write(Path(path), data)
