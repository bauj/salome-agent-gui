import salome_pluginsmanager


def runSalomeAgent(context):
    # The plugins manager exec()s this file with a throwaway locals dict, so
    # every name used at click time is imported here.
    from PyQt5.QtWidgets import QMessageBox

    import sagui_launcher

    try:
        msg = sagui_launcher.run(context)
    except Exception as e:  # noqa: BLE001
        QMessageBox.warning(None, "SALOME Agent", f"Failed to start SALOME Agent:\n{e}")
        return
    if msg:
        QMessageBox.information(None, "SALOME Agent", msg)


salome_pluginsmanager.AddFunction('SALOME Agent',
                                  'Start the agent server and open the SALOME Agent chat',
                                  runSalomeAgent)
