// Copyright (C) 2026  salome-agent authors, LGPL 2.1 or later
"use strict";

// Constant SVG markup only. Everything that comes from the engine or the LLM is
// set with textContent; never pass it to innerHTML / insertAdjacentHTML.
const ICON = {
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  fail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  run: '<svg class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><path d="M21 12a9 9 0 1 1-6.2-8.56"/></svg>',
  skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01"/></svg>',
  chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
  code: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/></svg>',
  approve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
};
const STEP = { ok: ["st ok", "ok"], running: ["st run", "run"], failed: ["st fail", "fail"],
               skipped: ["st skip", "skip"], pending: ["st pend", null],
               stopped: ["st stopped", "stop"] };
const LEAD = { needs_input: "Question", failed: "Turn failed", fatal: "Run failed",
               degraded: "Study out of sync", ended: "Session ended", aborted: "Run aborted" };
const TONE = { ok: "ok", needs_input: "info", degraded: "warn", ended: "warn", aborted: "muted" };

// Kept in step with salome_agent.cli (MAX_IMAGES, MAX_IMAGE_BYTES), which the
// bridge holds every message to: the formats the vision LLM accepts, and the limits.
// recognised by content, like the engine (salome_agent.cli._image_mime): the type the
// browser reports comes from the extension and the system, and can be empty for a
// WEBP dropped from another desktop or pasted from some applications
function imageMime(b) {
  const at = (i, s) => [...s].every((c, k) => b[i + k] === c.charCodeAt(0));
  if (at(0, "RIFF") && at(8, "WEBP")) return "image/webp";
  if (b[0] === 0x89 && at(1, "PNG\r\n\x1a\n")) return "image/png";
  if (b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff) return "image/jpeg";
  if (at(0, "GIF87a") || at(0, "GIF89a")) return "image/gif";
  if (at(0, "BM")) return "image/bmp";
  return null;
}
const MAX_IMAGES = 10;
const MAX_IMAGES_MB = 20;   // all images of a message together
const HINT = "Enter to send · Shift+Enter for a new line";
const DOC_MODES = ["rag", "rag_agentic"];
const PLACEHOLDER = { agent: "Describe what to build, or ask for a change…",
                      doc: "Ask a question about SALOME…" };

let bridge = null;
const state = { busy: false, open: false, canSend: false, stopping: false, locked: false, settings: null };
// images attached to the message being written: [{name, size, url}] with url a data: URI
let attached = [];
let hintTimer = null;
// reasoning blocks by data-key: which are open, and where their body was scrolled
const reasoningOpen = new Set();
const reasoningScroll = new Map();
const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}
function svg(parent, name) { parent.insertAdjacentHTML("beforeend", ICON[name]); return parent; }
function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }
function ordinal(n) {
  const t = n % 100;
  if (t >= 11 && t <= 13) return `${n}th`;
  return n + ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
}
function fmtDuration(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${s % 60} s`;
}
function fmtClock(s) {
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function fmtTokens(n) {
  if (n < 1000) return String(n);
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
}

// ---- transcript -------------------------------------------------------
function col() { return $("col"); }
function nearBottom() {
  const t = $("transcript");
  return t.scrollHeight - t.scrollTop - t.clientHeight < 80;
}
function scrollEnd() { const t = $("transcript"); t.scrollTop = t.scrollHeight; }
function updateEmpty() { document.body.classList.toggle("is-empty", col().children.length === 0); }
function append(node) {
  const stick = nearBottom();
  col().appendChild(node);
  updateEmpty();
  if (stick) scrollEnd();
}

function imageNode(url, name) {
  const img = el("img");
  img.src = url;                      // a data:image/... URI the bridge has checked
  img.alt = name || "";
  img.title = name || "";
  img.addEventListener("click", () => openLightbox(url));
  return img;
}

function userNode(text, images) {
  const d = el("div", "msg-user");
  if (images && images.length) {
    const g = el("div", "msg-images");
    for (const url of images) g.appendChild(imageNode(url));
    d.appendChild(g);
  }
  if (text) d.appendChild(el("div", "bubble", text));
  return d;
}
function noteNode(text) { return el("div", "note", text); }

function btn(label, cls, action, onClick, icon) {
  const b = el("button", "btn" + (cls ? " " + cls : ""));
  b.dataset.action = action;
  if (icon) svg(b, icon);
  b.appendChild(document.createTextNode(label));
  b.addEventListener("click", onClick);
  return b;
}
function answer(gate, action, text, container) {
  container.querySelectorAll("button, textarea").forEach((x) => { x.disabled = true; });
  bridge.gate(gate.id, action, text || "");
}

// ---- model reasoning (debug) --------------------------------------------
function reasoningCall(c) {
  const node = el("div", "r-call");
  node.dataset.call = String(c.call);
  node.appendChild(el("div", "r-think", c.reasoning || ""));
  node.appendChild(el("div", "r-prose", c.prose || ""));
  return node;
}

function reasoningSummary(details) {
  const n = details.querySelectorAll(".r-call").length;
  details.querySelector("summary").textContent = `Reasoning · ${plural(n, "call")}`;
}

function reasoningNode(turn, key, calls) {
  const details = el("details", "reasoning");
  const dkey = `${turn}:${key}`;
  details.dataset.key = dkey;
  details.appendChild(el("summary"));
  const body = el("div", "r-body");
  for (const c of calls) body.appendChild(reasoningCall(c));
  details.appendChild(body);
  reasoningSummary(details);
  details.open = reasoningOpen.has(dkey);
  details.addEventListener("toggle", () => {
    if (details.open) reasoningOpen.add(dkey); else reasoningOpen.delete(dkey);
  });
  body.addEventListener("scroll", () => {
    reasoningScroll.set(dkey, body.scrollHeight - body.scrollTop - body.clientHeight < 8
      ? "end" : body.scrollTop);
  });
  return details;
}

function restoreReasoningScroll(root) {
  root.querySelectorAll("details.reasoning[open]").forEach((d) => {
    const body = d.querySelector(".r-body");
    const at = reasoningScroll.get(d.dataset.key);
    body.scrollTop = at === undefined || at === "end" ? body.scrollHeight : at;
  });
}

function appendReasoning(p) {
  const wrap = col().querySelector(`[data-turn="${p.turn}"]`);
  if (!wrap) return;                      // the next renderTurn draws it from the view model
  let host;
  if (p.key.startsWith("stage:")) {
    host = wrap.querySelector(`.step[data-stage="${p.key.slice(6)}"] .main`);
  } else if (p.key === "vision") {
    host = wrap.querySelector(".vision-card .vision-reasoning");
  } else {
    host = wrap.querySelector(".turn-reasoning");
  }
  if (!host) return;
  let details = host.querySelector(`:scope > details.reasoning[data-key="${p.turn}:${p.key}"]`);
  if (!details) {
    details = reasoningNode(p.turn, p.key, []);
    host.appendChild(details);
  }
  const body = details.querySelector(".r-body");
  let call = body.querySelector(`.r-call[data-call="${p.call}"]`);
  if (!call) {
    call = reasoningCall({ call: p.call });
    body.appendChild(call);
    reasoningSummary(details);
  }
  const pinned = body.scrollHeight - body.scrollTop - body.clientHeight < 8;
  const stick = nearBottom();
  call.querySelector(p.channel === "prose" ? ".r-prose" : ".r-think")
    .appendChild(document.createTextNode(String(p.text || "")));
  if (pinned) body.scrollTop = body.scrollHeight;
  if (stick) scrollEnd();
}

function stepRow(s, vm) {
  const li = el("li", "step" + (s.status === "pending" ? " pending" : ""));
  li.dataset.stage = String(s.index);
  const [cls, icon] = STEP[s.status] || STEP.pending;
  const st = el("span", cls);
  if (icon) svg(st, icon);
  li.appendChild(st);
  const main = el("div", "main");
  const line = el("div", "line");
  if (s.icon) {
    const img = el("img", "mod");
    img.src = s.icon;
    img.alt = s.module;
    img.title = String(s.module).toUpperCase();
    line.appendChild(img);
  } else {
    const known = ["geom", "smesh", "shaper"].includes(s.module) ? " " + s.module : "";
    line.appendChild(el("span", "badge" + known, s.module));
  }
  line.appendChild(el("span", "intent", s.intent));
  const meta = el("span", "meta");
  if (s.status === "running" && s.started_at) {
    meta.dataset.start = s.started_at;
    meta.textContent = fmtClock(Date.now() / 1000 - s.started_at);
  } else {
    const bits = [];
    if (s.elapsed_s !== null && s.elapsed_s !== undefined) bits.push(fmtDuration(s.elapsed_s));
    if (s.status === "stopped") bits.push("stopped");
    if (s.status === "failed" && s.attempts > 0) bits.push(plural(s.attempts, "attempt"));
    else if (s.attempts > 1) bits.push(`${ordinal(s.attempts)} attempt`);
    meta.textContent = bits.join(" · ");
  }
  line.appendChild(meta);
  main.appendChild(line);
  if (s.objects && s.objects.length) {
    const objs = el("div", "step-objs");
    for (const name of s.objects) objs.appendChild(el("span", "chip mini", name));
    main.appendChild(objs);
  }
  const gateShowsError = vm.gate && vm.gate.kind === "stage_failed";
  if (s.error && s.status === "failed" && !gateShowsError) main.appendChild(el("div", "err", s.error));
  if (s.reasoning && s.reasoning.length) {
    main.appendChild(reasoningNode(vm.id, `stage:${s.index}`, s.reasoning));
  }
  li.appendChild(main);
  return li;
}

function planFoot(gate) {
  const f = el("div", "card-foot");
  f.appendChild(btn("Approve & build", "primary", "approve", () => answer(gate, "approve", "", f), "approve"));
  f.appendChild(btn("Edit plan", null, "edit", () => answer(gate, "edit", "", f)));
  f.appendChild(el("span", "spacer"));
  f.appendChild(btn("Abort", "ghost danger", "abort", () => answer(gate, "abort", "", f)));
  return f;
}

function stagesCard(vm) {
  const card = el("div", "card");
  const head = el("div", "card-head");
  const n = vm.stages.length;
  let title = "Plan";
  let count = `· ${plural(n, "stage")}`;
  if (vm.gate && vm.gate.kind === "plan") title = "Proposed plan";
  else if (vm.gate && vm.gate.kind === "stage_failed") { title = "Building"; count = "· waiting for you"; }
  else if (vm.status === "running") {
    title = "Building";
    const cur = vm.stages.findIndex((s) => s.status === "running");
    if (cur >= 0) count = `· stage ${cur + 1} of ${n}`;
  }
  head.appendChild(el("span", null, title));
  head.appendChild(el("span", "count", count));
  const total = vm.stages.reduce((a, s) => a + (s.elapsed_s || 0), 0);
  if (vm.status !== "running" && total > 0) {
    head.appendChild(el("span", "spacer"));
    head.appendChild(el("span", "usage", `built in ${fmtDuration(total)}`));
  }
  card.appendChild(head);
  const ol = el("ol", "steps");
  for (const s of vm.stages) ol.appendChild(stepRow(s, vm));
  card.appendChild(ol);
  if (vm.gate && vm.gate.kind === "plan") card.appendChild(planFoot(vm.gate));
  return card;
}

function turnClock(vm) {
  const meta = el("span", "meta");
  if (vm.status === "running" && vm.started_at) {
    meta.dataset.start = vm.started_at;
    meta.textContent = fmtClock(Date.now() / 1000 - vm.started_at);
  } else if (vm.elapsed_s !== null && vm.elapsed_s !== undefined) {
    meta.textContent = `done in ${fmtDuration(vm.elapsed_s)}`;
  }
  return meta;
}

function editsCard(vm) {
  const edits = vm.edits;
  const card = el("div", "card");
  const head = el("div", "card-head");
  const changes = edits.filter((e) => e.op !== "replay");
  const replay = edits.find((e) => e.op === "replay");
  head.appendChild(el("span", null, "Changes"));
  let count = `· ${plural(changes.length, "edit")}`;
  if (replay) count += `, ${plural(replay.nodes.length, "object")} rebuilt`;
  head.appendChild(el("span", "count", count));
  if (!vm.stages.length) {
    head.appendChild(el("span", "spacer"));
    head.appendChild(turnClock(vm));
  }
  card.appendChild(head);
  const ul = el("ul", "edits");
  for (const e of changes) {
    const li = el("li");
    if (e.op === "edit") {
      li.appendChild(el("code", null, `${e.node}.${e.param}`));
      li.appendChild(el("span", "old", e.old));
      li.appendChild(el("span", "arrow", "→"));
      li.appendChild(el("span", "new", e.new));
    } else if (e.op === "delete") {
      li.appendChild(el("span", "old", "removed"));
      li.appendChild(el("code", null, e.nodes.join(", ")));
    } else {
      li.appendChild(el("span", "new", "added"));
      li.appendChild(el("code", null, `${e.node} (${e.new})`));
    }
    ul.appendChild(li);
  }
  card.appendChild(ul);
  return card;
}

function failCard(vm, gate) {
  const card = el("div", "card gate-warn");
  const head = el("div", "card-head");
  svg(head, "warn");
  const stage = gate.stage !== null && gate.stage !== undefined ? vm.stages[gate.stage] : null;
  let title = stage ? `Stage ${gate.stage + 1} failed` : "Stage failed";
  if (stage && stage.attempts > 1) title += ` after ${stage.attempts} attempts`;
  head.appendChild(el("span", null, title));
  card.appendChild(head);
  const body = el("div", "gate-body");
  body.appendChild(el("div", "err", gate.message || "(no message)"));
  if (gate.line) body.appendChild(el("div", "err-line", `at line ${gate.line}`));
  card.appendChild(body);
  const hintBox = el("div", "hint-box");
  hintBox.hidden = true;
  const ta = el("textarea");
  ta.rows = 2;
  ta.placeholder = "Tell the specialist what to try…";
  hintBox.appendChild(ta);
  hintBox.appendChild(btn("Send hint", "primary", "hint", () => {
    if (ta.value.trim()) answer(gate, "hint", ta.value, card);
  }));
  const f = el("div", "card-foot");
  f.appendChild(btn("Give a hint", "primary", "show-hint", () => { hintBox.hidden = false; ta.focus(); }));
  f.appendChild(btn("Skip stage", null, "skip", () => answer(gate, "skip", "", card)));
  f.appendChild(el("span", "spacer"));
  f.appendChild(btn("Abort run", "ghost danger", "abort", () => answer(gate, "abort", "", card)));
  card.appendChild(hintBox);
  card.appendChild(f);
  return card;
}

function resultBlock(vm) {
  const r = el("div", "result");
  const line = el("div", "result-line " + (TONE[vm.status] || "bad"));
  svg(line.appendChild(el("span", "res-ic")), vm.status === "ok" ? "done" : "warn");
  const msg = vm.message || "";
  const block = msg.includes("\n") || vm.status === "failed" || vm.status === "fatal";
  if (vm.status === "ok") {
    const n = vm.objects.length;
    line.appendChild(el("span", null, msg || (n ? `Built ${plural(n, "object")}` : "Done")));
  } else {
    line.appendChild(el("span", null, LEAD[vm.status] || vm.status));
    if (msg && !block) line.appendChild(el("span", "result-msg", msg));
  }
  r.appendChild(line);
  if (msg && block && vm.status !== "ok") r.appendChild(el("div", "err", msg));
  for (const w of vm.warnings || []) {
    const row = el("div", "result-warning");
    svg(row.appendChild(el("span", "res-ic")), "warn");
    row.appendChild(el("span", null, w));
    r.appendChild(row);
  }
  const underSteps = new Set();
  for (const st of vm.stages) for (const name of st.objects || []) underSteps.add(name);
  if (vm.objects.length && !vm.objects.every((name) => underSteps.has(name))) {
    const d = el("details", "objects");
    const s = el("summary");
    svg(s, "chevron");
    s.appendChild(document.createTextNode(`Show ${plural(vm.objects.length, "object")}`));
    d.appendChild(s);
    const chips = el("div", "chips");
    for (const name of vm.objects) chips.appendChild(el("span", "chip", name));
    d.appendChild(chips);
    r.appendChild(d);
  }
  const files = el("div", "chips");
  for (const [key, label, icon] of [["result_py", "result.py", "code"], ["report_md", "report.md", "doc"]]) {
    const path = vm.files && vm.files[key];
    if (!path) continue;
    const b = el("button", "chip");
    b.dataset.file = key;
    b.title = path;
    svg(b, icon);
    b.appendChild(document.createTextNode(label));
    b.addEventListener("click", () => bridge.openFile(path));
    files.appendChild(b);
  }
  if (files.children.length) r.appendChild(files);
  if (vm.usage) {
    const u = el("div", "usage");
    const x = vm.usage;
    if (x.calls !== undefined) u.appendChild(el("span", null, plural(x.calls, "LLM call")));
    if (x.prompt_tokens !== undefined) {
      u.appendChild(el("span", null, `${fmtTokens(x.prompt_tokens)} in / ${fmtTokens(x.completion_tokens || 0)} out`));
    }
    if (x.llm_seconds !== undefined) u.appendChild(el("span", null, `${fmtDuration(x.llm_seconds)} waiting on the model`));
    r.appendChild(u);
  }
  return r;
}

const VISION_TITLE = { running: "Reading image", done: "Image read", conflicts: "Image read",
                       failed: "Could not read the image", stopped: "Image reading stopped" };

function visionCard(vm) {
  const v = vm.vision;
  const card = el("div", "card vision-card");
  card.dataset.status = v.status;
  const head = el("div", "card-head");
  const [cls, icon] = (v.status === "running" ? STEP.running
                       : v.status === "failed" ? STEP.failed
                       : v.status === "stopped" ? STEP.stopped
                       : v.status === "conflicts" ? ["st warn", "warn"] : STEP.ok);
  const st = el("span", cls);
  if (icon) svg(st, icon);
  head.appendChild(st);
  head.appendChild(el("span", null, VISION_TITLE[v.status] || "Image"));
  head.appendChild(el("span", "count", `· ${plural(v.images, "image")}`));
  const meta = el("span", "meta");
  if (v.status === "running" && v.started_at) {
    meta.dataset.start = v.started_at;
    meta.textContent = fmtClock(Date.now() / 1000 - v.started_at);
  } else if (v.elapsed_s !== null && v.elapsed_s !== undefined) {
    meta.textContent = fmtDuration(v.elapsed_s);
  }
  head.appendChild(meta);
  card.appendChild(head);
  const body = el("div", "vision-body");
  const facts = [...(v.sizes || []).map((s) => s.replace("x", "×")), v.model].filter(Boolean);
  if (facts.length) body.appendChild(el("div", "vision-facts", facts.join(" · ")));
  for (const c of v.checks || []) {
    const d = el("details", "vision-check");
    d.appendChild(el("summary", null,
                     `Fix round ${c.attempt}/${c.of}: ${plural(c.errors.length, "problem")}`));
    const ul = el("ul");
    for (const e of c.errors) ul.appendChild(el("li", null, e));
    d.appendChild(ul);
    body.appendChild(d);
  }
  if (v.status === "done") {
    body.appendChild(el("div", "vision-result", `Read ${plural(v.parts || 0, "part")}`));
  } else if (v.status === "conflicts") {
    body.appendChild(el("div", "vision-result warn",
      `Read ${plural(v.parts || 0, "part")}, ${plural(v.conflicts, "problem")} left for the build`));
  } else if (v.status === "failed" && v.error) {
    body.appendChild(el("div", "err", v.error));
  }
  const rhost = el("div", "vision-reasoning");
  if (v.reasoning && v.reasoning.length) rhost.appendChild(reasoningNode(vm.id, "vision", v.reasoning));
  body.appendChild(rhost);
  card.appendChild(body);
  return card;
}

// ---- documentation answers ----------------------------------------------
// A small Markdown subset drawn with DOM nodes and textContent only: the
// answer comes from the LLM and never reaches innerHTML.
function linkNode(text, target) {
  const a = el("a", null, text);
  if (/^https?:\/\//.test(target)) {
    a.title = target;
    a.addEventListener("click", (e) => { e.preventDefault(); bridge.openLink(target); });
  }
  return a;
}

const INLINE = /(`+)([\s\S]*?)\1|\*\*([\s\S]+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()\]]*[^\s<>()\].,;:!?'"])|\*([^*\s][^*]*?)\*/g;

function inline(parent, text) {
  let last = 0;
  const re = new RegExp(INLINE.source, "g");          // own lastIndex: inline() recurses
  for (let m; (m = re.exec(text)) !== null;) {
    if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
    if (m[1]) parent.appendChild(el("code", null, m[2]));
    else if (m[3] !== undefined) inline(parent.appendChild(el("strong")), m[3]);
    else if (m[4] !== undefined) {
      if (/^https?:\/\//.test(m[5])) inline(parent.appendChild(linkNode("", m[5])), m[4]);
      else inline(parent, m[4]);                       // a relative link goes nowhere: keep its text
    } else if (m[6]) parent.appendChild(linkNode(m[6], m[6]));
    else inline(parent.appendChild(el("em")), m[7]);
    last = re.lastIndex;
  }
  if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
  return parent;
}

function inlineLines(parent, lines) {
  lines.forEach((line, i) => {
    if (i) parent.appendChild(el("br"));
    inline(parent, line);
  });
  return parent;
}

function markdownNode(text) {
  const root = el("div", "answer");
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  const isList = (l) => /^\s*([-*+]|\d+[.)])\s+/.test(l);
  const blockStart = (l) => /^\s*(```|#{1,6}\s|>)/.test(l) || isList(l);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }
    const fence = line.match(/^\s*```\s*([\w+-]*)/);
    if (fence) {
      const body = [];
      for (i += 1; i < lines.length && !/^\s*```/.test(lines[i]); i += 1) body.push(lines[i]);
      i += 1;                                           // the closing fence (or the end)
      const pre = el("pre");
      const code = el("code", null, body.join("\n"));
      if (fence[1]) code.dataset.lang = fence[1];
      pre.appendChild(code);
      root.appendChild(pre);
      continue;
    }
    const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
    if (h) {
      inline(root.appendChild(el(`h${Math.min(h[1].length, 4)}`)), h[2].replace(/\s+#+\s*$/, ""));
      i += 1;
      continue;
    }
    if (/^\s*>/.test(line)) {
      const quote = [];
      for (; i < lines.length && /^\s*>/.test(lines[i]); i += 1) quote.push(lines[i].replace(/^\s*>\s?/, ""));
      inlineLines(root.appendChild(el("blockquote")), quote);
      continue;
    }
    if (isList(line)) {
      const ordered = /^\s*\d+[.)]/.test(line);
      const list = root.appendChild(el(ordered ? "ol" : "ul"));
      let item = null;
      for (; i < lines.length; i += 1) {
        const l = lines[i];
        if (isList(l)) {
          item = list.appendChild(el("li"));
          inline(item, l.replace(/^\s*([-*+]|\d+[.)])\s+/, ""));
        } else if (l.trim() && /^\s+/.test(l) && !/^\s*```/.test(l)) {
          item.appendChild(el("br"));
          inline(item, l.trim());                       // an indented continuation line
        } else break;
      }
      continue;
    }
    const para = [];
    for (; i < lines.length && lines[i].trim() && !(para.length && blockStart(lines[i])); i += 1) {
      para.push(lines[i]);
    }
    inlineLines(root.appendChild(el("p")), para);
  }
  return root;
}

const ANSWER_TITLE = { running: "Looking it up", done: "Answer", failed: "Could not answer",
                       stopped: "Stopped" };

function answerCard(vm) {
  const r = vm.rag;
  const card = el("div", "card answer-card");
  const head = el("div", "card-head");
  const [cls, icon] = (r.status === "running" ? STEP.running : r.status === "failed" ? STEP.failed
                       : r.status === "stopped" ? STEP.stopped : STEP.ok);
  const st = el("span", cls);
  if (icon) svg(st, icon);
  head.appendChild(st);
  let title = ANSWER_TITLE[r.status] || "Answer";
  if (r.status === "running") {
    title = r.phase === "loading" ? "Loading the documentation index…"
      : r.phase === "waiting" ? "Waiting for the stopped question to finish…"
      : (r.agentic ? "Searching and reading the documentation…" : "Searching the documentation…");
  }
  head.appendChild(el("span", null, title));
  head.appendChild(el("span", "count", r.agentic ? "· agentic RAG" : "· RAG"));
  head.appendChild(turnClock(vm));
  card.appendChild(head);
  if (r.status !== "done") return card;
  if (r.degraded) {
    card.appendChild(el("div", "answer-warn",
      "The model's answer could not be checked against the pages it read; these are the pages to look at."));
  }
  card.appendChild(markdownNode(r.answer || "(empty answer)"));
  if (r.sources && r.sources.length) {
    const d = el("details", "sources");
    d.open = true;
    d.appendChild(el("summary", null, `Sources · ${plural(r.sources.length, "page")}`));
    const ol = el("ol");
    for (const src of r.sources) {
      const li = el("li");
      const target = src.url || src.path;
      li.appendChild(target ? linkNode(src.title, target) : el("span", null, src.title));
      if (target && !src.url) {
        li.firstChild.title = target;
        li.firstChild.addEventListener("click", (e) => { e.preventDefault(); bridge.openLink(target); });
      }
      const meta = [src.module, src.category].filter((x) => x && x !== "Unknown").join(" · ");
      if (meta) li.appendChild(el("span", "src-meta", meta));
      ol.appendChild(li);
    }
    d.appendChild(ol);
    card.appendChild(d);
  }
  const u = el("div", "usage answer-foot");
  if (r.steps) u.appendChild(el("span", null, plural(r.steps, "agent message")));
  if (r.usage && r.usage.input_tokens !== undefined) {
    u.appendChild(el("span", null, `${fmtTokens(r.usage.input_tokens)} in / ${fmtTokens(r.usage.output_tokens || 0)} out`));
  }
  if (u.children.length) card.appendChild(u);
  return card;
}

function turnNode(vm) {
  const wrap = el("div", "msg-agent");
  wrap.dataset.turn = String(vm.id);
  const av = el("img", "avatar");
  av.src = "salome-s.png";
  av.alt = "";
  const body = el("div", "agent-body");
  wrap.appendChild(av);
  wrap.appendChild(body);
  const gate = vm.gate;
  if (vm.rag) {                                         // a documentation answer
    body.appendChild(answerCard(vm));
    if (vm.status !== "running" && vm.status !== "ok" && vm.status !== "aborted") {
      body.appendChild(resultBlock(vm));
    }
    return wrap;
  }
  // planner and chat-edit reasoning: the turn level, drawn before any card exists
  const turnReasoning = el("div", "turn-reasoning");
  for (const key of ["planner", "edit"]) {
    const calls = (vm.reasoning || {})[key];
    if (calls && calls.length) turnReasoning.appendChild(reasoningNode(vm.id, key, calls));
  }
  // order of events: image read, then planning (its reasoning under the placeholder)
  if (vm.vision) body.appendChild(visionCard(vm));
  if (!vm.stages.length && !vm.edits.length && !gate && vm.status === "running"
      && !(vm.vision && vm.vision.status === "running")) {
    const planning = vm.reasoning && vm.reasoning.planner;
    const wait = el("div", "agent-text muted", planning ? "Planning…" : "Thinking…");
    const clock = turnClock(vm);
    if (clock.textContent) wait.appendChild(clock);
    body.appendChild(wait);
  }
  body.appendChild(turnReasoning);
  if (gate && gate.kind === "plan") {
    const t = el("div", "agent-text", "Here's the plan. ");
    t.appendChild(el("span", "muted", "Approve it to start building, or edit the stages first."));
    body.appendChild(t);
  }
  if (vm.stages.length) body.appendChild(stagesCard(vm));
  else if (gate && gate.kind === "plan") body.appendChild(planFoot(gate));   // never leave no way out
  if (vm.edits.length) body.appendChild(editsCard(vm));
  if (gate && gate.kind === "stage_failed") body.appendChild(failCard(vm, gate));
  if (!gate && vm.status !== "running") body.appendChild(resultBlock(vm));
  return wrap;
}

function renderTurn(vm) {
  const node = turnNode(vm);
  const old = col().querySelector(`[data-turn="${vm.id}"]`);
  if (!old) { append(node); return; }
  const stick = nearBottom();
  old.replaceWith(node);
  restoreReasoningScroll(node);
  if (stick) scrollEnd();
}

function replay(p) {
  col().textContent = "";
  for (const it of p.items) {
    if (it.type === "user") col().appendChild(userNode(it.text, it.images));
    else if (it.type === "note") col().appendChild(noteNode(it.text));
    else col().appendChild(turnNode(it.vm));
  }
  restoreReasoningScroll(col());
  updateEmpty();
  scrollEnd();
}

// ---- header, status, busy ---------------------------------------------
function setBusy(p) {
  Object.assign(state, { busy: p.busy, open: p.open, canSend: p.can_send, stopping: p.stopping });
  const idleOpen = p.open && !p.busy;
  $("btn-undo").disabled = !idleOpen;
  $("btn-redo").disabled = !idleOpen;
  $("btn-new").disabled = !idleOpen;
  $("btn-rebuild").disabled = !(idleOpen && p.degraded);
  const send = $("send");
  send.classList.toggle("stop", p.busy);
  send.innerHTML = p.busy ? ICON.stop : ICON.send;
  send.title = p.busy ? "Stop" : "Send";
  send.disabled = p.busy ? p.stopping : !p.can_send;
  if (!hintTimer) showHint();
  setDocMode(!!p.doc);
  lockRunOptions(p.open);
  renderModeSwitch(p.mode, p.can_switch_mode, p.modes);
}

// the header's choice of assistant; Bridge.setMode saves it as gui.mode. The
// SALOME menu entry that opened the window decides which modes it offers.
function renderModeSwitch(mode, canSwitch, modes) {
  if (mode === undefined) return;
  if (Array.isArray(modes)) {
    for (const b of $("mode-switch").querySelectorAll("button")) b.hidden = !modes.includes(b.dataset.mode);
    $("mode-switch").hidden = modes.length < 2;
    for (const o of $("set-mode").options) o.hidden = !modes.includes(o.value);
  }
  const why = canSwitch ? "" : (mode === "agent"
    ? " · end the conversation (New conversation) to switch" : " · wait for the answer to switch");
  for (const b of $("mode-switch").querySelectorAll("button")) {
    const on = b.dataset.mode === mode;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
    b.disabled = !canSwitch;
    if (!b.dataset.baseTip) b.dataset.baseTip = b.title;
    b.title = b.dataset.baseTip + (canSwitch ? "" : why);
  }
}

function setDocMode(doc) {
  document.body.classList.toggle("doc-mode", doc);
  if (doc && attached.length) {                         // images are not read in these modes
    attached = [];
    renderAttachments();
  }
  $("input").placeholder = doc ? PLACEHOLDER.doc : PLACEHOLDER.agent;
}

// one background job at a time: the index build or a model download
function setIndex(p) {
  const models = p.job === "models";
  const line = $(models ? "models-job" : "rag-index-state");
  line.className = "idx-state";
  line.textContent = p.line || "";
  $("btn-build-index").disabled = !!p.building;
  $("btn-build-index").textContent = p.building && !models ? "Building…" : "Build index";
  for (const role of ["embedding", "reranker"]) {
    const b = $(`btn-dl-${role}`);
    b.disabled = !!p.building || !!state.locked;
    b.textContent = p.building && models ? "Downloading…" : "Download";
  }
}

// ---- local models (raglib's download_models.py) ---------------------------
const MODEL_STATE = {
  installed: (s) => `Installed${s.size ? " · " + s.size : ""}`,
  local: (s) => `Local folder${s.size ? " · " + s.size : ""}`,
  missing: () => "Not installed",
  api: () => "API endpoint: nothing to download",
  none: () => "No model set",
};

function modelState(id, st, edited) {
  const span = $(id);
  if (edited) {
    span.className = "model-state";
    span.textContent = "Changed: Download saves and checks it";
    return true;
  }
  span.className = "model-state " + (st.state || "");
  span.textContent = (MODEL_STATE[st.state] || (() => ""))(st);
  span.title = st.path || "";
  return st.state === "missing";
}

function renderModelStates() {
  const m = (state.settings || {}).rag_models;
  if (!m) return;
  const embEdited = $("set-emb-model").value.trim() !== m.embedding.model;
  const rrEdited = $("set-rr-model").value.trim() !== m.reranker.model
    || $("set-rr-type").value !== m.reranker.type;
  $("btn-dl-embedding").hidden = !modelState("emb-state", m.embedding.status, embEdited)
    || m.embedding.type === "api";
  $("btn-dl-reranker").hidden = !modelState("rr-state", m.reranker.status, rrEdited);
}

function renderModels(m) {
  if (!m) return;
  $("set-emb-model").value = m.embedding.model;
  $("set-rr-model").value = m.reranker.model;
  $("set-rr-type").value = m.reranker.type;
  $("rr-role").textContent = m.reranker.enabled ? "Reranker" : "Reranker (off)";
  $("rr-card").title = "Re-scores the passages a search found, when Rerank results is on (Search)"
    + (m.reranker.enabled ? "" : ": it is off, so this model is not used now");
  for (const [id, list] of [["emb-choices", m.choices.embedding], ["rr-choices", m.choices.reranker]]) {
    const dl = $(id);
    dl.textContent = "";
    for (const c of list) {
      const o = el("option");
      o.value = c.model;
      o.label = c.note;
      dl.appendChild(o);
    }
  }
  $("models-cache").textContent = `Models are kept in ${m.cache}.`;
  renderModelStates();
}

function readModels() {
  return { embedding_model: $("set-emb-model").value.trim(),
           reranker_model: $("set-rr-model").value.trim(),
           reranker_type: $("set-rr-type").value };
}

function downloadModel(role) {
  if (saveSettings(false)) bridge.downloadModels(role);
}

function renderRagInfo(r) {
  r = r || {};
  $("rag-index").textContent = r.configured ? (r.index || "rag.chatbot.chromadb_path is not set")
    : "No rag section in this configuration yet: choose a documentation mode and save to add one.";
  const line = $("rag-index-state");
  setIndex({ building: !!r.building, job: "models", line: r.models_line });
  if (!r.building && r.models_line) $("models-job").classList.add("warn");   // a failed download
  if (r.building && r.job !== "models") {
    setIndex({ building: true, job: "index", line: r.line });
    return;
  }
  line.className = "idx-state";
  line.textContent = "";
  if (!r.configured) return;
  const last = r.line ? ` Last build: ${r.line}.` : "";
  line.textContent = (r.index_exists ? "Index found."
    : "No index yet: build it before asking questions.") + last;
  const failed = (r.line || "").startsWith("failed");
  line.classList.add(r.index_exists && !failed ? "ok" : "warn");
}

function setStatus(p) {
  const connected = p.state === "connected";
  $("status").classList.toggle("off", !connected);
  $("status-label").textContent = p.label;
  $("status-label").title = p.title || p.label;
  $("banner").hidden = connected;
  $("banner").textContent = p.detail || "";
  $("conn-card").classList.toggle("off", !connected);
  $("conn-label").textContent = connected ? `Connected — ${p.label}` : (p.detail || p.label);
}

function setTheme(p) {
  const dark = p.theme === "dark";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("btn-theme").dataset.tip = dark ? "Light theme" : "Dark theme";
}

// ---- settings -----------------------------------------------------------
const MODULE_LABEL = { planner: "Planner", vision: "Vision", geom: "GEOM", smesh: "SMESH", shaper: "SHAPER",
                       amend: "Chat edits" };
const ENDPOINT_FIELDS = [
  ["base_url", "Base URL", null, "This module's own endpoint; empty uses the shared one"],
  ["api_key", "API key", "password", "Needed for another host: it never gets the shared key"],
  ["ssl_cert_file", "CA certificate file", null, "CA bundle for this module's endpoint; empty uses the system trust store"]];

function moduleRow(name, row, jsonOnly, sharedModel) {
  const r = el("div", "mod-row");
  r.dataset.module = name;
  const line = el("div", "mod-line");
  line.appendChild(el("span", "mod-name", MODULE_LABEL[name] || name));
  const model = el("input", "mod-model");
  model.dataset.key = "model";
  model.placeholder = sharedModel || "shared model";
  model.value = row.model || "";
  model.title = "Model for this module only; empty uses the shared model";
  line.appendChild(model);
  const link = el("button", "linkish", "other endpoint…");
  link.type = "button";
  link.title = "Another base URL / key / CA for this module; a different host does not reuse the shared key";
  line.appendChild(link);
  r.appendChild(line);
  const ep = el("div", "mod-endpoint");
  ep.hidden = !(row.base_url || row.api_key || row.ssl_cert_file);
  for (const [key, label, type, tip] of ENDPOINT_FIELDS) {
    const f = el("div", "field");
    f.title = tip;
    f.appendChild(el("label", null, label));
    const input = el("input");
    input.dataset.key = key;
    if (type) input.type = type;
    input.value = row[key] || "";
    input.dataset.orig = input.value;
    f.appendChild(input);
    ep.appendChild(f);
  }
  link.addEventListener("click", () => { ep.hidden = !ep.hidden; });
  r.appendChild(ep);
  if (jsonOnly && jsonOnly.length) {
    r.appendChild(el("div", "t-help json-only", `also set in JSON: ${jsonOnly.join(", ")}`));
  }
  return r;
}

function renderModuleRows(s) {
  const host = $("module-rows");
  host.textContent = "";
  const rows = s.modules || {};
  const names = [...(s.module_names || [])];
  for (const n of Object.keys(rows)) if (!names.includes(n)) names.push(n);
  for (const n of names) {
    host.appendChild(moduleRow(n, rows[n] || {}, (s.modules_json_only || {})[n], s.model));
  }
}

function readModuleRows() {
  const out = {};
  for (const r of $("module-rows").querySelectorAll(".mod-row")) {
    const row = {};
    for (const input of r.querySelectorAll("input[data-key]")) {
      row[input.dataset.key] = input.dataset.key === "api_key" ? input.value : input.value.trim();
    }
    out[r.dataset.module] = row;
  }
  return out;
}

// ---- documentation sources (rag.extraction.modules) ----------------------
const SOURCE_FIELDS = [
  ["description", "Description", "What this documentation covers; the agentic RAG reads it to choose where to search"],
  ["dev_path", "API reference folder", "HTML folder of the Doxygen API reference (share/doc/salome/tui/<MODULE>)"],
  ["user_path", "User guide folder", "HTML folder of the Sphinx user guide (share/doc/salome/gui/<MODULE>)"]];
const CITE_FIELDS = [
  ["cite_dev", "Online API reference URL", "Answers link API reference pages here, e.g. docs.salome-platform.org/latest/tui/GEOM"],
  ["cite_user", "Online user guide URL", "Answers link user guide pages here, e.g. docs.salome-platform.org/latest/gui/GEOM"]];
const SOURCE_NAME = /^[A-Za-z0-9][\w.+-]*$/;

function pathState(st) {
  if (!st || st.state === "empty") return null;
  const line = el("div", "src-state " + st.state);
  line.textContent = st.state === "ok" ? `found: ${st.resolved}`
    : st.state === "unset" ? `not set here: ${st.vars.map((v) => "$" + v).join(", ")} (start SALOME's environment)`
    : `not found: ${st.resolved}`;
  return line;
}

function sourceRow(row) {
  const r = el("div", "src-row");
  r.dataset.orig = row.name || "";
  const head = el("div", "mod-line");
  const name = el("input");
  name.dataset.key = "name";
  name.placeholder = "Name, e.g. GEOM";
  name.title = "Module name: shown with each cited page and used to filter the search";
  name.value = row.name || "";
  head.appendChild(name);
  const cite = el("button", "linkish", "online links…");
  cite.type = "button";
  cite.title = "Where answers link the pages of this source on the web";
  head.appendChild(cite);
  const del = el("button", "linkish", "remove");
  del.type = "button";
  del.title = "Leave this source out of the next index build";
  del.addEventListener("click", () => r.remove());
  head.appendChild(del);
  r.appendChild(head);
  const field = ([key, label, tip], parent) => {
    const f = el("div", "field");
    f.title = tip;
    f.appendChild(el("label", null, label));
    const input = el("input");
    input.dataset.key = key;
    input.value = row[key] || "";
    f.appendChild(input);
    parent.appendChild(f);
    return f;
  };
  for (const spec of SOURCE_FIELDS) {
    field(spec, r);
    const short = spec[0] === "dev_path" ? "dev" : spec[0] === "user_path" ? "user" : null;
    const st = short && pathState(row[short + "_state"]);
    if (st) r.appendChild(st);
  }
  const box = el("div", "src-cite");
  box.hidden = !!row.name;                    // a new source shows them
  for (const spec of CITE_FIELDS) field(spec, box);
  cite.addEventListener("click", () => { box.hidden = !box.hidden; });
  r.appendChild(box);
  if (row.json_only && row.json_only.length) {
    r.appendChild(el("div", "t-help json-only", `also set in JSON: ${row.json_only.join(", ")}`));
  }
  return r;
}

function renderSources(rows) {
  const host = $("doc-sources");
  host.textContent = "";
  for (const row of rows || []) host.appendChild(sourceRow(row));
  $("sources-error").hidden = true;
}

function readSources() {
  const out = [];
  for (const r of $("doc-sources").querySelectorAll(".src-row")) {
    const row = { orig: r.dataset.orig };
    for (const input of r.querySelectorAll("input[data-key]")) row[input.dataset.key] = input.value.trim();
    out.push(row);
  }
  return out;
}

// mirrors config_store._save_doc_sources
function sourcesError(rows) {
  const seen = new Set();
  for (const row of rows) {
    if (!row.name && !row.description && !row.dev_path && !row.user_path) continue;
    if (!SOURCE_NAME.test(row.name)) {
      return row.name ? `Source name "${row.name}": use letters, digits, _ . + - (no spaces).`
        : "Every documentation source needs a name.";
    }
    if (seen.has(row.name)) return `Documentation source "${row.name}" is listed twice.`;
    seen.add(row.name);
    if (!row.dev_path && !row.user_path) return `Source "${row.name}": give at least one folder.`;
  }
  return "";
}

// mirrors config_store._save_modules: another host never gets the shared key;
// only rows whose endpoint was edited here are checked
function modulesError(shared, sharedUrl) {
  if (shared) return "";
  const base = sharedUrl.replace(/\/+$/, "");
  for (const r of $("module-rows").querySelectorAll(".mod-row")) {
    const field = (key) => r.querySelector(`.mod-endpoint input[data-key=${key}]`);
    const edited = ["base_url", "api_key"].some((k) => field(k).value.trim() !== field(k).dataset.orig.trim());
    const url = field("base_url").value.trim().replace(/\/+$/, "");
    if (edited && url && url !== base && !field("api_key").value.trim()) {
      const name = r.dataset.module;
      return `${MODULE_LABEL[name] || name}: a different endpoint needs its own API key`;
    }
  }
  return "";
}

// documentation-mode knobs: [input id, rag_options key, modes that show it]
const RAG_NUMBERS = [
  ["set-rag-k", "k_standard", ["rag"]],
  ["set-rag-top", "top_n_after_rerank", ["rag"]],
  ["set-rag-expand", "expansion_char_budget", ["rag"]],
  ["set-rag-tokens", "max_tokens", ["rag", "rag_agentic"]],
  ["set-ag-steps", "max_steps", ["rag_agentic"]],
  ["set-ag-page", "max_chars_per_page", ["rag_agentic"]],
  ["set-ag-sections", "section_top_n", ["rag_agentic"]],
  ["set-ag-budget", "section_char_budget", ["rag_agentic"]],
];
const RAG_SWITCHES = [
  ["set-rag-reranker", "reranker", ["rag", "rag_agentic"]],
  ["set-rag-bm25", "bm25_enabled", ["rag", "rag_agentic"]],
  ["set-rag-title", "title_boost_enabled", ["rag", "rag_agentic"]],
  ["set-rag-hyde", "hyde_enabled", ["rag"]],
];

// the drawer shows the options of the mode the Assistant select holds
function showDrawerMode(mode) {
  for (const n of $("drawer").querySelectorAll("[data-modes]")) {
    n.hidden = !n.dataset.modes.split(" ").includes(mode);
  }
}

function readRagOptions(mode) {
  const out = {};
  for (const [id, key, modes] of RAG_NUMBERS) {
    const v = parseInt($(id).value, 10);
    if (modes.includes(mode) && !Number.isNaN(v)) out[key] = v;
  }
  for (const [id, key, modes] of RAG_SWITCHES) {
    if (modes.includes(mode)) out[key] = $(id).classList.contains("on");
  }
  const t = parseFloat($("set-rag-temp").value);
  if (!Number.isNaN(t)) out.temperature = t;
  return out;
}

function lockRunOptions(locked) {
  state.locked = locked;
  for (const id of ["set-mode", "set-on-failure", "set-tools", "set-verbose", "set-detail",
                    "set-cadence", "set-cap", "set-budget", "set-vision-fix",
                    "set-timeout", "set-rag-temp", "set-emb-model", "set-rr-model", "set-rr-type",
                    ...RAG_NUMBERS.map((r) => r[0])]) $(id).disabled = locked;
  for (const [id] of RAG_SWITCHES) $(id).classList.toggle("disabled", locked);
  for (const input of $("module-rows").querySelectorAll("input")) input.disabled = locked;
  $("set-batch").classList.toggle("disabled", locked);
  $("set-shared").classList.toggle("disabled", locked);
  $("auto").classList.toggle("disabled", locked);
  $("btn-load-config").disabled = locked;
  const building = !!(state.settings && state.settings.rag && state.settings.rag.building);
  for (const role of ["embedding", "reranker"]) $(`btn-dl-${role}`).disabled = locked || building;
  $("run-lock").hidden = !locked;
  $("mode-lock").hidden = !locked;
  $("model-lock").hidden = !locked;
  for (const n of $("drawer").querySelectorAll(".lock-note:not([id])")) n.hidden = !locked;
}

function setSettings(s) {
  state.settings = s;
  $("set-base-url").value = s.base_url || "";
  $("set-model").value = s.model || "";
  $("set-api-key").value = s.api_key || "";
  $("set-ssl-cert").value = s.ssl_cert_file || "";
  $("set-on-failure").value = s.on_stage_failure;
  $("set-tools").value = s.tool_selection;
  $("set-verbose").value = String(s.verbose);
  $("set-detail").value = s.plan_detail || "balanced";
  $("set-cadence").value = s.verify_cadence || "final";
  $("set-cap").value = String(s.tool_iteration_cap ?? 12);
  $("set-theme").value = s.theme;
  $("set-mode").value = s.mode || "agent";
  showDrawerMode($("set-mode").value);
  const rag = s.rag_options || {};
  for (const [id, key] of RAG_NUMBERS) $(id).value = rag[key] == null ? "" : String(rag[key]);
  for (const [id, key] of RAG_SWITCHES) $(id).classList.toggle("on", !!rag[key]);
  $("set-rag-temp").value = rag.temperature == null ? "" : String(rag.temperature);
  setDocMode(DOC_MODES.includes(s.active_mode));
  renderModeSwitch(s.active_mode, s.can_switch_mode, s.mode_order);
  renderSources(s.doc_sources);
  renderModels(s.rag_models);
  renderRagInfo(s.rag);
  $("set-batch").classList.toggle("on", !!s.batch);
  $("batch-sw").classList.toggle("on", !!s.batch);
  $("set-reasoning").classList.toggle("on", !!s.show_reasoning);
  document.body.classList.toggle("show-reasoning", !!s.show_reasoning);
  const shared = s.shared_model !== false;
  $("set-shared").classList.toggle("on", shared);
  renderModuleRows(s);
  $("module-rows").hidden = shared;
  $("models-error").hidden = true;
  $("set-budget").value = String(s.reasoning_budget ?? 20000);
  $("set-vision-fix").value = String(s.vision_fix_retries ?? 2);
  $("set-timeout").value = String(s.timeout ?? 120);
  $("config-path").textContent = s.config_path || "";
  lockRunOptions(!!s.locked);
}

function openSettings() { document.body.classList.add("settings-open"); }
function closeSettings() { document.body.classList.remove("settings-open"); }
function cancelSettings() { if (state.settings) setSettings(state.settings); closeSettings(); }

// close: false keeps the drawer open (Build index saves what it shows first)
function saveSettings(close = true) {
  const out = {
    base_url: $("set-base-url").value.trim(),
    model: $("set-model").value.trim(),
    api_key: $("set-api-key").value,
    ssl_cert_file: $("set-ssl-cert").value.trim(),
    theme: $("set-theme").value,
    show_reasoning: $("set-reasoning").classList.contains("on"),
  };
  if (!state.locked) {
    const shared = $("set-shared").classList.contains("on");
    const modules = readModuleRows();
    const err = modulesError(shared, out.base_url);
    if (err) {
      $("models-error").textContent = err;
      $("models-error").hidden = false;
      return false;
    }
    Object.assign(out, {
      mode: $("set-mode").value,
      batch: $("set-batch").classList.contains("on"),
      on_stage_failure: $("set-on-failure").value,
      tool_selection: $("set-tools").value,
      verbose: parseInt($("set-verbose").value, 10),
      plan_detail: $("set-detail").value,
      verify_cadence: $("set-cadence").value,
      tool_iteration_cap: parseInt($("set-cap").value, 10),
      shared_model: shared,
      modules,
      reasoning_budget: parseInt($("set-budget").value, 10),
      vision_fix_retries: parseInt($("set-vision-fix").value, 10),
      timeout: parseInt($("set-timeout").value, 10),
    });
    // a documentation mode's options go to rag.chatbot; the agent mode leaves them alone
    if (DOC_MODES.includes(out.mode)) {
      out.rag_options = readRagOptions(out.mode);
      out.rag_models = readModels();
    }
  }
  // the sources feed the index build, not an open conversation: saved even when locked
  if (DOC_MODES.includes($("set-mode").value)) {
    const sources = readSources();
    const err = sourcesError(sources);
    if (err) {
      $("sources-error").textContent = err;
      $("sources-error").hidden = false;
      $("sources-error").scrollIntoView({ block: "center" });
      return false;
    }
    out.doc_sources = sources;
  }
  bridge.saveSettings(JSON.stringify(out));
  if (close) closeSettings();
  return true;
}

// ---- composer -----------------------------------------------------------
function autosize() {
  const t = $("input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 180) + "px";
}

function showHint() {
  hintTimer = null;
  const h = $("hint");
  h.classList.remove("error");
  h.textContent = state.stopping ? "Stopping…"
    : (state.busy ? "Working… press Stop to cancel" : HINT);
}

function showError(text) {
  const h = $("hint");
  h.textContent = text;
  h.classList.add("error");
  clearTimeout(hintTimer);
  hintTimer = setTimeout(showHint, 5000);
}

// ---- attached images -----------------------------------------------------
function renderAttachments() {
  const box = $("attachments");
  box.textContent = "";
  attached.forEach((a, i) => {
    const t = el("div", "thumb");
    t.appendChild(imageNode(a.url, a.name));
    const x = el("button", "remove");
    x.title = "Remove " + a.name;
    svg(x, "fail");
    x.addEventListener("click", () => { attached.splice(i, 1); renderAttachments(); });
    t.appendChild(x);
    box.appendChild(t);
  });
  box.hidden = attached.length === 0;
}

function readFile(file, how = "readAsDataURL") {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    r[how](file);
  });
}

// the image as a data: URI labelled with the type its bytes show, or null
async function imageUrl(file) {
  const mime = imageMime(new Uint8Array(await readFile(file.slice(0, 16), "readAsArrayBuffer")));
  if (!mime) return null;
  const url = await readFile(file);
  return `data:${mime};base64,` + url.slice(url.indexOf(",") + 1);
}

async function attachFiles(files) {
  const errors = [];
  for (const f of files) {
    if (attached.reduce((n, a) => n + a.size, f.size) > MAX_IMAGES_MB * 1024 * 1024) {
      errors.push(`${f.name} would take this message past ${MAX_IMAGES_MB} MB of images`);
    } else if (attached.length >= MAX_IMAGES) {
      errors.push(`At most ${MAX_IMAGES} images per message`);
      break;
    } else {
      let url = null;
      try {
        url = await imageUrl(f);
      } catch (e) {
        errors.push(`Could not read ${f.name}`);
        continue;
      }
      if (url) attached.push({ name: f.name || "pasted image", size: f.size, url });
      else errors.push(`${f.name || "That file"} is not a PNG, JPEG, WEBP, GIF or BMP image`);
    }
  }
  renderAttachments();
  if (errors.length) showError(errors[0]);
  $("input").focus();
}

function hasFiles(e) { return e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files"); }

// ---- image viewer ---------------------------------------------------------
function openLightbox(url) {
  $("lightbox-img").src = url;
  $("lightbox").hidden = false;
}
function closeLightbox() {
  $("lightbox").hidden = true;
  $("lightbox-img").removeAttribute("src");
}

function submit() {
  if (state.busy) {
    if (!state.stopping) bridge.stop();
    return;
  }
  const text = $("input").value.trim();
  if ((!text && !attached.length) || !state.canSend) return;
  bridge.send(text, JSON.stringify(attached.map((a) => a.url)));
  $("input").value = "";
  attached = [];
  renderAttachments();
  autosize();
}

function tick() {
  const now = Date.now() / 1000;
  document.querySelectorAll("[data-start]").forEach((m) => {
    m.textContent = fmtClock(now - parseFloat(m.dataset.start));
  });
}

function wire() {
  $("btn-undo").addEventListener("click", () => bridge.command("undo"));
  $("btn-redo").addEventListener("click", () => bridge.command("redo"));
  $("btn-rebuild").addEventListener("click", () => bridge.command("rebuild"));
  $("btn-new").addEventListener("click", () => bridge.command("new"));
  $("btn-theme").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme === "dark";
    bridge.saveSettings(JSON.stringify({ theme: dark ? "light" : "dark" }));
  });
  $("btn-help").addEventListener("click", () => { $("help").hidden = !$("help").hidden; });
  $("btn-settings").addEventListener("click", openSettings);
  for (const id of ["btn-close-settings", "btn-cancel", "scrim"]) $(id).addEventListener("click", cancelSettings);
  $("btn-save").addEventListener("click", () => saveSettings());
  $("btn-reconnect").addEventListener("click", () => bridge.reconnect());
  $("btn-edit-json").addEventListener("click", () => bridge.editConfigJson());
  $("btn-load-config").addEventListener("click", () => bridge.loadConfig());
  $("btn-build-index").addEventListener("click", () => { if (saveSettings(false)) bridge.buildIndex(); });
  $("btn-dl-embedding").addEventListener("click", () => downloadModel("embedding"));
  $("btn-dl-reranker").addEventListener("click", () => downloadModel("reranker"));
  $("set-emb-model").addEventListener("input", renderModelStates);
  $("set-rr-type").addEventListener("change", renderModelStates);
  $("set-rr-model").addEventListener("input", () => {
    // a model from raglib's list brings its type
    const known = (((state.settings || {}).rag_models || {}).choices || { reranker: [] }).reranker
      .find((c) => c.model === $("set-rr-model").value.trim());
    if (known) $("set-rr-type").value = known.type;
    renderModelStates();
  });
  $("btn-add-source").addEventListener("click", () => {
    const r = sourceRow({});
    $("doc-sources").appendChild(r);
    r.querySelector("input").focus();
  });
  $("set-reasoning").addEventListener("click", () => $("set-reasoning").classList.toggle("on"));
  $("set-shared").addEventListener("click", () => {
    if (state.locked) return;
    $("module-rows").hidden = $("set-shared").classList.toggle("on");
    $("models-error").hidden = true;
  });
  $("set-mode").addEventListener("change", () => showDrawerMode($("set-mode").value));
  for (const b of $("mode-switch").querySelectorAll("button")) {
    b.addEventListener("click", () => { if (!b.disabled && !b.classList.contains("on")) bridge.setMode(b.dataset.mode); });
  }
  showDrawerMode($("set-mode").value);
  for (const [id] of RAG_SWITCHES) {
    $(id).addEventListener("click", () => { if (!state.locked) $(id).classList.toggle("on"); });
  }
  $("set-batch").addEventListener("click", () => {
    if (!state.locked) $("set-batch").classList.toggle("on");
  });
  $("auto").addEventListener("click", () => {
    if (state.locked) return;
    const on = !$("batch-sw").classList.contains("on");
    $("batch-sw").classList.toggle("on", on);
    bridge.saveSettings(JSON.stringify({ batch: on }));
  });
  const input = $("input");
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  });
  $("send").addEventListener("click", submit);
  $("btn-attach").addEventListener("click", () => $("file").click());
  $("file").addEventListener("change", () => {
    const files = Array.from($("file").files);
    $("file").value = "";
    attachFiles(files);
  });
  input.addEventListener("paste", (e) => {
    const files = Array.from(e.clipboardData ? e.clipboardData.files : []);
    if (!files.length) return;
    e.preventDefault();
    attachFiles(files);
  });
  // Every drop is handled here: one the page left alone would navigate away.
  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    dragDepth += 1;
    document.body.classList.add("dragging");
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) document.body.classList.remove("dragging");
  });
  window.addEventListener("dragover", (e) => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = hasFiles(e) ? "copy" : "none";
  });
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove("dragging");
    if (hasFiles(e)) attachFiles(Array.from(e.dataTransfer.files));
  });
  $("lightbox").addEventListener("click", closeLightbox);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("lightbox").hidden) closeLightbox();
  });
  document.querySelectorAll(".suggestion").forEach((s) => s.addEventListener("click", () => {
    input.value = s.dataset.text;
    autosize();
    input.focus();
  }));
  setInterval(tick, 1000);
}

const handlers = {
  addUser: (p) => append(userNode(p.text, p.images)),
  addNote: (p) => append(noteNode(p.text)),
  renderTurn,
  appendReasoning,
  setBusy,
  setStatus,
  setSettings,
  setTheme,
  setIndex,
  reset: () => { col().textContent = ""; updateEmpty(); },
  replay,
};

function boot() {
  wire();
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bridge.push.connect((name, payload) => {
      const handler = handlers[name];
      if (handler) handler(JSON.parse(payload));
    });
    bridge.ready();
  });
}

document.addEventListener("DOMContentLoaded", boot);
