"""Application settings: index-check and indexer API credentials."""

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.google_index import (
    PROVIDER_JSONSEO,
    PROVIDER_RIVER,
    PROVIDER_STOCK,
    fetch_balance,
    format_balance_label,
)
from core.speedyindex import PROVIDER_SPEEDYINDEX
from core.speedyindex import fetch_balance as fetch_speedy_balance
from core.speedyindex import format_balance_label as format_speedy_balance
from db import database as db
from gui.confirm import ask_confirm

SETTING_RIVER_URL = "xmlriver_url"
SETTING_STOCK_URL = "xmlstock_url"
SETTING_JSONSEO_KEY = "jsonseo_key"
SETTING_SPEEDYINDEX_KEY = "speedyindex_key"


class _BalanceWorker(QThread):
    finished_ok = pyqtSignal(str, object)

    def __init__(self, provider: str, url: str, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._url = url

    def run(self):
        if self._provider == PROVIDER_SPEEDYINDEX:
            result = fetch_speedy_balance(self._url)
        else:
            result = fetch_balance(self._provider, self._url)
        self.finished_ok.emit(self._provider, result)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, on_wipe=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(560)
        self._closed = False
        self._on_wipe = on_wipe
        self._workers: dict[str, _BalanceWorker] = {}
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        hint = QLabel(
            "Для XMLRiver и XMLStock вставьте персональный URL из кабинета "
            "(user и key). Для JSON SEO и SpeedyIndex — API-ключ. "
            "Для проверки индексации достаточно одного сервиса."
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

        root.addWidget(QLabel("JSON SEO"))
        self._jsonseo_edit = QLineEdit()
        self._jsonseo_edit.setPlaceholderText("API-ключ JSON SEO")
        self._jsonseo_edit.editingFinished.connect(
            lambda: self._refresh_balance(PROVIDER_JSONSEO)
        )
        root.addWidget(self._jsonseo_edit)
        self._jsonseo_bal = QLabel("")
        self._jsonseo_bal.setObjectName("secondary")
        self._jsonseo_bal.setWordWrap(True)
        root.addWidget(self._jsonseo_bal)

        root.addWidget(QLabel("SpeedyIndex"))
        self._speedy_edit = QLineEdit()
        self._speedy_edit.setPlaceholderText("API-ключ SpeedyIndex")
        self._speedy_edit.editingFinished.connect(
            lambda: self._refresh_balance(PROVIDER_SPEEDYINDEX)
        )
        root.addWidget(self._speedy_edit)
        self._speedy_bal = QLabel("")
        self._speedy_bal.setObjectName("secondary")
        self._speedy_bal.setWordWrap(True)
        root.addWidget(self._speedy_bal)

        self._wipe_btn = QPushButton("Очистить базу")
        self._wipe_btn.clicked.connect(self._wipe)
        self._cancel_btn = QPushButton("Отмена")
        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("Сохранить")
        self._save_btn.setObjectName("btnCreate")
        self._save_btn.clicked.connect(self._save)
        row = QHBoxLayout()
        row.addWidget(self._wipe_btn)
        row.addStretch()
        row.addWidget(self._cancel_btn)
        row.addWidget(self._save_btn)
        self._button_row = row
        root.addLayout(row)

    def _label_for(self, provider: str) -> QLabel:
        return {
            PROVIDER_RIVER: self._river_bal,
            PROVIDER_STOCK: self._stock_bal,
            PROVIDER_JSONSEO: self._jsonseo_bal,
            PROVIDER_SPEEDYINDEX: self._speedy_bal,
        }[provider]

    def _edit_for(self, provider: str) -> QLineEdit:
        return {
            PROVIDER_RIVER: self._river_edit,
            PROVIDER_STOCK: self._stock_edit,
            PROVIDER_JSONSEO: self._jsonseo_edit,
            PROVIDER_SPEEDYINDEX: self._speedy_edit,
        }[provider]

    def _format_balance(self, provider: str, result, empty: bool) -> str:
        if provider == PROVIDER_SPEEDYINDEX:
            return format_speedy_balance(result, empty)
        kind = "key" if provider == PROVIDER_JSONSEO else "url"
        return format_balance_label(result, empty, kind=kind)

    def _load(self):
        self._river_edit.setText(db.get_setting(SETTING_RIVER_URL, ""))
        self._stock_edit.setText(db.get_setting(SETTING_STOCK_URL, ""))
        self._jsonseo_edit.setText(db.get_setting(SETTING_JSONSEO_KEY, ""))
        self._speedy_edit.setText(db.get_setting(SETTING_SPEEDYINDEX_KEY, ""))
        for provider in (
            PROVIDER_RIVER, PROVIDER_STOCK, PROVIDER_JSONSEO, PROVIDER_SPEEDYINDEX
        ):
            self._refresh_balance(provider)

    def _refresh_balance(self, provider: str):
        if self._closed:
            return
        url = self._edit_for(provider).text().strip()
        lbl = self._label_for(provider)
        if not url:
            lbl.setText(self._format_balance(provider, None, True))
            lbl.setStyleSheet("")
            return
        lbl.setText(self._format_balance(provider, None, False))
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
        lbl.setText(self._format_balance(provider, result, False))
        if result.ok and result.amount is not None and result.amount > 0:
            lbl.setStyleSheet("color: #00c853;")
        else:
            lbl.setStyleSheet("color: #ff5252;")

    def _save(self):
        db.set_setting(SETTING_RIVER_URL, self._river_edit.text().strip())
        db.set_setting(SETTING_STOCK_URL, self._stock_edit.text().strip())
        db.set_setting(SETTING_JSONSEO_KEY, self._jsonseo_edit.text().strip())
        db.set_setting(SETTING_SPEEDYINDEX_KEY, self._speedy_edit.text().strip())
        self.accept()

    def _wipe(self):
        ok = ask_confirm(
            self,
            "Очистить базу",
            "Удалить все задания, доноров и бэклинки безвозвратно?\n\n"
            "URL сервисов, API-ключи и тема не изменятся.",
            ok_label="Очистить",
        )
        if not ok:
            return
        if self._on_wipe is not None:
            self._on_wipe()
        else:
            db.wipe_check_data()
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
        for edit in (
            self._river_edit, self._stock_edit, self._jsonseo_edit, self._speedy_edit
        ):
            try:
                edit.editingFinished.disconnect()
            except TypeError:
                pass
        for worker in list(self._workers.values()):
            self._abandon_worker(worker)
        self._workers.clear()
        super().closeEvent(event)
