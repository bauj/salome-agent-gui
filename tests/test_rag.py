# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import json
import threading
import tomllib
from pathlib import Path

import pytest

from salome_agent_gui import config_store as cs
from salome_agent_gui import rag_backend as rb
from salome_agent_gui.bridge import Bridge
from salome_agent_gui.rag_worker import RagWorker
from tests.fakes import CFG, opener, write_cfg

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "salome_agent_gui" / "config.example.json"
ENGINE_EXAMPLE = ROOT / "salome-agent" / "config.example.json"
ANSWER = {"answer": "Use `geompy.MakeBoxDXDYDZ(10, 10, 10)`.",
          "sources": [{"title": "Box", "module": "GEOM", "doc_category": "dev",
                       "url": "https://docs.salome-platform.org/latest/tui/GEOM/box.html"},
                      {"title": "Box", "module": "GEOM", "doc_category": "dev",
                       "url": "https://docs.salome-platform.org/latest/tui/GEOM/box.html"},
                      {"title": "Local page", "module": "SMESH", "doc_category": "user",
                       "filepath": "/docs/smesh/page.html", "filename": "page.html"}],
          "filters": {"mode": "rag", "token_usage": {"input_tokens": 1200, "output_tokens": 80}},
          "error": None}


def rag_cfg(mode="rag", **chatbot):
    data = json.loads(json.dumps(CFG))
    data["gui"] = {"mode": mode}
    data["rag"] = {"chatbot": {"project_name": "salome", "chromadb_path": "db/chromadb",
                               **chatbot},
                   "extraction": {"project_name": "salome", "output_dir": "db",
                                  "modules": {"GEOM": {"dev_path": "$FAKE_ROOT/tui/GEOM"}}}}
    return data


# ---- config ---------------------------------------------------------------
def test_raglib_is_found_in_the_submodule():
    assert (rb.raglib_dir() / "chatbot" / "core" / "config.py").is_file()


def test_chatbot_uses_the_shared_llm_and_resolves_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ROOT", "/opt/salome")
    path = tmp_path / "c.json"
    data = rag_cfg(agentic={"page_index_path": "$FAKE_ROOT/idx.json"})
    chatbot = rb.resolve_chatbot(data, path)
    assert chatbot["llm"] == {"base_url": "http://h/v1", "model": "m", "api_key": "secret",
                              "ssl_cert_file": None}
    assert chatbot["chromadb_path"] == str(tmp_path / "db" / "chromadb")
    assert chatbot["agentic"]["page_index_path"] == "/opt/salome/idx.json"
    assert rb.resolve_extraction(data, path)["modules"]["GEOM"]["dev_path"] == "/opt/salome/tui/GEOM"
    assert "llm" not in data["rag"]["chatbot"]          # the file's data is left as it was


def test_expand_env_follows_the_shell_fallback_syntax():
    env = {"DOC": "/doc", "GEOM_ROOT_DIR": "/geom", "EMPTY": ""}
    assert rb.expand_env("${DOC:-$GEOM_ROOT_DIR}/gui", env) == "/doc/gui"
    assert rb.expand_env("${NOPE:-$GEOM_ROOT_DIR}/gui", env) == "/geom/gui"
    assert rb.expand_env("${EMPTY:-${DOC}}/x", env) == "/doc/x"
    assert rb.expand_env("$GEOM_ROOT_DIR/a and ${DOC}", env) == "/geom/a and /doc"
    assert rb.expand_env("${NOPE:-$ALSO_NOPE}/x", env) == "$ALSO_NOPE/x"
    assert rb.expand_env("$NOPE/x ${NOPE} $ ${bad name} ${open", env) == "$NOPE/x ${NOPE} $ ${bad name} ${open"


def test_example_doc_paths_use_documentation_root_dir_then_the_module_root(tmp_path, monkeypatch):
    data = json.loads(EXAMPLE.read_text())
    monkeypatch.delenv("DOCUMENTATION_ROOT_DIR", raising=False)
    for m in ("GEOM", "SHAPER", "SMESH"):
        monkeypatch.setenv(f"{m}_ROOT_DIR", f"/install/{m}")
    geom = rb.resolve_extraction(data, EXAMPLE)["modules"]["GEOM"]
    assert geom["user_path"] == "/install/GEOM/share/doc/salome/gui/GEOM"
    assert rb.unset_doc_vars(data) == ([], False)
    monkeypatch.setenv("DOCUMENTATION_ROOT_DIR", "/install/DOCUMENTATION")
    smesh = rb.resolve_extraction(data, EXAMPLE)["modules"]["SMESH"]
    assert smesh["dev_path"] == "/install/DOCUMENTATION/share/doc/salome/tui/SMESH"
    assert smesh["url_for_sources_citation"]["user"].endswith("/gui/SMESH")


def test_index_build_without_salome_environment_names_the_variables(tmp_path, monkeypatch):
    data = json.loads(EXAMPLE.read_text())
    for var in ("DOCUMENTATION_ROOT_DIR", "GEOM_ROOT_DIR", "SHAPER_ROOT_DIR", "SMESH_ROOT_DIR"):
        monkeypatch.delenv(var, raising=False)
    assert rb.unset_doc_vars(data) == (["GEOM_ROOT_DIR", "SHAPER_ROOT_DIR", "SMESH_ROOT_DIR"], True)
    with pytest.raises(rb.RagError, match=r"\$GEOM_ROOT_DIR.*DOCUMENTATION_ROOT_DIR"):
        rb.extraction_command(data, EXAMPLE, tmp_path)
    monkeypatch.setenv("GEOM_ROOT_DIR", "/install/GEOM")      # some left: build, with a warning
    assert rb.unset_doc_vars(data) == (["SHAPER_ROOT_DIR", "SMESH_ROOT_DIR"], False)
    rb.extraction_command(data, EXAMPLE, tmp_path)


def test_rag_llm_keys_override_the_shared_ones_and_an_empty_key_becomes_dummy(tmp_path):
    data = rag_cfg(llm={"model": "doc-model", "base_url": ""})
    data["llm"]["api_key"] = ""
    llm = rb.resolve_chatbot(data, tmp_path / "c.json")["llm"]
    assert llm["model"] == "doc-model" and llm["base_url"] == "http://h/v1"
    assert llm["api_key"] == "dummy"


def test_no_model_or_no_rag_section_is_a_clear_error(tmp_path):
    data = rag_cfg()
    data["llm"]["model"] = ""
    with pytest.raises(rb.RagError, match="no LLM"):
        rb.resolve_chatbot(data, tmp_path / "c.json")
    with pytest.raises(rb.RagError, match="no \"rag\" section"):
        rb.resolve_chatbot(CFG, tmp_path / "c.json")


def test_check_accepts_no_rag_and_the_example_but_refuses_unknown_keys(tmp_path):
    rb.check(CFG, tmp_path / "c.json")
    rb.check(json.loads(EXAMPLE.read_text()), EXAMPLE)
    with pytest.raises(rb.RagError, match="rag.chatbot"):
        rb.check(rag_cfg(k_standart=3), tmp_path / "c.json")
    with pytest.raises(rb.RagError, match="rag.chatbot"):
        rb.check(rag_cfg(reranker={"model": "x", "type": "nope"}), tmp_path / "c.json")


def test_config_store_load_and_save_raw_check_the_rag_section(tmp_path):
    path = write_cfg(tmp_path, rag_cfg())
    assert cs.load(path)["gui"]["mode"] == "rag"
    before = path.read_text()
    with pytest.raises(rb.RagError):
        cs.save_raw(path, json.dumps(rag_cfg(bogus=1)))
    assert path.read_text() == before


def test_gui_example_keeps_the_engine_example_and_adds_mode_and_rag():
    gui, engine = json.loads(EXAMPLE.read_text()), json.loads(ENGINE_EXAMPLE.read_text())
    for key, value in engine.items():
        assert gui[key] == value, key
    assert gui["gui"]["mode"] == "agent"
    chatbot, extraction = rb.rag_section(gui)
    assert chatbot["embedding"] == extraction["embedding"]   # raglib: must stay identical
    assert chatbot["project_name"] == extraction["project_name"]
    assert rb.default_rag() == gui["rag"]


def test_seed_prefers_the_gui_example():
    assert cs.seed_candidates()[0] == EXAMPLE


def test_mode_is_a_run_option_and_a_doc_mode_adds_the_rag_section(tmp_path):
    path = write_cfg(tmp_path)
    assert cs.read_settings(path)["mode"] == "agent"
    cs.save_settings(path, {"mode": "rag"}, run_options=False)
    assert cs.read_settings(path)["mode"] == "agent"
    cs.save_settings(path, {"mode": "rag_agentic"})
    data = json.loads(path.read_text())
    assert data["gui"]["mode"] == "rag_agentic" and data["rag"] == rb.default_rag()
    cs.save_settings(path, {"mode": "nonsense"})
    assert cs.read_settings(path)["mode"] == "rag_agentic"
    data["gui"]["mode"] = "junk"
    path.write_text(json.dumps(data))
    assert cs.read_settings(path)["mode"] == "agent"


def test_sources_are_deduplicated_and_only_web_urls_kept():
    out = rb.sources_view(ANSWER["sources"] + [{"title": "x", "url": "javascript:alert(1)"}, "junk"])
    assert out == [
        {"title": "Box", "module": "GEOM", "category": "dev",
         "url": "https://docs.salome-platform.org/latest/tui/GEOM/box.html", "path": ""},
        {"title": "Local page", "module": "SMESH", "category": "user", "url": "",
         "path": "/docs/smesh/page.html"},
        {"title": "x", "module": "", "category": "", "url": "", "path": ""}]


def test_extraction_command_runs_process_docs_on_the_resolved_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ROOT", "/opt/salome")
    cmd = rb.extraction_command(rag_cfg(), tmp_path / "c.json", tmp_path)
    assert cmd[2].endswith("extraction/process_docs.py") and cmd[3] == "--config"
    written = json.loads(Path(cmd[4]).read_text())
    assert written["output_dir"] == str(tmp_path / "db")
    assert written["modules"]["GEOM"]["dev_path"] == "/opt/salome/tui/GEOM"
    data = rag_cfg()
    data["rag"]["extraction"]["modules"] = {}
    with pytest.raises(rb.RagError, match="nothing to index"):
        rb.extraction_command(data, tmp_path / "c.json", tmp_path)


def test_missing_index_is_reported_before_loading_any_model(tmp_path):
    pytest.importorskip("langchain_chroma")
    chatbot = rb.resolve_chatbot(rag_cfg(), tmp_path / "c.json")
    with pytest.raises(rb.RagError, match="no documentation index"):
        rb.RagSession(chatbot, agentic=False)


def test_rag_extra_and_raglib_sources_are_packaged():
    py = tomllib.loads((ROOT / "pyproject.toml").read_text())
    st = py["tool"]["setuptools"]
    assert st["package-dir"]["salome_agent_gui._raglib"] == "raglib"
    assert "salome_agent_gui._raglib" in st["packages"]
    assert "chatbot/core/*.py" in st["package-data"]["salome_agent_gui._raglib"]
    assert "config.example.json" in st["package-data"]["salome_agent_gui"]
    assert any(d.startswith("deepagents") for d in py["project"]["optional-dependencies"]["rag"])


# ---- worker ---------------------------------------------------------------
class FakeSession:
    def __init__(self, rec, result=None, release=None):
        self.rec, self.result, self.release = rec, result or ANSWER, release

    def ask(self, question):
        self.rec.setdefault("asked", []).append(question)
        if self.release is not None:
            self.release.wait(5)
        return self.result


def rag_opener(rec, **kw):
    def open_fn(chatbot, *, agentic):
        rec["opened"] = rec.get("opened", 0) + 1
        rec.update(chatbot=chatbot, agentic=agentic)
        if kw.get("fail"):
            raise rb.RagError("no documentation index at /x")
        return FakeSession(rec, kw.get("result"), kw.get("release"))
    return open_fn


def run_worker(qtbot, worker, command="turn", text="how?"):
    events, done = [], []
    worker.event.connect(events.append)
    worker.turn_done.connect(done.append)
    worker.start()
    if command == "turn":
        worker.submit(text)
    else:
        getattr(worker, command)()
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    return events, done


def stop_worker(worker):
    worker.close()
    worker.wait(3000)


def test_worker_answers_and_opens_the_session_once(qtbot):
    rec = {}
    w = RagWorker({"x": 1}, agentic=True, open_fn=rag_opener(rec))
    events, done = run_worker(qtbot, w)
    w.submit("again")
    qtbot.waitUntil(lambda: len(done) == 2, timeout=3000)
    stop_worker(w)
    assert rec["opened"] == 1 and rec["agentic"] is True and rec["asked"] == ["how?", "again"]
    kinds = [e["kind"] for e in events]
    assert kinds[:4] == ["rag_status", "rag_status", "rag_answer", "turn_done"]
    answer = events[2]["data"]
    assert answer["answer"] == ANSWER["answer"] and len(answer["sources"]) == 2
    assert answer["usage"] == {"input_tokens": 1200, "output_tokens": 80}
    assert done[0] == {"command": "turn", "status": "ok", "message": "", "degraded": False,
                       "ended": False}


def test_worker_reports_open_and_answer_errors_and_retries_the_open(qtbot):
    rec = {}
    w = RagWorker({}, agentic=False, open_fn=rag_opener(rec, fail=True))
    events, done = run_worker(qtbot, w)
    w.submit("again")
    qtbot.waitUntil(lambda: len(done) == 2, timeout=3000)
    stop_worker(w)
    assert rec["opened"] == 2
    assert done[0]["status"] == "failed" and "no documentation index" in done[0]["message"]
    assert any(e["kind"] == "fatal" for e in events)

    w = RagWorker({}, agentic=False, open_fn=rag_opener({}, result={"answer": None, "error": "boom"}))
    _, done = run_worker(qtbot, w)
    stop_worker(w)
    assert done[0]["status"] == "failed" and done[0]["message"] == "boom"


def test_stop_ends_the_turn_without_waiting_for_the_answer(qtbot):
    release = threading.Event()
    w = RagWorker({}, agentic=False, open_fn=rag_opener({}, release=release))
    events, done = [], []
    w.event.connect(events.append)
    w.turn_done.connect(done.append)
    w.start()
    w.submit("slow")
    qtbot.waitUntil(lambda: any(e["data"].get("phase") == "searching" for e in events), timeout=3000)
    w.stop()
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    release.set()
    stop_worker(w)
    assert done[0]["status"] == "aborted"
    assert not any(e["kind"] == "rag_answer" for e in events)


def test_undo_is_refused_in_the_documentation_modes(qtbot):
    w = RagWorker({}, agentic=False, open_fn=rag_opener({}))
    _, done = run_worker(qtbot, w, command="undo")
    stop_worker(w)
    assert done[0]["command"] == "undo" and done[0]["status"] == "failed"


# ---- bridge ---------------------------------------------------------------
class Pushes:
    def __init__(self, bridge):
        self.items = []
        bridge.push.connect(lambda name, payload: self.items.append((name, json.loads(payload))))

    def last(self, name):
        found = [p for n, p in self.items if n == name]
        return found[-1] if found else None


def fake_install(cache, repo):
    """A model as huggingface_hub leaves it in its cache."""
    snap = cache / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc123"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "config.json").write_text("{}")
    blobs = snap.parent.parent / "blobs"
    blobs.mkdir(exist_ok=True)
    (blobs / "deadbeef").write_bytes(b"x" * 2048)
    weights = snap / "model.safetensors"
    if weights.is_symlink():
        weights.unlink()
    weights.symlink_to(blobs / "deadbeef")


@pytest.fixture
def bridges(hf_cache):
    fake_install(hf_cache, "sentence-transformers/all-MiniLM-L6-v2")   # rag_cfg's embedding
    made = []
    yield made
    for b in made:
        for w in (b.worker, b.indexer):
            if w is not None:
                if hasattr(w, "close"):
                    w.close()
                w.wait(3000)


def make(bridges, path, rec, *, probe=lambda: None, **kw):
    opened = []
    b = Bridge(path, open_fn=opener(rec), probe_fn=probe, rag_open_fn=rag_opener(rec),
               open_file=opened.append, open_url=opened.append, **kw)
    b.opened = opened
    bridges.append(b)
    p = Pushes(b)
    b.ready()
    b.probe()
    return b, p


def test_doc_mode_sends_without_an_agent_server_and_renders_the_answer(qtbot, bridges, tmp_path):
    rec = {}
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg()), rec)
    assert p.last("setStatus")["state"] == "connected"
    assert p.last("setStatus")["label"].startswith("Classical RAG")
    assert p.last("setBusy")["can_send"] is True and p.last("setBusy")["doc"] is True
    b.send("how do I make a box?")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    vm = p.last("renderTurn")
    assert vm["status"] == "ok" and vm["rag"]["status"] == "done"
    assert vm["rag"]["answer"] == ANSWER["answer"] and vm["rag"]["agentic"] is False
    assert rec["chatbot"]["llm"]["model"] == "m"
    assert rec["chatbot"]["chromadb_path"] == str(tmp_path / "db" / "chromadb")
    assert p.last("setSettings")["active_mode"] == "rag" and p.last("setSettings")["locked"]
    assert "conv" not in rec                            # the agent engine was never opened


def test_agent_mode_still_needs_the_server(bridges, tmp_path):
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg(mode="agent")), {})
    assert p.last("setStatus")["state"] == "offline"
    assert p.last("setBusy")["can_send"] is False and p.last("setBusy")["doc"] is False


def test_doc_mode_refuses_images_and_undo(qtbot, bridges, tmp_path):
    rec = {}
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg(mode="rag_agentic")), rec)
    b.send("what is this", json.dumps(["data:image/png;base64,iVBORw0KGgo="]))
    assert b.worker is None and "only read in the Agentic assistant mode" in p.last("addNote")["text"]
    b.send("question")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert rec["agentic"] is True
    b.command("undo")
    assert not b.busy


def test_open_link_opens_cited_pages_and_web_links_only(qtbot, bridges, tmp_path):
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg()), {})
    b.send("q")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    b.openLink("/docs/smesh/page.html")
    b.openLink("/etc/passwd")
    b.openLink("https://example.org/x")
    b.openLink("file:///etc/passwd")
    assert b.opened == ["/docs/smesh/page.html", "https://example.org/x"]


def test_a_bad_rag_config_stops_the_conversation_start(bridges, tmp_path):
    data = rag_cfg()
    del data["rag"]
    b, p = make(bridges, write_cfg(tmp_path, data), {})
    b.send("q")
    assert b.worker is None and p.last("setStatus")["label"] == "Config error"


def test_build_index_reports_progress_and_the_result(qtbot, bridges, tmp_path):
    calls = []

    def build(path, *, on_line, cancel):
        calls.append(path)
        on_line("indexing GEOM")
        return 0

    b, p = make(bridges, write_cfg(tmp_path, rag_cfg()), {}, build_index_fn=build)
    assert p.last("setSettings")["rag"]["index_exists"] is False
    b.buildIndex()
    qtbot.waitUntil(lambda: b.indexer is None, timeout=3000)
    assert calls == [b.config_path]
    assert p.last("setIndex") == {"building": True, "job": "index", "line": "indexing GEOM"}
    assert p.last("addNote")["text"] == "Documentation index built."
    assert p.last("setSettings")["rag"]["building"] is False


def test_build_index_is_refused_while_a_doc_conversation_is_open(qtbot, bridges, tmp_path):
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg()), {},
                build_index_fn=lambda path, **kw: 0)
    b.send("q")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    b.buildIndex()
    assert b.indexer is None and "before rebuilding its index" in p.last("addNote")["text"]


def test_header_switch_saves_the_mode_and_closes_an_idle_doc_conversation(qtbot, bridges, tmp_path):
    rec = {}
    path = write_cfg(tmp_path, rag_cfg(mode="agent"))
    b, p = make(bridges, path, rec)
    assert p.last("setSettings")["mode_order"] == ["rag", "rag_agentic", "agent"]
    assert p.last("setBusy")["can_switch_mode"] is True
    b.setMode("rag")
    assert json.loads(path.read_text())["gui"]["mode"] == "rag"
    assert p.last("setBusy")["mode"] == "rag" and p.last("setBusy")["doc"] is True
    b.setMode("nonsense")
    assert json.loads(path.read_text())["gui"]["mode"] == "rag"
    b.send("question")
    qtbot.waitUntil(lambda: not b.busy, timeout=3000)
    assert b.worker is not None                        # an idle doc conversation is open
    b.setMode("rag_agentic")                           # closes it: questions carry no memory
    qtbot.waitUntil(lambda: b.worker is None and not b.busy, timeout=3000)
    assert b.mode() == "rag_agentic" and p.last("setSettings")["active_mode"] == "rag_agentic"
    assert "Agentic RAG" in p.last("addNote")["text"]


def test_header_switch_waits_for_an_agent_conversation_to_end(bridges, tmp_path):
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg(mode="agent")), {})
    b.worker, b._worker_mode = object(), "agent"       # an open agent conversation
    assert b.can_switch_mode() is False
    b.setMode("rag")
    assert b.mode() == "agent"
    b.worker = None


# ---- documentation sources (rag.extraction.modules) in the settings -------------
def test_doc_sources_show_each_path_state(tmp_path, monkeypatch):
    docs = tmp_path / "DOCUMENTATION"
    (docs / "share/doc/salome/gui/GEOM").mkdir(parents=True)
    monkeypatch.setenv("DOCUMENTATION_ROOT_DIR", str(docs))
    for var in ("SHAPER_ROOT_DIR", "SMESH_ROOT_DIR", "GEOM_ROOT_DIR"):
        monkeypatch.delenv(var, raising=False)
    data = rag_cfg()
    data["rag"]["extraction"]["modules"] = json.loads(EXAMPLE.read_text())["rag"]["extraction"]["modules"]
    data["rag"]["extraction"]["modules"]["MINE"] = {"user_path": "$NOT_SET_HERE/doc"}
    rows = {r["name"]: r for r in cs.read_settings(write_cfg(tmp_path, data))["doc_sources"]}
    assert list(rows) == ["GEOM", "SHAPER", "SMESH", "MINE"]
    geom = rows["GEOM"]
    assert geom["user_state"]["state"] == "ok" and geom["dev_state"]["state"] == "missing"
    assert geom["cite_user"].endswith("/gui/GEOM") and geom["cite_dev"].endswith("/tui/GEOM")
    assert rows["MINE"]["user_state"] == {"state": "unset", "resolved": str(tmp_path / "$NOT_SET_HERE/doc"),
                                          "vars": ["NOT_SET_HERE"]}
    assert rows["MINE"]["dev_state"]["state"] == "empty"


def test_doc_sources_save_in_order_keeping_unshown_keys_across_a_rename(tmp_path):
    data = rag_cfg()
    data["rag"]["extraction"]["modules"] = {
        "GEOM": {"description": "g", "user_path": "/g", "methodology_path": "/m", "_note": "x",
                 "url_for_sources_citation": "https://d/GEOM"},
        "OLD": {"user_path": "/o"}}
    path = write_cfg(tmp_path, data)
    cs.save_settings(path, {"doc_sources": [
        {"name": "NETGEN", "dev_path": "", "user_path": "$DOC/gui/NETGENPLUGIN",
         "cite_dev": "https://d/tui/N", "cite_user": "https://d/gui/N"},
        {"orig": "GEOM", "name": "GEOMETRY", "description": "geometry", "user_path": "/g2",
         "cite_dev": "https://d/GEOM", "cite_user": "https://d/GEOM"},
        {"name": "", "description": "", "dev_path": "", "user_path": ""}]},   # blank row: dropped
        run_options=False)                              # saved even with a conversation open
    modules = json.loads(path.read_text())["rag"]["extraction"]["modules"]
    assert list(modules) == ["NETGEN", "GEOMETRY"]                   # OLD was removed
    assert modules["NETGEN"] == {"user_path": "$DOC/gui/NETGENPLUGIN",
                                 "url_for_sources_citation": {"dev": "https://d/tui/N",
                                                              "user": "https://d/gui/N"}}
    assert modules["GEOMETRY"] == {"description": "geometry", "user_path": "/g2", "methodology_path": "/m",
                                   "_note": "x", "url_for_sources_citation": "https://d/GEOM"}
    assert cs.read_settings(path)["doc_sources"][1]["json_only"] == ["methodology_path"]


@pytest.mark.parametrize("rows, match", [
    ([{"name": "has space", "user_path": "/x"}], "letters, digits"),
    ([{"name": "_hidden", "user_path": "/x"}], "letters, digits"),
    ([{"name": "A", "user_path": "/x"}, {"name": "A", "user_path": "/y"}], "twice")])
def test_doc_sources_refuse_bad_names_and_leave_the_file_alone(tmp_path, rows, match):
    path = write_cfg(tmp_path, rag_cfg())
    before = path.read_text()
    with pytest.raises(ValueError, match=match):
        cs.save_settings(path, {"doc_sources": rows})
    assert path.read_text() == before


def test_doc_sources_on_a_config_without_rag_start_from_the_example(tmp_path):
    path = write_cfg(tmp_path)
    cs.save_settings(path, {"doc_sources": [{"name": "GEOM", "user_path": "/g"}]})
    data = json.loads(path.read_text())
    assert data["rag"]["extraction"]["modules"] == {"GEOM": {"user_path": "/g"}}
    assert data["rag"]["chatbot"] == rb.default_rag()["chatbot"]


# ---- local models (raglib's download_models.py) ----------------------------------
from salome_agent_gui import rag_models as rm  # noqa: E402


def test_model_status_reads_the_hub_cache_without_torch(hf_cache, tmp_path):
    assert rm.hub_cache() == hf_cache
    assert rm.status("all-MiniLM-L6-v2")["state"] == "missing"
    assert rm.status("all-MiniLM-L6-v2")["repo"] == "sentence-transformers/all-MiniLM-L6-v2"
    fake_install(hf_cache, "sentence-transformers/all-MiniLM-L6-v2")
    st = rm.status("all-MiniLM-L6-v2")
    assert st["state"] == "installed" and st["size"] == "2 KB"    # links followed
    (hf_cache / "models--sentence-transformers--all-MiniLM-L6-v2" / "blobs" / "deadbeef").unlink()
    assert rm.status("all-MiniLM-L6-v2")["state"] == "missing"    # a dangling link is no weights
    fake_install(hf_cache, "sentence-transformers/all-MiniLM-L6-v2")
    # a reranker name is a repository as is; a half-downloaded one (no weights) is missing
    snap = hf_cache / "models--BAAI--bge-reranker-v2-m3" / "snapshots" / "r1"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    assert rm.status("BAAI/bge-reranker-v2-m3", "cross_encoder")["state"] == "missing"
    assert rm.status(str(tmp_path), "embedding")["state"] == "local"
    assert rm.status("")["state"] == "none"


def test_models_view_follows_the_config_and_the_parked_reranker(hf_cache):
    data = json.loads(EXAMPLE.read_text())
    v = rm.models_view(data)
    assert v["embedding"]["model"] == "all-MiniLM-L6-v2" and v["embedding"]["status"]["state"] == "missing"
    assert v["reranker"] == {"model": "answerdotai/answerai-colbert-small-v1", "type": "late_interaction",
                             "enabled": True, "status": v["reranker"]["status"]}
    assert [c["model"] for c in v["choices"]["reranker"]] == [
        "answerdotai/answerai-colbert-small-v1", "BAAI/bge-reranker-v2-m3"]
    assert rm.missing(data) == [("embedding", "embedding", "all-MiniLM-L6-v2"),
                                ("reranker", "late_interaction", "answerdotai/answerai-colbert-small-v1")]
    data["rag"]["chatbot"]["_reranker_off"] = {"model": "BAAI/bge-reranker-v2-m3", "type": "cross_encoder"}
    data["rag"]["chatbot"]["reranker"] = None
    v = rm.models_view(data)
    assert v["reranker"]["enabled"] is False and v["reranker"]["type"] == "cross_encoder"
    assert [r for r, _, _ in rm.missing(data)] == ["embedding"]          # an off reranker is not needed
    assert len(rm.missing(data, only_enabled=False)) == 2
    data["rag"]["chatbot"]["embedding"]["type"] = "api"
    assert rm.models_view(data)["embedding"]["status"]["state"] == "api" and rm.missing(data) == []


def test_saving_models_keeps_both_embeddings_identical_and_respects_a_parked_reranker(tmp_path):
    path = write_cfg(tmp_path, json.loads(EXAMPLE.read_text()))
    cs.save_settings(path, {"rag_models": {"embedding_model": "BAAI/bge-small-en-v1.5",
                                           "reranker_model": "BAAI/bge-reranker-v2-m3",
                                           "reranker_type": "cross_encoder"}})
    rag = json.loads(path.read_text())["rag"]
    strip = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}  # noqa: E731
    assert strip(rag["chatbot"]["embedding"]) == strip(rag["extraction"]["embedding"])
    assert rag["chatbot"]["embedding"]["model"] == "BAAI/bge-small-en-v1.5"
    assert rag["chatbot"]["reranker"] == {"model": "BAAI/bge-reranker-v2-m3", "type": "cross_encoder"}
    cs.save_settings(path, {"rag_options": {"reranker": False},
                            "rag_models": {"reranker_model": "answerdotai/answerai-colbert-small-v1",
                                           "reranker_type": "late_interaction"}})
    chatbot = json.loads(path.read_text())["rag"]["chatbot"]
    assert chatbot["reranker"] is None
    assert chatbot["_reranker_off"]["model"] == "answerdotai/answerai-colbert-small-v1"
    rb.check(json.loads(path.read_text()), path)                     # raglib still accepts it
    cs.save_settings(path, {"rag_models": {"embedding_model": "x"}}, run_options=False)
    assert json.loads(path.read_text())["rag"]["chatbot"]["embedding"]["model"] != "x"


def test_doc_conversation_names_the_missing_model_before_raglib_fails(bridges, hf_cache, tmp_path):
    import shutil
    shutil.rmtree(hf_cache)
    b, p = make(bridges, write_cfg(tmp_path, rag_cfg()), {})
    b.send("question")
    assert b.worker is None
    assert "not installed: embedding model all-MiniLM-L6-v2" in p.last("setStatus")["detail"]


def test_download_runs_in_the_background_job_slot_and_refreshes_the_states(qtbot, bridges, hf_cache, tmp_path):
    import shutil
    shutil.rmtree(hf_cache)
    got = {}

    def download(items, on_line, cancel):
        got["items"] = list(items)
        on_line("Downloading the embedding model all-MiniLM-L6-v2…")
        fake_install(hf_cache, "sentence-transformers/all-MiniLM-L6-v2")
        return 0

    b, p = make(bridges, write_cfg(tmp_path, rag_cfg()), {}, download_fn=download)
    assert p.last("setSettings")["rag_models"]["embedding"]["status"]["state"] == "missing"
    b.downloadModels("all")
    assert b.indexer is not None and p.last("setSettings")["rag"]["job"] == "models"
    b.buildIndex()                                       # one background job at a time
    qtbot.waitUntil(lambda: b.indexer is None, timeout=3000)
    assert got["items"] == [("embedding", "embedding", "all-MiniLM-L6-v2")]
    assert p.last("setSettings")["rag_models"]["embedding"]["status"]["state"] == "installed"
    assert p.last("setSettings")["rag"]["job"] == "" and "Models downloaded." in p.last("addNote")["text"]
    b.downloadModels("embedding")                        # nothing left to fetch
    assert b.indexer is None and "already installed" in p.last("addNote")["text"]


def test_index_build_fetches_a_missing_embedding_model_first(tmp_path, monkeypatch, hf_cache):
    calls = []
    monkeypatch.setattr(rm, "download", lambda items, on_line, cancel: calls.append(list(items)) or 7)
    monkeypatch.setenv("FAKE_ROOT", str(tmp_path))
    path = write_cfg(tmp_path, rag_cfg())
    assert rb.build_index(path, on_line=lambda line: None) == 7
    assert calls == [[("embedding", "embedding", "all-MiniLM-L6-v2")]]


def test_download_command_runs_this_module():
    assert rm.download_command("cross_encoder", "BAAI/bge-reranker-v2-m3")[-4:] == [
        "-m", "salome_agent_gui.rag_models", "cross_encoder", "BAAI/bge-reranker-v2-m3"]
    assert rm.main(["nope", "x"]) == 2
