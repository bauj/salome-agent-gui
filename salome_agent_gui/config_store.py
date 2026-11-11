# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import base64
import json
import os
import re
import tempfile
from pathlib import Path

from salome_agent_gui import rag_backend, rag_models

USER_CONFIG = Path.home() / ".config" / "salome" / "salome-agent.json"
# which config file the GUI uses and the chat window geometry; kept outside the config
# files it switches between
GUI_STATE = USER_CONFIG.parent / "salome-agent-gui.json"
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


def _read_state(state: Path) -> dict:
    try:
        data = json.loads(state.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update_state(updates: dict, state: Path | None = None) -> None:
    """Merge `updates` into the GUI state file, keeping its other keys."""
    state = Path(state or GUI_STATE)
    data = _read_state(state)
    data.update(updates)
    state.parent.mkdir(parents=True, exist_ok=True)
    tmp = state.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, state)


def remember_config(path: Path, state: Path | None = None) -> None:
    _update_state({"config_path": str(Path(path).resolve())}, state)


def window_geometry(state: Path | None = None) -> bytes | None:
    """The chat window geometry saved at the last close (Qt saveGeometry), or None."""
    value = _read_state(Path(state or GUI_STATE)).get("window_geometry")
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:
        return None


def save_window_geometry(geometry: bytes, state: Path | None = None) -> None:
    _update_state({"window_geometry": base64.b64encode(bytes(geometry)).decode("ascii")},
                  state)


def startup_config(default: Path, state: Path | None = None) -> tuple[Path, str | None]:
    """The last loaded config, or `default` with a note when it is gone."""
    try:
        last = json.loads(Path(state or GUI_STATE).read_text()).get("config_path")
    except (OSError, ValueError, AttributeError):
        return Path(default), None
    if not isinstance(last, str) or not last:
        return Path(default), None
    if Path(last).is_file():
        return Path(last), None
    return Path(default), f"Last loaded config {last} not found, using {default}."


def read_key_fields(path: Path) -> dict:
    llm = json.loads(Path(path).read_text()).get("llm", {})
    return {k: llm.get(k, "") or "" for k in KEY_FIELDS}


def save_key_fields(path: Path, fields: dict) -> None:
    data = json.loads(Path(path).read_text())
    data.setdefault("llm", {}).update({k: fields[k] for k in KEY_FIELDS if k in fields})
    _write(Path(path), data)


def load(path: Path, *, check_rag: bool | None = None) -> dict:
    """The engine's checks, then raglib's on the `rag` section when a
    documentation mode will read it (by default: when gui.mode is one), so a
    bad rag section or a broken raglib never stops the agent mode."""
    from salome_agent.config import load_config

    config = load_config(str(path))
    if check_rag is None:
        gui = config.get("gui") if isinstance(config.get("gui"), dict) else {}
        check_rag = gui.get("mode") in rag_backend.DOC_MODES
    if check_rag:
        rag_backend.check(config, path)
    return config


def save_raw(path: Path, text: str) -> None:
    data = json.loads(text)
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "probe.json"
        probe.write_text(json.dumps(data))
        load(probe)
    _write(Path(path), data)


THEMES = ("system", "light", "dark")
# gui.mode: the SALOME Agent, or a documentation chatbot
MODES = rag_backend.MODES
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


# documentation-mode knobs the form edits, all in rag.chatbot (raglib's schema);
# ints: (default, min, max), defaults are raglib's
RAG_INTS = {"k_standard": (40, 1, 500), "top_n_after_rerank": (15, 1, 200),
            "expansion_char_budget": (60000, 0, 1000000), "max_tokens": (2000, 64, 64000)}
RAG_BOOLS = {"bm25_enabled": True, "title_boost_enabled": True, "hyde_enabled": False}
TEMPERATURE = (0.0, 0.0, 2.0)
# rag.chatbot.agentic, used by the agentic RAG mode only
AGENTIC_INTS = {"max_steps": (20, 1, 100), "max_chars_per_page": (8000, 500, 200000),
                "section_top_n": (5, 1, 50), "section_char_budget": (15000, 1000, 500000)}
# where the reranker block waits while reranking is off (raglib skips `_` keys)
RERANKER_PARKED = "_reranker_off"
DEFAULT_RERANKER = {"model": "answerdotai/answerai-colbert-small-v1", "type": "late_interaction"}


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


def _float(value, table) -> float:
    default, lo, hi = table
    if isinstance(value, bool):
        return default
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


def _rag_options(data: dict) -> dict:
    """The documentation-mode knobs, from rag.chatbot; raglib's defaults when unset."""
    chatbot = _section(_section(data, "rag"), "chatbot")
    agentic = _section(chatbot, "agentic")
    return {
        **{k: _clamped(chatbot, k, RAG_INTS) for k in RAG_INTS},
        **{k: bool(chatbot.get(k, d)) for k, d in RAG_BOOLS.items()},
        "temperature": _float(chatbot.get("temperature"), TEMPERATURE),
        "reranker": bool(chatbot.get("reranker")),
        **{k: _clamped(agentic, k, AGENTIC_INTS) for k in AGENTIC_INTS},
    }


def _default_chatbot() -> dict:
    try:
        chatbot = rag_backend.default_rag().get("chatbot")
    except (OSError, ValueError, KeyError, AttributeError):
        return {}
    return chatbot if isinstance(chatbot, dict) else {}


def _save_rag_options(data: dict, opts: dict) -> None:
    """Into rag.chatbot, keeping every key the form does not show. A config
    without a rag section gets the example's first."""
    if not isinstance(data.get("rag"), dict):
        data["rag"] = rag_backend.default_rag()
    rag = data["rag"]
    if not isinstance(rag.get("chatbot"), dict):
        rag["chatbot"] = _default_chatbot()
    chatbot = rag["chatbot"]
    for key, (_, lo, hi) in RAG_INTS.items():
        value = _int(opts.get(key))
        if value is not None:
            chatbot[key] = max(lo, min(hi, value))
    for key in RAG_BOOLS:
        if isinstance(opts.get(key), bool):
            chatbot[key] = opts[key]
    if "temperature" in opts and not isinstance(opts["temperature"], bool):
        try:
            chatbot["temperature"] = max(TEMPERATURE[1], min(TEMPERATURE[2], float(opts["temperature"])))
        except (TypeError, ValueError):
            pass
    if isinstance(opts.get("reranker"), bool):
        current = chatbot.get("reranker")
        if opts["reranker"] and not current:
            parked = chatbot.pop(RERANKER_PARKED, None)
            chatbot["reranker"] = (parked if isinstance(parked, dict) and parked
                                   else _default_chatbot().get("reranker") or dict(DEFAULT_RERANKER))
        elif not opts["reranker"] and current:
            chatbot[RERANKER_PARKED] = current
            chatbot["reranker"] = None
    if any(_int(opts.get(k)) is not None for k in AGENTIC_INTS):
        if not isinstance(chatbot.get("agentic"), dict):
            default = _default_chatbot().get("agentic")
            chatbot["agentic"] = dict(default) if isinstance(default, dict) else {}
        agentic = chatbot["agentic"]
        for key, (_, lo, hi) in AGENTIC_INTS.items():
            value = _int(opts.get(key))
            if value is not None:
                agentic[key] = max(lo, min(hi, value))


# ---- documentation sources: rag.extraction.modules -----------------------
# a source's name is raglib's module name (metadata, filters); `_` would make it a comment
SOURCE_NAME = re.compile(r"[A-Za-z0-9][\w.+-]*")
SOURCE_PATHS = (("dev", "dev_path"), ("user", "user_path"))


def _citations(value) -> tuple[str, str]:
    """url_for_sources_citation (one URL, or {"dev", "user"}) as (dev, user)."""
    if isinstance(value, dict):
        return str(value.get("dev") or ""), str(value.get("user") or "")
    return (str(value or ""),) * 2


def _path_state(raw: str, base_dir: Path) -> dict:
    """Where a source path points here: ok, missing, or unset (variables not set)."""
    if not raw:
        return {"state": "empty", "resolved": "", "vars": []}
    unset = rag_backend.unset_vars(raw)
    resolved = str(rag_backend._abspath(raw, base_dir))
    if unset:
        return {"state": "unset", "resolved": resolved, "vars": unset}
    return {"state": "ok" if Path(resolved).is_dir() else "missing", "resolved": resolved, "vars": []}


def _doc_sources(data: dict, path) -> list[dict]:
    """rag.extraction.modules as the settings' rows, each path with its state."""
    extraction = _section(_section(data, "rag"), "extraction")
    modules = extraction.get("modules") if isinstance(extraction.get("modules"), dict) else {}
    base_dir = Path(path).resolve().parent
    rows = []
    for name, m in modules.items():
        if str(name).startswith("_") or not isinstance(m, dict):
            continue
        dev, user = _citations(m.get("url_for_sources_citation"))
        row = {"name": str(name), "description": str(m.get("description") or ""),
               "cite_dev": dev, "cite_user": user,
               "json_only": sorted(k for k in m if not k.startswith("_") and k not in SOURCE_KEYS)}
        for short, key in SOURCE_PATHS:
            row[key] = str(m.get(key) or "")
            row[f"{short}_state"] = _path_state(row[key], base_dir)
        rows.append(row)
    return rows


SOURCE_KEYS = {"description", "dev_path", "user_path", "url_for_sources_citation"}


def _save_doc_sources(data: dict, rows) -> None:
    """The settings' rows into rag.extraction.modules, in their order. Keys the
    form does not show (methodology_path, comments...) stay with their source,
    also across a rename (`orig`). Raises ValueError on a bad or repeated name."""
    if not isinstance(rows, list):
        return
    if not isinstance(data.get("rag"), dict):
        data["rag"] = rag_backend.default_rag()
    rag = data["rag"]
    if not isinstance(rag.get("extraction"), dict):
        rag["extraction"] = rag_backend.default_rag().get("extraction") or {}
    extraction = rag["extraction"]
    old = extraction.get("modules") if isinstance(extraction.get("modules"), dict) else {}
    modules = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = {k: str(row.get(k) or "").strip() for k in
                ("name", "orig", "description", "dev_path", "user_path", "cite_dev", "cite_user")}
        name = text["name"]
        if not name and not any(text[k] for k in ("description", "dev_path", "user_path")):
            continue                                   # a blank row the user added
        if not SOURCE_NAME.fullmatch(name):
            raise ValueError(f"documentation source name {name!r}: use letters, digits, _ . + -")
        if name in modules:
            raise ValueError(f"documentation source {name!r} is listed twice")
        kept = old.get(text["orig"] or name)
        module = {k: v for k, v in kept.items() if k not in SOURCE_KEYS} if isinstance(kept, dict) else {}
        if text["description"]:
            module["description"] = text["description"]
        for _, key in SOURCE_PATHS:
            if text[key]:
                module[key] = text[key]
        dev, user = text["cite_dev"], text["cite_user"]
        if dev and user and dev != user:
            module["url_for_sources_citation"] = {"dev": dev, "user": user}
        elif dev or user:
            module["url_for_sources_citation"] = dev or user
        modules[name] = module
    extraction["modules"] = modules


def _save_rag_models(data: dict, fields: dict) -> None:
    """The Models section: the embedding model into both rag.chatbot.embedding
    and rag.extraction.embedding (raglib: they must stay identical), the
    reranker into rag.chatbot.reranker, or where it is parked while off."""
    if not isinstance(data.get("rag"), dict):
        data["rag"] = rag_backend.default_rag()
    rag = data["rag"]
    if not isinstance(rag.get("chatbot"), dict):
        rag["chatbot"] = {}
    chatbot = rag["chatbot"]
    emb = str(fields.get("embedding_model") or "").strip()
    if emb:
        if not isinstance(rag.get("extraction"), dict):
            rag["extraction"] = {}
        for section in (chatbot, rag["extraction"]):
            if not isinstance(section.get("embedding"), dict):
                section["embedding"] = {"model": emb, "type": "local", "base_url": None, "api_key": None}
            section["embedding"]["model"] = emb
    model = str(fields.get("reranker_model") or "").strip()
    kind = fields.get("reranker_type")
    if model or kind in rag_models.RERANKER_TYPES:
        target = chatbot.get("reranker")
        if not (isinstance(target, dict) and target):
            target = chatbot.get(RERANKER_PARKED)
            if not isinstance(target, dict):
                target = chatbot[RERANKER_PARKED] = dict(DEFAULT_RERANKER)
        if model:
            target["model"] = model
        if kind in rag_models.RERANKER_TYPES:
            target["type"] = kind


def complete_config(path: Path) -> bool:
    """Give a config seeded before the documentation modes the example's rag
    section, so one file holds the settings of every mode. An explicit
    `"rag": null` is left alone. True when the file was changed."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or "rag" in data:
        return False
    try:
        data["rag"] = rag_backend.default_rag()
        _write(Path(path), data)
    except (OSError, ValueError, KeyError):
        return False
    return True


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
        "mode": gui.get("mode") if gui.get("mode") in MODES else "agent",
        "show_reasoning": bool(gui.get("show_reasoning", False)),
        "verify_cadence": policy.get("verify_cadence") if policy.get("verify_cadence") in VERIFY_CADENCE else "final",
        "plan_detail": policy.get("plan_detail") if policy.get("plan_detail") in PLAN_DETAIL else "balanced",
        **{k: _clamped(policy, k, POLICY_INTS) for k in POLICY_INTS},
        "shared_model": not active,
        "modules": {name: {k: str(d.get(k) or "") for k in ROW_KEYS} for name, d in shown.items()},
        "modules_json_only": {name: sorted(set(d) - set(ROW_KEYS))
                              for name, d in shown.items() if set(d) - set(ROW_KEYS)},
        **{k: _clamped(llm, k, LLM_INTS) for k in LLM_INTS},
        "rag_options": _rag_options(data if isinstance(data, dict) else {}),
        "doc_sources": _doc_sources(data if isinstance(data, dict) else {}, path),
        "rag_models": rag_models.models_view(data if isinstance(data, dict) else {}),
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
        if fields.get("mode") in MODES:
            gui["mode"] = fields["mode"]
            if fields["mode"] in rag_backend.DOC_MODES and data.get("rag") is None:
                # a config seeded before the documentation modes: start from the example's
                data["rag"] = rag_backend.default_rag()
        if isinstance(fields.get("rag_options"), dict):
            _save_rag_options(data, fields["rag_options"])
        if isinstance(fields.get("rag_models"), dict):
            _save_rag_models(data, fields["rag_models"])
        if "batch" in fields:
            gui["batch"] = bool(fields["batch"])
        if "verbose" in fields:
            gui["verbose"] = max(0, min(2, int(fields["verbose"])))
    # what the index build reads, not an open conversation: saved at any time
    if "doc_sources" in fields:
        _save_doc_sources(data, fields["doc_sources"])
    _write(Path(path), data)
