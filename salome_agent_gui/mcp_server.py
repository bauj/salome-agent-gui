# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
"""SALOME for Claude Desktop and Claude Code, as an MCP server (stdio).

Claude holds the conversation and does the planning; this server gives it the
same tools the SALOME Agent's own model uses, through the agent server SALOME
runs (Tools > Plugins > AI tools > MCP server, or the headless server):

- the GEOM, SHAPER and SMESH tool catalogues (listed, described, called by name:
  132 tools would weigh ~18k tokens on every conversation if all were exposed),
  each module with the guide the engine's specialist reads;
- calc, the engine's locked-down arithmetic tool;
- a look at the 3D view, the study, show/hide/delete;
- the calls replayed as a standalone result.py, as the agent writes one;
- the documentation index of the RAG modes, searched without any LLM: Claude
  reads the passages and pages itself.

It talks to the agent server like an open chat-window conversation does: one
held session, so the chat window's Agentic assistant waits while Claude builds
(release_salome hands it back). Nothing here calls a model: Claude does, under
the user's own Claude plan.

Run: salome-agent-mcp [--config CONFIG] [--check]       on stdio (the client starts it)
     salome-agent-mcp --http [--port PORT] [--config CONFIG]
        a server on 127.0.0.1 that Claude Code, Gemini CLI or any MCP client
        connects to (Tools > Plugins > AI tools > MCP server starts this one);
        the port and the bearer token are kept in ~/.local/share/salome-agent/mcp-http.json
"""
import argparse
import contextlib
import copy
import hmac
import json
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path

MODULES = ("shaper", "geom", "smesh")
RUNS_DIR = Path.home() / ".local" / "share" / "salome-agent" / "mcp"
# --http: port and token, shared with the SALOME menu's dialog (sagui_launcher)
HTTP_FILE = Path.home() / ".local" / "share" / "salome-agent" / "mcp-http.json"
DEFAULT_PORT = 47801
SERVER_NAME = "salome-agent"

INSTRUCTIONS = """\
SALOME tools: build and mesh geometry in the user's running SALOME session, and
search the SALOME documentation.

Building:
1. Choose the module: SHAPER for CAD unless the user asks for GEOM; SMESH to mesh
   a shape built before.
2. Call list_cad_tools(module) once per module per conversation and read its
   guide: it says how the tools work together (sketches, booleans, meshing).
3. Call describe_cad_tool before the first use of a tool, then call_cad_tool.
   Read every reply: sizes and bounding boxes, rejected constraints, hints.
4. Lengths are millimetres, angles degrees. Use calc for any arithmetic.
5. view_salome shows the 3D view: look at the result when its shape matters.
6. save_salome_script writes a standalone Python script that rebuilds what was
   built; offer it at the end.
7. When done building, call release_salome so the SALOME chat window can use
   the agent server again.

Documentation: search_salome_docs, then read_salome_doc_page for a page worth
reading in full. Answer from what they return and cite the pages."""

ADAPTATION = """\
# How this session differs from the guide below
The guide was written for SALOME Agent's own model, which builds one planned
stage at a time. Here:
- Every tool of the module is available: call it with call_cad_tool(module,
  name, arguments); describe_cad_tool(module, name) gives its parameters.
  There is no load_tools.
- There is no finish_stage and no stage: build what the user asks, check it
  (measure, view_salome), and say what you built.
- calc is the separate `calc` tool.
- Objects built in earlier calls of this session are referenced by the names
  the replies gave them.

"""


class SalomeError(Exception):
    """A problem worth telling Claude as is."""


BUSY = ("The SALOME agent server is busy: the SALOME chat window has an Agentic "
        "assistant conversation open (or another client holds the server). Ask the user to "
        "end it there (New conversation) or switch the window to a documentation mode, "
        "then try again.")


def _unavailable(message: str) -> str:
    if "in progress" in message:
        return BUSY
    return (f"{message}\nAsk the user to start SALOME and open Tools > Plugins > "
            "AI tools > MCP server (or SALOME agent): that starts the agent server.")


def _strip_hidden(result: dict) -> dict:
    return {k: v for k, v in result.items() if k not in ("records", "id")}


# ---- the SALOME side ------------------------------------------------------
class SalomeSession:
    """One held session on the agent server, opened on first use. A new
    session resets the server's name bindings, so it is kept for as long as
    Claude builds; release() ends it."""

    def __init__(self, connect=None, runs_dir: Path = RUNS_DIR):
        self._connect = connect
        self._runs_dir = Path(runs_dir)
        self._lock = threading.RLock()
        self.client = None
        self.run_id = None
        self.calls: list[dict] = []          # {module, tool, args, records}
        self.deleted: set[str] = set()

    # connection
    def _open(self):
        if self._connect is None:
            from salome_agent import server_conn

            def connect(run_id, run_dir):
                try:
                    return server_conn.connect(run_id, hold=True, run_dir=run_dir)
                except server_conn.ServerUnavailable as e:
                    raise SalomeError(_unavailable(str(e))) from e
            self._connect = connect
        run_id = uuid.uuid4().hex[:12]
        run_dir = self._runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        self.client = self._connect(run_id, str(run_dir))
        self.run_id = run_id
        self.calls, self.deleted = [], set()

    def _call(self, fn):
        """fn(client) with a session open; a dropped one is reported, never
        silently reopened: the objects built so far could no longer be named."""
        from salome_agent.executor_client import SessionDied, SessionPoisoned

        with self._lock:
            if self.client is None:
                self._open()
            try:
                return fn(self.client)
            except (SessionDied, SessionPoisoned, OSError) as e:
                self._drop()
                raise SalomeError(
                    f"lost the SALOME agent server ({e}). The objects built so far stay in "
                    "the study, but this session can no longer refer to them by name; the "
                    "next call opens a new session. If SALOME restarted, start the server "
                    "again from Tools > Plugins > AI tools > MCP server.") from e

    def _drop(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # noqa: BLE001
                pass
        self.client = None

    def release(self) -> str:
        with self._lock:
            if self.client is None:
                return "No SALOME session was open."
            run_id = self.run_id
            self._drop()
            return (f"Released the SALOME agent server (session {run_id}). The objects stay "
                    "in the study; the next tool call opens a new session, which cannot refer "
                    "to them by name.")

    def status(self) -> dict:
        with self._lock:
            out = {"session_open": self.client is not None, "session": self.run_id,
                   "calls_recorded": len(self.calls)}
            if self.client is not None:
                out.update(mode=self.client.mode, name_prefix=self.client.name_prefix)
            return out

    # tools
    def call_tool(self, module: str, name: str, args: dict) -> dict:
        result = self._call(lambda c: c.call_tool(name, args, module=module))
        if result.get("ok") and result.get("records"):
            with self._lock:
                self.calls.append({"module": module, "tool": name, "args": dict(args),
                                   "records": list(result["records"])})
        return result

    def list_study(self) -> dict:
        return self._call(lambda c: c.list_study())

    def view_image(self) -> dict:
        return self._call(lambda c: c.view_image())

    def display(self, names: list) -> dict:
        return self._call(lambda c: c.display(names))

    def hide(self, names: list) -> dict:
        return self._call(lambda c: c.hide(names))

    def forget(self, names: list) -> dict:
        r = self._call(lambda c: c.forget(names))
        with self._lock:
            self.deleted |= set(r.get("removed") or [])
        return r

    # result.py
    def script(self) -> str:
        from salome_agent.build_graph import BuildGraph
        from salome_agent.nodes.assembler import render_script

        with self._lock:
            if not self.calls:
                raise SalomeError("nothing built in this session yet: no script to write")
            graph = BuildGraph()
            graph.requests = ["built with Claude through the salome-agent MCP server"]
            block, current = None, None
            for i, call in enumerate(self.calls, 1):
                if call["module"] != current:
                    current = call["module"]
                    block = graph.add_block(0, f"part {i}: {current}", current, [])
                graph.append(block, call["tool"], call["args"], call["records"], 0,
                             module=current)
            published = [p for n in graph.nodes.values() for p in n.published]
            roots = [p for p in dict.fromkeys(published) if p not in self.deleted]
            return render_script(graph, self.run_id, roots=roots)

    def save_script(self, path: str | None) -> Path:
        text = self.script()
        target = Path(os.path.expanduser(path)) if path else self._runs_dir / self.run_id / "result.py"
        if not target.is_absolute():
            raise SalomeError(f"give an absolute path, not {path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target


# ---- the documentation side -----------------------------------------------
class DocSearch:
    """raglib's agentic-RAG search (dense + keyword + reranker, whole sections),
    without its LLM: the index and models of the documentation modes."""

    def __init__(self, config_path=None, loader=None):
        self._config_path = config_path
        self._loader = loader or self._load
        self._lock = threading.Lock()
        self._state = None

    def config_path(self) -> Path:
        from salome_agent_gui import config_store

        if self._config_path:
            return Path(self._config_path).expanduser()
        return config_store.startup_config(config_store.ensure_user_config())[0]

    def _load(self, path: Path) -> dict:
        from salome_agent_gui import rag_backend, rag_models

        data = json.loads(Path(path).read_text())
        if not isinstance(data.get("rag"), dict):
            raise SalomeError(f"{path} has no rag section: open the documentation modes in the "
                              "SALOME chat window once, or copy it from config.example.json")
        absent = rag_models.missing(data)
        if absent:
            names = ", ".join(m for _, _, m in absent)
            raise SalomeError(f"local model(s) not installed: {names}. Download them in the "
                              "SALOME chat window: Settings > Local models.")
        # search needs no LLM, but raglib builds one: give it a placeholder
        data = copy.deepcopy(data)
        llm = data.setdefault("llm", {})
        llm["base_url"] = llm.get("base_url") or "http://127.0.0.1:9/v1"
        llm["model"] = llm.get("model") or "unused"
        chatbot = rag_backend.resolve_chatbot(data, path)
        if not isinstance(chatbot.get("agentic"), dict):
            raise SalomeError('search needs rag.chatbot.agentic (its page_index_path) in the config')
        rag_backend.ensure_path()
        # raglib prints progress to stdout, the MCP channel: send it to stderr
        with contextlib.redirect_stdout(sys.stderr):
            try:
                from core import ChatbotConfig, DocumentationChatbot
                from html_parser import parse_page, search_pages
            except ImportError as e:
                raise SalomeError(f"{e}; {rag_backend.INSTALL_HINT}") from e
            config = rag_backend._load_config(ChatbotConfig, chatbot)
            if not Path(config.chromadb_path).exists():
                raise SalomeError(f"no documentation index at {config.chromadb_path}: build it "
                                  "in the SALOME chat window (Settings > Build index)")
            bot = DocumentationChatbot(config)
        index_file = Path(config.agentic.page_index_path)
        if not index_file.exists():
            raise SalomeError(f"no page index at {index_file}: build the index again")
        pages = json.loads(index_file.read_text())
        score = bot.score_against_query if bot.reranker is not None else None

        def search(query: str, top_n: int):
            return search_pages(bot.vectorstore, pages, query, bm25_index=bot.bm25_index,
                                title_boost_enabled=config.title_boost_enabled,
                                rerank_fn=score, select_sections_fn=bot.expand_sections,
                                top_n=top_n, char_budget=config.agentic.section_char_budget,
                                k=15)

        return {"search": search, "read": parse_page,
                "pages": {p["filename"]: p for p in pages},
                "max_chars": config.agentic.max_chars_per_page,
                "online": online_roots(rag_backend.resolve_extraction(data, path))}

    def _online(self, entry: dict) -> str:
        """The page on docs.salome-platform.org, from the module's citation URL
        (rag.extraction.modules) and the page's path under its doc folder."""
        if entry.get("url"):
            return entry["url"]
        roots = (self._state or {}).get("online") or {}
        folder, base = roots.get((entry.get("module"), entry.get("doc_category")), (None, None))
        if not folder or not base or not entry.get("filepath"):
            return ""
        try:
            rel = Path(entry["filepath"]).resolve().relative_to(Path(folder).resolve())
        except ValueError:
            return ""
        return base.rstrip("/") + "/" + rel.as_posix()

    def _get(self) -> dict:
        with self._lock:
            if self._state is None:
                with contextlib.redirect_stdout(sys.stderr):
                    self._state = self._loader(self.config_path())
            return self._state

    def search(self, query: str, top_n: int = 5) -> str:
        state = self._get()
        with contextlib.redirect_stdout(sys.stderr):
            found = state["search"](query, top_n)
        if not found:
            return f"No match for {query!r}: try other words or a broader term."
        out = []
        for i, e in enumerate(found, 1):
            head = f"[{i}] {e.get('title') or e['filename']} | {e.get('module', '')}/{e.get('doc_category', '')}"
            head += f"\nfilename: {e['filename']}"
            online = self._online(e)
            if online:
                head += f"\nonline: {online}"
            out.append(f"{head}\n{e.get('section_text', '')}")
        return "\n\n".join(out)

    def read(self, filename: str, doc_category: str) -> str:
        state = self._get()
        entry = state["pages"].get(filename)
        if entry is None:
            raise SalomeError(f"{filename!r} is not a page of the index: use a filename "
                              "search_salome_docs returned")
        with contextlib.redirect_stdout(sys.stderr):
            try:
                text = state["read"](entry["filepath"], doc_category or entry.get("doc_category", ""),
                                     max_chars=state["max_chars"])
            except FileNotFoundError:
                raise SalomeError(f"page file not found: {entry['filepath']}") from None
        online = self._online(entry)
        where = f"{entry['filepath']}" + (f", online: {online}" if online else "")
        return f"{entry.get('title') or filename} ({where})\n\n{text}"

    def status(self) -> dict:
        try:
            path = self.config_path()
        except Exception as e:  # noqa: BLE001
            return {"ready": False, "error": str(e)}
        return {"config": str(path), "loaded": self._state is not None}


def online_roots(extraction: dict) -> dict:
    """{(module, "dev"|"user"): (local doc folder, online base URL)}."""
    out = {}
    for name, m in (extraction.get("modules") or {}).items():
        if not isinstance(m, dict):
            continue
        cite = m.get("url_for_sources_citation")
        for cat, key in (("dev", "dev_path"), ("user", "user_path")):
            base = cite.get(cat) if isinstance(cite, dict) else cite
            if m.get(key) and base:
                out[(name, cat)] = (m[key], base)
    return out


# ---- the MCP server --------------------------------------------------------
def _catalogue(module: str) -> list[dict]:
    import importlib

    if module not in MODULES:
        raise SalomeError(f"module must be one of {', '.join(MODULES)}, not {module!r}")
    return importlib.import_module(f"executor.{module}").list_tools()


def _summary(text: str) -> str:
    first = text.strip().split(". ")[0].split("\n")[0]
    return first if len(first) < 160 else first[:157] + "..."


def guide(module: str) -> str:
    from salome_agent.modules import spec_for

    tools = _catalogue(module)
    by_cat: dict[str, list] = {}
    for t in tools:
        by_cat.setdefault(t["category"], []).append(f"- {t['name']}: {_summary(t['description'])}")
    catalogue = "\n".join(f"## {cat}\n" + "\n".join(lines) for cat, lines in by_cat.items())
    return (ADAPTATION + "# Guide\n" + spec_for(module).prompt("final")
            + f"\n\n# All {module} tools\n" + catalogue)


def build_server(session: SalomeSession | None = None, docs: DocSearch | None = None):
    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp_types import ToolAnnotations

    session = session or SalomeSession()
    docs = docs or DocSearch()
    server = MCPServer("salome-agent", instructions=INSTRUCTIONS)
    read_only = ToolAnnotations(read_only_hint=True, open_world_hint=False)
    builds = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

    def guarded(fn):
        def run(*a, **kw):
            try:
                return fn(*a, **kw)
            except SalomeError as e:
                raise ToolError(str(e)) from e
        return run

    @server.tool(annotations=read_only, structured_output=False)
    def salome_status() -> str:
        """Whether the SALOME session and the documentation search are available."""
        try:
            from salome_agent import server_conn
            hs = server_conn.read_handshake()
        except Exception:  # noqa: BLE001
            hs = None
        out = {"agent_server": ("running" if hs else "not found: in SALOME, open Tools > Plugins "
                                "> AI tools > MCP server"),
               "salome": session.status(), "docs": docs.status()}
        return json.dumps(out, indent=1)

    @server.tool(annotations=read_only, structured_output=False)
    def list_cad_tools(module: str) -> str:
        """The guide and the tool catalogue of a SALOME module: "shaper" (parametric
        CAD, the default), "geom" (when the user asks for GEOM) or "smesh" (meshing).
        Read the guide before building."""
        return guarded(guide)(module)

    @server.tool(annotations=read_only, structured_output=False)
    def describe_cad_tool(module: str, name: str) -> str:
        """A tool's full description and its JSON parameters, to call it with call_cad_tool."""
        def run():
            for t in _catalogue(module):
                if t["name"] == name:
                    return json.dumps({"name": name, "description": t["description"],
                                       "parameters": t["parameters"]}, indent=1)
            raise SalomeError(f"no {module} tool {name!r}: see list_cad_tools({module!r})")
        return guarded(run)()

    @server.tool(annotations=builds, structured_output=False)
    def call_cad_tool(module: str, name: str, arguments: dict) -> str:
        """Run a SALOME tool in the user's study: module "shaper", "geom" or "smesh",
        the tool name, and its arguments as described by describe_cad_tool."""
        from salome_agent.modules import spec_for

        def run():
            _catalogue(module)                         # a clear error for a bad module
            result = session.call_tool(module, name, arguments or {})
            if not result.get("ok"):
                raise SalomeError(f"{name} failed: {result.get('error') or result}")
            try:
                return spec_for(module).render_result(result)
            except Exception:  # noqa: BLE001
                return json.dumps(_strip_hidden(result), default=str)
        return guarded(run)()

    @server.tool(annotations=read_only, structured_output=False)
    def calc(code: str) -> str:
        """Run a few lines of Python for arithmetic: trig, intersections, corner points,
        areas, is-this-point-inside checks. `math` and its functions are in scope;
        nothing else can be imported. print() what you need; the last expression's
        value is shown too. Nothing is built."""
        from salome_agent.calc import run_calc
        return run_calc(code)

    @server.tool(annotations=read_only, structured_output=False)
    def view_salome():
        """A picture of SALOME's 3D view as it is now."""
        import base64

        def run():
            r = session.view_image()
            uri = r.get("image") or ""
            if not r.get("ok", True) or not uri.startswith("data:image/"):
                raise SalomeError(r.get("error") or "SALOME returned no image")
            head, _, payload = uri.partition(",")
            fmt = head[len("data:image/"):].split(";")[0] or "png"
            return [Image(data=base64.b64decode(payload), format=fmt), "SALOME's 3D view"]
        return guarded(run)()

    @server.tool(annotations=read_only, structured_output=False)
    def list_study() -> str:
        """The top-level objects of the SALOME study."""
        return json.dumps(guarded(session.list_study)(), default=str, indent=1)

    @server.tool(annotations=builds, structured_output=False)
    def show_objects(names: list[str]) -> str:
        """Show study objects in the 3D view, by name."""
        return json.dumps(_strip_hidden(guarded(session.display)(names)), default=str)

    @server.tool(annotations=builds, structured_output=False)
    def hide_objects(names: list[str]) -> str:
        """Hide study objects from the 3D view, by name."""
        return json.dumps(_strip_hidden(guarded(session.hide)(names)), default=str)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True,
                                             open_world_hint=False), structured_output=False)
    def delete_objects(names: list[str]) -> str:
        """Remove objects this session built from the study, by name. They are left
        out of the saved script unless something kept still needs them."""
        return json.dumps(_strip_hidden(guarded(session.forget)(names)), default=str)

    @server.tool(annotations=builds, structured_output=False)
    def save_salome_script(path: str | None = None) -> str:
        """Write a standalone Python script that rebuilds what this session built
        (run it with `salome shell -- python3 result.py`, or File > Load Script).
        Without a path it goes to the session's folder. Returns where and the script."""
        def run():
            target = session.save_script(path)
            return f"Saved {target}\n\n```python\n{target.read_text()}```"
        return guarded(run)()

    @server.tool(annotations=builds, structured_output=False)
    def release_salome() -> str:
        """End this session on the SALOME agent server, so the SALOME chat window's
        Agentic assistant can use it. Objects stay in the study; save the script first
        if it is wanted."""
        return session.release()

    @server.tool(annotations=read_only, structured_output=False)
    def search_salome_docs(query: str, top_n: int = 5) -> str:
        """Search the SALOME documentation (GEOM, SHAPER, SMESH user guides and API
        reference, as indexed for the SALOME chat window). Returns the best sections
        with their page filename; read_salome_doc_page reads a whole page."""
        return guarded(docs.search)(query, max(1, min(int(top_n), 15)))

    @server.tool(annotations=read_only, structured_output=False)
    def read_salome_doc_page(filename: str, doc_category: str = "") -> str:
        """The text of a documentation page search_salome_docs returned (its filename,
        and its category: "dev" for the API reference, "user" for the user guide)."""
        return guarded(docs.read)(filename, doc_category)

    return server


def check(config=None) -> int:
    """--check: what Claude would find, printed to stderr."""
    session, docs = SalomeSession(), DocSearch(config)
    try:
        from salome_agent import server_conn
        hs = server_conn.read_handshake()
        print(f"agent server: {'running on port ' + str(hs['port']) if hs else 'not running'}",
              file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"agent server: {e}", file=sys.stderr)
    print(f"config: {docs.status()}", file=sys.stderr)
    for module in MODULES:
        print(f"{module}: {len(_catalogue(module))} tools", file=sys.stderr)
    try:
        docs._get()
        print("documentation search: ready", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"documentation search: {e}", file=sys.stderr)
    del session
    return 0


def serve_stdio(server) -> None:
    """Serve on a private copy of stdout, with fd 1 and sys.stdout sent to
    stderr: a stray print (raglib prints progress) or a library writing to fd 1
    must never reach the protocol channel. mcp's own stdio_server diverts fd 1
    but leaves sys.stdout writing to it."""
    import io

    import anyio
    from mcp.server.stdio import stdio_server

    wire = io.TextIOWrapper(os.fdopen(os.dup(1), "wb"), encoding="utf-8", newline="\n")
    stdin = io.TextIOWrapper(os.fdopen(os.dup(0), "rb"), encoding="utf-8", errors="replace")
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    async def run():
        low = server._lowlevel_server
        async with stdio_server(stdin=anyio.wrap_file(stdin),
                                stdout=anyio.wrap_file(wire)) as (read_stream, write_stream):
            await low.run(read_stream, write_stream, low.create_initialization_options())

    anyio.run(run)


def http_settings(path: Path | None = None, port: int | None = None) -> dict:
    """{"port", "token"} for --http, created on first use and kept, so a client
    registered once (claude mcp add ...) keeps working. Same file and format as
    sagui_launcher.http_settings."""
    path = Path(path or HTTP_FILE)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    changed = False
    if port is not None and data.get("port") != port:
        data["port"], changed = int(port), True
    if not isinstance(data.get("port"), int):
        data["port"], changed = DEFAULT_PORT, True
    if not isinstance(data.get("token"), str) or len(data["token"]) < 16:
        data["token"], changed = secrets.token_urlsafe(24), True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"port": data["port"], "token": data["token"]}, f)
    return {"port": data["port"], "token": data["token"]}


def http_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def client_commands(port: int, token: str) -> dict:
    """How to connect each client to the --http server (also in the SALOME
    dialog: sagui_launcher.client_commands)."""
    url, auth = http_url(port), f"Authorization: Bearer {token}"
    # flags before the name for gemini and agy (agy rejects them after it, and has
    # no --transport: it sees the http URL); claude's --header takes several
    # values, so it goes last. --scope user: every folder, not only the current one.
    return {"Claude Code": f'claude mcp add --scope user --transport http {SERVER_NAME} {url} '
                           f'--header "{auth}"',
            "Gemini CLI": f'gemini mcp add --scope user --transport http --header "{auth}" '
                          f'{SERVER_NAME} {url}',
            "Antigravity (agy)": f'agy mcp add --header "{auth}" {SERVER_NAME} {url}',
            "Other MCP clients": f"URL {url}, header {auth}"}


def require_token(app, token: str):
    """The ASGI app, answering 401 to an HTTP request without the bearer token:
    the server listens on loopback, but any local user could reach it."""
    expected = f"Bearer {token}".encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope.get("headers") or ()).get(b"authorization", b"")
            if not hmac.compare_digest(got, expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body",
                            "body": b"missing or wrong bearer token: see the SALOME menu "
                                    b"Tools > Plugins > AI tools > MCP server"})
                return
        await app(scope, receive, send)
    return guarded


def watch_parent(pid: int, interval: float = 2.0, exit_fn=os._exit) -> threading.Thread:
    """Stop the process when SALOME (the process that started it) is gone."""
    def run():
        while True:
            time.sleep(interval)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                exit_fn(0)
                return
            except PermissionError:
                pass
    t = threading.Thread(target=run, name="parent-watch", daemon=True)
    t.start()
    return t


def serve_http(server, port: int, token: str) -> None:
    import uvicorn

    app = require_token(server.streamable_http_app(host="127.0.0.1"), token)
    for name, line in client_commands(port, token).items():
        print(f"{name}: {line}", file=sys.stderr)
    uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")).run()


def desktop_entry(config=None, environ=None, argv0=None) -> dict:
    """The mcpServers entry for Claude Desktop's claude_desktop_config.json. Under
    WSL, Claude Desktop is a Windows app: it starts the server through wsl.exe."""
    environ = os.environ if environ is None else environ
    root = environ.get("SALOME_AGENT_GUI_ROOT_DIR")
    launcher = Path(root) / "bin" / "salome-agent-gui.sh" if root else None
    if launcher is not None and launcher.is_file():
        command = [str(launcher), "--mcp"]           # the venv activated, SALOME's env stripped
    else:
        command = [str(Path(argv0 or sys.argv[0]).resolve())]
    if config:
        command += ["--config", str(Path(config).expanduser().resolve())]
    distro = environ.get("WSL_DISTRO_NAME")
    if distro:
        return {"command": "wsl.exe", "args": ["-d", distro, "-e", *command]}
    return {"command": command[0], "args": command[1:]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="salome-agent-mcp", description=__doc__.split("\n")[0])
    parser.add_argument("--config", help="config file for the documentation search "
                                         "(default: the SALOME chat window's)")
    parser.add_argument("--check", action="store_true",
                        help="print what is available and exit, instead of serving")
    parser.add_argument("--desktop-config", action="store_true",
                        help="print the entry to add to Claude Desktop's claude_desktop_config.json")
    parser.add_argument("--http", action="store_true",
                        help="serve on http://127.0.0.1:PORT/mcp, waiting for clients, instead of stdio")
    parser.add_argument("--port", type=int, help=f"--http port (default: the saved one, else {DEFAULT_PORT})")
    args = parser.parse_args(argv)
    if args.check:
        return check(args.config)
    if args.desktop_config:
        print(json.dumps({"mcpServers": {"salome-agent": desktop_entry(args.config)}}, indent=2))
        return 0
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    if args.http:
        settings = http_settings(port=args.port)
        try:
            watch_parent(int(os.environ["SALOME_AGENT_GUI_PARENT_PID"]))
        except (KeyError, ValueError):
            pass
        serve_http(build_server(docs=DocSearch(args.config)), settings["port"], settings["token"])
        return 0
    serve_stdio(build_server(docs=DocSearch(args.config)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
