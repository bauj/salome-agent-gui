import time

import pytest

from salome_agent_gui import web_view
from tools.page_fixtures import (BUSY, DONE_VM, EDIT_VM, FAILED_VM, IDLE_OPEN, PLAN_VM,
                                 SETTINGS, STATUS_OFF, STATUS_OK, FakeBridge)

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
    qtbot.waitUntil(lambda: ("send", "line one") in fake.calls, timeout=3000)
    assert run_js(qtbot, view, "document.getElementById('input').value") == ""


def test_result_shows_objects_file_chips_and_usage(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", DONE_VM)
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
                     "theme": "dark"}


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


def test_approved_plan_shows_the_next_step_as_processing(qtbot, page):
    view, fake = page
    fake.emit("renderTurn", PLAN_VM)
    wait_js(qtbot, view, "document.querySelectorAll('.step').length === 2")
    assert run_js(qtbot, view, "document.querySelectorAll('.step .st.run').length") == 0
    fake.emit("renderTurn", dict(PLAN_VM, gate=None))           # approved, stage not started
    wait_js(qtbot, view, "!document.querySelector('[data-action=approve]')")
    assert run_js(qtbot, view, "[...document.querySelectorAll('.step > .st')]"
                               ".map(e => e.className).join('|')") == "st run|st pend"
    assert run_js(qtbot, view, "!!document.querySelector('.step .st.run svg.spin')") is True
    assert run_js(qtbot, view, "[...document.querySelectorAll('.step')]"
                               ".map(e => e.className).join('|')") == "step|step pending"
