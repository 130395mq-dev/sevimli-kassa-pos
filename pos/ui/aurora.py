"""
«Shimol yog'dusi» (aurora) fon — Sevimli Kassa tun rejimi.

To'q grafit fon ustida yumshoq zumrad yog'du dog'lari SEKIN suzib yuradi.
Keskin chiziq, miltillash, tez harakat YO'Q — kassir kun bo'yi qaraydi,
ko'z charchamasin.

KUCHSIZ KASSALAR uchun:
  * Aurora past rezolyutsiyali buferda chiziladi (masalan 1/3 o'lcham) va
    keyin kattalashtiriladi. Radial gradient yumshoq — kichraytirilса ham
    farqi bilinmaydi, lekin ancha arzon.
  * FPS past (~18) — aurora sekin, ko'p kadr shart emas.
  * Oyna yashirilса yoki kichraytirilса — taymer TO'XTAYDI (resurs sarflamaydi).
  * `animated=False` — taymer umuman yo'q, chiroyli STATIK fon qoladi.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from . import theme as t


def _c(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def paint_glow(painter: QPainter, cx: float, cy: float, radius: float,
               color: str, alpha: int = 120) -> None:
    """Bitta yumshoq radial yog'du dog'i. Logo halqasi ham shundan foydalanadi."""
    grad = QRadialGradient(QPointF(cx, cy), radius)
    grad.setColorAt(0.0, _c(color, alpha))
    grad.setColorAt(0.55, _c(color, alpha // 3))
    grad.setColorAt(1.0, _c(color, 0))
    painter.setBrush(grad)
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPointF(cx, cy), radius, radius)


class AuroraWidget(QWidget):
    """To'q grafit fon + sekin suzuvchi zumrad yog'du. UI shu widget ustiga
    joylashadi (u markaziy widget bo'ladi). Layout/joylashuv o'zgarmaydi —
    faqat orqa fon."""

    #: Yog'du dog'lari: (rang, o'lcham ulushi, x-markaz, y-markaz, tezlik, faza)
    _BLOBS = [
        (t.AURORA_1, 0.62, 0.12, 0.16, 0.55, 0.0),
        (t.AURORA_2, 0.70, 0.85, 0.22, 0.42, 1.7),
        (t.AURORA_1, 0.55, 0.70, 0.92, 0.50, 3.1),
        (t.AURORA_3, 0.48, 0.30, 0.85, 0.38, 4.6),
    ]
    _SCALE = 3          # bufer necha marta kichik (1/3)
    _FPS_MS = 55        # ~18 kadr/soniya — sekin auroraga yetarli

    def __init__(self, parent=None, animated: bool = True):
        super().__init__(parent)
        self._animated = animated
        self._phase = 0.0
        self._buf: QImage | None = None
        self._buf_key = (0, 0)
        # UI ustiga chiziladi — bu widget faqat fon.
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._timer = QTimer(self)
        self._timer.setInterval(self._FPS_MS)
        self._timer.timeout.connect(self._tick)

    # ---- resurs: yashirilganda/kichraytirilganda to'xtat -----------------

    def _should_run(self) -> bool:
        w = self.window()
        minimized = bool(w and w.isMinimized())
        return self._animated and self.isVisible() and not minimized

    def _sync_timer(self) -> None:
        if self._should_run():
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_timer()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._timer.stop()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange:
            self._sync_timer()

    def _tick(self) -> None:
        # Juda sekin: to'liq aylanish ~2 daqiqa.
        self._phase += 0.010
        self._render_buffer()
        self.update()

    # ---- chizish ---------------------------------------------------------

    def _render_buffer(self) -> None:
        bw = max(1, self.width() // self._SCALE)
        bh = max(1, self.height() // self._SCALE)
        if self._buf is None or self._buf_key != (bw, bh):
            self._buf = QImage(bw, bh, QImage.Format_RGB32)
            self._buf_key = (bw, bh)

        img = self._buf
        img.fill(QColor(t.BG_BASE))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, True)
        diag = math.hypot(bw, bh)
        for color, size, bx, by, speed, ph in self._BLOBS:
            # Markaz sekin aylanadi (kichik radiusда), keskinlik yo'q.
            ang = self._phase * speed + ph
            dx = math.cos(ang) * 0.06
            dy = math.sin(ang * 0.8) * 0.05
            cx = (bx + dx) * bw
            cy = (by + dy) * bh
            paint_glow(p, cx, cy, size * diag * 0.5, color, alpha=70)
        p.end()

    def paintEvent(self, _e) -> None:
        if self._buf is None or self._buf_key != (max(1, self.width() // self._SCALE),
                                                   max(1, self.height() // self._SCALE)):
            self._render_buffer()
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(self.rect(), self._buf)
        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._render_buffer()
        if not self._animated:
            self.update()
