ACCENT = "#007AFF"


def _make_qss(
    bg, surface, input_bg, border, border_ctrl, text, muted,
    btn_bg, btn_border, btn_hover, btn_pressed,
    selection, scroll_bg, scroll_handle, alt_row,
    tab_bg, tab_text, tab_sel_bg, tab_sel_text,
) -> str:
    return f"""
QMainWindow, QDialog, QWidget {{
    background-color: {bg};
    color: {text};
    font-size: 13px;
}}

/* Labels inherit the card surface instead of painting the page background. */
QFrame#card QLabel, QFrame#footerBar QLabel {{ background: transparent; }}

QFrame#footerBar {{
    background-color: {surface};
    border-top: 1px solid {border};
}}

QFrame#card {{
    background-color: {surface};
    border: 1px solid {border};
    border-radius: 12px;
}}

QPushButton {{
    background-color: {btn_bg};
    color: {text};
    border: 1px solid {btn_border};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background-color: {btn_hover}; }}
QPushButton:pressed {{ background-color: {btn_pressed}; }}
QPushButton:checked {{ background-color: {ACCENT}; color: #fff; border: none; }}

QPushButton#btnCreate {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #34AADC, stop:1 #007AFF);
    color: #fff;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
}}
QPushButton#btnCreate:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #47B7E8, stop:1 #1C8FFF);
}}

QPushButton#btnDanger {{
    background-color: transparent;
    color: #e53935;
    border: 1px solid #e53935;
}}
QPushButton#btnDanger:hover {{ background-color: rgba(229, 57, 53, 30); }}

QPushButton#btnLink {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 4px 0;
    text-align: left;
    font-weight: bold;
}}
QPushButton#btnLink:hover {{ text-decoration: underline; }}

QPushButton#segButton {{
    padding: 2px 8px;
    font-size: 11px;
    border-radius: 4px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {border_ctrl};
    background-color: {input_bg};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background-color: {input_bg};
    color: {text};
    border: 1px solid {border_ctrl};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}

QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background-color: {surface};
    color: {text};
    selection-background-color: {selection};
    selection-color: #ffffff;
}}

QTableWidget, QTableView {{
    background-color: {input_bg};
    color: {text};
    gridline-color: {border};
    border: none;
    alternate-background-color: {alt_row};
}}
QTableWidget::item:selected, QTableView::item:selected {{
    background-color: {selection};
    color: #ffffff;
}}
QHeaderView::section {{
    background-color: {surface};
    color: {muted};
    border: none;
    border-bottom: 1px solid {border};
    padding: 6px 8px;
    font-weight: bold;
    font-size: 11px;
}}

QScrollBar:vertical {{
    background: {scroll_bg};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {scroll_handle};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: {scroll_bg};
    height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: {scroll_handle};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QTabBar::tab {{
    background: {tab_bg};
    color: {tab_text};
    border: 1px solid {border_ctrl};
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 6px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {tab_sel_bg}; color: {tab_sel_text}; }}
QTabWidget::pane {{ border: 1px solid {border}; }}
QTabWidget::tab-bar {{ alignment: left; }}

QProgressBar {{
    background-color: {btn_bg};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 4px; }}

QLabel#heading {{
    font-size: 20px;
    font-weight: bold;
    color: {text};
}}
QLabel#secondary {{ color: {muted}; font-size: 12px; }}

QMenu {{
    background-color: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item:selected {{ background-color: {selection}; color: #ffffff; border-radius: 4px; }}

/* ── QDateEdit — iOS style (standalone, not in group) ───────────────── */
QDateEdit {{
    background-color: {input_bg};
    color: {text};
    border: 1px solid {border_ctrl};
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 108px;
    selection-background-color: #007AFF;
    selection-color: #ffffff;
}}
QDateEdit:focus {{
    border: 1.5px solid #007AFF;
}}
QDateEdit::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    border-left: 1px solid {border_ctrl};
    border-radius: 0 5px 5px 0;
    background: rgba(0, 122, 255, 18);
}}
QDateEdit::down-arrow {{ image: none; }}

/* ── QCalendarWidget — iOS style ────────────────────────────────────── */
QCalendarWidget {{
    background-color: {surface};
    border: 1px solid {border};
}}
QCalendarWidget QWidget#qt_calendar_navigationbar {{
    background-color: {surface};
    padding: 8px 6px;
}}
QCalendarWidget QToolButton {{
    color: #007AFF;
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: bold;
    font-size: 13px;
    min-width: 30px;
    min-height: 28px;
}}
QCalendarWidget QToolButton:hover {{
    background: rgba(0, 122, 255, 28);
}}
QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
QCalendarWidget QSpinBox {{
    color: {text};
    background: transparent;
    border: none;
    font-weight: bold;
    font-size: 13px;
    selection-background-color: #007AFF;
    selection-color: #fff;
}}
QCalendarWidget QSpinBox::up-button,
QCalendarWidget QSpinBox::down-button {{ width: 0; height: 0; }}
QCalendarWidget QAbstractItemView {{
    background-color: {surface};
    color: {text};
    selection-background-color: #007AFF;
    selection-color: #fff;
    alternate-background-color: {surface};
    border: none;
    outline: 0;
}}
QCalendarWidget QAbstractItemView:disabled {{
    color: {muted};
}}
"""


DARK_QSS = _make_qss(
    bg="#1a1a2e",
    surface="#1e1e3a",
    input_bg="#16213e",
    border="#2a2a4a",
    border_ctrl="#2a2a4a",
    text="#e0e0e0",
    muted="#888",
    btn_bg="#2a2a4a",
    btn_border="#3a3a5a",
    btn_hover="#3a3a5a",
    btn_pressed="#1a1a3a",
    selection="#2a2a6a",
    scroll_bg="#1a1a2e",
    scroll_handle="#2a2a4a",
    alt_row="#1a1a36",
    tab_bg="#1e1e3a",
    tab_text="#888",
    tab_sel_bg="#2a2a6a",
    tab_sel_text="#e0e0e0",
)

LIGHT_QSS = _make_qss(
    bg="#f5f5f5",
    surface="#ffffff",
    input_bg="#ffffff",
    border="#e0e0e0",
    border_ctrl="#bdbdbd",
    text="#212121",
    muted="#757575",
    btn_bg="#e0e0e0",
    btn_border="#bdbdbd",
    btn_hover="#bdbdbd",
    btn_pressed="#9e9e9e",
    selection="#007AFF",
    scroll_bg="#f5f5f5",
    scroll_handle="#bdbdbd",
    alt_row="#fafafa",
    tab_bg="#e0e0e0",
    tab_text="#757575",
    tab_sel_bg="#ffffff",
    tab_sel_text="#212121",
)


def make_palette(dark: bool):
    """QPalette matching the stylesheet: custom-painted widgets (_SegBar, the
    task-list progress cell) and rich-text links read colours from it."""
    from PyQt6.QtGui import QColor, QPalette

    colors = {
        QPalette.ColorRole.Window: "#1a1a2e" if dark else "#f5f5f5",
        QPalette.ColorRole.WindowText: "#e0e0e0" if dark else "#212121",
        QPalette.ColorRole.Base: "#16213e" if dark else "#ffffff",
        QPalette.ColorRole.AlternateBase: "#2a2a4a" if dark else "#e6e6ea",
        QPalette.ColorRole.Text: "#e0e0e0" if dark else "#212121",
        QPalette.ColorRole.Button: "#2a2a4a" if dark else "#e0e0e0",
        QPalette.ColorRole.ButtonText: "#e0e0e0" if dark else "#212121",
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#5aa9ff" if dark else ACCENT,
        QPalette.ColorRole.LinkVisited: "#5aa9ff" if dark else ACCENT,
        QPalette.ColorRole.PlaceholderText: "#888888" if dark else "#9e9e9e",
    }
    palette = QPalette()
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    return palette
