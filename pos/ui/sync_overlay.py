"""
«Ma'lumotlarni yangilash» oynasi.

Butun ekranni yopadigan oq sahifa (MoySklad Kassa'dagidek): o'rtada
yupqa aylanuvchi yoy va bosqich xabari — «Savdo nuqtasi sozlamalari
yuklanmoqda…», «Tovarlar ma'lumotnomasi yuklanmoqda…». Yakunda natija:
nechta narx yangilandi, nechta yangi, nechtasi o'chirildi. Tugagach
2 soniyadan so'ng o'zi yo'qoladi.

Hamma narsa QPainter bilan chizilgan — rasm fayli yo'q, EXE og'irlashmaydi.
Tarmoq ishi bu yerda YO'Q: oyna faqat fon oqimidan kelgan signallarga
qarab bosqichni almashtiradi. Shuning uchun kassa qotmaydi.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..i18n import tr
from . import theme as t



class SyncOverlay(QWidget):
    """Yangilanish jarayoni va natijasi."""

    STEPS = (
        "Savdo nuqtasi sozlamalari yuklanmoqda…",
        "Tovarlar ma'lumotnomasi yuklanmoqda…",
        "Kassa bazasi yangilanmoqda…",
    )

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()

        self._stage = 0          # 0..2 — joriy bosqich; 3 — tugadi
        self._angle = 0.0        # aylanuvchi indikator burchagi
        self._result: dict | None = None
        self._error = ""
        self._pulse = 0.0        # natija belgisining «paydo bo'lish» animatsiyasi
        self._started = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._finish_hide)

        # Ota oyna kattalashsa — parda ham
        parent.installEventFilter(self)

    # ------------------------------------------------------------ boshqaruv

    def start(self) -> None:
        self._stage = 0
        self._result = None
        self._error = ""
        self._pulse = 0.0
        self._hide_timer.stop()
        self._started = time.monotonic()
        self._fit()
        self.show()
        self.raise_()
        self._timer.start()

    def set_stage(self, stage: int) -> None:
        if self._result is None and not self._error:
            self._stage = max(0, min(int(stage), 2))
            self.update()

    # Juda tez tugasa (kesh, o'zgarish yo'q) bosqichlar «lip» etib o'tib
    # ketmasin — natija kamida shuncha vaqtdan keyin ko'rsatiladi.
    MIN_SHOW_MS = 900

    def _after_min(self, fn) -> None:
        left = self.MIN_SHOW_MS - int((time.monotonic() - self._started) * 1000)
        if left > 0:
            QTimer.singleShot(left, fn)
        else:
            fn()

    def finish(self, stats: dict) -> None:
        def show():
            self._stage = 3
            self._result = stats
            self._pulse = 0.0
            self.update()
            self._hide_timer.start(2400)
        self._after_min(show)

    def fail(self, message: str) -> None:
        def show():
            self._stage = 3
            self._error = message or tr("Noma'lum xato")
            self._pulse = 0.0
            self.update()
            # Xato bo'lsa uzoqroq turadi — kassir o'qib olsin
            self._hide_timer.start(5000)
        self._after_min(show)

    # ------------------------------------------------------------- ichki

    def _finish_hide(self) -> None:
        self._timer.stop()
        self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 5.0) % 360
        if self._stage == 3 and self._pulse < 1.0:
            self._pulse = min(1.0, self._pulse + 0.08)
        self.update()

    def _fit(self) -> None:
        p = self.parentWidget()
        if p:
            self.setGeometry(p.rect())

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._fit()
        return False

    def mousePressEvent(self, event):
        # Natija ko'rsatilayotganda bosilsa — darhol yopiladi
        if self._stage == 3:
            self._finish_hide()
        event.accept()

    # ----------------------------------------------------------- chizish
    #
    # Ko'rinish MoySklad Kassa'dagidek: butun ekran oq, o'rtada yupqa
    # aylanuvchi yoy va bitta xabar («Tovarlar ma'lumotnomasi
    # yuklanmoqda…»). Ortiqcha ramka, karta, ro'yxat yo'q — kassir
    # o'rganib qolgan sodda ko'rinish, faqat rang bizniki.

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), QColor(t.BG))

        cx = self.width() / 2
        cy = self.height() / 2 - 40

        if self._stage == 3:
            self._paint_result(painter, cx, cy)
        else:
            self._paint_progress(painter, cx, cy)
        painter.end()

    def _font(self, size: int, bold: bool = False) -> QFont:
        f = QFont()
        f.setPixelSize(size)
        f.setBold(bold)
        return f

    def _paint_progress(self, p: QPainter, cx: float, cy: float) -> None:
        r = 44
        ring = QRectF(cx - r, cy - r - 30, 2 * r, 2 * r)
        pen = QPen(QColor(t.ACCENT), 3.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        # Yoyning uzunligi «nafas oladi» — 60°..200° — jonli ko'rinsin
        import math
        span = 130 + 70 * math.sin(math.radians(self._angle * 2))
        p.drawArc(ring, int(-self._angle * 16), int(span * 16))

        p.setPen(QColor(t.INK_SOFT))
        p.setFont(self._font(22))
        p.drawText(
            QRectF(0, cy + r + 4, self.width(), 40),
            Qt.AlignCenter, tr(self.STEPS[self._stage]),
        )
        p.setPen(QColor(t.FAINT))
        p.setFont(self._font(13))
        p.drawText(
            QRectF(0, cy + r + 46, self.width(), 24),
            Qt.AlignCenter, tr("Narxlar, yangi va o'chirilgan tovarlar"),
        )

    def _paint_result(self, p: QPainter, cx: float, cy: float) -> None:
        ok = not self._error
        color = QColor(t.OK if ok else t.DANGER)

        scale = 0.6 + 0.4 * self._pulse
        r = 40 * scale
        c = cx, cy - 30
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(c[0] - r, c[1] - r, 2 * r, 2 * r))

        pen = QPen(QColor("#FFFFFF"), 5 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        if ok:
            p.drawPolyline([
                QPointF(c[0] - 16 * scale, c[1] + 1 * scale),
                QPointF(c[0] - 5 * scale, c[1] + 12 * scale),
                QPointF(c[0] + 17 * scale, c[1] - 12 * scale),
            ])
        else:
            p.drawLine(QPointF(c[0], c[1] - 16 * scale), QPointF(c[0], c[1] + 5 * scale))
            p.drawPoint(QPointF(c[0], c[1] + 15 * scale))

        p.setPen(QColor(t.INK))
        p.setFont(self._font(24, bold=True))
        title = tr("Katalog yangilandi") if ok else tr("Yangilab bo'lmadi")
        p.drawText(QRectF(0, cy + 28, self.width(), 40), Qt.AlignCenter, title)

        if not ok:
            p.setPen(QColor(t.INK_SOFT))
            p.setFont(self._font(15))
            p.drawText(
                QRectF(cx - 300, cy + 76, 600, 80),
                Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self._error,
            )
            p.setPen(QColor(t.FAINT))
            p.setFont(self._font(13))
            p.drawText(
                QRectF(0, cy + 160, self.width(), 24), Qt.AlignCenter,
                tr("Kassa avvalgi ma'lumotlar bilan ishlashda davom etadi"),
            )
            return

        st = self._result or {}
        rows = [
            (tr("Narx / nom yangilandi"), st.get("updated", 0)),
            (tr("Yangi tovar"), st.get("new", 0)),
            (tr("O'chirildi"), st.get("gone", 0)),
        ]
        total = sum(v for _, v in rows)

        y = cy + 84
        for label, value in rows:
            p.setFont(self._font(16))
            p.setPen(QColor(t.INK_SOFT))
            p.drawText(QRectF(cx - 170, y, 250, 28), Qt.AlignVCenter | Qt.AlignLeft, label)
            p.setFont(self._font(18, bold=True))
            p.setPen(QColor(t.INK if value else t.FAINT))
            p.drawText(QRectF(cx + 90, y, 80, 28), Qt.AlignVCenter | Qt.AlignRight, str(value))
            y += 34

        p.setPen(QColor(t.FAINT))
        p.setFont(self._font(13))
        note = (
            tr("Hammasi joyida — o'zgarish yo'q") if total == 0
            else tr("Yangi narxlar keyingi chekdan boshlab amal qiladi")
        )
        p.drawText(QRectF(0, y + 12, self.width(), 24), Qt.AlignCenter, note)
