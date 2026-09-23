from PyQt5.QtCore import QUrl

from salome_agent_gui.chat_view import ChatView


def test_renders_user_and_run_and_routes_gate_links(qtbot):
    v = ChatView()
    qtbot.addWidget(v)
    v.add_user("make a box")
    run = v.add_run()
    run.apply({"kind": "plan", "run_id": "r", "data": {"stages": [{"module": "geom", "intent": "box"}]}})
    run.gate = {"plan": []}
    v.refresh()
    assert "make a box" in v.markdown() and "gate:approve" in v.markdown()
    with qtbot.waitSignal(v.gate_clicked) as blk:
        v.anchorClicked.emit(QUrl("gate:approve"))
    assert blk.args == ["approve"]


def test_notes_render_between_turns(qtbot):
    v = ChatView()
    qtbot.addWidget(v)
    v.add_user("make a box")
    v.add_run()
    v.add_note("undo: undone back to turn 0")
    assert v.markdown().rstrip().endswith("_undo: undone back to turn 0_")
