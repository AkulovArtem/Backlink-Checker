"""
Screen 1: Task list with search, date filters, sortable table, context menu.
"""

import logging
from datetime import datetime

from PyQt6.QtCore import QDate, QSortFilterProxyModel, Qt, QUrl
from PyQt6.QtGui import (
    QColor,
    QDesktopServices,
    QPainter,
    QPalette,
    QStandardItem,
    QStandardItemModel,
    QTextCharFormat,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from db import database as db
from gui.constants import STATUS_COLORS, STATUS_LABELS
from gui.theme_toggle import ThemeToggle

logger = logging.getLogger(__name__)

COL_CREATED, COL_NAME, COL_DONORS, COL_BACKLINKS, COL_STATUS = range(5)

# UserRole on the COL_STATUS item stores the integer progress (0-100) for
# running tasks; None for all other statuses so the delegate falls through.
_PROGRESS_ROLE = Qt.ItemDataRole.UserRole


class _ProgressDelegate(QStyledItemDelegate):
    """Renders a progress bar inside the STATUS cell for running tasks."""

    def paint(self, painter, option, index):
        progress = index.data(_PROGRESS_ROLE)
        if isinstance(progress, int):
            rect = option.rect.adjusted(4, 4, -4, -4)
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            # Background — palette adapts to theme automatically
            painter.setBrush(option.palette.color(QPalette.ColorRole.AlternateBase))
            painter.drawRoundedRect(rect, 3, 3)
            # Progress chunk
            if progress > 0:
                chunk_w = int(rect.width() * progress / 100)
                chunk_rect = rect.adjusted(0, 0, -(rect.width() - chunk_w), 0)
                painter.setBrush(QColor("#00c853"))
                painter.drawRoundedRect(chunk_rect, 3, 3)
            # Label
            painter.setPen(option.palette.color(QPalette.ColorRole.Text))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"🔄 {progress}%")
            painter.restore()
        else:
            super().paint(painter, option, index)


def _configure_calendar(de: QDateEdit) -> None:
    """Attach a pre-configured QCalendarWidget: no grid, no red weekends."""
    cal = QCalendarWidget()
    cal.setGridVisible(False)
    plain = QTextCharFormat()
    cal.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, plain)
    cal.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, plain)
    de.setCalendarWidget(cal)


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

    def lessThan(self, left, right) -> bool:
        # Date column: compare ISO strings stored in UserRole (sorts correctly)
        if left.column() == COL_CREATED:
            l_iso = left.data(Qt.ItemDataRole.UserRole + 1) or ""
            r_iso = right.data(Qt.ItemDataRole.UserRole + 1) or ""
            return l_iso < r_iso
        return super().lessThan(left, right)

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
    def __init__(self, dark_mode: bool = True, parent=None):
        super().__init__(parent)
        self._app = None   # set by app.py
        self._dark_mode = dark_mode
        self._task_row_index: dict[int, int] = {}
        self._build_ui()
        self.refresh()

    def set_app(self, app):
        self._app = app

    def theme_toggle(self) -> ThemeToggle:
        return self._theme_btn

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        # Action bar: tg btn (left) — stretch — create btn + toggle (right)
        action_bar = QHBoxLayout()
        tg_btn = QPushButton("Поддержка и обновления")
        tg_btn.setObjectName("btnTelegram")
        tg_btn.setFixedHeight(30)
        tg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tg_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://t.me/akulov_pro"))
        )
        action_bar.addWidget(tg_btn)
        action_bar.addStretch()
        btn_create = QPushButton("+ Создать задание")
        btn_create.setObjectName("btnCreate")
        btn_create.clicked.connect(self._go_create)
        action_bar.addWidget(btn_create)
        action_bar.addSpacing(12)
        self._theme_btn = ThemeToggle(self._dark_mode)
        action_bar.addWidget(self._theme_btn)
        root.addLayout(action_bar)

        # Heading
        lbl = QLabel("Проверка обратных ссылок")
        lbl.setObjectName("heading")
        root.addWidget(lbl)

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
        _configure_calendar(self._date_from)
        filter_bar.addWidget(QLabel("от"), 0)
        filter_bar.addWidget(self._date_from, 1)

        self._date_to = QDateEdit()
        self._date_to.setDisplayFormat("dd.MM.yyyy")
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.dateChanged.connect(self._apply_filter)
        _configure_calendar(self._date_to)
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
        self._table.clicked.connect(self._on_cell_clicked)

        self._empty_lbl = QLabel("Нет заданий\n\nНажмите «+ Создать задание», чтобы начать")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setObjectName("secondary")

        self._content_stack = QStackedWidget()
        self._content_stack.addWidget(self._empty_lbl)  # 0
        self._content_stack.addWidget(self._table)       # 1
        self._content_stack.setCurrentIndex(1)
        root.addWidget(self._content_stack)

    # ── Data ──────────────────────────────────────────────────────────────

    def refresh(self):
        self._model.removeRows(0, self._model.rowCount())
        self._task_row_index = {}
        tasks = db.get_all_tasks_with_counts()   # single JOIN query — no N+1
        for i, task in enumerate(tasks):
            donor_count = task["donor_count"]
            backlink_count = task["backlink_count"]
            status = task["status"]
            progress = task["progress"]

            # Format created_at
            created_iso = task["created_at"]
            try:
                dt = datetime.fromisoformat(created_iso)
                created_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                created_str = created_iso

            status_label = STATUS_LABELS.get(status, status)
            if status == "running" and progress > 0:
                status_label = f"🔄 В процессе ({progress}%)"

            date_item = QStandardItem(created_str)
            # ISO string stored as sort key so lessThan sorts chronologically
            date_item.setData(created_iso, Qt.ItemDataRole.UserRole + 1)

            donors_item = QStandardItem()
            donors_item.setData(donor_count, Qt.ItemDataRole.DisplayRole)

            backlinks_item = QStandardItem()
            backlinks_item.setData(backlink_count, Qt.ItemDataRole.DisplayRole)

            items = [
                date_item,
                QStandardItem(task["name"]),
                donors_item,
                backlinks_item,
                QStandardItem(status_label),
                QStandardItem("⋮"),
            ]
            # task_id stored on col-0 UserRole; progress on COL_STATUS UserRole
            items[0].setData(task["id"], Qt.ItemDataRole.UserRole)
            items[COL_STATUS].setData(
                progress if status == "running" else None, _PROGRESS_ROLE
            )
            color = QColor(STATUS_COLORS.get(status, "#888888"))
            items[COL_STATUS].setForeground(color)
            items[5].setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._model.appendRow(items)
            self._task_row_index[task["id"]] = i

        self._content_stack.setCurrentIndex(0 if not tasks else 1)

    def update_task_row(self, task_id: int):
        """Refresh a single row after worker emits progress."""
        row = self._task_row_index.get(task_id)
        if row is None:
            return
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
            progress if status == "running" else None, _PROGRESS_ROLE
        )
        bl = db.count_task_backlinks(task_id)
        self._model.item(row, COL_BACKLINKS).setData(bl, Qt.ItemDataRole.DisplayRole)

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

    def _on_cell_clicked(self, index):
        if index.column() == 5:
            self._show_context_menu(self._table.visualRect(index).center())

    def _on_row_double_click(self, index):
        if index.column() == 5:
            return
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
        act_retry_failed = menu.addAction("Повторить неудачные")
        act_add_links    = menu.addAction("Добавить ссылки")
        act_clone        = menu.addAction("Дублировать задание")
        act_export       = menu.addAction("Экспортировать в .xlsx")
        menu.addSeparator()
        act_delete = menu.addAction("Удалить задание")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action == act_retry and self._app:
            self._app.retry_task(task_id)
        elif action == act_retry_failed and self._app:
            self._app.retry_failed_task(task_id)
        elif action == act_add_links and self._app:
            self._app.edit_task(task_id)
        elif action == act_clone and self._app:
            self._app.clone_task(task_id)
        elif action == act_export and self._app:
            self._app.export_task(task_id)
        elif action == act_delete and self._app:
            self._confirm_delete(task_id)

    def _confirm_delete(self, task_id: int) -> None:
        if self._app:
            self._app.confirm_and_delete_task(task_id, self)
