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
               skipped: ["st skip", "skip"], pending: ["st pend", null] };
const LEAD = { needs_input: "Question", failed: "Turn failed", fatal: "Run failed",
               degraded: "Study out of sync", ended: "Session ended", aborted: "Run aborted" };
const TONE = { ok: "ok", needs_input: "info", degraded: "warn", ended: "warn", aborted: "muted" };

let bridge = null;
const state = { busy: false, open: false, canSend: false, stopping: false, locked: false, settings: null };
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

function userNode(text) {
  const d = el("div", "msg-user");
  d.appendChild(el("div", "bubble", text));
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

// Between an approval (or a finished stage) and the next stage_start the
// engine is already working on the next pending step: show it spinning.
function nextStepIndex(vm) {
  if (vm.status !== "running" || vm.gate || vm.stages.some((s) => s.status === "running")) return -1;
  const next = vm.stages.find((s) => s.status === "pending");
  return next ? next.index : -1;
}

function stepRow(s, vm) {
  const shown = s.status === "pending" && s.index === nextStepIndex(vm) ? "running" : s.status;
  const li = el("li", "step" + (shown === "pending" ? " pending" : ""));
  const [cls, icon] = STEP[shown] || STEP.pending;
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
    const known = ["geom", "smesh", "paravis"].includes(s.module) ? " " + s.module : "";
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
    if (s.status === "failed" && s.attempts > 0) bits.push(plural(s.attempts, "attempt"));
    else if (s.attempts > 1) bits.push(`${ordinal(s.attempts)} attempt`);
    meta.textContent = bits.join(" · ");
  }
  line.appendChild(meta);
  main.appendChild(line);
  const gateShowsError = vm.gate && vm.gate.kind === "stage_failed";
  if (s.error && s.status === "failed" && !gateShowsError) main.appendChild(el("div", "err", s.error));
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

function editsCard(edits) {
  const card = el("div", "card");
  const head = el("div", "card-head");
  const changes = edits.filter((e) => e.op !== "replay");
  const replay = edits.find((e) => e.op === "replay");
  head.appendChild(el("span", null, "Changes"));
  let count = `· ${plural(changes.length, "edit")}`;
  if (replay) count += `, ${plural(replay.nodes.length, "object")} rebuilt`;
  head.appendChild(el("span", "count", count));
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
  if (vm.objects.length) {
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
  if (gate && gate.kind === "plan") {
    const t = el("div", "agent-text", "Here's the plan. ");
    t.appendChild(el("span", "muted", "Approve it to start building, or edit the stages first."));
    body.appendChild(t);
  }
  if (vm.stages.length) body.appendChild(stagesCard(vm));
  if (vm.edits.length) body.appendChild(editsCard(vm.edits));
  if (gate && gate.kind === "stage_failed") body.appendChild(failCard(vm, gate));
  if (!gate && vm.status !== "running") body.appendChild(resultBlock(vm));
  if (!vm.stages.length && !vm.edits.length && !gate && vm.status === "running") {
    body.appendChild(el("div", "agent-text muted", "Thinking…"));
  }
  return wrap;
}

function renderTurn(vm) {
  const node = turnNode(vm);
  const old = col().querySelector(`[data-turn="${vm.id}"]`);
  if (!old) { append(node); return; }
  const stick = nearBottom();
  old.replaceWith(node);
  if (stick) scrollEnd();
}

function replay(p) {
  col().textContent = "";
  for (const it of p.items) {
    if (it.type === "user") col().appendChild(userNode(it.text));
    else if (it.type === "note") col().appendChild(noteNode(it.text));
    else col().appendChild(turnNode(it.vm));
  }
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
  $("hint").textContent = p.stopping ? "Stopping…"
    : (p.busy ? "Working… press Stop to cancel" : "Enter to send · Shift+Enter for a new line");
  lockRunOptions(p.open);
}

function setStatus(p) {
  const connected = p.state === "connected";
  $("status").classList.toggle("off", !connected);
  $("status-label").textContent = p.label;
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
function lockRunOptions(locked) {
  state.locked = locked;
  for (const id of ["set-on-failure", "set-tools", "set-verbose"]) $(id).disabled = locked;
  $("set-batch").classList.toggle("disabled", locked);
  $("auto").classList.toggle("disabled", locked);
  $("run-lock").hidden = !locked;
}

function setSettings(s) {
  state.settings = s;
  $("set-base-url").value = s.base_url || "";
  $("set-model").value = s.model || "";
  $("set-api-key").value = s.api_key || "";
  $("set-on-failure").value = s.on_stage_failure;
  $("set-tools").value = s.tool_selection;
  $("set-verbose").value = String(s.verbose);
  $("set-theme").value = s.theme;
  $("set-batch").classList.toggle("on", !!s.batch);
  $("batch-sw").classList.toggle("on", !!s.batch);
  $("config-path").textContent = s.config_path || "";
  lockRunOptions(!!s.locked);
}

function openSettings() { document.body.classList.add("settings-open"); }
function closeSettings() { document.body.classList.remove("settings-open"); }
function cancelSettings() { if (state.settings) setSettings(state.settings); closeSettings(); }

function saveSettings() {
  const out = {
    base_url: $("set-base-url").value.trim(),
    model: $("set-model").value.trim(),
    api_key: $("set-api-key").value,
    theme: $("set-theme").value,
  };
  if (!state.locked) {
    Object.assign(out, {
      batch: $("set-batch").classList.contains("on"),
      on_stage_failure: $("set-on-failure").value,
      tool_selection: $("set-tools").value,
      verbose: parseInt($("set-verbose").value, 10),
    });
  }
  bridge.saveSettings(JSON.stringify(out));
  closeSettings();
}

// ---- composer -----------------------------------------------------------
function autosize() {
  const t = $("input");
  t.style.height = "auto";
  t.style.height = Math.min(t.scrollHeight, 180) + "px";
}

function submit() {
  if (state.busy) {
    if (!state.stopping) bridge.stop();
    return;
  }
  const text = $("input").value.trim();
  if (!text || !state.canSend) return;
  bridge.send(text);
  $("input").value = "";
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
  $("btn-save").addEventListener("click", saveSettings);
  $("btn-reconnect").addEventListener("click", () => bridge.reconnect());
  $("btn-edit-json").addEventListener("click", () => bridge.editConfigJson());
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
  document.querySelectorAll(".suggestion").forEach((s) => s.addEventListener("click", () => {
    input.value = s.dataset.text;
    autosize();
    input.focus();
  }));
  setInterval(tick, 1000);
}

const handlers = {
  addUser: (p) => append(userNode(p.text)),
  addNote: (p) => append(noteNode(p.text)),
  renderTurn,
  setBusy,
  setStatus,
  setSettings,
  setTheme,
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
