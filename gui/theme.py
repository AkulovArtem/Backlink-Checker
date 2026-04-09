DARK_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}

QFrame#card {
    background-color: #1e1e3a;
    border: 1px solid #2a2a4a;
    border-radius: 8px;
}

QPushButton {
    background-color: #2a2a4a;
    color: #e0e0e0;
    border: 1px solid #3a3a5a;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background-color: #3a3a5a; }
QPushButton:pressed { background-color: #1a1a3a; }

QPushButton#btnCreate {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00c853, stop:1 #00bcd4);
    color: #fff;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
}
QPushButton#btnCreate:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00e676, stop:1 #00e5ff);
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit {
    background-color: #16213e;
    color: #e0e0e0;
    border: 1px solid #2a2a4a;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #00c853;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus { border: 1px solid #00c853; }

QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #1e1e3a;
    color: #e0e0e0;
    selection-background-color: #2a2a6a;
}

QTableWidget, QTableView {
    background-color: #16213e;
    color: #e0e0e0;
    gridline-color: #2a2a4a;
    border: none;
    alternate-background-color: #1a1a36;
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: #2a2a6a;
}
QHeaderView::section {
    background-color: #1e1e3a;
    color: #888;
    border: none;
    border-bottom: 1px solid #2a2a4a;
    padding: 6px 8px;
    font-weight: bold;
    text-transform: uppercase;
    font-size: 11px;
}

QScrollBar:vertical {
    background: #1a1a2e;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2a2a4a;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #1a1a2e;
    height: 8px;
}
QScrollBar::handle:horizontal {
    background: #2a2a4a;
    border-radius: 4px;
    min-width: 20px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QTabBar::tab {
    background: #1e1e3a;
    color: #888;
    border: 1px solid #2a2a4a;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 6px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #2a2a6a; color: #e0e0e0; }
QTabWidget::pane { border: 1px solid #2a2a4a; }

QProgressBar {
    background-color: #2a2a4a;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk { background-color: #00c853; border-radius: 4px; }

QLabel#heading {
    font-size: 20px;
    font-weight: bold;
    color: #e0e0e0;
}
QLabel#secondary { color: #888; font-size: 12px; }

QMenu {
    background-color: #1e1e3a;
    color: #e0e0e0;
    border: 1px solid #2a2a4a;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item:selected { background-color: #2a2a6a; border-radius: 4px; }
"""

LIGHT_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #f5f5f5;
    color: #212121;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}

QFrame#card {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
    border-radius: 8px;
}

QPushButton {
    background-color: #e0e0e0;
    color: #212121;
    border: 1px solid #bdbdbd;
    border-radius: 6px;
    padding: 6px 14px;
}
QPushButton:hover { background-color: #bdbdbd; }
QPushButton:pressed { background-color: #9e9e9e; }

QPushButton#btnCreate {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00c853, stop:1 #00bcd4);
    color: #fff;
    font-weight: bold;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
}
QPushButton#btnCreate:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00e676, stop:1 #00e5ff);
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox, QDateEdit {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #bdbdbd;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #00c853;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QComboBox:focus { border: 1px solid #00c853; }

QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #212121;
    selection-background-color: #e0f7fa;
}

QTableWidget, QTableView {
    background-color: #ffffff;
    color: #212121;
    gridline-color: #e0e0e0;
    border: none;
    alternate-background-color: #fafafa;
}
QTableWidget::item:selected, QTableView::item:selected {
    background-color: #e0f7fa;
}
QHeaderView::section {
    background-color: #f5f5f5;
    color: #757575;
    border: none;
    border-bottom: 1px solid #e0e0e0;
    padding: 6px 8px;
    font-weight: bold;
    text-transform: uppercase;
    font-size: 11px;
}

QScrollBar:vertical { background: #f5f5f5; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #bdbdbd; border-radius: 4px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #f5f5f5; height: 8px; }
QScrollBar::handle:horizontal { background: #bdbdbd; border-radius: 4px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QTabBar::tab {
    background: #e0e0e0;
    color: #757575;
    border: 1px solid #bdbdbd;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 6px 16px;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #ffffff; color: #212121; }
QTabWidget::pane { border: 1px solid #e0e0e0; }

QProgressBar {
    background-color: #e0e0e0;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
}
QProgressBar::chunk { background-color: #00c853; border-radius: 4px; }

QLabel#heading { font-size: 20px; font-weight: bold; color: #212121; }
QLabel#secondary { color: #757575; font-size: 12px; }

QMenu {
    background-color: #ffffff;
    color: #212121;
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item:selected { background-color: #e0f7fa; border-radius: 4px; }
"""
