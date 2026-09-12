"""Aloqa chiroqlari — kassaning pastki qatoridagi dumaloq belgilar.

Ikki chiroq:
    Server   — kassa ↔ panel (server). Kassa o'zi biladi: 15 soniyalik
               «tirikman» so'rovi o'tdimi.
    MoySklad — server ↔ MoySklad. Kassa MoySklad'ga o'zi ulanmaydi,
               holatni serverdan (`hello` javobidagi `links`) oladi.

Ranglar va yonib-o'chish:
    yashil  — yaxshi, tinch turadi
    sariq   — kechikish / navbat (sekin yonib-o'chadi)
    qizil   — aloqa yo'q yoki xato (tez yonib-o'chadi)
    kulrang — noma'lum (masalan server o'chiq — MoySklad holatini
              so'rab bo'lmaydi)

Rasm fayli yo'q — belgi QPainter bilan chiziladi. Yonib-o'chish bitta
QTimer bilan (250 ms): qizil har 500 ms, sariq har 1 s da almashadi.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..i18n import tr
from . import theme as t

COLORS = {
    "ok": t.OK,
    "warn": t.WARN,
    "bad": t.DANGER,
    "unknown": t.FAINT,
}

# Tick 250 ms. Necha tickda bir «o'chadi»: qizil — 2 (500 ms), sariq — 4.
BLINK_EVERY = {"bad": 2, "warn": 4}


class _Dot(QWidget):
    """Bitta dumaloq chiroq. `state` — ok/warn/bad/unknown."""

    SIZE = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "unknown"
        self.lit = True
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(COLORS.get(self.state, t.FAINT))
        # O'chgan fazada rang butunlay yo'qolmaydi — xira turadi, shunda
        # qizil «yo'q bo'lib qoldi» emas, «yonib-o'chyapti» deb o'qiladi.
        if not self.lit:
            color.setAlphaF(0.28)
        p.setPen(Qt.NoPen)
        # Yashil atrofida yumshoq halqa — «tirik» ko'rinsin
        if self.state == "ok" and self.lit:
            halo = QColor(color)
            halo.setAlphaF(0.22)
            p.setBrush(halo)
            p.drawEllipse(QRectF(0, 0, self.SIZE, self.SIZE))
        p.setBrush(color)
        inset = 2.5
        p.drawEllipse(QRectF(inset, inset, self.SIZE - 2 * inset, self.SIZE - 2 * inset))
        p.end()


class LinkLights(QWidget):
    """Pastki qatordagi «Server» va «MoySklad» chiroqlari."""

    ORDER = ("server", "moysklad")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._dots: dict[str, _Dot] = {}
        self._labels: dict[str, QLabel] = {}
        self._titles = {"server": tr("Server"), "moysklad": "MoySklad"}
        self._texts: dict[str, str] = {}

        font = QFont()
        font.setPixelSize(12)
        for i, key in enumerate(self.ORDER):
            if i:
                row.addSpacing(10)
            dot = _Dot(self)
            lbl = QLabel(self._titles[key])
            lbl.setFont(font)
            lbl.setStyleSheet(f"color: {t.MUTED}; background: transparent; border: none;")
            row.addWidget(dot)
            row.addWidget(lbl)
            self._dots[key] = dot
            self._labels[key] = lbl

        self._tick = 0
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._blink)
        self._timer.start()

    # ---------------------------------------------------------------- API

    def set_state(self, key: str, state: str, text: str = "") -> None:
        """Chiroq holatini o'rnatish. `text` — qisqa izoh (sariq/qizilda
        yozuv yoniga qo'shiladi, yashilda faqat tooltip)."""
        if key not in self._dots:
            return
        if state not in COLORS:
            state = "unknown"
        dot = self._dots[key]
        changed = dot.state != state
        dot.state = state
        dot.lit = True
        self._texts[key] = text or ""

        lbl = self._labels[key]
        title = self._titles[key]
        if state in ("warn", "bad") and text:
            lbl.setText(f"{title} · {text}")
        else:
            lbl.setText(title)
        color = {"bad": t.DANGER, "warn": t.WARN}.get(state, t.MUTED)
        lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        tip = text or {"ok": tr("Aloqa yaxshi"), "unknown": tr("Noma'lum")}.get(state, "")
        dot.setToolTip(tip)
        lbl.setToolTip(tip)
        if changed:
            dot.update()

    def state(self, key: str) -> str:
        return self._dots[key].state if key in self._dots else "unknown"

    # ------------------------------------------------------------ blink

    def _blink(self) -> None:
        self._tick += 1
        for dot in self._dots.values():
            every = BLINK_EVERY.get(dot.state)
            lit = True if not every else (self._tick // every) % 2 == 0
            if lit != dot.lit:
                dot.lit = lit
                dot.update()
