import sys


def main(argv=None) -> int:
    from PyQt5.QtWidgets import QApplication

    from salome_agent.logs import setup_logging
    from salome_agent_gui import config_store
    from salome_agent_gui.main_window import MainWindow

    setup_logging(0)
    path = config_store.ensure_user_config()
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("SALOME Agent")
    window = MainWindow(path)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
