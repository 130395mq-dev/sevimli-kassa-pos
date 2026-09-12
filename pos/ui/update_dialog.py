"""
Ilova versiyasi bilan bog'liq oynalar.

`AboutDialog` — «Dastur haqida»: versiya, holat («Kassa yangi» yoki
«Yangi versiya bor»), «Yangilanishni tekshirish» tugmasi. MoySklad
Kassa'dagi «О приложении» ekranining o'rnini bosadi.

`UpdateDialog` — yangilanish yuklab olingach chiqadi: «Yangilash» /
«Keyinroq». Majburiy bo'lsa «Keyinroq» yo'q va sanoq ketadi.

Bu yerda tarmoq ishi yo'q — hammasi fon oqimidan signal bilan keladi.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..version import VERSION, is_newer
from . import theme as t
from .dialogs import BaseDialog, _label
from .keypad import touch_button


def _human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


class _StatusCard(QFrame):
    """Logo + ikki qator matn — «Kassa yangi / Sizda 1.1.0 o'rnatilgan»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {t.BG_SOFT}; border: 1px solid {t.LINE};"
            f" border-radius: 14px; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(16)

        logo = QLabel()
        logo.setFixedSize(64, 64)
        logo.setStyleSheet("background: transparent; border: none;")
        path = Path(__file__).resolve().parent.parent / "sevimli-logo.png"
        if path.exists():
            pm = QPixmap(str(path))
            logo.setPixmap(pm.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        row.addWidget(logo, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(3)
        self.state = _label("", 13, t.MUTED)
        self.title = _label("", 17, t.INK, bold=True)
        self.detail = _label("", 13, t.INK_SOFT)
        self.detail.setWordWrap(True)
        col.addWidget(self.state)
        col.addWidget(self.title)
        col.addWidget(self.detail)
        row.addLayout(col, 1)

    def set(self, state: str, title: str, detail: str = "", tone: str = "muted") -> None:
        color = {"ok": t.OK, "warn": t.WARN, "err": t.DANGER}.get(tone, t.MUTED)
        self.state.setText(state)
        self.state.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        self.title.setText(title)
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))


class AboutDialog(BaseDialog):
    """«Dastur haqida» — versiya va yangilanish.

    `request_check()` — fon oqimiga «hozir tekshir» deydi. Natija
    `show_result(info, error)` / `show_progress(done, total)` /
    `show_ready(info)` orqali keladi (main.py signallarni ulaydi).
    """

    def __init__(self, point: str, register: str, server: str, parent=None):
        super().__init__(tr("Dastur haqida"), width=520, parent=parent)
        self._request_check = None
        self._ready_info: dict | None = None
        self.on_install = None   # callable(info) — «Yangilash» bosilganda

        self.card = _StatusCard()
        self.root.addWidget(self.card)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {t.LINE}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {t.ACCENT}; border-radius: 4px; }}"
        )
        self.progress.hide()
        self.root.addWidget(self.progress)

        self.check_btn = touch_button(
            tr("Yangilanishni tekshirish"), size=16, height=58, tone="plain"
        )
        self.check_btn.clicked.connect(self._check)
        self.root.addWidget(self.check_btn)

        self.install_btn = touch_button(tr("Yangilash"), size=17, height=58, tone="accent")
        self.install_btn.clicked.connect(self._install)
        self.install_btn.hide()
        self.root.addWidget(self.install_btn)

        self.note = _label("", 13, t.MUTED)
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        self.root.addWidget(self.note)

        # Kassa ma'lumotlari — muammo bo'lsa telefon orqali aytish uchun
        info = QWidget()
        grid = QVBoxLayout(info)
        grid.setContentsMargins(4, 8, 4, 0)
        grid.setSpacing(4)
        for k, v in (
            (tr("Savdo nuqtasi"), point),
            (tr("Kassa"), register),
            (tr("Server"), server),
        ):
            line = QHBoxLayout()
            line.addWidget(_label(k, 13, t.FAINT))
            line.addStretch(1)
            val = _label(v or "—", 13, t.INK_SOFT)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            line.addWidget(val)
            grid.addLayout(line)
        self.root.addWidget(info)

        close = touch_button(tr("Yopish"), size=16, height=58, tone="soft")
        close.clicked.connect(self.accept)
        self.root.addWidget(close)

        self.show_idle()

    # ------------------------------------------------------- holatlar

    def set_checker(self, fn) -> None:
        self._request_check = fn

    def show_idle(self) -> None:
        self.card.set(
            tr("Kassa yangi"),
            tr("Sizda Sevimli Kassa {v} o'rnatilgan").format(v=VERSION),
            "", tone="ok",
        )
        self.note.setText(tr("Siz allaqachon eng so'nggi versiyadan foydalanyapsiz."))
        self.progress.hide()
        self.install_btn.hide()
        self.check_btn.setEnabled(True)

    def _check(self) -> None:
        self.card.set(
            tr("Tekshirilmoqda…"),
            tr("Sizda Sevimli Kassa {v} o'rnatilgan").format(v=VERSION),
            "",
        )
        self.note.setText(tr("Serverdan versiya so'ralmoqda"))
        self.check_btn.setEnabled(False)
        if self._request_check:
            self._request_check()

    def show_result(self, info: dict | None, error: str) -> None:
        self.check_btn.setEnabled(True)
        if error or not info:
            self.card.set(
                tr("Tekshirib bo'lmadi"),
                tr("Sizda Sevimli Kassa {v} o'rnatilgan").format(v=VERSION),
                error or "", tone="err",
            )
            self.note.setText(tr("Server bilan aloqa yo'q. Keyinroq urinib ko'ring."))
            return
        newest = info.get("version") or ""
        if is_newer(newest) and info.get("url"):
            self.card.set(
                tr("Yangi versiya bor"),
                tr("Sevimli Kassa {v}").format(v=newest),
                info.get("notes") or "", tone="warn",
            )
            self.note.setText(
                tr("Yuklab olinmoqda… kassa ishlashda davom etadi")
                + (f" · {_human_size(int(info.get('size') or 0))}" if info.get("size") else "")
            )
            self.progress.setValue(0)
            self.progress.show()
        else:
            self.show_idle()

    def show_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / total))
        else:
            self.progress.setRange(0, 0)
        self.progress.show()

    def show_ready(self, info: dict) -> None:
        self._ready_info = info
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.card.set(
            tr("Yangilanish tayyor"),
            tr("Sevimli Kassa {v}").format(v=info.get("version", "")),
            info.get("notes") or "", tone="warn",
        )
        self.note.setText(
            tr("«Yangilash» bosilgach kassa 10 soniyaga yopilib, yangi versiyada qayta ochiladi.")
        )
        self.install_btn.show()
        self.check_btn.setEnabled(True)

    def show_failed(self, error: str) -> None:
        self.progress.hide()
        self.card.set(
            tr("Yuklab bo'lmadi"),
            tr("Sizda Sevimli Kassa {v} o'rnatilgan").format(v=VERSION),
            error, tone="err",
        )
        self.note.setText(tr("Keyingi tekshiruvda qayta uriniladi."))
        self.check_btn.setEnabled(True)

    def _install(self) -> None:
        if self._ready_info and self.on_install:
            self.accept()
            self.on_install(self._ready_info)


class UpdateDialog(QDialog):
    """Yangilanish yuklab olindi — o'rnatamizmi?

    Majburiy bo'lsa: «Keyinroq» yo'q, 15 soniyalik sanoq bor — kassir
    hech narsa bosmasa ham yangilanadi. Bu MoySklad Kassa ishlayotgan
    do'kon uchun muhim: bitta eskirgan kassa butun tarmoqni buzmasin.
    """

    COUNTDOWN = 15

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setModal(True)
        self.setWindowTitle(tr("Yangilanish"))
        self.setMinimumWidth(520)
        self.setStyleSheet(f"background: {t.BG};")
        mandatory = bool(info.get("mandatory"))
        if mandatory:
            # Yopib bo'lmaydi — faqat «Yangilash»
            self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(12)

        badge = _label(
            tr("MAJBURIY YANGILANISH") if mandatory else tr("YANGILANISH TAYYOR"),
            12, t.DANGER if mandatory else t.OK, bold=True,
        )
        badge.setAlignment(Qt.AlignCenter)
        root.addWidget(badge)

        title = _label(
            tr("Sevimli Kassa {v}").format(v=info.get("version", "")),
            24, t.INK, bold=True,
        )
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        sub = _label(
            tr("Sizda {v} o'rnatilgan").format(v=VERSION), 13, t.MUTED
        )
        sub.setAlignment(Qt.AlignCenter)
        root.addWidget(sub)

        notes = (info.get("notes") or "").strip()
        if notes:
            box = QFrame()
            box.setStyleSheet(
                f"QFrame {{ background: {t.BG_SOFT}; border: 1px solid {t.LINE};"
                f" border-radius: 12px; }}"
            )
            lay = QVBoxLayout(box)
            lay.setContentsMargins(16, 12, 16, 12)
            head = _label(tr("Nima o'zgardi"), 12, t.FAINT, bold=True)
            body = _label(notes, 14, t.INK_SOFT)
            body.setWordWrap(True)
            lay.addWidget(head)
            lay.addWidget(body)
            root.addWidget(box)

        self.hint = _label("", 13, t.MUTED)
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        if not mandatory:
            later = touch_button(tr("Keyinroq"), size=16, height=64, tone="soft")
            later.clicked.connect(self.reject)
            row.addWidget(later, 2)
        self.ok = touch_button(tr("Hozir yangilash"), size=18, height=64, tone="accent")
        self.ok.clicked.connect(self.accept)
        row.addWidget(self.ok, 3)
        root.addLayout(row)

        self._left = self.COUNTDOWN if mandatory else 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._refresh_hint()
        if mandatory:
            self._timer.start()

    def _refresh_hint(self) -> None:
        if self._left > 0:
            self.hint.setText(
                tr("Kassa {n} soniyadan so'ng o'zi yangilanadi. "
                   "Yangilanish 10-20 soniya oladi.").format(n=self._left)
            )
        else:
            self.hint.setText(
                tr("Kassa yopilib, yangi versiyada qayta ochiladi (10-20 soniya). "
                   "Cheklar va navbat saqlanib qoladi.")
            )

    def _tick(self) -> None:
        self._left -= 1
        self._refresh_hint()
        if self._left <= 0:
            self._timer.stop()
            self.accept()

    def reject(self) -> None:
        # Majburiy bo'lsa Esc ham yopmaydi
        if self.info.get("mandatory"):
            return
        super().reject()
