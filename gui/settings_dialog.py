"""Application settings: XMLRiver / XMLStock API URLs and live balance."""

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from core.google_index import (
    PROVIDER_RIVER,
    PROVIDER_STOCK,
    fetch_balance,
    format_balance_label,
)
from db import database as db

SETTING_RIVER_URL = "xmlriver_url"
SETTING_STOCK_URL = "xmlstock_url"


class _BalanceWorker(QThread):
    finished_ok = pyqtSignal(str, object)

    def __init__(self, provider: str, url: str, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._url = url

    def run(self):
        result = fetch_balance(self._provider, self._url)
        self.finished_ok.emit(self._provider, result)


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(560)
        self._closed = False
        self._workers: dict[str, _BalanceWorker] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        hint = QLabel(
            "Вставьте персональный URL из кабинета сервиса "
            "(содержит user и key). Достаточно одного сервиса."
        )
        hint.setObjectName("secondary")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(QLabel("XMLRiver"))
        self._river_edit = QLineEdit()
        self._river_edit.setPlaceholderText(
            "http://xmlriver.com/search/xml?user=…&key=…"
        )
        self._river_edit.editingFinished.connect(
            lambda: self._refresh_balance(PROVIDER_RIVER)
        )
        root.addWidget(self._river_edit)
        self._river_bal = QLabel("")
        self._river_bal.setObjectName("secondary")
        self._river_bal.setWordWrap(True)
        root.addWidget(self._river_bal)

        root.addWidget(QLabel("XMLStock"))
        self._stock_edit = QLineEdit()
        self._stock_edit.setPlaceholderText(
            "https://xmlstock.com/google/xml/?user=…&key=…"
        )
        self._stock_edit.editingFinished.connect(
            lambda: self._refresh_balance(PROVIDER_STOCK)
        )
        root.addWidget(self._stock_edit)
        self._stock_bal = QLabel("")
        self._stock_bal.setObjectName("secondary")
        self._stock_bal.setWordWrap(True)
        root.addWidget(self._stock_bal)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_btn is not None:
            save_btn.setText("Сохранить")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_btn is not None:
            cancel_btn.setText("Отмена")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(buttons)
        root.addLayout(row)

    def _label_for(self, provider: str) -> QLabel:
        return self._river_bal if provider == PROVIDER_RIVER else self._stock_bal

    def _edit_for(self, provider: str) -> QLineEdit:
        return self._river_edit if provider == PROVIDER_RIVER else self._stock_edit

    def _load(self):
        self._river_edit.setText(db.get_setting(SETTING_RIVER_URL, ""))
        self._stock_edit.setText(db.get_setting(SETTING_STOCK_URL, ""))
        self._refresh_balance(PROVIDER_RIVER)
        self._refresh_balance(PROVIDER_STOCK)

    def _refresh_balance(self, provider: str):
        if self._closed:
            return
        url = self._edit_for(provider).text().strip()
        lbl = self._label_for(provider)
        if not url:
            lbl.setText(format_balance_label(None, empty_url=True))
            lbl.setStyleSheet("")
            return
        lbl.setText(format_balance_label(None, empty_url=False))
        lbl.setStyleSheet("")
        old = self._workers.get(provider)
        if old is not None:
            self._abandon_worker(old)
        worker = _BalanceWorker(provider, url, self)
        worker.finished_ok.connect(self._on_balance)
        self._workers[provider] = worker
        worker.start()

    def _on_balance(self, provider: str, result):
        if self._closed:
            return
        lbl = self._label_for(provider)
        lbl.setText(format_balance_label(result, empty_url=False))
        if result.ok and result.amount is not None and result.amount > 0:
            lbl.setStyleSheet("color: #00c853;")
        else:
            lbl.setStyleSheet("color: #ff5252;")

    def _save(self):
        db.set_setting(SETTING_RIVER_URL, self._river_edit.text().strip())
        db.set_setting(SETTING_STOCK_URL, self._stock_edit.text().strip())
        self.accept()

    def _abandon_worker(self, worker: _BalanceWorker) -> None:
        try:
            worker.finished_ok.disconnect()
        except TypeError:
            pass
        worker.setParent(None)
        worker.finished.connect(worker.deleteLater)

    def closeEvent(self, event):
        self._closed = True
        for edit in (self._river_edit, self._stock_edit):
            try:
                edit.editingFinished.disconnect()
            except TypeError:
                pass
        for worker in list(self._workers.values()):
            self._abandon_worker(worker)
        self._workers.clear()
        super().closeEvent(event)
