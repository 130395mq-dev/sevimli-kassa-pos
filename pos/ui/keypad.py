"""
Ekrandagi klaviatura — sensorli monoblok uchun.

Kassirlarda jismoniy klaviatura yo'q. Demak barmoq bilan bosiladigan
hamma narsa yetarlicha katta bo'lishi kerak va har bir kiritish uchun
ekranda tugma bo'lishi shart.

O'lchamlar bekorga tanlanmagan. Barmoq izining o'rtacha kengligi
9–10 mm; odatiy monoblok ekranida bu ~64 px. Tugmalar orasida bo'shliq
ham kerak — aks holda kassir shoshib turib qo'shni tugmani bosadi va
buni sezmaydi ham.

Ikkita klaviatura bor:

  Keypad   — raqamlar. Pul, miqdor, telefon uchun.
  Letters  — harflar. Kassir ismi, mijoz nomi uchun. Kam ishlatiladi,
             shuning uchun tugmalari kichikroq.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QPushButton, QVBoxLayout, QWidget

from . import theme as t

#: Barmoq uchun eng kichik qulay o'lcham
TOUCH = 64


def touch_button(text: str, *, size: int = 20, bold: bool = True,
                 height: int = TOUCH, tone: str = "plain") -> QPushButton:
    """Barmoq bilan bosiladigan tugma."""
    btn = QPushButton(text)
    btn.setMinimumHeight(height)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFocusPolicy(Qt.NoFocus)  # fokus sakrab yurmasin

    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    btn.setFont(font)

    palette = {
        "plain": (t.BG, t.INK, t.LINE_STRONG),
        "soft": (t.BG_SOFT, t.INK_SOFT, t.LINE_STRONG),
        "accent": (t.ACCENT, "#FFFFFF", t.ACCENT),
        "dark": (t.DARK, "#FFFFFF", t.DARK),
        "danger": (t.DANGER, "#FFFFFF", t.DANGER),
    }
    bg, fg, border = palette.get(tone, palette["plain"])

    btn.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: {fg};"
        f" border: 1.5px solid {border}; border-radius: 10px; }}"
        # Bosilganda rang o'zgarsin — kassir bosilganini ko'rsin,
        # chunki sensorli ekranda «bosildi» hissi yo'q
        f"QPushButton:pressed {{ background: {t.ACCENT_DARK if tone in ('accent', 'dark', 'danger') else t.ACCENT_PALE};"
        f" border-color: {t.ACCENT}; }}"
        f"QPushButton:disabled {{ background: {t.BG_SOFT}; color: {t.FAINT};"
        f" border-color: {t.LINE}; }}"
    )
    return btn


class Keypad(QWidget):
    """Raqamli klaviatura.

    Kiritilgan matnni o'zi saqlamaydi — har bosishda signal yuboradi.
    Matnni kim ishlatsa, o'sha boshqaradi.
    """

    digit = Signal(str)
    backspace = Signal()
    clear = Signal()

    def __init__(self, *, with_zeros: bool = True, parent=None):
        super().__init__(parent)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        for i in range(9):
            row, col = divmod(i, 3)
            btn = touch_button(str(i + 1), size=24)
            btn.clicked.connect(lambda _=False, d=str(i + 1): self.digit.emit(d))
            grid.addWidget(btn, row, col)

        # Oxirgi qator: 000 · 0 · o'chirish
        if with_zeros:
            triple = touch_button("000", size=20)
            triple.clicked.connect(lambda: self.digit.emit("000"))
            grid.addWidget(triple, 3, 0)
        else:
            spacer = touch_button("C", size=20, tone="soft")
            spacer.clicked.connect(self.clear.emit)
            grid.addWidget(spacer, 3, 0)

        zero = touch_button("0", size=24)
        zero.clicked.connect(lambda: self.digit.emit("0"))
        grid.addWidget(zero, 3, 1)

        back = touch_button("←", size=26, tone="soft")
        back.clicked.connect(self.backspace.emit)
        grid.addWidget(back, 3, 2)


class Letters(QWidget):
    """Harflar klaviaturasi — ism kiritish uchun.

    Kam ishlatiladi (smena boshida bir marta), shuning uchun tugmalar
    raqamlardagidan kichikroq. Lekin baribir barmoq bilan bosiladigan
    o'lchamda.
    """

    letter = Signal(str)
    backspace = Signal()
    space = Signal()

    ROWS = [
        "QWERTYUIOP",
        "ASDFGHJKL",
        "ZXCVBNM'",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(7)

        for line in self.ROWS:
            row = QGridLayout()
            row.setSpacing(6)
            for i, ch in enumerate(line):
                btn = touch_button(ch, size=18, height=52)
                btn.clicked.connect(lambda _=False, c=ch: self.letter.emit(c))
                row.addWidget(btn, 0, i)
            holder = QWidget()
            holder.setLayout(row)
            col.addWidget(holder)

        bottom = QGridLayout()
        bottom.setSpacing(6)

        space = touch_button("bo'sh joy", size=16, bold=False, height=52, tone="soft")
        space.clicked.connect(self.space.emit)
        bottom.addWidget(space, 0, 0, 1, 3)

        back = touch_button("←", size=22, height=52, tone="soft")
        back.clicked.connect(self.backspace.emit)
        bottom.addWidget(back, 0, 3)

        holder = QWidget()
        holder.setLayout(bottom)
        col.addWidget(holder)


class FullKeyboard(QWidget):
    """To'liq klaviatura — server manzili, login va parol uchun.

    Kassada jismoniy klaviatura yo'q, shuning uchun ulash oynasida ham
    barmoq bilan yoziladigan klaviatura kerak. Harflar, raqamlar va
    manzil belgilari (`.` `:` `/` `-`) bir joyda. `⇧` katta harfga
    o'tkazadi.
    """

    key = Signal(str)
    backspace = Signal()

    ROWS = [
        "1234567890",
        "qwertyuiop",
        "asdfghjkl",
        "zxcvbnm",
    ]
    #: Manzil (URL) uchun kerak belgilar
    SYMBOLS = ".:/-@_"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._upper = False
        self._letter_buttons: list[QPushButton] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        for line in self.ROWS:
            row = QGridLayout()
            row.setSpacing(5)
            for i, ch in enumerate(line):
                btn = touch_button(ch, size=17, height=50)
                btn.clicked.connect(lambda _=False, b=btn: self._emit(b.text()))
                if ch.isalpha():
                    self._letter_buttons.append(btn)
                row.addWidget(btn, 0, i)
            holder = QWidget()
            holder.setLayout(row)
            col.addWidget(holder)

        # Pastki qator: ⇧, belgilar, ←
        bottom = QGridLayout()
        bottom.setSpacing(5)

        self._shift = touch_button("⇧", size=20, height=50, tone="soft")
        self._shift.clicked.connect(self._toggle_shift)
        bottom.addWidget(self._shift, 0, 0)

        for i, ch in enumerate(self.SYMBOLS):
            btn = touch_button(ch, size=18, height=50, tone="soft")
            btn.clicked.connect(lambda _=False, c=ch: self.key.emit(c))
            bottom.addWidget(btn, 0, i + 1)

        back = touch_button("←", size=22, height=50, tone="soft")
        back.clicked.connect(self.backspace.emit)
        bottom.addWidget(back, 0, len(self.SYMBOLS) + 1)

        holder = QWidget()
        holder.setLayout(bottom)
        col.addWidget(holder)

    def _emit(self, text: str) -> None:
        self.key.emit(text.upper() if self._upper else text.lower())

    def _toggle_shift(self) -> None:
        self._upper = not self._upper
        for btn in self._letter_buttons:
            btn.setText(btn.text().upper() if self._upper else btn.text().lower())
        self._shift.setStyleSheet(self._shift.styleSheet())  # holatni yangilash
