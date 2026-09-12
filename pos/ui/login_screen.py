"""
Kirish ekrani — kassa ochilganda va «Chiqish» dan keyin ko'rinadigan sahifa.

Xodim o'z **login va parolini** teradi. Kassirlar ro'yxati ko'rsatilmaydi:
begona odam kassa yonida tursa ham, kim ishlashini ham, qanday kirishni
ham bilmaydi. Login-parolni do'kon boshqaruvchisi paneldan beradi
(Kassirlar bo'limi).

Dastur bu ekranda yopilmaydi — kassir chiqadi, ekran qoladi, keyingi
kassir kiradi (MoySklad Kassa'dagidek). Dasturni butunlay yopish — shu
ekrandagi «Dasturni yopish».

Bu asosiy oynaning ustidagi to'liq qatlam (child widget), alohida oyna
emas: kirish/chiqish — shunchaki qatlamni ko'rsatish/yashirish.

Ko'rinish haqida: klaviatura shu yerda o'z qo'limiz bilan yig'ilgan
(`_Keyboard`), umumiy `FullKeyboard` emas. Sabab — Qt'da har tugmaning
o'z uslubi ota-uslubdan ustun turadi, ya'ni tashqaridan chiroyli qilib
bo'lmaydi. Kirish ekrani kassirning kuniga birinchi ko'radigan ekrani,
shuning uchun u alohida ishlangan.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..version import VERSION
from . import theme as t

# Klaviatura tugmasi: to'q sirt, yupqa chegara, bosilganda zumrad tus
_KEY_QSS = f"""
QPushButton {{
    background: {t.BG};
    color: {t.INK};
    border: 1px solid {t.LINE};
    border-radius: 10px;
    font-size: 17px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {t.LINE_STRONG}; }}
QPushButton:pressed {{ background: {t.ACCENT_PALE}; border-color: {t.ACCENT}; }}
"""

_KEY_SOFT_QSS = f"""
QPushButton {{
    background: {t.BG_SOFT};
    color: {t.INK_SOFT};
    border: 1px solid {t.LINE};
    border-radius: 10px;
    font-size: 17px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {t.LINE_STRONG}; }}
QPushButton:pressed {{ background: {t.ACCENT_PALE}; border-color: {t.ACCENT}; }}
"""


def _text(text: str, size: int, color: str, bold: bool = False,
          spacing: float = 0.0) -> QLabel:
    lbl = QLabel(text)
    weight = "600" if bold else "400"
    ls = f"letter-spacing:{spacing}px;" if spacing else ""
    lbl.setStyleSheet(
        f"QLabel {{ color:{color}; background:transparent; border:none;"
        f" font-size:{size}px; font-weight:{weight}; {ls} }}"
    )
    return lbl


class _Keyboard(QWidget):
    """Barmoq bilan yoziladigan klaviatura — harf, raqam va belgilar."""

    key = Signal(str)
    backspace = Signal()

    ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
    SYMBOLS = ".-_@"

    KEY_H = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QWidget { background: transparent; }")
        self._upper = False
        self._letters: list[QPushButton] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(7)

        for line in self.ROWS:
            row = QHBoxLayout()
            row.setSpacing(7)
            # «asdf» va «zxcv» qatorlari haqiqiy klaviaturadagidek surilgan
            if line.startswith("a"):
                row.addSpacing(18)
            elif line.startswith("z"):
                row.addSpacing(52)
            for ch in line:
                btn = self._key(ch)
                if ch.isalpha():
                    self._letters.append(btn)
                row.addWidget(btn)
            if line.startswith("a"):
                row.addSpacing(18)
            elif line.startswith("z"):
                row.addSpacing(52)
            col.addLayout(row)

        bottom = QHBoxLayout()
        bottom.setSpacing(7)
        self._shift = self._key("⇧", soft=True)
        self._shift.clicked.disconnect()
        self._shift.clicked.connect(self._toggle_shift)
        bottom.addWidget(self._shift, 3)
        for ch in self.SYMBOLS:
            bottom.addWidget(self._key(ch, soft=True), 2)
        back = self._key("←", soft=True)
        back.clicked.disconnect()
        back.clicked.connect(self.backspace.emit)
        bottom.addWidget(back, 3)
        col.addLayout(bottom)

    def _key(self, ch: str, soft: bool = False) -> QPushButton:
        btn = QPushButton(ch)
        btn.setFixedHeight(self.KEY_H)
        btn.setMinimumWidth(40)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setStyleSheet(_KEY_SOFT_QSS if soft else _KEY_QSS)
        btn.clicked.connect(lambda _=False, b=btn: self.key.emit(b.text()))
        return btn

    def _toggle_shift(self) -> None:
        self._upper = not self._upper
        for b in self._letters:
            b.setText(b.text().upper() if self._upper else b.text().lower())
        self._shift.setStyleSheet(
            _KEY_QSS.replace(t.BG, t.ACCENT_PALE) if self._upper
            else _KEY_SOFT_QSS
        )


class _Field(QFrame):
    """Kiritish maydoni: tepada yorliq, ichida qiymat va kursor."""

    clicked = Signal()

    def __init__(self, caption: str, secret: bool = False, parent=None):
        super().__init__(parent)
        self.secret = secret
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(56)
        self._active = False

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 0, 18, 0)
        row.setSpacing(12)

        self.caption = _text(caption, 13, t.FAINT, bold=True, spacing=0.4)
        self.caption.setFixedWidth(72)
        row.addWidget(self.caption)

        self.value = _text("", 19, t.INK, bold=True)
        row.addWidget(self.value, 1)

        self._paint()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        event.accept()

    def set_active(self, active: bool) -> None:
        self._active = active
        self._paint()

    def set_value(self, raw: str, caret: bool) -> None:
        shown = ("●" * len(raw)) if self.secret else raw
        if self._active:
            shown += "▏" if caret else " "   # kursor joyi qimirlamasin
        elif not shown:
            shown = ""
        self.value.setText(shown)
        self.value.setStyleSheet(
            f"QLabel {{ color:{t.INK if raw else t.FAINT}; background:transparent;"
            f" border:none; font-size:19px; font-weight:600; }}"
        )

    def _paint(self) -> None:
        if self._active:
            bg, border, width = t.SURFACE_DARK, t.ACCENT, 2
        else:
            bg, border, width = t.BG_SOFT, t.LINE, 1
        self.setStyleSheet(
            f"_Field {{ background:{bg}; border:{width}px solid {border};"
            f" border-radius:12px; }}"
        )
        self.caption.setStyleSheet(
            f"QLabel {{ color:{t.ACCENT if self._active else t.FAINT};"
            f" background:transparent; border:none; font-size:13px;"
            f" font-weight:600; letter-spacing:0.4px; }}"
        )


class LoginScreen(QWidget):
    """Login + parol. Signallar: login(login, parol), quit_requested().

    Ikkinchi rejim — «davom etish»: kassir ilgari kirgan va «Chiqish» ni
    bosmagan (smena yopilgan yoki dastur qayta ochilgan). Unda login-parol
    so'ralmaydi: karta o'rniga kassir ismi va «SMENA OCHISH» tugmasi
    ko'rinadi. Signallar: resume_requested(), logout_requested().
    """

    login = Signal(str, str)
    quit_requested = Signal()
    resume_requested = Signal()
    logout_requested = Signal()

    LOGIN, PAROL = "login", "parol"

    def __init__(self, parent: QWidget, point: str = "", register: str = ""):
        super().__init__(parent)
        self.setObjectName("loginScreen")
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"QWidget#loginScreen {{ background: {t.BG_PAGE}; }}")
        self.values = {self.LOGIN: "", self.PAROL: ""}
        self.active = self.LOGIN
        self._point = point
        self._register = register
        parent.installEventFilter(self)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._brand_panel(), 4)
        root.addWidget(self._form_panel(), 6)

        # Kursor pirpirashi — maydon «tirik» ko'rinsin
        self._caret = True
        self._blink = QTimer(self)
        self._blink.setInterval(530)
        self._blink.timeout.connect(self._tick_caret)

        self.hide()
        self.refresh()

    # --------------------------------------------------------- ko'rinish

    def _brand_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("loginBrand")
        # Tekis, to'q yashil panel — gradientsiz, minimalistik va premium.
        panel.setStyleSheet(
            f"QWidget#loginBrand {{ background: {t.PRIMARY_DARK}; }}"
        )
        col = QVBoxLayout(panel)
        col.setContentsMargins(44, 40, 44, 30)
        col.addStretch(1)

        logo = QLabel()
        logo.setStyleSheet("background: transparent;")
        path = Path(__file__).resolve().parent.parent / "sevimli-logo.png"
        if path.exists():
            pm = QPixmap(str(path))
            logo.setPixmap(
                pm.scaled(330, 145, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        col.addWidget(logo, 0, Qt.AlignHCenter)
        col.addStretch(2)

        self.status = _text("", 13, "#DAF1DE")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        col.addSpacing(10)

        # Kassa metama'lumoti — kassa nomi · nuqta (bor bo'lsa)
        meta = "  ·  ".join(x for x in (self._register, self._point) if x)
        if meta:
            col.addWidget(_text(meta, 13, "#8EB69B", bold=True))
            col.addSpacing(1)
        col.addWidget(_text(tr("Versiya {v}").format(v=VERSION), 12, "#5C7E6E"))
        return panel

    def _form_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("loginForm")
        panel.setStyleSheet(f"QWidget#loginForm {{ background: {t.BG_PAGE}; }}")

        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 10, 0, 10)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("loginCard")
        card.setFixedWidth(540)
        card.setStyleSheet(
            f"QFrame#loginCard {{ background: {t.BG}; border: 1px solid {t.LINE};"
            f" border-radius: 20px; }}"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(46)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(28, 21, 23, 34))
        card.setGraphicsEffect(shadow)

        col = QVBoxLayout(card)
        col.setContentsMargins(28, 26, 28, 22)
        col.setSpacing(0)

        head = _text(tr("Kassaga kirish"), 25, t.INK, bold=True)
        head.setAlignment(Qt.AlignCenter)
        col.addWidget(head)
        col.addSpacing(4)
        note = _text(tr("Login va parolingizni kiriting"), 13, t.MUTED)
        note.setAlignment(Qt.AlignCenter)
        col.addWidget(note)
        col.addSpacing(20)

        self.fields: dict[str, _Field] = {}
        for key, caption, secret in (
            (self.LOGIN, tr("Login"), False),
            (self.PAROL, tr("Parol"), True),
        ):
            field = _Field(caption, secret=secret)
            field.clicked.connect(lambda k=key: self.select(k))
            self.fields[key] = field
            col.addWidget(field)
            col.addSpacing(10)

        self.hint = _text("", 13, t.DANGER)
        self.hint.setAlignment(Qt.AlignCenter)
        # Uzun xabar («bu login boshqa kompyuterda…») sig'sin — o'raladi
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(22)
        col.addWidget(self.hint)
        col.addSpacing(6)

        keyboard = _Keyboard()
        keyboard.key.connect(self.on_key)
        keyboard.backspace.connect(self.on_backspace)
        col.addWidget(keyboard)
        col.addSpacing(16)

        self.enter = QPushButton(tr("KIRISH"))
        self.enter.setFixedHeight(62)
        self.enter.setCursor(Qt.PointingHandCursor)
        self.enter.setFocusPolicy(Qt.NoFocus)
        self.enter.setStyleSheet(
            f"QPushButton {{ background:{t.ACCENT}; color:#FFFFFF; border:none;"
            f" border-radius:13px; font-size:18px; font-weight:700;"
            f" letter-spacing:0.8px; }}"
            f"QPushButton:hover {{ background:#1D4A3F; }}"
            f"QPushButton:pressed {{ background:{t.ACCENT_DARK}; }}"
            f"QPushButton:disabled {{ background:{t.ACCENT_SOFT}; color:#FFFFFF; }}"
        )
        self.enter.clicked.connect(self._submit)
        col.addWidget(self.enter)

        outer.addWidget(card, 0, Qt.AlignHCenter)
        self.card = card

        # «Davom etish» kartasi — login-parolsiz (kassir chiqmagan)
        self.resume_card = self._resume_card()
        self.resume_card.hide()
        outer.addWidget(self.resume_card, 0, Qt.AlignHCenter)
        outer.addSpacing(16)

        quit_btn = QPushButton(tr("Dasturni yopish"))
        quit_btn.setFixedHeight(36)
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.setFocusPolicy(Qt.NoFocus)
        quit_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{t.FAINT};"
            f" border:none; font-size:13px; }}"
            f"QPushButton:hover {{ color:{t.INK_SOFT}; }}"
        )
        quit_btn.clicked.connect(self.quit_requested.emit)
        outer.addWidget(quit_btn, 0, Qt.AlignHCenter)
        outer.addStretch(1)
        return panel

    def _resume_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("resumeCard")
        card.setFixedWidth(540)
        card.setStyleSheet(
            f"QFrame#resumeCard {{ background: {t.BG}; border: 1px solid {t.LINE};"
            f" border-radius: 20px; }}"
        )
        col = QVBoxLayout(card)
        col.setContentsMargins(28, 30, 28, 26)
        col.setSpacing(0)

        self.resume_who = _text("", 25, t.INK, bold=True)
        self.resume_who.setAlignment(Qt.AlignCenter)
        col.addWidget(self.resume_who)
        col.addSpacing(6)
        self.resume_note = _text("", 14, t.MUTED)
        self.resume_note.setAlignment(Qt.AlignCenter)
        self.resume_note.setWordWrap(True)
        col.addWidget(self.resume_note)
        col.addSpacing(22)

        self.resume_btn = QPushButton(tr("SMENA OCHISH"))
        self.resume_btn.setFixedHeight(72)
        self.resume_btn.setCursor(Qt.PointingHandCursor)
        self.resume_btn.setFocusPolicy(Qt.NoFocus)
        self.resume_btn.setStyleSheet(
            f"QPushButton {{ background:{t.ACCENT}; color:#FFFFFF; border:none;"
            f" border-radius:13px; font-size:20px; font-weight:700;"
            f" letter-spacing:0.8px; }}"
            f"QPushButton:pressed {{ background:{t.ACCENT_DARK}; }}"
        )
        self.resume_btn.clicked.connect(self.resume_requested.emit)
        col.addWidget(self.resume_btn)
        col.addSpacing(12)

        self.resume_logout = QPushButton(tr("CHIQISH — boshqa kassir kiradi"))
        self.resume_logout.setFixedHeight(52)
        self.resume_logout.setCursor(Qt.PointingHandCursor)
        self.resume_logout.setFocusPolicy(Qt.NoFocus)
        self.resume_logout.setStyleSheet(
            f"QPushButton {{ background:{t.BG_SOFT}; color:{t.INK_SOFT};"
            f" border:1.5px solid {t.LINE_STRONG}; border-radius:13px;"
            f" font-size:15px; font-weight:600; }}"
            f"QPushButton:pressed {{ background:{t.SURFACE_2}; }}"
        )
        self.resume_logout.clicked.connect(self.logout_requested.emit)
        col.addWidget(self.resume_logout)
        return card

    # ------------------------------------------------------------- holat

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def open_resume(self, name: str, note: str = "") -> None:
        """«Davom etish» rejimi: login-parol so'ralmaydi — kassir kirgan,
        faqat smena ochish kerak (yoki «Chiqish»)."""
        self.resume_who.setText(tr("Kirgan: {n}").format(n=name))
        self.resume_note.setText(
            note or tr("Smena yopiq. Yangi smena ochish uchun tugmani bosing.")
        )
        self.hint.setText("")
        self.card.hide()
        self.resume_card.show()
        self._blink.stop()
        self._fit()
        self.show()
        self.raise_()
        self.setFocus()

    @property
    def resume_mode(self) -> bool:
        return not self.resume_card.isHidden()

    def open(self, keep_login: str = "") -> None:
        """Ekranni ko'rsatadi. `keep_login` — login maydonini to'ldirib
        qo'yish (parol xato bo'lganda qulay); odatda bo'sh."""
        self.values[self.LOGIN] = keep_login
        self.values[self.PAROL] = ""
        self.active = self.PAROL if keep_login else self.LOGIN
        self.hint.setText("")
        self.enter.setEnabled(True)
        self.resume_card.hide()
        self.card.show()
        self._caret = True
        self._blink.start()
        self._fit()
        self.show()
        self.raise_()
        self.setFocus()
        self.refresh()

    def hideEvent(self, event) -> None:
        self._blink.stop()
        super().hideEvent(event)

    def show_error(self, text: str) -> None:
        """Xato — parol tozalanadi, login qoladi (qayta terish shart emas)."""
        self.values[self.PAROL] = ""
        self.active = self.PAROL
        self.hint.setText(text)
        self.enter.setEnabled(True)
        self.refresh()

    def set_busy(self, busy: bool) -> None:
        self.enter.setEnabled(not busy)
        self.enter.setText(tr("Tekshirilmoqda…") if busy else tr("KIRISH"))
        if busy:
            self.hint.setText("")

    # ---------------------------------------------------------- kiritish

    def select(self, key: str) -> None:
        self.active = key
        self._caret = True
        self.refresh()

    def on_key(self, ch: str) -> None:
        if len(self.values[self.active]) < 64:
            self.values[self.active] += ch
        self.hint.setText("")
        self._caret = True
        self.refresh()

    def on_backspace(self) -> None:
        self.values[self.active] = self.values[self.active][:-1]
        self._caret = True
        self.refresh()

    def _submit(self) -> None:
        login = self.values[self.LOGIN].strip()
        parol = self.values[self.PAROL]
        if not login or not parol:
            self.hint.setText(tr("Login va parolni kiriting"))
            self.select(self.LOGIN if not login else self.PAROL)
            return
        self.login.emit(login.lower(), parol)

    def keyPressEvent(self, event):
        """Jismoniy klaviatura ham ishlasin — ba'zi kassalarda u bor."""
        if self.resume_mode:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.resume_requested.emit()
            else:
                super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._submit()
        elif event.key() == Qt.Key_Backspace:
            self.on_backspace()
        elif event.key() == Qt.Key_Tab:
            self.select(self.PAROL if self.active == self.LOGIN else self.LOGIN)
        elif event.text() and event.text().isprintable():
            self.on_key(event.text())
        else:
            super().keyPressEvent(event)

    # ---------------------------------------------------------- chizish

    def _tick_caret(self) -> None:
        self._caret = not self._caret
        field = self.fields[self.active]
        field.set_value(self.values[self.active], self._caret)

    def refresh(self) -> None:
        for key, field in self.fields.items():
            field.set_active(key == self.active)
            field.set_value(self.values[key], self._caret if key == self.active else False)

    # -------------------------------------------------------- joylashuv

    def _fit(self) -> None:
        p = self.parentWidget()
        if p:
            self.setGeometry(p.rect())

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize and self.isVisible():
            self._fit()
        return False
