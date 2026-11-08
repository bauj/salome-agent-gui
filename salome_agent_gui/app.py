# Copyright (C) 2026  salome-agent authors
# LGPL 2.1 or later
import sys


def split_family(argv: list) -> tuple[str | None, list]:
    """`--mode agent|rag` (the SALOME menu entry, see sagui_launcher) out of
    argv; the rest goes to Qt."""
    family, rest, it = None, [], iter(argv)
    for a in it:
        if a == "--mode":
            family = next(it, None)
        elif a.startswith("--mode="):
            family = a.split("=", 1)[1]
        else:
            rest.append(a)
    return family, rest


def main(argv=None) -> int:
    from PyQt5.QtCore import QCoreApplication, Qt

    # Qt WebEngine must be imported, and GL context sharing switched on,
    # before the QApplication exists.
    try:
        import PyQt5.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        pass                     # web_view.create shows the fallback panel
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    from PyQt5.QtWidgets import QApplication

    from salome_agent.logs import setup_logging
    from salome_agent_gui import config_store
    from salome_agent_gui.main_window import MainWindow

    setup_logging(0)
    path, notice = config_store.startup_config(config_store.ensure_user_config())
    config_store.complete_config(path)          # one file for every mode's settings
    family, qt_argv = split_family(list(sys.argv if argv is None else argv))
    app = QApplication(qt_argv)
    app.setApplicationName("SALOME agentic assistants")
    window = MainWindow(path, notice=notice, family=family)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
