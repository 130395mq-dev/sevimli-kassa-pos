"""
Aralash to'lov oynasi — bir chekni bir necha to'lov turi bilan yopish.

Mijoz 200 mingning yarmini naqd, yarmini Click bilan to'lamoqchi.
To'lov oynasidagi «ARALASH TO'LOV» tugmasi shu oynani ochadi: chapda
raqamlar, o'ngda har to'lov turi uchun bitta qator (Naqd, UzCard, Humo,
Click, Karta …). Kassir qatorga bosadi, summani teradi; «QOLGANINI»
tanlangan qatorga hali yopilmagan summani qo'yadi. Pastda «Qoldi» yoki
«Qaytim» doim ko'rinib turadi — hammasi yopilganda YAKUNLASH yonadi.

Hisob-kitob `cart.split_payment` da — bu fayl faqat chizadi.

Vaznli tovar bo'lsa chek tiyinli chiqadi (16 001,20 so'm). Shuning uchun
bu oynaning klaviaturasida VERGUL bor — kassir 6001,20 deb tera oladi,
«QOLGANINI» esa qolgan summani tiyinigacha aniq qo'yadi (6001,20).
«Qoldi»/«Qaytim» tiyinni yashirmaydi — aks holda «QOLDI 0» deb turib
YAKUNLASH yonmas edi.

Qolgan summa O'ZI tushadi (2026-09-25, egasining so'rovi): kassir naqdga
10 000 teradi, keyin UzCard qatoriga bosadi — qolgan 12 500,55 o'zi
tushadi. Bunday «avto» qator bitta bo'ladi va boshqa qatorlar o'zgarsa
o'zi moslashadi; ustidan raqam terilsa — summa almashadi (qo'shilmaydi)
va qator oddiy (qo'lda yozilgan) bo'lib qoladi. Kassir qo'lda yozgan
summaga dastur hech qachon tegmaydi.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..cart import PaymentPart, SplitEntry, split_payment
from ..i18n import tr
from ..money import som, som_exact
from . import icons
from . import theme as t
from .keypad import Keypad, touch_button


def _label(text="", size=14, color=t.INK, bold=False) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return lbl


class _Row(QPushButton):
    """Bitta to'lov turi: nomi chapda, summa o'ngda. Bosilsa tanlanadi."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(66)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCheckable(True)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 18, 0)
        self.name_label = _label(name, 18, t.INK, bold=True)
        row.addWidget(self.name_label)
        # «qolgani» — summa o'zi tushganini bildiradi (ustidan tersa almashadi)
        self.hint_label = _label(tr("qolgani"), 13, t.ACCENT, bold=True)
        self.hint_label.hide()
        row.addSpacing(10)
        row.addWidget(self.hint_label)
        row.addStretch(1)
        self.amount_label = _label("—", 22, t.MUTED, bold=True)
        self.amount_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.amount_label)
        self._paint(False)

    def _paint(self, selected: bool) -> None:
        border = t.ACCENT if selected else t.LINE_STRONG
        bg = t.ACCENT_PALE if selected else t.BG
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; border: 2px solid {border};"
            f" border-radius: 12px; text-align: left; }}"
        )

    def set_selected(self, selected: bool) -> None:
        self.setChecked(selected)
        self._paint(selected)

    def set_auto(self, on: bool) -> None:
        self.hint_label.setVisible(on)

    def set_amount(self, tiyin: int) -> None:
        if tiyin > 0:
            self.amount_label.setText(som_exact(tiyin))
            self.amount_label.setStyleSheet(
                f"color: {t.PRICE}; background: transparent; border: none;"
            )
        else:
            self.amount_label.setText("—")
            self.amount_label.setStyleSheet(
                f"color: {t.MUTED}; background: transparent; border: none;"
            )


class SplitPaymentDialog(QDialog):
    """Aralash to'lov. Yakunlangach `parts` ichida to'lov qismlari bo'ladi."""

    def __init__(self, total: int, methods: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Aralash to'lov"))
        self.setModal(True)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(f"background: {t.BG};")

        self.total = total
        # Naqd birinchi, keyin karta/onlayn — kassir ko'zi o'rganib qolgan tartib
        self.methods = sorted(methods, key=lambda m: 0 if m.get("is_cash") else 1)
        #: Har qator uchun terilgan summa (matn, so'm; vergul bilan tiyin:
        #: "6001,20") — kod bo'yicha
        self.typed: dict[str, str] = {m["code"]: "" for m in self.methods}
        #: Qolgan summa o'zi tushgan («avto») qator — ko'pi bilan bittasi
        self.auto_code: str | None = None
        self.selected: str = self.methods[0]["code"] if self.methods else ""
        #: Natija — YAKUNLASH bosilganda to'ldiriladi
        self.parts: list[PaymentPart] = []
        self.change = 0

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

        title = _label(tr("Aralash to'lov"), 20, t.INK, bold=True)
        title.setAlignment(Qt.AlignCenter)
        row.addWidget(title, 1)
        row.addSpacing(64)
        return w

    def _left(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        hint = _label(
            tr("Qatorga bosing — qolgan summa o'zi tushadi. Boshqa summa kerak bo'lsa, ustidan tering."),
            13, t.MUTED,
        )
        hint.setWordWrap(True)
        col.addWidget(hint)

        self.rest_btn = touch_button(tr("QOLGANINI"), size=18, height=64, tone="accent")
        self.rest_btn.clicked.connect(self.put_rest)
        col.addWidget(self.rest_btn)

        keypad = Keypad(with_comma=True)
        keypad.digit.connect(self.on_digit)
        keypad.comma.connect(self.on_comma)
        keypad.backspace.connect(self.on_backspace)
        keypad.clear.connect(self.on_clear)
        col.addWidget(keypad, 1)
        return w

    def _right(self) -> QWidget:
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        box = QFrame()
        box.setStyleSheet(
            f"background: {t.BG_SOFT}; border: 1px solid {t.LINE}; border-radius: 12px;"
        )
        inner = QHBoxLayout(box)
        inner.setContentsMargins(20, 12, 20, 12)
        inner.addWidget(_label(tr("To'lovga"), 16, t.MUTED))
        inner.addStretch(1)
        self.total_label = _label(som_exact(self.total), 28, t.INK, bold=True)
        inner.addWidget(self.total_label)
        col.addWidget(box)

        self.rows: dict[str, _Row] = {}
        for m in self.methods:
            row = _Row(m["name"])
            row.clicked.connect(lambda _=False, code=m["code"]: self.select(code))
            col.addWidget(row)
            self.rows[m["code"]] = row

        # Qoldi / qaytim / xato — kassir ko'zi doim shu yerda
        self.status_box = QFrame()
        srow = QHBoxLayout(self.status_box)
        srow.setContentsMargins(22, 12, 22, 12)
        self.status_title = _label("", 14, "#BFE0C9", bold=True)
        srow.addWidget(self.status_title)
        srow.addStretch(1)
        self.status_value = _label("", 34, "#FFFFFF", bold=True)
        srow.addWidget(self.status_value)
        col.addWidget(self.status_box)

        col.addStretch(1)

        self.finish = touch_button(tr("YAKUNLASH"), size=20, height=76, tone="dark")
        self.finish.clicked.connect(self._finish)
        col.addWidget(self.finish)
        return w

    # ------------------------------------------------------------ holat

    @staticmethod
    def to_tiyin(raw: str) -> int:
        """Terilgan matn → tiyin: "6001" → 600100, "6001,2" → 600120,
        "6001,20" → 600120, "0,5" → 50, "" → 0."""
        whole, _, frac = raw.partition(",")
        if not (whole.isdigit() or (not whole and frac)):
            return 0
        frac = (frac + "00")[:2]
        if not frac.isdigit():
            return 0
        return int(whole or 0) * 100 + int(frac)

    @staticmethod
    def to_text(tiyin: int) -> str:
        """Tiyin → teriladigan matn: 600120 → "6001,20", 600100 → "6001"."""
        whole, frac = divmod(max(tiyin, 0), 100)
        return f"{whole},{frac:02d}" if frac else str(whole)

    def entries(self) -> list[SplitEntry]:
        out = []
        for m in self.methods:
            code = m["code"]
            amount = self.to_tiyin(self.typed.get(code, ""))
            out.append(SplitEntry(code, bool(m.get("is_cash")), amount))
        return out

    def result(self):
        return split_payment(self.total, self.entries())

    def _other_sum(self, code: str) -> int:
        """Tanlangan qatordan tashqari hamma kiritilgan summa (tiyin)."""
        return sum(e.amount for e in self.entries() if e.method != code)

    # ------------------------------------------------------------ harakat

    def _amount(self, code: str) -> int:
        return self.to_tiyin(self.typed.get(code, ""))

    def _rebalance(self) -> None:
        """Avto qator doim qolgan summaga teng (manfiy bo'lsa — bo'sh)."""
        code = self.auto_code
        if not code:
            return
        rest = self.total - self._other_sum(code)
        self.typed[code] = self.to_text(rest) if rest > 0 else ""

    def _start_typing(self) -> str:
        """Tanlangan qatorga terish boshlandi. Avto summa ustidan terilsa —
        u ALMASHADI (qo'shilmaydi) va qator qo'lda yozilganga aylanadi."""
        code = self.selected
        if code == self.auto_code:
            self.typed[code] = ""
            self.auto_code = None
        return code

    def select(self, code: str) -> None:
        """Qatorni tanlaydi. Qator bo'sh bo'lsa va to'lanmagan summa qolgan
        bo'lsa — o'sha summa shu qatorga O'ZI tushadi (tiyinigacha)."""
        self.selected = code
        if self._amount(code) == 0:
            rest = self.total - self._other_sum(code)
            if rest > 0:
                self.typed[code] = self.to_text(rest)
                self.auto_code = code
        self.refresh()

    def on_digit(self, value: str) -> None:
        if not self.selected:
            return
        code = self._start_typing()
        cur = self.typed.get(code, "")
        whole, comma, frac = cur.partition(",")
        if comma:
            # Verguldan keyin ko'pi bilan 2 raqam (tiyin)
            self.typed[code] = whole + "," + (frac + value)[:2]
        elif len(whole) + len(value) <= 9:
            self.typed[code] = (whole + value).lstrip("0") or "0"
        self._rebalance()
        self.refresh()

    def on_comma(self) -> None:
        """Vergul — tiyin terish uchun (6001,20). Ikkinchi vergul e'tiborsiz."""
        if not self.selected:
            return
        code = self._start_typing()
        cur = self.typed.get(code, "")
        if "," not in cur:
            self.typed[code] = (cur or "0") + ","
        self._rebalance()
        self.refresh()

    def on_backspace(self) -> None:
        if self.selected:
            code = self.selected
            if code == self.auto_code:
                self.auto_code = None      # endi qo'lda tahrirlanmoqda
            self.typed[code] = self.typed.get(code, "")[:-1]
            self._rebalance()
        self.refresh()

    def on_clear(self) -> None:
        if self.selected:
            code = self.selected
            if code == self.auto_code:
                self.auto_code = None
            self.typed[code] = ""
            self._rebalance()
        self.refresh()

    def put_rest(self) -> None:
        """«QOLGANINI»: tanlangan qatorga qolgan summani qo'yadi — tiyinigacha
        (16 001,20 so'mlik chekni 16 001 deb qo'ysak 20 tiyin ochiq qolardi).

        Boshqa qatorga avto tushgan summa bo'lsa — u shu qatorga KO'CHADI
        (kassir fikrini o'zgartirdi: «Humo emas, Click»)."""
        if not self.selected:
            return
        code = self.selected
        if self.auto_code and self.auto_code != code:
            self.typed[self.auto_code] = ""
            self.auto_code = None
        rest = self.total - self._other_sum(code)
        if rest > 0:
            self.typed[code] = self.to_text(rest)
            self.auto_code = code
        else:
            self.typed[code] = ""
            if self.auto_code == code:
                self.auto_code = None
        self.refresh()

    def _finish(self) -> None:
        res = self.result()
        if not res.ok:
            return
        self.parts = res.parts
        self.change = res.change
        self.accept()

    # ------------------------------------------------------------ chizish

    def refresh(self) -> None:
        for e in self.entries():
            row = self.rows[e.method]
            row.set_amount(e.amount)
            row.set_selected(e.method == self.selected)
            row.set_auto(e.method == self.auto_code and e.amount > 0)

        res = self.result()
        if res.error:
            self._status(tr(res.error), "", t.DANGER)
        elif res.remaining > 0:
            self._status(tr("QOLDI"), som_exact(res.remaining), t.WARN)
        elif res.change > 0:
            self._status(tr("QAYTIM"), som_exact(res.change), t.ACCENT)
        else:
            self._status(tr("HAMMASI YOPILDI"), som(0), t.ACCENT)

        self.finish.setEnabled(res.ok)
        sel = self.selected
        movable = bool(self.auto_code and self.auto_code != sel
                       and self._amount(self.auto_code) > 0)
        self.rest_btn.setEnabled(
            bool(sel) and (self.total - self._other_sum(sel) > 0 or movable)
        )

    def _status(self, title: str, value: str, bg: str) -> None:
        self.status_box.setStyleSheet(f"background: {bg}; border-radius: 12px;")
        self.status_title.setText(title)
        self.status_value.setText(value)

    # Klaviatura bo'lsa ham ishlasin — sinov va zaxira uchun
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F9:
            self._finish()
        elif key == Qt.Key_Escape:
            self.reject()
        elif Qt.Key_0 <= key <= Qt.Key_9:
            self.on_digit(chr(key))
        elif key in (Qt.Key_Comma, Qt.Key_Period):
            self.on_comma()
        elif key == Qt.Key_Backspace:
            self.on_backspace()
        else:
            super().keyPressEvent(event)
