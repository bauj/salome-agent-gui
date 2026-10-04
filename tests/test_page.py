import time

import pytest

from salome_agent_gui import web_view
from tools.page_fixtures import (BUSY, DONE_VM, EDIT_VM, FAILED_VM, IDLE_NEW, IDLE_OPEN, PLAN_VM,
                                 MODELS_SETTINGS, SETTINGS, STATUS_OFF, STATUS_OK,
                                 VISION_CONFLICTS_VM, FakeBridge, vision_running_vm)

pytestmark = pytest.mark.web

EVIL = '<img src=x onerror="window.pwned=1">'


def run_js(qtbot, view, code):
    box = []
    view.page().runJavaScript(code, box.append)
    qtbot.waitUntil(lambda: len(box) == 1, timeout=5000)
    return box[0]


def wait_js(qtbot, view, code, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if run_js(qtbot, view, code):
            return
        qtbot.wait(50)
    raise AssertionError(f"never true: {code}")


@pytest.fixture
def page(qtbot):
    fake = FakeBridge()
    view = web_view.create(None, fake)
    qtbot.addWidget(view)
    view.resize(900, 760)
    view.show()
    qtbot.waitUntil(lambda: fake.ready_calls == 1, timeout=20000)
    fake.emit("setSettings", SETTINGS)
    fake.emit("setStatus", STATUS_OK)
    fake.emit("setBusy", IDLE_OPEN)
    return view, fake


def test_page_calls_ready_and_starts_empty(qtbot, page):
    view, _ = page
    wait_js(qtbot, view, "document.body.classList.contains('is-empty')")
    assert run_js(qtbot, view, "document.getElementById('status-label').textContent") == \
        "GUI :46019 · auto"


def test_turn_shows_steps_with_icons_or_badges(qtbot, page):
    view, fake = page
    vm = dict(PLAN_VM, stages=[dict(PLAN_VM["stages"][0], icon="file:///nowhere/geom.png"),
                               PLAN_VM["stages"][1]])
    fake.emit("renderTurn", vm)
    wait_js(qtbot, view, "document.querySelectorAll('.step').length === 2")
    assert run_js(qtbot, view, "document.querySelector('.step img.mod').title") == "GEOM"
    assert run_js(qtbot, view, "document.querySelector('.step .badge').textContent") == "smesh"
    assert run_js(qtbot, view, "document.body.classList.contains('is-empty')") is False


def test_engine_text_is_never_html(qtbot, page):
    view, fake = page
    vm = dict(DONE_VM, status="failed", message=EVIL, objects=[EVIL],
              stages=[dict(DONE_VM["stages"][0], intent=EVIL, error=EVIL, status="failed")],
              edits=[{"op": "edit", "node": EVIL, "param": EVIL, "old": EVIL, "new": EVIL}])
    fake.emit("addUser", {"text": EVIL})
    fake.emit("addNote", {"text": EVIL})
    fake.emit("renderTurn", vm)
    wait_js(qtbot, view, "document.querySelectorAll('.msg-agent').length === 1")
    assert run_js(qtbot, view,
                  "document.querySelectorAll('#col img:not(.avatar):not(.mod)').length") == 0
    assert run_js(qtbot, view, "window.pwned === undefined") is True
    assert run_js(qtbot, view,
                  "document.getElementById('col').textContent.includes('<img src=x')") is True


def test_approve_click_reaches_the_bridge_and_disables_the_buttons(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    wait_js(qtbot, view, "!!document.querySelector('[data-action=approve]')")
    run_js(qtbot, view, "document.querySelector('[data-action=approve]').click();"
                        "document.querySelector('[data-action=approve]').click(); true")
    qtbot.waitUntil(lambda: ("gate", 1, "approve", "") in fake.calls, timeout=3000)
    qtbot.wait(200)
    assert [c for c in fake.calls if c[0] == "gate"] == [("gate", 1, "approve", "")]
    assert run_js(qtbot, view, "document.querySelector('[data-action=abort]').disabled") is True


def test_edit_plan_click_disables_the_buttons_until_the_turn_is_redrawn(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    wait_js(qtbot, view, "!!document.querySelector('[data-action=edit]')")
    run_js(qtbot, view, "document.querySelector('[data-action=edit]').click();"
                        "document.querySelector('[data-action=edit]').click(); true")
    qtbot.waitUntil(lambda: ("gate", 1, "edit", "") in fake.calls, timeout=3000)
    qtbot.wait(200)
    assert [c for c in fake.calls if c[0] == "gate"] == [("gate", 1, "edit", "")]
    assert run_js(qtbot, view, "document.querySelector('[data-action=approve]').disabled") is True
    fake.emit("renderTurn", PLAN_VM)                       # the bridge redraws on Cancel
    wait_js(qtbot, view, "!document.querySelector('[data-action=approve]').disabled")


def test_hint_needs_text_and_sends_it(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", FAILED_VM)
    wait_js(qtbot, view, "!!document.querySelector('[data-action=show-hint]')")
    assert run_js(qtbot, view, "document.querySelector('.gate-warn .err').textContent") == \
        FAILED_VM["gate"]["message"]
    run_js(qtbot, view, "document.querySelector('[data-action=show-hint]').click();"
                        "document.querySelector('[data-action=hint]').click(); true")
    qtbot.wait(200)
    assert not [c for c in fake.calls if c[0] == "gate"]
    run_js(qtbot, view, "document.querySelector('.hint-box textarea').value = 'use r=2';"
                        "document.querySelector('[data-action=hint]').click(); true")
    qtbot.waitUntil(lambda: ("gate", 2, "hint", "use r=2") in fake.calls, timeout=3000)


def test_busy_turns_send_into_stop(qtbot, page):
    view, fake = page
    fake.emit("setBusy", BUSY)
    wait_js(qtbot, view, "document.getElementById('send').classList.contains('stop')")
    assert run_js(qtbot, view, "document.getElementById('btn-undo').disabled") is True
    run_js(qtbot, view, "document.getElementById('send').click(); true")
    qtbot.waitUntil(lambda: ("stop",) in fake.calls, timeout=3000)
    fake.emit("setBusy", dict(BUSY, stopping=True))
    wait_js(qtbot, view, "document.getElementById('send').disabled")
    assert "Stopping" in run_js(qtbot, view, "document.getElementById('hint').textContent")


def test_enter_sends_and_shift_enter_does_not(qtbot, page):
    view, fake = page
    wait_js(qtbot, view, "!document.getElementById('send').disabled")
    key = ("document.getElementById('input').dispatchEvent(new KeyboardEvent('keydown',"
           "{key: 'Enter', shiftKey: %s, bubbles: true, cancelable: true})); true")
    run_js(qtbot, view, "document.getElementById('input').value = 'line one'; true")
    run_js(qtbot, view, key % "true")
    qtbot.wait(200)
    assert not [c for c in fake.calls if c[0] == "send"]
    run_js(qtbot, view, key % "false")
    qtbot.waitUntil(lambda: ("send", "line one", []) in fake.calls, timeout=3000)
    assert run_js(qtbot, view, "document.getElementById('input').value") == ""


def test_result_shows_objects_file_chips_and_usage(qtbot, page):
    view, fake = page
    bare = [dict(s, objects=[]) for s in DONE_VM["stages"]]   # steps that list no objects
    fake.emit("renderTurn", dict(DONE_VM, stages=bare))
    wait_js(qtbot, view, "!!document.querySelector('.result')")
    assert run_js(qtbot, view, "document.querySelector('.result-line').textContent") == \
        "Built 5 objects"
    assert run_js(qtbot, view, "document.querySelectorAll('.objects .chip').length") == 5
    usage = run_js(qtbot, view, "document.querySelector('.result .usage').textContent")
    assert "18 LLM calls" in usage and "71k in / 15k out" in usage
    run_js(qtbot, view, "document.querySelector('[data-file=result_py]').click(); true")
    qtbot.waitUntil(lambda: ("openFile", "/tmp/run/result.py") in fake.calls, timeout=3000)


def test_edits_card_lists_changes(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", EDIT_VM)
    wait_js(qtbot, view, "document.querySelectorAll('.edits li').length === 2")
    assert "4 objects rebuilt" in run_js(qtbot, view,
                                         "document.querySelector('.card-head').textContent")


def test_render_turn_replaces_the_same_turn(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    fake.emit("renderTurn", dict(PLAN_VM, gate=None, status="aborted"))
    wait_js(qtbot, view, "!!document.querySelector('.result')")
    assert run_js(qtbot, view, "document.querySelectorAll('.msg-agent').length") == 1


def test_replay_rebuilds_the_transcript(qtbot, page):
    view, fake = page
    fake.emit("addUser", {"text": "old"})
    fake.emit("replay", {"items": [{"type": "user", "text": "a"},
                                   {"type": "turn", "vm": DONE_VM},
                                   {"type": "note", "text": "undo: done"}]})
    wait_js(qtbot, view, "document.querySelectorAll('#col > *').length === 3")
    assert run_js(qtbot, view, "document.querySelector('.msg-user').textContent") == "a"


def test_offline_status_shows_the_banner(qtbot, page):
    view, fake = page
    fake.emit("setStatus", STATUS_OFF)
    wait_js(qtbot, view, "!document.getElementById('banner').hidden")
    assert "Plugins" in run_js(qtbot, view, "document.getElementById('banner').textContent")


def test_settings_lock_run_options_and_save(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, locked=True))
    wait_js(qtbot, view, "document.getElementById('set-on-failure').disabled")
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('set-model').value = 'qwen';"
                        "document.getElementById('set-theme').value = 'dark';"
                        "document.getElementById('btn-save').click(); true")
    qtbot.waitUntil(lambda: any(c[0] == "saveSettings" for c in fake.calls), timeout=3000)
    saved = [c for c in fake.calls if c[0] == "saveSettings"][-1][1]
    assert saved == {"base_url": "http://llm.example/v1", "model": "qwen", "api_key": "sk-test",
                     "ssl_cert_file": "~/certs/ca.pem", "theme": "dark", "show_reasoning": False}


def test_theme_push_sets_the_theme(qtbot, page):
    view, fake = page
    fake.emit("setTheme", {"theme": "dark"})
    wait_js(qtbot, view, "document.documentElement.dataset.theme === 'dark'")


def test_theme_button_flips_the_theme_and_stays_enabled_while_busy(qtbot, page):
    view, fake = page
    fake.emit("setTheme", {"theme": "light"})
    fake.emit("setBusy", BUSY)
    wait_js(qtbot, view, "document.getElementById('send').classList.contains('stop')")
    assert run_js(qtbot, view, "document.getElementById('btn-theme').disabled") is False
    run_js(qtbot, view, "document.getElementById('btn-theme').click(); true")
    qtbot.waitUntil(lambda: ("saveSettings", {"theme": "dark"}) in fake.calls, timeout=3000)
    fake.emit("setTheme", {"theme": "dark"})
    wait_js(qtbot, view, "document.documentElement.dataset.theme === 'dark'")
    assert run_js(qtbot, view, "document.getElementById('btn-theme').dataset.tip") == "Light theme"
    run_js(qtbot, view, "document.getElementById('btn-theme').click(); true")
    qtbot.waitUntil(lambda: ("saveSettings", {"theme": "light"}) in fake.calls, timeout=3000)


def test_step_shows_the_objects_it_made_as_text(qtbot, page):
    view, fake = page
    stages = [dict(DONE_VM["stages"][0], objects=["fuse_1", EVIL]),
              dict(DONE_VM["stages"][1], objects=[])]
    fake.emit("renderTurn", dict(DONE_VM, stages=stages))
    wait_js(qtbot, view, "document.querySelectorAll('.step').length === 2")
    assert run_js(qtbot, view, "[...document.querySelectorAll('.step')[0]"
                               ".querySelectorAll('.step-objs .chip')].map(e => e.textContent)"
                               ".join('|')") == "fuse_1|" + EVIL
    assert run_js(qtbot, view, "document.querySelectorAll('.step')[1]"
                               ".querySelector('.step-objs')") is None
    assert run_js(qtbot, view, "window.pwned === undefined") is True


def test_the_page_draws_pending_steps_as_pending(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", dict(PLAN_VM, gate=None))      # Python decides what runs
    wait_js(qtbot, view, "!document.querySelector('[data-action=approve]')")
    assert run_js(qtbot, view, "[...document.querySelectorAll('.step > .st')]"
                               ".map(e => e.className).join('|')") == "st pend|st pend"


def test_stopped_step_does_not_spin(qtbot, page):
    view, fake = page
    stages = [dict(PLAN_VM["stages"][0], status="stopped", started_at=time.time() - 5),
              PLAN_VM["stages"][1]]
    fake.emit("renderTurn", dict(PLAN_VM, gate=None, status="failed", stages=stages))
    wait_js(qtbot, view, "document.querySelectorAll('.step').length === 2")
    assert run_js(qtbot, view, "document.querySelector('.step > .st').className") == "st stopped"
    assert run_js(qtbot, view, "!!document.querySelector('.step svg.spin')") is False
    assert run_js(qtbot, view, "document.querySelector('.step .meta').textContent") == "stopped"


def test_a_plan_gate_with_no_stages_still_offers_approve_and_abort(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", dict(PLAN_VM, stages=[]))
    wait_js(qtbot, view, "document.querySelectorAll('.msg-agent').length === 1")
    assert run_js(qtbot, view, "!!document.querySelector('[data-action=approve]')") is True
    assert run_js(qtbot, view, "!!document.querySelector('[data-action=abort]')") is True


def test_objects_already_listed_under_their_steps_are_not_listed_again(qtbot, page):
    view, fake = page
    stages = [dict(DONE_VM["stages"][0], objects=["fuse_1"]),
              dict(DONE_VM["stages"][1], objects=DONE_VM["objects"][1:])]
    fake.emit("renderTurn", dict(DONE_VM, stages=stages))
    wait_js(qtbot, view, "!!document.querySelector('.result')")
    assert run_js(qtbot, view, "document.querySelector('.result details.objects')") is None
    assert run_js(qtbot, view, "document.querySelector('.result-line').textContent") == \
        "Built 5 objects"


def test_objects_of_a_turn_without_steps_are_still_listed(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", dict(EDIT_VM, objects=["torus_1"]))
    wait_js(qtbot, view, "!!document.querySelector('.result')")
    assert run_js(qtbot, view, "!!document.querySelector('.result details.objects')") is True


def _reasoning(turn, key, call, channel, text):
    return {"turn": turn, "key": key, "call": call, "channel": channel, "text": text}


def test_streamed_reasoning_lands_under_its_stage_and_the_turn(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, show_reasoning=True))
    fake.emit("renderTurn", PLAN_VM)
    wait_js(qtbot, view, "document.querySelectorAll('.step').length === 2")
    turn = PLAN_VM["id"]
    fake.emit("appendReasoning", _reasoning(turn, "planner", 1, "reasoning", "plan "))
    fake.emit("appendReasoning", _reasoning(turn, "planner", 1, "reasoning", EVIL))
    fake.emit("appendReasoning", _reasoning(turn, "stage:1", 2, "prose", "Meshing."))
    wait_js(qtbot, view, "!!document.querySelector('.step[data-stage=\"1\"] details.reasoning')")
    assert run_js(qtbot, view,
                  "document.querySelector('.turn-reasoning .r-think').textContent") == "plan " + EVIL
    assert run_js(qtbot, view, "window.pwned === undefined") is True
    assert run_js(qtbot, view, "document.querySelector('.step[data-stage=\"1\"] .r-prose')"
                               ".textContent") == "Meshing."
    assert run_js(qtbot, view, "document.querySelector('.turn-reasoning summary').textContent") \
        == "Reasoning · 1 call"
    assert run_js(qtbot, view, "getComputedStyle(document.querySelector('details.reasoning'))"
                               ".display") == "block"


def test_reasoning_is_hidden_unless_the_setting_is_on(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", dict(PLAN_VM, reasoning={"planner": [
        {"call": 1, "reasoning": "hmm", "prose": ""}]}))
    wait_js(qtbot, view, "!!document.querySelector('details.reasoning')")
    assert run_js(qtbot, view, "getComputedStyle(document.querySelector('details.reasoning'))"
                               ".display") == "none"


def test_an_open_reasoning_block_stays_open_across_a_re_render(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, show_reasoning=True))
    stages = [dict(PLAN_VM["stages"][0], reasoning=[{"call": 1, "reasoning": "a", "prose": ""}]),
              PLAN_VM["stages"][1]]
    fake.emit("renderTurn", dict(PLAN_VM, stages=stages))
    wait_js(qtbot, view, "!!document.querySelector('details.reasoning')")
    run_js(qtbot, view, "document.querySelector('details.reasoning summary').click(); true")
    wait_js(qtbot, view, "document.querySelector('details.reasoning').open")
    fake.emit("renderTurn", dict(PLAN_VM, stages=stages, status="ok"))
    qtbot.wait(200)
    assert run_js(qtbot, view, "document.querySelector('details.reasoning').open") is True


def test_unlocked_save_sends_the_policy_knobs(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, verify_cadence="final", plan_detail="balanced",
                                  exec_retries=2, tool_iteration_cap=12))
    wait_js(qtbot, view, "document.getElementById('set-cap').value === '12'")
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('set-cadence').value = 'strict';"
                        "document.getElementById('set-detail').value = 'coarse';"
                        "document.getElementById('set-exec-retries').value = '4';"
                        "document.getElementById('set-cap').value = '20';"
                        "document.getElementById('btn-save').click(); true")
    qtbot.waitUntil(lambda: any(c[0] == "saveSettings" for c in fake.calls), timeout=3000)
    saved = [c for c in fake.calls if c[0] == "saveSettings"][-1][1]
    assert (saved["verify_cadence"], saved["plan_detail"], saved["exec_retries"],
            saved["tool_iteration_cap"]) == ("strict", "coarse", 4, 20)


def test_policy_knobs_lock_with_the_other_run_options(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, locked=True))
    wait_js(qtbot, view, "document.getElementById('set-on-failure').disabled")
    assert run_js(qtbot, view, "['set-cadence','set-detail','set-exec-retries','set-cap']"
                               ".every((id) => document.getElementById(id).disabled)") is True


PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
PNG_URI = "data:image/png;base64," + PNG_B64


def drop_files(qtbot, view, files):
    """Drop files on the page; `files` is a list of (name, mime, base64)."""
    parts = ",".join(
        f"new File([Uint8Array.from(atob('{b64}'), c => c.charCodeAt(0))], '{name}', "
        f"{{type: '{mime}'}})" for name, mime, b64 in files)
    run_js(qtbot, view, f"""
        const dt = new DataTransfer();
        for (const f of [{parts}]) dt.items.add(f);
        window.dispatchEvent(new DragEvent('drop', {{dataTransfer: dt, bubbles: true,
                                                     cancelable: true}}));
        true""")


def test_dropped_images_show_in_the_composer_and_go_with_the_message(qtbot, page):
    view, fake = page
    drop_files(qtbot, view, [("a.png", "image/png", PNG_B64), ("b.png", "image/png", PNG_B64)])
    wait_js(qtbot, view, "document.querySelectorAll('#attachments .thumb').length === 2")
    assert run_js(qtbot, view, "document.getElementById('attachments').hidden") is False
    assert run_js(qtbot, view, "document.querySelector('.thumb img').src") == PNG_URI
    run_js(qtbot, view, "document.querySelector('.thumb .remove').click(); true")
    assert run_js(qtbot, view, "document.querySelectorAll('#attachments .thumb').length") == 1
    run_js(qtbot, view, "document.getElementById('input').value = 'like this'; "
                        "document.getElementById('send').click(); true")
    qtbot.waitUntil(lambda: ("send", "like this", [PNG_URI]) in fake.calls, timeout=3000)
    assert run_js(qtbot, view, "document.getElementById('attachments').hidden") is True
    assert run_js(qtbot, view, "document.querySelectorAll('#attachments .thumb').length") == 0


def test_images_alone_can_be_sent(qtbot, page):
    view, fake = page
    run_js(qtbot, view, "document.getElementById('send').click(); true")
    qtbot.wait(200)
    assert not [c for c in fake.calls if c[0] == "send"]
    drop_files(qtbot, view, [("a.png", "image/png", PNG_B64)])
    wait_js(qtbot, view, "document.querySelectorAll('#attachments .thumb').length === 1")
    run_js(qtbot, view, "document.getElementById('send').click(); true")
    qtbot.waitUntil(lambda: ("send", "", [PNG_URI]) in fake.calls, timeout=3000)


def test_a_file_that_is_not_an_image_is_refused(qtbot, page):
    view, _ = page
    drop_files(qtbot, view, [("notes.txt", "text/plain", "aGVsbG8=")])
    wait_js(qtbot, view, "document.getElementById('hint').classList.contains('error')")
    assert "notes.txt" in run_js(qtbot, view, "document.getElementById('hint').textContent")
    assert run_js(qtbot, view, "document.getElementById('attachments').hidden") is True


def test_sent_images_show_above_the_message_and_open_full_size(qtbot, page):
    view, fake = page
    fake.emit("addUser", {"text": "like this", "images": [PNG_URI, PNG_URI]})
    wait_js(qtbot, view, "document.querySelectorAll('.msg-user .msg-images img').length === 2")
    assert run_js(qtbot, view, "document.querySelector('.msg-user .bubble').textContent") == \
        "like this"
    run_js(qtbot, view, "document.querySelector('.msg-images img').click(); true")
    assert run_js(qtbot, view, "document.getElementById('lightbox').hidden") is False
    assert run_js(qtbot, view, "document.getElementById('lightbox-img').src") == PNG_URI
    run_js(qtbot, view, "document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'})); "
                        "true")
    assert run_js(qtbot, view, "document.getElementById('lightbox').hidden") is True


def test_an_image_only_message_has_no_empty_bubble_and_replays(qtbot, page):
    view, fake = page
    fake.emit("replay", {"items": [{"type": "user", "text": "", "images": [PNG_URI]},
                                   {"type": "user", "text": "taller"}]})
    wait_js(qtbot, view, "document.querySelectorAll('.msg-user').length === 2")
    assert run_js(qtbot, view, "document.querySelectorAll('.msg-user .bubble').length") == 1
    assert run_js(qtbot, view, "document.querySelectorAll('.msg-images img').length") == 1


def saved_settings(qtbot, fake):
    qtbot.waitUntil(lambda: any(c[0] == "saveSettings" for c in fake.calls), timeout=3000)
    return [c for c in fake.calls if c[0] == "saveSettings"][-1][1]


def test_shared_model_hides_the_rows_and_saves_them_anyway(qtbot, page):
    view, fake = page
    fake.emit("setBusy", IDLE_NEW)                      # no conversation: run options unlocked
    wait_js(qtbot, view, "document.getElementById('module-rows').hidden")
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('btn-save').click(); true")
    saved = saved_settings(qtbot, fake)
    assert saved["shared_model"] is True
    assert (saved["reasoning_budget"], saved["vision_fix_retries"], saved["timeout"]) == (20000, 2, 120)
    assert set(saved["modules"]) == {"planner", "vision", "geom", "smesh", "paravis", "amend"}


def test_module_rows_follow_the_engine_list_plus_unknown_entries(qtbot, page):
    view, fake = page
    fake.emit("setSettings", MODELS_SETTINGS)
    wait_js(qtbot, view, "!document.getElementById('module-rows').hidden")
    names = run_js(qtbot, view, "[...document.querySelectorAll('.mod-row')]"
                                ".map(r => r.dataset.module).join(',')")
    assert names == "planner,vision,geom,smesh,paravis,amend,visio"
    assert run_js(qtbot, view, "document.querySelector('.mod-row[data-module=amend] .mod-name')"
                               ".textContent") == "Chat edits"
    assert run_js(qtbot, view, "document.querySelector('.mod-row[data-module=vision] .json-only')"
                               ".textContent") == "also set in JSON: extra_body"
    assert run_js(qtbot, view, "!document.querySelector('.mod-row[data-module=vision] "
                               ".mod-endpoint').hidden") is True
    assert run_js(qtbot, view, "document.querySelector('.mod-row[data-module=geom] "
                               ".mod-endpoint').hidden") is True


def test_other_endpoint_without_key_keeps_the_drawer_open(qtbot, page):
    view, fake = page
    fake.emit("setBusy", IDLE_NEW)                      # no conversation: run options unlocked
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('set-shared').click();"
                        "const r = document.querySelector('.mod-row[data-module=vision]');"
                        "r.querySelector('.linkish').click();"
                        "r.querySelector('input[data-key=model]').value = 'reader';"
                        "r.querySelector('input[data-key=base_url]').value = 'http://other/v1';"
                        "document.getElementById('btn-save').click(); true")
    wait_js(qtbot, view, "!document.getElementById('models-error').hidden")
    assert "Vision: a different endpoint needs its own API key" in run_js(
        qtbot, view, "document.getElementById('models-error').textContent")
    assert run_js(qtbot, view, "document.body.classList.contains('settings-open')") is True
    assert not any(c[0] == "saveSettings" for c in fake.calls)
    run_js(qtbot, view, "document.querySelector('.mod-row[data-module=vision] "
                        "input[data-key=api_key]').value = 'sk-2';"
                        "document.getElementById('btn-save').click(); true")
    saved = saved_settings(qtbot, fake)
    assert saved["shared_model"] is False
    assert saved["modules"]["vision"] == {"model": "reader", "base_url": "http://other/v1",
                                          "api_key": "sk-2", "ssl_cert_file": ""}


def test_models_and_advanced_lock_with_the_run_options(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(MODELS_SETTINGS, locked=True))
    wait_js(qtbot, view, "document.getElementById('set-budget').disabled")
    assert run_js(qtbot, view, "document.getElementById('set-shared').classList"
                               ".contains('disabled')") is True
    assert run_js(qtbot, view, "[...document.querySelectorAll('#module-rows input')]"
                               ".every(i => i.disabled)") is True
    run_js(qtbot, view, "document.getElementById('set-shared').click(); true")
    assert run_js(qtbot, view, "document.getElementById('set-shared').classList"
                               ".contains('on')") is False


def test_vision_card_runs_with_a_timer_then_shows_conflicts(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", vision_running_vm())
    wait_js(qtbot, view, "!!document.querySelector('.vision-card[data-status=running]')")
    head = run_js(qtbot, view, "document.querySelector('.vision-card .card-head').textContent")
    assert head.startswith("Reading image")
    assert run_js(qtbot, view, "!!document.querySelector('.vision-card [data-start]')") is True
    assert "Fix round 1/2" in run_js(qtbot, view,
                                     "document.querySelector('.vision-card').textContent")
    fake.emit("renderTurn", VISION_CONFLICTS_VM)
    wait_js(qtbot, view, "!!document.querySelector('.vision-card[data-status=conflicts]')")
    text = run_js(qtbot, view, "document.querySelector('.vision-card').textContent")
    assert "Read 3 parts, 2 problems left for the build" in text
    assert run_js(qtbot, view, "!!document.querySelector('.vision-card [data-start]')") is False
    order = run_js(qtbot, view, "[...document.querySelectorAll('.vision-card, .steps')]"
                                ".map(n => n.className).join('|')")
    assert order.startswith("card vision-card")          # the card sits above the plan


def test_vision_errors_are_text(qtbot, page):
    view, fake = page
    vm = dict(VISION_CONFLICTS_VM, vision=dict(VISION_CONFLICTS_VM["vision"], checks=[
        {"attempt": 1, "of": 1, "errors": [EVIL]}], model=EVIL))
    fake.emit("renderTurn", vm)
    wait_js(qtbot, view, "!!document.querySelector('.vision-card')")
    assert run_js(qtbot, view, "document.querySelector('.vision-card img') === null") is True
    assert run_js(qtbot, view, "window.pwned === undefined") is True


def test_vision_reasoning_streams_into_the_card(qtbot, page):
    view, fake = page
    fake.emit("setSettings", dict(SETTINGS, show_reasoning=True))
    fake.emit("renderTurn", vision_running_vm())
    wait_js(qtbot, view, "!!document.querySelector('.vision-card')")
    fake.emit("appendReasoning", {"turn": 3, "key": "vision", "call": 1,
                                  "channel": "reasoning", "text": "the 80 is the width"})
    wait_js(qtbot, view, "document.querySelector('.vision-card details.reasoning') !== null")
    assert "the 80" in run_js(qtbot, view, "document.querySelector('.vision-card').textContent")


def test_whitespace_key_counts_as_no_key(qtbot, page):
    view, fake = page
    fake.emit("setBusy", IDLE_NEW)
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('set-shared').click();"
                        "const r = document.querySelector('.mod-row[data-module=vision]');"
                        "r.querySelector('input[data-key=base_url]').value = 'http://other/v1';"
                        "r.querySelector('input[data-key=api_key]').value = '   ';"
                        "document.getElementById('btn-save').click(); true")
    wait_js(qtbot, view, "!document.getElementById('models-error').hidden")
    assert not any(c[0] == "saveSettings" for c in fake.calls)


def test_untouched_keyless_endpoint_row_still_saves(qtbot, page):
    view, fake = page
    fake.emit("setBusy", IDLE_NEW)
    fake.emit("setSettings", dict(MODELS_SETTINGS, modules={"vision": {
        "model": "x", "base_url": "http://localhost:11434/v1", "api_key": "", "ssl_cert_file": ""}}))
    run_js(qtbot, view, "document.getElementById('btn-settings').click();"
                        "document.getElementById('btn-save').click(); true")
    saved = saved_settings(qtbot, fake)
    assert saved["modules"]["vision"]["base_url"] == "http://localhost:11434/v1"
