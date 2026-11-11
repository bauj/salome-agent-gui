# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""The documentation modes: raglib (git submodule `raglib/`) answering questions
about SALOME from its HTML documentation, in plain RAG or agentic RAG.

raglib is not an installable package: it runs with `raglib/chatbot/` on sys.path
(`import core`) and `raglib/extraction/` next to it. A wheel ships it as
`salome_agent_gui/_raglib/` (pyproject package-dir); a dev checkout uses the
submodule. Its heavy dependencies (torch, chromadb, langchain...) are the `rag`
extra, imported only when a documentation conversation starts, so the agent
mode works without them.

The config file holds raglib's two configs under `rag`:
`{"chatbot": {...}, "extraction": {...}}`, each exactly raglib's own schema.
`rag.chatbot.llm` may be left out: the shared `llm` endpoint and model are used,
and any key it does set wins.
"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

MODES = ("agent", "rag", "rag_agentic")
DOC_MODES = ("rag", "rag_agentic")
MODE_LABEL = {"rag": "Classical RAG", "rag_agentic": "Agentic RAG",
              "agent": "Agentic assistant"}
# the order the main window's mode switch shows them in
MODE_ORDER = ("rag", "rag_agentic", "agent")
# the SALOME menu (Tools > Plugins > AI tools) opens the window on one family:
# "agent" offers only the Agentic assistant, "rag" the two documentation modes
FAMILY_MODES = {"agent": ("agent",), "rag": ("rag", "rag_agentic")}


def modes_of(family) -> tuple:
    """The modes a window opened on `family` offers, in MODE_ORDER; every mode
    when it was started without one (salome-agent-gui run by hand)."""
    allowed = FAMILY_MODES.get(family, MODES)
    return tuple(m for m in MODE_ORDER if m in allowed)
MODE_HINT = {"rag": "answers from the SALOME documentation after one search.",
             "rag_agentic": "the model searches and reads the SALOME documentation "
                            "several times before answering.",
             "agent": "builds geometry and meshes in this SALOME study."}
# extra whose packages a documentation conversation needs (pyproject `rag`)
INSTALL_HINT = ("the documentation modes need the rag extra: "
                "pip install --extra-index-url https://download.pytorch.org/whl/cpu "
                "'salome-agent-gui[rag]'")
EMPTY_ANSWER_RETRIES = 2


class RagError(Exception):
    """A documentation-mode problem worth showing the user as is."""


# ---- where raglib is ----------------------------------------------------
def raglib_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [here / "_raglib",                    # installed wheel (pyproject package-dir)
            here.parent / "raglib"]              # dev checkout: the submodule


def raglib_dir() -> Path:
    for d in raglib_candidates():
        if (d / "chatbot" / "core" / "config.py").is_file():
            return d
    raise RagError("raglib not found (run `git submodule update --init` in the checkout)")


def ensure_path() -> Path:
    root = raglib_dir()
    for sub in ("extraction", "chatbot"):        # chatbot first on sys.path, like raglib's tests
        p = str(root / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    return root


_config_module = None


def _config_cls():
    """raglib's ChatbotConfig, loaded from its file alone: `core/__init__` imports
    the whole chatbot (langchain, chromadb), which config checks do not need."""
    global _config_module
    if _config_module is None:
        path = raglib_dir() / "chatbot" / "core" / "config.py"
        spec = importlib.util.spec_from_file_location("_salome_agent_gui_raglib_config", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _config_module = module
    return _config_module.ChatbotConfig


# ---- config -------------------------------------------------------------
def _strip_comments(d):
    if isinstance(d, dict):
        return {k: _strip_comments(v) for k, v in d.items() if not str(k).startswith("_")}
    return d


_NAME = re.compile(r"[A-Za-z_]\w*")
_UNSET = re.compile(r"\$\{?([A-Za-z_]\w*)")


def expand_env(text: str, env=None) -> str:
    """`$VAR`, `${VAR}` and the shell's `${VAR:-fallback}` (fallback used when VAR
    is unset or empty; it may hold variables itself). SALOME's environment sets
    DOCUMENTATION_ROOT_DIR and one <MODULE>_ROOT_DIR per module, so the doc paths
    read `${DOCUMENTATION_ROOT_DIR:-$GEOM_ROOT_DIR}/share/doc/salome/gui/GEOM`.
    An unset variable without fallback stays literal (see `unset_vars`)."""
    env = os.environ if env is None else env
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] != "$":
            out.append(text[i])
            i += 1
            continue
        if text.startswith("${", i):
            depth, j = 1, i + 2
            while j < n and depth:
                depth += {"{": 1, "}": -1}.get(text[j], 0)
                j += 1
            if depth:                              # no closing brace: keep the rest as is
                out.append(text[i:])
                break
            name, sep, fallback = text[i + 2:j - 1].partition(":-")
            if not _NAME.fullmatch(name):
                out.append(text[i:j])
            elif env.get(name):
                out.append(env[name])
            elif sep:
                out.append(expand_env(fallback, env))
            else:
                out.append(text[i:j])
            i = j
            continue
        m = _NAME.match(text, i + 1)
        if m and env.get(m.group()):
            out.append(env[m.group()])
        else:
            out.append(text[i:m.end()] if m else "$")
        i = m.end() if m else i + 1
    return "".join(out)


def unset_vars(text) -> list[str]:
    """The variables `expand_env` could not replace in `text`."""
    return _UNSET.findall(expand_env(text)) if isinstance(text, str) else []


def _abspath(p, base_dir: Path):
    """`~` and `$VAR`/`${VAR:-fallback}` expanded (`expand_env`), then relative to
    the config file's directory. An unset variable stays literal and fails later
    with a path-not-found message."""
    if not p or not isinstance(p, str):
        return p
    p = os.path.expanduser(expand_env(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base_dir, p))


def rag_section(data: dict) -> tuple[dict, dict]:
    """(chatbot, extraction) of a whole config file, comments stripped."""
    rag = data.get("rag") if isinstance(data, dict) else None
    if rag is None:
        raise RagError('the config has no "rag" section (see config.example.json)')
    if not isinstance(rag, dict):
        raise RagError('"rag" must be an object {"chatbot": {...}, "extraction": {...}}')
    rag = _strip_comments(rag)
    chatbot, extraction = rag.get("chatbot") or {}, rag.get("extraction") or {}
    if not isinstance(chatbot, dict) or not isinstance(extraction, dict):
        raise RagError('"rag.chatbot" and "rag.extraction" must be objects')
    return chatbot, extraction


def _shared_llm(data: dict) -> dict:
    llm = data.get("llm") if isinstance(data.get("llm"), dict) else {}
    return {"base_url": llm.get("base_url") or "", "model": llm.get("model") or "",
            "api_key": llm.get("api_key") or "", "ssl_cert_file": llm.get("ssl_cert_file") or ""}


def resolve_chatbot(data: dict, config_path) -> dict:
    """rag.chatbot ready for raglib: llm filled from the shared one, paths absolute."""
    base_dir = Path(config_path).resolve().parent
    chatbot = copy.deepcopy(rag_section(data)[0])
    llm = _shared_llm(data)
    own = chatbot.get("llm")
    if own is not None and not isinstance(own, dict):
        raise RagError('"rag.chatbot.llm" must be an object')
    llm.update({k: v for k, v in (own or {}).items() if v not in (None, "")})
    if not llm["base_url"] or not llm["model"]:
        raise RagError("no LLM set: give the base URL and model in the settings")
    llm["api_key"] = llm["api_key"] or "dummy"         # langchain-openai refuses an empty key
    llm["ssl_cert_file"] = _abspath(llm["ssl_cert_file"], base_dir) or None
    chatbot["llm"] = llm
    if chatbot.get("chromadb_path"):
        chatbot["chromadb_path"] = _abspath(chatbot["chromadb_path"], base_dir)
    agentic = chatbot.get("agentic")
    if isinstance(agentic, dict) and agentic.get("page_index_path"):
        agentic["page_index_path"] = _abspath(agentic["page_index_path"], base_dir)
    return chatbot


def index_path(chatbot: dict, config_path) -> str:
    """rag.chatbot.chromadb_path as raglib will open it; "" when unset."""
    p = chatbot.get("chromadb_path") if isinstance(chatbot, dict) else None
    return str(_abspath(p, Path(config_path).resolve().parent)) if p else ""


def resolve_extraction(data: dict, config_path) -> dict:
    base_dir = Path(config_path).resolve().parent
    extraction = copy.deepcopy(rag_section(data)[1])
    if extraction.get("output_dir"):
        extraction["output_dir"] = _abspath(extraction["output_dir"], base_dir)
    for module in (extraction.get("modules") or {}).values():
        if isinstance(module, dict):
            for key in DOC_PATH_KEYS:
                if module.get(key):
                    module[key] = _abspath(module[key], base_dir)
    return extraction


def _load_config(cls, chatbot: dict):
    """raglib's own loader (it checks every key), which only reads a file."""
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(chatbot, f)
        return cls.load(tmp)
    finally:
        os.unlink(tmp)


def check(data: dict, config_path) -> None:
    """Raise if the rag section is there and raglib would refuse it. No rag
    section is fine: the agent mode does not need one."""
    if not isinstance(data, dict) or data.get("rag") is None:
        return
    chatbot = rag_section(data)[0]
    if chatbot.get("llm") is not None and not isinstance(chatbot["llm"], dict):
        raise RagError('"rag.chatbot.llm" must be an object')
    chatbot = {k: v for k, v in chatbot.items() if not (k == "llm" and v is None)}
    try:
        cls = _config_cls()
    except (ImportError, OSError, SyntaxError) as e:
        raise RagError(f"raglib's config checks could not be loaded: {e}") from e
    try:
        _load_config(cls, chatbot)
    except (ValueError, TypeError, AttributeError) as e:
        raise RagError(f"rag.chatbot: {e}") from e


def default_rag() -> dict:
    """The rag section of the shipped config.example.json."""
    example = Path(__file__).resolve().parent / "config.example.json"
    return copy.deepcopy(json.loads(example.read_text())["rag"])


# ---- a documentation session -------------------------------------------
class RagSession:
    """The raglib chatbots built from one resolved config; slow to build (it
    loads the embedding and reranker models), so the bridge keeps one."""

    def __init__(self, chatbot: dict, *, agentic: bool):
        ensure_path()
        try:
            from core import AgenticChatbot, ChatbotConfig, DocumentationChatbot
        except ImportError as e:
            raise RagError(f"{e}; {INSTALL_HINT}") from e
        config = _load_config(ChatbotConfig, chatbot)
        db = Path(config.chromadb_path)
        if not db.exists():
            raise RagError(f"no documentation index at {db}: build it first "
                           "(Settings > Documentation > Build index)")
        self.config = config
        self.rag = DocumentationChatbot(config)
        self.agentic = None
        if agentic:
            if config.agentic is None:
                raise RagError('agentic RAG needs a "rag.chatbot.agentic" block in the config')
            score = self.rag.score_against_query if self.rag.reranker is not None else None
            # without these AgenticChatbot falls back to page-level search, unreranked
            self.agentic = AgenticChatbot(config, vectorstore=self.rag.vectorstore,
                                          bm25_index=self.rag.bm25_index,
                                          reranker_score_fn=score,
                                          section_select_fn=self.rag.expand_sections)

    @property
    def modules(self) -> list[str]:
        return list(getattr(self.rag, "available_modules", []) or [])

    def ask(self, question: str) -> dict:
        """raglib's {answer, sources, filters, error}."""
        if self.agentic is None:
            return self.rag.ask(question)
        # raglib's agent can end on a blank message with no error, mostly when its
        # tool history outgrew the context; usually transient
        result = self.agentic.ask(question)
        tries = 1
        while (not result.get("error") and not (result.get("answer") or "").strip()
               and tries <= EMPTY_ANSWER_RETRIES):
            result = self.agentic.ask(question)
            tries += 1
        if not result.get("error") and not (result.get("answer") or "").strip():
            result = dict(result, error=(
                f"the model returned an empty answer {tries} times; the pages it read may "
                "not fit its context. Lower rag.chatbot.agentic.max_steps or "
                "max_chars_per_page, or rephrase the question."))
        return result


_cache: dict = {}
_cache_lock = threading.Lock()


def open_session(chatbot: dict, *, agentic: bool) -> RagSession:
    """One cached session: a new conversation on the same config reuses its models."""
    key = (json.dumps(chatbot, sort_keys=True), agentic)
    with _cache_lock:
        if _cache.get("key") != key:
            _cache.clear()
            _cache.update(key=key, session=RagSession(chatbot, agentic=agentic))
        return _cache["session"]


def sources_view(sources) -> list[dict]:
    """raglib's sources (RAG: url; agentic: filepath), deduplicated by page."""
    out, seen = [], set()
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        url = str(s.get("url") or "")
        path = str(s.get("filepath") or "")
        title = str(s.get("title") or s.get("filename") or "Untitled")
        key = url or path or title
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": title, "module": str(s.get("module") or ""),
                    "category": str(s.get("doc_category") or ""),
                    "url": url if url.startswith(("http://", "https://")) else "",
                    "path": path})
    return out


# ---- building the index -------------------------------------------------
DOC_PATH_KEYS = ("dev_path", "user_path", "methodology_path")


def unset_doc_vars(data: dict) -> tuple[list[str], bool]:
    """(variables the module doc paths need but the environment lacks, whether
    every path needs one), from rag.extraction.modules."""
    missing, paths, broken = set(), 0, 0
    for module in (rag_section(data)[1].get("modules") or {}).values():
        if not isinstance(module, dict):
            continue
        for key in DOC_PATH_KEYS:
            if module.get(key):
                names = unset_vars(module[key])
                paths += 1
                broken += bool(names)
                missing.update(names)
    return sorted(missing), bool(paths) and broken == paths


def extraction_command(data: dict, config_path, workdir) -> list[str]:
    """process_docs.py on the resolved extraction config, written into `workdir`
    (it resolves relative paths against its cwd, not the config file)."""
    root = raglib_dir()
    extraction = resolve_extraction(data, config_path)
    if not extraction.get("modules"):
        raise RagError("rag.extraction.modules is empty: nothing to index")
    missing, none_left = unset_doc_vars(data)
    if none_left:
        raise RagError(
            f"the documentation paths need {', '.join('$' + v for v in missing)}, not set "
            "here: build the index in SALOME's environment (<SALOME>/salome shell -- ...), "
            "or export DOCUMENTATION_ROOT_DIR=<SALOME>/INSTALL/DOCUMENTATION")
    resolved = Path(workdir) / "extraction.json"
    resolved.write_text(json.dumps(extraction))
    return [sys.executable, "-u", str(root / "extraction" / "process_docs.py"),
            "--config", str(resolved)]


def build_index(config_path, on_line=print, cancel=None) -> int:
    """Run raglib's extraction for the config file; returns its exit code."""
    from salome_agent_gui import rag_models

    data = json.loads(Path(config_path).read_text())
    root = raglib_dir()
    with tempfile.TemporaryDirectory(prefix="salome-agent-rag-") as tmp:
        cmd = extraction_command(data, config_path, tmp)
        # the build embeds every chunk: fetch a missing embedding model first
        code = rag_models.download(rag_models.missing(data, ("embedding",)), on_line, cancel)
        if code != 0:
            return code
        missing = unset_doc_vars(data)[0]
        if missing:
            on_line(f"Warning: {', '.join('$' + v for v in missing)} not set: "
                    "the documentation paths using it are skipped")
        proc = subprocess.Popen(cmd, cwd=root / "extraction", stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            for line in proc.stdout:
                on_line(line.rstrip("\n"))
                if cancel is not None and cancel.is_set():
                    proc.terminate()
                    break
        finally:
            code = proc.wait()
    with _cache_lock:
        _cache.clear()                           # a rebuilt index needs a fresh session
    return code


def main_index(argv=None) -> int:
    """salome-agent-rag-index [CONFIG]: build the documentation index."""
    import argparse

    from salome_agent_gui import config_store

    parser = argparse.ArgumentParser(description=main_index.__doc__)
    parser.add_argument("config", nargs="?", help=f"default: {config_store.USER_CONFIG}")
    args = parser.parse_args(argv)
    path = Path(args.config) if args.config else config_store.ensure_user_config()
    try:
        return build_index(path)
    except (RagError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main_index())
