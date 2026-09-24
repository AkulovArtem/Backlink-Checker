"""
Screen 3: Task report — summary cards, SE tabs, analytics, donors table, top anchors.
"""

import json
import logging
import sqlite3
from collections import defaultdict

from PyQt6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRectF,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QUrl,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QPainter,
    QPainterPath,
    QPalette,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from db import database as db
from gui.constants import STATUS_COLORS, STATUS_DOT, STATUS_LABELS
from utils.url_utils import get_domain, matches_target, normalize_domain


def _clipboard_set(text: str) -> None:
    """Copy text to system clipboard; guards against clipboard() returning None."""
    cb = QApplication.clipboard()
    if cb is not None:
        cb.setText(text)

logger = logging.getLogger(__name__)

_SE_LABELS = {
    "google": "Google",
    "yandex": "Яндекс",
    "bing":   "Bing",
    "baidu":  "Baidu",
}

_SE_INDEX_COL = {
    "google": "index_google",
    "yandex": "index_yandex",
    "bing":   "index_bing",
    "baidu":  "index_baidu",
}


def matches_google_filter(google_indexed, key: str) -> bool:
    """True if a donor's google_indexed value passes the В GOOGLE filter key."""
    value = google_indexed or ""
    if key == "all":
        return True
    if key == "unchecked":
        return value not in ("indexed", "not_indexed", "error")
    return value == key


def matches_robots_filter(index_value, key: str) -> bool:
    """True if a donor's robots value for the active SE passes the ROBOTS filter."""
    value = index_value or ""
    if key == "all":
        return True
    if key == "unchecked":
        return value not in ("open", "closed")
    return value == key

REL_COLORS = {
    "dofollow":  "#00c853",
    "nofollow":  "#ff5252",
    "ugc":       "#ffa726",
    "sponsored": "#42a5f5",
}

HTTP_COLORS = {
    2: "#00c853",
    4: "#ffa726",
    5: "#ff5252",
}


COL_D_CODE, COL_D_URL, COL_D_ROBOTS, COL_D_GOOGLE, COL_D_LINKS, COL_D_INT, COL_D_EXT = range(7)
_DONOR_HEADERS = [
    "Код", "Ссылка-донор", "Robots", "В Google",
    "Ссылки на целевой домен", "Вн. ссылок", "Внш. ссылок",
]
_SORT_ROLE = Qt.ItemDataRole.UserRole

# key → (label, [(value, text), ...]); the value is kept in self._donor_filter_<key>
_DONOR_FILTERS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "type": ("Rel", [
        ("all", "Все"), ("dofollow", "Dofollow"), ("nofollow", "Nofollow"),
        ("ugc", "UGC"), ("sponsored", "Sponsored"),
    ]),
    "index": ("Robots", [
        ("all", "Все"), ("open", "Открыто"), ("closed", "Закрыто"),
        ("unchecked", "Не проверялось"),
    ]),
    "status": ("Статус", [
        ("all", "Все"), ("found", "Найдено"), ("not_found", "Не найдено"),
        ("not_loaded", "Не загружено"), ("pending", "В очереди"),
    ]),
    "google": ("В Google", [
        ("all", "Все"), ("indexed", "Да"), ("not_indexed", "Нет"),
        ("error", "Ошибка"), ("unchecked", "Не проверялось"),
    ]),
}

_ROBOTS_CELL = {"open": ("Открыто", "#00c853"), "closed": ("Закрыто", "#ff5252")}
_GOOGLE_CELL = {
    "indexed": ("Да", "#00c853"),
    "not_indexed": ("Нет", "#ff5252"),
    "error": ("Ошибка", "#ffa726"),
}


def _row_value(row, key: str):
    """Column value or None — older databases may lack newer columns."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _style_table(table: QTableView) -> None:
    """Shared compact look for report tables."""
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setWordWrap(False)
    vh = table.verticalHeader()
    if vh is not None:  # QHeaderView is falsy while it has no sections
        vh.setVisible(False)
        vh.setDefaultSectionSize(32)
    hh = table.horizontalHeader()
    if hh is not None:
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


def _capture_view_state(view: QTableView | None) -> tuple | None:
    """(sort column, sort order, scroll) of a table about to be rebuilt."""
    if view is None:
        return None
    try:
        header = view.horizontalHeader()
        bar = view.verticalScrollBar()
        if header is None or bar is None:
            return None
        return header.sortIndicatorSection(), header.sortIndicatorOrder(), bar.value()
    except RuntimeError:  # widget already deleted
        return None


def _restore_view_state(view: QTableView | None, state: tuple | None) -> None:
    if view is None or state is None:
        return
    section, order, scroll = state
    if section >= 0:
        view.sortByColumn(section, order)

    def _scroll() -> None:
        # Deferred: the scroll range exists only after the new table is laid out.
        try:
            bar = view.verticalScrollBar()
            if bar is not None:
                bar.setValue(scroll)
        except RuntimeError:  # replaced by another refresh meanwhile
            pass

    QTimer.singleShot(0, _scroll)


class DonorTableModel(QAbstractTableModel):
    """Donor rows for the report; filtering happens before set_rows()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple] = []   # (donor row, its backlinks after the Rel filter)
        self._se_col = "index_google"
        self._se_label = "Google"

    def set_rows(self, rows: list[tuple], se_col: str, se_label: str) -> None:
        self.beginResetModel()
        self._rows = rows
        self._se_col = se_col
        self._se_label = se_label
        self.endResetModel()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, COL_D_ROBOTS, COL_D_ROBOTS)

    def donor(self, row: int):
        return self._rows[row][0] if 0 <= row < len(self._rows) else None

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_DONOR_HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == COL_D_ROBOTS:
                return f"Robots ({self._se_label})"
            return _DONOR_HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        donor, bls = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._text(donor, bls, col)
        if role == Qt.ItemDataRole.ForegroundRole:
            color = self._color(donor, col)
            return QBrush(color) if color is not None else None
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(donor, bls, col)
        if role == _SORT_ROLE:
            if col == COL_D_CODE:
                return int(donor["http_status"] or 0)
            if col in (COL_D_INT, COL_D_EXT):
                return int(self._text(donor, bls, col))
            return self._text(donor, bls, col)
        return None

    def _text(self, donor, bls, col):
        if col == COL_D_CODE:
            return str(donor["http_status"] or donor["error_code"] or "—")
        if col == COL_D_URL:
            return donor["url"]
        if col == COL_D_ROBOTS:
            return _ROBOTS_CELL.get(donor[self._se_col], ("—", ""))[0]
        if col == COL_D_GOOGLE:
            return _GOOGLE_CELL.get(_row_value(donor, "google_indexed"), ("—", ""))[0]
        if col == COL_D_LINKS:
            if not bls:
                return "—"
            first = bls[0]
            text = f"{first['target_url']}  [{first['rel_type']}]  «{first['anchor_text'] or '—'}»"
            return f"{text}   +{len(bls) - 1}" if len(bls) > 1 else text
        if col == COL_D_INT:
            return str(donor["internal_links"] or 0)
        if col == COL_D_EXT:
            return str(donor["external_links"] or 0)
        return None

    def _color(self, donor, col) -> QColor | None:
        if col == COL_D_CODE:
            code = donor["http_status"]
            return QColor(HTTP_COLORS.get(int(code) // 100, "#888888") if code else "#888888")
        if col == COL_D_URL:
            return QApplication.palette().color(QPalette.ColorRole.Link)
        if col == COL_D_ROBOTS:
            return QColor(_ROBOTS_CELL.get(donor[self._se_col], ("", "#888888"))[1])
        if col == COL_D_GOOGLE:
            value = _row_value(donor, "google_indexed")
            return QColor(_GOOGLE_CELL.get(value, ("", "#888888"))[1])
        return None

    def _tooltip(self, donor, bls, col):
        if col == COL_D_URL:
            return f"{donor['url']}\nДвойной клик — открыть в браузере"
        if col == COL_D_GOOGLE:
            return _row_value(donor, "google_index_error") or None
        if col == COL_D_LINKS and bls:
            return "\n".join(
                f"{b['target_url']}  [{b['rel_type']}]  «{b['anchor_text'] or '—'}»"
                for b in bls
            )
        return None


def _secondary(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("secondary")
    return lbl


def _badge(text: str, color: str) -> QLabel:
    # Tinted fill via rgba(): Qt reads "#RRGGBBAA" as ARGB, which turned
    # orange into dark red and made blue fully transparent.
    c = QColor(color)
    fill = f"rgba({c.red()}, {c.green()}, {c.blue()}, 36)"
    lbl = QLabel(text)
    lbl.setTextFormat(Qt.TextFormat.PlainText)
    lbl.setStyleSheet(
        f"background-color: {fill}; color: {c.name()};"
        "border: none; border-radius: 10px;"
        "padding: 2px 10px; font-size: 11px; font-weight: 600;"
    )
    return lbl


class _SegBar(QWidget):
    """Segmented bar — fills proportionally with per-segment colours.

    Pass `total` to anchor proportions to a fixed denominator (e.g. total
    donors) so that unchecked/pending items show as the unfilled background
    instead of being excluded from the ratio.
    """

    def __init__(self, segments: list[tuple[int, str]],
                 total: int | None = None, parent=None):
        super().__init__(parent)
        self._segments = segments
        self._total = total
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_segments(self, segments: list[tuple[int, str]],
                     total: int | None = None) -> None:
        self._segments = segments
        if total is not None:
            self._total = total
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = float(self.width()), float(self.height())
        r = H / 2
        full = QRectF(0.0, 0.0, W, H)
        total = (self._total if self._total is not None
                 else sum(v for v, _ in self._segments if v > 0))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.palette().color(QPalette.ColorRole.AlternateBase))
        p.drawRoundedRect(full, r, r)

        if total > 0:
            clip = QPainterPath()
            clip.addRoundedRect(full, r, r)
            p.setClipPath(clip)
            x = 0.0
            for val, color in self._segments:
                if val <= 0:
                    continue
                seg_w = W * val / total
                p.setBrush(QColor(color))
                p.drawRect(QRectF(x, 0.0, seg_w, H))
                x += seg_w

        p.end()


def _card(title: str, value: str, subtitle: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setMinimumWidth(160)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(6)
    t = QLabel(title)
    t.setObjectName("secondary")
    layout.addWidget(t)
    v = QLabel(value)
    v.setStyleSheet("font-size: 20px; font-weight: 700;")
    v.setWordWrap(True)
    layout.addWidget(v)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("secondary")
        layout.addWidget(s)
    return frame


class ReportView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._app = None
        self._task_id = None
        self._current_se = "google"
        self._donor_filter_type = "all"
        self._donor_filter_index = "all"
        self._donor_filter_status = "all"
        self._donor_filter_google = "all"
        self._donors_cache: list = []
        self._backlinks_cache: list = []
        self._bl_donor_map_cache: dict = {}
        self._filter_combos: dict[str, QComboBox] = {}
        self._data_tabs: QTabWidget | None = None
        self._donor_search: QLineEdit | None = None
        self._bl_search: QLineEdit | None = None
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

        self._container = QWidget()
        self._container.setMinimumWidth(800)
        self._root = QVBoxLayout(self._container)
        self._root.setContentsMargins(24, 24, 24, 24)
        self._root.setSpacing(16)

        scroll.setWidget(self._container)
        outer.addWidget(scroll)

    @staticmethod
    def _delete_layout(layout) -> None:
        """Recursively delete all items in a layout."""
        if layout is None:
            return
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = child.layout()
                if sub is not None:
                    ReportView._delete_layout(sub)
            # QSpacerItem: Python GC handles cleanup when child goes out of scope

    def _clear(self):
        self._delete_layout(self._root)

    # ── Load task ─────────────────────────────────────────────────────────

    def load_task(self, task_id: int):
        switching = self._task_id != task_id
        if switching:
            self._donor_filter_type = "all"
            self._donor_filter_index = "all"
            self._donor_filter_status = "all"
            self._donor_filter_google = "all"
            self._current_se = "google"
        self._task_id = task_id
        # Auto-refresh during a check must not reset sorting or scroll position.
        _donor_view_state = (
            None if switching else _capture_view_state(getattr(self, "_donor_view", None))
        )
        _bl_view_state = (
            None if switching else _capture_view_state(getattr(self, "_bl_table", None))
        )
        if switching:
            _active_tab = 0
            _donor_search_text = ""
            _bl_search_text = ""
        else:
            _active_tab = (
                self._data_tabs.currentIndex() if self._data_tabs is not None else 0
            )
            _donor_search_text = (
                self._donor_search.text() if self._donor_search is not None else ""
            )
            _bl_search_text = (
                self._bl_search.text() if self._bl_search is not None else ""
            )
        self._clear()

        task = db.get_task(task_id)
        if not task:
            return

        try:
            domains = db.parse_target_domains(task["target_domains"])
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Corrupted target_domains for task %d: %s", task_id, exc)
            err = QLabel("Не удалось загрузить задание: повреждены целевые домены.")
            err.setWordWrap(True)
            self._root.addWidget(err)
            return
        donors = db.get_donors_for_task(task_id)
        backlinks = db.get_backlinks_for_task(task_id)
        stats = db.get_donor_stats(task_id)

        # donor_map built early — needed for anchor stats domain counting
        donor_map = {d["id"]: d["url"] for d in donors}

        # Rich anchor stats — computed client-side for perfect consistency with backlinks list
        _anchor_groups: dict[str, list] = defaultdict(list)
        for _bl in backlinks:
            _anchor_groups[_bl["anchor_text"] or ""].append(_bl)

        _total_bl = len(backlinks)
        anchor_stats = []
        for _anchor, _bls in sorted(_anchor_groups.items(), key=lambda x: -len(x[1])):
            _df = sum(1 for b in _bls if b["rel_type"] == "dofollow")
            _domains = len({
                get_domain(donor_map.get(b["donor_id"], ""))
                for b in _bls
                if donor_map.get(b["donor_id"])
            })
            anchor_stats.append({
                "anchor_text": _anchor,
                "cnt": len(_bls),
                "domains": _domains,
                "dofollow": _df,
                "nofollow": len(_bls) - _df,
                "pct": len(_bls) / _total_bl * 100 if _total_bl > 0 else 0.0,
            })

        # Counts
        total_donors = len(donors)
        found = stats.get("found", 0)
        not_found = stats.get("not_found", 0)
        not_loaded = stats.get("not_loaded", 0)
        pending = stats.get("pending", 0)

        df_count = sum(1 for bl in backlinks if bl["rel_type"] == "dofollow")
        nf_count = len(backlinks) - df_count
        text_count = sum(1 for bl in backlinks if bl["anchor_type"] == "text")
        img_count = len(backlinks) - text_count

        _idx_col = _SE_INDEX_COL.get(self._current_se, "index_google")
        open_count  = sum(1 for d in donors if d[_idx_col] == "open")
        closed_count = sum(1 for d in donors if d[_idx_col] == "closed")

        # ── Header ────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        back_btn = QPushButton("← Назад")
        back_btn.clicked.connect(self._go_back)
        header_row.addWidget(back_btn)

        title_lbl = QLabel(task["name"])
        title_lbl.setTextFormat(Qt.TextFormat.PlainText)
        title_lbl.setObjectName("heading")
        header_row.addWidget(title_lbl)
        header_row.addWidget(_badge("Проверка обратных ссылок", "#007AFF"))

        status = task["status"]
        status_color = STATUS_COLORS.get(status, "#888888")
        header_row.addWidget(_badge(STATUS_LABELS.get(status, status), status_color))
        header_row.addStretch()

        actions_btn = QPushButton("Действия ▾")
        actions_btn.clicked.connect(lambda: self._show_actions_menu(actions_btn))
        header_row.addWidget(actions_btn)
        self._root.addLayout(header_row)

        # ── Summary cards ─────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        created_str = db.format_task_created(task["created_at"])
        cards_row.addWidget(_card("Дата создания", created_str))
        cards_row.addWidget(_card("Ссылки-доноры", str(total_donors)))
        domains_short = ", ".join(domains[:2]) + (f" +{len(domains)-2}" if len(domains) > 2 else "")
        cards_row.addWidget(_card("Целевые домены", domains_short))

        # Donor status card with progress bar
        status_card = QFrame()
        status_card.setObjectName("card")
        status_card.setMinimumWidth(200)
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(16, 14, 16, 14)
        sc_layout.setSpacing(6)
        sc_layout.addWidget(_secondary("Статус доноров"))
        nums = QLabel(
            f'<span style="color:#00c853"><b>{found}</b></span>'
            f' / <span style="color:#ffa726"><b>{not_found}</b></span>'
            f' / <span style="color:#ff5252"><b>{not_loaded}</b></span>'
            f' / <span style="color:#888888"><b>{pending}</b></span>'
        )
        nums.setStyleSheet("font-size: 16px;")
        sc_layout.addWidget(nums)
        sc_layout.addWidget(_SegBar([
            (found,       "#00c853"),
            (not_found,   "#ffa726"),
            (not_loaded,  "#ff5252"),
        ], total=total_donors))
        sc_layout.addWidget(QLabel(
            '<span style="color:#00c853">■ Найдено</span>'
            '  <span style="color:#ffa726">■ Не найдено</span>'
            '  <span style="color:#ff5252">■ Ошибка</span>'
            '  <span style="color:#888888">■ В очереди</span>'
        ))

        cards_row.addWidget(status_card)

        g_yes = g_no = g_err = 0
        for d in donors:
            try:
                gv = d["google_indexed"]
            except (KeyError, IndexError):
                gv = None
            if gv == "indexed":
                g_yes += 1
            elif gv == "not_indexed":
                g_no += 1
            elif gv == "error":
                g_err += 1
        g_skip = total_donors - g_yes - g_no - g_err
        g_card = QFrame()
        g_card.setObjectName("card")
        g_card.setMinimumWidth(200)
        g_layout = QVBoxLayout(g_card)
        g_layout.setContentsMargins(16, 14, 16, 14)
        g_layout.setSpacing(6)
        g_layout.addWidget(_secondary("В индексе Google"))
        g_nums = QLabel(
            f'<span style="color:#00c853"><b>{g_yes}</b></span>'
            f' / <span style="color:#ff5252"><b>{g_no}</b></span>'
            f' / <span style="color:#ffa726"><b>{g_err}</b></span>'
            f' / <span style="color:#888888"><b>{g_skip}</b></span>'
        )
        g_nums.setStyleSheet("font-size: 16px;")
        g_layout.addWidget(g_nums)
        g_layout.addWidget(_SegBar([
            (g_yes, "#00c853"),
            (g_no,  "#ff5252"),
            (g_err, "#ffa726"),
        ], total=total_donors))
        g_layout.addWidget(QLabel(
            '<span style="color:#00c853">■ Да</span>'
            '  <span style="color:#ff5252">■ Нет</span>'
            '  <span style="color:#ffa726">■ Ошибка</span>'
            '  <span style="color:#888888">■ Не проверялось</span>'
        ))
        cards_row.addWidget(g_card)

        self._root.addLayout(cards_row)

        # ── Analytics cards ───────────────────────────────────────────────
        analytics_row = QHBoxLayout()

        def _analytics_block(title, a_val, b_val, a_label, b_label, a_color, b_color):
            frame = QFrame()
            frame.setObjectName("card")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(16, 14, 16, 14)
            fl.setSpacing(6)
            fl.addWidget(_secondary(title))
            nums_lbl = QLabel(f"{a_val} / {b_val}")
            nums_lbl.setStyleSheet("font-size: 20px; font-weight: 700;")
            fl.addWidget(nums_lbl)
            fl.addWidget(_SegBar([(a_val, a_color), (b_val, b_color)]))
            legend = QLabel(
                f'<span style="color:{a_color}">■ {a_label}: {a_val}</span>'
                f'  <span style="color:{b_color}">■ {b_label}: {b_val}</span>'
            )
            legend.setObjectName("secondary")
            fl.addWidget(legend)
            return frame

        analytics_row.addWidget(_analytics_block(
            "Dofollow / Nofollow", df_count, nf_count,
            "Dofollow", "Nofollow", "#007AFF", "#ff5252"
        ))

        # Unique donor domains split by whether they have ANY dofollow link.
        # Sets are mutually exclusive: DF = at least one DF backlink,
        # NF = backlinks exist but none are dofollow.
        _all_bl_domains = {
            get_domain(donor_map.get(bl["donor_id"], ""))
            for bl in backlinks
            if donor_map.get(bl["donor_id"])
        }
        _df_domain_set = {
            get_domain(donor_map.get(bl["donor_id"], ""))
            for bl in backlinks
            if bl["rel_type"] == "dofollow" and donor_map.get(bl["donor_id"])
        }
        df_domains = len(_df_domain_set)
        nf_domains = len(_all_bl_domains - _df_domain_set)
        analytics_row.addWidget(_analytics_block(
            "Ссылающиеся домены: DF / NF", df_domains, nf_domains,
            "Dofollow", "Nofollow", "#007AFF", "#ff5252"
        ))
        analytics_row.addWidget(_analytics_block(
            "Типы анкоров", text_count, img_count,
            "Текст", "Картинка", "#42a5f5", "#ffa726"
        ))
        # Indexability (meta robots / X-Robots-Tag) differs per search engine,
        # so the engine switch lives inside this card — it affects nothing else
        # except the donors' Robots column and filter.
        idx_frame = QFrame()
        idx_frame.setObjectName("card")
        idx_frame.setToolTip(
            "Директивы индексации и сканирования (meta robots, X-Robots-Tag) "
            "могут различаться для каждой поисковой системы"
        )
        idx_fl = QVBoxLayout(idx_frame)
        idx_fl.setContentsMargins(16, 14, 16, 14)
        idx_fl.setSpacing(6)
        idx_head = QHBoxLayout()
        idx_head.setSpacing(4)
        idx_head.addWidget(_secondary("Индексируемость"))
        idx_head.addStretch()
        self._se_btns: dict[str, QPushButton] = {}
        for key, label in _SE_LABELS.items():
            btn = QPushButton(label)
            btn.setObjectName("segButton")
            btn.setCheckable(True)
            btn.setChecked(key == self._current_se)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._switch_se(k))
            self._se_btns[key] = btn
            idx_head.addWidget(btn)
        idx_fl.addLayout(idx_head)
        self._idx_nums_lbl = QLabel()
        self._idx_nums_lbl.setStyleSheet("font-size: 20px; font-weight: 700;")
        idx_fl.addWidget(self._idx_nums_lbl)
        self._idx_bar = _SegBar([], total=total_donors)
        idx_fl.addWidget(self._idx_bar)
        self._idx_legend_lbl = QLabel()
        self._idx_legend_lbl.setObjectName("secondary")
        idx_fl.addWidget(self._idx_legend_lbl)
        self._set_indexability(open_count, closed_count, total_donors)
        analytics_row.addWidget(idx_frame)

        self._root.addLayout(analytics_row)

        # ── Data Tabs ─────────────────────────────────────────────────────
        self._data_tabs = QTabWidget()
        self._data_tabs.addTab(
            self._build_domains_tab(backlinks, domains), "По доменам"
        )
        self._data_tabs.addTab(
            self._build_donors_tab(donors, backlinks), "Доноры"
        )
        self._data_tabs.addTab(
            self._build_backlinks_tab(backlinks, donor_map),
            f"Бэклинки ({len(backlinks)})",
        )
        self._data_tabs.addTab(
            self._build_anchors_tab(anchor_stats), "Топ анкоры"
        )
        self._data_tabs.setCurrentIndex(_active_tab)
        self._root.addWidget(self._data_tabs)

        # Restore search text lost when widgets were recreated during refresh
        if _donor_search_text and self._donor_search is not None:
            self._donor_search.setText(_donor_search_text)
        if _bl_search_text and self._bl_search is not None:
            self._bl_search.setText(_bl_search_text)
        _restore_view_state(self._donor_view, _donor_view_state)
        _restore_view_state(self._bl_table, _bl_view_state)

    # ── Domains tab ───────────────────────────────────────────────────────

    def _build_domains_tab(self, backlinks: list, target_domains: list) -> QWidget:
        """One row per target domain: found/not-found with backlink and donor counts."""
        rows_data = []
        for orig in target_domains:
            norm = normalize_domain(orig)
            matched = [
                bl for bl in backlinks
                if matches_target(bl["target_url"] or "", norm)
            ]
            donor_ids = {bl["donor_id"] for bl in matched}
            df = sum(1 for bl in matched if bl["rel_type"] == "dofollow")
            rows_data.append({
                "domain":    orig,
                "donors":    len(donor_ids),
                "backlinks": len(matched),
                "dofollow":  df,
                "nofollow":  len(matched) - df,
                "found":     len(matched) > 0,
            })

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)

        table = QTableWidget(len(rows_data), 5)
        table.setHorizontalHeaderLabels(
            ["Целевой домен", "Доноров", "Бэклинков", "Dofollow / Nofollow", "Статус"]
        )
        _hh = table.horizontalHeader()
        if _hh is not None:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            _hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        _style_table(table)
        table.setSortingEnabled(False)

        for i, row in enumerate(rows_data):
            table.setItem(i, 0, QTableWidgetItem(row["domain"]))

            donors_item = QTableWidgetItem()
            donors_item.setData(Qt.ItemDataRole.DisplayRole, row["donors"])
            table.setItem(i, 1, donors_item)

            bl_item = QTableWidgetItem()
            bl_item.setData(Qt.ItemDataRole.DisplayRole, row["backlinks"])
            table.setItem(i, 2, bl_item)

            df_nf_item = QTableWidgetItem(f"{row['dofollow']} / {row['nofollow']}")
            if row["backlinks"] > 0:
                if row["nofollow"] == 0:
                    df_nf_item.setForeground(QColor(REL_COLORS["dofollow"]))
                elif row["dofollow"] == 0:
                    df_nf_item.setForeground(QColor(REL_COLORS["nofollow"]))
                else:
                    df_nf_item.setForeground(QColor("#ffa726"))
            table.setItem(i, 3, df_nf_item)

            status_text = f"{STATUS_DOT} {'Найден' if row['found'] else 'Не найден'}"
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor("#00c853" if row["found"] else "#ff5252"))
            table.setItem(i, 4, status_item)

        table.setSortingEnabled(True)
        layout.addWidget(table)
        return widget

    # ── Donors tab ────────────────────────────────────────────────────────

    def _build_donors_tab(self, donors, backlinks) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        # Search + one compact drop-down per filter
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self._donor_search = QLineEdit()
        self._donor_search.setPlaceholderText("Поиск по донорам...")
        self._donor_search.textChanged.connect(self._refilter)
        filter_row.addWidget(self._donor_search, 1)

        self._filter_combos = {}
        for key, (label, options) in _DONOR_FILTERS.items():
            filter_row.addWidget(_secondary(label))
            combo = QComboBox()
            for value, text in options:
                combo.addItem(text, value)
            combo.setCurrentIndex(max(0, combo.findData(getattr(self, f"_donor_filter_{key}"))))
            combo.currentIndexChanged.connect(lambda _i, k=key: self._on_filter_changed(k))
            self._filter_combos[key] = combo
            filter_row.addWidget(combo)

        self._reset_filters_btn = QPushButton("Сбросить")
        self._reset_filters_btn.setObjectName("btnLink")
        self._reset_filters_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_filters_btn.clicked.connect(self._reset_donor_filters)
        filter_row.addWidget(self._reset_filters_btn)
        layout.addLayout(filter_row)

        # Model/view table: one widget-free row per donor stays fast at 100k rows.
        # Model and proxy belong to the view, so each refresh frees the old rows.
        self._donor_view = QTableView()
        self._donor_model = DonorTableModel(self._donor_view)
        self._donor_proxy = QSortFilterProxyModel(self._donor_view)
        self._donor_proxy.setSourceModel(self._donor_model)
        self._donor_proxy.setSortRole(_SORT_ROLE)
        self._donor_view.setModel(self._donor_proxy)
        _style_table(self._donor_view)
        _hh = self._donor_view.horizontalHeader()
        if _hh is not None:
            _hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            _hh.setSectionResizeMode(COL_D_URL, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(COL_D_LINKS, QHeaderView.ResizeMode.Stretch)
            for col in (COL_D_CODE, COL_D_ROBOTS, COL_D_GOOGLE, COL_D_INT, COL_D_EXT):
                _hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
            _hh.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)  # keep DB order
        self._donor_view.setSortingEnabled(True)
        self._donor_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._donor_view.customContextMenuRequested.connect(self._show_donor_context_menu)
        self._donor_view.doubleClicked.connect(self._on_donor_double_click)
        layout.addWidget(self._donor_view)

        self._donors_cache = donors
        self._backlinks_cache = backlinks
        self._populate_donor_table(donors, backlinks)

        return widget

    def _populate_donor_table(self, donors, backlinks):
        bl_by_donor: dict[int, list] = {}
        for bl in backlinks:
            bl_by_donor.setdefault(bl["donor_id"], []).append(bl)

        search = getattr(self, "_donor_search", None)
        search_text = search.text().lower() if search else ""
        se_col = _SE_INDEX_COL.get(self._current_se, "index_google")

        rows: list[tuple] = []
        for donor in donors:
            if search_text and search_text not in donor["url"].lower():
                continue
            if not matches_robots_filter(donor[se_col], self._donor_filter_index):
                continue
            if (
                self._donor_filter_status != "all"
                and donor["status"] != self._donor_filter_status
            ):
                continue
            if not matches_google_filter(_row_value(donor, "google_indexed"),
                                         self._donor_filter_google):
                continue
            donor_bls = bl_by_donor.get(donor["id"], [])
            if self._donor_filter_type != "all":
                donor_bls = [b for b in donor_bls if b["rel_type"] == self._donor_filter_type]
                if not donor_bls:
                    continue
            rows.append((donor, donor_bls))

        self._donor_model.set_rows(rows, se_col, _SE_LABELS.get(self._current_se, "Google"))
        self._update_reset_button()

    def _refilter(self):
        self._populate_donor_table(self._donors_cache, self._backlinks_cache)

    def _on_filter_changed(self, key: str) -> None:
        combo = self._filter_combos[key]
        setattr(self, f"_donor_filter_{key}", combo.currentData() or "all")
        self._refilter()

    def _reset_donor_filters(self) -> None:
        for key, combo in self._filter_combos.items():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
            setattr(self, f"_donor_filter_{key}", "all")
        self._refilter()

    def _update_reset_button(self) -> None:
        active = any(
            getattr(self, f"_donor_filter_{key}") != "all" for key in _DONOR_FILTERS
        )
        self._reset_filters_btn.setVisible(active)

    # ── Backlinks tab ─────────────────────────────────────────────────────

    def _build_backlinks_tab(self, backlinks: list, donor_map: dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        self._bl_search = QLineEdit()
        self._bl_search.setPlaceholderText("Поиск по URL, анкору...")
        self._bl_search.textChanged.connect(self._refilter_backlinks)
        layout.addWidget(self._bl_search)

        self._bl_table = QTableWidget(0, 5)
        self._bl_table.setHorizontalHeaderLabels(
            ["URL донора", "URL цели", "Анкор", "Тип", "Rel"]
        )
        _hh = self._bl_table.horizontalHeader()
        if _hh is not None:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        _style_table(self._bl_table)
        self._bl_table.setSortingEnabled(True)
        self._bl_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bl_table.customContextMenuRequested.connect(self._show_bl_context_menu)
        self._bl_table.cellDoubleClicked.connect(self._on_bl_double_click)
        layout.addWidget(self._bl_table)

        self._backlinks_cache = backlinks          # shared with donors tab
        self._bl_donor_map_cache = donor_map
        self._populate_backlinks_table(backlinks, donor_map)

        return widget

    def _populate_backlinks_table(self, backlinks: list, donor_map: dict) -> None:
        search_text = ""
        if self._bl_search is not None:
            search_text = self._bl_search.text().lower()

        self._bl_table.setSortingEnabled(False)
        self._bl_table.setRowCount(0)

        for bl in backlinks:
            donor_url = donor_map.get(bl["donor_id"], "")
            target_url = bl["target_url"] or ""
            anchor = bl["anchor_text"] or ""

            if search_text and not any(
                search_text in v.lower() for v in [donor_url, target_url, anchor]
            ):
                continue

            row = self._bl_table.rowCount()
            self._bl_table.insertRow(row)

            # Col 0: donor URL — plain item so sorting moves it with its row
            donor_item = QTableWidgetItem(donor_url)
            donor_item.setForeground(QColor("#42a5f5"))
            donor_item.setToolTip(donor_url)
            self._bl_table.setItem(row, 0, donor_item)

            # Col 1: target URL — same treatment
            target_item = QTableWidgetItem(target_url)
            target_item.setForeground(QColor("#42a5f5"))
            target_item.setToolTip(target_url)
            self._bl_table.setItem(row, 1, target_item)

            # Col 2: anchor text — context in tooltip; donor_url/target_url/context
            # stored in UserRole so context menu and double-click can retrieve them.
            anchor_item = QTableWidgetItem(anchor or "—")
            anchor_item.setToolTip(bl["context_html"] or "")
            anchor_item.setData(Qt.ItemDataRole.UserRole, {
                "donor_url":    donor_url,
                "target_url":   target_url,
                "context_html": bl["context_html"] or "",
            })
            self._bl_table.setItem(row, 2, anchor_item)

            # Col 3: anchor type
            self._bl_table.setItem(row, 3, QTableWidgetItem(bl["anchor_type"] or ""))

            # Col 4: rel type (coloured)
            rel = bl["rel_type"] or ""
            rel_item = QTableWidgetItem(rel)
            rel_item.setForeground(QColor(REL_COLORS.get(rel, "#888")))
            self._bl_table.setItem(row, 4, rel_item)

        self._bl_table.setSortingEnabled(True)

    def _refilter_backlinks(self) -> None:
        self._populate_backlinks_table(self._backlinks_cache, self._bl_donor_map_cache)

    # ── Anchors tab ───────────────────────────────────────────────────────

    def _build_anchors_tab(self, anchor_stats) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)

        table = QTableWidget(len(anchor_stats), 5)
        table.setHorizontalHeaderLabels(
            ["Анкор", "Ссылки", "Домены", "Dofollow / Nofollow", "%"]
        )
        _hh = table.horizontalHeader()
        if _hh is not None:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        _style_table(table)

        table.setSortingEnabled(False)   # must be off while inserting rows
        for i, row in enumerate(anchor_stats):
            anchor = row["anchor_text"] or "(пусто)"
            cnt: int    = row["cnt"]
            domains: int = row["domains"]
            df: int     = row["dofollow"]
            nf: int     = row["nofollow"]
            pct: float  = row["pct"]

            # Col 0: anchor text
            table.setItem(i, 0, QTableWidgetItem(anchor))

            # Col 1: ссылки — stored as int for numeric sort
            cnt_item = QTableWidgetItem()
            cnt_item.setData(Qt.ItemDataRole.DisplayRole, cnt)
            table.setItem(i, 1, cnt_item)

            # Col 2: уникальные доноры — stored as int for numeric sort
            dom_item = QTableWidgetItem()
            dom_item.setData(Qt.ItemDataRole.DisplayRole, domains)
            table.setItem(i, 2, dom_item)

            # Col 3: dofollow / nofollow — colour by mix
            df_nf_item = QTableWidgetItem(f"{df} / {nf}")
            if nf == 0:
                df_nf_item.setForeground(QColor(REL_COLORS["dofollow"]))   # all df → green
            elif df == 0:
                df_nf_item.setForeground(QColor(REL_COLORS["nofollow"]))   # all nf → red
            else:
                df_nf_item.setForeground(QColor("#ffa726"))                 # mixed → orange
            table.setItem(i, 3, df_nf_item)

            # Col 4: % — stored as float for numeric sort
            pct_item = QTableWidgetItem()
            pct_item.setData(Qt.ItemDataRole.DisplayRole, round(pct, 1))
            table.setItem(i, 4, pct_item)

        table.setSortingEnabled(True)    # re-enable after all rows are inserted
        layout.addWidget(table)
        return widget

    # ── Backlinks context menu & HTML dialog ──────────────────────────────

    def _get_bl_row_data(self, row: int) -> dict | None:
        item = self._bl_table.item(row, 2)
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _show_bl_context_menu(self, pos) -> None:
        row = self._bl_table.rowAt(pos.y())
        if row < 0:
            return
        data = self._get_bl_row_data(row)
        if not data:
            return

        menu = QMenu(self)
        menu.addAction(
            "Копировать URL донора",
            lambda: _clipboard_set(data["donor_url"]),
        )
        menu.addAction(
            "Копировать URL цели",
            lambda: _clipboard_set(data["target_url"]),
        )
        menu.addSeparator()
        menu.addAction(
            "Просмотр HTML-контекста",
            lambda: self._show_context_dialog(data["context_html"]),
        )
        vp = self._bl_table.viewport()
        if vp:
            menu.exec(vp.mapToGlobal(pos))

    def _on_bl_double_click(self, row: int, col: int) -> None:
        if col == 0:
            item = self._bl_table.item(row, 0)
            if item and item.text():
                QDesktopServices.openUrl(QUrl(item.text()))
            return
        if col == 1:
            item = self._bl_table.item(row, 1)
            if item and item.text():
                QDesktopServices.openUrl(QUrl(item.text()))
            return
        data = self._get_bl_row_data(row)
        if data and data["context_html"]:
            self._show_context_dialog(data["context_html"])

    def _show_context_dialog(self, context_html: str, title: str = "HTML-контекст ссылки") -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(400, 160)
        dialog.setMaximumSize(1100, 560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(context_html)
        editor.setFont(QFont("Courier New", 10))
        layout.addWidget(editor)

        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.adjustSize()
        dialog.exec()

    # ── Donors context menu ───────────────────────────────────────────────

    def _donor_at(self, proxy_index) -> "sqlite3.Row | None":
        if not proxy_index.isValid():
            return None
        return self._donor_model.donor(self._donor_proxy.mapToSource(proxy_index).row())

    def _on_donor_double_click(self, proxy_index) -> None:
        donor = self._donor_at(proxy_index)
        if donor is not None and proxy_index.column() == COL_D_URL:
            QDesktopServices.openUrl(QUrl(donor["url"]))

    def _show_donor_context_menu(self, pos) -> None:
        donor = self._donor_at(self._donor_view.indexAt(pos))
        if donor is None:
            return
        url = donor["url"]
        snippet = _row_value(donor, "html_snippet") or ""
        menu = QMenu(self)
        menu.addAction("Открыть в браузере", lambda: QDesktopServices.openUrl(QUrl(url)))
        menu.addAction("Копировать URL донора", lambda: _clipboard_set(url))
        if snippet:
            menu.addAction(
                "Просмотр HTML страницы",
                lambda s=snippet: self._show_context_dialog(s, "HTML страницы донора"),
            )
        vp = self._donor_view.viewport()
        if vp:
            menu.exec(vp.mapToGlobal(pos))

    # ── SE switching ──────────────────────────────────────────────────────

    def _switch_se(self, key: str):
        self._current_se = key
        for k, btn in self._se_btns.items():
            btn.setChecked(k == key)
        if hasattr(self, "_donor_model"):
            self._refilter()
        self._update_indexability_card()

    def _update_indexability_card(self) -> None:
        """Refresh the indexability card to match the selected search engine."""
        if not hasattr(self, "_idx_nums_lbl") or not self._donors_cache:
            return
        col = _SE_INDEX_COL.get(self._current_se, "index_google")
        open_count   = sum(1 for d in self._donors_cache if d[col] == "open")
        closed_count = sum(1 for d in self._donors_cache if d[col] == "closed")
        self._set_indexability(open_count, closed_count, len(self._donors_cache))

    def _set_indexability(self, open_count: int, closed_count: int, total: int) -> None:
        self._idx_nums_lbl.setText(f"{open_count} / {closed_count}")
        self._idx_bar.set_segments(
            [(open_count, "#007AFF"), (closed_count, "#ff5252")], total=total
        )
        self._idx_legend_lbl.setText(
            f'<span style="color:#007AFF">■ Открыто: {open_count}</span>'
            f'  <span style="color:#ff5252">■ Закрыто: {closed_count}</span>'
        )

    # ── Actions ───────────────────────────────────────────────────────────

    def _actions_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("Продолжить проверку",
                       lambda: self._app and self._app.continue_task(self._task_id))
        menu.addAction("Повторить проверку",
                       lambda: self._app and self._app.retry_task(self._task_id))
        menu.addAction("Повторить неудачные",
                       lambda: self._app and self._app.retry_failed_task(self._task_id))
        menu.addAction("Добавить ссылки",
                       lambda: self._app and self._app.edit_task(self._task_id))
        menu.addAction("Дублировать задание",
                       lambda: self._app and self._app.clone_task(self._task_id))
        menu.addAction("Экспортировать в .xlsx",
                       lambda: self._app and self._app.export_task(self._task_id))
        menu.addAction("Отправить на индексацию",
                       lambda: self._app and self._app.send_task_to_index(self._task_id))
        menu.addSeparator()
        menu.addAction("Удалить задание", self._confirm_delete)
        return menu

    def _show_actions_menu(self, btn: QPushButton):
        menu = self._actions_menu()
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _confirm_delete(self) -> None:
        if self._app and self._task_id:
            self._app.confirm_and_delete_task(self._task_id, self)

    def _go_back(self):
        if self._app:
            self._app.show_list()

    def refresh(self):
        if self._task_id:
            self.load_task(self._task_id)
