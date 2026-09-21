"""
Kassa ilovasi — ishga tushirish nuqtasi.

    python -m pos.main

Windows'da bu fayl `SevimliKassa.exe` ga aylanadi (build/ papkasiga qarang).

Birinchi ishga tushirishda faqat kassa logini va paroli so'raladi (panel →
Kassalar). Server manzili dasturning ichida. EXE o'zini o'rnatadi —
alohida o'rnatuvchi yo'q (pos/installer.py).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config as cfg
from . import i18n
from .i18n import tr
from .hub import Hub, HubAuthError, HubBusyError, HubError, LiveBackend, settings_fingerprint
from .store import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(cfg.config_dir() / "kassa.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("pos")


def ask_setup(config: cfg.Config) -> bool:
    """Birinchi ishga tushirish: server manzili, kassa logini va paroli.

    Hammasi bitta oynada, ekran klaviaturasi bilan — kassada jismoniy
    klaviatura yo'q. Token so'ralmaydi: ilova uni login-parol evaziga
    o'zi oladi va saqlaydi. Xodim 43 belgili tokenni ko'chirmaydi.
    """
    from .ui.dialogs import SetupDialog

    def connect_fn(url: str, login: str, password: str) -> dict:
        # Har urinishda yangi manzil bilan sinaymiz. HubError chiqsa —
        # oyna uni o'zi ko'rsatadi (server o'chiq / login xato).
        config.server_url = url
        return Hub(config).connect(login.lower(), password)

    dialog = SetupDialog(config.server_url, connect_fn)
    if dialog.exec() != SetupDialog.Accepted or not dialog.result:
        return False

    config.server_url = dialog.server_url
    config.token = dialog.result["token"]
    cfg.save(config)

    QMessageBox.information(
        None, tr("Ulandi"),
        f"{dialog.result['point']} · {dialog.result['register']['name']}\n\n" +
        tr("Endi bu so'ralmaydi."),
    )
    return True


def open_shift(backend, cashier: dict) -> dict | None:
    """Smena ochish: razmen puli. Kassir allaqachon kirgan.

    Internet bo'lsa — serverда, bo'lmasa MAHALLIY ochiladi (kassa
    to'xtamaydi). Internet qaytganda smena o'zi serverга ochiladi.
    """
    from .ui.dialogs import OpeningCashDialog

    dialog = OpeningCashDialog(cashier["name"])
    if dialog.exec() != OpeningCashDialog.Accepted:
        return None

    try:
        return backend.open_shift(cashier, dialog.tiyin or 0)
    except Exception as e:  # backend oflaynда ham smena qaytaradi
        QMessageBox.critical(None, tr("Smena ochilmadi"), str(e))
        return None


# Ilova chiqish kodlari — KASSA.bat shu bo'yicha xabar ko'rsatadi:
#   0  — hammasi joyida
#   1  — haqiqiy nosozlik (kutilmagan xato). «XATOLIK» ko'rsatiladi.
#   2  — kutilgan chiqish (kassir bekor qildi, server topilmadi va h.k.).
#         Foydalanuvchiga allaqachon tushunarli oyna ko'rsatilgan —
#         qora oynada qo'rqinchli «XATOLIK» chiqmasligi kerak.
EXIT_OK = 0
EXIT_CRASH = 1
EXIT_HANDLED = 2


def main() -> int:
    # Yagona fayl: Telegram/fleshkadan ochilgan exe avval o'zini
    # o'rnatadi (yorliqlar, avto-ishga tushish) va o'rnatilgan nusxani
    # ochadi. O'rnatilgan joydan ishlayotgan bo'lsak — davom etamiz.
    from . import installer

    if installer.ensure_installed():
        return EXIT_OK

    # Allaqachon o'rnatilgan bo'lsak ham — avtoyuklanish yozuvi joyidami,
    # tekshiramiz. Yorliq yaratilmay qolgan eski o'rnatmalar ham shu tufayli
    # bundan keyin Windows'ga kirganda o'zi ochiladi.
    installer.ensure_autostart()

    # Bitta kompyuterda — bitta nusxa. Kassir dastur ochilishini kutmay
    # yana bossa, ikkinchi nusxa ochilmaydi: birinchisining oynasi
    # oldinga chiqadi va bu nusxa jimgina yopiladi. Ikki nusxa bitta
    # kassa.db ga yozsa smena holati chalkashadi (2026-09-19).
    from . import single
    if not single.acquire():
        logger.info("Kassa allaqachon ochiq — ikkinchi nusxa yopilmoqda")
        single.raise_existing_window()
        return EXIT_OK

    # Sog'liq bayrog'i: shu nuqtaga yetdik — exe ochildi va Python yuklandi.
    # Yangilash skripti shu bayroqni kutadi; paydo bo'lmasa rollback qiladi.
    from . import updater as _upd
    _upd.mark_started()

    app = QApplication(sys.argv)
    app.setApplicationName("Sevimli Kassa")

    # ── Tipografiya: butun UI uchun yagona font ──────────────────────
    # Birlamchi — Inter (pos/fonts/ ichida .ttf bo'lsa yuklanadi).
    # Bo'lmasa — Segoe UI (barcha Windows'da bor). app.setFont barcha
    # oynalarga meros bo'ladi, shuning uchun bitta joydan boshqariladi.
    from PySide6.QtGui import QFont, QFontDatabase
    from .ui import theme as _t

    fonts_dir = Path(__file__).resolve().parent / "fonts"
    if fonts_dir.is_dir():
        for _ttf in fonts_dir.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(_ttf))
    _families = set(QFontDatabase.families())
    _family = _t.FONT_FAMILY if _t.FONT_FAMILY in _families else next(
        (f for f in _t.FONT_FALLBACK if f in _families), "Segoe UI")
    _base = QFont(_family)
    _base.setPixelSize(_t.FS_BODY)
    app.setFont(_base)

    # Belgi — vazifalar panelida va oyna sarlavhasida
    icon_path = Path(__file__).resolve().parent / "sevimli-kassa.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    config = cfg.load()
    i18n.set_lang(config.language)
    if not config.is_ready and not ask_setup(config):
        # Sozlash bekor qilindi yoki ulanmadi — oyna ko'rsatilgan.
        return EXIT_HANDLED

    hub = Hub(config)
    store = Store(cfg.config_dir() / "kassa.db")

    # Yangilanish halqasi hisobini tozalash: joriy versiya oxirgi urinilgan
    # versiyaga yetgan (yoki undan yangi) bo'lsa — demak o'rnatildi, hisob
    # tozalanadi, keyingi yangilanishlar oddiy boradi.
    try:
        import json as _j0

        from .version import VERSION as _CUR, is_newer as _isn

        _last = _j0.loads(store.get("upd_last") or "{}")
        if _last.get("version") and not _isn(_last["version"], _CUR):
            store.set("upd_last", "")
    except Exception:
        pass

    # Ulanishni tekshiramiz. MUHIM (UZILMASLIK): server javob bermasa ham
    # kassa TO'XTAMAYDI — oxirgi muvaffaqiyatli javob keshdan olinadi va
    # OFLAYN davom etadi. Cheklar lokalда navbatга tushadi, aloqa tiklangach
    # fon oqimi o'zi yuboradi. Kesh umuman yo'q bo'lsa (eng birinchi
    # ochilish) — avvalgidek qayta sozlashni taklif qilamiz.
    import json as _json

    offline = False
    while True:
        try:
            info = hub.hello()
            store.set("last_hello", _json.dumps(info, ensure_ascii=False))
            break
        except HubAuthError as e:
            # Token bekor qilingan (panelda «Aloqani uzish» yoki kassa
            # o'chirilgan). Kesh bilan oflayn davom etish XATO bo'lardi —
            # cheklar hech qachon serverga yetmaydi. Qayta ulanamiz.
            logger.warning("Token rad etildi: %s — qayta ulanish so'raladi", e)
            QMessageBox.warning(
                None, tr("Qayta ulanish kerak"),
                tr("Server bu kassani tanimadi (aloqa uzilgan yoki kassa o'chirilgan).")
                + "\n\n" + tr("Paneldagi kassa logini va parolini kiriting."),
            )
            config.token = ""
            if not ask_setup(config):
                return EXIT_HANDLED
            hub = Hub(config)
            continue
        except HubError as e:
            cached = store.get("last_hello")
            if cached:
                info = _json.loads(cached)
                offline = True
                logger.warning(
                    "Server ulanmadi (%s) — keshlangan ma'lumot bilan OFLAYN "
                    "davom etamiz", e,
                )
                break
            retry = QMessageBox.question(
                None, tr("Ulanmadi"),
                f"{e}\n\n"
                "Server (panel) yoniq bo'lishi kerak.\n\n"
                "Qayta sozlaysizmi?\n"
                "(kassa logini va paroli)",
                QMessageBox.Yes | QMessageBox.No,
            )
            if retry != QMessageBox.Yes or not ask_setup(config):
                return EXIT_HANDLED
            hub = Hub(config)

    # Kirish ekrani oynaning ichida (pastda, LoginScreen). Bu yerda faqat
    # holatni eslab qolamiz: smena bormi, kim ochgan.
    shift = info.get("shift")
    cashier = None
    if shift:
        logger.info("Smena ochiq (%s) — kirish ekranida PIN so'raladi", shift.get("cashier"))

    backend = LiveBackend(hub, store, info["payment_methods"])
    backend.setup_price_types(
        info.get("price_types") or [], info.get("default_price_type") or ""
    )

    # Server ochiq smena ko'rsatmasa, lekin diskda internetsiz ochilgan
    # smena bo'lsa — o'shani tiklaymiz. Kassir dastur qayta ochilganda
    # razmen pulini qaytadan kiritmaydi, smena joyida turaveradi.
    if not shift:
        local = store.get_local_shift()
        if local:
            shift = {
                "id": None,
                "number": "—",
                "cashier": local.get("cashier", ""),
                "opened_at": local.get("opened_at", ""),
                "opening_cash": int(local.get("opening_cash") or 0),
                "next_receipt_number": int(local.get("next_receipt") or 1),
            }
            logger.info("Internetsiz ochilgan smena tiklandi (kassir: %s)",
                        local.get("cashier"))

    # Katalog bo'sh bo'lsa — birinchi to'liq yuklash
    if store.product_count() == 0:
        try:
            count = backend.sync_catalog()
            logger.info("Katalog yuklandi: %s tovar", count)
        except HubError as e:
            QMessageBox.warning(None, tr("Katalog"), f"Katalog yuklanmadi: {e}")

    from .ui.dialogs import (
        CashDialog,
        CloseShiftDialog,
        CustomerDialog,
        DiscountDialog,
        PointsDialog,
        QuantityDialog,
        ReceiptDialog,
    )
    from .ui.main_window import MainWindow

    window = MainWindow(backend, animated_bg=config.animated_bg)
    window.setWindowTitle(
        f"Sevimli Kassa — {info['point']} · {info['register']['name']}"
    )
    window.fill_catalog(backend.search(""))
    if shift:
        window.shift_label.setText(f"Smena #{shift['number']} · {shift['cashier']}")

    # ---------------------------------------------------- kirish ekrani
    #
    # Dastur ochilganda va «Chiqish» dan keyin — kassir tanlash + PIN.
    # Dastur yopilmaydi, faqat kirish ekraniga qaytadi (MoySklad'dagidek).
    # Dasturni butunlay yopish — kirish ekranidagi «Dasturni yopish».
    from .ui.login_screen import LoginScreen

    login_screen = LoginScreen(
        window, info.get("point", ""), (info.get("register") or {}).get("name", ""),
        show_keyboard=store.get("login_screen_keyboard", "0") == "1",
    )
    # Ekran klaviaturasi tanlovi shu kassada eslab qolinadi
    login_screen.keyboard_toggled.connect(
        lambda on: store.set("login_screen_keyboard", "1" if on else "0"))

    session = {"shift": shift, "cashier": cashier, "offline": offline}

    def _shift_caption(sh: dict) -> str:
        # Internetsiz ochilgan smenada raqam hali yo'q ("—") — kassirга
        # «oflayn» deb ko'rsatamiz, internet qaytganda haqiqiy raqam chiqadi.
        if sh.get("id") is None or sh.get("number") in ("—", None, ""):
            return tr("Smena (oflayn) · {c}").format(c=sh.get("cashier", ""))
        return f"Smena #{sh['number']} · {sh['cashier']}"

    # Chek raqami — smena boshidan. Har chekda bittaga oshadi. Serverdagi
    # haqiqiy raqam bilan mos keladi (bitta kassa = bitta smena).
    sale_no = {"n": 1}

    def _history_tag(sh: dict) -> str:
        """Smenaning barqaror belgisi — tarixда «shu smenadagi cheklar» uchun.
        Onlayn smenada server id, oflaynda mahalliy uuid. Smena davomida
        (oflayn→onlayn sinxronда ham) o'zgarmaydi, chunki faqat shu yerда,
        smenaga kirilганда o'rnatiladi."""
        if sh.get("id"):
            return f"srv:{sh['id']}"
        local = store.get_local_shift()
        if local and local.get("local_uuid"):
            return f"loc:{local['local_uuid']}"
        return f"loc:{sh.get('opened_at', '')}"

    def _enter_kassa(sh: dict) -> None:
        session["shift"] = sh
        if sh.get("id"):
            store.set("active_shift_id", str(sh["id"]))
        # Bundan keyingi cheklar shu smenaga tegishli deb belgilanadi.
        store.set("history_shift_tag", _history_tag(sh))
        sale_no["n"] = int(sh.get("next_receipt_number") or 1)
        window.shift_label.setText(_shift_caption(sh))
        window.centralWidget().setEnabled(True)
        login_screen.hide()
        window.scan_input.setFocus()

    def _print_sale(cart, plan) -> None:
        """Savdo tugagach mijoz chekini chiqaradi (avtomatik)."""
        if not config.auto_print:
            return
        from datetime import datetime

        from . import printer
        from .money import qty_str
        from shared.receipt import PaymentLine, SaleItem, SaleReceipt, render_sale

        extra = cart.extra_percent
        items = [
            SaleItem(
                name=line.product.name,
                qty=qty_str(line.quantity),
                price=line.product.price,
                total=line.net(extra),
            )
            for line in cart.lines
        ]
        names = {m["code"]: m for m in backend.methods}
        pays = [
            PaymentLine(
                name=(names.get(p.method, {}).get("name") or p.method),
                amount=p.amount,
                is_cash=bool(names.get(p.method, {}).get("is_cash")),
            )
            for p in plan.parts
        ]
        change = sum(p.change or 0 for p in plan.parts)
        sh = session.get("shift") or {}
        price_type = ""
        if not getattr(backend, "price_type_is_default", True):
            price_type = getattr(backend, "price_type_name", "") or ""

        # Bonus — mijoz cheki uchun. Balans server bilan bir xil formula
        # bilan hisoblanadi (sarflandi − , berildi +), shuning uchun
        # internetsiz ham to'g'ri chiqadi.
        spent = cart.points_spent
        earned = cart.points_earned()
        balance_after = None
        if cart.customer:
            balance_after = cart.customer.bonus_points - spent + earned

        receipt = SaleReceipt(
            market=info.get("market", "Sevimli Market"),
            point=info.get("point", ""),
            cashier=(session.get("cashier") or {}).get("name", ""),
            shift_no=sh.get("number", "—"),
            number=backend.last_receipt_number,
            when=datetime.now(),
            items=items,
            gross_total=cart.gross_total,
            discount_total=cart.discount_total,
            net_total=plan.total,
            payments=pays,
            change=change,
            price_type=price_type,
            points_spent=spent,
            points_earned=earned,
            balance_after=balance_after,
        )
        # Kenglik — foydalanuvchi tanlagan qog'oz o'lchamiga qarab (80/58mm)
        text = render_sale(receipt, config.receipt_width)
        printer.print_sale(text, config.printer, config.paper,
                           config.receipt_width, name="chek")
        sale_no["n"] += 1

    window.print_sale = _print_sale

    def _apply_shift_synced(sh: dict) -> None:
        """Internetsiz ochilgan smena serverга ochildi — raqamni yangilaymiz."""
        cur = session.get("shift")
        if cur and cur.get("id") is None and sh:
            session["shift"] = sh
            window.shift_label.setText(_shift_caption(sh))
            window.flash(tr("Smena serverga ochildi (#{n})").format(n=sh.get("number")))

    def _show_login(keep_login: str = "") -> None:
        window.centralWidget().setEnabled(False)
        sh = session.get("shift")
        if session["offline"]:
            login_screen.set_status(tr("Oflayn — server bilan aloqa yo'q"))
        elif sh:
            login_screen.set_status(
                tr("Smena #{n} ochiq · {c}").format(n=sh["number"], c=sh["cashier"])
            )
        else:
            login_screen.set_status(tr("Smena yopiq — kirgach razmen puli so'raladi"))
        login_screen.open(keep_login)

    # ---------------------------------------------------- eslab qolish
    #
    # Kassir kirgach login «Chiqish» bosilguncha eslab qolinadi: smena
    # yopib-ochilganda, dastur yangilanganda, kompyuter o'chib-yonganda —
    # parol qayta so'ralmaydi. Server ham buni biladi («bir login — bir
    # kompyuter»): qayta ochilganda `session/resume` bilan parolsiz davom
    # etiladi, boshqa kompyuter shu login bilan kirib olgan bo'lsa — 409
    # va kirish ekrani.
    LOGIN_KEY = "login_session"

    def _save_login(who: dict) -> None:
        try:
            store.set(LOGIN_KEY, _json.dumps(
                {"cashier": who, "session": getattr(hub, "session", "") or ""},
                ensure_ascii=False,
            ))
        except Exception as e:
            logger.info("Login saqlanmadi: %s", e)

    def _forget_login() -> None:
        try:
            store.set(LOGIN_KEY, "")
        except Exception:
            pass

    def _saved_login() -> dict | None:
        raw = store.get(LOGIN_KEY)
        if not raw:
            return None
        try:
            data = _json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) and data.get("cashier") else None

    def _show_open_shift() -> None:
        """Smena yopiq, kassir kirgan — login so'ramay «SMENA OCHISH» ekrani."""
        who = session.get("cashier") or {}
        window.centralWidget().setEnabled(False)
        if session["offline"]:
            login_screen.set_status(tr("Oflayn — server bilan aloqa yo'q"))
        else:
            login_screen.set_status(tr("Smena yopiq — kirgach razmen puli so'raladi"))
        login_screen.open_resume(who.get("name", ""))

    def _on_resume() -> None:
        """«SMENA OCHISH» — kassir kirgan, faqat razmen puli so'raladi."""
        who = session.get("cashier")
        if not who:
            _show_login()
            return
        sh = session.get("shift")
        if not sh:
            sh = open_shift(backend, who)
            if sh is None:
                return  # bekor qildi — ekran turaveradi
        _enter_kassa(sh)

    def _resume_saved_login() -> bool:
        """Dastur ochilganda: kassir «Chiqish» ni bosmagan bo'lsa — parolsiz
        davom etamiz. Server «bir login — bir kompyuter» ni tekshiradi."""
        data = _saved_login()
        if not data:
            return False
        who = data["cashier"]
        store.set("resume_after_update", "")  # eski bir martalik belgi kerak emas

        hub.session = data.get("session") or ""
        if not session["offline"]:
            try:
                res = hub.resume_session(int(who.get("id") or 0))
                who = res.get("cashier") or who
            except HubBusyError as e:
                # Boshqa kompyuter shu login bilan ishlayapti
                logger.warning("Davom etib bo'lmadi: %s", e)
                _forget_login()
                _show_login()
                login_screen.show_error(str(e))
                return True
            except HubAuthError as e:
                # Kassir o'chirilgan yoki login yo'q — oddiy kirish
                logger.warning("Saqlangan login rad etildi: %s", e)
                _forget_login()
                return False
            except HubError as e:
                # Server javob bermadi — oflayn kabi davom etamiz
                logger.info("Davom etish serverga yetmadi (%s) — oflayn", e)
                hub.session = data.get("session") or ""
        else:
            hub.session = data.get("session") or ""

        session["cashier"] = who
        _save_login(who)
        logger.info("Kassir qayta kirmadi — davom etadi: %s", who.get("name"))
        sh = session.get("shift")
        if sh:
            _enter_kassa(sh)
        else:
            _show_open_shift()
        return True

    def _resume_after_update() -> bool:
        """Yangilanishdan keyin kassir qayta login qilmasin.

        Yangilanish qo'llanishidan oldin kassir, smena va sessiya belgilab
        qo'yilgan edi. Ilova qayta ochilganda shu belgi bo'lsa — login
        so'ramasdan, o'sha kassir o'sha smenaga BIRDAN qaytadi.

        Shartlar (xavfsizlik uchun):
          * belgi yaqinda (10 daqiqa ichida) qo'yilgan bo'lsin — eski belgi
            bilan hech kim kira olmasin;
          * smena hali ochiq bo'lsin;
          * smena o'sha smena bo'lsin (boshqa smena ochilgan bo'lsa — login).
        Belgi BIR MARTALIK: o'qilishi bilan o'chiriladi, shuning uchun oddiy
        ochilishda (yangilanishsiz) har doim login so'raladi.
        """
        import json as _json
        import time as _time

        raw = store.get("resume_after_update")
        if not raw:
            return False
        store.set("resume_after_update", "")  # bir martalik — darhol o'chiramiz
        try:
            data = _json.loads(raw)
        except ValueError:
            return False
        if _time.time() - float(data.get("ts") or 0) > 600:
            return False  # eski belgi — e'tibor bermaymiz
        who = data.get("cashier")
        sh = session.get("shift")
        if not (who and sh):
            return False
        mid = data.get("shift_id")
        if mid is not None and sh.get("id") is not None and sh.get("id") != mid:
            return False  # boshqa smena — login so'raymiz
        session["cashier"] = who
        # Manager-only amallar (kassaga pul) uchun sessiya tokenini tiklaymiz
        hub.session = data.get("session") or ""
        # Eski versiyadan (1.15) yangilanganda ham login endi eslab qolinadi
        _save_login(who)
        logger.info("Yangilanishdan keyin sessiya tiklandi: %s", who.get("name"))
        _enter_kassa(sh)
        window.flash(tr("Yangilandi — ishni davom ettiring"))
        return True

    def _on_login(user_login: str, password: str) -> None:
        sh = session.get("shift")

        if session["offline"]:
            # Server yo'q — parolni SHU KASSADA saqlangan xesh bilan
            # tekshiramiz (ilgari muvaffaqiyatli kirgan kassir uchun).
            who = store.offline_cashier(user_login, password)
            if not who:
                login_screen.show_error(
                    tr("Oflayn: login yoki parol noto'g'ri. "
                       "Bu kassada ilgari kirmagan bo'lsangiz — internet kerak.")
                )
                return
            session["cashier"] = who
            logger.info("Oflayn kirish: %s", who.get("name"))
            _save_login(who)
            if not sh:
                # Smena yopiq va internet yo'q — MAHALLIY ochamiz.
                # Kassa to'xtamaydi: razmen puli kiritiladi, xodim sotadi,
                # internet qaytganda smena ham, cheklar ham serverга ketadi.
                new_shift = open_shift(backend, who)
                if new_shift is None:
                    return  # kassir bekor qildi
                _enter_kassa(new_shift)
                return
            _enter_kassa(sh)
            return

        login_screen.set_busy(True)
        QApplication.processEvents()
        try:
            who = hub.login(user_login, password)["cashier"]
        except HubAuthError:
            login_screen.set_busy(False)
            login_screen.show_error(tr("Login yoki parol noto'g'ri"))
            return
        except HubBusyError as e:
            # Bu login hozir boshqa kompyuterda ishlayapti — xabar serverdan
            login_screen.set_busy(False)
            login_screen.show_error(str(e))
            return
        except HubError as e:
            login_screen.set_busy(False)
            login_screen.show_error(str(e))
            return
        login_screen.set_busy(False)
        session["cashier"] = who
        logger.info("Kassir kirdi: %s (%s)", who["name"], who["login"])
        # «Chiqish» bosilguncha eslab qolamiz (smena yopilsa, qayta yoqilsa ham)
        _save_login(who)
        # Keyingi safar internet bo'lmasa ham shu kassir kira olsin
        try:
            store.remember_cashier(user_login, password, who)
        except Exception as e:
            logger.info("Oflayn kirish uchun saqlanmadi: %s", e)

        if not sh:
            # Smena yopiq — razmen puli, keyin ochamiz
            new_shift = open_shift(backend, who)
            if new_shift is None:
                login_screen.show_error(tr("Smena ochilmadi"))
                return
            sh = new_shift
        _enter_kassa(sh)

    def logout() -> None:
        """«Chiqish» — kassir chiqadi, dastur qoladi (kirish ekrani).

        Faqat shu yerda login unutiladi: serverga «bo'shatildi» deyiladi
        va boshqa kompyuter shu login bilan kira oladi."""
        if not window.cart.is_empty:
            window.flash(tr("Avval chekni yakunlang yoki tozalang"))
            return
        logger.info("Kassir chiqdi: %s", (session.get("cashier") or {}).get("name", "?"))
        _forget_login()
        session["cashier"] = None
        hub.session = ""

        def _release() -> None:
            # Fon oqimida — server javobini kutib kassirni ushlamaymiz.
            # Yetmasa ham server 3 daqiqadan keyin o'zi bo'shatadi.
            try:
                Hub(config).logout()
            except Exception as e:
                logger.info("Chiqish serverga yetmadi: %s", e)

        threading.Thread(target=_release, name="sevimli-logout", daemon=True).start()
        _show_login()

    login_screen.login.connect(_on_login)
    login_screen.resume_requested.connect(_on_resume)
    login_screen.logout_requested.connect(logout)

    # Kassaning panel sozlamalari — ilova shunga qarab ishlaydi.
    kset = info.get("settings") or {}
    backend.track_stock = bool(kset.get("track_stock"))

    # ------------------------------------------------------- narx turi
    #
    # Chakana / ulgurji. Kassir sarlavhadagi tugmani bosib almashtiradi
    # (panelda ruxsat bo'lsa). Tanlov kassada saqlanadi. Almashtirilganda
    # chekdagi mavjud qatorlar ham yangi narxga o'tadi.
    def _refresh_price_ui() -> None:
        window.set_price_type(
            backend.price_type_name, backend.price_type_is_default,
            bool(kset.get("allow_price_type_switch", True)) and len(backend.price_types) > 1,
        )

    def choose_price_type() -> None:
        from .ui.dialogs import PickDialog

        if not kset.get("allow_price_type_switch", True):
            window.flash(tr("Narx turini almashtirish paneldan taqiqlangan"))
            return
        rows = []
        for p in backend.price_types:
            mark = "✓  " if p["id"] == backend.price_type_id else "     "
            rows.append((mark + p["name"], p["id"]))
        dlg = PickDialog(tr("Narx turi"), rows, pick_text=tr("TANLASH"), parent=window)
        if dlg.exec() != PickDialog.Accepted or not dlg.chosen:
            return
        if dlg.chosen == backend.price_type_id:
            return
        backend.set_price_type(dlg.chosen)
        changed = window.cart.reprice(dlg.chosen)
        _refresh_price_ui()
        window.fill_catalog(backend.search(window.scan_input.text().strip()))
        window.refresh()
        if changed:
            window.flash(tr("Narx turi: {n} — chekdagi {c} ta qator qayta narxlandi").format(
                n=backend.price_type_name, c=changed))
        else:
            window.flash(tr("Narx turi: {n}").format(n=backend.price_type_name))

    window.price_type_clicked.connect(choose_price_type)
    _refresh_price_ui()

    # Dialoglarni backend'ga ulaymiz — backend Qt'ni bilmasligi kerak
    def ask_quantity(line):
        dialog = QuantityDialog(
            line, window, allow_delete=kset.get("allow_delete_line", True)
        )
        return dialog.quantity if dialog.exec() == QuantityDialog.Accepted else None

    def ask_customer():
        dialog = CustomerDialog(
            backend.find_customer_by_code, backend.create_customer, window,
            required=kset.get("required_customer_fields"),
        )
        if dialog.exec() != CustomerDialog.Accepted:
            # Kassir bekor qildi — hech nima o'zgartirmaymiz. (None esa
            # «Mijozsiz» — mijozni olib tashlash degani.)
            from .hub import ASK_CANCEL
            return ASK_CANCEL
        return dialog.chosen

    def ask_discount(current):
        # Panelda chegirma o'chirilgan bo'lsa — umuman berilmaydi
        if not kset.get("allow_discount", True):
            window.flash(tr("Chegirma o'chirilgan"))
            return None
        dialog = DiscountDialog(
            current, window, max_percent=float(kset.get("max_discount", 100))
        )
        return dialog.percent if dialog.exec() == DiscountDialog.Accepted else None

    def ask_points(balance, max_balls, current):
        # Panelda ball to'lovi o'chirilgan bo'lsa — berilmaydi
        if not kset.get("redeem_enabled", True):
            window.flash(tr("Ball bilan to'lash o'chirilgan"))
            return None
        dialog = PointsDialog(balance, max_balls, current, window)
        return dialog.balls if dialog.exec() == PointsDialog.Accepted else None

    backend.quantity_asker = ask_quantity
    backend.customer_asker = ask_customer
    backend.discount_asker = ask_discount
    backend.points_asker = ask_points

    def show_report() -> None:
        from . import printer

        try:
            data = hub.shift_report()
        except HubError as e:
            QMessageBox.warning(None, tr("Hisobot"), str(e))
            return
        printed, path = printer.print_text(
            data["receipt_text"], config.printer, name="oraliq"
        )
        ReceiptDialog(data["receipt_text"], printed, path, window).exec()

    def cash_move(kind: str) -> None:
        dialog = CashDialog(kind, window)
        if dialog.exec() != CashDialog.Accepted:
            return
        amount = dialog.tiyin
        if not amount:
            return
        try:
            result = backend.cash(kind, amount)
        except HubError as e:
            QMessageBox.warning(None, tr("Saqlanmadi"), str(e))
            return
        done = (f"Kassaga {amount // 100} so'm kiritildi" if kind == "in"
                else f"Kassadan {amount // 100} so'm chiqarildi")
        # Internet yo'q bo'lsa amal navbatда qoladi — kassir buni bilsin,
        # lekin ishi to'xtamaydi (smena ham yopiladi).
        if isinstance(result, dict) and result.get("offline"):
            done += " · internet qaytganda serverga ketadi"
        window.flash(done)

    def park_cart() -> None:
        """Chekni chetga qo'yadi — mijoz biror narsani unutgan bo'lsa."""
        from .cart import cart_to_dict

        if window.cart.is_empty:
            window.flash(tr("Chek bo'sh"))
            return

        names = ", ".join(l.product.name for l in window.cart.lines[:3])
        if window.cart.count > 3:
            names += f" +{window.cart.count - 3}"

        store.park(names, window.cart.total, cart_to_dict(window.cart))
        window.cart.clear()
        window.refresh()
        window.flash(tr("Chek qoldirildi"))

    def open_parked() -> None:
        from .cart import cart_from_dict
        from .money import som
        from .ui.dialogs import PickDialog

        rows = [
            (f"{r['created_at'][11:16]}   ·   {r['summary']}\n{som(r['total'])} so'm",
             r["id"])
            for r in store.parked()
        ]
        dialog = PickDialog(
            tr("Qoldirilgan cheklar"), rows,
            empty_text=tr("Qoldirilgan chek yo'q"), pick_text=tr("OCHISH"), parent=window,
        )
        if dialog.exec() != PickDialog.Accepted or dialog.chosen is None:
            return

        if not window.cart.is_empty:
            # Ochiq chek yo'qolmasin — uni ham chetga qo'yamiz
            park_cart()

        data = store.unpark(dialog.chosen)
        if data:
            window.cart = cart_from_dict(data)
            window.refresh()

    def show_history() -> None:
        import json as _json

        from .money import som
        from .history import render_history_sale
        from . import printer
        from .ui.dialogs import HistoryDialog

        sh = session.get("shift") or {}
        tag = store.get("history_shift_tag") or ""

        rows = []
        for r in store.shift_sales(tag, 1000):
            payload = _json.loads(r["payload"])
            total = sum(p["amount"] for p in payload.get("payments", []))
            _sent = r["sent"]
            state = ("bekor" if _sent == 2
                     else (tr("yuborildi") if _sent else tr("navbatda")))
            keys = r.keys()
            check_no = r["check_no"] if "check_no" in keys else None
            is_return = payload.get("kind") == "return"
            rows.append({
                "check_no": check_no,
                "receipt_number": payload.get("receipt_number"),
                "time": r["created_at"][11:16],
                "total": total,
                "total_text": som(total),
                "state": state,
                "is_return": is_return,
                "payload": payload,
            })

        # Smena sarlavhasi — «Smena #12» yoki oflayn.
        if sh.get("id") is None or sh.get("number") in ("—", None, ""):
            caption = tr("Smena (oflayn)")
        else:
            caption = tr("Smena #{n}").format(n=sh["number"])

        def reprint(row: dict) -> None:
            text = render_history_sale(
                row["payload"], market=info.get("market", "Sevimli Market"),
                point=info.get("point", ""),
                cashier=(session.get("cashier") or {}).get("name", ""),
                shift_no=sh.get("number", "—"), methods=backend.methods,
                width=config.receipt_width,
            )
            printed, path = printer.print_sale(
                text, config.printer, config.paper, config.receipt_width,
                name="chek-qayta",
            )
            window.flash(
                tr("Chek qayta chop etildi") if printed
                else tr("Printer javob bermadi. Chek faylga saqlandi: {p}").format(p=path)
            )

        HistoryDialog(rows, shift_caption=caption, on_reprint=reprint, parent=window).exec()

    def refresh_data() -> None:
        # Tarmoq ishi fon oqimida — kassa qotmaydi. Chiroyli oyna bosqichlarni
        # ko'rsatadi; natija `bridge.refreshed` signali orqali qaytadi.
        sync_overlay.start()
        refresh_now.set()

    def _test_receipt_text(width: int) -> str:
        from datetime import datetime

        def center(s: str) -> str:
            s = s[:width]
            return " " * ((width - len(s)) // 2) + s

        line = "=" * width
        rows = [
            center(info.get("market", "SEVIMLI MARKET")),
            center(tr("TEST CHEK")),
            line,
            tr("Printer ishlayapti."),
            tr("Chek to'g'ri chiqyapti."),
            line,
            center(datetime.now().strftime("%d.%m.%Y  %H:%M")),
            "",
        ]
        return "\n".join(rows)

    def open_settings() -> None:
        """Printer sozlamalari — MoySklad'dagi «Работа кассы» kabi."""
        from . import printer
        from .ui.dialogs import PrinterSettingsDialog

        printers = printer.list_printers()

        def do_test(name: str, paper: str) -> None:
            width = 32 if str(paper) == "58" else 48
            ok, _ = printer.print_text(_test_receipt_text(width), name, name="test")
            window.flash(
                tr("Test chek yuborildi") if ok
                else tr("Chop etilmadi — printerni tekshiring")
            )

        dlg = PrinterSettingsDialog(
            printers, current=config.printer, paper=config.paper,
            auto_print=config.auto_print, on_test=do_test, parent=window,
        )
        if dlg.exec() != PrinterSettingsDialog.Accepted:
            return
        config.printer = dlg.printer_name
        config.paper = dlg.paper
        config.auto_print = dlg.auto_print
        cfg.save(config)
        window.flash(tr("Sozlamalar saqlandi"))

    def menu_action(code: str) -> None:
        if code == "report":
            show_report()
        elif code == "settings":
            open_settings()
        elif code == "cash_in":
            cash_move("in")
        elif code == "cash_out":
            cash_move("out")
        elif code == "park":
            park_cart()
        elif code == "parked":
            open_parked()
        elif code == "history":
            show_history()
        elif code == "refresh":
            refresh_data()
        elif code == "return":
            do_return()
        elif code == "language":
            toggle_language()
        elif code == "about":
            show_about()
        elif code == "close_shift":
            close_shift()
        elif code == "quit":
            logout()

    def quit_app() -> None:
        """Dasturdan chiqish — ishonchli yo'l.

        Faqat `window.close()` yetarli emas edi: ba'zi holatlarda (ochiq
        dialog, fon oqimi, yopilmagan yordamchi oyna) Qt jarayonni tirik
        qoldirardi va kassa «yopilmay» turib qolardi. Endi: fon oqimini
        to'xtatamiz, oynani yopamiz va ilovaga aniq «chiq» deymiz.
        """
        logger.info("Dasturdan chiqish")
        try:
            stop_bg.set()
        except NameError:
            pass
        window.hide()
        window.close()
        app.quit()
        # Zaxira: Qt 6 `quit()` biror oyna «yopilishni rad etsa» chiqishni
        # bekor qiladi. Kassa kiosk-dastur — kassir «Chiqish» ni bosdi,
        # demak 1 soniyadan keyin baribir yopiladi. Baza WAL rejimida,
        # har chek allaqachon diskda — hech narsa yo'qolmaydi.
        import os as _os

        def _force():
            logger.warning("Qt chiqmadi — majburan yopamiz")
            logging.shutdown()
            _os._exit(0)

        QTimer.singleShot(1200, _force)

    login_screen.quit_requested.connect(quit_app)

    def toggle_language() -> None:
        """Tilni almashtiradi. To'liq qo'llanishi uchun dastur qayta ochiladi."""
        new = "ru" if config.language != "ru" else "uz"
        config.language = new
        cfg.save(config)
        i18n.set_lang(new)
        QMessageBox.information(
            None, tr("Til"), tr("Til o'zgardi. Dasturni qayta oching.")
        )
        quit_app()

    backend.menu_action = menu_action

    def do_return() -> None:
        """Qaytarish oqimi: savdo → tovarlar → pul → tayyor.

        Sizning MoySklad Kassa'dagi ketma-ketlikning aynan o'zi.
        Har qadam bekor qilinsa — to'xtaydi, hech narsa yozilmaydi.
        """
        from .ui.dialogs import (
            RefundMethodDialog,
            ReturnDetailDialog,
            ReturnDoneDialog,
            ReturnItemsDialog,
            ReturnSaleListDialog,
        )

        try:
            sales = backend.returnable_sales()
        except HubError as e:
            QMessageBox.warning(None, tr("Qaytarish"), f"Savdolar olinmadi: {e}")
            return

        if not sales:
            QMessageBox.information(None, tr("Qaytarish"), tr("Qaytariladigan savdo yo'q."))
            return

        # 1. Savdoni tanlash
        pick = ReturnSaleListDialog(sales, window, search_fn=backend.returnable_sales)
        if pick.exec() != ReturnSaleListDialog.Accepted or not pick.chosen:
            return
        sale = pick.chosen
        if sale.get("return_error"):
            QMessageBox.warning(window, tr("Qaytarish"), sale["return_error"])
            return

        # 2. Chek — «Qaytarish yaratish»
        detail = ReturnDetailDialog(sale, window)
        if detail.exec() != ReturnDetailDialog.Accepted:
            return

        # 3. Qaysi tovar, nechta
        items = ReturnItemsDialog(sale, window)
        # Bu chekda qaytarish uchun hech nima qolmagan bo'lsa (hammasi
        # allaqachon qaytarilgan) — kassirга aniq aytamiz, bo'sh oyna emas.
        if not items.rows:
            QMessageBox.information(
                None, tr("Qaytarish"),
                tr("Bu chekdagi tovarlar allaqachon qaytarilgan — qayta qaytarib bo'lmaydi."),
            )
            return
        if items.exec() != ReturnItemsDialog.Accepted or not items.lines:
            return

        # 4. Pulni qanday qaytaramiz
        refund_method = "naqd"
        if items.total > 0:
            method = RefundMethodDialog(items.total, backend.methods, window)
            if method.exec() != RefundMethodDialog.Accepted or not method.method:
                return
            refund_method = method.method

        try:
            amount = backend.submit_return(sale, items.lines, refund_method)
            backend.flush()
        except Exception as e:
            QMessageBox.critical(None, tr("Qaytarilmadi"), str(e))
            return
        row = store.db.execute("SELECT sent, last_error FROM outbox WHERE local_uuid=?",
                               (backend.last_return_uuid,)).fetchone()
        if not row or row["sent"] != 1:
            reason = row["last_error"] if row else ""
            QMessageBox.warning(window, tr("Qaytarish tasdiqlanmadi"),
                "Qaytarish kassada saqlandi, server hali tasdiqlamadi. "
                "Pul berishdan oldin Cheklar tarixidan holatini tekshiring.\n" + reason)
            flush_now.set()
            return

        from . import printer
        # Qaytarish cheki — printer bo'lsa chiqaradi
        text = (
            f"QAYTARISH\nChek: {backend.last_receipt_number}\n"
            f"Asl chek: {sale.get('receipt_number') or sale['number']}\n"
            f"Qaytarildi: {amount // 100} so'm\n"
        )
        printer.print_text(text, config.printer, name="qaytarish")

        ReturnDoneDialog(amount, window).exec()
        window.flash(f"Qaytarildi: {amount // 100} so'm")
        flush_now.set()   # fon oqimi darhol yuboradi

    def close_shift() -> None:
        from datetime import datetime, timezone

        from shared.receipt import render as render_shift

        from . import printer
        from .smena import build_shift_receipt, offline_banner

        # Yopishdan oldin navbatni bo'shatishga urinamiz — internet bo'lsa
        # hisobotni server chizadi va raqam bitta joyda hisoblanadi.
        try:
            backend.flush()
        except Exception:
            pass

        # Internet yo'qligi endi to'siq emas: chek kassaning o'zida turadi,
        # demak hisobot to'liq chiqadi. Faqat server RAD ETGAN cheklar
        # haqida ogohlantiramiz — ular haqiqatan ham muammo.
        stuck = store.stuck_count()
        dialog = CloseShiftDialog(stuck, window)
        if dialog.exec() != CloseShiftDialog.Accepted:
            return

        # Internetsiz yopilsa shu matn chop etiladi. Serverга ulanib
        # bo'lsa server chizgan matn ishlatiladi — ikkisi bir xil
        # formulalar bilan hisoblanadi.
        sh = session.get("shift") or {}
        width = config.receipt_width
        local_text = offline_banner(
            render_shift(
                build_shift_receipt(
                    store, backend.methods,
                    market=info.get("market", "Sevimli Market"),
                    point=info.get("point", ""),
                    register=(info.get("register") or {}).get("name", ""),
                    cashier=sh.get("cashier", ""),
                    shift_no=sh.get("number") or "—",
                    opened_at=sh.get("opened_at", ""),
                    closed_at=datetime.now(timezone.utc).isoformat(),
                    opening_cash=sh.get("opening_cash", 0),
                    shift_tag=store.get("history_shift_tag") or "",
                ),
                width,
            ),
            width,
        )

        try:
            result = backend.finish_shift(dialog.counted, local_text)
        except HubError as e:
            QMessageBox.critical(
                None, tr("Smena yopilmadi"),
                f"{e}\n\nSabab tuzatilgach qayta urinib ko'ring.",
            )
            return

        printed, path = printer.print_text(
            result["receipt_text"], config.printer, name="smena"
        )
        ReceiptDialog(result["receipt_text"], printed, path, window).exec()
        # Smena yopildi — dastur yopilmaydi. Kassir kirgan bo'lib qoladi:
        # login-parol qayta so'ralmaydi, «SMENA OCHISH» tugmasi chiqadi.
        # Boshqa kassir kirishi kerak bo'lsa — o'sha ekrandagi «Chiqish».
        session["shift"] = None
        store.set("active_shift_id", "")
        window.shift_label.setText("")
        if session.get("cashier"):
            _show_open_shift()
        else:
            _show_login()

    backend.close_shift = close_shift

    # ----------------------------------------------------------- fon oqimi
    #
    # MUHIM: barcha tarmoq amallari (chek yuborish, katalog sinxroni, holat
    # tekshiruvi) alohida oqimda bajariladi. UI oqimi hech qachon tarmoqni
    # kutib turmaydi — shuning uchun 22 000 tovarli katalog tortilayotganda
    # ham dastur qotmaydi. Ilgari bularning hammasi UI oqimida edi va kassa
    # «javob bermayapti» bo'lib qolardi.
    #
    # Fon oqimi bazaga O'Z ulanishi bilan tegadi (o'z Store nusxasi). Main
    # oqim faqat o'zining `store`/`backend` bilan o'qiydi. Ikki ulanish
    # bitta faylga WAL + busy_timeout orqali xavfsiz ishlaydi.

    class _Bridge(QObject):
        status = Signal(bool, int)     # onlayn, navbatdagi cheklar
        catalog = Signal(int)          # o'zgargan tovarlar soni (avto)
        refresh_stage = Signal(int)    # qo'lda yangilash: bosqich 0..2
        refreshed = Signal(object, str)  # qo'lda yangilash: stats dict, xato
        settings_refreshed = Signal(object)  # panel sozlamalari o'zgardi: yangi hello
        moysklad = Signal(object)            # server ↔ MoySklad chirog'i (dict|None)
        # Ilova yangilanishi
        version_checked = Signal(object, str)   # server javobi (dict|None), xato
        update_progress = Signal(int, int)      # yuklab olish: bo'ldi, jami
        update_ready = Signal(object)           # yuklab olindi: info (+path)
        update_failed = Signal(str)
        shift_synced = Signal(object)           # oflayn smena serverга ochildi
        # «Bir login — bir kompyuter»
        session_renewed = Signal(str)           # yangi sessiya tokeni (hello)
        session_lost = Signal(str)              # boshqa kompyuter kirib oldi

    bridge = _Bridge()

    def _apply_session_renewed(token: str) -> None:
        if token and token != hub.session:
            hub.session = token
            who = session.get("cashier")
            if who:
                _save_login(who)

    def _apply_session_lost(message: str) -> None:
        """Boshqa kompyuter shu login bilan kirib oldi (bu kompyuter jim
        qolgan paytda). Bu yerda ishlash to'xtaydi — kirish ekrani."""
        if not session.get("cashier"):
            return
        logger.warning("Sessiya boshqa kompyuterga o'tdi: %s", message)
        _forget_login()
        session["cashier"] = None
        hub.session = ""
        _show_login()
        login_screen.show_error(message or tr("Bu login boshqa kassada ochildi"))

    bridge.session_renewed.connect(_apply_session_renewed)
    bridge.session_lost.connect(_apply_session_lost)

    def _apply_status(online: bool, pending: int) -> None:
        session["offline"] = not online
        # Chiroq: yashil — ulangan, sariq — ulangan lekin cheklar navbatda,
        # qizil — server javob bermayapti (cheklar kassada saqlanadi).
        if not online:
            window.links.set_state("server", "bad", tr("aloqa yo'q"))
            # Server o'chiq — MoySklad holatini so'rab bo'lmaydi
            window.links.set_state("moysklad", "unknown")
        elif pending:
            window.links.set_state(
                "server", "warn", f"Serverga kutilmoqda: {pending} ta chek"
            )
        else:
            window.links.set_state("server", "ok")
        # Onlaynda navbat soni chiroq yonida turibdi — qatorni bo'sh
        # qoldiramiz (flash xabarlari shu yerga chiqadi).
        if not online:
            text = tr("Oflayn — cheklar kassada saqlanadi") + f" · navbat {pending}"
        else:
            text = f"Serverga kutilmoqda: {pending}" if pending else ""
        window.status_label.setText(text)
        window.status_label.setStyleSheet(
            f"color: {'#6B7672' if online and not pending else '#8A5A12'};"
            f"font-size: 12px;"
        )

    def _apply_moysklad(link) -> None:
        # Server ↔ MoySklad holati — hello javobidagi `links.moysklad`.
        # Eski server (bu maydonni bermaydigan) bo'lsa — noma'lum.
        if not isinstance(link, dict) or not link.get("state"):
            window.links.set_state("moysklad", "unknown")
            return
        window.links.set_state("moysklad", link["state"], link.get("text") or "")

    def _apply_catalog(changed: int) -> None:
        # Hech narsa o'zgarmagan bo'lsa ro'yxatga tegmaymiz — kassir
        # ishlayotganda bekorga chizmaymiz. Kassir qidiruv yozayotgan
        # bo'lsa ham tortib olmaymiz — faqat qidiruv bo'sh bo'lsa.
        if not changed:
            return
        if not window.scan_input.text().strip():
            window.fill_catalog(backend.search(""))

    from .ui.sync_overlay import SyncOverlay

    sync_overlay = SyncOverlay(window)

    def _apply_refreshed(stats, err: str) -> None:
        if err:
            sync_overlay.fail(err)
            window.flash(tr("Yangilanmadi: {e}").format(e=err))
            return
        stats = stats or {}
        window.fill_catalog(backend.search(window.scan_input.text().strip()))
        sync_overlay.finish(stats)
        changed = stats.get("new", 0) + stats.get("updated", 0) + stats.get("gone", 0)
        if changed:
            window.flash(tr("Katalog yangilandi ({n} ta o'zgarish)").format(n=changed))
        else:
            window.flash(tr("Katalog yangi — o'zgarish yo'q"))

    bridge.status.connect(_apply_status)
    bridge.shift_synced.connect(_apply_shift_synced)
    bridge.catalog.connect(_apply_catalog)
    bridge.refresh_stage.connect(sync_overlay.set_stage)

    def _apply_settings(fresh: dict) -> None:
        # Panel sozlamalari o'sha lug'at obyektida — dialoglar `kset` ga
        # qaraydi, shuning uchun joyida yangilaymiz (yangi obyekt emas).
        kset.clear()
        kset.update(fresh.get("settings") or {})
        info.update(fresh)
        backend.setup_price_types(
            fresh.get("price_types") or [], fresh.get("default_price_type") or ""
        )
        backend.track_stock = bool(kset.get("track_stock"))
        _refresh_price_ui()
        # To'lov turlari — panelda qo'shilgan/olib tashlangan/nomi
        # o'zgargan bo'lsa, keyingi to'lov oynasi yangi ro'yxat bilan
        # ochiladi. Ilgari bu faqat kassa qayta ochilganda o'qilardi.
        methods = fresh.get("payment_methods")
        if isinstance(methods, list) and methods:
            before = [(m.get("code"), m.get("name")) for m in backend.methods]
            after = [(m.get("code"), m.get("name")) for m in methods]
            backend.methods = list(methods)
            if before != after:
                logger.info("To'lov turlari paneldan yangilandi: %s",
                            ", ".join(m.get("name", "") for m in methods))
                window.flash(tr("To'lov turlari yangilandi"))
        sh = fresh.get("shift")
        if sh:
            session["shift"] = sh
            window.shift_label.setText(f"Smena #{sh['number']} · {sh['cashier']}")

    bridge.settings_refreshed.connect(_apply_settings)
    bridge.moysklad.connect(_apply_moysklad)
    # Ochilishdagi holat: server javob bergan bo'lsa — undan, keshdan
    # (oflayn) ochilgan bo'lsa — noma'lum; 15 soniyada aniqlashadi.
    _apply_moysklad(None if offline else (info.get("links") or {}).get("moysklad"))
    bridge.refreshed.connect(_apply_refreshed)

    stop_bg = threading.Event()
    flush_now = threading.Event()
    refresh_now = threading.Event()   # «Ma'lumotlarni yangilash» tugmasi
    check_update_now = threading.Event()  # «Yangilanishni tekshirish» tugmasi

    # ------------------------------------------------ ilova yangilanishi
    #
    # Fon oqimi versiyani tekshiradi va yangi exe ni yuklab oladi. Bu yerda
    # (main oqim) faqat oynalar: «Dastur haqida» va «Yangilash?».
    # Majburiy yangilanish chek ochiq turganda chiqmaydi — kassir chekni
    # yakunlagach chiqadi. Kassir «Keyinroq» desa — shu sessiyada boshqa
    # so'ralmaydi (majburiy bo'lmasa); keyingi ochilishda yana so'raladi.
    from . import updater
    from .ui.update_dialog import AboutDialog

    update_state = {"ready": None, "about": None, "applying": False, "skip": ""}

    # «Yangilanmoqda…» pardasi — yangilanish o'rnatilayotganda ekranни
    # yopadi, kassir «qotib qoldi» deb o'ylamasin. Dastur o'zi qayta ochiladi.
    def _show_updating() -> None:
        overlay = update_state.get("overlay")
        if overlay is None:
            from PySide6.QtWidgets import QLabel

            overlay = QLabel(window)
            overlay.setAlignment(Qt.AlignCenter)
            overlay.setText(
                tr("Yangilanmoqda…") + "\n\n"
                + tr("Dastur bir necha soniyada o'zi qayta ochiladi")
            )
            overlay.setStyleSheet(
                "background: rgba(20, 12, 14, 235); color: #FFFFFF;"
                "font-size: 26px; font-weight: 600;"
            )
            update_state["overlay"] = overlay
        overlay.setGeometry(window.rect())
        overlay.show()
        overlay.raise_()

    def _hide_updating() -> None:
        overlay = update_state.get("overlay")
        if overlay is not None:
            overlay.hide()

    def show_about() -> None:
        dlg = AboutDialog(
            info.get("point", ""), (info.get("register") or {}).get("name", ""),
            config.base, parent=window,
        )
        dlg.set_checker(lambda: check_update_now.set())
        dlg.on_install = _install_update
        if update_state["ready"]:
            dlg.show_ready(update_state["ready"])
        update_state["about"] = dlg
        dlg.exec()
        update_state["about"] = None

    def _about():
        return update_state["about"]

    def _on_version_checked(res, err: str) -> None:
        if _about():
            _about().show_result(res, err)

    def _on_update_progress(done: int, total: int) -> None:
        if _about():
            _about().show_progress(done, total)

    def _on_update_failed(err: str) -> None:
        if _about():
            _about().show_failed(err)

    def _on_update_ready(upd: dict) -> None:
        update_state["ready"] = upd
        if _about():
            _about().show_ready(upd)
        # Kassir hech narsa bosmaydi — dastur o'zi yangilanadi. Faqat
        # sotuv o'rtasida bo'lmasin: bo'sh turganda o'rnatiladi.
        _maybe_apply_update()

    def _maybe_apply_update() -> None:
        upd = update_state["ready"]
        if not upd or update_state["applying"]:
            return
        if update_state.get("skip") == upd.get("version"):
            return  # bu muhitda o'rnatib bo'lmadi — qayta urinmaymiz
        # Sotuv o'rtasida yoki oyna ustida bo'lsa — kutamiz. Chek
        # yakunlangach (sale_finished) yoki 15 soniyadan keyin qayta urinamiz.
        if not window.cart.is_empty or app.activeModalWidget() is not None:
            QTimer.singleShot(15_000, _maybe_apply_update)
            return
        _install_update(upd)

    def _install_update(upd: dict) -> None:
        if update_state["applying"]:
            return

        # HALQADAN HIMOYA. Agar bir versiyani (aynan bir xil ZIP — SHA
        # bo'yicha) 3 marta o'rnatib ham unga o'tolmasak, demak ZIP ichидаги
        # versiya panелdаги raqамга mos emas — cheksiz aylanmaymiz, to'xtaymiz.
        # Admin to'g'ri ZIP qayta yuklasa (boshqa SHA) — o'zi qayta sinaydi.
        import json as _j

        version = upd.get("version", "")
        sha = (upd.get("sha256") or "")[:16]
        try:
            last = _j.loads(store.get("upd_last") or "{}")
        except ValueError:
            last = {}
        if last.get("version") == version and last.get("sha") == sha:
            n = int(last.get("count", 0)) + 1
        else:
            n = 1
        store.set("upd_last", _j.dumps({"version": version, "sha": sha, "count": n}))
        if n > 3:
            logger.warning(
                "Yangilanish halqasi to'xtatildi: %s %s marta o'rnatildi, "
                "lekin versiya o'zgarmadi (ZIP ichi mos emas).", version, n
            )
            update_state["skip"] = version
            window.flash(tr("Yangilanish to'xtatildi — versiya mos emas"))
            return

        update_state["applying"] = True
        path = Path(upd.get("path") or "")
        logger.info("Yangilanish o'rnatilmoqda: %s (urinish %s)", path, n)

        # Yangilanishdan keyin kassir qayta login qilmasin — hozirgi kassir,
        # smena va sessiyani belgilab qo'yamiz. Ilova qayta ochilganda shu
        # belgi bo'lsa, to'g'ri kassaga birdan kiradi (login so'ralmaydi).
        # Bir martalik: keyingi ochilishda o'qilib, o'chiriladi.
        try:
            import time as _time
            cur_c = session.get("cashier")
            cur_s = session.get("shift")
            if cur_c and cur_s:
                store.set("resume_after_update", _j.dumps({
                    "cashier": cur_c,
                    "shift_id": cur_s.get("id"),
                    "session": getattr(hub, "session", "") or "",
                    "ts": _time.time(),
                }, ensure_ascii=False))
        except Exception as _e:
            logger.info("Sessiyani belgilash o'tkazib yuborildi: %s", _e)

        # Kassirga «Yangilanmoqda…» ko'rsatamiz — ekran «qotib qolgandek»
        # ko'rinmasin. Dastur o'zi yopilib, yangisi ochiladi.
        _show_updating()
        QApplication.processEvents()

        if updater.apply(path):
            # Skript ilova yopilishini kutyapti — chiqamiz. Navbat va
            # cheklar diskda, keyingi ochilishda davom etadi.
            stop_bg.set()
            window.close()
            app.quit()
        else:
            # Yig'ilmagan muhit yoki ZIP chala — qayta urinmaymiz, ekranга
            # qaytamiz. Kassir ishlashda davom etadi (eski versiya).
            update_state["applying"] = False
            update_state["skip"] = upd.get("version", "")
            _hide_updating()
            logger.warning("Yangilanish qo'llanmadi (o'tkazib yuborildi): %s", path)

    bridge.version_checked.connect(_on_version_checked)
    bridge.update_progress.connect(_on_update_progress)
    bridge.update_failed.connect(_on_update_failed)
    bridge.update_ready.connect(_on_update_ready)

    def _check_update(bg_hub: Hub) -> None:
        """Fon oqimida: versiyani so'raydi, yangisi bo'lsa yuklab oladi."""
        from .version import is_newer

        try:
            res = bg_hub.check_version()
        except Exception as e:
            bridge.version_checked.emit(None, str(e))
            return
        bridge.version_checked.emit(res, "")

        newest = res.get("version") or ""
        url = res.get("url") or ""
        if not (newest and url and is_newer(newest)):
            updater.cleanup()
            return

        path = updater.staged_path(newest)
        ready = dict(res, path=str(path))
        if path.exists() and path.stat().st_size == int(res.get("size") or path.stat().st_size):
            bridge.update_ready.emit(ready)
            return
        try:
            logger.info("Yangi versiya %s yuklab olinmoqda: %s", newest, url)
            updater.cleanup(keep=newest)
            bg_hub.download(
                url, path,
                progress=lambda d, tt: bridge.update_progress.emit(d, tt),
                expected_sha256=res.get("sha256") or "",
            )
        except Exception as e:
            logger.warning("Yangilanish yuklab olinmadi: %s", e)
            bridge.update_failed.emit(str(e))
            return
        logger.info("Yangilanish tayyor: %s", path)
        bridge.update_ready.emit(ready)

    session_retry = {"at": 0.0}

    def _watch_session(bg_hub: Hub, fresh: dict, now: float) -> None:
        """hello javobidagi «bir login — bir kompyuter» holati (fon oqimi).

        mine=True  — token uzaytirilgan bo'lsa yangilaymiz;
        mine=False — boshqa kompyuter kirib oldi: kirish ekraniga;
        mine=None  — biz kirgan deb hisoblaymiz, server bilmaydi (token
                     muddati o'tgan, server qayta o'rnatilgan, panelda
                     «Bo'shatish») — parolsiz qayta biriktiramiz (60 s da bir).
        """
        ls = fresh.get("login_session")
        if not isinstance(ls, dict) or not session.get("cashier"):
            return
        mine = ls.get("mine")
        if mine is True:
            if ls.get("session"):
                bridge.session_renewed.emit(ls["session"])
            return
        if mine is False:
            bridge.session_lost.emit(ls.get("message") or "")
            return
        if now - session_retry["at"] < 60:
            return
        session_retry["at"] = now
        try:
            res = bg_hub.resume_session(int((session.get("cashier") or {}).get("id") or 0))
            if res.get("session"):
                bridge.session_renewed.emit(res["session"])
        except HubBusyError as e:
            bridge.session_lost.emit(str(e))
        except Exception as e:
            logger.info("Sessiyani qayta biriktirib bo'lmadi: %s", e)

    def _bg_loop() -> None:
        bg_store = Store(cfg.config_dir() / "kassa.db")
        bg_hub = Hub(config)
        bg_backend = LiveBackend(bg_hub, bg_store, info["payment_methods"])

        # Eski config.json'da 300 saqlangan bo'lishi mumkin — 2 daqiqadan
        # uzoq kutmaymiz: narx o'zgarishi kassaga tez yetishi kerak.
        cat_every = min(config.catalog_interval or 120, 120)

        last_flush = last_cat = last_stat = 0.0
        # Versiya: ochilgandan 20 soniya keyin, so'ng har 30 daqiqada
        next_update_check = time.monotonic() + 20
        # Panel sozlamalarining barmoq izi. 15 soniyalik hello javobi
        # shundan farq qilsa — paneldan nimadir o'zgartirilgan, kassaga
        # darhol qo'llanadi (qayta ochish shart emas).
        last_fp = settings_fingerprint(info)
        while not stop_bg.is_set():
            now = time.monotonic()

            if check_update_now.is_set() or now >= next_update_check:
                check_update_now.clear()
                next_update_check = now + 30 * 60
                try:
                    _check_update(bg_hub)
                except Exception as e:
                    logger.warning("Versiya tekshiruvi xato: %s", e)

            if flush_now.is_set() or now - last_flush >= config.outbox_interval:
                flush_now.clear()
                last_flush = now
                try:
                    # Internetsiz ochilgan smena bo'lsa — avval uni serverга
                    # ochamiz (idempotent), keyin cheklar shunga tushadi.
                    bg_hub.session = getattr(hub, "session", "") or ""
                    synced = bg_backend.sync_shift()
                    if synced:
                        bridge.shift_synced.emit(synced)
                    sent = bg_backend.flush()
                    if sent:
                        logger.info("%s ta chek yuborildi", sent)
                except Exception as e:
                    logger.warning("Navbatni yuborishda xato: %s", e)

            # Qo'lda yangilash: server MoySklad'dan darhol tortadi, keyin
            # farq olinadi. Natija main oqimga signal bilan qaytadi.
            if refresh_now.is_set():
                refresh_now.clear()
                bg_store.retry_stuck()
                flush_now.set()
                last_cat = now
                try:
                    # 0-bosqich: savdo nuqtasi sozlamalari (hello) —
                    # buxgalter paneldan chegirma chegarasini o'zgartirgan
                    # bo'lsa, shu yerda kassaga yetadi.
                    bridge.refresh_stage.emit(0)
                    try:
                        fresh = bg_hub.hello(queue={"local_pending": bg_store.unsent_count(), "local_stuck": bg_store.stuck_count(), "local_error": bg_store.queue_error()})
                        bg_store.set("last_hello", _json.dumps(fresh, ensure_ascii=False))
                        last_fp = settings_fingerprint(fresh)
                        bridge.settings_refreshed.emit(fresh)
                        bridge.moysklad.emit((fresh.get("links") or {}).get("moysklad"))
                    except Exception as e:
                        logger.info("Sozlamalar yangilanmadi: %s", e)
                    stats = bg_backend.sync_catalog_detailed(
                        force=True,
                        progress=lambda i: bridge.refresh_stage.emit(1 if i < 2 else 2),
                    )
                    logger.info("Qo'lda yangilash: %s", stats)
                    bridge.refreshed.emit(stats, "")
                except Exception as e:
                    logger.warning("Qo'lda yangilash bo'lmadi: %s", e)
                    bridge.refreshed.emit(None, str(e))

            # Avtomatik: har `catalog_interval` soniyada farqni olamiz.
            # Server o'z navbatida MoySklad'ni har 5 daqiqada tortadi —
            # demak narx o'zgarishi kassaga eng ko'pi 7 daqiqada yetadi.
            if now - last_cat >= cat_every:
                last_cat = now
                try:
                    changed = bg_backend.sync_catalog()
                    if changed:
                        logger.info("Katalogda %s ta o'zgarish", changed)
                        bridge.catalog.emit(changed)
                except Exception as e:
                    logger.info("Katalog yangilanmadi: %s", e)

            if now - last_stat >= 15:
                last_stat = now
                online = True
                fresh = None
                # Sessiya tokeni bilan — server «kompyuter tirik» belgisini
                # yangilaydi va tokenni uzaytiradi
                bg_hub.session = getattr(hub, "session", "") or ""
                try:
                    fresh = bg_hub.hello(queue={"local_pending": bg_store.unsent_count(), "local_stuck": bg_store.stuck_count(), "local_error": bg_store.queue_error()})
                    # Keshni yangilab turamiz — keyingi ochilishда server
                    # o'chiq bo'lsa ham eng so'nggi holat (smena, sozlama)
                    # bilan oflayn davom etiladi.
                    try:
                        bg_store.set("last_hello", _json.dumps(fresh, ensure_ascii=False))
                    except Exception:
                        pass
                except Exception:
                    online = False
                try:
                    bridge.status.emit(online, bg_store.unsent_count())
                except Exception:
                    pass
                if fresh is not None:
                    # Server ↔ MoySklad chirog'i — har so'rovda
                    bridge.moysklad.emit((fresh.get("links") or {}).get("moysklad"))
                    _watch_session(bg_hub, fresh, now)
                    # Paneldan o'zgartirish berilgan bo'lsa — darhol qo'llash
                    fp = settings_fingerprint(fresh)
                    if fp != last_fp:
                        last_fp = fp
                        logger.info("Panel sozlamalari o'zgardi — kassaga qo'llanmoqda")
                        bridge.settings_refreshed.emit(fresh)

            stop_bg.wait(1.0)

        bg_store.close()

    window.sale_finished.connect(lambda: flush_now.set())
    window.sale_finished.connect(lambda: QTimer.singleShot(800, _maybe_apply_update))

    bg_thread = threading.Thread(target=_bg_loop, name="sevimli-bg", daemon=True)
    bg_thread.start()

    def _stop() -> None:
        stop_bg.set()
        bg_thread.join(timeout=2)

    app.aboutToQuit.connect(_stop)

    _apply_status(not offline, store.pending_count())

    # Deyarli to'liq ekran, lekin SUZUVCHI oyna — shunda Windows 11 oyna
    # burchaklarini yumaloq qiladi (maksimallashgan oyna to'rtburchak
    # bo'lib qoladi). Ekran chetидан ozgina bo'shliq.
    screen = app.primaryScreen().availableGeometry()
    m = 14
    window.setGeometry(
        screen.x() + m, screen.y() + m,
        screen.width() - 2 * m, screen.height() - 2 * m,
    )
    window.show()
    if offline:
        window.flash(tr("Oflayn rejim — aloqa tiklangach cheklar o'zi yuboriladi"))
    # Kassir «Chiqish» ni bosmagan bo'lsa — parolsiz davom etadi (smena
    # ochiq bo'lsa to'g'ri kassaga, yopiq bo'lsa «SMENA OCHISH» ekraniga).
    # Aks holda kirish ekrani: xodim login-parolini teradi.
    if not _resume_saved_login() and not _resume_after_update():
        _show_login()
    code = app.exec()
    _stop()
    logging.shutdown()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
