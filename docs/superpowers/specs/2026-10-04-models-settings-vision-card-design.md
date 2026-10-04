# Models settings + "Reading image" card — design

Date: 2026-10-04. Spans two repos: the engine (salome-agent, submodule) and salome-agent-gui.

## Why

salome-agent-gui has not followed the engine. Since the settings drawer was built, the engine gained:

- `llm.modules.<module>`: a per-module endpoint/model override (e.g. a better drawing reader for vision);
- `llm.reasoning_budget`, `llm.vision_fix_retries`;
- the vision step (structured image spec + validator fix loop), which can take several minutes.

In the GUI these are reachable only through "Edit JSON…", the header shows only the shared model, and the
vision step emits no event: the timeline sits silent while the image is read. Its streamed reasoning is
filed under the wrong key (no vision branch in the reasoning source).

Success: set a vision model override from the drawer, send p1 with the image, see vision run on that model in
the header and in a live "Reading image" card with its fix rounds, then build.

## Part 1 — engine (salome-agent, branch `feat/vision-events`)

### Live progress out of a node

`runner.drive()` streams with `stream_mode="updates"`, so the event mapper hears of a node only once it has
finished. Switch to `stream_mode=["updates", "custom"]` (LangGraph 1.2.11): a node calls
`langgraph.config.get_stream_writer()` and its dict reaches `drive()` at once. `custom` chunks are
already-shaped events and go to `on_event` through the mapper (`mapper.event(kind, **data)`) unchanged.

### Vision events

`nodes.vision.describe_images(..., on_progress=None)`: an optional callback `on_progress(kind, **data)`.
`_describe_image_node` wires it to the stream writer. The CLI and existing callers pass nothing.

| kind | data | when |
|---|---|---|
| `vision_start` | `images` (int), `sizes` (list of `"WxH"`, unknown sizes left out), `model` (the model vision actually calls, override included) | before the first vision call |
| `vision_check` | `attempt` (1-based), `of` (fix_retries), `errors` (list of str, the validator messages) | each validator pass that finds problems and leads to a fix call |
| `vision_done` | `parts` (int), `conflicts` (int, errors left attached as conflicts), `seconds` (float, wall) | spec returned |

An endpoint failure keeps today's path (`fatal` event). The model name comes from a small `LLMClient`
accessor that resolves the module override (`model_for("vision")`).

### Vision reasoning source

`EventMapper.reasoning()`: `module == "vision"` gives `source="vision"`, `index=None`. Today it falls through
to `edit` (no plan yet) or to the current stage.

### Module names for front ends

`salome_agent.modules.llm_module_names()` returns `["planner", "vision", *registered specialist names]` in
registry order (today: geom, smesh, paravis, amend). These are the names `llm.modules` accepts.

### Engine tests

- `describe_images` with a fake LLM: event sequence for a clean pass, one fix round, fixes exhausted (conflicts).
- `drive()`: a node writing a custom chunk reaches `on_event`, ordered before that node's update events.
- `EventMapper.reasoning("vision", ...)` gives source `vision`.
- `llm_module_names()` content.
- Goldens byte-identical: the CLI prints nothing new.

Out of scope: an early `stage_start` through the same custom stream (task 268). Cheap once this lands;
follow-up.

## Part 2 — salome-agent-gui (branch `feat/models-settings`)

Starts with a submodule bump to the merged engine commit, verified with `git ls-tree HEAD salome-agent`.

### Settings drawer, "Model" section

- The existing fields stay and are the shared endpoint: base URL, model, API key, CA file.
- New switch **"Same model for every module"**. On when `llm.modules` is empty or absent.
- Switch off: one row per name from `llm_module_names()`. Known names get a label ("amend" -> "Chat edits",
  others capitalised); an unknown name shows raw. Each row: a model field (placeholder = the shared model)
  and an "other endpoint…" link that reveals base URL / API key / CA file for that row, with the note
  "A different endpoint does not reuse the shared key."
- **Advanced** fold (collapsed): reasoning budget (approx tokens, 0 = off), vision fix rounds, LLM timeout (s).
  Written to `llm.reasoning_budget`, `llm.vision_fix_retries`, `llm.timeout`. Clamped like the policy ints:
  reasoning_budget 0..200000 (default 20000), vision_fix_retries 0..5 (default 2), timeout 10..1800 (default 120).
- The Models rows and Advanced are run options: locked while a conversation is open (the engine builds its LLM
  client once per conversation), like the "Runs" section.

### Config file (`config_store`)

- A row with an empty model and no endpoint fields is not written. A row writes only its non-empty fields,
  merged into the existing `llm.modules.<m>` dict, so keys the form does not show (`extra_body`,
  `extra_headers`, `temperature`) survive a save. Clearing a row removes the keys the form owns; an emptied
  dict is removed. Those hidden keys are often deliberate provider tuning (reasoning effort, thinking on/off
  in `extra_body`), so the form never deletes what it cannot show; instead a row holding such keys shows a
  line `also set in JSON: extra_body, temperature`, which stays after the row is cleared, so the module is
  visibly not fully inherited.
- Save refused, message shown in the drawer: a row with a base URL and no API key.
- Switch on + Save: `llm.modules` moves to `gui.parked_modules` (merged, not overwritten). Switch off: the rows
  refill from `gui.parked_modules`, and Save moves them back to `llm.modules`. The engine never reads `gui`.
- `read_settings` stays non-raising (broken file reads as defaults).

### Header label

`MODE :port · <shared model>`, plus ` · vision: <model>` when one module is overridden. With two or more:
` · +N overrides`, the full list in the tooltip. A row overriding only the endpoint shows its model as the
shared one.

### Drift guard

A test imports `LLM_KNOWN_KEYS` and `MODULE_LLM_KEYS` from the engine and asserts each key is either handled
by the form or listed in `config_store.JSON_ONLY` (`extra_headers`, `extra_body`, `module_extra_body`,
`json_retries`, `max_retries`, `temperature`). A submodule bump that adds a key fails the test, naming it.

### "Reading image" card

`RunView.vision`: `None` until `vision_start`, then
`{status: running|done|conflicts|failed, images, sizes, model, checks: [{attempt, of, errors}], parts,
conflicts, started_at, elapsed_s}`. `vision_check` appends to `checks`. `vision_done` sets `done`, or
`conflicts` when conflicts > 0. A `fatal` while running sets `failed`.

Drawn above the stage cards, stage-card style, image icon, live timer while running:

- running: `Reading image · 1200×800 · <model> · 2:14`
- per check: `Fix round 1/2: 3 problems`, the messages in a collapsed list
- done: `Read 3 parts · 3:52`; conflicts (amber): `Read 3 parts, 2 problems left for the build`
- failed: the fatal message, as stage failures show theirs

It stays above the plan gate, so what vision read is visible before approving the plan.

Vision reasoning: `reasoning_key` maps source `vision` to key `vision`. The view model's turn-level reasoning
excludes it, and the vision card draws it inside itself, as stage cards do.

### GUI tests

- `test_config_store`: rows written/omitted, merge keeps unknown module keys (and reports them for the
  "also set in JSON" line), park/unpark round trip,
  key-required refusal, Advanced clamps, drift guard.
- `test_timeline`: vision sequences (clean, fix rounds, conflicts, fatal while running) to view model;
  vision reasoning key.
- `test_bridge`: settings round trip with modules; header label variants.
- `tools/page_fixtures.py`: one fixture per card state and for the Models section (switch on/off, other
  endpoint open), so `render_states.py` screenshots them; `test_page` loads them.

## Order

1. Engine `feat/vision-events`, unit tests + goldens, merge to main.
2. salome-agent-gui `feat/models-settings`: bump (ls-tree verified), config_store, drawer, header, drift
   guard, timeline + card.
3. Live: vision override set from the drawer, p1 sent with its image in the GUI; check the header, the card,
   the fix rounds and that the vision call hit the override model (llm trace).
