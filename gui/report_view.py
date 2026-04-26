"""
Screen 3: Task report — summary cards, SE tabs, analytics, donors table, top anchors.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QTabWidget, QLineEdit, QProgressBar, QScrollArea, QMenu,
    QAbstractItemView, QMessageBox,
)

from db import database as db

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "pending":    "⏳ В очереди",
    "running":    "🔄 В процессе",
    "completed":  "✅ Завершено",
    "error":      "❌ Ошибка",
}

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


def _secondary(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("secondary")
    return lbl


def _badge(text: str, color: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background-color: {color}22; color: {color}; border: 1px solid {color};"
        "border-radius: 4px; padding: 1px 6px; font-size: 11px;"
    )
    return lbl


def _card(title: str, value: str, subtitle: str = "") -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setMinimumWidth(160)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    t = QLabel(title)
    t.setObjectName("secondary")
    layout.addWidget(t)
    v = QLabel(value)
    v.setStyleSheet("font-size: 18px; font-weight: bold;")
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
        self._donors_cache: list = []
        self._backlinks_cache: list = []
        self._bl_donor_map_cache: dict = {}
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
        self._task_id = task_id
        self._clear()

        task = db.get_task(task_id)
        if not task:
            return

        domains = json.loads(task["target_domains"])
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
                urlparse(donor_map.get(b["donor_id"], "")).netloc.lower().removeprefix("www.")
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

        df_count = sum(1 for bl in backlinks if bl["rel_type"] == "dofollow")
        nf_count = len(backlinks) - df_count
        text_count = sum(1 for bl in backlinks if bl["anchor_type"] == "text")
        img_count = len(backlinks) - text_count

        _idx_col = {
            "google": "index_google", "yandex": "index_yandex",
            "bing": "index_bing", "baidu": "index_baidu",
        }.get(self._current_se, "index_google")
        open_count = sum(1 for d in donors if d[_idx_col] == "open")
        closed_count = total_donors - open_count

        # ── Header ────────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        back_btn = QPushButton("← Назад")
        back_btn.clicked.connect(self._go_back)
        header_row.addWidget(back_btn)

        title_lbl = QLabel(task["name"].upper())
        title_lbl.setObjectName("heading")
        header_row.addWidget(title_lbl)
        header_row.addWidget(_badge("Проверка обратных ссылок", "#ff8f00"))

        status = task["status"]
        status_color = {"completed": "#00c853", "error": "#ff5252", "running": "#ffa726"}.get(status, "#888")
        header_row.addWidget(_badge(STATUS_LABELS.get(status, status), status_color))
        header_row.addStretch()

        actions_btn = QPushButton("Действия ▾")
        actions_btn.clicked.connect(lambda: self._show_actions_menu(actions_btn))
        header_row.addWidget(actions_btn)
        self._root.addLayout(header_row)

        # ── Summary cards ─────────────────────────────────────────────────
        cards_row = QHBoxLayout()
        try:
            dt = datetime.fromisoformat(task["created_at"])
            created_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            created_str = task["created_at"]

        cards_row.addWidget(_card("ДАТА СОЗДАНИЯ", created_str))
        cards_row.addWidget(_card("ССЫЛКИ-ДОНОРЫ", str(total_donors)))
        domains_short = ", ".join(domains[:2]) + (f" +{len(domains)-2}" if len(domains) > 2 else "")
        cards_row.addWidget(_card("ЦЕЛЕВЫЕ ДОМЕНЫ", domains_short))

        # Donor status card with progress bar
        status_card = QFrame()
        status_card.setObjectName("card")
        status_card.setMinimumWidth(200)
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(12, 10, 12, 10)
        sc_layout.addWidget(_secondary("СТАТУС ДОНОРОВ"))
        nums = QLabel(f"✅ {found}  🔍 {not_found}  ❌ {not_loaded}")
        nums.setStyleSheet("font-weight: bold;")
        sc_layout.addWidget(nums)
        bar = QProgressBar()
        bar.setMaximum(max(total_donors, 1))
        bar.setValue(found)
        bar.setTextVisible(False)
        sc_layout.addWidget(bar)

        cards_row.addWidget(status_card)
        self._root.addLayout(cards_row)

        # ── SE Tabs ───────────────────────────────────────────────────────
        se_row = QHBoxLayout()
        se_buttons = {
            "google": ("Google", "#00c853"),
            "bing":   ("Bing",   "#1976d2"),
            "yandex": ("Yandex", "#ef5350"),
            "baidu":  ("Baidu",  "#1565c0"),
        }
        self._se_btns: dict[str, QPushButton] = {}
        for key, (label, color) in se_buttons.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._current_se)
            btn.setStyleSheet(
                f"QPushButton:checked {{ background-color: {color}; color: #fff; border: none; }}"
            )
            btn.clicked.connect(lambda _, k=key: self._switch_se(k))
            self._se_btns[key] = btn
            se_row.addWidget(btn)
        se_row.addStretch()
        self._root.addLayout(se_row)

        hint = QLabel(
            "Директивы индексации и сканирования (meta robots, X-Robots-Tag) "
            "могут различаться для каждой поисковой системы"
        )
        hint.setObjectName("secondary")
        hint.setWordWrap(True)
        self._root.addWidget(hint)

        # ── Analytics cards ───────────────────────────────────────────────
        analytics_row = QHBoxLayout()

        def _analytics_block(title, a_val, b_val, a_label, b_label, a_color, b_color):
            frame = QFrame()
            frame.setObjectName("card")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(12, 10, 12, 10)
            fl.addWidget(_secondary(title))
            total = a_val + b_val
            nums_lbl = QLabel(f"{a_val} / {b_val}")
            nums_lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
            fl.addWidget(nums_lbl)
            bar2 = QProgressBar()
            bar2.setMaximum(max(total, 1))
            bar2.setValue(a_val)
            bar2.setTextVisible(False)
            bar2.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {a_color}; }}"
            )
            fl.addWidget(bar2)
            legend = QLabel(f"● {a_label}  ● {b_label}")
            legend.setObjectName("secondary")
            fl.addWidget(legend)
            return frame

        analytics_row.addWidget(_analytics_block(
            "DOFOLLOW / NOFOLLOW", df_count, nf_count,
            "dofollow", "nofollow", "#00c853", "#ff5252"
        ))

        # Unique domains DF/NF
        df_domains = len({
            urlparse(bl["target_url"]).netloc.lower()
            for bl in backlinks
            if bl["rel_type"] == "dofollow" and bl["target_url"]
        })
        nf_domains = len({
            urlparse(bl["target_url"]).netloc.lower()
            for bl in backlinks
            if bl["rel_type"] != "dofollow" and bl["target_url"]
        })
        analytics_row.addWidget(_analytics_block(
            "ССЫЛАЮЩИЕСЯ ДОМЕНЫ: DF / NF", df_domains, nf_domains,
            "dofollow", "nofollow", "#00c853", "#ff5252"
        ))
        analytics_row.addWidget(_analytics_block(
            "ТИПЫ АНКОРОВ", text_count, img_count,
            "Текст", "Картинка", "#42a5f5", "#ffa726"
        ))
        # ИНДЕКСИРУЕМОСТЬ — built manually so we can update it when SE tab switches
        idx_frame = QFrame()
        idx_frame.setObjectName("card")
        idx_fl = QVBoxLayout(idx_frame)
        idx_fl.setContentsMargins(12, 10, 12, 10)
        idx_fl.addWidget(_secondary("ИНДЕКСИРУЕМОСТЬ"))
        self._idx_nums_lbl = QLabel(f"{open_count} / {closed_count}")
        self._idx_nums_lbl.setStyleSheet("font-size: 16px; font-weight: bold;")
        idx_fl.addWidget(self._idx_nums_lbl)
        self._idx_bar = QProgressBar()
        self._idx_bar.setMaximum(max(total_donors, 1))
        self._idx_bar.setValue(open_count)
        self._idx_bar.setTextVisible(False)
        self._idx_bar.setStyleSheet(
            "QProgressBar::chunk { background-color: #00c853; }"
        )
        idx_fl.addWidget(self._idx_bar)
        idx_legend = QLabel("● Открыто  ● Закрыто")
        idx_legend.setObjectName("secondary")
        idx_fl.addWidget(idx_legend)
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
        self._root.addWidget(self._data_tabs)

    # ── Domains tab ───────────────────────────────────────────────────────

    def _build_domains_tab(self, backlinks: list, target_domains: list) -> QWidget:
        """One row per target domain: found/not-found with backlink and donor counts."""

        def _norm(d: str) -> str:
            d = d.lower().strip()
            if d.startswith("https://"):
                d = d[8:]
            elif d.startswith("http://"):
                d = d[7:]
            return d.removeprefix("www.").rstrip("/")

        def _link_domain(url: str) -> str:
            try:
                return urlparse(url).netloc.lower().removeprefix("www.")
            except Exception:
                return ""

        def _matches(link_domain: str, norm_target: str) -> bool:
            return link_domain == norm_target or link_domain.endswith("." + norm_target)

        rows_data = []
        for orig in target_domains:
            norm = _norm(orig)
            matched = [
                bl for bl in backlinks
                if _matches(_link_domain(bl["target_url"] or ""), norm)
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
            ["ЦЕЛЕВОЙ ДОМЕН", "ДОНОРОВ", "БЭКЛИНКОВ", "DOFOLLOW / NOFOLLOW", "СТАТУС"]
        )
        _hh = table.horizontalHeader()
        if _hh:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
            _hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        _vh = table.verticalHeader()
        if _vh:
            _vh.setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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

            status_text = "✅ Найден" if row["found"] else "❌ Не найден"
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

        # Search
        self._donor_search = QLineEdit()
        self._donor_search.setPlaceholderText("Поиск по донорам...")
        self._donor_search.textChanged.connect(self._refilter)
        layout.addWidget(self._donor_search)

        # Filters row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("ТИП:"))
        for key, label in [("all","Все"),("dofollow","Dofollow"),("nofollow","Nofollow"),
                            ("ugc","UGC"),("sponsored","Sponsored")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._donor_filter_type)
            btn.clicked.connect(lambda _, k=key: self._set_type_filter(k))
            filter_row.addWidget(btn)

        filter_row.addSpacing(16)
        filter_row.addWidget(QLabel("ИНДЕКС:"))
        for key, label in [("all","Все"),("open","Откр."),("closed","Закр.")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._donor_filter_index)
            btn.clicked.connect(lambda _, k=key: self._set_index_filter(k))
            filter_row.addWidget(btn)

        filter_row.addSpacing(16)
        filter_row.addWidget(QLabel("СТАТУС:"))
        for key, label in [("all","Все"),("found","Найдено"),("not_found","Не найдено"),
                            ("not_loaded","Не загружено")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._donor_filter_status)
            btn.clicked.connect(lambda _, k=key: self._set_status_filter(k))
            filter_row.addWidget(btn)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Table
        self._donor_table = QTableWidget(0, 5)
        self._donor_table.setHorizontalHeaderLabels(
            ["ССЫЛКА-ДОНОР", "В ИНДЕКСЕ", "ССЫЛКИ НА ЦЕЛЕВОЙ ДОМЕН", "ВН. ССЫЛОК", "ВНШ. ССЫЛОК"]
        )
        _hh = self._donor_table.horizontalHeader()
        if _hh:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._donor_table.setAlternatingRowColors(True)
        self._donor_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        _vh = self._donor_table.verticalHeader()
        if _vh:
            _vh.setVisible(False)
        layout.addWidget(self._donor_table)

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

        self._donor_table.setRowCount(0)
        for donor in donors:
            # Apply filters
            if search_text and search_text not in donor["url"].lower():
                continue
            if self._donor_filter_index != "all":
                _se_col_filter = {
                    "google": "index_google", "yandex": "index_yandex",
                    "bing": "index_bing", "baidu": "index_baidu",
                }.get(self._current_se, "index_google")
                if donor[_se_col_filter] != self._donor_filter_index:
                    continue
            if self._donor_filter_status != "all":
                if donor["status"] != self._donor_filter_status:
                    continue

            donor_bls = bl_by_donor.get(donor["id"], [])

            if self._donor_filter_type != "all":
                donor_bls = [b for b in donor_bls if b["rel_type"] == self._donor_filter_type]
                if not donor_bls:
                    continue

            row = self._donor_table.rowCount()
            self._donor_table.insertRow(row)

            # Column 0: URL + status
            status_code = donor["http_status"]
            color = HTTP_COLORS.get((status_code or 0) // 100, "#888") if status_code else "#888"
            status_str = str(status_code) if status_code else donor["error_code"] or "—"
            url_cell = QLabel(f'<b style="color:{color}">{status_str}</b>  '
                              f'<a href="{donor["url"]}">{donor["url"]}</a>')
            url_cell.setOpenExternalLinks(True)
            url_cell.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            url_cell.setWordWrap(True)
            self._donor_table.setCellWidget(row, 0, url_cell)

            # Column 1: indexability — use active SE tab
            _se_col = {
                "google": "index_google", "yandex": "index_yandex",
                "bing": "index_bing", "baidu": "index_baidu",
            }.get(self._current_se, "index_google")
            idx_val = donor[_se_col]  # None = not yet checked
            if idx_val == "open":
                idx_color = "#00c853"
                idx_text = "Открыто"
            elif idx_val == "closed":
                idx_color = "#ff5252"
                idx_text = "Закрыто"
            else:
                idx_color = "#888888"
                idx_text = "—"
            idx_item = QTableWidgetItem(idx_text)
            idx_item.setForeground(QColor(idx_color))  # noqa: F821
            self._donor_table.setItem(row, 1, idx_item)

            # Column 2: backlinks found
            if donor_bls:
                bls_text = "\n".join(
                    f"{bl['target_url']}  [{bl['rel_type']}]  «{bl['anchor_text'] or '—'}»"
                    for bl in donor_bls
                )
            else:
                bls_text = "—"
            bl_item = QTableWidgetItem(bls_text)
            bl_item.setToolTip(bls_text)
            self._donor_table.setItem(row, 2, bl_item)

            # Column 3-4: link counts
            self._donor_table.setItem(row, 3, QTableWidgetItem(str(donor["internal_links"] or 0)))
            self._donor_table.setItem(row, 4, QTableWidgetItem(str(donor["external_links"] or 0)))

            self._donor_table.setRowHeight(row, max(60, 24 * max(len(donor_bls), 1)))

    def _refilter(self):
        self._populate_donor_table(self._donors_cache, self._backlinks_cache)

    def _set_type_filter(self, key):
        self._donor_filter_type = key
        self._refilter()

    def _set_index_filter(self, key):
        self._donor_filter_index = key
        self._refilter()

    def _set_status_filter(self, key):
        self._donor_filter_status = key
        self._refilter()

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
            ["URL ДОНОРА", "URL ЦЕЛИ", "АНКОР", "ТИП", "REL"]
        )
        _hh = self._bl_table.horizontalHeader()
        if _hh:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        _vh = self._bl_table.verticalHeader()
        if _vh:
            _vh.setVisible(False)
        self._bl_table.setAlternatingRowColors(True)
        self._bl_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._bl_table.setSortingEnabled(True)
        layout.addWidget(self._bl_table)

        self._backlinks_cache = backlinks          # shared with donors tab
        self._bl_donor_map_cache = donor_map
        self._populate_backlinks_table(backlinks, donor_map)

        return widget

    def _populate_backlinks_table(self, backlinks: list, donor_map: dict) -> None:
        search_text = ""
        if hasattr(self, "_bl_search"):
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

            # Col 0: donor URL (clickable)
            donor_lbl = QLabel(f'<a href="{donor_url}">{donor_url}</a>')
            donor_lbl.setOpenExternalLinks(True)
            donor_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            donor_lbl.setContentsMargins(4, 2, 4, 2)
            self._bl_table.setCellWidget(row, 0, donor_lbl)

            # Col 1: target URL (clickable)
            target_lbl = QLabel(f'<a href="{target_url}">{target_url}</a>')
            target_lbl.setOpenExternalLinks(True)
            target_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            target_lbl.setContentsMargins(4, 2, 4, 2)
            self._bl_table.setCellWidget(row, 1, target_lbl)

            # Col 2: anchor text — context shown in tooltip
            anchor_item = QTableWidgetItem(anchor or "—")
            anchor_item.setToolTip(bl["context_html"] or "")
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
            ["АНКОР", "ССЫЛКИ", "ДОМЕНЫ", "DOFOLLOW / NOFOLLOW", "%"]
        )
        _hh = table.horizontalHeader()
        if _hh:
            _hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            _hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        _vh = table.verticalHeader()
        if _vh:
            _vh.setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

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

    # ── SE switching ──────────────────────────────────────────────────────

    def _switch_se(self, key: str):
        self._current_se = key
        for k, btn in self._se_btns.items():
            btn.setChecked(k == key)
        if hasattr(self, "_donor_table"):
            self._refilter()
        self._update_indexability_card()

    def _update_indexability_card(self) -> None:
        """Refresh the ИНДЕКСИРУЕМОСТЬ card to match the active SE tab."""
        if not hasattr(self, "_idx_nums_lbl") or not self._donors_cache:
            return
        col = {
            "google": "index_google", "yandex": "index_yandex",
            "bing": "index_bing", "baidu": "index_baidu",
        }.get(self._current_se, "index_google")
        open_count = sum(1 for d in self._donors_cache if d[col] == "open")
        closed_count = len(self._donors_cache) - open_count
        self._idx_nums_lbl.setText(f"{open_count} / {closed_count}")
        self._idx_bar.setMaximum(max(len(self._donors_cache), 1))
        self._idx_bar.setValue(open_count)

    # ── Actions ───────────────────────────────────────────────────────────

    def _show_actions_menu(self, btn: QPushButton):
        menu = QMenu(self)
        menu.addAction("Повторить проверку",
                       lambda: self._app and self._app.retry_task(self._task_id))
        menu.addAction("Экспортировать в .xlsx",
                       lambda: self._app and self._app.export_task(self._task_id))
        menu.addSeparator()
        menu.addAction("Удалить задание", self._confirm_delete)
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _confirm_delete(self) -> None:
        if not self._app or not self._task_id:
            return
        task = db.get_task(self._task_id)
        name = task["name"] if task else f"#{self._task_id}"
        reply = QMessageBox.question(
            self,
            "Удалить задание",
            f"Удалить задание «{name}»?\n\nВсе доноры и бэклинки будут удалены безвозвратно.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._app.delete_task(self._task_id)

    def _go_back(self):
        if self._app:
            self._app.show_list()

    def refresh(self):
        if self._task_id:
            self.load_task(self._task_id)
