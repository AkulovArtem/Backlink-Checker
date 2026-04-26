"""
Screen 1: Task list with search, date filters, sortable table, context menu.
"""

import logging
from datetime import datetime

from PyQt6.QtCore import Qt, QSortFilterProxyModel, QDate
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QDateEdit, QTableView, QHeaderView,
    QMenu, QAbstractItemView, QMessageBox,
    QApplication, QStyle, QStyleOptionProgressBar, QStyledItemDelegate,
)

from db import database as db

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "pending":   "⏳ В очереди",
    "running":   "🔄 В процессе",
    "completed": "✅ Завершено",
    "error":     "❌ Ошибка",
}
STATUS_COLORS = {
    "pending":   "#888888",
    "running":   "#ffa726",
    "completed": "#00c853",
    "error":     "#ff5252",
}

COL_CREATED, COL_NAME, COL_DONORS, COL_BACKLINKS, COL_STATUS = range(5)

# UserRole on the COL_STATUS item stores the integer progress (0-100) for
# running tasks; None for all other statuses so the delegate falls through.
_PROGRESS_ROLE = Qt.ItemDataRole.UserRole


class _ProgressDelegate(QStyledItemDelegate):
    """Renders a QProgressBar inside the STATUS cell for running tasks."""

    def paint(self, painter, option, index):
        progress = index.data(_PROGRESS_ROLE)
        if isinstance(progress, int):
            opt = QStyleOptionProgressBar()
            opt.rect = option.rect.adjusted(2, 3, -2, -3)
            opt.minimum = 0
            opt.maximum = 100
            opt.progress = progress
            opt.text = f"🔄 {progress}%"
            opt.textVisible = True
            opt.textAlignment = Qt.AlignmentFlag.AlignCenter
            QApplication.style().drawControl(
                QStyle.ControlElement.CE_ProgressBar, opt, painter
            )
        else:
            super().paint(painter, option, index)


class _TaskFilterProxy(QSortFilterProxyModel):
    """Proxy that filters tasks by name text and date range.
    Uses filterAcceptsRow so filtering survives column sorting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._date_from = QDate(2000, 1, 1)
        self._date_to = QDate.currentDate()

    def set_filters(self, text: str, date_from: QDate, date_to: QDate) -> None:
        self._text = text.lower()
        self._date_from = date_from
        self._date_to = date_to
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        model = self.sourceModel()
        if not isinstance(model, QStandardItemModel):
            return True

        if self._text:
            name_item = model.item(source_row, COL_NAME)
            if not name_item or self._text not in name_item.text().lower():
                return False

        date_item = model.item(source_row, COL_CREATED)
        if date_item:
            try:
                row_dt = datetime.strptime(date_item.text(), "%d.%m.%Y %H:%M")
                row_qdate = QDate(row_dt.year, row_dt.month, row_dt.day)
                if not (self._date_from <= row_qdate <= self._date_to):
                    return False
            except ValueError:
                pass

        return True


class TaskListView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._app = None   # set by app.py
        self._build_ui()
        self.refresh()

    def set_app(self, app):
        self._app = app

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # Header
        header = QHBoxLayout()
        lbl = QLabel("🔗  Проверка обратных ссылок")
        lbl.setObjectName("heading")
        header.addWidget(lbl)
        header.addStretch()
        btn_create = QPushButton("+ Создать задание")
        btn_create.setObjectName("btnCreate")
        btn_create.clicked.connect(self._go_create)
        header.addWidget(btn_create)
        root.addLayout(header)

        # Filters
        filter_bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск задания...")
        self._search.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._search, 3)

        self._date_from = QDateEdit()
        self._date_from.setDisplayFormat("dd.MM.yyyy")
        self._date_from.setCalendarPopup(True)
        self._date_from.setSpecialValueText("Дата начала")
        self._date_from.setDate(QDate(2000, 1, 1))
        self._date_from.dateChanged.connect(self._apply_filter)
        filter_bar.addWidget(QLabel("от"), 0)
        filter_bar.addWidget(self._date_from, 1)

        self._date_to = QDateEdit()
        self._date_to.setDisplayFormat("dd.MM.yyyy")
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.dateChanged.connect(self._apply_filter)
        filter_bar.addWidget(QLabel("до"), 0)
        filter_bar.addWidget(self._date_to, 1)

        root.addLayout(filter_bar)

        # Table
        self._model = QStandardItemModel(0, 6, self)
        self._model.setHorizontalHeaderLabels(
            ["СОЗДАНО", "НАЗВАНИЕ", "ДОНОРОВ", "БЕКЛИНКОВ", "СТАТУС", "ДЕЙСТВИЯ"]
        )

        self._proxy = _TaskFilterProxy(self)
        self._proxy.setSourceModel(self._model)

        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSortIndicatorShown(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.doubleClicked.connect(self._on_row_double_click)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._progress_delegate = _ProgressDelegate(self._table)
        self._table.setItemDelegateForColumn(COL_STATUS, self._progress_delegate)
        root.addWidget(self._table)

    # ── Data ──────────────────────────────────────────────────────────────

    def refresh(self):
        self._model.removeRows(0, self._model.rowCount())
        tasks = db.get_all_tasks_with_counts()   # single JOIN query — no N+1
        for task in tasks:
            donor_count = task["donor_count"]
            backlink_count = task["backlink_count"]
            status = task["status"]
            progress = task["progress"]

            # Format created_at
            try:
                dt = datetime.fromisoformat(task["created_at"])
                created_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                created_str = task["created_at"]

            status_label = STATUS_LABELS.get(status, status)
            if status == "running" and progress > 0:
                status_label = f"🔄 В процессе ({progress}%)"

            items = [
                QStandardItem(created_str),
                QStandardItem(task["name"]),
                QStandardItem(str(donor_count)),
                QStandardItem(str(backlink_count)),
                QStandardItem(status_label),
                QStandardItem("⋮"),
            ]
            # task_id stored on col-0 UserRole; progress on COL_STATUS UserRole
            items[0].setData(task["id"], Qt.ItemDataRole.UserRole)
            items[COL_STATUS].setData(
                _PROGRESS_ROLE, progress if status == "running" else None
            )
            color = QColor(STATUS_COLORS.get(status, "#888888"))
            items[COL_STATUS].setForeground(color)
            items[5].setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._model.appendRow(items)

    def update_task_row(self, task_id: int):
        """Refresh a single row after worker emits progress."""
        for row in range(self._model.rowCount()):
            item = self._model.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == task_id:
                task = db.get_task(task_id)
                if not task:
                    return
                status = task["status"]
                progress = task["progress"]
                status_label = STATUS_LABELS.get(status, status)
                if status == "running" and progress > 0:
                    status_label = f"🔄 В процессе ({progress}%)"
                self._model.item(row, COL_STATUS).setText(status_label)
                self._model.item(row, COL_STATUS).setForeground(
                    QColor(STATUS_COLORS.get(status, "#888888"))
                )
                self._model.item(row, COL_STATUS).setData(
                    _PROGRESS_ROLE, progress if status == "running" else None
                )
                bl = db.count_task_backlinks(task_id)
                self._model.item(row, COL_BACKLINKS).setText(str(bl))
                return

    # ── Filtering ─────────────────────────────────────────────────────────

    def _apply_filter(self):
        self._proxy.set_filters(
            self._search.text(),
            self._date_from.date(),
            self._date_to.date(),
        )

    # ── Navigation ────────────────────────────────────────────────────────

    def _get_task_id_for_proxy_row(self, proxy_row: int) -> int | None:
        source_row = self._proxy.mapToSource(self._proxy.index(proxy_row, 0)).row()
        item = self._model.item(source_row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_row_double_click(self, index):
        task_id = self._get_task_id_for_proxy_row(index.row())
        if task_id and self._app:
            self._app.show_report(task_id)

    def _go_create(self):
        if self._app:
            self._app.show_create()

    # ── Context menu ──────────────────────────────────────────────────────

    def _show_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        task_id = self._get_task_id_for_proxy_row(index.row())
        if task_id is None:
            return

        menu = QMenu(self)
        act_retry        = menu.addAction("Повторить проверку")
        act_retry_failed = menu.addAction("Повторить упавшие доноры")
        act_clone        = menu.addAction("Дублировать задание")
        act_export       = menu.addAction("Экспортировать в .xlsx")
        menu.addSeparator()
        act_delete = menu.addAction("Удалить задание")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == act_retry and self._app:
            self._app.retry_task(task_id)
        elif action == act_retry_failed and self._app:
            self._app.retry_failed_task(task_id)
        elif action == act_clone and self._app:
            self._app.clone_task(task_id)
        elif action == act_export and self._app:
            self._app.export_task(task_id)
        elif action == act_delete and self._app:
            self._confirm_delete(task_id)

    def _confirm_delete(self, task_id: int) -> None:
        task = db.get_task(task_id)
        name = task["name"] if task else f"#{task_id}"
        reply = QMessageBox.question(
            self,
            "Удалить задание",
            f"Удалить задание «{name}»?\n\nВсе доноры и бэклинки будут удалены безвозвратно.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._app.delete_task(task_id)  # type: ignore[union-attr]
