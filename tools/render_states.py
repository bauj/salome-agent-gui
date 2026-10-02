"""Render the chat page's fixture states to PNG, light and dark, for review
without SALOME. Needs a display:
    QT_QPA_PLATFORM=xcb .venv/bin/python tools/render_states.py OUTDIR"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv) -> int:
    from PyQt5.QtCore import QCoreApplication, Qt, QTimer
    import PyQt5.QtWebEngineWidgets  # noqa: F401
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from PyQt5.QtWidgets import QApplication

    from salome_agent_gui import web_view
    from tools.page_fixtures import STATES, FakeBridge, resolve

    out = Path(argv[1] if len(argv) > 1 else "render-states")
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(argv[:1])
    fake = FakeBridge()
    view = web_view.create(None, fake)
    view.resize(900, 760)
    view.show()
    jobs = [(name, theme) for name in STATES for theme in ("light", "dark")]

    def shoot(path):
        view.grab().save(str(path))
        print(path)
        step()

    def step():
        if not jobs:
            app.quit()
            return
        name, theme = jobs.pop(0)
        view.page().runJavaScript("document.body.classList.remove('settings-open')")
        fake.emit("reset", {})
        fake.emit("setTheme", {"theme": theme})
        for push_name, payload in STATES[name]:
            if push_name == "__js__":
                view.page().runJavaScript(resolve(payload))
            else:
                fake.emit(push_name, resolve(payload))
        # grab() returns the last frame the renderer delivered: wait for the
        # page to paint the new state, then let the frame reach the widget.
        view.page().runJavaScript(
            "window.__painted = false; requestAnimationFrame(() => "
            "requestAnimationFrame(() => { window.__painted = true; }))")
        wait_painted(out / f"{name}-{theme}.png")

    def wait_painted(path):
        def check(done):
            if done:
                QTimer.singleShot(400, lambda: shoot(path))
            else:
                QTimer.singleShot(50, lambda: wait_painted(path))
        view.page().runJavaScript("window.__painted === true", check)

    def wait_ready():
        if fake.ready_calls:
            step()
        else:
            QTimer.singleShot(100, wait_ready)

    wait_ready()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
