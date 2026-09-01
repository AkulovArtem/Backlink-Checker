from math import cos, pi, sin

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PyQt6.QtCore import pyqtProperty  # type: ignore[attr-defined]
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractButton


class ThemeToggle(QAbstractButton):
    """
    Pill toggle: knob sits on the sun (left) in light mode, on the moon (right)
    in dark mode. Both icons are drawn with QPainter — no emoji, no image files.

    Anatomy
    -------
    W=62, H=30, pad=3, knob_d=24
      cx_sun  = pad + knob_d/2 = 15   ← knob centre when t=0 (light)
      cx_moon = W - pad - knob_d/2 = 47  ← knob centre when t=1 (dark)
    The moving knob covers whichever icon is "active".
    """

    def __init__(self, dark_mode: bool = True, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(dark_mode)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(62, 30)
        self.setToolTip("Переключить тему")
        self._pos = 1.0 if dark_mode else 0.0   # 0.0 = light, 1.0 = dark

        self._anim = QPropertyAnimation(self, b"toggle_pos", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._on_toggled)

    # ── animation property ─────────────────────────────────────────────────

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _get_toggle_pos(self) -> float:
        return self._pos

    def _set_toggle_pos(self, val: float) -> None:
        self._pos = val
        self.update()

    toggle_pos = pyqtProperty(float, _get_toggle_pos, _set_toggle_pos)

    # ── icon drawing ───────────────────────────────────────────────────────

    @staticmethod
    def _draw_sun(p: QPainter, cx: float, cy: float, R: float) -> None:
        """Filled disk + 8 short rounded rays."""
        color = QColor("#f5a020")
        # core disk
        core = R * 0.40
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(cx - core, cy - core, core * 2, core * 2))
        # rays
        pen = QPen(color)
        pen.setWidthF(max(1.0, R * 0.19))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(8):
            a = i * pi / 4
            p.drawLine(
                QPointF(cx + cos(a) * R * 0.58, cy + sin(a) * R * 0.58),
                QPointF(cx + cos(a) * R * 0.88, cy + sin(a) * R * 0.88),
            )
        p.setPen(Qt.PenStyle.NoPen)

    @staticmethod
    def _draw_moon(p: QPainter, cx: float, cy: float, R: float) -> None:
        """Crescent: outer circle minus offset inner circle (☽ shape)."""
        # outer full disk
        outer = QPainterPath()
        outer.addEllipse(QRectF(cx - R, cy - R, R * 2, R * 2))
        # cutout — shifted right and slightly up → exposes left arc as crescent
        cr = R * 0.80
        cut = QPainterPath()
        cut.addEllipse(QRectF(
            cx - cr + R * 0.48,
            cy - cr - R * 0.10,
            cr * 2,
            cr * 2,
        ))
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(outer.subtracted(cut), QColor("#6272a4"))

    # ── paint ──────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        W, H = float(self.width()), float(self.height())
        t = self._pos

        # --- track (interpolates light-grey → dark-navy) ---
        lc, dc = QColor("#d0d0d8"), QColor("#1e1e38")
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, W, H), H / 2, H / 2)
        p.fillPath(track, QColor(
            int(lc.red()   + t * (dc.red()   - lc.red())),
            int(lc.green() + t * (dc.green() - lc.green())),
            int(lc.blue()  + t * (dc.blue()  - lc.blue())),
        ))

        # --- icons at the two extreme knob positions ---
        pad = 3.0
        knob_d = H - 2 * pad          # 24 px
        R = H * 0.265                  # ≈ 8 px  — icon scale radius
        cx_sun  = pad + knob_d / 2     # 15 — knob centre when t=0
        cx_moon = W - pad - knob_d / 2 # 47 — knob centre when t=1

        self._draw_sun(p, cx_sun, H / 2, R)
        self._draw_moon(p, cx_moon, H / 2, R)

        # --- knob (drawn last → covers the "active" icon) ---
        knob_x = pad + t * (W - 2 * pad - knob_d)
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(knob_x, pad, knob_d, knob_d))

        p.end()
