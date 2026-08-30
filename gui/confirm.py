"""Russian confirm dialog with explicit Отмена (left) / Да (right) order."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


def make_confirm_dialog(
    parent,
    title: str,
    text: str,
    *,
    ok_label: str = "Да",
    cancel_label: str = "Отмена",
) -> QDialog:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(True)
    root = QVBoxLayout(dlg)
    root.setSpacing(16)
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    lbl.setWordWrap(True)
    root.addWidget(lbl)
    row = QHBoxLayout()
    row.addStretch()
    cancel_btn = QPushButton(cancel_label)
    ok_btn = QPushButton(ok_label)
    ok_btn.setObjectName("btnCreate")
    cancel_btn.clicked.connect(dlg.reject)
    ok_btn.clicked.connect(dlg.accept)
    row.addWidget(cancel_btn)
    row.addWidget(ok_btn)
    root.addLayout(row)
    dlg._cancel_btn = cancel_btn
    dlg._ok_btn = ok_btn
    dlg._button_row = row
    cancel_btn.setDefault(True)
    cancel_btn.setAutoDefault(True)
    ok_btn.setDefault(False)
    ok_btn.setAutoDefault(False)
    return dlg


def ask_confirm(
    parent,
    title: str,
    text: str,
    *,
    ok_label: str = "Да",
    cancel_label: str = "Отмена",
) -> bool:
    dlg = make_confirm_dialog(
        parent, title, text, ok_label=ok_label, cancel_label=cancel_label
    )
    return bool(dlg.exec())
