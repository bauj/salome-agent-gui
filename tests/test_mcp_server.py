# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""salome-agent-mcp: SALOME as tools for Claude Desktop / Claude Code."""
import asyncio
import base64
import json
import sys
import textwrap

import pytest

pytest.importorskip("mcp")

from salome_agent_gui import mcp_server as ms  # noqa: E402

BOX = {"fn": "MakeBoxDXDYDZ", "out_vars": ["box_1"], "publish": ["box_1"],
       "args": [{"kind": "literal", "value": v} for v in (10, 20, 30)]}
CYL = {"fn": "MakeCylinderRH", "out_vars": ["cyl_1"], "publish": ["cyl_1"],
       "args": [{"kind": "literal", "value": 3}, {"kind": "literal", "value": 40}]}
CUT = {"fn": "MakeCutList", "out_vars": ["cut_1"], "publish": ["cut_1"],
       "args": [{"kind": "ref", "value": "box_1"},
                {"kind": "list", "value": [{"kind": "ref", "value": "cyl_1"}]}]}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeClient:
    mode, name_prefix = "gui", "sa_abc_"

    def __init__(self, replies=None, fail=None):
        self.replies = dict(replies or {})
        self.fail = fail
        self.calls = []
        self.closed = False

    def call_tool(self, name, args, module=None):
        self.calls.append((module, name, args))
        if self.fail:
            raise self.fail
        return self.replies.get(name, {"ok": False, "error": f"unknown tool {name!r}"})

    def view_image(self):
        return {"ok": True, "image": "data:image/png;base64," + base64.b64encode(PNG).decode()}

    def list_study(self):
        return {"objects": [{"name": "sa_abc_box_1", "type": ""}]}

    def display(self, names):
        return {"ok": True, "shown": names}

    def hide(self, names):
        return {"ok": True, "hidden": names}

    def forget(self, names):
        return {"ok": True, "removed": names}

    def close(self):
        self.closed = True


def make(tmp_path, client=None, docs=None):
    opened = []

    def connect(run_id, run_dir):
        opened.append((run_id, run_dir))
        return client

    session = ms.SalomeSession(connect=connect, runs_dir=tmp_path / "runs")
    server = ms.build_server(session, docs or ms.DocSearch(loader=lambda path: FAKE_DOCS))
    return server, session, opened


def call(server, name, args=None):
    """As a client sees it: a ToolError becomes an is_error result (the protocol
    layer does that; test_over_stdio checks it for real)."""
    from types import SimpleNamespace

    from mcp.server.mcpserver.exceptions import ToolError

    try:
        return asyncio.run(server.call_tool(name, args or {}))
    except ToolError as e:
        return SimpleNamespace(is_error=True, content=[SimpleNamespace(type="text", text=str(e))])


def text(result):
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


FAKE_DOCS = {
    "search": lambda q, n: [{"filename": "box.html", "title": "Box", "module": "GEOM",
                             "doc_category": "user", "section_text": f"about {q}",
                             "url": "https://docs.salome-platform.org/latest/gui/GEOM/box.html"}],
    "read": lambda path, cat, max_chars: f"page {path} ({cat}, {max_chars})",
    "pages": {"box.html": {"filename": "box.html", "filepath": "/doc/box.html", "title": "Box",
                           "doc_category": "user"}},
    "max_chars": 8000,
}


# ---- tools and the guide ------------------------------------------------------
def test_the_tool_list_is_small_and_marks_what_changes_the_study(tmp_path):
    server, _, _ = make(tmp_path)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == {
        "salome_status", "list_cad_tools", "describe_cad_tool", "call_cad_tool", "calc",
        "view_salome", "list_study", "show_objects", "hide_objects", "delete_objects",
        "save_salome_script", "release_salome", "search_salome_docs", "read_salome_doc_page"}
    assert tools["search_salome_docs"].annotations.read_only_hint is True
    assert tools["delete_objects"].annotations.destructive_hint is True
    assert tools["call_cad_tool"].annotations.read_only_hint is False
    assert "SHAPER for CAD" in server.instructions


@pytest.mark.parametrize("module", ms.MODULES)
def test_each_module_guide_says_how_this_session_differs_and_lists_every_tool(module, tmp_path):
    server, _, opened = make(tmp_path)
    guide = text(call(server, "list_cad_tools", {"module": module}))
    assert guide.startswith("# How this session differs") and "no finish_stage" in guide
    for tool in ms._catalogue(module):
        assert f"- {tool['name']}: " in guide
    assert "{" + "catalogue}" not in guide and "{verify}" not in guide
    assert opened == []                                  # listing needs no SALOME


def test_describe_gives_the_schema_and_names_a_wrong_tool(tmp_path):
    server, _, _ = make(tmp_path)
    d = json.loads(text(call(server, "describe_cad_tool", {"module": "geom", "name": "make_box"})))
    assert d["name"] == "make_box" and d["parameters"]["type"] == "object"
    r = call(server, "describe_cad_tool", {"module": "geom", "name": "nope"})
    assert r.is_error and "list_cad_tools('geom')" in text(r)
    r = call(server, "list_cad_tools", {"module": "paraview"})
    assert r.is_error and "shaper, geom, smesh" in text(r)


# ---- the SALOME session ------------------------------------------------------
def test_calls_open_one_held_session_and_show_what_the_engine_model_sees(tmp_path):
    client = FakeClient({"make_box": {"ok": True, "records": [BOX], "result_shape": "box_1",
                                      "shape_info": {"bbox": [0, 0, 0, 10, 20, 30]}}})
    server, session, opened = make(tmp_path, client)
    out = text(call(server, "call_cad_tool", {"module": "geom", "name": "make_box",
                                              "arguments": {"dx": 10, "dy": 20, "dz": 30}}))
    assert "records" not in out and "box_1" in out and "MakeBoxDXDYDZ" not in out
    call(server, "call_cad_tool", {"module": "geom", "name": "make_box", "arguments": {"dx": 1}})
    assert len(opened) == 1 and (tmp_path / "runs" / opened[0][0]).is_dir()
    assert client.calls[0] == ("geom", "make_box", {"dx": 10, "dy": 20, "dz": 30})
    assert len(session.calls) == 2
    status = json.loads(text(call(server, "salome_status")))
    assert status["salome"]["session_open"] and status["salome"]["calls_recorded"] == 2


def test_a_failed_call_is_a_tool_error_and_records_nothing(tmp_path):
    server, session, _ = make(tmp_path, FakeClient())
    r = call(server, "call_cad_tool", {"module": "shaper", "name": "nope", "arguments": {}})
    assert r.is_error and "unknown tool 'nope'" in text(r)
    assert session.calls == []


def test_a_lost_server_is_reported_and_never_reopened_silently(tmp_path):
    from salome_agent.executor_client import SessionDied

    client = FakeClient(fail=SessionDied("server socket closed"))
    server, session, opened = make(tmp_path, client)
    r = call(server, "call_cad_tool", {"module": "geom", "name": "make_box", "arguments": {}})
    assert r.is_error and "can no longer refer to them by name" in text(r)
    assert client.closed and session.client is None


def test_no_agent_server_says_how_to_start_it(tmp_path, monkeypatch):
    from salome_agent import server_conn

    def unavailable(*a, **kw):
        raise server_conn.ServerUnavailable("No SALOME agent server running.")

    monkeypatch.setattr(server_conn, "connect", unavailable)
    session = ms.SalomeSession(runs_dir=tmp_path)
    server = ms.build_server(session, ms.DocSearch(loader=lambda p: FAKE_DOCS))
    r = call(server, "list_study")
    assert r.is_error and "Tools > Plugins > AI tools > MCP server" in text(r)
    call(server, "list_study")
    assert list(tmp_path.iterdir()) == []              # no empty run folder per failed try


def test_a_busy_server_says_who_holds_it_not_how_to_start_it(tmp_path, monkeypatch):
    from salome_agent import server_conn

    def busy(*a, **kw):
        raise server_conn.ServerUnavailable("another agent run is in progress. Start it ...")

    monkeypatch.setattr(server_conn, "connect", busy)
    server = ms.build_server(ms.SalomeSession(runs_dir=tmp_path),
                             ms.DocSearch(loader=lambda p: FAKE_DOCS))
    r = call(server, "view_salome")
    assert r.is_error and "busy" in text(r) and "New conversation" in text(r)
    assert "Start it" not in text(r)


def test_release_hands_the_server_back(tmp_path):
    client = FakeClient({"make_box": {"ok": True, "records": [BOX]}})
    server, session, opened = make(tmp_path, client)
    assert "No SALOME session" in text(call(server, "release_salome"))
    call(server, "call_cad_tool", {"module": "geom", "name": "make_box", "arguments": {}})
    assert "Released" in text(call(server, "release_salome"))
    assert client.closed and session.client is None
    assert len(session.calls) == 1                    # the script can still be saved
    call(server, "list_study")
    assert session.calls == []                        # a new session starts afresh
    assert len(opened) == 2 and opened[0][0] != opened[1][0]   # a new session, a new run id


def test_a_session_left_idle_is_released_and_the_next_call_says_so(tmp_path):
    now, opened, client = [0.0], [], FakeClient()

    def connect(run_id, run_dir):
        opened.append(run_id)
        return client

    session = ms.SalomeSession(connect=connect, runs_dir=tmp_path, idle_release_s=600,
                               clock=lambda: now[0])
    pool = ms.SessionPool(single=session, reap_every=0)
    server = ms.build_server(pool, ms.DocSearch(loader=lambda p: FAKE_DOCS))
    call(server, "list_study")
    now[0] = 599
    pool.reap()
    assert not client.closed
    call(server, "list_study")                       # a call restarts the idle clock
    now[0] = 599 + 601
    pool.reap()
    assert client.closed and session.client is None
    r = call(server, "list_study")
    assert r.is_error and "released after 10 minutes" in text(r)
    assert not call(server, "list_study").is_error and len(opened) == 2


def test_each_client_gets_its_own_session(tmp_path):
    pool = ms.SessionPool(factory=lambda: ms.SalomeSession(runs_dir=tmp_path), reap_every=0)
    assert pool.get("a") is pool.get("a")
    assert pool.get("a") is not pool.get("b") and pool.get(None) is not pool.get("a")
    single = ms.SalomeSession(runs_dir=tmp_path)
    assert ms.SessionPool(single=single, reap_every=0).get("x") is single


def test_the_view_comes_back_as_an_image(tmp_path):
    server, _, _ = make(tmp_path, FakeClient())
    r = call(server, "view_salome")
    image = next(c for c in r.content if c.type == "image")
    assert image.mime_type == "image/png" and base64.b64decode(image.data) == PNG


# ---- result.py ------------------------------------------------------------------
def _built(tmp_path):
    client = FakeClient({"make_box": {"ok": True, "records": [BOX]},
                         "make_cylinder": {"ok": True, "records": [CYL]},
                         "cut": {"ok": True, "records": [CUT]}})
    server, session, _ = make(tmp_path, client)
    for name in ("make_box", "make_cylinder", "cut"):
        call(server, "call_cad_tool", {"module": "geom", "name": name, "arguments": {}})
    return server, session


def test_the_script_rebuilds_the_session_like_result_py(tmp_path):
    server, session = _built(tmp_path)
    out = text(call(server, "save_salome_script"))
    path = tmp_path / "runs" / session.run_id / "result.py"
    assert out.startswith(f"Saved {path}") and path.is_file()
    script = path.read_text()
    assert "geompy = geomBuilder.New()" in script
    assert "box_1 = geompy.MakeBoxDXDYDZ(10, 20, 30)" in script
    assert "cut_1 = geompy.MakeCutList(box_1, [cyl_1])" in script
    compile(script, "result.py", "exec")


def test_deleted_objects_leave_the_script_unless_a_kept_one_needs_them(tmp_path):
    server, session = _built(tmp_path)
    call(server, "delete_objects", {"names": ["cut_1"]})
    script = session.script()
    assert "MakeCutList" not in script and "MakeBoxDXDYDZ" in script and "MakeCylinderRH" in script
    server, session = _built(tmp_path)
    call(server, "delete_objects", {"names": ["box_1"]})
    assert "MakeBoxDXDYDZ" in session.script()             # cut_1 is built from it


def test_no_script_before_anything_is_built_and_paths_must_be_absolute(tmp_path):
    server, _, _ = make(tmp_path, FakeClient())
    r = call(server, "save_salome_script")
    assert r.is_error and "nothing built" in text(r)
    server, _ = _built(tmp_path)
    r = call(server, "save_salome_script", {"path": "rel/result.py"})
    assert r.is_error and "absolute path" in text(r)
    target = tmp_path / "out" / "part.py"
    call(server, "save_salome_script", {"path": str(target)})
    assert "MakeCutList" in target.read_text()


def test_the_script_is_a_new_py_file_or_one_this_session_wrote(tmp_path):
    server, _ = _built(tmp_path)
    r = call(server, "save_salome_script", {"path": str(tmp_path / "notes.txt")})
    assert r.is_error and ".py" in text(r)
    taken = tmp_path / "taken.py"
    taken.write_text("mine")
    r = call(server, "save_salome_script", {"path": str(taken)})
    assert r.is_error and "already exists" in text(r) and taken.read_text() == "mine"
    target = tmp_path / "part.py"
    call(server, "save_salome_script", {"path": str(target)})
    assert not call(server, "save_salome_script", {"path": str(target)}).is_error
    assert not call(server, "save_salome_script").is_error          # the session folder
    assert not call(server, "save_salome_script").is_error


def test_calc_runs_the_engine_calculator(tmp_path):
    server, _, _ = make(tmp_path)
    assert text(call(server, "calc", {"code": "round(hypot(3, 4), 3)"})).strip().endswith("5.0")


# ---- documentation -------------------------------------------------------------
def test_doc_search_returns_sections_with_filename_and_online_page(tmp_path):
    server, _, _ = make(tmp_path)
    out = text(call(server, "search_salome_docs", {"query": "box", "top_n": 99}))
    assert out.startswith("[1] Box | GEOM/user") and "filename: box.html" in out
    assert "online: https://docs.salome-platform.org/latest/gui/GEOM/box.html" in out
    assert "about box" in out
    page = text(call(server, "read_salome_doc_page", {"filename": "box.html"}))
    assert "page /doc/box.html (user, 8000)" in page
    r = call(server, "read_salome_doc_page", {"filename": "other.html"})
    assert r.is_error and "search_salome_docs returned" in text(r)


def test_doc_search_without_rag_section_or_models_says_what_to_do(tmp_path, hf_cache):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"llm": {}}))
    r = call(ms.build_server(ms.SalomeSession(runs_dir=tmp_path), ms.DocSearch(cfg)),
             "search_salome_docs", {"query": "box"})
    assert r.is_error and "no rag section" in text(r)
    example = json.loads((ms.Path(ms.__file__).parent / "config.example.json").read_text())
    cfg.write_text(json.dumps(example))
    r = call(ms.build_server(ms.SalomeSession(runs_dir=tmp_path), ms.DocSearch(cfg)),
             "search_salome_docs", {"query": "box"})
    assert r.is_error and "not installed: all-MiniLM-L6-v2" in text(r)
    assert "Settings > Local models" in text(r)
    cfg.write_text("{broken json")
    r = call(ms.build_server(ms.SalomeSession(runs_dir=tmp_path), ms.DocSearch(cfg)),
             "search_salome_docs", {"query": "box"})
    assert r.is_error and str(cfg) in text(r)
    example["rag"]["chatbot"]["embedding_model"] = ""
    example["rag"]["chatbot"]["reranker_enabled"] = False
    example["rag"]["chatbot"][" null_bad "] = 1
    cfg.write_text(json.dumps(example))
    r = call(ms.build_server(ms.SalomeSession(runs_dir=tmp_path), ms.DocSearch(cfg)),
             "search_salome_docs", {"query": "box"})
    assert r.is_error


# ---- over stdio, as Claude Desktop runs it ----------------------------------
SERVER_SCRIPT = textwrap.dedent("""
    import os, sys
    from salome_agent_gui import mcp_server as ms

    def loader(path):
        print("DEBUG : load vector store ...")          # what raglib does
        os.write(1, b"raw bytes on fd 1\\n")              # and C code might
        return {"search": lambda q, n: [{"filename": "a.html", "title": "A", "module": "SMESH",
                                         "doc_category": "dev", "section_text": "text"}],
                "read": None, "pages": {}, "max_chars": 1}

    ms.serve_stdio(ms.build_server(docs=ms.DocSearch(loader=loader)))
""")


def test_over_stdio_stray_output_never_reaches_the_protocol(tmp_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    script = tmp_path / "serve.py"
    script.write_text(SERVER_SCRIPT)

    async def run():
        params = StdioServerParameters(command=sys.executable, args=[str(script)])
        with open(tmp_path / "stderr.txt", "w") as err:
            async with stdio_client(params, errlog=err) as (read, write):
                async with ClientSession(read, write) as client:
                    init = await client.initialize()
                    tools = await client.list_tools()
                    found = await client.call_tool("search_salome_docs", {"query": "mesh"})
                    return init, tools, found

    init, tools, found = asyncio.run(run())
    assert init.server_info.name == "salome-agent" and "SALOME tools" in init.instructions
    assert len(tools.tools) == 14
    assert not found.is_error and found.content[0].text.startswith("[1] A | SMESH/dev")
    err = (tmp_path / "stderr.txt").read_text()
    assert "DEBUG : load vector store" in err and "raw bytes on fd 1" in err


# ---- Claude Desktop's config entry -----------------------------------------------
def test_desktop_entry_goes_through_wsl_and_prefers_the_launcher(tmp_path):
    launcher = tmp_path / "bin" / "salome-agent-gui.sh"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/bash\n")
    env = {"WSL_DISTRO_NAME": "Ubuntu-24.04", "SALOME_AGENT_GUI_ROOT_DIR": str(tmp_path)}
    assert ms.desktop_entry(environ=env) == {
        "command": "wsl.exe", "args": ["-d", "Ubuntu-24.04", "-e", str(launcher), "--mcp"]}
    entry = ms.desktop_entry(config="/c/x.json", environ={}, argv0="/venv/bin/salome-agent-mcp")
    assert entry == {"command": "/venv/bin/salome-agent-mcp", "args": ["--config", "/c/x.json"]}


def test_desktop_config_prints_a_mergeable_json(capsys):
    assert ms.main(["--desktop-config"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert list(printed["mcpServers"]) == ["salome-agent"]


def test_doc_search_loads_the_index_again_once_it_is_rebuilt(tmp_path):
    import os

    index = tmp_path / "page_index.json"
    index.write_text("[]")
    loads = []

    def loader(path):
        loads.append(path)
        return dict(FAKE_DOCS, watch=[str(index)])

    docs = ms.DocSearch(tmp_path / "c.json", loader=loader)
    docs.search("mesh")
    docs.search("mesh")
    assert len(loads) == 1
    st = index.stat()
    os.utime(index, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    docs.search("mesh")
    assert len(loads) == 2


def test_online_links_come_from_the_module_citation_and_the_page_path(tmp_path):
    roots = ms.online_roots({"modules": {
        "GEOM": {"user_path": str(tmp_path / "gui/GEOM"), "dev_path": str(tmp_path / "tui/GEOM"),
                 "url_for_sources_citation": {"user": "https://d/gui/GEOM/", "dev": "https://d/tui/GEOM"}},
        "MINE": {"user_path": "/x", "url_for_sources_citation": "https://mine"}, "_c": "skip"}})
    assert roots[("MINE", "user")] == ("/x", "https://mine")
    docs = ms.DocSearch(loader=lambda p: dict(FAKE_DOCS, online=roots))
    docs._get()
    page = {"module": "GEOM", "doc_category": "user", "filepath": str(tmp_path / "gui/GEOM/sub/box.html")}
    assert docs._online(page) == "https://d/gui/GEOM/sub/box.html"
    assert docs._online(dict(page, filepath="/elsewhere/box.html")) == ""
    assert docs._online(dict(page, url="https://given")) == "https://given"


# ---- over HTTP, as Tools > Plugins > AI tools > MCP server runs it ---------------
HTTP_SCRIPT = textwrap.dedent("""
    import sys
    from salome_agent_gui import mcp_server as ms

    def loader(path):
        return {"search": lambda q, n: [{"filename": "a.html", "title": "A", "module": "SMESH",
                                         "doc_category": "dev", "section_text": "text"}],
                "read": None, "pages": {}, "max_chars": 1}

    ms.serve_http(ms.build_server(docs=ms.DocSearch(loader=loader)), int(sys.argv[1]), sys.argv[2])
""")


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_over_http_the_server_waits_for_clients_with_the_token(tmp_path):
    import subprocess
    import time

    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    script = tmp_path / "serve_http.py"
    script.write_text(HTTP_SCRIPT)
    port, token = _free_port(), "s3cret-token-0123456789"
    url = ms.http_url(port)
    with open(tmp_path / "stderr.txt", "w") as err:
        proc = subprocess.Popen([sys.executable, str(script), str(port), token], stderr=err)
    try:
        deadline = time.time() + 30
        while True:
            try:
                r = httpx2.post(url, json={})
                break
            except httpx2.ConnectError:
                assert proc.poll() is None and time.time() < deadline
                time.sleep(0.2)
        assert r.status_code == 401                           # no token: refused

        async def run(headers):
            async with httpx2.AsyncClient(headers=headers) as http:
                async with streamable_http_client(url, http_client=http) as streams:
                    async with ClientSession(*streams[:2]) as client:
                        init = await client.initialize()
                        found = await client.call_tool("search_salome_docs", {"query": "mesh"})
                        return init, found

        init, found = asyncio.run(run({"Authorization": f"Bearer {token}"}))
        assert init.server_info.name == "salome-agent"
        assert not found.is_error and found.content[0].text.startswith("[1] A | SMESH/dev")
        bad = httpx2.post(url, json={}, headers={"Authorization": "Bearer wrong"})
        assert bad.status_code == 401
    finally:
        proc.terminate()
        proc.wait(10)
    err = (tmp_path / "stderr.txt").read_text()
    assert f"claude mcp add --scope user --transport http salome-agent {url}" in err
    assert f"salome-agent {url}" in err.split("agy mcp add", 1)[1]


HTTP_SESSIONS_SCRIPT = textwrap.dedent("""
    import sys
    from salome_agent_gui import mcp_server as ms

    class Client:
        mode, name_prefix = "gui", ""

        def __init__(self, run_id):
            self.run_id = run_id

        def list_study(self):
            return {"objects": [{"name": self.run_id}]}

        def close(self):
            pass

    def factory():
        return ms.SalomeSession(connect=lambda run_id, run_dir: Client(run_id),
                                runs_dir=sys.argv[3])

    ms.serve_http(ms.build_server(ms.SessionPool(factory=factory),
                                  ms.DocSearch(loader=lambda p: None)),
                  int(sys.argv[1]), sys.argv[2])
""")


def test_over_http_each_client_has_its_own_salome_session(tmp_path):
    import subprocess
    import time

    import httpx2
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    script = tmp_path / "serve_http.py"
    script.write_text(HTTP_SESSIONS_SCRIPT)
    port, token = _free_port(), "s3cret-token-0123456789"
    url = ms.http_url(port)
    proc = subprocess.Popen([sys.executable, str(script), str(port), token, str(tmp_path / "runs")],
                            stderr=subprocess.DEVNULL)
    headers = {"Authorization": f"Bearer {token}"}

    async def client_runs():
        async with httpx2.AsyncClient(headers=headers) as http:
            async with streamable_http_client(url, http_client=http) as streams:
                async with ClientSession(*streams[:2]) as client:
                    await client.initialize()
                    runs = []
                    for _ in range(2):
                        r = await client.call_tool("list_study", {})
                        runs.append(json.loads(r.content[0].text)["objects"][0]["name"])
                    return runs

    try:
        deadline = time.time() + 30
        while True:
            try:
                httpx2.post(url, json={})
                break
            except httpx2.ConnectError:
                assert proc.poll() is None and time.time() < deadline
                time.sleep(0.2)
        first, second = asyncio.run(client_runs()), asyncio.run(client_runs())
    finally:
        proc.terminate()
        proc.wait(10)
    assert first[0] == first[1] and second[0] == second[1]      # one session per client
    assert first[0] != second[0]


def test_http_settings_keep_the_token_and_take_a_new_port(tmp_path):
    p = tmp_path / "m.json"
    first = ms.http_settings(p)
    assert first["port"] == ms.DEFAULT_PORT
    assert ms.http_settings(p) == first
    moved = ms.http_settings(p, port=5001)
    assert moved == {"port": 5001, "token": first["token"]}
    assert ms.http_settings(p) == moved


def test_the_http_server_stops_with_salome():
    import os
    exits = []
    t = ms.watch_parent(2 ** 22 + 12345, interval=0.01, exit_fn=exits.append)
    t.join(2)
    assert exits == [0]
    alive = ms.watch_parent(os.getpid(), interval=0.01, exit_fn=exits.append)
    alive.join(0.1)
    assert exits == [0] and alive.is_alive()


def test_the_token_file_is_made_private_even_if_it_was_not(tmp_path):
    p = tmp_path / "m.json"
    ms.http_settings(p)
    p.chmod(0o644)
    ms.http_settings(p)
    assert p.stat().st_mode & 0o777 == 0o600
    p.write_text("{}")
    p.chmod(0o644)
    ms.http_settings(p)                                  # rewritten
    assert p.stat().st_mode & 0o777 == 0o600


def test_check_reports_a_broken_catalogue_and_still_shows_the_docs(tmp_path, monkeypatch, capsys):
    def broken(module):
        raise ImportError(f"no executor.{module}")

    monkeypatch.setattr(ms, "_catalogue", broken)
    monkeypatch.setattr(ms.DocSearch, "_get", lambda self: FAKE_DOCS)
    assert ms.check(str(tmp_path / "c.json")) == 0
    err = capsys.readouterr().err
    assert "geom: tools not available (ImportError: no executor.geom)" in err
    assert "documentation search: ready" in err
