"""
Kassaning yordamchi oynalari — sensorli ekran uchun.

Hamma summa ekrandagi raqamlar bilan kiritiladi: kassirda jismoniy
klaviatura yo'q. Windows'ning o'z ekran klaviaturasi ham bor, lekin u
ekranning yarmini to'sib qo'yadi va tugmalari mayda — shuning uchun
o'zimizniki.

Ism kabi matnlar kam kiritiladi (smenada bir marta), ular uchun
harflar klaviaturasi bor.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..money import som, refund_total
from ..i18n import get_lang, tr
from . import theme as t
from . import icons
from .keypad import FullKeyboard, Keypad, Letters, touch_button


def _label(text="", size=14, color=t.INK, bold=False) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return lbl


def _display(text="—", size=32) -> QLabel:
    """Kiritilgan qiymat ko'rinadigan katta maydon."""
    lbl = QLabel(text)
    font = QFont()
    font.setPixelSize(size)
    font.setBold(True)
    lbl.setFont(font)
    lbl.setFixedHeight(66)
    lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    lbl.setStyleSheet(
        f"color: {t.INK}; background: {t.BG}; border: 2px solid {t.ACCENT};"
        f"border-radius: 10px; padding: 0 16px;"
    )
    return lbl


class BaseDialog(QDialog):
    def __init__(self, title: str, width: int = 480, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setStyleSheet(f"background: {t.BG};")

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(12)

        heading = _label(title, 20, t.INK, bold=True)
        heading.setAlignment(Qt.AlignCenter)
        self.root.addWidget(heading)

    def buttons(self, ok_text: str, on_ok=None, height: int = 68) -> None:
        """Pastdagi ikkita tugma: bekor va tasdiqlash."""
        row = QHBoxLayout()
        row.setSpacing(10)
        cancel = touch_button(tr("Bekor"), size=17, height=height, tone="soft")
        cancel.clicked.connect(self.reject)
        ok = touch_button(ok_text, size=18, height=height, tone="accent")
        ok.clicked.connect(on_ok or self.accept)
        row.addWidget(cancel, 2)
        row.addWidget(ok, 3)
        self.root.addLayout(row)


class NumberDialog(BaseDialog):
    """Raqam kiritish uchun umumiy oyna. Summalar so'mda kiritiladi."""

    def __init__(self, title: str, hint: str = "", start: str = "",
                 ok_text: str = tr("SAQLASH"), parent=None):
        super().__init__(title, parent=parent)
        self.typed = start

        if hint:
            note = _label(hint, 14, t.MUTED)
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignCenter)
            self.root.addWidget(note)

        self.display = _display()
        self.root.addWidget(self.display)

        pad = Keypad()
        pad.digit.connect(self.on_digit)
        pad.backspace.connect(self.on_backspace)
        pad.clear.connect(self.on_clear)
        self.root.addWidget(pad)

        self.buttons(ok_text)
        self.refresh()

    def on_digit(self, value: str) -> None:
        if len(self.typed) + len(value) <= 9:
            self.typed = (self.typed + value).lstrip("0") or "0"
        self.refresh()

    def on_backspace(self) -> None:
        self.typed = self.typed[:-1]
        self.refresh()

    def on_clear(self) -> None:
        self.typed = ""
        self.refresh()

    def refresh(self) -> None:
        self.display.setText(
            f"{int(self.typed):,}".replace(",", " ") if self.typed else "—"
        )

    @property
    def value(self) -> int | None:
        """So'mdagi qiymat."""
        return int(self.typed) if self.typed.isdigit() else None

    @property
    def tiyin(self) -> int | None:
        value = self.value
        return None if value is None else value * 100


# ------------------------------------------------------------------ smena


class OpenShiftDialog(BaseDialog):
    """Smena ochish: kassir ismi va razmen puli."""

    def __init__(self, cashiers: list[str] | None = None, parent=None):
        super().__init__(tr("Smena ochish"), width=620, parent=parent)
        self.name = ""
        self.typed_cash = ""

        self.root.addWidget(_label(tr("KASSIR"), 12, t.FAINT, bold=True))
        self.name_display = _display("—", size=24)
        self.name_display.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.root.addWidget(self.name_display)

        # Oldin ishlagan kassirlar — bir bosishda tanlanadi.
        # Har smenada ismni yozib o'tirish sensorli ekranda azob.
        if cashiers:
            grid = QGridLayout()
            grid.setSpacing(8)
            for i, name in enumerate(cashiers[:6]):
                btn = touch_button(name, size=15, height=58, tone="soft")
                btn.clicked.connect(lambda _=False, n=name: self.set_name(n))
                grid.addWidget(btn, i // 2, i % 2)
            self.root.addLayout(grid)

        letters = Letters()
        letters.letter.connect(self.add_letter)
        letters.space.connect(lambda: self.add_letter(" "))
        letters.backspace.connect(self.del_letter)
        self.root.addWidget(letters)

        self.root.addWidget(_label(tr("RAZMEN PULI (so'm)"), 12, t.FAINT, bold=True))
        self.cash_display = _display("0", size=26)
        self.root.addWidget(self.cash_display)

        row = QHBoxLayout()
        row.setSpacing(8)
        for amount in (100_000, 200_000, 300_000, 500_000):
            btn = touch_button(f"{amount:,}".replace(",", " "), size=15,
                               height=54, tone="soft")
            btn.clicked.connect(lambda _=False, a=amount: self.set_cash(a))
            row.addWidget(btn)
        self.root.addLayout(row)

        self.buttons(tr("OCHISH"), self._accept)
        self.refresh()

    def set_name(self, name: str) -> None:
        self.name = name
        self.refresh()

    def add_letter(self, ch: str) -> None:
        if len(self.name) < 40:
            # Birinchi harf katta, qolgani kichik — ism shunday yoziladi
            self.name += ch if not self.name or self.name[-1] == " " else ch.lower()
        self.refresh()

    def del_letter(self) -> None:
        self.name = self.name[:-1]
        self.refresh()

    def set_cash(self, amount: int) -> None:
        self.typed_cash = str(amount)
        self.refresh()

    def refresh(self) -> None:
        self.name_display.setText(self.name or "—")
        value = int(self.typed_cash or 0)
        self.cash_display.setText(f"{value:,}".replace(",", " "))

    def _accept(self) -> None:
        if self.name.strip():
            self.accept()

    @property
    def values(self) -> tuple[str, int]:
        return self.name.strip(), int(self.typed_cash or 0) * 100


class CloseShiftDialog(NumberDialog):
    """Smena yopish: kassir sanagan naqd pul.

    «Bo'lishi kerak» summasi ataylab ko'rsatilmaydi. Kassir avval
    sanaydi, keyin kiritadi — aks holda tayyor raqamni ko'chirib
    yozish vasvasasi bo'ladi va nazoratning ma'nosi qolmaydi.
    """

    def __init__(self, pending: int = 0, parent=None):
        hint = tr("Kassadagi naqd pulni sanang va kiriting.")
        if pending:
            hint += (
                f"\n\nDiqqat: {pending} ta chek hali serverga yetib bormagan. "
                "Smena baribir yopiladi, cheklar navbatda qoladi."
            )
        super().__init__(tr("Smenani yopish"), hint=hint, ok_text="YOPISH",
                         parent=parent)

    @property
    def counted(self) -> int | None:
        return self.tiyin


class OpeningCashDialog(NumberDialog):
    """Smena ochish — faqat razmen puli. Kassir allaqachon kirgan."""

    def __init__(self, cashier_name: str, parent=None):
        super().__init__(
            tr("Smena ochish"),
            hint=f"{cashier_name}\n\nKassadagi razmen pulini kiriting.",
            ok_text=tr("OCHISH"), parent=parent,
        )

        row = QHBoxLayout()
        row.setSpacing(8)
        for amount in (100_000, 200_000, 300_000, 500_000):
            btn = touch_button(f"{amount:,}".replace(",", " "), size=15,
                               height=54, tone="soft")
            btn.clicked.connect(lambda _=False, a=amount: self.set_amount(a))
            row.addWidget(btn)
        # Raqamlar tagiga, tugmalardan yuqoriga
        self.root.insertLayout(self.root.count() - 1, row)

    def set_amount(self, amount: int) -> None:
        self.typed = str(amount)
        self.refresh()


class ReceiptDialog(BaseDialog):
    """Chekni ko'rsatadi."""

    def __init__(self, text: str, printed: bool, path, parent=None):
        super().__init__(tr("Smena cheki"), width=600, parent=parent)

        view = QPlainTextEdit()
        view.setPlainText(text)
        view.setReadOnly(True)
        font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPixelSize(13)
        view.setFont(font)
        view.setMinimumHeight(440)
        view.setStyleSheet(
            f"border: 1px solid {t.LINE}; border-radius: 10px;"
            f"background: {t.BG_SOFT}; color: {t.INK};"
        )
        self.root.addWidget(view)

        note = _label(
            "Chek printerga yuborildi." if printed
            else f"Printer javob bermadi. Chek faylga saqlandi:\n{path}",
            13, t.MUTED if printed else t.WARN,
        )
        note.setWordWrap(True)
        self.root.addWidget(note)

        ok = touch_button("YOPISH", size=18, height=68, tone="accent")
        ok.clicked.connect(self.accept)
        self.root.addWidget(ok)


# ------------------------------------------------------------------ mijoz


def _line_edit(text: str = "", placeholder: str = "") -> QLineEdit:
    """Kompyuter klaviaturasi bilan yoziladigan maydon."""
    edit = QLineEdit(text)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    edit.setFixedHeight(54)
    edit.setStyleSheet(
        f"QLineEdit {{ border: 1.5px solid {t.LINE_STRONG}; border-radius: 10px;"
        f" padding: 0 14px; font-size: 17px; background: {t.SURFACE_DARK};"
        f" color: {t.INK}; selection-background-color: {t.ACCENT}; }}"
        f"QLineEdit:focus {{ border: 2px solid {t.ACCENT}; background: {t.BG}; }}"
    )
    return edit


class CustomerDialog(BaseDialog):
    """Mijozni FAQAT nakopitelniy karta shtrix-kodi bilan biriktirish.

    Telefon yoki ism bo'yicha qidiruv YO'Q. Kassir mijozning kartasini
    skanerga tutadi — skaner kodni yozadi va Enter bosadi, aynan shu karta
    egasi topiladi. Kod qo'lda ham kiritilishi mumkin (skaner ishlamasa).

    Aniq moslik: boshqa mijoz tasodifan biriktirilmaydi.
    """

    def __init__(self, card_finder, creator=None, parent=None, required=None):
        super().__init__(tr("Mijoz kartasi"), width=560, parent=parent)
        self._find_card = card_finder
        self._creator = creator
        self._required = required
        self.chosen = None

        self.field = _line_edit(
            placeholder=tr("Karta shtrix-kodini skaner qiling")
        )
        # Skaner kodni yozib Enter bosadi — o'shanda qidiramiz. Harf sayin
        # emas: skaner kodni birdaniga to'liq yuboradi.
        self.field.returnPressed.connect(self.lookup)
        self.root.addWidget(self.field)

        self.hint = _label(
            tr("Mijoz kartasini skanerga tuting — orqasidagi shtrix-kod "
               "o'qilsa, mijoz o'zi biriktiriladi."), 14, t.MUTED
        )
        self.hint.setWordWrap(True)
        self.root.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        clear = touch_button(tr("Mijozsiz"), size=16, height=64, tone="soft")
        clear.clicked.connect(self.clear_customer)
        row.addWidget(clear, 2)
        if self._creator:
            new_btn = touch_button("+  " + tr("Yangi mijoz"), size=16,
                                   height=64, tone="soft")
            new_btn.clicked.connect(self.add_new)
            row.addWidget(new_btn, 2)
        self.root.addLayout(row)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.field.setFocus()

    def lookup(self) -> None:
        code = self.field.text().strip()
        # Maydonni tozalaymiz — keyingi skaner ustiga yozmasin.
        self.field.clear()
        self.field.setFocus()
        if not code:
            return
        self.hint.setText(tr("Qidirilmoqda…"))
        try:
            customer = self._find_card(code)
        except Exception as e:
            self.hint.setText(f"Qidirib bo'lmadi: {e}")
            return
        if customer is None:
            self.hint.setText(tr("Bu karta topilmadi — kod noto'g'ri yoki "
                                 "mijoz bazada yo'q."))
            return
        self.chosen = customer
        self.accept()

    def add_new(self) -> None:
        dialog = NewCustomerDialog(self._creator, self, required=self._required)
        if dialog.exec() == NewCustomerDialog.Accepted and dialog.created:
            self.chosen = dialog.created
            self.accept()

    def clear_customer(self) -> None:
        self.chosen = None
        self.accept()


class NewCustomerDialog(BaseDialog):
    """Yangi mijoz: ism, familiya, telefon, nakopitelniy karta raqami.

    Kompyuter klaviaturasidan yoziladi. Telefon maydonida +998 oldindan
    turadi. Saqlanganda mijoz serverda (MoySklad sozlangan bo'lsa — unda
    ham) yaratiladi.
    """

    def __init__(self, creator, parent=None, required=None):
        super().__init__(tr("Yangi mijoz"), width=560, parent=parent)
        self._creator = creator
        self.created = None
        # Panelda belgilangan majburiy maydonlar (fio, phone, card).
        self._required = set(required or ("fio", "phone", "card"))

        self.fields = {}
        # (kalit, yorliq, standart, panel-maydon-nomi)
        specs = [
            ("ism", "Ism", "", "fio"),
            ("familiya", "Familiya", "", "fio"),
            ("tel", "Telefon", "+998", "phone"),
            ("karta", "Karta raqami", "", "card"),
        ]
        for key, label, default, req_key in specs:
            star = " *" if req_key in self._required else ""
            self.root.addWidget(_label(tr(label) + star, 13, t.FAINT, bold=True))
            edit = _line_edit(text=default)
            self.fields[key] = edit
            self.root.addWidget(edit)

        self.hint = _label("", 13, t.DANGER)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.root.addWidget(self.hint)

        self.buttons(tr("SAQLASH"), self._save)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.fields["ism"].setFocus()

    def _save(self) -> None:
        ism = self.fields["ism"].text().strip()
        familiya = self.fields["familiya"].text().strip()
        tel = self.fields["tel"].text().strip()
        karta = self.fields["karta"].text().strip()
        if tel in ("+998", "+"):
            tel = ""

        def fail(msg: str) -> None:
            self.hint.setStyleSheet(
                f"color:{t.DANGER}; background:transparent; border:none;"
            )
            self.hint.setText(tr(msg))

        # Majburiy maydonlarni tekshiramiz — panel sozlamasi bo'yicha
        if "fio" in self._required and len(ism) < 2:
            fail("Ism kamida 2 harf bo'lishi kerak")
            return
        if "phone" in self._required and len(tel) < 7:
            fail("Telefon raqami kerak")
            return
        if "card" in self._required and not karta:
            fail("Karta raqami kerak")
            return
        name = f"{familiya} {ism}".strip()
        self.hint.setStyleSheet(
            f"color:{t.MUTED}; background:transparent; border:none;"
        )
        self.hint.setText(tr("Saqlanmoqda…"))
        QApplication.processEvents()
        try:
            self.created = self._creator(name, tel, karta)
        except Exception as e:
            self.hint.setStyleSheet(
                f"color:{t.DANGER}; background:transparent; border:none;"
            )
            self.hint.setText(str(e))
            return
        self.accept()



# --------------------------------------------------------- miqdor, chegirma


class QuantityDialog(BaseDialog):
    """Miqdor. Vaznli tovarda kilogramm, oddiy tovarda dona."""

    #: Kassir «O'chirish» ni bosgan bo'lsa — qator o'chiriladi
    deleted: bool = False

    def __init__(self, line, parent=None, allow_delete: bool = True):
        super().__init__(tr("Miqdor"), width=480, parent=parent)
        self.line = line
        self.is_weight = line.product.is_weight
        self.typed = ""
        self.deleted = False
        self._allow_delete = allow_delete

        self.root.addWidget(_label(line.product.name, 16, t.INK, bold=True))
        unit = "kg" if self.is_weight else "dona"
        self.root.addWidget(
            _label(f"{som(line.product.price)} so'm / {unit}", 14, t.MUTED)
        )

        self.display = _display(str(line.quantity))
        self.root.addWidget(self.display)

        if self.is_weight:
            note = _label("Grammda kiriting: 734 = 0.734 kg", 13, t.MUTED)
            note.setAlignment(Qt.AlignCenter)
            self.root.addWidget(note)
        else:
            row = QHBoxLayout()
            row.setSpacing(8)
            for n in (1, 2, 3, 5, 10):
                btn = touch_button(str(n), size=18, height=58, tone="soft")
                btn.clicked.connect(lambda _=False, v=n: self.set_value(v))
                row.addWidget(btn)
            self.root.addLayout(row)

        pad = Keypad(with_zeros=not self.is_weight)
        pad.digit.connect(self.on_digit)
        pad.backspace.connect(self.on_backspace)
        pad.clear.connect(self.on_clear)
        self.root.addWidget(pad)

        # Qatorni chekdan o'chirish — MoySklad'dagidek shu oynadan.
        # Panelda «qatorni o'chirishga ruxsat» o'chirilgan bo'lsa —
        # tugma ko'rsatilmaydi.
        if self._allow_delete:
            remove = touch_button(tr("Qatorni o'chirish"), size=16,
                                  height=56, tone="danger")
            remove.clicked.connect(self._delete)
            self.root.addWidget(remove)

        self.buttons(tr("SAQLASH"))
        self.refresh()

    def _delete(self) -> None:
        self.deleted = True
        self.accept()

    def set_value(self, n: int) -> None:
        self.typed = str(n * 1000 if self.is_weight else n)
        self.refresh()

    def on_digit(self, value: str) -> None:
        if len(self.typed) + len(value) <= 7:
            self.typed = (self.typed + value).lstrip("0") or "0"
        self.refresh()

    def on_backspace(self) -> None:
        self.typed = self.typed[:-1]
        self.refresh()

    def on_clear(self) -> None:
        self.typed = ""
        self.refresh()

    def refresh(self) -> None:
        value = self.quantity
        if value is None:
            self.display.setText("—")
        elif self.is_weight:
            self.display.setText(f"{value:.3f} kg")
        else:
            self.display.setText(str(int(value)))

    @property
    def quantity(self) -> Decimal | None:
        if not self.typed.isdigit():
            return None
        try:
            raw = Decimal(self.typed)
        except InvalidOperation:
            return None
        value = raw / 1000 if self.is_weight else raw
        return value if value > 0 else None


class DiscountDialog(BaseDialog):
    """Chek chegirmasi, foizda. Faqat tayyor qiymatlar."""

    #: 100% chegirma — bepul berish. Tasodifan bosilmasin uchun yo'q.
    OPTIONS = (0, 3, 5, 7, 10, 15, 20, 30)

    def __init__(self, current: float = 0.0, parent=None, max_percent: float = 100.0):
        super().__init__(tr("Chek chegirmasi"), width=480, parent=parent)
        self.percent = None

        self.display = _display(f"{current:g}%")
        self.root.addWidget(self.display)

        # Panelda belgilangan «Eng ko'p chegirma» dan oshmasin.
        options = [v for v in self.OPTIONS if v <= max_percent]
        if not options:
            options = [0]

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, value in enumerate(options):
            btn = touch_button(
                f"{value}%", size=19, height=72,
                tone="accent" if value == current else "soft",
            )
            btn.clicked.connect(lambda _=False, v=value: self.choose(v))
            grid.addWidget(btn, i // 4, i % 4)
        self.root.addLayout(grid)

        self.buttons(tr("QO'YISH"))

    def choose(self, value: int) -> None:
        self.percent = float(value)
        self.display.setText(f"{value}%")


class PointsDialog(BaseDialog):
    """Ball ishlatish — mijozning bonus ballaridan chek to'loviga.

    1 ball = 1 so'm. Kassir nechta ball ishlatishni kiritadi (yoki «Bor
    ballni to'liq ishlat»). Balans va bu chek uchun ruxsat etilgan eng
    ko'p ball ko'rsatiladi; kiritilgan son shundan oshirilmaydi.
    """

    def __init__(self, balance: int, max_balls: int, current: int = 0, parent=None):
        super().__init__(tr("Ball ishlatish"), parent=parent)
        self.max_balls = max(0, int(max_balls))
        self.typed = str(current) if current else ""

        info = _label(
            tr("Mijozda {b} ball  ·  bu chekda {m} ball ishlatish mumkin").format(
                b=f"{balance:,}".replace(",", " "),
                m=f"{self.max_balls:,}".replace(",", " "),
            ),
            13, t.MUTED,
        )
        info.setWordWrap(True)
        info.setAlignment(Qt.AlignCenter)
        self.root.addWidget(info)

        self.display = _display("—")
        self.root.addWidget(self.display)

        full = touch_button(tr("Bor ballni to'liq ishlat"), size=16,
                            height=60, tone="soft")
        full.clicked.connect(self.use_max)
        self.root.addWidget(full)

        pad = Keypad()
        pad.digit.connect(self.on_digit)
        pad.backspace.connect(self.on_backspace)
        pad.clear.connect(self.on_clear)
        self.root.addWidget(pad)

        self.buttons(tr("QO'YISH"))
        self.refresh()

    def on_digit(self, value: str) -> None:
        if len(self.typed) + len(value) <= 9:
            self.typed = (self.typed + value).lstrip("0") or "0"
        self.refresh()

    def on_backspace(self) -> None:
        self.typed = self.typed[:-1]
        self.refresh()

    def on_clear(self) -> None:
        self.typed = ""
        self.refresh()

    def use_max(self) -> None:
        self.typed = str(self.max_balls) if self.max_balls else ""
        self.refresh()

    def refresh(self) -> None:
        b = self.balls
        self.display.setText(
            (f"{b:,}".replace(",", " ") + " " + tr("ball")) if b else "—"
        )

    @property
    def balls(self) -> int:
        """Kiritilgan ball soni — chegaradan (max_balls) oshmaydi."""
        n = int(self.typed) if self.typed.isdigit() else 0
        return min(n, self.max_balls)


# ------------------------------------------------------------------- menyu


class MenuDialog(QDialog):
    """☰ tugmasi ochadigan menyu — chapdan siljib chiqadi.

    MoySklad Kassa'dagidek: menyu o'rtada modal bo'lib emas, chap
    chetdan silliq surilib chiqadi. Qolgan joy xiralashadi; u yerga
    bosilsa menyu yana chapga siljib yopiladi.

    Klaviaturasiz kassada hamma qo'shimcha amal shu yerda: smenani
    yopish, kassaga pul kiritish-chiqarish, oraliq hisobot.
    """

    PANEL_W = 340
    #: Tanlangan amal — oyna yopilgach o'qiladi
    action: str | None = None

    def __init__(self, parent=None, title_text: str = "", subtitle: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pending_accept = False

        # Chapdagi rangli panel — menyu shu yerda
        self.panel = QWidget(self)
        self.panel.setStyleSheet(f"background: {t.ACCENT};")

        col = QVBoxLayout(self.panel)
        col.setContentsMargins(0, 10, 0, 12)
        col.setSpacing(1)

        # Tartib MoySklad Kassa menyusidagidek: avval kundalik ishlar,
        # keyin pul bilan bog'liqlari, oxirida chiqish.
        items = [
            ("park", tr("Chekni keyinga qoldirish"), False),
            ("parked", tr("Qoldirilgan cheklar"), False),
            ("history", tr("Tarix"), False),
            ("return", tr("Qaytarish"), False),
            ("report", tr("Oraliq hisobot"), False),
            ("cash_in", tr("Kassaga pul kiritish"), False),
            ("cash_out", tr("Kassadan pul chiqarish"), False),
            ("refresh", tr("Ma'lumotlarni yangilash"), False),
            ("settings", tr("Printer sozlamalari"), False),
            ("about", tr("Dastur haqida"), False),
            ("close_shift", tr("Smenani yopish"), True),
            ("quit", tr("Chiqish"), False),
        ]
        for code, text, emph in items:
            col.addWidget(self._menu_button(text, code, emph))

        # Til almashtirish — bosilsa ikkinchi tilga o'tadi (qayta ochilgach).
        # "about" dan keyin, "close_shift" dan oldin joylashadi.
        lang_label = "Til: Русский" if get_lang() == "uz" else "Язык: O'zbekcha"
        col.insertWidget(10, self._menu_button(lang_label, "language", False))

        col.addStretch(1)

        # Pastda: kim kirgan, qaysi kassa (MoySklad'dagidek)
        if title_text or subtitle:
            line = QWidget()
            line.setFixedHeight(1)
            line.setStyleSheet("background: rgba(255,255,255,0.22);")
            col.addWidget(line)

            text = "\n".join(x for x in (subtitle, title_text) if x)
            info = QLabel(text)
            info.setWordWrap(True)
            info.setStyleSheet(
                "color: rgba(255,255,255,0.92); background: transparent;"
                "padding: 12px 28px;"
            )
            f = QFont()
            f.setPixelSize(14)
            info.setFont(f)
            col.addWidget(info)

        self._done_cb = None
        self._anim = QPropertyAnimation(self.panel, b"pos", self)
        self._anim.setDuration(210)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_done)

    def _menu_button(self, text: str, code: str, emphasized: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(52)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        f = QFont()
        f.setPixelSize(16)
        f.setBold(emphasized)
        btn.setFont(f)

        # Lucide uslubidagi SVG ikona — matn rangiga mos.
        ico_name = icons.MENU_ICON.get(code)
        if ico_name:
            ico_color = t.ACCENT if emphasized else "#FFFFFF"
            btn.setIcon(icons.icon(ico_name, 20, ico_color))
            btn.setIconSize(icons.button_icon_size(20))

        if emphasized:
            btn.setStyleSheet(
                f"QPushButton {{ background:#FFFFFF; color:{t.ACCENT};"
                f" border:none; text-align:left; padding:0 24px;"
                f" icon-size:20px; }}"
                f"QPushButton:pressed {{ background:{t.ACCENT_PALE}; }}"
                f"QPushButton:disabled {{ color:{t.ACCENT_SOFT}; }}"
            )
        else:
            btn.setStyleSheet(
                "QPushButton { background:transparent; color:#FFFFFF;"
                " border:none; text-align:left; padding:0 24px; icon-size:20px; }"
                "QPushButton:hover { background:rgba(255,255,255,0.10); }"
                "QPushButton:pressed { background:rgba(255,255,255,0.20); }"
                "QPushButton:disabled { color:rgba(255,255,255,0.38); }"
            )
        btn.clicked.connect(lambda _=False, c=code: self.pick(c))
        return btn

    # ------------------------------------------------------ joylashuv

    def _fit_parent(self) -> None:
        p = self.parentWidget()
        if p:
            top_left = p.mapToGlobal(QPoint(0, 0))
            self.setGeometry(top_left.x(), top_left.y(), p.width(), p.height())

    def paintEvent(self, event) -> None:
        # Qolgan joyni xiralashtiramiz — diqqat menyuga qaratilsin
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 21, 23, 97))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.panel.resize(self.PANEL_W, self.height())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_parent()
        self.panel.resize(self.PANEL_W, self.height())
        self.panel.move(-self.PANEL_W, 0)
        self._start(QPoint(-self.PANEL_W, 0), QPoint(0, 0), None)

    # -------------------------------------------------------- yopish

    def mousePressEvent(self, event) -> None:
        # Paneldan o'ngga bosilsa — yopamiz
        if event.position().x() > self.PANEL_W:
            self._slide_out(False)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self._slide_out(False)
        else:
            super().keyPressEvent(event)

    def pick(self, code: str) -> None:
        self.action = code
        self._slide_out(True)

    def _slide_out(self, accept: bool) -> None:
        self._pending_accept = accept
        self._start(self.panel.pos(), QPoint(-self.PANEL_W, 0), self._finish)

    def _finish(self) -> None:
        self.accept() if self._pending_accept else self.reject()

    def _on_anim_done(self) -> None:
        cb, self._done_cb = self._done_cb, None
        if cb:
            cb()

    def _start(self, start: QPoint, end: QPoint, on_done) -> None:
        self._anim.stop()
        self._done_cb = on_done
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()


class PrinterSettingsDialog(BaseDialog):
    """Printer sozlamalari — MoySklad Kassa'dagi «Работа кассы» kabi.

    Kassir shu yerda: printerni tanlaydi, qog'oz o'lchamini belgilaydi,
    avto-chekni yoqadi/o'chiradi va test chek chiqarib ko'radi.
    """

    def __init__(self, printers: list[str], current: str = "",
                 paper: str = "80", auto_print: bool = True,
                 on_test=None, parent=None):
        super().__init__(tr("Printer sozlamalari"), width=560, parent=parent)
        self._on_test = on_test

        combo_css = (
            f"QComboBox {{ background:{t.BG}; color:{t.INK};"
            f" border:2px solid {t.ACCENT}; border-radius:10px;"
            f" padding:10px 14px; font-size:17px; min-height:34px; }}"
            f"QComboBox::drop-down {{ width:38px; border:none; }}"
            f"QComboBox QAbstractItemView {{ background:{t.BG}; color:{t.INK};"
            f" selection-background-color:{t.ACCENT_PALE};"
            f" selection-color:{t.INK}; font-size:17px; outline:none; }}"
        )

        # --- Printer ---
        self.root.addWidget(_label(tr("Printer"), 15, t.MUTED))
        self.printer_combo = QComboBox()
        self.printer_combo.setStyleSheet(combo_css)
        self.printer_combo.setMinimumHeight(58)
        if printers:
            self.printer_combo.addItems(printers)
            if current and current in printers:
                self.printer_combo.setCurrentText(current)
        else:
            self.printer_combo.addItem(tr("Printer topilmadi"))
            self.printer_combo.setEnabled(False)
        self.root.addWidget(self.printer_combo)

        # --- Qog'oz o'lchami ---
        self.root.addWidget(_label(tr("Qog'oz o'lchami"), 15, t.MUTED))
        self.paper_combo = QComboBox()
        self.paper_combo.setStyleSheet(combo_css)
        self.paper_combo.setMinimumHeight(58)
        self.paper_combo.addItem(tr("Lenta — 80mm"), "80")
        self.paper_combo.addItem(tr("Lenta — 58mm"), "58")
        self.paper_combo.setCurrentIndex(1 if str(paper) == "58" else 0)
        self.root.addWidget(self.paper_combo)

        # --- Avto-chek ---
        self.auto_check = QCheckBox(tr("Har savdodan keyin chekni avtomatik chiqarish"))
        self.auto_check.setChecked(bool(auto_print))
        self.auto_check.setCursor(Qt.PointingHandCursor)
        self.auto_check.setStyleSheet(
            f"QCheckBox {{ color:{t.INK}; font-size:16px; padding:10px 2px; }}"
            f"QCheckBox::indicator {{ width:26px; height:26px; }}"
        )
        self.root.addWidget(self.auto_check)

        # --- Test chek ---
        test_btn = touch_button(tr("Test chek chiqarish"), size=17, height=62, tone="soft")
        test_btn.clicked.connect(self._test)
        self.root.addWidget(test_btn)

        self.buttons(tr("SAQLASH"))

    def _test(self) -> None:
        if callable(self._on_test):
            self._on_test(self.printer_name, self.paper)

    @property
    def printer_name(self) -> str:
        if not self.printer_combo.isEnabled():
            return ""
        return self.printer_combo.currentText()

    @property
    def paper(self) -> str:
        return self.paper_combo.currentData() or "80"

    @property
    def auto_print(self) -> bool:
        return self.auto_check.isChecked()


class CashDialog(NumberDialog):
    """Kassaga pul kiritish yoki undan chiqarish."""

    def __init__(self, kind: str, parent=None):
        title = tr("Kassaga pul kiritish") if kind == "in" else tr("Kassadan pul chiqarish")
        hint = (tr("Razmen yoki qo'shimcha pul") if kind == "in"
                else tr("Inkassatsiya yoki xarajat"))
        super().__init__(title, hint=hint, ok_text=tr("TASDIQLASH"), parent=parent)
        self.kind = kind


class PickDialog(BaseDialog):
    """Ro'yxatdan bittasini tanlash — qoldirilgan cheklar, tarix.

    Har qatorda uchta narsa: nima, qachon, qancha. Kassir shu uchtasi
    bo'yicha kerakli chekni topadi.
    """

    def __init__(self, title: str, rows: list[tuple[str, object]],
                 empty_text: str = "Bo'sh", pick_text: str = tr("TANLASH"),
                 parent=None):
        super().__init__(title, width=600, parent=parent)
        self.chosen = None

        self.list = QListWidget()
        self.list.setMinimumHeight(360)
        self.list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {t.LINE}; border-radius: 10px;"
            f" background: {t.BG}; font-size: 16px; }}"
            f"QListWidget::item {{ padding: 18px 16px;"
            f" border-bottom: 1px solid {t.LINE}; color: {t.INK}; }}"
            f"QListWidget::item:selected {{ background: {t.ACCENT_PALE};"
            f" color: {t.INK}; }}"
        )
        for text, data in rows:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, data)
            self.list.addItem(item)
        self.root.addWidget(self.list)

        if not rows:
            note = _label(empty_text, 15, t.MUTED)
            note.setAlignment(Qt.AlignCenter)
            self.root.addWidget(note)

        self.list.itemClicked.connect(self._pick)
        self.buttons(pick_text, self._pick_current)

    def _pick(self, item: QListWidgetItem) -> None:
        self.chosen = item.data(Qt.UserRole)

    def _pick_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self.chosen = item.data(Qt.UserRole)
            self.accept()


class HistoryDialog(BaseDialog):
    """Tarix — shu smenadagi cheklar. Chek raqami bo'yicha qidiriladi.

    Har qatorда: chek raqami (SK-…), vaqti, summasi va holati (yuborildi/
    navbatда/bekor). Yuqorida raqamli klaviatura — kassir chek raqamini
    tersa, ro'yxat shu zahoti filtrlanadi.
    """

    def __init__(self, rows: list[dict], shift_caption: str = "",
                 on_reprint=None, parent=None):
        super().__init__(tr("Tarix"), width=620, parent=parent)
        self._rows = rows
        self._query = ""
        self._on_reprint = on_reprint

        if shift_caption:
            cap = _label(shift_caption, 14, t.MUTED)
            cap.setAlignment(Qt.AlignCenter)
            self.root.addWidget(cap)

        hint = _label(tr("Chek raqami bo'yicha qidirish"), 13, t.FAINT)
        hint.setAlignment(Qt.AlignCenter)
        self.root.addWidget(hint)

        self.search = _display("")
        self.root.addWidget(self.search)

        self.list = QListWidget()
        self.list.setMinimumHeight(300)
        self.list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {t.LINE}; border-radius: 10px;"
            f" background: {t.BG}; font-size: 15px; }}"
            f"QListWidget::item {{ padding: 14px 16px;"
            f" border-bottom: 1px solid {t.LINE}; color: {t.INK}; }}"
        )
        self.root.addWidget(self.list)

        self.empty = _label("", 14, t.MUTED)
        self.empty.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.empty)

        pad = Keypad(with_zeros=False)
        pad.digit.connect(self._type)
        pad.backspace.connect(self._back)
        pad.clear.connect(self._clear)
        self.root.addWidget(pad)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.reprint = touch_button(tr("Qayta chop etish"), size=17, height=64, tone="primary")
        self.reprint.setEnabled(False)
        self.reprint.clicked.connect(self._reprint_current)
        self.list.currentItemChanged.connect(
            lambda current, _previous: self.reprint.setEnabled(current is not None)
        )
        actions.addWidget(self.reprint)
        close = touch_button(tr("Yopish"), size=18, height=64, tone="soft")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        self.root.addLayout(actions)

        self._refresh()

    def _type(self, d: str) -> None:
        self._query += d
        self._refresh()

    def _back(self) -> None:
        self._query = self._query[:-1]
        self._refresh()

    def _clear(self) -> None:
        self._query = ""
        self._refresh()

    def _reprint_current(self) -> None:
        item = self.list.currentItem()
        if item is not None and self._on_reprint:
            self._on_reprint(item.data(Qt.UserRole))

    def _refresh(self) -> None:
        # Qidiruv maydoni: terilgan raqam yoki bo'sh belgi
        self.search.setText(self._query or "—")
        self.list.clear()
        q = self._query
        shown = 0
        for r in self._rows:
            no = r.get("check_no")
            # Raqam terilgan bo'lsa — faqat mos chek raqamlari
            if q and q not in str(r.get("receipt_number") or no or ""):
                continue
            no_txt = r.get("receipt_number") or (f"SK-{no}" if no is not None else "—")
            pref = "↩ " if r.get("is_return") else ""
            text = (
                f"{pref}№ {no_txt}    ·    {r.get('time', '')}"
                f"    ·    {r.get('total_text', '')} so'm    ·    {r.get('state', '')}"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, r)
            if r.get("is_return"):
                item.setForeground(_color(t.DANGER))
            self.list.addItem(item)
            shown += 1

        if shown == 0:
            self.empty.setText(
                tr("Bu raqamli chek topilmadi") if q else tr("Hali chek yo'q")
            )
        else:
            self.empty.setText("")


class LoginDialog(BaseDialog):
    """Kassaga kirish: kim va PIN.

    Ismlar tugma bo'lib turadi — sensorli ekranda login terish sekin,
    va kassir har smenada shu ishni qiladi. PIN baribir so'raladi,
    shuning uchun ismni ko'rsatish himoyani kamaytirmaydi.

    PIN yulduzcha bilan ko'rsatiladi: kassa yonida mijoz turadi.
    """

    def __init__(self, cashiers: list[dict], parent=None):
        super().__init__(tr("Kassaga kirish"), width=560, parent=parent)
        self.cashiers = cashiers
        self.chosen: dict | None = None
        self.pin = ""
        self.error = ""

        self.who = _label(tr("Kassirni tanlang"), 16, t.MUTED)
        self.who.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.who)

        if cashiers:
            grid = QGridLayout()
            grid.setSpacing(8)
            self.buttons_by_login = {}
            for i, c in enumerate(cashiers[:8]):
                btn = touch_button(c["name"], size=15, height=62, tone="soft")
                btn.clicked.connect(lambda _=False, cc=c: self.choose(cc))
                grid.addWidget(btn, i // 2, i % 2)
                self.buttons_by_login[c["login"]] = btn
            self.root.addLayout(grid)
        else:
            note = _label(
                "Kassir qo'shilmagan.\n"
                "Panelga kiring: Kassirlar → Yangi kassir.",
                14, t.WARN,
            )
            note.setWordWrap(True)
            note.setAlignment(Qt.AlignCenter)
            self.root.addWidget(note)

        self.pin_display = _display("", size=34)
        self.pin_display.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.pin_display)

        self.hint = _label("", 13, t.DANGER)
        self.hint.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.hint)

        pad = Keypad(with_zeros=False)
        pad.digit.connect(self.on_digit)
        pad.backspace.connect(self.on_backspace)
        pad.clear.connect(self.on_clear)
        self.root.addWidget(pad)

        row = QHBoxLayout()
        row.setSpacing(10)
        quit_btn = touch_button(tr("Chiqish"), size=16, height=68, tone="soft")
        quit_btn.clicked.connect(self.reject)
        self.enter = touch_button(tr("KIRISH"), size=18, height=68, tone="accent")
        self.enter.clicked.connect(self.accept)
        row.addWidget(quit_btn, 2)
        row.addWidget(self.enter, 3)
        self.root.addLayout(row)

        self.refresh()

    def choose(self, cashier: dict) -> None:
        self.chosen = cashier
        self.pin = ""
        self.error = ""
        self.refresh()

    def on_digit(self, value: str) -> None:
        if len(self.pin) < 6:
            self.pin += value
        self.error = ""
        self.refresh()

    def on_backspace(self) -> None:
        self.pin = self.pin[:-1]
        self.refresh()

    def on_clear(self) -> None:
        self.pin = ""
        self.refresh()

    def show_error(self, text: str) -> None:
        """Xato bo'lsa PIN tozalanadi — qayta terish kerak."""
        self.error = text
        self.pin = ""
        self.refresh()

    def refresh(self) -> None:
        self.who.setText(
            self.chosen["name"] if self.chosen else tr("Kassirni tanlang")
        )
        self.who.setStyleSheet(
            f"color: {t.INK if self.chosen else t.MUTED};"
            f"background: transparent; border: none;"
        )
        self.pin_display.setText("●" * len(self.pin) if self.pin else "PIN")
        self.hint.setText(self.error)
        self.enter.setEnabled(bool(self.chosen) and len(self.pin) >= 4)


# --------------------------------------------------------------- ulanish


def _available_screen_height() -> int:
    """Ekranning bo'sh qismi (vazifalar paneli chiqarilgan), mantiqiy px.
    Ekran aniqlanmasa — katta deb olinadi (oddiy rejim)."""
    try:
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry().height() if screen else 10_000
    except Exception:  # noqa: BLE001
        return 10_000


def _fit_to_screen(dialog) -> None:
    try:
        from PySide6.QtGui import QGuiApplication
        screen = dialog.screen() or QGuiApplication.primaryScreen()
        if not screen:
            return
        area = screen.availableGeometry()
        dialog.setMaximumHeight(area.height())
        w = min(dialog.width(), area.width())
        h = min(dialog.height(), area.height())
        dialog.resize(w, h)
        dialog.move(area.x() + (area.width() - w) // 2,
                    area.y() + max(0, (area.height() - h) // 2))
    except Exception:  # noqa: BLE001
        pass


class SetupDialog(BaseDialog):
    """Kassani ulash — faqat login va parol, ekran klaviaturasi bilan.

    Server manzili so'ralmaydi: u dasturning ichida (config.DEFAULT_SERVER).
    Xodim paneldan olingan kassa login-parolini yozadi — bo'ldi.
    «Ulash» bosilganda darhol tekshiriladi — xato bo'lsa aynan nima
    xatoligi ko'rinadi.
    """

    LABELS = {
        "login": tr("Kassa logini"),
        "parol": tr("Kassa paroli"),
    }

    #: Shu balandlikdan (mantiqiy piksel, ekranning bo'sh qismi) kichik
    #: ekranda ixcham rejim: kichik ekran / Windows masshtabi 125–150% da
    #: oyna ekrandan uzun chiqib, ULASH tugmasi pastga tushib ketardi
    #: (2026-09-17, egasining skrinshoti).
    COMPACT_BELOW = 800

    def __init__(self, server_url: str, connect_fn, parent=None,
                 screen_height: int | None = None):
        super().__init__(tr("Kassani ulash"), width=700, parent=parent)
        self.connect_fn = connect_fn
        self.result: dict | None = None
        from ..config import DEFAULT_SERVER

        if screen_height is None:
            screen_height = _available_screen_height()
        self.compact = screen_height < self.COMPACT_BELOW
        if self.compact:
            self.root.setContentsMargins(16, 12, 16, 12)
            self.root.setSpacing(8)

        self.values = {
            "server": server_url or DEFAULT_SERVER,
            "login": "",
            "parol": "",
        }
        self.active = "login"

        note = _label(
            tr("Login va parolni paneldan olasiz: Kassalar bo'limi."),
            13, t.MUTED,
        )
        note.setAlignment(Qt.AlignCenter)
        self.root.addWidget(note)

        self.rows: dict[str, object] = {}
        for key in ("login", "parol"):
            btn = touch_button("", size=16, height=46 if self.compact else 58, tone="soft")
            btn.clicked.connect(lambda _=False, k=key: self.select(k))
            self.rows[key] = btn
            self.root.addWidget(btn)

        self.hint = _label("", 14, t.DANGER)
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignCenter)
        self.root.addWidget(self.hint)

        keyboard = FullKeyboard(key_height=38 if self.compact else 50)
        keyboard.key.connect(self.on_key)
        keyboard.backspace.connect(self.on_backspace)
        self.root.addWidget(keyboard)

        self.buttons(tr("ULASH"), self._try, height=54 if self.compact else 68)
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        """Oyna har doim ekran ichida: balandligi ekrandan oshmaydi va
        markazga qo'yiladi — ULASH tugmasi doim ko'rinadi."""
        super().showEvent(event)
        _fit_to_screen(self)

    def select(self, key: str) -> None:
        self.active = key
        self.refresh()

    def on_key(self, ch: str) -> None:
        self.values[self.active] += ch
        self.refresh()

    def on_backspace(self) -> None:
        self.values[self.active] = self.values[self.active][:-1]
        self.refresh()

    def _style_row(self, active: bool) -> str:
        if active:
            bg, fg, border, w = t.ACCENT_PALE, t.INK, t.ACCENT, "2px"
        else:
            bg, fg, border, w = t.BG_SOFT, t.INK_SOFT, t.LINE_STRONG, "1.5px"
        return (
            f"QPushButton {{ background:{bg}; color:{fg};"
            f" border:{w} solid {border}; border-radius:10px;"
            f" text-align:left; padding-left:16px; }}"
        )

    def refresh(self) -> None:
        for key, btn in self.rows.items():
            val = self.values[key]
            shown = ("●" * len(val)) if key == "parol" else val
            arrow = "▸  " if key == self.active else "    "
            btn.setText(f"{arrow}{self.LABELS[key]}:   {shown or '—'}")
            btn.setStyleSheet(self._style_row(key == self.active))

    def _try(self) -> None:
        url = self.values["server"].strip()
        login = self.values["login"].strip()
        parol = self.values["parol"].strip()

        if not (url and login and parol):
            self.hint.setStyleSheet(
                f"color:{t.DANGER}; background:transparent; border:none;"
            )
            self.hint.setText(tr("Login va parolni to'ldiring."))
            return

        self.hint.setStyleSheet(
            f"color:{t.MUTED}; background:transparent; border:none;"
        )
        self.hint.setText(tr("Ulanmoqda…"))
        QApplication.processEvents()

        try:
            self.result = self.connect_fn(url, login, parol)
        except Exception as e:
            self.hint.setStyleSheet(
                f"color:{t.DANGER}; background:transparent; border:none;"
            )
            self.hint.setText(str(e))
            return

        self.values["server"] = url
        self.accept()

    @property
    def server_url(self) -> str:
        return self.values["server"].strip()


# ------------------------------------------------------------- qaytarish


class ReturnSaleListDialog(BaseDialog):
    """Qaytarish — savdoni tanlash.

    MoySklad'dagidek: qidiruv + smena bo'yicha guruhlangan savdolar.
    Chek raqami, tovar nomi yoki summa bo'yicha qidiriladi.
    """

    def __init__(self, sales: list[dict], parent=None, search_fn=None):
        super().__init__(tr("Qaytarish"), width=680, parent=parent)
        self.sales = sales
        self.search_fn = search_fn
        self.query = QLineEdit()
        self.query.setPlaceholderText("Chek raqami yoki mijoz ismi")
        self.query.setMinimumHeight(48)
        self.root.addWidget(self.query)
        find = touch_button("QIDIRISH", size=16, height=48, tone="soft")
        find.clicked.connect(lambda: self._search(False))
        self.query.returnPressed.connect(lambda: self._search(False))
        self.root.addWidget(find)
        self.chosen: dict | None = None

        sub = _label(tr("Qaytariladigan savdoni tanlang"), 14, t.MUTED)
        sub.setAlignment(Qt.AlignCenter)
        self.root.addWidget(sub)

        self.list = QListWidget()
        self.list.setMinimumHeight(320)
        self.list.setStyleSheet(
            f"QListWidget {{ border: 1px solid {t.LINE}; border-radius: 10px;"
            f" background: {t.BG}; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {t.LINE}; }}"
            f"QListWidget::item:selected {{ background: {t.ACCENT_PALE}; }}"
        )
        self.list.itemClicked.connect(self._pick)
        self.root.addWidget(self.list)

        close = touch_button(tr("Yopish"), size=16, height=64, tone="soft")
        close.clicked.connect(self.reject)
        self.root.addWidget(close)

        self.more = touch_button("KEYINGI CHEKLAR", size=16, height=48, tone="soft")
        self.more.clicked.connect(lambda: self._search(True))
        self.more.setVisible(bool(search_fn) and len(sales) == 40)
        self.root.addWidget(self.more)
        self.refresh()

    def _search(self, more=False):
        if not self.search_fn:
            return
        from PySide6.QtWidgets import QMessageBox
        try:
            rows = self.search_fn(self.query.text().strip(), len(self.sales) if more else 0)
        except Exception as exc:
            QMessageBox.warning(self, "Qidiruv", str(exc))
            return
        self.sales = self.sales + rows if more else rows
        self.more.setVisible(len(rows) == 40)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()

        last_shift = None
        for sale in self.sales:
            # Smena sarlavhasi — yangi smena boshlanganda
            sh = sale["shift"]
            key = sh["number"]
            if key != last_shift:
                last_shift = key
                head = QListWidgetItem(
                    f"  Smena #{sh['number']}"
                    + ("  ·  yopilgan" if sh["closed"] else "  ·  ochiq")
                )
                head.setFlags(Qt.NoItemFlags)
                f = QFont(); f.setPixelSize(12); f.setBold(True)
                head.setFont(f)
                head.setForeground(_color(t.FAINT))
                self.list.addItem(head)

            widget = self._sale_row(sale)
            item = QListWidgetItem()
            hint = widget.minimumSizeHint()
            hint.setHeight(max(64, hint.height()))
            item.setSizeHint(hint)
            item.setData(Qt.UserRole, sale)
            self.list.addItem(item)
            self.list.setItemWidget(item, widget)

    def _sale_row(self, sale: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        w.setMinimumHeight(56)
        row = QHBoxLayout(w)
        row.setContentsMargins(16, 8, 20, 8)
        row.setSpacing(12)

        time = sale["created_at"][11:16]
        row.addWidget(_label(time, 14, t.MUTED))

        mid = QVBoxLayout()
        mid.setSpacing(1)
        mid.addWidget(_label(f"Chek {sale.get('receipt_number') or sale['number']}", 15, t.INK))
        if sale["customer"]:
            mid.addWidget(_label(sale["customer"], 12.5, t.MUTED))
        row.addLayout(mid, 1)

        # Naqd/karta belgisi
        mark = "naqd" if sale["is_cash"] else "karta"
        row.addWidget(_label(mark, 12.5, t.FAINT))

        value = _label(som(sale["net_total"]), 15, t.INK, bold=True)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setMinimumWidth(110)
        row.addWidget(value)
        return w

    def _pick(self, item: QListWidgetItem) -> None:
        sale = item.data(Qt.UserRole)
        if sale:
            self.chosen = sale
            self.accept()


class ReturnDetailDialog(BaseDialog):
    """Savdo cheki — «Qaytarish yaratish» tugmasi bilan."""

    def __init__(self, sale: dict, parent=None):
        super().__init__(f"Chek {sale.get('receipt_number') or sale['number']}", width=520, parent=parent)
        self.sale = sale

        when = _label(sale["created_at"][:16].replace("T", "  "), 13, t.MUTED)
        when.setAlignment(Qt.AlignCenter)
        self.root.addWidget(when)

        box = QListWidget()
        box.setMinimumHeight(300)
        box.setStyleSheet(
            f"QListWidget {{ border: 1px solid {t.LINE}; border-radius: 10px;"
            f" background: {t.BG_SOFT}; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {t.LINE}; }}"
        )
        for it in sale["items"]:
            w = QWidget()
            w.setStyleSheet("background: transparent; border: none;")
            r = QHBoxLayout(w)
            r.setContentsMargins(14, 8, 16, 8)
            left = QVBoxLayout(); left.setSpacing(1)
            left.addWidget(_label(it["name"], 14.5, t.INK))
            left.addWidget(_label(
                f"{it['sold_qty']} × {som(it['price'])}", 12.5, t.MUTED))
            r.addLayout(left, 1)
            total = int(it["refund_total"]) if "refund_total" in it else int(round(it["price"] * float(it["sold_qty"])))
            v = _label(som(total), 14.5, t.INK, bold=True)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            r.addWidget(v)
            item = QListWidgetItem(); item.setSizeHint(w.minimumSizeHint())
            box.addItem(item); box.setItemWidget(item, w)
        self.root.addWidget(box)

        total = _label(f"Jami: {som(sale['net_total'])} so'm", 16, t.INK, bold=True)
        total.setAlignment(Qt.AlignRight)
        self.root.addWidget(total)

        self.buttons(tr("QAYTARISH YARATISH"))


class ReturnItemsDialog(BaseDialog):
    """Qaysi tovar, nechta qaytishini belgilash.

    Har qator: nom, sotilgani, miqdor +/−, qator summasi. Pastda teal
    rangda «Qaytariladi». Boshida hammasi to'liq belgilanadi — kassir
    kerak bo'lmaganini kamaytiradi.

    Vaznli tovar: +/− bilan bo'linmaydi (0 yoki to'liq). Sabab — sensorli
    ekranda kasr kg terish qiyin, va qaytarishda odatda butun paket qaytadi.
    """

    def __init__(self, sale: dict, parent=None, local_returned: dict | None = None):
        super().__init__(tr("Qaytarish"), width=760, parent=parent)
        self.sale = sale
        self.rows: list[dict] = []
        # Navbatда turgan (serverга hali yetmagan) qaytarishlar — server
        # bilmaydi, lekin pul berilgan. Ularni ham ayiramiz, aks holda bir
        # tovar ikki marta qaytarilib, server rad etardi.
        local_returned = local_returned or {}

        for it in sale["items"]:
            sold = Decimal(str(it["sold_qty"]))
            already = Decimal(str(it.get("returned_qty") or 0))
            key = it.get("ms_product_id") or it.get("name")
            already += Decimal(str(local_returned.get(key, 0)))
            can = max(sold - already, 0)
            if can <= 0:
                continue  # bu qator to'liq qaytarilgan
            self.rows.append({"item": it, "can": can,
                              "qty": can, "is_weight": it.get("is_weight")})

        self.list = QListWidget()
        self.list.setMinimumHeight(360)
        self.list.setStyleSheet(
            f"QListWidget {{ border: none; background: {t.BG}; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {t.LINE}; }}"
        )
        self.root.addWidget(self.list)

        # Pastdagi teal qator
        self.bar = QLabel()
        self.bar.setFixedHeight(60)
        self.bar.setAlignment(Qt.AlignCenter)
        f = QFont(); f.setPixelSize(20); f.setBold(True); self.bar.setFont(f)
        self.bar.setStyleSheet(
            f"background: {t.ACCENT}; color: #fff; border-radius: 10px;"
        )
        self.root.addWidget(self.bar)

        self.buttons(tr("QAYTARISH"), self._accept)
        self._build_rows()
        self.refresh()

    def _build_rows(self) -> None:
        self.list.clear()
        for idx, row in enumerate(self.rows):
            self._item_row(idx, row)

    def _item_row(self, idx: int, row: dict) -> None:
        it = row["item"]
        w = QWidget()
        w.setStyleSheet("background: transparent; border: none;")
        w.setMinimumHeight(64)
        r = QHBoxLayout(w)
        r.setContentsMargins(14, 8, 16, 8)
        r.setSpacing(12)

        left = QVBoxLayout(); left.setSpacing(1)
        left.addWidget(_label(it["name"], 14.5, t.INK))
        left.addWidget(_label(
            f"sotildi: {row['can']:g}", 12.5, t.OK))
        r.addLayout(left, 1)

        minus = touch_button("−", size=22, height=48, tone="soft")
        minus.setFixedWidth(52)
        minus.clicked.connect(lambda _=False, i=idx: self._step(i, -1))
        r.addWidget(minus)

        qty_lbl = _label("", 17, t.INK, bold=True)
        qty_lbl.setAlignment(Qt.AlignCenter)
        qty_lbl.setFixedWidth(64)
        row["_qty_lbl"] = qty_lbl
        r.addWidget(qty_lbl)

        plus = touch_button("+", size=22, height=48, tone="soft")
        plus.setFixedWidth(52)
        plus.clicked.connect(lambda _=False, i=idx: self._step(i, +1))
        r.addWidget(plus)

        total_lbl = _label("", 15, t.INK, bold=True)
        total_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        total_lbl.setMinimumWidth(110)
        row["_total_lbl"] = total_lbl
        r.addWidget(total_lbl)

        item = QListWidgetItem()
        item.setSizeHint(w.minimumSizeHint())
        self.list.addItem(item)
        self.list.setItemWidget(item, w)

    def _step(self, idx: int, direction: int) -> None:
        row = self.rows[idx]
        if row["is_weight"]:
            # 0 yoki to'liq
            row["qty"] = 0 if row["qty"] > 0 else row["can"]
        else:
            row["qty"] = max(0, min(row["can"], row["qty"] + direction))
        self.refresh()

    def refresh(self) -> None:
        total = 0
        for row in self.rows:
            it = row["item"]
            line = refund_total(it, row["qty"])
            total += line
            row["_qty_lbl"].setText(f"{row['qty']:g}")
            row["_total_lbl"].setText(som(line) if row["qty"] else "0")
            row["_total_lbl"].setStyleSheet(
                f"color: {t.INK if row['qty'] else t.FAINT};"
                f"background: transparent; border: none;"
            )
        self.total = total
        self.bar.setText(f"Qaytariladi:  {som(total)} so'm")

    def _accept(self) -> None:
        if self.lines:
            self.accept()

    @property
    def lines(self) -> list[dict]:
        return [{"item": r["item"], "qty": r["qty"]}
                for r in self.rows if r["qty"] > 0]


class RefundMethodDialog(BaseDialog):
    """Pulni qanday qaytaramiz — naqd yoki karta."""

    def __init__(self, total: int, methods: list[dict], parent=None):
        super().__init__(tr("Pulni qaytarish"), width=460, parent=parent)
        self.method: str | None = None

        big = _label(f"{som(total)} so'm", 30, t.ACCENT, bold=True)
        big.setAlignment(Qt.AlignCenter)
        self.root.addWidget(big)

        note = _label(tr("Mijozga qanday qaytariladi?"), 14, t.MUTED)
        note.setAlignment(Qt.AlignCenter)
        self.root.addWidget(note)

        for m in methods:
            btn = touch_button(m["name"], size=17, height=72,
                               tone="accent" if m.get("is_cash") else "soft")
            btn.clicked.connect(lambda _=False, c=m["code"]: self._pick(c))
            self.root.addWidget(btn)

        cancel = touch_button(tr("Bekor"), size=16, height=60, tone="soft")
        cancel.clicked.connect(self.reject)
        self.root.addWidget(cancel)

    def _pick(self, code: str) -> None:
        self.method = code
        self.accept()


class ReturnDoneDialog(BaseDialog):
    """«Возврат завершен» — muvaffaqiyat."""

    def __init__(self, amount: int, parent=None):
        super().__init__(tr("Qaytarildi"), width=460, parent=parent)

        check = _label("✓", 56, t.OK, bold=True)
        check.setAlignment(Qt.AlignCenter)
        self.root.addWidget(check)

        msg = _label(f"{som(amount)} so'm qaytarildi", 18, t.INK, bold=True)
        msg.setAlignment(Qt.AlignCenter)
        self.root.addWidget(msg)

        ok = touch_button(tr("TAYYOR"), size=18, height=72, tone="accent")
        ok.clicked.connect(self.accept)
        self.root.addWidget(ok)


def _color(hexstr: str):
    from PySide6.QtGui import QColor
    return QColor(hexstr)
