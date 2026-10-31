import sys


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
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SALOME Agent")
    window = MainWindow(path, notice=notice)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
