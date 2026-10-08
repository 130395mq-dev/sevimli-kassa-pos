"""Regressions observed in the isolated Windows trial on 2026-09-29."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from .cart import Cart, PaymentPlan
from .hub import LiveBackend
from .store import Store
from .test_store import FakeHub, METHODS, PRODUCTS


class PanelPriceCheckoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_panel_change_during_payment_keeps_paid_and_printed_amount(self):
        from .price_policy import bind_price_policy
        from .test_store import PriceTypeTest
        from .ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "kassa.db")
            store.replace_products(PriceTypeTest.ROWS)
            backend = LiveBackend(FakeHub(), store, METHODS)
            types = [{"id": "chk", "name": "Chakana"}, {"id": "ulg", "name": "Ulgurji"}]
            backend.setup_price_types(types, "chk")
            window = MainWindow(backend)
            policy = bind_price_policy(backend, window)
            policy.offer({"price_types": types, "default_price_type": "chk", "price_policy_revision": "a"})
            printed = []
            window.print_sale = lambda cart, plan: printed.append((cart.total, backend.price_type_id))
            window.cart.add(store.by_barcode("1"))
            window.refresh()
            plan = PaymentPlan(window.cart.total)
            plan.add_cash(window.cart.total)
            try:
                with patch("pos.ui.main_window.PaymentDialog") as dialog:
                    dialog.Accepted = 1
                    dialog.return_value.plan = plan
                    def while_paying():
                        policy.offer({"price_types": types, "default_price_type": "ulg", "price_policy_revision": "b"})
                        self.assertEqual(window.cart.total, 55_000_00)
                        self.assertEqual(window.price_btn.text(), "Chakana")
                        return 1
                    dialog.return_value.exec.side_effect = while_paying
                    window.open_payment()
                self.assertEqual(printed, [(55_000_00, "chk")])
                self.assertTrue(window.cart.is_empty)
                self.assertEqual(window.price_btn.text(), "Ulgurji")
                self.assertFalse(window.price_btn.isEnabled())
                self.assertEqual(store.by_barcode("1").price, 52_000_00)
                payload = json.loads(store.pending()[0]["payload"])
                self.assertEqual(payload["price_type_id"], "chk")
                self.assertEqual(payload["payments"][0]["amount"], 55_000_00)
            finally:
                policy.timer.stop()
                window.close()
                store.close()


class ParkedCartPriceTest(unittest.TestCase):
    """Kechiktirilgan (park) chek va panel narx turi (2026-09-29 ko'rib chiqish).

    1) `open_parked` `window.cart` ni YANGI obyektga almashtiradi. Siyosat eski
       obyektga qarab qolsa, ochiq chek paytida narx turi almashib ketardi.
    2) Park paytidagi narx turi hozirgisidan farq qilsa, chek joriy turdagi
       narxga o'tkazilishi kerak — aks holda server «narx katalogga mos emas»
       deb rad etadi va to'langan chek navbatda tiqilib qoladi.
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _setup(self, folder):
        from .price_policy import bind_price_policy
        from .test_store import PriceTypeTest
        from .ui.main_window import MainWindow
        store = Store(Path(folder) / "kassa.db")
        store.replace_products(PriceTypeTest.ROWS)
        backend = LiveBackend(FakeHub(), store, METHODS)
        types = [{"id": "chk", "name": "Chakana"}, {"id": "ulg", "name": "Ulgurji"}]
        backend.setup_price_types(types, "chk")
        window = MainWindow(backend)
        policy = bind_price_policy(backend, window)
        policy.offer({"price_types": types, "default_price_type": "chk", "price_policy_revision": "a"})
        return store, backend, window, policy, types

    def test_unparked_open_cart_keeps_price_type_until_finished(self):
        from .cart import cart_from_dict, cart_to_dict
        with tempfile.TemporaryDirectory() as folder:
            store, backend, window, policy, types = self._setup(folder)
            try:
                parked = Cart()
                parked.add(store.by_barcode("1"))
                window.cart = cart_from_dict(cart_to_dict(parked))   # open_parked bilan bir xil
                window.refresh()
                policy.offer({"price_types": types, "default_price_type": "ulg", "price_policy_revision": "b"})
                policy.apply_if_idle()
                self.assertEqual(backend.price_type_id, "chk")        # ochiq chek — eski tur
                window.cart.clear()
                window.refresh()
                policy.apply_if_idle()
                self.assertEqual(backend.price_type_id, "ulg")        # bo'sh — yangi tur
            finally:
                policy.timer.stop()
                window.close()
                store.close()

    def test_parked_cart_repriced_to_current_type_on_restore(self):
        from .cart import cart_to_dict
        from .price_policy import restore_parked
        with tempfile.TemporaryDirectory() as folder:
            store, backend, window, policy, types = self._setup(folder)
            try:
                parked = Cart()
                parked.add(store.by_barcode("1"))
                self.assertEqual(parked.total, 55_000_00)             # chakana
                data = cart_to_dict(parked)
                policy.offer({"price_types": types, "default_price_type": "ulg", "price_policy_revision": "b"})
                self.assertEqual(backend.price_type_id, "ulg")
                cart, changed = restore_parked(backend, data)
                self.assertEqual(changed, 1)
                self.assertEqual(cart.total, 52_000_00)               # joriy (ulgurji) narx
                plan = PaymentPlan(cart.total)
                plan.add_cash(cart.total)
                backend.submit(cart, plan)
                payload = json.loads(store.pending()[0]["payload"])
                self.assertEqual(payload["price_type_id"], "ulg")
                self.assertEqual(payload["items"][0]["price"], 52_000_00)
            finally:
                policy.timer.stop()
                window.close()
                store.close()


class SaleQueueOnlyTest(unittest.TestCase):
    def test_checkout_never_waits_for_network_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "kassa.db"
            store = Store(path)
            store.replace_products(PRODUCTS)
            hub = FakeHub()
            backend = LiveBackend(hub, store, METHODS)
            cart = Cart()
            cart.add(store.by_barcode("4780001000017"), 1)
            plan = PaymentPlan(cart.total)
            plan.add_cash(cart.total)
            try:
                with patch.object(hub, "send_sale", side_effect=TimeoutError("unresponsive server")) as send:
                    backend.submit(cart, plan)
                    send.assert_not_called()
                row = store.pending()[0]
                uid = row["local_uuid"]
                payload = json.loads(row["payload"])
                self.assertEqual(payload["gross_total"], 300000)
                self.assertIn(uid[:8].upper(), backend.last_receipt_number)
            finally:
                store.close()
            reopened = Store(path)
            try:
                backend = LiveBackend(hub, reopened, METHODS)
                self.assertEqual(backend.flush(), 1)
                self.assertEqual(backend.flush(), 0)
                self.assertEqual([x["local_uuid"] for x in hub.received], [uid])
                self.assertEqual(reopened.pending_count(), 0)
            finally:
                reopened.close()


class ReturnTimezoneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_list_and_detail_match_local_history_across_midnight(self):
        from PySide6.QtWidgets import QLabel
        from . import history
        from .ui.dialogs import ReturnSaleListDialog, ReturnDetailDialog
        tz = timezone(timedelta(hours=5))
        real_datetime = datetime
        class LocalClock(datetime):
            @classmethod
            def fromisoformat(cls, value):
                parsed = real_datetime.fromisoformat(value)
                return cls(parsed.year, parsed.month, parsed.day, parsed.hour,
                           parsed.minute, parsed.second, tzinfo=parsed.tzinfo)

            def astimezone(self, zone=None):
                return super().astimezone(zone or tz)

        sale = {"created_at": "2026-09-29T21:21:00Z", "number": 1,
                "customer": "", "is_cash": True, "net_total": 300000,
                "shift": {"number": 1, "closed": False}, "items": []}
        with patch.object(history, "datetime", LocalClock):
            listing = ReturnSaleListDialog([sale])
            detail = ReturnDetailDialog(sale)
            try:
                labels = [w.text() for w in listing.findChildren(QLabel)]
                self.assertIn("02:21", labels)
                labels = [w.text() for w in detail.findChildren(QLabel)]
                self.assertIn("2026-09-30  02:21", labels)
            finally:
                listing.close(); detail.close()


class SessionEventsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_queued_old_rejection_cannot_log_out_resumed_cashier(self):
        import threading
        from types import SimpleNamespace
        from .session_events import SessionEvents
        hub = SimpleNamespace(session="before-resume")
        lost, renewed = [], []
        events = SessionEvents(hub, renewed.append, lost.append)
        thread = threading.Thread(target=lambda: events.lost.emit("expired", "before-resume"))
        thread.start(); thread.join()
        hub.session = "after-resume"
        self.app.processEvents()
        self.assertEqual(lost, [])
        events.renewed.emit("obsolete-renewal", "before-resume")
        self.assertEqual(renewed, [])
        events.renewed.emit("valid-renewal", "after-resume")
        self.assertEqual(renewed, ["valid-renewal"])
        events.lost.emit("revoked", "after-resume")
        self.assertEqual(lost, ["revoked"])

    def test_reply_after_logout_cannot_restore_session(self):
        from types import SimpleNamespace
        from .session_events import SessionEvents
        hub = SimpleNamespace(session="")
        renewed, lost = [], []
        events = SessionEvents(hub, renewed.append, lost.append)
        events.renewed.emit("old-renewal", "previous-login")
        events.lost.emit("old-error", "previous-login")
        self.assertEqual((renewed, lost), ([], []))


class WeightCommaTest(unittest.TestCase):
    """Vaznli tovar miqdori: vergul bilan kiloda terish (2026-10-06)."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, weight=True):
        from decimal import Decimal
        from types import SimpleNamespace
        from .ui.dialogs import QuantityDialog
        product = SimpleNamespace(name="kolbasa", price=5999000, is_weight=weight)
        return QuantityDialog(SimpleNamespace(product=product, quantity=Decimal("1")))

    def type(self, d, keys):
        for k in keys:
            if k == ",":
                d.on_comma()
            elif k == "<":
                d.on_backspace()
            else:
                d.on_digit(k)
        return d.quantity

    def test_vergulsiz_gramm_avvalgidek(self):
        from decimal import Decimal
        self.assertEqual(self.type(self.dialog(), "734"), Decimal("0.734"))
        self.assertEqual(self.type(self.dialog(), "1500"), Decimal("1.5"))

    def test_vergul_bilan_kilo(self):
        from decimal import Decimal
        d = self.dialog()
        self.assertEqual(self.type(d, "1,5"), Decimal("1.5"))
        self.assertEqual(d.display.text(), "1.500 kg")
        self.assertEqual(self.type(self.dialog(), "0,734"), Decimal("0.734"))
        self.assertEqual(self.type(self.dialog(), ",25"), Decimal("0.25"))      # boshida vergul = 0,
        self.assertEqual(self.type(self.dialog(), "12,"), Decimal("12"))        # 12 kg
        self.assertEqual(self.type(self.dialog(), "2,050"), Decimal("2.05"))

    def test_grammdan_mayda_va_ikkinchi_vergul_etiborsiz(self):
        from decimal import Decimal
        self.assertEqual(self.type(self.dialog(), "1,2345"), Decimal("1.234"))   # 4-xona olinmaydi
        self.assertEqual(self.type(self.dialog(), "1,,5"), Decimal("1.5"))
        self.assertEqual(self.type(self.dialog(), "1,5,7"), Decimal("1.57"))

    def test_nol_va_bosh_qiymat_saqlanmaydi(self):
        for keys in ("", ",", "0,", "0,000", "0"):
            self.assertIsNone(self.type(self.dialog(), keys), keys)

    def test_ochirish_vergulni_ham_ochiradi(self):
        from decimal import Decimal
        d = self.dialog()
        self.assertEqual(self.type(d, "1,5<<"), Decimal("0.001"))                # yana gramm: 1
        self.assertEqual(self.type(d, "50"), Decimal("0.15"))                    # 150 g

    def test_katta_gramm_sonidan_keyin_vergul_etiborsiz(self):
        from decimal import Decimal
        self.assertEqual(self.type(self.dialog(), "1500,5"), Decimal("15.005"))  # 15005 g — vergul olinmadi

    def test_donali_tovarda_vergul_yoq(self):
        from decimal import Decimal
        from .ui.keypad import Keypad
        d = self.dialog(weight=False)
        self.assertEqual(self.type(d, "3,5"), Decimal("35"))                     # vergul e'tiborsiz
        pads = d.findChildren(Keypad)
        self.assertEqual(len(pads), 1)
        from PySide6.QtWidgets import QPushButton
        texts = [b.text() for b in pads[0].findChildren(QPushButton)]
        self.assertNotIn(",", texts)
        vaznli = self.dialog()                                                   # oyna tirik tursin
        wpad = vaznli.findChildren(Keypad)[0]
        self.assertIn(",", [b.text() for b in wpad.findChildren(QPushButton)])

    def test_oyna_kassa_ekraniga_sigadi(self):
        d = self.dialog()
        d.adjustSize()
        self.assertLessEqual(d.sizeHint().height(), 700)                         # 1366x768 da ~720 px joy


class ManualKiloCommaTest(unittest.TestCase):
    """Kilo tovar QO'LDA qo'shilganda ham vergul chiqadi (2026-10-06).

    1.18.11 da vergul faqat «vaznli» belgili tovarda bor edi. Sevimli
    MoySklad'ida hamma birlik «шт» — ro'yxatdan bosib qo'shilgan kilo
    tovar donali bo'lib tushadi va kassir vergulni ko'rmasdi.
    """

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    KILO = dict(id=11, ms_id="ms-11", name="Uzum", price=13_990_00, code="00420")
    DONA = dict(id=12, ms_id="ms-12", name="Cola 1L", price=12_000_00, code="S00123")

    def product(self, **over):
        from .cart import Product
        return Product(**{**self.KILO, **over})

    def dialog(self, product, quantity="1"):
        from decimal import Decimal
        from .cart import Line
        from .ui.dialogs import QuantityDialog
        return QuantityDialog(Line(product=product, quantity=Decimal(quantity)))

    def type(self, d, keys):
        for k in keys:
            d.on_comma() if k == "," else d.on_digit(k)
        return d.quantity

    def keys(self, d):
        from PySide6.QtWidgets import QPushButton
        from .ui.keypad import Keypad
        pad, = d.findChildren(Keypad)
        return [b.text() for b in pad.findChildren(QPushButton)]

    def test_kilo_tovar_belgisi(self):
        from .cart import Product
        self.assertTrue(self.product().can_weigh)                                # kodi raqam
        self.assertTrue(self.product(code="S1", plu=77).can_weigh)               # tarozi PLU'si bor
        self.assertTrue(self.product(code="", is_weight=True).can_weigh)
        self.assertFalse(Product(**self.DONA).can_weigh)
        self.assertFalse(self.product(code="").can_weigh)
        self.assertFalse(self.product(code="00420A").can_weigh)

    def test_qolda_qoshilgan_kilo_tovarda_vergul_bor(self):
        from decimal import Decimal
        d = self.dialog(self.product())
        self.assertFalse(d.is_weight)                                            # katalogda vaznli emas
        self.assertIn(",", self.keys(d))
        self.assertEqual(self.type(d, "1,25"), Decimal("1.25"))
        self.assertEqual(d.display.text(), "1.250 kg")
        self.assertEqual(self.type(self.dialog(self.product()), ",5"), Decimal("0.5"))
        self.assertEqual(self.type(self.dialog(self.product()), "0,734"), Decimal("0.734"))

    def test_vergulsiz_butun_son_avvalgidek(self):
        """Vergulsiz son GRAMMGA aylanmaydi: 2 = 2 (avvalgi xatti-harakat)."""
        from decimal import Decimal
        d = self.dialog(self.product())
        self.assertEqual(self.type(d, "2"), Decimal("2"))
        self.assertEqual(d.display.text(), "2")
        self.assertEqual(self.type(self.dialog(self.product()), "10"), Decimal("10"))
        self.assertIn("000", self.keys(d))                                       # donali klaviatura joyida
        d.set_value(5)
        self.assertEqual(d.quantity, Decimal("5"))

    def test_donali_tovarda_vergul_yoq(self):
        from decimal import Decimal
        from .cart import Product
        d = self.dialog(Product(**self.DONA))
        self.assertNotIn(",", self.keys(d))
        self.assertEqual(self.type(d, "3,5"), Decimal("35"))                     # vergul e'tiborsiz

    def test_oyna_donali_oynadan_baland_emas(self):
        """Vergul tugmasi oynani o'stirmaydi — 1366x768 ekranga sig'ishi kerak."""
        from .cart import Product
        kilo = self.dialog(self.product())
        dona = self.dialog(Product(**self.DONA))
        kilo.adjustSize()
        dona.adjustSize()
        self.assertEqual(kilo.sizeHint().height(), dona.sizeHint().height())

    def test_kasr_qatorga_yangi_bosish_qoshilmaydi(self):
        """1,250 kg qatoridan keyin tovar yana bosilsa — yangi qator.

        Aks holda 2,250 bo'lib, kassir uni ikkinchi vazn bilan
        almashtiradi va birinchi tortish chekdan yo'qoladi."""
        from decimal import Decimal
        cart = Cart()
        p = self.product()
        cart.add(p)
        cart.set_quantity(0, Decimal("1.25"))
        cart.add(p)
        self.assertEqual([l.quantity for l in cart.lines], [Decimal("1.25"), Decimal("1")])
        cart.set_quantity(1, Decimal("0.8"))
        self.assertEqual(cart.gross_total, 1_748_750 + 1_119_200)                # 17 487,50 + 11 192

    def test_butun_miqdor_avvalgidek_birlashadi(self):
        from decimal import Decimal
        from .cart import Product
        cart = Cart()
        cart.add(self.product())
        cart.add(self.product())
        cart.add(Product(**self.DONA))
        cart.add(Product(**self.DONA))
        self.assertEqual([l.quantity for l in cart.lines], [Decimal("2"), Decimal("2")])

    def test_kassada_boshidan_oxirigacha(self):
        """Ro'yxatdan bosildi → qator bosildi → 1,25 terildi → serverga 1.25."""
        from decimal import Decimal
        from .hub import sale_payload
        from .ui.dialogs import QuantityDialog
        from .ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "kassa.db")
            store.replace_products(PRODUCTS + [{
                "id": 11, "ms_id": "ms-11", "name": "Uzum", "code": "00420",
                "barcode": "", "price": 13_990_00, "is_weight": False,
                "plu": None, "tracked": False, "stock": 50,
            }])
            backend = LiveBackend(FakeHub(), store, METHODS)
            window = MainWindow(backend)
            product, = [p for p in backend.search("Uzum") if p.id == 11]
            self.assertTrue(window._add_to_cart(product))
            d = QuantityDialog(window.cart.lines[0], window)
            self.assertEqual(self.type(d, "1,25"), Decimal("1.25"))
            window.cart.set_quantity(0, d.quantity)
            window.refresh()
            self.assertEqual(window.cart.total, 1_748_750)
            plan = PaymentPlan(total=window.cart.total)
            plan.add_cash(window.cart.total)
            payload = sale_payload(window.cart, plan, "u-1", "2026-10-06T10:00:00+05:00")
            self.assertEqual(payload["items"][0]["quantity"], "1.25")
            self.assertEqual(payload["items"][0]["total"], 1_748_750)
            store.close()


class ScanFocusTest(unittest.TestCase):
    """Skaner kodi doim shtrix-kod maydoniga tushsin (egasi, 2026-10-08).

    Kartani yoki chek qatorini bosgandan keyin fokus ro'yxatga o'tib
    qolardi: keyingi skaner kodi yo'qolar, kassir maydonni qo'l bilan
    bosishi kerak edi.
    """

    BARCODE = "4780001000017"                                                    # Buhanka S

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from .ui.main_window import MainWindow
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.folder.name) / "kassa.db")
        self.store.replace_products(PRODUCTS)
        self.backend = LiveBackend(FakeHub(), self.store, METHODS)
        self.window = MainWindow(self.backend)
        self.window.resize(1024, 768)
        self.window.show()
        self.window.activateWindow()
        self.settle()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.settle()
        self.store.close()
        self.folder.cleanup()

    def settle(self, ms=0):
        from PySide6.QtTest import QTest
        QTest.qWait(ms)
        for _ in range(5):
            self.app.processEvents()

    def focused(self):
        return self.app.focusWidget()

    def scan(self, code=None):
        """Skaner: raqamlar + Enter — fokusdagi joyga yoziladi."""
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        target = self.focused() or self.window
        QTest.keyClicks(target, code or self.BARCODE)
        QTest.keyClick(target, Qt.Key_Return)
        self.settle()

    def tap(self, view, row=0):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        r = view.visualItemRect(view.item(row))
        p = QPoint(r.left() + 30, r.top() + r.height() // 2)
        QTest.mousePress(view.viewport(), Qt.LeftButton, Qt.NoModifier, p)
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, Qt.NoModifier, p, 60)
        self.settle(250)

    def quantities(self):
        return [str(line.quantity) for line in self.window.cart.lines]

    def test_kartani_bosgandan_keyin_skaner_ishlaydi(self):
        w = self.window
        w.fill_catalog(self.backend.search("Buhanka"))
        self.settle()
        self.tap(w.catalog_list)
        self.assertEqual(self.quantities(), ["1"])                               # bosish ishlaydi
        self.assertIs(self.focused(), w.scan_input)
        self.scan()
        self.assertEqual(self.quantities(), ["2"])

    def test_qidirib_bosgandan_keyin_skaner_matnga_qoshilmaydi(self):
        from PySide6.QtTest import QTest
        w = self.window
        QTest.keyClicks(w.scan_input, "Buhanka")
        self.settle(400)                                                         # qidiruv 180 ms kutadi
        self.assertGreater(w.catalog_list.count(), 0)
        self.tap(w.catalog_list)
        self.assertEqual(self.quantities(), ["1"])
        self.assertGreater(w.catalog_list.count(), 0)                            # natija ekranda qoladi
        self.scan()
        self.assertEqual(self.quantities(), ["2"])
        self.assertEqual(w.scan_input.text(), "")

    def test_chek_qatoridan_keyin_skaner_ishlaydi(self):
        from PySide6.QtWidgets import QDialog
        from .ui.dialogs import QuantityDialog
        w = self.window
        self.scan()
        for result in (QDialog.Rejected, QDialog.Accepted):
            with patch.object(QuantityDialog, "exec", lambda self, r=result: r):
                self.tap(w.receipt_list)
            self.assertIs(self.focused(), w.scan_input, result)
            before = sum(int(q) for q in self.quantities())
            self.scan()
            self.assertEqual(sum(int(q) for q in self.quantities()), before + 1, result)

    def test_kassa_ekranida_faqat_maydon_fokus_oladi(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget
        w = self.window
        takers = [x for x in w.centralWidget().findChildren(QWidget)
                  if x.focusPolicy() != Qt.NoFocus]
        self.assertEqual(takers, [w.scan_input])

    def test_kirish_ekrani_fokusi_tegilmaydi(self):
        """Kirish ekrani (PIN) kassa oynasi USTIDA turadi — klaviatura unga
        yozadi, orqadagi shtrix-kod maydoniga emas."""
        from PySide6.QtTest import QTest
        from .ui.login_screen import LoginScreen
        screen = LoginScreen(self.window, "Shaxar 1", "kassa3")
        screen.setGeometry(self.window.rect())
        screen.show()
        screen.setFocus()
        self.settle()
        self.assertIs(self.focused(), screen)
        QTest.keyClicks(self.focused(), "1234")
        self.settle()
        self.assertIs(self.focused(), screen)
        self.assertEqual(self.window.scan_input.text(), "")
        screen.deleteLater()


def tearDownModule():
    """Testlar qoldirgan Qt oynalarini QApplication tirikligida yo'q qiladi.

    PySide6 6.12 (2026-10-08) da ota-onasiz dialoglar Python yopilayotganda
    tartibsiz o'chirilib, jarayon segfault bilan tugardi — testlarning
    hammasi OK bo'lsa ham CI yiqilardi.
    """
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    gc.collect()
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
