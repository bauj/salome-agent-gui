import json
from pathlib import Path

from PyQt5.QtGui import QFontDatabase
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QInputDialog, QLabel,
                             QPlainTextEdit, QVBoxLayout)


class JsonEditDialog(QDialog):
    """Monospace JSON editor; `validate(text)` raises to keep the dialog open."""

    def __init__(self, parent, title: str, text: str, validate):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 560)
        self._validate = validate
        self.edit = QPlainTextEdit(text)
        self.edit.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.error = QLabel("")
        self.error.setStyleSheet("color: #c0392b")
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.edit)
        lay.addWidget(self.error)
        lay.addWidget(buttons)

    def _on_save(self):
        try:
            self._validate(self.edit.toPlainText())
        except Exception as e:  # noqa: BLE001
            self.error.setText(str(e))
            return
        self.accept()


def edit_plan(parent, plan: list) -> list | None:
    from salome_agent.interactive import normalize_plan

    result = {}

    def validate(text):
        out = normalize_plan(json.loads(text))
        if out is None:
            raise ValueError("need a non-empty JSON list of stages, "
                             "each with module geom|smesh|paravis")
        result["plan"] = out

    dlg = JsonEditDialog(parent, "Edit plan", json.dumps(plan, indent=2), validate)
    return result.get("plan") if dlg.exec_() == QDialog.Accepted else None


def ask_hint(parent) -> str | None:
    text, ok = QInputDialog.getMultiLineText(parent, "Hint", "Hint for the specialist:")
    return text.strip() if ok and text.strip() else None


def edit_config(parent, path: Path) -> bool:
    from salome_agent_gui import config_store

    dlg = JsonEditDialog(parent, f"Edit {path}", Path(path).read_text(),
                         lambda text: config_store.save_raw(path, text))
    return dlg.exec_() == QDialog.Accepted
