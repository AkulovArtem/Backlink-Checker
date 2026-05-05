from PyQt6.QtCore import Qt, QRectF, QPointF, QEvent
from PyQt6.QtGui import QPainter, QPen, QColor, QFont
from PyQt6.QtWidgets import QWidget, QSizePolicy


class LinkIcon(QWidget):
    """
    Two interlocked ovals — chain / link glyph drawn with QPainter.
    Height is fixed; width is ~1.72 × height so the rings look square.
    Colour is taken from the widget palette (tracks light/dark theme automatically).
    """

    def __init__(self, size: int = 22, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(size * 1.72), size)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self.update()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = float(self.width()), float(self.height())

        pen = QPen(self.palette().text().color())
        pen.setWidthF(H * 0.13)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        rw = W * 0.55       # ring width  — rings overlap by ~10 % of W
        rh = H * 0.72       # ring height
        ry = (H - rh) / 2   # vertical centre
        radius = rh / 2

        # left ring
        p.drawRoundedRect(QRectF(0, ry, rw, rh), radius, radius)
        # right ring
        p.drawRoundedRect(QRectF(W - rw, ry, rw, rh), radius, radius)

        p.end()


class OrDivider(QWidget):
    """
    Horizontal divider with centred «или» label between two hairlines.
    Line and text colours are derived from the palette — works in both themes.
    """

    _TEXT = "или"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self.update()
        super().changeEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = float(self.width()), float(self.height())
        cy = H / 2

        base = self.palette().text().color()
        line_color = QColor(base.red(), base.green(), base.blue(), 55)   # ~22 % opacity
        text_color = QColor(base.red(), base.green(), base.blue(), 120)  # ~47 % opacity

        # ── text metrics ──────────────────────────────────────────────────
        font = QFont(p.font())
        font.setPixelSize(11)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self._TEXT)
        th = fm.height()

        text_x = (W - tw) / 2
        text_y = cy + fm.ascent() - th / 2  # vertically centred

        gap = 10.0  # space between text and each line

        # ── hairlines ─────────────────────────────────────────────────────
        pen = QPen(line_color, 1.0)
        p.setPen(pen)
        p.drawLine(QPointF(0, cy), QPointF(text_x - gap, cy))
        p.drawLine(QPointF(text_x + tw + gap, cy), QPointF(W, cy))

        # ── label ─────────────────────────────────────────────────────────
        p.setPen(text_color)
        p.drawText(QPointF(text_x, text_y), self._TEXT)

        p.end()
