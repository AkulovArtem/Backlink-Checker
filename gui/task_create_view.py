"""
Screen 2: Create task form.
"""

import json
import logging
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from db import database as db
from gui.icons import OrDivider
from utils.url_utils import MAX_DONORS, parse_donor_lines
from utils.user_agents import PROFILES

logger = logging.getLogger(__name__)


def _circle_label(n: str) -> QLabel:
    lbl = QLabel(n)
    lbl.setFixedSize(28, 28)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #34AADC, stop:1 #007AFF);"
        "color: #fff; border-radius: 14px; font-weight: bold;"
    )
    return lbl


class TaskCreateView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._app = None
        self._skip_confirmed = False
        self._edit_task_id: int | None = None
        self._existing_count = 0
        self._build_ui()

    def set_app(self, app):
        self._app = app

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(20)

        # Header
        header = QHBoxLayout()
        back_btn = QPushButton("← Назад")
        back_btn.clicked.connect(self._go_back)
        header.addWidget(back_btn)
        header.addStretch()
        self._heading_lbl = QLabel("Создать задание")
        self._heading_lbl.setObjectName("heading")
        header.addWidget(self._heading_lbl)
        header.addStretch()
        root.addLayout(header)

        # Section 1: name
        root.addLayout(self._section(1, "Название задания"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Введите название")
        root.addWidget(self._name_edit)

        # Section 2: donors
        root.addLayout(self._section(2, "Обратные ссылки (доноры) *"))
        self._existing_lbl = QLabel("")
        self._existing_lbl.setObjectName("secondary")
        self._existing_lbl.setWordWrap(True)
        self._existing_lbl.setVisible(False)
        root.addWidget(self._existing_lbl)
        self._donors_edit = QPlainTextEdit()
        self._donors_edit.setPlaceholderText(
            "https://example.com/products/item-123\nhttps://test-site.org/blog/article-title\n..."
        )
        self._donors_edit.setFixedHeight(140)
        self._donors_edit.textChanged.connect(self._on_donors_changed)
        root.addWidget(self._donors_edit)

        self._donors_hint = QLabel(
            "Введите ссылки, разделяя их переносами строк  •  До 100 000 ссылок"
        )
        self._donors_hint.setObjectName("secondary")
        root.addWidget(self._donors_hint)

        root.addWidget(OrDivider())

        file_row = QHBoxLayout()
        self._file_btn = QPushButton("Выберите файл (.txt)")
        self._file_btn.clicked.connect(self._load_file)
        file_row.addWidget(self._file_btn)
        file_row.addWidget(QLabel("Поддерживается только .txt"))
        file_row.addStretch()
        root.addLayout(file_row)

        # Section 3: targets
        root.addLayout(self._section(3, "Целевые домены (акцепторы) *"))
        self._targets_edit = QPlainTextEdit()
        self._targets_edit.setPlaceholderText("example.com\ntarget-site.org\n...")
        self._targets_edit.setFixedHeight(100)
        root.addWidget(self._targets_edit)

        hint2 = QLabel("Введите домены, разделяя их переносами строк  •  до 50 доменов")
        hint2.setObjectName("secondary")
        root.addWidget(hint2)

        # Settings (collapsible via GroupBox)
        settings_box = QGroupBox("Настройки")
        settings_box.setCheckable(True)
        settings_box.setChecked(False)
        settings_layout = QVBoxLayout(settings_box)
        settings_layout.setSpacing(10)

        # User-Agent
        ua_row = QHBoxLayout()
        ua_row.addWidget(QLabel("User-Agent:"))
        self._ua_combo = QComboBox()
        for key, profile in PROFILES.items():
            self._ua_combo.addItem(profile.label, key)
        self._ua_combo.currentIndexChanged.connect(self._on_ua_changed)
        ua_row.addWidget(self._ua_combo)
        ua_row.addStretch()
        settings_layout.addLayout(ua_row)

        self._custom_ua_edit = QLineEdit()
        self._custom_ua_edit.setPlaceholderText("Введите user-agent строку...")
        self._custom_ua_edit.setVisible(False)
        settings_layout.addWidget(self._custom_ua_edit)

        # Threads
        threads_row = QHBoxLayout()
        threads_row.addWidget(QLabel("Количество потоков:"))
        self._threads_spin = QSpinBox()
        self._threads_spin.setRange(1, 20)
        self._threads_spin.setValue(5)
        threads_row.addWidget(self._threads_spin)
        threads_row.addStretch()
        settings_layout.addLayout(threads_row)

        # Timeout
        timeout_row = QHBoxLayout()
        timeout_row.addWidget(QLabel("Таймаут страницы (сек):"))
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(5, 120)
        self._timeout_spin.setValue(30)
        timeout_row.addWidget(self._timeout_spin)
        timeout_row.addStretch()
        settings_layout.addLayout(timeout_row)

        root.addWidget(settings_box)

        self._index_check = QCheckBox("Проверка индексации ссылок")
        self._index_check.setToolTip(
            "Проверить в Google только доноров, у которых найден бэклинк. "
            "Нужен URL XMLRiver или XMLStock в Настройках."
        )
        root.addWidget(self._index_check)

        # Validation error label
        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #ff5252;")
        self._error_lbl.setVisible(False)
        root.addWidget(self._error_lbl)

        # Skipped-URL warning label (shown when some URLs lack http/https)
        self._warn_lbl = QLabel("")
        self._warn_lbl.setStyleSheet("color: #ffa726;")
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.setVisible(False)
        root.addWidget(self._warn_lbl)

        # Create / append button
        self._submit_btn = QPushButton("Создать")
        self._submit_btn.setObjectName("btnCreate")
        self._submit_btn.clicked.connect(self._submit)
        root.addWidget(self._submit_btn)

        root.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    @staticmethod
    def _section(num: int, title: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(_circle_label(str(num)))
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        row.addWidget(lbl)
        row.addStretch()
        return row

    # ── Slots ─────────────────────────────────────────────────────────────

    def _on_donors_changed(self):
        """Reset skip-confirmation so the warning re-appears if the text changes."""
        if self._skip_confirmed:
            self._skip_confirmed = False
            self._warn_lbl.setVisible(False)

    def _on_ua_changed(self):
        is_custom = self._ua_combo.currentData() == "custom"
        self._custom_ua_edit.setVisible(is_custom)

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть файл", "", "Text files (*.txt)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
            existing = self._donors_edit.toPlainText().strip()
            combined = (existing + "\n" + text).strip() if existing else text
            self._donors_edit.setPlainText(combined)
        except Exception as exc:
            logger.error("File read error: %s", exc)

    def _submit(self):
        self._error_lbl.setVisible(False)
        self._warn_lbl.setVisible(False)

        name = self._name_edit.text().strip() or "Задание"
        is_append = self._edit_task_id is not None
        remaining = (
            max(0, MAX_DONORS - self._existing_count) if is_append else MAX_DONORS
        )

        if is_append and remaining == 0:
            self._error_lbl.setText("Достигнут лимит 100 000 доноров в задании.")
            self._error_lbl.setVisible(True)
            return

        valid_donors, invalid_count = parse_donor_lines(
            self._donors_edit.toPlainText(), limit=remaining
        )

        # Parse & deduplicate targets (cap at 50)
        raw_targets = [
            t.strip() for t in self._targets_edit.toPlainText().splitlines()
            if t.strip()
        ]
        targets = list(dict.fromkeys(raw_targets))[:50]

        if not valid_donors:
            self._error_lbl.setText(
                "Добавьте хотя бы одну корректную ссылку-донор (http/https)."
            )
            self._error_lbl.setVisible(True)
            return
        if not targets:
            self._error_lbl.setText("Добавьте хотя бы один целевой домен.")
            self._error_lbl.setVisible(True)
            return

        ua_preset = self._ua_combo.currentData()
        custom_ua = self._custom_ua_edit.text().strip() if ua_preset == "custom" else None
        if ua_preset == "custom" and not custom_ua:
            self._error_lbl.setText("Введите строку User-Agent для режима «Custom».")
            self._error_lbl.setVisible(True)
            return

        # Warn about skipped URLs; require a second click to confirm
        if invalid_count > 0 and not self._skip_confirmed:
            action = "добавлено" if is_append else "создано"
            btn_label = "«Добавить и проверить»" if is_append else "«Создать»"
            self._warn_lbl.setText(
                f"⚠  {invalid_count} URL пропущено — нет схемы http:// или https://. "
                f"Задание будет {action} с {len(valid_donors)} донором(ами). "
                f"Нажмите {btn_label} ещё раз для подтверждения."
            )
            self._warn_lbl.setVisible(True)
            self._skip_confirmed = True
            return

        self._skip_confirmed = False

        threads = self._threads_spin.value()
        timeout = self._timeout_spin.value()
        check_index = self._index_check.isChecked()

        try:
            if is_append:
                task_id = self._edit_task_id
                if task_id is None:
                    return
                db.update_task_fields(
                    task_id,
                    name=name,
                    user_agent=ua_preset,
                    custom_user_agent=custom_ua,
                    threads=threads,
                    timeout=timeout,
                    check_google_index=1 if check_index else 0,
                )
                result = db.add_donors_to_task(task_id, valid_donors)
                if result["added"] == 0:
                    self._error_lbl.setText(
                        "Все указанные ссылки уже есть в задании."
                    )
                    self._error_lbl.setVisible(True)
                    return
            else:
                task_id = db.create_task(
                    name=name,
                    target_domains=targets,
                    user_agent=ua_preset,
                    custom_user_agent=custom_ua,
                    threads=threads,
                    timeout=timeout,
                    check_google_index=check_index,
                )
                db.create_donors_bulk(task_id, valid_donors)
        except Exception:
            logger.exception("Failed to save task")
            self._error_lbl.setText(
                "Ошибка сохранения задания. Подробности — в лог-файле."
            )
            self._error_lbl.setVisible(True)
            return

        if self._app:
            self._app.start_task(task_id)
            if is_append:
                self._app.show_report(task_id)
            else:
                self._app.show_list()

    def _go_back(self):
        if self._app:
            self._app.show_list()

    def reset(self):
        self._edit_task_id = None
        self._existing_count = 0
        self._name_edit.clear()
        self._donors_edit.clear()
        self._targets_edit.clear()
        self._targets_edit.setReadOnly(False)
        self._custom_ua_edit.clear()
        self._ua_combo.setCurrentIndex(0)
        self._threads_spin.setValue(5)
        self._timeout_spin.setValue(30)
        self._index_check.setChecked(False)
        self._error_lbl.setVisible(False)
        self._warn_lbl.setVisible(False)
        self._existing_lbl.setVisible(False)
        self._existing_lbl.clear()
        self._heading_lbl.setText("Создать задание")
        self._submit_btn.setText("Создать")
        self._donors_hint.setText(
            "Введите ссылки, разделяя их переносами строк  •  До 100 000 ссылок"
        )
        self._skip_confirmed = False

    def enter_append_mode(self, task, existing_count: int) -> None:
        """Switch the form to add new donor URLs to an existing task."""
        self.reset()
        self._edit_task_id = int(task["id"])
        self._existing_count = existing_count
        remaining = max(0, MAX_DONORS - existing_count)

        self._heading_lbl.setText("Добавить ссылки")
        self._submit_btn.setText("Добавить и проверить")
        self._name_edit.setText(task["name"])
        self._existing_lbl.setText(
            f"В задании уже {existing_count} донор(ов). "
            "Новые ссылки проверятся по тем же целевым доменам. "
            "Уже проверенные не будут перезапущены."
        )
        self._existing_lbl.setVisible(True)
        self._donors_hint.setText(
            "Вставьте новые ссылки, по одной на строку  •  "
            f"Можно добавить ещё {remaining}"
        )

        targets = json.loads(task["target_domains"])
        self._targets_edit.setPlainText("\n".join(targets))
        self._targets_edit.setReadOnly(True)

        ua = task["user_agent"] or "desktop_chrome"
        for i in range(self._ua_combo.count()):
            if self._ua_combo.itemData(i) == ua:
                self._ua_combo.setCurrentIndex(i)
                break
        custom = task["custom_user_agent"] or ""
        if custom:
            self._custom_ua_edit.setText(custom)
        self._threads_spin.setValue(task["threads"])
        self._timeout_spin.setValue(task["timeout"])
        try:
            self._index_check.setChecked(bool(task["check_google_index"]))
        except (KeyError, IndexError):
            self._index_check.setChecked(False)

    def prefill(self, task, donors: list) -> None:
        """Pre-fill the form with data from an existing task for cloning."""
        self._name_edit.setText(f"{task['name']} (копия)")
        self._donors_edit.setPlainText("\n".join(d["url"] for d in donors))
        targets = json.loads(task["target_domains"])
        self._targets_edit.setPlainText("\n".join(targets))
        ua = task["user_agent"] or "desktop_chrome"
        for i in range(self._ua_combo.count()):
            if self._ua_combo.itemData(i) == ua:
                self._ua_combo.setCurrentIndex(i)
                break
        custom = task["custom_user_agent"] or ""
        if custom:
            self._custom_ua_edit.setText(custom)
        self._threads_spin.setValue(task["threads"])
        self._timeout_spin.setValue(task["timeout"])
        try:
            self._index_check.setChecked(bool(task["check_google_index"]))
        except (KeyError, IndexError):
            self._index_check.setChecked(False)
