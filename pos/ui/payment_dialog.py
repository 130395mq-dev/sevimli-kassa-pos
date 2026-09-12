"""
To'lov oynasi — sensorli ekran uchun.

Kassirda klaviatura yo'q, shuning uchun summa ekrandagi raqamlar bilan
kiritiladi. Oyna kenglikda joylashgan: chapda raqamlar, o'ngda to'lov
turlari va qaytim. Monoblok ekrani odatda kenglikka cho'zilgan, shuning
uchun ustma-ust emas, yonma-yon.

MoySklad'dagi «Без сдачи» xatti-harakati saqlangan: summa kiritilmasa,
aniq summa berilgan deb hisoblanadi.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..cart import PaymentPlan
from ..money import som
from ..i18n import tr
from . import theme as t
from . import icons
from .keypad import Keypad, touch_button


def _label(text="", size=14, color=t.INK, bold=False) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return lbl


class PaymentDialog(QDialog):
    """To'lov. Yakunlangach `plan` ichida to'lov qismlari bo'ladi."""

    def __init__(self, total: int, methods: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("To'lov"))
        self.setModal(True)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(f"background: {t.BG};")

        self.plan = PaymentPlan(total=total)
        self.methods = methods
        #: Kassir kiritayotgan summa — tiyinda emas, so'mdagi raqamlar
        self.typed = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._header())

        body = QHBoxLayout()
        body.setContentsMargins(20, 16, 20, 16)
        body.setSpacing(20)
        body.addWidget(self._left(), 5)
        body.addWidget(self._right(), 6)
        root.addLayout(body, 1)

        self.refresh()

    # ------------------------------------------------------------ tuzilish

    def _header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(64)
        w.setStyleSheet(f"background: {t.BG}; border-bottom: 1px solid {t.LINE};")
        row = QHBoxLayout(w)
        row.setContentsMargins(16, 8, 16, 8)

        close = touch_button("", size=22, height=48, tone="soft")
        close.setFixedWidth(64)
        close.setIcon(icons.icon("close", 22, t.INK_SOFT))
        close.setIconSize(icons.button_icon_size(22))
        close.clicked.connect(self.reject)
        row.addWidget(close)

        title = _label(tr("To'lov"), 20, t.INK, bold=True)
        title.setAlignment(Qt.AlignCenter)
        row.addWidget(title, 1)
        row.addSpacing(64)
        return w

    def _left(self) -> QWidget:
        """Chap ustun: kiritilgan summa va raqamlar."""
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        col.addWidget(_label(tr("BERILGAN SUMMA"), 12, t.FAINT, bold=True))

        self.typed_label = _label("", 34, t.INK, bold=True)
        self.typed_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.typed_label.setFixedHeight(64)
        self.typed_label.setStyleSheet(
            f"color: {t.INK}; background: {t.BG}; border: 2px solid {t.ACCENT};"
            f"border-radius: 10px; padding: 0 16px;"
        )
        col.addWidget(self.typed_label)

        # Tez summa tugmalari (6 000 / 10 000 / 50 000 …) OLIB TASHLANDI —
        # kassir summani raqamlar bilan o'zi teradi. Shu bilan ekran toza
        # va tugma tasodifan bosilib, noto'g'ri summa kiritilmaydi.

        keypad = Keypad()
        keypad.digit.connect(self.on_digit)
        keypad.backspace.connect(self.on_backspace)
        keypad.clear.connect(self.on_clear)
        col.addWidget(keypad, 1)

        return w

    def _right(self) -> QWidget:
        """O'ng ustun: to'lanadigan summa, qaytim, to'lov turlari."""
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        # To'lovga
        box = QFrame()
        box.setStyleSheet(
            f"background: {t.BG_SOFT}; border: 1px solid {t.LINE};"
            f"border-radius: 12px;"
        )
        inner = QHBoxLayout(box)
        inner.setContentsMargins(20, 14, 20, 14)
        inner.addWidget(_label(tr("To'lovga"), 16, t.MUTED))
        inner.addStretch(1)
        self.remaining_label = _label("", 32, t.INK, bold=True)
        inner.addWidget(self.remaining_label)
        col.addWidget(box)

        # Qaytim — ekrandagi eng katta son
        self.change_box = QFrame()
        self.change_box.setStyleSheet(
            f"background: {t.ACCENT}; border-radius: 12px;"
        )
        crow = QHBoxLayout(self.change_box)
        crow.setContentsMargins(22, 14, 22, 14)
        left = QVBoxLayout()
        left.setSpacing(0)
        left.addWidget(_label(tr("QAYTIM"), 14, "#BFE0C9", bold=True))
        self.change_hint = _label("", 13, "#A8D3B5")
        left.addWidget(self.change_hint)
        crow.addLayout(left)
        crow.addStretch(1)
        self.change_value = _label("0", 48, "#FFFFFF", bold=True)
        crow.addWidget(self.change_value)
        col.addWidget(self.change_box)

        # Naqd qabul qilish
        self.take_cash_btn = touch_button(
            tr("NAQD QABUL QILISH"), size=18, height=72, tone="accent"
        )
        self.take_cash_btn.clicked.connect(self.take_cash)
        col.addWidget(self.take_cash_btn)

        # Karta va onlayn
        col.addWidget(_label(tr("KARTA VA ONLAYN"), 12, t.FAINT, bold=True))
        grid = QGridLayout()
        grid.setSpacing(8)
        cashless = [m for m in self.methods if not m.get("is_cash")]
        for i, method in enumerate(cashless):
            btn = touch_button(method["name"], size=16, height=62, tone="soft")
            btn.clicked.connect(
                lambda _=False, code=method["code"]: self.take_cashless(code)
            )
            grid.addWidget(btn, i // 2, i % 2)
        col.addLayout(grid)

        # Aralash to'lov — yarmi naqd, yarmi karta/onlayn. Alohida oynada
        # har to'lov turiga summa teriladi (kassir «yashirin» yo'lni —
        # summa terib NAQD, qolganiga karta — bilishi shart emas).
        self.split_btn = touch_button(
            tr("ARALASH TO'LOV (naqd + karta)"), size=16, height=62, tone="plain"
        )
        self.split_btn.setStyleSheet(
            self.split_btn.styleSheet()
            + f"QPushButton {{ border-color: {t.ACCENT}; color: {t.PRICE}; }}"
        )
        self.split_btn.clicked.connect(self.open_split)
        col.addWidget(self.split_btn)

        self.parts_label = _label("", 13, t.MUTED)
        self.parts_label.setWordWrap(True)
        col.addWidget(self.parts_label)

        col.addStretch(1)

        self.finish = touch_button(tr("YAKUNLASH"), size=20, height=76, tone="dark")
        self.finish.clicked.connect(self.accept)
        col.addWidget(self.finish)

        return w

    # ------------------------------------------------------------ kiritish

    def on_digit(self, value: str) -> None:
        # Uzun summa kiritilmasin — 9 raqam = 999 mln so'm, yetarli
        if len(self.typed) + len(value) <= 9:
            self.typed = (self.typed + value).lstrip("0") or "0"
        self.refresh()

    def on_backspace(self) -> None:
        self.typed = self.typed[:-1]
        self.refresh()

    def on_clear(self) -> None:
        self.typed = ""
        self.refresh()

    @property
    def tendered(self) -> int:
        """Kiritilgan summa tiyinda. Kiritilmagan bo'lsa 0."""
        return int(self.typed) * 100 if self.typed.isdigit() else 0

    # ------------------------------------------------------------ harakat

    def take_cash(self) -> None:
        tendered = self.tendered or self.plan.remaining
        if tendered <= 0:
            return
        self.plan.add_cash(tendered)
        self.typed = ""
        self.refresh()

    def take_cashless(self, code: str) -> None:
        if self.plan.remaining <= 0:
            return
        # Summa kiritilgan bo'lsa — o'shancha, aks holda qolganining hammasi
        amount = self.tendered or None
        self.plan.add(code, amount)
        self.typed = ""
        self.refresh()

    def open_split(self) -> None:
        """«Aralash to'lov» oynasi — qolgan summa bir necha turga bo'linadi."""
        if self.plan.remaining <= 0:
            return
        from .split_payment import SplitPaymentDialog

        dlg = SplitPaymentDialog(self.plan.remaining, self.methods, self)
        if dlg.exec() != QDialog.Accepted or not dlg.parts:
            return
        self.apply_split(dlg.parts)

    def apply_split(self, parts) -> None:
        """Aralash to'lov qismlarini rejaga qo'shadi; to'liq bo'lsa yakunlaydi."""
        self.plan.parts.extend(parts)
        self.typed = ""
        self.refresh()
        if self.plan.is_complete:
            self.accept()

    # ------------------------------------------------------------ chizish

    def refresh(self) -> None:
        remaining = self.plan.remaining
        self.remaining_label.setText(som(remaining))
        self.typed_label.setText(som(self.tendered) if self.typed else "—")

        self._refresh_change(remaining)
        self._refresh_parts()

        ready = self.plan.is_complete
        self.finish.setEnabled(ready)
        self.take_cash_btn.setEnabled(not ready)
        self.split_btn.setEnabled(not ready)

    def set_typed(self, tiyin: int) -> None:
        self.typed = str(tiyin // 100)
        self.refresh()

    def _refresh_change(self, remaining: int) -> None:
        tendered = self.tendered

        if tendered and tendered > remaining > 0:
            self.change_value.setText(som(tendered - remaining))
            self.change_hint.setText(f"{som(tendered)} − {som(remaining)}")
            self.change_box.show()
            return

        last_change = next(
            (p.change for p in reversed(self.plan.parts) if p.change), 0
        )
        if last_change:
            self.change_value.setText(som(last_change))
            self.change_hint.setText("mijozga qaytariladi")
            self.change_box.show()
            return

        self.change_value.setText("0")
        self.change_hint.setText("qaytim yo'q")
        self.change_box.show()

    def _refresh_parts(self) -> None:
        if not self.plan.parts:
            self.parts_label.setText("")
            return
        names = {m["code"]: m["name"] for m in self.methods}
        self.parts_label.setText(
            " · ".join(
                f"{names.get(p.method, p.method)} {som(p.amount)}"
                for p in self.plan.parts
            )
        )

    # Klaviatura bo'lsa ham ishlasin — sinov va zaxira uchun
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F9 and self.plan.is_complete:
            self.accept()
        elif key == Qt.Key_Escape:
            self.reject()
        elif Qt.Key_0 <= key <= Qt.Key_9:
            self.on_digit(chr(key))
        elif key == Qt.Key_Backspace:
            self.on_backspace()
        else:
            super().keyPressEvent(event)
