# Model reasoning in the chat — design

Date: 2026-09-25. Covers task 263 (debug option to show the model's reasoning in
the chat). Spans both repos: salome-agent emits the text, salome-agent-gui shows it.

## Goal

A debug switch that shows, live while the model is still generating, what the
model is thinking: the provider's `reasoning_content` and the short prose a
specialist writes next to its tool calls. Collapsed by default, one block per
source (planner, each stage, a chat edit), text only.

Motivation: during a long reasoning call the chat shows nothing but a running
clock (session 53: several minutes, then Stop). Today the reasoning only reaches
`llm_trace.jsonl` at `-vv`, after the call, and is dropped from the history on
purpose.

## Decisions

- **Engine emits a UI event; the GUI does not tail `llm_trace.jsonl`.** The trace
  needs `-vv`, file polling and parsing, and is only written per finished call.
- **Live, as it streams.** Not per finished call, not at stage end.
- **Reasoning and tool-turn prose.** `content` deltas are forwarded only on calls
  that offer tools (specialists). The planner's `content` is its JSON plan,
  already shown as the plan card, so it is not forwarded; its `reasoning_content` is.
- **Always emitted, shown on demand.** The engine always sends the event; the GUI
  switch only hides or shows it. Turning the switch on mid-turn shows everything
  received so far. `reasoning_content` stays out of the history sent back to the
  model (unchanged).
- **Not a run option.** The switch is saved immediately like the theme and is
  not locked while a conversation is open.

## Engine (salome-agent)

### Stream hook on `LLMClient`

`LLMClient.on_stream` (default `None`), installed by `runner.drive()` for the
turn and reset in its `finally`, exactly like `LLMClient.cancel` (GH #47).
`_round_trip` / `_consume_stream` call it with one dict per happening:

- `{"type": "start", "module": <module arg of chat()>}` once per `chat()`
  round-trip, before the POST (a retried attempt does not start a new call).
- `{"type": "delta", "channel": "reasoning" | "prose", "text": str}` for each
  non-empty `reasoning_content` delta, and for each `content` delta when the
  request carries tools.
- `{"type": "end"}` when the call returns or raises.

A hook exception is logged and ignored: a display problem must never fail a
model call. No hook installed costs one `None` check per line.

A retried attempt re-streams from scratch; its deltas are appended to the same
call (the GUI may show the dropped attempt's partial text followed by the
retry's). Accepted: rare, and it is what actually happened.

### Throttle in `drive()`

`drive()` wraps the hook in a small buffer: deltas of one call and channel are
concatenated and emitted as one event at most every 0.5 s, plus a flush on
`end`. A channel switch flushes the other channel first, so order is kept. The
clock is injectable for tests.

### The `reasoning` event

```
{"kind": "reasoning", "run_id": ..., "data": {
    "source": "planner" | "stage" | "edit",
    "index": <stage index> | None,
    "call": <per-turn call counter, from 1>,
    "channel": "reasoning" | "prose",
    "text": <chunk to append>}}
```

`EventMapper.reasoning(module, call, channel, text)` fills `source`/`index`:
`module == "planner"` -> `planner`; otherwise a plan exists this turn -> `stage`
with the mapper's current index; otherwise (an amend turn) -> `edit`. The mapper
is per turn (Conversation) / per run (run_request), so the call counter is too.

`chat.py`'s `-v` printer and `cli.py` already ignore unknown event kinds; no
change there.

## GUI (salome-agent-gui)

### Setting

`gui.show_reasoning` (bool, default false) in `config_store.read_settings` /
`save_settings`, saved outside the `run_options` lock. Settings drawer, under
Log detail: a switch "Show model reasoning" with help text "Debug: what the model
thinks while it works". JS toggles `body.show-reasoning`; CSS hides
`.reasoning` otherwise.

### View model

`RunView.reasoning`: ordered blocks keyed `planner`, `stage:<i>`, `edit`, each a
list of calls `{"call": n, "reasoning": str, "prose": str}`. A retried stage
(verify failure, `run_stage` again) keeps adding calls to the same stage block.
`apply({"kind": "reasoning"})` appends the chunk to the right call, creating the
block or call when new. `to_view_model` exposes them: the planner block on the
turn, each stage's block on its stage view, the edit block on the edits view.

### Rendering

A collapsed `<details class="reasoning" data-key="<turn>:<key>">`:

- planner block at the top of the stages card;
- stage block inside its step row, under the stage line;
- edit block in the edits card.

Summary: "Reasoning · N calls". Body: calls
separated by a thin rule; reasoning in muted pre-wrap text, prose in normal
text. All text through `textContent`. Body has a max height and scrolls inside.

### Streaming path

A `reasoning` event does not call `_render()`. The bridge applies it to the
`RunView` and pushes `appendReasoning({turn, key, call, channel, text})`; JS
appends to the matching node, creating the block/call when missing, and keeps
the block pinned to its bottom if it was scrolled there.

A full `renderTurn` (other events, gates, replay) rebuilds from the view model
and keeps open/closed state from a JS set of open `data-key`s.

## Testing

Engine (unit):
- `_consume_stream` calls the hook with reasoning deltas, prose deltas only with
  tools, start/end around the call (end also on error and cancel); a raising hook
  does not break the call.
- Throttle: fake clock; merges within 0.5 s, flushes on end and channel switch.
- `EventMapper.reasoning`: planner / stage index / edit.
- `drive()` installs and removes the hook.

GUI (unit):
- `RunView.apply` + `to_view_model` for the three sources, several calls on one
  stage, both channels.
- `config_store` round-trip of `show_reasoning`, saved while run options locked.
- Bridge: a `reasoning` event pushes `appendReasoning`, not `renderTurn`.

Live: a reasoning-on model in the SALOME chat; the switch on shows the planner
block filling during planning and each stage's block filling while it runs;
collapse state survives stage transitions; switch off hides everything.

## Out of scope

- Showing reasoning in the terminal chat (`salome-agent chat`).
- Sending reasoning back to the model.
- Task 268 (stage_start timing) — related, separate.
