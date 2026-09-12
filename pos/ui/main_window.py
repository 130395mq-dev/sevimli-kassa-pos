"""
Kassaning asosiy ekrani.

Tuzilishi MoySklad Kassa'nikidek: chapda katalog, o'ngda chek, pastda
«Jami:» qatori. «Jami:» bosilsa to'lov oynasi ochiladi — MoySklad'da
ham shunday, va F9 ham shu ishni qiladi.

Skaner klaviatura kabi ishlaydi: raqamlarni yozib, oxirida Enter bosadi.
Shuning uchun alohida qurilma drayveri kerak emas — kodni qabul qiladigan
maydon doim fokusda turadi.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..cart import Cart, Product
from ..money import qty_str, som
from ..i18n import tr
from . import theme as t
from . import icons
from .keypad import touch_button
from .link_lights import LinkLights
from .payment_dialog import PaymentDialog


def _label(text="", size=14, color=t.INK, bold=False) -> QLabel:
    lbl = QLabel(text)
    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return lbl


# Nozik skrollbar — o'q tugmalari, burchak qutichasi va gorizontal bar
# ko'rinmaydi. Sensorli ekranда chiroyliroq va toza.
_SCROLLBAR_QSS = """
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px 2px; }
QScrollBar::handle:vertical { background: rgba(80,110,94,0.28);
    border-radius: 4px; min-height: 48px; }
QScrollBar::handle:vertical:hover { background: rgba(80,110,94,0.48); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; background: transparent; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 0px; background: transparent; }
QAbstractScrollArea::corner { background: transparent; border: none; }
"""


class _LogoGlowPage(QWidget):
    """Bo'sh chek sahifasi: shaffof (orqada aurora), logo ortida mayin
    yashil yorug'lik halqasi. Logoning shakli/yozuvi o'zgarmaydi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._logo = None  # QLabel — glow markazi shu logoga bog'lanadi

    def paintEvent(self, _e):
        from .aurora import paint_glow
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        if self._logo is not None and self._logo.isVisible():
            c = self._logo.geometry().center()
            cx, cy = c.x(), c.y()
        else:
            cx, cy = self.width() // 2, int(self.height() * 0.42)
        # Ikki qatlamli yumshoq halqa — mayin, keskinliksiz.
        paint_glow(p, cx, cy, 230, t.GLOW, alpha=90)
        paint_glow(p, cx, cy, 130, t.ACCENT_GLOW, alpha=70)
        p.end()


class _StackHost(QWidget):
    """Ichki widget'ni to'ldiradi, ustiga pastga yopishgan overlay qo'yadi.

    Video/ro'yxat butun bo'shliqni egallaydi; «Покупатель» qatori uning
    ustида, pastда suzib turadi — orada oq joy qolmaydi.
    """

    def __init__(self, content: QWidget, overlay: QWidget, overlay_h: int = 64,
                 parent=None):
        super().__init__(parent)
        self._content = content
        self._overlay = overlay
        self._oh = overlay_h
        content.setParent(self)
        overlay.setParent(self)

    def resizeEvent(self, event):
        w, h = self.width(), self.height()
        self._content.setGeometry(0, 0, w, h)
        self._overlay.setGeometry(0, h - self._oh, w, self._oh)
        self._overlay.raise_()


def _initials(name: str) -> str:
    """Nomdan 2 harfli qisqartma: «Coca-Cola» -> «CO», «Non» -> «NO»."""
    letters = [c for c in (name or "") if c.isalnum()]
    return ("".join(letters[:2]).upper() or "?")


# Rasm yo'q tovarlar uchun — nomdan barqaror (deterministik) och yashil tus.
# Random rasm QO'YILMAYDI: professional initials placeholder.
_TILE_TINTS = ["#DAF1DE", "#C9E9D2", "#BCE1C7", "#D2EFDB", "#C2E6CE", "#CFEAD7"]


def _tile_color(name: str) -> str:
    if not name:
        return _TILE_TINTS[0]
    return _TILE_TINTS[sum(ord(c) for c in name) % len(_TILE_TINTS)]


class _CatalogDelegate(QStyledItemDelegate):
    """Bitta tovar KARTASINI chizadi (grid). Vidjet o'rniga delegat —
    minglab tovar ham tez chiziladi (faqat ko'rinadigani).

    Karta ixcham va MATNGA asoslangan: rasm maydoni YO'Q. Nom to'liq
    ko'rsatiladi (bir necha qatorда), pastда narx, yuqori-o'ngда yulduzcha,
    tugagan tovarда «yo'q» belgisi. Holatlar: hover, tanlangan, tugagan.
    """

    NAME = Qt.UserRole + 1
    PRICE = Qt.UserRole + 2
    GONE = Qt.UserRole + 3
    FAV = Qt.UserRole + 4
    UNIT = Qt.UserRole + 5
    STOCK = Qt.UserRole + 6

    # Karta o'lchamlari — rasmsiz, ixcham. Nom uchun 4 qatorgacha joy bor.
    CARD_W, CARD_H = 174, 134
    MARGIN = 5           # karta atrofidagi bo'sh joy (grid katak ichida)
    STAR_BOX = 24        # yuqori-o'ngdagi yulduzcha zonasi
    RAD = 10             # burchak radiusi (avvalgidan kichikroq)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name_font = QFont(); self._name_font.setPixelSize(14); self._name_font.setBold(True)
        self._price_font = QFont(); self._price_font.setPixelSize(19); self._price_font.setBold(True)
        self._unit_font = QFont(); self._unit_font.setPixelSize(11)
        self._tag_font = QFont(); self._tag_font.setPixelSize(10); self._tag_font.setBold(True)
        self._tag_text = tr("yo'q")

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.CARD_W, self.CARD_H)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        gone = bool(index.data(self.GONE))
        name = index.data(self.NAME) or ""
        price = index.data(self.PRICE) or ""
        unit = index.data(self.UNIT) or ""
        stock = index.data(self.STOCK) or ""
        fav = bool(index.data(self.FAV))
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)

        card = option.rect.adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        rad = self.RAD

        # Tugagan tovar — butun karta xiraroq
        if gone:
            painter.setOpacity(0.55)

        # Yumshoq soya — kartani fondan ko'taradi (3D). To'q fonda soya
        # to'qroq, hover/selected'da chuqurroq.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(16, 61, 50, 16 if (hover or selected) else 7))
        painter.drawRoundedRect(card.adjusted(0, 4, 0, 5), rad, rad)

        painter.setBrush(QColor(t.ACCENT_PALE if selected else t.BG))
        if selected:
            painter.setPen(QPen(QColor(t.ACCENT), 2))
        elif hover:
            painter.setPen(QPen(QColor(t.ACCENT_SOFT), 1.5))
        else:
            painter.setPen(QPen(QColor(t.LINE), 1))
        painter.drawRoundedRect(card, rad, rad)

        # Yuqori chetда nozik yorug'lik chizig'i — 3D «shisha» tuyg'usi.
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawLine(card.left() + rad, card.top() + 1,
                         card.right() - rad, card.top() + 1)

        pad = 9
        inner_l = card.left() + pad
        inner_w = card.width() - 2 * pad

        # Yulduzcha — yuqori-o'ng burchak (Lucide SVG, emoji emas).
        star = QRect(card.right() - self.STAR_BOX, card.top() + 2,
                     self.STAR_BOX, self.STAR_BOX)
        sp = icons.pixmap("star", 15, t.WARN if fav else t.FAINT, fill=fav)
        painter.drawPixmap(star.center().x() - 7, star.center().y() - 7, sp)

        # Nom — TO'LIQ (4 qatorgacha). 1-qator yulduzcha uchun torroq.
        fm = QFontMetrics(self._name_font)
        painter.setFont(self._name_font)
        painter.setPen(QColor(t.INK))
        name_rect = QRect(inner_l, card.top() + 7, inner_w,
                          card.bottom() - 40 - (card.top() + 7))
        self._draw_name(painter, name_rect, name, fm,
                        first_w=inner_w - (self.STAR_BOX - 4), max_lines=4)

        # Narx — pastda-chapда, urg'uli, OCH ZUMRAD
        painter.setFont(self._price_font)
        painter.setPen(QColor(t.PRICE))
        price_rect = QRect(inner_l, card.bottom() - 26, inner_w - 4, 20)
        painter.drawText(price_rect, Qt.AlignLeft | Qt.AlignVCenter, price)

        # Birlik + qoldiq — narx tepasида, muted
        if unit or stock:
            painter.setFont(self._unit_font)
            painter.setPen(QColor(t.MUTED))
            meta = QRect(inner_l, card.bottom() - 42, inner_w, 14)
            mfm = QFontMetrics(self._unit_font)
            txt = "  ·  ".join(x for x in (unit, stock) if x)
            painter.drawText(meta, Qt.AlignLeft | Qt.AlignVCenter,
                             mfm.elidedText(txt, Qt.ElideRight, inner_w))

        # «yo'q» belgisi — pastki-o'ngда qizil pill (narx yonida)
        if gone:
            painter.setOpacity(1.0)
            tfm = QFontMetrics(self._tag_font)
            tw = tfm.horizontalAdvance(self._tag_text) + 14
            tag = QRect(card.right() - pad - tw, card.bottom() - 25, tw, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.DANGER))
            painter.drawRoundedRect(tag, 9, 9)
            painter.setFont(self._tag_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(tag, Qt.AlignCenter, self._tag_text)

        painter.setOpacity(1.0)
        painter.restore()

    @staticmethod
    def _draw_name(painter, rect: QRect, text: str, fm: QFontMetrics,
                   first_w: int, max_lines: int) -> None:
        """Nomni to'liq ko'rsatadi (max_lines qatorgacha). 1-qator torroq
        (yulduzcha uchun). Joy yetmasa oxirgi qatorда «…»."""
        words = text.split()
        lines: list[str] = []
        cur = ""
        i = 0
        while i < len(words):
            w = first_w if len(lines) == 0 else rect.width()
            trial = (cur + " " + words[i]).strip()
            if fm.horizontalAdvance(trial) <= w or not cur:
                cur = trial
                i += 1
            else:
                lines.append(cur)
                cur = ""
                if len(lines) == max_lines - 1:
                    break
        if cur and len(lines) < max_lines:
            lines.append(cur)
        # Qolgan so'zlar bo'lsa — oxirgi qatorни «…» bilan yakunlaymiz
        if i < len(words) and lines:
            rest = (lines[-1] + " " + " ".join(words[i:])).strip()
            lines[-1] = fm.elidedText(rest, Qt.ElideRight, rect.width())
        y = rect.top() + fm.ascent()
        for ln in lines:
            painter.drawText(rect.left(), y, ln)
            y += fm.height()


class MainWindow(QMainWindow):
    """Kassa oynasi.

    `backend` — ma'lumot manbai. Unda quyidagilar bo'lishi kerak:
        find_by_barcode(code) -> Product | None
        find_by_plu(plu)      -> Product | None
        search(text)          -> list[Product]
        methods               -> list[dict]
        submit(cart, plan)    -> None
    """

    sale_finished = Signal()
    price_type_clicked = Signal()

    def __init__(self, backend, parent=None, animated_bg: bool = True):
        super().__init__(parent)
        self.backend = backend
        #: main.py o'rnatadi — savdo tugagach mijoz chekini chiqaradi.
        self.print_sale = None
        self.cart = Cart()
        self._bg_animated = animated_bg

        self.setWindowTitle("Sevimli Kassa")
        self.resize(1440, 900)

        # Katalog ro'yxatida hozir qaysi so'rov ko'rsatilgan ("" — hammasi).
        # None — hali hech narsa chizilmagan.
        self._catalog_query: str | None = None
        self._pending_query = ""
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(180)
        self._search_timer.timeout.connect(self._run_search)

        # Markaziy widget — «shimol yog'dusi» fon (tun rejimi). UI shu
        # ustiga joylashadi; layout/joylashuv o'zgarmaydi. animated_bg
        # o'chiq bo'lsa — chiroyli statik fon qoladi.
        central = QWidget()
        central.setObjectName("workspace")
        central.setStyleSheet(f"QWidget#workspace {{ background: {t.BG_PAGE}; }}")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        brand = QWidget()
        brand.setStyleSheet(f"background: {t.PRIMARY_DARK};")
        brand.setFixedHeight(54)
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(22, 0, 22, 0)
        brand_row.addWidget(_label("SEVIMLI", 23, "#FFFFFF", bold=True))
        brand_row.addSpacing(16)
        brand_row.addWidget(_label(tr("Kassa"), 13, "#C5DFD0"))
        brand_row.addStretch()
        self.clock_label = _label("", 13, "#C5DFD0")
        brand_row.addWidget(self.clock_label)
        from PySide6.QtCore import QDateTime
        def tick():
            self.clock_label.setText(QDateTime.currentDateTime().toString("dd.MM.yyyy  •  HH:mm"))
        self._clock = QTimer(self)
        self._clock.timeout.connect(tick)
        self._clock.start(10000)
        tick()
        root.addWidget(brand)

        body = QHBoxLayout()
        body.setContentsMargins(14, 14, 14, 14)
        body.setSpacing(14)
        body.addWidget(self._catalog_panel(), 1)
        body.addWidget(self._receipt_panel())

        root.addLayout(body, 1)

        self._shortcuts()
        self.refresh()
        self.scan_input.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not getattr(self, "_titlebar_styled", False):
            self._titlebar_styled = True
            self._style_titlebar()

    def _style_titlebar(self) -> None:
        """Windows 11 sarlavha chizig'ini burgundiya qiladi.

        Standart ko'k chiziq dastur rangi bilan urishmaydi. DWM API orqali
        sarlavha rangini o'zgartiramiz. Windows 10 / boshqa OS'da e'tiborsiz
        o'tadi (xato bermaydi).
        """
        import sys

        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            dwm = ctypes.windll.dwmapi
            # COLORREF = 0x00BBGGRR. #051F20 -> R=05 G=1F B=20
            caption = ctypes.c_int(0x00201F05)
            text = ctypes.c_int(0x00FFFFFF)  # oq matn
            dwm.DwmSetWindowAttribute(  # 35 = DWMWA_CAPTION_COLOR
                hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption)
            )
            dwm.DwmSetWindowAttribute(  # 36 = DWMWA_TEXT_COLOR
                hwnd, 36, ctypes.byref(text), ctypes.sizeof(text)
            )
            # Windows 11 — oyna burchaklarini yumaloq qiladi.
            # 33 = DWMWA_WINDOW_CORNER_PREFERENCE, 2 = DWMWCP_ROUND.
            # DIQQAT: faqat maksimallashmagan (suzuvchi) oynada ko'rinadi;
            # to'liq ekran oyna Windows qoidasi bo'yicha to'rtburchak bo'ladi.
            corner = ctypes.c_int(2)
            dwm.DwmSetWindowAttribute(
                hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner)
            )
        except Exception:
            pass

    # ------------------------------------------------------------ chap panel

    def _catalog_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(t.CATALOG_MIN)
        # Shaffof — orqada aurora ko'rinadi (kartalar fon ustida suzadi).
        panel.setStyleSheet(
            f"background: transparent; border-right: 1px solid {t.LINE};")

        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # Sarlavha — to'q yashil ustki chiziq. Qidiruv maydoni asosiy
        # element: kassir tovarni nomidan topadi, skaner shu yerga uradi.
        head = QWidget()
        head.setFixedHeight(t.HEADER_HEIGHT)
        # To'q, biroz shaffof chrome — aurora yumshoq sezilib turadi.
        head.setStyleSheet(f"background: {t.BG}; border-bottom: 1px solid {t.LINE};")
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(14, 0, 14, 0)
        head_row.setSpacing(10)

        # Menyu — Lucide SVG ikona (emoji emas)
        menu = self._header_icon_button("menu", self.on_menu, tip=tr("Menyu"))
        head_row.addWidget(menu)

        # Qidiruv maydoni — ichida qidiruv ikonasi + o'ng chetда qisqa
        # klaviatura ishorasi. Fokusда yashil accent ramka.
        self.scan_input = QLineEdit()
        self.scan_input.setPlaceholderText(tr("Tovar nomi yoki shtrix-kod"))
        self.scan_input.setFixedHeight(50)
        self.scan_input.setClearButtonEnabled(True)
        self.scan_input.addAction(
            icons.icon("search", 18, t.MUTED), QLineEdit.LeadingPosition)
        self.scan_input.setStyleSheet(
            f"QLineEdit {{ border: 2px solid {t.LINE}; border-radius: 10px;"
            f" padding: 0 12px; font-size: 15px; background: {t.SURFACE_DARK};"
            f" color: {t.INK}; selection-background-color: {t.ACCENT}; }}"
            f"QLineEdit:focus {{ border: 2px solid {t.ACCENT}; background: {t.BG}; }}"
        )
        self.scan_input.returnPressed.connect(self.on_scan)
        self.scan_input.textChanged.connect(self.on_search)
        head_row.addWidget(self.scan_input, 1)

        # Sozlamalar (printer va b.) — o'ng chetда gear ikona
        gear = self._header_icon_button(
            "settings", self.open_settings, tip=tr("Sozlamalar"))
        head_row.addWidget(gear)

        col.addWidget(head)

        self.catalog_list = QListWidget()
        self.catalog_list.setItemDelegate(_CatalogDelegate(self.catalog_list))
        self.catalog_list.setMouseTracking(True)
        self.catalog_list.setUniformItemSizes(True)
        # PROFESSIONAL PRODUCT GRID: kartalar yonma-yon, o'ralib ketadi.
        self.catalog_list.setViewMode(QListView.IconMode)
        self.catalog_list.setFlow(QListView.LeftToRight)
        self.catalog_list.setWrapping(True)
        self.catalog_list.setResizeMode(QListView.Adjust)
        self.catalog_list.setMovement(QListView.Static)
        self.catalog_list.setSpacing(0)
        self.catalog_list.setGridSize(
            QSize(_CatalogDelegate.CARD_W, _CatalogDelegate.CARD_H))
        self.catalog_list.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.catalog_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Kartani delegat to'liq chizadi — item foni shaffof; ro'yxat foni
        # och yashil (BG_PAGE) — oq kartalar ajralib, «workspace» ko'rinadi.
        self.catalog_list.setStyleSheet(
            f"QListWidget {{ border: none; background: transparent;"
            f" outline: none; padding: 8px 4px; }}"
            f"QListWidget::item {{ background: transparent; border: none; }}"
            + _SCROLLBAR_QSS
        )
        # Bitta bosish = bitta tovar. Avval itemActivated + itemDoubleClicked
        # ikkalasi ulangan edi — sensorli ekranda bitta bosish 2 marta
        # ishlab, tovar 2 tadan qo'shilardi. Endi faqat itemClicked (chek
        # ro'yxatidagidek).
        self.catalog_list.itemClicked.connect(self.on_catalog_pick)
        # O'ng chekkadagi yulduzcha zonasiga bosilса — savatga qo'shmaymiz,
        # balki «sevimli» qilib belgilaymiz. Buni bosishни viewport'da
        # ushlab, kerak bo'lsa yutamiz (itemClicked chaqirilmaydi).
        self.catalog_list.viewport().installEventFilter(self)
        col.addWidget(self.catalog_list, 1)

        # Ulanish holati — kichkina, lekin doim ko'rinadi.
        # Chapda ikkita dumaloq chiroq (Server, MoySklad), yonida navbat
        # soni yoki qisqa xabar (flash).
        status = QWidget()
        status.setFixedHeight(34)
        status.setStyleSheet(f"border-top: 1px solid {t.LINE};")
        srow = QHBoxLayout(status)
        srow.setContentsMargins(16, 0, 16, 0)
        self.links = LinkLights(status)
        srow.addWidget(self.links)
        srow.addSpacing(14)
        self.status_label = _label("", 12, t.MUTED)
        srow.addWidget(self.status_label)
        srow.addStretch(1)
        col.addWidget(status)

        return panel

    # ------------------------------------------------------------ o'ng panel

    def _receipt_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(t.RECEIPT_WIDTH)
        panel.setObjectName("receiptPanel")
        panel.setStyleSheet(f"QWidget#receiptPanel {{ background: {t.BG}; border-radius: {t.RADIUS}px; }}")
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head = QWidget()
        head.setFixedHeight(t.HEADER_HEIGHT)
        # To'q, biroz shaffof chrome — aurora yumshoq sezilib turadi.
        head.setStyleSheet(f"background: {t.BG}; border-bottom: 1px solid {t.LINE};")
        hrow = QHBoxLayout(head)
        hrow.setContentsMargins(20, 0, 20, 0)

        # Narx turi tugmasi — «Chakana» / «Ulgurji». Bosilsa ro'yxat
        # ochiladi. Asosiy bo'lmagan tur (ulgurji) tanlanganda tugma
        # sariq yonadi — kassir ulgurji rejimda ekanini unutmasin.
        self.price_btn = touch_button("", size=13, bold=True, height=36, tone="soft")
        self.price_btn.setCursor(Qt.PointingHandCursor)
        self.price_btn.clicked.connect(lambda: self.price_type_clicked.emit())
        self.price_btn.hide()
        hrow.addWidget(self.price_btn)

        self.receipt_title = _label(tr("Chek"), 18, t.INK, bold=True)
        self.receipt_title.setAlignment(Qt.AlignCenter)
        hrow.addWidget(self.receipt_title, 1)
        # Smena yozuvi — pastdagi panel olib tashlangach, shu yerda
        self.shift_label = _label("", 11, t.MUTED)
        self.shift_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hrow.addWidget(self.shift_label)
        col.addWidget(head)

        self.receipt_list = QListWidget()
        self.receipt_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.receipt_list.setStyleSheet(
            f"QListWidget {{ border: none; background: {t.BG}; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {t.LINE};"
            f" color: {t.INK}; }}"
            f"QListWidget::item:selected {{ background: {t.ACCENT_PALE};"
            f" color: {t.INK}; }}"
            + _SCROLLBAR_QSS
        )
        # Qatorga bosilsa — miqdor yoki o'chirish oynasi ochiladi.
        # Pastdagi panel olib tashlangani uchun endi shu yo'l bilan.
        self.receipt_list.itemClicked.connect(self.on_receipt_tap)

        # Chek bo'sh bo'lsa — o'rtada katta Sevimli logotipi. Tovar
        # qo'shilsa, logo o'rniga chek ro'yxati chiqadi.
        self.receipt_stack = QStackedWidget()
        self.receipt_stack.addWidget(self._logo_page())   # 0 — bo'sh holat
        self.receipt_stack.addWidget(self.receipt_list)    # 1 — chek
        # «Покупатель» qatori video/ro'yxat USTIGA (overlay) qo'yiladi —
        # pastda oq bo'shliq qolmaydi, jonli fon Итого panelgacha to'ladi.
        self.customer_row = self._action_row(
            tr("tanlash uchun bosing"), self.on_customer
        )
        host = _StackHost(self.receipt_stack, self.customer_row)
        col.addWidget(host, 1)

        # Ro'yxat holatida oxirgi qator «Покупатель» ostida qolib ketmasin
        self.receipt_list.setViewportMargins(0, 0, 0, 64)

        col.addWidget(self._total_bar())
        return panel

    def _logo_page(self) -> QWidget:
        """Chek bo'sh bo'lganda: toza och fon + markazda logo va yo'riqnoma.

        Bezakli fon yo'q — minimalistik. Fon och yashil (design system
        BG_PAGE), o'rtada brend logotipi va qisqa yo'riqnoma.
        """
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.addStretch(3)

        logo = QLabel()
        logo.setStyleSheet(f"background: {t.ACCENT_PALE}; border-radius: 30px; padding: 22px;")
        logo.setPixmap(icons.pixmap("cart", 48, t.ACCENT))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo, 0, Qt.AlignCenter)

        lay.addSpacing(20)
        title = _label(tr("Tovar tanlanmagan"), t.FS_H2, t.INK, bold=True)
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title, 0, Qt.AlignCenter)

        sub = _label(tr("Tovarni tanlang yoki shtrix-kodni skanerlang"),
                     t.FS_SMALL, t.MUTED)
        sub.setAlignment(Qt.AlignCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub, 0, Qt.AlignCenter)

        lay.addStretch(4)
        return page

    def _action_row(self, text: str, handler) -> QWidget:
        w = QWidget()
        w.setFixedHeight(64)
        w.setCursor(Qt.PointingHandCursor)
        # Oq fonli bar — chek bo'sh bo'lsa ham (yorug' logo foni ustida)
        # matn aniq ko'rinsin. Ilgari shaffof edi va «Mijoz» ko'rinmasдi.
        w.setStyleSheet(
            f"background: {t.BG}; border-top: 1px solid {t.LINE};"
        )
        row = QHBoxLayout(w)
        row.setContentsMargins(20, 0, 20, 0)
        # Chapда «Mijoz» yorlig'i, o'ngда qiymat/ishorat — labeled field kabi.
        cap = _label(tr("Mijoz"), 13, t.MUTED)
        row.addWidget(cap)
        row.addStretch(1)
        label = _label(text, 16, t.INK)
        row.addWidget(label)
        w.mousePressEvent = lambda _e: handler()
        w._label = label
        w._cap = cap
        return w

    def _summary_row(self, caption: str):
        """Yig'indi qatori: chapда yorliq, o'ngда qiymat. Nolь bo'lsa
        yashiriladi (refresh boshqaradi)."""
        w = QWidget()
        r = QHBoxLayout(w)
        r.setContentsMargins(24, 3, 24, 3)
        cap = _label(caption, 14, t.MUTED)
        val = _label("", 14, t.INK_SOFT)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        r.addWidget(cap)
        r.addStretch(1)
        r.addWidget(val)
        w._val = val
        w._cap = cap
        w._row = r
        return w

    def _total_bar(self) -> QWidget:
        """Checkout rail — pastki yopishqoq qism: yig'indi tafsiloti +
        katta JAMI + to'lov tugmasi. Oddiy «Jami» chizig'idan farqli,
        oraliq/chegirma/ball ko'rsatiladi (bor bo'lsa)."""
        wrap = QWidget()
        wrap.setStyleSheet(f"background: {t.BG}; border-top: 1px solid {t.LINE};")
        box = QVBoxLayout(wrap)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(0)

        # Tafsilot qatorlari — faqat qiymat bo'lsa ko'rinadi
        self.sum_subtotal = self._summary_row(tr("Oraliq summa"))
        self.sum_discount = self._summary_row(tr("Chegirma"))
        self.sum_bonus = self._summary_row(tr("Ball bilan"))
        # Ball qatori — bosiladigan tugma kabi: balandroq, katta matn.
        self.sum_bonus.setCursor(Qt.PointingHandCursor)
        self.sum_bonus.setMinimumHeight(52)
        self.sum_bonus._row.setContentsMargins(24, 8, 20, 8)
        self.sum_bonus._cap.setStyleSheet(
            f"color: {t.ACCENT}; background: transparent; font-weight: 700;"
            " font-size: 16px;")
        self.sum_bonus.mousePressEvent = lambda _e: self.on_points()
        for w in (self.sum_subtotal, self.sum_discount, self.sum_bonus):
            box.addWidget(w)
            w.hide()

        # Katta JAMI + to'lov — HAJMLI zumrad bar (gradient: tepasi yorug',
        # pasti to'q), bosilsa to'lovga o'tadi.
        bar = QWidget()
        bar.setFixedHeight(t.TOTAL_BAR_HEIGHT)
        bar.setCursor(Qt.PointingHandCursor)
        bar.setStyleSheet(f"background: {t.ACCENT}; border-radius: 12px;")
        row = QHBoxLayout(bar)
        row.setContentsMargins(24, 0, 20, 0)

        row.addWidget(_label(tr("JAMI"), 13, "#D6F5E4", bold=True))
        row.addStretch(1)
        self.total_label = _label("0", 30, "#FFFFFF", bold=True)
        row.addWidget(self.total_label)
        row.addSpacing(10)
        chev = QLabel()
        chev.setPixmap(icons.pixmap("chevron", 24, "#BFE0C9"))
        chev.setStyleSheet("background: transparent;")
        row.addWidget(chev)
        bar.mousePressEvent = lambda _e: self.open_payment()

        box.addWidget(bar)
        pay = QPushButton(tr("TO'LOV") + "  ·  F9")
        pay.setMinimumHeight(48)
        pay.setCursor(Qt.PointingHandCursor)
        pay.setStyleSheet(
            f"QPushButton {{background: {t.ACCENT_PALE}; color: {t.ACCENT_DARK};"
            f"border: none; border-radius: 10px; font-size: 16px; font-weight: 700;}}"
            f"QPushButton:hover {{background: {t.SURFACE_2};}}")
        pay.clicked.connect(self.open_payment)
        box.addSpacing(8)
        box.addWidget(pay)
        return wrap

    # ------------------------------------------------------------ tugmalar

    def _shortcuts(self) -> None:
        for key, handler in (
            ("F2", self.on_quantity),
            ("F3", self.on_customer),
            ("F4", self.on_discount),
            ("F5", self.on_points),
            ("F9", self.open_payment),
            ("F10", self.on_shift),
            ("Delete", self.on_delete),
        ):
            QShortcut(QKeySequence(key), self, handler)

    # ------------------------------------------------------------ harakatlar

    def _add_to_cart(self, product, quantity=1) -> bool:
        """Chekka qo'shishning YAGONA yo'li — qoldiq nazorati shu yerda.

        Panelda «Qoldiqlarni hisobga olish» yoqilgan bo'lsa, omborda
        yo'q tovarni sotib bo'lmaydi: kassir shu yerda to'xtatiladi.
        Chekda allaqachon turgan miqdor ham hisobga olinadi.
        """
        from decimal import Decimal

        check = getattr(self.backend, "check_stock", None)
        if check:
            already = sum(
                (line.quantity for line in self.cart.lines
                 if line.product.id == product.id),
                Decimal(0),
            )
            problem = check(product, Decimal(str(quantity)) + already)
            if problem:
                self.flash(problem)
                return False
        self.cart.add(product, quantity)
        self.refresh()
        return True

    def on_scan(self) -> None:
        code = self.scan_input.text().strip()
        # Kodni har doim tozalaymiz — muvaffaqiyatsiz ham. Aks holda
        # eski kod maydonda qolib, keyingi skaner ustiga yozadi.
        self.scan_input.clear()
        self.scan_input.setFocus()
        if not code:
            return

        # 1. Tovar shtrix-kodi
        found = self.backend.find_by_barcode(code)
        if found is not None:
            product, quantity = found
            self._add_to_cart(product, quantity)
            return

        # 2. Tovar emas — mijoz kartasi (nakopitelniy) bo'lishi mumkin
        finder = getattr(self.backend, "find_customer_by_code", None)
        customer = finder(code) if finder else None
        if customer is not None:
            self.cart.customer = customer
            self.refresh()
            self.flash(f"Mijoz: {customer.name}")
            return

        self.flash(tr("Tovar topilmadi"))

    def on_search(self, text: str) -> None:
        """Qidiruv maydoni o'zgardi.

        Skaner ham shu maydonga yozadi: 13 ta raqam + Enter, keyin maydon
        tozalanadi. Ilgari birinchi raqamda ham, tozalanganda ham ro'yxat
        qaytadan chizilardi — har skanerda 2 marta bekor ish. Endi:
          - raqamlar ro'yxatga umuman tegmaydi (bu skaner);
          - ro'yxat faqat so'rov HAQIQATAN o'zgarganda chiziladi;
          - matn yozilayotganda 180 ms kutamiz — har harfda emas,
            kassir yozib bo'lganda bir marta qidiramiz.
        """
        text = text.strip()
        if text.isdigit():
            return
        query = "" if len(text) < 2 else text
        if query == self._catalog_query:
            self._search_timer.stop()
            return
        self._pending_query = query
        self._search_timer.start()

    def _run_search(self) -> None:
        query = self._pending_query
        if query == self._catalog_query:
            return
        self._catalog_query = query
        self.fill_catalog(self.backend.search(query))

    def on_catalog_pick(self, item: QListWidgetItem) -> None:
        product = item.data(Qt.UserRole)
        if product:
            self._add_to_cart(product)

    def eventFilter(self, obj, event):
        """Katalogда o'ng chekkadagi yulduzchaga bosilса — tovarni «sevimli»
        qiladi (savatga qo'shmaydi). Sevimlilar ro'yxat tepasида turadi."""
        if (obj is self.catalog_list.viewport()
                and event.type() == QEvent.MouseButtonPress):
            pos = event.position().toPoint()
            item = self.catalog_list.itemAt(pos)
            if item is not None:
                # Yulduzcha katakchasi — kartaning yuqori-o'ng burchagi
                # (delegatdagi geometriya bilan bir xil hisoblanadi).
                D = _CatalogDelegate
                rect = self.catalog_list.visualItemRect(item)
                card = rect.adjusted(D.MARGIN, D.MARGIN, -D.MARGIN, -D.MARGIN)
                star = QRect(card.right() - D.STAR_BOX, card.top(),
                             D.STAR_BOX, D.STAR_BOX)
                if star.contains(pos):
                    toggle = getattr(self.backend, "toggle_favorite", None)
                    product = item.data(Qt.UserRole)
                    if product is not None and toggle:
                        toggle(product.id)
                        q = self.scan_input.text().strip()
                        query = q if (len(q) >= 2 and not q.isdigit()) else ""
                        self.fill_catalog(self.backend.search(query))
                    return True  # yutamiz — savatga qo'shilmaydi
        return super().eventFilter(obj, event)

    def _receipt_index(self, item: QListWidgetItem | None) -> int:
        """Ekrandagi qator → cart.lines dagi haqiqiy o'rin.

        Ro'yxat teskari ko'rsatiladi (oxirgisi tepada), shuning uchun
        ekran raqamiga emas, qatorга yozilgan haqiqiy o'ringa (data)
        qaraymiz."""
        if item is None:
            return -1
        idx = item.data(Qt.UserRole)
        if idx is None or not (0 <= int(idx) < len(self.cart.lines)):
            return -1
        return int(idx)

    def on_delete(self) -> None:
        index = self._receipt_index(self.receipt_list.currentItem())
        if index >= 0:
            self.cart.remove(index)
            self.refresh()

    def on_quantity(self) -> None:
        index = self._receipt_index(self.receipt_list.currentItem())
        if index < 0:
            return
        value = self.backend.ask_quantity(self.cart.lines[index])
        if value is not None:
            self.cart.set_quantity(index, Decimal(value))
            self.refresh()

    def on_receipt_tap(self, item: QListWidgetItem) -> None:
        """Chek qatoriga bosilganda: miqdorni o'zgartirish yoki o'chirish.

        Pastdagi «Miqdor»/«O'chirish» tugmalari olib tashlangani uchun
        endi shu ish qatorning o'zini bosib bajariladi.
        """
        from .dialogs import QuantityDialog

        index = self._receipt_index(item)
        if index < 0:
            return
        dialog = QuantityDialog(self.cart.lines[index], self)
        if dialog.exec() != QuantityDialog.Accepted:
            return
        if dialog.deleted:
            self.cart.remove(index)
            self.refresh()
        elif dialog.quantity is not None:
            self.cart.set_quantity(index, Decimal(dialog.quantity))
            self.refresh()

    def on_customer(self) -> None:
        from ..hub import ASK_CANCEL

        result = self.backend.ask_customer()
        if result is ASK_CANCEL:
            return  # kassir bekor qildi — hech nima o'zgarmaydi
        # result: Customer (tanlandi) yoki None («Mijozsiz» — olib tashlash).
        old_id = self.cart.customer.id if self.cart.customer else None
        new_id = result.id if result else None
        self.cart.customer = result
        # Mijoz o'zgardi — oldingi ball to'lovi endi to'g'ri kelmaydi
        # (balans boshqa), nolga tushiramiz.
        if new_id != old_id:
            self.cart.set_points_amount(0)
        self.refresh()

    def on_points(self) -> None:
        """Ball ishlatish — mijozning ballaridan chek to'loviga."""
        if self.cart.is_empty:
            self.flash(tr("Chek bo'sh"))
            return
        if not self.cart.customer:
            self.flash(tr("Avval mijoz tanlang"))
            return
        balance = self.cart.customer.bonus_points
        if balance <= 0:
            self.flash(tr("Mijozda ball yo'q"))
            return
        max_balls = self.cart.max_points // 100
        if max_balls <= 0:
            self.flash(tr("Bu chekda ball ishlatib bo'lmaydi"))
            return
        balls = self.backend.ask_points(balance, max_balls, self.cart.points_spent)
        if balls is not None:
            self.cart.set_points_amount(balls * 100)
            self.refresh()

    def _header_icon_button(self, name: str, handler, tip: str = ""):
        """Ustki chiziqdagi shaffof-oq ikona tugmasi (menyu, sozlama)."""
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedSize(50, 50)
        btn.setIcon(icons.icon(name, 22, t.INK_SOFT))
        btn.setIconSize(icons.button_icon_size(22))
        if tip:
            btn.setToolTip(tip)
        btn.setStyleSheet(
            "QPushButton { background: rgba(16,61,50,0.06); border: none;"
            " border-radius: 10px; }"
            "QPushButton:hover { background: rgba(16,61,50,0.10); }"
            "QPushButton:pressed { background: rgba(16,61,50,0.16); }"
        )
        btn.clicked.connect(handler)
        return btn

    def open_settings(self) -> None:
        """Sozlamalar (printer va b.) — menyudagi bilan bir xil yo'l."""
        handler = getattr(self.backend, "menu_action", None)
        if handler:
            handler("settings")

    def on_menu(self) -> None:
        """Menyu — qo'shimcha amallar."""
        from .dialogs import MenuDialog

        subtitle = self.shift_label.text() if hasattr(self, "shift_label") else ""
        dialog = MenuDialog(self, title_text=self.windowTitle(), subtitle=subtitle)
        if dialog.exec() != MenuDialog.Accepted or not dialog.action:
            return

        handler = getattr(self.backend, "menu_action", None)
        if handler:
            handler(dialog.action)

    def on_shift(self) -> None:
        """Smenani yopish. Chek bo'sh bo'lmasa — ogohlantiramiz."""
        if not self.cart.is_empty:
            self.flash(tr("Avval chekni yakunlang yoki tozalang"))
            return
        handler = getattr(self.backend, "close_shift", None)
        if handler:
            handler()

    def on_discount(self) -> None:
        percent = self.backend.ask_discount(self.cart.receipt_discount)
        if percent is not None:
            self.cart.receipt_discount = percent
            self.refresh()

    def open_payment(self) -> None:
        if self.cart.is_empty:
            self.flash(tr("Chek bo'sh"))
            return

        dialog = PaymentDialog(self.cart.total, self.backend.methods, self)
        if dialog.exec() != PaymentDialog.Accepted:
            return

        try:
            self.backend.submit(self.cart, dialog.plan)
        except Exception as e:  # tarmoq yoki baza xatosi
            self.flash(f"Saqlanmadi: {e}")
            return

        # Mijoz cheki — savat tozalanmasdan oldin (undan chek yig'iladi).
        # Chop etish muvaffaqiyatsiz bo'lsa ham savdo saqlangan, xato emas.
        if self.print_sale:
            try:
                self.print_sale(self.cart, dialog.plan)
            except Exception as e:
                logger = __import__("logging").getLogger("pos")
                logger.warning("Chek chiqmadi: %s", e)

        self.cart.clear()
        self.refresh()
        self.scan_input.setFocus()
        self.sale_finished.emit()

    def set_price_type(self, name: str, is_default: bool, switchable: bool) -> None:
        """Sarlavhadagi narx turi tugmasini yangilaydi."""
        if not name:
            self.price_btn.hide()
            return
        self.price_btn.setText(name if switchable else f"{name}")
        self.price_btn.setEnabled(switchable)
        self.price_btn.show()
        if is_default:
            self.price_btn.setStyleSheet(
                "QPushButton { background: #E8F4ED; color: #103D32;"
                " border: none; border-radius: 8px; padding: 0 14px; }"
                "QPushButton:pressed { background: rgba(16,61,50,0.16); }"
            )
        else:
            self.price_btn.setStyleSheet(
                "QPushButton { background: #B8791F; color: #FFFFFF;"
                " border: none; border-radius: 8px; padding: 0 14px; }"
                "QPushButton:pressed { background: #9A661A; }"
            )

    def flash(self, message: str) -> None:
        """Qisqa xabar — status qatorida."""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {t.DANGER}; font-size: 12px;")

    # ------------------------------------------------------------ chizish

    @staticmethod
    def _row_widget(title: str, subtitle: str, amount: str,
                    amount_size: int = 15, low_stock: bool = False) -> QWidget:
        """Ikki ustunli qator: chapda nom, o'ngda summa.

        Summalar bir ustunda tursin — kassir ularni ko'z bilan
        solishtira olishi kerak, matn ichida sochilib ketmasin.
        """
        w = QWidget()
        w.setStyleSheet("QWidget { background: transparent; border: none; }")
        w.setMinimumHeight(58)
        row = QHBoxLayout(w)
        # Bo'shliq qator vidjetining ichida — QListWidget'ning padding'i
        # setItemWidget bilan qo'yilgan vidjetga ta'sir qilmaydi
        row.setContentsMargins(18, 9, 22, 9)
        row.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(_label(title, 16, t.INK, bold=True))
        if subtitle:
            # Qoldiq nol bo'lsa — rangi o'zgaradi. Sotib bo'lmaydi degani
            # emas, lekin kassir buni ko'rib turishi kerak.
            left.addWidget(_label(subtitle, 12.5, t.DANGER if low_stock else t.MUTED))
        row.addLayout(left, 1)

        value = _label(amount, amount_size, t.INK, bold=True)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value.setMinimumWidth(120)
        row.addWidget(value)
        return w

    def _add_row(self, listw: QListWidget, widget: QWidget, data=None) -> None:
        item = QListWidgetItem()
        # Qator balandligi vidjetning minimumHeight'idan kam bo'lmasin:
        # sensorli ekranda barmoq tegadigan joy kerak, aks holda
        # minimumSizeHint matn balandligini beradi va qatorlar siqilib
        # qoladi.
        hint = widget.minimumSizeHint()
        hint.setHeight(max(hint.height(), widget.minimumHeight()))
        item.setSizeHint(hint)
        if data is not None:
            item.setData(Qt.UserRole, data)
        listw.addItem(item)
        listw.setItemWidget(item, widget)

    def fill_catalog(self, products: list[Product]) -> None:
        """Katalog qatorlari: chapda nom, o'ngda narx.

        Qatorlar alohida vidjet EMAS — delegat to'g'ridan-to'g'ri
        chizadi. Ilgari har qator uchun QWidget yasalardi: 200 qator
        ≈ yarim soniya, kuchsiz monoblokda 1-2 soniya. Va bu har
        skanerdan keyin 2 marta takrorlanardi — kassir «sekin» degani
        shu edi. Endi 200 qator bir necha millisekund.

        Nom ostidagi kod va qoldiq raqamlari yo'q: kassir tovarni
        nomidan topadi, kod skanerga tegishli. Qoldiqdan bittasi
        qoldi — tovar tugagan bo'lsa nomi yonida «yo'q» belgisi.
        """
        # Tashqaridan (sinxronizatsiyadan keyin) chaqirilganda ham
        # maydon bilan mos holatni eslab qolamiz.
        current = self.scan_input.text().strip() if hasattr(self, "scan_input") else ""
        if not current.isdigit():
            self._catalog_query = "" if len(current) < 2 else current

        lst = self.catalog_list
        lst.setUpdatesEnabled(False)
        lst.clear()
        fav = getattr(self.backend, "is_favorite", None)
        D = _CatalogDelegate
        for p in products:
            gone = bool(p.stock is not None and p.stock <= 0)
            unit = "kg" if p.is_weight else tr("dona")
            stock_txt = ""
            if p.stock is not None and not gone:
                stock_txt = (f"{p.stock:g}" if p.is_weight else f"{int(p.stock)}")
            item = QListWidgetItem()
            item.setData(Qt.UserRole, p)
            item.setData(D.NAME, p.name)
            item.setData(D.PRICE, som(p.price))
            item.setData(D.UNIT, unit)
            item.setData(D.STOCK, stock_txt)
            item.setData(D.GONE, gone)
            item.setData(D.FAV, bool(fav(p.id)) if fav else False)
            # Kelajakda MoySklad rasmi bo'lsa — bu yerda item.setData(
            # Qt.DecorationRole, QPixmap(...)) qo'yiladi; delegat o'zi chizadi.
            item.setToolTip(p.name)
            lst.addItem(item)
        lst.setUpdatesEnabled(True)

    def refresh(self) -> None:
        # Bo'sh bo'lsa logotip, aks holda chek ro'yxati
        empty = self.cart.is_empty
        self.receipt_stack.setCurrentIndex(0 if empty else 1)

        # «Mijoz» qatori endi DOIM oq fonli — matn ham doim to'q rangда
        # (ilgari bo'sh holatда oq matn edi va logo foni ustida ko'rinmasdi).
        # Mijoz tanlanmagan bo'lsa — «tanlash uchun bosing» (accent, ishorat);
        # tanlangan bo'lsa — ism + ball (to'q).
        has_customer = bool(self.cart.customer)
        self.customer_row._label.setStyleSheet(
            f"color: {t.INK if has_customer else t.ACCENT};"
            " background: transparent; border: none;"
        )

        self.receipt_list.clear()
        extra = self.cart.extra_percent
        total = len(self.cart.lines)
        # Eng oxirgi urilgan tovar TEPADA turadi — kassir nimani urganini
        # darhol ko'rsin. Raqam esa skanerlangan tartibda qoladi (tepada
        # eng katta raqam). Har qatorга cart.lines dagi haqiqiy o'rni
        # (data) yoziladi — bosilganda to'g'ri qator tahrirlanadi.
        for offset, line in enumerate(reversed(self.cart.lines)):
            idx = total - 1 - offset
            unit = " kg" if line.product.is_weight else ""
            widget = self._row_widget(
                f"{idx + 1}.  {line.product.name}",
                f"{qty_str(line.quantity)}{unit} × {som(line.product.price)}",
                som(line.net(extra)),
            )
            self._add_row(self.receipt_list, widget, data=idx)

        # Chek o'zgargan bo'lsa (qator o'chdi, miqdor kamaydi) ball
        # chegaradan oshib qolmasin — qayta chegaralaymiz.
        if self.cart.points_amount:
            self.cart.set_points_amount(self.cart.points_amount)

        self.total_label.setText(som(self.cart.total))
        self.receipt_title.setText(
            tr("Chek") if self.cart.is_empty else f"Chek · {self.cart.count} qator"
        )

        # Checkout tafsiloti — chegirma/ball bo'lsagina ko'rsatamiz.
        disc = self.cart.discount_total
        bonus = self.cart.points_amount
        has_reduction = bool(disc or bonus)
        self.sum_subtotal.setVisible(has_reduction)
        self.sum_discount.setVisible(bool(disc))
        if has_reduction:
            self.sum_subtotal._val.setText(som(self.cart.gross_total))
        if disc:
            self.sum_discount._val.setText("− " + som(disc))
            self.sum_discount._val.setStyleSheet(
                f"color: {t.WARN}; background: transparent; border: none;")

        # «Ball bilan» qatori: mijozда ball bo'lsa DOIM ko'rinadi va
        # bosilса ball ishlatish oynasini ochadi (kassir uchun yagona yo'l).
        cust = self.cart.customer
        can_use_points = bool(
            cust and cust.bonus_points > 0 and not self.cart.is_empty
        )
        self.sum_bonus.setVisible(bool(bonus) or can_use_points)
        _big = (f"color: {t.ACCENT}; background: transparent; border: none;"
                " font-size: 18px; font-weight: 700;")
        if bonus:
            # Ball ishlatilgan — qatorni oq fon, o'ngда «− X ✎» katta.
            self.sum_bonus.setStyleSheet("background: transparent;")
            self.sum_bonus._cap.setText(tr("Ball bilan"))
            self.sum_bonus._val.setText("− " + som(bonus) + "   ✎")
            self.sum_bonus._val.setStyleSheet(_big)
        elif can_use_points:
            # Ishlatilmagan — accent-tinted «tugma»: katta «Ball ishlatish →».
            self.sum_bonus.setStyleSheet(
                f"background: {t.ACCENT_PALE}; border-top: 1px solid {t.LINE};")
            self.sum_bonus._cap.setText(tr("★ Ball ishlatish"))
            self.sum_bonus._val.setText("→")
            self.sum_bonus._val.setStyleSheet(_big)

        if self.cart.customer:
            c = self.cart.customer
            bits = [c.name]
            if c.bonus_points:
                bits.append(f"{c.bonus_points} ball")
            if c.discount_percent:
                bits.append(f"daraja {c.discount_percent:g}%")
            self.customer_row._label.setText("   ·   ".join(bits))
        else:
            self.customer_row._label.setText(tr("tanlash uchun bosing"))
