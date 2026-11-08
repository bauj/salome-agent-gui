# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""The local models the documentation modes use, as raglib's download_models.py
lists them: the embedding model (index build and every search) and the
reranker. raglib's chatbot runs with HF_HUB_OFFLINE=1, so a model missing from
the Hugging Face cache fails at the first question: the settings show which are
installed and download the others.

Checking the cache needs no torch: it reads the hub cache layout
(models--org--name/snapshots/<rev>/...). Downloading loads the model once with
sentence-transformers, as download_models.py does, in a child process
(`python -m salome_agent_gui.rag_models KIND MODEL`) so the GUI never imports
torch and the offline switch of an open chatbot does not apply to it.
"""
import os
import subprocess
import sys
from pathlib import Path

# raglib/download_models.py's models, with what the settings say about them
EMBEDDINGS = [
    {"model": "all-MiniLM-L6-v2", "note": "small and fast, English (raglib's default)"},
]
RERANKERS = [
    {"model": "answerdotai/answerai-colbert-small-v1", "type": "late_interaction",
     "note": "ColBERT late interaction, small (default)"},
    {"model": "BAAI/bge-reranker-v2-m3", "type": "cross_encoder",
     "note": "cross-encoder, multilingual, larger and slower"},
]
RERANKER_TYPES = ("late_interaction", "cross_encoder")
KINDS = ("embedding",) + RERANKER_TYPES
WEIGHTS = (".safetensors", ".bin", ".onnx")
CONFIGS = ("config.json", "modules.json", "config_sentence_transformers.json")


def hub_cache() -> Path:
    """Where huggingface_hub keeps models: $HF_HUB_CACHE, else $HF_HOME/hub,
    else ~/.cache/huggingface/hub (huggingface_hub's own rule)."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    home = os.environ.get("HF_HOME") or os.path.join(
        os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "huggingface")
    return Path(home).expanduser() / "hub"


def repo_id(model: str, kind: str = "embedding") -> str:
    """The hub repository sentence-transformers loads: a bare embedding name
    such as all-MiniLM-L6-v2 lives under sentence-transformers/."""
    if kind == "embedding" and "/" not in model:
        return f"sentence-transformers/{model}"
    return model


def _snapshot_complete(snap: Path) -> bool:
    """A config and weights whose file is really there (snapshot files are links
    into blobs/, or, with xet storage, into the hub's shared blobs/)."""
    names = {p.name for p in snap.rglob("*") if p.is_file()}
    return any(c in names for c in CONFIGS) and any(n.endswith(WEIGHTS) for n in names)


def _size(path: Path) -> int:
    """Bytes of the files under `path`, links followed, each target counted once."""
    total, seen = 0, set()
    for p in path.rglob("*"):
        try:
            real = p.resolve()
            if real in seen or not real.is_file():
                continue
            seen.add(real)
            total += real.stat().st_size
        except OSError:
            pass
    return total


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def status(model: str, kind: str = "embedding", *, cache: Path | None = None) -> dict:
    """{state: installed | missing | local | none, repo, path, size}."""
    model = (model or "").strip()
    if not model:
        return {"state": "none", "repo": "", "path": "", "size": ""}
    local = Path(os.path.expanduser(model))
    if local.is_absolute() and local.is_dir():
        return {"state": "local", "repo": "", "path": str(local), "size": human_size(_size(local))}
    repo = repo_id(model, kind)
    folder = (cache or hub_cache()) / ("models--" + repo.replace("/", "--"))
    snaps = folder / "snapshots"
    complete = [s for s in snaps.iterdir() if s.is_dir() and _snapshot_complete(s)] if snaps.is_dir() else []
    if complete:
        return {"state": "installed", "repo": repo, "path": str(folder),
                "size": human_size(max(_size(s) for s in complete))}
    return {"state": "missing", "repo": repo, "path": str(folder), "size": ""}


def _section(data, name) -> dict:
    value = data.get(name) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def configured(data: dict) -> dict:
    """The models a config uses: {"embedding": (model, type), "reranker":
    (model, kind, enabled)}. A reranker switched off in the settings is parked
    under rag.chatbot._reranker_off and still shown."""
    chatbot = _section(_section(data, "rag"), "chatbot")
    emb = _section(chatbot, "embedding")
    rr = chatbot.get("reranker")
    enabled = isinstance(rr, dict) and bool(rr)
    if not enabled:
        rr = chatbot.get("_reranker_off")
    rr = rr if isinstance(rr, dict) else {}
    kind = rr.get("type") if rr.get("type") in RERANKER_TYPES else "late_interaction"
    return {"embedding": (str(emb.get("model") or "all-MiniLM-L6-v2"), str(emb.get("type") or "local")),
            "reranker": (str(rr.get("model") or RERANKERS[0]["model"]), kind, enabled)}


def models_view(data: dict) -> dict:
    """What the settings' Models section shows."""
    c = configured(data if isinstance(data, dict) else {})
    model, etype = c["embedding"]
    emb = {"model": model, "type": etype,
           "status": {"state": "api", "repo": "", "path": "", "size": ""} if etype == "api"
           else status(model, "embedding")}
    rmodel, kind, enabled = c["reranker"]
    rr = {"model": rmodel, "type": kind, "enabled": enabled, "status": status(rmodel, kind)}
    return {"embedding": emb, "reranker": rr, "cache": str(hub_cache()),
            "choices": {"embedding": EMBEDDINGS, "reranker": RERANKERS}}


def missing(data: dict, roles=("embedding", "reranker"), *, only_enabled=True) -> list[tuple]:
    """[(role, kind, model)] of the configured local models not in the cache."""
    c = configured(data)
    out = []
    model, etype = c["embedding"]
    if "embedding" in roles and etype != "api" and status(model, "embedding")["state"] == "missing":
        out.append(("embedding", "embedding", model))
    rmodel, kind, enabled = c["reranker"]
    if "reranker" in roles and (enabled or not only_enabled) and status(rmodel, kind)["state"] == "missing":
        out.append(("reranker", kind, rmodel))
    return out


def download_command(kind: str, model: str) -> list[str]:
    return [sys.executable, "-u", "-m", "salome_agent_gui.rag_models", kind, model]


def download(items, on_line=print, cancel=None) -> int:
    """Download each (role, kind, model) in a child process; the first failure's
    exit code, else 0."""
    for role, kind, model in items:
        on_line(f"Downloading the {role} model {model}…")
        env = dict(os.environ, HF_HUB_OFFLINE="0", TOKENIZERS_PARALLELISM="false")
        proc = subprocess.Popen(download_command(kind, model), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
        try:
            for line in proc.stdout:
                for part in line.replace("\r", "\n").split("\n"):
                    if part.strip():
                        on_line(part.rstrip())
                if cancel is not None and cancel.is_set():
                    proc.terminate()
                    break
        finally:
            code = proc.wait()
        if cancel is not None and cancel.is_set():
            return code or 1
        if code != 0:
            return code
        on_line(f"{model}: installed.")
    return 0


def main(argv=None) -> int:
    """python -m salome_agent_gui.rag_models KIND MODEL: what download_models.py does for one model."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in KINDS:
        print(f"usage: python -m salome_agent_gui.rag_models {{{'|'.join(KINDS)}}} MODEL", file=sys.stderr)
        return 2
    kind, model = args
    os.environ["HF_HUB_OFFLINE"] = "0"           # before huggingface_hub is imported
    try:
        import sentence_transformers as st
    except ImportError as e:
        print(f"error: {e}; the documentation modes need the rag extra", file=sys.stderr)
        return 3
    try:
        if kind == "embedding":
            st.SentenceTransformer(model)
        elif kind == "cross_encoder":
            st.CrossEncoder(model)
        else:
            st.MultiVectorEncoder(model)
    except Exception as e:  # noqa: BLE001
        print(f"error: could not download {model}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"{model}: done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
